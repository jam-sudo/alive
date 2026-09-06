"""Tests for the ``preflight`` subcommand orchestration (spec §3.2 / §7.1).

Written FIRST per TDD. The ``preflight`` subcommand runs AFTER ``phase2a`` (spec
§1 canonical order ``phase2a → preflight → phase2b``): it asserts the preflight
run-directory roster, loads the frozen prediction bundle, RE-READS the
persisted phase2a ledger (never reconstructing it — that would make preflight's
ledger↔bundle checksum check a tautology), calls the outcome-free
:func:`~alive.compose.preflight.run_preflight` gate, and on success installs the
FULL §3.2 ``seal_confirmation_manifest.json`` write-once. It constructs NO
outcome store of any kind and opens no seal.

These tests run the REAL ``phase2a → preflight`` chain on the committed fixture
(no mocks), except a single spy asserting ``ComposeOutcomeStore`` is never
constructed on the preflight code path (§4 single-creation-point invariant).

Coverage:

  1. success → returns 0; installs ``seal_confirmation_manifest.json``; the
     installed manifest passes ``verify_seal_confirmation_manifest`` with
     ``token = confirmation_checksum`` and the SAME independently re-derived
     ``reconstruct_inputs`` (proves phase2b's Task-9/13 reconstruction will match);
  2. byte-match: the manifest's ``ordered_seal_request_checksum`` equals the
     phase2b.py:1269-1277 ``intent_checksum`` expression computed independently
     from the EvaluationLock;
  3. the per-method ``worker_identity`` is the canonical 6-field
     ``ExecutionIdentityLock`` mapping form for exactly ``{gears, cpa}``, and the
     ``preseal_checksums`` carry the complete 12-key §3.2 set;
  4. preflight constructs NO ``ComposeOutcomeStore`` (§4);
  5. a FORBIDDEN terminal present at entry → roster raise;
  6. a tampered persisted ledger → fail closed (return 10); a deleted ledger →
     roster raise (fail closed).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import alive.compose.driver.preflight_cmd as preflight_mod
import alive.compose.outcome_store as outcome_store_mod
from alive.compose.config2 import load_compose_phase2_config
from alive.compose.driver.confirmation import verify_seal_confirmation_manifest
from alive.compose.driver.fixture_builder import build_compose_fixture
from alive.compose.driver.phase2a_cmd import run_phase2a_subcommand
from alive.compose.driver.preflight_cmd import (
    PREFLIGHT_PASS_EXIT,
    PREFLIGHT_REJECT_EXIT,
    build_confirmation_inputs,
    run_preflight_subcommand,
)
from alive.compose.driver.run_dir_state import RunDirStateError
from alive.compose.driver.run_spec import RunSpecError, load_resolved_run_spec
from alive.compose.freeze import FrozenPredictionBundle
from alive.compose.preflight import run_preflight
from alive.compose.terminal import Phase2bTerminal
from alive.provenance import RunLedger, sha256_file, sha256_json

_CONFIRMATION = "seal_confirmation_manifest.json"
_LEDGER = "phase2a_run_ledger.json"
_BUNDLE = "frozen_prediction_bundle.json"

_LOCK_FIELDS = {
    "prediction_representation",
    "adapter_version",
    "adapter_sha256",
    "config_sha256",
    "resource_sha256",
    "environment_lock_sha256",
}


def _forbid_compose_outcome_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spy: fail closed if the preflight code path ever constructs a sealed store."""

    def _boom(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError(
            "ComposeOutcomeStore must NOT be constructed on the preflight code path (spec §4)"
        )

    monkeypatch.setattr(outcome_store_mod.ComposeOutcomeStore, "__init__", _boom)


def _rederive(fx, root: Path):
    """Independently re-derive (spec, ledger, ledger_path, config, lock, git_clean).

    Mirrors what a SEPARATE preflight/phase2b process reconstructs from the
    run_dir artifacts + ResolvedRunSpec + config — never from the manifest itself.
    """
    spec = load_resolved_run_spec(
        fx.spec_path, approved_artifacts_root=root, mode_expected="fixture"
    )
    frozen = FrozenPredictionBundle.load(fx.run_dir / _BUNDLE)
    ledger_path = fx.run_dir / _LEDGER
    ledger = RunLedger.read(ledger_path)
    config = load_compose_phase2_config(spec.pre_seal["config"].path)
    pair_manifest = json.loads(Path(spec.pre_seal["pair_manifest"].path).read_bytes())
    dim = int(fx.response_artifact["response_space"].pca_dim)
    lock = run_preflight(
        bundle=frozen,
        pair_manifest=pair_manifest,
        config=config,
        data_card_digest=spec.data_card_digest,
        raw_or_source_digest=spec.raw_or_source_digest,
        sequence_mapping_digest=spec.sequence_mapping_digest,
        ledger=ledger,
        expected_response_dim=dim,
    )
    return spec, ledger, ledger_path, config, lock, frozen


def _run_chain(tmp_path: Path):
    """Build the fixture, run phase2a, then the preflight subcommand → return fx."""
    fx = build_compose_fixture(tmp_path)
    assert run_phase2a_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir) == 0
    return fx


# --------------------------------------------------------------------------- #
# Contract 1: success → 0, installs manifest, reconstructs byte-identically
# --------------------------------------------------------------------------- #
def test_preflight_passes_installs_and_reconstructs(tmp_path: Path) -> None:
    fx = _run_chain(tmp_path)

    rc = run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir)
    assert rc == PREFLIGHT_PASS_EXIT

    manifest_path = fx.run_dir / _CONFIRMATION
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_bytes())

    # Independently re-derive the reconstruction inputs (as a separate process
    # would) and require verify's byte-for-byte reconstruction to pass.
    spec, ledger, ledger_path, config, lock, frozen = _rederive(fx, tmp_path)
    inputs = build_confirmation_inputs(
        spec=spec,
        config=config,
        ledger=ledger,
        ledger_path=ledger_path,
        lock=lock,
        bundle=frozen,
        git_clean=True,
    )
    verify_seal_confirmation_manifest(
        manifest_path, manifest["confirmation_checksum"], reconstruct_inputs=inputs
    )

    # The manifest binds the run/execution identity of the loaded spec.
    assert manifest["run_id"] == lock.run_id == spec.run_id
    assert manifest["resolved_run_spec_file_sha256"] == spec.file_sha256
    assert manifest["approved_git_sha"] == spec.approved_git_sha
    assert manifest["futility_status"] == "CONTINUE"
    assert manifest["sealed_access_count"] == 0
    assert manifest["forbidden_output_absence"] is True

    # §3.2 (owner-ratified): selected_hyperparameters binds BOTH the search
    # config AND the actually-selected point (k*/lambda*) from the frozen bundle,
    # in the bundle's canonical round(.,12) lambda representation.
    sel = manifest["selected_hyperparameters"]
    assert sel["selected_k_total"] == int(frozen.selected_k_total)
    assert sel["selected_lambda"] == round(float(frozen.selected_lambda), 12)
    assert "total_k_grid" in sel and "lambda_grid" in sel  # grid still present
    assert sel["unregularized_solver"] == "svd_lstsq_minimum_norm"
    assert sel["regularized_solver"] == "svd_ridge_filter_factors"
    assert sel["unregularized_oof_rank_policy"] == "require_full_rank_each_train_fold"
    assert sel["rank_tolerance_rule"] == "max_shape_times_float64_eps_times_sigma_max"


# --------------------------------------------------------------------------- #
# Contract 1b (Amendment C, signed 2026-09-05): preflight writes NOTHING to stdout
# --------------------------------------------------------------------------- #
def test_preflight_writes_nothing_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """The confirmation payload reaches the second operator as a file, never as a screen.

    The driver design spec once said "화면에는 canonical payload와 full checksum을
    출력한다". The runbook's two-operator control is mediated by the write-once
    manifest, and a terminal transcript of ordered seal-request checksums would
    look like a record of a reconciliation that is supposed to happen against
    the file. Amendment C replaced the sentence; this pins the behaviour the
    implementation always had, so a later "helpful" print is refused by name.
    """
    fx = _run_chain(tmp_path)
    capsys.readouterr()  # drain anything the fixture chain printed

    rc = run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir)

    assert rc == PREFLIGHT_PASS_EXIT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (fx.run_dir / _CONFIRMATION).exists()


# --------------------------------------------------------------------------- #
# Contract 2: ordered_seal_request_checksum == phase2b intent_checksum bytes
# --------------------------------------------------------------------------- #
def test_ordered_seal_request_checksum_matches_phase2b_expression(tmp_path: Path) -> None:
    fx = _run_chain(tmp_path)
    run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir)
    manifest = json.loads((fx.run_dir / _CONFIRMATION).read_bytes())

    _, _, _, _, lock, _ = _rederive(fx, tmp_path)
    # The exact phase2b.py:1269-1277 intent_checksum expression, recomputed here.
    expected = sha256_json(
        {
            "run_id": lock.run_id,
            "bundle_checksum": lock.bundle_checksum,
            "manifest_checksum": lock.manifest_checksum,
            "double_pairs": sorted(list(p) for p in lock.pair_ids_double_unseen),
            "single_pairs": sorted(list(p) for p in lock.pair_ids_single_unseen),
        }
    )
    assert manifest["ordered_seal_request_checksum"] == expected
    assert manifest["double_pair_count"] == len(lock.pair_ids_double_unseen)
    assert manifest["single_pair_count"] == len(lock.pair_ids_single_unseen)


# --------------------------------------------------------------------------- #
# Contract 3: worker_identity is the 6-field lock form; full 12-key preseal set
# --------------------------------------------------------------------------- #
def test_worker_identity_is_six_field_lock_form_and_full_preseal_set(tmp_path: Path) -> None:
    fx = _run_chain(tmp_path)
    run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir)
    manifest = json.loads((fx.run_dir / _CONFIRMATION).read_bytes())

    assert set(manifest["worker_identity"]) == {"gears", "cpa"}
    for method in ("gears", "cpa"):
        wid = manifest["worker_identity"][method]
        assert isinstance(wid, dict)
        assert set(wid) == _LOCK_FIELDS
        assert all(isinstance(v, str) and v for v in wid.values())

    assert set(manifest["preseal_checksums"]) == {
        "config_checksum",
        "data_card_checksum",
        "manifest_checksum",
        "sequence_checksum",
        "feature_checksum",
        "factor_checksum",
        "response_space_checksum",
        "model_checksum",
        "bundle_checksum",
        "ledger_checksum",
        "pair_index_checksum",
        "seed_report_checksum",
    }
    # The lock-sourced members equal the EvaluationLock exactly.
    _, _, _, _, lock, _ = _rederive(fx, tmp_path)
    ps = manifest["preseal_checksums"]
    assert ps["bundle_checksum"] == lock.bundle_checksum
    assert ps["manifest_checksum"] == lock.manifest_checksum
    assert ps["response_space_checksum"] == lock.response_space_checksum
    assert ps["factor_checksum"] == lock.factor_checksum
    assert ps["model_checksum"] == lock.model_checksum


# --------------------------------------------------------------------------- #
# Contract 4: preflight constructs NO ComposeOutcomeStore (§4)
# --------------------------------------------------------------------------- #
def test_preflight_builds_no_outcome_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fx = _run_chain(tmp_path)
    # Install the spy AFTER phase2a so it isolates the preflight code path.
    _forbid_compose_outcome_store(monkeypatch)

    rc = run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir)
    assert rc == PREFLIGHT_PASS_EXIT
    assert (fx.run_dir / _CONFIRMATION).exists()


# --------------------------------------------------------------------------- #
# Contract 5: a FORBIDDEN terminal present at entry → roster raise
# --------------------------------------------------------------------------- #
def test_forbidden_terminal_present_raises_roster(tmp_path: Path) -> None:
    fx = _run_chain(tmp_path)
    # A terminal artifact is forbidden at the preflight entry roster (§7.1).
    (fx.run_dir / Phase2bTerminal.COMPLETE_ARTIFACT).write_text("{}", encoding="utf-8")

    with pytest.raises(RunDirStateError):
        run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir)
    assert not (fx.run_dir / _CONFIRMATION).exists()


# --------------------------------------------------------------------------- #
# Contract 6: tampered ledger → fail closed (10); deleted ledger → roster raise
# --------------------------------------------------------------------------- #
def test_tampered_ledger_fails_closed_returns_10(tmp_path: Path) -> None:
    fx = _run_chain(tmp_path)
    ledger_path = fx.run_dir / _LEDGER
    raw = json.loads(ledger_path.read_text(encoding="utf-8"))
    # Break the bundle↔ledger checksum agreement (valid JSON, wrong SHA).
    for art in raw["artifacts"]:
        if art["name"] == "frozen_prediction_bundle":
            art["sha256"] = "0" * 64
    ledger_path.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    rc = run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir)
    assert rc == PREFLIGHT_REJECT_EXIT
    # A pre-seal reject installs NO confirmation manifest.
    assert not (fx.run_dir / _CONFIRMATION).exists()


def test_deleted_ledger_fails_closed(tmp_path: Path) -> None:
    fx = _run_chain(tmp_path)
    (fx.run_dir / _LEDGER).unlink()

    # A missing required phase2a artifact violates the preflight entry roster.
    with pytest.raises(RunDirStateError):
        run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir)
    assert not (fx.run_dir / _CONFIRMATION).exists()


# --------------------------------------------------------------------------- #
# Contract 7: the pre-seal pair-index manifest / attestation validator (Task 2)
# is actually WIRED into the pre-seal gate — not dead code. It is invoked EXACTLY
# once over the fixture's pair-index manifest + attestation (the on-disk bytes
# were already SHA-verified by load_resolved_run_spec). The validator's own
# rejection behaviour (schema / self-checksum / attestation-binding) is unit-
# tested in test_pair_index_preseal.py; here we prove it runs in the flow.
# --------------------------------------------------------------------------- #
def test_preflight_invokes_preseal_pair_index_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fx = _run_chain(tmp_path)

    seen: list[tuple] = []
    real = preflight_mod.validate_pair_index_manifest_preseal

    def _spy(  # noqa: ANN001, ANN202
        manifest, *, attestation, pair_index_manifest_file_sha256
    ):
        seen.append((manifest, attestation, pair_index_manifest_file_sha256))
        return real(
            manifest,
            attestation=attestation,
            pair_index_manifest_file_sha256=pair_index_manifest_file_sha256,
        )

    monkeypatch.setattr(preflight_mod, "validate_pair_index_manifest_preseal", _spy)

    rc = run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir)
    assert rc == PREFLIGHT_PASS_EXIT
    # Invoked EXACTLY once, over the fixture's pair-index manifest + attestation.
    assert len(seen) == 1
    manifest, attestation, pair_index_file_sha256 = seen[0]
    assert manifest == fx.sealed_outcome["pair_index_manifest"]
    assert attestation == fx.sealed_outcome["attestation"]
    assert pair_index_file_sha256 == sha256_file(fx.paths["pair_index_manifest"])


# --------------------------------------------------------------------------- #
# Contract 7b: a pre-seal pair-index / attestation rejection fails the gate CLOSED
# — RunSpecError propagates (→ the CLI's pre-seal exit 10) and NO confirmation
# manifest is installed, so the seal can never be armed off an unbound pair index.
# --------------------------------------------------------------------------- #
def test_preflight_fails_closed_on_pair_index_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fx = _run_chain(tmp_path)

    def _reject(  # noqa: ANN001, ANN202
        manifest, *, attestation, pair_index_manifest_file_sha256
    ):
        raise RunSpecError("pair-index manifest failed pre-seal attestation binding")

    monkeypatch.setattr(preflight_mod, "validate_pair_index_manifest_preseal", _reject)

    with pytest.raises(RunSpecError):
        run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir)
    assert not (fx.run_dir / _CONFIRMATION).exists()
