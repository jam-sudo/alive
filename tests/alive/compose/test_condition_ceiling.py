"""The registered conditioning ceiling on the calibration design matrix Phi.

The 2026-07-29 representability guard was removed with the ridge normal equations
(commit ``04d74ca``). That guard was the only thing in the pipeline that ever
fired on **block-scale imbalance** between the expression block of ``z`` and the
ESM block — and it fired by accident, as a side effect of a penalty-loss check.
Nothing replaced it, and nothing upstream bounds the two blocks' relative scale.

This file pins the replacement: a registered ceiling on ``cond(Phi)``, applied as
an **admissibility screen inside selection** — the same shape as the sibling
``unregularized_oof_rank_policy``. An over-ceiling candidate is recorded in
``nonviable_candidates`` with its reason and selection proceeds among the rest;
only when EVERY candidate is inadmissible does selection itself become invalid
(``SelectionError``, a contracted pre-seal rejection, exit 10, runbook category D
"investigate, do not re-run").

The screen has TWO arms, and they remove different amounts:

* the **candidate** arm bounds the full calibration design, so it removes a
  ``k_total`` at every lambda;
* the **fold** arm (2026-08-07) bounds each unregularized OOF TRAIN design, so it
  removes that ``k_total``'s ``lam=0.0`` candidate alone. It exists because a
  degeneracy confined to one gene-disjoint group is invisible to the first arm:
  ``_fold_local_degeneracy_instance`` measures a full design at ``cond 6.47`` with a
  FULL-RANK train fold at ``3.03e12``. It is restricted to ``lam == 0.0`` because
  that is the only place ``cond(Phi)`` IS the conditioning of the solve; at
  ``lam > 0`` the ridge filter factors bound it.

On typical (noisy) data neither arm changes the WINNER: conditioning bounds noise
AMPLIFICATION, so a degenerate fold inflates held-out error, lowers theta, and
selection takes the max. What the arms change is the recorded REASON — without them
a numerical failure is filed as ``dev_oof_delta_below_threshold``, a claim about the
biology.

That is a CONDITIONAL claim and an earlier version of this file stated it
unconditionally, while its own fixture falsified it. With zero noise there is
nothing to amplify, an ill-conditioned but consistent ``lstsq`` is exact, and the
over-ceiling ``lam=0`` candidate wins at ``theta = 0.9999999993`` — so the screen
DOES move the winner there. Two independent reviews found it. The condition and its
boundary are now pinned in
:func:`test_the_winner_claim_is_conditional_on_noise_and_the_boundary_is_pinned`.

One further scope limit, also from review: ``cond`` is invariant to a uniform
rescale of ``z`` while the registered ``lambda_grid`` is ABSOLUTE, so how much
protection ``lam > 0`` actually provides depends on a factor-bank scale that no
config field bounds. Recorded as a limitation in the readiness index, not closed
here.

The first implementation enforced it on the WINNER as a futility condition. Three
independent reviews (2026-08-04) showed that was wrong on both axes:

* it terminated the study permanently whenever the best-scoring dimension was
  over the ceiling, even when the same registered grid held an admissible one;
* the justification for futility did not survive checking — the runbook does not
  say exit 10 means "fix and retry" (category D says the opposite), the durable
  futility report does not persist the spectrum it was said to preserve, and the
  registered futility vocabulary was never extended while the sibling threshold
  in the same config block (``uncovered_tolerance``) is a ``SelectionError``.

Two things the screen deliberately does NOT do. It never fires on a non-finite
condition number: that is the rank-deficient case (and, at ``k_total == 0``, a
zero-width bank that reports full rank), which the registered rank policy owns, and
screening it here would make that gate unreachable. And it does not police uniform
factor magnitude — the statistic is invariant to a uniform rescale of ``z`` (to
round-off), so uniform-scale penalty immateriality is recorded separately and is
not closed by this.

SYNTHETIC-ONLY: pure ``numpy`` except the forwarding test, which drives the
``phase2a`` fixture path (and so builds a DEVELOPMENT outcome store). No sealed
access, no seal, in any test here.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import yaml

from alive.compose.config2 import (
    _EXPECTED_CONDITION_CEILING,
    Phase2ConfigError,
    load_compose_phase2_config,
)
from alive.compose.gates import LeakageError
from alive.compose.identify import SingularDesignError, rank_diagnostics
from alive.compose.models import L1Model
from alive.compose.operator import bilinear_predict, sym_basis_dim
from alive.compose.phi_rank import (
    PHI_RANK_ACTIVATION_SCHEMA,
    validate_phi_rank_activation_report,
)
from alive.compose.select import (
    CEILING_REASON_PREFIX,
    FOLD_CEILING_MARKER,
    FoldConditioningError,
    SelectionError,
    _screen_unregularized_folds,
    build_gene_disjoint_folds,
)
from tests.alive.compose.test_config2 import CANON, _raw, _write
from tests.alive.compose.test_diagnostics2 import _full_rank_instance, _run, _sym_to_vec

# The registered value, restated here so a silent config edit breaks THIS file's
# margin claims rather than passing unnoticed. Bound to config2 by the first test.
_REGISTERED_CEILING = 1.0e8

_REAL_PHI_REPORT = Path("docs/activation-evidence/compose/real_norman_phi_rank_report.json")

_CEILING_MARKER = "conditioning above the registered ceiling"
_FOLD_MARKER = "OOF train fold"


# --------------------------------------------------------------------------- #
# the registered value, and the margins it was chosen for
# --------------------------------------------------------------------------- #
def test_the_ceiling_under_test_is_the_one_the_committed_config_registers():
    cfg = load_compose_phase2_config(CANON)
    assert cfg.condition_ceiling == _REGISTERED_CEILING
    assert _EXPECTED_CONDITION_CEILING == _REGISTERED_CEILING
    # The anchor is data-free: 1/sqrt(float64 eps) is where half the significant
    # digits are gone. The ceiling sits above it, so it never rejects a design
    # float64 can still resolve.
    assert _REGISTERED_CEILING > 1.0 / np.sqrt(np.finfo(np.float64).eps)


def test_the_block_imbalance_exhibit_clears_the_ceiling_by_orders_of_magnitude():
    """The exhibit from the guard that ``04d74ca`` deleted, re-measured here.

    Same construction as the removed ``test_one_over_scaled_factor_block_is_
    rejected_though_others_keep_the_penalty``: seed 6, k=4, the last two columns
    (registered ``esm_projection_dim: 2``) scaled by 1e6.

    The numbers this reproduces are the ones the readiness index and the spec
    register, so the construction has to be byte-faithful. A first version of this
    test dropped ``_make``'s ``coef_true`` draw as unused — it IS unused, but it
    advances the RNG, so the pair set changed (37 pairs to 39) and the exhibit
    silently became ``9.91 -> 4.15e12`` while the documents kept quoting
    ``10.42 -> 3.71e12``. Two independent reviews caught it. The draw stays.
    """
    rng = np.random.default_rng(6)
    n_genes, k, p = 20, 4, 3
    Z = rng.normal(size=(n_genes, k))
    rng.normal(size=(p, sym_basis_dim(k)))  # `_make`'s coef_true: consumed, not used
    pairs = [(int(a), int(b)) for a, b in rng.integers(0, n_genes, size=(40, 2)) if a != b]

    baseline = rank_diagnostics(Z, pairs).condition_number
    uniform = rank_diagnostics(Z * 1e6, pairs).condition_number
    Z_block = Z.copy()
    Z_block[:, 2:] *= 1e6
    imbalanced = rank_diagnostics(Z_block, pairs).condition_number

    # the design is FULL RANK in every case -- this is not a rank test
    assert rank_diagnostics(Z_block, pairs).is_full_rank
    assert uniform == pytest.approx(baseline, rel=1e-9)

    # The values the spec and the readiness index register, each pinned at the
    # precision it actually HAS. The two well-conditioned numbers are reproducible
    # to the last bit; the imbalanced one is not, and asserting that it was is the
    # defect this comment exists to stop recurring.
    #
    # A first version pinned all three at rel=1e-12. That is green on macOS
    # (Accelerate) and RED on Linux x86_64 (OpenBLAS): 3713365971178.1865 against
    # 3713121910859.7812, a relative difference of 6.6e-05. The arithmetic says it
    # must be: cond ~= 3.7e12 destroys 12.6 of float64's 15.65 significant
    # decimal digits, so ~3 remain, and a 12-digit pin asserts nine digits the
    # number does not carry. `rel=1e-3` asserts exactly the 3 figures it does,
    # with 15x headroom over the observed cross-BLAS spread.
    assert len(pairs) == 37
    assert baseline == pytest.approx(10.421787979549746, rel=1e-12)
    assert uniform == pytest.approx(10.421787979549734, rel=1e-12)
    assert imbalanced == pytest.approx(3.713e12, rel=1e-3)

    assert baseline < _REGISTERED_CEILING
    assert imbalanced > _REGISTERED_CEILING
    # both margins exceed four orders of magnitude, which is why the exact value
    # of the ceiling is not load-bearing between them
    assert np.log10(_REGISTERED_CEILING / baseline) > 4.0
    assert np.log10(imbalanced / _REGISTERED_CEILING) > 4.0


def test_a_uniform_rescale_leaves_the_statistic_where_it_was():
    """The property that makes this a block-imbalance detector, not a size limit.

    NOT exact equality: the two SVDs differ in the last couple of ulps, so an
    ``==`` assertion here would be a lie that happens to pass on one machine.
    """
    rng = np.random.default_rng(6)
    Z = rng.normal(size=(20, 4))
    pairs = [(int(a), int(b)) for a, b in rng.integers(0, 20, size=(40, 2)) if a != b]

    baseline = rank_diagnostics(Z, pairs).condition_number
    for scale in (1e-6, 1e3, 1e6):
        assert rank_diagnostics(Z * scale, pairs).condition_number == pytest.approx(
            baseline, rel=1e-9
        )


def test_the_recorded_real_designs_clear_the_registered_ceiling():
    """The registered ceiling must not trivially reject our own study.

    Read from the evidence file rather than transcribed, so a regenerated report
    is re-checked automatically instead of being compared against numbers frozen
    in a test. That report is bound to an EARLIER config digest (this branch moves
    it); the condition numbers are properties of the data and factor banks, and are
    used here only as an order-of-magnitude margin check, not as a live binding.
    """
    report = json.loads(_REAL_PHI_REPORT.read_text(encoding="utf-8"))
    per_k = report["report"]["per_k_total"]
    assert per_k, "the phi rank report records no dimension"
    for entry in per_k:
        cond = float(entry["condition_number"])
        assert np.isfinite(cond)
        assert cond < _REGISTERED_CEILING, (
            f"k_total={entry['k_total']} records cond={cond}, at or above the "
            "registered ceiling: the real study would futility-stop on conditioning"
        )
        assert np.log10(_REGISTERED_CEILING / cond) > 5.0


# --------------------------------------------------------------------------- #
# the screen, inside selection
# --------------------------------------------------------------------------- #
def _nonviable_reasons(result) -> list[str]:
    return [r for _, _, r in result.nonviable_candidates if r.startswith(_CEILING_MARKER)]


def _candidate_arm(result) -> list[str]:
    """Reasons from the arm that screens the FULL design, over every lambda."""
    return [r for r in _nonviable_reasons(result) if _FOLD_MARKER not in r]


def _fold_arm(result) -> list[str]:
    """Reasons from the arm that screens one unregularized TRAIN fold."""
    return [r for r in _nonviable_reasons(result) if _FOLD_MARKER in r]


def test_a_well_conditioned_design_continues_and_screens_nothing():
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert res.status == "CONTINUE"
    assert res.rank_report.condition_number < _REGISTERED_CEILING
    assert not _nonviable_reasons(res)


def test_an_over_ceiling_dimension_is_dropped_and_an_admissible_one_is_selected():
    """The finding this design exists to answer.

    Enforcing the ceiling on the WINNER meant a single over-ceiling ``k_total``
    permanently terminated the study — count 0, no re-run — even when the same
    registered grid held an admissible alternative. Screened per candidate, the
    bad dimension is recorded with its reason and selection moves on.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng, k=4)
    Z4 = inst["factors_by_k"][4]
    Z6 = np.hstack([Z4, rng.normal(size=(Z4.shape[0], 2)) * 1e6])  # imbalanced block

    inst["factors_by_k"] = {4: Z4, 6: Z6}
    inst["k_total_grid"] = [4, 6]

    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert rank_diagnostics(Z6, inst["idx_pairs"]).condition_number > _REGISTERED_CEILING
    assert res.status == "CONTINUE", "an admissible dimension existed; the run must not die"
    assert res.selected_k_total == 4
    dropped = [(k, lam) for k, lam, r in res.nonviable_candidates if r.startswith(_CEILING_MARKER)]
    assert {k for k, _ in dropped} == {6}, "every lambda at the bad k_total is dropped"
    assert len(dropped) == len(inst["lambda_grid"])
    assert not res.failures


def _signal_only_at_the_over_ceiling_dimension(seed: int):
    """A grid where the OVER-CEILING dimension is the one that wins.

    The case the reversal was made for, and the case no test covered: `k=6` is
    block-imbalanced AND carries the signal, `k=4` is well conditioned and cannot
    express it. Two reviews independently observed that the existing test's `k=4`
    wins with or without the screen, so it demonstrates nothing about the outcome.
    """
    rng = np.random.default_rng(seed)
    inst = _full_rank_instance(rng, k=4)
    Z4 = inst["factors_by_k"][4]
    Z6 = np.hstack([Z4, rng.normal(size=(Z4.shape[0], 2)) * 1e6])
    p = inst["eps_obs"].shape[1]
    B = rng.normal(size=(p, 6, 6))
    B = 0.5 * (B + np.transpose(B, (0, 2, 1)))
    coef = np.vstack([_sym_to_vec(B[m]) for m in range(p)])
    eps = np.vstack([bilinear_predict(coef, Z6[g], Z6[h]) for g, h in inst["idx_pairs"]])
    inst["eps_obs"] = eps
    inst["eps_split_a"] = eps
    inst["eps_split_b"] = eps
    inst["factors_by_k"] = {4: Z4, 6: Z6}
    inst["k_total_grid"] = [4, 6]
    return inst


def test_screening_the_winning_dimension_stops_the_run_and_says_so():
    """A stop caused by the screen must not read as a claim about the biology.

    With `k=6` screened, the surviving `k=4` fails the OOF theta gate — whose
    registered condition is `dev_oof_delta_below_threshold`, i.e. "the GI signal is
    not learnable at the registered dimensions". That is a statement about the
    BIOLOGY, and here the cause was numerical: the dimension that could express the
    signal was inadmissible. The ceiling reason lived only in
    `nonviable_candidates`, unlinked to the failure, so a reader of
    `futility_status` + `failures` recorded a scientific negative for an
    engineering defect (`CLAUDE.md#invariants` 12/14/18).
    """
    inst = _signal_only_at_the_over_ceiling_dimension(0)
    unscreened = _run(inst, condition_ceiling=1e300)
    screened = _run(inst, condition_ceiling=_REGISTERED_CEILING)

    # the premise: without the screen this run CONTINUEs on the over-ceiling k
    assert unscreened.status == "CONTINUE"
    assert unscreened.selected_k_total == 6
    assert rank_diagnostics(inst["factors_by_k"][6], inst["idx_pairs"]).condition_number > (
        _REGISTERED_CEILING
    )

    # with the screen the run stops -- honest, because the only admissible
    # dimension cannot express the signal -- but it must SAY the screen ran
    assert screened.status == "FUTILITY_STOPPED"
    assert screened.selected_k_total == 4
    assert any("OOF primary theta" in f for f in screened.failures)
    context = [f for f in screened.failures if f.startswith("context, not an independent failure")]
    assert len(context) == 1, "a screened stop must name the screen in `failures`"
    # Candidates, not dimensions: the two arms remove different amounts, and the
    # line must not inflate a lam=0.0-only removal into a whole screened k_total.
    assert "(6, 0.0)" in context[0]
    assert "(4," not in context[0], "the surviving dimension is not a screened one"
    assert _nonviable_reasons(screened), "and the per-candidate reasons are still recorded"


def test_no_screening_context_line_is_added_when_the_screen_did_not_run():
    """The context line is evidence, not decoration: absent when nothing was screened."""
    rng = np.random.default_rng(2)
    inst = _full_rank_instance(rng)
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k]
    v = rng.normal(size=Z.shape[1])
    inst["factors_by_k"] = {k: np.outer(rng.normal(size=Z.shape[0]), v)}
    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert res.status == "FUTILITY_STOPPED"
    assert not any(f.startswith("context, not an independent failure") for f in res.failures)


def test_when_every_dimension_is_inadmissible_selection_itself_is_invalid():
    """All candidates screened out is a REJECTION, not a futility verdict.

    ``SelectionError`` is already rostered as a contracted pre-seal rejection
    (exit 10) and already sits in the runbook's category D — "scientifically
    invalid, investigate rather than re-run" — which is the instruction this
    situation needs. No new exception class and no new futility condition.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k].copy()
    Z[:, 2:] *= 1e6  # ESM block only
    inst["factors_by_k"] = {k: Z}

    assert rank_diagnostics(Z, inst["idx_pairs"]).is_full_rank, "conditioning, not rank"
    with pytest.raises(SelectionError) as excinfo:
        _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert "no viable hyperparameter candidate" in str(excinfo.value)
    assert _CEILING_MARKER in str(excinfo.value), "the reason must reach the operator"


def test_the_screen_never_swallows_rank_deficiency():
    """The trap in moving the ceiling into selection.

    ``rank_diagnostics`` returns ``inf`` exactly for a rank-deficient design, and
    ``inf > ceiling`` is True. A screen that fired on it would drop every
    rank-deficient dimension as merely "non-viable" — selection would quietly move
    to a full-rank one and the run would CONTINUE, making the registered rank
    futility gate unreachable. The screen is restricted to FINITE condition
    numbers so rank deficiency still stops the run.
    """
    rng = np.random.default_rng(2)
    inst = _full_rank_instance(rng)
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k]
    v = rng.normal(size=Z.shape[1])
    inst["factors_by_k"] = {k: np.outer(rng.normal(size=Z.shape[0]), v)}

    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert not np.isfinite(res.rank_report.condition_number)
    assert res.status == "FUTILITY_STOPPED"
    assert any("rank" in f.lower() for f in res.failures)
    assert not _nonviable_reasons(res), "rank deficiency is the rank gate's, not the screen's"


def test_the_bound_is_inclusive_and_the_comparison_is_one_ulp_sharp():
    """The registered wording is "at or below", so the comparison is ``>``.

    Found by mutation: flipping ``>`` to ``>=`` changed nothing, because no test
    went near the boundary. A design whose condition number is exactly ``1.0e8``
    cannot be constructed, so the ceiling is moved onto the measured value
    instead — the same comparison, from the other side.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    measured = rank_diagnostics(
        inst["factors_by_k"][inst["selected_k_total"]], inst["idx_pairs"]
    ).condition_number

    at_the_bound = _run(inst, condition_ceiling=measured)
    assert at_the_bound.status == "CONTINUE", "the bound is inclusive"
    assert not _candidate_arm(at_the_bound)
    # The FOLD arm does fire at this ceiling, and must. A fold drops every pair
    # touching its held-out genes, so a train fold's design is strictly smaller
    # than the full design and generally worse conditioned; setting the ceiling
    # exactly at the FULL design's number therefore puts the folds above it. That
    # is the gap the fold arm exists to close, so it is asserted here rather than
    # filtered away silently.
    assert _fold_arm(at_the_bound)

    with pytest.raises(SelectionError, match=_CEILING_MARKER):
        _run(inst, condition_ceiling=float(np.nextafter(measured, 0.0)))


# --------------------------------------------------------------------------- #
# the second arm: the unregularized OOF TRAIN fold
# --------------------------------------------------------------------------- #
def _fold_local_degeneracy_instance(seed: int = 0, *, tiny: float = 1e-6, noise: float = 1e-2):
    """Full design comfortably under the ceiling; one TRAIN fold far above it.

    A gene-disjoint fold drops every pair touching its held-out genes, so a
    degeneracy confined to those genes is invisible to a statistic computed over
    the whole calibration roster. Confining the last factor's magnitude to fold
    0's held-out genes builds exactly that: pairs touching a carrier still probe
    the factor (the full design stays conditioned), fold 0's train pairs barely do.

    ``noise`` is RELATIVE to ``std(eps)`` and is not decoration. A first version of
    this helper regenerated ``eps_obs`` exactly and noiselessly from the degenerate
    ``Z``, which made the exhibit demonstrate the OPPOSITE of the claim it was cited
    for: ``cond(Phi)`` bounds noise AMPLIFICATION, so with nothing to amplify an
    ill-conditioned but consistent ``lstsq`` is exact, the over-ceiling ``lam=0``
    candidate scored ``theta = 0.9999999993`` and WON, and the screen changed the
    winner. Two independent reviews caught it. The noiseless case is not hidden —
    it is pinned as the boundary in
    :func:`test_the_winner_claim_is_conditional_on_noise_and_the_boundary_is_pinned`.
    """
    rng = np.random.default_rng(seed)
    inst = _full_rank_instance(rng)
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k].copy()
    folds = build_gene_disjoint_folds(
        inst["idx_pairs"],
        n_genes=inst["n_genes"],
        n_folds=inst["n_folds"],
        seed=inst["seed"],
    )
    carriers = tuple(sorted(folds[0].held_out_genes))
    for g in range(inst["n_genes"]):
        if g not in carriers:
            Z[g, -1] *= tiny
    inst["factors_by_k"] = {k: Z}

    # Regenerate the outcomes FROM the design under test. Reusing the outcomes
    # built from the unmodified Z would confound a conditioning assertion with a
    # representation mismatch, and every claim below would be about the wrong
    # thing.
    p = inst["eps_obs"].shape[1]
    B = rng.normal(size=(p, k, k))
    B = 0.5 * (B + np.transpose(B, (0, 2, 1)))
    coef = np.vstack([_sym_to_vec(B[m]) for m in range(p)])
    eps = np.vstack([bilinear_predict(coef, Z[g], Z[h]) for g, h in inst["idx_pairs"]])
    scale = float(np.std(eps))
    inst["eps_obs"] = eps + noise * scale * rng.normal(size=eps.shape)
    # The split halves are drawn from the CLEAN signal on purpose. Deriving them
    # from the noisy `eps_obs` gives both halves the SAME noise realization, and
    # `measurability_gate` is a split-half correlation -- it would then score the
    # injected noise as reproducible GI signal and could not fail. Nothing flipped
    # at the default level, but the gate would have stopped carrying information in
    # the one file whose central claim is about noise.
    inst["eps_split_a"] = eps + 0.02 * rng.normal(size=eps.shape)
    inst["eps_split_b"] = eps + 0.02 * rng.normal(size=eps.shape)
    return inst, folds, carriers


def _fold_conditions(inst, folds) -> list:
    Z = inst["factors_by_k"][inst["selected_k_total"]]
    return [rank_diagnostics(Z, [inst["idx_pairs"][i] for i in f.train_idx]) for f in folds]


def test_the_reason_markers_under_test_are_the_ones_selection_writes():
    """Restated literals above are drift detectors only if they are bound here."""
    assert _CEILING_MARKER == CEILING_REASON_PREFIX
    assert _FOLD_MARKER == FOLD_CEILING_MARKER
    assert _FOLD_MARKER not in _CEILING_MARKER, "the arms must stay distinguishable"


def test_a_fold_screen_escape_would_still_be_a_contracted_pre_seal_rejection():
    """The subclass choice, pinned instead of only asserted in a comment.

    ``select_hyperparams`` catches every ``FoldConditioningError`` on today's only
    call path, so this is unreachable — which is why it is worth pinning. A
    fail-safe nobody exercises is invisible until the day it is needed, and an
    escape landing outside the roster would exit 1 (uncontracted bug) instead of
    10 (registered pre-seal rejection).
    """
    from alive.compose.driver.cli import _KNOWN_PRESEAL_REJECTIONS

    assert issubclass(FoldConditioningError, SelectionError)
    assert isinstance(FoldConditioningError("x"), _KNOWN_PRESEAL_REJECTIONS)


def test_a_fold_local_degeneracy_is_invisible_to_every_other_guard():
    """The gap the fold arm exists to close, measured rather than asserted.

    Both guards that ran before it report the design healthy: the candidate-level
    screen sees the FULL roster, and the registered unregularized rank policy
    reads only ``is_full_rank``.
    """
    inst, folds, carriers = _fold_local_degeneracy_instance()
    Z = inst["factors_by_k"][inst["selected_k_total"]]
    full = rank_diagnostics(Z, inst["idx_pairs"])
    per_fold = _fold_conditions(inst, folds)

    assert len(carriers) >= 2, "fold 0 must hold out enough genes to carry the factor"
    assert full.is_full_rank and full.condition_number < _REGISTERED_CEILING
    assert all(r.is_full_rank for r in per_fold), "conditioning, not rank"

    worst = max(r.condition_number for r in per_fold)
    assert worst > _REGISTERED_CEILING
    # order-of-magnitude claim only: cond at this scale carries ~3 significant
    # figures, so no tighter pin would be honest (see the exhibit test above).
    assert np.log10(worst / full.condition_number) > 8.0


def test_the_fold_arm_removes_the_unregularized_candidate_and_nothing_else():
    """It fires where cond IS the conditioning of the solve, and only there.

    At ``lam == 0.0`` ``identify_operator`` takes the ``lstsq`` branch, so nothing
    bounds the amplification. At ``lam > 0`` the ridge filter factors do, and the
    UNREGULARIZED number is no longer the right statistic to reject on.
    """
    inst, _, _ = _fold_local_degeneracy_instance()
    assert 0.0 in inst["lambda_grid"] and any(x > 0.0 for x in inst["lambda_grid"])

    unscreened = _run(inst, condition_ceiling=1e300)
    # Stronger than `_nonviable_reasons`, which filters on the CEILING prefix and so
    # cannot see a rank-policy removal -- exactly the "something else" this premise
    # claims to rule out.
    assert not unscreened.nonviable_candidates, "the premise: nothing else removes it"

    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert not _candidate_arm(res), "the full design was admissible"
    assert _fold_arm(res)
    screened = {(k, lam) for k, lam, r in res.nonviable_candidates if _FOLD_MARKER in r}
    assert {lam for _, lam in screened} == {0.0}
    assert res.status == "CONTINUE", "an admissible candidate remained in the grid"
    assert res.selected_lambda > 0.0
    # The claim the module docstring makes, pinned on the exhibit that is cited for
    # it. This assertion is the one whose absence let the claim stand while the
    # fixture falsified it: the screened candidate must ALREADY have lost.
    assert unscreened.selected_lambda > 0.0, "the over-ceiling candidate must not win"
    assert unscreened.selected_lambda == res.selected_lambda
    assert res.oof_theta == pytest.approx(unscreened.oof_theta, rel=1e-12)


def test_the_winner_claim_is_conditional_on_noise_and_the_boundary_is_pinned():
    """The scope of "conditioning damage cannot change the winner".

    ``cond(Phi)`` bounds noise AMPLIFICATION. With NO noise there is nothing to
    amplify: an ill-conditioned but consistent unregularized solve is exact, the
    over-ceiling candidate scores ~1.0, wins, and the screen DOES move the winner.
    The claim is therefore conditional, and this test states the condition rather
    than leaving a reader to trust an unscoped sentence.

    Both reviews found this by running the fixture; it is pinned here so the scope
    cannot be quietly widened again.
    """
    noiseless, _, _ = _fold_local_degeneracy_instance(noise=0.0)
    u = _run(noiseless, condition_ceiling=1e300)
    s = _run(noiseless, condition_ceiling=_REGISTERED_CEILING)
    assert u.selected_lambda == 0.0, "noiseless: the over-ceiling candidate wins"
    # `1 - theta` is ~6.7e-10 out of a cond-3.03e12 solve, so it carries nowhere
    # near seven digits. A first version asserted `approx(1.0, abs=1e-6)`; the map
    # from data perturbation is QUADRATIC (`1-theta ~ 6.7e21 * delta^2`), so that
    # tolerance is crossed at ~55 ulps -- the same over-precise shape as the
    # `rel=1e-12` pin that went red on Linux. `< 1e-3` is equally discriminating:
    # the alternative candidate scores 0.8101.
    assert 1.0 - u.oof_theta < 1e-3, "and it recovers the operator"
    assert s.selected_lambda > 0.0, "so the screen DOES change the winner here"
    assert s.oof_theta < u.oof_theta

    # The BOUNDARY, measured rather than gestured at. An earlier version probed
    # 1e-6 and 1e-2 and called that "pinned"; both sit 5-9 orders ABOVE the flip
    # point, deep in the same regime, so the test's own name was false.
    below, _, _ = _fold_local_degeneracy_instance(noise=5e-12)
    above, _, _ = _fold_local_degeneracy_instance(noise=7e-12)
    assert _run(below, condition_ceiling=1e300).selected_lambda == 0.0
    assert _run(above, condition_ceiling=1e300).selected_lambda > 0.0

    default, _, _ = _fold_local_degeneracy_instance()
    assert _run(default, condition_ceiling=1e300).selected_lambda > 0.0


def test_the_fold_arm_reports_the_fold_and_the_two_numbers_it_compared():
    """A screened candidate must be diagnosable without re-running selection."""
    inst, _, _ = _fold_local_degeneracy_instance()
    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    reason = _fold_arm(res)[0]

    assert reason.startswith(_CEILING_MARKER), "diagnostics2 keys on this prefix"
    assert "lam=0.0" in reason
    assert f"condition_ceiling={_REGISTERED_CEILING}" in reason
    measured = float(reason.split("condition_number=")[1].split(" ")[0])
    assert measured > _REGISTERED_CEILING
    # The FOLD, which this test is named for and did not assert. A constant index
    # passed the suite until an independent review pointed at the gap -- while the
    # sibling RANK arm's index has been pinned all along (test_diagnostics2).
    assert f"{_FOLD_MARKER} 0" in reason, "fold 0 is the degenerate one"


def test_every_over_ceiling_fold_is_named_not_only_the_first():
    """An operator needs to know the degeneracy's extent, not one arbitrary index."""
    # Seed 4, not the default 0: seed 0 puts only TWO folds over any admissible
    # ceiling, which makes `over[1:]` and `over[1:2]` identical and lets "every"
    # silently become "the second". Three offenders are needed for the claim in
    # this test's name to be falsifiable at all.
    inst, folds, _ = _fold_local_degeneracy_instance(seed=4)
    conditions = sorted(r.condition_number for r in _fold_conditions(inst, folds))
    full = rank_diagnostics(
        inst["factors_by_k"][inst["selected_k_total"]], inst["idx_pairs"]
    ).condition_number
    # Below the THIRD-largest fold (so all three are over) but above the FULL design
    # (so the candidate arm stays silent and this measures the fold arm alone).
    assert full < conditions[-3], "no ceiling can separate the two arms on this exhibit"
    ceiling = float(np.sqrt(full * conditions[-3]))
    reason = _fold_arm(_run(inst, condition_ceiling=ceiling))[0]

    assert "also over the ceiling: fold " in reason
    named = {int(index) for index in re.findall(r"fold (\d+)", reason)}
    # IDENTITY, not count. Counting alone lets a mutant name a fold that does not
    # exist, or name a healthy under-ceiling fold, and stay green.
    by_fold = [r.condition_number for r in _fold_conditions(inst, folds)]
    expected = {i for i, c in enumerate(by_fold) if c > ceiling}
    assert named == expected, f"named {named}, over-ceiling {expected}: {reason}"
    assert len(named) >= 3, "'every' is only falsifiable with three or more offenders"
    assert max(named) < len(folds), "a named fold must exist"

    # Seed 4 puts ALL folds over, which makes "name every offender" and "name every
    # fold" indistinguishable. Seed 0 leaves one fold UNDER the ceiling, so it is the
    # fixture that can catch a clause naming healthy folds. Both are needed; either
    # alone leaves a mutant alive.
    inst0, folds0, _ = _fold_local_degeneracy_instance(seed=0)
    by_fold0 = [r.condition_number for r in _fold_conditions(inst0, folds0)]
    full0 = rank_diagnostics(
        inst0["factors_by_k"][inst0["selected_k_total"]], inst0["idx_pairs"]
    ).condition_number
    ceiling0 = float(np.sqrt(full0 * sorted(by_fold0)[-2]))
    expected0 = {i for i, c in enumerate(by_fold0) if c > ceiling0}
    under = {i for i, c in enumerate(by_fold0) if c <= ceiling0}
    assert under, "seed 0 must leave a healthy fold for this half to mean anything"
    reason0 = _fold_arm(_run(inst0, condition_ceiling=ceiling0))[0]
    named0 = {int(index) for index in re.findall(r"fold (\d+)", reason0)}
    assert named0 == expected0, f"named {named0}, over-ceiling {expected0}: {reason0}"


def test_a_rank_failure_in_any_fold_outranks_a_conditioning_failure_in_another():
    """The ordering contract is per CANDIDATE, not per fold.

    Checking rank then ceiling inside the fit loop looks equivalent and is not: the
    loop raises on the first offending fold, so a conditioning raise in fold 0
    short-circuits a rank failure in fold 1 and the candidate is recorded
    "numerically inadmissible" when it is actually NON-IDENTIFIABLE. That silently
    downgrades the diagnosis and makes the recorded reason depend on fold order --
    the misattribution class this whole screen exists to prevent. Found by
    independent review; the fix is the whole-candidate pre-pass.
    """
    inst, folds, _ = _fold_local_degeneracy_instance()
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k].copy()
    # collapse a factor for every gene OUTSIDE fold 1's held-out group, so fold 1's
    # train design loses a dimension outright while fold 0 stays full rank
    for g in range(inst["n_genes"]):
        if g not in set(folds[1].held_out_genes):
            Z[g, 1] = 0.0
    inst["factors_by_k"] = {k: Z}

    reports = _fold_conditions(inst, folds)
    assert reports[0].is_full_rank and reports[0].condition_number > _REGISTERED_CEILING
    assert not reports[1].is_full_rank, "fold 1 must be the rank-deficient one"

    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert not _fold_arm(res), "rank outranks conditioning across the whole candidate"
    rank_reasons = [r for _, _, r in res.nonviable_candidates if "non-identifiable" in r]
    assert rank_reasons
    # WHICH fold, not merely that some fold was named. Without this the reason's
    # index can be replaced by a constant `0` and the entire suite stays green --
    # and this is the only fixture in the repo where the deficient fold is not
    # fold 0, so nothing else can catch it. Found by independent review after a
    # first version of this very test asserted only that a rank reason existed.
    assert f"{_FOLD_MARKER} 1:" in rank_reasons[0], rank_reasons[0]
    assert f"{_FOLD_MARKER} 0:" not in rank_reasons[0]
    # ...and the rank REPORTED must be that fold's, not fold 0's. Substituting
    # `reports[0]` emits "non-identifiable ... rank=10, sym_dim=10" -- a
    # self-contradiction that no assertion caught.
    deficient = [r for r in reports if not r.is_full_rank][0]
    assert f"rank={deficient.rank}, sym_dim={deficient.sym_dim}" in rank_reasons[0]
    assert deficient.rank < deficient.sym_dim, "the reported rank must be deficient"


def test_every_rank_deficient_fold_is_named_not_only_the_first():
    """Symmetric with the conditioning arm, in the arm called the stronger diagnosis."""
    inst, folds, _ = _fold_local_degeneracy_instance()
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k].copy()
    # A fold's TRAIN design uses pairs with neither gene held out, so to make fold
    # i deficient the factor must vanish on every gene OUTSIDE fold i's group.
    for g in range(inst["n_genes"]):
        if g not in set(folds[1].held_out_genes):
            Z[g, 1] = 0.0
        if g not in set(folds[2].held_out_genes):
            Z[g, 2] = 0.0
    inst["factors_by_k"] = {k: Z}

    reports = _fold_conditions(inst, folds)
    deficient = [i for i, r in enumerate(reports) if not r.is_full_rank]
    assert len(deficient) >= 2, f"fixture must make several folds deficient, got {deficient}"

    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    reason = [r for _, _, r in res.nonviable_candidates if "non-identifiable" in r][0]
    named = {int(index) for index in re.findall(r"fold (\d+)", reason)}
    assert named == set(deficient), f"named {named}, deficient {deficient}: {reason}"


class _NotTheRegisteredModel(L1Model):
    """Behaves identically to the registered estimator; only its TYPE differs."""


class _SingularOnFit(L1Model):
    """A non-registered estimator whose fit reports a singular design."""

    def fit(self, Z, pairs, eps_obs, *, lam):  # type: ignore[override]
        raise SingularDesignError("stub estimator reports a singular design")


def test_a_singular_design_from_an_unregistered_estimator_invalidates_selection():
    """The counterpart the fold-arm test documents but nothing asserted.

    Reading a singular design as "this HYPERPARAMETER is non-viable" is only correct
    for the registered estimator, whose rank policy defines viability. For any other
    the run must INVALIDATE rather than quietly record a singular comparator as a bad
    lambda. Deleting that escalation left the whole suite green until this test
    existed -- and it is the asymmetry that
    ``test_the_fold_arm_records_the_same_reason_for_any_estimator`` exists to
    contrast with, so leaving one half unpinned made that contrast unfalsifiable.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    inst["model_factory"] = _SingularOnFit

    with pytest.raises(SelectionError) as excinfo:
        _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert "OOF non-viability is registered for" in str(excinfo.value)


def test_the_prepass_rank_raise_keeps_the_type_that_carries_the_escalation():
    """The rank arm's exception TYPE decides which handler sees it.

    Only the ``SingularDesignError`` handler carries the ``_OOF_SELECTION_MODEL``
    escalation; the ``FoldConditioningError`` handler deliberately does not. So
    raising the conditioning type from the RANK arm silently moves every
    rank-deficient candidate out of the escalation's reach -- and it survived the
    suite, because both types are caught and both record the same text.

    Recorded consequence, from independent review: because this pre-pass raise is
    itself model-free, routing it through the estimator-guarded handler is
    conservative rather than strictly necessary. It invalidates where it could
    record. Unreachable today (``phase2a`` hard-codes ``L1Model``); pinned so the
    choice cannot be reversed by accident.
    """
    inst, folds, _ = _fold_local_degeneracy_instance()
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k].copy()
    for g in range(inst["n_genes"]):
        if g not in set(folds[1].held_out_genes):
            Z[g, 1] = 0.0
    inst["factors_by_k"] = {k: Z}
    inst["model_factory"] = _NotTheRegisteredModel

    with pytest.raises(SelectionError) as excinfo:
        _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert "OOF non-viability is registered for" in str(excinfo.value)


def test_the_fold_arm_records_the_same_reason_for_any_estimator():
    """The deliberate asymmetry with the SingularDesignError branch, pinned.

    That branch escalates to ``SelectionError`` for a non-registered estimator,
    because a singular design means "this HYPERPARAMETER is non-viable" only for
    the registered one. Conditioning is different: ``cond(Phi)`` is a function of
    ``Z`` and the fold's train pair roster alone -- no model, no outcome -- so it
    means the same thing whatever the factory returns, and the fold arm carries no
    estimator guard. Adding one survived the suite until this test existed.
    """
    inst, _, _ = _fold_local_degeneracy_instance()
    inst["model_factory"] = _NotTheRegisteredModel
    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)

    assert _fold_arm(res), "recorded, not escalated"
    assert res.status == "CONTINUE"


def test_a_reason_that_merely_mentions_the_ceiling_is_not_a_screened_candidate(monkeypatch):
    """``startswith``, not ``in`` -- the prefix is a contract, not a keyword.

    ``select.py`` documents that a screened reason BEGINS with the prefix and that
    ``diagnostics2`` keys on it. A substring match would also catch any estimator
    error that merely quotes the ceiling in passing, and would then attribute a
    numerical stop to a screen that never ran -- a misattribution manufactured by
    the very line meant to prevent one. Weakening it to ``in`` survived the suite
    until this test existed.
    """
    import alive.compose.diagnostics2 as diagnostics2

    rng = np.random.default_rng(2)
    inst = _full_rank_instance(rng)
    real = diagnostics2.select_hyperparams

    def _mention_only(**kwargs):
        result = real(**kwargs)
        candidate = (inst["selected_k_total"], 0.0)
        reason = f"estimator failed while checking {_CEILING_MARKER} -- not a screen"
        assert not reason.startswith(_CEILING_MARKER) and _CEILING_MARKER in reason
        return replace(result, nonviable_candidates={candidate: reason})

    monkeypatch.setattr(diagnostics2, "select_hyperparams", _mention_only)
    res = _run(inst, condition_ceiling=_REGISTERED_CEILING, dev_oof_threshold=1.0)

    assert res.status == "FUTILITY_STOPPED", "the premise: a stop to attach context to"
    # Self-check: without this the test passes verbatim with the monkeypatch
    # DELETED, because an unpatched run records no nonviable candidate and emits no
    # context line either. All of its discriminating power rests on the crafted
    # reason actually reaching `diagnostics2`.
    assert res.nonviable_candidates, "the patch must actually reach diagnostics2"
    assert any(_CEILING_MARKER in r for _, _, r in res.nonviable_candidates)
    assert not any(f.startswith("context, not an independent failure") for f in res.failures), (
        "a mention is not a screen"
    )


def test_the_finiteness_guard_refuses_the_zero_width_bank_it_alone_can_see():
    """Why the ``isfinite`` guard is not redundant with the rank pass.

    ``rank_diagnostics`` returns ``inf`` when ``rank < sym_dim`` OR ``pos.size == 0``.
    At ``k_total == 0`` the second fires while ``is_full_rank`` is True (``0 >= 0``),
    so a zero-width bank arrives full-rank AND infinitely conditioned, and the rank
    pass above cannot see it. An earlier comment called the guard simply dead; it is
    not.

    Two honest limits, both from independent review. ``sym_dim == 0`` is the ONLY
    way to reach it (``pos.size == rank`` identically, so ``is_full_rank`` with
    ``cond == inf`` forces ``sym_dim == 0``), and ``config2`` pins ``total_k_grid``,
    so no legal config reaches this — the guard is white-box tested here and
    nowhere else. And this test does NOT show the rank policy "owns" the zero-width
    bank: driven end to end it is the estimator's own input contract
    (``EstimatorInputError``, ``identify.py``) that refuses it, three layers down.
    All this asserts is that the conditioning arm declines to file it.
    """
    inst, folds, _ = _fold_local_degeneracy_instance()
    empty = np.zeros((inst["n_genes"], 0), dtype=np.float64)
    report = rank_diagnostics(empty, inst["idx_pairs"])
    assert report.is_full_rank and not np.isfinite(report.condition_number)

    # must NOT raise FoldConditioningError: an inf here is a degenerate bank, and
    # filing it under the conditioning arm would be the wrong diagnosis
    _screen_unregularized_folds(
        folds=folds,
        idx_pairs=inst["idx_pairs"],
        Z=empty,
        condition_ceiling=_REGISTERED_CEILING,
    )


def test_the_fold_arm_never_swallows_a_rank_deficient_fold():
    """Same trap as the candidate arm, one level down.

    ``tiny=0.0`` removes the factor from fold 0's train pairs outright, so its
    design is rank-DEFICIENT and ``rank_diagnostics`` returns ``inf``. That case
    belongs to the registered rank policy; a fold arm that fired on it would
    relabel a rank failure as a conditioning one.
    """
    inst, folds, _ = _fold_local_degeneracy_instance(tiny=0.0)
    per_fold = _fold_conditions(inst, folds)
    assert any(not r.is_full_rank for r in per_fold)
    assert not np.isfinite(max(r.condition_number for r in per_fold))

    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert not _fold_arm(res), "rank deficiency is the rank policy's, not the screen's"
    assert not _candidate_arm(res), "and not the candidate arm's either"
    rank_reasons = [r for _, _, r in res.nonviable_candidates if "non-identifiable" in r]
    assert rank_reasons, "and the rank policy must still have recorded it"


def test_the_fold_bound_is_inclusive_and_the_comparison_is_one_ulp_sharp():
    """Kills ``>`` -> ``>=`` on the fold comparison specifically."""
    inst, folds, _ = _fold_local_degeneracy_instance()
    worst = max(r.condition_number for r in _fold_conditions(inst, folds))

    assert not _fold_arm(_run(inst, condition_ceiling=worst)), "the bound is inclusive"
    assert _fold_arm(_run(inst, condition_ceiling=float(np.nextafter(worst, 0.0))))


def test_a_fold_screened_stop_names_the_candidate_rather_than_the_dimension():
    """The misattribution link must not inflate a lam=0.0 removal into a k_total.

    Driven to a stop by a threshold above the achievable theta, so the failure the
    context line attaches to is the biology-shaped one.
    """
    inst, _, _ = _fold_local_degeneracy_instance()
    k = inst["selected_k_total"]
    res = _run(inst, condition_ceiling=_REGISTERED_CEILING, dev_oof_threshold=1.0)

    assert res.status == "FUTILITY_STOPPED"
    context = [f for f in res.failures if f.startswith("context, not an independent failure")]
    assert len(context) == 1
    assert f"({k}, 0.0)" in context[0]
    assert f"({k}, {inst['lambda_grid'][1]})" not in context[0], (
        "only the unregularized candidate was screened; naming the rest would be "
        "the very misattribution this line exists to prevent"
    )


def test_phase2a_forwards_the_registered_ceiling_rather_than_a_literal():
    """The screen is only as good as the value production actually hands it.

    Deleting the argument in ``phase2a`` is a ``TypeError`` the parameter's
    requiredness already catches. Passing a WRONG one — a hardcoded ``inf``, say —
    is caught by nothing: the screen would be dead in production with every test
    green.

    Checked with a SENTINEL config value, so a literal is caught even when it
    equals the registered one; comparing against the canonical config alone would
    not, and a hardcoded ``1.0e8`` passed that weaker form under mutation.

    The two sibling config-bound policies keep the weaker assertion on purpose:
    ``select.py`` pins both to registered constants and raises ``SelectionError``
    on anything else, so a literal there cannot diverge without failing loudly,
    and a sentinel is refused before it can prove anything. A sentinel CEILING is
    accepted (any finite positive value is legal), which is what makes the strong
    form possible here.
    """
    import dataclasses

    from alive.compose import phase2a
    from tests.alive.compose.test_phase2a import _HASHES, _build_instance, _inputs, _store

    canonical = load_compose_phase2_config(CANON)
    assert canonical.condition_ceiling == _REGISTERED_CEILING
    # distinct from the registered value, and permissive enough not to change the
    # verdict -- this test is about plumbing, not about the screen firing
    altered = dataclasses.replace(canonical, condition_ceiling=1.0e30)

    seen: dict = {}
    real = phase2a.real_calibration_diagnostics

    def _spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    phase2a.real_calibration_diagnostics = _spy
    try:
        rng = np.random.default_rng(0)
        inst = _build_instance(rng)
        phase2a.run_phase2a_fixture(
            _inputs(inst), _store(inst), expected_hashes=_HASHES, config=altered
        )
    finally:
        phase2a.real_calibration_diagnostics = real

    assert seen["condition_ceiling"] == 1.0e30, "phase2a is not forwarding the config value"
    assert seen["rank_tolerance_rule"] == canonical.rank_tolerance_rule
    assert seen["unregularized_oof_rank_policy"] == canonical.unregularized_oof_rank_policy


# --------------------------------------------------------------------------- #
# the screen cannot be silenced by an unusable ceiling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ceiling",
    [float("nan"), float("inf"), -float("inf"), 0.0, -1.0],
    ids=["nan", "inf", "neg_inf", "zero", "negative"],
)
def test_an_unusable_ceiling_is_refused_by_selection(ceiling):
    """Two opposite failures, one refusal.

    ``cond > nan`` and ``cond > inf`` are always False, so such a ceiling silences
    the screen on every candidate — a guard that is present, passes its tests, and
    never fires. A non-positive ceiling is always True, so it rejects every
    candidate including a perfect design. An earlier draft's message called ALL of
    these "silently disables", which is wrong for three of the five.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    with pytest.raises(SelectionError, match="must be finite and positive"):
        _run(inst, condition_ceiling=ceiling)


@pytest.mark.parametrize(
    "ceiling", [float("nan"), float("inf"), 0.0, -1.0], ids=["nan", "inf", "zero", "negative"]
)
def test_the_activation_gate_refuses_an_unusable_ceiling_argument(ceiling):
    """Both halves of the binding must refuse what silences or over-fires them.

    Production passes a loader-validated value, so this is defence in depth on the
    argument. It is here because the branch's own rationale names this failure
    mode, and the first version of the binding left it unguarded on this side —
    a validator called with ``inf`` accepted every design in silence.
    """
    env = _envelope_under_test()
    with pytest.raises(ValueError, match="must be finite and positive"):
        validate_phi_rank_activation_report(
            env, expected_condition_ceiling=ceiling, **_validator_kwargs(env)
        )


def test_the_refusal_runs_before_any_selection_work():
    """The other ordering, restored.

    The reversal deleted the test that pinned it. The property still held, but
    silently: the ceiling check sits in ``_validate_inputs`` ahead of the
    ``eps_obs``/``additive`` shape validation, so a malformed instance cannot mask
    it — and an unusable ceiling is never discovered after the OOF fit.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    poisoned = dict(inst)
    poisoned["eps_obs"] = np.zeros((0, 0))
    with pytest.raises(SelectionError, match="must be finite and positive"):
        _run(poisoned, condition_ceiling=float("nan"))


def test_a_screened_run_still_reports_zero_sealed_access_and_names_the_bound():
    """Two assertions the reversal dropped without recording it.

    The deleted futility test asserted ``sealed_access_count == 0`` on a
    ceiling-affected result and that the operator-facing reason carries the actual
    bound. Both still matter and neither had a home after the redesign.
    """
    inst = _signal_only_at_the_over_ceiling_dimension(0)
    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert res.sealed_access_count == 0
    reasons = _nonviable_reasons(res)
    assert reasons, "the screen fired"
    assert str(float(_REGISTERED_CEILING)) in reasons[0], "the bound must reach the operator"
    assert "condition_number=" in reasons[0], "and so must the measured value"


def test_the_refusal_still_sits_behind_the_leakage_gate():
    """A call that is both requesting a sealed role and carrying an unusable
    ceiling must report the LEAKAGE attempt, not the config-integrity failure that
    would hide it. Selection runs after ``measurability_gate``, so this holds by
    construction — pinned because an earlier draft placed the check at the top of
    the function and inverted it."""
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    assert not issubclass(LeakageError, ValueError), (
        "if LeakageError were a ValueError this assertion could not tell the two apart"
    )
    with pytest.raises(LeakageError):
        _run(inst, condition_ceiling=float("nan"), measurability_role="sealed_double_unseen")


# --------------------------------------------------------------------------- #
# the activation gate and the run's screen must agree
# --------------------------------------------------------------------------- #
def _envelope_under_test(**block_overrides):
    """The committed phi-rank evidence, repaired only where it is not under test.

    Three fields are normalised because they are not what this exercises and each
    would trip an earlier check: ``schema`` predates the current envelope,
    ``git_sha`` is the short form, and ``activation`` is ``BLOCKED`` (the committed
    report deliberately records a blocked lineage — the run it belongs to never
    opened a seal). Every other field is the committed value, and the expectations
    below are read FROM the envelope, so the conditioning check is the only thing
    left that can fail.
    """
    env = json.loads(_REAL_PHI_REPORT.read_text(encoding="utf-8"))
    env["schema"] = PHI_RANK_ACTIVATION_SCHEMA
    env["git_sha"] = env["git_sha"].ljust(40, "0")
    env["activation"] = "READY — normalised for this test only"
    for block in env["report"]["per_k_total"]:
        block.update(block_overrides)
    return env


def _validate(env):
    return validate_phi_rank_activation_report(
        env,
        expected_protocol=env["protocol"],
        expected_config_sha256=env["config_sha256"],
        expected_git_sha=env["git_sha"],
        expected_data_sha256=env["data_sha256"],
        expected_sequence_mapping_sha256=env["sequence_mapping_sha256"],
        expected_split_seed=11,
        expected_calibration_fraction=env["report"]["calibration_fraction"],
        expected_total_k_grid=[b["k_total"] for b in env["report"]["per_k_total"]],
        expected_esm_model=env["esm_model"],
        expected_esm_dim=env["report"]["esm_dim"],
        expected_condition_ceiling=_REGISTERED_CEILING,
    )


def test_the_committed_activation_evidence_still_passes_the_bound_validator():
    """Adding the ceiling must not invalidate evidence already in hand."""
    _validate(_envelope_under_test())


@pytest.mark.parametrize(
    "condition", [1.0e8 + 1.0, 1.0e12, 1.7e308], ids=["just_over", "1e12", "max"]
)
def test_the_activation_gate_refuses_a_grid_with_no_admissible_dimension(condition):
    """The gap two reviews found independently: two gates, one statistic.

    ``compute_phi_rank_report`` calls the SAME ``rank_diagnostics`` on the SAME
    full-calibration design as the run's admissibility screen, but the validator
    only ever checked full rank and finiteness, so a report could certify as READY
    a grid the run cannot use at all. Here EVERY block is over the ceiling, which
    is exactly the state that makes selection itself invalid.
    """
    with pytest.raises(ValueError, match="no admissible factor dimension"):
        _validate(_envelope_under_test(condition_number=condition))


@pytest.mark.parametrize("over_k", [4, 6, 8], ids=["k4", "k6", "k8"])
def test_the_activation_gate_accepts_a_grid_the_run_would_merely_screen(over_k):
    """ANY, not ALL — the correction two reviews demanded, independently.

    The first version of this binding raised on the FIRST over-ceiling block, so a
    single inadmissible ``k_total`` blocked scientific mode entirely. That is the
    same over-strictness the ceiling's own design was corrected for, relocated one
    gate earlier: the run screens that dimension out and proceeds on the rest, and
    the only remedy for a BLOCKED report would have been editing the registered
    ``total_k_grid`` after seeing a development diagnostic.

    ``k_total=8`` is the realistic case — `sym_dim=36` against 41 calibration
    pairs, already 30x worse conditioned than the others in the committed evidence.
    """
    env = _envelope_under_test()
    for block in env["report"]["per_k_total"]:
        if block["k_total"] == over_k:
            block["condition_number"] = 1.0e12
    assert (
        sum(1 for b in env["report"]["per_k_total"] if b["condition_number"] > _REGISTERED_CEILING)
        == 1
    ), "the premise: exactly one dimension is inadmissible"
    _validate(env)


def _validator_kwargs(env):
    return dict(
        expected_protocol=env["protocol"],
        expected_config_sha256=env["config_sha256"],
        expected_git_sha=env["git_sha"],
        expected_data_sha256=env["data_sha256"],
        expected_sequence_mapping_sha256=env["sequence_mapping_sha256"],
        expected_split_seed=11,
        expected_calibration_fraction=env["report"]["calibration_fraction"],
        expected_total_k_grid=[b["k_total"] for b in env["report"]["per_k_total"]],
        expected_esm_model=env["esm_model"],
        expected_esm_dim=env["report"]["esm_dim"],
    )


def test_the_ceiling_the_activation_gate_uses_comes_from_the_config():
    """Not a literal in `phi_rank.py`: a stricter ceiling must reject more.

    Under the ANY rule the discriminating boundary is the BEST-conditioned block,
    not the worst: at ``min(conds)`` that dimension is still admissible, and one
    ulp lower every dimension is over and the grid has nothing left.
    """
    env = _envelope_under_test()
    best = min(float(b["condition_number"]) for b in env["report"]["per_k_total"])
    kwargs = _validator_kwargs(env)
    validate_phi_rank_activation_report(env, expected_condition_ceiling=best, **kwargs)
    with pytest.raises(ValueError, match="no admissible factor dimension"):
        validate_phi_rank_activation_report(
            env, expected_condition_ceiling=float(np.nextafter(best, 0.0)), **kwargs
        )


# --------------------------------------------------------------------------- #
# config: the ceiling is registered, exact, and cannot arrive unusable
# --------------------------------------------------------------------------- #
def test_the_config_key_is_required(tmp_path):
    """Matched on the closed-schema message, not on the key name.

    Four other messages in ``_validate_identification`` also contain
    ``condition_ceiling``, so a key-name match would pass even if the key became
    optional with a default — the same substring collision already fixed twice on
    this branch.
    """
    raw = _raw()
    del raw["identification"]["condition_ceiling"]
    with pytest.raises(Phase2ConfigError, match="missing required identification keys"):
        load_compose_phase2_config(_write(tmp_path, raw))


@pytest.mark.parametrize(
    "value",
    ["1.0e8", True, None, [1.0e8]],
    ids=["str", "bool", "null", "list"],
)
def test_a_non_numeric_ceiling_is_refused_by_the_loader(tmp_path, value):
    """``"1.0e8"`` is not hypothetical: YAML 1.1 parses an unsigned exponent as a
    STRING, so the committed config must write ``1.0e+8``. The loader refuses the
    string rather than coercing it, which is how that was caught."""
    raw = _raw()
    raw["identification"]["condition_ceiling"] = value
    with pytest.raises(Phase2ConfigError, match="must be numeric"):
        load_compose_phase2_config(_write(tmp_path, raw))


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), -float("inf"), 0.0, -1.0e8],
    ids=["nan", "inf", "neg_inf", "zero", "negative"],
)
def test_an_unusable_numeric_ceiling_is_refused_for_being_unusable(tmp_path, value):
    """Matched on the SPECIFIC message, not on the key name.

    Every one of these also fails the exact-value comparison further down, whose
    message names ``condition_ceiling`` too — so a test keyed on the key name
    would still pass with the finite/positive check deleted, and the loader could
    hand a nan ceiling to a config that happened to register nan.
    """
    raw = _raw()
    raw["identification"]["condition_ceiling"] = value
    with pytest.raises(Phase2ConfigError, match="must be finite and positive"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_a_ceiling_other_than_the_preregistered_value_is_refused(tmp_path):
    raw = _raw()
    raw["identification"]["condition_ceiling"] = 1.0e9
    with pytest.raises(Phase2ConfigError, match="match the preregistration"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_the_committed_config_writes_the_exponent_form_yaml_can_parse():
    """Pins the trap itself: the raw mapping must yield a float, not a string."""
    raw = yaml.safe_load(Path(CANON).read_text(encoding="utf-8"))
    value = raw["identification"]["condition_ceiling"]
    assert isinstance(value, float), f"YAML parsed condition_ceiling as {type(value).__name__}"
    assert value == _REGISTERED_CEILING
