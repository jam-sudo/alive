"""Tests for alive.compose.models — written FIRST per TDD protocol.

Covers Task 2a-5: the four SYMMETRIC composition models (L1, L2, ID-only, L3)
and the load-bearing PAIR-SYMMETRY invariant (plan §2.3): genetic-combination
prediction is UNORDERED, so ``predict_eps(g, h) == predict_eps(h, g)`` EXACTLY
for every model. Concatenating ``[z_g, z_h]`` is prohibited because it makes the
prediction depend on label order; only order-invariant pair features are allowed.

Known-answer coverage (brief):
  * symmetry for every model (exact);
  * noiseless L1 recovery under full rank;
  * finite, bounded behaviour under rank deficiency;
  * false-GI null behaviour (eps_true == 0 -> small predicted GI);
  * L2 monotone saturation of the L1 score;
  * deterministic L3 initialisation AND training (two fits byte-identical);
  * identical input/output shape rules across models.
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.compose.identify import SingularDesignError, rank_diagnostics
from alive.compose.models import (
    IDOnlyModel,
    L1Model,
    L2Model,
    L3Model,
    SymmetricModel,
    fitted_model_checksum,
)
from alive.compose.operator import bilinear_predict, sym_basis_dim

ALL_MODEL_CLASSES = (L1Model, L2Model, IDOnlyModel, L3Model)


def _make(rng, n_genes=24, k=4, p=3, n_pairs=80):
    """A full-rank synthetic bilinear instance (mirrors test_identify._make)."""
    Z = rng.normal(size=(n_genes, k))
    coef_true = rng.normal(size=(p, sym_basis_dim(k)))
    seen: set[tuple[int, int]] = set()
    pairs: list[tuple[int, int]] = []
    while len(pairs) < n_pairs:
        a, b = int(rng.integers(n_genes)), int(rng.integers(n_genes))
        if a == b:
            continue
        key = (min(a, b), max(a, b))
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)
    eps = np.vstack([bilinear_predict(coef_true, Z[g], Z[h]) for g, h in pairs])
    return Z, coef_true, pairs, eps


def _fit_all(rng=None):
    """Fit one of every model on the same full-rank instance; return (Z, models)."""
    rng = rng or np.random.default_rng(0)
    Z, coef_true, pairs, eps = _make(rng)
    models = [cls().fit(Z, pairs, eps, lam=1e-3) for cls in ALL_MODEL_CLASSES]
    return Z, coef_true, pairs, eps, models


# --------------------------------------------------------------------------- #
# Protocol / shape rules
# --------------------------------------------------------------------------- #
def test_all_models_satisfy_protocol():
    for cls in ALL_MODEL_CLASSES:
        assert issubclass(cls, SymmetricModel)


def test_fit_returns_self_for_chaining():
    rng = np.random.default_rng(1)
    Z, _, pairs, eps = _make(rng)
    for cls in ALL_MODEL_CLASSES:
        m = cls()
        assert m.fit(Z, pairs, eps, lam=1e-3) is m


def test_predict_eps_is_one_d_of_length_p():
    Z, _, _, eps, models = _fit_all()
    p = eps.shape[1]
    for m in models:
        out = m.predict_eps(Z, 0, 7)
        assert isinstance(out, np.ndarray)
        assert out.shape == (p,)
        assert out.dtype == np.float64
        assert np.all(np.isfinite(out))


def test_predict_eps_rejects_out_of_range_index():
    Z, _, _, _, models = _fit_all()
    n_genes = Z.shape[0]
    for m in models:
        with pytest.raises((IndexError, ValueError)):
            m.predict_eps(Z, 0, n_genes)  # h out of range


def test_predict_before_fit_raises():
    Z = np.random.default_rng(2).normal(size=(10, 4))
    for cls in ALL_MODEL_CLASSES:
        with pytest.raises((RuntimeError, ValueError, AttributeError)):
            cls().predict_eps(Z, 0, 1)


# --------------------------------------------------------------------------- #
# THE central invariant: pair symmetry (load-bearing, plan §2.3)
# --------------------------------------------------------------------------- #
def test_predict_is_symmetric_for_every_model():
    """predict_eps(g, h) == predict_eps(h, g) EXACTLY for every model."""
    Z, _, _, _, models = _fit_all()
    n_genes = Z.shape[0]
    rng = np.random.default_rng(99)
    probe = [(int(a), int(b)) for a, b in rng.integers(0, n_genes, size=(25, 2)) if a != b]
    for m in models:
        for g, h in probe:
            np.testing.assert_array_equal(m.predict_eps(Z, g, h), m.predict_eps(Z, h, g))


def test_symmetry_holds_for_distinct_factor_values():
    """A non-degenerate check: z_g != z_h, prediction still order-invariant."""
    Z, _, _, _, models = _fit_all()
    g, h = 3, 11
    assert not np.allclose(Z[g], Z[h])  # genuinely different factors
    for m in models:
        np.testing.assert_array_equal(m.predict_eps(Z, g, h), m.predict_eps(Z, h, g))


# --------------------------------------------------------------------------- #
# L1: noiseless recovery + rank-deficient bounded behaviour
# --------------------------------------------------------------------------- #
def test_l1_noiseless_full_rank_recovers_truth():
    rng = np.random.default_rng(3)
    Z, coef_true, pairs, eps = _make(rng)
    m = L1Model().fit(Z, pairs, eps, lam=0.0)
    for g, h in [(0, 5), (1, 9), (2, 13)]:
        np.testing.assert_allclose(
            m.predict_eps(Z, g, h),
            bilinear_predict(coef_true, Z[g], Z[h]),
            atol=1e-6,
        )


def test_l1_rank_deficient_is_finite_and_bounded():
    """Under rank deficiency a ridge-regularised L1 fit must stay finite/bounded."""
    rng = np.random.default_rng(4)
    Z = rng.normal(size=(20, 4))
    coef_true = rng.normal(size=(3, sym_basis_dim(4)))
    pairs = [(0, 1), (0, 1), (2, 3)]  # far too few unique pairs -> rank deficient
    eps = np.vstack([bilinear_predict(coef_true, Z[g], Z[h]) for g, h in pairs])
    m = L1Model().fit(Z, pairs, eps, lam=1.0)  # ridge keeps the solve well-posed
    out = m.predict_eps(Z, 5, 6)
    assert np.all(np.isfinite(out))
    assert np.linalg.norm(out) < 1e6  # bounded, no blow-up


def test_l1_false_gi_null_behaviour():
    """eps_true == 0 (no genetic interaction) -> predicted GI is small."""
    rng = np.random.default_rng(5)
    Z, _, pairs, _ = _make(rng)
    p = 3
    eps_zero = np.zeros((len(pairs), p))
    m = L1Model().fit(Z, pairs, eps_zero, lam=1e-3)
    for g, h in [(0, 5), (1, 9), (2, 13)]:
        assert np.linalg.norm(m.predict_eps(Z, g, h)) < 1e-6


# --------------------------------------------------------------------------- #
# L2: preregistered monotone saturation of the L1 score
# --------------------------------------------------------------------------- #
def test_l2_is_monotone_saturation_of_l1():
    """L2 output is a coordinatewise monotone map of the L1 score.

    With ``scale_m * tanh(L1_m)`` the L2 prediction must, per output coordinate
    ``m``, be non-decreasing and sign-preserving in the L1 score.  The fitted
    scale is constrained non-negative to make this a structural invariant.
    """
    rng = np.random.default_rng(6)
    Z, _, pairs, eps = _make(rng)
    l1 = L1Model().fit(Z, pairs, eps, lam=1e-3)
    l2 = L2Model().fit(Z, pairs, eps, lam=1e-3)

    # Build a sweep of pairs and confirm coordinatewise monotonicity vs the L1 score.
    n_genes = Z.shape[0]
    probe = [(0, j) for j in range(1, n_genes)]
    l1_scores = np.vstack([l1.predict_eps(Z, g, h) for g, h in probe])
    l2_scores = np.vstack([l2.predict_eps(Z, g, h) for g, h in probe])

    for c in range(eps.shape[1]):
        order = np.argsort(l1_scores[:, c])
        sorted_l2 = l2_scores[order, c]
        diffs = np.diff(sorted_l2)
        assert l2.scale_[c] >= 0.0
        assert np.all(diffs >= -1e-9)
        # Each L2 value equals scale_c * tanh(L1_c) EXACTLY (the defining map).
        np.testing.assert_allclose(
            l2_scores[:, c], l2.scale_[c] * np.tanh(l1_scores[:, c]), atol=1e-12
        )


def test_l2_saturates_for_large_scores():
    """As |L1 score| grows, |L2| is bounded by the fitted per-output scale."""
    rng = np.random.default_rng(7)
    Z, _, pairs, eps = _make(rng)
    l2 = L2Model().fit(Z, pairs, eps, lam=1e-3)
    # Inflate the factors to push the bilinear score large; tanh must bound it.
    Z_big = Z * 50.0
    out = l2.predict_eps(Z_big, 0, 5)
    assert np.all(np.isfinite(out))
    # |scale * tanh(.)| <= |scale|; bound by the largest fitted scale magnitude.
    assert np.max(np.abs(out)) <= np.max(np.abs(l2.scale_)) + 1e-9


# --------------------------------------------------------------------------- #
# ID-only: symmetric non-bilinear ridge features
# --------------------------------------------------------------------------- #
def test_id_only_uses_symmetric_features_not_concat():
    """ID-only must be order-invariant -> built from [z_g+z_h, |z_g-z_h|]."""
    Z, _, _, _, _ = _fit_all()
    rng = np.random.default_rng(8)
    Z2, _, pairs, eps = _make(rng)
    m = IDOnlyModel().fit(Z2, pairs, eps, lam=1e-2)
    g, h = 4, 17
    np.testing.assert_array_equal(m.predict_eps(Z2, g, h), m.predict_eps(Z2, h, g))


# --------------------------------------------------------------------------- #
# L3: deterministic init AND training; symmetric features
# --------------------------------------------------------------------------- #
def test_l3_deterministic_init_and_training():
    """Two independent L3 fits on identical data are byte-identical (init+train)."""
    rng_a = np.random.default_rng(0)
    Z, _, pairs, eps = _make(rng_a)
    m1 = L3Model().fit(Z, pairs, eps, lam=1e-3)
    m2 = L3Model().fit(Z, pairs, eps, lam=1e-3)
    g, h = 2, 19
    np.testing.assert_array_equal(m1.predict_eps(Z, g, h), m2.predict_eps(Z, g, h))
    # The learned parameters themselves must match exactly, not just one prediction.
    for w1, w2 in zip(m1.weights_, m2.weights_):
        np.testing.assert_array_equal(w1, w2)


def test_l3_is_symmetric():
    rng = np.random.default_rng(0)
    Z, _, pairs, eps = _make(rng)
    m = L3Model().fit(Z, pairs, eps, lam=1e-3)
    for g, h in [(1, 8), (3, 20), (5, 22)]:
        np.testing.assert_array_equal(m.predict_eps(Z, g, h), m.predict_eps(Z, h, g))


def test_l3_training_reduces_train_error():
    """A higher-capacity learner should fit the calibration pairs better than init."""
    rng = np.random.default_rng(0)
    Z, _, pairs, eps = _make(rng)
    m = L3Model()
    # init-only error
    m._lazy_init(Z, pairs, eps)  # type: ignore[attr-defined]
    init_pred = np.vstack([m._forward(Z, g, h) for g, h in pairs])  # type: ignore[attr-defined]
    init_mse = float(np.mean((init_pred - eps) ** 2))
    m.fit(Z, pairs, eps, lam=1e-3)
    trained_pred = np.vstack([m.predict_eps(Z, g, h) for g, h in pairs])
    trained_mse = float(np.mean((trained_pred - eps) ** 2))
    assert trained_mse < init_mse


# --------------------------------------------------------------------------- #
# Shape rules are identical across all four models
# --------------------------------------------------------------------------- #
def test_identical_output_shape_across_models():
    Z, _, _, eps, models = _fit_all()
    shapes = {m.predict_eps(Z, 0, 9).shape for m in models}
    assert shapes == {(eps.shape[1],)}


def test_models_accept_varying_p():
    """Output dimension p tracks eps_obs columns for every model."""
    for p in (1, 2, 5):
        rng = np.random.default_rng(100 + p)
        Z, _, pairs, _ = _make(rng, p=p)
        eps = np.random.default_rng(200 + p).normal(size=(len(pairs), p))
        for cls in ALL_MODEL_CLASSES:
            out = cls().fit(Z, pairs, eps, lam=1e-2).predict_eps(Z, 0, 1)
            assert out.shape == (p,)


def test_fitted_model_checksum_is_deterministic_and_state_sensitive():
    rng = np.random.default_rng(908)
    Z, _, pairs, eps = _make(rng)
    first = L1Model().fit(Z, pairs, eps, lam=1e-3)
    second = L1Model().fit(Z, pairs, eps, lam=1e-3)
    assert fitted_model_checksum(first) == fitted_model_checksum(second)
    second.coef_[0, 0] += 1e-13
    assert fitted_model_checksum(first) != fitted_model_checksum(second)


def test_fitted_model_checksum_rejects_unregistered_type():
    class DuckModel:
        pass

    with pytest.raises(TypeError, match="unregistered fitted model type"):
        fitted_model_checksum(DuckModel())  # type: ignore[arg-type]


def test_id_only_singular_design_raises_the_contracted_type():
    """A singular ``id_only`` ridge must not escape the driver's exit-code contract.

    This solve is reached from the same post-selection loop in phase2a as the
    bilinear estimator, but ``numpy.linalg.LinAlgError`` is a bare ``ValueError``
    subclass and not a ``SingularDesignError``, so it was absent from the driver's
    pre-seal rejection roster and produced a traceback plus exit 1, writing no
    artifact.

    The factor bank here is the input class the fix actually protects, which
    matters: the BILINEAR design is full rank, so the registered
    estimator-domain rank policy leaves ``lam == 0.0`` selectable, while the
    ``id_only`` design — whose features are ``[z_g + z_h, |z_g - z_h|, 1]`` — is
    rank-deficient because a constant factor coordinate makes it collinear with
    the intercept. A bank that is rank-deficient bilinearly would be excluded by
    the policy before this solve is ever reached, and would prove only the type
    mapping.

    Exposure is confined to ``lam == 0.0``, which the second half asserts rather
    than argues: an earlier version of this docstring justified it by claiming a
    positive lambda cannot rescue an intercept-collinear design, and that is
    false — with the intercept unpenalised the Gram is positive definite for
    every ``lam > 0``, and ``lam = 1e-12`` solves cleanly on this very input.
    """
    rng = np.random.default_rng(4)
    Z = rng.normal(size=(20, 4))
    Z[:, 2] = 0.75  # one constant coordinate: bilinear full rank, id_only singular
    pairs = [(int(a), int(b)) for a, b in rng.integers(0, 20, size=(41, 2)) if a != b]
    eps = rng.normal(size=(len(pairs), 3))
    assert rank_diagnostics(Z, pairs).is_full_rank

    with pytest.raises(SingularDesignError, match="id_only design has no unique ridge solution"):
        IDOnlyModel().fit(Z, pairs, eps, lam=0.0)

    for lam in (1e-12, *(0.001, 0.01, 0.1)):
        assert IDOnlyModel().fit(Z, pairs, eps, lam=lam).weight_ is not None
