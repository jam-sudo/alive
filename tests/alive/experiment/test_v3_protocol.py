"""Known-answer and fail-closed tests for the CART-K562-V3 decision rules (synthetic only)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from alive.experiment import v3_protocol as v3
from alive.experiment.day8_protocol import evaluate_acceptance
from alive.experiment.day8_protocol import operating_point as d8_operating_point

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "cart_k562_v3.yaml"
INTERIM = {
    "strata": "p1_support_indicator",
    "b0_policy": "c_gate",
    "b0_weighting": "target_equal",
    "c_selection_unit": "pooled",
    "operating_point": "exhaustive_largest_coverage",
    "e_alpha": "bonferroni_all_intervals",
    "single_unit_eligibility": "evaluate_where_eligible",
    "predictions_per_unit": "shared",
    "verdict_aggregation": "fail_first",
    "no_candidate": "no_product_terminal",
}


def _rules(**over):
    cfg = yaml.safe_load(CONFIG.read_text())
    cfg["v3_1_rules"] = {**INTERIM, **over}
    rules = v3.resolve_rules(cfg)
    rules["thresholds"]["n_boot"] = 400  # speed; the registered 2,000 is read and checked below
    return rules


def _exact(n_targets, m, successes, prefix="T"):
    """Rows where each target has exactly ``successes`` of ``m`` outputs succeed."""
    t = np.repeat([f"{prefix}{i}" for i in range(n_targets)], m)
    z = np.tile(np.r_[np.ones(successes), np.zeros(m - successes)], n_targets)
    return z, t


def test_resolve_rules_fails_closed_on_every_blank():
    cfg = yaml.safe_load(CONFIG.read_text())
    with pytest.raises(ValueError) as e:
        v3.resolve_rules(cfg)
    for blank in v3.BLANKS:
        assert blank in str(e.value)
    cfg["v3_1_rules"] = {**INTERIM, "b0_policy": "something_else"}
    with pytest.raises(ValueError, match="b0_policy='something_else'"):
        v3.resolve_rules(cfg)
    cfg["v3_1_rules"] = INTERIM
    rules = v3.resolve_rules(cfg)
    assert rules["thresholds"]["n_boot"] == 2000 and rules["min_units"] == 2
    assert rules["thresholds"]["risk_ucb_max"] == 0.15


def test_operating_point_is_exhaustive_largest_coverage():
    p, z, t = np.array([0.99, 0.95, 0.90]), np.array([0.0, 1.0, 1.0]), np.array(["a", "b", "c"])
    assert v3.operating_point(p, z, t, budget=0.4) == 0.90
    assert d8_operating_point(p, z, t, budget=0.4) == float("inf")  # the D8 early-stop deviation
    # Several thresholds qualify: the lowest (largest coverage) is the registered one.
    two = np.array(["a", "b"])
    assert v3.operating_point(np.array([0.9, 0.8]), np.ones(2), two, budget=0.1) == 0.8
    # Target-equal weighting: target "a" fails on 1 of 9 outputs, target "b" on its single output.
    p = np.r_[np.full(9, 0.8), 0.6]
    z = np.r_[np.ones(8), 0.0, 0.0]
    t = np.array(["a"] * 9 + ["b"])
    assert v3.operating_point(p, z, t, budget=0.2) == 0.8  # row-weighted 0.2 would admit 0.6
    assert v3.operating_point(p, z, t, budget=0.01) == float("inf")


def test_b0_constant_weighting():
    z = np.r_[np.ones(9), 0.0, 0.0]
    t = np.array(["a"] * 10 + ["b"])
    assert v3.b0_constant(z, t, weighting="target_equal") == pytest.approx(0.45)
    assert v3.b0_constant(z, t, weighting="row") == pytest.approx(9 / 11)


def test_calibrated_constant_passes_where_d8_evaluator_cannot():
    rules = _rules()
    z, t = _exact(60, 10, 9)
    p = np.full(len(z), 0.9)
    req = v3.requirements(
        p,
        z,
        t,
        threshold=0.9,
        constant=True,
        baseline_constant=0.9,
        thresholds=rules["thresholds"],
        a=0.05 / 3,
        n_boot=400,
        seed=0,
    )
    assert req["pass"] and "brier_vs_constant" not in req
    assert req["calibration"]["bins"][9]["ci"] == pytest.approx([0.0, 0.0])
    old = evaluate_acceptance(
        p=p,
        z=z,
        targets=t,
        baseline_constant=0.9,
        comparator=p,
        threshold=0.9,
        thresholds={"calibration_margin": 0.10, "risk_ucb": 0.15, "use_lcb": 0.30},
        n_boot=400,
        alpha=0.05,
        seed=0,
    )
    assert old["verdict"] == "FAIL"  # Brier diff is identically 0 for B0 (F3)


def test_miscalibrated_constant_and_shuffled_score_fail():
    rules = _rules()
    z, t = _exact(60, 10, 6)
    req = v3.requirements(
        np.full(len(z), 0.9),
        z,
        t,
        threshold=0.9,
        constant=True,
        baseline_constant=0.9,
        thresholds=rules["thresholds"],
        a=0.05 / 3,
        n_boot=400,
        seed=0,
    )
    assert not req["calibration"]["pass"] and not req["selected"]["pass"] and not req["pass"]
    rng = np.random.default_rng(0)
    z = rng.random(3000) < 0.7
    t = np.repeat([f"T{i}" for i in range(100)], 30)
    shuffled = rng.random(3000)
    req = v3.requirements(
        shuffled,
        z,
        t,
        threshold=0.0,
        constant=False,
        baseline_constant=0.7,
        thresholds=rules["thresholds"],
        a=0.05 / 13,
        n_boot=400,
        seed=0,
    )
    assert not req["brier_vs_constant"]["pass"] and not req["pass"]


def test_informative_score_beats_constant_on_brier():
    rules = _rules()
    rng = np.random.default_rng(1)
    q = np.repeat(rng.choice([0.05, 0.95], 120), 20)
    z = (rng.random(len(q)) < q).astype(float)
    t = np.repeat([f"T{i}" for i in range(120)], 20)
    req = v3.requirements(
        q,
        z,
        t,
        threshold=0.5,
        constant=False,
        baseline_constant=float(z.mean()),
        thresholds=rules["thresholds"],
        a=0.05 / 5,
        n_boot=400,
        seed=0,
    )
    assert req["brier_vs_constant"]["pass"]


def _units(spec):
    """spec: unit -> (n_targets, successes of 10); every unit's p is the constant 0.9."""
    out = {}
    for u, (n, s) in spec.items():
        z, t = _exact(n, 10, s, prefix=f"{u}_")
        out[u] = (np.full(len(z), 0.9), z, t)
    return out


def test_every_transduction_must_pass_and_family_is_split_over_units():
    rules = _rules()
    kw = {"product": "B0_constant", "threshold": 0.9, "b0_value": 0.9, "rules": rules, "seed": 0}
    res = v3.evaluate_units(_units({"u1": (60, 9), "u2": (60, 9)}), **kw)
    assert res["verdict"] == "PASS"
    assert res["family_size"] == 6 and res["alpha_per_interval"] == pytest.approx(0.05 / 6)
    res = v3.evaluate_units(_units({"u1": (60, 9), "u2": (60, 6)}), **kw)
    assert [res["units"][u]["verdict"] for u in ("u1", "u2")] == ["PASS", "FAIL"]
    assert res["verdict"] == "FAIL"
    res = v3.evaluate_units(_units({"u1": (60, 9), "u2": (29, 9)}), **kw)
    assert res["units"]["u2"]["verdict"] == "INCONCLUSIVE" and res["verdict"] == "INCONCLUSIVE"
    assert res["family_size"] == 3 + 2
    with pytest.raises(ValueError, match="registered minimum"):
        v3.evaluate_units(_units({"u1": (60, 9)}), **kw)


def test_aggregate_verdicts_precedence():
    assert v3.aggregate_verdicts(["PASS", "INCONCLUSIVE", "FAIL"]) == "FAIL"
    assert v3.aggregate_verdicts(["PASS", "INCONCLUSIVE"]) == "INCONCLUSIVE"
    assert v3.aggregate_verdicts(["PASS", "PASS"]) == "PASS"
    with pytest.raises(ValueError):
        v3.aggregate_verdicts([])
    with pytest.raises(ValueError):
        v3.aggregate_verdicts(["PASS", "NO_DISTINCT_WIN"])


def test_b0_policy_gate_versus_accept_all():
    # C failure 0.12 > budget 0.10, but risk UCB still <= 0.15 with 400 targets of 25 outputs.
    z, t = _exact(400, 25, 22)
    p = np.full(len(z), 0.88)
    gate = v3.select_product([("B0_constant", p)], z, t, b0_value=0.88, rules=_rules(), seed=0)
    assert gate["product"] is None and gate["outcome"] == "NO_PRODUCT"
    assert gate["checks"][0]["selected"]["threshold"] == float("inf")
    rules = _rules(b0_policy="accept_all")
    acc = v3.select_product([("B0_constant", p)], z, t, b0_value=0.88, rules=rules, seed=0)
    assert acc["product"] == "B0_constant" and acc["threshold"] == pytest.approx(0.88)


def test_select_product_order_and_comparator_guards():
    z, t = _exact(60, 10, 9)
    p = np.full(len(z), 0.9)
    with pytest.raises(ValueError, match="registered order"):
        v3.select_product(
            [("B1_noise_analytic", p), ("B0_constant", p)],
            z,
            t,
            b0_value=0.9,
            rules=_rules(),
            seed=0,
        )
    with pytest.raises(ValueError, match="B1 candidate"):
        v3.select_product([("ALIVE_L", p)], z, t, b0_value=0.9, rules=_rules(), seed=0)


def test_alive_l_needs_distinct_win_over_b1():
    rng = np.random.default_rng(2)
    q = np.repeat(rng.choice([0.05, 0.95], 200), 20)
    z = (rng.random(len(q)) < q).astype(float)
    t = np.repeat([f"T{i}" for i in range(200)], 20)
    # ALIVE-L identical to B1 cannot win; with B0 and B1 failing first, nothing is selected.
    rules = _rules(b0_policy="accept_all")
    res = v3.select_product(
        [("B0_constant", np.full(len(z), z.mean())), ("B1_noise_analytic", 1 - q), ("ALIVE_L", q)],
        z,
        t,
        b0_value=float(z.mean()),
        rules=rules,
        seed=0,
    )
    assert [c["candidate"] for c in res["checks"]] == list(v3.PRODUCT_ORDER)
    assert res["checks"][2]["distinct_win"]["pass"]
    # B1 ranks exactly like ALIVE-L but is miscalibrated: ALIVE-L meets 1-2, yet with the same
    # accepted set it has no distinct win, so nothing is selected.
    tie = v3.select_product(
        [("B1_noise_analytic", 0.5 * q + 0.25), ("ALIVE_L", q)],
        z,
        t,
        b0_value=0.5,
        rules=rules,
        seed=0,
    )
    assert not tie["checks"][0]["pass"]
    assert tie["checks"][1]["calibration"]["pass"] and tie["checks"][1]["selected"]["pass"]
    assert tie["checks"][1]["distinct_win"]["risk_diff_ucb"] == 0.0
    assert tie["product"] is None
