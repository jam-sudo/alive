"""Tests for alive.compose.phase2a — written FIRST per TDD protocol (Task 2a-11).

``run_phase2a`` is the no-seal Phase-2a orchestrator. It ties Tasks 2a-1..2a-10
together and produces the frozen handoff Phase 2b consumes. SYNTHETIC-ONLY:
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
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import sparse

from alive.compose.baseline_subprocess import ExecutionIdentityLock, SubprocessBaselineBackend
from alive.compose.baselines_combo import BaselineAdapter, additive
from alive.compose.config2 import ScientificModeError, load_compose_phase2_config
from alive.compose.datacard import compute_compose_run_id
from alive.compose.fit_role import FitRoleExtraction, generate_fit_role_artifact
from alive.compose.freeze import FrozenPredictionBundle, OutcomeLeakageError
from alive.compose.models import IDOnlyModel, L1Model, L2Model, L3Model
from alive.compose.operator import bilinear_predict
from alive.compose.phase2a import (
    DevelopmentOutcomeStore,
    OutcomeAccessAudit,
    Phase2aInputs,
    Phase2aResult,
    _combined_pair_union,
    _predict_combined_adapters,
    _predict_role,
    _scan_inputs_for_leakage,
    _verify_factor_banks,
    _verify_scientific_data_assets,
    _verify_scientific_response_artifact,
    build_subprocess_fit_payload,
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
        "l3_symmetric_mlp": L3Model,
        "id_only": IDOnlyModel,
        # Synthetic stand-ins exercise the frozen roster contract. Scientific
        # activation still requires the separately pinned GEARS/CPA backends.
        "gears": L1Model,
        "cpa": L1Model,
    }


def _response_and_fit_role(
    tmp_path,
    *,
    response_dim,
    raw_data_sha256,
    cal_pair_ids,
    single_gene_ids,
    seed=0,
    tag="a",
):
    """Assemble a real response space + a written fit-role artifact for a payload.

    Builds a synthetic raw-count matrix (positive libraries, integer counts) over
    a ``response_dim + 1``-gene transcriptome, fits a leakage-safe response space
    on the control + single rows (``pca_dim == response_dim`` so the projection
    aligns with the payload's ``response_dim``), takes the z-space control
    centroid, and writes an immutable fit-role ``.h5ad`` whose ``var_names`` equal
    the ``gene_order`` and whose ``raw_data_sha256`` equals the shared digest.

    The ``combo_calibration`` cells carry tokens drawn from ``cal_pair_ids`` (the
    payload's calibration pairs), so the operator-path worker's
    ``validate_fit_role_artifact`` guard accepts every combo cell.

    Returns
    -------
    tuple
        ``(response_artifact, gene_order, fit_role_spec, combined_checksum)`` where
        ``combined_checksum`` is ``verify_response_artifact(space, control_mean)[2]``.
    """
    rng = np.random.default_rng(4242 + seed)
    n_genes = response_dim + 1
    gene_order = [f"T{i}" for i in range(n_genes)]
    combo_pairs = [tuple(p) for p in cal_pair_ids][:4]
    single_genes = list(single_gene_ids)
    n_control, n_single, n_combo = 12, len(single_genes), len(combo_pairs)
    n_cells = n_control + n_single + n_combo
    counts = rng.integers(1, 50, size=(n_cells, n_genes)).astype(np.float64)
    X = sparse.csr_matrix(counts)
    control_idx = np.arange(0, n_control)
    single_idx = np.arange(n_control, n_control + n_single)
    space = fit_response_space(
        X,
        control_idx=control_idx,
        eligible_single_idx=single_idx,
        n_hvg=n_genes,
        pca_dim=response_dim,
        seed=seed,
    )
    control_mean = space.project(X, control_idx).mean(axis=0)
    _, _, combined = verify_response_artifact(space, control_mean)

    # singles-cell tokens are drawn from the combo-pair genes, which are exactly
    # the payload's ``single_gene_ids`` universe (``inputs.delta_by_gene`` keys).
    # The fit-role validator rejects any `singles` token outside that universe
    # (the sealed-combo-as-single leak guard).
    rows = (
        [(f"c{i}", "control", "control") for i in range(n_control)]
        + [(f"s{i}", "singles", gene) for i, gene in enumerate(single_genes)]
        + [(f"m{i}", "combo_calibration", f"{a}_{b}") for i, (a, b) in enumerate(combo_pairs)]
    )
    extraction = FitRoleExtraction(
        X=X,
        var_names=tuple(gene_order),
        rows=tuple(rows),
        role_counts={"control": n_control, "singles": n_single, "combo_calibration": n_combo},
        raw_data_sha256=raw_data_sha256,
        pair_manifest_sha256=f"pair-manifest-{tag}",
        eligibility_hash=f"eligibility-{tag}",
    )
    spec = generate_fit_role_artifact(
        extraction=extraction,
        out_path=str(Path(tmp_path) / f"fit_role_{tag}.h5ad"),
        config_sha256="config-sha",
        data_card_sha256="data-card-sha",
        calibration_gene_set_hash="cal-set-sha",
        generator_code_sha256="gen-code-sha",
        writer_environment_sha256="writer-env-sha",
    )
    response_artifact = {"response_space": space, "control_mean": control_mean}
    return response_artifact, gene_order, spec, combined


def _stub_execution_lock(
    prediction_representation: str = "cell_raw_counts",
) -> ExecutionIdentityLock:
    """The lock whose identities match ``stub_worker.py``'s emitted manifest."""
    return ExecutionIdentityLock(
        prediction_representation=prediction_representation,
        adapter_version="stub-2",
        adapter_sha256=hashlib.sha256(b"stub-response-operator-v2").hexdigest(),
        config_sha256=hashlib.sha256(b"stub-config").hexdigest(),
        resource_sha256=hashlib.sha256(b"stub-resource").hexdigest(),
        environment_lock_sha256=hashlib.sha256(b"stub-environment").hexdigest(),
    )


def _subprocess_adapters(inputs: Phase2aInputs, store: DevelopmentOutcomeStore, tmp_path):
    response_artifact, gene_order, fit_role_spec, combined = _response_and_fit_role(
        tmp_path,
        response_dim=inputs.response_dim,
        raw_data_sha256="subproc-shared-raw",
        cal_pair_ids=inputs.cal_pair_ids,
        single_gene_ids=list(inputs.delta_by_gene),
    )
    # The run inputs and every backend consume the SAME independently verified
    # response artifact. Returning the aligned inputs prevents fixture tests from
    # masking the runtime response-space binding enforced by the orchestrator.
    payload_inputs = dataclasses.replace(inputs, response_space_checksum=combined)
    payload = build_subprocess_fit_payload(
        inputs=payload_inputs,
        outcome_store=store,
        response_artifact=response_artifact,
        oof_folds=[0] * len(inputs.cal_pair_ids),
        fit_role_spec=fit_role_spec,
        gene_order=gene_order,
        raw_data_sha256="subproc-shared-raw",
    )
    worker = Path(__file__).parents[3] / "scripts" / "baselines" / "stub_worker.py"
    adapters = {}
    representations = {
        "gears": "raw_pseudobulk_approximation",
        "cpa": "cell_raw_counts",
    }
    for name in ("gears", "cpa"):
        backend = SubprocessBaselineBackend(
            name=name,
            env_python=sys.executable,
            worker_script=str(worker),
            import_name="json",
            seed=inputs.seed,
            approved_artifacts_root=str(tmp_path),
            expected_response_artifact_sha256=combined,
            execution_identity_lock=_stub_execution_lock(representations[name]),
            allow_local_approved_root_checkpoint_store=True,
        )
        backend.configure_payload(payload)
        adapters[name] = BaselineAdapter(name=name, backend=backend)
    return adapters, payload_inputs


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
    assert len(res.bundle.model_checksum) == 64
    assert res.bundle.model_checksum != "model-checksum"
    assert res.ledger.artifact_sha("model") == res.bundle.model_checksum
    res.bundle.assert_no_outcomes()
    cfg = load_compose_phase2_config("configs/compose_k562_v1_phase2.yaml")
    assert res.bundle.method_roster == cfg.method_roster
    assert res.ledger.to_dict()["config_sha256"] == cfg.config_sha256
    # predictions exist for exactly the registered sealed pairs
    assert set(res.bundle.predictions_double_unseen["additive"]) == set(inst["sealed_double_id"])
    assert set(res.bundle.predictions_single_unseen["additive"]) == set(inst["sealed_single_id"])


def test_subprocess_baselines_are_wired_into_phase2a_freeze(tmp_path):
    inst = _build_instance(np.random.default_rng(31))
    local_factories = {
        name: factory
        for name, factory in _model_factories().items()
        if name not in {"gears", "cpa"}
    }
    inputs = _inputs(inst, model_factories=local_factories)
    store = _store(inst)
    adapters, inputs = _subprocess_adapters(inputs, store, tmp_path)
    expected_hashes = {**_HASHES, "response_space_checksum": inputs.response_space_checksum}
    res = run_phase2a_fixture(
        inputs,
        store,
        expected_hashes=expected_hashes,
        baseline_adapters=adapters,
    )
    assert res.bundle is not None
    for method in ("gears", "cpa"):
        assert set(res.bundle.predictions_double_unseen[method]) == set(inst["sealed_double_id"])
        assert set(res.bundle.predictions_single_unseen[method]) == set(inst["sealed_single_id"])
    assert res.method_lock is not None
    assert len(res.method_lock["method_roster"]) == 9


def test_phase2a_rejects_adapter_response_space_divergence(tmp_path):
    inst = _build_instance(np.random.default_rng(32))
    local_factories = {
        name: factory
        for name, factory in _model_factories().items()
        if name not in {"gears", "cpa"}
    }
    inputs = _inputs(inst, model_factories=local_factories)
    store = _store(inst)
    adapters, inputs = _subprocess_adapters(inputs, store, tmp_path)
    adapters["gears"].backend.expected_response_artifact_sha256 = "f" * 64
    expected_hashes = {**_HASHES, "response_space_checksum": inputs.response_space_checksum}
    with pytest.raises(ScientificModeError, match="response_space"):
        run_phase2a_fixture(
            inputs,
            store,
            expected_hashes=expected_hashes,
            baseline_adapters=adapters,
        )


def test_phase2a_rejects_adapter_representation_divergence(tmp_path):
    inst = _build_instance(np.random.default_rng(33))
    local_factories = {
        name: factory
        for name, factory in _model_factories().items()
        if name not in {"gears", "cpa"}
    }
    inputs = _inputs(inst, model_factories=local_factories)
    store = _store(inst)
    adapters, inputs = _subprocess_adapters(inputs, store, tmp_path)
    adapters["gears"].backend.execution_identity_lock = _stub_execution_lock("cell_raw_counts")
    expected_hashes = {**_HASHES, "response_space_checksum": inputs.response_space_checksum}
    with pytest.raises(ScientificModeError, match="prediction_representation"):
        run_phase2a_fixture(
            inputs,
            store,
            expected_hashes=expected_hashes,
            baseline_adapters=adapters,
        )


def test_build_subprocess_payload_is_v2_with_consistent_blocks(tmp_path):
    inst = _build_instance(np.random.default_rng(77))
    inputs_base = _inputs(inst)
    store = _store(inst)
    response_artifact, gene_order, fit_role_spec, combined = _response_and_fit_role(
        tmp_path,
        response_dim=inputs_base.response_dim,
        raw_data_sha256="shared_raw",
        cal_pair_ids=inputs_base.cal_pair_ids,
        single_gene_ids=list(inputs_base.delta_by_gene),
    )
    # bind the independently verified response-artifact digest onto the inputs
    inputs = _inputs(inst, response_space_checksum=combined)
    payload = build_subprocess_fit_payload(
        inputs=inputs,
        outcome_store=store,
        response_artifact=response_artifact,
        oof_folds=[0] * len(inputs.cal_pair_ids),
        fit_role_spec=fit_role_spec,
        gene_order=gene_order,
        raw_data_sha256="shared_raw",
    )
    assert payload["schema_version"] == 2
    assert (
        payload["response_projection"]["raw_data_sha256"]
        == payload["fit_role_artifact"]["raw_data_sha256"]
    )
    assert (
        payload["response_projection"]["response_artifact_sha256"] == inputs.response_space_checksum
    )
    from alive.compose.baseline_subprocess import _validate_payload

    _validate_payload(payload, expected_response_artifact_sha256=inputs.response_space_checksum)


def test_build_subprocess_payload_rejects_unverified_response_artifact(tmp_path):
    # Same Fixture-contract assembly as the Task-4 consistency test, but the bound
    # response-space checksum is corrupted so it no longer equals the projection's
    # independently verified response digest. The emitter must fail closed BEFORE a
    # payload is returned (Global Constraint "Response artifact equality is not
    # circular"; spec §2.2).
    inst = _build_instance(np.random.default_rng(77))
    store = _store(inst)
    base_inputs = _inputs(inst)
    response_artifact, gene_order, fit_role_spec, combined = _response_and_fit_role(
        tmp_path,
        response_dim=base_inputs.response_dim,
        raw_data_sha256="shared_raw",
        cal_pair_ids=base_inputs.cal_pair_ids,
        single_gene_ids=list(base_inputs.delta_by_gene),
    )
    inputs = _inputs(inst, response_space_checksum=combined)
    inputs = dataclasses.replace(inputs, response_space_checksum="f" * 64)
    with pytest.raises(ValueError, match="independently verified response artifact"):
        build_subprocess_fit_payload(
            inputs=inputs,
            outcome_store=store,
            response_artifact=response_artifact,
            oof_folds=[0] * len(inputs.cal_pair_ids),
            fit_role_spec=fit_role_spec,
            gene_order=gene_order,
            raw_data_sha256="shared_raw",
        )


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


def test_oof_fold_manifest_shares_one_checksum_across_bundle_lock_ledger_disk(tmp_path):
    # The persisted OOF fold manifest checksum is bound identically into the frozen
    # bundle diagnostics, the method lock, the ledger artifact and the on-disk
    # manifest — one checksum, four surfaces (D2 Task 1).
    from alive.compose.select import OOFFoldManifest

    rng = np.random.default_rng(41)
    inst = _build_instance(rng)
    out = tmp_path / "compose" / "oof_fold_manifest.json"
    res = run_phase2a_fixture(
        _inputs(inst), _store(inst), expected_hashes=_HASHES, oof_manifest_path=out
    )
    assert res.futility_status == "CONTINUE"
    checksum = res.oof_manifest.manifest_checksum
    assert len(checksum) == 64
    assert res.futility.oof_manifest.manifest_checksum == checksum
    # bundle diagnostics
    assert res.bundle.dev_diagnostics["oof_fold_manifest_checksum"] == checksum
    res.bundle.verify()
    # method lock
    assert res.method_lock["oof_fold_manifest_checksum"] == checksum
    # ledger artifact
    assert res.ledger.artifact_sha("phase2a_oof_fold_manifest") == checksum
    # on-disk manifest loads, verifies and matches
    assert out.exists()
    loaded = OOFFoldManifest.load(out)
    assert loaded.manifest_checksum == checksum
    # the manifest describes the calibration design of this run
    assert loaded.calibration_pair_ids == tuple(tuple(p) for p in inst["cal_pairs_id"])


def test_oof_fold_manifest_returned_in_memory_on_futility(tmp_path):
    # On a futility stop the manifest is still returned in memory, but NOT written
    # and NOT bound into a bundle/lock/ledger (there is no bundle on futility).
    rng = np.random.default_rng(42)
    inst = _build_instance(rng)
    store = _store(
        inst, combo_calibration_eps=np.zeros_like(inst["additive_cal"])
    )  # comparator exact -> theta == 0.0
    out = tmp_path / "futility_manifest.json"
    res = run_phase2a_fixture(_inputs(inst), store, expected_hashes=_HASHES, oof_manifest_path=out)
    assert res.futility_status == "FUTILITY_STOPPED"
    assert res.bundle is None
    assert res.method_lock is None
    assert res.oof_manifest is not None
    assert len(res.oof_manifest.manifest_checksum) == 64
    assert not out.exists()  # futility writes no manifest


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


# A GI residual of exactly zero makes the additive comparator EXACTLY correct, so
# the operator can at best tie it: theta == 0.0, and the registered futility
# condition is ``oof_theta <= dev_oof_threshold`` with the threshold at 0.0.
#
# The earlier construction passed ``inst["additive_cal"]`` instead, whose own
# comment claimed it made "the additive comparator perfect" -- it did not. It left
# a sliver of learnable structure, and futility depended on the operator
# OVERFITTING it into a slightly negative theta. When ``identification.lambda_scaling``
# made the registered lambda mean what it says, the overfit went away, theta rose to
# +0.0019 and two of these tests flipped to CONTINUE while a third (same
# construction, different seed) did not -- they were sitting on the boundary.
# Zero eps removes the dependence on regularization strength entirely.
_FUTILE_EPS_NOTE = None


# --------------------------------------------------------------------------- #
# futility -> NO bundle, no sealed predictions, seal closed
# --------------------------------------------------------------------------- #
def test_futility_writes_no_bundle(monkeypatch):
    rng = np.random.default_rng(7)
    inst = _build_instance(rng)
    # force the OOF theta <= 0 by making the additive comparator perfect (so L1
    # cannot beat it) — replace eps targets to equal additive exactly.
    store = _store(inst, combo_calibration_eps=np.zeros_like(inst["additive_cal"]))
    res = run_phase2a_fixture(_inputs(inst), store, expected_hashes=_HASHES)
    assert res.futility_status == "FUTILITY_STOPPED"
    assert res.bundle is None
    assert res.sealed_access_count == 0


def test_futility_does_not_write_bundle_file(tmp_path):
    rng = np.random.default_rng(8)
    inst = _build_instance(rng)
    store = _store(inst, combo_calibration_eps=np.zeros_like(inst["additive_cal"]))
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
    fut_store = _store(inst, combo_calibration_eps=np.zeros_like(inst["additive_cal"]))
    fut = run_phase2a_fixture(_inputs(inst), fut_store, expected_hashes=_HASHES)
    assert fut.sealed_access_count == 0


def test_result_is_frozen_dataclass():
    rng = np.random.default_rng(13)
    inst = _build_instance(rng)
    res = run_phase2a_fixture(_inputs(inst), _store(inst), expected_hashes=_HASHES)
    assert dataclasses.is_dataclass(res)
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.sealed_access_count = 1  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# §2.5 single-fit rule: subprocess adapters fit ONCE on the combined pair union
# --------------------------------------------------------------------------- #
@pytest.fixture
def minimal_inputs() -> Phase2aInputs:
    """A minimal ``Phase2aInputs`` with disjoint, non-empty sealed roles."""
    return _inputs(_build_instance(np.random.default_rng(8)))


class _SpyAdapter:
    """Duck-typed baseline adapter that records each predict() call."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple] = []

    def predict(self, context, pair_ids, response_dim):
        self.calls.append(tuple(tuple(p) for p in pair_ids))
        return {(g, h): np.full(response_dim, len(g + h), dtype=float) for g, h in pair_ids}


def test_subprocess_adapter_fits_once_for_combined_union(minimal_inputs):
    inputs = minimal_inputs  # sealed_double_pair_ids + sealed_single_pair_ids disjoint, non-empty
    spy = _SpyAdapter("gears")
    adapters = {"gears": spy}
    combined = _combined_pair_union(inputs.sealed_double_pair_ids, inputs.sealed_single_pair_ids)
    adapter_preds = _predict_combined_adapters(inputs, combined, adapters)
    assert len(spy.calls) == 1  # fit-once
    assert spy.calls[0] == tuple(combined)  # combined union, once
    Z = np.zeros((1, inputs.response_dim))
    mean = np.zeros(inputs.response_dim)
    double = _predict_role(
        inputs,
        inputs.sealed_double_pair_ids,
        {},
        Z,
        mean,
        adapters,
        adapter_predictions=adapter_preds,
    )
    single = _predict_role(
        inputs,
        inputs.sealed_single_pair_ids,
        {},
        Z,
        mean,
        adapters,
        adapter_predictions=adapter_preds,
    )
    assert len(spy.calls) == 1  # NOT re-invoked during role split
    assert set(double["gears"]) == {tuple(p) for p in inputs.sealed_double_pair_ids}
    assert set(single["gears"]) == {tuple(p) for p in inputs.sealed_single_pair_ids}
