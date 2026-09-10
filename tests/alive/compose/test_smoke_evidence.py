"""Producer for the dev-pod smoke evidence the committed validator already demands.

`alive.compose.activation_evidence` validates this evidence strictly but nothing
produces it, so the dependency lock has been `activation=BLOCKED` /
`evidence_status=INCOMPLETE` with every `required_evidence` field null. Filling
those by hand on the pod is how a measurement and its record drift apart -- this
repository's dominant defect. These tests drive a producer that derives both
sides of every cross-check from one computation.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from alive.compose import smoke_evidence
from alive.compose.activation_evidence import (
    ActivationEvidenceError,
    _validate_pair_roster_manifest,
    _validate_pinned_requirements,
    _validate_smoke_artifact_manifest,
    _validate_wheelhouse_manifest,
    validate_dependency_lock,
)
from alive.compose.fit_role import FitRoleArtifactError
from alive.compose.smoke_evidence import (
    _SIDECAR_NAMES,
    LOCK_NAME,
    build_smoke_artifact_manifest,
    build_smoke_pair_roster,
    build_wheelhouse_manifest,
    merge_backend_record,
    promote_lock_to_complete,
    publish_promotion,
    reclaim_unbound_sidecars,
)
from tests.alive.compose.smoke_evidence_support import (
    TINY_SEALED_PAIRS,
    TINY_TRAINING_TOKENS,
    write_tiny_fit_role_artifact,
)


def _write(tmp_path, payload):
    path = tmp_path / "roster.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _roster_from(tmp_path, *, backend="gears", sealed=TINY_SEALED_PAIRS, **kwargs):
    artifact = write_tiny_fit_role_artifact(tmp_path / "fit_role_artifact.h5ad", **kwargs)
    roster, record = build_smoke_pair_roster(
        backend=backend,
        fit_role_artifact=artifact.to_payload_block(),
        approved_root=tmp_path,
        sealed_pair_ids=sealed,
    )
    return artifact, roster, record


def test_the_training_roster_is_derived_from_the_verified_fit_role_artifact(tmp_path):
    """The roster is what the artifact's fit rows carry, read through the worker's own guard.

    Review C2: the first producer hashed a roster the operator typed into the
    bundle and certified `VERIFIED_ZERO_OVERLAP` on it. Now the artifact named by
    the payload's `fit_role_artifact` block is read with
    `read_verified_fit_role_artifact` -- SHA-verified on a stable descriptor,
    snapshot identity rebound to the spec -- and the roster is the sorted unique
    perturbation tokens of its `singles` / `combo_calibration` rows. The record's
    `fit_role_artifact_sha256` is the digest of the bytes that roster came from.
    """
    artifact, roster, record = _roster_from(tmp_path)

    assert roster["training_pair_ids"] == list(TINY_TRAINING_TOKENS)
    assert roster["sealed_pair_ids"] == ["AAA_BBB"]
    assert record["sealed_pair_overlap_count"] == 0
    assert record["fit_role_artifact_sha256"] == artifact.sha256.removeprefix("sha256:")
    _validate_pair_roster_manifest(_write(tmp_path, roster), backend="gears", record=record)


def test_sealed_pairs_are_canonicalised_to_the_artifact_s_token_form(tmp_path):
    """Both rosters must use ONE encoding or their intersection is vacuously empty.

    The artifact stores a combo as the byte-ordered `GENEA_GENEB` token; the split
    manifest and payload carry sealed pairs as `[a, b]` lists in either order. A
    producer that compared `("BBB", "AAA")` with `"AAA_BBB"` would report zero
    overlap for a training roster that contained the sealed pair -- the
    `e3b0c442` shape: two things equal only because neither was measured.
    """
    _, roster, _ = _roster_from(tmp_path, sealed=[("BBB", "AAA"), ["AAA", "BBB"]])
    assert roster["sealed_pair_ids"] == ["AAA_BBB"]


def test_the_sealed_token_form_follows_the_artifact_s_combo_separator(tmp_path):
    """`combo_sep` is not decoration: both rosters must be spelled with the artifact's own.

    The 2026-09-06 review asked for a mutation the three roster tests survive and
    named two. Byte-order vs code-point order is an equivalent mutant (UTF-8
    preserves code-point order; 0 disagreements over 200k random pairs). Ignoring
    `combo_sep` is not: with the default `"_"` in every test, a builder that
    hard-coded the underscore passed all of them. An artifact written with `"+"`
    must yield `AAA+BBB` on the sealed side and `CEBPE+KLF1` on the training side,
    or the two rosters are in different alphabets and their intersection is empty
    for the wrong reason.
    """
    artifact = write_tiny_fit_role_artifact(tmp_path / "fit_role_artifact.h5ad", combo_sep="+")
    roster, record = build_smoke_pair_roster(
        backend="gears",
        fit_role_artifact=artifact.to_payload_block(),
        approved_root=tmp_path,
        sealed_pair_ids=TINY_SEALED_PAIRS,
        combo_sep="+",
    )
    assert roster["sealed_pair_ids"] == ["AAA+BBB"]
    assert "CEBPE+KLF1" in roster["training_pair_ids"]
    assert record["sealed_pair_overlap_count"] == 0


def test_a_sealed_combo_row_in_the_artifact_is_reported_not_laundered(tmp_path):
    """Task 0.1's named acceptance condition: one sealed pair in training refuses.

    The artifact here carries a row with the sealed token `AAA_BBB` under the
    `combo_calibration` role -- the leak a broken extractor would produce. The
    derived roster must contain it and the overlap must be 1, so that the
    committed validator refuses; a producer that dropped the row while deriving
    would hand the validator a clean roster for a smoke that fitted on a sealed
    pair. This is what the derivation exists to make impossible to hide.
    """
    _, roster, record = _roster_from(tmp_path, with_sealed_row=True)

    assert "AAA_BBB" in roster["training_pair_ids"]
    assert record["sealed_pair_overlap_count"] == 1
    with pytest.raises(ActivationEvidenceError, match="overlaps sealed pairs"):
        _validate_pair_roster_manifest(_write(tmp_path, roster), backend="gears", record=record)


def test_a_harness_roster_that_disagrees_with_the_artifact_is_refused(tmp_path):
    """When the harness also reports what it fitted on, the two must agree exactly."""
    artifact = write_tiny_fit_role_artifact(tmp_path / "fit_role_artifact.h5ad")
    claimed = [token for token in TINY_TRAINING_TOKENS if token != "KLF1"]
    with pytest.raises(ValueError, match="KLF1"):
        build_smoke_pair_roster(
            backend="gears",
            fit_role_artifact=artifact.to_payload_block(),
            approved_root=tmp_path,
            sealed_pair_ids=TINY_SEALED_PAIRS,
            harness_training_pair_ids=claimed,
        )


def test_an_artifact_lacking_one_of_the_two_fit_roles_is_refused(tmp_path):
    """`training_roles` is established from the rows, not asserted from a constant.

    The validator requires exactly `["singles", "combo_calibration"]`. An artifact
    with no calibration-combo rows is a smoke that did not fit the roster the plan
    requires; writing the constant anyway would certify a fit that did not happen.
    """
    with pytest.raises(ValueError, match="combo_calibration"):
        _roster_from(tmp_path, without_combo_rows=True)


def test_an_artifact_whose_bytes_are_not_the_spec_s_is_refused(tmp_path):
    """The guard's SHA check is the producer's too; a swapped artifact yields no roster."""
    artifact = write_tiny_fit_role_artifact(tmp_path / "fit_role_artifact.h5ad")
    with open(artifact.path, "ab") as handle:
        handle.write(b"\x00")
    with pytest.raises(FitRoleArtifactError):
        build_smoke_pair_roster(
            backend="gears",
            fit_role_artifact=artifact.to_payload_block(),
            approved_root=tmp_path,
            sealed_pair_ids=TINY_SEALED_PAIRS,
        )


def test_merge_refuses_a_manifest_hashed_from_a_different_artifact_than_the_roster(tmp_path):
    """Two reads of the artifact are one only if they hashed the same bytes.

    The roster builder reads the artifact through the verified descriptor; the
    artifact-manifest builder hashes the file again for `fit_role_artifact_sha256`.
    A swap between the two would make the record describe a roster from one file
    and a digest of another. The merge is where the two measurements meet, and it
    refuses unless they agree.
    """
    with pytest.raises(ValueError, match="fit_role_artifact_sha256"):
        merge_backend_record(
            roster_record={"fit_role_artifact_sha256": "a" * 64, "sealed_pair_overlap_count": 0},
            artifact_record={"fit_role_artifact_sha256": "b" * 64},
            exit_code=0,
        )


_ARTIFACT_NAMES = (
    "norman_source",
    "fit_role_artifact",
    "fit_role_row_identity",
    "smoke_script",
    "command_log",
    "checkpoint",
)


def _artifact_inputs(tmp_path, *, fit_role_artifact=None):
    """Six real files plus a durable URI and immutable version for each.

    `fit_role_artifact`, when given, is the real `.h5ad` the roster was derived
    from; otherwise a stand-in blob (the builder only hashes it).
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    inputs = {}
    for index, name in enumerate(_ARTIFACT_NAMES):
        if name == "fit_role_artifact" and fit_role_artifact is not None:
            path = Path(fit_role_artifact)
        else:
            path = tmp_path / f"{name}.bin"
            path.write_bytes(f"{name}-bytes-{index}".encode())
        inputs[name] = {
            "path": path,
            "uri": f"s3://alive-compose-evidence/gears/{name}",
            "immutable_version": f"v{index}KJh3",
        }
    return inputs


def test_the_artifact_manifest_hashes_the_files_it_names(tmp_path):
    """The producer measures the bytes; it does not accept a hash from the caller.

    "A hash for a discarded or unlocatable object is not evidence" (plan Task 0.1).
    A producer that took `sha256` as an argument would let the record describe
    bytes nobody ever read. Hashing here makes "the recorded digest is the file on
    disk" true by construction, and the same value goes into both the manifest and
    the run-gate record.
    """
    inputs = _artifact_inputs(tmp_path)
    manifest, record = build_smoke_artifact_manifest(backend="gears", artifacts=inputs)

    for name in _ARTIFACT_NAMES:
        expected = hashlib.sha256(inputs[name]["path"].read_bytes()).hexdigest()
        assert manifest["artifacts"][name]["sha256"] == expected

    path = tmp_path / "artifacts.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    _validate_smoke_artifact_manifest(path, backend="gears", record=record)


def test_an_unexpected_artifact_name_is_refused_not_silently_dropped(tmp_path):
    """A seventh artifact must not vanish without a word.

    The builder iterates the six names the validator requires, so anything else the
    caller supplies is simply not read. An operator who adds an object expecting it
    to be recorded would get a manifest that silently omits it and a validator that
    happily accepts the six -- evidence that is complete by the letter and short by
    intent. Refusing is the only way the omission is visible.
    """
    inputs = _artifact_inputs(tmp_path)
    extra = tmp_path / "extra.bin"
    extra.write_bytes(b"extra")
    inputs["training_log"] = {
        "path": extra,
        "uri": "s3://alive-compose-evidence/gears/training_log",
        "immutable_version": "v9",
    }
    with pytest.raises(ValueError, match="training_log"):
        build_smoke_artifact_manifest(backend="gears", artifacts=inputs)


def _wheelhouse_inputs(tmp_path):
    """Both locked environments with one real wheel file per pin."""
    rosters = {
        "gears_env": ("cell-gears", "0.1.2"),
        "cpa_env": ("cpa-tools", "0.8.5"),
    }
    envs = {}
    for env_name, (backend_pkg, backend_version) in rosters.items():
        lock = tmp_path / f"requirements.{env_name}.lock"
        lock.write_text(f"{backend_pkg}=={backend_version}\ntorch==2.4.0\n", encoding="utf-8")
        wheels = {}
        for name, version in ((backend_pkg, backend_version), ("torch", "2.4.0")):
            wheel = tmp_path / f"{env_name}-{name}-{version}.whl"
            wheel.write_bytes(f"{env_name}{name}{version}".encode())
            wheels[name] = {
                "path": wheel,
                "filename": wheel.name,
                "source_url": f"https://pypi.org/simple/{name}/{wheel.name}",
            }
        envs[env_name] = (lock, wheels)
    return envs


def test_the_wheelhouse_roster_is_derived_from_the_requirements_lock(tmp_path):
    """The roster must come from the lock, not be typed beside it.

    `_validate_wheelhouse_manifest` requires the manifest's package roster to equal
    the pins parsed from the requirements lock EXACTLY. A producer that accepted a
    roster from its caller would let the two drift and rely on the validator to
    notice; deriving from the lock -- with the validator's own parser -- makes them
    the same thing.
    """
    envs = _wheelhouse_inputs(tmp_path)
    manifest = build_wheelhouse_manifest(environments=envs)

    path = tmp_path / "wheelhouse.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    _validate_wheelhouse_manifest(
        path,
        {name: _validate_pinned_requirements(lock) for name, (lock, _) in envs.items()},
    )


def test_a_wheelhouse_missing_an_environment_is_refused(tmp_path):
    """Both locked envs must be covered; a one-env manifest is not release evidence.

    The validator demands exactly `{gears_env, cpa_env}`. Emitting the single
    environment the caller happened to pass would produce a manifest that is
    internally consistent and still rejected downstream -- after the pod time is
    spent.
    """
    envs = _wheelhouse_inputs(tmp_path)
    del envs["cpa_env"]
    with pytest.raises(ValueError, match="cpa_env"):
        build_wheelhouse_manifest(environments=envs)


def test_a_wheel_missing_from_the_wheelhouse_is_refused(tmp_path):
    """A pin with no artifact must raise here, not produce a short roster.

    The validator would also catch it, but only after the pod has finished. The
    producer runs while the operator can still fetch the wheel.
    """
    envs = _wheelhouse_inputs(tmp_path)
    lock, wheels = envs["cpa_env"]
    del wheels["torch"]
    with pytest.raises(ValueError, match="torch"):
        build_wheelhouse_manifest(environments=envs)


_EVIDENCE_DIR = Path(__file__).resolve().parents[3] / "docs/activation-evidence/compose"


def _staged_evidence(tmp_path):
    """The committed evidence directory, copied so a test never writes into the repo."""
    staged = tmp_path / "compose"
    shutil.copytree(_EVIDENCE_DIR, staged)
    return staged


def _wheelhouse_for_real_locks(staged, tmp_path):
    """One real (tiny) artifact file per pin in each committed requirements lock."""
    envs = {}
    for env_name in ("gears_env", "cpa_env"):
        lock = staged / f"requirements.{env_name}.lock"
        pins = _validate_pinned_requirements(lock)
        wheels = {}
        for name, version in pins.items():
            wheel = tmp_path / "wheels" / env_name / f"{name}-{version}.whl"
            wheel.parent.mkdir(parents=True, exist_ok=True)
            wheel.write_bytes(f"{env_name}/{name}/{version}".encode())
            wheels[name] = {
                "path": wheel,
                "filename": wheel.name,
                "source_url": f"https://pypi.org/simple/{name}/{wheel.name}",
            }
        envs[env_name] = (lock, wheels)
    return envs


def _backends_for(tmp_path, *, overlap=False, exit_code=0):
    """Builder outputs for both backends; `overlap` puts a sealed row in gears' artifact."""
    backends = {}
    for backend in ("gears", "cpa"):
        artifact = write_tiny_fit_role_artifact(
            tmp_path / backend / "fit_role_artifact.h5ad",
            with_sealed_row=(overlap and backend == "gears"),
        )
        roster, roster_record = build_smoke_pair_roster(
            backend=backend,
            fit_role_artifact=artifact.to_payload_block(),
            approved_root=tmp_path,
            sealed_pair_ids=TINY_SEALED_PAIRS,
        )
        artifacts, artifact_record = build_smoke_artifact_manifest(
            backend=backend,
            artifacts=_artifact_inputs(tmp_path / backend, fit_role_artifact=artifact.path),
        )
        backends[backend] = {
            "roster": roster,
            "artifacts": artifacts,
            "record": merge_backend_record(
                roster_record=roster_record,
                artifact_record=artifact_record,
                exit_code=exit_code if backend == "cpa" else 0,
            ),
        }
    return backends


_HOST = {"gpu": "NVIDIA A100 80GB PCIe", "nvidia_driver": "550.127.05", "uv_version": "uv 0.9.0"}
_PROSE = {
    "generated_at_utc": "2026-09-05T21:00:00Z",
    "host": _HOST,
    "activation": "fit-role smoke evidence captured on the dev pod (plan Task 0.1)",
    "summary": "Both backends completed the fit-role smoke; rosters are disjoint from the seal.",
}


def _promote(
    staged,
    tmp_path,
    backends,
    *,
    container_image_digest="sha256:" + "b" * 64,
    git_sha="a" * 40,
    wheelhouse=None,
    **prose,
):
    return promote_lock_to_complete(
        lock=json.loads((staged / "gears_cpa_dependency_lock.json").read_text(encoding="utf-8")),
        backends=backends,
        wheelhouse=wheelhouse
        or build_wheelhouse_manifest(environments=_wheelhouse_for_real_locks(staged, tmp_path)),
        container_image_digest=container_image_digest,
        git_sha=git_sha,
        **{**_PROSE, **prose},
    )


def _drifted_wheelhouse(staged, tmp_path):
    """A wheelhouse built from a cpa lock that carries one pin the committed lock lacks.

    Promotion cannot see the drift -- it derives the roster from whatever lock it
    is handed -- while the validator compares the manifest against the pins in the
    evidence directory. This is the realistic validator-only refusal: a pod that
    resolved its wheelhouse from a stale requirements lock.
    """
    drifted = tmp_path / "requirements.cpa_env.drifted.lock"
    drifted.write_text(
        (staged / "requirements.cpa_env.lock").read_text(encoding="utf-8") + "extra-pkg==1.0\n",
        encoding="utf-8",
    )
    envs = _wheelhouse_for_real_locks(staged, tmp_path)
    lock, wheels = envs["cpa_env"]
    wheel = tmp_path / "wheels" / "cpa_env" / "extra-pkg-1.0.whl"
    wheel.write_bytes(b"extra")
    wheels["extra-pkg"] = {
        "path": wheel,
        "filename": wheel.name,
        "source_url": f"https://pypi.org/simple/extra-pkg/{wheel.name}",
    }
    envs["cpa_env"] = (drifted, wheels)
    return build_wheelhouse_manifest(environments=envs)


def _snapshot(directory):
    """Every file under `directory` with its exact bytes, so nothing can change unnoticed."""
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_promoting_the_committed_lock_yields_evidence_status_complete(tmp_path):
    """Task 0.1's acceptance condition, end to end on the real committed lock.

    `INCOMPLETE -> COMPLETE` touches nine places in the lock: the seal-safety
    status, three completion flags, the artifact-hash flag, the wheelhouse path and
    hash, the image digest, the reproducibility status, the missing-evidence list,
    and the top-level checksum. Flipping those by hand means getting nine things
    consistent; half a flip is refused by the validator with no clue which half.
    One function flips them together or not at all, and publishing puts the lock
    and every sidecar it binds on disk where the committed validator accepts them.
    """
    staged = _staged_evidence(tmp_path)
    lock_path = staged / "gears_cpa_dependency_lock.json"
    assert json.loads(lock_path.read_text(encoding="utf-8"))["run_gate"]["evidence_status"] == (
        "INCOMPLETE"
    )

    publish_promotion(_promote(staged, tmp_path, _backends_for(tmp_path)), evidence_dir=staged)

    validated = validate_dependency_lock(lock_path)
    assert validated["run_gate"]["evidence_status"] == "COMPLETE"
    assert validated["run_gate"]["seal_safety_status"] == "VERIFIED_ZERO_OVERLAP"


def test_promotion_refuses_to_certify_zero_overlap_it_did_not_verify(tmp_path):
    """`VERIFIED_ZERO_OVERLAP` must be established here, not merely asserted.

    Promotion writes that exact string into the lock. Writing it unconditionally
    means the producer claims a verification it never performed and leans on the
    validator to catch the lie downstream -- the same shape as an amendment that
    asserts a property the tree lacks.
    """
    staged = _staged_evidence(tmp_path)
    with pytest.raises(ValueError, match="overlap"):
        _promote(staged, tmp_path, _backends_for(tmp_path, overlap=True))


def test_promotion_refuses_a_nonzero_exit_code(tmp_path):
    """A smoke that did not exit 0 is not evidence that it ran."""
    staged = _staged_evidence(tmp_path)
    with pytest.raises(ValueError, match="exit_code"):
        _promote(staged, tmp_path, _backends_for(tmp_path, exit_code=1))


def test_promotion_refuses_a_lock_that_is_already_complete(tmp_path):
    """A COMPLETE lock is a published result; promoting it again is a new lineage.

    The first draft deep-copied whatever lock it was handed and overwrote the nine
    fields, so a second promotion onto a COMPLETE lock would have replaced the
    evidence of the first run with that of the second under the same identity --
    the overwrite `CLAUDE.md#provenance` forbids. Establish the input state
    before changing anything.
    """
    staged = _staged_evidence(tmp_path)
    backends = _backends_for(tmp_path)
    publish_promotion(_promote(staged, tmp_path, backends), evidence_dir=staged)
    published = _snapshot(staged)

    with pytest.raises(ValueError, match="COMPLETE"):
        _promote(staged, tmp_path, backends)
    assert _snapshot(staged) == published


def test_publishing_a_promotion_the_validator_refuses_leaves_the_directory_byte_identical(
    tmp_path,
):
    """The validator checks things promotion cannot; its refusal must cost nothing.

    The wheelhouse roster is one of them: promotion derives it from the lock it is
    handed, the validator compares it with the pins in the evidence directory, and
    a pod that resolved its wheelhouse from a stale lock passes the first and fails
    the second. The first producer wrote the five sidecar manifests into the
    evidence directory *before* anyone validated the result, so a refused run left
    files behind under the names the next run would use, and a refused run after a
    successful one overwrote that run's bound sidecars. The contract is now: every
    byte is staged and validated elsewhere first, and a refusal changes nothing
    under the evidence directory.
    """
    staged = _staged_evidence(tmp_path)
    before = _snapshot(staged)
    promotion = _promote(
        staged, tmp_path, _backends_for(tmp_path), wheelhouse=_drifted_wheelhouse(staged, tmp_path)
    )

    with pytest.raises(ActivationEvidenceError):
        publish_promotion(promotion, evidence_dir=staged)
    assert _snapshot(staged) == before


def test_publishing_refuses_when_a_sidecar_name_is_already_taken(tmp_path):
    """A sidecar is published write-once; an existing file under its name is refused.

    The lock is published last and is the commit point, so a crash between the
    sidecars and the lock leaves sidecars without a lock that binds them. The
    next run must not silently overwrite those -- or a stray file of the same
    name -- and it must not publish half the set before finding out: existence
    is established for every name before the first write.
    """
    staged = _staged_evidence(tmp_path)
    promotion = _promote(staged, tmp_path, _backends_for(tmp_path))
    taken = sorted(promotion.files)[-1]
    (staged / taken).write_bytes(b"not this run's")
    before = _snapshot(staged)

    with pytest.raises(FileExistsError, match=taken):
        publish_promotion(promotion, evidence_dir=staged)
    assert _snapshot(staged) == before


def test_the_sidecars_carry_the_names_the_dev_pod_plan_declares(tmp_path):
    """The dev-pod plan's file structure names the sidecars; the producer must use them.

    `docs/superpowers/plans/2026-07-09-compose-dev-pod-real-workers.md` declares
    `{gears,cpa}_smoke_pair_roster.json`, `{gears,cpa}_smoke_artifacts.json` and
    `python_artifact_manifest.json` as the files Task 0.1 creates. The first
    producer invented its own spellings, which the validator accepts (it binds by
    path + SHA, not by name) and the plan's reader would not find.
    """
    staged = _staged_evidence(tmp_path)
    promotion = _promote(staged, tmp_path, _backends_for(tmp_path))
    assert set(promotion.files) == {
        "gears_smoke_pair_roster.json",
        "cpa_smoke_pair_roster.json",
        "gears_smoke_artifacts.json",
        "cpa_smoke_artifacts.json",
        "python_artifact_manifest.json",
    }


def test_promotion_stamps_the_run_identity_and_prose_the_caller_supplies(tmp_path):
    """`generated_at_utc`, `host`, `activation` and `run_gate.summary` are this run's.

    The first producer inherited all four from the INCOMPLETE lock, so a COMPLETE
    lock carried the July compatibility observation's timestamp, host and the prose
    "no immutable smoke manifest ... was captured" -- a record that contradicted
    itself. The validator's INCOMPLETE branch requires the activation text to say
    BLOCKED and its COMPLETE branch does not read the text at all, so an inherited
    BLOCKED text validates COMPLETE while announcing the opposite.
    """
    staged = _staged_evidence(tmp_path)
    promotion = _promote(staged, tmp_path, _backends_for(tmp_path))
    lock = promotion.lock
    assert lock["generated_at_utc"] == _PROSE["generated_at_utc"]
    assert lock["host"] == _HOST
    assert lock["activation"] == _PROSE["activation"]
    assert lock["run_gate"]["summary"] == _PROSE["summary"]


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("activation", "BLOCKED — the smoke input roster was not captured", "BLOCKED"),
        ("activation", "   ", "activation"),
        ("generated_at_utc", "2026-09-05 21:00:00", "generated_at_utc"),
        ("host", {}, "host"),
        ("host", {"gpu": ""}, "host"),
        ("summary", "  ", "summary"),
    ],
    ids=[
        "activation-still-blocked",
        "activation-blank",
        "generated_at-not-utc-iso8601",
        "host-empty",
        "host-blank-value",
        "summary-blank",
    ],
)
def test_promotion_refuses_run_identity_or_prose_it_cannot_stand_behind(
    tmp_path, field, value, match
):
    """Each input is established here rather than left for a later reader to notice.

    The validator's INCOMPLETE branch requires the activation text to contain
    BLOCKED; its COMPLETE branch reads nothing, so a COMPLETE lock that still says
    BLOCKED is the one contradiction nothing downstream refuses. The timestamp is
    the one the plan asks the pod to record; a local-time or free-form value is not
    it. `host` is the pod's identity and an empty or blank one records no pod.
    """
    staged = _staged_evidence(tmp_path)
    with pytest.raises(ValueError, match=match):
        _promote(staged, tmp_path, _backends_for(tmp_path), **{field: value})


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"git_sha": "abc123"}, "git_sha"),
        ({"container_image_digest": "latest"}, "container_image_digest"),
    ],
    ids=["short-git-sha", "image-tag-not-digest"],
)
def test_promotion_refuses_a_malformed_run_identity(tmp_path, override, match):
    """The lock's identity fields are checked here, not left to the validator.

    Establish-before-write, carried to the siblings of the overlap/exit-code checks
    that the first draft stopped at: a 7-character SHA or an image *tag* would have
    been built into the lock and refused at publish time -- the right outcome, but
    after the wheelhouse was hashed and with an error about the lock rather than
    about the input.
    """
    staged = _staged_evidence(tmp_path)
    with pytest.raises(ValueError, match=match):
        _promote(staged, tmp_path, _backends_for(tmp_path), **override)


def test_promotion_refuses_a_backend_record_filed_under_the_other_backend(tmp_path):
    """A gears roster under the cpa key is two records disagreeing about one thing.

    The validator checks `roster["backend"] == backend` per record, so this would
    be refused at publish time. Establishing it here says which input is wrong.
    """
    staged = _staged_evidence(tmp_path)
    backends = _backends_for(tmp_path)
    backends["gears"], backends["cpa"] = backends["cpa"], backends["gears"]
    with pytest.raises(ValueError, match="backend"):
        _promote(staged, tmp_path, backends)


@pytest.mark.parametrize("builder_backend", ["GEARS", "scgpt"])
def test_the_builders_refuse_a_backend_outside_the_protocol_roster(tmp_path, builder_backend):
    """`backend` names a position in the lock; anything else has nowhere to go."""
    with pytest.raises(ValueError, match="backend"):
        build_smoke_pair_roster(
            backend=builder_backend,
            fit_role_artifact={},
            approved_root=tmp_path,
            sealed_pair_ids=TINY_SEALED_PAIRS,
        )
    with pytest.raises(ValueError, match="backend"):
        build_smoke_artifact_manifest(backend=builder_backend, artifacts=_artifact_inputs(tmp_path))


@pytest.mark.parametrize(
    "uri",
    ["file:///workspace/smoke/checkpoint.pt", "/workspace/smoke/checkpoint.pt", "checkpoint.pt"],
    ids=["file-scheme", "absolute-path", "bare-name"],
)
def test_the_artifact_manifest_refuses_a_uri_that_is_not_durable(tmp_path, uri):
    """Task 0.1: "a durable URI"; a pod-local path is gone with the pod."""
    inputs = _artifact_inputs(tmp_path)
    inputs["checkpoint"]["uri"] = uri
    with pytest.raises(ValueError, match="uri"):
        build_smoke_artifact_manifest(backend="gears", artifacts=inputs)


def test_an_artifact_entry_with_an_unexpected_key_is_refused(tmp_path):
    """Passing `sha256` in an entry is the exact thing the builder exists to prevent.

    The digest is measured here; a caller-supplied one was silently ignored, which
    let a caller believe it had been recorded. Unknown keys are refused so that the
    contract is visible at the call site.
    """
    inputs = _artifact_inputs(tmp_path)
    inputs["checkpoint"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="sha256"):
        build_smoke_artifact_manifest(backend="gears", artifacts=inputs)


def test_the_training_roles_are_the_fit_contract_s_allowed_roles(tmp_path):
    """The roster's roles are bound to `ALLOWED_ADAPTER_ROLES`, not retyped."""
    from alive.compose.baselines_combo import ALLOWED_ADAPTER_ROLES

    _, roster, _ = _roster_from(tmp_path)
    assert set(roster["training_roles"]) == set(ALLOWED_ADAPTER_ROLES)


def test_a_wheel_supplied_under_an_unnormalised_name_is_found(tmp_path):
    """`cell_gears` and `cell-gears` are one package; the lookup must know that.

    The first builder normalised names only for the roster comparison and then
    looked the artifact up under the pin's normalised name -- so an underscore in
    the caller's key passed the comparison and raised `KeyError` one line later.
    Normalise once, use the normalised map for everything.
    """
    envs = _wheelhouse_inputs(tmp_path)
    lock, wheels = envs["gears_env"]
    wheels["Cell_GEARS"] = wheels.pop("cell-gears")
    manifest = build_wheelhouse_manifest(environments=envs)
    assert [e["name"] for e in manifest["environments"]["gears_env"]] == ["cell-gears", "torch"]


def test_two_wheels_that_normalise_to_one_package_are_refused(tmp_path):
    """After normalisation a duplicate is two artifacts claiming one pin."""
    envs = _wheelhouse_inputs(tmp_path)
    lock, wheels = envs["gears_env"]
    wheels["cell_gears"] = dict(wheels["cell-gears"])
    with pytest.raises(ValueError, match="cell-gears"):
        build_wheelhouse_manifest(environments=envs)


def test_a_wheel_whose_declared_filename_is_not_the_hashed_file_s_name_is_refused(tmp_path):
    """The manifest names a file and records a digest; they must be the same file."""
    envs = _wheelhouse_inputs(tmp_path)
    lock, wheels = envs["cpa_env"]
    wheels["torch"]["filename"] = "torch-2.4.0-cp312-manylinux.whl"
    with pytest.raises(ValueError, match="filename"):
        build_wheelhouse_manifest(environments=envs)


def test_a_wheel_entry_with_an_unexpected_key_is_refused(tmp_path):
    """Same contract as the artifact entries: a `sha256` supplied here is ignored, so refuse it."""
    envs = _wheelhouse_inputs(tmp_path)
    lock, wheels = envs["cpa_env"]
    wheels["torch"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="sha256"):
        build_wheelhouse_manifest(environments=envs)


def _digests(directory):
    """Every file under `directory` with the SHA-256 of its bytes.

    A refusal must cost nothing, and "nothing" is measured, not asserted: the
    same digest under the same name for every file the directory holds.
    """
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _half_published(staged, *, named="gears_smoke_pair_roster.json"):
    """Rewrite the staged INCOMPLETE lock so it already names one sidecar.

    A pod operator filling `required_evidence` by hand -- the habit this producer
    exists to end -- leaves exactly this: a lock still reading INCOMPLETE that
    nonetheless names a roster manifest. Condition (a) passes on such a lock, so
    only the text search stands between a named file and its deletion.
    """
    lock_path = staged / LOCK_NAME
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["run_gate"]["required_evidence"]["gears"]["pair_roster_manifest_path"] = named
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return lock_path


def test_the_reclaimable_names_are_exactly_the_ones_a_promotion_publishes(tmp_path):
    """`_SIDECAR_NAMES` is a second spelling of what `promote_lock_to_complete` builds.

    Condition (b) needs a name set the reclaimer knows on its own: a caller that
    supplied both the names and the permission to delete them would be checking
    itself. That means two spellings of one roster, and this binds them, so a
    renamed sidecar cannot leave the guard refusing the very files it exists to
    reclaim -- or, worse, accepting a name no promotion writes.
    """
    staged = _staged_evidence(tmp_path)
    promotion = _promote(staged, tmp_path, _backends_for(tmp_path))

    assert set(promotion.files) == _SIDECAR_NAMES


def test_reclaim_removes_only_sidecars_left_by_a_crashed_publish(tmp_path, monkeypatch):
    """The crash `publish_promotion` cannot avoid, and the recovery that used to be `rm`.

    The sidecars are published write-once and the lock last, so a process that
    dies between them leaves sidecars nothing binds, and every retry is refused
    by the write-once guard until someone deletes the files by hand.

    The failure is injected at `alive.compose.smoke_evidence.atomic_write_once`
    -- the name this module imported -- and it INTERRUPTS THE I/O rather than
    mocking a guard away: the write-once publish, the `FileExistsError` refusal
    and the reclaim conditions below are all the committed ones, and what is
    simulated is only a machine that stopped mid-publish.
    """
    staged = _staged_evidence(tmp_path)
    promotion = _promote(staged, tmp_path, _backends_for(tmp_path))
    stray = staged / "operator_notes.txt"
    stray.write_bytes(b"not a sidecar")
    written = []
    real_atomic_write_once = smoke_evidence.atomic_write_once

    def dies_on_the_second_write(path, text, **kwargs):
        if len(written) == 1:
            raise OSError("the pod lost its volume between two sidecars")
        written.append(Path(path).name)
        real_atomic_write_once(path, text, **kwargs)

    monkeypatch.setattr(smoke_evidence, "atomic_write_once", dies_on_the_second_write)
    with pytest.raises(OSError, match="lost its volume"):
        publish_promotion(promotion, evidence_dir=staged)
    monkeypatch.undo()

    assert written == ["cpa_smoke_pair_roster.json"]
    assert (staged / "cpa_smoke_pair_roster.json").is_file()
    assert (
        json.loads((staged / LOCK_NAME).read_text(encoding="utf-8"))["run_gate"]["evidence_status"]
        == "INCOMPLETE"
    )
    with pytest.raises(FileExistsError) as blocked:
        publish_promotion(promotion, evidence_dir=staged)
    assert "cpa_smoke_pair_roster.json" in str(blocked.value)

    removed = reclaim_unbound_sidecars(evidence_dir=staged, sidecar_names=set(promotion.files))

    assert removed == ["cpa_smoke_pair_roster.json"]
    assert not (staged / "cpa_smoke_pair_roster.json").exists()
    assert stray.is_file()
    assert stray.read_bytes() == b"not a sidecar"
    republished = publish_promotion(promotion, evidence_dir=staged)
    assert republished["run_gate"]["evidence_status"] == "COMPLETE"
    assert republished["run_gate"]["seal_safety_status"] == "VERIFIED_ZERO_OVERLAP"


def test_reclaim_refuses_under_a_complete_lock(tmp_path):
    """A COMPLETE lock's record binds these five files by SHA-256; nothing there is loose.

    The reclaim path is the one place in this module that deletes, so its first
    question is about the lock, not about the files: under a published result
    every sidecar is bound evidence and the directory is never touched. The
    refusal must say THAT -- the lock is COMPLETE -- because it is the condition
    that makes the whole request wrong, not merely each file.
    """
    staged = _staged_evidence(tmp_path)
    promotion = _promote(staged, tmp_path, _backends_for(tmp_path))
    publish_promotion(promotion, evidence_dir=staged)
    published = _digests(staged)

    with pytest.raises(ActivationEvidenceError) as refusal:
        reclaim_unbound_sidecars(evidence_dir=staged, sidecar_names=set(promotion.files))

    assert "condition (a)" in str(refusal.value)
    assert "evidence_status=COMPLETE" in str(refusal.value)
    assert _digests(staged) == published


def test_reclaim_refuses_a_name_outside_this_promotion(tmp_path):
    """The name set is a permission, not a target list handed in with the request.

    `sidecar_names` comes from `Promotion.files`, so the caller names the files a
    promotion would write. A name from anywhere else is refused rather than
    deleted; otherwise the parameter is an `rm` list under an evidence directory
    with a checked-conditions story attached.
    """
    staged = _staged_evidence(tmp_path)
    promotion = _promote(staged, tmp_path, _backends_for(tmp_path))
    stray = staged / "operator_scratch.json"
    stray.write_bytes(b"{}\n")

    with pytest.raises(ActivationEvidenceError) as refusal:
        reclaim_unbound_sidecars(
            evidence_dir=staged,
            sidecar_names={*promotion.files, "operator_scratch.json"},
        )

    assert "condition (b)" in str(refusal.value)
    assert "operator_scratch.json" in str(refusal.value)
    assert stray.is_file()
    assert stray.read_bytes() == b"{}\n"


def test_reclaim_refuses_a_sidecar_the_lock_references(tmp_path):
    """A sidecar the lock names is bound, whatever the lock's status says.

    Condition (a) only establishes that the lock is not a published result; it
    does not establish that the lock has no claim on these bytes. A half-filled
    INCOMPLETE lock naming a roster manifest is a real state -- the record was
    being written by hand -- and deleting the file it names would leave the lock
    pointing at nothing.
    """
    staged = _staged_evidence(tmp_path)
    _half_published(staged)
    named = staged / "gears_smoke_pair_roster.json"
    named.write_bytes(b"half-published roster")

    with pytest.raises(ActivationEvidenceError) as refusal:
        reclaim_unbound_sidecars(
            evidence_dir=staged, sidecar_names={"gears_smoke_pair_roster.json"}
        )

    assert "condition (c)" in str(refusal.value)
    assert "gears_smoke_pair_roster.json" in str(refusal.value)
    assert named.is_file()
    assert named.read_bytes() == b"half-published roster"


def test_reclaim_leaves_the_directory_byte_identical_when_it_refuses(tmp_path):
    """A refused reclaim is a WHOLE refusal: not even the clean candidate goes.

    Two leftovers, one of them named by the lock. Checking condition (c) inside
    the deletion loop would remove the first (it sorts first and is genuinely
    unbound) and refuse the second, which is hand-deletion with extra steps: the
    operator is left with a half-reclaimed directory and an error, and no record
    of which half went.
    """
    staged = _staged_evidence(tmp_path)
    _half_published(staged)
    (staged / "cpa_smoke_artifacts.json").write_bytes(b"unbound leftover")
    (staged / "gears_smoke_pair_roster.json").write_bytes(b"named by the lock")
    before = _digests(staged)

    with pytest.raises(ActivationEvidenceError) as refusal:
        reclaim_unbound_sidecars(
            evidence_dir=staged,
            sidecar_names={"cpa_smoke_artifacts.json", "gears_smoke_pair_roster.json"},
        )

    assert "condition (c)" in str(refusal.value)
    assert _digests(staged) == before


def test_reclaim_finds_nothing_to_do_in_a_directory_no_publish_touched(tmp_path):
    """Nothing present is not an error: reclaim is safe to run before every retry.

    This test's claim is a NEGATIVE about raising, and a version that simply
    called the function proved it only by letting the exception escape into the
    production frame -- which this repository does not count as a kill (Codex
    review of 319229a, Important 1). The call is captured, so "it raised" becomes
    a named failure in this test's own frame that says what was raised; the
    success path still asserts both what came back and that not one byte of the
    directory moved.
    """
    staged = _staged_evidence(tmp_path)
    before = _digests(staged)

    raised: Exception | None = None
    removed: list[str] | None = None
    # Broad on purpose: the claim is that NOTHING is raised, so narrowing the
    # except would let the next unexpected type escape the frame again.
    try:
        removed = reclaim_unbound_sidecars(evidence_dir=staged, sidecar_names=_SIDECAR_NAMES)
    except Exception as exc:
        raised = exc

    assert raised is None, (
        f"reclaim must not raise when nothing is present, but raised "
        f"{type(raised).__name__}: {raised}"
    )
    assert removed == []
    assert _digests(staged) == before
