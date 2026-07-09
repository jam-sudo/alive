"""Tests for alive.compose.config2 — written FIRST per TDD protocol.

These tests pin the COMPOSE-K562-v1 Phase-2 strict config loader and the
execution-mode guard. The central safety property is: a config whose status is
``preregistered_activation_blocked`` MUST NOT be able to start a real-data
scientific pipeline. The canonical config is ACTIVE as of the 2026-06-30
activation; the blocked-rejection invariant is pinned here via a synthetic
blocked config, and the activated canonical config is checked to pass the gate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from alive.compose.config2 import (
    ActivationRecord,
    ComposePhase2Config,
    Phase2ConfigError,
    ScientificModeError,
    SecondaryMetricSpec,
    assert_scientific_mode_allowed,
    load_compose_phase2_config,
)

CANON = "configs/compose_k562_v1_phase2.yaml"
_EVIDENCE_FILES = {
    "real_norman_phi_rank_and_condition_report": (
        "docs/activation-evidence/compose/real_norman_phi_rank_report.json"
    ),
    "regime_specific_detectable_effect_analysis": (
        "docs/activation-evidence/compose/real_norman_detectable_effect_report.json"
    ),
    "finalized_norman_data_card_and_sha256": "docs/data-cards/norman_compose_k562_v1.json",
    "gears_cpa_reproducible_dependency_lock": (
        "docs/activation-evidence/compose/gears_cpa_dependency_lock.json"
    ),
    "independent_compose_outcome_store_and_access_audit": "src/alive/compose/outcome_store.py",
    "phase2_plan_metric_leakage_and_seal_integration_tests": "tests/alive/compose/test_phase2b.py",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _raw() -> dict:
    """Return a fresh mutable copy of the canonical raw YAML mapping."""
    with open(CANON) as handle:
        return yaml.safe_load(handle)


def _write(tmp_path, mapping) -> str:
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(mapping, sort_keys=False))
    return str(p)


def _activation_record() -> ActivationRecord:
    """A fully populated owner activation record covering every requirement."""
    cfg = load_compose_phase2_config(CANON)
    return ActivationRecord(
        owner="owner@example.org",
        approved_protocol="COMPOSE-K562-v1",
        approved_phase=2,
        evidence_hashes={
            req: "sha256:" + hashlib.sha256(Path(_EVIDENCE_FILES[req]).read_bytes()).hexdigest()
            for req in cfg.activation_requirements
        },
        evidence_files=dict(_EVIDENCE_FILES),
    )


def _fully_activated_raw() -> dict:
    """Return a synthetic config with every local activation blocker resolved."""
    raw = _raw()
    raw["status"] = "active"
    raw["regimes"]["power_status"] = "established_from_registered_report"
    raw["baselines"]["gears"]["revision"] = "cell-gears==0.1.2"
    raw["baselines"]["gears"]["environment_status"] = "pinned_and_fresh_sync_verified"
    raw["baselines"]["gears"]["approximation_bias_report_sha256"] = "a" * 64
    raw["baselines"]["cpa"]["revision"] = "cpa-tools==0.8.5"
    raw["baselines"]["cpa"]["environment_status"] = "pinned_and_fresh_sync_verified"
    return raw


def _activation_record_for_config(tmp_path: Path, cfg: ComposePhase2Config) -> ActivationRecord:
    """Create synthetic READY evidence whose lineage matches ``cfg`` exactly."""
    files = dict(_EVIDENCE_FILES)
    for requirement in (
        "real_norman_phi_rank_and_condition_report",
        "regime_specific_detectable_effect_analysis",
    ):
        payload = json.loads(Path(files[requirement]).read_text(encoding="utf-8"))
        payload["protocol"] = cfg.protocol
        payload["config_sha256"] = cfg.config_sha256
        payload["activation"] = "READY — synthetic unit-test evidence"
        path = tmp_path / f"{requirement}.json"
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        files[requirement] = str(path)
    return ActivationRecord(
        owner="owner@example.org",
        approved_protocol=cfg.protocol,
        approved_phase=cfg.phase,
        evidence_hashes={
            req: "sha256:" + hashlib.sha256(Path(files[req]).read_bytes()).hexdigest()
            for req in cfg.activation_requirements
        },
        evidence_files=files,
    )


# ---------------------------------------------------------------------------
# round-trip + value validation
# ---------------------------------------------------------------------------
def test_canonical_round_trip():
    cfg = load_compose_phase2_config(CANON)
    assert isinstance(cfg, ComposePhase2Config)
    assert cfg.protocol == "COMPOSE-K562-v1"
    assert cfg.phase == 2
    assert cfg.status == "active"


def test_config_is_frozen():
    cfg = load_compose_phase2_config(CANON)
    with pytest.raises((AttributeError, TypeError)):
        cfg.status = "active"  # type: ignore[misc]


def test_total_k_grid_and_esm_arithmetic():
    cfg = load_compose_phase2_config(CANON)
    assert cfg.total_k_grid == (4, 6, 8)
    assert cfg.esm_projection_dim == 2
    assert cfg.expression_dims == (2, 4, 6)
    # total_k = expression_dims + esm_projection_dim, element-wise.
    for total, expr in zip(cfg.total_k_grid, cfg.expression_dims):
        assert total == expr + cfg.esm_projection_dim


def test_runtime_contract_values_are_exposed_and_hashed():
    cfg = load_compose_phase2_config(CANON)
    assert cfg.lambda_grid == (0.0, 0.001, 0.01, 0.1)
    assert cfg.oof_folds == 3
    assert cfg.uncovered_tolerance == 0.75
    assert cfg.split_seed == 11
    assert cfg.registered_seeds == (11, 23, 37)
    assert cfg.sealed_minimum_n == 1
    assert cfg.method_roster == (
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
    assert len(cfg.config_sha256) == 64


@pytest.mark.parametrize("bad", [0, -1, True, "1", 1.0])
def test_minimum_sealed_n_is_strict_registered_positive_int(tmp_path, bad):
    raw = _raw()
    raw["seal"]["minimum_sealed_n"] = bad
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_esm_arithmetic_mismatch_rejected(tmp_path):
    raw = _raw()
    raw["factor_z"]["expression_dims"] = [2, 4, 7]  # 7 + 2 = 9 != 8
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_esm_projection_dim_must_be_two(tmp_path):
    raw = _raw()
    raw["factor_z"]["esm_projection_dim"] = 3
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_total_k_grid_must_be_4_6_8(tmp_path):
    raw = _raw()
    raw["factor_z"]["total_k_grid"] = [4, 6, 10]
    raw["factor_z"]["expression_dims"] = [2, 4, 8]  # keep arithmetic self-consistent
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_exact_comparator_roster():
    cfg = load_compose_phase2_config(CANON)
    assert cfg.comparator_family == ("additive", "gears", "cpa", "id_only", "l3_hypernetwork")


def test_comparator_roster_must_be_exact(tmp_path):
    raw = _raw()
    raw["inference"]["comparator_family"] = ["additive", "gears", "cpa", "id_only"]  # missing l3
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_comparator_roster_reordered_rejected(tmp_path):
    raw = _raw()
    raw["inference"]["comparator_family"] = [
        "gears",
        "additive",
        "cpa",
        "id_only",
        "l3_hypernetwork",
    ]
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_metric_formula_and_margins():
    cfg = load_compose_phase2_config(CANON)
    assert cfg.metric_primary == "paired_relative_error_reduction"
    assert cfg.metric_formula == (
        "(mean(error_comparator) - mean(error_l1)) / max(mean(error_comparator), 1e-12)"
    )
    assert cfg.material_margin_vs_additive == pytest.approx(0.05)
    assert cfg.learned_comparator_margin == pytest.approx(0.0)


def test_futility_rule_is_loaded_and_frozen():
    cfg = load_compose_phase2_config(CANON)
    assert cfg.futility_conditions == (
        "dev_oof_delta_below_threshold",
        "rank_condition_fail",
        "measurability_fail",
    )
    assert cfg.dev_oof_metric == "paired_relative_error_reduction_vs_additive"
    assert cfg.dev_oof_threshold == 0.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conditions", ["anything"]),
        ("dev_oof_metric", "unregistered"),
        ("dev_oof_threshold", 999.0),
    ],
)
def test_futility_rule_change_rejected(tmp_path, field, value):
    raw = _raw()
    raw["futility"][field] = value
    with pytest.raises(Phase2ConfigError, match="futility"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_metric_formula_change_rejected(tmp_path):
    raw = _raw()
    raw["metric"]["formula"] = "1 - mean(error_l1) / mean(error_comparator)"
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_metric_margin_change_rejected(tmp_path):
    raw = _raw()
    raw["metric"]["material_margin_vs_additive"] = 0.10
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_secondary_metrics_definitions():
    cfg = load_compose_phase2_config(CANON)
    names = {s.name for s in cfg.secondary_metrics}
    assert names == {"gi_explained_fraction", "gi_structure_recovery"}
    # Every registered secondary must carry a definition, an interval method and
    # either a material-regression margin OR a governance note that it is
    # descriptive-only. The config sets secondary_are_verdict_gates: false, so
    # both are descriptive-only and must declare a governance note.
    assert cfg.secondary_are_verdict_gates is False
    for spec in cfg.secondary_metrics:
        assert isinstance(spec, SecondaryMetricSpec)
        assert spec.definition  # non-empty
        assert spec.interval_method  # non-empty
        # descriptive-only secondaries: margin may be None but the governance
        # note explaining the absence must be present.
        if spec.material_regression_margin is None:
            assert spec.governance_note
        else:
            assert spec.material_regression_margin >= 0.0


def test_unknown_secondary_metric_rejected(tmp_path):
    raw = _raw()
    raw["metric"]["secondary"] = [
        "gi_explained_fraction",
        "gi_structure_recovery",
        "mystery_metric",
    ]
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_bootstrap_settings():
    cfg = load_compose_phase2_config(CANON)
    assert cfg.bootstrap_replicates == 10000
    assert cfg.family_confidence == pytest.approx(0.95)
    assert cfg.inference_method == "max_deviation_bootstrap"
    assert cfg.resampling_unit == "perturbation_pair"
    assert cfg.shared_resamples_across_contrasts is True


def test_bootstrap_replicates_change_rejected(tmp_path):
    raw = _raw()
    raw["inference"]["bootstrap_replicates"] = 1000
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_role_names():
    cfg = load_compose_phase2_config(CANON)
    assert cfg.role_names == ("combo_calibration", "sealed_double_unseen", "sealed_single_unseen")
    assert cfg.fit_roles == ("control", "singles")


def test_role_names_change_rejected(tmp_path):
    raw = _raw()
    raw["split"]["roles"] = {
        "combo_calibration": "x",
        "sealed_double_unseen": "y",
        # missing sealed_single_unseen
    }
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_activation_requirements():
    cfg = load_compose_phase2_config(CANON)
    assert cfg.activation_requirements == (
        "real_norman_phi_rank_and_condition_report",
        "regime_specific_detectable_effect_analysis",
        "finalized_norman_data_card_and_sha256",
        "gears_cpa_reproducible_dependency_lock",
        "independent_compose_outcome_store_and_access_audit",
        "phase2_plan_metric_leakage_and_seal_integration_tests",
    )


# ---------------------------------------------------------------------------
# unknown / missing key rejection (frozen schema)
# ---------------------------------------------------------------------------
def test_unknown_top_level_key_rejected(tmp_path):
    raw = _raw()
    raw["bogus_top_key"] = 1
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_unknown_nested_key_rejected(tmp_path):
    raw = _raw()
    raw["factor_z"]["bogus_nested"] = 1
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_missing_top_level_key_rejected(tmp_path):
    raw = _raw()
    del raw["metric"]
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_missing_nested_key_rejected(tmp_path):
    raw = _raw()
    del raw["inference"]["bootstrap_replicates"]
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_empty_config_rejected(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(str(p))


# ---------------------------------------------------------------------------
# full schema closure on EVERY pre-registered block + nested dicts (I1)
# ---------------------------------------------------------------------------
# Representative blocks across the config: a flat block (seal), a nested
# sub-block via its parent (verdict / verdict.no_distinct_win), an inner role
# dict (split.roles) and a nested baseline package dict (baselines.gears).
# Each must reject both an unknown inner key and a deleted required inner key.

# (block-path, callable that injects an unknown key, callable that deletes a key)
_UNKNOWN_KEY_CASES = [
    ("seal", lambda raw: raw["seal"].__setitem__("bogus_inner", 1)),
    ("verdict", lambda raw: raw["verdict"].__setitem__("bogus_inner", 1)),
    (
        "verdict.no_distinct_win",
        lambda raw: raw["verdict"]["no_distinct_win"].__setitem__("bogus_inner", 1),
    ),
    ("split.roles", lambda raw: raw["split"]["roles"].__setitem__("bogus_role", "x")),
    ("baselines.gears", lambda raw: raw["baselines"]["gears"].__setitem__("bogus_inner", 1)),
    ("data", lambda raw: raw["data"].__setitem__("bogus_inner", 1)),
    ("eligibility", lambda raw: raw["eligibility"].__setitem__("bogus_inner", 1)),
    ("identification", lambda raw: raw["identification"].__setitem__("bogus_inner", 1)),
    ("seeds", lambda raw: raw["seeds"].__setitem__("bogus_inner", 1)),
]

_MISSING_KEY_CASES = [
    ("seal", lambda raw: raw["seal"].pop("write_once")),
    ("verdict", lambda raw: raw["verdict"].pop("integrity_clause_disclaimer")),
    (
        "verdict.no_distinct_win",
        lambda raw: raw["verdict"]["no_distinct_win"].pop("additive_simultaneous_lower_bound_lte"),
    ),
    ("split.roles", lambda raw: raw["split"]["roles"].pop("sealed_single_unseen")),
    ("baselines.gears", lambda raw: raw["baselines"]["gears"].pop("package")),
    ("data", lambda raw: raw["data"].pop("cell_line")),
    ("eligibility", lambda raw: raw["eligibility"].pop("min_cells_per_gene")),
    ("identification", lambda raw: raw["identification"].pop("estimator")),
    ("seeds", lambda raw: raw["seeds"].pop("split_seed")),
]


@pytest.mark.parametrize(
    "block, inject", _UNKNOWN_KEY_CASES, ids=[c[0] for c in _UNKNOWN_KEY_CASES]
)
def test_unknown_inner_key_rejected_per_block(tmp_path, block, inject):
    raw = _raw()
    inject(raw)
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


@pytest.mark.parametrize(
    "block, delete", _MISSING_KEY_CASES, ids=[c[0] for c in _MISSING_KEY_CASES]
)
def test_missing_inner_key_rejected_per_block(tmp_path, block, delete):
    raw = _raw()
    delete(raw)
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_seal_unknown_inner_key_rejected(tmp_path):
    raw = _raw()
    raw["seal"]["bogus_inner"] = True
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_seal_missing_inner_key_rejected(tmp_path):
    raw = _raw()
    del raw["seal"]["write_once"]
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_verdict_unknown_inner_key_rejected(tmp_path):
    raw = _raw()
    raw["verdict"]["gi_learnable_win"]["bogus_inner"] = 1
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_verdict_missing_inner_key_rejected(tmp_path):
    raw = _raw()
    del raw["verdict"]["gi_learnable_win"]["additive_simultaneous_lower_bound_gt"]
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_split_roles_unknown_inner_key_rejected(tmp_path):
    raw = _raw()
    raw["split"]["roles"]["both_seen"] = "x"
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_baselines_gears_unknown_inner_key_rejected(tmp_path):
    raw = _raw()
    raw["baselines"]["gears"]["bogus_inner"] = "x"
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_baselines_gears_missing_inner_key_rejected(tmp_path):
    raw = _raw()
    del raw["baselines"]["gears"]["environment_status"]
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


# ---------------------------------------------------------------------------
# per-method prediction-representation lock (Task 5)
# ---------------------------------------------------------------------------
def test_canonical_baseline_representations_are_locked():
    cfg = load_compose_phase2_config(CANON)
    reps = {name: (rep, bias) for name, rep, bias in cfg.baseline_representations}
    assert reps["gears"] == ("raw_pseudobulk_approximation", None)
    assert reps["cpa"] == ("cell_raw_counts", None)


def test_null_pseudobulk_bias_keeps_activation_blocked():
    # The canonical config sets the GEARS pseudobulk bias report to null, which
    # keeps that method's representation scientifically activation-blocked.
    cfg = load_compose_phase2_config(CANON)
    assert cfg.pseudobulk_representation_activation_blocked is True


def test_measured_pseudobulk_bias_lifts_activation_block(tmp_path):
    raw = _raw()
    raw["baselines"]["gears"]["approximation_bias_report_sha256"] = "a" * 64
    cfg = load_compose_phase2_config(_write(tmp_path, raw))
    assert cfg.pseudobulk_representation_activation_blocked is False
    reps = {name: bias for name, _representation, bias in cfg.baseline_representations}
    assert reps["gears"] == "a" * 64


def test_unregistered_representation_rejected(tmp_path):
    raw = _raw()
    raw["baselines"]["gears"]["prediction_representation"] = "made_up_representation"
    with pytest.raises(Phase2ConfigError, match="prediction_representation"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_pseudobulk_malformed_bias_sha_rejected(tmp_path):
    raw = _raw()
    raw["baselines"]["gears"]["approximation_bias_report_sha256"] = "not-a-64-hex-sha"
    with pytest.raises(Phase2ConfigError, match="approximation_bias_report_sha256"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_cell_level_representation_rejects_non_null_bias(tmp_path):
    # cpa is an exact cell_raw_counts representation; a non-null bias report is
    # meaningless for an exact representation and must be rejected.
    raw = _raw()
    raw["baselines"]["cpa"]["approximation_bias_report_sha256"] = "b" * 64
    with pytest.raises(Phase2ConfigError, match="null for the exact representation"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_missing_representation_key_rejected(tmp_path):
    raw = _raw()
    del raw["baselines"]["gears"]["prediction_representation"]
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


# ---------------------------------------------------------------------------
# status enum (I2)
# ---------------------------------------------------------------------------
def test_status_typo_rejected(tmp_path):
    raw = _raw()
    raw["status"] = "activ"  # typo: must not silently behave as blocked
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_status_unknown_value_rejected(tmp_path):
    raw = _raw()
    raw["status"] = "blocked"  # not a registered status
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_status_active_accepted(tmp_path):
    raw = _raw()
    raw["status"] = "active"
    cfg = load_compose_phase2_config(_write(tmp_path, raw))
    assert cfg.status == "active"
    assert cfg.is_active is True


# ---------------------------------------------------------------------------
# strict int typing in factor_z (M)
# ---------------------------------------------------------------------------
def test_string_int_in_total_k_grid_rejected(tmp_path):
    raw = _raw()
    raw["factor_z"]["total_k_grid"] = ["4", 6, 8]  # string int must NOT be coerced
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_string_int_in_expression_dims_rejected(tmp_path):
    raw = _raw()
    raw["factor_z"]["expression_dims"] = ["2", 4, 6]
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_bool_in_esm_projection_dim_rejected(tmp_path):
    raw = _raw()
    raw["factor_z"]["esm_projection_dim"] = True  # bool is not an int here
    with pytest.raises(Phase2ConfigError):
        load_compose_phase2_config(_write(tmp_path, raw))


# ---------------------------------------------------------------------------
# fixture mode cannot be authorized by the scientific guard
# ---------------------------------------------------------------------------
def test_scientific_guard_rejects_fixture_mode():
    # Fixture mode is rejected regardless of config status (it is the first guard
    # check, before status). Verified here on the canonical (now active) config.
    cfg = load_compose_phase2_config(CANON)
    with pytest.raises(ScientificModeError, match="fixture"):
        assert_scientific_mode_allowed(cfg, fixture_mode=True)


def test_fixture_mode_cannot_bypass_activation_record():
    cfg = load_compose_phase2_config(CANON)
    with pytest.raises(ScientificModeError, match="fixture"):
        assert_scientific_mode_allowed(
            cfg,
            fixture_mode=True,
            activation_record=None,
            git_is_clean=False,
        )


# ---------------------------------------------------------------------------
# the core safety property: a BLOCKED config cannot start a real pipeline
# ---------------------------------------------------------------------------
def test_blocked_config_cannot_start_scientific_pipeline(tmp_path):
    # Safety invariant preserved after the 2026-06-30 activation: a config whose
    # status is ``preregistered_activation_blocked`` cannot start a real pipeline
    # even with a full activation record + clean tree. The canonical config is now
    # ``active``, so this pins the guard's blocked-rejection via a synthetic
    # blocked config.
    raw = _raw()
    raw["status"] = "preregistered_activation_blocked"
    cfg = load_compose_phase2_config(_write(tmp_path, raw))
    assert cfg.status == "preregistered_activation_blocked"
    with pytest.raises(ScientificModeError):
        assert_scientific_mode_allowed(
            cfg,
            fixture_mode=False,
            activation_record=_activation_record(),
            git_is_clean=True,
        )


def test_activated_canonical_config_is_blocked_by_missing_pseudobulk_bias_report():
    # Status activation alone is insufficient: the canonical GEARS representation
    # remains an approximation whose registered bias report checksum is null.
    cfg = load_compose_phase2_config(CANON)
    assert cfg.status == "active"
    assert "baselines.approximation_bias_report_sha256" in cfg.activation_blockers
    with pytest.raises(ScientificModeError, match="activation blockers"):
        assert_scientific_mode_allowed(
            cfg,
            fixture_mode=False,
            activation_record=_activation_record(),
            git_is_clean=True,
        )


def test_scientific_mode_requires_activation_record(tmp_path):
    raw = _raw()
    raw["status"] = "active"
    cfg = load_compose_phase2_config(_write(tmp_path, raw))
    with pytest.raises(ScientificModeError):
        assert_scientific_mode_allowed(
            cfg,
            fixture_mode=False,
            activation_record=None,
            git_is_clean=True,
        )


def test_scientific_mode_requires_clean_git(tmp_path):
    raw = _raw()
    raw["status"] = "active"
    cfg = load_compose_phase2_config(_write(tmp_path, raw))
    with pytest.raises(ScientificModeError):
        assert_scientific_mode_allowed(
            cfg,
            fixture_mode=False,
            activation_record=_activation_record(),
            git_is_clean=False,
        )


def test_scientific_mode_requires_all_evidence_hashes(tmp_path):
    raw = _raw()
    raw["status"] = "active"
    cfg = load_compose_phase2_config(_write(tmp_path, raw))
    rec = _activation_record()
    incomplete = ActivationRecord(
        owner=rec.owner,
        approved_protocol=rec.approved_protocol,
        approved_phase=rec.approved_phase,
        evidence_hashes=dict(list(rec.evidence_hashes.items())[:-1]),  # drop one
        evidence_files=rec.evidence_files,
    )
    with pytest.raises(ScientificModeError):
        assert_scientific_mode_allowed(
            cfg,
            fixture_mode=False,
            activation_record=incomplete,
            git_is_clean=True,
        )


def test_scientific_mode_requires_matching_protocol(tmp_path):
    raw = _raw()
    raw["status"] = "active"
    cfg = load_compose_phase2_config(_write(tmp_path, raw))
    rec = _activation_record()
    wrong = ActivationRecord(
        owner=rec.owner,
        approved_protocol="TG-K562-v1",  # mismatched protocol
        approved_phase=2,
        evidence_hashes=rec.evidence_hashes,
        evidence_files=rec.evidence_files,
    )
    with pytest.raises(ScientificModeError):
        assert_scientific_mode_allowed(
            cfg,
            fixture_mode=False,
            activation_record=wrong,
            git_is_clean=True,
        )


def test_scientific_mode_allowed_when_fully_activated(tmp_path):
    raw = _fully_activated_raw()
    cfg = load_compose_phase2_config(_write(tmp_path, raw))
    assert cfg.activation_blockers == ()
    # Every runtime and evidence-lineage precondition is satisfied -> no raise.
    assert_scientific_mode_allowed(
        cfg,
        fixture_mode=False,
        activation_record=_activation_record_for_config(tmp_path, cfg),
        git_is_clean=True,
    )


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("power", "regimes.power_status"),
        ("gears_revision", "baselines.gears.revision"),
        ("gears_environment", "baselines.gears.environment_status"),
        ("cpa_revision", "baselines.cpa.revision"),
        ("cpa_environment", "baselines.cpa.environment_status"),
    ],
)
def test_each_unresolved_activation_field_blocks_scientific_mode(tmp_path, field, expected):
    raw = _fully_activated_raw()
    if field == "power":
        raw["regimes"]["power_status"] = "unestablished_activation_blocker"
    else:
        method, key = field.split("_", 1)
        raw["baselines"][method]["environment_status" if key == "environment" else "revision"] = (
            "unpinned_activation_blocker" if key == "environment" else None
        )
    cfg = load_compose_phase2_config(_write(tmp_path, raw))
    assert expected in cfg.activation_blockers
    with pytest.raises(ScientificModeError, match=expected.replace(".", r"\.")):
        assert_scientific_mode_allowed(
            cfg,
            activation_record=_activation_record_for_config(tmp_path, cfg),
            git_is_clean=True,
        )


def test_stale_config_bound_evidence_blocks_scientific_mode(tmp_path):
    cfg = load_compose_phase2_config(_write(tmp_path, _fully_activated_raw()))
    assert cfg.activation_blockers == ()
    with pytest.raises(ScientificModeError, match="config_sha256 mismatch"):
        assert_scientific_mode_allowed(
            cfg,
            activation_record=_activation_record(),
            git_is_clean=True,
        )


def test_empty_evidence_hashes_blocks_scientific_mode(tmp_path):
    raw = _raw()
    raw["status"] = "active"
    cfg = load_compose_phase2_config(_write(tmp_path, raw))
    rec = ActivationRecord(
        owner="owner@example.org",
        approved_protocol="COMPOSE-K562-v1",
        approved_phase=2,
        evidence_hashes={},
        evidence_files={},
    )
    with pytest.raises(ScientificModeError):
        assert_scientific_mode_allowed(
            cfg,
            fixture_mode=False,
            activation_record=rec,
            git_is_clean=True,
        )


def test_malformed_evidence_hash_blocks_scientific_mode():
    cfg = load_compose_phase2_config(CANON)
    rec = _activation_record()
    malformed = dict(rec.evidence_hashes)
    malformed[cfg.activation_requirements[0]] = "present-but-not-a-sha256"
    with pytest.raises(ScientificModeError, match="64 lowercase hex"):
        assert_scientific_mode_allowed(
            cfg,
            activation_record=ActivationRecord(
                owner=rec.owner,
                approved_protocol=rec.approved_protocol,
                approved_phase=rec.approved_phase,
                evidence_hashes=malformed,
                evidence_files=rec.evidence_files,
            ),
            git_is_clean=True,
        )


def test_extra_evidence_requirement_blocks_scientific_mode():
    cfg = load_compose_phase2_config(CANON)
    rec = _activation_record()
    extra = dict(rec.evidence_hashes)
    extra["unregistered_requirement"] = "sha256:" + "a" * 64
    with pytest.raises(ScientificModeError, match="roster mismatch"):
        assert_scientific_mode_allowed(
            cfg,
            activation_record=ActivationRecord(
                owner=rec.owner,
                approved_protocol=rec.approved_protocol,
                approved_phase=rec.approved_phase,
                evidence_hashes=extra,
                evidence_files={**rec.evidence_files, "unregistered_requirement": CANON},
            ),
            git_is_clean=True,
        )


def test_default_call_is_scientific_mode_and_blocked():
    """A bare guard call (no fixture flag) defaults to scientific mode and must block."""
    cfg = load_compose_phase2_config(CANON)
    with pytest.raises(ScientificModeError):
        assert_scientific_mode_allowed(cfg)
