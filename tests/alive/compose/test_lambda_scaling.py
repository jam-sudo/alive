"""The registered ``lambda_grid`` is RELATIVE (``identification.lambda_scaling``).

Ridge is not scale-invariant and ``Phi`` is bilinear in ``z``, so ``z -> cz`` makes
an absolute penalty act as ``lambda/c^4`` while nothing upstream bounds ``‖z‖``.
Measured before this was registered: at the committed exhibit's own scale the whole
registered grid was nearly inert (weakest filter factors 0.9998/0.998/0.980), and at
``c=100`` it was numerically indistinguishable from ``lambda = 0``, with
``theta(lam=0.001)`` collapsing from ``0.8103`` to ``-3.34e6``. The same absolute
``lambda`` was simultaneously inert on the full design and dominant on a degenerate
fold -- over twenty orders of materiality inside one run.

The applied penalty is ``lambda * sigma_max(Phi_calibration)^2``. ``sigma_max`` is
not a new registered quantity: it is the value the registered
``max_shape_times_float64_eps_times_sigma_max`` rank tolerance is already built from.

SYNTHETIC-ONLY: pure ``numpy`` on committed helpers. No sealed access, no seal.
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.compose.identify import (
    LAMBDA_SCALING_RULE,
    SingularDesignError,
    calibration_lambda_scale,
    rank_diagnostics,
)
from alive.compose.operator import design_matrix
from alive.compose.select import SelectionError, select_hyperparams
from tests.alive.compose.test_condition_ceiling import _fold_local_degeneracy_instance
from tests.alive.compose.test_diagnostics2 import _run

_GRID = (0.001, 0.01, 0.1)


def _scaled(c: float):
    """The committed exhibit with its bank (and outcomes) rescaled by ``c``."""
    inst, folds, _ = _fold_local_degeneracy_instance()
    k = inst["selected_k_total"]
    inst["factors_by_k"] = {k: inst["factors_by_k"][k] * c}
    for key in ("eps_obs", "eps_split_a", "eps_split_b"):
        inst[key] = inst[key] * (c**2)
    return inst, folds


def test_the_registered_rule_is_the_one_the_config_pins():
    from alive.compose.config2 import load_compose_phase2_config

    cfg = load_compose_phase2_config("configs/compose_k562_v1_phase2.yaml")
    assert cfg.lambda_scaling == LAMBDA_SCALING_RULE == "calibration_sigma_max_squared"


def test_the_scale_is_exactly_sigma_max_squared():
    """Pinned against an independent SVD, not against the function's own return."""
    inst, _ = _scaled(1.0)
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k]
    sigma_max = float(np.linalg.svd(design_matrix(Z, inst["idx_pairs"]), compute_uv=False)[0])
    assert calibration_lambda_scale(Z, list(inst["idx_pairs"])) == sigma_max * sigma_max


@pytest.mark.parametrize("c", [0.01, 2.0, 100.0])
def test_the_scale_is_equivariant_so_the_applied_penalty_is_invariant(c):
    """``sigma_max^2`` must move as ``c^4`` -- exactly what cancels ``lambda/c^4``.

    A scale that moved as any other power would leave a residual scale dependence,
    which is the entire defect this rule exists to remove.
    """
    base, _ = _scaled(1.0)
    k = base["selected_k_total"]
    s1 = calibration_lambda_scale(base["factors_by_k"][k], list(base["idx_pairs"]))
    big, _ = _scaled(c)
    sc = calibration_lambda_scale(big["factors_by_k"][k], list(big["idx_pairs"]))
    assert sc / s1 == pytest.approx(c**4, rel=1e-9)


@pytest.mark.parametrize("lam", _GRID)
def test_theta_no_longer_depends_on_the_factor_bank_scale(lam):
    """The defect, and the fix, in one assertion.

    Before the rule, ``theta(lam=0.001)`` moved from ``0.8103`` to ``-3.34e6`` when
    the bank was rescaled by 100 at IDENTICAL ``cond(Phi)``. The two scales must now
    agree to round-off. The tolerance is ``1e-9`` relative, not exact equality: the
    scale is recomputed from a rescaled bank, so the two runs differ by float
    round-off in the scalar, not by construction.
    """
    small, _ = _scaled(1.0)
    large, _ = _scaled(100.0)
    t_small = _run(small, condition_ceiling=1e300, lambda_grid=(lam,)).oof_theta
    t_large = _run(large, condition_ceiling=1e300, lambda_grid=(lam,)).oof_theta
    assert t_small == pytest.approx(t_large, rel=1e-9)


def test_the_scale_does_not_touch_cond_or_rank():
    """The registered ceiling and rank rule must keep their exact meaning.

    They are defined on the design's geometry, which a penalty cannot move. Pinned
    because the alternative fix -- rescaling the bank -- WOULD have been able to move
    them if it had been applied per column instead of as one global scalar.
    """
    small, _ = _scaled(1.0)
    large, _ = _scaled(100.0)
    k = small["selected_k_total"]
    a = rank_diagnostics(small["factors_by_k"][k], list(small["idx_pairs"]))
    b = rank_diagnostics(large["factors_by_k"][k], list(large["idx_pairs"]))
    assert a.rank == b.rank and a.sym_dim == b.sym_dim
    assert float(a.condition_number) == pytest.approx(float(b.condition_number), rel=1e-9)


def test_lambda_zero_stays_exactly_zero_under_any_scale():
    """``lam == 0.0`` must remain the unregularized branch.

    The registered rank policy and the conditioning ceiling both key on
    ``float(lam) == 0.0``. If the scaling could make a zero penalty non-zero -- or a
    non-zero penalty zero -- those two guards would silently change which candidates
    they screen.
    """
    inst, _ = _scaled(1.0)
    k = inst["selected_k_total"]
    scale = calibration_lambda_scale(inst["factors_by_k"][k], list(inst["idx_pairs"]))
    assert scale > 0.0
    assert 0.0 * scale == 0.0
    for lam in _GRID:
        assert lam * scale != 0.0


def test_a_zero_bank_scores_rather_than_aborting_selection():
    """``sigma_max == 0`` iff ``Phi`` is identically zero, where ``beta = 0`` always.

    Returning ``1.0`` there is not a fail-open: no scale can change a prediction on
    an identically-zero design, and refusing would abort a selection the registered
    rank policy already handles. Pinned because the first implementation raised here
    and broke two registered behaviours.
    """
    Z = np.zeros((6, 4))
    pairs = [(0, 1), (2, 3), (4, 5)]
    assert calibration_lambda_scale(Z, pairs) == 1.0


def test_a_non_finite_design_is_refused_not_coerced():
    Z = np.full((6, 4), np.nan)
    pairs = [(0, 1), (2, 3), (4, 5)]
    # numpy raises LinAlgError before any finite check can run, and LinAlgError is
    # a bare ValueError subclass -- typing it is the point of this assertion.
    with pytest.raises(SingularDesignError, match="SVD failed"):
        calibration_lambda_scale(Z, pairs)
    with pytest.raises(SingularDesignError, match="empty"):
        calibration_lambda_scale(np.zeros((6, 4)), [])


def test_selection_refuses_an_unregistered_scaling_rule():
    """The rule is registered, so a disagreeing caller must fail closed."""
    inst, _ = _scaled(1.0)
    with pytest.raises(SelectionError, match="lambda_scaling must match"):
        select_hyperparams(
            idx_pairs=inst["idx_pairs"],
            pair_ids=inst["pair_ids"],
            eps_obs=inst["eps_obs"],
            additive=inst["additive"],
            factors_by_k=inst["factors_by_k"],
            k_total_grid=inst["k_total_grid"],
            lambda_grid=inst["lambda_grid"],
            n_genes=inst["n_genes"],
            n_folds=inst["n_folds"],
            seed=inst["seed"],
            model_factory=inst["model_factory"],
            uncovered_tolerance=inst["uncovered_tolerance"],
            condition_ceiling=1e300,
            lambda_scaling="absolute",
        )


def test_the_scale_comes_from_the_calibration_design_not_a_fold():
    """One scale per ``k_total``, shared by every fold.

    A per-fold scale would regularize each fold relative to its own spectrum and
    make their thetas incommensurable -- and on this exhibit the degenerate fold's
    scale differs from the calibration design's, so the two are distinguishable.
    """
    inst, folds = _scaled(1.0)
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k]
    cal = calibration_lambda_scale(Z, list(inst["idx_pairs"]))
    fold0 = calibration_lambda_scale(Z, [inst["idx_pairs"][i] for i in folds[0].train_idx])
    assert cal != fold0
