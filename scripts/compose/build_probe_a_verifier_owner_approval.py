#!/usr/bin/env python
"""Build one canonical statement for offline owner approval of a verifier candidate."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from alive.compose.verifier_image import (
    build_verifier_owner_approval,
    canonical_json,
    load_verifier_image_candidate,
    owner_public_key_identity,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--expected-git-commit", required=True)
    parser.add_argument("--expected-build-repository", required=True)
    parser.add_argument("--expected-build-workflow-ref", required=True)
    parser.add_argument("--owner-public-key", required=True)
    parser.add_argument("--approved-at-utc", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    candidate = load_verifier_image_candidate(
        args.candidate,
        expected_sha256=args.candidate_sha256,
        expected_git_commit=args.expected_git_commit,
        expected_build_repository=args.expected_build_repository,
        expected_build_workflow_ref=args.expected_build_workflow_ref,
    )
    key = owner_public_key_identity(args.owner_public_key)
    approval = build_verifier_owner_approval(
        candidate=candidate,
        candidate_sha256=args.candidate_sha256,
        approved_at_utc=args.approved_at_utc,
        approval_id=args.approval_id,
        owner_key_fingerprint=key["public_key_fingerprint"],
    )
    data = (canonical_json(approval) + "\n").encode("utf-8")
    output = Path(args.out)
    if output.is_symlink():
        raise ValueError("verifier owner approval output must not be a symlink")
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
