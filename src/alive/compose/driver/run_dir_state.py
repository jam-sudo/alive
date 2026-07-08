"""Run-directory basename state machine (COMPOSE production driver, spec §7.1).

There is NO blanket "``run_dir`` must be empty" rule — phase-shared artifacts
mean each subcommand instead validates the EXACT direct-child basename roster
(required / ephemeral-allowed / everything else forbidden) before it calls its
library entry point. This module centralises those four checks:

- ``phase2a``: no run-produced artifact present at entry (stage-1 inputs live
  under the separate immutable ``approved_artifacts_root``, never under
  ``run_dir``); optionally the post-outcome roster too (exactly the 4
  ``CONTINUE`` artifacts, or exactly the futility report).
- ``preflight``: the 4 phase2a artifacts required; confirmation / terminal /
  audit / pre-access / durable artifacts forbidden.
- ``phase2b``: the 4 + the confirmation manifest required; terminal / audit /
  pre-access / durable artifacts forbidden at entry; the driver lock and the
  terminal's own lock are ephemeral-allowed.
- ``recover``: same two locks ephemeral-allowed; the upstream 4 + confirmation
  must already exist, and exactly one of two disjoint states must hold —
  exactly-one-terminal, or (terminal absent + a durable audit claim with its
  causally-prior pre-access provenance); an already-produced partial subset of
  the durable finalize artifacts is accepted as crash-recovery input only
  alongside a terminal.

This module is pure directory-listing + basename-roster comparison. It opens
no seal, constructs no outcome store, and imports no ``gears``/``cpa`` — it
never reads file *contents*, only ``os.listdir`` of ``run_dir`` itself.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §7.1
(+ §3.1/§3.2/§3.3/§3.4 for each subcommand's installs).
"""

from __future__ import annotations

import os
from pathlib import Path

from alive.compose.driver.run_spec import RUN_PRODUCED_BASENAMES
from alive.compose.durable import (
    DURABLE_COMMIT_FILENAME,
    FINAL_LEDGER_FILENAME,
    REGISTERED_SUMMARY_FILENAME,
    SEAL_AUDIT_FILENAME,
)
from alive.compose.provenance2 import PRE_ACCESS_LEDGER_FILENAME
from alive.compose.terminal import Phase2bTerminal

__all__ = [
    "DRIVER_LOCK_FILE",
    "RunDirStateError",
    "assert_run_dir_roster",
]


class RunDirStateError(ValueError):
    """Raised when ``run_dir``'s direct-child basename roster violates spec §7.1.

    Fail-closed: raised on a forbidden/unknown basename present OR a required
    basename missing (or, for ``recover``, on neither of its two valid states
    holding).
    """


#: Driver-owned non-blocking exclusive lock guarding phase2b/recover
#: concurrency (spec §3.3 step 0: ``run_dir/phase2b.lock``). This is DISTINCT
#: from :attr:`Phase2bTerminal.LOCK_FILE` (``.phase2b_terminal.lock``), which
#: the terminal state machine acquires itself during ``run_phase2b`` — both are
#: ephemeral lock files and the ``phase2b``/``recover`` rosters allow both.
DRIVER_LOCK_FILE = "phase2b.lock"

# ---------------------------------------------------------------------------
# Basename groups, all sourced from the pinned upstream constants (never
# hardcoded here where a constant already provides the string).
# ---------------------------------------------------------------------------

_FROZEN_BUNDLE = RUN_PRODUCED_BASENAMES["frozen_bundle"]
_OOF_MANIFEST = RUN_PRODUCED_BASENAMES["oof_manifest"]
_SEED_VARIABILITY_REPORT = RUN_PRODUCED_BASENAMES["phase2a_seed_variability_report"]
_RUN_LEDGER = RUN_PRODUCED_BASENAMES["run_ledger"]
_FUTILITY_REPORT = RUN_PRODUCED_BASENAMES["futility_report"]
_CONFIRMATION_MANIFEST = RUN_PRODUCED_BASENAMES["seal_confirmation_manifest"]

#: The 4 phase2a ``CONTINUE`` artifacts (spec §3.1 / §7.1) — the shared
#: upstream roster that ``preflight``, ``phase2b`` and ``recover`` all build on.
_PHASE2A_CONTINUE_BASENAMES: frozenset[str] = frozenset(
    {_FROZEN_BUNDLE, _OOF_MANIFEST, _SEED_VARIABILITY_REPORT, _RUN_LEDGER}
)

#: The 4 phase2a artifacts + the confirmation manifest (spec §3.3 entry roster).
_PHASE2B_ENTRY_REQUIRED: frozenset[str] = _PHASE2A_CONTINUE_BASENAMES | {_CONFIRMATION_MANIFEST}

_TERMINAL_BASENAMES: frozenset[str] = frozenset(
    {
        Phase2bTerminal.COMPLETE_ARTIFACT,
        Phase2bTerminal.INVALID_ARTIFACT,
        Phase2bTerminal.ABORTED_ARTIFACT,
    }
)

_DURABLE_BASENAMES: frozenset[str] = frozenset(
    {REGISTERED_SUMMARY_FILENAME, FINAL_LEDGER_FILENAME, DURABLE_COMMIT_FILENAME}
)

#: Both ephemeral lock files (spec §7.1 + the two-lock distinction: a
#: driver-owned ``phase2b.lock`` and the terminal's own ``.phase2b_terminal.lock``).
_EPHEMERAL_LOCK_BASENAMES: frozenset[str] = frozenset({DRIVER_LOCK_FILE, Phase2bTerminal.LOCK_FILE})

_SUBCOMMANDS: frozenset[str] = frozenset({"phase2a", "preflight", "phase2b", "recover"})
_PHASE2A_OUTCOMES: frozenset[str] = frozenset({"CONTINUE", "FUTILITY_STOPPED"})


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _listdir_basenames(run_dir: Path) -> frozenset[str]:
    """Direct-child basenames of ``run_dir`` (no recursion, no content reads)."""
    try:
        return frozenset(os.listdir(run_dir))
    except OSError as exc:
        raise RunDirStateError(f"cannot list run_dir {run_dir}: {exc}") from exc


def _check_closed_roster(
    present: frozenset[str],
    required: frozenset[str],
    allowed_extra: frozenset[str],
    *,
    where: str,
) -> None:
    """Assert ``present`` is exactly ``required`` plus optional ``allowed_extra``.

    Fails closed both ways: any ``required`` basename missing raises, and any
    basename present that is neither ``required`` nor ``allowed_extra`` raises
    (this uniformly covers both an explicitly forbidden artifact from another
    phase and a genuinely unrecognised/unknown file — §7.1 draws no
    distinction between the two at the roster level).
    """
    missing = required - present
    if missing:
        raise RunDirStateError(f"{where}: required basename(s) missing: {sorted(missing)}")
    permitted = required | allowed_extra
    unexpected = present - permitted
    if unexpected:
        raise RunDirStateError(
            f"{where}: forbidden or unrecognised basename(s) present: {sorted(unexpected)}"
        )


# ---------------------------------------------------------------------------
# Per-subcommand rosters
# ---------------------------------------------------------------------------


def _assert_phase2a_roster(present: frozenset[str], phase2a_outcome: str | None) -> None:
    if phase2a_outcome is None:
        # Entry: no run-produced/terminal/confirmation/durable artifact of ANY
        # kind may exist yet — stage-1 inputs live under approved_artifacts_root,
        # never under run_dir (spec §3.1/§7.1).
        _check_closed_roster(present, frozenset(), frozenset(), where="phase2a (entry)")
        return
    if phase2a_outcome == "CONTINUE":
        _check_closed_roster(
            present, _PHASE2A_CONTINUE_BASENAMES, frozenset(), where="phase2a (CONTINUE)"
        )
        return
    if phase2a_outcome == "FUTILITY_STOPPED":
        _check_closed_roster(
            present, frozenset({_FUTILITY_REPORT}), frozenset(), where="phase2a (FUTILITY_STOPPED)"
        )
        return
    raise RunDirStateError(
        f"phase2a: unrecognised phase2a_outcome {phase2a_outcome!r}; "
        f"expected None or one of {sorted(_PHASE2A_OUTCOMES)}"
    )


def _assert_preflight_roster(present: frozenset[str]) -> None:
    # The 4 phase2a artifacts required; confirmation/terminal/audit/pre-access/
    # durable forbidden (spec §3.2/§7.1). preflight's own success install
    # (seal_confirmation_manifest.json) is the subcommand's job, not checked here.
    _check_closed_roster(
        present, _PHASE2A_CONTINUE_BASENAMES, frozenset(), where="preflight (entry)"
    )


def _assert_phase2b_roster(present: frozenset[str]) -> None:
    # The 4 + confirmation required; terminal/audit/pre-access/durable forbidden
    # at entry; both ephemeral locks allowed (spec §3.3 step 0/§7.1).
    _check_closed_roster(
        present,
        _PHASE2B_ENTRY_REQUIRED,
        _EPHEMERAL_LOCK_BASENAMES,
        where="phase2b (entry)",
    )


def _assert_recover_roster(present: frozenset[str]) -> None:
    # Both ephemeral locks may be present regardless of state; strip them
    # before classifying the meaningful (non-lock) roster (spec §3.4/§7.1).
    core = present - _EPHEMERAL_LOCK_BASENAMES

    missing_base = _PHASE2B_ENTRY_REQUIRED - core
    if missing_base:
        raise RunDirStateError(
            f"recover: required upstream basename(s) missing: {sorted(missing_base)}"
        )

    terminal_present = core & _TERMINAL_BASENAMES
    if len(terminal_present) > 1:
        raise RunDirStateError(
            f"recover: more than one terminal artifact present: {sorted(terminal_present)}"
        )

    known = (
        _PHASE2B_ENTRY_REQUIRED
        | _TERMINAL_BASENAMES
        | _DURABLE_BASENAMES
        | {SEAL_AUDIT_FILENAME, PRE_ACCESS_LEDGER_FILENAME}
    )
    unknown = core - known
    if unknown:
        raise RunDirStateError(
            f"recover: forbidden or unrecognised basename(s) present: {sorted(unknown)}"
        )

    if terminal_present:
        # State 1: exactly-one-terminal. A byte-identical partial subset of the
        # durable finalize artifacts (registered summary/final ledger/commit
        # marker), plus the audit claim and its pre-access provenance, are all
        # accepted as already-produced crash-recovery input (spec §3.4). Their
        # BYTE content is not re-verified here (pure basename check) — that is
        # the recovery library entry point's job.
        return

    # State 2: terminal=0 -> requires exactly-one durable audit claim together
    # with its causally-prior pre-access provenance (spec §3.3 step 5 order:
    # pre-access ledger -> durable audit claim -> terminal -> durable finalize).
    audit_present = SEAL_AUDIT_FILENAME in core
    pre_access_present = PRE_ACCESS_LEDGER_FILENAME in core
    if not audit_present:
        raise RunDirStateError(
            "recover: terminal=0 and no durable audit claim "
            f"({SEAL_AUDIT_FILENAME!r}) present — not a valid recover state"
        )
    if not pre_access_present:
        raise RunDirStateError(
            "recover: terminal=0 audit claim present without its causally-prior "
            f"pre-access provenance ({PRE_ACCESS_LEDGER_FILENAME!r}) — inconsistent partial state"
        )
    durable_present = core & _DURABLE_BASENAMES
    if durable_present:
        raise RunDirStateError(
            "recover: durable finalize artifact(s) present without a terminal — "
            f"invalid partial state: {sorted(durable_present)}"
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def assert_run_dir_roster(
    run_dir: str | Path,
    subcommand: str,
    *,
    phase2a_outcome: str | None = None,
) -> None:
    """Assert ``run_dir``'s direct-child basenames match ``subcommand``'s §7.1 roster.

    Parameters
    ----------
    run_dir
        The run directory to inspect. Must already exist; only its DIRECT
        children are listed (no recursion, no file-content reads).
    subcommand
        One of ``"phase2a"``, ``"preflight"``, ``"phase2b"``, ``"recover"``.
    phase2a_outcome
        Only meaningful when ``subcommand == "phase2a"``. ``None`` checks the
        ENTRY roster (nothing installed yet). ``"CONTINUE"`` or
        ``"FUTILITY_STOPPED"`` checks the POST-run roster for that outcome.

    Raises
    ------
    RunDirStateError
        On an unrecognised ``subcommand``/``phase2a_outcome``, a misuse of
        ``phase2a_outcome`` outside ``subcommand == "phase2a"``, a forbidden or
        unrecognised basename present, a required basename missing, or (for
        ``recover``) neither of its two valid states holding.
    """
    if subcommand not in _SUBCOMMANDS:
        raise RunDirStateError(
            f"unrecognised subcommand {subcommand!r}; expected one of {sorted(_SUBCOMMANDS)}"
        )
    if phase2a_outcome is not None and subcommand != "phase2a":
        raise RunDirStateError(
            "phase2a_outcome is only meaningful for subcommand='phase2a', "
            f"got subcommand={subcommand!r}"
        )

    present = _listdir_basenames(Path(run_dir))

    if subcommand == "phase2a":
        _assert_phase2a_roster(present, phase2a_outcome)
    elif subcommand == "preflight":
        _assert_preflight_roster(present)
    elif subcommand == "phase2b":
        _assert_phase2b_roster(present)
    else:
        _assert_recover_roster(present)
