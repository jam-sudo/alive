"""Tests for alive.provenance — streaming hashes, environment capture, RunLedger.

All tests must pass with stdlib only; no new dependencies are introduced by Task 2.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from alive.provenance import (
    ArtifactRecord,
    DuplicateArtifactError,
    EnvironmentInfo,
    LedgerError,
    RunLedger,
    capture_environment,
    sha256_bytes,
    sha256_file,
    sha256_json,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOCKFILE = Path(__file__).parents[2] / "uv.lock"
_REPO_DIR = Path(__file__).parents[2]  # ALIVE/ root (has .git)


def _make_ledger() -> RunLedger:
    """Return a minimal RunLedger with a real lockfile hash."""
    env = capture_environment(
        lockfile_path=_LOCKFILE,
        registered_seeds=(42, 7),
        repo_dir=_REPO_DIR,
    )
    return RunLedger(run_id="abc123", config_sha256="deadbeef" * 8, environment=env)


# ---------------------------------------------------------------------------
# sha256_file — chunked read
# ---------------------------------------------------------------------------


class TestSha256File:
    def test_matches_full_read(self, tmp_path: Path) -> None:
        """sha256_file must equal hashlib over the same bytes."""
        content = b"hello world" * 1000
        p = tmp_path / "test.bin"
        p.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert sha256_file(p) == expected

    def test_chunked_read_multiple_chunks(self, tmp_path: Path) -> None:
        """sha256_file with chunk_size=10 must match full-read hash (forces chunking)."""
        content = bytes(range(256)) * 100  # 25 600 bytes
        p = tmp_path / "chunked.bin"
        p.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert sha256_file(p, chunk_size=10) == expected

    def test_accepts_str_path(self, tmp_path: Path) -> None:
        p = tmp_path / "s.bin"
        p.write_bytes(b"abc")
        expected = hashlib.sha256(b"abc").hexdigest()
        assert sha256_file(str(p)) == expected

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.bin"
        p.write_bytes(b"")
        assert sha256_file(p) == hashlib.sha256(b"").hexdigest()


# ---------------------------------------------------------------------------
# sha256_bytes
# ---------------------------------------------------------------------------


class TestSha256Bytes:
    def test_basic(self) -> None:
        assert sha256_bytes(b"hello") == hashlib.sha256(b"hello").hexdigest()

    def test_empty(self) -> None:
        assert sha256_bytes(b"") == hashlib.sha256(b"").hexdigest()


# ---------------------------------------------------------------------------
# sha256_json
# ---------------------------------------------------------------------------


class TestSha256Json:
    def test_canonical_sort(self) -> None:
        """Key order must not affect the digest."""
        obj1 = {"b": 2, "a": 1}
        obj2 = {"a": 1, "b": 2}
        assert sha256_json(obj1) == sha256_json(obj2)

    def test_known_value(self) -> None:
        obj = {"a": 1}
        canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert sha256_json(obj) == expected

    def test_different_objects_differ(self) -> None:
        assert sha256_json({"a": 1}) != sha256_json({"a": 2})


# ---------------------------------------------------------------------------
# capture_environment
# ---------------------------------------------------------------------------


class TestCaptureEnvironment:
    def test_returns_environment_info(self) -> None:
        env = capture_environment(
            lockfile_path=_LOCKFILE,
            registered_seeds=(1, 2, 3),
            repo_dir=_REPO_DIR,
        )
        assert isinstance(env, EnvironmentInfo)

    def test_python_version(self) -> None:
        import platform

        env = capture_environment(
            lockfile_path=_LOCKFILE,
            registered_seeds=(1,),
            repo_dir=_REPO_DIR,
        )
        assert env.python_version == platform.python_version()

    def test_platform_field(self) -> None:
        import platform

        env = capture_environment(
            lockfile_path=_LOCKFILE,
            registered_seeds=(1,),
            repo_dir=_REPO_DIR,
        )
        assert env.platform == platform.platform()

    def test_lockfile_sha256(self) -> None:
        env = capture_environment(
            lockfile_path=_LOCKFILE,
            registered_seeds=(1,),
            repo_dir=_REPO_DIR,
        )
        expected = sha256_file(_LOCKFILE)
        assert env.lockfile_sha256 == expected

    def test_git_commit_real_repo(self) -> None:
        """In the ALIVE repo, git_commit must be a 40-hex string."""
        env = capture_environment(
            lockfile_path=_LOCKFILE,
            registered_seeds=(1,),
            repo_dir=_REPO_DIR,
        )
        assert re.fullmatch(r"[0-9a-f]{40}", env.git_commit), (
            f"Expected 40-hex git commit, got {env.git_commit!r}"
        )

    def test_git_commit_non_repo(self, tmp_path: Path) -> None:
        """In a directory that is not a git repo, git_commit must be 'UNKNOWN'."""
        env = capture_environment(
            lockfile_path=_LOCKFILE,
            registered_seeds=(1,),
            repo_dir=tmp_path,
        )
        assert env.git_commit == "UNKNOWN"

    def test_registered_seeds_stored(self) -> None:
        seeds = (10, 20, 30)
        env = capture_environment(
            lockfile_path=_LOCKFILE,
            registered_seeds=seeds,
            repo_dir=_REPO_DIR,
        )
        assert env.registered_seeds == seeds

    def test_no_timestamp_in_environment(self) -> None:
        """EnvironmentInfo fields must not contain a timestamp-like value."""
        env = capture_environment(
            lockfile_path=_LOCKFILE,
            registered_seeds=(1,),
            repo_dir=_REPO_DIR,
        )
        d = {
            "python_version": env.python_version,
            "platform": env.platform,
            "git_commit": env.git_commit,
            "lockfile_sha256": env.lockfile_sha256,
            "registered_seeds": list(env.registered_seeds),
        }
        serialised = json.dumps(d)
        # No epoch-like integer (10+ decimal digits) that looks like a Unix timestamp
        assert not re.search(r"\b1[67][0-9]{8,}\b", serialised), (
            "EnvironmentInfo appears to contain a timestamp-like value"
        )


# ---------------------------------------------------------------------------
# RunLedger — artifact registry
# ---------------------------------------------------------------------------


class TestRunLedgerArtifacts:
    def test_record_and_retrieve(self, tmp_path: Path) -> None:
        ledger = _make_ledger()
        ledger.record_artifact("raw_data", "abc123")
        assert ledger.artifact_sha("raw_data") == "abc123"

    def test_duplicate_artifact_name_raises(self, tmp_path: Path) -> None:
        ledger = _make_ledger()
        ledger.record_artifact("raw_data", "abc123")
        with pytest.raises(DuplicateArtifactError):
            ledger.record_artifact("raw_data", "def456")

    def test_duplicate_same_hash_raises(self, tmp_path: Path) -> None:
        """Names are write-once even if the hash is the same."""
        ledger = _make_ledger()
        ledger.record_artifact("raw_data", "abc123")
        with pytest.raises(DuplicateArtifactError):
            ledger.record_artifact("raw_data", "abc123")

    def test_artifact_sha_missing_raises_ledger_error(self, tmp_path: Path) -> None:
        ledger = _make_ledger()
        with pytest.raises(LedgerError):
            ledger.artifact_sha("nonexistent")

    def test_record_file_returns_hash(self, tmp_path: Path) -> None:
        ledger = _make_ledger()
        f = tmp_path / "data.bin"
        f.write_bytes(b"hello")
        h = ledger.record_file("raw_data", f)
        assert h == sha256_file(f)
        assert ledger.artifact_sha("raw_data") == h

    def test_record_file_duplicate_raises(self, tmp_path: Path) -> None:
        ledger = _make_ledger()
        f = tmp_path / "data.bin"
        f.write_bytes(b"hello")
        ledger.record_file("raw_data", f)
        with pytest.raises(DuplicateArtifactError):
            ledger.record_file("raw_data", f)


# ---------------------------------------------------------------------------
# Change detection / tamper detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "artifact_name",
    ["raw_data", "split_manifest", "feature_bank", "preprocessing_state", "result", "lockfile"],
)
class TestVerifyFile:
    def test_unchanged_file_returns_true(self, tmp_path: Path, artifact_name: str) -> None:
        ledger = _make_ledger()
        f = tmp_path / "artifact.bin"
        f.write_bytes(b"original content 12345")
        ledger.record_file(artifact_name, f)
        assert ledger.verify_file(artifact_name, f) is True

    def test_modified_file_returns_false(self, tmp_path: Path, artifact_name: str) -> None:
        ledger = _make_ledger()
        f = tmp_path / "artifact.bin"
        f.write_bytes(b"original content 12345")
        ledger.record_file(artifact_name, f)
        f.write_bytes(b"tampered!")
        assert ledger.verify_file(artifact_name, f) is False


class TestVerifyFileErrors:
    def test_unrecorded_name_raises_ledger_error(self, tmp_path: Path) -> None:
        ledger = _make_ledger()
        f = tmp_path / "x.bin"
        f.write_bytes(b"x")
        with pytest.raises(LedgerError):
            ledger.verify_file("never_recorded", f)


# ---------------------------------------------------------------------------
# Serialisation — determinism, no timestamp, round-trip
# ---------------------------------------------------------------------------


class TestRunLedgerSerialisation:
    def _build_matching_ledger(self, tmp_path: Path, data_file: Path) -> RunLedger:
        """Build a ledger from fixed inputs (env captured from the same repo dir)."""
        env = capture_environment(
            lockfile_path=_LOCKFILE,
            registered_seeds=(42, 7),
            repo_dir=_REPO_DIR,
        )
        ledger = RunLedger(run_id="testrun001", config_sha256="ff" * 32, environment=env)
        ledger.record_file("raw_data", data_file)
        return ledger

    def test_byte_identical_for_same_inputs(self, tmp_path: Path) -> None:
        """Two ledgers built from two independent env captures must serialise byte-identically.

        This proves that capture_environment() itself is timestamp-free, not merely
        that serialisation is deterministic when given the same env object.
        """
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(b"stable content")

        env_a = capture_environment(
            lockfile_path=_LOCKFILE,
            registered_seeds=(42, 7),
            repo_dir=_REPO_DIR,
        )
        ledger_a = RunLedger(run_id="testrun001", config_sha256="ff" * 32, environment=env_a)
        ledger_a.record_file("raw_data", data_file)

        env_b = capture_environment(
            lockfile_path=_LOCKFILE,
            registered_seeds=(42, 7),
            repo_dir=_REPO_DIR,
        )
        ledger_b = RunLedger(run_id="testrun001", config_sha256="ff" * 32, environment=env_b)
        ledger_b.record_file("raw_data", data_file)

        out_a = tmp_path / "a.json"
        out_b = tmp_path / "b.json"
        ledger_a.write(out_a)
        ledger_b.write(out_b)

        assert out_a.read_bytes() == out_b.read_bytes()

    def test_no_timestamp_in_serialised_output(self, tmp_path: Path) -> None:
        """The JSON written to disk must not contain any timestamp-like field."""
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(b"content")
        ledger = self._build_matching_ledger(tmp_path, data_file)
        out = tmp_path / "ledger.json"
        ledger.write(out)
        text = out.read_text()
        # Check that no epoch-like integer (10+ decimal digits) is present
        assert not re.search(r"\b1[67][0-9]{8,}\b", text), (
            "Serialised ledger appears to contain a timestamp-like value"
        )
        # Also check for common key names that would indicate a timestamp field
        lower_text = text.lower()
        for bad_key in ("timestamp", "created_at", "updated_at", "time"):
            assert bad_key not in lower_text, (
                f"Serialised ledger contains suspicious key {bad_key!r}"
            )

    def test_round_trip(self, tmp_path: Path) -> None:
        """RunLedger.read(write(x)).to_dict() must equal x.to_dict()."""
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(b"round trip test")
        ledger = self._build_matching_ledger(tmp_path, data_file)
        out = tmp_path / "ledger.json"
        ledger.write(out)
        loaded = RunLedger.read(out)
        assert loaded.to_dict() == ledger.to_dict()
        assert loaded == ledger  # exercise __eq__ directly

    def test_file_hash_equals_canonical_json_hash(self, tmp_path: Path) -> None:
        """sha256_file(written_ledger) must equal sha256_json(ledger.to_dict()).

        This is the audit-critical invariant: the on-disk file hash equals the
        canonical hash of its content, so the ledger can self-authenticate.
        """
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(b"audit invariant test")
        ledger = self._build_matching_ledger(tmp_path, data_file)
        out = tmp_path / "ledger.json"
        ledger.write(out)
        assert sha256_file(out) == sha256_json(ledger.to_dict())

    def test_to_dict_is_json_serialisable(self, tmp_path: Path) -> None:
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(b"x")
        ledger = self._build_matching_ledger(tmp_path, data_file)
        d = ledger.to_dict()
        # Should not raise
        json.dumps(d)

    def test_write_produces_valid_json(self, tmp_path: Path) -> None:
        data_file = tmp_path / "data.bin"
        data_file.write_bytes(b"y")
        ledger = self._build_matching_ledger(tmp_path, data_file)
        out = tmp_path / "ledger.json"
        ledger.write(out)
        parsed = json.loads(out.read_text())
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# ArtifactRecord dataclass
# ---------------------------------------------------------------------------


class TestArtifactRecord:
    def test_is_frozen(self) -> None:
        rec = ArtifactRecord(name="x", sha256="abc")
        with pytest.raises((TypeError, AttributeError)):
            rec.name = "y"  # type: ignore[misc]

    def test_fields(self) -> None:
        rec = ArtifactRecord(name="raw_data", sha256="deadbeef")
        assert rec.name == "raw_data"
        assert rec.sha256 == "deadbeef"
