"""OOF method development, MethodLock, and the preregistered futility rule.

This module is Task 12 Deliverables B and C.  It operates on
**method_development data ONLY**: the per-perturbation features, measured base
errors, and ensemble means.  It never reads the outcome store and never sees
sealed or conformal data — by construction, the public functions take only dev
arrays, so there is no channel through which sealed/conformal outcomes could
influence any result here.

Normalization convention (dev-risk scale)
-----------------------------------------
``mu = mean(dev_errors)`` is computed ONCE (the fixed method_development cohort
mean; :class:`~alive.metrics.selective.MetricError` if ``mu <= 0``).  Every AURC
and every delta in this module is on the dev-normalized scale
``norm_errors = dev_errors / mu``.  ``delta_min = 0.01`` is on this same scale.

Out-of-fold (OOF) development
-----------------------------
For each method and each hyperparameter combo, and for each registered seed:

1. Build a deterministic ``cv_folds``-fold partition of the ``n`` dev rows from
   the seed (permute ``range(n)`` with ``default_rng(seed)``, then
   :func:`numpy.array_split`).
2. For each fold: FIT the method's scorer on the *training* rows
   (``dev_features``/``dev_errors`` of the other folds) and SCORE the held-out
   fold — assembling a length-``n`` OOF score vector (each row scored from when
   it was held out).  :class:`~alive.baselines.uq.EnsembleDisagreement` needs no
   fitting and scores each row directly from its ensemble means; it is still run
   under every seed for uniform aggregation (identical across seeds — fine).

**Seed aggregation:** the method's OOF score per perturbation is the MEAN over
the registered seeds of that perturbation's OOF score (one vector per
method+combo).  The combo's ``oof_aurc`` is ``aurc(norm_errors, aggregated)``.

**Selection:** the combo with the LOWEST ``oof_aurc`` wins.  Tie-break:

- gate: larger ``w`` first, then smaller ``k``;
- residual_only: smaller ``k``;
- ridge_error: smaller ``alpha``;
- gbm_error: fewer ``n_estimators``.

Futility rule (§7.1)
--------------------
Reference is the gate.  Using the SELECTED gate's and each comparator's
seed-aggregated OOF scores plus ``norm_errors``, compute the simultaneous 90%
UPPER bounds on the deltas ``AURC[comparator] - AURC[gate]`` via
:func:`alive.eval.bootstrap.simultaneous_delta_bounds`.  Then::

    status = FUTILITY_STOPPED if any(upper_bounds[c] <= delta_min) else CONTINUE_CONFIRMATORY

The boundary is ``<=`` (equality stops).  Confirmatory must beat ALL
comparators; failing to plausibly beat ANY by ``delta_min`` ⇒ futile.  There is
no point-estimate override and no visual inspection — purely the bound rule.

Public API
----------
DevelopError
    Raised for invalid inputs / serialisation problems.
MethodLock
    Frozen record of the developed methods and their selected configs.
develop_methods(...)
    Run the OOF development and return a :class:`MethodLock`.
FutilityDecision
    Frozen record of the preregistered futility decision.
decide_futility(...)
    Apply the futility rule to a :class:`MethodLock`.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from alive.baselines.uq import (
    EnsembleDisagreement,
    GbmErrorRegressor,
    NearestFeatureDistance,
    ResidualOnly,
    RidgeErrorRegressor,
)
from alive.eval.bootstrap import simultaneous_delta_bounds
from alive.gate.recoverability import TrustGate
from alive.metrics.selective import aurc, normalize_by_mean
from alive.provenance import sha256_json
from alive.types import OperationalStatus

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The methods evaluated, in canonical order.
METHOD_IDS: tuple[str, ...] = (
    "gate",
    "nearest_feature",
    "ensemble_disagreement",
    "ridge_error",
    "gbm_error",
    "residual_only",
)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class DevelopError(ValueError):
    """Raised for invalid method-development inputs or serialisation problems.

    Parameters
    ----------
    message : str
        Human-readable description of the problem.
    """


# ---------------------------------------------------------------------------
# Deterministic CV fold partition
# ---------------------------------------------------------------------------


def _fold_partition(n: int, cv_folds: int, seed: int) -> list[np.ndarray]:
    """Deterministic ``cv_folds``-fold partition of ``range(n)`` from ``seed``.

    Permutes ``range(n)`` with ``numpy.random.default_rng(seed)`` and splits the
    permutation into ``cv_folds`` near-equal contiguous folds via
    :func:`numpy.array_split`.

    Parameters
    ----------
    n : int
        Number of rows.
    cv_folds : int
        Number of folds (``>= 2`` and ``<= n``).
    seed : int
        Seed for the permutation.

    Returns
    -------
    list[np.ndarray]
        ``cv_folds`` integer arrays of held-out row indices (disjoint, union is
        ``range(n)``).

    Raises
    ------
    DevelopError
        If ``cv_folds < 2`` or ``cv_folds > n``.
    """
    if cv_folds < 2:
        raise DevelopError(f"cv_folds must be >= 2; got {cv_folds!r}.")
    if cv_folds > n:
        raise DevelopError(
            f"cv_folds={cv_folds!r} exceeds the number of dev rows ({n}). "
            "Use fewer folds or provide more method-development perturbations."
        )
    rng = np.random.default_rng(seed)
    perm = rng.permutation(n)
    return [np.asarray(f, dtype=int) for f in np.array_split(perm, cv_folds)]


# ---------------------------------------------------------------------------
# Per-method OOF scoring under a single seed
# ---------------------------------------------------------------------------


def _oof_scores_one_seed(
    method: str,
    params: Mapping,
    dev_features: np.ndarray,
    dev_errors: np.ndarray,
    dev_ensemble_means: np.ndarray,
    *,
    cv_folds: int,
    seed: int,
) -> np.ndarray:
    """Assemble the length-n OOF score vector for one method+combo under one seed.

    Each row is scored from the fold in which it was held out, after fitting the
    method on the remaining (training) folds.  All sklearn calls are wrapped to
    keep test output pristine.

    Parameters
    ----------
    method : str
        One of :data:`METHOD_IDS`.
    params : Mapping
        Hyperparameters for this combo (method-specific keys).
    dev_features : np.ndarray
        Shape ``(n, feat_dim)``.
    dev_errors : np.ndarray
        Shape ``(n,)`` measured base errors (also the fit targets / R4 labels).
    dev_ensemble_means : np.ndarray
        Shape ``(n, n_members, pca_dims)``.
    cv_folds : int
        Number of folds.
    seed : int
        Seed for the fold partition (and the GBM random_state).

    Returns
    -------
    np.ndarray
        Shape ``(n,)`` OOF scores (higher = abstain).
    """
    n = dev_features.shape[0]
    out = np.full(n, np.nan, dtype=np.float64)
    folds = _fold_partition(n, cv_folds, seed)

    for held in folds:
        train_mask = np.ones(n, dtype=bool)
        train_mask[held] = False
        train_idx = np.flatnonzero(train_mask)
        Xtr = dev_features[train_idx]
        etr = dev_errors[train_idx]
        Xte = dev_features[held]

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if method == "gate":
                scorer = TrustGate.fit(Xtr, etr, k=params["k"], w=params["w"])
                out[held] = scorer.score(Xte)
            elif method == "residual_only":
                scorer = ResidualOnly().fit(Xtr, etr, k=params["k"])
                out[held] = scorer.score(Xte)
            elif method == "nearest_feature":
                scorer = NearestFeatureDistance().fit(Xtr, etr)
                out[held] = scorer.score(Xte)
            elif method == "ridge_error":
                scorer = RidgeErrorRegressor().fit(Xtr, etr, alpha=params["alpha"])
                out[held] = scorer.score(Xte)
            elif method == "gbm_error":
                scorer = GbmErrorRegressor().fit(
                    Xtr, etr, n_estimators=params["n_estimators"], seed=seed
                )
                out[held] = scorer.score(Xte)
            elif method == "ensemble_disagreement":
                # Fit-free, fold-independent: score the held-out rows directly
                # from their ensemble means.
                scorer = EnsembleDisagreement().fit(Xtr, etr)
                out[held] = scorer.score(dev_ensemble_means[held])
            else:  # pragma: no cover - guarded by caller
                raise DevelopError(f"Unknown method {method!r}.")

    return out


# ---------------------------------------------------------------------------
# Hyperparameter grids per method
# ---------------------------------------------------------------------------


def _combos_for(
    method: str,
    *,
    k_grid: Sequence[int],
    feature_weight_grid: Sequence[float],
    ridge_grid: Sequence[float],
    gbm_estimators_grid: Sequence[int],
) -> list[dict]:
    """Enumerate the hyperparameter combos for ``method`` (method-specific).

    Returns
    -------
    list[dict]
        One dict of hyperparameters per combo.
    """
    if method == "gate":
        return [{"k": int(k), "w": float(w)} for k in k_grid for w in feature_weight_grid]
    if method == "residual_only":
        return [{"k": int(k)} for k in k_grid]
    if method == "nearest_feature":
        return [{}]
    if method == "ensemble_disagreement":
        return [{}]
    if method == "ridge_error":
        return [{"alpha": float(a)} for a in ridge_grid]
    if method == "gbm_error":
        return [{"n_estimators": int(t)} for t in gbm_estimators_grid]
    raise DevelopError(f"Unknown method {method!r}.")  # pragma: no cover


def _tiebreak_key(method: str, row: Mapping) -> tuple:
    """Tie-break sort key (smaller = preferred) among combos with equal AURC.

    - gate: larger ``w`` first (negate), then smaller ``k``.
    - residual_only: smaller ``k``.
    - ridge_error: smaller ``alpha``.
    - gbm_error: fewer ``n_estimators``.
    - others: no hyperparameters → constant.
    """
    if method == "gate":
        return (-row["w"], row["k"])
    if method == "residual_only":
        return (row["k"],)
    if method == "ridge_error":
        return (row["alpha"],)
    if method == "gbm_error":
        return (row["n_estimators"],)
    return (0,)


# ---------------------------------------------------------------------------
# MethodLock
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MethodLock:
    """Frozen record of the OOF-developed methods and their selected configs.

    Parameters
    ----------
    method_ids : tuple[str, ...]
        The methods evaluated (canonical order :data:`METHOD_IDS`).
    selected_params : dict[str, dict]
        Method → chosen hyperparameters (the OOF-AURC argmin, after tie-break).
    search_table : dict[str, list[dict]]
        Method → list of ``{**params, "oof_aurc": float}`` rows, one per combo.
    oof_scores : dict[str, np.ndarray]
        Method → ``(n,)`` seed-aggregated OOF score of the SELECTED config.
    oof_aurc : dict[str, float]
        Method → AURC of the selected config (dev-normalized).
    dev_ids : tuple[str, ...]
        The method-development perturbation ids (sorted, row-aligned).
    cv_folds : int
        Number of CV folds used.
    registered_seeds : tuple[int, ...]
        The registered seeds aggregated over.
    config_sha256 : str
        SHA-256 of the resolved config (provenance link).
    """

    method_ids: tuple[str, ...]
    selected_params: dict[str, dict]
    search_table: dict[str, list[dict]]
    oof_scores: dict[str, np.ndarray]
    oof_aurc: dict[str, float]
    dev_ids: tuple[str, ...]
    cv_folds: int
    registered_seeds: tuple[int, ...]
    config_sha256: str

    # ------------------------------------------------------------------
    # Checksum
    # ------------------------------------------------------------------

    @cached_property
    def checksum(self) -> str:
        """Stable SHA-256 over the full content of this lock (canonical JSON).

        The digest covers the selected params, the full search table, the
        seed-aggregated OOF scores (rounded to a fixed precision for stable
        cross-platform serialisation), the per-method OOF AURCs, dev ids,
        folds, seeds, and the config hash.  Two locks developed from identical
        dev inputs share the same checksum.

        Returns
        -------
        str
            Lowercase hex-encoded SHA-256 digest.
        """
        return sha256_json(self._canonical())

    def _canonical(self) -> dict:
        """Canonical, JSON-serialisable content used for checksum and write()."""
        return {
            "method_ids": list(self.method_ids),
            "selected_params": {m: self.selected_params[m] for m in self.method_ids},
            "search_table": {
                m: [{k: _round_for_json(v) for k, v in row.items()} for row in self.search_table[m]]
                for m in self.method_ids
            },
            "oof_scores": {
                m: [_round_for_json(float(x)) for x in self.oof_scores[m]] for m in self.method_ids
            },
            "oof_aurc": {m: _round_for_json(float(self.oof_aurc[m])) for m in self.method_ids},
            "dev_ids": list(self.dev_ids),
            "cv_folds": int(self.cv_folds),
            "registered_seeds": list(self.registered_seeds),
            "config_sha256": self.config_sha256,
        }

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def write(self, path: str | Path) -> None:
        """Write the lock to ``{path}.json`` deterministically.

        Parameters
        ----------
        path : str or Path
            Base path (``.json`` suffix is added).  Parent directory must exist.
        """
        path = Path(path)
        payload = self._canonical()
        payload["checksum"] = self.checksum
        path.with_suffix(".json").write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: str | Path) -> "MethodLock":
        """Reconstruct a :class:`MethodLock` from a file written by :meth:`write`.

        Parameters
        ----------
        path : str or Path
            Base path (without ``.json`` suffix) as passed to :meth:`write`.

        Returns
        -------
        MethodLock
            The reconstructed lock; its checksum is recomputed and must match
            the stored value.

        Raises
        ------
        DevelopError
            If the file is malformed or the stored checksum does not match.
        """
        path = Path(path)
        try:
            raw = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise DevelopError(f"Failed to read MethodLock from {path!r}: {exc}") from exc

        try:
            method_ids = tuple(raw["method_ids"])
            lock = cls(
                method_ids=method_ids,
                selected_params={m: dict(raw["selected_params"][m]) for m in method_ids},
                search_table={m: [dict(row) for row in raw["search_table"][m]] for m in method_ids},
                oof_scores={
                    m: np.asarray(raw["oof_scores"][m], dtype=np.float64) for m in method_ids
                },
                oof_aurc={m: float(raw["oof_aurc"][m]) for m in method_ids},
                dev_ids=tuple(raw["dev_ids"]),
                cv_folds=int(raw["cv_folds"]),
                registered_seeds=tuple(int(s) for s in raw["registered_seeds"]),
                config_sha256=raw["config_sha256"],
            )
            stored = raw["checksum"]
        except (KeyError, TypeError) as exc:
            raise DevelopError(f"MethodLock JSON is missing required field: {exc}") from exc

        if lock.checksum != stored:
            raise DevelopError(
                f"MethodLock checksum mismatch: stored {stored!r} != recomputed "
                f"{lock.checksum!r}.  The serialised file may have been modified."
            )
        return lock


def _round_for_json(value):
    """Round floats to a fixed precision for stable cross-platform serialisation.

    Leaves non-floats untouched.  17 significant digits round-trips IEEE-754
    doubles exactly, but we use ``repr``-equivalent rounding via Python's float
    so that ``write``→``read``→``checksum`` is stable.
    """
    if isinstance(value, float):
        # Round to 12 decimals: more than enough for AURC/scores in [0, ~few],
        # while immune to last-bit platform jitter.
        return round(value, 12)
    if isinstance(value, (np.floating,)):
        return round(float(value), 12)
    if isinstance(value, (np.integer,)):
        return int(value)
    return value


# ---------------------------------------------------------------------------
# develop_methods
# ---------------------------------------------------------------------------


def develop_methods(
    dev_ids: Sequence[str],
    dev_features: np.ndarray,
    dev_errors: np.ndarray,
    dev_ensemble_means: np.ndarray,
    *,
    cv_folds: int,
    k_grid: Sequence[int],
    feature_weight_grid: Sequence[float],
    ridge_grid: Sequence[float],
    gbm_estimators_grid: Sequence[int],
    registered_seeds: Sequence[int],
    config_sha256: str,
) -> MethodLock:
    """Run OOF method development on method_development data and lock the result.

    Parameters
    ----------
    dev_ids : Sequence[str]
        ``n`` perturbation ids (sorted, row-aligned with the arrays).
    dev_features : np.ndarray
        Shape ``(n, feat_dim)`` standardized perturbation features.
    dev_errors : np.ndarray
        Shape ``(n,)`` measured base error per perturbation (the risk).
    dev_ensemble_means : np.ndarray
        Shape ``(n, n_members, pca_dims)`` per-perturbation ensemble means.
    cv_folds : int
        Number of CV folds.
    k_grid : Sequence[int]
        Candidate ``k`` values (gate, residual_only).
    feature_weight_grid : Sequence[float]
        Candidate gate ``w`` values.
    ridge_grid : Sequence[float]
        Candidate ridge ``alpha`` values.
    gbm_estimators_grid : Sequence[int]
        Candidate GBM ``n_estimators`` values.
    registered_seeds : Sequence[int]
        Registered seeds; OOF scores are MEAN-aggregated over them.
    config_sha256 : str
        SHA-256 of the resolved config (provenance link).

    Returns
    -------
    MethodLock
        Frozen record with selected configs, full search table, and
        seed-aggregated OOF scores/AURCs (dev-normalized).

    Raises
    ------
    DevelopError
        If arrays are misaligned, empty, or grids/seeds are empty.
    alive.metrics.selective.MetricError
        If ``mean(dev_errors) <= 0`` (cannot normalize).
    """
    dev_features = np.asarray(dev_features, dtype=np.float64)
    dev_errors = np.asarray(dev_errors, dtype=np.float64)
    dev_ensemble_means = np.asarray(dev_ensemble_means, dtype=np.float64)
    dev_ids = tuple(dev_ids)
    n = len(dev_ids)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    if n == 0:
        raise DevelopError("dev_ids must be non-empty.")
    if dev_features.ndim != 2 or dev_features.shape[0] != n:
        raise DevelopError(
            f"dev_features must have shape (n={n}, feat_dim); got {dev_features.shape}."
        )
    if dev_errors.ndim != 1 or dev_errors.shape[0] != n:
        raise DevelopError(f"dev_errors must have shape (n={n},); got {dev_errors.shape}.")
    if dev_ensemble_means.ndim != 3 or dev_ensemble_means.shape[0] != n:
        raise DevelopError(
            f"dev_ensemble_means must have shape (n={n}, n_members, pca_dims); "
            f"got {dev_ensemble_means.shape}."
        )
    if len(registered_seeds) == 0:
        raise DevelopError("registered_seeds must be non-empty.")
    for name, grid in (
        ("k_grid", k_grid),
        ("feature_weight_grid", feature_weight_grid),
        ("ridge_grid", ridge_grid),
        ("gbm_estimators_grid", gbm_estimators_grid),
    ):
        if len(grid) == 0:
            raise DevelopError(f"{name} must be non-empty.")

    # Normalize ONCE on the fixed dev cohort (MetricError if mean <= 0).
    norm_errors = normalize_by_mean(dev_errors)

    registered_seeds = tuple(int(s) for s in registered_seeds)

    # ------------------------------------------------------------------
    # OOF development per method
    # ------------------------------------------------------------------
    selected_params: dict[str, dict] = {}
    search_table: dict[str, list[dict]] = {}
    oof_scores: dict[str, np.ndarray] = {}
    oof_aurc: dict[str, float] = {}

    for method in METHOD_IDS:
        combos = _combos_for(
            method,
            k_grid=k_grid,
            feature_weight_grid=feature_weight_grid,
            ridge_grid=ridge_grid,
            gbm_estimators_grid=gbm_estimators_grid,
        )
        rows: list[dict] = []
        combo_scores: list[np.ndarray] = []
        for params in combos:
            # Seed aggregation: mean over registered seeds of the OOF scores.
            per_seed = np.stack(
                [
                    _oof_scores_one_seed(
                        method,
                        params,
                        dev_features,
                        dev_errors,
                        dev_ensemble_means,
                        cv_folds=cv_folds,
                        seed=s,
                    )
                    for s in registered_seeds
                ],
                axis=0,
            )
            aggregated = per_seed.mean(axis=0)
            combo_aurc = aurc(norm_errors, aggregated)
            row = dict(params)
            row["oof_aurc"] = float(combo_aurc)
            rows.append(row)
            combo_scores.append(aggregated)

        # Selection: lowest oof_aurc, tie-break per method.
        best_index = min(
            range(len(rows)),
            key=lambda i: (rows[i]["oof_aurc"], _tiebreak_key(method, rows[i])),
        )
        best_row = rows[best_index]
        selected = {k: v for k, v in best_row.items() if k != "oof_aurc"}

        selected_params[method] = selected
        search_table[method] = rows
        oof_scores[method] = combo_scores[best_index]
        oof_aurc[method] = best_row["oof_aurc"]

    return MethodLock(
        method_ids=METHOD_IDS,
        selected_params=selected_params,
        search_table=search_table,
        oof_scores=oof_scores,
        oof_aurc=oof_aurc,
        dev_ids=dev_ids,
        cv_folds=int(cv_folds),
        registered_seeds=registered_seeds,
        config_sha256=config_sha256,
    )


# ---------------------------------------------------------------------------
# FutilityDecision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FutilityDecision:
    """Frozen record of the preregistered futility decision (§7.1).

    Parameters
    ----------
    status : OperationalStatus
        ``CONTINUE_CONFIRMATORY`` or ``FUTILITY_STOPPED``.
    dev_deltas : dict[str, float]
        Comparator → point delta ``AURC[comparator] - AURC[gate]`` (dev-normalized).
    upper_bounds : dict[str, float]
        Comparator → simultaneous 90% UPPER bound on its delta.
    delta_min : float
        Minimum relevant delta on the dev-normalized scale (e.g. ``0.01``).
    comparators : tuple[str, ...]
        The comparator family (e.g. ``("gbm_error", "residual_only")``).
    confidence : float
        Family confidence (e.g. ``0.90``).
    config_sha256 : str
        SHA-256 of the resolved config.
    methodlock_sha256 : str
        SHA-256 of the source :class:`MethodLock` (provenance link).
    """

    status: OperationalStatus
    dev_deltas: dict[str, float]
    upper_bounds: dict[str, float]
    delta_min: float
    comparators: tuple[str, ...]
    confidence: float
    config_sha256: str
    methodlock_sha256: str

    @cached_property
    def checksum(self) -> str:
        """Stable SHA-256 over the full content of this decision (canonical JSON)."""
        return sha256_json(self._canonical())

    def _canonical(self) -> dict:
        return {
            "status": self.status.value,
            "dev_deltas": {c: _round_for_json(float(self.dev_deltas[c])) for c in self.comparators},
            "upper_bounds": {
                c: _round_for_json(float(self.upper_bounds[c])) for c in self.comparators
            },
            "delta_min": _round_for_json(float(self.delta_min)),
            "comparators": list(self.comparators),
            "confidence": _round_for_json(float(self.confidence)),
            "config_sha256": self.config_sha256,
            "methodlock_sha256": self.methodlock_sha256,
        }

    def write(self, path: str | Path) -> None:
        """Write the decision to ``path`` as canonical JSON."""
        payload = self._canonical()
        payload["checksum"] = self.checksum
        Path(path).write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: str | Path) -> "FutilityDecision":
        """Reconstruct a :class:`FutilityDecision` from :meth:`write` output.

        Raises
        ------
        DevelopError
            If the file is malformed or the stored checksum does not match.
        """
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise DevelopError(f"Failed to read FutilityDecision from {path!r}: {exc}") from exc
        try:
            comparators = tuple(raw["comparators"])
            decision = cls(
                status=OperationalStatus(raw["status"]),
                dev_deltas={c: float(raw["dev_deltas"][c]) for c in comparators},
                upper_bounds={c: float(raw["upper_bounds"][c]) for c in comparators},
                delta_min=float(raw["delta_min"]),
                comparators=comparators,
                confidence=float(raw["confidence"]),
                config_sha256=raw["config_sha256"],
                methodlock_sha256=raw["methodlock_sha256"],
            )
            stored = raw["checksum"]
        except (KeyError, TypeError, ValueError) as exc:
            raise DevelopError(f"FutilityDecision JSON is invalid: {exc}") from exc
        if decision.checksum != stored:
            raise DevelopError(
                f"FutilityDecision checksum mismatch: stored {stored!r} != recomputed "
                f"{decision.checksum!r}.  The serialised file may have been modified."
            )
        return decision


# ---------------------------------------------------------------------------
# decide_futility
# ---------------------------------------------------------------------------


def decide_futility(
    methodlock: MethodLock,
    norm_errors: np.ndarray,
    *,
    comparators: Sequence[str],
    delta_min: float,
    confidence: float,
    n_replicates: int,
    seed: int,
    config_sha256: str,
) -> FutilityDecision:
    """Apply the preregistered futility rule to a developed :class:`MethodLock`.

    Reference is the gate.  Computes the simultaneous one-sided UPPER bounds on
    ``AURC[comparator] - AURC[gate]`` (dev-normalized) for every comparator, then
    stops for futility iff ANY upper bound is ``<= delta_min`` (boundary equality
    stops).  Uses only the MethodLock's OOF scores and ``norm_errors``; it cannot
    see sealed or conformal data.

    Parameters
    ----------
    methodlock : MethodLock
        The developed methods (provides gate + comparator OOF scores).
    norm_errors : np.ndarray
        Shape ``(n,)`` dev-normalized errors (``dev_errors / mu``).
    comparators : Sequence[str]
        Comparator family (e.g. ``("gbm_error", "residual_only")``).
    delta_min : float
        Minimum relevant delta on the dev-normalized scale.
    confidence : float
        Family confidence (e.g. ``0.90``).
    n_replicates : int
        Bootstrap replicates.
    seed : int
        Bootstrap base seed.
    config_sha256 : str
        SHA-256 of the resolved config.

    Returns
    -------
    FutilityDecision
        The frozen decision record.

    Raises
    ------
    DevelopError
        If ``"gate"`` or any comparator is absent from the MethodLock.
    """
    comparators = tuple(comparators)
    if "gate" not in methodlock.oof_scores:
        raise DevelopError("methodlock has no 'gate' OOF scores; cannot decide futility.")
    for c in comparators:
        if c not in methodlock.oof_scores:
            raise DevelopError(
                f"comparator {c!r} not present in methodlock.oof_scores "
                f"(available: {sorted(methodlock.oof_scores)})."
            )

    norm_errors = np.asarray(norm_errors, dtype=np.float64)

    method_scores = {"gate": methodlock.oof_scores["gate"]}
    method_scores.update({c: methodlock.oof_scores[c] for c in comparators})

    bounds = simultaneous_delta_bounds(
        norm_errors,
        method_scores,
        reference="gate",
        comparators=comparators,
        side="upper",
        confidence=confidence,
        n_replicates=n_replicates,
        seed=seed,
    )

    dev_deltas = {c: float(bounds.point_delta[c]) for c in comparators}
    upper_bounds = {c: float(bounds.bound[c]) for c in comparators}

    # Boundary equality stops: <= delta_min for ANY comparator ⇒ futile.
    futile = any(upper_bounds[c] <= delta_min for c in comparators)
    status = (
        OperationalStatus.FUTILITY_STOPPED if futile else OperationalStatus.CONTINUE_CONFIRMATORY
    )

    return FutilityDecision(
        status=status,
        dev_deltas=dev_deltas,
        upper_bounds=upper_bounds,
        delta_min=float(delta_min),
        comparators=comparators,
        confidence=float(confidence),
        config_sha256=config_sha256,
        methodlock_sha256=methodlock.checksum,
    )
