"""Known-answer, constant, shuffled and random sanity checks for the D8 evaluator."""

from __future__ import annotations

import numpy as np

from alive.experiment.day8_protocol import (
    evaluate_acceptance,
    fit_trust_model,
    operating_point,
    predict_trust,
    target_weighted_rate,
)


def _synthetic(n_targets, per_target, seed, p_fn):
    rng = np.random.default_rng(seed)
    targets = np.repeat(np.arange(n_targets), per_target).astype(str)
    x = rng.uniform(-3, 3, size=(len(targets), 1))
    p = p_fn(x[:, 0])
    z = (rng.uniform(size=len(p)) < p).astype(float)
    return x, p, z, targets


def _logit(x):
    return 1 / (1 + np.exp(-x))


def test_target_weighted_rate_gives_targets_equal_weight():
    values = np.array([1.0, 1.0, 1.0, 0.0])
    targets = np.array(["a", "a", "a", "b"])
    assert np.isclose(target_weighted_rate(values, targets), 0.5)


def test_operating_point_selects_largest_coverage_within_budget():
    p = np.array([0.95, 0.9, 0.8, 0.5, 0.2])
    z = np.array([1, 1, 1, 0, 0], dtype=float)
    t = operating_point(p, z, np.array(list("abcde")), budget=0.10)
    assert t == 0.8


def _run(p_eval_fn, seed=0, budget=0.10, n=(1200, 600, 1200), per_target=40):
    xd, _, zd, td = _synthetic(n[0], per_target, seed, _logit)
    xc, _, zc, tc = _synthetic(n[1], per_target, seed + 1, _logit)
    xe, pe, ze, te = _synthetic(n[2], per_target, seed + 2, _logit)
    params = fit_trust_model(xd, zd, td, xc, zc, tc)
    model = lambda x: predict_trust(params, x)  # noqa: E731
    pc = model(xc)
    t = operating_point(pc, zc, tc, budget=budget)
    return evaluate_acceptance(
        p=p_eval_fn(model, xe, pe),
        z=ze,
        targets=te,
        baseline_constant=float(zd.mean()),
        comparator=np.full(len(ze), 0.5),
        threshold=t,
        thresholds={"calibration_margin": 0.10, "risk_ucb": 0.20, "use_lcb": 0.30},
        n_boot=300,
        alpha=0.05,
        seed=seed,
    )


def test_known_answer_calibrated_model_passes_calibration_and_beats_constant():
    # All sanity arms share an N at which a calibrated model passes, so each failure below
    # is attributable to the defect, not to power (300 targets x 20 outputs gave bin CI
    # widths up to 0.24 against a +/-0.10 equivalence margin).
    out = _run(lambda m, x, p: m(x))
    assert out["comparative"]["pass"] is True
    assert out["verdict"] in ("PASS", "NO_DISTINCT_WIN", "FAIL")
    assert out["calibration"]["pass"] is True
    assert out["brier_vs_constant"]["pass"] is True


def test_constant_probability_fails_brier_improvement():
    out = _run(lambda m, x, p: np.full(len(p), 0.5))
    assert out["brier_vs_constant"]["pass"] is False


def test_miscalibrated_probabilities_fail_calibration():
    out = _run(lambda m, x, p: np.clip(m(x) + 0.25, 0, 1))
    assert out["calibration"]["pass"] is False


def test_shuffled_scores_fail_comparative_value_and_selected_risk():
    rng = np.random.default_rng(9)
    out = _run(lambda m, x, p: rng.permutation(m(x)))
    assert out["comparative"]["pass"] is False
    assert out["verdict"] != "PASS"


def test_random_scores_do_not_pass():
    rng = np.random.default_rng(11)
    out = _run(lambda m, x, p: rng.uniform(size=len(p)))
    assert out["verdict"] != "PASS"
