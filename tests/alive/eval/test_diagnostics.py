"""Tests for alive.eval.diagnostics — written FIRST per TDD protocol.

Read-only post-hoc diagnostics over the *development* OOF surface (NOT the
sealed cohort).  All tests are pure-numpy with deterministic seeds; expected
values are hand-verified inline where closed-form.

Coverage discipline (CLAUDE.md#verify): known-answer, constant, shuffled and
random-sanity cases for every new statistical function.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from alive.eval.diagnostics import (
    DiagnosticsError,
    diagnose_oof,
    load_oof_table,
    partial_spearman,
    rank_overconfidence,
    spearman_corr,
)

# ---------------------------------------------------------------------------
# spearman_corr — known-answer / constant / shuffled / random
# ---------------------------------------------------------------------------


class TestSpearmanCorr:
    def test_perfect_monotone_is_plus_one(self) -> None:
        x = np.array([1.0, 2.0, 3.0, 4.0])
        y = np.array([10.0, 20.0, 30.0, 40.0])
        assert spearman_corr(x, y) == pytest.approx(1.0)

    def test_reverse_monotone_is_minus_one(self) -> None:
        x = np.array([1.0, 2.0, 3.0, 4.0])
        y = np.array([40.0, 30.0, 20.0, 10.0])
        assert spearman_corr(x, y) == pytest.approx(-1.0)

    def test_tie_handling_hand_verified(self) -> None:
        # x=[1,1,2,2] -> avg ranks [1.5,1.5,3.5,3.5]; y=[1,2,3,4] -> ranks [1,2,3,4].
        # Pearson(rx, ry) = 4.0 / (2 * sqrt(5)) = 0.8944271909999159.
        x = np.array([1.0, 1.0, 2.0, 2.0])
        y = np.array([1.0, 2.0, 3.0, 4.0])
        assert spearman_corr(x, y) == pytest.approx(0.8944271909999159)

    def test_constant_score_is_zero_not_nan(self) -> None:
        x = np.array([5.0, 5.0, 5.0, 5.0, 5.0])
        y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        out = spearman_corr(x, y)
        assert out == 0.0
        assert np.isfinite(out)

    def test_symmetric(self) -> None:
        rng = np.random.default_rng(7)
        x = rng.normal(size=64)
        y = rng.normal(size=64)
        assert spearman_corr(x, y) == pytest.approx(spearman_corr(y, x))

    def test_shuffled_breaks_correlation(self) -> None:
        rng = np.random.default_rng(0)
        n = 400
        y = np.arange(n, dtype=np.float64)
        x = y.copy()
        rng.shuffle(x)
        assert abs(spearman_corr(x, y)) < 0.2

    def test_random_independent_is_small(self) -> None:
        rng = np.random.default_rng(123)
        x = rng.normal(size=500)
        y = rng.normal(size=500)
        assert abs(spearman_corr(x, y)) < 0.15


# ---------------------------------------------------------------------------
# partial_spearman — the R1-vs-R4 "added value" primitive
# ---------------------------------------------------------------------------


class TestPartialSpearman:
    def test_controlling_for_self_is_zero(self) -> None:
        # Residualising rank(x) on rank(x) leaves nothing -> 0.0.
        rng = np.random.default_rng(1)
        x = rng.normal(size=50)
        y = rng.normal(size=50)
        assert partial_spearman(x, y, x) == pytest.approx(0.0, abs=1e-9)

    def test_monotone_transform_of_control_is_zero(self) -> None:
        # x is a monotone function of z -> rank(x)==rank(z) -> partial corr == 0.
        z = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        x = np.exp(z)  # strictly increasing in z
        y = np.array([2.0, 9.0, 1.0, 7.0, 3.0, 5.0])
        assert partial_spearman(x, y, z) == pytest.approx(0.0, abs=1e-9)

    def test_symmetric_in_first_two_args(self) -> None:
        rng = np.random.default_rng(2)
        a = rng.normal(size=80)
        b = rng.normal(size=80)
        z = rng.normal(size=80)
        assert partial_spearman(a, b, z) == pytest.approx(partial_spearman(b, a, z))

    def test_planted_independent_signal_is_positive(self) -> None:
        # error = z + x + tiny noise; x carries signal beyond z.
        rng = np.random.default_rng(0)
        n = 300
        z = rng.normal(size=n)
        x = rng.normal(size=n)
        error = z + x + 0.1 * rng.normal(size=n)
        assert partial_spearman(x, error, z) > 0.5

    def test_redundant_feature_adds_nothing(self) -> None:
        # error is driven by z only; x is correlated with z but adds no
        # independent signal -> partial corr(x, error | z) ~ 0.  This is the
        # R1-adds-nothing scenario the diagnostic exists to detect.
        rng = np.random.default_rng(0)
        n = 400
        z = rng.normal(size=n)
        error = z + 0.05 * rng.normal(size=n)
        x = z + 0.3 * rng.normal(size=n)  # correlated with z, no error-specific info
        assert abs(partial_spearman(x, error, z)) < 0.25


# ---------------------------------------------------------------------------
# rank_overconfidence — high true error but low (trustworthy) gate score
# ---------------------------------------------------------------------------


class TestRankOverconfidence:
    def test_flags_high_error_low_score(self) -> None:
        ids = ("a", "b", "c", "d", "e")
        errors = np.array([0.1, 0.2, 0.3, 5.0, 0.15])
        score = np.array([0.9, 0.8, 0.7, 0.01, 0.6])  # 'd' confidently trusted, worst error
        out = rank_overconfidence(ids, errors, score, error_quantile=0.8, score_quantile=0.2)
        flagged = [row["id"] for row in out]
        assert "d" in flagged
        assert out[0]["id"] == "d"  # sorted by error descending
        assert out[0]["error"] == pytest.approx(5.0)

    def test_empty_when_score_tracks_error(self) -> None:
        ids = ("a", "b", "c", "d", "e")
        errors = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
        score = errors.copy()  # perfect: worst error -> highest (least trusted) score
        out = rank_overconfidence(ids, errors, score, error_quantile=0.8, score_quantile=0.2)
        assert out == []


# ---------------------------------------------------------------------------
# diagnose_oof — orchestrator
# ---------------------------------------------------------------------------


def _oof_fixture() -> tuple[tuple[str, ...], np.ndarray, dict[str, np.ndarray]]:
    """residual_only tracks error; nearest_feature is pure noise."""
    rng = np.random.default_rng(0)
    n = 200
    ids = tuple(f"G{i}" for i in range(n))
    errors = np.abs(rng.normal(size=n)) + 0.01
    residual = errors + 0.02 * rng.normal(size=n)  # strong signal
    feature = rng.normal(size=n)  # noise
    gate = 0.95 * residual + 0.05 * feature
    ensemble = errors + 0.05 * rng.normal(size=n)
    scores = {
        "gate": gate,
        "residual_only": residual,
        "nearest_feature": feature,
        "ensemble_disagreement": ensemble,
        "ridge_error": rng.normal(size=n),
        "gbm_error": rng.normal(size=n),
    }
    return ids, errors, scores


class TestDiagnoseOof:
    def test_structure_and_signal_separation(self) -> None:
        ids, errors, scores = _oof_fixture()
        out = diagnose_oof(ids, errors, scores)

        # residual tracks error, feature does not
        assert out["per_method"]["residual_only"]["spearman"] > 0.8
        assert abs(out["per_method"]["nearest_feature"]["spearman"]) < 0.2

        # every method gets a finite recomputed AURC and spearman
        for m in scores:
            assert np.isfinite(out["per_method"][m]["aurc"])
            assert np.isfinite(out["per_method"][m]["spearman"])

        # the headline: feature adds nothing beyond residual; residual does
        av = out["added_value"]
        assert abs(av["partial_feature_given_residual"]) < 0.2
        assert av["partial_residual_given_feature"] > 0.5
        assert "corr_feature_residual" in av

        # overconfident list present and well-formed
        assert isinstance(out["overconfident"], list)
        for row in out["overconfident"]:
            assert {"id", "error", "score"} <= row.keys()

    def test_unknown_method_raises(self) -> None:
        ids, errors, scores = _oof_fixture()
        with pytest.raises(DiagnosticsError):
            diagnose_oof(ids, errors, scores, feature_method="does_not_exist")


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(DiagnosticsError):
            spearman_corr(np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0]))

    def test_non_finite_raises(self) -> None:
        with pytest.raises(DiagnosticsError):
            spearman_corr(np.array([1.0, np.nan, 3.0, 4.0]), np.array([1.0, 2.0, 3.0, 4.0]))

    def test_too_few_rows_raises(self) -> None:
        with pytest.raises(DiagnosticsError):
            partial_spearman(np.array([1.0, 2.0]), np.array([1.0, 2.0]), np.array([1.0, 2.0]))


# ---------------------------------------------------------------------------
# load_oof_table — round-trips the develop-stage artifact format
# ---------------------------------------------------------------------------


class TestLoadOofTable:
    def test_round_trip(self, tmp_path) -> None:
        ids = ["G0", "G1", "G2", "G3"]
        errors = np.array([0.5, 1.5, 2.5, 3.5])
        method_ids = ["gate", "residual_only", "nearest_feature"]
        oof = {
            "gate": [0.1, 0.2, 0.3, 0.4],
            "residual_only": [0.4, 0.3, 0.2, 0.1],
            "nearest_feature": [0.0, 0.0, 1.0, 1.0],
        }
        methodlock = {
            "method_ids": method_ids,
            "oof_scores": oof,
            "dev_ids": ids,
        }
        (tmp_path / "methodlock.json").write_text(json.dumps(methodlock))
        np.savez(tmp_path / "dev_errors.npz", ids=np.array(ids), errors=errors)

        got_ids, got_errors, got_scores = load_oof_table(tmp_path)
        assert got_ids == tuple(ids)
        np.testing.assert_allclose(got_errors, errors)
        assert set(got_scores) == set(method_ids)
        np.testing.assert_allclose(got_scores["gate"], oof["gate"])

    def test_missing_file_raises(self, tmp_path) -> None:
        with pytest.raises(DiagnosticsError):
            load_oof_table(tmp_path)

    def test_id_misalignment_raises(self, tmp_path) -> None:
        methodlock = {
            "method_ids": ["gate"],
            "oof_scores": {"gate": [0.1, 0.2, 0.3, 0.4]},
            "dev_ids": ["G0", "G1", "G2", "G3"],
        }
        (tmp_path / "methodlock.json").write_text(json.dumps(methodlock))
        np.savez(
            tmp_path / "dev_errors.npz",
            ids=np.array(["X0", "X1", "X2", "X3"]),  # disagrees with dev_ids
            errors=np.array([0.5, 1.5, 2.5, 3.5]),
        )
        with pytest.raises(DiagnosticsError):
            load_oof_table(tmp_path)
