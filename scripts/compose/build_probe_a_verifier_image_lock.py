#!/usr/bin/env python
"""Build one canonical, write-once owner lock for a signed Probe-A verifier image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

from alive.compose.verifier_image import (
    OWNER_APPROVAL_MODE,
    OWNER_APPROVAL_NAMESPACE,
    VERIFIER_IMAGE_LOCK_SCHEMA,
    VERIFIER_IMAGE_OWNER_APPROVAL_EVIDENCE_SCHEMA,
    VERIFIER_IMAGE_SIGNATURE_SCHEMA,
    canonical_json,
    load_verifier_image_candidate,
    load_verifier_owner_approval,
    owner_public_key_identity,
    self_checksum,
    validate_verifier_image_lock,
    validate_verifier_signature_subject,
    verify_verifier_owner_approval_signature,
)


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError(f"owner lock input must not be a symlink: {candidate}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(candidate, flags)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError(f"owner lock input must be a regular file: {candidate}")
    with os.fdopen(descriptor, "rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--expected-git-commit", required=True)
    parser.add_argument("--expected-build-repository", required=True)
    parser.add_argument("--expected-build-workflow-ref", required=True)
    parser.add_argument("--dockerfile", required=True)
    parser.add_argument("--uv-lock", required=True)
    parser.add_argument("--owner-approval", required=True)
    parser.add_argument("--owner-approval-sha256", required=True)
    parser.add_argument("--owner-signature", required=True)
    parser.add_argument("--owner-signature-sha256", required=True)
    parser.add_argument("--owner-public-key", required=True)
    parser.add_argument("--expected-owner-key-fingerprint", required=True)
    parser.add_argument("--ssh-keygen-executable", required=True)
    parser.add_argument("--cosign-bundle", required=True)
    parser.add_argument("--cosign-subject", required=True)
    parser.add_argument("--cosign-executable", required=True)
    parser.add_argument("--trusted-root", required=True)
    parser.add_argument("--certificate-identity", required=True)
    parser.add_argument("--oidc-issuer", required=True)
    parser.add_argument("--out", required=True)
    return parser


def build_lock(args: argparse.Namespace) -> dict[str, object]:
    """Construct and validate one exact lock mapping from immutable inputs."""
    candidate = load_verifier_image_candidate(
        args.candidate,
        expected_sha256=args.candidate_sha256,
        expected_git_commit=args.expected_git_commit,
        expected_build_repository=args.expected_build_repository,
        expected_build_workflow_ref=args.expected_build_workflow_ref,
    )
    key = owner_public_key_identity(args.owner_public_key)
    if key["public_key_fingerprint"] != args.expected_owner_key_fingerprint:
        raise ValueError("owner public key differs from the external owner registration")
    approval = load_verifier_owner_approval(
        args.owner_approval,
        expected_sha256=args.owner_approval_sha256,
        expected_candidate=candidate,
        expected_candidate_sha256=args.candidate_sha256,
        expected_owner_key_fingerprint=args.expected_owner_key_fingerprint,
    )
    signature_evidence = verify_verifier_owner_approval_signature(
        statement=args.owner_approval,
        signature=args.owner_signature,
        public_key=args.owner_public_key,
        expected_statement_sha256=args.owner_approval_sha256,
        expected_signature_sha256=args.owner_signature_sha256,
        expected_public_key_sha256=key["public_key_sha256"],
        expected_owner_key_fingerprint=args.expected_owner_key_fingerprint,
        ssh_keygen=args.ssh_keygen_executable,
    )
    dockerfile_sha256 = _sha256_file(args.dockerfile)
    uv_lock_sha256 = _sha256_file(args.uv_lock)
    if dockerfile_sha256 != candidate["dockerfile_sha256"]:
        raise ValueError("Dockerfile differs from the owner-approved candidate")
    if uv_lock_sha256 != candidate["uv_lock_sha256"]:
        raise ValueError("uv.lock differs from the owner-approved candidate")
    lock: dict[str, object] = {
        "schema": VERIFIER_IMAGE_LOCK_SCHEMA,
        "protocol": "COMPOSE-K562-v1",
        "git_commit": candidate["git_commit"],
        "image_reference": candidate["image_reference"],
        "image_manifest_digest": candidate["image_manifest_digest"],
        "platform": candidate["platform"],
        "python_base_image": candidate["python_base_image"],
        "uv_build_image": candidate["uv_build_image"],
        "dockerfile_sha256": dockerfile_sha256,
        "uv_lock_sha256": uv_lock_sha256,
        "verifier_code_sha256": candidate["verifier_code_sha256"],
        "owner_approval": {
            "schema": VERIFIER_IMAGE_OWNER_APPROVAL_EVIDENCE_SCHEMA,
            "mode": OWNER_APPROVAL_MODE,
            "namespace": OWNER_APPROVAL_NAMESPACE,
            "candidate_sha256": args.candidate_sha256,
            "statement_sha256": args.owner_approval_sha256,
            "signature_sha256": args.owner_signature_sha256,
            "public_key_sha256": key["public_key_sha256"],
            "public_key_fingerprint": key["public_key_fingerprint"],
            "ssh_keygen_executable_sha256": signature_evidence["ssh_keygen_executable_sha256"],
            "build_run_id": candidate["build_run_id"],
        },
        "signature": {
            "schema": VERIFIER_IMAGE_SIGNATURE_SCHEMA,
            "mode": "cosign_keyless_subject_bundle_v1",
            "subject_sha256": _sha256_file(args.cosign_subject),
            "bundle_sha256": _sha256_file(args.cosign_bundle),
            "cosign_executable_sha256": _sha256_file(args.cosign_executable),
            "trusted_root_sha256": _sha256_file(args.trusted_root),
            "certificate_identity": args.certificate_identity,
            "oidc_issuer": args.oidc_issuer,
        },
        "approved_at_utc": approval["approved_at_utc"],
        "approval_id": approval["approval_id"],
        "self_checksum": "",
    }
    lock["self_checksum"] = self_checksum(lock)
    validated = validate_verifier_image_lock(
        lock,
        expected_git_commit=candidate["git_commit"],
        expected_verifier_code_sha256=candidate["verifier_code_sha256"],
        expected_owner_key_fingerprint=args.expected_owner_key_fingerprint,
    )
    subject_bytes = Path(args.cosign_subject).read_bytes()
    try:
        subject = json.loads(subject_bytes)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("cannot parse verifier signature subject") from exc
    if not isinstance(subject, dict) or subject_bytes != (canonical_json(subject) + "\n").encode():
        raise ValueError("verifier signature subject must be canonical JSON with final LF")
    validate_verifier_signature_subject(subject, expected_lock=validated)
    return validated


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.out)
    if output.is_symlink():
        raise ValueError("verifier image lock output must not be a symlink")
    data = (canonical_json(build_lock(args)) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(output, flags, 0o444)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    print(hashlib.sha256(data).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
