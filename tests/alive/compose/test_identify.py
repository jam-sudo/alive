"""Tests for alive.compose.identify — written FIRST per TDD protocol."""

from __future__ import annotations

import numpy as np
import pytest

from alive.compose.identify import (
    RankReport,
    SingularDesignError,
    identify_operator,
    rank_diagnostics,
)
from alive.compose.operator import bilinear_predict, design_matrix, sym_basis_dim


def _make(rng, n_genes=20, k=4, p=3, n_pairs=40):
    Z = rng.normal(size=(n_genes, k))
    coef_true = rng.normal(size=(p, sym_basis_dim(k)))
    pairs = [(int(a), int(b)) for a, b in rng.integers(0, n_genes, size=(n_pairs, 2)) if a != b]
    eps = np.vstack([bilinear_predict(coef_true, Z[g], Z[h]) for g, h in pairs])
    return Z, coef_true, pairs, eps


def test_noiseless_full_rank_recovers_coef():
    rng = np.random.default_rng(0)
    Z, coef_true, pairs, eps = _make(rng)
    rep = rank_diagnostics(Z, pairs)
    assert isinstance(rep, RankReport)
    assert rep.is_full_rank  # enough diverse pairs
    coef_hat = identify_operator(Z, pairs, eps, lam=0.0)
    np.testing.assert_allclose(coef_hat, coef_true, atol=1e-6)


def test_predicts_held_out_pair_when_full_rank():
    rng = np.random.default_rng(1)
    Z, coef_true, pairs, eps = _make(rng)
    coef_hat = identify_operator(Z, pairs, eps, lam=0.0)
    g, h = 0, 5  # a pair not necessarily in `pairs`
    np.testing.assert_allclose(
        bilinear_predict(coef_hat, Z[g], Z[h]),
        bilinear_predict(coef_true, Z[g], Z[h]),
        atol=1e-6,
    )


def test_rank_deficient_flagged():
    rng = np.random.default_rng(2)
    Z = rng.normal(size=(20, 4))
    pairs = [(0, 1), (0, 1), (0, 1)]  # one unique pair → rank 1
    rep = rank_diagnostics(Z, pairs)
    assert not rep.is_full_rank
    assert rep.rank == 1
    assert rep.sym_dim == sym_basis_dim(4)
    # A rank-deficient design is effectively infinitely conditioned: the diagnostic
    # must NOT read "well-conditioned" off only the positive singular values.
    assert not np.isfinite(rep.condition_number)
    assert rep.condition_number == float("inf")


def test_lapack_singular_failure_is_normalized_to_typed_error(monkeypatch):
    """The general estimator normalizes LAPACK failure for its callers.

    Phase-2a does its policy-specific precheck in OOF selection. This lower-level
    function remains usable by Phase 1's rank-deficient recovery diagnostic.
    """
    n_genes, k, p = 6, 3, 2
    Z = np.zeros((n_genes, k))
    pairs = [(i, j) for i in range(n_genes) for j in range(i + 1, n_genes)]
    eps = np.zeros((len(pairs), p))

    def _failing_lstsq(phi, target, *, rcond):
        raise np.linalg.LinAlgError("synthetic singular pivot")

    monkeypatch.setattr(np.linalg, "lstsq", _failing_lstsq)
    with pytest.raises(SingularDesignError, match="least-squares solver failed"):
        identify_operator(Z, pairs, eps, lam=0.0)


def test_regularisation_makes_the_same_design_solvable():
    """The guard fires on singularity itself, not on the design being degenerate."""
    n_genes, k, p = 6, 3, 2
    Z = np.zeros((n_genes, k))
    pairs = [(i, j) for i in range(n_genes) for j in range(i + 1, n_genes)]
    eps = np.zeros((len(pairs), p))
    coef = identify_operator(Z, pairs, eps, lam=1e-3)
    assert coef.shape == (p, sym_basis_dim(k))
    assert np.all(coef == 0.0)


def test_unregularized_rank_deficient_fit_is_defined_by_minimum_norm():
    """Phase 1 can characterize rank-deficient recovery without a singular solve."""
    n_genes, k, p = 6, 3, 2
    Z = np.zeros((n_genes, k))
    pairs = [(i, j) for i in range(n_genes) for j in range(i + 1, n_genes)]
    eps = np.zeros((len(pairs), p))

    coef = identify_operator(Z, pairs, eps, lam=0.0)

    assert coef.shape == (p, sym_basis_dim(k))
    assert np.all(coef == 0.0)


def test_ridge_swallowed_by_the_gram_scale_is_rejected():
    """A positive lambda the Gram cannot represent must not be solved silently.

    ``lam`` is an absolute penalty on an UNNORMALIZED Gram, and nothing upstream
    bounds the factor scale. Far enough above the penalty, ``fl(d_ii + lam)``
    equals ``d_ii`` for every i, so a registered positive lambda would be applied
    as no regularization at all.
    """
    rng = np.random.default_rng(4)
    Z, _, pairs, eps = _make(rng)
    with pytest.raises(SingularDesignError, match="not representable against"):
        identify_operator(Z * 1e4, pairs, eps, lam=1e-3)


def test_the_rejected_ridge_really_is_byte_identical_to_the_unregularized_gram():
    """Pin the premise, not just the behaviour, of the guard above.

    If a future change made the pathological input representable again, this
    test fails rather than leaving a guard that can no longer detect anything.
    """
    rng = np.random.default_rng(4)
    Z, _, pairs, _ = _make(rng)
    phi = design_matrix(Z * 1e4, pairs)
    base = phi.T @ phi
    gram = base + 1e-3 * np.eye(phi.shape[1])
    assert np.array_equal(gram, base)


@pytest.mark.parametrize("lam", [0.001, 0.01, 0.1])
def test_registered_ridges_survive_the_largest_representable_factor_scale(lam):
    """The guard must not fire anywhere the registered response space can reach.

    ``normalize_total_median`` + ``log1p`` over ``n_hvg: 1500`` bounds a single
    gene shift by ``sqrt(1500) * log1p(1e4) ~= 356``, and the factor scores are
    an orthonormal projection of it, so ``|z| <= 356`` regardless of biology.
    """
    rng = np.random.default_rng(5)
    Z, _, pairs, eps = _make(rng)
    Z_ceiling = Z * (356.0 / np.abs(Z).max())
    coef = identify_operator(Z_ceiling, pairs, eps, lam=lam)
    assert np.all(np.isfinite(coef))


@pytest.mark.parametrize("lam", [-1.0, np.nan, np.inf])
def test_invalid_regularisation_is_rejected(lam):
    rng = np.random.default_rng(3)
    Z, _, pairs, eps = _make(rng)
    with pytest.raises(ValueError, match="finite and non-negative"):
        identify_operator(Z, pairs, eps, lam=lam)
