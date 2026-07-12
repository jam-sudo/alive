"""Typed ActivationProvenanceInputs assembly (spec §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from alive.compose.config2 import load_compose_phase2_config
from alive.compose.driver.carrier_loader import _assemble_provenance_inputs
from alive.compose.driver.run_spec import load_resolved_run_spec
from alive.compose.phase2b import ActivationProvenanceInputs
from alive.provenance import capture_environment, sha256_file
from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture


def _spec_config_env(bundle):
    spec = load_resolved_run_spec(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        mode_expected="scientific",
    )
    config = load_compose_phase2_config(spec.pre_seal["config"].path)
    env = capture_environment(
        spec.scientific["dependency_manifest"]["path"],
        config.registered_seeds,
        repo_dir=bundle.repo_root,
    )
    return spec, config, env


def test_provenance_inputs_map_to_authoritative_sources(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, config, env = _spec_config_env(bundle)
    inputs = _assemble_provenance_inputs(spec, config, environment=env)
    assert isinstance(inputs, ActivationProvenanceInputs)
    # processed_sha256 == raw_asset digest (data card declares raw asset as processed).
    assert inputs.processed_sha256 == sha256_file(spec.pre_seal["raw_asset"].path)
    assert inputs.feature_bank_sha256 == sha256_file(spec.pre_seal["feature_bank"].path)
    assert inputs.gears_revision == "0.1.2"
    assert inputs.cpa_revision == "0.8.5"
    assert inputs.device == "cpu"
    assert inputs.precision == "float32"
    assert inputs.git_commit == bundle.approved_git_sha
    assert env.registered_seeds == config.registered_seeds


def test_data_card_not_declaring_processed_asset_rejects(tmp_path):
    # If the data card does not identify the raw asset as the processed analysis asset,
    # assembly fails closed rather than recording a raw digest as processed_sha256 (§4).
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, config, env = _spec_config_env(bundle)
    import json

    card_path = Path(spec.pre_seal["data_card"].path)
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card.pop("processed_analysis_asset")
    card_path.write_text(json.dumps(card, sort_keys=True, separators=(",", ":")))
    with pytest.raises(ValueError, match="processed"):
        _assemble_provenance_inputs(spec, config, environment=env)
