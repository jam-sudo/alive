"""COMPOSE Phase-1 pre-check gates (spec §2.4): power, measurability, rank.

These gates decide go/no-go for the real Phase-2 study WITHOUT opening any seal.
The measurability gate enforces the leakage guard: it refuses every role except
the registered calibration role.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from alive.compose.identify import RankReport
from alive.compose.roles import CALIBRATION_ROLE_NAME


class LeakageError(Exception):
    """Raised if a gate is asked to read non-calibration-role data."""


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
    _role: str,
    ceiling_floor: float,
) -> GateResult:
    """Noise-ceiling via split-half agreement on calibration pairs only.

    ``_role`` is mandatory and must equal the registered calibration role.
    Unknown, legacy, misspelled and sealed roles all fail closed. The role check
    is defense in depth; the caller must still obtain the arrays through the
    typed development-only data boundary because an array has no intrinsic
    provenance that this numerical function could infer.

    ``ceiling_floor`` is the pre-registered futility floor
    (``futility.measurability_ceiling_floor`` in the Phase-2 config,
    ``measurability_ceiling_floor`` in the Phase-1 config). It is keyword-only and
    has NO default on purpose: a caller that fails to thread the registered value
    must fail with ``TypeError`` rather than silently re-introduce a source
    constant that no config could move (CLAUDE.md#invariants 1, #repo).
    """
    # This is a development-only operation, so an allowlist is safer than a
    # blacklist: legacy names, typos and future roles all fail closed.
    if _role != CALIBRATION_ROLE_NAME:
        raise LeakageError(
            "measurability gate accepts only the registered development role "
            f"{CALIBRATION_ROLE_NAME!r}; got {_role!r}"
        )
    if (
        isinstance(ceiling_floor, bool)
        or not isinstance(ceiling_floor, (int, float))
        or not math.isfinite(float(ceiling_floor))
    ):
        raise ValueError(f"ceiling_floor must be a finite number, got {ceiling_floor!r}")
    if not -1.0 <= float(ceiling_floor) <= 1.0:
        raise ValueError(
            "ceiling_floor must lie in [-1, 1] (it is compared to a correlation), "
            f"got {ceiling_floor!r}"
        )
    a = np.asarray(eps_split_a, dtype=np.float64).ravel()
    b = np.asarray(eps_split_b, dtype=np.float64).ravel()
    a0, b0 = a - a.mean(), b - b.mean()
    denom = float(np.linalg.norm(a0) * np.linalg.norm(b0))
    ceiling = float(a0 @ b0 / denom) if denom > 1e-12 else 0.0
    # Registered floor (config ``futility.measurability_ceiling_floor``): GI must
    # rise above noise. The threshold is an ARGUMENT, never a literal here.
    passed = ceiling > ceiling_floor
    rec = (
        "GI signal measurable above noise floor"
        if passed
        else "FUTILITY_STOPPED: GI ~ noise; ship synthetic result, keep seal closed"
    )
    return GateResult(
        name="measurability",
        passed=passed,
        detail={"ceiling": ceiling, "ceiling_floor": float(ceiling_floor)},
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
