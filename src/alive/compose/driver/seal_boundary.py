"""Canonical durable seal boundaries for the COMPOSE production driver.

Fixture runs intentionally keep their bounded, disposable audit inside the run
directory. Scientific runs do not: every run directory for one registered
protocol resolves to the same write-once audit under the owner-approved
artifacts root. The opaque protocol digest avoids path injection and makes the
filesystem location independent of a caller-selected run directory.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from alive.compose.durable import SEAL_AUDIT_FILENAME

__all__ = [
    "SCIENTIFIC_SEAL_AUDIT_PREFIX",
    "fixture_seal_audit_path",
    "scientific_protocol_seal_audit_path",
]


SCIENTIFIC_SEAL_AUDIT_PREFIX = ".compose-protocol-seal-"


def fixture_seal_audit_path(run_dir: str | Path) -> Path:
    """Return the bounded fixture audit path."""
    return Path(run_dir) / SEAL_AUDIT_FILENAME


def scientific_protocol_seal_audit_path(
    approved_artifacts_root: str | Path,
    protocol: str,
) -> Path:
    """Return the canonical write-once audit path for a scientific protocol.

    ``protocol`` is hashed as exact UTF-8 bytes. It is never interpolated into
    the filename, so separators, Unicode, and shell metacharacters cannot alter
    the destination. The approved root is canonicalised in the same way as the
    ResolvedRunSpec loader; callers must still enforce that the run spec binds
    that root.
    """
    if not isinstance(protocol, str) or not protocol.strip():
        raise ValueError("protocol must be a non-empty string")
    root = Path(os.path.realpath(str(approved_artifacts_root)))
    protocol_digest = hashlib.sha256(protocol.encode("utf-8")).hexdigest()
    return root / f"{SCIENTIFIC_SEAL_AUDIT_PREFIX}{protocol_digest}.jsonl"
