# tests/alive/compose/test_fit_role.py
from __future__ import annotations

import numpy as np
import pytest
from scipy import sparse

from alive.compose.fit_role import (
    ComposeFitRoleExtractor,
    FitRoleArtifactError,
    FitRoleExtraction,
    canonical_gene_order_sha256,
    content_manifest_sha256,
    extract_fit_roles,
    row_identity_sha256,
)


def _csr(rows: list[list[float]]) -> sparse.csr_matrix:
    return sparse.csr_matrix(np.asarray(rows, dtype=np.float64))


def test_gene_order_digest_is_order_sensitive_and_rejects_bad_ids():
    a = canonical_gene_order_sha256(["G1", "G2", "G3"])
    assert a == canonical_gene_order_sha256(["G1", "G2", "G3"])  # deterministic
    assert a != canonical_gene_order_sha256(["G2", "G1", "G3"])  # order matters
    with pytest.raises(FitRoleArtifactError):
        canonical_gene_order_sha256(["G1", "G1"])  # duplicate
    with pytest.raises(FitRoleArtifactError):
        canonical_gene_order_sha256(["G1", ""])  # empty


def test_content_manifest_is_invariant_to_csr_storage_layout():
    # Same logical matrix, two different CSR internal layouts (unsorted indices,
    # explicit zero / duplicate) must hash identically.
    dense = [[0.0, 2.0, 0.0], [1.0, 0.0, 3.0]]
    clean = _csr(dense)
    messy = sparse.csr_matrix(([2.0, 3.0, 1.0], ([0, 1, 1], [1, 2, 0])), shape=(2, 3))
    rows = [("r0", "control", "control"), ("r1", "singles", "KLF1")]
    prov = {"raw_data_sha256": "x"}
    counts = {"control": 1, "singles": 1, "combo_calibration": 0}
    kw = dict(
        schema_version=1,
        var_names=["G1", "G2", "G3"],
        rows=rows,
        provenance=prov,
        role_counts=counts,
    )
    assert content_manifest_sha256(X=clean, **kw) == content_manifest_sha256(X=messy, **kw)


def test_content_manifest_changes_when_logical_content_changes():
    rows = [("r0", "control", "control")]
    kw = dict(
        schema_version=1,
        var_names=["G1", "G2"],
        rows=rows,
        provenance={"raw_data_sha256": "x"},
        role_counts={"control": 1, "singles": 0, "combo_calibration": 0},
    )
    base = content_manifest_sha256(X=_csr([[1.0, 2.0]]), **kw)
    assert base != content_manifest_sha256(X=_csr([[1.0, 9.0]]), **kw)  # data changed
    assert base != content_manifest_sha256(
        X=_csr([[1.0, 2.0]]), **{**kw, "var_names": ["G2", "G1"]}
    )


def test_row_identity_digest_is_row_order_sensitive():
    a = row_identity_sha256([("r0", "control", "control"), ("r1", "singles", "KLF1")])
    b = row_identity_sha256([("r1", "singles", "KLF1"), ("r0", "control", "control")])
    assert a != b


def _extractor(**overrides):
    # 6 rows: 0 control, 1-2 singles, 3 combo_calibration, 4-5 sealed (double-unseen)
    obs_role = ["control", "singles", "singles", "combo_calibration", "singles", "singles"]
    obs_src = [f"r{i}" for i in range(6)]
    obs_pert = ["control", "KLF1", "CEBPE", "CEBPE_KLF1", "AAA", "BBB"]
    var_names = ["G1", "G2", "G3"]
    full = sparse.csr_matrix(np.arange(1, 19, dtype=np.float64).reshape(6, 3))
    sealed_rows = {4, 5}

    def row_reader(idx: list[int]) -> sparse.csr_matrix:
        if any(i in sealed_rows for i in idx):
            raise AssertionError(f"sealed row read attempted: {sorted(set(idx) & sealed_rows)}")
        return full[idx]

    kw = dict(
        obs_role=obs_role,
        obs_source_row_id=obs_src,
        obs_perturbation=obs_pert,
        var_names=var_names,
        calibration_pair_ids=[("CEBPE", "KLF1")],
        sealed_pair_ids=[("AAA", "BBB")],
        raw_data_sha256="raw",
        pair_manifest_sha256="pm",
        eligibility_hash="elig",
        row_reader=row_reader,
    )
    kw.update(overrides)
    return ComposeFitRoleExtractor(**kw)


def test_extract_selects_only_allowed_rows_and_never_reads_sealed():
    ex = _extractor()
    assert ex.select_row_ids() == [0, 1, 2, 3]  # sealed rows 4,5 excluded
    extraction = extract_fit_roles(extractor=ex)  # row_reader raises if sealed touched
    assert isinstance(extraction, FitRoleExtraction)
    assert extraction.X.shape == (4, 3)
    assert extraction.role_counts == {"control": 1, "singles": 2, "combo_calibration": 1}
    assert extraction.rows[3] == ("r3", "combo_calibration", "CEBPE_KLF1")


def test_extract_rejects_combo_calibration_pair_not_in_calibration_set():
    # r3 relabeled to a pair that is NOT a registered calibration pair -> abort
    ex = _extractor(obs_perturbation=["control", "KLF1", "CEBPE", "AAA_BBB", "AAA", "BBB"])
    with pytest.raises(FitRoleArtifactError):
        ex.select_row_ids()


def test_extract_rejects_unknown_role_before_reading_x():
    ex = _extractor(
        obs_role=["control", "singles", "singles", "sealed_double_unseen", "singles", "singles"]
    )
    with pytest.raises(FitRoleArtifactError):
        ex.select_row_ids()
