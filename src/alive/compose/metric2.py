"""COMPOSE-K562-v1 Phase-2 registered metrics (spec §10.5, config metric block).

ACTIVATION BLOCKED: pure-``numpy`` scoring on synthetic inputs only. This module
contains no seal access and no data ingestion; it scores already-computed
predictions against already-computed truth in the PCA-50 response space.

Primary metric (config ``metric.primary = paired_relative_error_reduction``)::

    e_{M,i}     = mean_j( (pred_{M,i,j} - truth_{i,j})^2 )          # per-pair MSE
    theta_{M,C} = 1 - mean_i(e_{M,i}) / max(mean_i(e_{C,i}), 1e-12) # paired ratio

``theta`` is the paired relative error reduction of a method ``M`` over a
comparator ``C`` (config ``metric.aggregation = ratio_of_mean_pair_errors``).
Positive ``theta`` means ``M`` has lower mean per-pair error than ``C``.

Secondary metrics (config ``metric.secondary``):

* ``gi_explained_fraction``::

      1 - sum||eps_truth - eps_pred||^2 / max(sum||eps_truth||^2, 1e-12)

* ``gi_structure_recovery`` — deferred. It is computable only when a versioned,
  hashed class-label manifest AND a fully specified prediction-to-class rule both
  exist. Until then it returns the explicit :data:`NOT_EVALUABLE` sentinel; it is
  never silently omitted and never fed to a verdict
  (config ``metric.secondary_are_verdict_gates = false``).

Input discipline (config ``metric.nonfinite_or_missing_policy = invalidate_run``):
empty, ID-misaligned, duplicate-ID, non-finite and shape-mismatched inputs all
raise :class:`MetricError`. Pairs are aligned by ID, never by row position, so a
shuffled truth/comparator ordering is realigned rather than silently mis-scored.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

import numpy as np

# Denominator floor shared by the primary ratio and the GI-explained fraction.
# Kept identical to the config formula string and to ``alive.compose.config2``.
_EPS_FLOOR: Final[float] = 1e-12


class MetricError(ValueError):
    """Raised on any invalid metric input (invalidate-run policy, spec §10.5)."""


class _NotEvaluable:
    """Singleton sentinel for a metric that cannot yet be computed.

    Distinct from any numeric verdict value: it is not equal to ``0.0`` or
    ``1.0`` and stringifies to ``"NOT_EVALUABLE"`` so it is impossible to launder
    into a numeric verdict.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "NOT_EVALUABLE"

    def __str__(self) -> str:
        return "NOT_EVALUABLE"

    def __eq__(self, other: object) -> bool:
        return other is self

    def __ne__(self, other: object) -> bool:
        return other is not self

    def __hash__(self) -> int:
        return hash("NOT_EVALUABLE")

    def __bool__(self) -> bool:  # never silently truthy as a "pass"
        return False


#: Explicit "deferred / cannot score" sentinel for GI structure recovery.
NOT_EVALUABLE: Final[_NotEvaluable] = _NotEvaluable()


def _validate_matrix(arr: np.ndarray, name: str) -> np.ndarray:
    """Coerce to a finite 2-D float64 array with at least one row and column."""
    a = np.asarray(arr, dtype=np.float64)
    if a.ndim != 2:
        raise MetricError(f"{name} must be 2-D (n_pairs, n_coords); got ndim={a.ndim}")
    if a.shape[0] == 0:
        raise MetricError(f"{name} is empty (zero pairs)")
    if a.shape[1] == 0:
        raise MetricError(f"{name} has zero response coordinates")
    if not np.all(np.isfinite(a)):
        raise MetricError(f"{name} contains non-finite values (nan/inf)")
    return a


def _validate_ids(ids: Sequence[Any], n_rows: int, name: str) -> list[str]:
    """Return IDs as a list, rejecting empty, length-mismatched or duplicated IDs."""
    id_list = [str(x) for x in ids]
    if len(id_list) == 0:
        raise MetricError(f"{name} is empty")
    if len(id_list) != n_rows:
        raise MetricError(f"{name} has {len(id_list)} ids for {n_rows} rows (count mismatch)")
    if len(set(id_list)) != len(id_list):
        raise MetricError(f"{name} contains duplicate pair IDs")
    return id_list


def _align_to(
    reference_ids: list[str],
    arr: np.ndarray,
    arr_ids: list[str],
    name: str,
) -> np.ndarray:
    """Reorder ``arr`` rows so they follow ``reference_ids`` (alignment by ID).

    Both ID sets must be identical; an ID present in one but not the other is a
    hard :class:`MetricError` (misalignment is never silently dropped).
    """
    ref_set = set(reference_ids)
    arr_set = set(arr_ids)
    if ref_set != arr_set:
        missing = ref_set - arr_set
        extra = arr_set - ref_set
        raise MetricError(
            f"{name} IDs do not match prediction IDs "
            f"(missing={sorted(missing)}, extra={sorted(extra)})"
        )
    index = {pair_id: row for row, pair_id in enumerate(arr_ids)}
    order = [index[pair_id] for pair_id in reference_ids]
    return arr[order]


def per_pair_mse(
    prediction: np.ndarray,
    truth: np.ndarray,
    *,
    pair_ids: Sequence[Any],
    truth_ids: Sequence[Any],
) -> np.ndarray:
    r"""Per-pair mean squared error over response (PCA) coordinates.

    Computes ``e_i = mean_j((pred_{i,j} - truth_{i,j})^2)`` after aligning
    ``truth`` to ``prediction`` by pair ID.

    Parameters
    ----------
    prediction, truth : numpy.ndarray
        Float arrays of shape ``(n_pairs, n_coords)`` in the response space.
    pair_ids, truth_ids : sequence
        Pair identifiers labelling the rows of ``prediction`` and ``truth``.

    Returns
    -------
    numpy.ndarray
        Shape ``(n_pairs,)``, ordered to follow ``pair_ids``.

    Raises
    ------
    MetricError
        On empty, non-finite, duplicate-ID, count-mismatched, shape-mismatched
        or ID-misaligned inputs.
    """
    pred = _validate_matrix(prediction, "prediction")
    tru = _validate_matrix(truth, "truth")
    if pred.shape[1] != tru.shape[1]:
        raise MetricError(f"prediction/truth coord dim mismatch: {pred.shape[1]} vs {tru.shape[1]}")
    pred_ids = _validate_ids(pair_ids, pred.shape[0], "pair_ids")
    tru_ids = _validate_ids(truth_ids, tru.shape[0], "truth_ids")
    tru = _align_to(pred_ids, tru, tru_ids, "truth")
    resid = pred - tru
    return np.mean(resid * resid, axis=1)


def paired_relative_error_reduction(
    method_prediction: np.ndarray,
    comparator_prediction: np.ndarray,
    truth: np.ndarray,
    *,
    pair_ids: Sequence[Any],
    comparator_ids: Sequence[Any],
    truth_ids: Sequence[Any],
) -> float:
    r"""Primary metric ``theta_{M,C}`` (config ``paired_relative_error_reduction``).

    ::

        theta = 1 - mean_i(e_{M,i}) / max(mean_i(e_{C,i}), 1e-12)

    where ``e_{M,i}`` / ``e_{C,i}`` are the per-pair MSEs of method ``M`` and
    comparator ``C`` against the shared truth. The comparator and truth are
    aligned to the method by pair ID.

    Parameters
    ----------
    method_prediction, comparator_prediction, truth : numpy.ndarray
        Float arrays of shape ``(n_pairs, n_coords)``.
    pair_ids, comparator_ids, truth_ids : sequence
        Pair identifiers for the rows of each array.

    Returns
    -------
    float
        ``theta``. ``theta == 1`` for a perfect method, ``theta == 0`` when the
        method equals the comparator, ``theta < 0`` when worse than the
        comparator. The ``1e-12`` floor keeps the result finite when the
        comparator error is zero.

    Raises
    ------
    MetricError
        On any invalid input (see :func:`per_pair_mse`).
    """
    method = _validate_matrix(method_prediction, "method_prediction")
    comparator = _validate_matrix(comparator_prediction, "comparator_prediction")
    tru = _validate_matrix(truth, "truth")
    if not (method.shape[1] == comparator.shape[1] == tru.shape[1]):
        raise MetricError(
            "coord dim mismatch across method/comparator/truth: "
            f"{method.shape[1]} / {comparator.shape[1]} / {tru.shape[1]}"
        )
    m_ids = _validate_ids(pair_ids, method.shape[0], "pair_ids")
    c_ids = _validate_ids(comparator_ids, comparator.shape[0], "comparator_ids")
    t_ids = _validate_ids(truth_ids, tru.shape[0], "truth_ids")

    comparator = _align_to(m_ids, comparator, c_ids, "comparator")
    tru_aligned = _align_to(m_ids, tru, t_ids, "truth")

    e_method = np.mean((method - tru_aligned) ** 2, axis=1)
    e_comparator = np.mean((comparator - tru_aligned) ** 2, axis=1)

    mean_method = float(np.mean(e_method))
    mean_comparator = float(np.mean(e_comparator))
    return 1.0 - mean_method / max(mean_comparator, _EPS_FLOOR)


def gi_explained_fraction(
    eps_pred: np.ndarray,
    eps_truth: np.ndarray,
    *,
    pair_ids: Sequence[Any],
    truth_ids: Sequence[Any],
) -> float:
    r"""Secondary metric: fraction of GI (epsilon) variance explained.

    ::

        1 - sum_i ||eps_truth_i - eps_pred_i||^2 / max(sum_i ||eps_truth_i||^2, 1e-12)

    ``eps_truth`` is aligned to ``eps_pred`` by pair ID. ``1.0`` for perfect GI
    prediction, ``0.0`` for a zero (no-GI) prediction against nonzero truth.

    Parameters
    ----------
    eps_pred, eps_truth : numpy.ndarray
        Predicted and observed GI (interaction) terms, ``(n_pairs, n_coords)``.
    pair_ids, truth_ids : sequence
        Pair identifiers for the rows of each array.

    Returns
    -------
    float
        Explained fraction (unclipped; can be negative when the prediction is
        worse than predicting all-zero GI).

    Raises
    ------
    MetricError
        On any invalid input (see :func:`per_pair_mse`).
    """
    pred = _validate_matrix(eps_pred, "eps_pred")
    tru = _validate_matrix(eps_truth, "eps_truth")
    if pred.shape[1] != tru.shape[1]:
        raise MetricError(f"eps coord dim mismatch: {pred.shape[1]} vs {tru.shape[1]}")
    p_ids = _validate_ids(pair_ids, pred.shape[0], "pair_ids")
    t_ids = _validate_ids(truth_ids, tru.shape[0], "truth_ids")
    tru = _align_to(p_ids, tru, t_ids, "eps_truth")

    residual_ss = float(np.sum((tru - pred) ** 2))
    truth_ss = float(np.sum(tru**2))
    return 1.0 - residual_ss / max(truth_ss, _EPS_FLOOR)


def gi_structure_recovery(
    *,
    eps_pred: np.ndarray,
    eps_truth: np.ndarray,
    pair_ids: Sequence[Any],
    truth_ids: Sequence[Any],
    class_manifest: dict[str, Any] | None = None,
    prediction_to_class_rule: Any | None = None,
) -> _NotEvaluable:
    """Secondary metric: GI sign/class recovery vs a known structure (deferred).

    Computable only when BOTH a versioned, hashed class-label manifest and a
    fully specified prediction-to-class rule exist. Neither is registered in
    Phase 2, so this always returns :data:`NOT_EVALUABLE`. The sentinel is
    returned explicitly (never silently omitted) and must never be fed to a
    verdict; the real structure metric is intentionally deferred.

    Parameters
    ----------
    eps_pred, eps_truth : numpy.ndarray
        GI terms (kept for the future real implementation's signature stability).
    pair_ids, truth_ids : sequence
        Pair identifiers.
    class_manifest : dict, optional
        Versioned, hashed class-label manifest. ``None`` until registered.
    prediction_to_class_rule : Any, optional
        Fully specified rule mapping predictions to GI classes. ``None`` until
        registered.

    Returns
    -------
    _NotEvaluable
        :data:`NOT_EVALUABLE` whenever either prerequisite is missing.
    """
    if class_manifest is None or prediction_to_class_rule is None:
        return NOT_EVALUABLE
    # Both prerequisites present: the real metric is deferred. Refuse to fabricate
    # a number rather than silently emit a placeholder verdict input.
    return NOT_EVALUABLE
