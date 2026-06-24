"""Strict Phase-2 config loader and execution-mode guard for COMPOSE-K562-v1.

This module is intentionally standalone. It does **not** import or extend the
CARTOGRAPHER ``alive.config.Config`` so that COMPOSE Phase-2 work cannot perturb
that run identity, and so the two protocols' seals remain non-interchangeable
(``CLAUDE.md`` §6.3).

The loader (:func:`load_compose_phase2_config`) parses
``configs/compose_k562_v1_phase2.yaml`` into a frozen
:class:`ComposePhase2Config`. The schema is fully closed: every top-level block
that carries pre-registered values — and every nested dict within it
(``split.roles``, ``baselines.gears``/``cpa``, the three ``verdict`` sub-blocks)
— must carry exactly its canonical key set. A missing required key or an unknown
key anywhere raises :class:`Phase2ConfigError`. ``status`` is validated against
the registered enum so a typo cannot silently masquerade as a blocked config.
The loader also pins the scientifically load-bearing values that the
pre-registration freezes: total factor dimensions and the ESM dimension
arithmetic (with strict int typing), the exact comparator roster, the primary
metric formula and margins, every registered secondary metric's definition /
interval / material-regression margin (or a governance note that it is
descriptive-only), the bootstrap settings, the role names and the activation
requirements.

The guard (:func:`assert_scientific_mode_allowed`) is scientific-only.
``fixture_mode=True`` is rejected so a caller-controlled boolean cannot bypass
activation; fixture execution has a separate bounded entry point in
``phase2a``. Scientific mode requires **all** of: config ``status == "active"``, a matching owner
:class:`ActivationRecord`, a clean committed Git state, and an evidence hash for
every activation requirement. The current candidate config carries
``status: preregistered_activation_blocked``, so a real-data pipeline cannot be
started from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from alive.provenance import sha256_json

# ---------------------------------------------------------------------------
# Frozen, pre-registered expected values. These are the contract the loader
# validates the candidate YAML against. Changing any of them requires a new
# protocol/run identity, not an in-place edit (CLAUDE.md §3.2, §11).
# ---------------------------------------------------------------------------
_EXPECTED_PROTOCOL = "COMPOSE-K562-v1"
_EXPECTED_PHASE = 2
_EXPECTED_TOTAL_K_GRID: tuple[int, ...] = (4, 6, 8)
_EXPECTED_EXPRESSION_DIMS: tuple[int, ...] = (2, 4, 6)
_EXPECTED_ESM_PROJECTION_DIM = 2
_EXPECTED_LAMBDA_GRID: tuple[float, ...] = (0.0, 0.001, 0.01, 0.1)
_EXPECTED_OOF_FOLDS = 3
_EXPECTED_UNCOVERED_TOLERANCE = 0.75
_EXPECTED_SPLIT_SEED = 11
_EXPECTED_REGISTERED_SEEDS: tuple[int, ...] = (11, 23, 37)
_EXPECTED_COMPARATOR_FAMILY: tuple[str, ...] = (
    "additive",
    "gears",
    "cpa",
    "id_only",
    "l3_hypernetwork",
)
_EXPECTED_METHOD_ROSTER: tuple[str, ...] = (
    "l1_bilinear_identifiable",
    "l2_saturation",
    "l3_hypernetwork",
    "additive",
    "no_change",
    "perturbation_mean",
    "id_only",
    "gears",
    "cpa",
)
_EXPECTED_METRIC_PRIMARY = "paired_relative_error_reduction"
_EXPECTED_METRIC_FORMULA = "1 - mean(error_l1) / max(mean(error_comparator), 1e-12)"
_EXPECTED_MATERIAL_MARGIN_VS_ADDITIVE = 0.05
_EXPECTED_LEARNED_COMPARATOR_MARGIN = 0.0
_EXPECTED_INFERENCE_METHOD = "max_deviation_bootstrap"
_EXPECTED_RESAMPLING_UNIT = "perturbation_pair"
_EXPECTED_FAMILY_CONFIDENCE = 0.95
_EXPECTED_BOOTSTRAP_REPLICATES = 10000
_EXPECTED_ROLE_NAMES: tuple[str, ...] = (
    "combo_calibration",
    "sealed_double_unseen",
    "sealed_single_unseen",
)
_EXPECTED_FIT_ROLES: tuple[str, ...] = ("control", "singles")
_EXPECTED_ACTIVATION_REQUIREMENTS: tuple[str, ...] = (
    "real_norman_phi_rank_and_condition_report",
    "regime_specific_detectable_effect_analysis",
    "finalized_norman_data_card_and_sha256",
    "gears_cpa_reproducible_dependency_lock",
    "independent_compose_outcome_store_and_access_audit",
    "phase2_plan_metric_leakage_and_seal_integration_tests",
)

# Registered status enum. Any other value (e.g. a typo like "activ") is rejected
# so a blocked config can never silently masquerade as something else (I2).
_KNOWN_STATUS = frozenset({"preregistered_activation_blocked", "active"})

# Registered secondary-metric governance. Per spec §10 and the config
# (``secondary_are_verdict_gates: false``), both secondaries are reported with an
# effect size, a simultaneous interval and a chance/null definition, but they are
# NOT verdict gates. They are therefore descriptive-only: no material-regression
# margin is registered, and each carries a versioned governance note explaining
# why (CLAUDE.md §10, brief Task 1 secondary clause).
_EXPECTED_SECONDARY_METRICS: dict[str, dict[str, Any]] = {
    "gi_explained_fraction": {
        "definition": (
            "GI-explained fraction of the combination response, normalized by the "
            "calibration-role split-half noise ceiling."
        ),
        "interval_method": "shared-resample max_deviation_bootstrap simultaneous 95% interval",
        "material_regression_margin": None,
        "governance_note": (
            "Descriptive-only: secondary_are_verdict_gates is false (spec §10). Reported "
            "with effect size, simultaneous interval and the split-half noise-ceiling null; "
            "not a verdict gate, so no material-regression margin is registered."
        ),
    },
    "gi_structure_recovery": {
        "definition": (
            "Recovery of GI sign/class structure versus known genetic-interaction labels, "
            "reported relative to chance."
        ),
        "interval_method": "shared-resample max_deviation_bootstrap simultaneous 95% interval",
        "material_regression_margin": None,
        "governance_note": (
            "Descriptive-only: secondary_are_verdict_gates is false (spec §10). Reported "
            "with effect size, simultaneous interval and an explicit chance/null definition; "
            "not a verdict gate, so no material-regression margin is registered."
        ),
    },
}

# Closed top-level schema. Every key must be present; unknown keys are rejected.
# Each nested block below has its inner keys closed too (I1).
_KNOWN_TOP_LEVEL = frozenset(
    {
        "protocol",
        "phase",
        "status",
        "activation_requirements",
        "data",
        "eligibility",
        "split",
        "response_space",
        "factor_z",
        "identification",
        "metric",
        "inference",
        "regimes",
        "baselines",
        "leakage_control",
        "phasing",
        "futility",
        "seal",
        "seeds",
        "verdict",
    }
)

# Closed inner schemas for every block that carries pre-registered values. Each
# key set is derived from the canonical YAML structure
# (``configs/compose_k562_v1_phase2.yaml``); a missing required key or an unknown
# key anywhere raises :class:`Phase2ConfigError`. Nested dicts inside a block
# (``split.roles``, ``baselines.gears``/``cpa``, ``verdict.*``) are closed via
# their own entries below (I1).
_KNOWN_DATA = frozenset(
    {
        "source",
        "file",
        "license",
        "cell_line",
        "modality",
        "perturbation_key",
        "control_token",
        "combo_sep",
    }
)
_KNOWN_ELIGIBILITY = frozenset({"min_cells_per_gene", "min_cells_per_pair", "require_esm_feature"})
_KNOWN_SPLIT = frozenset(
    {
        "seed",
        "calibration_fraction",
        "eligibility_before_split",
        "pair_canonicalization",
        "pair_deduplication",
        "string_order",
        "gene_permutation",
        "calibration_gene_count",
        "roles",
        "both_seen_test",
    }
)
_KNOWN_SPLIT_ROLES = frozenset(
    {"combo_calibration", "sealed_double_unseen", "sealed_single_unseen"}
)
_KNOWN_RESPONSE_SPACE = frozenset({"transform", "n_hvg", "pca_dim", "fit_roles"})
_KNOWN_FACTOR_Z = frozenset(
    {
        "total_k_grid",
        "expression_dims",
        "include_esm",
        "esm_model",
        "esm_projection_dim",
        "esm_projection_method",
        "esm_projection_fit_roles",
        "rank_gate",
        "selection",
    }
)
_KNOWN_IDENTIFICATION = frozenset(
    {"estimator", "lambda_grid", "selection", "oof_folds", "uncovered_tolerance"}
)
_KNOWN_METRIC = frozenset(
    {
        "pair_error",
        "primary",
        "formula",
        "distance",
        "aggregation",
        "material_margin_vs_additive",
        "learned_comparator_margin",
        "nonfinite_or_missing_policy",
        "secondary",
        "secondary_are_verdict_gates",
    }
)
_KNOWN_INFERENCE = frozenset(
    {
        "method",
        "comparator_family",
        "resampling_unit",
        "shared_resamples_across_contrasts",
        "family_confidence",
        "bootstrap_replicates",
    }
)
_KNOWN_REGIMES = frozenset(
    {"headline_candidate", "registered_secondary", "power_status", "report_all"}
)
_KNOWN_BASELINES = frozenset(
    {
        "additive",
        "lower_bounds",
        "id_only",
        "gears",
        "cpa",
        "ablation_ladder",
    }
)
_KNOWN_BASELINE_GEARS = frozenset({"package", "revision", "environment_status"})
_KNOWN_BASELINE_CPA = frozenset({"package", "revision", "environment_status"})
_KNOWN_LEAKAGE_CONTROL = frozenset(
    {"baseline_training_roles", "sealed_outcomes_touched_before_freeze"}
)
_KNOWN_PHASING = frozenset({"phase_2a", "phase_2b"})
_KNOWN_FUTILITY = frozenset({"conditions", "dev_oof_metric", "dev_oof_threshold"})
_KNOWN_SEAL = frozenset({"artifacts_root", "run_id_inputs", "sealed_access_max", "write_once"})
_KNOWN_SEEDS = frozenset({"split_seed", "registered_seeds"})
_KNOWN_VERDICT = frozenset(
    {
        "method_axis",
        "sealed_axis",
        "gi_learnable_win",
        "partial",
        "no_distinct_win",
        "integrity_clause_disclaimer",
    }
)
_KNOWN_VERDICT_GI_LEARNABLE_WIN = frozenset(
    {
        "additive_simultaneous_lower_bound_gt",
        "every_learned_comparator_simultaneous_lower_bound_gt",
    }
)
_KNOWN_VERDICT_PARTIAL = frozenset(
    {"additive_simultaneous_lower_bound_gt", "learned_family_condition"}
)
_KNOWN_VERDICT_NO_DISTINCT_WIN = frozenset({"additive_simultaneous_lower_bound_lte"})


class Phase2ConfigError(ValueError):
    """Raised when the Phase-2 config is structurally or scientifically invalid."""


class ScientificModeError(RuntimeError):
    """Raised when a scientific (real-data) pipeline is not permitted to start.

    The most important case is a config whose ``status`` is not ``active`` — for
    example the current ``preregistered_activation_blocked`` candidate.
    """


@dataclass(frozen=True)
class SecondaryMetricSpec:
    """A single registered secondary metric and its governance record.

    Attributes
    ----------
    name
        Registered secondary-metric identifier.
    definition
        Exact operational definition of the metric.
    interval_method
        How the reported simultaneous interval is computed.
    material_regression_margin
        Pre-registered material-regression margin, or ``None`` when the metric is
        descriptive-only (not a verdict gate).
    governance_note
        Versioned reconciliation explaining a descriptive-only metric; required
        whenever ``material_regression_margin`` is ``None``.
    """

    name: str
    definition: str
    interval_method: str
    material_regression_margin: float | None
    governance_note: str | None


@dataclass(frozen=True)
class ActivationRecord:
    """Owner authorization to leave fixture mode and run a real-data pipeline.

    Attributes
    ----------
    owner
        Identifier of the owner who authorized activation.
    approved_protocol
        Protocol name the owner approved; must match the config's protocol.
    approved_phase
        Phase the owner approved; must match the config's phase.
    evidence_hashes
        Mapping from each activation requirement to its evidence hash. Scientific
        mode requires a present hash for every requirement the config declares.
    """

    owner: str
    approved_protocol: str
    approved_phase: int
    evidence_hashes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ComposePhase2Config:
    """Frozen, validated COMPOSE-K562-v1 Phase-2 configuration.

    Construct via :func:`load_compose_phase2_config`; the constructor receives
    only values that have already passed schema and content validation.
    """

    protocol: str
    phase: int
    status: str
    activation_requirements: tuple[str, ...]
    total_k_grid: tuple[int, ...]
    expression_dims: tuple[int, ...]
    esm_projection_dim: int
    lambda_grid: tuple[float, ...]
    oof_folds: int
    uncovered_tolerance: float
    split_seed: int
    registered_seeds: tuple[int, ...]
    comparator_family: tuple[str, ...]
    method_roster: tuple[str, ...]
    metric_primary: str
    metric_formula: str
    material_margin_vs_additive: float
    learned_comparator_margin: float
    secondary_metrics: tuple[SecondaryMetricSpec, ...]
    secondary_are_verdict_gates: bool
    inference_method: str
    resampling_unit: str
    shared_resamples_across_contrasts: bool
    family_confidence: float
    bootstrap_replicates: int
    role_names: tuple[str, ...]
    fit_roles: tuple[str, ...]
    config_sha256: str

    @property
    def is_active(self) -> bool:
        """Return ``True`` only when the config status is exactly ``active``."""
        return self.status == "active"


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    """Return ``mapping[key]`` or raise :class:`Phase2ConfigError`."""
    if not isinstance(mapping, dict) or key not in mapping:
        raise Phase2ConfigError(f"missing required key '{key}' in {context}")
    return mapping[key]


def _close_schema(mapping: dict[str, Any], known: frozenset[str], context: str) -> None:
    """Fully close a block's schema: reject unknown AND missing inner keys.

    Parameters
    ----------
    mapping
        The block to validate; must be a mapping.
    known
        The exact set of keys the block is allowed (and required) to carry,
        derived from the canonical YAML structure.
    context
        Human-readable block name used in error messages.

    Raises
    ------
    Phase2ConfigError
        If ``mapping`` is not a mapping, carries any key outside ``known``, or is
        missing any key in ``known``.
    """
    if not isinstance(mapping, dict):
        raise Phase2ConfigError(f"expected a mapping for {context}")
    keys = set(mapping)
    unknown = keys - known
    if unknown:
        raise Phase2ConfigError(f"unknown {context} keys: {sorted(unknown)}")
    missing = known - keys
    if missing:
        raise Phase2ConfigError(f"missing required {context} keys: {sorted(missing)}")


def _strict_int(value: Any, context: str) -> int:
    """Return ``value`` only if it is a real ``int`` (``bool`` rejected).

    Unlike ``int(value)`` this never coerces string ints or floats, so a typo
    such as ``"4"`` in a frozen grid is surfaced rather than silently accepted.

    Parameters
    ----------
    value
        The candidate value.
    context
        Human-readable field name used in the error message.

    Raises
    ------
    Phase2ConfigError
        If ``value`` is not an ``int`` (booleans are explicitly rejected).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise Phase2ConfigError(f"{context} must be an int, got {value!r}")
    return value


def load_compose_phase2_config(path: str | Path) -> ComposePhase2Config:
    """Load and strictly validate the COMPOSE Phase-2 YAML config.

    Parameters
    ----------
    path
        Path to the Phase-2 YAML config (the candidate
        ``configs/compose_k562_v1_phase2.yaml`` or a test copy of it).

    Returns
    -------
    ComposePhase2Config
        A frozen, fully validated config.

    Raises
    ------
    Phase2ConfigError
        If the file is empty, carries unknown or missing keys, or any
        scientifically load-bearing value deviates from the pre-registration.
    """
    raw: dict[str, Any] | None = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict) or not raw:
        raise Phase2ConfigError("config is empty or not a mapping")

    _close_schema(raw, _KNOWN_TOP_LEVEL, "top-level")
    _validate_block_schemas(raw)

    protocol = _require(raw, "protocol", "top-level")
    if protocol != _EXPECTED_PROTOCOL:
        raise Phase2ConfigError(f"protocol must be {_EXPECTED_PROTOCOL!r}, got {protocol!r}")

    phase = _require(raw, "phase", "top-level")
    if phase != _EXPECTED_PHASE:
        raise Phase2ConfigError(f"phase must be {_EXPECTED_PHASE}, got {phase!r}")

    status = _require(raw, "status", "top-level")
    if not isinstance(status, str) or status not in _KNOWN_STATUS:
        raise Phase2ConfigError(f"status must be one of {sorted(_KNOWN_STATUS)}, got {status!r}")

    activation_requirements = _validate_activation_requirements(
        _require(raw, "activation_requirements", "top-level")
    )
    total_k_grid, expression_dims, esm_projection_dim = _validate_factor_z(
        _require(raw, "factor_z", "top-level")
    )
    lambda_grid, oof_folds, uncovered_tolerance = _validate_identification(
        _require(raw, "identification", "top-level")
    )
    split_seed, registered_seeds = _validate_seeds(_require(raw, "seeds", "top-level"))
    method_roster = _validate_baselines(_require(raw, "baselines", "top-level"))
    (
        metric_primary,
        metric_formula,
        material_margin,
        learned_margin,
        secondary_metrics,
        secondary_are_gates,
    ) = _validate_metric(_require(raw, "metric", "top-level"))
    (
        comparator_family,
        inference_method,
        resampling_unit,
        shared_resamples,
        family_confidence,
        bootstrap_replicates,
    ) = _validate_inference(_require(raw, "inference", "top-level"))
    role_names, fit_roles = _validate_roles(
        _require(raw, "split", "top-level"),
        _require(raw, "response_space", "top-level"),
    )

    return ComposePhase2Config(
        protocol=protocol,
        phase=phase,
        status=status,
        activation_requirements=activation_requirements,
        total_k_grid=total_k_grid,
        expression_dims=expression_dims,
        esm_projection_dim=esm_projection_dim,
        lambda_grid=lambda_grid,
        oof_folds=oof_folds,
        uncovered_tolerance=uncovered_tolerance,
        split_seed=split_seed,
        registered_seeds=registered_seeds,
        comparator_family=comparator_family,
        method_roster=method_roster,
        metric_primary=metric_primary,
        metric_formula=metric_formula,
        material_margin_vs_additive=material_margin,
        learned_comparator_margin=learned_margin,
        secondary_metrics=secondary_metrics,
        secondary_are_verdict_gates=secondary_are_gates,
        inference_method=inference_method,
        resampling_unit=resampling_unit,
        shared_resamples_across_contrasts=shared_resamples,
        family_confidence=family_confidence,
        bootstrap_replicates=bootstrap_replicates,
        role_names=role_names,
        fit_roles=fit_roles,
        config_sha256=sha256_json(raw),
    )


def _validate_block_schemas(raw: dict[str, Any]) -> None:
    """Close the schema of every pre-registered block and its nested dicts (I1).

    For each block listed in the top-level schema that carries pre-registered
    values, require its exact canonical inner-key set: an unknown key or a
    missing required key anywhere raises :class:`Phase2ConfigError`. Nested
    mappings (``split.roles``, ``baselines.gears``/``cpa`` and the three
    ``verdict`` sub-blocks) are closed as well. Value-level checks remain in the
    dedicated ``_validate_*`` helpers; this function only closes structure.

    Parameters
    ----------
    raw
        The top-level mapping parsed from the YAML config; already confirmed to
        carry exactly the canonical top-level keys.

    Raises
    ------
    Phase2ConfigError
        If any block (or nested dict) carries an unknown or missing inner key.
    """
    _close_schema(_require(raw, "data", "top-level"), _KNOWN_DATA, "data")
    _close_schema(_require(raw, "eligibility", "top-level"), _KNOWN_ELIGIBILITY, "eligibility")

    split = _require(raw, "split", "top-level")
    _close_schema(split, _KNOWN_SPLIT, "split")
    _close_schema(_require(split, "roles", "split"), _KNOWN_SPLIT_ROLES, "split.roles")

    _close_schema(
        _require(raw, "response_space", "top-level"), _KNOWN_RESPONSE_SPACE, "response_space"
    )
    _close_schema(_require(raw, "factor_z", "top-level"), _KNOWN_FACTOR_Z, "factor_z")
    _close_schema(
        _require(raw, "identification", "top-level"), _KNOWN_IDENTIFICATION, "identification"
    )
    _close_schema(_require(raw, "metric", "top-level"), _KNOWN_METRIC, "metric")
    _close_schema(_require(raw, "inference", "top-level"), _KNOWN_INFERENCE, "inference")
    _close_schema(_require(raw, "regimes", "top-level"), _KNOWN_REGIMES, "regimes")

    baselines = _require(raw, "baselines", "top-level")
    _close_schema(baselines, _KNOWN_BASELINES, "baselines")
    _close_schema(
        _require(baselines, "gears", "baselines"), _KNOWN_BASELINE_GEARS, "baselines.gears"
    )
    _close_schema(_require(baselines, "cpa", "baselines"), _KNOWN_BASELINE_CPA, "baselines.cpa")

    _close_schema(
        _require(raw, "leakage_control", "top-level"),
        _KNOWN_LEAKAGE_CONTROL,
        "leakage_control",
    )
    _close_schema(_require(raw, "phasing", "top-level"), _KNOWN_PHASING, "phasing")
    _close_schema(_require(raw, "futility", "top-level"), _KNOWN_FUTILITY, "futility")
    _close_schema(_require(raw, "seal", "top-level"), _KNOWN_SEAL, "seal")
    _close_schema(_require(raw, "seeds", "top-level"), _KNOWN_SEEDS, "seeds")

    verdict = _require(raw, "verdict", "top-level")
    _close_schema(verdict, _KNOWN_VERDICT, "verdict")
    _close_schema(
        _require(verdict, "gi_learnable_win", "verdict"),
        _KNOWN_VERDICT_GI_LEARNABLE_WIN,
        "verdict.gi_learnable_win",
    )
    _close_schema(
        _require(verdict, "partial", "verdict"),
        _KNOWN_VERDICT_PARTIAL,
        "verdict.partial",
    )
    _close_schema(
        _require(verdict, "no_distinct_win", "verdict"),
        _KNOWN_VERDICT_NO_DISTINCT_WIN,
        "verdict.no_distinct_win",
    )


def _validate_activation_requirements(value: Any) -> tuple[str, ...]:
    """Validate the activation-requirements list against the registered set."""
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise Phase2ConfigError("activation_requirements must be a list of strings")
    got = tuple(value)
    if got != _EXPECTED_ACTIVATION_REQUIREMENTS:
        raise Phase2ConfigError(
            "activation_requirements must match the registered set exactly: "
            f"expected {list(_EXPECTED_ACTIVATION_REQUIREMENTS)}, got {list(got)}"
        )
    return got


def _validate_factor_z(block: dict[str, Any]) -> tuple[tuple[int, ...], tuple[int, ...], int]:
    """Validate factor dimensions and the total_k = expression + ESM arithmetic."""
    _close_schema(block, _KNOWN_FACTOR_Z, "factor_z")

    total_k_raw = _require(block, "total_k_grid", "factor_z")
    expression_raw = _require(block, "expression_dims", "factor_z")
    if not isinstance(total_k_raw, list) or not isinstance(expression_raw, list):
        raise Phase2ConfigError("factor_z.total_k_grid/expression_dims must be lists")
    # Strict int typing (M): reject string ints, floats and bools rather than
    # coercing them, so a typo in a frozen dimension grid is surfaced.
    total_k_grid = tuple(_strict_int(x, "factor_z.total_k_grid entry") for x in total_k_raw)
    expression_dims = tuple(
        _strict_int(x, "factor_z.expression_dims entry") for x in expression_raw
    )
    esm_projection_dim = _strict_int(
        _require(block, "esm_projection_dim", "factor_z"), "factor_z.esm_projection_dim"
    )

    if esm_projection_dim != _EXPECTED_ESM_PROJECTION_DIM:
        raise Phase2ConfigError(
            f"esm_projection_dim must be {_EXPECTED_ESM_PROJECTION_DIM}, got {esm_projection_dim}"
        )
    if total_k_grid != _EXPECTED_TOTAL_K_GRID:
        raise Phase2ConfigError(
            f"total_k_grid must be {list(_EXPECTED_TOTAL_K_GRID)}, got {list(total_k_grid)}"
        )
    if expression_dims != _EXPECTED_EXPRESSION_DIMS:
        raise Phase2ConfigError(
            f"expression_dims must be {list(_EXPECTED_EXPRESSION_DIMS)}, "
            f"got {list(expression_dims)}"
        )
    if len(total_k_grid) != len(expression_dims):
        raise Phase2ConfigError("total_k_grid and expression_dims must have equal length")
    for total, expr in zip(total_k_grid, expression_dims):
        if total != expr + esm_projection_dim:
            raise Phase2ConfigError(
                "ESM dimension arithmetic violated: total_k "
                f"({total}) != expression_dim ({expr}) + esm_projection_dim ({esm_projection_dim})"
            )
    return total_k_grid, expression_dims, esm_projection_dim


def _validate_identification(block: dict[str, Any]) -> tuple[tuple[float, ...], int, float]:
    """Validate the exact preregistered ridge grid."""
    _close_schema(block, _KNOWN_IDENTIFICATION, "identification")
    raw = _require(block, "lambda_grid", "identification")
    if not isinstance(raw, list) or any(isinstance(x, bool) for x in raw):
        raise Phase2ConfigError("identification.lambda_grid must be a numeric list")
    try:
        grid = tuple(float(x) for x in raw)
    except (TypeError, ValueError) as exc:
        raise Phase2ConfigError("identification.lambda_grid must be a numeric list") from exc
    if grid != _EXPECTED_LAMBDA_GRID:
        raise Phase2ConfigError(
            "identification.lambda_grid must match the registered grid exactly: "
            f"expected {list(_EXPECTED_LAMBDA_GRID)}, got {list(grid)}"
        )
    oof_folds = _strict_int(
        _require(block, "oof_folds", "identification"), "identification.oof_folds"
    )
    tolerance_raw = _require(block, "uncovered_tolerance", "identification")
    if isinstance(tolerance_raw, bool) or not isinstance(tolerance_raw, (int, float)):
        raise Phase2ConfigError("identification.uncovered_tolerance must be numeric")
    tolerance = float(tolerance_raw)
    if oof_folds != _EXPECTED_OOF_FOLDS or tolerance != _EXPECTED_UNCOVERED_TOLERANCE:
        raise Phase2ConfigError(
            "identification OOF controls must match the preregistration exactly: "
            f"oof_folds={_EXPECTED_OOF_FOLDS}, "
            f"uncovered_tolerance={_EXPECTED_UNCOVERED_TOLERANCE}"
        )
    return grid, oof_folds, tolerance


def _validate_seeds(block: dict[str, Any]) -> tuple[int, tuple[int, ...]]:
    """Validate the fixed split seed and registered model seeds."""
    _close_schema(block, _KNOWN_SEEDS, "seeds")
    split_seed = _strict_int(_require(block, "split_seed", "seeds"), "seeds.split_seed")
    raw = _require(block, "registered_seeds", "seeds")
    if not isinstance(raw, list):
        raise Phase2ConfigError("seeds.registered_seeds must be a list")
    registered = tuple(_strict_int(x, "seeds.registered_seeds entry") for x in raw)
    if split_seed != _EXPECTED_SPLIT_SEED or registered != _EXPECTED_REGISTERED_SEEDS:
        raise Phase2ConfigError(
            "seeds must match the preregistration exactly: "
            f"split_seed={_EXPECTED_SPLIT_SEED}, registered={list(_EXPECTED_REGISTERED_SEEDS)}"
        )
    return split_seed, registered


def _validate_baselines(block: dict[str, Any]) -> tuple[str, ...]:
    """Validate and return the exact Phase-2a/2b method roster."""
    _close_schema(block, _KNOWN_BASELINES, "baselines")
    lower_bounds = _require(block, "lower_bounds", "baselines")
    ladder = _require(block, "ablation_ladder", "baselines")
    if lower_bounds != ["no_change", "perturbation_mean"]:
        raise Phase2ConfigError("baselines.lower_bounds must be [no_change, perturbation_mean]")
    if ladder != ["l1_bilinear_identifiable", "l2_saturation", "l3_hypernetwork"]:
        raise Phase2ConfigError("baselines.ablation_ladder does not match the registered ladder")
    return _EXPECTED_METHOD_ROSTER


def _validate_metric(
    block: dict[str, Any],
) -> tuple[str, str, float, float, tuple[SecondaryMetricSpec, ...], bool]:
    """Validate the primary metric formula/margins and secondary governance."""
    _close_schema(block, _KNOWN_METRIC, "metric")

    primary = _require(block, "primary", "metric")
    if primary != _EXPECTED_METRIC_PRIMARY:
        raise Phase2ConfigError(
            f"metric.primary must be {_EXPECTED_METRIC_PRIMARY!r}, got {primary!r}"
        )

    formula = _require(block, "formula", "metric")
    if formula != _EXPECTED_METRIC_FORMULA:
        raise Phase2ConfigError(
            f"metric.formula must be {_EXPECTED_METRIC_FORMULA!r}, got {formula!r}"
        )

    material_margin = float(_require(block, "material_margin_vs_additive", "metric"))
    if material_margin != _EXPECTED_MATERIAL_MARGIN_VS_ADDITIVE:
        raise Phase2ConfigError(
            "metric.material_margin_vs_additive must be "
            f"{_EXPECTED_MATERIAL_MARGIN_VS_ADDITIVE}, got {material_margin}"
        )

    learned_margin = float(_require(block, "learned_comparator_margin", "metric"))
    if learned_margin != _EXPECTED_LEARNED_COMPARATOR_MARGIN:
        raise Phase2ConfigError(
            "metric.learned_comparator_margin must be "
            f"{_EXPECTED_LEARNED_COMPARATOR_MARGIN}, got {learned_margin}"
        )

    secondary_are_gates = _require(block, "secondary_are_verdict_gates", "metric")
    if not isinstance(secondary_are_gates, bool):
        raise Phase2ConfigError("metric.secondary_are_verdict_gates must be a boolean")

    secondary_raw = _require(block, "secondary", "metric")
    if not isinstance(secondary_raw, list) or not all(isinstance(x, str) for x in secondary_raw):
        raise Phase2ConfigError("metric.secondary must be a list of strings")
    if tuple(secondary_raw) != tuple(_EXPECTED_SECONDARY_METRICS):
        raise Phase2ConfigError(
            "metric.secondary must match the registered roster exactly: expected "
            f"{list(_EXPECTED_SECONDARY_METRICS)}, got {list(secondary_raw)}"
        )

    specs: list[SecondaryMetricSpec] = []
    for name in secondary_raw:
        gov = _EXPECTED_SECONDARY_METRICS[name]
        spec = SecondaryMetricSpec(
            name=name,
            definition=gov["definition"],
            interval_method=gov["interval_method"],
            material_regression_margin=gov["material_regression_margin"],
            governance_note=gov["governance_note"],
        )
        # Every registered secondary must carry a definition, an interval method,
        # and either a material-regression margin OR a governance note.
        if not spec.definition or not spec.interval_method:
            raise Phase2ConfigError(f"secondary metric {name!r} missing definition/interval")
        if spec.material_regression_margin is None and not spec.governance_note:
            raise Phase2ConfigError(
                f"descriptive-only secondary metric {name!r} requires a governance note"
            )
        specs.append(spec)

    return (
        primary,
        formula,
        material_margin,
        learned_margin,
        tuple(specs),
        secondary_are_gates,
    )


def _validate_inference(
    block: dict[str, Any],
) -> tuple[tuple[str, ...], str, str, bool, float, int]:
    """Validate the comparator roster and bootstrap settings."""
    _close_schema(block, _KNOWN_INFERENCE, "inference")

    family_raw = _require(block, "comparator_family", "inference")
    if not isinstance(family_raw, list) or not all(isinstance(x, str) for x in family_raw):
        raise Phase2ConfigError("inference.comparator_family must be a list of strings")
    comparator_family = tuple(family_raw)
    if comparator_family != _EXPECTED_COMPARATOR_FAMILY:
        raise Phase2ConfigError(
            "inference.comparator_family must match the exact roster: expected "
            f"{list(_EXPECTED_COMPARATOR_FAMILY)}, got {list(comparator_family)}"
        )

    method = _require(block, "method", "inference")
    if method != _EXPECTED_INFERENCE_METHOD:
        raise Phase2ConfigError(
            f"inference.method must be {_EXPECTED_INFERENCE_METHOD!r}, got {method!r}"
        )

    resampling_unit = _require(block, "resampling_unit", "inference")
    if resampling_unit != _EXPECTED_RESAMPLING_UNIT:
        raise Phase2ConfigError(
            f"inference.resampling_unit must be {_EXPECTED_RESAMPLING_UNIT!r}, "
            f"got {resampling_unit!r}"
        )

    shared = _require(block, "shared_resamples_across_contrasts", "inference")
    if not isinstance(shared, bool):
        raise Phase2ConfigError("inference.shared_resamples_across_contrasts must be a boolean")

    family_confidence = float(_require(block, "family_confidence", "inference"))
    if family_confidence != _EXPECTED_FAMILY_CONFIDENCE:
        raise Phase2ConfigError(
            f"inference.family_confidence must be {_EXPECTED_FAMILY_CONFIDENCE}, "
            f"got {family_confidence}"
        )

    bootstrap_replicates = int(_require(block, "bootstrap_replicates", "inference"))
    if bootstrap_replicates != _EXPECTED_BOOTSTRAP_REPLICATES:
        raise Phase2ConfigError(
            "inference.bootstrap_replicates must be "
            f"{_EXPECTED_BOOTSTRAP_REPLICATES}, got {bootstrap_replicates}"
        )

    return (
        comparator_family,
        method,
        resampling_unit,
        shared,
        family_confidence,
        bootstrap_replicates,
    )


def _validate_roles(
    split_block: dict[str, Any], response_block: dict[str, Any]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Validate split role names and response-space fit roles."""
    if not isinstance(split_block, dict):
        raise Phase2ConfigError("split must be a mapping")
    roles = _require(split_block, "roles", "split")
    if not isinstance(roles, dict):
        raise Phase2ConfigError("split.roles must be a mapping")
    role_names = tuple(roles.keys())
    if role_names != _EXPECTED_ROLE_NAMES:
        raise Phase2ConfigError(
            "split.roles names must match the registered roles exactly: expected "
            f"{list(_EXPECTED_ROLE_NAMES)}, got {list(role_names)}"
        )

    if not isinstance(response_block, dict):
        raise Phase2ConfigError("response_space must be a mapping")
    fit_roles_raw = _require(response_block, "fit_roles", "response_space")
    if not isinstance(fit_roles_raw, list) or not all(isinstance(x, str) for x in fit_roles_raw):
        raise Phase2ConfigError("response_space.fit_roles must be a list of strings")
    fit_roles = tuple(fit_roles_raw)
    if fit_roles != _EXPECTED_FIT_ROLES:
        raise Phase2ConfigError(
            f"response_space.fit_roles must be {list(_EXPECTED_FIT_ROLES)}, got {list(fit_roles)}"
        )
    return role_names, fit_roles


def assert_scientific_mode_allowed(
    config: ComposePhase2Config,
    *,
    fixture_mode: bool = False,
    activation_record: ActivationRecord | None = None,
    git_is_clean: bool | None = None,
) -> None:
    """Guard the boundary between fixture mode and a real-data scientific run.

    Fixture mode is not accepted by this scientific guard. Scientific mode is
    permitted only when **every**
    precondition holds:

    1. the config ``status`` is exactly ``active``;
    2. an :class:`ActivationRecord` is supplied whose protocol/phase match the
       config;
    3. the working tree is a clean, committed Git state (``git_is_clean=True``);
    4. the activation record carries a non-empty evidence hash for every
       activation requirement the config declares.

    Parameters
    ----------
    config
        The loaded, validated Phase-2 config.
    fixture_mode
        Deprecated compatibility parameter. ``True`` is rejected; use the
        dedicated bounded fixture entry point.
    activation_record
        Owner authorization record; required in scientific mode.
    git_is_clean
        Whether the repository working tree is clean and committed; required in
        scientific mode. The caller resolves this (e.g. from ``git status``) so
        this guard performs no I/O.

    Raises
    ------
    ScientificModeError
        If scientific mode is requested but any precondition fails. The current
        ``preregistered_activation_blocked`` config always fails here.
    """
    if fixture_mode:
        raise ScientificModeError(
            "scientific-mode guard does not authorize fixture execution; "
            "use the dedicated bounded fixture entry point"
        )

    if not config.is_active:
        raise ScientificModeError(
            f"scientific mode blocked: config status is {config.status!r}, not 'active'. "
            "A blocked / pre-registered config cannot start a real-data pipeline."
        )

    if activation_record is None:
        raise ScientificModeError("scientific mode blocked: no owner activation record provided")

    if activation_record.approved_protocol != config.protocol:
        raise ScientificModeError(
            "scientific mode blocked: activation record protocol "
            f"{activation_record.approved_protocol!r} != config protocol {config.protocol!r}"
        )
    if activation_record.approved_phase != config.phase:
        raise ScientificModeError(
            "scientific mode blocked: activation record phase "
            f"{activation_record.approved_phase!r} != config phase {config.phase!r}"
        )

    if git_is_clean is not True:
        raise ScientificModeError(
            "scientific mode blocked: working tree is not a clean committed Git state "
            f"(git_is_clean={git_is_clean!r})"
        )

    missing = [
        req
        for req in config.activation_requirements
        if not activation_record.evidence_hashes.get(req)
    ]
    if missing:
        raise ScientificModeError(
            f"scientific mode blocked: missing activation evidence hashes for {missing}"
        )
