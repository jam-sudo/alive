"""Tests for alive.compose.config — written FIRST per TDD protocol."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

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


def test_the_phase1_measurability_ceiling_floor_is_registered_in_the_config():
    """F-A3: the Phase-1 gate floor is a config value, not a source constant."""
    cfg = load_compose_config(CANON)
    assert cfg.measurability_ceiling_floor == 0.2


def test_a_phase1_config_without_the_measurability_ceiling_floor_is_refused(tmp_path):
    raw = yaml.safe_load(Path(CANON).read_text(encoding="utf-8"))
    del raw["measurability_ceiling_floor"]
    p = tmp_path / "no_floor.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="measurability_ceiling_floor"):
        load_compose_config(p)
