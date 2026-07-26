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
from alive.compose.operator import bilinear_predict, sym_basis_dim


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


def test_singular_design_raises_a_typed_error_not_a_bare_linalg_error():
    """Whether LAPACK reports exact singularity is not portable; the outcome is.

    A zero factor bank makes the Gram matrix exactly zero at ``lam=0``, so every
    LAPACK build reports it singular. Without normalisation the caller would see
    ``numpy.linalg.LinAlgError`` here and an arbitrary estimate on a build whose
    pivots happen not to underflow to zero.
    """
    n_genes, k, p = 6, 3, 2
    Z = np.zeros((n_genes, k))
    pairs = [(i, j) for i in range(n_genes) for j in range(i + 1, n_genes)]
    eps = np.zeros((len(pairs), p))
    with pytest.raises(SingularDesignError, match="no unique least-squares solution"):
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
