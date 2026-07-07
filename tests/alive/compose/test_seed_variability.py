"""Tests for alive.compose.seed_variability — COMPOSE D2 Task 3 (fold jobs).

Written FIRST per TDD. ``build_fold_job`` assembles a controller-side, fold-scoped
fit job whose worker payload trains ONLY on one gene-disjoint OOF fold's TRAIN combo
pairs: the held-out TEST pairs and the cross-group EXCLUDED pairs must be fully
absent from both the fold-scoped fit-role artifact and the payload, or the OOF
seed-variability measurement leaks.

SYNTHETIC-ONLY: pure numpy + a tiny synthetic source; opens NO seal, reads NO sealed
outcome, imports NO gears/cpa. Development calibration outcomes only.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy import sparse

from alive.compose.baseline_subprocess import _REQUIRED_KEYS
from alive.compose.fit_role import (
    FitRoleExtraction,
    generate_fit_role_artifact,
)
from alive.compose.phase2a import (
    DevelopmentOutcomeStore,
    OutcomeAccessAudit,
    Phase2aInputs,
)
from alive.compose.response import fit_response_space, verify_response_artifact
from alive.compose.seed_variability import (
    FoldJob,
    FoldJobError,
    build_fold_job,
    restrict_development_store,
)
from alive.compose.select import (
    OOFFoldManifest,
    build_gene_disjoint_folds,
)

_RAW = "raw-shared-d2"
_SPLIT_SEED = 11
_N_FOLDS = 3
_P = 4  # response dim


def _canon(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a.encode("utf-8") <= b.encode("utf-8") else (b, a)


def _fixture(tmp_path: Path):
    """Full synthetic D2 fixture: base fit-role artifact + manifest + inputs + store.

    6 perturbation genes G0..G5, all calibration genes; the 15 within-gene pairs are
    all calibration pairs. A 3-fold gene-disjoint layout partitions every pair into
    TRAIN / TEST / EXCLUDED. The base fit-role artifact carries control + one single
    per gene + one combo cell per calibration pair, so the fold extractor can carve a
    train-only subset out of it.
    """
    rng = np.random.default_rng(7)
    pert_genes = [f"G{i}" for i in range(6)]
    gene_index = {g: i for i, g in enumerate(pert_genes)}
    cal_pairs_id: list[tuple[str, str]] = []
    cal_pairs_idx: list[tuple[int, int]] = []
    for i in range(6):
        for j in range(i + 1, 6):
            cal_pairs_id.append(_canon(pert_genes[i], pert_genes[j]))
            cal_pairs_idx.append((i, j))
    n_pairs = len(cal_pairs_id)  # 15

    eps_cal = rng.normal(size=(n_pairs, _P))
    additive_cal = rng.normal(size=(n_pairs, _P))
    eps_a = eps_cal + 0.01 * rng.normal(size=(n_pairs, _P))
    eps_b = eps_cal + 0.01 * rng.normal(size=(n_pairs, _P))
    delta_by_gene = {g: rng.normal(size=_P) for g in pert_genes}
    z = rng.normal(size=(6, 4))

    # --- base fit-role artifact (control + singles + ALL calibration combos) -----
    n_control, n_single = 12, 6
    n_combo = n_pairs
    n_cells = n_control + n_single + n_combo
    n_tx = _P + 1  # transcriptome genes
    counts = rng.integers(1, 50, size=(n_cells, n_tx)).astype(np.float64)
    X = sparse.csr_matrix(counts)
    gene_order = [f"T{i}" for i in range(n_tx)]
    control_idx = np.arange(0, n_control)
    single_idx = np.arange(n_control, n_control + n_single)
    space = fit_response_space(
        X,
        control_idx=control_idx,
        eligible_single_idx=single_idx,
        n_hvg=n_tx,
        pca_dim=_P,
        seed=1,
    )
    control_mean = space.project(X, control_idx).mean(axis=0)
    _, _, combined = verify_response_artifact(space, control_mean)

    rows = (
        [(f"c{i}", "control", "control") for i in range(n_control)]
        + [(f"s{i}", "singles", pert_genes[i % 6]) for i in range(n_single)]
        + [(f"m{i}", "combo_calibration", f"{a}_{b}") for i, (a, b) in enumerate(cal_pairs_id)]
    )
    extraction = FitRoleExtraction(
        X=X,
        var_names=tuple(gene_order),
        rows=tuple(rows),
        role_counts={"control": n_control, "singles": n_single, "combo_calibration": n_combo},
        raw_data_sha256=_RAW,
        pair_manifest_sha256="pm",
        eligibility_hash="elig",
    )
    base_spec = generate_fit_role_artifact(
        extraction=extraction,
        out_path=str(tmp_path / "base_fit_role.h5ad"),
        config_sha256="cfg",
        data_card_sha256="dc",
        calibration_gene_set_hash="cg",
        generator_code_sha256="gen",
        writer_environment_sha256="env",
    )
    response_artifact = {"response_space": space, "control_mean": control_mean}

    # --- OOF fold manifest (the exact single-call folds) -------------------------
    folds = build_gene_disjoint_folds(cal_pairs_idx, n_genes=6, n_folds=_N_FOLDS, seed=_SPLIT_SEED)
    manifest = OOFFoldManifest.from_folds(
        folds, pair_ids=cal_pairs_id, n_genes=6, n_folds=_N_FOLDS, split_seed=_SPLIT_SEED
    )

    inputs = Phase2aInputs(
        run_id="run-fixture",
        gene_index=gene_index,
        factors_by_k={4: z},
        cal_idx_pairs=cal_pairs_idx,
        cal_pair_ids=cal_pairs_id,
        additive_cal=additive_cal,
        eps_split_a=eps_a,
        eps_split_b=eps_b,
        k_total_grid=[4],
        lambda_grid=[0.0],
        n_genes=6,
        n_folds=_N_FOLDS,
        seed=_SPLIT_SEED,
        uncovered_tolerance=1.0,
        sealed_double_pair_ids=(),
        sealed_single_pair_ids=(),
        delta_by_gene=delta_by_gene,
        model_factories={},
        response_dim=_P,
        response_space_checksum=combined,
        factor_checksum="zf",
        manifest_checksum="mani",
        environment_checksum="env",
        registered_seeds=(11, 23, 37),
        data_card_checksum="dck",
        raw_data_checksum="rdk",
        sequence_mapping_checksum="smk",
    )
    store = DevelopmentOutcomeStore(
        combo_calibration_eps=eps_cal,
        combo_calibration_pair_ids=cal_pairs_id,
        access_audit=OutcomeAccessAudit(
            role="combo_calibration",
            manifest_checksum="mani",
            source_checksum="src",
            sealed_access_count=0,
            source_kind="synthetic_fixture",
        ),
    )
    fold_dir = tmp_path / "folds"
    return {
        "inputs": inputs,
        "store": store,
        "manifest": manifest,
        "response_artifact": response_artifact,
        "gene_order": gene_order,
        "base_spec": base_spec,
        "fold_dir": str(fold_dir),
        "cal_pairs_id": cal_pairs_id,
        "additive_cal": additive_cal,
        "eps_cal": eps_cal,
    }


def _build(fx, *, method="gears", seed=23, fold_index=0) -> FoldJob:
    return build_fold_job(
        method=method,
        seed=seed,
        fold_index=fold_index,
        oof_manifest=fx["manifest"],
        inputs=fx["inputs"],
        outcome_store=fx["store"],
        response_artifact=fx["response_artifact"],
        base_fit_role_spec=fx["base_spec"],
        fold_artifact_dir=fx["fold_dir"],
        gene_order=fx["gene_order"],
        raw_data_sha256=_RAW,
    )


# --------------------------------------------------------------------------- #
# payload schema: exactly the required keys, no fold metadata leakage
# --------------------------------------------------------------------------- #
def test_payload_key_set_is_exactly_required_keys(tmp_path):
    fx = _fixture(tmp_path)
    job = _build(fx)
    assert isinstance(job, FoldJob)
    assert set(job.payload) == set(_REQUIRED_KEYS)
    # fold metadata lives ONLY on the FoldJob, never inside the payload.
    for meta in ("fold_index", "test_pair_ids", "excluded_pair_ids", "method"):
        assert meta not in job.payload


def test_fold_metadata_lives_only_on_the_job(tmp_path):
    fx = _fixture(tmp_path)
    rec = fx["manifest"].folds[0]
    job = _build(fx, fold_index=0)
    assert job.method == "gears"
    assert job.seed == 23
    assert job.fold_index == 0
    assert job.test_pair_ids == rec.test_pair_ids
    assert job.excluded_pair_ids == rec.excluded_pair_ids
    assert job.fold_manifest_checksum == fx["manifest"].manifest_checksum
    assert job.fit_role_artifact_sha256.startswith("sha256:")
    assert Path(job.fit_role_artifact_path).is_file()


# --------------------------------------------------------------------------- #
# leakage: held-out / excluded combos absent from payload AND fold artifact
# --------------------------------------------------------------------------- #
def test_train_payload_has_no_heldout_or_excluded_pair(tmp_path):
    fx = _fixture(tmp_path)
    rec = fx["manifest"].folds[0]
    job = _build(fx, fold_index=0)
    payload_pairs = {tuple(p) for p in job.payload["calibration_pair_ids"]}
    assert payload_pairs == set(rec.train_pair_ids)
    forbidden = set(rec.test_pair_ids) | set(rec.excluded_pair_ids)
    assert payload_pairs.isdisjoint(forbidden)
    # calibration_delta has exactly one target row per train pair (no held-out rows)
    assert len(job.payload["calibration_delta"]) == len(rec.train_pair_ids)


def test_fold_fit_role_artifact_excludes_heldout_and_excluded_combos(tmp_path):
    import anndata as ad

    fx = _fixture(tmp_path)
    rec = fx["manifest"].folds[0]
    job = _build(fx, fold_index=0)
    adata = ad.read_h5ad(job.fit_role_artifact_path)
    tokens = [str(p) for p in adata.obs["perturbation"]]

    def _pair(tok: str) -> tuple[str, str]:
        a, b = tok.split("_", 1)
        return _canon(a, b)

    combos = {_pair(t) for t in tokens if "_" in t and t != "control"}
    assert combos == set(rec.train_pair_ids)
    forbidden = set(rec.test_pair_ids) | set(rec.excluded_pair_ids)
    assert combos.isdisjoint(forbidden)
    # control + single universes are intact (the artifact already re-validates as a
    # legitimate fit-role artifact inside build_fold_job against the fold's own
    # calibration/sealed sets, so a smuggled sealed/excluded cell fails closed there).
    roles = {str(r) for r in adata.obs["role"]}
    assert roles == {"control", "singles", "combo_calibration"}
    singles = {tok for tok, r in zip(tokens, adata.obs["role"]) if str(r) == "singles"}
    assert singles <= set(fx["inputs"].delta_by_gene)


# --------------------------------------------------------------------------- #
# alignment of payload target rows with train pair IDs
# --------------------------------------------------------------------------- #
def test_every_payload_target_row_aligns_with_its_train_pair(tmp_path):
    fx = _fixture(tmp_path)
    rec = fx["manifest"].folds[0]
    job = _build(fx, fold_index=0)
    train_pos = list(rec.train_pair_positions)
    payload_pairs = [tuple(p) for p in job.payload["calibration_pair_ids"]]
    assert tuple(payload_pairs) == rec.train_pair_ids
    expected_delta = fx["additive_cal"][train_pos] + fx["eps_cal"][train_pos]
    np.testing.assert_allclose(
        np.asarray(job.payload["calibration_delta"], dtype=float), expected_delta
    )


# --------------------------------------------------------------------------- #
# oof_folds labels: covered -> outer test-fold index, uncovered -> n_folds sentinel
# --------------------------------------------------------------------------- #
def test_oof_folds_labels_match_the_manifest(tmp_path):
    fx = _fixture(tmp_path)
    manifest = fx["manifest"]
    rec = manifest.folds[0]
    job = _build(fx, fold_index=0)
    labels = list(job.payload["oof_folds"])
    assert len(labels) == len(rec.train_pair_ids)
    test_fold_of: dict[tuple[str, str], int] = {}
    for r in manifest.folds:
        for pid in r.test_pair_ids:
            test_fold_of[pid] = r.fold_index
    covered = set(manifest.covered_pair_ids)
    seen_covered = seen_sentinel = False
    for pid, label in zip(rec.train_pair_ids, labels):
        if pid in covered:
            assert label == test_fold_of[pid] < manifest.n_folds
            seen_covered = True
        else:
            assert label == manifest.n_folds
            seen_sentinel = True
    # this fixture is constructed so BOTH label kinds are exercised
    assert seen_covered and seen_sentinel


# --------------------------------------------------------------------------- #
# store restriction: audit identity preserved, checksum recomputed over subset
# --------------------------------------------------------------------------- #
def test_store_restriction_preserves_audit_and_recomputes_checksum(tmp_path):
    fx = _fixture(tmp_path)
    store = fx["store"]
    rec = fx["manifest"].folds[0]
    positions = list(rec.train_pair_positions)
    restricted = restrict_development_store(store, positions=positions, pair_ids=rec.train_pair_ids)
    assert restricted.combo_calibration_pair_ids == rec.train_pair_ids
    assert restricted.combo_calibration_eps.shape[0] == len(positions)
    np.testing.assert_array_equal(
        restricted.combo_calibration_eps,
        np.asarray(store.combo_calibration_eps)[positions],
    )
    # audit identity is preserved bit-for-bit; the dev store has no sealed role.
    assert restricted.access_audit == store.access_audit
    assert restricted.access_audit.sealed_access_count == 0
    # content checksum is recomputed over the SUBSET (differs from the full store).
    assert len(restricted.content_checksum) == 64
    assert restricted.content_checksum != store.content_checksum


# --------------------------------------------------------------------------- #
# a manifest/input/store alignment mismatch fails BEFORE any artifact creation
# --------------------------------------------------------------------------- #
def test_store_input_mismatch_fails_before_artifact_creation(tmp_path):
    fx = _fixture(tmp_path)
    # a store whose pair order differs from inputs.cal_pair_ids (still a VALID dev
    # store on its own) must be rejected before any fold artifact is written.
    cal = fx["cal_pairs_id"]
    eps = fx["eps_cal"]
    reversed_pairs = tuple(reversed(cal))
    reversed_eps = eps[::-1]
    bad_store = DevelopmentOutcomeStore(
        combo_calibration_eps=reversed_eps,
        combo_calibration_pair_ids=reversed_pairs,
        access_audit=fx["store"].access_audit,
    )
    with pytest.raises(FoldJobError):
        build_fold_job(
            method="cpa",
            seed=11,
            fold_index=0,
            oof_manifest=fx["manifest"],
            inputs=fx["inputs"],
            outcome_store=bad_store,
            response_artifact=fx["response_artifact"],
            base_fit_role_spec=fx["base_spec"],
            fold_artifact_dir=fx["fold_dir"],
            gene_order=fx["gene_order"],
            raw_data_sha256=_RAW,
        )
    # no fold artifact was written (fail-closed BEFORE creation)
    assert list(Path(fx["fold_dir"]).glob("*.h5ad")) == []


def test_manifest_input_mismatch_fails_closed(tmp_path):
    fx = _fixture(tmp_path)
    # a manifest built for a different split seed disagrees with inputs.seed.
    import dataclasses

    other = OOFFoldManifest.from_folds(
        build_gene_disjoint_folds(
            fx["inputs"].cal_idx_pairs, n_genes=6, n_folds=_N_FOLDS, seed=_SPLIT_SEED + 1
        ),
        pair_ids=fx["cal_pairs_id"],
        n_genes=6,
        n_folds=_N_FOLDS,
        split_seed=_SPLIT_SEED + 1,
    )
    assert isinstance(other, OOFFoldManifest)
    with pytest.raises(FoldJobError):
        build_fold_job(
            method="gears",
            seed=23,
            fold_index=0,
            oof_manifest=other,
            inputs=fx["inputs"],
            outcome_store=fx["store"],
            response_artifact=fx["response_artifact"],
            base_fit_role_spec=fx["base_spec"],
            fold_artifact_dir=fx["fold_dir"],
            gene_order=fx["gene_order"],
            raw_data_sha256=_RAW,
        )
    del dataclasses


# --------------------------------------------------------------------------- #
# write-once: a second identical (method, seed, fold) job fails closed
# --------------------------------------------------------------------------- #
def test_fold_artifact_is_write_once(tmp_path):
    fx = _fixture(tmp_path)
    _build(fx, method="gears", seed=23, fold_index=0)
    with pytest.raises(FoldJobError):
        _build(fx, method="gears", seed=23, fold_index=0)


def test_distinct_jobs_get_distinct_fold_artifacts(tmp_path):
    fx = _fixture(tmp_path)
    a = _build(fx, method="gears", seed=23, fold_index=0)
    b = _build(fx, method="cpa", seed=37, fold_index=1)
    assert a.fit_role_artifact_path != b.fit_role_artifact_path
    assert Path(a.fit_role_artifact_path).is_file()
    assert Path(b.fit_role_artifact_path).is_file()
