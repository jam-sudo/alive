"""Pure-logic tests for the State inference adapter (no torch/state import)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

_PATH = Path(__file__).resolve().parents[3] / "scripts" / "cartographer" / "state_predict.py"
_SPEC = importlib.util.spec_from_file_location("state_predict", _PATH)
sp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sp)


def test_model_scale_matches_cp10k_log1p_on_selected_columns():
    counts = np.array([[1.0, 1.0, 2.0], [0.0, 3.0, 1.0]])
    got = sp.model_scale(counts, [2, 0])
    want = np.log1p(1e4 * counts / counts.sum(1, keepdims=True))[:, [2, 0]]
    assert np.allclose(got, want)


def test_model_scale_rejects_empty_cells():
    with pytest.raises(ValueError, match="zero-depth"):
        sp.model_scale(np.array([[0.0, 0.0]]), [0])


def test_require_input_role_rejects_rows_outside_c_input():
    manifest = {"roles": {"C_input": [5, 7], "C_ref": [9], "C_audit": [11]}}
    sp.require_input_role(np.array([5, 7]), manifest)
    with pytest.raises(ValueError, match="C_input"):
        sp.require_input_role(np.array([5, 9]), manifest)


def test_control_sets_are_disjoint_deterministic_and_sized():
    sets = sp.control_sets(n_cells=300, n_sets=4, set_size=64, seed=1)
    assert sets.shape == (4, 64)
    assert len(np.unique(sets)) == 4 * 64
    assert np.array_equal(sets, sp.control_sets(300, 4, 64, 1))
    with pytest.raises(ValueError, match="disjoint"):
        sp.control_sets(n_cells=100, n_sets=2, set_size=64, seed=1)


def test_predicted_change_marginalizes_every_batch_token_equally():
    ctrl = np.zeros((2, 3, 2))  # 2 sets x 3 cells x 2 genes

    def predict(ctrl_sets, pert_index, batch_index):
        # batch token t shifts gene 0 by t; perturbation shifts gene 1 by index
        out = ctrl_sets.copy()
        out[..., 0] += batch_index
        out[..., 1] += pert_index
        return out

    change, diag = sp.predicted_change(predict, ctrl, pert_index=5, n_batch_tokens=4)
    assert np.allclose(change, [np.mean([0, 1, 2, 3]), 5.0])
    assert np.allclose(diag["per_token_change"][:, 0], [0, 1, 2, 3])
    assert diag["per_set_change"].shape == (2, 2)


def test_predicted_change_is_relative_to_the_same_input_controls():
    rng = np.random.default_rng(0)
    ctrl = rng.normal(size=(3, 4, 5))
    change, _ = sp.predicted_change(lambda c, p, b: c + 0.0, ctrl, pert_index=0, n_batch_tokens=2)
    assert np.allclose(change, 0.0)


def test_resolve_queries_keeps_out_of_vocabulary_as_unsupported():
    idx = {"A": 0, "B": 1, "non-targeting": 2}
    supported, unsupported = sp.resolve_queries(["B", "Z", "A", "non-targeting"], idx)
    assert supported == [("A", 0), ("B", 1)]
    assert unsupported == ["Z"]


def test_anchored_change_cancels_perturbation_independent_offsets():
    ctrl = np.zeros((2, 3, 2))

    def predict(ctrl_sets, pert_index, batch_index):
        out = ctrl_sets + 0.3 + 0.1 * batch_index  # systematic offset shared by all perturbations
        if pert_index == 7:
            out = out.copy()
            out[..., 1] += 2.0
        return out

    change, diag = sp.anchored_change(
        predict, ctrl, pert_index=7, control_index=0, n_batch_tokens=3
    )
    assert np.allclose(change, [0.0, 2.0])
    assert np.allclose(diag["unanchored_change"], [0.3 + 0.1, 2.3 + 0.1])
    assert np.allclose(diag["per_token_change"], [[0.0, 2.0]] * 3)


def test_anchored_change_uses_precomputed_control_base_identically():
    rng = np.random.default_rng(3)
    ctrl = rng.normal(size=(2, 4, 3))

    def predict(c, p, b):
        return c * (1 + 0.1 * p) + 0.05 * b

    base = sp.predicted_change(predict, ctrl, 0, 3)
    direct, _ = sp.anchored_change(predict, ctrl, 2, 0, 3)
    reused, _ = sp.anchored_change(predict, ctrl, 2, 0, 3, base=base)
    assert np.allclose(direct, reused)


def test_se_input_is_full_axis_cp10k_log1p_on_se_columns():
    spec = importlib.util.spec_from_file_location(
        "state_se_predict", _PATH.parent / "state_se_predict.py"
    )
    se = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(se)
    counts = np.array([[2.0, 2.0, 4.0]])
    assert np.allclose(se.se_input(counts, [2]), np.log1p([[5000.0]]))
    with pytest.raises(ValueError):
        se.se_input(np.zeros((1, 3)), [0])
