"""COMPOSE-K562-v1 Phase-2b simultaneous theta inference (Task 2b-3).

SYNTHETIC-ONLY: pure-``numpy`` numeric primitive on already-computed
per-pair errors. This module touches **no** seal, **no** outcome store and
**no** real Norman data — it receives per-pair errors that were scored
elsewhere and returns family-wise simultaneous lower bounds.

Why a COMPOSE-specific function (not ``simultaneous_delta_bounds``)
-------------------------------------------------------------------
CARTOGRAPHER's :func:`alive.eval.bootstrap.simultaneous_delta_bounds` forms
``point_delta[c] = metric(reference) - metric(c)``, a *difference* of two
per-method scalar metrics. COMPOSE's registered statistic is a
*ratio-of-means relative-error-reduction*::

    theta_C = (mean(e_C) - mean(e_L1)) / max(mean(e_C), 1e-12)

which does not map onto that difference API. This module therefore implements
a COMPOSE-specific function that **reuses the exact resampling / quantile
machinery** of CARTOGRAPHER:

* the per-replicate resample indices come from the canonical shared primitive
  :func:`alive.eval.bootstrap._replicate_indices`
  (``SeedSequence(entropy=seed, spawn_key=(replicate,))`` →
  ``default_rng(seq).integers(0, n, size=n)``) — never re-implemented here, so
  determinism is provably identical to CARTOGRAPHER's bootstrap;
* a SINGLE common quantile ``q`` of the max-over-comparators centered
  deviation defines the family-wise (simultaneous) band — never a post-hoc
  single pairwise CI (ALIVE governance §10).

What it computes
----------------
For the headline method ``l1_bilinear_identifiable`` with per-pair errors
``e_L1`` and each comparator ``C`` (registered family
``additive, gears, cpa, id_only, l3_symmetric_mlp``) with per-pair errors
``e_C``::

    theta_C       = (mean(e_C) - mean(e_L1)) / max(mean(e_C), 1e-12)
    # shared resamples across contrasts: same idx for headline and EVERY C
    theta_C_b     = (mean(e_C[idx]) - mean(e_L1[idx])) / max(mean(e_C[idx]), 1e-12)
    max_dev[b]    = max_C ( theta_C - theta_C_b )
    q             = quantile_confidence( max_dev )           # common half-width
    lower_C       = theta_C - q                              # simultaneous lower

``all(lower_C > 0)`` certifies (at ``confidence``, family-wise) that the
headline beats EVERY comparator simultaneously.

Determinism
-----------
Per-replicate resample indices are derived only via the shared
:func:`alive.eval.bootstrap._replicate_indices`; the builtin ``hash()`` is
never used. A fixed ``seed`` yields a byte-identical
:class:`ComposeSimultaneousBounds` and ``checksum``.

Error handling
--------------
A local :class:`ComposeInferenceError` (a ``ValueError`` subclass) is raised on
every invalid input. It is intentionally distinct from
:class:`alive.eval.bootstrap.BootstrapError` so a COMPOSE caller can catch
COMPOSE-specific validation failures without coupling to the CARTOGRAPHER
exception type. (Only ``_replicate_indices`` is reused from that module.)
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from alive.eval.bootstrap import _replicate_indices
from alive.provenance import sha256_json

# Denominator floor — kept identical to the config formula string
# ("max(mean(error_comparator), 1e-12)") and to ``alive.compose.metric2``.
_EPS_FLOOR: float = 1e-12

# Headline method name (config ablation_ladder[0]); never a comparator.
HEADLINE_METHOD: str = "l1_bilinear_identifiable"


class ComposeInferenceError(ValueError):
    """Raised on any invalid input to :func:`simultaneous_theta_bounds`.

    Distinct from :class:`alive.eval.bootstrap.BootstrapError` so COMPOSE
    callers can catch COMPOSE-specific validation failures explicitly.
    """


@dataclass(frozen=True)
class ComposeSimultaneousBounds:
    """Family-wise simultaneous one-sided LOWER bounds on theta (COMPOSE Phase-2b).

    Parameters
    ----------
    comparators : tuple[str, ...]
        The exact ordered comparator family (config
        ``inference.comparator_family``). The headline
        ``l1_bilinear_identifiable`` is never a member.
    theta : dict[str, float]
        Comparator → stabilized relative error reduction.
        on the full data.
    lower : dict[str, float]
        Comparator → simultaneous one-sided lower bound ``theta_C - q``, sharing
        the common half-width ``q``.
    band_halfwidth : float
        The common max-deviation quantile ``q`` shared by every comparator.
    confidence : float
        Family confidence level in ``(0, 1)`` (e.g. ``0.95``).
    n_replicates : int
        Number of bootstrap replicates used.
    seed : int
        Base seed for the per-replicate resampling.
    """

    comparators: tuple[str, ...]
    theta: dict[str, float]
    lower: dict[str, float]
    band_halfwidth: float
    confidence: float
    n_replicates: int
    seed: int

    @cached_property
    def checksum(self) -> str:
        """SHA-256 hex digest of the canonical content of this result.

        Floats are serialised via ``repr()`` for stable, lossless formatting and
        the comparator order is preserved as a list, so a fixed ``seed`` and
        fixed inputs produce an identical checksum across processes.

        Returns
        -------
        str
            64-character lowercase hexadecimal SHA-256 digest.
        """
        canonical = {
            "comparators": list(self.comparators),
            "theta": [repr(self.theta[c]) for c in self.comparators],
            "lower": [repr(self.lower[c]) for c in self.comparators],
            "band_halfwidth": repr(self.band_halfwidth),
            "confidence": repr(self.confidence),
            "n_replicates": self.n_replicates,
            "seed": self.seed,
        }
        return sha256_json(canonical)


def _theta(mean_headline: float, mean_comparator: float) -> float:
    """Registered relative-error-reduction statistic with the 1e-12 floor."""
    return (mean_comparator - mean_headline) / max(mean_comparator, _EPS_FLOOR)


def _validate_error_array(arr: np.ndarray, n: int, name: str) -> np.ndarray:
    """Coerce to a 1-D float64 array of length ``n`` with finite, non-negative values."""
    a = np.asarray(arr, dtype=np.float64)
    if a.ndim != 1:
        raise ComposeInferenceError(f"{name} must be 1-D; got ndim={a.ndim}.")
    if len(a) != n:
        raise ComposeInferenceError(f"{name} must have length {n}; got {len(a)}.")
    if not np.all(np.isfinite(a)):
        raise ComposeInferenceError(f"{name} contains non-finite values (nan/inf).")
    if np.any(a < 0.0):
        raise ComposeInferenceError(
            f"{name} contains negative values; errors are squared distances >= 0."
        )
    return a


def simultaneous_theta_bounds(
    *,
    headline_errors: np.ndarray,
    comparator_errors: Mapping[str, np.ndarray],
    comparators: Sequence[str],
    confidence: float,
    n_replicates: int,
    seed: int,
) -> ComposeSimultaneousBounds:
    r"""One-sided non-studentized max-deviation SIMULTANEOUS lower bounds on theta.

    For each comparator ``C`` in the exact registered family, the point
    statistic is the COMPOSE relative-error-reduction::

        theta_C = (mean(e_C) - mean(e_L1)) / max(mean(e_C), 1e-12)

    A single common quantile ``q`` of the max-over-comparators centered
    deviation defines the family-wise lower band (``shared_resamples_across_
    contrasts: true`` — the SAME resample indices are used for the headline and
    EVERY comparator within each replicate)::

        for b in range(n_replicates):
            idx        = _replicate_indices(seed, b, n)   # shared primitive
            theta_C_b  = (mean(e_C[idx]) - mean(e_L1[idx])) / max(mean(e_C[idx]), 1e-12)
            max_dev[b] = max_C ( theta_C - theta_C_b )
        q       = quantile(max_dev, confidence, method="linear")
        lower_C = theta_C - q

    Parameters
    ----------
    headline_errors : numpy.ndarray
        Shape ``(n,)``. Per-pair error of the headline method
        ``l1_bilinear_identifiable`` (e.g. per-pair squared distance ``>= 0``).
    comparator_errors : Mapping[str, numpy.ndarray]
        Mapping ``comparator name -> (n,)`` per-pair error. Must contain every
        name in ``comparators``.
    comparators : Sequence[str]
        The EXACT ordered comparator family
        (``additive, gears, cpa, id_only, l3_symmetric_mlp``). Non-empty; the
        headline ``l1_bilinear_identifiable`` is NOT a comparator.
    confidence : float
        Family confidence level in ``(0, 1)`` (e.g. ``0.95``).
    n_replicates : int
        Number of bootstrap replicates (``>= 1``). The 10000-replicate
        scientific value is enforced by the config validator, not here.
    seed : int
        Base seed for deterministic per-replicate resampling (passed to the
        shared :func:`alive.eval.bootstrap._replicate_indices`).

    Returns
    -------
    ComposeSimultaneousBounds
        Frozen result with per-comparator point ``theta`` and simultaneous
        ``lower`` bounds, the common ``band_halfwidth`` ``q``, and a ``checksum``.
        Fixed ``seed`` and fixed inputs → byte-identical result and checksum.

    Raises
    ------
    ComposeInferenceError
        If the comparator family is empty, a comparator is missing from
        ``comparator_errors``, any array is not 1-D / has the wrong length / is
        empty, any error value is non-finite or negative, ``confidence`` is
        outside ``(0, 1)``, or ``n_replicates < 1``.
    """
    # ------------------------------------------------------------------
    # 1. Validation — fail closed BEFORE computing anything.
    # ------------------------------------------------------------------
    comparator_order = tuple(comparators)
    if len(comparator_order) == 0:
        raise ComposeInferenceError("comparators must be a non-empty sequence.")
    if not (0.0 < confidence < 1.0):
        raise ComposeInferenceError(f"confidence must be in (0, 1); got {confidence!r}.")
    if n_replicates < 1:
        raise ComposeInferenceError(f"n_replicates must be >= 1; got {n_replicates!r}.")

    missing = [c for c in comparator_order if c not in comparator_errors]
    if missing:
        raise ComposeInferenceError(
            f"comparator(s) {missing!r} missing from comparator_errors "
            f"(available: {sorted(comparator_errors)})."
        )

    headline = np.asarray(headline_errors, dtype=np.float64)
    if headline.ndim != 1:
        raise ComposeInferenceError(f"headline_errors must be 1-D; got ndim={headline.ndim}.")
    n = len(headline)
    if n == 0:
        raise ComposeInferenceError("headline_errors must be non-empty (n > 0).")
    headline = _validate_error_array(headline, n, "headline_errors")

    comp: dict[str, np.ndarray] = {}
    for c in comparator_order:
        comp[c] = _validate_error_array(comparator_errors[c], n, f"comparator_errors[{c!r}]")

    # ------------------------------------------------------------------
    # 2. Point theta on the full data.
    # ------------------------------------------------------------------
    mean_headline = float(np.mean(headline))
    theta: dict[str, float] = {
        c: _theta(mean_headline, float(np.mean(comp[c]))) for c in comparator_order
    }

    # ------------------------------------------------------------------
    # 3. Shared-resample bootstrap — SAME idx for headline and EVERY comparator.
    # ------------------------------------------------------------------
    max_dev = np.empty(n_replicates, dtype=np.float64)
    for b in range(n_replicates):
        idx = _replicate_indices(seed, b, n)
        mean_headline_b = float(np.mean(headline[idx]))
        dev = np.empty(len(comparator_order), dtype=np.float64)
        for j, c in enumerate(comparator_order):
            theta_c_b = _theta(mean_headline_b, float(np.mean(comp[c][idx])))
            dev[j] = theta[c] - theta_c_b
        max_dev[b] = float(np.max(dev))

    # ------------------------------------------------------------------
    # 4. Common quantile q and the one-sided simultaneous lower bounds.
    # ------------------------------------------------------------------
    q = float(np.quantile(max_dev, confidence, method="linear"))
    lower: dict[str, float] = {c: theta[c] - q for c in comparator_order}

    return ComposeSimultaneousBounds(
        comparators=comparator_order,
        theta=theta,
        lower=lower,
        band_halfwidth=q,
        confidence=float(confidence),
        n_replicates=int(n_replicates),
        seed=int(seed),
    )


# ---------------------------------------------------------------------------
# Band-inflation sensitivity (decision 2026-08-29, pair dependence)
# ---------------------------------------------------------------------------
# `docs/superpowers/2026-08-29-compose-pair-dependence-decision.md` settles that
# the simultaneous coverage claim is CONDITIONAL on the registered pair-i.i.d.
# resampling unit, because the headline structure violates that assumption by
# construction: 22 pairs drawn from 21 genes, with not one pair gene-disjoint from
# all the others, and only two connected components (19 and 3) so no cluster
# resample is available.
#
# The decision does NOT change the estimator or any threshold. The verdict is
# decided at lambda = 1.0 -- the registered band -- exactly as spec 10.5 says.
# Alongside it the bounds are re-reported at each registered lambda so the report
# states WHERE the verdict flips instead of asserting that it does not. This is
# descriptive-only and can never be a verdict gate.
#
# The ladder is anchored, not guessed: sweeping lambda over the same simulated
# trials, the minimum inflation restoring nominal coverage measured 1.0 / 1.10 /
# 1.15 / 1.10 across the sigma ladder, worst case interior at 1.15.


@dataclass(frozen=True)
class ComposeBandSensitivity:
    """Descriptive-only band-inflation sensitivity for one regime's bounds.

    Parameters
    ----------
    comparators : tuple of str
        The exact ordered comparator family the bounds were computed on.
    band_inflation : tuple of float
        The registered ladder (``config.sensitivity_band_inflation``). Its first
        entry is ``1.0`` -- the registered band, and the only one the verdict is
        decided on.
    lower_by_lambda : dict
        ``lambda -> {comparator: theta_C - lambda * q}``.
    flip_lambda : dict
        ``comparator -> the exact lambda at which that comparator's clause stops
        holding``, i.e. where ``theta_C - lambda * q`` reaches its registered
        threshold. Closed form ``(theta_C - threshold) / q``; no search. A value
        at or below ``1.0`` means the clause does not hold at the registered band
        either. A zero-width band is not moved by any inflation, so its clause
        keeps its lambda = 1 state everywhere: ``inf`` when it holds, ``-inf``
        when it already fails (the strict clause fails at ``theta_C`` exactly on
        the threshold too).
    verdict_holds_below_lambda : float
        ``min(flip_lambda)`` -- the inflation at which the first clause fails, so
        the whole conjunction stops holding.
    """

    comparators: tuple[str, ...]
    band_inflation: tuple[float, ...]
    lower_by_lambda: dict[float, dict[str, float]]
    flip_lambda: dict[str, float]
    verdict_holds_below_lambda: float

    @cached_property
    def checksum(self) -> str:
        """SHA-256 over the canonical content, floats via ``repr()`` as elsewhere."""
        canonical = {
            "comparators": list(self.comparators),
            "band_inflation": [repr(x) for x in self.band_inflation],
            "lower_by_lambda": [
                [repr(lam), [repr(self.lower_by_lambda[lam][c]) for c in self.comparators]]
                for lam in self.band_inflation
            ],
            "flip_lambda": [repr(self.flip_lambda[c]) for c in self.comparators],
            "verdict_holds_below_lambda": repr(self.verdict_holds_below_lambda),
        }
        return sha256_json(canonical)


def inflate_bounds(bounds: ComposeSimultaneousBounds, factor: float) -> ComposeSimultaneousBounds:
    """Return the same bounds with the shared band multiplied by ``factor``.

    ``theta`` is untouched -- inflation widens the band, it never moves the point
    estimate. The result is shaped exactly like the input so it can be handed to
    :func:`alive.compose.verdict2.sealed_verdict` unchanged.

    Raises
    ------
    ComposeInferenceError
        If ``factor`` is not finite or is below 1.0 (a factor under 1 would
        NARROW the registered band, which is the one thing this must never do).
    """
    f = float(factor)
    if not math.isfinite(f) or f < 1.0:
        raise ComposeInferenceError(
            f"band inflation factor must be finite and >= 1.0; got {factor!r}. "
            "A factor below 1 would narrow the registered band."
        )
    q = float(bounds.band_halfwidth) * f
    return dataclasses.replace(
        bounds,
        lower={c: float(bounds.theta[c]) - q for c in bounds.comparators},
        band_halfwidth=q,
    )


def band_sensitivity(
    *,
    bounds: ComposeSimultaneousBounds,
    band_inflation: Sequence[float],
    additive_margin: float,
    learned_margin: float,
) -> ComposeBandSensitivity:
    """Re-report the bounds at each registered inflation and locate the flip point.

    Parameters
    ----------
    bounds : ComposeSimultaneousBounds
        The registered bounds, as computed by :func:`simultaneous_theta_bounds`.
    band_inflation : sequence of float
        ``config.sensitivity_band_inflation``. Must be non-empty, start at exactly
        ``1.0``, be strictly increasing, and hold only finite values ``>= 1.0``.
    additive_margin : float
        The registered material margin the ``additive`` contrast must clear.
    learned_margin : float
        The registered margin every learned comparator must clear.

    Returns
    -------
    ComposeBandSensitivity

    Raises
    ------
    ComposeInferenceError
        If the ladder is malformed, or ``additive`` is absent from the roster.
    """
    ladder = tuple(float(x) for x in band_inflation)
    if not ladder:
        raise ComposeInferenceError("band_inflation must be non-empty.")
    if ladder[0] != 1.0:
        raise ComposeInferenceError(
            f"band_inflation must start at the registered band 1.0; got {ladder[0]!r}. "
            "The verdict is decided there, so it cannot be absent from the report."
        )
    if any(not math.isfinite(x) or x < 1.0 for x in ladder):
        raise ComposeInferenceError(
            f"band_inflation entries must be finite and >= 1.0; got {list(ladder)}"
        )
    if any(b <= a for a, b in zip(ladder, ladder[1:], strict=False)):
        raise ComposeInferenceError(
            f"band_inflation must be strictly increasing; got {list(ladder)}"
        )
    if "additive" not in bounds.comparators:
        raise ComposeInferenceError(
            "band_sensitivity requires 'additive' in the comparator roster; "
            f"got {list(bounds.comparators)}"
        )

    lower_by_lambda = {lam: dict(inflate_bounds(bounds, lam).lower) for lam in ladder}

    q = float(bounds.band_halfwidth)
    flip: dict[str, float] = {}
    for c in bounds.comparators:
        threshold = float(additive_margin) if c == "additive" else float(learned_margin)
        margin_above_threshold = float(bounds.theta[c]) - threshold
        # theta_C - lambda*q == threshold  =>  lambda = (theta_C - threshold)/q.
        # A zero-width band is not moved by any inflation, so the clause keeps
        # its lambda = 1 state at every lambda: inf when it holds, -inf (the
        # documented at-or-below-1.0 encoding) when it already fails. The
        # verdict clause is strict, so a margin of exactly zero fails too.
        if q == 0.0:
            flip[c] = math.inf if margin_above_threshold > 0.0 else -math.inf
        else:
            flip[c] = margin_above_threshold / q

    return ComposeBandSensitivity(
        comparators=tuple(bounds.comparators),
        band_inflation=ladder,
        lower_by_lambda=lower_by_lambda,
        flip_lambda=flip,
        verdict_holds_below_lambda=min(flip.values()),
    )
