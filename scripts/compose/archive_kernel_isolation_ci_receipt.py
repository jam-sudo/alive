#!/usr/bin/env python
"""Archive a downloaded COMPOSE Linux-isolation CI artifact durably."""

from __future__ import annotations

import argparse
from pathlib import Path

from alive.compose.kernel_isolation_ci import (
    build_kernel_isolation_ci_archive,
    write_kernel_isolation_ci_archive,
)
from alive.provenance import sha256_file, sha256_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--artifact-archive", required=True, type=Path)
    parser.add_argument("--artifact-id", required=True, type=int)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--expires-at-utc", required=True)
    parser.add_argument("--archived-at-utc", required=True)
    parser.add_argument("--archived-by", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Validate the downloaded transport and publish one write-once archive."""
    args = _parser().parse_args(argv)
    archive = build_kernel_isolation_ci_archive(
        receipt_path=args.receipt,
        artifact_archive_path=args.artifact_archive,
        artifact_id=args.artifact_id,
        artifact_name=args.artifact_name,
        expires_at_utc=args.expires_at_utc,
        archived_at_utc=args.archived_at_utc,
        archived_by=args.archived_by,
    )
    write_kernel_isolation_ci_archive(args.output, archive)
    print(f"kernel_isolation_ci_archive_sha256={sha256_json(archive)}")
    print(f"kernel_isolation_ci_archive_file_sha256={sha256_file(args.output)}")
    print(f"kernel_isolation_ci_archive_self_checksum={archive['self_checksum']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
