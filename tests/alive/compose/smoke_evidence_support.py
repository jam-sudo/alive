"""Synthetic COMPLETE dependency-lock evidence, built by the real producer.

Two test builders used to assemble a COMPLETE lock by hand -- nine fields, two
sidecars per backend, a wheelhouse and a checksum, duplicated line for line in
`tests/alive/compose/test_config2.py` and
`tests/alive/compose/driver/scientific_carrier_support.py`. Both now go through
`alive.compose.smoke_evidence`, so a test lock is built the way a pod lock is
built and the producer's own guarantees (measured digests, roster derived from
the lock, staged validation, write-once publish) hold for the fixture too. A
change to the lock contract is then one edit, in the producer, not three.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from alive.compose.activation_evidence import _validate_pinned_requirements
from alive.compose.smoke_evidence import (
    LOCK_NAME,
    build_smoke_artifact_manifest,
    build_smoke_pair_roster,
    build_wheelhouse_manifest,
    promote_lock_to_complete,
    publish_promotion,
)

_EVIDENCE_ROOT = Path(__file__).resolve().parents[3] / "docs/activation-evidence/compose"
_LINEAGE_FILES = (
    "requirements.gears_env.lock",
    "requirements.cpa_env.lock",
    "go_resource_manifest.json",
)
_ARTIFACT_NAMES = (
    "norman_source",
    "fit_role_artifact",
    "fit_role_row_identity",
    "smoke_script",
    "command_log",
    "checkpoint",
)


def publish_synthetic_complete_lock(
    evidence_dir: Path, *, objects_dir: Path, activation: str
) -> Path:
    """Copy the committed lineage into ``evidence_dir`` and publish a COMPLETE lock there.

    Parameters
    ----------
    evidence_dir : Path
        Receives the committed requirements locks and GO manifest, the five
        sidecars and the promoted lock. Created if absent.
    objects_dir : Path
        Receives the tiny files whose digests the lock records (six smoke objects
        per backend, one wheel per pin). Must not be inside ``evidence_dir``.
    activation : str
        The lock's activation text; must not say BLOCKED.

    Returns
    -------
    Path
        The published lock, ``evidence_dir / LOCK_NAME``.
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for name in _LINEAGE_FILES:
        shutil.copyfile(_EVIDENCE_ROOT / name, evidence_dir / name)
    lock = json.loads((_EVIDENCE_ROOT / LOCK_NAME).read_text(encoding="utf-8"))

    backends = {}
    for backend in ("gears", "cpa"):
        roster, roster_record = build_smoke_pair_roster(
            backend=backend,
            training_pair_ids=[f"{backend}:train:a", f"{backend}:train:b"],
            sealed_pair_ids=[f"{backend}:sealed:a", f"{backend}:sealed:b"],
        )
        objects = {}
        for name in _ARTIFACT_NAMES:
            path = objects_dir / backend / f"{name}.bin"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"{backend}:{name}".encode())
            objects[name] = {
                "path": path,
                "uri": f"s3://example.invalid/compose/{backend}/{name}",
                "immutable_version": "synthetic-unit-test-version",
            }
        manifest, artifact_record = build_smoke_artifact_manifest(
            backend=backend, artifacts=objects
        )
        backends[backend] = {
            "roster": roster,
            "artifacts": manifest,
            "record": {**roster_record, **artifact_record, "exit_code": 0},
        }

    environments = {}
    for env_name in ("gears_env", "cpa_env"):
        requirements = evidence_dir / f"requirements.{env_name}.lock"
        wheels = {}
        for name, version in _validate_pinned_requirements(requirements).items():
            wheel = objects_dir / "wheels" / env_name / f"{name}-{version}-py3-none-any.whl"
            wheel.parent.mkdir(parents=True, exist_ok=True)
            wheel.write_bytes(wheel.name.encode())
            wheels[name] = {
                "path": wheel,
                "filename": wheel.name,
                "source_url": f"https://packages.example.invalid/{wheel.name}",
            }
        environments[env_name] = (requirements, wheels)

    promotion = promote_lock_to_complete(
        lock=lock,
        backends=backends,
        wheelhouse=build_wheelhouse_manifest(environments=environments),
        container_image_digest="sha256:" + "b" * 64,
        git_sha=lock["git_sha"],
        generated_at_utc=lock["generated_at_utc"],
        host=lock["host"],
        activation=activation,
        summary="synthetic unit-test smoke evidence produced by alive.compose.smoke_evidence",
    )
    publish_promotion(promotion, evidence_dir=evidence_dir)
    return evidence_dir / LOCK_NAME
