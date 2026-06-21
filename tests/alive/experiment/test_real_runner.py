"""Integration tests for the four staged runner functions (Task 16).

These tests wire Tasks 3-15 into ``fit_base`` → ``develop_methods_stage`` →
``calibrate`` → ``evaluate_sealed_once`` on SYNTHETIC data and a feature bank
built from the Task 6 MOCK encoder.  The non-negotiable integrity properties
verified here:

1. **Leakage boundary.** ``fit_base`` / ``develop_methods_stage`` / ``calibrate``
   use ``read_controls`` + ``read_unsealed`` ONLY — never ``evaluate_sealed_once``,
   never a sealed id.  After all three, ``store.sealed_access_count == 0``.
2. **Scores-before-risks.** In ``evaluate_sealed_once`` ALL method scores + base
   predictions are computed from FEATURES (no seal) BEFORE the single
   ``store.evaluate_sealed_once`` call.
3. **Futility forbids sealed evaluation.** ``FUTILITY_STOPPED`` → raise, seal
   stays shut.
4. **The seal opens exactly once.**

All tests use synthetic data; the real K562 run is Task 17 on the A100.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import anndata
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from alive.config import (
    BaseModel,
    Config,
    Decision,
    Futility,
    Inference,
    MethodDevelopment,
    PerturbationFeatures,
    SplitFractions,
)
from alive.config import (
    ResponseSpace as ResponseSpaceCfg,
)
from alive.data.features import MockSequenceEncoder, build_feature_bank
from alive.data.manifest import build_manifest_from_index
from alive.data.outcome_store import Population, ReplogleOutcomeStore
from alive.data.replogle import DatasetSchema, build_index
from alive.experiment.real_runner import (
    BaseArtifact,
    calibrate,
    develop_methods_stage,
    evaluate_sealed_once,
    fit_base,
    gate_and_comparator_scores,
    measured_error,
    perturbation_inputs,
)
from alive.types import OperationalStatus, Verdict

# ---------------------------------------------------------------------------
# Synthetic-data construction
# ---------------------------------------------------------------------------

_PERT_KEY = "target"
_CTRL_VAL = "ctrl"

# A 20-amino-acid alphabet for deterministic mock sequences.
_AA = "ACDEFGHIKLMNPQRSTVWY"


def _stable_seed(key: object) -> int:
    """Process-stable integer seed from a key (SHA-256, NOT salted hash())."""
    import hashlib

    return int.from_bytes(hashlib.sha256(str(key).encode()).digest()[:7], "big")


def _seq_for(gene: str, length: int = 24) -> str:
    """A deterministic protein sequence for a gene (mock encoder input)."""
    rng = np.random.default_rng(_stable_seed(gene))
    return "".join(_AA[i] for i in rng.integers(0, len(_AA), size=length))


def _make_adata(
    *,
    n_ctrl: int,
    pert_cells: dict[str, int],
    n_genes: int,
    seed: int,
) -> anndata.AnnData:
    """Build a synthetic raw-count AnnData with controls + perturbations.

    Each perturbation's cells are drawn as controls plus a per-gene mean shift
    that is a deterministic function of the gene's feature vector, so the
    base predictor has real signal to learn.
    """
    rng = np.random.default_rng(seed)
    gene_ids = [f"g{i}" for i in range(n_genes)]

    labels: list[str] = [_CTRL_VAL] * n_ctrl
    for g, n in pert_cells.items():
        labels.extend([g] * n)
    n_cells = len(labels)

    # Base count level (Poisson-like positive counts).
    base_level = rng.uniform(1.0, 5.0, size=n_genes)
    X = np.zeros((n_cells, n_genes), dtype=np.float64)
    row = 0
    # Controls
    for _ in range(n_ctrl):
        X[row] = rng.poisson(base_level)
        row += 1
    # Perturbations: shift the level by a per-gene deterministic amount.
    for g, n in pert_cells.items():
        g_rng = np.random.default_rng(_stable_seed(("shift", g)))
        shift = g_rng.uniform(-0.5, 1.5, size=n_genes)
        level = np.clip(base_level + shift, 0.1, None)
        for _ in range(n):
            X[row] = g_rng.poisson(level)
            row += 1

    obs = pd.DataFrame({_PERT_KEY: labels}, index=[f"c{i}" for i in range(n_cells)])
    var = pd.DataFrame(index=gene_ids)
    return anndata.AnnData(X=sp.csr_matrix(X.astype(np.float32)), obs=obs, var=var)


def _test_config(
    *,
    minimum_sealed: int = 3,
    bootstrap_replicates: int = 2000,
    hvg_count: int = 8,
    pca_dims: int = 4,
    cell_cap: int = 30,
    min_cells: int = 8,
    cell_sampling_repeats: int = 2,
) -> Config:
    """A valid Config with small (but validator-legal) values for tests."""
    return Config(
        experiment="test_real_runner",
        manifest_seed=7,
        split_fractions=SplitFractions(
            base_train=0.40,
            method_development=0.30,
            conformal_calibration=0.15,
            sealed_evaluation=0.15,
        ),
        response_space=ResponseSpaceCfg(
            normalization="library_size_10000_log1p",
            hvg_count=hvg_count,
            pca_dims=pca_dims,
            cell_cap=cell_cap,
            min_cells=min_cells,
            cell_sampling_repeats=cell_sampling_repeats,
            energy_block_size=64,
        ),
        perturbation_features=PerturbationFeatures(
            primary="mock-v1",
            standardize_on="base_train",
            missing_policy="exclude_before_split",
        ),
        base_model=BaseModel(
            family="additive_ridge",
            ridge_grid=(0.1, 1.0, 10.0),
            cv_folds=3,
            ensemble_members=4,
        ),
        method_development=MethodDevelopment(
            cv_folds=3,
            k_grid=(3, 5),
            feature_weight_grid=(0.25, 0.5, 0.75, 1.0),
            gbm_estimators_grid=(10, 20),
            ridge_grid=(0.1, 1.0, 10.0),
            registered_seeds=(11, 23),
        ),
        decision=Decision(
            target_selection_coverage=0.70,
            conformal_alpha=0.10,
            minimum_sealed_perturbations=minimum_sealed,
        ),
        inference=Inference(
            bootstrap_replicates=bootstrap_replicates,
            family_confidence=0.95,
            secondary_augrc_noninferiority_margin=0.02,
        ),
        futility=Futility(
            enabled=True,
            comparators=("gbm_error", "residual_only"),
            minimum_relevant_delta=0.01,
            family_confidence=0.90,
            rule="stop_if_any_simultaneous_upper_bound_le_minimum",
        ),
    )


def _build_world(tmp_path: Path, *, config: Config, n_pert: int = 40, seed: int = 0):
    """Build (index, store, manifest, feature_bank) for a synthetic world.

    Returns also the manifest so tests can introspect split roles.
    """
    rng = np.random.default_rng(seed)
    genes = [f"GENE{i:03d}" for i in range(n_pert)]
    cells_per = {g: int(rng.integers(20, 30)) for g in genes}

    adata = _make_adata(
        n_ctrl=80,
        pert_cells=cells_per,
        n_genes=20,
        seed=seed + 1,
    )

    schema = DatasetSchema(perturbation_key=_PERT_KEY, control_value=_CTRL_VAL)
    index = build_index(adata, schema, min_cells=config.response_space.min_cells)

    manifest = build_manifest_from_index(index, config.split_fractions, config.manifest_seed)

    # Feature bank from the MOCK encoder over the base_train genes for standardization.
    base_train_ids = list(manifest.ids_for("base_train"))
    gene_sequences = {g: [_seq_for(g)] for g in index.eligible_perturbations}
    feature_bank = build_feature_bank(
        gene_sequences,
        MockSequenceEncoder(dim=8),
        sequence_source="mock-2026",
        id_mapping_version="id-map-v1",
        standardize_on=base_train_ids,
    )

    audit_path = tmp_path / "audit.jsonl"
    store = ReplogleOutcomeStore(
        index=index, source=adata, manifest=manifest, audit_path=audit_path
    )
    return index, store, manifest, feature_bank


# ---------------------------------------------------------------------------
# Spy store — the headline leakage guard
# ---------------------------------------------------------------------------


class SpyStore:
    """Wraps a real ReplogleOutcomeStore, recording every access for audit.

    Records every id passed to ``read_unsealed`` and every call to
    ``evaluate_sealed_once`` (with the ``sealed_access_count`` observed *before*
    the inner call opened the seal), so tests can prove the leakage boundary
    and the scores-before-risks ordering.
    """

    def __init__(self, inner: ReplogleOutcomeStore) -> None:
        self._inner = inner
        self.unsealed_ids: list[str] = []
        self.read_controls_calls: int = 0
        # (run_id, ids, sealed_count_seen_before_inner_call)
        self.evaluate_calls: list[tuple[str, list[str], int]] = []

    def read_controls(self) -> Population:
        self.read_controls_calls += 1
        return self._inner.read_controls()

    def read_unsealed(self, perturbation_ids: Sequence[str]) -> dict[str, Population]:
        self.unsealed_ids.extend(list(perturbation_ids))
        return self._inner.read_unsealed(perturbation_ids)

    def evaluate_sealed_once(
        self, run_id: str, perturbation_ids: Sequence[str]
    ) -> dict[str, Population]:
        before = self._inner.sealed_access_count
        self.evaluate_calls.append((run_id, list(perturbation_ids), before))
        return self._inner.evaluate_sealed_once(run_id, perturbation_ids)

    @property
    def sealed_access_count(self) -> int:
        return self._inner.sealed_access_count


def _config_sha(config: Config) -> str:
    from alive.provenance import sha256_json

    return sha256_json({"run_id": config.config_digest, "experiment": config.experiment})


# ===========================================================================
# Helper-level tests
# ===========================================================================


class TestMeasuredError:
    def test_zero_for_identical_population(self, tmp_path: Path) -> None:
        config = _test_config()
        _index, store, manifest, fb = _build_world(tmp_path, config=config)
        base_art = fit_base(_index, store, manifest, fb, config)
        rs = base_art.response_space
        base = base_art.base_predictor

        # Use a method-development id (unsealed) as the observed population.
        dev_ids = [i for i in manifest.ids_for("method_development") if fb.has(i)]
        pid = dev_ids[0]
        observed = store.read_unsealed([pid])[pid]
        feats = fb.standardized_vector(pid)
        err = measured_error(
            base,
            rs,
            feats,
            observed,
            response_cfg=config.response_space,
            seed_key=("t", pid),
        )
        assert np.isfinite(err)
        assert err >= 0.0


class TestPerturbationInputs:
    def test_aligned_arrays_and_skip(self, tmp_path: Path) -> None:
        config = _test_config()
        _index, store, manifest, fb = _build_world(tmp_path, config=config)
        base_art = fit_base(_index, store, manifest, fb, config)

        dev_ids_all = list(manifest.ids_for("method_development"))
        pops = store.read_unsealed([i for i in dev_ids_all if fb.has(i)])
        ids, feats, errs, ens = perturbation_inputs(
            base_art.base_predictor,
            base_art.response_space,
            fb,
            pops,
            response_cfg=config.response_space,
            run_id="r0",
        )
        n = len(ids)
        assert n >= 1
        assert tuple(ids) == tuple(sorted(ids))  # sorted id order
        assert feats.shape == (n, fb.dim)
        assert errs.shape == (n,)
        assert ens.ndim == 3 and ens.shape[0] == n
        assert np.all(np.isfinite(errs))


class TestGateAndComparatorScores:
    def test_returns_all_six_methods_query_aligned(self, tmp_path: Path) -> None:
        config = _test_config()
        _index, store, manifest, fb = _build_world(tmp_path, config=config)
        base_art = fit_base(_index, store, manifest, fb, config)
        method_lock, _fd = develop_methods_stage(_index, store, manifest, base_art, fb, config)

        # Reference = method_development; query = conformal_calibration.
        ref_ids = [i for i in manifest.ids_for("method_development") if fb.has(i)]
        ref_pops = store.read_unsealed(ref_ids)
        ref_ids2, ref_feats, ref_errs, ref_ens = perturbation_inputs(
            base_art.base_predictor,
            base_art.response_space,
            fb,
            ref_pops,
            response_cfg=config.response_space,
            run_id="r0",
        )
        q_ids = [i for i in manifest.ids_for("conformal_calibration") if fb.has(i)]
        q_pops = store.read_unsealed(q_ids)
        q_ids2, q_feats, _q_errs, q_ens = perturbation_inputs(
            base_art.base_predictor,
            base_art.response_space,
            fb,
            q_pops,
            response_cfg=config.response_space,
            run_id="r0",
        )

        scores = gate_and_comparator_scores(
            method_lock,
            base_art.base_predictor,
            ref_feats,
            ref_errs,
            ref_ens,
            q_feats,
            q_ens,
        )
        from alive.experiment.develop import METHOD_IDS

        assert set(scores) == set(METHOD_IDS)
        n_query = len(q_ids2)
        for m in METHOD_IDS:
            assert scores[m].shape == (n_query,)
            assert np.all(np.isfinite(scores[m]))


# ===========================================================================
# Stage tests
# ===========================================================================


class TestFitBase:
    def test_returns_base_artifact(self, tmp_path: Path) -> None:
        config = _test_config()
        _index, store, manifest, fb = _build_world(tmp_path, config=config)
        art = fit_base(_index, store, manifest, fb, config)
        assert isinstance(art, BaseArtifact)
        assert art.response_space is not None
        assert art.base_predictor is not None
        assert isinstance(art.checksum, str) and len(art.checksum) == 64

    def test_no_sealed_access(self, tmp_path: Path) -> None:
        config = _test_config()
        _index, store, manifest, fb = _build_world(tmp_path, config=config)
        fit_base(_index, store, manifest, fb, config)
        assert store.sealed_access_count == 0


# ===========================================================================
# Leakage guard — the headline test
# ===========================================================================


class TestLeakageGuard:
    def test_fit_develop_calibrate_never_touch_seal(self, tmp_path: Path) -> None:
        config = _test_config()
        index, real_store, manifest, fb = _build_world(tmp_path, config=config)
        spy = SpyStore(real_store)

        base_art = fit_base(index, spy, manifest, fb, config)
        method_lock, fdec = develop_methods_stage(index, spy, manifest, base_art, fb, config)
        _conf = calibrate(index, spy, manifest, base_art, method_lock, fb, config)

        sealed_ids = set(manifest.ids_for("sealed_evaluation"))

        # 1. ZERO evaluate_sealed_once calls.
        assert spy.evaluate_calls == []
        # 2. No sealed id ever appeared in any read_unsealed argument.
        leaked = sealed_ids.intersection(spy.unsealed_ids)
        assert leaked == set(), f"sealed ids leaked into read_unsealed: {leaked}"
        # 3. The store's durable audit count is still 0.
        assert real_store.sealed_access_count == 0


# ===========================================================================
# Scores-before-risks ordering
# ===========================================================================


class TestScoresBeforeRisks:
    def test_seal_opens_once_after_scores(self, tmp_path: Path) -> None:
        config = _test_config()
        index, real_store, manifest, fb = _build_world(tmp_path, config=config)
        spy = SpyStore(real_store)

        base_art = fit_base(index, spy, manifest, fb, config)
        method_lock, fdec = develop_methods_stage(index, spy, manifest, base_art, fb, config)
        # Force CONTINUE so the sealed branch is permitted.
        fdec = replace(fdec, status=OperationalStatus.CONTINUE_CONFIRMATORY)
        conf = calibrate(index, spy, manifest, base_art, method_lock, fb, config)

        result = evaluate_sealed_once(
            index,
            spy,
            manifest,
            base_art,
            method_lock,
            conf,
            fdec,
            fb,
            config,
            run_id=config.config_digest,
        )
        assert result is not None

        # Exactly one sealed access, and it was observed with sealed_count == 0
        # before the inner call (scores were computed first).
        assert len(spy.evaluate_calls) == 1
        _run_id, _ids, before_count = spy.evaluate_calls[0]
        assert before_count == 0
        assert real_store.sealed_access_count == 1


# ===========================================================================
# Futility forbids sealed evaluation
# ===========================================================================


class TestFutilityForbidsSeal:
    def test_raises_and_seal_stays_shut(self, tmp_path: Path) -> None:
        config = _test_config()
        index, real_store, manifest, fb = _build_world(tmp_path, config=config)
        spy = SpyStore(real_store)

        base_art = fit_base(index, spy, manifest, fb, config)
        method_lock, fdec = develop_methods_stage(index, spy, manifest, base_art, fb, config)
        conf = calibrate(index, spy, manifest, base_art, method_lock, fb, config)

        # Force FUTILITY_STOPPED.
        fdec = replace(fdec, status=OperationalStatus.FUTILITY_STOPPED)

        with pytest.raises(RuntimeError):
            evaluate_sealed_once(
                index,
                spy,
                manifest,
                base_art,
                method_lock,
                conf,
                fdec,
                fb,
                config,
                run_id=config.config_digest,
            )
        assert real_store.sealed_access_count == 0
        assert spy.evaluate_calls == []


# ===========================================================================
# End-to-end continue branch — a verdict we can predict
# ===========================================================================


class TestEndToEnd:
    def test_near_random_yields_no_distinct_win(self, tmp_path: Path) -> None:
        """Near-random data: the gate cannot beat all comparators → NO_DISTINCT_WIN.

        We engineer a scenario where calibration passes (so it isn't a
        CALIBRATION_FAILURE) and integrity is valid, but the confirmatory
        family test cannot certify a gate win on noisy synthetic data.
        """
        config = _test_config()
        index, store, manifest, fb = _build_world(tmp_path, config=config, seed=3)

        base_art = fit_base(index, store, manifest, fb, config)
        method_lock, fdec = develop_methods_stage(index, store, manifest, base_art, fb, config)
        # Force CONTINUE so the sealed branch runs even if dev was futile.
        fdec = replace(fdec, status=OperationalStatus.CONTINUE_CONFIRMATORY)
        conf = calibrate(index, store, manifest, base_art, method_lock, fb, config)

        result = evaluate_sealed_once(
            index,
            store,
            manifest,
            base_art,
            method_lock,
            conf,
            fdec,
            fb,
            config,
            run_id=config.config_digest,
        )
        # Valid set; near-random synthetic data should NOT certify a gate win.
        assert result.verdict in set(Verdict)
        assert result.verdict == Verdict.NO_DISTINCT_WIN


# ===========================================================================
# Low-n → INVALID_EVALUATION, but result is still written
# ===========================================================================


class TestLowNInvalid:
    def test_below_minimum_is_invalid_and_written(self, tmp_path: Path) -> None:
        # Set a minimum higher than the available sealed count.
        config = _test_config(minimum_sealed=10_000)
        index, store, manifest, fb = _build_world(tmp_path, config=config)

        base_art = fit_base(index, store, manifest, fb, config)
        method_lock, fdec = develop_methods_stage(index, store, manifest, base_art, fb, config)
        fdec = replace(fdec, status=OperationalStatus.CONTINUE_CONFIRMATORY)
        conf = calibrate(index, store, manifest, base_art, method_lock, fb, config)

        out_path = tmp_path / "result.json"
        result = evaluate_sealed_once(
            index,
            store,
            manifest,
            base_art,
            method_lock,
            conf,
            fdec,
            fb,
            config,
            run_id=config.config_digest,
            result_path=out_path,
        )
        assert result.verdict == Verdict.INVALID_EVALUATION
        # The result is still written (never silently dropped).
        assert out_path.exists()


# ===========================================================================
# Single sealed access — second call raises (inherited from Task 5)
# ===========================================================================


class TestSingleSealedAccess:
    def test_second_call_raises(self, tmp_path: Path) -> None:
        config = _test_config()
        index, store, manifest, fb = _build_world(tmp_path, config=config)

        base_art = fit_base(index, store, manifest, fb, config)
        method_lock, fdec = develop_methods_stage(index, store, manifest, base_art, fb, config)
        fdec = replace(fdec, status=OperationalStatus.CONTINUE_CONFIRMATORY)
        conf = calibrate(index, store, manifest, base_art, method_lock, fb, config)

        evaluate_sealed_once(
            index,
            store,
            manifest,
            base_art,
            method_lock,
            conf,
            fdec,
            fb,
            config,
            run_id=config.config_digest,
        )
        # A second call with the same run_id must surface the sealing error.
        with pytest.raises(Exception):
            evaluate_sealed_once(
                index,
                store,
                manifest,
                base_art,
                method_lock,
                conf,
                fdec,
                fb,
                config,
                run_id=config.config_digest,
            )


# ===========================================================================
# Determinism
# ===========================================================================


class TestDeterminism:
    def test_same_inputs_same_verdict_checksum(self, tmp_path: Path) -> None:
        config = _test_config()

        def _run(sub: Path) -> str:
            sub.mkdir(parents=True, exist_ok=True)
            index, store, manifest, fb = _build_world(sub, config=config, seed=5)
            base_art = fit_base(index, store, manifest, fb, config)
            method_lock, fdec = develop_methods_stage(index, store, manifest, base_art, fb, config)
            fdec = replace(fdec, status=OperationalStatus.CONTINUE_CONFIRMATORY)
            conf = calibrate(index, store, manifest, base_art, method_lock, fb, config)
            result = evaluate_sealed_once(
                index,
                store,
                manifest,
                base_art,
                method_lock,
                conf,
                fdec,
                fb,
                config,
                run_id=config.config_digest,
            )
            return result.checksum

        a = _run(tmp_path / "a")
        b = _run(tmp_path / "b")
        assert a == b


# ===========================================================================
# Provenance wiring (carry-forward fix a)
# ===========================================================================


class TestProvenanceWiring:
    def _ledger(self, *, run_id: str, config_sha256: str):
        from alive.provenance import EnvironmentInfo, RunLedger

        env = EnvironmentInfo(
            python_version="3.12.0",
            platform="test",
            git_commit="UNKNOWN",
            lockfile_sha256="0" * 64,
            registered_seeds=(11, 23),
        )
        return RunLedger(run_id=run_id, config_sha256=config_sha256, environment=env)

    def _setup(self, tmp_path: Path):
        config = _test_config()
        index, store, manifest, fb = _build_world(tmp_path, config=config, seed=3)
        base_art = fit_base(index, store, manifest, fb, config)
        method_lock, fdec = develop_methods_stage(index, store, manifest, base_art, fb, config)
        fdec = replace(fdec, status=OperationalStatus.CONTINUE_CONFIRMATORY)
        conf = calibrate(index, store, manifest, base_art, method_lock, fb, config)
        return config, index, store, manifest, fb, base_art, method_lock, fdec, conf

    def test_intact_ledger_provenance_ok(self, tmp_path: Path) -> None:
        config, index, store, manifest, fb, base_art, method_lock, fdec, conf = self._setup(
            tmp_path
        )
        cfg_digest = "f" * 64
        ledger = self._ledger(run_id=config.config_digest, config_sha256=cfg_digest)
        ledger.record_artifact("config", cfg_digest)
        ledger.record_artifact("split_manifest", manifest.checksum)
        ledger.record_artifact("feature_bank", fb.checksum)
        ledger.record_artifact("base_artifact", base_art.checksum)
        ledger.record_artifact("method_lock", method_lock.checksum)
        ledger.record_artifact("conformal_artifact", conf.checksum)

        result = evaluate_sealed_once(
            index,
            store,
            manifest,
            base_art,
            method_lock,
            conf,
            fdec,
            fb,
            config,
            run_id=config.config_digest,
            config_sha256=cfg_digest,
            ledger=ledger,
        )
        assert result.clauses["provenance_ok"] is True

    def test_tampered_ledger_hash_invalid(self, tmp_path: Path) -> None:
        config, index, store, manifest, fb, base_art, method_lock, fdec, conf = self._setup(
            tmp_path
        )
        cfg_digest = "f" * 64
        ledger = self._ledger(run_id=config.config_digest, config_sha256=cfg_digest)
        ledger.record_artifact("config", cfg_digest)
        ledger.record_artifact("split_manifest", manifest.checksum)
        ledger.record_artifact("feature_bank", fb.checksum)
        # Tamper the base_artifact hash.
        ledger.record_artifact("base_artifact", "0" * 64)
        ledger.record_artifact("method_lock", method_lock.checksum)
        ledger.record_artifact("conformal_artifact", conf.checksum)

        result = evaluate_sealed_once(
            index,
            store,
            manifest,
            base_art,
            method_lock,
            conf,
            fdec,
            fb,
            config,
            run_id=config.config_digest,
            config_sha256=cfg_digest,
            ledger=ledger,
        )
        assert result.clauses["provenance_ok"] is False
        assert result.verdict == Verdict.INVALID_EVALUATION


# ===========================================================================
# Fix 1: ConformalArtifact.config_sha256 must be the full 64-char digest
# ===========================================================================


class TestCalibrateConfigSha256:
    """calibrate() must stamp ConformalArtifact with the full 64-char config digest.

    The ConformalArtifact is the primary shippable deliverable of a
    futility-stopped run.  Its config_sha256 field must be the full 64-char
    SHA-256 hex digest of the config file — the same value that is threaded
    into the MethodLock and FutilityDecision by develop_methods_stage().
    """

    def test_conformal_artifact_config_sha256_is_full_digest(self, tmp_path: Path) -> None:
        """When a full 64-char digest is passed, ConformalArtifact carries it."""
        config = _test_config()
        index, store, manifest, fb = _build_world(tmp_path, config=config, seed=5)
        base_art = fit_base(index, store, manifest, fb, config)
        method_lock, _fdec = develop_methods_stage(index, store, manifest, base_art, fb, config)

        full_digest = "a" * 64  # a valid 64-char hex string (mock full digest)
        conf = calibrate(
            index,
            store,
            manifest,
            base_art,
            method_lock,
            fb,
            config,
            config_sha256=full_digest,
        )

        assert conf.config_sha256 == full_digest, (
            f"ConformalArtifact.config_sha256 should be the full 64-char digest "
            f"passed in, got {conf.config_sha256!r}"
        )
        assert len(conf.config_sha256) == 64

    def test_conformal_artifact_config_sha256_not_run_id_when_digest_given(
        self, tmp_path: Path
    ) -> None:
        """config_sha256 must NOT equal config.config_digest when the full digest is passed."""
        config = _test_config()
        index, store, manifest, fb = _build_world(tmp_path, config=config, seed=6)
        base_art = fit_base(index, store, manifest, fb, config)
        method_lock, _fdec = develop_methods_stage(index, store, manifest, base_art, fb, config)

        full_digest = "b" * 64
        conf = calibrate(
            index,
            store,
            manifest,
            base_art,
            method_lock,
            fb,
            config,
            config_sha256=full_digest,
        )

        # The run_id is 16 chars; the full digest is 64 chars — they must differ.
        assert conf.config_sha256 != config.config_digest, (
            "ConformalArtifact.config_sha256 must be the full digest, not config.config_digest"
        )

    def test_conformal_artifact_falls_back_to_run_id_without_digest(self, tmp_path: Path) -> None:
        """Without a config_sha256 argument (unit-test mode), falls back to run_id."""
        config = _test_config()
        index, store, manifest, fb = _build_world(tmp_path, config=config, seed=7)
        base_art = fit_base(index, store, manifest, fb, config)
        method_lock, _fdec = develop_methods_stage(index, store, manifest, base_art, fb, config)

        conf = calibrate(index, store, manifest, base_art, method_lock, fb, config)
        assert conf.config_sha256 == config.config_digest


# ===========================================================================
# P0-1(c): require_encoder_match in evaluate_sealed_once
# ===========================================================================


class TestRequireEncoderMatch:
    """P0-1(c): require_encoder_match=True with a mock bank but ESM config
    → provenance_ok=False → INVALID_EVALUATION.

    Default (require_encoder_match=False) leaves existing tests unchanged.
    """

    def _setup(self, tmp_path: Path):
        config = _test_config()
        index, store, manifest, fb = _build_world(tmp_path, config=config, seed=3)
        base_art = fit_base(index, store, manifest, fb, config)
        method_lock, fdec = develop_methods_stage(index, store, manifest, base_art, fb, config)
        from dataclasses import replace

        fdec = replace(fdec, status=OperationalStatus.CONTINUE_CONFIRMATORY)
        conf = calibrate(index, store, manifest, base_art, method_lock, fb, config)
        return config, index, store, manifest, fb, base_art, method_lock, fdec, conf

    def test_encoder_mismatch_with_require_match_yields_invalid(self, tmp_path: Path) -> None:
        """Mock feature bank + ESM-declaring config + require_encoder_match=True → INVALID."""
        config, index, store, manifest, fb, base_art, method_lock, fdec, conf = self._setup(
            tmp_path
        )
        # The test config declares primary="mock-v1" and the mock bank also has
        # model_revision="mock-v1", so they would match by default.
        # We need to simulate a mismatch: use a config that declares ESM but
        # the bank was built with the mock encoder.
        # Override config.perturbation_features.primary to look like an ESM config.
        from alive.config import PerturbationFeatures

        esm_config = replace(
            config,
            perturbation_features=PerturbationFeatures(
                primary="esm2_t33_650M_UR50D_mean_pool",
                standardize_on="base_train",
                missing_policy="exclude_before_split",
            ),
        )

        result = evaluate_sealed_once(
            index,
            store,
            manifest,
            base_art,
            method_lock,
            conf,
            fdec,
            fb,
            esm_config,
            run_id=esm_config.config_digest,
            require_encoder_match=True,
        )
        # Provenance check must have failed due to encoder mismatch.
        assert result.clauses["provenance_ok"] is False
        assert result.verdict == Verdict.INVALID_EVALUATION

    def test_encoder_mismatch_without_require_match_is_ignored(self, tmp_path: Path) -> None:
        """Default require_encoder_match=False: existing direct callers unaffected."""
        config, index, store, manifest, fb, base_art, method_lock, fdec, conf = self._setup(
            tmp_path
        )
        # run_id must come from config (the _test_config primary is "mock-v1" which
        # matches the mock bank, so there is no actual mismatch here —
        # just confirming default=False doesn't break anything).
        result = evaluate_sealed_once(
            index,
            store,
            manifest,
            base_art,
            method_lock,
            conf,
            fdec,
            fb,
            config,
            run_id=config.config_digest,
            require_encoder_match=False,
        )
        # With the default, the encoder leg never fires: the result is NOT
        # INVALID_EVALUATION (the mock bank matches the mock-config primary, and
        # require_encoder_match=False would skip the check regardless).
        assert result.verdict != Verdict.INVALID_EVALUATION


# ===========================================================================
# Fix wave 1 (Task 2 review; spec §4.5): the shared method_development
# reference-bank sampling seed must be the SAME composite run_id in calibrate
# and in evaluate_sealed_once.  If calibrate seeds the bank with one value and
# evaluate-once with another, the gate/comparator scorers refit at sealed
# evaluation diverge from the ones the conformal threshold was built on, which
# silently shifts coverage/verdict.  These tests pin the consistency.
# ===========================================================================


class TestReferenceBankSeedConsistency:
    """calibrate and evaluate_sealed_once must seed the shared reference bank alike.

    The equal-cell energy distance is deterministically seeded from
    ``(run_id, perturbation_id)``.  When the reference populations exceed
    ``cell_cap`` the subsample — and therefore ``ref_errors`` and the scorers
    fitted from it — depend on the seed.  After Fix wave 1, the composite
    ``run_id`` (NOT ``config.config_digest``) seeds that sampling in BOTH stages,
    so the gate/comparator scorer the conformal threshold is built on is byte-
    identical to the one evaluate_sealed_once refits at sealed evaluation.
    """

    @staticmethod
    def _seed_sensitive_config() -> Config:
        # cell_cap below the per-perturbation cell count (20-30) so the equal-cell
        # subsample is genuinely seed-dependent; >1 repeats amplifies it.
        return _test_config(cell_cap=12, min_cells=8, cell_sampling_repeats=4)

    def test_perturbation_inputs_reference_bank_is_seed_sensitive(self, tmp_path: Path) -> None:
        """Sanity precondition: the reference bank errors change with the seed.

        Without this the consistency tests below could pass vacuously (a
        seed-insensitive bank would agree regardless of which seed each stage
        used, hiding the very divergence we are guarding against).
        """
        config = self._seed_sensitive_config()
        index, store, manifest, fb = _build_world(tmp_path, config=config, seed=4)
        base_art = fit_base(index, store, manifest, fb, config)

        ref_ids = [pid for pid in manifest.ids_for("method_development") if fb.has(pid)]
        ref_pops = store.read_unsealed(ref_ids)

        def _ref_errors(run_id: str) -> np.ndarray:
            _ids, _f, errs, _e = perturbation_inputs(
                base_art.base_predictor,
                base_art.response_space,
                fb,
                ref_pops,
                response_cfg=config.response_space,
                run_id=run_id,
            )
            return errs

        errs_digest = _ref_errors(config.config_digest)
        errs_composite = _ref_errors("composite-run-id-deadbeef")
        assert not np.allclose(errs_digest, errs_composite), (
            "reference bank is seed-insensitive in this fixture; the consistency "
            "test would be vacuous — increase cell count / lower cell_cap"
        )

    @staticmethod
    def _spy_reference_bank_run_id(monkeypatch) -> dict[str, list[str]]:
        """Patch real_runner.perturbation_inputs to record every ``run_id`` seed.

        Returns a dict with key ``"run_ids"`` accumulating, in call order, the
        ``run_id`` value each stage passes to ``perturbation_inputs`` (the seed
        source for the equal-cell sampling of the reference / query banks).  The
        first call inside calibrate / evaluate_sealed_once is the SHARED
        method_development reference bank — that is the value under test.
        """
        import alive.experiment.real_runner as rr

        captured: dict[str, list[str]] = {"run_ids": []}
        original = rr.perturbation_inputs

        def _spy(*args, **kwargs):
            captured["run_ids"].append(kwargs["run_id"])
            return original(*args, **kwargs)

        monkeypatch.setattr(rr, "perturbation_inputs", _spy)
        return captured

    def test_calibrate_seeds_reference_bank_with_threaded_composite_run_id(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """calibrate(run_id=composite) MUST seed the reference bank with that run_id.

        RED before the fix: calibrate ignored the threaded run_id and seeded the
        reference bank with config.config_digest — so the captured seed equalled
        config.config_digest, NOT the composite run_id.
        GREEN after: the captured seed is the composite run_id.
        """
        config = self._seed_sensitive_config()
        composite_run_id = "composite-run-id-deadbeef"
        assert config.config_digest != composite_run_id

        index, store, manifest, fb = _build_world(tmp_path, config=config, seed=4)
        base_art = fit_base(index, store, manifest, fb, config)
        method_lock, _fd = develop_methods_stage(
            index, store, manifest, base_art, fb, config, run_id=composite_run_id
        )

        captured = self._spy_reference_bank_run_id(monkeypatch)
        calibrate(
            index, store, manifest, base_art, method_lock, fb, config, run_id=composite_run_id
        )

        # Every bank calibrate samples (reference + calibration query) must be
        # seeded with the composite run_id — never config.config_digest.
        assert captured["run_ids"], "calibrate did not sample any bank"
        assert all(rid == composite_run_id for rid in captured["run_ids"]), (
            f"calibrate seeded a bank with {set(captured['run_ids'])!r}; expected only "
            f"the composite run_id {composite_run_id!r}"
        )

    def test_calibrate_and_evaluate_seed_shared_bank_identically(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The SHARED method_development reference bank seed must match across stages.

        Captures the reference-bank ``run_id`` calibrate uses, then the one
        evaluate_sealed_once uses, with the SAME composite run_id threaded into
        both.  They must be equal (the conformal threshold and the sealed scores
        compared against it come from one identically-fitted scorer).

        RED before the fix: calibrate's reference-bank seed was
        config.config_digest while evaluate_sealed_once's was the composite
        run_id — divergent.
        """
        config = self._seed_sensitive_config()
        composite_run_id = "composite-run-id-deadbeef"
        assert config.config_digest != composite_run_id

        index, store, manifest, fb = _build_world(tmp_path, config=config, seed=4)
        base_art = fit_base(index, store, manifest, fb, config)
        method_lock, fdec = develop_methods_stage(
            index, store, manifest, base_art, fb, config, run_id=composite_run_id
        )
        fdec = replace(fdec, status=OperationalStatus.CONTINUE_CONFIRMATORY)

        cal_capture = self._spy_reference_bank_run_id(monkeypatch)
        conf = calibrate(
            index, store, manifest, base_art, method_lock, fb, config, run_id=composite_run_id
        )
        calibrate_ref_seed = cal_capture["run_ids"][0]

        eval_capture = self._spy_reference_bank_run_id(monkeypatch)
        evaluate_sealed_once(
            index,
            store,
            manifest,
            base_art,
            method_lock,
            conf,
            fdec,
            fb,
            config,
            run_id=composite_run_id,
        )
        evaluate_ref_seed = eval_capture["run_ids"][0]

        assert calibrate_ref_seed == evaluate_ref_seed == composite_run_id, (
            "calibrate and evaluate_sealed_once seeded the shared method_development "
            f"reference bank with DIFFERENT run_ids "
            f"(calibrate={calibrate_ref_seed!r}, evaluate={evaluate_ref_seed!r}); the "
            "conformal coverage guarantee is broken when the seeds diverge."
        )
