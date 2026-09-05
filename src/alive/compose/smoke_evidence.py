"""Produce the dev-pod smoke evidence that :mod:`alive.compose.activation_evidence` demands.

The validator is strict and complete; what was missing is a producer. Until now the
dependency lock's ``run_gate.required_evidence`` had to be filled in by hand on the
pod, which is exactly how a measurement and its record drift apart -- this
repository's dominant defect, and the reason the lock still reads
``activation=BLOCKED`` / ``evidence_status=INCOMPLETE``.

Every cross-check the validator performs is derived here from ONE computation, so
the two sides cannot disagree. The schema/protocol/role strings are spelled here
rather than imported: ``activation_evidence`` is a member of the frozen
kernel-isolation closure, so no public constant may be added to it, and reaching
for its private names would bind to a name rather than to the contract. The
round-trip tests bind them instead -- a wrong string is refused by the committed
validator itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alive.compose.activation_evidence import _validate_pinned_requirements
from alive.provenance import sha256_file, sha256_json

__all__ = [
    "ARTIFACT_MANIFEST_SCHEMA",
    "WHEELHOUSE_SCHEMA",
    "PAIR_ROSTER_SCHEMA",
    "build_smoke_artifact_manifest",
    "build_smoke_pair_roster",
    "build_wheelhouse_manifest",
]

PAIR_ROSTER_SCHEMA = "compose_smoke_pair_roster_v1"
ARTIFACT_MANIFEST_SCHEMA = "compose_backend_smoke_artifact_manifest_v1"
WHEELHOUSE_SCHEMA = "compose_python_artifact_manifest_v1"
_WHEELHOUSE_ENVIRONMENTS = frozenset({"gears_env", "cpa_env"})
#: The six objects the validator requires, mapped to their run-gate record field.
#: Spelled here to match the validator's own table; the round-trip test binds them.
_ARTIFACT_RECORD_FIELDS = {
    "norman_source": "norman_source_sha256",
    "fit_role_artifact": "fit_role_artifact_sha256",
    "fit_role_row_identity": "fit_role_row_identity_sha256",
    "smoke_script": "smoke_script_sha256",
    "command_log": "command_log_sha256",
    "checkpoint": "checkpoint_sha256",
}
_PROTOCOL = "COMPOSE-K562-v1"
_TRAINING_ROLES = ["singles", "combo_calibration"]


def build_smoke_pair_roster(
    *,
    backend: str,
    training_pair_ids: list[str],
    sealed_pair_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a pair-roster manifest and the run-gate record fields bound to it.

    Parameters
    ----------
    backend : str
        ``"gears"`` or ``"cpa"``; must match the record's position in the lock.
    training_pair_ids : list of str
        Pair IDs the smoke actually fits on. Sorted and de-duplicated here so the
        caller cannot hand the validator a non-canonical roster; the record's
        hashes are taken from the same normalised list the manifest carries.
    sealed_pair_ids : list of str
        Pair IDs the protocol seals; present only so the disjointness can be measured.
        Normalised the same way.

    Returns
    -------
    tuple of (dict, dict)
        The ``compose_smoke_pair_roster_v1`` manifest, and the fragment of
        ``run_gate.required_evidence[backend]`` that the manifest determines.
    """
    roster: dict[str, Any] = {
        "schema": PAIR_ROSTER_SCHEMA,
        "protocol": _PROTOCOL,
        "backend": backend,
        "training_roles": list(_TRAINING_ROLES),
        "training_pair_ids": sorted(set(training_pair_ids)),
        "sealed_pair_ids": sorted(set(sealed_pair_ids)),
    }
    roster["manifest_checksum"] = sha256_json(roster)
    record: dict[str, Any] = {
        "training_pair_roster_sha256": sha256_json(roster["training_pair_ids"]),
        "sealed_pair_roster_sha256": sha256_json(roster["sealed_pair_ids"]),
        "sealed_pair_overlap_count": len(
            set(roster["training_pair_ids"]) & set(roster["sealed_pair_ids"])
        ),
    }
    return roster, record


def build_smoke_artifact_manifest(
    *,
    backend: str,
    artifacts: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the artifact manifest by HASHING the named files, and its record fields.

    The digest is measured here rather than accepted as an argument. "A hash for a
    discarded or unlocatable object is not evidence" (dev-pod plan Task 0.1): a
    producer that took ``sha256`` from its caller would let the record describe
    bytes nobody read. Measuring makes the recorded digest and the file on disk the
    same thing by construction, and one measurement fills both the manifest and the
    run-gate record.

    Parameters
    ----------
    backend : str
        ``"gears"`` or ``"cpa"``.
    artifacts : dict
        Exactly the six required objects, each with ``path`` (the local file to
        hash), ``uri`` (a durable, non-``file:`` location) and
        ``immutable_version``. Any other key, or a missing one, raises.

    Raises
    ------
    ValueError
        If the supplied names are not exactly the six the validator requires.

    Returns
    -------
    tuple of (dict, dict)
        The ``compose_backend_smoke_artifact_manifest_v1`` manifest, and the
        fragment of ``run_gate.required_evidence[backend]`` it determines.
    """
    supplied_names = set(artifacts)
    expected_names = set(_ARTIFACT_RECORD_FIELDS)
    if supplied_names != expected_names:
        missing = sorted(expected_names - supplied_names)
        unexpected = sorted(supplied_names - expected_names)
        raise ValueError(
            "smoke artifact roster mismatch — "
            f"missing={missing} unexpected={unexpected}. The builder reads exactly the "
            "six objects the validator requires; anything else would be dropped without "
            "a word and the manifest would be complete by the letter and short by intent."
        )

    entries: dict[str, Any] = {}
    record: dict[str, Any] = {}
    for name, field in _ARTIFACT_RECORD_FIELDS.items():
        supplied = artifacts[name]
        digest = sha256_file(Path(supplied["path"]))
        entries[name] = {
            "uri": supplied["uri"],
            "immutable_version": supplied["immutable_version"],
            "sha256": digest,
        }
        record[field] = digest
    manifest: dict[str, Any] = {
        "schema": ARTIFACT_MANIFEST_SCHEMA,
        "protocol": _PROTOCOL,
        "backend": backend,
        "artifacts": entries,
    }
    manifest["manifest_checksum"] = sha256_json(manifest)
    return manifest, record


def build_wheelhouse_manifest(
    *,
    environments: dict[str, tuple[Any, dict[str, dict[str, Any]]]],
) -> dict[str, Any]:
    """Build the wheelhouse manifest with its roster DERIVED from the requirements locks.

    ``_validate_wheelhouse_manifest`` requires the manifest's package roster to equal
    the pins parsed from the requirements lock exactly. Accepting a roster from the
    caller would let the two be typed separately and drift, with the validator as the
    only thing standing between drift and release evidence. Deriving the roster from
    the lock -- using the validator's own parser, so there is not a second parser to
    disagree -- makes them the same thing.

    The parser is imported under its private name deliberately.
    ``activation_evidence`` is a member of the frozen kernel-isolation closure, so no
    public alias may be added to it; binding to the exact function the validator runs
    is a stronger guarantee than re-implementing the same grammar here, and a rename
    upstream breaks this import loudly instead of drifting quietly.

    Parameters
    ----------
    environments : dict
        ``env_name -> (requirements_lock_path, artifacts)`` where ``artifacts`` maps
        the normalised package name to ``path`` (the wheel/sdist to hash),
        ``filename`` and ``source_url``.

    Returns
    -------
    dict
        A ``compose_python_artifact_manifest_v1`` manifest.

    Raises
    ------
    ValueError
        If the environments are not exactly ``{"gears_env", "cpa_env"}``, or if an
        environment's artifacts do not cover its pins exactly.
    """
    if set(environments) != _WHEELHOUSE_ENVIRONMENTS:
        missing = sorted(_WHEELHOUSE_ENVIRONMENTS - set(environments))
        unexpected = sorted(set(environments) - _WHEELHOUSE_ENVIRONMENTS)
        raise ValueError(
            "wheelhouse must cover both locked environments — "
            f"missing={missing} unexpected={unexpected}. A one-environment manifest is "
            "internally consistent and still rejected downstream, after the pod time is spent."
        )

    built: dict[str, Any] = {}
    for env_name, (lock_path, artifacts) in environments.items():
        pins = _validate_pinned_requirements(Path(lock_path))
        supplied = {name.lower().replace("_", "-") for name in artifacts}
        if supplied != set(pins):
            missing = sorted(set(pins) - supplied)
            unexpected = sorted(supplied - set(pins))
            raise ValueError(
                f"{env_name} wheelhouse roster does not match its requirements lock — "
                f"missing={missing} unexpected={unexpected}. The pod can still fetch a "
                "missing wheel now; after the run it is only a rejected manifest."
            )
        entries = []
        for name, version in sorted(pins.items()):
            supplied_artifact = artifacts[name]
            entries.append(
                {
                    "name": name,
                    "version": version,
                    "filename": supplied_artifact["filename"],
                    "source_url": supplied_artifact["source_url"],
                    "sha256": sha256_file(Path(supplied_artifact["path"])),
                }
            )
        built[env_name] = entries
    manifest: dict[str, Any] = {"schema": WHEELHOUSE_SCHEMA, "environments": built}
    manifest["manifest_checksum"] = sha256_json(manifest)
    return manifest
