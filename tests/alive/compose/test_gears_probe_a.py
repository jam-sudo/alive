"""Tests for the admission-grade GEARS Probe-A evidence contract."""

from __future__ import annotations

import json

import pytest

from alive.compose.gears_probe_a import (
    ADMISSION_SCHEMA,
    PROTOCOL,
    REPORT_SCHEMA,
    ProbeAEvidenceError,
    build_admission,
    validate_admission,
    validate_probe_a_report,
)
from alive.provenance import sha256_file, sha256_json

SHA = "a" * 64
COMMIT = "b" * 40


def _report(tmp_path):
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps({"samples": [1, 2, 3]}) + "\n", encoding="utf-8")
    body = {
        "schema": REPORT_SCHEMA,
        "protocol": PROTOCOL,
        "status": "pass",
        "git_commit": COMMIT,
        "runtime_sha256": SHA,
        "input_manifest_sha256": "c" * 64,
        "source_fingerprint_sha256": "d" * 64,
        "input_scale": {
            "before_sha256": "e" * 64,
            "after_sha256": "e" * 64,
            "exact_equal": True,
            "normalization_target": 10000.0,
            "transform": "full_library_normalize_log1p_then_roster_subset",
        },
        "determinism": {
            "checkpoint_sha256": ["f" * 64, "f" * 64],
            "prediction_sha256": ["1" * 64, "1" * 64],
            "max_abs_error": 0.0,
            "tolerance": 1e-7,
            "verdict": "pass",
        },
        "control_count": {
            "counts": [1, 8, 300, 301, 400],
            "prediction_sha256": [str(i) * 64 for i in range(2, 7)],
            "first_300_max_abs_error": 0.0,
            "tolerance": 1e-7,
            "verdict": "pass",
        },
        "output_scale": {
            "minimum": -0.2,
            "median": 1.0,
            "maximum": 2.0,
            "negative_fraction": 0.1,
            "near_integer_fraction": 0.0,
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


def _resign(report):
    body = {key: value for key, value in report.items() if key != "self_checksum"}
    report["self_checksum"] = sha256_json(body)


def test_report_promotes_to_bias_gate_compatible_admission(tmp_path):
    report = _report(tmp_path)
    validate_probe_a_report(report, evidence_root=tmp_path, expected_git_commit=COMMIT)
    admission = build_admission(
        report,
        evidence_root=tmp_path,
        evidence_manifest_sha256="9" * 64,
        expected_git_commit=COMMIT,
    )
    assert admission["schema"] == ADMISSION_SCHEMA
    validate_admission(admission, expected_git_commit=COMMIT)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r["input_scale"].update(exact_equal=False), "input scale"),
        (
            lambda r: r["determinism"].update(checkpoint_sha256=["f" * 64, "0" * 64]),
            "determinism",
        ),
        (lambda r: r["control_count"].update(counts=[1, 8, 300]), "control-count roster"),
        (
            lambda r: r["output_bridge"].update(max_abs_error=2e-7),
            "output-bridge equivalence",
        ),
    ],
)
def test_report_fails_closed_on_scientific_gate_mutation(tmp_path, mutate, message):
    report = _report(tmp_path)
    mutate(report)
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match=message):
        validate_probe_a_report(report, evidence_root=tmp_path, expected_git_commit=COMMIT)


def test_report_rejects_raw_sample_tamper_and_path_escape(tmp_path):
    report = _report(tmp_path)
    (tmp_path / "raw.json").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ProbeAEvidenceError, match="raw sample SHA-256"):
        validate_probe_a_report(report, evidence_root=tmp_path, expected_git_commit=COMMIT)

    report = _report(tmp_path)
    report["raw_samples"][0]["path"] = "../raw.json"
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="safe and relative"):
        validate_probe_a_report(report, evidence_root=tmp_path, expected_git_commit=COMMIT)


def test_report_rejects_unknown_fields_even_with_valid_checksum(tmp_path):
    report = _report(tmp_path)
    report["posthoc_override"] = True
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="keys differ"):
        validate_probe_a_report(report, evidence_root=tmp_path, expected_git_commit=COMMIT)
