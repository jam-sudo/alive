"""Tests for the admission-grade GEARS Probe-A evidence contract."""

from __future__ import annotations

import importlib.util
import io
import json
import pickle
import subprocess
import sys
import types
import zipfile
from pathlib import Path
from types import SimpleNamespace

import anndata as ad
import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from alive.compose.approximation_bias import (
    PROBE_A_ADAPTER_TRANSFORM,
    PROBE_A_NEGATIVE_OUTPUT_POLICY,
    PROBE_A_OWNER_POLICY_PATH,
    PROBE_A_REPRESENTATION,
    load_probe_a_evidence,
    probe_a_owner_policy_sha256,
    validate_probe_a_evidence,
)
from alive.compose.fit_role import row_identity_sha256
from alive.compose.gears_probe_a import (
    ADMISSION_PATH,
    ADMISSION_SCHEMA,
    COMMAND_RECORD_SCHEMA,
    GEARS_LOCK_PATH,
    INPUTS_SCHEMA,
    MANIFEST_PATH,
    MANIFEST_SCHEMA,
    NEGATIVE_VERIFICATION_SCHEMA,
    PREPARATION_LOCK_PATH,
    PROBE_INPUT_ADATA_SCHEMA,
    PROBE_INPUT_MANIFEST_SCHEMA,
    PROBE_INPUT_TRANSFORM,
    PROTOCOL,
    RAW_SCHEMA,
    REGISTRATION_PATH,
    REGISTRATION_SCHEMA,
    REPORT_PATH,
    REPORT_SCHEMA,
    ROLE_ATTESTATION_SCHEMA,
    ROSTER_RECEIPT_SCHEMA,
    RUNTIME_SCHEMA,
    VERIFY_PATH,
    ProbeAEvidenceError,
    _matrix_identity,
    _validate_prepared_input_chain,
    assert_clean_approved_checkout,
    assert_report_manifest_binding,
    build_admission,
    build_evidence_manifest,
    build_evidence_outputs,
    build_probe_a_report,
    repository_lock_sha256,
    validate_admission,
    validate_evidence_manifest,
    validate_evidence_semantics,
    validate_negative_verification,
    validate_probe_a_report,
    validate_registration,
)
from alive.provenance import sha256_file, sha256_json

SHA = "a" * 64
COMMIT = "b" * 40
VERIFIER_SHA = "9" * 64

_REPO = Path(__file__).resolve().parents[3]
_VERIFY = _REPO / "scripts/compose/verify_gears_probe_a.py"
_PROBE_CLI = _REPO / "scripts/compose/gears_decision_probe.py"
_GEARS_WORKER = _REPO / "scripts/baselines/gears_worker.py"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_gears_probe_a", _VERIFY)
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_gears_probe_a"] = module
    spec.loader.exec_module(module)
    module.assert_clean_approved_checkout = lambda _commit: None
    return module


def _load_probe_cli():
    spec = importlib.util.spec_from_file_location("gears_decision_probe", _PROBE_CLI)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gears_decision_probe"] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_pretty_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _checkpoint_bytes(*, required_strings: set[str] | None = None) -> bytes:
    metadata = {
        "schema": "compose_gears_trained_model_v1",
        "backend_distribution": "cell-gears",
        "backend_version": "0.1.2",
        "native_input_scale_status": "PROBE_ONLY_DECISION_MEASUREMENT",
        "native_input_scale": PROBE_INPUT_TRANSFORM,
        "probe_context": {"mode": "probe_a"},
        "model_state_dict": {"fixture.weight": "external-tensor"},
        "required_strings": sorted(required_strings or set()),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, value in (
            ("archive/data.pkl", pickle.dumps(metadata, protocol=4)),
            ("archive/byteorder", b"little"),
            ("archive/data/0", b"tensor-storage"),
            ("archive/version", b"3\n"),
            ("archive/.data/serialization_id", b"fixture-id"),
        ):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o100600 << 16
            archive.writestr(info, value)
    return buffer.getvalue()


def _probe_matrix() -> list[list[float]]:
    return [[float(index), float(index) + 0.5] for index in range(402)]


def test_logical_matrix_identity_is_storage_independent_and_value_sensitive():
    dense = np.asarray([[0.0, 2.0], [3.0, 0.0]], dtype=np.float32)
    csr = sparse.csr_matrix(dense)
    csc = sparse.csc_matrix(dense.astype(np.float64))
    assert _matrix_identity(dense, "dense") == _matrix_identity(csr, "csr")
    assert _matrix_identity(csr, "csr") == _matrix_identity(csc, "csc")
    probe_cli = _load_probe_cli()
    assert probe_cli._matrix_identity(csr, label="runner csr") == _matrix_identity(csr, "csr")
    changed = dense.copy()
    changed[1, 0] = 4.0
    assert _matrix_identity(changed, "changed") != _matrix_identity(dense, "dense")


def _registration(root: Path) -> tuple[dict, str]:
    body = {
        "schema": REGISTRATION_SCHEMA,
        "protocol": PROTOCOL,
        "git_commit": COMMIT,
        "owner_policy_sha256": probe_a_owner_policy_sha256(),
        "input_scale": {
            "normalization_target": 10000.0,
            "transform": "full_library_normalize_log1p_then_roster_subset",
        },
        "determinism": {"max_abs_error_tolerance": 0.0},
        "control_count": {
            "counts": [1, 8, 300, 301, 400],
            "first_300_max_abs_error_tolerance": 1e-5,
        },
        "output_bridge": {
            "representation": PROBE_A_REPRESENTATION,
            "transform": PROBE_A_ADAPTER_TRANSFORM,
            "negative_output_policy": PROBE_A_NEGATIVE_OUTPUT_POLICY,
            "max_abs_error_tolerance": 1e-5,
        },
    }
    registration = {**body, "self_checksum": sha256_json(body)}
    path = root / REGISTRATION_PATH
    _write_json(path, registration)
    return registration, sha256_file(path)


def _report(
    root: Path,
    *,
    registration_sha256: str,
    probe_input_manifest_sha256: str = SHA,
    probe_input_h5ad_sha256: str = "e" * 64,
    probe_row_identity_sha256: str = "f" * 64,
    roster_sha256: str = "c" * 64,
    fit_artifact_content_sha256: str = "4" * 64,
) -> dict:
    raw = root / "raw.json"
    ordered_control_row_ids = [f"control-row-{index:04d}" for index in range(400)]
    prediction = [-0.2, 1.0]
    normalization_target = 10000.0
    input_scale_sha256 = sha256_json(
        {
            "normalization_target": normalization_target,
            "transform": PROBE_INPUT_TRANSFORM,
        }
    )
    producer = {
        "backend_distribution": "cell-gears",
        "backend_version": "0.1.2",
        "gears_dependency_lock_sha256": repository_lock_sha256(GEARS_LOCK_PATH),
        "gears_installed_packages_sha256": "e" * 64,
        "input_scale_sha256": input_scale_sha256,
        "normalization_target": normalization_target,
        "registration_sha256": registration_sha256,
        "worker_code_sha256": sha256_file(_GEARS_WORKER),
        "probe_driver_code_sha256": sha256_file(_PROBE_CLI),
        "probe_input_manifest_sha256": probe_input_manifest_sha256,
        "probe_input_h5ad_sha256": probe_input_h5ad_sha256,
        "probe_row_identity_sha256": probe_row_identity_sha256,
        "ordered_control_row_identity_sha256": sha256_json(ordered_control_row_ids),
        "roster_sha256": roster_sha256,
        "query": ["GENE_A", "GENE_B"],
        "seed": 11,
        "measurement_run_index": 1,
    }
    checkpoint_paths = ["checkpoints/run_1.pt", "checkpoints/run_2.pt"]
    checkpoint_strings = {
        PROBE_INPUT_TRANSFORM,
        producer["input_scale_sha256"],
        producer["gears_dependency_lock_sha256"],
        producer["gears_installed_packages_sha256"],
        producer["probe_input_h5ad_sha256"],
        producer["registration_sha256"],
        sha256_json(producer["query"]),
        producer["worker_code_sha256"],
        fit_artifact_content_sha256,
    }
    for checkpoint_path in checkpoint_paths:
        path = root / checkpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_checkpoint_bytes(required_strings=checkpoint_strings))
    raw_body = {
        "schema": RAW_SCHEMA,
        "producer": producer,
        "input_before": _matrix_identity(
            np.asarray(_probe_matrix(), dtype=np.float32), "fixture matrix"
        ),
        "input_after": _matrix_identity(
            np.asarray(_probe_matrix(), dtype=np.float32), "fixture matrix"
        ),
        "determinism_runs": [
            {
                "run_index": index + 1,
                "checkpoint_path": checkpoint_paths[index],
                "checkpoint_sha256": sha256_file(root / checkpoint_paths[index]),
                "checkpoint_bytes": (root / checkpoint_paths[index]).stat().st_size,
                "checkpoint_format": "pytorch_zip_v1",
                "seed": producer["seed"],
                "probe_input_h5ad_sha256": producer["probe_input_h5ad_sha256"],
                "query_sha256": sha256_json(producer["query"]),
                "worker_code_sha256": producer["worker_code_sha256"],
                "prediction": prediction,
            }
            for index in range(2)
        ],
        "ordered_control_row_ids": ordered_control_row_ids,
        "control_predictions": [
            {
                "count": count,
                "control_row_ids": ordered_control_row_ids[:count],
                "per_control_prediction": [prediction for _ in range(count)],
                "public_prediction": prediction,
            }
            for count in (1, 8, 300, 301, 400)
        ],
        "public_prediction": prediction,
        "bridge_prediction": prediction,
    }
    raw_payload = {**raw_body, "self_checksum": sha256_json(raw_body)}
    _write_json(raw, raw_payload)
    body = {
        "schema": REPORT_SCHEMA,
        "protocol": PROTOCOL,
        "status": "pass",
        "git_commit": COMMIT,
        "registration_sha256": registration_sha256,
        "runtime_sha256": SHA,
        "input_manifest_sha256": "c" * 64,
        "source_fingerprint_sha256": "d" * 64,
        "input_scale": {
            "before_sha256": sha256_json(raw_body["input_before"]),
            "after_sha256": sha256_json(raw_body["input_after"]),
            "exact_equal": True,
            "normalization_target": 10000.0,
            "transform": "full_library_normalize_log1p_then_roster_subset",
        },
        "determinism": {
            "checkpoint_sha256": [run["checkpoint_sha256"] for run in raw_body["determinism_runs"]],
            "prediction_sha256": [
                sha256_json(run["prediction"]) for run in raw_body["determinism_runs"]
            ],
            "max_abs_error": 0.0,
            "tolerance": 0.0,
            "verdict": "pass",
        },
        "control_count": {
            "counts": [1, 8, 300, 301, 400],
            "prediction_sha256": [
                sha256_json(item["public_prediction"]) for item in raw_body["control_predictions"]
            ],
            "first_300_max_abs_error": 0.0,
            "tolerance": 1e-5,
            "verdict": "pass",
        },
        "output_scale": {
            "minimum": -0.2,
            "median": 0.4,
            "maximum": 1.0,
            "negative_fraction": 0.5,
            "near_integer_fraction": 0.5,
        },
        "output_bridge": {
            "representation": PROBE_A_REPRESENTATION,
            "verdict": "pass",
            "tolerance": 1e-5,
            "max_abs_error": 0.0,
        },
        "raw_samples": [{"path": "raw.json", "sha256": sha256_file(raw)}],
    }
    return {**body, "self_checksum": sha256_json(body)}


def _resign(payload: dict, checksum_field: str = "self_checksum") -> None:
    body = {key: value for key, value in payload.items() if key != checksum_field}
    payload[checksum_field] = sha256_json(body)


def _file_entry(root: Path, role: str, relpath: str) -> dict:
    path = root / relpath
    return {
        "role": role,
        "path": relpath,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _refresh_manifest_entry(manifest: dict, root: Path, relpath: str) -> None:
    path = root / relpath
    entry = next(item for item in manifest["files"] if item["path"] == relpath)
    entry.update(sha256=sha256_file(path), bytes=path.stat().st_size)


def _manifest(files: list[dict]) -> dict:
    body = {
        "schema": MANIFEST_SCHEMA,
        "protocol": PROTOCOL,
        "git_commit": COMMIT,
        "files": files,
    }
    return {**body, "manifest_checksum": sha256_json(body)}


def _complete_evidence(root: Path) -> tuple[dict, dict, dict, str, str, str]:
    registration, registration_sha = _registration(root)
    runtime_body = {
        "schema": RUNTIME_SCHEMA,
        "protocol": PROTOCOL,
        "git_commit": COMMIT,
        "pod_instance": "unit-test-pod",
        "gpu_model": "A100",
        "gpu_uuid": "GPU-unit-test",
        "driver_version": "555.42",
        "cuda_version": "12.4",
        "cpu_model": "unit-test-cpu",
        "cpu_count": 8,
        "ram_bytes": 64 * 1024**3,
        "image_digest": f"sha256:{'7' * 64}",
        "python_version": "3.12.13",
        "preparation_dependency_lock_sha256": repository_lock_sha256(PREPARATION_LOCK_PATH),
        "gears_dependency_lock_sha256": repository_lock_sha256(GEARS_LOCK_PATH),
        "gears_installed_packages_sha256": "e" * 64,
        "runtime_fingerprint_sha256": "8" * 64,
        "network_disabled": True,
    }
    _write_json(
        root / "runtime.json",
        {**runtime_body, "self_checksum": sha256_json(runtime_body)},
    )
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "logs/gene2go_nodes.json").write_text("pinned nodes\n", encoding="utf-8")

    receipt_body = {
        "alias_artifact_sha256": "1" * 64,
        "candidate_artifact_sha256": "2" * 64,
        "driver_code_sha256": sha256_file(_PROBE_CLI),
        "preparation_dependency_lock_sha256": runtime_body["preparation_dependency_lock_sha256"],
        "gears_dependency_lock_sha256": runtime_body["gears_dependency_lock_sha256"],
        "fit_artifact_content_sha256": "4" * 64,
        "gene2go_nodes_artifact_sha256": sha256_file(root / "logs/gene2go_nodes.json"),
        "generator_code_sha256": "6" * 64,
        "n_target": 2000,
        "ordered_roster_sha256": "7" * 64,
        "payload_sha256": "8" * 64,
        "report_file_sha256": "9" * 64,
        "response_artifact_sha256": "a" * 64,
        "runtime_fingerprint_sha256": "8" * 64,
        "roster_artifact_checksum": "b" * 64,
        "roster_file_sha256": "c" * 64,
        "schema": ROSTER_RECEIPT_SCHEMA,
    }
    receipt = {**receipt_body, "manifest_checksum": sha256_json(receipt_body)}
    receipt_path = root / "roster_receipts/receipt.json"
    _write_pretty_json(receipt_path, receipt)

    source_row_ids = [f"control-row-{index:04d}" for index in range(400)] + [
        "single-row-0000",
        "combo-row-0000",
    ]
    roles = ["control"] * 400 + ["singles", "combo_calibration"]
    perturbations = ["control"] * 400 + ["GENE_A", "GENE_A_GENE_B"]
    rows = list(zip(source_row_ids, roles, perturbations, strict=True))
    row_sha256 = row_identity_sha256(rows)
    selected_source_row_ids_sha256 = sha256_json(source_row_ids)
    matrix_logical_sha256 = _matrix_identity(
        sparse.csr_matrix(np.asarray(_probe_matrix(), dtype=np.float32)), "fixture matrix"
    )["logical_csr_sha256"]
    probe = ad.AnnData(
        X=sparse.csr_matrix(np.asarray(_probe_matrix(), dtype=np.float32)),
        obs=pd.DataFrame(
            {
                "source_row_id": source_row_ids,
                "role": roles,
                "perturbation": perturbations,
            },
            index=[f"cell-{index:04d}" for index in range(402)],
        ),
        var=pd.DataFrame(index=["GENE_A", "GENE_B"]),
    )
    probe.uns.update(
        {
            "schema": PROBE_INPUT_ADATA_SCHEMA,
            "expression_scale": PROBE_INPUT_TRANSFORM,
            "fit_artifact_content_sha256": receipt["fit_artifact_content_sha256"],
            "normalization_target": 10000.0,
            "ordered_roster_sha256": receipt["ordered_roster_sha256"],
            "probe_driver_code_sha256": receipt["driver_code_sha256"],
            "probe_runtime_fingerprint_sha256": receipt["runtime_fingerprint_sha256"],
            "response_artifact_sha256": receipt["response_artifact_sha256"],
            "roster_artifact_checksum": receipt["roster_artifact_checksum"],
            "roster_receipt_sha256": sha256_file(receipt_path),
            "row_identity_sha256": row_sha256,
            "matrix_dtype": "float32-le",
            "matrix_format": "canonical_csr",
            "matrix_logical_sha256": matrix_logical_sha256,
            "selected_source_row_ids_sha256": selected_source_row_ids_sha256,
            "preparation_dependency_lock_sha256": runtime_body[
                "preparation_dependency_lock_sha256"
            ],
            "gears_dependency_lock_sha256": runtime_body["gears_dependency_lock_sha256"],
        }
    )
    probe_h5ad_path = root / "probe_input.h5ad"
    probe.write_h5ad(probe_h5ad_path)
    probe_manifest_body = {
        "expression_scale": PROBE_INPUT_TRANSFORM,
        "fit_artifact_content_sha256": receipt["fit_artifact_content_sha256"],
        "full_var_order_sha256": "0" * 64,
        "gears_dependency_lock_sha256": runtime_body["gears_dependency_lock_sha256"],
        "matrix_dtype": "float32-le",
        "matrix_format": "canonical_csr",
        "matrix_logical_sha256": matrix_logical_sha256,
        "n_cells": 402,
        "n_genes": 2,
        "normalization_target": 10000.0,
        "ordered_roster_sha256": receipt["ordered_roster_sha256"],
        "output_h5ad_sha256": sha256_file(probe_h5ad_path),
        "payload_sha256": receipt["payload_sha256"],
        "preparation_dependency_lock_sha256": runtime_body["preparation_dependency_lock_sha256"],
        "probe_driver_code_sha256": receipt["driver_code_sha256"],
        "probe_runtime_fingerprint_sha256": receipt["runtime_fingerprint_sha256"],
        "response_artifact_sha256": receipt["response_artifact_sha256"],
        "role_contract": {
            "calibration_pair_ids": [["GENE_A", "GENE_B"]],
            "combo_separator": "_",
            "control_token": "control",
            "sealed_pair_ids": [["GENE_C", "GENE_D"]],
            "single_gene_ids": ["GENE_A"],
        },
        "role_counts": {"control": 400, "singles": 1, "combo_calibration": 1},
        "roster_artifact_checksum": receipt["roster_artifact_checksum"],
        "roster_file_sha256": receipt["roster_file_sha256"],
        "roster_receipt_sha256": sha256_file(receipt_path),
        "row_identity_sha256": row_sha256,
        "selected_source_row_ids_sha256": selected_source_row_ids_sha256,
        "schema": PROBE_INPUT_MANIFEST_SCHEMA,
    }
    probe_manifest = {
        **probe_manifest_body,
        "manifest_checksum": sha256_json(probe_manifest_body),
    }
    probe_manifest_path = root / "probe_input_manifest.json"
    _write_pretty_json(probe_manifest_path, probe_manifest)

    fit_role_counts = {"control": 400, "singles": 1, "combo_calibration": 1}
    inputs_body = {
        "schema": INPUTS_SCHEMA,
        "protocol": PROTOCOL,
        "git_commit": COMMIT,
        "source_sha256": "1" * 64,
        "gene2go_manifest_sha256": "2" * 64,
        "pair_manifest_sha256": "3" * 64,
        "alias_artifact_sha256": "4" * 64,
        "fit_role_artifact_sha256": "5" * 64,
        "response_artifact_sha256": receipt["response_artifact_sha256"],
        "roster_receipt_sha256": sha256_file(receipt_path),
        "roster_sha256": receipt["roster_file_sha256"],
        "preparation_dependency_lock_sha256": runtime_body["preparation_dependency_lock_sha256"],
        "gears_dependency_lock_sha256": runtime_body["gears_dependency_lock_sha256"],
        "fit_role_counts": fit_role_counts,
        "probe_input_manifest_sha256": sha256_file(probe_manifest_path),
        "probe_input_h5ad_sha256": sha256_file(probe_h5ad_path),
        "probe_row_identity_sha256": row_sha256,
        "ordered_control_row_identity_sha256": sha256_json(source_row_ids[:400]),
    }
    _write_json(
        root / "inputs.json",
        {**inputs_body, "self_checksum": sha256_json(inputs_body)},
    )

    role_body = {
        "schema": ROLE_ATTESTATION_SCHEMA,
        "protocol": PROTOCOL,
        "git_commit": COMMIT,
        "fit_role_counts": fit_role_counts,
        "sealed_pair_overlap_count": 0,
        "sealed_row_read_count": 0,
        "reader_spy": {
            "status": "pass",
            "selected_source_row_ids_sha256": selected_source_row_ids_sha256,
            "observed_source_row_ids_sha256": selected_source_row_ids_sha256,
            "observed_source_row_count": len(source_row_ids),
            "forbidden_source_row_read_count": 0,
        },
    }
    _write_json(
        root / "role_attestation.json",
        {**role_body, "self_checksum": sha256_json(role_body)},
    )
    (root / "probe_a_source.txt").write_text("pinned source closure\n", encoding="utf-8")
    (root / "logs/run.log").parent.mkdir(parents=True, exist_ok=True)
    (root / "logs/run.log").write_text("complete\n", encoding="utf-8")

    report = _report(
        root,
        registration_sha256=registration_sha,
        probe_input_manifest_sha256=sha256_file(probe_manifest_path),
        probe_input_h5ad_sha256=sha256_file(probe_h5ad_path),
        probe_row_identity_sha256=row_sha256,
        roster_sha256=receipt["roster_file_sha256"],
    )
    report["runtime_sha256"] = sha256_file(root / "runtime.json")
    report["input_manifest_sha256"] = sha256_file(root / "inputs.json")
    report["source_fingerprint_sha256"] = sha256_file(root / "probe_a_source.txt")
    _resign(report)
    _write_json(root / REPORT_PATH, report)

    command_lines: list[str] = []
    for index, command in enumerate(
        (
            "build-roster",
            "prepare-input",
            "verify-input",
            "build-probe-a-registration",
            "probe-a",
            "build-probe-a-report",
        )
    ):
        command_body = {
            "schema": COMMAND_RECORD_SCHEMA,
            "command": command,
            "argv": [
                "uv",
                "run",
                "python",
                "scripts/compose/gears_decision_probe.py",
                command,
            ],
            "cwd": "/workspace/ALIVE",
            "env": {
                "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
                "PYTHONHASHSEED": "11",
            },
            "started_at_utc": f"2026-07-17T00:00:0{index}+00:00",
            "ended_at_utc": f"2026-07-17T00:00:0{index + 1}+00:00",
            "exit_code": 0,
            "primary_file_sha256": (
                sha256_file(root / "raw.json")
                if command == "probe-a"
                else (
                    registration_sha
                    if command == "build-probe-a-registration"
                    else (
                        sha256_file(root / REPORT_PATH)
                        if command == "build-probe-a-report"
                        else str(index + 1) * 64
                    )
                )
            ),
            "runtime_fingerprint_sha256": runtime_body["runtime_fingerprint_sha256"],
        }
        if command == "build-probe-a-registration":
            command_body["argv"].extend(
                [
                    "--evidence-root",
                    "/workspace/evidence",
                    "--probe-manifest",
                    "/workspace/evidence/probe_input_manifest.json",
                    "--probe-manifest-sha256",
                    sha256_file(probe_manifest_path),
                    "--owner-policy",
                    f"/workspace/ALIVE/{PROBE_A_OWNER_POLICY_PATH}",
                    "--owner-policy-sha256",
                    probe_a_owner_policy_sha256(),
                    "--git-commit",
                    COMMIT,
                    "--out-registration",
                    f"/workspace/evidence/{REGISTRATION_PATH}",
                ]
            )
        elif command == "build-roster":
            command_body["argv"].extend(
                [
                    "--gene2go-nodes-artifact",
                    "/workspace/evidence/logs/gene2go_nodes.json",
                    "--gene2go-nodes-artifact-sha256",
                    receipt["gene2go_nodes_artifact_sha256"],
                    "--gears-resource-manifest",
                    "/workspace/gears_data/go_resource_manifest.json",
                    "--gears-resource-manifest-sha256",
                    inputs_body["gene2go_manifest_sha256"],
                    "--gene2go-source",
                    "/workspace/gears_data/gene2go_all.pkl",
                    "--gene2go-source-sha256",
                    "f" * 64,
                ]
            )
        elif command == "probe-a":
            command_body["argv"].extend(
                [
                    "--payload-dir",
                    "/workspace/payload",
                    "--probe-a-registration",
                    f"/workspace/evidence/{REGISTRATION_PATH}",
                    "--probe-a-registration-sha256",
                    registration_sha,
                    "--git-commit",
                    COMMIT,
                    "--probe-manifest",
                    "/workspace/evidence/probe_input_manifest.json",
                    "--probe-manifest-sha256",
                    sha256_file(probe_manifest_path),
                    "--h5ad",
                    "/workspace/evidence/probe_input.h5ad",
                    "--roster",
                    "/workspace/roster.json",
                    "--roster-receipt",
                    "/workspace/evidence/roster_receipts/receipt.json",
                    "--approved-root",
                    "/workspace/approved",
                    "--evidence-root",
                    "/workspace/evidence",
                    "--out-raw",
                    "/workspace/evidence/raw.json",
                    "--checkpoint-dir",
                    "/workspace/evidence/checkpoints",
                ]
            )
        elif command == "build-probe-a-report":
            command_body["argv"].extend(
                [
                    "--evidence-root",
                    "/workspace/evidence",
                    "--raw-sample",
                    "/workspace/evidence/raw.json",
                    "--raw-sample-sha256",
                    sha256_file(root / "raw.json"),
                    "--probe-a-registration",
                    f"/workspace/evidence/{REGISTRATION_PATH}",
                    "--probe-a-registration-sha256",
                    registration_sha,
                    "--git-commit",
                    COMMIT,
                    "--out-report",
                    f"/workspace/evidence/{REPORT_PATH}",
                ]
            )
        command = {**command_body, "self_checksum": sha256_json(command_body)}
        command_lines.append(json.dumps(command, sort_keys=True, separators=(",", ":")))
    (root / "commands.jsonl").write_text("\n".join(command_lines) + "\n", encoding="utf-8")

    role_paths = [
        ("commands", "commands.jsonl"),
        ("runtime", "runtime.json"),
        ("inputs", "inputs.json"),
        ("role_attestation", "role_attestation.json"),
        ("probe_a_registration", REGISTRATION_PATH),
        ("probe_a_report", REPORT_PATH),
        ("probe_a_source", "probe_a_source.txt"),
        ("probe_input_manifest", "probe_input_manifest.json"),
        ("probe_input_h5ad", "probe_input.h5ad"),
        ("roster_receipt", "roster_receipts/receipt.json"),
        ("probe_a_checkpoint", "checkpoints/run_1.pt"),
        ("probe_a_checkpoint", "checkpoints/run_2.pt"),
        ("raw_sample", "raw.json"),
        ("log", "logs/run.log"),
        ("log", "logs/gene2go_nodes.json"),
    ]
    manifest = _manifest([_file_entry(root, role, path) for role, path in role_paths])
    _write_json(root / MANIFEST_PATH, manifest)
    return (
        registration,
        report,
        manifest,
        registration_sha,
        sha256_file(root / REPORT_PATH),
        sha256_file(root / MANIFEST_PATH),
    )


def _negative_evidence(root: Path) -> tuple[dict, dict, dict, str, str, str]:
    """Convert the complete fixture into a bridge-failed, fully bound evidence tree."""
    registration, _, _, registration_sha, _, _ = _complete_evidence(root)
    (root / REPORT_PATH).unlink()
    (root / MANIFEST_PATH).unlink()

    raw_path = root / "raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    count_400 = next(item for item in raw["control_predictions"] if item["count"] == 400)
    count_400["per_control_prediction"] = [[-0.1, 1.0] for _ in range(400)]
    raw["bridge_prediction"] = [-0.1, 1.0]
    _resign(raw)
    _write_json(raw_path, raw)

    report = build_probe_a_report(
        evidence_root=root,
        raw_sample_path="raw.json",
        raw_sample_sha256=sha256_file(raw_path),
        registration=registration,
        registration_sha256=registration_sha,
        expected_git_commit=COMMIT,
        runtime_sha256=sha256_file(root / "runtime.json"),
        inputs_sha256=sha256_file(root / "inputs.json"),
        source_fingerprint_sha256=sha256_file(root / "probe_a_source.txt"),
    )
    _write_json(root / REPORT_PATH, report)

    command_path = root / "commands.jsonl"
    commands = [json.loads(line) for line in command_path.read_text(encoding="utf-8").splitlines()]
    for command in commands:
        if command["command"] == "probe-a":
            command["primary_file_sha256"] = sha256_file(raw_path)
        elif command["command"] == "build-probe-a-report":
            command["primary_file_sha256"] = sha256_file(root / REPORT_PATH)
            sha_index = command["argv"].index("--raw-sample-sha256") + 1
            command["argv"][sha_index] = sha256_file(raw_path)
        _resign(command)
    command_path.write_text(
        "\n".join(
            json.dumps(command, sort_keys=True, separators=(",", ":")) for command in commands
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = build_evidence_manifest(evidence_root=root, expected_git_commit=COMMIT)
    _write_json(root / MANIFEST_PATH, manifest)
    return (
        registration,
        report,
        manifest,
        registration_sha,
        sha256_file(root / REPORT_PATH),
        sha256_file(root / MANIFEST_PATH),
    )


def _validate_report(root: Path, report: dict, registration: dict, registration_sha: str) -> None:
    validate_probe_a_report(
        report,
        registration=registration,
        registration_sha256=registration_sha,
        evidence_root=root,
        expected_git_commit=COMMIT,
    )


def _prepared_chain_arguments(root: Path, registration: dict, registration_sha256: str) -> dict:
    manifest = json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))
    entries = {entry["role"]: entry for entry in manifest["files"]}
    return {
        "root": root,
        "manifest_entry": entries["probe_input_manifest"],
        "h5ad_entry": entries["probe_input_h5ad"],
        "inputs": json.loads((root / "inputs.json").read_text(encoding="utf-8")),
        "receipt": json.loads((root / "roster_receipts/receipt.json").read_text(encoding="utf-8")),
        "runtime": json.loads((root / "runtime.json").read_text(encoding="utf-8")),
        "raw": json.loads((root / "raw.json").read_text(encoding="utf-8")),
        "role_attestation": json.loads(
            (root / "role_attestation.json").read_text(encoding="utf-8")
        ),
        "registration": registration,
        "registration_sha256": registration_sha256,
    }


def test_clean_checkout_gate_binds_head_and_rejects_tracked_or_untracked_drift(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    git("init", "-q")
    git("config", "user.name", "Probe Fixture")
    git("config", "user.email", "probe@example.invalid")
    tracked = repository / "tracked.txt"
    tracked.write_text("approved\n", encoding="utf-8")
    git("add", "tracked.txt")
    git("commit", "-q", "-m", "approved")
    approved = git("rev-parse", "HEAD")

    assert_clean_approved_checkout(approved, repository_root=repository)
    with pytest.raises(ProbeAEvidenceError, match="approved Git commit"):
        assert_clean_approved_checkout("0" * 40, repository_root=repository)

    (repository / "untracked.txt").write_text("drift\n", encoding="utf-8")
    with pytest.raises(ProbeAEvidenceError, match="dirty"):
        assert_clean_approved_checkout(approved, repository_root=repository)
    (repository / "untracked.txt").unlink()

    tracked.write_text("modified\n", encoding="utf-8")
    with pytest.raises(ProbeAEvidenceError, match="dirty"):
        assert_clean_approved_checkout(approved, repository_root=repository)


def test_report_and_manifest_builders_derive_the_complete_contract(tmp_path):
    registration, report, _, registration_sha, _, _ = _complete_evidence(tmp_path)
    rebuilt_report = build_probe_a_report(
        evidence_root=tmp_path,
        raw_sample_path="raw.json",
        raw_sample_sha256=sha256_file(tmp_path / "raw.json"),
        registration=registration,
        registration_sha256=registration_sha,
        expected_git_commit=COMMIT,
        runtime_sha256=sha256_file(tmp_path / "runtime.json"),
        inputs_sha256=sha256_file(tmp_path / "inputs.json"),
        source_fingerprint_sha256=sha256_file(tmp_path / "probe_a_source.txt"),
    )
    assert rebuilt_report == report

    (tmp_path / MANIFEST_PATH).unlink()
    rebuilt_manifest = build_evidence_manifest(
        evidence_root=tmp_path,
        expected_git_commit=COMMIT,
    )
    validate_evidence_manifest(
        rebuilt_manifest,
        evidence_root=tmp_path,
        expected_git_commit=COMMIT,
    )
    assert {entry["path"] for entry in rebuilt_manifest["files"]} == {
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()
    }


def test_failed_report_is_derived_from_measured_gates_and_remains_verifiable(tmp_path):
    registration, report, _, registration_sha, _, _ = _negative_evidence(tmp_path)
    assert report["status"] == "failed"
    assert report["determinism"]["verdict"] == "pass"
    assert report["control_count"]["verdict"] == "fail"
    assert report["output_bridge"]["verdict"] == "fail"
    _validate_report(tmp_path, report, registration, registration_sha)

    report["status"] = "pass"
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="status disagrees"):
        _validate_report(tmp_path, report, registration, registration_sha)


def test_registration_builder_derives_scale_from_manifest_and_is_write_once(tmp_path, monkeypatch):
    _complete_evidence(tmp_path)
    (tmp_path / REGISTRATION_PATH).unlink()
    probe_cli = _load_probe_cli()
    monkeypatch.setattr(probe_cli, "assert_clean_approved_checkout", lambda _commit: None)
    manifest_path = tmp_path / "probe_input_manifest.json"
    digest = probe_cli.publish_probe_a_registration(
        evidence_root=tmp_path,
        probe_manifest_path=manifest_path,
        probe_manifest_sha256=sha256_file(manifest_path),
        owner_policy_path=_REPO / PROBE_A_OWNER_POLICY_PATH,
        owner_policy_sha256=probe_a_owner_policy_sha256(),
        expected_git_commit=COMMIT,
        out_registration=tmp_path / REGISTRATION_PATH,
    )
    registration = json.loads((tmp_path / REGISTRATION_PATH).read_text(encoding="utf-8"))
    assert digest == sha256_file(tmp_path / REGISTRATION_PATH)
    assert registration["input_scale"]["normalization_target"] == 10000.0
    assert registration["owner_policy_sha256"] == probe_a_owner_policy_sha256()
    assert registration["output_bridge"] == {
        "representation": PROBE_A_REPRESENTATION,
        "transform": PROBE_A_ADAPTER_TRANSFORM,
        "negative_output_policy": PROBE_A_NEGATIVE_OUTPUT_POLICY,
        "max_abs_error_tolerance": 1e-5,
    }
    with pytest.raises(probe_cli.GeneUniverseError, match="already exists"):
        probe_cli.publish_probe_a_registration(
            evidence_root=tmp_path,
            probe_manifest_path=manifest_path,
            probe_manifest_sha256=sha256_file(manifest_path),
            owner_policy_path=_REPO / PROBE_A_OWNER_POLICY_PATH,
            owner_policy_sha256=probe_a_owner_policy_sha256(),
            expected_git_commit=COMMIT,
            out_registration=tmp_path / REGISTRATION_PATH,
        )


def test_manifest_builder_rejects_unclassified_evidence(tmp_path):
    _complete_evidence(tmp_path)
    (tmp_path / MANIFEST_PATH).unlink()
    (tmp_path / "unclassified.bin").write_bytes(b"unregistered evidence")
    with pytest.raises(ProbeAEvidenceError, match="cannot classify"):
        build_evidence_manifest(evidence_root=tmp_path, expected_git_commit=COMMIT)


def test_offline_chain_independently_rejects_sealed_rows_and_reader_spy_drift(tmp_path):
    registration, _, _, registration_sha, _, _ = _complete_evidence(tmp_path)
    arguments = _prepared_chain_arguments(tmp_path, registration, registration_sha)

    reader_drift = dict(arguments)
    reader_drift["role_attestation"] = json.loads(json.dumps(arguments["role_attestation"]))
    reader_drift["role_attestation"]["reader_spy"]["observed_source_row_ids_sha256"] = "0" * 64
    with pytest.raises(ProbeAEvidenceError, match="reader-spy attestation disagrees"):
        _validate_prepared_input_chain(**reader_drift)

    sealed_contract = dict(arguments)
    prepared_manifest = json.loads(
        (tmp_path / "probe_input_manifest.json").read_text(encoding="utf-8")
    )
    prepared_manifest["role_contract"]["calibration_pair_ids"] = [["GENE_X", "GENE_Y"]]
    prepared_manifest["role_contract"]["sealed_pair_ids"] = [["GENE_A", "GENE_B"]]
    body = {key: value for key, value in prepared_manifest.items() if key != "manifest_checksum"}
    prepared_manifest["manifest_checksum"] = sha256_json(body)
    sealed_contract["manifest_entry"] = dict(arguments["manifest_entry"])
    _write_pretty_json(tmp_path / "probe_input_manifest.json", prepared_manifest)
    manifest_bytes = (tmp_path / "probe_input_manifest.json").read_bytes()
    sealed_contract["manifest_entry"]["sha256"] = sha256_file(
        tmp_path / "probe_input_manifest.json"
    )
    sealed_contract["manifest_entry"]["bytes"] = len(manifest_bytes)
    sealed_contract["inputs"] = dict(arguments["inputs"])
    sealed_contract["inputs"]["probe_input_manifest_sha256"] = sealed_contract["manifest_entry"][
        "sha256"
    ]
    with pytest.raises(ProbeAEvidenceError, match="metadata-derived roles"):
        _validate_prepared_input_chain(**sealed_contract)


def test_registration_and_report_promote_to_consumer_compatible_admission(tmp_path):
    registration, report, _, registration_sha, report_sha, manifest_sha = _complete_evidence(
        tmp_path
    )
    validate_registration(registration, expected_git_commit=COMMIT)
    _validate_report(tmp_path, report, registration, registration_sha)
    outputs = build_evidence_outputs(
        report_bytes=(tmp_path / REPORT_PATH).read_bytes(),
        report_sha256=report_sha,
        registration_bytes=(tmp_path / REGISTRATION_PATH).read_bytes(),
        registration_sha256=registration_sha,
        manifest_bytes=(tmp_path / MANIFEST_PATH).read_bytes(),
        evidence_root=tmp_path,
        evidence_manifest_sha256=manifest_sha,
        expected_git_commit=COMMIT,
        verifier_code_sha256=VERIFIER_SHA,
    )
    admission = outputs.admission
    assert admission["schema"] == ADMISSION_SCHEMA
    assert admission["registration_sha256"] == registration_sha
    validate_admission(
        admission,
        registration=registration,
        registration_sha256=registration_sha,
        verification=outputs.verification,
        verification_sha256=outputs.verification_sha256,
        expected_git_commit=COMMIT,
    )


def test_negative_result_gets_verifier_receipt_but_never_an_admission(tmp_path):
    registration, report, _, registration_sha, report_sha, manifest_sha = _negative_evidence(
        tmp_path
    )
    kwargs = {
        "report_bytes": (tmp_path / REPORT_PATH).read_bytes(),
        "report_sha256": report_sha,
        "registration_bytes": (tmp_path / REGISTRATION_PATH).read_bytes(),
        "registration_sha256": registration_sha,
        "manifest_bytes": (tmp_path / MANIFEST_PATH).read_bytes(),
        "evidence_root": tmp_path,
        "evidence_manifest_sha256": manifest_sha,
        "expected_git_commit": COMMIT,
        "verifier_code_sha256": VERIFIER_SHA,
    }
    outputs = build_evidence_outputs(**kwargs)
    assert outputs.admission is None
    assert outputs.verification["schema"] == NEGATIVE_VERIFICATION_SCHEMA
    assert outputs.verification["status"] == "failed"
    assert outputs.verification["gate_verdicts"] == {
        "determinism": "pass",
        "control_count": "fail",
        "output_bridge": "fail",
    }
    validate_negative_verification(
        outputs.verification,
        report=report,
        report_sha256=report_sha,
        registration_sha256=registration_sha,
        evidence_manifest_sha256=manifest_sha,
        verifier_code_sha256=VERIFIER_SHA,
        expected_git_commit=COMMIT,
    )
    with pytest.raises(ProbeAEvidenceError, match="admission is forbidden"):
        build_admission(**kwargs)

    forged = json.loads(json.dumps(outputs.verification))
    forged["gate_verdicts"]["output_bridge"] = "pass"
    _resign(forged)
    with pytest.raises(ProbeAEvidenceError, match="gate verdicts differ"):
        validate_negative_verification(
            forged,
            report=report,
            report_sha256=report_sha,
            registration_sha256=registration_sha,
            evidence_manifest_sha256=manifest_sha,
            verifier_code_sha256=VERIFIER_SHA,
            expected_git_commit=COMMIT,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r["input_scale"].update(exact_equal=False), "input scale"),
        (
            lambda r: r["determinism"].update(checkpoint_sha256=["f" * 64, "0" * 64]),
            "determinism",
        ),
        (lambda r: r["control_count"].update(counts=[1, 8, 300]), "control-count roster"),
        (lambda r: r["output_bridge"].update(max_abs_error=2e-7), "output-bridge"),
    ],
)
def test_report_fails_closed_on_scientific_gate_mutation(tmp_path, mutate, message):
    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256=registration_sha)
    mutate(report)
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match=message):
        _validate_report(tmp_path, report, registration, registration_sha)


@pytest.mark.parametrize(
    "block",
    ["determinism", "control_count", "output_bridge"],
)
def test_posthoc_tolerance_widening_is_rejected_even_when_resigned(tmp_path, block):
    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256=registration_sha)
    report[block]["tolerance"] = 1e6
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="differs from preregistration"):
        _validate_report(tmp_path, report, registration, registration_sha)


def test_registration_tamper_and_report_registration_swap_are_rejected(tmp_path):
    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256=registration_sha)
    registration["output_bridge"]["max_abs_error_tolerance"] = 1e6
    with pytest.raises(ProbeAEvidenceError, match="self_checksum does not match"):
        _validate_report(tmp_path, report, registration, registration_sha)

    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256="0" * 64)
    with pytest.raises(ProbeAEvidenceError, match="not bound"):
        _validate_report(tmp_path, report, registration, registration_sha)


def test_registration_rejects_zero_normalization_target(tmp_path):
    registration, _ = _registration(tmp_path)
    registration["input_scale"]["normalization_target"] = 0.0
    _resign(registration)
    with pytest.raises(ProbeAEvidenceError, match="normalization_target must be positive"):
        validate_registration(registration, expected_git_commit=COMMIT)


def test_report_rejects_raw_sample_tamper_path_escape_and_symlink(tmp_path):
    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256=registration_sha)
    (tmp_path / "raw.json").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ProbeAEvidenceError, match="raw sample SHA-256"):
        _validate_report(tmp_path, report, registration, registration_sha)

    report = _report(tmp_path, registration_sha256=registration_sha)
    report["raw_samples"][0]["path"] = "../raw.json"
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="safe and relative"):
        _validate_report(tmp_path, report, registration, registration_sha)

    (tmp_path / "target.json").write_text("payload\n", encoding="utf-8")
    (tmp_path / "link.json").symlink_to(tmp_path / "target.json")
    report = _report(tmp_path, registration_sha256=registration_sha)
    report["raw_samples"] = [{"path": "link.json", "sha256": SHA}]
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="symlink"):
        _validate_report(tmp_path, report, registration, registration_sha)


def test_report_recomputes_metrics_from_raw_measurements(tmp_path):
    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256=registration_sha)
    raw_path = tmp_path / "raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["public_prediction"][0] = -10.0
    raw["bridge_prediction"][0] = -10.0
    for run in raw["determinism_runs"]:
        run["prediction"][0] = -10.0
    for control in raw["control_predictions"]:
        control["public_prediction"][0] = -10.0
        for row in control["per_control_prediction"]:
            row[0] = -10.0
    _resign(raw)
    _write_json(raw_path, raw)
    report["raw_samples"][0]["sha256"] = sha256_file(raw_path)
    report["determinism"]["prediction_sha256"] = [
        sha256_json(run["prediction"]) for run in raw["determinism_runs"]
    ]
    report["control_count"]["prediction_sha256"] = [
        sha256_json(control["public_prediction"]) for control in raw["control_predictions"]
    ]
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="output_scale.minimum.*raw measurements"):
        _validate_report(tmp_path, report, registration, registration_sha)


def test_report_rejects_unrelated_control_sets_disguised_as_first_300(tmp_path):
    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256=registration_sha)
    raw_path = tmp_path / "raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["control_predictions"][3]["control_row_ids"][300] = "unrelated-control-row"
    _resign(raw)
    _write_json(raw_path, raw)
    report["raw_samples"][0]["sha256"] = sha256_file(raw_path)
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="exact prefix"):
        _validate_report(tmp_path, report, registration, registration_sha)


def test_report_rejects_public_prediction_not_reconstructed_per_control(tmp_path):
    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256=registration_sha)
    raw_path = tmp_path / "raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["control_predictions"][0]["per_control_prediction"][0][0] = 9.0
    _resign(raw)
    _write_json(raw_path, raw)
    report["raw_samples"][0]["sha256"] = sha256_file(raw_path)
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="first_300_max_abs_error.*raw measurements"):
        _validate_report(tmp_path, report, registration, registration_sha)


def test_report_rejects_checkpoint_identity_without_matching_archived_bytes(tmp_path):
    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256=registration_sha)
    (tmp_path / "checkpoints/run_1.pt").write_bytes(b"tampered model state\n")
    with pytest.raises(ProbeAEvidenceError, match="checkpoint SHA-256 differs"):
        _validate_report(tmp_path, report, registration, registration_sha)


def test_report_rejects_digest_bound_non_pytorch_checkpoint(tmp_path):
    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256=registration_sha)
    checkpoint = tmp_path / "checkpoints/run_1.pt"
    checkpoint.write_bytes(b"not a model checkpoint\n")
    raw_path = tmp_path / "raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["determinism_runs"][0]["checkpoint_sha256"] = sha256_file(checkpoint)
    raw["determinism_runs"][0]["checkpoint_bytes"] = checkpoint.stat().st_size
    _resign(raw)
    _write_json(raw_path, raw)
    report["raw_samples"][0]["sha256"] = sha256_file(raw_path)
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="not a PyTorch ZIP checkpoint"):
        _validate_report(tmp_path, report, registration, registration_sha)


def test_report_rejects_pytorch_checkpoint_without_probe_bindings(tmp_path):
    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256=registration_sha)
    checkpoint = tmp_path / "checkpoints/run_1.pt"
    checkpoint.write_bytes(_checkpoint_bytes())
    raw_path = tmp_path / "raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["determinism_runs"][0]["checkpoint_sha256"] = sha256_file(checkpoint)
    raw["determinism_runs"][0]["checkpoint_bytes"] = checkpoint.stat().st_size
    _resign(raw)
    _write_json(raw_path, raw)
    report["raw_samples"][0]["sha256"] = sha256_file(raw_path)
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="not bound to the backend/input/query/worker"):
        _validate_report(tmp_path, report, registration, registration_sha)


def test_report_rejects_cross_run_bridge_splice(tmp_path):
    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256=registration_sha)
    raw_path = tmp_path / "raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["bridge_prediction"][0] = -0.1
    _resign(raw)
    _write_json(raw_path, raw)
    report["raw_samples"][0]["sha256"] = sha256_file(raw_path)
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="direct first-300 reconstruction"):
        _validate_report(tmp_path, report, registration, registration_sha)


def test_maintained_probe_a_command_rejects_arbitrary_measurement_publication():
    probe = _load_probe_cli()
    with pytest.raises(SystemExit):
        probe._parser().parse_args(
            [
                "probe-a",
                "--measurement-json",
                "forged.json",
                "--evidence-root",
                "evidence",
                "--out-raw",
                "evidence/raw.json",
            ]
        )
    assert not hasattr(probe, "publish_probe_a_measurements")
    assert callable(probe.run_probe_a_measurements)


def test_direct_control_predictions_use_each_prepared_control_exactly(monkeypatch):
    probe = _load_probe_cli()
    control_values = np.asarray([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]], dtype=np.float32)
    adata = ad.AnnData(
        X=sparse.csr_matrix(control_values),
        obs=pd.DataFrame(
            {"condition": ["ctrl"] * 4},
            index=[f"control-row-{index}" for index in range(4)],
        ),
        var=pd.DataFrame(index=["GENE_A", "GENE_B"]),
    )
    constructed_rows: list[list[float]] = []

    class FakeGraph:
        def __init__(self, values):
            self.values = np.asarray(values, dtype=np.float64)

        def to(self, _device):
            return self

    def create_cell_graph_for_prediction(values, pert_indices, query):
        assert pert_indices == [0]
        assert query == ["GENE_A"]
        constructed_rows.append(np.asarray(values).tolist())
        return FakeGraph(values)

    dataset_globals = {
        "create_cell_graph_for_prediction": create_cell_graph_for_prediction,
    }
    exec(
        "def create_cell_graph_dataset_for_prediction(*args, **kwargs):\n"
        "    raise AssertionError('random-sampling dataset helper must not be called')\n",
        dataset_globals,
    )
    predict_globals = {
        "np": np,
        "create_cell_graph_dataset_for_prediction": dataset_globals[
            "create_cell_graph_dataset_for_prediction"
        ],
    }
    exec(
        "def predict(self, queries):\n"
        "    values = self.adata.X.toarray()\n"
        "    return {'_'.join(queries[0]): np.mean(values, axis=0)}\n",
        predict_globals,
    )

    class FakeTensor:
        def __init__(self, values):
            self.values = np.asarray(values, dtype=np.float64)

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.values

    class FakeBatch(list):
        def to(self, _device):
            return self

    class FakeDataLoader:
        def __init__(self, graphs, batch_size, *, shuffle):
            assert batch_size == 300
            assert shuffle is False
            self.graphs = list(graphs)

        def __iter__(self):
            yield FakeBatch(self.graphs)

    class FakeModelState:
        def to(self, _device):
            return self

        def eval(self):
            return self

        def __call__(self, batch):
            return FakeTensor([graph.values + 10.0 for graph in batch])

    class NoGrad:
        def __enter__(self):
            return None

        def __exit__(self, *_args):
            return False

    fake_torch_geometric = types.ModuleType("torch_geometric")
    fake_torch_geometric.__path__ = []
    fake_loader = types.ModuleType("torch_geometric.loader")
    fake_loader.DataLoader = FakeDataLoader
    fake_torch_geometric.loader = fake_loader
    monkeypatch.setitem(sys.modules, "torch_geometric", fake_torch_geometric)
    monkeypatch.setitem(sys.modules, "torch_geometric.loader", fake_loader)

    model = SimpleNamespace(
        adata=adata,
        saved_pred={},
        pert_list=["GENE_A"],
        device="cuda",
        best_model=FakeModelState(),
    )
    model.predict = types.MethodType(predict_globals["predict"], model)
    public, per_control = probe._direct_control_predictions(
        model=model,
        torch_module=SimpleNamespace(no_grad=NoGrad),
        query=["GENE_A"],
        count=4,
        expected_control_row_ids=adata.obs_names.astype(str).tolist(),
    )

    assert public == [4.0, 5.0]
    assert per_control == (control_values + 10.0).tolist()
    assert constructed_rows == control_values.tolist()


def test_maintained_probe_a_runner_owns_fit_measurement_graph(tmp_path, monkeypatch):
    probe_cli = _load_probe_cli()
    monkeypatch.setattr(probe_cli, "assert_clean_approved_checkout", lambda _commit: None)
    evidence = tmp_path / "evidence"
    approved = tmp_path / "approved"
    evidence.mkdir()
    approved.mkdir()
    _, registration_sha = _registration(evidence)
    probe_manifest_path = evidence / "probe_input_manifest.json"
    h5ad_path = evidence / "probe_input.h5ad"
    probe_manifest_path.write_text("fixture\n", encoding="utf-8")
    h5ad_path.write_bytes(b"fixture-h5ad")
    source_ids = [f"control-row-{index:04d}" for index in range(400)] + [
        "single-row-0000",
        "combo-row-0000",
    ]
    roles = ["control"] * 400 + ["singles", "combo_calibration"]
    prepared = ad.AnnData(
        X=sparse.csr_matrix(np.asarray(_probe_matrix(), dtype=np.float32)),
        obs=pd.DataFrame(
            {"source_row_id": source_ids, "role": roles},
            index=[f"cell-{index:04d}" for index in range(402)],
        ),
        var=pd.DataFrame(index=["GENE_A", "GENE_B"]),
    )
    payload = {"calibration_pair_ids": [["GENE_A", "GENE_B"]], "seed": 11}
    manifest = {
        "expression_scale": PROBE_INPUT_TRANSFORM,
        "normalization_target": 10000.0,
        "output_h5ad_sha256": sha256_file(h5ad_path),
        "payload_sha256": "1" * 64,
        "fit_artifact_content_sha256": "2" * 64,
        "row_identity_sha256": "3" * 64,
        "roster_file_sha256": "4" * 64,
        "gears_dependency_lock_sha256": repository_lock_sha256(GEARS_LOCK_PATH),
        "role_contract": {
            "calibration_pair_ids": [["GENE_A", "GENE_B"]],
        },
    }
    monkeypatch.setattr(probe_cli, "verify_probe_input", lambda **_kwargs: manifest)
    monkeypatch.setattr(probe_cli, "_read_verified_probe_h5ad", lambda *_args, **_kwargs: prepared)
    monkeypatch.setattr(probe_cli, "read_payload", lambda *_args, **_kwargs: payload)
    monkeypatch.setattr(probe_cli, "canonical_payload_sha256", lambda _payload: "1" * 64)
    monkeypatch.setattr(
        probe_cli,
        "_direct_control_predictions",
        lambda *, count, **_kwargs: ([-0.2, 1.0], [[-0.2, 1.0] for _ in range(count)]),
    )
    monkeypatch.setattr(
        probe_cli,
        "_load_gears_worker_module",
        lambda: (
            SimpleNamespace(
                _fit_and_predict=None,
                verify_probe_runtime_identity=lambda **_kwargs: "e" * 64,
            ),
            _GEARS_WORKER,
        ),
    )
    calls: list[dict] = []

    def fake_fit_runner(
        _payload,
        adata,
        _projection,
        _genes,
        _representation,
        *,
        checkpoint_path,
        fitted_model_observer,
        observer_only,
        probe_context,
        input_scale,
        **_kwargs,
    ):
        assert observer_only is True
        assert input_scale == PROBE_INPUT_TRANSFORM
        assert probe_context["registration_sha256"] == registration_sha
        Path(checkpoint_path).write_bytes(
            _checkpoint_bytes(
                required_strings={
                    PROBE_INPUT_TRANSFORM,
                    probe_context["input_scale_sha256"],
                    probe_context["gears_dependency_lock_sha256"],
                    probe_context["gears_installed_packages_sha256"],
                    manifest["output_h5ad_sha256"],
                    manifest["fit_artifact_content_sha256"],
                    registration_sha,
                    sha256_json(["GENE_A", "GENE_B"]),
                    sha256_file(_GEARS_WORKER),
                }
            )
        )
        calls.append({"checkpoint_path": checkpoint_path})
        processed = adata.copy()
        processed.obs_names = processed.obs["source_row_id"].astype(str).tolist()
        fitted_model_observer(
            model=object(),
            pert_data=SimpleNamespace(adata=processed),
            torch_module=object(),
        )
        return {}

    digest = probe_cli.run_probe_a_measurements(
        payload_dir=tmp_path / "payload",
        registration_path=evidence / REGISTRATION_PATH,
        registration_sha256=registration_sha,
        expected_git_commit=COMMIT,
        probe_manifest_path=probe_manifest_path,
        probe_manifest_sha256=sha256_file(probe_manifest_path),
        h5ad_path=h5ad_path,
        roster_path=tmp_path / "roster.json",
        roster_receipt_path=tmp_path / "receipt.json",
        approved_root=approved,
        evidence_root=evidence,
        out_raw=evidence / "raw.json",
        checkpoint_dir=evidence / "checkpoints",
        fit_runner=fake_fit_runner,
    )
    published = json.loads((evidence / "raw.json").read_text(encoding="utf-8"))
    assert digest == sha256_file(evidence / "raw.json")
    assert len(calls) == 2
    assert [run["run_index"] for run in published["determinism_runs"]] == [1, 2]
    assert published["public_prediction"] == published["determinism_runs"][0]["prediction"]


def test_probe_a_runner_rejects_registration_pin_before_input_or_fit(tmp_path, monkeypatch):
    probe_cli = _load_probe_cli()
    monkeypatch.setattr(probe_cli, "assert_clean_approved_checkout", lambda _commit: None)
    evidence = tmp_path / "evidence"
    approved = tmp_path / "approved"
    evidence.mkdir()
    approved.mkdir()
    _registration(evidence)
    monkeypatch.setattr(
        probe_cli,
        "verify_probe_input",
        lambda **_kwargs: pytest.fail("input verification must follow registration admission"),
    )
    with pytest.raises(probe_cli.GeneUniverseError, match="external pin"):
        probe_cli.run_probe_a_measurements(
            payload_dir=tmp_path / "payload",
            registration_path=evidence / REGISTRATION_PATH,
            registration_sha256="0" * 64,
            expected_git_commit=COMMIT,
            probe_manifest_path=evidence / "probe_input_manifest.json",
            probe_manifest_sha256="1" * 64,
            h5ad_path=evidence / "probe_input.h5ad",
            roster_path=tmp_path / "roster.json",
            roster_receipt_path=tmp_path / "receipt.json",
            approved_root=approved,
            evidence_root=evidence,
            out_raw=evidence / "raw.json",
            checkpoint_dir=evidence / "checkpoints",
        )


def test_probe_a_runner_rejects_prepared_target_different_from_registration(tmp_path, monkeypatch):
    probe_cli = _load_probe_cli()
    monkeypatch.setattr(probe_cli, "assert_clean_approved_checkout", lambda _commit: None)
    evidence = tmp_path / "evidence"
    approved = tmp_path / "approved"
    evidence.mkdir()
    approved.mkdir()
    _, registration_sha = _registration(evidence)
    probe_manifest_path = evidence / "probe_input_manifest.json"
    h5ad_path = evidence / "probe_input.h5ad"
    probe_manifest_path.write_text("fixture\n", encoding="utf-8")
    h5ad_path.write_bytes(b"fixture")
    monkeypatch.setattr(
        probe_cli,
        "verify_probe_input",
        lambda **_kwargs: {
            "expression_scale": PROBE_INPUT_TRANSFORM,
            "normalization_target": 9999.0,
        },
    )
    monkeypatch.setattr(
        probe_cli,
        "_read_verified_probe_h5ad",
        lambda *_args, **_kwargs: pytest.fail("fit input must not load after target mismatch"),
    )
    with pytest.raises(probe_cli.GeneUniverseError, match="differs from.*registration"):
        probe_cli.run_probe_a_measurements(
            payload_dir=tmp_path / "payload",
            registration_path=evidence / REGISTRATION_PATH,
            registration_sha256=registration_sha,
            expected_git_commit=COMMIT,
            probe_manifest_path=probe_manifest_path,
            probe_manifest_sha256=sha256_file(probe_manifest_path),
            h5ad_path=h5ad_path,
            roster_path=tmp_path / "roster.json",
            roster_receipt_path=tmp_path / "receipt.json",
            approved_root=approved,
            evidence_root=evidence,
            out_raw=evidence / "raw.json",
            checkpoint_dir=evidence / "checkpoints",
        )


@pytest.mark.parametrize(("field", "value"), [("median", None), ("maximum", float("inf"))])
def test_output_scale_bad_values_fail_cleanly(tmp_path, field, value):
    registration, registration_sha = _registration(tmp_path)
    report = _report(tmp_path, registration_sha256=registration_sha)
    report["output_scale"][field] = value
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match=f"output_scale.{field}"):
        _validate_report(tmp_path, report, registration, registration_sha)


def test_admission_round_trips_through_real_consumer_and_rejects_v1_shape(tmp_path):
    registration, _, _, registration_sha, report_sha, manifest_sha = _complete_evidence(tmp_path)
    outputs = build_evidence_outputs(
        report_bytes=(tmp_path / REPORT_PATH).read_bytes(),
        report_sha256=report_sha,
        registration_bytes=(tmp_path / REGISTRATION_PATH).read_bytes(),
        registration_sha256=registration_sha,
        manifest_bytes=(tmp_path / MANIFEST_PATH).read_bytes(),
        evidence_root=tmp_path,
        evidence_manifest_sha256=manifest_sha,
        expected_git_commit=COMMIT,
        verifier_code_sha256=VERIFIER_SHA,
    )
    admission = outputs.admission
    validate_probe_a_evidence(
        admission,
        registration=registration,
        registration_sha256=registration_sha,
        verification=outputs.verification,
        verification_sha256=outputs.verification_sha256,
        expected_git_commit=COMMIT,
    )
    path = tmp_path / "admission.json"
    _write_json(path, admission)
    verification_path = tmp_path / VERIFY_PATH
    verification_path.write_bytes(outputs.verification_bytes)
    load_probe_a_evidence(
        path,
        registration_path=tmp_path / REGISTRATION_PATH,
        verification_path=verification_path,
        expected_git_commit=COMMIT,
        expected_registration_sha256=registration_sha,
        expected_verification_sha256=outputs.verification_sha256,
    )

    legacy = dict(admission)
    legacy["schema"] = "compose_gears_probe_a_admission_v1"
    legacy.pop("registration_sha256")
    _resign(legacy)
    with pytest.raises(ProbeAEvidenceError, match="key roster mismatch"):
        validate_admission(
            legacy,
            registration=registration,
            registration_sha256=registration_sha,
            verification=outputs.verification,
            verification_sha256=outputs.verification_sha256,
            expected_git_commit=COMMIT,
        )


def test_manifest_accepts_only_a_complete_role_typed_inventory(tmp_path):
    _, _, manifest, _, _, _ = _complete_evidence(tmp_path)
    validate_evidence_manifest(manifest, evidence_root=tmp_path, expected_git_commit=COMMIT)
    validate_evidence_semantics(
        manifest,
        evidence_root=tmp_path,
        expected_git_commit=COMMIT,
        registration_sha256=sha256_file(tmp_path / REGISTRATION_PATH),
    )


@pytest.mark.parametrize(
    ("path", "payload", "message"),
    [
        ("runtime.json", {"runtime": "pinned"}, "runtime evidence.*keys"),
        ("inputs.json", {"inputs": "pinned"}, "input evidence.*keys"),
        ("role_attestation.json", {"overlap_count": 0}, "role attestation.*keys"),
    ],
)
def test_semantic_validator_rejects_placeholder_evidence(tmp_path, path, payload, message):
    _, _, manifest, registration_sha, _, _ = _complete_evidence(tmp_path)
    _write_json(tmp_path / path, payload)
    _refresh_manifest_entry(manifest, tmp_path, path)
    with pytest.raises(ProbeAEvidenceError, match=message):
        validate_evidence_semantics(
            manifest,
            evidence_root=tmp_path,
            expected_git_commit=COMMIT,
            registration_sha256=registration_sha,
        )


def test_semantic_validator_rejects_placeholder_commands_and_receipt(tmp_path):
    _, _, manifest, registration_sha, _, _ = _complete_evidence(tmp_path)
    (tmp_path / "commands.jsonl").write_text('{"exit_code":0}\n', encoding="utf-8")
    _refresh_manifest_entry(manifest, tmp_path, "commands.jsonl")
    with pytest.raises(ProbeAEvidenceError, match="commands record 0.*keys"):
        validate_evidence_semantics(
            manifest,
            evidence_root=tmp_path,
            expected_git_commit=COMMIT,
            registration_sha256=registration_sha,
        )

    _, _, manifest, registration_sha, _, _ = _complete_evidence(tmp_path)
    _write_pretty_json(tmp_path / "roster_receipts/receipt.json", {"status": "complete"})
    _refresh_manifest_entry(manifest, tmp_path, "roster_receipts/receipt.json")
    with pytest.raises(ProbeAEvidenceError, match="roster receipt.*keys"):
        validate_evidence_semantics(
            manifest,
            evidence_root=tmp_path,
            expected_git_commit=COMMIT,
            registration_sha256=registration_sha,
        )


def test_semantic_validator_rejects_command_labels_wrapped_around_unrelated_argv(tmp_path):
    _, _, manifest, registration_sha, _, _ = _complete_evidence(tmp_path)
    commands_path = tmp_path / "commands.jsonl"
    records = [json.loads(line) for line in commands_path.read_text(encoding="utf-8").splitlines()]
    records[0]["argv"] = ["true", records[0]["command"]]
    _resign(records[0])
    commands_path.write_text(
        "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records)
        + "\n",
        encoding="utf-8",
    )
    _refresh_manifest_entry(manifest, tmp_path, "commands.jsonl")
    with pytest.raises(ProbeAEvidenceError, match="maintained GEARS probe CLI"):
        validate_evidence_semantics(
            manifest,
            evidence_root=tmp_path,
            expected_git_commit=COMMIT,
            registration_sha256=registration_sha,
        )


def test_semantic_validator_allows_repeated_real_candidate_commands(tmp_path):
    _, _, manifest, registration_sha, _, _ = _complete_evidence(tmp_path)
    commands_path = tmp_path / "commands.jsonl"
    records = [json.loads(line) for line in commands_path.read_text(encoding="utf-8").splitlines()]
    repeated = dict(records[0])
    repeated["started_at_utc"] = "2026-07-17T00:01:00+00:00"
    repeated["ended_at_utc"] = "2026-07-17T00:01:01+00:00"
    repeated["primary_file_sha256"] = "e" * 64
    _resign(repeated)
    records.append(repeated)
    commands_path.write_text(
        "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records)
        + "\n",
        encoding="utf-8",
    )
    _refresh_manifest_entry(manifest, tmp_path, "commands.jsonl")
    validate_evidence_semantics(
        manifest,
        evidence_root=tmp_path,
        expected_git_commit=COMMIT,
        registration_sha256=registration_sha,
    )


def test_semantic_validator_binds_probe_a_command_to_raw_artifact(tmp_path):
    _, _, manifest, registration_sha, _, _ = _complete_evidence(tmp_path)
    commands_path = tmp_path / "commands.jsonl"
    records = [json.loads(line) for line in commands_path.read_text(encoding="utf-8").splitlines()]
    probe_a = next(record for record in records if record["command"] == "probe-a")
    probe_a["primary_file_sha256"] = "0" * 64
    _resign(probe_a)
    commands_path.write_text(
        "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records)
        + "\n",
        encoding="utf-8",
    )
    _refresh_manifest_entry(manifest, tmp_path, "commands.jsonl")
    with pytest.raises(ProbeAEvidenceError, match="not bound to the raw artifact"):
        validate_evidence_semantics(
            manifest,
            evidence_root=tmp_path,
            expected_git_commit=COMMIT,
            registration_sha256=registration_sha,
        )


def test_semantic_validator_binds_report_command_to_its_inputs_and_output(tmp_path):
    _, _, manifest, registration_sha, _, _ = _complete_evidence(tmp_path)
    commands_path = tmp_path / "commands.jsonl"
    records = [json.loads(line) for line in commands_path.read_text(encoding="utf-8").splitlines()]
    report = next(record for record in records if record["command"] == "build-probe-a-report")
    report["argv"][report["argv"].index("--raw-sample-sha256") + 1] = "0" * 64
    _resign(report)
    commands_path.write_text(
        "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records)
        + "\n",
        encoding="utf-8",
    )
    _refresh_manifest_entry(manifest, tmp_path, "commands.jsonl")
    with pytest.raises(ProbeAEvidenceError, match="report command is not bound"):
        validate_evidence_semantics(
            manifest,
            evidence_root=tmp_path,
            expected_git_commit=COMMIT,
            registration_sha256=registration_sha,
        )


def test_semantic_validator_requires_exact_raw_checkpoint_roster(tmp_path):
    _, _, manifest, registration_sha, _, _ = _complete_evidence(tmp_path)
    manifest["files"] = [
        entry
        for entry in manifest["files"]
        if not (entry["role"] == "probe_a_checkpoint" and entry["path"] == "checkpoints/run_2.pt")
    ]
    with pytest.raises(ProbeAEvidenceError, match="exactly the two manifested checkpoint"):
        validate_evidence_semantics(
            manifest,
            evidence_root=tmp_path,
            expected_git_commit=COMMIT,
            registration_sha256=registration_sha,
        )


def test_semantic_validator_binds_control_rows_to_prepared_h5ad(tmp_path):
    _, _, manifest, registration_sha, _, _ = _complete_evidence(tmp_path)
    raw_path = tmp_path / "raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    forged_ids = list(raw["ordered_control_row_ids"])
    forged_ids[0] = "forged-control-row"
    raw["ordered_control_row_ids"] = forged_ids
    raw["producer"]["ordered_control_row_identity_sha256"] = sha256_json(forged_ids)
    for control in raw["control_predictions"]:
        control["control_row_ids"] = forged_ids[: control["count"]]
    _resign(raw)
    _write_json(raw_path, raw)

    inputs_path = tmp_path / "inputs.json"
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    inputs["ordered_control_row_identity_sha256"] = sha256_json(forged_ids)
    _resign(inputs)
    _write_json(inputs_path, inputs)

    commands_path = tmp_path / "commands.jsonl"
    records = [json.loads(line) for line in commands_path.read_text(encoding="utf-8").splitlines()]
    probe_record = next(record for record in records if record["command"] == "probe-a")
    probe_record["primary_file_sha256"] = sha256_file(raw_path)
    _resign(probe_record)
    report_path = tmp_path / REPORT_PATH
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["raw_samples"][0]["sha256"] = sha256_file(raw_path)
    _resign(report)
    _write_json(report_path, report)
    report_record = next(
        record for record in records if record["command"] == "build-probe-a-report"
    )
    report_record["argv"][report_record["argv"].index("--raw-sample-sha256") + 1] = sha256_file(
        raw_path
    )
    report_record["primary_file_sha256"] = sha256_file(report_path)
    _resign(report_record)
    commands_path.write_text(
        "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records)
        + "\n",
        encoding="utf-8",
    )
    for relative in ("raw.json", "inputs.json", REPORT_PATH, "commands.jsonl"):
        _refresh_manifest_entry(manifest, tmp_path, relative)

    with pytest.raises(ProbeAEvidenceError, match="raw control-row order"):
        validate_evidence_semantics(
            manifest,
            evidence_root=tmp_path,
            expected_git_commit=COMMIT,
            registration_sha256=registration_sha,
        )


def test_manifest_rejects_missing_required_role_and_unmanifested_extra_file(tmp_path):
    _, _, manifest, _, _, _ = _complete_evidence(tmp_path)
    manifest["files"] = [item for item in manifest["files"] if item["role"] != "commands"]
    _resign(manifest, "manifest_checksum")
    with pytest.raises(ProbeAEvidenceError, match="exactly one commands"):
        validate_evidence_manifest(manifest, evidence_root=tmp_path, expected_git_commit=COMMIT)

    _, _, manifest, _, _, _ = _complete_evidence(tmp_path)
    (tmp_path / "rogue.txt").write_text("unregistered\n", encoding="utf-8")
    with pytest.raises(ProbeAEvidenceError, match="not exhaustive.*rogue.txt"):
        validate_evidence_manifest(manifest, evidence_root=tmp_path, expected_git_commit=COMMIT)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda m: m.update(schema="wrong"), "identity mismatch"),
        (lambda m: m["files"][0].update(bytes=m["files"][0]["bytes"] + 1), "byte count"),
        (lambda m: m["files"].append(dict(m["files"][0])), "path is duplicated"),
        (lambda m: m["files"][0].update(role="unknown"), "role is unknown"),
    ],
)
def test_manifest_fails_closed_on_schema_and_roster_mutations(tmp_path, mutate, message):
    _, _, manifest, _, _, _ = _complete_evidence(tmp_path)
    mutate(manifest)
    _resign(manifest, "manifest_checksum")
    with pytest.raises(ProbeAEvidenceError, match=message):
        validate_evidence_manifest(manifest, evidence_root=tmp_path, expected_git_commit=COMMIT)


def test_manifest_rejects_symlink_anywhere_in_tree(tmp_path):
    _, _, manifest, _, _, _ = _complete_evidence(tmp_path)
    (tmp_path / "link.log").symlink_to(tmp_path / "logs/run.log")
    with pytest.raises(ProbeAEvidenceError, match="symlink"):
        validate_evidence_manifest(manifest, evidence_root=tmp_path, expected_git_commit=COMMIT)


def test_binding_covers_report_registration_identities_and_exact_raw_roster(tmp_path):
    _, report, manifest, registration_sha, report_sha, _ = _complete_evidence(tmp_path)
    assert_report_manifest_binding(
        report,
        manifest,
        report_sha256=report_sha,
        registration_sha256=registration_sha,
    )

    report["runtime_sha256"] = "0" * 64
    with pytest.raises(ProbeAEvidenceError, match="runtime SHA-256 disagrees"):
        assert_report_manifest_binding(
            report,
            manifest,
            report_sha256=report_sha,
            registration_sha256=registration_sha,
        )

    report["runtime_sha256"] = sha256_file(tmp_path / "runtime.json")
    report["raw_samples"] = []
    with pytest.raises(ProbeAEvidenceError, match="raw-sample rosters differ"):
        assert_report_manifest_binding(
            report,
            manifest,
            report_sha256=report_sha,
            registration_sha256=registration_sha,
        )


def _cli_argv(root: Path, *, negative: bool = False) -> tuple[list[str], Path]:
    evidence_builder = _negative_evidence if negative else _complete_evidence
    _, _, _, registration_sha, report_sha, manifest_sha = evidence_builder(root)
    verifier_code_sha = _load_verifier()._verifier_code_sha256()
    out = root / ADMISSION_PATH
    return (
        [
            "--evidence-root",
            str(root),
            "--report",
            str(root / REPORT_PATH),
            "--report-sha256",
            report_sha,
            "--registration",
            str(root / REGISTRATION_PATH),
            "--registration-sha256",
            registration_sha,
            "--manifest",
            str(root / MANIFEST_PATH),
            "--manifest-sha256",
            manifest_sha,
            "--git-commit",
            COMMIT,
            "--expected-verifier-code-sha256",
            verifier_code_sha,
            "--out-admission",
            str(out),
        ],
        out,
    )


def test_cli_publishes_a_registration_and_manifest_bound_admission(tmp_path):
    argv, out = _cli_argv(tmp_path)
    verify = _load_verifier()
    assert verify.main(argv) == 0
    admission = json.loads(out.read_text(encoding="utf-8"))
    registration = json.loads((tmp_path / REGISTRATION_PATH).read_text(encoding="utf-8"))
    verification_path = tmp_path / VERIFY_PATH
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    validate_probe_a_evidence(
        admission,
        registration=registration,
        registration_sha256=argv[argv.index("--registration-sha256") + 1],
        verification=verification,
        verification_sha256=sha256_file(verification_path),
        expected_git_commit=COMMIT,
    )
    assert admission["registration_sha256"] == argv[argv.index("--registration-sha256") + 1]
    assert admission["evidence_manifest_sha256"] == argv[argv.index("--manifest-sha256") + 1]
    assert admission["verification_sha256"] == sha256_file(verification_path)
    assert verification["verifier_code_sha256"] == verify._verifier_code_sha256()


def test_cli_publishes_negative_receipt_without_admission(tmp_path, capsys):
    argv, out = _cli_argv(tmp_path, negative=True)
    verify = _load_verifier()
    assert verify.main(argv) == 0
    assert not out.exists()
    verification_path = tmp_path / VERIFY_PATH
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    assert verification["schema"] == NEGATIVE_VERIFICATION_SCHEMA
    assert verification["status"] == "failed"
    published = json.loads(capsys.readouterr().out)
    assert published == {
        "admission_sha256": None,
        "schema": NEGATIVE_VERIFICATION_SCHEMA,
        "status": "NEGATIVE_RESULT",
        "verification_sha256": sha256_file(verification_path),
    }


def test_cli_rejects_unreviewed_verifier_code_before_publishing(tmp_path):
    argv, out = _cli_argv(tmp_path)
    argv[argv.index("--expected-verifier-code-sha256") + 1] = "0" * 64
    verify = _load_verifier()
    with pytest.raises(ProbeAEvidenceError, match="independently reviewed pre-run pin"):
        verify.main(argv)
    assert not out.exists()
    assert not (tmp_path / VERIFY_PATH).exists()


def test_mapping_level_validator_hashes_mappings_against_external_pins(tmp_path):
    registration, _, _, registration_sha, report_sha, manifest_sha = _complete_evidence(tmp_path)
    outputs = build_evidence_outputs(
        report_bytes=(tmp_path / REPORT_PATH).read_bytes(),
        report_sha256=report_sha,
        registration_bytes=(tmp_path / REGISTRATION_PATH).read_bytes(),
        registration_sha256=registration_sha,
        manifest_bytes=(tmp_path / MANIFEST_PATH).read_bytes(),
        evidence_root=tmp_path,
        evidence_manifest_sha256=manifest_sha,
        expected_git_commit=COMMIT,
        verifier_code_sha256=VERIFIER_SHA,
    )
    forged_registration = json.loads(json.dumps(registration))
    forged_registration["output_bridge"]["max_abs_error_tolerance"] = 1e6
    _resign(forged_registration)
    with pytest.raises(ProbeAEvidenceError, match="registration mapping bytes.*external pin"):
        validate_admission(
            outputs.admission,
            registration=forged_registration,
            registration_sha256=registration_sha,
            verification=outputs.verification,
            verification_sha256=outputs.verification_sha256,
            expected_git_commit=COMMIT,
        )

    forged_verification = json.loads(json.dumps(outputs.verification))
    forged_verification["output_bridge"]["tolerance"] = 1e6
    _resign(forged_verification)
    with pytest.raises(ProbeAEvidenceError, match="verification mapping bytes.*external pin"):
        validate_admission(
            outputs.admission,
            registration=registration,
            registration_sha256=registration_sha,
            verification=forged_verification,
            verification_sha256=outputs.verification_sha256,
            expected_git_commit=COMMIT,
        )


@pytest.mark.parametrize("existing_path", [VERIFY_PATH, ADMISSION_PATH])
def test_cli_rejects_preexisting_post_manifest_output_without_overwrite(tmp_path, existing_path):
    argv, _ = _cli_argv(tmp_path)
    path = tmp_path / existing_path
    sentinel = "preexisting-attempt\n"
    path.write_text(sentinel, encoding="utf-8")
    verify = _load_verifier()
    with pytest.raises(ProbeAEvidenceError, match="already contains"):
        verify.main(argv)
    assert path.read_text(encoding="utf-8") == sentinel


def test_cli_rejects_posthoc_tolerance_even_if_report_and_manifest_are_resigned(tmp_path):
    argv, out = _cli_argv(tmp_path)
    report_path = tmp_path / REPORT_PATH
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["output_bridge"]["tolerance"] = 1e6
    _resign(report)
    _write_json(report_path, report)
    report_sha = sha256_file(report_path)
    argv[argv.index("--report-sha256") + 1] = report_sha

    manifest_path = tmp_path / MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report_entry = next(item for item in manifest["files"] if item["role"] == "probe_a_report")
    report_entry.update(sha256=report_sha, bytes=report_path.stat().st_size)
    _resign(manifest, "manifest_checksum")
    _write_json(manifest_path, manifest)
    argv[argv.index("--manifest-sha256") + 1] = sha256_file(manifest_path)

    verify = _load_verifier()
    with pytest.raises(ProbeAEvidenceError, match="differs from preregistration"):
        verify.main(argv)
    assert not out.exists()
    assert not (tmp_path / VERIFY_PATH).exists()


def test_cli_rejects_noncanonical_paths_digest_mismatch_and_extra_file(tmp_path):
    argv, out = _cli_argv(tmp_path)
    argv[argv.index("--report-sha256") + 1] = "0" * 64
    verify = _load_verifier()
    with pytest.raises(ProbeAEvidenceError, match="SHA-256 mismatch"):
        verify.main(argv)
    assert not out.exists()

    argv, out = _cli_argv(tmp_path)
    outside = tmp_path / "report-copy.json"
    outside.write_bytes((tmp_path / REPORT_PATH).read_bytes())
    argv[argv.index("--report") + 1] = str(outside)
    with pytest.raises(ProbeAEvidenceError, match=f"must be {REPORT_PATH}"):
        verify.main(argv)
    assert not out.exists()

    outside.unlink()
    argv, out = _cli_argv(tmp_path)
    (tmp_path / "extra.bin").write_bytes(b"not manifested")
    with pytest.raises(ProbeAEvidenceError, match="not exhaustive"):
        verify.main(argv)
    assert not out.exists()
