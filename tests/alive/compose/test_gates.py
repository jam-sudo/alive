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
from alive.compose.split import (
    CALIBRATION_ROLE_NAME,
    ROLE_NAMES,
    SEALED_DOUBLE_UNSEEN_ROLE_NAME,
    SEALED_ROLE_NAMES,
    SEALED_SINGLE_UNSEEN_ROLE_NAME,
)


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
    res = measurability_gate(a, b, _role=CALIBRATION_ROLE_NAME)
    assert res.passed and res.detail["ceiling"] > 0.5


def test_measurability_gate_refuses_sealed_array():
    rng = np.random.default_rng(1)
    sealed = rng.normal(size=(10, 5))
    # The guard is an honest-caller `_role` contract: it fires on the `_role` STRING
    # alone (not on any array property), refusing data the caller marks as sealed.
    with pytest.raises(LeakageError):
        measurability_gate(sealed, sealed, _role="sealed_double_unseen")


@pytest.mark.parametrize(
    "role",
    [
        *SEALED_ROLE_NAMES,
        "secondary_sealed",
        "sealed_single_unseeen",
        "unknown",
        "",
    ],
)
def test_measurability_gate_refuses_every_non_calibration_role(role):
    # The gate is calibration-only. A blacklist would allow legacy names, typos
    # and future roles to bypass the leakage wall.
    rng = np.random.default_rng(2)
    sealed = rng.normal(size=(10, 5))
    with pytest.raises(LeakageError):
        measurability_gate(sealed, sealed, _role=role)


def test_measurability_gate_requires_explicit_role():
    values = np.arange(5.0)
    with pytest.raises(TypeError):
        measurability_gate(values, values)


def test_sealed_role_constants_are_consistent_across_modules():
    # Assert the semantic roster explicitly rather than deriving the expected
    # value positionally from ROLE_NAMES (which would make this test tautological).
    from alive.compose import outcome_store

    assert CALIBRATION_ROLE_NAME == "combo_calibration"
    assert SEALED_DOUBLE_UNSEEN_ROLE_NAME == "sealed_double_unseen"
    assert SEALED_SINGLE_UNSEEN_ROLE_NAME == "sealed_single_unseen"
    assert ROLE_NAMES == (
        CALIBRATION_ROLE_NAME,
        SEALED_DOUBLE_UNSEEN_ROLE_NAME,
        SEALED_SINGLE_UNSEEN_ROLE_NAME,
    )
    assert SEALED_ROLE_NAMES == (
        SEALED_DOUBLE_UNSEEN_ROLE_NAME,
        SEALED_SINGLE_UNSEEN_ROLE_NAME,
    )
    assert tuple(outcome_store._SEALED_ROLES) == SEALED_ROLE_NAMES
    assert CALIBRATION_ROLE_NAME not in outcome_store._SEALED_ROLES
