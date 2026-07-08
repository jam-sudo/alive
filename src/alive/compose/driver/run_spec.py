"""ResolvedRunSpec v1 schema + fail-closed loader (COMPOSE production driver).

The COMPOSE single production driver (sub-project C) drives its three normal
subcommands (``phase2a`` / ``preflight`` / ``phase2b``) from one immutable
``ResolvedRunSpec`` that PREPARE (or, locally, the fixture builder) produces.
This module is the driver's **trust boundary**: it validates the spec's
canonical bytes, exact schema, self-checksum, own file SHA, mode-block
exclusivity, path policy, the 7-key ``expected_hashes`` roster, the declared
pre-seal digests against the actual on-disk bytes, and the recomputed
``run_id`` — raising :class:`RunSpecError` on ANY violation *before* returning a
frozen :class:`ResolvedRunSpec`.

Scope (deliberately narrow — this module is consumed by ten downstream tasks):

- Opens **no** seal, constructs **no** outcome store, imports no ``gears`` /
  ``cpa``. It is pure validation over declared paths and their byte digests
  (digest-only; no AnnData / backed parse).
- ``run_id`` is *recomputed* via
  :func:`alive.compose.datacard.compute_compose_run_id` from the spec's four
  run-identity digests and must equal the declared value; ``mode`` is only a
  dispatch selector and never contributes to ``run_id``.
- The **sealed source** is never opened/stat'd/hashed here (that is a post-seal
  ``phase2b`` step); only its declared ``sealed_input`` block is schema- and
  lexically path-checked.
- The runtime ``execution_id`` is computed by :func:`compute_execution_id` from
  the spec's own file SHA and is deliberately **not** stored inside the spec
  (avoids a file-SHA circular reference; spec §2.1).

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §2.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from alive.compose.datacard import compute_compose_run_id
from alive.provenance import sha256_file, sha256_json

__all__ = [
    "RESOLVED_RUN_SPEC_SCHEMA",
    "RUN_PRODUCED_BASENAMES",
    "EXPECTED_HASHES_KEYS",
    "PRE_SEAL_PATH_FIELDS",
    "WORKER_BLOCK_KEYS",
    "EXECUTION_IDENTITY_LOCK_KEYS",
    "RunSpecError",
    "PathSha",
    "WorkerBlock",
    "ResolvedRunSpec",
    "load_resolved_run_spec",
    "compute_execution_id",
]

# ---------------------------------------------------------------------------
# Schema constants (spec §2.2)
# ---------------------------------------------------------------------------

#: Exact ``schema`` discriminator every v1 ResolvedRunSpec must carry.
RESOLVED_RUN_SPEC_SCHEMA = "compose_resolved_run_spec_v1"

#: The two recognised dispatch modes.
_MODES = frozenset({"fixture", "scientific"})

#: Run-produced fixed basenames — pinned so a caller cannot choose arbitrary
#: output names. The loader requires the spec's ``run_produced_basenames`` block
#: to equal this mapping exactly (spec §2.2 / §7.1).
RUN_PRODUCED_BASENAMES: Mapping[str, str] = MappingProxyType(
    {
        "frozen_bundle": "frozen_prediction_bundle.json",
        "oof_manifest": "oof_fold_manifest.json",
        "phase2a_seed_variability_report": "phase2a_development_seed_variability.json",
        "run_ledger": "phase2a_run_ledger.json",
        "futility_report": "phase2a_futility.json",
        "seal_confirmation_manifest": "seal_confirmation_manifest.json",
    }
)

#: The seven — and only seven — keys of ``expected_hashes`` (spec §2.2).
EXPECTED_HASHES_KEYS: frozenset[str] = frozenset(
    {
        "response_space_checksum",
        "factor_checksum",
        "manifest_checksum",
        "environment_checksum",
        "data_card_checksum",
        "raw_data_checksum",
        "sequence_mapping_checksum",
    }
)

#: Pre-seal ``{path, sha256}`` fields the loader fully verifies (path policy +
#: on-disk byte-SHA match). Order mirrors spec §2.2.
PRE_SEAL_PATH_FIELDS: tuple[str, ...] = (
    "config",
    "data_card",
    "raw_asset",
    "sequence_mapping",
    "feature_bank",
    "factor_bank",
    "response_artifact",
    "fit_role_artifact",
    "phase2a_inputs",
    "development_outcome_source",
    "development_outcome_manifest",
    "pair_manifest",
    "pair_index_manifest",
    "approved_sealed_input_attestation",
)

#: The four immutable run-identity digests fed to ``compute_compose_run_id``.
_RUN_IDENTITY_DIGEST_FIELDS: tuple[str, ...] = (
    "config_digest",
    "data_card_digest",
    "raw_or_source_digest",
    "sequence_mapping_digest",
)

#: Scalar identity fields (spec §2.2 identity block, minus ``self_checksum``
#: which is validated separately, plus ``run_produced_basenames`` handled
#: on its own).
_IDENTITY_SCALAR_FIELDS: tuple[str, ...] = (
    "schema",
    "mode",
    "protocol",
    "run_id",
    "approved_git_sha",
    "run_dir",
    "approved_artifacts_root",
)

#: Keys every per-method worker block must carry (spec §2.2 / §5).
WORKER_BLOCK_KEYS: frozenset[str] = frozenset(
    {
        "env_python",
        "worker_script",
        "import_name",
        "worker_config",
        "resource_manifest",
        "requirements_lock",
        "execution_identity_lock",
    }
)

#: Path+SHA sub-objects inside a worker block (schema-checked here; their byte
#: digests are the ``ExecutionIdentityLock`` assembler's job in a later task).
_WORKER_PATH_SHA_KEYS: tuple[str, ...] = (
    "worker_script",
    "worker_config",
    "resource_manifest",
    "requirements_lock",
)

#: The 6-field identity lock declared per method (spec §5).
EXECUTION_IDENTITY_LOCK_KEYS: frozenset[str] = frozenset(
    {
        "prediction_representation",
        "environment_lock_sha256",
        "adapter_version",
        "adapter_sha256",
        "config_sha256",
        "resource_sha256",
    }
)

#: Required keys of the mode-specific blocks (spec §2.2).
_FIXTURE_BLOCK_KEYS: frozenset[str] = frozenset(
    {"fixture_corpus_id", "builder_code_digest", "sealed_input"}
)
_SCIENTIFIC_BLOCK_KEYS: frozenset[str] = frozenset(
    {"activation_evidence", "dependency_manifest", "device", "precision", "sealed_input"}
)
_FIXTURE_SEALED_INPUT_KEYS: frozenset[str] = frozenset(
    {"source_path", "expected_file_sha256", "audit_path"}
)
_SCIENTIFIC_SEALED_INPUT_KEYS: frozenset[str] = frozenset(
    {"source_path", "expected_file_sha256", "snapshot_id", "audit_path"}
)

#: Common top-level keys present in *both* modes (identity scalars +
#: ``self_checksum`` + pre-seal path fields + run-identity digests +
#: ``run_produced_basenames`` + ``expected_hashes`` + ``worker_blocks``).
_COMMON_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    (
        *_IDENTITY_SCALAR_FIELDS,
        "self_checksum",
        *PRE_SEAL_PATH_FIELDS,
        *_RUN_IDENTITY_DIGEST_FIELDS,
        "run_produced_basenames",
        "expected_hashes",
        "worker_blocks",
    )
)

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RunSpecError(ValueError):
    """Raised on ANY ResolvedRunSpec validation failure (fail-closed).

    Subclasses :class:`ValueError`. The loader raises this — and never returns a
    partially validated object — for canonical-byte, schema, self-checksum,
    file-SHA, mode-block, path-policy, ``expected_hashes``, declared-vs-actual
    digest, or ``run_id``-recompute violations.
    """


# ---------------------------------------------------------------------------
# Immutable value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathSha:
    """A declared ``{"path": str, "sha256": 64-lower-hex}`` object."""

    path: str
    sha256: str


@dataclass(frozen=True)
class WorkerBlock:
    """A per-method subprocess worker block (spec §2.2 / §5).

    ``execution_identity_lock`` holds the 6 declared identity fields; their
    binding to the *actual* worker/adapter bytes is performed later by the
    ``ExecutionIdentityLock`` assembler (a separate task), not by this loader.
    """

    env_python: str
    worker_script: PathSha
    import_name: str
    worker_config: PathSha
    resource_manifest: PathSha
    requirements_lock: PathSha
    execution_identity_lock: Mapping[str, str]


@dataclass(frozen=True)
class ResolvedRunSpec:
    """A validated, immutable ResolvedRunSpec v1 (spec §2.2).

    Every field mirrors the canonical JSON, except :attr:`file_sha256`, which is
    the loader-computed SHA-256 of the spec file's own bytes (used downstream to
    derive the runtime ``execution_id``; it is *not* stored inside the spec).
    """

    schema: str
    mode: str
    protocol: str
    run_id: str
    approved_git_sha: str
    run_dir: str
    approved_artifacts_root: str
    self_checksum: str
    file_sha256: str
    config_digest: str
    data_card_digest: str
    raw_or_source_digest: str
    sequence_mapping_digest: str
    pre_seal: Mapping[str, PathSha]
    run_produced_basenames: Mapping[str, str]
    expected_hashes: Mapping[str, str]
    worker_blocks: Mapping[str, WorkerBlock]
    fixture: Mapping[str, Any] | None
    scientific: Mapping[str, Any] | None


# ---------------------------------------------------------------------------
# Small validation helpers
# ---------------------------------------------------------------------------


def _canonical_bytes(obj: object) -> bytes:
    """Canonical JSON bytes (``sort_keys`` + compact separators)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX64_RE.match(value))


def _require_str(obj: Mapping[str, Any], key: str, *, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise RunSpecError(f"{where}: {key!r} must be a string")
    return value


def _parse_path_sha(obj: Any, *, field: str) -> PathSha:
    """Validate an exact ``{"path": str, "sha256": 64-lower-hex}`` object."""
    if not isinstance(obj, dict):
        raise RunSpecError(f"{field}: must be a {{path, sha256}} object")
    if set(obj) != {"path", "sha256"}:
        raise RunSpecError(
            f"{field}: must have exactly keys {{'path', 'sha256'}}, got {sorted(obj)}"
        )
    path = obj["path"]
    sha = obj["sha256"]
    if not isinstance(path, str):
        raise RunSpecError(f"{field}: 'path' must be a string")
    if not _is_hex64(sha):
        raise RunSpecError(f"{field}: 'sha256' must be 64 lowercase hex chars")
    return PathSha(path=path, sha256=sha)


def _check_path_policy(declared: str, root_real: str, *, kind: str, field: str) -> str:
    """Enforce §2.2 path policy for an on-disk path; return its realpath.

    Rejects non-absolute paths, ``..`` components, non-existent paths, symlinks,
    device/FIFO/socket nodes, wrong node kind, and any path resolving outside
    *root_real*.
    """
    if not isinstance(declared, str):
        raise RunSpecError(f"{field}: path must be a string")
    if not os.path.isabs(declared):
        raise RunSpecError(f"{field}: path must be absolute")
    if ".." in Path(declared).parts:
        raise RunSpecError(f"{field}: path must not contain '..'")
    if not os.path.lexists(declared):
        raise RunSpecError(f"{field}: path does not exist: {declared}")
    node = os.lstat(declared)
    if stat.S_ISLNK(node.st_mode):
        raise RunSpecError(f"{field}: symlink not permitted: {declared}")
    if kind == "file" and not stat.S_ISREG(node.st_mode):
        raise RunSpecError(f"{field}: not a regular file: {declared}")
    if kind == "dir" and not stat.S_ISDIR(node.st_mode):
        raise RunSpecError(f"{field}: not a directory: {declared}")
    real = os.path.realpath(declared)
    if real != root_real and not real.startswith(root_real + os.sep):
        raise RunSpecError(f"{field}: path escapes approved_artifacts_root: {declared}")
    return real


def _check_lexically_under_root(declared: str, root_real: str, *, field: str) -> None:
    """Lexical containment for paths NOT opened by the loader (sealed source,
    worker files). Rejects non-absolute paths, ``..`` and root escapes without
    touching the filesystem."""
    if not isinstance(declared, str):
        raise RunSpecError(f"{field}: path must be a string")
    if not os.path.isabs(declared):
        raise RunSpecError(f"{field}: path must be absolute")
    if ".." in Path(declared).parts:
        raise RunSpecError(f"{field}: path must not contain '..'")
    norm = os.path.normpath(declared)
    if norm != root_real and not norm.startswith(root_real + os.sep):
        raise RunSpecError(f"{field}: path escapes approved_artifacts_root: {declared}")


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_resolved_run_spec(
    path: str | Path,
    *,
    approved_artifacts_root: str | Path,
    mode_expected: str,
) -> ResolvedRunSpec:
    """Load, fully validate, and return an immutable :class:`ResolvedRunSpec`.

    Fail-closed: any violation raises :class:`RunSpecError` *before* a
    ``ResolvedRunSpec`` is returned. Validation order (spec §2.2 / §2.4):

    1. read + JSON-parse the file (must be a JSON object);
    2. canonical-bytes check (file bytes == canonical re-serialisation);
    3. ``mode`` present and recognised;
    4. mode-block exclusivity (forbidden block for the mode → reject);
    5. exact top-level key roster (unknown / missing / extra → reject);
    6. ``self_checksum`` == ``sha256_json(payload without self_checksum)``;
    7. compute the spec's own file SHA (for downstream ``execution_id``);
    8. ``mode == mode_expected``;
    9. ``run_produced_basenames`` == the pinned constant;
    10. ``expected_hashes`` keyset == the 7 keys exactly (each 64-hex);
    11. ``approved_artifacts_root`` == ``realpath`` of the CLI root;
    12. ``run_dir`` path policy (directory under root);
    13. each pre-seal ``{path, sha256}``: shape + path policy + byte-SHA match;
    14. worker-block schema + lexical path safety;
    15. mode-block schema + ``sealed_input`` lexical path safety;
    16. recomputed ``run_id`` == declared ``run_id``.

    Parameters
    ----------
    path
        Path to the canonical-JSON ResolvedRunSpec file.
    approved_artifacts_root
        The out-of-band CLI trust root. Its canonical ``realpath`` must equal
        the spec's declared ``approved_artifacts_root``.
    mode_expected
        The mode the caller (subcommand) requires; must equal the spec's
        ``mode``.

    Returns
    -------
    ResolvedRunSpec
        The validated, frozen spec (with the loader-computed ``file_sha256``).

    Raises
    ------
    RunSpecError
        On any schema, checksum, digest, path-policy, or ``run_id`` violation.
    """
    spec_path = Path(path)

    # 1. read + parse ------------------------------------------------------
    try:
        raw_bytes = spec_path.read_bytes()
    except OSError as exc:
        raise RunSpecError(f"cannot read ResolvedRunSpec {spec_path}: {exc}") from exc
    try:
        payload = json.loads(raw_bytes)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RunSpecError(f"ResolvedRunSpec is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RunSpecError("ResolvedRunSpec must be a JSON object")

    # 2. canonical-bytes check --------------------------------------------
    if _canonical_bytes(payload) != raw_bytes:
        raise RunSpecError(
            "ResolvedRunSpec file bytes are not canonical JSON "
            "(sort_keys + compact separators required)"
        )

    # 3. mode present + recognised ----------------------------------------
    mode = payload.get("mode")
    if mode not in _MODES:
        raise RunSpecError(f"mode must be one of {sorted(_MODES)}, got {mode!r}")

    # 4. mode-block exclusivity -------------------------------------------
    if mode == "fixture":
        if "scientific" in payload:
            raise RunSpecError("scientific block is not permitted in fixture mode")
        mode_block_key = "fixture"
    else:  # scientific
        if "fixture" in payload:
            raise RunSpecError("fixture block is not permitted in scientific mode")
        mode_block_key = "scientific"

    # 5. exact top-level key roster ---------------------------------------
    expected_keys = _COMMON_TOP_LEVEL_KEYS | {mode_block_key}
    actual_keys = set(payload)
    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys
    if missing or extra:
        raise RunSpecError(
            f"top-level key roster mismatch: missing={sorted(missing)} unexpected={sorted(extra)}"
        )

    # 6. self_checksum -----------------------------------------------------
    declared_self = payload["self_checksum"]
    if not _is_hex64(declared_self):
        raise RunSpecError("self_checksum must be 64 lowercase hex chars")
    body = {k: v for k, v in payload.items() if k != "self_checksum"}
    if declared_self != sha256_json(body):
        raise RunSpecError("self_checksum does not match payload (excluding self_checksum)")

    # 7. spec's own file SHA (downstream execution_id binding) -------------
    file_sha256 = sha256_file(spec_path)

    # 8. mode == mode_expected --------------------------------------------
    if mode != mode_expected:
        raise RunSpecError(f"mode {mode!r} does not match expected mode {mode_expected!r}")

    # 9. run_produced_basenames constant ----------------------------------
    if payload["run_produced_basenames"] != dict(RUN_PRODUCED_BASENAMES):
        raise RunSpecError(
            "run_produced_basenames must equal the pinned schema constant "
            "(caller may not choose run-produced basenames)"
        )

    # 10. expected_hashes roster ------------------------------------------
    expected_hashes = payload["expected_hashes"]
    if not isinstance(expected_hashes, dict):
        raise RunSpecError("expected_hashes must be an object")
    if set(expected_hashes) != set(EXPECTED_HASHES_KEYS):
        raise RunSpecError(
            "expected_hashes keyset mismatch: "
            f"missing={sorted(EXPECTED_HASHES_KEYS - set(expected_hashes))} "
            f"unexpected={sorted(set(expected_hashes) - EXPECTED_HASHES_KEYS)}"
        )
    for key, value in expected_hashes.items():
        if not _is_hex64(value):
            raise RunSpecError(f"expected_hashes[{key!r}] must be 64 lowercase hex chars")

    # 11. approved_artifacts_root == realpath(CLI root) -------------------
    root_real = os.path.realpath(str(approved_artifacts_root))
    declared_root = payload["approved_artifacts_root"]
    if not isinstance(declared_root, str) or declared_root != root_real:
        raise RunSpecError(
            "approved_artifacts_root must equal the canonical realpath of the "
            f"CLI --approved-artifacts-root ({root_real!r}); got {declared_root!r}"
        )

    # 12. run_dir path policy (directory under root) ----------------------
    _check_path_policy(payload["run_dir"], root_real, kind="dir", field="run_dir")

    # 13. pre-seal path+SHA: shape + policy + byte-SHA match ---------------
    pre_seal: dict[str, PathSha] = {}
    for field in PRE_SEAL_PATH_FIELDS:
        ps = _parse_path_sha(payload[field], field=field)
        _check_path_policy(ps.path, root_real, kind="file", field=field)
        actual = sha256_file(ps.path)
        if actual != ps.sha256:
            raise RunSpecError(
                f"{field}: declared sha256 {ps.sha256} != actual file digest {actual}"
            )
        pre_seal[field] = ps

    # 14. worker-block schema + lexical path safety -----------------------
    worker_blocks = _parse_worker_blocks(payload["worker_blocks"], root_real)

    # 15. mode-block schema + sealed_input lexical safety -----------------
    mode_block = payload[mode_block_key]
    _validate_mode_block(mode_block, mode=mode, root_real=root_real)

    # 16. recomputed run_id == declared -----------------------------------
    digests = {
        f: _require_str(payload, f, where="run-identity digest")
        for f in _RUN_IDENTITY_DIGEST_FIELDS
    }
    recomputed = compute_compose_run_id(
        config_digest=digests["config_digest"],
        data_card_digest=digests["data_card_digest"],
        raw_or_source_digest=digests["raw_or_source_digest"],
        sequence_mapping_digest=digests["sequence_mapping_digest"],
    )
    if recomputed != payload["run_id"]:
        raise RunSpecError(
            f"run_id mismatch: declared {payload['run_id']!r} != "
            f"recomputed {recomputed!r} (from the four run-identity digests)"
        )

    return ResolvedRunSpec(
        schema=_require_str(payload, "schema", where="identity"),
        mode=mode,
        protocol=_require_str(payload, "protocol", where="identity"),
        run_id=payload["run_id"],
        approved_git_sha=_require_str(payload, "approved_git_sha", where="identity"),
        run_dir=payload["run_dir"],
        approved_artifacts_root=declared_root,
        self_checksum=declared_self,
        file_sha256=file_sha256,
        config_digest=digests["config_digest"],
        data_card_digest=digests["data_card_digest"],
        raw_or_source_digest=digests["raw_or_source_digest"],
        sequence_mapping_digest=digests["sequence_mapping_digest"],
        pre_seal=MappingProxyType(pre_seal),
        run_produced_basenames=MappingProxyType(dict(RUN_PRODUCED_BASENAMES)),
        expected_hashes=MappingProxyType(dict(expected_hashes)),
        worker_blocks=MappingProxyType(worker_blocks),
        fixture=MappingProxyType(dict(mode_block)) if mode == "fixture" else None,
        scientific=MappingProxyType(dict(mode_block)) if mode == "scientific" else None,
    )


def _parse_worker_blocks(obj: Any, root_real: str) -> dict[str, WorkerBlock]:
    """Validate the per-method worker blocks (schema + lexical path safety).

    The loader does NOT byte-hash worker/adapter/config/resource/lock files:
    binding those declared digests to the actual bytes (and to the worker's
    self-report) is the ``ExecutionIdentityLock`` assembler's responsibility
    (spec §5) in a later task. Here we only enforce the declared shape and that
    worker paths are lexically contained under the approved root.
    """
    if not isinstance(obj, dict) or not obj:
        raise RunSpecError("worker_blocks must be a non-empty object")
    blocks: dict[str, WorkerBlock] = {}
    for method, block in obj.items():
        where = f"worker_blocks[{method!r}]"
        if not isinstance(block, dict):
            raise RunSpecError(f"{where}: must be an object")
        if set(block) != set(WORKER_BLOCK_KEYS):
            raise RunSpecError(
                f"{where}: key roster mismatch: "
                f"missing={sorted(WORKER_BLOCK_KEYS - set(block))} "
                f"unexpected={sorted(set(block) - WORKER_BLOCK_KEYS)}"
            )
        path_shas: dict[str, PathSha] = {}
        for sub in _WORKER_PATH_SHA_KEYS:
            ps = _parse_path_sha(block[sub], field=f"{where}.{sub}")
            _check_lexically_under_root(ps.path, root_real, field=f"{where}.{sub}")
            path_shas[sub] = ps
        lock = block["execution_identity_lock"]
        if not isinstance(lock, dict):
            raise RunSpecError(f"{where}.execution_identity_lock: must be an object")
        if set(lock) != set(EXECUTION_IDENTITY_LOCK_KEYS):
            raise RunSpecError(
                f"{where}.execution_identity_lock: key roster mismatch: "
                f"missing={sorted(EXECUTION_IDENTITY_LOCK_KEYS - set(lock))} "
                f"unexpected={sorted(set(lock) - EXECUTION_IDENTITY_LOCK_KEYS)}"
            )
        for key, value in lock.items():
            if not isinstance(value, str):
                raise RunSpecError(f"{where}.execution_identity_lock[{key!r}] must be a string")
        env_python = block["env_python"]
        import_name = block["import_name"]
        if not isinstance(env_python, str):
            raise RunSpecError(f"{where}.env_python must be a string")
        if not isinstance(import_name, str):
            raise RunSpecError(f"{where}.import_name must be a string")
        blocks[method] = WorkerBlock(
            env_python=env_python,
            worker_script=path_shas["worker_script"],
            import_name=import_name,
            worker_config=path_shas["worker_config"],
            resource_manifest=path_shas["resource_manifest"],
            requirements_lock=path_shas["requirements_lock"],
            execution_identity_lock=MappingProxyType(dict(lock)),
        )
    return blocks


def _validate_mode_block(block: Any, *, mode: str, root_real: str) -> None:
    """Validate a fixture/scientific block's schema and sealed_input paths.

    The sealed source is NOT opened/stat'd/hashed here — only the declared
    ``sealed_input`` block is schema- and lexically path-checked, so the pre-seal
    sealed-source access count stays 0 (spec §2.2 / §3.3).
    """
    if not isinstance(block, dict):
        raise RunSpecError(f"{mode} block must be an object")
    if mode == "fixture":
        required = _FIXTURE_BLOCK_KEYS
        sealed_keys = _FIXTURE_SEALED_INPUT_KEYS
    else:
        required = _SCIENTIFIC_BLOCK_KEYS
        sealed_keys = _SCIENTIFIC_SEALED_INPUT_KEYS
    if set(block) != set(required):
        raise RunSpecError(
            f"{mode} block key roster mismatch: "
            f"missing={sorted(required - set(block))} "
            f"unexpected={sorted(set(block) - required)}"
        )
    sealed = block["sealed_input"]
    if not isinstance(sealed, dict):
        raise RunSpecError(f"{mode} block sealed_input must be an object")
    if set(sealed) != set(sealed_keys):
        raise RunSpecError(
            f"{mode} block sealed_input key roster mismatch: "
            f"missing={sorted(sealed_keys - set(sealed))} "
            f"unexpected={sorted(set(sealed) - sealed_keys)}"
        )
    if not _is_hex64(sealed.get("expected_file_sha256")):
        raise RunSpecError(
            f"{mode} block sealed_input.expected_file_sha256 must be 64 lowercase hex chars"
        )
    _check_lexically_under_root(
        sealed["source_path"], root_real, field=f"{mode}.sealed_input.source_path"
    )
    _check_lexically_under_root(
        sealed["audit_path"], root_real, field=f"{mode}.sealed_input.audit_path"
    )


# ---------------------------------------------------------------------------
# Runtime execution identity (not stored in the spec; spec §2.1)
# ---------------------------------------------------------------------------


def compute_execution_id(
    run_id: str,
    resolved_run_spec_file_sha256: str,
    approved_git_sha: str,
) -> str:
    """Runtime execution identity = ``sha256_json`` of the binding triple.

    Computed *after* the final canonical spec file is installed, binding the
    scientific ``run_id`` to the spec's own file SHA and the approved Git SHA.
    Deliberately **not** stored inside the ResolvedRunSpec (that would create a
    file-SHA circular reference; spec §2.1). Recorded downstream in the phase2a
    ledger and the confirmation manifest.

    Parameters
    ----------
    run_id
        The composite COMPOSE run identifier.
    resolved_run_spec_file_sha256
        SHA-256 of the ResolvedRunSpec file's own bytes
        (:attr:`ResolvedRunSpec.file_sha256`).
    approved_git_sha
        The exact approved Git SHA the run executes at.

    Returns
    -------
    str
        Hex-encoded SHA-256 of the canonical binding object.
    """
    return sha256_json(
        {
            "run_id": run_id,
            "resolved_run_spec_file_sha256": resolved_run_spec_file_sha256,
            "approved_git_sha": approved_git_sha,
        }
    )
