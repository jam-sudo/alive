"""``main(argv)`` — the single committed COMPOSE production-driver CLI (Task 11).

``scripts/run_compose_k562_phase2.py`` is a THIN shim (``import`` + ``sys.exit(
main())``); all argparse wiring, dispatch and exit-code mapping lives here per
CLAUDE.md#data-eval (production logic in ``src/``, scripts stay thin). This module
opens **no** seal and constructs **no**
:class:`~alive.compose.outcome_store.ComposeOutcomeStore` — dispatch to the four
already-committed subcommand entry points (Tasks 7-10:
:func:`~alive.compose.driver.phase2a_cmd.run_phase2a_subcommand`,
:func:`~alive.compose.driver.preflight_cmd.run_preflight_subcommand`,
:func:`~alive.compose.driver.phase2b_cmd.run_phase2b_subcommand`,
:func:`~alive.compose.driver.recover_cmd.run_recover_subcommand`) is this
module's entire job.

Four subcommands (spec §1.1)::

    phase2a    --run-spec PATH --approved-artifacts-root PATH --run-dir PATH
    preflight  --run-spec PATH --approved-artifacts-root PATH --run-dir PATH
    phase2b    --run-spec PATH --approved-artifacts-root PATH --run-dir PATH \\
               --confirm-seal TOKEN
    recover    --run-dir PATH

Exit-code contract (spec §1.1): ``0`` = the requested stage succeeded; ``10`` =
a pre-seal validation rejection (no seal consumed); ``20`` = ``phase2a``
FUTILITY_STOPPED (a valid stop; ``phase2b`` forbidden); ``30`` = a post-seal
non-``COMPLETE`` terminal or an incomplete durable export. Every non-``phase2a``
subcommand's own return value is ALREADY one of these exact codes (``preflight``
returns 0/10 itself, ``phase2b``/``recover`` return 0/30 themselves) — ``main``
passes that integer straight through. ``main`` only ADDS the ``10`` mapping for
the driver's own KNOWN pre-seal rejection exception types (see
:data:`_KNOWN_PRESEAL_REJECTIONS`); an unrecognised exception is a genuine bug
and is left to propagate with its full traceback (never silently swallowed).
Unknown subcommand / missing required flag is argparse's own exit ``2``.

Output discipline (spec §1.1 / CLAUDE.md operational-diagnostics convention,
matching Task 10's ``recover`` fail-closed print): on a caught pre-seal
rejection, exactly one line — ``f"{stage}: {type(exc).__name__}: {exc}"`` — is
written to STDERR. Nothing is ever written to STDOUT: no aggregate, no verdict,
no per-pair value, no outcome of any kind.

Run-spec carrier reconstruction (Task 11.5). The four subcommands' ``run_spec``
parameter is "the stage-1 DATA carrier": an object exposing ``spec_path`` PLUS the
live stage-1 objects (``phase2a_inputs``/``dev_store_audit``/``response_artifact``/
``sealed_outcome``) — NOT a bare
:class:`~alive.compose.driver.run_spec.ResolvedRunSpec` (which carries none of
those; passing it directly raises ``AttributeError`` in every subcommand). This CLI
therefore LOADS the carrier from disk via
:func:`~alive.compose.driver.carrier_loader.load_run_spec_carrier`, which:

1. peeks the CALLER-DECLARED ``--run-spec`` mode BEFORE any work — a missing /
   unreadable file or an unrecognised mode fails closed as
   :class:`~alive.compose.driver.run_spec.RunSpecError`; a scientific mode fails
   closed as :class:`UnsupportedModeError` (a ``RunSpecError`` subclass, caught by
   the same pre-seal-rejection mapping), since scientific carrier assembly is a
   separate PREPARE obligation (spec §0 "Out of scope");
2. loads + fully validates the immutable ResolvedRunSpec (canonical bytes / schema /
   self-checksum / file SHA / path policy / every declared pre-seal byte-SHA /
   recomputed ``run_id``), so a mismatched, stale, or tampered ``--run-spec`` fails
   closed before any subcommand runs;
3. reconstructs the carrier from the ALREADY-serialized, SHA-verified on-disk
   stage-1 artifacts — writing NO new bytes, deriving nothing.

Because the loader is a pure reader (no write-once producer), this CLI can service
each of ``phase2a`` / ``preflight`` / ``phase2b`` as an INDEPENDENT process against
the SAME ``--approved-artifacts-root`` / ``--run-spec`` / ``--run-dir`` — the spec
§1.1/§11 three-independent-process ``phase2a → preflight → phase2b`` e2e (previously
impossible while the CLI rebuilt a write-once fixture per call). The corpus itself is
produced once up-front (by the test harness / e2e driver / PREPARE), never per CLI
process.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §1.1/§11.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from alive.compose.driver.carrier_loader import (
    RunSpecCarrier,
    UnsupportedModeError,
    load_run_spec_carrier,
)
from alive.compose.driver.confirmation import ConfirmationError
from alive.compose.driver.identity_lock import AssemblerError
from alive.compose.driver.phase2a_cmd import Phase2aSubcommandError, run_phase2a_subcommand
from alive.compose.driver.phase2b_cmd import Phase2bSubcommandError, run_phase2b_subcommand
from alive.compose.driver.preflight_cmd import (
    PreflightSubcommandError,
    run_preflight_subcommand,
)
from alive.compose.driver.recover_cmd import RecoverSubcommandError, run_recover_subcommand
from alive.compose.driver.run_dir_state import RunDirStateError
from alive.compose.driver.run_spec import RunSpecError
from alive.compose.outcome_store import ComposeSealingError
from alive.compose.preflight import PreflightError
from alive.provenance import LedgerError

__all__ = [
    "SUCCESS_EXIT",
    "PRESEAL_REJECT_EXIT",
    "FUTILITY_EXIT",
    "POSTSEAL_NONCOMPLETE_EXIT",
    "UnsupportedModeError",
    "main",
]

#: Exit-code contract (spec §1.1). ``FUTILITY_EXIT`` / ``POSTSEAL_NONCOMPLETE_EXIT``
#: are documented here for readers of this module; ``main`` never constructs
#: them itself — they are the subcommands' OWN return values, passed through.
SUCCESS_EXIT = 0
PRESEAL_REJECT_EXIT = 10
FUTILITY_EXIT = 20
POSTSEAL_NONCOMPLETE_EXIT = 30

#: The driver's KNOWN pre-seal rejection exception types (spec §1.1 exit code
#: ``10``). Each is a documented, fail-closed validation/rejection type raised
#: by the CLI's own carrier-construction gate or by one of the four
#: subcommands (or a library call one of them makes) BEFORE any seal access —
#: never a bare/unexpected error. ``Phase2bSubcommandError`` is a KNOWN
#: exception (deliberately listed per the task brief's own enumeration) but is
#: not exclusively pre-seal: its docstring also covers a durable-commit-marker
#: re-read failure at ``phase2b`` step 6, which runs AFTER the seal is opened.
#: This CLI maps every ``Phase2bSubcommandError`` to ``10`` uniformly (the
#: driver has no subclass distinguishing the pre-/post-seal cases, and Task 11
#: may not modify ``phase2b_cmd.py``); a step-6 marker-corruption case is
#: therefore reported as ``10`` even though the seal WAS in fact consumed — a
#: known imprecision flagged in the Task 11 report, not silently resolved.
_KNOWN_PRESEAL_REJECTIONS: tuple[type[Exception], ...] = (
    RunSpecError,  # covers UnsupportedModeError (subclass)
    RunDirStateError,
    Phase2aSubcommandError,
    PreflightSubcommandError,
    ConfirmationError,
    ComposeSealingError,
    Phase2bSubcommandError,
    RecoverSubcommandError,
    PreflightError,
    LedgerError,
    # AssemblerError (a ``ValueError`` subclass, so NOT covered by any entry
    # above) is the §7.1 execution-lock-mismatch abort — a worker-digest /
    # execution-identity-lock divergence surfaced BEFORE any seal access by
    # phase2a's ``assemble_baseline_backends`` (via ``_assemble_adapters``) or
    # preflight's ``assemble_execution_identity_lock`` (via ``_worker_identity``).
    # Spec §1.1 assigns it exit 10; without this entry it propagated uncaught
    # (traceback + exit 1) instead of the contracted single-stderr-line + 10.
    AssemblerError,
)


# --------------------------------------------------------------------------- #
# argparse wiring
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_compose_k562_phase2.py",
        description=(
            "COMPOSE-K562-v1 production driver: phase2a / preflight / phase2b / "
            "recover (spec docs/superpowers/specs/2026-07-07-compose-production-"
            "driver-design.md §1.1)."
        ),
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    def _add_run_spec_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--run-spec", required=True, type=Path)
        sp.add_argument("--approved-artifacts-root", required=True, type=Path)
        sp.add_argument("--run-dir", required=True, type=Path)

    phase2a = subparsers.add_parser("phase2a")
    _add_run_spec_flags(phase2a)

    preflight = subparsers.add_parser("preflight")
    _add_run_spec_flags(preflight)

    phase2b = subparsers.add_parser("phase2b")
    _add_run_spec_flags(phase2b)
    phase2b.add_argument("--confirm-seal", required=True)

    recover = subparsers.add_parser("recover")
    recover.add_argument("--run-dir", required=True, type=Path)

    return parser


# --------------------------------------------------------------------------- #
# Run-spec carrier construction (see the module docstring)
# --------------------------------------------------------------------------- #


def _build_run_spec_carrier(spec_path: Path, approved_artifacts_root: Path) -> RunSpecCarrier:
    """LOAD the stage-1 carrier from the ResolvedRunSpec's on-disk artifacts.

    Delegates to :func:`~alive.compose.driver.carrier_loader.load_run_spec_carrier`,
    which peeks the declared ``mode`` BEFORE any work (fixture is the only committed
    carrier path; a scientific spec fails closed with
    :class:`~alive.compose.driver.carrier_loader.UnsupportedModeError`), then loads +
    fully validates the ResolvedRunSpec (canonical bytes / schema / self-checksum /
    file SHA / path policy / every declared pre-seal byte-SHA / recomputed
    ``run_id``) and reconstructs the carrier from the already-serialized stage-1
    artifacts. It writes NO bytes, so this CLI can now service each of the
    ``phase2a → preflight → phase2b`` stages as an INDEPENDENT process against the
    same approved-root (spec §11).

    Raises
    ------
    RunSpecError
        If ``mode`` cannot be peeked / is unrecognised, if ``mode == "scientific"``
        (:class:`UnsupportedModeError`), or if the ResolvedRunSpec fails validation.
    """
    return load_run_spec_carrier(spec_path, approved_artifacts_root=approved_artifacts_root)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv``, dispatch to the resolved subcommand, and return its exit code.

    Parameters
    ----------
    argv : Sequence[str] or None
        Command-line arguments (excluding the program name); ``None`` uses
        ``sys.argv[1:]`` (argparse's own default).

    Returns
    -------
    int
        ``0`` on success; ``10`` on a pre-seal validation rejection; ``20`` on
        ``phase2a`` FUTILITY_STOPPED; ``30`` on a post-seal non-``COMPLETE``
        terminal or incomplete durable export.

    Raises
    ------
    SystemExit
        On an unknown subcommand or a missing required flag (argparse's own
        behaviour; exit code ``2``).
    Exception
        Any exception NOT in :data:`_KNOWN_PRESEAL_REJECTIONS` propagates with
        its full traceback — an unexpected/unknown error is a genuine bug and
        is never silently mapped to an exit code.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "recover":
        try:
            return run_recover_subcommand(run_dir=args.run_dir)
        except _KNOWN_PRESEAL_REJECTIONS as exc:
            _report_preseal_rejection("recover", exc)
            return PRESEAL_REJECT_EXIT

    try:
        carrier = _build_run_spec_carrier(args.run_spec, args.approved_artifacts_root)
        if args.subcommand == "phase2a":
            return run_phase2a_subcommand(
                carrier, approved_artifacts_root=args.approved_artifacts_root, run_dir=args.run_dir
            )
        if args.subcommand == "preflight":
            return run_preflight_subcommand(
                carrier, approved_artifacts_root=args.approved_artifacts_root, run_dir=args.run_dir
            )
        # phase2b
        return run_phase2b_subcommand(
            carrier,
            approved_artifacts_root=args.approved_artifacts_root,
            run_dir=args.run_dir,
            confirm_seal_token=args.confirm_seal,
        )
    except _KNOWN_PRESEAL_REJECTIONS as exc:
        _report_preseal_rejection(args.subcommand, exc)
        return PRESEAL_REJECT_EXIT


def _report_preseal_rejection(stage: str, exc: Exception) -> None:
    """Write the T10-convention diagnostic line to STDERR only (never STDOUT)."""
    print(f"{stage}: {type(exc).__name__}: {exc}", file=sys.stderr)
