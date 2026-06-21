"""Tests for alive.gate.recoverability — TrustGate scorers.

These tests are written FIRST (TDD).  They verify:
- feature_knn_mean_distance correctness (brute-force comparison)
- local_residual returns median neighbor error
- k > len(refs) or k < 1 raises GateError
- LOO self-exclusion: scoring a reference item with loo=True excludes
  the self (zero distance) from its neighbor set
- ECDF normalization: correct fractions, in [0,1], monotone, ties via <=
- Gate combination: score = w*R1n + (1-w)*R4n
- w=1 → pure R1n; w→0 → residual-dominated
- w<=0 → GateError; w>1 → GateError
- Feature-scale invariance after standardization (headline test)
- TrustGate.fit stores refs and precomputes loo arrays
- TrustGate.score_loo returns LOO scores for reference items
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.gate.recoverability import (
    GateError,
    TrustGate,
    ecdf_normalize,
    feature_knn_mean_distance,
    local_residual,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _brute_knn_mean_dist(queries: np.ndarray, refs: np.ndarray, k: int) -> np.ndarray:
    """Reference brute-force kNN mean distance (Euclidean)."""
    result = np.empty(len(queries))
    for i, q in enumerate(queries):
        dists = np.sqrt(np.sum((refs - q) ** 2, axis=1))
        idx = np.argsort(dists)[:k]
        result[i] = dists[idx].mean()
    return result


def _brute_local_residual(
    queries: np.ndarray, refs: np.ndarray, ref_errors: np.ndarray, k: int
) -> np.ndarray:
    """Reference brute-force local residual (median neighbor error)."""
    result = np.empty(len(queries))
    for i, q in enumerate(queries):
        dists = np.sqrt(np.sum((refs - q) ** 2, axis=1))
        idx = np.argsort(dists)[:k]
        result[i] = np.median(ref_errors[idx])
    return result


# ---------------------------------------------------------------------------
# feature_knn_mean_distance
# ---------------------------------------------------------------------------


class TestFeatureKnnMeanDistance:
    def test_matches_brute_force_k1(self) -> None:
        rng = np.random.default_rng(0)
        refs = rng.standard_normal((10, 4))
        queries = rng.standard_normal((5, 4))
        k = 1
        expected = _brute_knn_mean_dist(queries, refs, k)
        got = feature_knn_mean_distance(queries, refs, k)
        np.testing.assert_allclose(got, expected, rtol=1e-10)

    def test_matches_brute_force_k3(self) -> None:
        rng = np.random.default_rng(1)
        refs = rng.standard_normal((20, 6))
        queries = rng.standard_normal((8, 6))
        k = 3
        expected = _brute_knn_mean_dist(queries, refs, k)
        got = feature_knn_mean_distance(queries, refs, k)
        np.testing.assert_allclose(got, expected, rtol=1e-10)

    def test_k_equals_n_refs(self) -> None:
        """k == len(refs): include all refs."""
        rng = np.random.default_rng(2)
        refs = rng.standard_normal((5, 3))
        queries = rng.standard_normal((3, 3))
        k = 5
        got = feature_knn_mean_distance(queries, refs, k)
        expected = _brute_knn_mean_dist(queries, refs, k)
        np.testing.assert_allclose(got, expected, rtol=1e-10)

    def test_raises_k_greater_than_refs(self) -> None:
        refs = np.ones((5, 3))
        queries = np.ones((2, 3))
        with pytest.raises(GateError, match="k"):
            feature_knn_mean_distance(queries, refs, k=6)

    def test_raises_k_less_than_1(self) -> None:
        refs = np.ones((5, 3))
        queries = np.ones((2, 3))
        with pytest.raises(GateError, match="k"):
            feature_knn_mean_distance(queries, refs, k=0)

    def test_raises_k_negative(self) -> None:
        refs = np.ones((5, 3))
        queries = np.ones((2, 3))
        with pytest.raises(GateError):
            feature_knn_mean_distance(queries, refs, k=-1)

    # --- LOO boundary tests ---

    def test_loo_k_equals_n_refs_raises_gate_error(self) -> None:
        """In LOO mode, k == n_refs is out of range: only n_refs-1 valid neighbors exist."""
        rng = np.random.default_rng(50)
        refs = rng.standard_normal((5, 3))
        with pytest.raises(GateError, match="k"):
            feature_knn_mean_distance(refs, refs, k=5, loo=True)

    def test_loo_k_equals_n_refs_minus_1_finite(self) -> None:
        """In LOO mode, k == n_refs-1 is the maximum valid k; result must be finite."""
        rng = np.random.default_rng(51)
        refs = rng.standard_normal((5, 3))
        k = 4  # n_refs - 1
        result = feature_knn_mean_distance(refs, refs, k=k, loo=True)
        assert result.shape == (5,)
        assert np.all(np.isfinite(result)), f"Expected finite values, got {result}"

    def test_loo_k_equals_n_refs_minus_1_equals_brute_force(self) -> None:
        """LOO k=n_refs-1 matches brute-force mean distance to all OTHER items."""
        rng = np.random.default_rng(52)
        n = 5
        refs = rng.standard_normal((n, 3))
        k = n - 1  # use all others

        result = feature_knn_mean_distance(refs, refs, k=k, loo=True)

        # Brute-force: for each item, mean distance to all OTHER items
        expected = np.empty(n)
        for i in range(n):
            others = np.delete(refs, i, axis=0)
            dists = np.sqrt(np.sum((others - refs[i]) ** 2, axis=1))
            expected[i] = dists.mean()

        np.testing.assert_allclose(result, expected, rtol=1e-10)

    def test_non_loo_k_equals_n_refs_ok(self) -> None:
        """Non-LOO k == n_refs is valid; should succeed and match brute-force."""
        rng = np.random.default_rng(53)
        refs = rng.standard_normal((5, 3))
        queries = rng.standard_normal((3, 3))
        k = 5
        result = feature_knn_mean_distance(queries, refs, k=k, loo=False)
        expected = _brute_knn_mean_dist(queries, refs, k)
        np.testing.assert_allclose(result, expected, rtol=1e-10)

    def test_output_shape(self) -> None:
        rng = np.random.default_rng(3)
        refs = rng.standard_normal((12, 5))
        queries = rng.standard_normal((7, 5))
        got = feature_knn_mean_distance(queries, refs, k=3)
        assert got.shape == (7,)

    def test_nonnegative(self) -> None:
        rng = np.random.default_rng(4)
        refs = rng.standard_normal((10, 4))
        queries = rng.standard_normal((5, 4))
        got = feature_knn_mean_distance(queries, refs, k=2)
        assert np.all(got >= 0)


# ---------------------------------------------------------------------------
# LOO self-exclusion
# ---------------------------------------------------------------------------


class TestLooSelfExclusion:
    def test_loo_excludes_self_distance(self) -> None:
        """With loo=True, scoring a reference item excludes its own zero distance.

        We construct refs such that item 0 is clearly closest to itself, then
        verify that LOO scores for item 0 do NOT include distance 0 (i.e. its
        LOO R1 equals the mean distance to its k nearest OTHER items).
        """
        # refs: item 0 at origin, others spread far away
        refs = np.array(
            [
                [0.0, 0.0],
                [10.0, 0.0],
                [0.0, 10.0],
                [10.0, 10.0],
                [5.0, 5.0],
            ]
        )
        k = 2
        # LOO R1 for item 0 (origin): exclude self (dist=0), take 2 nearest others
        # Distances from item 0 to others: 10, 10, sqrt(200)~14.14, sqrt(50)~7.07
        # Nearest 2 others: item 4 (dist~7.07), item 1 (dist=10)
        d4 = np.sqrt(50.0)
        d1 = 10.0
        expected_loo_r1_item0 = (d4 + d1) / 2.0

        loo_r1 = feature_knn_mean_distance(refs, refs, k, loo=True)
        assert loo_r1.shape == (5,)
        np.testing.assert_allclose(loo_r1[0], expected_loo_r1_item0, rtol=1e-10)

    def test_loo_non_loo_differ(self) -> None:
        """Non-LOO scoring of refs against themselves includes self (dist=0).

        The non-LOO mean distance for item 0 with k=2 would include the
        self-distance of 0, so it should be strictly less than the LOO version.
        """
        refs = np.array(
            [
                [0.0, 0.0],
                [10.0, 0.0],
                [0.0, 10.0],
                [10.0, 10.0],
                [5.0, 5.0],
            ]
        )
        k = 2
        # Non-LOO: k=2 nearest of ALL refs (including self, dist=0)
        # Item 0 nearest: self (0), item 4 (dist~7.07) → mean = 7.07/2
        d4 = np.sqrt(50.0)
        expected_non_loo_item0 = (0.0 + d4) / 2.0

        non_loo_r1 = feature_knn_mean_distance(refs, refs, k, loo=False)
        loo_r1 = feature_knn_mean_distance(refs, refs, k, loo=True)

        np.testing.assert_allclose(non_loo_r1[0], expected_non_loo_item0, rtol=1e-10)
        # LOO must be strictly greater (no zero distance in k neighbors)
        assert loo_r1[0] > non_loo_r1[0]

    def test_loo_local_residual_excludes_self(self) -> None:
        """local_residual with loo=True excludes the query's own self-error."""
        # Place ref 0 at origin with high error; others near origin with low error
        refs = np.array(
            [
                [0.0, 0.0],  # item 0: near-zero distances for itself
                [0.1, 0.0],  # close to item 0
                [0.0, 0.1],  # close to item 0
                [10.0, 0.0],  # far
                [10.0, 10.0],  # far
            ]
        )
        ref_errors = np.array([100.0, 1.0, 1.0, 1.0, 1.0])
        k = 2

        # LOO for item 0: exclude self. 2 nearest others: items 1,2 (errors 1,1)
        # → median = 1.0
        loo_r4 = local_residual(refs, refs, ref_errors, k, loo=True)
        np.testing.assert_allclose(loo_r4[0], 1.0, rtol=1e-10)

        # Non-LOO for item 0: 2 nearest are self (dist=0, error=100) + item 1 or 2
        # → median of [100, 1] = 50.5  (or [1, 100] → 50.5)
        non_loo_r4 = local_residual(refs, refs, ref_errors, k, loo=False)
        # Non-LOO item 0: self is one of the 2 nearest → error 100 included
        assert non_loo_r4[0] != loo_r4[0]


# ---------------------------------------------------------------------------
# local_residual
# ---------------------------------------------------------------------------


class TestLocalResidual:
    def test_matches_brute_force(self) -> None:
        rng = np.random.default_rng(5)
        refs = rng.standard_normal((15, 4))
        ref_errors = rng.uniform(0.0, 2.0, size=15)
        queries = rng.standard_normal((6, 4))
        k = 3
        expected = _brute_local_residual(queries, refs, ref_errors, k)
        got = local_residual(queries, refs, ref_errors, k)
        np.testing.assert_allclose(got, expected, rtol=1e-10)

    def test_k1_returns_nearest_error(self) -> None:
        refs = np.array([[0.0], [5.0], [10.0]])
        ref_errors = np.array([0.1, 0.5, 0.9])
        queries = np.array([[0.1]])  # nearest to refs[0]
        got = local_residual(queries, refs, ref_errors, k=1)
        np.testing.assert_allclose(got[0], 0.1, rtol=1e-10)

    def test_output_shape(self) -> None:
        rng = np.random.default_rng(6)
        refs = rng.standard_normal((10, 3))
        ref_errors = rng.uniform(size=10)
        queries = rng.standard_normal((4, 3))
        got = local_residual(queries, refs, ref_errors, k=2)
        assert got.shape == (4,)

    def test_raises_k_out_of_range(self) -> None:
        refs = np.ones((5, 3))
        ref_errors = np.ones(5)
        queries = np.ones((2, 3))
        with pytest.raises(GateError):
            local_residual(queries, refs, ref_errors, k=0)
        with pytest.raises(GateError):
            local_residual(queries, refs, ref_errors, k=6)

    def test_k_equals_n_refs_non_loo_ok(self) -> None:
        """Non-LOO k == n_refs is valid: median over all refs."""
        rng = np.random.default_rng(60)
        n = 5
        refs = rng.standard_normal((n, 3))
        ref_errors = rng.uniform(0.1, 2.0, size=n)
        queries = rng.standard_normal((3, 3))
        result = local_residual(queries, refs, ref_errors, k=n)
        expected = _brute_local_residual(queries, refs, ref_errors, k=n)
        np.testing.assert_allclose(result, expected, rtol=1e-10)

    def test_loo_k_equals_n_refs_raises_gate_error(self) -> None:
        """In LOO mode, k == n_refs is out of range (only n_refs-1 valid neighbors)."""
        rng = np.random.default_rng(61)
        n = 5
        refs = rng.standard_normal((n, 3))
        ref_errors = rng.uniform(0.1, 2.0, size=n)
        with pytest.raises(GateError, match="k"):
            local_residual(refs, refs, ref_errors, k=n, loo=True)

    def test_loo_k_equals_n_refs_minus_1_finite(self) -> None:
        """In LOO mode, k == n_refs-1 is valid; result must be finite."""
        rng = np.random.default_rng(62)
        n = 5
        refs = rng.standard_normal((n, 3))
        ref_errors = rng.uniform(0.1, 2.0, size=n)
        result = local_residual(refs, refs, ref_errors, k=n - 1, loo=True)
        assert result.shape == (n,)
        assert np.all(np.isfinite(result)), f"Expected finite values, got {result}"

    def test_loo_k_equals_n_refs_minus_1_equals_brute_force(self) -> None:
        """LOO k=n_refs-1 matches brute-force median of errors over all OTHER items."""
        rng = np.random.default_rng(63)
        n = 5
        refs = rng.standard_normal((n, 3))
        ref_errors = rng.uniform(0.1, 2.0, size=n)

        result = local_residual(refs, refs, ref_errors, k=n - 1, loo=True)

        expected = np.empty(n)
        for i in range(n):
            other_errors = np.delete(ref_errors, i)
            expected[i] = np.median(other_errors)

        np.testing.assert_allclose(result, expected, rtol=1e-10)


# ---------------------------------------------------------------------------
# ecdf_normalize
# ---------------------------------------------------------------------------


class TestEcdfNormalize:
    def test_fraction_of_reference_leq(self) -> None:
        """ecdf_normalize(v, ref) = fraction of ref items <= v."""
        reference = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        values = np.array([0.0, 1.0, 2.5, 5.0, 6.0])
        expected = np.array([0.0, 0.2, 0.4, 1.0, 1.0])
        got = ecdf_normalize(values, reference)
        np.testing.assert_allclose(got, expected, rtol=1e-10)

    def test_range_zero_to_one(self) -> None:
        rng = np.random.default_rng(7)
        reference = rng.standard_normal(50)
        values = rng.standard_normal(20)
        got = ecdf_normalize(values, reference)
        assert np.all(got >= 0.0)
        assert np.all(got <= 1.0)

    def test_monotone(self) -> None:
        rng = np.random.default_rng(8)
        reference = rng.standard_normal(30)
        values = np.sort(rng.standard_normal(10))
        got = ecdf_normalize(values, reference)
        # Monotone non-decreasing
        assert np.all(np.diff(got) >= 0)

    def test_ties_counted_with_leq(self) -> None:
        """Ties: fraction counts all references <= value."""
        reference = np.array([1.0, 1.0, 1.0, 2.0])
        values = np.array([1.0])
        # 3 out of 4 refs are <= 1.0
        expected = np.array([3.0 / 4.0])
        got = ecdf_normalize(values, reference)
        np.testing.assert_allclose(got, expected, rtol=1e-10)

    def test_value_below_all_reference(self) -> None:
        reference = np.array([5.0, 6.0, 7.0])
        values = np.array([0.0])
        got = ecdf_normalize(values, reference)
        np.testing.assert_allclose(got[0], 0.0, rtol=1e-10)

    def test_value_above_all_reference(self) -> None:
        reference = np.array([1.0, 2.0, 3.0])
        values = np.array([100.0])
        got = ecdf_normalize(values, reference)
        np.testing.assert_allclose(got[0], 1.0, rtol=1e-10)

    def test_output_shape(self) -> None:
        reference = np.linspace(0, 1, 20)
        values = np.array([0.1, 0.5, 0.9])
        got = ecdf_normalize(values, reference)
        assert got.shape == (3,)

    def test_single_reference_item(self) -> None:
        reference = np.array([0.5])
        values = np.array([0.0, 0.5, 1.0])
        expected = np.array([0.0, 1.0, 1.0])
        got = ecdf_normalize(values, reference)
        np.testing.assert_allclose(got, expected, rtol=1e-10)


# ---------------------------------------------------------------------------
# TrustGate — gate combination and API
# ---------------------------------------------------------------------------


class TestTrustGate:
    def _make_gate(
        self, n_refs: int = 20, feat_dim: int = 4, k: int = 3, w: float = 0.5, seed: int = 0
    ) -> TrustGate:
        rng = np.random.default_rng(seed)
        ref_features = rng.standard_normal((n_refs, feat_dim))
        ref_errors = rng.uniform(0.1, 2.0, size=n_refs)
        return TrustGate.fit(ref_features, ref_errors, k=k, w=w)

    def test_fit_stores_refs(self) -> None:
        gate = self._make_gate()
        assert gate.ref_features is not None
        assert gate.ref_errors is not None
        assert gate.ref_features.shape[0] == 20
        assert gate.ref_errors.shape[0] == 20

    def test_fit_precomputes_loo_arrays(self) -> None:
        gate = self._make_gate()
        assert gate.loo_r1.shape == (20,)
        assert gate.loo_r4.shape == (20,)

    def test_score_shape(self) -> None:
        gate = self._make_gate(n_refs=20, feat_dim=4, k=3)
        rng = np.random.default_rng(99)
        queries = rng.standard_normal((7, 4))
        scores = gate.score(queries)
        assert scores.shape == (7,)

    def test_score_range(self) -> None:
        """Scores are ECDF-normalized weighted combos, so in [0, 1]."""
        gate = self._make_gate(n_refs=30, feat_dim=5, k=4)
        rng = np.random.default_rng(10)
        queries = rng.standard_normal((15, 5))
        scores = gate.score(queries)
        # Weighted combo of two [0,1] values is in [0,1]
        assert np.all(scores >= 0.0)
        assert np.all(scores <= 1.0)

    def test_w1_equals_pure_r1n(self) -> None:
        """With w=1, gate score == ecdf_normalize(R1, loo_r1) (pure feature-distance ECDF)."""
        rng = np.random.default_rng(20)
        ref_features = rng.standard_normal((15, 4))
        ref_errors = rng.uniform(0.1, 2.0, size=15)
        gate = TrustGate.fit(ref_features, ref_errors, k=3, w=1.0)

        queries = rng.standard_normal((5, 4))
        scores = gate.score(queries)

        # Manually compute pure R1n
        r1 = feature_knn_mean_distance(queries, ref_features, k=3)
        r1n = ecdf_normalize(r1, gate.loo_r1)
        np.testing.assert_allclose(scores, r1n, rtol=1e-10)

    def test_w_small_formula_is_r4n_dominated(self) -> None:
        """With w close to 0, score exactly equals w*R1n + (1-w)*R4n (R4n-dominated)."""
        rng = np.random.default_rng(21)
        ref_features = rng.standard_normal((20, 4))
        ref_errors = rng.uniform(0.1, 2.0, size=20)
        w_small = 0.01
        gate = TrustGate.fit(ref_features, ref_errors, k=3, w=w_small)

        queries = rng.standard_normal((6, 4))
        scores = gate.score(queries)

        # Pure R4n component
        r4 = local_residual(queries, ref_features, ref_errors, k=3)
        r4n = ecdf_normalize(r4, gate.loo_r4)
        # Score should be very close to R4n (within the weight margin)
        np.testing.assert_allclose(
            scores,
            w_small
            * ecdf_normalize(feature_knn_mean_distance(queries, ref_features, k=3), gate.loo_r1)
            + (1 - w_small) * r4n,
            rtol=1e-10,
        )

    def test_w_zero_raises(self) -> None:
        rng = np.random.default_rng(22)
        ref_features = rng.standard_normal((10, 3))
        ref_errors = rng.uniform(size=10)
        with pytest.raises(GateError, match="w"):
            TrustGate.fit(ref_features, ref_errors, k=2, w=0.0)

    def test_w_negative_raises(self) -> None:
        rng = np.random.default_rng(23)
        ref_features = rng.standard_normal((10, 3))
        ref_errors = rng.uniform(size=10)
        with pytest.raises(GateError):
            TrustGate.fit(ref_features, ref_errors, k=2, w=-0.5)

    def test_w_greater_than_1_raises(self) -> None:
        rng = np.random.default_rng(24)
        ref_features = rng.standard_normal((10, 3))
        ref_errors = rng.uniform(size=10)
        with pytest.raises(GateError, match="w"):
            TrustGate.fit(ref_features, ref_errors, k=2, w=1.1)

    def test_fit_k_equals_n_refs_raises_gate_error(self) -> None:
        """TrustGate.fit uses LOO internally; k==n_refs is out of LOO range → GateError."""
        rng = np.random.default_rng(25)
        n = 10
        ref_features = rng.standard_normal((n, 3))
        ref_errors = rng.uniform(size=n)
        with pytest.raises(GateError, match="k"):
            TrustGate.fit(ref_features, ref_errors, k=n, w=0.5)

    def test_gate_combination_formula(self) -> None:
        """score = w*R1n + (1-w)*R4n verified manually for a small example."""
        rng = np.random.default_rng(30)
        n_refs = 12
        feat_dim = 3
        k = 2
        w = 0.6
        ref_features = rng.standard_normal((n_refs, feat_dim))
        ref_errors = rng.uniform(0.1, 1.5, size=n_refs)
        gate = TrustGate.fit(ref_features, ref_errors, k=k, w=w)

        queries = rng.standard_normal((4, feat_dim))
        scores = gate.score(queries)

        r1 = feature_knn_mean_distance(queries, ref_features, k)
        r4 = local_residual(queries, ref_features, ref_errors, k)
        r1n = ecdf_normalize(r1, gate.loo_r1)
        r4n = ecdf_normalize(r4, gate.loo_r4)
        expected = w * r1n + (1 - w) * r4n

        np.testing.assert_allclose(scores, expected, rtol=1e-10)

    def test_score_loo_shape(self) -> None:
        gate = self._make_gate(n_refs=15)
        loo_scores = gate.score_loo()
        assert loo_scores.shape == (15,)

    def test_score_loo_range(self) -> None:
        gate = self._make_gate(n_refs=20)
        loo_scores = gate.score_loo()
        assert np.all(loo_scores >= 0.0)
        assert np.all(loo_scores <= 1.0)

    def test_score_loo_uses_loo_computation(self) -> None:
        """score_loo() returns w*ECDF(LOO-R1, loo_r1) + (1-w)*ECDF(LOO-R4, loo_r4)."""
        rng = np.random.default_rng(31)
        n_refs = 10
        feat_dim = 3
        k = 2
        w = 0.4
        ref_features = rng.standard_normal((n_refs, feat_dim))
        ref_errors = rng.uniform(0.1, 1.5, size=n_refs)
        gate = TrustGate.fit(ref_features, ref_errors, k=k, w=w)

        loo_scores = gate.score_loo()

        # LOO R1 and R4 should equal gate.loo_r1 and gate.loo_r4 (they're the same computation)
        r1n = ecdf_normalize(gate.loo_r1, gate.loo_r1)
        r4n = ecdf_normalize(gate.loo_r4, gate.loo_r4)
        expected = w * r1n + (1 - w) * r4n
        np.testing.assert_allclose(loo_scores, expected, rtol=1e-10)


# ---------------------------------------------------------------------------
# Feature-scale invariance after standardization (headline test)
# ---------------------------------------------------------------------------


class TestFeatureScaleInvariance:
    def test_rescaled_raw_features_same_gate_scores(self) -> None:
        """Headline: rescaling raw features then re-standardizing → identical gate scores.

        Standardized features are scale-free, so multiplying the raw features
        by a constant before standardization must not change the gate scores.
        """
        rng = np.random.default_rng(42)
        n_refs = 20
        feat_dim = 5
        raw_ref = rng.standard_normal((n_refs, feat_dim))
        ref_errors = rng.uniform(0.1, 2.0, size=n_refs)

        raw_query = rng.standard_normal((6, feat_dim))

        def standardize(matrix: np.ndarray, fit_on: np.ndarray) -> np.ndarray:
            mean = fit_on.mean(axis=0)
            std = fit_on.std(axis=0, ddof=1)
            std = np.where(std == 0, 1.0, std)
            return (matrix - mean) / std

        # Standardize refs using themselves as training set
        std_ref = standardize(raw_ref, raw_ref)
        std_query = standardize(raw_query, raw_ref)

        # Scale raw features by a constant before re-standardizing
        scale = 17.3
        scaled_raw_ref = raw_ref * scale
        scaled_raw_query = raw_query * scale
        std_ref_scaled = standardize(scaled_raw_ref, scaled_raw_ref)
        std_query_scaled = standardize(scaled_raw_query, scaled_raw_ref)

        k = 3
        w = 0.5

        gate1 = TrustGate.fit(std_ref, ref_errors, k=k, w=w)
        gate2 = TrustGate.fit(std_ref_scaled, ref_errors, k=k, w=w)

        scores1 = gate1.score(std_query)
        scores2 = gate2.score(std_query_scaled)

        np.testing.assert_allclose(scores1, scores2, rtol=1e-6, atol=1e-10)
