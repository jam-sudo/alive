"""Local test for the DEV-POD-SMOKE payload builder (no gears/cpa, no seal).

Exercises ``scripts/compose/build_dev_smoke_payload.py`` on a tiny synthetic
AnnData and asserts the produced fit-role artifact + payload are contract-valid
(``baseline_subprocess.read_payload`` accepts them), that the sealed/calibration
split is disjoint with a recomputed zero-overlap proof, and that no sealed combo
cell is materialised in the artifact.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from alive.compose.baseline_subprocess import read_payload

_REPO = Path(__file__).resolve().parents[3]
_HARNESS = _REPO / "scripts" / "compose" / "build_dev_smoke_payload.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("_dev_smoke_harness", _HARNESS)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the module-level @dataclass can resolve __module__.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _synthetic_adata() -> ad.AnnData:
    rng = np.random.default_rng(0)
    genes = [f"G{i}" for i in range(12)]
    singles = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    combos = ["AAA_BBB", "AAA_CCC", "BBB_CCC", "CCC_DDD", "DDD_EEE", "AAA_EEE"]
    perts: list[str] = ["control"] * 40
    for g in singles:
        perts += [g] * 12
    for c in combos:
        perts += [c] * 10
    x = sparse.csr_matrix(rng.integers(0, 30, size=(len(perts), 12)).astype(np.float64))
    return ad.AnnData(
        X=x,
        obs=pd.DataFrame({"perturbation": perts}, index=[f"c{i}" for i in range(len(perts))]),
        var=pd.DataFrame(index=genes),
    )


def test_dev_smoke_payload_is_contract_valid_and_leakage_safe(tmp_path):
    harness = _load_harness()
    adata = _synthetic_adata()
    manifest = harness.build_dev_smoke_payload(
        adata,
        out_dir=str(tmp_path / "work"),
        artifact_path=str(tmp_path / "approved" / "fit_role.h5ad"),
        control_token="control",
        combo_sep="_",
        n_hvg=8,
        pca_dim=3,
        seed=11,
        n_sealed=2,
        n_calibration=3,
    )

    # 1. the payload round-trips through the frozen contract validator.
    payload = read_payload(str(tmp_path / "work"))
    assert payload["response_dim"] == 3
    assert set(payload["allowed_roles"]) == {"singles", "combo_calibration"}
    assert len(payload["pair_ids"]) == 2
    assert len(payload["calibration_pair_ids"]) == 3

    # 2. sealed request roster is disjoint from the calibration (fit) roster.
    sealed = {tuple(p) for p in payload["pair_ids"]}
    calib = {tuple(p) for p in payload["calibration_pair_ids"]}
    assert sealed.isdisjoint(calib)
    assert manifest["sealed_pair_overlap_count"] == 0

    # 3. the artifact materialises NO sealed combo cell (control retained).
    art = ad.read_h5ad(manifest["artifact_path"])
    sealed_tokens = {f"{a}_{b}" for a, b in sealed}
    assert sealed_tokens.isdisjoint(set(art.obs["perturbation"].astype(str)))
    assert set(art.obs["role"].astype(str)) <= {"control", "singles", "combo_calibration"}
    assert manifest["role_counts"]["control"] >= 1


def test_dev_smoke_split_is_outcome_free_and_deterministic(tmp_path):
    harness = _load_harness()
    adata = _synthetic_adata()
    perts = [str(p) for p in adata.obs["perturbation"]]
    universe = harness.parse_perturbation_universe(perts, control_token="control", combo_sep="_")
    a = harness.select_outcome_free_split(universe, n_sealed=2, n_calibration=3, seed=11)
    b = harness.select_outcome_free_split(universe, n_sealed=2, n_calibration=3, seed=11)
    assert a == b  # deterministic under a fixed seed (no outcome consulted)
    sealed, calib = a
    assert set(sealed).isdisjoint(set(calib))


def test_dev_smoke_rejects_multi_spelling_combo(tmp_path):
    harness = _load_harness()
    # same biological combo under both orderings -> fail closed (no silent under-sample).
    perts = ["AAA_BBB", "BBB_AAA"]
    with pytest.raises(ValueError, match="multiple raw spellings"):
        harness.parse_perturbation_universe(perts, control_token="control", combo_sep="_")


def test_dev_smoke_rejects_non_integer_counts(tmp_path):
    harness = _load_harness()
    adata = _synthetic_adata()
    adata.X = adata.X.astype(np.float64)
    adata.X.data = adata.X.data + 0.5  # non-integer → not raw counts
    with pytest.raises(ValueError, match="integer-valued"):
        harness.build_dev_smoke_payload(
            adata,
            out_dir=str(tmp_path / "work"),
            artifact_path=str(tmp_path / "approved" / "fit_role.h5ad"),
            control_token="control",
            combo_sep="_",
            n_hvg=8,
            pca_dim=3,
            seed=11,
            n_sealed=2,
            n_calibration=3,
        )
