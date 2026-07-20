"""Fail-closed evidence contract for the COMPOSE GEARS Probe A.

The actual GEARS fit runs only in the pinned pod environment. This verifier
reopens the prepared H5AD and validates checkpoint containers without loading
their pickle payloads, so evidence can be checked independently on a CPU host
before it is allowed to admit the approximation-bias measurement.
"""

from __future__ import annotations

import hashlib
import json
import math
import pickletools
import subprocess
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

import anndata as ad
import numpy as np
from scipy import sparse

from alive.compose.approximation_bias import (
    PROBE_A_OWNER_POLICY_PATH,
    PROBE_A_REGISTRATION_SCHEMA,
    PROBE_A_SCHEMA,
    PROBE_A_VERIFICATION_SCHEMA,
    ApproximationBiasValidationError,
    canonical_file_bytes,
    canonical_json,
    self_checksum,
    validate_probe_a_evidence,
    validate_probe_a_registration,
)
from alive.compose.fit_role import row_identity_sha256
from alive.provenance import sha256_bytes, sha256_file, sha256_json

REPORT_SCHEMA = "compose_gears_probe_a_report_v8"
RAW_SCHEMA = "compose_gears_probe_a_raw_measurements_v6"
REGISTRATION_SCHEMA = PROBE_A_REGISTRATION_SCHEMA
VERIFICATION_SCHEMA = PROBE_A_VERIFICATION_SCHEMA
NEGATIVE_VERIFICATION_SCHEMA = "compose_gears_probe_a_negative_verification_v1"
MANIFEST_SCHEMA = "compose_gears_probe_a_evidence_manifest_v7"
# The admission schema and its validation live exactly once, in the sole consumer
# gate ``approximation_bias.validate_probe_a_evidence``. Re-export the name and
# reuse that validator here so this producer cannot drift from the consumer.
ADMISSION_SCHEMA = PROBE_A_SCHEMA
PROTOCOL = "COMPOSE-K562-v1"

MANIFEST_PATH = "manifest.json"
REPORT_PATH = "probe_a.json"
REGISTRATION_PATH = "probe_a_registration.json"
ADMISSION_PATH = "probe_a_admission.json"
VERIFY_PATH = "verify.json"

_POST_MANIFEST_PATHS = frozenset({MANIFEST_PATH, ADMISSION_PATH, VERIFY_PATH})
_REPORT_KEYS = {
    "schema",
    "protocol",
    "status",
    "git_commit",
    "registration_sha256",
    "runtime_sha256",
    "input_manifest_sha256",
    "source_fingerprint_sha256",
    "input_scale",
    "determinism",
    "control_count",
    "output_scale",
    "output_bridge",
    "raw_samples",
    "self_checksum",
}
_REGISTRATION_KEYS = {
    "schema",
    "protocol",
    "git_commit",
    "owner_policy_sha256",
    "input_scale",
    "determinism",
    "control_count",
    "output_bridge",
    "self_checksum",
}
_BRIDGE_KEYS = {"representation", "verdict", "tolerance", "max_abs_error"}
_GATE_VERDICT_KEYS = {"determinism", "control_count", "output_bridge"}
_NEGATIVE_VERIFICATION_KEYS = {
    "schema",
    "protocol",
    "status",
    "git_commit",
    "registration_sha256",
    "report_sha256",
    "evidence_manifest_sha256",
    "verifier_code_sha256",
    "gate_verdicts",
    "output_bridge",
    "self_checksum",
}
_MANIFEST_ENTRY_KEYS = {"role", "path", "sha256", "bytes"}
_SINGLETON_ROLE_PATHS = {
    "commands": "commands.jsonl",
    "runtime": "runtime.json",
    "inputs": "inputs.json",
    "role_attestation": "role_attestation.json",
    "probe_a_registration": REGISTRATION_PATH,
    "probe_a_report": REPORT_PATH,
    "probe_a_source": "probe_a_source.txt",
    "probe_input_manifest": "probe_input_manifest.json",
    "probe_input_h5ad": "probe_input.h5ad",
}
_MULTI_ROLES = frozenset({"roster_receipt", "probe_a_checkpoint", "raw_sample", "log"})
_KNOWN_ROLES = frozenset(_SINGLETON_ROLE_PATHS) | _MULTI_ROLES

COMMAND_RECORD_SCHEMA = "compose_gears_probe_command_record_v1"
RUNTIME_SCHEMA = "compose_gears_probe_runtime_v2"
INPUTS_SCHEMA = "compose_gears_probe_inputs_v3"
ROLE_ATTESTATION_SCHEMA = "compose_gears_probe_role_attestation_v2"
ROSTER_RECEIPT_SCHEMA = "compose_gears_roster_receipt_v2"
PROBE_INPUT_MANIFEST_SCHEMA = "compose_gears_probe_input_manifest_v3"
PROBE_INPUT_ADATA_SCHEMA = "compose_gears_probe_input_v3"
PROBE_INPUT_TRANSFORM = "full_library_normalize_log1p_then_roster_subset"
PREPARATION_LOCK_PATH = "uv.lock"
GEARS_LOCK_PATH = "docs/activation-evidence/compose/requirements.gears_env.lock"
PROBE_MATRIX_DTYPE = "float32-le"
PROBE_MATRIX_FORMAT = "canonical_csr"
PROBE_INPUT_MANIFEST_KEYS = {
    "expression_scale",
    "fit_artifact_content_sha256",
    "full_var_order_sha256",
    "manifest_checksum",
    "matrix_dtype",
    "matrix_format",
    "matrix_logical_sha256",
    "n_cells",
    "n_genes",
    "normalization_target",
    "ordered_roster_sha256",
    "output_h5ad_sha256",
    "payload_sha256",
    "preparation_dependency_lock_sha256",
    "gears_dependency_lock_sha256",
    "probe_driver_code_sha256",
    "probe_runtime_fingerprint_sha256",
    "response_artifact_sha256",
    "role_contract",
    "role_counts",
    "roster_artifact_checksum",
    "roster_file_sha256",
    "roster_receipt_sha256",
    "row_identity_sha256",
    "selected_source_row_ids_sha256",
    "schema",
}

# These are the subcommands that the maintained CLI actually implements.  Probe-A
# measurement is admitted from its digest-bound raw artifact below; Probe B has a
# separate archive contract and must not gate Probe-A admission.
_REQUIRED_COMMANDS = frozenset(
    {
        "build-roster",
        "prepare-input",
        "verify-input",
        "build-probe-a-registration",
        "probe-a",
        "build-probe-a-report",
    }
)
_COMMAND_KEYS = {
    "schema",
    "command",
    "argv",
    "cwd",
    "env",
    "started_at_utc",
    "ended_at_utc",
    "exit_code",
    "primary_file_sha256",
    "runtime_fingerprint_sha256",
    "self_checksum",
}
_RUNTIME_KEYS = {
    "schema",
    "protocol",
    "git_commit",
    "pod_instance",
    "gpu_model",
    "gpu_uuid",
    "driver_version",
    "cuda_version",
    "cpu_model",
    "cpu_count",
    "ram_bytes",
    "image_digest",
    "python_version",
    "preparation_dependency_lock_sha256",
    "gears_dependency_lock_sha256",
    "gears_installed_packages_sha256",
    "runtime_fingerprint_sha256",
    "network_disabled",
    "self_checksum",
}
_INPUTS_KEYS = {
    "schema",
    "protocol",
    "git_commit",
    "source_sha256",
    "gene2go_manifest_sha256",
    "pair_manifest_sha256",
    "alias_artifact_sha256",
    "fit_role_artifact_sha256",
    "response_artifact_sha256",
    "roster_receipt_sha256",
    "roster_sha256",
    "preparation_dependency_lock_sha256",
    "gears_dependency_lock_sha256",
    "fit_role_counts",
    "probe_input_manifest_sha256",
    "probe_input_h5ad_sha256",
    "probe_row_identity_sha256",
    "ordered_control_row_identity_sha256",
    "self_checksum",
}
_ROLE_ATTESTATION_KEYS = {
    "schema",
    "protocol",
    "git_commit",
    "fit_role_counts",
    "sealed_pair_overlap_count",
    "sealed_row_read_count",
    "reader_spy",
    "self_checksum",
}
_ROSTER_RECEIPT_KEYS = {
    "alias_artifact_sha256",
    "candidate_artifact_sha256",
    "driver_code_sha256",
    "preparation_dependency_lock_sha256",
    "gears_dependency_lock_sha256",
    "fit_artifact_content_sha256",
    "gene2go_nodes_artifact_sha256",
    "generator_code_sha256",
    "manifest_checksum",
    "n_target",
    "ordered_roster_sha256",
    "payload_sha256",
    "report_file_sha256",
    "response_artifact_sha256",
    "runtime_fingerprint_sha256",
    "roster_artifact_checksum",
    "roster_file_sha256",
    "schema",
}
_FIT_ROLE_COUNT_KEYS = {"control", "singles", "combo_calibration"}
_ROLE_CONTRACT_KEYS = {
    "calibration_pair_ids",
    "combo_separator",
    "control_token",
    "sealed_pair_ids",
    "single_gene_ids",
}
_RAW_KEYS = {
    "schema",
    "producer",
    "input_before",
    "input_after",
    "determinism_runs",
    "ordered_control_row_ids",
    "control_predictions",
    "public_prediction",
    "bridge_prediction",
    "self_checksum",
}
_RAW_RUN_KEYS = {
    "run_index",
    "checkpoint_path",
    "checkpoint_sha256",
    "checkpoint_bytes",
    "checkpoint_format",
    "seed",
    "probe_input_h5ad_sha256",
    "query_sha256",
    "worker_code_sha256",
    "prediction",
}
_RAW_PRODUCER_KEYS = {
    "backend_distribution",
    "backend_version",
    "gears_dependency_lock_sha256",
    "gears_installed_packages_sha256",
    "input_scale_sha256",
    "normalization_target",
    "registration_sha256",
    "worker_code_sha256",
    "probe_driver_code_sha256",
    "probe_input_manifest_sha256",
    "probe_input_h5ad_sha256",
    "probe_row_identity_sha256",
    "ordered_control_row_identity_sha256",
    "roster_sha256",
    "query",
    "seed",
    "measurement_run_index",
}
_RAW_CONTROL_KEYS = {
    "count",
    "control_row_ids",
    "per_control_prediction",
    "public_prediction",
}
_MATRIX_IDENTITY_KEYS = {"canonical_dtype", "logical_csr_sha256", "nnz", "shape"}
_CONTROL_COUNTS = (1, 8, 300, 301, 400)
_NEAR_INTEGER_ATOL = 1e-6
#: Upper bound on the untrusted prepared-input H5AD before it is read into memory
#: so an oversized evidence file cannot OOM the CPU verifier (fail-closed; the
#: read + float64 CSR densify would otherwise be unbounded). Sized conservatively
#: below the 24 GB verification host: the legitimate ~70,987-cell roster-subset
#: input is ~1 GB, so a 4 GB cap (peak ~10 GB in memory) never false-rejects yet
#: keeps the host safe. Tune upward only if the real prepared input grows.
_H5AD_ENVELOPE_BYTES = 4_000_000_000


class ProbeAEvidenceError(ValueError):
    """Raised when Probe-A evidence cannot cross the promotion boundary."""


@dataclass(frozen=True)
class ProbeAAdmissionOutputs:
    """Receipt-first outputs; ``admission`` exists only for a passing probe.

    A scientifically valid negative result receives an immutable verifier
    receipt but can never produce an activation admission.
    """

    verification: dict
    verification_bytes: bytes
    verification_sha256: str
    admission: dict | None


def repository_lock_sha256(relative_path: str, *, repository_root: str | Path | None = None) -> str:
    """Return the SHA-256 of one committed dependency lock at its canonical path."""
    root = (
        Path(repository_root).resolve(strict=True)
        if repository_root is not None
        else Path(__file__).resolve().parents[3]
    )
    if relative_path not in {PREPARATION_LOCK_PATH, GEARS_LOCK_PATH}:
        raise ProbeAEvidenceError("dependency lock path is not part of the Probe-A contract")
    path = root / relative_path
    if path.is_symlink() or not path.is_file():
        raise ProbeAEvidenceError(f"dependency lock is missing or unsafe: {relative_path}")
    return sha256_file(path)


def assert_clean_approved_checkout(
    expected_git_commit: str,
    *,
    repository_root: str | Path | None = None,
) -> None:
    """Require the executing checkout to be the exact clean owner-approved commit.

    The check includes untracked files, replacement refs, and recursively dirty or
    uninitialized submodules. It intentionally runs immediately before every
    decision-bearing production/verification boundary rather than trusting a
    caller-supplied commit string.
    """
    expected = _git_commit(expected_git_commit, "expected Git commit")
    root = (
        Path(repository_root).resolve(strict=True)
        if repository_root is not None
        else Path(__file__).resolve().parents[3]
    )

    def git(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProbeAEvidenceError(f"cannot verify executing Git checkout: {exc}") from exc
        return result.stdout.strip()

    if git("rev-parse", "--show-toplevel") != str(root):
        raise ProbeAEvidenceError("Probe-A repository root is not the Git toplevel")
    if git("rev-parse", "HEAD") != expected:
        raise ProbeAEvidenceError("executing checkout does not match the approved Git commit")
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise ProbeAEvidenceError("executing checkout is dirty")
    if git("replace", "-l"):
        raise ProbeAEvidenceError("executing checkout has active Git replacement refs")
    submodules = git("submodule", "status", "--recursive")
    if any(line[:1] in {"-", "+", "U"} for line in submodules.splitlines() if line):
        raise ProbeAEvidenceError("executing checkout has unclean or uninitialized submodules")


def _sha(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ProbeAEvidenceError(f"{field} must be a lowercase SHA-256")
    return value


def _git_commit(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) not in {40, 64}
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ProbeAEvidenceError(f"{field} must be a full lowercase hexadecimal Git commit")
    return value


def _finite_nonnegative(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProbeAEvidenceError(f"{field} must be numeric")
    observed = float(value)
    if not math.isfinite(observed) or observed < 0:
        raise ProbeAEvidenceError(f"{field} must be finite and non-negative")
    return observed


def _finite(value: object, field: str) -> float:
    """Finite number of any sign (output-scale summary values may be negative)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProbeAEvidenceError(f"{field} must be numeric")
    observed = float(value)
    if not math.isfinite(observed):
        raise ProbeAEvidenceError(f"{field} must be finite")
    return observed


def _exact_keys(value: object, expected: set[str], field: str) -> Mapping:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ProbeAEvidenceError(f"{field} keys differ from the registered schema")
    return value


def _checksum(payload: Mapping, field: str) -> None:
    checksum = _sha(payload.get("self_checksum"), f"{field}.self_checksum")
    body = {key: value for key, value in payload.items() if key != "self_checksum"}
    if checksum != sha256_json(body):
        raise ProbeAEvidenceError(f"{field} self-checksum mismatch")


def _json_object_from_bytes(data: bytes, *, expected_sha256: str, label: str) -> dict:
    """Hash and parse one immutable byte snapshot; never authenticate a second read."""
    if not isinstance(data, bytes):
        raise ProbeAEvidenceError(f"{label} must be supplied as immutable bytes")
    expected = _sha(expected_sha256, f"{label} SHA-256")
    if sha256_bytes(data) != expected:
        raise ProbeAEvidenceError(f"{label} file SHA-256 mismatch")
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeAEvidenceError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProbeAEvidenceError(f"{label} must be a JSON object")
    try:
        canonical = canonical_file_bytes(value)
    except (TypeError, ValueError) as exc:
        raise ProbeAEvidenceError(f"{label} is not canonical finite JSON") from exc
    if data != canonical:
        raise ProbeAEvidenceError(f"{label} bytes are not canonical JSON with one trailing newline")
    return value


def _relative_file(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ProbeAEvidenceError("evidence path must be a non-empty string")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ProbeAEvidenceError("evidence path must be safe and relative")
    raw = root / rel
    if raw.is_symlink():
        raise ProbeAEvidenceError("evidence path must be a regular file, not a symlink")
    try:
        base = root.resolve(strict=True)
        candidate = raw.resolve(strict=True)
    except OSError as exc:
        raise ProbeAEvidenceError(f"evidence path is missing or unreadable: {relative}") from exc
    if not base.is_dir():
        raise ProbeAEvidenceError("evidence root must be a directory")
    if not candidate.is_relative_to(base) or not candidate.is_file():
        raise ProbeAEvidenceError("evidence path must be a regular file under evidence root")
    return candidate


def _manifest_inventory(root: Path) -> set[str]:
    """Return every regular evidence file except the three self/post outputs."""
    try:
        base = root.resolve(strict=True)
    except OSError as exc:
        raise ProbeAEvidenceError("evidence root is missing or unreadable") from exc
    if root.is_symlink() or not base.is_dir():
        raise ProbeAEvidenceError("evidence root must be a real directory, not a symlink")
    inventory: set[str] = set()
    try:
        descendants = sorted(base.rglob("*"))
    except OSError as exc:
        raise ProbeAEvidenceError("cannot enumerate the complete evidence tree") from exc
    for path in descendants:
        relative = path.relative_to(base).as_posix()
        if path.is_symlink():
            raise ProbeAEvidenceError(f"evidence tree contains symlink: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ProbeAEvidenceError(f"evidence tree contains a non-regular entry: {relative}")
        if relative not in _POST_MANIFEST_PATHS:
            inventory.add(relative)
    return inventory


def validate_registration(registration: Mapping, *, expected_git_commit: str) -> None:
    """Validate the owner-frozen decisions through the shared consumer contract."""
    try:
        validate_probe_a_registration(
            registration,
            expected_git_commit=expected_git_commit,
        )
    except ApproximationBiasValidationError as exc:
        raise ProbeAEvidenceError(str(exc)) from exc


def _finite_vector(value: object, field: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ProbeAEvidenceError(f"{field} must be a non-empty numeric vector")
    return [_finite(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _finite_matrix(value: object, field: str) -> list[list[float]]:
    if not isinstance(value, list) or not value:
        raise ProbeAEvidenceError(f"{field} must be a non-empty numeric matrix")
    rows = [_finite_vector(row, f"{field}[{index}]") for index, row in enumerate(value)]
    widths = {len(row) for row in rows}
    if len(widths) != 1:
        raise ProbeAEvidenceError(f"{field} must be rectangular")
    return rows


def _matrix_identity(value, field: str) -> dict[str, object]:
    """Independently derive the logical CSR identity used by the probe runner."""
    try:
        matrix = sparse.csr_matrix(value, dtype=np.float64, copy=True)
    except (TypeError, ValueError) as exc:
        raise ProbeAEvidenceError(f"{field} must be a two-dimensional numeric matrix") from exc
    matrix.sum_duplicates()
    matrix.sort_indices()
    matrix.eliminate_zeros()
    if matrix.ndim != 2 or not np.isfinite(matrix.data).all():
        raise ProbeAEvidenceError(f"{field} must be a finite two-dimensional matrix")
    digest = hashlib.sha256(b"alive-logical-csr-float64-v1\0")
    for array, dtype in (
        (np.asarray(matrix.shape, dtype="<u8"), "<u8"),
        (matrix.indptr, "<u8"),
        (matrix.indices, "<u8"),
        (matrix.data, "<f8"),
    ):
        canonical = np.asarray(array, dtype=dtype)
        view = memoryview(canonical).cast("B")
        for offset in range(0, len(view), 8 * 1024 * 1024):
            digest.update(view[offset : offset + 8 * 1024 * 1024])
    return {
        "canonical_dtype": "float64-le",
        "logical_csr_sha256": digest.hexdigest(),
        "nnz": int(matrix.nnz),
        "shape": [int(matrix.shape[0]), int(matrix.shape[1])],
    }


def _input_scale_sha256(normalization_target: float) -> str:
    return sha256_json(
        {
            "normalization_target": normalization_target,
            "transform": PROBE_INPUT_TRANSFORM,
        }
    )


def _validate_matrix_identity(value: object, field: str) -> dict[str, object]:
    obj = _exact_keys(value, _MATRIX_IDENTITY_KEYS, field)
    if obj["canonical_dtype"] != "float64-le":
        raise ProbeAEvidenceError(f"{field} canonical dtype mismatch")
    _sha(obj["logical_csr_sha256"], f"{field}.logical_csr_sha256")
    _positive_int(obj["nnz"], f"{field}.nnz", allow_zero=True)
    shape = obj["shape"]
    if not isinstance(shape, list) or len(shape) != 2:
        raise ProbeAEvidenceError(f"{field}.shape must have exactly two dimensions")
    for index, dimension in enumerate(shape):
        _positive_int(dimension, f"{field}.shape[{index}]")
    if obj["nnz"] > shape[0] * shape[1]:
        raise ProbeAEvidenceError(f"{field}.nnz exceeds its logical shape")
    return dict(obj)


def _max_abs_error(left: list[float], right: list[float], field: str) -> float:
    if len(left) != len(right):
        raise ProbeAEvidenceError(f"{field} vectors must have identical lengths")
    return max(abs(a - b) for a, b in zip(left, right, strict=True))


def _ordered_row_ids(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ProbeAEvidenceError(f"{field} must be a non-empty ordered string list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ProbeAEvidenceError(f"{field} must contain only non-empty strings")
    if len(set(value)) != len(value):
        raise ProbeAEvidenceError(f"{field} must not contain duplicate row identities")
    return list(value)


def _column_mean(rows: list[list[float]], field: str) -> list[float]:
    if not rows:
        raise ProbeAEvidenceError(f"{field} cannot be empty")
    width = len(rows[0])
    if width == 0 or any(len(row) != width for row in rows):
        raise ProbeAEvidenceError(f"{field} must be a non-empty rectangular matrix")
    return [sum(row[column] for row in rows) / len(rows) for column in range(width)]


def _require_close(observed: object, expected: float, field: str) -> None:
    value = _finite(observed, field)
    if not math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-15):
        raise ProbeAEvidenceError(f"{field} is inconsistent with the raw measurements")


def _validate_pytorch_checkpoint(path: Path, *, expected_bytes: int, field: str) -> set[str]:
    """Validate the safe, load-free envelope emitted by ``torch.save``.

    Loading an untrusted pickle would execute code, so admission deliberately
    validates the pinned PyTorch ZIP container and its complete CRCs without
    deserializing ``data.pkl``.
    """
    if path.stat().st_size != expected_bytes:
        raise ProbeAEvidenceError(f"{field} byte count differs from the archived file")
    if not zipfile.is_zipfile(path):
        raise ProbeAEvidenceError(f"{field} is not a PyTorch ZIP checkpoint")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if not infos or len(names) != len(set(names)):
                raise ProbeAEvidenceError(f"{field} has an invalid ZIP member roster")
            for info in infos:
                member = Path(info.filename)
                if member.is_absolute() or ".." in member.parts or info.flag_bits & 0x1:
                    raise ProbeAEvidenceError(f"{field} has an unsafe ZIP member")
                if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ProbeAEvidenceError(f"{field} contains a symbolic link")
            suffixes = {"data.pkl", "byteorder", "version", ".data/serialization_id"}
            members_by_suffix: dict[str, zipfile.ZipInfo] = {}
            for suffix in suffixes:
                matches = [info for info in infos if info.filename.endswith(f"/{suffix}")]
                if len(matches) != 1:
                    raise ProbeAEvidenceError(
                        f"{field} requires exactly one PyTorch member {suffix}"
                    )
                members_by_suffix[suffix] = matches[0]
            if not any("/data/" in name and not name.endswith("/") for name in names):
                raise ProbeAEvidenceError(f"{field} has no tensor-storage members")
            if sum(info.file_size for info in infos) > 20_000_000_000:
                raise ProbeAEvidenceError(f"{field} exceeds the checkpoint envelope bound")
            if archive.testzip() is not None:
                raise ProbeAEvidenceError(f"{field} failed ZIP CRC validation")
            pickle_info = members_by_suffix["data.pkl"]
            if pickle_info.file_size > 64 * 1024 * 1024:
                raise ProbeAEvidenceError(f"{field} metadata pickle exceeds the envelope bound")
            pickle_data = archive.read(pickle_info)
            strings = {
                arg
                for _opcode, arg, _position in pickletools.genops(pickle_data)
                if isinstance(arg, str)
            }
    except (OSError, zipfile.BadZipFile) as exc:
        raise ProbeAEvidenceError(f"cannot validate {field}: {exc}") from exc
    except ValueError as exc:
        raise ProbeAEvidenceError(f"{field} has invalid pickle metadata: {exc}") from exc
    return strings


def _load_probe_a_raw(root: Path, sample: Mapping) -> dict:
    entry = _exact_keys(sample, {"path", "sha256"}, "raw sample")
    path = _relative_file(root, entry["path"])
    expected_sha = _sha(entry["sha256"], "raw sample SHA-256")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ProbeAEvidenceError(f"cannot read Probe-A raw measurements: {exc}") from exc
    if sha256_bytes(data) != expected_sha:
        raise ProbeAEvidenceError("Probe-A raw sample SHA-256 mismatch")
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeAEvidenceError(f"cannot parse Probe-A raw measurements: {exc}") from exc
    obj = _exact_keys(payload, _RAW_KEYS, "Probe-A raw measurements")
    try:
        canonical = _canonical_file_bytes(obj)
    except (TypeError, ValueError) as exc:
        raise ProbeAEvidenceError("Probe-A raw measurements are not canonical finite JSON") from exc
    if data != canonical:
        raise ProbeAEvidenceError("Probe-A raw measurements are not canonical JSON")
    _checksum(obj, "Probe-A raw measurements")
    if obj["schema"] != RAW_SCHEMA:
        raise ProbeAEvidenceError("Probe-A raw-measurement schema mismatch")

    producer = _exact_keys(obj["producer"], _RAW_PRODUCER_KEYS, "raw.producer")
    if producer["backend_distribution"] != "cell-gears" or producer["backend_version"] != "0.1.2":
        raise ProbeAEvidenceError("Probe-A raw producer is not the pinned GEARS backend")
    for field in (
        "gears_dependency_lock_sha256",
        "gears_installed_packages_sha256",
        "input_scale_sha256",
        "registration_sha256",
        "worker_code_sha256",
        "probe_driver_code_sha256",
        "probe_input_manifest_sha256",
        "probe_input_h5ad_sha256",
        "probe_row_identity_sha256",
        "ordered_control_row_identity_sha256",
        "roster_sha256",
    ):
        _sha(producer[field], f"raw.producer.{field}")
    normalization_target = _finite_nonnegative(
        producer["normalization_target"], "raw.producer.normalization_target"
    )
    if normalization_target <= 0:
        raise ProbeAEvidenceError("raw producer normalization target must be positive")
    if producer["input_scale_sha256"] != _input_scale_sha256(normalization_target):
        raise ProbeAEvidenceError("raw producer input-scale identity is inconsistent")
    query = producer["query"]
    if (
        not isinstance(query, list)
        or len(query) != 2
        or any(not isinstance(gene, str) or not gene for gene in query)
        or query[0] >= query[1]
    ):
        raise ProbeAEvidenceError("raw.producer.query must be one canonical gene pair")
    seed = _positive_int(producer["seed"], "raw.producer.seed", allow_zero=True)
    measurement_run_index = _positive_int(
        producer["measurement_run_index"], "raw.producer.measurement_run_index"
    )
    if measurement_run_index != 1:
        raise ProbeAEvidenceError("Probe-A measurements must originate from determinism run 1")

    input_before = _validate_matrix_identity(obj["input_before"], "raw.input_before")
    input_after = _validate_matrix_identity(obj["input_after"], "raw.input_after")
    if input_before["shape"] != input_after["shape"]:
        raise ProbeAEvidenceError("Probe-A input matrices have different shapes")

    runs = obj["determinism_runs"]
    if not isinstance(runs, list) or len(runs) != 2:
        raise ProbeAEvidenceError("Probe-A raw determinism measurements require exactly two runs")
    checkpoints: list[str] = []
    checkpoint_files: list[tuple[str, str]] = []
    checkpoint_metadata_strings: list[set[str]] = []
    run_predictions: list[list[float]] = []
    for index, raw_run in enumerate(runs):
        run = _exact_keys(raw_run, _RAW_RUN_KEYS, f"raw determinism run {index}")
        if run["run_index"] != index + 1:
            raise ProbeAEvidenceError("Probe-A determinism run indexes must be exactly [1, 2]")
        checkpoint_path = run["checkpoint_path"]
        checkpoint_file = _relative_file(root, checkpoint_path)
        checkpoint_sha = _sha(run["checkpoint_sha256"], f"raw run {index} checkpoint")
        if sha256_file(checkpoint_file) != checkpoint_sha:
            raise ProbeAEvidenceError(
                f"raw run {index} checkpoint SHA-256 differs from the archived file"
            )
        checkpoint_bytes = _positive_int(
            run["checkpoint_bytes"], f"raw run {index} checkpoint_bytes"
        )
        if run["checkpoint_format"] != "pytorch_zip_v1":
            raise ProbeAEvidenceError("Probe-A checkpoint format is not registered")
        metadata_strings = _validate_pytorch_checkpoint(
            checkpoint_file,
            expected_bytes=checkpoint_bytes,
            field=f"raw run {index} checkpoint",
        )
        if (
            run["seed"] != seed
            or run["probe_input_h5ad_sha256"] != producer["probe_input_h5ad_sha256"]
            or run["query_sha256"] != sha256_json(query)
            or run["worker_code_sha256"] != producer["worker_code_sha256"]
        ):
            raise ProbeAEvidenceError(
                "Probe-A determinism run is not bound to its producer/input/query/seed"
            )
        required_checkpoint_strings = {
            "compose_gears_trained_model_v1",
            "cell-gears",
            "0.1.2",
            PROBE_INPUT_TRANSFORM,
            "PROBE_ONLY_DECISION_MEASUREMENT",
            "probe_a",
            "model_state_dict",
            producer["input_scale_sha256"],
            producer["gears_dependency_lock_sha256"],
            producer["gears_installed_packages_sha256"],
            producer["probe_input_h5ad_sha256"],
            producer["registration_sha256"],
            run["query_sha256"],
            producer["worker_code_sha256"],
        }
        if not required_checkpoint_strings <= metadata_strings:
            raise ProbeAEvidenceError(
                "Probe-A checkpoint metadata is not bound to the backend/input/query/worker"
            )
        checkpoints.append(checkpoint_sha)
        checkpoint_files.append((checkpoint_path, checkpoint_sha))
        checkpoint_metadata_strings.append(metadata_strings)
        run_predictions.append(
            _finite_vector(run["prediction"], f"raw determinism run {index} prediction")
        )
    det_error = _max_abs_error(
        run_predictions[0], run_predictions[1], "raw determinism predictions"
    )

    ordered_control_row_ids = _ordered_row_ids(
        obj["ordered_control_row_ids"], "raw.ordered_control_row_ids"
    )
    if len(ordered_control_row_ids) < max(_CONTROL_COUNTS):
        raise ProbeAEvidenceError(
            "Probe-A raw measurements require at least 400 ordered control-row identities"
        )
    if sha256_json(ordered_control_row_ids) != producer["ordered_control_row_identity_sha256"]:
        raise ProbeAEvidenceError("Probe-A ordered control identity differs from its producer pin")

    raw_controls = obj["control_predictions"]
    if not isinstance(raw_controls, list) or len(raw_controls) != 5:
        raise ProbeAEvidenceError("Probe-A raw control-count measurements are incomplete")
    controls: dict[int, list[float]] = {}
    reconstructed_controls: dict[int, list[float]] = {}
    control_order: list[int] = []
    for index, raw_control in enumerate(raw_controls):
        control = _exact_keys(raw_control, _RAW_CONTROL_KEYS, f"raw control prediction {index}")
        count = _positive_int(control["count"], f"raw control prediction {index}.count")
        if count in controls:
            raise ProbeAEvidenceError("Probe-A raw control-count roster contains duplicates")
        control_order.append(count)
        row_ids = _ordered_row_ids(
            control["control_row_ids"], f"raw control prediction {index}.control_row_ids"
        )
        if len(row_ids) != count or row_ids != ordered_control_row_ids[:count]:
            raise ProbeAEvidenceError(
                "Probe-A control rows must be the exact prefix of the frozen ordered control roster"
            )
        per_control = _finite_matrix(
            control["per_control_prediction"],
            f"raw control prediction {index}.per_control_prediction",
        )
        if len(per_control) != count:
            raise ProbeAEvidenceError(
                "Probe-A per-control prediction count differs from its ordered control prefix"
            )
        public_prediction = _finite_vector(
            control["public_prediction"],
            f"raw control prediction {index}.public_prediction",
        )
        reconstructed = _column_mean(
            per_control[: min(count, 300)],
            f"raw control prediction {index}.first_300_reconstruction",
        )
        if len(public_prediction) != len(reconstructed):
            raise ProbeAEvidenceError(
                "Probe-A public and per-control reconstructed predictions differ in width"
            )
        controls[count] = public_prediction
        reconstructed_controls[count] = reconstructed
    widths = {len(prediction) for prediction in controls.values()}
    if len(widths) != 1:
        raise ProbeAEvidenceError("Probe-A raw control predictions have different lengths")
    if control_order != list(_CONTROL_COUNTS):
        raise ProbeAEvidenceError("Probe-A raw control-count roster/order is not registered")
    reconstruction_errors = [
        _max_abs_error(
            controls[count],
            reconstructed_controls[count],
            f"raw controls {count} public versus per-control reconstruction",
        )
        for count in _CONTROL_COUNTS
    ]
    cap_errors = [
        _max_abs_error(controls[300], controls[count], f"raw controls 300 versus {count}")
        for count in (301, 400)
    ]
    cap_error = max([*reconstruction_errors, *cap_errors])

    public = _finite_vector(obj["public_prediction"], "raw.public_prediction")
    bridge = _finite_vector(obj["bridge_prediction"], "raw.bridge_prediction")
    if public != controls[400] or public != run_predictions[measurement_run_index - 1]:
        raise ProbeAEvidenceError(
            "Probe-A public measurement is not the 400-control output from determinism run 1"
        )
    if bridge != reconstructed_controls[400]:
        raise ProbeAEvidenceError(
            "Probe-A bridge is not the direct first-300 reconstruction from the same run"
        )
    bridge_error = _max_abs_error(public, bridge, "raw public/bridge predictions")
    ordered = sorted(public)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0
    return {
        "producer": dict(producer),
        "input_before": input_before,
        "input_after": input_after,
        "checkpoints": checkpoints,
        "checkpoint_files": checkpoint_files,
        "checkpoint_metadata_strings": checkpoint_metadata_strings,
        "run_predictions": run_predictions,
        "det_error": det_error,
        "control_order": control_order,
        "ordered_control_row_ids": ordered_control_row_ids,
        "controls": controls,
        "reconstructed_controls": reconstructed_controls,
        "cap_error": cap_error,
        "public": public,
        "bridge_error": bridge_error,
        "output_scale": {
            "minimum": min(public),
            "median": median,
            "maximum": max(public),
            "negative_fraction": sum(value < 0 for value in public) / len(public),
            "near_integer_fraction": sum(
                abs(value - round(value)) <= _NEAR_INTEGER_ATOL for value in public
            )
            / len(public),
        },
    }


def validate_probe_a_raw_artifact(
    *, evidence_root: str | Path, relative_path: str, expected_sha256: str
) -> None:
    """Validate one raw publication and every checkpoint it references."""
    _load_probe_a_raw(
        Path(evidence_root),
        {"path": relative_path, "sha256": expected_sha256},
    )


def build_probe_a_report(
    *,
    evidence_root: str | Path,
    raw_sample_path: str,
    raw_sample_sha256: str,
    registration: Mapping,
    registration_sha256: str,
    expected_git_commit: str,
    runtime_sha256: str,
    inputs_sha256: str,
    source_fingerprint_sha256: str,
) -> dict[str, object]:
    """Derive the complete Probe-A report from validated raw measurements.

    No aggregate or verdict is accepted from the caller. Every value below is
    recomputed from the raw artifact and compared with the owner-frozen
    registration by :func:`validate_probe_a_report` before publication.
    """
    validate_registration(registration, expected_git_commit=expected_git_commit)
    raw = _load_probe_a_raw(
        Path(evidence_root),
        {"path": raw_sample_path, "sha256": raw_sample_sha256},
    )
    producer = raw["producer"]
    det_tolerance = float(registration["determinism"]["max_abs_error_tolerance"])
    control_tolerance = float(registration["control_count"]["first_300_max_abs_error_tolerance"])
    bridge_tolerance = float(registration["output_bridge"]["max_abs_error_tolerance"])
    checkpoint_sha256 = list(raw["checkpoints"])
    prediction_sha256 = [sha256_json(value) for value in raw["run_predictions"]]
    determinism_passed = (
        raw["det_error"] <= det_tolerance
        and checkpoint_sha256[0] == checkpoint_sha256[1]
        and prediction_sha256[0] == prediction_sha256[1]
    )
    control_count_passed = raw["cap_error"] <= control_tolerance
    output_bridge_passed = raw["bridge_error"] <= bridge_tolerance
    status = (
        "pass" if determinism_passed and control_count_passed and output_bridge_passed else "failed"
    )
    body = {
        "schema": REPORT_SCHEMA,
        "protocol": PROTOCOL,
        "status": status,
        "git_commit": _git_commit(expected_git_commit, "expected Git commit"),
        "registration_sha256": _sha(registration_sha256, "registration_sha256"),
        "runtime_sha256": _sha(runtime_sha256, "runtime_sha256"),
        "input_manifest_sha256": _sha(inputs_sha256, "inputs_sha256"),
        "source_fingerprint_sha256": _sha(source_fingerprint_sha256, "source_fingerprint_sha256"),
        "input_scale": {
            "before_sha256": sha256_json(raw["input_before"]),
            "after_sha256": sha256_json(raw["input_after"]),
            "exact_equal": raw["input_before"] == raw["input_after"],
            "normalization_target": producer["normalization_target"],
            "transform": PROBE_INPUT_TRANSFORM,
        },
        "determinism": {
            "checkpoint_sha256": checkpoint_sha256,
            "prediction_sha256": prediction_sha256,
            "max_abs_error": raw["det_error"],
            "tolerance": det_tolerance,
            "verdict": "pass" if determinism_passed else "fail",
        },
        "control_count": {
            "counts": list(raw["control_order"]),
            "prediction_sha256": [
                sha256_json(raw["controls"][count]) for count in raw["control_order"]
            ],
            "first_300_max_abs_error": raw["cap_error"],
            "tolerance": control_tolerance,
            "verdict": "pass" if control_count_passed else "fail",
        },
        "output_scale": dict(raw["output_scale"]),
        "output_bridge": {
            "representation": registration["output_bridge"]["representation"],
            "verdict": "pass" if output_bridge_passed else "fail",
            "tolerance": bridge_tolerance,
            "max_abs_error": raw["bridge_error"],
        },
        "raw_samples": [
            {"path": raw_sample_path, "sha256": _sha(raw_sample_sha256, "raw_sample_sha256")}
        ],
    }
    report = {**body, "self_checksum": sha256_json(body)}
    validate_probe_a_report(
        report,
        registration=registration,
        registration_sha256=registration_sha256,
        evidence_root=evidence_root,
        expected_git_commit=expected_git_commit,
    )
    return report


def build_evidence_manifest(
    *, evidence_root: str | Path, expected_git_commit: str
) -> dict[str, object]:
    """Build and self-validate the exhaustive pre-admission evidence manifest."""
    root = Path(evidence_root)
    inventory = _manifest_inventory(root)
    singleton_by_path = {path: role for role, path in _SINGLETON_ROLE_PATHS.items()}
    entries: list[dict[str, object]] = []
    for relative in sorted(inventory):
        path = _relative_file(root, relative)
        role = singleton_by_path.get(relative)
        parts = Path(relative).parts
        if role is None and parts and parts[0] == "roster_receipts":
            role = "roster_receipt"
        elif role is None and parts and parts[0] == "checkpoints" and path.suffix == ".pt":
            role = "probe_a_checkpoint"
        elif role is None and parts and parts[0] == "logs":
            role = "log"
        elif role is None and path.suffix == ".json":
            try:
                candidate = json.loads(path.read_bytes())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProbeAEvidenceError(
                    f"cannot classify evidence file {relative}: {exc}"
                ) from exc
            if isinstance(candidate, Mapping) and candidate.get("schema") == RAW_SCHEMA:
                role = "raw_sample"
        if role is None:
            raise ProbeAEvidenceError(
                f"cannot classify evidence file into a manifest role: {relative}"
            )
        entries.append(
            {
                "role": role,
                "path": relative,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    body = {
        "schema": MANIFEST_SCHEMA,
        "protocol": PROTOCOL,
        "git_commit": _git_commit(expected_git_commit, "expected Git commit"),
        "files": entries,
    }
    manifest = {**body, "manifest_checksum": sha256_json(body)}
    validate_evidence_manifest(
        manifest,
        evidence_root=root,
        expected_git_commit=expected_git_commit,
    )
    return manifest


def validate_probe_a_report(
    report: Mapping,
    *,
    registration: Mapping,
    registration_sha256: str,
    evidence_root: str | Path,
    expected_git_commit: str,
) -> None:
    """Validate a complete Probe-A report against frozen decisions and raw samples."""
    validate_registration(registration, expected_git_commit=expected_git_commit)
    registered_sha = _sha(registration_sha256, "registration_sha256")
    _exact_keys(report, _REPORT_KEYS, "Probe-A report")
    _checksum(report, "Probe-A report")
    if report["schema"] != REPORT_SCHEMA or report["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("Probe-A report identity mismatch")
    if report["status"] not in {"pass", "failed"}:
        raise ProbeAEvidenceError("Probe-A report status must be 'pass' or 'failed'")
    commit = _git_commit(report["git_commit"], "Probe-A report git_commit")
    if commit != _git_commit(expected_git_commit, "expected Git commit"):
        raise ProbeAEvidenceError("Probe-A Git commit differs from the approved commit")
    if _sha(report["registration_sha256"], "report.registration_sha256") != registered_sha:
        raise ProbeAEvidenceError("Probe-A report is not bound to the approved registration")
    for field in ("runtime_sha256", "input_manifest_sha256", "source_fingerprint_sha256"):
        _sha(report[field], field)

    samples = report["raw_samples"]
    if not isinstance(samples, list) or len(samples) != 1:
        raise ProbeAEvidenceError("Probe-A requires exactly one complete raw-measurement artifact")
    raw = _load_probe_a_raw(Path(evidence_root), samples[0])
    if raw["producer"]["registration_sha256"] != registered_sha:
        raise ProbeAEvidenceError("Probe-A raw measurements are not bound to preregistration")

    registered_input = registration["input_scale"]
    input_scale = _exact_keys(
        report["input_scale"],
        {"before_sha256", "after_sha256", "exact_equal", "normalization_target", "transform"},
        "input_scale",
    )
    before_sha = _sha(input_scale["before_sha256"], "input_scale.before_sha256")
    after_sha = _sha(input_scale["after_sha256"], "input_scale.after_sha256")
    if before_sha != sha256_json(raw["input_before"]) or after_sha != sha256_json(
        raw["input_after"]
    ):
        raise ProbeAEvidenceError("Probe-A input-scale digests disagree with raw matrices")
    if (
        input_scale["exact_equal"] is not True
        or raw["input_before"] != raw["input_after"]
        or input_scale["before_sha256"] != input_scale["after_sha256"]
    ):
        raise ProbeAEvidenceError("GEARS changed the registered probe input scale")
    normalization_target = _finite_nonnegative(
        input_scale["normalization_target"], "normalization_target"
    )
    if (
        normalization_target != float(registered_input["normalization_target"])
        or normalization_target != raw["producer"]["normalization_target"]
        or input_scale["transform"] != registered_input["transform"]
        or input_scale["transform"] != PROBE_INPUT_TRANSFORM
    ):
        raise ProbeAEvidenceError("Probe-A input scale differs from preregistration")

    registered_determinism = registration["determinism"]
    determinism = _exact_keys(
        report["determinism"],
        {"checkpoint_sha256", "prediction_sha256", "max_abs_error", "tolerance", "verdict"},
        "determinism",
    )
    for field in ("checkpoint_sha256", "prediction_sha256"):
        values = determinism[field]
        if not isinstance(values, list) or len(values) != 2:
            raise ProbeAEvidenceError(f"determinism.{field} must contain exactly two runs")
        for value in values:
            _sha(value, f"determinism.{field}")
    if determinism["checkpoint_sha256"] != raw["checkpoints"] or determinism[
        "prediction_sha256"
    ] != [sha256_json(value) for value in raw["run_predictions"]]:
        raise ProbeAEvidenceError("Probe-A determinism identities disagree with raw measurements")
    det_error = _finite_nonnegative(determinism["max_abs_error"], "determinism.max_abs_error")
    _require_close(det_error, raw["det_error"], "determinism.max_abs_error")
    det_tol = _finite_nonnegative(determinism["tolerance"], "determinism.tolerance")
    if det_tol != float(registered_determinism["max_abs_error_tolerance"]):
        raise ProbeAEvidenceError("Probe-A determinism tolerance differs from preregistration")
    determinism_passed = (
        determinism["checkpoint_sha256"][0] == determinism["checkpoint_sha256"][1]
        and determinism["prediction_sha256"][0] == determinism["prediction_sha256"][1]
        and det_error <= det_tol
    )
    expected_determinism_verdict = "pass" if determinism_passed else "fail"
    if determinism["verdict"] != expected_determinism_verdict:
        raise ProbeAEvidenceError("Probe-A determinism verdict disagrees with raw measurements")

    registered_control = registration["control_count"]
    control = _exact_keys(
        report["control_count"],
        {"counts", "prediction_sha256", "first_300_max_abs_error", "tolerance", "verdict"},
        "control_count",
    )
    if control["counts"] != registered_control["counts"]:
        raise ProbeAEvidenceError("Probe-A control-count roster differs from preregistration")
    if control["counts"] != raw["control_order"]:
        raise ProbeAEvidenceError("Probe-A control-count roster differs from raw measurements")
    if not isinstance(control["prediction_sha256"], list) or len(control["prediction_sha256"]) != 5:
        raise ProbeAEvidenceError("Probe-A control-count predictions are incomplete")
    for value in control["prediction_sha256"]:
        _sha(value, "control_count.prediction_sha256")
    if control["prediction_sha256"] != [
        sha256_json(raw["controls"][count]) for count in raw["control_order"]
    ]:
        raise ProbeAEvidenceError(
            "Probe-A control prediction identities disagree with raw measurements"
        )
    cap_error = _finite_nonnegative(control["first_300_max_abs_error"], "first_300_max_abs_error")
    _require_close(cap_error, raw["cap_error"], "control_count.first_300_max_abs_error")
    cap_tol = _finite_nonnegative(control["tolerance"], "control_count.tolerance")
    if cap_tol != float(registered_control["first_300_max_abs_error_tolerance"]):
        raise ProbeAEvidenceError("Probe-A control-count tolerance differs from preregistration")
    control_count_passed = cap_error <= cap_tol
    expected_control_verdict = "pass" if control_count_passed else "fail"
    if control["verdict"] != expected_control_verdict:
        raise ProbeAEvidenceError("Probe-A control-count verdict disagrees with raw measurements")

    output_scale = _exact_keys(
        report["output_scale"],
        {"minimum", "median", "maximum", "negative_fraction", "near_integer_fraction"},
        "output_scale",
    )
    values = [
        _finite(output_scale[key], f"output_scale.{key}")
        for key in ("minimum", "median", "maximum")
    ]
    if values != sorted(values):
        raise ProbeAEvidenceError("Probe-A output-scale summary is invalid")
    for field in ("negative_fraction", "near_integer_fraction"):
        value = _finite_nonnegative(output_scale[field], f"output_scale.{field}")
        if value > 1:
            raise ProbeAEvidenceError(f"output_scale.{field} must be a fraction")
    for field, expected in raw["output_scale"].items():
        _require_close(output_scale[field], expected, f"output_scale.{field}")

    registered_bridge = registration["output_bridge"]
    bridge = _exact_keys(report["output_bridge"], _BRIDGE_KEYS, "output_bridge")
    bridge_error = _finite_nonnegative(bridge["max_abs_error"], "output_bridge.max_abs_error")
    _require_close(bridge_error, raw["bridge_error"], "output-bridge max_abs_error")
    bridge_tol = _finite_nonnegative(bridge["tolerance"], "output_bridge.tolerance")
    if bridge["representation"] != registered_bridge["representation"] or bridge_tol != float(
        registered_bridge["max_abs_error_tolerance"]
    ):
        raise ProbeAEvidenceError("Probe-A output bridge differs from preregistration")
    output_bridge_passed = bridge_error <= bridge_tol
    expected_bridge_verdict = "pass" if output_bridge_passed else "fail"
    if bridge["verdict"] != expected_bridge_verdict:
        raise ProbeAEvidenceError("Probe-A output-bridge verdict disagrees with raw measurements")

    expected_status = (
        "pass" if determinism_passed and control_count_passed and output_bridge_passed else "failed"
    )
    if report["status"] != expected_status:
        raise ProbeAEvidenceError("Probe-A report status disagrees with its measured gate verdicts")


def _validate_role_path(role: str, relative: str) -> None:
    if role in _SINGLETON_ROLE_PATHS and relative != _SINGLETON_ROLE_PATHS[role]:
        raise ProbeAEvidenceError(f"Probe-A manifest {role} path is not canonical")
    path = Path(relative)
    if role == "roster_receipt" and (not path.parts or path.parts[0] != "roster_receipts"):
        raise ProbeAEvidenceError("Probe-A roster receipt must be under roster_receipts/")
    if role == "probe_a_checkpoint" and (
        not path.parts or path.parts[0] != "checkpoints" or path.suffix != ".pt"
    ):
        raise ProbeAEvidenceError("Probe-A checkpoint must be a .pt file under checkpoints/")
    if role == "log" and (not path.parts or path.parts[0] != "logs"):
        raise ProbeAEvidenceError("Probe-A log must be under logs/")


def validate_evidence_manifest(
    manifest: Mapping,
    *,
    evidence_root: str | Path,
    expected_git_commit: str,
) -> None:
    """Validate the exhaustive, canonical file roster for one complete probe attempt."""
    obj = _exact_keys(
        manifest,
        {"schema", "protocol", "git_commit", "files", "manifest_checksum"},
        "evidence manifest",
    )
    if obj["schema"] != MANIFEST_SCHEMA or obj["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("Probe-A evidence-manifest identity mismatch")
    commit = _git_commit(obj["git_commit"], "evidence manifest git_commit")
    if commit != _git_commit(expected_git_commit, "expected Git commit"):
        raise ProbeAEvidenceError("Probe-A evidence-manifest Git commit mismatch")
    checksum = _sha(obj["manifest_checksum"], "evidence manifest checksum")
    body = {key: value for key, value in obj.items() if key != "manifest_checksum"}
    if checksum != sha256_json(body):
        raise ProbeAEvidenceError("Probe-A evidence-manifest checksum mismatch")
    files = obj["files"]
    if not isinstance(files, list) or not files:
        raise ProbeAEvidenceError("Probe-A evidence-manifest file roster is empty")

    root = Path(evidence_root)
    observed_paths: set[str] = set()
    roles: Counter[str] = Counter()
    for raw_entry in files:
        entry = _exact_keys(raw_entry, _MANIFEST_ENTRY_KEYS, "manifest file")
        role = entry["role"]
        if not isinstance(role, str) or role not in _KNOWN_ROLES:
            raise ProbeAEvidenceError("Probe-A evidence-manifest role is unknown")
        relative = entry["path"]
        if not isinstance(relative, str) or not relative:
            raise ProbeAEvidenceError("Probe-A evidence-manifest path must be a string")
        if relative in observed_paths:
            raise ProbeAEvidenceError("Probe-A evidence-manifest path is duplicated")
        observed_paths.add(relative)
        roles[role] += 1
        _validate_role_path(role, relative)
        path = _relative_file(root, relative)
        if isinstance(entry["bytes"], bool) or not isinstance(entry["bytes"], int):
            raise ProbeAEvidenceError("Probe-A manifest byte count must be an integer")
        if entry["bytes"] < 0 or path.stat().st_size != entry["bytes"]:
            raise ProbeAEvidenceError("Probe-A manifest byte count mismatch")
        if sha256_file(path) != _sha(entry["sha256"], "manifest file SHA-256"):
            raise ProbeAEvidenceError("Probe-A manifest file SHA-256 mismatch")

    for role in _SINGLETON_ROLE_PATHS:
        if roles[role] != 1:
            raise ProbeAEvidenceError(f"Probe-A manifest requires exactly one {role} file")
    for role in _MULTI_ROLES:
        if roles[role] < 1:
            raise ProbeAEvidenceError(f"Probe-A manifest requires at least one {role} file")
    if roles["probe_a_checkpoint"] != 2:
        raise ProbeAEvidenceError("Probe-A manifest requires exactly two checkpoint files")

    inventory = _manifest_inventory(root)
    if observed_paths != inventory:
        missing = sorted(inventory - observed_paths)
        unexpected = sorted(observed_paths - inventory)
        raise ProbeAEvidenceError(
            "Probe-A evidence-manifest is not exhaustive: "
            f"unmanifested={missing} absent_from_tree={unexpected}"
        )


def _read_json_entry(
    root: Path,
    entry: Mapping,
    *,
    label: str,
    pretty_canonical: bool = False,
) -> dict:
    path = _relative_file(root, entry["path"])
    try:
        data = path.read_bytes()
        payload = json.loads(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeAEvidenceError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProbeAEvidenceError(f"{label} must be a JSON object")
    if len(data) != entry["bytes"] or sha256_bytes(data) != entry["sha256"]:
        raise ProbeAEvidenceError(f"{label} bytes changed after manifest validation")
    try:
        if pretty_canonical:
            expected = (
                json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
            ).encode("utf-8")
        else:
            expected = _canonical_file_bytes(payload)
    except (TypeError, ValueError) as exc:
        raise ProbeAEvidenceError(f"{label} is not canonical finite JSON") from exc
    if data != expected:
        raise ProbeAEvidenceError(f"{label} bytes are not canonical JSON")
    return payload


def _positive_int(value: object, field: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ProbeAEvidenceError(f"{field} must be a {qualifier} integer")
    return value


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProbeAEvidenceError(f"{field} must be a non-empty string")
    return value


def _fit_role_counts(value: object, field: str) -> dict[str, int]:
    counts = _exact_keys(value, _FIT_ROLE_COUNT_KEYS, field)
    result = {
        "control": _positive_int(counts["control"], f"{field}.control"),
        "singles": _positive_int(counts["singles"], f"{field}.singles"),
        "combo_calibration": _positive_int(
            counts["combo_calibration"], f"{field}.combo_calibration", allow_zero=True
        ),
    }
    return result


def _canonical_pair_roster(value: object, field: str, *, allow_empty: bool) -> list[list[str]]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise ProbeAEvidenceError(f"{field} must be {qualifier} of canonical pairs")
    pairs: list[list[str]] = []
    for index, raw_pair in enumerate(value):
        if (
            not isinstance(raw_pair, list)
            or len(raw_pair) != 2
            or any(not isinstance(gene, str) or not gene for gene in raw_pair)
            or raw_pair[0].encode("utf-8") >= raw_pair[1].encode("utf-8")
        ):
            raise ProbeAEvidenceError(f"{field}[{index}] is not one canonical gene pair")
        pairs.append(list(raw_pair))
    if pairs != sorted(pairs, key=lambda pair: (pair[0].encode("utf-8"), pair[1].encode("utf-8"))):
        raise ProbeAEvidenceError(f"{field} must be byte-sorted")
    if len({tuple(pair) for pair in pairs}) != len(pairs):
        raise ProbeAEvidenceError(f"{field} must not contain duplicates")
    return pairs


def _validate_role_contract(value: object, field: str) -> dict[str, object]:
    obj = _exact_keys(value, _ROLE_CONTRACT_KEYS, field)
    control_token = _nonempty_string(obj["control_token"], f"{field}.control_token")
    combo_separator = _nonempty_string(obj["combo_separator"], f"{field}.combo_separator")
    if combo_separator in control_token:
        raise ProbeAEvidenceError(f"{field} control token contains the combo separator")
    calibration = _canonical_pair_roster(
        obj["calibration_pair_ids"], f"{field}.calibration_pair_ids", allow_empty=True
    )
    sealed = _canonical_pair_roster(
        obj["sealed_pair_ids"], f"{field}.sealed_pair_ids", allow_empty=False
    )
    if set(map(tuple, calibration)) & set(map(tuple, sealed)):
        raise ProbeAEvidenceError(f"{field} calibration and sealed pair rosters overlap")
    singles = obj["single_gene_ids"]
    if (
        not isinstance(singles, list)
        or not singles
        or any(not isinstance(gene, str) or not gene for gene in singles)
        or singles != sorted(singles, key=lambda gene: gene.encode("utf-8"))
        or len(set(singles)) != len(singles)
    ):
        raise ProbeAEvidenceError(f"{field}.single_gene_ids must be a unique byte-sorted roster")
    calibration_tokens = {combo_separator.join(pair) for pair in calibration}
    sealed_tokens = {combo_separator.join(pair) for pair in sealed}
    if len(calibration_tokens) != len(calibration) or len(sealed_tokens) != len(sealed):
        raise ProbeAEvidenceError(f"{field} pair roster has ambiguous serialized tokens")
    if calibration_tokens & sealed_tokens:
        raise ProbeAEvidenceError(f"{field} calibration and sealed tokens collide")
    reserved_tokens = calibration_tokens | sealed_tokens | {control_token}
    if reserved_tokens & set(singles):
        raise ProbeAEvidenceError(f"{field} control/combo and single tokens collide")
    return {
        "calibration_pair_ids": calibration,
        "combo_separator": combo_separator,
        "control_token": control_token,
        "sealed_pair_ids": sealed,
        "single_gene_ids": list(singles),
    }


def _timestamp(value: object, field: str) -> datetime:
    text = _nonempty_string(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProbeAEvidenceError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ProbeAEvidenceError(f"{field} must include a timezone")
    return parsed


def _validate_runtime(payload: Mapping, *, expected_git_commit: str) -> dict:
    obj = _exact_keys(payload, _RUNTIME_KEYS, "runtime evidence")
    _checksum(obj, "runtime evidence")
    if obj["schema"] != RUNTIME_SCHEMA or obj["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("runtime evidence identity mismatch")
    if _git_commit(obj["git_commit"], "runtime git_commit") != _git_commit(
        expected_git_commit, "expected Git commit"
    ):
        raise ProbeAEvidenceError("runtime evidence Git commit mismatch")
    for field in (
        "pod_instance",
        "gpu_model",
        "gpu_uuid",
        "driver_version",
        "cuda_version",
        "cpu_model",
        "python_version",
    ):
        _nonempty_string(obj[field], f"runtime.{field}")
    _positive_int(obj["cpu_count"], "runtime.cpu_count")
    _positive_int(obj["ram_bytes"], "runtime.ram_bytes")
    image_digest = _nonempty_string(obj["image_digest"], "runtime.image_digest")
    if not image_digest.startswith("sha256:") or len(image_digest) != 71:
        raise ProbeAEvidenceError("runtime.image_digest must be sha256:<64 lowercase hex>")
    _sha(image_digest.removeprefix("sha256:"), "runtime.image_digest")
    _sha(
        obj["preparation_dependency_lock_sha256"],
        "runtime.preparation_dependency_lock_sha256",
    )
    _sha(obj["gears_dependency_lock_sha256"], "runtime.gears_dependency_lock_sha256")
    _sha(
        obj["gears_installed_packages_sha256"],
        "runtime.gears_installed_packages_sha256",
    )
    _sha(obj["runtime_fingerprint_sha256"], "runtime.runtime_fingerprint_sha256")
    if obj["network_disabled"] is not True:
        raise ProbeAEvidenceError("runtime evidence must attest network_disabled=true")
    return dict(obj)


def _validate_inputs(payload: Mapping, *, expected_git_commit: str) -> dict:
    obj = _exact_keys(payload, _INPUTS_KEYS, "input evidence")
    _checksum(obj, "input evidence")
    if obj["schema"] != INPUTS_SCHEMA or obj["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("input evidence identity mismatch")
    if _git_commit(obj["git_commit"], "inputs git_commit") != _git_commit(
        expected_git_commit, "expected Git commit"
    ):
        raise ProbeAEvidenceError("input evidence Git commit mismatch")
    non_digest_fields = {"schema", "protocol", "git_commit", "fit_role_counts", "self_checksum"}
    for field in _INPUTS_KEYS - non_digest_fields:
        _sha(obj[field], f"inputs.{field}")
    obj = dict(obj)
    obj["fit_role_counts"] = _fit_role_counts(obj["fit_role_counts"], "inputs.fit_role_counts")
    return obj


def _validate_role_attestation(payload: Mapping, *, expected_git_commit: str) -> dict:
    obj = _exact_keys(payload, _ROLE_ATTESTATION_KEYS, "role attestation")
    _checksum(obj, "role attestation")
    if obj["schema"] != ROLE_ATTESTATION_SCHEMA or obj["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("role attestation identity mismatch")
    if _git_commit(obj["git_commit"], "role attestation git_commit") != _git_commit(
        expected_git_commit, "expected Git commit"
    ):
        raise ProbeAEvidenceError("role attestation Git commit mismatch")
    if obj["sealed_pair_overlap_count"] != 0 or obj["sealed_row_read_count"] != 0:
        raise ProbeAEvidenceError("role attestation must prove zero sealed overlap and zero reads")
    counts = _fit_role_counts(obj["fit_role_counts"], "role_attestation.fit_role_counts")
    spy = _exact_keys(
        obj["reader_spy"],
        {
            "status",
            "selected_source_row_ids_sha256",
            "observed_source_row_ids_sha256",
            "observed_source_row_count",
            "forbidden_source_row_read_count",
        },
        "reader_spy",
    )
    if spy["status"] != "pass":
        raise ProbeAEvidenceError("role attestation reader-spy did not pass")
    selected_sha = _sha(
        spy["selected_source_row_ids_sha256"],
        "reader_spy.selected_source_row_ids_sha256",
    )
    observed_sha = _sha(
        spy["observed_source_row_ids_sha256"],
        "reader_spy.observed_source_row_ids_sha256",
    )
    if selected_sha != observed_sha:
        raise ProbeAEvidenceError("reader-spy observed a different row roster than it selected")
    _positive_int(spy["observed_source_row_count"], "reader_spy.observed_source_row_count")
    forbidden_count = _positive_int(
        spy["forbidden_source_row_read_count"],
        "reader_spy.forbidden_source_row_read_count",
        allow_zero=True,
    )
    if forbidden_count != 0:
        raise ProbeAEvidenceError("reader-spy observed a forbidden source-row read")
    result = dict(obj)
    result["fit_role_counts"] = counts
    result["reader_spy"] = dict(spy)
    return result


def _validate_roster_receipt(payload: Mapping) -> dict:
    obj = _exact_keys(payload, _ROSTER_RECEIPT_KEYS, "roster receipt")
    if obj["schema"] != ROSTER_RECEIPT_SCHEMA:
        raise ProbeAEvidenceError("roster receipt identity mismatch")
    checksum = _sha(obj["manifest_checksum"], "roster receipt manifest_checksum")
    body = {key: value for key, value in obj.items() if key != "manifest_checksum"}
    if checksum != sha256_json(body):
        raise ProbeAEvidenceError("roster receipt manifest checksum mismatch")
    for field in _ROSTER_RECEIPT_KEYS - {"schema", "manifest_checksum", "n_target"}:
        _sha(obj[field], f"roster receipt.{field}")
    _positive_int(obj["n_target"], "roster receipt.n_target")
    return dict(obj)


def _validate_commands(
    path: Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
    runtime_fingerprint_sha256: str,
    gene2go_manifest_sha256: str,
    gene2go_nodes_artifact_sha256: str,
    manifested_files: Mapping[str, str],
    raw_sample_path: str,
    raw_sample_sha256: str,
    probe_input_manifest_path: str,
    probe_input_manifest_sha256: str,
    probe_input_h5ad_path: str,
    registration_path: str,
    registration_sha256: str,
    owner_policy_sha256: str,
    report_path: str,
    report_sha256: str,
    expected_git_commit: str,
) -> None:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ProbeAEvidenceError(f"cannot read commands evidence: {exc}") from exc
    if len(data) != expected_bytes or sha256_bytes(data) != expected_sha256:
        raise ProbeAEvidenceError("commands evidence bytes changed after manifest validation")
    lines = data.splitlines()
    if not lines:
        raise ProbeAEvidenceError("commands evidence is empty")
    observed: Counter[str] = Counter()
    command_order: list[str] = []
    registration_primary_sha256: list[str] = []
    probe_a_primary_sha256: list[str] = []
    report_primary_sha256: list[str] = []
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProbeAEvidenceError(f"commands record {index} is invalid JSON") from exc
        obj = _exact_keys(record, _COMMAND_KEYS, f"commands record {index}")
        try:
            canonical_line = canonical_json(obj).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ProbeAEvidenceError(
                f"commands record {index} is not canonical finite JSON"
            ) from exc
        if line != canonical_line:
            raise ProbeAEvidenceError(f"commands record {index} is not canonical JSONL")
        _checksum(obj, f"commands record {index}")
        if obj["schema"] != COMMAND_RECORD_SCHEMA:
            raise ProbeAEvidenceError("commands evidence schema mismatch")
        command = _nonempty_string(obj["command"], f"commands record {index}.command")
        if command not in _REQUIRED_COMMANDS:
            raise ProbeAEvidenceError(
                "commands evidence contains an unsupported maintained-CLI command"
            )
        observed[command] += 1
        command_order.append(command)
        argv = obj["argv"]
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(token, str) or not token for token in argv)
        ):
            raise ProbeAEvidenceError("commands argv must be a non-empty string list")
        if command not in argv or not any(
            token.endswith("scripts/compose/gears_decision_probe.py") for token in argv
        ):
            raise ProbeAEvidenceError(
                "commands argv must invoke the maintained GEARS probe CLI and named subcommand"
            )
        if any("$(" in token or "`" in token for token in argv):
            raise ProbeAEvidenceError("commands argv must not use shell command substitution")
        if command == "build-roster":
            required_options = (
                "--gene2go-nodes-artifact",
                "--gene2go-nodes-artifact-sha256",
                "--gears-resource-manifest",
                "--gears-resource-manifest-sha256",
                "--gene2go-source",
                "--gene2go-source-sha256",
            )
            for option in required_options:
                if argv.count(option) != 1 or argv.index(option) + 1 >= len(argv):
                    raise ProbeAEvidenceError(
                        f"GEARS roster command requires exactly one {option} value"
                    )
            source = argv[argv.index("--gene2go-source") + 1]
            nodes = argv[argv.index("--gene2go-nodes-artifact") + 1]
            matching_node_paths = [
                relative
                for relative in manifested_files
                if Path(nodes).as_posix() == relative or nodes.endswith(f"/{relative}")
            ]
            if (
                argv[argv.index("--gears-resource-manifest-sha256") + 1] != gene2go_manifest_sha256
                or Path(source).name != "gene2go_all.pkl"
                or len(matching_node_paths) != 1
                or manifested_files[matching_node_paths[0]] != gene2go_nodes_artifact_sha256
                or argv[argv.index("--gene2go-nodes-artifact-sha256") + 1]
                != gene2go_nodes_artifact_sha256
            ):
                raise ProbeAEvidenceError(
                    "GEARS roster command is not bound to the pinned gene2go resources"
                )
            _sha(
                argv[argv.index("--gene2go-source-sha256") + 1],
                "GEARS roster gene2go source SHA-256",
            )
        elif command == "build-probe-a-registration":
            required_options = (
                "--evidence-root",
                "--probe-manifest",
                "--probe-manifest-sha256",
                "--owner-policy",
                "--owner-policy-sha256",
                "--git-commit",
                "--out-registration",
            )
            for option in required_options:
                if argv.count(option) != 1 or argv.index(option) + 1 >= len(argv):
                    raise ProbeAEvidenceError(
                        f"Probe-A registration command requires exactly one {option} value"
                    )
            probe_manifest = argv[argv.index("--probe-manifest") + 1]
            owner_policy = argv[argv.index("--owner-policy") + 1]
            output = argv[argv.index("--out-registration") + 1]
            if (
                (
                    Path(probe_manifest).as_posix() != probe_input_manifest_path
                    and not probe_manifest.endswith(f"/{probe_input_manifest_path}")
                )
                or argv[argv.index("--probe-manifest-sha256") + 1] != probe_input_manifest_sha256
                or (
                    Path(owner_policy).as_posix() != PROBE_A_OWNER_POLICY_PATH
                    and not owner_policy.endswith(f"/{PROBE_A_OWNER_POLICY_PATH}")
                )
                or argv[argv.index("--owner-policy-sha256") + 1] != owner_policy_sha256
                or argv[argv.index("--git-commit") + 1] != expected_git_commit
                or (
                    Path(output).as_posix() != registration_path
                    and not output.endswith(f"/{registration_path}")
                )
            ):
                raise ProbeAEvidenceError(
                    "Probe-A registration command is not bound to policy/prepared input/output"
                )
        elif command == "probe-a":
            required_options = (
                "--payload-dir",
                "--probe-a-registration",
                "--probe-a-registration-sha256",
                "--git-commit",
                "--probe-manifest",
                "--probe-manifest-sha256",
                "--h5ad",
                "--roster",
                "--roster-receipt",
                "--approved-root",
                "--evidence-root",
                "--out-raw",
                "--checkpoint-dir",
            )
            if "--measurement-json" in argv:
                raise ProbeAEvidenceError(
                    "Probe-A command must execute the maintained runner, not publish JSON"
                )
            for option in required_options:
                if argv.count(option) != 1 or argv.index(option) + 1 >= len(argv):
                    raise ProbeAEvidenceError(
                        f"Probe-A measurement command requires exactly one {option} value"
                    )
            out_raw = argv[argv.index("--out-raw") + 1]
            if Path(out_raw).as_posix() != raw_sample_path and not out_raw.endswith(
                f"/{raw_sample_path}"
            ):
                raise ProbeAEvidenceError(
                    "Probe-A measurement command output path differs from the raw manifest path"
                )
            probe_manifest = argv[argv.index("--probe-manifest") + 1]
            registration = argv[argv.index("--probe-a-registration") + 1]
            h5ad = argv[argv.index("--h5ad") + 1]
            checkpoint_dir = argv[argv.index("--checkpoint-dir") + 1]
            if (
                (
                    Path(registration).as_posix() != registration_path
                    and not registration.endswith(f"/{registration_path}")
                )
                or argv[argv.index("--probe-a-registration-sha256") + 1] != registration_sha256
                or argv[argv.index("--git-commit") + 1] != expected_git_commit
                or (
                    Path(probe_manifest).as_posix() != probe_input_manifest_path
                    and not probe_manifest.endswith(f"/{probe_input_manifest_path}")
                )
                or (
                    Path(h5ad).as_posix() != probe_input_h5ad_path
                    and not h5ad.endswith(f"/{probe_input_h5ad_path}")
                )
                or argv[argv.index("--probe-manifest-sha256") + 1] != probe_input_manifest_sha256
                or (
                    Path(checkpoint_dir).as_posix() != "checkpoints"
                    and not checkpoint_dir.endswith("/checkpoints")
                )
            ):
                raise ProbeAEvidenceError(
                    "Probe-A command is not bound to the canonical prepared input/checkpoints"
                )
        elif command == "build-probe-a-report":
            required_options = (
                "--evidence-root",
                "--raw-sample",
                "--raw-sample-sha256",
                "--probe-a-registration",
                "--probe-a-registration-sha256",
                "--git-commit",
                "--out-report",
            )
            for option in required_options:
                if argv.count(option) != 1 or argv.index(option) + 1 >= len(argv):
                    raise ProbeAEvidenceError(
                        f"Probe-A report command requires exactly one {option} value"
                    )
            raw_sample = argv[argv.index("--raw-sample") + 1]
            registration = argv[argv.index("--probe-a-registration") + 1]
            output = argv[argv.index("--out-report") + 1]
            if (
                (
                    Path(raw_sample).as_posix() != raw_sample_path
                    and not raw_sample.endswith(f"/{raw_sample_path}")
                )
                or argv[argv.index("--raw-sample-sha256") + 1] != raw_sample_sha256
                or (
                    Path(registration).as_posix() != registration_path
                    and not registration.endswith(f"/{registration_path}")
                )
                or argv[argv.index("--probe-a-registration-sha256") + 1] != registration_sha256
                or argv[argv.index("--git-commit") + 1] != expected_git_commit
                or (
                    Path(output).as_posix() != report_path
                    and not output.endswith(f"/{report_path}")
                )
            ):
                raise ProbeAEvidenceError(
                    "Probe-A report command is not bound to the raw/registration/report contract"
                )
        _nonempty_string(obj["cwd"], f"commands record {index}.cwd")
        env = obj["env"]
        if not isinstance(env, Mapping) or any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or any(
                secret in key.lower() for secret in ("secret", "token", "password", "private_key")
            )
            for key, value in env.items()
        ):
            raise ProbeAEvidenceError("commands env must be a secret-free string allowlist")
        started = _timestamp(obj["started_at_utc"], f"commands record {index}.started_at_utc")
        ended = _timestamp(obj["ended_at_utc"], f"commands record {index}.ended_at_utc")
        if ended < started:
            raise ProbeAEvidenceError("commands record ended before it started")
        if obj["exit_code"] != 0:
            raise ProbeAEvidenceError("commands evidence contains a failed command")
        primary_sha256 = _sha(
            obj["primary_file_sha256"], f"commands record {index}.primary_file_sha256"
        )
        if command == "build-probe-a-registration":
            registration_primary_sha256.append(primary_sha256)
        elif command == "probe-a":
            probe_a_primary_sha256.append(primary_sha256)
        elif command == "build-probe-a-report":
            report_primary_sha256.append(primary_sha256)
        if (
            _sha(
                obj["runtime_fingerprint_sha256"],
                f"commands record {index}.runtime_fingerprint_sha256",
            )
            != runtime_fingerprint_sha256
        ):
            raise ProbeAEvidenceError("commands runtime fingerprint differs from runtime evidence")
    observed_commands = frozenset(observed)
    if observed_commands != _REQUIRED_COMMANDS:
        raise ProbeAEvidenceError(
            "commands evidence does not contain the exact required command roster: "
            f"missing={sorted(_REQUIRED_COMMANDS - observed_commands)} "
            f"unexpected={sorted(observed_commands - _REQUIRED_COMMANDS)}"
        )
    unique_commands = _REQUIRED_COMMANDS - {"build-roster"}
    if any(observed[command] != 1 for command in unique_commands):
        raise ProbeAEvidenceError(
            "commands evidence must contain each stateful maintained command exactly once"
        )
    critical_order = [
        command_order.index(command)
        for command in (
            "prepare-input",
            "verify-input",
            "build-probe-a-registration",
            "probe-a",
            "build-probe-a-report",
        )
    ]
    if critical_order != sorted(critical_order):
        raise ProbeAEvidenceError("commands evidence violates the stateful protocol order")
    if registration_primary_sha256 != [_sha(registration_sha256, "Probe-A registration SHA-256")]:
        raise ProbeAEvidenceError(
            "Probe-A registration command primary SHA-256 is not bound to registration"
        )
    if observed["probe-a"] != 1:
        raise ProbeAEvidenceError(
            "commands evidence requires exactly one Probe-A measurement command"
        )
    if probe_a_primary_sha256 != [_sha(raw_sample_sha256, "raw sample SHA-256")]:
        raise ProbeAEvidenceError(
            "Probe-A measurement command primary SHA-256 is not bound to the raw artifact"
        )
    if observed["build-probe-a-report"] != 1:
        raise ProbeAEvidenceError(
            "commands evidence requires exactly one Probe-A report-build command"
        )
    if report_primary_sha256 != [_sha(report_sha256, "Probe-A report SHA-256")]:
        raise ProbeAEvidenceError(
            "Probe-A report command primary SHA-256 is not bound to the report artifact"
        )


def _validate_prepared_input_chain(
    *,
    root: Path,
    manifest_entry: Mapping,
    h5ad_entry: Mapping,
    inputs: Mapping,
    receipt: Mapping,
    runtime: Mapping,
    raw: Mapping,
    role_attestation: Mapping,
    registration: Mapping,
    registration_sha256: str,
) -> None:
    manifest = _read_json_entry(
        root,
        manifest_entry,
        label="Probe-A prepared-input manifest",
        pretty_canonical=True,
    )
    _exact_keys(manifest, PROBE_INPUT_MANIFEST_KEYS, "Probe-A prepared-input manifest")
    if manifest["schema"] != PROBE_INPUT_MANIFEST_SCHEMA:
        raise ProbeAEvidenceError("Probe-A prepared-input manifest schema mismatch")
    for field in (
        "fit_artifact_content_sha256",
        "full_var_order_sha256",
        "ordered_roster_sha256",
        "output_h5ad_sha256",
        "payload_sha256",
        "probe_driver_code_sha256",
        "probe_runtime_fingerprint_sha256",
        "response_artifact_sha256",
        "roster_artifact_checksum",
        "roster_file_sha256",
        "roster_receipt_sha256",
        "row_identity_sha256",
        "selected_source_row_ids_sha256",
        "matrix_logical_sha256",
    ):
        _sha(manifest[field], f"prepared manifest.{field}")
    for field in ("n_cells", "n_genes"):
        _positive_int(manifest[field], f"prepared manifest.{field}")
    manifest_role_counts = _fit_role_counts(
        manifest["role_counts"], "prepared manifest.role_counts"
    )
    normalization_target = _finite_nonnegative(
        manifest["normalization_target"], "prepared manifest.normalization_target"
    )
    if normalization_target <= 0:
        raise ProbeAEvidenceError("prepared input normalization target must be positive")
    if manifest["expression_scale"] != PROBE_INPUT_TRANSFORM:
        raise ProbeAEvidenceError("Probe-A prepared-input expression scale mismatch")
    if (
        manifest["matrix_dtype"] != PROBE_MATRIX_DTYPE
        or manifest["matrix_format"] != PROBE_MATRIX_FORMAT
    ):
        raise ProbeAEvidenceError("Probe-A prepared-input matrix storage contract mismatch")
    role_contract = _validate_role_contract(
        manifest["role_contract"], "prepared manifest.role_contract"
    )
    if (
        normalization_target != float(registration["input_scale"]["normalization_target"])
        or manifest["expression_scale"] != registration["input_scale"]["transform"]
    ):
        raise ProbeAEvidenceError("prepared input scale differs from preregistration")
    manifest_body = {key: value for key, value in manifest.items() if key != "manifest_checksum"}
    if _sha(manifest["manifest_checksum"], "prepared manifest checksum") != sha256_json(
        manifest_body
    ):
        raise ProbeAEvidenceError("Probe-A prepared-input manifest checksum mismatch")
    if (
        inputs["probe_input_manifest_sha256"] != manifest_entry["sha256"]
        or inputs["probe_input_h5ad_sha256"] != h5ad_entry["sha256"]
        or manifest["output_h5ad_sha256"] != h5ad_entry["sha256"]
        or inputs["probe_row_identity_sha256"] != manifest["row_identity_sha256"]
        or inputs["roster_sha256"] != manifest["roster_file_sha256"]
        or inputs["roster_receipt_sha256"] != manifest["roster_receipt_sha256"]
    ):
        raise ProbeAEvidenceError("input evidence is not bound to the prepared H5AD/manifest")
    receipt_bindings = {
        "fit_artifact_content_sha256": "fit_artifact_content_sha256",
        "ordered_roster_sha256": "ordered_roster_sha256",
        "payload_sha256": "payload_sha256",
        "response_artifact_sha256": "response_artifact_sha256",
        "roster_artifact_checksum": "roster_artifact_checksum",
        "roster_file_sha256": "roster_file_sha256",
    }
    if any(manifest[left] != receipt[right] for left, right in receipt_bindings.items()):
        raise ProbeAEvidenceError("prepared input manifest differs from its roster receipt lineage")
    if (
        manifest["response_artifact_sha256"] != inputs["response_artifact_sha256"]
        or receipt["preparation_dependency_lock_sha256"]
        != inputs["preparation_dependency_lock_sha256"]
        or receipt["gears_dependency_lock_sha256"] != inputs["gears_dependency_lock_sha256"]
        or manifest["probe_runtime_fingerprint_sha256"] != runtime["runtime_fingerprint_sha256"]
    ):
        raise ProbeAEvidenceError("prepared input lineage differs from runtime/input evidence")

    h5ad_path = _relative_file(root, h5ad_entry["path"])
    if h5ad_path.stat().st_size > _H5AD_ENVELOPE_BYTES:
        raise ProbeAEvidenceError("prepared Probe-A H5AD exceeds the evidence envelope bound")
    try:
        probe = ad.read_h5ad(h5ad_path)
    except Exception as exc:
        raise ProbeAEvidenceError(f"cannot read the prepared Probe-A H5AD: {exc}") from exc
    required_obs = {"source_row_id", "role", "perturbation"}
    if not required_obs <= set(probe.obs.columns):
        raise ProbeAEvidenceError("prepared Probe-A H5AD lacks row-identity columns")
    if (
        int(probe.n_obs) != manifest["n_cells"]
        or int(probe.n_vars) != manifest["n_genes"]
        or not probe.var_names.is_unique
    ):
        raise ProbeAEvidenceError("prepared Probe-A H5AD dimensions/gene identity differ")
    source_ids = probe.obs["source_row_id"].astype(str).tolist()
    roles = probe.obs["role"].astype(str).tolist()
    perturbations = probe.obs["perturbation"].astype(str).tolist()
    if any(not row_id for row_id in source_ids) or len(set(source_ids)) != len(source_ids):
        raise ProbeAEvidenceError("prepared Probe-A source-row identities are invalid")
    rows = list(zip(source_ids, roles, perturbations, strict=True))
    if row_identity_sha256(rows) != manifest["row_identity_sha256"]:
        raise ProbeAEvidenceError("prepared Probe-A row identity differs from its manifest")
    observed_counts = {
        role: roles.count(role) for role in ("control", "singles", "combo_calibration")
    }
    if observed_counts != manifest_role_counts or observed_counts != inputs["fit_role_counts"]:
        raise ProbeAEvidenceError("prepared Probe-A role counts differ from input evidence")
    selected_source_row_ids_sha256 = sha256_json(source_ids)
    if selected_source_row_ids_sha256 != manifest["selected_source_row_ids_sha256"]:
        raise ProbeAEvidenceError("prepared source-row roster differs from its manifest")

    combo_separator = str(role_contract["combo_separator"])
    calibration_tokens = {
        combo_separator.join(pair) for pair in role_contract["calibration_pair_ids"]
    }
    sealed_tokens = {combo_separator.join(pair) for pair in role_contract["sealed_pair_ids"]}
    singles = set(role_contract["single_gene_ids"])
    control_token = str(role_contract["control_token"])
    recomputed_roles: list[str] = []
    sealed_pair_overlap_count = 0
    for perturbation in perturbations:
        if perturbation == control_token:
            recomputed_roles.append("control")
            continue
        if perturbation in sealed_tokens:
            sealed_pair_overlap_count += 1
            recomputed_roles.append("sealed")
            continue
        if perturbation in calibration_tokens:
            recomputed_roles.append("combo_calibration")
            continue
        if perturbation not in singles:
            raise ProbeAEvidenceError("prepared input contains an unregistered perturbation token")
        recomputed_roles.append("singles")
    if recomputed_roles != roles:
        raise ProbeAEvidenceError("prepared fit roles do not match metadata-derived roles")
    if sealed_pair_overlap_count != 0:
        raise ProbeAEvidenceError("prepared input overlaps the sealed pair roster")
    spy = role_attestation["reader_spy"]
    if (
        role_attestation["sealed_pair_overlap_count"] != sealed_pair_overlap_count
        or role_attestation["sealed_row_read_count"] != 0
        or spy["selected_source_row_ids_sha256"] != selected_source_row_ids_sha256
        or spy["observed_source_row_ids_sha256"] != selected_source_row_ids_sha256
        or spy["observed_source_row_count"] != len(source_ids)
        or spy["forbidden_source_row_read_count"] != 0
    ):
        raise ProbeAEvidenceError(
            "role/reader-spy attestation disagrees with independently derived prepared rows"
        )
    ordered_controls = [
        row_id for row_id, role in zip(source_ids, roles, strict=True) if role == "control"
    ]
    if ordered_controls != raw["ordered_control_row_ids"]:
        raise ProbeAEvidenceError(
            "raw control-row order is not the order in the archived prepared H5AD"
        )
    if sha256_json(ordered_controls) != inputs["ordered_control_row_identity_sha256"]:
        raise ProbeAEvidenceError("prepared control-row identity differs from input evidence")
    if not sparse.isspmatrix_csr(probe.X) or np.dtype(probe.X.dtype) != np.dtype("<f4"):
        raise ProbeAEvidenceError("prepared Probe-A H5AD is not canonical CSR float32")
    if not probe.X.has_sorted_indices or not probe.X.has_canonical_format:
        raise ProbeAEvidenceError("prepared Probe-A H5AD CSR storage is not canonical")
    matrix_identity = _matrix_identity(probe.X, "prepared Probe-A H5AD matrix")
    if matrix_identity["logical_csr_sha256"] != manifest["matrix_logical_sha256"]:
        raise ProbeAEvidenceError("prepared Probe-A matrix digest differs from its manifest")
    if matrix_identity != raw["input_before"]:
        raise ProbeAEvidenceError("raw input_before is not the archived prepared H5AD matrix")
    if probe.uns.get("schema") != PROBE_INPUT_ADATA_SCHEMA:
        raise ProbeAEvidenceError("prepared Probe-A H5AD schema mismatch")
    if probe.uns.get("normalization_target") != normalization_target:
        raise ProbeAEvidenceError("prepared Probe-A H5AD normalization target differs")
    for field in (
        "fit_artifact_content_sha256",
        "ordered_roster_sha256",
        "probe_driver_code_sha256",
        "probe_runtime_fingerprint_sha256",
        "response_artifact_sha256",
        "roster_artifact_checksum",
        "roster_receipt_sha256",
        "row_identity_sha256",
        "selected_source_row_ids_sha256",
        "matrix_logical_sha256",
        "matrix_dtype",
        "matrix_format",
    ):
        if probe.uns.get(field) != manifest[field]:
            raise ProbeAEvidenceError(f"prepared Probe-A H5AD {field} differs from manifest")

    producer = raw["producer"]
    repository_root = Path(__file__).resolve().parents[3]
    driver_path = repository_root / "scripts/compose/gears_decision_probe.py"
    worker_path = repository_root / "scripts/baselines/gears_worker.py"
    if (
        producer["registration_sha256"] != registration_sha256
        or producer["normalization_target"] != normalization_target
        or producer["input_scale_sha256"] != _input_scale_sha256(normalization_target)
        or producer["probe_input_manifest_sha256"] != manifest_entry["sha256"]
        or producer["probe_input_h5ad_sha256"] != h5ad_entry["sha256"]
        or producer["probe_row_identity_sha256"] != manifest["row_identity_sha256"]
        or producer["ordered_control_row_identity_sha256"]
        != inputs["ordered_control_row_identity_sha256"]
        or producer["roster_sha256"] != inputs["roster_sha256"]
        or producer["probe_driver_code_sha256"] != sha256_file(driver_path)
        or producer["probe_driver_code_sha256"] != manifest["probe_driver_code_sha256"]
        or producer["worker_code_sha256"] != sha256_file(worker_path)
    ):
        raise ProbeAEvidenceError(
            "raw producer is not bound to the maintained runner and prepared-input chain"
        )
    if any(
        manifest["fit_artifact_content_sha256"] not in strings
        for strings in raw["checkpoint_metadata_strings"]
    ):
        raise ProbeAEvidenceError(
            "Probe-A checkpoint metadata is not bound to the prepared fit artifact"
        )


def validate_evidence_semantics(
    manifest: Mapping,
    *,
    evidence_root: str | Path,
    expected_git_commit: str,
    registration_sha256: str,
) -> None:
    """Validate the content and cross-bindings of every decision-bearing evidence role."""
    root = Path(evidence_root)
    by_role = _manifest_by_role(manifest)
    registration_entry = by_role["probe_a_registration"][0]
    if registration_entry["sha256"] != _sha(registration_sha256, "registration_sha256"):
        raise ProbeAEvidenceError("semantic evidence registration SHA-256 differs from its pin")
    registration = _read_json_entry(
        root,
        registration_entry,
        label="Probe-A registration",
    )
    validate_registration(registration, expected_git_commit=expected_git_commit)
    runtime_entry = by_role["runtime"][0]
    inputs_entry = by_role["inputs"][0]
    runtime = _validate_runtime(
        _read_json_entry(root, runtime_entry, label="runtime evidence"),
        expected_git_commit=expected_git_commit,
    )
    inputs = _validate_inputs(
        _read_json_entry(root, inputs_entry, label="input evidence"),
        expected_git_commit=expected_git_commit,
    )
    role_attestation = _validate_role_attestation(
        _read_json_entry(
            root,
            by_role["role_attestation"][0],
            label="role attestation",
        ),
        expected_git_commit=expected_git_commit,
    )
    if role_attestation["fit_role_counts"] != inputs["fit_role_counts"]:
        raise ProbeAEvidenceError("role attestation counts differ from input evidence")
    expected_preparation_lock = repository_lock_sha256(PREPARATION_LOCK_PATH)
    expected_gears_lock = repository_lock_sha256(GEARS_LOCK_PATH)
    if (
        runtime["preparation_dependency_lock_sha256"]
        != inputs["preparation_dependency_lock_sha256"]
        or runtime["preparation_dependency_lock_sha256"] != expected_preparation_lock
        or runtime["gears_dependency_lock_sha256"] != inputs["gears_dependency_lock_sha256"]
        or runtime["gears_dependency_lock_sha256"] != expected_gears_lock
    ):
        raise ProbeAEvidenceError(
            "runtime/input dependency locks differ from the committed preparation/GEARS locks"
        )
    matching_receipts: list[dict] = []
    for entry in by_role["roster_receipt"]:
        receipt = _validate_roster_receipt(
            _read_json_entry(
                root,
                entry,
                label="roster receipt",
                pretty_canonical=True,
            )
        )
        if (entry["sha256"], receipt["roster_file_sha256"]) == (
            inputs["roster_receipt_sha256"],
            inputs["roster_sha256"],
        ):
            matching_receipts.append(receipt)
    if len(matching_receipts) != 1:
        raise ProbeAEvidenceError("input evidence is not bound to a manifested roster receipt")
    command_entry = by_role["commands"][0]
    raw_entries = by_role["raw_sample"]
    if len(raw_entries) != 1:
        raise ProbeAEvidenceError("semantic evidence requires exactly one raw sample")
    _validate_commands(
        _relative_file(root, command_entry["path"]),
        expected_sha256=command_entry["sha256"],
        expected_bytes=command_entry["bytes"],
        runtime_fingerprint_sha256=runtime["runtime_fingerprint_sha256"],
        gene2go_manifest_sha256=inputs["gene2go_manifest_sha256"],
        gene2go_nodes_artifact_sha256=matching_receipts[0]["gene2go_nodes_artifact_sha256"],
        manifested_files={
            entry["path"]: entry["sha256"] for entries in by_role.values() for entry in entries
        },
        raw_sample_path=raw_entries[0]["path"],
        raw_sample_sha256=raw_entries[0]["sha256"],
        probe_input_manifest_path=by_role["probe_input_manifest"][0]["path"],
        probe_input_manifest_sha256=by_role["probe_input_manifest"][0]["sha256"],
        probe_input_h5ad_path=by_role["probe_input_h5ad"][0]["path"],
        registration_path=registration_entry["path"],
        registration_sha256=registration_entry["sha256"],
        owner_policy_sha256=registration["owner_policy_sha256"],
        report_path=by_role["probe_a_report"][0]["path"],
        report_sha256=by_role["probe_a_report"][0]["sha256"],
        expected_git_commit=expected_git_commit,
    )

    raw = _load_probe_a_raw(
        root,
        {"path": raw_entries[0]["path"], "sha256": raw_entries[0]["sha256"]},
    )
    if (
        raw["producer"]["gears_dependency_lock_sha256"] != expected_gears_lock
        or raw["producer"]["gears_installed_packages_sha256"]
        != runtime["gears_installed_packages_sha256"]
    ):
        raise ProbeAEvidenceError(
            "raw producer runtime is not bound to the committed GEARS lock/package roster"
        )
    _validate_prepared_input_chain(
        root=root,
        manifest_entry=by_role["probe_input_manifest"][0],
        h5ad_entry=by_role["probe_input_h5ad"][0],
        inputs=inputs,
        receipt=matching_receipts[0],
        runtime=runtime,
        raw=raw,
        role_attestation=role_attestation,
        registration=registration,
        registration_sha256=registration_entry["sha256"],
    )
    manifested_checkpoints = {
        (entry["path"], entry["sha256"]) for entry in by_role["probe_a_checkpoint"]
    }
    if len(manifested_checkpoints) != 2 or set(raw["checkpoint_files"]) != manifested_checkpoints:
        raise ProbeAEvidenceError(
            "raw determinism checkpoints are not exactly the two manifested checkpoint files"
        )


def _manifest_by_role(manifest: Mapping) -> dict[str, list[Mapping]]:
    files = manifest.get("files") if isinstance(manifest, Mapping) else None
    if not isinstance(files, list):
        raise ProbeAEvidenceError("Probe-A binding requires a manifest file roster")
    result: dict[str, list[Mapping]] = {}
    for entry in files:
        item = _exact_keys(entry, _MANIFEST_ENTRY_KEYS, "manifest file")
        role = item["role"]
        if not isinstance(role, str) or role not in _KNOWN_ROLES:
            raise ProbeAEvidenceError("Probe-A binding encountered an unknown manifest role")
        result.setdefault(role, []).append(item)
    return result


def assert_report_manifest_binding(
    report: Mapping,
    manifest: Mapping,
    *,
    report_sha256: str,
    registration_sha256: str,
) -> None:
    """Bind report, registration, identities, and the exact raw-sample roster."""
    by_role = _manifest_by_role(manifest)

    def singleton_sha(role: str) -> str:
        entries = by_role.get(role, [])
        if len(entries) != 1:
            raise ProbeAEvidenceError(f"Probe-A binding requires exactly one {role} file")
        return entries[0]["sha256"]

    expected = {
        "probe_a_report": _sha(report_sha256, "report_sha256"),
        "probe_a_registration": _sha(registration_sha256, "registration_sha256"),
        "runtime": _sha(report.get("runtime_sha256"), "report.runtime_sha256"),
        "inputs": _sha(report.get("input_manifest_sha256"), "report.input_manifest_sha256"),
        "probe_a_source": _sha(
            report.get("source_fingerprint_sha256"), "report.source_fingerprint_sha256"
        ),
    }
    for role, digest in expected.items():
        if singleton_sha(role) != digest:
            raise ProbeAEvidenceError(f"Probe-A {role} SHA-256 disagrees with the report/CLI pin")
    if report.get("registration_sha256") != expected["probe_a_registration"]:
        raise ProbeAEvidenceError("Probe-A report registration SHA-256 disagrees with the manifest")

    samples = report.get("raw_samples") if isinstance(report, Mapping) else None
    if not isinstance(samples, list):
        raise ProbeAEvidenceError("Probe-A binding requires a report raw-sample roster")
    reported: set[tuple[str, str]] = set()
    for sample in samples:
        item = _exact_keys(sample, {"path", "sha256"}, "raw sample")
        path = item["path"]
        digest = _sha(item["sha256"], "raw sample SHA-256")
        if not isinstance(path, str) or not path:
            raise ProbeAEvidenceError("raw sample path must be a non-empty string")
        reported.add((path, digest))
    manifested: set[tuple[str, str]] = set()
    for item in by_role.get("raw_sample", []):
        path = item["path"]
        digest = _sha(item["sha256"], "manifest raw-sample SHA-256")
        if not isinstance(path, str) or not path:
            raise ProbeAEvidenceError("manifest raw-sample path must be a non-empty string")
        manifested.add((path, digest))
    if reported != manifested:
        raise ProbeAEvidenceError(
            "Probe-A report and manifest raw-sample rosters differ "
            f"report_only={sorted(reported - manifested)} "
            f"manifest_only={sorted(manifested - reported)}"
        )


def _canonical_file_bytes(payload: Mapping) -> bytes:
    return canonical_file_bytes(payload)


def validate_negative_verification(
    verification: Mapping,
    *,
    report: Mapping,
    report_sha256: str,
    registration_sha256: str,
    evidence_manifest_sha256: str,
    verifier_code_sha256: str,
    expected_git_commit: str,
) -> None:
    """Validate a verifier-bound negative result that grants no admission."""
    receipt = _exact_keys(
        verification,
        _NEGATIVE_VERIFICATION_KEYS,
        "Probe-A negative verification receipt",
    )
    _checksum(receipt, "Probe-A negative verification receipt")
    if receipt["schema"] != NEGATIVE_VERIFICATION_SCHEMA or receipt["protocol"] != PROTOCOL:
        raise ProbeAEvidenceError("Probe-A negative verification receipt identity mismatch")
    if receipt["status"] != "failed":
        raise ProbeAEvidenceError("Probe-A negative verification receipt status must be 'failed'")
    if report.get("status") != "failed":
        raise ProbeAEvidenceError("Probe-A negative verification requires a failed report")
    if _git_commit(receipt["git_commit"], "negative verification git_commit") != _git_commit(
        expected_git_commit, "expected Git commit"
    ):
        raise ProbeAEvidenceError("Probe-A negative verification Git commit mismatch")
    expected_pins = {
        "registration_sha256": _sha(registration_sha256, "registration_sha256"),
        "report_sha256": _sha(report_sha256, "report_sha256"),
        "evidence_manifest_sha256": _sha(evidence_manifest_sha256, "evidence_manifest_sha256"),
        "verifier_code_sha256": _sha(verifier_code_sha256, "verifier_code_sha256"),
    }
    for field, expected in expected_pins.items():
        if _sha(receipt[field], f"negative verification.{field}") != expected:
            raise ProbeAEvidenceError(f"Probe-A negative verification {field} mismatch")
    if sha256_bytes(_canonical_file_bytes(report)) != expected_pins["report_sha256"]:
        raise ProbeAEvidenceError("Probe-A failed report mapping does not match its external pin")

    determinism = _exact_keys(
        report.get("determinism"),
        {"checkpoint_sha256", "prediction_sha256", "max_abs_error", "tolerance", "verdict"},
        "Probe-A failed report determinism",
    )
    control_count = _exact_keys(
        report.get("control_count"),
        {"counts", "prediction_sha256", "first_300_max_abs_error", "tolerance", "verdict"},
        "Probe-A failed report control_count",
    )
    report_bridge = _exact_keys(
        report.get("output_bridge"), _BRIDGE_KEYS, "Probe-A failed report output_bridge"
    )
    gate_verdicts = _exact_keys(
        receipt["gate_verdicts"],
        _GATE_VERDICT_KEYS,
        "Probe-A negative verification gate_verdicts",
    )
    expected_verdicts = {
        "determinism": determinism["verdict"],
        "control_count": control_count["verdict"],
        "output_bridge": report_bridge["verdict"],
    }
    if dict(gate_verdicts) != expected_verdicts:
        raise ProbeAEvidenceError("Probe-A negative verification gate verdicts differ from report")
    if any(value not in {"pass", "fail"} for value in gate_verdicts.values()):
        raise ProbeAEvidenceError("Probe-A negative verification contains an invalid gate verdict")
    if "fail" not in gate_verdicts.values():
        raise ProbeAEvidenceError("Probe-A negative verification contains no failed gate")
    bridge = _exact_keys(
        receipt["output_bridge"], _BRIDGE_KEYS, "Probe-A negative verification output_bridge"
    )
    if dict(bridge) != dict(report_bridge):
        raise ProbeAEvidenceError("Probe-A negative verification output bridge differs from report")


def build_evidence_outputs(
    *,
    report_bytes: bytes,
    report_sha256: str,
    registration_bytes: bytes,
    registration_sha256: str,
    manifest_bytes: bytes,
    evidence_root: str | Path,
    evidence_manifest_sha256: str,
    expected_git_commit: str,
    verifier_code_sha256: str,
) -> ProbeAAdmissionOutputs:
    """Validate all evidence, always emit a receipt, and admit passes only."""
    registration = _json_object_from_bytes(
        registration_bytes,
        expected_sha256=registration_sha256,
        label="registration",
    )
    report = _json_object_from_bytes(
        report_bytes,
        expected_sha256=report_sha256,
        label="report",
    )
    manifest = _json_object_from_bytes(
        manifest_bytes,
        expected_sha256=evidence_manifest_sha256,
        label="evidence manifest",
    )
    validate_evidence_manifest(
        manifest,
        evidence_root=evidence_root,
        expected_git_commit=expected_git_commit,
    )
    validate_probe_a_report(
        report,
        registration=registration,
        registration_sha256=registration_sha256,
        evidence_root=evidence_root,
        expected_git_commit=expected_git_commit,
    )
    assert_report_manifest_binding(
        report,
        manifest,
        report_sha256=report_sha256,
        registration_sha256=registration_sha256,
    )
    validate_evidence_semantics(
        manifest,
        evidence_root=evidence_root,
        expected_git_commit=expected_git_commit,
        registration_sha256=registration_sha256,
    )
    common_verification = {
        "protocol": PROTOCOL,
        "git_commit": expected_git_commit,
        "registration_sha256": _sha(registration_sha256, "registration_sha256"),
        "report_sha256": _sha(report_sha256, "report_sha256"),
        "evidence_manifest_sha256": _sha(evidence_manifest_sha256, "evidence_manifest_sha256"),
        "verifier_code_sha256": _sha(verifier_code_sha256, "verifier_code_sha256"),
        "output_bridge": dict(report["output_bridge"]),
    }
    if report["status"] == "failed":
        verification_body = {
            "schema": NEGATIVE_VERIFICATION_SCHEMA,
            **common_verification,
            "status": "failed",
            "gate_verdicts": {
                "determinism": report["determinism"]["verdict"],
                "control_count": report["control_count"]["verdict"],
                "output_bridge": report["output_bridge"]["verdict"],
            },
        }
    else:
        verification_body = {
            "schema": VERIFICATION_SCHEMA,
            **common_verification,
            "status": "pass",
        }
    verification = {
        **verification_body,
        "self_checksum": self_checksum(verification_body),
    }
    verification_bytes = _canonical_file_bytes(verification)
    verification_sha256 = sha256_bytes(verification_bytes)
    if report["status"] == "failed":
        validate_negative_verification(
            verification,
            report=report,
            report_sha256=report_sha256,
            registration_sha256=registration_sha256,
            evidence_manifest_sha256=evidence_manifest_sha256,
            verifier_code_sha256=verifier_code_sha256,
            expected_git_commit=expected_git_commit,
        )
        return ProbeAAdmissionOutputs(
            verification=verification,
            verification_bytes=verification_bytes,
            verification_sha256=verification_sha256,
            admission=None,
        )

    body = {
        "schema": ADMISSION_SCHEMA,
        "protocol": PROTOCOL,
        "status": "pass",
        "git_commit": expected_git_commit,
        "registration_sha256": _sha(registration_sha256, "registration_sha256"),
        "evidence_manifest_sha256": _sha(evidence_manifest_sha256, "evidence_manifest_sha256"),
        "verification_sha256": verification_sha256,
        "output_bridge": dict(report["output_bridge"]),
    }
    admission = {**body, "self_checksum": self_checksum(body)}
    validate_admission(
        admission,
        registration=registration,
        registration_sha256=registration_sha256,
        verification=verification,
        verification_sha256=verification_sha256,
        expected_git_commit=expected_git_commit,
    )
    return ProbeAAdmissionOutputs(
        verification=verification,
        verification_bytes=verification_bytes,
        verification_sha256=verification_sha256,
        admission=admission,
    )


def build_admission(
    *,
    report_bytes: bytes,
    report_sha256: str,
    registration_bytes: bytes,
    registration_sha256: str,
    manifest_bytes: bytes,
    evidence_root: str | Path,
    evidence_manifest_sha256: str,
    expected_git_commit: str,
    verifier_code_sha256: str,
) -> dict:
    """Compatibility wrapper returning the admission from a fully bound output pair."""
    outputs = build_evidence_outputs(
        report_bytes=report_bytes,
        report_sha256=report_sha256,
        registration_bytes=registration_bytes,
        registration_sha256=registration_sha256,
        manifest_bytes=manifest_bytes,
        evidence_root=evidence_root,
        evidence_manifest_sha256=evidence_manifest_sha256,
        expected_git_commit=expected_git_commit,
        verifier_code_sha256=verifier_code_sha256,
    )
    if outputs.admission is None:
        raise ProbeAEvidenceError(
            "Probe-A failed; negative receipt verified but admission is forbidden"
        )
    return outputs.admission


def validate_admission(
    payload: Mapping,
    *,
    registration: Mapping,
    registration_sha256: str,
    verification: Mapping,
    verification_sha256: str,
    expected_git_commit: str,
) -> None:
    """Validate admission, registration and receipt via the consumer contract."""
    try:
        validate_probe_a_evidence(
            payload,
            registration=registration,
            registration_sha256=registration_sha256,
            verification=verification,
            verification_sha256=verification_sha256,
            expected_git_commit=expected_git_commit,
        )
    except ApproximationBiasValidationError as exc:
        raise ProbeAEvidenceError(str(exc)) from exc
