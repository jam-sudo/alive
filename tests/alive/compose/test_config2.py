"""Tests for alive.compose.config2 — written FIRST per TDD protocol.

These tests pin the COMPOSE-K562-v1 Phase-2 strict config loader and the
execution-mode guard. The central safety property is: a config whose status is
``preregistered_activation_blocked`` (the current candidate) MUST NOT be able to
start a real-data scientific pipeline.
"""

from __future__ import annotations

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
            req: f"sha256:{i:064x}" for i, req in enumerate(cfg.activation_requirements)
        },
    )


# ---------------------------------------------------------------------------
# round-trip + value validation
# ---------------------------------------------------------------------------
def test_canonical_round_trip():
    cfg = load_compose_phase2_config(CANON)
    assert isinstance(cfg, ComposePhase2Config)
    assert cfg.protocol == "COMPOSE-K562-v1"
    assert cfg.phase == 2
    assert cfg.status == "preregistered_activation_blocked"


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
    assert cfg.metric_formula == "1 - mean(error_l1) / max(mean(error_comparator), 1e-12)"
    assert cfg.material_margin_vs_additive == pytest.approx(0.05)
    assert cfg.learned_comparator_margin == pytest.approx(0.0)


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
# fixture mode is always allowed
# ---------------------------------------------------------------------------
def test_fixture_mode_always_allowed_even_when_blocked():
    cfg = load_compose_phase2_config(CANON)
    assert cfg.status != "active"
    # Must not raise: fixture mode is for synthetic / tiny-fixture tests only.
    assert_scientific_mode_allowed(cfg, fixture_mode=True)


def test_fixture_mode_allowed_without_activation_record():
    cfg = load_compose_phase2_config(CANON)
    assert_scientific_mode_allowed(
        cfg,
        fixture_mode=True,
        activation_record=None,
        git_is_clean=False,
    )


# ---------------------------------------------------------------------------
# the core safety property: a BLOCKED config cannot start a real pipeline
# ---------------------------------------------------------------------------
def test_blocked_config_cannot_start_scientific_pipeline():
    cfg = load_compose_phase2_config(CANON)
    assert cfg.status == "preregistered_activation_blocked"
    with pytest.raises(ScientificModeError):
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
    )
    with pytest.raises(ScientificModeError):
        assert_scientific_mode_allowed(
            cfg,
            fixture_mode=False,
            activation_record=wrong,
            git_is_clean=True,
        )


def test_scientific_mode_allowed_when_fully_activated(tmp_path):
    raw = _raw()
    raw["status"] = "active"
    cfg = load_compose_phase2_config(_write(tmp_path, raw))
    # All four scientific-mode preconditions satisfied -> must not raise.
    assert_scientific_mode_allowed(
        cfg,
        fixture_mode=False,
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
    )
    with pytest.raises(ScientificModeError):
        assert_scientific_mode_allowed(
            cfg,
            fixture_mode=False,
            activation_record=rec,
            git_is_clean=True,
        )


def test_default_call_is_scientific_mode_and_blocked():
    """A bare guard call (no fixture flag) defaults to scientific mode and must block."""
    cfg = load_compose_phase2_config(CANON)
    with pytest.raises(ScientificModeError):
        assert_scientific_mode_allowed(cfg)
