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


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    head = init_synthetic_repo(repo)
    return repo, head


def test_clean_repo_at_approved_head_resolves(tmp_path):
    repo, head = _repo(tmp_path)
    ctx = resolve_scientific_runtime_context(
        trusted_repo_root=repo, approved_git_sha=head, lockfile_path=repo / "README"
    )
    assert isinstance(ctx, ScientificRuntimeContext)
    assert ctx.git_is_clean is True
    assert ctx.head_sha == head
    assert ctx.environment.git_commit == head
    assert Path(ctx.repo_root) == Path(repo).resolve()


def test_wrong_head_rejects(tmp_path):
    repo, _ = _repo(tmp_path)
    with pytest.raises(ScientificRuntimeError, match="HEAD"):
        resolve_scientific_runtime_context(
            trusted_repo_root=repo, approved_git_sha="a" * 40, lockfile_path=repo / "README"
        )


def test_dirty_tracked_rejects(tmp_path):
    repo, head = _repo(tmp_path)
    (repo / "README").write_text("dirtied\n", encoding="utf-8")
    with pytest.raises(ScientificRuntimeError, match="clean|dirty|status"):
        resolve_scientific_runtime_context(
            trusted_repo_root=repo, approved_git_sha=head, lockfile_path=repo / "README"
        )


def test_untracked_file_rejects(tmp_path):
    repo, head = _repo(tmp_path)
    (repo / "stray.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(ScientificRuntimeError, match="clean|dirty|status"):
        resolve_scientific_runtime_context(
            trusted_repo_root=repo, approved_git_sha=head, lockfile_path=repo / "README"
        )


def test_malformed_sha_rejects(tmp_path):
    repo, _ = _repo(tmp_path)
    with pytest.raises(ScientificRuntimeError, match="hex|sha|SHA"):
        resolve_scientific_runtime_context(
            trusted_repo_root=repo, approved_git_sha="not-a-sha", lockfile_path=repo / "README"
        )


def test_absent_git_rejects(tmp_path, monkeypatch):
    repo, head = _repo(tmp_path)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(ScientificRuntimeError):
        resolve_scientific_runtime_context(
            trusted_repo_root=repo, approved_git_sha=head, lockfile_path=repo / "README"
        )


def test_wrong_repo_root_rejects(tmp_path):
    repo, head = _repo(tmp_path)
    other = tmp_path / "not-a-repo"
    other.mkdir()
    with pytest.raises(ScientificRuntimeError):
        resolve_scientific_runtime_context(
            trusted_repo_root=other, approved_git_sha=head, lockfile_path=repo / "README"
        )


def test_status_command_does_not_ignore_submodules(tmp_path):
    # The porcelain status command must carry --ignore-submodules=none so submodule dirt
    # is never silently ignored (spec §2.3.3). Guard the constant directly.
    from alive.compose.driver import scientific_runtime as sr

    assert "--ignore-submodules=none" in sr._STATUS_ARGV
    assert "--untracked-files=all" in sr._STATUS_ARGV
