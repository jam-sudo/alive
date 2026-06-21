#!/usr/bin/env python
"""Inspect a real Perturb-seq AnnData before any split or feature build.

Thin CLI over :mod:`alive.data.profile`.  Reads the ``.h5ad`` BACKED (never
densifies the whole matrix) and reports the obs columns, the per-perturbation
cell-count distribution, the per-cell UMI quantiles, and whether the four-way
split can yield the registered sealed cohort — then prints a data-card stub.

Usage
-----
    # discover obs columns (omit --perturbation-key)
    uv run python scripts/inspect_h5ad.py --h5ad data/k562_essential.h5ad

    # full profile once you know the columns
    uv run python scripts/inspect_h5ad.py \
        --h5ad data/k562_essential.h5ad \
        --config configs/cartographer_trust_gate_k562_v1.yaml \
        --perturbation-key gene --control-value non-targeting

This is read-only and outcome-independent; it opens nothing sealed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anndata
import numpy as np

from alive.config import load_config
from alive.data.profile import profile_perturbations, split_feasibility


def _stream_umi_per_cell(adata, chunk: int = 20000) -> np.ndarray:
    """Per-cell total counts, computed in chunks to avoid densifying."""
    n = adata.n_obs
    totals = np.zeros(n, dtype=np.float64)
    for start in range(0, n, chunk):
        stop = min(start + chunk, n)
        block = adata.X[start:stop]
        totals[start:stop] = np.asarray(block.sum(axis=1)).ravel()
    return totals


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Profile a Perturb-seq AnnData (pre-split).")
    p.add_argument("--h5ad", required=True, type=Path)
    p.add_argument("--config", type=Path, help="config YAML (for min_cells + split thresholds)")
    p.add_argument("--perturbation-key", help="obs column with the perturbation/target label")
    p.add_argument("--control-value", help="the label marking control cells")
    p.add_argument(
        "--gene-id-key", default=None, help="var column for gene IDs (default var_names)"
    )
    args = p.parse_args(argv)

    adata = anndata.read_h5ad(args.h5ad, backed="r")
    print(f"shape: {adata.n_obs} cells x {adata.n_vars} genes")
    print(f"obs columns: {list(adata.obs.columns)}")

    if not args.perturbation_key:
        print("\n--perturbation-key not given; candidate obs columns (nunique / sample values):")
        for col in adata.obs.columns:
            vals = adata.obs[col].astype(str)
            uniq = vals.unique()
            print(f"  {col}: nunique={len(uniq)}  e.g. {list(uniq[:6])}")
        print("\nRe-run with --perturbation-key and --control-value to get the full profile.")
        return 0

    if not args.control_value:
        print(
            "error: --control-value is required when --perturbation-key is given", file=sys.stderr
        )
        return 2

    # min_cells + split thresholds come from the config (never hardcoded here).
    if args.config:
        cfg = load_config(args.config)
        min_cells = cfg.response_space.min_cells
        sealed_fraction = cfg.split_fractions.sealed_evaluation
        min_sealed = cfg.decision.minimum_sealed_perturbations
    else:
        print("warning: no --config; using min_cells=64, sealed_fraction=0.15, min_sealed=200")
        min_cells, sealed_fraction, min_sealed = 64, 0.15, 200

    totals = _stream_umi_per_cell(adata)
    summ = profile_perturbations(
        adata,
        perturbation_key=args.perturbation_key,
        control_value=args.control_value,
        min_cells=min_cells,
        umi_per_cell=totals,
    )

    counts = sorted(summ.perturbation_counts.values())
    print(f"\ncontrol '{summ.control_value}': {summ.n_control_cells} cells")
    print(f"perturbations: {summ.n_perturbations} distinct")
    if counts:
        print(f"  cells/pert: min={counts[0]} median={counts[len(counts) // 2]} max={counts[-1]}")
    print(f"  >= min_cells ({min_cells}): {summ.n_perturbations_ge_min_cells} perturbations")
    print("per-cell UMI quantiles:")
    for q, v in summ.umi_quantiles.items():
        print(f"  p{int(q * 100):02d}: {v:.0f}")

    # NOTE: eligibility also requires a usable protein sequence (step 4), so the
    # count below is an UPPER bound on the truly eligible set.
    feas = split_feasibility(
        n_eligible=summ.n_perturbations_ge_min_cells,
        sealed_fraction=sealed_fraction,
        minimum_sealed_perturbations=min_sealed,
    )
    verdict = "OK" if feas.ok else "INSUFFICIENT"
    print(
        f"\nfour-way split feasibility (min_cells only; sequence filter applied later):\n"
        f"  eligible(upper-bound)={feas.n_eligible}  sealed≈{feas.sealed_count} "
        f"(need >= {feas.minimum_sealed_perturbations})  -> {verdict}\n"
        f"  minimum eligible needed for the sealed cohort: {feas.min_eligible_needed}"
    )
    if not feas.ok:
        print(
            "  WARNING: sealed cohort would be below the registered minimum even before the "
            "sequence-availability filter. Do not start the run until this is resolved."
        )

    stub = {
        "h5ad": str(args.h5ad),
        "sequences": "<path to gene->[protein_seq] JSON from fetch_sequences.py>",
        "perturbation_key": args.perturbation_key,
        "control_value": args.control_value,
        "gene_id_key": args.gene_id_key,
        "counts_layer": None,
        "raw_data_uri": "<expression dataset provenance string>",
        "sequence_source": "<protein DB release, e.g. uniprot-2024_05>",
        "id_mapping_version": "<gene->protein id mapping version>",
    }
    print("\ndata-card stub (fill the <...> after steps 4-5):")
    print(json.dumps(stub, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
