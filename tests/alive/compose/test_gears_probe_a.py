"""Tests for the admission-grade GEARS Probe-A evidence contract."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from alive.compose.approximation_bias import (
    load_probe_a_evidence,
    validate_probe_a_evidence,
)
from alive.compose.gears_probe_a import (
    ADMISSION_SCHEMA,
    MANIFEST_SCHEMA,
    PROTOCOL,
    REPORT_SCHEMA,
    ProbeAEvidenceError,
    assert_report_samples_manifested,
    build_admission,
    validate_admission,
    validate_evidence_manifest,
    validate_probe_a_report,
)
from alive.provenance import sha256_file, sha256_json

SHA = "a" * 64
COMMIT = "b" * 40

_REPO = Path(__file__).resolve().parents[3]
_VERIFY = _REPO / "scripts/compose/verify_gears_probe_a.py"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_gears_probe_a", _VERIFY)
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_gears_probe_a"] = module
    spec.loader.exec_module(module)
    return module


def _file_entry(root, relpath):
    path = root / relpath
    return {"path": relpath, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _manifest(root, *, files):
    body = {
        "schema": MANIFEST_SCHEMA,
        "protocol": PROTOCOL,
        "git_commit": COMMIT,
        "files": files,
    }
    return {**body, "manifest_checksum": sha256_json(body)}


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


def test_report_rejects_symlinked_raw_sample(tmp_path):
    report = _report(tmp_path)
    (tmp_path / "target.json").write_text("payload\n", encoding="utf-8")
    (tmp_path / "link.json").symlink_to(tmp_path / "target.json")
    report["raw_samples"] = [{"path": "link.json", "sha256": SHA}]
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="symlink"):
        validate_probe_a_report(report, evidence_root=tmp_path, expected_git_commit=COMMIT)


def test_output_scale_non_numeric_fails_cleanly(tmp_path):
    report = _report(tmp_path)
    report["output_scale"]["median"] = None
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="output_scale.median"):
        validate_probe_a_report(report, evidence_root=tmp_path, expected_git_commit=COMMIT)


def test_output_scale_non_finite_fails_cleanly(tmp_path):
    report = _report(tmp_path)
    report["output_scale"]["maximum"] = float("inf")
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="output_scale.maximum must be finite"):
        validate_probe_a_report(report, evidence_root=tmp_path, expected_git_commit=COMMIT)


# --- admission <-> consumer contract (the integration that guards seal use) ---


def test_admission_round_trips_through_the_real_consumer_gate(tmp_path):
    report = _report(tmp_path)
    admission = build_admission(
        report,
        evidence_root=tmp_path,
        evidence_manifest_sha256="9" * 64,
        expected_git_commit=COMMIT,
    )
    # The sole gate that admits the bias measurement must accept what we emit.
    validate_probe_a_evidence(admission, expected_git_commit=COMMIT)
    # And through the byte-bound loader the measurement script actually uses.
    path = tmp_path / "admission.json"
    path.write_text(json.dumps(admission) + "\n", encoding="utf-8")
    load_probe_a_evidence(path, expected_git_commit=COMMIT)


def test_build_admission_rejects_non_hex_git_commit(tmp_path):
    report = _report(tmp_path)
    report["git_commit"] = "g" * 40
    _resign(report)
    with pytest.raises(ProbeAEvidenceError, match="git_commit"):
        build_admission(
            report,
            evidence_root=tmp_path,
            evidence_manifest_sha256="9" * 64,
            expected_git_commit="g" * 40,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda a: a.update(status="failed"), "NOT_ADMISSIBLE"),
        (lambda a: a.update(schema="wrong_schema"), "schema"),
        (lambda a: a.update(git_commit="c" * 40), "does not match"),
        (lambda a: a["output_bridge"].update(verdict="fail"), "verdict"),
        (lambda a: a.update(self_checksum="0" * 64), "self_checksum"),
    ],
)
def test_validate_admission_rejects_each_forgery(tmp_path, mutate, message):
    report = _report(tmp_path)
    admission = build_admission(
        report,
        evidence_root=tmp_path,
        evidence_manifest_sha256="9" * 64,
        expected_git_commit=COMMIT,
    )
    mutate(admission)
    with pytest.raises(ProbeAEvidenceError, match=message):
        validate_admission(admission, expected_git_commit=COMMIT)


# --- manifest validation + report<->manifest binding ---


def test_validate_evidence_manifest_accepts_a_consistent_roster(tmp_path):
    _report(tmp_path)  # creates raw.json under the evidence root
    manifest = _manifest(tmp_path, files=[_file_entry(tmp_path, "raw.json")])
    validate_evidence_manifest(manifest, evidence_root=tmp_path, expected_git_commit=COMMIT)


def _resign_manifest(manifest):
    body = {key: value for key, value in manifest.items() if key != "manifest_checksum"}
    manifest["manifest_checksum"] = sha256_json(body)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda m: m.update(schema="wrong"), "identity mismatch"),
        (lambda m: m.update(files=[]), "roster is empty"),
        (lambda m: m["files"][0].update(bytes=m["files"][0]["bytes"] + 1), "byte count mismatch"),
        (lambda m: m["files"][0].update(bytes="5"), "byte count must be an integer"),
        (lambda m: m["files"].append(dict(m["files"][0])), "path is duplicated"),
    ],
)
def test_validate_evidence_manifest_fails_closed(tmp_path, mutate, message):
    _report(tmp_path)
    manifest = _manifest(tmp_path, files=[_file_entry(tmp_path, "raw.json")])
    mutate(manifest)
    _resign_manifest(manifest)
    with pytest.raises(ProbeAEvidenceError, match=message):
        validate_evidence_manifest(manifest, evidence_root=tmp_path, expected_git_commit=COMMIT)


def test_validate_evidence_manifest_rejects_checksum_tamper(tmp_path):
    _report(tmp_path)
    manifest = _manifest(tmp_path, files=[_file_entry(tmp_path, "raw.json")])
    manifest["manifest_checksum"] = "0" * 64  # not re-signed
    with pytest.raises(ProbeAEvidenceError, match="checksum mismatch"):
        validate_evidence_manifest(manifest, evidence_root=tmp_path, expected_git_commit=COMMIT)


def test_binding_requires_report_samples_in_manifest(tmp_path):
    report = _report(tmp_path)
    good = _manifest(tmp_path, files=[_file_entry(tmp_path, "raw.json")])
    assert_report_samples_manifested(report, good)  # no raise

    (tmp_path / "other.json").write_text("other\n", encoding="utf-8")
    absent = _manifest(tmp_path, files=[_file_entry(tmp_path, "other.json")])
    with pytest.raises(ProbeAEvidenceError, match="absent from the evidence manifest"):
        assert_report_samples_manifested(report, absent)

    wrong_sha = _manifest(
        tmp_path,
        files=[{"path": "raw.json", "sha256": SHA, "bytes": 1}],
    )
    with pytest.raises(ProbeAEvidenceError, match="disagrees with the evidence manifest"):
        assert_report_samples_manifested(report, wrong_sha)


# --- verifier CLI end to end ---


def _write_cli_inputs(tmp_path, *, manifest_relpaths):
    report = _report(tmp_path)  # creates raw.json under the evidence root
    manifest = _manifest(tmp_path, files=[_file_entry(tmp_path, rel) for rel in manifest_relpaths])
    report_path = tmp_path / "report.json"
    manifest_path = tmp_path / "manifest.json"
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    out = tmp_path / "admission.json"
    argv = [
        "--evidence-root",
        str(tmp_path),
        "--report",
        str(report_path),
        "--report-sha256",
        sha256_file(report_path),
        "--manifest",
        str(manifest_path),
        "--manifest-sha256",
        sha256_file(manifest_path),
        "--git-commit",
        COMMIT,
        "--out-admission",
        str(out),
    ]
    return argv, out


def test_cli_publishes_a_consumer_valid_admission(tmp_path):
    argv, out = _write_cli_inputs(tmp_path, manifest_relpaths=["raw.json"])
    verify = _load_verifier()
    assert verify.main(argv) == 0
    admission = json.loads(out.read_text(encoding="utf-8"))
    # Round-trip proof: what the CLI publishes is exactly what the seal gate admits.
    validate_probe_a_evidence(admission, expected_git_commit=COMMIT)
    assert admission["evidence_manifest_sha256"] == sha256_file(tmp_path / "manifest.json")


def test_cli_rejects_report_sample_outside_the_manifest(tmp_path):
    (tmp_path / "other.json").write_text("other\n", encoding="utf-8")
    argv, out = _write_cli_inputs(tmp_path, manifest_relpaths=["other.json"])
    verify = _load_verifier()
    with pytest.raises(ProbeAEvidenceError, match="absent from the evidence manifest"):
        verify.main(argv)
    assert not out.exists()


def test_cli_rejects_report_digest_mismatch(tmp_path):
    argv, out = _write_cli_inputs(tmp_path, manifest_relpaths=["raw.json"])
    argv[argv.index("--report-sha256") + 1] = "0" * 64
    verify = _load_verifier()
    with pytest.raises(ProbeAEvidenceError, match="SHA-256 mismatch"):
        verify.main(argv)
    assert not out.exists()


def test_cli_rejects_unparseable_report(tmp_path):
    argv, out = _write_cli_inputs(tmp_path, manifest_relpaths=["raw.json"])
    report_path = tmp_path / "report.json"
    report_path.write_text("not json\n", encoding="utf-8")  # digest re-pinned to matching bytes
    argv[argv.index("--report-sha256") + 1] = sha256_file(report_path)
    verify = _load_verifier()
    with pytest.raises(ProbeAEvidenceError, match="cannot parse"):
        verify.main(argv)
    assert not out.exists()
