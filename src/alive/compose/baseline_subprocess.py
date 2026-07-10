# src/alive/compose/baseline_subprocess.py
"""SYNTHETIC-ONLY: fit-role-only subprocess protocol for deep combo baselines.

No ``gears``/``cpa`` import here; the real backends run only inside pod-only
worker scripts. This module serializes a fit-role payload, invokes a worker
under a locked-env python, and returns response-space delta. See
docs/superpowers/specs/2026-07-01-compose-deep-baselines-design.md §1.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field
from pathlib import Path

import numpy as np

from alive.compose.baselines_combo import BaselineUnavailable, _assert_no_sealed_reference

# ``PREDICTION_REPRESENTATIONS`` is re-exported here for the Task-5 envelope /
# worker execution-manifest contract; imported now so the symbol lives in this
# module's namespace from the payload-v2 schema bump onward.
from alive.compose.fit_role import PREDICTION_REPRESENTATIONS  # noqa: F401

_SCHEMA_VERSION = 2
_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "response_dim",
        "seed",
        "allowed_roles",
        "pair_ids",
        "single_gene_ids",
        "singles_response",
        "control_mean",
        "calibration_pair_ids",
        "calibration_delta",
        "pca_components",
        "oof_folds",
        "fit_role_artifact",
        "response_projection",
    }
)

_FIT_ROLE_KEYS: frozenset[str] = frozenset(
    {
        "format",
        "artifact_schema_version",
        "path",
        "sha256",
        "content_manifest_sha256",
        "raw_data_sha256",
        "pair_manifest_sha256",
        "eligibility_hash",
        "row_identity_sha256",
        "role_obs_key",
        "perturbation_obs_key",
        "allowed_obs_roles",
        "gene_order_sha256",
        "n_cells",
        "n_genes",
        "role_counts",
        "counts_location",
    }
)
_ALLOWED_OBS_ROLES: frozenset[str] = frozenset({"control", "singles", "combo_calibration"})

_WORKER_IDENTITY_PATH_ENV: dict[str, str] = {
    "worker_config": "ALIVE_WORKER_CONFIG_PATH",
    "resource_manifest": "ALIVE_WORKER_RESOURCE_MANIFEST_PATH",
    "requirements_lock": "ALIVE_WORKER_REQUIREMENTS_LOCK_PATH",
    "adapter_artifact": "ALIVE_WORKER_ADAPTER_ARTIFACT_PATH",
}
_WORKER_IDENTITY_DIGEST_ENV: dict[str, tuple[str, str]] = {
    "worker_config": ("ALIVE_WORKER_CONFIG_SHA256", "config_sha256"),
    "resource_manifest": ("ALIVE_WORKER_RESOURCE_SHA256", "resource_sha256"),
    "requirements_lock": (
        "ALIVE_WORKER_ENVIRONMENT_LOCK_SHA256",
        "environment_lock_sha256",
    ),
    "adapter_artifact": ("ALIVE_WORKER_ADAPTER_SHA256", "adapter_sha256"),
}
_CHECKPOINT_DIRNAME = ".worker_checkpoints"
_CUBLAS_WORKSPACE_CONFIG = ":4096:8"
_WORKER_EXECUTABLE_PATH_ENV = "ALIVE_WORKER_EXECUTABLE_PATH"
_WORKER_EXECUTABLE_SHA_ENV = "ALIVE_WORKER_EXECUTABLE_SHA256"
_WORKER_PAYLOAD_SHA_ENV = "ALIVE_WORKER_PAYLOAD_SHA256"
_FIXED_WORKER_ENV: Mapping[str, str] = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
    "MPLBACKEND": "Agg",
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
    "CUBLAS_WORKSPACE_CONFIG": _CUBLAS_WORKSPACE_CONFIG,
}

_RESPONSE_PROJECTION_KEYS: frozenset[str] = frozenset(
    {
        "response_artifact_sha256",
        "raw_data_sha256",
        "gene_order_sha256",
        "hvg_gene_ids",
        "transform",
        "median_library",
        "pca_mean",
        "pca_components",
        "control_mean",
        "delta_convention",
    }
)


class PayloadError(ValueError):
    """Raised on a malformed payload / prediction file (unknown or missing key)."""


def _validate_pair_list(value: object, *, name: str) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        raise PayloadError(f"{name} must be a list")
    pairs: list[tuple[str, str]] = []
    for raw in value:
        if (
            not isinstance(raw, list)
            or len(raw) != 2
            or not all(isinstance(gene, str) and gene for gene in raw)
        ):
            raise PayloadError(f"{name} entries must be two non-empty gene strings")
        pair = (raw[0], raw[1])
        if pair[0].encode("utf-8") >= pair[1].encode("utf-8"):
            raise PayloadError(f"{name} pair must be canonical and non-self: {pair!r}")
        if pair in pairs:
            raise PayloadError(f"{name} contains duplicate pair {pair!r}")
        pairs.append(pair)
    return pairs


def _is_bare_sha256(value: object) -> bool:
    """Return ``True`` for an exact bare 64-character lowercase-hex digest."""
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _is_file_sha256(value: object) -> bool:
    """Return ``True`` for an exact ``"sha256:" + <64 lowercase hex>`` file digest."""
    return isinstance(value, str) and value.startswith("sha256:") and _is_bare_sha256(value[7:])


def _float_hex(arr) -> list:
    """Canonical float64 ``.hex()`` list for exact cross-block float equality."""
    flat = np.asarray(arr, dtype=np.float64).ravel(order="C")
    return [float(v).hex() for v in flat]


def _float_hex_equal(a, b) -> bool:
    """Return ``True`` iff ``a`` and ``b`` are shape- and bitwise-float64-equal."""
    aa, bb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return aa.shape == bb.shape and _float_hex(aa) == _float_hex(bb)


def _validate_fit_role_block(block: object) -> None:
    """Structurally validate the ``fit_role_artifact`` payload block (spec §2.1).

    The block is checked for its exact key set, frozen format/obs-key contract,
    the exact allowed-role roster, digest formats (file vs. bare hex), and
    non-negative integer counts that sum to ``n_cells``. No file existence or
    on-disk content check happens here — the worker re-validates the ``.h5ad``
    at fit time.

    Parameters
    ----------
    block : object
        The candidate ``fit_role_artifact`` block.

    Raises
    ------
    PayloadError
        On any structural, format, digest or count violation.
    """
    if not isinstance(block, dict) or set(block) != set(_FIT_ROLE_KEYS):
        raise PayloadError("fit_role_artifact has an unexpected key set")
    if block["format"] != "anndata_h5ad" or block["counts_location"] != "X":
        raise PayloadError("fit_role_artifact format/counts_location invalid")
    if block["artifact_schema_version"] != 1:
        raise PayloadError("fit_role_artifact artifact_schema_version must be 1")
    if block["role_obs_key"] != "role" or block["perturbation_obs_key"] != "perturbation":
        raise PayloadError("fit_role_artifact obs-key contract invalid")
    roles = block["allowed_obs_roles"]
    if not isinstance(roles, list) or set(roles) != _ALLOWED_OBS_ROLES or len(roles) != 3:
        raise PayloadError("fit_role_artifact allowed_obs_roles must be the exact role roster")
    if not _is_file_sha256(block["sha256"]):
        raise PayloadError("fit_role_artifact file sha must be exact sha256:<64 lowercase hex>")
    for key in ("content_manifest_sha256", "gene_order_sha256", "row_identity_sha256"):
        if not _is_bare_sha256(block[key]):
            raise PayloadError(f"fit_role_artifact {key} must be exact 64 lowercase hex")
    for key in ("raw_data_sha256", "pair_manifest_sha256", "eligibility_hash"):
        if not isinstance(block[key], str) or not block[key]:
            raise PayloadError(f"fit_role_artifact {key} must be a non-empty string")
    if any(
        isinstance(block[k], bool) or not isinstance(block[k], int) or block[k] < 1
        for k in ("n_cells", "n_genes")
    ):
        raise PayloadError("fit_role_artifact n_cells/n_genes must be positive ints")
    counts = block["role_counts"]
    if not isinstance(counts, dict) or set(counts) != _ALLOWED_OBS_ROLES:
        raise PayloadError("fit_role_artifact role_counts must have the exact role roster")
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts.values()):
        raise PayloadError("fit_role_artifact role_counts must be non-negative ints")
    if sum(counts.values()) != block["n_cells"]:
        raise PayloadError("fit_role_artifact role_counts do not sum to n_cells")


def _validate_response_projection(
    block: object,
    payload: dict,
    response_dim: int,
    *,
    expected_response_artifact_sha256: str | None,
) -> None:
    """Validate the ``response_projection`` block + its cross-source equality (spec §2.2).

    Beyond the block's own key set / frozen transform / digest and shape checks,
    this enforces that the serialized operator arrays equal the top-level payload
    arrays bit-for-bit (float64 ``.hex()``), that the raw-data and gene-order
    digests equal the ``fit_role_artifact`` block's, and — when the controller
    supplies it — that ``response_artifact_sha256`` equals the independently
    verified response-artifact digest.

    Parameters
    ----------
    block : object
        The candidate ``response_projection`` block.
    payload : dict
        The full payload (for the cross-source ``pca_components`` / ``control_mean``
        and ``fit_role_artifact`` digest equality checks).
    response_dim : int
        The already-validated positive response dimension.
    expected_response_artifact_sha256 : str or None
        The independently verified combined response-artifact digest, or ``None``
        to skip that binding (supplied by the controller in a later task).

    Raises
    ------
    PayloadError
        On any structural, digest, shape, finiteness or cross-source mismatch.
    """
    if not isinstance(block, dict) or set(block) != set(_RESPONSE_PROJECTION_KEYS):
        raise PayloadError("response_projection has an unexpected key set")
    if block["transform"] != ["normalize_total_median", "log1p"]:
        raise PayloadError("response_projection transform is not the frozen transform")
    if block["delta_convention"] != "z_minus_control_mean":
        raise PayloadError("response_projection delta_convention invalid")
    if not _is_bare_sha256(block["response_artifact_sha256"]):
        raise PayloadError("response_projection response_artifact_sha256 must be 64 hex")
    if (
        expected_response_artifact_sha256 is not None
        and block["response_artifact_sha256"] != expected_response_artifact_sha256
    ):
        raise PayloadError("response_projection is not bound to the verified response artifact")
    if not _is_bare_sha256(block["gene_order_sha256"]):
        raise PayloadError("response_projection gene_order_sha256 must be 64 hex")
    hvg = block["hvg_gene_ids"]
    if (
        not isinstance(hvg, list)
        or not hvg
        or not all(isinstance(g, str) and g for g in hvg)
        or len(set(hvg)) != len(hvg)
    ):
        raise PayloadError("hvg_gene_ids must be a non-empty unique string list")
    n_hvg = len(hvg)
    pca_mean = np.asarray(block["pca_mean"], dtype=float)
    if pca_mean.shape != (n_hvg,) or not np.all(np.isfinite(pca_mean)):
        raise PayloadError("response_projection pca_mean must be a finite length-n_hvg vector")
    components = np.asarray(block["pca_components"], dtype=float)
    if components.shape != (response_dim, n_hvg) or not np.all(np.isfinite(components)):
        raise PayloadError("response_projection pca_components must be (response_dim, n_hvg)")
    control = np.asarray(block["control_mean"], dtype=float)
    if control.shape != (response_dim,) or not np.all(np.isfinite(control)):
        raise PayloadError("response_projection control_mean must be a finite response_dim vector")
    if (
        isinstance(block["median_library"], bool)
        or not isinstance(block["median_library"], (int, float))
        or not np.isfinite(block["median_library"])
        or block["median_library"] <= 0
    ):
        raise PayloadError("response_projection median_library must be a positive number")
    # cross-source equality (spec §2.2)
    if not _float_hex_equal(components, payload["pca_components"]):
        raise PayloadError("response_projection pca_components diverge from payload pca_components")
    if not _float_hex_equal(control, payload["control_mean"]):
        raise PayloadError("response_projection control_mean diverge from payload control_mean")
    fit_role = payload["fit_role_artifact"]
    if block["raw_data_sha256"] != fit_role["raw_data_sha256"]:
        raise PayloadError("response_projection raw_data_sha256 diverges from fit_role_artifact")
    if block["gene_order_sha256"] != fit_role["gene_order_sha256"]:
        raise PayloadError("response_projection gene_order_sha256 diverges from fit_role_artifact")


def _validate_payload(
    payload: dict,
    *,
    expected_response_artifact_sha256: str | None = None,
) -> None:
    if set(payload) != set(_REQUIRED_KEYS):
        raise PayloadError("payload has an unexpected key set")
    if payload["schema_version"] != _SCHEMA_VERSION:
        raise PayloadError(f"unsupported schema_version {payload['schema_version']}")
    response_dim = payload["response_dim"]
    if isinstance(response_dim, bool) or not isinstance(response_dim, int) or response_dim < 1:
        raise PayloadError("response_dim must be a positive int")
    if isinstance(payload["seed"], bool) or not isinstance(payload["seed"], int):
        raise PayloadError("seed must be an int")
    roles = payload["allowed_roles"]
    if not isinstance(roles, list) or set(roles) != {"singles", "combo_calibration"}:
        raise PayloadError("allowed_roles must be exactly singles + combo_calibration")
    genes = payload["single_gene_ids"]
    if (
        not isinstance(genes, list)
        or not genes
        or not all(isinstance(gene, str) and gene for gene in genes)
        or len(set(genes)) != len(genes)
    ):
        raise PayloadError("single_gene_ids must be a non-empty unique string list")
    singles = np.asarray(payload["singles_response"], dtype=float)
    if singles.shape != (len(genes), response_dim) or not np.all(np.isfinite(singles)):
        raise PayloadError("singles_response must be finite and aligned to genes/response_dim")
    control = np.asarray(payload["control_mean"], dtype=float)
    if control.shape != (response_dim,) or not np.all(np.isfinite(control)):
        raise PayloadError("control_mean must be a finite response_dim vector")
    requested = _validate_pair_list(payload["pair_ids"], name="pair_ids")
    calibration = _validate_pair_list(payload["calibration_pair_ids"], name="calibration_pair_ids")
    universe = set(genes)
    if any(gene not in universe for pair in (*requested, *calibration) for gene in pair):
        raise PayloadError("all payload pair genes must exist in single_gene_ids")
    if set(requested) & set(calibration):
        raise PayloadError("pair_ids must be disjoint from calibration_pair_ids")
    calibration_delta = np.asarray(payload["calibration_delta"], dtype=float)
    if calibration_delta.shape != (len(calibration), response_dim) or not np.all(
        np.isfinite(calibration_delta)
    ):
        raise PayloadError("calibration_delta must be finite and pair/response aligned")
    components = np.asarray(payload["pca_components"], dtype=float)
    if (
        components.ndim != 2
        or components.shape[0] != response_dim
        or not np.all(np.isfinite(components))
    ):
        raise PayloadError("pca_components must be finite 2-D with response_dim rows")
    folds = payload["oof_folds"]
    if (
        not isinstance(folds, list)
        or len(folds) != len(calibration)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in folds
        )
    ):
        raise PayloadError("oof_folds must be non-negative ints aligned to calibration pairs")
    _validate_fit_role_block(payload["fit_role_artifact"])
    _validate_response_projection(
        payload["response_projection"],
        payload,
        response_dim,
        expected_response_artifact_sha256=expected_response_artifact_sha256,
    )


def _canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_payload_sha256(payload: Mapping[str, object]) -> str:
    """Return the digest of the one canonical payload serialization."""
    snapshot = dict(payload)
    _validate_payload(snapshot)
    return _sha256(_canonical_json(snapshot))


def write_payload(work_dir: str, payload: dict) -> str:
    _validate_payload(payload)
    os.makedirs(work_dir, exist_ok=True)
    text = _canonical_json(payload)
    with open(os.path.join(work_dir, "payload.json"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return _sha256(text)


def read_payload(work_dir: str, *, require_expected_sha256: bool = False) -> dict:
    """Read canonical payload bytes and optionally require the controller digest.

    Production workers set ``require_expected_sha256=True``.  The expected digest
    comes only from the controller's sanitized environment, so replacing the
    temporary pathname after the parent writes it cannot change worker inputs
    without being detected.  Direct library callers retain a validation-only
    mode for local payload construction tests.
    """
    data = _read_regular_bytes(os.path.join(work_dir, "payload.json"), field="payload")

    def _object_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise PayloadError(f"payload contains duplicate key {key!r}")
            value[key] = item
        return value

    def _reject_constant(value: str) -> None:
        raise PayloadError(f"payload contains non-finite JSON number {value!r}")

    try:
        text = data.decode("utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=_object_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadError(f"payload is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PayloadError("payload root must be a JSON object")
    _validate_payload(payload)
    canonical = _canonical_json(payload)
    if text != canonical:
        raise PayloadError("payload bytes are not canonical JSON")
    observed = _sha256(canonical)
    expected = os.environ.get(_WORKER_PAYLOAD_SHA_ENV)
    if require_expected_sha256 and not _is_bare_sha256(expected):
        raise PayloadError("controller payload SHA-256 is missing or malformed")
    if expected is not None and (not _is_bare_sha256(expected) or observed != expected):
        raise PayloadError("payload SHA-256 differs from the controller-bound digest")
    return payload


#: The exact key set every worker execution manifest must carry (Task 5).
EXECUTION_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "prediction_representation",
        "adapter_version",
        "adapter_sha256",
        "expected_gene_order_sha256",
        "observed_gene_order_sha256",
        "checkpoint_sha256",
        "worker_sha256",
        "config_sha256",
        "resource_sha256",
        "environment_lock_sha256",
        "payload_sha256",
        "fit_artifact_content_sha256",
        "combined_request_sha256",
        "predictions_sha256",
    }
)


@dataclass(frozen=True)
class ExecutionIdentityLock:
    """Controller-trusted, out-of-band worker-execution identity (spec §2.5).

    The controller supplies this at construction; it is the ground truth that a
    self-reported worker execution manifest is verified against. A worker may not
    select its own representation, adapter, config, resource or environment
    identity — every field here is compared to the worker's claim and any
    divergence fails closed.

    Attributes
    ----------
    prediction_representation : str
        The registered prediction representation the worker is locked to; one of
        :data:`PREDICTION_REPRESENTATIONS`.
    adapter_version : str
        The pinned adapter version identity.
    adapter_sha256 : str
        The pinned adapter content digest (bare 64 lowercase hex).
    config_sha256 : str
        The pinned worker-config digest (bare 64 lowercase hex).
    resource_sha256 : str
        The pinned resource-manifest digest (bare 64 lowercase hex).
    environment_lock_sha256 : str
        The pinned environment-lock digest (bare 64 lowercase hex).
    """

    prediction_representation: str
    adapter_version: str
    adapter_sha256: str
    config_sha256: str
    resource_sha256: str
    environment_lock_sha256: str


def _validate_execution_manifest(manifest: object) -> None:
    """Structurally validate a worker execution manifest (spec §2.5).

    Checks the exact key set, that ``prediction_representation`` is a registered
    enum, that expected and observed gene orders agree, and that every field is a
    non-empty 64-lowercase-hex digest string. This is a self-consistency check
    only; it is **not** evidence that the worker's claimed identities are the
    controller's expected identities (that is :func:`_verify_execution_manifest`).

    Parameters
    ----------
    manifest : object
        The candidate execution manifest.

    Raises
    ------
    PayloadError
        On any structural, enum, gene-order or digest-format violation.
    """
    if not isinstance(manifest, dict) or set(manifest) != set(EXECUTION_MANIFEST_KEYS):
        raise PayloadError("execution_manifest has an unexpected key set")
    if manifest["prediction_representation"] not in PREDICTION_REPRESENTATIONS:
        raise PayloadError("execution_manifest prediction_representation is not a registered enum")
    if manifest["expected_gene_order_sha256"] != manifest["observed_gene_order_sha256"]:
        raise PayloadError("worker observed a different gene order than expected")
    for key in EXECUTION_MANIFEST_KEYS:
        if not (isinstance(manifest[key], str) and manifest[key]):
            raise PayloadError(f"execution_manifest {key} must be a non-empty string")
    for key in (
        "adapter_sha256",
        "expected_gene_order_sha256",
        "observed_gene_order_sha256",
        "checkpoint_sha256",
        "worker_sha256",
        "fit_artifact_content_sha256",
        "combined_request_sha256",
        "predictions_sha256",
        "config_sha256",
        "resource_sha256",
        "environment_lock_sha256",
        "payload_sha256",
    ):
        if not _is_bare_sha256(manifest[key]):
            raise PayloadError(f"execution_manifest {key} must be exact 64 lowercase hex")


def _ordered_request_sha256(pair_ids: Sequence[tuple[str, str]]) -> str:
    """Return the order-sensitive digest of a requested pair-ID sequence."""
    return _sha256(_canonical_json([list(pair) for pair in pair_ids]))


def _stable_stat_tuple(value: os.stat_result) -> tuple[int, ...]:
    """Return the file attributes that must not change during a trusted read."""
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_nlink),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _open_regular_no_follow(path: str, *, field: str) -> tuple[int, os.stat_result]:
    """Open ``path`` as the same regular, non-symlink node observed by ``lstat``."""
    if not isinstance(path, str) or not path:
        raise PayloadError(f"{field} path must be a non-empty string")
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise PayloadError(f"cannot stat {field}: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise PayloadError(f"{field} must be a regular non-symlink file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise PayloadError(f"cannot open {field}: {exc}") from exc
    opened = os.fstat(fd)
    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
        before.st_dev,
        before.st_ino,
    ):
        os.close(fd)
        raise PayloadError(f"{field} changed between lstat and open")
    return fd, opened


def _open_regular_at(
    dir_fd: int,
    name: str,
    *,
    field: str,
) -> tuple[int, os.stat_result]:
    """Open a direct child of ``dir_fd`` without following a final symlink."""
    try:
        before = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError as exc:
        raise PayloadError(f"cannot stat {field}: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise PayloadError(f"{field} must be a regular non-symlink file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, dir_fd=dir_fd)
    except OSError as exc:
        raise PayloadError(f"cannot open {field}: {exc}") from exc
    opened = os.fstat(fd)
    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
        before.st_dev,
        before.st_ino,
    ):
        os.close(fd)
        raise PayloadError(f"{field} changed between stat and open")
    return fd, opened


def _hash_open_fd(fd: int, before: os.stat_result, *, field: str) -> str:
    """Hash an open regular file and reject any in-place mutation during the read."""
    h = hashlib.sha256()
    while True:
        chunk = os.read(fd, 1 << 20)
        if not chunk:
            break
        h.update(chunk)
    after = os.fstat(fd)
    if _stable_stat_tuple(after) != _stable_stat_tuple(before):
        raise PayloadError(f"{field} changed while being read")
    return h.hexdigest()


def _file_sha256_bare(path: str) -> str:
    """Return a stable bare SHA-256 of a regular, non-symlink file."""
    fd, before = _open_regular_no_follow(path, field="hashed file")
    try:
        return _hash_open_fd(fd, before, field="hashed file")
    finally:
        os.close(fd)


def _read_regular_bytes(path: str, *, field: str) -> bytes:
    """Read stable bytes from a regular, non-symlink file."""
    fd, before = _open_regular_no_follow(path, field=field)
    chunks: list[bytes] = []
    try:
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        if _stable_stat_tuple(after) != _stable_stat_tuple(before):
            raise PayloadError(f"{field} changed while being read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _validated_worker_bundle_method(path: str, *, expected_sha256: str) -> str:
    """Controller-only lazy validation returning a bundle's registered method."""
    try:
        from alive.compose.worker_bundle import (  # controller-only lazy import
            WorkerBundleError,
            validate_worker_bundle,
        )

        info = validate_worker_bundle(path, expected_sha256=expected_sha256)
    except WorkerBundleError as exc:
        raise PayloadError(f"worker execution bundle is invalid: {exc}") from exc
    method = info.manifest["method"]
    if not isinstance(method, str):  # validated schema; defensive typing boundary
        raise PayloadError("worker execution bundle method is invalid")
    return method


def _snapshot_verified_worker_script(
    worker_script: str,
    destination: str,
    *,
    expected_sha256: str,
    expected_method: str,
    allow_fixture_stub: bool,
    allow_direct_py: bool,
) -> str:
    """Copy a verified worker executable into a fresh read-only snapshot.

    Bundle validation is a controller-only lazy import: this module is itself a
    bundle helper and must remain importable when ``worker_bundle`` is absent from
    the archive roster. Direct ``.py`` execution is explicit local/unit
    compatibility only.
    """
    if not _is_bare_sha256(expected_sha256):
        raise PayloadError("expected worker SHA-256 must be exact 64 lowercase hex")
    is_bundle = worker_script.endswith(".pyz")
    if not is_bundle and (not allow_direct_py or not worker_script.endswith(".py")):
        raise PayloadError("worker executable must be a verified .pyz bundle")
    if is_bundle:
        method = _validated_worker_bundle_method(
            worker_script,
            expected_sha256=expected_sha256,
        )
        allowed_methods = {expected_method}
        if allow_fixture_stub:
            allowed_methods.add("stub")
        if method not in allowed_methods:
            raise PayloadError("worker bundle method differs from controller expectation")
    data = _read_regular_bytes(worker_script, field="worker script")
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise PayloadError("worker script bytes differ from the trusted worker identity")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(destination, flags, 0o400)
    except OSError as exc:
        raise PayloadError(f"cannot create worker execution snapshot: {exc}") from exc
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise PayloadError("short write while snapshotting worker script")
            view = view[written:]
        os.fchmod(fd, 0o400)
        os.fsync(fd)
    finally:
        os.close(fd)
    if _file_sha256_bare(destination) != expected_sha256:
        raise PayloadError("worker execution snapshot failed post-write verification")
    if is_bundle:
        _validated_worker_bundle_method(destination, expected_sha256=expected_sha256)
    return destination


def _verify_execution_manifest(
    manifest: Mapping[str, str],
    *,
    payload: Mapping[str, object],
    requested_pair_ids: Sequence[tuple[str, str]],
    worker_script: str,
    checkpoint_path: str,
    identity_lock: ExecutionIdentityLock,
    expected_worker_sha256: str | None = None,
    expected_payload_sha256: str | None = None,
) -> None:
    """Independently verify a worker execution manifest (spec §2.5).

    A structurally self-consistent worker manifest is not evidence: this
    controller-side check RECOMPUTES the worker-script digest, the ordered
    request digest, the fit-artifact content digest and the checkpoint-file
    digest, reads the expected gene order from the payload, and compares the
    adapter / config / resource / environment / representation identities to the
    trusted :class:`ExecutionIdentityLock` — never to the worker's own claims.

    Parameters
    ----------
    manifest : Mapping
        The worker-reported execution manifest.
    payload : Mapping
        The fit-role payload the worker was invoked with (source of the expected
        gene order and fit-artifact content digest).
    requested_pair_ids : Sequence of tuple of str
        The exact ordered pair IDs the controller requested.
    worker_script : str
        Path to the worker script the controller launched.
    checkpoint_path : str
        Path to the checkpoint sidecar the worker produced.
    identity_lock : ExecutionIdentityLock
        The controller-trusted, out-of-band execution identity.
    expected_worker_sha256 : str, optional
        Out-of-band digest of the verified execution snapshot. When supplied,
        neither worker self-report nor a post-run pathname hash may replace it.

    Raises
    ------
    PayloadError
        On any structural violation or any divergence between the worker's claim
        and the controller-computed / trusted identity.
    """
    _validate_execution_manifest(dict(manifest))
    observed_worker_sha256 = _file_sha256_bare(worker_script)
    if expected_worker_sha256 is not None:
        if not _is_bare_sha256(expected_worker_sha256):
            raise PayloadError("expected worker SHA-256 must be exact 64 lowercase hex")
        if observed_worker_sha256 != expected_worker_sha256:
            raise PayloadError("executed worker snapshot differs from trusted worker identity")
    expected = {
        "prediction_representation": identity_lock.prediction_representation,
        "adapter_version": identity_lock.adapter_version,
        "adapter_sha256": identity_lock.adapter_sha256,
        "config_sha256": identity_lock.config_sha256,
        "resource_sha256": identity_lock.resource_sha256,
        "environment_lock_sha256": identity_lock.environment_lock_sha256,
        "payload_sha256": expected_payload_sha256,
        "expected_gene_order_sha256": payload["response_projection"]["gene_order_sha256"],
        "fit_artifact_content_sha256": payload["fit_role_artifact"]["content_manifest_sha256"],
        "combined_request_sha256": _ordered_request_sha256(requested_pair_ids),
        "worker_sha256": expected_worker_sha256 or observed_worker_sha256,
        "checkpoint_sha256": _file_sha256_bare(checkpoint_path),
    }
    if not _is_bare_sha256(expected_payload_sha256):
        raise PayloadError("expected payload SHA-256 must be exact 64 lowercase hex")
    for key, value in expected.items():
        if manifest[key] != value:
            raise PayloadError(f"execution_manifest {key} differs from controller expectation")


def write_predictions(
    path: str,
    preds: Mapping[tuple[str, str], np.ndarray],
    *,
    execution_manifest: Mapping[str, object],
) -> str:
    """Write the ``{schema_version, predictions, execution_manifest}`` envelope.

    The predictions are serialized as ``[pair, vector]`` records; their canonical
    digest is written into ``execution_manifest["predictions_sha256"]`` and the
    full manifest is structurally validated before the file is emitted.

    Parameters
    ----------
    path : str
        Output stem; ``".json"`` is appended.
    preds : Mapping
        Mapping from canonical pair ID to its response-space prediction vector.
    execution_manifest : Mapping
        The worker execution manifest (its ``predictions_sha256`` is overwritten
        with the digest of the serialized predictions before validation).

    Returns
    -------
    str
        The bare-hex SHA-256 of the serialized envelope file.

    Raises
    ------
    PayloadError
        If the resulting execution manifest is structurally invalid.
    """
    pairs = [[list(p), np.asarray(v, dtype=float).tolist()] for p, v in preds.items()]
    predictions_sha256 = _sha256(_canonical_json(pairs))
    manifest = dict(execution_manifest)
    manifest["predictions_sha256"] = predictions_sha256
    _validate_execution_manifest(manifest)
    obj = {
        "schema_version": _SCHEMA_VERSION,
        "predictions": pairs,
        "execution_manifest": manifest,
    }
    text = _canonical_json(obj)
    with open(path + ".json", "w", encoding="utf-8") as fh:
        fh.write(text)
    return _sha256(text)


def read_predictions(path: str) -> tuple[dict[tuple[str, str], np.ndarray], dict]:
    """Read + validate the prediction envelope, returning ``(preds, manifest)``.

    Parameters
    ----------
    path : str
        Input stem; ``".json"`` is appended.

    Returns
    -------
    tuple
        ``(predictions, execution_manifest)`` where ``predictions`` maps each
        canonical pair ID to its response-space vector and ``execution_manifest``
        is the structurally validated, predictions-bound manifest dict.

    Raises
    ------
    PayloadError
        On any structural, duplicate, digest-format or predictions-binding
        violation.
    """
    envelope_path = path + ".json"
    data = _read_regular_bytes(envelope_path, field="prediction envelope")
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadError(f"prediction envelope is not canonical UTF-8 JSON: {exc}") from exc
    if set(obj) != {"schema_version", "predictions", "execution_manifest"}:
        raise PayloadError("prediction file has an unexpected key set")
    if obj.get("schema_version") != _SCHEMA_VERSION:
        raise PayloadError("prediction file has an unexpected schema_version")
    if not isinstance(obj["predictions"], list):
        raise PayloadError("predictions must be a list")
    predictions: dict[tuple[str, str], np.ndarray] = {}
    for item in obj["predictions"]:
        if not isinstance(item, list) or len(item) != 2:
            raise PayloadError("each prediction record must be [pair, vector]")
        pair, vec = item
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(gene, str) and gene for gene in pair)
        ):
            raise PayloadError("prediction pair IDs must be two non-empty strings")
        pair_id = (pair[0], pair[1])
        if pair_id in predictions:
            raise PayloadError(f"duplicate prediction pair {pair_id!r}")
        predictions[pair_id] = np.asarray(vec, dtype=float)
    manifest = obj["execution_manifest"]
    _validate_execution_manifest(manifest)
    recomputed = _sha256(_canonical_json(obj["predictions"]))
    if manifest["predictions_sha256"] != recomputed:
        raise PayloadError("execution_manifest predictions_sha256 does not match predictions")
    return predictions, dict(manifest)


def _canonical_approved_root(path: str) -> str:
    """Return a canonical approved root, rejecting relative/symlinked paths."""
    if not isinstance(path, str) or not os.path.isabs(path) or path != os.path.normpath(path):
        raise PayloadError("approved artifacts root must be an absolute path in normalized form")
    resolved = os.path.realpath(path)
    if resolved != path:
        raise PayloadError("approved artifacts root must be canonical and non-symlinked")
    try:
        node = os.lstat(path)
    except OSError as exc:
        raise PayloadError(f"cannot stat approved artifacts root: {exc}") from exc
    if stat.S_ISLNK(node.st_mode) or not stat.S_ISDIR(node.st_mode):
        raise PayloadError("approved artifacts root must be a non-symlink directory")
    return path


def _path_is_within(path: str, root: str) -> bool:
    """Return whether canonical ``path`` is a strict descendant of ``root``."""
    try:
        return os.path.commonpath([root, path]) == root and path != root
    except ValueError:
        return False


def _build_worker_environment(
    base_env: Mapping[str, str],
    *,
    worker_identity_paths: Mapping[str, str] | None,
    identity_lock: ExecutionIdentityLock,
    approved_root: str,
    seed: int,
    worker_executable_path: str | None = None,
    worker_executable_sha256: str | None = None,
    payload_sha256: str | None = None,
) -> dict[str, str]:
    """Build a minimal, controller-verified execution environment for a worker.

    The environment is constructed from fixed controller constants instead of
    copying any ambient process variable. Consequently Python-path controls,
    dynamic-loader injection variables, scheduler routing, locale/temp changes,
    and unregistered numeric-runtime knobs cannot reach either the availability
    probe or the worker. When identity
    paths are configured, every file must be canonical, regular, non-symlinked,
    contained by the approved root, and byte-equal to the controller lock
    immediately before launch.  The worker independently repeats the hash checks,
    closing the controller-check-to-worker-open race.
    """
    del base_env  # ambient state is intentionally not part of the worker contract
    env = dict(_FIXED_WORKER_ENV)
    env["PYTHONHASHSEED"] = str(int(seed))
    if payload_sha256 is not None:
        if not _is_bare_sha256(payload_sha256):
            raise PayloadError("payload SHA-256 must be exact 64 lowercase hex")
        env[_WORKER_PAYLOAD_SHA_ENV] = payload_sha256
    if (worker_executable_path is None) != (worker_executable_sha256 is None):
        raise PayloadError("worker executable path and SHA-256 must be supplied together")
    if worker_executable_path is not None:
        if (
            not os.path.isabs(worker_executable_path)
            or worker_executable_path != os.path.normpath(worker_executable_path)
            or os.path.realpath(worker_executable_path) != worker_executable_path
            or not _is_bare_sha256(worker_executable_sha256)
        ):
            raise PayloadError("worker executable identity is not canonical")
        if _file_sha256_bare(worker_executable_path) != worker_executable_sha256:
            raise PayloadError("worker executable snapshot differs from controller identity")
        env[_WORKER_EXECUTABLE_PATH_ENV] = worker_executable_path
        env[_WORKER_EXECUTABLE_SHA_ENV] = worker_executable_sha256
        if worker_executable_path.endswith(".pyz"):
            # The trusted snapshot is the sole PYTHONPATH entry; no ambient path
            # survives the fixed environment construction above.
            env["PYTHONPATH"] = worker_executable_path
    if worker_identity_paths is None:
        return env
    if set(worker_identity_paths) != set(_WORKER_IDENTITY_PATH_ENV):
        required_fields = sorted(_WORKER_IDENTITY_PATH_ENV)
        raise PayloadError(f"worker_identity_paths must be exactly {required_fields}")

    root = _canonical_approved_root(approved_root)
    for identity_field, env_name in _WORKER_IDENTITY_PATH_ENV.items():
        raw_path = worker_identity_paths[identity_field]
        if (
            not isinstance(raw_path, str)
            or not os.path.isabs(raw_path)
            or raw_path != os.path.normpath(raw_path)
            or os.path.realpath(raw_path) != raw_path
            or not _path_is_within(raw_path, root)
        ):
            raise PayloadError(
                f"worker identity {identity_field} must be a canonical path under approved root"
            )
        observed = _file_sha256_bare(raw_path)
        digest_env, lock_field = _WORKER_IDENTITY_DIGEST_ENV[identity_field]
        expected = getattr(identity_lock, lock_field)
        if observed != expected:
            raise PayloadError(f"worker identity {identity_field} differs from controller lock")
        env[env_name] = raw_path
        env[digest_env] = expected
    env["ALIVE_WORKER_ADAPTER_VERSION"] = identity_lock.adapter_version
    return env


def _open_checkpoint_store(
    root_fd: int,
    *,
    create: bool = True,
) -> tuple[int, os.stat_result]:
    """Open/create the checkpoint store as a real directory below ``root_fd``."""
    created = False
    if create:
        try:
            os.mkdir(_CHECKPOINT_DIRNAME, mode=0o700, dir_fd=root_fd)
            created = True
        except FileExistsError:
            pass
        except OSError as exc:
            raise PayloadError(f"cannot create checkpoint store: {exc}") from exc
    if created:
        os.fsync(root_fd)
    try:
        before = os.stat(_CHECKPOINT_DIRNAME, dir_fd=root_fd, follow_symlinks=False)
    except OSError as exc:
        raise PayloadError(f"cannot stat checkpoint store: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise PayloadError("checkpoint store must be a real directory, not a symlink or file")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        store_fd = os.open(_CHECKPOINT_DIRNAME, flags, dir_fd=root_fd)
    except OSError as exc:
        raise PayloadError(f"cannot open checkpoint store: {exc}") from exc
    opened = os.fstat(store_fd)
    if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
        before.st_dev,
        before.st_ino,
    ):
        os.close(store_fd)
        raise PayloadError("checkpoint store changed between stat and open")
    return store_fd, opened


def _checkpoint_digest_at(store_fd: int, filename: str) -> str:
    """Hash an existing content-addressed node without following symlinks."""
    fd, before = _open_regular_at(store_fd, filename, field="durable checkpoint")
    try:
        if before.st_nlink != 1:
            raise PayloadError("durable checkpoint must not have external hard links")
        if before.st_mode & 0o222:
            raise PayloadError("durable checkpoint must be read-only")
        return _hash_open_fd(fd, before, field="durable checkpoint")
    finally:
        os.close(fd)


def _verify_durable_checkpoint_path(
    checkpoint_path: str,
    *,
    approved_root: str,
    checkpoint_sha256: str,
) -> None:
    """Re-verify a durable checkpoint's exact path, node kind and content."""
    root = _canonical_approved_root(approved_root)
    if not _is_bare_sha256(checkpoint_sha256):
        raise PayloadError("checkpoint_sha256 must be exact 64 lowercase hex")
    expected_name = f"{checkpoint_sha256}.pt"
    expected_path = os.path.join(root, _CHECKPOINT_DIRNAME, expected_name)
    if checkpoint_path != expected_path or os.path.realpath(checkpoint_path) != checkpoint_path:
        raise PayloadError("durable checkpoint path is not its canonical content address")
    root_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        root_fd = os.open(root, root_flags)
    except OSError as exc:
        raise PayloadError(f"cannot open approved artifacts root: {exc}") from exc
    store_fd: int | None = None
    try:
        store_fd, _ = _open_checkpoint_store(root_fd, create=False)
        if _checkpoint_digest_at(store_fd, expected_name) != checkpoint_sha256:
            raise PayloadError("durable checkpoint digest differs from its content address")
    finally:
        if store_fd is not None:
            os.close(store_fd)
        os.close(root_fd)


def _persist_content_addressed_checkpoint(
    checkpoint_path: str,
    *,
    approved_root: str,
    checkpoint_sha256: str,
) -> str:
    """Atomically install a verified checkpoint below the approved root.

    The worker sidecar is opened with ``O_NOFOLLOW`` and streamed into a temporary
    node in the destination directory while being hashed.  The fully written,
    read-only, fsynced node is then published with an atomic no-replace hard link;
    both file and directory entries are fsynced.  Existing content-addressed nodes
    are accepted only when they are ordinary single-link files with the exact
    expected digest.
    """
    if not _is_bare_sha256(checkpoint_sha256):
        raise PayloadError("checkpoint_sha256 must be exact 64 lowercase hex")
    root = _canonical_approved_root(approved_root)
    if not isinstance(checkpoint_path, str) or not os.path.isabs(checkpoint_path):
        raise PayloadError("worker checkpoint path must be absolute")

    root_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        root_fd = os.open(root, root_flags)
    except OSError as exc:
        raise PayloadError(f"cannot open approved artifacts root: {exc}") from exc
    store_fd: int | None = None
    source_fd: int | None = None
    temp_name: str | None = None
    try:
        root_stat = os.fstat(root_fd)
        store_fd, store_stat = _open_checkpoint_store(root_fd)
        source_fd, source_before = _open_regular_no_follow(
            checkpoint_path, field="worker checkpoint"
        )

        for _ in range(32):
            candidate = f".tmp-{os.getpid()}-{secrets.token_hex(12)}"
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            try:
                temp_fd = os.open(candidate, flags, 0o600, dir_fd=store_fd)
                temp_name = candidate
                break
            except FileExistsError:
                continue
            except OSError as exc:
                raise PayloadError(f"cannot create checkpoint staging file: {exc}") from exc
        else:
            raise PayloadError("cannot allocate a unique checkpoint staging file")

        observed = hashlib.sha256()
        try:
            while True:
                chunk = os.read(source_fd, 1 << 20)
                if not chunk:
                    break
                observed.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(temp_fd, view)
                    if written <= 0:
                        raise PayloadError("short write while staging checkpoint")
                    view = view[written:]
            if _stable_stat_tuple(os.fstat(source_fd)) != _stable_stat_tuple(source_before):
                raise PayloadError("worker checkpoint changed while being copied")
            if observed.hexdigest() != checkpoint_sha256:
                raise PayloadError("checkpoint bytes changed before durable installation")
            os.fchmod(temp_fd, 0o400)
            os.fsync(temp_fd)
        finally:
            os.close(temp_fd)

        destination_name = f"{checkpoint_sha256}.pt"
        try:
            os.link(
                temp_name,
                destination_name,
                src_dir_fd=store_fd,
                dst_dir_fd=store_fd,
                follow_symlinks=False,
            )
            os.fsync(store_fd)
        except FileExistsError:
            existing = _checkpoint_digest_at(store_fd, destination_name)
            if existing != checkpoint_sha256:
                raise PayloadError("content-addressed checkpoint path contains different bytes")
        except OSError as exc:
            raise PayloadError(f"cannot atomically publish durable checkpoint: {exc}") from exc

        os.unlink(temp_name, dir_fd=store_fd)
        temp_name = None
        os.fsync(store_fd)
        if _checkpoint_digest_at(store_fd, destination_name) != checkpoint_sha256:
            raise PayloadError("durable checkpoint failed post-publish verification")

        # Ensure the path we return still resolves to the exact opened root/store.
        current_root = os.stat(root, follow_symlinks=False)
        current_store = os.stat(_CHECKPOINT_DIRNAME, dir_fd=root_fd, follow_symlinks=False)
        if (current_root.st_dev, current_root.st_ino) != (root_stat.st_dev, root_stat.st_ino):
            raise PayloadError("approved artifacts root changed during checkpoint publication")
        if (current_store.st_dev, current_store.st_ino) != (
            store_stat.st_dev,
            store_stat.st_ino,
        ):
            raise PayloadError("checkpoint store changed during checkpoint publication")
        return os.path.join(root, _CHECKPOINT_DIRNAME, destination_name)
    finally:
        if temp_name is not None and store_fd is not None:
            try:
                os.unlink(temp_name, dir_fd=store_fd)
                os.fsync(store_fd)
            except FileNotFoundError:
                pass
        if source_fd is not None:
            os.close(source_fd)
        if store_fd is not None:
            os.close(store_fd)
        os.close(root_fd)


@dataclass
class SubprocessBaselineBackend:
    """Guarded deep-baseline backend that runs a worker under a locked-env python.

    Implements the seam contract (``is_available`` + ``predict``) from
    ``baselines_combo.BaselineAdapter``. Imports no gears/cpa itself.
    """

    name: str
    env_python: str
    worker_script: str
    import_name: str
    seed: int = 11
    _: KW_ONLY
    approved_artifacts_root: str
    expected_response_artifact_sha256: str
    execution_identity_lock: ExecutionIdentityLock
    worker_identity_paths: Mapping[str, str] | None = None
    expected_worker_sha256: str | None = None
    allow_local_approved_root_checkpoint_store: bool = False
    _available: bool | None = field(default=None, init=False, repr=False)
    _payload: dict | None = field(default=None, init=False, repr=False)
    _last_execution_manifest: dict | None = field(default=None, init=False, repr=False)
    _last_checkpoint_path: str | None = field(default=None, init=False, repr=False)

    def _trusted_worker_sha256(self) -> str:
        """Return and re-verify the out-of-band worker-script identity."""
        expected = self.expected_worker_sha256
        if expected is None:
            # Compatibility for directly constructed local/test backends. The
            # production assembler always supplies WorkerBlock.worker_script.sha256.
            expected = _file_sha256_bare(self.worker_script)
            self.expected_worker_sha256 = expected
        if not _is_bare_sha256(expected):
            raise PayloadError("expected_worker_sha256 must be exact 64 lowercase hex")
        if _file_sha256_bare(self.worker_script) != expected:
            raise PayloadError("worker script differs from its trusted identity")
        return expected

    def spawn(self, *, seed: int) -> SubprocessBaselineBackend:
        """Return a fresh, unconfigured backend with identical execution identity.

        D2 runs each ``(method, seed, fold)`` job on its own backend instance so
        the mutable ``_payload`` / ``_last_execution_manifest`` state cannot bleed
        across folds. This copies only the immutable execution identity — ``name``,
        the resolved executable / worker paths, the import name, and the
        keyword-only ``approved_artifacts_root`` / ``expected_response_artifact_sha256``
        / ``execution_identity_lock`` — sets the requested ``seed``, and leaves the
        new instance **unconfigured**: its ``init=False`` cache fields
        (``_available``, ``_payload``, ``_last_execution_manifest``) start at their
        ``None`` defaults. ``self`` is never mutated.

        Parameters
        ----------
        seed : int
            The seed the fresh backend serializes into its worker payload and
            binds into its provenance manifest.

        Returns
        -------
        SubprocessBaselineBackend
            A new, unconfigured backend sharing no mutable payload / manifest
            state with ``self``.
        """
        return SubprocessBaselineBackend(
            name=self.name,
            env_python=self.env_python,
            worker_script=self.worker_script,
            import_name=self.import_name,
            seed=int(seed),
            approved_artifacts_root=self.approved_artifacts_root,
            expected_response_artifact_sha256=self.expected_response_artifact_sha256,
            execution_identity_lock=self.execution_identity_lock,
            worker_identity_paths=(
                None if self.worker_identity_paths is None else dict(self.worker_identity_paths)
            ),
            expected_worker_sha256=self.expected_worker_sha256,
            allow_local_approved_root_checkpoint_store=(
                self.allow_local_approved_root_checkpoint_store
            ),
        )

    def configure_payload(self, payload: Mapping[str, object]) -> None:
        """Bind a validated fit-role payload before Phase-2a prediction."""
        candidate = dict(payload)
        _assert_no_sealed_reference(candidate)
        _validate_payload(
            candidate,
            expected_response_artifact_sha256=self.expected_response_artifact_sha256,
        )
        # Canonical JSON round-trip creates a detached deep snapshot. A shallow
        # ``dict(payload)`` would retain aliases to nested lists/blocks, allowing
        # callers to mutate an already-validated payload after configuration.
        snapshot = json.loads(_canonical_json(candidate))
        _validate_payload(
            snapshot,
            expected_response_artifact_sha256=self.expected_response_artifact_sha256,
        )
        self._payload = snapshot
        self._last_execution_manifest = None
        self._last_checkpoint_path = None

    @property
    def provenance_manifest(self) -> dict[str, object]:
        """Return the worker/payload identity bound into the Phase-2a model lock.

        Before any predict has run this carries the full frozen
        :class:`ExecutionIdentityLock`. After a successful controller-side
        verification it additionally carries the **entire** verified execution
        manifest (not merely a digest subset), so the ordered request,
        worker/config/resource/environment and adapter identities all enter the
        method lock. Scientific completion requires the post-predict form.
        """
        if self._payload is None:
            raise PayloadError(f"{self.name} backend has no fit-role payload assigned")
        worker = Path(self.worker_script)
        if not worker.is_file():
            raise PayloadError(f"{self.name} worker script does not exist: {str(worker)!r}")
        lock = self.execution_identity_lock
        manifest: dict[str, object] = {
            "name": self.name,
            "env_python": str(Path(self.env_python).resolve()),
            "worker_script": str(worker.resolve()),
            "worker_sha256": self._trusted_worker_sha256(),
            "import_name": self.import_name,
            "seed": int(self.seed),
            "payload_sha256": _sha256(_canonical_json(self._payload)),
            "execution_identity_lock": {
                "prediction_representation": lock.prediction_representation,
                "adapter_version": lock.adapter_version,
                "adapter_sha256": lock.adapter_sha256,
                "config_sha256": lock.config_sha256,
                "resource_sha256": lock.resource_sha256,
                "environment_lock_sha256": lock.environment_lock_sha256,
            },
        }
        if self._last_execution_manifest is not None:
            checkpoint_path = self._last_checkpoint_path
            expected_checkpoint_sha = self._last_execution_manifest["checkpoint_sha256"]
            if checkpoint_path is None:
                raise PayloadError("post-predict provenance lacks a durable checkpoint path")
            approved_root = _canonical_approved_root(self.approved_artifacts_root)
            _verify_durable_checkpoint_path(
                checkpoint_path,
                approved_root=approved_root,
                checkpoint_sha256=expected_checkpoint_sha,
            )
            manifest["execution_manifest"] = {
                key: self._last_execution_manifest[key] for key in sorted(EXECUTION_MANIFEST_KEYS)
            }
            manifest["payload_sha256"] = self._last_execution_manifest["payload_sha256"]
            manifest["durable_checkpoint_path"] = checkpoint_path
        return manifest

    @property
    def is_available(self) -> bool:
        if self._available is None:
            try:
                trusted_sha256 = self._trusted_worker_sha256()
                is_bundle = self.worker_script.endswith(".pyz")
                with tempfile.TemporaryDirectory() as raw_probe_dir:
                    probe_dir = os.path.realpath(raw_probe_dir)
                    snapshot = _snapshot_verified_worker_script(
                        self.worker_script,
                        os.path.join(
                            probe_dir,
                            "worker.snapshot.pyz" if is_bundle else "worker.snapshot.py",
                        ),
                        expected_sha256=trusted_sha256,
                        expected_method=self.name,
                        allow_fixture_stub=self.allow_local_approved_root_checkpoint_store,
                        allow_direct_py=self.allow_local_approved_root_checkpoint_store,
                    )
                    probe_env = _build_worker_environment(
                        os.environ,
                        worker_identity_paths=None,
                        identity_lock=self.execution_identity_lock,
                        approved_root=self.approved_artifacts_root,
                        seed=self.seed,
                        worker_executable_path=snapshot,
                        worker_executable_sha256=trusted_sha256,
                    )
                    if is_bundle:
                        # Import the identity helper from the one verified archive,
                        # independently re-hash that archive in the child, verify
                        # every loaded ALIVE origin, then import the real backend.
                        probe_code = (
                            "import importlib,sys;"
                            "from alive.compose.worker_identity import "
                            "load_verified_worker_executable,"
                            "require_loaded_alive_helpers_from_executable,"
                            "require_module_from_environment;"
                            "x=load_verified_worker_executable(require_argv_match=False);"
                            "m=importlib.import_module(sys.argv[1]) if sys.argv[1] else None;"
                            "require_module_from_environment(m,expected_name=sys.argv[1]) "
                            "if m is not None else None;"
                            "require_loaded_alive_helpers_from_executable(x)"
                        )
                        # The fixture reference bundle has no external backend.
                        bundle_method = _validated_worker_bundle_method(
                            snapshot,
                            expected_sha256=trusted_sha256,
                        )
                        backend_import = (
                            ""
                            if self.allow_local_approved_root_checkpoint_store
                            and bundle_method == "stub"
                            else self.import_name
                        )
                        command = [self.env_python, "-c", probe_code, backend_import]
                    else:
                        command = [
                            self.env_python,
                            "-c",
                            "import importlib,sys; importlib.import_module(sys.argv[1])",
                            self.import_name,
                        ]
                    r = subprocess.run(
                        command,
                        capture_output=True,
                        timeout=120,
                        env=probe_env,
                        cwd=probe_dir,
                    )
                self._available = r.returncode == 0
            except Exception:
                self._available = False
        return self._available

    def predict(
        self,
        context: object,
        pair_ids: list[tuple[str, str]],
        response_dim: int,
    ) -> dict[tuple[str, str], np.ndarray]:
        """Run the locked-env worker on the assigned fit-role payload.

        The fit-role ``_payload`` is assigned by the caller / Phase-2a wiring
        (never carrying a sealed role, token or path). This method scans the
        serialized payload for any sealed reference, writes it to a fresh temp
        work directory, invokes ``<env_python> <worker_script> --in <work_dir>
        --out <preds>``, and returns the parsed response-space delta.

        Parameters
        ----------
        context : object
            The frozen development-role context (validated by the adapter seam
            before this backend is touched); unused here beyond the seam guard.
        pair_ids : list of tuple of str
            The canonical pair IDs to predict.
        response_dim : int
            The required response dimension for every prediction vector.

        Returns
        -------
        dict
            Mapping from each requested canonical pair ID to a
            length-``response_dim`` prediction vector.

        Raises
        ------
        PayloadError
            If no fit-role payload has been assigned.
        ValueError
            If the serialized payload contains any sealed reference.
        BaselineUnavailable
            If the worker subprocess exits non-zero.
        """
        if self._payload is None:
            raise PayloadError(f"{self.name} backend has no fit-role payload assigned")
        # A failed re-invocation must never leave a stale successful manifest/path
        # visible as if it described the most recent predict attempt.
        self._last_execution_manifest = None
        self._last_checkpoint_path = None
        approved_root = _canonical_approved_root(self.approved_artifacts_root)
        if not self.allow_local_approved_root_checkpoint_store:
            raise PayloadError(
                "no registered durable checkpoint output is configured; refusing to write "
                "into the immutable approved-artifacts input root"
            )
        trusted_worker_sha256 = self._trusted_worker_sha256()
        payload = dict(self._payload)
        payload["pair_ids"] = [list(p) for p in pair_ids]
        payload["response_dim"] = int(response_dim)
        payload["seed"] = int(self.seed)
        _assert_no_sealed_reference(payload)  # fit-role-only guard on the payload
        with tempfile.TemporaryDirectory() as raw_work_dir:
            work_dir = os.path.realpath(raw_work_dir)
            payload_sha256 = write_payload(work_dir, payload)
            out = f"{work_dir}/preds"
            is_bundle = self.worker_script.endswith(".pyz")
            worker_snapshot = _snapshot_verified_worker_script(
                self.worker_script,
                os.path.join(
                    work_dir,
                    "worker.snapshot.pyz" if is_bundle else "worker.snapshot.py",
                ),
                expected_sha256=trusted_worker_sha256,
                expected_method=self.name,
                allow_fixture_stub=self.allow_local_approved_root_checkpoint_store,
                allow_direct_py=self.allow_local_approved_root_checkpoint_store,
            )
            worker_env = _build_worker_environment(
                os.environ,
                worker_identity_paths=self.worker_identity_paths,
                identity_lock=self.execution_identity_lock,
                approved_root=approved_root,
                seed=self.seed,
                worker_executable_path=worker_snapshot,
                worker_executable_sha256=trusted_worker_sha256,
                payload_sha256=payload_sha256,
            )
            r = subprocess.run(
                [
                    self.env_python,
                    worker_snapshot,
                    "--in",
                    work_dir,
                    "--out",
                    out,
                    "--approved-root",
                    approved_root,
                    "--prediction-representation",
                    self.execution_identity_lock.prediction_representation,
                ],
                capture_output=True,
                text=True,
                timeout=1800,
                env=worker_env,
                cwd=work_dir,
            )
            if r.returncode != 0:
                raise BaselineUnavailable(f"{self.name} worker failed: {r.stderr[-500:]}")
            preds, manifest = read_predictions(out)
            checkpoint_path = out + ".checkpoint"
            _verify_execution_manifest(
                manifest,
                payload=payload,
                requested_pair_ids=pair_ids,
                worker_script=worker_snapshot,
                checkpoint_path=checkpoint_path,
                identity_lock=self.execution_identity_lock,
                expected_worker_sha256=trusted_worker_sha256,
                expected_payload_sha256=payload_sha256,
            )
            durable_checkpoint = _persist_content_addressed_checkpoint(
                checkpoint_path,
                approved_root=approved_root,
                checkpoint_sha256=manifest["checkpoint_sha256"],
            )
            self._last_execution_manifest = manifest
            self._last_checkpoint_path = durable_checkpoint
            return preds
