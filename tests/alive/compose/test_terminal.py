"""Tests for alive.compose.terminal — single-owner terminal state machine (Task 2b-7).

TDD order: tests written first; the implementation must pass all of them.

This module is Task 7 of 8 for COMPOSE-K562-v1 Phase 2b. It is the SAFETY NET
around the one-time COMPOSE seal opening: once ``claim_access()`` is called (the
point the seal is about to be opened), EVERY exit path MUST leave exactly one
write-once terminal artifact — ``COMPLETE``, ``INVALID`` or ``ABORTED_AFTER_SEAL``.
A consumed seal with no durable terminal record is the worst-case failure; the
``try/except/finally`` boundary makes it impossible.

The crash-injection suite covers every stage BEFORE and AFTER access:

  * BEFORE access (no ``claim_access``) → a crash leaves NO terminal artifact
    (the seal was never opened);
  * AFTER access (``claim_access`` done) → any crash, or even a silent return,
    leaves exactly one ``ABORTED_AFTER_SEAL`` artifact.

Raw outcome matrices may NEVER appear in a report, in provenance, or in scrubbed
exception text. The guard rejects arrays / nested raw matrices BEFORE any write
and scrubs exception messages before they are persisted.

ACTIVATION BLOCKED: pure synthetic / tiny-fixture values only; NO real Norman,
NO seal open, NO sealed-outcome read.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from alive.compose.terminal import (
    Phase2bTerminal,
    TerminalError,
    TerminalState,
)
from alive.provenance import (
    EnvironmentInfo,
    RunLedger,
)

# ---------------------------------------------------------------------------
# Synthetic fixtures — tiny, deterministic, no real data.
# ---------------------------------------------------------------------------


def _environment() -> EnvironmentInfo:
    """A deterministic environment snapshot (no wall-clock)."""
    return EnvironmentInfo(
        python_version="3.12.0",
        platform="test-platform",
        git_commit="0" * 40,
        lockfile_sha256="lock-sha-eeee",
        registered_seeds=(0, 1, 2),
    )


def _ledger() -> RunLedger:
    """A fresh write-once ledger for a run."""
    return RunLedger(
        run_id="run-aaaa",
        config_sha256="config-sha-bbbb",
        environment=_environment(),
    )


def _payload() -> dict:
    """A small, outcome-free report payload (verdict-style summary only)."""
    return {
        "protocol": "COMPOSE-K562-v1",
        "verdict": "NO_DISTINCT_WIN",
        "regime_double_metric": 0.42,
        "regime_single_metric": 0.31,
        "method_roster": ["operator", "additive", "gears"],
        "preflight_checksums": {"pair_manifest": "a" * 64},
    }


def _terminal(tmp_path: Path, *, audit_path: Path | None = None) -> Phase2bTerminal:
    """Construct a terminal state machine over a fresh run dir."""
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    return Phase2bTerminal(run_dir, ledger=_ledger(), audit_path=audit_path)


def _terminal_artifact_paths(run_dir: Path) -> list[Path]:
    """Every candidate terminal artifact path in the run dir."""
    return [
        run_dir / Phase2bTerminal.COMPLETE_ARTIFACT,
        run_dir / Phase2bTerminal.INVALID_ARTIFACT,
        run_dir / Phase2bTerminal.ABORTED_ARTIFACT,
    ]


def _existing_terminal_artifacts(run_dir: Path) -> list[Path]:
    return [p for p in _terminal_artifact_paths(run_dir) if p.exists()]


# ---------------------------------------------------------------------------
# Happy path — COMPLETE
# ---------------------------------------------------------------------------


def test_complete_happy_path_writes_canonical_json_and_ledger(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    run_dir = term.run_dir

    term.acquire()
    assert term.state is TerminalState.PREPARED
    term.claim_access()
    assert term.state is TerminalState.ACCESS_CLAIMED

    payload = _payload()
    term.complete(payload)
    assert term.state is TerminalState.COMPLETE

    artifact = run_dir / Phase2bTerminal.COMPLETE_ARTIFACT
    assert artifact.exists()

    # Canonical JSON: sort_keys + compact separators. The body carries the
    # payload plus a terminal_state marker.
    text = artifact.read_text(encoding="utf-8")
    body = json.loads(text)
    expected = dict(payload)
    expected["terminal_state"] = TerminalState.COMPLETE.value
    assert body == expected
    assert text == json.dumps(body, sort_keys=True, separators=(",", ":"))

    # Ledger entry appended AND verifies against the file on disk.
    sha = term.ledger.artifact_sha(Phase2bTerminal.COMPLETE_ARTIFACT)
    assert isinstance(sha, str) and len(sha) == 64
    assert term.ledger.verify_file(Phase2bTerminal.COMPLETE_ARTIFACT, artifact) is True


def test_complete_is_write_once_second_complete_raises(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()
    term.complete(_payload())

    # A second terminal write must fail (state guard fires first).
    with pytest.raises(TerminalError):
        term.complete(_payload())

    # Exactly one terminal artifact on disk.
    assert len(_existing_terminal_artifacts(term.run_dir)) == 1


def test_complete_only_valid_from_access_claimed(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    # complete() before claim_access() is illegal — seal not yet opened.
    with pytest.raises(TerminalError):
        term.complete(_payload())
    assert _existing_terminal_artifacts(term.run_dir) == []


# ---------------------------------------------------------------------------
# INVALID path
# ---------------------------------------------------------------------------


def test_invalid_path_writes_artifact_and_ledger(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    run_dir = term.run_dir
    term.acquire()
    term.claim_access()

    term.invalid("post-access checksum mismatch", evidence={"observed": "x", "expected": "y"})
    assert term.state is TerminalState.INVALID

    artifact = run_dir / Phase2bTerminal.INVALID_ARTIFACT
    assert artifact.exists()
    body = json.loads(artifact.read_text(encoding="utf-8"))
    assert body["terminal_state"] == TerminalState.INVALID.value
    assert body["reason"] == "post-access checksum mismatch"
    assert body["evidence"] == {"observed": "x", "expected": "y"}

    assert term.ledger.verify_file(Phase2bTerminal.INVALID_ARTIFACT, artifact) is True


def test_invalid_only_valid_from_access_claimed(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    with pytest.raises(TerminalError):
        term.invalid("too early")
    assert _existing_terminal_artifacts(term.run_dir) == []


# ---------------------------------------------------------------------------
# ABORTED path (protect boundary)
# ---------------------------------------------------------------------------


def test_aborted_via_protect_records_class_and_stage_and_reraises(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    run_dir = term.run_dir
    term.acquire()
    term.claim_access()

    class ScoringBoom(RuntimeError):
        pass

    with pytest.raises(ScoringBoom):
        with term.protect(stage="scoring"):
            raise ScoringBoom("kaboom during scoring")

    assert term.state is TerminalState.ABORTED_AFTER_SEAL
    artifact = run_dir / Phase2bTerminal.ABORTED_ARTIFACT
    assert artifact.exists()
    body = json.loads(artifact.read_text(encoding="utf-8"))
    assert body["terminal_state"] == TerminalState.ABORTED_AFTER_SEAL.value
    assert body["exception_class"] == "ScoringBoom"
    assert body["stage"] == "scoring"
    # Scrubbed message present; benign text preserved.
    assert "kaboom during scoring" in body["message"]
    assert term.ledger.verify_file(Phase2bTerminal.ABORTED_ARTIFACT, artifact) is True


def test_aborted_records_preflight_checksums_not_raw_outcomes(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()
    checksums = {"pair_manifest": "a" * 64, "data_card": "b" * 64}

    with pytest.raises(ValueError):
        with term.protect(stage="scoring", preflight_checksums=checksums):
            raise ValueError("benign failure")

    body = json.loads((term.run_dir / Phase2bTerminal.ABORTED_ARTIFACT).read_text())
    assert body["preflight_checksums"] == checksums
    # No raw outcome content anywhere in the artifact.
    assert "preflight_checksums" in body


# ---------------------------------------------------------------------------
# finally-guarantee — a silent return still burns a terminal artifact
# ---------------------------------------------------------------------------


def test_finally_guarantee_silent_return_writes_aborted(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()

    # Exit the protected block WITHOUT writing a terminal (simulate a silent
    # early return where no complete/invalid was reached).
    with term.protect(stage="scoring"):
        pass  # no exception, no terminal write

    assert term.state is TerminalState.ABORTED_AFTER_SEAL
    artifact = term.run_dir / Phase2bTerminal.ABORTED_ARTIFACT
    assert artifact.exists()
    body = json.loads(artifact.read_text(encoding="utf-8"))
    assert body["stage"] == "no-terminal-written"
    assert body["exception_class"] == "NoTerminalWritten"


def test_protect_complete_inside_block_does_not_double_write(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()

    with term.protect(stage="scoring"):
        term.complete(_payload())

    # The terminal was already COMPLETE; finally must NOT overwrite/append.
    assert term.state is TerminalState.COMPLETE
    assert len(_existing_terminal_artifacts(term.run_dir)) == 1
    assert (term.run_dir / Phase2bTerminal.COMPLETE_ARTIFACT).exists()


def test_run_protected_helper_aborts_on_exception(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()

    def _boom() -> None:
        raise KeyError("nested boom")

    with pytest.raises(KeyError):
        term.run_protected(_boom, stage="materialise")

    assert term.state is TerminalState.ABORTED_AFTER_SEAL
    body = json.loads((term.run_dir / Phase2bTerminal.ABORTED_ARTIFACT).read_text())
    assert body["exception_class"] == "KeyError"
    assert body["stage"] == "materialise"


# ---------------------------------------------------------------------------
# Crash BEFORE access — the seal was never opened, so NO terminal artifact
# ---------------------------------------------------------------------------


def test_crash_before_access_writes_no_terminal_artifact(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    assert term.state is TerminalState.PREPARED

    # A crash before claim_access: the seal was never opened. The protect
    # boundary must refuse to run pre-claim, and no terminal artifact appears.
    with pytest.raises(TerminalError):
        with term.protect(stage="preflight"):
            raise RuntimeError("crash before access")

    # No terminal artifact written — a closed seal needs no terminal record.
    assert _existing_terminal_artifacts(term.run_dir) == []


def test_run_protected_refuses_before_access(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    with pytest.raises(TerminalError):
        term.run_protected(lambda: None, stage="preflight")
    assert _existing_terminal_artifacts(term.run_dir) == []


# ---------------------------------------------------------------------------
# Refuse existing terminal artifact / prior audit / concurrent lock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "artifact_name",
    [
        Phase2bTerminal.COMPLETE_ARTIFACT,
        Phase2bTerminal.INVALID_ARTIFACT,
        Phase2bTerminal.ABORTED_ARTIFACT,
    ],
)
def test_acquire_refuses_pre_existing_terminal_artifact(tmp_path: Path, artifact_name: str) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / artifact_name).write_text("{}", encoding="utf-8")

    term = Phase2bTerminal(run_dir, ledger=_ledger())
    with pytest.raises(TerminalError):
        term.acquire()


def test_acquire_refuses_prior_audit(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text(json.dumps({"run_id": "prior", "pair_ids": []}) + "\n", encoding="utf-8")

    term = Phase2bTerminal(run_dir, ledger=_ledger(), audit_path=audit_path)
    with pytest.raises(TerminalError):
        term.acquire()


def test_acquire_allows_empty_audit_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text("", encoding="utf-8")  # exists but no records

    term = Phase2bTerminal(run_dir, ledger=_ledger(), audit_path=audit_path)
    term.acquire()  # must not raise
    assert term.state is TerminalState.PREPARED


def test_exclusive_lock_blocks_second_owner(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    first = Phase2bTerminal(run_dir, ledger=_ledger())
    first.acquire()  # holds the lock

    second = Phase2bTerminal(run_dir, ledger=_ledger())
    with pytest.raises(TerminalError):
        second.acquire()  # lock already held


def test_double_acquire_same_owner_raises(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    with pytest.raises(TerminalError):
        term.acquire()


def test_claim_access_only_from_prepared(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    # Not yet acquired (state is the initial pre-PREPARED state).
    with pytest.raises(TerminalError):
        term.claim_access()


# ---------------------------------------------------------------------------
# No raw outcomes — reject arrays / nested matrices BEFORE writing
# ---------------------------------------------------------------------------


def test_complete_rejects_numpy_array_payload(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()

    payload = {"verdict": "x", "leaked": np.arange(10)}
    with pytest.raises(TerminalError):
        term.complete(payload)

    # Rejected BEFORE writing: state unchanged, no terminal artifact.
    assert term.state is TerminalState.ACCESS_CLAIMED
    assert _existing_terminal_artifacts(term.run_dir) == []


def test_complete_rejects_nested_raw_cell_matrix(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()

    # A nested raw cell/observation matrix (list of equal-length numeric rows).
    raw_matrix = [[float(i + j) for j in range(8)] for i in range(8)]
    payload = {"verdict": "x", "deep": {"cells": raw_matrix}}
    with pytest.raises(TerminalError):
        term.complete(payload)

    assert _existing_terminal_artifacts(term.run_dir) == []


def test_complete_rejects_oversized_numeric_list(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()

    payload = {"verdict": "x", "flat": list(range(10_000))}
    with pytest.raises(TerminalError):
        term.complete(payload)

    assert _existing_terminal_artifacts(term.run_dir) == []


def test_invalid_rejects_array_evidence(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()

    with pytest.raises(TerminalError):
        term.invalid("reason", evidence={"leaked": np.zeros(5)})

    assert _existing_terminal_artifacts(term.run_dir) == []


def test_small_numeric_metrics_are_allowed(tmp_path: Path) -> None:
    # A handful of scalar metrics must NOT trip the raw-outcome guard.
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()
    term.complete({"a": 1.0, "b": 2.0, "c": [0.1, 0.2, 0.3]})
    assert term.state is TerminalState.COMPLETE


def test_aborted_scrubs_array_in_exception_message(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()

    big = np.arange(64).tolist()
    msg = f"failure with embedded outcomes {big}"

    with pytest.raises(ValueError):
        with term.protect(stage="scoring"):
            raise ValueError(msg)

    body = json.loads((term.run_dir / Phase2bTerminal.ABORTED_ARTIFACT).read_text())
    scrubbed = body["message"]
    # The raw array digits/brackets are scrubbed out of the persisted text.
    assert "[" not in scrubbed
    assert "63" not in scrubbed
    assert "outcomes" in scrubbed  # benign words survive
    # And the artifact as a whole carries no embedded array.
    raw_text = (term.run_dir / Phase2bTerminal.ABORTED_ARTIFACT).read_text()
    assert "63, 62" not in raw_text and "62, 63" not in raw_text


# ---------------------------------------------------------------------------
# Atomicity hygiene — no leftover temp files, destination never overwritten
# ---------------------------------------------------------------------------


def test_no_leftover_temp_files_after_complete(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()
    term.complete(_payload())

    leftovers = list(term.run_dir.glob("*.tmp")) + list(term.run_dir.glob(".*.tmp"))
    assert leftovers == []


def test_terminal_artifact_destination_never_overwritten(tmp_path: Path) -> None:
    # Pre-create the COMPLETE destination, then a complete() must refuse to clobber.
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()

    # Simulate a stale COMPLETE artifact appearing between claim and complete.
    sentinel = term.run_dir / Phase2bTerminal.COMPLETE_ARTIFACT
    sentinel.write_text("STALE", encoding="utf-8")

    with pytest.raises((FileExistsError, TerminalError)):
        term.complete(_payload())

    # The pre-existing content was NOT overwritten.
    assert sentinel.read_text(encoding="utf-8") == "STALE"


# ---------------------------------------------------------------------------
# Ledger-after-verify ordering — no ledger entry without a verified file
# ---------------------------------------------------------------------------


def test_no_ledger_entry_when_payload_rejected_before_write(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()

    with pytest.raises(TerminalError):
        term.complete({"leaked": np.arange(5)})

    # The guard fired before any write → no terminal artifact, no ledger entry.
    from alive.provenance import LedgerError

    with pytest.raises(LedgerError):
        term.ledger.artifact_sha(Phase2bTerminal.COMPLETE_ARTIFACT)


def test_ledger_entry_only_after_file_exists_and_verifies(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()
    term.complete(_payload())

    artifact = term.run_dir / Phase2bTerminal.COMPLETE_ARTIFACT
    # The recorded sha equals the on-disk file sha (file existed + verified first).
    from alive.provenance import sha256_file

    assert term.ledger.artifact_sha(Phase2bTerminal.COMPLETE_ARTIFACT) == sha256_file(artifact)


# ---------------------------------------------------------------------------
# Exactly one terminal artifact per run (cross-state)
# ---------------------------------------------------------------------------


def test_invalid_then_complete_is_blocked(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()
    term.invalid("first terminal")

    with pytest.raises(TerminalError):
        term.complete(_payload())
    assert len(_existing_terminal_artifacts(term.run_dir)) == 1


def test_aborted_then_no_further_terminal(tmp_path: Path) -> None:
    term = _terminal(tmp_path)
    term.acquire()
    term.claim_access()
    with pytest.raises(RuntimeError):
        with term.protect(stage="scoring"):
            raise RuntimeError("boom")

    # After ABORTED, complete() is rejected.
    with pytest.raises(TerminalError):
        term.complete(_payload())
    assert len(_existing_terminal_artifacts(term.run_dir)) == 1


# ---------------------------------------------------------------------------
# Double-fault in the protection boundary — aborted() itself fails on exit
# ---------------------------------------------------------------------------


def _last_resort_markers(run_dir: Path) -> list[Path]:
    """Every best-effort last-resort finalization-failure marker in the run dir."""
    return sorted(run_dir.glob("terminal_abort_failure-*.json"))


def _durable_terminal_markers(run_dir: Path) -> list[Path]:
    """Every durable terminal marker: real terminal artifacts plus last-resort ones."""
    return _existing_terminal_artifacts(run_dir) + _last_resort_markers(run_dir)


def test_protect_preserves_original_exception_when_abort_write_fails(tmp_path: Path) -> None:
    # The abort destination already exists on disk, so aborted() -> atomic_write_once
    # raises FileExistsError -> TerminalError inside __exit__. The original exception
    # must STILL be what propagates (not the TerminalError/FileExistsError), and a
    # durable last-resort marker must exist (never zero terminal markers).
    term = _terminal(tmp_path)
    run_dir = term.run_dir
    term.acquire()
    term.claim_access()

    # Pre-create the canonical abort artifact so aborted() cannot install its own.
    (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).write_text("STALE-ABORT", encoding="utf-8")

    class OriginalBoom(RuntimeError):
        pass

    with pytest.raises(OriginalBoom) as excinfo:
        with term.protect(stage="scoring"):
            raise OriginalBoom("the real failure")

    # The ORIGINAL exception type/message is what the caller sees.
    assert isinstance(excinfo.value, OriginalBoom)
    assert "the real failure" in str(excinfo.value)
    assert not isinstance(excinfo.value, TerminalError)

    # A durable last-resort marker exists; we are NOT left with zero terminal markers.
    assert _durable_terminal_markers(run_dir), "no durable terminal marker on disk"
    markers = _last_resort_markers(run_dir)
    assert markers, "best-effort last-resort marker not written"
    # The stale pre-existing abort artifact was NOT overwritten.
    assert (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).read_text() == "STALE-ABORT"


def test_protect_preserves_original_exception_when_checksums_are_raw(tmp_path: Path) -> None:
    # preflight_checksums carrying a raw ndarray makes aborted()'s guard reject —
    # but because aborted() drops unsafe checksums, the abort still writes. Force a
    # genuine double-fault by ALSO pre-creating the abort destination, and confirm
    # the original exception propagates with a durable marker present.
    term = _terminal(tmp_path)
    run_dir = term.run_dir
    term.acquire()
    term.claim_access()
    (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).write_text("STALE", encoding="utf-8")

    class OriginalBoom(ValueError):
        pass

    bad_checksums = {"pair_manifest": np.arange(10)}
    with pytest.raises(OriginalBoom):
        with term.protect(stage="scoring", preflight_checksums=bad_checksums):
            raise OriginalBoom("real failure with bad checksums")

    assert _durable_terminal_markers(run_dir), "no durable terminal marker on disk"


def test_aborted_direct_with_raw_checksums_omits_unsafe_and_does_not_raise(tmp_path: Path) -> None:
    # aborted() called directly with preflight_checksums containing a raw ndarray
    # must STILL write a valid ABORTED_AFTER_SEAL artifact (checksums omitted-unsafe)
    # and must NOT raise — the core abort record cannot be blocked by a bad field.
    term = _terminal(tmp_path)
    run_dir = term.run_dir
    term.acquire()
    term.claim_access()

    term.aborted(
        exception=RuntimeError("core abort message"),
        stage="scoring",
        preflight_checksums={"pair_manifest": np.arange(64)},
    )

    assert term.state is TerminalState.ABORTED_AFTER_SEAL
    artifact = run_dir / Phase2bTerminal.ABORTED_ARTIFACT
    assert artifact.exists()
    body = json.loads(artifact.read_text(encoding="utf-8"))
    assert body["terminal_state"] == TerminalState.ABORTED_AFTER_SEAL.value
    assert body["exception_class"] == "RuntimeError"
    assert body["stage"] == "scoring"
    # The unsafe checksum block was dropped, not embedded.
    assert body["preflight_checksums"] == "OMITTED_UNSAFE"
    # The artifact still verifies in the ledger.
    assert term.ledger.verify_file(Phase2bTerminal.ABORTED_ARTIFACT, artifact) is True


def test_clean_silent_return_raises_terminal_error_when_abort_write_fails(tmp_path: Path) -> None:
    # Clean exit, state still ACCESS_CLAIMED (silent return), but the safety-net
    # abort write is forced to fail (abort destination pre-exists). There is NO
    # original exception to preserve → a TerminalError must be raised, and a
    # last-resort marker must exist.
    term = _terminal(tmp_path)
    run_dir = term.run_dir
    term.acquire()
    term.claim_access()
    (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).write_text("STALE", encoding="utf-8")

    with pytest.raises(TerminalError):
        with term.protect(stage="scoring"):
            pass  # silent return, no terminal written

    assert _last_resort_markers(run_dir), "best-effort last-resort marker not written"
