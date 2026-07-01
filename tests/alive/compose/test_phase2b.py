"""Tests for alive.compose.phase2b — the Phase-2b sealed-evaluation ORCHESTRATOR.

TDD order: tests written FIRST; the implementation must pass all of them.

This is Task 8 of 8 for COMPOSE-K562-v1 Phase 2b — the capstone that wires the
seven built modules (outcome_store, preflight, inference2, scoring2, verdict2,
provenance2, terminal) into the one-time sealed evaluation. It opens the COMPOSE
seal EXACTLY ONCE, for the UNION of both sealed roles, inside the terminal
protection boundary, and produces a frozen :class:`Phase2bResult`.

Load-bearing contracts under test (brief + plan §5):

  * the public API takes ONLY a ``ComposeOutcomeStore`` — NEVER raw truth, an
    outcome dict/array, a path to outcomes, or an AnnData of sealed rows;
  * the seven steps run in order; ``evaluate_sealed_once`` is called EXACTLY ONCE
    for the union of both sealed roles, inside the terminal boundary;
  * only DOUBLE-UNSEEN drives the sealed verdict; single-unseen is descriptive
    secondary; the two regimes are scored SEPARATELY and NEVER pooled;
  * every consumed access leaves a write-once terminal artifact (COMPLETE /
    INVALID / ABORTED_AFTER_SEAL); a preflight/pre-access failure keeps
    ``sealed_access_count == 0`` and the seal closed;
  * scientific ``run_phase2b`` enforces activation — a blocked config makes it
    fail; the bounded synthetic ``run_phase2b_fixture`` is the test path. (The
    canonical config is ``active`` as of the 2026-06-30 activation; blocked
    rejection is pinned via a synthetic blocked config.)

SYNTHETIC-ONLY: pure synthetic / tiny-fixture values only; NO real Norman,
NO seal open beyond the synthetic in-memory store, NO real sealed-outcome read.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path

import numpy as np
import pytest

from alive.compose.config2 import (
    ScientificModeError,
    load_compose_phase2_config,
)
from alive.compose.datacard import compute_compose_run_id
from alive.compose.freeze import FrozenPredictionBundle
from alive.compose.outcome_store import ComposeOutcomeStore, ComposeSealingError
from alive.compose.preflight import PreflightError
from alive.compose.provenance2 import Phase2bProvenance
from alive.compose.response import fit_response_space
from alive.compose.scoring2 import RegimeScore
from alive.compose.split import build_split_manifest
from alive.compose.terminal import Phase2bTerminal, TerminalState
from alive.compose.verdict2 import MethodAxis, SealedAxis
from alive.provenance import EnvironmentInfo, RunLedger

from alive.compose.phase2b import (  # isort: skip
    Phase2bResult,
    run_phase2b,
    run_phase2b_fixture,
)

_CONFIG_PATH = "configs/compose_k562_v1_phase2.yaml"

# Provenance digests bound into the composite run id (synthetic).
_DATA_CARD = "data-card-checksum"
_RAW = "raw-data-checksum"
_SEQ = "sequence-mapping-checksum"

# Eligible gene pairs engineered (seed below) to populate ALL three roles.
_ELIGIBLE_PAIRS: list[tuple[str, str]] = [
    ("GENEA", "GENEB"),
    ("GENEA", "GENEC"),
    ("GENEB", "GENEC"),
    ("GENEC", "GENED"),
    ("GENED", "GENEE"),
    ("GENEE", "GENEF"),
    ("GENEA", "GENED"),
    ("GENEB", "GENEF"),
]
_SPLIT_SEED = 7
_CAL_FRACTION = 0.5
_N_GENES = 6
_ROWS_PER_PAIR = 12


# ---------------------------------------------------------------------------
# In-memory synthetic source + fixture builders
# ---------------------------------------------------------------------------


class _InMemorySource:
    """Tiny stand-in AnnData-like source exposing only an ``.X`` matrix.

    The store reads ``source.X[row_indices]``. The matrix carries deterministic
    positive-library raw counts so a projected population is well-defined.
    """

    def __init__(self, X: np.ndarray) -> None:
        self.X = X


def _config():
    return load_compose_phase2_config(_CONFIG_PATH)


def _environment() -> EnvironmentInfo:
    return EnvironmentInfo(
        python_version="fixture",
        platform="fixture",
        git_commit="0" * 40,
        lockfile_sha256="lock-sha-fixture",
        registered_seeds=(11, 23, 37),
    )


def _manifest() -> dict:
    return build_split_manifest(
        _ELIGIBLE_PAIRS, seed=_SPLIT_SEED, calibration_fraction=_CAL_FRACTION
    )


def _role_pairs(manifest: dict, role: str) -> list[tuple[str, str]]:
    return [tuple(p) for p in manifest["roles"][role]]


def _counts(seed: int, n_cells: int, n_genes: int = _N_GENES) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 8, size=(n_cells, n_genes)).astype(np.float64)
    base[:, 0] += 1.0  # every cell a positive library size
    return base


def _response_space():
    """A small fitted ResponseSpace + explicit PCA-space control mean."""
    X = _counts(0, 24, _N_GENES)
    control_idx = np.arange(0, 8)
    single_idx = np.arange(8, 16)
    space = fit_response_space(
        X, control_idx=control_idx, eligible_single_idx=single_idx, n_hvg=4, pca_dim=2, seed=7
    )
    control_cells = X[control_idx]
    control_mean = space.project(control_cells, np.arange(control_cells.shape[0])).mean(axis=0)
    return space, control_mean


def _build_source_and_index(manifest: dict):
    """Assign each pair (all roles) a disjoint block of source rows."""
    all_pairs: list[tuple[str, str]] = []
    for role in ("combo_calibration", "sealed_double_unseen", "sealed_single_unseen"):
        all_pairs.extend(_role_pairs(manifest, role))

    rows: list[np.ndarray] = []
    pair_index: dict[tuple[str, str], np.ndarray] = {}
    cursor = 0
    for k, pair in enumerate(all_pairs):
        block = _counts(1000 + k, _ROWS_PER_PAIR, _N_GENES)
        rows.append(block)
        pair_index[pair] = np.arange(cursor, cursor + _ROWS_PER_PAIR, dtype=np.int64)
        cursor += _ROWS_PER_PAIR
    X = np.vstack(rows)
    return _InMemorySource(X), pair_index


def _build_store(audit_path, manifest: dict, *, fixture: bool = True):
    """Build a ComposeOutcomeStore over a synthetic in-memory source.

    Tests NEVER hand truth to ``run_phase2b*`` — the store hides the source. The
    fixture marker (set when ``fixture=True``) lets ``run_phase2b_fixture`` accept
    a bounded synthetic store without owner activation.
    """
    source, pair_index = _build_source_and_index(manifest)
    store = ComposeOutcomeStore(
        pair_index=pair_index,
        source=source,
        manifest=manifest,
        audit_path=audit_path,
    )
    if fixture:
        # Synthetic-fixture marker; the bounded fixture entry verifies it.
        object.__setattr__(store, "_compose_fixture_marker", True)
    return store


def _run_id(cfg) -> str:
    return compute_compose_run_id(
        config_digest=cfg.config_sha256,
        data_card_digest=_DATA_CARD,
        raw_or_source_digest=_RAW,
        sequence_mapping_digest=_SEQ,
    )


def _predictions_for_role(pair_ids, *, response_dim, headline_factor):
    """Build a complete-roster prediction block for one regime.

    The headline beats the comparators (so the happy-path verdict is meaningful):
    headline ~ the additive baseline plus a small GI residual; learned comparators
    are deliberately noisier.
    """
    rng = np.random.default_rng(hash(("preds", headline_factor)) % (2**32))
    roster = (
        "l1_bilinear_identifiable",
        "l2_saturation",
        "l3_hypernetwork",
        "additive",
        "no_change",
        "perturbation_mean",
        "id_only",
        "gears",
        "cpa",
    )
    out: dict[str, dict[tuple[str, str], np.ndarray]] = {m: {} for m in roster}
    for k, pid in enumerate(pair_ids):
        additive_pred = rng.normal(size=response_dim)
        out["additive"][pid] = additive_pred
        out["l1_bilinear_identifiable"][pid] = additive_pred + headline_factor * rng.normal(
            size=response_dim
        )
        out["l2_saturation"][pid] = additive_pred + 3.0 * rng.normal(size=response_dim)
        out["l3_hypernetwork"][pid] = additive_pred + 5.0 * rng.normal(size=response_dim)
        out["id_only"][pid] = additive_pred + 5.0 * rng.normal(size=response_dim)
        out["gears"][pid] = additive_pred + 5.0 * rng.normal(size=response_dim)
        out["cpa"][pid] = additive_pred + 5.0 * rng.normal(size=response_dim)
        out["no_change"][pid] = np.zeros(response_dim)
        out["perturbation_mean"][pid] = additive_pred.copy()
    return out


def _build_bundle(manifest: dict, cfg, *, response_dim=2, futility_status="CONTINUE"):
    """A FrozenPredictionBundle whose sealed pairs == the manifest roles exactly."""
    double_ids = tuple(_role_pairs(manifest, "sealed_double_unseen"))
    single_ids = tuple(_role_pairs(manifest, "sealed_single_unseen"))
    return FrozenPredictionBundle.create(
        run_id=_run_id(cfg),
        method_roster=cfg.method_roster,
        pair_ids_double_unseen=double_ids,
        pair_ids_single_unseen=single_ids,
        predictions_double_unseen=_predictions_for_role(
            double_ids, response_dim=response_dim, headline_factor=0.1
        ),
        predictions_single_unseen=_predictions_for_role(
            single_ids, response_dim=response_dim, headline_factor=0.1
        ),
        response_space_checksum="rs-checksum",
        factor_checksum="zf-checksum",
        model_checksum="model-checksum",
        manifest_checksum=manifest["checksum"],
        selected_k_total=4,
        selected_lambda=0.01,
        registered_seeds=cfg.registered_seeds,
        futility_status=futility_status,
        dev_diagnostics={"selected_k_total": 4, "seal_open_count": 0},
        response_dim=response_dim,
        required_roster=cfg.method_roster,
    )


def _build_ledger(manifest: dict, bundle: FrozenPredictionBundle, cfg) -> RunLedger:
    """A ledger recording the bundle + upstream artifacts (preflight expects these)."""
    ledger = RunLedger(
        run_id=bundle.run_id, config_sha256=cfg.config_sha256, environment=_environment()
    )
    ledger.record_artifact("pair_manifest", manifest["checksum"])
    ledger.record_artifact("response_space", bundle.response_space_checksum)
    ledger.record_artifact("factor_bank", bundle.factor_checksum)
    ledger.record_artifact("model", bundle.model_checksum)
    ledger.record_artifact("frozen_prediction_bundle", bundle.bundle_checksum)
    return ledger


def _response_artifact():
    space, control_mean = _response_space()
    return {"response_space": space, "control_mean": control_mean}


def _provenance(manifest: dict, bundle: FrozenPredictionBundle, cfg) -> Phase2bProvenance:
    """A COMPLETE Phase2bProvenance whose upstream hashes match the ledger."""
    return Phase2bProvenance(
        protocol="COMPOSE-K562-v1",
        config_digest=cfg.config_sha256,
        pair_manifest_sha256=manifest["checksum"],
        exclusion_manifest_sha256="exclusion-sha",
        data_card_sha256=_DATA_CARD,
        raw_or_source_sha256=_RAW,
        processed_sha256="processed-sha",
        sequence_mapping_sha256=_SEQ,
        feature_bank_sha256="feature-bank-sha",
        response_space_sha256=bundle.response_space_checksum,
        factor_bank_sha256=bundle.factor_checksum,
        model_lock_sha256=bundle.model_checksum,
        frozen_prediction_bundle_sha256=bundle.bundle_checksum,
        git_commit="0" * 40,
        git_clean=True,
        dependency_lock_sha256="lock-sha-fixture",
        gears_revision="gears-rev",
        cpa_revision="cpa-rev",
        python_version="fixture",
        platform="fixture",
        device="cpu",
        precision="float64",
        registered_seeds=cfg.registered_seeds,
        split_seed=cfg.split_seed,
        seal_audit_reference="audit.jsonl",
        regime_result_double_sha256="placeholder-double",
        regime_result_single_sha256="placeholder-single",
        terminal_report_sha256="placeholder-terminal",
    )


def _make_run(tmp_path: Path, *, manifest=None, fixture_store=True, futility_status="CONTINUE"):
    """Assemble a complete fixture run kit (everything but the truth)."""
    cfg = _config()
    manifest = manifest if manifest is not None else _manifest()
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    audit_path = run_dir / "compose_audit.jsonl"
    bundle = _build_bundle(manifest, cfg, futility_status=futility_status)
    ledger = _build_ledger(manifest, bundle, cfg)
    store = _build_store(audit_path, manifest, fixture=fixture_store)
    return {
        "cfg": cfg,
        "manifest": manifest,
        "run_dir": run_dir,
        "audit_path": audit_path,
        "bundle": bundle,
        "ledger": ledger,
        "store": store,
        "response_artifact": _response_artifact(),
        "provenance": _provenance(manifest, bundle, cfg),
    }


def _fixture_kwargs(kit):
    return dict(
        run_dir=kit["run_dir"],
        outcome_store=kit["store"],
        frozen_bundle=kit["bundle"],
        pair_manifest=kit["manifest"],
        response_artifact=kit["response_artifact"],
        config=kit["cfg"],
        ledger=kit["ledger"],
    )


def _terminal_artifacts(run_dir: Path) -> list[Path]:
    return [
        p
        for p in (
            run_dir / Phase2bTerminal.COMPLETE_ARTIFACT,
            run_dir / Phase2bTerminal.INVALID_ARTIFACT,
            run_dir / Phase2bTerminal.ABORTED_ARTIFACT,
        )
        if p.exists()
    ]


# ===========================================================================
# Happy path
# ===========================================================================


def test_happy_path_complete_terminal_and_one_access(tmp_path):
    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))

    assert isinstance(res, Phase2bResult)
    assert res.sealed_access_count == 1
    assert res.terminal_state == TerminalState.COMPLETE
    # exactly one terminal artifact: COMPLETE.
    artifacts = _terminal_artifacts(kit["run_dir"])
    assert artifacts == [kit["run_dir"] / Phase2bTerminal.COMPLETE_ARTIFACT]
    # both regimes scored, kept separate.
    assert isinstance(res.regime_double, RegimeScore)
    assert isinstance(res.regime_single, RegimeScore)
    assert res.regime_double.regime == "sealed_double_unseen"
    assert res.regime_single.regime == "sealed_single_unseen"
    # a sensible verdict on a clean, integrity-valid run (headline beats family).
    assert res.sealed_verdict.sealed_axis in {
        SealedAxis.GI_LEARNABLE_WIN,
        SealedAxis.PARTIAL,
        SealedAxis.NO_DISTINCT_WIN,
    }
    assert res.run_id == kit["bundle"].run_id


def test_result_is_frozen(tmp_path):
    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))
    assert dataclasses.is_dataclass(res)
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.sealed_access_count = 99  # type: ignore[misc]


# ===========================================================================
# 1. preflight failure → access count 0 and no terminal artifact
# ===========================================================================


def test_preflight_failure_keeps_access_zero_and_no_terminal(tmp_path):
    kit = _make_run(tmp_path)
    # Tamper the ledger so the bundle/ledger checksum disagreement fails preflight.
    bad_ledger = RunLedger(
        run_id=kit["bundle"].run_id,
        config_sha256=kit["cfg"].config_sha256,
        environment=_environment(),
    )
    bad_ledger.record_artifact("pair_manifest", kit["manifest"]["checksum"])
    bad_ledger.record_artifact("response_space", kit["bundle"].response_space_checksum)
    bad_ledger.record_artifact("factor_bank", kit["bundle"].factor_checksum)
    bad_ledger.record_artifact("model", kit["bundle"].model_checksum)
    bad_ledger.record_artifact("frozen_prediction_bundle", "WRONG-SHA")

    kwargs = _fixture_kwargs(kit)
    kwargs["ledger"] = bad_ledger
    with pytest.raises(PreflightError):
        run_phase2b_fixture(**kwargs)

    assert kit["store"].sealed_access_count == 0
    assert _terminal_artifacts(kit["run_dir"]) == []


# ===========================================================================
# 2. a missing registered comparator in the bundle → preflight fails, access 0
# ===========================================================================


@pytest.mark.parametrize("drop", ["gears", "cpa", "id_only", "l3_hypernetwork"])
def test_missing_registered_comparator_fails_preflight(tmp_path, drop):
    kit = _make_run(tmp_path)
    # Drop a comparator's predictions from the double-unseen regime; the bundle
    # itself is frozen, so rebuild it minus that method's role block — which the
    # bundle's own create() rejects (roster mismatch). Instead, build a bundle on
    # a roster that omits the method by mutating the validated dict post-freeze,
    # then re-run preflight which must reject the incomplete roster.
    bundle = kit["bundle"]
    object.__setattr__(
        bundle,
        "predictions_double_unseen",
        {m: blk for m, blk in bundle.predictions_double_unseen.items() if m != drop},
    )
    kwargs = _fixture_kwargs(kit)
    kwargs["frozen_bundle"] = bundle
    with pytest.raises(PreflightError):
        run_phase2b_fixture(**kwargs)
    assert kit["store"].sealed_access_count == 0
    assert _terminal_artifacts(kit["run_dir"]) == []


# ===========================================================================
# 3. raw truth CANNOT be supplied through the public API
# ===========================================================================


def test_public_api_has_no_truth_parameter():
    # raw-truth-smelling tokens. ``outcome_store`` is the SOLE allowed seal handle
    # (a typed structurally-sealed store, NOT raw truth), so it is exempt from the
    # bare "outcome" scan; every OTHER parameter must be truth-free.
    truth_tokens = (
        "truth",
        "observed",
        "sealed_truth",
        "cells",
        "anndata",
        "adata",
        "y_true",
        "delta",
        "eps_obs",
    )
    for fn in (run_phase2b, run_phase2b_fixture):
        params = set(inspect.signature(fn).parameters)
        assert "outcome_store" in params
        for p in params:
            if p == "outcome_store":
                continue
            low = p.casefold()
            assert "outcome" not in low, f"{fn.__name__} parameter {p!r} smells like an outcome"
            for tok in truth_tokens:
                assert tok not in low, f"{fn.__name__} parameter {p!r} smells like raw truth"
    # the only store-like parameter is outcome_store (a typed sealed store).
    sci_params = set(inspect.signature(run_phase2b).parameters)
    store_like = {p for p in sci_params if "store" in p.casefold()}
    assert store_like == {"outcome_store"}


# ===========================================================================
# 4. predictions are frozen BEFORE access — a spy store records zero access
#    until the single evaluate_sealed_once call
# ===========================================================================


class _SpyStore:
    """Wraps a ComposeOutcomeStore, recording the access order of calls."""

    def __init__(self, inner: ComposeOutcomeStore) -> None:
        self._inner = inner
        self.events: list[str] = []
        self._compose_fixture_marker = True

    def evaluate_sealed_once(self, run_id, pair_ids):
        self.events.append("evaluate_sealed_once")
        return self._inner.evaluate_sealed_once(run_id, pair_ids)

    def read_unsealed(self, pair_ids):  # pragma: no cover - defensive
        self.events.append("read_unsealed")
        return self._inner.read_unsealed(pair_ids)

    @property
    def sealed_access_count(self):
        return self._inner.sealed_access_count

    def audit_records(self):
        return self._inner.audit_records()


def test_predictions_consumed_readonly_no_access_until_step_six(tmp_path):
    kit = _make_run(tmp_path)
    spy = _SpyStore(kit["store"])
    pre_checksum = kit["bundle"].bundle_checksum

    kwargs = _fixture_kwargs(kit)
    kwargs["outcome_store"] = spy
    res = run_phase2b_fixture(**kwargs)

    # exactly one access event, and the bundle was not mutated (consumed read-only).
    assert spy.events == ["evaluate_sealed_once"]
    assert kit["bundle"].bundle_checksum == pre_checksum
    kit["bundle"].verify()
    assert res.sealed_access_count == 1


# ===========================================================================
# 5. one access releases BOTH roles; role labels are preserved (separate)
# ===========================================================================


def test_one_access_releases_both_roles_kept_separate(tmp_path):
    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))

    # exactly one audited access opened the UNION of both roles.
    assert kit["store"].sealed_access_count == 1
    records = kit["store"].audit_records()
    assert len(records) == 1
    double = set(_role_pairs(kit["manifest"], "sealed_double_unseen"))
    single = set(_role_pairs(kit["manifest"], "sealed_single_unseen"))
    opened = {tuple(p) for p in records[0]["pair_ids"]}
    assert opened == double | single

    # the result keeps the two regimes separate (different labels + pair sets).
    assert set(res.regime_double.pair_ids) == double
    assert set(res.regime_single.pair_ids) == single
    assert res.regime_double.checksum != res.regime_single.checksum


# ===========================================================================
# 6. headline verdict uses DOUBLE-UNSEEN only
# ===========================================================================


def test_headline_verdict_uses_double_unseen_only(tmp_path):
    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))
    # the sealed verdict's evidence/bounds are the double-unseen bounds.
    assert res.sealed_verdict.evidence["comparators"] == list(kit["cfg"].comparator_family)
    # verdict checksum must be reproducible from the double regime's bounds only.
    from alive.compose.verdict2 import ComposeIntegrityReport, sealed_verdict

    integ = ComposeIntegrityReport(
        provenance_ok=True,
        leakage_ok=True,
        all_metrics_finite=True,
        sealed_access_consistent=True,
        sealed_n=res.regime_double.sample_count,
        minimum_sealed=0,
    )
    recomputed = sealed_verdict(
        regime="sealed_double_unseen",
        bounds=res.regime_double.bounds,
        comparators=kit["cfg"].comparator_family,
        additive_margin=kit["cfg"].material_margin_vs_additive,
        learned_margin=kit["cfg"].learned_comparator_margin,
        integrity=integ,
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    assert recomputed.sealed_axis == res.sealed_verdict.sealed_axis


# ===========================================================================
# 7. changing the single-unseen OBSERVED outcomes does NOT change the headline
# ===========================================================================


def test_single_unseen_outcomes_do_not_change_headline(tmp_path):
    kit_a = _make_run(tmp_path / "a")
    res_a = run_phase2b_fixture(**_fixture_kwargs(kit_a))

    # Build a second run whose SINGLE-unseen observed cells differ (different
    # seed offset for the single-role pairs) but whose double-unseen cells and
    # bundle are identical. The headline (double-unseen) verdict must not move.
    manifest = _manifest()
    cfg = _config()
    run_dir = (tmp_path / "b") / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    audit_path = run_dir / "compose_audit.jsonl"
    bundle = _build_bundle(manifest, cfg)
    ledger = _build_ledger(manifest, bundle, cfg)

    # custom source: same double-unseen blocks as run a, perturbed single blocks.
    source_a, index_a = _build_source_and_index(manifest)
    X = source_a.X.copy()
    for pair in _role_pairs(manifest, "sealed_single_unseen"):
        rows = index_a[pair]
        X[rows] = X[rows] + 13.0  # shift single-unseen observed cells only
    store_b = ComposeOutcomeStore(
        pair_index=index_a,
        source=_InMemorySource(X),
        manifest=manifest,
        audit_path=audit_path,
    )
    object.__setattr__(store_b, "_compose_fixture_marker", True)

    res_b = run_phase2b_fixture(
        run_dir=run_dir,
        outcome_store=store_b,
        frozen_bundle=bundle,
        pair_manifest=manifest,
        response_artifact=_response_artifact(),
        config=cfg,
        ledger=ledger,
    )

    # single-unseen scoring DID change; the headline (double) verdict did NOT.
    assert res_a.regime_single.checksum != res_b.regime_single.checksum
    assert res_a.regime_double.checksum == res_b.regime_double.checksum
    assert res_a.sealed_verdict.checksum == res_b.sealed_verdict.checksum


# ===========================================================================
# 8. second access fails (once-only) across a fresh store over the same audit
# ===========================================================================


def test_second_run_refuses_once_only(tmp_path):
    kit = _make_run(tmp_path)
    run_phase2b_fixture(**_fixture_kwargs(kit))
    assert kit["store"].sealed_access_count == 1

    # A fresh store instance over the SAME audit path must refuse to re-open.
    fresh = _build_store(kit["audit_path"], kit["manifest"], fixture=True)
    assert fresh.sealed_access_count == 1  # durable audit already burned
    kwargs = _fixture_kwargs(kit)
    kwargs["outcome_store"] = fresh
    # the terminal lock / existing terminal artifact refuses re-run before access.
    with pytest.raises(Exception):  # noqa: B017 - TerminalError or ComposeSealingError
        run_phase2b_fixture(**kwargs)
    assert fresh.sealed_access_count == 1


def test_terminal_artifact_blocks_rerun_in_same_dir(tmp_path):
    kit = _make_run(tmp_path)
    run_phase2b_fixture(**_fixture_kwargs(kit))
    # a terminal artifact now exists; a second run in the SAME run_dir refuses.
    fresh = _build_store(kit["run_dir"] / "audit2.jsonl", kit["manifest"], fixture=True)
    kwargs = _fixture_kwargs(kit)
    kwargs["outcome_store"] = fresh
    with pytest.raises(Exception):  # noqa: B017
        run_phase2b_fixture(**kwargs)
    # the fresh store's own audit was never opened.
    assert fresh.sealed_access_count == 0


# ===========================================================================
# 9. a post-access scoring/metric failure writes a terminal failure artifact
# ===========================================================================


class _EmptyCellsStore:
    """Store whose release returns an empty (0-row) observed population.

    The seal opens normally (the audit is burned), but ``score_regime`` rejects
    the empty population AFTER access — a genuine post-access scoring failure that
    the terminal protection boundary must turn into a failure artifact.
    """

    def __init__(self, inner: ComposeOutcomeStore) -> None:
        self._inner = inner
        self._audit_path = inner._audit_path
        self._compose_fixture_marker = True

    def evaluate_sealed_once(self, run_id, pair_ids):
        from alive.compose.outcome_store import ObservedPair

        release = self._inner.evaluate_sealed_once(run_id, pair_ids)
        return {pid: ObservedPair(pair_id=pid, cells=op.cells[:0]) for pid, op in release.items()}

    def read_unsealed(self, pair_ids):  # pragma: no cover - defensive
        return self._inner.read_unsealed(pair_ids)

    @property
    def sealed_access_count(self):
        return self._inner.sealed_access_count

    def audit_records(self):
        return self._inner.audit_records()


def test_post_access_scoring_failure_writes_failure_terminal(tmp_path):
    kit = _make_run(tmp_path)
    # An empty observed population is rejected by score_regime AFTER the seal opens.
    empty = _EmptyCellsStore(kit["store"])
    kwargs = _fixture_kwargs(kit)
    kwargs["outcome_store"] = empty
    with pytest.raises(Exception):  # noqa: B017 - propagated after the abort artifact
        run_phase2b_fixture(**kwargs)
    # the seal was consumed and a terminal failure artifact exists.
    assert kit["store"].sealed_access_count == 1
    artifacts = _terminal_artifacts(kit["run_dir"])
    assert len(artifacts) == 1
    body = json.loads(artifacts[0].read_text())
    assert body["terminal_state"] in {
        TerminalState.ABORTED_AFTER_SEAL.value,
        TerminalState.INVALID.value,
    }


# ===========================================================================
# 10. a materialisation failure burns the run and writes a failure record
# ===========================================================================


class _RaisingAfterClaimStore:
    """Store whose evaluate_sealed_once burns the audit, then raises."""

    def __init__(self, inner: ComposeOutcomeStore) -> None:
        self._inner = inner
        self._compose_fixture_marker = True

    def evaluate_sealed_once(self, run_id, pair_ids):
        # Burn the audit exactly as the real store would (write FIRST), then fail
        # during materialisation — the worst-case the terminal must survive.
        self._inner._write_audit_record(run_id, [self._inner._canonical(p) for p in pair_ids])
        raise RuntimeError("synthetic materialisation failure")

    def read_unsealed(self, pair_ids):  # pragma: no cover - defensive
        return self._inner.read_unsealed(pair_ids)

    @property
    def sealed_access_count(self):
        return self._inner.sealed_access_count

    def audit_records(self):
        return self._inner.audit_records()


def test_materialisation_failure_burns_run_writes_failure(tmp_path):
    kit = _make_run(tmp_path)
    burner = _RaisingAfterClaimStore(kit["store"])
    kwargs = _fixture_kwargs(kit)
    kwargs["outcome_store"] = burner
    with pytest.raises(RuntimeError, match="materialisation failure"):
        run_phase2b_fixture(**kwargs)
    # the audit was burned (access consumed) and a failure terminal exists.
    assert kit["store"].sealed_access_count == 1
    artifacts = _terminal_artifacts(kit["run_dir"])
    assert len(artifacts) == 1
    body = json.loads(artifacts[0].read_text())
    assert body["terminal_state"] == TerminalState.ABORTED_AFTER_SEAL.value


# ===========================================================================
# 11. provenance tampering (post-access run-id/audit mismatch) → INVALID
# ===========================================================================


def test_provenance_tamper_yields_invalid(tmp_path):
    kit = _make_run(tmp_path)
    # A provenance record whose self-checksum will NOT match what the orchestrator
    # registered before access → post-access consistency returns INVALID.
    tampered = dataclasses.replace(kit["provenance"], processed_sha256="TAMPERED-AFTER-REGISTER")
    res = run_phase2b_fixture(
        **_fixture_kwargs(kit),
        _tamper_provenance_after_register=tampered,
    )
    assert res.terminal_state == TerminalState.INVALID
    assert res.sealed_verdict.sealed_axis == SealedAxis.INVALID
    # the seal was still consumed exactly once.
    assert res.sealed_access_count == 1
    artifacts = _terminal_artifacts(kit["run_dir"])
    assert artifacts == [kit["run_dir"] / Phase2bTerminal.INVALID_ARTIFACT]


# ===========================================================================
# 12. no terminal artifact contains a raw outcome array
# ===========================================================================


def _iter_numbers(obj):
    """Yield every numeric scalar at any nesting depth (for matrix-shape checks)."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_numbers(v)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield obj


def test_no_terminal_artifact_carries_raw_outcomes(tmp_path):
    kit = _make_run(tmp_path)
    run_phase2b_fixture(**_fixture_kwargs(kit))
    for path in _terminal_artifacts(kit["run_dir"]):
        body = json.loads(path.read_text())

        # walk for a raw 2-D cell/observation matrix or oversized numeric vector.
        def _walk(node):
            if isinstance(node, list):
                if len(node) > 64 and all(
                    isinstance(x, (int, float)) and not isinstance(x, bool) for x in node
                ):
                    raise AssertionError("oversized numeric list found in terminal artifact")
                if len(node) >= 4 and all(
                    isinstance(r, list)
                    and len(r) >= 4
                    and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in r)
                    for r in node
                ):
                    raise AssertionError("raw cell matrix found in terminal artifact")
                for v in node:
                    _walk(v)
            elif isinstance(node, dict):
                for v in node.values():
                    _walk(v)

        _walk(body)


# ===========================================================================
# 13. result / report / ledger hashes verify (round-trip)
# ===========================================================================


def test_terminal_and_ledger_hashes_round_trip(tmp_path):
    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))

    complete = kit["run_dir"] / Phase2bTerminal.COMPLETE_ARTIFACT
    assert complete.exists()
    body = json.loads(complete.read_text())

    # the result reports the terminal/report checksum that matches the file's hash.
    from alive.provenance import sha256_file

    file_sha = sha256_file(complete)
    # the ledger recorded the terminal artifact under its canonical name.
    assert res.ledger.artifact_sha(Phase2bTerminal.COMPLETE_ARTIFACT) == file_sha
    assert res.ledger.verify_file(Phase2bTerminal.COMPLETE_ARTIFACT, complete)
    # the result's recorded checksums are present in the persisted body.
    assert body["sealed_verdict_checksum"] == res.sealed_verdict.checksum
    assert res.result_checksum  # non-empty


# ===========================================================================
# 14. a futility-stopped bundle cannot invoke Phase 2b (refused before access)
# ===========================================================================


def test_futility_stopped_bundle_refused_before_access(tmp_path):
    kit = _make_run(tmp_path, futility_status="FUTILITY_STOPPED")
    with pytest.raises(PreflightError, match="futility|CONTINUE"):
        run_phase2b_fixture(**_fixture_kwargs(kit))
    assert kit["store"].sealed_access_count == 0
    assert _terminal_artifacts(kit["run_dir"]) == []


# ===========================================================================
# scientific entry enforces activation on the BLOCKED candidate config
# ===========================================================================


def _activation_record(cfg):
    from alive.compose.config2 import ActivationRecord

    return ActivationRecord(
        owner="owner",
        approved_protocol=cfg.protocol,
        approved_phase=cfg.phase,
        evidence_hashes={req: "h" for req in cfg.activation_requirements},
    )


def test_scientific_entry_blocked_config_raises(tmp_path):
    # Safety invariant preserved after the 2026-06-30 activation: a BLOCKED config
    # is refused by the scientific entry point before the seal is ever opened. The
    # canonical config is now ``active``, so a synthetic blocked config pins this.
    kit = _make_run(tmp_path, fixture_store=False)
    blocked_cfg = dataclasses.replace(kit["cfg"], status="preregistered_activation_blocked")
    with pytest.raises(ScientificModeError):
        run_phase2b(
            run_dir=kit["run_dir"],
            outcome_store=kit["store"],
            frozen_bundle=kit["bundle"],
            pair_manifest=kit["manifest"],
            response_artifact=kit["response_artifact"],
            config=blocked_cfg,
            ledger=kit["ledger"],
            activation_record=_activation_record(kit["cfg"]),
            git_is_clean=True,
        )
    # the blocked config means the seal never opened.
    assert kit["store"].sealed_access_count == 0
    assert _terminal_artifacts(kit["run_dir"]) == []


def test_scientific_entry_rejects_fixture_store(tmp_path):
    kit = _make_run(tmp_path, fixture_store=True)
    # a synthetic-fixture store is not scientific evidence and is refused by the
    # scientific entry point even under an active config with a full activation
    # record — the fixture path (`run_phase2b_fixture`) is the only synthetic entry.
    with pytest.raises((ScientificModeError, PreflightError, ComposeSealingError)):
        run_phase2b(
            run_dir=kit["run_dir"],
            outcome_store=kit["store"],
            frozen_bundle=kit["bundle"],
            pair_manifest=kit["manifest"],
            response_artifact=kit["response_artifact"],
            config=kit["cfg"],
            ledger=kit["ledger"],
            activation_record=_activation_record(kit["cfg"]),
            git_is_clean=True,
        )
    assert kit["store"].sealed_access_count == 0
