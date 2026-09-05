"""Typed ActivationProvenanceInputs assembly (spec §4)."""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from types import MappingProxyType

import pytest

from alive.compose.config2 import load_compose_phase2_config
from alive.compose.driver.carrier_loader import _assemble_provenance_inputs
from alive.compose.driver.run_spec import PathSha, load_resolved_run_spec
from alive.compose.phase2b import ActivationProvenanceInputs, Phase2bError
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
    mutated = json.dumps(card, sort_keys=True, separators=(",", ":")).encode("utf-8")
    card_path.write_bytes(mutated)
    # Pre-seal reads are digest-bound since 2026-08-25: the bytes consumed must hash
    # to the digest the run spec declared. Rewriting the card on disk without
    # re-declaring its digest now trips THAT guard first, which would leave this
    # test passing for a reason its name does not claim. Re-declare so the subject
    # under test is still "the card does not name a processed asset".
    spec = dataclasses.replace(
        spec,
        pre_seal=MappingProxyType(
            {
                **spec.pre_seal,
                "data_card": PathSha(
                    path=str(card_path), sha256=hashlib.sha256(mutated).hexdigest()
                ),
            }
        ),
    )
    with pytest.raises(ValueError, match="processed"):
        _assemble_provenance_inputs(spec, config, environment=env)


_LANES = {
    "raw_asset": (lambda spec: spec.pre_seal["raw_asset"].path, "processed"),
    "feature_bank": (lambda spec: spec.pre_seal["feature_bank"].path, "feature_bank"),
    "dependency_manifest": (
        lambda spec: spec.scientific["dependency_manifest"]["path"],
        "dependency_lock",
    ),
    "gears_requirements": (
        lambda spec: spec.worker_blocks["gears"].requirements_lock.path,
        "gears_requirements",
    ),
    "cpa_requirements": (
        lambda spec: spec.worker_blocks["cpa"].requirements_lock.path,
        "cpa_requirements",
    ),
}


@pytest.mark.parametrize("lane", sorted(_LANES))
def test_a_pre_seal_input_swapped_after_the_run_spec_verified_it_is_refused(tmp_path, lane):
    """The five declared digests must cross the boundary, not be discarded at it.

    `load_resolved_run_spec` verifies every `PathSha` it accepts. This assembler
    then unwrapped five of them to bare `.path` and handed the paths to a function
    that re-read the files and recorded whatever digest they had by then. A
    replacement landing between the two -- the feature-bank residual of the
    2026-09-03 review and the worker-requirements lane of 2026-09-05, three lines
    apart in this call -- was recorded as provenance and refused by nothing. Each
    lane is now handed to the builder as `(path, declared sha256)` and a mismatch
    is refused before any digest is recorded.
    """
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, config, env = _spec_config_env(bundle)
    locate, field = _LANES[lane]
    path = Path(locate(spec))
    # Append rather than rewrite: a requirements lock keeps its pins, so the only
    # reason left to refuse is that the bytes are no longer the declared ones.
    path.write_bytes(path.read_bytes() + b"\n# replaced after the run spec verified it\n")

    with pytest.raises(Phase2bError, match=field):
        _assemble_provenance_inputs(spec, config, environment=env)
