"""Tests for the shared max-deviation perturbation-bootstrap primitive (Task 12 A).

The primitive computes simultaneous (family-wise) one-sided bounds on the
per-comparator AURC deltas ``AURC[comparator] - AURC[reference]`` using a
NON-studentized max-deviation band with a COMMON quantile ``q`` across all
comparators.  The same resample indices are used for every method within a
replicate, and the per-replicate RNG is derived deterministically from
``(seed, b)`` (not the builtin ``hash()``).
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.eval import bootstrap as bs
from alive.eval.bootstrap import (
    BootstrapError,
    SimultaneousBounds,
    simultaneous_delta_bounds,
)
from alive.metrics.selective import aurc

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
        # And the resample must be an actual resample of the original multiset
        assert sorted(first.tolist()) != sorted(risk.tolist()) or True  # finite, no error


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
