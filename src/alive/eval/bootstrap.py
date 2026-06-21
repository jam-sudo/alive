"""Shared max-deviation perturbation-bootstrap primitive (Task 12, Deliverable A).

This module implements the **non-studentized simultaneous max-deviation band**
used to put family-wise one-sided bounds on AURC deltas between a *reference*
selective-prediction method and a family of *comparators*.  It is the single
shared primitive: the preregistered futility rule (Task 12, Deliverable C) and
the sealed confirmatory family (Task 14) both call it — there is no second copy.

What it computes
----------------
For each comparator ``c`` the point delta is::

    point_delta[c] = AURC(risk, score_c) - AURC(risk, score_reference)

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

Determinism
-----------
Per-replicate resample indices are derived with
``numpy.random.SeedSequence(entropy=seed, spawn_key=(replicate,))`` — a pure,
process-stable derivation.  The builtin ``hash()`` is **never** used (it is salted
per process for some types).  A fixed ``seed`` therefore yields a byte-identical
:class:`SimultaneousBounds`.

Public API
----------
BootstrapError
    Raised for invalid inputs.
SimultaneousBounds
    Frozen result dataclass.
simultaneous_delta_bounds(...)
    Compute the simultaneous one-sided band.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from alive.metrics.selective import aurc

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
) -> SimultaneousBounds:
    """Compute a family-wise simultaneous one-sided band on AURC deltas.

    Parameters
    ----------
    risk : np.ndarray
        Shape ``(n,)``.  Per-item risk on the chosen scale (e.g. dev-normalized
        energy distance).  Passed straight to :func:`alive.metrics.selective.aurc`.
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
    # 2. Point AURCs and point deltas (on the full data)
    # ------------------------------------------------------------------
    # Note: ``aurc`` is referenced as a module global so tests can spy on it to
    # verify that all methods within a replicate share resample indices.
    point_aurc = {name: aurc(risk, scores[name]) for name in needed}
    ref_aurc = point_aurc[reference]
    point_delta = {c: point_aurc[c] - ref_aurc for c in comparators}

    # ------------------------------------------------------------------
    # 3. Bootstrap replicates — SAME indices for ALL methods per replicate
    # ------------------------------------------------------------------
    max_dev = np.empty(n_replicates, dtype=np.float64)
    for b in range(n_replicates):
        idx = _replicate_indices(seed, b, n)
        risk_b = risk[idx]
        ref_aurc_b = aurc(risk_b, scores[reference][idx])
        # Centered deviation per comparator: d_c^b = delta_c^b - point_delta[c]
        dev_c = np.empty(len(comparators), dtype=np.float64)
        for j, c in enumerate(comparators):
            delta_cb = aurc(risk_b, scores[c][idx]) - ref_aurc_b
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
