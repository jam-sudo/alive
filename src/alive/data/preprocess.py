"""Train-fitted transcriptomic response space (normalize -> HVG -> center -> PCA).

This module fits a *frozen* response-space transform on the leakage-safe fit set
(controls + ``base_train`` perturbation populations) and then applies it one
population at a time to any later split.  It is the substrate for ALL downstream
distance and model computation, so three properties are paramount:

1. **Leakage boundary.**  Every fitted statistic (HVG selection, centering means,
   PCA components) is computed from CONTROLS + ``base_train`` cells ONLY.  No
   ``method_development`` / ``conformal_calibration`` / ``sealed_evaluation`` cell
   ever contributes.  The fit obtains data exclusively via
   :meth:`~alive.data.outcome_store.ReplogleOutcomeStore.read_controls` and
   :meth:`~alive.data.outcome_store.ReplogleOutcomeStore.read_unsealed`; it never
   calls ``evaluate_sealed_once``.
2. **Determinism.**  Sufficient statistics accumulate in ``float64`` and the
   eigenvector sign convention (each component's largest-magnitude entry is made
   positive) removes sign ambiguity, so the fit and transform are byte-identical
   across runs, processes, and platforms.
3. **Bounded memory.**  The fit is a two-pass *streaming* accumulation over one
   population at a time; the full dataset is never densified.  Transform densifies
   only the single population passed by the caller.

Public API
----------
PreprocessError
    Raised for any preprocessing configuration or shape violation.
ResponseSpace
    Frozen fitted transform with ``transform``, ``checksum``, ``write``, ``read``.
fit_response_space(index, store, manifest, *, normalization, target_sum, hvg_count, pca_dims)
    Stream-fit a :class:`ResponseSpace` on controls + ``base_train`` cells.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from alive.provenance import sha256_json

if TYPE_CHECKING:
    from alive.data.manifest import SplitManifest
    from alive.data.outcome_store import OutcomeStore
    from alive.data.replogle import ReplogleIndex

# The single supported normalization identifier.
_SUPPORTED_NORMALIZATION = "library_size_10000_log1p"


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class PreprocessError(ValueError):
    """Raised for any preprocessing configuration or shape violation.

    Parameters
    ----------
    message : str
        Human-readable description of the failure.
    """


# ---------------------------------------------------------------------------
# Normalization (per cell, no fitting)
# ---------------------------------------------------------------------------


def _normalize_log1p(cells: np.ndarray, target_sum: float) -> np.ndarray:
    """Library-size normalize each cell row to *target_sum*, then ``log1p``.

    For a raw count row ``x`` with positive total, ``x_norm = x * target_sum /
    x.sum()``; rows whose total is zero are left as zeros (no division).  The
    result is then passed through ``numpy.log1p``.  All arithmetic is performed
    in ``float64`` for determinism.

    Parameters
    ----------
    cells : np.ndarray
        Dense ``(n_cells, n_genes)`` raw-count matrix for one population.
    target_sum : float
        Per-cell library size to normalize to (e.g. ``10000.0``).

    Returns
    -------
    np.ndarray
        ``float64`` ``(n_cells, n_genes)`` normalized log1p matrix.
    """
    x = np.asarray(cells, dtype=np.float64)
    sums = x.sum(axis=1, keepdims=True)
    # Guard zero-sum rows: leave them as zeros (np.where avoids div-by-zero).
    with np.errstate(divide="ignore", invalid="ignore"):
        scaled = np.where(sums > 0.0, x * (target_sum / sums), 0.0)
    return np.log1p(scaled)


# ---------------------------------------------------------------------------
# ResponseSpace — frozen fitted transform
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResponseSpace:
    """Frozen, fitted response-space transform.

    Apply :meth:`transform` to one population's raw count matrix to project it
    into the ``pca_dims``-dimensional response space.  All fitted arrays were
    derived from controls + ``base_train`` cells only.

    Parameters
    ----------
    normalization : str
        Normalisation strategy identifier (only ``"library_size_10000_log1p"``).
    target_sum : float
        Per-cell library size used during normalisation.
    selected_gene_indices : np.ndarray
        ``int`` positions of the selected HVGs into the full gene axis, SORTED
        ASCENDING.
    selected_gene_ids : tuple[str, ...]
        Gene identifiers for the selected HVGs, in the same order as
        :attr:`selected_gene_indices`.
    hvg_means : np.ndarray
        ``(hvg_count,)`` per-gene centering means on the normalized log1p data.
    components : np.ndarray
        ``(pca_dims, hvg_count)`` PCA loadings; rows are components, descending
        by eigenvalue, with the fixed sign convention applied.
    explained_variance : np.ndarray
        ``(pca_dims,)`` eigenvalues, descending.
    explained_variance_ratio : np.ndarray
        ``(pca_dims,)`` eigenvalue divided by the sum of ALL covariance
        eigenvalues.
    n_fit_cells : int
        Total number of cells used to fit (controls + base_train).
    fit_perturbation_ids : tuple[str, ...]
        The ``base_train`` perturbation ids used (sorted); controls are implied.
    n_genes_full : int
        Expected gene-axis width of inputs to :meth:`transform`.
    """

    normalization: str
    target_sum: float
    selected_gene_indices: np.ndarray
    selected_gene_ids: tuple[str, ...]
    hvg_means: np.ndarray
    components: np.ndarray
    explained_variance: np.ndarray
    explained_variance_ratio: np.ndarray
    n_fit_cells: int
    fit_perturbation_ids: tuple[str, ...]
    n_genes_full: int

    # ------------------------------------------------------------------
    # Transform
    # ------------------------------------------------------------------

    def transform(self, cells: np.ndarray) -> np.ndarray:
        """Project one population's raw counts into the response space.

        Steps: library-size normalize + ``log1p`` -> subset to
        :attr:`selected_gene_indices` -> subtract :attr:`hvg_means` -> matrix
        multiply by ``components.T``.  Only the passed population is densified
        (the caller is responsible for passing one population at a time).

        Parameters
        ----------
        cells : np.ndarray
            Dense ``(n_cells, n_genes_full)`` raw-count matrix.

        Returns
        -------
        np.ndarray
            ``float64`` ``(n_cells, pca_dims)`` response-space coordinates.

        Raises
        ------
        PreprocessError
            If ``cells.shape[1]`` does not equal :attr:`n_genes_full`.
        """
        arr = np.asarray(cells)
        if arr.ndim != 2 or arr.shape[1] != self.n_genes_full:
            raise PreprocessError(
                f"transform expects a (n_cells, {self.n_genes_full}) matrix; "
                f"got shape {arr.shape}.  The gene-axis width must match the "
                "matrix the response space was fitted on."
            )
        normed = _normalize_log1p(arr, self.target_sum)
        subset = normed[:, self.selected_gene_indices]
        centered = subset - self.hvg_means
        return centered @ self.components.T

    # ------------------------------------------------------------------
    # Checksum
    # ------------------------------------------------------------------

    @cached_property
    def checksum(self) -> str:
        """Stable SHA-256 over all fitted arrays and scalars (canonical JSON).

        The digest is computed over the canonical JSON of the normalization
        spec, target sum, selected indices/ids, centering means, PCA components,
        eigenvalues and ratios, fit-cell count, fit ids, and gene-axis width.
        Two response spaces fitted from identical inputs share the same checksum.

        Returns
        -------
        str
            Lowercase hex-encoded SHA-256 digest.
        """
        payload = {
            "normalization": self.normalization,
            "target_sum": repr(float(self.target_sum)),
            "selected_gene_indices": self.selected_gene_indices.astype(int).tolist(),
            "selected_gene_ids": list(self.selected_gene_ids),
            "hvg_means": self.hvg_means.astype(np.float64).tolist(),
            "components": self.components.astype(np.float64).tolist(),
            "explained_variance": self.explained_variance.astype(np.float64).tolist(),
            "explained_variance_ratio": self.explained_variance_ratio.astype(np.float64).tolist(),
            "n_fit_cells": int(self.n_fit_cells),
            "fit_perturbation_ids": list(self.fit_perturbation_ids),
            "n_genes_full": int(self.n_genes_full),
        }
        return sha256_json(payload)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def write(self, path: str | Path) -> None:
        """Write the response space to disk deterministically.

        Writes two files:

        - ``{path}.npz`` — uncompressed numpy archive of the fitted arrays
          (saved in ``float64`` / ``int64`` so the round trip is exact).
        - ``{path}.json`` — scalar metadata, gene ids, and the checksum.

        Parameters
        ----------
        path : str or Path
            Base path (without extension).  Parent directory must exist.
        """
        path = Path(path)
        np.savez(
            str(path) + ".npz",
            selected_gene_indices=self.selected_gene_indices.astype(np.int64),
            hvg_means=self.hvg_means.astype(np.float64),
            components=self.components.astype(np.float64),
            explained_variance=self.explained_variance.astype(np.float64),
            explained_variance_ratio=self.explained_variance_ratio.astype(np.float64),
        )
        meta = {
            "normalization": self.normalization,
            "target_sum": float(self.target_sum),
            "selected_gene_ids": list(self.selected_gene_ids),
            "n_fit_cells": int(self.n_fit_cells),
            "fit_perturbation_ids": list(self.fit_perturbation_ids),
            "n_genes_full": int(self.n_genes_full),
            "checksum": self.checksum,
        }
        path.with_suffix(".json").write_text(
            json.dumps(meta, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: str | Path) -> "ResponseSpace":
        """Reconstruct a :class:`ResponseSpace` from files written by :meth:`write`.

        Parameters
        ----------
        path : str or Path
            Base path (without extension) as passed to :meth:`write`.

        Returns
        -------
        ResponseSpace
            The reconstructed response space.  Its :attr:`checksum` is recomputed
            from content and must match the stored value.

        Raises
        ------
        PreprocessError
            If the stored checksum does not match the recomputed checksum.
        """
        path = Path(path)
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        npz = np.load(str(path) + ".npz")

        rs = cls(
            normalization=meta["normalization"],
            target_sum=float(meta["target_sum"]),
            selected_gene_indices=np.asarray(npz["selected_gene_indices"], dtype=int),
            selected_gene_ids=tuple(meta["selected_gene_ids"]),
            hvg_means=np.asarray(npz["hvg_means"], dtype=np.float64),
            components=np.asarray(npz["components"], dtype=np.float64),
            explained_variance=np.asarray(npz["explained_variance"], dtype=np.float64),
            explained_variance_ratio=np.asarray(npz["explained_variance_ratio"], dtype=np.float64),
            n_fit_cells=int(meta["n_fit_cells"]),
            fit_perturbation_ids=tuple(meta["fit_perturbation_ids"]),
            n_genes_full=int(meta["n_genes_full"]),
        )
        stored = meta["checksum"]
        if rs.checksum != stored:
            raise PreprocessError(
                f"ResponseSpace checksum mismatch: stored {stored!r} != recomputed "
                f"{rs.checksum!r}.  The serialised file may have been modified."
            )
        return rs


# ---------------------------------------------------------------------------
# Streaming fit
# ---------------------------------------------------------------------------


def fit_response_space(
    index: "ReplogleIndex",
    store: "OutcomeStore",
    manifest: "SplitManifest",
    *,
    normalization: str,
    target_sum: float,
    hvg_count: int,
    pca_dims: int,
) -> ResponseSpace:
    """Stream-fit a :class:`ResponseSpace` on controls + ``base_train`` cells.

    The fit set is gathered as ``store.read_controls()`` plus
    ``store.read_unsealed(manifest.ids_for("base_train"))`` — and nothing else.
    ``method_development`` / ``conformal_calibration`` / ``sealed_evaluation``
    cells never contribute to any fitted statistic.

    Two streaming passes accumulate ``float64`` sufficient statistics over one
    population at a time:

    1. **Pass A (HVG selection).**  For each fit population, normalize + log1p,
       and accumulate per-gene ``sum``, ``sumsq``, and the running cell count.
       Per-gene ``mean = sum/n`` and population variance
       ``var = sumsq/n - mean**2`` (tiny negatives from round-off clamped to 0).
       The top ``hvg_count`` genes by variance (descending; ties broken by
       ascending gene index) are selected and stored sorted ascending.
    2. **Pass B (centering + covariance).**  For each fit population, normalize +
       log1p, subset to the selected HVGs, and accumulate per-HVG ``sum``
       (-> ``hvg_means``) and the ``hvg_count x hvg_count`` Gram matrix
       ``sum(x x^T)``.  The centered population covariance is
       ``C = Gram/n - mean^T mean`` (i.e. ``(1/n) sum (x-mean)(x-mean)^T``).

    The covariance ``C`` is symmetric; its eigendecomposition
    (``numpy.linalg.eigh``) yields the PCA loadings.  The top ``pca_dims``
    eigenpairs (descending by eigenvalue) become the components; each component's
    largest-magnitude entry is forced positive for a deterministic sign.

    Parameters
    ----------
    index : ReplogleIndex
        Metadata index (provides ``gene_ids`` and ``n_genes``).
    store : OutcomeStore
        Sealed outcome store; only ``read_controls`` and ``read_unsealed`` are
        used.
    manifest : SplitManifest
        Split manifest; ``ids_for("base_train")`` defines the fit perturbations.
    normalization : str
        Must equal ``"library_size_10000_log1p"``.
    target_sum : float
        Per-cell library size to normalize to.
    hvg_count : int
        Number of highly-variable genes to select.
    pca_dims : int
        Number of PCA dimensions to retain.

    Returns
    -------
    ResponseSpace
        The frozen fitted transform.

    Raises
    ------
    PreprocessError
        If *normalization* is unsupported, the dataset has fewer than
        *hvg_count* genes, or *pca_dims* exceeds the number of selected HVGs.
    """
    if normalization != _SUPPORTED_NORMALIZATION:
        raise PreprocessError(
            f"Unsupported normalization {normalization!r}; only "
            f"{_SUPPORTED_NORMALIZATION!r} is supported."
        )

    n_genes = index.n_genes
    if hvg_count > n_genes:
        raise PreprocessError(
            f"hvg_count ({hvg_count}) exceeds the total number of genes ({n_genes}); "
            "cannot select more HVGs than exist."
        )

    base_train_ids = tuple(manifest.ids_for("base_train"))

    # ------------------------------------------------------------------
    # Pass A — per-gene sufficient statistics over the fit populations.
    # ------------------------------------------------------------------
    sum_g = np.zeros(n_genes, dtype=np.float64)
    sumsq_g = np.zeros(n_genes, dtype=np.float64)
    n_cells_total = 0

    for cells in _iter_fit_populations(store, base_train_ids):
        normed = _normalize_log1p(cells, target_sum)
        sum_g += normed.sum(axis=0)
        sumsq_g += np.square(normed).sum(axis=0)
        n_cells_total += normed.shape[0]

    if n_cells_total == 0:
        raise PreprocessError(
            "No fit cells were found (controls + base_train produced 0 cells); "
            "cannot fit a response space."
        )

    mean_g = sum_g / n_cells_total
    var_g = sumsq_g / n_cells_total - np.square(mean_g)
    # Clamp tiny negative variances from float round-off to exactly 0.
    var_g = np.where(var_g < 0.0, 0.0, var_g)

    # Top hvg_count by variance DESCENDING; ties -> ascending gene index.
    order = sorted(range(n_genes), key=lambda j: (-var_g[j], j))
    selected = sorted(order[:hvg_count])
    selected_gene_indices = np.asarray(selected, dtype=int)
    selected_gene_ids = tuple(index.gene_ids[i] for i in selected)
    n_hvg = len(selected)

    if pca_dims > n_hvg:
        raise PreprocessError(
            f"pca_dims ({pca_dims}) exceeds the number of selected HVGs ({n_hvg}); "
            "cannot retain more components than HVG dimensions."
        )

    # ------------------------------------------------------------------
    # Pass B — centering means + Gram matrix on the HVG subset.
    # ------------------------------------------------------------------
    hvg_sum = np.zeros(n_hvg, dtype=np.float64)
    gram = np.zeros((n_hvg, n_hvg), dtype=np.float64)

    for cells in _iter_fit_populations(store, base_train_ids):
        normed = _normalize_log1p(cells, target_sum)
        subset = normed[:, selected_gene_indices]
        hvg_sum += subset.sum(axis=0)
        gram += subset.T @ subset

    hvg_means = hvg_sum / n_cells_total
    # Centered population covariance: C = Gram/n - mean^T mean.
    cov = gram / n_cells_total - np.outer(hvg_means, hvg_means)
    # Symmetrise to remove any float asymmetry before eigh (determinism).
    cov = 0.5 * (cov + cov.T)

    # ------------------------------------------------------------------
    # PCA via deterministic symmetric eigendecomposition.
    # ------------------------------------------------------------------
    eigvals, eigvecs = np.linalg.eigh(cov)  # ascending eigenvalues
    # Descending order: reverse.
    order_desc = np.argsort(eigvals)[::-1]
    eigvals_desc = eigvals[order_desc]
    eigvecs_desc = eigvecs[:, order_desc]

    total_variance = float(eigvals.sum())
    top_vals = eigvals_desc[:pca_dims]
    top_vecs = eigvecs_desc[:, :pca_dims]  # columns are eigenvectors

    # Components as ROWS: shape (pca_dims, n_hvg).
    components = np.ascontiguousarray(top_vecs.T)
    # Sign convention: flip each row so its max-abs entry is positive.
    for r in range(components.shape[0]):
        row = components[r]
        max_abs_pos = int(np.argmax(np.abs(row)))
        if row[max_abs_pos] < 0.0:
            components[r] = -row

    explained_variance = np.ascontiguousarray(top_vals.astype(np.float64))
    if total_variance != 0.0:
        explained_variance_ratio = explained_variance / total_variance
    else:
        explained_variance_ratio = np.zeros_like(explained_variance)

    return ResponseSpace(
        normalization=normalization,
        target_sum=float(target_sum),
        selected_gene_indices=selected_gene_indices,
        selected_gene_ids=selected_gene_ids,
        hvg_means=hvg_means,
        components=components,
        explained_variance=explained_variance,
        explained_variance_ratio=explained_variance_ratio,
        n_fit_cells=int(n_cells_total),
        fit_perturbation_ids=tuple(sorted(base_train_ids)),
        n_genes_full=int(n_genes),
    )


def _iter_fit_populations(store: "OutcomeStore", base_train_ids: tuple[str, ...]):
    """Yield fit populations' cell matrices one at a time (controls first).

    Only :meth:`read_controls` and :meth:`read_unsealed` are used — the sealed
    cohort is never opened.  Each ``base_train`` id is materialised and released
    individually so peak memory is bounded by the largest single population.

    Parameters
    ----------
    store : OutcomeStore
        The outcome store.
    base_train_ids : tuple[str, ...]
        The ``base_train`` perturbation ids to stream.

    Yields
    ------
    np.ndarray
        Dense ``(n_cells, n_genes)`` raw-count matrix for one fit population.
    """
    yield store.read_controls().cells
    for pid in base_train_ids:
        yield store.read_unsealed([pid])[pid].cells
