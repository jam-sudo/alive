"""Shared max-deviation perturbation-bootstrap primitive (Task 12, Deliverable A)
and confirmatory simultaneous inference layer (Task 14).

This module implements the **non-studentized simultaneous max-deviation band**
used to put family-wise one-sided bounds on metric deltas between a *reference*
selective-prediction method and a family of *comparators*.  It is the single
shared primitive: the preregistered futility rule (Task 12, Deliverable C) and
the sealed confirmatory family (Task 14) both call it — there is no second copy.

What it computes (primitive)
----------------------------
For each comparator ``c`` the point delta is::

    point_delta[c] = metric(risk, score_c) - metric(risk, score_reference)

where ``metric`` is any callable ``(risk, score) -> float`` (default: ``aurc``).
A higher AURC means a *worse* selective ranking, so ``point_delta[c] > 0`` means
the reference ranks risk better than comparator ``c``.

The simultaneous band is built by a perturbation bootstrap: ``n_replicates``
resamples of the items (with replacement).  Within each replicate the **same
resample indices** are applied to *every* method, so the per-replicate deltas
share their resampling noise.  A single COMMON quantile ``q`` of the maximum
centered deviation across comparators defines the family-wise band:

- ``side="lower"``::

      q        = quantile_confidence_b( max_c ( point_delta[c] - delta_c^b ) )
      bound[c] = point_delta[c] - q

  These are simultaneous LOWER bounds: ``all(bound[c] > 0)`` certifies (at the
  chosen family confidence) that the reference beats *every* comparator.

- ``side="upper"``::

      q        = quantile_confidence_b( max_c ( delta_c^b - point_delta[c] ) )
      bound[c] = point_delta[c] + q

  These are simultaneous UPPER bounds.

Because the same ``q`` is shared across comparators, the band is family-wise
(controls the simultaneous error rate), and ``lower[c] <= point_delta[c] <=
upper[c]`` always holds.

AUGRC degradation identity (used in Task 14)
---------------------------------------------
For the non-studentized symmetric max-deviation band, the following identity
holds exactly when using the *same* ``confidence`` and ``n_replicates``::

    upper_bound(AUGRC_gate - AUGRC_c)  ==  -lower_bound(AUGRC_c - AUGRC_gate)

Derivation: let ``D_c^b = (AUGRC_c^b - AUGRC_gate^b) - (AUGRC_c - AUGRC_gate)``
be the centered deviation in replicate ``b``.  The LOWER bound computation uses::

    q = quantile_alpha( max_c (-D_c^b) )    →   L_c = point_delta[c] - q

Now consider the UPPER bound on ``(AUGRC_gate - AUGRC_c)`` directly.  Define
``delta'_c = -point_delta[c] = AUGRC_gate - AUGRC_c`` and the centered deviation
``(D'_c)^b = -D_c^b``.  The UPPER band gives::

    q' = quantile_alpha( max_c ((D'_c)^b) )
       = quantile_alpha( max_c (-D_c^b) )   [same!]
       = q

    upper_bound_c = delta'_c + q = -point_delta[c] + q = -(point_delta[c] - q) = -L_c

So ``augrc_degradation_upper[c] = -L_c``.  This is implemented by calling the
primitive with ``metric=augrc, reference="gate", side="lower"`` and negating.

Determinism
-----------
Per-replicate resample indices are derived with
``numpy.random.SeedSequence(entropy=seed, spawn_key=(replicate,))`` — a pure,
process-stable derivation.  The builtin ``hash()`` is **never** used (it is salted
per process for some types).  A fixed ``seed`` therefore yields a byte-identical
:class:`SimultaneousBounds` or :class:`ConfirmatoryInference`.

Public API
----------
BootstrapError
    Raised for invalid inputs.
SimultaneousBounds
    Frozen result dataclass (primitive output).
simultaneous_delta_bounds(...)
    Compute the simultaneous one-sided band for any metric.
ConfirmatoryInference
    Frozen dataclass bundling all confirmatory tests (Task 14).
confirmatory_inference(...)
    High-level wrapper: AURC lower bounds + AUGRC degradation upper bounds +
    added-value test + pairwise descriptive intervals.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Callable, Mapping, Sequence

import numpy as np

from alive.metrics.selective import augrc, aurc
from alive.provenance import sha256_json

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class BootstrapError(ValueError):
    """Raised when inputs to the bootstrap primitive are invalid.

    Parameters
    ----------
    message : str
        Human-readable description of the problem.
    """


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimultaneousBounds:
    """Family-wise simultaneous one-sided bounds on AURC deltas.

    Parameters
    ----------
    reference : str
        Name of the reference method (deltas are measured *relative* to it).
    side : str
        ``"lower"`` or ``"upper"`` — which one-sided simultaneous bound was
        computed.
    confidence : float
        Family confidence level in ``(0, 1)`` (e.g. ``0.90``).
    point_delta : dict[str, float]
        Comparator → ``AURC(comparator) - AURC(reference)`` on the full data.
    bound : dict[str, float]
        Comparator → the simultaneous one-sided bound.
    band_halfwidth : float
        The common max-deviation quantile ``q`` shared by all comparators.
    n_replicates : int
        Number of bootstrap replicates used.
    seed : int
        Base seed for the per-replicate resampling.
    """

    reference: str
    side: str
    confidence: float
    point_delta: dict[str, float]
    bound: dict[str, float]
    band_halfwidth: float
    n_replicates: int
    seed: int


# ---------------------------------------------------------------------------
# Deterministic per-replicate index derivation
# ---------------------------------------------------------------------------


def _replicate_indices(seed: int, replicate: int, n: int) -> np.ndarray:
    """Deterministic resample indices for one bootstrap replicate.

    Uses ``numpy.random.SeedSequence(entropy=seed, spawn_key=(replicate,))`` so
    the derivation is pure and process-stable.  The builtin ``hash()`` is not
    used anywhere.

    Parameters
    ----------
    seed : int
        Base seed for the whole bootstrap run.
    replicate : int
        Replicate index ``b`` (``0 <= b < n_replicates``).
    n : int
        Number of items to resample (draws ``n`` indices with replacement from
        ``range(n)``).

    Returns
    -------
    np.ndarray
        Integer array of shape ``(n,)`` with values in ``[0, n)``.
    """
    seq = np.random.SeedSequence(entropy=seed, spawn_key=(replicate,))
    rng = np.random.default_rng(seq)
    return rng.integers(0, n, size=n)


# ---------------------------------------------------------------------------
# Core primitive
# ---------------------------------------------------------------------------


def simultaneous_delta_bounds(
    risk: np.ndarray,
    method_scores: Mapping[str, np.ndarray],
    *,
    reference: str,
    comparators: Sequence[str],
    side: str,
    confidence: float,
    n_replicates: int,
    seed: int,
    metric: Callable[[np.ndarray, np.ndarray], float] | None = None,
) -> SimultaneousBounds:
    """Compute a family-wise simultaneous one-sided band on metric deltas.

    Parameters
    ----------
    risk : np.ndarray
        Shape ``(n,)``.  Per-item risk on the chosen scale (e.g. dev-normalized
        energy distance).  Passed to ``metric(risk, score)``.
    method_scores : Mapping[str, np.ndarray]
        Mapping ``method name -> (n,) per-item score`` (higher = abstain).  Must
        contain ``reference`` and every name in ``comparators``.
    reference : str
        Reference method name.
    comparators : Sequence[str]
        Comparator method names (non-empty).
    side : str
        ``"lower"`` or ``"upper"``.
    confidence : float
        Family confidence in ``(0, 1)``.
    n_replicates : int
        Number of bootstrap replicates (``>= 1``).  The 2000-replicate
        scientific floor is enforced by the config validator, not here.
    seed : int
        Base seed for deterministic per-replicate resampling.
    metric : Callable[[np.ndarray, np.ndarray], float] or None, optional
        Metric function ``(risk, score) -> float``.  Default ``None`` means use
        the module-level ``aurc``.  Passing ``None`` (or omitting the argument)
        preserves full backward-compatibility with all Task 12 callers: the
        module-level ``aurc`` is looked up at call time, so ``monkeypatch.setattr``
        on ``bs.aurc`` is respected by the default path.

    Returns
    -------
    SimultaneousBounds
        Frozen result with point deltas, simultaneous bounds, and the common
        band halfwidth ``q``.

    Raises
    ------
    BootstrapError
        If names are missing, array lengths disagree, ``side`` is invalid,
        ``confidence`` is outside ``(0, 1)``, ``comparators`` is empty, or
        ``n_replicates < 1``.
    """
    # ------------------------------------------------------------------
    # 1. Validation
    # ------------------------------------------------------------------
    if side not in ("lower", "upper"):
        raise BootstrapError(f"side must be 'lower' or 'upper'; got {side!r}.")
    if not (0.0 < confidence < 1.0):
        raise BootstrapError(f"confidence must be in (0, 1); got {confidence!r}.")
    if n_replicates < 1:
        raise BootstrapError(f"n_replicates must be >= 1; got {n_replicates!r}.")
    if len(comparators) == 0:
        raise BootstrapError("comparators must be a non-empty sequence.")

    if reference not in method_scores:
        raise BootstrapError(
            f"reference {reference!r} not found in method_scores "
            f"(available: {sorted(method_scores)})."
        )
    for c in comparators:
        if c not in method_scores:
            raise BootstrapError(
                f"comparator {c!r} not found in method_scores (available: {sorted(method_scores)})."
            )

    risk = np.asarray(risk, dtype=np.float64)
    if risk.ndim != 1:
        raise BootstrapError("risk must be a 1-D array.")
    n = len(risk)
    if n == 0:
        raise BootstrapError("risk must be non-empty.")

    # Materialise the methods we touch (reference first, then comparators in order).
    needed = [reference, *comparators]
    scores: dict[str, np.ndarray] = {}
    for name in needed:
        arr = np.asarray(method_scores[name], dtype=np.float64)
        if arr.ndim != 1 or len(arr) != n:
            raise BootstrapError(
                f"method_scores[{name!r}] must be 1-D of length {n}; got shape {arr.shape}."
            )
        scores[name] = arr

    # ------------------------------------------------------------------
    # 2. Point metric values and point deltas (on the full data)
    # ------------------------------------------------------------------
    # When metric is None (the default), call the module-level ``aurc`` at call
    # time so that test-suite monkeypatching of ``bs.aurc`` is respected — this
    # is a deliberate design for testability.  The boolean ``_use_aurc`` avoids
    # repeated None checks inside the hot loop.
    _use_aurc: bool = metric is None

    def _call_metric(r: np.ndarray, s: np.ndarray) -> float:
        if _use_aurc:
            return aurc(r, s)  # module-level lookup → monkeypatch-safe
        return metric(r, s)  # type: ignore[misc]

    point_m = {name: _call_metric(risk, scores[name]) for name in needed}
    ref_m = point_m[reference]
    point_delta = {c: point_m[c] - ref_m for c in comparators}

    # ------------------------------------------------------------------
    # 3. Bootstrap replicates — SAME indices for ALL methods per replicate
    # ------------------------------------------------------------------
    max_dev = np.empty(n_replicates, dtype=np.float64)
    for b in range(n_replicates):
        idx = _replicate_indices(seed, b, n)
        risk_b = risk[idx]
        ref_m_b = _call_metric(risk_b, scores[reference][idx])
        # Centered deviation per comparator: d_c^b = delta_c^b - point_delta[c]
        dev_c = np.empty(len(comparators), dtype=np.float64)
        for j, c in enumerate(comparators):
            m_cb = _call_metric(risk_b, scores[c][idx])
            delta_cb = m_cb - ref_m_b
            dev_c[j] = delta_cb - point_delta[c]
        if side == "lower":
            # max_c (point_delta[c] - delta_c^b) = max_c (-d_c^b)
            max_dev[b] = float(np.max(-dev_c))
        else:  # upper
            # max_c (delta_c^b - point_delta[c]) = max_c (d_c^b)
            max_dev[b] = float(np.max(dev_c))

    # ------------------------------------------------------------------
    # 4. Common quantile q and the one-sided simultaneous bounds
    # ------------------------------------------------------------------
    q = float(np.quantile(max_dev, confidence, method="linear"))

    if side == "lower":
        bound = {c: point_delta[c] - q for c in comparators}
    else:  # upper
        bound = {c: point_delta[c] + q for c in comparators}

    return SimultaneousBounds(
        reference=reference,
        side=side,
        confidence=confidence,
        point_delta=point_delta,
        bound=bound,
        band_halfwidth=q,
        n_replicates=n_replicates,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Task 14 — Confirmatory inference layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfirmatoryInference:
    """Bundled confirmatory simultaneous inference results (Task 14).

    All bounds are family-wise at ``family_confidence``; pairwise intervals
    are per-comparator percentile CIs for reporting only (NOT simultaneous).

    Parameters
    ----------
    aurc_point_delta : dict[str, float]
        Comparator → ``AURC(comparator) - AURC(gate)`` on the full data.
    aurc_lower_bound : dict[str, float]
        Simultaneous one-sided 95% lower bound per comparator on the AURC delta.
    aurc_family_passes : bool
        ``True`` iff every ``aurc_lower_bound`` value is ``> 0``.
    augrc_degradation_upper : dict[str, float]
        Simultaneous upper bound on ``(AUGRC_gate - AUGRC_c)`` per comparator.
        Derived via the identity: ``-lower_bound(AUGRC_c - AUGRC_gate)``.
        "No material degradation" for ``c`` ⇔ this value ``<= augrc_margin``.
    augrc_margin : float
        Allowed AUGRC degradation margin.
    augrc_no_material_degradation : bool
        ``True`` iff every ``augrc_degradation_upper[c] <= augrc_margin``.
    delta_added_value : float
        ``AURC(residual_only) - AURC(gate)`` on the full data (positive = gate adds value).
    delta_added_value_lower_bound : float
        One-sided 95% simultaneous lower bound on ``delta_added_value``.
    added_value_passes : bool
        ``True`` iff ``delta_added_value_lower_bound > 0``.
    pairwise_intervals : dict[str, tuple[float, float]]
        Comparator → ``(lo, hi)`` percentile CI on the AURC delta.  These are
        per-comparator bootstrap percentiles; NOT simultaneous.  Labelled
        *descriptive* — do not use them for confirmatory decisions.
    family_confidence : float
        Family confidence level in ``(0, 1)``.
    n_replicates : int
        Bootstrap replicates used.
    seed : int
        Base seed for determinism.
    """

    # Primary: AURC simultaneous lower bounds
    aurc_point_delta: dict[str, float]
    aurc_lower_bound: dict[str, float]
    aurc_family_passes: bool
    # Secondary: AUGRC degradation upper bounds
    augrc_degradation_upper: dict[str, float]
    augrc_margin: float
    augrc_no_material_degradation: bool
    # Ablation: full gate vs residual-only
    delta_added_value: float
    delta_added_value_lower_bound: float
    added_value_passes: bool
    # Descriptive (NOT simultaneous): percentile CIs per comparator
    pairwise_intervals: dict[str, tuple[float, float]]
    # Metadata
    family_confidence: float
    n_replicates: int
    seed: int

    @cached_property
    def checksum(self) -> str:
        """SHA-256 hex digest of the canonical content of this result.

        Floats are serialised via ``repr()`` for stable, lossless formatting.
        A fixed ``seed`` and fixed inputs produce an identical checksum.

        Returns
        -------
        str
            64-character lowercase hexadecimal SHA-256 digest.
        """
        canonical = {
            "aurc_point_delta": {k: repr(v) for k, v in sorted(self.aurc_point_delta.items())},
            "aurc_lower_bound": {k: repr(v) for k, v in sorted(self.aurc_lower_bound.items())},
            "aurc_family_passes": self.aurc_family_passes,
            "augrc_degradation_upper": {
                k: repr(v) for k, v in sorted(self.augrc_degradation_upper.items())
            },
            "augrc_margin": repr(self.augrc_margin),
            "augrc_no_material_degradation": self.augrc_no_material_degradation,
            "delta_added_value": repr(self.delta_added_value),
            "delta_added_value_lower_bound": repr(self.delta_added_value_lower_bound),
            "added_value_passes": self.added_value_passes,
            "pairwise_intervals": {
                k: [repr(lo), repr(hi)] for k, (lo, hi) in sorted(self.pairwise_intervals.items())
            },
            "family_confidence": repr(self.family_confidence),
            "n_replicates": self.n_replicates,
            "seed": self.seed,
        }
        return sha256_json(canonical)


def confirmatory_inference(
    risk: np.ndarray,
    method_scores: Mapping[str, np.ndarray],
    *,
    comparators: Sequence[str],
    augrc_margin: float,
    family_confidence: float,
    n_replicates: int,
    seed: int,
) -> ConfirmatoryInference:
    """Confirmatory simultaneous bootstrap inference (Task 14).

    Runs three inference tests using the shared max-deviation bootstrap primitive:

    1. **AURC primary**: simultaneous lower bounds on
       ``AURC(comparator) - AURC(gate)`` for the full comparator family.
       Passes iff every lower bound ``> 0``.

    2. **AUGRC secondary**: simultaneous upper bounds on
       ``AUGRC(gate) - AUGRC(comparator)`` ("gate does not materially degrade").

       Derivation of the identity used here (see module docstring):
       For the symmetric max-deviation band, calling the primitive with
       ``metric=augrc, reference="gate", side="lower"`` yields lower bounds
       ``L_c`` on ``(AUGRC_c - AUGRC_gate)``.  Then::

           upper_bound(AUGRC_gate - AUGRC_c) = -L_c

       because the max-deviation quantile ``q`` is the same for both
       directions (symmetric band).  Hence ``augrc_degradation_upper[c] = -L_c``.
       "No material degradation" ⇔ every ``-L_c <= augrc_margin``
       ⇔ every ``L_c >= -augrc_margin``.

    3. **Added value**: single-comparator family testing whether the full gate
       outperforms ``residual_only``.  Passes iff the lower bound on
       ``AURC(residual_only) - AURC(gate) > 0``.

    Pairwise descriptive intervals are per-comparator bootstrap percentile CIs
    for reporting.  They are NOT family-wise simultaneous — label them as
    *descriptive* when presenting.

    Parameters
    ----------
    risk : np.ndarray
        Shape ``(n,)``.  Per-item risk (already on the chosen scale).
    method_scores : Mapping[str, np.ndarray]
        Must include ``"gate"``, ``"residual_only"``, and all ``comparators``.
    comparators : Sequence[str]
        Full comparator family vs the gate (must not include ``"gate"``).
    augrc_margin : float
        Allowed AUGRC degradation (e.g. ``0.02``).
    family_confidence : float
        Family confidence level in ``(0, 1)`` (e.g. ``0.95``).
    n_replicates : int
        Bootstrap replicates (``>= 1``).
    seed : int
        Base seed for determinism.

    Returns
    -------
    ConfirmatoryInference
        Frozen result with all simultaneous bounds and metadata.
        Fixed ``seed`` → byte-identical result and checksum.
    """
    risk = np.asarray(risk, dtype=np.float64)

    # ------------------------------------------------------------------
    # 1. AURC primary: simultaneous lower bounds on AURC delta (gate is ref)
    # Pass metric=None to use the default (module-level aurc), which keeps the
    # call path identical to Task 12 callers and preserves monkeypatch support.
    # ------------------------------------------------------------------
    aurc_bounds = simultaneous_delta_bounds(
        risk,
        method_scores,
        reference="gate",
        comparators=list(comparators),
        side="lower",
        confidence=family_confidence,
        n_replicates=n_replicates,
        seed=seed,
    )
    aurc_point_delta = dict(aurc_bounds.point_delta)
    aurc_lower_bound = dict(aurc_bounds.bound)
    aurc_family_passes = all(lb > 0.0 for lb in aurc_lower_bound.values())

    # ------------------------------------------------------------------
    # 2. AUGRC secondary: degradation upper bounds via the identity
    #
    # Call primitive with metric=augrc, reference="gate", side="lower"
    # to get L_c = lower_bound(AUGRC_c - AUGRC_gate).
    # Then: upper_bound(AUGRC_gate - AUGRC_c) = -L_c   (see module docstring).
    # "No material degradation" ⇔ -L_c <= augrc_margin ⇔ L_c >= -augrc_margin.
    # ------------------------------------------------------------------
    augrc_lower_obj = simultaneous_delta_bounds(
        risk,
        method_scores,
        reference="gate",
        comparators=list(comparators),
        side="lower",
        confidence=family_confidence,
        n_replicates=n_replicates,
        seed=seed,
        metric=augrc,
    )
    augrc_degradation_upper = {c: -augrc_lower_obj.bound[c] for c in comparators}
    augrc_no_material_degradation = all(v <= augrc_margin for v in augrc_degradation_upper.values())

    # ------------------------------------------------------------------
    # 3. Added value: full gate vs residual_only (single-comparator family)
    # ------------------------------------------------------------------
    av_bounds = simultaneous_delta_bounds(
        risk,
        method_scores,
        reference="gate",
        comparators=["residual_only"],
        side="lower",
        confidence=family_confidence,
        n_replicates=n_replicates,
        seed=seed,
    )
    delta_added_value = float(av_bounds.point_delta["residual_only"])
    delta_added_value_lower_bound = float(av_bounds.bound["residual_only"])
    added_value_passes = delta_added_value_lower_bound > 0.0

    # ------------------------------------------------------------------
    # 4. Pairwise descriptive intervals (per-comparator percentile CIs)
    #
    # These are NOT simultaneous — we compute per-comparator bootstrap
    # percentile CIs of the AURC delta using the same resampling.
    # The alpha-lo tail is (1 - family_confidence) / 2 and hi is the mirror.
    # ------------------------------------------------------------------
    risk_arr = risk
    scores_arr: dict[str, np.ndarray] = {
        name: np.asarray(method_scores[name], dtype=np.float64) for name in method_scores
    }
    n = len(risk_arr)
    alpha_half = (1.0 - family_confidence) / 2.0

    # Collect per-replicate deltas for each comparator
    comp_deltas: dict[str, list[float]] = {c: [] for c in comparators}

    for b in range(n_replicates):
        idx = _replicate_indices(seed, b, n)
        risk_b = risk_arr[idx]
        gate_aurc_b = aurc(risk_b, scores_arr["gate"][idx])
        for c in comparators:
            comp_aurc_b = aurc(risk_b, scores_arr[c][idx])
            comp_deltas[c].append(comp_aurc_b - gate_aurc_b)

    # Per-comparator percentile CI (basic percentile, not bias-corrected)
    pairwise_intervals: dict[str, tuple[float, float]] = {}
    for c in comparators:
        deltas_arr = np.array(comp_deltas[c], dtype=np.float64)
        lo = float(np.quantile(deltas_arr, alpha_half, method="linear"))
        hi = float(np.quantile(deltas_arr, 1.0 - alpha_half, method="linear"))
        pairwise_intervals[c] = (lo, hi)

    return ConfirmatoryInference(
        aurc_point_delta=aurc_point_delta,
        aurc_lower_bound=aurc_lower_bound,
        aurc_family_passes=aurc_family_passes,
        augrc_degradation_upper=augrc_degradation_upper,
        augrc_margin=float(augrc_margin),
        augrc_no_material_degradation=augrc_no_material_degradation,
        delta_added_value=delta_added_value,
        delta_added_value_lower_bound=delta_added_value_lower_bound,
        added_value_passes=added_value_passes,
        pairwise_intervals=pairwise_intervals,
        family_confidence=float(family_confidence),
        n_replicates=n_replicates,
        seed=seed,
    )
