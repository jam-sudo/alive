"""End-to-end gene-disjoint OOF hyperparameter selection (Task 2a-8, plan §2.4).

ACTIVATION BLOCKED. Pure ``numpy``; no sealed access. Out-of-fold (OOF)
hyperparameter selection runs on **development calibration pairs only**: the
folds mirror the sealed gene-disjoint regime so the selected ``(k_total, lambda)``
is chosen the way the sealed double-unseen claim will be scored, but no sealed
outcome is ever read.

Selection executes the COMPLETE path for every ``(k_total, lambda)`` candidate
(brief steps 1–7):

1. build deterministic gene-disjoint fold train/test PAIR indices — a fold's TEST
   pairs have BOTH genes in the held-out gene group, TRAIN pairs have NEITHER
   held-out gene, and CROSS-GROUP pairs (exactly one held-out gene) are EXCLUDED
   from that fold (never silently trained on, plan §2.4);
2. fit a fresh model on the TRAIN combo outcomes only;
3. predict the held-out (test) pairs;
4. add the registered additive prediction (RESPONSE-shaped) to the model's eps
   prediction to form the double-shift prediction ``delta_hat`` — the additive is
   the comparator and is length ``p`` (response dim), never length ``k_total``
   (factor dim);
5. compute aligned per-pair errors and ``theta`` (vs additive) via
   :mod:`alive.compose.metric2` (alignment by pair ID);
6. aggregate OOF errors by pair ID across folds (each pair appears as a test pair
   in at most one fold under a disjoint gene partition);
7. select the candidate with maximum ``theta``, with the registered deterministic
   tie-break: lower ``k_total`` first, then LARGER regularization (``lambda``).

Empty folds (a retained fold must have non-empty train AND test) or an
uncovered-pair fraction above the registered tolerance INVALIDATE selection and
raise :class:`SelectionError`. The result reports the union of OOF test pairs, the
uncovered calibration pairs and the per-fold exclusions (plan §2.4).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.random import PCG64, Generator

from alive.compose.metric2 import paired_relative_error_reduction

#: A typed model factory: a zero-arg callable returning a fresh symmetric model
#: exposing ``fit(Z, pairs, eps_obs, *, lam)`` and ``predict_eps(Z, g, h)``.
ModelFactory = Callable[[], object]


class SelectionError(ValueError):
    """Raised on any invalid OOF-selection input or an invalidating fold layout.

    Covers empty/ill-typed grids, missing factor banks, dimension mismatches
    (including a factor-shaped additive added to a response-shaped prediction),
    empty folds and an uncovered-pair fraction above the registered tolerance.
    """


@dataclass(frozen=True)
class GeneDisjointFold:
    """One deterministic gene-disjoint OOF fold over calibration PAIR indices.

    Attributes
    ----------
    held_out_genes : tuple of int
        Gene indices held out for this fold (the test gene group).
    train_idx : tuple of int
        Indices (into the calibration pair list) of TRAIN pairs — both genes are
        OUTSIDE ``held_out_genes``.
    test_idx : tuple of int
        Indices of TEST pairs — both genes are INSIDE ``held_out_genes``.
    excluded_idx : tuple of int
        Indices of CROSS-GROUP pairs — exactly one gene in ``held_out_genes`` —
        excluded from this fold (never trained on, plan §2.4).
    """

    held_out_genes: tuple[int, ...]
    train_idx: tuple[int, ...]
    test_idx: tuple[int, ...]
    excluded_idx: tuple[int, ...]


@dataclass(frozen=True)
class SelectionResult:
    """Outcome of end-to-end gene-disjoint OOF hyperparameter selection.

    Attributes
    ----------
    selected_k_total : int
        Chosen total factor dimension.
    selected_lambda : float
        Chosen ridge regularization.
    theta_by_candidate : dict
        Map ``(k_total, lambda) -> OOF theta`` (paired relative error reduction of
        ``delta_hat`` vs the additive comparator, aggregated over OOF test pairs).
    union_test_pair_ids : tuple of tuple of str
        Sorted union of canonical pair IDs that appear as some fold's OOF test
        pair (the covered calibration pairs).
    uncovered_pair_ids : tuple of tuple of str
        Sorted canonical pair IDs that never appear as an OOF test pair (e.g.
        cross-group pairs); their fraction is bounded by ``uncovered_tolerance``.
    uncovered_fraction : float
        Fraction of calibration pairs that are uncovered.
    fold_exclusions : tuple of tuple of tuple of str
        Per-fold tuple of the canonical pair IDs excluded from that fold.
    n_folds : int
        Number of retained folds (every retained fold has non-empty train+test).
    """

    selected_k_total: int
    selected_lambda: float
    theta_by_candidate: dict[tuple[int, float], float]
    union_test_pair_ids: tuple[tuple[str, str], ...]
    uncovered_pair_ids: tuple[tuple[str, str], ...]
    uncovered_fraction: float
    fold_exclusions: tuple[tuple[tuple[str, str], ...], ...] = field(default=())
    n_folds: int = 0


# --------------------------------------------------------------------------- #
# fold construction
# --------------------------------------------------------------------------- #


def build_gene_disjoint_folds(
    idx_pairs: Sequence[tuple[int, int]],
    *,
    n_genes: int,
    n_folds: int,
    seed: int,
) -> list[GeneDisjointFold]:
    """Build deterministic gene-disjoint OOF folds over calibration pair indices.

    The set of genes that actually appear in ``idx_pairs`` is partitioned into
    ``n_folds`` disjoint gene groups by a seeded ``PCG64`` permutation (genes are
    first sorted so the permutation is reproducible across processes). For each
    group, a pair is a TEST pair iff BOTH its genes are in the group, a TRAIN pair
    iff NEITHER gene is in the group, and an EXCLUDED (cross-group) pair iff
    exactly one gene is in the group (plan §2.4).

    Parameters
    ----------
    idx_pairs : sequence of (int, int)
        Calibration gene-index pairs (canonical or not; treated as unordered).
    n_genes : int
        Total number of genes (the factor matrices have this many rows).
    n_folds : int
        Number of gene-disjoint folds; must be ``>= 1``.
    seed : int
        Seed for the ``PCG64`` gene-permutation generator.

    Returns
    -------
    list of GeneDisjointFold
        One fold per gene group, in group order.

    Raises
    ------
    SelectionError
        If ``n_folds < 1``, ``n_genes`` is non-positive, a pair references a gene
        index outside ``range(n_genes)``, or a pair is a self-pair.
    """
    if n_folds < 1:
        raise SelectionError(f"n_folds must be >= 1, got {n_folds}")
    if n_genes <= 0:
        raise SelectionError(f"n_genes must be positive, got {n_genes}")

    for g, h in idx_pairs:
        if not (0 <= g < n_genes) or not (0 <= h < n_genes):
            raise SelectionError(f"pair ({g}, {h}) references a gene outside [0, {n_genes})")
        if g == h:
            raise SelectionError(f"self-pair not allowed: ({g}, {h})")

    # Only genes that actually appear in calibration pairs can drive a fold.
    present = sorted({g for pair in idx_pairs for g in pair})
    rng = Generator(PCG64(seed))
    permuted = list(rng.permutation(present)) if present else []
    # round-robin into n_folds groups so groups stay balanced and deterministic
    groups: list[list[int]] = [[] for _ in range(n_folds)]
    for position, gene in enumerate(permuted):
        groups[position % n_folds].append(int(gene))

    folds: list[GeneDisjointFold] = []
    for group in groups:
        held = set(group)
        train_idx: list[int] = []
        test_idx: list[int] = []
        excluded_idx: list[int] = []
        for pi, (g, h) in enumerate(idx_pairs):
            g_in = g in held
            h_in = h in held
            if g_in and h_in:
                test_idx.append(pi)
            elif not g_in and not h_in:
                train_idx.append(pi)
            else:
                excluded_idx.append(pi)
        folds.append(
            GeneDisjointFold(
                held_out_genes=tuple(sorted(held)),
                train_idx=tuple(train_idx),
                test_idx=tuple(test_idx),
                excluded_idx=tuple(excluded_idx),
            )
        )
    return folds


# --------------------------------------------------------------------------- #
# input validation
# --------------------------------------------------------------------------- #


def _validate_inputs(
    idx_pairs: Sequence[tuple[int, int]],
    pair_ids: Sequence[tuple[str, str]],
    eps_obs: np.ndarray,
    additive: np.ndarray,
    factors_by_k: dict[int, np.ndarray],
    k_total_grid: Sequence[int],
    lambda_grid: Sequence[float],
    uncovered_tolerance: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Validate every selection input; return ``(eps_obs, additive, p)``.

    Raises
    ------
    SelectionError
        On empty grids, mismatched lengths, a missing factor bank, a factor bank
        whose column count disagrees with its ``k_total`` key, a non-2-D / empty
        target, or — the load-bearing guard — a factor-shaped ``additive`` whose
        response dimension does not match ``eps_obs`` (length ``p``). The additive
        added to the model eps MUST be response-dimensional, never factor-shaped.
    """
    if len(k_total_grid) == 0:
        raise SelectionError("k_total_grid is empty")
    if len(lambda_grid) == 0:
        raise SelectionError("lambda_grid is empty")
    if not (0.0 <= float(uncovered_tolerance) <= 1.0):
        raise SelectionError(f"uncovered_tolerance must be in [0, 1], got {uncovered_tolerance}")

    n_pairs = len(idx_pairs)
    if n_pairs == 0:
        raise SelectionError("idx_pairs is empty")
    if len(pair_ids) != n_pairs:
        raise SelectionError(f"pair_ids has {len(pair_ids)} entries for {n_pairs} pairs")
    if len(set(pair_ids)) != n_pairs:
        raise SelectionError("pair_ids contains duplicate canonical pair IDs")

    eps = np.asarray(eps_obs, dtype=np.float64)
    add = np.asarray(additive, dtype=np.float64)
    if eps.ndim != 2 or eps.shape[0] != n_pairs or eps.shape[1] == 0:
        raise SelectionError(f"eps_obs must be ({n_pairs}, p) non-empty; got shape {eps.shape}")
    p = eps.shape[1]
    # Load-bearing guard: the additive comparator/prediction is RESPONSE-shaped.
    # A factor-shaped additive (length k_total) would be silently broadcast or
    # add a factor-dim vector to a response-dim prediction; refuse it.
    if add.ndim != 2 or add.shape != (n_pairs, p):
        raise SelectionError(
            "additive must be response-dimensional (n_pairs, p) matching eps_obs "
            f"({n_pairs}, {p}); got shape {add.shape}. A factor-shaped additive "
            "(length k_total) must never be added to a response-shaped prediction."
        )
    if not np.all(np.isfinite(eps)) or not np.all(np.isfinite(add)):
        raise SelectionError("eps_obs / additive contain non-finite values")

    for k_total in k_total_grid:
        if k_total not in factors_by_k:
            raise SelectionError(f"no factor bank in factors_by_k for k_total={k_total}")
        Z = np.asarray(factors_by_k[k_total], dtype=np.float64)
        if Z.ndim != 2 or Z.shape[1] != k_total:
            raise SelectionError(
                f"factors_by_k[{k_total}] must be (n_genes, {k_total}); got shape {Z.shape}"
            )
    return eps, add, p


# --------------------------------------------------------------------------- #
# single-candidate OOF evaluation
# --------------------------------------------------------------------------- #


def _oof_theta_for_candidate(
    *,
    folds: Sequence[GeneDisjointFold],
    idx_pairs: Sequence[tuple[int, int]],
    pair_ids: Sequence[tuple[str, str]],
    eps_obs: np.ndarray,
    additive: np.ndarray,
    Z: np.ndarray,
    lam: float,
    p: int,
    model_factory: ModelFactory,
) -> tuple[float, set[tuple[str, str]]]:
    """OOF ``theta`` (vs additive) for one ``(Z, lambda)`` over all folds.

    For every fold: fit a fresh model on TRAIN combo outcomes only, predict the
    held-out TEST pairs, add the RESPONSE-shaped additive prediction to the
    model's eps prediction to form ``delta_hat`` (and the additive truth target
    ``delta = additive + eps_obs``), then accumulate the OOF predictions, the
    additive-comparator predictions and the truth — all by pair ID. ``theta`` is
    computed once over the aggregated OOF rows (alignment by pair ID).

    Returns
    -------
    (float, set)
        OOF theta and the set of covered (OOF test) canonical pair IDs.
    """
    pred_rows: list[np.ndarray] = []
    comp_rows: list[np.ndarray] = []
    truth_rows: list[np.ndarray] = []
    row_ids: list[tuple[str, str]] = []
    covered: set[tuple[str, str]] = set()

    for fold in folds:
        model = model_factory()
        train_pairs = [idx_pairs[i] for i in fold.train_idx]
        train_eps = eps_obs[list(fold.train_idx)]
        model.fit(Z, train_pairs, train_eps, lam=float(lam))

        for pi in fold.test_idx:
            g, h = idx_pairs[pi]
            eps_pred = np.asarray(model.predict_eps(Z, g, h), dtype=np.float64)
            if eps_pred.shape != (p,):
                raise SelectionError(
                    f"model eps prediction for pair {pair_ids[pi]} has shape "
                    f"{eps_pred.shape}, expected ({p},)"
                )
            # delta_hat = additive + model eps  (BOTH response-dimensional)
            delta_hat = additive[pi] + eps_pred
            # additive comparator prediction == additive (eps = 0)
            delta_truth = additive[pi] + eps_obs[pi]
            pred_rows.append(delta_hat)
            comp_rows.append(additive[pi])
            truth_rows.append(delta_truth)
            row_ids.append(pair_ids[pi])
            covered.add(pair_ids[pi])

    if not pred_rows:
        # no OOF test pair was scored for this candidate -> cannot select on it
        raise SelectionError("candidate produced no OOF test predictions (empty coverage)")

    pred = np.vstack(pred_rows)
    comp = np.vstack(comp_rows)
    truth = np.vstack(truth_rows)
    # pair_ids are stringified for the metric (alignment by ID, never by position)
    str_ids = [f"{a}|{b}" for a, b in row_ids]
    theta = paired_relative_error_reduction(
        pred,
        comp,
        truth,
        pair_ids=str_ids,
        comparator_ids=str_ids,
        truth_ids=str_ids,
    )
    return float(theta), covered


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #


def select_hyperparams(
    *,
    idx_pairs: Sequence[tuple[int, int]],
    pair_ids: Sequence[tuple[str, str]],
    eps_obs: np.ndarray,
    additive: np.ndarray,
    factors_by_k: dict[int, np.ndarray],
    k_total_grid: Sequence[int],
    lambda_grid: Sequence[float],
    n_genes: int,
    n_folds: int,
    seed: int,
    model_factory: ModelFactory,
    uncovered_tolerance: float,
) -> SelectionResult:
    """Select ``(k_total, lambda)`` by end-to-end gene-disjoint OOF (plan §2.4).

    Builds deterministic gene-disjoint folds once, then for every
    ``(k_total, lambda)`` candidate runs the COMPLETE fit -> predict -> additive ->
    metric path on calibration pairs and records the OOF ``theta`` (vs additive).
    The candidate with maximum ``theta`` is selected; ties resolve to lower
    ``k_total`` first, then LARGER regularization (``lambda``).

    Parameters
    ----------
    idx_pairs : sequence of (int, int)
        Calibration gene-index pairs (treated as unordered).
    pair_ids : sequence of (str, str)
        Canonical pair IDs (one per ``idx_pairs`` entry); must be unique.
    eps_obs : numpy.ndarray
        Observed GI (epsilon) targets, shape ``(n_pairs, p)`` — RESPONSE space.
    additive : numpy.ndarray
        Registered additive prediction per pair, shape ``(n_pairs, p)`` — must be
        RESPONSE-dimensional (length ``p``), never factor-shaped (length
        ``k_total``).
    factors_by_k : dict
        Map ``k_total -> Z`` factor matrix of shape ``(n_genes, k_total)``.
    k_total_grid : sequence of int
        Candidate total factor dimensions (e.g. the config ``total_k_grid``).
    lambda_grid : sequence of float
        Candidate ridge regularizations (e.g. the config ``lambda_grid``).
    n_genes : int
        Total number of genes.
    n_folds : int
        Number of gene-disjoint folds.
    seed : int
        Seed for deterministic fold construction.
    model_factory : callable
        Zero-arg callable returning a fresh model implementing
        ``fit(Z, pairs, eps_obs, *, lam)`` and ``predict_eps(Z, g, h)``.
    uncovered_tolerance : float
        Maximum allowed fraction of calibration pairs that are never an OOF test
        pair. An uncovered fraction strictly above this invalidates selection.

    Returns
    -------
    SelectionResult
        Selected hyperparameters, per-candidate OOF theta, and the coverage /
        exclusion report (union test pairs, uncovered pairs, fold exclusions).

    Raises
    ------
    SelectionError
        On invalid inputs (see :func:`_validate_inputs`), an empty fold (a
        retained fold must have non-empty train AND test), or an uncovered-pair
        fraction strictly above ``uncovered_tolerance``.
    """
    eps, add, p = _validate_inputs(
        idx_pairs,
        pair_ids,
        eps_obs,
        additive,
        factors_by_k,
        k_total_grid,
        lambda_grid,
        uncovered_tolerance,
    )

    folds = build_gene_disjoint_folds(idx_pairs, n_genes=n_genes, n_folds=n_folds, seed=seed)

    # Every RETAINED fold must have non-empty train AND test (plan §2.4). An empty
    # train or test fold invalidates selection rather than being silently skipped.
    for f_i, fold in enumerate(folds):
        if len(fold.train_idx) == 0 or len(fold.test_idx) == 0:
            raise SelectionError(
                f"fold {f_i} (held-out genes {fold.held_out_genes}) has empty "
                f"train ({len(fold.train_idx)}) or test ({len(fold.test_idx)}); "
                "selection invalidated"
            )

    # Coverage: union of OOF test pairs across folds, and the uncovered remainder.
    all_pair_ids = set(pair_ids)
    covered_all: set[tuple[str, str]] = set()
    for fold in folds:
        covered_all.update(pair_ids[i] for i in fold.test_idx)
    uncovered = all_pair_ids - covered_all
    uncovered_fraction = len(uncovered) / len(all_pair_ids)
    if uncovered_fraction > float(uncovered_tolerance):
        raise SelectionError(
            f"uncovered-pair fraction {uncovered_fraction:.4f} exceeds tolerance "
            f"{float(uncovered_tolerance):.4f}; selection invalidated"
        )

    theta_by_candidate: dict[tuple[int, float], float] = {}
    for k_total in k_total_grid:
        Z = np.asarray(factors_by_k[k_total], dtype=np.float64)
        if Z.shape[0] != n_genes:
            raise SelectionError(
                f"factors_by_k[{k_total}] has {Z.shape[0]} gene rows, expected {n_genes}"
            )
        for lam in lambda_grid:
            theta, _ = _oof_theta_for_candidate(
                folds=folds,
                idx_pairs=idx_pairs,
                pair_ids=pair_ids,
                eps_obs=eps,
                additive=add,
                Z=Z,
                lam=float(lam),
                p=p,
                model_factory=model_factory,
            )
            theta_by_candidate[(int(k_total), float(lam))] = theta

    # Select max theta; deterministic tie-break: lower k_total, then LARGER lambda.
    # Sort key maximizes theta, then minimizes k_total, then maximizes lambda. We
    # encode "maximize" as negation so the plain min over the key is the winner.
    def _key(candidate: tuple[int, float]) -> tuple[float, int, float]:
        k_total, lam = candidate
        theta = theta_by_candidate[candidate]
        return (-theta, k_total, -lam)

    best = min(theta_by_candidate, key=_key)

    fold_exclusions = tuple(tuple(pair_ids[i] for i in fold.excluded_idx) for fold in folds)

    return SelectionResult(
        selected_k_total=best[0],
        selected_lambda=best[1],
        theta_by_candidate=theta_by_candidate,
        union_test_pair_ids=tuple(sorted(covered_all)),
        uncovered_pair_ids=tuple(sorted(uncovered)),
        uncovered_fraction=float(uncovered_fraction),
        fold_exclusions=fold_exclusions,
        n_folds=len(folds),
    )
