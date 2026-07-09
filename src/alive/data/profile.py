"""Outcome-independent profiling of a Perturb-seq AnnData (A100 prep).

This module summarises a dataset BEFORE any split or feature build, so the
operator can (a) choose the data-card fields (``perturbation_key`` /
``control_value``) from real ``obs`` columns and (b) confirm the four-way split
is feasible at the registered thresholds (CLAUDE.md#data-eval: profile distributions and
pre-register thresholds; never hardcode cell/UMI cutoffs as universal facts).

Nothing here reads a sealed evaluation outcome — it is a pure description of the
input matrix and its perturbation labels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

_DEFAULT_QUANTILES: tuple[float, ...] = (0.05, 0.25, 0.5, 0.75, 0.95)


@dataclass(frozen=True)
class ProfileSummary:
    """Pre-split description of a Perturb-seq AnnData.

    Attributes
    ----------
    n_cells, n_genes : int
        Matrix shape.
    n_control_cells : int
        Number of cells whose ``perturbation_key`` equals ``control_value``.
    control_value : str
        The control label used.
    perturbation_counts : dict[str, int]
        Cell count per non-control perturbation label.
    n_perturbations : int
        Number of distinct non-control perturbations.
    n_perturbations_ge_min_cells : int
        How many perturbations have at least ``min_cells`` cells.
    min_cells : int
        The threshold applied (from the config, not hardcoded here).
    umi_quantiles : dict[float, float]
        Per-cell total-count quantiles (a coarse UMI/library-size profile).
    """

    n_cells: int
    n_genes: int
    n_control_cells: int
    control_value: str
    perturbation_counts: dict[str, int]
    n_perturbations: int
    n_perturbations_ge_min_cells: int
    min_cells: int
    umi_quantiles: dict[float, float]


@dataclass(frozen=True)
class Feasibility:
    """Whether the four-way split can yield the registered sealed cohort size."""

    n_eligible: int
    sealed_fraction: float
    minimum_sealed_perturbations: int
    sealed_count: int
    ok: bool
    min_eligible_needed: int


def profile_perturbations(
    adata,
    *,
    perturbation_key: str,
    control_value: str,
    min_cells: int,
    umi_per_cell: np.ndarray | None = None,
    quantiles: tuple[float, ...] = _DEFAULT_QUANTILES,
) -> ProfileSummary:
    """Summarise an AnnData's perturbation labels and library-size distribution.

    Parameters
    ----------
    adata : anndata.AnnData
        The dataset (read in-memory or backed; only ``obs`` and ``X`` are touched).
    perturbation_key : str
        ``obs`` column holding each cell's perturbation/target label.
    control_value : str
        The label marking control (non-targeting) cells.
    min_cells : int
        Per-perturbation cell-count threshold to report eligibility against.
    umi_per_cell : numpy.ndarray or None, optional
        Precomputed per-cell total counts (for large/backed matrices the caller
        may stream this).  When ``None``, it is computed from ``adata.X``.
    quantiles : tuple[float, ...], optional
        Quantiles to report for the per-cell total-count distribution.

    Raises
    ------
    KeyError
        If ``perturbation_key`` is not an ``obs`` column.
    ValueError
        If ``control_value`` does not appear in that column.
    """
    if perturbation_key not in adata.obs.columns:
        raise KeyError(
            f"perturbation_key {perturbation_key!r} is not an obs column; "
            f"available: {list(adata.obs.columns)}"
        )
    labels = adata.obs[perturbation_key].astype(str)
    if control_value not in set(labels.unique()):
        raise ValueError(f"control_value {control_value!r} not found in obs[{perturbation_key!r}].")

    is_ctrl = labels == control_value
    n_control_cells = int(is_ctrl.sum())
    counts = labels[~is_ctrl].value_counts()
    perturbation_counts = {str(k): int(v) for k, v in counts.items()}
    n_perturbations_ge_min_cells = sum(1 for c in perturbation_counts.values() if c >= min_cells)

    if umi_per_cell is None:
        totals = np.asarray(adata.X.sum(axis=1)).ravel().astype(np.float64)
    else:
        totals = np.asarray(umi_per_cell, dtype=np.float64).ravel()
    qs = np.quantile(totals, list(quantiles)) if totals.size else np.full(len(quantiles), np.nan)
    umi_quantiles = {float(q): float(v) for q, v in zip(quantiles, qs, strict=True)}

    return ProfileSummary(
        n_cells=int(adata.n_obs),
        n_genes=int(adata.n_vars),
        n_control_cells=n_control_cells,
        control_value=control_value,
        perturbation_counts=perturbation_counts,
        n_perturbations=len(perturbation_counts),
        n_perturbations_ge_min_cells=n_perturbations_ge_min_cells,
        min_cells=min_cells,
        umi_quantiles=umi_quantiles,
    )


def split_feasibility(
    *,
    n_eligible: int,
    sealed_fraction: float,
    minimum_sealed_perturbations: int,
) -> Feasibility:
    """Check whether ``n_eligible`` perturbations yield a large-enough sealed cohort.

    The sealed cohort is a conservative floor of ``n_eligible * sealed_fraction``
    (a small epsilon guards against binary-float underflow, e.g. 1400*0.15).
    """
    sealed_count = int(n_eligible * sealed_fraction + 1e-9)
    min_eligible_needed = math.ceil(minimum_sealed_perturbations / sealed_fraction)
    return Feasibility(
        n_eligible=n_eligible,
        sealed_fraction=sealed_fraction,
        minimum_sealed_perturbations=minimum_sealed_perturbations,
        sealed_count=sealed_count,
        ok=sealed_count >= minimum_sealed_perturbations,
        min_eligible_needed=min_eligible_needed,
    )
