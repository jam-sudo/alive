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
          "fit_role_artifact": {...},     # the payload-v2 block the worker consumed
          "approved_root": "...",         # the worker's --approved-root
          "sealed_pair_ids": [["GENEA", "GENEB"], ...],   # the payload's pair_ids
          "training_pair_ids": [...],     # OPTIONAL: the harness's own report; must match
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

The training roster is DERIVED from the fit-role artifact (review C2): the
artifact named by ``fit_role_artifact`` is read through the worker's own guard
(``read_verified_fit_role_artifact``) and the roster is what its ``singles`` /
``combo_calibration`` rows carry. ``training_pair_ids`` in the bundle is optional
and, when present, must equal the derived roster. Still operator-attested:
``exit_code`` and the content of the ``fit_role_row_identity`` object (only its
bytes are hashed).

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
    merge_backend_record,
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
            fit_role_artifact=supplied["fit_role_artifact"],
            approved_root=supplied["approved_root"],
            sealed_pair_ids=supplied["sealed_pair_ids"],
            harness_training_pair_ids=supplied.get("training_pair_ids"),
            combo_sep=supplied.get("combo_sep", "_"),
        )
        artifacts, artifact_record = build_smoke_artifact_manifest(
            backend=backend, artifacts=supplied["artifacts"]
        )
        backends[backend] = {
            "roster": roster,
            "artifacts": artifacts,
            "record": merge_backend_record(
                roster_record=roster_record,
                artifact_record=artifact_record,
                exit_code=supplied["exit_code"],
            ),
        }

    wheelhouse = build_wheelhouse_manifest(
        environments={
            env_name: (env["requirements_lock"], env["artifacts"])
            for env_name, env in bundle["wheelhouse"].items()
        }
    )
    promotion_fields = {
        "container_image_digest": bundle["container_image_digest"],
        "git_sha": bundle["git_sha"],
        "generated_at_utc": bundle["generated_at_utc"],
        "host": bundle["host"],
        "activation": bundle["activation"],
        "summary": bundle["summary"],
    }
    # The inputs bundle has now been fully read. Past this line a `KeyError` comes from
    # the LOCK or the evidence directory, not from the bundle -- `promote_lock_to_complete`
    # indexes `lock["run_gate"]["evidence_status"]`, so a malformed lock used to be
    # reported as "inputs bundle is missing 'run_gate'" and exit 2 (PR #15 fable Minor 6).
    # A malformed lock is a REFUSAL (exit 1), which is what an operator reading `$?` needs.
    try:
        promotion = promote_lock_to_complete(
            lock=json.loads(lock_path.read_text(encoding="utf-8")),
            backends=backends,
            wheelhouse=wheelhouse,
            **promotion_fields,
        )
        validated = publish_promotion(promotion, evidence_dir=evidence_dir)
    except KeyError as exc:
        raise ValueError(f"the staged {LOCK_NAME} is malformed: missing key {exc}") from exc
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
        # Narrowed to the bundle-parsing stage: `_promote` converts a KeyError raised
        # after the bundle is read into a refusal, so this can only be a bundle key.
        print(f"usage error: inputs bundle is missing {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"usage/IO error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
