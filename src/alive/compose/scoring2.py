"""COMPOSE-K562-v1 Phase-2b regime-specific primary + secondary scoring (Task 2b-4).

SYNTHETIC-ONLY: pure-``numpy`` scoring on synthetic / tiny-fixture inputs.
This module performs **no** seal access and **no** data ingestion. It receives
the populations the single sealed access already yielded (one regime's worth)
plus already-computed per-method predictions, and scores exactly ONE regime.

What this module is for
-----------------------
After the single :meth:`alive.compose.outcome_store.ComposeOutcomeStore.
evaluate_sealed_once` call returns observed populations, the orchestrator
(Task 8) calls :func:`score_regime` ONCE PER REGIME. Each call:

1. preserves the manifest pair order and the regime role label;
2. transforms the observed populations through the **frozen** response-space
   artifact and computes the observed pair shift ``δ_gh`` (minus the explicit
   control mean — the artifact's ``_control_mean`` cache does not survive
   reload, so the caller passes it in);
3. aligns each method's prediction to the regime's canonical pair IDs;
4. computes the per-pair MSE per method
   (:func:`alive.compose.metric2.per_pair_mse`);
5. runs the registered family-wise simultaneous inference for THIS regime
   (:func:`alive.compose.inference2.simultaneous_theta_bounds`), with the
   headline ``l1_bilinear_identifiable`` per-pair MSE as ``headline_errors`` and
   each registered comparator's per-pair MSE as ``comparator_errors``.

Regime independence (no pooling)
--------------------------------
``score_regime`` only ever sees ONE regime's pairs, so the double-unseen and
single-unseen regimes are scored INDEPENDENTLY by construction. Pooling the two
regimes to inflate the apparent sample is impossible at this layer.

Secondary block (NEVER a verdict input)
---------------------------------------
The :class:`SecondaryBlock` is STRUCTURALLY SEPARATE from the primary
:class:`~alive.compose.inference2.ComposeSimultaneousBounds`. The verdict
(Task 5) consumes only the bounds; secondary metrics never enter it.

* ``gi_explained_fraction`` point estimate via the GI identity
  ``eps_pred = headline_pred - additive_pred`` and
  ``eps_truth = observed_δ_gh - additive_pred`` (per pair), WITH a bootstrap
  interval that reuses the EXACT same shared resample primitive
  (:func:`alive.eval.bootstrap._replicate_indices`) and ``family_confidence``
  as the primary inference, so determinism is identical.
* ``gi_structure_recovery`` is :data:`alive.compose.metric2.NOT_EVALUABLE`:
  Phase 2 registers no versioned class-label manifest or prediction-to-class
  rule, so it returns the explicit sentinel — never laundered into a number.
* the interval method and material-regression margin come **from the activated
  config's** :class:`~alive.compose.config2.SecondaryMetricSpec`; absence or a
  governance conflict (``secondary_are_verdict_gates`` True) raises
  :class:`ComposeScoringError` (an activation/preflight-style failure) rather
  than silently defaulting.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cached_property

import numpy as np
from numpy.typing import NDArray

from alive.compose.config2 import ComposePhase2Config, SecondaryMetricSpec
from alive.compose.inference2 import ComposeSimultaneousBounds, simultaneous_theta_bounds
from alive.compose.metric2 import (
    MetricError,
    gi_explained_fraction,
    gi_structure_recovery,
    per_pair_mse,
)
from alive.compose.response import ResponseSpace
from alive.eval.bootstrap import _replicate_indices
from alive.provenance import sha256_json

#: Denominator floor — identical to the metric / inference modules.
_EPS_FLOOR: float = 1e-12

#: The registered secondary metric whose interval this module computes.
_GI_EXPLAINED = "gi_explained_fraction"

#: The additive baseline whose prediction IS δ_g + δ_h (GI identity anchor).
_ADDITIVE = "additive"


class ComposeScoringError(ValueError):
    """Raised on any invalid input or governance conflict in :func:`score_regime`.

    Distinct from :class:`alive.compose.metric2.MetricError` and
    :class:`alive.compose.inference2.ComposeInferenceError` so a COMPOSE caller
    can catch scoring-layer failures (missing pairs, governance conflicts)
    explicitly.
    """


# ---------------------------------------------------------------------------
# Result value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecondaryBlock:
    """Registered secondary reporting for one regime — NEVER a verdict input.

    This object is held by :class:`RegimeScore` in a field that is structurally
    separate from the primary :class:`ComposeSimultaneousBounds`. The verdict
    (Task 5) reads only the bounds.

    Attributes
    ----------
    gi_explained_point : float
        Point estimate of the GI-explained fraction (config secondary
        ``gi_explained_fraction``), via the eps identity.
    gi_explained_interval : tuple[float, float]
        Two-sided ``(lower, upper)`` bootstrap interval at the config
        ``family_confidence`` (e.g. 95%), reusing the shared resample primitive.
    gi_structure : object
        :data:`alive.compose.metric2.NOT_EVALUABLE` — deferred in Phase 2; never
        a number, raises on ``float()``.
    gi_per_pair_error : numpy.ndarray
        Per-pair GI squared-error ``||eps_truth - eps_pred||^2`` (effect-size /
        diagnostic array, ordered by manifest pair IDs).
    theta_mean, theta_median : float
        Effect-size summaries of the per-comparator point ``theta`` from the
        primary bounds (reported for context; NOT a verdict input).
    interval_method : str
        The interval method copied verbatim from the config secondary spec.
    material_regression_margin : float or None
        The registered material-regression margin from the config secondary
        spec (``None`` for descriptive-only metrics).
    governance_note : str or None
        The config secondary spec's governance note.
    confidence : float
        The ``family_confidence`` used for the GI interval.
    """

    gi_explained_point: float
    gi_explained_interval: tuple[float, float]
    gi_structure: object
    gi_per_pair_error: NDArray[np.float64]
    theta_mean: float
    theta_median: float
    interval_method: str
    material_regression_margin: float | None
    governance_note: str | None
    confidence: float

    def _payload(self) -> dict:
        """Canonical, checksum-stable payload (floats via ``repr`` for fidelity)."""
        return {
            "gi_explained_point": repr(self.gi_explained_point),
            "gi_explained_interval": [
                repr(self.gi_explained_interval[0]),
                repr(self.gi_explained_interval[1]),
            ],
            "gi_structure": str(self.gi_structure),
            "gi_per_pair_error": [repr(float(x)) for x in self.gi_per_pair_error],
            "theta_mean": repr(self.theta_mean),
            "theta_median": repr(self.theta_median),
            "interval_method": self.interval_method,
            "material_regression_margin": (
                None
                if self.material_regression_margin is None
                else repr(self.material_regression_margin)
            ),
            "governance_note": self.governance_note,
            "confidence": repr(self.confidence),
        }


@dataclass(frozen=True)
class RegimeScore:
    """Frozen scored result for ONE regime (double-unseen OR single-unseen).

    The primary verdict input is :attr:`bounds`. The :attr:`secondary` block is
    structurally separate and never enters the verdict.

    Attributes
    ----------
    regime : str
        The regime role label (e.g. ``"sealed_double_unseen"``).
    pair_ids : tuple
        The scored pairs, in manifest order (missing pairs excluded when
        ``require_complete=False``).
    pair_errors : dict[str, numpy.ndarray]
        Per-method per-pair MSE arrays (headline + every comparator), each
        ordered by :attr:`pair_ids`. Independent arrays — never shared across
        regimes. This is the SOLE verdict input from this layer (via
        :attr:`bounds`).
    descriptive_pair_errors : dict[str, numpy.ndarray]
        DESCRIPTIVE (non-verdict) per-pair MSE arrays for EVERY roster method
        present in ``predictions`` (all nine: the six verdict methods PLUS
        ``l2_saturation`` / ``no_change`` / ``perturbation_mean``), each ordered
        by :attr:`pair_ids`. The six shared methods' arrays are byte-identical to
        :attr:`pair_errors`. NEVER a verdict input — surfaced only for the
        registered per-method aggregate MSE report (CLAUDE.md#data-eval).
    bounds : ComposeSimultaneousBounds
        The registered family-wise simultaneous lower bounds — the SOLE verdict
        input from this layer.
    secondary : SecondaryBlock
        Registered secondary reporting; NEVER a verdict input.
    sample_count : int
        Number of scored pairs (``len(pair_ids)``).
    missing_pairs : tuple
        Manifest pairs excluded because they lacked an observed population or a
        prediction (always empty when scoring succeeded with
        ``require_complete=True``; populated when ``require_complete=False``).
    """

    regime: str
    pair_ids: tuple
    pair_errors: dict[str, NDArray[np.float64]]
    descriptive_pair_errors: dict[str, NDArray[np.float64]]
    bounds: ComposeSimultaneousBounds
    secondary: SecondaryBlock
    sample_count: int
    missing_pairs: tuple
    headline: str = field(default="")

    def headline_errors_view(self) -> NDArray[np.float64]:
        """Return the headline method's per-pair MSE array (the bounds' input)."""
        return self.pair_errors[self.headline]

    @cached_property
    def checksum(self) -> str:
        """SHA-256 hex digest over the canonical content of this regime score.

        Includes the regime label, ordered pair IDs, per-method pair-error
        arrays, the bounds checksum, the secondary payload, sample count and
        missing IDs. Fixed inputs and seed → identical checksum.
        """
        canonical = {
            "regime": self.regime,
            "headline": self.headline,
            "pair_ids": [list(p) for p in self.pair_ids],
            "pair_errors": {
                name: [repr(float(x)) for x in self.pair_errors[name]]
                for name in sorted(self.pair_errors)
            },
            "bounds_checksum": self.bounds.checksum,
            "secondary": self.secondary._payload(),
            "sample_count": self.sample_count,
            "missing_pairs": sorted(list(p) for p in self.missing_pairs),
        }
        return sha256_json(canonical)


# ---------------------------------------------------------------------------
# Governance gate
# ---------------------------------------------------------------------------


def _resolve_secondary_governance(config: ComposePhase2Config) -> SecondaryMetricSpec:
    """Fail-closed governance check; return the GI-explained secondary spec.

    The interval method and any material-regression margin MUST come from the
    activated config. A missing GI-explained spec, or a config that declares the
    secondaries to be verdict gates, is an activation/preflight-style failure
    (CLAUDE.md#data-eval — secondaries are never verdict gates), not a silent default.

    Parameters
    ----------
    config : ComposePhase2Config
        The activated (or candidate) Phase-2 config.

    Returns
    -------
    SecondaryMetricSpec
        The registered ``gi_explained_fraction`` secondary spec.

    Raises
    ------
    ComposeScoringError
        If ``secondary_are_verdict_gates`` is True, or the GI-explained spec is
        absent, or it is missing its interval method.
    """
    if getattr(config, "secondary_are_verdict_gates", None) is not False:
        raise ComposeScoringError(
            "governance violation: secondary metrics must NOT be verdict gates "
            f"(secondary_are_verdict_gates={config.secondary_are_verdict_gates!r}). "
            "Secondaries are reported separately and never enter the sealed verdict."
        )

    spec = next(
        (s for s in config.secondary_metrics if s.name == _GI_EXPLAINED),
        None,
    )
    if spec is None:
        raise ComposeScoringError(
            f"governance violation: registered secondary metric {_GI_EXPLAINED!r} is absent "
            "from the config; the interval method and material-regression margin must come "
            "from the activated config, not a silent default."
        )
    if not spec.interval_method:
        raise ComposeScoringError(
            f"governance violation: secondary metric {_GI_EXPLAINED!r} has no registered "
            "interval method in the config."
        )
    return spec


# ---------------------------------------------------------------------------
# Alignment & observed-delta helpers
# ---------------------------------------------------------------------------


def _resolve_scored_pairs(
    pair_ids: Sequence,
    observed: Mapping,
    predictions: Mapping[str, Mapping],
    methods: Sequence[str],
    *,
    require_complete: bool,
) -> tuple[list, list]:
    """Split the manifest pairs into scored vs missing (fail-closed-but-reported).

    A manifest pair is "missing" if it lacks an observed population OR any
    method's prediction. With ``require_complete=True`` any missing pair raises
    :class:`ComposeScoringError` (naming the pair and what is missing). With
    ``require_complete=False`` the pair is EXCLUDED AND REPORTED, never silently
    dropped, and manifest order is preserved among the scored pairs.

    Returns
    -------
    (scored, missing)
        ``scored`` preserves manifest order; ``missing`` lists excluded pairs.
    """
    scored: list = []
    missing: list = []
    for pid in pair_ids:
        reasons: list[str] = []
        if pid not in observed:
            reasons.append("observed population")
        for m in methods:
            if pid not in predictions.get(m, {}):
                reasons.append(f"prediction[{m}]")
        if reasons:
            if require_complete:
                raise ComposeScoringError(
                    f"manifest pair {pid!r} is missing: {', '.join(reasons)}. "
                    "Scoring fails closed; a missing observed population or prediction is "
                    "never silently dropped."
                )
            missing.append(pid)
        else:
            scored.append(pid)
    return scored, missing


def _observed_delta_matrix(
    scored: Sequence,
    observed: Mapping,
    response_space: ResponseSpace,
    control_mean: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Observed pair shift ``δ_gh`` per scored pair, in manifest order.

    For each pair, project its raw observed cells through the frozen response
    space and subtract the EXPLICIT control mean (the artifact's
    ``_control_mean`` cache does not survive reload).

    Returns
    -------
    numpy.ndarray
        Shape ``(len(scored), pca_dim)``.
    """
    ctrl = np.asarray(control_mean, dtype=np.float64)
    if ctrl.ndim != 1 or ctrl.shape[0] != response_space.pca_dim:
        raise ComposeScoringError(
            f"control_mean must be a (pca_dim={response_space.pca_dim},) vector, "
            f"got shape {ctrl.shape}."
        )
    rows: list[NDArray[np.float64]] = []
    for pid in scored:
        raw = observed[pid]
        cells = np.asarray(raw.cells if hasattr(raw, "cells") else raw)
        if cells.ndim != 2 or cells.shape[0] == 0:
            raise ComposeScoringError(
                f"observed population for pair {pid!r} must be a non-empty 2-D matrix, "
                f"got shape {cells.shape}."
            )
        proj = response_space.project(cells, np.arange(cells.shape[0]))
        rows.append(proj.mean(axis=0) - ctrl)
    return np.vstack(rows)


def _prediction_matrix(
    method: str,
    scored: Sequence,
    predictions: Mapping[str, Mapping],
    pca_dim: int,
) -> NDArray[np.float64]:
    """Stack a method's per-pair prediction vectors in manifest order."""
    block = predictions[method]
    rows = []
    for pid in scored:
        vec = np.asarray(block[pid], dtype=np.float64).reshape(-1)
        if vec.shape[0] != pca_dim:
            raise ComposeScoringError(
                f"prediction[{method!r}][{pid!r}] must have length pca_dim={pca_dim}, "
                f"got {vec.shape[0]}."
            )
        rows.append(vec)
    return np.vstack(rows)


# ---------------------------------------------------------------------------
# Secondary GI-explained bootstrap interval (reuses the shared primitive)
# ---------------------------------------------------------------------------


def _gi_explained_value(eps_pred: NDArray, eps_truth: NDArray) -> float:
    """Zero-GI-reference explained fraction for an already-aligned row subset.

    ``eps_pred`` and ``eps_truth`` are already row-aligned by construction
    (manifest order), so this computes the registered ratio directly::

        1 - sum||eps_truth - eps_pred||^2 / max(sum||eps_truth||^2, 1e-12)

    This registered secondary is not split-half-noise-ceiling normalized.
    """
    residual_ss = float(np.sum((eps_truth - eps_pred) ** 2))
    truth_ss = float(np.sum(eps_truth**2))
    return 1.0 - residual_ss / max(truth_ss, _EPS_FLOOR)


def _gi_explained_interval(
    eps_pred: NDArray[np.float64],
    eps_truth: NDArray[np.float64],
    *,
    confidence: float,
    n_replicates: int,
    seed: int,
) -> tuple[float, float]:
    """Two-sided bootstrap interval for the GI-explained fraction.

    Reuses the EXACT shared resample primitive
    :func:`alive.eval.bootstrap._replicate_indices` (same ``SeedSequence``
    determinism as the primary inference) at the config ``family_confidence``,
    so the secondary interval is reproducible and consistent with the registered
    interval method (a shared-resample bootstrap).

    Parameters
    ----------
    eps_pred, eps_truth : numpy.ndarray
        Row-aligned predicted / observed GI terms, shape ``(n_pairs, pca_dim)``.
    confidence : float
        Family confidence (e.g. 0.95) → central ``confidence`` interval.
    n_replicates : int
        Bootstrap replicates (must match the primary inference for shared
        determinism).
    seed : int
        Base seed for the shared resample primitive.

    Returns
    -------
    (lower, upper)
        The two-sided percentile interval at ``confidence``.
    """
    n = eps_truth.shape[0]
    stats = np.empty(n_replicates, dtype=np.float64)
    for b in range(n_replicates):
        idx = _replicate_indices(seed, b, n)
        stats[b] = _gi_explained_value(eps_pred[idx], eps_truth[idx])
    alpha = (1.0 - confidence) / 2.0
    lower = float(np.quantile(stats, alpha, method="linear"))
    upper = float(np.quantile(stats, 1.0 - alpha, method="linear"))
    return lower, upper


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def score_regime(
    *,
    regime: str,
    pair_ids: Sequence,
    observed: Mapping,
    response_space: ResponseSpace,
    control_mean: NDArray[np.float64],
    predictions: Mapping[str, Mapping],
    headline: str,
    comparators: Sequence[str],
    confidence: float,
    n_replicates: int,
    seed: int,
    config: ComposePhase2Config,
    require_complete: bool = True,
    class_manifest: dict | None = None,
    prediction_to_class_rule: object | None = None,
) -> RegimeScore:
    """Score ONE regime: primary simultaneous bounds + a separate secondary block.

    The orchestrator (Task 8) calls this twice — once per regime — so the
    double-unseen and single-unseen regimes are scored INDEPENDENTLY and can
    never be pooled at this layer.

    Parameters
    ----------
    regime : str
        The regime role label, preserved verbatim on the result.
    pair_ids : Sequence
        The regime's canonical pair IDs in MANIFEST ORDER (preserved).
    observed : Mapping
        ``pair_id -> raw-count cells`` (an ``np.ndarray`` or an
        :class:`~alive.compose.outcome_store.ObservedPair` with ``.cells``).
    response_space : ResponseSpace
        The frozen response-space artifact; observed cells are projected
        through it.
    control_mean : numpy.ndarray
        EXPLICIT ``(pca_dim,)`` control mean in PCA space (the artifact's cache
        does not survive reload). Observed ``δ_gh`` is
        ``project(cells).mean(0) - control_mean``.
    predictions : Mapping[str, Mapping]
        ``method -> {pair_id -> δ_gh vector}`` for the headline AND every
        comparator. Each vector is the FULL pair shift in PCA space; the
        ``additive`` baseline's prediction IS ``δ_g + δ_h``.
    headline : str
        The headline method name (``"l1_bilinear_identifiable"``), NOT a
        comparator.
    comparators : Sequence[str]
        The exact ordered comparator family (``config.comparator_family``).
    confidence, n_replicates, seed : float, int, int
        Inference params (sourced from the config by the orchestrator). The
        secondary interval reuses ``n_replicates``/``seed`` for shared
        determinism and ``config.family_confidence`` for its width.
    config : ComposePhase2Config
        The activated/candidate config (secondary specs + governance checks).
    require_complete : bool, optional
        ``True`` (default): a manifest pair missing an observed population or any
        prediction raises :class:`ComposeScoringError`. ``False``: such a pair is
        EXCLUDED AND REPORTED in ``missing_pairs`` (never silently dropped).
    class_manifest, prediction_to_class_rule : optional
        Passed through to :func:`gi_structure_recovery`. Phase 2 registers
        neither, so the structure metric stays :data:`NOT_EVALUABLE`.

    Returns
    -------
    RegimeScore
        Frozen result: regime label, ordered pair IDs, per-method pair-error
        arrays, the primary :class:`ComposeSimultaneousBounds`, the structurally
        separate :class:`SecondaryBlock`, sample count, missing/failed pairs and
        a checksum.

    Raises
    ------
    ComposeScoringError
        On a governance conflict, an unknown headline/comparator, a missing pair
        under ``require_complete=True``, an empty scored set, or malformed
        observed/prediction shapes.
    """
    # --- 0. Governance: secondary interval method / margin come from config. ---
    secondary_spec = _resolve_secondary_governance(config)

    # Fail-closed seam guard: the PRIMARY simultaneous band uses ``confidence``
    # while the SECONDARY GI interval uses ``config.family_confidence`` directly.
    # If a caller (the Task 8 orchestrator) ever passes a primary ``confidence``
    # that disagrees with the config family confidence, the two would silently
    # diverge — so refuse to score rather than emit an inconsistent regime.
    if float(confidence) != float(config.family_confidence):
        raise ComposeScoringError(
            "primary confidence must equal config.family_confidence "
            f"(got confidence={confidence!r}, family_confidence={config.family_confidence!r}). "
            "The primary simultaneous band and the secondary GI interval are required to "
            "share one family confidence; they must never diverge."
        )

    # --- 1. Validate the method roster + preserve manifest order. --------------
    comparators = tuple(comparators)
    if headline in comparators:
        raise ComposeScoringError(
            f"headline {headline!r} must NOT be a member of the comparator family "
            f"{list(comparators)}."
        )
    methods = (headline, *comparators)
    for m in methods:
        if m not in predictions:
            raise ComposeScoringError(
                f"predictions is missing required method {m!r} (have: {sorted(predictions)})."
            )
    if _ADDITIVE not in predictions:
        raise ComposeScoringError(
            f"predictions is missing the {_ADDITIVE!r} baseline required for the GI "
            "secondary (eps_pred = headline - additive)."
        )

    scored, missing = _resolve_scored_pairs(
        pair_ids, observed, predictions, methods, require_complete=require_complete
    )
    if not scored:
        raise ComposeScoringError(
            "no scorable pairs in this regime (every manifest pair was empty or missing "
            "an observed population / prediction)."
        )

    scored = list(scored)
    str_ids = [str(p) for p in scored]
    pca_dim = response_space.pca_dim

    # --- 2. Observed δ_gh per pair via the frozen response-space projection. ---
    observed_delta = _observed_delta_matrix(scored, observed, response_space, control_mean)

    # --- 3. + 4. Align each method, then per-pair MSE per method. --------------
    pair_errors: dict[str, NDArray[np.float64]] = {}
    pred_matrices: dict[str, NDArray[np.float64]] = {}
    for m in methods:
        pred = _prediction_matrix(m, scored, predictions, pca_dim)
        pred_matrices[m] = pred
        try:
            pair_errors[m] = per_pair_mse(pred, observed_delta, pair_ids=str_ids, truth_ids=str_ids)
        except MetricError as exc:  # pragma: no cover - defensive
            raise ComposeScoringError(f"per-pair MSE failed for method {m!r}: {exc}") from exc

    # --- 4b. DESCRIPTIVE (non-verdict) per-pair MSE over EVERY roster method. ---
    # freeze validates the full nine-method roster per regime, so predictions
    # carries three methods (l2_saturation / no_change / perturbation_mean) that the
    # verdict does NOT consume. We surface their per-pair MSE descriptively — with
    # the SAME argument shape as the verdict loop — for the registered per-method
    # aggregate MSE report (CLAUDE.md#data-eval). This NEVER feeds the bounds/verdict.
    descriptive_pair_errors: dict[str, NDArray[np.float64]] = {}
    for m in sorted(predictions):
        if m in pair_errors:
            continue  # already computed by the verdict loop (byte-identical); reuse below.
        pred = _prediction_matrix(m, scored, predictions, pca_dim)
        try:
            descriptive_pair_errors[m] = per_pair_mse(
                pred, observed_delta, pair_ids=str_ids, truth_ids=str_ids
            )
        except MetricError as exc:  # pragma: no cover - defensive
            raise ComposeScoringError(
                f"descriptive per-pair MSE failed for method {m!r}: {exc}"
            ) from exc
    # the six verdict methods' descriptive values ARE the verdict values (identical).
    descriptive_pair_errors.update(pair_errors)

    # --- 5. Registered simultaneous inference for THIS regime only. ------------
    bounds = simultaneous_theta_bounds(
        headline_errors=pair_errors[headline],
        comparator_errors={c: pair_errors[c] for c in comparators},
        comparators=comparators,
        confidence=confidence,
        n_replicates=n_replicates,
        seed=seed,
    )

    # --- 6. Secondary block (structurally separate; never a verdict input). ----
    additive_pred = pred_matrices[_ADDITIVE]
    eps_pred = pred_matrices[headline] - additive_pred
    eps_truth = observed_delta - additive_pred

    gi_point = gi_explained_fraction(eps_pred, eps_truth, pair_ids=str_ids, truth_ids=str_ids)
    gi_interval = _gi_explained_interval(
        eps_pred,
        eps_truth,
        confidence=config.family_confidence,
        n_replicates=n_replicates,
        seed=seed,
    )
    gi_per_pair_error = np.sum((eps_truth - eps_pred) ** 2, axis=1)

    # GI structure recovery stays NOT_EVALUABLE (no class manifest in Phase 2).
    gi_structure = gi_structure_recovery(
        eps_pred=eps_pred,
        eps_truth=eps_truth,
        pair_ids=str_ids,
        truth_ids=str_ids,
        class_manifest=class_manifest,
        prediction_to_class_rule=prediction_to_class_rule,
    )

    theta_vals = np.array([bounds.theta[c] for c in comparators], dtype=np.float64)
    secondary = SecondaryBlock(
        gi_explained_point=float(gi_point),
        gi_explained_interval=gi_interval,
        gi_structure=gi_structure,
        gi_per_pair_error=gi_per_pair_error,
        theta_mean=float(np.mean(theta_vals)),
        theta_median=float(np.median(theta_vals)),
        interval_method=secondary_spec.interval_method,
        material_regression_margin=secondary_spec.material_regression_margin,
        governance_note=secondary_spec.governance_note,
        confidence=float(config.family_confidence),
    )

    return RegimeScore(
        regime=regime,
        pair_ids=tuple(scored),
        pair_errors=pair_errors,
        descriptive_pair_errors=descriptive_pair_errors,
        bounds=bounds,
        secondary=secondary,
        sample_count=len(scored),
        missing_pairs=tuple(missing),
        headline=headline,
    )
