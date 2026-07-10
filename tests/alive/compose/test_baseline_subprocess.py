# tests/alive/compose/test_baseline_subprocess.py
"""SYNTHETIC-ONLY: pure numpy + subprocess protocol; no gears/cpa, no seal access."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from alive.compose import baseline_subprocess
from alive.compose.baseline_subprocess import (
    ExecutionIdentityLock,
    PayloadError,
    SubprocessBaselineBackend,
    _build_worker_environment,
    _file_sha256_bare,
    _ordered_request_sha256,
    _persist_content_addressed_checkpoint,
    _snapshot_verified_worker_script,
    _validate_payload,
    _verify_execution_manifest,
    read_payload,
    read_predictions,
    write_payload,
    write_predictions,
)
from alive.compose.worker_bundle import build_worker_bundle
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
        "payload_sha256": "7" * 64,
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


def test_worker_payload_read_requires_controller_bound_exact_bytes(tmp_path, monkeypatch) -> None:
    import json

    original = _payload()
    expected = write_payload(str(tmp_path), original)
    monkeypatch.setenv("ALIVE_WORKER_PAYLOAD_SHA256", expected)
    assert read_payload(str(tmp_path), require_expected_sha256=True) == original

    replaced = _payload()
    replaced["response_projection"]["pca_mean"] = [9.0, 9.0]
    text = json.dumps(replaced, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    (tmp_path / "payload.json").write_text(text, encoding="utf-8")
    with pytest.raises(PayloadError, match="controller-bound"):
        read_payload(str(tmp_path), require_expected_sha256=True)


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


def test_prediction_envelope_symlink_is_rejected(tmp_path) -> None:
    real_stem = str(tmp_path / "real-preds")
    write_predictions(
        real_stem,
        {("A", "B"): np.array([1.0, 2.0, 3.0])},
        execution_manifest=_manifest(),
    )
    linked_stem = str(tmp_path / "linked-preds")
    Path(linked_stem + ".json").symlink_to(Path(real_stem + ".json"))
    with pytest.raises(PayloadError, match="regular non-symlink"):
        read_predictions(linked_stem)


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
        "payload_sha256",
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
            expected_payload_sha256="7" * 64,
        )


def test_controller_rejects_replaced_execution_snapshot_against_trusted_sha(tmp_path) -> None:
    worker = tmp_path / "worker.snapshot.py"
    checkpoint = tmp_path / "checkpoint.bin"
    worker.write_bytes(b"trusted-worker")
    trusted_worker_sha = _file_sha256_bare(str(worker))
    checkpoint.write_bytes(b"checkpoint")
    requested = [("A", "B")]
    manifest = _manifest()
    manifest.update(
        worker_sha256=trusted_worker_sha,
        checkpoint_sha256=_file_sha256_bare(str(checkpoint)),
        combined_request_sha256=_ordered_request_sha256(requested),
        predictions_sha256="8" * 64,
    )
    worker.write_bytes(b"replacement-after-interpreter-load")
    with pytest.raises(PayloadError, match="snapshot differs from trusted"):
        _verify_execution_manifest(
            manifest,
            payload=_payload(),
            requested_pair_ids=requested,
            worker_script=str(worker),
            checkpoint_path=str(checkpoint),
            identity_lock=_dummy_lock(),
            expected_worker_sha256=trusted_worker_sha,
            expected_payload_sha256="7" * 64,
        )


def test_is_available_true_for_importable_module() -> None:
    be = SubprocessBaselineBackend(
        name="stub",
        env_python=sys.executable,
        worker_script=str(Path(__file__).resolve()),
        import_name="json",
        approved_artifacts_root="/unused",
        expected_response_artifact_sha256="0" * 64,
        execution_identity_lock=_dummy_lock(),
        allow_local_approved_root_checkpoint_store=True,
    )
    assert be.is_available is True


def test_is_available_uses_minimal_noninjectable_environment(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/attacker/shadow-modules")
    monkeypatch.setenv("PYTHONHOME", "/attacker/python-home")
    monkeypatch.setenv("PYTHONSTARTUP", "/attacker/startup.py")
    monkeypatch.setenv("PYTHONINSPECT", "1")
    monkeypatch.setenv("LD_PRELOAD", "/attacker/inject.so")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/attacker/libs")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "/attacker/inject.dylib")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/attacker/dylibs")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2")
    captured: dict[str, object] = {}

    def _run(args, *, capture_output, timeout, env, cwd):
        captured["env"] = dict(env)
        captured["cwd"] = cwd
        return baseline_subprocess.subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(baseline_subprocess.subprocess, "run", _run)
    be = SubprocessBaselineBackend(
        name="stub",
        env_python=sys.executable,
        worker_script=str(Path(__file__).resolve()),
        import_name="json",
        seed=23,
        approved_artifacts_root="/unused",
        expected_response_artifact_sha256="0" * 64,
        execution_identity_lock=_dummy_lock(),
        allow_local_approved_root_checkpoint_store=True,
    )
    assert be.is_available is True
    env = captured["env"]
    assert isinstance(env, dict)
    assert "CUDA_VISIBLE_DEVICES" not in env
    assert env["PYTHONHASHSEED"] == "23"
    assert env["CUBLAS_WORKSPACE_CONFIG"] == ":4096:8"
    assert env["LANG"] == "C.UTF-8"
    assert env["LC_ALL"] == "C.UTF-8"
    assert env["TZ"] == "UTC"
    assert env["MPLBACKEND"] == "Agg"
    assert env["ALIVE_WORKER_EXECUTABLE_PATH"].endswith("worker.snapshot.py")
    assert len(env["ALIVE_WORKER_EXECUTABLE_SHA256"]) == 64
    assert captured["cwd"] == str(Path(captured["cwd"]).resolve())
    assert {
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONINSPECT",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
    }.isdisjoint(env)


def test_is_available_false_for_missing_module() -> None:
    be = SubprocessBaselineBackend(
        name="gears",
        env_python=sys.executable,
        worker_script=str(Path(__file__).resolve()),
        import_name="definitely_not_a_real_module_xyz",
        approved_artifacts_root="/unused",
        expected_response_artifact_sha256="0" * 64,
        execution_identity_lock=_dummy_lock(),
        allow_local_approved_root_checkpoint_store=True,
    )
    assert be.is_available is False


def test_is_available_false_for_bad_python() -> None:
    be = SubprocessBaselineBackend(
        name="cpa",
        env_python="/no/such/python",
        worker_script=str(Path(__file__).resolve()),
        import_name="cpa",
        approved_artifacts_root="/unused",
        expected_response_artifact_sha256="0" * 64,
        execution_identity_lock=_dummy_lock(),
        allow_local_approved_root_checkpoint_store=True,
    )
    assert be.is_available is False


def test_bundle_availability_imports_helpers_and_backend_from_verified_snapshot(tmp_path) -> None:
    root = Path(__file__).resolve().parents[3]
    bundle = build_worker_bundle(
        source_root=root,
        entrypoint=root / "scripts/baselines/cpa_worker.py",
        output_path=tmp_path / "cpa.pyz",
        method="cpa",
    )
    be = SubprocessBaselineBackend(
        name="cpa",
        env_python=sys.executable,
        worker_script=bundle.path,
        import_name="numpy",
        approved_artifacts_root=str(tmp_path),
        expected_response_artifact_sha256="0" * 64,
        execution_identity_lock=_dummy_lock(),
        expected_worker_sha256=bundle.sha256,
        allow_local_approved_root_checkpoint_store=True,
    )
    assert be.is_available is True


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
        allow_local_approved_root_checkpoint_store=True,
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


def test_verified_checkpoint_is_persisted_content_addressed(tmp_path) -> None:
    source = tmp_path / "worker-output.pt"
    source.write_bytes(b"real trained model state")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    checkpoint = Path(
        _persist_content_addressed_checkpoint(
            str(source), approved_root=str(tmp_path), checkpoint_sha256=digest
        )
    )
    assert checkpoint == tmp_path / ".worker_checkpoints" / f"{digest}.pt"
    assert checkpoint.is_file()
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == digest
    assert checkpoint.stat().st_mode & 0o222 == 0
    assert checkpoint.stat().st_nlink == 1

    # Re-installing identical content is idempotent and preserves the one real node.
    again = _persist_content_addressed_checkpoint(
        str(source), approved_root=str(tmp_path), checkpoint_sha256=digest
    )
    assert again == str(checkpoint)
    assert checkpoint.stat().st_nlink == 1


def test_worker_executes_from_verified_read_only_snapshot(tmp_path) -> None:
    source = tmp_path / "worker.py"
    original = b"print('trusted worker')\n"
    source.write_bytes(original)
    digest = hashlib.sha256(original).hexdigest()
    snapshot = tmp_path / "worker.snapshot.py"
    assert _snapshot_verified_worker_script(
        str(source),
        str(snapshot),
        expected_sha256=digest,
        expected_method="stub",
        allow_fixture_stub=True,
        allow_direct_py=True,
    ) == str(snapshot)
    source.write_bytes(b"print('replacement')\n")
    assert snapshot.read_bytes() == original
    assert snapshot.stat().st_mode & 0o222 == 0
    with pytest.raises(PayloadError, match="trusted worker identity"):
        _snapshot_verified_worker_script(
            str(source),
            str(tmp_path / "second.snapshot.py"),
            expected_sha256=digest,
            expected_method="stub",
            allow_fixture_stub=True,
            allow_direct_py=True,
        )


def test_worker_bundle_snapshot_is_validated_and_is_the_only_pythonpath(tmp_path) -> None:
    root = Path(__file__).resolve().parents[3]
    bundle = build_worker_bundle(
        source_root=root,
        entrypoint=root / "scripts/baselines/stub_worker.py",
        output_path=tmp_path / "stub.pyz",
        method="stub",
    )
    snapshot = tmp_path / "worker.snapshot.pyz"
    assert _snapshot_verified_worker_script(
        bundle.path,
        str(snapshot),
        expected_sha256=bundle.sha256,
        expected_method="cpa",
        allow_fixture_stub=True,
        allow_direct_py=False,
    ) == str(snapshot)
    env = _build_worker_environment(
        {"PYTHONPATH": "/attacker"},
        worker_identity_paths=None,
        identity_lock=_dummy_lock(),
        approved_root=str(tmp_path),
        seed=11,
        worker_executable_path=str(snapshot),
        worker_executable_sha256=bundle.sha256,
    )
    assert env["PYTHONPATH"] == str(snapshot)
    assert env["ALIVE_WORKER_EXECUTABLE_PATH"] == str(snapshot)
    assert env["ALIVE_WORKER_EXECUTABLE_SHA256"] == bundle.sha256

    with pytest.raises(PayloadError, match="method differs"):
        _snapshot_verified_worker_script(
            bundle.path,
            str(tmp_path / "rejected.pyz"),
            expected_sha256=bundle.sha256,
            expected_method="cpa",
            allow_fixture_stub=False,
            allow_direct_py=False,
        )


def test_checkpoint_source_symlink_is_rejected(tmp_path) -> None:
    real = tmp_path / "real.pt"
    real.write_bytes(b"checkpoint")
    link = tmp_path / "worker-output.pt"
    link.symlink_to(real)
    digest = hashlib.sha256(real.read_bytes()).hexdigest()

    with pytest.raises(PayloadError, match="regular non-symlink"):
        _persist_content_addressed_checkpoint(
            str(link), approved_root=str(tmp_path), checkpoint_sha256=digest
        )


def test_checkpoint_store_symlink_cannot_escape_approved_root(tmp_path) -> None:
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    (approved / ".worker_checkpoints").symlink_to(outside, target_is_directory=True)
    source = tmp_path / "source.pt"
    source.write_bytes(b"checkpoint")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    with pytest.raises(PayloadError, match="real directory"):
        _persist_content_addressed_checkpoint(
            str(source), approved_root=str(approved), checkpoint_sha256=digest
        )
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("destination_kind", ["symlink", "directory"])
def test_existing_nonregular_content_address_is_rejected(tmp_path, destination_kind) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(b"checkpoint")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = tmp_path / ".worker_checkpoints"
    store.mkdir()
    destination = store / f"{digest}.pt"
    if destination_kind == "symlink":
        target = tmp_path / "matching-target.pt"
        target.write_bytes(source.read_bytes())
        target.chmod(0o400)
        destination.symlink_to(target)
    else:
        destination.mkdir()

    with pytest.raises(PayloadError, match="regular non-symlink"):
        _persist_content_addressed_checkpoint(
            str(source), approved_root=str(tmp_path), checkpoint_sha256=digest
        )


def test_failed_atomic_publish_removes_staging_node(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(b"checkpoint")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    def _fail_link(*args, **kwargs):
        raise OSError("injected link failure")

    monkeypatch.setattr(baseline_subprocess.os, "link", _fail_link)
    with pytest.raises(PayloadError, match="atomically publish"):
        _persist_content_addressed_checkpoint(
            str(source), approved_root=str(tmp_path), checkpoint_sha256=digest
        )
    store = tmp_path / ".worker_checkpoints"
    assert list(store.iterdir()) == []


def test_checkpoint_publish_fsyncs_file_and_directories(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.pt"
    source.write_bytes(b"checkpoint")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    real_fsync = os.fsync
    synced_modes: list[int] = []

    def _spy_fsync(fd: int) -> None:
        synced_modes.append(os.fstat(fd).st_mode)
        real_fsync(fd)

    monkeypatch.setattr(baseline_subprocess.os, "fsync", _spy_fsync)
    _persist_content_addressed_checkpoint(
        str(source), approved_root=str(tmp_path), checkpoint_sha256=digest
    )
    assert any(mode & 0o170000 == 0o100000 for mode in synced_modes)
    assert any(mode & 0o170000 == 0o040000 for mode in synced_modes)


def _identity_files(root: Path) -> tuple[dict[str, str], ExecutionIdentityLock]:
    contents = {
        "worker_config": b"config",
        "resource_manifest": b"resource",
        "requirements_lock": b"requirements",
        "adapter_artifact": b"adapter",
    }
    paths: dict[str, str] = {}
    for field, data in contents.items():
        path = root / field
        path.write_bytes(data)
        paths[field] = str(path)
    lock = ExecutionIdentityLock(
        prediction_representation="cell_raw_counts",
        adapter_version="adapter-v1",
        adapter_sha256=hashlib.sha256(contents["adapter_artifact"]).hexdigest(),
        config_sha256=hashlib.sha256(contents["worker_config"]).hexdigest(),
        resource_sha256=hashlib.sha256(contents["resource_manifest"]).hexdigest(),
        environment_lock_sha256=hashlib.sha256(contents["requirements_lock"]).hexdigest(),
    )
    return paths, lock


def test_worker_environment_uses_only_fixed_controller_values_without_paths(tmp_path) -> None:
    ambient = {
        "KEEP_ME": "yes",
        "CUDA_VISIBLE_DEVICES": "3",
        "TMPDIR": "/attacker/tmp",
        "ALIVE_WORKER_CONFIG_PATH": "/attacker/config",
        "ALIVE_WORKER_ADAPTER_VERSION": "attacker",
        "ALIVE_WORKER_CONFIG_SHA256": "0" * 64,
        "PYTHONPATH": "/attacker/shadow-modules",
        "PYTHONHOME": "/attacker/python-home",
        "PYTHONSTARTUP": "/attacker/startup.py",
        "PYTHONINSPECT": "1",
        "LD_PRELOAD": "/attacker/inject.so",
        "LD_LIBRARY_PATH": "/attacker/libs",
        "DYLD_INSERT_LIBRARIES": "/attacker/inject.dylib",
        "DYLD_LIBRARY_PATH": "/attacker/dylibs",
        "CUBLAS_WORKSPACE_CONFIG": "attacker",
    }
    env = _build_worker_environment(
        ambient,
        worker_identity_paths=None,
        identity_lock=_dummy_lock(),
        approved_root=str(tmp_path),
        seed=37,
    )
    assert env == {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "MPLBACKEND": "Agg",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        "PYTHONHASHSEED": "37",
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
    }


def test_worker_environment_binds_verified_paths_and_lock(tmp_path) -> None:
    paths, lock = _identity_files(tmp_path)
    env = _build_worker_environment(
        {"KEEP_ME": "dropped", "CUDA_VISIBLE_DEVICES": "1"},
        worker_identity_paths=paths,
        identity_lock=lock,
        approved_root=str(tmp_path),
        seed=11,
    )
    assert "KEEP_ME" not in env
    assert "CUDA_VISIBLE_DEVICES" not in env
    assert env["PYTHONHASHSEED"] == "11"
    assert env["ALIVE_WORKER_CONFIG_PATH"] == paths["worker_config"]
    assert env["ALIVE_WORKER_ADAPTER_VERSION"] == "adapter-v1"
    assert env["ALIVE_WORKER_ADAPTER_SHA256"] == lock.adapter_sha256
    assert env["ALIVE_WORKER_CONFIG_SHA256"] == lock.config_sha256
    assert env["ALIVE_WORKER_RESOURCE_SHA256"] == lock.resource_sha256
    assert env["ALIVE_WORKER_ENVIRONMENT_LOCK_SHA256"] == lock.environment_lock_sha256


def test_worker_environment_rejects_symlinked_or_outside_identity_path(tmp_path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    paths, lock = _identity_files(approved)
    real_config = Path(paths["worker_config"])
    symlink = approved / "worker_config_link"
    symlink.symlink_to(real_config)
    paths["worker_config"] = str(symlink)
    with pytest.raises(PayloadError, match="canonical path"):
        _build_worker_environment(
            {},
            worker_identity_paths=paths,
            identity_lock=lock,
            approved_root=str(approved),
            seed=11,
        )

    paths["worker_config"] = str(real_config)
    outside = tmp_path / "outside-config"
    outside.write_bytes(real_config.read_bytes())
    paths["worker_config"] = str(outside)
    with pytest.raises(PayloadError, match="under approved root"):
        _build_worker_environment(
            {},
            worker_identity_paths=paths,
            identity_lock=lock,
            approved_root=str(approved),
            seed=11,
        )


def test_worker_environment_rehashes_identity_immediately_before_launch(tmp_path) -> None:
    paths, lock = _identity_files(tmp_path)
    Path(paths["worker_config"]).write_bytes(b"changed-after-lock-assembly")
    with pytest.raises(PayloadError, match="differs from controller lock"):
        _build_worker_environment(
            {},
            worker_identity_paths=paths,
            identity_lock=lock,
            approved_root=str(tmp_path),
            seed=11,
        )


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


def test_scientific_backend_refuses_to_mutate_approved_input_root(tmp_path) -> None:
    be = _backend(tmp_path)
    be.allow_local_approved_root_checkpoint_store = False
    be.configure_payload(_payload())
    with pytest.raises(PayloadError, match="immutable approved-artifacts input root"):
        be.predict(None, [("A", "B")], 3)
    assert not (tmp_path / ".worker_checkpoints").exists()


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


# --------------------------------------------------------------------------- #
# D2 fresh-backend spawn contract
# --------------------------------------------------------------------------- #


def test_spawn_backends_do_not_share_payload_or_manifest_state(tmp_path):
    # D2 runs each (method, seed, fold) job on a fresh backend so mutable payload
    # / execution-manifest state cannot bleed across folds. Configuring fold A
    # must leave a sibling spawned fold B (and the parent) untouched.
    base = _backend(tmp_path)
    fold_a = base.spawn(seed=11)
    fold_b = base.spawn(seed=23)

    fold_a.configure_payload(_payload())
    # simulate a post-predict manifest on A to prove the field is not aliased.
    fold_a._last_execution_manifest = {"marker": "fold-a"}

    assert fold_a._payload is not None
    assert fold_b._payload is None
    assert fold_b._last_execution_manifest is None
    # the parent is never mutated by spawn or by a child's configuration.
    assert base._payload is None
    assert base._last_execution_manifest is None
    # a fresh spawn copies immutable execution identity but sets the new seed.
    assert fold_a.seed == 11
    assert fold_b.seed == 23
    assert fold_b.name == base.name
    assert fold_b.execution_identity_lock is base.execution_identity_lock


def test_spawn_seed_reaches_serialized_payload_and_provenance(tmp_path, monkeypatch):
    # seed=23 must reach BOTH the worker payload the controller serializes and the
    # provenance manifest bound into the method lock.
    base = _backend(tmp_path)
    fold = base.spawn(seed=23)
    fold.configure_payload(_payload())

    # (a) provenance path records the spawned seed.
    assert fold.provenance_manifest["seed"] == 23

    # (b) the seed the worker actually receives is the serialized payload seed.
    captured: dict[str, object] = {}

    class _StopBeforeWorker(RuntimeError):
        pass

    def _spy_write_payload(work_dir: str, payload: dict) -> str:
        captured["seed"] = payload["seed"]
        raise _StopBeforeWorker

    monkeypatch.setattr(baseline_subprocess, "write_payload", _spy_write_payload)
    with pytest.raises(_StopBeforeWorker):
        fold.predict(None, [("A", "B")], 3)
    assert captured["seed"] == 23


def test_failed_repredict_clears_stale_manifest_and_checkpoint(tmp_path, monkeypatch) -> None:
    backend = _backend(tmp_path)
    backend.configure_payload(_payload())
    backend._last_execution_manifest = {"checkpoint_sha256": "a" * 64}
    backend._last_checkpoint_path = "/stale/checkpoint"

    class _StopBeforeWorker(RuntimeError):
        pass

    def _stop(*args, **kwargs):
        raise _StopBeforeWorker

    monkeypatch.setattr(baseline_subprocess, "write_payload", _stop)
    with pytest.raises(_StopBeforeWorker):
        backend.predict(None, [("A", "B")], 3)
    assert backend._last_execution_manifest is None
    assert backend._last_checkpoint_path is None


def test_configuring_fold_b_cannot_change_fold_a(tmp_path):
    # A previously spawned & configured fold-A backend is immune to fold-B config.
    base = _backend(tmp_path)
    fold_a = base.spawn(seed=11)
    fold_b = base.spawn(seed=23)

    fold_a.configure_payload(_payload())
    payload_a = fold_a._payload

    fold_b.configure_payload(_payload())

    # A's bound snapshot is the same object, byte-identical, and independent of B.
    assert fold_a._payload is payload_a
    assert fold_a._payload is not fold_b._payload
    assert fold_a.seed == 11
    assert write_payload(str(tmp_path / "a"), fold_a._payload) == write_payload(
        str(tmp_path / "a2"), payload_a
    )
