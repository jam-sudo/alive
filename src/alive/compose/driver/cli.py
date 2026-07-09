"""``main(argv)`` — the single committed COMPOSE production-driver CLI (Task 11).

``scripts/run_compose_k562_phase2.py`` is a THIN shim (``import`` + ``sys.exit(
main())``); all argparse wiring, dispatch and exit-code mapping lives here per
CLAUDE.md §7 (production logic in ``src/``, scripts stay thin). This module
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

Run-spec carrier reconstruction (a resolved brief ambiguity — see the Task 11
report). The four subcommands' ``run_spec`` parameter is documented as "the
stage-1 DATA carrier" (locally the committed fixture builder's
:class:`~alive.compose.driver.fixture_builder.FixtureBundle`) — an object
exposing ``spec_path`` PLUS live in-memory stage-1 objects
(``phase2a_inputs``/``dev_store_audit``/``response_artifact``/
``sealed_outcome``/...). A bare :class:`~alive.compose.driver.run_spec.ResolvedRunSpec`
(the object :func:`~alive.compose.driver.run_spec.load_resolved_run_spec`
returns) carries none of those — passing it directly raises ``AttributeError``
in every subcommand. There is no committed loader that reconstructs a full
carrier purely from an on-disk ``ResolvedRunSpec`` either (deserialising a live
``Phase2aInputs``/``ResponseSpace``/sealed-outcome ``pair_index`` back out of
JSON is a separate PREPARE sub-project obligation, spec §0 "Out of scope"). For
``mode == "fixture"`` — the only mode this CLI can currently service — this CLI
therefore performs THREE steps for ``phase2a``/``preflight``/``phase2b``:

1. construct the carrier: :func:`~alive.compose.driver.fixture_builder.build_compose_fixture`
   is the ONLY committed carrier-construction path today, attempted
   unconditionally against ``--approved-artifacts-root``. It is deterministic
   (fixed seeds throughout) but writes a WRITE-ONCE fit-role artifact, so it
   can be called at most once per ``--approved-artifacts-root`` — a second
   call (e.g. a stale re-run over an already-populated root) fails closed by
   propagating the library's own write-once error (an unrecognised/unexpected
   error, not one of :data:`_KNOWN_PRESEAL_REJECTIONS`);
2. peek ``mode`` from the CALLER-DECLARED ``--run-spec`` path (mirrors each
   subcommand's own private ``_peek_mode`` helper) — a missing/unreadable file
   or an unrecognised mode fails closed here as
   :class:`~alive.compose.driver.run_spec.RunSpecError`. Scientific mode has
   no carrier-construction path yet and fails closed here as
   :class:`UnsupportedModeError` (a
   :class:`~alive.compose.driver.run_spec.RunSpecError` subclass, so it is
   caught by the same pre-seal-rejection mapping) rather than silently
   dispatching against the (wrong-mode) fixture carrier step 1 just built;
3. an explicit, CLI-owned pre-seal validation gate over that SAME
   ``--run-spec`` path: ``load_resolved_run_spec`` (canonical bytes / schema /
   self-checksum / file SHA / path policy / every declared pre-seal byte-SHA /
   recomputed ``run_id``) — this is independent of what step 1 just built, so
   a caller pointing ``--run-spec`` at a mismatched, stale, or tampered file
   fails closed here even though a (different) carrier was already
   constructed at ``--approved-artifacts-root``. ANY violation raises
   :class:`~alive.compose.driver.run_spec.RunSpecError` before any subcommand
   is invoked.

A production PREPARE-backed CLI would instead LOAD a pre-built carrier from
disk without ever re-deriving it; today's fixture-only build-then-validate
order is the pragmatic, testable shape given the write-once and no-loader
constraints above — flagged explicitly here (and in the Task 11 report) rather
than silently glossed over.

KNOWN LIMITATION (flagged, not silently worked around): because step 1 above
re-invokes ``build_compose_fixture`` on every ``main()`` call, THIS CLI can
service AT MOST ONE subcommand call per fresh ``--approved-artifacts-root``.
The canonical ``phase2a -> preflight -> phase2b`` sequence — three independent
process invocations sharing ONE ``ResolvedRunSpec``/``run_dir`` (spec §1.1's
own CLI usage example) — currently fails on the SECOND call with an
uncaught ``FitRoleArtifactError`` propagating out of ``build_compose_fixture``
(the write-once fit-role artifact already exists from the first call). This is
NOT one of :data:`_KNOWN_PRESEAL_REJECTIONS` and is deliberately left
uncaught/unmapped rather than silently swallowed into a misleading exit code.
Closing this gap needs either a genuine carrier LOADER (reconstructing
``Phase2aInputs``/``ResponseSpace``/sealed-outcome data from the ALREADY-
WRITTEN pre-seal files without rebuilding them — the real "PREPARE" shape) or
an idempotent ``build_compose_fixture`` (skip-if-already-built) — both are
out of Task 11's scope (four files only; ``fixture_builder.py`` is off
limits). Task 11's own four tested scenarios only exercise a single
``phase2a`` call, so this gap does not block them.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §1.1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from alive.compose.driver.confirmation import ConfirmationError
from alive.compose.driver.fixture_builder import FixtureBundle, build_compose_fixture
from alive.compose.driver.identity_lock import AssemblerError
from alive.compose.driver.phase2a_cmd import Phase2aSubcommandError, run_phase2a_subcommand
from alive.compose.driver.phase2b_cmd import Phase2bSubcommandError, run_phase2b_subcommand
from alive.compose.driver.preflight_cmd import (
    PreflightSubcommandError,
    run_preflight_subcommand,
)
from alive.compose.driver.recover_cmd import RecoverSubcommandError, run_recover_subcommand
from alive.compose.driver.run_dir_state import RunDirStateError
from alive.compose.driver.run_spec import RunSpecError, load_resolved_run_spec
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

_MODES = frozenset({"fixture", "scientific"})


class UnsupportedModeError(RunSpecError):
    """Raised when this CLI build cannot yet construct a run_spec carrier.

    Subclasses :class:`~alive.compose.driver.run_spec.RunSpecError` so it is
    caught by the SAME known-pre-seal-rejection mapping (exit ``10``) without a
    separate ``except`` clause. Scientific-mode carrier assembly (raw Norman ->
    ``Phase2aInputs``/factor bank/response artifact/pair manifest/... ) is a
    separate PREPARE sub-project obligation (spec §0 "Out of scope"); a
    scientific ResolvedRunSpec fails closed here rather than being silently
    dispatched against a carrier this CLI has no way to build.
    """


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


def _peek_mode(spec_path: Path) -> str:
    """Read the declared ``mode`` before the full load (mirrors each subcommand's
    own ``_peek_mode`` helper; the loader re-validates it)."""
    try:
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunSpecError(f"cannot read ResolvedRunSpec {spec_path}: {exc}") from exc
    mode = raw.get("mode") if isinstance(raw, dict) else None
    if mode not in _MODES:
        raise RunSpecError(f"ResolvedRunSpec declares an unrecognised mode {mode!r}")
    return mode


def _build_run_spec_carrier(spec_path: Path, approved_artifacts_root: Path) -> FixtureBundle:
    """Peek mode, construct the stage-1 carrier, then validate ``--run-spec``.

    See the module docstring "Run-spec carrier reconstruction" section for why
    this build-then-validate order (rather than validate-then-build) is
    necessary given ``build_compose_fixture``'s write-once fit-role artifact
    and the absence of a from-disk carrier loader.

    Raises
    ------
    RunSpecError
        If ``mode`` cannot be peeked/is unrecognised, if ``mode ==
        "scientific"`` (:class:`UnsupportedModeError`), or if the FINAL
        ``load_resolved_run_spec`` validation of the caller-declared
        ``--run-spec`` path rejects it.
    """
    # Fixture is the only carrier-construction path currently committed (see
    # module docstring); attempt it unconditionally so a genuinely missing
    # ``--run-spec`` file (never written by any builder) is distinguishable
    # from a merely-mismatched one, both caught by the validation gate below.
    carrier = build_compose_fixture(approved_artifacts_root)
    mode = _peek_mode(spec_path)
    if mode != "fixture":
        raise UnsupportedModeError(
            "this CLI build can only construct a run_spec carrier for "
            f"mode='fixture' (scientific carrier assembly is a separate PREPARE "
            f"obligation, spec §0); got mode={mode!r}"
        )
    # CLI-owned pre-seal validation gate over the CALLER-DECLARED path (not
    # necessarily ``carrier.spec_path`` — see module docstring): fails closed
    # BEFORE any subcommand is invoked. The subcommand re-validates
    # independently too (defense in depth); this return value is discarded.
    load_resolved_run_spec(
        spec_path, approved_artifacts_root=approved_artifacts_root, mode_expected=mode
    )
    return carrier


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
