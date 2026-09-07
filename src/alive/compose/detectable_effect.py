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

import math
import re
from collections.abc import Mapping
from typing import Any

import numpy as np
from numpy.typing import NDArray

from alive.compose.gates import measurability_gate, power_gate
from alive.compose.roles import (
    CALIBRATION_ROLE_NAME,
    SEALED_DOUBLE_UNSEEN_ROLE_NAME,
    SEALED_ROLE_NAMES,
)

#: Evaluation regimes the power gate is reported for (headline first). The
#: development role ``combo_calibration`` is NOT an evaluation regime.
_EVAL_REGIMES = SEALED_ROLE_NAMES

#: The headline regime; the other eval regime is a secondary/fallback.
_HEADLINE_REGIME = SEALED_DOUBLE_UNSEEN_ROLE_NAME

# Phase-1 preregistration values consumed by
# ``scripts/compose_detectable_effect_report.py``. The scientific activation
# boundary independently checks them rather than trusting serialized booleans.
REGISTERED_MIN_PAIRS = 20
REGISTERED_MIN_CELLS = 50
REGISTERED_CALIBRATION_FRACTION = 0.6
# Moved 2026-09-07 (F-A3): the Phase-1 config gained the registered
# ``measurability_ceiling_floor``, so its canonical-JSON digest moved
# ``2e044e75…`` -> ``732f43fe…``. Historical evidence generated under the old
# Phase-1 config no longer validates, by design: the floor is part of the lineage.
REGISTERED_PHASE1_CONFIG_SHA256 = "732f43fe0a51d50b66867d39d0f1512d7307f0126a3806e4353b8651219416c8"
#: Bumped v1 -> v2 on 2026-09-07 (F-A3). The ``measurability`` block gained a
#: required ``ceiling_floor``, so a v1 report is NOT a v2 report: the key set is
#: closed and a v1 producer never wrote it. The lineage digests moved with it, so
#: no v1 artifact could have validated anyway -- the version bump is what makes
#: that visible on the artifact's own face instead of only in a digest mismatch.
DETECTABLE_EFFECT_ACTIVATION_SCHEMA = "compose_regime_detectable_effect_report_v2"

_ENVELOPE_KEYS = frozenset(
    {
        "activation",
        "calibration_fraction",
        "config_sha256",
        "data_sha256",
        "generated_at_utc",
        "git_sha",
        "phase1_config_sha256",
        "protocol",
        "regime_cells_per_pair",
        "regime_pair_counts",
        "report",
        "schema",
        "split_seed",
    }
)
_REPORT_KEYS = frozenset(
    {
        "deliverable",
        "effect_size",
        "headline_powered",
        "headline_regime",
        "measurability",
        "power_floors",
        "regimes",
    }
)
_MEASURABILITY_KEYS = frozenset(
    {"ceiling", "ceiling_floor", "passed", "recommendation", "n_calibration_pairs"}
)
_EFFECT_SIZE_KEYS = frozenset(
    {"mean_pair_eps_l2", "median_pair_eps_l2", "split_half_noise_l2", "signal_to_noise"}
)
_REGIME_KEYS = frozenset({"n_pairs", "cells_per_pair", "power_passed", "recommendation"})


def _require_exact_keys(value: Any, expected: frozenset[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    got = set(value)
    if got != expected:
        raise ValueError(
            f"{context} schema mismatch (missing={sorted(expected - got)}, "
            f"extra={sorted(got - expected)})"
        )
    return value


def _finite_number(
    value: Any,
    context: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{context} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{context} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{context} must be <= {maximum}")
    return result


def _nonnegative_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{context} must be a non-negative integer")
    return value


def validate_regime_detectable_effect_activation_report(
    envelope: Any,
    *,
    expected_protocol: str,
    expected_config_sha256: str,
    expected_git_sha: str,
    expected_split_seed: int,
    expected_data_sha256: str,
    expected_pair_counts: Mapping[str, int],
    ceiling_floor: float,
) -> None:
    """Validate a READY detectable-effect artifact at the scientific boundary.

    Every power boolean is re-computed from the registered pair/cell floors.
    A hash-pinned producer assertion establishes provenance, but does not prove
    that its statistical conclusion is internally consistent. Outcome-independent
    split counts are cross-checked against the independent rank report supplied
    by the caller.

    ``ceiling_floor`` is the registered futility floor read from the config
    (``futility.measurability_ceiling_floor``). It is keyword-only and has no
    default: the boundary re-computes the measurability verdict against the
    REGISTERED floor, and additionally requires the producer to have recorded the
    same floor in the report, so a report generated under a different threshold is
    refused rather than silently accepted (F-A3).
    """
    top = _require_exact_keys(envelope, _ENVELOPE_KEYS, "detectable-effect envelope")
    activation = top["activation"]
    if not isinstance(activation, str) or not activation.upper().startswith("READY"):
        raise ValueError("detectable-effect activation must start with 'READY'")
    if top["protocol"] != expected_protocol:
        raise ValueError("detectable-effect protocol mismatch")
    if top["schema"] != DETECTABLE_EFFECT_ACTIVATION_SCHEMA:
        raise ValueError("detectable-effect schema mismatch")
    if top["config_sha256"] != expected_config_sha256:
        raise ValueError("detectable-effect config_sha256 mismatch")
    if top["phase1_config_sha256"] != REGISTERED_PHASE1_CONFIG_SHA256:
        raise ValueError("detectable-effect phase1_config_sha256 mismatch")
    if top["data_sha256"] != expected_data_sha256:
        raise ValueError("detectable-effect data_sha256 mismatch")
    if top["split_seed"] != expected_split_seed:
        raise ValueError("detectable-effect split_seed mismatch")
    if top["calibration_fraction"] != REGISTERED_CALIBRATION_FRACTION:
        raise ValueError("detectable-effect calibration_fraction mismatch")
    if not isinstance(top["generated_at_utc"], str) or not top["generated_at_utc"].strip():
        raise ValueError("detectable-effect generated_at_utc must be non-empty")
    if (
        not isinstance(top["git_sha"], str)
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", top["git_sha"]) is None
    ):
        raise ValueError("detectable-effect git_sha must be full lowercase hex")
    if top["git_sha"] != expected_git_sha:
        raise ValueError("detectable-effect git_sha mismatch")

    expected_regime_keys = frozenset({CALIBRATION_ROLE_NAME, *_EVAL_REGIMES})
    pair_counts = _require_exact_keys(
        top["regime_pair_counts"], expected_regime_keys, "regime_pair_counts"
    )
    cell_counts = _require_exact_keys(
        top["regime_cells_per_pair"], expected_regime_keys, "regime_cells_per_pair"
    )
    for regime in expected_regime_keys:
        observed = _nonnegative_int(pair_counts[regime], f"regime_pair_counts.{regime}")
        expected = _nonnegative_int(expected_pair_counts.get(regime), f"expected {regime} count")
        if observed != expected:
            raise ValueError(
                f"detectable-effect {regime} pair count {observed} != independent report {expected}"
            )
        _finite_number(cell_counts[regime], f"regime_cells_per_pair.{regime}", minimum=0.0)

    report = _require_exact_keys(top["report"], _REPORT_KEYS, "detectable-effect report")
    if report["deliverable"] != "regime_specific_detectable_effect_analysis":
        raise ValueError("detectable-effect deliverable mismatch")
    if report["headline_regime"] != _HEADLINE_REGIME:
        raise ValueError("detectable-effect headline_regime mismatch")

    floors = _require_exact_keys(
        report["power_floors"], frozenset({"min_pairs", "min_cells"}), "power_floors"
    )
    min_pairs = _nonnegative_int(floors["min_pairs"], "power_floors.min_pairs")
    min_cells = _nonnegative_int(floors["min_cells"], "power_floors.min_cells")
    if (min_pairs, min_cells) != (REGISTERED_MIN_PAIRS, REGISTERED_MIN_CELLS):
        raise ValueError("detectable-effect power floors do not match the preregistration")

    measurability = _require_exact_keys(
        report["measurability"], _MEASURABILITY_KEYS, "measurability"
    )
    ceiling = _finite_number(
        measurability["ceiling"], "measurability.ceiling", minimum=-1.0, maximum=1.0
    )
    reported_floor = _finite_number(
        measurability["ceiling_floor"], "measurability.ceiling_floor", minimum=-1.0, maximum=1.0
    )
    if reported_floor != float(ceiling_floor):
        raise ValueError(
            f"measurability.ceiling_floor {reported_floor} was generated under a floor "
            f"other than the registered {float(ceiling_floor)}"
        )
    n_calibration = _nonnegative_int(
        measurability["n_calibration_pairs"], "measurability.n_calibration_pairs"
    )
    if n_calibration != pair_counts[CALIBRATION_ROLE_NAME]:
        raise ValueError("measurability calibration count does not match the split count")
    if type(measurability["passed"]) is not bool:  # noqa: E721 - reject int-as-bool
        raise ValueError("measurability.passed must be a boolean")
    expected_measurable = ceiling > ceiling_floor
    if measurability["passed"] is not expected_measurable:
        raise ValueError("measurability.passed is inconsistent with the registered floor")
    if not expected_measurable:
        raise ValueError("detectable-effect measurability gate did not pass")
    if measurability["recommendation"] != "GI signal measurable above noise floor":
        raise ValueError("detectable-effect measurability recommendation is inconsistent")

    effect = _require_exact_keys(report["effect_size"], _EFFECT_SIZE_KEYS, "effect_size")
    for field in _EFFECT_SIZE_KEYS:
        _finite_number(effect[field], f"effect_size.{field}", minimum=0.0)

    regimes = _require_exact_keys(report["regimes"], frozenset(_EVAL_REGIMES), "regimes")
    recomputed_power: dict[str, bool] = {}
    for regime in _EVAL_REGIMES:
        block = _require_exact_keys(regimes[regime], _REGIME_KEYS, f"regimes.{regime}")
        n_pairs = _nonnegative_int(block["n_pairs"], f"regimes.{regime}.n_pairs")
        cells = _finite_number(
            block["cells_per_pair"], f"regimes.{regime}.cells_per_pair", minimum=0.0
        )
        if n_pairs != pair_counts[regime] or cells != float(cell_counts[regime]):
            raise ValueError(f"regimes.{regime} does not match envelope split metadata")
        expected_power = n_pairs >= REGISTERED_MIN_PAIRS and cells >= REGISTERED_MIN_CELLS
        if type(block["power_passed"]) is not bool:  # noqa: E721 - reject int-as-bool
            raise ValueError(f"regimes.{regime}.power_passed must be a boolean")
        if block["power_passed"] is not expected_power:
            raise ValueError(
                f"regimes.{regime}.power_passed is inconsistent with registered floors"
            )
        expected_recommendation = _regime_power_recommendation(regime, expected_power)
        if block["recommendation"] != expected_recommendation:
            raise ValueError(f"regimes.{regime}.recommendation is inconsistent")
        recomputed_power[regime] = expected_power

    if type(report["headline_powered"]) is not bool:  # noqa: E721 - reject int-as-bool
        raise ValueError("headline_powered must be a boolean")
    if report["headline_powered"] is not recomputed_power[_HEADLINE_REGIME]:
        raise ValueError("headline_powered is inconsistent with the headline regime")
    if not report["headline_powered"]:
        raise ValueError(
            "registered headline is underpowered; revise and re-register the headline "
            "before activation"
        )


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
    ceiling_floor: float,
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
    ceiling_floor : float
        Registered split-half measurability floor (config
        ``futility.measurability_ceiling_floor``). Keyword-only, no default.

    Returns
    -------
    dict
        Measurability ceiling, ``ε`` effect-size vs split-half noise, and the
        per-regime power gate result (headline = ``sealed_double_unseen``).
    """
    meas = measurability_gate(
        eps_split_a,
        eps_split_b,
        _role=CALIBRATION_ROLE_NAME,
        ceiling_floor=ceiling_floor,
    )

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
            "ceiling_floor": float(meas.detail["ceiling_floor"]),
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
