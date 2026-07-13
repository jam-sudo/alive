# tests/alive/compose/test_approximation_bias_metric.py
"""Known-answer tests for the approximation-bias v1 point-estimate core.

Task 1 of the COMPOSE approximation-bias v1 implementation plan (design spec
``docs/superpowers/specs/2026-07-13-compose-approximation-bias-metric-design.md``):
stratify + per-pair bias ``b_i`` + GI residual ``g_i`` + the ratio-of-medians
``bias_to_signal_ratio_R`` + the pre-registered ``fairness_flag``.

Every fixture here is a HAND-BUILT identity ``response_projection`` block
(``pca_mean = 0``, ``pca_components = I`` over an all-HVG gene set) so
``z(x) = log1p(normalize(x))`` exactly, and every expected value is
independently hand-computed (or derived analytically) in this file rather than
by calling the metric under test — anti-tautology per the task brief. Opens no
seal, imports no ``gears``/``cpa``, constructs no store.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest

from alive.compose.fit_role import canonical_gene_order_sha256

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "compose" / "measure_pseudobulk_approximation_bias.py"
_SENTINEL = "NON_FINITE"


def _load_metric_module():
    """Import the metric script by path (mirrors the legacy metric test)."""
    spec = importlib.util.spec_from_file_location("_pb_bias_metric_v1", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identity_block(genes: list[str], median_library: float, control_mean: list[float]) -> dict:
    """A frozen ``response_projection`` block whose z-transform is exactly
    ``log1p(normalize(x, median_library))``: HVG = every gene, ``pca_mean`` is
    zero, and ``pca_components`` is the identity matrix (no rotation)."""
    n = len(genes)
    return {
        "median_library": float(median_library),
        "hvg_gene_ids": list(genes),
        "pca_mean": [0.0] * n,
        "pca_components": np.eye(n).tolist(),
        "gene_order_sha256": canonical_gene_order_sha256(genes),
        "control_mean": [float(v) for v in control_mean],
    }


def _cells(*rows: list[float]) -> np.ndarray:
    """Stack raw per-cell count rows into a ``(n_cells, n_genes)`` matrix."""
    return np.array(rows, dtype=np.float64)


def _z_by_hand(row: np.ndarray, median_library: float) -> np.ndarray:
    """Independent reference implementation of the identity-block transform.

    Reimplements ``normalize_total_median + log1p`` directly (NOT by calling
    into the metric module or ``fit_role.apply_response_projection``) so
    known-answer assertions are not circular.
    """
    row = np.asarray(row, dtype=np.float64)
    lib = row.sum(axis=-1, keepdims=True)
    safe = np.where(lib > 0, lib, 1.0)
    return np.log1p(row * (median_library / safe))


# ---------------------------------------------------------------------------
# Test 1: degenerate identical cells -> exact zero floor.
# ---------------------------------------------------------------------------


def test_degenerate_identical_cells_zero_floor():
    module = _load_metric_module()
    genes = ["G1", "G2", "G3"]
    block = _identity_block(genes, median_library=15.0, control_mean=[0.0, 0.0, 0.0])

    # >=2 IDENTICAL cells (not the trivial 1-cell case): mean(z) == z(mean)
    # exactly, since averaging 2 bit-identical rows is exact in IEEE-754
    # (doubling then halving never rounds).
    identical_row = [3.0, 7.0, 2.0]
    raw = _cells(identical_row, identical_row)

    result = module._stratum_bias({"PERTX_PERTY": raw}, block, genes)

    assert result["n_pairs"] == 1
    assert result["per_pair"] == [{"pair_id": "PERTX_PERTY", "b_i": 0.0}]
    assert result["b_distribution"]["median"] == 0.0
    assert result["b_distribution"]["max"] == 0.0


# ---------------------------------------------------------------------------
# Test 2: analytic 2-cell case matches an independent by-hand computation.
# ---------------------------------------------------------------------------


def test_analytic_two_cell_bias_matches_by_hand():
    module = _load_metric_module()
    genes = ["G1", "G2"]
    median_library = 10.0
    block = _identity_block(genes, median_library, control_mean=[0.0, 0.0])

    cell1 = [2.0, 8.0]
    cell2 = [6.0, 4.0]
    raw = _cells(cell1, cell2)

    z_mean_by_hand = _z_by_hand(np.array([4.0, 6.0]), median_library)  # z(mean(cells))
    mean_z_by_hand = 0.5 * (
        _z_by_hand(np.array(cell1), median_library) + _z_by_hand(np.array(cell2), median_library)
    )
    bias_by_hand = z_mean_by_hand - mean_z_by_hand
    b_i_by_hand = float(np.mean(bias_by_hand**2))

    result = module._stratum_bias({"PAIRX_PAIRY": raw}, block, genes)

    assert result["per_pair"][0]["pair_id"] == "PAIRX_PAIRY"
    assert result["per_pair"][0]["b_i"] == pytest.approx(b_i_by_hand, abs=1e-12)
    # Sanity: the Jensen gap on this spread population is not degenerate.
    assert b_i_by_hand > 0.0


# ---------------------------------------------------------------------------
# Test 3: bias_to_signal_ratio_R is the ratio of medians, not the median of
# per-pair ratios.
# ---------------------------------------------------------------------------


def test_bias_to_signal_ratio_is_ratio_of_medians():
    module = _load_metric_module()
    genes = [f"F{i}" for i in range(1, 7)]  # F1..F6, p=6
    median_library = 30.0
    control_mean = [0.0] * 6
    block = _identity_block(genes, median_library, control_mean)

    base = [5.0, 5.0, 5.0, 5.0, 5.0, 5.0]

    def _spread(dims: tuple[int, int], s: float) -> tuple[list[float], list[float]]:
        row = list(base)
        row[dims[0]] += s
        row[dims[1]] -= s
        row_swapped = list(base)
        row_swapped[dims[0]] -= s
        row_swapped[dims[1]] += s
        return row, row_swapped

    # Three combo pairs with deliberately DIFFERENT spread (-> different b_i)
    # and deliberately DIFFERENT single-vs-combo mismatch (-> different g_i),
    # anti-correlated so ratio-of-medians != median-of-per-pair-ratios.
    pair1_a, pair1_b = _spread((0, 1), 4.0)
    pair2_a, pair2_b = _spread((2, 3), 2.0)
    pair3_a, pair3_b = _spread((4, 5), 1.0)

    combo_pairs = {
        "P1_P2": _cells(pair1_a, pair1_b),
        "P3_P4": _cells(pair2_a, pair2_b),
        "P5_P6": _cells(pair3_a, pair3_b),
    }
    singles_rows = {
        "P1": _cells([7.0, 3.0, 5.0, 5.0, 5.0, 5.0]),
        "P2": _cells([3.0, 7.0, 5.0, 5.0, 5.0, 5.0]),
        "P3": _cells([5.0, 5.0, 9.0, 1.0, 5.0, 5.0]),
        "P4": _cells([5.0, 5.0, 1.0, 9.0, 5.0, 5.0]),
        "P5": _cells([5.0, 5.0, 5.0, 5.0, 7.0, 3.0]),
        "P6": _cells([5.0, 5.0, 5.0, 5.0, 3.0, 7.0]),
    }

    single_effects = module._single_effects(singles_rows, block, genes)
    result = module._gi_and_fairness(combo_pairs, single_effects, block, genes, combo_sep="_")

    b_values = [
        entry["b_i"] for entry in module._stratum_bias(combo_pairs, block, genes)["per_pair"]
    ]
    g_values = [entry["g_i"] for entry in result["gi_signal_per_pair"]]
    assert all(isinstance(v, float) for v in b_values + g_values)

    ratio_of_medians = float(np.median(b_values)) / float(np.median(g_values))
    median_of_per_pair_ratios = float(np.median([b / g for b, g in zip(b_values, g_values)]))

    # The two aggregation methods must genuinely differ for this fixture,
    # otherwise the test would not discriminate between them.
    assert ratio_of_medians != pytest.approx(median_of_per_pair_ratios, rel=1e-6)

    assert result["bias_to_signal_ratio_R"] == pytest.approx(ratio_of_medians, rel=1e-12)
    assert result["bias_to_signal_ratio_R"] != pytest.approx(median_of_per_pair_ratios, rel=1e-6)
    assert result["bias_to_signal_ratio_per_pair_median"] == pytest.approx(
        median_of_per_pair_ratios, rel=1e-12
    )


# ---------------------------------------------------------------------------
# Test 4: fairness_flag flips at R_star = 0.5, from real floor+eps arithmetic.
# ---------------------------------------------------------------------------


def _fairness_dataset(cell_a, cell_b, single_g, single_h):
    genes = ["F1", "F2", "F3", "F4"]
    median_library = 20.0
    block = _identity_block(genes, median_library, control_mean=[0.0] * 4)
    combo_pairs = {"GENEA_GENEB": _cells(cell_a, cell_b)}
    singles_rows = {"GENEA": _cells(single_g), "GENEB": _cells(single_h)}
    return genes, block, combo_pairs, singles_rows


def test_fairness_flag_flips_at_r_star():
    module = _load_metric_module()

    # Dataset A: real floor+eps arithmetic gives R just BELOW 0.5 -> "clear".
    genes, block, combo_pairs, singles_rows = _fairness_dataset(
        cell_a=[40.0, 21.02, 40.0, 9.38],
        cell_b=[0.2, 0.2, 0.2, 3.49],
        single_g=[40.0, 8.45, 0.2, 0.2],
        single_h=[0.2, 0.2, 25.22, 34.59],
    )
    single_effects = module._single_effects(singles_rows, block, genes)
    result_below = module._gi_and_fairness(combo_pairs, single_effects, block, genes)
    assert result_below["bias_to_signal_ratio_R"] < module._R_STAR
    assert result_below["fairness_flag"] == "clear"

    # Dataset B: real floor+eps arithmetic gives R just ABOVE 0.5 ->
    # "representation_confounded".
    genes, block, combo_pairs, singles_rows = _fairness_dataset(
        cell_a=[40.0, 18.06, 0.2, 40.0],
        cell_b=[0.2, 0.2, 0.74, 0.2],
        single_g=[0.2, 10.46, 0.2, 40.0],
        single_h=[40.0, 0.2, 18.32, 0.2],
    )
    single_effects = module._single_effects(singles_rows, block, genes)
    result_above = module._gi_and_fairness(combo_pairs, single_effects, block, genes)
    assert result_above["bias_to_signal_ratio_R"] >= module._R_STAR
    assert result_above["fairness_flag"] == "representation_confounded"

    # Sanity: both R's are close to the threshold (a real "just below/above"
    # straddle, not an arbitrarily wide margin).
    assert 0.4 < result_below["bias_to_signal_ratio_R"] < 0.5
    assert 0.5 <= result_above["bias_to_signal_ratio_R"] < 0.6


# ---------------------------------------------------------------------------
# Test 5: control is reference-only -- never a measured pair in any stratum.
# ---------------------------------------------------------------------------


def test_control_is_not_a_measured_pair():
    module = _load_metric_module()
    genes = ["G1", "G2"]
    block = _identity_block(genes, median_library=10.0, control_mean=[0.0, 0.0])

    roles = ["control", "control", "singles", "singles", "combo_calibration", "combo_calibration"]
    perturbations = ["control", "control", "GENEA", "GENEB", "GENEA_GENEB", "GENEA_GENEB"]
    X = _cells(
        [1.0, 9.0],  # control
        [2.0, 8.0],  # control
        [3.0, 7.0],  # GENEA single
        [4.0, 6.0],  # GENEB single
        [5.0, 5.0],  # GENEA_GENEB combo cell 1
        [6.0, 4.0],  # GENEA_GENEB combo cell 2
    )

    strata = module._stratify_by_role(roles, perturbations, X)

    assert "control" not in strata["combo_calibration"]
    assert "control" not in strata["singles"]
    assert set(strata["singles"]) == {"GENEA", "GENEB"}
    assert set(strata["combo_calibration"]) == {"GENEA_GENEB"}

    combo_result = module._stratum_bias(strata["combo_calibration"], block, genes)
    singles_result = module._stratum_bias(strata["singles"], block, genes)
    all_pair_ids = {e["pair_id"] for e in combo_result["per_pair"]} | {
        e["pair_id"] for e in singles_result["per_pair"]
    }
    assert "control" not in all_pair_ids


# ---------------------------------------------------------------------------
# Extra coverage: R_STAR module constant is exactly 0.5 (auditability).
# ---------------------------------------------------------------------------


def test_r_star_constant_is_one_half():
    module = _load_metric_module()
    assert module._R_STAR == 0.5
    assert math.isfinite(module._R_STAR)


# ---------------------------------------------------------------------------
# Task 2: two-stage bootstrap + NON_FINITE accounting + determinism.
# ---------------------------------------------------------------------------


def _three_pair_ratio_fixture(module):
    """The ``bias_to_signal_ratio_R``-fixture (Test 3, re-used): three combo pairs
    with deliberately different spread/mismatch so every pair's ``g_i`` is real and
    nonzero -- a well-behaved (non-degenerate) bootstrap input."""
    genes = [f"F{i}" for i in range(1, 7)]  # F1..F6, p=6
    median_library = 30.0
    control_mean = [0.0] * 6
    block = _identity_block(genes, median_library, control_mean)

    base = [5.0, 5.0, 5.0, 5.0, 5.0, 5.0]

    def _spread(dims: tuple[int, int], s: float) -> tuple[list[float], list[float]]:
        row = list(base)
        row[dims[0]] += s
        row[dims[1]] -= s
        row_swapped = list(base)
        row_swapped[dims[0]] -= s
        row_swapped[dims[1]] += s
        return row, row_swapped

    pair1_a, pair1_b = _spread((0, 1), 4.0)
    pair2_a, pair2_b = _spread((2, 3), 2.0)
    pair3_a, pair3_b = _spread((4, 5), 1.0)

    combo_pairs = {
        "P1_P2": _cells(pair1_a, pair1_b),
        "P3_P4": _cells(pair2_a, pair2_b),
        "P5_P6": _cells(pair3_a, pair3_b),
    }
    singles_rows = {
        "P1": _cells([7.0, 3.0, 5.0, 5.0, 5.0, 5.0]),
        "P2": _cells([3.0, 7.0, 5.0, 5.0, 5.0, 5.0]),
        "P3": _cells([5.0, 5.0, 9.0, 1.0, 5.0, 5.0]),
        "P4": _cells([5.0, 5.0, 1.0, 9.0, 5.0, 5.0]),
        "P5": _cells([5.0, 5.0, 5.0, 5.0, 7.0, 3.0]),
        "P6": _cells([5.0, 5.0, 5.0, 5.0, 3.0, 7.0]),
    }
    single_effects = module._single_effects(singles_rows, block, genes)
    return genes, block, combo_pairs, single_effects


def test_bootstrap_determinism_byte_identical():
    module = _load_metric_module()
    genes, block, combo_pairs, single_effects = _three_pair_ratio_fixture(module)

    result_1 = module._bootstrap_intervals(
        combo_pairs, single_effects, block, genes, seeds=[11, 23, 37], replicates=50
    )
    result_2 = module._bootstrap_intervals(
        combo_pairs, single_effects, block, genes, seeds=[11, 23, 37], replicates=50
    )

    # Byte-identical canonical-JSON serialisation across two independent calls with
    # the same seeds/replicates -- not just "==" on the dicts.
    json_1 = json.dumps(result_1, sort_keys=True, separators=(",", ":"))
    json_2 = json.dumps(result_2, sort_keys=True, separators=(",", ":"))
    assert json_1 == json_2

    # Sanity: the fixture is non-degenerate (real finite replicates + a real
    # interval), so byte-identity isn't vacuously true over all-NON_FINITE output.
    assert result_1["replicates_finite"] > 0
    assert result_1["replicates_finite"] + result_1["replicates_non_finite"] == 50
    assert isinstance(result_1["bootstrap_95_interval"]["bias_to_signal_ratio_R"], list)

    # A DIFFERENT seed roster must generally move the interval (proves the seeds are
    # actually consumed, not ignored) while still summing to the requested count.
    result_3 = module._bootstrap_intervals(
        combo_pairs, single_effects, block, genes, seeds=[999, 1000], replicates=50
    )
    assert result_3["replicates_finite"] + result_3["replicates_non_finite"] == 50
    json_3 = json.dumps(result_3, sort_keys=True, separators=(",", ":"))
    assert json_3 != json_1


def test_zero_gi_denominator_counted_non_finite():
    module = _load_metric_module()
    genes = ["F1", "F2", "F3", "F4"]
    median_library = 20.0
    control_mean = [0.0] * 4
    block = _identity_block(genes, median_library, control_mean)

    zero_row = [0.0, 0.0, 0.0, 0.0]
    # Dataset B from test_fairness_flag_flips_at_r_star ("above" R_star): real,
    # solidly nonzero GI signal (independent, hand-picked, already known-good).
    cell_a = [40.0, 18.06, 0.2, 40.0]
    cell_b = [0.2, 0.2, 0.74, 0.2]
    single_g = [0.2, 10.46, 0.2, 40.0]
    single_h = [40.0, 0.2, 18.32, 0.2]

    combo_pairs = {
        "PERTA_PERTB": _cells(zero_row),  # exact eps_i = 0 by construction below
        "PERTC_PERTD": _cells(cell_a, cell_b),
    }
    singles_rows = {
        "PERTA": _cells(zero_row),
        "PERTB": _cells(zero_row),
        "PERTC": _cells(single_g),
        "PERTD": _cells(single_h),
    }
    single_effects = module._single_effects(singles_rows, block, genes)

    # Force (not monkeypatch) a REAL degenerate zero-GI-denominator pair: PERTA,
    # PERTB, and the PERTA_PERTB combo all use the identical all-zero raw row, and
    # control_mean is exactly [0]*4, so z(zero_row) = [0]*4 (log1p(0) == 0) and every
    # one of delta_g/delta_h/delta_i is exactly `0.0 - 0.0 == 0.0` (IEEE-754 exact) ->
    # eps_i is the exact zero vector -> g_i == 0.0 exactly, not an approximation.
    point = module._gi_and_fairness(combo_pairs, single_effects, block, genes)
    zero_pair_g_i = next(
        e["g_i"] for e in point["gi_signal_per_pair"] if e["pair_id"] == "PERTA_PERTB"
    )
    assert zero_pair_g_i == 0.0

    result = module._bootstrap_intervals(
        combo_pairs, single_effects, block, genes, seeds=[11, 23, 37], replicates=300
    )

    # Nothing silently dropped: every replicate lands in exactly one bucket.
    assert (
        result["replicates_finite"] + result["replicates_non_finite"]
        == result["replicates_requested"]
        == 300
    )
    # With only 2 combo pairs (one exact-zero-g_i, one real-signal) drawn with
    # replacement, "both draws hit the zero pair" genuinely occurs across 300
    # replicates (median([0, 0]) == 0 -> zero GI denominator -> non-finite ratio),
    # and so does "at least one draw hits the real-signal pair" (finite ratio) --
    # this is a REAL degenerate branch being exercised, not a contrived 100% case.
    assert result["replicates_non_finite"] >= 1
    assert result["replicates_finite"] >= 1


def test_point_estimate_is_rng_free():
    module = _load_metric_module()
    genes, block, combo_pairs, single_effects = _three_pair_ratio_fixture(module)

    stratum_before = module._stratum_bias(combo_pairs, block, genes)
    point_before = module._gi_and_fairness(combo_pairs, single_effects, block, genes)

    module._bootstrap_intervals(
        combo_pairs, single_effects, block, genes, seeds=[11, 23, 37], replicates=25
    )
    module._bootstrap_intervals(
        combo_pairs, single_effects, block, genes, seeds=[999, 1000], replicates=40
    )

    stratum_after = module._stratum_bias(combo_pairs, block, genes)
    point_after = module._gi_and_fairness(combo_pairs, single_effects, block, genes)

    # The point estimate (signed_pc_bias / per_pair via _stratum_bias, and the full
    # _gi_and_fairness result) is byte-identical regardless of which/how many
    # bootstrap seeds were used -- the point path never consumes an RNG.
    assert stratum_after["per_pair"] == stratum_before["per_pair"]
    assert stratum_after["signed_pc_bias"] == stratum_before["signed_pc_bias"]
    assert point_after == point_before

    # The bootstrap must not mutate its inputs in place either.
    assert set(combo_pairs) == {"P1_P2", "P3_P4", "P5_P6"}
    assert set(single_effects) == {"P1", "P2", "P3", "P4", "P5", "P6"}
