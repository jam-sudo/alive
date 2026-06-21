"""Tests for src/alive/data/replogle.py — sparse Replogle index with schema validation.

All tests use small synthetic AnnData fixtures built with scipy.sparse; the real .h5ad
is NOT required locally.

TDD order: tests are written first; the implementation must pass all of them.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import anndata
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from alive.data.replogle import DatasetSchema, ReplogleIndex, SchemaError, build_index

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

PERT_KEY = "target"
CTRL_VAL = "non-targeting"
GENE_IDS = ["geneA", "geneB", "geneC", "geneD", "geneE"]
N_GENES = len(GENE_IDS)


def _make_adata(
    *,
    n_ctrl: int = 80,
    pert_cells: dict[str, int] | None = None,
    gene_ids: list[str] | None = None,
    pert_key: str = PERT_KEY,
    ctrl_val: str = CTRL_VAL,
    data_value: float = 1.0,
    X_override: sp.spmatrix | np.ndarray | None = None,
    add_nan_label: bool = False,
    add_empty_label: bool = False,
) -> anndata.AnnData:
    """Build a minimal synthetic AnnData for testing."""
    if pert_cells is None:
        pert_cells = {"geneA": 100, "geneB": 30}  # geneB < 64 cells
    if gene_ids is None:
        gene_ids = GENE_IDS

    n_g = len(gene_ids)
    labels: list[str] = [ctrl_val] * n_ctrl
    for label, n in pert_cells.items():
        labels.extend([label] * n)
    if add_nan_label:
        labels.append(float("nan"))  # type: ignore[arg-type]
    if add_empty_label:
        labels.append("")

    n_cells = len(labels)

    if X_override is not None:
        X = X_override
    else:
        X = sp.random(n_cells, n_g, density=0.3, format="csr", dtype=np.float32)
        X.data[:] = data_value

    obs = pd.DataFrame({pert_key: labels}, index=[f"cell{i}" for i in range(n_cells)])
    var = pd.DataFrame(index=gene_ids)
    return anndata.AnnData(X=X, obs=obs, var=var)


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_basic_index_fields(self) -> None:
        adata = _make_adata(n_ctrl=80, pert_cells={"geneA": 100, "geneB": 30})
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        idx = build_index(adata, schema, min_cells=64)

        assert idx.n_genes == N_GENES
        assert idx.n_cells == 210  # 80 ctrl + 100 geneA + 30 geneB
        assert tuple(idx.gene_ids) == tuple(GENE_IDS)
        assert idx.schema is schema

    def test_control_indices(self) -> None:
        adata = _make_adata(n_ctrl=80, pert_cells={"geneA": 100})
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        idx = build_index(adata, schema, min_cells=10)

        assert len(idx.control_indices) == 80
        # Control cells are first 80 rows in our fixture
        np.testing.assert_array_equal(idx.control_indices, np.arange(80))

    def test_perturbation_indices(self) -> None:
        adata = _make_adata(n_ctrl=80, pert_cells={"geneA": 100, "geneB": 30})
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        idx = build_index(adata, schema, min_cells=10)

        # geneA occupies rows 80..179, geneB rows 180..209
        np.testing.assert_array_equal(idx.perturbation_indices["geneA"], np.arange(80, 180))
        np.testing.assert_array_equal(idx.perturbation_indices["geneB"], np.arange(180, 210))
        # control must NOT appear in perturbation_indices
        assert CTRL_VAL not in idx.perturbation_indices

    def test_cell_indices_method(self) -> None:
        adata = _make_adata(n_ctrl=80, pert_cells={"geneA": 100, "geneB": 30})
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        idx = build_index(adata, schema, min_cells=10)

        result = idx.cell_indices("geneA")
        np.testing.assert_array_equal(result, np.arange(80, 180))

    def test_cell_indices_unknown_raises(self) -> None:
        adata = _make_adata(n_ctrl=80, pert_cells={"geneA": 100})
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        idx = build_index(adata, schema, min_cells=10)

        with pytest.raises(SchemaError, match="unknown"):
            idx.cell_indices("totally_unknown_gene")

    def test_is_eligible(self) -> None:
        adata = _make_adata(n_ctrl=80, pert_cells={"geneA": 100, "geneB": 30})
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        idx = build_index(adata, schema, min_cells=64)

        assert idx.is_eligible("geneA") is True
        assert idx.is_eligible("geneB") is False


# ---------------------------------------------------------------------------
# 2. Eligibility
# ---------------------------------------------------------------------------


class TestEligibility:
    def test_min_cells_exclusion(self) -> None:
        adata = _make_adata(n_ctrl=80, pert_cells={"geneA": 100, "geneB": 30})
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        idx = build_index(adata, schema, min_cells=64)

        assert "geneA" in idx.eligible_perturbations
        assert "geneB" not in idx.eligible_perturbations
        assert "geneB" in idx.exclusions
        assert "30" in idx.exclusions["geneB"] or "64" in idx.exclusions["geneB"]

    def test_available_feature_ids_restricts_eligibility(self) -> None:
        adata = _make_adata(n_ctrl=80, pert_cells={"geneA": 100, "geneC": 100})
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        idx = build_index(
            adata,
            schema,
            min_cells=10,
            available_feature_ids={"geneA"},  # geneC not in set
        )

        assert "geneA" in idx.eligible_perturbations
        assert "geneC" not in idx.eligible_perturbations
        assert "geneC" in idx.exclusions
        assert "external feature" in idx.exclusions["geneC"].lower()

    def test_combined_exclusion_cell_count_wins(self) -> None:
        """A pert that fails BOTH cell count and feature availability → recorded with some reason."""
        adata = _make_adata(n_ctrl=80, pert_cells={"geneA": 100, "geneB": 10})
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        idx = build_index(adata, schema, min_cells=64, available_feature_ids={"geneA"})

        # geneB fails both; must be in exclusions
        assert "geneB" in idx.exclusions

    def test_eligible_sorted(self) -> None:
        adata = _make_adata(n_ctrl=80, pert_cells={"geneC": 100, "geneA": 100})
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        idx = build_index(adata, schema, min_cells=10)

        # eligible_perturbations must be a sorted tuple
        assert list(idx.eligible_perturbations) == sorted(idx.eligible_perturbations)


# ---------------------------------------------------------------------------
# 3. Schema failures (each must raise SchemaError)
# ---------------------------------------------------------------------------


class TestSchemaFailures:
    def test_missing_perturbation_key(self) -> None:
        adata = _make_adata()
        schema = DatasetSchema(perturbation_key="nonexistent_col", control_value=CTRL_VAL)
        with pytest.raises(SchemaError, match="nonexistent_col"):
            build_index(adata, schema, min_cells=10)

    def test_nan_perturbation_label(self) -> None:
        adata = _make_adata(add_nan_label=True)
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        with pytest.raises(SchemaError, match="[Nn]aN|empty|null"):
            build_index(adata, schema, min_cells=10)

    def test_empty_perturbation_label(self) -> None:
        adata = _make_adata(add_empty_label=True)
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        with pytest.raises(SchemaError, match="empty|blank|label"):
            build_index(adata, schema, min_cells=10)

    def test_no_control_cells(self) -> None:
        adata = _make_adata(n_ctrl=0, pert_cells={"geneA": 100})
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        with pytest.raises(SchemaError, match="[Cc]ontrol"):
            build_index(adata, schema, min_cells=10)

    def test_duplicate_gene_ids(self) -> None:
        adata = _make_adata(gene_ids=["geneA", "geneA", "geneB"])
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        with pytest.raises(SchemaError, match="[Dd]uplicate|unique"):
            build_index(adata, schema, min_cells=10)

    def test_empty_gene_id(self) -> None:
        adata = _make_adata(gene_ids=["geneA", "", "geneB"])
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        with pytest.raises(SchemaError, match="[Ee]mpty|blank|gene"):
            build_index(adata, schema, min_cells=10)

    def test_gene_axis_mismatch(self) -> None:
        """gene_id_key column has more IDs than X.shape[1] — mismatch detected.

        AnnData enforces var.shape[0] == X.shape[1], so we cannot create a direct
        var/X shape mismatch via the normal AnnData API.  Instead we test the
        same guard via a gene_id_key column whose number of *unique* values differs
        from n_genes — but AnnData would still be consistent internally.

        The only way to trigger the mismatch check without fighting AnnData is to
        use a mock-like object.  We subclass AnnData-backed concepts to simulate an
        AnnData where gene_id_key resolves to a different count than X.shape[1].

        Practically we build a valid AnnData (5 genes, X.shape=(n,5)), then after
        construction we monkey-patch var to have 3 rows to simulate the discrepancy
        that our validation code should catch.  We bypass AnnData's setter to do this.
        """
        n_cells = 110
        X = sp.random(n_cells, 5, density=0.3, format="csr", dtype=np.float32)
        X.data[:] = 1.0
        labels = [CTRL_VAL] * 80 + ["geneA"] * 30
        obs = pd.DataFrame({PERT_KEY: labels}, index=[f"c{i}" for i in range(n_cells)])
        var5 = pd.DataFrame(index=[f"g{i}" for i in range(5)])
        adata = anndata.AnnData(X=X, obs=obs, var=var5)

        # Patch var to only 3 rows — bypassing AnnData's setter via the backing dict
        var3 = pd.DataFrame(index=["g0", "g1", "g2"])
        object.__setattr__(adata, "_var", var3)

        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        with pytest.raises(SchemaError, match="gene|axis|mismatch|shape"):
            build_index(adata, schema, min_cells=10)

    def test_negative_value_in_X(self) -> None:
        adata = _make_adata(data_value=-1.0)
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        with pytest.raises(SchemaError, match="[Nn]egative|nonneg"):
            build_index(adata, schema, min_cells=10)

    def test_inf_value_in_X(self) -> None:
        adata = _make_adata(data_value=np.inf)
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        with pytest.raises(SchemaError, match="[Ff]inite|inf"):
            build_index(adata, schema, min_cells=10)

    def test_nan_value_in_X(self) -> None:
        adata = _make_adata(data_value=np.nan)
        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        with pytest.raises(SchemaError, match="[Ff]inite|nan|NaN"):
            build_index(adata, schema, min_cells=10)


# ---------------------------------------------------------------------------
# 4. NO GLOBAL DENSIFICATION — the headline test
# ---------------------------------------------------------------------------


class _NoGlobalDenseCSR(sp.csr_matrix):
    """Sentinel CSR that raises AssertionError if toarray/todense is called on it."""

    def toarray(self, order=None, out=None):  # type: ignore[override]
        raise AssertionError("global densification attempted: toarray() called")

    def todense(self, order=None, out=None):  # type: ignore[override]
        raise AssertionError("global densification attempted: todense() called")


class TestNoDensification:
    def test_sentinel_does_not_densify(self) -> None:
        """build_index must complete on the sentinel sparse matrix without densifying."""
        n_cells, n_g = 210, N_GENES
        base = sp.random(n_cells, n_g, density=0.3, format="csr", dtype=np.float32)
        base.data[:] = 1.0
        sentinel = _NoGlobalDenseCSR(base)

        labels = [CTRL_VAL] * 80 + ["geneA"] * 100 + ["geneB"] * 30
        obs = pd.DataFrame({PERT_KEY: labels}, index=[f"cell{i}" for i in range(n_cells)])
        var = pd.DataFrame(index=GENE_IDS)
        adata = anndata.AnnData(X=sentinel, obs=obs, var=var)

        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)
        # Must NOT raise AssertionError (densification guard)
        idx = build_index(adata, schema, min_cells=64)

        assert idx.n_cells == n_cells
        assert "geneA" in idx.eligible_perturbations
        assert "geneB" not in idx.eligible_perturbations


# ---------------------------------------------------------------------------
# 5. gene_id_key: use var column instead of var_names
# ---------------------------------------------------------------------------


class TestGeneIdKey:
    def test_gene_id_from_var_column(self) -> None:
        n_cells, n_g = 120, 3
        X = sp.random(n_cells, n_g, density=0.3, format="csr", dtype=np.float32)
        X.data[:] = 1.0

        labels = [CTRL_VAL] * 80 + ["geneA"] * 40
        obs = pd.DataFrame({PERT_KEY: labels}, index=[f"c{i}" for i in range(n_cells)])
        # var has custom gene_id column
        var = pd.DataFrame(
            {"ensembl_id": ["ENSG001", "ENSG002", "ENSG003"]},
            index=["row0", "row1", "row2"],
        )
        adata = anndata.AnnData(X=X, obs=obs, var=var)

        schema = DatasetSchema(
            perturbation_key=PERT_KEY,
            control_value=CTRL_VAL,
            gene_id_key="ensembl_id",
        )
        idx = build_index(adata, schema, min_cells=10)
        assert idx.gene_ids == ("ENSG001", "ENSG002", "ENSG003")


# ---------------------------------------------------------------------------
# 6. counts_layer: use a layer instead of X
# ---------------------------------------------------------------------------


class TestCountsLayer:
    def test_counts_from_layer(self) -> None:
        n_cells, n_g = 120, N_GENES
        X = sp.random(n_cells, n_g, density=0.3, format="csr", dtype=np.float32)
        X.data[:] = 5.0  # X has valid positive data
        layer_counts = sp.random(n_cells, n_g, density=0.3, format="csr", dtype=np.float32)
        layer_counts.data[:] = 2.0

        labels = [CTRL_VAL] * 80 + ["geneA"] * 40
        obs = pd.DataFrame({PERT_KEY: labels}, index=[f"c{i}" for i in range(n_cells)])
        var = pd.DataFrame(index=GENE_IDS)
        adata = anndata.AnnData(X=X, obs=obs, var=var, layers={"counts": layer_counts})

        schema = DatasetSchema(
            perturbation_key=PERT_KEY,
            control_value=CTRL_VAL,
            counts_layer="counts",
        )
        idx = build_index(adata, schema, min_cells=10)
        assert idx.n_genes == N_GENES

    def test_counts_layer_negative_raises(self) -> None:
        """Negative values in the *layer* (not X) must still raise SchemaError."""
        n_cells, n_g = 120, N_GENES
        X = sp.random(n_cells, n_g, density=0.3, format="csr", dtype=np.float32)
        X.data[:] = 5.0
        bad_layer = sp.random(n_cells, n_g, density=0.3, format="csr", dtype=np.float32)
        bad_layer.data[:] = -1.0

        labels = [CTRL_VAL] * 80 + ["geneA"] * 40
        obs = pd.DataFrame({PERT_KEY: labels}, index=[f"c{i}" for i in range(n_cells)])
        var = pd.DataFrame(index=GENE_IDS)
        adata = anndata.AnnData(X=X, obs=obs, var=var, layers={"raw_counts": bad_layer})

        schema = DatasetSchema(
            perturbation_key=PERT_KEY,
            control_value=CTRL_VAL,
            counts_layer="raw_counts",
        )
        with pytest.raises(SchemaError, match="[Nn]egative|nonneg"):
            build_index(adata, schema, min_cells=10)


# ---------------------------------------------------------------------------
# 7. backed="r" path test
# ---------------------------------------------------------------------------


class TestBackedPath:
    def test_backed_path_matches_in_memory(self, tmp_path: Path) -> None:
        """Write a fixture .h5ad and open via path; result must match in-memory build."""
        adata = _make_adata(n_ctrl=80, pert_cells={"geneA": 100, "geneB": 30})
        h5_path = tmp_path / "fixture.h5ad"
        adata.write_h5ad(h5_path)

        schema = DatasetSchema(perturbation_key=PERT_KEY, control_value=CTRL_VAL)

        idx_mem = build_index(adata, schema, min_cells=64)
        idx_path = build_index(h5_path, schema, min_cells=64)

        assert idx_path.n_cells == idx_mem.n_cells
        assert idx_path.n_genes == idx_mem.n_genes
        assert idx_path.gene_ids == idx_mem.gene_ids
        assert idx_path.eligible_perturbations == idx_mem.eligible_perturbations
        assert set(idx_path.exclusions.keys()) == set(idx_mem.exclusions.keys())
        np.testing.assert_array_equal(idx_path.control_indices, idx_mem.control_indices)
        for pert in idx_mem.perturbation_indices:
            np.testing.assert_array_equal(
                idx_path.perturbation_indices[pert], idx_mem.perturbation_indices[pert]
            )
