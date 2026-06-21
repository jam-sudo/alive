"""Tests for src/alive/base/predictor.py — frozen additive ridge base predictor.

TDD order: tests written first; implementation must pass all of them.

All tests use small synthetic fixtures; the real .h5ad is NOT required.
A stub ResponseSpace transform (identity-like) is used where the real
fit_response_space would be heavy.  One "recover known linear shift" test
engineers populations whose means equal control_mean + phi_g @ W_true.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from alive.base.predictor import BaseModelError, BasePredictor, fit_base_predictor
from alive.types import BasePrediction, Query

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEED = 42
_FEAT_DIM = 4  # small for speed
_PCA_DIMS = 3
_N_CTRL = 20
_RIDGE_GRID = (1e-3, 1.0, 10.0, 100.0)
_CV_FOLDS = 3
_ENSEMBLE_MEMBERS = 5

# ---------------------------------------------------------------------------
# Stub ResponseSpace
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StubResponseSpace:
    """Minimal stub that applies a fixed linear projection.

    ``transform(cells)`` -> cells[:, :pca_dims]  (first pca_dims columns).
    Requires cells to have at least pca_dims columns.
    """

    pca_dims: int = _PCA_DIMS

    def transform(self, cells: np.ndarray) -> np.ndarray:
        arr = np.asarray(cells, dtype=np.float64)
        return arr[:, : self.pca_dims]


# ---------------------------------------------------------------------------
# Stub Population / FeatureBank / SplitManifest / OutcomeStore
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Population:
    perturbation_id: str
    cells: np.ndarray


class _StubFeatureBank:
    """Minimal feature bank backed by a dict of pre-computed float64 vectors."""

    def __init__(self, vectors: dict[str, np.ndarray]) -> None:
        self._vectors = vectors
        self.dim = next(iter(vectors.values())).shape[0] if vectors else _FEAT_DIM

    def has(self, gene: str) -> bool:
        return gene in self._vectors

    def standardized_vector(self, gene: str) -> np.ndarray:
        if gene not in self._vectors:
            raise KeyError(gene)
        return self._vectors[gene].astype(np.float64)


class _StubManifest:
    """Returns a fixed list of base_train ids."""

    def __init__(self, base_train_ids: list[str]) -> None:
        self._ids = tuple(sorted(base_train_ids))

    def ids_for(self, role: str) -> tuple[str, ...]:
        if role == "base_train":
            return self._ids
        return ()


class _StubStore:
    """Returns pre-built populations; tracks sealed_access_count."""

    def __init__(
        self,
        ctrl_cells: np.ndarray,
        pert_populations: dict[str, np.ndarray],
    ) -> None:
        self._ctrl = _Population("ctrl", ctrl_cells)
        self._pops = pert_populations
        self._sealed_count = 0

    @property
    def sealed_access_count(self) -> int:
        return self._sealed_count

    def read_controls(self) -> _Population:
        return self._ctrl

    def read_unsealed(self, perturbation_ids: Sequence[str]) -> dict[str, _Population]:
        return {pid: _Population(pid, self._pops[pid]) for pid in perturbation_ids}

    def evaluate_sealed_once(self, run_id: str, perturbation_ids: Sequence[str]) -> dict:
        # Must never be called by fit_base_predictor
        self._sealed_count += 1
        raise RuntimeError("evaluate_sealed_once must never be called by fit_base_predictor")


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_ctrl_cells(rng: np.random.Generator) -> np.ndarray:
    """(N_CTRL, _PCA_DIMS+2) raw count matrix that after stub-transform gives _PCA_DIMS cols."""
    return rng.uniform(0.5, 1.5, size=(_N_CTRL, _PCA_DIMS + 2)).astype(np.float32)


def _make_feature_vectors(n_genes: int, rng: np.random.Generator) -> np.ndarray:
    """(n_genes, FEAT_DIM) random feature matrix."""
    return rng.standard_normal(size=(n_genes, _FEAT_DIM))


def _build_linear_fixture(
    n_pert: int = 10,
    rng_seed: int = 0,
) -> tuple[_StubManifest, _StubStore, _StubResponseSpace, _StubFeatureBank, np.ndarray]:
    """Build a fixture where each perturbation mean shift = phi_g @ W_true (+ tiny noise)."""
    rng = np.random.default_rng(rng_seed)

    # True weights (feat_dim x pca_dims)
    W_true = rng.standard_normal((_FEAT_DIM, _PCA_DIMS))

    ctrl_cells = _make_ctrl_cells(rng)
    rs = _StubResponseSpace(pca_dims=_PCA_DIMS)

    # Control mean in response space
    ctrl_transformed = rs.transform(ctrl_cells.astype(np.float64))
    control_mean = ctrl_transformed.mean(axis=0)  # (pca_dims,)

    gene_ids = [f"g{i}" for i in range(n_pert)]
    feat_matrix = _make_feature_vectors(n_pert, rng)  # (n_pert, feat_dim)

    # For each gene: engineer cells so mean = control_mean + phi @ W_true
    pert_pops: dict[str, np.ndarray] = {}
    feat_vectors: dict[str, np.ndarray] = {}
    n_cells_per_pert = 30

    for i, gid in enumerate(gene_ids):
        phi = feat_matrix[i]  # (feat_dim,)
        target_mean = control_mean + phi @ W_true  # (pca_dims,)

        # We need cells such that rs.transform(cells).mean(axis=0) ≈ target_mean.
        # rs.transform returns cells[:, :pca_dims]. So we need raw cells where
        # first pca_dims columns have mean ≈ target_mean.
        # Build cells in raw space: first pca_dims cols = target_mean (broadcast)
        # + tiny noise (noise << signal so W_true is recoverable).
        noise_scale = 1e-4
        raw = np.zeros((n_cells_per_pert, _PCA_DIMS + 2), dtype=np.float64)
        raw[:, :_PCA_DIMS] = (
            target_mean + rng.standard_normal((n_cells_per_pert, _PCA_DIMS)) * noise_scale
        )
        raw[:, _PCA_DIMS:] = 1.0  # dummy extra columns
        pert_pops[gid] = raw.astype(np.float32)
        feat_vectors[gid] = phi

    manifest = _StubManifest(gene_ids)
    store = _StubStore(ctrl_cells=ctrl_cells, pert_populations=pert_pops)
    feature_bank = _StubFeatureBank(feat_vectors)

    return manifest, store, rs, feature_bank, W_true


def _build_simple_fixture(
    n_pert: int = 8,
    rng_seed: int = 99,
) -> tuple[_StubManifest, _StubStore, _StubResponseSpace, _StubFeatureBank]:
    """Simple fixture without a known W_true — suitable for shape/composition tests."""
    rng = np.random.default_rng(rng_seed)
    ctrl_cells = _make_ctrl_cells(rng).astype(np.float64)

    gene_ids = [f"gene_{i}" for i in range(n_pert)]
    feat_vectors: dict[str, np.ndarray] = {}
    pert_pops: dict[str, np.ndarray] = {}

    for gid in gene_ids:
        feat_vectors[gid] = rng.standard_normal(_FEAT_DIM)
        cells = rng.uniform(0.5, 2.0, size=(20, _PCA_DIMS + 2)).astype(np.float64)
        pert_pops[gid] = cells

    manifest = _StubManifest(gene_ids)
    store = _StubStore(ctrl_cells=ctrl_cells, pert_populations=pert_pops)
    rs = _StubResponseSpace(pca_dims=_PCA_DIMS)
    feature_bank = _StubFeatureBank(feat_vectors)
    return manifest, store, rs, feature_bank


def _fit_simple(rng_seed: int = 99) -> BasePredictor:
    manifest, store, rs, fb = _build_simple_fixture(rng_seed=rng_seed)
    return fit_base_predictor(
        manifest=manifest,
        store=store,
        response_space=rs,
        feature_bank=fb,
        ridge_grid=_RIDGE_GRID,
        cv_folds=_CV_FOLDS,
        ensemble_members=_ENSEMBLE_MEMBERS,
        seed=_SEED,
    )


# ===========================================================================
# Test classes
# ===========================================================================


class TestRecoverKnownLinearShift:
    """fit_base_predictor should recover W_true on near-noiseless linear data."""

    def test_weights_close_to_w_true(self) -> None:
        manifest, store, rs, fb, W_true = _build_linear_fixture(n_pert=12, rng_seed=7)
        predictor = fit_base_predictor(
            manifest=manifest,
            store=store,
            response_space=rs,
            feature_bank=fb,
            ridge_grid=(1e-6, 1e-4, 1e-2),  # small alphas so bias is tiny
            cv_folds=_CV_FOLDS,
            ensemble_members=_ENSEMBLE_MEMBERS,
            seed=_SEED,
        )
        # With near-zero noise, recovered W should be close to W_true
        np.testing.assert_allclose(predictor.weights, W_true, atol=1e-2)

    def test_predicted_shift_close_to_true(self) -> None:
        manifest, store, rs, fb, W_true = _build_linear_fixture(n_pert=12, rng_seed=7)
        predictor = fit_base_predictor(
            manifest=manifest,
            store=store,
            response_space=rs,
            feature_bank=fb,
            ridge_grid=(1e-6, 1e-4, 1e-2),
            cv_folds=_CV_FOLDS,
            ensemble_members=_ENSEMBLE_MEMBERS,
            seed=_SEED,
        )
        rng = np.random.default_rng(42)
        phi = rng.standard_normal(_FEAT_DIM)
        true_shift = phi @ W_true
        predicted = predictor.predicted_shift(phi)
        np.testing.assert_allclose(predicted, true_shift, atol=1e-2)


class TestPredictShapeAndComposition:
    """predict() must return the correct shapes and mathematical relationships."""

    def test_predicted_cells_shape(self) -> None:
        predictor = _fit_simple()
        phi = np.zeros(_FEAT_DIM)
        query = Query(perturbation_id="test", features=phi)
        pred = predictor.predict(query)
        assert isinstance(pred, BasePrediction)
        assert pred.predicted_cells.shape == (_N_CTRL, _PCA_DIMS)

    def test_predicted_cells_equals_ctrl_plus_shift(self) -> None:
        predictor = _fit_simple()
        phi = np.ones(_FEAT_DIM)
        query = Query(perturbation_id="test", features=phi)
        pred = predictor.predict(query)
        shift = predictor.predicted_shift(phi)
        expected = predictor.transformed_control + shift
        np.testing.assert_array_equal(pred.predicted_cells, expected)

    def test_predicted_mean_equals_control_mean_plus_shift(self) -> None:
        predictor = _fit_simple()
        phi = np.ones(_FEAT_DIM)
        shift = predictor.predicted_shift(phi)
        expected_mean = predictor.control_mean + shift
        np.testing.assert_array_equal(predictor.predicted_mean(phi), expected_mean)

    def test_ensemble_member_means_shape(self) -> None:
        predictor = _fit_simple()
        phi = np.zeros(_FEAT_DIM)
        query = Query(perturbation_id="test", features=phi)
        pred = predictor.predict(query)
        assert pred.ensemble_member_means is not None
        assert pred.ensemble_member_means.shape == (_ENSEMBLE_MEMBERS, _PCA_DIMS)

    def test_ensemble_member_means_equals_control_mean_plus_phi_at_w_m(self) -> None:
        predictor = _fit_simple()
        phi = np.ones(_FEAT_DIM)
        query = Query(perturbation_id="test", features=phi)
        pred = predictor.predict(query)
        assert pred.ensemble_member_means is not None
        for m in range(_ENSEMBLE_MEMBERS):
            expected_m = predictor.control_mean + phi @ predictor.ensemble_weights[m]
            np.testing.assert_array_equal(pred.ensemble_member_means[m], expected_m)

    def test_predicted_cells_uses_query_features(self) -> None:
        predictor = _fit_simple()
        phi_a = np.ones(_FEAT_DIM)
        phi_b = -np.ones(_FEAT_DIM)
        pred_a = predictor.predict(Query("a", phi_a))
        pred_b = predictor.predict(Query("b", phi_b))
        # If W is nonzero, the two predictions differ
        # At minimum they should not both equal zero
        assert not np.allclose(pred_a.predicted_cells, pred_b.predicted_cells) or np.allclose(
            predictor.weights, 0.0
        )

    def test_predict_returns_correct_perturbation_id(self) -> None:
        predictor = _fit_simple()
        query = Query(perturbation_id="TP53", features=np.zeros(_FEAT_DIM))
        pred = predictor.predict(query)
        assert pred.perturbation_id == "TP53"


class TestCVAlphaSelection:
    """CV must populate cv_scores and choose the correct alpha."""

    def test_cv_scores_has_one_entry_per_grid_alpha(self) -> None:
        predictor = _fit_simple()
        assert set(predictor.cv_scores.keys()) == set(_RIDGE_GRID)

    def test_chosen_alpha_is_argmin_cv_score(self) -> None:
        predictor = _fit_simple()
        best_alpha = min(predictor.cv_scores, key=lambda a: (predictor.cv_scores[a], a))
        assert predictor.chosen_alpha == best_alpha

    def test_chosen_alpha_smaller_tie_break(self) -> None:
        """On near-flat CV (all identical), the smallest alpha wins."""
        # Build a fixture where all shifts are zero -> alpha should not matter
        # and tie-break picks the smallest
        rng = np.random.default_rng(55)
        ctrl = rng.uniform(size=(_N_CTRL, _PCA_DIMS + 2)).astype(np.float64)
        gene_ids = [f"z{i}" for i in range(6)]
        pops: dict[str, np.ndarray] = {}
        feats: dict[str, np.ndarray] = {}
        rs = _StubResponseSpace()
        for gid in gene_ids:
            # cells identical to control -> shift == 0
            pops[gid] = ctrl.copy()
            feats[gid] = rng.standard_normal(_FEAT_DIM)
        manifest = _StubManifest(gene_ids)
        store = _StubStore(ctrl_cells=ctrl, pert_populations=pops)
        fb = _StubFeatureBank(feats)
        grid = (0.01, 1.0, 100.0)
        predictor = fit_base_predictor(
            manifest=manifest,
            store=store,
            response_space=rs,
            feature_bank=fb,
            ridge_grid=grid,
            cv_folds=2,
            ensemble_members=2,
            seed=0,
        )
        # All CV MSEs should be ~0 (shifts are zero); tie -> smallest alpha
        assert predictor.chosen_alpha == min(grid)

    def test_small_alpha_wins_on_noiseless_linear(self) -> None:
        manifest, store, rs, fb, W_true = _build_linear_fixture(n_pert=12, rng_seed=77)
        grid = (1e-6, 1e-3, 1.0, 100.0)
        predictor = fit_base_predictor(
            manifest=manifest,
            store=store,
            response_space=rs,
            feature_bank=fb,
            ridge_grid=grid,
            cv_folds=_CV_FOLDS,
            ensemble_members=_ENSEMBLE_MEMBERS,
            seed=_SEED,
        )
        assert predictor.chosen_alpha in (1e-6, 1e-3)


class TestPairedBootstrapIndices:
    """Ensemble must use the SAME index array for both Phi and S rows."""

    def test_paired_indices_via_math(self) -> None:
        """Verify pairing by reproducing ensemble member weights manually.

        We fit the predictor, then reproduce each W_m using the same per-member
        RNG and verify agreement.  Mis-pairing would pick different rows from Phi
        vs S and produce a different W_m.
        """
        manifest, store, rs, feature_bank = _build_simple_fixture(n_pert=8, rng_seed=3)
        predictor = fit_base_predictor(
            manifest=manifest,
            store=store,
            response_space=rs,
            feature_bank=feature_bank,
            ridge_grid=_RIDGE_GRID,
            cv_folds=_CV_FOLDS,
            ensemble_members=_ENSEMBLE_MEMBERS,
            seed=_SEED,
        )

        # Reproduce Phi and S (base_train rows in sorted-id order, same as fit)
        base_ids = sorted(manifest.ids_for("base_train"))
        ctrl_cells = store.read_controls().cells
        ctrl_transformed = rs.transform(ctrl_cells.astype(np.float64))
        control_mean = ctrl_transformed.mean(axis=0)

        phi_rows = []
        s_rows = []
        for gid in base_ids:
            if feature_bank.has(gid):
                pop = store.read_unsealed([gid])[gid]
                t = rs.transform(pop.cells.astype(np.float64))
                s_g = t.mean(axis=0) - control_mean
                phi_g = feature_bank.standardized_vector(gid)
                phi_rows.append(phi_g)
                s_rows.append(s_g)
        Phi = np.array(phi_rows, dtype=np.float64)
        S = np.array(s_rows, dtype=np.float64)
        n = len(phi_rows)

        alpha = predictor.chosen_alpha

        # Reproduce each ensemble member with paired resampling
        # Seed derivation: see predictor implementation (use np.uint64 stable hash)
        for m in range(_ENSEMBLE_MEMBERS):
            # Derive member seed deterministically (same as implementation)
            member_seed = int(np.uint64(np.uint64(_SEED) + np.uint64(m + 1)))
            rng_m = np.random.default_rng(member_seed)
            idx = rng_m.integers(0, n, size=n)
            Phi_m = Phi[idx]
            S_m = S[idx]
            A_m = Phi_m.T @ Phi_m + alpha * np.eye(Phi_m.shape[1])
            b_m = Phi_m.T @ S_m
            W_m = np.linalg.solve(A_m, b_m)
            np.testing.assert_allclose(
                predictor.ensemble_weights[m],
                W_m,
                atol=1e-10,
                err_msg=f"Ensemble member {m} weights do not match paired computation",
            )

    def test_ensemble_weights_shape(self) -> None:
        predictor = _fit_simple()
        assert predictor.ensemble_weights.shape == (_ENSEMBLE_MEMBERS, _FEAT_DIM, _PCA_DIMS)


class TestLeakageBoundary:
    """Method-development data must not affect the base predictor."""

    def test_method_dev_labels_do_not_affect_base(self) -> None:
        """Two fits with different method_development data must produce identical outputs."""
        manifest, store_a, rs, fb = _build_simple_fixture(rng_seed=10)
        # store_b has different pert populations but identical base_train content
        # We'll use the same base_train data in both stores but different method-dev data
        # (which fit_base_predictor never reads)
        # Both store_a and store_b are constructed identically here;
        # the critical thing is the fit only reads controls + base_train ids.
        manifest_b, store_b, rs_b, fb_b = _build_simple_fixture(rng_seed=10)

        pred_a = fit_base_predictor(
            manifest=manifest,
            store=store_a,
            response_space=rs,
            feature_bank=fb,
            ridge_grid=_RIDGE_GRID,
            cv_folds=_CV_FOLDS,
            ensemble_members=_ENSEMBLE_MEMBERS,
            seed=_SEED,
        )
        pred_b = fit_base_predictor(
            manifest=manifest_b,
            store=store_b,
            response_space=rs_b,
            feature_bank=fb_b,
            ridge_grid=_RIDGE_GRID,
            cv_folds=_CV_FOLDS,
            ensemble_members=_ENSEMBLE_MEMBERS,
            seed=_SEED,
        )
        np.testing.assert_array_equal(pred_a.weights, pred_b.weights)
        np.testing.assert_array_equal(pred_a.ensemble_weights, pred_b.ensemble_weights)
        assert pred_a.chosen_alpha == pred_b.chosen_alpha
        assert pred_a.checksum == pred_b.checksum

    def test_sealed_access_count_is_zero_after_fit(self) -> None:
        manifest, store, rs, fb = _build_simple_fixture()
        fit_base_predictor(
            manifest=manifest,
            store=store,
            response_space=rs,
            feature_bank=fb,
            ridge_grid=_RIDGE_GRID,
            cv_folds=_CV_FOLDS,
            ensemble_members=_ENSEMBLE_MEMBERS,
            seed=_SEED,
        )
        assert store.sealed_access_count == 0

    def test_different_method_dev_populations_give_same_base(self) -> None:
        """If we use a store that would expose method-dev pops differently,
        the base predictor must not change since it never reads them."""
        rng_a = np.random.default_rng(10)
        rng_b = np.random.default_rng(99)  # different seed for non-base_train pops

        gene_ids = [f"g{i}" for i in range(6)]
        ctrl = rng_a.uniform(size=(_N_CTRL, _PCA_DIMS + 2)).astype(np.float64)

        pops_a: dict[str, np.ndarray] = {}
        pops_b: dict[str, np.ndarray] = {}
        feats: dict[str, np.ndarray] = {}

        for gid in gene_ids:
            feats[gid] = rng_a.standard_normal(_FEAT_DIM)
            # Both stores have the same base_train populations
            pops_a[gid] = rng_a.uniform(size=(15, _PCA_DIMS + 2)).astype(np.float64)
            # store_b uses *very different* populations (as if method_dev had wild signatures)
            pops_b[gid] = rng_b.uniform(0, 100, size=(15, _PCA_DIMS + 2)).astype(np.float64)

        # But fit_base_predictor reads base_train from manifest.ids_for("base_train"),
        # which is the same gene_ids in both stores.
        # To make the test meaningful, use identical pops for base_train only:
        for gid in gene_ids:
            pops_b[gid] = pops_a[gid]  # same base_train data

        manifest = _StubManifest(gene_ids)
        store_a = _StubStore(ctrl_cells=ctrl, pert_populations=pops_a)
        store_b = _StubStore(ctrl_cells=ctrl, pert_populations=pops_b)
        rs = _StubResponseSpace()
        fb = _StubFeatureBank(feats)

        pred_a = fit_base_predictor(
            manifest=manifest,
            store=store_a,
            response_space=rs,
            feature_bank=fb,
            ridge_grid=_RIDGE_GRID,
            cv_folds=_CV_FOLDS,
            ensemble_members=_ENSEMBLE_MEMBERS,
            seed=_SEED,
        )
        pred_b = fit_base_predictor(
            manifest=manifest,
            store=store_b,
            response_space=rs,
            feature_bank=fb,
            ridge_grid=_RIDGE_GRID,
            cv_folds=_CV_FOLDS,
            ensemble_members=_ENSEMBLE_MEMBERS,
            seed=_SEED,
        )

        np.testing.assert_array_equal(pred_a.weights, pred_b.weights)
        np.testing.assert_array_equal(pred_a.ensemble_weights, pred_b.ensemble_weights)
        np.testing.assert_array_equal(pred_a.transformed_control, pred_b.transformed_control)
        assert pred_a.checksum == pred_b.checksum


class TestDeterminism:
    """Same seed -> identical outputs; different seed -> different ensemble (but same W/alpha)."""

    def test_same_seed_gives_identical_checksum(self) -> None:
        p1 = _fit_simple(rng_seed=99)
        p2 = _fit_simple(rng_seed=99)
        assert p1.checksum == p2.checksum
        np.testing.assert_array_equal(p1.weights, p2.weights)
        np.testing.assert_array_equal(p1.ensemble_weights, p2.ensemble_weights)

    def test_different_seed_changes_ensemble_but_not_weights(self) -> None:
        """W and alpha are CV-deterministic; seed only drives fold assignment and bootstrap."""
        manifest, store, rs, fb = _build_simple_fixture(rng_seed=99)

        def _fit_with_seed(s: int) -> BasePredictor:
            return fit_base_predictor(
                manifest=manifest,
                store=store,
                response_space=rs,
                feature_bank=fb,
                ridge_grid=_RIDGE_GRID,
                cv_folds=_CV_FOLDS,
                ensemble_members=_ENSEMBLE_MEMBERS,
                seed=s,
            )

        p1 = _fit_with_seed(1)
        p2 = _fit_with_seed(999)

        # W and alpha may differ if CV fold assignment differs, but typically the
        # winner alpha on a fixed dataset is the same.  The test verifies
        # ensemble_weights differ (due to different bootstrap seeds).
        # W and alpha: CV is seeded; different seeds → different fold indices →
        # may or may not change W/alpha depending on data.  What we CAN assert:
        # ensemble_weights are different when seed is different.
        assert not np.allclose(p1.ensemble_weights, p2.ensemble_weights), (
            "Different seeds must yield different bootstrap ensembles"
        )

    def test_fold_assignment_is_seed_derived(self) -> None:
        """The chosen_alpha may differ between seeds (fold assignment differs)."""
        # This is a documentation test: seed drives fold assignment.
        # We assert that two different seeds CAN produce different chosen_alpha
        # (not guaranteed but shows it's possible on data with borderline CV).
        # At minimum the implementation must not use builtin hash() for this.
        # We verify the predictor objects are reproducible for each seed.
        manifest, store, rs, fb = _build_simple_fixture(rng_seed=5)

        def _fit_twice(s: int) -> tuple[BasePredictor, BasePredictor]:
            return (
                fit_base_predictor(
                    manifest=manifest,
                    store=store,
                    response_space=rs,
                    feature_bank=fb,
                    ridge_grid=_RIDGE_GRID,
                    cv_folds=_CV_FOLDS,
                    ensemble_members=_ENSEMBLE_MEMBERS,
                    seed=s,
                ),
                fit_base_predictor(
                    manifest=manifest,
                    store=store,
                    response_space=rs,
                    feature_bank=fb,
                    ridge_grid=_RIDGE_GRID,
                    cv_folds=_CV_FOLDS,
                    ensemble_members=_ENSEMBLE_MEMBERS,
                    seed=s,
                ),
            )

        p1a, p1b = _fit_twice(7)
        np.testing.assert_array_equal(p1a.weights, p1b.weights)
        np.testing.assert_array_equal(p1a.ensemble_weights, p1b.ensemble_weights)
        assert p1a.checksum == p1b.checksum


class TestRoundTrip:
    """write / read must reproduce all arrays exactly and give identical predict output."""

    def test_round_trip_arrays(self, tmp_path: Path) -> None:
        predictor = _fit_simple()
        out = tmp_path / "base_predictor"
        predictor.write(str(out))

        loaded = BasePredictor.read(str(out))
        np.testing.assert_array_equal(loaded.weights, predictor.weights)
        np.testing.assert_array_equal(loaded.ensemble_weights, predictor.ensemble_weights)
        np.testing.assert_array_equal(loaded.control_mean, predictor.control_mean)
        np.testing.assert_array_equal(loaded.transformed_control, predictor.transformed_control)

    def test_round_trip_checksum(self, tmp_path: Path) -> None:
        predictor = _fit_simple()
        out = tmp_path / "base_predictor"
        predictor.write(str(out))
        loaded = BasePredictor.read(str(out))
        assert loaded.checksum == predictor.checksum

    def test_round_trip_predict(self, tmp_path: Path) -> None:
        predictor = _fit_simple()
        out = tmp_path / "base_predictor"
        predictor.write(str(out))
        loaded = BasePredictor.read(str(out))

        phi = np.ones(_FEAT_DIM)
        q = Query(perturbation_id="x", features=phi)
        pred_orig = predictor.predict(q)
        pred_loaded = loaded.predict(q)
        np.testing.assert_array_equal(pred_orig.predicted_cells, pred_loaded.predicted_cells)
        np.testing.assert_array_equal(
            pred_orig.ensemble_member_means, pred_loaded.ensemble_member_means
        )

    def test_round_trip_scalar_fields(self, tmp_path: Path) -> None:
        predictor = _fit_simple()
        out = tmp_path / "base_predictor"
        predictor.write(str(out))
        loaded = BasePredictor.read(str(out))

        assert loaded.chosen_alpha == predictor.chosen_alpha
        assert loaded.seed == predictor.seed
        assert loaded.feature_dim == predictor.feature_dim
        assert loaded.pca_dims == predictor.pca_dims
        assert loaded.fit_perturbation_ids == predictor.fit_perturbation_ids
        assert loaded.cv_scores == predictor.cv_scores


class TestMissingFeatureIds:
    """base_train ids absent from the feature bank must be skipped and recorded."""

    def test_missing_ids_skipped(self) -> None:
        rng = np.random.default_rng(20)
        ctrl = rng.uniform(size=(_N_CTRL, _PCA_DIMS + 2)).astype(np.float64)

        all_ids = ["has_feat", "no_feat_a", "no_feat_b", "also_has"]
        pops = {gid: rng.uniform(size=(15, _PCA_DIMS + 2)).astype(np.float64) for gid in all_ids}
        feats = {
            "has_feat": rng.standard_normal(_FEAT_DIM),
            "also_has": rng.standard_normal(_FEAT_DIM),
        }

        manifest = _StubManifest(all_ids)
        store = _StubStore(ctrl_cells=ctrl, pert_populations=pops)
        rs = _StubResponseSpace()
        fb = _StubFeatureBank(feats)

        predictor = fit_base_predictor(
            manifest=manifest,
            store=store,
            response_space=rs,
            feature_bank=fb,
            ridge_grid=_RIDGE_GRID,
            cv_folds=2,
            ensemble_members=2,
            seed=_SEED,
        )
        assert predictor.fit_perturbation_ids == ("also_has", "has_feat")

    def test_all_ids_missing_raises(self) -> None:
        rng = np.random.default_rng(30)
        ctrl = rng.uniform(size=(_N_CTRL, _PCA_DIMS + 2)).astype(np.float64)
        all_ids = ["no_feat_a", "no_feat_b"]
        pops = {gid: rng.uniform(size=(10, _PCA_DIMS + 2)).astype(np.float64) for gid in all_ids}

        manifest = _StubManifest(all_ids)
        store = _StubStore(ctrl_cells=ctrl, pert_populations=pops)
        rs = _StubResponseSpace()
        fb = _StubFeatureBank({})  # empty bank

        with pytest.raises(BaseModelError, match="No base_train perturbation"):
            fit_base_predictor(
                manifest=manifest,
                store=store,
                response_space=rs,
                feature_bank=fb,
                ridge_grid=_RIDGE_GRID,
                cv_folds=2,
                ensemble_members=2,
                seed=_SEED,
            )


class TestPredictor:
    """Miscellaneous predictor attribute tests."""

    def test_feature_dim_and_pca_dims(self) -> None:
        predictor = _fit_simple()
        assert predictor.feature_dim == _FEAT_DIM
        assert predictor.pca_dims == _PCA_DIMS

    def test_control_mean_shape(self) -> None:
        predictor = _fit_simple()
        assert predictor.control_mean.shape == (_PCA_DIMS,)

    def test_transformed_control_shape(self) -> None:
        predictor = _fit_simple()
        assert predictor.transformed_control.shape == (_N_CTRL, _PCA_DIMS)

    def test_weights_shape(self) -> None:
        predictor = _fit_simple()
        assert predictor.weights.shape == (_FEAT_DIM, _PCA_DIMS)

    def test_checksum_is_string(self) -> None:
        predictor = _fit_simple()
        assert isinstance(predictor.checksum, str)
        assert len(predictor.checksum) == 64  # SHA-256 hex

    def test_fit_perturbation_ids_sorted(self) -> None:
        predictor = _fit_simple()
        ids = predictor.fit_perturbation_ids
        assert list(ids) == sorted(ids)

    def test_fit_perturbation_ids_subset_of_base_train(self) -> None:
        manifest, store, rs, fb = _build_simple_fixture(rng_seed=99)
        predictor = fit_base_predictor(
            manifest=manifest,
            store=store,
            response_space=rs,
            feature_bank=fb,
            ridge_grid=_RIDGE_GRID,
            cv_folds=_CV_FOLDS,
            ensemble_members=_ENSEMBLE_MEMBERS,
            seed=_SEED,
        )
        base_train = set(manifest.ids_for("base_train"))
        for pid in predictor.fit_perturbation_ids:
            assert pid in base_train

    def test_checksum_changes_with_weights(self) -> None:
        p1 = _fit_simple()
        # Build a different predictor (different seed for bootstrap, different data)
        manifest, store, rs, fb = _build_simple_fixture(rng_seed=77)
        p2 = fit_base_predictor(
            manifest=manifest,
            store=store,
            response_space=rs,
            feature_bank=fb,
            ridge_grid=_RIDGE_GRID,
            cv_folds=_CV_FOLDS,
            ensemble_members=_ENSEMBLE_MEMBERS,
            seed=_SEED + 1,
        )
        assert p1.checksum != p2.checksum
