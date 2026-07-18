"""Test-only builder for a synthetic-but-valid COMPOSE *scientific* stage-1 corpus.

Produces a ``mode="scientific"`` ResolvedRunSpec + every declared non-sealed artifact, reusing
the committed fixture builder's DETERMINISTIC serializers (spec §6). It NEVER modifies the
production fixture builder: the committed fixture artifact keeps ``source_kind='synthetic_fixture'``
byte-for-byte, whereas this corpus declares ``source_kind='audited_unsealed'``, an ACTIVATED
test-only config with every activation blocker resolved, config-bound activation reports embedding
that config's SHA/protocol, and the exact nested scientific block. It opens no seal and constructs
no store.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from alive.compose.approximation_bias import (
    APPROXIMATION_BIAS_SCHEMA,
    NON_FINITE,
    PROTOCOL,
    REPRESENTATION,
    canonical_json,
    measurement_contract_sha256,
    self_checksum,
)
from alive.compose.config2 import load_compose_phase2_config
from alive.compose.datacard import compute_compose_run_id
from alive.compose.driver import fixture_builder as fb
from alive.compose.driver.pair_index import ATTESTATION_SCHEMA, PAIR_INDEX_MANIFEST_SCHEMA
from alive.compose.driver.run_spec import (
    EXPECTED_HASHES_KEYS,
    PRE_SEAL_PATH_FIELDS,
    RESOLVED_RUN_SPEC_SCHEMA,
    RUN_PRODUCED_BASENAMES,
)
from alive.compose.fit_role import build_response_projection
from alive.compose.split import ROLE_NAMES, build_split_manifest
from alive.provenance import sha256_file, sha256_json

_CANON_CONFIG = "configs/compose_k562_v1_phase2.yaml"
_EVIDENCE_ROOT = Path("docs/activation-evidence/compose")

# Committed evidence templates whose bytes/lineage this corpus copies + overrides to READY.
_CONFIG_BOUND = (
    "real_norman_phi_rank_and_condition_report",
    "regime_specific_detectable_effect_analysis",
)


@dataclass(frozen=True)
class ScientificCarrierBundle:
    spec_path: Path
    approved_artifacts_root: Path
    run_dir: Path
    audit_path: Path
    repo_root: Path
    approved_git_sha: str
    config_sha256: str
    activation_requirements: tuple[str, ...]


def init_synthetic_repo(repo_root: Path) -> str:
    """Init a clean committed git repo (no shell) and return its HEAD sha."""
    repo_root.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=repo_root, capture_output=True, text=True, check=True, env=env
        )

    run("init", "-q")
    run("config", "user.email", "test@example.invalid")
    run("config", "user.name", "compose-test")
    (repo_root / "README").write_text("compose scientific carrier test repo\n", encoding="utf-8")
    run("add", "README")
    run("commit", "-q", "-m", "init")
    return run("rev-parse", "HEAD").stdout.strip()


def _write_activated_config(stage1: Path, *, approved_git_sha: str) -> tuple[Any, Path, str, Path]:
    """Write + load an ACTIVATED test-only config with all local blockers resolved."""
    raw = yaml.safe_load(Path(_CANON_CONFIG).read_text(encoding="utf-8"))
    raw["status"] = "active"
    raw["regimes"]["power_status"] = "established_from_registered_report"
    raw["baselines"]["gears"]["revision"] = "cell-gears==0.1.2"
    raw["baselines"]["gears"]["environment_status"] = "pinned_and_fresh_sync_verified"
    raw["baselines"]["cpa"]["revision"] = "cpa-tools==0.8.5"
    raw["baselines"]["cpa"]["environment_status"] = "pinned_and_fresh_sync_verified"
    raw["baselines"]["gears"]["approximation_bias_report_sha256"] = None
    basis_sha = sha256_json(raw)
    empty_stratum = {
        "n_pairs": 0,
        "per_pair": [],
        "b_distribution": dict.fromkeys(("median", "mean", "max", "q90"), NON_FINITE),
        "signed_pc_bias": [],
    }
    report_body = {
        "schema": APPROXIMATION_BIAS_SCHEMA,
        "deliverable": "gears_pseudobulk_approximation_bias_report",
        "protocol": PROTOCOL,
        "seal_status": "unopened",
        "method": REPRESENTATION,
        "admission_status": "admitted",
        "strata": {"combo_calibration": empty_stratum, "singles": empty_stratum},
        "gi_and_fairness": {
            "gi_signal_per_pair": [],
            "gi_signal_median": NON_FINITE,
            "floor_median": NON_FINITE,
            "bias_to_signal_ratio_R": NON_FINITE,
            "bias_to_signal_ratio_per_pair_median": NON_FINITE,
            "R_star": 0.5,
            "fairness_flag": "indeterminate",
            "bootstrap_95_interval": {
                "floor_median": NON_FINITE,
                "gi_signal_median": NON_FINITE,
                "bias_to_signal_ratio_R": NON_FINITE,
            },
            "replicates_requested": 1,
            "replicates_finite": 0,
            "replicates_non_finite": 1,
        },
        "provenance": {
            "measurement_contract_sha256": measurement_contract_sha256(),
            "basis_config_sha256": basis_sha,
            "git_commit": approved_git_sha,
            "norman_source_sha256": "1" * 64,
            "fit_role_artifact_sha256": "2" * 64,
            "response_projection_sha256": "3" * 64,
            "gene_order_sha256": "4" * 64,
            "pca_dim": 1,
            "registered_seeds": list(raw["seeds"]["registered_seeds"]),
            "probe_a_evidence_sha256": "5" * 64,
            "probe_a_evidence_manifest_sha256": "6" * 64,
            "probe_a_registration_sha256": "7" * 64,
            "probe_a_verification_sha256": "8" * 64,
            "sealed_pair_overlap_count": 0,
            "pod_instance": "synthetic-test",
        },
    }
    report = {**report_body, "self_checksum": self_checksum(report_body)}
    report_path = stage1 / "approximation_bias_report.json"
    report_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    raw["baselines"]["gears"]["approximation_bias_report_sha256"] = sha256_file(report_path)
    path = stage1 / "config.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    cfg = load_compose_phase2_config(path)
    return cfg, path, cfg.config_sha256, report_path


def _rebind_bias_report_to_scientific_inputs(
    *,
    config_path: Path,
    report_path: Path,
    approved_git_sha: str,
    response_artifact: dict[str, Any],
    gene_order: list[str],
    fit_role_sha256: str,
    raw_data_sha256: str,
) -> tuple[Any, str]:
    """Replace synthetic placeholders with exact stage-1 provenance, then re-finalize."""
    from alive.compose.driver.carrier_loader import _deserialize_response_space

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["baselines"]["gears"]["approximation_bias_report_sha256"] = None
    basis_sha = sha256_json(raw)
    rounded_space = _deserialize_response_space(
        json.loads(response_artifact["response_space"].artifact_bytes())
    )
    projection = build_response_projection(
        rounded_space,
        gene_order=gene_order,
        control_mean=response_artifact["control_mean"],
        raw_data_sha256=raw_data_sha256,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["provenance"].update(
        {
            "basis_config_sha256": basis_sha,
            "git_commit": approved_git_sha,
            "norman_source_sha256": raw_data_sha256,
            "fit_role_artifact_sha256": fit_role_sha256,
            "response_projection_sha256": sha256_json(projection),
            "gene_order_sha256": projection["gene_order_sha256"],
            "pca_dim": len(projection["control_mean"]),
            "registered_seeds": list(raw["seeds"]["registered_seeds"]),
        }
    )
    report_body = {key: value for key, value in report.items() if key != "self_checksum"}
    report["self_checksum"] = self_checksum(report_body)
    report_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    raw["baselines"]["gears"]["approximation_bias_report_sha256"] = sha256_file(report_path)
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    cfg = load_compose_phase2_config(config_path)
    return cfg, cfg.config_sha256


def _build_dependency_lock_evidence(ev: Path, *, gears_lock: Path, cpa_lock: Path) -> Path:
    """Build a READY ``gears_cpa_reproducible_dependency_lock`` evidence file under ``ev``.

    Reproduces the READY dependency-lock construction from
    ``tests/alive/compose/test_config2.py::_activation_record_for_config`` (deterministic,
    file-driven): copies the committed ``requirements.gears_env.lock`` /
    ``requirements.cpa_env.lock`` / ``go_resource_manifest.json`` from
    ``docs/activation-evidence/compose``, fills every per-backend ``required_evidence`` digest +
    pair roster + artifact manifest, marks the wheelhouse/reproducibility block COMPLETE,
    recomputes ``manifest_checksum``, and writes the lock under ``ev``. ``gears_lock`` /
    ``cpa_lock`` are accepted for call-site symmetry with the worker requirement locks; the
    dependency-lock evidence itself is derived entirely from the committed docs lineage.
    """
    del gears_lock, cpa_lock
    for name in (
        "requirements.gears_env.lock",
        "requirements.cpa_env.lock",
        "go_resource_manifest.json",
    ):
        shutil.copyfile(_EVIDENCE_ROOT / name, ev / name)
    dependency = json.loads(
        (_EVIDENCE_ROOT / "gears_cpa_dependency_lock.json").read_text(encoding="utf-8")
    )
    dependency["activation"] = "READY — synthetic scientific-carrier evidence"
    dependency["both_backends_run_evidence_complete"] = True
    dependency["run_gate"]["evidence_status"] = "COMPLETE"
    dependency["run_gate"]["seal_safety_status"] = "VERIFIED_ZERO_OVERLAP"
    dependency["run_gate"]["missing_evidence"] = []
    digest_fields = (
        "norman_source_sha256",
        "fit_role_artifact_sha256",
        "fit_role_row_identity_sha256",
        "smoke_script_sha256",
        "command_log_sha256",
        "checkpoint_sha256",
    )
    for index, backend in enumerate(("gears", "cpa"), start=1):
        record = dependency["run_gate"]["required_evidence"][backend]
        for offset, field in enumerate(digest_fields, start=index):
            record[field] = f"{offset:064x}"
        training_pairs = [f"{backend}:train:a", f"{backend}:train:b"]
        sealed_pairs = [f"{backend}:sealed:a", f"{backend}:sealed:b"]
        roster = {
            "schema": "compose_smoke_pair_roster_v1",
            "protocol": "COMPOSE-K562-v1",
            "backend": backend,
            "training_roles": ["singles", "combo_calibration"],
            "training_pair_ids": training_pairs,
            "sealed_pair_ids": sealed_pairs,
        }
        roster["manifest_checksum"] = sha256_json(roster)
        roster_path = ev / f"{backend}_pair_roster.json"
        roster_path.write_text(
            json.dumps(roster, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        record["training_pair_roster_sha256"] = sha256_json(training_pairs)
        record["sealed_pair_roster_sha256"] = sha256_json(sealed_pairs)
        record["sealed_pair_overlap_count"] = 0
        record["pair_roster_manifest_path"] = roster_path.name
        record["pair_roster_manifest_sha256"] = hashlib.sha256(roster_path.read_bytes()).hexdigest()
        artifact_fields = {
            "norman_source": "norman_source_sha256",
            "fit_role_artifact": "fit_role_artifact_sha256",
            "fit_role_row_identity": "fit_role_row_identity_sha256",
            "smoke_script": "smoke_script_sha256",
            "command_log": "command_log_sha256",
            "checkpoint": "checkpoint_sha256",
        }
        artifact_manifest = {
            "schema": "compose_backend_smoke_artifact_manifest_v1",
            "protocol": "COMPOSE-K562-v1",
            "backend": backend,
            "artifacts": {
                name: {
                    "uri": f"s3://example.invalid/compose/{backend}/{name}",
                    "immutable_version": "synthetic-unit-test-version",
                    "sha256": record[field],
                }
                for name, field in artifact_fields.items()
            },
        }
        artifact_manifest["manifest_checksum"] = sha256_json(artifact_manifest)
        artifact_manifest_path = ev / f"{backend}_artifact_manifest.json"
        artifact_manifest_path.write_text(
            json.dumps(artifact_manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        record["artifact_manifest_path"] = artifact_manifest_path.name
        record["artifact_manifest_sha256"] = hashlib.sha256(
            artifact_manifest_path.read_bytes()
        ).hexdigest()
        record["exit_code"] = 0
        dependency["environments"][f"{backend}_env"]["target_run_evidence_complete"] = True
    reproducibility = dependency["environment_reproducibility"]
    reproducibility["package_artifact_hashes_complete"] = True
    artifact_environments: dict[str, list[dict[str, str]]] = {}
    for backend in ("gears", "cpa"):
        artifacts = []
        requirements_path = ev / f"requirements.{backend}_env.lock"
        for line in requirements_path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            name, version = line.split("==", 1)
            filename = f"{name}-{version}-py3-none-any.whl"
            artifacts.append(
                {
                    "name": name,
                    "version": version,
                    "filename": filename,
                    "source_url": f"https://packages.example.invalid/{filename}",
                    "sha256": hashlib.sha256(filename.encode()).hexdigest(),
                }
            )
        artifact_environments[f"{backend}_env"] = artifacts
    wheelhouse = {
        "schema": "compose_python_artifact_manifest_v1",
        "environments": artifact_environments,
    }
    wheelhouse["manifest_checksum"] = sha256_json(wheelhouse)
    wheelhouse_path = ev / "wheelhouse_manifest.json"
    wheelhouse_path.write_text(
        json.dumps(wheelhouse, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    reproducibility["wheelhouse_manifest_path"] = wheelhouse_path.name
    reproducibility["wheelhouse_manifest_sha256"] = hashlib.sha256(
        wheelhouse_path.read_bytes()
    ).hexdigest()
    reproducibility["container_image_digest"] = "sha256:" + "b" * 64
    reproducibility["status"] = "COMPLETE"
    go_path = ev / "go_resource_manifest.json"
    dependency["go_resource_manifest"]["sha256"] = hashlib.sha256(go_path.read_bytes()).hexdigest()
    dependency["manifest_checksum"] = sha256_json(
        {key: value for key, value in dependency.items() if key != "manifest_checksum"}
    )
    dependency_path = ev / "gears_cpa_dependency_lock.json"
    dependency_path.write_text(
        json.dumps(dependency, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    return dependency_path


def _build_activation_evidence(
    root: Path, stage1: Path, cfg: Any, *, gears_lock: Path, cpa_lock: Path
) -> dict[str, dict[str, str]]:
    """Build all six activation-requirement evidence files under ``root``.

    Returns ``{requirement: {"path": <abs>, "sha256": "sha256:"+hex}}`` — the exact
    ``activation_evidence.requirements`` roster the scientific block declares. Config-bound
    reports embed ``cfg.config_sha256`` + ``cfg.protocol`` and read ``activation="READY"``.
    """
    ev = stage1 / "activation_evidence"
    ev.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}

    # 1-2. config-bound analytical reports.
    template = {
        "real_norman_phi_rank_and_condition_report": (
            _EVIDENCE_ROOT / "real_norman_phi_rank_report.json"
        ),
        "regime_specific_detectable_effect_analysis": (
            _EVIDENCE_ROOT / "real_norman_detectable_effect_report.json"
        ),
    }
    for req in _CONFIG_BOUND:
        payload = json.loads(template[req].read_text(encoding="utf-8"))
        payload["protocol"] = cfg.protocol
        payload["config_sha256"] = cfg.config_sha256
        payload["activation"] = "READY — synthetic scientific-carrier evidence"
        p = ev / f"{req}.json"
        p.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        files[req] = p

    # 3. finalized data card (also the pre-seal data_card file).
    files["finalized_norman_data_card_and_sha256"] = stage1 / "data_card.json"

    # 4. dependency lock (COMPLETE run-gate) — copy env locks + build the READY lock.
    files["gears_cpa_reproducible_dependency_lock"] = _build_dependency_lock_evidence(
        ev, gears_lock=gears_lock, cpa_lock=cpa_lock
    )

    # 5-6. outcome-store source + integration tests — COPY under root (every activation
    # evidence file must satisfy the approved-root policy of Task 2; the committed repo paths
    # are outside approved_artifacts_root, so reference in-root copies of their exact bytes).
    store_copy = ev / "outcome_store_evidence.py"
    shutil.copyfile("src/alive/compose/outcome_store.py", store_copy)
    files["independent_compose_outcome_store_and_access_audit"] = store_copy
    tests_copy = ev / "seal_integration_tests_evidence.py"
    shutil.copyfile("tests/alive/compose/test_phase2b.py", tests_copy)
    files["phase2_plan_metric_leakage_and_seal_integration_tests"] = tests_copy

    roster: dict[str, dict[str, str]] = {}
    for req in cfg.activation_requirements:
        fpath = files[req]
        roster[req] = {
            "path": str(fpath.resolve()),
            "sha256": "sha256:" + hashlib.sha256(fpath.read_bytes()).hexdigest(),
        }
    return roster


def build_scientific_carrier_fixture(root: Path, *, repo_root: Path) -> ScientificCarrierBundle:
    import numpy as np

    from alive.compose.driver.seal_boundary import scientific_protocol_seal_audit_path

    root = Path(os.path.realpath(str(root)))
    stage1 = root / "stage1"
    workers = root / "workers"
    run_dir = root / "run"
    for d in (stage1, workers, run_dir):
        d.mkdir(parents=True, exist_ok=True)
    audit_path = scientific_protocol_seal_audit_path(root, fb.PROTOCOL)

    approved_git_sha = init_synthetic_repo(repo_root)
    cfg, config_path, config_sha, bias_report_path = _write_activated_config(
        stage1, approved_git_sha=approved_git_sha
    )

    # 1. split manifest + instance (config-independent given split_seed / k_grid).
    gene_ids = [f"G{i:02d}" for i in range(fb._N_GENES)]
    eligible = [
        (gene_ids[i], gene_ids[j]) for i in range(fb._N_GENES) for j in range(i + 1, fb._N_GENES)
    ]
    manifest = build_split_manifest(
        eligible, seed=cfg.split_seed, calibration_fraction=fb._CALIBRATION_FRACTION
    )
    for role in ROLE_NAMES:
        assert manifest["roles"][role], f"empty {role!r} role"
    instance = fb._build_instance(manifest, k_grid=cfg.total_k_grid)

    # 2. response artifact + fit-role h5ad.
    fit_role_raw_sha = fb._fixture_digest("fit_role_raw_data")
    response_artifact, gene_order, fit_role_spec, response_combined = (
        fb._build_response_and_fit_role(
            out_path=stage1 / "fit_role.h5ad",
            response_dim=instance["p"],
            raw_data_sha256=fit_role_raw_sha,
            cal_pair_ids=instance["cal_pairs"],
            single_gene_ids=instance["gene_ids"],
        )
    )
    cfg, config_sha = _rebind_bias_report_to_scientific_inputs(
        config_path=config_path,
        report_path=bias_report_path,
        approved_git_sha=approved_git_sha,
        response_artifact=response_artifact,
        gene_order=list(gene_order),
        fit_role_sha256=sha256_file(stage1 / "fit_role.h5ad"),
        raw_data_sha256=fit_role_raw_sha,
    )

    # 3. run identity from the ACTIVATED config sha.
    data_card_digest = fb._fixture_digest("data_card")
    raw_or_source_digest = fb._fixture_digest("raw_or_source")
    sequence_mapping_digest = fb._fixture_digest("sequence_mapping")
    run_id = compute_compose_run_id(
        config_digest=config_sha,
        data_card_digest=data_card_digest,
        raw_or_source_digest=raw_or_source_digest,
        sequence_mapping_digest=sequence_mapping_digest,
    )
    checksums = {
        "response_space_checksum": response_combined,
        "factor_checksum": fb._fixture_digest("factor_bank"),
        "manifest_checksum": manifest["checksum"],
        "environment_checksum": fb._fixture_digest("environment"),
        "data_card_checksum": data_card_digest,
        "raw_data_checksum": raw_or_source_digest,
        "sequence_mapping_checksum": sequence_mapping_digest,
    }
    assert set(checksums) == set(EXPECTED_HASHES_KEYS)

    phase2a_inputs = fb._build_phase2a_inputs(
        instance, config=cfg, run_id=run_id, checksums=checksums
    )

    # 4. dev-store DATA — source_kind="audited_unsealed" (scientific evidence).
    dev_source = {
        "schema": "compose_development_outcome_source_v1",
        "combo_calibration_pair_ids": [list(p) for p in instance["cal_pairs"]],
        "combo_calibration_eps": np.asarray(instance["eps_cal"]).tolist(),
        "source_kind": "audited_unsealed",
    }
    dev_source_path = fb._write_json(stage1 / "development_outcome_source.json", dev_source)
    access_audit = {
        "role": "combo_calibration",
        "manifest_checksum": manifest["checksum"],
        "source_checksum": sha256_file(dev_source_path),
        "sealed_access_count": 0,
        "source_kind": "audited_unsealed",
    }
    dev_manifest_path = fb._write_json(
        stage1 / "development_outcome_manifest.json",
        {"schema": "compose_development_outcome_manifest_v1", "access_audit": access_audit},
    )

    # 5. sealed-outcome DATA + attestation (with scientific snapshot_id).
    sealed_source_path = stage1 / "sealed_source.h5ad"
    pair_index, pair_entries, obs_row_identity = fb._build_sealed_source(
        manifest, out_path=sealed_source_path, n_source_genes=instance["p"] + 1
    )
    sealed_source_sha = sha256_file(sealed_source_path)
    pair_index_body = {
        "schema": PAIR_INDEX_MANIFEST_SCHEMA,
        "source_file_sha256": sealed_source_sha,
        "obs_row_identity_sha256": obs_row_identity,
        "perturbation_column": fb.PERTURBATION_COLUMN,
        "control_token": fb.CONTROL_TOKEN,
        "combo_sep": fb.COMBO_SEP,
        "pairs": [
            {
                "gene_a": a,
                "gene_b": b,
                "role": role,
                "row_indices": [int(i) for i in pair_index[(a, b)]],
                "row_id_sha256": sha256_json(
                    {"pair": [a, b], "rows": [int(i) for i in pair_index[(a, b)]]}
                ),
            }
            for (a, b, role) in pair_entries
        ],
    }
    pair_index_manifest = fb._self_checksummed(pair_index_body)
    pair_index_manifest_path = fb._write_json(
        stage1 / "pair_index_manifest.json", pair_index_manifest
    )
    snapshot_id = "compose_scientific_carrier_v1_snapshot"
    attestation = fb._self_checksummed(
        {
            "schema": ATTESTATION_SCHEMA,
            "canonical_source_path": str(sealed_source_path),
            "expected_source_file_sha256": sealed_source_sha,
            "snapshot_id": snapshot_id,
            "source_row_identity_sha256": obs_row_identity,
            "pair_index_file_sha256": sha256_file(pair_index_manifest_path),
        }
    )
    attestation_path = fb._write_json(
        stage1 / "approved_sealed_input_attestation.json", attestation
    )

    # 6. remaining pre-seal DATA files.
    pair_manifest_path = fb._write_json(stage1 / "pair_manifest.json", manifest)
    phase2a_inputs_path = fb._write_json(
        stage1 / "phase2a_inputs.json", fb._serialize_phase2a_inputs(phase2a_inputs)
    )
    response_artifact_path = fb._write_json(
        stage1 / "response_artifact.json",
        {
            "schema": "compose_response_artifact_fixture_v1",
            "response_space": json.loads(response_artifact["response_space"].artifact_bytes()),
            "control_mean": np.asarray(response_artifact["control_mean"]).tolist(),
            "combined_checksum": response_combined,
            "gene_order": list(gene_order),
            "raw_data_sha256": fit_role_raw_sha,
            "fit_role_artifact": fit_role_spec.to_payload_block(),
        },
    )
    # data card declares the raw asset AS the processed analysis asset (spec §4 caveat).
    raw_asset_path = fb._write_bytes(
        stage1 / "raw_asset.bin", b"compose_scientific_carrier_v1::synthetic-processed-asset"
    )
    data_card_path = fb._write_json(
        stage1 / "data_card.json",
        {
            "schema": "compose_data_card_scientific_v1",
            "raw_or_source": {"kind": "declared_source_digest", "digest": raw_or_source_digest},
            "processed_analysis_asset": {
                "role": "processed",
                "sha256": sha256_file(raw_asset_path),
            },
            "data_card_digest": data_card_digest,
        },
    )
    sequence_mapping_path = fb._write_json(
        stage1 / "sequence_mapping.json",
        {"schema": "compose_sequence_mapping_scientific_v1", "digest": sequence_mapping_digest},
    )
    feature_bank_path = fb._write_json(
        stage1 / "feature_bank.json", {"schema": "compose_feature_bank_scientific_v1"}
    )
    factor_bank_path = fb._write_json(
        stage1 / "factor_bank.json",
        {
            "schema": "compose_factor_bank_scientific_v1",
            "factor_checksum": checksums["factor_checksum"],
            "k_grid": [int(k) for k in cfg.total_k_grid],
        },
    )

    # 7. worker files — gears/cpa requirements_lock pin the real revisions. Each method
    # gets its OWN execution bundle (the bundle's internal manifest declares its method;
    # ``assemble_execution_identity_lock`` validates it against the controller's per-method
    # expectation, so a shared bundle with a mismatched method would fail closed BEFORE
    # ever reaching the intended B ``adapter_version`` boundary — see Task 10).
    gears_lock = fb._write_bytes(
        workers / "requirements.gears.lock", b"cell-gears==0.1.2\nnumpy==1.26.4\n"
    )
    cpa_lock = fb._write_bytes(
        workers / "requirements.cpa.lock", b"cpa-tools==0.8.5\nnumpy==1.26.4\n"
    )
    worker_blocks: dict[str, Any] = {}
    representations = {name: rep for name, rep, _b in cfg.baseline_representations}
    for method, lock in (("gears", gears_lock), ("cpa", cpa_lock)):
        bundle = fb.build_worker_bundle(
            source_root=fb._REPO_ROOT,
            entrypoint=fb.STUB_WORKER_PATH,
            output_path=workers / f"{method}_worker.pyz",
            method=method,
        )
        paths = {
            "worker_script": Path(bundle.path),
            "worker_config": fb._write_bytes(workers / f"{method}_config.json", b"stub-config"),
            "resource_manifest": fb._write_bytes(
                workers / f"{method}_resource.json", b"stub-resource"
            ),
            "requirements_lock": lock,
            "adapter_artifact": fb._write_bytes(workers / f"{method}_adapter.bin", b"stub-adapter"),
        }
        block = fb._worker_block(paths, representation=representations[method])
        # ``_worker_block`` declares its ``execution_identity_lock`` digests from
        # fixture_builder's own hardcoded stub bytes (the FIXTURE-mode convention);
        # this corpus writes DIFFERENT real per-method bytes above, so the declared
        # digests are recomputed here from the ACTUAL file contents instead of
        # reusing the mismatched fixture constants — self-consistency, not a
        # coincidental byte match, is what makes the corpus valid.
        block["execution_identity_lock"] = {
            **block["execution_identity_lock"],
            "adapter_sha256": sha256_file(paths["adapter_artifact"]),
            "config_sha256": sha256_file(paths["worker_config"]),
            "resource_sha256": sha256_file(paths["resource_manifest"]),
            "environment_lock_sha256": sha256_file(paths["requirements_lock"]),
        }
        worker_blocks[method] = block

    # 8. dependency manifest for the scientific block (== the dependency evidence lock).
    pre_seal_paths = {
        "config": config_path,
        "data_card": data_card_path,
        "raw_asset": raw_asset_path,
        "sequence_mapping": sequence_mapping_path,
        "feature_bank": feature_bank_path,
        "factor_bank": factor_bank_path,
        "response_artifact": response_artifact_path,
        "fit_role_artifact": stage1 / "fit_role.h5ad",
        "phase2a_inputs": phase2a_inputs_path,
        "development_outcome_source": dev_source_path,
        "development_outcome_manifest": dev_manifest_path,
        "pair_manifest": pair_manifest_path,
        "pair_index_manifest": pair_index_manifest_path,
        "approved_sealed_input_attestation": attestation_path,
    }
    assert set(pre_seal_paths) == set(PRE_SEAL_PATH_FIELDS)

    requirements_roster = _build_activation_evidence(
        root, stage1, cfg, gears_lock=gears_lock, cpa_lock=cpa_lock
    )
    dependency_path = Path(requirements_roster["gears_cpa_reproducible_dependency_lock"]["path"])

    # 9. assemble the scientific ResolvedRunSpec.
    spec_body: dict[str, Any] = {
        "schema": RESOLVED_RUN_SPEC_SCHEMA,
        "mode": "scientific",
        "protocol": fb.PROTOCOL,
        "run_id": run_id,
        "approved_git_sha": approved_git_sha,
        "run_dir": str(run_dir),
        "approved_artifacts_root": str(root),
        "config_digest": config_sha,
        "data_card_digest": data_card_digest,
        "raw_or_source_digest": raw_or_source_digest,
        "sequence_mapping_digest": sequence_mapping_digest,
        "run_produced_basenames": dict(RUN_PRODUCED_BASENAMES),
        "expected_hashes": dict(checksums),
        "worker_blocks": worker_blocks,
        "scientific": {
            "activation_evidence": {
                "owner": "owner@example.org",
                "requirements": requirements_roster,
            },
            "dependency_manifest": {
                "path": str(dependency_path),
                "sha256": sha256_file(dependency_path),
            },
            "approximation_bias_report": {
                "path": str(bias_report_path),
                "sha256": sha256_file(bias_report_path),
            },
            "device": "cpu",
            "precision": "float32",
            "sealed_input": {
                "source_path": str(sealed_source_path),
                "expected_file_sha256": sealed_source_sha,
                "snapshot_id": snapshot_id,
                "audit_path": str(audit_path),
            },
        },
    }
    for field in PRE_SEAL_PATH_FIELDS:
        spec_body[field] = fb._path_sha(pre_seal_paths[field])
    spec = fb._self_checksummed(spec_body)
    spec_path = fb._write_bytes(root / "resolved_run_spec.json", fb._canonical_bytes(spec))

    return ScientificCarrierBundle(
        spec_path=spec_path,
        approved_artifacts_root=root,
        run_dir=run_dir,
        audit_path=audit_path,
        repo_root=repo_root,
        approved_git_sha=approved_git_sha,
        config_sha256=config_sha,
        activation_requirements=cfg.activation_requirements,
    )
