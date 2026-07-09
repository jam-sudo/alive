"""Norman et al. 2019 K562 CRISPRa GI Perturb-seq ingestion (COMPOSE Phase 1).

Outcome-independent: eligibility uses cell counts + feature availability only,
never GI strength (CLAUDE.md#invariants; spec §2.2). Combo labels are "<g><sep><h>".
"""

from __future__ import annotations

import numpy as np


def parse_labels(
    obs_values: np.ndarray,
    *,
    control_token: str,
    combo_sep: str,
) -> tuple[dict[str, np.ndarray], dict[tuple[str, str], np.ndarray], np.ndarray]:
    """Split obs perturbation labels into singles, doubles, and control indices."""
    obs_values = np.asarray(obs_values, dtype=object)
    singles: dict[str, list[int]] = {}
    doubles: dict[tuple[str, str], list[int]] = {}
    control: list[int] = []
    for i, raw in enumerate(obs_values):
        s = str(raw)
        if s == control_token:
            control.append(i)
        elif combo_sep in s:
            a, b = s.split(combo_sep, 1)
            key = (min(a, b), max(a, b))
            doubles.setdefault(key, []).append(i)
        else:
            singles.setdefault(s, []).append(i)
    return (
        {g: np.asarray(ix, dtype=int) for g, ix in singles.items()},
        {k: np.asarray(ix, dtype=int) for k, ix in doubles.items()},
        np.asarray(control, dtype=int),
    )


def single_effects(
    X: np.ndarray,
    singles: dict[str, np.ndarray],
    control_idx: np.ndarray,
) -> dict[str, np.ndarray]:
    """Per-gene mean shift delta_g = mean(X[single]) - mean(X[control])."""
    ctrl_mean = np.asarray(X[control_idx]).mean(axis=0)
    return {g: np.asarray(X[ix]).mean(axis=0) - ctrl_mean for g, ix in singles.items()}


def eligible_genes(
    singles: dict[str, np.ndarray],
    *,
    min_cells: int,
    available_feature_ids: set[str],
) -> list[str]:
    """Genes with enough single cells AND an available sequence feature."""
    return sorted(
        g for g, ix in singles.items() if len(ix) >= min_cells and g in available_feature_ids
    )


def eligible_pairs(
    doubles: dict[tuple[str, str], np.ndarray],
    eligible_gene_set: set[str],
    *,
    min_cells: int,
) -> list[tuple[str, str]]:
    """Pairs with enough double cells whose BOTH genes are eligible singles."""
    return sorted(
        key
        for key, ix in doubles.items()
        if len(ix) >= min_cells and key[0] in eligible_gene_set and key[1] in eligible_gene_set
    )


def data_card(
    path: str,
    *,
    source: str,
    license: str,
    cell_line: str,
    modality: str,
) -> dict[str, str]:
    """Minimal provenance card for the Norman dataset (extended in Phase 2)."""
    return {
        "path": str(path),
        "source": source,
        "license": license,
        "cell_line": cell_line,
        "modality": modality,
    }
