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

import numpy as np
import pytest

from alive.compose.baselines_combo import additive
from alive.compose.config2 import ScientificModeError
from alive.compose.freeze import FrozenPredictionBundle, OutcomeLeakageError
from alive.compose.models import IDOnlyModel, L1Model, L3Model
from alive.compose.operator import bilinear_predict
from alive.compose.phase2a import (
    DevelopmentOutcomeStore,
    Phase2aInputs,
    Phase2aResult,
    run_phase2a,
)

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
        "id_only": IDOnlyModel,
        "l3_hypernetwork": L3Model,
    }


def _inputs(inst, **overrides) -> Phase2aInputs:
    kwargs = dict(
        run_id="abc123abc123abc1",
        gene_index=inst["gene_index"],
        factors_by_k={inst["k"]: inst["Z"]},
        cal_idx_pairs=inst["cal_pairs_idx"],
        cal_pair_ids=inst["cal_pairs_id"],
        additive_cal=inst["additive_cal"],
        eps_split_a=inst["eps_a"],
        eps_split_b=inst["eps_b"],
        k_total_grid=[inst["k"]],
        lambda_grid=[0.0, 1e-3],
        n_genes=len(inst["gene_ids"]),
        n_folds=3,
        seed=11,
        uncovered_tolerance=1.0,
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
    )
    kwargs.update(overrides)
    return Phase2aInputs(**kwargs)


def _store(inst, **overrides) -> DevelopmentOutcomeStore:
    """A development outcome store exposing only the unsealed calibration eps."""
    kwargs = dict(
        combo_calibration_eps=inst["eps_cal"],
        combo_calibration_pair_ids=inst["cal_pairs_id"],
    )
    kwargs.update(overrides)
    return DevelopmentOutcomeStore(**kwargs)


_HASHES = dict(
    response_space_checksum="rs-checksum",
    factor_checksum="zf-checksum",
    model_checksum="model-checksum",
    manifest_checksum="manifest-checksum",
    environment_checksum="env-checksum",
)


# --------------------------------------------------------------------------- #
# happy path: CONTINUE -> frozen bundle with predictions only
# --------------------------------------------------------------------------- #
def test_continue_produces_a_verified_bundle_no_outcomes():
    rng = np.random.default_rng(0)
    inst = _build_instance(rng)
    res = run_phase2a(_inputs(inst), _store(inst), fixture_mode=True, expected_hashes=_HASHES)
    assert isinstance(res, Phase2aResult)
    assert res.futility_status == "CONTINUE"
    assert res.sealed_access_count == 0
    assert isinstance(res.bundle, FrozenPredictionBundle)
    res.bundle.verify()
    res.bundle.assert_no_outcomes()
    # roster covers the registered methods
    for m in ("l1_bilinear_identifiable", "additive", "no_change", "id_only", "l3_hypernetwork"):
        assert m in res.bundle.method_roster
    # predictions exist for exactly the registered sealed pairs
    assert set(res.bundle.predictions_double_unseen["additive"]) == set(inst["sealed_double_id"])
    assert set(res.bundle.predictions_single_unseen["additive"]) == set(inst["sealed_single_id"])


def test_l1_prediction_equals_identity_only_path():
    # predictions must be generated from identities/features only: for L1 the
    # double-shift prediction is bilinear_predict(coef, z_g, z_h) + additive(d_g, d_h).
    rng = np.random.default_rng(1)
    inst = _build_instance(rng)
    res = run_phase2a(_inputs(inst), _store(inst), fixture_mode=True, expected_hashes=_HASHES)

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
    res = run_phase2a(_inputs(inst), _store(inst), fixture_mode=True, expected_hashes=_HASHES)
    for g, h in inst["sealed_double_id"]:
        expected = additive(inst["delta_by_gene"][g], inst["delta_by_gene"][h])
        got = res.bundle.predictions_double_unseen["additive"][(g, h)]
        np.testing.assert_allclose(got, expected, rtol=1e-9, atol=1e-9)


def test_no_change_prediction_is_zero():
    rng = np.random.default_rng(3)
    inst = _build_instance(rng)
    res = run_phase2a(_inputs(inst), _store(inst), fixture_mode=True, expected_hashes=_HASHES)
    for g, h in inst["sealed_double_id"]:
        got = res.bundle.predictions_double_unseen["no_change"][(g, h)]
        np.testing.assert_array_equal(got, np.zeros(inst["p"]))


def test_bundle_written_once(tmp_path):
    rng = np.random.default_rng(4)
    inst = _build_instance(rng)
    out = tmp_path / "compose" / "bundle.json"
    res = run_phase2a(
        _inputs(inst), _store(inst), fixture_mode=True, expected_hashes=_HASHES, bundle_path=out
    )
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


# --------------------------------------------------------------------------- #
# upstream hash verification (step 2) aborts before prediction
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "bad_key",
    ["response_space_checksum", "factor_checksum", "manifest_checksum", "environment_checksum"],
)
def test_hash_mismatch_aborts(bad_key):
    rng = np.random.default_rng(6)
    inst = _build_instance(rng)
    tampered = dict(_HASHES)
    tampered[bad_key] = "WRONG"
    with pytest.raises(ValueError, match="hash|checksum"):
        run_phase2a(_inputs(inst), _store(inst), fixture_mode=True, expected_hashes=tampered)


# --------------------------------------------------------------------------- #
# futility -> NO bundle, no sealed predictions, seal closed
# --------------------------------------------------------------------------- #
def test_futility_writes_no_bundle(monkeypatch):
    rng = np.random.default_rng(7)
    inst = _build_instance(rng)
    # force the OOF theta <= 0 by making the additive comparator perfect (so L1
    # cannot beat it) — replace eps targets to equal additive exactly.
    store = _store(inst, combo_calibration_eps=inst["additive_cal"])
    res = run_phase2a(_inputs(inst), store, fixture_mode=True, expected_hashes=_HASHES)
    assert res.futility_status == "FUTILITY_STOPPED"
    assert res.bundle is None
    assert res.sealed_access_count == 0


def test_futility_does_not_write_bundle_file(tmp_path):
    rng = np.random.default_rng(8)
    inst = _build_instance(rng)
    store = _store(inst, combo_calibration_eps=inst["additive_cal"])
    out = tmp_path / "bundle.json"
    res = run_phase2a(
        _inputs(inst), store, fixture_mode=True, expected_hashes=_HASHES, bundle_path=out
    )
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
        run_phase2a(_inputs(inst), store, fixture_mode=True, expected_hashes=_HASHES)


def test_store_with_sealed_path_nested_deep_is_rejected():
    rng = np.random.default_rng(10)
    inst = _build_instance(rng)
    store = _store(inst)
    object.__setattr__(
        store, "extra", {"a": [{"b": ["ok", "data/sealed_single_unseen/outcomes.npy"]}]}
    )
    with pytest.raises(OutcomeLeakageError):
        run_phase2a(_inputs(inst), store, fixture_mode=True, expected_hashes=_HASHES)


def test_inputs_with_sealed_token_in_diagnostics_path_rejected():
    rng = np.random.default_rng(11)
    inst = _build_instance(rng)
    # a sealed token smuggled into the run_id-adjacent free field
    bad = _inputs(inst, run_id="run-sealed_double_unseen-xyz")
    with pytest.raises(OutcomeLeakageError):
        run_phase2a(bad, _store(inst), fixture_mode=True, expected_hashes=_HASHES)


# --------------------------------------------------------------------------- #
# sealed access count stays zero in every path
# --------------------------------------------------------------------------- #
def test_sealed_access_count_zero_on_continue_and_futility():
    rng = np.random.default_rng(12)
    inst = _build_instance(rng)
    ok = run_phase2a(_inputs(inst), _store(inst), fixture_mode=True, expected_hashes=_HASHES)
    assert ok.sealed_access_count == 0
    fut_store = _store(inst, combo_calibration_eps=inst["additive_cal"])
    fut = run_phase2a(_inputs(inst), fut_store, fixture_mode=True, expected_hashes=_HASHES)
    assert fut.sealed_access_count == 0


def test_result_is_frozen_dataclass():
    rng = np.random.default_rng(13)
    inst = _build_instance(rng)
    res = run_phase2a(_inputs(inst), _store(inst), fixture_mode=True, expected_hashes=_HASHES)
    assert dataclasses.is_dataclass(res)
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.sealed_access_count = 1  # type: ignore[misc]
