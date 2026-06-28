"""Tests for alive.compose.phase2a — written FIRST per TDD protocol (Task 2a-11).

``run_phase2a`` is the no-seal Phase-2a orchestrator. It ties Tasks 2a-1..2a-10
together and produces the frozen handoff Phase 2b consumes. ACTIVATION BLOCKED:
pure ``numpy`` on synthetic fixtures only; NO real Norman, NO seal open, NO
sealed-outcome read.

Load-bearing contracts under test (brief steps 1-9, plan §2.1 / §2.5):

  * fixture mode is allowed; scientific mode on the blocked config is refused;
  * upstream hash mismatch (manifest / response / factor / environment) aborts
    BEFORE any prediction;
  * futility (FUTILITY_STOPPED) returns NO ``FrozenPredictionBundle`` and writes
    no sealed predictions — the seal stays closed and ``sealed_access_count == 0``;
  * a CONTINUE run generates predictions for the REGISTERED sealed pair IDs using
    identities/features ONLY (z_g, z_h -> model.predict_eps + additive), never
    reading a sealed outcome;
  * the complete method roster + every prediction are validated and frozen ONCE;
  * an outcome store that exposes a sealed role / sealed outcome / sealed path
    (recursively, at multiple nesting depths) is REJECTED;
  * ``sealed_access_count == 0`` throughout and the result records it.
"""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from alive.compose.baselines_combo import additive
from alive.compose.config2 import ScientificModeError, load_compose_phase2_config
from alive.compose.datacard import compute_compose_run_id
from alive.compose.freeze import FrozenPredictionBundle, OutcomeLeakageError
from alive.compose.models import IDOnlyModel, L1Model, L2Model, L3Model
from alive.compose.operator import bilinear_predict
from alive.compose.phase2a import (
    DevelopmentOutcomeStore,
    OutcomeAccessAudit,
    Phase2aInputs,
    Phase2aResult,
    _scan_inputs_for_leakage,
    _verify_factor_banks,
    _verify_scientific_data_assets,
    _verify_scientific_response_artifact,
    run_phase2a,
    run_phase2a_fixture,
)
from alive.compose.response import fit_response_space, verify_response_artifact
from alive.compose.zfactor import GeneFactorBank
from alive.provenance import sha256_bytes, sha256_file, sha256_json

# --------------------------------------------------------------------------- #
# synthetic instance
# --------------------------------------------------------------------------- #


def _canon(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a.encode("utf-8") <= b.encode("utf-8") else (b, a)


def _sym_to_vec(B: np.ndarray) -> np.ndarray:
    k = B.shape[0]
    iu = np.triu_indices(k)
    out = B[iu].astype(np.float64).copy()
    off = iu[0] != iu[1]
    out[off] *= np.sqrt(2.0)
    return out


def _build_instance(rng, *, n_genes=18, k=4, p=7, n_sealed_double=4, n_sealed_single=3, noise=0.02):
    """A full-rank synthetic instance with a held-out sealed pair set.

    Calibration pairs are the within-calibration-gene pairs (development role);
    sealed pairs are a disjoint set of (gene-i, gene-j) used for prediction ONLY.
    No sealed *outcome* is ever produced or read.
    """
    gene_ids = [f"G{i:02d}" for i in range(n_genes)]
    gene_index = {g: i for i, g in enumerate(gene_ids)}
    Z = rng.normal(size=(n_genes, k))
    B = rng.normal(size=(p, k, k))
    B = 0.5 * (B + np.transpose(B, (0, 2, 1)))
    coef = np.vstack([_sym_to_vec(B[m]) for m in range(p)])

    # calibration genes = first 12; the rest drive the sealed pairs.
    cal_genes = list(range(12))
    cal_pairs_idx: list[tuple[int, int]] = []
    cal_pairs_id: list[tuple[str, str]] = []
    for ii in range(len(cal_genes)):
        for jj in range(ii + 1, len(cal_genes)):
            i, j = cal_genes[ii], cal_genes[jj]
            cal_pairs_idx.append((i, j))
            cal_pairs_id.append(_canon(gene_ids[i], gene_ids[j]))

    eps_cal = np.vstack([bilinear_predict(coef, Z[g], Z[h]) for g, h in cal_pairs_idx])
    additive_cal = rng.normal(size=eps_cal.shape)

    eps_a = eps_cal + noise * rng.normal(size=eps_cal.shape)
    eps_b = eps_cal + noise * rng.normal(size=eps_cal.shape)

    # sealed double-unseen pairs: both genes outside calibration (12..17).
    sealed_genes = list(range(12, n_genes))
    sd_idx, sd_id = [], []
    for ii in range(len(sealed_genes)):
        for jj in range(ii + 1, len(sealed_genes)):
            i, j = sealed_genes[ii], sealed_genes[jj]
            sd_idx.append((i, j))
            sd_id.append(_canon(gene_ids[i], gene_ids[j]))
    sd_idx, sd_id = sd_idx[:n_sealed_double], sd_id[:n_sealed_double]

    # sealed single-unseen pairs: exactly one calibration gene.
    ss_idx, ss_id = [], []
    for i in sealed_genes:
        for j in cal_genes:
            ss_idx.append((i, j))
            ss_id.append(_canon(gene_ids[i], gene_ids[j]))
    ss_idx, ss_id = ss_idx[:n_sealed_single], ss_id[:n_sealed_single]

    # single-gene deltas (single-role; allowed) for the additive comparator.
    delta_by_gene = {g: rng.normal(size=p) for g in gene_ids}

    return {
        "gene_ids": gene_ids,
        "gene_index": gene_index,
        "Z": Z,
        "k": k,
        "p": p,
        "coef": coef,
        "cal_pairs_idx": cal_pairs_idx,
        "cal_pairs_id": cal_pairs_id,
        "eps_cal": eps_cal,
        "additive_cal": additive_cal,
        "eps_a": eps_a,
        "eps_b": eps_b,
        "sealed_double_idx": sd_idx,
        "sealed_double_id": sd_id,
        "sealed_single_idx": ss_idx,
        "sealed_single_id": ss_id,
        "delta_by_gene": delta_by_gene,
    }


def _model_factories():
    """The registered model roster -> a fresh-instance factory each."""
    return {
        "l1_bilinear_identifiable": L1Model,
        "l2_saturation": L2Model,
        "l3_hypernetwork": L3Model,
        "id_only": IDOnlyModel,
        # Synthetic stand-ins exercise the frozen roster contract. Scientific
        # activation still requires the separately pinned GEARS/CPA backends.
        "gears": L1Model,
        "cpa": L1Model,
    }


def _inputs(inst, **overrides) -> Phase2aInputs:
    cfg = load_compose_phase2_config("configs/compose_k562_v1_phase2.yaml")
    data_card_checksum = "data-card-checksum"
    raw_data_checksum = "raw-data-checksum"
    sequence_mapping_checksum = "sequence-mapping-checksum"
    run_id = compute_compose_run_id(
        config_digest=cfg.config_sha256,
        data_card_digest=data_card_checksum,
        raw_or_source_digest=raw_data_checksum,
        sequence_mapping_digest=sequence_mapping_checksum,
    )
    z4 = inst["Z"]
    z6 = np.column_stack((z4, z4[:, 0] ** 2, z4[:, 1] ** 2))
    z8 = np.column_stack((z6, z4[:, 2] ** 2, z4[:, 3] ** 2))
    kwargs = dict(
        run_id=run_id,
        gene_index=inst["gene_index"],
        factors_by_k={4: z4, 6: z6, 8: z8},
        cal_idx_pairs=inst["cal_pairs_idx"],
        cal_pair_ids=inst["cal_pairs_id"],
        additive_cal=inst["additive_cal"],
        eps_split_a=inst["eps_a"],
        eps_split_b=inst["eps_b"],
        k_total_grid=[4, 6, 8],
        lambda_grid=[0.0, 1e-3, 1e-2, 1e-1],
        n_genes=len(inst["gene_ids"]),
        n_folds=3,
        seed=11,
        uncovered_tolerance=0.75,
        sealed_double_pair_ids=inst["sealed_double_id"],
        sealed_single_pair_ids=inst["sealed_single_id"],
        delta_by_gene=inst["delta_by_gene"],
        model_factories=_model_factories(),
        response_dim=inst["p"],
        response_space_checksum="rs-checksum",
        factor_checksum="zf-checksum",
        model_checksum="model-checksum",
        manifest_checksum="manifest-checksum",
        environment_checksum="env-checksum",
        registered_seeds=(11, 23, 37),
        data_card_checksum=data_card_checksum,
        raw_data_checksum=raw_data_checksum,
        sequence_mapping_checksum=sequence_mapping_checksum,
    )
    kwargs.update(overrides)
    return Phase2aInputs(**kwargs)


def _store(inst, **overrides) -> DevelopmentOutcomeStore:
    """A development outcome store exposing only the unsealed calibration eps."""
    kwargs = dict(
        combo_calibration_eps=inst["eps_cal"],
        combo_calibration_pair_ids=inst["cal_pairs_id"],
        access_audit=OutcomeAccessAudit(
            role="combo_calibration",
            manifest_checksum="manifest-checksum",
            source_checksum="fixture-source-checksum",
            sealed_access_count=0,
            source_kind="synthetic_fixture",
        ),
    )
    kwargs.update(overrides)
    return DevelopmentOutcomeStore(**kwargs)


def _factor_banks(inputs: Phase2aInputs) -> dict[int, GeneFactorBank]:
    gene_order = tuple(sorted(inputs.gene_index, key=lambda g: g.encode("utf-8")))
    banks: dict[int, GeneFactorBank] = {}
    for k_total, matrix in inputs.factors_by_k.items():
        bank = GeneFactorBank(
            k_total=k_total,
            expression_dim=k_total,
            esm_dim=0,
            gene_order=gene_order,
            z_by_gene={g: np.asarray(matrix[inputs.gene_index[g]]).copy() for g in gene_order},
            expression_explained_variance=np.zeros(k_total),
            esm_explained_variance=np.zeros(0),
            expression_components=np.zeros((k_total, k_total)),
            esm_components=np.zeros((0, 0)),
            encoder_revision="fixture-revision",
            sequence_mapping_hash=inputs.sequence_mapping_checksum,
        )
        banks[k_total] = dataclasses.replace(bank, checksum=sha256_bytes(bank.artifact_bytes()))
    return banks


_HASHES = dict(
    response_space_checksum="rs-checksum",
    factor_checksum="zf-checksum",
    model_checksum="model-checksum",
    manifest_checksum="manifest-checksum",
    environment_checksum="env-checksum",
    data_card_checksum="data-card-checksum",
    raw_data_checksum="raw-data-checksum",
    sequence_mapping_checksum="sequence-mapping-checksum",
)


# --------------------------------------------------------------------------- #
# happy path: CONTINUE -> frozen bundle with predictions only
# --------------------------------------------------------------------------- #
def test_continue_produces_a_verified_bundle_no_outcomes():
    rng = np.random.default_rng(0)
    inst = _build_instance(rng)
    res = run_phase2a_fixture(_inputs(inst), _store(inst), expected_hashes=_HASHES)
    assert isinstance(res, Phase2aResult)
    assert res.futility_status == "CONTINUE"
    assert res.sealed_access_count == 0
    assert isinstance(res.bundle, FrozenPredictionBundle)
    res.bundle.verify()
    res.bundle.assert_no_outcomes()
    cfg = load_compose_phase2_config("configs/compose_k562_v1_phase2.yaml")
    assert res.bundle.method_roster == cfg.method_roster
    assert res.ledger.to_dict()["config_sha256"] == cfg.config_sha256
    # predictions exist for exactly the registered sealed pairs
    assert set(res.bundle.predictions_double_unseen["additive"]) == set(inst["sealed_double_id"])
    assert set(res.bundle.predictions_single_unseen["additive"]) == set(inst["sealed_single_id"])


def test_l1_prediction_equals_identity_only_path():
    # predictions must be generated from identities/features only: for L1 the
    # double-shift prediction is bilinear_predict(coef, z_g, z_h) + additive(d_g, d_h).
    rng = np.random.default_rng(1)
    inst = _build_instance(rng)
    res = run_phase2a_fixture(_inputs(inst), _store(inst), expected_hashes=_HASHES)

    # refit L1 the same way the orchestrator does, on calibration data only
    l1 = L1Model().fit(inst["Z"], inst["cal_pairs_idx"], inst["eps_cal"], lam=res.selected_lambda)
    for g, h in inst["sealed_double_id"]:
        gi, hi = inst["gene_index"][g], inst["gene_index"][h]
        expected = l1.predict_eps(inst["Z"], gi, hi) + additive(
            inst["delta_by_gene"][g], inst["delta_by_gene"][h]
        )
        got = res.bundle.predictions_double_unseen["l1_bilinear_identifiable"][(g, h)]
        np.testing.assert_allclose(got, expected, rtol=1e-9, atol=1e-9)


def test_additive_prediction_is_delta_sum():
    rng = np.random.default_rng(2)
    inst = _build_instance(rng)
    res = run_phase2a_fixture(_inputs(inst), _store(inst), expected_hashes=_HASHES)
    for g, h in inst["sealed_double_id"]:
        expected = additive(inst["delta_by_gene"][g], inst["delta_by_gene"][h])
        got = res.bundle.predictions_double_unseen["additive"][(g, h)]
        np.testing.assert_allclose(got, expected, rtol=1e-9, atol=1e-9)


def test_no_change_prediction_is_zero():
    rng = np.random.default_rng(3)
    inst = _build_instance(rng)
    res = run_phase2a_fixture(_inputs(inst), _store(inst), expected_hashes=_HASHES)
    for g, h in inst["sealed_double_id"]:
        got = res.bundle.predictions_double_unseen["no_change"][(g, h)]
        np.testing.assert_array_equal(got, np.zeros(inst["p"]))


def test_perturbation_mean_uses_calibration_double_shifts_only():
    rng = np.random.default_rng(31)
    inst = _build_instance(rng)
    res = run_phase2a_fixture(_inputs(inst), _store(inst), expected_hashes=_HASHES)
    expected = np.mean(inst["additive_cal"] + inst["eps_cal"], axis=0)
    for pair in inst["sealed_double_id"]:
        np.testing.assert_allclose(
            res.bundle.predictions_double_unseen["perturbation_mean"][pair],
            expected,
        )


def test_bundle_written_once(tmp_path):
    rng = np.random.default_rng(4)
    inst = _build_instance(rng)
    out = tmp_path / "compose" / "bundle.json"
    res = run_phase2a_fixture(_inputs(inst), _store(inst), expected_hashes=_HASHES, bundle_path=out)
    assert out.exists()
    loaded = FrozenPredictionBundle.load(out)
    loaded.verify()
    assert loaded.bundle_checksum == res.bundle.bundle_checksum
    # ledger records the bundle checksum
    assert res.ledger.artifact_sha("frozen_prediction_bundle") == res.bundle.bundle_checksum


# --------------------------------------------------------------------------- #
# execution-mode guard
# --------------------------------------------------------------------------- #
def test_scientific_mode_blocked_refuses_to_run():
    rng = np.random.default_rng(5)
    inst = _build_instance(rng)
    with pytest.raises(ScientificModeError):
        run_phase2a(
            _inputs(inst),
            _store(inst),
            fixture_mode=False,  # scientific mode on the blocked config
            expected_hashes=_HASHES,
        )


def test_scientific_entry_rejects_caller_controlled_fixture_boolean():
    rng = np.random.default_rng(50)
    inst = _build_instance(rng)
    with pytest.raises(ScientificModeError, match="run_phase2a_fixture"):
        run_phase2a(
            _inputs(inst),
            _store(inst),
            fixture_mode=True,
            expected_hashes=_HASHES,
        )


def test_fixture_entry_requires_synthetic_audit():
    rng = np.random.default_rng(51)
    inst = _build_instance(rng)
    audit = dataclasses.replace(_store(inst).access_audit, source_kind="audited_unsealed")
    with pytest.raises(ScientificModeError, match="synthetic_fixture"):
        run_phase2a_fixture(
            _inputs(inst),
            _store(inst, access_audit=audit),
            expected_hashes=_HASHES,
        )


# --------------------------------------------------------------------------- #
# upstream hash verification (step 2) aborts before prediction
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "bad_key",
    [
        "response_space_checksum",
        "factor_checksum",
        "model_checksum",
        "manifest_checksum",
        "environment_checksum",
        "data_card_checksum",
        "raw_data_checksum",
        "sequence_mapping_checksum",
    ],
)
def test_hash_mismatch_aborts(bad_key):
    rng = np.random.default_rng(6)
    inst = _build_instance(rng)
    tampered = dict(_HASHES)
    tampered[bad_key] = "WRONG"
    with pytest.raises(ValueError, match="hash|checksum"):
        run_phase2a_fixture(_inputs(inst), _store(inst), expected_hashes=tampered)


def test_mutated_inputs_after_binding_are_rejected():
    rng = np.random.default_rng(52)
    inst = _build_instance(rng)
    inputs = _inputs(inst)
    with pytest.raises(ValueError, match="read-only"):
        np.asarray(inputs.additive_cal)[0, 0] += 1.0


def test_mutated_outcomes_after_binding_are_rejected():
    rng = np.random.default_rng(56)
    inst = _build_instance(rng)
    store = _store(inst)
    with pytest.raises(ValueError, match="read-only"):
        store.combo_calibration_eps[0, 0] += 1.0


def test_factor_bank_artifacts_bind_runtime_factor_rows():
    inst = _build_instance(np.random.default_rng(57))
    base = _inputs(inst)
    banks = _factor_banks(base)
    aggregate = sha256_json(
        {"factor_banks_by_k": {str(k): banks[k].checksum for k in sorted(banks)}}
    )
    bound = dataclasses.replace(base, factor_banks_by_k=banks, factor_checksum=aggregate)

    _verify_factor_banks(bound, require_banks=True)

    changed = np.array(bound.factors_by_k[4], copy=True)
    changed[0, 0] += 1.0
    mismatched = dataclasses.replace(bound, factors_by_k={**bound.factors_by_k, 4: changed})
    with pytest.raises(ValueError, match="does not match bank"):
        _verify_factor_banks(mismatched, require_banks=True)


def test_scientific_data_assets_are_hashed_from_actual_files(tmp_path):
    raw_path = tmp_path / "source.bin"
    raw_path.write_bytes(b"audited source bytes")
    raw_digest = sha256_file(raw_path)
    card = {"raw_or_source": {"digest": raw_digest}, "dataset": "fixture-card"}
    card_path = tmp_path / "data-card.json"
    card_path.write_text(json.dumps(card), encoding="utf-8")

    inst = _build_instance(np.random.default_rng(58))
    inputs = _inputs(
        inst,
        data_card_checksum=sha256_json(card),
        raw_data_checksum=raw_digest,
    )
    _verify_scientific_data_assets(
        inputs,
        data_card_path=card_path,
        raw_asset_path=raw_path,
    )

    raw_path.write_bytes(b"changed after binding")
    with pytest.raises(ValueError, match="raw/source digest mismatch"):
        _verify_scientific_data_assets(
            inputs,
            data_card_path=card_path,
            raw_asset_path=raw_path,
        )


def test_scientific_response_artifact_binds_space_and_control_mean():
    X = np.arange(60, dtype=np.float64).reshape(10, 6) + 1.0
    controls = np.array([0, 1, 2])
    singles = np.array([3, 4, 5])
    space = fit_response_space(
        X,
        control_idx=controls,
        eligible_single_idx=singles,
        n_hvg=4,
        pca_dim=2,
        seed=0,
    )
    control_mean = space.project(X, controls).mean(axis=0)
    _, _, checksum = verify_response_artifact(space, control_mean)
    artifact = {
        "response_space": space,
        "control_mean": control_mean,
        "checksum": checksum,
    }
    inst = _build_instance(np.random.default_rng(59))
    inputs = _inputs(inst, response_space_checksum=checksum)

    _verify_scientific_response_artifact(inputs, artifact)

    artifact["control_mean"] = control_mean + 1e-12
    with pytest.raises(ValueError, match="checksum"):
        _verify_scientific_response_artifact(inputs, artifact)


def test_reordered_outcome_pair_ids_are_rejected():
    rng = np.random.default_rng(53)
    inst = _build_instance(rng)
    reversed_ids = tuple(reversed(inst["cal_pairs_id"]))
    with pytest.raises(ValueError, match="aligned"):
        run_phase2a_fixture(
            _inputs(inst),
            _store(inst, combo_calibration_pair_ids=reversed_ids),
            expected_hashes=_HASHES,
        )


def test_calibration_string_and_index_pairs_must_match_gene_index():
    rng = np.random.default_rng(104)
    inst = _build_instance(rng)
    bad_idx = list(inst["cal_pairs_idx"])
    bad_idx[0], bad_idx[1] = bad_idx[1], bad_idx[0]
    with pytest.raises(ValueError, match="calibration pair mismatch"):
        run_phase2a_fixture(
            _inputs(inst, cal_idx_pairs=bad_idx),
            _store(inst),
            expected_hashes=_HASHES,
        )


def test_gene_index_must_be_bijective():
    rng = np.random.default_rng(105)
    inst = _build_instance(rng)
    bad_index = dict(inst["gene_index"])
    genes = list(bad_index)
    bad_index[genes[1]] = bad_index[genes[0]]
    with pytest.raises(ValueError, match="bijection"):
        run_phase2a_fixture(
            _inputs(inst, gene_index=bad_index),
            _store(inst),
            expected_hashes=_HASHES,
        )


def test_outcome_audit_must_bind_the_same_manifest():
    rng = np.random.default_rng(57)
    inst = _build_instance(rng)
    audit = dataclasses.replace(_store(inst).access_audit, manifest_checksum="other-manifest")
    with pytest.raises(ValueError, match="audit manifest"):
        run_phase2a_fixture(
            _inputs(inst),
            _store(inst, access_audit=audit),
            expected_hashes=_HASHES,
        )


def test_nonzero_sealed_access_audit_is_rejected_at_construction():
    rng = np.random.default_rng(58)
    inst = _build_instance(rng)
    audit = dataclasses.replace(_store(inst).access_audit, sealed_access_count=1)
    with pytest.raises(OutcomeLeakageError, match="non-zero sealed access"):
        _store(inst, access_audit=audit)


def test_runtime_grid_must_equal_preregistered_config():
    rng = np.random.default_rng(54)
    inst = _build_instance(rng)
    with pytest.raises(ValueError, match="k_total_grid"):
        run_phase2a_fixture(
            _inputs(inst, k_total_grid=[4]),
            _store(inst),
            expected_hashes=_HASHES,
        )


def test_run_id_is_recomputed_from_provenance():
    rng = np.random.default_rng(55)
    inst = _build_instance(rng)
    with pytest.raises(ValueError, match="run_id mismatch"):
        run_phase2a_fixture(
            _inputs(inst, run_id="0000000000000000"),
            _store(inst),
            expected_hashes=_HASHES,
        )


# --------------------------------------------------------------------------- #
# futility -> NO bundle, no sealed predictions, seal closed
# --------------------------------------------------------------------------- #
def test_futility_writes_no_bundle(monkeypatch):
    rng = np.random.default_rng(7)
    inst = _build_instance(rng)
    # force the OOF theta <= 0 by making the additive comparator perfect (so L1
    # cannot beat it) — replace eps targets to equal additive exactly.
    store = _store(inst, combo_calibration_eps=inst["additive_cal"])
    res = run_phase2a_fixture(_inputs(inst), store, expected_hashes=_HASHES)
    assert res.futility_status == "FUTILITY_STOPPED"
    assert res.bundle is None
    assert res.sealed_access_count == 0


def test_futility_does_not_write_bundle_file(tmp_path):
    rng = np.random.default_rng(8)
    inst = _build_instance(rng)
    store = _store(inst, combo_calibration_eps=inst["additive_cal"])
    out = tmp_path / "bundle.json"
    res = run_phase2a_fixture(_inputs(inst), store, expected_hashes=_HASHES, bundle_path=out)
    assert res.bundle is None
    assert not out.exists()


# --------------------------------------------------------------------------- #
# recursive sealed-reference rejection in the outcome store / inputs
# --------------------------------------------------------------------------- #
def test_store_with_sealed_outcome_attribute_is_rejected():
    rng = np.random.default_rng(9)
    inst = _build_instance(rng)
    store = _store(inst)
    # inject a sealed-outcome attribute onto the store (simulating a leaked handle)
    object.__setattr__(store, "sealed_double_unseen_eps", inst["eps_cal"])
    with pytest.raises(OutcomeLeakageError):
        run_phase2a_fixture(_inputs(inst), store, expected_hashes=_HASHES)


def test_store_with_sealed_path_nested_deep_is_rejected():
    rng = np.random.default_rng(10)
    inst = _build_instance(rng)
    store = _store(inst)
    object.__setattr__(
        store, "extra", {"a": [{"b": ["ok", "data/sealed_single_unseen/outcomes.npy"]}]}
    )
    with pytest.raises(OutcomeLeakageError):
        run_phase2a_fixture(_inputs(inst), store, expected_hashes=_HASHES)


def test_inputs_with_sealed_token_in_diagnostics_path_rejected():
    rng = np.random.default_rng(11)
    inst = _build_instance(rng)
    # a sealed token smuggled into the run_id-adjacent free field
    bad = _inputs(inst, run_id="run-sealed_double_unseen-xyz")
    with pytest.raises(OutcomeLeakageError):
        run_phase2a_fixture(bad, _store(inst), expected_hashes=_HASHES)


def test_inputs_with_sealed_token_in_cal_pair_ids_rejected():
    # the full-dataclass scan must fire on a sealed token planted in cal_pair_ids
    # (a field the old enumerated subset-scan never touched).
    rng = np.random.default_rng(14)
    inst = _build_instance(rng)
    bad_cal = list(inst["cal_pairs_id"])
    bad_cal[0] = _canon("sealed_double_unseen", bad_cal[0][1])
    bad = _inputs(inst, cal_pair_ids=bad_cal)
    with pytest.raises(OutcomeLeakageError):
        run_phase2a_fixture(bad, _store(inst), expected_hashes=_HASHES)


def test_inputs_with_sealed_token_in_factors_by_k_key_rejected():
    # a sealed token planted as a factors_by_k *key* (string) must also be caught.
    rng = np.random.default_rng(15)
    inst = _build_instance(rng)
    bad_factors = {inst["k"]: inst["Z"], "sealed_single_unseen": inst["Z"]}
    bad = _inputs(inst, factors_by_k=bad_factors)
    with pytest.raises(OutcomeLeakageError):
        run_phase2a_fixture(bad, _store(inst), expected_hashes=_HASHES)


def test_inputs_with_sealed_token_in_cal_idx_pairs_rejected():
    # cal_idx_pairs normally carries ints, but a smuggled string token must fail
    # closed too — the recursive scan tolerates the int leaves and fires on the str.
    rng = np.random.default_rng(16)
    inst = _build_instance(rng)
    bad_idx = list(inst["cal_pairs_idx"]) + [("sealed", "x")]
    bad = _inputs(inst, cal_idx_pairs=bad_idx)
    with pytest.raises(OutcomeLeakageError):
        run_phase2a_fixture(bad, _store(inst), expected_hashes=_HASHES)


def test_inputs_with_outcome_token_in_string_field_rejected():
    # the outcome-token scan must now cover the whole inputs object, not just the
    # store + run_id: an outcome marker in cal_pair_ids must fail closed.
    rng = np.random.default_rng(17)
    inst = _build_instance(rng)
    bad_cal = list(inst["cal_pairs_id"])
    bad_cal[0] = _canon("y_true_x", bad_cal[0][1])
    bad = _inputs(inst, cal_pair_ids=bad_cal)
    with pytest.raises(OutcomeLeakageError):
        run_phase2a_fixture(bad, _store(inst), expected_hashes=_HASHES)


def test_audited_unsealed_store_passes_the_leakage_scan():
    # The scientific source_kind is 'audited_unsealed' (it contains the substring
    # "sealed"). The leakage scan must NOT false-trip on that construction-validated
    # enum: it is the only legal scientific value, so a trip here would make the
    # activated path unreachable. The scan passes; the run still stops at the
    # activation guard (blocked config) with ScientificModeError, never with a
    # leakage error.
    rng = np.random.default_rng(59)
    inst = _build_instance(rng)
    sci_audit = dataclasses.replace(_store(inst).access_audit, source_kind="audited_unsealed")
    store = _store(inst, access_audit=sci_audit)
    # The leakage wall itself is clean for a legitimate scientific store.
    _scan_inputs_for_leakage(_inputs(inst), store)
    # End-to-end: the blocked config stops at the guard, not the (false) scan.
    with pytest.raises(ScientificModeError):
        run_phase2a(
            _inputs(inst),
            store,
            fixture_mode=False,
            expected_hashes=_HASHES,
        )


# --------------------------------------------------------------------------- #
# sealed access count stays zero in every path
# --------------------------------------------------------------------------- #
def test_sealed_access_count_zero_on_continue_and_futility():
    rng = np.random.default_rng(12)
    inst = _build_instance(rng)
    ok = run_phase2a_fixture(_inputs(inst), _store(inst), expected_hashes=_HASHES)
    assert ok.sealed_access_count == 0
    fut_store = _store(inst, combo_calibration_eps=inst["additive_cal"])
    fut = run_phase2a_fixture(_inputs(inst), fut_store, expected_hashes=_HASHES)
    assert fut.sealed_access_count == 0


def test_result_is_frozen_dataclass():
    rng = np.random.default_rng(13)
    inst = _build_instance(rng)
    res = run_phase2a_fixture(_inputs(inst), _store(inst), expected_hashes=_HASHES)
    assert dataclasses.is_dataclass(res)
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.sealed_access_count = 1  # type: ignore[misc]
