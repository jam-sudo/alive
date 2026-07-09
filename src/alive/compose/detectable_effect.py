"""Regime-specific detectable-effect / measurability report (§10.1).

This is the COMPOSE-K562-v1 activation-blocker deliverable
``regime_specific_detectable_effect_analysis`` (spec §2.4 / §4.2): it reports the
split-half measurability ceiling of the non-additive residual ``ε`` on the
``combo_calibration`` development pairs, the ``ε`` effect-size versus its
split-half noise, and the pre-registered power gate per *evaluation* regime
(``sealed_double_unseen`` as headline, ``sealed_single_unseen`` as fallback).

Leakage discipline (CLAUDE.md#seal, spec §2.4): ``ε`` is computed ONLY on the
``combo_calibration`` development role; the sealed evaluation regimes contribute
their outcome-independent **pair and cell counts** only (never their outcomes).
:func:`alive.compose.gates.measurability_gate` additionally fails closed if asked
to read a sealed role. The pure function here takes arrays/counts so it is
unit-testable; the CLI ``scripts/compose_detectable_effect_report.py`` assembles
the real ``ε`` split-halves.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from numpy.typing import NDArray

from alive.compose.gates import measurability_gate, power_gate

#: Evaluation regimes the power gate is reported for (headline first). The
#: development role ``combo_calibration`` is NOT an evaluation regime.
_EVAL_REGIMES = ("sealed_double_unseen", "sealed_single_unseen")

#: The headline regime; the other eval regime is a secondary/fallback.
_HEADLINE_REGIME = "sealed_double_unseen"


def _regime_power_recommendation(regime: str, passed: bool) -> str:
    """Regime-correct power recommendation.

    ``power_gate``'s own recommendation string names the *headline* regime
    (``sealed_double_unseen``), which is correct in the Phase-1 go/no-go but
    mislabels ``sealed_single_unseen`` when the gate is reported per regime here.
    """
    role = "headline" if regime == _HEADLINE_REGIME else "secondary regime"
    if passed:
        return f"{regime} adequately powered as {role}"
    return (
        f"{regime} underpowered; downgrade headline to the strongest "
        "adequately-powered regime (e.g. single-unseen)"
    )


def compute_regime_detectable_effect_report(
    *,
    eps_calibration: NDArray,
    eps_split_a: NDArray,
    eps_split_b: NDArray,
    regime_pair_counts: Mapping[str, int],
    regime_cells_per_pair: Mapping[str, float],
    min_pairs: int,
    min_cells: int,
) -> dict:
    """Assemble the measurability + per-regime power detectable-effect report.

    Parameters
    ----------
    eps_calibration : numpy.ndarray
        Per-pair non-additive residual ``ε_gh`` on ``combo_calibration`` using
        all double cells, shape ``(n_calibration_pairs, p)``.
    eps_split_a, eps_split_b : numpy.ndarray
        The same residual estimated on two disjoint cell halves per pair, shape
        ``(n_calibration_pairs, p)`` each (the measurability split-half inputs).
    regime_pair_counts : Mapping[str, int]
        Pair count per regime (outcome-independent), including the sealed
        evaluation regimes.
    regime_cells_per_pair : Mapping[str, float]
        Median (or representative) double-cell count per pair per regime
        (outcome-independent metadata; never an outcome).
    min_pairs, min_cells : int
        Pre-registered power-gate floors.

    Returns
    -------
    dict
        Measurability ceiling, ``ε`` effect-size vs split-half noise, and the
        per-regime power gate result (headline = ``sealed_double_unseen``).
    """
    meas = measurability_gate(eps_split_a, eps_split_b)  # fails closed on sealed roles

    eps = np.asarray(eps_calibration, dtype=np.float64)
    a = np.asarray(eps_split_a, dtype=np.float64)
    b = np.asarray(eps_split_b, dtype=np.float64)
    pair_norms = np.linalg.norm(eps, axis=1)
    # Split-half disagreement is a per-pair noise scale on the ε estimate.
    noise = float(np.sqrt(np.mean(np.sum(((a - b) / 2.0) ** 2, axis=1)))) if a.size else 0.0
    mean_norm = float(np.mean(pair_norms)) if pair_norms.size else 0.0

    regimes: dict[str, dict] = {}
    for regime in _EVAL_REGIMES:
        n_pairs = int(regime_pair_counts.get(regime, 0))
        cells = float(regime_cells_per_pair.get(regime, 0.0))
        gate = power_gate(n_pairs, cells, min_pairs=int(min_pairs), min_cells=int(min_cells))
        regimes[regime] = {
            "n_pairs": n_pairs,
            "cells_per_pair": cells,
            "power_passed": bool(gate.passed),
            "recommendation": _regime_power_recommendation(regime, gate.passed),
        }

    headline = _HEADLINE_REGIME
    return {
        "deliverable": "regime_specific_detectable_effect_analysis",
        "measurability": {
            "ceiling": float(meas.detail["ceiling"]),
            "passed": bool(meas.passed),
            "recommendation": meas.recommendation,
            "n_calibration_pairs": int(eps.shape[0]) if eps.ndim == 2 else 0,
        },
        "effect_size": {
            "mean_pair_eps_l2": mean_norm,
            "median_pair_eps_l2": float(np.median(pair_norms)) if pair_norms.size else 0.0,
            "split_half_noise_l2": noise,
            "signal_to_noise": float(mean_norm / noise) if noise > 1e-12 else float("inf"),
        },
        "power_floors": {"min_pairs": int(min_pairs), "min_cells": int(min_cells)},
        "regimes": regimes,
        "headline_regime": headline,
        "headline_powered": bool(regimes[headline]["power_passed"]),
    }
