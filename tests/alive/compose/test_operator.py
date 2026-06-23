"""Tests for alive.compose.operator — written FIRST per TDD protocol."""
from __future__ import annotations

import numpy as np

from alive.compose.operator import (
    bilinear_predict,
    design_matrix,
    pair_feature,
    sym_basis_dim,
)


def test_sym_basis_dim():
    assert sym_basis_dim(1) == 1
    assert sym_basis_dim(4) == 10


def test_pair_feature_symmetric():
    rng = np.random.default_rng(0)
    zg, zh = rng.normal(size=5), rng.normal(size=5)
    np.testing.assert_allclose(pair_feature(zg, zh), pair_feature(zh, zg))
    assert pair_feature(zg, zh).shape == (sym_basis_dim(5),)


def test_design_matrix_shape():
    Z = np.random.default_rng(1).normal(size=(6, 4))
    pairs = [(0, 1), (2, 3), (0, 4)]
    Phi = design_matrix(Z, pairs)
    assert Phi.shape == (3, sym_basis_dim(4))


def test_predict_matches_quadratic_form():
    # eps[m] = z_g^T B_m z_h with symmetric B_m must equal coef @ pair_feature.
    rng = np.random.default_rng(2)
    k, p = 4, 3
    Z = rng.normal(size=(2, k))
    zg, zh = Z[0], Z[1]
    Bs = []
    coef_rows = []
    from alive.compose.operator import _sym_to_vec  # internal, see impl
    for _ in range(p):
        M = rng.normal(size=(k, k))
        B = (M + M.T) / 2
        Bs.append(B)
        coef_rows.append(_sym_to_vec(B))
    coef = np.vstack(coef_rows)
    quad = np.array([zg @ B @ zh for B in Bs])
    np.testing.assert_allclose(bilinear_predict(coef, zg, zh), quad, atol=1e-10)
