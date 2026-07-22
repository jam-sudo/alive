#!/usr/bin/env python
"""Build the canonical blob signed to approve one Probe-A verifier image."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from alive.compose.verifier_image import build_verifier_signature_subject, canonical_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--image-reference", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--python-base-image", required=True)
    parser.add_argument("--uv-build-image", required=True)
    parser.add_argument("--dockerfile-sha256", required=True)
    parser.add_argument("--uv-lock-sha256", required=True)
    parser.add_argument("--verifier-code-sha256", required=True)
    parser.add_argument("--owner-approval-sha256", required=True)
    parser.add_argument("--owner-signature-sha256", required=True)
    parser.add_argument("--owner-key-fingerprint", required=True)
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    subject = build_verifier_signature_subject(
        git_commit=args.git_commit,
        image_reference=args.image_reference,
        platform=args.platform,
        python_base_image=args.python_base_image,
        uv_build_image=args.uv_build_image,
        dockerfile_sha256=args.dockerfile_sha256,
        uv_lock_sha256=args.uv_lock_sha256,
        verifier_code_sha256=args.verifier_code_sha256,
        owner_approval_sha256=args.owner_approval_sha256,
        owner_signature_sha256=args.owner_signature_sha256,
        owner_key_fingerprint=args.owner_key_fingerprint,
    )
    data = (canonical_json(subject) + "\n").encode()
    output = Path(args.out)
    if output.is_symlink():
        raise ValueError("verifier signature subject output must not be a symlink")
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
