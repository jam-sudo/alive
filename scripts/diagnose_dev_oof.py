#!/usr/bin/env python
"""Diagnose why the Trust-Gate ranked error the way it did — on the OOF surface.

Thin CLI over :mod:`alive.eval.diagnostics`.  Reads the ``develop``-stage
artifacts (``methodlock.json`` + ``dev_errors.npz``) from a run directory and
reports, per method, the Spearman correlation between its UQ score and the
realised per-perturbation error, plus the feature-vs-residual partial
correlations (the registered ``added_value`` question) and the gate's most
overconfident misses.

This is **read-only** and operates only on the *development* surface, which is
not sealed under the ``TG-K562-v1`` seal contract (CLAUDE.md §6.1).  It does
not touch, re-open, or slice the sealed cohort; the registered verdict is
immutable.

Usage
-----
    uv run python scripts/diagnose_dev_oof.py \
        --run-dir /workspace/alive_artifacts_full/cartographer/d18c601b6855b3b1

    # write the structured summary to JSON as well
    uv run python scripts/diagnose_dev_oof.py --run-dir <dir> --json-out diag.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from alive.eval.diagnostics import diagnose_oof, load_oof_table


def _fmt(x: float) -> str:
    return f"{x:+.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        required=True,
        type=Path,
        help="Per-run artifacts directory written by `alive cartographer develop`.",
    )
    parser.add_argument(
        "--feature-method", default="nearest_feature", help="R1 (feature-distance) comparator name."
    )
    parser.add_argument(
        "--residual-method", default="residual_only", help="R4 (local-residual) comparator name."
    )
    parser.add_argument("--gate-method", default="gate", help="Combined gate method name.")
    parser.add_argument(
        "--ensemble-method",
        default="ensemble_disagreement",
        help="Ensemble-disagreement comparator name.",
    )
    parser.add_argument(
        "--top-k", type=int, default=10, help="Number of overconfident misses to list."
    )
    parser.add_argument(
        "--json-out", type=Path, default=None, help="Optional path to write the summary as JSON."
    )
    args = parser.parse_args(argv)

    ids, errors, oof_scores = load_oof_table(args.run_dir)
    out = diagnose_oof(
        ids,
        errors,
        oof_scores,
        feature_method=args.feature_method,
        residual_method=args.residual_method,
        gate_method=args.gate_method,
        ensemble_method=args.ensemble_method,
        top_k_overconfident=args.top_k,
    )

    print(f"# OOF diagnostics — {args.run_dir}")
    print(f"n_dev_perturbations = {out['n']}")
    print()
    print("## Per-method: Spearman(score, error)  [higher = score tracks error]  + recomputed AURC")
    ranked = sorted(out["per_method"].items(), key=lambda kv: kv[1]["spearman"], reverse=True)
    width = max(len(m) for m, _ in ranked)
    for method, stats in ranked:
        print(f"  {method:<{width}}  spearman={_fmt(stats['spearman'])}  aurc={stats['aurc']:.4f}")
    print()
    av = out["added_value"]
    feat_given_resid = _fmt(av["partial_feature_given_residual"])
    resid_given_feat = _fmt(av["partial_residual_given_feature"])
    redundancy = _fmt(av["corr_feature_residual"])
    print("## Added value of the feature axis (R1) over the residual axis (R4)")
    print(f"  partial spearman(feature, error | residual) = {feat_given_resid}")
    print(f"  partial spearman(residual, error | feature) = {resid_given_feat}")
    print(f"  spearman(feature, residual) [redundancy]    = {redundancy}")
    print()
    print(f"## Gate's most overconfident misses (high error, low/trusted score) — top {args.top_k}")
    if not out["overconfident"]:
        print("  (none flagged)")
    for row in out["overconfident"]:
        print(f"  {row['id']:<16}  error={row['error']:.4f}  gate_score={row['score']:.4f}")

    if args.json_out is not None:
        args.json_out.write_text(json.dumps(out, indent=2, sort_keys=True))
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
