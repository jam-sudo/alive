"""Tests for strict dependency/resource activation-evidence validation."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from alive.compose.activation_evidence import (
    ActivationEvidenceError,
    validate_dependency_lock,
    validate_go_resource_manifest,
)
from alive.provenance import sha256_json

_ROOT = Path("docs/activation-evidence/compose")
_DEPENDENCY = _ROOT / "gears_cpa_dependency_lock.json"
_GO = _ROOT / "go_resource_manifest.json"


def _reseal(payload: dict) -> None:
    payload["manifest_checksum"] = sha256_json(
        {key: value for key, value in payload.items() if key != "manifest_checksum"}
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _dependency_copy(tmp_path: Path) -> tuple[Path, dict]:
    for name in (
        "requirements.gears_env.lock",
        "requirements.cpa_env.lock",
        "go_resource_manifest.json",
    ):
        shutil.copyfile(_ROOT / name, tmp_path / name)
    payload = json.loads(_DEPENDENCY.read_text(encoding="utf-8"))
    path = tmp_path / "gears_cpa_dependency_lock.json"
    _write_json(path, payload)
    return path, payload


def test_committed_go_manifest_is_strict_and_complete() -> None:
    payload = validate_go_resource_manifest(_GO)
    assert payload["dataset"]["persistent_id"] == "doi:10.7910/DVN/Q2ZV3E"
    assert payload["dataset"]["license"]["spdx"] == "CC0-1.0"


def test_committed_dependency_lock_is_honestly_blocked() -> None:
    payload = validate_dependency_lock(_DEPENDENCY)
    assert payload["run_gate"]["evidence_status"] == "INCOMPLETE"
    assert payload["both_backends_runtime_smoke_observed_on_norman"] is True
    assert payload["both_backends_run_evidence_complete"] is False


def test_go_manifest_checksum_tamper_rejected(tmp_path: Path) -> None:
    payload = json.loads(_GO.read_text(encoding="utf-8"))
    payload["resources"][0]["bytes"] += 1
    path = tmp_path / "go.json"
    _write_json(path, payload)
    with pytest.raises(ActivationEvidenceError, match="manifest_checksum"):
        validate_go_resource_manifest(path)


def test_go_license_must_be_exact(tmp_path: Path) -> None:
    payload = json.loads(_GO.read_text(encoding="utf-8"))
    payload["dataset"]["license"]["spdx"] = "UNKNOWN"
    _reseal(payload)
    path = tmp_path / "go.json"
    _write_json(path, payload)
    with pytest.raises(ActivationEvidenceError, match="CC0"):
        validate_go_resource_manifest(path)


def test_go_upstream_identity_cannot_be_resealed_to_other_bytes(tmp_path: Path) -> None:
    payload = json.loads(_GO.read_text(encoding="utf-8"))
    payload["resources"][0]["upstream_md5"] = "0" * 32
    payload["resources"][0]["sha256"] = "0" * 64
    _reseal(payload)
    path = tmp_path / "go.json"
    _write_json(path, payload)
    with pytest.raises(ActivationEvidenceError, match="upstream MD5 mismatch"):
        validate_go_resource_manifest(path)


def test_dependency_requirements_file_sha_tamper_rejected(tmp_path: Path) -> None:
    path, _payload = _dependency_copy(tmp_path)
    with (tmp_path / "requirements.gears_env.lock").open("a", encoding="utf-8") as handle:
        handle.write("tampered-package==1\n")
    with pytest.raises(ActivationEvidenceError, match=r"requirements lock.*SHA"):
        validate_dependency_lock(path)


def test_dependency_backend_pin_is_exact_even_after_rehash(tmp_path: Path) -> None:
    path, payload = _dependency_copy(tmp_path)
    requirements = tmp_path / "requirements.cpa_env.lock"
    requirements.write_text(
        requirements.read_text(encoding="utf-8").replace("cpa-tools==0.8.5", "cpa-tools==0.8.6"),
        encoding="utf-8",
    )
    payload["environments"]["cpa_env"]["requirements_lock_sha256"] = hashlib.sha256(
        requirements.read_bytes()
    ).hexdigest()
    _reseal(payload)
    _write_json(path, payload)
    with pytest.raises(ActivationEvidenceError, match="cpa-tools==0.8.5"):
        validate_dependency_lock(path)


def test_incomplete_evidence_cannot_claim_completion(tmp_path: Path) -> None:
    path, payload = _dependency_copy(tmp_path)
    payload["both_backends_run_evidence_complete"] = True
    _reseal(payload)
    _write_json(path, payload)
    with pytest.raises(ActivationEvidenceError, match="cannot claim completion"):
        validate_dependency_lock(path)


def test_complete_claim_requires_zero_overlap_and_content_hashes(tmp_path: Path) -> None:
    path, payload = _dependency_copy(tmp_path)
    payload["run_gate"]["evidence_status"] = "COMPLETE"
    payload["run_gate"]["seal_safety_status"] = "VERIFIED_ZERO_OVERLAP"
    payload["both_backends_run_evidence_complete"] = True
    payload["environment_reproducibility"]["package_artifact_hashes_complete"] = True
    payload["environment_reproducibility"]["wheelhouse_manifest_sha256"] = "a" * 64
    payload["environment_reproducibility"]["container_image_digest"] = "sha256:" + "b" * 64
    # Deliberately leave the per-backend evidence fields null.
    _reseal(payload)
    _write_json(path, payload)
    with pytest.raises(ActivationEvidenceError, match="must be 64 lowercase hex"):
        validate_dependency_lock(path)


def test_dependency_go_file_sha_tamper_rejected(tmp_path: Path) -> None:
    path, _payload = _dependency_copy(tmp_path)
    go_path = tmp_path / "go_resource_manifest.json"
    with go_path.open("a", encoding="utf-8") as handle:
        handle.write(" ")
    observed = hashlib.sha256(go_path.read_bytes()).hexdigest()
    assert observed != json.loads(path.read_text())["go_resource_manifest"]["sha256"]
    with pytest.raises(ActivationEvidenceError, match="GO resource manifest file SHA"):
        validate_dependency_lock(path)


def test_dependency_relative_symlink_cannot_escape_evidence_directory(tmp_path: Path) -> None:
    path, _payload = _dependency_copy(tmp_path)
    go_path = tmp_path / "go_resource_manifest.json"
    go_path.unlink()
    go_path.symlink_to(_GO.resolve())
    with pytest.raises(ActivationEvidenceError, match="escapes its evidence directory"):
        validate_dependency_lock(path)
