"""Tests for alive.compose.synthetic generator — written FIRST per TDD protocol."""

from __future__ import annotations

import numpy as np

from alive.compose.operator import sym_basis_dim
from alive.compose.synthetic import SyntheticData, make_synthetic


def test_shapes_and_noiseless_equality():
    d = make_synthetic(n_genes=30, k=4, p=5, rank=2, n_pairs=50, noise_sd=0.0, seed=0)
    assert isinstance(d, SyntheticData)
    assert d.Z.shape == (30, 4)
    assert d.coef_true.shape == (5, sym_basis_dim(4))
    assert d.eps_true.shape == (len(d.pairs), 5)
    np.testing.assert_array_equal(d.eps_obs, d.eps_true)  # noiseless


def test_zero_rank_means_zero_gi():
    d = make_synthetic(n_genes=20, k=4, p=3, rank=0, n_pairs=30, noise_sd=0.0, seed=1)
    np.testing.assert_allclose(d.eps_true, 0.0, atol=1e-12)


def test_noise_perturbs_and_is_deterministic():
    a = make_synthetic(n_genes=20, k=4, p=3, rank=2, n_pairs=30, noise_sd=0.1, seed=2)
    b = make_synthetic(n_genes=20, k=4, p=3, rank=2, n_pairs=30, noise_sd=0.1, seed=2)
    np.testing.assert_array_equal(a.eps_obs, b.eps_obs)  # seed-deterministic
    assert not np.allclose(a.eps_obs, a.eps_true)  # noise applied
