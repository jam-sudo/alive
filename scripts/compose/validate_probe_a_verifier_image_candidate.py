#!/usr/bin/env python
"""Validate one externally pinned Probe-A verifier image build candidate."""

from __future__ import annotations

import argparse

from alive.compose.verifier_image import load_verifier_image_candidate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--expected-git-commit", required=True)
    parser.add_argument("--expected-build-repository", required=True)
    parser.add_argument("--expected-build-workflow-ref", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    load_verifier_image_candidate(
        args.candidate,
        expected_sha256=args.candidate_sha256,
        expected_git_commit=args.expected_git_commit,
        expected_build_repository=args.expected_build_repository,
        expected_build_workflow_ref=args.expected_build_workflow_ref,
    )
    print(args.candidate_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
