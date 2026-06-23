"""Tests for alive.data.norman — written FIRST per TDD protocol.

Uses a tiny synthetic AnnData; no real download.
"""
from __future__ import annotations

import numpy as np

from alive.data.norman import (
    eligible_genes,
    eligible_pairs,
    parse_labels,
    single_effects,
)


def _toy():
    labels = np.array(
        ["ctrl"] * 4 + ["A"] * 3 + ["B"] * 3 + ["A+B"] * 2 + ["A+C"] * 1, dtype=object
    )
    X = np.arange(labels.size * 2, dtype=np.float64).reshape(labels.size, 2)
    return labels, X


def test_parse_labels():
    labels, X = _toy()
    singles, doubles, ctrl = parse_labels(labels, control_token="ctrl", combo_sep="+")
    assert set(singles) == {"A", "B"}
    assert set(doubles) == {("A", "B"), ("A", "C")}
    assert ctrl.tolist() == [0, 1, 2, 3]


def test_single_effects_shape():
    labels, X = _toy()
    singles, doubles, ctrl = parse_labels(labels, control_token="ctrl", combo_sep="+")
    eff = single_effects(X, singles, ctrl)
    assert set(eff) == {"A", "B"}
    assert eff["A"].shape == (2,)


def test_eligibility_is_outcome_independent():
    labels, X = _toy()
    singles, doubles, ctrl = parse_labels(labels, control_token="ctrl", combo_sep="+")
    # min_cells=3 keeps A,B; require feature availability for A,B only
    genes = eligible_genes(singles, min_cells=3, available_feature_ids={"A", "B"})
    assert genes == ["A", "B"]
    # ("A","B") has 2 cells; with min_cells=2 it is eligible, ("A","C") drops (C ineligible)
    pairs = eligible_pairs(doubles, set(genes), min_cells=2)
    assert pairs == [("A", "B")]
