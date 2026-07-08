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
from typing import Any, Mapping, Sequence

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
#: approved Git SHA + clean status, the FULL pre-seal content checksum set, the
#: selected hyperparameters, the per-method worker identity, the double/single
#: pair counts, the ordered seal-request intent checksum, the ``CONTINUE``
#: futility status, the zero sealed-access count, the forbidden-output-absence
#: attestation, the owner-approved ``accepted_limitations`` roster, the two
#: config2-sourced rosters, and the self-excluding ``confirmation_checksum``.
SEAL_CONFIRMATION_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "schema",
        "run_id",
        "execution_id",
        "resolved_run_spec_file_sha256",
        "approved_git_sha",
        "git_clean",
        "preseal_checksums",
        "selected_hyperparameters",
        "worker_identity",
        "double_pair_count",
        "single_pair_count",
        "ordered_seal_request_checksum",
        "futility_status",
        "sealed_access_count",
        "forbidden_output_absence",
        "accepted_limitations",
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
        "selected_hyperparameters",
        "worker_identity",
        "double_pair_count",
        "single_pair_count",
        "ordered_seal_request_checksum",
        "futility_status",
        "sealed_access_count",
        "forbidden_output_absence",
        "accepted_limitations",
    }
)

#: The COMPLETE pre-seal content-checksum roster (spec §3.2): config, data-card,
#: manifest, sequence, feature, factor, response(-space), model, bundle, ledger,
#: pair-index and seed-report. Every one is a required 64-lowercase-hex digest;
#: ``preseal_checksums`` must carry exactly this set (no missing, no extra).
_REQUIRED_PRESEAL_CHECKSUM_KEYS: frozenset[str] = frozenset(
    {
        "config_checksum",
        "data_card_checksum",
        "manifest_checksum",
        "sequence_checksum",
        "feature_checksum",
        "factor_checksum",
        "response_space_checksum",
        "model_checksum",
        "bundle_checksum",
        "ledger_checksum",
        "pair_index_checksum",
        "seed_report_checksum",
    }
)

#: The exact per-method worker-identity keys (spec §3.2): the two subprocess
#: methods whose ``ExecutionIdentityLock`` (worker/config/resource/env) identity
#: is bound into the confirmation.
_WORKER_IDENTITY_METHODS: frozenset[str] = frozenset({"gears", "cpa"})

#: The only futility status a confirmation may be built on (spec §3.2): a
#: confirmation is authorised solely on ``CONTINUE``.
_FUTILITY_CONTINUE = "CONTINUE"

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


def _validate_preseal_checksums(preseal_checksums: object) -> dict[str, str]:
    """Validate the COMPLETE pre-seal checksum set (spec §3.2).

    ``preseal_checksums`` must carry EXACTLY
    :data:`_REQUIRED_PRESEAL_CHECKSUM_KEYS` — no missing, no extra — and every
    value must be a 64-lowercase-hex digest string.
    """
    if not isinstance(preseal_checksums, Mapping):
        raise ConfirmationError("preseal_checksums must be a mapping")
    keys = set(preseal_checksums)
    if keys != set(_REQUIRED_PRESEAL_CHECKSUM_KEYS):
        raise ConfirmationError(
            "preseal_checksums key roster mismatch: "
            f"missing={sorted(_REQUIRED_PRESEAL_CHECKSUM_KEYS - keys)} "
            f"unexpected={sorted(keys - _REQUIRED_PRESEAL_CHECKSUM_KEYS)}"
        )
    checksums: dict[str, str] = {}
    for key in _REQUIRED_PRESEAL_CHECKSUM_KEYS:
        value = preseal_checksums[key]
        if not _is_hex64(value):
            raise ConfirmationError(
                f"preseal_checksums[{key!r}] must be 64 lowercase hex chars, got {value!r}"
            )
        checksums[key] = value
    return checksums


def _validate_selected_hyperparameters(selected_hyperparameters: object) -> dict[str, Any]:
    """Validate ``selected_hyperparameters`` (spec §3.2): a non-empty, canonical
    JSON-serialisable mapping keyed by non-empty strings."""
    if not isinstance(selected_hyperparameters, Mapping) or not selected_hyperparameters:
        raise ConfirmationError("selected_hyperparameters must be a non-empty mapping")
    normalized: dict[str, Any] = {}
    for key, value in selected_hyperparameters.items():
        if not isinstance(key, str) or not key:
            raise ConfirmationError("selected_hyperparameters keys must be non-empty strings")
        normalized[key] = value
    try:
        json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ConfirmationError(
            f"selected_hyperparameters must be JSON-serialisable: {exc}"
        ) from exc
    return normalized


def _validate_worker_identity(worker_identity: object) -> dict[str, Any]:
    """Validate the per-method ``worker_identity`` (spec §3.2).

    Must be a mapping keyed by EXACTLY :data:`_WORKER_IDENTITY_METHODS`
    (``{gears, cpa}``). Each method's value is either a non-empty content-digest
    string, or a non-empty mapping of the (worker/config/resource/env)
    ``ExecutionIdentityLock`` identity fields — string keys to non-empty string
    values.
    """
    if not isinstance(worker_identity, Mapping):
        raise ConfirmationError("worker_identity must be a mapping")
    keys = set(worker_identity)
    if keys != set(_WORKER_IDENTITY_METHODS):
        raise ConfirmationError(
            "worker_identity must have exactly the method keys "
            f"{sorted(_WORKER_IDENTITY_METHODS)}, got {sorted(keys)}"
        )
    normalized: dict[str, Any] = {}
    for method in _WORKER_IDENTITY_METHODS:
        value = worker_identity[method]
        if isinstance(value, str):
            if not value:
                raise ConfirmationError(
                    f"worker_identity[{method!r}] digest string must be non-empty"
                )
            normalized[method] = value
        elif isinstance(value, Mapping):
            if not value:
                raise ConfirmationError(
                    f"worker_identity[{method!r}] identity mapping must be non-empty"
                )
            fields: dict[str, str] = {}
            for field_key, field_value in value.items():
                if not isinstance(field_key, str) or not field_key:
                    raise ConfirmationError(
                        f"worker_identity[{method!r}] field keys must be non-empty strings"
                    )
                if not isinstance(field_value, str) or not field_value:
                    raise ConfirmationError(
                        f"worker_identity[{method!r}][{field_key!r}] must be a non-empty string"
                    )
                fields[field_key] = field_value
            normalized[method] = fields
        else:
            raise ConfirmationError(
                f"worker_identity[{method!r}] must be a digest string or an identity mapping"
            )
    return normalized


def _validate_pair_count(value: object, name: str) -> int:
    """Validate a non-negative int pair count (rejecting ``bool``)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfirmationError(f"{name} must be a non-negative int, got {value!r}")
    return value


def _require_continue(value: object) -> None:
    """Fail closed unless ``futility_status`` is exactly ``CONTINUE`` (spec §3.2)."""
    if value != _FUTILITY_CONTINUE:
        raise ConfirmationError(
            f"futility_status must be exactly {_FUTILITY_CONTINUE!r} "
            f"(a confirmation is only built on CONTINUE), got {value!r}"
        )


def _require_zero_sealed_access_count(value: object) -> None:
    """Fail closed unless ``sealed_access_count`` is exactly ``0`` (spec §3.2).

    Rejects ``bool`` (``False == 0`` in Python) so ``false`` cannot masquerade
    as a zero count.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value != 0:
        raise ConfirmationError(
            f"sealed_access_count must be exactly 0 at confirmation time "
            f"(the seal is never open here), got {value!r}"
        )


def _require_forbidden_output_absence(value: object) -> None:
    """Fail closed unless ``forbidden_output_absence`` attests absence (``True``)."""
    if not isinstance(value, bool) or value is not True:
        raise ConfirmationError(
            "forbidden_output_absence must be True (attesting that no forbidden "
            f"output artifact is present), got {value!r}"
        )


def _validate_accepted_limitations(accepted_limitations: object) -> list[str]:
    """Validate the owner-approved ``accepted_limitations`` roster (spec §3.2).

    Must be a non-empty list/tuple of non-empty strings (a bare string is
    rejected). Returned as a list; element order is preserved as the exact
    owner-approved roster.
    """
    if isinstance(accepted_limitations, str) or not isinstance(accepted_limitations, (list, tuple)):
        raise ConfirmationError("accepted_limitations must be a list of strings")
    limitations: list[str] = []
    for item in accepted_limitations:
        if not isinstance(item, str) or not item:
            raise ConfirmationError("accepted_limitations must be a list of non-empty strings")
        limitations.append(item)
    if not limitations:
        raise ConfirmationError("accepted_limitations must be a non-empty list of strings")
    return limitations


def build_seal_confirmation_manifest(
    *,
    run_id: str,
    execution_id: str,
    resolved_run_spec_file_sha256: str,
    approved_git_sha: str,
    git_clean: bool,
    preseal_checksums: Mapping[str, str],
    selected_hyperparameters: Mapping[str, Any],
    worker_identity: Mapping[str, Any],
    double_pair_count: int,
    single_pair_count: int,
    ordered_seal_request_checksum: str,
    futility_status: str,
    sealed_access_count: int,
    forbidden_output_absence: bool,
    accepted_limitations: Sequence[str],
) -> dict[str, Any]:
    """Build a self-checksummed v1 seal-confirmation manifest (spec §3.2 tail).

    ``method_roster`` and ``comparator_roster`` are never taken from the
    caller — they are always exactly
    :data:`alive.compose.config2._EXPECTED_METHOD_ROSTER` (9, order-fixed) and
    :data:`alive.compose.config2._EXPECTED_COMPARATOR_FAMILY` (5, order-fixed),
    referenced directly so the manifest can never drift from the registered
    config contract. Every other field is caller-supplied and fully validated.

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
        The COMPLETE pre-seal content-checksum set (spec §3.2): EXACTLY
        :data:`_REQUIRED_PRESEAL_CHECKSUM_KEYS` — config / data-card / manifest /
        sequence / feature / factor / response(-space) / model / bundle / ledger /
        pair-index / seed-report — each a 64-lowercase-hex digest.
    selected_hyperparameters : Mapping[str, Any]
        The selected hyperparameters (non-empty, JSON-serialisable, string keys).
    worker_identity : Mapping[str, Any]
        Per-method ``{gears, cpa}`` worker/config/resource/env identity — each a
        content-digest string or the ``ExecutionIdentityLock`` identity mapping.
    double_pair_count, single_pair_count : int
        The non-negative double-unseen / single-unseen pair counts.
    ordered_seal_request_checksum : str
        The intent checksum over the ORDERED pair set the seal will request
        (64 lowercase hex). phase2b's Task-9 ``intent_checksum`` re-verifies it.
    futility_status : str
        Must be exactly ``"CONTINUE"`` — a confirmation is only built on CONTINUE.
    sealed_access_count : int
        Must be ``0`` at confirmation time (the seal is never opened here).
    forbidden_output_absence : bool
        Must be ``True``, attesting no forbidden output artifact is present.
    accepted_limitations : Sequence[str]
        The owner-approved EXACT roster of accepted limitations (non-empty list
        of non-empty strings; element order preserved).

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
    hyperparameters = _validate_selected_hyperparameters(selected_hyperparameters)
    workers = _validate_worker_identity(worker_identity)
    double_count = _validate_pair_count(double_pair_count, "double_pair_count")
    single_count = _validate_pair_count(single_pair_count, "single_pair_count")
    if not _is_hex64(ordered_seal_request_checksum):
        raise ConfirmationError("ordered_seal_request_checksum must be 64 lowercase hex chars")
    _require_continue(futility_status)
    _require_zero_sealed_access_count(sealed_access_count)
    _require_forbidden_output_absence(forbidden_output_absence)
    limitations = _validate_accepted_limitations(accepted_limitations)

    payload: dict[str, Any] = {
        "schema": SEAL_CONFIRMATION_MANIFEST_SCHEMA,
        "run_id": run_id,
        "execution_id": execution_id,
        "resolved_run_spec_file_sha256": resolved_run_spec_file_sha256,
        "approved_git_sha": approved_git_sha,
        "git_clean": git_clean,
        "preseal_checksums": checksums,
        "selected_hyperparameters": hyperparameters,
        "worker_identity": workers,
        "double_pair_count": double_count,
        "single_pair_count": single_count,
        "ordered_seal_request_checksum": ordered_seal_request_checksum,
        "futility_status": futility_status,
        "sealed_access_count": sealed_access_count,
        "forbidden_output_absence": forbidden_output_absence,
        "accepted_limitations": limitations,
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
    6b. the FULL extended §3.2 field schema (defense in depth, independent of
       ``reconstruct_inputs``): the complete pre-seal checksum set, the selected
       hyperparameters, the per-method worker identity, the non-negative pair
       counts, the hex64 ordered seal-request checksum, ``futility_status ==
       "CONTINUE"``, ``sealed_access_count == 0``, ``forbidden_output_absence is
       True`` and a non-empty ``accepted_limitations`` list of strings — any
       violation fails closed;
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
        expects (:data:`_BUILD_INPUT_KEYS`: ``run_id``, ``execution_id``,
        ``resolved_run_spec_file_sha256``, ``approved_git_sha``, ``git_clean``,
        ``preseal_checksums``, ``selected_hyperparameters``, ``worker_identity``,
        ``double_pair_count``, ``single_pair_count``,
        ``ordered_seal_request_checksum``, ``futility_status``,
        ``sealed_access_count``, ``forbidden_output_absence``,
        ``accepted_limitations``), computed by the caller from the CURRENT
        non-sealed files/environment + attested sealed-input identity (never
        from the sealed source itself).

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

    # 6b. FULL extended §3.2 field schema (defense in depth) ------------------
    _validate_preseal_checksums(manifest.get("preseal_checksums"))
    _validate_selected_hyperparameters(manifest.get("selected_hyperparameters"))
    _validate_worker_identity(manifest.get("worker_identity"))
    _validate_pair_count(manifest.get("double_pair_count"), "double_pair_count")
    _validate_pair_count(manifest.get("single_pair_count"), "single_pair_count")
    if not _is_hex64(manifest.get("ordered_seal_request_checksum")):
        raise ConfirmationError("ordered_seal_request_checksum must be 64 lowercase hex chars")
    _require_continue(manifest.get("futility_status"))
    _require_zero_sealed_access_count(manifest.get("sealed_access_count"))
    _require_forbidden_output_absence(manifest.get("forbidden_output_absence"))
    _validate_accepted_limitations(manifest.get("accepted_limitations"))

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
        selected_hyperparameters=reconstruct_inputs["selected_hyperparameters"],
        worker_identity=reconstruct_inputs["worker_identity"],
        double_pair_count=reconstruct_inputs["double_pair_count"],
        single_pair_count=reconstruct_inputs["single_pair_count"],
        ordered_seal_request_checksum=reconstruct_inputs["ordered_seal_request_checksum"],
        futility_status=reconstruct_inputs["futility_status"],
        sealed_access_count=reconstruct_inputs["sealed_access_count"],
        forbidden_output_absence=reconstruct_inputs["forbidden_output_absence"],
        accepted_limitations=reconstruct_inputs["accepted_limitations"],
    )
    if _canonical_bytes(reconstructed) != _canonical_bytes(manifest):
        raise ConfirmationError(
            "reconstructed seal confirmation manifest diverges from the stored "
            "manifest — the current non-sealed inputs no longer match what was "
            "confirmed (fail closed; NO seal opened)"
        )
