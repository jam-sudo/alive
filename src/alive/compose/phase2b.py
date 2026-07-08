"""COMPOSE-K562-v1 Phase-2b sealed-evaluation ORCHESTRATOR (Task 2b-8, plan §2.6).

This is the CAPSTONE of COMPOSE-K562-v1 Phase 2b: it wires the seven built
modules — :mod:`~alive.compose.outcome_store`, :mod:`~alive.compose.preflight`,
:mod:`~alive.compose.inference2`, :mod:`~alive.compose.scoring2`,
:mod:`~alive.compose.verdict2`, :mod:`~alive.compose.provenance2` and
:mod:`~alive.compose.terminal` — into the one-time sealed evaluation that opens
the COMPOSE seal EXACTLY ONCE and produces the confirmatory verdict (CLAUDE.md
§6 multiple-seal rule, §11 write-once provenance).

The load-bearing safety properties
----------------------------------
* The orchestrator takes ONLY a :class:`~alive.compose.outcome_store.
  ComposeOutcomeStore`. Its public signature has NO truth / outcome / array /
  dict-of-outcomes / path-to-outcomes parameter. It NEVER seals data, NEVER
  accepts truth, NEVER fits models and NEVER mutates the frozen bundle.
* :meth:`~alive.compose.outcome_store.ComposeOutcomeStore.evaluate_sealed_once`
  is called EXACTLY ONCE, inside the terminal protection boundary, for the
  UNION of both sealed roles' pair IDs.
* Only the DOUBLE-UNSEEN regime drives the sealed verdict; the single-unseen
  regime is descriptive secondary. The two regimes are scored SEPARATELY and
  NEVER pooled.
* Every consumed access leaves a write-once terminal artifact (COMPLETE /
  INVALID / ABORTED_AFTER_SEAL). A preflight / pre-access failure keeps
  ``sealed_access_count == 0`` and the seal CLOSED (raise, leave no terminal
  artifact — the seal was never opened).

Two-entry activation pattern (mirrors :mod:`alive.compose.phase2a`)
-------------------------------------------------------------------
* :func:`run_phase2b` — the SCIENTIFIC entry. It enforces activation (config
  ``active`` + a valid :class:`~alive.compose.config2.ActivationRecord` + clean
  git, via the same :func:`~alive.compose.config2.assert_scientific_mode_allowed`
  guard Phase-2a uses); the current BLOCKED candidate config makes this fail. It
  rejects any ``fixture_mode``-style bypass and refuses a synthetic-fixture
  store as scientific evidence.
* :func:`run_phase2b_fixture` — the BOUNDED SYNTHETIC entry the integration
  tests use (no activation required; the synthetic store carries a fixture
  marker; the payload is bounded like Phase-2a's fixture guard).

Both delegate to a shared :func:`_run_phase2b_core`. NEITHER entry accepts raw
truth.

SYNTHETIC-ONLY: this is code + synthetic/tiny-fixture integration tests
only. Real execution remains blocked until the owner activation commit and every
§10.1 activation requirement is complete.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from alive.compose.config2 import (
    ActivationRecord,
    ComposePhase2Config,
    ScientificModeError,
    assert_scientific_mode_allowed,
)
from alive.compose.durable import finalize_phase2b_durable_outputs
from alive.compose.freeze import FrozenPredictionBundle
from alive.compose.outcome_store import (
    _FIXTURE_CORPUS_ALLOWLIST,
    ComposeOutcomeStore,
    FixtureOutcomeStore,
    ObservedPair,
    SealedAccessClaim,
)
from alive.compose.preflight import EvaluationLock, run_preflight
from alive.compose.provenance2 import (
    PRE_ACCESS_LEDGER_FILENAME,
    PRE_ACCESS_PROVENANCE_ARTIFACT,
    Phase2bProvenance,
    PostAccessStatus,
    check_post_access_consistency,
    persist_pre_access_ledger,
    recompute_run_id,
    record_pre_access_provenance,
    verify_upstream_before_access,
)
from alive.compose.response import ResponseSpace, verify_response_artifact
from alive.compose.scoring2 import RegimeScore, score_regime
from alive.compose.seed_variability import (
    DEVELOPMENT_SEED_VARIABILITY_FILENAME,
    DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT,
    SeedVariabilityPreflightError,
    SeedVariabilityReport,
    SeedVariabilityReportError,
    bind_development_seed_variability,
    build_bounded_fixture_seed_variability_report,
    verify_seed_variability_binding_bounded,
    verify_seed_variability_for_preflight,
)
from alive.compose.select import OOFFoldManifest, OOFFoldManifestError
from alive.compose.split import verify_split_manifest
from alive.compose.terminal import Phase2bTerminal, TerminalState
from alive.compose.verdict2 import (
    ComposeIntegrityReport,
    ComposeSealedResult,
    MethodAxis,
    SealedAxis,
    sealed_verdict,
)
from alive.provenance import EnvironmentInfo, RunLedger, sha256_file, sha256_json

#: The two sealed regime role labels (manifest order).
_DOUBLE_ROLE = "sealed_double_unseen"
_SINGLE_ROLE = "sealed_single_unseen"

#: The headline method (config ``baselines.ablation_ladder[0]``); never a
#: comparator. The double-unseen headline bounds drive the sealed verdict.
_HEADLINE = "l1_bilinear_identifiable"

#: Bounded synthetic/tiny-fixture safety limits for the fixture entry point
#: (mirrors :func:`alive.compose.phase2a._assert_fixture_payload`).
_FIXTURE_MAX_SEALED_PAIRS = 4096
_FIXTURE_MAX_RESPONSE_DIM = 256

#: The audit-claim stage label recorded if the protected block aborts.
_PROTECT_STAGE = "sealed_evaluation"

#: Terminal lifecycle state -> the on-disk terminal artifact filename the terminal
#: writer produces for it. Used to hand the durable finalizer the exact terminal
#: path on the normal / INVALID path (the finalizer re-scans and cross-checks it).
_TERMINAL_STATE_ARTIFACT: dict[TerminalState, str] = {
    TerminalState.COMPLETE: Phase2bTerminal.COMPLETE_ARTIFACT,
    TerminalState.INVALID: Phase2bTerminal.INVALID_ARTIFACT,
    TerminalState.ABORTED_AFTER_SEAL: Phase2bTerminal.ABORTED_ARTIFACT,
}


def _durable_inputs_present(run_dir: Path) -> bool:
    """Return ``True`` iff both durable-finalize inputs are regular files in ``run_dir``.

    The durable finalizer (:func:`~alive.compose.durable.finalize_phase2b_durable_outputs`)
    consumes the persisted pre-access ledger snapshot and the D2 development
    seed-variability report. Both are written on every path that reaches the seal
    (``persist_pre_access_ledger`` + ``_preaccess_seed_variability``), so their
    presence gates the finalize: a run that never got that far (a pure pre-access
    failure) does not crash demanding a finalize.
    """
    return (run_dir / PRE_ACCESS_LEDGER_FILENAME).is_file() and (
        run_dir / DEVELOPMENT_SEED_VARIABILITY_FILENAME
    ).is_file()


def _terminal_file_path(run_dir: Path) -> Path | None:
    """Return the single terminal artifact path in ``run_dir``, or ``None``.

    Independently scans the run directory for the three terminal filenames. Returns
    the sole match, or ``None`` if zero or more than one exist. On the abort path
    this gates the finalize on a post-seal terminal actually being present (a
    pre-audit failure leaves none, so no finalize is owed).
    """
    present = [
        run_dir / name
        for name in (
            Phase2bTerminal.COMPLETE_ARTIFACT,
            Phase2bTerminal.INVALID_ARTIFACT,
            Phase2bTerminal.ABORTED_ARTIFACT,
        )
        if (run_dir / name).is_file()
    ]
    return present[0] if len(present) == 1 else None


class Phase2bError(RuntimeError):
    """Raised on an orchestration precondition failure outside the seal boundary.

    Distinct from the module-specific errors (``PreflightError``,
    ``ComposeSealingError``, ``ProvenanceError``, ``TerminalError``,
    ``ComposeScoringError``) so a caller can catch an orchestrator-level
    misconfiguration (e.g. a malformed ``response_artifact`` or a non-fixture
    store handed to the fixture entry) explicitly. Raised only BEFORE any sealed
    access, so it never leaves a consumed seal without a terminal artifact.
    """


@dataclass(frozen=True)
class Phase2bResult:
    """Frozen result of the one-time Phase-2b sealed evaluation.

    Attributes
    ----------
    run_id : str
        The verified composite COMPOSE run identifier.
    sealed_verdict : ComposeSealedResult
        The sealed-axis verdict, decided from the DOUBLE-UNSEEN headline bounds
        ONLY (single-unseen never enters it). On a post-access inconsistency the
        sealed axis is :attr:`~alive.compose.verdict2.SealedAxis.INVALID`.
    regime_double : RegimeScore
        The double-unseen regime score (headline simultaneous bounds + the
        structurally-separate secondary block). The SOLE verdict input.
    regime_single : RegimeScore
        The single-unseen regime score (registered descriptive secondary). Scored
        independently; NEVER pooled with double-unseen.
    terminal_state : TerminalState
        The terminal lifecycle state — ``COMPLETE``, ``INVALID`` or
        ``ABORTED_AFTER_SEAL``.
    sealed_access_count : int
        The number of recorded sealed accesses (``1`` for any consumed run).
    provenance_checksum : str
        The COMPLETE provenance record's self-checksum.
    result_checksum : str
        The layered ``final_result_checksum`` — ``sha256_json`` over exactly
        ``{terminal_state, final_verdict_checksum, registered_summary_checksum,
        evaluation_payload_checksum, provenance_checksum}`` (spec §2.1). An INVALID
        result never reuses the normal verdict payload checksum.
    ledger : RunLedger
        The write-once ledger carrying the terminal artifact's hash.
    durable_commit_checksum : str or None
        The self-excluding ``commit_checksum`` of the durable commit marker
        published by :func:`~alive.compose.durable.finalize_phase2b_durable_outputs`
        AFTER the terminal was written and the protection context exited (spec
        §3.3). ``None`` until finalize succeeds; a ``None`` value on a returned
        result therefore signals no verified durable export. The abort path never
        returns a :class:`Phase2bResult` (its marker, if published, lives only on
        disk), so this field is populated only on the normal / INVALID path.
    durable_commit_path : str or None
        The filesystem path of the published durable commit marker (companion to
        :attr:`durable_commit_checksum`); ``None`` until finalize succeeds.
    """

    run_id: str
    sealed_verdict: ComposeSealedResult
    regime_double: RegimeScore
    regime_single: RegimeScore
    terminal_state: TerminalState
    sealed_access_count: int
    provenance_checksum: str
    result_checksum: str
    ledger: RunLedger
    durable_commit_checksum: str | None = None
    durable_commit_path: str | None = None


# --------------------------------------------------------------------------- #
# response artifact + helpers
# --------------------------------------------------------------------------- #


def _resolve_response_artifact(
    response_artifact: Mapping,
    *,
    require_checksum: bool = False,
) -> tuple[ResponseSpace, np.ndarray, str]:
    """Extract the frozen response space and the explicit control mean.

    The ``_control_mean`` cache on a reloaded :class:`ResponseSpace` does not
    survive reload, so the orchestrator carries the control mean explicitly and
    hands it to :func:`alive.compose.scoring2.score_regime`. This function NEVER
    reads a sealed outcome — the response artifact is the training-role-only PCA
    basis plus the control-population mean.

    Parameters
    ----------
    response_artifact : Mapping
        Must carry ``response_space`` (a :class:`ResponseSpace`) and
        ``control_mean`` (a ``(pca_dim,)`` vector).

    Returns
    -------
    (ResponseSpace, numpy.ndarray)

    Raises
    ------
    Phase2bError
        If a key is absent or the control mean has the wrong shape.
    """
    if not isinstance(response_artifact, Mapping):
        raise Phase2bError("response_artifact must be a mapping with response_space + control_mean")
    space = response_artifact.get("response_space")
    control_mean = response_artifact.get("control_mean")
    if not isinstance(space, ResponseSpace):
        raise Phase2bError("response_artifact['response_space'] must be a ResponseSpace")
    if control_mean is None:
        raise Phase2bError("response_artifact['control_mean'] is required (explicit control mean)")
    try:
        snapshot, ctrl, computed_checksum = verify_response_artifact(space, control_mean)
    except ValueError as exc:
        raise Phase2bError(f"invalid response artifact: {exc}") from exc
    declared_checksum = response_artifact.get("checksum")
    if require_checksum and declared_checksum is None:
        raise Phase2bError(
            "scientific response_artifact requires a combined 'checksum' covering "
            "ResponseSpace + control_mean"
        )
    if declared_checksum is not None and declared_checksum != computed_checksum:
        raise Phase2bError(
            "response_artifact checksum mismatch: declared checksum does not cover the "
            "supplied ResponseSpace + control_mean"
        )
    return snapshot, ctrl, computed_checksum


def _truth_from_release(
    release: Mapping[tuple[str, str], ObservedPair],
    pair_ids: tuple[tuple[str, str], ...],
) -> dict[tuple[str, str], ObservedPair]:
    """Select one regime's observed pairs from the single sealed release.

    The single :meth:`~alive.compose.outcome_store.ComposeOutcomeStore.
    evaluate_sealed_once` call returns the UNION of both roles' observed pairs;
    this slices out one regime's pairs (in manifest order) for independent
    scoring. No pooling: each regime sees only its own pairs.

    Parameters
    ----------
    release : Mapping
        The full union release ``{pair_id -> ObservedPair}``.
    pair_ids : tuple of tuple of str
        The regime's registered pair IDs.

    Returns
    -------
    dict
        ``{pair_id -> ObservedPair}`` for the regime, manifest order preserved.

    Raises
    ------
    Phase2bError
        If a registered pair is absent from the release.
    """
    out: dict[tuple[str, str], ObservedPair] = {}
    for pid in pair_ids:
        canon = tuple(pid)
        if canon not in release:
            raise Phase2bError(
                f"sealed release is missing registered pair {canon!r}; the single access "
                "must release every registered sealed pair"
            )
        out[canon] = release[canon]
    return out


def _score_one_regime(
    *,
    regime: str,
    pair_ids: tuple[tuple[str, str], ...],
    release: Mapping[tuple[str, str], ObservedPair],
    predictions: Mapping[str, Mapping[tuple[str, str], np.ndarray]],
    response_space: ResponseSpace,
    control_mean: np.ndarray,
    config: ComposePhase2Config,
) -> RegimeScore:
    """Score one regime independently (primary bounds + separate secondary)."""
    observed = _truth_from_release(release, pair_ids)
    return score_regime(
        regime=regime,
        pair_ids=pair_ids,
        observed=observed,
        response_space=response_space,
        control_mean=control_mean,
        predictions={method: dict(block) for method, block in predictions.items()},
        headline=_HEADLINE,
        comparators=config.comparator_family,
        confidence=config.family_confidence,
        n_replicates=config.bootstrap_replicates,
        seed=config.split_seed,
        config=config,
    )


@dataclass(frozen=True)
class ActivationProvenanceInputs:
    """Evidence-sourced provenance digests for an activated Phase-2b run.

    Carries the scientific digests that are NOT on the run-identity path (which
    flows from the upstream ledger). Assembled by the caller from the run
    environment and committed activation evidence; passed to :func:`run_phase2b`
    on the activated run. Never carries ``data_card`` / ``raw_data`` /
    ``sequence_mapping`` — those come from the ledger (single source of truth).

    Attributes
    ----------
    processed_sha256, feature_bank_sha256, dependency_lock_sha256 : str
        Processed-AnnData, frozen feature-bank, and dependency-lock digests.
    gears_revision, cpa_revision : str
        Pinned GEARS / CPA baseline revisions (from the dependency lock).
    python_version, platform, device, precision : str
        Run environment tags.
    git_commit : str
        Full Git SHA of the run.
    """

    processed_sha256: str
    feature_bank_sha256: str
    dependency_lock_sha256: str
    gears_revision: str
    cpa_revision: str
    python_version: str
    platform: str
    device: str
    precision: str
    git_commit: str

    def __post_init__(self) -> None:
        """Reject placeholder, malformed, or ambiguous scientific provenance."""
        import re

        for name in (
            "processed_sha256",
            "feature_bank_sha256",
            "dependency_lock_sha256",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError(f"{name} must be a 64-character lowercase SHA-256 hex digest")
        for name in (
            "gears_revision",
            "cpa_revision",
            "python_version",
            "platform",
            "device",
            "precision",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty activation value")
        if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.git_commit) is None:
            raise ValueError("git_commit must be a full 40- or 64-character lowercase hex digest")


def build_activation_provenance_inputs(
    *,
    processed_path: str | Path,
    feature_bank_path: str | Path,
    dependency_lock_path: str | Path,
    gears_requirements_path: str | Path,
    cpa_requirements_path: str | Path,
    environment: EnvironmentInfo,
    device: str,
    precision: str,
) -> ActivationProvenanceInputs:
    """Build activation provenance from actual files and the captured environment."""

    def _pinned_revision(path: str | Path, package: str) -> str:
        prefix = package.casefold() + "=="
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise Phase2bError(
                f"failed to read dependency requirements {str(path)!r}: {exc}"
            ) from exc
        matches = [line.strip() for line in lines if line.strip().casefold().startswith(prefix)]
        if len(matches) != 1:
            raise Phase2bError(
                f"dependency requirements {str(path)!r} must pin exactly one {package} revision"
            )
        return matches[0].split("==", 1)[1]

    paths = {
        "dependency_manifest": dependency_lock_path,
        "gears_requirements": gears_requirements_path,
        "cpa_requirements": cpa_requirements_path,
    }
    try:
        dependency_digest = sha256_json(
            {name: sha256_file(path) for name, path in sorted(paths.items())}
        )
        processed_digest = sha256_file(processed_path)
        feature_digest = sha256_file(feature_bank_path)
    except OSError as exc:
        raise Phase2bError(f"failed to hash activation provenance input: {exc}") from exc

    return ActivationProvenanceInputs(
        processed_sha256=processed_digest,
        feature_bank_sha256=feature_digest,
        dependency_lock_sha256=dependency_digest,
        gears_revision=_pinned_revision(gears_requirements_path, "cell-gears"),
        cpa_revision=_pinned_revision(cpa_requirements_path, "cpa-tools"),
        python_version=environment.python_version,
        platform=environment.platform,
        device=device,
        precision=precision,
        git_commit=environment.git_commit,
    )


def _validate_activation_provenance_environment(
    *, ledger: RunLedger, inputs: ActivationProvenanceInputs
) -> None:
    """Cross-check caller-supplied environment tags against the bound ledger."""
    environment = ledger.to_dict()["environment"]
    expected = {
        "python_version": environment["python_version"],
        "platform": environment["platform"],
        "git_commit": environment["git_commit"],
    }
    mismatches = {
        name: (expected_value, getattr(inputs, name))
        for name, expected_value in expected.items()
        if getattr(inputs, name) != expected_value
    }
    if mismatches:
        raise Phase2bError(
            "ActivationProvenanceInputs disagree with the upstream ledger environment: "
            f"{mismatches}"
        )


def _build_provenance(
    *,
    bundle: FrozenPredictionBundle,
    pair_manifest: Mapping,
    config: ComposePhase2Config,
    audit_reference: str,
    regime_double: RegimeScore | None,
    regime_single: RegimeScore | None,
    git_clean: bool,
    ledger: RunLedger,
    inputs: ActivationProvenanceInputs | None,
    fixture_execution: bool,
) -> Phase2bProvenance:
    """Assemble the COMPLETE composite provenance record for this run.

    Binds the upstream artifact checksums the run consumed (bundle / manifest /
    response-space / factor / model), the scientific provenance digests, the
    registered seeds and the regime-result checksums.

    On the fixture path the scientific digests are synthetic-empty (they are not
    real evidence). On the scientific path the run-identity digests
    (``data_card`` / ``raw_data`` / ``sequence_mapping``) come from the upstream
    ledger — the same values preflight and the run-id recomputation consume, so
    there is ONE source of truth — and the remaining scientific digests come from
    ``inputs``. A scientific run with ``inputs is None`` fails closed (an
    activated run must supply real evidence, never empty digests).

    ``regime_double`` / ``regime_single`` may be ``None`` to build the pre-access
    record (Change C): the regime-result checksums are then empty, which is
    correct because the pre-access subset excludes them.
    """
    if fixture_execution:
        data_card_sha256 = ""
        raw_or_source_sha256 = ""
        processed_sha256 = ""
        sequence_mapping_sha256 = ""
        feature_bank_sha256 = ""
        dependency_lock_sha256 = ""
        gears_revision = ""
        cpa_revision = ""
        python_version = ""
        platform = ""
        device = ""
        precision = ""
        git_commit = "UNKNOWN"
    else:
        if inputs is None:
            raise Phase2bError(
                "scientific Phase-2b requires ActivationProvenanceInputs to populate the "
                "provenance digests; refusing to assemble a provenance record with empty "
                "scientific evidence on an activated run"
            )
        _validate_activation_provenance_environment(ledger=ledger, inputs=inputs)
        # Single source of truth: run-identity digests from the upstream ledger.
        data_card_sha256 = _required_digest(ledger, "data_card")
        raw_or_source_sha256 = _required_digest(ledger, "raw_data")
        sequence_mapping_sha256 = _required_digest(ledger, "sequence_mapping")
        processed_sha256 = inputs.processed_sha256
        feature_bank_sha256 = inputs.feature_bank_sha256
        dependency_lock_sha256 = inputs.dependency_lock_sha256
        gears_revision = inputs.gears_revision
        cpa_revision = inputs.cpa_revision
        python_version = inputs.python_version
        platform = inputs.platform
        device = inputs.device
        precision = inputs.precision
        git_commit = inputs.git_commit

    return Phase2bProvenance(
        protocol=config.protocol,
        config_digest=config.config_sha256,
        pair_manifest_sha256=pair_manifest["checksum"],
        exclusion_manifest_sha256=pair_manifest.get("eligibility_hash", ""),
        data_card_sha256=data_card_sha256,
        raw_or_source_sha256=raw_or_source_sha256,
        processed_sha256=processed_sha256,
        sequence_mapping_sha256=sequence_mapping_sha256,
        feature_bank_sha256=feature_bank_sha256,
        response_space_sha256=bundle.response_space_checksum,
        factor_bank_sha256=bundle.factor_checksum,
        model_lock_sha256=bundle.model_checksum,
        frozen_prediction_bundle_sha256=bundle.bundle_checksum,
        git_commit=git_commit,
        git_clean=bool(git_clean),
        dependency_lock_sha256=dependency_lock_sha256,
        gears_revision=gears_revision,
        cpa_revision=cpa_revision,
        python_version=python_version,
        platform=platform,
        device=device,
        precision=precision,
        registered_seeds=tuple(int(s) for s in config.registered_seeds),
        split_seed=int(config.split_seed),
        seal_audit_reference=audit_reference,
        regime_result_double_sha256=regime_double.checksum if regime_double is not None else "",
        regime_result_single_sha256=regime_single.checksum if regime_single is not None else "",
    )


#: Sentinel substituted for any non-finite embedded float. A ``NaN`` / ``Infinity``
#: anywhere in the registered summary would make the shared terminal canonicalizer
#: REFUSE the write (a latent forced abort on the seal path), so the summary carries
#: only finite floats or this string sentinel (spec §2, CLAUDE.md §5 / §10.10 —
#: report the degenerate value honestly, never a silent NaN).
_NON_FINITE_SENTINEL = "NON_FINITE"

#: The Phase-2 GI-structure recovery is deferred; the summary reports the fixed
#: sentinel string, never a number (mirrors the secondary block's gi_structure).
_GI_STRUCTURE_RECOVERY = "NOT_EVALUABLE"


def _finite_or_sentinel(value: float) -> float | str:
    """Return ``float(value)`` when finite, else :data:`_NON_FINITE_SENTINEL`.

    Every float embedded in the registered summary must be finite or a string
    sentinel; otherwise :meth:`~alive.compose.terminal.Phase2bTerminal._write_terminal`
    (via ``canonicalize_terminal_checksum_input``) refuses a legitimate COMPLETE /
    INVALID write. Thetas are already gated finite on the COMPLETE path; this guards
    the remaining embedded aggregates (per-method MSE, GI point/interval) so a
    degenerate value can never silently force an abort.
    """
    number = float(value)
    return number if math.isfinite(number) else _NON_FINITE_SENTINEL


def build_registered_evaluation_summary(
    *,
    protocol: str,
    run_id: str,
    terminal_state: str,
    sealed_access_count: int,
    regime_double: RegimeScore,
    regime_single: RegimeScore,
    per_method_aggregate_mse: Mapping[str, Mapping[str, float | str]],
    final_verdict: ComposeSealedResult,
    integrity: ComposeIntegrityReport,
    family_confidence: float,
    bootstrap_replicates: int,
    bundle_checksum: str,
    manifest_checksum: str,
    provenance_checksum: str,
    seed_variability_report_checksum: str,
) -> dict:
    """Build the outcome-free ``RegisteredEvaluationSummary`` ONCE (spec §2.1).

    Constructed inside the protected evaluation AFTER the final terminal state and
    final verdict are decided (for ``INVALID`` the verdict is already swapped to
    ``INVALID``). Carries ONLY scalar summaries, per-method / per-comparator
    aggregates, verdict axes/clauses, the integrity disclaimer and content
    checksums — NO per-pair error array, NO per-pair CI, NO raw cell/count matrix.
    Aggregate values (``per_method_aggregate_mse``) are computed ONCE in the
    protected evaluation and COPIED in here; this exporter never recomputes them.

    Every embedded float is passed through :func:`_finite_or_sentinel` so the
    shared terminal canonicalizer can never refuse the write on a non-finite value.

    Parameters
    ----------
    protocol, run_id, terminal_state, sealed_access_count
        Common run identity echoed into the summary.
    regime_double, regime_single : RegimeScore
        The two independently-scored regimes (double-unseen is the headline / sole
        verdict input). Only sample counts, checksums and the double-regime
        secondary GI block are read; per-pair arrays are never embedded.
    per_method_aggregate_mse : Mapping
        ``{"double": {method -> mean(pair_errors[method])}, "single": {...}}`` —
        the per-method aggregate MSE for BOTH regimes, computed ONCE inside the
        protected evaluation. ``double`` is the headline / verdict-linked regime;
        ``single`` is the registered secondary (CLAUDE.md §10). Each regime is
        scored INDEPENDENTLY over its own pairs and the two are NEVER pooled.
    final_verdict : ComposeSealedResult
        The FINAL sealed verdict (swapped to ``INVALID`` on a post-access
        inconsistency). Its axes and clauses are reported verbatim.
    integrity : ComposeIntegrityReport
        The structural integrity self-check; its ``disclaimer`` is embedded.
    family_confidence, bootstrap_replicates
        The registered family confidence and bootstrap replicate count.
    bundle_checksum, manifest_checksum, provenance_checksum,
    seed_variability_report_checksum : str
        The bundle / manifest / provenance / pre-seal seed-variability content
        checksums (regime-result + bounds checksums are read from the regimes).

    Returns
    -------
    dict
        The canonical outcome-free registered summary payload.
    """
    bounds = regime_double.bounds
    secondary = regime_double.secondary
    gi_lower, gi_upper = secondary.gi_explained_interval
    return {
        "protocol": protocol,
        "run_id": run_id,
        "terminal_state": terminal_state,
        "sealed_access_count": int(sealed_access_count),
        "sample_counts": {
            "double": int(regime_double.sample_count),
            "single": int(regime_single.sample_count),
        },
        "per_method_aggregate_mse": {
            regime: {
                method: (
                    regime_mse[method]
                    if isinstance(regime_mse[method], str)
                    else _finite_or_sentinel(float(regime_mse[method]))
                )
                for method in sorted(regime_mse)
            }
            for regime, regime_mse in sorted(per_method_aggregate_mse.items())
        },
        "theta": {c: _finite_or_sentinel(bounds.theta[c]) for c in bounds.comparators},
        "simultaneous_lower_bounds": {
            c: _finite_or_sentinel(bounds.lower[c]) for c in bounds.comparators
        },
        "family_confidence": _finite_or_sentinel(family_confidence),
        "bootstrap_replicates": int(bootstrap_replicates),
        "gi_explained_point": _finite_or_sentinel(secondary.gi_explained_point),
        "gi_explained_interval": [
            _finite_or_sentinel(gi_lower),
            _finite_or_sentinel(gi_upper),
        ],
        "gi_structure_recovery": _GI_STRUCTURE_RECOVERY,
        "sealed_axis": final_verdict.sealed_axis.value,
        "method_axis": final_verdict.method_axis.value,
        "verdict_clauses": {
            k: bool(final_verdict.clauses[k]) for k in sorted(final_verdict.clauses)
        },
        "integrity_disclaimer": integrity.disclaimer,
        "bundle_checksum": bundle_checksum,
        "manifest_checksum": manifest_checksum,
        "provenance_checksum": provenance_checksum,
        "regime_result_double_checksum": regime_double.checksum,
        "regime_result_single_checksum": regime_single.checksum,
        "bounds_checksum": bounds.checksum,
        "seed_variability_report_checksum": seed_variability_report_checksum,
    }


# --------------------------------------------------------------------------- #
# public entry points
# --------------------------------------------------------------------------- #


def run_phase2b(
    *,
    run_dir: str | Path,
    outcome_store: ComposeOutcomeStore,
    frozen_bundle: FrozenPredictionBundle,
    pair_manifest: Mapping,
    response_artifact: Mapping,
    config: ComposePhase2Config,
    ledger: RunLedger,
    activation_record: ActivationRecord | None,
    git_is_clean: bool | None = None,
    provenance_inputs: ActivationProvenanceInputs | None = None,
    oof_manifest_path: str | Path | None = None,
    oof_manifest_checksum: str | None = None,
    seed_variability_report_path: str | Path | None = None,
    seed_variability_report_checksum: str | None = None,
) -> Phase2bResult:
    """Run the SCIENTIFIC Phase-2b sealed evaluation after activation.

    Enforces activation via the same guard Phase-2a uses (config ``active`` + a
    valid :class:`~alive.compose.config2.ActivationRecord` + clean git). The
    current BLOCKED candidate config always fails here. A synthetic-fixture
    outcome store is rejected as non-scientific evidence. NEVER accepts raw
    truth.

    Parameters
    ----------
    run_dir : str or Path
        The run directory (holds the terminal artifact + lock); must exist.
    outcome_store : ComposeOutcomeStore
        The structurally-sealed COMPOSE outcome store. The ONLY path to sealed
        data; opened exactly once.
    frozen_bundle : FrozenPredictionBundle
        The frozen Phase-2a predictions-only handoff.
    pair_manifest : Mapping
        The immutable pair-split manifest.
    response_artifact : Mapping
        ``{"response_space": ResponseSpace, "control_mean": (pca_dim,) vector}``.
    config : ComposePhase2Config
        The validated (candidate or activated) Phase-2 config.
    ledger : RunLedger
        The write-once run ledger recording the bundle + upstream artifacts.
    activation_record : ActivationRecord or None
        Owner activation; required in scientific mode.
    git_is_clean : bool or None, optional
        Whether the working tree is a clean committed Git state; required in
        scientific mode (the caller resolves it so this performs no I/O).
    provenance_inputs : ActivationProvenanceInputs or None, optional
        The activated run's evidence-sourced provenance digests; required to
        populate the scientific provenance on the sealed run.
    oof_manifest_path, oof_manifest_checksum : str, Path or None, optional
        The verified OOF fold manifest path and its self-excluding checksum.
        Required together with the seed-variability report on the scientific
        path (all four provided, or none).
    seed_variability_report_path, seed_variability_report_checksum : str, Path \
or None, optional
        The development seed-variability report path and its verified byte SHA.
        The outcome-free pre-access gate binds + verifies this before any seal
        access; its absence fails closed on the scientific path.

    Returns
    -------
    Phase2bResult
        The frozen sealed-evaluation result.

    Raises
    ------
    alive.compose.config2.ScientificModeError
        If scientific mode is requested but not permitted (the blocked config).
    Phase2bError
        If the seed-variability / OOF-manifest inputs are supplied incompletely.
    """
    provided = (
        oof_manifest_path,
        oof_manifest_checksum,
        seed_variability_report_path,
        seed_variability_report_checksum,
    )
    seed_variability: SeedVariabilityPreflightInputs | None = None
    if any(v is not None for v in provided):
        if any(v is None for v in provided):
            raise Phase2bError(
                "run_phase2b requires oof_manifest_path/checksum AND "
                "seed_variability_report_path/checksum together (all four), or none"
            )
        seed_variability = SeedVariabilityPreflightInputs(
            oof_manifest_path=oof_manifest_path,
            oof_manifest_checksum=oof_manifest_checksum,
            report_source_path=seed_variability_report_path,
            report_checksum=seed_variability_report_checksum,
        )
    assert_scientific_mode_allowed(
        config,
        fixture_mode=False,
        activation_record=activation_record,
        git_is_clean=git_is_clean,
    )
    if _is_fixture_store(outcome_store):
        raise ScientificModeError(
            "scientific Phase2b refuses a synthetic-fixture outcome store; a fixture marker "
            "is not scientific evidence. Use run_phase2b_fixture for bounded synthetic runs."
        )
    return _run_phase2b_core(
        run_dir=run_dir,
        outcome_store=outcome_store,
        frozen_bundle=frozen_bundle,
        pair_manifest=pair_manifest,
        response_artifact=response_artifact,
        config=config,
        ledger=ledger,
        fixture_execution=False,
        git_clean=bool(git_is_clean),
        provenance_tamper=None,
        provenance_inputs=provenance_inputs,
        seed_variability=seed_variability,
    )


def run_phase2b_fixture(
    *,
    run_dir: str | Path,
    outcome_store: ComposeOutcomeStore,
    frozen_bundle: FrozenPredictionBundle,
    pair_manifest: Mapping,
    response_artifact: Mapping,
    config: ComposePhase2Config,
    ledger: RunLedger,
    _tamper_provenance_after_register: Phase2bProvenance | None = None,
) -> Phase2bResult:
    """Run the BOUNDED SYNTHETIC Phase-2b sealed evaluation (no activation).

    The integration-test path. No activation is required, but the outcome store
    must carry a synthetic-fixture marker and the sealed payload must be bounded
    (mirrors Phase-2a's fixture guard). NEVER accepts raw truth.

    Parameters
    ----------
    run_dir, outcome_store, frozen_bundle, pair_manifest, response_artifact,
    config, ledger
        See :func:`run_phase2b`.
    _tamper_provenance_after_register : Phase2bProvenance or None, optional
        TEST-ONLY hook to inject a tampered provenance record AFTER it was
        registered (before access), to exercise the post-access INVALID path. It
        carries no outcome (it is a checksum/identity record) and is never a real
        execution input.

    Returns
    -------
    Phase2bResult
        The frozen sealed-evaluation result.

    Raises
    ------
    Phase2bError
        If the store is not a synthetic-fixture store, or the payload exceeds the
        bounded fixture limits.
    """
    if not _is_fixture_store(outcome_store):
        raise Phase2bError(
            "run_phase2b_fixture requires a synthetic-fixture outcome store (a store "
            "carrying the fixture marker); the scientific store must use run_phase2b"
        )
    _assert_fixture_payload(frozen_bundle)
    return _run_phase2b_core(
        run_dir=run_dir,
        outcome_store=outcome_store,
        frozen_bundle=frozen_bundle,
        pair_manifest=pair_manifest,
        response_artifact=response_artifact,
        config=config,
        ledger=ledger,
        fixture_execution=True,
        git_clean=True,
        provenance_tamper=_tamper_provenance_after_register,
        provenance_inputs=None,
        seed_variability=None,
    )


def _canonical_pair(pair) -> tuple[str, str]:
    """Return the canonical ``(min, max)`` 2-tuple by UTF-8 bytes (locale-free).

    Mirrors the store's canonicalisation so the orchestrator can recompute the
    request checksum without depending on any private store method (the seal
    handle may be a typed wrapper in tests).
    """
    a, b = tuple(pair)
    return (a, b) if a.encode("utf-8") <= b.encode("utf-8") else (b, a)


def _is_fixture_store(outcome_store: object) -> bool:
    """Return ``True`` only for a sanctioned synthetic-fixture store.

    A store is a fixture store IFF it is a :class:`FixtureOutcomeStore` AND its
    carried corpus attestation is in the committed allowlist. BOTH conditions are
    required: a raw ``FixtureOutcomeStore`` built with a non-allowlisted
    attestation does NOT pass, and setting any attribute on a real
    :class:`ComposeOutcomeStore` can never make it read as a fixture store (the
    old spoofable ``_compose_fixture_marker`` boolean is retired).
    """
    return (
        isinstance(outcome_store, FixtureOutcomeStore)
        and getattr(outcome_store, "fixture_corpus_attestation", None) in _FIXTURE_CORPUS_ALLOWLIST
    )


def _assert_fixture_payload(bundle: FrozenPredictionBundle) -> None:
    """Keep the fixture entry point bounded and distinct from scientific data."""
    n_sealed = len(bundle.pair_ids_double_unseen) + len(bundle.pair_ids_single_unseen)
    if n_sealed > _FIXTURE_MAX_SEALED_PAIRS or int(bundle.response_dim) > _FIXTURE_MAX_RESPONSE_DIM:
        raise Phase2bError("fixture payload exceeds the synthetic/tiny-fixture safety limits")


@dataclass(frozen=True)
class SeedVariabilityPreflightInputs:
    """Verified OOF-manifest + development seed-variability report handles (D2 Task 6).

    Threaded EXPLICITLY into the SCIENTIFIC :func:`run_phase2b` so the outcome-free
    pre-access gate can BIND the report into the write-once ledger and VERIFY it
    BEFORE any seal access. Carries paths + verified checksums only — never an
    outcome. The bounded synthetic :func:`run_phase2b_fixture` builds its own
    bounded report and never receives this.

    Attributes
    ----------
    oof_manifest_path : str or Path
        Path to the verified single-call OOF fold manifest JSON.
    oof_manifest_checksum : str
        The manifest's verified self-excluding checksum (cross-checked on load).
    report_source_path : str or Path
        Path to the development seed-variability report produced by
        :func:`alive.compose.seed_variability.development_seed_variability`.
    report_checksum : str
        The verified byte SHA the bound canonical report must reproduce.
    """

    oof_manifest_path: str | Path
    oof_manifest_checksum: str
    report_source_path: str | Path
    report_checksum: str


def _preaccess_seed_variability(
    *,
    run_dir: str | Path,
    ledger: RunLedger,
    frozen_bundle: FrozenPredictionBundle,
    config: ComposePhase2Config,
    fixture_execution: bool,
    seed_variability: SeedVariabilityPreflightInputs | None,
) -> None:
    """Bind + verify the development seed-variability report BEFORE any seal access.

    Writes ``development_seed_variability.json`` into ``run_dir`` and records its
    byte SHA into the write-once ``ledger`` (BEFORE any pre-access snapshot), then
    verifies it. On the SCIENTIFIC path (``fixture_execution=False``) the report is
    REQUIRED — its absence fails closed (seal CLOSED) — and the FULL scientific
    verifier runs; there is no branch that silently bypasses it. The bounded
    synthetic fixture path builds a bounded report and runs the bounded check, so
    it never silently skips the step either. Opens NO seal.

    The ``frozen_bundle`` is the TRUST ROOT for the OOF fold layout: its
    ``dev_diagnostics["oof_fold_manifest_checksum"]`` (bound into the
    self-verifying bundle checksum by D2 Task 1) is the authoritative digest that
    BOTH the loaded :class:`OOFFoldManifest` and the report's bound OOF-manifest
    checksum must equal. The caller-supplied
    ``seed_variability.oof_manifest_checksum`` is retained only as an additional
    defense-in-depth check; it is never the authority.

    Raises
    ------
    Phase2bError
        On a missing scientific input or a caller-side OOF-manifest load / checksum
        mismatch.
    SeedVariabilityReportError, SeedVariabilityPreflightError
        On an absent authoritative bundle digest, an OOF layout that does not bind
        to the frozen bundle, a write-once collision, a byte-SHA / ledger conflict,
        or any verification failure (all PRE-ACCESS; the seal stays CLOSED).
    """
    run_id = frozen_bundle.run_id
    response_space_checksum = frozen_bundle.response_space_checksum
    if fixture_execution:
        report = build_bounded_fixture_seed_variability_report(
            run_id=run_id,
            protocol=config.protocol,
            config_sha256=config.config_sha256,
            registered_seeds=tuple(config.registered_seeds),
            response_space_checksum=response_space_checksum,
        )
        path, _sha = bind_development_seed_variability(
            run_dir=run_dir, ledger=ledger, report=report
        )
        verify_seed_variability_binding_bounded(report_path=path, run_dir=run_dir, ledger=ledger)
        return

    if seed_variability is None:
        raise Phase2bError(
            "scientific Phase2b requires the verified development seed-variability report and "
            "OOF fold manifest (path + checksum); refusing to open the seal without the "
            "pre-access artifact"
        )
    # The frozen bundle is the authority for the development OOF fold layout: read
    # its bound checksum FIRST and fail closed if it is absent (should not happen
    # post D2 Task 1, which binds it into the self-verifying bundle checksum).
    try:
        expected_oof = str(frozen_bundle.dev_diagnostics["oof_fold_manifest_checksum"])
    except KeyError as exc:
        raise SeedVariabilityPreflightError(
            "frozen bundle dev_diagnostics is missing the authoritative "
            "'oof_fold_manifest_checksum'; refusing to open the seal"
        ) from exc
    try:
        oof_manifest = OOFFoldManifest.load(seed_variability.oof_manifest_path)
    except OOFFoldManifestError as exc:
        raise Phase2bError(f"failed to load the OOF fold manifest: {exc}") from exc
    # Defense-in-depth: the caller-supplied value must still match the on-disk
    # manifest, but it is NOT the authority.
    if oof_manifest.manifest_checksum != seed_variability.oof_manifest_checksum:
        raise Phase2bError(
            "OOF fold manifest checksum does not match the verified value: "
            f"{oof_manifest.manifest_checksum!r} != {seed_variability.oof_manifest_checksum!r}"
        )
    # Authority: the loaded manifest MUST bind to the frozen bundle's OOF digest.
    if oof_manifest.manifest_checksum != expected_oof:
        raise SeedVariabilityPreflightError(
            "loaded OOF fold manifest checksum "
            f"{oof_manifest.manifest_checksum!r} != the frozen bundle's authoritative "
            f"oof_fold_manifest_checksum {expected_oof!r}"
        )
    try:
        report = SeedVariabilityReport.load(seed_variability.report_source_path)
    except SeedVariabilityReportError as exc:
        raise Phase2bError(
            f"failed to load the development seed-variability report: {exc}"
        ) from exc
    # Authority: the report's bound OOF-manifest checksum MUST also equal the
    # frozen bundle's digest BEFORE the report is bound into the ledger.
    if report.oof_manifest_checksum != expected_oof:
        raise SeedVariabilityPreflightError(
            "development seed-variability report OOF-manifest checksum "
            f"{report.oof_manifest_checksum!r} != the frozen bundle's authoritative "
            f"oof_fold_manifest_checksum {expected_oof!r}"
        )
    path, _sha = bind_development_seed_variability(
        run_dir=run_dir,
        ledger=ledger,
        report=report,
        expected_report_checksum=seed_variability.report_checksum,
    )
    verify_seed_variability_for_preflight(
        report_path=path,
        run_dir=run_dir,
        ledger=ledger,
        expected_protocol=config.protocol,
        expected_run_id=run_id,
        expected_config_sha256=config.config_sha256,
        expected_registered_seeds=tuple(config.registered_seeds),
        oof_manifest=oof_manifest,
        expected_response_space_checksum=response_space_checksum,
    )


# --------------------------------------------------------------------------- #
# shared core — the 12-step sealed-evaluation flow
# --------------------------------------------------------------------------- #


def _run_phase2b_core(
    *,
    run_dir: str | Path,
    outcome_store: ComposeOutcomeStore,
    frozen_bundle: FrozenPredictionBundle,
    pair_manifest: Mapping,
    response_artifact: Mapping,
    config: ComposePhase2Config,
    ledger: RunLedger,
    fixture_execution: bool,
    git_clean: bool,
    provenance_tamper: Phase2bProvenance | None,
    provenance_inputs: ActivationProvenanceInputs | None,
    seed_variability: SeedVariabilityPreflightInputs | None,
) -> Phase2bResult:
    """The shared 12-step sealed-evaluation flow (after the public boundary).

    Implements (brief steps 1-12):

    1. acquire the exclusive terminal lock BEFORE preflight;
    2. run the outcome-free preflight + the COMPLETE composite pre-access gate;
    3. assert the sealed access count is zero;
    4. persist the EvaluationLock / intent checksum;
    5. claim access then enter the protection boundary;
    6. INSIDE the boundary: open the seal EXACTLY ONCE for the union of both
       sealed roles;
    7. derive truth in the frozen response space;
    8. score double-unseen AND single-unseen SEPARATELY (no pooling);
    9. headline inference = the double-unseen bounds; secondary per regime;
    10. integrity report + sealed verdict (double-unseen ONLY);
    11. post-access consistency → OK / INVALID (never raises);
    12. on OK → complete; on post-access INVALID → invalid; on any in-boundary
        exception → aborted via protect(). Return a frozen Phase2bResult.

    The seal is consumed (step 6) ONLY inside the protection boundary, so every
    consumed access leaves a terminal artifact. A failure in steps 1-4 keeps the
    access count zero and the seal closed, leaving NO terminal artifact.
    """
    run_dir = Path(run_dir)
    if not fixture_execution:
        try:
            verify_split_manifest(dict(pair_manifest))
        except ValueError as exc:
            raise Phase2bError(f"invalid pair manifest: {exc}") from exc
    response_space, control_mean, response_artifact_checksum = _resolve_response_artifact(
        response_artifact,
        require_checksum=not fixture_execution,
    )

    # --- Step 2 (pre-access, outcome-free): bind + verify the development ------
    # seed-variability report BEFORE any seal access. On the scientific path the
    # report is REQUIRED (a missing / tampered / INCOMPLETE / misbound report
    # fails closed here); the fixture path binds + bounded-verifies its own
    # bounded report. The byte SHA is recorded into the write-once ledger BEFORE
    # persist_pre_access_ledger below. The seal is untouched; any failure keeps
    # access_count==0 and leaves NO terminal artifact.
    _preaccess_seed_variability(
        run_dir=run_dir,
        ledger=ledger,
        frozen_bundle=frozen_bundle,
        config=config,
        fixture_execution=fixture_execution,
        seed_variability=seed_variability,
    )

    # --- Step 2 (pre-access, outcome-free): preflight + composite gate. --------
    # The seal is untouched here; any failure leaves access_count==0 and no
    # terminal artifact (the seal was never opened). Preflight runs FIRST so a
    # futility / roster / checksum problem aborts before the lock is even needed.
    expected_response_dim = int(response_space.pca_dim)
    lock = run_preflight(
        bundle=frozen_bundle,
        pair_manifest=pair_manifest,
        config=config,
        data_card_digest="data-card-checksum"
        if fixture_execution
        else _required_digest(ledger, "data_card"),
        raw_or_source_digest="raw-data-checksum"
        if fixture_execution
        else _required_digest(ledger, "raw_data"),
        sequence_mapping_digest="sequence-mapping-checksum"
        if fixture_execution
        else _required_digest(ledger, "sequence_mapping"),
        ledger=ledger,
        expected_response_dim=expected_response_dim,
    )
    if not fixture_execution and response_artifact_checksum != lock.response_space_checksum:
        raise Phase2bError(
            "verified response artifact checksum does not match the frozen bundle / ledger"
        )

    # The COMPLETE composite pre-access gate (a focused superset of the preflight
    # run-id check): recompute the run id and verify the upstream artifacts. On
    # any mismatch/absence this RAISES, leaving the seal closed.
    recomputed_run_id = recompute_run_id(
        config_digest=config.config_sha256,
        data_card_digest="data-card-checksum"
        if fixture_execution
        else _required_digest(ledger, "data_card"),
        raw_or_source_sha256="raw-data-checksum"
        if fixture_execution
        else _required_digest(ledger, "raw_data"),
        sequence_mapping_sha256="sequence-mapping-checksum"
        if fixture_execution
        else _required_digest(ledger, "sequence_mapping"),
    )
    verify_upstream_before_access(
        expected_run_id=lock.run_id,
        recomputed_run_id=recomputed_run_id,
        upstream_ledger=ledger,
        required_artifacts=(
            "pair_manifest",
            "response_space",
            "factor_bank",
            "model",
            "frozen_prediction_bundle",
        ),
        expected_checksums={
            "pair_manifest": lock.manifest_checksum,
            "response_space": lock.response_space_checksum,
            "factor_bank": lock.factor_checksum,
            "model": lock.model_checksum,
            "frozen_prediction_bundle": lock.bundle_checksum,
        },
    )

    # --- Step 1: acquire the exclusive terminal lock (also refuses a re-run). --
    # Acquire AFTER preflight so a pure preflight failure never even creates the
    # lock file (keeping the run dir pristine for a corrected re-run); the lock
    # still precedes the seal opening and refuses a prior terminal / burned audit.
    audit_path = getattr(outcome_store, "_audit_path", None)
    terminal = Phase2bTerminal(
        run_dir,
        ledger=ledger,
        audit_path=audit_path,
        protocol=config.protocol,
        run_id=lock.run_id,
    )
    terminal.acquire()

    # --- Step 3: the sealed access count MUST still be zero. -------------------
    if outcome_store.sealed_access_count != 0:
        raise Phase2bError(
            "invariant violated: sealed access count is non-zero BEFORE the single sealed "
            f"opening (got {outcome_store.sealed_access_count}); refusing to proceed"
        )

    # --- Step 4: record the intent checksum BEFORE opening the seal. ----------
    intent_checksum = sha256_json(
        {
            "run_id": lock.run_id,
            "bundle_checksum": lock.bundle_checksum,
            "manifest_checksum": lock.manifest_checksum,
            "double_pairs": sorted(list(p) for p in lock.pair_ids_double_unseen),
            "single_pairs": sorted(list(p) for p in lock.pair_ids_single_unseen),
        }
    )
    preflight_checksums = {
        "bundle_checksum": lock.bundle_checksum,
        "manifest_checksum": lock.manifest_checksum,
        "intent_checksum": intent_checksum,
        "run_id": lock.run_id,
    }

    # --- Change C: persist the pre-access provenance subset BEFORE the seal opens.
    # The subset excludes post-access result/terminal checksums, so it is fully
    # computable here; recording it write-once lets the post-access check
    # cross-verify a PERSISTED value instead of a self-reference (CLAUDE.md §11).
    audit_reference = str(audit_path) if audit_path is not None else "in-memory"
    pre_access_provenance = _build_provenance(
        bundle=frozen_bundle,
        pair_manifest=pair_manifest,
        config=config,
        audit_reference=audit_reference,
        regime_double=None,
        regime_single=None,
        git_clean=git_clean,
        ledger=ledger,
        inputs=provenance_inputs,
        fixture_execution=fixture_execution,
    )
    record_pre_access_provenance(ledger=ledger, provenance=pre_access_provenance)
    persist_pre_access_ledger(run_dir=run_dir, ledger=ledger)

    # Bind the pre-access provenance identity onto the terminal now that the
    # pre-access ledger is persisted (its file SHA and the provenance self-checksum
    # are the only two common-roster fields not known at construction). Binding
    # BEFORE the seal-open block guarantees an ABORT written from the protection
    # boundary still emits the full common identity roster (CLAUDE.md §11).
    # Bind the pre-access provenance SUBSET checksum (the value persisted into the
    # write-once pre-access ledger under PRE_ACCESS_PROVENANCE_ARTIFACT by
    # record_pre_access_provenance, i.e. provenance.pre_access_checksum), NOT the
    # full self_checksum. The durable finalizer's ABORTED branch — which has no
    # embedded provenance to recompute a subset from — cross-checks the terminal's
    # pre_access_provenance_checksum DIRECTLY against that persisted subset checksum
    # (the non-circular binding); the COMPLETE/INVALID branch recomputes the subset
    # from the embedded provenance instead, so the discrepancy only surfaced on the
    # abort path. This matches the terminal writer's documented use (see
    # tests/alive/compose/test_durable.py _write_aborted_terminal).
    terminal.bind_pre_access(
        pre_access_ledger_sha256=sha256_file(run_dir / PRE_ACCESS_LEDGER_FILENAME),
        pre_access_provenance_checksum=pre_access_provenance.pre_access_checksum,
    )

    # --- Step 5: attempt access, claim the DURABLE seal, then confirm. --------
    # The consumption boundary is the durable audit write inside
    # claim_sealed_access. attempt_access() enters ACCESS_ATTEMPTED (no terminal
    # owed yet); a failure BEFORE the durable claim leaves NO terminal and
    # sealed_access_count == 0. Only the VERIFIED durable audit reference advances
    # the terminal to ACCESS_CLAIMED, after which every exit writes one terminal.
    #
    # D1 §3.3 durable finalize wiring: the seal-open sequence + the protection
    # boundary run inside a single top-level try/except BaseException. On ANY
    # exception the except owner locates the terminal that ``protect`` left and
    # calls the SAME finalizer ONCE — but ONLY if a post-seal terminal file
    # actually exists (a pre-audit failure leaves none → SKIP, seal never opened).
    # It then re-raises with a BARE ``raise`` preserving the original traceback; a
    # finalize failure here is attached as an exception note (it does NOT replace
    # the original evaluation exception) and leaves no marker (incomplete export).
    # The NORMAL / INVALID finalize is OUTSIDE the except so its own failure never
    # re-enters the abort finalize; it runs exactly ONCE after ``protect`` exits
    # (no outcome-bearing evaluation frame is active) and is attached to the frozen
    # result via ``dataclasses.replace``.
    result_box: dict[str, object] = {}
    try:
        terminal.attempt_access()
        union = list(lock.pair_ids_double_unseen) + list(lock.pair_ids_single_unseen)
        claim = outcome_store.claim_sealed_access(lock.run_id, union)
        terminal.confirm_durable_access(claim.audit_reference)

        with terminal.protect(stage=_PROTECT_STAGE, preflight_checksums=preflight_checksums):
            _evaluate_inside_boundary(
                terminal=terminal,
                outcome_store=outcome_store,
                claim=claim,
                lock=lock,
                frozen_bundle=frozen_bundle,
                pair_manifest=pair_manifest,
                config=config,
                response_space=response_space,
                control_mean=control_mean,
                recomputed_run_id=recomputed_run_id,
                audit_reference=audit_reference,
                git_clean=git_clean,
                provenance_tamper=provenance_tamper,
                provenance_inputs=provenance_inputs,
                fixture_execution=fixture_execution,
                result_box=result_box,
            )
        result: Phase2bResult = result_box["result"]  # type: ignore[assignment]
    except BaseException as exc:
        # Abort path: protect wrote ABORTED (or a pre-audit failure wrote no
        # terminal). Finalize ONLY when a post-seal terminal file exists AND the
        # durable inputs are present; a finalize failure is noted, never masking.
        aborted_terminal = _terminal_file_path(run_dir)
        if _durable_inputs_present(run_dir) and aborted_terminal is not None:
            try:
                finalize_phase2b_durable_outputs(
                    run_dir=run_dir,
                    terminal_path=aborted_terminal,
                    pre_access_ledger_path=run_dir / PRE_ACCESS_LEDGER_FILENAME,
                    seed_variability_path=run_dir / DEVELOPMENT_SEED_VARIABILITY_FILENAME,
                )
            except BaseException as fin_exc:  # noqa: BLE001 - noted, never masking
                exc.add_note(
                    "durable finalize failed on abort (incomplete durable export; "
                    f"commit marker absent): {fin_exc!r}"
                )
        raise

    # --- Normal / INVALID path: exactly one terminal was written inside protect. -
    # Finalize ONCE after the boundary exited, then bind the verified commit marker
    # onto the frozen result. A finalize failure here PROPAGATES as a clear
    # DurableLedgerError (the seal is consumed + terminal on disk → recoverable),
    # so the operator learns the export is incomplete rather than it passing silently.
    if _durable_inputs_present(run_dir):
        terminal_path = run_dir / _TERMINAL_STATE_ARTIFACT[result.terminal_state]
        commit = finalize_phase2b_durable_outputs(
            run_dir=run_dir,
            terminal_path=terminal_path,
            pre_access_ledger_path=run_dir / PRE_ACCESS_LEDGER_FILENAME,
            seed_variability_path=run_dir / DEVELOPMENT_SEED_VARIABILITY_FILENAME,
        )
        result = replace(
            result,
            durable_commit_checksum=commit.commit_checksum,
            durable_commit_path=str(commit.commit_marker_path),
        )
    return result


def _evaluate_inside_boundary(
    *,
    terminal: Phase2bTerminal,
    outcome_store: ComposeOutcomeStore,
    claim: SealedAccessClaim,
    lock: EvaluationLock,
    frozen_bundle: FrozenPredictionBundle,
    pair_manifest: Mapping,
    config: ComposePhase2Config,
    response_space: ResponseSpace,
    control_mean: np.ndarray,
    recomputed_run_id: str,
    audit_reference: str,
    git_clean: bool,
    provenance_tamper: Phase2bProvenance | None,
    provenance_inputs: ActivationProvenanceInputs | None,
    fixture_execution: bool,
    result_box: dict[str, object],
) -> None:
    """Steps 6-12, executed INSIDE the terminal protection boundary.

    On any exception here, :meth:`Phase2bTerminal.protect` records an
    ``ABORTED_AFTER_SEAL`` artifact and re-raises — the consumed seal never
    vanishes silently. On a post-access INVALID, an ``INVALID`` terminal is
    written; on success, ``COMPLETE``. Exactly one terminal artifact results.
    """
    double_ids = lock.pair_ids_double_unseen
    single_ids = lock.pair_ids_single_unseen
    union = list(double_ids) + list(single_ids)

    # --- Step 6: materialise the DURABLY-claimed union (seal already burned). --
    # The seal was consumed once by claim_sealed_access (durable audit write) in
    # _run_phase2b_core; this only materialises the claim's observed pairs. A
    # failure HERE is post-audit → the protection boundary writes ABORTED (count
    # 1). materialize_claimed re-verifies the claim against the persisted audit.
    release = outcome_store.materialize_claimed(claim)

    # --- Step 7 + 8: derive truth in the response space; score each regime. ---
    # score_regime projects each ObservedPair through the frozen response space
    # and subtracts the explicit control mean to form observed δ_gh, then scores
    # the regime independently. The two regimes are NEVER pooled.
    regime_double = _score_one_regime(
        regime=_DOUBLE_ROLE,
        pair_ids=double_ids,
        release=release,
        predictions=lock.predictions_double_unseen,
        response_space=response_space,
        control_mean=control_mean,
        config=config,
    )
    regime_single = _score_one_regime(
        regime=_SINGLE_ROLE,
        pair_ids=single_ids,
        release=release,
        predictions=lock.predictions_single_unseen,
        response_space=response_space,
        control_mean=control_mean,
        config=config,
    )

    # --- Step 9 + 10: headline = double-unseen bounds; verdict (double ONLY). --
    sealed_n = regime_double.sample_count
    minimum_sealed = config.sealed_minimum_n
    bounds = regime_double.bounds
    all_finite = bool(
        np.all(np.isfinite(list(bounds.lower.values())))
        and np.all(np.isfinite(list(bounds.theta.values())))
    )
    integrity = ComposeIntegrityReport(
        provenance_ok=True,
        leakage_ok=True,
        all_metrics_finite=all_finite,
        sealed_access_consistent=outcome_store.sealed_access_count == 1,
        sealed_n=sealed_n,
        minimum_sealed=minimum_sealed,
    )
    verdict = sealed_verdict(
        regime=_DOUBLE_ROLE,
        bounds=bounds,
        comparators=config.comparator_family,
        additive_margin=config.material_margin_vs_additive,
        learned_margin=config.learned_comparator_margin,
        integrity=integrity,
        method_axis=MethodAxis.METHOD_VALIDATED,
    )

    # --- Step 11: COMPLETE composite provenance + post-access consistency. -----
    provenance = _build_provenance(
        bundle=frozen_bundle,
        pair_manifest=pair_manifest,
        config=config,
        audit_reference=audit_reference,
        regime_double=regime_double,
        regime_single=regime_single,
        git_clean=git_clean,
        ledger=terminal.ledger,
        inputs=provenance_inputs,
        fixture_execution=fixture_execution,
    )
    expected_provenance_checksum = provenance.self_checksum

    # Change C: cross-check against the PERSISTED pre-access subset (recorded
    # write-once before access), not the in-memory record.
    persisted_ledger = RunLedger.read(terminal.run_dir / PRE_ACCESS_LEDGER_FILENAME)
    persisted_pre_access_checksum = persisted_ledger.artifact_sha(PRE_ACCESS_PROVENANCE_ARTIFACT)

    # Recompute the observed request checksum exactly as the store recorded it.
    # The lock pairs are already canonical (preflight enforces it); canonicalize
    # defensively without depending on the store's private method.
    sorted_pairs = sorted([list(_canonical_pair(p)) for p in union])
    observed_request_checksum = sha256_json(sorted_pairs)
    records = outcome_store.audit_records()
    seal_audit_run_id = records[0]["run_id"] if records else ""
    seal_audit_request_checksum = records[0]["request_checksum"] if records else ""

    # TEST-ONLY: a tampered provenance (registered before access, mismatched now)
    # forces the post-access INVALID path. It is a checksum/identity record only.
    consistency_provenance = provenance_tamper if provenance_tamper is not None else provenance
    post_status = check_post_access_consistency(
        recomputed_run_id=recomputed_run_id,
        seal_audit_run_id=seal_audit_run_id,
        seal_audit_request_checksum=seal_audit_request_checksum,
        observed_request_checksum=observed_request_checksum,
        provenance=consistency_provenance,
        persisted_pre_access_checksum=persisted_pre_access_checksum,
        result_checksums={
            "double": regime_double.checksum,
            "single": regime_single.checksum,
        },
        expected_result_checksums={
            "double": regime_double.checksum,
            "single": regime_single.checksum,
        },
    )

    # --- Step 12: build the outcome-free summary + layered checksums ONCE. ------
    # Aggregates are computed ONCE HERE inside the protected evaluation (spec §2.1);
    # the summary exporter only COPIES them and never recomputes. per-pair error
    # arrays and per-pair CIs are NEVER embedded — only the per-method mean MSE.
    # Reported for BOTH regimes, regime-labeled and scored INDEPENDENTLY (never
    # pooled): double = headline / verdict-linked, single = registered secondary
    # (CLAUDE.md §10). Each embedded float passes _finite_or_sentinel so a
    # degenerate mean becomes the sentinel string, never a summary-write abort.
    per_method_aggregate_mse: dict[str, dict[str, float | str]] = {
        "double": {
            method: _finite_or_sentinel(float(np.mean(regime_double.pair_errors[method])))
            for method in sorted(regime_double.pair_errors)
        },
        "single": {
            method: _finite_or_sentinel(float(np.mean(regime_single.pair_errors[method])))
            for method in sorted(regime_single.pair_errors)
        },
    }
    # evaluation_payload_checksum binds the regime/bounds scoring results directly
    # after scoring (distinct from final_result_checksum, which binds identity).
    evaluation_payload_checksum = sha256_json(
        {
            "double_regime_checksum": regime_double.checksum,
            "single_regime_checksum": regime_single.checksum,
            "double_bounds_checksum": regime_double.bounds.checksum,
            "single_bounds_checksum": regime_single.bounds.checksum,
        }
    )
    # Source the ALREADY-VERIFIED pre-seal seed-variability report checksum from the
    # write-once ledger (bound + verified pre-access); never recomputed here.
    seed_variability_report_checksum = terminal.ledger.artifact_sha(
        DEVELOPMENT_SEED_VARIABILITY_LEDGER_ARTIFACT
    )

    # Decide the FINAL terminal state + FINAL verdict BEFORE building the summary.
    # For INVALID the verdict is swapped to INVALID first (spec §2.1), so the
    # summary and every checksum bind the swapped verdict — never the normal one.
    if post_status is PostAccessStatus.OK:
        final_verdict = verdict
        terminal_state = TerminalState.COMPLETE
    else:
        # A post-access inconsistency dominates: the sealed axis is INVALID and the
        # result is not trustworthy (CLAUDE.md §6 / §11).
        final_verdict = ComposeSealedResult(
            sealed_axis=SealedAxis.INVALID,
            method_axis=verdict.method_axis,
            clauses=dict(verdict.clauses),
            evidence={**verdict.evidence, "post_access_status": post_status.value},
        )
        terminal_state = TerminalState.INVALID

    summary = build_registered_evaluation_summary(
        protocol=provenance.protocol,
        run_id=lock.run_id,
        terminal_state=terminal_state.value,
        sealed_access_count=outcome_store.sealed_access_count,
        regime_double=regime_double,
        regime_single=regime_single,
        per_method_aggregate_mse=per_method_aggregate_mse,
        final_verdict=final_verdict,
        integrity=integrity,
        family_confidence=config.family_confidence,
        bootstrap_replicates=config.bootstrap_replicates,
        bundle_checksum=lock.bundle_checksum,
        manifest_checksum=lock.manifest_checksum,
        provenance_checksum=expected_provenance_checksum,
        seed_variability_report_checksum=seed_variability_report_checksum,
    )
    registered_summary_checksum = sha256_json(summary)
    final_verdict_checksum = final_verdict.checksum
    # final_result_checksum binds EXACTLY these five identity fields (spec §2.1).
    final_result_checksum = sha256_json(
        {
            "terminal_state": terminal_state.value,
            "final_verdict_checksum": final_verdict_checksum,
            "registered_summary_checksum": registered_summary_checksum,
            "evaluation_payload_checksum": evaluation_payload_checksum,
            "provenance_checksum": expected_provenance_checksum,
        }
    )

    # The v2 COMPLETE / INVALID body: exactly the state-specific roster (spec §2.1).
    # The whole-body terminal_payload_checksum is computed by the terminal writer;
    # these are the inner content checksums over specific in-process dicts.
    body = {
        "registered_summary": summary,
        "registered_summary_checksum": registered_summary_checksum,
        "final_verdict_checksum": final_verdict_checksum,
        "terminal_embedded_provenance": provenance.to_dict(),
        "provenance_checksum": expected_provenance_checksum,
        "evaluation_payload_checksum": evaluation_payload_checksum,
        "final_result_checksum": final_result_checksum,
    }

    if terminal_state is TerminalState.COMPLETE:
        terminal.complete(body)
    else:
        terminal.invalid(body)

    result_box["result"] = Phase2bResult(
        run_id=lock.run_id,
        sealed_verdict=final_verdict,
        regime_double=regime_double,
        regime_single=regime_single,
        terminal_state=terminal_state,
        sealed_access_count=outcome_store.sealed_access_count,
        provenance_checksum=expected_provenance_checksum,
        result_checksum=final_result_checksum,
        ledger=terminal.ledger,
    )


def _required_digest(ledger: RunLedger, name: str) -> str:
    """Return a provenance digest from the ledger, raising if absent.

    Used only on the SCIENTIFIC path where the run-identity provenance digests
    are recorded in the upstream ledger. The fixture path uses the bound
    synthetic digests directly (they are not real evidence).
    """
    from alive.provenance import LedgerError

    try:
        return ledger.artifact_sha(name)
    except LedgerError as exc:
        raise Phase2bError(
            f"scientific Phase2b requires the run-identity provenance digest {name!r} in the "
            f"upstream ledger: {exc}"
        ) from exc
