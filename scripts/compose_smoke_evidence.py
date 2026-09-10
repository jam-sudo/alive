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

A publish that dies between the write-once sidecars and the final lock rename
leaves sidecars nothing binds, and every retry is then refused (`FileExistsError`)
until they are gone. Reclaim them with the SAME bundle, which is what names the
files this promotion would have written::

    python scripts/compose_smoke_evidence.py reclaim-unbound \
        --inputs  /workspace/smoke/inputs.json \
        --evidence-dir docs/activation-evidence/compose

It removes nothing under a COMPLETE lock, nothing the lock's text mentions, and
nothing outside this promotion's own sidecar names -- and refuses the whole
request rather than applying part of it.

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
          "pair_manifest": "...",         # path to the protocol's split manifest JSON
          "sealed_pair_ids": [["GENEA", "GENEB"], ...],  # OPTIONAL cross-check; must match
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
and, when present, must equal the derived roster.

The SEALED roster is derived too (judgment 3, 2026-09-10): ``pair_manifest`` names
the protocol's split manifest, which must verify and whose checksum must equal the
artifact block's ``pair_manifest_sha256``; the roster is then that manifest's two
sealed roles. ``sealed_pair_ids`` is therefore optional and, when present, a
cross-check that must equal the derived roster exactly. Still operator-attested:
``exit_code`` and the content of the ``fit_role_row_identity`` object (only its
bytes are hashed).

Exit codes
----------
0 promoted and validated COMPLETE · 1 refused (nothing written) · 2 usage error
(unreadable or incomplete bundle, I/O failure; nothing written).

For ``reclaim-unbound``: 0 reclaimed (possibly nothing to reclaim, which is not an
error) · 1 refused (nothing removed) · 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from alive.compose.activation_evidence import ActivationEvidenceError
from alive.compose.smoke_evidence import (
    LOCK_NAME,
    Promotion,
    build_smoke_artifact_manifest,
    build_smoke_pair_roster,
    build_wheelhouse_manifest,
    merge_backend_record,
    promote_lock_to_complete,
    publish_promotion,
    reclaim_unbound_sidecars,
)


def _promotion_from_bundle(bundle: dict, lock_path: Path) -> Promotion:
    """Build the promotion the bundle describes, writing nothing.

    Shared by both subcommands. `promote` publishes the result; `reclaim-unbound`
    wants only the names of the sidecars this promotion WOULD publish, and takes
    them from the same computation rather than from a second spelling of the file
    names -- a reclaim list assembled independently of the promotion is a list of
    files nobody proved this run would have written.
    """
    backends = {}
    for backend, supplied in bundle["backends"].items():
        # A missing `pair_manifest` key is a KeyError and an unreadable file an
        # OSError, and both leave `main` at exit 2 -- a bundle that does not say
        # which split the smoke was cut against has not described a promotion.
        manifest_path = Path(supplied["pair_manifest"])
        roster, roster_record = build_smoke_pair_roster(
            backend=backend,
            fit_role_artifact=supplied["fit_role_artifact"],
            approved_root=supplied["approved_root"],
            pair_manifest=json.loads(manifest_path.read_text(encoding="utf-8")),
            sealed_pair_ids=supplied.get("sealed_pair_ids"),
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
        return promote_lock_to_complete(
            lock=json.loads(lock_path.read_text(encoding="utf-8")),
            backends=backends,
            wheelhouse=wheelhouse,
            **promotion_fields,
        )
    except KeyError as exc:
        raise ValueError(f"the staged {LOCK_NAME} is malformed: missing key {exc}") from exc


def _promote(inputs_path: Path, evidence_dir: Path) -> int:
    bundle = json.loads(inputs_path.read_text(encoding="utf-8"))
    lock_path = evidence_dir / LOCK_NAME
    promotion = _promotion_from_bundle(bundle, lock_path)
    try:
        validated = publish_promotion(promotion, evidence_dir=evidence_dir)
    except KeyError as exc:
        raise ValueError(f"the staged {LOCK_NAME} is malformed: missing key {exc}") from exc
    print(
        f"OK: {lock_path} validates COMPLETE "
        f"({validated['run_gate']['seal_safety_status']}); no seal was opened."
    )
    return 0


def _reclaim_unbound(inputs_path: Path, evidence_dir: Path) -> int:
    """Reclaim the sidecars a publish that died before the lock rename left behind.

    The sidecars are published write-once and the lock last, so a crash between
    them leaves files that no lock binds and that the write-once guard then
    refuses to overwrite. This removes exactly those -- under an INCOMPLETE lock,
    among the names THIS promotion publishes, and only when the lock's text
    mentions none of them -- so the recovery is a checked command instead of an
    `rm` typed inside an evidence directory.

    Nothing about publishing is weakened: the promotion built here is thrown
    away, and if the lock is already COMPLETE the name computation itself refuses
    before `reclaim_unbound_sidecars` gets to refuse on the same fact.
    """
    bundle = json.loads(inputs_path.read_text(encoding="utf-8"))
    try:
        promotion = _promotion_from_bundle(bundle, evidence_dir / LOCK_NAME)
    except (ValueError, ActivationEvidenceError) as exc:
        # The name computation reuses the promotion path, so its refusals speak of
        # "promoting". An operator running reclaim-unbound must read a refusal about
        # reclaiming (2026-09-10 whole-branch review, Minor 4). Same class, so `main`'s
        # exit-code mapping is unchanged.
        raise type(exc)(
            f"reclaim-unbound: this bundle cannot name a promotion's sidecars — {exc}"
        ) from exc
    removed = reclaim_unbound_sidecars(
        evidence_dir=evidence_dir, sidecar_names=set(promotion.files)
    )
    if removed:
        print(f"OK: reclaimed {len(removed)} unbound sidecar(s) under {evidence_dir}: {removed}")
    else:
        print(f"OK: no unbound sidecar of this promotion under {evidence_dir}; nothing removed.")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    promote = sub.add_parser("promote", help="assemble the evidence and validate the lock")
    promote.add_argument("--inputs", required=True, type=Path)
    promote.add_argument("--evidence-dir", required=True, type=Path)
    reclaim = sub.add_parser(
        "reclaim-unbound",
        help="remove sidecars a crashed publish left behind, under an INCOMPLETE lock only",
    )
    reclaim.add_argument("--inputs", required=True, type=Path)
    reclaim.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "reclaim-unbound":
            return _reclaim_unbound(args.inputs, args.evidence_dir)
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
