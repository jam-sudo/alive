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


# --------------------------------------------------------------------------- #
# The properties below were ALL unpinned in the first version of this file, and
# the mutation harness found them: six mutations survived, including "the final
# fit drops the scale" -- the exact defect this rule's design notes call the one
# that would make selection meaningless. Fourteen tests that read as thorough
# still left the load-bearing sites untested.
# --------------------------------------------------------------------------- #


def _lam_spy(base, sink, name):
    """A factory whose models record the ``lam`` they are actually fitted with.

    Patches the INSTANCE rather than subclassing, deliberately: selection enforces
    ``type(model_factory()) is L1Model`` before reading a singular design as
    hyperparameter non-viability, so a subclass trips a registered guard that is
    doing its job. The instance attribute shadows the class method for the call
    while leaving ``type(obj)`` untouched.
    """

    def _make():
        obj = base()
        original = obj.fit

        def _fit(Z, pairs, eps_obs, *, lam):
            sink[name] = float(lam)
            return original(Z, pairs, eps_obs, lam=lam)

        obj.fit = _fit
        return obj

    return _make


def test_an_infinite_bank_reaches_the_finiteness_refusal():
    """The ``isfinite`` branch is reachable, and by a DIFFERENT input than NaN.

    A NaN bank makes ``np.linalg.svd`` raise ``LinAlgError``; an infinite one lets
    it converge and return ``nan`` for ``sigma_max``. Only the second reaches the
    finiteness check, which is why the NaN test above did not kill the mutation
    that deletes it.
    """
    Z = np.full((6, 4), np.inf)
    pairs = [(0, 1), (2, 3), (4, 5)]
    with pytest.raises(SingularDesignError, match="non-finite sigma_max"):
        calibration_lambda_scale(Z, pairs)


def test_selection_applies_the_scale_and_takes_it_from_the_FULL_roster():
    """Pins the applied penalty itself, not just an invariance of the result.

    An invariance assertion cannot tell a correct scale from any other constant,
    because both sides of the comparison move together -- which is how a mutation
    computing the scale from a one-pair subset survived.
    """
    from alive.compose.models import L1Model

    inst, _ = _scaled(1.0)
    k = inst["selected_k_total"]
    seen: dict[str, float] = {}
    select_hyperparams(
        idx_pairs=inst["idx_pairs"],
        pair_ids=inst["pair_ids"],
        eps_obs=inst["eps_obs"],
        additive=inst["additive"],
        factors_by_k={k: inst["factors_by_k"][k]},
        k_total_grid=[k],
        lambda_grid=[0.01],
        n_genes=inst["n_genes"],
        n_folds=inst["n_folds"],
        seed=inst["seed"],
        model_factory=_lam_spy(L1Model, seen, "oof"),
        uncovered_tolerance=inst["uncovered_tolerance"],
        condition_ceiling=1e300,
    )
    expected = 0.01 * calibration_lambda_scale(inst["factors_by_k"][k], list(inst["idx_pairs"]))
    assert seen["oof"] == expected


def test_the_final_fit_scales_the_headline_operator_and_leaves_the_baseline_alone():
    """Selection and the final fit must apply the SAME interpretation.

    If only one scaled, the recorded ``selected_lambda`` would not be the penalty
    that was scored -- selection would be optimizing a different model than the one
    that ships. Nothing tested this until a mutation deleting the final-fit scaling
    survived the whole suite.

    The baseline arm is asserted too, in the same test: ``id_only``'s feature is
    LINEAR in ``z`` while the operator's is bilinear, so this scale would not make
    it invariant, and scaling it would silently change a registered baseline's fit.
    """
    import dataclasses

    from alive.compose.identify import calibration_lambda_scale as _scale
    from alive.compose.phase2a import run_phase2a_fixture
    from tests.alive.compose.test_phase2a import _HASHES, _build_instance, _inputs, _store

    rng = np.random.default_rng(3)
    inst = _build_instance(rng)
    inp = _inputs(inst)
    seen: dict[str, float] = {}
    factories = {
        name: _lam_spy(factory, seen, name) for name, factory in inp.model_factories.items()
    }
    res = run_phase2a_fixture(
        dataclasses.replace(inp, model_factories=factories), _store(inst), expected_hashes=_HASHES
    )
    assert res.futility_status == "CONTINUE", "the final fit is only reached on CONTINUE"

    selected_lambda = float(res.futility.selected_lambda)
    selected_Z = np.asarray(inp.factors_by_k[res.futility.selected_k_total], dtype=float)
    scale = _scale(selected_Z, list(inp.cal_idx_pairs))
    assert scale != 1.0, "a unit scale would make this test unable to tell the arms apart"

    assert seen["l1_bilinear_identifiable"] == selected_lambda * scale
    assert seen["id_only"] == selected_lambda


def test_the_config_refuses_an_unregistered_scaling_value():
    """A registered string is only registered if a disagreeing config is refused."""
    import yaml

    from alive.compose.config2 import Phase2ConfigError, load_compose_phase2_config

    raw = yaml.safe_load(open("configs/compose_k562_v1_phase2.yaml"))
    raw["identification"]["lambda_scaling"] = "absolute"
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
        yaml.safe_dump(raw, handle)
        path = handle.name
    with pytest.raises(Phase2ConfigError, match="lambda_scaling must match"):
        load_compose_phase2_config(path)
