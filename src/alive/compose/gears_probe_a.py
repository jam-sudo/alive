"""Fail-closed evidence contract for the COMPOSE GEARS Probe A.

The actual GEARS fit runs only in the pinned pod environment.  This module is
dependency-light so the resulting evidence can be verified independently on a
CPU host before it is allowed to admit the approximation-bias measurement.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Mapping

from alive.provenance import sha256_file, sha256_json

REPORT_SCHEMA = "compose_gears_probe_a_report_v1"
MANIFEST_SCHEMA = "compose_gears_probe_a_evidence_manifest_v1"
ADMISSION_SCHEMA = "compose_gears_probe_a_admission_v1"
PROTOCOL = "COMPOSE-K562-v1"

_REPORT_KEYS = {
    "schema",
    "protocol",
    "status",
    "git_commit",
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
_BRIDGE_KEYS = {"representation", "verdict", "tolerance", "max_abs_error"}
_ADMISSION_KEYS = {
    "schema",
    "protocol",
    "status",
    "git_commit",
    "evidence_manifest_sha256",
    "output_bridge",
    "self_checksum",
}


class ProbeAEvidenceError(ValueError):
    """Raised when Probe-A evidence cannot cross the promotion boundary."""


def _sha(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ProbeAEvidenceError(f"{field} must be a lowercase SHA-256")
    return value


def _finite_nonnegative(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProbeAEvidenceError(f"{field} must be numeric")
    observed = float(value)
    if not math.isfinite(observed) or observed < 0:
        raise ProbeAEvidenceError(f"{field} must be finite and non-negative")
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


def _relative_file(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ProbeAEvidenceError("raw sample path must be a non-empty string")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ProbeAEvidenceError("raw sample path must be safe and relative")
    base = root.resolve(strict=True)
    candidate = (root / rel).resolve(strict=True)
    if not candidate.is_relative_to(base) or not candidate.is_file() or candidate.is_symlink():
        raise ProbeAEvidenceError("raw sample must be a regular file under evidence root")
    return candidate


def validate_probe_a_report(
    report: Mapping,
    *,
    evidence_root: str | Path,
    expected_git_commit: str,
) -> None:
    """Validate a complete Probe-A report and every referenced raw sample."""
    _exact_keys(report, _REPORT_KEYS, "Probe-A report")
    _checksum(report, "Probe-A report")
    if report["schema"] != REPORT_SCHEMA or report["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("Probe-A report identity mismatch")
    if report["status"] != "pass":
        raise ProbeAEvidenceError("Probe-A report did not pass")
    if report["git_commit"] != expected_git_commit or len(expected_git_commit) != 40:
        raise ProbeAEvidenceError("Probe-A Git commit differs from the approved commit")
    for field in ("runtime_sha256", "input_manifest_sha256", "source_fingerprint_sha256"):
        _sha(report[field], field)

    input_scale = _exact_keys(
        report["input_scale"],
        {"before_sha256", "after_sha256", "exact_equal", "normalization_target", "transform"},
        "input_scale",
    )
    _sha(input_scale["before_sha256"], "input_scale.before_sha256")
    _sha(input_scale["after_sha256"], "input_scale.after_sha256")
    if (
        input_scale["exact_equal"] is not True
        or input_scale["before_sha256"] != input_scale["after_sha256"]
    ):
        raise ProbeAEvidenceError("GEARS changed the registered probe input scale")
    _finite_nonnegative(input_scale["normalization_target"], "normalization_target")
    if input_scale["transform"] != "full_library_normalize_log1p_then_roster_subset":
        raise ProbeAEvidenceError("Probe-A input transform is not registered")

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
    det_error = _finite_nonnegative(determinism["max_abs_error"], "determinism.max_abs_error")
    det_tol = _finite_nonnegative(determinism["tolerance"], "determinism.tolerance")
    if (
        determinism["verdict"] != "pass"
        or determinism["checkpoint_sha256"][0] != determinism["checkpoint_sha256"][1]
        or determinism["prediction_sha256"][0] != determinism["prediction_sha256"][1]
        or det_error > det_tol
    ):
        raise ProbeAEvidenceError("Probe-A determinism gate failed")

    control = _exact_keys(
        report["control_count"],
        {"counts", "prediction_sha256", "first_300_max_abs_error", "tolerance", "verdict"},
        "control_count",
    )
    if control["counts"] != [1, 8, 300, 301, 400]:
        raise ProbeAEvidenceError("Probe-A control-count roster differs from preregistration")
    if not isinstance(control["prediction_sha256"], list) or len(control["prediction_sha256"]) != 5:
        raise ProbeAEvidenceError("Probe-A control-count predictions are incomplete")
    for value in control["prediction_sha256"]:
        _sha(value, "control_count.prediction_sha256")
    cap_error = _finite_nonnegative(control["first_300_max_abs_error"], "first_300_max_abs_error")
    cap_tol = _finite_nonnegative(control["tolerance"], "control_count.tolerance")
    if control["verdict"] != "pass" or cap_error > cap_tol:
        raise ProbeAEvidenceError("Probe-A first-300 control gate failed")

    output_scale = _exact_keys(
        report["output_scale"],
        {"minimum", "median", "maximum", "negative_fraction", "near_integer_fraction"},
        "output_scale",
    )
    values = [float(output_scale[key]) for key in ("minimum", "median", "maximum")]
    if not all(math.isfinite(value) for value in values) or values != sorted(values):
        raise ProbeAEvidenceError("Probe-A output-scale summary is invalid")
    for field in ("negative_fraction", "near_integer_fraction"):
        value = _finite_nonnegative(output_scale[field], f"output_scale.{field}")
        if value > 1:
            raise ProbeAEvidenceError(f"output_scale.{field} must be a fraction")

    bridge = _exact_keys(report["output_bridge"], _BRIDGE_KEYS, "output_bridge")
    bridge_error = _finite_nonnegative(bridge["max_abs_error"], "output_bridge.max_abs_error")
    bridge_tol = _finite_nonnegative(bridge["tolerance"], "output_bridge.tolerance")
    if (
        bridge["representation"] != "raw_pseudobulk_approximation"
        or bridge["verdict"] != "pass"
        or bridge_error > bridge_tol
    ):
        raise ProbeAEvidenceError("Probe-A output-bridge equivalence failed")

    samples = report["raw_samples"]
    if not isinstance(samples, list) or not samples:
        raise ProbeAEvidenceError("Probe-A raw samples are missing")
    seen: set[str] = set()
    root = Path(evidence_root)
    for sample in samples:
        entry = _exact_keys(sample, {"path", "sha256"}, "raw sample")
        if entry["path"] in seen:
            raise ProbeAEvidenceError("Probe-A raw sample path is duplicated")
        seen.add(entry["path"])
        path = _relative_file(root, entry["path"])
        if sha256_file(path) != _sha(entry["sha256"], "raw sample SHA-256"):
            raise ProbeAEvidenceError("Probe-A raw sample SHA-256 mismatch")


def validate_evidence_manifest(
    manifest: Mapping,
    *,
    evidence_root: str | Path,
    expected_git_commit: str,
) -> None:
    """Validate the exhaustive, canonical file roster for one Probe-A attempt."""
    obj = _exact_keys(
        manifest,
        {"schema", "protocol", "git_commit", "files", "manifest_checksum"},
        "evidence manifest",
    )
    if obj["schema"] != MANIFEST_SCHEMA or obj["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("Probe-A evidence-manifest identity mismatch")
    if obj["git_commit"] != expected_git_commit:
        raise ProbeAEvidenceError("Probe-A evidence-manifest Git commit mismatch")
    checksum = _sha(obj["manifest_checksum"], "evidence manifest checksum")
    body = {key: value for key, value in obj.items() if key != "manifest_checksum"}
    if checksum != sha256_json(body):
        raise ProbeAEvidenceError("Probe-A evidence-manifest checksum mismatch")
    files = obj["files"]
    if not isinstance(files, list) or not files:
        raise ProbeAEvidenceError("Probe-A evidence-manifest file roster is empty")
    root = Path(evidence_root)
    observed: set[str] = set()
    for raw_entry in files:
        entry = _exact_keys(raw_entry, {"path", "sha256", "bytes"}, "manifest file")
        relative = entry["path"]
        if relative in observed:
            raise ProbeAEvidenceError("Probe-A evidence-manifest path is duplicated")
        observed.add(relative)
        path = _relative_file(root, relative)
        if isinstance(entry["bytes"], bool) or not isinstance(entry["bytes"], int):
            raise ProbeAEvidenceError("Probe-A manifest byte count must be an integer")
        if entry["bytes"] < 0 or path.stat().st_size != entry["bytes"]:
            raise ProbeAEvidenceError("Probe-A manifest byte count mismatch")
        if sha256_file(path) != _sha(entry["sha256"], "manifest file SHA-256"):
            raise ProbeAEvidenceError("Probe-A manifest file SHA-256 mismatch")


def build_admission(
    report: Mapping,
    *,
    evidence_root: str | Path,
    evidence_manifest_sha256: str,
    expected_git_commit: str,
) -> dict:
    """Return the sole admission-grade snapshot after full offline validation."""
    validate_probe_a_report(
        report,
        evidence_root=evidence_root,
        expected_git_commit=expected_git_commit,
    )
    body = {
        "schema": ADMISSION_SCHEMA,
        "protocol": PROTOCOL,
        "status": "pass",
        "git_commit": expected_git_commit,
        "evidence_manifest_sha256": _sha(evidence_manifest_sha256, "evidence_manifest_sha256"),
        "output_bridge": dict(report["output_bridge"]),
    }
    return {**body, "self_checksum": sha256_json(body)}


def validate_admission(payload: Mapping, *, expected_git_commit: str) -> None:
    """Validate the compact snapshot consumed by the bias-metric gate."""
    _exact_keys(payload, _ADMISSION_KEYS, "Probe-A admission")
    _checksum(payload, "Probe-A admission")
    if payload["schema"] != ADMISSION_SCHEMA or payload["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("Probe-A admission identity mismatch")
    if payload["status"] != "pass" or payload["git_commit"] != expected_git_commit:
        raise ProbeAEvidenceError("Probe-A admission status or Git commit mismatch")
    _sha(payload["evidence_manifest_sha256"], "evidence_manifest_sha256")
    bridge = _exact_keys(payload["output_bridge"], _BRIDGE_KEYS, "output_bridge")
    error = _finite_nonnegative(bridge["max_abs_error"], "output_bridge.max_abs_error")
    tolerance = _finite_nonnegative(bridge["tolerance"], "output_bridge.tolerance")
    if (
        bridge["representation"] != "raw_pseudobulk_approximation"
        or bridge["verdict"] != "pass"
        or error > tolerance
    ):
        raise ProbeAEvidenceError("Probe-A admission bridge failed")
