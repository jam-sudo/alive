#!/usr/bin/env python
"""Thin CLI over alive.compose.phase1 (COMPOSE-K562-v1 Phase 1).

Synthetic recovery + dev-only gate inputs come from a profiled Norman split;
this script wires them and writes the go/no-go report through a write-once run
dir. Phase 1 opens no seal. See docs/superpowers/plans/2026-06-23-compose-phase1.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from alive.compose.config import load_compose_config
from alive.compose.phase1 import run_phase1, write_phase1


def main(argv: list[str] | None = None) -> int:
    """Wire gate inputs, run Phase 1, and write the write-once report."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--n-double-unseen-pairs", required=True, type=int)
    ap.add_argument("--cells-per-pair", required=True, type=float)
    ap.add_argument("--eps-split-a", required=True, type=Path, help=".npy dev split-half A")
    ap.add_argument("--eps-split-b", required=True, type=Path, help=".npy dev split-half B")
    args = ap.parse_args(argv)
    cfg = load_compose_config(args.config)
    gate_inputs = {
        "n_double_unseen_pairs": args.n_double_unseen_pairs,
        "cells_per_pair": args.cells_per_pair,
        "eps_split_a": np.load(args.eps_split_a),
        "eps_split_b": np.load(args.eps_split_b),
    }
    rep = run_phase1(cfg, gate_inputs=gate_inputs)
    write_phase1(rep, args.out_dir)
    print(
        f"method_axis={rep.method_axis} headline={rep.headline_regime} "
        f"go_no_go={rep.go_no_go}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
