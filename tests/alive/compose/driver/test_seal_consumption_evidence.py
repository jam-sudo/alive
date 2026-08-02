"""The two places the driver decides "was the seal consumed?" from the filesystem.

Both were reported by independent review (2026-08-01 / 2026-08-02) and both had the
same failure DIRECTION: on missing or ambiguous information they concluded "not
consumed", which is the one answer that puts a false claim about the seal into a
pod operator's hands. Exit ``10`` means "pre-seal rejection, the seal was NOT
consumed"; guessing it wrong invites a retry on a run whose seal is already burned.

The two directions are not symmetric, and these tests pin that asymmetry:

* guessing "consumed" costs a ``recover`` -- recoverable, and the runbook says so;
* guessing "not consumed" costs a false statement about a one-shot scientific seal.

So both helpers fail CLOSED toward "consumed" whenever the filesystem does not give
a clean answer. Neither opens a seal, reads an outcome, or constructs a store.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alive.compose.driver.phase2b_cmd import (
    PHASE2B_NONCOMPLETE_EXIT,
    _prior_terminal_present,
    _seal_consumed,
    run_phase2b_subcommand,
)
from alive.compose.driver.run_dir_state import TERMINAL_BASENAMES, RunDirStateError

# --------------------------------------------------------------------------- #
# _seal_consumed
# --------------------------------------------------------------------------- #


def test_an_absent_audit_is_the_only_read_of_not_consumed(tmp_path):
    assert _seal_consumed(tmp_path / "nope.jsonl") is False


def test_an_empty_audit_is_not_consumed(tmp_path):
    audit = tmp_path / "audit.jsonl"
    audit.write_text("", encoding="utf-8")
    assert _seal_consumed(audit) is False


def test_a_non_empty_audit_is_consumed(tmp_path):
    audit = tmp_path / "audit.jsonl"
    audit.write_text('{"claim": 1}\n', encoding="utf-8")
    assert _seal_consumed(audit) is True


@pytest.mark.parametrize(
    "error",
    [
        PermissionError(13, "Permission denied"),
        OSError(5, "Input/output error"),
        OSError(116, "Stale file handle"),
        OSError(24, "Too many open files"),
    ],
    ids=["EACCES", "EIO", "ESTALE", "EMFILE"],
)
def test_an_unreadable_audit_fails_closed_toward_consumed(tmp_path, monkeypatch, error):
    """The defect this replaced: ``Path.exists()`` swallows these and returns False.

    A post-seal exception was then re-raised and reported as exit 10 -- "the seal was
    NOT consumed" -- about a seal that may have been burned. An NFS-backed approved
    root going stale, or a remount changing permissions, is an ordinary pod event.
    """
    audit = tmp_path / "audit.jsonl"
    audit.write_text('{"claim": 1}\n', encoding="utf-8")

    def _raise(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(Path, "stat", _raise)
    assert _seal_consumed(audit) is True


def test_the_audit_vanishing_mid_check_does_not_replace_the_caller_s_exception(
    tmp_path, monkeypatch
):
    """The TOCTOU: ``exists()`` then ``stat()`` could raise from inside the handler.

    The caller runs this inside its own ``except Exception`` block, so a
    ``FileNotFoundError`` escaping here replaced the original post-seal exception and
    surfaced as an unrelated chained traceback. One ``stat()`` removes the window.
    """
    calls: list[int] = []

    def _vanish(*_args, **_kwargs):
        calls.append(1)
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(Path, "stat", _vanish)
    assert _seal_consumed(tmp_path / "audit.jsonl") is False
    assert len(calls) == 1, "more than one filesystem call reopens the TOCTOU window"


# --------------------------------------------------------------------------- #
# _prior_terminal_present / phase2b step 0
# --------------------------------------------------------------------------- #


def test_no_terminal_means_no_prior_consumption(tmp_path):
    assert _prior_terminal_present(tmp_path) is False


@pytest.mark.parametrize("basename", sorted(TERMINAL_BASENAMES))
def test_each_terminal_artifact_counts_as_prior_consumption(tmp_path, basename):
    (tmp_path / basename).write_text("{}", encoding="utf-8")
    assert _prior_terminal_present(tmp_path) is True


def test_an_unreadable_run_dir_fails_closed_toward_consumed(tmp_path, monkeypatch):
    def _raise(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "iterdir", _raise)
    assert _prior_terminal_present(tmp_path) is True


def test_phase2b_reports_30_not_a_false_preseal_rejection_when_a_terminal_exists(tmp_path):
    """The step-0 defect, end to end through the subcommand.

    ``phase2b``'s entry roster FORBIDS a terminal, so the artifact that proves the
    seal was consumed is exactly the artifact that trips the roster. Before this,
    ``RunDirStateError`` propagated to ``cli.main`` and became exit ``10`` -- "the
    seal was NOT consumed" -- with ``terminal_complete.json`` sitting on disk saying
    otherwise. It is the same defect the ``recover`` branch had, on the subcommand a
    real scientific run actually reaches.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "terminal_complete.json").write_text("{}", encoding="utf-8")

    code = run_phase2b_subcommand(
        object(),  # never touched: step 0 returns before the carrier is used
        approved_artifacts_root=tmp_path / "root",
        run_dir=run_dir,
        confirm_seal_token="unused",
    )
    assert code == PHASE2B_NONCOMPLETE_EXIT


def test_a_roster_violation_without_a_terminal_still_raises(tmp_path):
    """The gate is evidence-based, not a blanket downgrade of every roster failure."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "some_unexpected_file.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RunDirStateError):
        run_phase2b_subcommand(
            object(),
            approved_artifacts_root=tmp_path / "root",
            run_dir=run_dir,
            confirm_seal_token="unused",
        )


# --------------------------------------------------------------------------- #
# step 6: the post-seal durable marker re-read
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "error",
    [KeyError("filename"), OSError(5, "Input/output error"), ValueError("bad json")],
    ids=["KeyError", "OSError", "ValueError"],
)
def test_a_malformed_durable_marker_returns_30_rather_than_a_bug_traceback(
    tmp_path, monkeypatch, capsys, error
):
    """Step 6 runs after the seal is consumed, so its failures are 30, not 1.

    The handler caught only ``Phase2bSubcommandError``, but ``_reread_durable_commit``
    reads the marker AND every file it records: a missing ``filename``/``sha256`` key
    is a ``KeyError``, an unreadable recorded file an ``OSError``. Those escaped as
    the registered bug escape (exit 1) when the operator's actual next action is
    ``recover`` -- which is what 30 says. The seal-state reasoning does not depend on
    the exception class, so the handler must not either.
    """
    from alive.compose.driver import phase2b_cmd
    from tests.alive.compose.driver.test_phase2b_cmd import (
        _confirmation_token,
        _run_preseal,
    )

    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)

    def _raise(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(phase2b_cmd, "_reread_durable_commit", _raise)

    code = phase2b_cmd.run_phase2b_subcommand(
        fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
    )
    assert code == phase2b_cmd.PHASE2B_NONCOMPLETE_EXIT
    assert "post-seal" in capsys.readouterr().err
