"""Known answers for the v2 analytic noise baselines."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np

_PATH = Path(__file__).resolve().parents[3] / "scripts" / "cartographer" / "d8_develop_v2.py"
_SPEC = importlib.util.spec_from_file_location("d8_develop_v2", _PATH)
v2 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(v2)


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def test_b1_sign_is_phi_of_standardized_magnitude():
    assert np.allclose(v2.b1_sign(np.array([0.2, -0.4]), np.array([0.1, 0.2])), [_phi(2), _phi(2)])


def test_b1_magnitude_is_two_sided_normal_mass():
    assert np.allclose(v2.b1_magnitude(np.array([0.1]), 0.2), [2 * _phi(2) - 1])
