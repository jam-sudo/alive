"""``recover`` subcommand orchestration (COMPOSE production driver, spec §3.4).

The recovery subcommand and a THIN wrapper over the C0 library entry point
:func:`~alive.compose.durable.recover_phase2b_durable_outputs`. It salvages a run
whose seal was ALREADY consumed (the burned ``<run_dir>/audit.jsonl`` exists) but
whose durable terminal / commit marker was not fully published, covering the three
library-owned states:

- ``1 terminal + marker``: VERIFY ONLY — the marker's self-checksum, run id /
  state and every recorded file SHA are re-verified; nothing is ever rewritten;
- ``1 terminal, no marker``: idempotent forward re-publish (byte-identical
  re-derivation is a no-op; any divergence fails closed);
- ``terminal=0 + a burned audit`` (the ``audit=1 / terminal=0`` post-crash state
  the C0 #5 fix added): the library SYNTHESIZES the sole ``ABORTED_AFTER_SEAL``
  terminal via
  :meth:`~alive.compose.terminal.Phase2bTerminal.recover_aborted_after_seal`, then
  finalizes.

This module RE-IMPLEMENTS NONE of that recovery / synthesis logic — the library
owns it. It opens NO seal (the seal was already consumed by the aborted phase2b
run), loads NO outcome source / pair-index / frozen bundle, and constructs NO
:class:`~alive.compose.outcome_store.ComposeOutcomeStore` (the §4 single-
construction-point invariant lives entirely in ``phase2b``; ``recover`` never
touches the store). It only:

0. acquires the SAME non-blocking OS-exclusive driver lock ``run_dir/phase2b.lock``
   the ``phase2b`` subcommand uses — ``recover`` and a ``phase2b`` run are mutually
   exclusive on one ``run_dir``, so a concurrent driver fails closed immediately;
1. asserts the ``recover`` roster (spec §7.1: both ephemeral locks allowed; the
   upstream 4 phase2a artifacts + confirmation required; then exactly-one-terminal
   OR ``terminal=0`` with a durable audit claim + its causally-prior pre-access
   provenance + the even-earlier seed-variability report);
2. calls the library recovery function and maps its result to an exit code.

Exit codes (spec §1.1). ``0`` = the durable export was recovered / verified to a
``COMPLETE`` terminal; ``30`` = a non-``COMPLETE`` terminal was published / verified
(``INVALID`` / the synthesized ``ABORTED_AFTER_SEAL``) OR the library fails closed
(a burned audit with 0 records → a pre-access failure, a missing / invalid
pre-access provenance, a tampered seed report, a divergent partial durable byte,
…). Because ``recover`` is entirely POST-seal — it NEVER opens a seal — a library
:class:`~alive.compose.durable.DurableLedgerError` is precisely the CLI's exit-30
"durable export incomplete" condition (spec §1.1), so it is mapped to ``30`` rather
than re-raised. A ``run_dir`` structural precondition failure (the ``recover``
roster) instead fails closed by RAISING
:class:`~alive.compose.driver.run_dir_state.RunDirStateError`, exactly like
``phase2b`` — the directory is not in a recoverable shape at all. A failed lock
acquisition (a concurrent ``phase2b`` / ``recover``) raises
:class:`RecoverSubcommandError`.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §3.4.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import sys
from pathlib import Path
from typing import Iterator

from alive.compose.driver.run_dir_state import DRIVER_LOCK_FILE, assert_run_dir_roster
from alive.compose.durable import DurableLedgerError, recover_phase2b_durable_outputs
from alive.compose.terminal import TerminalState

__all__ = [
    "RECOVER_COMPLETE_EXIT",
    "RECOVER_NONCOMPLETE_EXIT",
    "RecoverSubcommandError",
    "run_recover_subcommand",
]

#: Exit code for a durable export recovered / verified to a ``COMPLETE`` terminal.
RECOVER_COMPLETE_EXIT = 0

#: Exit code for a non-``COMPLETE`` terminal (``INVALID`` / the synthesized
#: ``ABORTED_AFTER_SEAL``) OR a library fail-closed condition. ``recover`` opens no
#: seal, so a post-seal fail-closed is the CLI's exit-30 "durable export incomplete"
#: outcome, never a silently-swallowed seal violation.
RECOVER_NONCOMPLETE_EXIT = 30


class RecoverSubcommandError(RuntimeError):
    """Raised on a driver-level recover orchestration failure (fail-closed).

    Covers ONLY a failed driver-lock acquisition — a concurrent ``phase2b`` /
    ``recover`` already holds ``run_dir/phase2b.lock``, or the lock file cannot be
    opened. The recovery / synthesis fail-closed conditions are the LIBRARY's
    :class:`~alive.compose.durable.DurableLedgerError` (mapped to exit
    :data:`RECOVER_NONCOMPLETE_EXIT`), and the structural ``run_dir`` precondition
    is :class:`~alive.compose.driver.run_dir_state.RunDirStateError` from the
    ``recover`` roster — neither is re-raised as this type.
    """


# --------------------------------------------------------------------------- #
# Public subcommand
# --------------------------------------------------------------------------- #


def run_recover_subcommand(*, run_dir: str | Path) -> int:
    """Recover / verify the durable Phase-2b publish for ``run_dir`` (spec §3.4).

    Acquires the shared ``run_dir/phase2b.lock``, asserts the ``recover`` roster,
    hands off to the library recovery entry point
    :func:`~alive.compose.durable.recover_phase2b_durable_outputs`, and maps its
    result to an exit code. It loads no outcome source / pair-index / frozen bundle,
    constructs no outcome store, and opens no seal — the seal was already consumed
    by the aborted ``phase2b`` run; ``recover`` only publishes / verifies the durable
    terminal from the EXISTING burned ``audit.jsonl``.

    Parameters
    ----------
    run_dir : str or Path
        The run directory to recover. Must already satisfy the ``recover`` roster
        (spec §7.1): the upstream 4 phase2a artifacts + confirmation present, and
        exactly one of the two disjoint recovery states (a single terminal, or
        ``terminal=0`` with a burned audit claim + its causally-prior pre-access
        provenance + seed-variability report).

    Returns
    -------
    int
        :data:`RECOVER_COMPLETE_EXIT` (``0``) if the durable export is recovered /
        verified to a ``COMPLETE`` terminal; :data:`RECOVER_NONCOMPLETE_EXIT`
        (``30``) for a non-``COMPLETE`` terminal (``INVALID`` / the synthesized
        ``ABORTED_AFTER_SEAL``) or any library fail-closed condition.

    Raises
    ------
    RecoverSubcommandError
        If the driver lock is already held (a concurrent ``phase2b`` / ``recover``)
        or cannot be opened.
    RunDirStateError
        If ``run_dir`` violates the ``recover`` roster (checked before the library
        recovery runs).
    """
    run_dir = Path(run_dir)

    # Step 0: acquire the SAME non-blocking OS-exclusive driver lock the phase2b
    # subcommand uses, then assert the recover roster (a structural precondition
    # that fails closed by RAISING). Both run BEFORE the library recovery.
    with _recover_lock(run_dir):
        assert_run_dir_roster(run_dir, "recover")

        # Step 1: hand off to the library. It owns ALL recovery / synthesis logic
        # (verify-only, idempotent re-publish, or ABORTED_AFTER_SEAL synthesis); the
        # wrapper never re-implements it and never touches the outcome store or seal.
        try:
            result = recover_phase2b_durable_outputs(run_dir=run_dir)
        except DurableLedgerError as exc:
            # POST-seal fail-closed (e.g. a burned audit with 0 records, an invalid
            # pre-access provenance, a divergent partial durable byte). recover opens
            # no seal, so this is the CLI's "durable export incomplete" -> exit 30.
            print(
                f"recover: durable export fail-closed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return RECOVER_NONCOMPLETE_EXIT

        # Step 2: map the verified terminal state to an exit code (result-driven).
        if result.terminal_state == TerminalState.COMPLETE.value:
            return RECOVER_COMPLETE_EXIT
        return RECOVER_NONCOMPLETE_EXIT


# --------------------------------------------------------------------------- #
# Step 0: driver lock (mutually exclusive with a phase2b run on this run_dir)
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def _recover_lock(run_dir: Path) -> Iterator[None]:
    """Hold the non-blocking OS-exclusive ``run_dir/phase2b.lock`` (spec §3.4).

    Acquires the SAME lock file, the SAME way, as
    :func:`~alive.compose.driver.phase2b_cmd.run_phase2b_subcommand` (``flock`` with
    ``LOCK_EX | LOCK_NB`` on the shared :data:`DRIVER_LOCK_FILE`), so a ``recover``
    and a ``phase2b`` run cannot proceed concurrently on one ``run_dir`` — a held
    lock fails closed immediately (never blocks) and the lock is released even if
    this process dies.

    Raises
    ------
    RecoverSubcommandError
        If the lock is already held (a concurrent driver run) or cannot be opened.
    """
    lock_path = run_dir / DRIVER_LOCK_FILE
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise RecoverSubcommandError(
            f"cannot open the phase2b driver lock {str(lock_path)!r}: {exc}"
        ) from exc
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RecoverSubcommandError(
                f"another phase2b/recover holds the driver lock {str(lock_path)!r}; "
                "refusing to run concurrently"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
