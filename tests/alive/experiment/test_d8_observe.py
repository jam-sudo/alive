"""Tests for D8 observation arithmetic and the sealed-store boundary."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest

from alive.data.manifest import SplitManifest
from alive.data.outcome_store import ReplogleOutcomeStore, SealingError
from alive.data.replogle import DatasetSchema, ReplogleIndex

_PATH = Path(__file__).resolve().parents[3] / "scripts" / "cartographer" / "d8_observe.py"
_SPEC = importlib.util.spec_from_file_location("d8_observe", _PATH)
do = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(do)


def test_log_cp10k_rejects_invalid_counts():
    with pytest.raises(ValueError):
        do.log_cp10k(np.array([[1.0, -1.0]]), [0])
    with pytest.raises(ValueError):
        do.log_cp10k(np.array([[0.0, 0.0]]), [0])


def test_observed_change_is_target_mean_minus_batch_matched_reference():
    cells = np.array([[3.0, 1.0], [1.0, 1.0]])  # cp10k col0: 7500, 5000
    ref_scaled = np.array([[1.0], [2.0]])
    got, fb = do.observed_change(cells, np.array([1, 2]), ref_scaled, np.array([1, 2]), [0])
    want = np.mean(np.log1p([7500.0, 5000.0])) - 1.5
    assert np.allclose(got, [want]) and fb == []


def _store(tmp_path, sealed):
    X = np.array([[1.0, 2.0], [3.0, 1.0], [2.0, 2.0], [5.0, 1.0]])
    obs = pd.DataFrame(
        {"gene": ["A", "B", "non-targeting", "B"]}, index=[f"c{i}" for i in range(4)]
    )
    adata = ad.AnnData(X=X, obs=obs, var=pd.DataFrame(index=["g1", "g2"]))
    index = ReplogleIndex(
        schema=DatasetSchema(perturbation_key="gene", control_value="non-targeting"),
        gene_ids=("g1", "g2"),
        n_cells=4,
        n_genes=2,
        control_indices=np.array([2]),
        perturbation_indices={"A": np.array([0]), "B": np.array([1, 3])},
        eligible_perturbations=("A", "B"),
        exclusions={},
    )
    manifest = SplitManifest(
        seed=1,
        fractions={
            "base_train": 0.0,
            "method_development": 0.5,
            "conformal_calibration": 0.0,
            "sealed_evaluation": 0.5,
        },
        assignments={
            "base_train": (),
            "method_development": ("A",),
            "conformal_calibration": (),
            "sealed_evaluation": (sealed,),
        },
        exclusions={},
        counts={
            "base_train": 0,
            "method_development": 1,
            "conformal_calibration": 0,
            "sealed_evaluation": 1,
            "excluded": 0,
            "eligible_total": 2,
        },
    )
    return ReplogleOutcomeStore(index, adata, manifest, audit_path=tmp_path / "audit.jsonl")


def test_metadata_index_store_blocks_sealed_role_and_allows_development(tmp_path):
    store = _store(tmp_path, "B")
    assert store.read_unsealed(["A"])["A"].cells.shape == (1, 2)
    with pytest.raises(SealingError):
        store.read_unsealed(["B"])
    assert store.sealed_access_count == 0


def test_verify_freeze_rejects_changed_files(tmp_path):
    spec = importlib.util.spec_from_file_location("d8_evaluate", _PATH.parent / "d8_evaluate.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    f = tmp_path / "method.json"
    f.write_text("{}")
    record = {"files": {"method.json": ev.sha256(f)}}
    ev.verify_freeze(record, tmp_path)
    f.write_text('{"changed": 1}')
    with pytest.raises(ValueError, match="freeze violation"):
        ev.verify_freeze(record, tmp_path)


def test_sealed_role_opens_once_per_run_id(tmp_path):
    store = _store(tmp_path, "B")
    assert store.evaluate_sealed_once("CART-K562-D8-v1", ["B"])["B"].cells.shape == (2, 2)
    with pytest.raises(SealingError):
        store.evaluate_sealed_once("CART-K562-D8-v1", ["B"])


def test_v2_audit_guard_refuses_any_prior_record(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "d8_evaluate_v2", _PATH.parent / "d8_evaluate_v2.py"
    )
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    audit = tmp_path / "seal-audit.jsonl"
    assert ev.audit_is_empty(audit)
    audit.write_text("")
    assert ev.audit_is_empty(audit)
    audit.write_text('{"run_id": "CART-K562-D8-v1"}\n')
    assert not ev.audit_is_empty(audit)
