"""End-to-end: where the sealed-source integrity re-check fires, and what it decides.

PR #15 finding C1 (Codex Critical 1 = fable Important 1, 2026-09-08), reproduced
independently by both reviews: the post-consumption re-hash used to run at
``verified_descriptor``'s context exit, and the driver wraps the WHOLE library call
in that context. So it ran after ``run_phase2b[_fixture]`` had already published a
``COMPLETE`` terminal and its durable commit marker; the exception was raised by the
``with`` statement's own exit, which is OUTSIDE the ``try/except`` that maps a
post-seal failure to exit 30; the CLI mapped it to the PRE-seal exit 10 ("no seal
consumed") while a COMPLETE terminal sat on disk; and ``recover`` read that terminal
and returned 0. A detected integrity failure left a recoverable COMPLETE run.

The fix moves the call, not the check: consumption ends inside
``ComposeOutcomeStore.materialize_claimed`` (every claimed row is densified into
numpy there; from that point the library only computes in memory), so the store
calls the driver's ``post_materialization_check`` at exactly that point. That is
inside ``Phase2bTerminal.protect``, so the refusal writes ``ABORTED_AFTER_SEAL``,
step 5's handler returns 30, and ``recover`` agrees.

What happens AFTER consumption is deliberately NOT the same event: the run consumed
the bytes it verified, the terminal records that, and raising there would recreate
the very COMPLETE-terminal / exit-code contradiction C1 measured. It is reported as
one stderr diagnostic and the terminal is left alone --- pinned below, so it is a
declared behaviour and not a silent swallow.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path

import pytest

import alive.compose.driver.phase2b_cmd as phase2b_mod
import alive.compose.driver.preseal_read as preseal_mod
from alive.compose.driver.phase2b_cmd import (
    PHASE2B_COMPLETE_EXIT,
    PHASE2B_NONCOMPLETE_EXIT,
    run_phase2b_subcommand,
)
from alive.compose.driver.preseal_read import (
    PresealDescriptorError,
    verified_descriptor_handle,
)
from alive.compose.driver.recover_cmd import (
    RECOVER_COMPLETE_EXIT,
    RECOVER_NONCOMPLETE_EXIT,
    run_recover_subcommand,
)
from alive.compose.durable import DURABLE_COMMIT_FILENAME, SEAL_AUDIT_FILENAME
from alive.compose.terminal import Phase2bTerminal
from tests.alive.compose.driver.test_phase2b_cmd import _confirmation_token, _run_preseal

_PROBE = b"PR15 integrity probe"


def _audit_lines(run_dir: Path) -> list[str]:
    return (run_dir / SEAL_AUDIT_FILENAME).read_text(encoding="utf-8").splitlines()


def _terminal_states(run_dir: Path) -> list[str]:
    states = []
    for artifact in (
        Phase2bTerminal.COMPLETE_ARTIFACT,
        Phase2bTerminal.INVALID_ARTIFACT,
        Phase2bTerminal.ABORTED_ARTIFACT,
    ):
        path = run_dir / artifact
        if path.exists():
            states.append(json.loads(path.read_bytes())["terminal_state"])
    return states


# --------------------------------------------------------------------------- #
# (a) mutation DURING consumption → ABORTED_AFTER_SEAL, exit 30, recover 30
# --------------------------------------------------------------------------- #
def test_in_place_mutation_during_materialization_aborts_and_recover_agrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The whole chain, on the real fixture: detected → durable → recover agrees.

    The mutation is injected at a point that is provably AFTER the durable claim
    and BEFORE the re-check: ``anndata.read_h5ad`` is only called by the store's
    post-claim ``materialization_validator``, which ``materialize_claimed`` runs
    after verifying the persisted audit and before slicing the first row. Bytes are
    appended to the SAME inode (never restored), which is the mutation class the
    re-check exists for.
    """
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)
    source = Path(fx.sealed_outcome["source_path"])
    inode_before = source.stat().st_ino

    real_read_h5ad = phase2b_mod.anndata.read_h5ad

    def read_then_mutate(*args, **kwargs):
        opened = real_read_h5ad(*args, **kwargs)
        with source.open("ab") as handle:
            handle.write(_PROBE)
            handle.flush()
            os.fsync(handle.fileno())
        return opened

    monkeypatch.setattr(phase2b_mod.anndata, "read_h5ad", read_then_mutate)

    rc = run_phase2b_subcommand(
        fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
    )

    assert rc == PHASE2B_NONCOMPLETE_EXIT, "a refused sealed source must not exit 0 or raise"
    assert source.stat().st_ino == inode_before, "the reproduction requires the same inode"
    err = capsys.readouterr().err
    assert "modified IN PLACE" in err
    assert "sealed source integrity check failed after materialization" in err
    # The seal was consumed exactly once and the durable witness is the terminal.
    assert len(_audit_lines(fx.run_dir)) == 1
    assert _terminal_states(fx.run_dir) == ["ABORTED_AFTER_SEAL"]
    assert not (fx.run_dir / Phase2bTerminal.COMPLETE_ARTIFACT).exists()
    assert (fx.run_dir / DURABLE_COMMIT_FILENAME).is_file()
    # recover reads that terminal and refuses to call the run complete.
    assert run_recover_subcommand(run_dir=fx.run_dir) == RECOVER_NONCOMPLETE_EXIT


# --------------------------------------------------------------------------- #
# (b) control: no mutation → 0 / COMPLETE / recover 0
#
# Covered by the committed end-to-end pair rather than re-run here:
#   tests/alive/compose/driver/test_phase2b_cmd.py
#     ::test_full_fixture_path_completes_with_run_bound_audit   (0 + COMPLETE)
#   tests/alive/compose/driver/test_recover_cmd.py
#     ::test_recover_verify_only_is_byte_identical_and_returns_zero  (recover 0)
# Both run the same `_run_preseal` fixture through the same subcommands with the
# post-materialization check installed, so they are the control arm for (a) and (c).
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# (c) mutation AFTER consumption → COMPLETE stands, diagnostic printed
# --------------------------------------------------------------------------- #
def test_mutation_after_consumption_leaves_the_complete_terminal_and_prints_a_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Codex's original reproduction, with the ruling's outcome.

    The library has returned: every sealed byte this run will ever read was read
    and re-verified inside ``materialize_claimed``, and the terminal records that
    consumption. The file's state afterwards is not what the "the bytes we verified
    are the bytes we consumed" contract is about, and D3-a's runtime premises (no
    concurrent writer, immutable mount) are what cover a writer at all. Raising here
    would put the exit code back in contradiction with a durable COMPLETE terminal
    --- the exact defect C1 named --- so the divergence is reported on stderr and
    the terminal stands. The diagnostic is asserted here so this is a declared
    behaviour with a witness, not a silent swallow.
    """
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)
    source = Path(fx.sealed_outcome["source_path"])

    real_dispatch = phase2b_mod.run_phase2b_fixture

    def dispatch_then_mutate(*args, **kwargs):
        result = real_dispatch(*args, **kwargs)
        with source.open("ab") as handle:
            handle.write(_PROBE)
            handle.flush()
            os.fsync(handle.fileno())
        return result

    monkeypatch.setattr(phase2b_mod, "run_phase2b_fixture", dispatch_then_mutate)

    rc = run_phase2b_subcommand(
        fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
    )

    assert rc == PHASE2B_COMPLETE_EXIT
    assert _terminal_states(fx.run_dir) == ["COMPLETE"]
    assert run_recover_subcommand(run_dir=fx.run_dir) == RECOVER_COMPLETE_EXIT
    err = capsys.readouterr().err
    assert "changed AFTER consumption" in err
    assert "terminal state unaffected" in err
    assert fx.sealed_outcome["source_file_sha256"] in err


# --------------------------------------------------------------------------- #
# (c2) the diagnostic re-hash cannot RUN → still COMPLETE; the same failure
#      inside the consumption boundary → ABORTED_AFTER_SEAL
#
# PR #15 re-review R1 (Codex, 2026-09-08), reproduced: the ruling in (c) is
# "post-consumption divergence is a stderr diagnostic, never an exception", but
# the branch caught only `Phase2bSubcommandError`. `recheck()` re-streams the
# digest with `os.lseek`/`os.read`, so a storage-level `OSError` escaped the
# `with store_context` exit, skipped step 5's post-seal handler, and left
# `RESULT OSError / TERMINAL COMPLETE / RECOVER 0 / STDERR ''` --- the same
# contradiction C1 named, arriving by an I/O error instead of a digest mismatch.
#
# The two arms below are the SAME injected failure at the two positions, and they
# must decide differently: failing to prove integrity while consumption is still
# open fails CLOSED (30); failing to run a diagnostic after consumption ended
# cannot contradict a terminal that is already durable (0 + one stderr line).
# --------------------------------------------------------------------------- #
_INJECTED_IO_MESSAGE = "review-injected I/O error on the sealed descriptor"


def _fail_the_nth_recheck(monkeypatch: pytest.MonkeyPatch, nth: int) -> dict[str, int]:
    """Arm a real ``os.read`` I/O error for the *nth* ``recheck()`` and no other.

    The counter counts RE-CHECKS, not raw reads: one ``recheck()`` streams a
    0.70 GB digest through many ``os.read`` calls, so counting reads would arm the
    failure at an arbitrary point of an arbitrary pass. Wrapping
    :meth:`VerifiedDescriptor.recheck` makes "which re-check" the unit, and the
    patched ``os.read`` is installed only for the duration of that one call.

    Returns
    -------
    dict
        ``{"rechecks": n}``, live, so a test can assert HOW MANY re-checks ran.
    """
    state = {"rechecks": 0}
    real_recheck = preseal_mod.VerifiedDescriptor.recheck
    real_os_read = preseal_mod.os.read

    def failing_read(fd, length):  # noqa: ARG001 - signature parity with os.read
        raise OSError(errno.EIO, _INJECTED_IO_MESSAGE)

    def counting_recheck(self):
        state["rechecks"] += 1
        if state["rechecks"] != nth:
            return real_recheck(self)
        preseal_mod.os.read = failing_read
        try:
            return real_recheck(self)
        finally:
            preseal_mod.os.read = real_os_read

    monkeypatch.setattr(preseal_mod.VerifiedDescriptor, "recheck", counting_recheck)
    monkeypatch.setattr(preseal_mod.os, "read", real_os_read)  # restored by monkeypatch
    return state


def test_an_io_error_in_the_diagnostic_rehash_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Arm 1: the SECOND re-check (the exit diagnostic) cannot read the descriptor.

    Consumption already ended and was already proven: the first re-check ran on
    the real bytes and accepted them, and the terminal records that. A diagnostic
    that cannot RUN is not evidence that the consumed bytes were wrong, so it must
    not overturn a durable COMPLETE --- it names itself on stderr and exits 0.
    """
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)
    state = _fail_the_nth_recheck(monkeypatch, nth=2)

    # CAPTURE the escape rather than letting it end the test body: the claim in this
    # test's own name is "not raised", so removing the guard must fail HERE, as an
    # AssertionError from this test, not as an OSError erroring out of pytest.
    rc: int | None = None
    escaped = ""
    try:
        rc = run_phase2b_subcommand(
            fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
        )
    except Exception as exc:  # noqa: BLE001 - the escape is the thing being measured
        escaped = f"{type(exc).__name__}: {exc}"

    assert escaped == "", (
        "the exit-time diagnostic re-hash must never raise; it escaped "
        f"`run_phase2b_subcommand` as {escaped}"
    )
    assert rc == PHASE2B_COMPLETE_EXIT, "a diagnostic that could not run must not change the exit"
    assert state["rechecks"] == 2, (
        "the arm requires exactly two re-checks (materialization, then diagnostic); "
        f"got {state['rechecks']}"
    )
    assert _terminal_states(fx.run_dir) == ["COMPLETE"]
    assert run_recover_subcommand(run_dir=fx.run_dir) == RECOVER_COMPLETE_EXIT
    err = capsys.readouterr().err
    assert "post-consumption diagnostic re-hash could not run" in err, (
        f"the failure must name itself on stderr, not vanish; stderr was {err!r}"
    )
    assert "OSError" in err and "I/O error" in err and f"[Errno {errno.EIO}]" in err, (
        f"the diagnostic must name the failure class and message; stderr was {err!r}"
    )
    assert fx.sealed_outcome["source_file_sha256"] in err


def test_an_io_error_in_the_materialization_recheck_still_aborts_after_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Arm 2: the FIRST re-check (the consumption boundary) cannot read the descriptor.

    Here the run cannot PROVE that what it consumed is what it verified, and it is
    still inside the terminal protection boundary. Fail closed: the store wraps any
    ``Exception`` from ``post_materialization_check`` into ``ComposeSealingError``,
    so this becomes ``ABORTED_AFTER_SEAL`` / exit 30 and ``recover`` agrees. Widening
    the diagnostic branch to ``except Exception`` must not reach this position ---
    that is what this arm measures.

    The EXIT CODE below is NOT the store's to give: ``phase2b_cmd._seal_consumed``
    returns 30 on the durable audit's mere existence, whatever the exception type.
    Measured: disabling the store's ``except Exception`` leaves ``rc == 30`` green and
    turns only the message assertion red -- so the message assertion, not ``rc``, is
    this arm's kill for a mutation of that wrapping (변이 규칙 7).
    """
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)
    state = _fail_the_nth_recheck(monkeypatch, nth=1)

    rc = run_phase2b_subcommand(
        fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
    )

    assert rc == PHASE2B_NONCOMPLETE_EXIT, "an unprovable consumption must fail closed, not exit 0"
    assert state["rechecks"] == 1, (
        "the failure must end the run at the consumption boundary, before any "
        f"diagnostic re-check; got {state['rechecks']} re-checks"
    )
    err = capsys.readouterr().err
    assert "sealed source integrity check failed after materialization" in err
    assert "OSError" in err and "I/O error" in err
    assert len(_audit_lines(fx.run_dir)) == 1
    assert _terminal_states(fx.run_dir) == ["ABORTED_AFTER_SEAL"]
    assert not (fx.run_dir / Phase2bTerminal.COMPLETE_ARTIFACT).exists()
    assert (fx.run_dir / DURABLE_COMMIT_FILENAME).is_file()
    assert run_recover_subcommand(run_dir=fx.run_dir) == RECOVER_NONCOMPLETE_EXIT


# --------------------------------------------------------------------------- #
# (d) the handle itself: the three arms of `recheck()`
#
# Each arm CAPTURES the refusal (or its absence) and asserts on it, so every
# mutation of the guard is killed by an AssertionError from the test whose own
# name makes the claim -- not by an exception escaping the test body.
# --------------------------------------------------------------------------- #
def _recheck_refusal(handle) -> str:
    """Return the refusal message ``recheck()`` raises, or ``""`` if it accepts."""
    try:
        handle.recheck()
    except PresealDescriptorError as exc:
        return str(exc)
    return ""


def test_the_handle_recheck_accepts_an_untouched_source(tmp_path: Path) -> None:
    """Non-vacuity: a check that refuses everything is an outage, not a guard."""
    source = tmp_path / "sealed.bin"
    payload = b"untouched" * 512
    source.write_bytes(payload)

    with verified_descriptor_handle(source, hashlib.sha256(payload).hexdigest()) as handle:
        assert handle.path.read_bytes() == payload
        # twice: re-streaming must be idempotent, not a one-shot consumption
        refusals = [_recheck_refusal(handle), _recheck_refusal(handle)]

    assert refusals == ["", ""], f"an untouched source must not be refused: {refusals}"


def test_the_handle_recheck_refuses_an_in_place_mutation(tmp_path: Path) -> None:
    source = tmp_path / "sealed.bin"
    payload = b"O" * 4096
    source.write_bytes(payload)
    inode_before = source.stat().st_ino
    stat_before = source.stat()

    with verified_descriptor_handle(source, hashlib.sha256(payload).hexdigest()) as handle:
        with open(source, "r+b") as fh:
            fh.seek(0)
            fh.write(b"X" * 4096)  # same LENGTH, so st_size is unchanged
            fh.flush()
            os.fsync(fh.fileno())
        # restore (atime, mtime) too, so ONLY the digest can tell: an identity-only
        # re-check would have nothing left to see.
        os.utime(source, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))
        refusal = _recheck_refusal(handle)

    assert source.stat().st_ino == inode_before, "the reproduction requires the same inode"
    assert "modified IN PLACE" in refusal, f"a mutated inode must be refused, got {refusal!r}"


def test_the_handle_recheck_refuses_an_identity_change_with_matching_bytes(
    tmp_path: Path,
) -> None:
    """Bytes alone are not the contract: the inode identity must also hold."""
    source = tmp_path / "sealed.bin"
    payload = b"Z" * 4096
    source.write_bytes(payload)
    before = source.stat()

    with verified_descriptor_handle(source, hashlib.sha256(payload).hexdigest()) as handle:
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
        refusal = _recheck_refusal(handle)

    assert "changed identity while it was open" in refusal, (
        f"a changed identity must be refused even with matching bytes, got {refusal!r}"
    )


def test_the_handle_does_not_recheck_at_context_exit(tmp_path: Path) -> None:
    """The property the C1 fix rests on: the EXIT is not the consumption boundary.

    If this context manager re-checked on exit, the driver would be back to
    discovering the divergence after the terminal is durable. The lane that really
    does end consumption with the `with` block is `verified_descriptor`, and its
    exit-time re-check is pinned in
    `test_phase2b_cmd.py::test_the_exit_time_lane_still_refuses_an_in_place_mutation`.
    """
    source = tmp_path / "sealed.bin"
    payload = b"Q" * 4096
    source.write_bytes(payload)

    raised_at_exit = ""
    try:
        with verified_descriptor_handle(source, hashlib.sha256(payload).hexdigest()):
            with open(source, "r+b") as fh:
                fh.seek(0)
                fh.write(b"W" * 4096)
                fh.flush()
                os.fsync(fh.fileno())
    except PresealDescriptorError as exc:  # pragma: no cover - the assertion reports it
        raised_at_exit = str(exc)

    assert raised_at_exit == "", (
        "the handle must leave the decision to the consumer; it re-checked at exit: "
        f"{raised_at_exit!r}"
    )
