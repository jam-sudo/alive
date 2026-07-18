"""Fail-closed evidence contract for the COMPOSE GEARS Probe A.

The actual GEARS fit runs only in the pinned pod environment. This module is
dependency-light so the resulting evidence can be verified independently on a
CPU host before it is allowed to admit the approximation-bias measurement.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from alive.compose.approximation_bias import (
    PROBE_A_REGISTRATION_SCHEMA,
    PROBE_A_SCHEMA,
    PROBE_A_VERIFICATION_SCHEMA,
    ApproximationBiasValidationError,
    canonical_file_bytes,
    canonical_json,
    self_checksum,
    validate_probe_a_evidence,
    validate_probe_a_registration,
)
from alive.provenance import sha256_bytes, sha256_file, sha256_json

REPORT_SCHEMA = "compose_gears_probe_a_report_v4"
RAW_SCHEMA = "compose_gears_probe_a_raw_measurements_v2"
REGISTRATION_SCHEMA = PROBE_A_REGISTRATION_SCHEMA
VERIFICATION_SCHEMA = PROBE_A_VERIFICATION_SCHEMA
MANIFEST_SCHEMA = "compose_gears_probe_a_evidence_manifest_v4"
# The admission schema and its validation live exactly once, in the sole consumer
# gate ``approximation_bias.validate_probe_a_evidence``. Re-export the name and
# reuse that validator here so this producer cannot drift from the consumer.
ADMISSION_SCHEMA = PROBE_A_SCHEMA
PROTOCOL = "COMPOSE-K562-v1"

MANIFEST_PATH = "manifest.json"
REPORT_PATH = "probe_a.json"
REGISTRATION_PATH = "probe_a_registration.json"
ADMISSION_PATH = "probe_a_admission.json"
VERIFY_PATH = "verify.json"

_POST_MANIFEST_PATHS = frozenset({MANIFEST_PATH, ADMISSION_PATH, VERIFY_PATH})
_REPORT_KEYS = {
    "schema",
    "protocol",
    "status",
    "git_commit",
    "registration_sha256",
    "runtime_sha256",
    "input_manifest_sha256",
    "source_fingerprint_sha256",
    "input_scale",
    "determinism",
    "control_count",
    "output_scale",
    "output_bridge",
    "raw_samples",
    "self_checksum",
}
_REGISTRATION_KEYS = {
    "schema",
    "protocol",
    "git_commit",
    "input_scale",
    "determinism",
    "control_count",
    "output_bridge",
    "self_checksum",
}
_BRIDGE_KEYS = {"representation", "verdict", "tolerance", "max_abs_error"}
_MANIFEST_ENTRY_KEYS = {"role", "path", "sha256", "bytes"}
_SINGLETON_ROLE_PATHS = {
    "commands": "commands.jsonl",
    "runtime": "runtime.json",
    "inputs": "inputs.json",
    "role_attestation": "role_attestation.json",
    "probe_a_registration": REGISTRATION_PATH,
    "probe_a_report": REPORT_PATH,
    "probe_a_source": "probe_a_source.txt",
}
_MULTI_ROLES = frozenset({"roster_receipt", "probe_a_checkpoint", "raw_sample", "log"})
_KNOWN_ROLES = frozenset(_SINGLETON_ROLE_PATHS) | _MULTI_ROLES

COMMAND_RECORD_SCHEMA = "compose_gears_probe_command_record_v1"
RUNTIME_SCHEMA = "compose_gears_probe_runtime_v1"
INPUTS_SCHEMA = "compose_gears_probe_inputs_v1"
ROLE_ATTESTATION_SCHEMA = "compose_gears_probe_role_attestation_v1"
ROSTER_RECEIPT_SCHEMA = "compose_gears_roster_receipt_v1"

# These are the subcommands that the maintained CLI actually implements.  Probe-A
# measurement is admitted from its digest-bound raw artifact below; Probe B has a
# separate archive contract and must not gate Probe-A admission.
_REQUIRED_COMMANDS = frozenset({"build-roster", "prepare-input", "verify-input", "probe-a"})
_COMMAND_KEYS = {
    "schema",
    "command",
    "argv",
    "cwd",
    "env",
    "started_at_utc",
    "ended_at_utc",
    "exit_code",
    "primary_file_sha256",
    "runtime_fingerprint_sha256",
    "self_checksum",
}
_RUNTIME_KEYS = {
    "schema",
    "protocol",
    "git_commit",
    "pod_instance",
    "gpu_model",
    "gpu_uuid",
    "driver_version",
    "cuda_version",
    "cpu_model",
    "cpu_count",
    "ram_bytes",
    "image_digest",
    "python_version",
    "dependency_lock_sha256",
    "runtime_fingerprint_sha256",
    "network_disabled",
    "self_checksum",
}
_INPUTS_KEYS = {
    "schema",
    "protocol",
    "git_commit",
    "source_sha256",
    "gene2go_manifest_sha256",
    "pair_manifest_sha256",
    "alias_artifact_sha256",
    "fit_role_artifact_sha256",
    "response_artifact_sha256",
    "roster_receipt_sha256",
    "roster_sha256",
    "dependency_lock_sha256",
    "fit_role_counts",
    "self_checksum",
}
_ROLE_ATTESTATION_KEYS = {
    "schema",
    "protocol",
    "git_commit",
    "fit_role_counts",
    "sealed_pair_overlap_count",
    "sealed_row_read_count",
    "reader_spy",
    "self_checksum",
}
_ROSTER_RECEIPT_KEYS = {
    "alias_artifact_sha256",
    "candidate_artifact_sha256",
    "driver_code_sha256",
    "dependency_lock_sha256",
    "fit_artifact_content_sha256",
    "gene2go_nodes_artifact_sha256",
    "generator_code_sha256",
    "manifest_checksum",
    "n_target",
    "ordered_roster_sha256",
    "payload_sha256",
    "report_file_sha256",
    "response_artifact_sha256",
    "runtime_fingerprint_sha256",
    "roster_artifact_checksum",
    "roster_file_sha256",
    "schema",
}
_FIT_ROLE_COUNT_KEYS = {"control", "singles", "combo_calibration"}
_RAW_KEYS = {
    "schema",
    "input_before",
    "input_after",
    "determinism_runs",
    "ordered_control_row_ids",
    "control_predictions",
    "public_prediction",
    "bridge_prediction",
    "self_checksum",
}
_RAW_RUN_KEYS = {"checkpoint_path", "checkpoint_sha256", "prediction"}
_RAW_CONTROL_KEYS = {
    "count",
    "control_row_ids",
    "per_control_prediction",
    "public_prediction",
}
_CONTROL_COUNTS = (1, 8, 300, 301, 400)
_NEAR_INTEGER_ATOL = 1e-6


class ProbeAEvidenceError(ValueError):
    """Raised when Probe-A evidence cannot cross the promotion boundary."""


@dataclass(frozen=True)
class ProbeAAdmissionOutputs:
    """The receipt-first, admission-last outputs of one successful verification."""

    verification: dict
    verification_bytes: bytes
    verification_sha256: str
    admission: dict


def _sha(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ProbeAEvidenceError(f"{field} must be a lowercase SHA-256")
    return value


def _git_commit(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) not in {40, 64}
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ProbeAEvidenceError(f"{field} must be a full lowercase hexadecimal Git commit")
    return value


def _finite_nonnegative(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProbeAEvidenceError(f"{field} must be numeric")
    observed = float(value)
    if not math.isfinite(observed) or observed < 0:
        raise ProbeAEvidenceError(f"{field} must be finite and non-negative")
    return observed


def _finite(value: object, field: str) -> float:
    """Finite number of any sign (output-scale summary values may be negative)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProbeAEvidenceError(f"{field} must be numeric")
    observed = float(value)
    if not math.isfinite(observed):
        raise ProbeAEvidenceError(f"{field} must be finite")
    return observed


def _exact_keys(value: object, expected: set[str], field: str) -> Mapping:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ProbeAEvidenceError(f"{field} keys differ from the registered schema")
    return value


def _checksum(payload: Mapping, field: str) -> None:
    checksum = _sha(payload.get("self_checksum"), f"{field}.self_checksum")
    body = {key: value for key, value in payload.items() if key != "self_checksum"}
    if checksum != sha256_json(body):
        raise ProbeAEvidenceError(f"{field} self-checksum mismatch")


def _json_object_from_bytes(data: bytes, *, expected_sha256: str, label: str) -> dict:
    """Hash and parse one immutable byte snapshot; never authenticate a second read."""
    if not isinstance(data, bytes):
        raise ProbeAEvidenceError(f"{label} must be supplied as immutable bytes")
    expected = _sha(expected_sha256, f"{label} SHA-256")
    if sha256_bytes(data) != expected:
        raise ProbeAEvidenceError(f"{label} file SHA-256 mismatch")
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeAEvidenceError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProbeAEvidenceError(f"{label} must be a JSON object")
    try:
        canonical = canonical_file_bytes(value)
    except (TypeError, ValueError) as exc:
        raise ProbeAEvidenceError(f"{label} is not canonical finite JSON") from exc
    if data != canonical:
        raise ProbeAEvidenceError(f"{label} bytes are not canonical JSON with one trailing newline")
    return value


def _relative_file(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ProbeAEvidenceError("evidence path must be a non-empty string")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ProbeAEvidenceError("evidence path must be safe and relative")
    raw = root / rel
    if raw.is_symlink():
        raise ProbeAEvidenceError("evidence path must be a regular file, not a symlink")
    try:
        base = root.resolve(strict=True)
        candidate = raw.resolve(strict=True)
    except OSError as exc:
        raise ProbeAEvidenceError(f"evidence path is missing or unreadable: {relative}") from exc
    if not base.is_dir():
        raise ProbeAEvidenceError("evidence root must be a directory")
    if not candidate.is_relative_to(base) or not candidate.is_file():
        raise ProbeAEvidenceError("evidence path must be a regular file under evidence root")
    return candidate


def _manifest_inventory(root: Path) -> set[str]:
    """Return every regular evidence file except the three self/post outputs."""
    try:
        base = root.resolve(strict=True)
    except OSError as exc:
        raise ProbeAEvidenceError("evidence root is missing or unreadable") from exc
    if root.is_symlink() or not base.is_dir():
        raise ProbeAEvidenceError("evidence root must be a real directory, not a symlink")
    inventory: set[str] = set()
    try:
        descendants = sorted(base.rglob("*"))
    except OSError as exc:
        raise ProbeAEvidenceError("cannot enumerate the complete evidence tree") from exc
    for path in descendants:
        relative = path.relative_to(base).as_posix()
        if path.is_symlink():
            raise ProbeAEvidenceError(f"evidence tree contains symlink: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ProbeAEvidenceError(f"evidence tree contains a non-regular entry: {relative}")
        if relative not in _POST_MANIFEST_PATHS:
            inventory.add(relative)
    return inventory


def validate_registration(registration: Mapping, *, expected_git_commit: str) -> None:
    """Validate the owner-frozen decisions through the shared consumer contract."""
    try:
        validate_probe_a_registration(
            registration,
            expected_git_commit=expected_git_commit,
        )
    except ApproximationBiasValidationError as exc:
        raise ProbeAEvidenceError(str(exc)) from exc


def _finite_vector(value: object, field: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ProbeAEvidenceError(f"{field} must be a non-empty numeric vector")
    return [_finite(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _finite_matrix(value: object, field: str) -> list[list[float]]:
    if not isinstance(value, list) or not value:
        raise ProbeAEvidenceError(f"{field} must be a non-empty numeric matrix")
    rows = [_finite_vector(row, f"{field}[{index}]") for index, row in enumerate(value)]
    widths = {len(row) for row in rows}
    if len(widths) != 1:
        raise ProbeAEvidenceError(f"{field} must be rectangular")
    return rows


def _max_abs_error(left: list[float], right: list[float], field: str) -> float:
    if len(left) != len(right):
        raise ProbeAEvidenceError(f"{field} vectors must have identical lengths")
    return max(abs(a - b) for a, b in zip(left, right, strict=True))


def _ordered_row_ids(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ProbeAEvidenceError(f"{field} must be a non-empty ordered string list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ProbeAEvidenceError(f"{field} must contain only non-empty strings")
    if len(set(value)) != len(value):
        raise ProbeAEvidenceError(f"{field} must not contain duplicate row identities")
    return list(value)


def _column_mean(rows: list[list[float]], field: str) -> list[float]:
    if not rows:
        raise ProbeAEvidenceError(f"{field} cannot be empty")
    width = len(rows[0])
    if width == 0 or any(len(row) != width for row in rows):
        raise ProbeAEvidenceError(f"{field} must be a non-empty rectangular matrix")
    return [sum(row[column] for row in rows) / len(rows) for column in range(width)]


def _require_close(observed: object, expected: float, field: str) -> None:
    value = _finite(observed, field)
    if not math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-15):
        raise ProbeAEvidenceError(f"{field} is inconsistent with the raw measurements")


def _load_probe_a_raw(root: Path, sample: Mapping) -> dict:
    entry = _exact_keys(sample, {"path", "sha256"}, "raw sample")
    path = _relative_file(root, entry["path"])
    expected_sha = _sha(entry["sha256"], "raw sample SHA-256")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ProbeAEvidenceError(f"cannot read Probe-A raw measurements: {exc}") from exc
    if sha256_bytes(data) != expected_sha:
        raise ProbeAEvidenceError("Probe-A raw sample SHA-256 mismatch")
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeAEvidenceError(f"cannot parse Probe-A raw measurements: {exc}") from exc
    obj = _exact_keys(payload, _RAW_KEYS, "Probe-A raw measurements")
    try:
        canonical = _canonical_file_bytes(obj)
    except (TypeError, ValueError) as exc:
        raise ProbeAEvidenceError("Probe-A raw measurements are not canonical finite JSON") from exc
    if data != canonical:
        raise ProbeAEvidenceError("Probe-A raw measurements are not canonical JSON")
    _checksum(obj, "Probe-A raw measurements")
    if obj["schema"] != RAW_SCHEMA:
        raise ProbeAEvidenceError("Probe-A raw-measurement schema mismatch")

    input_before = _finite_matrix(obj["input_before"], "raw.input_before")
    input_after = _finite_matrix(obj["input_after"], "raw.input_after")
    if len(input_before) != len(input_after) or len(input_before[0]) != len(input_after[0]):
        raise ProbeAEvidenceError("Probe-A input matrices have different shapes")

    runs = obj["determinism_runs"]
    if not isinstance(runs, list) or len(runs) != 2:
        raise ProbeAEvidenceError("Probe-A raw determinism measurements require exactly two runs")
    checkpoints: list[str] = []
    checkpoint_files: list[tuple[str, str]] = []
    run_predictions: list[list[float]] = []
    for index, raw_run in enumerate(runs):
        run = _exact_keys(raw_run, _RAW_RUN_KEYS, f"raw determinism run {index}")
        checkpoint_path = run["checkpoint_path"]
        checkpoint_file = _relative_file(root, checkpoint_path)
        checkpoint_sha = _sha(run["checkpoint_sha256"], f"raw run {index} checkpoint")
        if sha256_file(checkpoint_file) != checkpoint_sha:
            raise ProbeAEvidenceError(
                f"raw run {index} checkpoint SHA-256 differs from the archived file"
            )
        checkpoints.append(checkpoint_sha)
        checkpoint_files.append((checkpoint_path, checkpoint_sha))
        run_predictions.append(
            _finite_vector(run["prediction"], f"raw determinism run {index} prediction")
        )
    det_error = _max_abs_error(
        run_predictions[0], run_predictions[1], "raw determinism predictions"
    )

    ordered_control_row_ids = _ordered_row_ids(
        obj["ordered_control_row_ids"], "raw.ordered_control_row_ids"
    )
    if len(ordered_control_row_ids) < max(_CONTROL_COUNTS):
        raise ProbeAEvidenceError(
            "Probe-A raw measurements require at least 400 ordered control-row identities"
        )

    raw_controls = obj["control_predictions"]
    if not isinstance(raw_controls, list) or len(raw_controls) != 5:
        raise ProbeAEvidenceError("Probe-A raw control-count measurements are incomplete")
    controls: dict[int, list[float]] = {}
    reconstructed_controls: dict[int, list[float]] = {}
    control_order: list[int] = []
    for index, raw_control in enumerate(raw_controls):
        control = _exact_keys(raw_control, _RAW_CONTROL_KEYS, f"raw control prediction {index}")
        count = _positive_int(control["count"], f"raw control prediction {index}.count")
        if count in controls:
            raise ProbeAEvidenceError("Probe-A raw control-count roster contains duplicates")
        control_order.append(count)
        row_ids = _ordered_row_ids(
            control["control_row_ids"], f"raw control prediction {index}.control_row_ids"
        )
        if len(row_ids) != count or row_ids != ordered_control_row_ids[:count]:
            raise ProbeAEvidenceError(
                "Probe-A control rows must be the exact prefix of the frozen ordered control roster"
            )
        per_control = _finite_matrix(
            control["per_control_prediction"],
            f"raw control prediction {index}.per_control_prediction",
        )
        if len(per_control) != count:
            raise ProbeAEvidenceError(
                "Probe-A per-control prediction count differs from its ordered control prefix"
            )
        public_prediction = _finite_vector(
            control["public_prediction"],
            f"raw control prediction {index}.public_prediction",
        )
        reconstructed = _column_mean(
            per_control[: min(count, 300)],
            f"raw control prediction {index}.first_300_reconstruction",
        )
        if len(public_prediction) != len(reconstructed):
            raise ProbeAEvidenceError(
                "Probe-A public and per-control reconstructed predictions differ in width"
            )
        controls[count] = public_prediction
        reconstructed_controls[count] = reconstructed
    widths = {len(prediction) for prediction in controls.values()}
    if len(widths) != 1:
        raise ProbeAEvidenceError("Probe-A raw control predictions have different lengths")
    if control_order != list(_CONTROL_COUNTS):
        raise ProbeAEvidenceError("Probe-A raw control-count roster/order is not registered")
    reconstruction_errors = [
        _max_abs_error(
            controls[count],
            reconstructed_controls[count],
            f"raw controls {count} public versus per-control reconstruction",
        )
        for count in _CONTROL_COUNTS
    ]
    cap_errors = [
        _max_abs_error(controls[300], controls[count], f"raw controls 300 versus {count}")
        for count in (301, 400)
    ]
    cap_error = max([*reconstruction_errors, *cap_errors])

    public = _finite_vector(obj["public_prediction"], "raw.public_prediction")
    bridge = _finite_vector(obj["bridge_prediction"], "raw.bridge_prediction")
    bridge_error = _max_abs_error(public, bridge, "raw public/bridge predictions")
    ordered = sorted(public)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0
    return {
        "input_before": input_before,
        "input_after": input_after,
        "checkpoints": checkpoints,
        "checkpoint_files": checkpoint_files,
        "run_predictions": run_predictions,
        "det_error": det_error,
        "control_order": control_order,
        "controls": controls,
        "reconstructed_controls": reconstructed_controls,
        "cap_error": cap_error,
        "public": public,
        "bridge_error": bridge_error,
        "output_scale": {
            "minimum": min(public),
            "median": median,
            "maximum": max(public),
            "negative_fraction": sum(value < 0 for value in public) / len(public),
            "near_integer_fraction": sum(
                abs(value - round(value)) <= _NEAR_INTEGER_ATOL for value in public
            )
            / len(public),
        },
    }


def validate_probe_a_raw_artifact(
    *, evidence_root: str | Path, relative_path: str, expected_sha256: str
) -> None:
    """Validate one raw publication and every checkpoint it references."""
    _load_probe_a_raw(
        Path(evidence_root),
        {"path": relative_path, "sha256": expected_sha256},
    )


def validate_probe_a_report(
    report: Mapping,
    *,
    registration: Mapping,
    registration_sha256: str,
    evidence_root: str | Path,
    expected_git_commit: str,
) -> None:
    """Validate a complete Probe-A report against frozen decisions and raw samples."""
    validate_registration(registration, expected_git_commit=expected_git_commit)
    registered_sha = _sha(registration_sha256, "registration_sha256")
    _exact_keys(report, _REPORT_KEYS, "Probe-A report")
    _checksum(report, "Probe-A report")
    if report["schema"] != REPORT_SCHEMA or report["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("Probe-A report identity mismatch")
    if report["status"] != "pass":
        raise ProbeAEvidenceError("Probe-A report did not pass")
    commit = _git_commit(report["git_commit"], "Probe-A report git_commit")
    if commit != _git_commit(expected_git_commit, "expected Git commit"):
        raise ProbeAEvidenceError("Probe-A Git commit differs from the approved commit")
    if _sha(report["registration_sha256"], "report.registration_sha256") != registered_sha:
        raise ProbeAEvidenceError("Probe-A report is not bound to the approved registration")
    for field in ("runtime_sha256", "input_manifest_sha256", "source_fingerprint_sha256"):
        _sha(report[field], field)

    samples = report["raw_samples"]
    if not isinstance(samples, list) or len(samples) != 1:
        raise ProbeAEvidenceError("Probe-A requires exactly one complete raw-measurement artifact")
    raw = _load_probe_a_raw(Path(evidence_root), samples[0])

    registered_input = registration["input_scale"]
    input_scale = _exact_keys(
        report["input_scale"],
        {"before_sha256", "after_sha256", "exact_equal", "normalization_target", "transform"},
        "input_scale",
    )
    before_sha = _sha(input_scale["before_sha256"], "input_scale.before_sha256")
    after_sha = _sha(input_scale["after_sha256"], "input_scale.after_sha256")
    if before_sha != sha256_json(raw["input_before"]) or after_sha != sha256_json(
        raw["input_after"]
    ):
        raise ProbeAEvidenceError("Probe-A input-scale digests disagree with raw matrices")
    if (
        input_scale["exact_equal"] is not True
        or raw["input_before"] != raw["input_after"]
        or input_scale["before_sha256"] != input_scale["after_sha256"]
    ):
        raise ProbeAEvidenceError("GEARS changed the registered probe input scale")
    normalization_target = _finite_nonnegative(
        input_scale["normalization_target"], "normalization_target"
    )
    if (
        normalization_target != float(registered_input["normalization_target"])
        or input_scale["transform"] != registered_input["transform"]
    ):
        raise ProbeAEvidenceError("Probe-A input scale differs from preregistration")

    registered_determinism = registration["determinism"]
    determinism = _exact_keys(
        report["determinism"],
        {"checkpoint_sha256", "prediction_sha256", "max_abs_error", "tolerance", "verdict"},
        "determinism",
    )
    for field in ("checkpoint_sha256", "prediction_sha256"):
        values = determinism[field]
        if not isinstance(values, list) or len(values) != 2:
            raise ProbeAEvidenceError(f"determinism.{field} must contain exactly two runs")
        for value in values:
            _sha(value, f"determinism.{field}")
    if determinism["checkpoint_sha256"] != raw["checkpoints"] or determinism[
        "prediction_sha256"
    ] != [sha256_json(value) for value in raw["run_predictions"]]:
        raise ProbeAEvidenceError("Probe-A determinism identities disagree with raw measurements")
    det_error = _finite_nonnegative(determinism["max_abs_error"], "determinism.max_abs_error")
    _require_close(det_error, raw["det_error"], "determinism.max_abs_error")
    det_tol = _finite_nonnegative(determinism["tolerance"], "determinism.tolerance")
    if det_tol != float(registered_determinism["max_abs_error_tolerance"]):
        raise ProbeAEvidenceError("Probe-A determinism tolerance differs from preregistration")
    if (
        determinism["verdict"] != "pass"
        or determinism["checkpoint_sha256"][0] != determinism["checkpoint_sha256"][1]
        or determinism["prediction_sha256"][0] != determinism["prediction_sha256"][1]
        or det_error > det_tol
    ):
        raise ProbeAEvidenceError("Probe-A determinism gate failed")

    registered_control = registration["control_count"]
    control = _exact_keys(
        report["control_count"],
        {"counts", "prediction_sha256", "first_300_max_abs_error", "tolerance", "verdict"},
        "control_count",
    )
    if control["counts"] != registered_control["counts"]:
        raise ProbeAEvidenceError("Probe-A control-count roster differs from preregistration")
    if control["counts"] != raw["control_order"]:
        raise ProbeAEvidenceError("Probe-A control-count roster differs from raw measurements")
    if not isinstance(control["prediction_sha256"], list) or len(control["prediction_sha256"]) != 5:
        raise ProbeAEvidenceError("Probe-A control-count predictions are incomplete")
    for value in control["prediction_sha256"]:
        _sha(value, "control_count.prediction_sha256")
    if control["prediction_sha256"] != [
        sha256_json(raw["controls"][count]) for count in raw["control_order"]
    ]:
        raise ProbeAEvidenceError(
            "Probe-A control prediction identities disagree with raw measurements"
        )
    cap_error = _finite_nonnegative(control["first_300_max_abs_error"], "first_300_max_abs_error")
    _require_close(cap_error, raw["cap_error"], "control_count.first_300_max_abs_error")
    cap_tol = _finite_nonnegative(control["tolerance"], "control_count.tolerance")
    if cap_tol != float(registered_control["first_300_max_abs_error_tolerance"]):
        raise ProbeAEvidenceError("Probe-A control-count tolerance differs from preregistration")
    if control["verdict"] != "pass" or cap_error > cap_tol:
        raise ProbeAEvidenceError("Probe-A first-300 control gate failed")

    output_scale = _exact_keys(
        report["output_scale"],
        {"minimum", "median", "maximum", "negative_fraction", "near_integer_fraction"},
        "output_scale",
    )
    values = [
        _finite(output_scale[key], f"output_scale.{key}")
        for key in ("minimum", "median", "maximum")
    ]
    if values != sorted(values):
        raise ProbeAEvidenceError("Probe-A output-scale summary is invalid")
    for field in ("negative_fraction", "near_integer_fraction"):
        value = _finite_nonnegative(output_scale[field], f"output_scale.{field}")
        if value > 1:
            raise ProbeAEvidenceError(f"output_scale.{field} must be a fraction")
    for field, expected in raw["output_scale"].items():
        _require_close(output_scale[field], expected, f"output_scale.{field}")

    registered_bridge = registration["output_bridge"]
    bridge = _exact_keys(report["output_bridge"], _BRIDGE_KEYS, "output_bridge")
    bridge_error = _finite_nonnegative(bridge["max_abs_error"], "output_bridge.max_abs_error")
    _require_close(bridge_error, raw["bridge_error"], "output-bridge max_abs_error")
    bridge_tol = _finite_nonnegative(bridge["tolerance"], "output_bridge.tolerance")
    if bridge["representation"] != registered_bridge["representation"] or bridge_tol != float(
        registered_bridge["max_abs_error_tolerance"]
    ):
        raise ProbeAEvidenceError("Probe-A output bridge differs from preregistration")
    if bridge["verdict"] != "pass" or bridge_error > bridge_tol:
        raise ProbeAEvidenceError("Probe-A output-bridge equivalence failed")


def _validate_role_path(role: str, relative: str) -> None:
    if role in _SINGLETON_ROLE_PATHS and relative != _SINGLETON_ROLE_PATHS[role]:
        raise ProbeAEvidenceError(f"Probe-A manifest {role} path is not canonical")
    path = Path(relative)
    if role == "roster_receipt" and (not path.parts or path.parts[0] != "roster_receipts"):
        raise ProbeAEvidenceError("Probe-A roster receipt must be under roster_receipts/")
    if role == "probe_a_checkpoint" and (
        not path.parts or path.parts[0] != "checkpoints" or path.suffix != ".pt"
    ):
        raise ProbeAEvidenceError("Probe-A checkpoint must be a .pt file under checkpoints/")
    if role == "log" and (not path.parts or path.parts[0] != "logs"):
        raise ProbeAEvidenceError("Probe-A log must be under logs/")


def validate_evidence_manifest(
    manifest: Mapping,
    *,
    evidence_root: str | Path,
    expected_git_commit: str,
) -> None:
    """Validate the exhaustive, canonical file roster for one complete probe attempt."""
    obj = _exact_keys(
        manifest,
        {"schema", "protocol", "git_commit", "files", "manifest_checksum"},
        "evidence manifest",
    )
    if obj["schema"] != MANIFEST_SCHEMA or obj["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("Probe-A evidence-manifest identity mismatch")
    commit = _git_commit(obj["git_commit"], "evidence manifest git_commit")
    if commit != _git_commit(expected_git_commit, "expected Git commit"):
        raise ProbeAEvidenceError("Probe-A evidence-manifest Git commit mismatch")
    checksum = _sha(obj["manifest_checksum"], "evidence manifest checksum")
    body = {key: value for key, value in obj.items() if key != "manifest_checksum"}
    if checksum != sha256_json(body):
        raise ProbeAEvidenceError("Probe-A evidence-manifest checksum mismatch")
    files = obj["files"]
    if not isinstance(files, list) or not files:
        raise ProbeAEvidenceError("Probe-A evidence-manifest file roster is empty")

    root = Path(evidence_root)
    observed_paths: set[str] = set()
    roles: Counter[str] = Counter()
    for raw_entry in files:
        entry = _exact_keys(raw_entry, _MANIFEST_ENTRY_KEYS, "manifest file")
        role = entry["role"]
        if not isinstance(role, str) or role not in _KNOWN_ROLES:
            raise ProbeAEvidenceError("Probe-A evidence-manifest role is unknown")
        relative = entry["path"]
        if not isinstance(relative, str) or not relative:
            raise ProbeAEvidenceError("Probe-A evidence-manifest path must be a string")
        if relative in observed_paths:
            raise ProbeAEvidenceError("Probe-A evidence-manifest path is duplicated")
        observed_paths.add(relative)
        roles[role] += 1
        _validate_role_path(role, relative)
        path = _relative_file(root, relative)
        if isinstance(entry["bytes"], bool) or not isinstance(entry["bytes"], int):
            raise ProbeAEvidenceError("Probe-A manifest byte count must be an integer")
        if entry["bytes"] < 0 or path.stat().st_size != entry["bytes"]:
            raise ProbeAEvidenceError("Probe-A manifest byte count mismatch")
        if sha256_file(path) != _sha(entry["sha256"], "manifest file SHA-256"):
            raise ProbeAEvidenceError("Probe-A manifest file SHA-256 mismatch")

    for role in _SINGLETON_ROLE_PATHS:
        if roles[role] != 1:
            raise ProbeAEvidenceError(f"Probe-A manifest requires exactly one {role} file")
    for role in _MULTI_ROLES:
        if roles[role] < 1:
            raise ProbeAEvidenceError(f"Probe-A manifest requires at least one {role} file")
    if roles["probe_a_checkpoint"] != 2:
        raise ProbeAEvidenceError("Probe-A manifest requires exactly two checkpoint files")

    inventory = _manifest_inventory(root)
    if observed_paths != inventory:
        missing = sorted(inventory - observed_paths)
        unexpected = sorted(observed_paths - inventory)
        raise ProbeAEvidenceError(
            "Probe-A evidence-manifest is not exhaustive: "
            f"unmanifested={missing} absent_from_tree={unexpected}"
        )


def _read_json_entry(
    root: Path,
    entry: Mapping,
    *,
    label: str,
    pretty_canonical: bool = False,
) -> dict:
    path = _relative_file(root, entry["path"])
    try:
        data = path.read_bytes()
        payload = json.loads(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeAEvidenceError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProbeAEvidenceError(f"{label} must be a JSON object")
    if len(data) != entry["bytes"] or sha256_bytes(data) != entry["sha256"]:
        raise ProbeAEvidenceError(f"{label} bytes changed after manifest validation")
    try:
        if pretty_canonical:
            expected = (
                json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
            ).encode("utf-8")
        else:
            expected = _canonical_file_bytes(payload)
    except (TypeError, ValueError) as exc:
        raise ProbeAEvidenceError(f"{label} is not canonical finite JSON") from exc
    if data != expected:
        raise ProbeAEvidenceError(f"{label} bytes are not canonical JSON")
    return payload


def _positive_int(value: object, field: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ProbeAEvidenceError(f"{field} must be a {qualifier} integer")
    return value


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProbeAEvidenceError(f"{field} must be a non-empty string")
    return value


def _fit_role_counts(value: object, field: str) -> dict[str, int]:
    counts = _exact_keys(value, _FIT_ROLE_COUNT_KEYS, field)
    result = {
        "control": _positive_int(counts["control"], f"{field}.control"),
        "singles": _positive_int(counts["singles"], f"{field}.singles"),
        "combo_calibration": _positive_int(
            counts["combo_calibration"], f"{field}.combo_calibration", allow_zero=True
        ),
    }
    return result


def _timestamp(value: object, field: str) -> datetime:
    text = _nonempty_string(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProbeAEvidenceError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ProbeAEvidenceError(f"{field} must include a timezone")
    return parsed


def _validate_runtime(payload: Mapping, *, expected_git_commit: str) -> dict:
    obj = _exact_keys(payload, _RUNTIME_KEYS, "runtime evidence")
    _checksum(obj, "runtime evidence")
    if obj["schema"] != RUNTIME_SCHEMA or obj["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("runtime evidence identity mismatch")
    if _git_commit(obj["git_commit"], "runtime git_commit") != _git_commit(
        expected_git_commit, "expected Git commit"
    ):
        raise ProbeAEvidenceError("runtime evidence Git commit mismatch")
    for field in (
        "pod_instance",
        "gpu_model",
        "gpu_uuid",
        "driver_version",
        "cuda_version",
        "cpu_model",
        "python_version",
    ):
        _nonempty_string(obj[field], f"runtime.{field}")
    _positive_int(obj["cpu_count"], "runtime.cpu_count")
    _positive_int(obj["ram_bytes"], "runtime.ram_bytes")
    image_digest = _nonempty_string(obj["image_digest"], "runtime.image_digest")
    if not image_digest.startswith("sha256:") or len(image_digest) != 71:
        raise ProbeAEvidenceError("runtime.image_digest must be sha256:<64 lowercase hex>")
    _sha(image_digest.removeprefix("sha256:"), "runtime.image_digest")
    _sha(obj["dependency_lock_sha256"], "runtime.dependency_lock_sha256")
    _sha(obj["runtime_fingerprint_sha256"], "runtime.runtime_fingerprint_sha256")
    if obj["network_disabled"] is not True:
        raise ProbeAEvidenceError("runtime evidence must attest network_disabled=true")
    return dict(obj)


def _validate_inputs(payload: Mapping, *, expected_git_commit: str) -> dict:
    obj = _exact_keys(payload, _INPUTS_KEYS, "input evidence")
    _checksum(obj, "input evidence")
    if obj["schema"] != INPUTS_SCHEMA or obj["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("input evidence identity mismatch")
    if _git_commit(obj["git_commit"], "inputs git_commit") != _git_commit(
        expected_git_commit, "expected Git commit"
    ):
        raise ProbeAEvidenceError("input evidence Git commit mismatch")
    non_digest_fields = {"schema", "protocol", "git_commit", "fit_role_counts", "self_checksum"}
    for field in _INPUTS_KEYS - non_digest_fields:
        _sha(obj[field], f"inputs.{field}")
    obj = dict(obj)
    obj["fit_role_counts"] = _fit_role_counts(obj["fit_role_counts"], "inputs.fit_role_counts")
    return obj


def _validate_role_attestation(payload: Mapping, *, expected_git_commit: str) -> dict:
    obj = _exact_keys(payload, _ROLE_ATTESTATION_KEYS, "role attestation")
    _checksum(obj, "role attestation")
    if obj["schema"] != ROLE_ATTESTATION_SCHEMA or obj["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("role attestation identity mismatch")
    if _git_commit(obj["git_commit"], "role attestation git_commit") != _git_commit(
        expected_git_commit, "expected Git commit"
    ):
        raise ProbeAEvidenceError("role attestation Git commit mismatch")
    if obj["sealed_pair_overlap_count"] != 0 or obj["sealed_row_read_count"] != 0:
        raise ProbeAEvidenceError("role attestation must prove zero sealed overlap and zero reads")
    counts = _fit_role_counts(obj["fit_role_counts"], "role_attestation.fit_role_counts")
    spy = _exact_keys(obj["reader_spy"], {"status", "observed_row_indices_sha256"}, "reader_spy")
    if spy["status"] != "pass":
        raise ProbeAEvidenceError("role attestation reader-spy did not pass")
    _sha(spy["observed_row_indices_sha256"], "reader_spy.observed_row_indices_sha256")
    result = dict(obj)
    result["fit_role_counts"] = counts
    return result


def _validate_roster_receipt(payload: Mapping) -> dict:
    obj = _exact_keys(payload, _ROSTER_RECEIPT_KEYS, "roster receipt")
    if obj["schema"] != ROSTER_RECEIPT_SCHEMA:
        raise ProbeAEvidenceError("roster receipt identity mismatch")
    checksum = _sha(obj["manifest_checksum"], "roster receipt manifest_checksum")
    body = {key: value for key, value in obj.items() if key != "manifest_checksum"}
    if checksum != sha256_json(body):
        raise ProbeAEvidenceError("roster receipt manifest checksum mismatch")
    for field in _ROSTER_RECEIPT_KEYS - {"schema", "manifest_checksum", "n_target"}:
        _sha(obj[field], f"roster receipt.{field}")
    _positive_int(obj["n_target"], "roster receipt.n_target")
    return dict(obj)


def _validate_commands(
    path: Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
    runtime_fingerprint_sha256: str,
    raw_sample_path: str,
    raw_sample_sha256: str,
) -> None:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ProbeAEvidenceError(f"cannot read commands evidence: {exc}") from exc
    if len(data) != expected_bytes or sha256_bytes(data) != expected_sha256:
        raise ProbeAEvidenceError("commands evidence bytes changed after manifest validation")
    lines = data.splitlines()
    if not lines:
        raise ProbeAEvidenceError("commands evidence is empty")
    observed: Counter[str] = Counter()
    probe_a_primary_sha256: list[str] = []
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProbeAEvidenceError(f"commands record {index} is invalid JSON") from exc
        obj = _exact_keys(record, _COMMAND_KEYS, f"commands record {index}")
        try:
            canonical_line = canonical_json(obj).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ProbeAEvidenceError(
                f"commands record {index} is not canonical finite JSON"
            ) from exc
        if line != canonical_line:
            raise ProbeAEvidenceError(f"commands record {index} is not canonical JSONL")
        _checksum(obj, f"commands record {index}")
        if obj["schema"] != COMMAND_RECORD_SCHEMA:
            raise ProbeAEvidenceError("commands evidence schema mismatch")
        command = _nonempty_string(obj["command"], f"commands record {index}.command")
        if command not in _REQUIRED_COMMANDS:
            raise ProbeAEvidenceError(
                "commands evidence contains an unsupported maintained-CLI command"
            )
        observed[command] += 1
        argv = obj["argv"]
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(token, str) or not token for token in argv)
        ):
            raise ProbeAEvidenceError("commands argv must be a non-empty string list")
        if command not in argv or not any(
            token.endswith("scripts/compose/gears_decision_probe.py") for token in argv
        ):
            raise ProbeAEvidenceError(
                "commands argv must invoke the maintained GEARS probe CLI and named subcommand"
            )
        if any("$(" in token or "`" in token for token in argv):
            raise ProbeAEvidenceError("commands argv must not use shell command substitution")
        if command == "probe-a":
            for option in ("--measurement-json", "--evidence-root", "--out-raw"):
                if argv.count(option) != 1 or argv.index(option) + 1 >= len(argv):
                    raise ProbeAEvidenceError(
                        f"Probe-A measurement command requires exactly one {option} value"
                    )
            out_raw = argv[argv.index("--out-raw") + 1]
            if Path(out_raw).as_posix() != raw_sample_path and not out_raw.endswith(
                f"/{raw_sample_path}"
            ):
                raise ProbeAEvidenceError(
                    "Probe-A measurement command output path differs from the raw manifest path"
                )
        _nonempty_string(obj["cwd"], f"commands record {index}.cwd")
        env = obj["env"]
        if not isinstance(env, Mapping) or any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or any(
                secret in key.lower() for secret in ("secret", "token", "password", "private_key")
            )
            for key, value in env.items()
        ):
            raise ProbeAEvidenceError("commands env must be a secret-free string allowlist")
        started = _timestamp(obj["started_at_utc"], f"commands record {index}.started_at_utc")
        ended = _timestamp(obj["ended_at_utc"], f"commands record {index}.ended_at_utc")
        if ended < started:
            raise ProbeAEvidenceError("commands record ended before it started")
        if obj["exit_code"] != 0:
            raise ProbeAEvidenceError("commands evidence contains a failed command")
        primary_sha256 = _sha(
            obj["primary_file_sha256"], f"commands record {index}.primary_file_sha256"
        )
        if command == "probe-a":
            probe_a_primary_sha256.append(primary_sha256)
        if (
            _sha(
                obj["runtime_fingerprint_sha256"],
                f"commands record {index}.runtime_fingerprint_sha256",
            )
            != runtime_fingerprint_sha256
        ):
            raise ProbeAEvidenceError("commands runtime fingerprint differs from runtime evidence")
    observed_commands = frozenset(observed)
    if observed_commands != _REQUIRED_COMMANDS:
        raise ProbeAEvidenceError(
            "commands evidence does not contain the exact required command roster: "
            f"missing={sorted(_REQUIRED_COMMANDS - observed_commands)} "
            f"unexpected={sorted(observed_commands - _REQUIRED_COMMANDS)}"
        )
    if observed["probe-a"] != 1:
        raise ProbeAEvidenceError(
            "commands evidence requires exactly one Probe-A measurement command"
        )
    if probe_a_primary_sha256 != [_sha(raw_sample_sha256, "raw sample SHA-256")]:
        raise ProbeAEvidenceError(
            "Probe-A measurement command primary SHA-256 is not bound to the raw artifact"
        )


def validate_evidence_semantics(
    manifest: Mapping,
    *,
    evidence_root: str | Path,
    expected_git_commit: str,
    registration_sha256: str,
) -> None:
    """Validate the content and cross-bindings of every decision-bearing evidence role."""
    root = Path(evidence_root)
    by_role = _manifest_by_role(manifest)
    registration_entry = by_role["probe_a_registration"][0]
    if registration_entry["sha256"] != _sha(registration_sha256, "registration_sha256"):
        raise ProbeAEvidenceError("semantic evidence registration SHA-256 differs from its pin")
    runtime_entry = by_role["runtime"][0]
    inputs_entry = by_role["inputs"][0]
    runtime = _validate_runtime(
        _read_json_entry(root, runtime_entry, label="runtime evidence"),
        expected_git_commit=expected_git_commit,
    )
    inputs = _validate_inputs(
        _read_json_entry(root, inputs_entry, label="input evidence"),
        expected_git_commit=expected_git_commit,
    )
    role_attestation = _validate_role_attestation(
        _read_json_entry(
            root,
            by_role["role_attestation"][0],
            label="role attestation",
        ),
        expected_git_commit=expected_git_commit,
    )
    if role_attestation["fit_role_counts"] != inputs["fit_role_counts"]:
        raise ProbeAEvidenceError("role attestation counts differ from input evidence")
    if runtime["dependency_lock_sha256"] != inputs["dependency_lock_sha256"]:
        raise ProbeAEvidenceError("runtime and input dependency-lock identities differ")
    receipt_pairs: set[tuple[str, str]] = set()
    for entry in by_role["roster_receipt"]:
        receipt = _validate_roster_receipt(
            _read_json_entry(
                root,
                entry,
                label="roster receipt",
                pretty_canonical=True,
            )
        )
        receipt_pairs.add((entry["sha256"], receipt["roster_file_sha256"]))
    if (inputs["roster_receipt_sha256"], inputs["roster_sha256"]) not in receipt_pairs:
        raise ProbeAEvidenceError("input evidence is not bound to a manifested roster receipt")
    command_entry = by_role["commands"][0]
    raw_entries = by_role["raw_sample"]
    if len(raw_entries) != 1:
        raise ProbeAEvidenceError("semantic evidence requires exactly one raw sample")
    _validate_commands(
        _relative_file(root, command_entry["path"]),
        expected_sha256=command_entry["sha256"],
        expected_bytes=command_entry["bytes"],
        runtime_fingerprint_sha256=runtime["runtime_fingerprint_sha256"],
        raw_sample_path=raw_entries[0]["path"],
        raw_sample_sha256=raw_entries[0]["sha256"],
    )

    raw = _load_probe_a_raw(
        root,
        {"path": raw_entries[0]["path"], "sha256": raw_entries[0]["sha256"]},
    )
    manifested_checkpoints = {
        (entry["path"], entry["sha256"]) for entry in by_role["probe_a_checkpoint"]
    }
    if len(manifested_checkpoints) != 2 or set(raw["checkpoint_files"]) != manifested_checkpoints:
        raise ProbeAEvidenceError(
            "raw determinism checkpoints are not exactly the two manifested checkpoint files"
        )


def _manifest_by_role(manifest: Mapping) -> dict[str, list[Mapping]]:
    files = manifest.get("files") if isinstance(manifest, Mapping) else None
    if not isinstance(files, list):
        raise ProbeAEvidenceError("Probe-A binding requires a manifest file roster")
    result: dict[str, list[Mapping]] = {}
    for entry in files:
        item = _exact_keys(entry, _MANIFEST_ENTRY_KEYS, "manifest file")
        role = item["role"]
        if not isinstance(role, str) or role not in _KNOWN_ROLES:
            raise ProbeAEvidenceError("Probe-A binding encountered an unknown manifest role")
        result.setdefault(role, []).append(item)
    return result


def assert_report_manifest_binding(
    report: Mapping,
    manifest: Mapping,
    *,
    report_sha256: str,
    registration_sha256: str,
) -> None:
    """Bind report, registration, identities, and the exact raw-sample roster."""
    by_role = _manifest_by_role(manifest)

    def singleton_sha(role: str) -> str:
        entries = by_role.get(role, [])
        if len(entries) != 1:
            raise ProbeAEvidenceError(f"Probe-A binding requires exactly one {role} file")
        return entries[0]["sha256"]

    expected = {
        "probe_a_report": _sha(report_sha256, "report_sha256"),
        "probe_a_registration": _sha(registration_sha256, "registration_sha256"),
        "runtime": _sha(report.get("runtime_sha256"), "report.runtime_sha256"),
        "inputs": _sha(report.get("input_manifest_sha256"), "report.input_manifest_sha256"),
        "probe_a_source": _sha(
            report.get("source_fingerprint_sha256"), "report.source_fingerprint_sha256"
        ),
    }
    for role, digest in expected.items():
        if singleton_sha(role) != digest:
            raise ProbeAEvidenceError(f"Probe-A {role} SHA-256 disagrees with the report/CLI pin")
    if report.get("registration_sha256") != expected["probe_a_registration"]:
        raise ProbeAEvidenceError("Probe-A report registration SHA-256 disagrees with the manifest")

    samples = report.get("raw_samples") if isinstance(report, Mapping) else None
    if not isinstance(samples, list):
        raise ProbeAEvidenceError("Probe-A binding requires a report raw-sample roster")
    reported: set[tuple[str, str]] = set()
    for sample in samples:
        item = _exact_keys(sample, {"path", "sha256"}, "raw sample")
        path = item["path"]
        digest = _sha(item["sha256"], "raw sample SHA-256")
        if not isinstance(path, str) or not path:
            raise ProbeAEvidenceError("raw sample path must be a non-empty string")
        reported.add((path, digest))
    manifested: set[tuple[str, str]] = set()
    for item in by_role.get("raw_sample", []):
        path = item["path"]
        digest = _sha(item["sha256"], "manifest raw-sample SHA-256")
        if not isinstance(path, str) or not path:
            raise ProbeAEvidenceError("manifest raw-sample path must be a non-empty string")
        manifested.add((path, digest))
    if reported != manifested:
        raise ProbeAEvidenceError(
            "Probe-A report and manifest raw-sample rosters differ "
            f"report_only={sorted(reported - manifested)} "
            f"manifest_only={sorted(manifested - reported)}"
        )


def _canonical_file_bytes(payload: Mapping) -> bytes:
    return canonical_file_bytes(payload)


def build_evidence_outputs(
    *,
    report_bytes: bytes,
    report_sha256: str,
    registration_bytes: bytes,
    registration_sha256: str,
    manifest_bytes: bytes,
    evidence_root: str | Path,
    evidence_manifest_sha256: str,
    expected_git_commit: str,
    verifier_code_sha256: str,
) -> ProbeAAdmissionOutputs:
    """Validate all evidence and build a receipt-first, admission-last output pair."""
    registration = _json_object_from_bytes(
        registration_bytes,
        expected_sha256=registration_sha256,
        label="registration",
    )
    report = _json_object_from_bytes(
        report_bytes,
        expected_sha256=report_sha256,
        label="report",
    )
    manifest = _json_object_from_bytes(
        manifest_bytes,
        expected_sha256=evidence_manifest_sha256,
        label="evidence manifest",
    )
    validate_evidence_manifest(
        manifest,
        evidence_root=evidence_root,
        expected_git_commit=expected_git_commit,
    )
    validate_probe_a_report(
        report,
        registration=registration,
        registration_sha256=registration_sha256,
        evidence_root=evidence_root,
        expected_git_commit=expected_git_commit,
    )
    assert_report_manifest_binding(
        report,
        manifest,
        report_sha256=report_sha256,
        registration_sha256=registration_sha256,
    )
    validate_evidence_semantics(
        manifest,
        evidence_root=evidence_root,
        expected_git_commit=expected_git_commit,
        registration_sha256=registration_sha256,
    )
    verification_body = {
        "schema": VERIFICATION_SCHEMA,
        "protocol": PROTOCOL,
        "status": "pass",
        "git_commit": expected_git_commit,
        "registration_sha256": _sha(registration_sha256, "registration_sha256"),
        "report_sha256": _sha(report_sha256, "report_sha256"),
        "evidence_manifest_sha256": _sha(evidence_manifest_sha256, "evidence_manifest_sha256"),
        "verifier_code_sha256": _sha(verifier_code_sha256, "verifier_code_sha256"),
        "output_bridge": dict(report["output_bridge"]),
    }
    verification = {
        **verification_body,
        "self_checksum": self_checksum(verification_body),
    }
    verification_bytes = _canonical_file_bytes(verification)
    verification_sha256 = sha256_bytes(verification_bytes)
    body = {
        "schema": ADMISSION_SCHEMA,
        "protocol": PROTOCOL,
        "status": "pass",
        "git_commit": expected_git_commit,
        "registration_sha256": _sha(registration_sha256, "registration_sha256"),
        "evidence_manifest_sha256": _sha(evidence_manifest_sha256, "evidence_manifest_sha256"),
        "verification_sha256": verification_sha256,
        "output_bridge": dict(report["output_bridge"]),
    }
    admission = {**body, "self_checksum": self_checksum(body)}
    validate_admission(
        admission,
        registration=registration,
        registration_sha256=registration_sha256,
        verification=verification,
        verification_sha256=verification_sha256,
        expected_git_commit=expected_git_commit,
    )
    return ProbeAAdmissionOutputs(
        verification=verification,
        verification_bytes=verification_bytes,
        verification_sha256=verification_sha256,
        admission=admission,
    )


def build_admission(
    *,
    report_bytes: bytes,
    report_sha256: str,
    registration_bytes: bytes,
    registration_sha256: str,
    manifest_bytes: bytes,
    evidence_root: str | Path,
    evidence_manifest_sha256: str,
    expected_git_commit: str,
    verifier_code_sha256: str,
) -> dict:
    """Compatibility wrapper returning the admission from a fully bound output pair."""
    return build_evidence_outputs(
        report_bytes=report_bytes,
        report_sha256=report_sha256,
        registration_bytes=registration_bytes,
        registration_sha256=registration_sha256,
        manifest_bytes=manifest_bytes,
        evidence_root=evidence_root,
        evidence_manifest_sha256=evidence_manifest_sha256,
        expected_git_commit=expected_git_commit,
        verifier_code_sha256=verifier_code_sha256,
    ).admission


def validate_admission(
    payload: Mapping,
    *,
    registration: Mapping,
    registration_sha256: str,
    verification: Mapping,
    verification_sha256: str,
    expected_git_commit: str,
) -> None:
    """Validate admission, registration and receipt via the consumer contract."""
    try:
        validate_probe_a_evidence(
            payload,
            registration=registration,
            registration_sha256=registration_sha256,
            verification=verification,
            verification_sha256=verification_sha256,
            expected_git_commit=expected_git_commit,
        )
    except ApproximationBiasValidationError as exc:
        raise ProbeAEvidenceError(str(exc)) from exc
