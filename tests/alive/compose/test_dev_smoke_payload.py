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
from types import SimpleNamespace

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


def _build(harness, adata, root: Path, label: str) -> dict:
    """Build one dev-smoke payload under a labelled output path."""
    return harness.build_dev_smoke_payload(
        adata,
        out_dir=str(root / label / "work"),
        artifact_path=str(root / label / "approved" / "fit_role.h5ad"),
        control_token="control",
        combo_sep="_",
        n_hvg=8,
        pca_dim=3,
        seed=11,
        n_sealed=2,
        n_calibration=3,
    )


def test_dev_smoke_payload_is_contract_valid_and_leakage_safe(tmp_path):
    harness = _load_harness()
    adata = _synthetic_adata()
    manifest = _build(harness, adata, tmp_path, "case")

    # 1. the payload round-trips through the frozen contract validator.
    payload = read_payload(str(tmp_path / "case" / "work"))
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


def test_dev_smoke_content_identity_is_path_independent(tmp_path):
    """Equivalent allowed source content has one identity at every output path."""
    harness = _load_harness()
    adata = _synthetic_adata()
    a = _build(harness, adata, tmp_path, "path-a")
    b = _build(harness, adata, tmp_path, "path-b")

    assert a["raw_data_sha256"] == b["raw_data_sha256"]
    assert a["artifact_content_manifest_sha256"] == b["artifact_content_manifest_sha256"]


def test_dev_smoke_allowed_source_mutations_change_content_identity(tmp_path):
    """Counts, source-row IDs, and gene IDs are all bound into source identity."""
    harness = _load_harness()
    original = _synthetic_adata()
    base = _build(harness, original, tmp_path, "base")

    count_mutation = original.copy()
    counts = count_mutation.X.toarray()
    counts[0, 0] += 1
    count_mutation.X = sparse.csr_matrix(counts)

    row_mutation = original.copy()
    row_ids = [str(x) for x in row_mutation.obs_names]
    row_ids[0] = "mutated-source-row-id"
    row_mutation.obs_names = row_ids

    gene_mutation = original.copy()
    gene_ids = [str(x) for x in gene_mutation.var_names]
    gene_ids[0] = "MUTATED_GENE_ID"
    gene_mutation.var_names = gene_ids

    for label, mutated in (
        ("count-mutation", count_mutation),
        ("row-mutation", row_mutation),
        ("gene-mutation", gene_mutation),
    ):
        observed = _build(harness, mutated, tmp_path, label)
        assert observed["raw_data_sha256"] != base["raw_data_sha256"]
        assert (
            observed["artifact_content_manifest_sha256"] != base["artifact_content_manifest_sha256"]
        )


class _ForbiddenRowGuard:
    """Matrix facade that raises if the builder requests any forbidden source row."""

    def __init__(self, matrix: sparse.csr_matrix, forbidden: set[int]):
        self._matrix = matrix
        self._forbidden = set(forbidden)
        self.accessed: set[int] = set()

    def __getitem__(self, key):
        rows = key[0] if isinstance(key, tuple) else key
        selected = np.asarray(np.arange(self._matrix.shape[0])[rows], dtype=np.int64).reshape(-1)
        selected_set = {int(i) for i in selected}
        forbidden = selected_set & self._forbidden
        if forbidden:
            raise AssertionError(f"dev-sealed expression rows were accessed: {sorted(forbidden)}")
        self.accessed.update(selected_set)
        return self._matrix[key]


def test_dev_smoke_never_accesses_selected_sealed_expression_rows(tmp_path):
    """The metadata-selected dev-sealed rows never reach the expression reader."""
    harness = _load_harness()
    source = _synthetic_adata()
    perts = [str(p) for p in source.obs["perturbation"]]
    universe = harness.parse_perturbation_universe(perts, control_token="control", combo_sep="_")
    sealed, _calibration = harness.select_outcome_free_split(
        universe, n_sealed=2, n_calibration=3, seed=11
    )
    sealed_tokens = {universe.token_of_pair[pair] for pair in sealed}
    forbidden = {i for i, token in enumerate(perts) if token in sealed_tokens}
    assert forbidden

    guard = _ForbiddenRowGuard(sparse.csr_matrix(source.X), forbidden)
    guarded_source = SimpleNamespace(
        X=guard,
        layers={},
        obs=source.obs,
        obs_names=source.obs_names,
        var_names=source.var_names,
    )
    manifest = _build(harness, guarded_source, tmp_path, "guarded")

    assert guard.accessed
    assert guard.accessed.isdisjoint(forbidden)
    artifact = ad.read_h5ad(manifest["artifact_path"])
    assert sealed_tokens.isdisjoint(set(artifact.obs["perturbation"].astype(str)))


def test_dev_smoke_sealed_expression_mutation_does_not_change_allowed_source_identity(tmp_path):
    """Changing held-out dev-sealed outcomes cannot influence the fit payload."""
    harness = _load_harness()
    original = _synthetic_adata()
    perts = [str(p) for p in original.obs["perturbation"]]
    universe = harness.parse_perturbation_universe(perts, control_token="control", combo_sep="_")
    sealed, _calibration = harness.select_outcome_free_split(
        universe, n_sealed=2, n_calibration=3, seed=11
    )
    sealed_tokens = {universe.token_of_pair[pair] for pair in sealed}
    sealed_rows = [i for i, token in enumerate(perts) if token in sealed_tokens]
    assert sealed_rows

    mutated = original.copy()
    counts = mutated.X.toarray()
    counts[sealed_rows] += 1000
    mutated.X = sparse.csr_matrix(counts)

    base = _build(harness, original, tmp_path, "sealed-base")
    changed = _build(harness, mutated, tmp_path, "sealed-mutated")
    assert changed["raw_data_sha256"] == base["raw_data_sha256"]
    assert changed["artifact_content_manifest_sha256"] == base["artifact_content_manifest_sha256"]


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


def test_compose_dir_includes_normal_globals_and_lazy_exports():
    """PEP 562 introspection preserves normal module attributes and public API."""
    import alive.compose as compose

    names = set(dir(compose))
    assert {"__name__", "__file__", "__spec__"} <= names
    assert set(compose.__all__) <= names
