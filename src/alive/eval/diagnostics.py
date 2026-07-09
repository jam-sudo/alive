"""Read-only post-hoc diagnostics over the CARTOGRAPHER *development* OOF surface.

This module answers "why did the Trust-Gate not beat its comparator family?"
*without* touching the sealed cohort.  It operates exclusively on the
out-of-fold (OOF) scores and realised per-perturbation errors persisted by the
``develop`` stage (``methodlock.json`` + ``dev_errors.npz``) — the same surface
model/method selection was based on, which is **not** sealed under the
``TG-K562-v1`` seal contract (CLAUDE.md#seal).  Nothing here re-opens or
slices the sealed evaluation; the registered verdict is immutable.

Sign conventions (matching :mod:`alive.metrics.selective`)
----------------------------------------------------------
- ``error``: realised per-perturbation risk (energy distance, ≥0).  Higher =
  the base predictor was more wrong on that perturbation.
- ``score``: a method's UQ score where **higher = less trustworthy** (expected
  larger error).  A *good* score is therefore **positively** rank-correlated
  with ``error`` (and yields a *lower* AURC).

The "added value" question
--------------------------
The registered ``added_value`` clause asks whether the gate's feature-distance
component (R1, standalone comparator ``nearest_feature``) ranks error *beyond*
the local-residual component (R4, standalone comparator ``residual_only``).
:func:`partial_spearman` is the primitive: a partial rank correlation of the
feature score with error, *controlling for* the residual score.  ≈0 means R1
carries no error-ranking signal R4 does not already provide.

Public API
----------
DiagnosticsError
    Raised for invalid inputs.
spearman_corr(x, y)
    Spearman rank correlation; constant input -> 0.0 (never NaN).
partial_spearman(x, y, given)
    Partial Spearman correlation of x and y controlling for ``given``.
rank_overconfidence(ids, errors, score, ...)
    Perturbations with high realised error but a low (trusted) score.
diagnose_oof(dev_ids, errors, oof_scores, ...)
    Structured per-method + added-value + overconfidence summary.
load_oof_table(run_dir)
    Load ``(ids, errors, oof_scores)`` from a develop-stage run directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import rankdata

from alive.metrics.selective import MetricError, aurc, normalize_by_mean

__all__ = [
    "DiagnosticsError",
    "spearman_corr",
    "partial_spearman",
    "rank_overconfidence",
    "diagnose_oof",
    "load_oof_table",
]


class DiagnosticsError(ValueError):
    """Raised when inputs to the OOF diagnostics are invalid."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _as_finite_vector(name: str, arr: np.ndarray) -> np.ndarray:
    """Coerce to 1-D float64 and require all-finite."""
    out = np.asarray(arr, dtype=np.float64)
    if out.ndim != 1:
        raise DiagnosticsError(f"{name} must be 1-D, got shape {out.shape}.")
    if not np.all(np.isfinite(out)):
        raise DiagnosticsError(f"{name} contains non-finite values.")
    return out


def _check_pair(x: np.ndarray, y: np.ndarray, *, min_n: int) -> tuple[np.ndarray, np.ndarray]:
    x = _as_finite_vector("x", x)
    y = _as_finite_vector("y", y)
    if x.shape != y.shape:
        raise DiagnosticsError(f"length mismatch: {x.shape} vs {y.shape}.")
    if len(x) < min_n:
        raise DiagnosticsError(f"need at least {min_n} rows, got {len(x)}.")
    return x, y


# ---------------------------------------------------------------------------
# Rank-correlation primitives
# ---------------------------------------------------------------------------


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation; zero-variance input -> 0.0 (no information)."""
    a = a - a.mean()
    b = b - b.mean()
    da = float(np.sqrt(np.dot(a, a)))
    db = float(np.sqrt(np.dot(b, b)))
    if da == 0.0 or db == 0.0:
        return 0.0
    return float(np.dot(a, b) / (da * db))


def _residualise(a: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Residuals of ``a`` after an ordinary least-squares fit on ``[1, z]``."""
    design = np.column_stack([np.ones_like(z), z])
    coef, *_ = np.linalg.lstsq(design, a, rcond=None)
    return a - design @ coef


def _centred_norm(a: np.ndarray) -> float:
    """L2 norm of ``a`` after mean removal."""
    a0 = a - a.mean()
    return float(np.sqrt(np.dot(a0, a0)))


def spearman_corr(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rank correlation between ``x`` and ``y``.

    Ties receive average ranks.  A constant input (zero rank variance) yields
    ``0.0`` rather than NaN, so a degenerate score reads as "no ranking
    information" instead of poisoning downstream aggregates.

    Parameters
    ----------
    x, y : np.ndarray
        1-D, equal-length, finite.

    Returns
    -------
    float
        Correlation in ``[-1, 1]``.

    Raises
    ------
    DiagnosticsError
        On shape mismatch, non-finite values, or fewer than 2 rows.
    """
    x, y = _check_pair(x, y, min_n=2)
    return _pearson(rankdata(x), rankdata(y))


def partial_spearman(x: np.ndarray, y: np.ndarray, given: np.ndarray) -> float:
    """Partial Spearman correlation of ``x`` and ``y`` controlling for ``given``.

    Computed by rank-transforming all three vectors, regressing the ranks of
    ``x`` and ``y`` on the ranks of ``given`` (with intercept), and taking the
    Pearson correlation of the residuals.  If ``given`` linearly explains all
    rank variance of ``x`` or ``y`` (e.g. ``given`` is a monotone transform of
    one of them), the corresponding residual is ~0 and the result is ``0.0``.

    Parameters
    ----------
    x, y, given : np.ndarray
        1-D, equal-length, finite.

    Returns
    -------
    float
        Partial correlation in ``[-1, 1]``.  Symmetric in ``x`` and ``y``.

    Raises
    ------
    DiagnosticsError
        On shape mismatch, non-finite values, or fewer than 4 rows (the
        residualisation consumes 2 degrees of freedom).
    """
    x, y = _check_pair(x, y, min_n=4)
    _, given = _check_pair(x, given, min_n=4)
    rx, ry, rz = rankdata(x), rankdata(y), rankdata(given)
    res_x, res_y = _residualise(rx, rz), _residualise(ry, rz)
    # If ``given`` explains essentially all rank variance of x or y (e.g. it is
    # a monotone transform of one of them), the residual is numerical noise:
    # _pearson would then divide noise-by-noise and return a spurious value.
    # Guard with a relative tolerance against the original rank spread.
    tol = 1e-9
    if _centred_norm(res_x) <= tol * max(_centred_norm(rx), 1.0):
        return 0.0
    if _centred_norm(res_y) <= tol * max(_centred_norm(ry), 1.0):
        return 0.0
    return _pearson(res_x, res_y)


# ---------------------------------------------------------------------------
# Overconfidence
# ---------------------------------------------------------------------------


def rank_overconfidence(
    ids: tuple[str, ...] | list[str],
    errors: np.ndarray,
    score: np.ndarray,
    *,
    error_quantile: float = 0.8,
    score_quantile: float = 0.2,
) -> list[dict[str, Any]]:
    """Perturbations the gate trusted yet predicted poorly.

    Flags rows whose realised ``error`` is at or above ``error_quantile`` *and*
    whose ``score`` is at or below ``score_quantile`` (low score = trusted).
    These are the confident misses a better model must capture.

    Parameters
    ----------
    ids : sequence of str
        Perturbation identifiers, row-aligned with ``errors``/``score``.
    errors : np.ndarray
        Realised per-perturbation error.
    score : np.ndarray
        Gate score (higher = less trustworthy).
    error_quantile : float, optional
        Upper-tail error cut (default 0.8).
    score_quantile : float, optional
        Lower-tail score cut (default 0.2).

    Returns
    -------
    list[dict]
        One ``{"id", "error", "score"}`` dict per flagged perturbation, sorted
        by ``error`` descending.

    Raises
    ------
    DiagnosticsError
        On length mismatch, non-finite values, or quantiles outside ``[0, 1]``.
    """
    errors, score = _check_pair(errors, score, min_n=1)
    if len(ids) != len(errors):
        raise DiagnosticsError(f"ids length {len(ids)} != errors length {len(errors)}.")
    if not (0.0 <= error_quantile <= 1.0 and 0.0 <= score_quantile <= 1.0):
        raise DiagnosticsError("quantiles must lie in [0, 1].")

    err_cut = float(np.quantile(errors, error_quantile))
    score_cut = float(np.quantile(score, score_quantile))
    flagged = [
        {"id": str(ids[i]), "error": float(errors[i]), "score": float(score[i])}
        for i in range(len(errors))
        if errors[i] >= err_cut and score[i] <= score_cut
    ]
    flagged.sort(key=lambda row: row["error"], reverse=True)
    return flagged


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _safe_aurc(errors: np.ndarray, score: np.ndarray) -> float:
    """AURC on mean-normalised errors; comparable with the recorded oof_aurc."""
    try:
        return aurc(normalize_by_mean(errors), score)
    except MetricError as exc:  # pragma: no cover - errors are positive in practice
        raise DiagnosticsError(str(exc)) from exc


def diagnose_oof(
    dev_ids: tuple[str, ...] | list[str],
    errors: np.ndarray,
    oof_scores: dict[str, np.ndarray],
    *,
    feature_method: str = "nearest_feature",
    residual_method: str = "residual_only",
    gate_method: str = "gate",
    ensemble_method: str = "ensemble_disagreement",
    top_k_overconfident: int = 10,
) -> dict[str, Any]:
    """Summarise why the gate ranked error the way it did, on the OOF surface.

    Parameters
    ----------
    dev_ids : sequence of str
        Development perturbation identifiers, row-aligned with ``errors`` and
        every array in ``oof_scores``.
    errors : np.ndarray
        Realised per-perturbation error (energy distance, ≥0).
    oof_scores : dict[str, np.ndarray]
        ``{method_name -> per-perturbation OOF score}``.
    feature_method, residual_method, gate_method, ensemble_method : str
        Canonical method names for the R1 (feature), R4 (residual), combined
        gate, and ensemble-disagreement comparators.  Each must be a key of
        ``oof_scores``.
    top_k_overconfident : int, optional
        Number of confident-miss perturbations to return (default 10).

    Returns
    -------
    dict
        ``per_method`` (spearman + recomputed AURC per method), ``added_value``
        (feature-vs-residual partial correlations and redundancy), and
        ``overconfident`` (top confident misses for the gate).

    Raises
    ------
    DiagnosticsError
        On unknown method names, length mismatch, or non-finite inputs.
    """
    errors = _as_finite_vector("errors", errors)
    n = len(errors)
    if len(dev_ids) != n:
        raise DiagnosticsError(f"dev_ids length {len(dev_ids)} != errors length {n}.")
    if not oof_scores:
        raise DiagnosticsError("oof_scores is empty.")

    scores: dict[str, np.ndarray] = {}
    for name, arr in oof_scores.items():
        vec = _as_finite_vector(f"oof_scores[{name!r}]", arr)
        if len(vec) != n:
            raise DiagnosticsError(f"oof_scores[{name!r}] length {len(vec)} != errors length {n}.")
        scores[name] = vec

    for role, name in (
        ("feature_method", feature_method),
        ("residual_method", residual_method),
        ("gate_method", gate_method),
        ("ensemble_method", ensemble_method),
    ):
        if name not in scores:
            raise DiagnosticsError(
                f"{role}={name!r} not present in oof_scores keys {sorted(scores)}."
            )

    per_method = {
        name: {"spearman": spearman_corr(arr, errors), "aurc": _safe_aurc(errors, arr)}
        for name, arr in scores.items()
    }

    feat, resid = scores[feature_method], scores[residual_method]
    added_value = {
        "partial_feature_given_residual": partial_spearman(feat, errors, resid),
        "partial_residual_given_feature": partial_spearman(resid, errors, feat),
        "corr_feature_residual": spearman_corr(feat, resid),
    }

    overconfident = rank_overconfidence(dev_ids, errors, scores[gate_method])[:top_k_overconfident]

    return {
        "n": n,
        "methods": sorted(scores),
        "per_method": per_method,
        "added_value": added_value,
        "overconfident": overconfident,
    }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_oof_table(
    run_dir: str | Path,
) -> tuple[tuple[str, ...], np.ndarray, dict[str, np.ndarray]]:
    """Load ``(ids, errors, oof_scores)`` from a develop-stage run directory.

    Reads ``methodlock.json`` (``method_ids``, ``oof_scores``, ``dev_ids``) and
    ``dev_errors.npz`` (``ids``, ``errors``), and verifies the two ID orderings
    agree so downstream row alignment is sound.

    Parameters
    ----------
    run_dir : str or Path
        Per-run artifacts directory written by ``alive cartographer develop``.

    Returns
    -------
    tuple[tuple[str, ...], np.ndarray, dict[str, np.ndarray]]
        ``(ids, errors, oof_scores)`` all row-aligned.

    Raises
    ------
    DiagnosticsError
        If an artifact is missing, malformed, or the ID orderings disagree.
    """
    run_dir = Path(run_dir)
    ml_path = run_dir / "methodlock.json"
    npz_path = run_dir / "dev_errors.npz"
    if not ml_path.exists():
        raise DiagnosticsError(f"required artifact not found: {ml_path}")
    if not npz_path.exists():
        raise DiagnosticsError(f"required artifact not found: {npz_path}")

    try:
        ml = json.loads(ml_path.read_text())
        method_ids = list(ml["method_ids"])
        oof_scores = {m: np.asarray(ml["oof_scores"][m], dtype=np.float64) for m in method_ids}
        dev_ids = tuple(str(x) for x in ml["dev_ids"])
    except (KeyError, ValueError, TypeError) as exc:
        raise DiagnosticsError(f"malformed methodlock.json: {exc}") from exc

    npz = np.load(npz_path, allow_pickle=False)
    ids = tuple(str(x) for x in npz["ids"])
    errors = np.asarray(npz["errors"], dtype=np.float64)

    if ids != dev_ids:
        raise DiagnosticsError(
            "dev_errors.npz ids do not match methodlock dev_ids ordering; "
            "row alignment cannot be guaranteed."
        )
    return ids, errors, oof_scores
