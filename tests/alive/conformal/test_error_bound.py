"""Tests for the split-conformal calibration layer (Task 13).

These tests pin down the four statistically-subtle pieces of the calibration
layer:

1. the finite-sample split-conformal scalar bound (off-by-one in the
   order-statistic rank ``k = ceil((n_cal+1)(1-alpha))`` clipped to ``n_cal``);
2. the PREDICT threshold derived from calibration GATE SCORES (never errors);
3. the 5-metric coverage report; and
4. the EXACT split-conformal beta-binomial predictive acceptance band, checked
   both against ``scipy.stats.betabinom`` directly and against an
   exchangeable-rank Monte-Carlo simulation.

The headline correctness test is the Monte-Carlo simulation: it independently
re-derives that the number of covered test points among ``n_test`` exchangeable
points follows ``BetaBinomial(n_test, k, n_cal+1-k)``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import betabinom

from alive.conformal.error_bound import (
    ConformalArtifact,
    ConformalError,
    betabinom_acceptance_band,
    build_conformal_artifact,
    conformal_coverage_passes,
    conformal_error_bound,
    conformal_rank,
    coverage_report,
    predict_threshold,
)

# ===========================================================================
# Finite-sample scalar bound + rank: hand-verified order statistics
# ===========================================================================


def test_rank_hand_verified_examples() -> None:
    """k = min(ceil((n+1)(1-alpha)), n) for hand-verified cases."""
    # n=9, alpha=0.1 -> ceil(10*0.9)=ceil(9.0)=9 -> clip to 9 -> the max
    assert conformal_rank(9, 0.1) == 9
    # n=19, alpha=0.1 -> ceil(20*0.9)=ceil(18.0)=18 -> 18th of 19
    assert conformal_rank(19, 0.1) == 18
    # n=10, alpha=0.1 -> ceil(11*0.9)=ceil(9.9)=10 -> clip to 10 -> the max
    assert conformal_rank(10, 0.1) == 10
    # n=5, alpha=0.5 -> ceil(6*0.5)=3 -> 3rd of 5 (median)
    assert conformal_rank(5, 0.5) == 3
    # n=100, alpha=0.05 -> ceil(101*0.95)=ceil(95.95)=96
    assert conformal_rank(100, 0.05) == 96
    # n=20, alpha=0.2 -> ceil(21*0.8)=ceil(16.8)=17
    assert conformal_rank(20, 0.2) == 17


def test_rank_clips_to_n() -> None:
    """When (n+1)(1-alpha) exceeds n the rank is clipped to n (use the max)."""
    # very small alpha forces ceil((n+1)(1-alpha)) = n+1 -> clipped to n
    assert conformal_rank(7, 1e-6) == 7
    assert conformal_rank(1, 0.1) == 1
    assert conformal_rank(2, 0.1) == 2


def test_error_bound_off_by_one_n9_alpha01() -> None:
    """n=9, alpha=0.1 -> k=9 -> bound = max (9th order statistic)."""
    errors = np.array([3.0, 1.0, 9.0, 2.0, 5.0, 8.0, 4.0, 7.0, 6.0])
    bound = conformal_error_bound(errors, alpha=0.1)
    assert bound == 9.0  # the max, index min(9,9)-1 = 8 of sorted


def test_error_bound_off_by_one_n19_alpha01() -> None:
    """n=19, alpha=0.1 -> k=18 -> bound = 18th of 19 sorted order statistics."""
    errors = np.arange(1.0, 20.0)  # 1..19, already sorted
    rng = np.random.default_rng(0)
    shuffled = errors.copy()
    rng.shuffle(shuffled)
    bound = conformal_error_bound(shuffled, alpha=0.1)
    # sorted is 1..19; 18th order statistic (index 17) == 18.0
    assert bound == 18.0
    assert np.sort(shuffled)[conformal_rank(19, 0.1) - 1] == bound


def test_error_bound_matches_sorted_kth_for_many_alphas() -> None:
    """For several (n, alpha) the bound equals sorted[min(k,n)-1] exactly."""
    rng = np.random.default_rng(42)
    for n in (5, 10, 13, 50, 137):
        errors = rng.uniform(0.0, 100.0, size=n)
        srt = np.sort(errors)
        for alpha in (0.01, 0.05, 0.1, 0.2, 0.33, 0.5, 0.9):
            k = conformal_rank(n, alpha)
            expected = srt[k - 1]
            assert conformal_error_bound(errors, alpha) == expected
            # cross-check k matches the closed form
            assert k == min(math.ceil((n + 1) * (1 - alpha)), n)


def test_error_bound_small_samples() -> None:
    """n_cal in {1, 2, 5} behave; bound = max when k == n."""
    assert conformal_error_bound(np.array([7.0]), alpha=0.1) == 7.0
    # n=2, alpha=0.1 -> k=2 -> max
    assert conformal_error_bound(np.array([2.0, 9.0]), alpha=0.1) == 9.0
    # n=5, alpha=0.5 -> k=3 -> 3rd order statistic (median)
    assert conformal_error_bound(np.array([5.0, 1.0, 3.0, 2.0, 4.0]), alpha=0.5) == 3.0


def test_error_bound_does_not_mutate_input() -> None:
    """Sorting happens on a copy; the caller's array is untouched."""
    errors = np.array([3.0, 1.0, 2.0])
    before = errors.copy()
    conformal_error_bound(errors, alpha=0.1)
    assert np.array_equal(errors, before)


def test_error_bound_accepts_list_input() -> None:
    """Plain python sequences are coerced to arrays."""
    assert conformal_error_bound([3.0, 1.0, 9.0, 2.0], alpha=0.1) == 9.0


def test_error_bound_empty_raises() -> None:
    with pytest.raises(ConformalError):
        conformal_error_bound(np.array([]), alpha=0.1)


def test_error_bound_bad_alpha_raises() -> None:
    errors = np.array([1.0, 2.0, 3.0])
    for bad in (0.0, 1.0, -0.1, 1.5, float("nan")):
        with pytest.raises(ConformalError):
            conformal_error_bound(errors, alpha=bad)


def test_rank_bad_alpha_raises() -> None:
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ConformalError):
            conformal_rank(10, bad)


def test_rank_bad_n_raises() -> None:
    with pytest.raises(ConformalError):
        conformal_rank(0, 0.1)
    with pytest.raises(ConformalError):
        conformal_rank(-3, 0.1)


def test_error_bound_2d_input_raises() -> None:
    with pytest.raises(ConformalError):
        conformal_error_bound(np.zeros((3, 2)), alpha=0.1)


def test_error_bound_nan_input_raises() -> None:
    with pytest.raises(ConformalError):
        conformal_error_bound(np.array([1.0, np.nan, 3.0]), alpha=0.1)


# ===========================================================================
# PREDICT threshold (from calibration GATE SCORES, method="lower")
# ===========================================================================


def test_predict_threshold_matches_numpy_lower_quantile() -> None:
    """Threshold is the target-coverage quantile via method='lower'."""
    scores = np.arange(1.0, 11.0)  # 1..10
    for target in (0.1, 0.3, 0.5, 0.7, 0.9, 1.0):
        expected = np.quantile(scores, target, method="lower")
        assert predict_threshold(scores, target) == expected


def test_predict_threshold_selection_fraction_approx_target() -> None:
    """Fraction of calibration scores <= threshold ~ target (method='lower')."""
    rng = np.random.default_rng(7)
    scores = rng.normal(0.0, 1.0, size=2000)
    for target in (0.3, 0.5, 0.7, 0.9):
        thr = predict_threshold(scores, target)
        frac = np.mean(scores <= thr)
        # method='lower' selects at least 'target' fraction for continuous data
        assert frac >= target - 1e-9
        assert abs(frac - target) < 0.02


def test_predict_threshold_full_coverage_target_one() -> None:
    """target=1.0 -> threshold = max -> everything selected."""
    scores = np.array([2.0, 5.0, 1.0, 9.0])
    thr = predict_threshold(scores, 1.0)
    assert thr == 9.0
    assert np.all(scores <= thr)


def test_predict_threshold_bad_target_raises() -> None:
    scores = np.array([1.0, 2.0, 3.0])
    for bad in (0.0, -0.1, 1.01, 2.0, float("nan")):
        with pytest.raises(ConformalError):
            predict_threshold(scores, bad)


def test_predict_threshold_empty_raises() -> None:
    with pytest.raises(ConformalError):
        predict_threshold(np.array([]), 0.7)


def test_predict_threshold_2d_raises() -> None:
    with pytest.raises(ConformalError):
        predict_threshold(np.zeros((4, 2)), 0.7)


def test_predict_threshold_does_not_mutate() -> None:
    scores = np.array([3.0, 1.0, 2.0])
    before = scores.copy()
    predict_threshold(scores, 0.5)
    assert np.array_equal(scores, before)


# ===========================================================================
# Coverage report (5 metrics + n_selected/n_total)
# ===========================================================================


def test_coverage_report_constructed_case() -> None:
    """All five metrics + counts on a fully hand-computed example."""
    # bound = 5.0, threshold = 2.0
    #   errors:  [1, 6, 3, 9, 2]
    #   scores:  [1, 5, 2, 3, 0]
    test_errors = np.array([1.0, 6.0, 3.0, 9.0, 2.0])
    test_scores = np.array([1.0, 5.0, 2.0, 3.0, 0.0])
    rep = coverage_report(test_errors, test_scores, error_bound=5.0, threshold=2.0)

    # selected = score <= 2.0 -> indices 0(1<=2), 2(2<=2), 4(0<=2) -> [T,F,T,F,T]
    # within   = error <= 5.0 -> indices 0(1),    2(3),    4(2)    -> [T,F,T,F,T]
    selected = test_scores <= 2.0
    within = test_errors <= 5.0
    assert rep["marginal_error_bound_coverage"] == pytest.approx(np.mean(within))
    assert rep["marginal_error_bound_coverage"] == pytest.approx(3 / 5)
    assert rep["selective_error_bound_coverage"] == pytest.approx(np.mean(within[selected]))
    assert rep["selective_error_bound_coverage"] == pytest.approx(1.0)  # all 3 selected covered
    assert rep["selection_coverage"] == pytest.approx(3 / 5)
    assert rep["effective_covered_fraction"] == pytest.approx(np.mean(selected & within))
    assert rep["effective_covered_fraction"] == pytest.approx(3 / 5)
    assert rep["abstain_rate"] == pytest.approx(1 - 3 / 5)
    assert rep["n_selected"] == 3
    assert rep["n_total"] == 5
    assert isinstance(rep["n_selected"], int)
    assert isinstance(rep["n_total"], int)


def test_coverage_report_selective_nan_when_none_selected() -> None:
    """selective_error_bound_coverage is NaN when nothing is selected."""
    test_errors = np.array([1.0, 2.0, 3.0])
    test_scores = np.array([10.0, 11.0, 12.0])  # all above threshold
    rep = coverage_report(test_errors, test_scores, error_bound=5.0, threshold=2.0)
    assert math.isnan(rep["selective_error_bound_coverage"])
    assert rep["selection_coverage"] == 0.0
    assert rep["abstain_rate"] == 1.0
    assert rep["n_selected"] == 0
    assert rep["effective_covered_fraction"] == 0.0
    # marginal still defined
    assert rep["marginal_error_bound_coverage"] == pytest.approx(1.0)


def test_coverage_report_all_selected() -> None:
    test_errors = np.array([1.0, 2.0, 9.0])
    test_scores = np.array([0.0, 0.0, 0.0])
    rep = coverage_report(test_errors, test_scores, error_bound=5.0, threshold=1.0)
    assert rep["selection_coverage"] == 1.0
    assert rep["abstain_rate"] == 0.0
    assert rep["n_selected"] == 3
    # within = [T,T,F]; selective coverage over all 3 = 2/3
    assert rep["selective_error_bound_coverage"] == pytest.approx(2 / 3)
    assert rep["marginal_error_bound_coverage"] == pytest.approx(2 / 3)


def test_coverage_report_length_mismatch_raises() -> None:
    with pytest.raises(ConformalError):
        coverage_report(np.array([1.0, 2.0]), np.array([1.0]), error_bound=5.0, threshold=2.0)


def test_coverage_report_empty_raises() -> None:
    with pytest.raises(ConformalError):
        coverage_report(np.array([]), np.array([]), error_bound=5.0, threshold=2.0)


def test_coverage_report_boundary_inclusive() -> None:
    """<= is inclusive at both the bound and threshold (equality counts)."""
    test_errors = np.array([5.0])  # exactly == bound
    test_scores = np.array([2.0])  # exactly == threshold
    rep = coverage_report(test_errors, test_scores, error_bound=5.0, threshold=2.0)
    assert rep["marginal_error_bound_coverage"] == 1.0
    assert rep["selection_coverage"] == 1.0
    assert rep["selective_error_bound_coverage"] == 1.0


# ===========================================================================
# EXACT beta-binomial acceptance band
# ===========================================================================


def test_band_equals_betabinom_central_interval() -> None:
    """Band matches scipy.stats.betabinom(n_test, k, n_cal+1-k) central mass."""
    n_cal, alpha, n_test, central = 100, 0.1, 50, 0.99
    k = conformal_rank(n_cal, alpha)
    a, b = k, n_cal + 1 - k
    low, high = betabinom_acceptance_band(n_cal, alpha, n_test, central=central)

    dist = betabinom(n_test, a, b)
    tail = (1 - central) / 2
    # The band must hold >= central central mass.
    mass = dist.cdf(high) - dist.cdf(low - 1)
    assert mass >= central
    assert 0 <= low <= high <= n_test
    # Equal-tailed tightness: each edge is the minimal exclusion keeping that
    # tail <= `tail`. Moving `low` up by one would push the lower tail over.
    if low > 0:
        assert dist.cdf(low - 1) <= tail + 1e-12  # current lower tail OK
        assert dist.cdf(low) > tail  # one step in violates the lower-tail budget
    if high < n_test:
        assert (1 - dist.cdf(high)) <= tail + 1e-12  # current upper tail OK
        assert (1 - dist.cdf(high - 1)) > tail  # one step in violates upper-tail


def test_band_tail_probabilities_bounded() -> None:
    """Each tail beyond the band holds <= (1-central)/2 (discrete-ppf rule)."""
    n_cal, alpha, n_test, central = 80, 0.05, 64, 0.99
    k = conformal_rank(n_cal, alpha)
    a, b = k, n_cal + 1 - k
    low, high = betabinom_acceptance_band(n_cal, alpha, n_test, central=central)
    dist = betabinom(n_test, a, b)
    tail = (1 - central) / 2
    # lower tail P(X < low) = cdf(low-1) <= tail
    assert dist.cdf(low - 1) <= tail + 1e-12
    # upper tail P(X > high) = 1 - cdf(high) <= tail
    assert (1 - dist.cdf(high)) <= tail + 1e-12


def test_band_central_levels_monotone() -> None:
    """Higher central level -> wider (never narrower) band."""
    n_cal, alpha, n_test = 60, 0.1, 40
    low90, high90 = betabinom_acceptance_band(n_cal, alpha, n_test, central=0.90)
    low99, high99 = betabinom_acceptance_band(n_cal, alpha, n_test, central=0.99)
    assert low99 <= low90
    assert high99 >= high90


def test_band_bad_args_raise() -> None:
    with pytest.raises(ConformalError):
        betabinom_acceptance_band(10, 0.1, 0)  # n_test must be >= 1
    with pytest.raises(ConformalError):
        betabinom_acceptance_band(0, 0.1, 5)  # n_cal must be >= 1
    with pytest.raises(ConformalError):
        betabinom_acceptance_band(10, 0.0, 5)  # alpha out of range
    with pytest.raises(ConformalError):
        betabinom_acceptance_band(10, 0.1, 5, central=0.0)
    with pytest.raises(ConformalError):
        betabinom_acceptance_band(10, 0.1, 5, central=1.0)


def test_coverage_passes_uses_band() -> None:
    n_cal, alpha, n_test = 100, 0.1, 50
    low, high = betabinom_acceptance_band(n_cal, alpha, n_test)
    assert conformal_coverage_passes(low, n_cal, alpha, n_test)
    assert conformal_coverage_passes(high, n_cal, alpha, n_test)
    assert conformal_coverage_passes((low + high) // 2, n_cal, alpha, n_test)
    if low > 0:
        assert not conformal_coverage_passes(low - 1, n_cal, alpha, n_test)
    if high < n_test:
        assert not conformal_coverage_passes(high + 1, n_cal, alpha, n_test)


# ===========================================================================
# Headline: exchangeable-rank Monte-Carlo simulation
# ===========================================================================


def test_exchangeable_rank_simulation_matches_betabinom() -> None:
    """Monte-Carlo: covered-count distribution ~ BetaBinomial(n_test, k, n_cal+1-k).

    Independently re-derive the predictive distribution: draw many
    (calibration + test) sets from a CONTINUOUS distribution, compute the
    conformal bound on calibration, count covered test points, and confirm the
    empirical covered-count distribution matches the analytic beta-binomial in
    mean, variance, and the central 99% interval.
    """
    n_cal, alpha, n_test = 40, 0.1, 30
    n_sim = 30_000
    k = conformal_rank(n_cal, alpha)
    a, b = k, n_cal + 1 - k

    rng = np.random.default_rng(20260619)
    covered_counts = np.empty(n_sim, dtype=np.int64)
    idx = k - 1  # index of the kth order statistic
    for s in range(n_sim):
        cal = rng.standard_normal(n_cal)
        test = rng.standard_normal(n_test)
        bound = np.sort(cal)[idx]
        covered_counts[s] = int(np.sum(test <= bound))

    dist = betabinom(n_test, a, b)
    analytic_mean = dist.mean()
    analytic_var = dist.var()
    emp_mean = covered_counts.mean()
    emp_var = covered_counts.var()

    # MC standard error of the mean ~ sqrt(var/n_sim); allow ~5 SE.
    se_mean = math.sqrt(analytic_var / n_sim)
    assert abs(emp_mean - analytic_mean) < 5 * se_mean
    # variance within ~6% (var-of-var noise is larger)
    assert abs(emp_var - analytic_var) / analytic_var < 0.06

    # central ~99% interval should match the analytic band closely
    band_low, band_high = betabinom_acceptance_band(n_cal, alpha, n_test, central=0.99)
    emp_low = int(np.quantile(covered_counts, 0.005, method="lower"))
    emp_high = int(np.quantile(covered_counts, 0.995, method="higher"))
    assert abs(emp_low - band_low) <= 2
    assert abs(emp_high - band_high) <= 2

    # The analytic 99% band should empirically cover >= ~98.5% of simulations.
    inside = np.mean((covered_counts >= band_low) & (covered_counts <= band_high))
    assert inside >= 0.985


# ===========================================================================
# Selection-induced behavior on calibration scores
# ===========================================================================


def test_selection_coverage_on_calibration_approx_target() -> None:
    """predict_threshold selects ~ target fraction of CALIBRATION items."""
    rng = np.random.default_rng(11)
    cal_scores = rng.normal(0.0, 1.0, size=3000)
    target = 0.7
    thr = predict_threshold(cal_scores, target)
    # reuse coverage_report's selection logic on the calibration scores with a
    # dummy error array & bound (errors irrelevant to selection_coverage).
    dummy_errors = np.zeros_like(cal_scores)
    rep = coverage_report(dummy_errors, cal_scores, error_bound=0.0, threshold=thr)
    assert abs(rep["selection_coverage"] - target) < 0.02
    assert rep["selection_coverage"] >= target - 1e-9


# ===========================================================================
# Structural invariance to sealed outcomes
# ===========================================================================


def test_calibration_outputs_independent_of_sealed_array() -> None:
    """error_bound/rank/threshold/checksum depend on calibration arrays only.

    Structural guarantee: these functions never take sealed data, so shuffling
    a separate 'sealed' array cannot change them. We assert the same calibration
    inputs always yield the same outputs regardless of any sealed array.
    """
    cal_errors = np.array([3.0, 1.0, 9.0, 2.0, 5.0, 8.0, 4.0, 7.0, 6.0])
    cal_scores = np.array([0.5, 0.1, 0.9, 0.2, 0.5, 0.8, 0.4, 0.7, 0.6])

    art1 = build_conformal_artifact(
        cal_errors,
        cal_scores,
        alpha=0.1,
        target_selection_coverage=0.7,
        config_sha256="cfg",
    )
    # A separate sealed array exists in the caller; we shuffle it. It is never
    # passed to any Task-13 function, so outputs are unchanged.
    rng = np.random.default_rng(3)
    sealed = rng.standard_normal(100)
    rng.shuffle(sealed)
    art2 = build_conformal_artifact(
        cal_errors,
        cal_scores,
        alpha=0.1,
        target_selection_coverage=0.7,
        config_sha256="cfg",
    )
    assert art1.checksum == art2.checksum
    assert art1.error_bound == art2.error_bound
    assert art1.rank_k == art2.rank_k
    assert art1.predict_threshold == art2.predict_threshold


# ===========================================================================
# ConformalArtifact: build, determinism, round-trip
# ===========================================================================


def test_build_artifact_fields() -> None:
    cal_errors = np.arange(1.0, 20.0)
    cal_scores = np.arange(1.0, 20.0)
    art = build_conformal_artifact(
        cal_errors,
        cal_scores,
        alpha=0.1,
        target_selection_coverage=0.7,
        config_sha256="deadbeef",
    )
    assert art.n_cal == 19
    assert art.alpha == 0.1
    assert art.rank_k == conformal_rank(19, 0.1)
    assert art.error_bound == conformal_error_bound(cal_errors, 0.1)
    assert art.predict_threshold == predict_threshold(cal_scores, 0.7)
    assert art.target_selection_coverage == 0.7
    assert art.config_sha256 == "deadbeef"
    assert len(art.checksum) == 64


def test_build_artifact_length_mismatch_raises() -> None:
    with pytest.raises(ConformalError):
        build_conformal_artifact(
            np.arange(5.0),
            np.arange(4.0),
            alpha=0.1,
            target_selection_coverage=0.7,
            config_sha256="x",
        )


def test_artifact_checksum_deterministic() -> None:
    cal_errors = np.arange(1.0, 11.0)
    cal_scores = np.arange(1.0, 11.0)[::-1].copy()
    a1 = build_conformal_artifact(
        cal_errors, cal_scores, alpha=0.1, target_selection_coverage=0.7, config_sha256="c"
    )
    a2 = build_conformal_artifact(
        cal_errors, cal_scores, alpha=0.1, target_selection_coverage=0.7, config_sha256="c"
    )
    assert a1.checksum == a2.checksum


def test_artifact_checksum_changes_with_fields() -> None:
    cal_errors = np.arange(1.0, 11.0)
    cal_scores = np.arange(1.0, 11.0)
    base = build_conformal_artifact(
        cal_errors, cal_scores, alpha=0.1, target_selection_coverage=0.7, config_sha256="c"
    )
    diff_alpha = build_conformal_artifact(
        cal_errors, cal_scores, alpha=0.2, target_selection_coverage=0.7, config_sha256="c"
    )
    diff_cfg = build_conformal_artifact(
        cal_errors, cal_scores, alpha=0.1, target_selection_coverage=0.7, config_sha256="d"
    )
    assert base.checksum != diff_alpha.checksum
    assert base.checksum != diff_cfg.checksum


def test_artifact_round_trip(tmp_path) -> None:
    cal_errors = np.arange(1.0, 20.0)
    cal_scores = np.arange(1.0, 20.0)
    art = build_conformal_artifact(
        cal_errors,
        cal_scores,
        alpha=0.1,
        target_selection_coverage=0.7,
        config_sha256="abc123",
    )
    path = tmp_path / "conformal_artifact.json"
    art.write(path)
    loaded = ConformalArtifact.read(path)
    assert loaded == art
    assert loaded.checksum == art.checksum
    assert loaded.error_bound == art.error_bound
    assert loaded.rank_k == art.rank_k
    assert loaded.predict_threshold == art.predict_threshold


def test_artifact_read_detects_tamper(tmp_path) -> None:
    cal_errors = np.arange(1.0, 20.0)
    cal_scores = np.arange(1.0, 20.0)
    art = build_conformal_artifact(
        cal_errors, cal_scores, alpha=0.1, target_selection_coverage=0.7, config_sha256="abc"
    )
    path = tmp_path / "a.json"
    art.write(path)
    import json

    raw = json.loads(path.read_text())
    raw["error_bound"] = raw["error_bound"] + 100.0
    path.write_text(json.dumps(raw))
    with pytest.raises(ConformalError):
        ConformalArtifact.read(path)
