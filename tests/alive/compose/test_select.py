"""Tests for alive.compose.select — written FIRST per TDD protocol (Task 2a-8).

Covers the END-TO-END gene-disjoint OOF hyperparameter selection (plan §2.4).
The selection executes the COMPLETE fit -> predict -> additive -> metric path for
every ``(k_total, lambda)`` candidate, on calibration pairs ONLY (ACTIVATION
BLOCKED: no sealed access; OOF uses development calibration pairs).

Load-bearing invariants under test (brief + plan §2.4):

  * gene-disjoint folds — a fold's TEST pairs have BOTH genes held out; TRAIN
    pairs have NEITHER held-out gene; cross-group pairs are EXCLUDED (not silently
    trained on). No held-out gene may appear in ANY training pair of its fold.
  * ``p != k_total`` — the response/eps dimension ``p`` differs from the factor
    dimension ``k_total``; the additive prediction added to the model eps is
    response-dimensional (length ``p``), never factor-shaped (length ``k_total``).
  * known-best hyperparameter — on a constructed instance where one ``(k, lambda)``
    is clearly best, selection returns it.
  * deterministic tie-break — equal theta resolves to lower ``k_total`` then larger
    regularization (larger ``lambda``).
  * empty-fold / uncovered-pair invalidation — a fold with empty train or test, or
    an uncovered-pair fraction above the registered tolerance, raises.
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.compose.models import L1Model
from alive.compose.operator import bilinear_predict, sym_basis_dim
from alive.compose.select import (
    SelectionError,
    SelectionResult,
    build_gene_disjoint_folds,
    select_hyperparams,
)

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _canon(a: str, b: str) -> tuple[str, str]:
    """Canonical UTF-8 pair ID (min, max)."""
    return (a, b) if a.encode("utf-8") <= b.encode("utf-8") else (b, a)


def _make_instance(rng, *, n_genes=18, k=4, p=7):
    """A full-rank synthetic bilinear instance with p != k over ALL gene pairs.

    Using the COMPLETE pair set guarantees every gene-disjoint group has both
    within-group (test) and outside-group (train) pairs, so no fold is empty —
    which is the regime where end-to-end OOF selection is well-posed.

    Returns gene IDs, an index map, canonical (idx) pairs, canonical (str) pair
    IDs, the true factor matrix ``Z`` (n_genes, k), the additive prediction per
    pair (n_pairs, p) and the observed eps target (n_pairs, p) where
    ``eps = bilinear(Z_g, Z_h)``. The double truth is ``additive + eps``.
    """
    gene_ids = [f"G{i:02d}" for i in range(n_genes)]
    Z = rng.normal(size=(n_genes, k))
    coef_true = rng.normal(size=(p, sym_basis_dim(k)))
    # single-gene shifts (response space, length p) drive the additive baseline
    deltas = rng.normal(size=(n_genes, p))

    idx_pairs: list[tuple[int, int]] = [
        (i, j) for i in range(n_genes) for j in range(i + 1, n_genes)
    ]
    eps = np.vstack([bilinear_predict(coef_true, Z[g], Z[h]) for g, h in idx_pairs])
    additive = np.vstack([deltas[g] + deltas[h] for g, h in idx_pairs])
    pair_ids = [_canon(gene_ids[g], gene_ids[h]) for g, h in idx_pairs]
    return gene_ids, idx_pairs, pair_ids, Z, additive, eps


# --------------------------------------------------------------------------- #
# fold construction — gene-disjointness
# --------------------------------------------------------------------------- #


def test_folds_are_gene_disjoint_no_heldout_gene_in_training():
    """No held-out gene of a fold appears in ANY of that fold's training pairs."""
    rng = np.random.default_rng(0)
    gene_ids, idx_pairs, _, _, _, _ = _make_instance(rng)
    folds = build_gene_disjoint_folds(idx_pairs, n_genes=len(gene_ids), n_folds=5, seed=11)
    assert len(folds) == 5
    for fold in folds:
        held = set(fold.held_out_genes)
        # TEST pairs: BOTH genes held out.
        for pi in fold.test_idx:
            g, h = idx_pairs[pi]
            assert g in held and h in held
        # TRAIN pairs: NEITHER gene held out.
        for pi in fold.train_idx:
            g, h = idx_pairs[pi]
            assert g not in held and h not in held


def test_cross_group_pairs_are_excluded_not_trained():
    """Cross-group pairs (exactly one held-out gene) go to neither train nor test."""
    rng = np.random.default_rng(1)
    gene_ids, idx_pairs, _, _, _, _ = _make_instance(rng)
    folds = build_gene_disjoint_folds(idx_pairs, n_genes=len(gene_ids), n_folds=5, seed=11)
    for fold in folds:
        held = set(fold.held_out_genes)
        in_fold = set(fold.train_idx) | set(fold.test_idx)
        for pi, (g, h) in enumerate(idx_pairs):
            cross = (g in held) ^ (h in held)
            if cross:
                assert pi not in in_fold
        # excluded set is exactly the cross-group pairs
        excluded = set(fold.excluded_idx)
        expected_excluded = {pi for pi, (g, h) in enumerate(idx_pairs) if (g in held) ^ (h in held)}
        assert excluded == expected_excluded


def test_every_pair_index_accounted_for():
    """Each pair is in exactly one of train / test / excluded per fold."""
    rng = np.random.default_rng(2)
    gene_ids, idx_pairs, _, _, _, _ = _make_instance(rng)
    folds = build_gene_disjoint_folds(idx_pairs, n_genes=len(gene_ids), n_folds=4, seed=23)
    for fold in folds:
        parts = [set(fold.train_idx), set(fold.test_idx), set(fold.excluded_idx)]
        union = parts[0] | parts[1] | parts[2]
        assert union == set(range(len(idx_pairs)))
        # disjoint
        assert len(parts[0] & parts[1]) == 0
        assert len(parts[0] & parts[2]) == 0
        assert len(parts[1] & parts[2]) == 0


def test_folds_are_deterministic():
    """Same seed -> identical fold structure (cross-call determinism)."""
    rng = np.random.default_rng(3)
    gene_ids, idx_pairs, _, _, _, _ = _make_instance(rng)
    a = build_gene_disjoint_folds(idx_pairs, n_genes=len(gene_ids), n_folds=5, seed=37)
    b = build_gene_disjoint_folds(idx_pairs, n_genes=len(gene_ids), n_folds=5, seed=37)
    for fa, fb in zip(a, b):
        assert fa.held_out_genes == fb.held_out_genes
        assert fa.train_idx == fb.train_idx
        assert fa.test_idx == fb.test_idx
        assert fa.excluded_idx == fb.excluded_idx


# --------------------------------------------------------------------------- #
# end-to-end selection — p != k_total and known best
# --------------------------------------------------------------------------- #


def test_select_runs_with_p_not_equal_k_and_returns_result():
    """select_hyperparams executes the full path with p != k_total (brief)."""
    rng = np.random.default_rng(10)
    gene_ids, idx_pairs, pair_ids, Z, additive, eps = _make_instance(rng, k=4, p=7)
    assert Z.shape[1] != eps.shape[1]  # p != k_total, the load-bearing case

    result = select_hyperparams(
        idx_pairs=idx_pairs,
        pair_ids=pair_ids,
        eps_obs=eps,
        additive=additive,
        factors_by_k={4: Z},
        k_total_grid=[4],
        lambda_grid=[0.0, 0.001, 0.01, 0.1],
        n_genes=len(gene_ids),
        n_folds=3,
        seed=11,
        model_factory=lambda: L1Model(),
        uncovered_tolerance=0.9,
    )
    assert isinstance(result, SelectionResult)
    assert result.selected_k_total == 4
    assert result.selected_lambda in (0.0, 0.001, 0.01, 0.1)
    # full path produced a theta per candidate
    assert len(result.theta_by_candidate) == 4
    # union of test pairs / uncovered pairs / exclusions reported
    assert len(result.union_test_pair_ids) > 0


def test_select_picks_known_best_lambda():
    """On a noiseless full-rank L1 instance, lambda=0.0 recovers exactly.

    With p != k, the noiseless bilinear truth is recovered exactly at lambda=0.0;
    larger ridge shrinks the operator and raises OOF error, so theta is maximal at
    lambda=0.0 and selection must return it.
    """
    rng = np.random.default_rng(11)
    gene_ids, idx_pairs, pair_ids, Z, additive, eps = _make_instance(rng, n_genes=18, k=4, p=9)
    result = select_hyperparams(
        idx_pairs=idx_pairs,
        pair_ids=pair_ids,
        eps_obs=eps,
        additive=additive,
        factors_by_k={4: Z},
        k_total_grid=[4],
        lambda_grid=[0.0, 0.001, 0.01, 0.1],
        n_genes=len(gene_ids),
        n_folds=3,
        seed=11,
        model_factory=lambda: L1Model(),
        uncovered_tolerance=0.9,
    )
    # noiseless recovery: lambda=0 must be the argmax theta
    thetas = result.theta_by_candidate
    best = max(thetas, key=lambda kc: thetas[kc])
    assert best[1] == 0.0
    assert result.selected_lambda == 0.0
    # theta at the recovered optimum is ~1 (near-perfect vs additive comparator)
    assert thetas[(4, 0.0)] > 0.99


def test_select_picks_known_best_k_total():
    """A constructed instance where one k_total is clearly best is selected.

    The truth is generated from a k=4 operator. Both k=4 and k=8 factor banks are
    offered, but the k=8 bank's extra columns are pure noise uncorrelated with the
    response, raising its OOF error. The known-best k_total = 4 must be selected
    (and, given equal-or-better theta, the tie-break also favours the smaller k).
    """
    rng = np.random.default_rng(12)
    gene_ids, idx_pairs, pair_ids, Z4, additive, eps = _make_instance(rng, n_genes=18, k=4, p=8)
    # k=8 bank: the first 4 columns are the TRUE factors, the last 4 are noise
    noise = rng.normal(size=(Z4.shape[0], 4))
    Z8 = np.hstack([Z4, noise])

    result = select_hyperparams(
        idx_pairs=idx_pairs,
        pair_ids=pair_ids,
        eps_obs=eps,
        additive=additive,
        factors_by_k={4: Z4, 8: Z8},
        k_total_grid=[4, 8],
        lambda_grid=[0.001],
        n_genes=len(gene_ids),
        n_folds=3,
        seed=11,
        model_factory=lambda: L1Model(),
        uncovered_tolerance=0.9,
    )
    assert result.selected_k_total == 4


# --------------------------------------------------------------------------- #
# deterministic tie-break
# --------------------------------------------------------------------------- #


def test_tie_break_lower_k_then_larger_lambda():
    """Equal theta resolves to lower k_total, then larger regularization."""

    # A model that ignores Z entirely (and lambda) gives the SAME OOF theta for
    # every k_total -> an exact tie that the tie-break must resolve to lower k.
    class _ConstModel:
        def fit(self, Z, pairs, eps_obs, *, lam):
            self._p = eps_obs.shape[1]
            return self

        def predict_eps(self, Z, g, h):
            return np.zeros(self._p)

    rng = np.random.default_rng(13)
    gene_ids, idx_pairs, pair_ids, Z4, additive, eps = _make_instance(rng, k=4, p=6)
    Z6 = rng.normal(size=(Z4.shape[0], 6))  # distinct bank; model ignores it
    result = select_hyperparams(
        idx_pairs=idx_pairs,
        pair_ids=pair_ids,
        eps_obs=eps,
        additive=additive,
        factors_by_k={4: Z4, 6: Z6},
        k_total_grid=[4, 6],
        lambda_grid=[0.0],
        n_genes=len(gene_ids),
        n_folds=3,
        seed=11,
        model_factory=lambda: _ConstModel(),
        uncovered_tolerance=0.9,
    )
    # exact tie in theta (model ignores k_total) -> lower k_total wins
    assert np.isclose(result.theta_by_candidate[(4, 0.0)], result.theta_by_candidate[(6, 0.0)])
    assert result.selected_k_total == 4


def test_tie_break_larger_lambda_when_k_equal():
    """When k_total is tied and theta is tied, larger lambda wins."""

    # A degenerate model that ignores lambda and predicts additive's complement so
    # theta is identical for every lambda -> the tie-break must pick the LARGEST
    # lambda within the same k_total.
    class _ConstModel:
        def fit(self, Z, pairs, eps_obs, *, lam):
            self._p = eps_obs.shape[1]
            return self

        def predict_eps(self, Z, g, h):
            return np.zeros(self._p)

    rng = np.random.default_rng(14)
    gene_ids, idx_pairs, pair_ids, Z, additive, eps = _make_instance(rng, k=4, p=5)
    result = select_hyperparams(
        idx_pairs=idx_pairs,
        pair_ids=pair_ids,
        eps_obs=eps,
        additive=additive,
        factors_by_k={4: Z},
        k_total_grid=[4],
        lambda_grid=[0.0, 0.001, 0.01, 0.1],
        n_genes=len(gene_ids),
        n_folds=3,
        seed=11,
        model_factory=lambda: _ConstModel(),
        uncovered_tolerance=0.9,
    )
    # all lambdas give the same theta (model ignores lambda) -> largest lambda wins
    vals = list(result.theta_by_candidate.values())
    assert all(np.isclose(v, vals[0]) for v in vals)
    assert result.selected_k_total == 4
    assert result.selected_lambda == 0.1


# --------------------------------------------------------------------------- #
# response-dimensionality guard — never add factor-shaped to response-shaped
# --------------------------------------------------------------------------- #


def test_additive_must_be_response_dimensional_not_factor_shaped():
    """additive shaped (n_pairs, k_total) instead of (n_pairs, p) is rejected.

    The δ̂ formed by adding additive to the model eps must be RESPONSE-dimensional;
    a factor-shaped additive (length k_total) is a hard error, never broadcast.
    """
    rng = np.random.default_rng(15)
    gene_ids, idx_pairs, pair_ids, Z, _, eps = _make_instance(rng, k=4, p=7)
    bad_additive = rng.normal(size=(len(idx_pairs), 4))  # k_total, not p
    with pytest.raises(SelectionError):
        select_hyperparams(
            idx_pairs=idx_pairs,
            pair_ids=pair_ids,
            eps_obs=eps,
            additive=bad_additive,
            factors_by_k={4: Z},
            k_total_grid=[4],
            lambda_grid=[0.0],
            n_genes=len(gene_ids),
            n_folds=5,
            seed=11,
            model_factory=lambda: L1Model(),
            uncovered_tolerance=0.7,
        )


# --------------------------------------------------------------------------- #
# invalidation — empty folds and uncovered-pair fraction
# --------------------------------------------------------------------------- #


def test_empty_fold_invalidates_selection():
    """Too many folds (fewer test pairs than folds) yields an empty fold -> raise."""
    rng = np.random.default_rng(16)
    # 3 genes -> only pair (0,1),(0,2),(1,2); asking for 5 folds forces empties
    gene_ids = ["A", "B", "C"]
    idx_pairs = [(0, 1), (0, 2), (1, 2)]
    pair_ids = [_canon(gene_ids[g], gene_ids[h]) for g, h in idx_pairs]
    eps = rng.normal(size=(3, 5))
    additive = rng.normal(size=(3, 5))
    Z = rng.normal(size=(3, 4))
    with pytest.raises(SelectionError):
        select_hyperparams(
            idx_pairs=idx_pairs,
            pair_ids=pair_ids,
            eps_obs=eps,
            additive=additive,
            factors_by_k={4: Z},
            k_total_grid=[4],
            lambda_grid=[0.0],
            n_genes=len(gene_ids),
            n_folds=5,
            seed=11,
            model_factory=lambda: L1Model(),
            uncovered_tolerance=0.9,
        )


def test_uncovered_pair_fraction_above_tolerance_invalidates():
    """If too few pairs are covered as OOF test, selection invalidates."""
    rng = np.random.default_rng(17)
    gene_ids, idx_pairs, pair_ids, Z, additive, eps = _make_instance(rng, k=4, p=6)
    # a 0.0 tolerance demands EVERY calibration pair be covered as some fold's test
    # pair; gene-disjoint folds inevitably leave cross-group pairs uncovered, so a
    # zero tolerance must invalidate.
    with pytest.raises(SelectionError):
        select_hyperparams(
            idx_pairs=idx_pairs,
            pair_ids=pair_ids,
            eps_obs=eps,
            additive=additive,
            factors_by_k={4: Z},
            k_total_grid=[4],
            lambda_grid=[0.0],
            n_genes=len(gene_ids),
            n_folds=5,
            seed=11,
            model_factory=lambda: L1Model(),
            uncovered_tolerance=0.0,
        )


def test_empty_grid_rejected():
    """Empty k_total or lambda grid is a hard error."""
    rng = np.random.default_rng(18)
    gene_ids, idx_pairs, pair_ids, Z, additive, eps = _make_instance(rng, k=4, p=6)
    with pytest.raises(SelectionError):
        select_hyperparams(
            idx_pairs=idx_pairs,
            pair_ids=pair_ids,
            eps_obs=eps,
            additive=additive,
            factors_by_k={4: Z},
            k_total_grid=[],
            lambda_grid=[0.0],
            n_genes=len(gene_ids),
            n_folds=5,
            seed=11,
            model_factory=lambda: L1Model(),
            uncovered_tolerance=0.7,
        )


def test_missing_factor_bank_for_k_rejected():
    """A k_total in the grid with no factor bank in factors_by_k is rejected."""
    rng = np.random.default_rng(19)
    gene_ids, idx_pairs, pair_ids, Z, additive, eps = _make_instance(rng, k=4, p=6)
    with pytest.raises(SelectionError):
        select_hyperparams(
            idx_pairs=idx_pairs,
            pair_ids=pair_ids,
            eps_obs=eps,
            additive=additive,
            factors_by_k={4: Z},  # no bank for k=8
            k_total_grid=[4, 8],
            lambda_grid=[0.0],
            n_genes=len(gene_ids),
            n_folds=5,
            seed=11,
            model_factory=lambda: L1Model(),
            uncovered_tolerance=0.7,
        )
