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


def _held_out_pair(pairs: list[tuple[int, int]], n_genes: int) -> tuple[int, int]:
    """First gene-disjoint ``(g, h)``, ``g < h``, whose BOTH genes are unseen.

    Returns the first pair such that NEITHER ``g`` nor ``h`` appears in ANY pair
    in ``pairs``. This is a genuine double-unseen / combo-zero-shot pair (spec
    §1.3, §3.4 (b)): both genes are absent from every calibration pair, not merely
    the pair itself being absent. Predicting it exercises the operator's
    extrapolation to two simultaneously novel gene factors.

    Raises
    ------
    ValueError
        If fewer than two genes are free (every gene appears in some calibration
        pair, or only one free gene remains), so no gene-disjoint pair exists.
    """
    used = {g for a, b in pairs for g in (a, b)}
    free = [g for g in range(n_genes) if g not in used]
    if len(free) < 2:
        raise ValueError(
            "no gene-disjoint held-out pair available: "
            f"{len(free)} free gene(s) over {n_genes} genes "
            f"({len(used)} used by calibration pairs); need >= 2"
        )
    return free[0], free[1]


def _max_recovered_gi(coef: np.ndarray, Z: np.ndarray, pairs: list[tuple[int, int]]) -> float:
    """Largest recovered-GI norm ``max_p ||coef @ pair_feature(z_a, z_b)||`` over pairs."""
    return float(np.max([np.linalg.norm(bilinear_predict(coef, Z[a], Z[b])) for a, b in pairs]))


@dataclass(frozen=True)
class RecoveryReport:
    """Outcome of a synthetic recovery run (claim-1 evidence, §3.4).

    Attributes
    ----------
    noiseless_rel_err
        Algebraic coefficient recovery error from the noiseless ``lam=0`` fit
        (§3.4 (a); ~0 by construction when full rank).
    noisy_rel_err
        Coefficient recovery error from the noisy ridge fit (§3.4 (b)).
    held_out_pred_rel_err
        Genuine double-unseen (combo-zero-shot) generalization error (§3.4 (b)):
        the *noisy* fit predicting a held-out pair whose BOTH genes are absent
        from every calibration pair (gene-disjoint), scored against the
        ground-truth bilinear response. Noise-dependent; looser than the
        coefficient tolerance.
    false_gi_norm_noiseless
        False-GI algebraic check (§3.4 (d)): with no true GI (rank 0) the
        noiseless ``lam=0`` fit recovers ``eps_hat ~ 0`` (< 1e-8). Pinned to ~0
        by construction; kept only as the algebraic sanity leg.
    false_gi_norm_noisy
        Spurious recovered-GI magnitude from the **noisy** rank-0 fit. This is
        the noise-robust false-GI guard: it must stay far below
        ``genuine_gi_norm`` (the estimator does not invent interactions of
        real-GI magnitude). ``nan`` when the run is not a rank-0 run.
    genuine_gi_norm
        Recovered-GI magnitude from a noisy rank>0 fit at the **same noise and
        config**, used as the reference scale for ``false_gi_norm_noisy``.
        ``nan`` when not computed (only computed on rank-0 runs).
    false_gi_norm
        Backward-compatible alias for the operative noise-aware guard,
        ``false_gi_norm_noisy`` (or ``false_gi_norm_noiseless`` when noiseless).
    is_full_rank
        Whether the calibration design matrix is full rank (§3.4 (c)).
    frontier
        Optional ``frontier_sweep`` rows; empty for a single run.
    """

    noiseless_rel_err: float
    noisy_rel_err: float
    held_out_pred_rel_err: float
    false_gi_norm_noiseless: float
    false_gi_norm_noisy: float
    genuine_gi_norm: float
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

    # Held-out double-unseen (combo-zero-shot) generalization (§3.4 (b)): the NOISY
    # fit predicts a gene-disjoint pair whose BOTH genes are absent from every
    # calibration pair, scored against the ground-truth bilinear response.
    # Genuinely noise-dependent and genuinely zero-shot in both gene factors.
    g, h = _held_out_pair(d.pairs, n_genes)
    held = _rel_err(
        bilinear_predict(coef_noisy, d.Z[g], d.Z[h]),
        bilinear_predict(d.coef_true, d.Z[g], d.Z[h]),
    )

    # False-GI guard (§3.4 (d)). Two legs:
    #   (1) noiseless algebraic: rank-0 + lam=0 fit on eps_true (all zeros) -> eps_hat ~ 0.
    #   (2) noise-robust: spurious recovered-GI from the NOISY rank-0 fit must be far
    #       below GENUINE recovered-GI from a noisy rank>0 fit at the same noise/config
    #       (the estimator does not invent interactions of real-GI magnitude).
    # Both legs use a well-determined config (n_pairs >> sym_dim) for a stable ridge.
    if rank == 0:
        false_gi_noiseless = _max_recovered_gi(coef_clean, clean.Z, clean.pairs)
        false_gi_noisy = _max_recovered_gi(coef_noisy, d.Z, d.pairs)
        genuine = make_synthetic(
            n_genes=n_genes, k=k, p=p, rank=1, n_pairs=n_pairs, noise_sd=noise_sd, seed=seed
        )
        coef_genuine = identify_operator(genuine.Z, genuine.pairs, genuine.eps_obs, lam=1e-3)
        genuine_gi_norm = _max_recovered_gi(coef_genuine, genuine.Z, genuine.pairs)
        false_gi_alias = false_gi_noisy
    else:
        false_gi_noiseless = float("nan")
        false_gi_noisy = float("nan")
        genuine_gi_norm = float("nan")
        false_gi_alias = 0.0

    return RecoveryReport(
        noiseless_rel_err=noiseless_rel,
        noisy_rel_err=noisy_rel,
        held_out_pred_rel_err=held,
        false_gi_norm_noiseless=false_gi_noiseless,
        false_gi_norm_noisy=false_gi_noisy,
        genuine_gi_norm=genuine_gi_norm,
        false_gi_norm=false_gi_alias,
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
                n_genes=n_genes,
                p=p,
                rank=rank,
                n_pairs=n_cal,
                noise_sd=noise_sd,
                seed=seed,
                k=k,
            )
            out.append(
                {"k": k, "n_cal": n_cal, "rel_err": r.noisy_rel_err, "is_full_rank": r.is_full_rank}
            )
    return tuple(out)
