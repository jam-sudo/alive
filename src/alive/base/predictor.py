"""Frozen additive ridge base predictor with paired bootstrap ensemble.

Design
------
The base predictor fits a multi-output ridge regression model::

    W_a = (Phi^T Phi + a I)^{-1} Phi^T S

where:

- ``Phi`` (n, feat_dim) is the matrix of standardised perturbation features
  (one row per base_train perturbation that the feature bank carries).
- ``S`` (n, pca_dims) is the matrix of mean shifts in response space
  ``s_g = mean_g - control_mean``.
- ``a`` is the ridge regularisation strength chosen by fixed-fold CV.

There is **no intercept column** in ``Phi``.  Features are already
zero-mean-standardised (base_train statistics) and shifts are
control-relative, so the intercept is identically absorbed into the
response-space control mean.  This is the standard no-intercept ridge
formulation for standardised, centred features.

Leakage boundary
----------------
``fit_base_predictor`` reads ONLY ``store.read_controls()`` and
``store.read_unsealed(base_train_ids)``.  It never calls
``evaluate_sealed_once``.  After fitting, ``store.sealed_access_count``
must remain 0.

Determinism
-----------
- All arithmetic is performed in ``float64``.
- CV fold indices are derived from a ``numpy.random.default_rng(seed)``
  permutation of the base_train rows (stable; no Python ``hash()``).
- Bootstrap member seeds are derived as ``int(uint64(seed) + uint64(m + 1))``
  so the derivation is fully portable and independent of platform hash state.
- Identical inputs and seed → identical ``W``, alpha, ensemble, checksum.

Public API
----------
BaseModelError
    Raised when fit inputs are invalid (e.g. no usable base_train ids).
BasePredictor
    Frozen dataclass; the complete fitted artifact.
fit_base_predictor
    Build a :class:`BasePredictor` from a manifest, store, response space,
    and feature bank.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from alive.provenance import sha256_json
from alive.types import BasePrediction, Query

if TYPE_CHECKING:
    pass  # only used for string annotations below


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class BaseModelError(ValueError):
    """Raised when ``fit_base_predictor`` receives invalid inputs.

    Parameters
    ----------
    message : str
        Human-readable description of the problem.
    """


# ---------------------------------------------------------------------------
# BasePredictor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BasePredictor:
    """Frozen additive ridge base predictor with paired bootstrap ensemble.

    Do not construct directly; use :func:`fit_base_predictor`.

    Parameters
    ----------
    feature_dim : int
        Dimensionality of the standardised perturbation feature vectors.
    pca_dims : int
        Dimensionality of the response space (PCA dimensions).
    control_mean : np.ndarray
        Shape ``(pca_dims,)``.  Mean of the transformed control population
        in response space.  Used as the reference point for all predictions.
    transformed_control : np.ndarray
        Shape ``(n_control, pca_dims)``.  The full response-space control
        population; each prediction shifts every cell by the predicted mean
        shift, preserving the control population structure.
    weights : np.ndarray
        Shape ``(feature_dim, pca_dims)``.  Ridge regression weights ``W``
        fitted at ``chosen_alpha`` on all base_train rows.
    chosen_alpha : float
        Ridge regularisation strength chosen by the lowest-mean-CV-MSE
        criterion; ties broken by the smallest alpha.
    cv_scores : dict[float, float]
        Mapping ``alpha -> mean 5-fold (or cv_folds-fold) CV MSE``, one
        entry per value in the ``ridge_grid`` passed to the builder.
    ensemble_weights : np.ndarray
        Shape ``(ensemble_members, feature_dim, pca_dims)``.  Per-member
        weights fitted on paired bootstrap resamples of ``(Phi, S)`` at
        ``chosen_alpha``.
    fit_perturbation_ids : tuple[str, ...]
        Sorted tuple of base_train perturbation ids that were actually used
        (the feature bank must carry them; missing ids are excluded).
    seed : int
        The seed that was passed to :func:`fit_base_predictor`; it drives
        both CV fold assignment and bootstrap member seeds.

    Notes
    -----
    **No intercept.** Features are standardised (zero-mean over base_train)
    and shifts are control-relative, so an intercept would be identically
    zero and is omitted from the ridge normal equations.

    **Paired bootstrap.** Each ensemble member ``m`` draws the same index
    array ``idx`` from ``numpy.random.default_rng(member_seed).integers``
    and uses it to resample BOTH ``Phi`` and ``S`` row-wise, ensuring that
    the feature-shift pairing is preserved.
    """

    feature_dim: int
    pca_dims: int
    control_mean: np.ndarray  # (pca_dims,)
    transformed_control: np.ndarray  # (n_control, pca_dims)
    weights: np.ndarray  # W: (feature_dim, pca_dims)
    chosen_alpha: float
    cv_scores: dict[float, float]  # alpha -> mean CV MSE
    ensemble_weights: np.ndarray  # (ensemble_members, feature_dim, pca_dims)
    fit_perturbation_ids: tuple[str, ...]  # sorted, base_train ids actually used
    seed: int

    # ------------------------------------------------------------------
    # Prediction helpers
    # ------------------------------------------------------------------

    def predicted_shift(self, features: np.ndarray) -> np.ndarray:
        """Compute the predicted mean-shift vector for a feature vector.

        Parameters
        ----------
        features : np.ndarray
            Standardised 1-D feature vector of shape ``(feature_dim,)``.

        Returns
        -------
        np.ndarray
            Shape ``(pca_dims,)``.  The predicted shift ``features @ W``.
        """
        return np.asarray(features, dtype=np.float64) @ self.weights

    def predicted_mean(self, features: np.ndarray) -> np.ndarray:
        """Compute the predicted post-perturbation population mean.

        Parameters
        ----------
        features : np.ndarray
            Standardised 1-D feature vector of shape ``(feature_dim,)``.

        Returns
        -------
        np.ndarray
            Shape ``(pca_dims,)``.  Equal to ``control_mean + predicted_shift``.
        """
        return self.control_mean + self.predicted_shift(features)

    def predict(self, query: Query) -> BasePrediction:
        """Generate the full base prediction for one perturbation query.

        The predicted cell population is the control population translated
        by the predicted mean shift::

            predicted_cells = transformed_control + features @ W   (broadcast)

        The ensemble member means are::

            ensemble_member_means[m] = control_mean + features @ W_m

        Parameters
        ----------
        query : Query
            A :class:`~alive.types.Query` carrying ``perturbation_id`` and
            a standardised ``features`` vector.

        Returns
        -------
        BasePrediction
            A :class:`~alive.types.BasePrediction` with ``predicted_cells``
            of shape ``(n_control, pca_dims)`` and ``ensemble_member_means``
            of shape ``(ensemble_members, pca_dims)``.
        """
        phi = np.asarray(query.features, dtype=np.float64)
        shift = self.predicted_shift(phi)  # (pca_dims,)

        # Broadcast shift across all control cells: (n_control, pca_dims)
        predicted_cells = self.transformed_control + shift

        # Ensemble member means: (ensemble_members, pca_dims)
        # ensemble_weights: (M, feat_dim, pca_dims), phi: (feat_dim,) -> (M, pca_dims)
        # einsum 'mfp,f->mp' contracts the feature dimension.
        member_shifts = np.einsum("mfp,f->mp", self.ensemble_weights, phi)
        ensemble_member_means = self.control_mean + member_shifts  # (M, pca_dims)

        return BasePrediction(
            perturbation_id=query.perturbation_id,
            predicted_cells=predicted_cells,
            ensemble_member_means=ensemble_member_means,
        )

    # ------------------------------------------------------------------
    # Checksum
    # ------------------------------------------------------------------

    @cached_property
    def checksum(self) -> str:
        """Stable SHA-256 over all fitted arrays and scalars.

        The digest covers: ``feature_dim``, ``pca_dims``, ``control_mean``,
        ``transformed_control``, ``weights``, ``chosen_alpha``, ``cv_scores``
        (sorted by alpha), ``ensemble_weights``, ``fit_perturbation_ids``,
        and ``seed``.  No non-deterministic fields are included.

        Returns
        -------
        str
            64-character lowercase hexadecimal SHA-256 digest.
        """
        payload: dict = {
            "feature_dim": int(self.feature_dim),
            "pca_dims": int(self.pca_dims),
            "control_mean": self.control_mean.astype(np.float64).tolist(),
            "transformed_control": self.transformed_control.astype(np.float64).tolist(),
            "weights": self.weights.astype(np.float64).tolist(),
            "chosen_alpha": repr(float(self.chosen_alpha)),
            "cv_scores": {
                repr(float(a)): repr(float(v)) for a, v in sorted(self.cv_scores.items())
            },
            "ensemble_weights": self.ensemble_weights.astype(np.float64).tolist(),
            "fit_perturbation_ids": list(self.fit_perturbation_ids),
            "seed": int(self.seed),
        }
        return sha256_json(payload)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def write(self, path: str | Path) -> None:
        """Write the predictor to disk deterministically.

        Writes two files:

        - ``{path}.npz`` — uncompressed numpy archive of all fitted arrays
          (``float64`` / ``int64`` for exact round-trip).
        - ``{path}.json`` — scalar metadata, cv_scores, ids, and checksum.

        Parameters
        ----------
        path : str or Path
            Base path (without extension).  Parent directory must exist.
        """
        path = Path(path)
        np.savez(
            str(path) + ".npz",
            control_mean=self.control_mean.astype(np.float64),
            transformed_control=self.transformed_control.astype(np.float64),
            weights=self.weights.astype(np.float64),
            ensemble_weights=self.ensemble_weights.astype(np.float64),
        )
        meta: dict = {
            "feature_dim": int(self.feature_dim),
            "pca_dims": int(self.pca_dims),
            "chosen_alpha": float(self.chosen_alpha),
            "cv_scores": {float(a): float(v) for a, v in self.cv_scores.items()},
            "fit_perturbation_ids": list(self.fit_perturbation_ids),
            "seed": int(self.seed),
            "checksum": self.checksum,
        }
        path.with_suffix(".json").write_text(
            json.dumps(meta, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: str | Path) -> "BasePredictor":
        """Reconstruct a :class:`BasePredictor` from files written by :meth:`write`.

        Parameters
        ----------
        path : str or Path
            Base path (without extension) as passed to :meth:`write`.

        Returns
        -------
        BasePredictor
            The reconstructed predictor.  Its :attr:`checksum` is recomputed
            and must match the stored value.

        Raises
        ------
        BaseModelError
            If the stored checksum does not match the recomputed checksum.
        """
        path = Path(path)
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        npz = np.load(str(path) + ".npz")

        predictor = cls(
            feature_dim=int(meta["feature_dim"]),
            pca_dims=int(meta["pca_dims"]),
            control_mean=np.asarray(npz["control_mean"], dtype=np.float64),
            transformed_control=np.asarray(npz["transformed_control"], dtype=np.float64),
            weights=np.asarray(npz["weights"], dtype=np.float64),
            chosen_alpha=float(meta["chosen_alpha"]),
            cv_scores={float(a): float(v) for a, v in meta["cv_scores"].items()},
            ensemble_weights=np.asarray(npz["ensemble_weights"], dtype=np.float64),
            fit_perturbation_ids=tuple(meta["fit_perturbation_ids"]),
            seed=int(meta["seed"]),
        )

        stored = meta["checksum"]
        recomputed = predictor.checksum
        if recomputed != stored:
            raise BaseModelError(
                f"BasePredictor checksum mismatch: stored {stored!r} != recomputed "
                f"{recomputed!r}.  The serialised file may have been modified."
            )
        return predictor


# ---------------------------------------------------------------------------
# Fit procedure
# ---------------------------------------------------------------------------


def _ridge_solve(Phi: np.ndarray, S: np.ndarray, alpha: float) -> np.ndarray:
    """Solve the multi-output ridge normal equations.

    Computes ``W = (Phi^T Phi + alpha * I)^{-1} Phi^T S`` via
    ``numpy.linalg.solve`` (Cholesky / LU decomposition internally;
    no explicit matrix inverse).

    Parameters
    ----------
    Phi : np.ndarray
        Shape ``(n, feat_dim)`` feature matrix.
    S : np.ndarray
        Shape ``(n, pca_dims)`` target-shift matrix.
    alpha : float
        Ridge regularisation strength (must be > 0).

    Returns
    -------
    np.ndarray
        Shape ``(feat_dim, pca_dims)`` weight matrix ``W``.
    """
    feat_dim = Phi.shape[1]
    A = Phi.T @ Phi + alpha * np.eye(feat_dim, dtype=np.float64)
    b = Phi.T @ S
    return np.linalg.solve(A, b)


def _cv_fold_indices(n: int, n_folds: int, rng: np.random.Generator) -> list[np.ndarray]:
    """Return a list of *n_folds* validation-index arrays via a seeded permutation.

    The permuted row indices are partitioned into *n_folds* roughly equal
    chunks.  The partition uses ``np.array_split`` which spreads the
    remainder across the first ``n % n_folds`` folds.

    Parameters
    ----------
    n : int
        Number of training rows.
    n_folds : int
        Number of CV folds.
    rng : np.random.Generator
        Seeded RNG (consumed here; caller must not reuse for other purposes).

    Returns
    -------
    list[np.ndarray]
        One validation-index array per fold, in partition order.
    """
    perm = rng.permutation(n)
    return [chunk for chunk in np.array_split(perm, n_folds)]


def fit_base_predictor(
    manifest: object,
    store: object,
    response_space: object,
    feature_bank: object,
    *,
    ridge_grid: Sequence[float],
    cv_folds: int,
    ensemble_members: int,
    seed: int,
) -> BasePredictor:
    """Fit the frozen additive ridge base predictor.

    This function is the only entry point for constructing a
    :class:`BasePredictor`.  It follows the exact fit procedure specified
    below and enforces the leakage boundary.

    **Leakage boundary (hard).**  Only ``store.read_controls()`` and
    ``store.read_unsealed(base_train_ids)`` are ever called.
    ``evaluate_sealed_once`` is never called; the ``sealed_access_count``
    of the store must remain 0 after this function returns.

    **Fit procedure:**

    1. Obtain the transformed control population and its mean.
    2. For each base_train id that the feature bank carries (sorted order):
       transform its population, compute its mean, form the shift
       ``s_g = mean_g - control_mean``, and obtain its standardised feature
       vector ``phi_g``.  Stack into ``Phi`` and ``S``.
    3. Select alpha by fixed ``cv_folds``-fold CV over ``Phi`` / ``S``
       (fold assignment from a seeded permutation of rows).  For each alpha,
       compute the mean MSE across all held-out rows and all PCA dims.
       Choose the alpha with the lowest mean CV MSE; ties broken by the
       smallest alpha.
    4. Refit ``W`` on all rows at the chosen alpha.
    5. Build ``ensemble_members`` bootstrap members using paired resampling
       (same index array for both ``Phi`` and ``S`` rows), each fitted at
       the chosen alpha.

    Parameters
    ----------
    manifest : SplitManifest-like
        Must have ``ids_for("base_train") -> Sequence[str]``.
    store : OutcomeStore-like
        Must have ``read_controls()`` and ``read_unsealed(ids)``.
        Must never call ``evaluate_sealed_once`` (leakage boundary).
    response_space : ResponseSpace-like
        Must have ``transform(cells: np.ndarray) -> np.ndarray``.
    feature_bank : FeatureBank-like
        Must have ``has(gene: str) -> bool`` and
        ``standardized_vector(gene: str) -> np.ndarray``.
    ridge_grid : Sequence[float]
        Non-empty sequence of regularisation strengths to CV over.
    cv_folds : int
        Number of folds for inner CV (must be >= 2).
    ensemble_members : int
        Number of paired-bootstrap ensemble members (must be >= 1).
    seed : int
        Master seed.  Drives CV fold permutation and per-member bootstrap
        seeds.  The per-member seed for member ``m`` is::

            int(uint64(seed) + uint64(m + 1))

        This derivation is fully portable (no Python ``hash()``) and stable
        across platforms.

    Returns
    -------
    BasePredictor
        Frozen predictor artifact.

    Raises
    ------
    BaseModelError
        If no base_train perturbation ids are present in the feature bank
        (after filtering missing ids), or if ``ridge_grid`` is empty, or if
        ``cv_folds < 2``, or if the number of usable base_train rows ``n``
        is less than ``cv_folds`` (CV fold assignment is undefined).
    """
    # ------------------------------------------------------------------
    # Validate inputs
    # ------------------------------------------------------------------
    ridge_grid_list = list(ridge_grid)
    if not ridge_grid_list:
        raise BaseModelError("ridge_grid must be non-empty.")
    if cv_folds < 2:
        raise BaseModelError(f"cv_folds must be >= 2; got {cv_folds!r}.")
    if ensemble_members < 1:
        raise BaseModelError(f"ensemble_members must be >= 1; got {ensemble_members!r}.")

    # ------------------------------------------------------------------
    # Step 1: Control population
    # ------------------------------------------------------------------
    ctrl_pop = store.read_controls()
    ctrl_cells = np.asarray(ctrl_pop.cells, dtype=np.float64)
    transformed_control = np.asarray(
        response_space.transform(ctrl_cells), dtype=np.float64
    )  # (n_control, pca_dims)
    control_mean = transformed_control.mean(axis=0)  # (pca_dims,)
    pca_dims = control_mean.shape[0]

    # ------------------------------------------------------------------
    # Step 2: Build Phi and S from base_train (sorted id order)
    # ------------------------------------------------------------------
    base_train_ids = sorted(manifest.ids_for("base_train"))

    phi_rows: list[np.ndarray] = []
    s_rows: list[np.ndarray] = []
    used_ids: list[str] = []

    for gid in base_train_ids:
        if not feature_bank.has(gid):
            continue  # skip missing
        pop_dict = store.read_unsealed([gid])
        pop_cells = np.asarray(pop_dict[gid].cells, dtype=np.float64)
        t = np.asarray(response_space.transform(pop_cells), dtype=np.float64)
        mean_g = t.mean(axis=0)  # (pca_dims,)
        s_g = mean_g - control_mean  # (pca_dims,)
        phi_g = np.asarray(feature_bank.standardized_vector(gid), dtype=np.float64)
        phi_rows.append(phi_g)
        s_rows.append(s_g)
        used_ids.append(gid)

    if not used_ids:
        raise BaseModelError(
            "No base_train perturbation ids are present in the feature bank. "
            "Ensure the feature bank covers at least one base_train perturbation."
        )

    Phi = np.array(phi_rows, dtype=np.float64)  # (n, feat_dim)
    S = np.array(s_rows, dtype=np.float64)  # (n, pca_dims)
    n, feat_dim = Phi.shape

    if n < cv_folds:
        raise BaseModelError(
            f"Number of usable base_train rows ({n}) is less than cv_folds ({cv_folds}). "
            "CV fold assignment is undefined when n < cv_folds. "
            "Reduce cv_folds or provide more base_train perturbations with feature vectors."
        )

    # ------------------------------------------------------------------
    # Step 3: CV alpha selection
    # ------------------------------------------------------------------
    # CV fold indices derived from a seeded permutation (stable, no hash())
    cv_rng = np.random.default_rng(seed)
    fold_val_indices = _cv_fold_indices(n, cv_folds, cv_rng)

    cv_scores: dict[float, float] = {}
    for alpha in ridge_grid_list:
        mse_accum = 0.0
        n_val_total = 0
        for fold_idx in range(cv_folds):
            val_idx = fold_val_indices[fold_idx]
            train_idx = np.concatenate(
                [fold_val_indices[k] for k in range(cv_folds) if k != fold_idx]
            )
            Phi_tr = Phi[train_idx]
            S_tr = S[train_idx]
            Phi_val = Phi[val_idx]
            S_val = S[val_idx]

            W_cv = _ridge_solve(Phi_tr, S_tr, alpha)
            S_pred = Phi_val @ W_cv  # (n_val, pca_dims)
            residuals = S_val - S_pred  # (n_val, pca_dims)
            mse_accum += float(np.sum(residuals**2))
            n_val_total += residuals.size

        cv_scores[float(alpha)] = mse_accum / n_val_total if n_val_total > 0 else 0.0

    # Choose alpha: lowest CV MSE; ties broken by smallest alpha
    chosen_alpha = min(cv_scores, key=lambda a: (cv_scores[a], a))

    # ------------------------------------------------------------------
    # Step 4: Refit W on all rows at chosen alpha
    # ------------------------------------------------------------------
    weights = _ridge_solve(Phi, S, chosen_alpha)  # (feat_dim, pca_dims)

    # ------------------------------------------------------------------
    # Step 5: Paired bootstrap ensemble
    # ------------------------------------------------------------------
    # Per-member seed: int(uint64(seed) + uint64(m + 1))
    # This derivation avoids Python hash() and is portable across platforms.
    ensemble_weights_list: list[np.ndarray] = []
    seed_u64 = np.uint64(seed)
    for m in range(ensemble_members):
        member_seed = int(np.uint64(seed_u64 + np.uint64(m + 1)))
        rng_m = np.random.default_rng(member_seed)
        idx = rng_m.integers(0, n, size=n)  # bootstrap resample indices
        # Paired: same idx for BOTH Phi and S
        Phi_m = Phi[idx]
        S_m = S[idx]
        W_m = _ridge_solve(Phi_m, S_m, chosen_alpha)  # (feat_dim, pca_dims)
        ensemble_weights_list.append(W_m)

    ensemble_weights = np.stack(ensemble_weights_list, axis=0)  # (M, feat_dim, pca_dims)

    return BasePredictor(
        feature_dim=feat_dim,
        pca_dims=pca_dims,
        control_mean=control_mean,
        transformed_control=transformed_control,
        weights=weights,
        chosen_alpha=chosen_alpha,
        cv_scores=cv_scores,
        ensemble_weights=ensemble_weights,
        fit_perturbation_ids=tuple(sorted(used_ids)),
        seed=seed,
    )
