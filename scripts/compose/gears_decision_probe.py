#!/usr/bin/env python
"""Prepare and verify a seal-safe GEARS decision-probe input.

This maintained CLI never accepts the original Norman/source outcome file.  It
consumes only a previously verified fit-role payload whose expression rows are
already restricted to control, singles, and combo-calibration.  Rows are
normalized over the full fit-role gene universe before selecting the frozen
method-specific GEARS roster.

The result is a probe-only log-normalized AnnData.  It is not a raw-count
fit-role artifact and must never be passed through a code path that labels it as
one.  Scientific GEARS output projection remains blocked pending Probe A.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import stat
import sys
import tempfile
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

from alive.compose.approximation_bias import canonical_file_bytes
from alive.compose.baseline_subprocess import canonical_payload_sha256, read_payload
from alive.compose.fit_role import (
    FitRoleArtifactSpec,
    read_verified_fit_role_artifact,
    row_identity_sha256,
    validate_fit_role_artifact,
)
from alive.compose.gears_probe_a import (
    GEARS_LOCK_PATH,
    MANIFEST_SCHEMA,
    PREPARATION_LOCK_PATH,
    PROBE_INPUT_ADATA_SCHEMA,
    PROBE_INPUT_MANIFEST_SCHEMA,
    PROBE_MATRIX_DTYPE,
    PROBE_MATRIX_FORMAT,
    RAW_SCHEMA,
    REGISTRATION_PATH,
    REPORT_PATH,
    ROSTER_RECEIPT_SCHEMA,
    assert_clean_approved_checkout,
    build_evidence_manifest,
    build_probe_a_report,
    repository_lock_sha256,
    validate_probe_a_raw_artifact,
    validate_registration,
)
from alive.compose.gene_universe import (
    AliasMap,
    GeneUniverseError,
    assert_gears_roster_matches,
    compute_mandatory_report,
    generate_gears_gene_roster,
    load_gears_gene_roster,
    normalize_full_then_subset,
)
from alive.io import atomic_write_once
from alive.provenance import sha256_bytes, sha256_file, sha256_json

_MANIFEST_SCHEMA = PROBE_INPUT_MANIFEST_SCHEMA
_RECEIPT_SCHEMA = ROSTER_RECEIPT_SCHEMA
_ADATA_SCHEMA = PROBE_INPUT_ADATA_SCHEMA
_CANDIDATE_SCHEMA = "compose_perturbation_candidates_v1"
_GENE2GO_SCHEMA = "compose_gene2go_nodes_v1"
_COMMAND_RESULT_SCHEMA = "compose_gears_probe_command_result_v1"
_PROBE_INPUT_TRANSFORM = "full_library_normalize_log1p_then_roster_subset"
_RECEIPT_KEYS = {
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


def _require_sha256(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise GeneUniverseError(f"{label} must be a bare lowercase SHA-256")
    return value


def _stable_bytes(path: str | Path, *, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(Path(path), flags)
    except OSError as exc:
        raise GeneUniverseError(f"cannot open {label} safely: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise GeneUniverseError(f"{label} is not a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        data = b"".join(chunks)
        if before_identity != after_identity or len(data) != before.st_size:
            raise GeneUniverseError(f"{label} changed while being read")
        return data
    finally:
        os.close(fd)


def _sha256_fd(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 1 << 20)
        if not chunk:
            break
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()


def _read_verified_probe_h5ad(path: str | Path, *, expected_sha256: str) -> ad.AnnData:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(Path(path), flags)
    except OSError as exc:
        raise GeneUniverseError(f"cannot open probe input safely: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise GeneUniverseError("probe input is not a regular file")
        if _sha256_fd(fd) != expected_sha256:
            raise GeneUniverseError("probe input H5AD SHA-256 mismatch")
        fd_root = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
        try:
            snapshot = ad.read_h5ad(os.path.join(fd_root, str(fd)))
        except Exception as exc:
            raise GeneUniverseError(f"cannot read verified probe input: {exc}") from exc
        if _sha256_fd(fd) != expected_sha256:
            raise GeneUniverseError("probe input bytes changed while being read")
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise GeneUniverseError("probe input identity changed while being read")
        return snapshot
    finally:
        os.close(fd)


def _contract_json(
    path: str | Path,
    *,
    expected_file_sha256: str,
    schema: str,
    keys: set[str],
    label: str,
) -> dict[str, object]:
    expected_file_sha256 = _require_sha256(
        expected_file_sha256, label=f"{label} expected file SHA-256"
    )
    data = _stable_bytes(path, label=label)
    if sha256_bytes(data) != expected_file_sha256:
        raise GeneUniverseError(f"{label} file SHA-256 mismatch")
    try:
        text = data.decode("utf-8")
        payload = json.loads(text)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GeneUniverseError(f"cannot decode {label}: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != keys or payload.get("schema") != schema:
        raise GeneUniverseError(f"{label} schema/key roster is invalid")
    core = dict(payload)
    checksum = core.pop("manifest_checksum")
    if checksum != sha256_json(core):
        raise GeneUniverseError(f"{label} manifest checksum mismatch")
    canonical = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if text != canonical:
        raise GeneUniverseError(f"{label} is not canonical JSON")
    return payload


def _load_roster_receipt(path: str | Path, *, expected_file_sha256: str) -> dict[str, object]:
    receipt = _contract_json(
        path,
        expected_file_sha256=expected_file_sha256,
        schema=_RECEIPT_SCHEMA,
        keys=_RECEIPT_KEYS,
        label="GEARS roster receipt",
    )
    for field in _RECEIPT_KEYS - {"manifest_checksum", "n_target", "schema"}:
        _require_sha256(receipt[field], label=f"GEARS roster receipt {field}")
    n_target = receipt["n_target"]
    if isinstance(n_target, bool) or not isinstance(n_target, int) or n_target < 1:
        raise GeneUniverseError("GEARS roster receipt n_target must be a positive integer")
    return receipt


def _emit_command_result(*, command: str, primary_file_sha256: str) -> None:
    """Emit a publication-boundary digest for the durable command log."""
    payload = {
        "command": command,
        "primary_file_sha256": _require_sha256(
            primary_file_sha256, label="command result primary file SHA-256"
        ),
        "runtime_fingerprint_sha256": _runtime_fingerprint_sha256(),
        "schema": _COMMAND_RESULT_SCHEMA,
        "status": "OK",
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def _probe_output_path(*, evidence_root: str | Path, out_raw: str | Path) -> str:
    try:
        return (
            Path(out_raw).resolve().relative_to(Path(evidence_root).resolve(strict=True)).as_posix()
        )
    except (OSError, ValueError) as exc:
        raise GeneUniverseError(
            "Probe-A raw output must be under the existing evidence root"
        ) from exc


def _input_scale_sha256(normalization_target: float) -> str:
    return sha256_json(
        {
            "normalization_target": normalization_target,
            "transform": _PROBE_INPUT_TRANSFORM,
        }
    )


def _canonical_pair_roster(values, *, label: str) -> list[list[str]]:
    pairs: list[tuple[str, str]] = []
    for index, raw_pair in enumerate(values):
        if not isinstance(raw_pair, (list, tuple)) or len(raw_pair) != 2:
            raise GeneUniverseError(f"{label}[{index}] must be one gene pair")
        genes = tuple(str(gene) for gene in raw_pair)
        if any(not gene for gene in genes) or genes[0] == genes[1]:
            raise GeneUniverseError(f"{label}[{index}] contains invalid gene ids")
        pairs.append(tuple(sorted(genes, key=lambda gene: gene.encode("utf-8"))))
    ordered = sorted(
        set(pairs), key=lambda pair: (pair[0].encode("utf-8"), pair[1].encode("utf-8"))
    )
    if len(ordered) != len(pairs):
        raise GeneUniverseError(f"{label} contains duplicate pairs")
    return [list(pair) for pair in ordered]


def _role_token_sets(role_contract: dict) -> tuple[set[str], set[str], set[str]]:
    """Build unambiguous tokens without parsing gene ids by the combo separator."""
    separator = role_contract["combo_separator"]
    control = role_contract["control_token"]
    singles = set(role_contract["single_gene_ids"])
    calibration_pairs = role_contract["calibration_pair_ids"]
    sealed_pairs = role_contract["sealed_pair_ids"]
    calibration = {separator.join(pair) for pair in calibration_pairs}
    sealed = {separator.join(pair) for pair in sealed_pairs}
    if len(calibration) != len(calibration_pairs) or len(sealed) != len(sealed_pairs):
        raise GeneUniverseError("probe role contract has ambiguous serialized pair tokens")
    if calibration & sealed:
        raise GeneUniverseError("probe calibration and sealed pair tokens collide")
    if (calibration | sealed | {control}) & singles:
        raise GeneUniverseError("probe control/combo and single perturbation tokens collide")
    return calibration, sealed, singles


def _load_frozen_registration(
    *,
    evidence_root: Path,
    registration_path: str | Path,
    registration_sha256: str,
    expected_git_commit: str,
) -> tuple[dict, str]:
    """Load the canonical owner-frozen registration before any Probe-A fit."""
    expected_path = evidence_root / REGISTRATION_PATH
    try:
        actual_path = Path(registration_path).resolve(strict=True)
    except OSError as exc:
        raise GeneUniverseError(f"cannot resolve Probe-A registration: {exc}") from exc
    if actual_path != expected_path:
        raise GeneUniverseError("Probe-A must consume the archived canonical registration")
    expected_sha256 = _require_sha256(
        registration_sha256, label="Probe-A registration expected SHA-256"
    )
    data = _stable_bytes(actual_path, label="Probe-A registration")
    if sha256_bytes(data) != expected_sha256:
        raise GeneUniverseError("Probe-A registration SHA-256 differs from its external pin")
    try:
        registration = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GeneUniverseError(f"cannot parse Probe-A registration: {exc}") from exc
    if not isinstance(registration, dict) or data != canonical_file_bytes(registration):
        raise GeneUniverseError("Probe-A registration must be canonical finite JSON")
    try:
        validate_registration(registration, expected_git_commit=expected_git_commit)
    except ValueError as exc:
        raise GeneUniverseError(f"Probe-A registration is invalid: {exc}") from exc
    return registration, expected_sha256


def _matrix_identity(value, *, label: str) -> dict[str, object]:
    """Hash one logical matrix canonically without densifying the full fit input."""
    try:
        matrix = sparse.csr_matrix(value, dtype=np.float64, copy=True)
    except (TypeError, ValueError) as exc:
        raise GeneUniverseError(f"{label} must be a two-dimensional numeric matrix") from exc
    matrix.sum_duplicates()
    matrix.sort_indices()
    matrix.eliminate_zeros()
    if matrix.ndim != 2 or not np.isfinite(matrix.data).all():
        raise GeneUniverseError(f"{label} must be a finite two-dimensional matrix")
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


def _load_gears_worker_module():
    worker_path = Path(__file__).resolve().parents[1] / "baselines/gears_worker.py"
    spec = importlib.util.spec_from_file_location("alive_compose_probe_gears_worker", worker_path)
    if spec is None or spec.loader is None:
        raise GeneUniverseError("cannot load the maintained GEARS worker source")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, worker_path


def _direct_control_predictions(
    *,
    model,
    torch_module,
    query: list[str],
    count: int,
    expected_control_row_ids: list[str],
):
    """Return public GEARS output and every direct per-control model row."""
    controls = model.adata[model.adata.obs["condition"] == "ctrl"][:count].copy()
    if int(controls.n_obs) != count:
        raise GeneUniverseError(f"Probe-A requested {count} controls but the model has fewer")
    observed_control_row_ids = controls.obs_names.astype(str).tolist()
    if observed_control_row_ids != expected_control_row_ids[:count]:
        raise GeneUniverseError("processed GEARS control-row order differs from prepared input")
    original_adata = model.adata
    original_saved = dict(model.saved_pred)
    key = "_".join(query)
    try:
        model.adata = controls
        model.saved_pred.clear()
        public_result = model.predict([query])
        if not isinstance(public_result, dict) or set(public_result) != {key}:
            raise GeneUniverseError("GEARS public prediction returned an unexpected key roster")
        public = np.asarray(public_result[key], dtype=np.float64)

        graph_factory = model.predict.__globals__.get("create_cell_graph_dataset_for_prediction")
        if not callable(graph_factory):
            raise GeneUniverseError(
                "pinned GEARS predict no longer exposes its control-graph factory"
            )
        from torch_geometric.loader import DataLoader

        graphs = graph_factory(query, controls, model.pert_list, model.device)
        rows: list[np.ndarray] = []
        fitted = model.best_model.to(model.device)
        fitted.eval()
        with torch_module.no_grad():
            for batch in DataLoader(graphs, 300, shuffle=False):
                batch.to(model.device)
                prediction = fitted(batch)
                if isinstance(prediction, tuple):
                    prediction = prediction[0]
                rows.append(np.asarray(prediction.detach().cpu().numpy(), dtype=np.float64))
        per_control = np.concatenate(rows, axis=0)
    finally:
        model.adata = original_adata
        model.saved_pred.clear()
        model.saved_pred.update(original_saved)
    if public.ndim != 1 or per_control.ndim != 2 or per_control.shape[0] != count:
        raise GeneUniverseError("GEARS Probe-A prediction shape is invalid")
    if public.shape[0] != per_control.shape[1]:
        raise GeneUniverseError("GEARS public/per-control gene widths differ")
    if not np.isfinite(public).all() or not np.isfinite(per_control).all():
        raise GeneUniverseError("GEARS Probe-A predictions must be finite")
    return public.tolist(), per_control.tolist()


def run_probe_a_measurements(
    *,
    payload_dir: str | Path,
    registration_path: str | Path,
    registration_sha256: str,
    expected_git_commit: str,
    probe_manifest_path: str | Path,
    probe_manifest_sha256: str,
    h5ad_path: str | Path,
    roster_path: str | Path,
    roster_receipt_path: str | Path,
    approved_root: str | Path,
    evidence_root: str | Path,
    out_raw: str | Path,
    checkpoint_dir: str | Path,
    fit_runner=None,
) -> str:
    """Execute two fresh pinned GEARS fits and publish their measured raw evidence."""
    try:
        assert_clean_approved_checkout(expected_git_commit)
    except ValueError as exc:
        raise GeneUniverseError(str(exc)) from exc
    evidence = Path(evidence_root).resolve(strict=True)
    approved = Path(approved_root).resolve(strict=True)
    if not evidence.is_dir() or not approved.is_dir():
        raise GeneUniverseError("Probe-A roots must be existing directories")
    registration, registration_sha256 = _load_frozen_registration(
        evidence_root=evidence,
        registration_path=registration_path,
        registration_sha256=registration_sha256,
        expected_git_commit=expected_git_commit,
    )
    relative_output = _probe_output_path(evidence_root=evidence, out_raw=out_raw)
    expected_manifest = evidence / "probe_input_manifest.json"
    expected_h5ad = evidence / "probe_input.h5ad"
    if Path(probe_manifest_path).resolve(strict=True) != expected_manifest:
        raise GeneUniverseError("Probe-A must consume the archived canonical input manifest")
    if Path(h5ad_path).resolve(strict=True) != expected_h5ad:
        raise GeneUniverseError("Probe-A must consume the archived canonical input H5AD")
    checkpoint_root = Path(checkpoint_dir).resolve()
    if checkpoint_root != evidence / "checkpoints":
        raise GeneUniverseError("Probe-A checkpoints must use evidence-root/checkpoints")
    manifest = verify_probe_input(
        manifest_path=probe_manifest_path,
        expected_manifest_sha256=probe_manifest_sha256,
        h5ad_path=h5ad_path,
        roster_path=roster_path,
        roster_receipt_path=roster_receipt_path,
    )
    normalization_target = float(manifest["normalization_target"])
    registered_scale = registration["input_scale"]
    if (
        normalization_target != float(registered_scale["normalization_target"])
        or manifest["expression_scale"] != registered_scale["transform"]
    ):
        raise GeneUniverseError(
            "prepared Probe-A input scale differs from the owner-frozen registration"
        )
    input_scale_sha256 = _input_scale_sha256(normalization_target)
    probe = _read_verified_probe_h5ad(
        h5ad_path, expected_sha256=str(manifest["output_h5ad_sha256"])
    )
    payload = read_payload(str(payload_dir), require_expected_sha256=True)
    if canonical_payload_sha256(payload) != manifest["payload_sha256"]:
        raise GeneUniverseError("Probe-A payload identity differs from the prepared input")
    controls = probe.obs.loc[probe.obs["role"].astype(str) == "control", "source_row_id"].astype(
        str
    )
    ordered_control_row_ids = controls.tolist()
    if len(ordered_control_row_ids) < 400 or len(set(ordered_control_row_ids)) != len(
        ordered_control_row_ids
    ):
        raise GeneUniverseError("Probe-A requires at least 400 unique prepared control rows")
    calibration_pairs = _canonical_pair_roster(
        payload["calibration_pair_ids"], label="calibration_pair_ids"
    )
    if calibration_pairs != manifest["role_contract"]["calibration_pair_ids"]:
        raise GeneUniverseError(
            "Probe-A calibration roster differs from the prepared role contract"
        )
    if not calibration_pairs:
        raise GeneUniverseError("Probe-A requires a non-sealed calibration-pair query")
    query = calibration_pairs[0]
    if len(query) != 2 or query[0] >= query[1]:
        raise GeneUniverseError("Probe-A query must be one canonical calibration pair")
    seed = int(payload["seed"])
    before = _matrix_identity(probe.X, label="Probe-A prepared input")

    worker, worker_path = _load_gears_worker_module()
    worker_code_sha256 = sha256_file(worker_path)
    gears_dependency_lock_sha256 = str(manifest["gears_dependency_lock_sha256"])
    try:
        gears_installed_packages_sha256 = worker.verify_probe_runtime_identity(
            expected_gears_lock_sha256=gears_dependency_lock_sha256
        )
    except ValueError as exc:
        raise GeneUniverseError(f"Probe-A GEARS runtime identity is invalid: {exc}") from exc
    _require_sha256(
        gears_installed_packages_sha256, label="Probe-A installed package roster SHA-256"
    )
    query_sha256 = sha256_json(query)
    runner = fit_runner or worker._fit_and_predict
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    observations: list[dict[str, object]] = []
    probe_payload = {
        **payload,
        "pair_ids": [query],
        "response_dim": int(probe.n_vars),
        "seed": seed,
    }
    for run_index in range(2):
        checkpoint = checkpoint_root / f"run_{run_index + 1}.pt"
        if checkpoint.exists() or checkpoint.is_symlink():
            raise GeneUniverseError("Probe-A checkpoint destination already exists")
        captured: dict[str, object] = {}

        def observe(*, model, pert_data, torch_module, **_unused):
            processed_row_ids = pert_data.adata.obs_names.astype(str).tolist()
            if processed_row_ids != probe.obs["source_row_id"].astype(str).tolist():
                raise GeneUniverseError("GEARS processed row order differs from prepared input")
            captured["input_after"] = _matrix_identity(
                pert_data.adata.X, label="GEARS processed Probe-A input"
            )
            control_predictions = []
            for count in (1, 8, 300, 301, 400):
                public, per_control = _direct_control_predictions(
                    model=model,
                    torch_module=torch_module,
                    query=query,
                    count=count,
                    expected_control_row_ids=ordered_control_row_ids,
                )
                control_predictions.append(
                    {
                        "count": count,
                        "control_row_ids": ordered_control_row_ids[:count],
                        "per_control_prediction": per_control,
                        "public_prediction": public,
                    }
                )
            captured["control_predictions"] = control_predictions

        runner(
            probe_payload,
            probe,
            {},
            [str(gene) for gene in probe.var_names],
            "raw_pseudobulk_approximation",
            fit_artifact_content_sha256=str(manifest["fit_artifact_content_sha256"]),
            checkpoint_path=str(checkpoint),
            fitted_model_observer=observe,
            observer_only=True,
            input_scale="full_library_normalize_log1p_then_roster_subset",
            probe_context={
                "gears_dependency_lock_sha256": gears_dependency_lock_sha256,
                "gears_installed_packages_sha256": gears_installed_packages_sha256,
                "mode": "probe_a",
                "input_scale_sha256": input_scale_sha256,
                "probe_input_h5ad_sha256": str(manifest["output_h5ad_sha256"]),
                "query_sha256": query_sha256,
                "registration_sha256": registration_sha256,
                "worker_code_sha256": worker_code_sha256,
            },
        )
        if set(captured) != {"input_after", "control_predictions"}:
            raise GeneUniverseError("GEARS fit returned without complete Probe-A observations")
        observations.append(
            {
                **captured,
                "checkpoint_path": checkpoint.resolve()
                .relative_to(Path(evidence_root).resolve(strict=True))
                .as_posix(),
                "checkpoint_sha256": sha256_file(checkpoint),
            }
        )
    if observations[0]["input_after"] != observations[1]["input_after"]:
        raise GeneUniverseError("GEARS processed input differs across deterministic Probe-A runs")
    if before != observations[0]["input_after"]:
        raise GeneUniverseError("GEARS changed the canonical prepared Probe-A matrix")
    controls_run_1 = observations[0]["control_predictions"]
    controls_run_2 = observations[1]["control_predictions"]
    public_1 = controls_run_1[-1]["public_prediction"]
    public_2 = controls_run_2[-1]["public_prediction"]
    producer = {
        "backend_distribution": "cell-gears",
        "backend_version": "0.1.2",
        "gears_dependency_lock_sha256": gears_dependency_lock_sha256,
        "gears_installed_packages_sha256": gears_installed_packages_sha256,
        "input_scale_sha256": input_scale_sha256,
        "normalization_target": normalization_target,
        "registration_sha256": registration_sha256,
        "worker_code_sha256": worker_code_sha256,
        "probe_driver_code_sha256": sha256_file(Path(__file__).resolve()),
        "probe_input_manifest_sha256": probe_manifest_sha256,
        "probe_input_h5ad_sha256": str(manifest["output_h5ad_sha256"]),
        "probe_row_identity_sha256": str(manifest["row_identity_sha256"]),
        "ordered_control_row_identity_sha256": sha256_json(ordered_control_row_ids),
        "roster_sha256": str(manifest["roster_file_sha256"]),
        "query": query,
        "seed": seed,
        "measurement_run_index": 1,
    }
    measurement = {
        "producer": producer,
        "input_before": before,
        "input_after": observations[0]["input_after"],
        "determinism_runs": [
            {
                "run_index": index + 1,
                "checkpoint_path": observation["checkpoint_path"],
                "checkpoint_sha256": observation["checkpoint_sha256"],
                "checkpoint_bytes": checkpoint_root.joinpath(f"run_{index + 1}.pt").stat().st_size,
                "checkpoint_format": "pytorch_zip_v1",
                "seed": seed,
                "probe_input_h5ad_sha256": str(manifest["output_h5ad_sha256"]),
                "query_sha256": query_sha256,
                "worker_code_sha256": worker_code_sha256,
                "prediction": prediction,
            }
            for index, (observation, prediction) in enumerate(
                zip(observations, (public_1, public_2), strict=True)
            )
        ],
        "ordered_control_row_ids": ordered_control_row_ids,
        "control_predictions": controls_run_1,
        "public_prediction": public_1,
        "bridge_prediction": [
            sum(row[column] for row in controls_run_1[-1]["per_control_prediction"][:300]) / 300
            for column in range(len(public_1))
        ],
    }
    body = {"schema": RAW_SCHEMA, **measurement}
    payload = {**body, "self_checksum": sha256_json(body)}
    encoded = canonical_file_bytes(payload)
    atomic_write_once(out_raw, encoded.decode("utf-8"))
    digest = sha256_bytes(encoded)
    try:
        validate_probe_a_raw_artifact(
            evidence_root=evidence_root,
            relative_path=relative_output,
            expected_sha256=digest,
        )
    except (ValueError, OSError) as exc:
        raise GeneUniverseError(f"Probe-A raw publication failed validation: {exc}") from exc
    return digest


def _generator_code_sha256() -> str:
    """Hash the complete maintained source closure that determines a roster."""
    root = Path(__file__).resolve().parents[2]
    relative_paths = (
        "src/alive/compose/fit_role.py",
        "src/alive/compose/gene_universe.py",
        "src/alive/compose/response.py",
        "src/alive/io.py",
        "src/alive/provenance.py",
    )
    return sha256_json(
        {
            relative: sha256_bytes(
                _stable_bytes(root / relative, label=f"generator dependency {relative}")
            )
            for relative in relative_paths
        }
    )


def _preparation_dependency_lock_sha256() -> str:
    return repository_lock_sha256(PREPARATION_LOCK_PATH)


def _gears_dependency_lock_sha256() -> str:
    return repository_lock_sha256(GEARS_LOCK_PATH)


def _runtime_fingerprint_sha256() -> str:
    """Digest the local numerical/runtime stack; detailed values belong in runtime.json."""
    packages = ("anndata", "h5py", "numpy", "pandas", "scipy")
    return sha256_json(
        {
            "implementation": platform.python_implementation(),
            "packages": {name: importlib.metadata.version(name) for name in packages},
            "platform": platform.platform(),
            "python": sys.version,
        }
    )


def _fit_spec(block: dict) -> FitRoleArtifactSpec:
    return FitRoleArtifactSpec(
        path=block["path"],
        sha256=block["sha256"],
        content_manifest_sha256=block["content_manifest_sha256"],
        raw_data_sha256=block["raw_data_sha256"],
        pair_manifest_sha256=block["pair_manifest_sha256"],
        eligibility_hash=block["eligibility_hash"],
        row_identity_sha256=block["row_identity_sha256"],
        gene_order_sha256=block["gene_order_sha256"],
        n_cells=int(block["n_cells"]),
        n_genes=int(block["n_genes"]),
        role_counts=dict(block["role_counts"]),
    )


def build_roster(
    *,
    payload_dir: str | Path,
    candidate_artifact: str | Path,
    candidate_artifact_sha256: str,
    gene2go_nodes_artifact: str | Path,
    gene2go_nodes_artifact_sha256: str,
    alias_artifact: str | Path,
    alias_artifact_sha256: str,
    approved_root: str | Path,
    n_target: int,
    out_report: str | Path,
    out_roster: str | Path,
    out_receipt: str | Path,
    require_payload_sha256: bool = True,
) -> dict[str, object]:
    """Build report/freeze artifacts from a verified non-sealed fit payload."""
    destinations = (Path(out_report), Path(out_roster), Path(out_receipt))
    if len({destination.resolve(strict=False) for destination in destinations}) != len(
        destinations
    ):
        raise GeneUniverseError("roster output destinations must be distinct")
    for destination in destinations:
        if destination.exists() or destination.is_symlink():
            raise GeneUniverseError("roster output destination already exists")
    candidates = _contract_json(
        candidate_artifact,
        expected_file_sha256=candidate_artifact_sha256,
        schema=_CANDIDATE_SCHEMA,
        keys={"manifest_checksum", "schema", "source_manifest_sha256", "tokens"},
        label="perturbation candidate artifact",
    )
    gene2go = _contract_json(
        gene2go_nodes_artifact,
        expected_file_sha256=gene2go_nodes_artifact_sha256,
        schema=_GENE2GO_SCHEMA,
        keys={"genes", "manifest_checksum", "schema", "source_gene2go_sha256"},
        label="gene2go node artifact",
    )
    if not isinstance(candidates["tokens"], list) or not isinstance(gene2go["genes"], list):
        raise GeneUniverseError("candidate/gene2go node rosters must be lists")
    alias = AliasMap.load(alias_artifact, expected_sha256=alias_artifact_sha256)
    payload = read_payload(str(payload_dir), require_expected_sha256=require_payload_sha256)
    fit_role = payload["fit_role_artifact"]
    projection = payload["response_projection"]
    spec = _fit_spec(fit_role)
    validate_fit_role_artifact(
        fit_role["path"],
        spec=spec,
        approved_root=str(approved_root),
        calibration_pair_ids=[tuple(pair) for pair in payload["calibration_pair_ids"]],
        sealed_pair_ids=[tuple(pair) for pair in payload["pair_ids"]],
        single_gene_ids=[str(gene) for gene in payload["single_gene_ids"]],
    )
    source = read_verified_fit_role_artifact(
        fit_role["path"], spec=spec, approved_root=str(approved_root)
    )
    roles = source.obs["role"].astype(str).to_numpy()
    control_indices = [int(index) for index in (roles == "control").nonzero()[0]]
    if not control_indices:
        raise GeneUniverseError("verified fit-role artifact contains no control rows")
    control_rows = [
        (
            str(source.obs.iloc[index]["source_row_id"]),
            str(source.obs.iloc[index]["role"]),
            str(source.obs.iloc[index]["perturbation"]),
        )
        for index in control_indices
    ]
    report = compute_mandatory_report(
        full_var=[str(gene) for gene in source.var_names],
        fit_artifact_identity=fit_role,
        response_projection=projection,
        perturbation_candidates=candidates["tokens"],
        gene2go=gene2go["genes"],
        gene2go_sha256=str(gene2go["source_gene2go_sha256"]),
        alias=alias,
        perturbation_candidate_source_sha256=str(candidates["source_manifest_sha256"]),
    )
    report_core = report.to_dict()
    report_payload = {**report_core, "report_checksum": sha256_json(report_core)}
    generator_code_sha256 = _generator_code_sha256()
    driver_code_sha256 = sha256_bytes(
        _stable_bytes(Path(__file__).resolve(), label="GEARS probe driver source")
    )
    roster = generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=source.X[control_indices],
        control_row_identity_sha256=row_identity_sha256(control_rows),
        generator_code_sha256=generator_code_sha256,
        n_target=n_target,
    )
    # Publish the roster first only after both output payloads are fully assembled;
    # a crash between the two creates an invalid partial run and requires new paths.
    roster_text = json.dumps(roster.to_dict(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    report_text = json.dumps(report_payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    roster.write(out_roster)
    atomic_write_once(
        out_report,
        report_text,
    )
    receipt_core = {
        "alias_artifact_sha256": alias_artifact_sha256,
        "candidate_artifact_sha256": candidate_artifact_sha256,
        "preparation_dependency_lock_sha256": _preparation_dependency_lock_sha256(),
        "gears_dependency_lock_sha256": _gears_dependency_lock_sha256(),
        "driver_code_sha256": driver_code_sha256,
        "fit_artifact_content_sha256": fit_role["content_manifest_sha256"],
        "gene2go_nodes_artifact_sha256": gene2go_nodes_artifact_sha256,
        "generator_code_sha256": generator_code_sha256,
        "n_target": n_target,
        "ordered_roster_sha256": roster.ordered_roster_sha256,
        "payload_sha256": canonical_payload_sha256(payload),
        "report_file_sha256": sha256_bytes(report_text.encode("utf-8")),
        "response_artifact_sha256": projection["response_artifact_sha256"],
        "runtime_fingerprint_sha256": _runtime_fingerprint_sha256(),
        "roster_artifact_checksum": roster.artifact_checksum,
        "roster_file_sha256": sha256_bytes(roster_text.encode("utf-8")),
        "schema": _RECEIPT_SCHEMA,
    }
    receipt = {**receipt_core, "manifest_checksum": sha256_json(receipt_core)}
    receipt_text = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    receipt_file_sha256 = sha256_bytes(receipt_text.encode("utf-8"))
    atomic_write_once(out_receipt, receipt_text)
    return {
        "receipt": receipt,
        "receipt_file_sha256": receipt_file_sha256,
        "report": report_payload,
        "roster": roster.to_dict(),
    }


def _atomic_write_h5ad(adata: ad.AnnData, destination: Path) -> str:
    """Publish one H5AD atomically and return the pre-publication byte digest."""
    if destination.exists() or destination.is_symlink():
        raise GeneUniverseError("probe input destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp.h5ad", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    temporary.unlink()
    output_sha256: str | None = None
    try:
        adata.write_h5ad(temporary)
        with open(temporary, "rb") as handle:
            os.fsync(handle.fileno())
        output_sha256 = sha256_file(temporary)
        os.link(temporary, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    if output_sha256 is None:  # pragma: no cover - defensive; writes raise before this point
        raise GeneUniverseError("probe input H5AD digest was not established")
    return output_sha256


def prepare_probe_input(
    *,
    payload_dir: str | Path,
    roster_path: str | Path,
    roster_receipt_path: str | Path,
    roster_receipt_sha256: str,
    approved_root: str | Path,
    out_h5ad: str | Path,
    out_manifest: str | Path,
    require_payload_sha256: bool = True,
) -> dict[str, object]:
    """Create one full-normalize-then-subset GEARS probe input."""
    if Path(out_h5ad).resolve(strict=False) == Path(out_manifest).resolve(strict=False):
        raise GeneUniverseError("probe input and manifest destinations must be distinct")
    if Path(out_manifest).exists() or Path(out_manifest).is_symlink():
        raise GeneUniverseError("probe manifest destination already exists")
    receipt = _load_roster_receipt(roster_receipt_path, expected_file_sha256=roster_receipt_sha256)
    payload = read_payload(str(payload_dir), require_expected_sha256=require_payload_sha256)
    fit_role = payload["fit_role_artifact"]
    projection = payload["response_projection"]
    spec = _fit_spec(fit_role)
    validate_fit_role_artifact(
        fit_role["path"],
        spec=spec,
        approved_root=str(approved_root),
        calibration_pair_ids=[tuple(pair) for pair in payload["calibration_pair_ids"]],
        sealed_pair_ids=[tuple(pair) for pair in payload["pair_ids"]],
        single_gene_ids=[str(gene) for gene in payload["single_gene_ids"]],
    )
    source = read_verified_fit_role_artifact(
        fit_role["path"], spec=spec, approved_root=str(approved_root)
    )
    roster_file_sha256 = str(receipt["roster_file_sha256"])
    roster = load_gears_gene_roster(roster_path, expected_file_sha256=roster_file_sha256)
    if roster.provenance["fit_artifact_content_sha256"] != fit_role["content_manifest_sha256"]:
        raise GeneUniverseError("roster is not bound to the verified fit-role artifact")
    if roster.provenance["raw_data_sha256"] != fit_role["raw_data_sha256"]:
        raise GeneUniverseError("roster raw-data identity differs from the fit-role artifact")
    receipt_bindings = {
        "preparation_dependency_lock_sha256": _preparation_dependency_lock_sha256(),
        "gears_dependency_lock_sha256": _gears_dependency_lock_sha256(),
        "driver_code_sha256": sha256_bytes(
            _stable_bytes(Path(__file__).resolve(), label="GEARS probe driver source")
        ),
        "fit_artifact_content_sha256": fit_role["content_manifest_sha256"],
        "generator_code_sha256": _generator_code_sha256(),
        "n_target": roster.n_target,
        "ordered_roster_sha256": roster.ordered_roster_sha256,
        "payload_sha256": canonical_payload_sha256(payload),
        "response_artifact_sha256": projection["response_artifact_sha256"],
        "roster_artifact_checksum": roster.artifact_checksum,
    }
    for field, expected_value in receipt_bindings.items():
        if receipt[field] != expected_value:
            raise GeneUniverseError(f"roster receipt {field} differs from verified inputs")

    full_genes = [str(gene) for gene in source.var_names]
    transformed = normalize_full_then_subset(
        source.X,
        full_gene_order=full_genes,
        response_projection=projection,
        roster=roster,
    )
    transformed = sparse.csr_matrix(transformed, dtype=np.float32, copy=True)
    transformed.sum_duplicates()
    transformed.eliminate_zeros()
    transformed.sort_indices()
    if not transformed.has_canonical_format or not np.isfinite(transformed.data).all():
        raise GeneUniverseError("Probe-A transformed matrix is not finite canonical CSR")
    normalization_target = float(projection["median_library"])
    probe = ad.AnnData(
        X=transformed,
        obs=source.obs.copy(),
        var=pd.DataFrame(index=list(roster.ordered_roster)),
    )
    probe.uns["schema"] = _ADATA_SCHEMA
    probe.uns["expression_scale"] = _PROBE_INPUT_TRANSFORM
    probe.uns["normalization_target"] = normalization_target
    probe.uns["fit_artifact_content_sha256"] = fit_role["content_manifest_sha256"]
    probe.uns["full_var_order_sha256"] = fit_role["gene_order_sha256"]
    probe.uns["response_artifact_sha256"] = projection["response_artifact_sha256"]
    probe.uns["roster_artifact_checksum"] = roster.artifact_checksum
    probe.uns["ordered_roster_sha256"] = roster.ordered_roster_sha256
    probe.uns["probe_driver_code_sha256"] = receipt["driver_code_sha256"]
    probe.uns["probe_runtime_fingerprint_sha256"] = _runtime_fingerprint_sha256()
    probe.uns["roster_receipt_sha256"] = roster_receipt_sha256
    matrix_identity = _matrix_identity(probe.X, label="prepared Probe-A matrix")
    selected_source_row_ids = probe.obs["source_row_id"].astype(str).tolist()
    selected_source_row_ids_sha256 = sha256_json(selected_source_row_ids)
    role_contract = {
        "calibration_pair_ids": _canonical_pair_roster(
            payload["calibration_pair_ids"], label="calibration_pair_ids"
        ),
        "combo_separator": "_",
        "control_token": "control",
        "sealed_pair_ids": _canonical_pair_roster(payload["pair_ids"], label="sealed_pair_ids"),
        "single_gene_ids": sorted(
            {str(gene) for gene in payload["single_gene_ids"]},
            key=lambda gene: gene.encode("utf-8"),
        ),
    }
    _role_token_sets(role_contract)
    probe.uns["matrix_dtype"] = PROBE_MATRIX_DTYPE
    probe.uns["matrix_format"] = PROBE_MATRIX_FORMAT
    probe.uns["matrix_logical_sha256"] = matrix_identity["logical_csr_sha256"]
    probe.uns["selected_source_row_ids_sha256"] = selected_source_row_ids_sha256
    probe.uns["preparation_dependency_lock_sha256"] = receipt["preparation_dependency_lock_sha256"]
    probe.uns["gears_dependency_lock_sha256"] = receipt["gears_dependency_lock_sha256"]

    destination = Path(out_h5ad)
    output_h5ad_sha256 = _atomic_write_h5ad(probe, destination)
    core = {
        "expression_scale": _PROBE_INPUT_TRANSFORM,
        "fit_artifact_content_sha256": fit_role["content_manifest_sha256"],
        "full_var_order_sha256": fit_role["gene_order_sha256"],
        "gears_dependency_lock_sha256": receipt["gears_dependency_lock_sha256"],
        "matrix_dtype": PROBE_MATRIX_DTYPE,
        "matrix_format": PROBE_MATRIX_FORMAT,
        "matrix_logical_sha256": matrix_identity["logical_csr_sha256"],
        "n_cells": int(probe.n_obs),
        "n_genes": int(probe.n_vars),
        "normalization_target": normalization_target,
        "ordered_roster_sha256": roster.ordered_roster_sha256,
        "output_h5ad_sha256": output_h5ad_sha256,
        "payload_sha256": canonical_payload_sha256(payload),
        "preparation_dependency_lock_sha256": receipt["preparation_dependency_lock_sha256"],
        "probe_driver_code_sha256": receipt["driver_code_sha256"],
        "probe_runtime_fingerprint_sha256": probe.uns["probe_runtime_fingerprint_sha256"],
        "response_artifact_sha256": projection["response_artifact_sha256"],
        "role_contract": role_contract,
        "role_counts": dict(fit_role["role_counts"]),
        "roster_artifact_checksum": roster.artifact_checksum,
        "roster_file_sha256": roster_file_sha256,
        "roster_receipt_sha256": roster_receipt_sha256,
        "row_identity_sha256": fit_role["row_identity_sha256"],
        "selected_source_row_ids_sha256": selected_source_row_ids_sha256,
        "schema": _MANIFEST_SCHEMA,
    }
    manifest = {**core, "manifest_checksum": sha256_json(core)}
    atomic_write_once(out_manifest, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def verify_probe_input(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    h5ad_path: str | Path,
    roster_path: str | Path,
    roster_receipt_path: str | Path,
) -> dict[str, object]:
    """Offline-verify a prepared probe input and its complete identity chain."""
    try:
        manifest_bytes = _stable_bytes(manifest_path, label="probe manifest")
        expected_manifest_sha256 = _require_sha256(
            expected_manifest_sha256, label="probe manifest expected SHA-256"
        )
        if sha256_bytes(manifest_bytes) != expected_manifest_sha256:
            raise GeneUniverseError("probe manifest file SHA-256 mismatch")
        manifest_text = manifest_bytes.decode("utf-8")
        manifest = json.loads(manifest_text)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GeneUniverseError(f"cannot read probe manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != _MANIFEST_SCHEMA:
        raise GeneUniverseError("probe manifest schema is invalid")
    expected_keys = {
        "expression_scale",
        "fit_artifact_content_sha256",
        "full_var_order_sha256",
        "gears_dependency_lock_sha256",
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
        "preparation_dependency_lock_sha256",
        "gears_dependency_lock_sha256",
        "schema",
    }
    if set(manifest) != expected_keys:
        raise GeneUniverseError("probe manifest has an unexpected key set")
    checksum = manifest.get("manifest_checksum")
    core = dict(manifest)
    core.pop("manifest_checksum", None)
    if checksum != sha256_json(core):
        raise GeneUniverseError("probe manifest checksum mismatch")
    canonical_manifest = json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if manifest_text != canonical_manifest:
        raise GeneUniverseError("probe manifest is not canonical JSON")
    sha_fields = {
        "fit_artifact_content_sha256",
        "full_var_order_sha256",
        "gears_dependency_lock_sha256",
        "matrix_logical_sha256",
        "ordered_roster_sha256",
        "output_h5ad_sha256",
        "payload_sha256",
        "preparation_dependency_lock_sha256",
        "probe_driver_code_sha256",
        "probe_runtime_fingerprint_sha256",
        "response_artifact_sha256",
        "roster_artifact_checksum",
        "roster_file_sha256",
        "roster_receipt_sha256",
        "row_identity_sha256",
        "selected_source_row_ids_sha256",
    }
    for field in sha_fields:
        _require_sha256(manifest[field], label=f"probe manifest {field}")
    for field in ("n_cells", "n_genes"):
        value = manifest[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise GeneUniverseError(f"probe manifest {field} must be a positive integer")
    role_counts = manifest["role_counts"]
    allowed_roles = {"control", "singles", "combo_calibration"}
    if (
        not isinstance(role_counts, dict)
        or not role_counts
        or not set(role_counts) <= allowed_roles
        or any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in role_counts.values()
        )
        or sum(role_counts.values()) != manifest["n_cells"]
    ):
        raise GeneUniverseError("probe manifest role_counts are invalid")
    normalization_target = manifest["normalization_target"]
    if (
        isinstance(normalization_target, bool)
        or not isinstance(normalization_target, (int, float))
        or not np.isfinite(normalization_target)
        or normalization_target <= 0
    ):
        raise GeneUniverseError("probe manifest normalization_target must be positive and finite")
    if manifest["expression_scale"] != _PROBE_INPUT_TRANSFORM:
        raise GeneUniverseError("probe manifest expression scale is invalid")
    if (
        manifest["matrix_dtype"] != PROBE_MATRIX_DTYPE
        or manifest["matrix_format"] != PROBE_MATRIX_FORMAT
    ):
        raise GeneUniverseError("probe manifest matrix storage contract is invalid")
    receipt = _load_roster_receipt(
        roster_receipt_path, expected_file_sha256=manifest["roster_receipt_sha256"]
    )
    for field in (
        "fit_artifact_content_sha256",
        "ordered_roster_sha256",
        "payload_sha256",
        "response_artifact_sha256",
        "roster_artifact_checksum",
        "roster_file_sha256",
        "preparation_dependency_lock_sha256",
        "gears_dependency_lock_sha256",
    ):
        if receipt[field] != manifest[field]:
            raise GeneUniverseError(f"roster receipt {field} differs from probe manifest")
    current_driver_sha256 = sha256_bytes(
        _stable_bytes(Path(__file__).resolve(), label="GEARS probe driver source")
    )
    if manifest["probe_driver_code_sha256"] != current_driver_sha256:
        raise GeneUniverseError("probe manifest was produced by a different driver")
    roster = load_gears_gene_roster(
        roster_path, expected_file_sha256=manifest["roster_file_sha256"]
    )
    if (
        roster.artifact_checksum != manifest["roster_artifact_checksum"]
        or roster.ordered_roster_sha256 != manifest["ordered_roster_sha256"]
    ):
        raise GeneUniverseError("roster semantic identity differs from probe manifest")
    snapshot = _read_verified_probe_h5ad(h5ad_path, expected_sha256=manifest["output_h5ad_sha256"])
    assert_gears_roster_matches(snapshot.var_names, roster)
    if snapshot.uns.get("schema") != _ADATA_SCHEMA:
        raise GeneUniverseError("probe input AnnData schema is invalid")
    if snapshot.uns.get("expression_scale") != _PROBE_INPUT_TRANSFORM:
        raise GeneUniverseError("probe input expression scale is invalid")
    if snapshot.uns.get("normalization_target") != normalization_target:
        raise GeneUniverseError("probe input normalization target differs from manifest")
    if snapshot.shape != (manifest["n_cells"], manifest["n_genes"]):
        raise GeneUniverseError("probe input shape differs from manifest")
    if not sparse.isspmatrix_csr(snapshot.X) or np.dtype(snapshot.X.dtype) != np.dtype("<f4"):
        raise GeneUniverseError("probe input matrix is not canonical CSR float32")
    if not snapshot.X.has_sorted_indices or not snapshot.X.has_canonical_format:
        raise GeneUniverseError("probe input CSR storage is not canonical")
    if (
        _matrix_identity(snapshot.X, label="verified Probe-A matrix")["logical_csr_sha256"]
        != manifest["matrix_logical_sha256"]
    ):
        raise GeneUniverseError("probe input matrix digest differs from manifest")
    role_contract = manifest["role_contract"]
    required_role_contract_keys = {
        "calibration_pair_ids",
        "combo_separator",
        "control_token",
        "sealed_pair_ids",
        "single_gene_ids",
    }
    if not isinstance(role_contract, dict) or set(role_contract) != required_role_contract_keys:
        raise GeneUniverseError("probe manifest role contract is invalid")
    calibration_pairs = _canonical_pair_roster(
        role_contract["calibration_pair_ids"], label="role_contract.calibration_pair_ids"
    )
    sealed_pairs = _canonical_pair_roster(
        role_contract["sealed_pair_ids"], label="role_contract.sealed_pair_ids"
    )
    if (
        calibration_pairs != role_contract["calibration_pair_ids"]
        or sealed_pairs != role_contract["sealed_pair_ids"]
    ):
        raise GeneUniverseError("probe manifest role pair rosters are not canonical")
    if set(map(tuple, calibration_pairs)) & set(map(tuple, sealed_pairs)):
        raise GeneUniverseError("probe manifest calibration/sealed pair rosters overlap")
    singles = role_contract["single_gene_ids"]
    if (
        not isinstance(singles, list)
        or not singles
        or any(not isinstance(gene, str) or not gene for gene in singles)
        or singles != sorted(set(singles), key=lambda gene: gene.encode("utf-8"))
    ):
        raise GeneUniverseError("probe manifest single-gene roster is invalid")
    control_token = role_contract["control_token"]
    combo_separator = role_contract["combo_separator"]
    if (
        not isinstance(control_token, str)
        or not control_token
        or not isinstance(combo_separator, str)
        or not combo_separator
    ):
        raise GeneUniverseError("probe manifest role tokens are invalid")
    calibration_tokens, sealed_tokens, single_set = _role_token_sets(role_contract)
    expected_roles: list[str] = []
    for perturbation in snapshot.obs["perturbation"].astype(str):
        if perturbation == control_token:
            expected_roles.append("control")
        elif perturbation in sealed_tokens:
            raise GeneUniverseError("probe input contains sealed combo rows")
        elif perturbation in calibration_tokens:
            expected_roles.append("combo_calibration")
        elif perturbation in single_set:
            expected_roles.append("singles")
        else:
            raise GeneUniverseError("probe input contains an unregistered single row")
    if expected_roles != snapshot.obs["role"].astype(str).tolist():
        raise GeneUniverseError("probe input roles differ from metadata-derived roles")
    observed_roles = {role: 0 for role in manifest["role_counts"]}
    for role in snapshot.obs["role"].astype(str):
        if role not in observed_roles:
            raise GeneUniverseError("probe input contains an unexpected fit role")
        observed_roles[role] += 1
    if observed_roles != manifest["role_counts"]:
        raise GeneUniverseError("probe input role counts differ from manifest")
    rows = list(
        zip(
            snapshot.obs["source_row_id"].astype(str),
            snapshot.obs["role"].astype(str),
            snapshot.obs["perturbation"].astype(str),
            strict=True,
        )
    )
    if row_identity_sha256(rows) != manifest["row_identity_sha256"]:
        raise GeneUniverseError("probe input row identity differs from manifest")
    if (
        sha256_json(snapshot.obs["source_row_id"].astype(str).tolist())
        != manifest["selected_source_row_ids_sha256"]
    ):
        raise GeneUniverseError("probe input selected source-row roster differs from manifest")
    for field in (
        "fit_artifact_content_sha256",
        "full_var_order_sha256",
        "ordered_roster_sha256",
        "probe_driver_code_sha256",
        "probe_runtime_fingerprint_sha256",
        "response_artifact_sha256",
        "roster_artifact_checksum",
        "roster_receipt_sha256",
        "matrix_dtype",
        "matrix_format",
        "matrix_logical_sha256",
        "selected_source_row_ids_sha256",
    ):
        if snapshot.uns.get(field) != manifest[field]:
            raise GeneUniverseError(f"probe input {field} differs from manifest")
    return manifest


def publish_probe_a_report(
    *,
    evidence_root: str | Path,
    raw_sample_path: str,
    raw_sample_sha256: str,
    registration_path: str | Path,
    registration_sha256: str,
    expected_git_commit: str,
    out_report: str | Path,
) -> str:
    """Derive and publish the canonical report from raw evidence only."""
    try:
        assert_clean_approved_checkout(expected_git_commit)
    except ValueError as exc:
        raise GeneUniverseError(str(exc)) from exc
    root = Path(evidence_root).resolve(strict=True)
    registration, registration_sha256 = _load_frozen_registration(
        evidence_root=root,
        registration_path=registration_path,
        registration_sha256=registration_sha256,
        expected_git_commit=expected_git_commit,
    )
    output = Path(out_report).resolve(strict=False)
    if output != root / REPORT_PATH:
        raise GeneUniverseError(f"Probe-A report must be {REPORT_PATH} under the evidence root")
    if output.exists() or output.is_symlink():
        raise GeneUniverseError("Probe-A report destination already exists")
    required = {
        "runtime_sha256": root / "runtime.json",
        "inputs_sha256": root / "inputs.json",
        "source_fingerprint_sha256": root / "probe_a_source.txt",
    }
    for path in required.values():
        if path.is_symlink() or not path.is_file():
            raise GeneUniverseError(f"Probe-A report dependency is missing or unsafe: {path.name}")
    report = build_probe_a_report(
        evidence_root=root,
        raw_sample_path=raw_sample_path,
        raw_sample_sha256=raw_sample_sha256,
        registration=registration,
        registration_sha256=registration_sha256,
        expected_git_commit=expected_git_commit,
        **{name: sha256_file(path) for name, path in required.items()},
    )
    encoded = canonical_file_bytes(report)
    atomic_write_once(output, encoded.decode("utf-8"))
    return sha256_bytes(encoded)


def publish_evidence_manifest(
    *, evidence_root: str | Path, expected_git_commit: str, out_manifest: str | Path
) -> str:
    """Close the pre-admission evidence tree with one exhaustive write-once manifest."""
    try:
        assert_clean_approved_checkout(expected_git_commit)
    except ValueError as exc:
        raise GeneUniverseError(str(exc)) from exc
    root = Path(evidence_root).resolve(strict=True)
    output = Path(out_manifest).resolve(strict=False)
    if output != root / "manifest.json":
        raise GeneUniverseError(
            "Probe-A evidence manifest must be manifest.json under evidence root"
        )
    if output.exists() or output.is_symlink():
        raise GeneUniverseError("Probe-A evidence manifest destination already exists")
    manifest = build_evidence_manifest(
        evidence_root=root,
        expected_git_commit=expected_git_commit,
    )
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise GeneUniverseError("Probe-A evidence manifest schema drifted")
    encoded = canonical_file_bytes(manifest)
    atomic_write_once(output, encoded.decode("utf-8"))
    return sha256_bytes(encoded)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    roster = commands.add_parser("build-roster")
    roster.add_argument("--payload-dir", required=True)
    roster.add_argument("--candidate-artifact", required=True)
    roster.add_argument("--candidate-artifact-sha256", required=True)
    roster.add_argument("--gene2go-nodes-artifact", required=True)
    roster.add_argument("--gene2go-nodes-artifact-sha256", required=True)
    roster.add_argument("--alias-artifact", required=True)
    roster.add_argument("--alias-artifact-sha256", required=True)
    roster.add_argument("--approved-root", required=True)
    roster.add_argument("--n-target", type=int, required=True)
    roster.add_argument("--out-report", required=True)
    roster.add_argument("--out-roster", required=True)
    roster.add_argument("--out-receipt", required=True)
    roster.add_argument("--allow-unbound-dev-payload", action="store_true")
    prepare = commands.add_parser("prepare-input")
    prepare.add_argument("--payload-dir", required=True)
    prepare.add_argument("--roster", required=True)
    prepare.add_argument("--roster-receipt", required=True)
    prepare.add_argument("--roster-receipt-sha256", required=True)
    prepare.add_argument("--approved-root", required=True)
    prepare.add_argument("--out-h5ad", required=True)
    prepare.add_argument("--out-manifest", required=True)
    prepare.add_argument(
        "--allow-unbound-dev-payload",
        action="store_true",
        help="fixture/dev only: allow a payload without the expected-SHA sidecar",
    )
    verify = commands.add_parser("verify-input")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--manifest-sha256", required=True)
    verify.add_argument("--h5ad", required=True)
    verify.add_argument("--roster", required=True)
    verify.add_argument("--roster-receipt", required=True)
    probe_a = commands.add_parser("probe-a")
    probe_a.add_argument("--payload-dir", required=True)
    probe_a.add_argument("--probe-a-registration", required=True)
    probe_a.add_argument("--probe-a-registration-sha256", required=True)
    probe_a.add_argument("--git-commit", required=True)
    probe_a.add_argument("--probe-manifest", required=True)
    probe_a.add_argument("--probe-manifest-sha256", required=True)
    probe_a.add_argument("--h5ad", required=True)
    probe_a.add_argument("--roster", required=True)
    probe_a.add_argument("--roster-receipt", required=True)
    probe_a.add_argument("--approved-root", required=True)
    probe_a.add_argument("--evidence-root", required=True)
    probe_a.add_argument("--out-raw", required=True)
    probe_a.add_argument("--checkpoint-dir", required=True)
    report = commands.add_parser("build-probe-a-report")
    report.add_argument("--evidence-root", required=True)
    report.add_argument("--raw-sample", required=True)
    report.add_argument("--raw-sample-sha256", required=True)
    report.add_argument("--probe-a-registration", required=True)
    report.add_argument("--probe-a-registration-sha256", required=True)
    report.add_argument("--git-commit", required=True)
    report.add_argument("--out-report", required=True)
    evidence_manifest = commands.add_parser("build-evidence-manifest")
    evidence_manifest.add_argument("--evidence-root", required=True)
    evidence_manifest.add_argument("--git-commit", required=True)
    evidence_manifest.add_argument("--out-manifest", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one maintained probe-preparation command."""
    args = _parser().parse_args(argv)
    if args.command == "build-roster":
        result = build_roster(
            payload_dir=args.payload_dir,
            candidate_artifact=args.candidate_artifact,
            candidate_artifact_sha256=args.candidate_artifact_sha256,
            gene2go_nodes_artifact=args.gene2go_nodes_artifact,
            gene2go_nodes_artifact_sha256=args.gene2go_nodes_artifact_sha256,
            alias_artifact=args.alias_artifact,
            alias_artifact_sha256=args.alias_artifact_sha256,
            approved_root=args.approved_root,
            n_target=args.n_target,
            out_report=args.out_report,
            out_roster=args.out_roster,
            out_receipt=args.out_receipt,
            require_payload_sha256=not args.allow_unbound_dev_payload,
        )
        _emit_command_result(
            command="build-roster",
            primary_file_sha256=result["receipt_file_sha256"],
        )
    elif args.command == "prepare-input":
        manifest = prepare_probe_input(
            payload_dir=args.payload_dir,
            roster_path=args.roster,
            roster_receipt_path=args.roster_receipt,
            roster_receipt_sha256=args.roster_receipt_sha256,
            approved_root=args.approved_root,
            out_h5ad=args.out_h5ad,
            out_manifest=args.out_manifest,
            require_payload_sha256=not args.allow_unbound_dev_payload,
        )
        _emit_command_result(
            command="prepare-input",
            primary_file_sha256=sha256_bytes(
                (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
                    "utf-8"
                )
            ),
        )
    elif args.command == "verify-input":
        verify_probe_input(
            manifest_path=args.manifest,
            expected_manifest_sha256=args.manifest_sha256,
            h5ad_path=args.h5ad,
            roster_path=args.roster,
            roster_receipt_path=args.roster_receipt,
        )
        _emit_command_result(
            command="verify-input",
            primary_file_sha256=args.manifest_sha256,
        )
    elif args.command == "probe-a":
        raw_sha256 = run_probe_a_measurements(
            payload_dir=args.payload_dir,
            registration_path=args.probe_a_registration,
            registration_sha256=args.probe_a_registration_sha256,
            expected_git_commit=args.git_commit,
            probe_manifest_path=args.probe_manifest,
            probe_manifest_sha256=args.probe_manifest_sha256,
            h5ad_path=args.h5ad,
            roster_path=args.roster,
            roster_receipt_path=args.roster_receipt,
            approved_root=args.approved_root,
            evidence_root=args.evidence_root,
            out_raw=args.out_raw,
            checkpoint_dir=args.checkpoint_dir,
        )
        _emit_command_result(command="probe-a", primary_file_sha256=raw_sha256)
    elif args.command == "build-probe-a-report":
        report_sha256 = publish_probe_a_report(
            evidence_root=args.evidence_root,
            raw_sample_path=args.raw_sample,
            raw_sample_sha256=args.raw_sample_sha256,
            registration_path=args.probe_a_registration,
            registration_sha256=args.probe_a_registration_sha256,
            expected_git_commit=args.git_commit,
            out_report=args.out_report,
        )
        _emit_command_result(command="build-probe-a-report", primary_file_sha256=report_sha256)
    else:
        manifest_sha256 = publish_evidence_manifest(
            evidence_root=args.evidence_root,
            expected_git_commit=args.git_commit,
            out_manifest=args.out_manifest,
        )
        # This closure command must not be appended to commands.jsonl after the
        # manifest hashes it; its digest is externally pinned and passed to the
        # offline verifier instead.
        _emit_command_result(command="build-evidence-manifest", primary_file_sha256=manifest_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
