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

from alive.compose.driver.carrier_loader import (
    RunSpecCarrier,
    UnsupportedModeError,
    load_run_spec_carrier,
)
from alive.compose.driver.fixture_builder import build_compose_fixture
from alive.compose.driver.phase2a_cmd import run_phase2a_subcommand
from alive.compose.driver.run_spec import RunSpecError
from alive.compose.response import verify_response_artifact


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
# fixture is the only committed carrier path: scientific fails closed
# --------------------------------------------------------------------------- #
def test_scientific_mode_raises_unsupported(tmp_path: Path) -> None:
    spec_path = tmp_path / "scientific_spec.json"
    spec_path.write_text(json.dumps({"mode": "scientific"}), encoding="utf-8")
    with pytest.raises(UnsupportedModeError):
        load_run_spec_carrier(spec_path, approved_artifacts_root=tmp_path)


def test_unreadable_spec_raises_runspecerror(tmp_path: Path) -> None:
    with pytest.raises(RunSpecError):
        load_run_spec_carrier(tmp_path / "does-not-exist.json", approved_artifacts_root=tmp_path)
