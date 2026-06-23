"""Tests for alive.compose.config — written FIRST per TDD protocol."""

from __future__ import annotations

import pytest

from alive.compose.config import ComposePhase1Config, ConfigError, load_compose_config

CANON = "configs/compose_k562_v1_phase1.yaml"


def test_canonical_round_trip():
    cfg = load_compose_config(CANON)
    assert isinstance(cfg, ComposePhase1Config)
    assert cfg.calibration_fraction == 0.6
    assert cfg.min_double_unseen_pairs >= 1
    assert len(cfg.k_grid) >= 1
    assert all(k >= 1 for k in cfg.k_grid)
    assert cfg.registered_seeds  # non-empty


def test_unknown_key_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("calibration_fraction: 0.6\nbogus_key: 1\n")
    with pytest.raises(ConfigError):
        load_compose_config(p)


def test_bad_fraction_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("calibration_fraction: 1.5\n")
    with pytest.raises(ConfigError):
        load_compose_config(p)
