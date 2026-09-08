"""Known-answer + guard tests for COMPOSE Phase-2 metrics (spec §10.5).

Synthetic-only: no real Norman outcomes are touched.
The primary metric is the paired relative error reduction

    e_{M,i}     = mean_j( (pred_{M,i,j} - truth_{i,j})^2 )
    theta_{M,C} = (mean_i(e_{C,i}) - mean_i(e_{M,i})) / max(mean_i(e_{C,i}), 1e-12)

and the secondary GI-explained fraction

    1 - sum||eps_truth - eps_pred||^2 / max(sum||eps_truth||^2, 1e-12).

GI structure recovery is deferred and must return the sentinel ``NOT_EVALUABLE``.
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.compose.metric2 import (
    NOT_EVALUABLE,
    MetricError,
    gi_explained_fraction,
    gi_structure_recovery,
    paired_relative_error_reduction,
    per_pair_mse,
)


# --------------------------------------------------------------------------- #
# per-pair MSE primitive
# --------------------------------------------------------------------------- #
def test_per_pair_mse_known_answer():
    """e_{M,i} is the mean over response coords of the squared residual."""
    pred = np.array([[1.0, 2.0], [3.0, 4.0]])
    truth = np.array([[0.0, 0.0], [3.0, 0.0]])  # resid row0=[1,2], row1=[0,4]
    e = per_pair_mse(pred, truth, pair_ids=["a", "b"], truth_ids=["a", "b"])
    # row0: (1+4)/2 = 2.5 ; row1: (0+16)/2 = 8.0
    np.testing.assert_allclose(e, [2.5, 8.0])


def test_per_pair_mse_aligns_by_id_not_position():
    """Truth supplied in a different ID order is realigned to prediction order."""
    pred = np.array([[1.0, 0.0], [0.0, 2.0]])  # ids a, b
    truth = np.array([[0.0, 2.0], [1.0, 0.0]])  # ids b, a -> shuffled rows
    # truth["a"] = row1 = [1, 0]; truth["b"] = row0 = [0, 2]
    e = per_pair_mse(pred, truth, pair_ids=["a", "b"], truth_ids=["b", "a"])
    # a: pred[a]=[1,0] vs truth[a]=[1,0] -> resid [0,0] -> 0
    # b: pred[b]=[0,2] vs truth[b]=[0,2] -> resid [0,0] -> 0
    np.testing.assert_allclose(e, [0.0, 0.0])
    # Confirm alignment matters: labelling the SAME shuffled truth as if it were
    # already in pred order (positional scoring) yields non-zero error.
    e_positional = per_pair_mse(pred, truth, pair_ids=["a", "b"], truth_ids=["a", "b"])
    assert not np.allclose(e_positional, [0.0, 0.0])


# --------------------------------------------------------------------------- #
# primary metric — known answers
# --------------------------------------------------------------------------- #
def test_theta_perfect_prediction_is_one():
    """A perfect method has zero error -> theta = 1 over any nonzero comparator."""
    truth = np.array([[1.0, 2.0], [3.0, 4.0]])
    method = truth.copy()
    comparator = truth + 1.0  # nonzero error
    theta = paired_relative_error_reduction(
        method,
        comparator,
        truth,
        pair_ids=["a", "b"],
        comparator_ids=["a", "b"],
        truth_ids=["a", "b"],
    )
    assert theta == pytest.approx(1.0)


def test_theta_additive_truth_equals_zero():
    """If the model reproduces the additive comparator exactly, theta == 0."""
    truth = np.array([[0.0, 0.0], [0.0, 0.0]])
    additive = np.array([[1.0, 1.0], [2.0, 2.0]])  # some nonzero error
    method = additive.copy()  # model == additive
    theta = paired_relative_error_reduction(
        method,
        additive,
        truth,
        pair_ids=["a", "b"],
        comparator_ids=["a", "b"],
        truth_ids=["a", "b"],
    )
    assert theta == pytest.approx(0.0)


def test_theta_worse_than_additive_is_negative():
    """A method worse than its comparator yields theta < 0."""
    truth = np.array([[0.0], [0.0]])
    additive = np.array([[1.0], [1.0]])  # comparator error = 1
    method = np.array([[2.0], [2.0]])  # method error = 4 > 1
    theta = paired_relative_error_reduction(
        method,
        additive,
        truth,
        pair_ids=["a", "b"],
        comparator_ids=["a", "b"],
        truth_ids=["a", "b"],
    )
    assert theta < 0.0
    # 1 - 4/1 = -3
    assert theta == pytest.approx(-3.0)


def test_theta_zero_denominator_guard():
    """When the comparator is also perfect the 1e-12 floor prevents div-by-zero."""
    truth = np.array([[1.0, 2.0], [3.0, 4.0]])
    method = truth.copy()  # error 0
    comparator = truth.copy()  # error 0 -> denom floored to 1e-12
    theta = paired_relative_error_reduction(
        method,
        comparator,
        truth,
        pair_ids=["a", "b"],
        comparator_ids=["a", "b"],
        truth_ids=["a", "b"],
    )
    # Both methods are perfect: the stabilized contrast is an exact tie.
    assert np.isfinite(theta)
    assert theta == pytest.approx(0.0)


@pytest.mark.parametrize("mse,expected", [(0.0, 0.0), (5e-13, 0.5), (1e-12, 1.0)])
def test_theta_at_and_below_the_comparator_epsilon_floor_is_the_stabilized_difference(
    mse, expected
):
    """Known answers where the registered formula (mean_C - mean_M)/max(mean_C, 1e-12) and the
    withdrawn spec sentence 1 - mean_M/max(mean_C, 1e-12) differ below the floor and agree at the
    boundary (mse=1e-12 -> 1.0 in both): a perfect method against a comparator at or below the
    floor. The withdrawn form returns 1.0 in every row."""
    truth = np.zeros((2, 1))
    comparator = np.full((2, 1), np.sqrt(mse))
    ids = ["a", "b"]
    theta = paired_relative_error_reduction(
        truth, comparator, truth, pair_ids=ids, comparator_ids=ids, truth_ids=ids
    )
    assert theta == pytest.approx(expected, rel=1e-9)


def test_theta_shuffled_pair_ids_aligned_not_positional():
    """Permuting the comparator/truth ID order must not change theta."""
    truth = np.array([[0.0], [0.0], [0.0]])
    method = np.array([[1.0], [1.0], [1.0]])  # error 1 each
    comparator = np.array([[2.0], [2.0], [2.0]])  # error 4 each
    base = paired_relative_error_reduction(
        method,
        comparator,
        truth,
        pair_ids=["a", "b", "c"],
        comparator_ids=["a", "b", "c"],
        truth_ids=["a", "b", "c"],
    )
    # shuffle comparator + truth row order with matching id lists
    perm = [2, 0, 1]
    theta = paired_relative_error_reduction(
        method,
        comparator[perm],
        truth[perm],
        pair_ids=["a", "b", "c"],
        comparator_ids=[["a", "b", "c"][p] for p in perm],
        truth_ids=[["a", "b", "c"][p] for p in perm],
    )
    assert theta == pytest.approx(base)
    assert theta == pytest.approx(1 - 1.0 / 4.0)


# --------------------------------------------------------------------------- #
# primary metric — rejected / invalid inputs
# --------------------------------------------------------------------------- #
def test_empty_input_rejected():
    with pytest.raises(MetricError):
        paired_relative_error_reduction(
            np.empty((0, 2)),
            np.empty((0, 2)),
            np.empty((0, 2)),
            pair_ids=[],
            comparator_ids=[],
            truth_ids=[],
        )


def test_misaligned_ids_rejected():
    """An ID present in prediction but absent from truth is a hard error."""
    truth = np.array([[0.0], [0.0]])
    method = np.array([[1.0], [1.0]])
    comparator = np.array([[2.0], [2.0]])
    with pytest.raises(MetricError):
        paired_relative_error_reduction(
            method,
            comparator,
            truth,
            pair_ids=["a", "b"],
            comparator_ids=["a", "b"],
            truth_ids=["a", "x"],  # "b" missing, "x" extra
        )


def test_duplicated_ids_rejected():
    truth = np.array([[0.0], [0.0]])
    method = np.array([[1.0], [1.0]])
    comparator = np.array([[2.0], [2.0]])
    with pytest.raises(MetricError):
        paired_relative_error_reduction(
            method,
            comparator,
            truth,
            pair_ids=["a", "a"],  # duplicate
            comparator_ids=["a", "b"],
            truth_ids=["a", "b"],
        )


def test_nonfinite_inputs_rejected():
    truth = np.array([[0.0], [0.0]])
    comparator = np.array([[2.0], [2.0]])
    method = np.array([[np.nan], [1.0]])  # nan
    with pytest.raises(MetricError):
        paired_relative_error_reduction(
            method,
            comparator,
            truth,
            pair_ids=["a", "b"],
            comparator_ids=["a", "b"],
            truth_ids=["a", "b"],
        )
    method_inf = np.array([[np.inf], [1.0]])
    with pytest.raises(MetricError):
        paired_relative_error_reduction(
            method_inf,
            comparator,
            truth,
            pair_ids=["a", "b"],
            comparator_ids=["a", "b"],
            truth_ids=["a", "b"],
        )


def test_shape_mismatch_rejected():
    """Differing response dimension across method/comparator/truth is rejected."""
    truth = np.array([[0.0, 0.0], [0.0, 0.0]])  # 2 coords
    method = np.array([[1.0], [1.0]])  # 1 coord
    comparator = np.array([[2.0, 2.0], [2.0, 2.0]])
    with pytest.raises(MetricError):
        paired_relative_error_reduction(
            method,
            comparator,
            truth,
            pair_ids=["a", "b"],
            comparator_ids=["a", "b"],
            truth_ids=["a", "b"],
        )


def test_id_count_mismatch_rejected():
    """An ID list whose length differs from its array's row count is rejected."""
    truth = np.array([[0.0], [0.0]])
    method = np.array([[1.0], [1.0]])
    comparator = np.array([[2.0], [2.0]])
    with pytest.raises(MetricError):
        paired_relative_error_reduction(
            method,
            comparator,
            truth,
            pair_ids=["a"],  # only one id for two rows
            comparator_ids=["a", "b"],
            truth_ids=["a", "b"],
        )


# --------------------------------------------------------------------------- #
# secondary — GI explained fraction
# --------------------------------------------------------------------------- #
def test_gi_explained_fraction_perfect_is_one():
    eps_truth = np.array([[1.0, -2.0], [0.5, 3.0]])
    eps_pred = eps_truth.copy()
    frac = gi_explained_fraction(eps_pred, eps_truth, pair_ids=["a", "b"], truth_ids=["a", "b"])
    assert frac == pytest.approx(1.0)


def test_gi_explained_fraction_zero_prediction_is_zero():
    """Predicting no GI leaves all variance unexplained -> fraction 0."""
    eps_truth = np.array([[1.0, -2.0], [0.5, 3.0]])
    eps_pred = np.zeros_like(eps_truth)
    frac = gi_explained_fraction(eps_pred, eps_truth, pair_ids=["a", "b"], truth_ids=["a", "b"])
    assert frac == pytest.approx(0.0)


def test_gi_explained_fraction_zero_denominator_guard():
    """All-zero truth GI -> denominator floored, fraction stays finite."""
    eps_truth = np.zeros((2, 2))
    eps_pred = np.array([[0.0, 0.0], [0.0, 0.0]])
    frac = gi_explained_fraction(eps_pred, eps_truth, pair_ids=["a", "b"], truth_ids=["a", "b"])
    assert np.isfinite(frac)
    assert frac == pytest.approx(1.0)


def test_gi_explained_fraction_aligns_by_id():
    eps_truth = np.array([[1.0], [2.0]])  # ids a, b
    eps_pred = np.array([[2.0], [1.0]])  # ids b, a
    frac = gi_explained_fraction(eps_pred, eps_truth, pair_ids=["a", "b"], truth_ids=["b", "a"])
    # realigned pred = [[1],[2]] == truth -> 1.0
    assert frac == pytest.approx(1.0)


def test_gi_explained_fraction_nonfinite_rejected():
    eps_truth = np.array([[1.0], [2.0]])
    eps_pred = np.array([[np.nan], [2.0]])
    with pytest.raises(MetricError):
        gi_explained_fraction(eps_pred, eps_truth, pair_ids=["a", "b"], truth_ids=["a", "b"])


# --------------------------------------------------------------------------- #
# secondary — GI structure recovery (deferred)
# --------------------------------------------------------------------------- #
def test_gi_structure_recovery_not_evaluable_without_manifest():
    """No hashed class-label manifest -> explicit NOT_EVALUABLE sentinel."""
    result = gi_structure_recovery(
        eps_pred=np.array([[1.0], [2.0]]),
        eps_truth=np.array([[1.0], [2.0]]),
        pair_ids=["a", "b"],
        truth_ids=["a", "b"],
        class_manifest=None,
        prediction_to_class_rule=None,
    )
    assert result is NOT_EVALUABLE


def test_gi_structure_recovery_not_evaluable_without_rule():
    """Manifest present but no fully specified rule -> still NOT_EVALUABLE."""
    result = gi_structure_recovery(
        eps_pred=np.array([[1.0], [2.0]]),
        eps_truth=np.array([[1.0], [2.0]]),
        pair_ids=["a", "b"],
        truth_ids=["a", "b"],
        class_manifest={"sha256": "deadbeef", "labels": {"a": 1, "b": 0}},
        prediction_to_class_rule=None,
    )
    assert result is NOT_EVALUABLE


def test_not_evaluable_is_distinct_sentinel():
    """The sentinel is not a number and not silently falsy-equal to a verdict."""
    assert NOT_EVALUABLE != 0.0
    assert NOT_EVALUABLE != 1.0
    assert str(NOT_EVALUABLE) == "NOT_EVALUABLE"
