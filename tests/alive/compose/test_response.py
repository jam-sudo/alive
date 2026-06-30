"""Leakage-boundary tests for the COMPOSE Phase-2a response space (Task 2a-3).

These tests encode the plan §2.1/§2.2 invariants as executable guarantees:

- the fitted response artifact depends ONLY on control + eligible-single rows;
- changing any sealed/double row leaves the complete artifact byte-identical
  (checked via the artifact checksum and the fitted-component bytes);
- changing controls or eligible singles DOES change the artifact;
- zero-library and insufficient-dimension inputs fail closed (raise);
- the sparse input is never globally densified.

All fixtures are tiny synthetic ``scipy.sparse`` count matrices.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import sparse

from alive.compose.response import ResponseSpace, fit_response_space, verify_response_artifact

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _counts(seed: int, n_cells: int, n_genes: int) -> np.ndarray:
    """Deterministic positive-ish integer count matrix (dense ndarray)."""
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 8, size=(n_cells, n_genes)).astype(np.float64)
    # guarantee every cell has a positive library size
    base[:, 0] += 1.0
    return base


def _toy(seed: int = 0):
    """Return (X_csr, control_idx, eligible_single_idx, double_idx, sealed_idx).

    Layout (12 cells, 6 genes):
      rows 0-3  : controls
      rows 4-7  : eligible singles
      rows 8-9  : calibration doubles (projected only, never fit)
      rows 10-11: sealed rows (must never touch the artifact)
    """
    X = sparse.csr_matrix(_counts(seed, 12, 6))
    control_idx = np.array([0, 1, 2, 3])
    eligible_single_idx = np.array([4, 5, 6, 7])
    double_idx = np.array([8, 9])
    sealed_idx = np.array([10, 11])
    return X, control_idx, eligible_single_idx, double_idx, sealed_idx


# ---------------------------------------------------------------------------
# Basic shape / determinism
# ---------------------------------------------------------------------------


def test_returns_response_space_and_is_deterministic():
    X, c, s, _, _ = _toy()
    a = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=7)
    b = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=7)
    assert isinstance(a, ResponseSpace)
    assert a.pca_dim == 2
    assert a.n_hvg == 4
    assert a.hvg_idx.shape == (4,)
    assert a.checksum == b.checksum
    # HVG indices selected from controls, deterministic and sorted-unique.
    assert list(a.hvg_idx) == sorted(set(a.hvg_idx.tolist()))


def test_projection_shape_and_post_fit_only():
    X, c, s, d, _ = _toy()
    space = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=1)
    proj = space.project(X, d)
    assert proj.shape == (len(d), 2)
    assert np.all(np.isfinite(proj))


# ---------------------------------------------------------------------------
# (a) changing ONLY sealed rows leaves the artifact byte-identical
# ---------------------------------------------------------------------------


def test_changing_sealed_rows_leaves_artifact_byte_identical():
    X, c, s, _, sealed = _toy()
    base = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=3)

    X2 = X.toarray()
    X2[sealed] = X2[sealed] * 1000.0 + 17.0  # arbitrary mutation of sealed rows only
    X2 = sparse.csr_matrix(X2)
    other = fit_response_space(X2, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=3)

    assert base.checksum == other.checksum
    assert base.artifact_bytes() == other.artifact_bytes()


def test_changing_double_rows_leaves_artifact_byte_identical():
    X, c, s, d, _ = _toy()
    base = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=3)

    X2 = X.toarray()
    X2[d] = X2[d] * 5.0 + 3.0  # mutate calibration doubles only
    X2 = sparse.csr_matrix(X2)
    other = fit_response_space(X2, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=3)

    assert base.checksum == other.checksum
    assert base.artifact_bytes() == other.artifact_bytes()


# ---------------------------------------------------------------------------
# (b) changing controls or eligible singles DOES change the artifact
# ---------------------------------------------------------------------------


def test_changing_controls_changes_artifact():
    X, c, s, _, _ = _toy()
    base = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=3)

    X2 = X.toarray()
    X2[c[0]] = X2[c[0]] * 7.0 + 11.0
    X2 = sparse.csr_matrix(X2)
    other = fit_response_space(X2, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=3)

    assert base.checksum != other.checksum


def test_changing_eligible_singles_changes_artifact():
    X, c, s, _, _ = _toy()
    base = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=3)

    X2 = X.toarray()
    X2[s[0]] = X2[s[0]] * 3.0 + 2.0
    X2 = sparse.csr_matrix(X2)
    other = fit_response_space(X2, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=3)

    assert base.checksum != other.checksum


# ---------------------------------------------------------------------------
# (c) fail-closed: zero library and insufficient dimensions
# ---------------------------------------------------------------------------


def test_zero_library_fit_cell_raises():
    X = _counts(0, 12, 6)
    X[4, :] = 0.0  # an eligible-single cell with empty library
    Xs = sparse.csr_matrix(X)
    c = np.array([0, 1, 2, 3])
    s = np.array([4, 5, 6, 7])
    with pytest.raises(ValueError, match="library"):
        fit_response_space(Xs, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)


def test_n_hvg_exceeds_n_genes_raises():
    X, c, s, _, _ = _toy()
    with pytest.raises(ValueError, match="n_hvg"):
        fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=99, pca_dim=2, seed=0)


def test_pca_dim_exceeds_n_hvg_raises():
    X, c, s, _, _ = _toy()
    with pytest.raises(ValueError, match="pca_dim"):
        fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=3, pca_dim=4, seed=0)


def test_pca_dim_exceeds_n_fit_cells_raises():
    # 4 controls + 1 single = 5 fit cells; pca_dim 6 is infeasible.
    X, _, _, _, _ = _toy()
    c = np.array([0, 1, 2, 3])
    s = np.array([4])
    with pytest.raises(ValueError, match="pca_dim"):
        fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=5, pca_dim=6, seed=0)


# ---------------------------------------------------------------------------
# index validation / disjointness
# ---------------------------------------------------------------------------


def test_overlapping_control_and_single_idx_raises():
    X, _, _, _, _ = _toy()
    c = np.array([0, 1, 2, 3])
    s = np.array([3, 4, 5, 6])  # 3 overlaps control
    with pytest.raises(ValueError, match="disjoint"):
        fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)


def test_out_of_range_index_raises():
    X, _, s, _, _ = _toy()
    c = np.array([0, 1, 2, 99])  # 99 out of range
    with pytest.raises((ValueError, IndexError)):
        fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)


def test_empty_control_idx_raises():
    X, _, s, _, _ = _toy()
    empty = np.array([], dtype=int)
    with pytest.raises(ValueError):
        fit_response_space(X, control_idx=empty, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)


def test_duplicate_index_raises():
    X, _, s, _, _ = _toy()
    c = np.array([0, 0, 1, 2])  # duplicate control index
    with pytest.raises(ValueError, match="duplicate"):
        fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)


# ---------------------------------------------------------------------------
# (d) sparse input is never globally densified
# ---------------------------------------------------------------------------


def test_sparse_input_never_globally_densified():
    """A sparse matrix whose ``.toarray`` raises proves we never densify the whole X.

    We wrap a real CSR matrix and make full materialisation explode; only
    bounded row-slicing (which returns small sub-matrices) is allowed.
    """
    X, c, s, _, _ = _toy()
    full_shape = X.shape

    class NoGlobalDensify(sparse.csr_matrix):
        # Bounded row slices are allowed to densify (they are small
        # sub-matrices); densifying the *full* matrix is forbidden.
        def toarray(self, *args, **kwargs):  # noqa: D102
            if self.shape == full_shape:
                raise AssertionError("global densification of full X is forbidden")
            return super().toarray(*args, **kwargs)

        def todense(self, *args, **kwargs):  # noqa: D102
            if self.shape == full_shape:
                raise AssertionError("global densification of full X is forbidden")
            return super().todense(*args, **kwargs)

    guarded = NoGlobalDensify(X)
    space = fit_response_space(
        guarded, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0
    )
    assert isinstance(space, ResponseSpace)


def test_accepts_dense_ndarray_input():
    """Dense ndarray input is also accepted (bounded fixtures)."""
    X = _counts(0, 12, 6)
    c = np.array([0, 1, 2, 3])
    s = np.array([4, 5, 6, 7])
    space = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)
    assert isinstance(space, ResponseSpace)


# ---------------------------------------------------------------------------
# provenance: fit indices stored only as hashes/counts, not raw barcodes
# ---------------------------------------------------------------------------


def test_artifact_records_counts_and_hashes_not_raw_indices():
    X, c, s, _, _ = _toy()
    space = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)
    rep = space.report()
    assert rep["n_control"] == len(c)
    assert rep["n_eligible_single"] == len(s)
    assert rep["n_fit"] == len(c) + len(s)
    assert isinstance(rep["fit_index_hash"], str) and len(rep["fit_index_hash"]) == 64
    assert isinstance(rep["checksum"], str) and len(rep["checksum"]) == 64
    # no raw cell indices/barcodes anywhere in the serialised report
    flat = repr(rep)
    assert "control_idx" not in rep
    assert "eligible_single_idx" not in rep
    # the literal fit index list must not be leaked
    assert "[0, 1, 2, 3, 4, 5, 6, 7]" not in flat


def test_fit_index_hash_changes_with_index_membership():
    X, c, s, _, _ = _toy()
    a = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)
    # use a different but still-disjoint, in-range membership
    c2 = np.array([0, 1, 2, 9])
    s2 = np.array([4, 5, 6, 7])
    b = fit_response_space(X, control_idx=c2, eligible_single_idx=s2, n_hvg=4, pca_dim=2, seed=0)
    assert a.report()["fit_index_hash"] != b.report()["fit_index_hash"]


# ---------------------------------------------------------------------------
# helpers consumed by later tasks: mean_shift + epsilon (in PCA space)
# ---------------------------------------------------------------------------


def test_mean_shift_is_role_mean_minus_control_mean():
    X, c, s, d, _ = _toy()
    space = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)
    shift = space.mean_shift(X, d)
    ctrl_mean = space.project(X, c).mean(axis=0)
    role_mean = space.project(X, d).mean(axis=0)
    np.testing.assert_allclose(shift, role_mean - ctrl_mean)
    assert shift.shape == (2,)


def test_epsilon_is_pair_shift_minus_single_deltas():
    X, c, s, d, _ = _toy()
    space = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)
    # use two single-cell "roles" as delta_g and delta_h
    delta_g = space.mean_shift(X, np.array([s[0]]))
    delta_h = space.mean_shift(X, np.array([s[1]]))
    pair_shift = space.mean_shift(X, d)
    eps = space.epsilon(pair_shift, delta_g, delta_h)
    np.testing.assert_allclose(eps, pair_shift - delta_g - delta_h)
    assert eps.shape == (2,)


def test_verify_response_artifact_returns_immutable_snapshot():
    X, c, s, _, _ = _toy()
    space = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)
    control_mean = space.project(X, c).mean(axis=0)

    snapshot, frozen_control, checksum = verify_response_artifact(space, control_mean)

    assert len(checksum) == 64
    assert not snapshot.hvg_idx.flags.writeable
    assert not snapshot.pca_components.flags.writeable
    assert not snapshot.pca_mean.flags.writeable
    assert not snapshot.pca_explained_variance.flags.writeable
    assert not frozen_control.flags.writeable
    with pytest.raises(ValueError):
        frozen_control[0] = 0.0


def test_verify_response_artifact_rejects_tampered_space():
    X, c, s, _, _ = _toy()
    space = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)
    control_mean = space.project(X, c).mean(axis=0)
    space.pca_components[0, 0] += 1.0

    with pytest.raises(ValueError, match="checksum"):
        verify_response_artifact(space, control_mean)


def test_response_artifact_checksum_binds_control_mean():
    X, c, s, _, _ = _toy()
    space = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)
    control_mean = space.project(X, c).mean(axis=0)

    _, _, first = verify_response_artifact(space, control_mean)
    changed = control_mean.copy()
    changed[0] += 1e-13
    _, _, second = verify_response_artifact(space, changed)

    assert first != second


def test_verify_response_artifact_rejects_nonfinite_control_mean():
    X, c, s, _, _ = _toy()
    space = fit_response_space(X, control_idx=c, eligible_single_idx=s, n_hvg=4, pca_dim=2, seed=0)
    control_mean = space.project(X, c).mean(axis=0)
    control_mean[0] = np.nan

    with pytest.raises(ValueError, match="finite"):
        verify_response_artifact(space, control_mean)
