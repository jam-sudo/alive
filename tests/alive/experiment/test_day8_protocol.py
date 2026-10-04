"""Synthetic tests for CART-K562-D8-v1 draft protocol primitives."""

from __future__ import annotations

import math

import numpy as np
import pytest

from alive.experiment.day8_protocol import (
    batch_matched_reference,
    noise_analytic_probability,
    split_roles,
)


def test_split_roles_is_disjoint_stratified_and_deterministic():
    targets = [f"T{i}" for i in range(20)]
    strata = {t: ("a" if i < 10 else "b") for i, t in enumerate(targets)}
    roles = split_roles(targets, strata, fractions=(0.4, 0.2), seed=7)
    assert sorted(sum(roles.values(), [])) == sorted(targets)
    for s in ("a", "b"):
        members = [t for t in targets if strata[t] == s]
        assert [len(set(roles[r]) & set(members)) for r in ("D", "C", "E")] == [4, 2, 4]
    assert roles == split_roles(targets, strata, fractions=(0.4, 0.2), seed=7)
    assert roles != split_roles(targets, strata, fractions=(0.4, 0.2), seed=8)


def test_noise_analytic_probability_known_answers():
    phi = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    # Predicted NEGLIGIBLE at 0 with sigma 0.1, tau 0.2, eps 0.2: interval [-0.2, 0.2].
    p = noise_analytic_probability(np.array([0.0]), np.array([0.1]), tau=0.2, epsilon=0.2)
    assert np.isclose(p[0], phi(2) - phi(-2))
    # Predicted UP at 1.0: class (0.2, inf) intersect [0.8, 1.2] = [0.8, 1.2].
    p = noise_analytic_probability(np.array([1.0]), np.array([0.1]), tau=0.2, epsilon=0.2)
    assert np.isclose(p[0], phi(2) - phi(-2))
    # Predicted UP at 0.25: class (0.2, inf) intersect [0.05, 0.45] = (0.2, 0.45].
    p = noise_analytic_probability(np.array([0.25]), np.array([0.1]), tau=0.2, epsilon=0.2)
    assert np.isclose(p[0], phi(2.0) - phi(-0.5))


def test_noise_analytic_probability_rejects_nonpositive_sigma():
    with pytest.raises(ValueError, match="sigma"):
        noise_analytic_probability(np.array([0.0]), np.array([0.0]), tau=0.2, epsilon=0.2)


def test_batch_matched_reference_weights_groups_by_target_share():
    ref = np.array([[0.0], [0.0], [10.0]])
    ref_groups = np.array([1, 1, 2])
    target_groups = np.array([2, 2, 2, 1])  # 3/4 in group 2, 1/4 in group 1
    got, fallback = batch_matched_reference(ref, ref_groups, target_groups)
    assert np.allclose(got, [0.75 * 10.0 + 0.25 * 0.0])
    assert fallback == []


def test_batch_matched_reference_records_pooled_fallback():
    ref = np.array([[1.0], [3.0]])
    got, fallback = batch_matched_reference(ref, np.array([1, 1]), np.array([1, 9]))
    assert np.allclose(got, [0.5 * 2.0 + 0.5 * 2.0])
    assert fallback == [9]


def test_joint_event_matches_scalar_reference_including_boundaries():
    from alive.eval.events import classify_direction_magnitude
    from alive.experiment.day8_protocol import joint_event

    rng = np.random.default_rng(5)
    h = np.concatenate([rng.normal(0, 0.3, 500), [0.2, -0.2, 1.0, 1.25, -0.25]])
    d = np.concatenate([rng.normal(0, 0.3, 500), [0.2, 0.3, 1.2, 1.0, 0.25]])
    got = joint_event(h, d, tau=0.2, epsilon=0.2)
    for i in range(len(h)):
        ref = classify_direction_magnitude(float(h[i]), float(d[i]), tau=0.2, epsilon=0.2)
        want = [ref[k] for k in ref if isinstance(ref[k], bool)]
        assert [bool(got["z_dir"][i]), bool(got["z_mag"][i]), bool(got["z_joint"][i])] == want


def test_sign_event_counts_zero_observation_as_failure():
    from alive.experiment.day8_protocol import sign_event

    got = sign_event(np.array([0.5, 0.5, -0.5, 0.5]), np.array([0.1, -0.1, -0.3, 0.0]))
    assert got.tolist() == [True, False, True, False]


def test_attenuation_slope_recovers_known_shrinkage():
    from alive.experiment.day8_protocol import attenuation_slope

    rng = np.random.default_rng(2)
    targets = np.repeat(np.arange(200), 20).astype(str)
    h = rng.normal(0, 1, len(targets))
    d = 0.6 * h + rng.normal(0, 0.1, len(h))
    out = attenuation_slope(h, d, targets, n_boot=200, seed=0, alpha=0.05)
    assert abs(out["slope"] - 0.6) < 0.02 and out["ci"][0] < 0.6 < out["ci"][1] and out["ci"][1] < 1
