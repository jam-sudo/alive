#!/usr/bin/env python
"""Regime detectable-effect / measurability report (§10.1 deliverable).

Thin CLI over :func:`alive.compose.detectable_effect.compute_regime_detectable_effect_report`.
It assembles the real, response-space non-additive residual ``ε_gh = δ_gh - δ_g - δ_h``
on the ``combo_calibration`` DEVELOPMENT pairs (split into two disjoint cell halves
for the measurability noise-ceiling), and the outcome-independent pair / cell counts
of the sealed evaluation regimes for the pre-registered power gate.

Leakage discipline (CLAUDE.md#seal, spec §2.4): ``ε`` is computed ONLY on
``combo_calibration`` (development / ``audited_unsealed`` role). The sealed
evaluation regimes (``sealed_double_unseen`` / ``sealed_single_unseen``) are read
for their **cell counts only** — never their outcomes. No seal is opened.

Usage
-----
    uv run python scripts/compose_detectable_effect_report.py \
        --config configs/compose_k562_v1_phase2.yaml \
        --phase1-config configs/compose_k562_v1_phase1.yaml \
        --h5ad /workspace/alive_data/NormanWeissman2019_filtered.h5ad \
        --sequences seqs.json --out artifacts/compose/detectable_effect_report.json \
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

from alive.compose.detectable_effect import (
    DETECTABLE_EFFECT_ACTIVATION_SCHEMA,
    REGISTERED_MIN_CELLS,
    REGISTERED_MIN_PAIRS,
    REGISTERED_PHASE1_CONFIG_SHA256,
    compute_regime_detectable_effect_report,
)
from alive.compose.response import fit_response_space
from alive.compose.split import build_pair_split
from alive.data.norman import eligible_genes, eligible_pairs, parse_labels
from alive.provenance import sha256_file, sha256_json


def _median_cells(doubles: dict, pairs) -> float:
    """Median double-cell count over ``pairs`` (outcome-independent metadata)."""
    counts = [int(doubles[p].size) for p in pairs if p in doubles]
    return float(np.median(counts)) if counts else 0.0


def main(argv: list[str] | None = None) -> int:
    """Assemble real ε split-halves + regime counts and write the report."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--phase1-config", required=True, type=Path, help="power-gate floors")
    ap.add_argument("--h5ad", required=True, type=Path)
    ap.add_argument("--sequences", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--git-sha", required=True)
    args = ap.parse_args(argv)
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", args.git_sha) is None:
        raise SystemExit("--git-sha must be the full 40- or 64-character lowercase commit")

    raw = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    p1 = yaml.safe_load(args.phase1_config.read_text(encoding="utf-8"))
    d, el = raw["data"], raw["eligibility"]
    rs, sp = raw["response_space"], raw["split"]
    split_seed = int(raw["seeds"]["split_seed"])
    min_pairs = int(p1["min_double_unseen_pairs"])
    min_cells = int(p1["min_cells_per_pair"])
    phase1_config_sha256 = sha256_json(p1)
    if (
        min_pairs != REGISTERED_MIN_PAIRS
        or min_cells != REGISTERED_MIN_CELLS
        or phase1_config_sha256 != REGISTERED_PHASE1_CONFIG_SHA256
    ):
        raise SystemExit("phase1 power contract drifted from the registered 20-pair/50-cell config")

    adata = ad.read_h5ad(args.h5ad)
    obs_values = np.asarray(adata.obs[str(d["perturbation_key"])].to_numpy())
    singles, doubles, control_idx = parse_labels(
        obs_values, control_token=str(d["control_token"]), combo_sep=str(d["combo_sep"])
    )

    seqs = json.loads(args.sequences.read_text(encoding="utf-8"))
    available = {g for g, v in seqs.items() if isinstance(v, list) and v and v[0]}
    genes_elig = eligible_genes(
        singles, min_cells=int(el["min_cells_per_gene"]), available_feature_ids=available
    )
    pairs_elig = eligible_pairs(doubles, set(genes_elig), min_cells=int(el["min_cells_per_pair"]))
    genes = sorted({g for pair in pairs_elig for g in pair})
    if not pairs_elig:
        raise SystemExit("no eligible pairs after outcome-independent filtering")

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
    delta = {g: space.project(adata.X, singles[g]).mean(axis=0) - ctrl_mean for g in genes}

    split = build_pair_split(
        pairs_elig, seed=split_seed, calibration_fraction=float(sp["calibration_fraction"])
    )

    # ε on combo_calibration ONLY (development role); split-half by a seeded
    # permutation of each pair's double cells. Sealed regimes are never projected.
    rng = np.random.default_rng(split_seed)
    eps_full, eps_a, eps_b = [], [], []
    for g, h in split.combo_calibration:
        rows = np.asarray(doubles[(g, h)], dtype=int)
        perm = rng.permutation(rows.size)
        half = rows.size // 2
        idx_a, idx_b = rows[perm[:half]], rows[perm[half : 2 * half]]
        d_full = space.project(adata.X, rows).mean(axis=0)
        d_a = space.project(adata.X, idx_a).mean(axis=0)
        d_b = space.project(adata.X, idx_b).mean(axis=0)
        eps_full.append(d_full - delta[g] - delta[h])
        eps_a.append(d_a - delta[g] - delta[h])
        eps_b.append(d_b - delta[g] - delta[h])

    regime_pair_counts = {
        "combo_calibration": len(split.combo_calibration),
        "sealed_double_unseen": len(split.sealed_double_unseen),
        "sealed_single_unseen": len(split.sealed_single_unseen),
    }
    # Sealed regimes: outcome-INDEPENDENT cell-count metadata only (no projection).
    regime_cells_per_pair = {
        "sealed_double_unseen": _median_cells(doubles, split.sealed_double_unseen),
        "sealed_single_unseen": _median_cells(doubles, split.sealed_single_unseen),
        "combo_calibration": _median_cells(doubles, split.combo_calibration),
    }

    report = compute_regime_detectable_effect_report(
        eps_calibration=np.asarray(eps_full),
        eps_split_a=np.asarray(eps_a),
        eps_split_b=np.asarray(eps_b),
        regime_pair_counts=regime_pair_counts,
        regime_cells_per_pair=regime_cells_per_pair,
        min_pairs=min_pairs,
        min_cells=min_cells,
    )

    report_ready = report["measurability"]["passed"] and report["headline_powered"]
    activation = (
        "READY — registered measurability and headline power gates passed; "
        "sealed outcomes remain unread"
        if report_ready
        else "BLOCKED — measurability or registered headline power gate failed; no seal"
    )
    envelope = {
        "schema": DETECTABLE_EFFECT_ACTIVATION_SCHEMA,
        "protocol": "COMPOSE-K562-v1",
        "activation": activation,
        "generated_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "git_sha": str(args.git_sha),
        "config_sha256": sha256_json(raw),
        "phase1_config_sha256": phase1_config_sha256,
        "data_sha256": sha256_file(args.h5ad),
        "split_seed": split_seed,
        "calibration_fraction": float(sp["calibration_fraction"]),
        "regime_pair_counts": regime_pair_counts,
        "regime_cells_per_pair": regime_cells_per_pair,
        "report": report,
    }
    try:
        serialized = json.dumps(
            envelope, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
    except ValueError as exc:
        raise SystemExit("detectable-effect report contains a non-finite numeric value") from exc
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(serialized + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    m, e = report["measurability"], report["effect_size"]
    print(f"  measurability ceiling={m['ceiling']:.4f} passed={m['passed']}")
    print(f"  effect mean|eps|={e['mean_pair_eps_l2']:.4f} snr={e['signal_to_noise']:.3f}")
    for regime, r in report["regimes"].items():
        print(f"  {regime}: n={r['n_pairs']} power={r['power_passed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
