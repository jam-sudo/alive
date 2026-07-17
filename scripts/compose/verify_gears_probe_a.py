#!/usr/bin/env python
"""Offline verifier and sole admission publisher for GEARS Probe A."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from alive.compose.gears_probe_a import (
    ProbeAEvidenceError,
    build_admission,
    validate_evidence_manifest,
)
from alive.io import atomic_write_once
from alive.provenance import sha256_file


def _read_json(path: Path, *, expected_sha256: str, label: str) -> dict:
    if sha256_file(path) != expected_sha256:
        raise ProbeAEvidenceError(f"{label} file SHA-256 mismatch")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeAEvidenceError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProbeAEvidenceError(f"{label} must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    """Verify a complete evidence tree and publish one write-once admission."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--out-admission", required=True)
    args = parser.parse_args(argv)

    root = Path(args.evidence_root)
    report = _read_json(Path(args.report), expected_sha256=args.report_sha256, label="report")
    manifest = _read_json(
        Path(args.manifest), expected_sha256=args.manifest_sha256, label="evidence manifest"
    )
    validate_evidence_manifest(
        manifest,
        evidence_root=root,
        expected_git_commit=args.git_commit,
    )
    admission = build_admission(
        report,
        evidence_root=root,
        evidence_manifest_sha256=args.manifest_sha256,
        expected_git_commit=args.git_commit,
    )
    encoded = json.dumps(admission, indent=2, sort_keys=True, allow_nan=False) + "\n"
    atomic_write_once(args.out_admission, encoded)
    print(json.dumps({"schema": admission["schema"], "status": "OK"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
