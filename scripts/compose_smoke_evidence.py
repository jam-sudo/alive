#!/usr/bin/env python3
"""Assemble the dev-pod smoke evidence and prove it validates.

Thin entry point (``CLAUDE.md#repo``): the assembly and the publish transaction
live in :mod:`alive.compose.smoke_evidence`. What this layer adds is the exit
code: a refused promotion is a non-zero exit, not a line of output nobody reads.

Usage
-----
    python scripts/compose_smoke_evidence.py promote \
        --inputs  /workspace/smoke/inputs.json \
        --evidence-dir docs/activation-evidence/compose

The inputs bundle is one JSON object::

    {
      "git_sha": "<40 hex, the clean detached commit the pod ran>",
      "container_image_digest": "sha256:<64 hex>",
      "generated_at_utc": "<YYYY-MM-DDTHH:MM:SSZ, the pod's recorded start time>",
      "host": {"gpu": ..., "nvidia_driver": ..., "uv_version": ...},
      "activation": "READY — <what this evidence is; must start with READY>",
      "summary": "<run_gate.summary for this run>",
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

``training_pair_ids`` and ``exit_code`` come from the smoke harness and are
operator-attested: the roster is hashed and checked for sealed overlap, but it is
not re-derived from the fit-role artifact here. Deriving it is an open decision
(review C2); until then the bundle's roster is the claim.

Exit codes
----------
0 promoted and validated COMPLETE · 1 refused (nothing written) · 2 usage error
(unreadable or incomplete bundle, I/O failure; nothing written).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from alive.compose.activation_evidence import ActivationEvidenceError
from alive.compose.smoke_evidence import (
    LOCK_NAME,
    build_smoke_artifact_manifest,
    build_smoke_pair_roster,
    build_wheelhouse_manifest,
    promote_lock_to_complete,
    publish_promotion,
)


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
    promotion = promote_lock_to_complete(
        lock=json.loads(lock_path.read_text(encoding="utf-8")),
        backends=backends,
        wheelhouse=wheelhouse,
        container_image_digest=bundle["container_image_digest"],
        git_sha=bundle["git_sha"],
        generated_at_utc=bundle["generated_at_utc"],
        host=bundle["host"],
        activation=bundle["activation"],
        summary=bundle["summary"],
    )
    validated = publish_promotion(promotion, evidence_dir=evidence_dir)
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
    except (ValueError, ActivationEvidenceError, FileExistsError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    except KeyError as exc:
        print(f"usage error: inputs bundle is missing {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"usage/IO error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
