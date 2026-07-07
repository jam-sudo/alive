"""Tests for alive.compose.seed_variability — COMPOSE D2 Task 3 (fold jobs).

Written FIRST per TDD. ``build_fold_job`` assembles a controller-side, fold-scoped
fit job whose worker payload trains ONLY on one gene-disjoint OOF fold's TRAIN combo
pairs: the held-out TEST pairs and the cross-group EXCLUDED pairs must be fully
absent from both the fold-scoped fit-role artifact and the payload, or the OOF
seed-variability measurement leaks.

SYNTHETIC-ONLY: pure numpy + a tiny synthetic source; opens NO seal, reads NO sealed
outcome, imports NO gears/cpa. Development calibration outcomes only.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import random
import warnings
from pathlib import Path

import numpy as np
import pytest
from scipy import sparse

from alive.compose.baseline_subprocess import _REQUIRED_KEYS
from alive.compose.baselines_combo import BaselineAdapter
from alive.compose.fit_role import (
    FitRoleExtraction,
    generate_fit_role_artifact,
)
from alive.compose.phase2a import (
    DevelopmentOutcomeStore,
    OutcomeAccessAudit,
    Phase2aInputs,
)
from alive.compose.response import fit_response_space, verify_response_artifact
from alive.compose.seed_variability import (
    DEVELOPMENT_SEED_VARIABILITY_FILENAME,
    DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT,
    CoverageReport,
    FoldExecutionError,
    FoldExecutionRecord,
    FoldExecutionResult,
    FoldJob,
    FoldJobError,
    SeedAssemblyError,
    SeedComparatorSummary,
    SeedVariabilityContractError,
    SeedVariabilityPreflightError,
    SeedVariabilityReport,
    SeedVariabilityReportError,
    SeedVariabilityStatus,
    assemble_seed_scalar,
    bind_development_seed_variability,
    build_fold_job,
    development_seed_variability,
    restrict_development_store,
    run_fold_job,
    verify_seed_variability_for_preflight,
)
from alive.compose.select import (
    OOFFoldManifest,
    build_gene_disjoint_folds,
)
from alive.provenance import (
    EnvironmentInfo,
    RunLedger,
    sha256_file,
)

_RAW = "raw-shared-d2"
_SPLIT_SEED = 11
_N_FOLDS = 3
_P = 4  # response dim


def _canon(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a.encode("utf-8") <= b.encode("utf-8") else (b, a)


@contextlib.contextmanager
def _ignore_anndata_str_index_warning():
    """Silence anndata's implicit-str-index warning at fit-role artifact creation.

    ``generate_fit_role_artifact`` (``alive.compose.fit_role``, production code out
    of scope for this test module) builds its ``obs`` DataFrame without an explicit
    string index, so ``anndata.AnnData.__init__`` always auto-transforms the
    default integer ``RangeIndex`` to str, emitting an
    ``ImplicitModificationWarning`` on every call. This fixture module calls that
    path (directly, and transitively via ``build_fold_job`` /
    ``development_seed_variability``) far more often than other test modules do,
    so the identical pre-existing warning becomes disproportionate noise here.
    Narrowly scoped to this one warning category, at exactly the call sites that
    reach it — no test assertion or semantics are affected.
    """
    import anndata as ad

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ad.ImplicitModificationWarning)
        yield


def _fixture(tmp_path: Path):
    """Full synthetic D2 fixture: base fit-role artifact + manifest + inputs + store.

    6 perturbation genes G0..G5, all calibration genes; the 15 within-gene pairs are
    all calibration pairs. A 3-fold gene-disjoint layout partitions every pair into
    TRAIN / TEST / EXCLUDED. The base fit-role artifact carries control + one single
    per gene + one combo cell per calibration pair, so the fold extractor can carve a
    train-only subset out of it.
    """
    rng = np.random.default_rng(7)
    pert_genes = [f"G{i}" for i in range(6)]
    gene_index = {g: i for i, g in enumerate(pert_genes)}
    cal_pairs_id: list[tuple[str, str]] = []
    cal_pairs_idx: list[tuple[int, int]] = []
    for i in range(6):
        for j in range(i + 1, 6):
            cal_pairs_id.append(_canon(pert_genes[i], pert_genes[j]))
            cal_pairs_idx.append((i, j))
    n_pairs = len(cal_pairs_id)  # 15

    eps_cal = rng.normal(size=(n_pairs, _P))
    additive_cal = rng.normal(size=(n_pairs, _P))
    eps_a = eps_cal + 0.01 * rng.normal(size=(n_pairs, _P))
    eps_b = eps_cal + 0.01 * rng.normal(size=(n_pairs, _P))
    delta_by_gene = {g: rng.normal(size=_P) for g in pert_genes}
    z = rng.normal(size=(6, 4))

    # --- base fit-role artifact (control + singles + ALL calibration combos) -----
    n_control, n_single = 12, 6
    n_combo = n_pairs
    n_cells = n_control + n_single + n_combo
    n_tx = _P + 1  # transcriptome genes
    counts = rng.integers(1, 50, size=(n_cells, n_tx)).astype(np.float64)
    X = sparse.csr_matrix(counts)
    gene_order = [f"T{i}" for i in range(n_tx)]
    control_idx = np.arange(0, n_control)
    single_idx = np.arange(n_control, n_control + n_single)
    space = fit_response_space(
        X,
        control_idx=control_idx,
        eligible_single_idx=single_idx,
        n_hvg=n_tx,
        pca_dim=_P,
        seed=1,
    )
    control_mean = space.project(X, control_idx).mean(axis=0)
    _, _, combined = verify_response_artifact(space, control_mean)

    rows = (
        [(f"c{i}", "control", "control") for i in range(n_control)]
        + [(f"s{i}", "singles", pert_genes[i % 6]) for i in range(n_single)]
        + [(f"m{i}", "combo_calibration", f"{a}_{b}") for i, (a, b) in enumerate(cal_pairs_id)]
    )
    extraction = FitRoleExtraction(
        X=X,
        var_names=tuple(gene_order),
        rows=tuple(rows),
        role_counts={"control": n_control, "singles": n_single, "combo_calibration": n_combo},
        raw_data_sha256=_RAW,
        pair_manifest_sha256="pm",
        eligibility_hash="elig",
    )
    with _ignore_anndata_str_index_warning():
        base_spec = generate_fit_role_artifact(
            extraction=extraction,
            out_path=str(tmp_path / "base_fit_role.h5ad"),
            config_sha256="cfg",
            data_card_sha256="dc",
            calibration_gene_set_hash="cg",
            generator_code_sha256="gen",
            writer_environment_sha256="env",
        )
    response_artifact = {"response_space": space, "control_mean": control_mean}

    # --- OOF fold manifest (the exact single-call folds) -------------------------
    folds = build_gene_disjoint_folds(cal_pairs_idx, n_genes=6, n_folds=_N_FOLDS, seed=_SPLIT_SEED)
    manifest = OOFFoldManifest.from_folds(
        folds, pair_ids=cal_pairs_id, n_genes=6, n_folds=_N_FOLDS, split_seed=_SPLIT_SEED
    )

    inputs = Phase2aInputs(
        run_id="run-fixture",
        gene_index=gene_index,
        factors_by_k={4: z},
        cal_idx_pairs=cal_pairs_idx,
        cal_pair_ids=cal_pairs_id,
        additive_cal=additive_cal,
        eps_split_a=eps_a,
        eps_split_b=eps_b,
        k_total_grid=[4],
        lambda_grid=[0.0],
        n_genes=6,
        n_folds=_N_FOLDS,
        seed=_SPLIT_SEED,
        uncovered_tolerance=1.0,
        sealed_double_pair_ids=(),
        sealed_single_pair_ids=(),
        delta_by_gene=delta_by_gene,
        model_factories={},
        response_dim=_P,
        response_space_checksum=combined,
        factor_checksum="zf",
        manifest_checksum="mani",
        environment_checksum="env",
        registered_seeds=(11, 23, 37),
        data_card_checksum="dck",
        raw_data_checksum="rdk",
        sequence_mapping_checksum="smk",
    )
    store = DevelopmentOutcomeStore(
        combo_calibration_eps=eps_cal,
        combo_calibration_pair_ids=cal_pairs_id,
        access_audit=OutcomeAccessAudit(
            role="combo_calibration",
            manifest_checksum="mani",
            source_checksum="src",
            sealed_access_count=0,
            source_kind="synthetic_fixture",
        ),
    )
    fold_dir = tmp_path / "folds"
    return {
        "inputs": inputs,
        "store": store,
        "manifest": manifest,
        "response_artifact": response_artifact,
        "gene_order": gene_order,
        "base_spec": base_spec,
        "fold_dir": str(fold_dir),
        "cal_pairs_id": cal_pairs_id,
        "additive_cal": additive_cal,
        "eps_cal": eps_cal,
    }


def _build(fx, *, method="gears", seed=23, fold_index=0) -> FoldJob:
    with _ignore_anndata_str_index_warning():
        return build_fold_job(
            method=method,
            seed=seed,
            fold_index=fold_index,
            oof_manifest=fx["manifest"],
            inputs=fx["inputs"],
            outcome_store=fx["store"],
            response_artifact=fx["response_artifact"],
            base_fit_role_spec=fx["base_spec"],
            fold_artifact_dir=fx["fold_dir"],
            gene_order=fx["gene_order"],
            raw_data_sha256=_RAW,
        )


# --------------------------------------------------------------------------- #
# payload schema: exactly the required keys, no fold metadata leakage
# --------------------------------------------------------------------------- #
def test_payload_key_set_is_exactly_required_keys(tmp_path):
    fx = _fixture(tmp_path)
    job = _build(fx)
    assert isinstance(job, FoldJob)
    assert set(job.payload) == set(_REQUIRED_KEYS)
    # fold metadata lives ONLY on the FoldJob, never inside the payload.
    for meta in ("fold_index", "test_pair_ids", "excluded_pair_ids", "method"):
        assert meta not in job.payload


def test_fold_metadata_lives_only_on_the_job(tmp_path):
    fx = _fixture(tmp_path)
    rec = fx["manifest"].folds[0]
    job = _build(fx, fold_index=0)
    assert job.method == "gears"
    assert job.seed == 23
    assert job.fold_index == 0
    assert job.test_pair_ids == rec.test_pair_ids
    assert job.excluded_pair_ids == rec.excluded_pair_ids
    assert job.fold_manifest_checksum == fx["manifest"].manifest_checksum
    assert job.fit_role_artifact_sha256.startswith("sha256:")
    assert Path(job.fit_role_artifact_path).is_file()


# --------------------------------------------------------------------------- #
# leakage: held-out / excluded combos absent from payload AND fold artifact
# --------------------------------------------------------------------------- #
def test_train_payload_has_no_heldout_or_excluded_pair(tmp_path):
    fx = _fixture(tmp_path)
    rec = fx["manifest"].folds[0]
    job = _build(fx, fold_index=0)
    payload_pairs = {tuple(p) for p in job.payload["calibration_pair_ids"]}
    assert payload_pairs == set(rec.train_pair_ids)
    forbidden = set(rec.test_pair_ids) | set(rec.excluded_pair_ids)
    assert payload_pairs.isdisjoint(forbidden)
    # calibration_delta has exactly one target row per train pair (no held-out rows)
    assert len(job.payload["calibration_delta"]) == len(rec.train_pair_ids)


def test_fold_fit_role_artifact_excludes_heldout_and_excluded_combos(tmp_path):
    import anndata as ad

    fx = _fixture(tmp_path)
    rec = fx["manifest"].folds[0]
    job = _build(fx, fold_index=0)
    adata = ad.read_h5ad(job.fit_role_artifact_path)
    tokens = [str(p) for p in adata.obs["perturbation"]]

    def _pair(tok: str) -> tuple[str, str]:
        a, b = tok.split("_", 1)
        return _canon(a, b)

    combos = {_pair(t) for t in tokens if "_" in t and t != "control"}
    assert combos == set(rec.train_pair_ids)
    forbidden = set(rec.test_pair_ids) | set(rec.excluded_pair_ids)
    assert combos.isdisjoint(forbidden)
    # control + single universes are intact (the artifact already re-validates as a
    # legitimate fit-role artifact inside build_fold_job against the fold's own
    # calibration/sealed sets, so a smuggled sealed/excluded cell fails closed there).
    roles = {str(r) for r in adata.obs["role"]}
    assert roles == {"control", "singles", "combo_calibration"}
    singles = {tok for tok, r in zip(tokens, adata.obs["role"]) if str(r) == "singles"}
    assert singles <= set(fx["inputs"].delta_by_gene)


# --------------------------------------------------------------------------- #
# alignment of payload target rows with train pair IDs
# --------------------------------------------------------------------------- #
def test_every_payload_target_row_aligns_with_its_train_pair(tmp_path):
    fx = _fixture(tmp_path)
    rec = fx["manifest"].folds[0]
    job = _build(fx, fold_index=0)
    train_pos = list(rec.train_pair_positions)
    payload_pairs = [tuple(p) for p in job.payload["calibration_pair_ids"]]
    assert tuple(payload_pairs) == rec.train_pair_ids
    expected_delta = fx["additive_cal"][train_pos] + fx["eps_cal"][train_pos]
    np.testing.assert_allclose(
        np.asarray(job.payload["calibration_delta"], dtype=float), expected_delta
    )


# --------------------------------------------------------------------------- #
# oof_folds labels: covered -> outer test-fold index, uncovered -> n_folds sentinel
# --------------------------------------------------------------------------- #
def test_oof_folds_labels_match_the_manifest(tmp_path):
    fx = _fixture(tmp_path)
    manifest = fx["manifest"]
    rec = manifest.folds[0]
    job = _build(fx, fold_index=0)
    labels = list(job.payload["oof_folds"])
    assert len(labels) == len(rec.train_pair_ids)
    test_fold_of: dict[tuple[str, str], int] = {}
    for r in manifest.folds:
        for pid in r.test_pair_ids:
            test_fold_of[pid] = r.fold_index
    covered = set(manifest.covered_pair_ids)
    seen_covered = seen_sentinel = False
    for pid, label in zip(rec.train_pair_ids, labels):
        if pid in covered:
            assert label == test_fold_of[pid] < manifest.n_folds
            seen_covered = True
        else:
            assert label == manifest.n_folds
            seen_sentinel = True
    # this fixture is constructed so BOTH label kinds are exercised
    assert seen_covered and seen_sentinel


# --------------------------------------------------------------------------- #
# store restriction: audit identity preserved, checksum recomputed over subset
# --------------------------------------------------------------------------- #
def test_store_restriction_preserves_audit_and_recomputes_checksum(tmp_path):
    fx = _fixture(tmp_path)
    store = fx["store"]
    rec = fx["manifest"].folds[0]
    positions = list(rec.train_pair_positions)
    restricted = restrict_development_store(store, positions=positions, pair_ids=rec.train_pair_ids)
    assert restricted.combo_calibration_pair_ids == rec.train_pair_ids
    assert restricted.combo_calibration_eps.shape[0] == len(positions)
    np.testing.assert_array_equal(
        restricted.combo_calibration_eps,
        np.asarray(store.combo_calibration_eps)[positions],
    )
    # audit identity is preserved bit-for-bit; the dev store has no sealed role.
    assert restricted.access_audit == store.access_audit
    assert restricted.access_audit.sealed_access_count == 0
    # content checksum is recomputed over the SUBSET (differs from the full store).
    assert len(restricted.content_checksum) == 64
    assert restricted.content_checksum != store.content_checksum


# --------------------------------------------------------------------------- #
# a manifest/input/store alignment mismatch fails BEFORE any artifact creation
# --------------------------------------------------------------------------- #
def test_store_input_mismatch_fails_before_artifact_creation(tmp_path):
    fx = _fixture(tmp_path)
    # a store whose pair order differs from inputs.cal_pair_ids (still a VALID dev
    # store on its own) must be rejected before any fold artifact is written.
    cal = fx["cal_pairs_id"]
    eps = fx["eps_cal"]
    reversed_pairs = tuple(reversed(cal))
    reversed_eps = eps[::-1]
    bad_store = DevelopmentOutcomeStore(
        combo_calibration_eps=reversed_eps,
        combo_calibration_pair_ids=reversed_pairs,
        access_audit=fx["store"].access_audit,
    )
    with pytest.raises(FoldJobError):
        build_fold_job(
            method="cpa",
            seed=11,
            fold_index=0,
            oof_manifest=fx["manifest"],
            inputs=fx["inputs"],
            outcome_store=bad_store,
            response_artifact=fx["response_artifact"],
            base_fit_role_spec=fx["base_spec"],
            fold_artifact_dir=fx["fold_dir"],
            gene_order=fx["gene_order"],
            raw_data_sha256=_RAW,
        )
    # no fold artifact was written (fail-closed BEFORE creation)
    assert list(Path(fx["fold_dir"]).glob("*.h5ad")) == []


def test_manifest_input_mismatch_fails_closed(tmp_path):
    fx = _fixture(tmp_path)
    # a manifest built for a different split seed disagrees with inputs.seed.
    import dataclasses

    other = OOFFoldManifest.from_folds(
        build_gene_disjoint_folds(
            fx["inputs"].cal_idx_pairs, n_genes=6, n_folds=_N_FOLDS, seed=_SPLIT_SEED + 1
        ),
        pair_ids=fx["cal_pairs_id"],
        n_genes=6,
        n_folds=_N_FOLDS,
        split_seed=_SPLIT_SEED + 1,
    )
    assert isinstance(other, OOFFoldManifest)
    with pytest.raises(FoldJobError):
        build_fold_job(
            method="gears",
            seed=23,
            fold_index=0,
            oof_manifest=other,
            inputs=fx["inputs"],
            outcome_store=fx["store"],
            response_artifact=fx["response_artifact"],
            base_fit_role_spec=fx["base_spec"],
            fold_artifact_dir=fx["fold_dir"],
            gene_order=fx["gene_order"],
            raw_data_sha256=_RAW,
        )
    del dataclasses


# --------------------------------------------------------------------------- #
# write-once: a second identical (method, seed, fold) job fails closed
# --------------------------------------------------------------------------- #
def test_fold_artifact_is_write_once(tmp_path):
    fx = _fixture(tmp_path)
    _build(fx, method="gears", seed=23, fold_index=0)
    with pytest.raises(FoldJobError):
        _build(fx, method="gears", seed=23, fold_index=0)


def test_distinct_jobs_get_distinct_fold_artifacts(tmp_path):
    fx = _fixture(tmp_path)
    a = _build(fx, method="gears", seed=23, fold_index=0)
    b = _build(fx, method="cpa", seed=37, fold_index=1)
    assert a.fit_role_artifact_path != b.fit_role_artifact_path
    assert Path(a.fit_role_artifact_path).is_file()
    assert Path(b.fit_role_artifact_path).is_file()


# =========================================================================== #
# Task 4 — execute one (method, seed, fold) job + per-seed covered reassembly
# =========================================================================== #
#
# A deterministic stub backend modelled on the Task-2/Task-3 seam
# (``spawn`` / ``configure_payload`` / ``predict`` / ``provenance_manifest``);
# it imports NO gears/cpa. Its ``provenance_manifest`` mirrors the real
# ``SubprocessBaselineBackend`` post-predict shape: real digests bound to the
# configured payload / worker bytes / requested pair IDs — never a
# ``{method, seed}`` synthesis — so a fabricated checkpoint hash cannot match.


class _StubFoldBackend:
    """Deterministic, seam-compatible stand-in for a GEARS/CPA subprocess backend.

    Every mutable-state method mirrors ``SubprocessBaselineBackend``: ``spawn``
    returns a fresh, unconfigured child (registered so a test can inspect it),
    ``configure_payload`` takes a detached JSON snapshot, ``predict`` runs a
    caller-supplied ``pred_fn`` exactly once and records the requested pairs, and
    ``provenance_manifest`` exposes real payload/worker/checkpoint/request digests
    (only in its post-predict form once ``predict`` has run).
    """

    def __init__(self, *, seed, pred_fn, registry, worker_bytes=b"stub-worker-v1"):
        self.seed = int(seed)
        self._pred_fn = pred_fn
        self._registry = registry
        self._worker_bytes = worker_bytes
        self._payload = None
        self._predicted_pairs = None
        self.predict_calls = 0

    def spawn(self, *, seed):
        child = type(self)(
            seed=seed,
            pred_fn=self._pred_fn,
            registry=self._registry,
            worker_bytes=self._worker_bytes,
        )
        self._registry.setdefault("spawned", []).append(child)
        return child

    @property
    def is_available(self):
        return True

    def configure_payload(self, payload):
        self._payload = json.loads(json.dumps(dict(payload), sort_keys=True))
        self._predicted_pairs = None

    def predict(self, context, pair_ids, response_dim):
        if self._payload is None:
            raise RuntimeError("stub predict called before configure_payload")
        self.predict_calls += 1
        self._predicted_pairs = [tuple(p) for p in pair_ids]
        return self._pred_fn(self._payload, self._predicted_pairs, int(response_dim))

    @staticmethod
    def _digest(text):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @property
    def provenance_manifest(self):
        if self._payload is None:
            raise RuntimeError("stub provenance requested before configure_payload")
        payload_sha = self._digest(json.dumps(self._payload, sort_keys=True))
        worker_sha = hashlib.sha256(self._worker_bytes).hexdigest()
        manifest = {
            "worker_sha256": worker_sha,
            "payload_sha256": payload_sha,
            "seed": self.seed,
        }
        if self._predicted_pairs is not None:
            request_sha = self._digest(
                json.dumps([list(p) for p in self._predicted_pairs], sort_keys=True)
            )
            manifest["execution_manifest"] = {
                "checkpoint_sha256": self._digest("checkpoint:" + payload_sha),
                "combined_request_sha256": request_sha,
                "worker_sha256": worker_sha,
            }
        return manifest


def _delta_truth_by_pair(fx) -> dict[tuple[str, str], np.ndarray]:
    """Development delta ``additive_cal + combo_calibration_eps``, pair-aligned."""
    cal = fx["cal_pairs_id"]
    add = np.asarray(fx["additive_cal"], dtype=float)
    eps = np.asarray(fx["eps_cal"], dtype=float)
    return {tuple(cal[i]): add[i] + eps[i] for i in range(len(cal))}


def _exact_truth_pred_fn(truth):
    def _fn(payload, pair_ids, response_dim):
        return {p: np.asarray(truth[p], dtype=float) for p in pair_ids}

    return _fn


def _adapter(pred_fn, *, name="gears"):
    registry: dict[str, list] = {}
    backend = _StubFoldBackend(seed=0, pred_fn=pred_fn, registry=registry)
    return BaselineAdapter(name=name, backend=backend), registry, backend


def _run(fx, adapter, *, method, seed, fold_index):
    job = _build(fx, method=method, seed=seed, fold_index=fold_index)
    result = run_fold_job(
        adapter,
        job,
        _P,
        pair_manifest_checksum=fx["inputs"].manifest_checksum,
        response_space_checksum=fx["inputs"].response_space_checksum,
    )
    return job, result


def _run_all_folds(fx, adapter, *, method="gears", seed=23):
    return [_run(fx, adapter, method=method, seed=seed, fold_index=fi)[1] for fi in range(_N_FOLDS)]


# --------------------------------------------------------------------------- #
# run_fold_job: fresh backend, predicts the test pairs exactly once
# --------------------------------------------------------------------------- #
def test_run_fold_job_spawns_fresh_backend_and_predicts_once(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    adapter, registry, parent = _adapter(_exact_truth_pred_fn(truth))
    job, result = _run(fx, adapter, method="gears", seed=23, fold_index=0)

    assert isinstance(result, FoldExecutionResult)
    # exactly one fresh child backend, seeded to the job seed, is NOT the parent.
    assert len(registry["spawned"]) == 1
    child = registry["spawned"][0]
    assert child is not parent
    assert child.seed == job.seed == 23
    # the fold's held-out test pairs were predicted exactly once.
    assert child.predict_calls == 1
    assert child._predicted_pairs == list(job.test_pair_ids)
    # predictions are keyed by the fold's test pair IDs.
    assert set(result.predictions) == set(job.test_pair_ids)
    for vec in result.predictions.values():
        assert np.asarray(vec).shape == (_P,)


def test_run_fold_job_result_carries_job_identity(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    adapter, _registry, _parent = _adapter(_exact_truth_pred_fn(truth), name="cpa")
    job, result = _run(fx, adapter, method="cpa", seed=37, fold_index=1)
    assert result.method == "cpa"
    assert result.seed == 37
    assert result.fold_index == 1
    assert result.test_pair_ids == job.test_pair_ids


# --------------------------------------------------------------------------- #
# checksums are the REAL post-predict provenance digests, not a {method,seed} hash
# --------------------------------------------------------------------------- #
def test_run_fold_job_captures_real_provenance_checksums(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    adapter, registry, _parent = _adapter(_exact_truth_pred_fn(truth), name="cpa")
    job, result = _run(fx, adapter, method="cpa", seed=37, fold_index=1)

    child = registry["spawned"][0]
    manifest = child.provenance_manifest
    exec_manifest = manifest["execution_manifest"]
    # every captured digest equals exactly what the backend manifest reports.
    assert result.worker_sha256 == manifest["worker_sha256"]
    assert result.payload_sha256 == manifest["payload_sha256"]
    assert result.checkpoint_sha256 == exec_manifest["checkpoint_sha256"]
    assert result.request_sha256 == exec_manifest["combined_request_sha256"]
    # a fabricated {method, seed} checkpoint hash would NOT match the real one.
    fabricated = hashlib.sha256(f"{job.method}:{job.seed}".encode("utf-8")).hexdigest()
    assert result.checkpoint_sha256 != fabricated
    assert len(result.checkpoint_sha256) == 64


def test_run_fold_job_requires_post_predict_manifest(tmp_path):
    # a backend whose provenance never reaches the post-predict form (no
    # execution_manifest) must fail closed rather than fabricate checksums.
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)

    class _NoManifestBackend(_StubFoldBackend):
        @property
        def provenance_manifest(self):
            m = dict(super().provenance_manifest)
            m.pop("execution_manifest", None)  # simulate a pre-predict manifest
            return m

    registry: dict[str, list] = {}
    backend = _NoManifestBackend(seed=0, pred_fn=_exact_truth_pred_fn(truth), registry=registry)
    adapter = BaselineAdapter(name="gears", backend=backend)
    job = _build(fx, method="gears", seed=23, fold_index=0)
    with pytest.raises(FoldExecutionError):
        run_fold_job(
            adapter,
            job,
            _P,
            pair_manifest_checksum=fx["inputs"].manifest_checksum,
            response_space_checksum=fx["inputs"].response_space_checksum,
        )


# --------------------------------------------------------------------------- #
# per-seed reassembly: covered order, independent of fold execution order
# --------------------------------------------------------------------------- #
def test_reassembly_is_covered_order_independent_of_fold_order(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    adapter, _registry, _parent = _adapter(_exact_truth_pred_fn(truth))
    results = _run_all_folds(fx, adapter)

    shuffled = list(results)
    random.Random(5).shuffle(shuffled)
    pred_by_pair, scalar = assemble_seed_scalar(
        shuffled,
        manifest=fx["manifest"],
        delta_truth_by_pair=truth,
        response_dim=_P,
    )
    # covered pairs appear EXACTLY once, in the manifest's covered order.
    assert tuple(pred_by_pair) == fx["manifest"].covered_pair_ids
    assert set(pred_by_pair) == set(fx["manifest"].covered_pair_ids)
    # WIRING known-answer (not stochastic-stability evidence): a stub predicting
    # exactly the development delta yields a per-seed scalar of 0.
    assert scalar == pytest.approx(0.0)


def test_seed_scalar_equals_hand_computed_mean_pair_mse(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    offset = 0.5

    def _offset_pred_fn(payload, pair_ids, response_dim):
        return {p: np.asarray(truth[p], dtype=float) + offset for p in pair_ids}

    adapter, _registry, _parent = _adapter(_offset_pred_fn)
    results = _run_all_folds(fx, adapter)
    _pred_by_pair, scalar = assemble_seed_scalar(
        results,
        manifest=fx["manifest"],
        delta_truth_by_pair=truth,
        response_dim=_P,
    )
    # every covered pair has per-pair MSE mean(offset**2) == offset**2, so the
    # mean over the fixed covered set is offset**2.
    assert scalar == pytest.approx(offset**2)


# --------------------------------------------------------------------------- #
# a covered-set defect makes the whole seed FAIL (raises)
# --------------------------------------------------------------------------- #
def _valid_results(fx, truth):
    """One FoldExecutionResult per manifest fold, predicting that fold's tests."""
    results = []
    for rec in fx["manifest"].folds:
        preds = {tuple(p): np.asarray(truth[tuple(p)], dtype=float) for p in rec.test_pair_ids}
        results.append(
            FoldExecutionResult(
                method="gears",
                seed=23,
                fold_index=int(rec.fold_index),
                test_pair_ids=rec.test_pair_ids,
                predictions=preds,
                worker_sha256="w" * 64,
                payload_sha256="p" * 64,
                checkpoint_sha256="c" * 64,
                request_sha256="r" * 64,
            )
        )
    return results


@pytest.mark.parametrize("defect", ["missing", "duplicate", "extra", "nonfinite", "dim"])
def test_covered_set_defect_fails_the_seed(tmp_path, defect):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    results = _valid_results(fx, truth)
    covered = fx["manifest"].covered_pair_ids
    target = covered[0]

    if defect == "missing":
        for r in results:
            if target in r.predictions:
                del r.predictions[target]
                break
    elif defect == "duplicate":
        for r in results:
            if target not in r.predictions:
                r.predictions[target] = np.asarray(truth[target], dtype=float)
                break
    elif defect == "extra":
        results[0].predictions[("ZZnot", "ZZcovered")] = np.zeros(_P)
    elif defect == "nonfinite":
        for r in results:
            if target in r.predictions:
                r.predictions[target] = np.full(_P, np.inf)
                break
    elif defect == "dim":
        for r in results:
            if target in r.predictions:
                r.predictions[target] = np.zeros(_P + 1)
                break

    with pytest.raises(SeedAssemblyError):
        assemble_seed_scalar(
            results,
            manifest=fx["manifest"],
            delta_truth_by_pair=truth,
            response_dim=_P,
        )


def test_valid_results_assemble_cleanly_before_corruption(tmp_path):
    # guards the defect suite: the uncorrupted baseline assembles without error.
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    pred_by_pair, scalar = assemble_seed_scalar(
        _valid_results(fx, truth),
        manifest=fx["manifest"],
        delta_truth_by_pair=truth,
        response_dim=_P,
    )
    assert tuple(pred_by_pair) == fx["manifest"].covered_pair_ids
    assert scalar == pytest.approx(0.0)


# =========================================================================== #
# Task 5 — report containers + development_seed_variability orchestration entry
# =========================================================================== #
#
# The seed loop refits ONLY {gears, cpa}; the deterministic single-shot roster is
# RECORDED but never entered. Deterministic seam-compatible stub adapters are used
# throughout (no gears/cpa import). Opens NO seal (development delta only).

import dataclasses  # noqa: E402

from alive.compose.config2 import load_compose_phase2_config  # noqa: E402
from alive.compose.outcome_store import ComposeOutcomeStore  # noqa: E402
from alive.compose.phase2b import (  # noqa: E402
    SeedVariabilityPreflightInputs,
    _preaccess_seed_variability,
)
from alive.compose.provenance2 import PROTOCOL  # noqa: E402

_DETERMINISTIC = {
    "l1_bilinear_identifiable",
    "l2_saturation",
    "l3_hypernetwork",
    "id_only",
    "additive",
    "no_change",
    "perturbation_mean",
}


def _config(**overrides):
    """Real preregistered config, relaxed to match the synthetic fixture.

    The fixture's ``inputs.uncovered_tolerance`` is ``1.0`` (its 3-fold/6-gene
    layout leaves an 0.8 uncovered fraction), so the config's tolerance is relaxed
    to ``1.0`` for the config↔inputs equality gate. Everything else (split_seed=11,
    oof_folds=3, registered_seeds=(11, 23, 37)) already matches the fixture.
    """
    cfg = load_compose_phase2_config("configs/compose_k562_v1_phase2.yaml")
    cfg = dataclasses.replace(cfg, uncovered_tolerance=1.0)
    if overrides:
        cfg = dataclasses.replace(cfg, **overrides)
    return cfg


def _seed_from_payload(payload) -> int:
    return int(payload["seed"])


def _adapters(pred_fn, *, cpa_pred_fn=None):
    """A ``{gears, cpa}`` adapter roster wrapping spawnable stub backends."""
    gears, _rg, _bg = _adapter(pred_fn, name="gears")
    cpa, _rc, _bc = _adapter(cpa_pred_fn or pred_fn, name="cpa")
    return {"gears": gears, "cpa": cpa}


def _entry(fx, adapters, config, **overrides):
    kwargs = dict(
        inputs=fx["inputs"],
        development_outcome_store=fx["store"],
        oof_manifest=fx["manifest"],
        baseline_adapters=adapters,
        config=config,
        response_artifact=fx["response_artifact"],
        fit_role_spec=fx["base_spec"],
        gene_order=fx["gene_order"],
        raw_data_sha256=_RAW,
    )
    kwargs.update(overrides)
    with _ignore_anndata_str_index_warning():
        return development_seed_variability(**kwargs)


# --------------------------------------------------------------------------- #
# store-type gate: a ComposeOutcomeStore / object / dict / path raises BEFORE work
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "bad_store",
    [
        ComposeOutcomeStore.__new__(ComposeOutcomeStore),  # the SEAL store, rejected
        {"combo_calibration_eps": [], "combo_calibration_pair_ids": []},  # arbitrary dict
        np.zeros((3, _P)),  # arbitrary array
        "artifacts/dev_outcome_store.h5ad",  # a path
        object(),  # arbitrary object
    ],
)
def test_store_type_gate_rejects_non_development_store(tmp_path, bad_store):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    adapters = _adapters(_exact_truth_pred_fn(truth))
    with pytest.raises(SeedVariabilityContractError):
        _entry(fx, adapters, _config(), development_outcome_store=bad_store)


# --------------------------------------------------------------------------- #
# all-seeds-success -> COMPLETE; roster / seed order recorded exactly
# --------------------------------------------------------------------------- #
def test_all_seeds_success_is_complete(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    adapters = _adapters(_exact_truth_pred_fn(truth))
    report = _entry(fx, adapters, _config())

    assert isinstance(report, SeedVariabilityReport)
    assert report.status is SeedVariabilityStatus.COMPLETE
    assert report.protocol == PROTOCOL == "COMPOSE-K562-v1"
    assert report.run_id == fx["inputs"].run_id
    assert report.registered_seeds == (11, 23, 37)
    by_method = {s.method: s for s in report.summaries}
    assert set(by_method) == {"gears", "cpa"}
    for summary in by_method.values():
        # each stochastic method lists all three seeds, in registered order.
        assert tuple(summary.oof_mse_by_seed) == (11, 23, 37)
        for value in summary.oof_mse_by_seed.values():
            assert value == pytest.approx(0.0)
        assert summary.failed_seeds == ()


# --------------------------------------------------------------------------- #
# deterministic roster is RECORDED but never entered into the seed loop
# --------------------------------------------------------------------------- #
def test_deterministic_roster_recorded_but_not_in_seed_loop(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    report = _entry(fx, _adapters(_exact_truth_pred_fn(truth)), _config())
    assert set(report.deterministic_roster) == _DETERMINISTIC
    summarized = {s.method for s in report.summaries}
    assert summarized == {"gears", "cpa"}
    assert summarized.isdisjoint(_DETERMINISTIC)


# --------------------------------------------------------------------------- #
# one stub raising for seed 23 -> INCOMPLETE; seed 23 scrubbed + NOT dropped
# --------------------------------------------------------------------------- #
def test_one_failed_seed_is_incomplete_and_scrubbed(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)

    def _fail_seed_23(payload, pair_ids, response_dim):
        if _seed_from_payload(payload) == 23:
            raise RuntimeError("stub backend crash carrying secret=hunter2")
        return {p: np.asarray(truth[p], dtype=float) for p in pair_ids}

    report = _entry(fx, _adapters(_fail_seed_23), _config())
    assert report.status is SeedVariabilityStatus.INCOMPLETE
    # the seed is NOT dropped from the roster.
    assert report.registered_seeds == (11, 23, 37)
    for summary in report.summaries:
        assert 23 in summary.failed_seeds
        # scrubbed: only the class name, never the message/data.
        assert summary.failure_class_by_seed[23] == "RuntimeError"
        assert "hunter2" not in repr(summary.failure_class_by_seed)
        # successful seeds are still summarized; the failed seed is absent from them.
        assert 11 in summary.oof_mse_by_seed
        assert 37 in summary.oof_mse_by_seed
        assert 23 not in summary.oof_mse_by_seed


# --------------------------------------------------------------------------- #
# sample_std uses ddof=1 (hand-checked on three known per-seed scalars)
# --------------------------------------------------------------------------- #
def test_sample_std_is_ddof_one(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    offset_by_seed = {11: 1.0, 23: 2.0, 37: 3.0}  # -> scalars 1.0, 4.0, 9.0

    def _offset(payload, pair_ids, response_dim):
        off = offset_by_seed[_seed_from_payload(payload)]
        return {p: np.asarray(truth[p], dtype=float) + off for p in pair_ids}

    report = _entry(fx, _adapters(_offset), _config())
    assert report.status is SeedVariabilityStatus.COMPLETE
    scalars = [1.0, 4.0, 9.0]
    for summary in report.summaries:
        assert list(summary.oof_mse_by_seed.values()) == pytest.approx(scalars)
        assert summary.mean == pytest.approx(float(np.mean(scalars)))
        assert summary.sample_std == pytest.approx(float(np.std(scalars, ddof=1)))
        # ddof=1 differs from the population std -> guards against ddof=0.
        assert summary.sample_std != pytest.approx(float(np.std(scalars, ddof=0)))
        assert summary.minimum == pytest.approx(1.0)
        assert summary.maximum == pytest.approx(9.0)
        assert summary.value_range == pytest.approx(8.0)


def test_sample_std_zero_with_single_successful_seed(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)

    def _only_seed_11(payload, pair_ids, response_dim):
        if _seed_from_payload(payload) != 11:
            raise RuntimeError("crash")
        return {p: np.asarray(truth[p], dtype=float) for p in pair_ids}

    report = _entry(fx, _adapters(_only_seed_11), _config())
    assert report.status is SeedVariabilityStatus.INCOMPLETE
    for summary in report.summaries:
        assert tuple(summary.oof_mse_by_seed) == (11,)
        assert summary.sample_std == 0.0  # ddof=1 with <2 successful seeds


# --------------------------------------------------------------------------- #
# whole-call failures: manifest/config mismatch RAISES (not INCOMPLETE)
# --------------------------------------------------------------------------- #
def test_config_manifest_mismatch_raises_whole_call(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    adapters = _adapters(_exact_truth_pred_fn(truth))
    # config.split_seed disagrees with the manifest/inputs split seed -> whole-call.
    with pytest.raises(SeedVariabilityContractError):
        _entry(fx, adapters, _config(split_seed=99))


def test_adapter_roster_must_be_exactly_gears_cpa(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    only_gears = {"gears": _adapter(_exact_truth_pred_fn(truth), name="gears")[0]}
    with pytest.raises(SeedVariabilityContractError):
        _entry(fx, only_gears, _config())


def test_coverage_above_tolerance_is_incomplete(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    # tighten BOTH inputs and config tolerance below the fixture's 0.8 uncovered
    # fraction so coverage falls outside tolerance -> INCOMPLETE (not a raise).
    tight_inputs = dataclasses.replace(fx["inputs"], uncovered_tolerance=0.5)
    fx["inputs"] = tight_inputs
    report = _entry(fx, _adapters(_exact_truth_pred_fn(truth)), _config(uncovered_tolerance=0.5))
    assert report.status is SeedVariabilityStatus.INCOMPLETE
    assert report.coverage.uncovered_fraction > report.coverage.uncovered_tolerance


# --------------------------------------------------------------------------- #
# report provenance + self-excluding checksum round-trip
# --------------------------------------------------------------------------- #
def test_report_binds_provenance_and_records(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    report = _entry(fx, _adapters(_exact_truth_pred_fn(truth)), _config())
    assert report.oof_manifest_checksum == fx["manifest"].manifest_checksum
    assert report.response_space_checksum == fx["inputs"].response_space_checksum
    assert report.base_fit_role_artifact_sha256 == fx["base_spec"].sha256
    assert report.dev_store_content_checksum == fx["store"].content_checksum
    assert isinstance(report.coverage, CoverageReport)
    assert all(isinstance(s, SeedComparatorSummary) for s in report.summaries)
    # every (method, seed, fold) job contributes a fold-scoped artifact checksum:
    # 2 methods * 3 seeds * 3 folds = 18.
    assert len(report.fold_fit_role_artifact_sha256s) == 2 * 3 * _N_FOLDS
    assert all(s.startswith("sha256:") for s in report.fold_fit_role_artifact_sha256s)
    # one FoldExecutionRecord per successfully executed fold (all succeed here).
    assert len(report.fold_execution_records) == 2 * 3 * _N_FOLDS
    rec = report.fold_execution_records[0]
    assert isinstance(rec, FoldExecutionRecord)
    assert rec.worker_identity_sha256 in report.worker_locks
    assert len(rec.predictions_sha256) == 64


def test_report_checksum_round_trips(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    report = _entry(fx, _adapters(_exact_truth_pred_fn(truth)), _config())
    assert len(report.report_checksum) == 64
    path = tmp_path / "seed_variability_report.json"
    report.write_once(path)
    loaded = SeedVariabilityReport.load(path)
    assert loaded.report_checksum == report.report_checksum
    assert loaded.to_dict() == report.to_dict()
    # write-once: a second write to the same path fails closed.
    with pytest.raises(SeedVariabilityReportError):
        report.write_once(path)


def test_tampered_report_fails_closed_on_load(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    report = _entry(fx, _adapters(_exact_truth_pred_fn(truth)), _config())
    path = tmp_path / "report.json"
    report.write_once(path)
    data = json.loads(path.read_text())
    data["status"] = "COMPLETE" if data["status"] == "INCOMPLETE" else "INCOMPLETE"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(data))
    with pytest.raises(SeedVariabilityReportError):
        SeedVariabilityReport.load(tampered)


def test_non_finite_statistic_is_rejected(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    report = _entry(fx, _adapters(_exact_truth_pred_fn(truth)), _config())
    bad_summary = dataclasses.replace(report.summaries[0], mean=float("nan"))
    with pytest.raises(SeedVariabilityReportError):
        dataclasses.replace(report, summaries=(bad_summary, *report.summaries[1:]))


# --------------------------------------------------------------------------- #
# whole-call-failure guarantees: a STRUCTURAL/contract/leakage defect RAISES the
# whole call — it is NEVER laundered into an INCOMPLETE report (Fix pass).
# --------------------------------------------------------------------------- #
class _NonSpawnableBackend:
    """A seam-shaped backend that is NOT spawnable (no callable ``spawn``).

    It exposes ``is_available`` / ``configure_payload`` / ``predict`` /
    ``provenance_manifest`` like a real backend but deliberately omits ``spawn``,
    so the scientific entry must reject it UP FRONT as a structural contract
    defect (Task 2: a backend without spawn is rejected BEFORE fitting) rather
    than launder it into per-fold spawn failures -> INCOMPLETE.
    """

    is_available = True

    def configure_payload(self, payload):  # pragma: no cover - must never run
        raise AssertionError("configure_payload must not run for a non-spawnable backend")

    def predict(self, context, pair_ids, response_dim):  # pragma: no cover - must never run
        raise AssertionError("predict must not run for a non-spawnable backend")

    @property
    def provenance_manifest(self):  # pragma: no cover - must never run
        raise AssertionError("provenance must not run for a non-spawnable backend")


@pytest.mark.parametrize("bad_backend", [None, _NonSpawnableBackend()])
def test_non_spawnable_adapter_raises_whole_call_before_fitting(tmp_path, bad_backend):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    # roster keys stay exactly {gears, cpa} (the roster-set gate passes); gears'
    # backend is non-spawnable, so the spawn-capability gate must FAIL THE WHOLE
    # CALL up front, never yield an INCOMPLETE report from caught spawn failures.
    cpa, _rc, _bc = _adapter(_exact_truth_pred_fn(truth), name="cpa")
    adapters = {"gears": BaselineAdapter(name="gears", backend=bad_backend), "cpa": cpa}
    with pytest.raises(SeedVariabilityContractError):
        _entry(fx, adapters, _config())
    # rejected BEFORE any fold artifact is written (fail-closed up front).
    fold_dir = Path(fx["base_spec"].path).parent / "d2_seed_variability_folds"
    assert not fold_dir.exists() or list(fold_dir.glob("*.h5ad")) == []


def test_build_fold_job_failure_raises_whole_call_not_incomplete(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    n = len(fx["cal_pairs_id"])
    # Corrupt eps_split_a to a wrong row count. This PASSES the orchestration
    # contract and _build_delta_truth (which check the cal-pair IDs / additive_cal
    # / combo_calibration_eps, not eps_split_a) but trips _verify_alignment INSIDE
    # build_fold_job -> FoldJobError. A build/contract (leakage-guard) failure must
    # RAISE the whole call, never be laundered into an INCOMPLETE report.
    fx["inputs"] = dataclasses.replace(fx["inputs"], eps_split_a=np.zeros((n - 1, _P)))
    adapters = _adapters(_exact_truth_pred_fn(truth))
    with pytest.raises(FoldJobError):
        _entry(fx, adapters, _config())


def test_dev_store_checksum_mismatch_raises_whole_call(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    store = fx["store"]
    # Tamper the bound content_checksum so it no longer matches the store content:
    # the orchestration contract must FAIL THE WHOLE CALL (dev-store integrity),
    # never produce an INCOMPLETE report.
    object.__setattr__(store, "content_checksum", "0" * 64)
    adapters = _adapters(_exact_truth_pred_fn(truth))
    with pytest.raises(SeedVariabilityContractError):
        _entry(fx, adapters, _config())


def test_store_pair_misalignment_raises_whole_call(tmp_path):
    fx = _fixture(tmp_path)
    truth = _delta_truth_by_pair(fx)
    cal = fx["cal_pairs_id"]
    eps = fx["eps_cal"]
    # A valid dev store on its own, but its pair ORDER disagrees with
    # inputs.cal_pair_ids -> the orchestration-contract pair-ID / coverage
    # alignment path -> WHOLE-CALL raise (never an INCOMPLETE report).
    misaligned = DevelopmentOutcomeStore(
        combo_calibration_eps=eps[::-1],
        combo_calibration_pair_ids=tuple(reversed(cal)),
        access_audit=fx["store"].access_audit,
    )
    adapters = _adapters(_exact_truth_pred_fn(truth))
    with pytest.raises(SeedVariabilityContractError):
        _entry(fx, adapters, _config(), development_outcome_store=misaligned)


# =========================================================================== #
# D2 Task 6 — pre-access ledger binding + Phase-2b preflight verification
# =========================================================================== #
#
# Deterministic stubs only: NO gears/cpa, NO seal. The bound report is written
# ONCE as development_seed_variability.json; the verifier fails closed on any
# absence / tamper / identity / roster / OOF / binding / byte-SHA mismatch.


def _d2_env() -> EnvironmentInfo:
    return EnvironmentInfo(
        python_version="t",
        platform="t",
        git_commit="0" * 40,
        lockfile_sha256="l",
        registered_seeds=(11, 23, 37),
    )


def _d2_ledger(fx, cfg) -> RunLedger:
    return RunLedger(
        run_id=fx["inputs"].run_id, config_sha256=cfg.config_sha256, environment=_d2_env()
    )


def _complete_report(fx, cfg) -> SeedVariabilityReport:
    truth = _delta_truth_by_pair(fx)
    report = _entry(fx, _adapters(_exact_truth_pred_fn(truth)), cfg)
    assert report.status is SeedVariabilityStatus.COMPLETE
    return report


def _run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return run_dir


def _verify_kwargs(fx, cfg, ledger, run_dir):
    return dict(
        report_path=Path(run_dir) / DEVELOPMENT_SEED_VARIABILITY_FILENAME,
        run_dir=run_dir,
        ledger=ledger,
        expected_protocol=PROTOCOL,
        expected_run_id=fx["inputs"].run_id,
        expected_config_sha256=cfg.config_sha256,
        expected_registered_seeds=(11, 23, 37),
        oof_manifest=fx["manifest"],
        expected_response_space_checksum=fx["inputs"].response_space_checksum,
        expected_base_fit_role_sha256=fx["base_spec"].sha256,
        expected_dev_store_checksum=fx["store"].content_checksum,
    )


def test_preflight_verify_passes_for_bound_complete_report(tmp_path):
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)

    canonical, byte_sha = bind_development_seed_variability(
        run_dir=run_dir, ledger=ledger, report=report
    )
    assert canonical == run_dir / DEVELOPMENT_SEED_VARIABILITY_FILENAME
    assert canonical.is_file()
    # recorded into the ledger under the canonical artifact name (before any persist).
    assert ledger.artifact_sha(DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT) == byte_sha

    verified = verify_seed_variability_for_preflight(**_verify_kwargs(fx, cfg, ledger, run_dir))
    assert isinstance(verified, SeedVariabilityReport)
    assert verified.report_checksum == report.report_checksum


def test_bind_records_before_persist_and_is_write_once(tmp_path):
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)

    _canonical, byte_sha = bind_development_seed_variability(
        run_dir=run_dir, ledger=ledger, report=report
    )
    # the artifact is recorded into the ledger BEFORE any persist snapshot exists.
    assert ledger.artifact_sha(DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT) == byte_sha
    # a second write to the SAME run_dir (a re-write / post-persist mutation) fails closed.
    with pytest.raises(SeedVariabilityReportError):
        bind_development_seed_variability(run_dir=run_dir, ledger=ledger, report=report)


def test_bind_byte_sha_mismatch_fails_closed(tmp_path):
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    with pytest.raises(SeedVariabilityPreflightError):
        bind_development_seed_variability(
            run_dir=run_dir, ledger=ledger, report=report, expected_report_checksum="0" * 64
        )


def test_preflight_missing_file_fails_closed(tmp_path):
    fx = _fixture(tmp_path)
    cfg = _config()
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    ledger.record_artifact(DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT, "0" * 64)
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**_verify_kwargs(fx, cfg, ledger, run_dir))


def test_preflight_symlink_fails_closed(tmp_path):
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    real = tmp_path / "real_report.json"
    report.write_once(real)
    link = run_dir / DEVELOPMENT_SEED_VARIABILITY_FILENAME
    link.symlink_to(real)
    ledger.record_artifact(DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT, sha256_file(real))
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**_verify_kwargs(fx, cfg, ledger, run_dir))


def test_preflight_non_direct_child_fails_closed(tmp_path):
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    run_dir = _run_dir(tmp_path)
    sub = run_dir / "sub"
    sub.mkdir()
    nested = sub / DEVELOPMENT_SEED_VARIABILITY_FILENAME
    report.write_once(nested)
    ledger = _d2_ledger(fx, cfg)
    ledger.record_artifact(DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT, sha256_file(nested))
    kwargs = _verify_kwargs(fx, cfg, ledger, run_dir)
    kwargs["report_path"] = nested
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**kwargs)


def test_preflight_incomplete_status_fails_closed(tmp_path):
    fx = _fixture(tmp_path)
    cfg = _config()
    truth = _delta_truth_by_pair(fx)

    def _fail_23(payload, pair_ids, response_dim):
        if _seed_from_payload(payload) == 23:
            raise RuntimeError("boom")
        return {p: np.asarray(truth[p], dtype=float) for p in pair_ids}

    report = _entry(fx, _adapters(_fail_23), cfg)
    assert report.status is SeedVariabilityStatus.INCOMPLETE
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    bind_development_seed_variability(run_dir=run_dir, ledger=ledger, report=report)
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**_verify_kwargs(fx, cfg, ledger, run_dir))


@pytest.mark.parametrize(
    "override",
    [
        {"expected_protocol": "OTHER-PROTOCOL"},
        {"expected_run_id": "wrong-run-id"},
        {"expected_config_sha256": "0" * 64},
        {"expected_registered_seeds": (11, 23, 38)},
        {"expected_method_roster": frozenset({"gears", "foo"})},
    ],
)
def test_preflight_identity_or_roster_mismatch_fails_closed(tmp_path, override):
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    bind_development_seed_variability(run_dir=run_dir, ledger=ledger, report=report)
    kwargs = _verify_kwargs(fx, cfg, ledger, run_dir)
    kwargs.update(override)
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**kwargs)


def test_preflight_oof_manifest_checksum_mismatch_fails_closed(tmp_path):
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    bind_development_seed_variability(run_dir=run_dir, ledger=ledger, report=report)
    kwargs = _verify_kwargs(fx, cfg, ledger, run_dir)
    kwargs["oof_manifest"] = dataclasses.replace(fx["manifest"], manifest_checksum="0" * 64)
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**kwargs)


def test_preflight_covered_checksum_mismatch_fails_closed(tmp_path):
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    bind_development_seed_variability(run_dir=run_dir, ledger=ledger, report=report)
    m = fx["manifest"]
    # keep the same manifest_checksum (so the OOF-checksum leg passes) but swap the
    # covered / uncovered ID lists -> the covered/uncovered digest recompute differs.
    swapped = dataclasses.replace(
        m,
        covered_pair_ids=m.uncovered_pair_ids,
        uncovered_pair_ids=m.covered_pair_ids,
        manifest_checksum=m.manifest_checksum,
    )
    kwargs = _verify_kwargs(fx, cfg, ledger, run_dir)
    kwargs["oof_manifest"] = swapped
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**kwargs)


@pytest.mark.parametrize(
    "override",
    [
        {"expected_response_space_checksum": "wrong-response"},
        {"expected_base_fit_role_sha256": "sha256:" + "0" * 64},
        {"expected_dev_store_checksum": "0" * 64},
    ],
)
def test_preflight_binding_mismatch_fails_closed(tmp_path, override):
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    bind_development_seed_variability(run_dir=run_dir, ledger=ledger, report=report)
    kwargs = _verify_kwargs(fx, cfg, ledger, run_dir)
    kwargs.update(override)
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**kwargs)


def test_preflight_worker_lock_binding_mismatch_fails_closed(tmp_path):
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    # a self-consistent report whose worker_locks no longer bind to the fold records.
    tampered = dataclasses.replace(report, worker_locks=("deadbeef",))
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    bind_development_seed_variability(run_dir=run_dir, ledger=ledger, report=tampered)
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**_verify_kwargs(fx, cfg, ledger, run_dir))


def test_preflight_byte_sha_ne_ledger_entry_fails_closed(tmp_path):
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    bind_development_seed_variability(run_dir=run_dir, ledger=ledger, report=report)
    # a DIFFERENT ledger whose recorded entry does not match the bound file's bytes.
    ledger2 = _d2_ledger(fx, cfg)
    ledger2.record_artifact(DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT, "1" * 64)
    kwargs = _verify_kwargs(fx, cfg, ledger2, run_dir)
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**kwargs)


def test_preflight_ledger_missing_entry_fails_closed(tmp_path):
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    bind_development_seed_variability(run_dir=run_dir, ledger=ledger, report=report)
    empty = _d2_ledger(fx, cfg)  # no development_seed_variability entry recorded
    kwargs = _verify_kwargs(fx, cfg, empty, run_dir)
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**kwargs)


# =========================================================================== #
# D2 Task 6 (fix pass) — frozen bundle is the OOF-manifest TRUST ROOT and two
# cheap verifier fail-closed legs.
# =========================================================================== #


@dataclasses.dataclass(frozen=True)
class _BundleStub:
    """Minimal stand-in for the fields ``_preaccess_seed_variability`` reads.

    Exposes ONLY the run identity, response-space checksum and ``dev_diagnostics``
    (which carries the authoritative ``oof_fold_manifest_checksum``) that the
    pre-access gate consults on a :class:`FrozenPredictionBundle`.
    """

    run_id: str
    response_space_checksum: str
    dev_diagnostics: dict


def test_preaccess_rejects_oof_layout_not_bound_to_frozen_bundle(tmp_path):
    # A report + OOF manifest that are INTERNALLY self-consistent but describe a
    # DIFFERENT OOF layout than the frozen bundle's authoritative digest are
    # rejected at preflight (seal CLOSED) — even though the CALLER passes that
    # different manifest's own matching checksum (the defense-in-depth leg passes).
    fx = _fixture(tmp_path)
    cfg = _config()
    report = _complete_report(fx, cfg)
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)

    manifest = fx["manifest"]
    oof_path = tmp_path / "source_oof_manifest.json"
    manifest.write_once(oof_path)
    report_src = tmp_path / "source_report.json"
    report.write_once(report_src)

    # the frozen bundle is the TRUST ROOT and binds a DIFFERENT OOF layout.
    authoritative_oof = hashlib.sha256(b"a-different-authoritative-oof-layout").hexdigest()
    assert authoritative_oof != manifest.manifest_checksum
    bundle = _BundleStub(
        run_id=fx["inputs"].run_id,
        response_space_checksum=fx["inputs"].response_space_checksum,
        dev_diagnostics={"oof_fold_manifest_checksum": authoritative_oof},
    )
    inputs = SeedVariabilityPreflightInputs(
        oof_manifest_path=oof_path,
        oof_manifest_checksum=manifest.manifest_checksum,  # matches the on-disk manifest
        report_source_path=report_src,
        report_checksum=report.report_checksum,
    )

    with pytest.raises(SeedVariabilityPreflightError):
        _preaccess_seed_variability(
            run_dir=run_dir,
            ledger=ledger,
            frozen_bundle=bundle,
            config=cfg,
            fixture_execution=False,
            seed_variability=inputs,
        )
    # fail closed BEFORE any bind: nothing was written into the run directory.
    assert not (run_dir / DEVELOPMENT_SEED_VARIABILITY_FILENAME).exists()


def _mutate_out_of_range(report: SeedVariabilityReport) -> SeedVariabilityReport:
    bad = dataclasses.replace(report.fold_execution_records[0], fold=999)
    return dataclasses.replace(
        report, fold_execution_records=(bad, *report.fold_execution_records[1:])
    )


def _drop_one_record(report: SeedVariabilityReport) -> SeedVariabilityReport:
    return dataclasses.replace(
        report, fold_execution_records=tuple(report.fold_execution_records[:-1])
    )


@pytest.mark.parametrize("mutate", [_mutate_out_of_range, _drop_one_record])
def test_preflight_fold_execution_record_defect_fails_closed(tmp_path, mutate):
    # The verifier fails closed on a fold-execution-consistency defect: a record
    # whose (method, seed, fold) is out of range, or a missing record (count guard).
    # Each mutation re-derives the report self-checksum (so the strict load passes)
    # yet trips a fold-execution binding/range/count leg.
    fx = _fixture(tmp_path)
    cfg = _config()
    tampered = mutate(_complete_report(fx, cfg))
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    bind_development_seed_variability(run_dir=run_dir, ledger=ledger, report=tampered)
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**_verify_kwargs(fx, cfg, ledger, run_dir))


def test_preflight_directory_at_report_path_fails_closed(tmp_path):
    # A DIRECTORY at the report path (not a symlink, not missing) is rejected
    # fail-closed by the is_file() regular-file guard, before any ledger read.
    fx = _fixture(tmp_path)
    cfg = _config()
    run_dir = _run_dir(tmp_path)
    ledger = _d2_ledger(fx, cfg)
    (run_dir / DEVELOPMENT_SEED_VARIABILITY_FILENAME).mkdir()
    ledger.record_artifact(DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT, "0" * 64)
    with pytest.raises(SeedVariabilityPreflightError):
        verify_seed_variability_for_preflight(**_verify_kwargs(fx, cfg, ledger, run_dir))
