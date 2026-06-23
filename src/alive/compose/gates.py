"""COMPOSE Phase-1 pre-check gates (spec §2.4): power, measurability, rank.

These gates decide go/no-go for the real Phase-2 study WITHOUT opening any seal.
The measurability gate enforces the leakage guard: it refuses to run on data
tagged with a sealed role.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from alive.compose.identify import RankReport

_SEALED_ROLES = frozenset({"sealed_double_unseen", "secondary_sealed"})


class LeakageError(Exception):
    """Raised if a gate is asked to read sealed-role data."""


@dataclass(frozen=True)
class GateResult:
    """Outcome of one pre-check gate."""

    name: str
    passed: bool
    detail: dict
    recommendation: str


def power_gate(
    n_double_unseen_pairs: int,
    cells_per_pair: float,
    *,
    min_pairs: int,
    min_cells: int,
) -> GateResult:
    """Pass iff enough double-unseen pairs AND cells/pair for a powered contrast."""
    passed = n_double_unseen_pairs >= min_pairs and cells_per_pair >= min_cells
    rec = (
        "double-unseen adequately powered as headline"
        if passed
        else "downgrade headline to the strongest adequately-powered regime (e.g. single-unseen)"
    )
    return GateResult(
        name="power",
        passed=passed,
        detail={
            "n_double_unseen_pairs": int(n_double_unseen_pairs),
            "cells_per_pair": float(cells_per_pair),
            "min_pairs": int(min_pairs),
            "min_cells": int(min_cells),
        },
        recommendation=rec,
    )


def measurability_gate(
    eps_split_a: np.ndarray,
    eps_split_b: np.ndarray,
    *,
    _role: str = "combo_calibration",
) -> GateResult:
    """Noise-ceiling via split-half agreement on DEV pairs only (§2.4 guard)."""
    if _role in _SEALED_ROLES:
        raise LeakageError(f"measurability gate must not read sealed role {_role!r}")
    a = np.asarray(eps_split_a, dtype=np.float64).ravel()
    b = np.asarray(eps_split_b, dtype=np.float64).ravel()
    a0, b0 = a - a.mean(), b - b.mean()
    denom = float(np.linalg.norm(a0) * np.linalg.norm(b0))
    ceiling = float(a0 @ b0 / denom) if denom > 1e-12 else 0.0
    passed = ceiling > 0.2  # pre-registered floor: GI must rise above noise
    rec = (
        "GI signal measurable above noise floor"
        if passed
        else "FUTILITY_STOPPED: GI ~ noise; ship synthetic result, keep seal closed"
    )
    return GateResult(
        name="measurability",
        passed=passed,
        detail={"ceiling": ceiling},
        recommendation=rec,
    )


def rank_gate(rank_report: RankReport) -> GateResult:
    """Pass iff the calibration design matrix is full rank (algebraic id.)."""
    passed = rank_report.is_full_rank
    rec = (
        "operator algebraically identifiable on calibration pairs"
        if passed
        else "rank-deficient: restrict claims to the identifiable subspace"
    )
    return GateResult(
        name="rank",
        passed=passed,
        detail={
            "rank": rank_report.rank,
            "sym_dim": rank_report.sym_dim,
            "condition_number": rank_report.condition_number,
        },
        recommendation=rec,
    )
