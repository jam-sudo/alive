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
import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import pytest

from alive.compose.approximation_bias import (
    APPROXIMATION_BIAS_SCHEMA,
    PROBE_A_ADAPTER_TRANSFORM,
    PROBE_A_NEGATIVE_OUTPUT_POLICY,
    PROBE_A_REGISTRATION_SCHEMA,
    PROBE_A_REPRESENTATION,
    PROBE_A_SCHEMA,
    PROBE_A_VERIFICATION_SCHEMA,
    PROTOCOL,
    REPRESENTATION,
    ApproximationBiasEvidence,
    ProbeAEvidence,
    canonical_json,
    load_approximation_bias_report,
    measurement_contract_sha256,
    probe_a_owner_policy_sha256,
    self_checksum,
)
from alive.compose.config2 import (
    _EXPECTED_METHOD_ROSTER,
    ScientificModeError,
    load_compose_phase2_config,
)
from alive.compose.datacard import compute_compose_run_id
from alive.compose.durable import (
    COMMIT_CHECKSUM_FIELD,
    DURABLE_COMMIT_FILENAME,
    DurableLedgerError,
    recover_phase2b_durable_outputs,
)
from alive.compose.freeze import FrozenPredictionBundle
from alive.compose.outcome_store import (
    FIXTURE_CORPUS_V1,
    ComposeOutcomeStore,
    ComposeSealingError,
    FixtureCorpusAttestation,
    FixtureOutcomeStore,
    ObservedPair,
    build_fixture_outcome_store,
)
from alive.compose.preflight import PreflightError
from alive.compose.provenance2 import (
    PRE_ACCESS_LEDGER_FILENAME,
    PRE_ACCESS_PROVENANCE_ARTIFACT,
    Phase2bProvenance,
)
from alive.compose.response import fit_response_space
from alive.compose.scoring2 import RegimeScore
from alive.compose.seed_variability import (
    DEVELOPMENT_SEED_VARIABILITY_FILENAME,
    DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT,
)
from alive.compose.split import build_split_manifest
from alive.compose.terminal import Phase2bTerminal, TerminalState
from alive.compose.verdict2 import MethodAxis, SealedAxis
from alive.provenance import EnvironmentInfo, RunLedger, sha256_bytes, sha256_file, sha256_json

from alive.compose.phase2b import (  # isort: skip
    ActivationProvenanceInputs,
    ApproximationBiasReportError,
    Phase2bError,
    Phase2bResult,
    _build_provenance,
    _is_fixture_store,
    _load_approximation_bias_fairness,
    _preaccess_seed_variability,
    _run_phase2b_core,
    build_activation_provenance_inputs,
    build_registered_evaluation_summary,
    run_phase2b,
    run_phase2b_fixture,
)

_CONFIG_PATH = "configs/compose_k562_v1_phase2.yaml"
_ACTIVATION_EVIDENCE_FILES = {
    "real_norman_phi_rank_and_condition_report": (
        "docs/activation-evidence/compose/real_norman_phi_rank_report.json"
    ),
    "regime_specific_detectable_effect_analysis": (
        "docs/activation-evidence/compose/real_norman_detectable_effect_report.json"
    ),
    "finalized_norman_data_card_and_sha256": "docs/data-cards/norman_compose_k562_v1.json",
    "gears_cpa_reproducible_dependency_lock": (
        "docs/activation-evidence/compose/gears_cpa_dependency_lock.json"
    ),
    "independent_compose_outcome_store_and_access_audit": "src/alive/compose/outcome_store.py",
    "phase2_plan_metric_leakage_and_seal_integration_tests": "tests/alive/compose/test_phase2b.py",
}

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
    """Build a Compose outcome store over a synthetic in-memory source.

    Tests NEVER hand truth to ``run_phase2b*`` — the store hides the source. When
    ``fixture=True`` the store is a :class:`FixtureOutcomeStore` minted by the
    sanctioned :func:`build_fixture_outcome_store` (allowlisted attestation), which
    ``run_phase2b_fixture`` accepts by TYPE without owner activation. When
    ``fixture=False`` it is a plain scientific :class:`ComposeOutcomeStore`.
    """
    source, pair_index = _build_source_and_index(manifest)
    if fixture:
        return build_fixture_outcome_store(
            pair_index=pair_index,
            source=source,
            manifest=manifest,
            audit_path=audit_path,
            corpus_id=FIXTURE_CORPUS_V1.corpus_id,
            source_sha256=FIXTURE_CORPUS_V1.source_sha256,
            builder_code_sha256=FIXTURE_CORPUS_V1.builder_code_sha256,
        )
    return ComposeOutcomeStore(
        pair_index=pair_index,
        source=source,
        manifest=manifest,
        audit_path=audit_path,
    )


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
        "l3_symmetric_mlp",
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
        out["l3_symmetric_mlp"][pid] = additive_pred + 5.0 * rng.normal(size=response_dim)
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
    model_artifact_checksums = {
        name: sha256_json({"fixture_model": name})
        for name in cfg.method_roster
        if name not in {"additive", "no_change", "perturbation_mean"}
    }
    model_checksum = sha256_json(
        {
            "schema": "compose_model_set_v1",
            "methods": model_artifact_checksums,
            "selected_k_total": 4,
            "selected_lambda": float(0.01).hex(),
        }
    )
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
        model_checksum=model_checksum,
        model_artifact_checksums=model_artifact_checksums,
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
    ledger.record_artifact("data_card", _DATA_CARD)
    ledger.record_artifact("raw_data", _RAW)
    ledger.record_artifact("sequence_mapping", _SEQ)
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


def _read_terminal(run_dir: Path, which: str) -> dict:
    """Load a written terminal artifact body (``"complete"`` or ``"invalid"``)."""
    name = {
        "complete": Phase2bTerminal.COMPLETE_ARTIFACT,
        "invalid": Phase2bTerminal.INVALID_ARTIFACT,
    }[which]
    return json.loads((run_dir / name).read_text(encoding="utf-8"))


def _flatten_keys(obj) -> list[str]:
    """Every mapping key at any nesting depth (for per-pair / *_ci leakage checks)."""
    keys: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            keys.append(key)
            keys.extend(_flatten_keys(value))
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            keys.extend(_flatten_keys(value))
    return keys


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
    bad_ledger.record_artifact("data_card", _DATA_CARD)
    bad_ledger.record_artifact("raw_data", _RAW)
    bad_ledger.record_artifact("sequence_mapping", _SEQ)
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


@pytest.mark.parametrize("drop", ["gears", "cpa", "id_only", "l3_symmetric_mlp"])
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


class _SpyStore(FixtureOutcomeStore):
    """A FixtureOutcomeStore that records the access order of sealed calls.

    Rebuilt over the wrapped store's own source/index/manifest/audit so it stays a
    genuine (allowlisted) fixture store — the bounded fixture path accepts it by
    TYPE — and it spies by overriding ONLY the sealed-access methods.
    """

    def __init__(self, inner: ComposeOutcomeStore) -> None:
        super().__init__(
            inner._pair_index,
            inner._source,
            inner._manifest,
            audit_path=inner._audit_path,
            fixture_corpus_attestation=FIXTURE_CORPUS_V1,
        )
        self.events: list[str] = []

    def claim_sealed_access(self, run_id, pair_ids):
        self.events.append("claim_sealed_access")
        return super().claim_sealed_access(run_id, pair_ids)

    def materialize_claimed(self, claim):
        self.events.append("materialize_claimed")
        return super().materialize_claimed(claim)

    def read_unsealed(self, pair_ids):  # pragma: no cover - defensive
        self.events.append("read_unsealed")
        return super().read_unsealed(pair_ids)


def test_predictions_consumed_readonly_no_access_until_step_six(tmp_path):
    kit = _make_run(tmp_path)
    spy = _SpyStore(kit["store"])
    pre_checksum = kit["bundle"].bundle_checksum

    kwargs = _fixture_kwargs(kit)
    kwargs["outcome_store"] = spy
    res = run_phase2b_fixture(**kwargs)

    # the durable claim then materialisation are the only sealed events, and the
    # bundle was not mutated (consumed read-only).
    assert spy.events == ["claim_sealed_access", "materialize_claimed"]
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


def test_scientific_verdict_requires_registered_power_floor_after_scoring(tmp_path):
    from alive.compose.phase2b import _minimum_scored_headline_pairs

    kit = _make_run(tmp_path)
    assert kit["cfg"].sealed_minimum_n == 1
    assert _minimum_scored_headline_pairs(kit["cfg"], fixture_execution=True) == 1
    assert _minimum_scored_headline_pairs(kit["cfg"], fixture_execution=False) == 20


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
    store_b = build_fixture_outcome_store(
        pair_index=index_a,
        source=_InMemorySource(X),
        manifest=manifest,
        audit_path=audit_path,
        corpus_id=FIXTURE_CORPUS_V1.corpus_id,
        source_sha256=FIXTURE_CORPUS_V1.source_sha256,
        builder_code_sha256=FIXTURE_CORPUS_V1.builder_code_sha256,
    )

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


class _EmptyCellsStore(FixtureOutcomeStore):
    """A fixture store whose release returns an empty (0-row) observed population.

    The seal opens normally (the audit is burned by the inherited claim), but
    ``score_regime`` rejects the empty population AFTER access — a genuine
    post-access scoring failure that the terminal protection boundary must turn
    into a failure artifact. Only ``materialize_claimed`` is overridden.
    """

    def __init__(self, inner: ComposeOutcomeStore) -> None:
        super().__init__(
            inner._pair_index,
            inner._source,
            inner._manifest,
            audit_path=inner._audit_path,
            fixture_corpus_attestation=FIXTURE_CORPUS_V1,
        )

    def materialize_claimed(self, claim):
        release = super().materialize_claimed(claim)
        return {pid: ObservedPair(pair_id=pid, cells=op.cells[:0]) for pid, op in release.items()}


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


class _RaisingAfterClaimStore(FixtureOutcomeStore):
    """A fixture store whose durable claim burns the audit (inherited), then
    materialisation raises — the worst case the terminal boundary must survive
    (ABORTED_AFTER_SEAL). Only ``materialize_claimed`` is overridden.
    """

    def __init__(self, inner: ComposeOutcomeStore) -> None:
        super().__init__(
            inner._pair_index,
            inner._source,
            inner._manifest,
            audit_path=inner._audit_path,
            fixture_corpus_attestation=FIXTURE_CORPUS_V1,
        )

    def materialize_claimed(self, claim):
        # Fail AFTER the audit is on disk (the inherited claim already burned it).
        raise RuntimeError("synthetic materialisation failure")


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
    # the result's recorded checksums are present in the persisted body. The
    # sealed verdict checksum is now the top-level state field final_verdict_checksum
    # (COMPLETE: the final verdict IS the sealed verdict).
    assert body["final_verdict_checksum"] == res.sealed_verdict.checksum
    assert res.result_checksum  # non-empty


# ===========================================================================
# 13b. COMPLETE terminal embeds the outcome-free registered summary + the
#      layered final_result_checksum; INVALID differs from COMPLETE (D1 Task 3)
# ===========================================================================


def test_complete_terminal_embeds_summary_and_final_result_checksum(tmp_path):
    kit = _make_run(tmp_path)
    result = run_phase2b_fixture(**_fixture_kwargs(kit))
    assert result.terminal_state == TerminalState.COMPLETE

    body = _read_terminal(kit["run_dir"], "complete")
    summ = body["registered_summary"]
    assert set(summ) >= {
        "per_method_aggregate_mse",
        "theta",
        "simultaneous_lower_bounds",
        "family_confidence",
        "bootstrap_replicates",
        "gi_explained_interval",
        "gi_structure_recovery",
        "sample_counts",
        "seed_variability_report_checksum",
    }
    assert summ["gi_structure_recovery"] == "NOT_EVALUABLE"
    # per_method_aggregate_mse is a regime-labeled mapping (mirrors sample_counts):
    # both the double (headline / verdict-linked) AND single (registered secondary,
    # §10) regimes are present, regime-labeled, scored INDEPENDENTLY and NEVER
    # pooled into one flat method->mse map.
    pmm = summ["per_method_aggregate_mse"]
    assert set(pmm) == {"double", "single"}
    assert set(pmm["double"]) == set(pmm["single"])
    assert pmm["single"] != pmm["double"]
    # no per-pair error array or per-pair CI leaks into the terminal payload.
    assert not any("per_pair" in k or k.endswith("_ci") for k in _flatten_keys(body))

    # the inner content checksums bind their in-process dicts.
    assert body["registered_summary_checksum"] == sha256_json(summ)
    assert body["final_result_checksum"] == sha256_json(
        {
            "terminal_state": body["terminal_state"],
            "final_verdict_checksum": body["final_verdict_checksum"],
            "registered_summary_checksum": body["registered_summary_checksum"],
            "evaluation_payload_checksum": body["evaluation_payload_checksum"],
            "provenance_checksum": body["provenance_checksum"],
        }
    )
    # Phase2bResult.result_checksum IS the layered final_result_checksum.
    assert result.result_checksum == body["final_result_checksum"]


def test_the_sealed_result_carries_the_band_sensitivity_computed_from_the_headline_bounds(
    tmp_path,
):
    """Amendment B (signed 2026-09-05): one computation, from the bounds the verdict used.

    The sensitivity is descriptive-only and never a verdict gate; what makes it
    honest is that it is computed inside the sealed run from the SAME
    `regime_double.bounds` the verdict was decided on, not re-derived later from
    a report. `lower_by_lambda[1.0]` is therefore the registered bounds exactly.
    """
    from alive.compose.inference2 import band_sensitivity

    kit = _make_run(tmp_path)
    result = run_phase2b_fixture(**_fixture_kwargs(kit))
    cfg = kit["cfg"]

    expected = band_sensitivity(
        bounds=result.regime_double.bounds,
        band_inflation=cfg.sensitivity_band_inflation,
        additive_margin=cfg.material_margin_vs_additive,
        learned_margin=cfg.learned_comparator_margin,
    )
    assert result.band_sensitivity == expected
    assert result.band_sensitivity.lower_by_lambda[1.0] == result.regime_double.bounds.lower


def test_the_terminal_carries_the_sensitivity_outside_the_result_checksum_with_its_own_checksum(
    tmp_path,
):
    """Amendment B: where the sensitivity is recorded, and what it is NOT part of.

    It is written into the terminal report body as `band_sensitivity` with its own
    `band_sensitivity_checksum`; `final_result_checksum` keeps its exact five-field
    composition, so a descriptive report never enters the run's registered
    identity (the opposite of what the pair-dependence decision says).
    """
    kit = _make_run(tmp_path)
    result = run_phase2b_fixture(**_fixture_kwargs(kit))
    body = _read_terminal(kit["run_dir"], "complete")

    block = body["band_sensitivity"]
    assert block["schema"] == "compose_band_sensitivity_v1"
    assert block["descriptive_only"] is True
    ladder = [entry["lambda"] for entry in block["by_lambda"]]
    assert ladder == [float(x) for x in kit["cfg"].sensitivity_band_inflation]
    assert block["by_lambda"][0]["lower"] == pytest.approx(result.regime_double.bounds.lower)
    assert body["band_sensitivity_checksum"] == sha256_json(block)
    assert body["final_result_checksum"] == sha256_json(
        {
            "terminal_state": body["terminal_state"],
            "final_verdict_checksum": body["final_verdict_checksum"],
            "registered_summary_checksum": body["registered_summary_checksum"],
            "evaluation_payload_checksum": body["evaluation_payload_checksum"],
            "provenance_checksum": body["provenance_checksum"],
        }
    )


def test_per_method_aggregate_mse_reports_both_regimes_unpooled(tmp_path):
    # §10 registered-secondary completeness: the summary must report the per-method
    # aggregate MSE for BOTH the double-unseen (headline / verdict-linked) AND the
    # single-unseen (registered secondary) regimes — regime-labeled, scored
    # INDEPENDENTLY, and NEVER pooled. Under-reporting only the double regime would
    # silently drop the §10 registered secondary.
    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))
    assert res.terminal_state == TerminalState.COMPLETE

    body = _read_terminal(kit["run_dir"], "complete")
    per_method = body["registered_summary"]["per_method_aggregate_mse"]

    # regime-labeled mapping mirroring sample_counts: {"double": {...}, "single": {...}}.
    assert set(per_method) == {"double", "single"}
    assert isinstance(per_method["double"], dict)
    assert isinstance(per_method["single"], dict)

    # both regimes carry the SAME (full 9-method) DESCRIPTIVE roster; per-method,
    # never per-pair. The verdict pair_errors (6) are a subset; the aggregate MSE
    # surfaces every roster method via descriptive_pair_errors.
    assert set(per_method["double"]) == set(per_method["single"])
    assert set(per_method["single"]) == set(res.regime_single.descriptive_pair_errors)

    # each embedded value is the INDEPENDENT per-regime mean over THAT regime's own
    # descriptive_pair_errors — proving it is regime-labeled, aggregate-scalar and
    # NOT pooled.
    for method in sorted(res.regime_single.descriptive_pair_errors):
        expected_double = float(np.mean(res.regime_double.descriptive_pair_errors[method]))
        expected_single = float(np.mean(res.regime_single.descriptive_pair_errors[method]))
        assert per_method["double"][method] == pytest.approx(expected_double)
        assert per_method["single"][method] == pytest.approx(expected_single)
        # a finite aggregate scalar, never a per-pair array.
        assert isinstance(per_method["single"][method], float)
        assert np.isfinite(per_method["single"][method])
        # NOT pooled: a mean over the union of both regimes would differ from the
        # single-regime mean (the regimes score disjoint pairs).
        pooled = float(
            np.mean(
                np.concatenate(
                    [
                        res.regime_double.descriptive_pair_errors[method],
                        res.regime_single.descriptive_pair_errors[method],
                    ]
                )
            )
        )
        assert per_method["single"][method] != pytest.approx(pooled)

    # single is a DISTINCT dict from double (independent regimes).
    assert per_method["single"] != per_method["double"]


def test_per_method_aggregate_mse_covers_full_roster_both_regimes(tmp_path):
    # The descriptive per-method aggregate MSE must span the FULL 9-method roster in
    # BOTH regimes (not just the 6 verdict methods): freeze validates all nine per
    # regime, so l2_saturation / no_change / perturbation_mean are reported
    # descriptively even though the verdict consumes only headline + 5 comparators.
    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))
    assert res.terminal_state == TerminalState.COMPLETE

    body = _read_terminal(kit["run_dir"], "complete")
    pmm = body["registered_summary"]["per_method_aggregate_mse"]
    assert set(pmm["double"]) == set(_EXPECTED_METHOD_ROSTER)
    assert set(pmm["single"]) == set(_EXPECTED_METHOD_ROSTER)


def test_registered_summary_has_schema_v1(tmp_path):
    # The registered summary carries a versioned schema tag so downstream durable
    # finalization (Task 6) can version-gate it. Task 5 only ADDS the tag.
    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))
    assert res.terminal_state == TerminalState.COMPLETE

    body = _read_terminal(kit["run_dir"], "complete")
    assert body["registered_summary"]["schema"] == "compose_registered_evaluation_summary_v1"


def test_invalid_final_result_checksum_differs_from_complete(tmp_path):
    # A clean COMPLETE run and a post-access-tampered INVALID run from the SAME
    # inputs must not share a final_result_checksum (terminal_state + final
    # verdict differ), and INVALID must not reuse the normal verdict checksum.
    kit_c = _make_run(tmp_path / "complete")
    complete = run_phase2b_fixture(**_fixture_kwargs(kit_c))
    assert complete.terminal_state == TerminalState.COMPLETE

    kit_i = _make_run(tmp_path / "invalid")
    tampered = dataclasses.replace(kit_i["provenance"], processed_sha256="TAMPERED-AFTER-REGISTER")
    invalid = run_phase2b_fixture(
        **_fixture_kwargs(kit_i),
        _tamper_provenance_after_register=tampered,
    )
    assert invalid.terminal_state == TerminalState.INVALID

    assert invalid.result_checksum != complete.result_checksum
    inv_body = _read_terminal(kit_i["run_dir"], "invalid")
    assert inv_body["terminal_state"] == TerminalState.INVALID.value
    assert inv_body["final_result_checksum"] == invalid.result_checksum

    # WHY the checksums differ: the `!=` above would ALSO hold merely because the
    # two runs live in different run dirs (different seal_audit_reference ->
    # different provenance_checksum), even if terminal_state / verdict were NOT
    # bound into final_result_checksum. Reconstruct the INVALID checksum from its
    # OWN five composition keys (mirroring the COMPLETE composition test) to prove
    # terminal_state="INVALID" + the swapped final_verdict_checksum are the bound
    # inputs, not an incidental run-dir difference.
    assert inv_body["final_result_checksum"] == sha256_json(
        {
            "terminal_state": inv_body["terminal_state"],
            "final_verdict_checksum": inv_body["final_verdict_checksum"],
            "registered_summary_checksum": inv_body["registered_summary_checksum"],
            "evaluation_payload_checksum": inv_body["evaluation_payload_checksum"],
            "provenance_checksum": inv_body["provenance_checksum"],
        }
    )
    # The verdict->INVALID swap is bound: this INVALID body's final_verdict_checksum
    # differs from the COMPLETE run's, so the difference is attributable to the
    # terminal_state + swapped verdict, not just the run dir / provenance.
    complete_body = _read_terminal(kit_c["run_dir"], "complete")
    assert inv_body["final_verdict_checksum"] != complete_body["final_verdict_checksum"]


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
        approved_git_sha="0" * 40,
        approved_sequence_mapping_sha256=json.loads(
            Path(_ACTIVATION_EVIDENCE_FILES["real_norman_phi_rank_and_condition_report"]).read_text(
                encoding="utf-8"
            )
        )["sequence_mapping_sha256"],
        evidence_hashes={
            req: "sha256:"
            + hashlib.sha256(Path(_ACTIVATION_EVIDENCE_FILES[req]).read_bytes()).hexdigest()
            for req in cfg.activation_requirements
        },
        evidence_files=dict(_ACTIVATION_EVIDENCE_FILES),
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


def test_scientific_entry_requires_pinned_bias_evidence_before_seal(tmp_path, monkeypatch):
    """The public library entry cannot bypass the driver's pre-seal report carrier."""
    kit = _make_run(tmp_path, fixture_store=False)
    pinned_sha = "a" * 64
    cfg = dataclasses.replace(
        kit["cfg"],
        power_status="established",
        baseline_activation_statuses=tuple(
            (name, revision or "pinned-revision", "pinned")
            for name, revision, _status in kit["cfg"].baseline_activation_statuses
        ),
        baseline_representations=tuple(
            (name, representation, pinned_sha if name == "gears" else bias)
            for name, representation, bias in kit["cfg"].baseline_representations
        ),
    )
    assert cfg.pseudobulk_representation_activation_blocked is False
    # Isolate the evidence boundary after activation: the production activation guard
    # has its own exhaustive suite, while the canonical config is intentionally still
    # blocked until pod evidence exists.
    monkeypatch.setattr(
        "alive.compose.phase2b.assert_scientific_mode_allowed",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(ApproximationBiasReportError, match="no immutable report"):
        run_phase2b(
            run_dir=kit["run_dir"],
            outcome_store=kit["store"],
            frozen_bundle=kit["bundle"],
            pair_manifest=kit["manifest"],
            response_artifact=kit["response_artifact"],
            config=cfg,
            ledger=kit["ledger"],
            activation_record=_activation_record(kit["cfg"]),
            git_is_clean=True,
            approximation_bias_report_evidence=None,
        )
    assert kit["store"].sealed_access_count == 0
    assert _terminal_artifacts(kit["run_dir"]) == []


# ===========================================================================
# C0 #4: dedicated FixtureOutcomeStore type + corpus allowlist (retire marker)
# ===========================================================================


def _plain_and_fixture_stores(tmp_path):
    """A plain scientific store and a sanctioned fixture store over fresh audits."""
    manifest = _manifest()
    source_r, index_r = _build_source_and_index(manifest)
    real = ComposeOutcomeStore(
        pair_index=index_r,
        source=source_r,
        manifest=manifest,
        audit_path=tmp_path / "real_audit.jsonl",
    )
    source_f, index_f = _build_source_and_index(manifest)
    fixture = build_fixture_outcome_store(
        pair_index=index_f,
        source=source_f,
        manifest=manifest,
        audit_path=tmp_path / "fix_audit.jsonl",
        corpus_id=FIXTURE_CORPUS_V1.corpus_id,
        source_sha256=FIXTURE_CORPUS_V1.source_sha256,
        builder_code_sha256=FIXTURE_CORPUS_V1.builder_code_sha256,
    )
    return real, fixture


def test_is_fixture_store_true_only_for_fixture_type(tmp_path):
    real, fixture = _plain_and_fixture_stores(tmp_path)
    # a real scientific store is NOT a fixture store...
    assert _is_fixture_store(real) is False
    # ...and the retired spoof (setting the old marker on a real store) is inert.
    object.__setattr__(real, "_compose_fixture_marker", True)
    assert _is_fixture_store(real) is False
    # only a sanctioned FixtureOutcomeStore with an allowlisted attestation passes.
    assert _is_fixture_store(fixture) is True


def test_is_fixture_store_rejects_bogus_attestation(tmp_path):
    # isinstance alone is INSUFFICIENT: a raw FixtureOutcomeStore built with a
    # non-allowlisted attestation must NOT read as a fixture store.
    manifest = _manifest()
    source, pair_index = _build_source_and_index(manifest)
    bogus = FixtureCorpusAttestation(
        corpus_id="nope", source_sha256="0" * 64, builder_code_sha256="0" * 64
    )
    store = FixtureOutcomeStore(
        pair_index,
        source,
        manifest,
        audit_path=tmp_path / "bogus_audit.jsonl",
        fixture_corpus_attestation=bogus,
    )
    assert isinstance(store, FixtureOutcomeStore)
    assert _is_fixture_store(store) is False


def test_run_phase2b_fixture_rejects_spoofed_marker(tmp_path):
    # A plain store with a manually-set legacy marker must NOT pass the bounded
    # fixture entry anymore (the marker is retired; type + allowlist decides).
    kit = _make_run(tmp_path, fixture_store=False)
    object.__setattr__(kit["store"], "_compose_fixture_marker", True)
    with pytest.raises(Phase2bError, match="fixture"):
        run_phase2b_fixture(**_fixture_kwargs(kit))
    assert kit["store"].sealed_access_count == 0
    assert _terminal_artifacts(kit["run_dir"]) == []


def test_run_phase2b_rejects_fixture_type(tmp_path):
    # The scientific entry refuses a synthetic-fixture store even when every OTHER
    # scientific-mode gate is satisfied: a fixture TYPE is not scientific evidence.
    # Unblock the UNRELATED pseudobulk-representation activation gate so the
    # fixture-type check (the behavior under test) is the only remaining barrier.
    kit = _make_run(tmp_path, fixture_store=True)
    cfg = dataclasses.replace(
        kit["cfg"], baseline_representations=(("additive", "cell_raw_counts", None),)
    )
    assert cfg.pseudobulk_representation_activation_blocked is False
    with pytest.raises(ScientificModeError, match="fixture"):
        run_phase2b(
            run_dir=kit["run_dir"],
            outcome_store=kit["store"],
            frozen_bundle=kit["bundle"],
            pair_manifest=kit["manifest"],
            response_artifact=kit["response_artifact"],
            config=cfg,
            ledger=kit["ledger"],
            activation_record=_activation_record(kit["cfg"]),
            git_is_clean=True,
        )
    assert kit["store"].sealed_access_count == 0
    assert _terminal_artifacts(kit["run_dir"]) == []


# ===========================================================================
# Change B: _build_provenance digest population
# ===========================================================================


def _prov_inputs() -> ActivationProvenanceInputs:
    return ActivationProvenanceInputs(
        processed_sha256="1" * 64,
        feature_bank_sha256="2" * 64,
        dependency_lock_sha256="3" * 64,
        gears_revision="gears-9",
        cpa_revision="cpa-9",
        python_version="fixture",
        platform="fixture",
        device="cuda",
        precision="float32",
        git_commit="0" * 40,
    )


def test_build_provenance_fixture_leaves_scientific_digests_empty(tmp_path):
    kit = _make_run(tmp_path)
    prov = _build_provenance(
        bundle=kit["bundle"],
        pair_manifest=kit["manifest"],
        config=kit["cfg"],
        audit_reference="ref",
        regime_double=None,
        regime_single=None,
        git_clean=True,
        ledger=kit["ledger"],
        inputs=None,
        fixture_execution=True,
    )
    # run-IDENTITY digests come from the ledger on BOTH paths (single source of
    # truth) so the durable ledger<->provenance cross-check holds on the fixture
    # path; the scientific EVIDENCE digests stay empty (a fixture is not evidence).
    assert prov.data_card_sha256 == _DATA_CARD
    assert prov.raw_or_source_sha256 == _RAW
    assert prov.sequence_mapping_sha256 == _SEQ
    assert prov.processed_sha256 == ""
    assert prov.feature_bank_sha256 == ""
    assert prov.dependency_lock_sha256 == ""
    assert prov.gears_revision == ""
    assert prov.cpa_revision == ""
    assert prov.python_version == ""
    assert prov.platform == ""
    assert prov.device == ""
    assert prov.precision == ""
    assert prov.git_commit == "UNKNOWN"
    # upstream (bundle-derived) hashes are still populated on the fixture path.
    assert prov.frozen_prediction_bundle_sha256 == kit["bundle"].bundle_checksum


def test_build_provenance_scientific_requires_inputs(tmp_path):
    kit = _make_run(tmp_path)
    with pytest.raises(Phase2bError, match="ActivationProvenanceInputs"):
        _build_provenance(
            bundle=kit["bundle"],
            pair_manifest=kit["manifest"],
            config=kit["cfg"],
            audit_reference="ref",
            regime_double=None,
            regime_single=None,
            git_clean=True,
            ledger=kit["ledger"],
            inputs=None,
            fixture_execution=False,
        )


def test_build_provenance_scientific_populates_from_ledger_and_inputs(tmp_path):
    kit = _make_run(tmp_path)
    ledger = kit["ledger"]
    # Single source of truth: run-identity digests come from the upstream ledger
    # (recorded by the shared _build_ledger as _DATA_CARD / _RAW / _SEQ).
    prov = _build_provenance(
        bundle=kit["bundle"],
        pair_manifest=kit["manifest"],
        config=kit["cfg"],
        audit_reference="ref",
        regime_double=None,
        regime_single=None,
        git_clean=True,
        ledger=ledger,
        inputs=_prov_inputs(),
        fixture_execution=False,
    )
    # from the ledger (run-identity path):
    assert prov.data_card_sha256 == _DATA_CARD
    assert prov.raw_or_source_sha256 == _RAW
    assert prov.sequence_mapping_sha256 == _SEQ
    # from the inputs object (evidence-sourced digests):
    assert prov.processed_sha256 == "1" * 64
    assert prov.feature_bank_sha256 == "2" * 64
    assert prov.dependency_lock_sha256 == "3" * 64
    assert prov.gears_revision == "gears-9"
    assert prov.cpa_revision == "cpa-9"
    assert prov.device == "cuda"
    assert prov.precision == "float32"
    assert prov.git_commit == "0" * 40


# ===========================================================================
# Change C: pre-access provenance subset is PERSISTED write-once before access
# ===========================================================================


def test_pre_access_provenance_persisted_in_ledger(tmp_path):
    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))
    # The pre-access digest-subset checksum is recorded write-once BEFORE the seal
    # opens, so the post-access provenance leg cross-checks a PERSISTED value.
    persisted = res.ledger.artifact_sha(PRE_ACCESS_PROVENANCE_ARTIFACT)
    assert isinstance(persisted, str) and len(persisted) == 64
    snapshot = RunLedger.read(kit["run_dir"] / PRE_ACCESS_LEDGER_FILENAME)
    assert snapshot.artifact_sha(PRE_ACCESS_PROVENANCE_ARTIFACT) == persisted


@pytest.mark.parametrize(
    "field,value",
    [
        ("processed_sha256", "not-a-digest"),
        ("feature_bank_sha256", ""),
        ("dependency_lock_sha256", "A" * 64),
        ("gears_revision", ""),
        ("git_commit", "short"),
    ],
)
def test_activation_provenance_inputs_reject_malformed_values(field, value):
    values = dataclasses.asdict(_prov_inputs())
    values[field] = value
    with pytest.raises(ValueError):
        ActivationProvenanceInputs(**values)


def test_build_provenance_rejects_environment_mismatch(tmp_path):
    kit = _make_run(tmp_path)
    ledger = kit["ledger"]
    # run-identity digests are already recorded by the shared _build_ledger.
    values = dataclasses.asdict(_prov_inputs())
    values["git_commit"] = "f" * 40
    with pytest.raises(Phase2bError, match="ledger environment"):
        _build_provenance(
            bundle=kit["bundle"],
            pair_manifest=kit["manifest"],
            config=kit["cfg"],
            audit_reference="ref",
            regime_double=None,
            regime_single=None,
            git_clean=True,
            ledger=ledger,
            inputs=ActivationProvenanceInputs(**values),
            fixture_execution=False,
        )


def _declared(path: Path) -> tuple[Path, str]:
    """``(path, sha256)`` as the validated run spec would declare it -- the boundary's shape."""
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_activation_provenance_inputs_hashes_real_files(tmp_path):
    processed = tmp_path / "processed.h5ad"
    feature_bank = tmp_path / "features.json"
    dependency = tmp_path / "dependency.json"
    gears = tmp_path / "gears.lock"
    cpa = tmp_path / "cpa.lock"
    processed.write_bytes(b"processed")
    feature_bank.write_bytes(b"features")
    dependency.write_text("{}", encoding="utf-8")
    gears.write_text("cell-gears==0.1.2\n", encoding="utf-8")
    cpa.write_text("cpa-tools==0.7.2\n", encoding="utf-8")
    inputs = build_activation_provenance_inputs(
        processed=_declared(processed),
        feature_bank=_declared(feature_bank),
        dependency_lock=_declared(dependency),
        gears_requirements=_declared(gears),
        cpa_requirements=_declared(cpa),
        environment=_environment(),
        device="cuda:0",
        precision="float32",
    )
    assert inputs.processed_sha256 == hashlib.sha256(b"processed").hexdigest()
    assert inputs.feature_bank_sha256 == hashlib.sha256(b"features").hexdigest()
    assert inputs.gears_revision == "0.1.2"
    assert inputs.cpa_revision == "0.7.2"
    assert len(inputs.dependency_lock_sha256) == 64
    assert inputs.git_commit == _environment().git_commit


def _provenance_fixture(tmp_path):
    """Small files for the activation-provenance inputs, gears pinned at 0.1.2."""
    processed = tmp_path / "processed.h5ad"
    feature_bank = tmp_path / "features.json"
    dependency = tmp_path / "dependency.json"
    gears = tmp_path / "gears.lock"
    cpa = tmp_path / "cpa.lock"
    processed.write_bytes(b"processed")
    feature_bank.write_bytes(b"features")
    dependency.write_text("{}", encoding="utf-8")
    gears.write_text("cell-gears==0.1.2\n", encoding="utf-8")
    cpa.write_text("cpa-tools==0.7.2\n", encoding="utf-8")
    return processed, feature_bank, dependency, gears, cpa


_PROVENANCE_FIELDS = (
    "processed",
    "feature_bank",
    "dependency_lock",
    "gears_requirements",
    "cpa_requirements",
)


@pytest.mark.parametrize("field", _PROVENANCE_FIELDS)
def test_a_provenance_input_whose_bytes_are_not_the_declared_digest_is_refused(tmp_path, field):
    """The boundary carries the digest the run spec verified, and the read checks it.

    `60a8c5f` closed the double read INSIDE this function. The window that
    remained was at its boundary: the caller unwrapped five declared `PathSha`
    objects to bare paths and this function hashed whatever was on disk NOW. A
    file replaced between run-spec verification and provenance assembly was
    recorded with the replacement's digest, and nothing refused it -- the
    feature-bank residual and the worker-requirements lane the daily review
    reported on separate days are the same window in two of the five lanes.
    Now each input is `(path, declared_sha256)` and bytes that do not hash to the
    declaration are refused, naming the lane.
    """
    files = dict(zip(_PROVENANCE_FIELDS, _provenance_fixture(tmp_path), strict=True))
    declared = {name: _declared(path) for name, path in files.items()}
    # A replacement that still parses, so the ONLY reason to refuse is the digest.
    swapped = {
        "gears_requirements": b"cell-gears==0.1.2\n# replaced after verification\n",
        "cpa_requirements": b"cpa-tools==0.7.2\n# replaced after verification\n",
    }.get(field, b"replaced after the run spec verified it")
    files[field].write_bytes(swapped)

    with pytest.raises(Phase2bError, match=field):
        build_activation_provenance_inputs(
            **declared, environment=_environment(), device="cuda:0", precision="float32"
        )


def _install_swapping_open(monkeypatch, target: str, fire_on: int, state: dict, new_text: str):
    """Count opens of *target* and rewrite it just before its *fire_on*-th open.

    Installed on **both** ``builtins.open`` and ``io.open``. That is not belt and
    braces -- it is required, and measuring it is how this probe was fixed:
    ``sha256_file`` calls the bare ``open`` (``builtins.open``) while
    ``Path.read_text`` calls ``io.open``, and the two names are separate
    references. Patching only ``builtins.open`` counted ONE of the two reads, so
    the first version of the test below passed against the unfixed code. The
    control arm ``test_the_swap_probe_is_not_vacuous`` is what caught that.
    """
    import builtins
    import io
    import os

    real_open = builtins.open

    def wrapper(file, *args, **kwargs):
        try:
            key = os.fspath(file)
        except TypeError:
            key = None
        if key == target:
            state["opens"] = state.get("opens", 0) + 1
            if state["opens"] == fire_on:
                state["fired"] = True
                with real_open(key, "w", encoding="utf-8") as fh:
                    fh.write(new_text)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", wrapper)
    monkeypatch.setattr(io, "open", wrapper)


def test_the_requirements_file_is_read_once_so_a_swap_has_no_window(tmp_path, monkeypatch):
    """The recorded revision and the recorded digest must come from ONE read.

    The previous shape hashed ``gears_requirements_path`` with ``sha256_file`` and
    then reopened the SAME pathname to parse the pinned revision. A writer landing
    between the two reads makes ``dependency_lock_sha256`` and ``gears_revision``
    describe different bytes, and nothing refuses it -- reproduced by the external
    audit and by the 2026-09-03 review with a control arm. Two of the six
    registered activation blockers are exactly these revisions, so the window
    corrupts the evidence a dev-pod run is meant to produce.
    """
    processed, feature_bank, dependency, gears, cpa = _provenance_fixture(tmp_path)
    # The declarations are the run spec's reads, made BEFORE the probe is armed;
    # the probe counts only the builder's own opens of the file.
    declared = {
        "processed": _declared(processed),
        "feature_bank": _declared(feature_bank),
        "dependency_lock": _declared(dependency),
        "gears_requirements": _declared(gears),
        "cpa_requirements": _declared(cpa),
    }
    state: dict = {}
    _install_swapping_open(monkeypatch, str(gears), 2, state, "cell-gears==9.9.9\n")
    inputs = build_activation_provenance_inputs(
        **declared, environment=_environment(), device="cuda:0", precision="float32"
    )
    monkeypatch.undo()

    assert state.get("opens") == 1, (
        "the requirements file was opened more than once -- the gap between those "
        f"reads is the TOCTOU window (opens={state.get('opens')})"
    )
    assert not state.get("fired"), "the swap fired, so a second read existed"
    assert inputs.gears_revision == "0.1.2"
    assert gears.read_text(encoding="utf-8") == "cell-gears==0.1.2\n"


def test_the_swap_probe_is_not_vacuous(tmp_path, monkeypatch):
    """Control arm: the same injection DOES corrupt a deliberate two-read function.

    Without this, the test above would pass for a function that never reads the
    file at all, and would be measuring nothing.
    """
    _, _, _, gears, _ = _provenance_fixture(tmp_path)
    state: dict = {}
    _install_swapping_open(monkeypatch, str(gears), 2, state, "cell-gears==9.9.9\n")

    def two_reads(path):
        first = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        second = Path(path).read_text(encoding="utf-8").strip()
        return first, second

    digest, line = two_reads(gears)
    monkeypatch.undo()

    assert state.get("opens") == 2
    assert state.get("fired") is True
    assert line == "cell-gears==9.9.9"
    assert digest == hashlib.sha256(b"cell-gears==0.1.2\n").hexdigest()


# ===========================================================================
# D2 Task 6 — pre-access seed-variability binding wired into Phase-2b preflight
# ===========================================================================


def _scientific_response_artifact():
    """A response artifact carrying the combined checksum the scientific path needs."""
    from alive.compose.response import verify_response_artifact

    space, control_mean = _response_space()
    _, _, checksum = verify_response_artifact(space, control_mean)
    return {"response_space": space, "control_mean": control_mean, "checksum": checksum}


def test_fixture_path_binds_seed_variability_before_persist(tmp_path):
    # The bounded fixture path is NOT a silent bypass: it writes the report ONCE
    # and records its byte SHA into the write-once ledger BEFORE the pre-access
    # snapshot, so the persisted snapshot carries the artifact.
    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))

    report_path = kit["run_dir"] / DEVELOPMENT_SEED_VARIABILITY_FILENAME
    assert report_path.is_file()
    recorded = res.ledger.artifact_sha(DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT)
    assert recorded == sha256_file(report_path)
    # recorded BEFORE persist_pre_access_ledger -> present in the durable snapshot.
    snapshot = RunLedger.read(kit["run_dir"] / PRE_ACCESS_LEDGER_FILENAME)
    assert snapshot.artifact_sha(DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT) == recorded
    # the run still completes normally (one sealed access, COMPLETE terminal).
    assert res.sealed_access_count == 1
    assert res.terminal_state == TerminalState.COMPLETE


def test_preaccess_fixture_binds_bounded_report(tmp_path):
    kit = _make_run(tmp_path)
    _preaccess_seed_variability(
        run_dir=kit["run_dir"],
        ledger=kit["ledger"],
        frozen_bundle=kit["bundle"],
        config=kit["cfg"],
        fixture_execution=True,
        seed_variability=None,
    )
    assert (kit["run_dir"] / DEVELOPMENT_SEED_VARIABILITY_FILENAME).is_file()
    assert kit["ledger"].artifact_sha(DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT)


def test_preaccess_scientific_requires_seed_variability_inputs(tmp_path):
    # The scientific branch cannot be silently bypassed: with no seed-variability
    # inputs it FAILS CLOSED (before any seal access).
    kit = _make_run(tmp_path)
    with pytest.raises(Phase2bError, match="seed-variability"):
        _preaccess_seed_variability(
            run_dir=kit["run_dir"],
            ledger=kit["ledger"],
            frozen_bundle=kit["bundle"],
            config=kit["cfg"],
            fixture_execution=False,
            seed_variability=None,
        )


def test_scientific_core_missing_seed_report_leaves_seal_closed(tmp_path):
    # Drive _run_phase2b_core on the SCIENTIFIC path with no seed-variability
    # inputs: the pre-access seed-variability gate raises BEFORE any seal access,
    # so the seal stays CLOSED and NO terminal artifact is written.
    kit = _make_run(tmp_path, fixture_store=True)
    with pytest.raises(Phase2bError, match="seed-variability"):
        _run_phase2b_core(
            run_dir=kit["run_dir"],
            outcome_store=kit["store"],
            frozen_bundle=kit["bundle"],
            pair_manifest=kit["manifest"],
            response_artifact=_scientific_response_artifact(),
            config=kit["cfg"],
            ledger=kit["ledger"],
            fixture_execution=False,
            git_clean=True,
            provenance_tamper=None,
            provenance_inputs=None,
            seed_variability=None,
        )
    assert kit["store"].sealed_access_count == 0
    assert _terminal_artifacts(kit["run_dir"]) == []


def test_run_phase2b_partial_seed_inputs_rejected(tmp_path):
    # The scientific entry refuses a partial seed-variability input set (all four
    # of oof_manifest_path/checksum + report_path/checksum, or none).
    kit = _make_run(tmp_path, fixture_store=False)
    with pytest.raises(Phase2bError, match="together"):
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
            oof_manifest_path=tmp_path / "oof.json",  # only one of four supplied
        )
    assert kit["store"].sealed_access_count == 0


# ===========================================================================
# D1 Task 7: durable finalize wired into run_phase2b (normal / abort)
# ===========================================================================


def test_complete_run_publishes_verified_durable_commit_marker(tmp_path):
    # NORMAL path: after the terminal is written and the protection context has
    # exited, the durable finalizer publishes a commit marker and the frozen
    # Phase2bResult carries its checksum + path.
    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))
    run_dir = kit["run_dir"]

    assert res.terminal_state == TerminalState.COMPLETE
    # exactly one terminal (COMPLETE) — the marker is NOT a terminal artifact.
    assert _terminal_artifacts(run_dir) == [run_dir / Phase2bTerminal.COMPLETE_ARTIFACT]

    marker_path = run_dir / DURABLE_COMMIT_FILENAME
    assert marker_path.is_file()
    assert res.durable_commit_checksum is not None
    assert res.durable_commit_path == str(marker_path)

    # the marker's self-excluding checksum recomputes (verified marker).
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    core = {k: v for k, v in marker.items() if k != COMMIT_CHECKSUM_FIELD}
    assert marker[COMMIT_CHECKSUM_FIELD] == res.durable_commit_checksum
    assert sha256_json(core) == res.durable_commit_checksum

    # a marker-present recovery re-verifies every published file (verify-only).
    recovered = recover_phase2b_durable_outputs(run_dir=run_dir)
    assert recovered.commit_checksum == res.durable_commit_checksum


def test_abort_publishes_durable_marker_and_reraises_original(tmp_path):
    # ABORT path: an exception inside the protection boundary → protect writes the
    # ABORTED terminal and re-raises; the SAME finalizer then publishes the reduced
    # abort marker. The ORIGINAL evaluation exception propagates unchanged.
    kit = _make_run(tmp_path)
    burner = _RaisingAfterClaimStore(kit["store"])
    kwargs = _fixture_kwargs(kit)
    kwargs["outcome_store"] = burner
    with pytest.raises(RuntimeError, match="synthetic materialisation failure"):
        run_phase2b_fixture(**kwargs)

    run_dir = kit["run_dir"]
    # the seal was consumed once; exactly one terminal (ABORTED).
    assert kit["store"].sealed_access_count == 1
    assert _terminal_artifacts(run_dir) == [run_dir / Phase2bTerminal.ABORTED_ARTIFACT]

    # the abort marker was published and re-verifies.
    marker_path = run_dir / DURABLE_COMMIT_FILENAME
    assert marker_path.is_file()
    recover_phase2b_durable_outputs(run_dir=run_dir)


def test_abort_finalize_failure_does_not_mask_original_exception(tmp_path, monkeypatch):
    # A finalizer that ITSELF raises on the abort path must NOT replace the original
    # evaluation exception (it is attached as a note) and must leave NO commit
    # marker (a missing marker signals an incomplete durable export).
    kit = _make_run(tmp_path)
    burner = _RaisingAfterClaimStore(kit["store"])
    kwargs = _fixture_kwargs(kit)
    kwargs["outcome_store"] = burner

    def _boom(**_kwargs):
        raise DurableLedgerError("synthetic durable finalize failure")

    monkeypatch.setattr("alive.compose.phase2b.finalize_phase2b_durable_outputs", _boom)

    with pytest.raises(RuntimeError, match="synthetic materialisation failure") as excinfo:
        run_phase2b_fixture(**kwargs)

    # the original evaluation exception is preserved; the finalize failure is a note.
    notes = getattr(excinfo.value, "__notes__", [])
    assert any("finalize" in note for note in notes)

    run_dir = kit["run_dir"]
    # no commit marker (incomplete export) but the abort terminal is untouched.
    assert not (run_dir / DURABLE_COMMIT_FILENAME).exists()
    assert _terminal_artifacts(run_dir) == [run_dir / Phase2bTerminal.ABORTED_ARTIFACT]


def test_pre_audit_failure_does_not_finalize(tmp_path, monkeypatch):
    # A pre-audit failure (here a preflight checksum mismatch) happens BEFORE the
    # seal is claimed: no terminal exists, so the durable finalizer is NEVER called
    # and no marker is published.
    kit = _make_run(tmp_path)
    bad_ledger = RunLedger(
        run_id=kit["bundle"].run_id,
        config_sha256=kit["cfg"].config_sha256,
        environment=_environment(),
    )
    bad_ledger.record_artifact("data_card", _DATA_CARD)
    bad_ledger.record_artifact("raw_data", _RAW)
    bad_ledger.record_artifact("sequence_mapping", _SEQ)
    bad_ledger.record_artifact("pair_manifest", kit["manifest"]["checksum"])
    bad_ledger.record_artifact("response_space", kit["bundle"].response_space_checksum)
    bad_ledger.record_artifact("factor_bank", kit["bundle"].factor_checksum)
    bad_ledger.record_artifact("model", kit["bundle"].model_checksum)
    bad_ledger.record_artifact("frozen_prediction_bundle", "WRONG-SHA")

    def _must_not_run(**_kwargs):
        raise AssertionError("finalize must NOT run on a pre-audit failure")

    monkeypatch.setattr("alive.compose.phase2b.finalize_phase2b_durable_outputs", _must_not_run)

    kwargs = _fixture_kwargs(kit)
    kwargs["ledger"] = bad_ledger
    with pytest.raises(PreflightError):
        run_phase2b_fixture(**kwargs)

    assert kit["store"].sealed_access_count == 0
    assert _terminal_artifacts(kit["run_dir"]) == []
    assert not (kit["run_dir"] / DURABLE_COMMIT_FILENAME).exists()


# ---------------------------------------------------------------------------
# Task 7: verdict-invariant durable carry of the approximation-bias fairness flag
# (design spec §5/§7). The block is BUILT inside build_registered_evaluation_summary
# from the pinned report (SHA-verified, fail-closed) and lives in the registered
# summary dict ONLY — never in ComposeSealedResult, so the verdict is byte-unchanged.
# ---------------------------------------------------------------------------


def _builder_base_kwargs(tmp_path):
    """Real regime / verdict objects from a fixture run + the base build kwargs.

    Uses genuine ``RegimeScore`` / ``ComposeSealedResult`` objects (not synthetic
    stand-ins) so the verdict-invariance proof binds a REAL verdict checksum.
    """
    from alive.compose.verdict2 import ComposeIntegrityReport

    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))
    integrity = ComposeIntegrityReport(
        provenance_ok=True,
        leakage_ok=True,
        all_metrics_finite=True,
        sealed_access_consistent=True,
        sealed_n=res.regime_double.sample_count,
        minimum_sealed=1,
    )
    per_method_aggregate_mse = {
        regime_name: {
            method: float(np.mean(regime.descriptive_pair_errors[method]))
            for method in sorted(regime.descriptive_pair_errors)
        }
        for regime_name, regime in (("double", res.regime_double), ("single", res.regime_single))
    }
    return {
        "protocol": "COMPOSE-K562-v1",
        "run_id": "run-task7",
        "terminal_state": "COMPLETE",
        "sealed_access_count": 1,
        "regime_double": res.regime_double,
        "regime_single": res.regime_single,
        "per_method_aggregate_mse": per_method_aggregate_mse,
        "final_verdict": res.sealed_verdict,
        "integrity": integrity,
        "family_confidence": 0.95,
        "bootstrap_replicates": 3,
        "bundle_checksum": "a" * 64,
        "manifest_checksum": "b" * 64,
        "provenance_checksum": "c" * 64,
        "seed_variability_report_checksum": "0" * 64,
    }


def _write_bias_report(
    path,
    *,
    fairness_flag="representation_confounded",
    bias_to_signal_ratio_R=0.6,
    bootstrap_95_interval=(0.4, 0.9),
    R_star=0.5,
):
    """Write a REAL-shaped ``compose_approximation_bias_report_v3`` report and return
    its ``sha256_file`` content SHA.

    Faithful to the true on-disk contract that ``measure_approximation_bias_v3`` /
    ``measure_pseudobulk_approximation_bias.py::main`` produce — NOT a flat,
    newline-free stub: the fairness fields are NESTED under ``gi_and_fairness``, the
    ``bootstrap_95_interval`` is a DICT of three sub-intervals (the loader carries only
    the ``bias_to_signal_ratio_R`` one), and the file is the canonical JSON WITH a
    trailing newline. So the durable loader is exercised against the real schema +
    hashing recipe, not a stub that would hide the integration bug.
    """
    combo_floor = 0.9 * bias_to_signal_ratio_R
    combo_stratum = {
        "n_pairs": 1,
        "per_pair": [{"pair_id": "A_B", "b_i": combo_floor}],
        "b_distribution": {
            "median": combo_floor,
            "mean": combo_floor,
            "max": combo_floor,
            "q90": combo_floor,
        },
        "signed_pc_bias": [0.0, 0.0],
    }
    empty_stratum = {
        "n_pairs": 0,
        "per_pair": [],
        "b_distribution": {
            "median": "NON_FINITE",
            "mean": "NON_FINITE",
            "max": "NON_FINITE",
            "q90": "NON_FINITE",
        },
        "signed_pc_bias": [],
    }
    body = {
        "schema": APPROXIMATION_BIAS_SCHEMA,
        "deliverable": "gears_pseudobulk_approximation_bias_report",
        "protocol": PROTOCOL,
        "seal_status": "unopened",
        "method": REPRESENTATION,
        "admission_status": "admitted",
        "strata": {"combo_calibration": combo_stratum, "singles": empty_stratum},
        "gi_and_fairness": {
            "gi_signal_per_pair": [{"pair_id": "A_B", "g_i": 0.9}],
            "fairness_flag": fairness_flag,
            "bias_to_signal_ratio_R": bias_to_signal_ratio_R,
            "R_star": R_star,
            "bootstrap_95_interval": {
                "floor_median": [0.0, 0.05],
                "gi_signal_median": [0.8, 1.0],
                "bias_to_signal_ratio_R": list(bootstrap_95_interval),
            },
            # sibling fields a real report carries and the loader ignores.
            "gi_signal_median": 0.9,
            "floor_median": combo_floor,
            "bias_to_signal_ratio_per_pair_median": bias_to_signal_ratio_R,
            "replicates_requested": 10,
            "replicates_finite": 10,
            "replicates_non_finite": 0,
        },
        "provenance": {
            "measurement_contract_sha256": measurement_contract_sha256(),
            "basis_config_sha256": "a" * 64,
            "git_commit": "b" * 40,
            "norman_source_sha256": "1" * 64,
            "fit_role_artifact_sha256": "2" * 64,
            "response_projection_sha256": "3" * 64,
            "gene_order_sha256": "4" * 64,
            "pca_dim": 2,
            "registered_seeds": [11, 23, 37],
            "probe_a_evidence_sha256": "5" * 64,
            "probe_a_evidence_manifest_sha256": "6" * 64,
            "probe_a_registration_sha256": "7" * 64,
            "probe_a_verification_sha256": "8" * 64,
            "sealed_pair_overlap_count": 0,
            "pod_instance": "unit-test",
        },
    }
    report = {**body, "self_checksum": self_checksum(body)}
    # EXACTLY as main writes it: canonical JSON + a trailing newline.
    text = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    Path(path).write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_fairness_block_sourced_from_pinned_report(tmp_path):
    # config SHA == report content SHA ⇒ the block carries the report's flag / ratio /
    # interval / R_star verbatim (ratio + interval routed through the finite sentinel).
    base = _builder_base_kwargs(tmp_path)
    report_path = tmp_path / "bias_report.json"
    sha = _write_bias_report(
        report_path,
        fairness_flag="representation_confounded",
        bias_to_signal_ratio_R=0.6,
        bootstrap_95_interval=(0.4, 0.9),
        R_star=0.5,
    )
    evidence = load_approximation_bias_report(
        report_path,
        expected_content_sha256=sha,
        expected_measurement_contract_sha256=measurement_contract_sha256(),
    )
    fairness = _load_approximation_bias_fairness(report_sha256=sha, report_evidence=evidence)
    summary = build_registered_evaluation_summary(
        **base,
        approximation_bias_report_sha256=sha,
        approximation_bias_fairness=fairness,
    )
    block = summary["approximation_bias_fairness"]
    assert block["report_sha256"] == sha
    assert block["fairness_flag"] == "representation_confounded"
    assert block["bias_to_signal_ratio_R"] == 0.6
    assert block["bootstrap_95_interval"] == [0.4, 0.9]
    assert block["R_star"] == 0.5


def test_fairness_block_fails_closed_on_sha_mismatch(tmp_path):
    # report content SHA != config SHA ⇒ the loader RAISES; no report value leaks in.
    report_path = tmp_path / "bias_report.json"
    real_sha = _write_bias_report(report_path, fairness_flag="clear", bias_to_signal_ratio_R=0.4)
    wrong_sha = "9" * 64
    assert wrong_sha != real_sha  # the config SHA genuinely differs from the report SHA
    with pytest.raises(ApproximationBiasReportError, match="SHA"):
        _load_approximation_bias_fairness(
            report_sha256=wrong_sha,
            report_evidence=ApproximationBiasEvidence(
                content_sha256=real_sha, report_bytes=report_path.read_bytes()
            ),
        )


def test_final_verdict_checksum_byte_unchanged(tmp_path):
    # The block lives in the summary dict ONLY: building WITH vs WITHOUT the wiring
    # leaves the real verdict checksum AND every non-block field byte-identical.
    base = _builder_base_kwargs(tmp_path)
    baseline_verdict_checksum = base["final_verdict"].checksum  # a REAL verdict checksum
    report_path = tmp_path / "bias_report.json"
    sha = _write_bias_report(report_path)
    evidence = load_approximation_bias_report(report_path, expected_content_sha256=sha)
    fairness = _load_approximation_bias_fairness(report_sha256=sha, report_evidence=evidence)

    with_block = build_registered_evaluation_summary(
        **base,
        approximation_bias_report_sha256=sha,
        approximation_bias_fairness=fairness,
    )
    without_block = build_registered_evaluation_summary(**base)  # defaults ⇒ unavailable

    # the passed verdict's own checksum is untouched by the block.
    assert base["final_verdict"].checksum == baseline_verdict_checksum
    # every verdict axis / clause in the summary is byte-identical either way.
    for key in ("sealed_axis", "method_axis", "verdict_clauses"):
        assert sha256_json(with_block[key]) == sha256_json(without_block[key])
    # only the fairness block differs; everything else is byte-identical.
    assert with_block["approximation_bias_fairness"] != without_block["approximation_bias_fairness"]
    stripped_with = {k: v for k, v in with_block.items() if k != "approximation_bias_fairness"}
    stripped_without = {
        k: v for k, v in without_block.items() if k != "approximation_bias_fairness"
    }
    assert sha256_json(stripped_with) == sha256_json(stripped_without)


def test_null_config_field_yields_unavailable_block(tmp_path):
    # null config field (not yet finalized) ⇒ the carry EXISTS but is honestly empty.
    base = _builder_base_kwargs(tmp_path)
    summary = build_registered_evaluation_summary(
        **base,
        approximation_bias_report_sha256=None,
    )
    block = summary["approximation_bias_fairness"]
    assert block["report_sha256"] is None
    assert block["fairness_flag"] == "unavailable"
    assert block["bias_to_signal_ratio_R"] is None
    assert block["bootstrap_95_interval"] is None
    assert block["R_star"] is None


# ---------------------------------------------------------------------------
# END-TO-END: metric ↔ finalize ↔ phase2b agree on BOTH schema nesting AND the
# on-disk-bytes hashing recipe. This is the integration seam the per-task stubs
# papered over: it builds a REAL compose_approximation_bias_report_v3 via the
# metric, writes it EXACTLY as production does (canonical JSON + trailing '\n'),
# finalizes the config leaf SHA via the real finalize tool (which now pins
# sha256_file of those bytes), and feeds that SHA + report path into the phase2b
# immutable evidence loader — which must populate the fairness block (NOT "unavailable",
# NOT a raise). Would have caught both Important integration bugs.
# ---------------------------------------------------------------------------


def _load_script_module(rel_path: str, mod_name: str):
    """Import a ``scripts/`` module by file path (mirrors the metric/finalize tests)."""
    import importlib.util

    repo_root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(mod_name, repo_root / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _probe_a_evidence_snapshot() -> ProbeAEvidence:
    """Return a valid immutable Probe-A snapshot for direct producer tests."""
    registration_body = {
        "schema": PROBE_A_REGISTRATION_SCHEMA,
        "protocol": PROTOCOL,
        "git_commit": "b" * 40,
        "owner_policy_sha256": probe_a_owner_policy_sha256(),
        "input_scale": {
            "normalization_target": 10000.0,
            "transform": "full_library_normalize_log1p_then_roster_subset",
        },
        "determinism": {"max_abs_error_tolerance": 0.0},
        "control_count": {
            "counts": [1, 8, 300, 301, 400],
            "first_300_max_abs_error_tolerance": 1e-5,
        },
        "output_bridge": {
            "representation": PROBE_A_REPRESENTATION,
            "transform": PROBE_A_ADAPTER_TRANSFORM,
            "negative_output_policy": PROBE_A_NEGATIVE_OUTPUT_POLICY,
            "max_abs_error_tolerance": 1e-5,
        },
    }
    registration = {
        **registration_body,
        "self_checksum": self_checksum(registration_body),
    }
    registration_bytes = (canonical_json(registration) + "\n").encode("utf-8")
    registration_sha = sha256_bytes(registration_bytes)
    bridge = {
        "representation": PROBE_A_REPRESENTATION,
        "verdict": "pass",
        "tolerance": 1e-5,
        "max_abs_error": 0.0,
    }
    verification_body = {
        "schema": PROBE_A_VERIFICATION_SCHEMA,
        "protocol": PROTOCOL,
        "status": "pass",
        "git_commit": "b" * 40,
        "registration_sha256": registration_sha,
        "payload_sha256": "6" * 64,
        "roster_receipt_sha256": "7" * 64,
        "verifier_image_digest": "sha256:" + "8" * 64,
        "verifier_image_lock_sha256": "9" * 64,
        "report_sha256": "a" * 64,
        "evidence_manifest_sha256": "d" * 64,
        "verifier_code_sha256": "e" * 64,
        "output_bridge": bridge,
    }
    verification = {
        **verification_body,
        "self_checksum": self_checksum(verification_body),
    }
    verification_bytes = (canonical_json(verification) + "\n").encode("utf-8")
    verification_sha = sha256_bytes(verification_bytes)
    body = {
        "schema": PROBE_A_SCHEMA,
        "protocol": PROTOCOL,
        "status": "pass",
        "git_commit": "b" * 40,
        "registration_sha256": registration_sha,
        "evidence_manifest_sha256": "d" * 64,
        "verification_sha256": verification_sha,
        "output_bridge": bridge,
    }
    payload = {**body, "self_checksum": self_checksum(body)}
    encoded = (canonical_json(payload) + "\n").encode("utf-8")
    return ProbeAEvidence(
        content_sha256=sha256_bytes(encoded),
        evidence_bytes=encoded,
        registration_sha256=registration_sha,
        registration_bytes=registration_bytes,
        verification_sha256=verification_sha,
        verification_bytes=verification_bytes,
    )


def _build_real_bias_report(tmp_path):
    """Build a REAL v2 report via ``measure_approximation_bias_v3`` on a small
    synthetic control-free fit-role artifact + identity projection block, bound to a
    bias-NULL basis config. Writes the report EXACTLY as the metric CLI does
    (canonical JSON + trailing newline). Returns ``(report, basis_yaml, report_path)``.

    The synthetic roster mirrors the metric test's ``_full_report_fixture`` (three
    combo pairs / six singles, identity block) — already known to yield real, finite,
    non-degenerate ``bias_to_signal_ratio_R`` and a real bootstrap interval.
    """
    import anndata as ad
    import pandas as pd
    import yaml

    from alive.compose.fit_role import canonical_gene_order_sha256

    metric = _load_script_module(
        "scripts/compose/measure_pseudobulk_approximation_bias.py", "_pb_bias_metric_e2e"
    )

    # bias-NULL basis config; its sha256_json is what the report's provenance binds.
    basis = {
        "protocol": "COMPOSE-K562-v1",
        "seeds": {"registered_seeds": [11, 23, 37], "split_seed": 11},
        "baselines": {"gears": {"approximation_bias_report_sha256": None}},
    }
    basis_yaml = tmp_path / "basis_config.yaml"
    basis_yaml.write_text(yaml.safe_dump(basis, sort_keys=False), encoding="utf-8")
    basis_sha = sha256_json(yaml.safe_load(basis_yaml.read_text(encoding="utf-8")))

    genes = [f"F{i}" for i in range(1, 7)]
    base_row = [5.0] * 6

    def _spread(dims, s):
        a = list(base_row)
        a[dims[0]] += s
        a[dims[1]] -= s
        b = list(base_row)
        b[dims[0]] -= s
        b[dims[1]] += s
        return a, b

    p1a, p1b = _spread((0, 1), 4.0)
    p2a, p2b = _spread((2, 3), 2.0)
    p3a, p3b = _spread((4, 5), 1.0)
    roles = ["singles"] * 6 + ["combo_calibration"] * 6
    singles = ["P1", "P2", "P3", "P4", "P5", "P6"]
    combos = ["P1_P2", "P1_P2", "P3_P4", "P3_P4", "P5_P6", "P5_P6"]
    perts = singles + combos
    rows = [
        [7.0, 3.0, 5.0, 5.0, 5.0, 5.0],
        [3.0, 7.0, 5.0, 5.0, 5.0, 5.0],
        [5.0, 5.0, 9.0, 1.0, 5.0, 5.0],
        [5.0, 5.0, 1.0, 9.0, 5.0, 5.0],
        [5.0, 5.0, 5.0, 5.0, 7.0, 3.0],
        [5.0, 5.0, 5.0, 5.0, 3.0, 7.0],
        p1a,
        p1b,
        p2a,
        p2b,
        p3a,
        p3b,
    ]
    obs = pd.DataFrame(
        {"role": roles, "perturbation": perts}, index=[f"cell{i}" for i in range(12)]
    )
    adata = ad.AnnData(X=np.asarray(rows, dtype=np.float64), obs=obs, var=pd.DataFrame(index=genes))
    artifact = tmp_path / "e2e_fit_role.h5ad"
    adata.write_h5ad(artifact)
    block = {
        "median_library": 30.0,
        "hvg_gene_ids": genes,
        "pca_mean": [0.0] * 6,
        "pca_components": np.eye(6).tolist(),
        "gene_order_sha256": canonical_gene_order_sha256(genes),
        "control_mean": [0.0] * 6,
    }
    probe_a_evidence = _probe_a_evidence_snapshot()
    report = metric.measure_approximation_bias_v3(
        fit_role_artifact=str(artifact),
        response_projection=block,
        sealed_pair_ids=["ZZZ_YYY"],
        basis_config_sha256=basis_sha,
        registered_seeds=[11, 23, 37],
        replicates=40,
        git_commit="b" * 40,
        norman_source_sha256="c" * 64,
        pod_instance="unit-test-local",
        probe_a_evidence=probe_a_evidence,
        probe_a_registration_sha256=probe_a_evidence.registration_sha256,
        probe_a_verification_sha256=probe_a_evidence.verification_sha256,
    )
    report_path = tmp_path / "approximation_bias_report.json"
    # EXACTLY as measure_pseudobulk_approximation_bias.py::main writes it.
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    report_path.write_text(canonical + "\n", encoding="utf-8")
    return report, basis_yaml, report_path


def test_metric_finalize_phase2b_roundtrip(tmp_path):
    # Build the REAL report + finalize the config leaf via the real tool.
    report, basis_yaml, report_path = _build_real_bias_report(tmp_path)
    gi = report["gi_and_fairness"]
    # Sanity: this fixture yields a genuinely populated (non-degenerate) report.
    assert gi["fairness_flag"] in {"clear", "representation_confounded"}
    assert isinstance(gi["bias_to_signal_ratio_R"], float)
    assert isinstance(gi["bootstrap_95_interval"]["bias_to_signal_ratio_R"], list)

    finalize = _load_script_module(
        "scripts/compose/finalize_approximation_bias_config.py", "_finalize_bias_config_e2e"
    )
    final_config = finalize.finalize_bias_config(
        basis_config_path=basis_yaml, report_path=report_path
    )
    pinned_sha = final_config["baselines"]["gears"]["approximation_bias_report_sha256"]
    # The finalized leaf must be the SHA of the EXACT on-disk report bytes — the one
    # recipe phase2b re-verifies. (Off-by-a-newline here is Important-2.)
    assert pinned_sha == sha256_file(report_path)

    # Feed the finalized SHA + immutable report evidence into the phase2b loader.
    base = _builder_base_kwargs(tmp_path)
    evidence = load_approximation_bias_report(
        report_path,
        expected_content_sha256=pinned_sha,
        expected_basis_config_sha256=report["provenance"]["basis_config_sha256"],
        expected_measurement_contract_sha256=measurement_contract_sha256(),
        expected_git_commit="b" * 40,
    )
    fairness = _load_approximation_bias_fairness(
        report_sha256=pinned_sha,
        report_evidence=evidence,
        expected_git_commit="b" * 40,
    )
    summary = build_registered_evaluation_summary(
        **base,
        approximation_bias_report_sha256=pinned_sha,
        approximation_bias_fairness=fairness,
    )
    block = summary["approximation_bias_fairness"]
    # The block populates from the REAL nested report — NOT "unavailable", NOT a raise.
    assert block["report_sha256"] == pinned_sha
    assert block["fairness_flag"] == gi["fairness_flag"]
    assert block["fairness_flag"] != "unavailable"
    assert block["bias_to_signal_ratio_R"] == gi["bias_to_signal_ratio_R"]
    assert block["bootstrap_95_interval"] == gi["bootstrap_95_interval"]["bias_to_signal_ratio_R"]
    assert block["R_star"] == gi["R_star"]


# Fail-closed unit coverage for the seal-critical loader's numeric/interval helpers +
# loader-level branches (final-review Minor: these leak-barrier branches were only
# reached by the round-trip happy path). The KEY assertion is that every malformed
# value raises the TYPED ApproximationBiasReportError — never a bare ValueError/TypeError
# (which is exactly what float("NON_FINITE") would raise and the caller could not classify).
def test_bias_numeric_or_sentinel_fail_closed(tmp_path):
    from alive.compose.phase2b import _bias_numeric_or_sentinel

    p = tmp_path / "r.json"
    assert _bias_numeric_or_sentinel("NON_FINITE", path=p, field="R") == "NON_FINITE"
    assert _bias_numeric_or_sentinel(1.5, path=p, field="R") == 1.5
    assert _bias_numeric_or_sentinel(2, path=p, field="R") == 2.0
    for bad in (True, False, "garbage", None, [1.0], {"x": 1}):
        with pytest.raises(ApproximationBiasReportError, match="approximation-bias report"):
            _bias_numeric_or_sentinel(bad, path=p, field="R")


def test_bias_interval_or_sentinel_fail_closed(tmp_path):
    from alive.compose.phase2b import _bias_interval_or_sentinel

    p = tmp_path / "r.json"
    assert _bias_interval_or_sentinel("NON_FINITE", path=p, field="ci") == "NON_FINITE"
    assert _bias_interval_or_sentinel([0.1, 0.9], path=p, field="ci") == [0.1, 0.9]
    assert _bias_interval_or_sentinel([0.1, "NON_FINITE"], path=p, field="ci") == [
        0.1,
        "NON_FINITE",
    ]
    for bad in ("garbage", [1.0], [1, 2, 3], 0.5, None, [0.1, True]):
        with pytest.raises(ApproximationBiasReportError, match="approximation-bias report"):
            _bias_interval_or_sentinel(bad, path=p, field="ci")


def test_loader_fail_closed_branches(tmp_path):
    # A pinned SHA but no immutable report evidence.
    with pytest.raises(ApproximationBiasReportError, match="no immutable report"):
        _load_approximation_bias_fairness(report_sha256="a" * 64, report_evidence=None)
    # A report whose content SHA matches the pin but lacks the nested gi_and_fairness block.
    nogi_bytes = b'{"schema":"compose_approximation_bias_report_v3"}\n'
    nogi_sha = sha256_bytes(nogi_bytes)
    with pytest.raises(ApproximationBiasReportError):
        _load_approximation_bias_fairness(
            report_sha256=nogi_sha,
            report_evidence=ApproximationBiasEvidence(
                content_sha256=nogi_sha, report_bytes=nogi_bytes
            ),
        )
