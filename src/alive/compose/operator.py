"""Symmetric bilinear interaction-composition operator (Phase 1, §3.2).

eps_gh[m] = z_g^T B_m z_h with each B_m symmetric. We store the operator as a
``coef`` matrix of shape (p, sym_dim) where each row is the symmetric matrix
B_m flattened by :func:`_sym_to_vec`. The matching pair feature
:func:`pair_feature` is built so that ``coef @ pair_feature(z_g, z_h)`` equals
the stacked quadratic forms — and is symmetric in (g, h).
"""

from __future__ import annotations

import numpy as np


def sym_basis_dim(k: int) -> int:
    """Dimension of the symmetric k x k space: ``k(k+1)/2``."""
    return k * (k + 1) // 2


def _sym_to_vec(B: np.ndarray) -> np.ndarray:
    """Flatten a symmetric matrix: diagonal as-is, off-diagonal scaled by sqrt(2).

    The sqrt(2) scaling makes ``_sym_to_vec(B) @ pair_feature(zg, zh)`` reproduce
    ``zg^T B zh`` for symmetric B without double counting off-diagonal terms.
    """
    k = B.shape[0]
    iu = np.triu_indices(k)
    out = B[iu].astype(np.float64).copy()
    off = iu[0] != iu[1]
    out[off] *= np.sqrt(2.0)
    return out


def pair_feature(z_g: np.ndarray, z_h: np.ndarray) -> np.ndarray:
    """Symmetric bilinear feature vector of length ``sym_basis_dim(k)``."""
    z_g = np.asarray(z_g, dtype=np.float64)
    z_h = np.asarray(z_h, dtype=np.float64)
    outer = np.outer(z_g, z_h)
    sym = (outer + outer.T) / 2.0
    return _sym_to_vec(sym)


def design_matrix(Z: np.ndarray, pairs: list[tuple[int, int]]) -> np.ndarray:
    """Stack :func:`pair_feature` over ``pairs`` → ``(n_pairs, sym_dim)``."""
    Z = np.asarray(Z, dtype=np.float64)
    return np.vstack([pair_feature(Z[g], Z[h]) for (g, h) in pairs])


def bilinear_predict(coef: np.ndarray, z_g: np.ndarray, z_h: np.ndarray) -> np.ndarray:
    """Predict eps (length p) = ``coef @ pair_feature(z_g, z_h)``."""
    return np.asarray(coef, dtype=np.float64) @ pair_feature(z_g, z_h)
