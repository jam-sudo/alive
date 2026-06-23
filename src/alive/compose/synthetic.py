"""Synthetic generator + recovery harness for the claim-1 known-answer proof.

The generator builds fixed gene factors Z, a low-rank symmetric ground-truth
operator, the exact GI vectors eps_true, and a noisy observation eps_obs. The
recovery harness (Task 5) consumes this to prove algebraic recovery (noiseless)
and characterise noisy recovery — independent of any real data.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from alive.compose.identify import identify_operator, rank_diagnostics
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


def _rel_err(a: np.ndarray, b: np.ndarray) -> float:
    """Relative L2 error ||a-b|| / max(||b||, eps)."""
    denom = float(np.linalg.norm(b))
    return float(np.linalg.norm(a - b) / denom) if denom > 1e-12 else float(np.linalg.norm(a))


@dataclass(frozen=True)
class RecoveryReport:
    """Outcome of a synthetic recovery run (claim-1 evidence)."""

    noiseless_rel_err: float
    noisy_rel_err: float
    held_out_pred_rel_err: float
    false_gi_norm: float
    is_full_rank: bool
    frontier: tuple[dict, ...]


def run_recovery(
    *,
    n_genes: int,
    p: int,
    rank: int,
    n_pairs: int,
    noise_sd: float,
    seed: int,
    k: int,
) -> RecoveryReport:
    """Recover the operator from synthetic data and score it (§3.4)."""
    d = make_synthetic(
        n_genes=n_genes, k=k, p=p, rank=rank, n_pairs=n_pairs, noise_sd=noise_sd, seed=seed
    )
    rep_rank = rank_diagnostics(d.Z, d.pairs)

    # Noiseless coefficient recovery (algebraic).
    clean = make_synthetic(
        n_genes=n_genes, k=k, p=p, rank=rank, n_pairs=n_pairs, noise_sd=0.0, seed=seed
    )
    coef_clean = identify_operator(clean.Z, clean.pairs, clean.eps_true, lam=0.0)
    noiseless_rel = _rel_err(coef_clean, clean.coef_true)

    # Noisy recovery (small ridge).
    coef_noisy = identify_operator(d.Z, d.pairs, d.eps_obs, lam=1e-3)
    noisy_rel = _rel_err(coef_noisy, d.coef_true)

    # Held-out (combo-unseen) pair prediction from the clean fit.
    g, h = 0, n_genes - 1
    held = _rel_err(
        bilinear_predict(coef_clean, clean.Z[g], clean.Z[h]),
        bilinear_predict(clean.coef_true, clean.Z[g], clean.Z[h]),
    )

    # False-GI guard: when eps* == 0, recovered eps must be ~0.
    false_gi = float(
        np.max([np.linalg.norm(bilinear_predict(coef_clean, clean.Z[a], clean.Z[b]))
                for a, b in clean.pairs])
    ) if rank == 0 else 0.0

    return RecoveryReport(
        noiseless_rel_err=noiseless_rel,
        noisy_rel_err=noisy_rel,
        held_out_pred_rel_err=held,
        false_gi_norm=false_gi,
        is_full_rank=rep_rank.is_full_rank,
        frontier=(),
    )


def frontier_sweep(
    *,
    k_grid: tuple[int, ...],
    n_cal_grid: tuple[int, ...],
    p: int,
    rank: int,
    noise_sd: float,
    seed: int,
    n_genes: int = 60,
) -> tuple[dict, ...]:
    """Sweep (k, |Cal|) and report noisy recovery error + rank status."""
    out: list[dict] = []
    for k in k_grid:
        for n_cal in n_cal_grid:
            r = run_recovery(
                n_genes=n_genes, p=p, rank=rank, n_pairs=n_cal,
                noise_sd=noise_sd, seed=seed, k=k,
            )
            out.append(
                {"k": k, "n_cal": n_cal, "rel_err": r.noisy_rel_err, "is_full_rank": r.is_full_rank}
            )
    return tuple(out)
