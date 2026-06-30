"""Crash-resistant, non-overwriting artifact writes (milestone-neutral).

This primitive is shared by every protocol's write-once seal/audit lifecycle
(§11): it lives at the package root so that lower/shared layers (e.g.
``alive.data``) never need to depend on any single milestone package such as
``alive.compose``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_once(path: str | Path, data: str, *, encoding: str = "utf-8") -> None:
    """Atomically publish ``data`` at ``path`` without replacing an existing file."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # link(2) publishes atomically and fails if destination already exists.
        os.link(temporary, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
