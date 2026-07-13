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
from collections.abc import Mapping, Sequence
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

#: Pre-registered fairness threshold (design spec §5): ``R >= _R_STAR`` marks the
#: sealed GEARS family-comparator interpretation ``"representation_confounded"``.
_R_STAR = 0.5


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


def _safe_ratio(numerator: float, denominator: float) -> float:
    """Return ``numerator / denominator``, or ``math.nan`` if that is ill-defined.

    Ill-defined means either operand is non-finite or ``denominator == 0.0``
    (a zero-GI-denominator pair is recorded as ``NON_FINITE``, never silently
    dropped or treated as an arbitrary large ratio).
    """
    if math.isfinite(numerator) and math.isfinite(denominator) and denominator != 0.0:
        return numerator / denominator
    return math.nan


def _stratify_by_role(
    roles: Sequence[str],
    perturbations: Sequence[str],
    X: np.ndarray,
    *,
    control_token: str = "control",
) -> dict[str, dict[str, np.ndarray]]:
    """Group raw rows by fit role into per-pair / per-gene raw cell matrices.

    Only rows whose role is ``"combo_calibration"`` or ``"singles"`` are kept;
    ``control_token`` rows (and any other role) are dropped — ``control`` is
    reference-only via the frozen projection block's ``control_mean`` and is
    NEVER a measured pair (CLAUDE.md invariants; spec §3 "Populations"). This
    is stratification only: the seal-safety fail-closed rejection of a
    ``sealed_pair_ids`` member is Task 3's guard, not built here (YAGNI).

    Parameters
    ----------
    roles : sequence of str
        Per-row fit role (``adata.obs["role"]`` values).
    perturbations : sequence of str
        Per-row canonical perturbation token (``adata.obs["perturbation"]``); a
        combo token is already byte-canonicalized as ``"{gene_a}{sep}{gene_b}"``
        upstream (spec §3.2 / ``fit_role.py``).
    X : numpy.ndarray
        Raw counts, shape ``(n_rows, n_genes)``, row-aligned with ``roles``.

    Returns
    -------
    dict of str to dict
        ``{"combo_calibration": {pair_id: raw_matrix}, "singles": {gene_id: raw_matrix}}``.

    Raises
    ------
    ValueError
        If ``roles``, ``perturbations``, and ``X`` do not have matching row counts.
    """
    X = np.asarray(X, dtype=np.float64)
    if len(roles) != len(perturbations) or len(roles) != X.shape[0]:
        raise ValueError("roles, perturbations, and X must have matching row counts")

    row_idx: dict[str, dict[str, list[int]]] = {"combo_calibration": {}, "singles": {}}
    for i, (role, pert) in enumerate(zip(roles, perturbations, strict=True)):
        if role == control_token or role not in row_idx:
            continue
        row_idx[role].setdefault(str(pert), []).append(i)

    return {
        stratum: {key: X[idx, :] for key, idx in keys.items()} for stratum, keys in row_idx.items()
    }


def _stratum_bias(
    rows_by_pair: Mapping[str, np.ndarray],
    block: Mapping,
    gene_order: Sequence[str],
) -> dict:
    """Per-pair (or per-gene) pseudobulk-approximation bias for one stratum.

    For each ``key -> raw_cell_matrix`` entry, projects the population-mean row
    via ``"raw_pseudobulk_approximation"`` and the individual cells via
    ``"cell_raw_counts"`` (both through the SAME frozen ``block``), and reports
    the representation-floor bias vector ``bias_i = z(mean_cells(raw)) -
    mean_cells(z(raw))`` (design spec §2 — ``control_mean`` cancels in this
    difference and is not subtracted here) and ``b_i = p^-1 ||bias_i||_2^2``
    (mean of squares).

    Parameters
    ----------
    rows_by_pair : mapping of str to numpy.ndarray
        ``pair_id -> raw cell matrix`` (shape ``(n_cells, n_genes)``) for one
        stratum; the key is a gene id for the ``singles`` stratum.
    block : Mapping
        The frozen ``response_projection`` block (spec §2.2): ``median_library``,
        ``hvg_gene_ids``, ``pca_mean``, ``pca_components``, ``gene_order_sha256``.
    gene_order : sequence of str
        The full gene-ID order of every raw matrix; must match the block's
        ``gene_order_sha256`` (enforced by :func:`apply_response_projection`).

    Returns
    -------
    dict
        ``{"n_pairs": int, "per_pair": [{"pair_id", "b_i"}, ...] (sorted by
        pair_id), "b_distribution": {"median", "mean", "max", "q90"},
        "signed_pc_bias": [float, ...]}``. Every float leaf is finite or the
        string sentinel :data:`_NON_FINITE_SENTINEL`.
    """
    pair_ids = sorted(rows_by_pair)
    per_pair: list[dict] = []
    bias_vectors: list[np.ndarray] = []
    for pair_id in pair_ids:
        raw = np.asarray(rows_by_pair[pair_id], dtype=np.float64)
        mean_row = raw.mean(axis=0, keepdims=True)
        z_pseudobulk = apply_response_projection(
            block, mean_row, gene_order, representation="raw_pseudobulk_approximation"
        )[0]
        z_per_cell = apply_response_projection(
            block, raw, gene_order, representation="cell_raw_counts"
        ).mean(axis=0)
        bias_i = z_pseudobulk - z_per_cell
        bias_vectors.append(bias_i)
        per_pair.append({"pair_id": pair_id, "b_i": _finite_or_sentinel(float(np.mean(bias_i**2)))})

    finite_b = [entry["b_i"] for entry in per_pair if isinstance(entry["b_i"], float)]
    if finite_b:
        b_distribution = {
            "median": _finite_or_sentinel(float(np.median(finite_b))),
            "mean": _finite_or_sentinel(float(np.mean(finite_b))),
            "max": _finite_or_sentinel(float(np.max(finite_b))),
            "q90": _finite_or_sentinel(float(np.quantile(finite_b, 0.9))),
        }
    else:
        b_distribution = dict.fromkeys(("median", "mean", "max", "q90"), _NON_FINITE_SENTINEL)

    signed_pc_bias = (
        [_finite_or_sentinel(float(v)) for v in np.mean(np.stack(bias_vectors), axis=0)]
        if bias_vectors
        else []
    )

    return {
        "n_pairs": len(pair_ids),
        "per_pair": per_pair,
        "b_distribution": b_distribution,
        "signed_pc_bias": signed_pc_bias,
    }


def _single_effects(
    singles_rows_by_gene: Mapping[str, np.ndarray],
    block: Mapping,
    gene_order: Sequence[str],
) -> dict[str, np.ndarray]:
    """Per-gene single-perturbation truth effect (additive-null input).

    ``delta_g = mean_cells(z(cells_raw)) - control_mean`` using the exact
    per-cell representation (``"cell_raw_counts"``) — a truth response, not a
    bias/floor measurement.

    Parameters
    ----------
    singles_rows_by_gene : mapping of str to numpy.ndarray
        ``gene_id -> raw cell matrix`` for the ``singles`` stratum.
    block : Mapping
        The frozen ``response_projection`` block (spec §2.2).
    gene_order : sequence of str
        The full gene-ID order of every raw matrix.

    Returns
    -------
    dict of str to numpy.ndarray
        ``gene_id -> delta_g``, shape ``(pca_dim,)``.
    """
    control_mean = np.asarray(block["control_mean"], dtype=np.float64)
    out: dict[str, np.ndarray] = {}
    for gene, raw in singles_rows_by_gene.items():
        z_per_cell = apply_response_projection(
            block, np.asarray(raw, dtype=np.float64), gene_order, representation="cell_raw_counts"
        )
        out[gene] = z_per_cell.mean(axis=0) - control_mean
    return out


def _gi_and_fairness(
    combo_pairs: Mapping[str, np.ndarray],
    single_effects: Mapping[str, np.ndarray],
    block: Mapping,
    gene_order: Sequence[str],
    *,
    combo_sep: str = "_",
) -> dict:
    """GI residual, ratio-of-medians fairness ratio, and the pre-registered flag.

    Computed on ``combo_calibration`` only (design spec §4/§5). For each combo
    pair, decomposes its ``pair_id`` into its two constituent genes on
    ``combo_sep``, forms the additive-null residual ``eps_i = delta_i -
    (delta_g + delta_h)`` (``delta_i`` uses the exact ``"cell_raw_counts"``
    path; ``control_mean`` cancels), and reports ``g_i = p^-1 ||eps_i||_2^2``.
    ``floor_median`` reuses the SAME pairs' ``b_i`` via :func:`_stratum_bias` so
    the ratio and the reported per-pair bias are computed identically.
    ``bias_to_signal_ratio_R`` is the **ratio of medians**
    (``floor_median / gi_signal_median``), not the median of per-pair ratios
    (reported separately as ``bias_to_signal_ratio_per_pair_median``, a
    secondary robustness view) — the ratio-of-medians is the pre-registered
    primitive that drives ``fairness_flag`` and stays stable when some ``g_i``
    is near zero.

    Parameters
    ----------
    combo_pairs : mapping of str to numpy.ndarray
        ``pair_id -> raw cell matrix`` for ``combo_calibration``.
    single_effects : mapping of str to numpy.ndarray
        ``gene_id -> delta_g``, as returned by :func:`_single_effects`; must
        cover every gene named by every ``combo_pairs`` key.
    block : Mapping
        The frozen ``response_projection`` block (spec §2.2).
    gene_order : sequence of str
        The full gene-ID order of every raw matrix.
    combo_sep : str, default ``"_"``
        Separator between a pair id's two constituent gene tokens (the
        config's ``data.combo_sep``).

    Returns
    -------
    dict
        ``{"gi_signal_per_pair": [{"pair_id", "g_i"}, ...] (sorted by pair_id),
        "gi_signal_median", "floor_median", "bias_to_signal_ratio_R",
        "bias_to_signal_ratio_per_pair_median", "R_star", "fairness_flag"}``.
        Every float leaf is finite or the string sentinel
        :data:`_NON_FINITE_SENTINEL`; ``fairness_flag`` is derived from the
        raw (pre-sentinel) ratio.
    """
    control_mean = np.asarray(block["control_mean"], dtype=np.float64)
    stratum = _stratum_bias(combo_pairs, block, gene_order)
    b_by_pair = {entry["pair_id"]: entry["b_i"] for entry in stratum["per_pair"]}

    pair_ids = sorted(combo_pairs)
    gi_per_pair: list[dict] = []
    g_by_pair: dict[str, float] = {}
    for pair_id in pair_ids:
        gene_a, gene_b = pair_id.split(combo_sep, 1)
        raw = np.asarray(combo_pairs[pair_id], dtype=np.float64)
        delta_i = (
            apply_response_projection(
                block, raw, gene_order, representation="cell_raw_counts"
            ).mean(axis=0)
            - control_mean
        )
        eps_i = delta_i - (single_effects[gene_a] + single_effects[gene_b])
        g_i = float(np.mean(eps_i**2))
        g_by_pair[pair_id] = g_i
        gi_per_pair.append({"pair_id": pair_id, "g_i": _finite_or_sentinel(g_i)})

    finite_b = [b_by_pair[p] for p in pair_ids if isinstance(b_by_pair[p], float)]
    finite_g = [g_by_pair[p] for p in pair_ids if math.isfinite(g_by_pair[p])]
    floor_median = float(np.median(finite_b)) if finite_b else math.nan
    gi_signal_median = float(np.median(finite_g)) if finite_g else math.nan

    ratio_r = _safe_ratio(floor_median, gi_signal_median)
    per_pair_ratios = [
        _safe_ratio(b_by_pair[p], g_by_pair[p])
        for p in pair_ids
        if isinstance(b_by_pair[p], float) and math.isfinite(g_by_pair[p])
    ]
    finite_per_pair_ratios = [r for r in per_pair_ratios if math.isfinite(r)]
    per_pair_median = (
        float(np.median(finite_per_pair_ratios)) if finite_per_pair_ratios else math.nan
    )

    # A non-finite ratio (undetermined floor/GI-signal median) never claims
    # confoundedness; it honestly falls back to "clear" (CLAUDE.md invariants
    # — do not overclaim on a degenerate/undefined comparison).
    fairness_flag = (
        "representation_confounded" if math.isfinite(ratio_r) and ratio_r >= _R_STAR else "clear"
    )

    return {
        "gi_signal_per_pair": gi_per_pair,
        "gi_signal_median": _finite_or_sentinel(gi_signal_median),
        "floor_median": _finite_or_sentinel(floor_median),
        "bias_to_signal_ratio_R": _finite_or_sentinel(ratio_r),
        "bias_to_signal_ratio_per_pair_median": _finite_or_sentinel(per_pair_median),
        "R_star": _R_STAR,
        "fairness_flag": fairness_flag,
    }


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
