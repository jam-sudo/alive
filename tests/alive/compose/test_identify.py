"""Tests for alive.compose.identify — written FIRST per TDD protocol."""

from __future__ import annotations

import math

import numpy as np
import pytest

from alive.compose.identify import (
    RankReport,
    SingularDesignError,
    identify_operator,
    rank_diagnostics,
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
    assert rep.is_full_rank  # enough diverse pairs
    coef_hat = identify_operator(Z, pairs, eps, lam=0.0)
    np.testing.assert_allclose(coef_hat, coef_true, atol=1e-6)


def test_predicts_held_out_pair_when_full_rank():
    rng = np.random.default_rng(1)
    Z, coef_true, pairs, eps = _make(rng)
    coef_hat = identify_operator(Z, pairs, eps, lam=0.0)
    g, h = 0, 5  # a pair not necessarily in `pairs`
    np.testing.assert_allclose(
        bilinear_predict(coef_hat, Z[g], Z[h]),
        bilinear_predict(coef_true, Z[g], Z[h]),
        atol=1e-6,
    )


def test_rank_deficient_flagged():
    rng = np.random.default_rng(2)
    Z = rng.normal(size=(20, 4))
    pairs = [(0, 1), (0, 1), (0, 1)]  # one unique pair → rank 1
    rep = rank_diagnostics(Z, pairs)
    assert not rep.is_full_rank
    assert rep.rank == 1
    assert rep.sym_dim == sym_basis_dim(4)
    # A rank-deficient design is effectively infinitely conditioned: the diagnostic
    # must NOT read "well-conditioned" off only the positive singular values.
    assert not np.isfinite(rep.condition_number)
    assert rep.condition_number == float("inf")


def test_lapack_singular_failure_is_normalized_to_typed_error(monkeypatch):
    """The general estimator normalizes LAPACK failure for its callers.

    Phase-2a does its policy-specific precheck in OOF selection. This lower-level
    function remains usable by Phase 1's rank-deficient recovery diagnostic.
    """
    n_genes, k, p = 6, 3, 2
    Z = np.zeros((n_genes, k))
    pairs = [(i, j) for i in range(n_genes) for j in range(i + 1, n_genes)]
    eps = np.zeros((len(pairs), p))

    def _failing_lstsq(phi, target, *, rcond):
        raise np.linalg.LinAlgError("synthetic singular pivot")

    monkeypatch.setattr(np.linalg, "lstsq", _failing_lstsq)
    with pytest.raises(SingularDesignError, match="least-squares solver failed"):
        identify_operator(Z, pairs, eps, lam=0.0)


def test_regularisation_makes_the_same_design_solvable():
    """The guard fires on singularity itself, not on the design being degenerate."""
    n_genes, k, p = 6, 3, 2
    Z = np.zeros((n_genes, k))
    pairs = [(i, j) for i in range(n_genes) for j in range(i + 1, n_genes)]
    eps = np.zeros((len(pairs), p))
    coef = identify_operator(Z, pairs, eps, lam=1e-3)
    assert coef.shape == (p, sym_basis_dim(k))
    assert np.all(coef == 0.0)


def test_unregularized_rank_deficient_fit_is_defined_by_minimum_norm():
    """Phase 1 can characterize rank-deficient recovery without a singular solve."""
    n_genes, k, p = 6, 3, 2
    Z = np.zeros((n_genes, k))
    pairs = [(i, j) for i in range(n_genes) for j in range(i + 1, n_genes)]
    eps = np.zeros((len(pairs), p))

    coef = identify_operator(Z, pairs, eps, lam=0.0)

    assert coef.shape == (p, sym_basis_dim(k))
    assert np.all(coef == 0.0)


def test_ridge_swallowed_by_the_gram_scale_is_rejected():
    """A positive lambda the Gram cannot represent must not be solved silently.

    ``lam`` is an absolute penalty on an UNNORMALIZED Gram, and nothing upstream
    bounds the factor scale. Far enough above the penalty ``fl(d_ii + lam)``
    equals ``d_ii``, so a registered positive lambda is applied as something
    other than itself.
    """
    rng = np.random.default_rng(4)
    Z, _, pairs, eps = _make(rng)
    with pytest.raises(SingularDesignError, match="not representable against"):
        identify_operator(Z * 1e4, pairs, eps, lam=1e-3)


def test_the_rejected_ridge_really_is_byte_identical_to_the_unregularized_gram():
    """Pin the premise, not just the behaviour, of the guard above.

    If a future change made the pathological input representable again, this
    test fails rather than leaving a guard that can no longer detect anything.
    """
    rng = np.random.default_rng(4)
    Z, _, pairs, _ = _make(rng)
    phi = design_matrix(Z * 1e4, pairs)
    base = phi.T @ phi
    gram = base + 1e-3 * np.eye(phi.shape[1])
    assert np.array_equal(gram, base)


def test_one_over_scaled_factor_block_is_rejected_though_others_keep_the_penalty():
    """Pin ANY-coordinate rejection, which an all-coordinates rule cannot do.

    ``z`` concatenates an expression block and an ESM block (registered
    ``esm_projection_dim: 2``). Over-scaling one block loses the penalty only on
    the basis elements that involve it, so a rule keyed on "every coordinate
    lost" can never fire on a block imbalance — the one input whose scale
    nothing upstream bounds.
    """
    rng = np.random.default_rng(6)
    Z, _, pairs, eps = _make(rng)
    Z_block = Z.copy()
    Z_block[:, 2:] *= 1e6  # ESM block only

    phi = design_matrix(Z_block, pairs)
    base = phi.T @ phi
    kept = int(np.sum(np.diag(base + 1e-3 * np.eye(phi.shape[1])) != np.diag(base)))
    # premise: an all-coordinates rule would NOT fire here
    assert 0 < kept < phi.shape[1]

    with pytest.raises(SingularDesignError, match="not representable against"):
        identify_operator(Z_block, pairs, eps, lam=1e-3)


def test_a_single_lost_coordinate_is_enough_to_reject():
    """Pin the boundary of ANY: one lost coordinate out of ten must reject.

    This is the case the guard exists for and the one a weakened rule would slip
    through — a quorum rule, ``n_lost > 1``, or skipping index 0 all still reject
    the seven-lost block case, so only a single-coordinate loss pins the actual
    criterion. It is also what the reachable end-to-end path produces: over-scale
    one factor coordinate and the full calibration design loses exactly the basis
    element built from it.
    """
    rng = np.random.default_rng(4)
    Z, _, pairs, eps = _make(rng)
    Z_one = Z.copy()
    Z_one[:, 0] *= 1e3

    phi = design_matrix(Z_one, pairs)
    base = phi.T @ phi
    lost = np.flatnonzero(np.diag(base + 1e-3 * np.eye(phi.shape[1])) == np.diag(base))
    # premise: exactly one coordinate, and it is index 0
    assert lost.tolist() == [0]

    with pytest.raises(SingularDesignError, match="on 1 of 10 coordinates"):
        identify_operator(Z_one, pairs, eps, lam=1e-3)


def _single_loss_at(index: int, k: int = 4, scale: float = 1e4):
    """Build a design losing the penalty on exactly the sym-basis ``index``.

    A pair whose two genes load only coordinates ``i`` and ``j`` contributes to
    the ``(i, j)`` basis element alone, so one dominant such pair puts the whole
    loss there — on the diagonal when ``i == j``, off it otherwise.
    """
    row, col = (int(x[index]) for x in np.triu_indices(k))
    rng = np.random.default_rng(index)
    Z = rng.normal(size=(12, k)) * 0.1
    Z[10] = np.zeros(k)
    Z[11] = np.zeros(k)
    Z[10][row] = scale
    Z[11][col] = scale
    pairs = [(int(a), int(b)) for a, b in rng.integers(0, 10, size=(30, 2)) if a != b]
    pairs += [(10, 11)] * 8
    return Z, pairs, np.zeros((len(pairs), 3)), (row, col)


@pytest.mark.parametrize("index", range(10))
def test_every_sym_basis_coordinate_alone_is_enough_to_reject(index):
    """No coordinate is exempt — not the first, the last, nor any interior one.

    A rule scanning only diagonal basis elements, only one half of the
    coordinates, or skipping any single index would pass a loss located
    elsewhere. Sweeping every index of ``sym_dim`` 10 leaves no such subset rule
    standing, and it covers both diagonal and off-diagonal basis elements.
    """
    Z, pairs, eps, (row, col) = _single_loss_at(index)

    phi = design_matrix(Z, pairs)
    base = phi.T @ phi
    lost = np.flatnonzero(np.diag(base + 1e-3 * np.eye(phi.shape[1])) == np.diag(base))
    assert lost.tolist() == [index]

    with pytest.raises(SingularDesignError, match="on 1 of 10 coordinates"):
        identify_operator(Z, pairs, eps, lam=1e-3)


def test_a_single_loss_rejects_at_the_largest_registered_dimension_too():
    """One lost coordinate of 36 must reject — a lenient quorum would not.

    Every other guard test runs at ``k_total=4`` (``sym_dim`` 10), where a single
    loss is 10% of the coordinates and any lenient fraction still rejects. At the
    registered ``k_total=8`` (``sym_dim`` 36) it is 2.8%, below such a rule — and
    that is the dimension where the OOF train folds are rank-deficient and the
    ridge is load-bearing, so it is the worst place to be lenient.
    """
    rng = np.random.default_rng(9)
    Z = rng.normal(size=(20, 8))
    pairs = [(int(a), int(b)) for a, b in rng.integers(0, 20, size=(40, 2)) if a != b]
    eps = np.zeros((len(pairs), 3))
    Z[:, 0] *= 1e4

    phi = design_matrix(Z, pairs)
    assert phi.shape[1] == sym_basis_dim(8) == 36
    base = phi.T @ phi
    lost = np.flatnonzero(np.diag(base + 1e-3 * np.eye(phi.shape[1])) == np.diag(base))
    assert lost.tolist() == [0]
    # below any quorum lenient enough to differ from ANY at a registered sym_dim
    # (10/21/36); quorums at or below 1/36 are equivalent to ANY throughout
    assert len(lost) / phi.shape[1] < 0.05

    with pytest.raises(SingularDesignError, match="on 1 of 36 coordinates"):
        identify_operator(Z, pairs, eps, lam=1e-3)


def _scaled_to_gram_diagonal(Z, pairs, target):
    """Rescale ``Z`` so the largest Gram diagonal lands near ``target``."""
    achieved = np.diag(design_matrix(Z, pairs).T @ design_matrix(Z, pairs)).max()
    return Z * (target / achieved) ** 0.25


@pytest.mark.parametrize("lam", [0.001, 0.01, 0.1])
def test_the_guard_tracks_representability_and_not_a_magnitude_threshold(lam):
    """Separate exact representability from a ``lam / eps`` magnitude tolerance.

    Loss requires ``lam < ulp(d)/2``, i.e. ``d >= 2**ceil(53 + log2 lam)``, which
    for ``lam=0.001`` is ``2**44 ~ 1.76e13``. A tolerance keyed on ``lam / eps``
    would instead fire from ``~4.5e12``. The band between them is 2.5x-3.9x wide
    across the registered grid and the guard must stay SILENT throughout it —
    that is the difference between an exact-representability check and a
    threshold, and the branch's claim to register no new numerical criterion
    rests on it.

    Run at every registered lambda on purpose: the exact threshold scales with
    ``lam`` while a constant magnitude rule does not, so a single lambda would
    leave that scaling unpinned.
    """
    rng = np.random.default_rng(7)
    Z, _, pairs, eps = _make(rng)
    tolerance_would_fire_from = lam / np.finfo(np.float64).eps
    exact_fires_from = 2.0 ** math.ceil(53 + math.log2(lam))
    assert tolerance_would_fire_from < exact_fires_from

    # inside the band: a lam/eps tolerance fires here, exact representability does not
    inside = _scaled_to_gram_diagonal(
        Z, pairs, (tolerance_would_fire_from * exact_fires_from) ** 0.5
    )
    coef = identify_operator(inside, pairs, eps, lam=lam)
    assert np.all(np.isfinite(coef))

    below = _scaled_to_gram_diagonal(Z, pairs, tolerance_would_fire_from / 100.0)
    coef = identify_operator(below, pairs, eps, lam=lam)
    assert np.all(np.isfinite(coef))

    # silent immediately BELOW the exact threshold and rejecting immediately
    # ABOVE it: together these bracket any wrong-valued magnitude rule to within
    # ~1.5% of the exact one, instead of leaving it a wide window to hide in
    just_below = _scaled_to_gram_diagonal(Z, pairs, exact_fires_from * 0.99)
    assert np.diag(design_matrix(just_below, pairs).T @ design_matrix(just_below, pairs)).max() < (
        exact_fires_from
    )
    coef = identify_operator(just_below, pairs, eps, lam=lam)
    assert np.all(np.isfinite(coef))

    above = _scaled_to_gram_diagonal(Z, pairs, exact_fires_from * 1.005)
    assert np.diag(design_matrix(above, pairs).T @ design_matrix(above, pairs)).max() >= (
        exact_fires_from
    )
    with pytest.raises(SingularDesignError, match="not representable against"):
        identify_operator(above, pairs, eps, lam=lam)

    far_above = _scaled_to_gram_diagonal(Z, pairs, exact_fires_from * 100.0)
    with pytest.raises(SingularDesignError, match="not representable against"):
        identify_operator(far_above, pairs, eps, lam=lam)


@pytest.mark.parametrize("lam", [0.001, 0.01, 0.1])
def test_registered_ridges_survive_every_provably_representable_factor_scale(lam):
    """No registered lambda may be rejected below the representability floor.

    ``d_ii <= n_pairs * max||z||**4`` with constant 1 sharp, and loss needs
    ``d >= 2**ceil(53 + log2 lam)``, so no coordinate can lose ``lam`` until
    ``max||z||`` reaches ``(2**ceil(53 + log2 lam) / n_pairs)**0.25``. Below that
    the guard must stay silent for ANY design of this size, independently of the
    Gram spectrum — which is the property that makes the safety argument
    reproducible without committing a factor bank. Only that FLOOR follows from
    the pair count; where the guard actually fires is spectrum-dependent.

    The expression-block ceiling is covered by this. Factor scores project a
    GENE-CENTERED shift, so that cap is
    ``2 * (1 - 1/n_genes) * max_g ||delta_g||`` — twice the per-gene norm — which
    for ``sqrt(1500) * log1p(1e4)`` and 73 genes is ~704, BELOW the floor at any
    pair count used here. It is not a cap on ``||z||``: the ESM block is bounded
    by nothing in the repository, so no global statement follows from it.
    """
    rng = np.random.default_rng(5)
    Z, _, pairs, eps = _make(rng)
    floor = (2.0 ** math.ceil(53 + math.log2(lam)) / len(pairs)) ** 0.25
    assert floor > 704.0  # the expression-block ceiling is inside the safe region
    Z_safe = Z * (0.5 * floor / np.linalg.norm(Z, axis=1).max())
    coef = identify_operator(Z_safe, pairs, eps, lam=lam)
    assert np.all(np.isfinite(coef))


@pytest.mark.parametrize("lam", [-1.0, np.nan, np.inf])
def test_invalid_regularisation_is_rejected(lam):
    rng = np.random.default_rng(3)
    Z, _, pairs, eps = _make(rng)
    with pytest.raises(ValueError, match="finite and non-negative"):
        identify_operator(Z, pairs, eps, lam=lam)
