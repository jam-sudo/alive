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

import pytest

from alive.compose.activation_evidence import (
    ActivationEvidenceError,
    _validate_pair_roster_manifest,
    _validate_pinned_requirements,
    _validate_smoke_artifact_manifest,
    _validate_wheelhouse_manifest,
)
from alive.compose.smoke_evidence import (
    build_smoke_artifact_manifest,
    build_smoke_pair_roster,
    build_wheelhouse_manifest,
)


def _write(tmp_path, payload):
    path = tmp_path / "roster.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_emitted_roster_and_record_are_accepted_by_the_committed_validator(tmp_path):
    """One call emits both sides, so the validator's cross-checks cannot disagree.

    `_validate_pair_roster_manifest` requires the record's
    `training_pair_roster_sha256` / `sealed_pair_roster_sha256` /
    `sealed_pair_overlap_count` to match the manifest it is handed. Producing the
    two separately means getting the same thing right twice; producing them from
    one computation makes the cross-check true by construction.
    """
    roster, record = build_smoke_pair_roster(
        backend="gears",
        training_pair_ids=["A+B", "C+D"],
        sealed_pair_ids=["W+X", "Y+Z"],
    )
    _validate_pair_roster_manifest(_write(tmp_path, roster), backend="gears", record=record)


def test_the_roster_is_canonicalised_sorted_and_unique(tmp_path):
    """Task 0.1 requires canonical sorted unique rosters; the caller must not have to.

    The validator refuses `values != sorted(set(values))`. Normalising here rather
    than at every call site means one place can be wrong instead of many, and the
    hashes in the record are taken from the SAME normalised list the manifest
    carries.
    """
    roster, record = build_smoke_pair_roster(
        backend="cpa",
        training_pair_ids=["C+D", "A+B", "C+D"],
        sealed_pair_ids=["Y+Z", "W+X", "W+X"],
    )
    assert roster["training_pair_ids"] == ["A+B", "C+D"]
    assert roster["sealed_pair_ids"] == ["W+X", "Y+Z"]
    _validate_pair_roster_manifest(_write(tmp_path, roster), backend="cpa", record=record)


def test_a_sealed_pair_in_the_training_roster_fails_closed(tmp_path):
    """Task 0.1's named acceptance condition: one sealed pair in training refuses.

    The producer must REPORT the overlap, never launder it. A "helpful"
    implementation that silently dropped overlapping pairs from the training
    roster would hand the validator a clean roster while the smoke had in fact
    fitted on a sealed pair -- evidence that certifies the opposite of what
    happened. That mutation is what this test exists to kill.
    """
    roster, record = build_smoke_pair_roster(
        backend="gears",
        training_pair_ids=["A+B", "W+X"],
        sealed_pair_ids=["W+X", "Y+Z"],
    )
    assert record["sealed_pair_overlap_count"] == 1
    assert "W+X" in roster["training_pair_ids"]
    with pytest.raises(ActivationEvidenceError, match="overlaps sealed pairs"):
        _validate_pair_roster_manifest(_write(tmp_path, roster), backend="gears", record=record)


_ARTIFACT_NAMES = (
    "norman_source",
    "fit_role_artifact",
    "fit_role_row_identity",
    "smoke_script",
    "command_log",
    "checkpoint",
)


def _artifact_inputs(tmp_path):
    """Six real files plus a durable URI and immutable version for each."""
    inputs = {}
    for index, name in enumerate(_ARTIFACT_NAMES):
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
