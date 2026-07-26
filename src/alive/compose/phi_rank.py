"""Real-Norman Φ rank + condition report on ``combo_calibration`` (§10.6).

This is the COMPOSE-K562-v1 activation-blocker deliverable
``real_norman_phi_rank_and_condition_report`` (spec §2.4 / §3.2 / §10.6): for
each registered total factor dimension ``k_total`` it builds the fixed per-gene
factor bank ``z_g = [PCA_k(δ_g) ; ESM-PCA(s_g)]`` (:func:`alive.compose.zfactor.
build_factor_grid`), forms the symmetric bilinear design matrix
``Φ = [vecsym(z_g z_hᵀ)]`` over the seeded ``combo_calibration`` pair set
(:func:`alive.compose.split.build_pair_split`), and reports its algebraic rank
versus the identifiable subspace dimension ``sym_dim = k(k+1)/2`` plus the
conditioning that governs noisy recovery (:func:`alive.compose.identify.
rank_diagnostics`).

The computation is outcome-free and opens NO seal: it consumes single-role
``δ_g`` and outcome-free ESM sequence vectors only, and the split is driven by a
seeded gene partition (never GI strength). The pure function here takes arrays
so it is unit-testable without real data or a real ESM model; the thin CLI
``scripts/compose_phi_rank_report.py`` assembles the real inputs.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from alive.compose.identify import rank_diagnostics
from alive.compose.roles import (
    CALIBRATION_ROLE_NAME,
    SEALED_DOUBLE_UNSEEN_ROLE_NAME,
    SEALED_SINGLE_UNSEEN_ROLE_NAME,
)
from alive.compose.split import build_pair_split
from alive.compose.zfactor import build_factor_grid

PHI_RANK_ACTIVATION_SCHEMA = "compose_phi_rank_report_v1"

_ENVELOPE_KEYS = frozenset(
    {
        "activation",
        "config_sha256",
        "data_sha256",
        "deliverable",
        "device",
        "esm_model",
        "generated_at_utc",
        "git_sha",
        "long_sequence_policy",
        "n_cells",
        "n_control_cells",
        "n_doubles_total",
        "n_eligible_genes",
        "n_singles_total",
        "n_z_universe_genes",
        "protocol",
        "report",
        "schema",
        "sequence_mapping_sha256",
    }
)
_REPORT_KEYS = frozenset(
    {
        "calibration_fraction",
        "esm_dim",
        "n_calibration_genes",
        "n_combo_calibration",
        "n_eligible_pairs",
        "n_sealed_double_unseen",
        "n_sealed_single_unseen",
        "per_k_total",
        "split_seed",
    }
)
_FACTOR_BLOCK_KEYS = frozenset(
    {
        "condition_number",
        "factor_bank_checksum",
        "is_full_rank",
        "k_total",
        "n_calibration_pairs_scored",
        "n_calibration_pairs_skipped",
        "n_genes",
        "rank",
        "sym_dim",
    }
)


def _exact_object(value: Any, expected: frozenset[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    got = set(value)
    if got != expected:
        raise ValueError(
            f"{context} schema mismatch (missing={sorted(expected - got)}, "
            f"extra={sorted(got - expected)})"
        )
    return value


def _nonnegative_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def _full_hex(value: Any, context: str, *, lengths: tuple[int, ...]) -> str:
    if (
        not isinstance(value, str)
        or len(value) not in lengths
        or re.fullmatch(r"[0-9a-f]+", value) is None
    ):
        raise ValueError(f"{context} must be full lowercase hex")
    return value


def validate_phi_rank_activation_report(
    envelope: Any,
    *,
    expected_protocol: str,
    expected_config_sha256: str,
    expected_git_sha: str,
    expected_data_sha256: str,
    expected_sequence_mapping_sha256: str,
    expected_split_seed: int,
    expected_calibration_fraction: float,
    expected_total_k_grid: Sequence[int],
    expected_esm_model: str,
    expected_esm_dim: int,
) -> dict[str, int]:
    """Validate a READY rank report and return its independently bound role counts."""
    top = _exact_object(envelope, _ENVELOPE_KEYS, "phi-rank envelope")
    if top["schema"] != PHI_RANK_ACTIVATION_SCHEMA:
        raise ValueError("phi-rank schema mismatch")
    if top["deliverable"] != "real_norman_phi_rank_and_condition_report":
        raise ValueError("phi-rank deliverable mismatch")
    if top["protocol"] != expected_protocol:
        raise ValueError("phi-rank protocol mismatch")
    if not isinstance(top["activation"], str) or not top["activation"].upper().startswith("READY"):
        raise ValueError("phi-rank activation must start with 'READY'")
    if top["config_sha256"] != expected_config_sha256:
        raise ValueError("phi-rank config_sha256 mismatch")
    if top["data_sha256"] != expected_data_sha256:
        raise ValueError("phi-rank data_sha256 mismatch")
    _full_hex(top["config_sha256"], "phi-rank config_sha256", lengths=(64,))
    _full_hex(top["data_sha256"], "phi-rank data_sha256", lengths=(64,))
    _full_hex(top["sequence_mapping_sha256"], "phi-rank sequence mapping SHA", lengths=(64,))
    if top["sequence_mapping_sha256"] != expected_sequence_mapping_sha256:
        raise ValueError("phi-rank sequence mapping SHA mismatch")
    _full_hex(top["git_sha"], "phi-rank git_sha", lengths=(40, 64))
    if top["git_sha"] != expected_git_sha:
        raise ValueError("phi-rank git_sha mismatch")
    if not isinstance(top["generated_at_utc"], str) or not top["generated_at_utc"].strip():
        raise ValueError("phi-rank generated_at_utc must be non-empty")
    if top["esm_model"] != expected_esm_model:
        raise ValueError("phi-rank esm_model mismatch")
    if top["long_sequence_policy"] not in {"truncate", "error"}:
        raise ValueError("phi-rank long_sequence_policy is invalid")
    for field in (
        "n_cells",
        "n_control_cells",
        "n_doubles_total",
        "n_eligible_genes",
        "n_singles_total",
        "n_z_universe_genes",
    ):
        _nonnegative_int(top[field], f"phi-rank {field}")
    if top["n_z_universe_genes"] > top["n_eligible_genes"]:
        raise ValueError("phi-rank z-universe cannot exceed the eligible-gene universe")

    device = top["device"]
    if not isinstance(device, dict) or set(device) not in (
        {"cuda_available", "device_name", "torch_version"},
        {"cuda_available", "device_name", "error"},
    ):
        raise ValueError("phi-rank device provenance schema mismatch")
    if type(device["cuda_available"]) is not bool:  # noqa: E721 - reject int-as-bool
        raise ValueError("phi-rank device.cuda_available must be boolean")
    if not isinstance(device["device_name"], str) or not device["device_name"].strip():
        raise ValueError("phi-rank device_name must be non-empty")
    provenance_field = "torch_version" if "torch_version" in device else "error"
    if not isinstance(device[provenance_field], str) or not device[provenance_field].strip():
        raise ValueError(f"phi-rank device.{provenance_field} must be non-empty")

    report = _exact_object(top["report"], _REPORT_KEYS, "phi-rank report")
    if report["split_seed"] != expected_split_seed:
        raise ValueError("phi-rank split_seed mismatch")
    if report["calibration_fraction"] != expected_calibration_fraction:
        raise ValueError("phi-rank calibration_fraction mismatch")
    if report["esm_dim"] != expected_esm_dim:
        raise ValueError("phi-rank esm_dim mismatch")
    n_calibration_genes = _nonnegative_int(
        report["n_calibration_genes"], "phi-rank n_calibration_genes"
    )
    if n_calibration_genes > top["n_z_universe_genes"]:
        raise ValueError("phi-rank calibration-gene count exceeds its gene universe")
    pair_counts = {
        CALIBRATION_ROLE_NAME: _nonnegative_int(
            report["n_combo_calibration"], "phi-rank n_combo_calibration"
        ),
        SEALED_DOUBLE_UNSEEN_ROLE_NAME: _nonnegative_int(
            report["n_sealed_double_unseen"], "phi-rank n_sealed_double_unseen"
        ),
        SEALED_SINGLE_UNSEEN_ROLE_NAME: _nonnegative_int(
            report["n_sealed_single_unseen"], "phi-rank n_sealed_single_unseen"
        ),
    }
    if _nonnegative_int(report["n_eligible_pairs"], "phi-rank n_eligible_pairs") != sum(
        pair_counts.values()
    ):
        raise ValueError("phi-rank eligible-pair total is inconsistent")

    expected_grid = tuple(int(k) for k in expected_total_k_grid)
    per_k = report["per_k_total"]
    if not isinstance(per_k, list) or len(per_k) != len(expected_grid):
        raise ValueError("phi-rank factor-grid roster is incomplete")
    for raw_block, expected_k in zip(per_k, expected_grid, strict=True):
        block = _exact_object(raw_block, _FACTOR_BLOCK_KEYS, "phi-rank factor block")
        sym_dim = expected_k * (expected_k + 1) // 2
        condition = block["condition_number"]
        if (
            block["k_total"] != expected_k
            or block["sym_dim"] != sym_dim
            or block["rank"] != sym_dim
            or block["is_full_rank"] is not True
            or block["n_calibration_pairs_scored"] != pair_counts[CALIBRATION_ROLE_NAME]
            or block["n_calibration_pairs_skipped"] != 0
            or _nonnegative_int(block["n_genes"], "phi-rank factor n_genes")
            != top["n_z_universe_genes"]
            or isinstance(condition, bool)
            or not isinstance(condition, (int, float))
            or not math.isfinite(float(condition))
            or float(condition) <= 0.0
        ):
            raise ValueError(
                f"phi-rank invalid or non-full-rank factor block for k_total={expected_k}"
            )
        _full_hex(block["factor_bank_checksum"], "phi-rank factor-bank checksum", lengths=(64,))
    return pair_counts


def compute_phi_rank_report(
    *,
    delta_by_gene: Mapping[str, NDArray],
    sequence_by_gene: Mapping[str, NDArray],
    eligible_pairs: Sequence[tuple[str, str]],
    total_k_grid: Sequence[int],
    esm_dim: int,
    split_seed: int,
    calibration_fraction: float,
    encoder_revision: str,
    sequence_mapping_hash: str,
) -> dict:
    """Build the per-``k_total`` Φ rank/condition report on ``combo_calibration``.

    Parameters
    ----------
    delta_by_gene, sequence_by_gene : Mapping[str, numpy.ndarray]
        Single-role response-space shifts ``δ_g`` and outcome-free ESM sequence
        vectors ``s_g``, covering exactly the same gene set (forwarded to
        :func:`alive.compose.zfactor.build_factor_grid`).
    eligible_pairs : sequence of (str, str)
        The pre-registered eligible pair universe (eligibility decided before
        the split). Split into roles by a seeded gene partition.
    total_k_grid : sequence of int
        Registered total factor dimensions (e.g. ``(4, 6, 8)``).
    esm_dim : int
        ESM-PCA projection dimension shared across the grid.
    split_seed : int
        The pre-registered split seed.
    calibration_fraction : float
        The pre-registered calibration gene fraction (``0 < f < 1``).
    encoder_revision, sequence_mapping_hash : str
        Provenance fields forwarded to the factor banks.

    Returns
    -------
    dict
        Report with the split role counts and, per ``k_total``, the
        ``RankReport`` fields plus the scored calibration-pair count.
    """
    split = build_pair_split(
        list(eligible_pairs), seed=split_seed, calibration_fraction=calibration_fraction
    )
    banks = build_factor_grid(
        delta_by_gene=dict(delta_by_gene),
        sequence_by_gene=dict(sequence_by_gene),
        total_k_grid=tuple(int(k) for k in total_k_grid),
        esm_dim=int(esm_dim),
        encoder_revision=encoder_revision,
        sequence_mapping_hash=sequence_mapping_hash,
    )

    per_k: list[dict] = []
    for k_total in sorted(banks):
        bank = banks[k_total]
        gene_order = list(bank.gene_order)
        index_of = {gene: i for i, gene in enumerate(gene_order)}
        z = np.stack([np.asarray(bank.z_by_gene[g], dtype=np.float64) for g in gene_order])

        scored: list[tuple[int, int]] = []
        skipped = 0
        for g, h in split.combo_calibration:
            if g in index_of and h in index_of:
                scored.append((index_of[g], index_of[h]))
            else:  # pragma: no cover - eligible pairs are a subset of the gene universe
                skipped += 1

        report = rank_diagnostics(z, scored)
        per_k.append(
            {
                "k_total": int(k_total),
                "sym_dim": int(report.sym_dim),
                "rank": int(report.rank),
                "is_full_rank": bool(report.is_full_rank),
                "condition_number": float(report.condition_number),
                "n_calibration_pairs_scored": len(scored),
                "n_calibration_pairs_skipped": int(skipped),
                "n_genes": len(gene_order),
                "factor_bank_checksum": bank.checksum,
            }
        )

    return {
        "split_seed": int(split_seed),
        "calibration_fraction": float(calibration_fraction),
        "esm_dim": int(esm_dim),
        "n_eligible_pairs": len(split.combo_calibration)
        + len(split.sealed_double_unseen)
        + len(split.sealed_single_unseen),
        "n_combo_calibration": len(split.combo_calibration),
        "n_sealed_double_unseen": len(split.sealed_double_unseen),
        "n_sealed_single_unseen": len(split.sealed_single_unseen),
        "n_calibration_genes": len(split.combo_genes),
        "per_k_total": per_k,
    }
