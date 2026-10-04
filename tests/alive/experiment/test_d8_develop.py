"""Tests for outcome-free D8 trust features."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

_PATH = Path(__file__).resolve().parents[3] / "scripts" / "cartographer" / "d8_develop.py"
_SPEC = importlib.util.spec_from_file_location("d8_develop", _PATH)
dv = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dv)


def test_build_features_columns_and_analytic_sigma():
    h = np.array([0.5, -0.3, 0.0])
    x, sigma = dv.build_features(
        h,
        n_cells=100,
        noise_var=np.array([1.0, 4.0, 0.25]),
        ctrl_mean=np.zeros(3),
        n_ref=100,
        exposure="base_train",
        tau=0.2,
    )
    assert np.allclose(sigma, np.sqrt(np.array([1.0, 4.0, 0.25]) * 0.02))
    assert x.shape == (3, 6 + len(dv.EXPOSURE_GROUPS))
    assert x[:, 1].tolist() == [1.0, 0.0, 0.0] and x[:, 2].tolist() == [0.0, 1.0, 0.0]
    assert x[:, 6].tolist() == [1.0, 1.0, 1.0] and x[:, 7:].sum() == 0


def test_build_features_appends_predictor_internal_spread():
    x, _ = dv.build_features(
        np.zeros(2),
        50,
        np.ones(2),
        np.zeros(2),
        50,
        "sealed_evaluation",
        0.2,
        extra=[np.array([0.1, 0.2]), np.array([0.3, 0.4])],
    )
    assert x.shape[1] == 6 + len(dv.EXPOSURE_GROUPS) + 2
    assert x[:, -1].tolist() == [0.3, 0.4]
