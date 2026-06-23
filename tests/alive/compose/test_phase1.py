"""Tests for alive.compose.phase1 — written FIRST per TDD protocol.

Preserves the four Task-9 intents: GO when all pass; headline downgrade when
underpowered; NO_GO when unmeasurable; write-once. Adapted to the actual
``RecoveryReport`` schema (Task-5 fix): the method axis is validated with TWO
synthetic runs (a rank>0 recovery run + a rank-0 false-GI guard run), not the
NaN-at-rank>0 ``false_gi_norm`` alias.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from alive.compose.config import load_compose_config
from alive.compose.phase1 import Phase1Report, run_phase1, write_phase1

_CONFIG = "configs/compose_k562_v1_phase1.yaml"


def _gate_inputs(measurable: bool = True, powered: bool = True) -> dict:
    """Outcome-independent dev-only gate inputs (no sealed roles)."""
    rng = np.random.default_rng(0)
    base = rng.normal(size=(40, 5))
    noise = 0.05 if measurable else 5.0
    return {
        "n_double_unseen_pairs": 30 if powered else 3,
        "cells_per_pair": 80.0,
        "eps_split_a": base + noise * rng.normal(size=(40, 5)),
        "eps_split_b": base + noise * rng.normal(size=(40, 5)),
    }


def test_go_when_all_pass():
    cfg = load_compose_config(_CONFIG)
    rep = run_phase1(cfg, gate_inputs=_gate_inputs())
    assert isinstance(rep, Phase1Report)
    assert rep.method_axis == "METHOD_VALIDATED"
    assert rep.go_no_go == "GO"
    assert rep.headline_regime == "double-unseen"


def test_downgrade_when_underpowered():
    cfg = load_compose_config(_CONFIG)
    rep = run_phase1(cfg, gate_inputs=_gate_inputs(powered=False))
    assert rep.headline_regime != "double-unseen"  # downgraded


def test_no_go_when_unmeasurable():
    cfg = load_compose_config(_CONFIG)
    rep = run_phase1(cfg, gate_inputs=_gate_inputs(measurable=False))
    assert rep.go_no_go == "NO_GO"


def test_write_is_write_once(tmp_path):
    cfg = load_compose_config(_CONFIG)
    rep = run_phase1(cfg, gate_inputs=_gate_inputs())
    write_phase1(rep, tmp_path)
    data = json.loads((tmp_path / "phase1_report.json").read_text())
    assert data["go_no_go"] == "GO"
    with pytest.raises(FileExistsError):
        write_phase1(rep, tmp_path)  # write-once
