"""Tests for the admission-grade GEARS Probe-A evidence contract."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from alive.compose.approximation_bias import load_probe_a_evidence, validate_probe_a_evidence
from alive.compose.gears_probe_a import (
    ADMISSION_PATH,
    ADMISSION_SCHEMA,
    COMMAND_RECORD_SCHEMA,
    INPUTS_SCHEMA,
    MANIFEST_PATH,
    MANIFEST_SCHEMA,
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
    assert_report_manifest_binding,
    build_evidence_outputs,
    validate_admission,
    validate_evidence_manifest,
    validate_evidence_semantics,
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


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_gears_probe_a", _VERIFY)
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_gears_probe_a"] = module
    spec.loader.exec_module(module)
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


def _registration(root: Path) -> tuple[dict, str]:
    body = {
        "schema": REGISTRATION_SCHEMA,
        "protocol": PROTOCOL,
        "git_commit": COMMIT,
        "input_scale": {
            "normalization_target": 10000.0,
            "transform": "full_library_normalize_log1p_then_roster_subset",
        },
        "determinism": {"max_abs_error_tolerance": 1e-7},
        "control_count": {
            "counts": [1, 8, 300, 301, 400],
            "first_300_max_abs_error_tolerance": 1e-7,
        },
        "output_bridge": {
            "representation": "raw_pseudobulk_approximation",
            "max_abs_error_tolerance": 1e-7,
        },
    }
    registration = {**body, "self_checksum": sha256_json(body)}
    path = root / REGISTRATION_PATH
    _write_json(path, registration)
    return registration, sha256_file(path)


def _report(root: Path, *, registration_sha256: str) -> dict:
    raw = root / "raw.json"
    checkpoint_paths = ["checkpoints/run_1.pt", "checkpoints/run_2.pt"]
    for checkpoint_path in checkpoint_paths:
        path = root / checkpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"identical trained model state\n")
    ordered_control_row_ids = [f"control-row-{index:04d}" for index in range(400)]
    raw_body = {
        "schema": RAW_SCHEMA,
        "input_before": [[1.0, 2.0], [3.0, 4.0]],
        "input_after": [[1.0, 2.0], [3.0, 4.0]],
        "determinism_runs": [
            {
                "checkpoint_path": checkpoint_paths[index],
                "checkpoint_sha256": sha256_file(root / checkpoint_paths[index]),
                "prediction": [0.1, -0.2, 2.0],
            }
            for index in range(2)
        ],
        "ordered_control_row_ids": ordered_control_row_ids,
        "control_predictions": [
            {
                "count": count,
                "control_row_ids": ordered_control_row_ids[:count],
                "per_control_prediction": [[0.2, 0.3] for _ in range(count)],
                "public_prediction": [0.2, 0.3],
            }
            for count in (1, 8, 300, 301, 400)
        ],
        "public_prediction": [-0.2, 1.0, 2.0],
        "bridge_prediction": [-0.2, 1.0, 2.0],
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
            "tolerance": 1e-7,
            "verdict": "pass",
        },
        "control_count": {
            "counts": [1, 8, 300, 301, 400],
            "prediction_sha256": [
                sha256_json(item["public_prediction"]) for item in raw_body["control_predictions"]
            ],
            "first_300_max_abs_error": 0.0,
            "tolerance": 1e-7,
            "verdict": "pass",
        },
        "output_scale": {
            "minimum": -0.2,
            "median": 1.0,
            "maximum": 2.0,
            "negative_fraction": 1 / 3,
            "near_integer_fraction": 2 / 3,
        },
        "output_bridge": {
            "representation": "raw_pseudobulk_approximation",
            "verdict": "pass",
            "tolerance": 1e-7,
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
        "dependency_lock_sha256": "6" * 64,
        "runtime_fingerprint_sha256": "8" * 64,
        "network_disabled": True,
    }
    _write_json(
        root / "runtime.json",
        {**runtime_body, "self_checksum": sha256_json(runtime_body)},
    )

    receipt_body = {
        "alias_artifact_sha256": "1" * 64,
        "candidate_artifact_sha256": "2" * 64,
        "driver_code_sha256": "3" * 64,
        "dependency_lock_sha256": "6" * 64,
        "fit_artifact_content_sha256": "4" * 64,
        "gene2go_nodes_artifact_sha256": "5" * 64,
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

    fit_role_counts = {"control": 8, "singles": 16, "combo_calibration": 8}
    inputs_body = {
        "schema": INPUTS_SCHEMA,
        "protocol": PROTOCOL,
        "git_commit": COMMIT,
        "source_sha256": "1" * 64,
        "gene2go_manifest_sha256": "2" * 64,
        "pair_manifest_sha256": "3" * 64,
        "alias_artifact_sha256": "4" * 64,
        "fit_role_artifact_sha256": "5" * 64,
        "response_artifact_sha256": "6" * 64,
        "roster_receipt_sha256": sha256_file(receipt_path),
        "roster_sha256": receipt["roster_file_sha256"],
        "dependency_lock_sha256": runtime_body["dependency_lock_sha256"],
        "fit_role_counts": fit_role_counts,
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
        "reader_spy": {"status": "pass", "observed_row_indices_sha256": "d" * 64},
    }
    _write_json(
        root / "role_attestation.json",
        {**role_body, "self_checksum": sha256_json(role_body)},
    )
    (root / "probe_a_source.txt").write_text("pinned source closure\n", encoding="utf-8")
    (root / "logs/run.log").parent.mkdir(parents=True, exist_ok=True)
    (root / "logs/run.log").write_text("complete\n", encoding="utf-8")

    report = _report(root, registration_sha256=registration_sha)

    command_lines: list[str] = []
    for index, command in enumerate(("build-roster", "prepare-input", "verify-input", "probe-a")):
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
                sha256_file(root / "raw.json") if command == "probe-a" else str(index + 1) * 64
            ),
            "runtime_fingerprint_sha256": runtime_body["runtime_fingerprint_sha256"],
        }
        if command == "probe-a":
            command_body["argv"].extend(
                [
                    "--measurement-json",
                    "/workspace/probe_a_measurement.json",
                    "--evidence-root",
                    "/workspace/evidence",
                    "--out-raw",
                    "/workspace/evidence/raw.json",
                ]
            )
        command = {**command_body, "self_checksum": sha256_json(command_body)}
        command_lines.append(json.dumps(command, sort_keys=True, separators=(",", ":")))
    (root / "commands.jsonl").write_text("\n".join(command_lines) + "\n", encoding="utf-8")

    report["runtime_sha256"] = sha256_file(root / "runtime.json")
    report["input_manifest_sha256"] = sha256_file(root / "inputs.json")
    report["source_fingerprint_sha256"] = sha256_file(root / "probe_a_source.txt")
    _resign(report)
    _write_json(root / REPORT_PATH, report)

    role_paths = [
        ("commands", "commands.jsonl"),
        ("runtime", "runtime.json"),
        ("inputs", "inputs.json"),
        ("role_attestation", "role_attestation.json"),
        ("probe_a_registration", REGISTRATION_PATH),
        ("probe_a_report", REPORT_PATH),
        ("probe_a_source", "probe_a_source.txt"),
        ("roster_receipt", "roster_receipts/receipt.json"),
        ("probe_a_checkpoint", "checkpoints/run_1.pt"),
        ("probe_a_checkpoint", "checkpoints/run_2.pt"),
        ("raw_sample", "raw.json"),
        ("log", "logs/run.log"),
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


def _validate_report(root: Path, report: dict, registration: dict, registration_sha: str) -> None:
    validate_probe_a_report(
        report,
        registration=registration,
        registration_sha256=registration_sha,
        evidence_root=root,
        expected_git_commit=COMMIT,
    )


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
    _resign(raw)
    _write_json(raw_path, raw)
    report["raw_samples"][0]["sha256"] = sha256_file(raw_path)
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


def test_maintained_probe_a_command_owns_raw_schema_and_publication(tmp_path):
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    _report(evidence_root, registration_sha256=SHA)
    raw_path = evidence_root / "raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    measurement = {
        key: value for key, value in raw.items() if key not in {"schema", "self_checksum"}
    }
    measurement_path = tmp_path / "measurement_hook.json"
    _write_json(measurement_path, measurement)
    raw_path.unlink()

    probe = _load_probe_cli()
    digest = probe.publish_probe_a_measurements(
        measurement_json=measurement_path,
        evidence_root=evidence_root,
        out_raw=raw_path,
    )
    published = json.loads(raw_path.read_text(encoding="utf-8"))
    assert digest == sha256_file(raw_path)
    assert published["schema"] == RAW_SCHEMA
    with pytest.raises(FileExistsError):
        probe.publish_probe_a_measurements(
            measurement_json=measurement_path,
            evidence_root=evidence_root,
            out_raw=raw_path,
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


def _cli_argv(root: Path) -> tuple[list[str], Path]:
    _, _, _, registration_sha, report_sha, manifest_sha = _complete_evidence(root)
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
