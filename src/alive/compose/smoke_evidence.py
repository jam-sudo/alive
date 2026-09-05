"""Produce the dev-pod smoke evidence that :mod:`alive.compose.activation_evidence` demands.

The validator is strict and complete; what was missing is a producer. Until now the
dependency lock's ``run_gate.required_evidence`` had to be filled in by hand on the
pod, which is exactly how a measurement and its record drift apart -- this
repository's dominant defect, and the reason the lock still reads
``activation=BLOCKED`` / ``evidence_status=INCOMPLETE``.

Every cross-check the validator performs is derived here from ONE computation, so
the two sides cannot disagree, and every claim the promoted lock makes is
established here before anything is built. The schema/protocol strings are spelled
here rather than imported: ``activation_evidence`` is a member of the frozen
kernel-isolation closure, so no public constant may be added to it, and reaching
for its private names would bind to a name rather than to the contract. The
round-trip tests bind them instead -- a wrong string is refused by the committed
validator itself.

Nothing in this module writes into the evidence directory except
:func:`publish_promotion`, which validates a staged copy first.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alive.compose.activation_evidence import (
    ActivationEvidenceError,
    _validate_pinned_requirements,
    validate_dependency_lock,
)
from alive.compose.roles import CALIBRATION_ROLE_NAME
from alive.io import atomic_write_once
from alive.provenance import sha256_file, sha256_json

__all__ = [
    "ARTIFACT_MANIFEST_SCHEMA",
    "LOCK_NAME",
    "WHEELHOUSE_SCHEMA",
    "PAIR_ROSTER_SCHEMA",
    "Promotion",
    "build_smoke_artifact_manifest",
    "build_smoke_pair_roster",
    "build_wheelhouse_manifest",
    "promote_lock_to_complete",
    "publish_promotion",
]

#: The dependency lock's fixed name inside the evidence directory.
LOCK_NAME = "gears_cpa_dependency_lock.json"

PAIR_ROSTER_SCHEMA = "compose_smoke_pair_roster_v1"
ARTIFACT_MANIFEST_SCHEMA = "compose_backend_smoke_artifact_manifest_v1"
WHEELHOUSE_SCHEMA = "compose_python_artifact_manifest_v1"
_WHEELHOUSE_ENVIRONMENTS = frozenset({"gears_env", "cpa_env"})
_BACKENDS = frozenset({"gears", "cpa"})
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
_ARTIFACT_ENTRY_KEYS = frozenset({"path", "uri", "immutable_version"})
_WHEEL_ENTRY_KEYS = frozenset({"path", "filename", "source_url"})
_PROTOCOL = "COMPOSE-K562-v1"
#: The exact fit roster, in the order the validator requires. ``singles`` has no
#: shared constant; the calibration role is bound to the canonical vocabulary.
_TRAINING_ROLES = ["singles", CALIBRATION_ROLE_NAME]
_HEX40 = re.compile(r"[0-9a-f]{40}")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_UTC_ISO8601 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_URI_SCHEME = re.compile(r"([a-z][a-z0-9+.-]*):")


def _require_backend(backend: Any) -> str:
    if backend not in _BACKENDS:
        raise ValueError(
            f"backend must be one of {sorted(_BACKENDS)}, got {backend!r}; the backend names "
            "a position in the lock and anything else has nowhere to go"
        )
    return backend


def _exact_entry_keys(entry: Any, expected: frozenset[str], where: str) -> dict[str, Any]:
    """Refuse an entry whose keys are not exactly ``expected``.

    An unexpected key is not harmless. A caller that passes ``sha256`` beside
    ``path`` believes it has recorded a digest; this builder measures its own and
    would have ignored the caller's without a word.
    """
    if not isinstance(entry, dict):
        raise ValueError(f"{where} must be an object with keys {sorted(expected)}")
    supplied = set(entry)
    if supplied != expected:
        missing = sorted(expected - supplied)
        unexpected = sorted(supplied - expected)
        raise ValueError(
            f"{where} keys mismatch — missing={missing} unexpected={unexpected}; "
            f"exactly {sorted(expected)} are read and anything else would be ignored"
        )
    return entry


def _require_durable_uri(uri: Any, where: str) -> str:
    """A durable URI has a scheme and is not ``file:``; a pod-local path leaves with the pod."""
    scheme = _URI_SCHEME.match(uri) if isinstance(uri, str) else None
    if scheme is None or scheme.group(1) == "file":
        raise ValueError(
            f"{where}.uri must be a durable, non-file URI with a scheme, got {uri!r}; "
            "Task 0.1 requires each smoke object retained in durable storage"
        )
    return uri


def _normalize_package(name: str) -> str:
    """The validator's own normalisation (``_validate_pinned_requirements``)."""
    return name.lower().replace("_", "-")


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

    Raises
    ------
    ValueError
        If ``backend`` is not one of the protocol's two backends.
    """
    roster: dict[str, Any] = {
        "schema": PAIR_ROSTER_SCHEMA,
        "protocol": _PROTOCOL,
        "backend": _require_backend(backend),
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
        Exactly the six required objects, each with exactly ``path`` (the local
        file to hash), ``uri`` (a durable, non-``file:`` location with a scheme)
        and ``immutable_version``. Any other name or key, or a missing one, raises.

    Raises
    ------
    ValueError
        If the supplied names are not exactly the six the validator requires, if an
        entry carries keys other than the three read here, or if a URI is not
        durable.

    Returns
    -------
    tuple of (dict, dict)
        The ``compose_backend_smoke_artifact_manifest_v1`` manifest, and the
        fragment of ``run_gate.required_evidence[backend]`` it determines.
    """
    _require_backend(backend)
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
    for name in _ARTIFACT_RECORD_FIELDS:
        entry = _exact_entry_keys(artifacts[name], _ARTIFACT_ENTRY_KEYS, f"artifacts[{name!r}]")
        _require_durable_uri(entry["uri"], f"artifacts[{name!r}]")

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
        the package name (normalised here the way the validator normalises pins) to
        exactly ``path`` (the wheel/sdist to hash), ``filename`` (which must be the
        hashed file's own name) and ``source_url``.

    Returns
    -------
    dict
        A ``compose_python_artifact_manifest_v1`` manifest.

    Raises
    ------
    ValueError
        If the environments are not exactly ``{"gears_env", "cpa_env"}``, if two
        supplied names normalise to one package, if an entry carries keys other than
        the three read here, if a declared filename is not the hashed file's name, or
        if an environment's artifacts do not cover its pins exactly.
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
        # Normalise once and use the normalised map for everything. Normalising only
        # for the roster comparison and then looking the artifact up under the pin's
        # name let an underscore pass the comparison and raise KeyError a line later.
        normalized: dict[str, dict[str, Any]] = {}
        for supplied_name, entry in artifacts.items():
            name = _normalize_package(supplied_name)
            if name in normalized:
                raise ValueError(
                    f"{env_name} wheelhouse supplies {name!r} twice after normalisation; "
                    "two artifacts cannot claim one pin"
                )
            normalized[name] = _exact_entry_keys(
                entry, _WHEEL_ENTRY_KEYS, f"{env_name} wheelhouse[{supplied_name!r}]"
            )
            if Path(normalized[name]["path"]).name != normalized[name]["filename"]:
                raise ValueError(
                    f"{env_name} wheelhouse[{supplied_name!r}] declares filename "
                    f"{normalized[name]['filename']!r} but the hashed file is "
                    f"{Path(normalized[name]['path']).name!r}; the manifest names a file "
                    "and records a digest, and they must be the same file"
                )
        if set(normalized) != set(pins):
            missing = sorted(set(pins) - set(normalized))
            unexpected = sorted(set(normalized) - set(pins))
            raise ValueError(
                f"{env_name} wheelhouse roster does not match its requirements lock — "
                f"missing={missing} unexpected={unexpected}. The pod can still fetch a "
                "missing wheel now; after the run it is only a rejected manifest."
            )
        entries = []
        for name, version in sorted(pins.items()):
            supplied_artifact = normalized[name]
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


def _serialize(payload: dict[str, Any]) -> str:
    """The one serialisation every hash and every write of a manifest goes through."""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _manifest_file(filename: str, payload: dict[str, Any]) -> tuple[str, str, str]:
    """Serialise a manifest once and return ``(filename, text, sha256 of that text)``.

    The validator binds ``*_manifest_path`` to ``*_manifest_sha256`` by re-hashing
    the file it finds. Hashing the exact text that will later be written is what
    makes the recorded pair describe the same object; a producer that wrote a file
    and separately reported a digest could report one for bytes it later replaced.
    """
    text = _serialize(payload)
    return filename, text, hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Promotion:
    """A promoted lock and the sidecar files its record binds by SHA-256.

    Nothing here has touched the evidence directory. :func:`publish_promotion` is
    the only step that writes, and it validates first.
    """

    lock: dict[str, Any]
    files: dict[str, str]


def _establish_run_identity(
    *,
    git_sha: Any,
    container_image_digest: Any,
    generated_at_utc: Any,
    host: Any,
    activation: Any,
    summary: Any,
) -> None:
    """Refuse identity or prose the promoted lock could not stand behind.

    ``git_sha`` and the image digest are checked downstream by the validator, but
    only after the wheelhouse is hashed and with an error about the lock rather than
    about the input. ``activation`` is checked by nothing downstream once the lock is
    COMPLETE: the validator's INCOMPLETE branch requires the text to say BLOCKED and
    its COMPLETE branch never reads it, so the one contradiction it cannot see -- a
    COMPLETE lock still announcing BLOCKED -- is refused here.
    """
    if not isinstance(git_sha, str) or _HEX40.fullmatch(git_sha) is None:
        raise ValueError(f"git_sha must be the full 40-hex commit the pod ran, got {git_sha!r}")
    if not isinstance(container_image_digest, str) or (
        _IMAGE_DIGEST.fullmatch(container_image_digest) is None
    ):
        raise ValueError(
            f"container_image_digest must be sha256:<64 hex>, got {container_image_digest!r}; "
            "a mutable tag is not a digest"
        )
    if not isinstance(generated_at_utc, str) or _UTC_ISO8601.fullmatch(generated_at_utc) is None:
        raise ValueError(
            f"generated_at_utc must be UTC ISO-8601 (YYYY-MM-DDTHH:MM:SSZ), got "
            f"{generated_at_utc!r}"
        )
    if (
        not isinstance(host, dict)
        or not host
        or not all(
            isinstance(key, str) and key and isinstance(value, str) and value.strip()
            for key, value in host.items()
        )
    ):
        raise ValueError(
            f"host must be a non-empty mapping of non-empty strings describing the pod, got "
            f"{host!r}"
        )
    if not isinstance(activation, str) or not activation.strip():
        raise ValueError("activation must be non-empty prose saying what this evidence is")
    if "BLOCKED" in activation.upper():
        raise ValueError(
            f"activation still says BLOCKED: {activation!r}; the validator requires that word "
            "on an INCOMPLETE lock and never reads it on a COMPLETE one, so a COMPLETE lock "
            "announcing BLOCKED would be the one contradiction nothing downstream refuses"
        )
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary must be non-empty prose describing this run's evidence")


def promote_lock_to_complete(
    *,
    lock: dict[str, Any],
    backends: dict[str, dict[str, Any]],
    wheelhouse: dict[str, Any],
    container_image_digest: str,
    git_sha: str,
    generated_at_utc: str,
    host: dict[str, str],
    activation: str,
    summary: str,
) -> Promotion:
    """Build the COMPLETE form of an INCOMPLETE dependency lock, writing nothing.

    The transition touches nine places: ``run_gate.seal_safety_status``, the two
    per-backend completion flags, the lock-wide completion flag,
    ``package_artifact_hashes_complete``, the wheelhouse path and hash, the
    container image digest, the reproducibility status, ``missing_evidence``, and
    the top-level ``manifest_checksum`` -- plus the four fields that identify THIS
    run rather than the July observation the INCOMPLETE lock records:
    ``generated_at_utc``, ``host``, ``activation`` and ``run_gate.summary``. Half a
    flip is refused by the validator without saying which half, so this either
    builds all of it or raises.

    Parameters
    ----------
    lock : dict
        The parsed INCOMPLETE lock. Not mutated; a new object is returned.
    backends : dict
        ``backend -> {"roster", "artifacts", "record"}`` where ``record`` carries
        the digest fields the two builders produced plus ``exit_code``.
    wheelhouse : dict
        The manifest from :func:`build_wheelhouse_manifest`.
    container_image_digest : str
        ``sha256:<64 hex>`` of the pod image. A mutable tag is not a digest.
    git_sha : str
        The full 40-hex commit the pod ran.
    generated_at_utc : str
        The pod's recorded start time, ``YYYY-MM-DDTHH:MM:SSZ``.
    host : dict
        Non-empty mapping describing the pod (GPU, driver, tool versions).
    activation : str
        The lock's activation text for this run. Must not say BLOCKED: the
        validator requires that word on an INCOMPLETE lock and does not read the
        text on a COMPLETE one.
    summary : str
        ``run_gate.summary`` for this run.

    Returns
    -------
    Promotion
        The promoted lock and the five sidecar manifests it binds, as the exact
        text whose digests the lock records. Hand it to :func:`publish_promotion`.

    Raises
    ------
    ValueError
        If the lock is not INCOMPLETE, if the backends are not exactly
        ``{"gears", "cpa"}`` or a record is filed under the other backend, if any
        roster overlaps the sealed pairs, if any smoke did not exit 0, or if the
        run identity or prose is malformed.
    """
    status = lock["run_gate"]["evidence_status"]
    if status != "INCOMPLETE":
        raise ValueError(
            f"lock evidence_status is {status!r}, not INCOMPLETE; a COMPLETE lock is a "
            "published result and promoting it again would overwrite one run's evidence "
            "with another's under the same identity (CLAUDE.md#provenance)"
        )
    if set(backends) != _BACKENDS:
        raise ValueError(f"promotion needs exactly {sorted(_BACKENDS)}, got {sorted(backends)}")
    _establish_run_identity(
        git_sha=git_sha,
        container_image_digest=container_image_digest,
        generated_at_utc=generated_at_utc,
        host=host,
        activation=activation,
        summary=summary,
    )

    # Establish the claims the promoted lock makes before building anything.
    # `VERIFIED_ZERO_OVERLAP` and "the smoke ran" are assertions; a producer that
    # writes them without checking is claiming a verification it never performed and
    # leaning on the validator to catch it downstream.
    for backend in sorted(_BACKENDS):
        supplied = backends[backend]
        for part in ("roster", "artifacts"):
            filed_as = supplied[part].get("backend")
            if filed_as != backend:
                raise ValueError(
                    f"backends[{backend!r}].{part} carries backend={filed_as!r}; a record "
                    "filed under the other backend is two records disagreeing about one thing"
                )
        record = supplied["record"]
        overlap = record.get("sealed_pair_overlap_count")
        if overlap != 0:
            raise ValueError(
                f"{backend} smoke training roster overlaps sealed pairs "
                f"(sealed_pair_overlap_count={overlap}); refusing to certify "
                "VERIFIED_ZERO_OVERLAP for a run that did not achieve it"
            )
        if record.get("exit_code") != 0:
            raise ValueError(
                f"{backend} smoke exit_code={record.get('exit_code')}; a run that did "
                "not exit 0 is not evidence that it ran"
            )

    promoted = copy.deepcopy(lock)
    run_gate = promoted["run_gate"]
    required: dict[str, Any] = {}
    files: dict[str, str] = {}
    for backend in sorted(_BACKENDS):
        supplied = backends[backend]
        roster_path, roster_text, roster_sha = _manifest_file(
            f"{backend}_smoke_pair_roster.json", supplied["roster"]
        )
        artifact_path, artifact_text, artifact_sha = _manifest_file(
            f"{backend}_smoke_artifacts.json", supplied["artifacts"]
        )
        files[roster_path] = roster_text
        files[artifact_path] = artifact_text
        required[backend] = {
            **supplied["record"],
            "pair_roster_manifest_path": roster_path,
            "pair_roster_manifest_sha256": roster_sha,
            "artifact_manifest_path": artifact_path,
            "artifact_manifest_sha256": artifact_sha,
        }
        promoted["environments"][f"{backend}_env"]["target_run_evidence_complete"] = True

    wheelhouse_path, wheelhouse_text, wheelhouse_sha = _manifest_file(
        "python_artifact_manifest.json", wheelhouse
    )
    files[wheelhouse_path] = wheelhouse_text

    run_gate["required_evidence"] = required
    run_gate["evidence_status"] = "COMPLETE"
    run_gate["seal_safety_status"] = "VERIFIED_ZERO_OVERLAP"
    run_gate["missing_evidence"] = []
    run_gate["summary"] = summary
    promoted["both_backends_run_evidence_complete"] = True
    promoted["environment_reproducibility"] = {
        "version_pins_complete": True,
        "package_artifact_hashes_complete": True,
        "wheelhouse_manifest_path": wheelhouse_path,
        "wheelhouse_manifest_sha256": wheelhouse_sha,
        "container_image_digest": container_image_digest,
        "status": "COMPLETE",
    }
    promoted["git_sha"] = git_sha
    promoted["generated_at_utc"] = generated_at_utc
    promoted["host"] = dict(host)
    promoted["activation"] = activation
    promoted.pop("manifest_checksum", None)
    promoted["manifest_checksum"] = sha256_json(promoted)
    return Promotion(lock=promoted, files=files)


def _atomic_replace(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` through a same-directory temp file and ``rename(2)``."""
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def publish_promotion(promotion: Promotion, *, evidence_dir: Path) -> dict[str, Any]:
    """Validate a promotion in a staging copy, then publish it; refuse without a trace.

    The committed validator checks things promotion cannot (the wheelhouse roster
    against the pins in the evidence directory, for one), and it resolves every
    referenced path relative to the lock's own directory. So the whole evidence
    directory is copied to a temporary staging area, the promoted lock and its
    sidecars are written there, and :func:`validate_dependency_lock` is run on the
    staged lock. Only a COMPLETE verdict reaches the evidence directory. The
    sidecars are then published write-once (:func:`alive.io.atomic_write_once`)
    and the lock last, by atomic rename, so the lock is the commit point and a
    refusal at any earlier step leaves the directory byte-identical.

    Parameters
    ----------
    promotion : Promotion
        From :func:`promote_lock_to_complete`.
    evidence_dir : Path
        The directory holding the INCOMPLETE lock and the files it references.

    Returns
    -------
    dict
        The published lock as :func:`validate_dependency_lock` returns it, re-read
        from the evidence directory after publishing.

    Raises
    ------
    FileExistsError
        If any sidecar name is already taken under ``evidence_dir``. Established
        for every name before the first write, so no partial set is published.
    ActivationEvidenceError
        If the staged lock does not validate COMPLETE. Nothing has been written.
    """
    for filename in sorted(promotion.files):
        if (evidence_dir / filename).exists():
            raise FileExistsError(
                f"{filename} already exists under {evidence_dir}; a sidecar is published "
                "write-once and an existing file is either a stray or the remains of an "
                "earlier run, and either way not this run's to overwrite"
            )

    lock_text = _serialize(promotion.lock)
    with tempfile.TemporaryDirectory(prefix="compose-promotion-") as scratch:
        staging = Path(scratch) / evidence_dir.name
        shutil.copytree(evidence_dir, staging)
        for filename, text in promotion.files.items():
            (staging / filename).write_text(text, encoding="utf-8")
        (staging / LOCK_NAME).write_text(lock_text, encoding="utf-8")
        staged = validate_dependency_lock(staging / LOCK_NAME)
        status = staged["run_gate"]["evidence_status"]
        if status != "COMPLETE":
            raise ActivationEvidenceError(f"staged lock validates as {status}, not COMPLETE")

    for filename, text in promotion.files.items():
        atomic_write_once(evidence_dir / filename, text)
    _atomic_replace(evidence_dir / LOCK_NAME, lock_text)
    return validate_dependency_lock(evidence_dir / LOCK_NAME)
