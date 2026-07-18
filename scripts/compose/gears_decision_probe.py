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
import json
import os
import platform
import stat
import sys
import tempfile
from pathlib import Path

import anndata as ad
import pandas as pd

from alive.compose.baseline_subprocess import canonical_payload_sha256, read_payload
from alive.compose.fit_role import (
    FitRoleArtifactSpec,
    read_verified_fit_role_artifact,
    row_identity_sha256,
    validate_fit_role_artifact,
)
from alive.compose.gears_probe_a import RAW_SCHEMA, validate_probe_a_raw_artifact
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

_MANIFEST_SCHEMA = "compose_gears_probe_input_manifest_v1"
_RECEIPT_SCHEMA = "compose_gears_roster_receipt_v1"
_ADATA_SCHEMA = "compose_gears_probe_input_v1"
_CANDIDATE_SCHEMA = "compose_perturbation_candidates_v1"
_GENE2GO_SCHEMA = "compose_gene2go_nodes_v1"
_COMMAND_RESULT_SCHEMA = "compose_gears_probe_command_result_v1"
_RECEIPT_KEYS = {
    "alias_artifact_sha256",
    "candidate_artifact_sha256",
    "driver_code_sha256",
    "dependency_lock_sha256",
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


def publish_probe_a_measurements(
    *, measurement_json: str | Path, evidence_root: str | Path, out_raw: str | Path
) -> str:
    """Publish and immediately revalidate the maintained Probe-A raw artifact.

    The measurement hook supplies numeric observations, ordered control-row
    identities, per-control predictions, and real checkpoint paths.  This
    maintained boundary owns the schema/checksum and refuses overwrite; the
    independent admission verifier later repeats every check against the
    exhaustive evidence manifest.
    """
    try:
        relative_output = (
            Path(out_raw).resolve().relative_to(Path(evidence_root).resolve(strict=True)).as_posix()
        )
    except (OSError, ValueError) as exc:
        raise GeneUniverseError(
            "Probe-A raw output must be under the existing evidence root"
        ) from exc
    data = _stable_bytes(measurement_json, label="Probe-A measurement hook output")
    try:
        measurement = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GeneUniverseError(f"cannot decode Probe-A measurement hook output: {exc}") from exc
    expected = {
        "input_before",
        "input_after",
        "determinism_runs",
        "ordered_control_row_ids",
        "control_predictions",
        "public_prediction",
        "bridge_prediction",
    }
    if not isinstance(measurement, dict) or set(measurement) != expected:
        raise GeneUniverseError("Probe-A measurement hook output key roster is invalid")
    body = {"schema": RAW_SCHEMA, **measurement}
    payload = {**body, "self_checksum": sha256_json(body)}
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")
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


def _dependency_lock_sha256() -> str:
    root = Path(__file__).resolve().parents[2]
    return sha256_bytes(_stable_bytes(root / "uv.lock", label="workspace dependency lock"))


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
        "dependency_lock_sha256": _dependency_lock_sha256(),
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
        "dependency_lock_sha256": _dependency_lock_sha256(),
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
    probe = ad.AnnData(
        X=transformed,
        obs=source.obs.copy(),
        var=pd.DataFrame(index=list(roster.ordered_roster)),
    )
    probe.uns["schema"] = _ADATA_SCHEMA
    probe.uns["expression_scale"] = "full_library_normalize_log1p_then_roster_subset"
    probe.uns["fit_artifact_content_sha256"] = fit_role["content_manifest_sha256"]
    probe.uns["full_var_order_sha256"] = fit_role["gene_order_sha256"]
    probe.uns["response_artifact_sha256"] = projection["response_artifact_sha256"]
    probe.uns["roster_artifact_checksum"] = roster.artifact_checksum
    probe.uns["ordered_roster_sha256"] = roster.ordered_roster_sha256
    probe.uns["probe_driver_code_sha256"] = receipt["driver_code_sha256"]
    probe.uns["probe_runtime_fingerprint_sha256"] = _runtime_fingerprint_sha256()
    probe.uns["roster_receipt_sha256"] = roster_receipt_sha256

    destination = Path(out_h5ad)
    output_h5ad_sha256 = _atomic_write_h5ad(probe, destination)
    core = {
        "expression_scale": "full_library_normalize_log1p_then_roster_subset",
        "fit_artifact_content_sha256": fit_role["content_manifest_sha256"],
        "full_var_order_sha256": fit_role["gene_order_sha256"],
        "n_cells": int(probe.n_obs),
        "n_genes": int(probe.n_vars),
        "ordered_roster_sha256": roster.ordered_roster_sha256,
        "output_h5ad_sha256": output_h5ad_sha256,
        "payload_sha256": canonical_payload_sha256(payload),
        "probe_driver_code_sha256": receipt["driver_code_sha256"],
        "probe_runtime_fingerprint_sha256": probe.uns["probe_runtime_fingerprint_sha256"],
        "response_artifact_sha256": projection["response_artifact_sha256"],
        "role_counts": dict(fit_role["role_counts"]),
        "roster_artifact_checksum": roster.artifact_checksum,
        "roster_file_sha256": roster_file_sha256,
        "roster_receipt_sha256": roster_receipt_sha256,
        "row_identity_sha256": fit_role["row_identity_sha256"],
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
        "manifest_checksum",
        "n_cells",
        "n_genes",
        "ordered_roster_sha256",
        "output_h5ad_sha256",
        "payload_sha256",
        "probe_driver_code_sha256",
        "probe_runtime_fingerprint_sha256",
        "response_artifact_sha256",
        "role_counts",
        "roster_artifact_checksum",
        "roster_file_sha256",
        "roster_receipt_sha256",
        "row_identity_sha256",
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
    if manifest["expression_scale"] != "full_library_normalize_log1p_then_roster_subset":
        raise GeneUniverseError("probe manifest expression scale is invalid")
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
    if snapshot.uns.get("expression_scale") != "full_library_normalize_log1p_then_roster_subset":
        raise GeneUniverseError("probe input expression scale is invalid")
    if snapshot.shape != (manifest["n_cells"], manifest["n_genes"]):
        raise GeneUniverseError("probe input shape differs from manifest")
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
    for field in (
        "fit_artifact_content_sha256",
        "full_var_order_sha256",
        "ordered_roster_sha256",
        "probe_driver_code_sha256",
        "probe_runtime_fingerprint_sha256",
        "response_artifact_sha256",
        "roster_artifact_checksum",
        "roster_receipt_sha256",
    ):
        if snapshot.uns.get(field) != manifest[field]:
            raise GeneUniverseError(f"probe input {field} differs from manifest")
    return manifest


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
    probe_a.add_argument("--measurement-json", required=True)
    probe_a.add_argument("--evidence-root", required=True)
    probe_a.add_argument("--out-raw", required=True)
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
    else:
        raw_sha256 = publish_probe_a_measurements(
            measurement_json=args.measurement_json,
            evidence_root=args.evidence_root,
            out_raw=args.out_raw,
        )
        _emit_command_result(command="probe-a", primary_file_sha256=raw_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
