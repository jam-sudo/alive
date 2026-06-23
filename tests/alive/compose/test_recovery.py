"""Known-answer tests for the synthetic recovery harness (claim 1).

Covers §3.4: (a) noiseless algebraic recovery, (b) noisy within tolerance,
(c) graceful degradation when rank-deficient, (d) false-GI guard (eps*=0 -> ~0),
(e) k vs |Cal| frontier.
"""
from __future__ import annotations

from alive.compose.synthetic import RecoveryReport, frontier_sweep, run_recovery


def test_noiseless_algebraic_recovery():
    r = run_recovery(n_genes=40, p=5, rank=2, n_pairs=60, noise_sd=0.0, seed=0, k=4)
    assert isinstance(r, RecoveryReport)
    assert r.is_full_rank
    assert r.noiseless_rel_err < 1e-8           # (a)
    assert r.held_out_pred_rel_err < 1e-8


def test_noisy_recovery_within_tolerance():
    r = run_recovery(n_genes=40, p=5, rank=2, n_pairs=60, noise_sd=0.05, seed=1, k=4)
    assert r.noisy_rel_err < 0.15               # (b) matches config tol


def test_false_gi_guard():
    r = run_recovery(n_genes=40, p=5, rank=0, n_pairs=60, noise_sd=0.0, seed=2, k=4)
    assert r.false_gi_norm < 1e-8               # (d) eps*=0 -> eps_hat ~ 0


def test_rank_deficient_degrades_and_flags():
    # Too few pairs for k=8 (sym_dim=36) -> not full rank.
    r = run_recovery(n_genes=40, p=3, rank=2, n_pairs=10, noise_sd=0.0, seed=3, k=8)
    assert not r.is_full_rank                    # (c) flagged


def test_frontier_sweep_keys():
    fr = frontier_sweep(k_grid=(4, 8), n_cal_grid=(20, 60), p=3, rank=2, noise_sd=0.05, seed=4)
    assert {(d["k"], d["n_cal"]) for d in fr} == {(4, 20), (4, 60), (8, 20), (8, 60)}
    assert all("rel_err" in d and "is_full_rank" in d for d in fr)
