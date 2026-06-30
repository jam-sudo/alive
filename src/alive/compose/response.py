"""Training-role-only response space for COMPOSE Phase 2a (Task 2a-3).

This module fits a PCA response space used by later Phase-2a tasks (per-gene
factor :math:`\\delta_g`, pair shift and epistasis residual :math:`\\epsilon`).
Its single hard guarantee is *no preprocessing leakage* (plan §2.1 / §2.2):

The fitted artifact is a deterministic function of the **control** and
**eligible-single** rows of ``X`` only. Double cells (including calibration
doubles) and any sealed rows are never read during fitting; they are projected
only after the space is fixed. Consequently, mutating sealed or double rows
leaves the complete response artifact byte-identical.

Fitting order (exactly as registered in the task brief):

1. validate all indices and disjointness;
2. ``fit_idx = control_idx ∪ eligible_single_idx``;
3. positive-library-size median computed from ``X[fit_idx]`` only, never full X;
4. ``normalize_total`` to that frozen scalar, then ``log1p``;
5. select HVGs from normalized **control** cells only, deterministic tie-break
   by ascending gene index;
6. fit PCA on the normalized ``X[fit_idx][:, hvg_idx]``;
7. store fit indices only as a hash + counts, never raw barcodes in reports;
8. project calibration doubles only after the space is fixed.

Sparse safety: ``X`` may be a SciPy sparse matrix; only bounded row subsets are
densified. The full matrix is never materialised.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
from numpy.typing import NDArray
from scipy import sparse
from sklearn.decomposition import PCA

from alive.provenance import sha256_bytes, sha256_json

RESPONSE_SPACE_ALGORITHM = "compose_response_pca"
RESPONSE_SPACE_VERSION = "2a.1"

#: Frozen, registered transform identity (config ``response_space.transform``).
RESPONSE_TRANSFORM = ("normalize_total_median", "log1p")


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResponseSpace:
    """A frozen, leakage-safe PCA response space.

    The artifact stores only fitted state plus fit-index provenance (a hash and
    counts, never raw cell indices). The ``checksum`` is a self-excluding
    SHA-256 over the canonical artifact payload; it changes if and only if a
    fitted component or a fit-input statistic changes.

    Attributes
    ----------
    median_library : float
        Frozen median positive library size over the fit rows, used as the
        ``normalize_total`` target.
    hvg_idx : numpy.ndarray
        Sorted gene indices of the selected highly variable genes (selected on
        normalized control cells only).
    pca_components : numpy.ndarray
        PCA components, shape ``(pca_dim, n_hvg)``.
    pca_mean : numpy.ndarray
        Per-HVG mean removed before projection, shape ``(n_hvg,)``.
    pca_explained_variance : numpy.ndarray
        Explained variance per component, shape ``(pca_dim,)``.
    n_hvg : int
        Number of selected HVGs.
    pca_dim : int
        Number of retained principal components.
    seed : int
        Seed used for the (deterministic) PCA solver.
    n_control : int
        Number of control fit cells.
    n_eligible_single : int
        Number of eligible-single fit cells.
    fit_index_hash : str
        SHA-256 over the canonical (sorted) fit-index membership. Records *which*
        rows were used without storing raw barcodes in reports.
    checksum : str
        Self-excluding SHA-256 over the full artifact payload.
    """

    median_library: float
    hvg_idx: NDArray[np.intp]
    pca_components: NDArray[np.float64]
    pca_mean: NDArray[np.float64]
    pca_explained_variance: NDArray[np.float64]
    n_hvg: int
    pca_dim: int
    seed: int
    n_control: int
    n_eligible_single: int
    fit_index_hash: str
    checksum: str = field(default="")

    # -- projection -------------------------------------------------------

    def project(self, X: sparse.spmatrix | NDArray, idx: NDArray) -> NDArray[np.float64]:
        """Project the rows ``X[idx]`` into the fixed PCA response space.

        The same frozen transform (normalize to ``median_library`` + ``log1p``)
        and PCA basis are applied. Only the bounded ``X[idx]`` subset is
        densified.

        Parameters
        ----------
        X : scipy.sparse matrix or numpy.ndarray
            The full expression matrix (raw counts). Never densified globally.
        idx : numpy.ndarray
            Row indices to project (e.g. calibration doubles). May be empty.

        Returns
        -------
        numpy.ndarray
            Projected coordinates, shape ``(len(idx), pca_dim)``.
        """
        idx = _as_index_array(idx, name="idx")
        if idx.size == 0:
            return np.empty((0, self.pca_dim), dtype=np.float64)
        _check_in_range(idx, X.shape[0], name="idx")
        sub = _normalize_log1p(_dense_rows(X, idx), self.median_library)
        sub = sub[:, self.hvg_idx]
        return (sub - self.pca_mean) @ self.pca_components.T

    def mean_shift(self, X: sparse.spmatrix | NDArray, role_idx: NDArray) -> NDArray[np.float64]:
        """Population mean shift of ``role_idx`` relative to the control mean.

        Both means are taken in the fixed PCA response space, so the returned
        vector is the per-coordinate :math:`\\delta` used by later tasks.

        Parameters
        ----------
        X : scipy.sparse matrix or numpy.ndarray
            The full expression matrix.
        role_idx : numpy.ndarray
            Row indices of the perturbation/pair population.

        Returns
        -------
        numpy.ndarray
            Mean shift, shape ``(pca_dim,)``.
        """
        role_mean = self.project(X, role_idx).mean(axis=0)
        ctrl_mean = self._control_mean
        return role_mean - ctrl_mean

    @staticmethod
    def epsilon(
        pair_shift: NDArray[np.float64],
        delta_g: NDArray[np.float64],
        delta_h: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        """Epistasis residual :math:`\\epsilon = \\delta_{gh} - \\delta_g - \\delta_h`.

        Parameters
        ----------
        pair_shift : numpy.ndarray
            Pair (double) mean shift in PCA space.
        delta_g, delta_h : numpy.ndarray
            Single-gene mean shifts in PCA space.

        Returns
        -------
        numpy.ndarray
            The non-additive residual, same shape as ``pair_shift``.
        """
        return np.asarray(pair_shift) - np.asarray(delta_g) - np.asarray(delta_h)

    # -- provenance -------------------------------------------------------

    def _payload(self) -> dict:
        """Canonical, JSON-serialisable artifact payload (checksum input)."""
        return {
            "algorithm": RESPONSE_SPACE_ALGORITHM,
            "version": RESPONSE_SPACE_VERSION,
            "transform": list(RESPONSE_TRANSFORM),
            "median_library": _round_float(self.median_library),
            "hvg_idx": [int(i) for i in self.hvg_idx],
            "pca_components": _round_array(self.pca_components),
            "pca_mean": _round_array(self.pca_mean),
            "pca_explained_variance": _round_array(self.pca_explained_variance),
            "n_hvg": int(self.n_hvg),
            "pca_dim": int(self.pca_dim),
            "seed": int(self.seed),
            "n_control": int(self.n_control),
            "n_eligible_single": int(self.n_eligible_single),
            "n_fit": int(self.n_control) + int(self.n_eligible_single),
            "fit_index_hash": self.fit_index_hash,
        }

    def artifact_bytes(self) -> bytes:
        """Canonical bytes of the artifact payload (excludes the checksum)."""
        import json

        return json.dumps(self._payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")

    def report(self) -> dict:
        """Serialisable provenance report (counts + hashes, no raw indices).

        Returns
        -------
        dict
            Payload augmented with the self-excluding ``checksum``. Contains no
            raw cell indices/barcodes — only counts and the ``fit_index_hash``.
        """
        rep = self._payload()
        rep["checksum"] = self.checksum
        return rep

    # internal cache for the control mean used by ``mean_shift``
    _control_mean: NDArray[np.float64] = field(default=None, repr=False, compare=False)


def verify_response_artifact(
    space: ResponseSpace,
    control_mean: NDArray | list[float],
) -> tuple[ResponseSpace, NDArray[np.float64], str]:
    """Verify and snapshot the response space plus its frozen control mean."""
    actual_space_checksum = sha256_bytes(space.artifact_bytes())
    if actual_space_checksum != space.checksum:
        raise ValueError(
            "response-space checksum mismatch: fitted state changed after the artifact was sealed"
        )

    ctrl = np.array(control_mean, dtype=np.float64, copy=True)
    if ctrl.ndim != 1 or ctrl.shape != (space.pca_dim,):
        raise ValueError(f"control_mean must have shape ({space.pca_dim},), got {ctrl.shape}")
    if not np.all(np.isfinite(ctrl)):
        raise ValueError("control_mean contains non-finite values")

    def _readonly(value, *, dtype=None):
        copied = np.array(value, dtype=dtype, copy=True)
        copied.setflags(write=False)
        return copied

    snapshot = replace(
        space,
        hvg_idx=_readonly(space.hvg_idx, dtype=np.intp),
        pca_components=_readonly(space.pca_components, dtype=np.float64),
        pca_mean=_readonly(space.pca_mean, dtype=np.float64),
        pca_explained_variance=_readonly(space.pca_explained_variance, dtype=np.float64),
        _control_mean=None,
    )
    ctrl.setflags(write=False)
    combined_checksum = sha256_json(
        {
            "response_space_checksum": actual_space_checksum,
            "control_mean_float64_hex": [float(value).hex() for value in ctrl],
        }
    )
    return snapshot, ctrl, combined_checksum


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------


def fit_response_space(
    X: sparse.spmatrix | NDArray,
    *,
    control_idx: NDArray,
    eligible_single_idx: NDArray,
    n_hvg: int,
    pca_dim: int,
    seed: int,
) -> ResponseSpace:
    """Fit a leakage-safe PCA response space from training roles only.

    See the module docstring for the exact, registered fitting order. The fitted
    artifact is a deterministic function of the control and eligible-single rows
    only; sealed and double rows are never read here.

    Parameters
    ----------
    X : scipy.sparse matrix or numpy.ndarray
        Full raw-count expression matrix, shape ``(n_cells, n_genes)``. Never
        densified globally — only bounded fit-row subsets are materialised.
    control_idx : numpy.ndarray
        Row indices of control cells. Non-empty, in range, unique.
    eligible_single_idx : numpy.ndarray
        Row indices of eligible single-gene perturbation cells. In range, unique,
        and disjoint from ``control_idx``.
    n_hvg : int
        Number of highly variable genes to select (from normalized controls).
        Must satisfy ``0 < n_hvg <= n_genes``.
    pca_dim : int
        Number of principal components to retain. Must satisfy
        ``0 < pca_dim <= min(n_hvg, n_fit_cells)``.
    seed : int
        Seed for the deterministic randomized PCA solver.

    Returns
    -------
    ResponseSpace
        The frozen, checksum-sealed response space.

    Raises
    ------
    ValueError
        On invalid/duplicate/overlapping/out-of-range indices, on a zero
        positive-library fit cell, or on infeasible ``n_hvg`` / ``pca_dim``.
    """
    n_cells, n_genes = X.shape

    # (1) validate indices + disjointness ---------------------------------
    control_idx = _as_index_array(control_idx, name="control_idx")
    eligible_single_idx = _as_index_array(eligible_single_idx, name="eligible_single_idx")
    if control_idx.size == 0:
        raise ValueError("control_idx must be non-empty")
    _check_unique(control_idx, name="control_idx")
    _check_unique(eligible_single_idx, name="eligible_single_idx")
    _check_in_range(control_idx, n_cells, name="control_idx")
    _check_in_range(eligible_single_idx, n_cells, name="eligible_single_idx")
    if np.intersect1d(control_idx, eligible_single_idx).size > 0:
        raise ValueError("control_idx and eligible_single_idx must be disjoint")

    if not (0 < n_hvg <= n_genes):
        raise ValueError(f"n_hvg must satisfy 0 < n_hvg <= n_genes ({n_genes}), got {n_hvg}")

    # (2) fit_idx = control ∪ eligible_single (controls first, sorted within)
    control_sorted = np.sort(control_idx)
    single_sorted = np.sort(eligible_single_idx)
    fit_idx = np.concatenate([control_sorted, single_sorted])
    n_fit = fit_idx.size

    if not (0 < pca_dim <= min(n_hvg, n_fit)):
        raise ValueError(
            f"pca_dim must satisfy 0 < pca_dim <= min(n_hvg={n_hvg}, n_fit_cells={n_fit}), "
            f"got {pca_dim}"
        )

    # bounded densification: only the fit rows, never the full matrix
    fit_counts = _dense_rows(X, fit_idx)

    # (3) positive-library-size median from X[fit_idx] ONLY ---------------
    lib = fit_counts.sum(axis=1)
    if np.any(lib <= 0):
        raise ValueError("every fit cell must have a positive library size (zero library found)")
    median_library = float(np.median(lib))

    # (4) normalize_total to frozen scalar + log1p ------------------------
    fit_norm = _normalize_log1p(fit_counts, median_library)

    # (5) HVG selection from normalized CONTROL cells only ----------------
    n_control = control_sorted.size
    control_norm = fit_norm[:n_control]  # controls occupy the leading block
    hvg_idx = _select_hvg(control_norm, n_hvg)

    # (6) fit PCA on normalized X[fit_idx][:, hvg_idx] --------------------
    fit_hvg = fit_norm[:, hvg_idx]
    pca = PCA(n_components=pca_dim, svd_solver="full", random_state=seed)
    pca.fit(fit_hvg)
    components = np.ascontiguousarray(pca.components_, dtype=np.float64)
    pca_mean = np.ascontiguousarray(pca.mean_, dtype=np.float64)
    explained = np.ascontiguousarray(pca.explained_variance_, dtype=np.float64)
    _orient_components(components)

    # (7) fit indices stored only as hash + counts ------------------------
    fit_index_hash = sha256_json(
        {
            "control": [int(i) for i in control_sorted],
            "eligible_single": [int(i) for i in single_sorted],
        }
    )

    # control mean in PCA space, cached for mean_shift (control rows only)
    control_mean = ((control_norm[:, hvg_idx] - pca_mean) @ components.T).mean(axis=0)

    space = ResponseSpace(
        median_library=median_library,
        hvg_idx=hvg_idx,
        pca_components=components,
        pca_mean=pca_mean,
        pca_explained_variance=explained,
        n_hvg=int(n_hvg),
        pca_dim=int(pca_dim),
        seed=int(seed),
        n_control=int(n_control),
        n_eligible_single=int(single_sorted.size),
        fit_index_hash=fit_index_hash,
        _control_mean=control_mean,
    )
    checksum = sha256_bytes(space.artifact_bytes())
    return _with_checksum(space, checksum)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _with_checksum(space: ResponseSpace, checksum: str) -> ResponseSpace:
    """Return a copy of ``space`` with its ``checksum`` field set (frozen dc)."""
    object.__setattr__(space, "checksum", checksum)
    return space


def _as_index_array(idx: NDArray, *, name: str) -> NDArray[np.intp]:
    """Coerce ``idx`` to a 1-D integer index array."""
    arr = np.asarray(idx)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be 1-D, got shape {arr.shape}")
    if not np.issubdtype(arr.dtype, np.integer):
        if arr.size == 0:
            return arr.astype(np.intp)
        raise ValueError(f"{name} must be integer-typed, got dtype {arr.dtype}")
    return arr.astype(np.intp)


def _check_unique(idx: NDArray, *, name: str) -> None:
    """Raise if ``idx`` contains duplicates."""
    if np.unique(idx).size != idx.size:
        raise ValueError(f"{name} contains duplicate indices")


def _check_in_range(idx: NDArray, n: int, *, name: str) -> None:
    """Raise if any index is outside ``[0, n)``."""
    if idx.size and (idx.min() < 0 or idx.max() >= n):
        raise ValueError(f"{name} has out-of-range indices for n_cells={n}")


def _dense_rows(X: sparse.spmatrix | NDArray, idx: NDArray) -> NDArray[np.float64]:
    """Densify only the bounded row subset ``X[idx]`` (never the full matrix)."""
    if sparse.issparse(X):
        # Row-slicing a CSR/CSC returns a small sub-matrix; densify only that.
        sub = X[idx]
        dense = np.asarray(sub.todense(), dtype=np.float64)
    else:
        dense = np.asarray(X[idx], dtype=np.float64)
    return np.ascontiguousarray(dense)


def _normalize_log1p(counts: NDArray[np.float64], target: float) -> NDArray[np.float64]:
    """Normalize each row to a frozen library-size ``target``, then ``log1p``.

    Parameters
    ----------
    counts : numpy.ndarray
        Dense raw counts for a bounded set of rows.
    target : float
        Frozen median positive library size used as the normalization target.

    Returns
    -------
    numpy.ndarray
        ``log1p`` of the size-normalized counts.
    """
    lib = counts.sum(axis=1, keepdims=True)
    # rows are guaranteed positive-library at fit time; guard projection rows.
    safe = np.where(lib > 0, lib, 1.0)
    normed = counts * (target / safe)
    return np.log1p(normed)


def _select_hvg(control_norm: NDArray[np.float64], n_hvg: int) -> NDArray[np.intp]:
    """Select the top-``n_hvg`` variable genes on normalized control cells.

    Variance is computed per gene over control cells; ties are broken
    deterministically by ascending gene index. The returned indices are sorted
    ascending so the HVG block has a canonical gene order.

    Parameters
    ----------
    control_norm : numpy.ndarray
        Normalized control expression, shape ``(n_control, n_genes)``.
    n_hvg : int
        Number of HVGs to keep.

    Returns
    -------
    numpy.ndarray
        Sorted, unique HVG gene indices, shape ``(n_hvg,)``.
    """
    variance = control_norm.var(axis=0)
    # Sort by descending variance; ascending gene index breaks ties because
    # ``np.lexsort`` is stable and we negate variance for the primary key.
    order = np.lexsort((np.arange(variance.size), -variance))
    chosen = order[:n_hvg]
    return np.sort(chosen).astype(np.intp)


def _orient_components(components: NDArray[np.float64]) -> None:
    """Deterministically orient PCA components in place (sign convention).

    Each component's sign is fixed so its largest-magnitude loading is positive,
    removing the arbitrary sign degeneracy of the SVD across platforms.

    Parameters
    ----------
    components : numpy.ndarray
        PCA components, shape ``(pca_dim, n_hvg)``; modified in place.
    """
    for i in range(components.shape[0]):
        row = components[i]
        pivot = int(np.argmax(np.abs(row)))
        if row[pivot] < 0:
            components[i] = -row


def _round_array(arr: NDArray) -> list:
    """Round-to-12-decimal nested list for stable cross-platform checksums."""
    return np.round(np.asarray(arr, dtype=np.float64), 12).tolist()


def _round_float(value: float) -> float:
    """Round a scalar to 12 decimals for stable checksums."""
    return float(np.round(float(value), 12))
