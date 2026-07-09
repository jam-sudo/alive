#!/usr/bin/env python
"""GEARS pseudobulk-approximation bias metric (§10.1 ``approximation_bias_report``).

The CPA baseline predicts per-cell (``cell_raw_counts``); GEARS predicts a
pseudobulk/mean vector (``raw_pseudobulk_approximation``). The frozen §2.2
response projection applies a NONLINEAR transform (library-size normalize to the
median library + ``log1p``) then an HVG subset + PCA. Because the transform is
nonlinear, projecting the pseudobulk mean of raw counts differs from projecting
each cell then averaging — a systematic "pseudobulk-approximation bias". This
script QUANTIFIES that representation gap on the NON-SEALED fit roles.

For each non-sealed group (control, each single, each ``combo_calibration`` pair
— grouped by ``(role, perturbation)`` in the fit-role artifact) with raw cell
counts ``raw`` over the block's gene order:

    delta_pb = z(mean_cells(raw)) - control_mean      # pseudobulk path
    delta_pc = mean_cells(z(raw)) - control_mean      # per-cell path
    b        = delta_pb - delta_pc                    # representation gap

where ``z`` is :func:`alive.compose.fit_role.apply_response_projection`. The
control-mean subtraction cancels in the difference, so ``b`` is purely the
aggregation gap on the group. It is nevertheless applied to both paths so
the relative-magnitude denominator is the registered perturbation effect
``delta_pc = mean(z(raw)) - control_mean``, not an origin-dependent PCA
coordinate.

This is a MODEL-INDEPENDENT, NON-SEALED activation-requirement report: it opens
NO seal, reads NO sealed outcome, fits NO model, imports no ``gears``/``cpa``,
and touches NO sealed cells (the input artifact has no sealed rows by
construction). It becomes ``baselines.gears.approximation_bias_report_sha256``;
the GPU pod runs it on real Norman, and it is unit-tested locally on synthetic
data.

Usage
-----
    uv run python scripts/compose/measure_pseudobulk_approximation_bias.py \
        --fit-role-artifact artifacts/compose/fit_role.h5ad \
        --response-projection artifacts/compose/response_projection.json \
        --out artifacts/compose/approximation_bias_report.json \
        --git-sha e5cfe05
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping
from pathlib import Path

import anndata as ad
import numpy as np
from scipy import sparse

from alive.compose.fit_role import apply_response_projection
from alive.provenance import sha256_file, sha256_json

#: Only finite floats or this string sentinel are ever embedded in the report
#: (CLAUDE.md#invariants / #data-eval — report the degenerate value honestly,
#: never a silent NaN; mirrors ``compose.phase2b._NON_FINITE_SENTINEL``).
_NON_FINITE_SENTINEL = "NON_FINITE"

_GROUP_KEY_SEP = "::"


def _finite_or_sentinel(value: float) -> float | str:
    """Return ``float(value)`` when finite, else :data:`_NON_FINITE_SENTINEL`."""
    number = float(value)
    return number if math.isfinite(number) else _NON_FINITE_SENTINEL


def _group_bias_vectors(
    artifact_path: str,
    block: Mapping,
) -> dict[str, dict[str, np.ndarray]]:
    """Compute the per-group representation gap ``b`` and per-cell delta.

    Reads ONLY the non-sealed fit-role artifact (control + singles +
    combo_calibration rows; no sealed rows by construction) and the frozen §2.2
    projection block. Groups the cells by ``(role, perturbation)`` and, for each
    group, returns the aggregation gap ``b = z(mean(raw)) - mean(z(raw))`` and
    the per-cell path delta ``mean(z(raw))``.

    Parameters
    ----------
    artifact_path : str
        Path to the fit-role ``.h5ad`` (obs carries ``role``/``perturbation``;
        ``X`` is raw counts over ``var_names``).
    block : Mapping
        A frozen ``response_projection`` block (spec §2.2). Its
        ``gene_order_sha256`` must match the artifact's ``var_names``.

    Returns
    -------
    dict of str to dict
        ``group_key -> {"b": ndarray (pca_dim,), "delta_pc": ndarray (pca_dim,)}``,
        keyed by ``f"{role}{sep}{perturbation}"``.
    """
    adata = ad.read_h5ad(artifact_path)
    roles = [str(r) for r in adata.obs["role"]]
    perts = [str(p) for p in adata.obs["perturbation"]]
    gene_order = [str(g) for g in adata.var_names]
    X = sparse.csr_matrix(adata.X)

    groups: dict[str, list[int]] = {}
    for i, (role, pert) in enumerate(zip(roles, perts, strict=True)):
        groups.setdefault(f"{role}{_GROUP_KEY_SEP}{pert}", []).append(i)

    out: dict[str, dict[str, np.ndarray]] = {}
    for key in sorted(groups):
        raw = np.asarray(X[groups[key]].toarray(), dtype=np.float64)
        control_mean = np.asarray(block["control_mean"], dtype=np.float64)
        delta_pb = (
            apply_response_projection(
                block,
                raw.mean(axis=0, keepdims=True),
                gene_order,
                representation="raw_pseudobulk_approximation",
            )[0]
            - control_mean
        )
        delta_pc = (
            apply_response_projection(
                block,
                raw,
                gene_order,
                representation="cell_raw_counts",
            ).mean(axis=0)
            - control_mean
        )
        out[key] = {"b": delta_pb - delta_pc, "delta_pc": delta_pc}
    return out


def measure_pseudobulk_approximation_bias(
    artifact_path: str,
    block: Mapping,
    *,
    git_sha: str,
) -> dict:
    """Quantify the GEARS pseudobulk-approximation bias on non-sealed roles.

    Parameters
    ----------
    artifact_path : str
        Path to the non-sealed fit-role ``.h5ad``.
    block : Mapping
        The frozen §2.2 ``response_projection`` block.
    git_sha : str
        Git SHA of the run, embedded for provenance.

    Returns
    -------
    dict
        The outcome-free bias report (canonical-JSON serialisable). Carries only
        group-level aggregates + provenance; NO sealed pair id, NO per-cell value,
        NO raw expression.
    """
    groups = _group_bias_vectors(artifact_path, block)
    keys = sorted(groups)
    stacked = np.stack([groups[k]["b"] for k in keys], axis=0)  # (n_groups, pca_dim)
    mean_b = stacked.mean(axis=0)
    directional_l2 = float(np.linalg.norm(mean_b))

    ratios: list[float] = []
    for k in keys:
        denom = float(np.linalg.norm(groups[k]["delta_pc"]))
        if math.isfinite(denom) and denom > 0.0:
            ratios.append(float(np.linalg.norm(groups[k]["b"])) / denom)
    rel_median = _finite_or_sentinel(float(np.median(ratios))) if ratios else _NON_FINITE_SENTINEL
    rel_max = _finite_or_sentinel(float(np.max(ratios))) if ratios else _NON_FINITE_SENTINEL

    return {
        "deliverable": "gears_pseudobulk_approximation_bias_report",
        "protocol": "COMPOSE-K562-v1",
        "seal_status": (
            "NO_SEAL_OPENED — non-sealed roles only; model-independent "
            "(frozen §2.2 projection); no model fit; no sealed outcome read"
        ),
        "method": (
            "per (role, perturbation) group over non-sealed fit roles: "
            "b = z(mean_cells(raw)) - mean_cells(z(raw)) with z = frozen §2.2 "
            "normalize_total_median+log1p then HVG+PCA (control_mean cancels in "
            "the difference). directional_bias_l2 = ||mean_g b|| (non-cancelling "
            "component); relative_magnitude = ||b|| / "
            "||mean_cells(z(raw)) - control_mean|| over "
            "groups with non-zero per-cell delta."
        ),
        "git_sha": str(git_sha),
        "gene_order_sha256": str(block["gene_order_sha256"]),
        "pca_dim": int(len(block["control_mean"])),
        "fit_role_artifact_sha256": sha256_file(artifact_path),
        "response_projection_sha256": sha256_json(block),
        "roles_measured": sorted({k.split(_GROUP_KEY_SEP, 1)[0] for k in keys}),
        "n_groups": len(keys),
        "group_roster": keys,
        "directional_bias_l2": _finite_or_sentinel(directional_l2),
        "directional_bias_per_dim": [_finite_or_sentinel(float(v)) for v in mean_b],
        "relative_magnitude_median": rel_median,
        "relative_magnitude_max": rel_max,
    }


def main(argv: list[str] | None = None) -> int:
    """Load the artifact + block, compute the report, and write canonical JSON."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fit-role-artifact", required=True, type=Path)
    ap.add_argument("--response-projection", required=True, type=Path, help="§2.2 block JSON")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--git-sha", default="UNKNOWN")
    args = ap.parse_args(argv)

    block = json.loads(args.response_projection.read_text(encoding="utf-8"))
    report = measure_pseudobulk_approximation_bias(
        str(args.fit_role_artifact), block, git_sha=str(args.git_sha)
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {args.out}: n_groups={report['n_groups']} "
        f"directional_bias_l2={report['directional_bias_l2']} "
        f"relative_magnitude_max={report['relative_magnitude_max']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
