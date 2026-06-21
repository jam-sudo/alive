"""Mini-dataset selection logic (A100 prep, Gate D — CLAUDE.md §14.2).

A mini dataset is a small, deterministic, *eligibility-preserving* subset of the
full Perturb-seq AnnData: only perturbations that pass ``min_cells`` AND have a
usable protein sequence are eligible, so the mini end-to-end run exercises the
same code path (real encoder, four-way split, seal) as the full run on a few
hundred cells.  Pure selection logic here; ``scripts/make_mini.py`` does the I/O.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

import numpy as np


def select_mini_perturbations(
    perturbation_counts: Mapping[str, int],
    usable_gene_ids: Collection[str],
    *,
    min_cells: int,
    n_perturbations: int,
    seed: int,
) -> list[str]:
    """Pick up to ``n_perturbations`` eligible perturbations, deterministically.

    Eligible = at least ``min_cells`` cells AND a usable protein sequence.
    Returns a sorted list (a deterministic seeded subsample when more than
    ``n_perturbations`` are eligible).
    """
    usable = set(usable_gene_ids)
    eligible = sorted(g for g, c in perturbation_counts.items() if c >= min_cells and g in usable)
    if len(eligible) <= n_perturbations:
        return eligible
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(eligible), size=n_perturbations, replace=False)
    return sorted(eligible[i] for i in idx)


def subset_cells_mask(
    labels: np.ndarray,
    *,
    control_value: str,
    selected_perts: Collection[str],
    control_cap: int | None,
    per_pert_cap: int | None,
    seed: int,
) -> np.ndarray:
    """Boolean cell mask keeping the selected perturbations + (capped) controls.

    Parameters
    ----------
    labels : numpy.ndarray
        Per-cell perturbation labels (length n_cells).
    control_value : str
        The control label.
    selected_perts : Collection[str]
        Perturbations to keep.
    control_cap, per_pert_cap : int or None
        Optional per-group cell caps (``None`` keeps all).  When a group exceeds
        its cap it is deterministically subsampled.
    seed : int
        Seed for the subsampling.

    Returns
    -------
    numpy.ndarray
        Boolean mask of length ``len(labels)``.
    """
    labels = np.asarray(labels)
    selected = set(selected_perts)
    mask = np.zeros(len(labels), dtype=bool)
    rng = np.random.default_rng(seed)

    def _keep(group_idx: np.ndarray, cap: int | None) -> None:
        if cap is not None and group_idx.size > cap:
            group_idx = np.sort(rng.choice(group_idx, size=cap, replace=False))
        mask[group_idx] = True

    # deterministic group order
    for pert in sorted(selected):
        _keep(np.flatnonzero(labels == pert), per_pert_cap)
    _keep(np.flatnonzero(labels == control_value), control_cap)
    return mask
