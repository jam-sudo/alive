#!/usr/bin/env python
"""Offline verifier for GEARS Probe A and sole publisher of passing admissions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from alive.compose.approximation_bias import canonical_file_bytes
from alive.compose.gears_probe_a import (
    ADMISSION_PATH,
    MANIFEST_PATH,
    REGISTRATION_PATH,
    REPORT_PATH,
    VERIFY_PATH,
    ProbeAEvidenceError,
    assert_clean_approved_checkout,
    build_evidence_outputs,
)
from alive.io import atomic_write_once
from alive.provenance import sha256_bytes, sha256_json


def _read_bytes(path: Path, *, label: str) -> bytes:
    """Capture one immutable snapshot; the contract hashes and parses these bytes."""
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ProbeAEvidenceError(f"cannot read {label}: {exc}") from exc


def _pinned_input_path(root: Path, supplied: str, expected_relative: str, label: str) -> Path:
    path = Path(supplied)
    if path.is_symlink():
        raise ProbeAEvidenceError(f"{label} must not be a symlink")
    try:
        actual = path.resolve(strict=True)
        expected = (root / expected_relative).resolve(strict=True)
    except OSError as exc:
        raise ProbeAEvidenceError(f"{label} is missing or unreadable") from exc
    if actual != expected or not actual.is_file():
        raise ProbeAEvidenceError(f"{label} must be {expected_relative} under evidence root")
    return actual


def _pinned_output_path(root: Path, supplied: str) -> Path:
    path = Path(supplied)
    if path.is_symlink():
        raise ProbeAEvidenceError("admission output must not be a symlink")
    actual = path.resolve(strict=False)
    expected = (root / ADMISSION_PATH).resolve(strict=False)
    if actual != expected:
        raise ProbeAEvidenceError(f"admission output must be {ADMISSION_PATH} under evidence root")
    if path.exists():
        raise ProbeAEvidenceError("fresh evidence root already contains an admission output")
    return actual


def _verifier_code_sha256() -> str:
    """Hash the exact source closure that decides admission."""
    repository = Path(__file__).resolve().parents[2]
    closure = (
        "scripts/compose/verify_gears_probe_a.py",
        "src/alive/compose/gears_probe_a.py",
        "src/alive/compose/approximation_bias.py",
        # fit_role.row_identity_sha256 participates in the prepared-input admission decision.
        "src/alive/compose/fit_role.py",
        "src/alive/io.py",
        "src/alive/provenance.py",
    )
    try:
        return sha256_json(
            {relative: sha256_bytes((repository / relative).read_bytes()) for relative in closure}
        )
    except OSError as exc:
        raise ProbeAEvidenceError(f"cannot hash verifier source closure: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    """Publish one receipt; publish an admission only when every gate passes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--registration-sha256", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument(
        "--expected-verifier-code-sha256",
        required=True,
        help="independently reviewed pre-run SHA-256 of the verifier source closure",
    )
    parser.add_argument("--out-admission", required=True)
    args = parser.parse_args(argv)

    assert_clean_approved_checkout(args.git_commit)

    observed_verifier_code_sha256 = _verifier_code_sha256()
    if args.expected_verifier_code_sha256 != observed_verifier_code_sha256:
        raise ProbeAEvidenceError(
            "verifier source closure differs from the independently reviewed pre-run pin"
        )

    root_arg = Path(args.evidence_root)
    if root_arg.is_symlink():
        raise ProbeAEvidenceError("evidence root must not be a symlink")
    try:
        root = root_arg.resolve(strict=True)
    except OSError as exc:
        raise ProbeAEvidenceError("evidence root is missing or unreadable") from exc
    if not root.is_dir():
        raise ProbeAEvidenceError("evidence root must be a directory")

    report_path = _pinned_input_path(root, args.report, REPORT_PATH, "report")
    registration_path = _pinned_input_path(
        root, args.registration, REGISTRATION_PATH, "registration"
    )
    manifest_path = _pinned_input_path(root, args.manifest, MANIFEST_PATH, "evidence manifest")
    out_path = _pinned_output_path(root, args.out_admission)
    verify_path = root / VERIFY_PATH
    if verify_path.exists() or verify_path.is_symlink():
        raise ProbeAEvidenceError("fresh evidence root already contains verify.json")

    outputs = build_evidence_outputs(
        report_bytes=_read_bytes(report_path, label="report"),
        report_sha256=args.report_sha256,
        registration_bytes=_read_bytes(registration_path, label="registration"),
        registration_sha256=args.registration_sha256,
        manifest_bytes=_read_bytes(manifest_path, label="evidence manifest"),
        evidence_root=root,
        evidence_manifest_sha256=args.manifest_sha256,
        expected_git_commit=args.git_commit,
        verifier_code_sha256=observed_verifier_code_sha256,
    )
    atomic_write_once(verify_path, outputs.verification_bytes.decode("utf-8"))
    admission_bytes = (
        canonical_file_bytes(outputs.admission) if outputs.admission is not None else None
    )
    if admission_bytes is not None:
        atomic_write_once(out_path, admission_bytes.decode("utf-8"))
    print(
        json.dumps(
            {
                "admission_sha256": (
                    sha256_bytes(admission_bytes) if admission_bytes is not None else None
                ),
                "schema": (
                    outputs.admission["schema"]
                    if outputs.admission is not None
                    else outputs.verification["schema"]
                ),
                "status": "OK" if outputs.admission is not None else "NEGATIVE_RESULT",
                "verification_sha256": outputs.verification_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
