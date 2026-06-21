#!/usr/bin/env python
"""Build a mini K562 dataset for end-to-end pipeline validation (Gate D, §14.2).

Derives a small, deterministic, eligibility-preserving subset from the FULL
data-card (same perturbation_key / control_value / provenance), writing a mini
``.h5ad`` + mini sequences JSON + mini data-card.  Run the mini through
``prepare -> fit -> develop -> futility -> calibrate`` with the REAL encoder and a
mini config BEFORE the full run (CLAUDE.md §14.2).

Thin CLI over :mod:`alive.data.mini`.  Run this on the A100 against the full file:
the subset is materialised in memory (``adata[mask].to_memory()``), so it expects
A100-class memory (not the 24 GB Mac).

Usage
-----
    uv run python scripts/make_mini.py \
        --data-card data/k562_data_card.json \
        --config configs/cartographer_trust_gate_k562_v1.yaml \
        --out-dir data/mini --n-perturbations 40 --seed 20260621
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import anndata

from alive.config import load_config
from alive.data.mini import select_mini_perturbations, subset_cells_mask


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build a mini dataset from the full data-card.")
    p.add_argument("--data-card", required=True, type=Path, help="the FULL data-card JSON")
    p.add_argument("--config", required=True, type=Path, help="config (for min_cells)")
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--n-perturbations", type=int, default=40)
    p.add_argument("--control-cap", type=int, default=600)
    p.add_argument("--per-pert-cap", type=int, default=None)
    p.add_argument("--seed", type=int, default=20260621)
    args = p.parse_args(argv)

    card = json.loads(args.data_card.read_text(encoding="utf-8"))
    pkey, ctrl = card["perturbation_key"], card["control_value"]
    min_cells = load_config(args.config).response_space.min_cells

    sequences = json.loads(Path(card["sequences"]).read_text(encoding="utf-8"))
    usable = {g for g, seqs in sequences.items() if isinstance(seqs, list) and len(seqs) == 1}

    adata = anndata.read_h5ad(card["h5ad"], backed="r")
    labels = adata.obs[pkey].astype(str).to_numpy()
    counts: dict[str, int] = {}
    for lab in labels:
        if lab != ctrl:
            counts[lab] = counts.get(lab, 0) + 1

    selected = select_mini_perturbations(
        counts, usable, min_cells=min_cells, n_perturbations=args.n_perturbations, seed=args.seed
    )
    if not selected:
        print("error: no eligible (>=min_cells AND usable-sequence) perturbations found")
        return 2

    mask = subset_cells_mask(
        labels,
        control_value=ctrl,
        selected_perts=selected,
        control_cap=args.control_cap,
        per_pert_cap=args.per_pert_cap,
        seed=args.seed,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    mini = adata[mask].to_memory()
    mini_h5ad = args.out_dir / "mini.h5ad"
    mini.write_h5ad(mini_h5ad)

    mini_sequences = {g: sequences[g] for g in selected}
    mini_seq_path = args.out_dir / "mini_sequences.json"
    mini_seq_path.write_text(json.dumps(mini_sequences), encoding="utf-8")

    mini_card = dict(card)
    mini_card["h5ad"] = str(mini_h5ad)
    mini_card["sequences"] = str(mini_seq_path)
    mini_card["raw_data_uri"] = f"{card.get('raw_data_uri', 'unknown')}#mini-{len(selected)}p"
    mini_card_path = args.out_dir / "mini_data_card.json"
    mini_card_path.write_text(json.dumps(mini_card, indent=2), encoding="utf-8")

    print(
        f"mini: {len(selected)} perturbations, {int(mask.sum())} cells "
        f"(controls capped at {args.control_cap})\n"
        f"  {mini_h5ad}\n  {mini_seq_path}\n  {mini_card_path}\n"
        f"selected perturbations: {selected}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
