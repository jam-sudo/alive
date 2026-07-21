#!/usr/bin/env python
"""Build one canonical, write-once unsigned Probe-A verifier image candidate."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from alive.compose.verifier_image import build_verifier_image_candidate, canonical_json


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
    parser.add_argument("--build-repository", required=True)
    parser.add_argument("--build-workflow-ref", required=True)
    parser.add_argument("--build-run-id", required=True)
    parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    candidate = build_verifier_image_candidate(
        git_commit=args.git_commit,
        image_reference=args.image_reference,
        platform=args.platform,
        python_base_image=args.python_base_image,
        uv_build_image=args.uv_build_image,
        dockerfile_sha256=args.dockerfile_sha256,
        uv_lock_sha256=args.uv_lock_sha256,
        verifier_code_sha256=args.verifier_code_sha256,
        build_repository=args.build_repository,
        build_workflow_ref=args.build_workflow_ref,
        build_run_id=args.build_run_id,
    )
    data = (canonical_json(candidate) + "\n").encode()
    output = Path(args.out)
    if output.is_symlink():
        raise ValueError("verifier image candidate output must not be a symlink")
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
