"""Tests for alive.baselines.uq — preregistered UQ comparators.

These tests are written FIRST (TDD).  They verify:
- NearestFeatureDistance: k=1 special case of feature_knn_mean_distance
- EnsembleDisagreement: higher spread → higher score; identical → ~0; deterministic
- RidgeErrorRegressor: predicts higher for high-error refs
- GbmErrorRegressor: deterministic given seed; two fits → identical scores
- ResidualOnly: distinct class, equal to R4-only computation
- TrustGate.fit(w=0) raises GateError; ResidualOnly does not use TrustGate(w=0)
- Identical method budgets: all comparators consume same ref_features/ref_errors
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.baselines.uq import (
    EnsembleDisagreement,
    GbmErrorRegressor,
    NearestFeatureDistance,
    ResidualOnly,
    RidgeErrorRegressor,
)
from alive.gate.recoverability import (
    GateError,
    TrustGate,
    ecdf_normalize,
    feature_knn_mean_distance,
    local_residual,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_data(
    n_refs: int = 20,
    feat_dim: int = 5,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    ref_features = rng.standard_normal((n_refs, feat_dim))
    ref_errors = rng.uniform(0.1, 3.0, size=n_refs)
    return ref_features, ref_errors


# ---------------------------------------------------------------------------
# NearestFeatureDistance
# ---------------------------------------------------------------------------


class TestNearestFeatureDistance:
    def test_matches_k1_feature_knn(self) -> None:
        ref_features, _ = _make_data()
        rng = np.random.default_rng(1)
        queries = rng.standard_normal((6, 5))

        nfd = NearestFeatureDistance()
        nfd.fit(ref_features, _[: len(ref_features)])

        got = nfd.score(queries)
        expected = feature_knn_mean_distance(queries, ref_features, k=1)
        np.testing.assert_allclose(got, expected, rtol=1e-10)

    def test_output_shape(self) -> None:
        ref_features, ref_errors = _make_data()
        nfd = NearestFeatureDistance()
        nfd.fit(ref_features, ref_errors)
        rng = np.random.default_rng(2)
        queries = rng.standard_normal((8, 5))
        got = nfd.score(queries)
        assert got.shape == (8,)

    def test_nonnegative(self) -> None:
        ref_features, ref_errors = _make_data()
        nfd = NearestFeatureDistance()
        nfd.fit(ref_features, ref_errors)
        rng = np.random.default_rng(3)
        queries = rng.standard_normal((5, 5))
        got = nfd.score(queries)
        assert np.all(got >= 0)

    def test_identical_query_to_ref_zero(self) -> None:
        """A query identical to a reference point has zero distance to it."""
        ref_features, ref_errors = _make_data(n_refs=10)
        nfd = NearestFeatureDistance()
        nfd.fit(ref_features, ref_errors)
        # Query is ref[0] itself
        score = nfd.score(ref_features[:1])
        np.testing.assert_allclose(score[0], 0.0, atol=1e-12)

    def test_higher_score_more_distant(self) -> None:
        """Point far from all references has higher score than one near a reference."""
        ref_features, ref_errors = _make_data(n_refs=10, feat_dim=2)
        nfd = NearestFeatureDistance()
        nfd.fit(ref_features, ref_errors)
        near_query = ref_features[:1] + 0.001  # tiny offset
        far_query = np.array([[1000.0, 1000.0]])
        near_score = nfd.score(near_query)[0]
        far_score = nfd.score(far_query)[0]
        assert far_score > near_score


# ---------------------------------------------------------------------------
# EnsembleDisagreement
# ---------------------------------------------------------------------------


class TestEnsembleDisagreement:
    def _make_ensemble_means(
        self,
        n_queries: int,
        n_members: int,
        pca_dims: int,
        spread: float,
        seed: int = 0,
    ) -> np.ndarray:
        """Create (n_queries, n_members, pca_dims) with controllable spread."""
        rng = np.random.default_rng(seed)
        center = rng.standard_normal((n_queries, 1, pca_dims))
        offsets = rng.standard_normal((n_queries, n_members, pca_dims)) * spread
        return center + offsets

    def test_identical_members_near_zero(self) -> None:
        """When all ensemble members agree, disagreement score should be ~0."""
        rng = np.random.default_rng(5)
        means = rng.standard_normal((6, 1, 4))
        # Repeat identical member across n_members
        identical_means = np.repeat(means, 5, axis=1)  # (6, 5, 4)

        ed = EnsembleDisagreement()
        ed.fit(np.zeros((10, 4)), np.zeros(10))  # fit args unused for score
        scores = ed.score(identical_means)
        np.testing.assert_allclose(scores, 0.0, atol=1e-10)

    def test_higher_spread_higher_score(self) -> None:
        """Higher spread of ensemble members → higher disagreement score."""
        n_queries, n_members, pca_dims = 8, 5, 4
        high_spread = self._make_ensemble_means(n_queries, n_members, pca_dims, spread=5.0)
        low_spread = self._make_ensemble_means(n_queries, n_members, pca_dims, spread=0.01)

        ed = EnsembleDisagreement()
        ed.fit(np.zeros((10, 4)), np.zeros(10))
        high_scores = ed.score(high_spread)
        low_scores = ed.score(low_spread)

        assert np.all(high_scores > low_scores)

    def test_output_shape(self) -> None:
        n_queries, n_members, pca_dims = 7, 4, 3
        means = self._make_ensemble_means(n_queries, n_members, pca_dims, spread=1.0)
        ed = EnsembleDisagreement()
        ed.fit(np.zeros((5, 3)), np.zeros(5))
        scores = ed.score(means)
        assert scores.shape == (n_queries,)

    def test_deterministic(self) -> None:
        """EnsembleDisagreement is purely deterministic (no random state)."""
        means = self._make_ensemble_means(5, 3, 4, spread=1.0)
        ed1 = EnsembleDisagreement()
        ed1.fit(np.zeros((5, 4)), np.zeros(5))
        ed2 = EnsembleDisagreement()
        ed2.fit(np.zeros((5, 4)), np.zeros(5))
        np.testing.assert_array_equal(ed1.score(means), ed2.score(means))

    def test_nonnegative(self) -> None:
        means = self._make_ensemble_means(6, 4, 3, spread=2.0)
        ed = EnsembleDisagreement()
        ed.fit(np.zeros((5, 3)), np.zeros(5))
        scores = ed.score(means)
        assert np.all(scores >= 0)

    def test_different_signature_documented(self) -> None:
        """EnsembleDisagreement.score takes ensemble_member_means, NOT query features."""
        # This just verifies the API accepts a 3-D array
        means = np.zeros((3, 4, 5))  # (n_queries, n_members, pca_dims)
        ed = EnsembleDisagreement()
        ed.fit(np.zeros((5, 5)), np.zeros(5))
        scores = ed.score(means)
        assert scores.shape == (3,)

    def test_score_before_fit_raises(self) -> None:
        """Calling score() before fit() must raise an error (fitted state guard)."""
        ed = EnsembleDisagreement()
        means = np.zeros((3, 2, 4))
        with pytest.raises((RuntimeError, AssertionError), match="fit"):
            ed.score(means)


# ---------------------------------------------------------------------------
# RidgeErrorRegressor
# ---------------------------------------------------------------------------


class TestRidgeErrorRegressor:
    def test_output_shape(self) -> None:
        ref_features, ref_errors = _make_data()
        reg = RidgeErrorRegressor()
        reg.fit(ref_features, ref_errors, alpha=1.0)
        rng = np.random.default_rng(10)
        queries = rng.standard_normal((7, 5))
        got = reg.score(queries)
        assert got.shape == (7,)

    def test_predicts_higher_near_high_error_refs(self) -> None:
        """Queries near high-error references get higher predicted errors."""
        rng = np.random.default_rng(11)
        n = 30
        feat_dim = 4

        # Create a feature space where dim 0 determines error
        ref_features = rng.standard_normal((n, feat_dim))
        # High error when dim 0 > 0; low error when dim 0 < 0
        ref_errors = np.where(ref_features[:, 0] > 0, 2.0, 0.1)

        reg = RidgeErrorRegressor()
        reg.fit(ref_features, ref_errors, alpha=0.01)

        # High-error query: dim 0 = 3 (far positive)
        high_err_query = np.array([[3.0, 0.0, 0.0, 0.0]])
        # Low-error query: dim 0 = -3 (far negative)
        low_err_query = np.array([[-3.0, 0.0, 0.0, 0.0]])

        high_score = reg.score(high_err_query)[0]
        low_score = reg.score(low_err_query)[0]
        assert high_score > low_score

    def test_deterministic(self) -> None:
        ref_features, ref_errors = _make_data()
        reg1 = RidgeErrorRegressor()
        reg1.fit(ref_features, ref_errors, alpha=1.0)
        reg2 = RidgeErrorRegressor()
        reg2.fit(ref_features, ref_errors, alpha=1.0)
        rng = np.random.default_rng(12)
        queries = rng.standard_normal((5, 5))
        np.testing.assert_array_equal(reg1.score(queries), reg2.score(queries))

    def test_consumes_same_inputs(self) -> None:
        """RidgeErrorRegressor fits on exactly (ref_features, ref_errors)."""
        ref_features, ref_errors = _make_data()
        reg = RidgeErrorRegressor()
        reg.fit(ref_features, ref_errors, alpha=1.0)
        # The regressor has stored the features/errors (just check it fitted without error)
        rng = np.random.default_rng(13)
        queries = rng.standard_normal((3, 5))
        scores = reg.score(queries)
        assert scores.shape == (3,)


# ---------------------------------------------------------------------------
# GbmErrorRegressor
# ---------------------------------------------------------------------------


class TestGbmErrorRegressor:
    def test_output_shape(self) -> None:
        ref_features, ref_errors = _make_data()
        reg = GbmErrorRegressor()
        reg.fit(ref_features, ref_errors, n_estimators=10, seed=0)
        rng = np.random.default_rng(20)
        queries = rng.standard_normal((6, 5))
        got = reg.score(queries)
        assert got.shape == (6,)

    def test_deterministic_given_seed(self) -> None:
        """Two GBM fits with same seed → identical scores."""
        ref_features, ref_errors = _make_data()
        rng = np.random.default_rng(21)
        queries = rng.standard_normal((5, 5))

        reg1 = GbmErrorRegressor()
        reg1.fit(ref_features, ref_errors, n_estimators=10, seed=42)

        reg2 = GbmErrorRegressor()
        reg2.fit(ref_features, ref_errors, n_estimators=10, seed=42)

        np.testing.assert_array_equal(reg1.score(queries), reg2.score(queries))

    def test_different_seeds_may_differ(self) -> None:
        """Different seeds produce different scores.

        We use a fixture with enough refs and estimators that two different seeds
        genuinely diverge.  The same-seed → identical case is in test_deterministic_given_seed.
        """
        # Use more refs and more estimators so random split choices actually diverge.
        ref_features, ref_errors = _make_data(n_refs=60, seed=100)
        rng = np.random.default_rng(22)
        queries = rng.standard_normal((10, 5))

        reg1 = GbmErrorRegressor()
        reg1.fit(ref_features, ref_errors, n_estimators=50, seed=1)
        reg2 = GbmErrorRegressor()
        reg2.fit(ref_features, ref_errors, n_estimators=50, seed=999)

        scores1 = reg1.score(queries)
        scores2 = reg2.score(queries)
        assert scores1.shape == scores2.shape
        # Different seeds must produce different predictions for this fixture.
        assert not np.array_equal(scores1, scores2), (
            "Expected different seeds to produce different GBM scores, but got identical results. "
            "Increase n_refs, n_estimators, or choose more distinct seeds."
        )

    def test_predicts_higher_near_high_error_refs(self) -> None:
        """GBM predicts higher score for queries near high-error references."""
        rng = np.random.default_rng(23)
        n = 40
        feat_dim = 4

        ref_features = rng.standard_normal((n, feat_dim))
        ref_errors = np.where(ref_features[:, 0] > 0, 2.0, 0.1)

        reg = GbmErrorRegressor()
        reg.fit(ref_features, ref_errors, n_estimators=50, seed=0)

        high_err_query = np.array([[3.0, 0.0, 0.0, 0.0]])
        low_err_query = np.array([[-3.0, 0.0, 0.0, 0.0]])

        assert reg.score(high_err_query)[0] > reg.score(low_err_query)[0]

    def test_consumes_same_inputs_as_ridge(self) -> None:
        """GbmErrorRegressor and RidgeErrorRegressor both consume same (features, errors)."""
        ref_features, ref_errors = _make_data()
        rng = np.random.default_rng(24)
        queries = rng.standard_normal((4, 5))

        gbm = GbmErrorRegressor()
        gbm.fit(ref_features, ref_errors, n_estimators=10, seed=0)

        ridge = RidgeErrorRegressor()
        ridge.fit(ref_features, ref_errors, alpha=1.0)

        # Both produce valid scores for the same queries
        gbm_scores = gbm.score(queries)
        ridge_scores = ridge.score(queries)
        assert gbm_scores.shape == ridge_scores.shape == (4,)


# ---------------------------------------------------------------------------
# ResidualOnly — mandatory ablation
# ---------------------------------------------------------------------------


class TestResidualOnly:
    def test_distinct_class_not_trust_gate(self) -> None:
        """ResidualOnly must be a distinct class, not produced by TrustGate(w=0)."""
        ref_features, ref_errors = _make_data()
        # TrustGate.fit(w=0) MUST raise GateError
        with pytest.raises(GateError):
            TrustGate.fit(ref_features, ref_errors, k=3, w=0.0)
        # ResidualOnly can be constructed independently
        ro = ResidualOnly()
        ro.fit(ref_features, ref_errors, k=3)
        rng = np.random.default_rng(30)
        queries = rng.standard_normal((5, 5))
        scores = ro.score(queries)
        assert scores.shape == (5,)

    def test_equals_r4_only_computation(self) -> None:
        """ResidualOnly score == ECDF-normalized local residual (R4 alone)."""
        ref_features, ref_errors = _make_data(n_refs=20)
        k = 3
        ro = ResidualOnly()
        ro.fit(ref_features, ref_errors, k=k)

        rng = np.random.default_rng(31)
        queries = rng.standard_normal((6, 5))
        ro_scores = ro.score(queries)

        # Manual R4-only: local_residual + ECDF against LOO r4
        loo_r4 = local_residual(ref_features, ref_features, ref_errors, k, loo=True)
        r4 = local_residual(queries, ref_features, ref_errors, k)
        r4n = ecdf_normalize(r4, loo_r4)

        np.testing.assert_allclose(ro_scores, r4n, rtol=1e-10)

    def test_output_shape(self) -> None:
        ref_features, ref_errors = _make_data()
        ro = ResidualOnly()
        ro.fit(ref_features, ref_errors, k=3)
        rng = np.random.default_rng(32)
        queries = rng.standard_normal((7, 5))
        assert ro.score(queries).shape == (7,)

    def test_range(self) -> None:
        """ResidualOnly scores are in [0, 1] (ECDF-normalized)."""
        ref_features, ref_errors = _make_data()
        ro = ResidualOnly()
        ro.fit(ref_features, ref_errors, k=3)
        rng = np.random.default_rng(33)
        queries = rng.standard_normal((10, 5))
        scores = ro.score(queries)
        assert np.all(scores >= 0.0)
        assert np.all(scores <= 1.0)

    def test_is_not_trust_gate_subclass(self) -> None:
        """ResidualOnly must not be a TrustGate or subclass thereof."""
        assert not issubclass(ResidualOnly, TrustGate)

    def test_fit_k_equals_n_refs_raises_gate_error(self) -> None:
        """ResidualOnly.fit uses LOO internally; k==n_refs is out of LOO range → GateError."""
        ref_features, ref_errors = _make_data(n_refs=10)
        with pytest.raises(GateError, match="k"):
            ResidualOnly().fit(ref_features, ref_errors, k=10)

    def test_higher_score_near_high_error_refs(self) -> None:
        """ResidualOnly gives higher score near high-error reference points."""
        rng = np.random.default_rng(34)
        n = 30
        feat_dim = 3
        ref_features = rng.standard_normal((n, feat_dim))
        # High error when dim 0 > 0
        ref_errors = np.where(ref_features[:, 0] > 0, 2.0, 0.1)

        ro = ResidualOnly()
        ro.fit(ref_features, ref_errors, k=5)

        high_err_query = np.array([[3.0, 0.0, 0.0]])
        low_err_query = np.array([[-3.0, 0.0, 0.0]])

        assert ro.score(high_err_query)[0] > ro.score(low_err_query)[0]


# ---------------------------------------------------------------------------
# Identical method budgets
# ---------------------------------------------------------------------------


class TestIdenticalMethodBudgets:
    def test_all_comparators_same_inputs(self) -> None:
        """All learned comparators can be constructed from the same (ref_features, ref_errors)."""
        ref_features, ref_errors = _make_data(n_refs=25, feat_dim=6, seed=50)
        rng = np.random.default_rng(51)
        queries = rng.standard_normal((8, 6))

        # All comparators must accept and score the same inputs
        nfd = NearestFeatureDistance()
        nfd.fit(ref_features, ref_errors)
        nfd_scores = nfd.score(queries)

        ridge = RidgeErrorRegressor()
        ridge.fit(ref_features, ref_errors, alpha=1.0)
        ridge_scores = ridge.score(queries)

        gbm = GbmErrorRegressor()
        gbm.fit(ref_features, ref_errors, n_estimators=10, seed=0)
        gbm_scores = gbm.score(queries)

        ro = ResidualOnly()
        ro.fit(ref_features, ref_errors, k=3)
        ro_scores = ro.score(queries)

        # All shapes match
        n_q = queries.shape[0]
        assert nfd_scores.shape == (n_q,)
        assert ridge_scores.shape == (n_q,)
        assert gbm_scores.shape == (n_q,)
        assert ro_scores.shape == (n_q,)

    def test_ensemble_disagreement_takes_different_input(self) -> None:
        """EnsembleDisagreement takes ensemble_member_means, not feature queries."""
        ref_features, ref_errors = _make_data(n_refs=15, feat_dim=4)
        ed = EnsembleDisagreement()
        ed.fit(ref_features, ref_errors)  # fit still accepts ref_features/ref_errors

        # score takes (n_queries, n_members, pca_dims) — different from feature queries
        n_queries, n_members, pca_dims = 5, 3, 8
        ensemble_means = np.random.default_rng(52).standard_normal((n_queries, n_members, pca_dims))
        scores = ed.score(ensemble_means)
        assert scores.shape == (n_queries,)
