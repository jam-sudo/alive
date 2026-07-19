# scripts/baselines/gears_worker.py
"""Real GEARS deep-baseline worker with a frozen, offline fit contract.

COMPLETE contract surface for the fit-role-only subprocess protocol: reads +
validates the fit-role artifact (the SEALED requested pairs enter ONLY as
``sealed_pair_ids`` to the leakage guard — never as fit rows), delegates the
model fit + prediction to :func:`_fit_and_predict`, and returns the
``{predictions, execution_manifest}`` envelope with real digests.

``_fit_and_predict`` is import-guarded: on a host without the pinned ``gears``
package it raises :class:`WorkerUnavailable`; in the registered environment it
fits GEARS from the verified fit-role snapshot and predicts each requested pair.
This worker opens no seal and reads no sealed outcome. Exact pin: GEARS
``cell-gears==0.1.2``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import random
import stat
import sys
import tempfile
from pathlib import Path
from typing import Callable, Mapping

import anndata as ad
import numpy as np

from alive.compose.approximation_bias import PROBE_A_REPRESENTATION
from alive.compose.baseline_subprocess import (
    canonical_payload_sha256,
    read_payload,
    write_predictions,
)
from alive.compose.fit_role import (
    FitRoleArtifactSpec,
    apply_response_projection,
    canonical_gene_order_sha256,
    read_verified_fit_role_artifact,
    validate_fit_role_artifact,
)
from alive.compose.worker_identity import (
    VerifiedWorkerIdentity,
    load_verified_worker_identity,
    require_distribution_version,
    require_exact_worker_config,
    require_module_from_environment,
)
from alive.provenance import sha256_json

# Published GEARS defaults for K562 Perturb-seq (plan decision #1; GEARS paper /
# repo defaults). Named constants, not tuned knobs — no outcome or environment
# variable selects or weakens any of these at worker runtime.
_GEARS_HIDDEN_SIZE = 64
_GEARS_NUM_GO_GNN_LAYERS = 1
_GEARS_NUM_GENE_GNN_LAYERS = 1
_GEARS_DECODER_HIDDEN_SIZE = 16
_GEARS_NUM_SIMILAR_GENES_GO_GRAPH = 20
_GEARS_NUM_SIMILAR_GENES_COEXPRESS_GRAPH = 20
_GEARS_COEXPRESS_THRESHOLD = 0.4
_GEARS_UNCERTAINTY = False
_GEARS_UNCERTAINTY_REG = 1.0
_GEARS_DIRECTION_LAMBDA = 0.1
_GEARS_NO_PERTURB = False
_GEARS_EPOCHS = 20
_GEARS_LEARNING_RATE = 1e-3
_GEARS_WEIGHT_DECAY = 5e-4
_GEARS_OPTIMIZER = "Adam"
_GEARS_SCHEDULER = "StepLR(step_size=1,gamma=0.5)"
_GEARS_GRADIENT_CLIP_VALUE = 1.0
_GEARS_MODEL_SELECTION_POLICY = "fixed_final_epoch"
_GEARS_MONITORING_POLICY = "deterministic_training_subset_no_holdout"
_GEARS_UPSTREAM_BEST_MODEL_METRIC = "monitoring_mse_de_ignored"
_GEARS_PREDICTION_CONTROL_BATCH_SIZE = 300
_GEARS_PREDICTION_RNG_POLICY = "sha256(payload_seed,canonical_pair)"
_GEARS_BATCH_SIZE = 32
_GEARS_TEST_BATCH_SIZE = 128
_GEARS_VALIDATION_FRACTION = 0.10
_GEARS_PACKAGE = "cell-gears"
_GEARS_PACKAGE_VERSION = "0.1.2"
_GEARS_DEVICE_POLICY = "cuda_required"
_GEARS_NUMERIC_PRECISION = "float32"
_GEARS_DETERMINISTIC_ALGORITHMS = True
_GEARS_MODULE_ORIGIN_POLICY = "regular_non_symlink_under_sys_prefix"
_GEARS_CUBLAS_WORKSPACE_CONFIG = ":4096:8"
_GEARS_PYTHON_HASH_SEED_SOURCE = "payload_seed"
_GEARS_PREDICTION_REPRESENTATION = "raw_pseudobulk_approximation"
_GEARS_LOCK_RELATIVE_PATH = "docs/activation-evidence/compose/requirements.gears_env.lock"
_CONTROL_TOKEN = "control"
_COMBO_SEP = "_"

# Deliberately do not silently normalize or reduce the registered full-gene raw
# artifact in this worker.  The present raw-input path is useful for compatibility
# plumbing, but it is NOT a release claim that raw counts reproduce the published
# GEARS preprocessing.  Scientific activation remains blocked until the registered
# worker config settles that scale/universe decision and binds it into CONFIG_SHA256.
_GEARS_NATIVE_INPUT_SCALE = "raw_counts"
_GEARS_NATIVE_INPUT_SCALE_STATUS = "ACTIVATION_BLOCKED_PENDING_PUBLISHED_SCALE_DECISION"

_RESOURCE_MANIFEST_ENV = "ALIVE_WORKER_RESOURCE_MANIFEST_PATH"
_RESOURCE_SHA_ENV = "ALIVE_WORKER_RESOURCE_SHA256"
_REQUIRED_RESOURCE_NAMES = frozenset(
    {
        "gene2go_all.pkl",
        "essential_all_data_pert_genes.pkl",
        "go_essential_all.tar.gz",
    }
)
_EXTRACTED_GO_PATH = "go_essential_all/go_essential_all.csv"


def verify_probe_runtime_identity(*, expected_gears_lock_sha256: str) -> str:
    """Verify the complete installed GEARS environment against its committed lock.

    Returns the canonical installed-package-roster digest embedded in Probe-A raw
    evidence and checkpoints. This is intentionally stricter than checking only
    ``cell-gears`` and ``torch`` because a transitive numerical-stack drift can
    change preprocessing or prediction behavior.
    """
    if not _is_sha256(expected_gears_lock_sha256):
        raise ValueError("Probe-A requires a lowercase GEARS lock SHA-256")
    lock_path = Path(__file__).resolve().parents[2] / _GEARS_LOCK_RELATIVE_PATH
    try:
        lock_bytes = lock_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read committed GEARS lock: {exc}") from exc
    if hashlib.sha256(lock_bytes).hexdigest() != expected_gears_lock_sha256:
        raise ValueError("committed GEARS lock differs from the externally bound identity")
    try:
        lines = lock_bytes.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("committed GEARS lock is not UTF-8") from exc
    expected: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if line.count("==") != 1:
            raise ValueError("committed GEARS lock contains an unsupported requirement")
        distribution, version = line.split("==", 1)
        if not distribution or not version or distribution in expected:
            raise ValueError("committed GEARS lock contains an invalid/duplicate requirement")
        expected[distribution] = version
    if not expected:
        raise ValueError("committed GEARS lock is empty")
    installed: dict[str, str] = {}
    for distribution, expected_version in sorted(expected.items()):
        try:
            observed_version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError(
                f"GEARS environment is missing locked distribution {distribution}"
            ) from exc
        if observed_version != expected_version:
            raise ValueError(
                f"GEARS environment distribution drift: {distribution} "
                f"expected={expected_version} observed={observed_version}"
            )
        installed[distribution] = observed_version
    return sha256_json(installed)


def _registered_worker_config(adapter_version: str) -> dict[str, object]:
    """Return the exact JSON config implemented by this worker body."""
    return {
        "schema": "compose_deep_worker_config_v1",
        "method": "gears",
        "adapter_version": adapter_version,
        "prediction_representation": _GEARS_PREDICTION_REPRESENTATION,
        "training": {
            "schema": "compose_gears_worker_config_v1",
            "package": _GEARS_PACKAGE,
            "package_version": _GEARS_PACKAGE_VERSION,
            "device_policy": _GEARS_DEVICE_POLICY,
            "numeric_precision": _GEARS_NUMERIC_PRECISION,
            "deterministic_algorithms": _GEARS_DETERMINISTIC_ALGORITHMS,
            "module_origin_policy": _GEARS_MODULE_ORIGIN_POLICY,
            "cublas_workspace_config": _GEARS_CUBLAS_WORKSPACE_CONFIG,
            "python_hash_seed_source": _GEARS_PYTHON_HASH_SEED_SOURCE,
            "hidden_size": _GEARS_HIDDEN_SIZE,
            "num_go_gnn_layers": _GEARS_NUM_GO_GNN_LAYERS,
            "num_gene_gnn_layers": _GEARS_NUM_GENE_GNN_LAYERS,
            "decoder_hidden_size": _GEARS_DECODER_HIDDEN_SIZE,
            "num_similar_genes_go_graph": _GEARS_NUM_SIMILAR_GENES_GO_GRAPH,
            "num_similar_genes_co_express_graph": _GEARS_NUM_SIMILAR_GENES_COEXPRESS_GRAPH,
            "coexpress_threshold": _GEARS_COEXPRESS_THRESHOLD,
            "uncertainty": _GEARS_UNCERTAINTY,
            "uncertainty_reg": _GEARS_UNCERTAINTY_REG,
            "direction_lambda": _GEARS_DIRECTION_LAMBDA,
            "no_perturb": _GEARS_NO_PERTURB,
            "epochs": _GEARS_EPOCHS,
            "learning_rate": _GEARS_LEARNING_RATE,
            "weight_decay": _GEARS_WEIGHT_DECAY,
            "optimizer": _GEARS_OPTIMIZER,
            "scheduler": _GEARS_SCHEDULER,
            "gradient_clip_value": _GEARS_GRADIENT_CLIP_VALUE,
            "model_selection_policy": _GEARS_MODEL_SELECTION_POLICY,
            "monitoring_policy": _GEARS_MONITORING_POLICY,
            "upstream_best_model_metric": _GEARS_UPSTREAM_BEST_MODEL_METRIC,
            "prediction_control_batch_size": _GEARS_PREDICTION_CONTROL_BATCH_SIZE,
            "prediction_rng_policy": _GEARS_PREDICTION_RNG_POLICY,
            "batch_size": _GEARS_BATCH_SIZE,
            "validation_batch_size": _GEARS_TEST_BATCH_SIZE,
            "validation_fraction": _GEARS_VALIDATION_FRACTION,
            "split_policy": "deterministic_within_condition_cell_level",
            "optimization_roles": ["singles", "combo_calibration"],
            "control_optimization": "reference_only",
            "native_input_scale": _GEARS_NATIVE_INPUT_SCALE,
            "native_input_scale_status": _GEARS_NATIVE_INPUT_SCALE_STATUS,
            "negative_prediction_policy": "clip_zero_before_response_projection",
        },
    }


def _verify_runtime_identity(representation: str) -> VerifiedWorkerIdentity:
    """Re-hash controller artifacts and bind config bytes to code semantics."""
    identity = load_verified_worker_identity(method="gears")
    require_exact_worker_config(
        identity,
        expected=_registered_worker_config(identity.adapter_version),
    )
    if representation != _GEARS_PREDICTION_REPRESENTATION:
        raise ValueError(
            "GEARS prediction representation diverges from the registered "
            "raw_pseudobulk_approximation contract"
        )
    return identity


class WorkerUnavailable(RuntimeError):
    """Raised when the pinned ``gears`` backend is absent."""


def _is_sha256(value: object) -> bool:
    """Return whether ``value`` is an exact bare lowercase SHA-256."""
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Return file-identity fields that must remain stable while streaming."""
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _write_all(fd: int, data: bytes) -> None:
    """Write every byte to ``fd`` even when the OS performs a short write."""
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write while snapshotting GEARS resource")
        view = view[written:]


def _stream_verified_regular_file(
    path: Path,
    *,
    expected_sha256: str,
    expected_bytes: int | None,
    label: str,
    destination_fd: int | None = None,
    capture_bytes: bool = False,
) -> tuple[Path, bytes | None]:
    """Verify one stable source descriptor, optionally copying/capturing its bytes."""
    if destination_fd is not None and capture_bytes:
        raise ValueError("cannot both copy and capture a GEARS resource stream")
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} path must be absolute and normalized")
    try:
        before = path.lstat()
    except OSError as exc:
        raise ValueError(f"cannot stat {label}: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError(f"{label} must be a non-symlink regular file")
    if expected_bytes is not None and (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or before.st_size != expected_bytes
    ):
        raise ValueError(f"{label} byte count differs from its manifest")
    if not _is_sha256(expected_sha256):
        raise ValueError(f"{label} manifest SHA-256 is malformed")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"cannot open {label}: {exc}") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or _stat_signature(before) != _stat_signature(opened):
            raise ValueError(f"{label} descriptor is not a stable regular file")
        digest = hashlib.sha256()
        captured: list[bytes] | None = [] if capture_bytes else None
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            if destination_fd is not None:
                _write_all(destination_fd, chunk)
            if captured is not None:
                captured.append(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if _stat_signature(opened) != _stat_signature(after):
        raise ValueError(f"{label} identity changed while hashing")
    if digest.hexdigest() != expected_sha256:
        raise ValueError(f"{label} SHA-256 differs from its manifest")
    return path.absolute(), b"".join(captured) if captured is not None else None


def _read_verified_regular_file(
    path: Path,
    *,
    expected_sha256: str,
    expected_bytes: int | None,
    label: str,
) -> tuple[Path, bytes]:
    """Read bytes from the same descriptor whose identity and digest are verified."""
    verified, content = _stream_verified_regular_file(
        path,
        expected_sha256=expected_sha256,
        expected_bytes=expected_bytes,
        label=label,
        capture_bytes=True,
    )
    assert content is not None
    return verified, content


def _snapshot_verified_regular_file(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
    label: str,
) -> Path:
    """Copy the exact verified source stream into a fresh read-only regular file."""
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        destination_fd = os.open(destination, flags, 0o400)
    except OSError as exc:
        raise ValueError(f"cannot create {label} snapshot: {exc}") from exc
    try:
        _stream_verified_regular_file(
            source,
            expected_sha256=expected_sha256,
            expected_bytes=expected_bytes,
            label=label,
            destination_fd=destination_fd,
        )
        os.fsync(destination_fd)
    except Exception:
        os.close(destination_fd)
        destination.unlink(missing_ok=True)
        raise
    else:
        os.close(destination_fd)
    return destination


def _write_exclusive_snapshot(path: Path, content: bytes, *, label: str) -> Path:
    """Write already-verified bytes as a fresh read-only snapshot file."""
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(path, flags, 0o400)
    except OSError as exc:
        raise ValueError(f"cannot create {label} snapshot: {exc}") from exc
    try:
        _write_all(fd, content)
        os.fsync(fd)
    except Exception:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    else:
        os.close(fd)
    return path


def _safe_bundle_file(bundle_root: Path, relative: str, *, label: str) -> Path:
    """Resolve a manifest-relative file without permitting bundle escape."""
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"{label} must be a safe path relative to the resource manifest")
    root = bundle_root.resolve(strict=True)
    candidate = bundle_root / rel
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"cannot resolve {label}: {exc}") from exc
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} escapes the resource bundle")
    return candidate.absolute()


def _validate_gears_resource_bundle() -> dict[str, object]:
    """Read the controller-bound GEARS manifest through one verified descriptor.

    Resource paths are resolved here, but each resource is validated while it is
    copied into the fit snapshot by :func:`_stage_gears_resource_bundle`. This
    closes the validation-to-use race: GEARS never consumes the source pathname.
    """
    raw_manifest_path = os.environ.get(_RESOURCE_MANIFEST_ENV)
    expected_manifest_sha = os.environ.get(_RESOURCE_SHA_ENV)
    if not raw_manifest_path or not expected_manifest_sha:
        raise ValueError(
            f"GEARS requires {_RESOURCE_MANIFEST_ENV} and {_RESOURCE_SHA_ENV}; "
            "fit-time resource download/substitution is forbidden"
        )
    manifest_path = Path(raw_manifest_path)
    if not manifest_path.is_absolute():
        raise ValueError(f"{_RESOURCE_MANIFEST_ENV} must be an absolute path")
    manifest_source, manifest_bytes = _read_verified_regular_file(
        manifest_path,
        expected_sha256=expected_manifest_sha,
        expected_bytes=None,
        label="GEARS resource manifest",
    )
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"cannot read GEARS resource manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("GEARS resource manifest must be a JSON object")
    if manifest.get("schema") != "compose_go_resource_manifest_v2":
        raise ValueError("GEARS resource manifest schema mismatch")
    if manifest.get("protocol") != "COMPOSE-K562-v1":
        raise ValueError("GEARS resource manifest protocol mismatch")
    checksum = manifest.get("manifest_checksum")
    body = {key: value for key, value in manifest.items() if key != "manifest_checksum"}
    if not _is_sha256(checksum) or checksum != sha256_json(body):
        raise ValueError("GEARS resource manifest checksum mismatch")

    resources = manifest.get("resources")
    if not isinstance(resources, list):
        raise ValueError("GEARS resource manifest resources must be a list")
    by_name: dict[str, dict] = {}
    for resource in resources:
        if not isinstance(resource, dict) or not isinstance(resource.get("name"), str):
            raise ValueError("GEARS resource manifest contains a malformed resource")
        name = resource["name"]
        if name in by_name:
            raise ValueError(f"GEARS resource manifest contains duplicate {name!r}")
        by_name[name] = resource
    if set(by_name) != set(_REQUIRED_RESOURCE_NAMES):
        raise ValueError("GEARS resource manifest has an unexpected resource roster")

    bundle_root = manifest_source.parent.resolve(strict=True)
    source_files: list[tuple[Path, int, str, str]] = []
    for name in sorted(_REQUIRED_RESOURCE_NAMES):
        resource = by_name[name]
        byte_count = resource.get("bytes")
        digest = resource.get("sha256")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise ValueError(f"GEARS resource {name} has a malformed byte count")
        if not _is_sha256(digest):
            raise ValueError(f"GEARS resource {name} has a malformed SHA-256")
        source = _safe_bundle_file(bundle_root, name, label=f"GEARS resource {name}")
        source_files.append((source, byte_count, digest, name))

    archive = by_name["go_essential_all.tar.gz"]
    extracted = archive.get("extracted_artifact")
    if not isinstance(extracted, dict) or extracted.get("name") != _EXTRACTED_GO_PATH:
        raise ValueError("GEARS extracted GO artifact contract mismatch")
    extracted_bytes = extracted.get("bytes")
    extracted_sha256 = extracted.get("sha256")
    if (
        isinstance(extracted_bytes, bool)
        or not isinstance(extracted_bytes, int)
        or extracted_bytes < 0
    ):
        raise ValueError("GEARS extracted GO artifact has a malformed byte count")
    if not _is_sha256(extracted_sha256):
        raise ValueError("GEARS extracted GO artifact has a malformed SHA-256")
    extracted_source = _safe_bundle_file(
        bundle_root,
        _EXTRACTED_GO_PATH,
        label="GEARS extracted GO CSV",
    )
    source_files.append(
        (
            extracted_source,
            extracted_bytes,
            extracted_sha256,
            _EXTRACTED_GO_PATH,
        )
    )
    return {
        "manifest_source": manifest_source,
        "manifest_bytes": manifest_bytes,
        "manifest_sha256": expected_manifest_sha,
        "bundle_root": bundle_root,
        "source_files": tuple(source_files),
    }


def _revalidate_gears_resource_bundle(bundle: dict[str, object]) -> None:
    """Recheck every regular file in the isolated GEARS snapshot."""
    manifest_path = Path(bundle["manifest_path"])
    _stream_verified_regular_file(
        manifest_path,
        expected_sha256=str(bundle["manifest_sha256"]),
        expected_bytes=int(bundle["manifest_bytes"]),
        label="GEARS resource manifest",
    )
    for path, byte_count, digest, name in bundle["files"]:
        _stream_verified_regular_file(
            Path(path),
            expected_sha256=str(digest),
            expected_bytes=int(byte_count),
            label=f"GEARS resource {name}",
        )


def _stage_gears_resource_bundle(bundle: dict[str, object], work_dir: str) -> dict[str, object]:
    """Copy exact verified streams into an isolated regular-file snapshot."""
    work = Path(work_dir)
    if not work.is_absolute() or not work.is_dir() or any(work.iterdir()):
        raise ValueError("GEARS resource snapshot destination must be a fresh empty directory")
    manifest_bytes = bytes(bundle["manifest_bytes"])
    manifest_path = _write_exclusive_snapshot(
        work / "go_resource_manifest.json",
        manifest_bytes,
        label="GEARS resource manifest",
    )
    extracted_dir = work / "go_essential_all"
    extracted_dir.mkdir(mode=0o700)

    snapshot_files: list[tuple[Path, int, str, str]] = []
    for source, byte_count, digest, name in bundle["source_files"]:
        destination = work / str(name)
        snapshot = _snapshot_verified_regular_file(
            Path(source),
            destination,
            expected_sha256=str(digest),
            expected_bytes=int(byte_count),
            label=f"GEARS resource {name}",
        )
        snapshot_files.append((snapshot, int(byte_count), str(digest), str(name)))
    extracted_dir.chmod(0o500)
    snapshot_bundle = {
        "manifest_path": manifest_path,
        "manifest_sha256": bundle["manifest_sha256"],
        "manifest_bytes": len(manifest_bytes),
        "files": tuple(snapshot_files),
    }
    _revalidate_gears_resource_bundle(snapshot_bundle)
    return snapshot_bundle


def _install_deterministic_cell_split(pert_data, *, seed: int, dataloader_cls) -> dict:
    """Install all fit graphs for training plus a monitoring-only subset.

    GEARS requires a ``val_loader`` and internally tracks a best validation model.
    Withheld-cell preprocessing is not independent because cell-gears constructs
    DE/nonzero metadata and coexpression graphs before loaders exist. Therefore no
    outcome is mislabeled as an independent validation holdout: every governed
    non-control graph enters TRAIN, and a deterministic duplicated subset is used
    for monitoring only. The worker later checkpoints/predicts the fixed final-epoch
    model, never GEARS' validation-selected ``best_model``.
    """
    processed = getattr(pert_data, "dataset_processed", None)
    if not isinstance(processed, dict):
        raise ValueError("GEARS did not expose its processed per-condition cell graphs")
    normalized: dict[str, object] = {}
    for raw_condition, graphs in processed.items():
        condition = str(raw_condition)
        if condition in normalized:
            raise ValueError(f"GEARS processed duplicate normalized condition {condition!r}")
        normalized[condition] = graphs
    observed_conditions = {
        str(condition) for condition in pert_data.adata.obs["condition"].astype(str).unique()
    }
    if set(normalized) != observed_conditions:
        raise ValueError("GEARS processed condition roster differs from the fit-role artifact")
    if "ctrl" not in normalized:
        raise ValueError("GEARS fit-role artifact is missing the required control reference")
    conditions = sorted(
        (condition for condition in normalized if condition != "ctrl"),
        key=lambda value: value.encode("utf-8"),
    )
    if not conditions:
        raise ValueError("GEARS fit requires at least one non-control perturbation condition")

    rng = np.random.default_rng(int(seed))
    train_graphs: list[object] = []
    val_graphs: list[object] = []
    split_counts: dict[str, dict[str, int]] = {}
    for condition in conditions:
        graphs = list(normalized[condition])
        if not graphs:
            raise ValueError(f"GEARS condition {condition!r} contains no processed cell graph")
        order = rng.permutation(len(graphs))
        n_monitoring = max(1, int(round(len(graphs) * _GEARS_VALIDATION_FRACTION)))
        n_monitoring = min(n_monitoring, len(graphs))
        monitoring = [graphs[int(position)] for position in order[:n_monitoring]]
        train_graphs.extend(graphs)
        val_graphs.extend(monitoring)
        split_counts[condition] = {
            "train": len(graphs),
            "monitoring_duplicate": len(monitoring),
        }

    if len(train_graphs) < _GEARS_BATCH_SIZE:
        raise ValueError("GEARS train split is smaller than the registered batch size")
    pert_data.split = "custom"
    pert_data.seed = int(seed)
    pert_data.train_gene_set_size = 1.0
    pert_data.set2conditions = {"train": list(conditions), "val": list(conditions)}
    gene_names = [str(gene) for gene in pert_data.adata.var["gene_name"]]
    if not gene_names or len(set(gene_names)) != len(gene_names):
        raise ValueError("GEARS processed gene roster is empty or non-unique")
    # PertData.get_dataloader normally installs these two attributes. We build
    # cell-level loaders directly, so install the same model-facing state here.
    pert_data.node_map = {gene: index for index, gene in enumerate(gene_names)}
    pert_data.gene_names = pert_data.adata.var["gene_name"]
    pert_data.dataloader = {
        "train_loader": dataloader_cls(
            train_graphs,
            batch_size=_GEARS_BATCH_SIZE,
            shuffle=True,
            drop_last=True,
        ),
        "val_loader": dataloader_cls(
            val_graphs,
            batch_size=_GEARS_TEST_BATCH_SIZE,
            shuffle=False,
        ),
    }
    return {
        "schema": "compose_gears_training_loaders_v1",
        "seed": int(seed),
        "monitoring_fraction": _GEARS_VALIDATION_FRACTION,
        "model_selection_policy": _GEARS_MODEL_SELECTION_POLICY,
        "monitoring_policy": _GEARS_MONITORING_POLICY,
        "conditions": split_counts,
        "control_in_optimization_loaders": False,
    }


def _seed_gears_runtime(torch_module, seed: int) -> None:
    """Bind Python, NumPy and Torch RNGs to the registered payload seed."""
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != _GEARS_CUBLAS_WORKSPACE_CONFIG:
        raise WorkerUnavailable("GEARS CUBLAS workspace configuration is not registered")
    if os.environ.get("PYTHONHASHSEED") != str(int(seed)):
        raise WorkerUnavailable("GEARS PYTHONHASHSEED does not match the payload seed")
    random.seed(int(seed))
    np.random.seed(int(seed))
    torch_module.manual_seed(int(seed))
    if not torch_module.cuda.is_available():
        raise WorkerUnavailable("GEARS registered execution requires CUDA")
    torch_module.cuda.manual_seed_all(int(seed))
    deterministic = getattr(torch_module, "use_deterministic_algorithms", None)
    if not callable(deterministic):
        raise WorkerUnavailable("GEARS runtime lacks deterministic-algorithm enforcement")
    deterministic(True)
    cudnn = getattr(getattr(torch_module, "backends", None), "cudnn", None)
    if cudnn is not None:
        cudnn.deterministic = True
        cudnn.benchmark = False


def _pair_prediction_seed(seed: int, pair: tuple[str, str]) -> int:
    """Derive an order-independent 32-bit prediction seed for one canonical pair."""
    material = json.dumps(
        {"seed": int(seed), "pair": list(pair)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big")


def _predict_pairs_order_independent(model, requests: list[list[str]], *, seed: int, torch_module):
    """Predict each pair under its own derived RNG state, preserving request order."""
    predictions: dict[str, np.ndarray] = {}
    for request in requests:
        pair = (str(request[0]), str(request[1]))
        pair_seed = _pair_prediction_seed(seed, pair)
        random.seed(pair_seed)
        np.random.seed(pair_seed)
        torch_module.manual_seed(pair_seed)
        torch_module.cuda.manual_seed_all(pair_seed)
        one = model.predict([list(pair)])
        expected_key = f"{pair[0]}_{pair[1]}"
        if not isinstance(one, dict) or set(one) != {expected_key}:
            raise ValueError(f"GEARS prediction roster differs for pair {pair!r}")
        predictions[expected_key] = one[expected_key]
    return predictions


def _fit_perturbation_gene_roster(tokens: list[str]) -> set[str]:
    """Return every non-control gene component present in governed fit rows."""
    genes: set[str] = set()
    for token in tokens:
        if token == _CONTROL_TOKEN:
            continue
        parts = token.split(_COMBO_SEP, 1)
        if not all(parts) or len(parts) not in {1, 2}:
            raise ValueError(f"GEARS fit perturbation token is malformed: {token!r}")
        genes.update(parts)
    if not genes:
        raise ValueError("GEARS fit artifact contains no perturbation genes")
    return genes


def _require_fit_genes_in_gears_roster(
    fit_genes: set[str],
    observed_roster,
    *,
    field: str,
) -> set[str]:
    """Reject GEARS' silent ``pert_idx=-1`` fallback for any governed fit gene."""
    try:
        raw_roster = [str(gene) for gene in observed_roster]
    except TypeError as exc:
        raise ValueError(f"GEARS {field} is not an iterable gene roster") from exc
    observed = set(raw_roster)
    if not observed or len(observed) != len(raw_roster):
        raise ValueError(f"GEARS {field} is empty or non-unique")
    missing = fit_genes - observed
    if missing:
        raise ValueError(f"GEARS {field} omits governed fit gene(s): {sorted(missing)}")
    return observed


def _fit_and_predict(
    payload: dict,
    adata: ad.AnnData,
    proj: dict,
    gene_order: list[str],
    representation: str,
    *,
    fit_artifact_content_sha256: str | None = None,
    checkpoint_path: str | None = None,
    fitted_model_observer: Callable[..., None] | None = None,
    observer_only: bool = False,
    input_scale: str = _GEARS_NATIVE_INPUT_SCALE,
    probe_context: Mapping[str, str] | None = None,
) -> dict[tuple[str, str], np.ndarray]:
    """Fit real GEARS and predict each requested pair's response-space delta.

    The implementation uses only fit roles (control + singles +
    combo_calibration); sealed requested pairs are never fit rows.  It must:

    1. consume the already verified, in-memory fit-role ``AnnData`` from ``main``;
    2. fit GEARS on those rows using only pre-acquired, hash-verified resources;
    3. predict each ``payload["pair_ids"]`` pair's native full-gene expression;
    4. map native -> response space with ``apply_response_projection`` honoring
       ``representation`` (scientific ``raw_pseudobulk_approximation`` ->
       ``native.mean(axis=0, keepdims=True)``; ``cell_*`` -> ``native``), then
       ``delta = mean(z) - control_mean``;
    5. return ``{pair: delta[:response_dim]}`` over ``payload["pair_ids"]``.

    Returns
    -------
    dict
        Mapping from each requested canonical pair to its length-``response_dim``
        response-space prediction vector.

    Raises
    ------
    WorkerUnavailable
        If the pinned ``gears`` package is not installed.
    ValueError
        If the registered resource bundle, deterministic split, checkpoint path,
        or prediction roster violates the frozen worker contract.
    """
    probe_input_scale = "full_library_normalize_log1p_then_roster_subset"
    expected_probe_context_keys = {
        "gears_dependency_lock_sha256",
        "gears_installed_packages_sha256",
        "mode",
        "input_scale_sha256",
        "probe_input_h5ad_sha256",
        "query_sha256",
        "registration_sha256",
        "worker_code_sha256",
    }
    if observer_only:
        if (
            fitted_model_observer is None
            or input_scale != probe_input_scale
            or not isinstance(probe_context, Mapping)
            or set(probe_context) != expected_probe_context_keys
            or probe_context["mode"] != "probe_a"
            or any(
                not _is_sha256(probe_context[field])
                for field in expected_probe_context_keys - {"mode"}
            )
        ):
            raise ValueError(
                "observer-only Probe A requires its observer, normalized input scale, "
                "and complete checkpoint context"
            )
        observed_packages_sha256 = verify_probe_runtime_identity(
            expected_gears_lock_sha256=probe_context["gears_dependency_lock_sha256"]
        )
        if observed_packages_sha256 != probe_context["gears_installed_packages_sha256"]:
            raise ValueError("Probe-A installed-package roster changed before GEARS fitting")
    elif (
        fitted_model_observer is not None
        or probe_context is not None
        or input_scale != _GEARS_NATIVE_INPUT_SCALE
    ):
        raise ValueError(
            "scientific GEARS execution forbids observers/probe context/input-scale overrides"
        )

    try:
        import gears.pertdata as gears_pertdata
        import gears.utils as gears_utils
        import torch
        from gears import GEARS, PertData
        from torch_geometric.loader import DataLoader
    except ImportError as exc:
        raise WorkerUnavailable("pinned cell-gears backend is not installed") from exc
    require_distribution_version(
        distribution=_GEARS_PACKAGE,
        expected=_GEARS_PACKAGE_VERSION,
    )
    require_module_from_environment(sys.modules["gears"], expected_name="gears")

    import pandas as pd
    from scipy import sparse

    if not isinstance(checkpoint_path, str) or not checkpoint_path:
        raise ValueError("GEARS requires an explicit trained-model checkpoint path")
    if not _is_sha256(fit_artifact_content_sha256):
        raise ValueError("GEARS requires the verified fit artifact content SHA-256")
    expected_representation = (
        PROBE_A_REPRESENTATION if observer_only else _GEARS_PREDICTION_REPRESENTATION
    )
    if representation != expected_representation:
        raise ValueError(
            "GEARS representation differs from the mode-locked scientific/Probe-A contract"
        )
    if os.path.lexists(checkpoint_path):
        raise ValueError("GEARS checkpoint path already exists")

    seed = int(payload["seed"])
    _seed_gears_runtime(torch, seed)

    # The AnnData object was read through a stable verified descriptor in ``main``.
    # Never reopen ``fit_role['path']`` here: the model trains on this exact snapshot.
    art_genes = [str(v) for v in adata.var_names]
    if art_genes != list(gene_order):
        raise ValueError("fit-role artifact gene order diverges from the observed gene order")
    tokens = [str(p) for p in adata.obs["perturbation"]]
    fit_perturbation_genes = _fit_perturbation_gene_roster(tokens)

    # 2. build a GEARS-format AnnData: raw counts, GEARS condition naming
    #    (ctrl / GENE+ctrl / GENEA+GENEB), gene_name var column, cell_type obs.
    def _condition(token: str) -> str:
        if token == _CONTROL_TOKEN:
            return "ctrl"
        if _COMBO_SEP in token:
            a, b = token.split(_COMBO_SEP, 1)
            return f"{a}+{b}"
        return f"{token}+ctrl"

    conditions = [_condition(t) for t in tokens]
    if observer_only:
        # Probe-A only: carry the source-row identity into the GEARS AnnData index so
        # the observer can bind processed control-row order to the prepared input.  The
        # scientific caller keeps the original positional index below, so its GEARS
        # input matrix and predictions are numerically byte-identical to before.
        required_identity_columns = {"source_row_id", "role"}
        if not required_identity_columns <= set(adata.obs.columns):
            raise ValueError("fit-role artifact lacks source_row_id/role identity columns")
        source_row_ids = adata.obs["source_row_id"].astype(str).tolist()
        if any(not row_id for row_id in source_row_ids) or len(set(source_row_ids)) != len(
            source_row_ids
        ):
            raise ValueError("fit-role source_row_id values must be non-empty and unique")
        gears_obs = pd.DataFrame(
            {
                "condition": pd.Categorical(conditions),
                "cell_type": pd.Categorical(["K562"] * len(conditions)),
                "source_row_id": source_row_ids,
                "role": adata.obs["role"].astype(str).tolist(),
            },
            index=source_row_ids,
        )
    else:
        gears_obs = pd.DataFrame(
            {
                "condition": pd.Categorical(conditions),
                "cell_type": pd.Categorical(["K562"] * len(conditions)),
            },
            index=[str(s) for s in adata.obs_names],
        )
    gears_var = pd.DataFrame({"gene_name": art_genes}, index=art_genes)
    gears_adata = ad.AnnData(
        X=sparse.csr_matrix(adata.X, dtype="float32"), obs=gears_obs, var=gears_var
    )

    bundle = _validate_gears_resource_bundle()
    with tempfile.TemporaryDirectory(prefix="compose_gears_") as work:
        snapshot_bundle = _stage_gears_resource_bundle(bundle, work)
        snapshot_by_path = {
            os.path.abspath(os.fspath(path)): (int(byte_count), str(digest), str(name))
            for path, byte_count, digest, name in snapshot_bundle["files"]
        }

        # Refuse every package-internal download path. A guard returns only for the
        # exact read-only snapshot path and rechecks its bytes before GEARS opens it.
        def _verify_snapshot_file(save_path) -> None:
            candidate = os.path.abspath(os.fspath(save_path))
            spec = snapshot_by_path.get(candidate)
            if spec is None:
                raise RuntimeError("GEARS attempted an unmanifested fit-time resource access")
            byte_count, digest, name = spec
            _stream_verified_regular_file(
                Path(candidate),
                expected_sha256=digest,
                expected_bytes=byte_count,
                label=f"GEARS snapshot resource {name}",
            )

        def _offline_file_guard(_url, save_path, *_args, **_kwargs):
            _verify_snapshot_file(save_path)
            return None

        def _offline_archive_guard(_url, save_path, data_path, *_args, **_kwargs):
            if os.path.abspath(os.fspath(save_path)) != os.path.join(work, "go_essential_all"):
                raise RuntimeError("GEARS attempted a forbidden fit-time archive download")
            if os.path.abspath(os.fspath(data_path)) != work:
                raise RuntimeError("GEARS attempted a forbidden archive destination")
            _verify_snapshot_file(os.path.join(save_path, "go_essential_all.csv"))
            return None

        def _offline_zip_guard(*_args, **_kwargs):
            raise RuntimeError("GEARS attempted a forbidden fit-time zip download")

        for module in (gears_pertdata, gears_utils):
            if hasattr(module, "dataverse_download"):
                module.dataverse_download = _offline_file_guard
            if hasattr(module, "tar_data_download_wrapper"):
                module.tar_data_download_wrapper = _offline_archive_guard
            if hasattr(module, "zip_data_download_wrapper"):
                module.zip_data_download_wrapper = _offline_zip_guard

        pert_data = PertData(work)
        pert_data.new_data_process("compose_fit_role", adata=gears_adata)
        _require_fit_genes_in_gears_roster(
            fit_perturbation_genes,
            getattr(pert_data, "pert_names", None),
            field="PertData.pert_names",
        )

        # 3. deterministic cell-level validation. Every non-control fit condition
        #    remains represented in TRAIN; no target single/calibration condition is
        #    withheld wholesale by GEARS' condition-level ``no_test`` splitter.
        split_manifest = _install_deterministic_cell_split(
            pert_data,
            seed=seed,
            dataloader_cls=DataLoader,
        )
        trained_conditions = set(split_manifest["conditions"])
        requests: list[list[str]] = []
        for g, h in payload["pair_ids"]:
            required_singles = {f"{g}+ctrl", f"{h}+ctrl"}
            missing_train = required_singles - trained_conditions
            if missing_train:
                raise ValueError(
                    f"sealed pair ({g!r},{h!r}) lacks trained single condition(s): "
                    f"{sorted(missing_train)}"
                )
            requests.append([g, h])

        # 4. fit with frozen constants. No environment variable may weaken the
        #    scientific worker to a smoke-only epoch count.
        device = "cuda"
        model = GEARS(pert_data, device=device)
        pert_list = getattr(model, "pert_list", None)
        if pert_list is None:
            raise ValueError("GEARS did not expose its perturbation graph roster")
        predictable = {str(gene) for gene in pert_list}
        if not predictable:
            raise ValueError("GEARS perturbation graph roster is empty")
        _require_fit_genes_in_gears_roster(
            fit_perturbation_genes,
            pert_list,
            field="GEARS.pert_list",
        )
        for g, h in payload["pair_ids"]:
            if g not in predictable or h not in predictable:
                raise ValueError(
                    f"sealed pair ({g!r},{h!r}) has a gene absent from GEARS.pert_list"
                )
        model.model_initialize(
            hidden_size=_GEARS_HIDDEN_SIZE,
            num_go_gnn_layers=_GEARS_NUM_GO_GNN_LAYERS,
            num_gene_gnn_layers=_GEARS_NUM_GENE_GNN_LAYERS,
            decoder_hidden_size=_GEARS_DECODER_HIDDEN_SIZE,
            num_similar_genes_go_graph=_GEARS_NUM_SIMILAR_GENES_GO_GRAPH,
            num_similar_genes_co_express_graph=_GEARS_NUM_SIMILAR_GENES_COEXPRESS_GRAPH,
            coexpress_threshold=_GEARS_COEXPRESS_THRESHOLD,
            uncertainty=_GEARS_UNCERTAINTY,
            uncertainty_reg=_GEARS_UNCERTAINTY_REG,
            direction_lambda=_GEARS_DIRECTION_LAMBDA,
            no_perturb=_GEARS_NO_PERTURB,
        )
        model.train(
            epochs=_GEARS_EPOCHS,
            lr=_GEARS_LEARNING_RATE,
            weight_decay=_GEARS_WEIGHT_DECAY,
        )
        final_model = getattr(model, "model", None)
        if final_model is None or not callable(getattr(final_model, "state_dict", None)):
            raise ValueError("GEARS did not expose the fixed final-epoch model state")
        # GEARS' internal best_model uses the monitoring loader. That loader is
        # deliberately not an independent validation set, so never let it select
        # the scientific checkpoint: fixed final epoch is the registered policy.
        model.best_model = final_model
        _revalidate_gears_resource_bundle(snapshot_bundle)

        # 5. Persist the registered fixed-final-epoch state BEFORE any requested
        #    pair prediction. ``best_model`` was explicitly rebound to this state
        #    because GEARS.predict reads that attribute.
        fitted_model = getattr(model, "best_model", None)
        if fitted_model is None or not callable(getattr(fitted_model, "state_dict", None)):
            raise ValueError("GEARS did not expose a fitted best_model state_dict")
        state_dict = {
            str(key): value.detach().cpu() for key, value in fitted_model.state_dict().items()
        }
        checkpoint_obj = {
            "schema": "compose_gears_trained_model_v1",
            "backend_distribution": _GEARS_PACKAGE,
            "backend_version": _GEARS_PACKAGE_VERSION,
            "seed": seed,
            "fit_artifact_content_sha256": fit_artifact_content_sha256,
            "gene_order_sha256": canonical_gene_order_sha256(gene_order),
            "resource_manifest_sha256": snapshot_bundle["manifest_sha256"],
            "native_input_scale": input_scale,
            "native_input_scale_status": (
                "PROBE_ONLY_DECISION_MEASUREMENT"
                if observer_only
                else _GEARS_NATIVE_INPUT_SCALE_STATUS
            ),
            "training_device": device,
            "numeric_precision": _GEARS_NUMERIC_PRECISION,
            "training_config": {
                "hidden_size": _GEARS_HIDDEN_SIZE,
                "num_go_gnn_layers": _GEARS_NUM_GO_GNN_LAYERS,
                "num_gene_gnn_layers": _GEARS_NUM_GENE_GNN_LAYERS,
                "decoder_hidden_size": _GEARS_DECODER_HIDDEN_SIZE,
                "num_similar_genes_go_graph": _GEARS_NUM_SIMILAR_GENES_GO_GRAPH,
                "num_similar_genes_co_express_graph": _GEARS_NUM_SIMILAR_GENES_COEXPRESS_GRAPH,
                "coexpress_threshold": _GEARS_COEXPRESS_THRESHOLD,
                "uncertainty": _GEARS_UNCERTAINTY,
                "uncertainty_reg": _GEARS_UNCERTAINTY_REG,
                "direction_lambda": _GEARS_DIRECTION_LAMBDA,
                "no_perturb": _GEARS_NO_PERTURB,
                "epochs": _GEARS_EPOCHS,
                "learning_rate": _GEARS_LEARNING_RATE,
                "weight_decay": _GEARS_WEIGHT_DECAY,
                "optimizer": _GEARS_OPTIMIZER,
                "scheduler": _GEARS_SCHEDULER,
                "gradient_clip_value": _GEARS_GRADIENT_CLIP_VALUE,
                "model_selection_policy": _GEARS_MODEL_SELECTION_POLICY,
                "monitoring_policy": _GEARS_MONITORING_POLICY,
                "upstream_best_model_metric": _GEARS_UPSTREAM_BEST_MODEL_METRIC,
                "prediction_control_batch_size": _GEARS_PREDICTION_CONTROL_BATCH_SIZE,
                "prediction_rng_policy": _GEARS_PREDICTION_RNG_POLICY,
                "negative_prediction_policy": "clip_zero_before_response_projection",
                "batch_size": _GEARS_BATCH_SIZE,
                "validation_batch_size": _GEARS_TEST_BATCH_SIZE,
            },
            "split_manifest": split_manifest,
            "probe_context": dict(probe_context) if probe_context is not None else None,
            "model_state_dict": state_dict,
        }
        try:
            with open(checkpoint_path, "xb") as checkpoint_file:
                torch.save(checkpoint_obj, checkpoint_file)
                checkpoint_file.flush()
                os.fsync(checkpoint_file.fileno())
        except Exception:
            Path(checkpoint_path).unlink(missing_ok=True)
            raise

        # Probe-only callers may observe the already-fitted, checkpointed model inside
        # this temporary offline resource snapshot.  The scientific worker supplies no
        # observer and no probe_context: with the positional GEARS obs index restored
        # above and the default input scale, its fitted model and predictions are
        # numerically unchanged; the durable checkpoint only additionally records inert
        # backend distribution/version provenance.  The callback cannot alter the
        # checkpoint durably written above without the caller's later SHA/envelope
        # verification failing closed.
        if fitted_model_observer is not None:
            fitted_model_observer(
                model=model,
                pert_data=pert_data,
                torch_module=torch,
                requests=requests,
                checkpoint_path=checkpoint_path,
            )
            if observer_only:
                return {}

        # 6. Predict each requested combo only after the fitted state is durable.
        raw_pred = _predict_pairs_order_independent(
            model,
            requests,
            seed=seed,
            torch_module=torch,
        )
        expected_prediction_keys = {f"{g}_{h}" for g, h in payload["pair_ids"]}
        if not isinstance(raw_pred, dict) or set(raw_pred) != expected_prediction_keys:
            raise ValueError("GEARS prediction key roster differs from the sealed request")

        gears_genes = [str(x) for x in pert_data.adata.var["gene_name"]]
        if len(set(gears_genes)) != len(gears_genes) or set(gears_genes) != set(gene_order):
            raise ValueError("GEARS output gene roster differs from the fit-role artifact")
        name_to_col = {g: i for i, g in enumerate(gears_genes)}
        try:
            remap = [name_to_col[g] for g in gene_order]
        except KeyError as exc:
            raise ValueError(
                f"GEARS output is missing gene {exc} from the response gene order"
            ) from exc

        control_mean = np.asarray(proj["control_mean"], dtype=np.float64)
        dim = int(payload["response_dim"])
        preds: dict[tuple[str, str], np.ndarray] = {}
        for g, h in payload["pair_ids"]:
            raw_vector = np.asarray(raw_pred[f"{g}_{h}"], dtype=np.float64)
            if raw_vector.shape != (len(gears_genes),) or not np.isfinite(raw_vector).all():
                raise ValueError(f"GEARS prediction for ({g!r},{h!r}) has invalid shape/values")
            vec = raw_vector[remap]
            # This remains the explicitly activation-blocked raw-pseudobulk path;
            # do not silently substitute normalized GEARS preprocessing here.
            native = np.clip(vec, 0.0, None)[None, :]
            z = apply_response_projection(
                proj,
                native,
                gene_order,
                representation=representation,
            )
            preds[(g, h)] = (z.mean(axis=0) - control_mean)[:dim]
            if preds[(g, h)].shape != (dim,) or not np.isfinite(preds[(g, h)]).all():
                raise ValueError(f"GEARS response for ({g!r},{h!r}) has invalid shape/values")
        _revalidate_gears_resource_bundle(snapshot_bundle)
        return preds


def main() -> None:
    """Validate the fit-role artifact, run the pod fit, emit the envelope."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="work_dir", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--approved-root", required=True)
    ap.add_argument(
        "--prediction-representation",
        required=True,
        choices=("cell_raw_counts", "raw_pseudobulk_approximation"),
    )
    a = ap.parse_args()
    identity = _verify_runtime_identity(a.prediction_representation)
    payload = read_payload(a.work_dir, require_expected_sha256=True)
    payload_sha256 = canonical_payload_sha256(payload)
    fit_role = payload["fit_role_artifact"]
    proj = payload["response_projection"]

    # 1. re-validate the artifact exactly as the guard requires (fails closed).
    #    The requested pair identities are SEALED: their cells must never occur
    #    in the fit artifact, so they are passed as ``sealed_pair_ids``.
    spec = FitRoleArtifactSpec(
        path=fit_role["path"],
        sha256=fit_role["sha256"],
        content_manifest_sha256=fit_role["content_manifest_sha256"],
        raw_data_sha256=fit_role["raw_data_sha256"],
        pair_manifest_sha256=fit_role["pair_manifest_sha256"],
        eligibility_hash=fit_role["eligibility_hash"],
        row_identity_sha256=fit_role["row_identity_sha256"],
        gene_order_sha256=fit_role["gene_order_sha256"],
        n_cells=int(fit_role["n_cells"]),
        n_genes=int(fit_role["n_genes"]),
        role_counts=dict(fit_role["role_counts"]),
    )
    validate_fit_role_artifact(
        fit_role["path"],
        spec=spec,
        approved_root=a.approved_root,
        calibration_pair_ids=[tuple(pr) for pr in payload["calibration_pair_ids"]],
        sealed_pair_ids=[tuple(pr) for pr in payload["pair_ids"]],
        single_gene_ids=[str(g) for g in payload["single_gene_ids"]],
    )

    # 2. Read the exact validated bytes through a stable descriptor and hand that
    #    in-memory snapshot to the fit. The fit body must never reopen the pathname.
    adata = read_verified_fit_role_artifact(
        fit_role["path"],
        spec=spec,
        approved_root=a.approved_root,
    )
    gene_order = [str(v) for v in adata.var_names]
    representation = a.prediction_representation

    # 3. Fit, persist the real model state, then predict. The checkpoint destination
    #    lives beside the output envelope and is supplied before fitting begins.
    checkpoint_path = a.out + ".checkpoint"
    preds = _fit_and_predict(
        payload,
        adata,
        proj,
        gene_order,
        representation,
        fit_artifact_content_sha256=fit_role["content_manifest_sha256"],
        checkpoint_path=checkpoint_path,
    )
    if not os.path.isfile(checkpoint_path) or os.path.islink(checkpoint_path):
        raise ValueError("GEARS fit returned without a trained-model checkpoint")
    with open(checkpoint_path, "rb") as checkpoint_file:
        checkpoint = hashlib.sha256(checkpoint_file.read()).hexdigest()

    manifest = {
        "prediction_representation": representation,
        "adapter_version": identity.adapter_version,
        "adapter_sha256": identity.adapter_sha256,
        "expected_gene_order_sha256": proj["gene_order_sha256"],
        "observed_gene_order_sha256": canonical_gene_order_sha256(gene_order),
        "checkpoint_sha256": checkpoint,
        "worker_sha256": identity.worker_executable_sha256,
        "config_sha256": identity.config_sha256,
        "resource_sha256": identity.resource_sha256,
        "environment_lock_sha256": identity.environment_lock_sha256,
        "payload_sha256": payload_sha256,
        "fit_artifact_content_sha256": fit_role["content_manifest_sha256"],
        "combined_request_sha256": hashlib.sha256(
            json.dumps([list(pr) for pr in payload["pair_ids"]], separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
        "predictions_sha256": "",  # write_predictions fills this
    }
    write_predictions(a.out, preds, execution_manifest=manifest)


if __name__ == "__main__":
    main()
