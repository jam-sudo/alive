"""Trust-gate scorers: R1 (feature-kNN) and R4 (local-residual), ECDF-normalized.

The TrustGate combines two complementary recoverability signals:

- **R1 — feature-kNN distance:** How far a query is from the reference bank in
  standardized feature space.  Captures *novelty* (the query is unlike anything
  seen during method development).
- **R4 — local residual:** Median measured base-error of the k nearest reference
  items.  Captures *known local difficulty* (nearby perturbations were hard even
  when seen).

Both signals are ECDF-normalized against leave-one-out (LOO) reference
distributions so they are comparable and unit-free.  The combined score is::

    score = w * R1_ecdf + (1 - w) * R4_ecdf

Higher score → ABSTAIN (less trustworthy).  Lower score → PREDICT.

Leave-one-out (LOO) mechanism
------------------------------
When scoring reference items *against themselves* (``queries is refs`` or
equivalently the same array with the same length), using the ordinary k-NN
would include each item's own zero self-distance, which biases R1 downward and
R4 toward the item's own error.  To correct for this, every kNN function
accepts an optional ``loo: bool`` flag.  When ``loo=True`` **and**
``queries.shape == refs.shape`` (same number of rows), the pairwise distance
matrix is constructed and each item's *own column* (diagonal) is masked out
before sorting, so the nearest ``k`` neighbors are always from the *other*
``n-1`` reference items.

This is the mechanism used by :meth:`TrustGate.fit` to precompute ``loo_r1``
and ``loo_r4`` (the LOO reference distributions for ECDF normalization).

Public API
----------
GateError
    Raised for invalid gate configuration.
feature_knn_mean_distance
    Mean Euclidean distance to k nearest reference features.
local_residual
    Median error over k nearest reference items.
ecdf_normalize
    ECDF-rank normalization: fraction of reference <= value, in [0,1].
TrustGate
    Full trust gate combining R1 and R4 via ECDF-normalized weighted sum.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class GateError(ValueError):
    """Raised for invalid gate configuration.

    Parameters
    ----------
    message : str
        Human-readable description of the problem.
    """


# ---------------------------------------------------------------------------
# Primitive functions
# ---------------------------------------------------------------------------


def feature_knn_mean_distance(
    queries: np.ndarray,
    refs: np.ndarray,
    k: int,
    *,
    loo: bool = False,
) -> np.ndarray:
    """For each query row, the mean Euclidean distance to its k nearest rows in ``refs``.

    Parameters
    ----------
    queries : np.ndarray
        Shape ``(n_queries, d)``.  Query feature vectors.
    refs : np.ndarray
        Shape ``(n_refs, d)``.  Reference feature vectors.
    k : int
        Number of nearest neighbours to average over.  Must satisfy
        ``1 <= k <= len(refs)``.
    loo : bool, optional
        Leave-one-out mode.  When ``True`` **and** ``queries.shape[0] == refs.shape[0]``
        (same number of rows), each query excludes its own index from the
        candidate neighbour set before selecting the k nearest.  This is used to
        score reference items against themselves without self-contamination.
        When ``queries.shape[0] != refs.shape[0]``, this flag has no effect.

    Returns
    -------
    np.ndarray
        Shape ``(n_queries,)``.  Per-query mean distance to k nearest references.

    Raises
    ------
    GateError
        If ``k < 1`` or ``k > len(refs)``.

    Notes
    -----
    LOO mechanism: a full ``(n_queries, n_refs)`` pairwise distance matrix is
    computed; when ``loo=True`` and ``n_queries == n_refs``, the diagonal
    entries are set to ``+inf`` so that index ``i`` is never selected as its
    own nearest neighbour.
    """
    n_refs = refs.shape[0]
    if k < 1:
        raise GateError(f"k must be >= 1; got k={k!r}.")
    if k > n_refs:
        raise GateError(
            f"k={k!r} exceeds the number of reference items ({n_refs}). "
            "Reduce k or provide more reference items."
        )

    queries = np.asarray(queries, dtype=np.float64)
    refs = np.asarray(refs, dtype=np.float64)

    # Pairwise squared Euclidean distances via (a-b)^2 = a^2 - 2ab + b^2
    # queries: (n_q, d), refs: (n_r, d)
    q_sq = np.sum(queries**2, axis=1, keepdims=True)  # (n_q, 1)
    r_sq = np.sum(refs**2, axis=1, keepdims=True)  # (n_r, 1)
    cross = queries @ refs.T  # (n_q, n_r)
    sq_dists = q_sq + r_sq.T - 2.0 * cross  # (n_q, n_r)
    # Clamp negative values to 0 (floating-point rounding)
    sq_dists = np.maximum(sq_dists, 0.0)
    dists = np.sqrt(sq_dists)  # (n_q, n_r)

    # LOO: mask out self-distances when n_queries == n_refs
    if loo and queries.shape[0] == n_refs:
        np.fill_diagonal(dists, np.inf)

    # Partial sort to find k nearest
    result = np.empty(queries.shape[0])
    if k == n_refs:
        # No need to partial-sort when using all refs (or all minus self when loo)
        # LOO case: diagonal is inf, so take k columns that are finite
        if loo and queries.shape[0] == n_refs:
            # After masking diagonal, each row has n_refs-1 finite distances
            # Use full sort (n_refs is manageable)
            sorted_dists = np.sort(dists, axis=1)  # infs will be last
            result = sorted_dists[:, :k].mean(axis=1)
        else:
            result = dists.mean(axis=1)
    else:
        # argpartition to get the k smallest indices per row
        part = np.argpartition(dists, k, axis=1)[:, :k]  # (n_q, k)
        # Gather the k smallest distances using advanced indexing
        row_idx = np.arange(queries.shape[0])[:, None]  # (n_q, 1)
        k_dists = dists[row_idx, part]  # (n_q, k)
        result = k_dists.mean(axis=1)

    return result


def local_residual(
    queries: np.ndarray,
    refs: np.ndarray,
    ref_errors: np.ndarray,
    k: int,
    *,
    loo: bool = False,
) -> np.ndarray:
    """For each query row, the median of ``ref_errors`` over its k nearest ``refs`` rows.

    Parameters
    ----------
    queries : np.ndarray
        Shape ``(n_queries, d)``.  Query feature vectors.
    refs : np.ndarray
        Shape ``(n_refs, d)``.  Reference feature vectors.
    ref_errors : np.ndarray
        Shape ``(n_refs,)``.  Measured base errors for each reference item.
    k : int
        Number of nearest neighbours whose errors to median.  Must satisfy
        ``1 <= k <= len(refs)``.
    loo : bool, optional
        Leave-one-out mode.  When ``True`` and ``n_queries == n_refs``, each
        query excludes its own index (diagonal of the distance matrix set to
        ``+inf``) before selecting the k nearest.  See module docstring for
        the full LOO mechanism description.

    Returns
    -------
    np.ndarray
        Shape ``(n_queries,)``.  Per-query median error of k nearest references.

    Raises
    ------
    GateError
        If ``k < 1`` or ``k > len(refs)``.
    """
    n_refs = refs.shape[0]
    if k < 1:
        raise GateError(f"k must be >= 1; got k={k!r}.")
    if k > n_refs:
        raise GateError(
            f"k={k!r} exceeds the number of reference items ({n_refs}). "
            "Reduce k or provide more reference items."
        )

    queries = np.asarray(queries, dtype=np.float64)
    refs = np.asarray(refs, dtype=np.float64)
    ref_errors = np.asarray(ref_errors, dtype=np.float64)

    # Pairwise distances
    q_sq = np.sum(queries**2, axis=1, keepdims=True)
    r_sq = np.sum(refs**2, axis=1, keepdims=True)
    cross = queries @ refs.T
    sq_dists = q_sq + r_sq.T - 2.0 * cross
    sq_dists = np.maximum(sq_dists, 0.0)
    dists = np.sqrt(sq_dists)

    if loo and queries.shape[0] == n_refs:
        np.fill_diagonal(dists, np.inf)

    # For each query, find k nearest and take median of their errors
    # argpartition for k nearest; ref_errors is 1-D so fancy index directly
    part = np.argpartition(dists, k, axis=1)[:, :k]  # (n_q, k)
    k_errors = ref_errors[part]  # (n_q, k) — errors of k nearest per query
    result = np.median(k_errors, axis=1)

    return result


def ecdf_normalize(values: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """ECDF rank of each value against ``reference``: fraction of reference <= value.

    The result is in ``[0, 1]``.  Ties are counted with ``<=`` (i.e. a value
    equal to reference items contributes those reference items to the count).

    Parameters
    ----------
    values : np.ndarray
        Shape ``(n,)``.  Values to normalize.
    reference : np.ndarray
        Shape ``(m,)``.  The reference distribution to compare against.

    Returns
    -------
    np.ndarray
        Shape ``(n,)``.  ECDF fraction in ``[0, 1]`` for each value.

    Notes
    -----
    This is the standard empirical CDF evaluated at ``values``:
    ``F(v) = (#reference <= v) / len(reference)``.  Deterministic; no RNG used.
    """
    values = np.asarray(values, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)
    n_ref = len(reference)
    # Broadcasting: (n_values, n_ref) -> count of refs <= each value
    # Use float to avoid overflow for large n_ref
    counts = np.sum(reference[np.newaxis, :] <= values[:, np.newaxis], axis=1)
    return counts.astype(np.float64) / n_ref


# ---------------------------------------------------------------------------
# TrustGate
# ---------------------------------------------------------------------------


@dataclass
class TrustGate:
    """Full trust gate combining R1 (feature-kNN) and R4 (local-residual).

    The gate score for a query is::

        R1  = feature_knn_mean_distance(query, ref_features, k)
        R4  = local_residual(query, ref_features, ref_errors, k)
        R1n = ecdf_normalize(R1, self.loo_r1)
        R4n = ecdf_normalize(R4, self.loo_r4)
        score = w * R1n + (1 - w) * R4n

    Higher score = ABSTAIN (less trustworthy); lower score = PREDICT.

    Do not construct directly; use :meth:`fit`.

    Parameters
    ----------
    k : int
        Number of nearest neighbours for both R1 and R4.
    w : float
        Weight on the R1 (feature-distance) component.  Must satisfy
        ``0 < w <= 1``.  ``w=0`` is invalid (use :class:`ResidualOnly`
        from ``alive.baselines.uq`` for the R4-only ablation).
    ref_features : np.ndarray
        Shape ``(n_refs, d)``.  Standardized reference feature matrix.
    ref_errors : np.ndarray
        Shape ``(n_refs,)``.  Measured base errors for each reference item.
    loo_r1 : np.ndarray
        Shape ``(n_refs,)``.  LOO R1 distances for the reference items.
        Used as the ECDF reference distribution for R1 normalization.
    loo_r4 : np.ndarray
        Shape ``(n_refs,)``.  LOO R4 residuals for the reference items.
        Used as the ECDF reference distribution for R4 normalization.
    """

    k: int
    w: float
    ref_features: np.ndarray
    ref_errors: np.ndarray
    loo_r1: np.ndarray = field(default_factory=lambda: np.empty(0))
    loo_r4: np.ndarray = field(default_factory=lambda: np.empty(0))

    @classmethod
    def fit(
        cls,
        ref_features: np.ndarray,
        ref_errors: np.ndarray,
        *,
        k: int,
        w: float,
    ) -> "TrustGate":
        """Fit the TrustGate by storing references and precomputing LOO distributions.

        Parameters
        ----------
        ref_features : np.ndarray
            Shape ``(n_refs, d)``.  Standardized reference feature matrix.
        ref_errors : np.ndarray
            Shape ``(n_refs,)``.  Measured base errors (energy distances) for
            each reference item.  These are the regression targets / risk labels
            for R4 computation.
        k : int
            Number of nearest neighbours.
        w : float
            Weight on the R1 component.  Must satisfy ``0 < w <= 1``.

        Returns
        -------
        TrustGate
            Fitted gate instance with ``loo_r1`` and ``loo_r4`` precomputed.

        Raises
        ------
        GateError
            If ``w <= 0`` or ``w > 1``.  ``w=0`` is not permitted because
            the R4-only ablation is the distinct :class:`~alive.baselines.uq.ResidualOnly`
            class; intermediate weights must be strictly positive.
        """
        if w <= 0.0 or w > 1.0:
            raise GateError(
                f"w must satisfy 0 < w <= 1; got w={w!r}. "
                "For the R4-only ablation (w=0), use ResidualOnly from alive.baselines.uq."
            )

        ref_features = np.asarray(ref_features, dtype=np.float64)
        ref_errors = np.asarray(ref_errors, dtype=np.float64)

        # Precompute LOO R1 and R4 distributions
        loo_r1 = feature_knn_mean_distance(ref_features, ref_features, k, loo=True)
        loo_r4 = local_residual(ref_features, ref_features, ref_errors, k, loo=True)

        return cls(
            k=k,
            w=w,
            ref_features=ref_features,
            ref_errors=ref_errors,
            loo_r1=loo_r1,
            loo_r4=loo_r4,
        )

    def score(self, query_features: np.ndarray) -> np.ndarray:
        """Compute the abstain score for one or more query feature vectors.

        Parameters
        ----------
        query_features : np.ndarray
            Shape ``(n_queries, d)``.  Standardized query feature vectors.

        Returns
        -------
        np.ndarray
            Shape ``(n_queries,)``.  Per-query abstain score in ``[0, 1]``.
            Higher = ABSTAIN; lower = PREDICT.
        """
        query_features = np.asarray(query_features, dtype=np.float64)
        r1 = feature_knn_mean_distance(query_features, self.ref_features, self.k)
        r4 = local_residual(query_features, self.ref_features, self.ref_errors, self.k)
        r1n = ecdf_normalize(r1, self.loo_r1)
        r4n = ecdf_normalize(r4, self.loo_r4)
        return self.w * r1n + (1.0 - self.w) * r4n

    def score_loo(self) -> np.ndarray:
        """LOO abstain scores for the reference items themselves.

        Computes R1 and R4 in LOO mode (each reference item excluded from
        its own neighbour set), then ECDF-normalizes against ``loo_r1`` and
        ``loo_r4`` respectively.

        This produces OOF-style (out-of-fold) scores for the reference bank
        items, used by Task 12 for OOF-style AURC diagnostics.

        Returns
        -------
        np.ndarray
            Shape ``(n_refs,)``.  Per-reference-item LOO abstain score in ``[0, 1]``.
        """
        r1n = ecdf_normalize(self.loo_r1, self.loo_r1)
        r4n = ecdf_normalize(self.loo_r4, self.loo_r4)
        return self.w * r1n + (1.0 - self.w) * r4n
