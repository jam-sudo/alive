"""Outcome-free Phase-2b preflight + frozen :class:`EvaluationLock` (Task 2b-2).

Phase 2b opens the COMPOSE seal **exactly once** and produces the confirmatory
verdict (CLAUDE.md §6 multiple-seal rule, §11 write-once provenance). This module
is everything that must be validated BEFORE the seal is touched: it consumes the
frozen Phase-2a :class:`~alive.compose.freeze.FrozenPredictionBundle`, the pair
manifest, the validated config, the run-identity provenance digests and the
run :class:`~alive.provenance.RunLedger`, and freezes the validated NON-outcome
evaluation inputs into an :class:`EvaluationLock`.

Structural outcome-freedom (the load-bearing safety property)
-------------------------------------------------------------
:func:`run_preflight` NEVER accepts or touches a
:class:`~alive.compose.outcome_store.ComposeOutcomeStore`, a sealed truth, an
observed array / dict / path, or any measured outcome. Its only job is to
validate the frozen non-outcome inputs and **fail closed** before any sealed
access could occur. The resulting :class:`EvaluationLock` carries predictions,
role-labelled pair IDs, thresholds, verified hashes and seeds — and is itself
scanned for any measured-outcome marker (reusing the freeze leakage wall) so it
cannot smuggle an observed quantity into the evaluator.

Fail-closed contract
--------------------
There is no ``all([])`` / "available comparator" behaviour: a missing OR extra
registered method / pair / prediction is a FAILURE, not a pass. Every check is
validated over the WHOLE set (no early success return); the first reasonable
violation raises :class:`PreflightError` and NO lock is returned.

The preflight enforces, in order:

1. ``bundle.verify()`` (checksum integrity) and ``bundle.assert_no_outcomes()``.
2. ``bundle.futility_status == "CONTINUE"`` — a futility-stopped dev run is
   refused (CLAUDE.md §6.1: futility-stopped runs end with zero sealed access).
3. method roster EXACT equality (order + membership) against
   ``config.method_roster``.
4. per regime, the bundle's pair-ID set equals the manifest role's pair set
   EXACTLY, pairs canonical; AND each method's prediction keys equal that
   regime's pair set EXACTLY.
5. every prediction vector has shape ``(expected_response_dim,)`` and is finite;
   and ``bundle.response_dim == expected_response_dim``.
6. recomputed composite run id equals the bundle's.
7. bundle/ledger checksum agreement for the frozen bundle and the manifest /
   response-space / factor-bank / model artifacts.
8. ``bundle.manifest_checksum == pair_manifest["checksum"]``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from alive.compose.config2 import ComposePhase2Config
from alive.compose.datacard import compute_compose_run_id
from alive.compose.freeze import (
    FreezeError,
    FrozenPredictionBundle,
    OutcomeLeakageError,
    _assert_no_outcome_reference,
)
from alive.compose.split import ROLE_NAMES
from alive.provenance import LedgerError, RunLedger

#: The two sealed regimes, in their fixed manifest order. ``combo_calibration``
#: (``ROLE_NAMES[0]``) is a development role and is intentionally NOT a sealed
#: evaluation regime.
_DOUBLE_ROLE = ROLE_NAMES[1]  # "sealed_double_unseen"
_SINGLE_ROLE = ROLE_NAMES[2]  # "sealed_single_unseen"

#: Ledger artifact names whose recorded SHA must equal the bundle field of the
#: same meaning. The exact names are those recorded by the Phase-2a orchestrator
#: (:func:`alive.compose.phase2a.run_phase2a`'s ``ledger.record_artifact`` calls).
_LEDGER_BUNDLE_ARTIFACT = "frozen_prediction_bundle"
_LEDGER_UPSTREAM_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("pair_manifest", "manifest_checksum"),
    ("response_space", "response_space_checksum"),
    ("factor_bank", "factor_checksum"),
    ("model", "model_checksum"),
)


class PreflightError(ValueError):
    """Raised when an outcome-free preflight check fails (fail closed).

    Covers every preflight violation: a tampered / unverifiable bundle, a
    futility-stopped dev run, a roster mismatch (missing / extra / reordered
    method), a regime pair-set or prediction-key mismatch (missing / extra), a
    wrong-shape or non-finite prediction, a response-dimension mismatch, a
    recomputed-run-id mismatch, a bundle/ledger checksum disagreement, or a
    manifest-checksum mismatch. On any violation NO :class:`EvaluationLock` is
    returned — the preflight refuses to hand a lock to the (later) seal opener.
    """


@dataclass(frozen=True)
class EvaluationLock:
    """Frozen, outcome-free evaluation inputs for the single sealed opening.

    Carries ONLY the validated non-outcome inputs the evaluator needs: the
    role-labelled sealed pair IDs for both regimes, the predictions for both
    regimes, the registered thresholds, the verified hashes, the seeds and the
    response dimension. It holds NO measured outcome; :meth:`assert_no_outcomes`
    (run in :meth:`__post_init__`) re-scans the whole lock with the freeze
    leakage wall so a measured-outcome marker anywhere fails closed.

    Attributes
    ----------
    run_id : str
        Verified composite COMPOSE run identifier.
    pair_ids_double_unseen, pair_ids_single_unseen : tuple of tuple of str
        Canonical sealed pair IDs per regime (role-labelled by the field name).
    predictions_double_unseen, predictions_single_unseen : dict
        ``method -> {pair_id -> length-response_dim vector}`` per regime;
        predictions only.
    material_margin_vs_additive : float
        Registered primary-metric material margin versus the additive null.
    learned_comparator_margin : float
        Registered margin every learned comparator must be beaten by.
    bundle_checksum : str
        Verified self-excluding SHA-256 of the frozen prediction bundle.
    manifest_checksum, response_space_checksum, factor_checksum, model_checksum :
        str. Verified upstream artifact checksums the evaluation is bound to.
    registered_seeds : tuple of int
        Registered model seeds.
    split_seed : int
        Registered split seed.
    response_dim : int
        Response dimension of every prediction vector.
    """

    run_id: str
    pair_ids_double_unseen: tuple[tuple[str, str], ...]
    pair_ids_single_unseen: tuple[tuple[str, str], ...]
    predictions_double_unseen: dict[str, dict[tuple[str, str], np.ndarray]]
    predictions_single_unseen: dict[str, dict[tuple[str, str], np.ndarray]]
    material_margin_vs_additive: float
    learned_comparator_margin: float
    bundle_checksum: str
    manifest_checksum: str
    response_space_checksum: str
    factor_checksum: str
    model_checksum: str
    registered_seeds: tuple[int, ...]
    split_seed: int
    response_dim: int

    def __post_init__(self) -> None:
        # Fail closed at construction if a measured-outcome marker is present
        # anywhere in the identities / thresholds / hashes / seeds. Numeric
        # prediction arrays carry no token, so this does not fire on them.
        self.assert_no_outcomes()

    def assert_no_outcomes(self) -> None:
        """Assert the lock holds predictions only (no measured outcomes).

        Re-runs the freeze measured-outcome leakage wall over the lock's
        identities, role labels, thresholds, hashes and seeds (the numeric
        prediction arrays carry no string token).

        Raises
        ------
        OutcomeLeakageError
            If a measured-outcome marker is present anywhere.
        """
        # Numeric prediction arrays are intentionally excluded from this token scan: they are
        # token-free numpy floats already validated finite/shaped by freeze.py.
        _assert_no_outcome_reference(
            {
                "run_id": self.run_id,
                "pair_ids_double_unseen": [list(p) for p in self.pair_ids_double_unseen],
                "pair_ids_single_unseen": [list(p) for p in self.pair_ids_single_unseen],
                "prediction_methods": sorted(self.predictions_double_unseen)
                + sorted(self.predictions_single_unseen),
                "bundle_checksum": self.bundle_checksum,
                "manifest_checksum": self.manifest_checksum,
                "response_space_checksum": self.response_space_checksum,
                "factor_checksum": self.factor_checksum,
                "model_checksum": self.model_checksum,
            }
        )


def _canonical_pair_set(
    pairs,
    *,
    context: str,
) -> set[tuple[str, str]]:
    """Return the canonical pair set, refusing non-canonical or duplicate pairs.

    Parameters
    ----------
    pairs : iterable of (str, str)
        Pairs to canonicalise and de-duplicate.
    context : str
        Human-readable context used in error messages.

    Returns
    -------
    set of tuple of str
        The canonical ``(min_utf8, max_utf8)`` pair set.

    Raises
    ------
    PreflightError
        If a pair is not a (str, str), is non-canonical, or is duplicated.
    """
    out: set[tuple[str, str]] = set()
    for raw in pairs:
        items = tuple(raw)
        if len(items) != 2 or not all(isinstance(x, str) for x in items):
            raise PreflightError(f"{context}: pair must be a (str, str), got {items!r}")
        g, h = items
        if g.encode("utf-8") > h.encode("utf-8"):
            raise PreflightError(f"{context}: pair is not canonical (min, max): {items!r}")
        if items in out:
            raise PreflightError(f"{context}: duplicate pair {items!r}")
        out.add(items)
    return out


def _check_regime(
    *,
    role: str,
    bundle_pairs: tuple[tuple[str, str], ...],
    manifest_role_pairs,
    predictions: Mapping[str, Mapping[tuple[str, str], np.ndarray]],
    roster: tuple[str, ...],
    expected_response_dim: int,
) -> None:
    """Validate one sealed regime: pair sets, prediction keys and vectors.

    The bundle's registered pair set must equal the manifest role's pair set
    EXACTLY (no missing, no extra), every pair canonical. Each roster method's
    prediction keys must equal that pair set EXACTLY, and every prediction
    vector must have shape ``(expected_response_dim,)`` and be finite.

    Raises
    ------
    PreflightError
        On any missing / extra / non-canonical pair, any missing / extra
        prediction key, or any wrong-shape / non-finite prediction vector.
    """
    bundle_set = _canonical_pair_set(bundle_pairs, context=f"{role} bundle pairs")
    manifest_set = _canonical_pair_set(manifest_role_pairs, context=f"{role} manifest pairs")

    missing = manifest_set - bundle_set
    extra = bundle_set - manifest_set
    if missing or extra:
        raise PreflightError(
            f"{role}: bundle pair set must equal the manifest role pair set exactly; "
            f"missing from bundle: {sorted(missing)!r}; extra in bundle: {sorted(extra)!r}"
        )

    for method in roster:
        if method not in predictions:
            raise PreflightError(f"{role}: roster method {method!r} has no predictions")
        method_pairs = _canonical_pair_set(
            predictions[method], context=f"{role}/{method} prediction keys"
        )
        pred_missing = bundle_set - method_pairs
        pred_extra = method_pairs - bundle_set
        if pred_missing or pred_extra:
            raise PreflightError(
                f"{role}/{method}: prediction keys must equal the regime pair set exactly; "
                f"missing: {sorted(pred_missing)!r}; extra: {sorted(pred_extra)!r}"
            )
        for pair, vec in predictions[method].items():
            arr = np.asarray(vec, dtype=float)
            if arr.shape != (expected_response_dim,):
                raise PreflightError(
                    f"{role}/{method}: prediction for {tuple(pair)!r} has shape {arr.shape}, "
                    f"expected ({expected_response_dim},)"
                )
            if not np.all(np.isfinite(arr)):
                raise PreflightError(
                    f"{role}/{method}: prediction for {tuple(pair)!r} is not finite"
                )


def _ledger_sha(ledger: RunLedger, name: str) -> str:
    """Return ``ledger.artifact_sha(name)``, re-raising a miss as PreflightError."""
    try:
        return ledger.artifact_sha(name)
    except LedgerError as exc:
        raise PreflightError(f"ledger is missing required artifact {name!r}: {exc}") from exc


def run_preflight(
    *,
    bundle: FrozenPredictionBundle,
    pair_manifest: Mapping,
    config: ComposePhase2Config,
    data_card_digest: str,
    raw_or_source_digest: str,
    sequence_mapping_digest: str,
    ledger: RunLedger,
    expected_response_dim: int,
) -> EvaluationLock:
    """Validate the frozen NON-outcome evaluation inputs and freeze them.

    Outcome-free: this function never receives or touches a sealed outcome store,
    a sealed truth or any observed data. It validates the frozen Phase-2a bundle,
    the pair manifest, the config-bound thresholds, the run-identity provenance
    and the run ledger, then returns a frozen :class:`EvaluationLock` carrying the
    predictions, role-labelled pair IDs, thresholds, verified hashes and seeds
    that the (later) single sealed opening will consume. On the FIRST reasonable
    violation it raises :class:`PreflightError` and returns NO lock.

    Parameters
    ----------
    bundle : FrozenPredictionBundle
        The frozen Phase-2a prediction handoff (predictions only).
    pair_manifest : Mapping
        The immutable pair-split manifest (``roles`` + self-excluding
        ``checksum``) the bundle's sealed pairs were drawn from.
    config : ComposePhase2Config
        The validated Phase-2 config supplying the registered method roster, the
        thresholds and the split seed.
    data_card_digest, raw_or_source_digest, sequence_mapping_digest : str
        The run-identity provenance digests; the composite run id is recomputed
        from them (with ``config.config_sha256``) and must equal the bundle's.
    ledger : RunLedger
        The write-once run ledger recording the bundle and upstream artifact
        checksums.
    expected_response_dim : int
        The required length of every prediction vector; must equal
        ``bundle.response_dim``.

    Returns
    -------
    EvaluationLock
        The frozen, outcome-free evaluation inputs.

    Raises
    ------
    PreflightError
        On any preflight violation (fail closed; no lock returned).
    """
    # 1. checksum integrity + outcome-free bundle.
    try:
        bundle.verify()
    except FreezeError as exc:
        raise PreflightError(f"bundle failed checksum verification: {exc}") from exc
    try:
        bundle.assert_no_outcomes()
    except OutcomeLeakageError as exc:
        raise PreflightError(f"bundle carries a measured-outcome / sealed marker: {exc}") from exc

    # 2. refuse a futility-stopped development run.
    if bundle.futility_status != "CONTINUE":
        raise PreflightError(
            f"bundle.futility_status is {bundle.futility_status!r}, expected 'CONTINUE'; "
            "a futility-stopped dev run is not eligible for a sealed evaluation"
        )

    # 3. method roster EXACT equality (order + membership).
    if tuple(bundle.method_roster) != tuple(config.method_roster):
        raise PreflightError(
            "method roster must equal the registered config roster exactly (order + membership): "
            f"bundle={tuple(bundle.method_roster)!r}, config={tuple(config.method_roster)!r}"
        )
    roster = tuple(config.method_roster)

    # 4 + 5. per-regime pair sets, prediction keys and prediction vectors.
    if not isinstance(pair_manifest, Mapping) or "roles" not in pair_manifest:
        raise PreflightError("pair_manifest must be a mapping carrying a 'roles' block")
    roles = pair_manifest["roles"]
    if not isinstance(roles, Mapping):
        raise PreflightError("pair_manifest['roles'] must be a mapping")
    for required_role in (_DOUBLE_ROLE, _SINGLE_ROLE):
        if required_role not in roles:
            raise PreflightError(f"pair_manifest['roles'] is missing role {required_role!r}")

    _check_regime(
        role=_DOUBLE_ROLE,
        bundle_pairs=bundle.pair_ids_double_unseen,
        manifest_role_pairs=roles[_DOUBLE_ROLE],
        predictions=bundle.predictions_double_unseen,
        roster=roster,
        expected_response_dim=expected_response_dim,
    )
    _check_regime(
        role=_SINGLE_ROLE,
        bundle_pairs=bundle.pair_ids_single_unseen,
        manifest_role_pairs=roles[_SINGLE_ROLE],
        predictions=bundle.predictions_single_unseen,
        roster=roster,
        expected_response_dim=expected_response_dim,
    )

    if int(bundle.response_dim) != int(expected_response_dim):
        raise PreflightError(
            f"bundle.response_dim ({bundle.response_dim}) != expected_response_dim "
            f"({expected_response_dim})"
        )

    # 6. recomputed composite run id must equal the bundle's.
    recomputed = compute_compose_run_id(
        config_digest=config.config_sha256,
        data_card_digest=data_card_digest,
        raw_or_source_digest=raw_or_source_digest,
        sequence_mapping_digest=sequence_mapping_digest,
    )
    if recomputed != bundle.run_id:
        raise PreflightError(
            f"recomputed run id {recomputed!r} != bundle.run_id {bundle.run_id!r}; "
            "the run-identity provenance does not bind this bundle"
        )

    # 7. bundle / ledger checksum agreement.
    ledger_bundle_sha = _ledger_sha(ledger, _LEDGER_BUNDLE_ARTIFACT)
    if ledger_bundle_sha != bundle.bundle_checksum:
        raise PreflightError(
            f"ledger artifact {_LEDGER_BUNDLE_ARTIFACT!r} ({ledger_bundle_sha!r}) != "
            f"bundle.bundle_checksum ({bundle.bundle_checksum!r})"
        )
    for artifact_name, bundle_field in _LEDGER_UPSTREAM_ARTIFACTS:
        ledger_sha = _ledger_sha(ledger, artifact_name)
        bundle_sha = getattr(bundle, bundle_field)
        if ledger_sha != bundle_sha:
            raise PreflightError(
                f"ledger artifact {artifact_name!r} ({ledger_sha!r}) != "
                f"bundle.{bundle_field} ({bundle_sha!r})"
            )

    # 8. manifest checksum agreement.
    if "checksum" not in pair_manifest:
        raise PreflightError("pair_manifest is missing its self-excluding 'checksum'")
    if bundle.manifest_checksum != pair_manifest["checksum"]:
        raise PreflightError(
            f"bundle.manifest_checksum ({bundle.manifest_checksum!r}) != "
            f"pair_manifest['checksum'] ({pair_manifest['checksum']!r})"
        )

    # All checks passed: freeze the validated, outcome-free evaluation inputs.
    def _immutable_predictions(
        predictions: Mapping[str, Mapping[tuple[str, str], np.ndarray]],
    ) -> dict[str, dict[tuple[str, str], np.ndarray]]:
        snapshot: dict[str, dict[tuple[str, str], np.ndarray]] = {}
        for method, block in predictions.items():
            method_snapshot: dict[tuple[str, str], np.ndarray] = {}
            for pair, vector in block.items():
                copied = np.array(vector, dtype=np.float64, copy=True)
                copied.setflags(write=False)
                method_snapshot[tuple(pair)] = copied
            snapshot[method] = method_snapshot
        return snapshot

    return EvaluationLock(
        run_id=bundle.run_id,
        pair_ids_double_unseen=tuple(tuple(p) for p in bundle.pair_ids_double_unseen),
        pair_ids_single_unseen=tuple(tuple(p) for p in bundle.pair_ids_single_unseen),
        predictions_double_unseen=_immutable_predictions(bundle.predictions_double_unseen),
        predictions_single_unseen=_immutable_predictions(bundle.predictions_single_unseen),
        material_margin_vs_additive=float(config.material_margin_vs_additive),
        learned_comparator_margin=float(config.learned_comparator_margin),
        bundle_checksum=bundle.bundle_checksum,
        manifest_checksum=bundle.manifest_checksum,
        response_space_checksum=bundle.response_space_checksum,
        factor_checksum=bundle.factor_checksum,
        model_checksum=bundle.model_checksum,
        registered_seeds=tuple(int(s) for s in bundle.registered_seeds),
        split_seed=int(config.split_seed),
        response_dim=int(bundle.response_dim),
    )
