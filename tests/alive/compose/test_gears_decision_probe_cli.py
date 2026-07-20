"""Local tests for the maintained, fit-role-only GEARS probe CLI."""

from __future__ import annotations

import importlib.util
import json
import pickle
import sys
from pathlib import Path
from types import SimpleNamespace

import anndata as ad
import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from alive.compose.baseline_subprocess import canonical_payload_sha256, read_payload
from alive.compose.gene_universe import (
    AliasMap,
    GeneUniverseError,
    compute_mandatory_report,
    generate_gears_gene_roster,
    normalize_full_then_subset,
)
from alive.provenance import sha256_file, sha256_json

_REPO = Path(__file__).resolve().parents[3]
_BUILDER = _REPO / "scripts/compose/build_dev_smoke_payload.py"
_PROBE = _REPO / "scripts/compose/gears_decision_probe.py"
_SHA = "a" * 64


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _source() -> ad.AnnData:
    rng = np.random.default_rng(4)
    genes = ["AAA", "BBB", "CCC", "DDD", "G4", "G5", "G6", "G7"]
    perts = ["control"] * 20
    for gene in ("AAA", "BBB", "CCC", "DDD"):
        perts += [gene] * 8
    for token in ("AAA_BBB", "AAA_CCC", "BBB_CCC", "CCC_DDD"):
        perts += [token] * 7
    counts = sparse.csr_matrix(rng.integers(0, 20, size=(len(perts), len(genes))))
    return ad.AnnData(
        X=counts,
        obs=pd.DataFrame({"perturbation": perts}, index=[f"row-{i}" for i in range(len(perts))]),
        var=pd.DataFrame(index=genes),
    )


def _empty_alias(tmp_path: Path) -> AliasMap:
    path = tmp_path / "aliases.json"
    path.write_text('{"aliases": [], "schema": "compose_gene_aliases_v1"}\n')
    return AliasMap.load(path, expected_sha256=sha256_file(path))


def _write_contract(path: Path, core: dict) -> Path:
    payload = {**core, "manifest_checksum": sha256_json(core)}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_provider_attestation(root: Path, probe, **overrides) -> Path:
    allocation = {
        "cpu_count": 8,
        "gpu_count": 1,
        "gpu_model": "NVIDIA A100-SXM4-80GB",
        "ram_bytes": 64 * 1024**3,
    }
    source_path = root / "logs/provider_control_plane.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text('{"pod":"unit-test-pod"}\n', encoding="utf-8")
    body = {
        "schema": "compose_provider_runtime_attestation_v1",
        "protocol": probe.PROTOCOL,
        "provider": "unit-test-provider",
        "pod_instance": "unit-test-pod",
        "attestation_id": "unit-test-attestation",
        "issued_at_utc": "2026-07-20T00:00:00Z",
        "source_evidence_type": "provider_api_response",
        "source_evidence_path": "logs/provider_control_plane.json",
        "source_evidence_sha256": sha256_file(source_path),
        "image_digest": "sha256:" + "b" * 64,
        "allocation": allocation,
    }
    for key, value in overrides.items():
        if key == "allocation":
            body["allocation"] = {**allocation, **value}
        else:
            body[key] = value
    payload = {**body, "self_checksum": sha256_json(body)}
    path = root / probe.PROVIDER_ATTESTATION_PATH
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def _write_runtime_sources(tmp_path: Path, *, version: int) -> tuple[Path, Path]:
    cgroup = tmp_path / f"cgroup-v{version}"
    cgroup.mkdir()
    if version == 2:
        (cgroup / "cgroup.controllers").write_text("cpu cpuset memory\n")
        (cgroup / "cpu.max").write_text("800000 100000\n")
        (cgroup / "cpuset.cpus.effective").write_text("0-7\n")
        (cgroup / "memory.max").write_text(f"{64 * 1024**3}\n")
    else:
        for controller in ("cpu", "cpuset", "memory"):
            (cgroup / controller).mkdir()
        (cgroup / "cpu/cpu.cfs_quota_us").write_text("800000\n")
        (cgroup / "cpu/cpu.cfs_period_us").write_text("100000\n")
        (cgroup / "cpuset/cpuset.cpus").write_text("0-7\n")
        (cgroup / "memory/memory.limit_in_bytes").write_text(f"{64 * 1024**3}\n")
    proc = tmp_path / f"proc-v{version}"
    proc.mkdir()
    (proc / "cpuinfo").write_text("processor : 0\nmodel name : Unit Test CPU\n")
    (proc / "meminfo").write_text("MemTotal:       67108864 kB\n")
    return cgroup, proc


def _patch_runtime_dependencies(probe, monkeypatch) -> None:
    monkeypatch.setattr(probe, "assert_clean_approved_checkout", lambda _commit: None)
    monkeypatch.setattr(probe.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        probe,
        "_collect_gpu_identity",
        lambda: {
            "gpu_model": "NVIDIA A100-SXM4-80GB",
            "gpu_uuid": "GPU-unit-test",
            "driver_version": "550.54.15",
            "cuda_version": "12.4",
        },
    )
    worker = SimpleNamespace(verify_probe_runtime_identity=lambda **_kwargs: "e" * 64)
    monkeypatch.setattr(
        probe,
        "_load_gears_worker_module",
        lambda: (worker, _REPO / "scripts/baselines/gears_worker.py"),
    )
    monkeypatch.setattr(probe, "_preparation_dependency_lock_sha256", lambda: "c" * 64)
    monkeypatch.setattr(probe, "_gears_dependency_lock_sha256", lambda: "d" * 64)
    monkeypatch.setattr(probe, "_runtime_fingerprint_sha256", lambda: "f" * 64)


def _pinned_gene2go_source(tmp_path: Path, probe, monkeypatch, genes: list[str]) -> dict:
    manifest = tmp_path / "go_resource_manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    source = tmp_path / "gene2go_all.pkl"
    source.write_bytes(pickle.dumps({gene: set() for gene in genes}, protocol=4))
    source_sha = sha256_file(source)
    monkeypatch.setattr(
        probe,
        "validate_go_resource_manifest",
        lambda _path: {"resources": [{"name": "gene2go_all.pkl", "sha256": source_sha}]},
    )
    return {
        "resource_manifest_path": manifest,
        "resource_manifest_sha256": sha256_file(manifest),
        "gene2go_source_path": source,
        "gene2go_source_sha256": source_sha,
    }


def _write_roster_receipt(path: Path, *, probe, payload: dict, roster, roster_path: Path) -> Path:
    core = {
        "alias_artifact_sha256": _SHA,
        "candidate_artifact_sha256": _SHA,
        "preparation_dependency_lock_sha256": probe._preparation_dependency_lock_sha256(),
        "gears_dependency_lock_sha256": probe._gears_dependency_lock_sha256(),
        "driver_code_sha256": sha256_file(_PROBE),
        "fit_artifact_content_sha256": payload["fit_role_artifact"]["content_manifest_sha256"],
        "gene2go_nodes_artifact_sha256": _SHA,
        "generator_code_sha256": probe._generator_code_sha256(),
        "n_target": roster.n_target,
        "ordered_roster_sha256": roster.ordered_roster_sha256,
        "payload_sha256": canonical_payload_sha256(payload),
        "report_file_sha256": _SHA,
        "response_artifact_sha256": payload["response_projection"]["response_artifact_sha256"],
        "runtime_fingerprint_sha256": probe._runtime_fingerprint_sha256(),
        "roster_artifact_checksum": roster.artifact_checksum,
        "roster_file_sha256": sha256_file(roster_path),
        "schema": "compose_gears_roster_receipt_v2",
    }
    return _write_contract(path, core)


def _build_inputs(tmp_path: Path, probe):
    builder = _load(_BUILDER, "_probe_test_builder")
    manifest = builder.build_dev_smoke_payload(
        _source(),
        out_dir=str(tmp_path / "payload"),
        artifact_path=str(tmp_path / "approved" / "fit_role.h5ad"),
        control_token="control",
        combo_sep="_",
        n_hvg=5,
        pca_dim=3,
        seed=11,
        n_sealed=1,
        n_calibration=2,
    )
    payload = read_payload(str(tmp_path / "payload"), require_expected_sha256=False)
    fit_role = payload["fit_role_artifact"]
    snapshot = ad.read_h5ad(manifest["artifact_path"])
    genes = [str(gene) for gene in snapshot.var_names]
    candidates = [str(gene) for gene in payload["single_gene_ids"]]
    candidates += ["_".join(pair) for pair in payload["calibration_pair_ids"]]
    report = compute_mandatory_report(
        full_var=genes,
        fit_artifact_identity=fit_role,
        response_projection=payload["response_projection"],
        perturbation_candidates=candidates,
        gene2go=set(genes),
        gene2go_sha256=_SHA,
        alias=_empty_alias(tmp_path),
    )
    control = snapshot[snapshot.obs["role"].astype(str) == "control"].X
    roster_path = tmp_path / "roster.json"
    roster = generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=control,
        control_row_identity_sha256=_SHA,
        generator_code_sha256=probe._generator_code_sha256(),
        n_target=max(report.mandatory_size, 6),
        out_path=roster_path,
    )
    receipt_path = _write_roster_receipt(
        tmp_path / "roster_receipt.json",
        probe=probe,
        payload=payload,
        roster=roster,
        roster_path=roster_path,
    )
    return payload, snapshot, roster, roster_path, receipt_path


def test_probe_cli_prepares_only_verified_fit_rows_and_verifies_offline(tmp_path, monkeypatch):
    probe = _load(_PROBE, "_probe_test_cli")
    payload, source, roster, roster_path, receipt_path = _build_inputs(tmp_path, probe)
    output = tmp_path / "probe_input.h5ad"
    manifest_path = tmp_path / "probe_manifest.json"

    result = probe.prepare_probe_input(
        payload_dir=tmp_path / "payload",
        roster_path=roster_path,
        roster_receipt_path=receipt_path,
        roster_receipt_sha256=sha256_file(receipt_path),
        approved_root=tmp_path / "approved",
        out_h5ad=output,
        out_manifest=manifest_path,
        require_payload_sha256=False,
    )
    producer_runtime_sha256 = result["probe_runtime_fingerprint_sha256"]
    monkeypatch.setattr(probe, "_runtime_fingerprint_sha256", lambda: "f" * 64)
    verified = probe.verify_probe_input(
        manifest_path=manifest_path,
        expected_manifest_sha256=sha256_file(manifest_path),
        h5ad_path=output,
        roster_path=roster_path,
        roster_receipt_path=receipt_path,
    )
    with pytest.raises(GeneUniverseError, match="manifest file SHA-256 mismatch"):
        probe.verify_probe_input(
            manifest_path=manifest_path,
            expected_manifest_sha256=_SHA,
            h5ad_path=output,
            roster_path=roster_path,
            roster_receipt_path=receipt_path,
        )
    forged_manifest_path = tmp_path / "forged_probe_manifest.json"
    forged_manifest = json.loads(manifest_path.read_text())
    forged_manifest["payload_sha256"] = "e" * 64
    forged_core = {
        key: value for key, value in forged_manifest.items() if key != "manifest_checksum"
    }
    forged_manifest["manifest_checksum"] = sha256_json(forged_core)
    forged_manifest_path.write_text(
        json.dumps(forged_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(GeneUniverseError, match="payload_sha256 differs"):
        probe.verify_probe_input(
            manifest_path=forged_manifest_path,
            expected_manifest_sha256=sha256_file(forged_manifest_path),
            h5ad_path=output,
            roster_path=roster_path,
            roster_receipt_path=receipt_path,
        )
    malformed_manifest_path = tmp_path / "malformed_probe_manifest.json"
    malformed_manifest = json.loads(manifest_path.read_text())
    malformed_manifest["role_counts"] = ["control"]
    malformed_core = {
        key: value for key, value in malformed_manifest.items() if key != "manifest_checksum"
    }
    malformed_manifest["manifest_checksum"] = sha256_json(malformed_core)
    malformed_manifest_path.write_text(
        json.dumps(malformed_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(GeneUniverseError, match="role_counts are invalid"):
        probe.verify_probe_input(
            manifest_path=malformed_manifest_path,
            expected_manifest_sha256=sha256_file(malformed_manifest_path),
            h5ad_path=output,
            roster_path=roster_path,
            roster_receipt_path=receipt_path,
        )
    observed = ad.read_h5ad(output)
    expected = normalize_full_then_subset(
        source.X,
        full_gene_order=source.var_names,
        response_projection=payload["response_projection"],
        roster=roster,
    )

    assert verified == result
    assert observed.obs_names.tolist() == source.obs_names.tolist()
    assert observed.var_names.tolist() == list(roster.ordered_roster)
    assert sparse.isspmatrix_csr(observed.X)
    assert observed.X.dtype == np.dtype("float32")
    assert np.allclose(observed.X.toarray(), expected.toarray())
    assert set(observed.obs["role"].astype(str)) <= {
        "control",
        "singles",
        "combo_calibration",
    }
    assert result["expression_scale"] == "full_library_normalize_log1p_then_roster_subset"
    assert result["normalization_target"] == payload["response_projection"]["median_library"]
    assert observed.uns["normalization_target"] == result["normalization_target"]
    assert observed.uns["roster_receipt_sha256"] == sha256_file(receipt_path)
    assert observed.uns["probe_runtime_fingerprint_sha256"] == producer_runtime_sha256

    forged_target_h5ad = tmp_path / "forged_target.h5ad"
    observed.uns["normalization_target"] = float(result["normalization_target"]) + 1.0
    observed.write_h5ad(forged_target_h5ad)
    forged_target_manifest = json.loads(manifest_path.read_text())
    forged_target_manifest["output_h5ad_sha256"] = sha256_file(forged_target_h5ad)
    forged_target_core = {
        key: value for key, value in forged_target_manifest.items() if key != "manifest_checksum"
    }
    forged_target_manifest["manifest_checksum"] = sha256_json(forged_target_core)
    forged_target_manifest_path = tmp_path / "forged_target_manifest.json"
    forged_target_manifest_path.write_text(
        json.dumps(forged_target_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(GeneUniverseError, match="normalization target differs"):
        probe.verify_probe_input(
            manifest_path=forged_target_manifest_path,
            expected_manifest_sha256=sha256_file(forged_target_manifest_path),
            h5ad_path=forged_target_h5ad,
            roster_path=roster_path,
            roster_receipt_path=receipt_path,
        )


def test_probe_cli_builds_roster_only_from_verified_contract_artifacts(tmp_path, monkeypatch):
    probe = _load(_PROBE, "_probe_test_roster_cli")
    payload, source, _roster, _roster_path, _receipt_path = _build_inputs(tmp_path, probe)
    candidate_core = {
        "schema": "compose_perturbation_candidates_v1",
        "source_manifest_sha256": _SHA,
        "tokens": [str(gene) for gene in payload["single_gene_ids"]],
    }
    candidates = _write_contract(tmp_path / "candidates.json", candidate_core)
    gene2go_source = _pinned_gene2go_source(
        tmp_path, probe, monkeypatch, [str(gene) for gene in source.var_names]
    )
    gene2go_core = {
        "genes": sorted(
            [str(gene) for gene in source.var_names], key=lambda gene: gene.encode("utf-8")
        ),
        "schema": "compose_gene2go_nodes_v1",
        "source_gene2go_sha256": gene2go_source["gene2go_source_sha256"],
    }
    gene2go = _write_contract(tmp_path / "gene2go.json", gene2go_core)
    alias = tmp_path / "aliases.json"
    report_path = tmp_path / "mandatory_report.json"
    roster_path = tmp_path / "cli_roster.json"
    receipt_path = tmp_path / "cli_roster_receipt.json"

    result = probe.build_roster(
        payload_dir=tmp_path / "payload",
        candidate_artifact=candidates,
        candidate_artifact_sha256=sha256_file(candidates),
        gene2go_nodes_artifact=gene2go,
        gene2go_nodes_artifact_sha256=sha256_file(gene2go),
        **gene2go_source,
        alias_artifact=alias,
        alias_artifact_sha256=sha256_file(alias),
        approved_root=tmp_path / "approved",
        n_target=8,
        out_report=report_path,
        out_roster=roster_path,
        out_receipt=receipt_path,
        require_payload_sha256=False,
    )

    assert result["report"]["perturbation_candidate_sha256"] == _SHA
    assert result["roster"]["n_target"] == 8
    assert result["receipt"]["roster_file_sha256"] == sha256_file(roster_path)
    assert result["receipt"]["report_file_sha256"] == sha256_file(report_path)
    assert result["receipt_file_sha256"] == sha256_file(receipt_path)
    assert result["receipt"]["preparation_dependency_lock_sha256"] == (
        probe._preparation_dependency_lock_sha256()
    )
    assert result["receipt"]["gears_dependency_lock_sha256"] == (
        probe._gears_dependency_lock_sha256()
    )
    assert result["receipt"]["runtime_fingerprint_sha256"] == probe._runtime_fingerprint_sha256()
    assert report_path.is_file() and roster_path.is_file() and receipt_path.is_file()


def test_gene2go_nodes_must_exactly_match_activation_pinned_source(tmp_path, monkeypatch):
    probe = _load(_PROBE, "_probe_test_gene2go_source_binding")
    source = _pinned_gene2go_source(tmp_path, probe, monkeypatch, ["AAA", "BBB"])
    with pytest.raises(GeneUniverseError, match="differs from the pinned source key roster"):
        probe._validate_gene2go_nodes_against_pinned_source(
            nodes={
                "genes": ["AAA"],
                "source_gene2go_sha256": source["gene2go_source_sha256"],
            },
            **source,
        )

    with pytest.raises(GeneUniverseError, match="names the wrong source"):
        probe._validate_gene2go_nodes_against_pinned_source(
            nodes={"genes": ["AAA", "BBB"], "source_gene2go_sha256": "f" * 64},
            **source,
        )


def test_probe_cli_refuses_overwrite_and_tampered_roster_binding(tmp_path, monkeypatch):
    probe = _load(_PROBE, "_probe_test_cli_failclosed")
    _payload, _source_snapshot, _roster, roster_path, receipt_path = _build_inputs(tmp_path, probe)
    output = tmp_path / "probe_input.h5ad"
    manifest_path = tmp_path / "probe_manifest.json"
    kwargs = {
        "payload_dir": tmp_path / "payload",
        "roster_path": roster_path,
        "roster_receipt_path": receipt_path,
        "roster_receipt_sha256": sha256_file(receipt_path),
        "approved_root": tmp_path / "approved",
        "out_h5ad": output,
        "out_manifest": manifest_path,
        "require_payload_sha256": False,
    }
    probe.prepare_probe_input(**kwargs)
    with pytest.raises(GeneUniverseError, match="destination already exists"):
        probe.prepare_probe_input(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(probe, "_preparation_dependency_lock_sha256", lambda: "e" * 64)
        with pytest.raises(GeneUniverseError, match="preparation_dependency_lock_sha256 differs"):
            probe.prepare_probe_input(
                **{
                    **kwargs,
                    "out_h5ad": tmp_path / "wrong-lock.h5ad",
                    "out_manifest": tmp_path / "wrong-lock.json",
                }
            )

    other_path = tmp_path / "mismatched.json"
    # This assertion exercises the loader's tamper wall before any output is written.
    other_path.write_text(roster_path.read_text().replace(_SHA, "e" * 64, 1))
    with pytest.raises(GeneUniverseError):
        probe.prepare_probe_input(
            **{
                **kwargs,
                "roster_path": other_path,
                "out_h5ad": tmp_path / "other.h5ad",
                "out_manifest": tmp_path / "other.json",
            }
        )

    forged_receipt = tmp_path / "forged_receipt.json"
    forged_payload = json.loads(receipt_path.read_text())
    forged_payload["roster_file_sha256"] = sha256_file(other_path)
    forged_core = {
        key: value for key, value in forged_payload.items() if key != "manifest_checksum"
    }
    forged_payload["manifest_checksum"] = sha256_json(forged_core)
    forged_receipt.write_text(
        json.dumps(forged_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(GeneUniverseError, match="receipt file SHA-256 mismatch"):
        probe.prepare_probe_input(
            **{
                **kwargs,
                "roster_path": other_path,
                "roster_receipt_path": forged_receipt,
                "out_h5ad": tmp_path / "forged.h5ad",
                "out_manifest": tmp_path / "forged.json",
            }
        )


def test_command_result_emits_publication_boundary_digest(tmp_path, capsys):
    probe = _load(_PROBE, "_probe_test_command_result")
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}\n", encoding="utf-8")

    probe._emit_command_result(
        command="build-roster",
        primary_file_sha256=sha256_file(artifact),
    )

    observed = json.loads(capsys.readouterr().out)
    assert observed == {
        "command": "build-roster",
        "primary_file_sha256": sha256_file(artifact),
        "runtime_fingerprint_sha256": probe._runtime_fingerprint_sha256(),
        "schema": "compose_gears_probe_command_result_v1",
        "status": "OK",
    }


def test_multi_artifact_outputs_require_distinct_destinations(tmp_path):
    probe = _load(_PROBE, "_probe_test_distinct_outputs")
    shared = tmp_path / "shared-output"

    with pytest.raises(GeneUniverseError, match="roster output destinations must be distinct"):
        probe.build_roster(
            payload_dir=tmp_path / "missing-payload",
            candidate_artifact=tmp_path / "missing-candidates",
            candidate_artifact_sha256=_SHA,
            gene2go_nodes_artifact=tmp_path / "missing-go",
            gene2go_nodes_artifact_sha256=_SHA,
            resource_manifest_path=tmp_path / "missing-manifest",
            resource_manifest_sha256=_SHA,
            gene2go_source_path=tmp_path / "missing-gene2go",
            gene2go_source_sha256=_SHA,
            alias_artifact=tmp_path / "missing-alias",
            alias_artifact_sha256=_SHA,
            approved_root=tmp_path,
            n_target=1,
            out_report=shared,
            out_roster=shared,
            out_receipt=shared,
        )
    assert not shared.exists()

    with pytest.raises(GeneUniverseError, match="destinations must be distinct"):
        probe.prepare_probe_input(
            payload_dir=tmp_path / "missing-payload",
            roster_path=tmp_path / "missing-roster",
            roster_receipt_path=tmp_path / "missing-receipt",
            roster_receipt_sha256=_SHA,
            approved_root=tmp_path,
            out_h5ad=shared,
            out_manifest=shared,
        )
    assert not shared.exists()


def test_prepare_rejects_receipt_that_passes_file_sha_but_is_internally_inconsistent(tmp_path):
    """A receipt whose own file SHA is honest but whose contents are inconsistent fails closed.

    Covers the _contract_json / _load_roster_receipt rejection branches that the file-SHA gate
    would otherwise shadow when the caller passes the tampered file's own SHA.
    """
    probe = _load(_PROBE, "_probe_test_receipt_internal")
    _payload, _source, _roster, roster_path, receipt_path = _build_inputs(tmp_path, probe)
    base = dict(
        payload_dir=tmp_path / "payload",
        roster_path=roster_path,
        approved_root=tmp_path / "approved",
        require_payload_sha256=False,
    )

    def _run(name, receipt_file):
        probe.prepare_probe_input(
            **base,
            roster_receipt_path=receipt_file,
            roster_receipt_sha256=sha256_file(receipt_file),
            out_h5ad=tmp_path / f"{name}.h5ad",
            out_manifest=tmp_path / f"{name}.json",
        )

    # (a) manifest_checksum not recomputed after mutating a field -> checksum mismatch.
    bad_checksum = tmp_path / "bad_checksum_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["n_target"] = int(receipt["n_target"]) + 1
    bad_checksum.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(GeneUniverseError, match="manifest checksum mismatch"):
        _run("a", bad_checksum)

    # (b) valid checksum but compact (non-canonical) serialization.
    noncanonical = tmp_path / "noncanonical_receipt.json"
    noncanonical.write_text(json.dumps(json.loads(receipt_path.read_text())), encoding="utf-8")
    with pytest.raises(GeneUniverseError, match="not canonical JSON"):
        _run("b", noncanonical)

    # (c) internally consistent but n_target is not a positive integer.
    bad_ntarget = tmp_path / "bad_ntarget_receipt.json"
    _write_contract(
        bad_ntarget,
        {
            **{
                k: v
                for k, v in json.loads(receipt_path.read_text()).items()
                if k != "manifest_checksum"
            },
            "n_target": 0,
        },
    )
    with pytest.raises(GeneUniverseError, match="n_target must be a positive integer"):
        _run("c", bad_ntarget)

    # (d) internally consistent but a receipt SHA field is not a bare SHA-256.
    bad_sha = tmp_path / "bad_sha_receipt.json"
    _write_contract(
        bad_sha,
        {
            **{
                k: v
                for k, v in json.loads(receipt_path.read_text()).items()
                if k != "manifest_checksum"
            },
            "roster_file_sha256": "not-a-sha",
        },
    )
    with pytest.raises(GeneUniverseError, match="roster_file_sha256"):
        _run("d", bad_sha)


@pytest.mark.parametrize("cgroup_version", [1, 2])
def test_runtime_publication_binds_provider_and_cgroup_limits(
    tmp_path, monkeypatch, cgroup_version
):
    probe = _load(_PROBE, f"_probe_test_runtime_v{cgroup_version}")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    attestation = _write_provider_attestation(evidence, probe)
    cgroup, proc = _write_runtime_sources(tmp_path, version=cgroup_version)
    _patch_runtime_dependencies(probe, monkeypatch)

    output = evidence / "runtime.json"
    observed_sha = probe.publish_runtime_evidence(
        evidence_root=evidence,
        provider_attestation_path=attestation,
        provider_attestation_sha256=sha256_file(attestation),
        expected_git_commit="1" * 40,
        out_runtime=output,
        network_disabled=True,
        cgroup_root=cgroup,
        proc_root=proc,
    )

    runtime = json.loads(output.read_text())
    assert observed_sha == sha256_file(output)
    assert runtime["schema"] == "compose_gears_probe_runtime_v3"
    assert runtime["provider_attestation_sha256"] == sha256_file(attestation)
    assert runtime["provider_allocation"]["cpu_count"] == 8
    assert runtime["cgroup_effective"] == {
        "version": cgroup_version,
        "cpu_quota_us": 800000,
        "cpu_period_us": 100000,
        "cpu_quota_cores": 8.0,
        "cpuset_cpus": "0-7",
        "cpuset_cpu_count": 8,
        "effective_cpu_cores": 8.0,
        "memory_limit_bytes": 64 * 1024**3,
    }
    assert runtime["host_visible"] == {
        "cpu_model": "Unit Test CPU",
        "cpu_count": 8,
        "ram_bytes": 64 * 1024**3,
    }


@pytest.mark.parametrize(
    ("version", "relative", "replacement", "message"),
    [
        (2, "cpu.max", "max 100000\n", "CPU quota must be finite"),
        (2, "memory.max", "max\n", "memory limit must be finite"),
        (1, "cpu/cpu.cfs_quota_us", "-1\n", "CPU quota must be finite and positive"),
        (
            1,
            "memory/memory.limit_in_bytes",
            f"{1 << 60}\n",
            "memory limit is an unlimited sentinel",
        ),
    ],
)
def test_runtime_publication_rejects_unbounded_cgroups(
    tmp_path, monkeypatch, version, relative, replacement, message
):
    probe = _load(_PROBE, f"_probe_test_unbounded_{version}_{Path(relative).name}")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    attestation = _write_provider_attestation(evidence, probe)
    cgroup, proc = _write_runtime_sources(tmp_path, version=version)
    (cgroup / relative).write_text(replacement)
    _patch_runtime_dependencies(probe, monkeypatch)

    output = evidence / "runtime.json"
    with pytest.raises(GeneUniverseError, match=message):
        probe.publish_runtime_evidence(
            evidence_root=evidence,
            provider_attestation_path=attestation,
            provider_attestation_sha256=sha256_file(attestation),
            expected_git_commit="1" * 40,
            out_runtime=output,
            network_disabled=True,
            cgroup_root=cgroup,
            proc_root=proc,
        )
    assert not output.exists()


@pytest.mark.parametrize("cpuset", ["0-3,3-7", "0-03", "1,0", "0-", ""])
def test_runtime_publication_rejects_noncanonical_cpuset(tmp_path, cpuset):
    probe = _load(_PROBE, f"_probe_test_cpuset_{len(cpuset)}_{cpuset.count(',')}")
    cgroup, _proc = _write_runtime_sources(tmp_path, version=2)
    (cgroup / "cpuset.cpus.effective").write_text(cpuset + "\n")

    with pytest.raises(GeneUniverseError, match="cpuset|CPU list|empty"):
        probe._collect_cgroup_effective(cgroup)


def test_runtime_publication_rejects_unpinned_attestation_and_overwrite(tmp_path, monkeypatch):
    probe = _load(_PROBE, "_probe_test_runtime_pin_overwrite")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    attestation = _write_provider_attestation(evidence, probe)
    cgroup, proc = _write_runtime_sources(tmp_path, version=2)
    _patch_runtime_dependencies(probe, monkeypatch)
    output = evidence / "runtime.json"

    with pytest.raises(GeneUniverseError, match="attestation file SHA-256 mismatch"):
        probe.publish_runtime_evidence(
            evidence_root=evidence,
            provider_attestation_path=attestation,
            provider_attestation_sha256="0" * 64,
            expected_git_commit="1" * 40,
            out_runtime=output,
            network_disabled=True,
            cgroup_root=cgroup,
            proc_root=proc,
        )
    assert not output.exists()

    provider_source = evidence / "logs/provider_control_plane.json"
    original_source = provider_source.read_text(encoding="utf-8")
    provider_source.write_text('{"pod":"different"}\n', encoding="utf-8")
    with pytest.raises(GeneUniverseError, match="source evidence SHA-256 mismatch"):
        probe.publish_runtime_evidence(
            evidence_root=evidence,
            provider_attestation_path=attestation,
            provider_attestation_sha256=sha256_file(attestation),
            expected_git_commit="1" * 40,
            out_runtime=output,
            network_disabled=True,
            cgroup_root=cgroup,
            proc_root=proc,
        )
    provider_source.write_text(original_source, encoding="utf-8")
    assert not output.exists()

    linked_root = tmp_path / "linked-evidence"
    linked_root.symlink_to(evidence, target_is_directory=True)
    with pytest.raises(GeneUniverseError, match="evidence root must not be a symlink"):
        probe.publish_runtime_evidence(
            evidence_root=linked_root,
            provider_attestation_path=linked_root / probe.PROVIDER_ATTESTATION_PATH,
            provider_attestation_sha256=sha256_file(attestation),
            expected_git_commit="1" * 40,
            out_runtime=linked_root / "runtime.json",
            network_disabled=True,
            cgroup_root=cgroup,
            proc_root=proc,
        )
    assert not output.exists()

    kwargs = {
        "evidence_root": evidence,
        "provider_attestation_path": attestation,
        "provider_attestation_sha256": sha256_file(attestation),
        "expected_git_commit": "1" * 40,
        "out_runtime": output,
        "network_disabled": True,
        "cgroup_root": cgroup,
        "proc_root": proc,
    }
    probe.publish_runtime_evidence(**kwargs)
    with pytest.raises(GeneUniverseError, match="destination already exists"):
        probe.publish_runtime_evidence(**kwargs)


def test_runtime_publication_rejects_provider_gpu_mismatch(tmp_path, monkeypatch):
    probe = _load(_PROBE, "_probe_test_runtime_gpu_mismatch")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    attestation = _write_provider_attestation(
        evidence,
        probe,
        allocation={"gpu_model": "NVIDIA H100 80GB HBM3"},
    )
    cgroup, proc = _write_runtime_sources(tmp_path, version=2)
    _patch_runtime_dependencies(probe, monkeypatch)

    with pytest.raises(GeneUniverseError, match="differs from its provider attestation"):
        probe.publish_runtime_evidence(
            evidence_root=evidence,
            provider_attestation_path=attestation,
            provider_attestation_sha256=sha256_file(attestation),
            expected_git_commit="1" * 40,
            out_runtime=evidence / "runtime.json",
            network_disabled=True,
            cgroup_root=cgroup,
            proc_root=proc,
        )
