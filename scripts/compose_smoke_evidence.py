#!/usr/bin/env python3
"""Assemble the dev-pod smoke evidence and prove it validates.

Thin entry point (``CLAUDE.md#repo``): the assembly lives in
:mod:`alive.compose.smoke_evidence`. What this layer adds is that the operator
cannot walk away with a lock that does not validate -- after writing, the
committed ``validate_dependency_lock`` is re-run on the bytes on disk and a
non-COMPLETE result is a non-zero exit, not a line of output nobody reads.

Usage
-----
    python scripts/compose_smoke_evidence.py promote \
        --inputs  /workspace/smoke/inputs.json \
        --evidence-dir docs/activation-evidence/compose

The inputs bundle is one JSON object::

    {
      "git_sha": "<40 hex, the clean detached commit the pod ran>",
      "container_image_digest": "sha256:<64 hex>",
      "backends": {
        "gears": {
          "training_pair_ids": [...],     # what the smoke ACTUALLY fitted on
          "sealed_pair_ids":  [...],
          "exit_code": 0,
          "artifacts": {"<name>": {"path": ..., "uri": ..., "immutable_version": ...}}
        },
        "cpa": {...}
      },
      "wheelhouse": {
        "gears_env": {"requirements_lock": ...,
                      "artifacts": {"<pkg>": {"path", "filename", "source_url"}}},
        "cpa_env":   {...}
      }
    }

``training_pair_ids`` comes from the smoke harness, which knows what it fitted on.
It is deliberately not re-derived here: a second derivation could disagree with
the first, and the roster's whole purpose is to record what happened.

Exit codes
----------
0 promoted and validated COMPLETE · 1 refused (nothing written) · 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from alive.compose.activation_evidence import ActivationEvidenceError, validate_dependency_lock
from alive.compose.smoke_evidence import (
    build_smoke_artifact_manifest,
    build_smoke_pair_roster,
    build_wheelhouse_manifest,
    promote_lock_to_complete,
)

LOCK_NAME = "gears_cpa_dependency_lock.json"


def _promote(inputs_path: Path, evidence_dir: Path) -> int:
    bundle = json.loads(inputs_path.read_text(encoding="utf-8"))
    lock_path = evidence_dir / LOCK_NAME

    backends = {}
    for backend, supplied in bundle["backends"].items():
        roster, roster_record = build_smoke_pair_roster(
            backend=backend,
            training_pair_ids=supplied["training_pair_ids"],
            sealed_pair_ids=supplied["sealed_pair_ids"],
        )
        artifacts, artifact_record = build_smoke_artifact_manifest(
            backend=backend, artifacts=supplied["artifacts"]
        )
        backends[backend] = {
            "roster": roster,
            "artifacts": artifacts,
            "record": {
                **roster_record,
                **artifact_record,
                "exit_code": supplied["exit_code"],
            },
        }

    wheelhouse = build_wheelhouse_manifest(
        environments={
            env_name: (env["requirements_lock"], env["artifacts"])
            for env_name, env in bundle["wheelhouse"].items()
        }
    )
    promoted = promote_lock_to_complete(
        lock=json.loads(lock_path.read_text(encoding="utf-8")),
        evidence_dir=evidence_dir,
        backends=backends,
        wheelhouse=wheelhouse,
        container_image_digest=bundle["container_image_digest"],
        git_sha=bundle["git_sha"],
    )
    # Validate first, replace second. The validator resolves every referenced path
    # relative to the lock's own directory, so the candidate is written beside the
    # committed lock rather than in a temp directory. Overwriting first and
    # discovering afterwards that the result does not validate would leave the
    # evidence directory holding a lock nobody can use, for the next operator to
    # inherit -- and some of what the validator checks (the image digest, for one)
    # is not checked by promotion.
    candidate = lock_path.with_name(lock_path.name + ".candidate")
    candidate.write_text(json.dumps(promoted, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        validated = validate_dependency_lock(candidate)
        status = validated["run_gate"]["evidence_status"]
        if status != "COMPLETE":
            raise ActivationEvidenceError(f"candidate validates as {status}, not COMPLETE")
    except (ActivationEvidenceError, ValueError) as exc:
        candidate.unlink(missing_ok=True)
        print(f"FAILED: candidate does not validate: {exc}", file=sys.stderr)
        return 1
    os.replace(candidate, lock_path)
    print(
        f"OK: {lock_path} validates COMPLETE "
        f"({validated['run_gate']['seal_safety_status']}); no seal was opened."
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    promote = sub.add_parser("promote", help="assemble the evidence and validate the lock")
    promote.add_argument("--inputs", required=True, type=Path)
    promote.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        return _promote(args.inputs, args.evidence_dir)
    except (ValueError, ActivationEvidenceError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"usage/IO error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
