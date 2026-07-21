"""Tests for the from-disk stage-1 carrier loader (spec §0/§1.1/§11, Task 11.5).

Written FIRST per TDD. The committed fixture builder (``build_compose_fixture``)
is a write-once one-time producer, so the CLI could only run ONE process per
approved-root — the spec §11 three-independent-process ``phase2a → preflight →
phase2b`` e2e was impossible. :func:`load_run_spec_carrier` closes that gap by
reconstructing the DATA carrier (``Phase2aInputs`` / dev-store DATA / response
artifact / sealed-outcome DATA) purely from the ResolvedRunSpec's ALREADY-
serialized, SHA-verified on-disk stage-1 artifacts — writing NO new bytes.

The corpus is produced ONCE up-front (``build_compose_fixture(root)``); every
assertion then compares the LOADED carrier's consumed surface against the built
``FixtureBundle``, culminating in the seal-critical response-space fidelity gate
and an end-to-end ``run_phase2a_subcommand`` over the loaded carrier.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from alive.compose.config2 import ActivationRecord
from alive.compose.driver.carrier_loader import (
    RunSpecCarrier,
    load_run_spec_carrier,
)
from alive.compose.driver.fixture_builder import build_compose_fixture
from alive.compose.driver.phase2a_cmd import run_phase2a_subcommand
from alive.compose.driver.run_spec import RunSpecError
from alive.compose.phase2b import ActivationProvenanceInputs
from alive.compose.response import verify_response_artifact
from alive.provenance import EnvironmentInfo


# --------------------------------------------------------------------------- #
# Phase2aInputs reconstruction
# --------------------------------------------------------------------------- #
def test_loaded_phase2a_inputs_match_built(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    carrier = load_run_spec_carrier(
        bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
    )
    assert isinstance(carrier, RunSpecCarrier)
    assert Path(carrier.spec_path) == Path(bundle.spec_path)

    loaded = carrier.phase2a_inputs
    built = bundle.phase2a_inputs

    # content_checksum binds every field that can affect a frozen bundle: equal
    # here proves a byte-faithful reconstruction of the whole typed input set.
    assert loaded.content_checksum == built.content_checksum
    assert loaded.run_id == built.run_id
    assert loaded.seed == built.seed
    assert loaded.response_dim == built.response_dim
    assert loaded.gene_index == built.gene_index
    assert tuple(loaded.cal_pair_ids) == tuple(built.cal_pair_ids)
    assert tuple(loaded.k_total_grid) == tuple(built.k_total_grid)

    # arrays are serialized full-precision (no rounding) -> exact equality.
    assert np.array_equal(loaded.additive_cal, built.additive_cal)
    assert np.array_equal(loaded.eps_split_a, built.eps_split_a)
    assert np.array_equal(loaded.eps_split_b, built.eps_split_b)
    assert set(loaded.factors_by_k) == set(built.factors_by_k)
    for k in built.factors_by_k:
        assert np.array_equal(loaded.factors_by_k[k], built.factors_by_k[k])

    # model factories: same roster order, re-bound to the SAME class objects,
    # each callable (a factory).
    assert list(loaded.model_factories) == list(built.model_factories)
    for name, factory in loaded.model_factories.items():
        assert factory is built.model_factories[name]
        assert callable(factory)


# --------------------------------------------------------------------------- #
# dev-store DATA reconstruction
# --------------------------------------------------------------------------- #
def test_loaded_dev_store_audit_matches_built(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    carrier = load_run_spec_carrier(
        bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
    )
    loaded = carrier.dev_store_audit
    built = bundle.dev_store_audit

    assert np.array_equal(
        loaded["combo_calibration_eps"], np.asarray(built["combo_calibration_eps"])
    )
    assert tuple(loaded["combo_calibration_pair_ids"]) == tuple(built["combo_calibration_pair_ids"])
    # OutcomeAccessAudit is a frozen scalar dataclass -> value equality.
    assert loaded["access_audit"] == built["access_audit"]


# --------------------------------------------------------------------------- #
# response artifact reconstruction + fit-role spec
# --------------------------------------------------------------------------- #
def test_loaded_response_artifact_matches_built(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    carrier = load_run_spec_carrier(
        bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
    )
    loaded = carrier.response_artifact
    built = bundle.response_artifact

    # control_mean is serialized full-precision -> exact.
    assert np.array_equal(np.asarray(loaded["control_mean"]), np.asarray(built["control_mean"]))
    assert loaded["combined_checksum"] == built["combined_checksum"]
    assert list(loaded["gene_order"]) == list(built["gene_order"])
    assert loaded["raw_data_sha256"] == built["raw_data_sha256"]
    # FitRoleArtifactSpec is a frozen dataclass (scalars + role_counts dict) ->
    # value equality; must be the live object downstream reads .path/.sha256 from.
    assert loaded["fit_role_spec"] == built["fit_role_spec"]
    assert Path(loaded["fit_role_spec"].path).is_file()


# --------------------------------------------------------------------------- #
# ⚑ SEAL-CRITICAL response-space fidelity gate
# --------------------------------------------------------------------------- #
def test_response_space_checksum_fidelity_gate(tmp_path: Path) -> None:
    """The rehydrated response space must reproduce the EXACT checksums the
    phase2a hash gate binds — else the whole e2e fails closed (spec §3.1).

    The on-disk response-space payload is written ROUNDED (``artifact_bytes()``),
    so recomputing the bare space checksum from it reproduces the built space's
    checksum; and the COMBINED (space + control_mean) digest — the value stored
    in both ``expected_hashes['response_space_checksum']`` and
    ``Phase2aInputs.response_space_checksum`` (phase2a.py:410) — must reproduce
    exactly from the rehydrated space + control_mean.
    """
    bundle = build_compose_fixture(tmp_path)
    carrier = load_run_spec_carrier(
        bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
    )
    loaded_space = carrier.response_artifact["response_space"]
    built_space = bundle.response_artifact["response_space"]

    # bare space checksum: rounding is idempotent, so the rehydrated space's
    # artifact_bytes() reproduce the built space's self-checksum byte-for-byte.
    assert loaded_space.checksum == built_space.checksum

    # combined digest recomputed from the rehydrated space + control_mean must
    # equal the value the phase2a gate compares against (and the built one).
    _, _, combined = verify_response_artifact(
        loaded_space, carrier.response_artifact["control_mean"]
    )
    expected = bundle.expected_hashes["response_space_checksum"]
    assert combined == expected
    assert combined == carrier.phase2a_inputs.response_space_checksum
    assert combined == bundle.phase2a_inputs.response_space_checksum


# --------------------------------------------------------------------------- #
# sealed-outcome DATA reconstruction
# --------------------------------------------------------------------------- #
def test_loaded_sealed_outcome_matches_built(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    carrier = load_run_spec_carrier(
        bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
    )
    loaded = carrier.sealed_outcome
    built = bundle.sealed_outcome

    # pair_index: same canonical-pair keys + identical row-index arrays.
    assert set(loaded["pair_index"]) == set(built["pair_index"])
    for pair, rows in built["pair_index"].items():
        assert np.array_equal(loaded["pair_index"][pair], np.asarray(rows))

    assert Path(loaded["source_path"]) == Path(built["source_path"])
    assert loaded["source_file_sha256"] == built["source_file_sha256"]
    assert loaded["perturbation_column"] == built["perturbation_column"]
    assert loaded["combo_sep"] == built["combo_sep"]
    assert loaded["corpus_id"] == built["corpus_id"]
    assert loaded["source_sha256"] == built["source_sha256"]
    assert loaded["builder_code_sha256"] == built["builder_code_sha256"]

    # split manifest + pair-index manifest identity via their own checksums
    # (a disk JSON round-trip may swap tuples->lists; the checksums are stable).
    assert loaded["manifest"]["checksum"] == built["manifest"]["checksum"]
    assert (
        loaded["pair_index_manifest"]["self_checksum"]
        == built["pair_index_manifest"]["self_checksum"]
    )
    assert loaded["pair_index_manifest"]["source_file_sha256"] == built["source_file_sha256"]


# --------------------------------------------------------------------------- #
# the loaded carrier DRIVES phase2a to the same result (the whole point)
# --------------------------------------------------------------------------- #
def test_loaded_carrier_drives_phase2a_to_zero(tmp_path: Path) -> None:
    bundle = build_compose_fixture(tmp_path)
    carrier = load_run_spec_carrier(
        bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
    )
    rc = run_phase2a_subcommand(
        carrier,
        approved_artifacts_root=bundle.approved_artifacts_root,
        run_dir=bundle.run_dir,
    )
    assert rc == 0
    present = sorted(p.name for p in Path(bundle.run_dir).iterdir())
    assert present == sorted(
        [
            "frozen_prediction_bundle.json",
            "oof_fold_manifest.json",
            "phase2a_development_seed_variability.json",
            "phase2a_run_ledger.json",
        ]
    )


# --------------------------------------------------------------------------- #
# a bare scientific spec with no out-of-band trusted_repo_root fails closed
# (spec §5; a full scientific carrier assembly is covered separately in
# test_scientific_carrier_load.py)
# --------------------------------------------------------------------------- #
def test_scientific_mode_without_trusted_repo_root_raises_runspecerror(tmp_path: Path) -> None:
    spec_path = tmp_path / "scientific_spec.json"
    spec_path.write_text(json.dumps({"mode": "scientific"}), encoding="utf-8")
    with pytest.raises(RunSpecError, match="trusted_repo_root"):
        load_run_spec_carrier(spec_path, approved_artifacts_root=tmp_path)


def test_unreadable_spec_raises_runspecerror(tmp_path: Path) -> None:
    with pytest.raises(RunSpecError):
        load_run_spec_carrier(tmp_path / "does-not-exist.json", approved_artifacts_root=tmp_path)


# --------------------------------------------------------------------------- #
# discriminated-shape: mode + six scientific fields (§3)
# --------------------------------------------------------------------------- #
def test_fixture_carrier_has_scientific_fields_none(tmp_path):
    bundle = build_compose_fixture(tmp_path)
    carrier = load_run_spec_carrier(
        bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
    )
    assert carrier.mode == "fixture"
    assert carrier.activation_record is None
    assert carrier.git_is_clean is None
    assert carrier.environment is None
    assert carrier.data_card_path is None
    assert carrier.raw_asset_path is None
    assert carrier.provenance_inputs is None


def test_scientific_carrier_requires_all_fields(tmp_path):
    # A carrier declaring mode="scientific" but leaving the scientific surface None fails closed.
    from alive.compose.driver.carrier_loader import RunSpecCarrier

    bundle = build_compose_fixture(tmp_path)
    base = load_run_spec_carrier(
        bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
    )
    with pytest.raises(ValueError, match="scientific"):
        RunSpecCarrier(
            spec_path=base.spec_path,
            phase2a_inputs=base.phase2a_inputs,
            dev_store_audit=base.dev_store_audit,
            response_artifact=base.response_artifact,
            sealed_outcome=base.sealed_outcome,
            mode="scientific",  # every scientific field left None → reject
        )


def test_fixture_mode_rejects_populated_scientific_field(tmp_path):
    from alive.compose.driver.carrier_loader import RunSpecCarrier

    bundle = build_compose_fixture(tmp_path)
    base = load_run_spec_carrier(
        bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
    )
    with pytest.raises(ValueError, match="fixture"):
        RunSpecCarrier(
            spec_path=base.spec_path,
            phase2a_inputs=base.phase2a_inputs,
            dev_store_audit=base.dev_store_audit,
            response_artifact=base.response_artifact,
            sealed_outcome=base.sealed_outcome,
            mode="fixture",
            git_is_clean=True,  # a scientific field populated in fixture mode → reject
        )


# --------------------------------------------------------------------------- #
# partial-miss / per-field type-check / unknown-mode negatives (§6.2)
#
# __post_init__ only isinstance-checks the scientific dataclasses -- it does
# not validate their contents -- so dummy field values are sufficient to build
# minimal VALID instances of each scientific type.
# --------------------------------------------------------------------------- #
def _valid_scientific_fields() -> dict[str, object]:
    """All six scientific-mode fields populated with minimal valid values."""
    return {
        "activation_record": ActivationRecord(
            owner="dummy-owner",
            approved_protocol="COMPOSE-K562-v1",
            approved_phase=2,
            approved_git_sha="0" * 40,
            approved_sequence_mapping_sha256="0" * 64,
            evidence_hashes={},
            evidence_files={},
        ),
        "git_is_clean": True,
        "environment": EnvironmentInfo(
            python_version="3.12.3",
            platform="dummy-platform",
            git_commit="0" * 40,
            lockfile_sha256="0" * 64,
            registered_seeds=(0,),
        ),
        "data_card_path": Path("x"),
        "raw_asset_path": Path("x"),
        "provenance_inputs": ActivationProvenanceInputs(
            processed_sha256="0" * 64,
            feature_bank_sha256="0" * 64,
            dependency_lock_sha256="0" * 64,
            gears_revision="dummy",
            cpa_revision="dummy",
            python_version="3.12.3",
            platform="dummy-platform",
            device="cpu",
            precision="fp32",
            git_commit="0" * 40,
        ),
    }


@pytest.mark.parametrize(
    "missing_field",
    [
        "activation_record",
        "git_is_clean",
        "environment",
        "data_card_path",
        "raw_asset_path",
        "provenance_inputs",
    ],
)
def test_scientific_partial_miss_rejects(tmp_path, missing_field):
    """5 of 6 scientific fields populated, 1 left None -> rejected as "missing".

    Missing-ness is checked BEFORE any per-field type check (spec §3), so this
    must fail on the "missing" guard even though every OTHER field here is
    validly typed.
    """
    bundle = build_compose_fixture(tmp_path)
    base = load_run_spec_carrier(
        bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
    )
    fields = _valid_scientific_fields()
    fields[missing_field] = None
    with pytest.raises(ValueError, match="requires every scientific field"):
        RunSpecCarrier(
            spec_path=base.spec_path,
            phase2a_inputs=base.phase2a_inputs,
            dev_store_audit=base.dev_store_audit,
            response_artifact=base.response_artifact,
            sealed_outcome=base.sealed_outcome,
            mode="scientific",
            **fields,
        )


@pytest.mark.parametrize(
    "field, bad_value, match",
    [
        ("git_is_clean", 1, "must be exactly True"),
        ("activation_record", "x", "must be an ActivationRecord"),
        ("environment", "x", "must be an EnvironmentInfo"),
        ("provenance_inputs", "x", "must be ActivationProvenanceInputs"),
        ("data_card_path", "x", "must be Path"),
        ("raw_asset_path", "x", "must be Path"),
    ],
)
def test_scientific_wrong_type_rejects(tmp_path, field, bad_value, match):
    """All six fields non-None, only the target field wrong-typed -> rejected by
    that field's specific type-check branch (spec §3), never by the "missing"
    guard (which only fires on None).
    """
    bundle = build_compose_fixture(tmp_path)
    base = load_run_spec_carrier(
        bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
    )
    fields = _valid_scientific_fields()
    fields[field] = bad_value
    with pytest.raises(ValueError, match=match):
        RunSpecCarrier(
            spec_path=base.spec_path,
            phase2a_inputs=base.phase2a_inputs,
            dev_store_audit=base.dev_store_audit,
            response_artifact=base.response_artifact,
            sealed_outcome=base.sealed_outcome,
            mode="scientific",
            **fields,
        )


def test_unknown_mode_rejects(tmp_path):
    """An unrecognised ``mode`` is rejected regardless of field population."""
    bundle = build_compose_fixture(tmp_path)
    base = load_run_spec_carrier(
        bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
    )
    with pytest.raises(ValueError, match="must be 'fixture' or 'scientific'"):
        RunSpecCarrier(
            spec_path=base.spec_path,
            phase2a_inputs=base.phase2a_inputs,
            dev_store_audit=base.dev_store_audit,
            response_artifact=base.response_artifact,
            sealed_outcome=base.sealed_outcome,
            mode="bogus",
        )
