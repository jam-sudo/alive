"""Tests for the registered bilinear identification solvers."""

from __future__ import annotations

import numpy as np
import pytest

from alive.compose.identify import (
    REGULARIZED_SOLVER,
    RankReport,
    SingularDesignError,
    identify_operator,
    rank_diagnostics,
    solve_ridge_svd,
)
from alive.compose.operator import bilinear_predict, design_matrix, sym_basis_dim


def _make(rng, n_genes=20, k=4, p=3, n_pairs=40):
    Z = rng.normal(size=(n_genes, k))
    coef_true = rng.normal(size=(p, sym_basis_dim(k)))
    pairs = [(int(a), int(b)) for a, b in rng.integers(0, n_genes, size=(n_pairs, 2)) if a != b]
    eps = np.vstack([bilinear_predict(coef_true, Z[g], Z[h]) for g, h in pairs])
    return Z, coef_true, pairs, eps


def test_noiseless_full_rank_recovers_coef():
    rng = np.random.default_rng(0)
    Z, coef_true, pairs, eps = _make(rng)
    rep = rank_diagnostics(Z, pairs)
    assert isinstance(rep, RankReport)
    assert rep.is_full_rank
    coef_hat = identify_operator(Z, pairs, eps, lam=0.0)
    np.testing.assert_allclose(coef_hat, coef_true, atol=1e-6)


def test_predicts_held_out_pair_when_full_rank():
    rng = np.random.default_rng(1)
    Z, coef_true, pairs, eps = _make(rng)
    coef_hat = identify_operator(Z, pairs, eps, lam=0.0)
    np.testing.assert_allclose(
        bilinear_predict(coef_hat, Z[0], Z[5]),
        bilinear_predict(coef_true, Z[0], Z[5]),
        atol=1e-6,
    )


def test_rank_deficient_flagged():
    rng = np.random.default_rng(2)
    Z = rng.normal(size=(20, 4))
    pairs = [(0, 1), (0, 1), (0, 1)]
    rep = rank_diagnostics(Z, pairs)
    assert not rep.is_full_rank
    assert rep.rank == 1
    assert rep.sym_dim == sym_basis_dim(4)
    assert rep.condition_number == float("inf")


def test_lapack_unregularized_failure_is_normalized(monkeypatch):
    Z = np.zeros((6, 3))
    pairs = [(i, j) for i in range(6) for j in range(i + 1, 6)]
    eps = np.zeros((len(pairs), 2))

    def _failing_lstsq(phi, target, *, rcond):
        raise np.linalg.LinAlgError("synthetic failure")

    monkeypatch.setattr(np.linalg, "lstsq", _failing_lstsq)
    with pytest.raises(SingularDesignError, match="least-squares solver failed"):
        identify_operator(Z, pairs, eps, lam=0.0)


def test_regularisation_makes_rank_deficient_design_solvable():
    Z = np.zeros((6, 3))
    pairs = [(i, j) for i in range(6) for j in range(i + 1, 6)]
    eps = np.zeros((len(pairs), 2))
    coef = identify_operator(Z, pairs, eps, lam=1e-3)
    assert coef.shape == (2, sym_basis_dim(3))
    assert np.all(coef == 0.0)


def test_unregularized_rank_deficient_fit_is_minimum_norm():
    Z = np.zeros((6, 3))
    pairs = [(i, j) for i in range(6) for j in range(i + 1, 6)]
    eps = np.zeros((len(pairs), 2))
    coef = identify_operator(Z, pairs, eps, lam=0.0)
    assert coef.shape == (2, sym_basis_dim(3))
    assert np.all(coef == 0.0)


@pytest.mark.parametrize("lam", [0.001, 0.01, 0.1])
def test_svd_ridge_matches_augmented_least_squares_reference(lam):
    rng = np.random.default_rng(10)
    Z, _, pairs, eps = _make(rng)
    phi = design_matrix(Z, pairs)
    augmented_design = np.vstack([phi, np.sqrt(lam) * np.eye(phi.shape[1])])
    augmented_target = np.vstack([eps, np.zeros((phi.shape[1], eps.shape[1]))])
    reference, *_ = np.linalg.lstsq(augmented_design, augmented_target, rcond=None)

    assert REGULARIZED_SOLVER == "svd_ridge_filter_factors"
    observed = identify_operator(Z, pairs, eps, lam=lam).T
    np.testing.assert_allclose(observed, reference, rtol=2e-11, atol=2e-11)


def test_positive_ridge_does_not_form_or_solve_normal_equations(monkeypatch):
    rng = np.random.default_rng(4)
    Z, _, pairs, eps = _make(rng)
    scaled = Z * 1e4
    phi = design_matrix(scaled, pairs)
    base = phi.T @ phi
    # This is the precise failure mode of the replaced implementation: lambda
    # disappears completely if it is first added to the Gram matrix.
    assert np.array_equal(base + 1e-3 * np.eye(base.shape[0]), base)

    def _forbidden_solve(*args, **kwargs):
        raise AssertionError("positive ridge must not call np.linalg.solve")

    monkeypatch.setattr(np.linalg, "solve", _forbidden_solve)
    coef = identify_operator(scaled, pairs, eps, lam=1e-3)
    assert coef.shape == (eps.shape[1], phi.shape[1])
    assert np.all(np.isfinite(coef))


def test_filter_factor_formula_handles_extreme_singular_value_spread():
    design = np.diag([1e12, 1.0, 0.0])
    target = np.eye(3)
    lam = 1e-3
    observed = solve_ridge_svd(design, target, lam=lam)
    expected = np.diag(
        [
            (1.0 / 1e12) / (1.0 + lam / 1e24),
            1.0 / (1.0 + lam),
            0.0,
        ]
    )
    np.testing.assert_allclose(observed, expected, rtol=1e-15, atol=0.0)


def test_regularized_svd_failure_is_normalized(monkeypatch):
    rng = np.random.default_rng(12)
    Z, _, pairs, eps = _make(rng)

    def _failing_svd(*args, **kwargs):
        raise np.linalg.LinAlgError("synthetic SVD failure")

    monkeypatch.setattr(np.linalg, "svd", _failing_svd)
    with pytest.raises(SingularDesignError, match="regularized SVD solver failed"):
        identify_operator(Z, pairs, eps, lam=1e-3)


@pytest.mark.parametrize("lam", [-1.0, np.nan, np.inf])
def test_invalid_regularisation_is_rejected(lam):
    rng = np.random.default_rng(3)
    Z, _, pairs, eps = _make(rng)
    with pytest.raises(ValueError, match="finite and non-negative"):
        identify_operator(Z, pairs, eps, lam=lam)


@pytest.mark.parametrize("field", ["Z", "target"])
def test_non_finite_regression_inputs_are_rejected(field):
    rng = np.random.default_rng(13)
    Z, _, pairs, eps = _make(rng)
    if field == "Z":
        Z[0, 0] = np.nan
    else:
        eps[0, 0] = np.inf
    with pytest.raises(ValueError, match="finite"):
        identify_operator(Z, pairs, eps, lam=1e-3)


def test_a_non_finite_factor_bank_is_a_typed_preseal_rejection():
    """A NaN in a PREPARE factor bank must reach the operator as a contracted 10.

    Nothing upstream checks factor-bank finiteness -- ``select._validate_inputs``
    looks at ndim/shape, ``phase2a._validate_pair_alignment`` at shape -- so this is
    the first gate that sees it, and while it raised a bare ``ValueError`` the driver
    exited 1 (the registered bug escape) for an ordinary bad input (2026-08-02
    review). Still a ``ValueError`` subclass, so every existing caller is unaffected.
    """
    import numpy as np
    import pytest

    from alive.compose.driver.cli import _KNOWN_PRESEAL_REJECTIONS
    from alive.compose.identify import EstimatorInputError, identify_operator

    Z = np.array([[1.0, 0.0], [0.0, 1.0], [np.nan, 1.0]], dtype=float)
    pairs = [(0, 1), (0, 2)]
    eps = np.zeros((2, 2), dtype=float)

    with pytest.raises(EstimatorInputError):
        identify_operator(Z, pairs, eps, lam=1e-3)

    assert issubclass(EstimatorInputError, ValueError)
    assert isinstance(EstimatorInputError("x"), _KNOWN_PRESEAL_REJECTIONS)


def test_the_phase2a_invariant_class_is_a_bug_not_a_contracted_rejection():
    """The other half of the split: an internal invariant must stay exit 1.

    ``CONTINUE`` without the persisted OOF fold manifest used to raise
    ``OutcomeLeakageError``, so a code invariant was reported to a pod operator as a
    documented pre-seal rejection. The genuine leakage assertion in step 9 keeps its
    own class -- that one really does mean a sealed outcome was touched.
    """
    from alive.compose.driver.cli import _KNOWN_PRESEAL_REJECTIONS
    from alive.compose.freeze import OutcomeLeakageError
    from alive.compose.phase2a import Phase2aInvariantError

    assert not isinstance(Phase2aInvariantError("x"), _KNOWN_PRESEAL_REJECTIONS)
    assert not issubclass(Phase2aInvariantError, OutcomeLeakageError)
    assert isinstance(OutcomeLeakageError("x"), _KNOWN_PRESEAL_REJECTIONS)
