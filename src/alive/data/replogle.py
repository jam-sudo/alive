"""Metadata-only index over a Replogle Perturb-seq AnnData.

This module builds a :class:`ReplogleIndex` from a Perturb-seq `.h5ad` file
(or an in-memory :class:`anndata.AnnData`) **without ever densifying the full
expression matrix**.  Validation is strict and raises :class:`SchemaError` on
any schema or data-integrity violation.

Public API
----------
SchemaError
    Raised for any schema or data-integrity failure.
DatasetSchema
    Frozen descriptor of column names and layer choices for one AnnData.
ReplogleIndex
    Metadata index produced by :func:`build_index`.
build_index(source, schema, *, min_cells, available_feature_ids, counts_chunk)
    Build and return a :class:`ReplogleIndex`.

Global invariant
----------------
**No global densification.**  The expression matrix (X or a layer) is never
passed to ``.toarray()``, ``.todense()``, or ``np.asarray()`` in its entirety.
Finiteness/nonnegativity checks operate on the sparse ``.data`` array of stored
nonzeros only.  The chunked-dense path (for already-dense small fixtures) slices
row ranges and never materialises more than ``counts_chunk`` rows at once.

Examples
--------
>>> import scipy.sparse as sp, numpy as np, anndata, pandas as pd
>>> from alive.data.replogle import DatasetSchema, build_index
>>> n_cells, n_genes = 50, 10
>>> X = sp.random(n_cells, n_genes, density=0.3, format="csr", dtype=np.float32)
>>> X.data[:] = 1.0
>>> obs = pd.DataFrame(
...     {"target": ["ctrl"] * 20 + ["geneA"] * 30},
...     index=[f"c{i}" for i in range(n_cells)],
... )
>>> var = pd.DataFrame(index=[f"g{i}" for i in range(n_genes)])
>>> adata = anndata.AnnData(X=X, obs=obs, var=var)
>>> schema = DatasetSchema(perturbation_key="target", control_value="ctrl")
>>> idx = build_index(adata, schema, min_cells=10)
>>> idx.n_cells
50
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import scipy.sparse as sp

if TYPE_CHECKING:
    import anndata as _anndata
    import pandas as pd


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class SchemaError(ValueError):
    """Raised when an AnnData fails schema or data-integrity validation.

    Parameters
    ----------
    message : str
        Human-readable description of the failure.
    """


# ---------------------------------------------------------------------------
# Schema descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetSchema:
    """Descriptor specifying column names and layer choices for one AnnData.

    Parameters
    ----------
    perturbation_key : str
        Column in ``obs`` holding the perturbation/target label per cell.
    control_value : str
        The value in ``perturbation_key`` that marks control (non-targeting) cells.
    gene_id_key : str or None, optional
        Column in ``var`` for gene IDs.  ``None`` means use ``var_names`` (the index).
    counts_layer : str or None, optional
        Layer name holding raw counts.  ``None`` means use ``.X``.
    """

    perturbation_key: str
    control_value: str
    gene_id_key: str | None = None
    counts_layer: str | None = None


# ---------------------------------------------------------------------------
# Index structure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplogleIndex:
    """Metadata-only index over a Replogle Perturb-seq AnnData.

    No expression data is stored here — only obs/var metadata, cell positions,
    and eligibility information.

    Parameters
    ----------
    schema : DatasetSchema
        The schema descriptor used to build this index.
    gene_ids : tuple[str, ...]
        Ordered gene identifiers from ``var`` (unique, non-empty).
    n_cells : int
        Total number of cells in the AnnData.
    n_genes : int
        Total number of genes (features) in the expression matrix.
    control_indices : np.ndarray
        Sorted integer row positions of control cells.
    perturbation_indices : dict[str, np.ndarray]
        Mapping from non-control perturbation label to sorted integer row positions.
    eligible_perturbations : tuple[str, ...]
        Perturbations passing eligibility criteria (sorted alphabetically).
    exclusions : dict[str, str]
        Mapping from ineligible perturbation label to a human-readable reason.
    """

    schema: DatasetSchema
    gene_ids: tuple[str, ...]
    n_cells: int
    n_genes: int
    control_indices: np.ndarray
    perturbation_indices: dict[str, np.ndarray]
    eligible_perturbations: tuple[str, ...]
    exclusions: dict[str, str]

    def cell_indices(self, perturbation_id: str) -> np.ndarray:
        """Return sorted row positions for *perturbation_id*.

        Parameters
        ----------
        perturbation_id : str
            A non-control perturbation label (must appear in :attr:`perturbation_indices`).

        Returns
        -------
        np.ndarray
            Sorted integer array of row positions.

        Raises
        ------
        SchemaError
            If *perturbation_id* is not found in :attr:`perturbation_indices`
            (e.g. it is the control label, or it never appeared in the data).
            Chained from a :exc:`KeyError` for traceback clarity.
        """
        if perturbation_id not in self.perturbation_indices:
            raise SchemaError(
                f"unknown perturbation '{perturbation_id}': "
                "it does not appear in perturbation_indices.  "
                "Use control_indices for control cells."
            ) from KeyError(perturbation_id)
        return self.perturbation_indices[perturbation_id]

    def is_eligible(self, perturbation_id: str) -> bool:
        """Return ``True`` if *perturbation_id* is in :attr:`eligible_perturbations`.

        Parameters
        ----------
        perturbation_id : str
            Perturbation label to query.

        Returns
        -------
        bool
        """
        return perturbation_id in self.eligible_perturbations


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_index(
    source: "_anndata.AnnData | str | Path",
    schema: DatasetSchema,
    *,
    min_cells: int,
    available_feature_ids: Collection[str] | None = None,
    counts_chunk: int = 4096,
) -> ReplogleIndex:
    """Build a metadata-only :class:`ReplogleIndex` from a Perturb-seq AnnData.

    The expression matrix is **never densified** in its entirety.  If *source*
    is a path, the file is opened with ``backed="r"`` so ``.X`` is not loaded
    into memory; only ``obs`` and ``var`` metadata are read.  Finiteness and
    nonnegativity are validated via the sparse ``.data`` attribute (stored
    nonzeros) for sparse matrices, or via row-chunked slices for dense fixtures.

    Parameters
    ----------
    source : anndata.AnnData or str or Path
        In-memory AnnData (for tests) or a path to an ``.h5ad`` file.
    schema : DatasetSchema
        Column-name and layer-choice descriptor.
    min_cells : int
        Minimum cell count for a perturbation to be eligible.
    available_feature_ids : Collection[str] or None, optional
        If given, a perturbation label must be present in this set to be
        eligible.  Labels absent from the set are excluded with reason
        ``"no external feature"``.
    counts_chunk : int, optional
        Row-chunk size used when validating an already-dense expression matrix.
        Has no effect when the matrix is sparse.  Default 4096.

    Returns
    -------
    ReplogleIndex
        Validated metadata index.

    Raises
    ------
    SchemaError
        On any schema or data-integrity violation (see module docstring).
    """
    import anndata as ad

    # ------------------------------------------------------------------
    # 1. Open or use source AnnData
    # ------------------------------------------------------------------
    _backed_mode = False
    if isinstance(source, (str, Path)):
        adata = ad.read_h5ad(Path(source), backed="r")
        _backed_mode = True
    else:
        adata = source

    try:
        return _build_index_from_adata(
            adata=adata,
            schema=schema,
            min_cells=min_cells,
            available_feature_ids=available_feature_ids,
            counts_chunk=counts_chunk,
        )
    finally:
        if _backed_mode:
            adata.file.close()


def _build_index_from_adata(
    *,
    adata: "_anndata.AnnData",
    schema: DatasetSchema,
    min_cells: int,
    available_feature_ids: Collection[str] | None,
    counts_chunk: int,
) -> ReplogleIndex:
    """Internal builder; assumes *adata* is already open."""

    # ------------------------------------------------------------------
    # 2. Validate perturbation_key exists in obs
    # ------------------------------------------------------------------
    if schema.perturbation_key not in adata.obs.columns:
        raise SchemaError(
            f"perturbation_key {schema.perturbation_key!r} is not a column in obs.  "
            f"Available columns: {list(adata.obs.columns)}"
        )

    pert_series = adata.obs[schema.perturbation_key]

    # ------------------------------------------------------------------
    # 3. Validate no empty or NaN labels
    # ------------------------------------------------------------------
    _validate_labels(pert_series)

    # ------------------------------------------------------------------
    # 4. Validate at least one control cell
    # ------------------------------------------------------------------
    ctrl_mask = pert_series == schema.control_value
    if not ctrl_mask.any():
        raise SchemaError(
            f"No control cells found: no cell has "
            f"{schema.perturbation_key!r} == {schema.control_value!r}."
        )

    # ------------------------------------------------------------------
    # 5. Resolve gene IDs from var
    # ------------------------------------------------------------------
    if schema.gene_id_key is not None:
        if schema.gene_id_key not in adata.var.columns:
            raise SchemaError(
                f"gene_id_key {schema.gene_id_key!r} is not a column in var.  "
                f"Available columns: {list(adata.var.columns)}"
            )
        gene_ids_raw: list[str] = list(adata.var[schema.gene_id_key].astype(str))
    else:
        gene_ids_raw = list(adata.var_names)

    # Validate: no empty gene IDs
    for gid in gene_ids_raw:
        if not gid or gid.strip() == "":
            raise SchemaError(
                "Gene IDs must be non-empty strings; found an empty or blank gene ID."
            )

    # Validate: unique gene IDs
    if len(gene_ids_raw) != len(set(gene_ids_raw)):
        seen: set[str] = set()
        dups: list[str] = []
        for g in gene_ids_raw:
            if g in seen:
                dups.append(g)
            seen.add(g)
        raise SchemaError(f"Duplicate gene IDs found: {dups[:5]!r}.  Gene IDs must be unique.")

    gene_ids: tuple[str, ...] = tuple(gene_ids_raw)
    n_genes = len(gene_ids)

    # ------------------------------------------------------------------
    # 6. Resolve expression matrix (X or layer) and validate axes + values
    # ------------------------------------------------------------------
    if schema.counts_layer is not None:
        if schema.counts_layer not in adata.layers:
            raise SchemaError(
                f"counts_layer {schema.counts_layer!r} is not present in adata.layers.  "
                f"Available layers: {list(adata.layers.keys())}"
            )
        expr = adata.layers[schema.counts_layer]
    else:
        expr = adata.X

    # Gene-axis consistency check (shape only — no densification)
    n_cells_total = adata.n_obs
    expr_shape = expr.shape  # .shape is always safe for sparse and dense
    if expr_shape[1] != n_genes:
        raise SchemaError(
            f"Gene-axis mismatch: var has {n_genes} rows but the expression "
            f"matrix has shape {expr_shape} (axis 1 = {expr_shape[1]}).  "
            "len(gene_ids) must equal X.shape[1]."
        )

    # Finiteness + nonnegativity — sparse path (never calls toarray/todense)
    _validate_expression_values(expr, counts_chunk=counts_chunk)

    # ------------------------------------------------------------------
    # 7. Build index arrays from obs metadata only
    # ------------------------------------------------------------------
    labels_array = pert_series.to_numpy()
    ctrl_indices = np.where(ctrl_mask.to_numpy())[0]

    # Build per-perturbation index (excluding control)
    unique_perts = sorted(set(labels_array) - {schema.control_value})
    perturbation_indices: dict[str, np.ndarray] = {}
    for label in unique_perts:
        idxs = np.where(labels_array == label)[0]
        perturbation_indices[label] = idxs

    # ------------------------------------------------------------------
    # 8. Compute eligibility (metadata only — never expression response)
    # ------------------------------------------------------------------
    eligible: list[str] = []
    exclusions: dict[str, str] = {}
    feat_set = set(available_feature_ids) if available_feature_ids is not None else None

    for label in unique_perts:
        n = len(perturbation_indices[label])
        if n < min_cells:
            exclusions[label] = f"only {n} cells (min {min_cells})"
            continue
        if feat_set is not None and label not in feat_set:
            exclusions[label] = f"no external feature: label {label!r} not in available_feature_ids"
            continue
        eligible.append(label)

    eligible_tuple: tuple[str, ...] = tuple(sorted(eligible))

    return ReplogleIndex(
        schema=schema,
        gene_ids=gene_ids,
        n_cells=n_cells_total,
        n_genes=n_genes,
        control_indices=ctrl_indices,
        perturbation_indices=perturbation_indices,
        eligible_perturbations=eligible_tuple,
        exclusions=exclusions,
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_labels(pert_series: "pd.Series") -> None:
    """Raise SchemaError if any perturbation label is NaN, None, or empty.

    Parameters
    ----------
    pert_series : pd.Series
        The obs column holding perturbation labels.
    """
    # Check for NaN / None
    if pert_series.isna().any():
        raise SchemaError(
            "Perturbation column contains NaN or null values.  "
            "All cells must have a valid perturbation label."
        )

    # Check for empty strings (after converting to str for safety).
    # Note: astype(str) empty-check runs AFTER the isna() check above, so NaN is already handled.
    str_series = pert_series.astype(str)
    empty_mask = str_series.str.strip() == ""
    if empty_mask.any():
        raise SchemaError(
            "Perturbation column contains empty or blank labels.  "
            "Every cell must have a non-empty perturbation label."
        )


def _validate_expression_values(
    expr: "sp.spmatrix | np.ndarray",
    *,
    counts_chunk: int,
) -> None:
    """Validate that expression values are finite and nonnegative.

    For sparse matrices (``scipy.sparse``): checks ``expr.data`` (stored
    nonzeros) only — never calls ``toarray()`` or ``todense()``.

    For h5py-backed sparse datasets (``anndata._CSRDataset`` etc.): slices
    row-ranges of size *counts_chunk*; each slice yields a regular scipy sparse
    matrix whose ``.data`` is then checked.

    For dense ndarrays (small fixtures): slices row-ranges of size
    *counts_chunk* and validates each chunk without materialising the whole
    matrix.

    Parameters
    ----------
    expr : sparse matrix, ndarray, or backed sparse dataset
        The expression matrix (X or a layer).
    counts_chunk : int
        Row-chunk size used for backed-sparse and dense validation paths.

    Raises
    ------
    SchemaError
        If any stored nonzero is non-finite or negative.
    """
    if sp.issparse(expr):
        # In-memory scipy sparse: safe to access .data directly
        data = expr.data
        if data.size > 0:
            if not np.isfinite(data).all():
                raise SchemaError(
                    "Expression matrix contains non-finite values (inf or NaN) "
                    "in the stored nonzero entries.  "
                    "All expression values must be finite and nonnegative."
                )
            if not (data >= 0).all():
                raise SchemaError(
                    "Expression matrix contains negative values in the stored "
                    "nonzero entries.  All count values must be nonnegative."
                )
    elif isinstance(expr, np.ndarray):
        # Dense ndarray: validate in row-chunks
        n_rows = expr.shape[0]
        for start in range(0, n_rows, counts_chunk):
            chunk = expr[start : start + counts_chunk]
            if not np.isfinite(chunk).all():
                raise SchemaError(
                    f"Expression matrix contains non-finite values (inf or NaN) "
                    f"in rows {start}:{start + counts_chunk}.  "
                    "All expression values must be finite and nonnegative."
                )
            if not (chunk >= 0).all():
                raise SchemaError(
                    f"Expression matrix contains negative values in rows "
                    f"{start}:{start + counts_chunk}.  "
                    "All count values must be nonnegative."
                )
    else:
        # Backed sparse dataset (e.g. anndata._CSRDataset from backed="r"):
        # slicing returns regular scipy sparse matrices — check .data per chunk.
        n_rows = expr.shape[0]
        for start in range(0, n_rows, counts_chunk):
            chunk = expr[start : start + counts_chunk]
            if sp.issparse(chunk):
                chunk_data = chunk.data
                if chunk_data.size > 0:
                    if not np.isfinite(chunk_data).all():
                        raise SchemaError(
                            f"Expression matrix contains non-finite values (inf or NaN) "
                            f"in rows {start}:{start + counts_chunk}.  "
                            "All expression values must be finite and nonnegative."
                        )
                    if not (chunk_data >= 0).all():
                        raise SchemaError(
                            f"Expression matrix contains negative values in rows "
                            f"{start}:{start + counts_chunk}.  "
                            "All count values must be nonnegative."
                        )
            else:
                # Unexpected: chunk came back dense anyway; validate it.
                # Operates on a bounded chunk (<= counts_chunk rows), not the whole matrix.
                chunk_arr = np.asarray(chunk)
                if not np.isfinite(chunk_arr).all():
                    raise SchemaError(
                        f"Expression matrix contains non-finite values (inf or NaN) "
                        f"in rows {start}:{start + counts_chunk}.  "
                        "All expression values must be finite and nonnegative."
                    )
                if not (chunk_arr >= 0).all():
                    raise SchemaError(
                        f"Expression matrix contains negative values in rows "
                        f"{start}:{start + counts_chunk}.  "
                        "All count values must be nonnegative."
                    )
