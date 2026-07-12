"""Runtime git/environment identity resolver (spec §2.3) — fail-closed, no shell."""

from __future__ import annotations

from pathlib import Path

import pytest

from alive.compose.driver.scientific_runtime import (
    ScientificRuntimeContext,
    ScientificRuntimeError,
    resolve_scientific_runtime_context,
)
from tests.alive.compose.driver.scientific_carrier_support import init_synthetic_repo

_SEEDS = (11, 23, 37)


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    head = init_synthetic_repo(repo)
    return repo, head


def test_clean_repo_at_approved_head_resolves(tmp_path):
    repo, head = _repo(tmp_path)
    ctx = resolve_scientific_runtime_context(
        trusted_repo_root=repo,
        approved_git_sha=head,
        lockfile_path=repo / "README",
        registered_seeds=_SEEDS,
    )
    assert isinstance(ctx, ScientificRuntimeContext)
    assert ctx.git_is_clean is True
    assert ctx.head_sha == head
    assert ctx.environment.git_commit == head
    assert ctx.environment.registered_seeds == _SEEDS
    assert Path(ctx.repo_root) == Path(repo).resolve()


def test_wrong_head_rejects(tmp_path):
    repo, _ = _repo(tmp_path)
    with pytest.raises(ScientificRuntimeError, match="HEAD"):
        resolve_scientific_runtime_context(
            trusted_repo_root=repo,
            approved_git_sha="a" * 40,
            lockfile_path=repo / "README",
            registered_seeds=_SEEDS,
        )


def test_dirty_tracked_rejects(tmp_path):
    repo, head = _repo(tmp_path)
    (repo / "README").write_text("dirtied\n", encoding="utf-8")
    with pytest.raises(ScientificRuntimeError, match="clean|dirty|status"):
        resolve_scientific_runtime_context(
            trusted_repo_root=repo,
            approved_git_sha=head,
            lockfile_path=repo / "README",
            registered_seeds=_SEEDS,
        )


def test_untracked_file_rejects(tmp_path):
    repo, head = _repo(tmp_path)
    (repo / "stray.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(ScientificRuntimeError, match="clean|dirty|status"):
        resolve_scientific_runtime_context(
            trusted_repo_root=repo,
            approved_git_sha=head,
            lockfile_path=repo / "README",
            registered_seeds=_SEEDS,
        )


def test_malformed_sha_rejects(tmp_path):
    repo, _ = _repo(tmp_path)
    # Match text unique to the format-validation guard (scientific_runtime.py ~L78-81) so this
    # test fails if that guard is removed. A generic "hex|sha|SHA" regex is also satisfied by the
    # unrelated HEAD-mismatch fallback message further down ("runtime HEAD ... != approved_git_sha
    # ..." -- "sha" appears in the variable name), so it gave zero regression protection.
    with pytest.raises(ScientificRuntimeError, match="40- or 64-char lowercase hex"):
        resolve_scientific_runtime_context(
            trusted_repo_root=repo,
            approved_git_sha="not-a-sha",
            lockfile_path=repo / "README",
            registered_seeds=_SEEDS,
        )


def test_absent_git_rejects(tmp_path, monkeypatch):
    repo, head = _repo(tmp_path)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(ScientificRuntimeError):
        resolve_scientific_runtime_context(
            trusted_repo_root=repo,
            approved_git_sha=head,
            lockfile_path=repo / "README",
            registered_seeds=_SEEDS,
        )


def test_wrong_repo_root_rejects(tmp_path):
    # Pins the toplevel-mismatch guard (scientific_runtime.py ~L86-90): build a real, initialized
    # repo (init_synthetic_repo, Task-1 support) and pass a SUBDIRECTORY of it as
    # `trusted_repo_root`. `git rev-parse --show-toplevel` run with cwd=subdir still succeeds and
    # returns the repo's ANCESTOR root, which != the trusted subdirectory, so the mismatch guard
    # must fire. A plain never-git-init'd directory (see
    # test_repo_root_not_a_git_repo_rejects below) instead trips `_git()`'s "not a git repository"
    # exit-128 error and never reaches this guard -- that gave zero regression protection for it.
    repo, head = _repo(tmp_path)
    subdir = repo / "nested"
    subdir.mkdir()
    with pytest.raises(ScientificRuntimeError, match="git toplevel"):
        resolve_scientific_runtime_context(
            trusted_repo_root=subdir,
            approved_git_sha=head,
            lockfile_path=repo / "README",
            registered_seeds=_SEEDS,
        )


def test_repo_root_not_a_git_repo_rejects(tmp_path):
    repo, head = _repo(tmp_path)
    other = tmp_path / "not-a-repo"
    other.mkdir()
    with pytest.raises(ScientificRuntimeError):
        resolve_scientific_runtime_context(
            trusted_repo_root=other,
            approved_git_sha=head,
            lockfile_path=repo / "README",
            registered_seeds=_SEEDS,
        )


@pytest.mark.parametrize("bad_seeds", [(), [], "11", (11, True), (11, 2.5)])
def test_invalid_registered_seed_roster_rejects(tmp_path, bad_seeds):
    repo, head = _repo(tmp_path)
    with pytest.raises(ScientificRuntimeError, match="registered_seeds"):
        resolve_scientific_runtime_context(
            trusted_repo_root=repo,
            approved_git_sha=head,
            lockfile_path=repo / "README",
            registered_seeds=bad_seeds,
        )


def test_status_command_does_not_ignore_submodules(tmp_path):
    # The porcelain status command must carry --ignore-submodules=none so submodule dirt
    # is never silently ignored (spec §2.3.3). Guard the constant directly.
    from alive.compose.driver import scientific_runtime as sr

    assert "--ignore-submodules=none" in sr._STATUS_ARGV
    assert "--untracked-files=all" in sr._STATUS_ARGV
