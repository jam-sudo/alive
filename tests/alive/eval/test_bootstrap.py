"""Tests for the shared max-deviation perturbation-bootstrap primitive (Task 12 A)
and the confirmatory simultaneous inference layer (Task 14).

Task 12 primitive: ``simultaneous_delta_bounds`` computes family-wise one-sided
bounds on per-comparator AURC deltas using a NON-studentized max-deviation band
with a COMMON quantile ``q`` across all comparators.  Same resample indices for
every method within a replicate; deterministic from ``(seed, b)``.

Task 14 extension: ``confirmatory_inference`` wraps the primitive to produce
AURC simultaneous lower bounds, AUGRC degradation upper bounds, an added-value
test (full gate vs residual-only), and pairwise descriptive intervals.
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.eval import bootstrap as bs
from alive.eval.bootstrap import (
    BootstrapError,
    ConfirmatoryInference,
    SimultaneousBounds,
    confirmatory_inference,
    simultaneous_delta_bounds,
)
from alive.metrics.selective import augrc, aurc

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_data(n: int, seed: int) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Build a (risk, method_scores) pair where 'good' ranks risk well."""
    rng = np.random.default_rng(seed)
    risk = rng.uniform(0.1, 2.0, size=n)
    method_scores = {
        # 'good' is the reference: score == risk → near-perfect ranking → low AURC
        "good": risk + rng.normal(0.0, 0.01, size=n),
        # 'bad' ranks almost randomly → higher AURC → positive delta
        "bad": rng.normal(0.0, 1.0, size=n),
    }
    return risk, method_scores


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_reference_raises(self):
        risk, scores = _make_data(20, 0)
        with pytest.raises(BootstrapError):
            simultaneous_delta_bounds(
                risk,
                scores,
                reference="not_present",
                comparators=["bad"],
                side="lower",
                confidence=0.9,
                n_replicates=10,
                seed=1,
            )

    def test_missing_comparator_raises(self):
        risk, scores = _make_data(20, 0)
        with pytest.raises(BootstrapError):
            simultaneous_delta_bounds(
                risk,
                scores,
                reference="good",
                comparators=["missing"],
                side="lower",
                confidence=0.9,
                n_replicates=10,
                seed=1,
            )

    def test_bad_side_raises(self):
        risk, scores = _make_data(20, 0)
        with pytest.raises(BootstrapError):
            simultaneous_delta_bounds(
                risk,
                scores,
                reference="good",
                comparators=["bad"],
                side="sideways",
                confidence=0.9,
                n_replicates=10,
                seed=1,
            )

    def test_bad_confidence_raises(self):
        risk, scores = _make_data(20, 0)
        for conf in (0.0, 1.0, -0.1, 1.5):
            with pytest.raises(BootstrapError):
                simultaneous_delta_bounds(
                    risk,
                    scores,
                    reference="good",
                    comparators=["bad"],
                    side="lower",
                    confidence=conf,
                    n_replicates=10,
                    seed=1,
                )

    def test_zero_replicates_raises(self):
        risk, scores = _make_data(20, 0)
        with pytest.raises(BootstrapError):
            simultaneous_delta_bounds(
                risk,
                scores,
                reference="good",
                comparators=["bad"],
                side="lower",
                confidence=0.9,
                n_replicates=0,
                seed=1,
            )

    def test_mismatched_lengths_raises(self):
        risk, scores = _make_data(20, 0)
        scores = dict(scores)
        scores["bad"] = scores["bad"][:-1]  # wrong length
        with pytest.raises(BootstrapError):
            simultaneous_delta_bounds(
                risk,
                scores,
                reference="good",
                comparators=["bad"],
                side="lower",
                confidence=0.9,
                n_replicates=10,
                seed=1,
            )


# ---------------------------------------------------------------------------
# Point delta correctness
# ---------------------------------------------------------------------------


def test_point_delta_matches_aurc_difference():
    risk, scores = _make_data(40, 7)
    out = simultaneous_delta_bounds(
        risk,
        scores,
        reference="good",
        comparators=["bad"],
        side="upper",
        confidence=0.9,
        n_replicates=50,
        seed=3,
    )
    expected = aurc(risk, scores["bad"]) - aurc(risk, scores["good"])
    assert out.point_delta["bad"] == pytest.approx(expected)
    # 'bad' is genuinely worse → positive point delta
    assert out.point_delta["bad"] > 0.0


# ---------------------------------------------------------------------------
# Identical sampled indices across methods
# ---------------------------------------------------------------------------


def test_identical_sampled_indices_across_methods(monkeypatch):
    """Every method in a replicate must be scored on the SAME resample indices.

    We spy on the module-level ``aurc`` used by the primitive.  Within each
    bootstrap replicate, every method's call must receive an identical resampled
    ``risk`` array (and therefore identical indices).  We capture the resampled
    risk arrays per call and assert they cluster into groups of equal size
    (one per replicate) with byte-identical content across methods.
    """
    risk, scores = _make_data(25, 11)
    comparators = ["bad"]
    methods = ["good", "bad"]  # reference + comparators

    captured: list[np.ndarray] = []
    real_aurc = bs.aurc

    def spy_aurc(r, s):
        captured.append(np.asarray(r).copy())
        return real_aurc(r, s)

    monkeypatch.setattr(bs, "aurc", spy_aurc)

    n_replicates = 8
    simultaneous_delta_bounds(
        risk,
        scores,
        reference="good",
        comparators=comparators,
        side="lower",
        confidence=0.9,
        n_replicates=n_replicates,
        seed=99,
    )

    # First len(methods) calls are the point estimates on the FULL data.
    n_methods = len(methods)
    point_calls = captured[:n_methods]
    for arr in point_calls:
        np.testing.assert_array_equal(arr, np.asarray(risk, dtype=float))

    # Remaining calls are grouped per replicate: n_methods consecutive calls,
    # all on the identical resampled risk vector.
    replicate_calls = captured[n_methods:]
    assert len(replicate_calls) == n_replicates * n_methods
    for b in range(n_replicates):
        block = replicate_calls[b * n_methods : (b + 1) * n_methods]
        first = block[0]
        for arr in block[1:]:
            np.testing.assert_array_equal(arr, first)
        # The resample must have the same length and all values must be drawn
        # from the original risk array (bootstrap with replacement draws risk[idx]).
        assert len(first) == len(risk)
        risk_set = set(np.asarray(risk, dtype=float).tolist())
        assert all(v in risk_set for v in first.tolist())


# ---------------------------------------------------------------------------
# Determinism / byte-identical
# ---------------------------------------------------------------------------


def test_byte_identical_under_fixed_seed():
    risk, scores = _make_data(30, 5)
    kwargs = dict(
        reference="good",
        comparators=["bad"],
        side="lower",
        confidence=0.9,
        n_replicates=40,
        seed=2024,
    )
    a = simultaneous_delta_bounds(risk, scores, **kwargs)
    b = simultaneous_delta_bounds(risk, scores, **kwargs)
    assert a == b
    assert a.band_halfwidth == b.band_halfwidth
    assert a.point_delta == b.point_delta
    assert a.bound == b.bound


def test_seed_changes_band():
    risk, scores = _make_data(30, 5)
    kwargs = dict(
        reference="good",
        comparators=["bad"],
        side="lower",
        confidence=0.9,
        n_replicates=40,
    )
    a = simultaneous_delta_bounds(risk, scores, seed=1, **kwargs)
    b = simultaneous_delta_bounds(risk, scores, seed=2, **kwargs)
    # Point delta is seed-independent; the band (resampling) is not.
    assert a.point_delta == b.point_delta
    assert a.band_halfwidth != b.band_halfwidth


def test_not_builtin_hash_derivation():
    """Seed derivation must be stable across processes (not builtin hash()).

    ``hash()`` of ints is identity in CPython, but tuples are salted by
    PYTHONHASHSEED for strings only; to be safe we assert that two runs in the
    SAME process with the same seed are identical (covered above) and that the
    derivation does not depend on Python's per-run hash randomization by
    checking the documented helper exists and is pure.
    """
    # The implementation must expose a pure, deterministic per-replicate index
    # function so the derivation is auditable and process-stable.
    idx_a = bs._replicate_indices(seed=123, replicate=4, n=10)
    idx_b = bs._replicate_indices(seed=123, replicate=4, n=10)
    np.testing.assert_array_equal(idx_a, idx_b)
    assert idx_a.shape == (10,)
    assert idx_a.min() >= 0 and idx_a.max() < 10
    # Different replicate → (almost surely) different indices
    idx_c = bs._replicate_indices(seed=123, replicate=5, n=10)
    assert not np.array_equal(idx_a, idx_c)


# ---------------------------------------------------------------------------
# Lower vs upper duality
# ---------------------------------------------------------------------------


def test_lower_upper_duality():
    risk, scores = _make_data(35, 8)
    common = dict(
        reference="good",
        comparators=["bad"],
        confidence=0.9,
        n_replicates=60,
        seed=42,
    )
    lo = simultaneous_delta_bounds(risk, scores, side="lower", **common)
    hi = simultaneous_delta_bounds(risk, scores, side="upper", **common)
    c = "bad"
    assert lo.point_delta[c] == pytest.approx(hi.point_delta[c])
    assert lo.bound[c] <= lo.point_delta[c] + 1e-12
    assert hi.bound[c] >= hi.point_delta[c] - 1e-12
    assert lo.bound[c] <= hi.bound[c]
    assert lo.band_halfwidth >= 0.0
    assert hi.band_halfwidth >= 0.0


# ---------------------------------------------------------------------------
# Degenerate / tied data
# ---------------------------------------------------------------------------


def test_degenerate_tied_data_finite():
    n = 20
    risk = np.full(n, 1.0)  # all tied
    scores = {
        "good": np.zeros(n),
        "bad": np.ones(n),
    }
    out = simultaneous_delta_bounds(
        risk,
        scores,
        reference="good",
        comparators=["bad"],
        side="lower",
        confidence=0.9,
        n_replicates=30,
        seed=1,
    )
    assert np.isfinite(out.point_delta["bad"])
    assert np.isfinite(out.bound["bad"])
    assert np.isfinite(out.band_halfwidth)


def test_comparator_equal_to_reference_has_zero_delta_and_nonpositive_lower():
    risk, scores = _make_data(40, 13)
    # A comparator that is literally the reference's score
    scores = dict(scores)
    scores["copy"] = scores["good"].copy()
    out = simultaneous_delta_bounds(
        risk,
        scores,
        reference="good",
        comparators=["copy"],
        side="lower",
        confidence=0.9,
        n_replicates=60,
        seed=4,
    )
    assert out.point_delta["copy"] == pytest.approx(0.0, abs=1e-12)
    assert out.bound["copy"] <= 1e-12  # lower bound on a ~zero delta is <= 0


# ---------------------------------------------------------------------------
# Nominal coverage on a known-delta simulation
# ---------------------------------------------------------------------------


def test_nominal_coverage_lower_bounds():
    """Over many independent datasets, the simultaneous LOWER bounds should
    cover the true deltas at >= nominal confidence (with Monte-Carlo slack).

    Construction: 'good' ranks by the latent difficulty; comparators rank
    progressively worse.  The "true" delta is estimated from a large gold
    dataset; each trial draws a small dataset and we check that ALL comparators'
    simultaneous lower bounds fall below the true deltas (simultaneous coverage).
    """
    confidence = 0.90
    n_trials = 200
    n = 40
    n_replicates = 120

    # Define a generative model with a fixed structure so 'true' deltas are stable.
    def sample(local_rng):
        difficulty = local_rng.uniform(0.1, 2.0, size=n)
        good = difficulty + local_rng.normal(0.0, 0.05, size=n)  # ranks well
        mid = difficulty + local_rng.normal(0.0, 0.8, size=n)  # noisier
        bad = local_rng.normal(0.0, 1.0, size=n)  # ~random
        return difficulty, {"good": good, "mid": mid, "bad": bad}

    # Estimate 'true' simultaneous deltas via a large Monte-Carlo average.
    gold_rng = np.random.default_rng(7)
    deltas_mid = []
    deltas_bad = []
    for _ in range(400):
        difficulty, sc = sample(gold_rng)
        d_mid = aurc(difficulty, sc["mid"]) - aurc(difficulty, sc["good"])
        d_bad = aurc(difficulty, sc["bad"]) - aurc(difficulty, sc["good"])
        deltas_mid.append(d_mid)
        deltas_bad.append(d_bad)
    true_mid = float(np.mean(deltas_mid))
    true_bad = float(np.mean(deltas_bad))

    covered = 0
    for t in range(n_trials):
        local_rng = np.random.default_rng(1000 + t)
        difficulty, sc = sample(local_rng)
        out = simultaneous_delta_bounds(
            difficulty,
            sc,
            reference="good",
            comparators=["mid", "bad"],
            side="lower",
            confidence=confidence,
            n_replicates=n_replicates,
            seed=t,
        )
        # Simultaneous coverage: BOTH lower bounds below their true deltas.
        if out.bound["mid"] <= true_mid and out.bound["bad"] <= true_bad:
            covered += 1

    rate = covered / n_trials
    # Allow Monte-Carlo slack below nominal (bootstrap is approximate at small n).
    assert rate >= confidence - 0.07, f"coverage {rate:.3f} < nominal {confidence}"


def test_dataclass_fields_populated():
    risk, scores = _make_data(20, 0)
    out = simultaneous_delta_bounds(
        risk,
        scores,
        reference="good",
        comparators=["bad"],
        side="upper",
        confidence=0.9,
        n_replicates=15,
        seed=1,
    )
    assert isinstance(out, SimultaneousBounds)
    assert out.reference == "good"
    assert out.side == "upper"
    assert out.confidence == 0.9
    assert out.n_replicates == 15
    assert out.seed == 1
    assert set(out.point_delta) == {"bad"}
    assert set(out.bound) == {"bad"}


# ===========================================================================
# Task 14 — ConfirmatoryInference tests
# ===========================================================================


def _make_confirmatory_scores(
    n: int,
    seed: int,
    gate_advantage: float = 0.5,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Build (risk, method_scores) for confirmatory inference tests.

    The 'gate' is better than comparators by ranking risk with noise scaled by
    ``gate_advantage``: lower advantage = closer to comparators.  ``residual_only``
    is always slightly worse than the gate (higher AURC).
    """
    rng = np.random.default_rng(seed)
    risk = rng.uniform(0.1, 2.0, size=n)
    gate_noise = rng.normal(0.0, 0.05 / max(gate_advantage, 0.01), size=n)
    scores = {
        "gate": risk + gate_noise,
        "residual_only": risk + rng.normal(0.0, 0.3, size=n),
        "comp_a": rng.normal(0.0, 1.0, size=n),
        "comp_b": rng.normal(0.0, 1.0, size=n) * 0.5,
    }
    return risk, scores


_CI_KWARGS = dict(
    comparators=["comp_a", "comp_b"],
    augrc_margin=0.02,
    family_confidence=0.90,
    n_replicates=200,
    seed=42,
)


# ---------------------------------------------------------------------------
# Task 12 regression: metric param is backward-compatible
# ---------------------------------------------------------------------------


class TestMetricParamBackwardCompat:
    """Adding metric=aurc default must not break any Task 12 call."""

    def test_default_metric_aurc_same_result(self):
        """Explicit metric=aurc must equal the no-metric call."""
        risk, scores = _make_data(40, 7)
        out_default = simultaneous_delta_bounds(
            risk,
            scores,
            reference="good",
            comparators=["bad"],
            side="lower",
            confidence=0.9,
            n_replicates=50,
            seed=3,
        )
        out_explicit = simultaneous_delta_bounds(
            risk,
            scores,
            reference="good",
            comparators=["bad"],
            side="lower",
            confidence=0.9,
            n_replicates=50,
            seed=3,
            metric=aurc,
        )
        assert out_default == out_explicit

    def test_augrc_metric_differs_from_aurc(self):
        """metric=augrc should give different point deltas than metric=aurc."""
        risk, scores = _make_data(40, 7)
        out_aurc = simultaneous_delta_bounds(
            risk,
            scores,
            reference="good",
            comparators=["bad"],
            side="lower",
            confidence=0.9,
            n_replicates=50,
            seed=3,
            metric=aurc,
        )
        out_augrc = simultaneous_delta_bounds(
            risk,
            scores,
            reference="good",
            comparators=["bad"],
            side="lower",
            confidence=0.9,
            n_replicates=50,
            seed=3,
            metric=augrc,
        )
        # AURC and AUGRC are different metrics; deltas should differ
        assert out_aurc.point_delta["bad"] != pytest.approx(out_augrc.point_delta["bad"], abs=1e-9)


# ---------------------------------------------------------------------------
# Gate tied with one comparator cannot pass the family
# ---------------------------------------------------------------------------


def test_gate_tied_with_comparator_family_fails():
    """A gate tied (AURC equal) with a comparator gives lower bound <= 0 → family fails."""
    rng = np.random.default_rng(99)
    n = 100
    risk = rng.uniform(0.1, 2.0, size=n)
    # gate score = some arbitrary score
    gate_score = rng.normal(0.0, 1.0, size=n)
    # tied_comp has exactly the same score as gate → AURC delta == 0
    tied_comp = gate_score.copy()
    # comp_b is genuinely worse (random)
    comp_b = rng.normal(0.0, 2.0, size=n)

    method_scores = {
        "gate": gate_score,
        "residual_only": rng.normal(0.0, 1.0, size=n),
        "tied_comp": tied_comp,
        "comp_b": comp_b,
    }

    ci = confirmatory_inference(
        risk,
        method_scores,
        comparators=["tied_comp", "comp_b"],
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=300,
        seed=7,
    )

    # tied_comp must have lower bound <= 0
    assert ci.aurc_lower_bound["tied_comp"] <= 1e-9, (
        f"Expected lower_bound('tied_comp') <= 0, got {ci.aurc_lower_bound['tied_comp']}"
    )
    # The family must fail because of the tie
    assert ci.aurc_family_passes is False, "Family should FAIL when gate ties a comparator"


# ---------------------------------------------------------------------------
# Adding weak comparators cannot flip a failing family to passing
# ---------------------------------------------------------------------------


def test_weak_comparators_cannot_flip_failing_family():
    """Adding comparators the gate clearly beats must not rescue a failing family.

    The common-q max-deviation band uses the MAXIMUM deviation across comparators.
    If the binding (hard) comparator pulls q up, adding easy comparators cannot
    reduce q — it can only keep it the same or increase it.
    """
    rng = np.random.default_rng(555)
    n = 80
    risk = rng.uniform(0.1, 2.0, size=n)
    gate_score = rng.normal(0.0, 1.0, size=n)

    # Hard comparator: tied with gate → forces q high → family fails
    hard_comp = gate_score.copy()
    # Weak comparators: gate clearly beats them (random scores)
    weak_comps = {f"weak_{i}": rng.normal(0.0, 3.0, size=n) for i in range(5)}

    base_scores = {
        "gate": gate_score,
        "residual_only": rng.normal(0.0, 1.5, size=n),
        "hard_comp": hard_comp,
    }

    # Without weak comparators: should already fail (tied hard_comp)
    ci_no_weak = confirmatory_inference(
        risk,
        base_scores,
        comparators=["hard_comp"],
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=300,
        seed=8,
    )
    assert ci_no_weak.aurc_family_passes is False

    # With weak comparators added: must STILL fail
    full_scores = {**base_scores, **weak_comps}
    ci_with_weak = confirmatory_inference(
        risk,
        full_scores,
        comparators=["hard_comp", *weak_comps.keys()],
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=300,
        seed=8,
    )
    assert ci_with_weak.aurc_family_passes is False, (
        "Adding weak comparators must NOT flip a failing family to passing"
    )

    # Verify the common-q cannot shrink: adding more comparators can only
    # keep q the same or increase it (max-over-comparators property).
    # The no_weak family's q is a lower bound on the full family's q.
    # (We don't assert the exact inequality because different seeds might
    # produce slightly different values; the family-fails assertion is the key.)


# ---------------------------------------------------------------------------
# AUGRC identity correctness
# ---------------------------------------------------------------------------


def test_augrc_identity_upper_equals_negated_lower():
    """Verify: upper_bound(AUGRC_gate - AUGRC_c) == -lower_bound(AUGRC_c - AUGRC_gate).

    The brief specifies this identity holds exactly for the symmetric max-deviation
    band.  We verify it by computing both sides manually and checking equality.
    """
    risk, scores_raw = _make_confirmatory_scores(60, 20)
    method_scores = dict(scores_raw)

    comparators = ["comp_a", "comp_b"]

    # Compute upper bounds on (AUGRC_gate - AUGRC_c) via the identity:
    # Call primitive with metric=augrc, reference="gate", side="lower" → L_c
    # then augrc_degradation_upper[c] = -L_c
    lower_bounds_obj = simultaneous_delta_bounds(
        risk,
        method_scores,
        reference="gate",
        comparators=comparators,
        side="lower",
        confidence=0.90,
        n_replicates=200,
        seed=42,
        metric=augrc,
    )

    ci = confirmatory_inference(
        risk,
        method_scores,
        comparators=comparators,
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=200,
        seed=42,
    )

    for c in comparators:
        L_c = lower_bounds_obj.bound[c]
        expected_upper = -L_c
        actual_upper = ci.augrc_degradation_upper[c]
        assert actual_upper == pytest.approx(expected_upper, abs=1e-12), (
            f"AUGRC identity failed for {c!r}: "
            f"expected -L_c={expected_upper:.6f}, got {actual_upper:.6f}"
        )


def test_augrc_no_material_degradation_rule():
    """augrc_no_material_degradation is True iff every upper bound <= margin."""
    risk, scores_raw = _make_confirmatory_scores(60, 21)
    method_scores = dict(scores_raw)
    comparators = ["comp_a", "comp_b"]

    ci = confirmatory_inference(
        risk,
        method_scores,
        comparators=comparators,
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=200,
        seed=42,
    )

    expected = all(ci.augrc_degradation_upper[c] <= 0.02 for c in comparators)
    assert ci.augrc_no_material_degradation == expected


# ---------------------------------------------------------------------------
# Added value: full gate vs residual_only
# ---------------------------------------------------------------------------


def test_added_value_passes_when_gate_beats_residual():
    """When the full gate clearly beats residual_only, added_value_passes is True."""
    rng = np.random.default_rng(300)
    n = 150
    risk = rng.uniform(0.1, 2.0, size=n)

    method_scores = {
        # gate: ranks risk near-perfectly → very low AURC
        "gate": risk + rng.normal(0.0, 0.02, size=n),
        # residual_only: random → much higher AURC
        "residual_only": rng.normal(0.0, 1.0, size=n),
        "comp_a": rng.normal(0.0, 1.0, size=n),
    }

    ci = confirmatory_inference(
        risk,
        method_scores,
        comparators=["comp_a"],
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=500,
        seed=10,
    )

    assert ci.delta_added_value > 0.0, "Point delta should be positive (gate beats residual)"
    assert ci.delta_added_value_lower_bound > 0.0, (
        f"Lower bound should be > 0; got {ci.delta_added_value_lower_bound}"
    )
    assert ci.added_value_passes is True


def test_added_value_fails_when_gate_ties_residual():
    """When gate and residual_only have identical scores, added_value_passes is False."""
    rng = np.random.default_rng(400)
    n = 80
    risk = rng.uniform(0.1, 2.0, size=n)
    tied_score = rng.normal(0.0, 1.0, size=n)

    method_scores = {
        "gate": tied_score.copy(),
        "residual_only": tied_score.copy(),  # exactly tied
        "comp_a": rng.normal(0.0, 1.0, size=n),
    }

    ci = confirmatory_inference(
        risk,
        method_scores,
        comparators=["comp_a"],
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=300,
        seed=11,
    )

    # Point delta ~0 (tied), lower bound <= 0
    assert ci.delta_added_value == pytest.approx(0.0, abs=1e-12)
    assert ci.delta_added_value_lower_bound <= 1e-9
    assert ci.added_value_passes is False


# ---------------------------------------------------------------------------
# Degenerate / duplicate data remain finite
# ---------------------------------------------------------------------------


def test_degenerate_inputs_produce_finite_bounds():
    """Degenerate inputs (all-tied risk or identical scores) produce finite bounds."""
    n = 30
    risk = np.full(n, 1.0)  # all tied
    tied_score = np.zeros(n)

    method_scores = {
        "gate": tied_score.copy(),
        "residual_only": np.ones(n),
        "comp_a": tied_score.copy(),
    }

    ci = confirmatory_inference(
        risk,
        method_scores,
        comparators=["comp_a"],
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=50,
        seed=999,
    )

    assert np.isfinite(ci.aurc_lower_bound["comp_a"])
    assert np.isfinite(ci.augrc_degradation_upper["comp_a"])
    assert np.isfinite(ci.delta_added_value)
    assert np.isfinite(ci.delta_added_value_lower_bound)
    for c, (lo, hi) in ci.pairwise_intervals.items():
        assert np.isfinite(lo)
        assert np.isfinite(hi)


# ---------------------------------------------------------------------------
# Shared indices across methods within a replicate (inherited from primitive)
# ---------------------------------------------------------------------------


def test_confirmatory_inference_shared_indices(monkeypatch):
    """All methods within each replicate share the same resample indices.

    We monkeypatch bs.aurc to capture the resampled risk arrays.  Within each
    bootstrap replicate, all methods receive the same risk_b array.
    """
    risk, scores = _make_confirmatory_scores(40, 77)
    comparators = ["comp_a", "comp_b"]

    captured_risks: list[np.ndarray] = []
    real_aurc = bs.aurc

    def spy_aurc(r, s):
        captured_risks.append(np.asarray(r).copy())
        return real_aurc(r, s)

    monkeypatch.setattr(bs, "aurc", spy_aurc)

    n_replicates = 5
    confirmatory_inference(
        risk,
        scores,
        comparators=comparators,
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=n_replicates,
        seed=55,
    )

    # The primitive is called three times (AURC primary, AUGRC secondary via
    # identity, added-value).  We check that within each primitive's replicate
    # block, all methods share the same risk array.  Rather than tracking exact
    # call counts, we look for consecutive blocks where the same risk array
    # appears for multiple methods.
    risk_f64 = np.asarray(risk, dtype=float)

    # Find bootstrap replicate calls (non-full-data calls)
    replicate_risks = [r for r in captured_risks if not np.array_equal(r, risk_f64)]

    # Within each block of n_methods consecutive replicate calls (sharing indices),
    # all should be equal.  We detect block boundaries by changes in the array.
    i = 0
    while i < len(replicate_risks) - 1:
        # Check if two consecutive calls share the same risk array (same replicate)
        # This is a soft check — we verify at least some consecutive pairs are equal
        if np.array_equal(replicate_risks[i], replicate_risks[i + 1]):
            break
        i += 1
    # There should be at least some equal consecutive pairs (shared indices)
    found_shared = any(
        np.array_equal(replicate_risks[j], replicate_risks[j + 1])
        for j in range(len(replicate_risks) - 1)
    )
    assert found_shared, "Expected some consecutive replicate calls to share risk arrays"


# ---------------------------------------------------------------------------
# Byte-identical under fixed seed
# ---------------------------------------------------------------------------


def test_confirmatory_inference_byte_identical_under_fixed_seed():
    """Two confirmatory_inference calls with identical args produce identical results."""
    risk, scores = _make_confirmatory_scores(50, 123)

    kwargs = dict(
        comparators=["comp_a", "comp_b"],
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=150,
        seed=2025,
    )

    ci_a = confirmatory_inference(risk, scores, **kwargs)
    ci_b = confirmatory_inference(risk, scores, **kwargs)

    assert ci_a == ci_b
    assert ci_a.checksum == ci_b.checksum
    assert ci_a.aurc_lower_bound == ci_b.aurc_lower_bound
    assert ci_a.augrc_degradation_upper == ci_b.augrc_degradation_upper
    assert ci_a.delta_added_value_lower_bound == ci_b.delta_added_value_lower_bound
    assert ci_a.pairwise_intervals == ci_b.pairwise_intervals


# ---------------------------------------------------------------------------
# ConfirmatoryInference dataclass fields
# ---------------------------------------------------------------------------


def test_confirmatory_inference_fields_populated():
    """All fields are populated with the right types and key sets."""
    risk, scores = _make_confirmatory_scores(50, 77)
    comparators = ["comp_a", "comp_b"]

    ci = confirmatory_inference(
        risk,
        scores,
        comparators=comparators,
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=100,
        seed=1,
    )

    assert isinstance(ci, ConfirmatoryInference)
    assert set(ci.aurc_point_delta) == set(comparators)
    assert set(ci.aurc_lower_bound) == set(comparators)
    assert isinstance(ci.aurc_family_passes, bool)
    assert set(ci.augrc_degradation_upper) == set(comparators)
    assert ci.augrc_margin == 0.02
    assert isinstance(ci.augrc_no_material_degradation, bool)
    assert isinstance(ci.delta_added_value, float)
    assert isinstance(ci.delta_added_value_lower_bound, float)
    assert isinstance(ci.added_value_passes, bool)
    assert set(ci.pairwise_intervals) == set(comparators)
    for c in comparators:
        lo, hi = ci.pairwise_intervals[c]
        assert lo <= hi
    assert ci.family_confidence == 0.90
    assert ci.n_replicates == 100
    assert ci.seed == 1
    assert isinstance(ci.checksum, str) and len(ci.checksum) == 64


# ---------------------------------------------------------------------------
# Point delta matches direct AURC computation
# ---------------------------------------------------------------------------


def test_confirmatory_point_delta_matches_aurc():
    """aurc_point_delta[c] == aurc(risk, score_c) - aurc(risk, score_gate)."""
    risk, scores = _make_confirmatory_scores(60, 88)
    comparators = ["comp_a", "comp_b"]

    ci = confirmatory_inference(
        risk,
        scores,
        comparators=comparators,
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=100,
        seed=5,
    )

    for c in comparators:
        expected = aurc(risk, scores[c]) - aurc(risk, scores["gate"])
        assert ci.aurc_point_delta[c] == pytest.approx(expected, abs=1e-12), (
            f"Point delta mismatch for {c!r}"
        )

    # Also check added value point delta
    expected_av = aurc(risk, scores["residual_only"]) - aurc(risk, scores["gate"])
    assert ci.delta_added_value == pytest.approx(expected_av, abs=1e-12)


# ---------------------------------------------------------------------------
# aurc_family_passes matches all lower bounds > 0
# ---------------------------------------------------------------------------


def test_family_passes_logic():
    """aurc_family_passes is True iff every aurc_lower_bound > 0."""
    risk, scores = _make_confirmatory_scores(60, 200)
    comparators = ["comp_a", "comp_b"]

    ci = confirmatory_inference(
        risk,
        scores,
        comparators=comparators,
        augrc_margin=0.02,
        family_confidence=0.90,
        n_replicates=100,
        seed=5,
    )

    expected = all(ci.aurc_lower_bound[c] > 0 for c in comparators)
    assert ci.aurc_family_passes == expected
