#!/usr/bin/env python
"""Verify one externally pinned owner approval and its detached Ed25519 signature."""

from __future__ import annotations

import argparse

from alive.compose.verifier_image import (
    load_verifier_image_candidate,
    load_verifier_owner_approval,
    owner_public_key_identity,
    verify_verifier_owner_approval_signature,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--expected-git-commit", required=True)
    parser.add_argument("--expected-build-repository", required=True)
    parser.add_argument("--expected-build-workflow-ref", required=True)
    parser.add_argument("--owner-approval", required=True)
    parser.add_argument("--owner-approval-sha256", required=True)
    parser.add_argument("--owner-signature", required=True)
    parser.add_argument("--owner-signature-sha256", required=True)
    parser.add_argument("--owner-public-key", required=True)
    parser.add_argument("--ssh-keygen", default="ssh-keygen")
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
    load_verifier_owner_approval(
        args.owner_approval,
        expected_sha256=args.owner_approval_sha256,
        expected_candidate=candidate,
        expected_candidate_sha256=args.candidate_sha256,
        expected_owner_key_fingerprint=key["public_key_fingerprint"],
    )
    evidence = verify_verifier_owner_approval_signature(
        statement=args.owner_approval,
        signature=args.owner_signature,
        public_key=args.owner_public_key,
        expected_statement_sha256=args.owner_approval_sha256,
        expected_signature_sha256=args.owner_signature_sha256,
        expected_public_key_sha256=key["public_key_sha256"],
        expected_owner_key_fingerprint=key["public_key_fingerprint"],
        ssh_keygen=args.ssh_keygen,
    )
    print(evidence["signature_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
