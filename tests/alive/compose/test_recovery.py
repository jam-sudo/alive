"""Known-answer tests for the synthetic recovery harness (claim 1).

Covers §3.4: (a) noiseless algebraic recovery, (b) noisy recovery + genuine
double-unseen (combo-zero-shot) generalization within tolerance, (c) graceful
degradation when rank-deficient, (d) noise-robust false-GI guard (no true GI +
noise must not hallucinate real-GI-magnitude interactions), (e) k vs |Cal|
frontier.

Tolerances asserted here are tied to the Phase-1 config
(`configs/compose_k562_v1_phase1.yaml`):
  * ``RECOVERY_REL_ERR_TOL = 0.15`` — noisy coefficient acceptance.
  * Held-out (double-unseen) generalization is asserted LOOSER than the
    coefficient tolerance (``2 * RECOVERY_REL_ERR_TOL``), per §3.4: predicting a
    GENUINELY gene-disjoint pair (BOTH genes absent from every calibration pair)
    is a strictly harder, noise-amplified target. Empirically it sits ~0.01
    across registered seeds, so the bound is generous but principled.
  * False-GI is asserted as a RATIO, not a magic absolute: spurious recovered-GI
    from the noisy rank-0 fit must be ``< FALSE_GI_RATIO_MARGIN`` of the genuine
    recovered-GI from a noisy rank>0 fit at the same noise/config. The absolute
    spurious norm (~0.08-0.6 across seeds/noise) would VIOLATE a magic absolute
    tolerance on several seeds, which is exactly why the honest guard is
    scale-relative (an absolute tol is a Phase-2 concern). Observed worst ratio is
    ~0.05; the 0.1 margin leaves ~2x headroom while still catching real-GI-
    magnitude hallucination.
"""

from __future__ import annotations

import math

from alive.compose.synthetic import (
    RecoveryReport,
    _held_out_pair,
    frontier_sweep,
    make_synthetic,
    run_recovery,
)

RECOVERY_REL_ERR_TOL = 0.15
HELD_OUT_REL_ERR_TOL = 2.0 * RECOVERY_REL_ERR_TOL  # looser than coefficient tol (§3.4)
FALSE_GI_RATIO_MARGIN = 0.1  # spurious GI must be < 10% of genuine GI


def test_noiseless_algebraic_recovery():
    # n_genes=60 (production setting) guarantees >= 2 genes free of every calibration
    # pair, so a genuinely gene-disjoint held-out pair always exists.
    r = run_recovery(n_genes=60, p=5, rank=2, n_pairs=60, noise_sd=0.0, seed=0, k=4)
    assert isinstance(r, RecoveryReport)
    assert r.is_full_rank
    assert r.noiseless_rel_err < 1e-8  # (a) algebraic coefficient recovery
    # Held-out uses the ``lam=1e-3`` fit, so at noise_sd=0 only the tiny ridge bias
    # remains (~1e-5); it is not the 1e-8 algebraic floor of the coefficient leg.
    assert r.held_out_pred_rel_err < 1e-3


def test_noisy_recovery_within_tolerance():
    r = run_recovery(n_genes=60, p=5, rank=2, n_pairs=60, noise_sd=0.05, seed=1, k=4)
    assert r.noisy_rel_err < RECOVERY_REL_ERR_TOL  # (b) coefficient tol


def test_held_out_noisy_generalization():
    # (b) GENUINE double-unseen (combo-zero-shot): the NOISY fit predicts a held-out
    # pair whose BOTH genes are absent from EVERY calibration pair (gene-disjoint),
    # scored vs ground truth. Must be finite, noise-driven, within the looser bound.
    n_genes, n_pairs, seed, k = 60, 60, 1, 4
    r = run_recovery(n_genes=n_genes, p=5, rank=2, n_pairs=n_pairs, noise_sd=0.05, seed=seed, k=k)
    assert math.isfinite(r.held_out_pred_rel_err)
    assert r.held_out_pred_rel_err > 0.0  # noise => not exactly zero
    assert r.held_out_pred_rel_err < HELD_OUT_REL_ERR_TOL

    # Load-bearing §3.4 (b) evidence: reconstruct the exact synthetic instance the
    # recovery run used and prove the scored held-out pair is TRULY gene-disjoint —
    # i.e. NEITHER gene appears in ANY calibration pair (not merely the pair absent).
    d = make_synthetic(n_genes=n_genes, k=k, p=5, rank=2, n_pairs=n_pairs, noise_sd=0.05, seed=seed)
    g, h = _held_out_pair(d.pairs, n_genes)
    calibration_genes = {gene for a, b in d.pairs for gene in (a, b)}
    assert g not in calibration_genes  # gene g unseen in all cal pairs
    assert h not in calibration_genes  # gene h unseen in all cal pairs
    assert g != h  # a genuine pair
    # And the pair itself is therefore absent from calibration (weaker corollary).
    assert (min(g, h), max(g, h)) not in {(min(a, b), max(a, b)) for a, b in d.pairs}


def test_false_gi_guard_noise_robust():
    # (d) NO true GI (rank 0) WITH noise. The estimator must not invent interactions
    # of real-GI magnitude. Tested as a scale-relative ratio, not a magic absolute.
    r = run_recovery(n_genes=60, p=5, rank=0, n_pairs=60, noise_sd=0.05, seed=2, k=4)
    # Algebraic leg: noiseless rank-0 fit recovers eps_hat ~ 0.
    assert r.false_gi_norm_noiseless < 1e-8
    # Noise-robust leg: spurious (noisy rank-0) GI is much smaller than genuine GI.
    assert math.isfinite(r.false_gi_norm_noisy)
    assert r.false_gi_norm_noisy > 0.0  # noise does produce *some* fit
    assert math.isfinite(r.genuine_gi_norm)
    assert r.false_gi_norm_noisy < FALSE_GI_RATIO_MARGIN * r.genuine_gi_norm
    # Backward-compatible alias tracks the operative (noisy) guard for rank-0 runs.
    assert r.false_gi_norm == r.false_gi_norm_noisy


def test_false_gi_guard_holds_across_noise_and_seeds():
    # The ratio margin must hold across registered seeds and noise levels, not just one.
    for seed in (11, 23, 37):
        for noise_sd in (0.05, 0.1, 0.2):
            r = run_recovery(n_genes=60, p=5, rank=0, n_pairs=60, noise_sd=noise_sd, seed=seed, k=4)
            assert r.false_gi_norm_noisy < FALSE_GI_RATIO_MARGIN * r.genuine_gi_norm


def test_rank_deficient_degrades_and_flags():
    # Too few pairs for k=8 (sym_dim=36) -> not full rank.
    r = run_recovery(n_genes=40, p=3, rank=2, n_pairs=10, noise_sd=0.0, seed=3, k=8)
    assert not r.is_full_rank  # (c) flagged


def test_frontier_sweep_keys():
    fr = frontier_sweep(k_grid=(4, 8), n_cal_grid=(20, 60), p=3, rank=2, noise_sd=0.05, seed=4)
    assert {(d["k"], d["n_cal"]) for d in fr} == {(4, 20), (4, 60), (8, 20), (8, 60)}
    assert all("rel_err" in d and "is_full_rank" in d for d in fr)
