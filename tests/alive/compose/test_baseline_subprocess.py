# tests/alive/compose/test_baseline_subprocess.py
"""SYNTHETIC-ONLY: pure numpy + subprocess protocol; no gears/cpa, no seal access."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest

from alive.compose.baseline_subprocess import (
    ExecutionIdentityLock,
    PayloadError,
    SubprocessBaselineBackend,
    _file_sha256_bare,
    _ordered_request_sha256,
    _validate_payload,
    _verify_execution_manifest,
    read_payload,
    read_predictions,
    write_payload,
    write_predictions,
)
from alive.provenance import sha256_json

_GENES = ["A", "B", "C"]
_GENE_ORDER_SHA = sha256_json(_GENES)


def _dummy_lock() -> ExecutionIdentityLock:
    """A structurally valid lock for construction-only (never-predict) sites."""
    return ExecutionIdentityLock(
        prediction_representation="cell_raw_counts",
        adapter_version="1",
        adapter_sha256="a" * 64,
        config_sha256="e" * 64,
        resource_sha256="f" * 64,
        environment_lock_sha256="0" * 64,
    )


def _stub_lock() -> ExecutionIdentityLock:
    """The lock whose identities match ``stub_worker.py``'s emitted manifest."""
    return ExecutionIdentityLock(
        prediction_representation="cell_raw_counts",
        adapter_version="stub-1",
        adapter_sha256=hashlib.sha256(b"stub-1").hexdigest(),
        config_sha256=hashlib.sha256(b"stub-config").hexdigest(),
        resource_sha256=hashlib.sha256(b"stub-resource").hexdigest(),
        environment_lock_sha256=hashlib.sha256(b"stub-environment").hexdigest(),
    )


def _manifest() -> dict:
    return {
        "prediction_representation": "cell_raw_counts",
        "adapter_version": "1",
        "adapter_sha256": "a" * 64,
        "expected_gene_order_sha256": _GENE_ORDER_SHA,
        "observed_gene_order_sha256": _GENE_ORDER_SHA,
        "checkpoint_sha256": "c" * 64,
        "worker_sha256": "b" * 64,
        "config_sha256": "e" * 64,
        "resource_sha256": "f" * 64,
        "environment_lock_sha256": "0" * 64,
        "fit_artifact_content_sha256": "1" * 64,
        "combined_request_sha256": "d" * 64,
        "predictions_sha256": "",  # filled by write_predictions
    }


def _fit_role_block() -> dict:
    return {
        "format": "anndata_h5ad",
        "artifact_schema_version": 1,
        "path": "/approved/artifacts/fit_role.h5ad",
        "sha256": "sha256:" + "0" * 64,
        "content_manifest_sha256": "1" * 64,
        "raw_data_sha256": "raw123",
        "pair_manifest_sha256": "pm123",
        "eligibility_hash": "elig123",
        "row_identity_sha256": "2" * 64,
        "role_obs_key": "role",
        "perturbation_obs_key": "perturbation",
        "allowed_obs_roles": ["control", "singles", "combo_calibration"],
        "gene_order_sha256": _GENE_ORDER_SHA,
        "n_cells": 30,
        "n_genes": 3,
        "role_counts": {"control": 20, "singles": 6, "combo_calibration": 4},
        "counts_location": "X",
    }


def _response_projection_block(pca_components, control_mean) -> dict:
    return {
        "response_artifact_sha256": "3" * 64,
        "raw_data_sha256": "raw123",  # == fit_role_artifact.raw_data_sha256
        "gene_order_sha256": _GENE_ORDER_SHA,  # == fit_role_artifact.gene_order_sha256
        "hvg_gene_ids": ["A", "B"],
        "transform": ["normalize_total_median", "log1p"],
        "median_library": 1000.0,
        "pca_mean": [0.0, 0.0],
        "pca_components": pca_components,  # == payload["pca_components"]
        "control_mean": control_mean,  # == payload["control_mean"]
        "delta_convention": "z_minus_control_mean",
    }


def _payload() -> dict:
    pca_components = [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]
    control_mean = [0.0, 0.0, 0.0]
    return {
        "schema_version": 2,
        "response_dim": 3,
        "seed": 11,
        "allowed_roles": ["combo_calibration", "singles"],
        "pair_ids": [["A", "B"], ["A", "C"]],
        "single_gene_ids": ["A", "B", "C"],
        "singles_response": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]],
        "control_mean": control_mean,
        "calibration_pair_ids": [["B", "C"]],
        "calibration_delta": [[0.5, 0.5, 0.5]],
        "pca_components": pca_components,
        "oof_folds": [0],
        "fit_role_artifact": _fit_role_block(),
        "response_projection": _response_projection_block(pca_components, control_mean),
    }


def test_payload_round_trip_preserves_values_and_checksum(tmp_path) -> None:
    p = _payload()
    c1 = write_payload(str(tmp_path), p)
    back = read_payload(str(tmp_path))
    assert back["pair_ids"] == p["pair_ids"]
    assert back["response_dim"] == 3
    np.testing.assert_allclose(back["singles_response"], p["singles_response"])
    # checksum is stable across a re-serialization of the same content
    c2 = write_payload(str(tmp_path), read_payload(str(tmp_path)))
    assert c1 == c2 and len(c1) == 64


def test_missing_key_rejected(tmp_path) -> None:
    p = _payload()
    del p["control_mean"]
    with pytest.raises(PayloadError):
        write_payload(str(tmp_path), p)


def test_unknown_key_rejected(tmp_path) -> None:
    p = _payload()
    p["surprise"] = 1
    with pytest.raises(PayloadError):
        write_payload(str(tmp_path), p)


def test_duplicate_prediction_request_pair_rejected(tmp_path) -> None:
    p = _payload()
    p["pair_ids"] = [["A", "B"], ["A", "B"]]
    with pytest.raises(PayloadError, match="duplicate"):
        write_payload(str(tmp_path), p)


def test_misaligned_singles_response_rejected(tmp_path) -> None:
    p = _payload()
    p["singles_response"] = p["singles_response"][:-1]
    with pytest.raises(PayloadError, match="aligned"):
        write_payload(str(tmp_path), p)


def test_prediction_envelope_round_trip(tmp_path) -> None:
    preds = {("A", "B"): np.array([1.0, 2.0, 3.0]), ("A", "C"): np.array([4.0, 5.0, 6.0])}
    path = str(tmp_path / "preds")
    manifest = _manifest()
    c = write_predictions(path, preds, execution_manifest=manifest)
    back_preds, back_manifest = read_predictions(path)
    assert set(back_preds) == set(preds)
    np.testing.assert_allclose(back_preds[("A", "B")], preds[("A", "B")])
    assert back_manifest["prediction_representation"] == "cell_raw_counts"
    # predictions_sha256 is bound by write_predictions, not the caller's blank.
    assert len(back_manifest["predictions_sha256"]) == 64
    assert len(c) == 64


def test_prediction_envelope_bad_representation_rejected(tmp_path) -> None:
    preds = {("A", "B"): np.array([1.0, 2.0, 3.0])}
    manifest = _manifest()
    manifest["prediction_representation"] = "made_up"
    with pytest.raises(PayloadError, match="representation"):
        write_predictions(str(tmp_path / "p"), preds, execution_manifest=manifest)


def test_prediction_envelope_tampered_predictions_rejected(tmp_path) -> None:
    # A file whose predictions were edited after the manifest was written must be
    # rejected by read_predictions' predictions_sha256 binding.
    import json

    preds = {("A", "B"): np.array([1.0, 2.0, 3.0])}
    path = str(tmp_path / "preds")
    write_predictions(path, preds, execution_manifest=_manifest())
    with open(path + ".json") as fh:
        obj = json.load(fh)
    obj["predictions"] = [[["A", "B"], [9.0, 9.0, 9.0]]]  # tamper, leave sha as-is
    with open(path + ".json", "w") as fh:
        json.dump(obj, fh)
    with pytest.raises(PayloadError, match="predictions_sha256"):
        read_predictions(path)


@pytest.mark.parametrize(
    "field",
    [
        "combined_request_sha256",
        "fit_artifact_content_sha256",
        "worker_sha256",
        "checkpoint_sha256",
        "config_sha256",
        "resource_sha256",
        "environment_lock_sha256",
        "adapter_sha256",
    ],
)
def test_controller_rejects_self_consistent_but_false_manifest_identity(tmp_path, field) -> None:
    worker = tmp_path / "worker.py"
    checkpoint = tmp_path / "checkpoint.bin"
    worker.write_bytes(b"worker")
    checkpoint.write_bytes(b"checkpoint")
    requested = [("A", "B"), ("A", "C")]
    lock = ExecutionIdentityLock(
        prediction_representation="cell_raw_counts",
        adapter_version="1",
        adapter_sha256="a" * 64,
        config_sha256="e" * 64,
        resource_sha256="f" * 64,
        environment_lock_sha256="0" * 64,
    )
    manifest = _manifest()
    manifest.update(
        worker_sha256=_file_sha256_bare(str(worker)),
        checkpoint_sha256=_file_sha256_bare(str(checkpoint)),
        combined_request_sha256=_ordered_request_sha256(requested),
        # read_predictions normally fills predictions_sha256; this direct unit
        # test supplies a structurally valid value so the selected identity field
        # is the first and only mismatch.
        predictions_sha256="8" * 64,
    )
    manifest[field] = "9" * 64
    with pytest.raises(PayloadError, match=field):
        _verify_execution_manifest(
            manifest,
            payload=_payload(),
            requested_pair_ids=requested,
            worker_script=str(worker),
            checkpoint_path=str(checkpoint),
            identity_lock=lock,
        )


def test_is_available_true_for_importable_module() -> None:
    be = SubprocessBaselineBackend(
        name="stub",
        env_python=sys.executable,
        worker_script="x",
        import_name="json",
        approved_artifacts_root="/unused",
        expected_response_artifact_sha256="0" * 64,
        execution_identity_lock=_dummy_lock(),
    )
    assert be.is_available is True


def test_is_available_false_for_missing_module() -> None:
    be = SubprocessBaselineBackend(
        name="gears",
        env_python=sys.executable,
        worker_script="x",
        import_name="definitely_not_a_real_module_xyz",
        approved_artifacts_root="/unused",
        expected_response_artifact_sha256="0" * 64,
        execution_identity_lock=_dummy_lock(),
    )
    assert be.is_available is False


def test_is_available_false_for_bad_python() -> None:
    be = SubprocessBaselineBackend(
        name="cpa",
        env_python="/no/such/python",
        worker_script="x",
        import_name="cpa",
        approved_artifacts_root="/unused",
        expected_response_artifact_sha256="0" * 64,
        execution_identity_lock=_dummy_lock(),
    )
    assert be.is_available is False


_STUB = str(Path(__file__).resolve().parents[3] / "scripts" / "baselines" / "stub_worker.py")


def _backend(tmp_path) -> SubprocessBaselineBackend:
    # expected_response_artifact_sha256 matches _payload()'s response_projection
    # ("3" * 64); execution_identity_lock matches the stub worker's manifest.
    return SubprocessBaselineBackend(
        name="stub",
        env_python=sys.executable,
        worker_script=_STUB,
        import_name="json",
        approved_artifacts_root=str(tmp_path),
        expected_response_artifact_sha256="3" * 64,
        execution_identity_lock=_stub_lock(),
    )


def test_payload_with_sealed_token_is_refused(tmp_path) -> None:
    be = _backend(tmp_path)
    bad = _payload()
    bad["single_gene_ids"] = ["A", "sealed_double_unseen", "C"]
    with pytest.raises(ValueError, match="sealed"):
        be.configure_payload(bad)


def test_configure_payload_detaches_nested_state(tmp_path) -> None:
    be = _backend(tmp_path)
    payload = _payload()
    be.configure_payload(payload)
    payload["response_projection"]["response_artifact_sha256"] = "4" * 64
    payload["fit_role_artifact"]["path"] = "/tampered/after/configure.h5ad"
    assert be._payload["response_projection"]["response_artifact_sha256"] == "3" * 64
    assert be._payload["fit_role_artifact"]["path"] == "/approved/artifacts/fit_role.h5ad"


def test_predict_rejects_relative_approved_root() -> None:
    be = SubprocessBaselineBackend(
        name="stub",
        env_python=sys.executable,
        worker_script=_STUB,
        import_name="json",
        approved_artifacts_root=".",
        expected_response_artifact_sha256="3" * 64,
        execution_identity_lock=_stub_lock(),
    )
    be.configure_payload(_payload())
    with pytest.raises(PayloadError, match="absolute path"):
        be.predict(None, [("A", "B")], 3)


def test_v1_schema_version_rejected(tmp_path):
    p = _payload()
    p["schema_version"] = 1
    with pytest.raises(PayloadError):
        write_payload(str(tmp_path), p)


def test_projection_control_mean_divergence_rejected(tmp_path):
    p = _payload()
    p["response_projection"]["control_mean"] = [9.0, 9.0, 9.0]  # != payload control_mean
    with pytest.raises(PayloadError, match="control_mean"):
        write_payload(str(tmp_path), p)


def test_projection_raw_data_divergence_rejected(tmp_path):
    p = _payload()
    p["response_projection"]["raw_data_sha256"] = "different"
    with pytest.raises(PayloadError, match="raw_data"):
        write_payload(str(tmp_path), p)


def test_projection_bad_pca_mean_length_rejected(tmp_path):
    p = _payload()
    p["response_projection"]["pca_mean"] = [0.0, 0.0, 0.0]  # len 3 != 2 hvg
    with pytest.raises(PayloadError, match="pca_mean"):
        write_payload(str(tmp_path), p)


def test_projection_response_artifact_divergence_rejected():
    p = _payload()
    with pytest.raises(PayloadError, match="verified response artifact"):
        _validate_payload(p, expected_response_artifact_sha256="f" * 64)


def test_malformed_digest_and_role_counts_rejected(tmp_path):
    p = _payload()
    p["fit_role_artifact"]["content_manifest_sha256"] = "not-a-sha"
    with pytest.raises(PayloadError):
        write_payload(str(tmp_path), p)
    p = _payload()
    p["fit_role_artifact"]["role_counts"]["control"] += 1
    with pytest.raises(PayloadError, match="n_cells"):
        write_payload(str(tmp_path), p)


def test_fit_role_disallowed_obs_role_rejected(tmp_path):
    p = _payload()
    p["fit_role_artifact"]["allowed_obs_roles"] = ["control", "sealed_double_unseen"]
    with pytest.raises(ValueError):  # sealed-token scan or role-subset
        write_payload(str(tmp_path), p)


def test_pair_ids_overlapping_calibration_rejected(tmp_path):
    # In A2 the sealed request pair_ids must be disjoint from the calibration
    # cells present in the fit artifact.
    p = _payload()
    p["pair_ids"] = [["A", "B"], ["B", "C"]]  # ("B","C") is a calibration pair
    with pytest.raises(PayloadError, match="disjoint"):
        write_payload(str(tmp_path), p)
