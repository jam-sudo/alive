#!/usr/bin/env python
"""Real-Norman Φ rank + condition report (§10.1 ``real_norman_phi_rank_and_condition_report``).

Thin CLI over :func:`alive.compose.phi_rank.compute_phi_rank_report`. It assembles
the real, outcome-free inputs from the Norman ``.h5ad`` and a gene->protein-sequence
JSON (produced by ``scripts/fetch_sequences.py``):

1. parse perturbation labels -> singles / doubles / control (no GI strength used);
2. outcome-independent eligibility (cells-per-gene/pair + ESM availability);
3. fit the leakage-safe PCA-50 response space on control + eligible singles, and
   take ``δ_g`` = response-space mean shift of single ``g`` vs control;
4. encode the real ESM-2 mean-pooled sequence vectors ``s_g`` on GPU;
5. for each registered ``k_total`` build ``z_g = [PCA_k(δ_g) ; ESM-PCA(s_g)]`` and
   report the ``combo_calibration`` design-matrix Φ rank vs ``sym_dim`` + condition.

Opens NO seal and reads NO sealed/double outcomes for fitting: ``δ_g`` is a
single-role quantity and the split is a seeded gene partition. The report is
dev-stage activation-blocker evidence; it does not authorize a real fit.

Usage
-----
    uv run python scripts/compose_phi_rank_report.py \
        --config configs/compose_k562_v1_phase2.yaml \
        --h5ad /workspace/alive_data/NormanWeissman2019_filtered.h5ad \
        --sequences seqs.json --out artifacts/compose/phi_rank_report.json \
        --git-sha "$(git rev-parse HEAD)"
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

import anndata as ad
import numpy as np
import yaml

from alive.compose.config2 import load_compose_phase2_config
from alive.compose.phi_rank import PHI_RANK_ACTIVATION_SCHEMA, compute_phi_rank_report
from alive.compose.response import fit_response_space
from alive.data.features import Esm2Encoder
from alive.data.norman import eligible_genes, eligible_pairs, parse_labels
from alive.data.smoke import mean_pool
from alive.provenance import sha256_file, sha256_json


def _device_info() -> dict:
    """Best-effort torch device record for §14.2 provenance (never fatal)."""
    try:
        import torch  # noqa: PLC0415

        cuda = bool(torch.cuda.is_available())
        return {
            "cuda_available": cuda,
            "device_name": torch.cuda.get_device_name(0) if cuda else "cpu",
            "torch_version": str(torch.__version__),
        }
    except Exception as exc:  # noqa: BLE001
        return {"cuda_available": False, "device_name": "unknown", "error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    """Assemble real inputs, compute the Φ rank report, and write the JSON envelope."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--h5ad", required=True, type=Path)
    ap.add_argument("--sequences", required=True, type=Path, help="gene->[seq] JSON")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--git-sha", required=True)
    ap.add_argument("--long-seq-policy", default="truncate", choices=("truncate", "error"))
    ap.add_argument("--max-residues", type=int, default=1022)
    ap.add_argument("--max-batch-tokens", type=int, default=16384)
    args = ap.parse_args(argv)
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", args.git_sha) is None:
        raise SystemExit("--git-sha must be the full 40- or 64-character lowercase commit")

    raw = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    d, el = raw["data"], raw["eligibility"]
    rs, fz, sp = raw["response_space"], raw["factor_z"], raw["split"]
    split_seed = int(raw["seeds"]["split_seed"])
    model_name = str(fz["esm_model"]).removesuffix("_mean_pool")

    # --- load data + labels -------------------------------------------------
    adata = ad.read_h5ad(args.h5ad)
    obs_values = np.asarray(adata.obs[str(d["perturbation_key"])].to_numpy())
    singles, doubles, control_idx = parse_labels(
        obs_values, control_token=str(d["control_token"]), combo_sep=str(d["combo_sep"])
    )

    # --- eligibility (outcome-independent) ----------------------------------
    seqs = json.loads(args.sequences.read_text(encoding="utf-8"))
    available = {g for g, v in seqs.items() if isinstance(v, list) and v and v[0]}
    genes_elig = eligible_genes(
        singles, min_cells=int(el["min_cells_per_gene"]), available_feature_ids=available
    )
    pairs_elig = eligible_pairs(doubles, set(genes_elig), min_cells=int(el["min_cells_per_pair"]))
    genes = sorted({g for pair in pairs_elig for g in pair})
    if not pairs_elig:
        raise SystemExit("no eligible pairs after outcome-independent filtering")

    # --- response space + single-role δ_g (response-space mean shift) --------
    eligible_single_idx = np.concatenate([singles[g] for g in genes])
    space = fit_response_space(
        adata.X,
        control_idx=control_idx,
        eligible_single_idx=eligible_single_idx,
        n_hvg=int(rs["n_hvg"]),
        pca_dim=int(rs["pca_dim"]),
        seed=split_seed,
    )
    ctrl_mean = space.project(adata.X, control_idx).mean(axis=0)
    delta_by_gene = {g: space.project(adata.X, singles[g]).mean(axis=0) - ctrl_mean for g in genes}

    # --- real ESM-2 mean-pooled sequence vectors (GPU) ----------------------
    encoder = Esm2Encoder(
        model_name,
        max_residues=int(args.max_residues),
        long_sequence_policy=str(args.long_seq_policy),
        max_batch_tokens=int(args.max_batch_tokens),
    )
    pooled = mean_pool(encoder.encode_residues([str(seqs[g][0]) for g in genes]))
    sequence_by_gene = {g: np.asarray(pooled[i], dtype=np.float64) for i, g in enumerate(genes)}
    seq_mapping = {g: str(seqs[g][0]) for g in genes}
    seq_mapping_hash = sha256_json(seq_mapping)

    # --- Φ rank report (tested core) ----------------------------------------
    report = compute_phi_rank_report(
        delta_by_gene=delta_by_gene,
        sequence_by_gene=sequence_by_gene,
        eligible_pairs=pairs_elig,
        total_k_grid=[int(k) for k in fz["total_k_grid"]],
        esm_dim=int(fz["esm_projection_dim"]),
        split_seed=split_seed,
        calibration_fraction=float(sp["calibration_fraction"]),
        encoder_revision=model_name,
        sequence_mapping_hash=seq_mapping_hash,
    )

    # READY must mean "the run can use every registered dimension", not merely
    # "every dimension is full rank". The conditioning ceiling is the run's
    # registered admissibility criterion (`select_hyperparams` screens candidates
    # against exactly this statistic on exactly this design), so a report that
    # certified an over-ceiling dimension would green-light a design the run then
    # rejects. Read through the VALIDATED loader, not the raw mapping: the raw
    # value can be a string (YAML 1.1 parses `1.0e8` that way), and a coerced
    # comparison would certify silently. Never hardcoded here.
    ceiling = float(load_compose_phase2_config(args.config).condition_ceiling)
    rank_ready = all(
        block["is_full_rank"]
        and block["rank"] == block["sym_dim"]
        and block["n_calibration_pairs_skipped"] == 0
        for block in report["per_k_total"]
    )
    # ANY, not ALL -- the run screens an over-ceiling dimension out of selection and
    # proceeds on the rest, so only a grid with no admissible dimension is
    # uncertifiable. The over-ceiling dimensions are named in the verdict either
    # way, so an owner sees which ones the run will drop before approving a SHA.
    over_ceiling = [
        int(block["k_total"])
        for block in report["per_k_total"]
        if float(block["condition_number"]) > ceiling
    ]
    conditioning_ready = len(over_ceiling) < len(report["per_k_total"])
    if not rank_ready:
        activation = "BLOCKED — at least one registered factor grid failed the rank gate; no seal"
    elif not conditioning_ready:
        activation = (
            "BLOCKED — every registered factor grid is full rank but ALL are conditioned "
            f"above the registered ceiling {ceiling}, so the run's admissibility screen "
            "would leave no viable candidate; no seal"
        )
    elif over_ceiling:
        activation = (
            f"READY — k_total {over_ceiling} exceed the registered conditioning ceiling "
            f"{ceiling} and the run will screen them out; the remaining registered grid is "
            "full rank and admissible; sealed outcomes remain unread"
        )
    else:
        activation = (
            "READY — every registered factor grid is full rank and conditioned at or "
            f"below the registered ceiling {ceiling}; sealed outcomes remain unread"
        )
    envelope = {
        "schema": PHI_RANK_ACTIVATION_SCHEMA,
        "deliverable": "real_norman_phi_rank_and_condition_report",
        "protocol": "COMPOSE-K562-v1",
        "activation": activation,
        "generated_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "git_sha": str(args.git_sha),
        "config_sha256": sha256_json(raw),
        "data_sha256": sha256_file(args.h5ad),
        "sequence_mapping_sha256": seq_mapping_hash,
        "esm_model": model_name,
        "long_sequence_policy": str(args.long_seq_policy),
        "device": _device_info(),
        "n_cells": int(adata.n_obs),
        "n_singles_total": len(singles),
        "n_doubles_total": len(doubles),
        "n_control_cells": int(control_idx.size),
        "n_eligible_genes": len(genes_elig),
        "n_z_universe_genes": len(genes),
        "report": report,
    }

    try:
        serialized = json.dumps(
            envelope, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
    except ValueError as exc:
        raise SystemExit("phi-rank report contains a non-finite numeric value") from exc
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(serialized + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    for r in report["per_k_total"]:
        print(
            f"  k_total={r['k_total']:>2} sym_dim={r['sym_dim']:>3} rank={r['rank']:>3} "
            f"full_rank={r['is_full_rank']!s:>5} cond={r['condition_number']:.4g} "
            f"|cal|={r['n_calibration_pairs_scored']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
