"""Independent runtime Git/environment identity for a scientific driver process (spec §2.3).

Each scientific CLI command re-resolves this context, so a change between phase2a, preflight and
phase2b fails closed. Resolution uses argv-based subprocess calls (NO shell) and fails closed
unless: the trusted canonical repository root equals ``git rev-parse --show-toplevel``; HEAD equals
the spec's ``approved_git_sha`` exactly; the working tree is fully clean (tracked + untracked +
submodules, none ignored); the SHA is exact full-hex; and environment capture succeeds. No
caller-asserted clean boolean or context is accepted. This module opens no seal and reads no
outcome.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from alive.provenance import EnvironmentInfo, capture_environment

__all__ = [
    "ScientificRuntimeContext",
    "ScientificRuntimeError",
    "resolve_scientific_runtime_context",
]

_FULL_HEX_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")

#: Porcelain status argv — tracked + untracked + submodule changes all surface (none ignored).
_STATUS_ARGV: tuple[str, ...] = (
    "status",
    "--porcelain=v1",
    "--untracked-files=all",
    "--ignore-submodules=none",
)
_GIT_TIMEOUT = 15


class ScientificRuntimeError(RuntimeError):
    """Raised on ANY runtime git/environment identity failure (fail-closed)."""


@dataclass(frozen=True)
class ScientificRuntimeContext:
    repo_root: Path
    head_sha: str
    git_is_clean: bool
    environment: EnvironmentInfo


def _git(repo_root: Path, *args: str) -> str:
    """Run ``git <args>`` with cwd=repo_root (argv, no shell); return stripped stdout."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScientificRuntimeError(f"git {' '.join(args)} failed at {repo_root}: {exc}") from exc
    if result.returncode != 0:
        raise ScientificRuntimeError(
            f"git {' '.join(args)} exited {result.returncode} at {repo_root}: "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def resolve_scientific_runtime_context(
    *,
    trusted_repo_root: Path,
    approved_git_sha: str,
    lockfile_path: Path,
    registered_seeds: Sequence[int],
) -> ScientificRuntimeContext:
    """Resolve + validate the runtime context, or fail closed (§2.3)."""
    if not isinstance(approved_git_sha, str) or _FULL_HEX_RE.match(approved_git_sha) is None:
        raise ScientificRuntimeError(
            f"approved_git_sha must be full 40- or 64-char lowercase hex, got {approved_git_sha!r}"
        )
    root_real = Path(os.path.realpath(str(trusted_repo_root)))
    if not root_real.is_dir():
        raise ScientificRuntimeError(f"trusted repo root is not a directory: {root_real}")
    if isinstance(registered_seeds, (str, bytes)) or not isinstance(registered_seeds, Sequence):
        raise ScientificRuntimeError("registered_seeds must be a non-empty sequence of integers")
    seeds = tuple(registered_seeds)
    if not seeds or any(type(seed) is not int for seed in seeds):
        raise ScientificRuntimeError("registered_seeds must be a non-empty sequence of integers")

    toplevel = _git(root_real, "rev-parse", "--show-toplevel").strip()
    if Path(os.path.realpath(toplevel)) != root_real:
        raise ScientificRuntimeError(
            f"git toplevel {toplevel!r} != trusted repo root {str(root_real)!r}"
        )

    head = _git(root_real, "rev-parse", "HEAD").strip()
    if _FULL_HEX_RE.match(head) is None:
        raise ScientificRuntimeError(f"HEAD is not exact full-hex: {head!r}")
    if head != approved_git_sha:
        raise ScientificRuntimeError(
            f"runtime HEAD {head!r} != approved_git_sha {approved_git_sha!r}"
        )

    status = _git(root_real, *_STATUS_ARGV)
    if status.strip() != "":
        raise ScientificRuntimeError(
            "working tree is not clean (tracked/untracked/submodule changes present)"
        )

    try:
        environment = capture_environment(lockfile_path, seeds, repo_dir=root_real)
    except OSError as exc:
        raise ScientificRuntimeError(f"environment capture failed: {exc}") from exc
    if environment.git_commit != approved_git_sha:
        raise ScientificRuntimeError(
            f"captured environment git_commit {environment.git_commit!r} != "
            f"approved_git_sha {approved_git_sha!r}"
        )

    return ScientificRuntimeContext(
        repo_root=root_real,
        head_sha=head,
        git_is_clean=True,
        environment=environment,
    )
