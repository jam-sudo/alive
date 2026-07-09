"""Tests for the ``recover`` subcommand orchestration (spec §3.4 / §7.1).

Written FIRST per TDD. ``recover`` is a THIN driver wrapper over the C0 library
recovery entry point
:func:`~alive.compose.durable.recover_phase2b_durable_outputs`. It salvages a run
whose seal was ALREADY consumed (the burned ``audit.jsonl`` exists) but whose
durable terminal / commit marker was not fully published. It re-implements NO
recovery/synthesis logic (the library owns it), opens NO seal, and constructs NO
:class:`~alive.compose.outcome_store.ComposeOutcomeStore` (§4).

These tests run the REAL ``phase2a → preflight → phase2b`` fixture chain (no mocks)
to obtain a genuine burned audit + durable outputs, then drive the three brief
scenarios and assert REAL on-disk outcomes:

  (a) after a full phase2b run, ``recover`` is VERIFY-ONLY → exit 0, and the
      durable commit marker + terminal are byte-identical (never rewritten);
  (b) a synthesized ``audit=1 / terminal=0`` run_dir (the full run with the
      terminal + durable finalize artifacts removed) → ``recover`` publishes the
      sole ``ABORTED_AFTER_SEAL`` terminal + a fresh commit marker → exit 30;
  (c) a run_dir with the burned audit emptied to 0 records (basename still
      present, so the roster passes and the LIBRARY's audit-record guard is what
      trips) → fail closed → exit 30, and NO terminal is fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path

from alive.compose.driver.fixture_builder import build_compose_fixture
from alive.compose.driver.phase2a_cmd import run_phase2a_subcommand
from alive.compose.driver.phase2b_cmd import run_phase2b_subcommand
from alive.compose.driver.preflight_cmd import run_preflight_subcommand
from alive.compose.driver.recover_cmd import (
    RECOVER_COMPLETE_EXIT,
    RECOVER_NONCOMPLETE_EXIT,
    run_recover_subcommand,
)
from alive.compose.driver.run_spec import RUN_PRODUCED_BASENAMES
from alive.compose.durable import (
    DURABLE_COMMIT_FILENAME,
    FINAL_LEDGER_FILENAME,
    REGISTERED_SUMMARY_FILENAME,
    SEAL_AUDIT_FILENAME,
)
from alive.compose.terminal import Phase2bTerminal

_CONFIRMATION = RUN_PRODUCED_BASENAMES["seal_confirmation_manifest"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _run_full_fixture(tmp_path: Path):
    """Build the fixture and run the REAL phase2a → preflight → phase2b chain.

    Returns the carrier fx; on return ``fx.run_dir`` holds a genuine burned audit,
    a ``COMPLETE`` terminal, and the full durable finalize set.
    """
    fx = build_compose_fixture(tmp_path)
    assert run_phase2a_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir) == 0
    assert run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir) == 0
    token = json.loads((fx.run_dir / _CONFIRMATION).read_bytes())["confirmation_checksum"]
    assert (
        run_phase2b_subcommand(
            fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
        )
        == 0
    )
    return fx


def _reduce_to_audit_only(run_dir: Path) -> None:
    """Reduce a full run to the ``audit=1 / terminal=0`` post-crash state (State 2).

    Removes the terminal AND every durable finalize artifact (the recover roster
    forbids a durable-without-terminal partial), leaving the burned audit + its
    causally-prior pre-access provenance + the canonical seed-variability report.
    """
    (run_dir / Phase2bTerminal.COMPLETE_ARTIFACT).unlink()
    (run_dir / DURABLE_COMMIT_FILENAME).unlink()
    (run_dir / FINAL_LEDGER_FILENAME).unlink()
    (run_dir / REGISTERED_SUMMARY_FILENAME).unlink()


# --------------------------------------------------------------------------- #
# Scenario (a): full run → verify-only → exit 0, byte-identical (no rewrite)
# --------------------------------------------------------------------------- #
def test_recover_verify_only_is_byte_identical_and_returns_zero(tmp_path: Path) -> None:
    fx = _run_full_fixture(tmp_path)
    terminal = fx.run_dir / Phase2bTerminal.COMPLETE_ARTIFACT
    marker = fx.run_dir / DURABLE_COMMIT_FILENAME
    terminal_before = terminal.read_bytes()
    marker_before = marker.read_bytes()

    rc = run_recover_subcommand(run_dir=fx.run_dir)

    assert rc == RECOVER_COMPLETE_EXIT
    # VERIFY ONLY: neither the terminal nor the durable commit marker is rewritten.
    assert terminal.read_bytes() == terminal_before
    assert marker.read_bytes() == marker_before
    # No ABORTED terminal is ever synthesized when a real terminal is present.
    assert not (fx.run_dir / Phase2bTerminal.ABORTED_ARTIFACT).exists()


# --------------------------------------------------------------------------- #
# Scenario (b): audit=1 / terminal=0 → synthesize ABORTED_AFTER_SEAL → exit 30
# --------------------------------------------------------------------------- #
def test_recover_synthesizes_aborted_terminal_returns_thirty(tmp_path: Path) -> None:
    fx = _run_full_fixture(tmp_path)
    run_dir = fx.run_dir
    _reduce_to_audit_only(run_dir)

    # Sanity: this really is the audit=1 / terminal=0 state before recovery.
    assert (run_dir / SEAL_AUDIT_FILENAME).stat().st_size > 0
    assert not (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).exists()
    assert not (run_dir / DURABLE_COMMIT_FILENAME).exists()

    rc = run_recover_subcommand(run_dir=run_dir)

    assert rc == RECOVER_NONCOMPLETE_EXIT
    # The library published the sole ABORTED_AFTER_SEAL terminal + a fresh marker.
    assert (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).is_file()
    assert (run_dir / DURABLE_COMMIT_FILENAME).is_file()
    assert (run_dir / FINAL_LEDGER_FILENAME).is_file()
    # The reduced abort publish carries NO registered summary, and never resurrects
    # a COMPLETE terminal.
    assert not (run_dir / REGISTERED_SUMMARY_FILENAME).exists()
    assert not (run_dir / Phase2bTerminal.COMPLETE_ARTIFACT).exists()


# --------------------------------------------------------------------------- #
# Scenario (c): pre-access ledger + 0 audit records + 0 terminals → fail closed
# --------------------------------------------------------------------------- #
def test_recover_zero_audit_records_fails_closed_returns_thirty(tmp_path: Path, capsys) -> None:
    fx = _run_full_fixture(tmp_path)
    run_dir = fx.run_dir
    _reduce_to_audit_only(run_dir)
    # Empty the burned audit to 0 records while KEEPING the basename present: the
    # roster's State-2 basename check still passes, so the LIBRARY's audit-record
    # guard is what fails closed (a pre-access failure, spec §3.4).
    (run_dir / SEAL_AUDIT_FILENAME).write_bytes(b"")
    assert not (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).exists()

    rc = run_recover_subcommand(run_dir=run_dir)

    assert rc == RECOVER_NONCOMPLETE_EXIT
    # Fail closed: NO terminal is fabricated when the seal was not truly consumed.
    assert not (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).exists()
    assert not (run_dir / DURABLE_COMMIT_FILENAME).exists()
    assert not (run_dir / FINAL_LEDGER_FILENAME).exists()
    # The fail-closed reason is diagnosed on stderr, not silently swallowed: it
    # names the caught exception class so a tampered/corrupt durable export is
    # distinguishable from a benign aborted-recovery.
    stderr = capsys.readouterr().err
    assert stderr
    assert "DurableLedgerError" in stderr


# --------------------------------------------------------------------------- #
# Sanity: exit-code constants are the documented 0 / 30
# --------------------------------------------------------------------------- #
def test_recover_exit_code_constants() -> None:
    assert RECOVER_COMPLETE_EXIT == 0
    assert RECOVER_NONCOMPLETE_EXIT == 30
