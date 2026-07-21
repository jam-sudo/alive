"""Synthetic-only tests for the regime detectable-effect report.

No real Norman outcomes are touched: ``ε`` arrays are synthetic, so measurability
(split-half agreement) and the per-regime power gate are known-answer properties.
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.compose.detectable_effect import (
    DETECTABLE_EFFECT_ACTIVATION_SCHEMA,
    REGISTERED_PHASE1_CONFIG_SHA256,
    compute_regime_detectable_effect_report,
    validate_regime_detectable_effect_activation_report,
)
from alive.compose.gates import LeakageError

_MIN_PAIRS = 20
_MIN_CELLS = 50


def _eps(n_pairs: int, p: int, *, corr: bool, seed: int = 0):
    rng = np.random.default_rng(seed)
    truth = rng.standard_normal((n_pairs, p))
    if corr:  # both halves see the same signal + small independent noise
        a = truth + 0.1 * rng.standard_normal((n_pairs, p))
        b = truth + 0.1 * rng.standard_normal((n_pairs, p))
    else:  # halves are independent: split-half agreement ~ 0
        a = rng.standard_normal((n_pairs, p))
        b = rng.standard_normal((n_pairs, p))
    full = (a + b) / 2.0
    return full, a, b


def _report(*, n_cal=30, p=5, corr=True, double=22, single=68, cells=60.0):
    full, a, b = _eps(n_cal, p, corr=corr)
    return compute_regime_detectable_effect_report(
        eps_calibration=full,
        eps_split_a=a,
        eps_split_b=b,
        regime_pair_counts={"sealed_double_unseen": double, "sealed_single_unseen": single},
        regime_cells_per_pair={"sealed_double_unseen": cells, "sealed_single_unseen": cells},
        min_pairs=_MIN_PAIRS,
        min_cells=_MIN_CELLS,
    )


def _activation_envelope(*, double=22, single=68, cells=60.0):
    report = _report(n_cal=30, double=double, single=single, cells=cells)
    return {
        "activation": "READY — synthetic known-answer evidence",
        "calibration_fraction": 0.6,
        "config_sha256": "a" * 64,
        "data_sha256": "b" * 64,
        "generated_at_utc": "2026-07-21T00:00:00+00:00",
        "git_sha": "1" * 40,
        "phase1_config_sha256": REGISTERED_PHASE1_CONFIG_SHA256,
        "protocol": "COMPOSE-K562-v1",
        "regime_cells_per_pair": {
            "combo_calibration": cells,
            "sealed_double_unseen": cells,
            "sealed_single_unseen": cells,
        },
        "regime_pair_counts": {
            "combo_calibration": 30,
            "sealed_double_unseen": double,
            "sealed_single_unseen": single,
        },
        "report": report,
        "schema": DETECTABLE_EFFECT_ACTIVATION_SCHEMA,
        "split_seed": 11,
    }


def _validate_activation_envelope(envelope):
    validate_regime_detectable_effect_activation_report(
        envelope,
        expected_protocol="COMPOSE-K562-v1",
        expected_config_sha256="a" * 64,
        expected_git_sha="1" * 40,
        expected_split_seed=11,
        expected_data_sha256="b" * 64,
        expected_pair_counts={
            "combo_calibration": 30,
            "sealed_double_unseen": envelope["regime_pair_counts"]["sealed_double_unseen"],
            "sealed_single_unseen": envelope["regime_pair_counts"]["sealed_single_unseen"],
        },
    )


def test_correlated_split_halves_clear_the_measurability_floor():
    rep = _report(corr=True)
    assert rep["measurability"]["ceiling"] > 0.2
    assert rep["measurability"]["passed"] is True
    assert np.isfinite(rep["effect_size"]["signal_to_noise"])
    assert rep["effect_size"]["mean_pair_eps_l2"] > 0.0


def test_independent_split_halves_fail_the_measurability_floor():
    rep = _report(corr=False)
    assert rep["measurability"]["ceiling"] <= 0.2
    assert rep["measurability"]["passed"] is False


def test_power_gate_is_reported_per_regime_headline_double_unseen():
    rep = _report(double=22, single=68, cells=60.0)
    assert rep["headline_regime"] == "sealed_double_unseen"
    assert rep["regimes"]["sealed_double_unseen"]["power_passed"] is True
    assert rep["regimes"]["sealed_single_unseen"]["power_passed"] is True
    assert rep["headline_powered"] is True


def test_per_regime_recommendation_names_its_own_regime():
    # Each regime's recommendation text must reference ITS OWN regime, not the
    # headline — power_gate's raw string hardcodes the double-unseen headline.
    rep = _report(double=22, single=68, cells=60.0)
    dbl = rep["regimes"]["sealed_double_unseen"]["recommendation"]
    sgl = rep["regimes"]["sealed_single_unseen"]["recommendation"]
    assert "sealed_double_unseen" in dbl and "headline" in dbl
    assert "sealed_single_unseen" in sgl and "secondary" in sgl
    assert "sealed_double_unseen" not in sgl  # the mislabel that bug_001 caught


def test_underpowered_double_unseen_downgrades_headline():
    rep = _report(double=12, single=68, cells=60.0)
    assert rep["regimes"]["sealed_double_unseen"]["power_passed"] is False
    assert rep["headline_powered"] is False
    # single-unseen (68 pairs) is still adequately powered as a fallback.
    assert rep["regimes"]["sealed_single_unseen"]["power_passed"] is True


def test_too_few_cells_per_pair_fails_power():
    rep = _report(double=22, single=68, cells=10.0)
    assert rep["regimes"]["sealed_double_unseen"]["power_passed"] is False


def test_measurability_gate_refuses_sealed_role():
    # The underlying gate must fail closed if ever pointed at a sealed role;
    # proves the leakage guard is real, not decorative.
    a = np.ones((4, 3))
    with pytest.raises(LeakageError):
        from alive.compose.gates import measurability_gate

        measurability_gate(a, a, _role="sealed_double_unseen")


def test_ready_activation_report_passes_strict_independent_validation():
    _validate_activation_envelope(_activation_envelope())


def test_underpowered_registered_headline_cannot_be_labeled_ready():
    envelope = _activation_envelope(double=12)
    with pytest.raises(ValueError, match="revise and re-register"):
        _validate_activation_envelope(envelope)


def test_nonfinite_effect_size_cannot_cross_activation_boundary():
    envelope = _activation_envelope()
    envelope["report"]["effect_size"]["signal_to_noise"] = float("inf")
    with pytest.raises(ValueError, match="must be finite"):
        _validate_activation_envelope(envelope)


def test_detectable_effect_schema_is_closed():
    envelope = _activation_envelope()
    envelope["report"]["unregistered_claim"] = True
    with pytest.raises(ValueError, match="schema mismatch"):
        _validate_activation_envelope(envelope)
