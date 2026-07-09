"""Tests for the run-directory basename state machine (spec §7.1).

Uses real tmp directories + real touched files (no mocks). Exercises the four
subcommand rosters: a correct roster passes; a forbidden file present raises; a
missing required file raises; an unexpected unknown file raises.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alive.compose.driver.run_dir_state import (
    DRIVER_LOCK_FILE,
    RunDirStateError,
    assert_run_dir_roster,
)
from alive.compose.driver.run_spec import RUN_PRODUCED_BASENAMES
from alive.compose.durable import (
    DURABLE_COMMIT_FILENAME,
    FINAL_LEDGER_FILENAME,
    REGISTERED_SUMMARY_FILENAME,
    SEAL_AUDIT_FILENAME,
)
from alive.compose.provenance2 import PRE_ACCESS_LEDGER_FILENAME
from alive.compose.seed_variability import DEVELOPMENT_SEED_VARIABILITY_FILENAME
from alive.compose.terminal import Phase2bTerminal

_FROZEN_BUNDLE = RUN_PRODUCED_BASENAMES["frozen_bundle"]
_OOF_MANIFEST = RUN_PRODUCED_BASENAMES["oof_manifest"]
_SEED_VARIABILITY_REPORT = RUN_PRODUCED_BASENAMES["phase2a_seed_variability_report"]
_RUN_LEDGER = RUN_PRODUCED_BASENAMES["run_ledger"]
_FUTILITY_REPORT = RUN_PRODUCED_BASENAMES["futility_report"]
_CONFIRMATION_MANIFEST = RUN_PRODUCED_BASENAMES["seal_confirmation_manifest"]

_PHASE2A_FOUR = (_FROZEN_BUNDLE, _OOF_MANIFEST, _SEED_VARIABILITY_REPORT, _RUN_LEDGER)


def _touch(run_dir: Path, *basenames: str) -> None:
    for name in basenames:
        (run_dir / name).write_bytes(b"{}")


def _rundir(tmp_path: Path, name: str = "run") -> Path:
    d = tmp_path / name
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# phase2a
# ---------------------------------------------------------------------------


def test_phase2a_entry_empty_passes(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    assert_run_dir_roster(run_dir, "phase2a")


def test_phase2a_entry_with_run_produced_artifact_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, _FROZEN_BUNDLE)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2a")


def test_phase2a_entry_with_unknown_file_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, "some_unexpected_junk.txt")
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2a")


def test_phase2a_continue_exact_four_passes(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR)
    assert_run_dir_roster(run_dir, "phase2a", phase2a_outcome="CONTINUE")


def test_phase2a_continue_missing_one_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, _FROZEN_BUNDLE, _OOF_MANIFEST, _SEED_VARIABILITY_REPORT)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2a", phase2a_outcome="CONTINUE")


def test_phase2a_continue_with_extra_confirmation_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, _CONFIRMATION_MANIFEST)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2a", phase2a_outcome="CONTINUE")


def test_phase2a_futility_exact_one_passes(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, _FUTILITY_REPORT)
    assert_run_dir_roster(run_dir, "phase2a", phase2a_outcome="FUTILITY_STOPPED")


def test_phase2a_futility_with_bundle_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, _FUTILITY_REPORT, _FROZEN_BUNDLE)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2a", phase2a_outcome="FUTILITY_STOPPED")


def test_phase2a_futility_with_terminal_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, _FUTILITY_REPORT, Phase2bTerminal.COMPLETE_ARTIFACT)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2a", phase2a_outcome="FUTILITY_STOPPED")


def test_phase2a_outcome_ignored_for_other_subcommands_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "preflight", phase2a_outcome="CONTINUE")


def test_phase2a_unrecognised_outcome_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2a", phase2a_outcome="BOGUS")


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------


def test_preflight_correct_roster_passes(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR)
    assert_run_dir_roster(run_dir, "preflight")


def test_preflight_missing_bundle_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, _OOF_MANIFEST, _SEED_VARIABILITY_REPORT, _RUN_LEDGER)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "preflight")


def test_preflight_with_terminal_present_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, Phase2bTerminal.COMPLETE_ARTIFACT)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "preflight")


def test_preflight_with_confirmation_already_present_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, _CONFIRMATION_MANIFEST)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "preflight")


def test_preflight_with_audit_present_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, SEAL_AUDIT_FILENAME)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "preflight")


def test_preflight_with_pre_access_ledger_present_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, PRE_ACCESS_LEDGER_FILENAME)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "preflight")


def test_preflight_with_durable_artifact_present_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, REGISTERED_SUMMARY_FILENAME)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "preflight")


def test_preflight_with_unknown_file_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, "mystery.bin")
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "preflight")


# ---------------------------------------------------------------------------
# phase2b
# ---------------------------------------------------------------------------


def test_phase2b_correct_roster_passes(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, _CONFIRMATION_MANIFEST)
    assert_run_dir_roster(run_dir, "phase2b")


def test_phase2b_with_both_ephemeral_locks_passes(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(
        run_dir,
        *_PHASE2A_FOUR,
        _CONFIRMATION_MANIFEST,
        DRIVER_LOCK_FILE,
        Phase2bTerminal.LOCK_FILE,
    )
    assert_run_dir_roster(run_dir, "phase2b")


def test_phase2b_missing_confirmation_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2b")


def test_phase2b_with_terminal_present_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, _CONFIRMATION_MANIFEST, Phase2bTerminal.INVALID_ARTIFACT)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2b")


def test_phase2b_with_audit_present_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, _CONFIRMATION_MANIFEST, SEAL_AUDIT_FILENAME)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2b")


def test_phase2b_with_pre_access_ledger_present_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, _CONFIRMATION_MANIFEST, PRE_ACCESS_LEDGER_FILENAME)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2b")


def test_phase2b_with_durable_artifact_present_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, _CONFIRMATION_MANIFEST, FINAL_LEDGER_FILENAME)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2b")


def test_phase2b_with_unknown_file_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, _CONFIRMATION_MANIFEST, "stray.log")
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "phase2b")


# ---------------------------------------------------------------------------
# recover
# ---------------------------------------------------------------------------


def test_recover_exactly_one_terminal_passes(tmp_path: Path) -> None:
    # A realistic post-phase2b crash run_dir: base 4 + confirmation + the
    # canonical seed-variability bind artifact (development_seed_variability.json,
    # ALWAYS written by run_phase2b before the pre-access snapshot) + audit +
    # pre-access ledger + exactly one terminal.
    run_dir = _rundir(tmp_path)
    _touch(
        run_dir,
        *_PHASE2A_FOUR,
        _CONFIRMATION_MANIFEST,
        DEVELOPMENT_SEED_VARIABILITY_FILENAME,
        SEAL_AUDIT_FILENAME,
        PRE_ACCESS_LEDGER_FILENAME,
        Phase2bTerminal.COMPLETE_ARTIFACT,
    )
    assert_run_dir_roster(run_dir, "recover")


def test_recover_terminal_with_partial_durable_subset_passes(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(
        run_dir,
        *_PHASE2A_FOUR,
        _CONFIRMATION_MANIFEST,
        DEVELOPMENT_SEED_VARIABILITY_FILENAME,
        SEAL_AUDIT_FILENAME,
        PRE_ACCESS_LEDGER_FILENAME,
        Phase2bTerminal.COMPLETE_ARTIFACT,
        REGISTERED_SUMMARY_FILENAME,
        FINAL_LEDGER_FILENAME,
        DRIVER_LOCK_FILE,
    )
    assert_run_dir_roster(run_dir, "recover")


def test_recover_terminal_zero_with_audit_claim_passes(tmp_path: Path) -> None:
    # State 2 (terminal=0 + audit claim): the seed-variability report is
    # causally prior to even the pre-access ledger, so a legitimate post-seal
    # crash with no terminal yet always carries it too.
    run_dir = _rundir(tmp_path)
    _touch(
        run_dir,
        *_PHASE2A_FOUR,
        _CONFIRMATION_MANIFEST,
        DEVELOPMENT_SEED_VARIABILITY_FILENAME,
        SEAL_AUDIT_FILENAME,
        PRE_ACCESS_LEDGER_FILENAME,
        Phase2bTerminal.LOCK_FILE,
    )
    assert_run_dir_roster(run_dir, "recover")


def test_recover_terminal_zero_missing_seed_variability_raises(tmp_path: Path) -> None:
    # Proves the new state-2 requirement: audit claim + pre-access ledger
    # present, no terminal, but the causally-prior seed-variability report is
    # ABSENT -> an inconsistent partial state, must raise.
    run_dir = _rundir(tmp_path)
    _touch(
        run_dir,
        *_PHASE2A_FOUR,
        _CONFIRMATION_MANIFEST,
        SEAL_AUDIT_FILENAME,
        PRE_ACCESS_LEDGER_FILENAME,
    )
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "recover")


def test_recover_both_ephemeral_locks_allowed(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(
        run_dir,
        *_PHASE2A_FOUR,
        _CONFIRMATION_MANIFEST,
        DEVELOPMENT_SEED_VARIABILITY_FILENAME,
        SEAL_AUDIT_FILENAME,
        PRE_ACCESS_LEDGER_FILENAME,
        DRIVER_LOCK_FILE,
        Phase2bTerminal.LOCK_FILE,
    )
    assert_run_dir_roster(run_dir, "recover")


def test_recover_missing_upstream_bundle_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(
        run_dir,
        _OOF_MANIFEST,
        _SEED_VARIABILITY_REPORT,
        _RUN_LEDGER,
        _CONFIRMATION_MANIFEST,
        Phase2bTerminal.COMPLETE_ARTIFACT,
    )
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "recover")


def test_recover_two_terminals_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(
        run_dir,
        *_PHASE2A_FOUR,
        _CONFIRMATION_MANIFEST,
        SEAL_AUDIT_FILENAME,
        PRE_ACCESS_LEDGER_FILENAME,
        Phase2bTerminal.COMPLETE_ARTIFACT,
        Phase2bTerminal.INVALID_ARTIFACT,
    )
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "recover")


def test_recover_terminal_zero_no_audit_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, _CONFIRMATION_MANIFEST)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "recover")


def test_recover_audit_without_pre_access_ledger_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(run_dir, *_PHASE2A_FOUR, _CONFIRMATION_MANIFEST, SEAL_AUDIT_FILENAME)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "recover")


def test_recover_durable_without_terminal_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(
        run_dir,
        *_PHASE2A_FOUR,
        _CONFIRMATION_MANIFEST,
        DEVELOPMENT_SEED_VARIABILITY_FILENAME,
        SEAL_AUDIT_FILENAME,
        PRE_ACCESS_LEDGER_FILENAME,
        DURABLE_COMMIT_FILENAME,
    )
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "recover")


def test_recover_with_unknown_file_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    _touch(
        run_dir,
        *_PHASE2A_FOUR,
        _CONFIRMATION_MANIFEST,
        SEAL_AUDIT_FILENAME,
        PRE_ACCESS_LEDGER_FILENAME,
        Phase2bTerminal.COMPLETE_ARTIFACT,
        "not_a_real_artifact.tmp",
    )
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "recover")


# ---------------------------------------------------------------------------
# subcommand dispatch
# ---------------------------------------------------------------------------


def test_unrecognised_subcommand_raises(tmp_path: Path) -> None:
    run_dir = _rundir(tmp_path)
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(run_dir, "bogus")


def test_nonexistent_run_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(RunDirStateError):
        assert_run_dir_roster(tmp_path / "does_not_exist", "phase2a")
