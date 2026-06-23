"""Synthetic generator + recovery harness for the claim-1 known-answer proof.

The generator builds fixed gene factors Z, a low-rank symmetric ground-truth
operator, the exact GI vectors eps_true, and a noisy observation eps_obs. The
recovery harness (Task 5) consumes this to prove algebraic recovery (noiseless)
and characterise noisy recovery — independent of any real data.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from alive.compose.operator import _sym_to_vec, bilinear_predict


@dataclass(frozen=True)
class SyntheticData:
    """Ground-truth synthetic instance for recovery testing."""

    Z: np.ndarray
    coef_true: np.ndarray
    pairs: list[tuple[int, int]]
    eps_true: np.ndarray
    eps_obs: np.ndarray


def _low_rank_sym(rng: np.random.Generator, k: int, rank: int) -> np.ndarray:
    """A symmetric k x k matrix of given rank (zero matrix when rank == 0)."""
    if rank <= 0:
        return np.zeros((k, k))
    U = rng.normal(size=(k, rank))
    return U @ U.T


def make_synthetic(
    *,
    n_genes: int,
    k: int,
    p: int,
    rank: int,
    n_pairs: int,
    noise_sd: float,
    seed: int,
) -> SyntheticData:
    """Generate a synthetic identification instance (see module docstring)."""
    rng = np.random.default_rng(seed)
    Z = rng.normal(size=(n_genes, k))
    coef_true = np.vstack([_sym_to_vec(_low_rank_sym(rng, k, rank)) for _ in range(p)])
    seen: set[tuple[int, int]] = set()
    pairs: list[tuple[int, int]] = []
    while len(pairs) < n_pairs:
        a, b = int(rng.integers(n_genes)), int(rng.integers(n_genes))
        if a == b:
            continue
        key = (min(a, b), max(a, b))
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)
    eps_true = np.vstack([bilinear_predict(coef_true, Z[g], Z[h]) for g, h in pairs])
    noise = rng.normal(scale=noise_sd, size=eps_true.shape) if noise_sd > 0 else 0.0
    eps_obs = eps_true + noise
    return SyntheticData(Z=Z, coef_true=coef_true, pairs=pairs, eps_true=eps_true, eps_obs=eps_obs)
