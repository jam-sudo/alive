"""Tests for the committed COMPOSE fixture builder (sub-project C, spec §6).

Written FIRST per TDD. The builder promotes the per-test synthetic assembly into
one committed function that writes bounded synthetic DATA + a fixture
ResolvedRunSpec. These tests exercise the five non-negotiable contracts against
the REAL loader / validator / stub (no mocks):

  1. the fixture ResolvedRunSpec loads via ``load_resolved_run_spec`` (mode
     ``"fixture"``) with NO raise — so every declared path exists, every digest
     matches on-disk bytes, the ``run_id`` recomputes, and each worker block is
     complete;
  2. the fixed ``run_id`` recomputes from the four run-identity digests AND
     equals ``Phase2aInputs.run_id``;
  3. the ``adapter_artifact`` / config / resource / lock file digests equal the
     ``stub_worker.py`` self-reported constants (T4 reconcile);
  4. the pair-index manifest binds to its attestation via
     ``validate_pair_index_manifest_preseal`` (and the sealed source's obs labels
     align with the pair index);
  5. the sealed-outcome corpus identity is ``FIXTURE_CORPUS_V1`` and NO store
     object is constructed.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import anndata
import numpy as np

from alive.compose.datacard import compute_compose_run_id
from alive.compose.driver.fixture_builder import FixtureBundle, build_compose_fixture
from alive.compose.driver.pair_index import validate_pair_index_manifest_preseal
from alive.compose.driver.run_spec import (
    EXPECTED_HASHES_KEYS,
    ResolvedRunSpec,
    load_resolved_run_spec,
)
from alive.compose.operator import _sym_to_vec
from alive.compose.outcome_store import (
    FIXTURE_CORPUS_V1,
    ComposeOutcomeStore,
    validate_pair_index_against_source_obs,
)
from alive.compose.phase2a import DevelopmentOutcomeStore, Phase2aInputs
from alive.compose.worker_bundle import validate_worker_bundle
from alive.provenance import sha256_file

_ADAPTER_METHODS = ("gears", "cpa")


# --------------------------------------------------------------------------- #
# Contract 1: the fixture ResolvedRunSpec loads (mode="fixture"), no raise
# --------------------------------------------------------------------------- #
def test_fixture_spec_loads_via_loader(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    assert isinstance(bundle, FixtureBundle)

    spec = load_resolved_run_spec(
        bundle.spec_path,
        approved_artifacts_root=tmp_path,
        mode_expected="fixture",
    )
    assert isinstance(spec, ResolvedRunSpec)
    assert spec.mode == "fixture"
    assert spec.protocol == "COMPOSE-K562-v1"
    assert spec.run_id == bundle.run_id
    assert set(spec.expected_hashes) == set(EXPECTED_HASHES_KEYS)
    # every worker block carries adapter_artifact + the other worker path+SHA.
    assert set(spec.worker_blocks) == set(_ADAPTER_METHODS)
    for method in _ADAPTER_METHODS:
        block = spec.worker_blocks[method]
        assert block.adapter_artifact.path
        assert block.worker_script.path


def test_every_declared_digest_matches_on_disk_bytes(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    raw = json.loads(bundle.spec_path.read_text())
    # pre-seal path+SHA fields verify byte-for-byte.
    for field, decl in raw.items():
        if isinstance(decl, dict) and set(decl) == {"path", "sha256"}:
            assert sha256_file(decl["path"]) == decl["sha256"], field
    # worker path+SHA fields verify too.
    for method in _ADAPTER_METHODS:
        block = raw["worker_blocks"][method]
        for key in (
            "worker_script",
            "worker_config",
            "resource_manifest",
            "requirements_lock",
            "adapter_artifact",
        ):
            assert sha256_file(block[key]["path"]) == block[key]["sha256"], (method, key)


# --------------------------------------------------------------------------- #
# Contract 1b: the fixture's symmetric-vectorisation matches operator._sym_to_vec
# --------------------------------------------------------------------------- #
def test_fixture_sym_to_vec_matches_operator_sym_to_vec() -> None:
    """Pin the fixture builder's coef construction to the SAME half-vectorisation
    ``alive.compose.operator`` uses (the same sqrt(2) off-diagonal convention),
    so the two can never silently diverge (fixture_builder.py imports
    ``_sym_to_vec`` from ``operator`` rather than carrying its own copy).
    """
    rng = np.random.default_rng(7)
    b = rng.normal(size=(5, 5))
    sym = 0.5 * (b + b.T)

    from alive.compose.driver import fixture_builder

    assert fixture_builder._sym_to_vec is _sym_to_vec
    np.testing.assert_array_equal(fixture_builder._sym_to_vec(sym), _sym_to_vec(sym))


# --------------------------------------------------------------------------- #
# Contract 2: fixed run_id — recomputes AND equals Phase2aInputs.run_id
# --------------------------------------------------------------------------- #
def test_run_id_is_fixed_and_recomputes(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    spec = load_resolved_run_spec(
        bundle.spec_path, approved_artifacts_root=tmp_path, mode_expected="fixture"
    )
    recomputed = compute_compose_run_id(
        config_digest=spec.config_digest,
        data_card_digest=spec.data_card_digest,
        raw_or_source_digest=spec.raw_or_source_digest,
        sequence_mapping_digest=spec.sequence_mapping_digest,
    )
    assert recomputed == bundle.run_id
    # phase2a's bound run_id == the spec's recompute (landmine).
    assert bundle.phase2a_inputs.run_id == bundle.run_id
    # expected_hashes agree with the bound Phase2aInputs checksums.
    assert bundle.expected_hashes["data_card_checksum"] == spec.data_card_digest
    assert bundle.expected_hashes["raw_data_checksum"] == spec.raw_or_source_digest
    assert bundle.expected_hashes["sequence_mapping_checksum"] == spec.sequence_mapping_digest
    assert bundle.phase2a_inputs.data_card_checksum == spec.data_card_digest


# --------------------------------------------------------------------------- #
# Contract 3: adapter_artifact + stub file bytes hash to the stub constants
# --------------------------------------------------------------------------- #
def test_worker_file_digests_match_stub_constants(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    expected = {
        "adapter_artifact": hashlib.sha256(b"stub-response-operator-v2").hexdigest(),
        "worker_config": hashlib.sha256(b"stub-config").hexdigest(),
        "resource_manifest": hashlib.sha256(b"stub-resource").hexdigest(),
        "requirements_lock": hashlib.sha256(b"stub-environment").hexdigest(),
    }
    for role, want in expected.items():
        assert sha256_file(bundle.worker_paths[role]) == want, role
    # and those digests are exactly what the worker blocks declare in the lock.
    raw = json.loads(bundle.spec_path.read_text())
    for method in _ADAPTER_METHODS:
        lock = raw["worker_blocks"][method]["execution_identity_lock"]
        assert lock["adapter_sha256"] == expected["adapter_artifact"]
        assert lock["config_sha256"] == expected["worker_config"]
        assert lock["resource_sha256"] == expected["resource_manifest"]
        assert lock["environment_lock_sha256"] == expected["requirements_lock"]
        assert lock["adapter_version"] == "stub-2"


def test_worker_bundle_contains_the_committed_stub_and_exact_helpers(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    repo_stub = Path(__file__).resolve().parents[4] / "scripts" / "baselines" / "stub_worker.py"
    worker_path = bundle.worker_paths["worker_script"]
    info = validate_worker_bundle(worker_path, expected_method="stub")
    assert info.path == str(worker_path)
    with zipfile.ZipFile(worker_path, "r") as archive:
        assert archive.read("__main__.py") == repo_stub.read_bytes()


# --------------------------------------------------------------------------- #
# Contract 4: pair-index manifest binds to its attestation (T2 schema)
# --------------------------------------------------------------------------- #
def test_pair_index_manifest_passes_preseal_validation(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    manifest = bundle.sealed_outcome["pair_index_manifest"]
    attestation = bundle.sealed_outcome["attestation"]
    # no raise
    pair_index_file_sha256 = sha256_file(bundle.paths["pair_index_manifest"])
    validate_pair_index_manifest_preseal(
        manifest,
        attestation=attestation,
        pair_index_manifest_file_sha256=pair_index_file_sha256,
    )
    # the on-disk pair-index manifest / attestation are the SAME objects.
    on_disk_manifest = json.loads(bundle.paths["pair_index_manifest"].read_text())
    on_disk_attestation = json.loads(bundle.paths["approved_sealed_input_attestation"].read_text())
    validate_pair_index_manifest_preseal(
        on_disk_manifest,
        attestation=on_disk_attestation,
        pair_index_manifest_file_sha256=pair_index_file_sha256,
    )


def test_sealed_source_obs_labels_align_with_pair_index(tmp_path: Path) -> None:
    # the phase2b obs-alignment gate accepts the fixture (proves the sealed source
    # obs perturbation labels canonicalize to their indexed pair).
    bundle = build_compose_fixture(tmp_path)
    source = anndata.read_h5ad(bundle.sealed_outcome["source_path"])
    validate_pair_index_against_source_obs(
        source,
        bundle.sealed_outcome["pair_index"],
        bundle.sealed_outcome["manifest"],
        perturbation_col=bundle.sealed_outcome["perturbation_column"],
        combo_sep=bundle.sealed_outcome["combo_sep"],
    )


# --------------------------------------------------------------------------- #
# Contract 5: corpus == FIXTURE_CORPUS_V1 and NO store object is built
# --------------------------------------------------------------------------- #
def test_corpus_attestation_matches_v1(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    assert bundle.fixture_corpus == FIXTURE_CORPUS_V1
    assert bundle.sealed_outcome["corpus_id"] == FIXTURE_CORPUS_V1.corpus_id
    assert bundle.sealed_outcome["source_sha256"] == FIXTURE_CORPUS_V1.source_sha256
    assert bundle.sealed_outcome["builder_code_sha256"] == FIXTURE_CORPUS_V1.builder_code_sha256


def test_builder_constructs_no_store_object(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)

    def _walk(obj, depth=0):
        assert not isinstance(obj, (DevelopmentOutcomeStore, ComposeOutcomeStore))
        if depth > 3:
            return
        if isinstance(obj, dict):
            for v in obj.values():
                _walk(v, depth + 1)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                _walk(v, depth + 1)

    for value in vars(bundle).values():
        _walk(value)
    # the carried development inputs are a typed Phase2aInputs, never a store.
    assert isinstance(bundle.phase2a_inputs, Phase2aInputs)


def test_payload_within_fixture_bounds(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    inp = bundle.phase2a_inputs
    assert inp.n_genes <= 128
    assert len(inp.cal_pair_ids) <= 4096
    assert inp.response_dim <= 256
    assert bundle.dev_store_audit["access_audit"].source_kind == "synthetic_fixture"


def test_fit_role_carries_a_combo_cell_per_calibration_pair(tmp_path: Path) -> None:
    """The fit-role artifact holds one ``combo_calibration`` cell per calibration
    pair — the D2 seed-variability ``COMPLETE`` prerequisite (T9/T13).

    ``development_seed_variability`` re-derives, per ``(method, seed, fold)``, a
    fold-scoped fit-role artifact restricted to that fold's TRAIN pairs; the
    reference worker fails closed unless that artifact carries a
    ``combo_calibration`` cell. Because each OOF fold's ``train ∪ test ∪ excluded``
    equals the full calibration set, every fold's TRAIN subset retains a combo cell
    IFF the base artifact carries a cell for every calibration pair. A short slice
    left most folds with zero combo cells → an INCOMPLETE report.
    """
    bundle = build_compose_fixture(tmp_path)
    adata = anndata.read_h5ad(bundle.paths["fit_role_artifact"])
    roles = [str(r) for r in adata.obs["role"]]
    perts = [str(p) for p in adata.obs["perturbation"]]
    cal_pairs = tuple(tuple(p) for p in bundle.phase2a_inputs.cal_pair_ids)

    combo_tokens = {tok for tok, role in zip(perts, roles) if role == "combo_calibration"}
    # exactly one combo cell per calibration pair, tokens byte-canonical "a_b".
    assert roles.count("combo_calibration") == len(cal_pairs)
    assert combo_tokens == {f"{a}_{b}" for a, b in cal_pairs}
    # Every governed single gene must be present exactly once: the strict worker
    # roster check intentionally rejects the old eight-row convenience subset.
    single_tokens = [tok for tok, role in zip(perts, roles) if role == "singles"]
    governed_singles = list(bundle.phase2a_inputs.gene_index)
    assert single_tokens == governed_singles
    # Still bounded synthetic: a tiny cell/gene count within the fixture limits.
    assert adata.n_obs == 12 + len(governed_singles) + len(cal_pairs)
    assert adata.n_vars == bundle.phase2a_inputs.response_dim + 1


def test_run_dir_starts_empty(tmp_path: Path) -> None:
    # stage-1 inputs live outside run_dir; the driver installs run-produced
    # artifacts INTO run_dir (spec §7.1), so it must start empty.
    bundle = build_compose_fixture(tmp_path)
    assert bundle.run_dir.is_dir()
    assert list(bundle.run_dir.iterdir()) == []
    assert not bundle.audit_path.exists()
