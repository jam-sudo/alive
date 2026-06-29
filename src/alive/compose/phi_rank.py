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

from collections.abc import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

from alive.compose.identify import rank_diagnostics
from alive.compose.split import build_pair_split
from alive.compose.zfactor import build_factor_grid


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
