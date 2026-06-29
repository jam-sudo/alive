"""Tests for COMPOSE-K562-v1 Phase-2b simultaneous theta inference (Task 2b-3).

Pure numeric / synthetic tests — NO seal, NO real Norman, NO outcomes. The
function under test receives already-computed per-pair errors and produces
one-sided non-studentized max-deviation SIMULTANEOUS lower bounds over the
EXACT registered comparator family.

Determinism is pinned to the shared CARTOGRAPHER primitive
``alive.eval.bootstrap._replicate_indices`` so a future seeding change fails
here.
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.compose.inference2 import (
    ComposeInferenceError,
    ComposeSimultaneousBounds,
    simultaneous_theta_bounds,
)
from alive.eval import bootstrap as bs

# The EXACT registered comparator family (config inference.comparator_family).
FAMILY = ("additive", "gears", "cpa", "id_only", "l3_hypernetwork")
CONF = 0.95
REPS = 200  # numeric-test value; the 10000 floor is enforced by the config validator.
SEED = 1234


def _const_errors(value: float, n: int) -> np.ndarray:
    return np.full(n, float(value), dtype=np.float64)


def _family_errors(value: float, n: int) -> dict[str, np.ndarray]:
    return {c: _const_errors(value, n) for c in FAMILY}


# ---------------------------------------------------------------------------
# Known-answer: strong win
# ---------------------------------------------------------------------------


def test_strong_win_all_theta_near_one_and_lower_positive() -> None:
    """Headline errors far below every comparator → theta ~ 1 and lower > 0."""
    n = 64
    rng = np.random.default_rng(0)
    headline = rng.uniform(0.001, 0.01, size=n)  # tiny errors
    comparator_errors = {c: rng.uniform(5.0, 10.0, size=n) for c in FAMILY}

    res = simultaneous_theta_bounds(
        headline_errors=headline,
        comparator_errors=comparator_errors,
        comparators=FAMILY,
        confidence=CONF,
        n_replicates=REPS,
        seed=SEED,
    )

    assert isinstance(res, ComposeSimultaneousBounds)
    for c in FAMILY:
        assert res.theta[c] > 0.99, (c, res.theta[c])
        assert res.lower[c] > 0.0, (c, res.lower[c])
    # Common half-width is small and non-negative; lower <= theta everywhere.
    assert res.band_halfwidth >= 0.0
    for c in FAMILY:
        assert res.lower[c] <= res.theta[c] + 1e-12


# ---------------------------------------------------------------------------
# Known-answer: exact null
# ---------------------------------------------------------------------------


def test_exact_null_theta_zero_and_lower_nonpositive() -> None:
    """headline == each comparator → theta == 0 and lower <= 0 for every C."""
    n = 40
    rng = np.random.default_rng(7)
    headline = rng.uniform(0.1, 2.0, size=n)
    # Each comparator error array is identical to the headline array.
    comparator_errors = {c: headline.copy() for c in FAMILY}

    res = simultaneous_theta_bounds(
        headline_errors=headline,
        comparator_errors=comparator_errors,
        comparators=FAMILY,
        confidence=CONF,
        n_replicates=REPS,
        seed=SEED,
    )

    for c in FAMILY:
        assert res.theta[c] == pytest.approx(0.0, abs=1e-12), (c, res.theta[c])
        assert res.lower[c] <= 0.0 + 1e-12, (c, res.lower[c])
    # Under exact null, every resampled theta is also exactly 0 → deviation 0 → q == 0.
    assert res.band_halfwidth == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# Known-answer: one degraded comparator must not manufacture a win
# ---------------------------------------------------------------------------


def test_one_degraded_comparator_band_driven_by_hard_comparator() -> None:
    """A trivially-beaten comparator must NOT widen/inflate the win for a hard one.

    Construct: one comparator ("additive") is a hard comparator the headline only
    barely beats; the rest are hugely degraded (trivially beaten). The simultaneous
    band half-width q is driven by the comparator with the most negative deviation
    under resampling. The degraded comparators have theta ~ 1 (huge) and their
    resampled theta stays ~1 with tiny variance, so they should NOT be the binding
    constraint; the hard comparator drives q and its lower bound reflects the
    shared q.
    """
    n = 80
    rng = np.random.default_rng(3)
    # Headline: moderate errors.
    headline = rng.uniform(0.9, 1.1, size=n)
    # Hard comparator: only slightly larger errors → small positive theta.
    hard = rng.uniform(1.0, 1.2, size=n)
    # Degraded comparators: gigantic errors → theta ~ 1.
    degraded = rng.uniform(900.0, 1100.0, size=n)

    comparator_errors = {
        "additive": hard,
        "gears": degraded.copy(),
        "cpa": degraded.copy(),
        "id_only": degraded.copy(),
        "l3_hypernetwork": degraded.copy(),
    }

    res = simultaneous_theta_bounds(
        headline_errors=headline,
        comparator_errors=comparator_errors,
        comparators=FAMILY,
        confidence=CONF,
        n_replicates=REPS,
        seed=SEED,
    )

    # The degraded comparators are near a perfect win.
    for c in ("gears", "cpa", "id_only", "l3_hypernetwork"):
        assert res.theta[c] > 0.99, (c, res.theta[c])
    # The hard comparator has a small positive point theta.
    assert 0.0 < res.theta["additive"] < 0.3

    # The binding constraint: the hard comparator's resampling deviation is far
    # larger than any degraded comparator's. Recompute the per-comparator max
    # deviation contribution to assert the hard comparator drives q.
    n_obs = n
    hard_dev_max = -np.inf
    degraded_dev_max = -np.inf
    for b in range(REPS):
        idx = bs._replicate_indices(SEED, b, n_obs)
        mean_h = float(np.mean(headline[idx]))

        def theta_of(err: np.ndarray) -> float:
            return 1.0 - mean_h / max(float(np.mean(err[idx])), 1e-12)

        for c in FAMILY:
            theta_b = theta_of(comparator_errors[c])
            dev = res.theta[c] - theta_b
            if c == "additive":
                hard_dev_max = max(hard_dev_max, dev)
            else:
                degraded_dev_max = max(degraded_dev_max, dev)

    assert hard_dev_max > degraded_dev_max, (hard_dev_max, degraded_dev_max)

    # The common half-width equals the max-over-comparators deviation quantile,
    # and lower for the hard comparator uses that shared q.
    assert res.lower["additive"] == pytest.approx(
        res.theta["additive"] - res.band_halfwidth, abs=1e-12
    )
    # The degraded win is not manufactured: it remains a near-perfect win even
    # after subtracting the shared (hard-driven) q.
    for c in ("gears", "cpa", "id_only", "l3_hypernetwork"):
        assert res.lower[c] == pytest.approx(res.theta[c] - res.band_halfwidth, abs=1e-12)


# ---------------------------------------------------------------------------
# Small samples
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [2, 3])
def test_small_samples_run_and_return_finite(n: int) -> None:
    """n in {2, 3} runs deterministically with finite bounds and no crash."""
    headline = np.array([0.5, 0.7, 0.6][:n], dtype=np.float64)
    comparator_errors = {c: np.array([1.0, 1.2, 1.1][:n], dtype=np.float64) for c in FAMILY}
    res = simultaneous_theta_bounds(
        headline_errors=headline,
        comparator_errors=comparator_errors,
        comparators=FAMILY,
        confidence=CONF,
        n_replicates=50,
        seed=SEED,
    )
    for c in FAMILY:
        assert np.isfinite(res.theta[c])
        assert np.isfinite(res.lower[c])
    assert np.isfinite(res.band_halfwidth)


# ---------------------------------------------------------------------------
# Zero-comparator error: divide guarded
# ---------------------------------------------------------------------------


def test_zero_comparator_error_is_finite_large_negative() -> None:
    """All-zero comparator errors → 1e-12 floor guards the divide; theta finite."""
    n = 16
    headline = np.full(n, 0.5, dtype=np.float64)
    comparator_errors = _family_errors(2.0, n)
    comparator_errors["id_only"] = np.zeros(n, dtype=np.float64)  # zero error

    res = simultaneous_theta_bounds(
        headline_errors=headline,
        comparator_errors=comparator_errors,
        comparators=FAMILY,
        confidence=CONF,
        n_replicates=REPS,
        seed=SEED,
    )

    # theta_id_only = 1 - 0.5 / max(0, 1e-12) = 1 - 0.5/1e-12 = large negative.
    assert np.isfinite(res.theta["id_only"])
    assert res.theta["id_only"] < -1e10
    for c in FAMILY:
        assert np.isfinite(res.theta[c])
        assert np.isfinite(res.lower[c])
    assert np.isfinite(res.band_halfwidth)


def test_all_methods_perfect_is_an_exact_tie_not_a_win() -> None:
    zero = np.zeros(12, dtype=np.float64)
    res = simultaneous_theta_bounds(
        headline_errors=zero,
        comparator_errors={c: zero.copy() for c in FAMILY},
        comparators=FAMILY,
        confidence=CONF,
        n_replicates=REPS,
        seed=SEED,
    )
    assert all(value == pytest.approx(0.0) for value in res.theta.values())
    assert all(value == pytest.approx(0.0) for value in res.lower.values())


# ---------------------------------------------------------------------------
# Validation: non-finite, negative, missing comparator, empty/length/confidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_non_finite_input_raises(bad: float) -> None:
    n = 10
    headline = _const_errors(0.5, n)
    comparator_errors = _family_errors(1.0, n)
    comparator_errors["gears"][3] = bad
    with pytest.raises(ComposeInferenceError):
        simultaneous_theta_bounds(
            headline_errors=headline,
            comparator_errors=comparator_errors,
            comparators=FAMILY,
            confidence=CONF,
            n_replicates=REPS,
            seed=SEED,
        )


def test_non_finite_headline_raises() -> None:
    n = 10
    headline = _const_errors(0.5, n)
    headline[0] = np.nan
    comparator_errors = _family_errors(1.0, n)
    with pytest.raises(ComposeInferenceError):
        simultaneous_theta_bounds(
            headline_errors=headline,
            comparator_errors=comparator_errors,
            comparators=FAMILY,
            confidence=CONF,
            n_replicates=REPS,
            seed=SEED,
        )


def test_negative_input_raises() -> None:
    n = 10
    headline = _const_errors(0.5, n)
    comparator_errors = _family_errors(1.0, n)
    comparator_errors["cpa"][2] = -0.0001  # errors are squared distances >= 0
    with pytest.raises(ComposeInferenceError):
        simultaneous_theta_bounds(
            headline_errors=headline,
            comparator_errors=comparator_errors,
            comparators=FAMILY,
            confidence=CONF,
            n_replicates=REPS,
            seed=SEED,
        )


def test_negative_headline_raises() -> None:
    n = 10
    headline = _const_errors(0.5, n)
    headline[1] = -1.0
    comparator_errors = _family_errors(1.0, n)
    with pytest.raises(ComposeInferenceError):
        simultaneous_theta_bounds(
            headline_errors=headline,
            comparator_errors=comparator_errors,
            comparators=FAMILY,
            confidence=CONF,
            n_replicates=REPS,
            seed=SEED,
        )


def test_missing_comparator_raises() -> None:
    n = 10
    headline = _const_errors(0.5, n)
    comparator_errors = _family_errors(1.0, n)
    del comparator_errors["cpa"]  # listed in comparators but absent from mapping
    with pytest.raises(ComposeInferenceError):
        simultaneous_theta_bounds(
            headline_errors=headline,
            comparator_errors=comparator_errors,
            comparators=FAMILY,
            confidence=CONF,
            n_replicates=REPS,
            seed=SEED,
        )


def test_empty_comparator_family_raises() -> None:
    n = 10
    headline = _const_errors(0.5, n)
    comparator_errors = _family_errors(1.0, n)
    with pytest.raises(ComposeInferenceError):
        simultaneous_theta_bounds(
            headline_errors=headline,
            comparator_errors=comparator_errors,
            comparators=(),
            confidence=CONF,
            n_replicates=REPS,
            seed=SEED,
        )


def test_length_mismatch_raises() -> None:
    headline = _const_errors(0.5, 10)
    comparator_errors = _family_errors(1.0, 10)
    comparator_errors["additive"] = _const_errors(1.0, 9)  # wrong length
    with pytest.raises(ComposeInferenceError):
        simultaneous_theta_bounds(
            headline_errors=headline,
            comparator_errors=comparator_errors,
            comparators=FAMILY,
            confidence=CONF,
            n_replicates=REPS,
            seed=SEED,
        )


def test_zero_length_raises() -> None:
    headline = np.array([], dtype=np.float64)
    comparator_errors = {c: np.array([], dtype=np.float64) for c in FAMILY}
    with pytest.raises(ComposeInferenceError):
        simultaneous_theta_bounds(
            headline_errors=headline,
            comparator_errors=comparator_errors,
            comparators=FAMILY,
            confidence=CONF,
            n_replicates=REPS,
            seed=SEED,
        )


def test_non_1d_input_raises() -> None:
    headline = np.full((10, 1), 0.5, dtype=np.float64)  # 2-D
    comparator_errors = _family_errors(1.0, 10)
    with pytest.raises(ComposeInferenceError):
        simultaneous_theta_bounds(
            headline_errors=headline,
            comparator_errors=comparator_errors,
            comparators=FAMILY,
            confidence=CONF,
            n_replicates=REPS,
            seed=SEED,
        )


@pytest.mark.parametrize("conf", [0.0, 1.0, -0.1, 1.1])
def test_confidence_out_of_range_raises(conf: float) -> None:
    n = 10
    headline = _const_errors(0.5, n)
    comparator_errors = _family_errors(1.0, n)
    with pytest.raises(ComposeInferenceError):
        simultaneous_theta_bounds(
            headline_errors=headline,
            comparator_errors=comparator_errors,
            comparators=FAMILY,
            confidence=conf,
            n_replicates=REPS,
            seed=SEED,
        )


def test_n_replicates_below_one_raises() -> None:
    n = 10
    headline = _const_errors(0.5, n)
    comparator_errors = _family_errors(1.0, n)
    with pytest.raises(ComposeInferenceError):
        simultaneous_theta_bounds(
            headline_errors=headline,
            comparator_errors=comparator_errors,
            comparators=FAMILY,
            confidence=CONF,
            n_replicates=0,
            seed=SEED,
        )


# ---------------------------------------------------------------------------
# Determinism: process-stable + pinned to the shared primitive
# ---------------------------------------------------------------------------


def test_process_stable_determinism_identical_results_and_checksum() -> None:
    n = 48
    rng = np.random.default_rng(11)
    headline = rng.uniform(0.01, 0.1, size=n)
    comparator_errors = {c: rng.uniform(0.5, 2.0, size=n) for c in FAMILY}

    res1 = simultaneous_theta_bounds(
        headline_errors=headline,
        comparator_errors=comparator_errors,
        comparators=FAMILY,
        confidence=CONF,
        n_replicates=REPS,
        seed=SEED,
    )
    res2 = simultaneous_theta_bounds(
        headline_errors=headline,
        comparator_errors=comparator_errors,
        comparators=FAMILY,
        confidence=CONF,
        n_replicates=REPS,
        seed=SEED,
    )
    for c in FAMILY:
        assert res1.theta[c] == res2.theta[c]
        assert res1.lower[c] == res2.lower[c]
    assert res1.band_halfwidth == res2.band_halfwidth
    assert res1.checksum == res2.checksum
    assert res1.comparators == res2.comparators == FAMILY


def test_determinism_pinned_to_shared_replicate_indices() -> None:
    """Reproduce theta_C_b using bs._replicate_indices to pin the seeding.

    A future change to the shared primitive's seeding would break this test,
    proving determinism is identical to CARTOGRAPHER's bootstrap.
    """
    n = 32
    rng = np.random.default_rng(5)
    headline = rng.uniform(0.1, 0.3, size=n)
    comparator_errors = {c: rng.uniform(0.5, 1.5, size=n) for c in FAMILY}

    res = simultaneous_theta_bounds(
        headline_errors=headline,
        comparator_errors=comparator_errors,
        comparators=FAMILY,
        confidence=CONF,
        n_replicates=REPS,
        seed=SEED,
    )

    # Independently reconstruct the max-deviation array using the SHARED primitive
    # and the SAME idx for headline and every comparator.
    point_theta = {
        c: (float(np.mean(comparator_errors[c])) - float(np.mean(headline)))
        / max(float(np.mean(comparator_errors[c])), 1e-12)
        for c in FAMILY
    }
    max_dev = np.empty(REPS, dtype=np.float64)
    for b in range(REPS):
        idx = bs._replicate_indices(SEED, b, n)
        mean_h_b = float(np.mean(headline[idx]))
        devs = []
        for c in FAMILY:
            mean_c_b = float(np.mean(comparator_errors[c][idx]))
            theta_c_b = (mean_c_b - mean_h_b) / max(mean_c_b, 1e-12)
            devs.append(point_theta[c] - theta_c_b)
        max_dev[b] = max(devs)
    q_expected = float(np.quantile(max_dev, CONF, method="linear"))

    assert res.band_halfwidth == pytest.approx(q_expected, abs=0.0, rel=0.0)
    for c in FAMILY:
        assert res.theta[c] == pytest.approx(point_theta[c], abs=0.0, rel=0.0)
        assert res.lower[c] == pytest.approx(point_theta[c] - q_expected, abs=0.0, rel=0.0)

    # Spot-check that the EXACT indices used match the shared primitive for a
    # couple of replicate values (so a future seeding change fails here).
    for b in (0, 3, REPS - 1):
        idx = bs._replicate_indices(SEED, b, n)
        assert idx.shape == (n,)
        assert idx.min() >= 0 and idx.max() < n


def test_headline_not_a_comparator_and_order_preserved() -> None:
    """The headline l1_bilinear_identifiable is never a comparator; order kept."""
    n = 20
    headline = _const_errors(0.2, n)
    comparator_errors = _family_errors(1.0, n)
    res = simultaneous_theta_bounds(
        headline_errors=headline,
        comparator_errors=comparator_errors,
        comparators=FAMILY,
        confidence=CONF,
        n_replicates=REPS,
        seed=SEED,
    )
    assert res.comparators == FAMILY
    assert "l1_bilinear_identifiable" not in res.theta
    assert "l1_bilinear_identifiable" not in res.lower
