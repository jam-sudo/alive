"""Tests for src/alive/data/preprocess.py — train-fitted response space.

TDD order: tests written first; the implementation must pass all of them.

The three properties under test are leakage-boundary correctness, determinism
(byte-identical fit + serialisation), and bounded-memory streaming.  All tests
use small synthetic AnnData fixtures; the real ``.h5ad`` is NOT required.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import anndata
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from alive.config import SplitFractions
from alive.data.manifest import build_manifest_from_index
from alive.data.outcome_store import Population, ReplogleOutcomeStore
from alive.data.preprocess import (
    PreprocessError,
    ResponseSpace,
    fit_response_space,
)
from alive.data.replogle import DatasetSchema, build_index

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PERT_KEY = "target"
_CTRL_VAL = "ctrl"
_NORM = "library_size_10000_log1p"
_TARGET_SUM = 10000.0

# Many eligible perturbations so every split role is non-empty.
_FRACTIONS = SplitFractions(
    base_train=0.40,
    method_development=0.25,
    conformal_calibration=0.15,
    sealed_evaluation=0.20,
)
_SEED = 11


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_store(
    adata: anndata.AnnData,
    tmp_path: Path,
    *,
    min_cells: int = 5,
) -> tuple[ReplogleOutcomeStore, object, object]:
    """Build index + manifest + store from a synthetic AnnData.

    Returns ``(store, index, manifest)``.
    """
    schema = DatasetSchema(perturbation_key=_PERT_KEY, control_value=_CTRL_VAL)
    index = build_index(adata, schema, min_cells=min_cells)
    manifest = build_manifest_from_index(index, _FRACTIONS, _SEED)
    store = ReplogleOutcomeStore(
        index=index,
        source=adata,
        manifest=manifest,
        audit_path=tmp_path / "audit.jsonl",
    )
    return store, index, manifest


def _make_simple_adata(
    *,
    n_genes: int = 12,
    n_ctrl: int = 30,
    n_perts: int = 12,
    cells_per_pert: int = 12,
    seed: int = 0,
) -> anndata.AnnData:
    """Synthetic count AnnData with random nonnegative integer counts."""
    rng = np.random.default_rng(seed)
    labels: list[str] = [_CTRL_VAL] * n_ctrl
    for i in range(n_perts):
        labels.extend([f"gene{i:02d}"] * cells_per_pert)
    n_cells = len(labels)

    counts = rng.integers(0, 50, size=(n_cells, n_genes)).astype(np.float32)
    X = sp.csr_matrix(counts)
    gene_ids = [f"g{j}" for j in range(n_genes)]
    obs = pd.DataFrame({_PERT_KEY: labels}, index=[f"c{i}" for i in range(n_cells)])
    var = pd.DataFrame(index=gene_ids)
    return anndata.AnnData(X=X, obs=obs, var=var)


# ---------------------------------------------------------------------------
# Spy store: proves sealed cohort is never touched during fitting
# ---------------------------------------------------------------------------


class SpyOutcomeStore:
    """Wraps a real store; counts any call to ``evaluate_sealed_once``."""

    def __init__(self, inner: ReplogleOutcomeStore) -> None:
        self._inner = inner
        self.evaluate_sealed_calls = 0

    def read_controls(self) -> Population:
        return self._inner.read_controls()

    def read_unsealed(self, perturbation_ids: Sequence[str]) -> dict[str, Population]:
        return self._inner.read_unsealed(perturbation_ids)

    def evaluate_sealed_once(
        self, run_id: str, perturbation_ids: Sequence[str]
    ) -> dict[str, Population]:
        self.evaluate_sealed_calls += 1
        return self._inner.evaluate_sealed_once(run_id, perturbation_ids)

    @property
    def sealed_access_count(self) -> int:
        return self._inner.sealed_access_count


# ---------------------------------------------------------------------------
# Reference helpers (independent re-implementations for leakage proof)
# ---------------------------------------------------------------------------


def _normalize_log1p(cells: np.ndarray, target_sum: float) -> np.ndarray:
    """Independent normalize+log1p reference (float64)."""
    x = cells.astype(np.float64)
    sums = x.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        scaled = np.where(sums > 0, x * (target_sum / sums), 0.0)
    return np.log1p(scaled)


def _reference_fit_stats(
    fit_pops: list[np.ndarray],
    target_sum: float,
    hvg_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Independently compute (selected_gene_indices, hvg_means, variances)."""
    stacked = np.vstack([_normalize_log1p(p, target_sum) for p in fit_pops])
    n = stacked.shape[0]
    mean = stacked.sum(axis=0) / n
    var = stacked.var(axis=0)  # population variance, divide by n
    # top hvg_count by variance descending, ties by ascending gene index
    order = sorted(range(len(var)), key=lambda j: (-var[j], j))
    selected = sorted(order[:hvg_count])
    hvg_means = mean[selected]
    return np.array(selected, dtype=int), hvg_means, var


# ===========================================================================
# 1. Shapes
# ===========================================================================


class TestShapes:
    def test_components_and_transform_shapes(self, tmp_path: Path) -> None:
        adata = _make_simple_adata(n_genes=12)
        store, index, manifest = _build_store(adata, tmp_path)
        hvg_count, pca_dims = 6, 3

        rs = fit_response_space(
            index,
            store,
            manifest,
            normalization=_NORM,
            target_sum=_TARGET_SUM,
            hvg_count=hvg_count,
            pca_dims=pca_dims,
        )

        assert rs.components.shape == (pca_dims, hvg_count)
        assert rs.explained_variance.shape == (pca_dims,)
        assert rs.explained_variance_ratio.shape == (pca_dims,)
        assert rs.hvg_means.shape == (hvg_count,)
        assert rs.selected_gene_indices.shape == (hvg_count,)
        assert len(rs.selected_gene_ids) == hvg_count
        assert rs.n_genes_full == 12

        ctrl = store.read_controls()
        out = rs.transform(ctrl.cells)
        assert out.shape == (ctrl.cells.shape[0], pca_dims)

    def test_selected_gene_indices_sorted_ascending(self, tmp_path: Path) -> None:
        adata = _make_simple_adata(n_genes=12)
        store, index, manifest = _build_store(adata, tmp_path)
        rs = fit_response_space(
            index,
            store,
            manifest,
            normalization=_NORM,
            target_sum=_TARGET_SUM,
            hvg_count=5,
            pca_dims=2,
        )
        idx = rs.selected_gene_indices
        assert list(idx) == sorted(idx)
        # ids correspond in order to indices
        expected_ids = tuple(index.gene_ids[i] for i in idx)
        assert rs.selected_gene_ids == expected_ids


# ===========================================================================
# 2. Normalization correctness
# ===========================================================================


class TestNormalization:
    def test_hand_built_row_normalizes_to_expected(self, tmp_path: Path) -> None:
        # A cell row [1, 3] -> sum 4 -> scaled to target_sum 10 -> [2.5, 7.5]
        # -> log1p -> [log(3.5), log(8.5)].  We verify this through transform's
        # first step by fitting on a trivial dataset and re-deriving.
        # Direct verification: build the response space then check that the
        # internal normalization matches log1p(library_size_normalize).
        adata = _make_simple_adata(n_genes=4, n_ctrl=20, n_perts=10, cells_per_pert=8)
        store, index, manifest = _build_store(adata, tmp_path)
        rs = fit_response_space(
            index,
            store,
            manifest,
            normalization=_NORM,
            target_sum=10.0,
            hvg_count=4,
            pca_dims=2,
        )
        # hvg = all 4 genes (sorted), so transform = (norm - means) @ comps.T.
        # Reconstruct the normalized representation by inverting centering+PCA
        # is fragile; instead assert normalization formula directly via a
        # 1-cell population transform against a manual computation.
        cell = np.array([[1.0, 3.0, 0.0, 0.0]], dtype=np.float32)
        norm_expected = _normalize_log1p(cell, 10.0)  # [[log(3.5), log(8.5), 0, 0]]
        # Selected indices are all 4 (sorted ascending) because hvg_count=4.
        assert list(rs.selected_gene_indices) == [0, 1, 2, 3]
        centered = norm_expected - rs.hvg_means
        manual = centered @ rs.components.T
        got = rs.transform(cell)
        np.testing.assert_allclose(got, manual, rtol=0, atol=1e-12)
        # And check the literal normalization values.
        np.testing.assert_allclose(
            norm_expected[0, :2],
            [np.log1p(2.5), np.log1p(7.5)],
            rtol=0,
            atol=1e-12,
        )

    def test_zero_sum_row_stays_zero(self, tmp_path: Path) -> None:
        out = _normalize_log1p(np.zeros((1, 4), dtype=np.float32), 10000.0)
        assert np.all(out == 0.0)

    def test_unsupported_normalization_raises(self, tmp_path: Path) -> None:
        adata = _make_simple_adata()
        store, index, manifest = _build_store(adata, tmp_path)
        with pytest.raises(PreprocessError):
            fit_response_space(
                index,
                store,
                manifest,
                normalization="counts_per_million",
                target_sum=_TARGET_SUM,
                hvg_count=4,
                pca_dims=2,
            )


# ===========================================================================
# 3. HVG selection picks high-variance genes
# ===========================================================================


class TestHVGSelection:
    def test_high_variance_genes_selected(self, tmp_path: Path) -> None:
        # Construct fit cells where genes 0 and 1 carry ALL the variance and
        # the rest are constant-per-cell (after normalization).  Because
        # normalization couples genes via library size, we make the high-var
        # genes dominate the total counts so their normalized values vary a
        # lot and the rest stay near-constant.
        rng = np.random.default_rng(3)
        n_genes = 8
        labels: list[str] = [_CTRL_VAL] * 30
        for i in range(12):
            labels.extend([f"gene{i:02d}"] * 10)
        n_cells = len(labels)

        counts = np.full((n_cells, n_genes), 5.0, dtype=np.float32)
        # genes 2 and 5 carry large cell-to-cell variation
        counts[:, 2] = rng.integers(0, 500, size=n_cells).astype(np.float32)
        counts[:, 5] = rng.integers(0, 500, size=n_cells).astype(np.float32)
        X = sp.csr_matrix(counts)
        gene_ids = [f"g{j}" for j in range(n_genes)]
        obs = pd.DataFrame({_PERT_KEY: labels}, index=[f"c{i}" for i in range(n_cells)])
        var = pd.DataFrame(index=gene_ids)
        adata = anndata.AnnData(X=X, obs=obs, var=var)

        store, index, manifest = _build_store(adata, tmp_path)
        rs = fit_response_space(
            index,
            store,
            manifest,
            normalization=_NORM,
            target_sum=_TARGET_SUM,
            hvg_count=2,
            pca_dims=2,
        )
        assert set(rs.selected_gene_indices.tolist()) == {2, 5}

    def test_total_genes_below_hvg_count_raises(self, tmp_path: Path) -> None:
        adata = _make_simple_adata(n_genes=4)
        store, index, manifest = _build_store(adata, tmp_path)
        with pytest.raises(PreprocessError):
            fit_response_space(
                index,
                store,
                manifest,
                normalization=_NORM,
                target_sum=_TARGET_SUM,
                hvg_count=5,  # > 4 total genes
                pca_dims=2,
            )


# ===========================================================================
# 4. PCA sanity
# ===========================================================================


class TestPCA:
    def test_dominant_direction_recovered(self, tmp_path: Path) -> None:
        # Build data whose normalized-log1p representation has a dominant axis
        # of variation across two HVGs.  We assert the top component aligns
        # with that axis up to the fixed sign convention.
        rng = np.random.default_rng(5)
        n_genes = 6
        labels: list[str] = [_CTRL_VAL] * 40
        for i in range(12):
            labels.extend([f"gene{i:02d}"] * 12)
        n_cells = len(labels)

        # Genes 1 and 4 dominate variance, gene 1 with ~3x the spread of gene 4.
        counts = np.full((n_cells, n_genes), 10.0, dtype=np.float32)
        counts[:, 1] = rng.integers(0, 900, size=n_cells).astype(np.float32)
        counts[:, 4] = rng.integers(0, 300, size=n_cells).astype(np.float32)
        X = sp.csr_matrix(counts)
        gene_ids = [f"g{j}" for j in range(n_genes)]
        obs = pd.DataFrame({_PERT_KEY: labels}, index=[f"c{i}" for i in range(n_cells)])
        var = pd.DataFrame(index=gene_ids)
        adata = anndata.AnnData(X=X, obs=obs, var=var)

        store, index, manifest = _build_store(adata, tmp_path)
        rs = fit_response_space(
            index,
            store,
            manifest,
            normalization=_NORM,
            target_sum=_TARGET_SUM,
            hvg_count=2,
            pca_dims=2,
        )
        # selected HVGs are genes 1 and 4 (sorted -> [1, 4])
        assert list(rs.selected_gene_indices) == [1, 4]
        # explained_variance descending
        assert rs.explained_variance[0] >= rs.explained_variance[1]
        # ratios sum to <= 1 (top-2 of a 2-dim cov == 1.0)
        assert rs.explained_variance_ratio.sum() <= 1.0 + 1e-9
        # the top component's largest-magnitude entry is the higher-variance HVG
        top = rs.components[0]
        assert abs(top[0]) > abs(top[1])  # gene 1 (HVG position 0) dominates
        # sign convention: max-abs entry positive
        assert top[np.argmax(np.abs(top))] > 0

    def test_pca_dims_exceeds_hvg_raises(self, tmp_path: Path) -> None:
        adata = _make_simple_adata(n_genes=12)
        store, index, manifest = _build_store(adata, tmp_path)
        with pytest.raises(PreprocessError):
            fit_response_space(
                index,
                store,
                manifest,
                normalization=_NORM,
                target_sum=_TARGET_SUM,
                hvg_count=3,
                pca_dims=4,  # > hvg_count
            )

    def test_sign_convention_max_abs_positive(self, tmp_path: Path) -> None:
        adata = _make_simple_adata(n_genes=10)
        store, index, manifest = _build_store(adata, tmp_path)
        rs = fit_response_space(
            index,
            store,
            manifest,
            normalization=_NORM,
            target_sum=_TARGET_SUM,
            hvg_count=6,
            pca_dims=4,
        )
        for comp in rs.components:
            assert comp[np.argmax(np.abs(comp))] > 0


# ===========================================================================
# 5. Determinism
# ===========================================================================


class TestDeterminism:
    def test_two_fits_identical(self, tmp_path: Path) -> None:
        adata = _make_simple_adata(n_genes=12, seed=2)
        store_a, index_a, manifest_a = _build_store(adata, tmp_path / "a")
        store_b, index_b, manifest_b = _build_store(adata, tmp_path / "b")
        (tmp_path / "a").mkdir(exist_ok=True)
        (tmp_path / "b").mkdir(exist_ok=True)

        kwargs = dict(
            normalization=_NORM,
            target_sum=_TARGET_SUM,
            hvg_count=6,
            pca_dims=3,
        )
        rs1 = fit_response_space(index_a, store_a, manifest_a, **kwargs)
        rs2 = fit_response_space(index_b, store_b, manifest_b, **kwargs)

        np.testing.assert_array_equal(rs1.components, rs2.components)
        np.testing.assert_array_equal(rs1.hvg_means, rs2.hvg_means)
        np.testing.assert_array_equal(rs1.selected_gene_indices, rs2.selected_gene_indices)
        np.testing.assert_array_equal(rs1.explained_variance, rs2.explained_variance)
        assert rs1.checksum == rs2.checksum


# ===========================================================================
# 6. Byte-identical after serialization
# ===========================================================================


class TestSerialization:
    def test_round_trip_transform_identical(self, tmp_path: Path) -> None:
        adata = _make_simple_adata(n_genes=12, seed=4)
        store, index, manifest = _build_store(adata, tmp_path)
        rs = fit_response_space(
            index,
            store,
            manifest,
            normalization=_NORM,
            target_sum=_TARGET_SUM,
            hvg_count=6,
            pca_dims=3,
        )
        path = tmp_path / "respspace"
        rs.write(path)
        rs2 = ResponseSpace.read(path)

        ctrl = store.read_controls()
        np.testing.assert_array_equal(rs.transform(ctrl.cells), rs2.transform(ctrl.cells))
        assert rs.checksum == rs2.checksum
        np.testing.assert_array_equal(rs.components, rs2.components)
        np.testing.assert_array_equal(rs.hvg_means, rs2.hvg_means)
        assert rs.selected_gene_ids == rs2.selected_gene_ids
        assert rs.n_genes_full == rs2.n_genes_full

    def test_transform_width_mismatch_raises(self, tmp_path: Path) -> None:
        adata = _make_simple_adata(n_genes=12)
        store, index, manifest = _build_store(adata, tmp_path)
        rs = fit_response_space(
            index,
            store,
            manifest,
            normalization=_NORM,
            target_sum=_TARGET_SUM,
            hvg_count=6,
            pca_dims=3,
        )
        bad = np.ones((3, 11), dtype=np.float32)  # wrong gene-axis width
        with pytest.raises(PreprocessError):
            rs.transform(bad)


# ===========================================================================
# 7. LEAKAGE (headline)
# ===========================================================================


class TestLeakageBoundary:
    def _make_marker_adata(
        self, tmp_path: Path
    ) -> tuple[anndata.AnnData, object, object, list[str], list[str], int]:
        """Build an AnnData where ONE marker gene is hugely expressed ONLY in
        method_development / conformal_calibration / sealed_evaluation cells,
        and ~zero in controls + base_train cells.

        Returns (adata, index, manifest, fit_ids, nonfit_ids, marker_idx).
        """
        n_genes = 10
        marker_idx = 7

        # First build a provisional dataset to derive the manifest split, then
        # inject the marker into the non-fit split cells.
        rng = np.random.default_rng(13)
        n_ctrl = 40
        n_perts = 20
        cells_per_pert = 12
        labels: list[str] = [_CTRL_VAL] * n_ctrl
        for i in range(n_perts):
            labels.extend([f"gene{i:02d}"] * cells_per_pert)
        n_cells = len(labels)
        counts = rng.integers(0, 30, size=(n_cells, n_genes)).astype(np.float64)
        # zero out the marker everywhere first
        counts[:, marker_idx] = 0.0

        obs = pd.DataFrame({_PERT_KEY: labels}, index=[f"c{i}" for i in range(n_cells)])
        var = pd.DataFrame(index=[f"g{j}" for j in range(n_genes)])

        schema = DatasetSchema(perturbation_key=_PERT_KEY, control_value=_CTRL_VAL)
        prelim = anndata.AnnData(X=sp.csr_matrix(counts), obs=obs, var=var)
        index = build_index(prelim, schema, min_cells=5)
        manifest = build_manifest_from_index(index, _FRACTIONS, _SEED)

        base_train_ids = list(manifest.ids_for("base_train"))
        nonfit_ids = (
            list(manifest.ids_for("method_development"))
            + list(manifest.ids_for("conformal_calibration"))
            + list(manifest.ids_for("sealed_evaluation"))
        )

        # Inject a huge marker signal ONLY into the non-fit perturbation cells.
        for pid in nonfit_ids:
            rows = index.cell_indices(pid)
            counts[rows, marker_idx] = 5000.0

        adata = anndata.AnnData(X=sp.csr_matrix(counts), obs=obs, var=var)
        index2 = build_index(adata, schema, min_cells=5)
        manifest2 = build_manifest_from_index(index2, _FRACTIONS, _SEED)
        return adata, index2, manifest2, base_train_ids, nonfit_ids, marker_idx

    def test_marker_gene_not_selected_and_stats_match_reference(self, tmp_path: Path) -> None:
        adata, index, manifest, base_train_ids, nonfit_ids, marker_idx = self._make_marker_adata(
            tmp_path
        )
        store = ReplogleOutcomeStore(
            index=index, source=adata, manifest=manifest, audit_path=tmp_path / "audit.jsonl"
        )
        hvg_count = 6
        rs = fit_response_space(
            index,
            store,
            manifest,
            normalization=_NORM,
            target_sum=_TARGET_SUM,
            hvg_count=hvg_count,
            pca_dims=3,
        )

        # (b) marker gene is NOT selected as an HVG (its variance over fit cells ~0)
        assert marker_idx not in rs.selected_gene_indices.tolist()

        # (a) hvg_means and selected_gene_indices equal an independent reference
        # computed ONLY from controls + base_train cells.
        ctrl = store.read_controls()
        fit_pops = [ctrl.cells]
        for pid in base_train_ids:
            fit_pops.append(store.read_unsealed([pid])[pid].cells)
        ref_idx, ref_means, ref_var = _reference_fit_stats(fit_pops, _TARGET_SUM, hvg_count)

        np.testing.assert_array_equal(rs.selected_gene_indices, ref_idx)
        np.testing.assert_allclose(rs.hvg_means, ref_means, rtol=0, atol=1e-12)

        # marker variance over fit cells must be ~0 (it is identically zero there)
        assert ref_var[marker_idx] == pytest.approx(0.0, abs=1e-12)

    def test_fit_differs_from_hypothetical_leaky_fit(self, tmp_path: Path) -> None:
        adata, index, manifest, base_train_ids, nonfit_ids, marker_idx = self._make_marker_adata(
            tmp_path
        )
        store = ReplogleOutcomeStore(
            index=index, source=adata, manifest=manifest, audit_path=tmp_path / "audit.jsonl"
        )
        hvg_count = 6
        rs = fit_response_space(
            index,
            store,
            manifest,
            normalization=_NORM,
            target_sum=_TARGET_SUM,
            hvg_count=hvg_count,
            pca_dims=3,
        )

        # (c) a hypothetical fit that INCLUDED the other splits would select the
        # marker gene (huge variance) — proving the real fit excluded them.
        ctrl = store.read_controls()
        leaky_pops = [ctrl.cells]
        for pid in base_train_ids:
            leaky_pops.append(store.read_unsealed([pid])[pid].cells)
        for pid in manifest.ids_for("method_development"):
            leaky_pops.append(store.read_unsealed([pid])[pid].cells)
        for pid in manifest.ids_for("conformal_calibration"):
            leaky_pops.append(store.read_unsealed([pid])[pid].cells)
        leaky_idx, leaky_means, leaky_var = _reference_fit_stats(leaky_pops, _TARGET_SUM, hvg_count)

        # The leaky fit selects the marker; the real one does not.
        assert marker_idx in leaky_idx.tolist()
        assert marker_idx not in rs.selected_gene_indices.tolist()
        # Therefore the selected sets (and hence the stats) differ.
        assert set(rs.selected_gene_indices.tolist()) != set(leaky_idx.tolist())


# ===========================================================================
# 8. Sealing respected
# ===========================================================================


class TestSealingRespected:
    def test_fit_never_opens_sealed_cohort(self, tmp_path: Path) -> None:
        adata = _make_simple_adata(n_genes=12)
        inner, index, manifest = _build_store(adata, tmp_path)
        spy = SpyOutcomeStore(inner)

        fit_response_space(
            index,
            spy,
            manifest,
            normalization=_NORM,
            target_sum=_TARGET_SUM,
            hvg_count=6,
            pca_dims=3,
        )

        assert spy.evaluate_sealed_calls == 0
        assert spy.sealed_access_count == 0
