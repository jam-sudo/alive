"""Tests for alive.compose.gates — written FIRST per TDD protocol.

Includes a leakage test: the measurability gate must refuse sealed arrays.
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.compose.gates import (
    GateResult,
    LeakageError,
    measurability_gate,
    power_gate,
    rank_gate,
)
from alive.compose.identify import RankReport


def test_power_gate_pass_and_fail():
    ok = power_gate(30, 80, min_pairs=20, min_cells=50)
    assert isinstance(ok, GateResult) and ok.passed
    bad = power_gate(5, 80, min_pairs=20, min_cells=50)
    assert not bad.passed and "downgrade" in bad.recommendation.lower()


def test_rank_gate():
    full = rank_gate(RankReport(sym_dim=10, rank=10, is_full_rank=True, condition_number=3.0))
    assert full.passed
    deficient = rank_gate(RankReport(sym_dim=10, rank=4, is_full_rank=False, condition_number=1e9))
    assert not deficient.passed


def test_measurability_gate_signal_vs_noise():
    rng = np.random.default_rng(0)
    # strong shared signal across halves -> measurable
    base = rng.normal(size=(40, 5))
    a = base + 0.05 * rng.normal(size=(40, 5))
    b = base + 0.05 * rng.normal(size=(40, 5))
    res = measurability_gate(a, b)
    assert res.passed and res.detail["ceiling"] > 0.5


def test_measurability_gate_refuses_sealed_array():
    rng = np.random.default_rng(1)
    sealed = rng.normal(size=(10, 5))
    # The guard is an honest-caller `_role` contract: it fires on the `_role` STRING
    # alone (not on any array property), refusing data the caller marks as sealed.
    with pytest.raises(LeakageError):
        measurability_gate(sealed, sealed, _role="sealed_double_unseen")
