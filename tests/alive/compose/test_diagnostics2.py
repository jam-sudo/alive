"""Tests for alive.compose.diagnostics2 — written FIRST per TDD protocol (Task 2a-9).

Real calibration diagnostics + futility checkpoint on DEVELOPMENT-role inputs only.
SYNTHETIC-ONLY: pure ``numpy`` on synthetic inputs; NO sealed access.

Load-bearing contracts under test (brief Task 9 + spec §10.4 / §10.6):

  * CONTINUE iff every registered gate passes — full-rank selected-dimension design
    AND measurable split-half AND OOF theta > 0.
  * each individual failure path returns FUTILITY_STOPPED:
      - rank-deficient calibration design (rank < sym_dim);
      - non-finite conditioning (condition number not finite);
      - measurability below the registered floor;
      - OOF primary theta <= 0.
  * the result carries ``sealed_access_count == 0`` and exposes NO sealed-verdict
    field — a FUTILITY_STOPPED development stop can never be confused with the
    sealed-axis NO_DISTINCT_WIN.
  * a sealed-role input to the measurability step is REFUSED (LeakageError).
  * the retained singular-value spectrum + rank tolerance are reported.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from alive.compose.diagnostics2 import (
    FutilityResult,
    real_calibration_diagnostics,
)
from alive.compose.gates import LeakageError
from alive.compose.models import L1Model
from alive.compose.operator import bilinear_predict, sym_basis_dim
from alive.compose.split import CALIBRATION_ROLE_NAME


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _canon(a: str, b: str) -> tuple[str, str]:
    """Canonical UTF-8 pair ID (min, max)."""
    return (a, b) if a.encode("utf-8") <= b.encode("utf-8") else (b, a)


def _l1_factory():
    return L1Model()


def _full_rank_instance(rng, *, n_genes=18, k=4, p=7, noise=0.02):
    """Full-rank synthetic bilinear instance over ALL gene pairs (p != k).

    The complete pair set guarantees every gene-disjoint OOF group has both
    within-group (test) and outside-group (train) pairs (no empty fold), and that
    the calibration design matrix Phi is full rank for k=4 (sym_dim=10).

    Returns a dict of all inputs ``real_calibration_diagnostics`` needs plus the
    two split-half eps arrays (a strongly shared signal -> measurable).
    """
    gene_ids = [f"G{i:02d}" for i in range(n_genes)]
    Z = rng.normal(size=(n_genes, k))
    # symmetric ground-truth operator B_m for each of the p outputs
    B = rng.normal(size=(p, k, k))
    B = 0.5 * (B + np.transpose(B, (0, 2, 1)))
    coef = np.vstack([_sym_to_vec(B[m]) for m in range(p)])

    idx_pairs: list[tuple[int, int]] = []
    pair_ids: list[tuple[str, str]] = []
    for i in range(n_genes):
        for j in range(i + 1, n_genes):
            idx_pairs.append((i, j))
            pair_ids.append(_canon(gene_ids[i], gene_ids[j]))

    eps = np.vstack([bilinear_predict(coef, Z[g], Z[h]) for g, h in idx_pairs])
    additive = rng.normal(size=eps.shape)  # response-shaped additive comparator

    # two development split-half eps estimates: shared signal + independent noise
    eps_a = eps + noise * rng.normal(size=eps.shape)
    eps_b = eps + noise * rng.normal(size=eps.shape)

    factors_by_k = {k: Z}
    return {
        "idx_pairs": idx_pairs,
        "pair_ids": pair_ids,
        "eps_obs": eps,
        "additive": additive,
        "factors_by_k": factors_by_k,
        "k_total_grid": [k],
        "lambda_grid": [0.0, 1e-3],
        "n_genes": n_genes,
        "n_folds": 3,
        "seed": 11,
        "model_factory": _l1_factory,
        "uncovered_tolerance": 1.0,
        "eps_split_a": eps_a,
        "eps_split_b": eps_b,
        "selected_k_total": k,
    }


def _sym_to_vec(B: np.ndarray) -> np.ndarray:
    """Mirror alive.compose.operator._sym_to_vec for building a truth operator."""
    k = B.shape[0]
    iu = np.triu_indices(k)
    out = B[iu].astype(np.float64).copy()
    off = iu[0] != iu[1]
    out[off] *= np.sqrt(2.0)
    return out


def _run(inst, **overrides):
    kwargs = {
        "idx_pairs": inst["idx_pairs"],
        "pair_ids": inst["pair_ids"],
        "eps_obs": inst["eps_obs"],
        "additive": inst["additive"],
        "factors_by_k": inst["factors_by_k"],
        "k_total_grid": inst["k_total_grid"],
        "lambda_grid": inst["lambda_grid"],
        "n_genes": inst["n_genes"],
        "n_folds": inst["n_folds"],
        "seed": inst["seed"],
        "model_factory": inst["model_factory"],
        "uncovered_tolerance": inst["uncovered_tolerance"],
        "eps_split_a": inst["eps_split_a"],
        "eps_split_b": inst["eps_split_b"],
        "measurability_role": CALIBRATION_ROLE_NAME,
        # The registered floor (config ``futility.measurability_ceiling_floor``).
        # Its own behaviour is pinned in ``test_gates.py``; here it is threaded
        # explicitly because the diagnostics entry point has no default.
        "measurability_ceiling_floor": 0.2,
        "unregularized_oof_rank_policy": "require_full_rank_each_train_fold",
        "rank_tolerance_rule": "max_shape_times_float64_eps_times_sigma_max",
        "lambda_scaling": "calibration_sigma_max_squared",
        # Effectively unbounded, so the tests in THIS file keep testing what they
        # were written to test. The ceiling itself is exercised in
        # ``test_condition_ceiling.py`` against the registered 1.0e8. Finite, not
        # ``inf``: selection refuses a non-finite ceiling precisely because it
        # would silence the screen rather than widen it.
        "condition_ceiling": 1e300,
    }
    kwargs.update(overrides)
    return real_calibration_diagnostics(**kwargs)


# --------------------------------------------------------------------------- #
# CONTINUE when every gate passes
# --------------------------------------------------------------------------- #
def test_continue_when_all_gates_pass():
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    res = _run(inst)

    assert isinstance(res, FutilityResult)
    assert res.status == "CONTINUE"
    # full-rank selected dimension
    assert res.rank_report.is_full_rank
    assert res.rank_report.rank == sym_basis_dim(inst["selected_k_total"])
    assert np.isfinite(res.rank_report.condition_number)
    # measurable
    assert res.measurability.passed
    # OOF theta > 0 (L1 recovers the bilinear signal vs additive)
    assert res.oof_theta > 0.0
    assert not res.failures


def test_continue_retains_spectrum_and_tolerance():
    rng = np.random.default_rng(1)
    inst = _full_rank_instance(rng)
    res = _run(inst)
    # singular-value spectrum + tolerance retained
    assert res.singular_values.ndim == 1
    assert res.singular_values.size == sym_basis_dim(inst["selected_k_total"])
    assert np.all(np.diff(res.singular_values) <= 1e-9)  # descending
    assert res.rank_tolerance > 0.0


# --------------------------------------------------------------------------- #
# failure paths -> FUTILITY_STOPPED
# --------------------------------------------------------------------------- #
def test_rank_deficient_design_is_futility_stopped():
    rng = np.random.default_rng(2)
    inst = _full_rank_instance(rng)
    # Collapse every gene factor to a 1-D line -> outer products span < sym_dim.
    Z = inst["factors_by_k"][inst["selected_k_total"]]
    v = rng.normal(size=Z.shape[1])
    rank1 = np.outer(rng.normal(size=Z.shape[0]), v)  # all rows colinear
    inst["factors_by_k"] = {inst["selected_k_total"]: rank1}
    res = _run(inst)
    assert res.status == "FUTILITY_STOPPED"
    assert not res.rank_report.is_full_rank
    assert any("rank" in f.lower() for f in res.failures)


def test_exactly_singular_design_stops_for_futility_instead_of_raising():
    """A design whose normal equations are singular must not abort the checkpoint.

    ``np.linalg.solve`` reports exact singularity on some LAPACK builds and
    returns an arbitrary vector on others, so before the estimator normalised
    that outcome this path raised ``LinAlgError`` on one machine and reached the
    rank gate on another. A zero factor bank makes the Gram matrix exactly zero
    at ``lam=0``, which every LAPACK reports, so this pins the portable result.
    """
    rng = np.random.default_rng(7)
    inst = _full_rank_instance(rng)
    Z = inst["factors_by_k"][inst["selected_k_total"]]
    inst["factors_by_k"] = {inst["selected_k_total"]: np.zeros_like(Z)}
    res = _run(inst)
    assert res.status == "FUTILITY_STOPPED"
    assert not res.rank_report.is_full_rank
    assert any("rank" in f.lower() for f in res.failures)
    # The singular lam=0 candidate scored non-viable and lost to the regularised
    # one, which is solvable; the rank gate then stopped the study anyway.
    assert res.selected_lambda == 1e-3
    assert len(res.nonviable_candidates) == 1
    k_total, lam, reason = res.nonviable_candidates[0]
    assert (k_total, lam) == (inst["selected_k_total"], 0.0)
    assert "OOF train fold 0" in reason
    assert "non-identifiable" in reason


def test_non_finite_conditioning_is_futility_stopped():
    rng = np.random.default_rng(3)
    inst = _full_rank_instance(rng)
    # A rank-deficient design reports condition_number == inf (Phase-1 F3);
    # use a 2-distinct-row factor bank so rank << sym_dim and cond is non-finite.
    Z = inst["factors_by_k"][inst["selected_k_total"]]
    base = rng.normal(size=(2, Z.shape[1]))
    rows = base[rng.integers(0, 2, size=Z.shape[0])]
    inst["factors_by_k"] = {inst["selected_k_total"]: rows}
    res = _run(inst)
    assert res.status == "FUTILITY_STOPPED"
    assert not np.isfinite(res.rank_report.condition_number)
    assert any("condition" in f.lower() or "rank" in f.lower() for f in res.failures)


def test_measurability_failure_is_futility_stopped():
    rng = np.random.default_rng(4)
    inst = _full_rank_instance(rng)
    # Replace the split halves with pure independent noise -> no shared signal.
    shape = inst["eps_split_a"].shape
    inst["eps_split_a"] = rng.normal(size=shape)
    inst["eps_split_b"] = rng.normal(size=shape)
    res = _run(inst)
    assert res.status == "FUTILITY_STOPPED"
    assert not res.measurability.passed
    assert any("measur" in f.lower() for f in res.failures)


def test_oof_theta_nonpositive_is_futility_stopped():
    rng = np.random.default_rng(5)
    inst = _full_rank_instance(rng)
    # Destroy the bilinear signal: random eps targets, so L1 cannot beat additive
    # out-of-fold and OOF theta <= 0. Keep the design full rank and measurable.
    inst["eps_obs"] = rng.normal(size=inst["eps_obs"].shape)
    res = _run(inst)
    assert res.status == "FUTILITY_STOPPED"
    assert res.oof_theta <= 0.0
    assert any("theta" in f.lower() for f in res.failures)


# --------------------------------------------------------------------------- #
# sealed-access discipline: count zero, NO sealed verdict, leakage refusal
# --------------------------------------------------------------------------- #
def test_result_records_zero_sealed_access_and_no_sealed_verdict():
    rng = np.random.default_rng(6)
    inst = _full_rank_instance(rng)
    res = _run(inst)
    assert res.sealed_access_count == 0

    field_names = {f.name for f in dataclasses.fields(res)}
    # No field that could carry a sealed verdict (NO_DISTINCT_WIN / GI_LEARNABLE_WIN).
    forbidden = {"sealed_verdict", "verdict", "sealed_axis", "no_distinct_win"}
    assert not (field_names & forbidden)
    # The status itself is never a sealed-axis verdict value.
    assert res.status in {"CONTINUE", "FUTILITY_STOPPED"}
    for sealed_value in ("NO_DISTINCT_WIN", "GI_LEARNABLE_WIN", "PARTIAL", "INVALID"):
        assert res.status != sealed_value


def test_futility_result_zero_access_even_when_stopped():
    rng = np.random.default_rng(7)
    inst = _full_rank_instance(rng)
    inst["eps_obs"] = rng.normal(size=inst["eps_obs"].shape)  # force theta<=0 stop
    res = _run(inst)
    assert res.status == "FUTILITY_STOPPED"
    assert res.sealed_access_count == 0  # a development stop never opens a seal


def test_measurability_refuses_sealed_role():
    rng = np.random.default_rng(8)
    inst = _full_rank_instance(rng)
    # Passing a sealed measurability role must hard-fail (leakage guard, §2.4).
    with pytest.raises(LeakageError):
        _run(inst, measurability_role="sealed_double_unseen")
