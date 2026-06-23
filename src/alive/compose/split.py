"""Pair-level split with double-unseen gene isolation (COMPOSE Phase 1, §2.3).

The headline `sealed_double_unseen` role holds pairs whose BOTH genes are absent
from every `combo_calibration` pair (combo/pair-zero-shot). Selection is
outcome-independent — driven only by a seeded gene partition.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ComposeSplit:
    """Disjoint pair roles + the calibration gene set."""

    combo_calibration: list[tuple[str, str]]
    sealed_double_unseen: list[tuple[str, str]]
    secondary: list[tuple[str, str]]
    combo_genes: frozenset[str]


def build_pair_split(
    eligible_pairs: list[tuple[str, str]],
    *,
    seed: int,
    calibration_fraction: float,
) -> ComposeSplit:
    """Partition genes into calibration vs held-out, then assign pairs by role."""
    genes = sorted({g for pair in eligible_pairs for g in pair})
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(genes))
    n_cal = int(round(calibration_fraction * len(genes)))
    cal_genes = {genes[i] for i in perm[:n_cal]}

    calibration: list[tuple[str, str]] = []
    sealed: list[tuple[str, str]] = []
    secondary: list[tuple[str, str]] = []
    for a, b in eligible_pairs:
        a_in, b_in = a in cal_genes, b in cal_genes
        if a_in and b_in:
            calibration.append((a, b))
        elif not a_in and not b_in:
            sealed.append((a, b))       # double-unseen: neither gene in calibration
        else:
            secondary.append((a, b))    # single-unseen
    return ComposeSplit(
        combo_calibration=calibration,
        sealed_double_unseen=sealed,
        secondary=secondary,
        combo_genes=frozenset(cal_genes),
    )
