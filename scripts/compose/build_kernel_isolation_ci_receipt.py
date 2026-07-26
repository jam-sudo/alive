#!/usr/bin/env python
"""Build the canonical COMPOSE Linux-isolation CI receipt from JUnit."""

from __future__ import annotations

import argparse
from pathlib import Path

from alive.compose.kernel_isolation_ci import (
    CI_PROOF_PROFILE_V2,
    build_kernel_isolation_ci_receipt,
    write_kernel_isolation_ci_receipt,
)
from alive.provenance import sha256_file, sha256_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--workflow", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--runner-os", required=True)
    parser.add_argument("--runner-architecture", required=True)
    parser.add_argument("--kernel-release", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Build, validate and write one CI receipt."""
    args = _parser().parse_args(argv)
    receipt = build_kernel_isolation_ci_receipt(
        junit_path=args.junit,
        workflow_path=args.workflow,
        repository=args.repository,
        head_sha=args.head_sha,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        runner_os=args.runner_os,
        runner_architecture=args.runner_architecture,
        kernel_release=args.kernel_release,
        proof_profile=CI_PROOF_PROFILE_V2,
    )
    write_kernel_isolation_ci_receipt(args.output, receipt)
    print(f"kernel_isolation_ci_receipt_sha256={sha256_json(receipt)}")
    print(f"kernel_isolation_ci_receipt_file_sha256={sha256_file(args.output)}")
    print(f"kernel_isolation_ci_receipt_self_checksum={receipt['self_checksum']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
