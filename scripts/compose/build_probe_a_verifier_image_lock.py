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
    VERIFIER_IMAGE_LOCK_SCHEMA,
    VERIFIER_IMAGE_SIGNATURE_SCHEMA,
    canonical_json,
    self_checksum,
    validate_verifier_image_lock,
    validate_verifier_signature_subject,
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
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--image-reference", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--python-base-image", required=True)
    parser.add_argument("--uv-build-image", required=True)
    parser.add_argument("--dockerfile", required=True)
    parser.add_argument("--uv-lock", required=True)
    parser.add_argument("--verifier-code-sha256", required=True)
    parser.add_argument("--cosign-bundle", required=True)
    parser.add_argument("--cosign-subject", required=True)
    parser.add_argument("--cosign-executable", required=True)
    parser.add_argument("--trusted-root", required=True)
    parser.add_argument("--certificate-identity", required=True)
    parser.add_argument("--oidc-issuer", required=True)
    parser.add_argument("--approved-at-utc", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--out", required=True)
    return parser


def build_lock(args: argparse.Namespace) -> dict[str, object]:
    """Construct and validate one exact lock mapping from immutable inputs."""
    image_digest = args.image_reference.rsplit("@", 1)[-1]
    lock: dict[str, object] = {
        "schema": VERIFIER_IMAGE_LOCK_SCHEMA,
        "protocol": "COMPOSE-K562-v1",
        "git_commit": args.git_commit,
        "image_reference": args.image_reference,
        "image_manifest_digest": image_digest,
        "platform": args.platform,
        "python_base_image": args.python_base_image,
        "uv_build_image": args.uv_build_image,
        "dockerfile_sha256": _sha256_file(args.dockerfile),
        "uv_lock_sha256": _sha256_file(args.uv_lock),
        "verifier_code_sha256": args.verifier_code_sha256,
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
        "approved_at_utc": args.approved_at_utc,
        "approval_id": args.approval_id,
        "self_checksum": "",
    }
    lock["self_checksum"] = self_checksum(lock)
    validated = validate_verifier_image_lock(
        lock,
        expected_git_commit=args.git_commit,
        expected_verifier_code_sha256=args.verifier_code_sha256,
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
