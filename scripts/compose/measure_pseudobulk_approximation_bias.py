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

Bootstrap replicate-count decision (design spec §3 "Finite-sample uncertainty"):
:func:`_bootstrap_intervals` takes an explicit ``replicates`` count from its
caller. The CLI (wired in a later task) exposes this as a DEDICATED
``--bootstrap-replicates`` argument defaulting to 2000, recorded verbatim as
the report's ``replicates_requested``. This is deliberately NOT
``configs/compose_k562_v1_phase2.yaml::baselines.method.bootstrap_replicates``
(10000) -- that value calibrates the SEALED evaluation-outcome bootstrap over
held-out predictions, a different estimand computed over a different
population than this non-sealed fit-role fairness-ratio interval. Reusing it
here would silently conflate two distinct bootstraps under one number.

Usage
-----
    uv run python scripts/compose/measure_pseudobulk_approximation_bias.py \
        --fit-role-artifact artifacts/compose/fit_role.h5ad \
        --response-projection artifacts/compose/response_projection.json \
        --sealed-pair-ids artifacts/compose/sealed_pair_ids.json \
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

from alive.compose.fit_role import apply_response_projection, canonical_gene_order_sha256
from alive.provenance import sha256_file, sha256_json

#: Only finite floats or this string sentinel are ever embedded in the report
#: (CLAUDE.md#invariants / #data-eval — report the degenerate value honestly,
#: never a silent NaN; mirrors ``compose.phase2b._NON_FINITE_SENTINEL``).
_NON_FINITE_SENTINEL = "NON_FINITE"

_GROUP_KEY_SEP = "::"

#: Pre-registered fairness threshold (design spec §5): ``R >= _R_STAR`` marks the
#: sealed GEARS family-comparator interpretation ``"representation_confounded"``.
_R_STAR = 0.5

#: The v1 measurement entry's measured-role whitelist (design spec §3 "Seal
#: safety"). Deliberately narrower than ``fit_role``'s overall allowed-role set
#: (which also permits ``control`` as a reference-only row): ``control`` may
#: legitimately exist in a fit-role artifact for ``control_mean`` provenance,
#: but must NEVER be presented as a *measured* pair to this metric.
_MEASURED_ROLES: frozenset[str] = frozenset({"singles", "combo_calibration"})


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


def _split_bootstrap_replicates(replicates: int, n_seeds: int) -> list[int]:
    """Deterministically split ``replicates`` total draws across ``n_seeds`` seeds.

    ``base, remainder = divmod(replicates, n_seeds)``; the first ``remainder`` seeds
    (in the caller's ``seeds`` order) get ``base + 1`` draws, the rest get ``base`` --
    so the split depends only on ``replicates`` and the ORDER of ``seeds``, never on
    any additional randomness, and always sums to exactly ``replicates``.
    """
    if n_seeds <= 0:
        raise ValueError("_bootstrap_intervals requires at least one seed")
    base, remainder = divmod(replicates, n_seeds)
    return [base + 1 if i < remainder else base for i in range(n_seeds)]


def _bootstrap_intervals(
    combo_pairs: Mapping[str, np.ndarray],
    single_effects: Mapping[str, np.ndarray],
    block: Mapping,
    gene_order: Sequence[str],
    *,
    seeds: Sequence[int],
    replicates: int,
    combo_sep: str = "_",
) -> dict:
    """Two-stage nonparametric bootstrap 95% interval for the GI fairness statistics.

    Registered-seed, byte-reproducible finite-sample uncertainty for
    ``floor_median``, ``gi_signal_median``, and ``bias_to_signal_ratio_R`` (design
    spec §3 "Finite-sample uncertainty"). Each replicate: (a) resamples
    ``combo_calibration`` pair IDs WITH REPLACEMENT (``n_pairs`` draws), then (b)
    resamples cells WITH REPLACEMENT within each sampled pair's own observed cell
    matrix, then recomputes the three statistics on that resampled data via
    :func:`_gi_and_fairness` -- the SAME ratio-of-medians aggregation as the point
    estimate, not a re-derived formula. ``single_effects`` (the additive-null
    delta_g/delta_h baseline from :func:`_single_effects`) is held FIXED across
    every replicate: only the ``combo_calibration`` cells are resampled, because the
    finite-sample question this interval answers is "how much does the observed
    combo_calibration SAMPLE (of pairs, and of cells within each pair) move the
    fairness ratio", not "how much would the single-role delta_g/delta_h estimate
    itself move" -- resampling singles too would conflate two different estimands
    into one interval.

    Replicate count: ``replicates`` is a DEDICATED bootstrap-interval draw count,
    never silently taken from
    ``configs/compose_k562_v1_phase2.yaml::baselines.method.bootstrap_replicates``
    (10000) -- see the module docstring. The CLI wires this as
    ``--bootstrap-replicates`` (default 2000) in a later task; this function always
    requires an explicit ``replicates`` from its caller.

    Determinism: ``seeds`` (the config's ``seeds.registered_seeds``) are consumed
    via ``np.random.default_rng(seed)`` in the given order, each producing a fixed
    deterministic share of ``replicates`` (:func:`_split_bootstrap_replicates`).
    Neither ``combo_pairs`` nor ``single_effects`` is ever mutated, so
    byte-identical inputs + ``seeds`` + ``replicates`` always yield byte-identical
    output, and calling this function never perturbs a separately-computed point
    estimate (the point estimate takes no RNG input at all).

    A resampled pair drawn more than once within one replicate is kept as DISTINCT
    occurrences (each with its own independently-resampled cell subsample) by
    giving each occurrence a unique salted key
    (``f"{gene_a}~{occurrence}{combo_sep}{gene_b}~{occurrence}"``) with a
    correspondingly salted copy of ``single_effects`` for that occurrence's two
    genes. This lets ONE call to :func:`_gi_and_fairness` per replicate compute
    every occurrence's ``b_i``/``g_i`` and their ratio-of-medians aggregation
    exactly as the point estimate would, including a duplicate pair contributing
    independently (twice) to the replicate's median.

    Parameters
    ----------
    combo_pairs : mapping of str to numpy.ndarray
        ``pair_id -> raw cell matrix`` for ``combo_calibration`` (the OBSERVED
        sample; never mutated).
    single_effects : mapping of str to numpy.ndarray
        ``gene_id -> delta_g``, as returned by :func:`_single_effects`; held fixed
        across every replicate (never mutated or resampled).
    block : Mapping
        The frozen ``response_projection`` block (spec §2.2).
    gene_order : sequence of str
        The full gene-ID order of every raw matrix.
    seeds : sequence of int
        The registered seed roster
        (``configs/compose_k562_v1_phase2.yaml::seeds.registered_seeds``),
        consumed in order.
    replicates : int
        Total bootstrap replicate count (becomes ``replicates_requested``).
    combo_sep : str, default ``"_"``
        Separator between a pair id's two constituent gene tokens.

    Returns
    -------
    dict
        ``{"bootstrap_95_interval": {"floor_median": [lo, hi] | "NON_FINITE",
        "gi_signal_median": [lo, hi] | "NON_FINITE",
        "bias_to_signal_ratio_R": [lo, hi] | "NON_FINITE"},
        "replicates_requested": int, "replicates_finite": int,
        "replicates_non_finite": int}``. ``replicates_finite +
        replicates_non_finite == replicates_requested`` always holds. A replicate
        is finite iff its resampled ``bias_to_signal_ratio_R`` is a finite number
        (a zero-GI-denominator draw makes the ratio non-finite via
        :func:`_safe_ratio`, which requires BOTH ``floor_median`` and
        ``gi_signal_median`` to already be finite -- so a finite ratio implies the
        other two are finite too). A non-finite replicate is excluded from all
        three interval computations but is always counted, never silently
        dropped. Interval endpoints are the 2.5th/97.5th percentiles over the
        FINITE replicates for that statistic, or the string sentinel
        :data:`_NON_FINITE_SENTINEL` when zero replicates are finite.
    """
    pair_ids = sorted(combo_pairs)
    n_pairs = len(pair_ids)
    replicate_counts = _split_bootstrap_replicates(replicates, len(seeds))

    floor_vals: list[float] = []
    gi_vals: list[float] = []
    ratio_vals: list[float] = []
    replicates_finite = 0
    replicates_non_finite = 0

    for seed, n_rep in zip(seeds, replicate_counts, strict=True):
        rng = np.random.default_rng(seed)
        for _ in range(n_rep):
            resampled_combo: dict[str, np.ndarray] = {}
            resampled_singles: dict[str, np.ndarray] = dict(single_effects)
            if n_pairs > 0:
                drawn = rng.integers(0, n_pairs, size=n_pairs)
                for occurrence, idx in enumerate(drawn):
                    pair_id = pair_ids[int(idx)]
                    gene_a, gene_b = pair_id.split(combo_sep, 1)
                    raw = np.asarray(combo_pairs[pair_id], dtype=np.float64)
                    n_cells = raw.shape[0]
                    cell_idx = rng.integers(0, n_cells, size=n_cells)
                    key_a, key_b = f"{gene_a}~{occurrence}", f"{gene_b}~{occurrence}"
                    resampled_combo[f"{key_a}{combo_sep}{key_b}"] = raw[cell_idx, :]
                    resampled_singles[key_a] = single_effects[gene_a]
                    resampled_singles[key_b] = single_effects[gene_b]

            if resampled_combo:
                rep = _gi_and_fairness(
                    resampled_combo, resampled_singles, block, gene_order, combo_sep=combo_sep
                )
                floor_rep = rep["floor_median"]
                gi_rep = rep["gi_signal_median"]
                ratio_rep = rep["bias_to_signal_ratio_R"]
            else:
                floor_rep = gi_rep = ratio_rep = _NON_FINITE_SENTINEL

            if isinstance(ratio_rep, float) and math.isfinite(ratio_rep):
                replicates_finite += 1
                floor_vals.append(floor_rep)
                gi_vals.append(gi_rep)
                ratio_vals.append(ratio_rep)
            else:
                replicates_non_finite += 1

    def _interval(values: list[float]) -> list[float] | str:
        if not values:
            return _NON_FINITE_SENTINEL
        lo, hi = np.percentile(values, [2.5, 97.5])
        return [_finite_or_sentinel(float(lo)), _finite_or_sentinel(float(hi))]

    return {
        "bootstrap_95_interval": {
            "floor_median": _interval(floor_vals),
            "gi_signal_median": _interval(gi_vals),
            "bias_to_signal_ratio_R": _interval(ratio_vals),
        },
        "replicates_requested": int(replicates),
        "replicates_finite": replicates_finite,
        "replicates_non_finite": replicates_non_finite,
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


def measure_approximation_bias_v1(
    *,
    fit_role_artifact: str,
    response_projection: Mapping,
    sealed_pair_ids: Sequence[str],
) -> dict:
    """Guards-only v1 measurement entry (design spec §3 "Seal safety (fail-closed)").

    Task 3 of the COMPOSE approximation-bias v1 implementation plan
    (``docs/superpowers/plans/2026-07-13-compose-approximation-bias-implementation.md``):
    this is the metric's OWN fail-closed gate, run BEFORE any projection is
    computed for the v1 report. In order:

    (a) every measured row's ``role`` must be in ``{"singles",
        "combo_calibration"}`` — a ``control``-role row (or any other
        non-whitelisted role) presented as a measured input aborts. This is
        checked against the artifact's RAW roles, never through
        :func:`_stratify_by_role` (which silently *drops* ``control`` — the
        right behavior for stratification, the wrong one for a seal-safety
        gate, which must fail closed rather than fail silent);
    (b) once (a) has passed, the measured perturbation-id roster (every row's
        ``perturbation``) must have ZERO overlap with ``sealed_pair_ids``. The
        overlap count is recomputed here — never trusted from an upstream
        builder — and returned for the report;
    (c) the artifact's gene order must match the frozen ``response_projection``
        block's ``gene_order_sha256``, verified UP FRONT. (``apply_response_projection``
        also re-checks this digest, but only deep inside the projection math —
        not a clean, early, metric-owned abort.)

    Report assembly (strata, GI/fairness, bootstrap, provenance,
    ``self_checksum``) is Task 4's job; the Probe-A admission gate is Task 5's
    (YAGNI here — this function performs NO projection at all; once every
    guard passes it returns only the recomputed overlap count).

    Parameters
    ----------
    fit_role_artifact : str
        Path to the fit-role ``.h5ad`` (``obs`` carries ``role`` /
        ``perturbation``; ``var_names`` is the full gene order).
    response_projection : Mapping
        The frozen ``response_projection`` block (spec §2.2); must carry
        ``gene_order_sha256``.
    sealed_pair_ids : sequence of str
        The sealed double-unseen pair-id roster (already-canonicalized combo
        tokens, e.g. ``"GENEA_GENEB"``) — a measured row whose ``perturbation``
        is a member aborts.

    Returns
    -------
    dict
        ``{"sealed_pair_overlap_count": 0}`` once every guard has passed.

    Raises
    ------
    ValueError
        ``"approximation-bias: measured role must be singles|combo_calibration"``
        for guard (a); ``"approximation-bias: measured roster overlaps
        sealed_pair_ids"`` for guard (b); ``"approximation-bias: gene_order
        digest mismatch"`` for guard (c).
    """
    block = response_projection
    adata = ad.read_h5ad(fit_role_artifact)
    roles = [str(r) for r in adata.obs["role"]]
    perturbations = [str(p) for p in adata.obs["perturbation"]]
    gene_order = [str(g) for g in adata.var_names]

    if not set(roles) <= _MEASURED_ROLES:
        raise ValueError("approximation-bias: measured role must be singles|combo_calibration")

    sealed_pair_overlap_count = len(set(perturbations) & set(sealed_pair_ids))
    if sealed_pair_overlap_count != 0:
        raise ValueError("approximation-bias: measured roster overlaps sealed_pair_ids")

    if canonical_gene_order_sha256(gene_order) != str(block["gene_order_sha256"]):
        raise ValueError("approximation-bias: gene_order digest mismatch")

    return {"sealed_pair_overlap_count": sealed_pair_overlap_count}


def main(argv: list[str] | None = None) -> int:
    """Load the artifact + block, run seal-safety guards, compute the report, write canonical JSON.

    ``--sealed-pair-ids`` is a required JSON-list-of-str file (design spec §3);
    :func:`measure_approximation_bias_v1`'s guards run BEFORE the legacy
    aggregate report below is computed, and the recomputed
    ``sealed_pair_overlap_count`` (must be ``0``) is recorded alongside it.
    Full v1 report assembly (self_checksum, provenance, Probe-A admission)
    lands in a later task; this CLI wiring is intentionally incremental.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fit-role-artifact", required=True, type=Path)
    ap.add_argument("--response-projection", required=True, type=Path, help="§2.2 block JSON")
    ap.add_argument(
        "--sealed-pair-ids",
        required=True,
        type=Path,
        help="JSON list of sealed pair-id tokens (design spec §3 seal-safety guard)",
    )
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--git-sha", default="UNKNOWN")
    args = ap.parse_args(argv)

    block = json.loads(args.response_projection.read_text(encoding="utf-8"))
    sealed_pair_ids = json.loads(args.sealed_pair_ids.read_text(encoding="utf-8"))

    guard_result = measure_approximation_bias_v1(
        fit_role_artifact=str(args.fit_role_artifact),
        response_projection=block,
        sealed_pair_ids=sealed_pair_ids,
    )
    report = measure_pseudobulk_approximation_bias(
        str(args.fit_role_artifact), block, git_sha=str(args.git_sha)
    )
    report["sealed_pair_overlap_count"] = guard_result["sealed_pair_overlap_count"]

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
