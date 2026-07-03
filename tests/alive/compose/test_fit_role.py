# tests/alive/compose/test_fit_role.py
from __future__ import annotations

import numpy as np
import pytest
from scipy import sparse

from alive.compose.fit_role import (
    ComposeFitRoleExtractor,
    FitRoleArtifactError,
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
    # 7 rows. Role is DERIVED from the perturbation token (no obs_role input):
    #   r0 control; r1 KLF1, r2 CEBPE -> singles; r3 CEBPE_KLF1 -> calibration combo;
    #   r4 AAA, r5 BBB -> singles, RETAINED even though (AAA,BBB) is a sealed pair
    #     (double-unseen means both singles ARE seen and needed);
    #   r6 AAA_BBB -> sealed double-unseen COMBO cell, EXCLUDED and never read.
    obs_src = [f"r{i}" for i in range(7)]
    obs_pert = ["control", "KLF1", "CEBPE", "CEBPE_KLF1", "AAA", "BBB", "AAA_BBB"]
    var_names = ["G1", "G2", "G3"]
    full = sparse.csr_matrix(np.arange(1, 22, dtype=np.float64).reshape(7, 3))
    sealed_rows = {6}  # only the AAA_BBB combo cell is sealed

    def row_reader(idx: list[int]) -> sparse.csr_matrix:
        if any(i in sealed_rows for i in idx):
            raise AssertionError(f"sealed row read attempted: {sorted(set(idx) & sealed_rows)}")
        return full[idx]

    kw = dict(
        obs_source_row_id=obs_src,
        obs_perturbation=obs_pert,
        var_names=var_names,
        calibration_pair_ids=[("CEBPE", "KLF1")],
        sealed_pair_ids=[("AAA", "BBB")],
        control_token="control",
        raw_data_sha256="raw",
        pair_manifest_sha256="pm",
        eligibility_hash="elig",
        row_reader=row_reader,
    )
    kw.update(overrides)
    return ComposeFitRoleExtractor(**kw)


def test_extract_retains_all_singles_and_excludes_only_sealed_combo():
    ex = _extractor()
    # singles AAA,BBB (r4,r5) are retained though (AAA,BBB) is sealed; only the
    # sealed COMBO cell r6 is excluded and never read (row_reader raises if it is).
    assert ex.select_row_ids() == [0, 1, 2, 3, 4, 5]
    extraction = extract_fit_roles(extractor=ex)
    assert extraction.X.shape == (6, 3)
    assert extraction.role_counts == {"control": 1, "singles": 4, "combo_calibration": 1}
    assert extraction.rows[4] == ("r4", "singles", "AAA")
    assert extraction.rows[3] == ("r3", "combo_calibration", "CEBPE_KLF1")


def test_extract_aborts_on_unregistered_combo_pair():
    # r6 combo pair (XXX,YYY) is neither a calibration nor a sealed pair -> abort
    ex = _extractor(
        obs_perturbation=["control", "KLF1", "CEBPE", "CEBPE_KLF1", "AAA", "BBB", "XXX_YYY"]
    )
    with pytest.raises(FitRoleArtifactError):
        ex.select_row_ids()


def test_extract_aborts_on_pair_in_both_calibration_and_sealed():
    # (AAA,BBB) declared in BOTH sets -> ambiguous -> abort
    ex = _extractor(calibration_pair_ids=[("CEBPE", "KLF1"), ("AAA", "BBB")])
    with pytest.raises(FitRoleArtifactError):
        ex.select_row_ids()
