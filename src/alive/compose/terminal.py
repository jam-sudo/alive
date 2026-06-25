"""Single-owner terminal state machine for COMPOSE-K562-v1 Phase 2b (Task 2b-7).

This module is the SAFETY NET around the one-time COMPOSE seal opening (CLAUDE.md
§6 multiple-seal rule, §11 write-once provenance). It does NOT open the seal
itself; it guards the lifecycle so the orchestrator (Task 8) can never consume a
seal without producing a durable terminal record.

The guarantee
-------------
Once :meth:`Phase2bTerminal.claim_access` is called — the point the seal is about
to be opened — EVERY exit path leaves exactly one write-once terminal artifact:

  * :attr:`TerminalState.COMPLETE` — a clean sealed evaluation;
  * :attr:`TerminalState.INVALID` — a post-access inconsistency (seal consumed,
    result not trustworthy);
  * :attr:`TerminalState.ABORTED_AFTER_SEAL` — a crash, a silent return, or any
    other exit after the seal was opened with no terminal of its own.

A consumed seal with no terminal artifact is the worst-case failure. The
``try/except/finally`` boundary in :meth:`Phase2bTerminal.protect` /
:meth:`Phase2bTerminal.run_protected` makes that impossible: any exception is
converted to an ``ABORTED_AFTER_SEAL`` artifact and RE-RAISED, and the ``finally``
clause writes an ``ABORTED_AFTER_SEAL`` artifact whenever the state is still
``ACCESS_CLAIMED`` (i.e. no terminal was written).

State machine::

    (initial) --acquire()--> PREPARED --claim_access()--> ACCESS_CLAIMED
                                                              |
                              complete(payload) ------------> COMPLETE
                              invalid(reason) --------------> INVALID
                              aborted(...) / protect finally> ABORTED_AFTER_SEAL

Single ownership is enforced with an exclusive lock file created via
``os.open(..., O_CREAT | O_EXCL | O_WRONLY)`` BEFORE any preflight: a concurrent
or prior owner holding the lock makes :meth:`acquire` raise. :meth:`acquire` also
refuses if ANY terminal artifact already exists or a prior seal audit has
records — both mean the run already happened.

Write discipline (every terminal artifact)
-------------------------------------------
1. Guard the payload — :func:`_assert_no_raw_outcomes` rejects any ``np.ndarray``,
   nested raw cell/observation matrix, or oversized numeric list ANYWHERE in the
   payload (recursive) BEFORE a single byte is written.
2. Install canonical JSON via :func:`alive.compose.io.atomic_write_once`
   (same-directory temp file + flush + fsync of file and dir, then non-overwriting
   ``os.link`` — a second write to the same destination raises ``FileExistsError``).
3. VERIFY the installed file (recompute its sha and confirm) BEFORE touching the
   ledger.
4. Only AFTER the file exists and verifies, append the write-once ledger entry.

Abort artifacts never embed raw outcomes: they carry the exception CLASS NAME, a
SCRUBBED message (numeric arrays stripped via :func:`scrub_exception_message`),
the failing ``stage`` and the preflight artifact CHECKSUMS — never the data.

ACTIVATION BLOCKED: this is code only. It touches no seal, no outcome store and
no real Norman data. The COMPOSE terminal is independent of TG-K562 (§6.3): a
COMPOSE terminal artifact can never represent a CARTOGRAPHER seal, and vice versa.

Public API
----------
TerminalState
    The five-state lifecycle enum.
TerminalError
    Raised on any illegal lifecycle transition, lock/acquire refusal, or
    raw-outcome guard violation.
Phase2bTerminal
    The single-owner terminal state machine.
scrub_exception_message(message)
    Strip numeric arrays / oversized number runs from an exception message so
    abort text can never embed an outcome array.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path

import numpy as np

from alive.compose.io import atomic_write_once
from alive.provenance import (
    DuplicateArtifactError,
    RunLedger,
    sha256_file,
)

#: Maximum length of a flat numeric list before it is treated as a raw outcome
#: vector. Scalar metric vectors (a handful of values) stay well under this; a
#: per-cell or per-gene vector blows past it.
_MAX_NUMERIC_LIST = 64

#: Minimum side length for a nested list-of-lists to be treated as a raw
#: cell/observation matrix (a 2-D numeric block of at least this many rows, each
#: at least this wide). Small fixed-shape diagnostic tables stay under it.
_MATRIX_MIN_ROWS = 4
_MATRIX_MIN_COLS = 4

#: A run of >= this many digit-groups inside a string is treated as an embedded
#: numeric array and scrubbed from exception text.
_SCRUB_MIN_RUN = 4


class TerminalState(Enum):
    """The five-state Phase-2b terminal lifecycle.

    ``PREPARED`` and ``ACCESS_CLAIMED`` are transient; ``COMPLETE``, ``INVALID``
    and ``ABORTED_AFTER_SEAL`` are terminal (each leaves exactly one write-once
    artifact). The initial pre-:meth:`Phase2bTerminal.acquire` state is ``None``.
    """

    PREPARED = "PREPARED"
    ACCESS_CLAIMED = "ACCESS_CLAIMED"
    COMPLETE = "COMPLETE"
    INVALID = "INVALID"
    ABORTED_AFTER_SEAL = "ABORTED_AFTER_SEAL"


class TerminalError(RuntimeError):
    """Raised on an illegal transition, lock refusal, or raw-outcome violation.

    Distinct from :class:`alive.compose.outcome_store.ComposeSealingError` (which
    guards the seal boundary) and the provenance error types: this type is the
    lifecycle / write-once guard around the terminal artifact.

    Parameters
    ----------
    message : str
        Human-readable description of the violation.
    """


# ---------------------------------------------------------------------------
# Raw-outcome guard
# ---------------------------------------------------------------------------


def _looks_like_raw_matrix(obj: object) -> bool:
    """Return ``True`` if ``obj`` is a 2-D numeric block (a raw cell matrix).

    A list/tuple of at least :data:`_MATRIX_MIN_ROWS` rows, each itself a
    list/tuple of at least :data:`_MATRIX_MIN_COLS` numbers.

    Parameters
    ----------
    obj : object
        Candidate structure.

    Returns
    -------
    bool
    """
    if not isinstance(obj, (list, tuple)) or len(obj) < _MATRIX_MIN_ROWS:
        return False
    for row in obj:
        if not isinstance(row, (list, tuple)) or len(row) < _MATRIX_MIN_COLS:
            return False
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in row):
            return False
    return True


def _looks_like_raw_vector(obj: object) -> bool:
    """Return ``True`` if ``obj`` is an oversized flat numeric list.

    A list/tuple longer than :data:`_MAX_NUMERIC_LIST` whose elements are all
    numbers (the shape of a per-cell / per-gene outcome vector). Short scalar
    metric lists stay under the threshold and are allowed.

    Parameters
    ----------
    obj : object
        Candidate structure.

    Returns
    -------
    bool
    """
    if not isinstance(obj, (list, tuple)) or len(obj) <= _MAX_NUMERIC_LIST:
        return False
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in obj)


def _assert_no_raw_outcomes(payload: object) -> None:
    """Recursively reject any raw outcome matrix anywhere in ``payload``.

    Walks the whole structure (mappings, sequences, sets) and raises
    :class:`TerminalError` on the first of:

    * a NumPy ``ndarray`` (or any object exposing ``.shape`` + ``__array__``);
    * a nested raw cell/observation matrix (:func:`_looks_like_raw_matrix`); or
    * an oversized flat numeric list (:func:`_looks_like_raw_vector`).

    Strings and bytes are never recursed into (a digit-bearing string is not a
    matrix). The guard runs BEFORE any artifact byte is written so a rejected
    payload leaves the state and the run directory untouched.

    Parameters
    ----------
    payload : object
        The report / evidence structure about to be persisted.

    Raises
    ------
    TerminalError
        If any raw outcome structure is detected.
    """
    stack: list[object] = [payload]
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))

        if isinstance(cur, np.ndarray):
            raise TerminalError(
                "raw-outcome guard: payload contains a numpy.ndarray "
                f"(shape={cur.shape}); terminal artifacts must be outcome-free."
            )
        # Any non-str object exposing an array interface is treated as raw data.
        if not isinstance(cur, (str, bytes, bytearray)) and hasattr(cur, "__array__"):
            raise TerminalError(
                "raw-outcome guard: payload contains an array-like object "
                f"({type(cur).__name__}); terminal artifacts must be outcome-free."
            )
        if isinstance(cur, (str, bytes, bytearray)):
            continue
        if _looks_like_raw_matrix(cur):
            raise TerminalError(
                "raw-outcome guard: payload contains a nested raw cell/observation "
                "matrix; terminal artifacts must be outcome-free."
            )
        if _looks_like_raw_vector(cur):
            raise TerminalError(
                "raw-outcome guard: payload contains an oversized numeric list "
                f"(len>{_MAX_NUMERIC_LIST}); terminal artifacts must be outcome-free."
            )
        if isinstance(cur, Mapping):
            for key, val in cur.items():
                stack.append(key)
                stack.append(val)
            continue
        if isinstance(cur, (set, frozenset)):
            stack.extend(cur)
            continue
        if isinstance(cur, Sequence):
            stack.extend(cur)
            continue
        # scalars: nothing to recurse into.


#: A run of bracketed/comma-separated numbers (an embedded array literal).
_ARRAY_LITERAL = re.compile(r"[\[\(]\s*-?\d[\d.,eE+\-\s]*[\]\)]")
#: A long run of comma/space separated numbers without brackets.
_NUMBER_RUN = re.compile(r"(?:-?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?[,\s]+){%d,}-?\d" % _SCRUB_MIN_RUN)


def scrub_exception_message(message: str) -> str:
    """Strip embedded numeric arrays from an exception message.

    Abort artifacts persist exception text. A naive message could embed a raw
    outcome array (``str(np.array(...))`` or ``repr(list_of_floats)``). This
    replaces any bracketed array literal or long run of numbers with a redaction
    marker so the persisted text can never carry outcome data. Benign words and
    short numbers (counts, shapes) survive.

    Parameters
    ----------
    message : str
        The raw exception message.

    Returns
    -------
    str
        The message with embedded numeric arrays redacted.
    """
    scrubbed = _ARRAY_LITERAL.sub("<redacted-array>", message)
    scrubbed = _NUMBER_RUN.sub("<redacted-numbers>", scrubbed)
    return scrubbed


# ---------------------------------------------------------------------------
# Terminal state machine
# ---------------------------------------------------------------------------


class NoTerminalWritten(RuntimeError):
    """Sentinel exception: the protected block exited without a terminal write.

    Used as the recorded exception when the ``finally`` safety net fires (a silent
    return left the seal consumed with no terminal of its own). Its class name
    appears as ``exception_class`` in the ``ABORTED_AFTER_SEAL`` artifact.
    """


class Phase2bTerminal:
    """Single-owner terminal state machine guarding the one-time seal opening.

    Holds an exclusive lock over ``run_dir`` for the duration of the run and
    guarantees that, once :meth:`claim_access` is called, every exit path leaves
    exactly one write-once terminal artifact.

    Parameters
    ----------
    run_dir : str or Path
        The run directory that will hold the terminal artifact and the lock file.
        Must already exist.
    ledger : RunLedger
        The write-once provenance ledger; the terminal artifact's hash is recorded
        into it AFTER the file exists and verifies.
    audit_path : str or Path or None, optional
        Path to the durable seal audit (JSONL). When supplied and it already
        contains records, :meth:`acquire` refuses — the seal was already opened.

    Notes
    -----
    Terminal artifact filenames are class constants (:attr:`COMPLETE_ARTIFACT`,
    :attr:`INVALID_ARTIFACT`, :attr:`ABORTED_ARTIFACT`) and are also used as the
    canonical write-once ledger artifact names.
    """

    #: Terminal artifact filenames (also the canonical ledger artifact names).
    COMPLETE_ARTIFACT = "terminal_complete.json"
    INVALID_ARTIFACT = "terminal_invalid.json"
    ABORTED_ARTIFACT = "terminal_aborted.json"
    #: Exclusive evaluation lock filename.
    LOCK_FILE = ".phase2b_terminal.lock"

    def __init__(
        self,
        run_dir: str | Path,
        *,
        ledger: RunLedger,
        audit_path: str | Path | None = None,
    ) -> None:
        self._run_dir = Path(run_dir)
        self._ledger = ledger
        self._audit_path = Path(audit_path) if audit_path is not None else None
        self._state: TerminalState | None = None
        self._lock_fd: int | None = None

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def run_dir(self) -> Path:
        """The run directory holding the terminal artifact and lock."""
        return self._run_dir

    @property
    def ledger(self) -> RunLedger:
        """The write-once provenance ledger."""
        return self._ledger

    @property
    def state(self) -> TerminalState | None:
        """The current lifecycle state (``None`` before :meth:`acquire`)."""
        return self._state

    # ------------------------------------------------------------------
    # Lifecycle: acquire -> claim_access
    # ------------------------------------------------------------------

    def acquire(self) -> None:
        """Acquire the exclusive evaluation lock and pass preflight.

        Acquires the lock BEFORE preflight: creates :attr:`LOCK_FILE` atomically
        with ``os.open(..., O_CREAT | O_EXCL | O_WRONLY)``. If the lock already
        exists (a concurrent or prior owner) this raises. After locking, it
        refuses if ANY terminal artifact already exists, or if a prior seal audit
        has records — both mean the run already happened. On success the state
        becomes :attr:`TerminalState.PREPARED`.

        Raises
        ------
        TerminalError
            If already acquired, if the lock is held, if a terminal artifact
            already exists, or if a prior seal audit has records.
        """
        if self._state is not None:
            raise TerminalError(
                f"acquire() called from state {self._state.value!r}; "
                "the terminal may be acquired exactly once."
            )
        if not self._run_dir.is_dir():
            raise TerminalError(f"run_dir {str(self._run_dir)!r} does not exist.")

        # 1. Acquire the exclusive lock FIRST (before any preflight read).
        lock_path = self._run_dir / self.LOCK_FILE
        try:
            self._lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise TerminalError(
                f"exclusive evaluation lock {str(lock_path)!r} is already held; "
                "a concurrent or prior owner holds the run. Refusing to acquire."
            ) from exc

        # 2. Refuse if any terminal artifact already exists (run already ran).
        existing = [name for name in self._artifact_names() if (self._run_dir / name).exists()]
        if existing:
            raise TerminalError(
                f"terminal artifact(s) already present in run_dir: {existing!r}; "
                "refusing to re-run a run that already has a terminal record."
            )

        # 3. Refuse if a prior seal audit already has records (seal opened).
        if self._audit_path is not None and self._audit_has_records():
            raise TerminalError(
                f"prior seal audit {str(self._audit_path)!r} already has records; "
                "the seal was already opened — refusing to acquire."
            )

        self._state = TerminalState.PREPARED

    def claim_access(self) -> None:
        """Mark the point the seal is about to be opened (``PREPARED -> CLAIMED``).

        After this transition a terminal artifact is MANDATORY on every exit; the
        :meth:`protect` boundary enforces it. Only valid from
        :attr:`TerminalState.PREPARED`.

        Raises
        ------
        TerminalError
            If called from any state other than ``PREPARED``.
        """
        self._require_state(TerminalState.PREPARED, "claim_access")
        self._state = TerminalState.ACCESS_CLAIMED

    # ------------------------------------------------------------------
    # Terminal transitions
    # ------------------------------------------------------------------

    def complete(self, report_payload: Mapping | dict) -> None:
        """Write the ``COMPLETE`` terminal artifact (``CLAIMED -> COMPLETE``).

        Guards the payload (:func:`_assert_no_raw_outcomes`), installs canonical
        JSON via :func:`atomic_write_once`, verifies the installed file, then
        records the write-once ledger entry. Only valid from
        :attr:`TerminalState.ACCESS_CLAIMED`.

        Parameters
        ----------
        report_payload : Mapping
            The outcome-free terminal report (verdict-style summary, metrics,
            checksums — NEVER raw outcome matrices).

        Raises
        ------
        TerminalError
            If not in ``ACCESS_CLAIMED``, if the payload carries raw outcomes, or
            if the destination already exists (write-once).
        """
        self._require_state(TerminalState.ACCESS_CLAIMED, "complete")
        body = dict(report_payload)
        body["terminal_state"] = TerminalState.COMPLETE.value
        self._write_terminal(self.COMPLETE_ARTIFACT, body, payload_to_guard=report_payload)
        self._state = TerminalState.COMPLETE

    def invalid(self, reason: str, *, evidence: Mapping | None = None) -> None:
        """Write the ``INVALID`` terminal artifact (``CLAIMED -> INVALID``).

        Same write/verify/ledger discipline as :meth:`complete`. Used when the
        seal is already consumed but a post-access inconsistency was detected, so
        the result is not trustworthy. Only valid from ``ACCESS_CLAIMED``.

        Parameters
        ----------
        reason : str
            Human-readable reason the run is invalid.
        evidence : Mapping or None, optional
            Optional outcome-free evidence (checksums, ids). Guarded for raw
            outcomes before writing.

        Raises
        ------
        TerminalError
            If not in ``ACCESS_CLAIMED``, if the evidence carries raw outcomes, or
            if the destination already exists (write-once).
        """
        self._require_state(TerminalState.ACCESS_CLAIMED, "invalid")
        evidence = dict(evidence) if evidence is not None else {}
        body = {
            "terminal_state": TerminalState.INVALID.value,
            "reason": reason,
            "evidence": evidence,
        }
        self._write_terminal(self.INVALID_ARTIFACT, body, payload_to_guard=evidence)
        self._state = TerminalState.INVALID

    def aborted(
        self,
        *,
        exception: BaseException,
        stage: str,
        preflight_checksums: Mapping[str, str] | None = None,
    ) -> None:
        """Write the ``ABORTED_AFTER_SEAL`` terminal artifact.

        Records the exception CLASS NAME, a SCRUBBED message (no raw outcomes),
        the failing ``stage`` and the preflight artifact CHECKSUMS — never raw
        outcomes. Only valid from :attr:`TerminalState.ACCESS_CLAIMED`.

        Parameters
        ----------
        exception : BaseException
            The exception that triggered the abort.
        stage : str
            The pipeline stage at which the abort occurred.
        preflight_checksums : Mapping of str to str or None, optional
            Outcome-free preflight artifact checksums to record (never raw data).

        Raises
        ------
        TerminalError
            If not in ``ACCESS_CLAIMED`` or if the destination already exists.
        """
        self._require_state(TerminalState.ACCESS_CLAIMED, "aborted")
        checksums = dict(preflight_checksums) if preflight_checksums is not None else {}
        # Guard the checksum payload too: it must carry no raw outcomes.
        body = {
            "terminal_state": TerminalState.ABORTED_AFTER_SEAL.value,
            "exception_class": type(exception).__name__,
            "message": scrub_exception_message(str(exception)),
            "stage": stage,
            "preflight_checksums": checksums,
        }
        self._write_terminal(self.ABORTED_ARTIFACT, body, payload_to_guard=checksums)
        self._state = TerminalState.ABORTED_AFTER_SEAL

    # ------------------------------------------------------------------
    # Protection boundary — guarantees a terminal artifact on EVERY exit
    # ------------------------------------------------------------------

    def protect(self, *, stage: str = "scoring", preflight_checksums: Mapping | None = None):
        """Context manager guaranteeing a terminal artifact on every post-claim exit.

        Must be entered only after :meth:`claim_access`. Wraps the protected block
        in ``try/except/finally``:

        * on any exception → :meth:`aborted` (recording the exception class, a
          scrubbed message and the stage) then RE-RAISE the original exception;
        * in ``finally`` → if the state is STILL ``ACCESS_CLAIMED`` (no terminal
          was written inside the block, e.g. a silent ``return``), write an
          ``ABORTED_AFTER_SEAL`` artifact with ``stage="no-terminal-written"``.

        If a terminal (``complete`` / ``invalid``) was written inside the block,
        the ``finally`` clause is a no-op — there is always exactly one terminal
        artifact. Entering before ``claim_access`` raises (the seal is not open,
        so no terminal record is owed).

        Parameters
        ----------
        stage : str, optional
            The stage label recorded if the block raises.
        preflight_checksums : Mapping or None, optional
            Outcome-free preflight checksums recorded on abort.

        Returns
        -------
        contextlib.AbstractContextManager
            The protection context manager.

        Raises
        ------
        TerminalError
            If entered before :meth:`claim_access`.
        """
        return _ProtectBoundary(self, stage=stage, preflight_checksums=preflight_checksums)

    def run_protected(
        self,
        fn,
        *,
        stage: str = "scoring",
        preflight_checksums: Mapping | None = None,
    ):
        """Run ``fn()`` inside the :meth:`protect` boundary and return its result.

        Convenience wrapper around :meth:`protect`. Re-raises any exception ``fn``
        raises (after recording the abort artifact). Refuses if called before
        :meth:`claim_access`.

        Parameters
        ----------
        fn : callable
            Zero-argument callable to run inside the protection boundary.
        stage : str, optional
            Stage label recorded on abort.
        preflight_checksums : Mapping or None, optional
            Outcome-free preflight checksums recorded on abort.

        Returns
        -------
        object
            Whatever ``fn()`` returns.

        Raises
        ------
        TerminalError
            If called before :meth:`claim_access`.
        """
        with self.protect(stage=stage, preflight_checksums=preflight_checksums):
            return fn()

    # ------------------------------------------------------------------
    # Private — terminal write/verify/ledger
    # ------------------------------------------------------------------

    def _write_terminal(
        self,
        artifact_name: str,
        body: Mapping,
        *,
        payload_to_guard: object,
    ) -> None:
        """Guard, install (atomic, non-overwriting), verify, then record in ledger.

        The strict order is: (1) reject raw outcomes BEFORE writing; (2) install
        canonical JSON via :func:`atomic_write_once` (raises ``FileExistsError`` if
        the destination exists — write-once); (3) verify the installed file by
        recomputing its sha; (4) only then append the write-once ledger entry.

        Parameters
        ----------
        artifact_name : str
            Terminal artifact filename (also the ledger artifact name).
        body : Mapping
            The full JSON body to install.
        payload_to_guard : object
            The user-supplied portion to scan for raw outcomes.

        Raises
        ------
        TerminalError
            On a raw-outcome violation, a write-once destination conflict, a
            verification failure, or a duplicate ledger entry.
        """
        # 1. Guard BEFORE any byte is written. A rejected payload leaves the run
        #    directory and the ledger completely untouched.
        _assert_no_raw_outcomes(payload_to_guard)

        destination = self._run_dir / artifact_name
        text = json.dumps(body, sort_keys=True, separators=(",", ":"))

        # 2. Atomic, non-overwriting install (FileExistsError if it already exists).
        try:
            atomic_write_once(destination, text)
        except FileExistsError as exc:
            raise TerminalError(
                f"terminal artifact {artifact_name!r} already exists at "
                f"{str(destination)!r}; terminal artifacts are write-once and are "
                "never overwritten."
            ) from exc

        # 3. Verify the installed file before touching the ledger.
        installed_sha = sha256_file(destination)
        if installed_sha != _sha256_text(text):
            raise TerminalError(
                f"terminal artifact {artifact_name!r} failed post-install verification; "
                "the installed bytes do not match the intended content."
            )

        # 4. Only now record the write-once ledger entry (after file verified).
        try:
            self._ledger.record_artifact(artifact_name, installed_sha)
        except DuplicateArtifactError as exc:
            raise TerminalError(
                f"ledger already records a terminal artifact named {artifact_name!r}: {exc}"
            ) from exc
        if not self._ledger.verify_file(artifact_name, destination):
            raise TerminalError(
                f"ledger verify_file failed for terminal artifact {artifact_name!r}."
            )

    # ------------------------------------------------------------------
    # Private — helpers
    # ------------------------------------------------------------------

    def _artifact_names(self) -> tuple[str, ...]:
        return (self.COMPLETE_ARTIFACT, self.INVALID_ARTIFACT, self.ABORTED_ARTIFACT)

    def _require_state(self, expected: TerminalState, action: str) -> None:
        if self._state is not expected:
            current = self._state.value if self._state is not None else None
            raise TerminalError(
                f"{action}() is only valid from {expected.value!r}; current state is {current!r}."
            )

    def _audit_has_records(self) -> bool:
        """Return ``True`` if the seal audit file exists and has >= 1 JSON record.

        An empty (or whitespace-only) audit file counts as no records. A blank
        line is ignored; any non-blank line is a record (no JSON parse needed for
        the existence check — presence of content is sufficient to refuse).
        """
        if self._audit_path is None or not self._audit_path.exists():
            return False
        for line in self._audit_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                return True
        return False


def _sha256_text(text: str) -> str:
    """SHA-256 hex of a UTF-8 string (matches :func:`sha256_file` of the file)."""
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _ProtectBoundary:
    """The ``try/except/finally`` boundary returned by :meth:`Phase2bTerminal.protect`.

    On ``__enter__`` it refuses unless the owner is in ``ACCESS_CLAIMED`` (the
    seal is being / has been opened). On ``__exit__``:

    * an exception → record an ``ABORTED_AFTER_SEAL`` artifact then RE-RAISE;
    * a clean exit with the state STILL ``ACCESS_CLAIMED`` (no terminal written)
      → record an ``ABORTED_AFTER_SEAL`` artifact with
      ``stage="no-terminal-written"``.

    Parameters
    ----------
    owner : Phase2bTerminal
        The terminal whose lifecycle this boundary guards.
    stage : str
        Stage label recorded on an exception.
    preflight_checksums : Mapping or None
        Outcome-free preflight checksums recorded on abort.
    """

    def __init__(
        self,
        owner: Phase2bTerminal,
        *,
        stage: str,
        preflight_checksums: Mapping | None,
    ) -> None:
        self._owner = owner
        self._stage = stage
        self._preflight_checksums = preflight_checksums

    def __enter__(self) -> Phase2bTerminal:
        if self._owner.state is not TerminalState.ACCESS_CLAIMED:
            current = self._owner.state.value if self._owner.state is not None else None
            raise TerminalError(
                "protect() may only wrap post-claim work; current state is "
                f"{current!r} (call claim_access() first)."
            )
        return self._owner

    def __exit__(self, exc_type, exc, exc_tb) -> bool:
        if exc is not None:
            # An exception escaped the block: record the abort then RE-RAISE.
            # If the block had already written a terminal (state no longer
            # ACCESS_CLAIMED), do not attempt a second terminal write.
            if self._owner.state is TerminalState.ACCESS_CLAIMED:
                self._owner.aborted(
                    exception=exc,
                    stage=self._stage,
                    preflight_checksums=self._preflight_checksums,
                )
            return False  # propagate (re-raise) the original exception

        # Clean exit. If no terminal was written inside the block, the seal would
        # be consumed with no terminal record — write the safety-net abort.
        if self._owner.state is TerminalState.ACCESS_CLAIMED:
            self._owner.aborted(
                exception=NoTerminalWritten(
                    "protected block exited without writing a terminal artifact"
                ),
                stage="no-terminal-written",
                preflight_checksums=self._preflight_checksums,
            )
        return False
