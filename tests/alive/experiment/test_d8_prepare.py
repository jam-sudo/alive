"""Tests for the metadata-only D8 PREPARE helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import h5py
import numpy as np
import pytest

_PATH = Path(__file__).resolve().parents[3] / "scripts" / "cartographer" / "d8_prepare.py"
_SPEC = importlib.util.spec_from_file_location("d8_prepare", _PATH)
dp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dp)


def test_cell_count_band_assigns_registered_bands():
    bands = [[30, 100], [100, 260], [260, None]]
    assert dp.cell_count_band(30, bands) == "30-100"
    assert dp.cell_count_band(259, bands) == "100-260"
    assert dp.cell_count_band(5000, bands) == "260-"
    with pytest.raises(ValueError):
        dp.cell_count_band(12, bands)


def test_read_obs_labels_supports_legacy_categoricals_without_touching_x(tmp_path):
    path = tmp_path / "legacy.h5ad"
    with h5py.File(path, "w") as f:
        obs = f.create_group("obs")
        obs.create_dataset("gene", data=np.array([0, 1, 1], dtype="int16"))
        obs.create_group("__categories").create_dataset("gene", data=[b"A", b"non-targeting"])
        obs.create_dataset("gem_group", data=np.array([3, 3, 4]))
    codes, cats, gem = dp.read_obs_labels(path)
    assert codes.tolist() == [0, 1, 1] and cats == ["A", "non-targeting"]
    assert gem.tolist() == [3, 3, 4]
