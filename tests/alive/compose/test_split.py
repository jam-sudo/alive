"""Tests for alive.compose.split — written FIRST per TDD protocol.

Enforces the double-unseen gene-isolation invariant (spec §2.3) and leakage.
"""
from __future__ import annotations

from alive.compose.split import ComposeSplit, build_pair_split


def _pairs():
    genes = [chr(ord("A") + i) for i in range(8)]
    return [(genes[i], genes[j]) for i in range(8) for j in range(i + 1, 8)]


def test_roles_disjoint_and_cover():
    sp = build_pair_split(_pairs(), seed=0, calibration_fraction=0.6)
    assert isinstance(sp, ComposeSplit)
    all_pairs = set(_pairs())
    union = set(sp.combo_calibration) | set(sp.sealed_double_unseen) | set(sp.secondary)
    assert union <= all_pairs
    assert not (set(sp.combo_calibration) & set(sp.sealed_double_unseen))


def test_double_unseen_genes_isolated_from_calibration():
    sp = build_pair_split(_pairs(), seed=1, calibration_fraction=0.6)
    cal_genes = {g for pair in sp.combo_calibration for g in pair}
    for a, b in sp.sealed_double_unseen:
        assert a not in cal_genes and b not in cal_genes  # gene isolation invariant
