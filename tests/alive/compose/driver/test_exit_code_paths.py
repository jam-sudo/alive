"""Every classified pre-seal rejection really produces the contracted exit 10.

The sibling :mod:`test_exit_code_contract` proves the ROSTER is complete and
consistent with the classification table. This file proves the roster is EFFECTIVE:
each admitted type, injected into the real :func:`~alive.compose.driver.cli.main`,
produces exit ``10``, exactly one STDERR line of the registered
``f"{stage}: {type(exc).__name__}: {exc}"`` shape, and an empty STDOUT. The last
of those is the seal-safety property: no aggregate, no verdict, no per-pair value
ever reaches STDOUT on a rejection.

It also pins the OTHER half of the 2026-08-01 contract amendment -- an exception
outside the roster is a driver BUG that propagates with its traceback (exit ``1``
once the interpreter is done with it), and even then STDOUT stays empty.
"""

from __future__ import annotations

import pytest

from alive.compose.driver import cli
from tests.alive.compose.driver.test_exit_code_contract import (
    _CLASSIFICATION,
    PRESEAL_REJECTION,
)

_SUBCOMMAND_ARGV = {
    "phase2a": [
        "phase2a",
        "--run-spec",
        "s.json",
        "--approved-artifacts-root",
        "r",
        "--run-dir",
        "d",
    ],
    "preflight": [
        "preflight",
        "--run-spec",
        "s.json",
        "--approved-artifacts-root",
        "r",
        "--run-dir",
        "d",
    ],
    "phase2b": [
        "phase2b",
        "--run-spec",
        "s.json",
        "--approved-artifacts-root",
        "r",
        "--run-dir",
        "d",
        "--confirm-seal",
        "token",
    ],
    "recover": ["recover", "--run-dir", "d"],
}


def _rejection_types() -> list[type[BaseException]]:
    """Every class the table classifies PRESEAL_REJECTION, resolved to a type."""
    types: list[type[BaseException]] = []
    for key, (classification, _why) in sorted(_CLASSIFICATION.items()):
        if classification != PRESEAL_REJECTION:
            continue
        module_name, _, class_name = key.partition("::")
        module = __import__(module_name, fromlist=[class_name])
        types.append(getattr(module, class_name))
    return types


_REJECTIONS = _rejection_types()


def _install_raiser(monkeypatch, stage: str, exc: BaseException) -> None:
    """Make ``stage``'s first real step raise ``exc``, before any I/O happens."""

    def _raise(*_args, **_kwargs):
        raise exc

    target = "run_recover_subcommand" if stage == "recover" else "_build_run_spec_carrier"
    monkeypatch.setattr(cli, target, _raise)


#: The contracted code per stage. ``recover`` is 30, not 10, on purpose: exit 10
#: asserts "the seal was NOT consumed", and recover runs only on a run whose seal
#: may already be burned (2026-08-01 review). The stderr LINE is identical in both.
_EXPECTED_EXIT = {
    "phase2a": cli.PRESEAL_REJECT_EXIT,
    "preflight": cli.PRESEAL_REJECT_EXIT,
    "phase2b": cli.PRESEAL_REJECT_EXIT,
    "recover": cli.POSTSEAL_NONCOMPLETE_EXIT,
}


@pytest.mark.parametrize("stage", sorted(_SUBCOMMAND_ARGV))
@pytest.mark.parametrize("exc_type", _REJECTIONS, ids=lambda t: t.__name__)
def test_a_classified_rejection_exits_contracted_with_one_stderr_line_and_no_stdout(
    stage, exc_type, monkeypatch, capsys
):
    exc = exc_type("injected rejection")
    _install_raiser(monkeypatch, stage, exc)

    code = cli.main(_SUBCOMMAND_ARGV[stage])

    captured = capsys.readouterr()
    assert code == _EXPECTED_EXIT[stage]
    assert captured.out == "", f"{exc_type.__name__} leaked to STDOUT: {captured.out!r}"
    lines = captured.err.splitlines()
    assert lines == [f"{stage}: {exc_type.__name__}: injected rejection"]


def test_recover_never_reports_the_seal_as_unconsumed():
    """Pins the 2026-08-01 correction as a property, not just a table lookup.

    ``recover`` exists for the crash state where a seal was already claimed. Exit
    10's registered meaning is "pre-seal rejection, no seal consumed", so recover
    must never return it -- ``run_dir_state`` raising on two terminal artifacts, and
    ``_assert_no_raw_outcomes`` raising ``TerminalError`` out of the marker-absent
    salvage path, are both only REACHABLE once the seal is gone.
    """
    assert _EXPECTED_EXIT["recover"] != cli.PRESEAL_REJECT_EXIT
    assert _EXPECTED_EXIT["recover"] == cli.POSTSEAL_NONCOMPLETE_EXIT


@pytest.mark.parametrize("stage", sorted(_SUBCOMMAND_ARGV))
def test_an_unclassified_exception_propagates_as_a_bug_and_keeps_stdout_empty(
    stage, monkeypatch, capsys
):
    """The registered exit-1 escape: a bug is never mapped to a contracted code."""

    class _NotInTheRoster(Exception):
        """Deliberately unrelated to every admitted type."""

    _install_raiser(monkeypatch, stage, _NotInTheRoster("internal invariant broken"))

    with pytest.raises(_NotInTheRoster):
        cli.main(_SUBCOMMAND_ARGV[stage])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""  # no contracted one-liner for a bug; the traceback is the signal


@pytest.mark.parametrize("stage", sorted(_SUBCOMMAND_ARGV))
def test_a_bare_valueerror_is_a_bug_not_a_contracted_rejection(stage, monkeypatch, capsys):
    """The admission rule, exercised end to end rather than only asserted.

    ``src/alive/compose`` raises a bare ``ValueError`` in over two hundred places,
    most of them internal-invariant violations. If the builtin were ever admitted,
    this would return a contracted code and every one of those would be reported as
    a documented rejection. An earlier version of this test only did an
    ``isinstance`` check, which was a strict subset of
    ``test_the_roster_admits_no_builtin_base`` wearing a stronger name.
    """
    _install_raiser(monkeypatch, stage, ValueError("a bare builtin, not a contract type"))

    with pytest.raises(ValueError):
        cli.main(_SUBCOMMAND_ARGV[stage])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_the_injected_roster_is_not_silently_empty():
    """An empty parametrize list SKIPS rather than fails, so pin the count.

    ``_REJECTIONS`` is derived at import from the sibling module's table. If that
    derivation ever yields nothing -- a renamed constant, a partial edit -- pytest
    reports a skip and the suite stays green while 168 cases quietly vanish.
    """
    assert len(_REJECTIONS) == 43, (
        f"expected 43 PRESEAL_REJECTION classes, found {len(_REJECTIONS)}; update this "
        "count deliberately when the classification changes, never to make it pass"
    )
