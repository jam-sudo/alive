"""Local tests for the maintained, fit-role-only GEARS probe CLI."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

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


def test_probe_cli_builds_roster_only_from_verified_contract_artifacts(tmp_path):
    probe = _load(_PROBE, "_probe_test_roster_cli")
    payload, source, _roster, _roster_path, _receipt_path = _build_inputs(tmp_path, probe)
    candidate_core = {
        "schema": "compose_perturbation_candidates_v1",
        "source_manifest_sha256": _SHA,
        "tokens": [str(gene) for gene in payload["single_gene_ids"]],
    }
    candidates = _write_contract(tmp_path / "candidates.json", candidate_core)
    gene2go_core = {
        "genes": [str(gene) for gene in source.var_names],
        "schema": "compose_gene2go_nodes_v1",
        "source_gene2go_sha256": _SHA,
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
