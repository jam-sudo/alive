"""Direct tests for the shared approximation-bias pre-seal binding.

These tests pin the exact provenance roster owned by the shared helper and use
real v2 report validation for input-tamper cases. They open no seal and construct
no outcome store.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import MappingProxyType

import pytest

from alive.compose.approximation_bias import (
    ApproximationBiasValidationError,
    basis_config_sha256_from_final_config,
    measurement_contract_sha256,
)
from alive.compose.config2 import load_compose_phase2_config
from alive.compose.driver import bias_report_preseal
from alive.compose.driver.bias_report_preseal import resolve_pinned_approximation_bias_evidence
from alive.compose.driver.carrier_loader import load_run_spec_carrier
from alive.compose.driver.run_spec import load_resolved_run_spec
from alive.compose.fit_role import build_response_projection
from alive.provenance import sha256_json
from tests.alive.compose.driver.scientific_carrier_support import (
    build_scientific_carrier_fixture,
)


@pytest.fixture
def scientific_context(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "stage", repo_root=tmp_path / "repo")
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
    return spec, config, carrier.response_artifact


def test_shared_helper_pins_exact_expected_provenance_roster(scientific_context, monkeypatch):
    spec, config, response = scientific_context
    captured = {}
    sentinel = object()

    def capture_load(path, **kwargs):
        captured["path"] = Path(path)
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(bias_report_preseal, "load_approximation_bias_report", capture_load)
    result = resolve_pinned_approximation_bias_evidence(spec, config, response_artifact=response)

    projection = build_response_projection(
        response["response_space"],
        gene_order=response["gene_order"],
        control_mean=response["control_mean"],
        raw_data_sha256=response["raw_data_sha256"],
    )
    declaration = spec.scientific["approximation_bias_report"]
    assert result is sentinel
    assert captured["path"] == Path(declaration["path"])
    assert captured["expected_content_sha256"] == declaration["sha256"]
    assert captured["expected_protocol"] == config.protocol
    assert captured["expected_basis_config_sha256"] == basis_config_sha256_from_final_config(
        spec.pre_seal["config"].path,
        expected_report_sha256=declaration["sha256"],
    )
    assert captured["expected_measurement_contract_sha256"] == measurement_contract_sha256()
    assert captured["expected_git_commit"] == spec.approved_git_sha
    assert captured["expected_provenance"] == {
        "norman_source_sha256": response["raw_data_sha256"],
        "fit_role_artifact_sha256": spec.pre_seal["fit_role_artifact"].sha256,
        "response_projection_sha256": sha256_json(projection),
        "gene_order_sha256": projection["gene_order_sha256"],
        "pca_dim": len(projection["control_mean"]),
        "registered_seeds": list(config.registered_seeds),
    }


def test_shared_helper_rejects_each_run_bound_input_tamper(scientific_context):
    spec, config, response = scientific_context

    raw_tamper = dict(response)
    raw_tamper["raw_data_sha256"] = "e" * 64

    projection_tamper = dict(response)
    projection_tamper["control_mean"] = [float(value) + 0.125 for value in response["control_mean"]]

    pre_seal_tamper = dict(spec.pre_seal)
    pre_seal_tamper["fit_role_artifact"] = dataclasses.replace(
        spec.pre_seal["fit_role_artifact"], sha256="f" * 64
    )
    fit_role_tamper = dataclasses.replace(spec, pre_seal=MappingProxyType(pre_seal_tamper))

    seed_tamper = dataclasses.replace(config, registered_seeds=(101, 103, 107))

    cases = (
        ("norman_source_sha256", spec, config, raw_tamper),
        ("fit_role_artifact_sha256", fit_role_tamper, config, response),
        ("response_projection_sha256", spec, config, projection_tamper),
        ("registered_seeds", spec, seed_tamper, response),
    )
    for field, candidate_spec, candidate_config, candidate_response in cases:
        with pytest.raises(ApproximationBiasValidationError, match=field):
            resolve_pinned_approximation_bias_evidence(
                candidate_spec,
                candidate_config,
                response_artifact=candidate_response,
            )
