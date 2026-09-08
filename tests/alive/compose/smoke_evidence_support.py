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
from alive.compose.fit_role import (
    FitRoleArtifactSpec,
    FitRoleExtraction,
    extract_fit_roles,
    generate_fit_role_artifact,
)
from alive.compose.smoke_evidence import (
    LOCK_NAME,
    build_smoke_artifact_manifest,
    build_smoke_pair_roster,
    build_wheelhouse_manifest,
    merge_backend_record,
    promote_lock_to_complete,
    publish_promotion,
)
from tests.alive.compose.test_fit_role import _extractor

#: The one sealed pair the tiny artifact's extractor registers (test_fit_role._extractor).
TINY_SEALED_PAIRS: tuple[tuple[str, str], ...] = (("AAA", "BBB"),)
#: What the tiny artifact's non-control rows carry, sorted unique, as the roster records it.
TINY_TRAINING_TOKENS: tuple[str, ...] = ("AAA", "BBB", "CEBPE", "CEBPE_KLF1", "KLF1")

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


def write_tiny_fit_role_artifact(
    path: Path,
    *,
    with_sealed_row: bool = False,
    without_combo_rows: bool = False,
    combo_sep: str = "_",
) -> FitRoleArtifactSpec:
    """Write a real (tiny) fit-role ``.h5ad`` at ``path`` and return its spec.

    Rows come from ``test_fit_role._extractor``: control, KLF1, CEBPE, CEBPE_KLF1
    (calibration combo), AAA, BBB; the sealed pair is (AAA, BBB). ``with_sealed_row``
    appends a row carrying the sealed combo token under the ``combo_calibration``
    role -- the leak Task 0.1's negative test must see refused. ``without_combo_rows``
    drops the calibration combo so the artifact lacks one of the two fit roles.
    """
    if without_combo_rows:
        extractor = _extractor(
            obs_source_row_id=[f"r{i}" for i in range(6)],
            obs_perturbation=["control", "KLF1", "CEBPE", "AAA", "BBB", "KLF1"],
            combo_sep=combo_sep,
        )
    else:
        extractor = _extractor(
            obs_perturbation=[
                "control",
                "KLF1",
                "CEBPE",
                f"CEBPE{combo_sep}KLF1",
                "AAA",
                "BBB",
                f"AAA{combo_sep}BBB",
            ],
            combo_sep=combo_sep,
        )
    extraction = extract_fit_roles(extractor=extractor)
    if with_sealed_row:
        import numpy as np
        from scipy import sparse

        leaked = ("r9", "combo_calibration", f"AAA{combo_sep}BBB")
        extra = sparse.csr_matrix(np.ones((1, extraction.X.shape[1])))
        counts = dict(extraction.role_counts)
        counts["combo_calibration"] += 1
        extraction = FitRoleExtraction(
            X=sparse.vstack([extraction.X, extra]).tocsr(),
            var_names=extraction.var_names,
            rows=(*extraction.rows, leaked),
            role_counts=counts,
            raw_data_sha256=extraction.raw_data_sha256,
            pair_manifest_sha256=extraction.pair_manifest_sha256,
            eligibility_hash=extraction.eligibility_hash,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return generate_fit_role_artifact(
        extraction=extraction,
        out_path=str(path),
        config_sha256="cfg",
        data_card_sha256="dc",
        calibration_gene_set_hash="cg",
        generator_code_sha256="gen",
        writer_environment_sha256="env",
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
        artifact = write_tiny_fit_role_artifact(objects_dir / backend / "fit_role_artifact.h5ad")
        roster, roster_record = build_smoke_pair_roster(
            backend=backend,
            fit_role_artifact=artifact.to_payload_block(),
            approved_root=objects_dir,
            sealed_pair_ids=TINY_SEALED_PAIRS,
        )
        objects = {}
        for name in _ARTIFACT_NAMES:
            if name == "fit_role_artifact":
                path = Path(artifact.path)
            else:
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
            "record": merge_backend_record(
                roster_record=roster_record, artifact_record=artifact_record, exit_code=0
            ),
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
