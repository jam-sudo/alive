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

ACTIVATION BLOCKED: this is code + synthetic/tiny-fixture integration tests
only. Real execution remains blocked until the owner activation commit and every
§10.1 activation requirement is complete.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from alive.compose.config2 import (
    ActivationRecord,
    ComposePhase2Config,
    ScientificModeError,
    assert_scientific_mode_allowed,
)
from alive.compose.freeze import FrozenPredictionBundle
from alive.compose.outcome_store import ComposeOutcomeStore, ObservedPair
from alive.compose.preflight import EvaluationLock, run_preflight
from alive.compose.provenance2 import (
    Phase2bProvenance,
    PostAccessStatus,
    check_post_access_consistency,
    recompute_run_id,
    verify_upstream_before_access,
)
from alive.compose.response import ResponseSpace, verify_response_artifact
from alive.compose.scoring2 import RegimeScore, score_regime
from alive.compose.split import verify_split_manifest
from alive.compose.terminal import Phase2bTerminal, TerminalState
from alive.compose.verdict2 import (
    ComposeIntegrityReport,
    ComposeSealedResult,
    MethodAxis,
    SealedAxis,
    sealed_verdict,
)
from alive.provenance import RunLedger, sha256_json

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
        The self-excluding checksum over the terminal report payload.
    ledger : RunLedger
        The write-once ledger carrying the terminal artifact's hash.
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


def _build_provenance(
    *,
    bundle: FrozenPredictionBundle,
    pair_manifest: Mapping,
    config: ComposePhase2Config,
    audit_reference: str,
    regime_double: RegimeScore,
    regime_single: RegimeScore,
    git_clean: bool,
) -> Phase2bProvenance:
    """Assemble the COMPLETE composite provenance record for this run.

    Binds the upstream artifact checksums the run consumed (bundle / manifest /
    response-space / factor / model), the provenance digests, the registered
    seeds and the regime-result checksums. Used for the post-access consistency
    check and recorded into the terminal report.
    """
    # TODO(activation): populate the scientific provenance digests (data_card /
    # raw / processed / sequence_mapping / dependency_lock / gears+cpa revisions /
    # device / precision / git_commit) from the ledger + environment on the
    # activated run; empty/UNKNOWN values are fixture-only.
    return Phase2bProvenance(
        protocol=config.protocol,
        config_digest=config.config_sha256,
        pair_manifest_sha256=pair_manifest["checksum"],
        exclusion_manifest_sha256=pair_manifest.get("eligibility_hash", ""),
        data_card_sha256="",
        raw_or_source_sha256="",
        processed_sha256="",
        sequence_mapping_sha256="",
        feature_bank_sha256="",
        response_space_sha256=bundle.response_space_checksum,
        factor_bank_sha256=bundle.factor_checksum,
        model_lock_sha256=bundle.model_checksum,
        frozen_prediction_bundle_sha256=bundle.bundle_checksum,
        git_commit="UNKNOWN",
        git_clean=bool(git_clean),
        dependency_lock_sha256="",
        gears_revision="",
        cpa_revision="",
        python_version="",
        platform="",
        device="",
        precision="",
        registered_seeds=tuple(int(s) for s in config.registered_seeds),
        split_seed=int(config.split_seed),
        seal_audit_reference=audit_reference,
        regime_result_double_sha256=regime_double.checksum,
        regime_result_single_sha256=regime_single.checksum,
        terminal_report_sha256="",
    )


def _terminal_payload(
    *,
    run_id: str,
    verdict: ComposeSealedResult,
    regime_double: RegimeScore,
    regime_single: RegimeScore,
    lock: EvaluationLock,
    provenance: Phase2bProvenance,
    sealed_access_count: int,
) -> dict:
    """Build the outcome-free terminal report payload (summaries / hashes only).

    Carries NO raw observed cell matrix and NO per-cell vector — only scalar
    summaries, verdict axes, pair counts and content checksums. The terminal
    writer's raw-outcome backstop guards this before any byte is written; the
    orchestrator OWNS the no-raw-outcome property by constructing only summaries.
    """
    return {
        "protocol": "COMPOSE-K562-v1",
        "run_id": run_id,
        "sealed_access_count": int(sealed_access_count),
        "sealed_axis": verdict.sealed_axis.value,
        "method_axis": verdict.method_axis.value,
        "sealed_verdict_checksum": verdict.checksum,
        "verdict_clauses": {k: bool(v) for k, v in verdict.clauses.items()},
        "double_unseen": {
            "regime": regime_double.regime,
            "sample_count": int(regime_double.sample_count),
            "result_checksum": regime_double.checksum,
            "bounds_checksum": regime_double.bounds.checksum,
        },
        "single_unseen": {
            "regime": regime_single.regime,
            "sample_count": int(regime_single.sample_count),
            "result_checksum": regime_single.checksum,
            "bounds_checksum": regime_single.bounds.checksum,
        },
        "bundle_checksum": lock.bundle_checksum,
        "manifest_checksum": lock.manifest_checksum,
        "provenance_checksum": provenance.self_checksum,
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

    Returns
    -------
    Phase2bResult
        The frozen sealed-evaluation result.

    Raises
    ------
    alive.compose.config2.ScientificModeError
        If scientific mode is requested but not permitted (the blocked config).
    """
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
    """Return ``True`` if the store carries the synthetic-fixture marker."""
    return getattr(outcome_store, "_compose_fixture_marker", False) is True


def _assert_fixture_payload(bundle: FrozenPredictionBundle) -> None:
    """Keep the fixture entry point bounded and distinct from scientific data."""
    n_sealed = len(bundle.pair_ids_double_unseen) + len(bundle.pair_ids_single_unseen)
    if n_sealed > _FIXTURE_MAX_SEALED_PAIRS or int(bundle.response_dim) > _FIXTURE_MAX_RESPONSE_DIM:
        raise Phase2bError("fixture payload exceeds the synthetic/tiny-fixture safety limits")


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
    terminal = Phase2bTerminal(run_dir, ledger=ledger, audit_path=audit_path)
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

    # --- Step 5: claim access, then enter the protection boundary. ------------
    terminal.claim_access()
    result_box: dict[str, object] = {}
    with terminal.protect(stage=_PROTECT_STAGE, preflight_checksums=preflight_checksums):
        _evaluate_inside_boundary(
            terminal=terminal,
            outcome_store=outcome_store,
            lock=lock,
            frozen_bundle=frozen_bundle,
            pair_manifest=pair_manifest,
            config=config,
            response_space=response_space,
            control_mean=control_mean,
            recomputed_run_id=recomputed_run_id,
            audit_reference=str(audit_path) if audit_path is not None else "in-memory",
            git_clean=git_clean,
            provenance_tamper=provenance_tamper,
            result_box=result_box,
        )

    return result_box["result"]  # type: ignore[return-value]


def _evaluate_inside_boundary(
    *,
    terminal: Phase2bTerminal,
    outcome_store: ComposeOutcomeStore,
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

    # --- Step 6: open the seal EXACTLY ONCE for the UNION of both roles. -------
    release = outcome_store.evaluate_sealed_once(lock.run_id, union)

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
    )
    expected_provenance_checksum = provenance.self_checksum

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
    # TODO(activation): bind post-access provenance/result consistency against a
    # PERSISTED registered value (recorded into the ledger BEFORE access), not the
    # in-memory provenance object — otherwise the provenance/result legs are
    # self-referential and can never fail in production; only the run-id/
    # request-checksum legs cross-check today.
    post_status = check_post_access_consistency(
        recomputed_run_id=recomputed_run_id,
        seal_audit_run_id=seal_audit_run_id,
        seal_audit_request_checksum=seal_audit_request_checksum,
        observed_request_checksum=observed_request_checksum,
        provenance=consistency_provenance,
        expected_provenance_checksum=expected_provenance_checksum,
        result_checksums={
            "double": regime_double.checksum,
            "single": regime_single.checksum,
        },
        expected_result_checksums={
            "double": regime_double.checksum,
            "single": regime_single.checksum,
        },
    )

    # --- Step 12: write the terminal result + ledger entries ONCE. -------------
    payload = _terminal_payload(
        run_id=lock.run_id,
        verdict=verdict,
        regime_double=regime_double,
        regime_single=regime_single,
        lock=lock,
        provenance=provenance,
        sealed_access_count=outcome_store.sealed_access_count,
    )
    result_checksum = sha256_json(payload)
    payload["result_checksum"] = result_checksum

    if post_status is PostAccessStatus.OK:
        terminal.complete(payload)
        final_verdict = verdict
        terminal_state = TerminalState.COMPLETE
    else:
        terminal.invalid(
            "post-access provenance / audit consistency check failed",
            evidence={
                "run_id": lock.run_id,
                "provenance_checksum": expected_provenance_checksum,
                "result_checksum": result_checksum,
                "post_access_status": post_status.value,
            },
        )
        # A post-access inconsistency dominates: the sealed axis is INVALID and
        # the result is not trustworthy (CLAUDE.md §6 / §11).
        final_verdict = ComposeSealedResult(
            sealed_axis=SealedAxis.INVALID,
            method_axis=verdict.method_axis,
            clauses=dict(verdict.clauses),
            evidence={**verdict.evidence, "post_access_status": post_status.value},
        )
        terminal_state = TerminalState.INVALID

    result_box["result"] = Phase2bResult(
        run_id=lock.run_id,
        sealed_verdict=final_verdict,
        regime_double=regime_double,
        regime_single=regime_single,
        terminal_state=terminal_state,
        sealed_access_count=outcome_store.sealed_access_count,
        provenance_checksum=expected_provenance_checksum,
        result_checksum=result_checksum,
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
