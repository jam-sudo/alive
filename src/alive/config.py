"""Locked-config schema, validation, and deterministic run-ID hashing.

This module provides the canonical representation of an ALIVE experiment
configuration as nested frozen dataclasses, strict validation logic, and
a deterministic SHA-256 run-ID computed from the validated config state.

Public API
----------
load_config(path)
    Parse a YAML config file, validate it, and return a ``Config`` instance.
Config.run_id
    Cached property: first 16 hex characters of the SHA-256 hash of a
    canonically serialised version of the config (keys sorted recursively,
    no timestamps or environment data).  Identical configs produce identical
    run IDs regardless of YAML key order or insignificant whitespace.

Raises
------
ConfigError
    Raised with a human-readable message for any validation failure.

Examples
--------
>>> from pathlib import Path
>>> from alive.config import load_config
>>> cfg = load_config(Path("configs/cartographer_trust_gate_k562_v1.yaml"))
>>> cfg.experiment
'cartographer_trust_gate_k562_v1'
>>> len(cfg.run_id)
16
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Known comparator names (futility.comparators must be a subset of this set)
# ---------------------------------------------------------------------------

_KNOWN_COMPARATORS: frozenset[str] = frozenset(
    {"gbm_error", "residual_only", "nearest_feature", "ensemble_disagreement", "ridge_error"}
)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ConfigError(ValueError):
    """Raised when a config file fails schema or validation checks.

    Parameters
    ----------
    message : str
        Human-readable description of what is wrong.
    """


# ---------------------------------------------------------------------------
# Nested frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SplitFractions:
    """Fractional sizes for the four data partitions.

    All values must be in the open interval (0, 1) and must sum to exactly 1.0
    within a tolerance of 1e-9.

    Parameters
    ----------
    base_train : float
        Fraction used for base-model training.
    method_development : float
        Fraction reserved for method-development cross-validation.
    conformal_calibration : float
        Fraction used for conformal calibration.
    sealed_evaluation : float
        Fraction held out as the sealed external test set.
    """

    base_train: float
    method_development: float
    conformal_calibration: float
    sealed_evaluation: float


@dataclass(frozen=True)
class ResponseSpace:
    """Parameters governing the transcriptomic response-space construction.

    Parameters
    ----------
    normalization : str
        Normalisation strategy identifier.
    hvg_count : int
        Number of highly-variable genes selected.
    pca_dims : int
        Number of PCA dimensions retained.
    cell_cap : int
        Maximum cells sampled per perturbation for population-level metrics.
    min_cells : int
        Minimum cells required per perturbation to include it in evaluation.
    cell_sampling_repeats : int
        Number of bootstrap resampling rounds for population metrics.
    energy_block_size : int
        Block size used in block-wise energy-distance computation.
    """

    normalization: str
    hvg_count: int
    pca_dims: int
    cell_cap: int
    min_cells: int
    cell_sampling_repeats: int
    energy_block_size: int


@dataclass(frozen=True)
class PerturbationFeatures:
    """Configuration for perturbation feature encoding.

    Parameters
    ----------
    primary : str
        Identifier of the primary feature encoder (e.g. ESM-2 variant name).
    standardize_on : str
        Split name whose statistics are used for z-score standardisation.
    missing_policy : str
        Policy when a perturbation has no available features.
    """

    primary: str
    standardize_on: str
    missing_policy: str


@dataclass(frozen=True)
class BaseModel:
    """Hyperparameters for the base additive-ridge model.

    Parameters
    ----------
    family : str
        Model family identifier.
    ridge_grid : list[float]
        Grid of ridge regularisation strengths to search over cross-validation.
    cv_folds : int
        Number of cross-validation folds.
    ensemble_members : int
        Number of ensemble members to fit (different sub-samples).
    """

    family: str
    ridge_grid: tuple[float, ...]
    cv_folds: int
    ensemble_members: int


@dataclass(frozen=True)
class MethodDevelopment:
    """Hyperparameter grids and seeds for the method-development phase.

    Parameters
    ----------
    cv_folds : int
        Number of cross-validation folds used in method development.
    k_grid : list[int]
        Grid of neighbour counts for kNN-based methods.
    feature_weight_grid : list[float]
        Grid of feature weighting multipliers.
    gbm_estimators_grid : list[int]
        Grid of GBM tree counts.
    ridge_grid : list[float]
        Grid of ridge regularisation strengths.
    registered_seeds : list[int]
        Fixed random seeds for reproducible CV; must be unique.
    """

    cv_folds: int
    k_grid: tuple[int, ...]
    feature_weight_grid: tuple[float, ...]
    gbm_estimators_grid: tuple[int, ...]
    ridge_grid: tuple[float, ...]
    registered_seeds: tuple[int, ...]


@dataclass(frozen=True)
class Decision:
    """Parameters governing the Trust-Gate decision logic.

    Parameters
    ----------
    target_selection_coverage : float
        Required coverage (0, 1) for conformal prediction sets.
    conformal_alpha : float
        Miscoverage level (0, 1) for conformal calibration.
    minimum_sealed_perturbations : int
        Minimum number of perturbations that must be present in the sealed
        evaluation cohort; the runtime check rejects runs below this floor.
    """

    target_selection_coverage: float
    conformal_alpha: float
    minimum_sealed_perturbations: int


@dataclass(frozen=True)
class Inference:
    """Parameters governing bootstrap inference and reporting.

    Parameters
    ----------
    bootstrap_replicates : int
        Number of bootstrap resampling rounds; must be >= 2000 for a scientific
        run.
    family_confidence : float
        Family-wise confidence level (0, 1) for simultaneous inference.
    secondary_augrc_noninferiority_margin : float
        Non-inferiority margin for the secondary AUGRC metric.
    """

    bootstrap_replicates: int
    family_confidence: float
    secondary_augrc_noninferiority_margin: float


@dataclass(frozen=True)
class Futility:
    """Configuration for the futility stopping rule.

    Parameters
    ----------
    enabled : bool
        Whether futility monitoring is active.
    comparators : tuple[str, ...]
        Names of the comparator methods evaluated in the futility analysis.
        Must be a non-empty subset of known comparator names.
    minimum_relevant_delta : float
        Minimum effect-size delta considered relevant; effects below this
        threshold trigger futility.
    family_confidence : float
        Family-wise confidence level (0, 1) for the simultaneous upper bounds.
    rule : str
        Name of the futility stopping rule to apply.
    """

    enabled: bool
    comparators: tuple[str, ...]
    minimum_relevant_delta: float
    family_confidence: float
    rule: str


# ---------------------------------------------------------------------------
# Top-level Config
# ---------------------------------------------------------------------------

# Expected top-level keys in the YAML (used for unknown-key detection)
_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "experiment",
        "manifest_seed",
        "split_fractions",
        "response_space",
        "perturbation_features",
        "base_model",
        "method_development",
        "decision",
        "inference",
        "futility",
    }
)

# Expected keys per nested section
_SECTION_KEYS: dict[str, frozenset[str]] = {
    "split_fractions": frozenset(
        {"base_train", "method_development", "conformal_calibration", "sealed_evaluation"}
    ),
    "response_space": frozenset(
        {
            "normalization",
            "hvg_count",
            "pca_dims",
            "cell_cap",
            "min_cells",
            "cell_sampling_repeats",
            "energy_block_size",
        }
    ),
    "perturbation_features": frozenset({"primary", "standardize_on", "missing_policy"}),
    "base_model": frozenset({"family", "ridge_grid", "cv_folds", "ensemble_members"}),
    "method_development": frozenset(
        {
            "cv_folds",
            "k_grid",
            "feature_weight_grid",
            "gbm_estimators_grid",
            "ridge_grid",
            "registered_seeds",
        }
    ),
    "decision": frozenset(
        {"target_selection_coverage", "conformal_alpha", "minimum_sealed_perturbations"}
    ),
    "inference": frozenset(
        {
            "bootstrap_replicates",
            "family_confidence",
            "secondary_augrc_noninferiority_margin",
        }
    ),
    "futility": frozenset(
        {
            "enabled",
            "comparators",
            "minimum_relevant_delta",
            "family_confidence",
            "rule",
        }
    ),
}


@dataclass(frozen=True)
class Config:
    """Top-level locked experiment configuration.

    Load via :func:`load_config`; do not construct directly.

    Parameters
    ----------
    experiment : str
        Unique name for this experiment configuration.
    manifest_seed : int
        Random seed used exclusively for manifest construction (cell-barcode
        assignment to splits); must not be used for any model randomness.
    split_fractions : SplitFractions
        Fractional sizes of the four data partitions.
    response_space : ResponseSpace
        Transcriptomic response-space construction parameters.
    perturbation_features : PerturbationFeatures
        Perturbation feature encoding configuration.
    base_model : BaseModel
        Base additive-ridge model hyperparameters.
    method_development : MethodDevelopment
        Method-development phase hyperparameter grids and seeds.
    decision : Decision
        Trust-Gate decision parameters.
    inference : Inference
        Bootstrap inference parameters.
    futility : Futility
        Futility monitoring parameters.
    """

    experiment: str
    manifest_seed: int
    split_fractions: SplitFractions
    response_space: ResponseSpace
    perturbation_features: PerturbationFeatures
    base_model: BaseModel
    method_development: MethodDevelopment
    decision: Decision
    inference: Inference
    futility: Futility

    @cached_property
    def run_id(self) -> str:
        """Deterministic 16-character hex run identifier.

        Computed as the first 16 hex characters of the SHA-256 hash of the
        canonically serialised config (all keys sorted recursively, stable
        numeric formatting, no timestamps or environment data).

        Two configs that are field-identical — regardless of the YAML key order
        in the source file — produce the same ``run_id``.  Any change to a
        registered field produces a different ``run_id``.

        Returns
        -------
        str
            16-character lowercase hexadecimal string.
        """
        canonical = _canonical_dict(self)
        serialised = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(serialised.encode("utf-8")).hexdigest()
        return digest[:16]


# ---------------------------------------------------------------------------
# Canonical serialisation helper (for run-ID hashing)
# ---------------------------------------------------------------------------


def _canonical_dict(obj: Any) -> Any:
    """Recursively convert a config object to a JSON-serialisable, sorted dict.

    Parameters
    ----------
    obj : Any
        A Config or nested dataclass, list, tuple, or scalar.

    Returns
    -------
    Any
        A nested structure of dicts, lists, and scalars suitable for
        ``json.dumps(sort_keys=True)``.
    """
    if hasattr(obj, "__dataclass_fields__"):
        # Sort fields alphabetically for canonical ordering
        return {
            k: _canonical_dict(getattr(obj, k)) for k in sorted(obj.__dataclass_fields__.keys())
        }
    if isinstance(obj, (list, tuple)):
        return [_canonical_dict(v) for v in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        # Use repr for stable float formatting (avoids locale-dependent str())
        return repr(obj)
    return obj


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _check_unknown_keys(section_name: str, data: dict, known: frozenset[str]) -> None:
    """Raise ConfigError if *data* contains keys not in *known*.

    Parameters
    ----------
    section_name : str
        Human-readable name for error messages (e.g. ``"split_fractions"``).
    data : dict
        The YAML sub-dict to inspect.
    known : frozenset[str]
        The set of recognised keys.
    """
    unknown = set(data.keys()) - known
    if unknown:
        raise ConfigError(
            f"Unknown key(s) in {section_name!r}: {sorted(unknown)}. "
            f"Recognised keys: {sorted(known)}."
        )


def _validate_probability(name: str, value: float) -> None:
    """Raise ConfigError if *value* is not in the open interval (0, 1).

    Parameters
    ----------
    name : str
        Field name for the error message.
    value : float
        The value to check.
    """
    if not (0.0 < value < 1.0):
        raise ConfigError(f"{name!r} must be in the open interval (0, 1); got {value!r}.")


def _validate_non_empty_list(name: str, lst: list) -> None:
    """Raise ConfigError if *lst* is empty.

    Parameters
    ----------
    name : str
        Field name for the error message.
    lst : list
        The list to check.
    """
    if not lst:
        raise ConfigError(f"{name!r} must be a non-empty list; got an empty list.")


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_config(path: str | Path) -> Config:
    """Parse, validate, and return a locked experiment :class:`Config`.

    Parameters
    ----------
    path : str or Path
        Path to a YAML config file conforming to the CARTOGRAPHER schema.

    Returns
    -------
    Config
        Validated frozen dataclass tree.

    Raises
    ------
    ConfigError
        If the YAML contains unknown keys, values out of range, or any other
        schema violation (see module docstring for full rule list).
    FileNotFoundError
        If *path* does not exist.
    """
    path = Path(path)
    raw: dict = yaml.safe_load(path.read_text(encoding="utf-8"))

    # -----------------------------------------------------------------------
    # 1. Unknown top-level keys
    # -----------------------------------------------------------------------
    _check_unknown_keys("(top level)", raw, _TOP_LEVEL_KEYS)

    # -----------------------------------------------------------------------
    # 2. Unknown nested keys (check every section)
    # -----------------------------------------------------------------------
    for section, known in _SECTION_KEYS.items():
        if section in raw and isinstance(raw[section], dict):
            _check_unknown_keys(section, raw[section], known)

    # -----------------------------------------------------------------------
    # 3. split_fractions: values in (0,1), sum == 1.0 ± 1e-9, exact keys
    # -----------------------------------------------------------------------
    sf_raw: dict = raw["split_fractions"]
    _check_unknown_keys("split_fractions", sf_raw, _SECTION_KEYS["split_fractions"])

    for key, val in sf_raw.items():
        if not (0.0 < val < 1.0):
            raise ConfigError(
                f"split_fractions.{key!r} must be in the open interval (0, 1); got {val!r}."
            )
    total = sum(sf_raw.values())
    if abs(total - 1.0) > 1e-9:
        raise ConfigError(f"split_fractions must sum to 1.0 (within 1e-9); got sum = {total!r}.")

    # -----------------------------------------------------------------------
    # 4. inference.bootstrap_replicates >= 2000
    # -----------------------------------------------------------------------
    br = raw["inference"]["bootstrap_replicates"]
    if br < 2000:
        raise ConfigError(
            f"inference.bootstrap_replicates must be >= 2000 for a scientific run; got {br!r}."
        )

    # -----------------------------------------------------------------------
    # 5. decision.minimum_sealed_perturbations >= 1
    # -----------------------------------------------------------------------
    msp = raw["decision"]["minimum_sealed_perturbations"]
    if msp < 1:
        raise ConfigError(f"decision.minimum_sealed_perturbations must be >= 1; got {msp!r}.")

    # -----------------------------------------------------------------------
    # 6. Probability/coverage fields in (0, 1)
    # -----------------------------------------------------------------------
    _validate_probability("decision.conformal_alpha", raw["decision"]["conformal_alpha"])
    _validate_probability(
        "decision.target_selection_coverage", raw["decision"]["target_selection_coverage"]
    )
    _validate_probability("inference.family_confidence", raw["inference"]["family_confidence"])
    _validate_probability("futility.family_confidence", raw["futility"]["family_confidence"])

    # -----------------------------------------------------------------------
    # 7. futility.comparators: non-empty subset of known names
    # -----------------------------------------------------------------------
    comparators: list = raw["futility"]["comparators"]
    if not comparators:
        raise ConfigError("futility.comparators must be a non-empty list of comparator names.")
    unknown_comp = set(comparators) - _KNOWN_COMPARATORS
    if unknown_comp:
        raise ConfigError(
            f"Unknown comparator name(s) in futility.comparators: {sorted(unknown_comp)}. "
            f"Known comparators: {sorted(_KNOWN_COMPARATORS)}."
        )

    # -----------------------------------------------------------------------
    # 8. Grid lists non-empty; registered_seeds non-empty and unique
    # -----------------------------------------------------------------------
    grid_fields = [
        ("base_model", "ridge_grid"),
        ("method_development", "k_grid"),
        ("method_development", "feature_weight_grid"),
        ("method_development", "gbm_estimators_grid"),
        ("method_development", "ridge_grid"),
    ]
    for section, field_name in grid_fields:
        lst = raw[section][field_name]
        _validate_non_empty_list(f"{section}.{field_name}", lst)

    seeds: list = raw["method_development"]["registered_seeds"]
    _validate_non_empty_list("method_development.registered_seeds", seeds)
    if len(seeds) != len(set(seeds)):
        raise ConfigError(
            "method_development.registered_seeds must contain Unique values; "
            f"got duplicates in {seeds!r}."
        )

    # -----------------------------------------------------------------------
    # Build the dataclass tree
    # -----------------------------------------------------------------------
    sf = SplitFractions(**sf_raw)

    rs_raw = raw["response_space"]
    rs = ResponseSpace(**rs_raw)

    pf_raw = raw["perturbation_features"]
    pf = PerturbationFeatures(**pf_raw)

    bm_raw = raw["base_model"]
    bm = BaseModel(
        family=bm_raw["family"],
        ridge_grid=tuple(bm_raw["ridge_grid"]),
        cv_folds=bm_raw["cv_folds"],
        ensemble_members=bm_raw["ensemble_members"],
    )

    md_raw = raw["method_development"]
    md = MethodDevelopment(
        cv_folds=md_raw["cv_folds"],
        k_grid=tuple(md_raw["k_grid"]),
        feature_weight_grid=tuple(md_raw["feature_weight_grid"]),
        gbm_estimators_grid=tuple(md_raw["gbm_estimators_grid"]),
        ridge_grid=tuple(md_raw["ridge_grid"]),
        registered_seeds=tuple(md_raw["registered_seeds"]),
    )

    d_raw = raw["decision"]
    d = Decision(**d_raw)

    inf_raw = raw["inference"]
    inf = Inference(**inf_raw)

    fut_raw = raw["futility"]
    fut = Futility(
        enabled=fut_raw["enabled"],
        comparators=tuple(fut_raw["comparators"]),
        minimum_relevant_delta=fut_raw["minimum_relevant_delta"],
        family_confidence=fut_raw["family_confidence"],
        rule=fut_raw["rule"],
    )

    return Config(
        experiment=raw["experiment"],
        manifest_seed=raw["manifest_seed"],
        split_fractions=sf,
        response_space=rs,
        perturbation_features=pf,
        base_model=bm,
        method_development=md,
        decision=d,
        inference=inf,
        futility=fut,
    )
