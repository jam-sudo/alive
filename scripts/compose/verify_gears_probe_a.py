#!/usr/bin/env python
"""Offline verifier for GEARS Probe A and sole publisher of passing admissions."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import site
import sys
from pathlib import Path


def _bootstrap_runtime_identity() -> None:
    """Reject import shadowing before any decision-bearing package is imported."""
    repository = Path(__file__).resolve().parents[2]
    if os.environ.get("PYTHONPATH"):
        raise RuntimeError("offline verifier forbids PYTHONPATH import overrides")
    if site.ENABLE_USER_SITE:
        raise RuntimeError("offline verifier requires user site-packages to be disabled")

    expected_alive = (repository / "src/alive/__init__.py").resolve(strict=True)
    alive_spec = importlib.util.find_spec("alive")
    if alive_spec is None or alive_spec.origin is None:
        raise RuntimeError("offline verifier cannot resolve the maintained alive package")
    if Path(alive_spec.origin).resolve(strict=True) != expected_alive:
        raise RuntimeError("offline verifier alive import does not originate from this checkout")

    environment_root = Path(sys.prefix).resolve(strict=True)
    for module_name in ("anndata", "h5py", "numpy", "pandas", "scipy"):
        spec = importlib.util.find_spec(module_name)
        if spec is None or spec.origin is None:
            raise RuntimeError(f"offline verifier cannot resolve required module {module_name}")
        origin = Path(spec.origin)
        if origin.is_symlink():
            raise RuntimeError(f"offline verifier module {module_name} must not be a symlink")
        resolved = origin.resolve(strict=True)
        if not resolved.is_file() or not resolved.is_relative_to(environment_root):
            raise RuntimeError(
                f"offline verifier module {module_name} is outside the active environment"
            )


_bootstrap_runtime_identity()


def _verifier_code_sha256() -> str:
    """Hash source, locks, and the active verifier dependency identity."""
    repository = Path(__file__).resolve().parents[2]
    entrypoints = (
        "scripts/compose/verify_gears_probe_a.py",
        "scripts/compose/gears_decision_probe.py",
        "scripts/baselines/gears_worker.py",
    )
    alive_sources = tuple(
        path.relative_to(repository).as_posix()
        for path in sorted((repository / "src/alive").rglob("*.py"))
    )
    closure = (*entrypoints, "pyproject.toml", "uv.lock", *alive_sources)
    try:
        source_files = {
            relative: hashlib.sha256((repository / relative).read_bytes()).hexdigest()
            for relative in closure
        }
        environment_root = Path(sys.prefix).resolve(strict=True)
        distributions: dict[str, object] = {}
        installed_distributions = list(importlib.metadata.distributions())
        if not installed_distributions:
            raise RuntimeError("verifier environment exposes no installed distributions")
        for distribution in installed_distributions:
            declared_name = distribution.metadata.get("Name")
            if not isinstance(declared_name, str) or not declared_name:
                raise RuntimeError("verifier environment contains an unnamed distribution")
            name = declared_name.lower().replace("_", "-").replace(".", "-")
            while "--" in name:
                name = name.replace("--", "-")
            if name in distributions:
                raise RuntimeError(f"verifier environment contains duplicate distribution {name}")
            files = distribution.files
            if not files:
                raise RuntimeError(
                    f"verifier dependency {name} exposes no installed-file inventory"
                )
            installed_files: dict[str, str] = {}
            for relative in files:
                relative_path = Path(relative)
                if relative_path.suffix == ".pyc" or "__pycache__" in relative_path.parts:
                    continue
                candidate = Path(distribution.locate_file(relative))
                if candidate.is_symlink():
                    raise RuntimeError(f"verifier dependency {name} contains a symlink: {relative}")
                resolved = candidate.resolve(strict=True)
                if not resolved.is_file() or not resolved.is_relative_to(environment_root):
                    detail = f"{name} file escapes the active environment: {relative}"
                    raise RuntimeError(f"verifier dependency {detail}")
                installed_relative = resolved.relative_to(environment_root).as_posix()
                if installed_relative in installed_files:
                    raise RuntimeError(
                        f"verifier dependency {name} has a duplicate installed path: {relative}"
                    )
                installed_files[installed_relative] = hashlib.sha256(
                    resolved.read_bytes()
                ).hexdigest()
            if not installed_files:
                raise RuntimeError(f"verifier dependency {name} has no hashable installed files")
            distributions[name] = {
                "files": installed_files,
                "version": distribution.version,
            }
        python_executable = Path(sys.executable).resolve(strict=True)
        runtime = {
            "distributions": distributions,
            "python": {
                "cache_tag": sys.implementation.cache_tag,
                "executable_sha256": hashlib.sha256(python_executable.read_bytes()).hexdigest(),
                "version": sys.version,
            },
        }
        canonical = json.dumps(
            {"runtime": runtime, "source_files": source_files},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
    except (OSError, importlib.metadata.PackageNotFoundError) as exc:
        raise RuntimeError(f"cannot hash verifier source closure: {exc}") from exc


def _bootstrap_expected_verifier_pin(argv: list[str]) -> None:
    """Authenticate the complete closure before importing decision-bearing code."""
    if "-h" in argv or "--help" in argv:
        return
    option = "--expected-verifier-code-sha256"
    if argv.count(option) != 1:
        raise RuntimeError(f"offline verifier requires exactly one {option}")
    index = argv.index(option)
    if index + 1 >= len(argv):
        raise RuntimeError(f"offline verifier requires a value for {option}")
    expected = argv[index + 1]
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise RuntimeError(f"offline verifier {option} must be one lowercase SHA-256")
    if _verifier_code_sha256() != expected:
        raise RuntimeError(
            "verifier source/runtime closure differs from the independently reviewed pre-run pin"
        )
    image_option = "--verifier-image-digest"
    if argv.count(image_option) != 1 or argv.index(image_option) + 1 >= len(argv):
        raise RuntimeError(f"offline verifier requires exactly one {image_option}")
    image_digest = argv[argv.index(image_option) + 1]
    if (
        len(image_digest) != 71
        or not image_digest.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in image_digest[7:])
    ):
        raise RuntimeError("offline verifier image digest is malformed")
    if os.environ.get("ALIVE_VERIFIER_IMAGE_DIGEST") != image_digest:
        raise RuntimeError("offline verifier image digest differs from the launcher boundary")

    commit_option = "--git-commit"
    if argv.count(commit_option) != 1 or argv.index(commit_option) + 1 >= len(argv):
        raise RuntimeError(f"offline verifier requires exactly one {commit_option}")
    expected_commit = argv[argv.index(commit_option) + 1]
    baked_commit_path = Path(__file__).resolve().parents[2] / ".alive-verifier-git-commit"
    try:
        baked_commit = baked_commit_path.read_text(encoding="ascii")
    except OSError as exc:
        raise RuntimeError("operational verifier must run from its baked OCI image") from exc
    if baked_commit != f"{expected_commit}\n":
        raise RuntimeError("baked verifier commit differs from the owner-approved Git commit")


if __name__ == "__main__" and sys.argv[1:] == ["--print-verifier-code-sha256"]:
    print(_verifier_code_sha256())
    raise SystemExit(0)

if __name__ == "__main__":
    _bootstrap_expected_verifier_pin(sys.argv[1:])


from alive.compose.approximation_bias import canonical_file_bytes  # noqa: E402
from alive.compose.gears_probe_a import (  # noqa: E402
    ADMISSION_PATH,
    MANIFEST_PATH,
    REGISTRATION_PATH,
    REPORT_PATH,
    VERIFY_PATH,
    ProbeAEvidenceError,
    assert_clean_approved_checkout,
    build_evidence_outputs,
)
from alive.io import atomic_write_once  # noqa: E402
from alive.provenance import sha256_bytes  # noqa: E402


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


def _assert_approved_source(expected_git_commit: str) -> None:
    """Accept either a clean checkout or the commit baked into the pinned image."""
    repository = Path(__file__).resolve().parents[2]
    baked = repository / ".alive-verifier-git-commit"
    if baked.exists():
        if baked.is_symlink() or baked.read_text(encoding="ascii") != f"{expected_git_commit}\n":
            raise ProbeAEvidenceError("baked verifier Git commit differs from the owner pin")
        return
    assert_clean_approved_checkout(expected_git_commit)


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
    parser.add_argument(
        "--provider-attestation-sha256",
        required=True,
        help="independently recorded pre-run SHA-256 of provider_runtime_attestation.json",
    )
    parser.add_argument(
        "--payload-sha256",
        required=True,
        help="externally recorded pre-fit SHA-256 of upstream/payload.json",
    )
    parser.add_argument(
        "--roster-receipt-sha256",
        required=True,
        help="externally recorded pre-prepare SHA-256 of the selected roster receipt",
    )
    parser.add_argument("--git-commit", required=True)
    parser.add_argument(
        "--expected-verifier-code-sha256",
        required=True,
        help="independently reviewed pre-run SHA-256 of the verifier source closure",
    )
    parser.add_argument(
        "--verifier-image-digest",
        required=True,
        help="owner-pinned platform-specific OCI manifest digest",
    )
    parser.add_argument(
        "--verifier-image-lock-sha256",
        required=True,
        help="external SHA-256 of the signed verifier image lock",
    )
    parser.add_argument("--out-admission", required=True)
    args = parser.parse_args(argv)

    _assert_approved_source(args.git_commit)

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
        provider_attestation_sha256=args.provider_attestation_sha256,
        payload_sha256=args.payload_sha256,
        roster_receipt_sha256=args.roster_receipt_sha256,
        verifier_image_digest=args.verifier_image_digest,
        verifier_image_lock_sha256=args.verifier_image_lock_sha256,
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
