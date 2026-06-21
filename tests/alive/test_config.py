"""Tests for alive.config — locked-config schema, validation, and run-ID hashing.

Run with: uv run pytest -q tests/alive/test_config.py
"""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from alive.config import ConfigError, load_config

# Path to the canonical reference config that ships with the repo.
CANON_CONFIG = (
    Path(__file__).parent.parent.parent / "configs" / "cartographer_trust_gate_k562_v1.yaml"
)


# ---------------------------------------------------------------------------
# Round-trip tests: load the canonical config and spot-check values
# ---------------------------------------------------------------------------


def test_round_trip_loads():
    """The canonical YAML loads without error."""
    cfg = load_config(CANON_CONFIG)
    assert cfg is not None


def test_experiment_name():
    cfg = load_config(CANON_CONFIG)
    assert cfg.experiment == "cartographer_trust_gate_k562_v1"


def test_manifest_seed():
    cfg = load_config(CANON_CONFIG)
    assert cfg.manifest_seed == 20260621


def test_split_fractions():
    cfg = load_config(CANON_CONFIG)
    assert cfg.split_fractions.base_train == pytest.approx(0.45)
    assert cfg.split_fractions.method_development == pytest.approx(0.25)
    assert cfg.split_fractions.conformal_calibration == pytest.approx(0.15)
    assert cfg.split_fractions.sealed_evaluation == pytest.approx(0.15)


def test_response_space_fields():
    cfg = load_config(CANON_CONFIG)
    rs = cfg.response_space
    assert rs.normalization == "library_size_10000_log1p"
    assert rs.hvg_count == 2000
    assert rs.pca_dims == 50
    assert rs.cell_cap == 96
    assert rs.min_cells == 64
    assert rs.cell_sampling_repeats == 8
    assert rs.energy_block_size == 256


def test_perturbation_features():
    cfg = load_config(CANON_CONFIG)
    pf = cfg.perturbation_features
    assert pf.primary == "esm2_t33_650M_UR50D_mean_pool"
    assert pf.standardize_on == "base_train"
    assert pf.missing_policy == "exclude_before_split"


def test_base_model_fields():
    cfg = load_config(CANON_CONFIG)
    bm = cfg.base_model
    assert bm.family == "additive_ridge"
    assert list(bm.ridge_grid) == [0.01, 0.1, 1.0, 10.0, 100.0]
    assert bm.cv_folds == 5
    assert bm.ensemble_members == 20


def test_method_development_fields():
    cfg = load_config(CANON_CONFIG)
    md = cfg.method_development
    assert md.cv_folds == 5
    assert list(md.k_grid) == [5, 10, 20, 40]
    assert list(md.feature_weight_grid) == [0.25, 0.5, 0.75, 1.0]
    assert list(md.gbm_estimators_grid) == [50, 100, 200]
    assert list(md.ridge_grid) == [0.01, 0.1, 1.0, 10.0, 100.0]
    assert list(md.registered_seeds) == [11, 23, 47, 71, 101]


def test_decision_fields():
    cfg = load_config(CANON_CONFIG)
    d = cfg.decision
    assert d.target_selection_coverage == pytest.approx(0.70)
    assert d.conformal_alpha == pytest.approx(0.10)
    assert d.minimum_sealed_perturbations == 200


def test_inference_fields():
    cfg = load_config(CANON_CONFIG)
    inf = cfg.inference
    assert inf.bootstrap_replicates == 10000
    assert inf.family_confidence == pytest.approx(0.95)
    assert inf.secondary_augrc_noninferiority_margin == pytest.approx(0.02)


def test_futility_fields():
    cfg = load_config(CANON_CONFIG)
    f = cfg.futility
    assert f.enabled is True
    assert set(f.comparators) == {"gbm_error", "residual_only"}
    assert f.minimum_relevant_delta == pytest.approx(0.01)
    assert f.family_confidence == pytest.approx(0.90)
    assert f.rule == "stop_if_any_simultaneous_upper_bound_le_minimum"


# ---------------------------------------------------------------------------
# Validation: split_fractions
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path, data: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(data))
    return p


def _base_dict() -> dict:
    """Minimal valid config dict (mirrors canonical)."""
    return {
        "experiment": "test_exp",
        "manifest_seed": 42,
        "split_fractions": {
            "base_train": 0.45,
            "method_development": 0.25,
            "conformal_calibration": 0.15,
            "sealed_evaluation": 0.15,
        },
        "response_space": {
            "normalization": "library_size_10000_log1p",
            "hvg_count": 2000,
            "pca_dims": 50,
            "cell_cap": 96,
            "min_cells": 64,
            "cell_sampling_repeats": 8,
            "energy_block_size": 256,
        },
        "perturbation_features": {
            "primary": "esm2_t33_650M_UR50D_mean_pool",
            "standardize_on": "base_train",
            "missing_policy": "exclude_before_split",
        },
        "base_model": {
            "family": "additive_ridge",
            "ridge_grid": [0.01, 0.1, 1.0, 10.0, 100.0],
            "cv_folds": 5,
            "ensemble_members": 20,
        },
        "method_development": {
            "cv_folds": 5,
            "k_grid": [5, 10, 20, 40],
            "feature_weight_grid": [0.25, 0.5, 0.75, 1.0],
            "gbm_estimators_grid": [50, 100, 200],
            "ridge_grid": [0.01, 0.1, 1.0, 10.0, 100.0],
            "registered_seeds": [11, 23, 47, 71, 101],
        },
        "decision": {
            "target_selection_coverage": 0.70,
            "conformal_alpha": 0.10,
            "minimum_sealed_perturbations": 200,
        },
        "inference": {
            "bootstrap_replicates": 10000,
            "family_confidence": 0.95,
            "secondary_augrc_noninferiority_margin": 0.02,
        },
        "futility": {
            "enabled": True,
            "comparators": ["gbm_error", "residual_only"],
            "minimum_relevant_delta": 0.01,
            "family_confidence": 0.90,
            "rule": "stop_if_any_simultaneous_upper_bound_le_minimum",
        },
    }


def test_fractions_dont_sum_to_one(tmp_path):
    d = _base_dict()
    d["split_fractions"]["base_train"] = 0.50  # sums to 1.05
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError, match="sum"):
        load_config(p)


def test_fraction_value_gte_one(tmp_path):
    d = _base_dict()
    d["split_fractions"]["base_train"] = 1.0
    d["split_fractions"]["method_development"] = 0.0  # but also causes sum issue
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError):
        load_config(p)


def test_fraction_value_lte_zero(tmp_path):
    d = _base_dict()
    d["split_fractions"]["sealed_evaluation"] = -0.15
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError):
        load_config(p)


def test_fractions_wrong_keys(tmp_path):
    d = _base_dict()
    d["split_fractions"]["extra_key"] = 0.05
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError):
        load_config(p)


# ---------------------------------------------------------------------------
# Validation: unknown keys
# ---------------------------------------------------------------------------


def test_unknown_top_level_key(tmp_path):
    d = _base_dict()
    d["rogue_field"] = "oops"
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError, match="[Uu]nknown"):
        load_config(p)


def test_unknown_nested_key_in_response_space(tmp_path):
    d = _base_dict()
    d["response_space"]["extra"] = 99
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError, match="[Uu]nknown"):
        load_config(p)


# ---------------------------------------------------------------------------
# Validation: inference.bootstrap_replicates
# ---------------------------------------------------------------------------


def test_small_bootstrap_replicates(tmp_path):
    d = _base_dict()
    d["inference"]["bootstrap_replicates"] = 1500
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError, match="2000"):
        load_config(p)


# ---------------------------------------------------------------------------
# Validation: futility comparators
# ---------------------------------------------------------------------------


def test_unknown_futility_comparator(tmp_path):
    d = _base_dict()
    d["futility"]["comparators"] = ["gbm_error", "not_a_real_comparator"]
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError, match="[Cc]omparator"):
        load_config(p)


def test_empty_futility_comparators(tmp_path):
    d = _base_dict()
    d["futility"]["comparators"] = []
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError):
        load_config(p)


# ---------------------------------------------------------------------------
# Validation: probability/coverage fields
# ---------------------------------------------------------------------------


def test_conformal_alpha_out_of_range(tmp_path):
    d = _base_dict()
    d["decision"]["conformal_alpha"] = 1.1
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError):
        load_config(p)


def test_family_confidence_out_of_range(tmp_path):
    d = _base_dict()
    d["inference"]["family_confidence"] = 0.0
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError):
        load_config(p)


def test_minimum_sealed_perturbations_zero(tmp_path):
    d = _base_dict()
    d["decision"]["minimum_sealed_perturbations"] = 0
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError):
        load_config(p)


# ---------------------------------------------------------------------------
# Validation: grid lists must be non-empty; registered_seeds unique
# ---------------------------------------------------------------------------


def test_empty_ridge_grid(tmp_path):
    d = _base_dict()
    d["base_model"]["ridge_grid"] = []
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError):
        load_config(p)


def test_duplicate_registered_seeds(tmp_path):
    d = _base_dict()
    d["method_development"]["registered_seeds"] = [11, 11, 23]
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError, match="[Uu]nique"):
        load_config(p)


# ---------------------------------------------------------------------------
# Deterministic run-ID
# ---------------------------------------------------------------------------


def test_run_id_deterministic_across_key_order(tmp_path):
    """Two YAML files differing only in key order must yield the same run_id."""
    base = _base_dict()
    # Reorder top-level keys
    reordered = {k: base[k] for k in reversed(list(base.keys()))}

    p1 = tmp_path / "c1.yaml"
    p2 = tmp_path / "c2.yaml"
    p1.write_text(yaml.dump(base))
    p2.write_text(yaml.dump(reordered))

    cfg1 = load_config(p1)
    cfg2 = load_config(p2)
    assert cfg1.config_digest == cfg2.config_digest


def test_run_id_changes_with_manifest_seed(tmp_path):
    base = _base_dict()
    modified = copy.deepcopy(base)
    modified["manifest_seed"] = 99999

    p1 = tmp_path / "c1.yaml"
    p2 = tmp_path / "c2.yaml"
    p1.write_text(yaml.dump(base))
    p2.write_text(yaml.dump(modified))

    cfg1 = load_config(p1)
    cfg2 = load_config(p2)
    assert cfg1.config_digest != cfg2.config_digest


def test_run_id_is_hex_string(tmp_path):
    cfg = load_config(CANON_CONFIG)
    rid = cfg.config_digest
    assert isinstance(rid, str)
    assert len(rid) == 16
    int(rid, 16)  # must be valid hex


def test_run_id_stable_across_calls():
    """Calling config_digest multiple times on the same Config returns the same value."""
    cfg = load_config(CANON_CONFIG)
    assert cfg.config_digest == cfg.config_digest


# ---------------------------------------------------------------------------
# Fix 1: missing required keys must raise ConfigError (not KeyError)
# ---------------------------------------------------------------------------


def test_missing_top_level_section_raises_config_error(tmp_path):
    """Omitting an entire required section (inference) raises ConfigError."""
    d = _base_dict()
    del d["inference"]
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError, match="inference"):
        load_config(p)


def test_missing_nested_required_field_raises_config_error(tmp_path):
    """Omitting a single nested field (inference.bootstrap_replicates) raises ConfigError."""
    d = _base_dict()
    del d["inference"]["bootstrap_replicates"]
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError, match="bootstrap_replicates"):
        load_config(p)


# ---------------------------------------------------------------------------
# Fix 2: empty registered_seeds must raise ConfigError
# ---------------------------------------------------------------------------


def test_empty_registered_seeds_raises_config_error(tmp_path):
    """method_development.registered_seeds = [] raises ConfigError."""
    d = _base_dict()
    d["method_development"]["registered_seeds"] = []
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError):
        load_config(p)


# ---------------------------------------------------------------------------
# Fix 5: run_id is stable across processes
# ---------------------------------------------------------------------------


def test_run_id_stable_across_processes():
    """run_id computed in a separate subprocess matches the in-process value."""
    in_process_id = load_config(CANON_CONFIG).config_digest
    canon_path = str(CANON_CONFIG)
    code = (
        "from pathlib import Path; "
        "from alive.config import load_config; "
        f"cfg = load_config(Path({canon_path!r})); "
        "print(cfg.config_digest)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    cross_process_id = result.stdout.strip()
    assert cross_process_id == in_process_id


# ---------------------------------------------------------------------------
# feature_extraction: round-trip from canonical YAML
# ---------------------------------------------------------------------------


def test_feature_extraction_canonical_round_trip():
    """Canonical YAML feature_extraction section loads to the correct values."""
    cfg = load_config(CANON_CONFIG)
    fe = cfg.feature_extraction
    assert fe.max_residues == 1022
    assert fe.long_sequence_policy == "error"
    assert fe.max_batch_tokens == 16384


# ---------------------------------------------------------------------------
# feature_extraction: absent section → defaults
# ---------------------------------------------------------------------------


def test_feature_extraction_absent_defaults(tmp_path):
    """A YAML without feature_extraction loads with the default FeatureExtraction values."""
    d = _base_dict()
    # _base_dict() does NOT include feature_extraction → should be defaulted
    assert "feature_extraction" not in d
    p = _write_yaml(tmp_path, d)
    cfg = load_config(p)
    fe = cfg.feature_extraction
    assert fe.max_residues == 1022
    assert fe.long_sequence_policy == "error"
    assert fe.max_batch_tokens == 16384


# ---------------------------------------------------------------------------
# feature_extraction: validation rules
# ---------------------------------------------------------------------------


def test_feature_extraction_bad_policy_string(tmp_path):
    """long_sequence_policy must be 'error' or 'truncate'; other values raise ConfigError."""
    d = _base_dict()
    d["feature_extraction"] = {
        "max_residues": 1022,
        "long_sequence_policy": "ignore",
        "max_batch_tokens": 16384,
    }
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError, match="long_sequence_policy"):
        load_config(p)


def test_feature_extraction_max_batch_too_small(tmp_path):
    """max_batch_tokens must be >= max_residues + 2; violation raises ConfigError."""
    d = _base_dict()
    d["feature_extraction"] = {
        "max_residues": 1022,
        "long_sequence_policy": "error",
        "max_batch_tokens": 1023,  # < 1022 + 2 = 1024
    }
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError, match="max_batch_tokens"):
        load_config(p)


def test_feature_extraction_max_residues_lt_one(tmp_path):
    """max_residues must be >= 1; 0 raises ConfigError."""
    d = _base_dict()
    d["feature_extraction"] = {
        "max_residues": 0,
        "long_sequence_policy": "error",
        "max_batch_tokens": 16384,
    }
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError, match="max_residues"):
        load_config(p)


def test_feature_extraction_unknown_key_rejected(tmp_path):
    """Unknown keys inside feature_extraction raise ConfigError."""
    d = _base_dict()
    d["feature_extraction"] = {
        "max_residues": 1022,
        "long_sequence_policy": "error",
        "max_batch_tokens": 16384,
        "unknown_param": 99,
    }
    p = _write_yaml(tmp_path, d)
    with pytest.raises(ConfigError, match="[Uu]nknown"):
        load_config(p)


def test_feature_extraction_truncate_policy_valid(tmp_path):
    """'truncate' is a valid long_sequence_policy value."""
    d = _base_dict()
    d["feature_extraction"] = {
        "max_residues": 512,
        "long_sequence_policy": "truncate",
        "max_batch_tokens": 8192,
    }
    p = _write_yaml(tmp_path, d)
    cfg = load_config(p)
    assert cfg.feature_extraction.long_sequence_policy == "truncate"
    assert cfg.feature_extraction.max_residues == 512


def test_feature_extraction_max_batch_exactly_minimum_valid(tmp_path):
    """max_batch_tokens == max_residues + 2 is the boundary — must be accepted."""
    d = _base_dict()
    d["feature_extraction"] = {
        "max_residues": 100,
        "long_sequence_policy": "error",
        "max_batch_tokens": 102,  # exactly 100 + 2
    }
    p = _write_yaml(tmp_path, d)
    cfg = load_config(p)
    assert cfg.feature_extraction.max_batch_tokens == 102
