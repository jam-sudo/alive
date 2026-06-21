"""Selective-prediction metrics for the ALIVE Trust-Gate MVP.

This module scores how well a gate's per-item SCORES rank items by their
observed RISK (energy distance from Task 8).  The risk axis is the *observed*
energy distance passed by the caller — never a conformal error bound.

Conventions
-----------
- ``risk``  : observed per-item risk values (energy distances, ≥0).
- ``score`` : gate score where **higher means less trustworthy** (more likely
  to abstain).  Lower AURC is better.

Sort order
----------
Items are sorted by ``score`` **ascending** (most-trustworthy first).  For
k = 1 … n (number of items covered = predicted):

    coverage_k        = k / n
    selective_risk_k  = (1/k) * sum(r_{1..k})     # mean risk over covered items
    generalized_risk_k= (1/n) * sum(r_{1..k})     # normalized by TOTAL n

    AURC  = (1/n) * sum_{k=1}^{n} selective_risk_k   (discrete mean, Traub 2024)
    AUGRC = (1/n) * sum_{k=1}^{n} generalized_risk_k

Tie convention (order-invariance)
----------------------------------
Items with **equal score** must yield an AURC/AUGRC that is **invariant to
their arbitrary intra-group ordering**.  This is achieved by, after sorting by
score, replacing each item's risk with the **mean risk of its equal-score
group** before forming cumulative sums.  All members of a tie group then share
the group-mean risk, so any intra-group permutation produces identical partial
sums — and therefore identical AURC/AUGRC.

The coverage curve and both area metrics are computed on these tie-averaged
risks.

Public API
----------
MetricError
    Raised for invalid inputs.
REGISTERED_COVERAGE_POINTS
    Module-level tuple ``(0.25, 0.50, 0.70, 1.00)`` — the runner's convenience
    constant for fixed-coverage evaluation.
risk_coverage_curve(risk, score)
    (coverage, selective_risk) arrays of length n, with tie convention applied.
aurc(risk, score)
    Area under the risk-coverage curve (discrete AURC, lower is better).
augrc(risk, score)
    Area under the generalised risk-coverage curve (discrete AUGRC).
risk_at_coverage(risk, score, coverage)
    Selective risk at a fixed coverage point.
normalize_by_mean(risk)
    Cohort-mean normalisation — divides by mean(risk).

Examples
--------
>>> import numpy as np
>>> risk = np.array([0.0, 1.0, 2.0, 3.0])
>>> score = risk.copy()          # perfect ranking
>>> aurc(risk, score)
0.75
>>> augrc(risk, score)
0.625
>>> risk_at_coverage(risk, score, 1.0)
1.5
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

REGISTERED_COVERAGE_POINTS: tuple[float, ...] = (0.25, 0.50, 0.70, 1.00)
"""Fixed coverage points used by the evaluation runner.

Values are ``(0.25, 0.50, 0.70, 1.00)`` as registered in the project protocol.
Pass individual points to :func:`risk_at_coverage`.
"""

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class MetricError(ValueError):
    """Raised when inputs to selective-prediction metrics are invalid.

    Parameters
    ----------
    message : str
        Human-readable description of the problem.
    """


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _validate(
    risk: np.ndarray,
    score: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Shared validation: equal length, n≥1, all finite, risk non-negative.

    Parameters
    ----------
    risk : np.ndarray
        Per-item observed risk values.  Must be finite and non-negative.
    score : np.ndarray
        Per-item gate scores.  Must be finite.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(risk_f64, score_f64)`` cast to ``float64``.

    Raises
    ------
    MetricError
        If arrays are empty, have different lengths, contain non-finite values,
        or if any risk value is negative.
    """
    risk = np.asarray(risk, dtype=np.float64)
    score = np.asarray(score, dtype=np.float64)

    if risk.ndim != 1 or score.ndim != 1:
        raise MetricError("risk and score must be 1-D arrays.")

    if len(risk) == 0:
        raise MetricError("risk and score must be non-empty (n >= 1).")

    if len(risk) != len(score):
        raise MetricError(
            f"risk and score must have the same length; got {len(risk)} and {len(score)}."
        )

    if not np.all(np.isfinite(risk)):
        raise MetricError("risk contains non-finite values (NaN or Inf).")

    if not np.all(np.isfinite(score)):
        raise MetricError("score contains non-finite values (NaN or Inf).")

    if np.any(risk < 0.0):
        raise MetricError("risk values must be non-negative; found negative entries.")

    return risk, score


# ---------------------------------------------------------------------------
# Tie-averaged sorted risks
# ---------------------------------------------------------------------------


def _sorted_tie_averaged_risks(
    risk: np.ndarray,
    score: np.ndarray,
) -> np.ndarray:
    """Return risks sorted ascending by score with the tie convention applied.

    Algorithm
    ---------
    1. Sort items by ``score`` ascending (stable sort preserves original order
       within each tie group, but the tie convention replaces all members with
       the group mean, so the sort order within ties is irrelevant).
    2. Identify contiguous equal-score groups in the sorted order.
    3. Replace each group's risks with the group mean.

    Parameters
    ----------
    risk : np.ndarray
        Validated float64 risk array (length n).
    score : np.ndarray
        Validated float64 score array (length n).

    Returns
    -------
    np.ndarray
        Float64 array of length n: risks in ascending-score order, with
        each equal-score group replaced by the group-mean risk.
    """
    # Stable sort by score ascending (most-trustworthy first)
    order = np.argsort(score, kind="stable")
    sorted_score = score[order]
    sorted_risk = risk[order].copy()

    # Find tie-group boundaries using consecutive-difference trick
    # A new group starts where sorted_score[i] != sorted_score[i-1]
    n = len(sorted_score)
    group_start = 0
    i = 1
    while i <= n:
        # End of a group: either at the end of the array or score changed
        if i == n or sorted_score[i] != sorted_score[group_start]:
            # Replace all risks in [group_start, i) with their mean
            group_mean = float(np.mean(sorted_risk[group_start:i]))
            sorted_risk[group_start:i] = group_mean
            group_start = i
        i += 1

    return sorted_risk


# ---------------------------------------------------------------------------
# Core metric functions
# ---------------------------------------------------------------------------


def risk_coverage_curve(
    risk: np.ndarray,
    score: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Risk-coverage curve with the tie convention applied.

    Items are sorted by ``score`` ascending (most-trustworthy first).
    Equal-score groups have their risks replaced by the group mean before
    forming cumulative sums, making the curve order-invariant within ties.

    Parameters
    ----------
    risk : np.ndarray
        Per-item observed risk values (≥0, finite).
    score : np.ndarray
        Per-item gate scores (finite).  Higher = less trustworthy.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(coverage, selective_risk)`` — two float64 arrays of length n.

        - ``coverage[k-1] = k / n`` for k = 1 … n.
        - ``selective_risk[k-1] = (1/k) * sum(r_{1..k})`` using
          tie-averaged risks.

    Raises
    ------
    MetricError
        See :func:`_validate`.
    """
    risk, score = _validate(risk, score)
    n = len(risk)

    sorted_risk = _sorted_tie_averaged_risks(risk, score)

    # coverage = [1/n, 2/n, ..., n/n]
    ks = np.arange(1, n + 1, dtype=np.float64)
    coverage = ks / n

    # selective_risk_k = cumsum(sorted_risk)[:k] / k
    cumsum = np.cumsum(sorted_risk)
    selective_risk = cumsum / ks

    return coverage, selective_risk


def aurc(risk: np.ndarray, score: np.ndarray) -> float:
    """Discrete Area Under the Risk-Coverage Curve (AURC).

    Lower AURC is better: a perfect gate (lowest-risk items predicted first)
    achieves the minimum AURC for the given risk multiset.

    .. math::

        \\text{AURC} = \\frac{1}{n} \\sum_{k=1}^{n} \\text{selective\\_risk}_k

    The tie convention (equal-score group-mean replacement) ensures this value
    is invariant to the ordering of items within a tie group.

    Parameters
    ----------
    risk : np.ndarray
        Per-item observed risk values (≥0, finite).
    score : np.ndarray
        Per-item gate scores (finite).  Higher = less trustworthy.

    Returns
    -------
    float
        AURC ≥ 0.

    Raises
    ------
    MetricError
        See :func:`_validate`.
    """
    _, selective_risk = risk_coverage_curve(risk, score)
    return float(np.mean(selective_risk))


def augrc(risk: np.ndarray, score: np.ndarray) -> float:
    """Discrete Area Under the Generalised Risk-Coverage Curve (AUGRC).

    Based on Traub et al. (2024): the generalised risk normalises by the
    total n rather than the covered k.

    .. math::

        \\text{generalised\\_risk}_k = \\frac{1}{n} \\sum_{i=1}^{k} r_i
            = \\text{selective\\_risk}_k \\cdot \\text{coverage}_k

        \\text{AUGRC} = \\frac{1}{n} \\sum_{k=1}^{n} \\text{generalised\\_risk}_k

    Parameters
    ----------
    risk : np.ndarray
        Per-item observed risk values (≥0, finite).
    score : np.ndarray
        Per-item gate scores (finite).  Higher = less trustworthy.

    Returns
    -------
    float
        AUGRC ≥ 0.

    Raises
    ------
    MetricError
        See :func:`_validate`.
    """
    coverage, selective_risk = risk_coverage_curve(risk, score)
    generalised_risk = selective_risk * coverage
    return float(np.mean(generalised_risk))


def risk_at_coverage(
    risk: np.ndarray,
    score: np.ndarray,
    coverage: float,
) -> float:
    """Selective risk at a fixed coverage point.

    Computes ``selective_risk_k`` with ``k = max(1, round(coverage * n))``.

    Parameters
    ----------
    risk : np.ndarray
        Per-item observed risk values (≥0, finite).
    score : np.ndarray
        Per-item gate scores (finite).  Higher = less trustworthy.
    coverage : float
        Coverage fraction in ``(0, 1]``.

    Returns
    -------
    float
        Selective risk at the rounded coverage point.

    Raises
    ------
    MetricError
        If ``coverage`` is not in ``(0, 1]``, or if the input arrays are
        invalid (see :func:`_validate`).
    """
    if not (0.0 < coverage <= 1.0):
        raise MetricError(f"coverage must be in (0, 1]; got {coverage!r}.")
    cov_arr, sel_arr = risk_coverage_curve(risk, score)
    n = len(sel_arr)
    k = max(1, round(coverage * n))
    k = min(k, n)  # guard: round may produce n+1 for floating-point reasons
    return float(sel_arr[k - 1])


def normalize_by_mean(risk: np.ndarray) -> np.ndarray:
    """Cohort-mean normalisation: divide risks by their mean.

    Makes AURC/AUGRC margins dimensionless and comparable across perturbations
    with different absolute risk scales.  Since AURC is linear in risk,
    ``aurc(normalize_by_mean(risk), score) == aurc(risk, score) / mean(risk)``.

    Parameters
    ----------
    risk : np.ndarray
        Per-item risk values.  Must have a strictly positive mean.

    Returns
    -------
    np.ndarray
        Float64 array of the same shape, with mean ≈ 1.0.

    Raises
    ------
    MetricError
        If ``mean(risk) <= 0``.

    Notes
    -----
    - Deterministic: no randomness.
    - Rank-preserving: dividing by a positive constant preserves order.
    - Does **not** require risks to be validated against the full ``_validate``
      contract (e.g. finiteness), as callers may apply this to intermediate
      arrays; basic positivity of the mean is the only enforced invariant.
    """
    risk = np.asarray(risk, dtype=np.float64)
    mean_val = float(np.mean(risk))
    if mean_val <= 0.0:
        raise MetricError(
            f"Cannot normalise: mean(risk) = {mean_val} <= 0.  "
            "Cohort-mean normalisation requires a strictly positive mean."
        )
    return risk / mean_val
