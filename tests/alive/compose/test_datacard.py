"""Tests for alive.compose.datacard — written FIRST per TDD protocol (Task 2a-10).

A validated Norman data-card builder + composite run identity + provenance capture.

All fixtures are tiny synthetic AnnData written to a temp ``.h5ad``; NO real
Norman download (activation blocked). The data-card derives schema and counts
DIRECTLY from the AnnData/labels and refuses caller-supplied counts that
contradict the derived values.
"""

from __future__ import annotations

import json
from pathlib import Path

import anndata
import numpy as np
import pytest

from alive.compose.datacard import (
    DataCardError,
    build_data_card,
    capture_compose_provenance,
    compute_compose_run_id,
)
from alive.provenance import RunLedger, sha256_file, sha256_json

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PERT_COL = "perturbation"
_LABELS = (
    ["ctrl"] * 4  # 4 control cells
    + ["A"] * 3  # single A
    + ["B"] * 3  # single B
    + ["C"] * 2  # single C
    + ["A+B"] * 2  # double A+B
    + ["A+C"] * 1  # double A+C
)
# counts: n_cells=15, n_control=4, singles A,B,C, doubles (A,B),(A,C)


def _toy_adata(n_genes: int = 5) -> anndata.AnnData:
    """Build a tiny synthetic Norman-like AnnData with a perturbation obs column."""
    labels = np.array(_LABELS, dtype=object)
    rng = np.random.default_rng(0)
    x = rng.normal(size=(labels.size, n_genes)).astype(np.float32)
    obs = {
        _PERT_COL: labels,
        "n_counts": rng.integers(100, 200, size=labels.size),
    }
    var = {"gene_name": np.array([f"g{i}" for i in range(n_genes)], dtype=object)}
    import pandas as pd

    return anndata.AnnData(
        X=x,
        obs=pd.DataFrame(obs, index=[f"cell{i}" for i in range(labels.size)]),
        var=pd.DataFrame(var, index=[f"ENSG{i}" for i in range(n_genes)]),
    )


@pytest.fixture
def processed_h5ad(tmp_path: Path) -> Path:
    """Write the toy processed AnnData to disk and return its path."""
    path = tmp_path / "norman_processed.h5ad"
    _toy_adata().write_h5ad(path)
    return path


@pytest.fixture
def raw_asset(tmp_path: Path) -> Path:
    """A small raw asset file with deterministic content."""
    path = tmp_path / "norman_raw.tar.gz"
    path.write_bytes(b"raw-norman-bytes-deterministic")
    return path


_SOURCE_KW = dict(
    source_uri="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE133344",
    source_doi="10.1016/j.cell.2019.07.014",
    license="CC-BY-4.0",
    cell_line="K562",
    modality="CRISPRa-Perturb-seq",
    processing_version="compose-norman-v1",
    perturbation_col=_PERT_COL,
    control_token="ctrl",
    combo_sep="+",
)


# ---------------------------------------------------------------------------
# Derived counts and schema
# ---------------------------------------------------------------------------


def test_counts_derived_from_labels(processed_h5ad: Path):
    card = build_data_card(processed_h5ad=processed_h5ad, declared_source_digest="d", **_SOURCE_KW)
    assert card["counts"]["n_cells"] == 15
    assert card["counts"]["n_genes"] == 5
    assert card["counts"]["n_control"] == 4
    assert card["counts"]["n_singles"] == 3  # A, B, C
    assert card["counts"]["n_doubles"] == 2  # (A,B), (A,C)


def test_schema_derived_from_anndata(processed_h5ad: Path):
    card = build_data_card(processed_h5ad=processed_h5ad, declared_source_digest="d", **_SOURCE_KW)
    assert _PERT_COL in card["schema"]["obs_columns"]
    assert "n_counts" in card["schema"]["obs_columns"]
    assert "gene_name" in card["schema"]["var_columns"]
    # schema is sorted/deterministic
    assert card["schema"]["obs_columns"] == sorted(card["schema"]["obs_columns"])


def test_source_metadata_recorded(processed_h5ad: Path):
    card = build_data_card(processed_h5ad=processed_h5ad, declared_source_digest="d", **_SOURCE_KW)
    assert card["source"]["uri"] == _SOURCE_KW["source_uri"]
    assert card["source"]["doi"] == _SOURCE_KW["source_doi"]
    assert card["license"] == "CC-BY-4.0"
    assert card["cell_line"] == "K562"
    assert card["modality"] == "CRISPRa-Perturb-seq"
    assert card["processing_version"] == "compose-norman-v1"


def test_processed_sha256_recorded(processed_h5ad: Path):
    card = build_data_card(processed_h5ad=processed_h5ad, declared_source_digest="d", **_SOURCE_KW)
    assert card["processed_sha256"] == sha256_file(processed_h5ad)


# ---------------------------------------------------------------------------
# Caller-supplied counts cannot overwrite derived; mismatch RAISES
# ---------------------------------------------------------------------------


def test_caller_counts_matching_is_accepted(processed_h5ad: Path):
    card = build_data_card(
        processed_h5ad=processed_h5ad,
        declared_source_digest="d",
        declared_counts={"n_cells": 15, "n_control": 4, "n_singles": 3, "n_doubles": 2},
        **_SOURCE_KW,
    )
    # derived values are authoritative and unchanged
    assert card["counts"]["n_cells"] == 15
    assert card["counts"]["n_singles"] == 3


@pytest.mark.parametrize(
    "bad",
    [
        {"n_cells": 99},
        {"n_control": 0},
        {"n_singles": 2},
        {"n_doubles": 5},
    ],
)
def test_caller_counts_mismatch_raises(processed_h5ad: Path, bad: dict):
    with pytest.raises(DataCardError):
        build_data_card(
            processed_h5ad=processed_h5ad,
            declared_source_digest="d",
            declared_counts=bad,
            **_SOURCE_KW,
        )


def test_caller_counts_cannot_overwrite_derived(processed_h5ad: Path):
    # even an attempt to declare a wrong value never silently wins
    with pytest.raises(DataCardError):
        build_data_card(
            processed_h5ad=processed_h5ad,
            declared_source_digest="d",
            declared_counts={"n_cells": 14},  # off by one
            **_SOURCE_KW,
        )


# ---------------------------------------------------------------------------
# Raw vs source digest branch
# ---------------------------------------------------------------------------


def test_raw_present_uses_raw_sha(processed_h5ad: Path, raw_asset: Path):
    card = build_data_card(processed_h5ad=processed_h5ad, raw_asset=raw_asset, **_SOURCE_KW)
    assert card["raw_or_source"]["kind"] == "raw_sha256"
    assert card["raw_or_source"]["digest"] == sha256_file(raw_asset)


def test_raw_absent_uses_declared_source_digest(processed_h5ad: Path):
    card = build_data_card(
        processed_h5ad=processed_h5ad,
        declared_source_digest="immutable-geo-accession-digest-v1",
        **_SOURCE_KW,
    )
    assert card["raw_or_source"]["kind"] == "declared_source_digest"
    assert card["raw_or_source"]["digest"] == "immutable-geo-accession-digest-v1"


def test_raw_absent_without_declared_source_raises(processed_h5ad: Path):
    with pytest.raises(DataCardError):
        build_data_card(processed_h5ad=processed_h5ad, **_SOURCE_KW)


def test_raw_and_declared_source_both_given_raises(processed_h5ad: Path, raw_asset: Path):
    with pytest.raises(DataCardError):
        build_data_card(
            processed_h5ad=processed_h5ad,
            raw_asset=raw_asset,
            declared_source_digest="x",
            **_SOURCE_KW,
        )


# ---------------------------------------------------------------------------
# Outcome-independent exclusions + manifest hash
# ---------------------------------------------------------------------------


def test_exclusions_manifest_hashed(processed_h5ad: Path):
    exclusions = [
        {"unit": "cell", "id": "cell0", "reason": "low_n_counts"},
        {"unit": "gene", "id": "ENSG3", "reason": "no_sequence_feature"},
    ]
    card = build_data_card(
        processed_h5ad=processed_h5ad,
        raw_asset=None,
        declared_source_digest="d",
        exclusions=exclusions,
        **_SOURCE_KW,
    )
    assert card["exclusions"] == exclusions
    assert card["exclusions_manifest_sha256"] == sha256_json(exclusions)


def test_exclusions_default_empty(processed_h5ad: Path):
    card = build_data_card(
        processed_h5ad=processed_h5ad,
        declared_source_digest="d",
        **_SOURCE_KW,
    )
    assert card["exclusions"] == []
    assert card["exclusions_manifest_sha256"] == sha256_json([])


# ---------------------------------------------------------------------------
# Composite run_id: deterministic + sensitive to every input digest
# ---------------------------------------------------------------------------


def _base_digests() -> dict:
    return dict(
        config_digest="cfg",
        data_card={"k": "v"},
        raw_or_source_digest="raw",
        sequence_mapping_digest="seq",
    )


def test_run_id_deterministic():
    a = compute_compose_run_id(**_base_digests())
    b = compute_compose_run_id(**_base_digests())
    assert a == b
    assert isinstance(a, str) and len(a) == 16


def test_run_id_accepts_card_dict_or_digest():
    d = _base_digests()
    by_dict = compute_compose_run_id(**d)
    by_digest = compute_compose_run_id(
        config_digest="cfg",
        data_card_digest=sha256_json({"k": "v"}),
        raw_or_source_digest="raw",
        sequence_mapping_digest="seq",
    )
    assert by_dict == by_digest


@pytest.mark.parametrize(
    "override",
    [
        {"config_digest": "cfg2"},
        {"data_card": {"k": "v2"}},
        {"raw_or_source_digest": "raw2"},
        {"sequence_mapping_digest": "seq2"},
    ],
)
def test_run_id_changes_when_any_input_changes(override: dict):
    base = compute_compose_run_id(**_base_digests())
    changed_kwargs = {**_base_digests(), **override}
    assert compute_compose_run_id(**changed_kwargs) != base


def test_run_id_requires_card_or_digest():
    with pytest.raises(DataCardError):
        compute_compose_run_id(
            config_digest="cfg",
            raw_or_source_digest="raw",
            sequence_mapping_digest="seq",
        )


def test_run_id_rejects_both_card_and_digest():
    with pytest.raises(DataCardError):
        compute_compose_run_id(
            config_digest="cfg",
            data_card={"k": "v"},
            data_card_digest="x",
            raw_or_source_digest="raw",
            sequence_mapping_digest="seq",
        )


# ---------------------------------------------------------------------------
# Provenance capture via RunLedger
# ---------------------------------------------------------------------------


def test_capture_provenance_builds_ledger(processed_h5ad: Path, tmp_path: Path):
    lockfile = tmp_path / "uv.lock"
    lockfile.write_bytes(b"lock-bytes")
    card = build_data_card(processed_h5ad=processed_h5ad, declared_source_digest="d", **_SOURCE_KW)
    run_id = compute_compose_run_id(
        config_digest="cfg", data_card=card, raw_or_source_digest="d", sequence_mapping_digest="seq"
    )
    ledger = capture_compose_provenance(
        run_id=run_id,
        config_digest="cfg",
        data_card=card,
        processed_h5ad=processed_h5ad,
        sequence_mapping_digest="seq",
        registered_seeds=(0, 1, 2),
        lockfile_path=lockfile,
        device="cpu",
        precision="float32",
        repo_dir=tmp_path,  # not a git repo -> UNKNOWN, no crash
    )
    assert isinstance(ledger, RunLedger)
    d = ledger.to_dict()
    assert d["run_id"] == run_id
    assert d["environment"]["registered_seeds"] == [0, 1, 2]
    assert d["environment"]["lockfile_sha256"] == sha256_file(lockfile)
    # the data card + processed file + device/precision are all recorded artifacts
    names = {a["name"] for a in d["artifacts"]}
    assert {"data_card", "processed_h5ad", "device_precision"} <= names
    assert ledger.artifact_sha("processed_h5ad") == sha256_file(processed_h5ad)
    assert ledger.artifact_sha("data_card") == sha256_json(card)


def test_capture_provenance_round_trips(processed_h5ad: Path, tmp_path: Path):
    lockfile = tmp_path / "uv.lock"
    lockfile.write_bytes(b"lock-bytes")
    card = build_data_card(processed_h5ad=processed_h5ad, declared_source_digest="d", **_SOURCE_KW)
    ledger = capture_compose_provenance(
        run_id="rid",
        config_digest="cfg",
        data_card=card,
        processed_h5ad=processed_h5ad,
        sequence_mapping_digest="seq",
        registered_seeds=(7,),
        lockfile_path=lockfile,
        device="cuda",
        precision="bf16",
        repo_dir=tmp_path,
    )
    out = tmp_path / "ledger.json"
    ledger.write(out)
    assert RunLedger.read(out) == ledger
    # device/precision digest is reproducible
    payload = json.loads(out.read_text())
    assert payload["run_id"] == "rid"
