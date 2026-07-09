"""Single-owner terminal state machine for COMPOSE-K562-v1 Phase 2b (Task 2b-7).

This module is the SAFETY NET around the one-time COMPOSE seal opening
(CLAUDE.md#seal multiple-seal rule, #provenance write-once provenance). It does NOT open the seal
itself; it guards the lifecycle so the orchestrator (Task 8) can never consume a
seal without producing a durable terminal record.

The guarantee
-------------
Once :meth:`Phase2bTerminal.confirm_durable_access` advances the terminal to
``ACCESS_CLAIMED`` — the point the durable audit proves the seal is consumed —
EVERY exit path leaves exactly one write-once terminal artifact:

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

    (initial) --acquire()--> PREPARED --attempt_access()--> ACCESS_ATTEMPTED
                                                                  |
                              confirm_durable_access(ref) ------> ACCESS_CLAIMED
                                                                  |
                              complete(payload) --------------> COMPLETE
                              invalid(reason) ----------------> INVALID
                              aborted(...) / protect finally--> ABORTED_AFTER_SEAL

An exception in ``ACCESS_ATTEMPTED`` (before the durable audit) writes NO terminal
— the seal was never consumed. The deprecated one-step in-memory claim
(``PREPARED -> ACCESS_CLAIMED`` with no durable reference) was RETIRED in D1 Task
4H; the ONLY route to ``ACCESS_CLAIMED`` is :meth:`Phase2bTerminal.attempt_access`
then :meth:`Phase2bTerminal.confirm_durable_access` (a VERIFIED durable reference).

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
2. Install canonical JSON via :func:`alive.io.atomic_write_once`
   (same-directory temp file + flush + fsync of file and dir, then non-overwriting
   ``os.link`` — a second write to the same destination raises ``FileExistsError``).
3. VERIFY the installed file (recompute its sha and confirm) BEFORE touching the
   ledger.
4. Only AFTER the file exists and verifies, append the write-once ledger entry.

Abort artifacts never embed raw outcomes: they carry the exception CLASS NAME, a
SCRUBBED message (numeric arrays stripped via :func:`scrub_exception_message`),
the failing ``stage`` and the preflight artifact CHECKSUMS — never the data.

SYNTHETIC-ONLY: this is code only. It touches no seal, no outcome store and
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

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path

import numpy as np

from alive.io import atomic_write_once
from alive.provenance import (
    DuplicateArtifactError,
    RunLedger,
    sha256_file,
    sha256_json,
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
    """The six-state Phase-2b terminal lifecycle.

    ``PREPARED``, ``ACCESS_ATTEMPTED`` and ``ACCESS_CLAIMED`` are transient;
    ``COMPLETE``, ``INVALID`` and ``ABORTED_AFTER_SEAL`` are terminal (each leaves
    exactly one write-once artifact). The initial pre-:meth:`Phase2bTerminal.acquire`
    state is ``None``.

    ``ACCESS_ATTEMPTED`` is the window between "about to open the seal" and the
    durable audit write: an exception here writes NO terminal (the seal was never
    durably consumed, ``sealed_access_count == 0``). Only a VERIFIED durable audit
    reference (:meth:`Phase2bTerminal.confirm_durable_access`) advances
    ``ACCESS_ATTEMPTED -> ACCESS_CLAIMED``; from ``ACCESS_CLAIMED`` every exit path
    leaves exactly one terminal artifact.
    """

    PREPARED = "PREPARED"
    ACCESS_ATTEMPTED = "ACCESS_ATTEMPTED"
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

    This is a COARSE BACKSTOP, not the primary owner of the no-raw-outcome
    property. The contract is that the Task-8 orchestrator constructs every
    terminal payload as a summary / checksum-only structure (verdicts, scalar
    metrics, ids, hashes) and is RESPONSIBLE for never handing raw outcomes to
    the terminal. This guard exists to catch a gross programming mistake (a whole
    expression matrix or per-cell vector leaking in), not to certify an
    adversarial payload safe.

    Walks the whole structure (mappings, sequences, sets) and raises
    :class:`TerminalError` on the first of:

    * a NumPy ``ndarray`` (or any object exposing ``.shape`` + ``__array__``);
    * a nested raw cell/observation matrix (:func:`_looks_like_raw_matrix`); or
    * an oversized flat numeric list (:func:`_looks_like_raw_vector`).

    Threshold rationale
    -------------------
    The matrix / vector thresholds (:data:`_MATRIX_MIN_ROWS`,
    :data:`_MATRIX_MIN_COLS`, :data:`_MAX_NUMERIC_LIST`) are deliberately set
    ABOVE the smallest legitimate scalar metric table so that legitimate summary
    payloads (a 3x3 confusion-style table, a handful of per-method metric
    scalars, a short per-fold score list) never false-positive. The cost of that
    headroom is that a small raw block (e.g. a 3x3 numeric matrix or a 50-element
    float vector) can slip past — which is acceptable precisely because this is a
    backstop and the orchestrator, not this function, owns the property. Do NOT
    lower the thresholds to chase such cases: that would reject legitimate metric
    tables and is the wrong layer to enforce the invariant.

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
# v2 terminal payload schema + canonical checksum input
# ---------------------------------------------------------------------------

#: The versioned terminal payload schema string carried by every v2 terminal body.
TERMINAL_SCHEMA_V2 = "compose_phase2b_terminal_v2"

#: The self-excluding checksum field name (excluded from its own checksum input).
TERMINAL_PAYLOAD_CHECKSUM_FIELD = "terminal_payload_checksum"

#: The common exact identity fields injected into EVERY terminal body BEFORE the
#: self-excluding :data:`TERMINAL_PAYLOAD_CHECKSUM_FIELD`. Writer, recovery reader
#: and durable finalizer all agree on this one roster (CLAUDE.md#provenance).
_COMMON_TERMINAL_FIELDS = frozenset(
    {
        "schema",
        "protocol",
        "run_id",
        "terminal_state",
        "sealed_access_count",
        "seal_audit_reference",
        "pre_access_ledger_sha256",
        "pre_access_provenance_checksum",
    }
)

#: The subset of :data:`_COMMON_TERMINAL_FIELDS` whose VALUE must be a non-empty
#: string, not merely present (CLAUDE.md#provenance). These are the run-identity anchors:
#: a seal artifact recorded with a null/empty protocol, run id, seal reference or
#: pre-access provenance identity is un-attributable and must NEVER be written
#: (fail closed). Deliberately EXCLUDES ``schema`` (a writer-injected constant),
#: ``terminal_state`` (an enum value validated by the filename↔state check) and
#: ``sealed_access_count`` (an int; ``0`` is a valid value and the count is
#: prevented structurally by the durable-audit path, not here).
_REQUIRED_NONEMPTY_IDENTITY_FIELDS = frozenset(
    {
        "protocol",
        "run_id",
        "seal_audit_reference",
        "pre_access_ledger_sha256",
        "pre_access_provenance_checksum",
    }
)


def canonicalize_terminal_checksum_input(value: object) -> object:
    """Canonicalise a terminal payload value for ``terminal_payload_checksum``.

    The SINGLE source of truth shared by the terminal writer, the recovery reader,
    the durable finalizer and the tests: the writer and every verifier hash the
    body through THIS function, never by applying :func:`sha256_json` to the raw
    decoded body. Recursively it

    * sorts mappings by (stringified) key and recurses into their values;
    * preserves ``int``, ``str``, ``bool`` and ``None`` verbatim;
    * converts every FINITE ``float`` to its exact ``float.hex()`` string so the
      hash does not depend on a platform-specific decimal ``repr``;
    * recurses into ``list`` / ``tuple`` (both emitted as lists so a tuple in the
      in-memory body and the list it round-trips to through JSON hash equally);
    * REJECTS a non-finite float (``NaN`` / ``Infinity``) or any unsupported type
      with :class:`TerminalError`.

    The PERSISTED terminal JSON keeps ordinary finite JSON numbers; only this
    checksum input substitutes ``float.hex()`` strings. Because a finite float
    round-trips through JSON to the identical value, the writer's hash of the
    in-memory body and a verifier's hash of the reloaded body agree.

    Parameters
    ----------
    value : object
        A terminal body (or any nested value) to canonicalise.

    Returns
    -------
    object
        A structure of mappings, lists, ints, strings, booleans, ``None`` and
        ``float.hex()`` strings, safe to pass to :func:`sha256_json`.

    Raises
    ------
    TerminalError
        If ``value`` contains a non-finite float or an unsupported type.
    """
    # ``bool`` is a subclass of ``int``; both are preserved verbatim here.
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TerminalError(
                "terminal checksum input rejects a non-finite float "
                f"({value!r}); every terminal float must be finite (no NaN/Infinity)."
            )
        return value.hex()
    if isinstance(value, Mapping):
        return {
            str(key): canonicalize_terminal_checksum_input(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize_terminal_checksum_input(item) for item in value]
    raise TerminalError(
        "terminal checksum input rejects an unsupported value of type "
        f"{type(value).__name__!r}; terminal payloads must contain only mappings, "
        "lists, tuples, strings, integers, booleans, finite floats and null."
    )


#: The exact state-specific roster shared by ``COMPLETE`` and ``INVALID`` (spec
#: §2.1). Both terminals carry the outcome-free registered evaluation summary and
#: its canonical embedded provenance PLUS the four layered content checksums. An
#: ``INVALID`` terminal builds the same summary AFTER the verdict is swapped to
#: ``INVALID`` (so ``final_verdict_checksum`` / ``final_result_checksum`` differ),
#: never reusing the normal verdict payload checksum. There is no free-form
#: ``reason`` / ``evidence`` roster any more: the reason lives inside the summary
#: (the swapped verdict clauses / evidence) and is bound by the checksums.
_COMPLETE_INVALID_STATE_FIELDS = frozenset(
    {
        "registered_summary",
        "registered_summary_checksum",
        "final_verdict_checksum",
        "terminal_embedded_provenance",
        "provenance_checksum",
        "evaluation_payload_checksum",
        "final_result_checksum",
    }
)

#: State-specific exact field rosters. Every terminal state now carries a FIXED set
#: of state fields validated exactly against ``common ∪ state`` (missing OR unknown
#: key → :class:`TerminalError`). ``COMPLETE`` / ``INVALID`` share
#: :data:`_COMPLETE_INVALID_STATE_FIELDS`; ``ABORTED_AFTER_SEAL`` keeps its own
#: minimal abort roster (Task 4 owns the v2 ABORTED body).
_STATE_TERMINAL_FIELDS: dict[TerminalState, frozenset[str] | None] = {
    TerminalState.COMPLETE: _COMPLETE_INVALID_STATE_FIELDS,
    TerminalState.INVALID: _COMPLETE_INVALID_STATE_FIELDS,
    TerminalState.ABORTED_AFTER_SEAL: frozenset(
        {
            "exception_class",
            "message",
            "stage",
            "preflight_checksums",
            "audit_reference",
            "registered_results_status",
        }
    ),
}


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
    guarantees that, once :meth:`confirm_durable_access` reaches ``ACCESS_CLAIMED``,
    every exit path leaves exactly one write-once terminal artifact.

    The no-raw-outcome property of terminal artifacts is OWNED BY the Task-8
    orchestrator, which must construct every payload as a summary / checksum-only
    structure. :func:`_assert_no_raw_outcomes` here is only a COARSE BACKSTOP
    against a gross leak (a whole matrix / per-cell vector), not a certification
    that an arbitrary payload is outcome-free.

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
        protocol: str | None = None,
        run_id: str | None = None,
        pre_access_ledger_sha256: str | None = None,
        pre_access_provenance_checksum: str | None = None,
    ) -> None:
        self._run_dir = Path(run_dir)
        self._ledger = ledger
        self._audit_path = Path(audit_path) if audit_path is not None else None
        self._state: TerminalState | None = None
        self._lock_fd: int | None = None
        #: The durable audit reference confirmed by :meth:`confirm_durable_access`
        #: (``None`` until confirmed / on the deprecated in-memory path). Emitted as
        #: the common ``seal_audit_reference`` field and, in ``ABORTED_AFTER_SEAL``
        #: artifacts, also as the state ``audit_reference`` — durable proof of
        #: consumption.
        self._audit_reference: str | None = None
        #: v2 common identity fields (CLAUDE.md#provenance). ``protocol`` / ``run_id`` are
        #: known at construction; the pre-access provenance identity is only known
        #: after the pre-access ledger is persisted and is bound via
        #: :meth:`bind_pre_access` BEFORE the seal-open block, so an ABORT written
        #: from the protection boundary (no caller payload) still emits the full
        #: common roster.
        self._protocol = protocol
        self._run_id = run_id
        self._pre_access_ledger_sha256 = pre_access_ledger_sha256
        self._pre_access_provenance_checksum = pre_access_provenance_checksum

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
    # v2 identity binding
    # ------------------------------------------------------------------

    def bind_pre_access(
        self,
        *,
        pre_access_ledger_sha256: str,
        pre_access_provenance_checksum: str,
    ) -> None:
        """Bind the pre-access provenance identity onto the terminal instance.

        These two common fields — the SHA-256 of the persisted pre-access ledger
        file and the self-excluding checksum of the pre-access provenance payload —
        are only available AFTER the pre-access ledger is persisted, which is after
        :meth:`acquire` but BEFORE :meth:`attempt_access`. They are terminal-INSTANCE
        state (not per-call) so that an ``ABORTED_AFTER_SEAL`` written from the
        protection boundary (which has no caller payload) still emits the full
        common identity roster. Only valid from ``PREPARED`` (exactly the production
        call site: after ``acquire`` and the pre-access ledger persist, before
        ``attempt_access``) — binding from any other state, including the pre-audit
        ``ACCESS_ATTEMPTED`` window, is refused.

        Parameters
        ----------
        pre_access_ledger_sha256 : str
            SHA-256 of the persisted pre-access ledger file.
        pre_access_provenance_checksum : str
            Self-excluding checksum of the pre-access provenance payload.

        Raises
        ------
        TerminalError
            If called from any state other than ``PREPARED``.
        """
        self._require_state(TerminalState.PREPARED, "bind_pre_access")
        self._pre_access_ledger_sha256 = pre_access_ledger_sha256
        self._pre_access_provenance_checksum = pre_access_provenance_checksum

    # ------------------------------------------------------------------
    # Lifecycle: acquire -> attempt_access -> confirm_durable_access
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
        # The lock FILE on disk is the lock (O_EXCL); the descriptor is not needed
        # once it exists. Close it so we never leak a fd. Never unlink the file.
        os.close(self._lock_fd)
        self._lock_fd = None

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

    def attempt_access(self) -> None:
        """Enter the pre-durable-audit window (``PREPARED -> ACCESS_ATTEMPTED``).

        Marks the point at which the seal is ABOUT to be opened but the durable
        audit has NOT yet been written. An exception in ``ACCESS_ATTEMPTED`` writes
        NO terminal artifact (the seal was never durably consumed — count 0):
        :meth:`protect` refuses to wrap ``ACCESS_ATTEMPTED`` work and
        :meth:`aborted` refuses to run from it. Only valid from
        :attr:`TerminalState.PREPARED`.

        Raises
        ------
        TerminalError
            If called from any state other than ``PREPARED``.
        """
        self._require_state(TerminalState.PREPARED, "attempt_access")
        self._state = TerminalState.ACCESS_ATTEMPTED

    def confirm_durable_access(self, audit_reference: str) -> None:
        """Confirm the durable seal consumption (``ACCESS_ATTEMPTED -> CLAIMED``).

        Only a VERIFIED durable audit reference advances the terminal into
        ``ACCESS_CLAIMED``, after which a terminal artifact is MANDATORY on every
        exit (the :meth:`protect` boundary enforces it) and any
        ``ABORTED_AFTER_SEAL`` is only ever written post-audit (count 1).

        The reference must be a non-empty string (a real claim receipt — an empty
        or absent reference is not durable proof). When this terminal was
        constructed with an ``audit_path``, the durable audit is additionally
        required to already carry records (the seal really is burned on disk).
        Only valid from :attr:`TerminalState.ACCESS_ATTEMPTED`.

        Parameters
        ----------
        audit_reference : str
            The durable identity of the written audit record (from the store's
            :class:`~alive.compose.outcome_store.SealedAccessClaim`).

        Raises
        ------
        TerminalError
            If not in ``ACCESS_ATTEMPTED``, if ``audit_reference`` is empty, or if
            an ``audit_path`` was supplied but has no durable records yet.
        """
        self._require_state(TerminalState.ACCESS_ATTEMPTED, "confirm_durable_access")
        if not isinstance(audit_reference, str) or not audit_reference:
            raise TerminalError(
                "confirm_durable_access requires a non-empty durable audit reference; "
                "an empty reference is not proof the seal was durably consumed."
            )
        if self._audit_path is not None and not self._audit_has_records():
            raise TerminalError(
                f"confirm_durable_access refused: audit {str(self._audit_path)!r} has "
                "no durable records; the seal is not yet burned on disk."
            )
        self._audit_reference = audit_reference
        self._state = TerminalState.ACCESS_CLAIMED

    # NOTE: the deprecated in-memory one-step claim (``PREPARED -> ACCESS_CLAIMED``
    # with no durable audit reference) was RETIRED in D1 Task 4H. It was the only
    # way to reach a terminal write with a null run identity; removing it lets
    # ``_validate_terminal_roster`` fail closed on an empty identity. The ONLY route
    # to ``ACCESS_CLAIMED`` is now :meth:`attempt_access` then
    # :meth:`confirm_durable_access` (a VERIFIED durable audit reference).

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

    def invalid(self, report_payload: Mapping | dict) -> None:
        """Write the ``INVALID`` terminal artifact (``CLAIMED -> INVALID``).

        Same write/verify/ledger discipline and the SAME state roster as
        :meth:`complete` (spec §2.1): the seal is already consumed but a
        post-access inconsistency was detected, so the caller builds the registered
        evaluation summary AFTER swapping the verdict to ``INVALID`` and hands the
        full v2 report body here. Only valid from ``ACCESS_CLAIMED``.

        Parameters
        ----------
        report_payload : Mapping
            The outcome-free INVALID report — exactly the
            :data:`_COMPLETE_INVALID_STATE_FIELDS` state fields (the registered
            summary + embedded provenance + the four layered checksums). Guarded
            for raw outcomes before writing.

        Raises
        ------
        TerminalError
            If not in ``ACCESS_CLAIMED``, if the payload carries raw outcomes, if it
            does not match the exact ``common ∪ state`` roster, or if the
            destination already exists (write-once).
        """
        self._require_state(TerminalState.ACCESS_CLAIMED, "invalid")
        body = dict(report_payload)
        body["terminal_state"] = TerminalState.INVALID.value
        self._write_terminal(self.INVALID_ARTIFACT, body, payload_to_guard=report_payload)
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

        The CORE abort record — state ``ABORTED_AFTER_SEAL``, the exception class
        name, the scrubbed message and the stage — must essentially always be
        writable: it is the durable proof a consumed seal did not vanish silently.
        Therefore an unsafe ``preflight_checksums`` block (one that fails the
        raw-outcome guard, or is otherwise unserialisable) is DROPPED — recorded as
        ``"OMITTED_UNSAFE"`` — rather than allowed to block the core record. The
        scrubbed message is still never allowed to embed raw outcomes.

        Parameters
        ----------
        exception : BaseException
            The exception that triggered the abort.
        stage : str
            The pipeline stage at which the abort occurred.
        preflight_checksums : Mapping of str to str or None, optional
            Outcome-free preflight artifact checksums to record (never raw data).
            If they carry raw outcomes or are otherwise unserialisable they are
            dropped (``"OMITTED_UNSAFE"``) so the core abort record still writes.

        Raises
        ------
        TerminalError
            If not in ``ACCESS_CLAIMED`` or if the destination already exists.
        """
        self._require_state(TerminalState.ACCESS_CLAIMED, "aborted")
        checksums: object = dict(preflight_checksums) if preflight_checksums is not None else {}
        # The optional checksum block must never block the core abort record. If it
        # carries raw outcomes (guard rejection) or cannot be JSON-serialised, drop
        # it for a safe marker rather than failing the whole abort write.
        try:
            _assert_no_raw_outcomes(checksums)
            json.dumps(checksums, sort_keys=True, separators=(",", ":"))
        except (TerminalError, TypeError, ValueError):
            checksums = "OMITTED_UNSAFE"
        body = {
            "terminal_state": TerminalState.ABORTED_AFTER_SEAL.value,
            "exception_class": type(exception).__name__,
            "message": scrub_exception_message(str(exception)),
            "stage": stage,
            "preflight_checksums": checksums,
            "audit_reference": self._audit_reference,
            # An abort re-raises with NO trustworthy result (spec §2.2): the seal is
            # consumed but there is no registered evaluation to embed. This marker
            # makes that explicit so a reader never mistakes an abort for a result.
            "registered_results_status": "NOT_AVAILABLE_DUE_TO_ABORT",
        }
        # The body's checksum field is now guaranteed safe, so guard the (possibly
        # reduced) value rather than the original unsafe input.
        self._write_terminal(self.ABORTED_ARTIFACT, body, payload_to_guard=checksums)
        self._state = TerminalState.ABORTED_AFTER_SEAL

    # ------------------------------------------------------------------
    # Recovery-sanctioned entry — the audit=1 / terminal=0 post-crash state
    # ------------------------------------------------------------------

    @classmethod
    def recover_aborted_after_seal(
        cls,
        run_dir: str | Path,
        *,
        ledger: RunLedger,
        audit_path: str | Path,
        protocol: str,
        run_id: str,
        pre_access_ledger_sha256: str,
        pre_access_provenance_checksum: str,
        exception: BaseException,
        stage: str,
    ) -> None:
        """Recovery-ONLY terminal write for the ``audit=1`` / ``terminal=0`` crash state.

        A hard process death AFTER the durable seal claim
        (:meth:`~alive.compose.outcome_store.ComposeOutcomeStore.claim_sealed_access`)
        burns the durable audit (``sealed_access_count >= 1``) but, if it lands before
        any terminal artifact is written, leaves the worst-case state: a consumed seal
        with NO durable terminal record. The FORWARD lifecycle (:meth:`acquire` ->
        :meth:`attempt_access` -> :meth:`confirm_durable_access`) is DESIGNED to refuse
        this state — :meth:`acquire` rejects a burned audit and holds a never-unlinked
        exclusive lock, and :meth:`aborted` is reachable only from ``ACCESS_CLAIMED``,
        itself reachable only through :meth:`acquire`.

        This classmethod is the SANCTIONED, encapsulated recovery entry: it writes
        EXCLUSIVELY one ``ABORTED_AFTER_SEAL`` terminal recording the already-consumed
        seal, opens / reopens NO seal, constructs NO outcome store, re-scores nothing,
        and creates NO exclusive lock. The seal count is auto-derived from the on-disk
        burned audit via :meth:`_sealed_access_count` (the TRUE consumed count, ``>= 1``,
        never asserted ``0``); the durable ``seal_audit_reference`` is re-derived the SAME
        way the outcome store did (``sha256_json`` over the FIRST parsed audit record), a
        verifiable proof of consumption. The whole-body ``terminal_payload_checksum`` is
        written by :meth:`_write_terminal` through the shared canonicalizer, never
        hand-computed. There is NO ``COMPLETE`` / ``INVALID`` path.

        Fails CLOSED (:class:`TerminalError`) when a terminal artifact already exists
        (the run already has a durable record — nothing to recover) or when the burned
        audit has NO records (the seal was never consumed, so this is a pre-access
        failure, not an ``ABORTED_AFTER_SEAL`` state).

        Parameters
        ----------
        run_dir : str or Path
            The run directory holding the burned audit and receiving the terminal.
        ledger : RunLedger
            The pre-access run ledger (``RunLedger.read`` of the persisted pre-access
            ledger); the terminal artifact's SHA is recorded into it AFTER the file
            verifies (an in-memory record — the on-disk pre-access ledger is untouched).
        audit_path : str or Path
            The resolved burned-audit JSONL path (``<run_dir>/audit.jsonl``); the true
            ``sealed_access_count`` and the durable ``seal_audit_reference`` are read
            from it.
        protocol : str
            The run protocol (sourced upstream from the self-checksum-verified
            seed-variability report — ``RunLedger`` carries no protocol).
        run_id : str
            The run identifier (sourced from the pre-access ledger).
        pre_access_ledger_sha256 : str
            SHA-256 of the persisted pre-access ledger file.
        pre_access_provenance_checksum : str
            The persisted pre-access provenance subset checksum
            (``pre_access_ledger.artifact_sha(PRE_ACCESS_PROVENANCE_ARTIFACT)``); the
            durable finalizer cross-checks the terminal against exactly this value.
        exception : BaseException
            The (fixed) exception recorded as the abort cause.
        stage : str
            The (fixed) stage label recorded on the abort artifact.

        Raises
        ------
        TerminalError
            If a terminal artifact already exists, or if the burned audit has no
            durable records.
        """
        terminal = cls(
            run_dir,
            ledger=ledger,
            audit_path=audit_path,
            protocol=protocol,
            run_id=run_id,
            pre_access_ledger_sha256=pre_access_ledger_sha256,
            pre_access_provenance_checksum=pre_access_provenance_checksum,
        )
        # Fail-closed recovery guard 1: a terminal already present -> nothing to recover.
        # This is a PUBLIC seal-critical entry a C driver can call directly, so mirror
        # durable.py._scan_terminals' symlink-refusing posture: a terminal-named path that
        # is a SYMLINK (broken or not) OR an existing regular file is refused. ``.exists()``
        # follows symlinks and returns False for a BROKEN symlink, so test ``is_symlink()``
        # first, else a broken symlink at a terminal name would slip past this guard.
        existing = [
            name
            for name in terminal._artifact_names()
            if (terminal._run_dir / name).is_symlink() or (terminal._run_dir / name).exists()
        ]
        if existing:
            raise TerminalError(
                f"recover_aborted_after_seal refused: terminal artifact(s) already "
                f"present {existing!r} (regular file or symlink, broken or not); the run "
                "already has a durable terminal record — nothing to recover."
            )
        # Fail-closed recovery guard 2: no burned audit records -> the seal was never
        # consumed, so this is a pre-access failure, not an ABORTED_AFTER_SEAL state.
        if terminal._audit_path is None or not terminal._audit_has_records():
            raise TerminalError(
                "recover_aborted_after_seal refused: no durable seal-audit records at "
                f"{str(terminal._audit_path)!r}; the seal was not consumed, so this is a "
                "pre-access failure, not an ABORTED_AFTER_SEAL state (fail closed)."
            )
        # Derive the durable audit reference the SAME way ComposeOutcomeStore._audit_reference
        # did — sha256_json over the FIRST parsed audit record — a verifiable proof of the
        # consumed seal (even though _finalize_aborted_terminal does not re-derive it).
        terminal._audit_reference = sha256_json(terminal._first_audit_record())
        # Sanctioned bypass: the seal is ALREADY durably burned on disk, so enter
        # ACCESS_CLAIMED directly (the forward guards would refuse this legitimate
        # post-crash state). This is ENCAPSULATED in the state machine — durable.py never
        # pokes terminal state. From ACCESS_CLAIMED, aborted() writes the sole terminal
        # (its atomic write-once install is the anti-double-write guard).
        terminal._state = TerminalState.ACCESS_CLAIMED
        terminal.aborted(exception=exception, stage=stage)

    # ------------------------------------------------------------------
    # Protection boundary — guarantees a terminal artifact on EVERY exit
    # ------------------------------------------------------------------

    def protect(self, *, stage: str = "scoring", preflight_checksums: Mapping | None = None):
        """Context manager guaranteeing a terminal artifact on every post-claim exit.

        Must be entered only after :meth:`confirm_durable_access` (state
        ``ACCESS_CLAIMED``). Wraps the protected block in ``try/except/finally``:

        * on any exception → :meth:`aborted` (recording the exception class, a
          scrubbed message and the stage) then RE-RAISE the original exception;
        * in ``finally`` → if the state is STILL ``ACCESS_CLAIMED`` (no terminal
          was written inside the block, e.g. a silent ``return``), write an
          ``ABORTED_AFTER_SEAL`` artifact with ``stage="no-terminal-written"``.

        If a terminal (``complete`` / ``invalid``) was written inside the block,
        the ``finally`` clause is a no-op — there is always exactly one terminal
        artifact. Entering before ``ACCESS_CLAIMED`` raises (the seal is not open,
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
            If entered before :meth:`confirm_durable_access`.
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
        :meth:`confirm_durable_access`.

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
            If called before :meth:`confirm_durable_access`.
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
        """Inject the common roster, guard, install, verify, then record in ledger.

        The strict order is: (1) reject raw outcomes BEFORE writing; (2) inject the
        v2 common identity roster (instance / derived state) into the body; (3)
        validate the assembled body against the exact ``common ∪ state`` roster and
        verify the filename ↔ ``terminal_state`` agreement; (4) compute and insert
        the self-excluding ``terminal_payload_checksum`` via
        :func:`canonicalize_terminal_checksum_input`; (5) install canonical JSON via
        :func:`atomic_write_once` (raises ``FileExistsError`` if the destination
        exists — write-once); (6) verify the installed file by recomputing its sha;
        (7) only then append the write-once ledger entry.

        Parameters
        ----------
        artifact_name : str
            Terminal artifact filename (also the ledger artifact name).
        body : Mapping
            The state-specific JSON body (carrying at least ``terminal_state``); the
            common identity roster is injected here, never supplied per-call.
        payload_to_guard : object
            The user-supplied portion to scan for raw outcomes.

        Raises
        ------
        TerminalError
            On a raw-outcome violation, a roster / filename-state violation, a
            non-finite / unsupported checksum value, a write-once destination
            conflict, a verification failure, or a duplicate ledger entry.
        """
        # 1. Guard BEFORE any byte is written. A rejected payload leaves the run
        #    directory and the ledger completely untouched.
        _assert_no_raw_outcomes(payload_to_guard)

        expected_state = self._artifact_state(artifact_name)

        # 2. Inject the v2 common identity roster into a LOCAL copy of the body so
        #    COMPLETE / INVALID / ABORTED share one identity contract. The five
        #    identity fields are terminal-INSTANCE state, so an ABORT with no caller
        #    payload still emits the full roster (CLAUDE.md#provenance).
        caller_state = body.get("terminal_state")
        if caller_state != expected_state.value:
            raise TerminalError(
                f"terminal artifact {artifact_name!r} maps to state "
                f"{expected_state.value!r} but the body carries terminal_state "
                f"{caller_state!r}; filename and state must agree."
            )
        assembled: dict = dict(body)
        assembled["schema"] = TERMINAL_SCHEMA_V2
        assembled["protocol"] = self._protocol
        assembled["run_id"] = self._run_id
        assembled["seal_audit_reference"] = self._audit_reference
        assembled["pre_access_ledger_sha256"] = self._pre_access_ledger_sha256
        assembled["pre_access_provenance_checksum"] = self._pre_access_provenance_checksum
        assembled["sealed_access_count"] = self._sealed_access_count()

        # 3. Validate the assembled body against the exact common ∪ state roster.
        self._validate_terminal_roster(assembled, expected_state)

        # 4. Compute + insert the self-excluding checksum via the ONE shared
        #    canonicalizer (never a raw sha256_json over the decoded body).
        checksum_input = canonicalize_terminal_checksum_input(assembled)
        assembled[TERMINAL_PAYLOAD_CHECKSUM_FIELD] = sha256_json(checksum_input)

        destination = self._run_dir / artifact_name
        text = json.dumps(assembled, sort_keys=True, separators=(",", ":"))

        # 5. Atomic, non-overwriting install (FileExistsError if it already exists).
        try:
            atomic_write_once(destination, text)
        except FileExistsError as exc:
            raise TerminalError(
                f"terminal artifact {artifact_name!r} already exists at "
                f"{str(destination)!r}; terminal artifacts are write-once and are "
                "never overwritten."
            ) from exc

        # 6. Verify the installed file before touching the ledger.
        installed_sha = sha256_file(destination)
        if installed_sha != _sha256_text(text):
            raise TerminalError(
                f"terminal artifact {artifact_name!r} failed post-install verification; "
                "the installed bytes do not match the intended content."
            )

        # 7. Only now record the write-once ledger entry (after file verified).
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

    def _artifact_state(self, artifact_name: str) -> TerminalState:
        """Return the terminal state that ``artifact_name`` must carry.

        Raises
        ------
        TerminalError
            If ``artifact_name`` is not one of the three terminal filenames.
        """
        mapping = {
            self.COMPLETE_ARTIFACT: TerminalState.COMPLETE,
            self.INVALID_ARTIFACT: TerminalState.INVALID,
            self.ABORTED_ARTIFACT: TerminalState.ABORTED_AFTER_SEAL,
        }
        try:
            return mapping[artifact_name]
        except KeyError as exc:  # pragma: no cover - guards a wiring mistake
            raise TerminalError(f"{artifact_name!r} is not a terminal artifact filename.") from exc

    def _validate_terminal_roster(self, body: Mapping, state: TerminalState) -> None:
        """Validate an assembled body against the exact ``common ∪ state`` roster.

        Every common identity field must be present (a missing one means the
        injection failed). Additionally, every field in
        :data:`_REQUIRED_NONEMPTY_IDENTITY_FIELDS` must carry a NON-EMPTY value —
        presence alone is not enough: a ``None`` or blank run-identity anchor fails
        CLOSED (the seal artifact is un-attributable and must never be written,
        CLAUDE.md#provenance). Every terminal state now has a FIXED state roster
        (``COMPLETE`` / ``INVALID`` share :data:`_COMPLETE_INVALID_STATE_FIELDS`;
        ``ABORTED_AFTER_SEAL`` its own), so the body must carry exactly
        ``common ∪ state`` — an unknown OR missing state field raises. The
        self-excluding ``terminal_payload_checksum`` is inserted AFTER this check and
        is not part of the validated roster.

        Raises
        ------
        TerminalError
            On a missing common field, a null/empty required-identity value, or
            (fixed-roster states) an unknown or missing state field.
        """
        present = set(body.keys())
        missing_common = _COMMON_TERMINAL_FIELDS - present
        if missing_common:
            raise TerminalError(
                f"terminal body for state {state.value!r} is missing required common "
                f"field(s) {sorted(missing_common)!r}."
            )
        # Fail CLOSED on a null/empty run-identity anchor: presence is not enough —
        # a ``None`` or blank protocol / run id / seal reference / pre-access
        # provenance identity means the seal artifact is un-attributable and MUST
        # NOT be recorded (CLAUDE.md#provenance). This is the canary that stops a future
        # refactor dropping / reordering ``bind_pre_access`` from silently emitting
        # a null-identity seal artifact.
        for field in _REQUIRED_NONEMPTY_IDENTITY_FIELDS:
            value = body.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise TerminalError(
                    f"terminal body for state {state.value!r} carries an empty identity "
                    f"field {field!r} (value {value!r}); the seal cannot be recorded with "
                    "an empty identity — the run would be un-attributable."
                )
        state_keys = _STATE_TERMINAL_FIELDS[state]
        if state_keys is None:
            return
        allowed = _COMMON_TERMINAL_FIELDS | state_keys | {TERMINAL_PAYLOAD_CHECKSUM_FIELD}
        unknown = present - allowed
        if unknown:
            raise TerminalError(
                f"terminal body for state {state.value!r} carries unknown field(s) "
                f"{sorted(unknown)!r}; allowed fields are {sorted(allowed)!r}."
            )
        missing_state = state_keys - present
        if missing_state:
            raise TerminalError(
                f"terminal body for state {state.value!r} is missing state field(s) "
                f"{sorted(missing_state)!r}."
            )

    def _sealed_access_count(self) -> int:
        """Count the durable seal-audit records at this terminal's own audit path.

        Returns 0 when no audit path was supplied or the file is absent / empty. A
        blank line is ignored; every non-blank line is one durable record (mirrors
        :meth:`_audit_has_records`). This is the terminal's OWN derived count — it
        never reaches into the outcome store's counter.
        """
        if self._audit_path is None or not self._audit_path.exists():
            return 0
        return sum(
            1 for line in self._audit_path.read_text(encoding="utf-8").splitlines() if line.strip()
        )

    def _require_state(self, expected: TerminalState, action: str) -> None:
        if self._state is not expected:
            current = self._state.value if self._state is not None else None
            raise TerminalError(
                f"{action}() is only valid from {expected.value!r}; current state is {current!r}."
            )

    def _first_audit_record(self) -> dict:
        """Return the FIRST durable audit record parsed from ``self._audit_path``.

        Reads the first non-blank JSONL line and parses it as JSON — the record the
        :class:`~alive.compose.outcome_store.ComposeOutcomeStore` wrote at
        ``claim_sealed_access``. Its ``sha256_json`` reproduces the store's
        ``_audit_reference`` byte-for-byte (both hash the record under sorted keys).
        Fails closed if the audit path is unset / absent / empty, or the first record
        is not valid JSON.

        Raises
        ------
        TerminalError
            If there is no readable durable audit record to reference.
        """
        if self._audit_path is None or not self._audit_path.exists():
            raise TerminalError(
                "recover_aborted_after_seal: no durable seal audit to read a reference from."
            )
        for line in self._audit_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError as exc:
                raise TerminalError(
                    f"first durable audit record at {str(self._audit_path)!r} is not valid "
                    f"JSON: {exc} (fail closed)."
                ) from exc
        raise TerminalError(
            f"durable seal audit {str(self._audit_path)!r} has no records to reference."
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
                f"{current!r} (reach ACCESS_CLAIMED via confirm_durable_access first)."
            )
        return self._owner

    #: Prefix for the best-effort last-resort finalization-failure marker. Used
    #: only when :meth:`Phase2bTerminal.aborted` itself fails on exit.
    _LAST_RESORT_PREFIX = "terminal_abort_failure"

    def __exit__(self, exc_type, exc, exc_tb) -> bool:
        if exc is not None:
            # An exception escaped the block: record the abort then RE-RAISE the
            # ORIGINAL exception. If the block already wrote a terminal (state no
            # longer ACCESS_CLAIMED) there is nothing to record.
            if self._owner.state is TerminalState.ACCESS_CLAIMED:
                try:
                    self._owner.aborted(
                        exception=exc,
                        stage=self._stage,
                        preflight_checksums=self._preflight_checksums,
                    )
                except BaseException as abort_err:
                    # Finalization itself failed (e.g. a terminal already exists, or
                    # the ledger already records the abort name). Drop a best-effort
                    # durable marker so the run never ends silently with no terminal
                    # record, then let the ORIGINAL exception propagate — abort_err
                    # must never mask the real failure.
                    self._write_last_resort_marker(exc, abort_err)
            return False  # propagate (re-raise) the original exception

        # Clean exit. If no terminal was written inside the block, the seal would
        # be consumed with no terminal record — write the safety-net abort.
        if self._owner.state is TerminalState.ACCESS_CLAIMED:
            try:
                self._owner.aborted(
                    exception=NoTerminalWritten(
                        "protected block exited without writing a terminal artifact"
                    ),
                    stage="no-terminal-written",
                    preflight_checksums=self._preflight_checksums,
                )
            except BaseException as abort_err:
                # No in-flight exception to preserve here, so the run genuinely
                # failed to finalize. Drop a best-effort marker, then surface the
                # finalization failure as a TerminalError chained from abort_err.
                self._write_last_resort_marker(None, abort_err)
                raise TerminalError(
                    "protected block exited cleanly with the seal still consumed but "
                    "the safety-net abort write failed; the run did not finalize."
                ) from abort_err
        return False

    def _write_last_resort_marker(
        self,
        original: BaseException | None,
        abort_err: BaseException,
    ) -> None:
        """Best-effort durable marker that finalization itself failed.

        Writes a uniquely-named ``terminal_abort_failure-<n>.json`` via
        :func:`atomic_write_once` so a consumed seal never ends with zero durable
        terminal markers, even when :meth:`Phase2bTerminal.aborted` could not
        install its own artifact. Records only outcome-free metadata (exception
        CLASS NAMES and scrubbed messages — never raw outcomes or checksums). Any
        error from this last-resort attempt is swallowed: it must never raise.

        Parameters
        ----------
        original : BaseException or None
            The in-flight exception being preserved (``None`` on the clean path).
        abort_err : BaseException
            The exception raised by the failed :meth:`Phase2bTerminal.aborted` call.
        """
        body = {
            "terminal_state": TerminalState.ABORTED_AFTER_SEAL.value,
            "finalization_failed": True,
            "stage": self._stage,
            "original_exception_class": (type(original).__name__ if original is not None else None),
            "original_message": (
                scrub_exception_message(str(original)) if original is not None else None
            ),
            "abort_failure_class": type(abort_err).__name__,
            "abort_failure_message": scrub_exception_message(str(abort_err)),
        }
        text = json.dumps(body, sort_keys=True, separators=(",", ":"))
        run_dir = self._owner.run_dir
        for n in range(1000):
            destination = run_dir / f"{self._LAST_RESORT_PREFIX}-{n}.json"
            try:
                atomic_write_once(destination, text)
                return
            except FileExistsError:
                continue
            except BaseException:
                # Disk full, permissions, etc. Nothing more we can durably do.
                return
