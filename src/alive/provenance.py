"""Provenance ledger: streaming SHA-256 utilities, environment capture, and RunLedger.

This module provides the spine for scientific auditability in ALIVE experiments.
Every artifact produced by later tasks (data preprocessing, splits, model checkpoints,
evaluation results) should be recorded here to enable tamper detection and reproducibility.

Canonical artifact names (used as ``name`` arguments to :meth:`RunLedger.record_artifact`
and :meth:`RunLedger.record_file`):

- ``"raw_data"``         — the downloaded / validated raw .h5ad input
- ``"split_manifest"``   — the versioned cell-barcode split manifest
- ``"feature_bank"``     — the frozen perturbation feature matrix
- ``"preprocessing_state"`` — fitted preprocessor (scaler, PCA, etc.)
- ``"result"``           — final evaluation result JSON/parquet

These names are just strings; the ledger imposes no schema on them.

Public API
----------
sha256_file(path, *, chunk_size=1<<20)
    Streaming SHA-256 hex digest of a file.
sha256_bytes(data)
    SHA-256 hex digest of a bytes object.
sha256_json(obj)
    SHA-256 hex of canonical JSON (sort_keys, compact separators).
capture_environment(lockfile_path, registered_seeds, *, repo_dir=None)
    Capture Python version, platform, git HEAD, lockfile hash, and seeds.
RunLedger
    Immutable artifact registry with change/tamper detection and JSON round-trip.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class DuplicateArtifactError(ValueError):
    """Raised when an artifact name is registered more than once.

    Artifact names in :class:`RunLedger` are write-once; attempting to
    overwrite an existing entry (even with the same hash) raises this error.

    Parameters
    ----------
    message : str
        Human-readable description of the conflict.
    """


class LedgerError(ValueError):
    """Raised when a requested artifact name is not present in the ledger.

    Parameters
    ----------
    message : str
        Human-readable description of the missing entry.
    """


# ---------------------------------------------------------------------------
# Streaming hash utilities
# ---------------------------------------------------------------------------


def sha256_file(path: str | Path, *, chunk_size: int = 1 << 20) -> str:
    """Streaming SHA-256 hex digest of a file.

    Reads the file in chunks of *chunk_size* bytes so it works on arbitrarily
    large files (e.g. multi-GB ``.h5ad`` datasets) without loading them into
    memory.

    Parameters
    ----------
    path : str or Path
        Path to the file to hash.
    chunk_size : int, optional
        Number of bytes per read chunk.  Defaults to 1 MiB.

    Returns
    -------
    str
        Lowercase hex-encoded SHA-256 digest.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """SHA-256 hex digest of a :class:`bytes` object.

    Parameters
    ----------
    data : bytes
        Raw bytes to hash.

    Returns
    -------
    str
        Lowercase hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(data).hexdigest()


def sha256_json(obj: object) -> str:
    """SHA-256 hex digest of a canonical JSON serialisation of *obj*.

    Serialises *obj* with ``sort_keys=True`` and compact separators
    ``(',', ':')`` so that dict key order does not affect the digest.

    Parameters
    ----------
    obj : object
        A JSON-serialisable Python object (dict, list, str, int, float, bool,
        or None, composed arbitrarily).

    Returns
    -------
    str
        Lowercase hex-encoded SHA-256 digest.
    """
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Environment capture
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnvironmentInfo:
    """Snapshot of the runtime environment at the time of a run.

    Contains no wall-clock or timestamp data so that two runs on identical
    software with identical inputs produce byte-identical ledger output.

    Parameters
    ----------
    python_version : str
        Python version string (e.g. ``"3.12.3"``).
    platform : str
        Platform description string (e.g. ``"macOS-15.0-arm64-arm-64bit"``).
    git_commit : str
        Full 40-character SHA-1 hex of the current ``HEAD`` commit, or
        ``"UNKNOWN"`` if the working directory is not a git repository or
        ``git`` is not installed.
    lockfile_sha256 : str
        SHA-256 hex digest of the ``uv.lock`` lockfile.
    registered_seeds : tuple[int, ...]
        Fixed random seeds from the experiment config for reproducible CV.
    """

    python_version: str
    platform: str
    git_commit: str
    lockfile_sha256: str
    registered_seeds: tuple[int, ...]


def capture_environment(
    lockfile_path: str | Path,
    registered_seeds: Sequence[int],
    *,
    repo_dir: str | Path | None = None,
) -> EnvironmentInfo:
    """Capture the current runtime environment without any wall-clock data.

    Parameters
    ----------
    lockfile_path : str or Path
        Path to the ``uv.lock`` (or other) lockfile whose SHA-256 is recorded.
    registered_seeds : Sequence[int]
        Registered random seeds from :attr:`Config.method_development.registered_seeds`.
    repo_dir : str or Path or None, optional
        Directory used as ``cwd`` when calling ``git rev-parse HEAD``.  If
        ``None``, uses the current working directory.  Pass a path that is *not*
        a git repository to get ``git_commit="UNKNOWN"``.

    Returns
    -------
    EnvironmentInfo
        Frozen snapshot of the environment.  Contains no timestamp.
    """
    python_version = platform.python_version()
    platform_str = platform.platform()
    lockfile_sha = sha256_file(lockfile_path)
    git_commit = _get_git_commit(repo_dir)
    return EnvironmentInfo(
        python_version=python_version,
        platform=platform_str,
        git_commit=git_commit,
        lockfile_sha256=lockfile_sha,
        registered_seeds=tuple(registered_seeds),
    )


def _get_git_commit(repo_dir: str | Path | None) -> str:
    """Return the full hex SHA-1 of HEAD, or ``"UNKNOWN"`` on any failure.

    Parameters
    ----------
    repo_dir : str or Path or None
        Working directory for the subprocess call.

    Returns
    -------
    str
        40-character hex string or ``"UNKNOWN"``.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            commit = result.stdout.strip()
            if commit:
                return commit
        return "UNKNOWN"
    except Exception:  # noqa: BLE001 — any error (FileNotFoundError, TimeoutExpired, …)
        return "UNKNOWN"


# ---------------------------------------------------------------------------
# Artifact record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactRecord:
    """An immutable (name, SHA-256) pair recorded in a :class:`RunLedger`.

    Parameters
    ----------
    name : str
        Canonical artifact name (e.g. ``"raw_data"``, ``"split_manifest"``).
    sha256 : str
        Hex-encoded SHA-256 digest of the artifact at the time of recording.
    """

    name: str
    sha256: str


# ---------------------------------------------------------------------------
# RunLedger
# ---------------------------------------------------------------------------


class RunLedger:
    """Immutable artifact ledger for a single experimental run.

    Records the provenance set required by §3.3 of the CARTOGRAPHER spec:
    every artifact is registered with its name and SHA-256 hash.  Artifact
    names are **write-once** — recording the same name twice always raises
    :class:`DuplicateArtifactError`, even if the hash is identical.

    The ledger serialises to deterministic canonical JSON (no wall-clock,
    no randomness) so that two ledgers built from identical inputs produce
    byte-identical ``write()`` output.

    Parameters
    ----------
    run_id : str
        Deterministic run identifier from :attr:`Config.run_id`.
    config_sha256 : str
        SHA-256 of the serialised config (for the §3.3 provenance set).
    environment : EnvironmentInfo
        Captured runtime environment (stdlib versions, git commit, lockfile).

    Examples
    --------
    >>> ledger = RunLedger(run_id="abc", config_sha256="def", environment=env)
    >>> ledger.record_artifact("raw_data", "abc123")
    >>> ledger.artifact_sha("raw_data")
    'abc123'
    """

    def __init__(
        self,
        run_id: str,
        config_sha256: str,
        environment: EnvironmentInfo,
    ) -> None:
        self._run_id = run_id
        self._config_sha256 = config_sha256
        self._environment = environment
        # ordered dict preserving insertion order for deterministic serialisation
        self._artifacts: dict[str, ArtifactRecord] = {}

    # ------------------------------------------------------------------
    # Artifact registry
    # ------------------------------------------------------------------

    def record_artifact(self, name: str, sha256: str) -> None:
        """Register a name→hash mapping.

        Parameters
        ----------
        name : str
            Canonical artifact name (write-once).
        sha256 : str
            Hex-encoded SHA-256 of the artifact.

        Raises
        ------
        DuplicateArtifactError
            If *name* has already been registered (even with the same hash).
        """
        if name in self._artifacts:
            raise DuplicateArtifactError(
                f"Artifact {name!r} is already recorded in this ledger. "
                "Artifact names are write-once and cannot be overwritten."
            )
        self._artifacts[name] = ArtifactRecord(name=name, sha256=sha256)

    def record_file(self, name: str, path: str | Path) -> str:
        """Stream-hash a file, record it, and return its SHA-256 digest.

        Parameters
        ----------
        name : str
            Canonical artifact name (write-once).
        path : str or Path
            Path to the file to hash and register.

        Returns
        -------
        str
            Hex-encoded SHA-256 of the file contents.

        Raises
        ------
        DuplicateArtifactError
            If *name* has already been registered.
        """
        h = sha256_file(path)
        self.record_artifact(name, h)
        return h

    def verify_file(self, name: str, path: str | Path) -> bool:
        """Recompute a file's hash and compare it to the recorded value.

        Parameters
        ----------
        name : str
            Artifact name to look up in the ledger.
        path : str or Path
            Path to the file whose current contents will be hashed.

        Returns
        -------
        bool
            ``True`` if the current hash matches the recorded hash; ``False``
            if the file has been modified or corrupted.

        Raises
        ------
        LedgerError
            If *name* has not been recorded in this ledger.
        """
        recorded = self.artifact_sha(name)  # raises LedgerError if missing
        current = sha256_file(path)
        return current == recorded

    def artifact_sha(self, name: str) -> str:
        """Return the recorded SHA-256 for *name*.

        Parameters
        ----------
        name : str
            Artifact name to look up.

        Returns
        -------
        str
            Hex-encoded SHA-256 digest.

        Raises
        ------
        LedgerError
            If *name* is not present in the ledger.
        """
        if name not in self._artifacts:
            raise LedgerError(
                f"Artifact {name!r} has not been recorded in this ledger. "
                "Call record_artifact() or record_file() first."
            )
        return self._artifacts[name].sha256

    # ------------------------------------------------------------------
    # Serialisation — deterministic, no timestamp
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dict.

        The output is deterministic: two ledgers built from identical inputs
        produce identical dicts.  No wall-clock or timestamp data is included.

        Returns
        -------
        dict
            JSON-serialisable dictionary representing the full ledger state.
        """
        env = self._environment
        return {
            "run_id": self._run_id,
            "config_sha256": self._config_sha256,
            "environment": {
                "python_version": env.python_version,
                "platform": env.platform,
                "git_commit": env.git_commit,
                "lockfile_sha256": env.lockfile_sha256,
                "registered_seeds": list(env.registered_seeds),
            },
            "artifacts": [
                {"name": rec.name, "sha256": rec.sha256} for rec in self._artifacts.values()
            ],
        }

    def write(self, path: str | Path) -> None:
        """Write the ledger to *path* as canonical JSON.

        Uses ``sort_keys=True`` and stable separators so that the output is
        byte-identical for identical ledger state, regardless of Python dict
        iteration order.

        Parameters
        ----------
        path : str or Path
            Destination file path.  Parent directory must exist.
        """
        text = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), indent=2)
        Path(path).write_text(text, encoding="utf-8")

    @classmethod
    def read(cls, path: str | Path) -> "RunLedger":
        """Deserialise a :class:`RunLedger` from a JSON file written by :meth:`write`.

        Parameters
        ----------
        path : str or Path
            Path to a JSON file produced by :meth:`write`.

        Returns
        -------
        RunLedger
            A ledger instance whose ``to_dict()`` equals that of the original.

        Raises
        ------
        LedgerError
            If the file is missing required fields or is malformed.
        """
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            raise LedgerError(f"Failed to read ledger from {path!r}: {exc}") from exc

        try:
            env_raw = raw["environment"]
            env = EnvironmentInfo(
                python_version=env_raw["python_version"],
                platform=env_raw["platform"],
                git_commit=env_raw["git_commit"],
                lockfile_sha256=env_raw["lockfile_sha256"],
                registered_seeds=tuple(env_raw["registered_seeds"]),
            )
            ledger = cls(
                run_id=raw["run_id"],
                config_sha256=raw["config_sha256"],
                environment=env,
            )
            for art in raw.get("artifacts", []):
                ledger.record_artifact(art["name"], art["sha256"])
            return ledger
        except (KeyError, TypeError) as exc:
            raise LedgerError(f"Ledger JSON is missing required field: {exc}") from exc

    # ------------------------------------------------------------------
    # Equality (compare by content for round-trip tests)
    # ------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RunLedger):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self) -> str:
        n = len(self._artifacts)
        return f"RunLedger(run_id={self._run_id!r}, artifacts={n})"
