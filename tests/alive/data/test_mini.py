"""Tests for mini-dataset selection logic (A100 prep, Gate D).

A mini dataset is a small, deterministic, eligibility-preserving subset of the
full Perturb-seq AnnData used to validate the whole pipeline end-to-end with the
REAL encoder before the full run (CLAUDE.md §14.2).
"""

from __future__ import annotations

import numpy as np

from alive.data.mini import select_mini_perturbations, subset_cells_mask


def test_select_respects_min_cells_and_usable_sequence() -> None:
    counts = {"A": 100, "B": 80, "C": 10, "D": 200}
    usable = {"A", "B", "C"}  # D has no usable sequence
    # eligible = A(100), B(80) ; C<64 excluded ; D not usable
    sel = select_mini_perturbations(counts, usable, min_cells=64, n_perturbations=5, seed=0)
    assert sel == ["A", "B"]


def test_select_subsamples_deterministically() -> None:
    counts = {f"G{i:02d}": 100 for i in range(20)}
    usable = set(counts)
    a = select_mini_perturbations(counts, usable, min_cells=64, n_perturbations=5, seed=7)
    b = select_mini_perturbations(counts, usable, min_cells=64, n_perturbations=5, seed=7)
    assert a == b  # deterministic
    assert len(a) == 5
    assert a == sorted(a)  # returned sorted
    assert set(a) <= set(counts)


def test_subset_mask_keeps_selected_perts_and_capped_controls() -> None:
    labels = np.array(["ctrl"] * 300 + ["A"] * 100 + ["B"] * 80 + ["C"] * 10)
    mask = subset_cells_mask(
        labels,
        control_value="ctrl",
        selected_perts={"A"},
        control_cap=50,
        per_pert_cap=None,
        seed=0,
    )
    assert mask.dtype == bool
    assert mask.sum() == 100 + 50  # all of A + 50 controls
    # only A and ctrl cells selected
    kept = set(labels[mask])
    assert kept == {"A", "ctrl"}


def test_subset_mask_caps_per_pert() -> None:
    labels = np.array(["ctrl"] * 100 + ["A"] * 100)
    mask = subset_cells_mask(
        labels,
        control_value="ctrl",
        selected_perts={"A"},
        control_cap=None,
        per_pert_cap=30,
        seed=1,
    )
    # 30 of A + all 100 controls
    assert (labels[mask] == "A").sum() == 30
    assert (labels[mask] == "ctrl").sum() == 100
