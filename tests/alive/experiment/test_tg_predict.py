"""Known-answer test for the frozen TG shift decoder."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

_PATH = Path(__file__).resolve().parents[3] / "scripts" / "cartographer" / "tg_predict.py"
_SPEC = importlib.util.spec_from_file_location("tg_predict", _PATH)
tp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tp)


def test_decode_shift_is_row_vector_times_loadings():
    components = np.array([[1.0, 0.0], [0.0, 2.0]])
    assert np.allclose(tp.decode_shift(np.array([[3.0, 0.5]]), components), [[3.0, 1.0]])


def test_decoded_low_rank_prediction_cannot_represent_discarded_components():
    # Audit counterexample: C=[[1,0]], observed change [0,2] projects to the same PCA
    # coordinate as prediction [0,0]; gene-space error must remain 2.
    components = np.array([[1.0, 0.0]])
    observed = np.array([0.0, 2.0])
    shift = observed @ components.T
    decoded = tp.decode_shift(shift[None, :], components)[0]
    assert np.allclose(decoded, [0.0, 0.0])
    assert np.isclose(np.abs(decoded - observed).max(), 2.0)
