#!/usr/bin/env python
"""Run the Probe-A verifier only from an owner-approved OCI manifest digest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from alive.compose.verifier_image import (
    VerifierImageLockError,
    canonical_json,
    load_verifier_image_lock,
    validate_verifier_signature_subject,
)

_DOCKERFILE = "containers/compose-probe-a-verifier/Dockerfile"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _executable(value: str, *, label: str) -> str:
    resolved = shutil.which(value) if os.sep not in value else value
    if not resolved:
        raise VerifierImageLockError(f"{label} executable is unavailable")
    path = Path(resolved).resolve(strict=True)
    if not path.is_file():
        raise VerifierImageLockError(f"{label} executable is not a regular file")
    return str(path)


def _assert_clean_commit(repository: Path, expected_commit: str) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if head != expected_commit or status:
        raise VerifierImageLockError("launcher checkout is not the clean owner-approved commit")


def _cosign_command(
    cosign: str, lock: dict, subject: Path, bundle: Path, trusted_root: Path
) -> list[str]:
    signature = lock["signature"]
    return [
        cosign,
        "verify-blob",
        str(subject),
        "--offline",
        "--bundle",
        str(bundle),
        "--trusted-root",
        str(trusted_root),
        "--certificate-identity",
        signature["certificate_identity"],
        "--certificate-oidc-issuer",
        signature["oidc_issuer"],
    ]


def _inspect_command(engine: str, lock: dict) -> list[str]:
    return [
        engine,
        "image",
        "inspect",
        "--format",
        "{{json .RepoDigests}}",
        lock["image_reference"],
    ]


def _container_command(args: argparse.Namespace, *, engine: str, lock: dict) -> list[str]:
    root = Path(args.evidence_root).resolve(strict=True)
    if Path(args.evidence_root).is_symlink() or not root.is_dir() or "," in str(root):
        raise VerifierImageLockError(
            "evidence root must be a real directory whose path contains no comma"
        )
    mount = f"type=bind,src={root},dst=/evidence"
    return [
        engine,
        "run",
        "--rm",
        "--pull=never",
        "--platform",
        lock["platform"],
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--pids-limit=256",
        "--memory=8g",
        "--cpus=4",
        "--user",
        "65532:65532",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=1g",
        "--mount",
        mount,
        "--env",
        f"ALIVE_VERIFIER_IMAGE_DIGEST={lock['image_manifest_digest']}",
        lock["image_reference"],
        "--evidence-root",
        "/evidence",
        "--report",
        "/evidence/probe_a.json",
        "--report-sha256",
        args.report_sha256,
        "--registration",
        "/evidence/probe_a_registration.json",
        "--registration-sha256",
        args.registration_sha256,
        "--manifest",
        "/evidence/manifest.json",
        "--manifest-sha256",
        args.manifest_sha256,
        "--provider-attestation-sha256",
        args.provider_attestation_sha256,
        "--payload-sha256",
        args.payload_sha256,
        "--roster-receipt-sha256",
        args.roster_receipt_sha256,
        "--git-commit",
        args.git_commit,
        "--expected-verifier-code-sha256",
        args.expected_verifier_code_sha256,
        "--verifier-image-digest",
        lock["image_manifest_digest"],
        "--verifier-image-lock-sha256",
        args.image_lock_sha256,
        "--out-admission",
        "/evidence/probe_a_admission.json",
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default="docker")
    parser.add_argument("--cosign", default="cosign")
    parser.add_argument("--image-lock", required=True)
    parser.add_argument("--image-lock-sha256", required=True)
    parser.add_argument("--cosign-bundle", required=True)
    parser.add_argument("--cosign-subject", required=True)
    parser.add_argument("--cosign-trusted-root", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--registration-sha256", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--provider-attestation-sha256", required=True)
    parser.add_argument("--payload-sha256", required=True)
    parser.add_argument("--roster-receipt-sha256", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--expected-verifier-code-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Verify signature/local identity, then run the pinned image without network."""
    args = _parser().parse_args(argv)
    repository = Path(__file__).resolve().parents[2]
    _assert_clean_commit(repository, args.git_commit)
    lock = load_verifier_image_lock(
        args.image_lock,
        expected_sha256=args.image_lock_sha256,
        expected_git_commit=args.git_commit,
        expected_verifier_code_sha256=args.expected_verifier_code_sha256,
    )
    if _sha256_file(repository / _DOCKERFILE) != lock["dockerfile_sha256"]:
        raise VerifierImageLockError("current Dockerfile differs from the owner image lock")
    if _sha256_file(repository / "uv.lock") != lock["uv_lock_sha256"]:
        raise VerifierImageLockError("current uv.lock differs from the owner image lock")

    bundle = Path(args.cosign_bundle)
    if bundle.is_symlink() or not bundle.resolve(strict=True).is_file():
        raise VerifierImageLockError("Cosign bundle must be a real regular file")
    if _sha256_file(bundle) != lock["signature"]["bundle_sha256"]:
        raise VerifierImageLockError("Cosign bundle differs from the owner image lock")
    subject = Path(args.cosign_subject)
    if subject.is_symlink() or not subject.resolve(strict=True).is_file():
        raise VerifierImageLockError("Cosign signature subject must be a real regular file")
    subject_bytes = subject.read_bytes()
    if _sha256_file(subject) != lock["signature"]["subject_sha256"]:
        raise VerifierImageLockError("Cosign signature subject differs from the owner image lock")
    try:
        subject_payload = json.loads(subject_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifierImageLockError("cannot parse Cosign signature subject") from exc
    if (
        not isinstance(subject_payload, dict)
        or subject_bytes != (canonical_json(subject_payload) + "\n").encode()
    ):
        raise VerifierImageLockError(
            "Cosign signature subject must be canonical JSON with final LF"
        )
    validate_verifier_signature_subject(subject_payload, expected_lock=lock)
    cosign = _executable(args.cosign, label="Cosign")
    if _sha256_file(Path(cosign)) != lock["signature"]["cosign_executable_sha256"]:
        raise VerifierImageLockError("Cosign executable differs from the owner image lock")
    trusted_root = Path(args.cosign_trusted_root)
    if trusted_root.is_symlink() or not trusted_root.resolve(strict=True).is_file():
        raise VerifierImageLockError("Sigstore trusted root must be a real regular file")
    if _sha256_file(trusted_root) != lock["signature"]["trusted_root_sha256"]:
        raise VerifierImageLockError("Sigstore trusted root differs from the owner image lock")
    engine = _executable(args.engine, label="OCI engine")
    subprocess.run(
        _cosign_command(
            cosign,
            lock,
            subject.resolve(),
            bundle.resolve(),
            trusted_root.resolve(),
        ),
        check=True,
    )
    inspected = subprocess.run(
        _inspect_command(engine, lock),
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        repo_digests = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise VerifierImageLockError("OCI engine returned invalid RepoDigests JSON") from exc
    if not isinstance(repo_digests, list) or lock["image_reference"] not in repo_digests:
        raise VerifierImageLockError(
            "local OCI image does not carry the owner-pinned manifest digest"
        )
    subprocess.run(_container_command(args, engine=engine, lock=lock), check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
