"""Tests for the single authoritative verdict engine (Task 15).

Implements the Section-7 truth-table tests:

  Precedence order (first match wins):
    1. INVALID_EVALUATION  — any integrity failure
    2. CALIBRATION_FAILURE — integrity valid but conformal_passes=False
    3. GATE_WINS           — integrity+calibration valid AND all four gate clauses pass
    4. NO_DISTINCT_WIN     — everything else

Rules:
  - Every verdict assertion uses ``==`` (exact equality), NEVER set membership.
  - Every clause key must appear in VerdictResult.clauses and .evidence for
    every verdict, regardless of which rule fired (full auditability).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alive.eval.bootstrap import ConfirmatoryInference
from alive.eval.verdict import IntegrityReport, VerdictResult, compute_verdict
from alive.types import Verdict

# ---------------------------------------------------------------------------
# Helpers: build "all-passing" inputs
# ---------------------------------------------------------------------------

CLAUSE_KEYS = {
    "provenance_ok",
    "leakage_ok",
    "sealed_n_ok",
    "metrics_finite",
    "reliability_ok",
    "integrity_valid",
    "conformal_passes",
    "aurc_family_passes",
    "augrc_no_material_degradation",
    "added_value_passes",
    "feature_weight_positive",
}


def _passing_integrity() -> IntegrityReport:
    return IntegrityReport(
        provenance_ok=True,
        leakage_ok=True,
        sealed_n=100,
        minimum_sealed=50,
        all_metrics_finite=True,
        reliability_ok=True,
        evidence={"source": "unit-test"},
    )


def _passing_confirmatory() -> ConfirmatoryInference:
    """A ConfirmatoryInference with all three gate booleans True."""
    return ConfirmatoryInference(
        aurc_point_delta={"c1": 0.05},
        aurc_lower_bound={"c1": 0.01},
        aurc_family_passes=True,
        augrc_degradation_upper={"c1": 0.005},
        augrc_margin=0.02,
        augrc_no_material_degradation=True,
        delta_added_value=0.04,
        delta_added_value_lower_bound=0.01,
        added_value_passes=True,
        pairwise_intervals={"c1": (0.005, 0.09)},
        family_confidence=0.95,
        n_replicates=10,
        seed=42,
    )


def _call_passing() -> VerdictResult:
    return compute_verdict(
        integrity=_passing_integrity(),
        conformal_passes=True,
        confirmatory=_passing_confirmatory(),
        selected_feature_weight=0.5,
    )


# ---------------------------------------------------------------------------
# Positive fixture: all passing → EXACTLY GATE_WINS
# ---------------------------------------------------------------------------


class TestPositiveFixture:
    def test_all_passing_yields_gate_wins(self):
        result = _call_passing()
        assert result.verdict == Verdict.GATE_WINS

    def test_gate_wins_not_a_set_membership(self):
        # Guard against accidentally testing isinstance or __contains__
        result = _call_passing()
        assert result.verdict == Verdict.GATE_WINS
        # Explicitly NOT other verdicts
        assert result.verdict != Verdict.NO_DISTINCT_WIN
        assert result.verdict != Verdict.CALIBRATION_FAILURE
        assert result.verdict != Verdict.INVALID_EVALUATION


# ---------------------------------------------------------------------------
# Clause/evidence completeness — always, for every verdict
# ---------------------------------------------------------------------------


class TestClauseCompleteness:
    """Every clause key must appear in .clauses and .evidence for every verdict."""

    def _check_completeness(self, result: VerdictResult) -> None:
        for key in CLAUSE_KEYS:
            assert key in result.clauses, f"Missing clause key {key!r} in result.clauses"
            assert key in result.evidence, f"Missing evidence key {key!r} in result.evidence"

    def test_gate_wins_completeness(self):
        self._check_completeness(_call_passing())

    def test_calibration_failure_completeness(self):
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=False,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.5,
        )
        self._check_completeness(result)

    def test_invalid_evaluation_completeness(self):
        bad = IntegrityReport(
            provenance_ok=False,
            leakage_ok=True,
            sealed_n=100,
            minimum_sealed=50,
            all_metrics_finite=True,
            reliability_ok=True,
            evidence={"source": "unit-test"},
        )
        result = compute_verdict(
            integrity=bad,
            conformal_passes=True,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.5,
        )
        self._check_completeness(result)

    def test_no_distinct_win_completeness(self):
        bad_conf = ConfirmatoryInference(
            aurc_point_delta={"c1": -0.01},
            aurc_lower_bound={"c1": -0.05},
            aurc_family_passes=False,
            augrc_degradation_upper={"c1": 0.005},
            augrc_margin=0.02,
            augrc_no_material_degradation=True,
            delta_added_value=0.04,
            delta_added_value_lower_bound=0.01,
            added_value_passes=True,
            pairwise_intervals={"c1": (-0.09, 0.01)},
            family_confidence=0.95,
            n_replicates=10,
            seed=42,
        )
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=True,
            confirmatory=bad_conf,
            selected_feature_weight=0.5,
        )
        self._check_completeness(result)


# ---------------------------------------------------------------------------
# Gate clauses: one failure at a time → NO_DISTINCT_WIN
# ---------------------------------------------------------------------------


class TestGateClausesSingleFailure:
    """Failing any single gate clause (while all others pass) yields NO_DISTINCT_WIN."""

    def test_aurc_family_fails(self):
        conf = ConfirmatoryInference(
            aurc_point_delta={"c1": -0.01},
            aurc_lower_bound={"c1": -0.05},
            aurc_family_passes=False,  # failing
            augrc_degradation_upper={"c1": 0.005},
            augrc_margin=0.02,
            augrc_no_material_degradation=True,
            delta_added_value=0.04,
            delta_added_value_lower_bound=0.01,
            added_value_passes=True,
            pairwise_intervals={"c1": (-0.09, 0.01)},
            family_confidence=0.95,
            n_replicates=10,
            seed=42,
        )
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=True,
            confirmatory=conf,
            selected_feature_weight=0.5,
        )
        assert result.verdict == Verdict.NO_DISTINCT_WIN

    def test_augrc_no_material_degradation_fails(self):
        conf = ConfirmatoryInference(
            aurc_point_delta={"c1": 0.05},
            aurc_lower_bound={"c1": 0.01},
            aurc_family_passes=True,
            augrc_degradation_upper={"c1": 0.05},
            augrc_margin=0.02,
            augrc_no_material_degradation=False,  # failing
            delta_added_value=0.04,
            delta_added_value_lower_bound=0.01,
            added_value_passes=True,
            pairwise_intervals={"c1": (0.005, 0.09)},
            family_confidence=0.95,
            n_replicates=10,
            seed=42,
        )
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=True,
            confirmatory=conf,
            selected_feature_weight=0.5,
        )
        assert result.verdict == Verdict.NO_DISTINCT_WIN

    def test_added_value_fails(self):
        conf = ConfirmatoryInference(
            aurc_point_delta={"c1": 0.05},
            aurc_lower_bound={"c1": 0.01},
            aurc_family_passes=True,
            augrc_degradation_upper={"c1": 0.005},
            augrc_margin=0.02,
            augrc_no_material_degradation=True,
            delta_added_value=-0.01,
            delta_added_value_lower_bound=-0.05,
            added_value_passes=False,  # failing
            pairwise_intervals={"c1": (0.005, 0.09)},
            family_confidence=0.95,
            n_replicates=10,
            seed=42,
        )
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=True,
            confirmatory=conf,
            selected_feature_weight=0.5,
        )
        assert result.verdict == Verdict.NO_DISTINCT_WIN

    def test_feature_weight_zero_fails(self):
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=True,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.0,  # w=0 → residual-only ablation, not a full-gate win
        )
        assert result.verdict == Verdict.NO_DISTINCT_WIN

    def test_feature_weight_negative_fails(self):
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=True,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=-0.1,
        )
        assert result.verdict == Verdict.NO_DISTINCT_WIN

    @pytest.mark.parametrize(
        "clause",
        ["aurc_family_passes", "augrc_no_material_degradation", "added_value_passes"],
    )
    def test_single_gate_clause_failure_never_yields_gate_wins(self, clause: str):
        """Prove no single failed gate clause can produce GATE_WINS."""
        kwargs: dict = dict(
            aurc_point_delta={"c1": 0.05},
            aurc_lower_bound={"c1": 0.01},
            aurc_family_passes=True,
            augrc_degradation_upper={"c1": 0.005},
            augrc_margin=0.02,
            augrc_no_material_degradation=True,
            delta_added_value=0.04,
            delta_added_value_lower_bound=0.01,
            added_value_passes=True,
            pairwise_intervals={"c1": (0.005, 0.09)},
            family_confidence=0.95,
            n_replicates=10,
            seed=42,
        )
        kwargs[clause] = False
        conf = ConfirmatoryInference(**kwargs)
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=True,
            confirmatory=conf,
            selected_feature_weight=0.5,
        )
        assert result.verdict != Verdict.GATE_WINS


# ---------------------------------------------------------------------------
# CALIBRATION_FAILURE: conformal_passes=False (integrity valid)
# ---------------------------------------------------------------------------


class TestCalibrationFailure:
    def test_conformal_false_yields_calibration_failure(self):
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=False,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.5,
        )
        assert result.verdict == Verdict.CALIBRATION_FAILURE

    def test_conformal_false_beats_gate_wins_precedence(self):
        """Even if all gate clauses would pass, conformal miss → CALIBRATION_FAILURE."""
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=False,  # calibration failure
            confirmatory=_passing_confirmatory(),  # all gate clauses pass
            selected_feature_weight=0.5,
        )
        assert result.verdict == Verdict.CALIBRATION_FAILURE
        assert result.verdict != Verdict.GATE_WINS

    def test_calibration_failure_clauses_still_recorded(self):
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=False,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.5,
        )
        assert result.clauses["conformal_passes"] is False
        assert result.clauses["integrity_valid"] is True
        # Gate clauses are still recorded
        assert result.clauses["aurc_family_passes"] is True
        assert result.clauses["augrc_no_material_degradation"] is True
        assert result.clauses["added_value_passes"] is True
        assert result.clauses["feature_weight_positive"] is True


# ---------------------------------------------------------------------------
# INVALID_EVALUATION: integrity failure (precedence over everything)
# ---------------------------------------------------------------------------


class TestInvalidEvaluation:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("provenance_ok", False),
            ("leakage_ok", False),
            ("all_metrics_finite", False),
            ("reliability_ok", False),
        ],
    )
    def test_integrity_bool_failure_yields_invalid(self, field: str, value: bool):
        """Any boolean integrity failure → INVALID_EVALUATION."""
        kwargs: dict = dict(
            provenance_ok=True,
            leakage_ok=True,
            sealed_n=100,
            minimum_sealed=50,
            all_metrics_finite=True,
            reliability_ok=True,
            evidence={"source": "unit-test"},
        )
        kwargs[field] = value
        integrity = IntegrityReport(**kwargs)
        result = compute_verdict(
            integrity=integrity,
            conformal_passes=True,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.5,
        )
        assert result.verdict == Verdict.INVALID_EVALUATION

    def test_low_sealed_n_yields_invalid(self):
        """sealed_n < minimum_sealed → INVALID_EVALUATION."""
        integrity = IntegrityReport(
            provenance_ok=True,
            leakage_ok=True,
            sealed_n=49,
            minimum_sealed=50,
            all_metrics_finite=True,
            reliability_ok=True,
            evidence={"source": "unit-test"},
        )
        result = compute_verdict(
            integrity=integrity,
            conformal_passes=True,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.5,
        )
        assert result.verdict == Verdict.INVALID_EVALUATION

    def test_low_n_sealed_n_ok_clause_false(self):
        """sealed_n = minimum-1 → sealed_n_ok=False in clauses."""
        integrity = IntegrityReport(
            provenance_ok=True,
            leakage_ok=True,
            sealed_n=49,
            minimum_sealed=50,
            all_metrics_finite=True,
            reliability_ok=True,
            evidence={},
        )
        result = compute_verdict(
            integrity=integrity,
            conformal_passes=True,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.5,
        )
        assert result.verdict == Verdict.INVALID_EVALUATION
        assert result.clauses["sealed_n_ok"] is False

    def test_integrity_beats_conformal_precedence(self):
        """INVALID_EVALUATION fires even when conformal_passes=False."""
        bad = IntegrityReport(
            provenance_ok=False,
            leakage_ok=True,
            sealed_n=100,
            minimum_sealed=50,
            all_metrics_finite=True,
            reliability_ok=True,
            evidence={},
        )
        result = compute_verdict(
            integrity=bad,
            conformal_passes=False,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.5,
        )
        assert result.verdict == Verdict.INVALID_EVALUATION

    def test_integrity_beats_gate_wins_precedence(self):
        """INVALID_EVALUATION fires even when all gate clauses pass."""
        bad = IntegrityReport(
            provenance_ok=False,
            leakage_ok=True,
            sealed_n=100,
            minimum_sealed=50,
            all_metrics_finite=True,
            reliability_ok=True,
            evidence={},
        )
        result = compute_verdict(
            integrity=bad,
            conformal_passes=True,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.5,
        )
        assert result.verdict == Verdict.INVALID_EVALUATION
        assert result.verdict != Verdict.GATE_WINS

    @pytest.mark.parametrize(
        "field",
        ["provenance_ok", "leakage_ok", "all_metrics_finite", "reliability_ok"],
    )
    def test_single_integrity_failure_never_yields_gate_wins(self, field: str):
        """Prove integrity failure never produces GATE_WINS."""
        kwargs: dict = dict(
            provenance_ok=True,
            leakage_ok=True,
            sealed_n=100,
            minimum_sealed=50,
            all_metrics_finite=True,
            reliability_ok=True,
            evidence={},
        )
        kwargs[field] = False
        integrity = IntegrityReport(**kwargs)
        result = compute_verdict(
            integrity=integrity,
            conformal_passes=True,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.5,
        )
        assert result.verdict != Verdict.GATE_WINS


# ---------------------------------------------------------------------------
# Specific fixture: residual-only / added-value gate
# ---------------------------------------------------------------------------


class TestAddedValueGate:
    def test_added_value_fails_yields_no_distinct_win(self):
        """added_value_passes=False with everything else passing → NO_DISTINCT_WIN."""
        conf = ConfirmatoryInference(
            aurc_point_delta={"c1": 0.05},
            aurc_lower_bound={"c1": 0.01},
            aurc_family_passes=True,
            augrc_degradation_upper={"c1": 0.005},
            augrc_margin=0.02,
            augrc_no_material_degradation=True,
            delta_added_value=-0.01,
            delta_added_value_lower_bound=-0.05,
            added_value_passes=False,  # gate doesn't beat residual
            pairwise_intervals={"c1": (0.005, 0.09)},
            family_confidence=0.95,
            n_replicates=10,
            seed=42,
        )
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=True,
            confirmatory=conf,
            selected_feature_weight=0.5,
        )
        assert result.verdict == Verdict.NO_DISTINCT_WIN

    def test_added_value_clause_recorded(self):
        conf = ConfirmatoryInference(
            aurc_point_delta={"c1": 0.05},
            aurc_lower_bound={"c1": 0.01},
            aurc_family_passes=True,
            augrc_degradation_upper={"c1": 0.005},
            augrc_margin=0.02,
            augrc_no_material_degradation=True,
            delta_added_value=-0.01,
            delta_added_value_lower_bound=-0.05,
            added_value_passes=False,
            pairwise_intervals={"c1": (0.005, 0.09)},
            family_confidence=0.95,
            n_replicates=10,
            seed=42,
        )
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=True,
            confirmatory=conf,
            selected_feature_weight=0.5,
        )
        assert result.clauses["added_value_passes"] is False


# ---------------------------------------------------------------------------
# Feature-weight clause
# ---------------------------------------------------------------------------


class TestFeatureWeightClause:
    def test_weight_zero_yields_no_distinct_win(self):
        """w=0 is the residual-only ablation → NO_DISTINCT_WIN."""
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=True,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.0,
        )
        assert result.verdict == Verdict.NO_DISTINCT_WIN

    def test_weight_positive_contributes_to_gate_wins(self):
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=True,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=1e-9,  # tiny but > 0
        )
        assert result.verdict == Verdict.GATE_WINS

    def test_weight_clause_recorded_in_evidence(self):
        result = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=True,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.75,
        )
        assert result.clauses["feature_weight_positive"] is True
        assert result.evidence["feature_weight_positive"] == 0.75


# ---------------------------------------------------------------------------
# Clause values match inputs
# ---------------------------------------------------------------------------


class TestClauseValues:
    def test_integrity_clauses_match_inputs(self):
        result = _call_passing()
        assert result.clauses["provenance_ok"] is True
        assert result.clauses["leakage_ok"] is True
        assert result.clauses["sealed_n_ok"] is True
        assert result.clauses["metrics_finite"] is True
        assert result.clauses["reliability_ok"] is True
        assert result.clauses["integrity_valid"] is True

    def test_sealed_n_recorded_in_evidence(self):
        result = _call_passing()
        assert result.evidence["sealed_n_ok"] == 100  # sealed_n value

    def test_conformal_passes_clause_true(self):
        result = _call_passing()
        assert result.clauses["conformal_passes"] is True

    def test_gate_clauses_true_in_gate_wins(self):
        result = _call_passing()
        assert result.clauses["aurc_family_passes"] is True
        assert result.clauses["augrc_no_material_degradation"] is True
        assert result.clauses["added_value_passes"] is True
        assert result.clauses["feature_weight_positive"] is True


# ---------------------------------------------------------------------------
# Determinism and round-trip
# ---------------------------------------------------------------------------


class TestDeterminismAndRoundTrip:
    def test_same_inputs_same_checksum(self):
        r1 = _call_passing()
        r2 = _call_passing()
        assert r1.checksum == r2.checksum

    def test_different_verdict_different_checksum(self):
        r_pass = _call_passing()
        r_fail = compute_verdict(
            integrity=_passing_integrity(),
            conformal_passes=False,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.5,
        )
        assert r_pass.checksum != r_fail.checksum

    def test_round_trip_write_read(self, tmp_path: Path):
        result = _call_passing()
        out = tmp_path / "verdict.json"
        result.write(out)
        loaded = VerdictResult.read(out)
        assert loaded.verdict == result.verdict
        assert loaded.clauses == result.clauses
        assert loaded.checksum == result.checksum

    def test_round_trip_invalid_evaluation(self, tmp_path: Path):
        bad = IntegrityReport(
            provenance_ok=False,
            leakage_ok=True,
            sealed_n=100,
            minimum_sealed=50,
            all_metrics_finite=True,
            reliability_ok=True,
            evidence={"source": "rt-test"},
        )
        result = compute_verdict(
            integrity=bad,
            conformal_passes=True,
            confirmatory=_passing_confirmatory(),
            selected_feature_weight=0.5,
        )
        out = tmp_path / "verdict_invalid.json"
        result.write(out)
        loaded = VerdictResult.read(out)
        assert loaded.verdict == Verdict.INVALID_EVALUATION
        assert loaded.clauses == result.clauses

    def test_write_is_valid_json(self, tmp_path: Path):
        result = _call_passing()
        out = tmp_path / "verdict.json"
        result.write(out)
        raw = json.loads(out.read_text())
        assert "verdict" in raw
        assert "clauses" in raw
        assert "checksum" in raw
