# tests/alive/compose/test_baseline_subprocess.py
"""SYNTHETIC-ONLY: pure numpy + subprocess protocol; no gears/cpa, no seal access."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from alive.compose.baseline_subprocess import (
    PayloadError,
    SubprocessBaselineBackend,
    read_payload,
    read_predictions,
    write_payload,
    write_predictions,
)
from alive.compose.baselines_combo import BaselineAdapter, BaselineTrainingContext


def _payload() -> dict:
    return {
        "schema_version": 1,
        "response_dim": 3,
        "seed": 11,
        "allowed_roles": ["combo_calibration", "singles"],
        "pair_ids": [["A", "B"], ["A", "C"]],
        "single_gene_ids": ["A", "B", "C"],
        "singles_response": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]],
        "control_mean": [0.0, 0.0, 0.0],
        "calibration_pair_ids": [["B", "C"]],
        "calibration_delta": [[0.5, 0.5, 0.5]],
        "pca_components": [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]],
        "oof_folds": [0],
    }


def test_payload_round_trip_preserves_values_and_checksum(tmp_path):
    p = _payload()
    c1 = write_payload(str(tmp_path), p)
    back = read_payload(str(tmp_path))
    assert back["pair_ids"] == p["pair_ids"]
    assert back["response_dim"] == 3
    np.testing.assert_allclose(back["singles_response"], p["singles_response"])
    # checksum is stable across a re-serialization of the same content
    c2 = write_payload(str(tmp_path), read_payload(str(tmp_path)))
    assert c1 == c2 and len(c1) == 64


def test_missing_key_rejected(tmp_path):
    p = _payload()
    del p["control_mean"]
    with pytest.raises(PayloadError):
        write_payload(str(tmp_path), p)


def test_unknown_key_rejected(tmp_path):
    p = _payload()
    p["surprise"] = 1
    with pytest.raises(PayloadError):
        write_payload(str(tmp_path), p)


def test_prediction_round_trip(tmp_path):
    preds = {("A", "B"): np.array([1.0, 2.0, 3.0]), ("A", "C"): np.array([4.0, 5.0, 6.0])}
    path = str(tmp_path / "preds")
    c = write_predictions(path, preds)
    back = read_predictions(path)
    assert set(back) == set(preds)
    np.testing.assert_allclose(back[("A", "B")], preds[("A", "B")])
    assert len(c) == 64


def test_is_available_true_for_importable_module():
    be = SubprocessBaselineBackend(
        name="stub", env_python=sys.executable, worker_script="x", import_name="json"
    )
    assert be.is_available is True


def test_is_available_false_for_missing_module():
    be = SubprocessBaselineBackend(
        name="gears",
        env_python=sys.executable,
        worker_script="x",
        import_name="definitely_not_a_real_module_xyz",
    )
    assert be.is_available is False


def test_is_available_false_for_bad_python():
    be = SubprocessBaselineBackend(
        name="cpa", env_python="/no/such/python", worker_script="x", import_name="cpa"
    )
    assert be.is_available is False


_STUB = str(Path(__file__).resolve().parents[3] / "scripts" / "baselines" / "stub_worker.py")


def _context() -> BaselineTrainingContext:
    return BaselineTrainingContext(
        allowed_roles=frozenset({"singles", "combo_calibration"}),
        pair_manifest_checksum="deadbeef",
        response_space_checksum="cafe",
        training_pair_ids=(("B", "C"),),
        single_gene_ids=("A", "B", "C"),
    )


def _backend() -> SubprocessBaselineBackend:
    return SubprocessBaselineBackend(
        name="stub", env_python=sys.executable, worker_script=_STUB, import_name="json"
    )


def test_predict_end_to_end_through_adapter(tmp_path):
    be = _backend()
    be._payload = _payload()  # test injects the fit-role payload (see Step 3 note)
    adapter = BaselineAdapter(name="stub", backend=be)
    out = adapter.predict(_context(), [("A", "B"), ("A", "C")], 3)
    assert set(out) == {("A", "B"), ("A", "C")}
    # additive stub: delta(A,B) = singles[A] + singles[B]
    np.testing.assert_allclose(out[("A", "B")], np.array([0.5, 0.7, 0.9]))


def test_predict_is_deterministic(tmp_path):
    be1, be2 = _backend(), _backend()
    be1._payload = _payload()
    be2._payload = _payload()
    a = BaselineAdapter(name="stub", backend=be1).predict(_context(), [("A", "B")], 3)
    b = BaselineAdapter(name="stub", backend=be2).predict(_context(), [("A", "B")], 3)
    np.testing.assert_allclose(a[("A", "B")], b[("A", "B")])


def test_payload_with_sealed_token_is_refused():
    be = _backend()
    bad = _payload()
    bad["single_gene_ids"] = ["A", "sealed_double_unseen", "C"]
    be._payload = bad
    with pytest.raises(ValueError, match="sealed"):
        be.predict(_context(), [("A", "B")], 3)
