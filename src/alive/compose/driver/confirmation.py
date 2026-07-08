"""Seal-confirmation manifest v1: build, write-once install, and token verify.

``preflight`` (spec §3.2) installs a write-once ``seal_confirmation_manifest.json``
after its pre-seal gate succeeds. ``phase2b --confirm-seal <token>`` (spec §3.3
step 3) re-verifies it before doing anything else seal-adjacent: the
``--confirm-seal`` token must equal the manifest's full ``confirmation_checksum``
— NOT the (trivially recomputable) ``run_id`` — and the driver must then
reconstruct the manifest from the CURRENT non-sealed inputs and require
byte-for-byte equality with the stored manifest. Both directions of this module
run with the sealed source access count at 0: the seal is never opened here.

``method_roster`` / ``comparator_roster`` are never hardcoded in this module —
they are read directly off :mod:`alive.compose.config2`'s frozen, order-fixed
constants (``_EXPECTED_METHOD_ROSTER`` / ``_EXPECTED_COMPARATOR_FAMILY``) so the
manifest can never drift from the registered config contract.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md
§3.2 (tail) and §3.3 step 3.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from alive.compose.config2 import _EXPECTED_COMPARATOR_FAMILY, _EXPECTED_METHOD_ROSTER
from alive.io import atomic_write_once
from alive.provenance import sha256_json

__all__ = [
    "SEAL_CONFIRMATION_MANIFEST_SCHEMA",
    "SEAL_CONFIRMATION_MANIFEST_KEYS",
    "ConfirmationError",
    "build_seal_confirmation_manifest",
    "install_seal_confirmation_manifest",
    "verify_seal_confirmation_manifest",
]

#: Exact ``schema`` discriminator every v1 seal-confirmation manifest must carry
#: (spec §3.2).
SEAL_CONFIRMATION_MANIFEST_SCHEMA = "compose_seal_confirmation_manifest_v1"

#: Exact top-level key roster of a v1 seal-confirmation manifest (spec §3.2
#: tail): run/execution identity, the ResolvedRunSpec's own file SHA, the exact
#: approved Git SHA + clean status, the caller-supplied pre-seal content
#: checksums, the two config2-sourced rosters, and the self-excluding
#: ``confirmation_checksum``.
SEAL_CONFIRMATION_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "schema",
        "run_id",
        "execution_id",
        "resolved_run_spec_file_sha256",
        "approved_git_sha",
        "git_clean",
        "preseal_checksums",
        "method_roster",
        "comparator_roster",
        "confirmation_checksum",
    }
)

#: The keyword-only inputs both :func:`build_seal_confirmation_manifest` and
#: reconstruction (inside :func:`verify_seal_confirmation_manifest`) consume.
_BUILD_INPUT_KEYS: frozenset[str] = frozenset(
    {
        "run_id",
        "execution_id",
        "resolved_run_spec_file_sha256",
        "approved_git_sha",
        "git_clean",
        "preseal_checksums",
    }
)

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class ConfirmationError(ValueError):
    """Raised on ANY seal-confirmation manifest build/install/verify violation.

    Subclasses :class:`ValueError`. Covers a malformed build input, a corrupt or
    non-canonical stored manifest, a schema/self-checksum/roster mismatch, a
    ``--confirm-seal`` token that is not exactly the manifest's full
    ``confirmation_checksum`` (including a run-id-only token), and a
    reconstruction from current non-sealed inputs that diverges byte-for-byte
    from the stored manifest.
    """


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX64_RE.match(value))


def _canonical_bytes(obj: object) -> bytes:
    """Canonical JSON bytes (``sort_keys`` + compact separators)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validate_preseal_checksums(preseal_checksums: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(preseal_checksums, Mapping) or not preseal_checksums:
        raise ConfirmationError("preseal_checksums must be a non-empty mapping")
    checksums: dict[str, str] = {}
    for key, value in preseal_checksums.items():
        if not isinstance(key, str) or not key:
            raise ConfirmationError("preseal_checksums keys must be non-empty strings")
        if not _is_hex64(value):
            raise ConfirmationError(
                f"preseal_checksums[{key!r}] must be 64 lowercase hex chars, got {value!r}"
            )
        checksums[key] = value
    return checksums


def build_seal_confirmation_manifest(
    *,
    run_id: str,
    execution_id: str,
    resolved_run_spec_file_sha256: str,
    approved_git_sha: str,
    git_clean: bool,
    preseal_checksums: Mapping[str, str],
) -> dict[str, Any]:
    """Build a self-checksummed v1 seal-confirmation manifest (spec §3.2 tail).

    ``method_roster`` and ``comparator_roster`` are never taken from the
    caller — they are always exactly
    :data:`alive.compose.config2._EXPECTED_METHOD_ROSTER` (9, order-fixed) and
    :data:`alive.compose.config2._EXPECTED_COMPARATOR_FAMILY` (5, order-fixed),
    referenced directly so the manifest can never drift from the registered
    config contract.

    Parameters
    ----------
    run_id : str
        The verified composite COMPOSE run identifier.
    execution_id : str
        The runtime execution identity (:func:`alive.compose.driver.run_spec.compute_execution_id`).
    resolved_run_spec_file_sha256 : str
        SHA-256 of the ResolvedRunSpec file's own bytes.
    approved_git_sha : str
        The exact approved Git SHA the run executes at.
    git_clean : bool
        Whether the working tree was clean at confirmation time.
    preseal_checksums : Mapping[str, str]
        The caller-supplied pre-seal content checksums (config / data-card /
        manifest / response-space / factor / etc. — exactly the set the caller
        passes; each value must be 64 lowercase hex chars). This module does
        not prescribe the key roster; the caller owns which pre-seal artifacts
        are bound into the confirmation.

    Returns
    -------
    dict
        The v1 manifest, including the self-excluding ``confirmation_checksum``
        (``sha256_json`` of the payload without that key).

    Raises
    ------
    ConfirmationError
        On any malformed input.
    """
    if not isinstance(run_id, str) or not run_id:
        raise ConfirmationError("run_id must be a non-empty string")
    if not isinstance(execution_id, str) or not execution_id:
        raise ConfirmationError("execution_id must be a non-empty string")
    if not _is_hex64(resolved_run_spec_file_sha256):
        raise ConfirmationError("resolved_run_spec_file_sha256 must be 64 lowercase hex chars")
    if not isinstance(approved_git_sha, str) or not approved_git_sha:
        raise ConfirmationError("approved_git_sha must be a non-empty string")
    if not isinstance(git_clean, bool):
        raise ConfirmationError("git_clean must be a bool")
    checksums = _validate_preseal_checksums(preseal_checksums)

    payload: dict[str, Any] = {
        "schema": SEAL_CONFIRMATION_MANIFEST_SCHEMA,
        "run_id": run_id,
        "execution_id": execution_id,
        "resolved_run_spec_file_sha256": resolved_run_spec_file_sha256,
        "approved_git_sha": approved_git_sha,
        "git_clean": git_clean,
        "preseal_checksums": checksums,
        "method_roster": list(_EXPECTED_METHOD_ROSTER),
        "comparator_roster": list(_EXPECTED_COMPARATOR_FAMILY),
    }
    confirmation_checksum = sha256_json(payload)
    return {**payload, "confirmation_checksum": confirmation_checksum}


def install_seal_confirmation_manifest(path: str | Path, manifest: Mapping[str, Any]) -> None:
    """Write-once install a seal-confirmation manifest as canonical JSON bytes.

    Re-validates the manifest's exact key roster and self-checksum before
    installing (defense in depth — never installs a manifest that would fail
    its own :func:`verify_seal_confirmation_manifest` self-check), then
    publishes it via :func:`alive.io.atomic_write_once`, which never replaces an
    existing file.

    Parameters
    ----------
    path : str or Path
        Destination path (e.g. ``<run_dir>/seal_confirmation_manifest.json``).
    manifest : Mapping
        The manifest returned by :func:`build_seal_confirmation_manifest`.

    Raises
    ------
    ConfirmationError
        If the manifest fails its own shape/self-checksum check, or the
        destination already exists (write-once).
    """
    if set(manifest) != SEAL_CONFIRMATION_MANIFEST_KEYS:
        raise ConfirmationError(
            "seal confirmation manifest key roster mismatch: "
            f"missing={sorted(SEAL_CONFIRMATION_MANIFEST_KEYS - set(manifest))} "
            f"unexpected={sorted(set(manifest) - SEAL_CONFIRMATION_MANIFEST_KEYS)}"
        )
    body = {k: v for k, v in manifest.items() if k != "confirmation_checksum"}
    if manifest.get("confirmation_checksum") != sha256_json(body):
        raise ConfirmationError(
            "refusing to install: confirmation_checksum does not match the "
            "manifest payload (excluding confirmation_checksum)"
        )
    try:
        atomic_write_once(path, _canonical_bytes(dict(manifest)).decode("utf-8"))
    except OSError as exc:
        raise ConfirmationError(
            f"failed to write-once install seal confirmation manifest {path!r}: {exc}"
        ) from exc


def verify_seal_confirmation_manifest(
    path: str | Path,
    token: str,
    *,
    reconstruct_inputs: Mapping[str, Any],
) -> None:
    """Verify an installed seal-confirmation manifest against a token (spec §3.3 step 3).

    Order of checks (fail-closed at the first violation; opens NO seal, reads NO
    sealed source):

    1. read + parse the installed manifest file; it must be canonical JSON
       (``sort_keys`` + compact separators);
    2. exact top-level key roster;
    3. exact ``schema`` discriminator;
    4. self-checksum: ``confirmation_checksum == sha256_json(manifest excluding
       confirmation_checksum)``;
    5. ``resolved_run_spec_file_sha256`` is a well-formed 64-hex digest;
    6. ``method_roster`` / ``comparator_roster`` equal exactly
       :data:`alive.compose.config2._EXPECTED_METHOD_ROSTER` /
       ``_EXPECTED_COMPARATOR_FAMILY`` (order-fixed);
    7. ``token == manifest["confirmation_checksum"]`` — checked BEFORE
       reconstruction. A token equal to ``run_id`` (or any other non-matching
       value) is rejected; this is the landmine the ``--confirm-seal`` CLI
       flag guards against (the token is the FULL checksum, not the
       recomputable run id);
    8. reconstructs the manifest from ``reconstruct_inputs`` — the CURRENT
       non-sealed values, via the exact same
       :func:`build_seal_confirmation_manifest` — and requires byte-for-byte
       canonical-JSON equality with the stored manifest. This is what proves
       the manifest still binds the current pre-seal reality without opening
       the seal.

    Parameters
    ----------
    path : str or Path
        Path to the installed manifest file.
    token : str
        The ``--confirm-seal`` CLI argument; must equal the manifest's full
        ``confirmation_checksum``.
    reconstruct_inputs : Mapping[str, Any]
        The exact keyword inputs :func:`build_seal_confirmation_manifest`
        expects (``run_id``, ``execution_id``, ``resolved_run_spec_file_sha256``,
        ``approved_git_sha``, ``git_clean``, ``preseal_checksums``), computed by
        the caller from the CURRENT non-sealed files/environment + attested
        sealed-input identity (never from the sealed source itself).

    Raises
    ------
    ConfirmationError
        On any violation in the ordered checks above.
    """
    manifest_path = Path(path)
    try:
        raw_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise ConfirmationError(
            f"cannot read seal confirmation manifest {manifest_path}: {exc}"
        ) from exc
    try:
        manifest = json.loads(raw_bytes)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ConfirmationError(f"seal confirmation manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ConfirmationError("seal confirmation manifest must be a JSON object")

    # 1. canonical-bytes check ---------------------------------------------
    if _canonical_bytes(manifest) != raw_bytes:
        raise ConfirmationError(
            "seal confirmation manifest file bytes are not canonical JSON "
            "(sort_keys + compact separators required)"
        )

    # 2. exact top-level key roster ----------------------------------------
    actual_keys = set(manifest)
    if actual_keys != SEAL_CONFIRMATION_MANIFEST_KEYS:
        raise ConfirmationError(
            "seal confirmation manifest key roster mismatch: "
            f"missing={sorted(SEAL_CONFIRMATION_MANIFEST_KEYS - actual_keys)} "
            f"unexpected={sorted(actual_keys - SEAL_CONFIRMATION_MANIFEST_KEYS)}"
        )

    # 3. exact schema --------------------------------------------------------
    if manifest.get("schema") != SEAL_CONFIRMATION_MANIFEST_SCHEMA:
        raise ConfirmationError(
            f"seal confirmation manifest schema must be {SEAL_CONFIRMATION_MANIFEST_SCHEMA!r}, "
            f"got {manifest.get('schema')!r}"
        )

    # 4. self-checksum ---------------------------------------------------------
    declared_checksum = manifest.get("confirmation_checksum")
    if not _is_hex64(declared_checksum):
        raise ConfirmationError("confirmation_checksum must be 64 lowercase hex chars")
    body = {k: v for k, v in manifest.items() if k != "confirmation_checksum"}
    if declared_checksum != sha256_json(body):
        raise ConfirmationError(
            "confirmation_checksum does not match the manifest payload "
            "(excluding confirmation_checksum) — manifest is tampered"
        )

    # 5. resolved_run_spec_file_sha256 shape ----------------------------------
    if not _is_hex64(manifest.get("resolved_run_spec_file_sha256")):
        raise ConfirmationError(
            "seal confirmation manifest resolved_run_spec_file_sha256 must be "
            "64 lowercase hex chars"
        )

    # 6. roster equality (== config2 constants) -------------------------------
    if list(manifest.get("method_roster") or []) != list(_EXPECTED_METHOD_ROSTER):
        raise ConfirmationError(
            "seal confirmation manifest method_roster does not equal exactly "
            "config2._EXPECTED_METHOD_ROSTER"
        )
    if list(manifest.get("comparator_roster") or []) != list(_EXPECTED_COMPARATOR_FAMILY):
        raise ConfirmationError(
            "seal confirmation manifest comparator_roster does not equal exactly "
            "config2._EXPECTED_COMPARATOR_FAMILY"
        )

    # 7. token FIRST, before any reconstruction -------------------------------
    if not isinstance(token, str) or token != declared_checksum:
        raise ConfirmationError(
            "--confirm-seal token does not equal the manifest's full "
            "confirmation_checksum (a run-id-only or otherwise non-matching "
            "token is rejected)"
        )

    # 8. reconstruct from CURRENT non-sealed inputs; require byte equality ---
    if not isinstance(reconstruct_inputs, Mapping):
        raise ConfirmationError("reconstruct_inputs must be a mapping")
    missing = _BUILD_INPUT_KEYS - set(reconstruct_inputs)
    if missing:
        raise ConfirmationError(f"reconstruct_inputs is missing keys: {sorted(missing)}")
    reconstructed = build_seal_confirmation_manifest(
        run_id=reconstruct_inputs["run_id"],
        execution_id=reconstruct_inputs["execution_id"],
        resolved_run_spec_file_sha256=reconstruct_inputs["resolved_run_spec_file_sha256"],
        approved_git_sha=reconstruct_inputs["approved_git_sha"],
        git_clean=reconstruct_inputs["git_clean"],
        preseal_checksums=reconstruct_inputs["preseal_checksums"],
    )
    if _canonical_bytes(reconstructed) != _canonical_bytes(manifest):
        raise ConfirmationError(
            "reconstructed seal confirmation manifest diverges from the stored "
            "manifest — the current non-sealed inputs no longer match what was "
            "confirmed (fail closed; NO seal opened)"
        )
