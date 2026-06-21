"""Tests for alive.metrics.selective — written FIRST per TDD protocol.

All tests are pure-numpy: no data files or external dependencies.

Hand-verified expected values are documented inline with derivations.
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.metrics.selective import (
    REGISTERED_COVERAGE_POINTS,
    MetricError,
    augrc,
    aurc,
    normalize_by_mean,
    risk_at_coverage,
    risk_coverage_curve,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_perfect(risks: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """Return (risk, score) where score == risk (perfectly ordered ascending)."""
    r = np.array(risks, dtype=np.float64)
    return r, r.copy()


def _make_reverse(risks: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """Return (risk, score) where score is descending in risk (worst = most-trusted first)."""
    r = np.array(risks, dtype=np.float64)
    s = -r  # lower risk → higher score → sorted LAST (ascending) → highest-risk items first
    return r, s


# ---------------------------------------------------------------------------
# Perfect ranking — hand-computed AURC/AUGRC
# ---------------------------------------------------------------------------


class TestPerfectRanking:
    """Score perfectly orders by risk ascending → minimises AURC.

    risks = [0, 1, 2, 3], n=4, perfectly sorted → [0, 1, 2, 3].

    selective_risk:
      k=1 → 0/1  = 0.0
      k=2 → 1/2  = 0.5
      k=3 → 3/3  = 1.0
      k=4 → 6/4  = 1.5

    AURC = (0.0 + 0.5 + 1.0 + 1.5) / 4 = 3.0 / 4 = 0.75

    generalized_risk_k = selective_risk_k * (k/n):
      k=1 → 0.0 * 0.25 = 0.0
      k=2 → 0.5 * 0.50 = 0.25
      k=3 → 1.0 * 0.75 = 0.75
      k=4 → 1.5 * 1.00 = 1.50

    AUGRC = (0.0 + 0.25 + 0.75 + 1.50) / 4 = 2.5 / 4 = 0.625
    """

    RISKS = [0.0, 1.0, 2.0, 3.0]

    def test_aurc(self) -> None:
        risk, score = _make_perfect(self.RISKS)
        assert aurc(risk, score) == pytest.approx(0.75)

    def test_augrc(self) -> None:
        risk, score = _make_perfect(self.RISKS)
        assert augrc(risk, score) == pytest.approx(0.625)

    def test_coverage_curve_values(self) -> None:
        risk, score = _make_perfect(self.RISKS)
        cov, sel = risk_coverage_curve(risk, score)
        assert len(cov) == 4
        assert len(sel) == 4
        np.testing.assert_allclose(cov, [0.25, 0.50, 0.75, 1.00])
        np.testing.assert_allclose(sel, [0.00, 0.50, 1.00, 1.50])

    def test_aurc_is_minimum_for_this_multiset(self) -> None:
        """Perfect order gives strictly smaller AURC than reverse for non-constant risk."""
        risk, score = _make_perfect(self.RISKS)
        risk_r, score_r = _make_reverse(self.RISKS)
        assert aurc(risk, score) < aurc(risk_r, score_r)


# ---------------------------------------------------------------------------
# Reverse ranking — hand-computed AURC
# ---------------------------------------------------------------------------


class TestReverseRanking:
    """Score = -risk → sorted ascending by score yields risks in descending order.

    Sorted order: [3, 2, 1, 0]

    selective_risk:
      k=1 → 3/1  = 3.0
      k=2 → 5/2  = 2.5
      k=3 → 6/3  = 2.0
      k=4 → 6/4  = 1.5

    AURC = (3.0 + 2.5 + 2.0 + 1.5) / 4 = 9.0 / 4 = 2.25
    """

    RISKS = [0.0, 1.0, 2.0, 3.0]

    def test_aurc(self) -> None:
        risk, score = _make_reverse(self.RISKS)
        assert aurc(risk, score) == pytest.approx(2.25)

    def test_strictly_greater_than_perfect(self) -> None:
        risk_p, score_p = _make_perfect(self.RISKS)
        risk_r, score_r = _make_reverse(self.RISKS)
        assert aurc(risk_r, score_r) > aurc(risk_p, score_p)


# ---------------------------------------------------------------------------
# Middling order (random) — between perfect and reverse
# ---------------------------------------------------------------------------


class TestMiddlingOrder:
    """A non-extreme ordering produces AURC between perfect and reverse."""

    RISKS = [0.0, 1.0, 2.0, 3.0]

    def test_between_perfect_and_reverse(self) -> None:
        risk = np.array(self.RISKS)
        # Assign scores: 1→high score (abstain), 3→low score (predict), 0→medium, 2→medium
        # score[i] for risk[i]: 0→1.5, 1→3.0, 2→1.0, 3→0.5
        # Ascending by score: 3(s=0.5), 2(s=1.0), 0(s=1.5), 1(s=3.0)  → risks: [3,2,0,1]
        score = np.array([1.5, 3.0, 1.0, 0.5])
        aurc_middle = aurc(risk, score)

        risk_p, score_p = _make_perfect(self.RISKS)
        risk_r, score_r = _make_reverse(self.RISKS)

        assert aurc(risk_p, score_p) < aurc_middle < aurc(risk_r, score_r)


# ---------------------------------------------------------------------------
# Constant risk
# ---------------------------------------------------------------------------


class TestConstantRisk:
    """All risks equal c → AURC == c; AUGRC == c*(n+1)/(2n).

    Derivation:
      selective_risk_k = c for all k.
      AURC = (1/n) * sum_{k=1}^{n} c = c.

      generalized_risk_k = (k/n) * c.
      AUGRC = (1/n) * sum_{k=1}^{n} (k/n) * c
            = (c/n^2) * sum_{k=1}^{n} k
            = (c/n^2) * n*(n+1)/2
            = c*(n+1)/(2n).

    For c=2, n=4: AURC=2.0, AUGRC=2*5/(2*4)=10/8=1.25.
    """

    def test_aurc_constant(self) -> None:
        c = 2.0
        n = 4
        risk = np.full(n, c)
        score = np.array([3.0, 1.0, 4.0, 2.0])  # arbitrary scores
        assert aurc(risk, score) == pytest.approx(c)

    def test_augrc_constant(self) -> None:
        c = 2.0
        n = 4
        risk = np.full(n, c)
        score = np.array([3.0, 1.0, 4.0, 2.0])
        expected_augrc = c * (n + 1) / (2 * n)  # = 1.25
        assert augrc(risk, score) == pytest.approx(expected_augrc)

    def test_invariant_to_score_order(self) -> None:
        """Any score ordering produces identical AURC/AUGRC when risk is constant."""
        c = 5.0
        n = 6
        risk = np.full(n, c)
        for scores in [
            np.arange(n, dtype=float),
            np.arange(n, dtype=float)[::-1],
            np.zeros(n),
        ]:
            assert aurc(risk, scores) == pytest.approx(c)
            assert augrc(risk, scores) == pytest.approx(c * (n + 1) / (2 * n))


# ---------------------------------------------------------------------------
# Tie invariance (headline test)
# ---------------------------------------------------------------------------


class TestTieInvariance:
    """Items with equal score MUST produce identical AURC and AUGRC regardless of
    intra-tie ordering.  The tie convention replaces each item's risk with the
    group-mean risk before forming cumulative sums.

    Example: risks=[1,3,2,4], scores=[0,0,1,1]
      Tie group 1 (score=0): items with risks [1,3] → mean=2.0
      Tie group 2 (score=1): items with risks [2,4] → mean=3.0

    After tie-averaging, effective risks in sorted order: [2, 2, 3, 3]

    selective_risk:
      k=1 → 2/1 = 2.0
      k=2 → 4/2 = 2.0
      k=3 → 7/3 ≈ 2.333...
      k=4 → 10/4 = 2.5

    AURC = (2.0 + 2.0 + 7/3 + 2.5) / 4 = (4.0 + 2.333... + 2.5) / 4
         = (2 + 2 + 7/3 + 5/2) / 4
         = (24/12 + 24/12 + 28/12 + 30/12) / 4
         = (106/12) / 4
         = 106 / 48
         ≈ 2.2083...
    """

    RISKS = np.array([1.0, 3.0, 2.0, 4.0])
    SCORES = np.array([0.0, 0.0, 1.0, 1.0])
    # Swapped order within each tie group
    RISKS_SWAPPED = np.array([3.0, 1.0, 4.0, 2.0])
    SCORES_SWAPPED = np.array([0.0, 0.0, 1.0, 1.0])

    EXPECTED_AURC = (2.0 + 2.0 + 7 / 3 + 2.5) / 4  # ≈ 2.2083...

    def test_aurc_invariant_to_intra_tie_order(self) -> None:
        a1 = aurc(self.RISKS, self.SCORES)
        a2 = aurc(self.RISKS_SWAPPED, self.SCORES_SWAPPED)
        assert a1 == pytest.approx(a2)

    def test_augrc_invariant_to_intra_tie_order(self) -> None:
        ag1 = augrc(self.RISKS, self.SCORES)
        ag2 = augrc(self.RISKS_SWAPPED, self.SCORES_SWAPPED)
        assert ag1 == pytest.approx(ag2)

    def test_aurc_expected_value(self) -> None:
        """AURC equals the hand-computed value with the tie convention applied."""
        assert aurc(self.RISKS, self.SCORES) == pytest.approx(self.EXPECTED_AURC)

    def test_curve_uses_group_means(self) -> None:
        """risk_coverage_curve returns group-mean risks within each tie group."""
        cov, sel = risk_coverage_curve(self.RISKS, self.SCORES)
        # After tie-averaging, effective risks: [2,2,3,3]
        # selective_risk:
        np.testing.assert_allclose(sel[:2], [2.0, 2.0])
        np.testing.assert_allclose(sel[2], 7 / 3, rtol=1e-10)
        np.testing.assert_allclose(sel[3], 2.5)

    def test_all_equal_scores(self) -> None:
        """All items sharing a single score: AURC == mean(risk) for any ordering."""
        risk = np.array([1.0, 5.0, 3.0])
        score = np.zeros(3)
        # tie-mean = 3.0; selective_risk_k = 3.0 for k=1,2,3 → AURC=3.0
        assert aurc(risk, score) == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# AURC vs AUGRC relationship
# ---------------------------------------------------------------------------


class TestAurcAugrcRelationship:
    """Verify generalized_risk_k = selective_risk_k * coverage_k per k.

    Using perfect ranking on [0,1,2,3]:
    k=1: sel=0.0, cov=0.25, gen=0.0
    k=2: sel=0.5, cov=0.50, gen=0.25
    k=3: sel=1.0, cov=0.75, gen=0.75
    k=4: sel=1.5, cov=1.00, gen=1.50
    """

    def test_generalized_risk_per_k(self) -> None:
        risk = np.array([0.0, 1.0, 2.0, 3.0])
        score = risk.copy()  # perfect order
        cov, sel = risk_coverage_curve(risk, score)
        # generalized_risk_k = sel_k * cov_k = (1/k)*sum * (k/n) = (1/n)*sum
        # So generalized = sel * cov
        gen_expected = sel * cov
        np.testing.assert_allclose(gen_expected, [0.0, 0.25, 0.75, 1.50])

    def test_augrc_from_coverage_curve(self) -> None:
        """AUGRC == mean of (sel * cov) over k."""
        risk = np.array([0.0, 1.0, 2.0, 3.0])
        score = risk.copy()
        cov, sel = risk_coverage_curve(risk, score)
        augrc_from_curve = float(np.mean(sel * cov))
        assert augrc(risk, score) == pytest.approx(augrc_from_curve)

    def test_aurc_from_coverage_curve(self) -> None:
        """AURC == mean of sel over k == (1/n)*sum sel_k."""
        risk = np.array([0.0, 1.0, 2.0, 3.0])
        score = risk.copy()
        cov, sel = risk_coverage_curve(risk, score)
        aurc_from_curve = float(np.mean(sel))
        assert aurc(risk, score) == pytest.approx(aurc_from_curve)


# ---------------------------------------------------------------------------
# risk_at_coverage
# ---------------------------------------------------------------------------


class TestRiskAtCoverage:
    """risk_at_coverage(c) returns selective_risk at k=max(1, round(c*n))."""

    RISKS = np.array([0.0, 1.0, 2.0, 3.0])
    SCORES = np.array([0.0, 1.0, 2.0, 3.0])  # perfect order

    def test_c_equal_one_returns_mean(self) -> None:
        """c=1.0 → k=n → selective_risk = mean(all risks)."""
        result = risk_at_coverage(self.RISKS, self.SCORES, 1.0)
        assert result == pytest.approx(np.mean(self.RISKS))  # 1.5

    def test_c_half(self) -> None:
        """c=0.5 → k=round(0.5*4)=2 → selective_risk = mean([0,1]) = 0.5."""
        result = risk_at_coverage(self.RISKS, self.SCORES, 0.5)
        assert result == pytest.approx(0.5)

    def test_c_quarter(self) -> None:
        """c=0.25 → k=round(0.25*4)=1 → selective_risk = 0.0."""
        result = risk_at_coverage(self.RISKS, self.SCORES, 0.25)
        assert result == pytest.approx(0.0)

    def test_c_zero_raises(self) -> None:
        with pytest.raises(MetricError):
            risk_at_coverage(self.RISKS, self.SCORES, 0.0)

    def test_c_negative_raises(self) -> None:
        with pytest.raises(MetricError):
            risk_at_coverage(self.RISKS, self.SCORES, -0.1)

    def test_c_greater_than_one_raises(self) -> None:
        with pytest.raises(MetricError):
            risk_at_coverage(self.RISKS, self.SCORES, 1.1)

    def test_registered_coverage_points_sensible(self) -> None:
        """All registered coverage points return finite, non-negative values."""
        for c in REGISTERED_COVERAGE_POINTS:
            val = risk_at_coverage(self.RISKS, self.SCORES, c)
            assert np.isfinite(val)
            assert val >= 0.0

    def test_registered_coverage_points_tuple(self) -> None:
        assert REGISTERED_COVERAGE_POINTS == (0.25, 0.50, 0.70, 1.00)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_arrays_raise(self) -> None:
        with pytest.raises(MetricError):
            aurc(np.array([]), np.array([]))

    def test_unequal_lengths_raise(self) -> None:
        with pytest.raises(MetricError):
            aurc(np.array([1.0, 2.0]), np.array([1.0]))

    def test_nan_risk_raises(self) -> None:
        with pytest.raises(MetricError):
            aurc(np.array([1.0, np.nan]), np.array([0.0, 1.0]))

    def test_inf_risk_raises(self) -> None:
        with pytest.raises(MetricError):
            aurc(np.array([1.0, np.inf]), np.array([0.0, 1.0]))

    def test_nan_score_raises(self) -> None:
        with pytest.raises(MetricError):
            aurc(np.array([1.0, 2.0]), np.array([np.nan, 1.0]))

    def test_inf_score_raises(self) -> None:
        with pytest.raises(MetricError):
            aurc(np.array([1.0, 2.0]), np.array([np.inf, 1.0]))

    def test_negative_risk_raises(self) -> None:
        with pytest.raises(MetricError):
            aurc(np.array([-1.0, 2.0]), np.array([0.0, 1.0]))

    def test_single_item(self) -> None:
        """n=1: AURC == risk[0]; AUGRC == risk[0] * 1.0."""
        r = np.array([3.5])
        s = np.array([0.0])
        assert aurc(r, s) == pytest.approx(3.5)
        assert augrc(r, s) == pytest.approx(3.5)

    def test_zero_risk_allowed(self) -> None:
        """risk=0 is valid (no negative-risk violation)."""
        r = np.array([0.0, 0.0])
        s = np.array([0.0, 1.0])
        assert aurc(r, s) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Bootstrap resampling (duplicated rows)
# ---------------------------------------------------------------------------


class TestBootstrapResample:
    """Passing a bootstrap resample (repeated identical rows) must not crash."""

    def test_duplicated_rows_finite(self) -> None:
        risk_base = np.array([1.0, 2.0, 3.0])
        score_base = np.array([0.1, 0.5, 0.9])
        # Simulate a bootstrap resample: duplicate the first item twice
        risk_boot = np.concatenate([risk_base[[0, 0]], risk_base])
        score_boot = np.concatenate([score_base[[0, 0]], score_base])
        val = aurc(risk_boot, score_boot)
        assert np.isfinite(val)
        assert val >= 0.0

    def test_all_identical_rows(self) -> None:
        """All items identical (extreme bootstrap corner): no crash, no div-by-zero."""
        risk = np.full(5, 2.0)
        score = np.full(5, 1.0)  # all same score → one giant tie group
        val = aurc(risk, score)
        assert np.isfinite(val)
        assert val == pytest.approx(2.0)  # constant-risk case


# ---------------------------------------------------------------------------
# normalize_by_mean
# ---------------------------------------------------------------------------


class TestNormalizeByMean:
    def test_divides_by_mean(self) -> None:
        risk = np.array([1.0, 2.0, 3.0])
        normed = normalize_by_mean(risk)
        mean_ = np.mean(risk)  # 2.0
        np.testing.assert_allclose(normed, risk / mean_)

    def test_rank_order_preserved(self) -> None:
        risk = np.array([3.0, 1.0, 5.0, 2.0])
        normed = normalize_by_mean(risk)
        assert list(np.argsort(normed)) == list(np.argsort(risk))

    def test_aurc_linearity(self) -> None:
        """AURC(normalized) == AURC(raw) / mean(raw)."""
        risk = np.array([0.0, 1.0, 2.0, 3.0])
        score = risk.copy()
        normed = normalize_by_mean(risk)
        mean_ = float(np.mean(risk))
        # AURC is linear in risk, so AURC(risk/mean) = AURC(risk)/mean
        assert aurc(normed, score) == pytest.approx(aurc(risk, score) / mean_)

    def test_zero_mean_raises(self) -> None:
        with pytest.raises(MetricError):
            normalize_by_mean(np.array([0.0, 0.0, 0.0]))

    def test_negative_mean_raises(self) -> None:
        """Should not arise with non-negative risks, but guard anyway."""
        # Artificially pass array with negative mean — library should raise
        with pytest.raises(MetricError):
            normalize_by_mean(np.array([-2.0, -3.0]))

    def test_output_mean_is_one(self) -> None:
        risk = np.array([2.0, 4.0, 6.0])
        normed = normalize_by_mean(risk)
        assert float(np.mean(normed)) == pytest.approx(1.0)
