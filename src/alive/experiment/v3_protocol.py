"""Executable decision rules for CART-K562-V3 (pre-registered 2026-09-29; no outcome access).

Product selection on role C and per-transduction acceptance on role E. The registered text
leaves several rules open; :func:`resolve_rules` refuses to run until each is given a value
this module implements, so an unresolved blank fails closed instead of taking a default.
Thresholds come from the registered config; nothing here is a default scientific value.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from alive.experiment.day8_protocol import _boot_means, _per_target_mean, target_weighted_rate

PRODUCT_ORDER = ("B0_constant", "B1_noise_analytic", "ALIVE_L")

# Blank -> values this module implements. Any other value (or a missing key) is refused.
BLANKS: dict[str, frozenset[str] | None] = {
    "strata": None,  # recorded only; the split is done upstream
    "b0_policy": frozenset({"c_gate", "accept_all"}),
    "b0_weighting": frozenset({"target_equal", "row"}),
    "c_selection_unit": frozenset({"pooled"}),
    "operating_point": frozenset({"exhaustive_largest_coverage"}),
    "e_alpha": frozenset({"bonferroni_all_intervals"}),
    "single_unit_eligibility": frozenset({"evaluate_where_eligible"}),
    "predictions_per_unit": frozenset({"shared"}),
    "verdict_aggregation": frozenset({"fail_first"}),
    "no_candidate": frozenset({"no_product_terminal"}),
}


def resolve_rules(config: Mapping) -> dict:
    """Registered thresholds plus resolved blanks; raise naming every unresolved blank.

    Parameters
    ----------
    config : mapping
        Parsed V3 config. Blanks are read from ``config["v3_1_rules"]``.

    Returns
    -------
    dict
        ``thresholds`` (registered acceptance values) and ``blanks`` (resolved values).
    """
    given = dict(config.get("v3_1_rules") or {})
    missing = [k for k in BLANKS if k not in given]
    bad = [
        f"{k}={given[k]!r}"
        for k, allowed in BLANKS.items()
        if k in given and allowed is not None and given[k] not in allowed
    ]
    if missing or bad:
        raise ValueError(f"unresolved V3 blanks: missing={missing} unsupported={bad}")
    acc = config["acceptance"]
    order = list(config["product_rule"]["order"])
    if order != list(PRODUCT_ORDER):
        raise ValueError(f"product order {order} differs from {list(PRODUCT_ORDER)}")
    if acc["multiplicity"] != "bonferroni_over_family_and_transductions":
        raise ValueError(f"unsupported multiplicity {acc['multiplicity']!r}")
    keys = (
        "bins",
        "min_targets_per_bin",
        "calibration_margin",
        "operating_budget_on_C",
        "risk_ucb_max",
        "use_lcb_min",
        "alpha",
        "n_boot",
    )
    return {
        "thresholds": {k: acc[k] for k in keys},
        "min_units": int(config["replication"]["min_units"]),
        "blanks": {k: given[k] for k in BLANKS},
    }


def operating_point(p, z, targets, *, budget: float) -> float:
    """Registered operating point: the largest coverage whose target-weighted failure <= budget.

    Every distinct threshold is checked (no early stop), so a non-monotone risk curve cannot
    hide a qualifying lower threshold. Returns ``inf`` (accept nothing) if none qualifies.
    """
    p, z, targets = np.asarray(p, float), np.asarray(z, float), np.asarray(targets)
    for t in np.unique(p):  # ascending: the first qualifying threshold has the largest coverage
        keep = p >= t
        if target_weighted_rate(1.0 - z[keep], targets[keep]) <= budget:
            return float(t)
    return float("inf")


def b0_constant(z, targets, *, weighting: str) -> float:
    """B0 product: the role-D sign rate (target-equal or row-weighted per the resolved blank)."""
    z = np.asarray(z, float)
    if weighting == "target_equal":
        return target_weighted_rate(z, np.asarray(targets))
    if weighting == "row":
        return float(z.mean())
    raise ValueError(f"unsupported b0 weighting {weighting!r}")


def supported_bins(p, targets, thresholds: Mapping) -> list[int]:
    """Probability bins holding at least ``min_targets_per_bin`` distinct targets."""
    bins = _bin_index(p, thresholds["bins"])
    targets = np.asarray(targets)
    return [
        b
        for b in range(thresholds["bins"])
        if len(np.unique(targets[bins == b])) >= thresholds["min_targets_per_bin"]
    ]


def _bin_index(p, n_bins: int) -> np.ndarray:
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    return np.clip(np.digitize(np.asarray(p, float), edges[1:-1]), 0, n_bins - 1)


def family_size(n_supported: int, *, constant: bool, distinct_win: bool = False) -> int:
    """Intervals in one analysis: supported bins + risk + use [+ Brier] [+ distinct win]."""
    return n_supported + 2 + (0 if constant else 1) + (1 if distinct_win else 0)


def requirements(
    p,
    z,
    targets,
    *,
    threshold: float,
    constant: bool,
    baseline_constant: float,
    thresholds: Mapping,
    a: float,
    n_boot: int,
    seed: int,
) -> dict:
    """Requirements 1-2 on one analysis set; ``a`` is the per-interval (Bonferroni) level.

    Calibration: every supported bin's two-sided CI of (observed - predicted) lies within the
    margin; a non-constant product must also beat the constant on Brier (paired UCB < 0).
    Practicality: at ``threshold``, selected-risk UCB <= max and use-rate LCB >= min. Every
    rate weighs targets equally (target-cluster bootstrap).
    """
    p, z, targets = np.asarray(p, float), np.asarray(z, float), np.asarray(targets)
    uniq, inv = np.unique(targets, return_inverse=True)
    n = len(uniq)
    sup = supported_bins(p, targets, thresholds)
    bins = _bin_index(p, thresholds["bins"])
    margin = thresholds["calibration_margin"]

    cal = {}
    for b in sup:
        per = _per_target_mean(z - p, inv, n, bins == b)
        lo, hi = np.quantile(_boot_means(per, n_boot, seed + b), [a / 2, 1 - a / 2])
        cal[b] = {"gap": float(np.nanmean(per)), "ci": [float(lo), float(hi)]}
    cal_pass = bool(sup) and all(
        -margin <= c["ci"][0] and c["ci"][1] <= margin for c in cal.values()
    )

    out: dict = {"n_targets": n, "supported_bins": sup}
    out["calibration"] = {"bins": cal, "pass": cal_pass}
    if not constant:
        diff = _per_target_mean((p - z) ** 2 - (baseline_constant - z) ** 2, inv, n)
        ucb = float(np.quantile(_boot_means(diff, n_boot, seed + 100), 1 - a))
        out["brier_vs_constant"] = {"diff_ucb": ucb, "pass": ucb < 0}

    keep = p >= threshold
    if keep.any():
        risk_draws = _boot_means(_per_target_mean(1.0 - z, inv, n, keep), n_boot, seed + 200)
        risk_ucb = float(np.quantile(np.nan_to_num(risk_draws, nan=1.0), 1 - a))
    else:
        risk_ucb = 1.0
    use_per = _per_target_mean(keep.astype(float), inv, n)
    use_lcb = float(np.quantile(_boot_means(use_per, n_boot, seed + 300), a))
    out["selected"] = {
        "threshold": threshold,
        "risk_ucb": risk_ucb,
        "use_lcb": use_lcb,
        "pass": risk_ucb <= thresholds["risk_ucb_max"] and use_lcb >= thresholds["use_lcb_min"],
    }
    out["pass"] = (
        cal_pass and out["selected"]["pass"] and out.get("brier_vs_constant", {}).get("pass", True)
    )
    return out


def distinct_win(p, comparator, z, targets, *, threshold: float, a: float, n_boot: int, seed: int):
    """Requirement 4: at matched coverage, risk(product) - risk(comparator) has paired UCB < 0."""
    p, z, targets = np.asarray(p, float), np.asarray(z, float), np.asarray(targets)
    uniq, inv = np.unique(targets, return_inverse=True)
    keep = p >= threshold
    k = int(keep.sum())
    if not k:
        return {"risk_diff_ucb": None, "pass": False}
    comp = np.zeros(len(p), bool)
    comp[np.argsort(-np.asarray(comparator, float), kind="stable")[:k]] = True
    delta = _per_target_mean((1.0 - z) * (keep.astype(float) - comp), inv, len(uniq))
    ucb = float(np.quantile(_boot_means(delta, n_boot, seed + 400), 1 - a))
    return {"risk_diff_ucb": ucb, "pass": ucb < 0}


def select_product(
    candidates: Sequence[tuple[str, np.ndarray]],
    z,
    targets,
    *,
    b0_value: float,
    rules: Mapping,
    seed: int,
) -> dict:
    """Pre-registered product rule on role C: the first candidate meeting requirements 1-2.

    ``candidates`` are (name, probability on C rows) in registered order (a prefix-preserving
    subsequence of :data:`PRODUCT_ORDER`). ALIVE-L additionally needs a distinct win over B1.
    B0 under ``b0_policy="accept_all"`` takes its own value as threshold (accept all); under
    ``"c_gate"`` it uses the registered operating point like any other candidate.
    Returns the selected name (or ``None``), its threshold and every check made.
    """
    names = [c[0] for c in candidates]
    if names != [n for n in PRODUCT_ORDER if n in names]:
        raise ValueError(f"candidates {names} not in registered order")
    th, blanks = rules["thresholds"], rules["blanks"]
    probs = dict(candidates)
    checks = []
    for name, p in candidates:
        p = np.asarray(p, float)
        is_b0 = name == "B0_constant"
        if is_b0 and blanks["b0_policy"] == "accept_all":
            threshold = float(p.min())
        else:
            threshold = operating_point(p, z, targets, budget=th["operating_budget_on_C"])
        needs_win = name == "ALIVE_L"
        if needs_win and "B1_noise_analytic" not in probs:
            raise ValueError("ALIVE_L selection requires the B1 candidate as comparator")
        fam = family_size(
            len(supported_bins(p, targets, th)), constant=is_b0, distinct_win=needs_win
        )
        a = th["alpha"] / fam
        req = requirements(
            p,
            z,
            targets,
            threshold=threshold,
            constant=is_b0,
            baseline_constant=b0_value,
            thresholds=th,
            a=a,
            n_boot=th["n_boot"],
            seed=seed,
        )
        if needs_win:
            req["distinct_win"] = distinct_win(
                p,
                probs["B1_noise_analytic"],
                z,
                targets,
                threshold=threshold,
                a=a,
                n_boot=th["n_boot"],
                seed=seed,
            )
            req["pass"] = req["pass"] and req["distinct_win"]["pass"]
        checks.append({"candidate": name, "family_size": fam, **req})
        if req["pass"]:
            return {"product": name, "threshold": threshold, "checks": checks}
    return {"product": None, "threshold": None, "checks": checks, "outcome": "NO_PRODUCT"}


def evaluate_units(
    units: Mapping[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    *,
    product: str,
    threshold: float,
    b0_value: float,
    rules: Mapping,
    seed: int,
) -> dict:
    """Registered E acceptance, separately per independent transduction.

    ``units`` maps transduction id -> (p, z, targets) for the eligible E rows of that unit.
    Alpha is Bonferroni-split over every interval of every unit. A unit with no supported bin
    is INCONCLUSIVE; overall: any FAIL -> FAIL, else any INCONCLUSIVE -> INCONCLUSIVE, else PASS.
    """
    th = rules["thresholds"]
    if len(units) < rules["min_units"]:
        raise ValueError(f"{len(units)} transductions < registered minimum {rules['min_units']}")
    constant = product == "B0_constant"
    fam = {
        u: family_size(len(supported_bins(p, t, th)), constant=constant)
        for u, (p, _, t) in units.items()
    }
    a = th["alpha"] / sum(fam.values())
    per_unit = {}
    for i, (u, (p, z, t)) in enumerate(sorted(units.items())):
        req = requirements(
            p,
            z,
            t,
            threshold=threshold,
            constant=constant,
            baseline_constant=b0_value,
            thresholds=th,
            a=a,
            n_boot=th["n_boot"],
            seed=seed + 1000 * i,
        )
        req["verdict"] = (
            "INCONCLUSIVE" if not req["supported_bins"] else ("PASS" if req["pass"] else "FAIL")
        )
        per_unit[u] = req
    return {
        "product": product,
        "alpha_per_interval": a,
        "family_size": sum(fam.values()),
        "units": per_unit,
        "verdict": aggregate_verdicts([r["verdict"] for r in per_unit.values()]),
    }


def aggregate_verdicts(verdicts: Sequence[str]) -> str:
    """PASS only if every unit passes; any FAIL dominates INCONCLUSIVE."""
    if not verdicts:
        raise ValueError("no transduction verdicts")
    if "FAIL" in verdicts:
        return "FAIL"
    if "INCONCLUSIVE" in verdicts:
        return "INCONCLUSIVE"
    if set(verdicts) != {"PASS"}:
        raise ValueError(f"unknown verdicts {sorted(set(verdicts))}")
    return "PASS"
