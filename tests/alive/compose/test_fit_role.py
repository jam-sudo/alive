# tests/alive/compose/test_fit_role.py
from __future__ import annotations

import os as _os
from pathlib import Path

import numpy as np
import pytest
from scipy import sparse

from alive.compose.fit_role import (
    ComposeFitRoleExtractor,
    FitRoleArtifactError,
    FitRoleArtifactSpec,
    _file_sha256,
    canonical_gene_order_sha256,
    content_manifest_sha256,
    extract_fit_roles,
    generate_fit_role_artifact,
    row_identity_sha256,
    validate_fit_role_artifact,
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


def _gen(tmp_path: Path, name: str = "art.h5ad", **prov) -> FitRoleArtifactSpec:
    extraction = extract_fit_roles(extractor=_extractor())
    p = dict(
        config_sha256="cfg",
        data_card_sha256="dc",
        calibration_gene_set_hash="cg",
        generator_code_sha256="gen",
        writer_environment_sha256="env",
    )
    p.update(prov)
    return generate_fit_role_artifact(extraction=extraction, out_path=str(tmp_path / name), **p)


def test_generate_writes_valid_h5ad_and_spec(tmp_path):
    import anndata as ad

    spec = _gen(tmp_path)
    assert spec.sha256.startswith("sha256:")
    assert spec.n_cells == 6 and spec.n_genes == 3
    assert spec.role_counts == {"control": 1, "singles": 4, "combo_calibration": 1}
    adata = ad.read_h5ad(spec.path)
    assert set(map(str, adata.obs["role"].unique())) <= {"control", "singles", "combo_calibration"}
    assert "source_row_id" in adata.obs
    block = spec.to_payload_block()
    assert block["allowed_obs_roles"] == ["control", "singles", "combo_calibration"]
    assert block["counts_location"] == "X"


def test_generate_is_content_deterministic(tmp_path):
    a = _gen(tmp_path, "a.h5ad")
    b = _gen(tmp_path, "b.h5ad")
    assert a.content_manifest_sha256 == b.content_manifest_sha256  # logical identity stable
    assert a.gene_order_sha256 == b.gene_order_sha256


def test_generate_is_write_once(tmp_path):
    _gen(tmp_path, "once.h5ad")
    with pytest.raises(FitRoleArtifactError):
        _gen(tmp_path, "once.h5ad")  # refuse to overwrite


_CALIB = [("CEBPE", "KLF1")]
_SEALED = [("AAA", "BBB")]


def _validate(spec, approved_root, **over):
    kw = dict(
        spec=spec, approved_root=approved_root, calibration_pair_ids=_CALIB, sealed_pair_ids=_SEALED
    )
    kw.update(over)
    validate_fit_role_artifact(spec.path, **kw)


def test_validate_happy_path(tmp_path):
    spec = _gen(tmp_path)
    _validate(spec, str(tmp_path))  # no raise


def test_validate_rejects_file_sha_mismatch(tmp_path):
    spec = _gen(tmp_path)
    tampered = FitRoleArtifactSpec(**{**spec.__dict__, "sha256": "sha256:" + "0" * 64})
    with pytest.raises(FitRoleArtifactError):
        _validate(tampered, str(tmp_path))


def test_validate_rejects_content_manifest_mismatch(tmp_path):
    spec = _gen(tmp_path)
    tampered = FitRoleArtifactSpec(**{**spec.__dict__, "content_manifest_sha256": "deadbeef"})
    with pytest.raises(FitRoleArtifactError):
        _validate(tampered, str(tmp_path))


def test_validate_rejects_path_outside_approved_root(tmp_path):
    spec = _gen(tmp_path)
    with pytest.raises(FitRoleArtifactError):
        _validate(spec, str(tmp_path / "other_root"))


def test_validate_rejects_symlink(tmp_path):
    spec = _gen(tmp_path)
    link = tmp_path / "link.h5ad"
    _os.symlink(spec.path, link)
    linked = FitRoleArtifactSpec(**{**spec.__dict__, "path": str(link)})
    with pytest.raises(FitRoleArtifactError):
        _validate(linked, str(tmp_path))


def test_validate_rejects_sealed_pair_in_obs(tmp_path):
    # generate an artifact whose sole calibration pair IS a sealed pair, bypassing
    # the extractor, then validate against the real sealed set -> reject.
    ex = _extractor(
        obs_source_row_id=["r0", "r1"],
        obs_perturbation=["control", "AAA_BBB"],
        calibration_pair_ids=[("AAA", "BBB")],
        sealed_pair_ids=[],  # bypass extractor guard to forge the artifact
    )
    extraction = extract_fit_roles(extractor=ex)
    spec = generate_fit_role_artifact(
        extraction=extraction,
        out_path=str(tmp_path / "forged.h5ad"),
        config_sha256="c",
        data_card_sha256="d",
        calibration_gene_set_hash="g",
        generator_code_sha256="x",
        writer_environment_sha256="e",
    )
    with pytest.raises(FitRoleArtifactError):  # validated against the REAL sealed set
        _validate(
            spec,
            str(tmp_path),
            calibration_pair_ids=[("AAA", "BBB")],
            sealed_pair_ids=[("AAA", "BBB")],
        )


def test_extract_stores_combo_token_canonically():
    # A NON-canonical raw combo token (KLF1_CEBPE, since CEBPE < KLF1) must be
    # stored canonically (CEBPE_KLF1), and its identity digests must be
    # order-invariant vs. the already-canonical CEBPE_KLF1 input. Singles and the
    # control token pass through unchanged.
    def _rows_for(combo_token: str):
        ex = _extractor(
            obs_source_row_id=["r0", "r1", "r2", "r3"],
            obs_perturbation=["control", "KLF1", "CEBPE", combo_token],
            calibration_pair_ids=[("CEBPE", "KLF1")],
            sealed_pair_ids=[],
        )
        return extract_fit_roles(extractor=ex)

    noncanon = _rows_for("KLF1_CEBPE")  # raw token reversed vs. byte-canonical order
    canon = _rows_for("CEBPE_KLF1")

    # combo cell (r3) is stored canonically regardless of raw token order
    assert noncanon.rows[3] == ("r3", "combo_calibration", "CEBPE_KLF1")
    assert canon.rows[3] == ("r3", "combo_calibration", "CEBPE_KLF1")
    # control + singles tokens pass through unchanged
    assert noncanon.rows[0] == ("r0", "control", "control")
    assert noncanon.rows[1] == ("r1", "singles", "KLF1")
    assert noncanon.rows[2] == ("r2", "singles", "CEBPE")
    # order-invariant identity: the digests match the canonical-input digests
    assert row_identity_sha256(noncanon.rows) == row_identity_sha256(canon.rows)
    kw = dict(
        schema_version=1,
        var_names=list(noncanon.var_names),
        provenance={"raw_data_sha256": noncanon.raw_data_sha256},
        role_counts=noncanon.role_counts,
    )
    assert content_manifest_sha256(
        X=noncanon.X, rows=noncanon.rows, **kw
    ) == content_manifest_sha256(X=canon.X, rows=canon.rows, **kw)


def test_validate_wraps_malformed_artifact_as_fit_role_error(tmp_path):
    import anndata as ad

    # Forge an artifact whose combo_calibration obs row has a perturbation token
    # WITHOUT the combo separator. On validation, _canonical_pair(...).split -> a
    # single-element unpack would raise a bare ValueError; the guard must surface
    # it as FitRoleArtifactError (fail closed), not ValueError.
    spec = _gen(tmp_path, "malformed.h5ad")
    adata = ad.read_h5ad(spec.path)
    perts = [str(p) for p in adata.obs["perturbation"]]
    # r3 is the combo_calibration cell (CEBPE_KLF1); strip its separator
    perts = [p.replace("_", "") if "_" in p else p for p in perts]
    adata.obs["perturbation"] = perts
    corrupt = tmp_path / "corrupt.h5ad"
    adata.write_h5ad(corrupt)
    corrupt_spec = FitRoleArtifactSpec(
        **{**spec.__dict__, "path": str(corrupt), "sha256": _file_sha256(str(corrupt))}
    )
    with pytest.raises(FitRoleArtifactError):
        _validate(corrupt_spec, str(tmp_path))

    # A malformed artifact missing an obs column also fails closed as
    # FitRoleArtifactError (KeyError -> FitRoleArtifactError), not KeyError.
    adata2 = ad.read_h5ad(spec.path)
    del adata2.obs["source_row_id"]
    missing = tmp_path / "missing_col.h5ad"
    adata2.write_h5ad(missing)
    missing_spec = FitRoleArtifactSpec(
        **{**spec.__dict__, "path": str(missing), "sha256": _file_sha256(str(missing))}
    )
    with pytest.raises(FitRoleArtifactError):
        _validate(missing_spec, str(tmp_path))
