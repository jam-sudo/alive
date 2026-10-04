"""Primitives for the CART-K562-D8-v1 draft protocol (not registered; no outcome access).

Target-level role split, the noise-analytic trust baseline (B1) and the batch-matched
control reference. Values such as tau, epsilon, fractions and seeds are supplied by the
caller from the registered protocol; nothing here is a default scientific threshold.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np

_ROLES = ("D", "C", "E")


def split_roles(
    targets: Sequence[str],
    strata: Mapping[str, str],
    *,
    fractions: tuple[float, float],
    seed: int,
) -> dict[str, list[str]]:
    """Seeded, stratified target-level split into development/calibration/evaluation.

    Parameters
    ----------
    targets : sequence of str
        Unique claim-unit targets.
    strata : mapping
        Outcome-independent stratum label per target.
    fractions : tuple of float
        (D, C) fractions; E receives the remainder. Floor cuts per stratum.
    seed : int
        Registered seed.

    Returns
    -------
    dict
        Sorted target lists for ``D``, ``C`` and ``E``.
    """
    if len(set(targets)) != len(targets):
        raise ValueError("targets must be unique")
    rng = np.random.default_rng(seed)
    roles: dict[str, list[str]] = {r: [] for r in _ROLES}
    for stratum in sorted({strata[t] for t in targets}):
        members = sorted(t for t in targets if strata[t] == stratum)
        members = [members[i] for i in rng.permutation(len(members))]
        a = math.floor(fractions[0] * len(members))
        b = a + math.floor(fractions[1] * len(members))
        roles["D"] += members[:a]
        roles["C"] += members[a:b]
        roles["E"] += members[b:]
    return {r: sorted(v) for r, v in roles.items()}


def _phi(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.vectorize(math.erf)(x / math.sqrt(2.0)))


def noise_analytic_probability(
    predicted: np.ndarray, sigma: np.ndarray, *, tau: float, epsilon: float
) -> np.ndarray:
    """B1 baseline: P(joint event) if the observation were prediction + Gaussian noise.

    The observed change is modelled as ``d ~ N(h, sigma^2)`` with the prediction taken as
    exact; success requires ``d`` in the predicted direction class and ``|d - h| <= epsilon``.
    This is a measurement-noise baseline, not a model of prediction error.
    """
    h = np.asarray(predicted, dtype=np.float64)
    s = np.asarray(sigma, dtype=np.float64)
    if np.any(~np.isfinite(s)) or np.any(s <= 0):
        raise ValueError("sigma must be finite and positive")
    lo = np.where(h > tau, tau, np.where(h < -tau, -np.inf, -tau))
    hi = np.where(h > tau, np.inf, np.where(h < -tau, -tau, tau))
    a = np.maximum(lo, h - epsilon)
    b = np.minimum(hi, h + epsilon)
    return np.clip(_phi((b - h) / s) - _phi((a - h) / s), 0.0, 1.0)


def batch_matched_reference(
    reference: np.ndarray, reference_groups: np.ndarray, target_groups: np.ndarray
) -> tuple[np.ndarray, list]:
    """Control mean weighted to the target's gem-group composition.

    Groups in the target with no reference cells use the pooled reference mean; their
    labels are returned so the fallback is recorded.
    """
    pooled = reference.mean(axis=0)
    groups, counts = np.unique(target_groups, return_counts=True)
    total = counts.sum()
    out = np.zeros(reference.shape[1])
    fallback = []
    for g, n in zip(groups.tolist(), counts.tolist()):
        mask = reference_groups == g
        if mask.any():
            out += (n / total) * reference[mask].mean(axis=0)
        else:
            out += (n / total) * pooled
            fallback.append(g)
    return out, fallback


# ---------------------------------------------------------------------------
# Trust model, operating point and acceptance (S3/S4 machinery; synthetic-tested)
# ---------------------------------------------------------------------------


def target_weighted_rate(values: np.ndarray, targets: np.ndarray) -> float:
    """Mean over targets of each target's mean value (equal total weight per target)."""
    uniq, inv = np.unique(targets, return_inverse=True)
    sums = np.bincount(inv, weights=values, minlength=len(uniq))
    counts = np.bincount(inv, minlength=len(uniq))
    return float(np.mean(sums / counts))


def _target_weights(targets: np.ndarray) -> np.ndarray:
    _, inv, counts = np.unique(targets, return_inverse=True, return_counts=True)
    return 1.0 / counts[inv]


def fit_trust_model(x_dev, z_dev, t_dev, x_cal, z_cal, t_cal) -> dict:
    """ALIVE-L: logistic model fit on role D, isotonic recalibration on role C.

    Rows are weighted so each target has equal total weight; hyperparameters are fixed.
    Returns JSON-serializable parameters for :func:`predict_trust` (the frozen method).
    """
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression

    logit = LogisticRegression(C=1.0, max_iter=1000)
    logit.fit(x_dev, z_dev, sample_weight=_target_weights(t_dev))
    params = {"coef": logit.coef_[0].tolist(), "intercept": float(logit.intercept_[0])}
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    iso.fit(_logistic(params, x_cal), z_cal, sample_weight=_target_weights(t_cal))
    params["iso_x"] = iso.X_thresholds_.tolist()
    params["iso_y"] = iso.y_thresholds_.tolist()
    return params


def _logistic(params: dict, x) -> np.ndarray:
    s = np.asarray(x, float) @ np.asarray(params["coef"]) + params["intercept"]
    return 1.0 / (1.0 + np.exp(-s))


def predict_trust(params: dict, x) -> np.ndarray:
    """Calibrated probability from frozen ALIVE-L parameters (isotonic step interpolation)."""
    return np.interp(_logistic(params, x), params["iso_x"], params["iso_y"])


def operating_point(p: np.ndarray, z: np.ndarray, targets: np.ndarray, *, budget: float) -> float:
    """Lowest threshold whose accepted set (p >= t) has target-weighted failure <= budget.

    Fixed on role C. Returns ``inf`` (accept nothing) if no threshold qualifies.
    """
    best = float("inf")
    for t in np.unique(p)[::-1]:
        keep = p >= t
        if target_weighted_rate(1.0 - z[keep], targets[keep]) <= budget:
            best = float(t)
        else:
            break
    return best


def _per_target_mean(values, inv, n, mask=None):
    """Per-target mean of ``values`` over rows in ``mask``; NaN where a target has none."""
    m = np.ones(len(values), bool) if mask is None else mask
    s = np.bincount(inv[m], weights=values[m], minlength=n)
    c = np.bincount(inv[m], minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(c > 0, s / np.maximum(c, 1), np.nan)


def _boot_means(per_target: np.ndarray, n_boot: int, seed: int) -> np.ndarray:
    """Target-cluster bootstrap of the mean over targets (NaN targets excluded per draw)."""
    rng = np.random.default_rng(seed)
    n = len(per_target)
    draws = rng.integers(0, n, size=(n_boot, n))
    return np.nanmean(per_target[draws], axis=1)


def evaluate_acceptance(
    *, p, z, targets, baseline_constant, comparator, threshold, thresholds, n_boot, alpha, seed
) -> dict:
    """Evaluate registered acceptance on one role-E stratum (descriptive + verdict).

    Target-cluster bootstrap over precomputed per-target means (each target weighs equally);
    Bonferroni allocation of ``alpha`` over every primitive interval in the family (valid
    under arbitrary dependence, conservative). Unsupported bins (< 30 targets) are reported,
    never passed.
    """
    p, z, targets = np.asarray(p, float), np.asarray(z, float), np.asarray(targets)
    uniq, inv = np.unique(targets, return_inverse=True)
    n = len(uniq)
    edges = np.linspace(0, 1, 11)
    bins = np.clip(np.digitize(p, edges[1:-1]), 0, 9)
    supported = [b for b in range(10) if len(np.unique(inv[bins == b])) >= 30]
    family = len(supported) + 4  # bins + brier + risk + use + comparative
    a = alpha / family

    cal = {}
    for b in supported:
        per = _per_target_mean(z - p, inv, n, bins == b)
        lo, hi = np.quantile(_boot_means(per, n_boot, seed + b), [a / 2, 1 - a / 2])
        cal[b] = {"gap": float(np.nanmean(per)), "ci": [float(lo), float(hi)]}
    margin = thresholds["calibration_margin"]
    cal_pass = bool(supported) and all(
        -margin <= c["ci"][0] and c["ci"][1] <= margin for c in cal.values()
    )

    diff = _per_target_mean((p - z) ** 2 - (baseline_constant - z) ** 2, inv, n)
    brier_hi = float(np.quantile(_boot_means(diff, n_boot, seed + 100), 1 - a))

    keep = p >= threshold
    risk_per = _per_target_mean(1.0 - z, inv, n, keep)
    risk_draws = _boot_means(risk_per, n_boot, seed + 200) if keep.any() else np.ones(n_boot)
    risk_ucb = float(np.nanquantile(np.nan_to_num(risk_draws, nan=1.0), 1 - a))
    use_per = _per_target_mean(keep.astype(float), inv, n)
    use_lcb = float(np.quantile(_boot_means(use_per, n_boot, seed + 300), a))

    k = int(keep.sum())
    comp_keep = np.zeros(len(p), bool)
    if k:
        comp_keep[np.argsort(-np.asarray(comparator, float), kind="stable")[:k]] = True
    delta = _per_target_mean((1.0 - z) * (keep.astype(float) - comp_keep.astype(float)), inv, n)
    comp_hi = float(np.quantile(_boot_means(delta, n_boot, seed + 400), 1 - a)) if k else 0.0

    out = {
        "n_targets": n,
        "supported_bins": supported,
        "calibration": {"bins": cal, "pass": cal_pass},
        "brier_vs_constant": {"diff_ucb": brier_hi, "pass": brier_hi < 0},
        "selected": {
            "threshold": threshold,
            "risk_ucb": risk_ucb,
            "use_lcb": use_lcb,
            "pass": risk_ucb <= thresholds["risk_ucb"] and use_lcb >= thresholds["use_lcb"],
        },
        "comparative": {"risk_diff_ucb": comp_hi, "pass": bool(k) and comp_hi < 0},
        "family_size": family,
    }
    core = (
        out["calibration"]["pass"] and out["brier_vs_constant"]["pass"] and out["selected"]["pass"]
    )
    out["verdict"] = (
        "PASS" if core and out["comparative"]["pass"] else ("NO_DISTINCT_WIN" if core else "FAIL")
    )
    if not supported:
        out["verdict"] = "INCONCLUSIVE"
    return out


def joint_event(h: np.ndarray, d: np.ndarray, *, tau: float, epsilon: float) -> dict:
    """Vectorized direction-class, magnitude and joint events (registered definitions).

    Boundary values are NEGLIGIBLE and magnitude equality succeeds, matching
    :func:`alive.eval.events.classify_direction_magnitude`.
    """
    h, d = np.asarray(h, float), np.asarray(d, float)

    def cls(v):
        return np.where(v > tau, 1, np.where(v < -tau, -1, 0))

    z_dir = cls(h) == cls(d)
    z_mag = np.abs(h - d) <= epsilon
    return {"predicted_class": cls(h), "z_dir": z_dir, "z_mag": z_mag, "z_joint": z_dir & z_mag}


def sign_event(h: np.ndarray, d: np.ndarray) -> np.ndarray:
    """v2 direction event: observed sign equals predicted sign (observed zero fails)."""
    h, d = np.asarray(h, float), np.asarray(d, float)
    return (np.sign(d) == np.sign(h)) & (d != 0)


def attenuation_slope(
    h: np.ndarray, d: np.ndarray, targets: np.ndarray, *, n_boot: int, seed: int, alpha: float
) -> dict:
    """OLS slope of observed on predicted change with a target-cluster bootstrap CI."""
    h, d, targets = np.asarray(h, float), np.asarray(d, float), np.asarray(targets)
    slope = float(np.polyfit(h, d, 1)[0])
    uniq, inv = np.unique(targets, return_inverse=True)
    groups = [np.flatnonzero(inv == i) for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        rows = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        draws.append(np.polyfit(h[rows], d[rows], 1)[0])
    lo, hi = np.quantile(draws, [alpha / 2, 1 - alpha / 2])
    return {
        "slope": slope,
        "ci": [float(lo), float(hi)],
        "median_ratio": float(np.median(np.abs(d) / np.abs(h))),
    }
