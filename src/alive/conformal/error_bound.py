"""Split-conformal calibration layer: scalar error bound, PREDICT threshold, coverage band.

This module is the calibration layer of the CARTOGRAPHER Trust-Gate MVP and the
primary *shippable* deliverable: it is produced even when the run is
futility-stopped.  It is **pure statistics** on arrays that the caller (Task 16)
computes — it never reads the sealed store, fits the gate, or computes energy
distances.

The error axis is always an *observed* error (a quantity measured against ground
truth), never a model-predicted quantity.

Public API
----------
conformal_error_bound(calibration_errors, alpha)
    Finite-sample split-conformal scalar bound (k-th order statistic).
conformal_rank(n_cal, alpha)
    The 1-indexed order-statistic rank ``k = min(ceil((n_cal+1)(1-alpha)), n_cal)``.
predict_threshold(calibration_gate_scores, target_selection_coverage)
    PREDICT threshold from calibration GATE SCORES (lower score = PREDICT).
coverage_report(test_errors, test_gate_scores, *, error_bound, threshold)
    Five-metric coverage report on a (sealed) evaluation set.
betabinom_acceptance_band(n_cal, alpha, n_test, *, central=0.99)
    EXACT split-conformal beta-binomial predictive acceptance band.
conformal_coverage_passes(n_covered, n_cal, alpha, n_test, *, central=0.99)
    Whether an observed covered-count falls inside the acceptance band.
ConformalArtifact / build_conformal_artifact(...)
    The bundled, checksummed, round-trippable scalar conformal artifact.

Theory: finite-sample split conformal
-------------------------------------
With ``n_cal`` exchangeable calibration errors and a fresh exchangeable test
point, the *marginal* coverage guarantee
``P(error_test <= bound) >= 1 - alpha`` holds when ``bound`` is the
``k``-th smallest calibration error with::

    k = ceil((n_cal + 1) * (1 - alpha))

clipped to ``n_cal`` (you cannot ask for an order statistic beyond the sample;
when ``k > n_cal`` the bound is the calibration maximum).  Order statistics are
**1-indexed** in this formula, so the value is ``sorted(errors)[k - 1]`` — i.e.
``index = min(k, n_cal) - 1`` into the sorted array.

Theory: exact beta-binomial predictive band
--------------------------------------------
Because the bound is the ``k``-th order statistic of a *random* calibration set,
the coverage of a future point *conditional on the calibration set* is itself
random and ``Beta(k, n_cal + 1 - k)``-distributed (the classic distribution-free
order-statistic rank result for continuous error distributions).  Marginalising
over that Beta coverage, the number of covered points among ``n_test``
exchangeable test points follows ``BetaBinomial(n_test, a=k, b=n_cal+1-k)``.
The acceptance band is the central ``central`` interval of that beta-binomial;
an observed covered-count outside the band signals a calibration failure.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np
from scipy.stats import betabinom

from alive.provenance import sha256_json

# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ConformalError(ValueError):
    """Raised on invalid inputs to the conformal calibration layer.

    Covers empty arrays, out-of-range ``alpha`` / coverage / ``central`` levels,
    non-1-D or NaN-containing inputs, length mismatches, and a checksum mismatch
    when reading a :class:`ConformalArtifact` from disk.

    Parameters
    ----------
    message : str
        Human-readable description of the violation.
    """


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------


def _as_1d_finite(values: object, name: str) -> np.ndarray:
    """Coerce *values* to a 1-D float array, validating non-empty and finite.

    Parameters
    ----------
    values : object
        Array-like sequence of scalars.
    name : str
        Field name used in error messages.

    Returns
    -------
    numpy.ndarray
        A new 1-D ``float64`` array (a copy; the caller's data is never sorted
        in place).

    Raises
    ------
    ConformalError
        If *values* is not 1-D, is empty, or contains non-finite entries.
    """
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1:
        raise ConformalError(f"{name} must be a 1-D array; got shape {arr.shape}.")
    if arr.size == 0:
        raise ConformalError(f"{name} must be non-empty; got an empty array.")
    if not np.all(np.isfinite(arr)):
        raise ConformalError(f"{name} must contain only finite values (no NaN/Inf).")
    return arr


def _validate_open_unit(name: str, value: float) -> None:
    """Raise :class:`ConformalError` unless *value* is in the open interval (0, 1).

    Parameters
    ----------
    name : str
        Field name for the error message.
    value : float
        The value to check (NaN fails).
    """
    if not (math.isfinite(value) and 0.0 < value < 1.0):
        raise ConformalError(f"{name} must be in the open interval (0, 1); got {value!r}.")


# ---------------------------------------------------------------------------
# Finite-sample split-conformal scalar bound
# ---------------------------------------------------------------------------


def conformal_rank(n_cal: int, alpha: float) -> int:
    """Return the 1-indexed order-statistic rank used by the conformal bound.

    Computes ``k = min(ceil((n_cal + 1) * (1 - alpha)), n_cal)``.  This is the
    1-indexed position of the order statistic whose value is the conformal
    scalar bound; the corresponding array index is ``k - 1``.

    Parameters
    ----------
    n_cal : int
        Number of calibration points (must be >= 1).
    alpha : float
        Target miscoverage level in the open interval (0, 1).

    Returns
    -------
    int
        The clipped 1-indexed rank ``k`` (1 <= k <= n_cal).

    Raises
    ------
    ConformalError
        If ``n_cal < 1`` or ``alpha`` is not in (0, 1).
    """
    if n_cal < 1:
        raise ConformalError(f"n_cal must be >= 1; got {n_cal!r}.")
    _validate_open_unit("alpha", alpha)
    k = math.ceil((n_cal + 1) * (1.0 - alpha))
    return min(k, n_cal)


def conformal_error_bound(calibration_errors: np.ndarray, alpha: float) -> float:
    """Finite-sample split-conformal scalar error bound.

    Computes the ``k``-th smallest calibration error, where
    ``k = ceil((n_cal + 1) * (1 - alpha))`` clipped to ``n_cal``.  The returned
    value is a scalar ``error_bound`` (NOT a prediction set): a future
    exchangeable test point satisfies ``error_test <= error_bound`` with
    marginal probability at least ``1 - alpha``.

    Notes
    -----
    Off-by-one: order statistics are **1-indexed** in the formula, so the value
    is taken at array index ``min(k, n_cal) - 1`` of the sorted errors.  When
    ``k`` clips to ``n_cal`` the bound is the calibration maximum.

    Parameters
    ----------
    calibration_errors : numpy.ndarray
        1-D array of OBSERVED base errors on the conformal-calibration split.
        Not modified (sorting is done on a copy).
    alpha : float
        Target miscoverage level in (0, 1).

    Returns
    -------
    float
        The scalar conformal error bound.

    Raises
    ------
    ConformalError
        On empty / non-1-D / non-finite input, or ``alpha`` not in (0, 1).
    """
    errors = _as_1d_finite(calibration_errors, "calibration_errors")
    n_cal = errors.size
    k = conformal_rank(n_cal, alpha)
    ordered = np.sort(errors)
    return float(ordered[k - 1])


# ---------------------------------------------------------------------------
# PREDICT threshold (from calibration GATE SCORES, not errors)
# ---------------------------------------------------------------------------


def predict_threshold(
    calibration_gate_scores: np.ndarray, target_selection_coverage: float
) -> float:
    """PREDICT threshold from calibration GATE SCORES (lower score = PREDICT).

    The threshold is the ``target_selection_coverage`` quantile of the
    calibration gate scores.  An item with ``gate_score <= threshold`` is
    PREDICT (the gate trusts it); higher scores abstain.

    Uses :func:`numpy.quantile` with ``method="lower"`` for determinism and so
    that on the calibration set the selected fraction is at least
    ``target_selection_coverage`` (the lower-quantile value is an actual data
    point, so ``score <= threshold`` selects no fewer than the target fraction).

    EVALUATION errors must never enter this computation — the signature
    intentionally has no errors argument; only calibration gate scores are used.

    Parameters
    ----------
    calibration_gate_scores : numpy.ndarray
        1-D array of the fitted gate's scores on calibration perturbations
        (higher = abstain).  Not modified.
    target_selection_coverage : float
        Desired fraction of items to PREDICT, in the half-open interval (0, 1].

    Returns
    -------
    float
        The gate-score threshold; items with score <= it are PREDICT.

    Raises
    ------
    ConformalError
        On empty / non-1-D / non-finite input, or
        ``target_selection_coverage`` not in (0, 1].
    """
    scores = _as_1d_finite(calibration_gate_scores, "calibration_gate_scores")
    if not (math.isfinite(target_selection_coverage) and 0.0 < target_selection_coverage <= 1.0):
        raise ConformalError(
            "target_selection_coverage must be in the half-open interval (0, 1]; "
            f"got {target_selection_coverage!r}."
        )
    return float(np.quantile(scores, target_selection_coverage, method="lower"))


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------


def coverage_report(
    test_errors: np.ndarray,
    test_gate_scores: np.ndarray,
    *,
    error_bound: float,
    threshold: float,
) -> dict:
    """Five-metric conformal coverage report on a (sealed) evaluation set.

    Both ``<=`` comparisons are inclusive (equality counts as covered /
    selected).

    Definitions::

        selected = test_gate_scores <= threshold      # the PREDICT set
        within   = test_errors      <= error_bound    # bound holds

    Parameters
    ----------
    test_errors : numpy.ndarray
        1-D array of OBSERVED errors on the evaluation set.
    test_gate_scores : numpy.ndarray
        1-D array of gate scores on the evaluation set (same length).
    error_bound : float
        The scalar conformal bound from :func:`conformal_error_bound`.
    threshold : float
        The PREDICT threshold from :func:`predict_threshold`.

    Returns
    -------
    dict
        ``marginal_error_bound_coverage`` : mean(within) over all points.
        ``selective_error_bound_coverage`` : mean(within[selected]); NaN if
            nothing is selected.
        ``selection_coverage`` : mean(selected) (the realized PREDICT fraction).
        ``effective_covered_fraction`` : mean(selected & within).
        ``abstain_rate`` : ``1 - selection_coverage``.
        ``n_selected`` : int count of selected points.
        ``n_total`` : int total number of evaluation points.

    Raises
    ------
    ConformalError
        On empty input or a length mismatch between the two arrays.

    Notes
    -----
    Selection by gate score is **not** independent of the error, so the
    selective coverage on test can differ from the marginal coverage and from
    the nominal ``1 - alpha`` — this is expected and is exactly what the report
    surfaces.
    """
    errors = _as_1d_finite(test_errors, "test_errors")
    scores = _as_1d_finite(test_gate_scores, "test_gate_scores")
    if errors.size != scores.size:
        raise ConformalError(
            f"test_errors and test_gate_scores must have equal length; "
            f"got {errors.size} and {scores.size}."
        )

    selected = scores <= threshold
    within = errors <= error_bound
    n_total = int(errors.size)
    n_selected = int(np.count_nonzero(selected))

    if n_selected == 0:
        selective = float("nan")
    else:
        selective = float(np.mean(within[selected]))

    selection_coverage = float(np.mean(selected))
    return {
        "marginal_error_bound_coverage": float(np.mean(within)),
        "selective_error_bound_coverage": selective,
        "selection_coverage": selection_coverage,
        "effective_covered_fraction": float(np.mean(selected & within)),
        "abstain_rate": 1.0 - selection_coverage,
        "n_selected": n_selected,
        "n_total": n_total,
    }


# ---------------------------------------------------------------------------
# EXACT split-conformal beta-binomial acceptance band
# ---------------------------------------------------------------------------


def betabinom_acceptance_band(
    n_cal: int, alpha: float, n_test: int, *, central: float = 0.99
) -> tuple[int, int]:
    """EXACT split-conformal beta-binomial predictive acceptance band.

    The conformal bound is the ``k``-th order statistic of a *random*
    calibration set, so the per-future-point coverage is
    ``Beta(k, n_cal + 1 - k)`` and the covered-count among ``n_test``
    exchangeable test points is ``BetaBinomial(n_test, a=k, b=n_cal+1-k)`` with
    ``k = conformal_rank(n_cal, alpha)``.  This returns the central ``central``
    interval ``[low, high]`` (inclusive integer counts) of that distribution.

    Discrete-ppf convention
    -----------------------
    For a discrete distribution ``ppf(p)`` returns the smallest ``x`` with
    ``cdf(x) >= p``.  To guarantee the band carries **at least** ``central``
    central mass with each tail bounded by ``(1 - central) / 2``, we set::

        tail = (1 - central) / 2
        low  = smallest x with P(X < x)  <= tail   (i.e. cdf(low - 1)  <= tail)
        high = smallest x with P(X <= x) >= 1 - tail (i.e. cdf(high)   >= 1 - tail)

    ``high`` is exactly ``ppf(1 - tail)``.  ``low`` is computed as
    ``ppf(tail)`` and then *decremented* while ``cdf(low - 1) <= tail`` would be
    violated — i.e. we take the largest ``low`` whose lower tail
    ``cdf(low - 1)`` does not exceed ``tail`` (equivalently the smallest ``x``
    with ``cdf(x) > tail``).  Together these give
    ``P(low <= X <= high) = cdf(high) - cdf(low - 1) >= central``.

    Parameters
    ----------
    n_cal : int
        Number of calibration points (>= 1).
    alpha : float
        Conformal miscoverage level in (0, 1).
    n_test : int
        Number of exchangeable evaluation points (>= 1).
    central : float, optional
        Central mass to enclose, in (0, 1).  Defaults to ``0.99``.

    Returns
    -------
    tuple[int, int]
        ``(low, high)`` inclusive integer covered-count bounds with
        ``0 <= low <= high <= n_test``.

    Raises
    ------
    ConformalError
        If ``n_cal < 1``, ``n_test < 1``, ``alpha`` not in (0, 1), or
        ``central`` not in (0, 1).
    """
    if n_test < 1:
        raise ConformalError(f"n_test must be >= 1; got {n_test!r}.")
    _validate_open_unit("central", central)
    # conformal_rank validates n_cal and alpha.
    k = conformal_rank(n_cal, alpha)
    a, b = k, n_cal + 1 - k
    dist = betabinom(n_test, a, b)
    tail = (1.0 - central) / 2.0

    # high: smallest x with cdf(x) >= 1 - tail  (upper tail P(X > high) <= tail)
    high = int(dist.ppf(1.0 - tail))
    high = max(0, min(high, n_test))

    # low: smallest x with cdf(x) > tail, i.e. the largest x for which the lower
    # tail P(X < low) = cdf(low - 1) <= tail. ``ppf(tail)`` returns the smallest
    # x with cdf(x) >= tail; that satisfies cdf(low - 1) <= tail unless mass sits
    # exactly at the tail boundary (cdf(low) == tail), in which case we step up
    # so the strict lower-tail bound still holds.
    low = int(dist.ppf(tail))
    low = max(0, min(low, n_test))
    while low < high and dist.cdf(low) <= tail:
        low += 1

    return low, high


def conformal_coverage_passes(
    n_covered: int, n_cal: int, alpha: float, n_test: int, *, central: float = 0.99
) -> bool:
    """Whether an observed covered-count falls inside the acceptance band.

    Parameters
    ----------
    n_covered : int
        Observed number of evaluation points whose error is within the bound.
    n_cal : int
        Number of calibration points.
    alpha : float
        Conformal miscoverage level in (0, 1).
    n_test : int
        Number of evaluation points.
    central : float, optional
        Central mass for the band.  Defaults to ``0.99``.

    Returns
    -------
    bool
        ``True`` iff ``low <= n_covered <= high`` from
        :func:`betabinom_acceptance_band`.  A miss signals a calibration
        failure for the runner (Task 15/16) to emit ``CALIBRATION_FAILURE``.
    """
    low, high = betabinom_acceptance_band(n_cal, alpha, n_test, central=central)
    return low <= n_covered <= high


# ---------------------------------------------------------------------------
# Bundled shippable artifact
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConformalArtifact:
    """The bundled, checksummed scalar conformal calibration artifact.

    This is the primary shippable deliverable of the calibration layer.  It
    carries the scalar conformal bound, the order-statistic rank, the PREDICT
    threshold, and the provenance needed to reconstruct/verify them — but never
    any sealed evaluation data.

    Parameters
    ----------
    error_bound : float
        Scalar split-conformal error bound on the calibration split.
    rank_k : int
        1-indexed order-statistic rank used for the bound.
    n_cal : int
        Number of calibration points the bound was computed from.
    alpha : float
        Conformal miscoverage level.
    predict_threshold : float
        Gate-score threshold; items with score <= it are PREDICT.
    target_selection_coverage : float
        Target PREDICT fraction used to derive ``predict_threshold``.
    config_sha256 : str
        SHA-256 of the locked config that governed this run.
    """

    error_bound: float
    rank_k: int
    n_cal: int
    alpha: float
    predict_threshold: float
    target_selection_coverage: float
    config_sha256: str

    @cached_property
    def checksum(self) -> str:
        """SHA-256 hex digest of the canonical content of this artifact.

        Floats are serialised via :func:`repr` for stable, lossless formatting
        so two artifacts built from identical inputs have identical checksums.

        Returns
        -------
        str
            64-character lowercase hexadecimal SHA-256 digest.
        """
        canonical = {
            "error_bound": repr(self.error_bound),
            "rank_k": self.rank_k,
            "n_cal": self.n_cal,
            "alpha": repr(self.alpha),
            "predict_threshold": repr(self.predict_threshold),
            "target_selection_coverage": repr(self.target_selection_coverage),
            "config_sha256": self.config_sha256,
        }
        return sha256_json(canonical)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict including the checksum.

        Returns
        -------
        dict
            All artifact fields plus the pre-computed ``checksum``.
        """
        return {
            "error_bound": self.error_bound,
            "rank_k": self.rank_k,
            "n_cal": self.n_cal,
            "alpha": self.alpha,
            "predict_threshold": self.predict_threshold,
            "target_selection_coverage": self.target_selection_coverage,
            "config_sha256": self.config_sha256,
            "checksum": self.checksum,
        }

    def write(self, path: str | Path) -> None:
        """Write the artifact to *path* as canonical JSON.

        Parameters
        ----------
        path : str or Path
            Destination file path; the parent directory must already exist.
        """
        text = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        Path(path).write_text(text, encoding="utf-8")

    @classmethod
    def read(cls, path: str | Path) -> "ConformalArtifact":
        """Deserialise and checksum-verify a :class:`ConformalArtifact`.

        Parameters
        ----------
        path : str or Path
            Path to a JSON file produced by :meth:`write`.

        Returns
        -------
        ConformalArtifact
            The reconstructed artifact.

        Raises
        ------
        ConformalError
            If the file is malformed, missing fields, or its recomputed checksum
            does not match the stored value (tamper detection).
        """
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            raise ConformalError(f"Failed to read conformal artifact from {path!r}: {exc}") from exc

        try:
            stored_checksum: str = raw["checksum"]
            artifact = cls(
                error_bound=float(raw["error_bound"]),
                rank_k=int(raw["rank_k"]),
                n_cal=int(raw["n_cal"]),
                alpha=float(raw["alpha"]),
                predict_threshold=float(raw["predict_threshold"]),
                target_selection_coverage=float(raw["target_selection_coverage"]),
                config_sha256=raw["config_sha256"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConformalError(
                f"Conformal artifact JSON is missing/invalid field: {exc}"
            ) from exc

        if artifact.checksum != stored_checksum:
            raise ConformalError(
                f"Conformal artifact checksum mismatch: stored {stored_checksum!r} "
                f"!= recomputed {artifact.checksum!r}. The file may have been modified."
            )
        return artifact


def build_conformal_artifact(
    calibration_errors: np.ndarray,
    calibration_gate_scores: np.ndarray,
    *,
    alpha: float,
    target_selection_coverage: float,
    config_sha256: str,
) -> ConformalArtifact:
    """Build the bundled :class:`ConformalArtifact` from calibration arrays.

    Computes the scalar conformal bound and order-statistic rank from
    ``calibration_errors`` and the PREDICT threshold from
    ``calibration_gate_scores``.  Sealed evaluation data is never an input.

    Parameters
    ----------
    calibration_errors : numpy.ndarray
        1-D OBSERVED base errors on the conformal-calibration split.
    calibration_gate_scores : numpy.ndarray
        1-D fitted-gate scores on calibration perturbations (same length).
    alpha : float
        Conformal miscoverage level in (0, 1).
    target_selection_coverage : float
        Target PREDICT fraction in (0, 1].
    config_sha256 : str
        SHA-256 of the locked config for provenance.

    Returns
    -------
    ConformalArtifact
        The bundled scalar conformal artifact.

    Raises
    ------
    ConformalError
        On invalid arrays, a length mismatch, or out-of-range parameters.
    """
    errors = _as_1d_finite(calibration_errors, "calibration_errors")
    scores = _as_1d_finite(calibration_gate_scores, "calibration_gate_scores")
    if errors.size != scores.size:
        raise ConformalError(
            f"calibration_errors and calibration_gate_scores must have equal length; "
            f"got {errors.size} and {scores.size}."
        )
    n_cal = errors.size
    rank_k = conformal_rank(n_cal, alpha)
    bound = conformal_error_bound(errors, alpha)
    threshold = predict_threshold(scores, target_selection_coverage)
    return ConformalArtifact(
        error_bound=bound,
        rank_k=rank_k,
        n_cal=n_cal,
        alpha=alpha,
        predict_threshold=threshold,
        target_selection_coverage=target_selection_coverage,
        config_sha256=config_sha256,
    )
