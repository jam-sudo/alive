"""Tests for real-data profiling (A100 prep toolkit).

``profile_perturbations`` summarises a Perturb-seq AnnData WITHOUT opening any
sealed evaluation outcome — it is a pre-split, outcome-independent description
used to choose the data-card fields and to confirm the four-way split is
feasible (CLAUDE.md §7: profile distributions, pre-register thresholds).
"""

from __future__ import annotations

import anndata
import numpy as np
import pandas as pd
import scipy.sparse as sp

from alive.data.profile import ProfileSummary, profile_perturbations, split_feasibility


def _adata(counts_per_pert: dict[str, int], *, n_ctrl: int, n_genes: int = 6):
    labels: list[str] = ["ctrl"] * n_ctrl
    for g, n in counts_per_pert.items():
        labels.extend([g] * n)
    rng = np.random.default_rng(0)
    x = sp.csr_matrix(rng.poisson(1.0, size=(len(labels), n_genes)).astype(np.float32))
    obs = pd.DataFrame({"target": labels}, index=[f"c{i}" for i in range(len(labels))])
    var = pd.DataFrame(index=[f"g{i}" for i in range(n_genes)])
    return anndata.AnnData(X=x, obs=obs, var=var)


def test_profile_counts_controls_and_perturbations() -> None:
    adata = _adata({"GENE_A": 100, "GENE_B": 40, "GENE_C": 10}, n_ctrl=200)
    summ = profile_perturbations(
        adata, perturbation_key="target", control_value="ctrl", min_cells=64
    )
    assert isinstance(summ, ProfileSummary)
    assert summ.n_cells == 350
    assert summ.n_control_cells == 200
    assert summ.n_perturbations == 3  # control excluded
    assert summ.perturbation_counts["GENE_A"] == 100
    # only GENE_A (100) and ... GENE_B(40)<64, GENE_C(10)<64 → 1 passes min_cells
    assert summ.n_perturbations_ge_min_cells == 1


def test_profile_reports_umi_quantiles() -> None:
    adata = _adata({"GENE_A": 80}, n_ctrl=80, n_genes=10)
    summ = profile_perturbations(
        adata, perturbation_key="target", control_value="ctrl", min_cells=64
    )
    # per-cell total counts quantiles are present and ordered
    q = summ.umi_quantiles
    assert set(q) >= {0.05, 0.5, 0.95}
    assert q[0.05] <= q[0.5] <= q[0.95]


def test_profile_raises_on_missing_key_or_control() -> None:
    adata = _adata({"GENE_A": 80}, n_ctrl=80)
    import pytest

    with pytest.raises(KeyError):
        profile_perturbations(adata, perturbation_key="nope", control_value="ctrl", min_cells=64)
    with pytest.raises(ValueError):
        profile_perturbations(
            adata, perturbation_key="target", control_value="absent_ctrl", min_cells=64
        )


def test_split_feasibility_flags_insufficient_sealed_cohort() -> None:
    # 10 eligible perts, sealed fraction 0.15 → 1.5 → 1 sealed pert < required 200
    feas = split_feasibility(n_eligible=10, sealed_fraction=0.15, minimum_sealed_perturbations=200)
    assert feas.sealed_count == 1
    assert feas.ok is False
    # 1400 eligible → 210 sealed ≥ 200 → ok
    feas2 = split_feasibility(
        n_eligible=1400, sealed_fraction=0.15, minimum_sealed_perturbations=200
    )
    assert feas2.sealed_count == 210
    assert feas2.ok is True
    # report the minimum eligible needed
    assert feas.min_eligible_needed == 1334  # ceil(200 / 0.15)
