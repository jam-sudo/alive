"""Synthetic-only tests for the Φ rank/condition report.

No real Norman outcomes are touched: the pure :func:`compute_phi_rank_report`
is exercised with random single-role ``δ_g`` and outcome-free sequence vectors,
so the rank behaviour is a known-answer property — for generic ``z`` the design
matrix rank is ``min(|combo_calibration|, sym_dim)``.
"""

from __future__ import annotations

import numpy as np

from alive.compose.phi_rank import compute_phi_rank_report

# 14 genes, all distinct pairs eligible. calibration_fraction 0.6 ->
# round-half-to-even(8.4) = 8 calibration genes -> C(8,2) = 28 combo pairs.
# sym_dim = k(k+1)/2 = 10 (k=4), 21 (k=6), 36 (k=8): generic rank = min(28, sym).
_GENES = [f"g{i:02d}" for i in range(14)]
_ELIGIBLE = [(a, b) for i, a in enumerate(_GENES) for b in _GENES[i + 1 :]]


def _inputs(seed: int = 11):
    rng = np.random.default_rng(seed)
    delta = {g: rng.standard_normal(10) for g in _GENES}
    seq = {g: rng.standard_normal(20) for g in _GENES}
    return delta, seq


def _report(seed: int = 11) -> dict:
    delta, seq = _inputs(seed)
    return compute_phi_rank_report(
        delta_by_gene=delta,
        sequence_by_gene=seq,
        eligible_pairs=_ELIGIBLE,
        total_k_grid=(4, 6, 8),
        esm_dim=2,
        split_seed=11,
        calibration_fraction=0.6,
        encoder_revision="mock-v1",
        sequence_mapping_hash="0" * 64,
    )


def test_split_counts_partition_the_eligible_universe():
    rep = _report()
    assert rep["n_eligible_pairs"] == len(_ELIGIBLE)
    assert rep["n_combo_calibration"] + rep["n_sealed_double_unseen"] + rep[
        "n_sealed_single_unseen"
    ] == len(_ELIGIBLE)
    assert rep["n_combo_calibration"] == 28  # C(8, 2)
    assert rep["n_calibration_genes"] == 8


def test_per_k_sym_dim_matches_k_choose_two_plus_k():
    rep = {r["k_total"]: r for r in _report()["per_k_total"]}
    assert rep[4]["sym_dim"] == 10
    assert rep[6]["sym_dim"] == 21
    assert rep[8]["sym_dim"] == 36


def test_full_rank_when_calibration_pairs_exceed_sym_dim():
    rep = {r["k_total"]: r for r in _report()["per_k_total"]}
    # 28 calibration pairs >= sym_dim for k in {4, 6}: generic design is full rank.
    for k in (4, 6):
        assert rep[k]["is_full_rank"] is True
        assert rep[k]["rank"] == rep[k]["sym_dim"]
        assert np.isfinite(rep[k]["condition_number"])
        assert rep[k]["condition_number"] > 0.0


def test_rank_deficient_design_is_infinitely_conditioned():
    rep = {r["k_total"]: r for r in _report()["per_k_total"]}
    # 28 calibration pairs < sym_dim=36 for k=8: rank-deficient, cond = inf.
    assert rep[8]["is_full_rank"] is False
    assert rep[8]["rank"] == 28
    assert rep[8]["condition_number"] == float("inf")


def test_report_is_deterministic_for_fixed_inputs():
    assert _report(seed=11) == _report(seed=11)
