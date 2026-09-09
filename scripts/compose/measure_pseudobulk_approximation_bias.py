#!/usr/bin/env python
"""GEARS pseudobulk-approximation bias metric (§10.1 ``approximation_bias_report``).

The CPA baseline predicts per-cell (``cell_raw_counts``); GEARS predicts a
pseudobulk/mean vector (``raw_pseudobulk_approximation``). The frozen §2.2
response projection applies a NONLINEAR transform (library-size normalize to the
median library + ``log1p``) then an HVG subset + PCA. Because the transform is
nonlinear, projecting the pseudobulk mean of raw counts differs from projecting
each cell then averaging — a systematic "pseudobulk-approximation bias". This
script QUANTIFIES that representation gap on the NON-SEALED fit roles.

For each measured non-sealed group (each single and each
``combo_calibration`` pair — grouped by ``(role, perturbation)`` in the
fit-role artifact) with raw cell counts ``raw`` over the block's gene order:

    delta_pb = z(mean_cells(raw)) - control_mean      # pseudobulk path
    delta_pc = mean_cells(z(raw)) - control_mean      # per-cell path
    b        = delta_pb - delta_pc                    # representation gap

where ``z`` is :func:`alive.compose.fit_role.apply_response_projection`. The
control-mean subtraction cancels in the difference, so ``b`` is purely the
aggregation gap on the group. Control rows may exist in the authoritative
fit-role artifact, but they are reference-only and excluded from every
measured stratum and GI roster.

This is a MODEL-INDEPENDENT, NON-SEALED activation-requirement report: it opens
NO seal, reads NO sealed outcome, fits NO model, imports no ``gears``/``cpa``,
and touches NO sealed cells (the metric independently proves zero measured
overlap with the declared sealed pair roster). It becomes
``baselines.gears.approximation_bias_report_sha256``;
the GPU pod runs it on real Norman, and it is unit-tested locally on synthetic
data.

Probe-A admission gate (design spec §3 "Admission prerequisite"): the CLI
refuses to run this measurement at all -- no report is assembled or written --
unless ``--probe-a-evidence``, ``--probe-a-registration``, and
``--probe-a-verification`` name a fully validated, immutable Probe-A evidence
bundle. The bundle cross-binds the protocol, requested Git commit, externally
frozen registration bytes, evidence-manifest SHA, verifier-code closure,
raw-pseudobulk bridge representation, pass verdict, and observed bridge error
within its preregistered tolerance. The registration and verification receipt
pins must be supplied independently through
``--probe-a-registration-sha256`` and
``--probe-a-verification-sha256``. A bare ``{"status":"pass"}``, missing,
failed, quarantined, self-consistent forgery, or tampered object raises
:class:`ValueError` from the shared immutable evidence validator, called at the
very TOP of :func:`main` before any other scientific input is read. See
``docs/superpowers/runbooks/2026-07-11-compose-gears-decision-probe-rerun.md``
for the admission vocabulary.

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
        --probe-a-evidence artifacts/compose/probe_a_evidence.json \
        --probe-a-registration artifacts/compose/probe_a_registration.json \
        --probe-a-registration-sha256 <externally frozen sha256> \
        --probe-a-verification artifacts/compose/verify.json \
        --probe-a-verification-sha256 <externally anchored sha256> \
        --fit-role-artifact artifacts/compose/fit_role.h5ad \
        --response-projection artifacts/compose/response_projection.json \
        --sealed-pair-ids artifacts/compose/sealed_pair_ids.json \
        --basis-config configs/compose_k562_v1_phase2.yaml \
        --norman-source-sha256 <norman .h5ad sha256> \
        --git-commit <repo HEAD sha> \
        --pod-instance <pod identifier> \
        --bootstrap-replicates 2000 \
        --out artifacts/compose/approximation_bias_report.json
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
import yaml
from scipy import sparse

from alive.compose.approximation_bias import (
    ADMITTED,
    APPROXIMATION_BIAS_SCHEMA,
    NON_FINITE,
    NOT_ADMISSIBLE,
    R_STAR,
    REPRESENTATION,
    ProbeAEvidence,
    bridge_admits,
    canonical_json,
    load_probe_a_evidence,
    measurement_contract_sha256,
    probe_a_from_evidence,
    self_checksum,
    validate_approximation_bias_report,
)
from alive.compose.fit_role import apply_response_projection, canonical_gene_order_sha256
from alive.provenance import sha256_file, sha256_json

#: Only finite floats or this string sentinel are ever embedded in the report
#: (CLAUDE.md#invariants / #data-eval — report the degenerate value honestly,
#: never a silent NaN; mirrors ``compose.phase2b._NON_FINITE_SENTINEL``).
_NON_FINITE_SENTINEL = NON_FINITE

#: Pre-registered fairness threshold (design spec §5): ``R >= _R_STAR`` marks the
#: sealed GEARS family-comparator interpretation ``"representation_confounded"``.
_R_STAR = R_STAR

#: The v1 measurement entry's measured-role whitelist (design spec §3 "Seal
#: safety"). Deliberately narrower than ``fit_role``'s overall allowed-role set
#: (which also permits ``control`` as a reference-only row): ``control`` may
#: legitimately exist in a fit-role artifact for ``control_mean`` provenance,
#: but must NEVER be presented as a *measured* pair to this metric.
_ARTIFACT_ROLES: frozenset[str] = frozenset({"control", "singles", "combo_calibration"})

#: The v4 report's ``schema`` literal (design spec §4; v4 adds the R1
#: ``provenance.probe_a_output_representation`` leaf).
_SCHEMA_V4 = APPROXIMATION_BIAS_SCHEMA


def _finite_or_sentinel(value: float) -> float | str:
    """Return ``float(value)`` when finite, else :data:`_NON_FINITE_SENTINEL`."""
    number = float(value)
    return number if math.isfinite(number) else _NON_FINITE_SENTINEL


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
    ``control_token`` rows are dropped — ``control`` is
    reference-only via the frozen projection block's ``control_mean`` and is
    NEVER a measured pair (CLAUDE.md invariants; spec §3 "Populations"). The
    caller's exact artifact-role guard rejects every other role before this
    helper runs.

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

    # An undefined comparison is not evidence that the representation is clear.
    fairness_flag = (
        "indeterminate"
        if not math.isfinite(ratio_r)
        else "representation_confounded"
        if ratio_r >= _R_STAR
        else "clear"
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
    singles_rows_by_gene: Mapping[str, np.ndarray],
    block: Mapping,
    gene_order: Sequence[str],
    *,
    seeds: Sequence[int],
    replicates: int,
    combo_sep: str = "_",
) -> dict:
    """Hierarchical nonparametric bootstrap interval for the GI fairness statistics.

    Registered-seed, byte-reproducible finite-sample uncertainty for
    ``floor_median``, ``gi_signal_median``, and ``bias_to_signal_ratio_R`` (design
    spec §3 "Finite-sample uncertainty"). Each replicate: (a) resamples
    ``combo_calibration`` pair IDs WITH REPLACEMENT (``n_pairs`` draws), then (b)
    resamples cells WITH REPLACEMENT within each sampled pair's own observed cell
    matrix, then recomputes the three statistics on that resampled data via
    :func:`_gi_and_fairness` -- the SAME ratio-of-medians aggregation as the point
    estimate, not a re-derived formula. Single-role cells are also resampled
    within gene once per replicate before recomputing ``delta_g``/``delta_h``:
    those effects are estimated from finite samples and contribute directly to
    the uncertainty of ``g_i`` and ``R``.

    Replicate count: ``replicates`` is a DEDICATED bootstrap-interval draw count,
    never silently taken from
    ``configs/compose_k562_v1_phase2.yaml::baselines.method.bootstrap_replicates``
    (10000) -- see the module docstring. The CLI wires this as
    ``--bootstrap-replicates`` (default 2000) in a later task; this function always
    requires an explicit ``replicates`` from its caller.

    Determinism: ``seeds`` (the config's ``seeds.registered_seeds``) are consumed
    via ``np.random.default_rng(seed)`` in the given order, each producing a fixed
    deterministic share of ``replicates`` (:func:`_split_bootstrap_replicates`).
    Neither input mapping is ever mutated, so
    byte-identical inputs + ``seeds`` + ``replicates`` always yield byte-identical
    output, and calling this function never perturbs a separately-computed point
    estimate (the point estimate takes no RNG input at all).

    A resampled pair drawn more than once within one replicate is kept as DISTINCT
    occurrences (each with its own independently-resampled cell subsample) by
    giving each occurrence a unique salted key
    (``f"{gene_a}~{occurrence}{combo_sep}{gene_b}~{occurrence}"``) with a
    correspondingly salted copy of the resampled single effects for that occurrence's two
    genes. This lets ONE call to :func:`_gi_and_fairness` per replicate compute
    every occurrence's ``b_i``/``g_i`` and their ratio-of-medians aggregation
    exactly as the point estimate would, including a duplicate pair contributing
    independently (twice) to the replicate's median.

    Parameters
    ----------
    combo_pairs : mapping of str to numpy.ndarray
        ``pair_id -> raw cell matrix`` for ``combo_calibration`` (the OBSERVED
        sample; never mutated).
    singles_rows_by_gene : mapping of str to numpy.ndarray
        ``gene_id -> raw single-role cell matrix``. Cells are resampled within
        each gene once per replicate before recomputing ``delta_g``.
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
            single_draws: dict[str, np.ndarray] = {}
            for gene in sorted(singles_rows_by_gene):
                single_raw = np.asarray(singles_rows_by_gene[gene], dtype=np.float64)
                n_single_cells = single_raw.shape[0]
                single_idx = rng.integers(0, n_single_cells, size=n_single_cells)
                single_draws[gene] = single_raw[single_idx, :]
            resampled_base_effects = _single_effects(single_draws, block, gene_order)
            resampled_effects: dict[str, np.ndarray] = dict(resampled_base_effects)
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
                    resampled_effects[key_a] = resampled_base_effects[gene_a]
                    resampled_effects[key_b] = resampled_base_effects[gene_b]

            if resampled_combo:
                rep = _gi_and_fairness(
                    resampled_combo, resampled_effects, block, gene_order, combo_sep=combo_sep
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


def _canonical_json(obj: Mapping) -> str:
    """The v4 report's one canonical serialisation recipe (design spec §4).

    ``sort_keys=True`` (dict key order never affects the bytes),
    ``separators=(",", ":")`` (no incidental whitespace), and
    ``ensure_ascii=False`` (non-ASCII, if any, is kept literal rather than
    ``\\uXXXX``-escaped) — the SAME recipe used both to compute
    :func:`_self_checksum` and to write the report file in :func:`main`, so
    the checksum always covers exactly the bytes that get written.
    """
    return canonical_json(obj)


def _self_checksum(report_without_checksum: Mapping) -> str:
    """SHA-256 hex digest of :func:`_canonical_json` applied to *report_without_checksum*.

    Parameters
    ----------
    report_without_checksum : Mapping
        The full v4 report object MINUS its own ``self_checksum`` key (design
        spec §4: "SHA-256 of the canonical JSON of every field above except
        ``self_checksum``"). Passing a dict that still contains
        ``self_checksum`` would make the digest depend on itself; callers
        (including :func:`measure_approximation_bias_v4`) always strip that
        key first.

    Returns
    -------
    str
        Lowercase hex-encoded SHA-256 digest.
    """
    return self_checksum(report_without_checksum)


def measure_approximation_bias_v4(
    *,
    fit_role_artifact: str,
    response_projection: Mapping,
    sealed_pair_ids: Sequence[str],
    basis_config_sha256: str | None = None,
    registered_seeds: Sequence[int] | None = None,
    replicates: int | None = None,
    git_commit: str | None = None,
    norman_source_sha256: str | None = None,
    pod_instance: str | None = None,
    combo_sep: str = "_",
    probe_a_evidence: ProbeAEvidence | None = None,
    probe_a_registration_sha256: str | None = None,
    probe_a_verification_sha256: str | None = None,
) -> dict:
    """Assemble the FULL ``compose_approximation_bias_report_v4`` object.

    Task 4 of the COMPOSE approximation-bias v1 implementation plan
    (``docs/superpowers/plans/2026-07-13-compose-approximation-bias-implementation.md``):
    builds on Task 3's seal-safety guards (unchanged, still run FIRST and in
    the same order) to assemble the report's ``strata``, ``gi_and_fairness``
    (point estimate + bootstrap interval), ``provenance``, and
    ``self_checksum`` blocks (design spec §4). In order:

    (a)-(c) Task 3's guards (measured-role whitelist, sealed-roster overlap,
        gene-order digest) — see :func:`measure_approximation_bias_v4`'s prior
        revision for their exact messages; UNCHANGED here so every existing
        seal-safety negative test keeps matching the metric's OWN message
        before any provenance field is even inspected.
    (d) once the guards pass, every provenance input
        (``basis_config_sha256``, ``registered_seeds``, ``replicates``,
        ``git_commit``, ``norman_source_sha256``, ``pod_instance``) must be an
        explicitly-resolved, non-empty value — none of them defaults to a
        placeholder like ``"UNKNOWN"``; a missing one raises here rather than
        silently embedding a fake value in a binding v4 report (CLAUDE.md
        §data-eval, §invariants #1 "Protocol first"). This intentionally runs
        AFTER the seal-safety guards so a bad roster/gene-order/role always
        raises its own dedicated message first, never masked by a
        missing-provenance error.

    Only non-sealed ``{"singles", "combo_calibration"}`` cells are ever read
    (``control`` is reference-only via ``response_projection["control_mean"]``
    and is stratified out by :func:`_stratify_by_role`); no sealed outcome is
    read, no seal is opened, no ``gears``/``cpa`` is imported.

    ``basis_config_sha256`` is the caller-computed ``sha256_json`` of the
    bias-NULL config (i.e. the config whose
    ``baselines.gears.approximation_bias_report_sha256`` is still ``null``);
    this function never computes or embeds a FINAL config SHA (design spec §4
    "one-way provenance" — the report must not contain the SHA of a config
    that itself contains the report's SHA, which would create an impossible
    cycle). ``registered_seeds`` is consumed, in order, by
    :func:`_bootstrap_intervals` and also recorded verbatim in ``provenance``.

    Parameters
    ----------
    fit_role_artifact : str
        Path to the fit-role ``.h5ad`` (``obs`` carries ``role`` /
        ``perturbation``; ``var_names`` is the full gene order).
    response_projection : Mapping
        The frozen ``response_projection`` block (spec §2.2); must carry
        ``gene_order_sha256`` and ``control_mean``.
    sealed_pair_ids : sequence of str
        The sealed double-unseen pair-id roster — a measured row whose
        ``perturbation`` is a member aborts (guard (b)).
    basis_config_sha256 : str, optional
        ``sha256_json`` of the bias-NULL basis config, computed by the caller
        (e.g. the CLI's ``--basis-config``). Required once the guards pass.
    registered_seeds : sequence of int, optional
        The registered seed roster (the basis config's
        ``seeds.registered_seeds``), consumed in order by
        :func:`_bootstrap_intervals`. Required (non-empty) once the guards
        pass.
    replicates : int, optional
        Total bootstrap replicate count (becomes ``replicates_requested``).
        Required (positive) once the guards pass; deliberately never defaults
        (see the module docstring's "Bootstrap replicate-count decision") —
        the CLI supplies its own default of 2000 via ``--bootstrap-replicates``.
    git_commit : str, optional
        Git SHA of the run. Required (non-empty, never ``"UNKNOWN"``) once the
        guards pass.
    norman_source_sha256 : str, optional
        SHA-256 of the source Norman ``.h5ad`` this fit-role artifact was
        built from. Required once the guards pass.
    pod_instance : str, optional
        Identifier of the compute instance the measurement ran on. Required
        once the guards pass.
    combo_sep : str, default ``"_"``
        Separator between a combo pair id's two constituent gene tokens (the
        config's ``data.combo_sep``).
    probe_a_evidence : ProbeAEvidence
        Required immutable Probe-A admission, registration, and verification
        receipt bytes. The producer revalidates them even for direct API calls
        and binds their exact SHA values plus the evidence-manifest SHA into
        report provenance; there is no admitted default or free-form status
        bypass.
    probe_a_registration_sha256 : str
        Externally frozen pre-run registration SHA-256, supplied independently of
        the admission bytes so it cannot be read back from the admission it
        validates. It authenticates the separately supplied registration-byte
        snapshot, binds the admission to that frozen identity, and rejects any
        legacy or registration-unbound admission.
    probe_a_verification_sha256 : str
        Externally anchored SHA-256 of ``verify.json``. The immutable evidence
        bundle must contain those exact bytes, and the admission must bind the
        same receipt digest. This authenticates the measured error and manifest
        identity instead of trusting a recomputable admission self-checksum.

    Returns
    -------
    dict
        The full ``compose_approximation_bias_report_v4`` object (see "The v4
        report object" in the implementation plan): ``schema``,
        ``deliverable``, ``protocol``, ``seal_status``, ``method``,
        ``admission_status``, ``strata`` (``combo_calibration`` + ``singles``),
        ``gi_and_fairness`` (point estimate + bootstrap interval),
        ``provenance``, and ``self_checksum``.

    Raises
    ------
    ValueError
        ``"approximation-bias: artifact role must be
        control|singles|combo_calibration"`` for guard (a);
        ``"approximation-bias: measured roster overlaps
        sealed_pair_ids"`` for guard (b); ``"approximation-bias: gene_order
        digest mismatch"`` for guard (c); ``"approximation-bias: missing
        required provenance field(s): ..."`` or a ``registered_seeds``/
        ``replicates`` message for guard (d).
    """
    if probe_a_evidence is None:
        raise ValueError(
            "approximation-bias: Probe-A evidence is required; measurement NOT_ADMISSIBLE"
        )
    if probe_a_registration_sha256 is None:
        raise ValueError(
            "approximation-bias: externally frozen Probe-A registration SHA-256 is required; "
            "measurement NOT_ADMISSIBLE"
        )
    if probe_a_verification_sha256 is None:
        raise ValueError(
            "approximation-bias: externally anchored Probe-A verification SHA-256 is required; "
            "measurement NOT_ADMISSIBLE"
        )
    try:
        probe_a = probe_a_from_evidence(
            probe_a_evidence,
            expected_git_commit=git_commit,
            expected_registration_sha256=probe_a_registration_sha256,
            expected_verification_sha256=probe_a_verification_sha256,
        )
    except ValueError as exc:
        raise ValueError(f"approximation-bias: {exc}") from exc

    # R1 (design spec, "Probe-A candidate correction"): the measurement below computes the
    # RAW-count Jensen floor. A Probe-A PASS on some other native scale does not validate
    # that formula, so it cannot ADMIT this report -- the measurement still runs and is
    # still written, but only as a non-promotable record. `bridge_admits` is the same
    # predicate `validate_approximation_bias_report` re-checks at every consuming boundary,
    # so producer and validator cannot drift apart.
    bridge_representation = str(probe_a["output_bridge"]["representation"])
    admission_status = (
        ADMITTED
        if bridge_admits(method=REPRESENTATION, probe_representation=bridge_representation)
        else NOT_ADMISSIBLE
    )

    block = response_projection
    adata = ad.read_h5ad(fit_role_artifact)
    roles = [str(r) for r in adata.obs["role"]]
    perturbations = [str(p) for p in adata.obs["perturbation"]]
    gene_order = [str(g) for g in adata.var_names]

    if not set(roles) <= _ARTIFACT_ROLES:
        raise ValueError(
            "approximation-bias: artifact role must be control|singles|combo_calibration"
        )

    measured_perturbations = {
        perturbation
        for role, perturbation in zip(roles, perturbations, strict=True)
        if role in {"singles", "combo_calibration"}
    }
    sealed_pair_overlap_count = len(measured_perturbations & set(sealed_pair_ids))
    if sealed_pair_overlap_count != 0:
        raise ValueError("approximation-bias: measured roster overlaps sealed_pair_ids")

    if canonical_gene_order_sha256(gene_order) != str(block["gene_order_sha256"]):
        raise ValueError("approximation-bias: gene_order digest mismatch")

    missing = [
        name
        for name, value in (
            ("basis_config_sha256", basis_config_sha256),
            ("git_commit", git_commit),
            ("norman_source_sha256", norman_source_sha256),
            ("pod_instance", pod_instance),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "approximation-bias: missing required provenance field(s): " + ", ".join(missing)
        )
    if str(git_commit) == "UNKNOWN":
        raise ValueError("approximation-bias: git_commit must be resolved, not 'UNKNOWN'")
    if not registered_seeds:
        raise ValueError("approximation-bias: registered_seeds must be a non-empty sequence")
    if replicates is None or int(replicates) <= 0:
        raise ValueError("approximation-bias: replicates must be a positive int")

    X = np.asarray(sparse.csr_matrix(adata.X).toarray(), dtype=np.float64)
    stratified = _stratify_by_role(roles, perturbations, X)
    combo_rows = stratified["combo_calibration"]
    singles_rows = stratified["singles"]

    strata = {
        "combo_calibration": _stratum_bias(combo_rows, block, gene_order),
        "singles": _stratum_bias(singles_rows, block, gene_order),
    }

    single_effects = _single_effects(singles_rows, block, gene_order)
    gi_point = _gi_and_fairness(combo_rows, single_effects, block, gene_order, combo_sep=combo_sep)
    bootstrap = _bootstrap_intervals(
        combo_rows,
        singles_rows,
        block,
        gene_order,
        seeds=list(registered_seeds),
        replicates=int(replicates),
        combo_sep=combo_sep,
    )
    gi_and_fairness = {**gi_point, **bootstrap}

    provenance = {
        "measurement_contract_sha256": measurement_contract_sha256(),
        "basis_config_sha256": str(basis_config_sha256),
        "git_commit": str(git_commit),
        "norman_source_sha256": str(norman_source_sha256),
        "fit_role_artifact_sha256": sha256_file(fit_role_artifact),
        "response_projection_sha256": sha256_json(block),
        "gene_order_sha256": str(block["gene_order_sha256"]),
        "pca_dim": int(len(block["control_mean"])),
        "registered_seeds": [int(s) for s in registered_seeds],
        "probe_a_evidence_sha256": probe_a_evidence.content_sha256,
        "probe_a_evidence_manifest_sha256": str(probe_a["evidence_manifest_sha256"]),
        "probe_a_registration_sha256": probe_a_evidence.registration_sha256,
        "probe_a_verification_sha256": probe_a_evidence.verification_sha256,
        "probe_a_output_representation": bridge_representation,
        "sealed_pair_overlap_count": sealed_pair_overlap_count,
        "pod_instance": str(pod_instance),
    }

    report_without_checksum = {
        "schema": _SCHEMA_V4,
        "deliverable": "gears_pseudobulk_approximation_bias_report",
        "protocol": "COMPOSE-K562-v1",
        "seal_status": "unopened",
        "method": REPRESENTATION,
        "admission_status": admission_status,
        "strata": strata,
        "gi_and_fairness": gi_and_fairness,
        "provenance": provenance,
    }
    report = dict(report_without_checksum)
    report["self_checksum"] = _self_checksum(report_without_checksum)
    validate_approximation_bias_report(
        report,
        # The producer is the ONE boundary that may see a non-admitted report: it is the
        # author of the refusal record. Every consumer keeps the strict default.
        require_admitted=False,
        expected_basis_config_sha256=str(basis_config_sha256),
        expected_measurement_contract_sha256=measurement_contract_sha256(),
        expected_git_commit=str(git_commit),
        expected_provenance={
            "norman_source_sha256": str(norman_source_sha256),
            "fit_role_artifact_sha256": sha256_file(fit_role_artifact),
            "response_projection_sha256": sha256_json(block),
            "gene_order_sha256": str(block["gene_order_sha256"]),
            "pca_dim": int(len(block["control_mean"])),
            "registered_seeds": [int(seed) for seed in registered_seeds],
            "probe_a_evidence_sha256": probe_a_evidence.content_sha256,
            "probe_a_evidence_manifest_sha256": str(probe_a["evidence_manifest_sha256"]),
            "probe_a_registration_sha256": probe_a_evidence.registration_sha256,
            "probe_a_verification_sha256": probe_a_evidence.verification_sha256,
            "probe_a_output_representation": bridge_representation,
        },
    )
    return report


def main(argv: list[str] | None = None) -> int:
    """Gate on Probe-A evidence, then load inputs and write the v4 report.

    The FIRST thing this function does after parsing arguments is read and
    validate the immutable admission, registration, and verification snapshots
    against the independently supplied registration and verification SHA-256
    pins -- BEFORE ``--fit-role-artifact``,
    ``--response-projection``, or any other scientific input is opened (design
    spec §3 "Admission prerequisite"). A missing, failed, quarantined, or
    pin-mismatched Probe-A raises there: no report is assembled, no
    ``--out`` file is written, and the process exits non-zero. Only a conforming
    v3 pass admission and v1 verification receipt let execution continue past
    the gate.

    A conforming PASS is necessary but NOT sufficient for ADMISSION (R1): the report's
    ``admission_status`` is ``ADMITTED`` only if the Probe-A output bridge validated the
    very representation this report measures. Otherwise the measurement is still performed
    and still written, as a ``NOT_ADMISSIBLE`` record that every consuming boundary --
    including the one-way config finalizer -- refuses.

    ``--basis-config`` is the bias-NULL YAML config (design spec §4): its
    ``sha256_json`` becomes ``provenance.basis_config_sha256`` and its
    ``seeds.registered_seeds`` seeds :func:`_bootstrap_intervals`. This CLI
    NEVER computes or accepts a FINAL config SHA — that binding is one-way and
    lives in the separate finalization tool (a later task).
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--probe-a-evidence",
        required=True,
        type=Path,
        help="exact verifier-published Probe-A admission JSON (design spec §3 admission "
        "prerequisite; vocabulary: "
        "docs/superpowers/runbooks/2026-07-11-compose-gears-decision-probe-rerun.md)",
    )
    ap.add_argument(
        "--probe-a-registration-sha256",
        required=True,
        help="externally frozen pre-run SHA-256 of probe_a_registration.json",
    )
    ap.add_argument(
        "--probe-a-registration",
        required=True,
        type=Path,
        help="exact owner-frozen probe_a_registration.json bytes",
    )
    ap.add_argument(
        "--probe-a-verification",
        required=True,
        type=Path,
        help="exact verifier-published verify.json receipt",
    )
    ap.add_argument(
        "--probe-a-verification-sha256",
        required=True,
        help="externally anchored SHA-256 of verify.json",
    )
    ap.add_argument("--fit-role-artifact", required=True, type=Path)
    ap.add_argument("--response-projection", required=True, type=Path, help="§2.2 block JSON")
    ap.add_argument(
        "--sealed-pair-ids",
        required=True,
        type=Path,
        help="JSON list of sealed pair-id tokens (design spec §3 seal-safety guard)",
    )
    ap.add_argument(
        "--basis-config",
        required=True,
        type=Path,
        help="bias-NULL YAML config (its sha256_json + seeds.registered_seeds are used; "
        "NEVER the finalized config)",
    )
    ap.add_argument("--norman-source-sha256", required=True)
    ap.add_argument("--git-commit", required=True)
    ap.add_argument("--pod-instance", required=True)
    ap.add_argument("--bootstrap-replicates", type=int, default=2000)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--require-admitted",
        action="store_true",
        help=(
            "exit non-zero when the report is NOT_ADMISSIBLE. The report is STILL "
            "written -- the refusal reason belongs on disk. Default off, because the "
            "measurement succeeding and the report being admissible are two different "
            "facts, and two committed tests pin the default."
        ),
    )
    args = ap.parse_args(argv)

    probe_a_evidence = load_probe_a_evidence(
        args.probe_a_evidence,
        registration_path=args.probe_a_registration,
        verification_path=args.probe_a_verification,
        expected_git_commit=args.git_commit,
        expected_registration_sha256=args.probe_a_registration_sha256,
        expected_verification_sha256=args.probe_a_verification_sha256,
    )

    block = json.loads(args.response_projection.read_text(encoding="utf-8"))
    sealed_pair_ids = json.loads(args.sealed_pair_ids.read_text(encoding="utf-8"))
    basis_config_raw = yaml.safe_load(args.basis_config.read_text(encoding="utf-8"))
    basis_config_sha256 = sha256_json(basis_config_raw)
    registered_seeds = [int(s) for s in basis_config_raw["seeds"]["registered_seeds"]]

    report = measure_approximation_bias_v4(
        fit_role_artifact=str(args.fit_role_artifact),
        response_projection=block,
        sealed_pair_ids=sealed_pair_ids,
        probe_a_evidence=probe_a_evidence,
        probe_a_registration_sha256=args.probe_a_registration_sha256,
        probe_a_verification_sha256=args.probe_a_verification_sha256,
        basis_config_sha256=basis_config_sha256,
        registered_seeds=registered_seeds,
        replicates=args.bootstrap_replicates,
        git_commit=args.git_commit,
        norman_source_sha256=args.norman_source_sha256,
        pod_instance=args.pod_instance,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_canonical_json(report) + "\n", encoding="utf-8")
    gi = report["gi_and_fairness"]
    print(
        f"wrote {args.out}: admission_status={report['admission_status']} "
        f"fairness_flag={gi['fairness_flag']} "
        f"bias_to_signal_ratio_R={gi['bias_to_signal_ratio_R']}"
    )
    if args.require_admitted and report["admission_status"] != ADMITTED:
        print(
            f"refusing: admission_status={report['admission_status']} (--require-admitted)",
            file=sys.stderr,
        )
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
