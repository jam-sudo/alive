"""Strict validators for COMPOSE activation-time dependency/resource evidence.

The scientific boundary must not treat a prose claim such as ``RUN-verified``
as evidence.  These validators bind the dependency lock to its requirements
files and GO-resource manifest, and distinguish a compatibility observation
from a complete, seal-safe run-smoke attestation.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from alive.provenance import sha256_json

__all__ = [
    "ActivationEvidenceError",
    "DEPENDENCY_LOCK_SCHEMA",
    "GO_RESOURCE_MANIFEST_SCHEMA",
    "validate_dependency_lock",
    "validate_go_resource_manifest",
]

GO_RESOURCE_MANIFEST_SCHEMA = "compose_go_resource_manifest_v2"
DEPENDENCY_LOCK_SCHEMA = "compose_gears_cpa_dependency_lock_v2"
_PROTOCOL = "COMPOSE-K562-v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_GO_TOP_KEYS = frozenset(
    {"schema", "protocol", "purpose", "dataset", "acquisition", "resources", "manifest_checksum"}
)
_GO_DATASET_KEYS = frozenset(
    {"title", "persistent_id", "doi_url", "publisher", "license", "metadata_api"}
)
_GO_LICENSE_KEYS = frozenset({"name", "spdx", "url"})
_GO_ACQUISITION_KEYS = frozenset(
    {"method", "retrieved_utc", "retrieved_git_sha", "pod", "opened_seal"}
)
_GO_RESOURCE_KEYS = frozenset(
    {
        "name",
        "source_filename",
        "role",
        "url",
        "dataverse_datafile_id",
        "dataset_version",
        "file_version",
        "bytes",
        "upstream_md5",
        "sha256",
        "derivation",
    }
)
_GO_EXTRACTED_KEYS = frozenset({"name", "bytes", "sha256", "derivation"})
_EXPECTED_GO_RESOURCES = {
    "gene2go_all.pkl": (
        6153417,
        "3.0",
        9462558,
        "77c9af0c61c30ea4d7a85680f4d122dc",
        "f145c5e84a53048d87942a417d870a4f2d8db50200b96e492b358c13aba8c771",
    ),
    "essential_all_data_pert_genes.pkl": (
        6934320,
        "7.0",
        558811,
        "b7bc2a91ca513b86f27f090d963711a6",
        "46c3dfe354d8ad5c0da22c69f3d0ca451987b1a61ed9d984279b22b9565ff8d7",
    ),
    "go_essential_all.tar.gz": (
        6934319,
        "7.0",
        60654049,
        "b8bff0d53407f26648330d264df7fe16",
        "98a14a60e8b76f76fd172570d023a6036775f151604ec01340b3fec7d36693da",
    ),
}
_EXPECTED_EXTRACTED_GO = {
    "name": "go_essential_all/go_essential_all.csv",
    "bytes": 354733543,
    "sha256": "99622d9215462e7bbea99a5f6c0b1e86febfef9f57226269418053484fcb3f9f",
}

_DEPENDENCY_TOP_KEYS = frozenset(
    {
        "schema",
        "activation",
        "both_backends_import_ok",
        "both_backends_runtime_smoke_observed_on_norman",
        "both_backends_run_evidence_complete",
        "deliverable",
        "run_gate",
        "go_resource_manifest",
        "environment_reproducibility",
        "environments",
        "generated_at_utc",
        "git_sha",
        "host",
        "indexes",
        "isolation_rationale",
        "protocol",
        "manifest_checksum",
    }
)
_RUN_GATE_KEYS = frozenset(
    {
        "schema",
        "evidence_status",
        "seal_safety_status",
        "summary",
        "observations",
        "required_evidence",
        "missing_evidence",
    }
)
_RUN_EVIDENCE_KEYS = frozenset(
    {
        "norman_source_sha256",
        "fit_role_artifact_sha256",
        "fit_role_row_identity_sha256",
        "training_pair_roster_sha256",
        "sealed_pair_roster_sha256",
        "sealed_pair_overlap_count",
        "pair_roster_manifest_path",
        "pair_roster_manifest_sha256",
        "artifact_manifest_path",
        "artifact_manifest_sha256",
        "smoke_script_sha256",
        "command_log_sha256",
        "checkpoint_sha256",
        "exit_code",
    }
)
_DIGEST_EVIDENCE_KEYS = frozenset(
    {
        "norman_source_sha256",
        "fit_role_artifact_sha256",
        "fit_role_row_identity_sha256",
        "training_pair_roster_sha256",
        "sealed_pair_roster_sha256",
        "pair_roster_manifest_sha256",
        "artifact_manifest_sha256",
        "smoke_script_sha256",
        "command_log_sha256",
        "checkpoint_sha256",
    }
)
_REPRODUCIBILITY_KEYS = frozenset(
    {
        "version_pins_complete",
        "package_artifact_hashes_complete",
        "wheelhouse_manifest_path",
        "wheelhouse_manifest_sha256",
        "container_image_digest",
        "status",
    }
)
_EXPECTED_BACKEND_PINS = {"gears": ("cell-gears", "0.1.2"), "cpa": ("cpa-tools", "0.8.5")}
_PAIR_ROSTER_KEYS = frozenset(
    {
        "schema",
        "protocol",
        "backend",
        "training_roles",
        "training_pair_ids",
        "sealed_pair_ids",
        "manifest_checksum",
    }
)
_WHEELHOUSE_TOP_KEYS = frozenset({"schema", "environments", "manifest_checksum"})
_WHEELHOUSE_ARTIFACT_KEYS = frozenset({"name", "version", "filename", "source_url", "sha256"})
_SMOKE_ARTIFACT_TOP_KEYS = frozenset(
    {"schema", "protocol", "backend", "artifacts", "manifest_checksum"}
)
_SMOKE_ARTIFACT_ENTRY_KEYS = frozenset({"uri", "immutable_version", "sha256"})
_SMOKE_ARTIFACT_RECORD_FIELDS = {
    "norman_source": "norman_source_sha256",
    "fit_role_artifact": "fit_role_artifact_sha256",
    "fit_role_row_identity": "fit_role_row_identity_sha256",
    "smoke_script": "smoke_script_sha256",
    "command_log": "command_log_sha256",
    "checkpoint": "checkpoint_sha256",
}


class ActivationEvidenceError(ValueError):
    """Raised when activation evidence is malformed, unbound, or overclaims readiness."""


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ActivationEvidenceError(f"cannot read JSON evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ActivationEvidenceError(f"evidence {path} must be a JSON object")
    return value


def _exact_keys(value: Any, expected: frozenset[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActivationEvidenceError(f"{where} must be an object")
    actual = set(value)
    if actual != set(expected):
        raise ActivationEvidenceError(
            f"{where} key roster mismatch: missing={sorted(expected - actual)} "
            f"unexpected={sorted(actual - expected)}"
        )
    return value


def _verify_manifest_checksum(payload: dict[str, Any], where: str) -> None:
    checksum = payload.get("manifest_checksum")
    if not isinstance(checksum, str) or _HEX64.fullmatch(checksum) is None:
        raise ActivationEvidenceError(f"{where}.manifest_checksum must be 64 lowercase hex")
    body = {key: value for key, value in payload.items() if key != "manifest_checksum"}
    if checksum != sha256_json(body):
        raise ActivationEvidenceError(f"{where}.manifest_checksum does not match payload")


def _require_nonempty_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActivationEvidenceError(f"{where} must be a non-empty string")
    return value


def _bound_relative_file(
    parent: Path,
    relative_value: Any,
    expected_sha: Any,
    where: str,
) -> Path:
    relative = Path(_require_nonempty_string(relative_value, f"{where}.path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ActivationEvidenceError(f"{where} path must be safe and relative")
    if _HEX64.fullmatch(str(expected_sha)) is None:
        raise ActivationEvidenceError(f"{where} SHA-256 is malformed")
    try:
        base = parent.resolve(strict=True)
        path = (parent / relative).resolve(strict=True)
        if not path.is_relative_to(base):
            raise ActivationEvidenceError(f"{where} path escapes its evidence directory")
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ActivationEvidenceError(f"cannot read {where}: {exc}") from exc
    if observed != expected_sha:
        raise ActivationEvidenceError(f"{where} file SHA mismatch")
    return path


def validate_go_resource_manifest(path: str | Path) -> dict[str, Any]:
    """Validate the exact GEARS GO-resource identity and licensing contract."""
    manifest_path = Path(path)
    payload = _exact_keys(_load_object(manifest_path), _GO_TOP_KEYS, "go_resource_manifest")
    if payload["schema"] != GO_RESOURCE_MANIFEST_SCHEMA or payload["protocol"] != _PROTOCOL:
        raise ActivationEvidenceError("GO resource manifest schema/protocol mismatch")
    _verify_manifest_checksum(payload, "go_resource_manifest")

    dataset = _exact_keys(payload["dataset"], _GO_DATASET_KEYS, "go_resource_manifest.dataset")
    expected_dataset = {
        "title": "PertNet",
        "persistent_id": "doi:10.7910/DVN/Q2ZV3E",
        "doi_url": "https://doi.org/10.7910/DVN/Q2ZV3E",
        "publisher": "Harvard Dataverse",
        "metadata_api": (
            "https://dataverse.harvard.edu/api/datasets/:persistentId/"
            "?persistentId=doi:10.7910/DVN/Q2ZV3E"
        ),
    }
    for key, expected in expected_dataset.items():
        if dataset[key] != expected:
            raise ActivationEvidenceError(f"GO resource dataset {key} mismatch")
    license_block = _exact_keys(
        dataset["license"], _GO_LICENSE_KEYS, "go_resource_manifest.dataset.license"
    )
    if license_block != {
        "name": "CC0 1.0",
        "spdx": "CC0-1.0",
        "url": "https://creativecommons.org/publicdomain/zero/1.0/",
    }:
        raise ActivationEvidenceError("GO resource dataset license must be exact CC0-1.0")

    acquisition = _exact_keys(
        payload["acquisition"], _GO_ACQUISITION_KEYS, "go_resource_manifest.acquisition"
    )
    if acquisition["opened_seal"] is not False:
        raise ActivationEvidenceError("GO resource acquisition must not open the seal")
    if _HEX40.fullmatch(str(acquisition["retrieved_git_sha"])) is None:
        raise ActivationEvidenceError("GO resource retrieved_git_sha must be a full Git SHA")

    resources = payload["resources"]
    if not isinstance(resources, list) or len(resources) != len(_EXPECTED_GO_RESOURCES):
        raise ActivationEvidenceError("GO resource manifest must carry exactly three resources")
    seen: set[str] = set()
    for index, raw in enumerate(resources):
        expected_keys = _GO_RESOURCE_KEYS | ({"extracted_artifact"} if index == 2 else set())
        resource = _exact_keys(
            raw, frozenset(expected_keys), f"go_resource_manifest.resources[{index}]"
        )
        name = _require_nonempty_string(resource["name"], f"resources[{index}].name")
        if name in seen or name not in _EXPECTED_GO_RESOURCES:
            raise ActivationEvidenceError(f"unexpected/duplicate GO resource {name!r}")
        seen.add(name)
        datafile_id, dataset_version, byte_count, upstream_md5, sha256 = _EXPECTED_GO_RESOURCES[
            name
        ]
        if resource["dataverse_datafile_id"] != datafile_id:
            raise ActivationEvidenceError(f"{name}: Dataverse datafile ID mismatch")
        if resource["url"] != f"https://dataverse.harvard.edu/api/access/datafile/{datafile_id}":
            raise ActivationEvidenceError(f"{name}: Dataverse URL mismatch")
        if resource["dataset_version"] != dataset_version or resource["file_version"] != 1:
            raise ActivationEvidenceError(f"{name}: dataset/file version mismatch")
        if (
            isinstance(resource["bytes"], bool)
            or not isinstance(resource["bytes"], int)
            or resource["bytes"] != byte_count
        ):
            raise ActivationEvidenceError(f"{name}: byte count mismatch")
        if resource["upstream_md5"] != upstream_md5:
            raise ActivationEvidenceError(f"{name}: upstream MD5 mismatch")
        if resource["sha256"] != sha256:
            raise ActivationEvidenceError(f"{name}: acquired SHA-256 mismatch")
        for key in ("source_filename", "role", "derivation"):
            _require_nonempty_string(resource[key], f"{name}.{key}")
        if name == "go_essential_all.tar.gz":
            extracted = _exact_keys(
                resource["extracted_artifact"],
                _GO_EXTRACTED_KEYS,
                f"{name}.extracted_artifact",
            )
            for key, expected in _EXPECTED_EXTRACTED_GO.items():
                if extracted[key] != expected:
                    raise ActivationEvidenceError(f"extracted GO CSV {key} mismatch")
    if seen != set(_EXPECTED_GO_RESOURCES):
        raise ActivationEvidenceError("GO resource roster mismatch")
    return payload


def _validate_pinned_requirements(path: Path) -> dict[str, str]:
    try:
        lines = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except OSError as exc:
        raise ActivationEvidenceError(f"cannot read requirements lock {path}: {exc}") from exc
    pins: dict[str, str] = {}
    for line in lines:
        if line.count("==") != 1 or line.startswith(("-", "http://", "https://")):
            raise ActivationEvidenceError(f"requirements lock has an unpinned entry: {line!r}")
        name, version = line.split("==", 1)
        if not name or not version:
            raise ActivationEvidenceError(f"requirements lock has a malformed pin: {line!r}")
        normalized = name.lower().replace("_", "-")
        if normalized in pins:
            raise ActivationEvidenceError("requirements lock contains duplicate packages")
        pins[normalized] = version
    if not pins:
        raise ActivationEvidenceError("requirements lock must not be empty")
    return pins


def _validate_pair_roster_manifest(
    path: Path,
    *,
    backend: str,
    record: dict[str, Any],
) -> None:
    roster = _exact_keys(_load_object(path), _PAIR_ROSTER_KEYS, f"{backend} pair roster")
    _verify_manifest_checksum(roster, f"{backend} pair roster")
    if (
        roster["schema"] != "compose_smoke_pair_roster_v1"
        or roster["protocol"] != _PROTOCOL
        or roster["backend"] != backend
    ):
        raise ActivationEvidenceError(f"{backend} pair-roster identity mismatch")
    if roster["training_roles"] != ["singles", "combo_calibration"]:
        raise ActivationEvidenceError(f"{backend} training roles are not the exact fit roster")

    pair_sets: dict[str, set[str]] = {}
    for key in ("training_pair_ids", "sealed_pair_ids"):
        values = roster[key]
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value for value in values)
            or values != sorted(set(values))
        ):
            raise ActivationEvidenceError(
                f"{backend} {key} must be a non-empty sorted unique string list"
            )
        pair_sets[key] = set(values)
    overlap = pair_sets["training_pair_ids"] & pair_sets["sealed_pair_ids"]
    if record["sealed_pair_overlap_count"] != len(overlap) or overlap:
        raise ActivationEvidenceError(f"{backend} smoke training roster overlaps sealed pairs")
    if record["training_pair_roster_sha256"] != sha256_json(roster["training_pair_ids"]):
        raise ActivationEvidenceError(f"{backend} training pair-roster hash mismatch")
    if record["sealed_pair_roster_sha256"] != sha256_json(roster["sealed_pair_ids"]):
        raise ActivationEvidenceError(f"{backend} sealed pair-roster hash mismatch")


def _validate_wheelhouse_manifest(
    path: Path,
    expected_pins: dict[str, dict[str, str]],
) -> None:
    manifest = _exact_keys(_load_object(path), _WHEELHOUSE_TOP_KEYS, "wheelhouse manifest")
    _verify_manifest_checksum(manifest, "wheelhouse manifest")
    if manifest["schema"] != "compose_python_artifact_manifest_v1":
        raise ActivationEvidenceError("wheelhouse manifest schema mismatch")
    environments = _exact_keys(
        manifest["environments"],
        frozenset({"gears_env", "cpa_env"}),
        "wheelhouse manifest environments",
    )
    for env_name, pins in expected_pins.items():
        artifacts = environments[env_name]
        if not isinstance(artifacts, list):
            raise ActivationEvidenceError(f"wheelhouse {env_name} must be a list")
        observed: dict[str, str] = {}
        for index, raw in enumerate(artifacts):
            artifact = _exact_keys(
                raw,
                _WHEELHOUSE_ARTIFACT_KEYS,
                f"wheelhouse {env_name}[{index}]",
            )
            name = _require_nonempty_string(artifact["name"], f"{env_name}[{index}].name")
            normalized = name.lower().replace("_", "-")
            if normalized in observed:
                raise ActivationEvidenceError(f"wheelhouse {env_name} has duplicate {normalized}")
            observed[normalized] = _require_nonempty_string(
                artifact["version"], f"{env_name}[{index}].version"
            )
            for field in ("filename", "source_url"):
                _require_nonempty_string(artifact[field], f"{env_name}[{index}].{field}")
            if _HEX64.fullmatch(str(artifact["sha256"])) is None:
                raise ActivationEvidenceError(f"wheelhouse {env_name}[{index}] SHA is malformed")
        if observed != pins:
            raise ActivationEvidenceError(f"wheelhouse {env_name} package roster mismatch")


def _validate_smoke_artifact_manifest(
    path: Path,
    *,
    backend: str,
    record: dict[str, Any],
) -> None:
    manifest = _exact_keys(
        _load_object(path),
        _SMOKE_ARTIFACT_TOP_KEYS,
        f"{backend} smoke artifact manifest",
    )
    _verify_manifest_checksum(manifest, f"{backend} smoke artifact manifest")
    if (
        manifest["schema"] != "compose_backend_smoke_artifact_manifest_v1"
        or manifest["protocol"] != _PROTOCOL
        or manifest["backend"] != backend
    ):
        raise ActivationEvidenceError(f"{backend} smoke artifact identity mismatch")
    artifacts = _exact_keys(
        manifest["artifacts"],
        frozenset(_SMOKE_ARTIFACT_RECORD_FIELDS),
        f"{backend} smoke artifacts",
    )
    for name, record_field in _SMOKE_ARTIFACT_RECORD_FIELDS.items():
        artifact = _exact_keys(
            artifacts[name],
            _SMOKE_ARTIFACT_ENTRY_KEYS,
            f"{backend} smoke artifact {name}",
        )
        uri = _require_nonempty_string(artifact["uri"], f"{backend}.{name}.uri")
        if re.match(r"^[a-z][a-z0-9+.-]*:", uri) is None or uri.startswith("file:"):
            raise ActivationEvidenceError(f"{backend}.{name}.uri must be a durable URI")
        _require_nonempty_string(
            artifact["immutable_version"], f"{backend}.{name}.immutable_version"
        )
        if artifact["sha256"] != record[record_field]:
            raise ActivationEvidenceError(f"{backend}.{name} artifact hash mismatch")


def _validate_complete_run_evidence(run_gate: dict[str, Any], lock_parent: Path) -> None:
    evidence = _exact_keys(
        run_gate["required_evidence"], frozenset({"gears", "cpa"}), "run_gate.required_evidence"
    )
    for backend in ("gears", "cpa"):
        record = _exact_keys(
            evidence[backend], _RUN_EVIDENCE_KEYS, f"run_gate.required_evidence.{backend}"
        )
        for field in _DIGEST_EVIDENCE_KEYS:
            if _HEX64.fullmatch(str(record[field])) is None:
                raise ActivationEvidenceError(f"{backend}.{field} must be 64 lowercase hex")
        roster_path = _bound_relative_file(
            lock_parent,
            record["pair_roster_manifest_path"],
            record["pair_roster_manifest_sha256"],
            f"{backend} pair roster",
        )
        _validate_pair_roster_manifest(roster_path, backend=backend, record=record)
        artifact_manifest_path = _bound_relative_file(
            lock_parent,
            record["artifact_manifest_path"],
            record["artifact_manifest_sha256"],
            f"{backend} smoke artifact manifest",
        )
        _validate_smoke_artifact_manifest(
            artifact_manifest_path,
            backend=backend,
            record=record,
        )
        if record["exit_code"] != 0:
            raise ActivationEvidenceError(f"{backend} smoke exit_code must be zero")


def validate_dependency_lock(path: str | Path) -> dict[str, Any]:
    """Validate dependency pins and fail closed on incomplete run-smoke evidence."""
    lock_path = Path(path)
    payload = _exact_keys(_load_object(lock_path), _DEPENDENCY_TOP_KEYS, "dependency_lock")
    if payload["schema"] != DEPENDENCY_LOCK_SCHEMA or payload["protocol"] != _PROTOCOL:
        raise ActivationEvidenceError("dependency lock schema/protocol mismatch")
    _verify_manifest_checksum(payload, "dependency_lock")
    if _HEX40.fullmatch(str(payload["git_sha"])) is None:
        raise ActivationEvidenceError("dependency lock git_sha must be a full Git SHA")

    go_ref = _exact_keys(
        payload["go_resource_manifest"],
        frozenset({"path", "sha256"}),
        "dependency_lock.go_resource_manifest",
    )
    if _HEX64.fullmatch(str(go_ref["sha256"])) is None:
        raise ActivationEvidenceError("GO resource manifest file SHA is malformed")
    go_path = _bound_relative_file(
        lock_path.parent,
        go_ref["path"],
        go_ref["sha256"],
        "GO resource manifest",
    )
    validate_go_resource_manifest(go_path)

    environments = _exact_keys(
        payload["environments"], frozenset({"gears_env", "cpa_env"}), "dependency_lock.environments"
    )
    environment_pins: dict[str, dict[str, str]] = {}
    for backend in ("gears", "cpa"):
        env = environments[f"{backend}_env"]
        if not isinstance(env, dict):
            raise ActivationEvidenceError(f"{backend}_env must be an object")
        for key in (
            "requirements_lock",
            "requirements_lock_sha256",
            "target_backend",
            "target_import_ok",
            "target_runtime_smoke_observed_on_norman",
            "target_run_evidence_complete",
        ):
            if key not in env:
                raise ActivationEvidenceError(f"{backend}_env missing {key!r}")
        requirements_path = _bound_relative_file(
            lock_path.parent,
            env["requirements_lock"],
            env["requirements_lock_sha256"],
            f"{backend} requirements lock",
        )
        pins = _validate_pinned_requirements(requirements_path)
        environment_pins[f"{backend}_env"] = pins
        package, version = _EXPECTED_BACKEND_PINS[backend]
        if pins.get(package) != version:
            raise ActivationEvidenceError(
                f"{backend} requirements lock must pin {package}=={version}"
            )
        if env["n_packages"] != len(pins):
            raise ActivationEvidenceError(f"{backend} package count does not match lock roster")
        if env["target_backend"] != backend:
            raise ActivationEvidenceError(f"{backend} target_backend mismatch")
        for field in ("target_import_ok", "target_runtime_smoke_observed_on_norman"):
            if env[field] is not True:
                raise ActivationEvidenceError(f"{backend} {field} must be true")

    run_gate = _exact_keys(payload["run_gate"], _RUN_GATE_KEYS, "dependency_lock.run_gate")
    if run_gate["schema"] != "compose_backend_run_smoke_evidence_v1":
        raise ActivationEvidenceError("run-smoke schema mismatch")
    evidence_status = run_gate["evidence_status"]
    if evidence_status not in {"INCOMPLETE", "COMPLETE"}:
        raise ActivationEvidenceError("run-smoke evidence_status must be INCOMPLETE or COMPLETE")

    reproduction = _exact_keys(
        payload["environment_reproducibility"],
        _REPRODUCIBILITY_KEYS,
        "dependency_lock.environment_reproducibility",
    )
    if reproduction["version_pins_complete"] is not True:
        raise ActivationEvidenceError("dependency versions are not completely pinned")
    if payload["both_backends_import_ok"] is not True:
        raise ActivationEvidenceError("both backend imports must be observed")
    if payload["both_backends_runtime_smoke_observed_on_norman"] is not True:
        raise ActivationEvidenceError("both backend runtime smokes must be observed")
    complete = evidence_status == "COMPLETE"
    if complete:
        _validate_complete_run_evidence(run_gate, lock_path.parent)
        if run_gate["seal_safety_status"] != "VERIFIED_ZERO_OVERLAP":
            raise ActivationEvidenceError("complete run evidence must verify zero sealed overlap")
        if payload["both_backends_run_evidence_complete"] is not True:
            raise ActivationEvidenceError("complete run evidence flag is false")
        if any(
            environments[f"{backend}_env"]["target_run_evidence_complete"] is not True
            for backend in ("gears", "cpa")
        ):
            raise ActivationEvidenceError("per-backend run evidence flag is false")
        if reproduction.get("package_artifact_hashes_complete") is not True:
            raise ActivationEvidenceError("package artifact hashes remain incomplete")
        wheelhouse_path = _bound_relative_file(
            lock_path.parent,
            reproduction["wheelhouse_manifest_path"],
            reproduction["wheelhouse_manifest_sha256"],
            "wheelhouse manifest",
        )
        _validate_wheelhouse_manifest(wheelhouse_path, environment_pins)
        if (
            re.fullmatch(r"sha256:[0-9a-f]{64}", str(reproduction.get("container_image_digest")))
            is None
        ):
            raise ActivationEvidenceError("container image digest is missing")
        if reproduction["status"] != "COMPLETE":
            raise ActivationEvidenceError("environment reproducibility status is not COMPLETE")
        if run_gate["missing_evidence"] != []:
            raise ActivationEvidenceError(
                "complete run evidence must have no missing-evidence entries"
            )
    else:
        evidence = _exact_keys(
            run_gate["required_evidence"],
            frozenset({"gears", "cpa"}),
            "run_gate.required_evidence",
        )
        for backend in ("gears", "cpa"):
            record = _exact_keys(
                evidence[backend], _RUN_EVIDENCE_KEYS, f"run_gate.required_evidence.{backend}"
            )
            if any(value is not None for value in record.values()):
                raise ActivationEvidenceError(
                    "incomplete run evidence must not carry partial claims"
                )
        if "BLOCKED" not in str(payload["activation"]).upper():
            raise ActivationEvidenceError("incomplete dependency evidence must remain BLOCKED")
        if payload["both_backends_run_evidence_complete"] is not False:
            raise ActivationEvidenceError("incomplete run evidence cannot claim completion")
        if any(
            environments[f"{backend}_env"]["target_run_evidence_complete"] is not False
            for backend in ("gears", "cpa")
        ):
            raise ActivationEvidenceError("incomplete per-backend evidence cannot claim completion")
        if run_gate["seal_safety_status"] != "UNVERIFIED":
            raise ActivationEvidenceError(
                "incomplete run evidence must mark seal safety UNVERIFIED"
            )
        if not isinstance(run_gate["missing_evidence"], list) or not run_gate["missing_evidence"]:
            raise ActivationEvidenceError("incomplete run evidence must enumerate missing evidence")
        if not all(isinstance(item, str) and item.strip() for item in run_gate["missing_evidence"]):
            raise ActivationEvidenceError("missing-evidence entries must be non-empty strings")
        if reproduction["package_artifact_hashes_complete"] is not False:
            raise ActivationEvidenceError(
                "incomplete environment evidence cannot claim artifact hashes"
            )
        if reproduction["wheelhouse_manifest_sha256"] is not None:
            raise ActivationEvidenceError(
                "incomplete environment evidence cannot claim a wheelhouse manifest"
            )
        if reproduction["wheelhouse_manifest_path"] is not None:
            raise ActivationEvidenceError(
                "incomplete environment evidence cannot claim a wheelhouse path"
            )
        if reproduction["container_image_digest"] is not None:
            raise ActivationEvidenceError(
                "incomplete environment evidence cannot claim an image digest"
            )
        if not str(reproduction["status"]).startswith("INCOMPLETE"):
            raise ActivationEvidenceError("environment reproducibility must remain INCOMPLETE")
    return payload
