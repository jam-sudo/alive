"""Full scientific carrier assembly (spec §5) + trusted_repo_root gating."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alive.compose.config2 import ActivationRecord, load_compose_phase2_config
from alive.compose.driver.carrier_loader import (
    RunSpecCarrier,
    load_run_spec_carrier,
)
from alive.compose.driver.phase2b_cmd import _resolve_approximation_bias_report
from alive.compose.driver.run_spec import RunSpecError, load_resolved_run_spec
from alive.compose.phase2b import ActivationProvenanceInputs
from alive.provenance import EnvironmentInfo, sha256_json
from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture


def test_scientific_carrier_fully_assembles(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    carrier = load_run_spec_carrier(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        trusted_repo_root=bundle.repo_root,
    )
    assert isinstance(carrier, RunSpecCarrier)
    assert carrier.mode == "scientific"
    assert isinstance(carrier.activation_record, ActivationRecord)
    assert carrier.git_is_clean is True
    assert isinstance(carrier.environment, EnvironmentInfo)
    assert carrier.environment.git_commit == bundle.approved_git_sha
    spec = load_resolved_run_spec(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        mode_expected="scientific",
    )
    config = load_compose_phase2_config(spec.pre_seal["config"].path)
    assert carrier.environment.registered_seeds == config.registered_seeds
    assert isinstance(carrier.provenance_inputs, ActivationProvenanceInputs)
    assert Path(carrier.data_card_path).is_file()
    assert Path(carrier.raw_asset_path).is_file()
    # scientific sealed_outcome carries the phase2b-consumed keys, NOT the corpus triple.
    assert set(carrier.sealed_outcome) == {
        "manifest",
        "pair_index",
        "pair_index_manifest",
        "source_path",
        "source_file_sha256",
        "perturbation_column",
        "combo_sep",
    }


def test_phase2b_resolves_the_same_preseal_validated_bias_report(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    carrier = load_run_spec_carrier(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        trusted_repo_root=bundle.repo_root,
    )
    spec = load_resolved_run_spec(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        mode_expected="scientific",
    )
    config = load_compose_phase2_config(spec.pre_seal["config"].path)

    resolved = _resolve_approximation_bias_report(
        spec, config, response_artifact=carrier.response_artifact
    )

    assert resolved == Path(spec.scientific["approximation_bias_report"]["path"])


def test_scientific_carrier_rejects_missing_config_pinned_bias_report(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    raw = json.loads(bundle.spec_path.read_text(encoding="utf-8"))
    raw["scientific"]["approximation_bias_report"] = None
    body = {key: value for key, value in raw.items() if key != "self_checksum"}
    raw["self_checksum"] = sha256_json(body)
    bundle.spec_path.write_text(
        json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    with pytest.raises(RunSpecError, match="pins an approximation-bias SHA|carries no report"):
        load_run_spec_carrier(
            bundle.spec_path,
            approved_artifacts_root=bundle.approved_artifacts_root,
            trusted_repo_root=bundle.repo_root,
        )


def test_scientific_requires_trusted_repo_root(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    with pytest.raises(RunSpecError, match="trusted_repo_root"):
        load_run_spec_carrier(
            bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
        )


def test_fixture_rejects_trusted_repo_root(tmp_path):
    from alive.compose.driver.fixture_builder import build_compose_fixture

    bundle = build_compose_fixture(tmp_path)
    with pytest.raises(RunSpecError, match="trusted_repo_root"):
        load_run_spec_carrier(
            bundle.spec_path,
            approved_artifacts_root=bundle.approved_artifacts_root,
            trusted_repo_root=tmp_path,
        )


def test_wrong_head_fails_closed(tmp_path):
    from alive.compose.driver.scientific_runtime import ScientificRuntimeError

    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    import subprocess

    (bundle.repo_root / "extra.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "extra.txt"], cwd=bundle.repo_root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "advance"],
        cwd=bundle.repo_root,
        check=True,
        env={**__import__("os").environ, "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    # HEAD moved; the spec's approved_git_sha is now stale → fail closed.
    with pytest.raises(ScientificRuntimeError):
        load_run_spec_carrier(
            bundle.spec_path,
            approved_artifacts_root=bundle.approved_artifacts_root,
            trusted_repo_root=bundle.repo_root,
        )
