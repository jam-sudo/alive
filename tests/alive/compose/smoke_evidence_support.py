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
from alive.compose.roles import (
    CALIBRATION_ROLE_NAME,
    SEALED_DOUBLE_UNSEEN_ROLE_NAME,
    SEALED_SINGLE_UNSEEN_ROLE_NAME,
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
from alive.compose.split import build_split_manifest
from tests.alive.compose.test_fit_role import _extractor

#: The tiny pair universe the fixture's split manifest is cut over. Three pairs on
#: four genes -- the smallest universe that can hold one pair in each of the three
#: roles, which is what makes "the sealed roster is BOTH sealed roles" measurable.
TINY_ELIGIBLE_PAIRS: tuple[tuple[str, str], ...] = (
    ("AAA", "BBB"),
    ("AAA", "KLF1"),
    ("CEBPE", "KLF1"),
)
#: MEASURED, not chosen. `build_pair_split` -- not this file -- decides which pair
#: takes which role, so the seed was searched for and the constants below follow
#: its answer. Over this universe at f=0.5: seed 0 leaves the calibration and
#: double-unseen roles EMPTY (all three pairs single-unseen), seed 1 puts
#: (AAA, BBB) in calibration and (CEBPE, KLF1) in the seal, and seed 2 is the
#: first that gives one pair to each role -- calibration (CEBPE, KLF1),
#: double-unseen (AAA, BBB), single-unseen (AAA, KLF1).
TINY_SPLIT_SEED = 2
TINY_CALIBRATION_FRACTION = 0.5

#: The real split manifest -- built by the committed builder, checksum and all.
#: `build_split_manifest` verifies what it returns, so importing this module is
#: itself a check that the seed still reproduces the split it is pinned to.
TINY_PAIR_MANIFEST: dict = build_split_manifest(
    list(TINY_ELIGIBLE_PAIRS),
    seed=TINY_SPLIT_SEED,
    calibration_fraction=TINY_CALIBRATION_FRACTION,
)
#: The digest the tiny fit-role artifact carries as its `pair_manifest_sha256`; the
#: producer derives the sealed roster only from a manifest that verifies TO THIS.
TINY_PAIR_MANIFEST_SHA256: str = TINY_PAIR_MANIFEST["checksum"]


def _role_pairs(role: str) -> tuple[tuple[str, str], ...]:
    """The manifest's own membership for one role, as canonical tuples."""
    return tuple((str(a), str(b)) for a, b in TINY_PAIR_MANIFEST["roles"][role])


#: Every constant below is DERIVED from the manifest above. A hand-set roster that
#: disagreed with `build_pair_split` would be a fixture asserting a split the
#: algorithm does not produce, and the producer under test now refuses exactly that.
TINY_CALIBRATION_PAIRS: tuple[tuple[str, str], ...] = _role_pairs(CALIBRATION_ROLE_NAME)
#: Both sealed roles, in the order the producer reads them.
TINY_SEALED_PAIRS: tuple[tuple[str, str], ...] = _role_pairs(
    SEALED_DOUBLE_UNSEEN_ROLE_NAME
) + _role_pairs(SEALED_SINGLE_UNSEEN_ROLE_NAME)
#: The double-unseen pair whose combo cell the tiny artifact must exclude.
TINY_SEALED_COMBO_PAIR: tuple[str, str] = _role_pairs(SEALED_DOUBLE_UNSEEN_ROLE_NAME)[0]
#: The universe's genes, UTF-8 byte-ordered; every one is a retained single.
TINY_GENES: tuple[str, ...] = tuple(
    sorted({gene for pair in TINY_ELIGIBLE_PAIRS for gene in pair}, key=lambda s: s.encode("utf-8"))
)


def tiny_training_tokens(combo_sep: str = "_") -> tuple[str, ...]:
    """What the tiny artifact's fit rows carry, sorted unique, in one separator's spelling."""
    combos = {f"{a}{combo_sep}{b}" for a, b in TINY_CALIBRATION_PAIRS}
    return tuple(sorted(set(TINY_GENES) | combos))


#: What the tiny artifact's non-control rows carry, sorted unique, as the roster records it.
TINY_TRAINING_TOKENS: tuple[str, ...] = tiny_training_tokens()


def write_tiny_pair_manifest(path: Path) -> Path:
    """Write :data:`TINY_PAIR_MANIFEST` to ``path`` as JSON and return it.

    The CLI reads the split manifest from a path in the inputs bundle, so a test
    that drives the CLI needs the same manifest on disk that the tiny artifact
    was cut against.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(TINY_PAIR_MANIFEST, sort_keys=True), encoding="utf-8")
    return path


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

    The rows and the registered pair sets come from :data:`TINY_PAIR_MANIFEST`,
    not from this file: control, one single per gene in :data:`TINY_GENES`, one
    row per calibration combo, and last the double-unseen combo cell that must be
    excluded and never read. The artifact records the manifest's own ``checksum``
    as its ``pair_manifest_sha256`` and its ``eligibility_hash``, which is what
    lets :func:`~alive.compose.smoke_evidence.build_smoke_pair_roster` derive the
    sealed roster from the manifest instead of taking one from a caller.

    ``with_sealed_row`` appends a row carrying the sealed combo token under the
    ``combo_calibration`` role -- the leak Task 0.1's negative test must see
    refused. ``without_combo_rows`` drops the calibration combos so the artifact
    lacks one of the two fit roles.
    """
    sealed_combo_token = f"{TINY_SEALED_COMBO_PAIR[0]}{combo_sep}{TINY_SEALED_COMBO_PAIR[1]}"
    perturbations = ["control", *TINY_GENES]
    if not without_combo_rows:
        perturbations += [f"{a}{combo_sep}{b}" for a, b in TINY_CALIBRATION_PAIRS]
    # Last. In the default (7-row) shape that puts the sealed combo at index 6,
    # which is the row `test_fit_role._extractor`'s reader raises on if anything
    # ever reads it -- so "the sealed cell is never read" stays a measured claim.
    perturbations.append(sealed_combo_token)
    extractor = _extractor(
        obs_source_row_id=[f"r{i}" for i in range(len(perturbations))],
        obs_perturbation=perturbations,
        calibration_pair_ids=list(TINY_CALIBRATION_PAIRS),
        sealed_pair_ids=list(TINY_SEALED_PAIRS),
        pair_manifest_sha256=TINY_PAIR_MANIFEST_SHA256,
        eligibility_hash=TINY_PAIR_MANIFEST["eligibility_hash"],
        combo_sep=combo_sep,
    )
    extraction = extract_fit_roles(extractor=extractor)
    if with_sealed_row:
        import numpy as np
        from scipy import sparse

        leaked = ("r9", CALIBRATION_ROLE_NAME, sealed_combo_token)
        extra = sparse.csr_matrix(np.ones((1, extraction.X.shape[1])))
        counts = dict(extraction.role_counts)
        counts[CALIBRATION_ROLE_NAME] += 1
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
            pair_manifest=TINY_PAIR_MANIFEST,
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
