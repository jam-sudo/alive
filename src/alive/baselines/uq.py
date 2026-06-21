"""Preregistered UQ comparators for the ALIVE CARTOGRAPHER Trust-Gate MVP.

All comparators expose a uniform ``fit(ref_features, ref_errors, **hparams)``
and ``score(...) -> np.ndarray`` API.  Higher score = ABSTAIN (less trustworthy).

Comparators
-----------
NearestFeatureDistance
    Score = distance to the single nearest reference feature (k=1 R1).
    This is the simplest possible density-based UQ signal.

EnsembleDisagreement
    Score = spread of ensemble member predicted means in response space.
    Differing signature: ``score(ensemble_member_means)`` takes a 3-D array
    ``(n_queries, n_members, pca_dims)`` rather than feature vectors, because
    disagreement is measured in output space, not feature space.
    Spread metric: mean pairwise Euclidean distance among members.

RidgeErrorRegressor
    Ridge regression of ``ref_errors`` on ``ref_features``; score = predicted
    error.  Uses sklearn Ridge with a fixed ``alpha`` argument.

GbmErrorRegressor
    Gradient-boosted regression (sklearn ``GradientBoostingRegressor``) of
    ``ref_errors`` on ``ref_features``; score = predicted error.  The
    ``random_state`` is derived from a ``seed`` argument for determinism.

ResidualOnly
    **Mandatory ablation.** R4 component alone: ECDF-normalized
    ``local_residual(query, refs, errors, k)`` against LOO R4 distribution.
    This is a distinct class — it is NEVER produced by calling
    :class:`~alive.gate.recoverability.TrustGate` with ``w=0`` (which raises
    :class:`~alive.gate.recoverability.GateError`).

Notes
-----
All comparators receive exactly the same ``(ref_features, ref_errors)`` budget
during fit.  ``EnsembleDisagreement`` accepts them for API uniformity but does
not use ``ref_features``/``ref_errors`` in ``score``; its score input is the
ensemble member means from the base predictor.

No new dependencies are introduced.  sklearn is a declared core dep.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge

from alive.gate.recoverability import (
    ecdf_normalize,
    feature_knn_mean_distance,
    local_residual,
)

# ---------------------------------------------------------------------------
# NearestFeatureDistance
# ---------------------------------------------------------------------------


class NearestFeatureDistance:
    """Score = distance to the single nearest reference feature vector (k=1 R1).

    This is a degenerate case of
    :func:`~alive.gate.recoverability.feature_knn_mean_distance` with ``k=1``.

    Parameters (fit)
    ----------------
    ref_features : np.ndarray
        Shape ``(n_refs, d)``.  Standardized reference feature matrix.
    ref_errors : np.ndarray
        Shape ``(n_refs,)``.  Accepted for API uniformity; not used in score.

    Score
    -----
    Higher = ABSTAIN (query is farther from any reference = novel context).
    """

    def __init__(self) -> None:
        self._ref_features: np.ndarray | None = None

    def fit(self, ref_features: np.ndarray, ref_errors: np.ndarray) -> "NearestFeatureDistance":
        """Store reference features.

        Parameters
        ----------
        ref_features : np.ndarray
            Shape ``(n_refs, d)``.  Standardized reference feature matrix.
        ref_errors : np.ndarray
            Shape ``(n_refs,)``.  Not used; accepted for API uniformity.

        Returns
        -------
        NearestFeatureDistance
            Self (for chaining).
        """
        self._ref_features = np.asarray(ref_features, dtype=np.float64)
        return self

    def score(self, query_features: np.ndarray) -> np.ndarray:
        """Return the distance to the nearest reference for each query.

        Parameters
        ----------
        query_features : np.ndarray
            Shape ``(n_queries, d)``.  Standardized query feature vectors.

        Returns
        -------
        np.ndarray
            Shape ``(n_queries,)``.  Per-query distance to nearest reference.
            Higher = ABSTAIN.
        """
        assert self._ref_features is not None, "Call fit() before score()."
        return feature_knn_mean_distance(
            np.asarray(query_features, dtype=np.float64),
            self._ref_features,
            k=1,
        )


# ---------------------------------------------------------------------------
# EnsembleDisagreement
# ---------------------------------------------------------------------------


class EnsembleDisagreement:
    """Score = spread of ensemble member predicted means in response space.

    **Differing signature:** ``score`` takes ``ensemble_member_means`` of
    shape ``(n_queries, n_members, pca_dims)`` rather than feature vectors.
    Disagreement is measured in *output* space (PCA response space), not
    feature space, so it captures model uncertainty in the space where errors
    are computed.

    Spread metric
    -------------
    Mean pairwise Euclidean distance among the ``n_members`` ensemble member
    means for each query.  For a single member, the spread is 0 (no
    disagreement).  For identical members, the spread is 0.

    Parameters (fit)
    ----------------
    ref_features : np.ndarray
        Accepted for API uniformity; not used in score.
    ref_errors : np.ndarray
        Accepted for API uniformity; not used in score.

    Score
    -----
    Higher = ABSTAIN (ensemble members disagree more = more epistemic
    uncertainty about the prediction).
    """

    def __init__(self) -> None:
        # No state needed beyond the fitted flag
        self._fitted: bool = False

    def fit(self, ref_features: np.ndarray, ref_errors: np.ndarray) -> "EnsembleDisagreement":
        """Accept reference data for API uniformity; no fitting required.

        Parameters
        ----------
        ref_features : np.ndarray
            Not used; accepted for API uniformity.
        ref_errors : np.ndarray
            Not used; accepted for API uniformity.

        Returns
        -------
        EnsembleDisagreement
            Self (for chaining).
        """
        self._fitted = True
        return self

    def score(self, ensemble_member_means: np.ndarray) -> np.ndarray:
        """Return per-query ensemble spread.

        Parameters
        ----------
        ensemble_member_means : np.ndarray
            Shape ``(n_queries, n_members, pca_dims)``.  Per-member predicted
            means in response space (e.g. ``BasePrediction.ensemble_member_means``
            stacked across queries).

        Returns
        -------
        np.ndarray
            Shape ``(n_queries,)``.  Per-query mean pairwise Euclidean distance
            among ensemble members.  Higher = ABSTAIN.

        Raises
        ------
        AssertionError
            If ``fit()`` has not been called before ``score()``.

        Notes
        -----
        This method takes *ensemble member means*, not feature vectors — its
        signature differs from the other comparators because disagreement is
        measured in output space.
        """
        assert self._fitted, "Call fit() before score()."
        means = np.asarray(ensemble_member_means, dtype=np.float64)
        n_queries, n_members, _ = means.shape

        if n_members == 1:
            return np.zeros(n_queries)

        # Mean pairwise Euclidean distance among members for each query
        result = np.empty(n_queries)
        for i in range(n_queries):
            m = means[i]  # (n_members, pca_dims)
            # Pairwise distances: (n_members, n_members)
            diff = m[:, np.newaxis, :] - m[np.newaxis, :, :]  # (M, M, pca_dims)
            pairwise = np.sqrt(np.sum(diff**2, axis=-1))  # (M, M)
            # Upper triangle (unique pairs)
            n_pairs = n_members * (n_members - 1) / 2
            result[i] = pairwise[np.triu_indices(n_members, k=1)].sum() / n_pairs

        return result


# ---------------------------------------------------------------------------
# RidgeErrorRegressor
# ---------------------------------------------------------------------------


class RidgeErrorRegressor:
    """Ridge regression of ``ref_errors`` on ``ref_features``; score = predicted error.

    Uses ``sklearn.linear_model.Ridge`` with a fixed ``alpha`` regularization
    strength.  The regressor learns to predict the measured base error from
    standardized features, so a query near high-error references gets a high
    predicted error (= high abstain score).

    Parameters (fit)
    ----------------
    ref_features : np.ndarray
        Shape ``(n_refs, d)``.  Standardized reference feature matrix.
    ref_errors : np.ndarray
        Shape ``(n_refs,)``.  Measured base errors (regression targets).
    alpha : float
        Ridge regularization strength.

    Score
    -----
    Higher = ABSTAIN (higher predicted error = less trustworthy prediction).
    """

    def __init__(self) -> None:
        self._model: Ridge | None = None

    def fit(
        self, ref_features: np.ndarray, ref_errors: np.ndarray, *, alpha: float
    ) -> "RidgeErrorRegressor":
        """Fit ridge regression on (ref_features, ref_errors).

        Parameters
        ----------
        ref_features : np.ndarray
            Shape ``(n_refs, d)``.  Standardized reference feature matrix.
        ref_errors : np.ndarray
            Shape ``(n_refs,)``.  Measured base errors (regression targets).
        alpha : float
            Ridge regularization strength.

        Returns
        -------
        RidgeErrorRegressor
            Self (for chaining).
        """
        self._model = Ridge(alpha=alpha, fit_intercept=True)
        self._model.fit(
            np.asarray(ref_features, dtype=np.float64),
            np.asarray(ref_errors, dtype=np.float64),
        )
        return self

    def score(self, query_features: np.ndarray) -> np.ndarray:
        """Return predicted error for each query.

        Parameters
        ----------
        query_features : np.ndarray
            Shape ``(n_queries, d)``.  Standardized query feature vectors.

        Returns
        -------
        np.ndarray
            Shape ``(n_queries,)``.  Predicted error.  Higher = ABSTAIN.

        Notes
        -----
        Scores may be negative because ``Ridge.predict`` is unconstrained (no
        non-negativity constraint).  This is acceptable: comparators are evaluated
        by AURC, which is rank-based within each method.  Absolute score scales
        are not mixed across methods; only the within-method ranking matters.
        """
        assert self._model is not None, "Call fit() before score()."
        return self._model.predict(np.asarray(query_features, dtype=np.float64))


# ---------------------------------------------------------------------------
# GbmErrorRegressor
# ---------------------------------------------------------------------------


class GbmErrorRegressor:
    """Gradient-boosted regression of ``ref_errors`` on ``ref_features``.

    Uses ``sklearn.ensemble.GradientBoostingRegressor`` with a fixed
    ``random_state`` derived from a ``seed`` argument for full determinism.
    Identical inputs + ``n_estimators`` + ``seed`` → identical scores.

    Parameters (fit)
    ----------------
    ref_features : np.ndarray
        Shape ``(n_refs, d)``.  Standardized reference feature matrix.
    ref_errors : np.ndarray
        Shape ``(n_refs,)``.  Measured base errors (regression targets).
    n_estimators : int
        Number of boosting stages.
    seed : int
        Random state for reproducibility.

    Score
    -----
    Higher = ABSTAIN (higher predicted error = less trustworthy prediction).
    """

    def __init__(self) -> None:
        self._model: GradientBoostingRegressor | None = None

    def fit(
        self,
        ref_features: np.ndarray,
        ref_errors: np.ndarray,
        *,
        n_estimators: int,
        seed: int,
    ) -> "GbmErrorRegressor":
        """Fit gradient boosting on (ref_features, ref_errors).

        Parameters
        ----------
        ref_features : np.ndarray
            Shape ``(n_refs, d)``.  Standardized reference feature matrix.
        ref_errors : np.ndarray
            Shape ``(n_refs,)``.  Measured base errors (regression targets).
        n_estimators : int
            Number of boosting stages.
        seed : int
            Random state seed for ``GradientBoostingRegressor``.  Identical
            inputs + ``n_estimators`` + ``seed`` → identical predictions.

        Returns
        -------
        GbmErrorRegressor
            Self (for chaining).
        """
        self._model = GradientBoostingRegressor(
            n_estimators=n_estimators,
            random_state=seed,
        )
        self._model.fit(
            np.asarray(ref_features, dtype=np.float64),
            np.asarray(ref_errors, dtype=np.float64),
        )
        return self

    def score(self, query_features: np.ndarray) -> np.ndarray:
        """Return predicted error for each query.

        Parameters
        ----------
        query_features : np.ndarray
            Shape ``(n_queries, d)``.  Standardized query feature vectors.

        Returns
        -------
        np.ndarray
            Shape ``(n_queries,)``.  Predicted error.  Higher = ABSTAIN.
        """
        assert self._model is not None, "Call fit() before score()."
        return self._model.predict(np.asarray(query_features, dtype=np.float64))


# ---------------------------------------------------------------------------
# ResidualOnly — mandatory ablation
# ---------------------------------------------------------------------------


class ResidualOnly:
    """Mandatory ablation: R4 component alone (ECDF-normalized local residual).

    This is the gate's R4 component in isolation.  It is the official ablation
    that shows the contribution of the R1 (feature-distance) signal by
    comparison with the full :class:`~alive.gate.recoverability.TrustGate`.

    This MUST be a distinct class.  It is NEVER produced by calling
    :class:`~alive.gate.recoverability.TrustGate` with ``w=0`` — that raises
    :class:`~alive.gate.recoverability.GateError`.

    Computation
    -----------
    ::

        loo_r4  = local_residual(ref, ref, ref_errors, k, loo=True)
        R4      = local_residual(query, ref, ref_errors, k)
        score   = ecdf_normalize(R4, loo_r4)

    Parameters (fit)
    ----------------
    ref_features : np.ndarray
        Shape ``(n_refs, d)``.  Standardized reference feature matrix.
    ref_errors : np.ndarray
        Shape ``(n_refs,)``.  Measured base errors.
    k : int
        Number of nearest neighbours for the local residual.

    Score
    -----
    Higher = ABSTAIN (queries near high-error references score higher).
    """

    def __init__(self) -> None:
        self._ref_features: np.ndarray | None = None
        self._ref_errors: np.ndarray | None = None
        self._k: int | None = None
        self._loo_r4: np.ndarray | None = None

    def fit(self, ref_features: np.ndarray, ref_errors: np.ndarray, *, k: int) -> "ResidualOnly":
        """Store references and precompute LOO R4 distribution.

        Parameters
        ----------
        ref_features : np.ndarray
            Shape ``(n_refs, d)``.  Standardized reference feature matrix.
        ref_errors : np.ndarray
            Shape ``(n_refs,)``.  Measured base errors.
        k : int
            Number of nearest neighbours.

        Returns
        -------
        ResidualOnly
            Self (for chaining).
        """
        self._ref_features = np.asarray(ref_features, dtype=np.float64)
        self._ref_errors = np.asarray(ref_errors, dtype=np.float64)
        self._k = k
        self._loo_r4 = local_residual(
            self._ref_features, self._ref_features, self._ref_errors, k, loo=True
        )
        return self

    def score(self, query_features: np.ndarray) -> np.ndarray:
        """Return ECDF-normalized R4 (local-residual) score.

        Parameters
        ----------
        query_features : np.ndarray
            Shape ``(n_queries, d)``.  Standardized query feature vectors.

        Returns
        -------
        np.ndarray
            Shape ``(n_queries,)``.  ECDF-normalized R4 score in ``[0, 1]``.
            Higher = ABSTAIN.
        """
        assert self._ref_features is not None, "Call fit() before score()."
        r4 = local_residual(
            np.asarray(query_features, dtype=np.float64),
            self._ref_features,
            self._ref_errors,
            self._k,
        )
        return ecdf_normalize(r4, self._loo_r4)
