"""Tests for the ``phase2b`` subcommand orchestration (spec §3.3 / §7.1).

Written FIRST per TDD. ``phase2b`` is the LAST of the three driver subcommands
(canonical order ``phase2a → preflight → phase2b``) and the SOLE place in the
whole driver that constructs a sealed
:class:`~alive.compose.outcome_store.ComposeOutcomeStore` (spec §4). It asserts
the phase2b entry roster, acquires the driver lock, re-verifies the frozen bundle
+ re-read ledger via the outcome-free preflight gate, re-verifies the installed
seal-confirmation manifest against a ``--confirm-seal`` token (the FULL
``confirmation_checksum``, never the run id), and — ONLY after confirmation —
integrity-checks and retains the sealed source descriptor, constructs the sealed
FIXTURE store with
``audit_path == run_dir/audit.jsonl``, runs the bounded synthetic
``run_phase2b_fixture`` (validating source obs only after the durable claim),
independently re-reads the durable commit marker, and
maps the terminal state to an exit code.

These tests run the REAL ``phase2a → preflight → phase2b`` chain on the committed
fixture (no mocks), plus a spy asserting the sealed store is constructed EXACTLY
once on the phase2b code path (§4 single-creation-point invariant).

Coverage (the four brief scenarios + guards):

  1. full fixture path → returns 0, a ``COMPLETE`` terminal + a verified durable
     commit marker are present, and the sealed store was constructed with
     ``audit_path == run_dir/audit.jsonl`` (the recover-critical path);
  2. omitting preflight (no confirmation manifest) → the phase2b entry roster
     fails closed BEFORE any store construction (no audit, no terminal);
  3. a run-id-only ``--confirm-seal`` token → confirmation fails closed BEFORE
     any store construction (no audit, no terminal);
  4. swapping two pairs' obs rows in the pair index → the post-claim
     obs-alignment validator burns the audit and records ``ABORTED_AFTER_SEAL``;
  plus: the sealed store is constructed EXACTLY once (§4).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import alive.compose.driver.phase2b_cmd as phase2b_mod
import alive.compose.outcome_store as outcome_store_mod
from alive.compose.driver.confirmation import ConfirmationError
from alive.compose.driver.fixture_builder import build_compose_fixture
from alive.compose.driver.phase2a_cmd import run_phase2a_subcommand
from alive.compose.driver.phase2b_cmd import (
    PHASE2B_COMPLETE_EXIT,
    PHASE2B_NONCOMPLETE_EXIT,
    Phase2bSubcommandError,
    run_phase2b_subcommand,
)
from alive.compose.driver.preflight_cmd import run_preflight_subcommand
from alive.compose.driver.run_dir_state import RunDirStateError
from alive.compose.durable import (
    COMMIT_CHECKSUM_FIELD,
    DURABLE_COMMIT_FILENAME,
    SEAL_AUDIT_FILENAME,
    DurableLedgerError,
)
from alive.compose.outcome_store import ComposeSealingError
from alive.compose.terminal import Phase2bTerminal
from alive.provenance import sha256_json

_CONFIRMATION = "seal_confirmation_manifest.json"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _run_preseal(tmp_path: Path):
    """Build the fixture, run phase2a then preflight → return the carrier fx."""
    fx = build_compose_fixture(tmp_path)
    assert run_phase2a_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir) == 0
    assert run_preflight_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir) == 0
    return fx


def _confirmation_token(run_dir: Path) -> str:
    """The FULL ``confirmation_checksum`` of the installed manifest (the token)."""
    manifest = json.loads((run_dir / _CONFIRMATION).read_bytes())
    return manifest["confirmation_checksum"]


def _terminal_artifacts(run_dir: Path) -> list[Path]:
    return [
        p
        for p in (
            run_dir / Phase2bTerminal.COMPLETE_ARTIFACT,
            run_dir / Phase2bTerminal.INVALID_ARTIFACT,
            run_dir / Phase2bTerminal.ABORTED_ARTIFACT,
        )
        if p.exists()
    ]


def _no_seal_side_effects(run_dir: Path) -> None:
    """Assert a rejected pre-seal run consumed no seal and wrote no terminal."""
    assert not (run_dir / SEAL_AUDIT_FILENAME).exists()
    assert _terminal_artifacts(run_dir) == []
    assert not (run_dir / DURABLE_COMMIT_FILENAME).exists()


# --------------------------------------------------------------------------- #
# Scenario 1: full fixture path → 0, COMPLETE + durable marker, run-bound audit
# --------------------------------------------------------------------------- #
def test_full_fixture_path_completes_with_run_bound_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)

    # Spy every ComposeOutcomeStore construction to capture the audit_path the
    # sealed store is built with (§4: exactly one construction on this path).
    seen_audit_paths: list[Path] = []
    real_init = outcome_store_mod.ComposeOutcomeStore.__init__

    def _spy_init(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        real_init(self, *args, **kwargs)
        seen_audit_paths.append(Path(self._audit_path))

    monkeypatch.setattr(outcome_store_mod.ComposeOutcomeStore, "__init__", _spy_init)

    rc = run_phase2b_subcommand(
        fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
    )
    assert rc == PHASE2B_COMPLETE_EXIT

    # The sealed store was constructed EXACTLY once, with the recover-critical
    # audit path (spec §3.3 / §3.4: recover reconstructs THIS exact path).
    assert seen_audit_paths == [fx.run_dir / SEAL_AUDIT_FILENAME]

    # A COMPLETE terminal + a durable commit marker are present.
    assert _terminal_artifacts(fx.run_dir) == [fx.run_dir / Phase2bTerminal.COMPLETE_ARTIFACT]
    marker_path = fx.run_dir / DURABLE_COMMIT_FILENAME
    assert marker_path.is_file()
    assert (fx.run_dir / SEAL_AUDIT_FILENAME).is_file()

    # The independently re-read marker binds its own self-checksum + every file.
    marker = json.loads(marker_path.read_bytes())
    core = {k: v for k, v in marker.items() if k != COMMIT_CHECKSUM_FIELD}
    assert sha256_json(core) == marker[COMMIT_CHECKSUM_FIELD]
    for key in ("terminal", "registered_summary", "final_ledger", "pre_access_ledger"):
        entry = marker[key]
        on_disk = hashlib.sha256((fx.run_dir / entry["filename"]).read_bytes()).hexdigest()
        assert on_disk == entry["sha256"]


# --------------------------------------------------------------------------- #
# Scenario: the sealed store is constructed EXACTLY once on the phase2b path (§4)
# --------------------------------------------------------------------------- #
def test_outcome_store_constructed_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)

    count = {"n": 0}
    real_init = outcome_store_mod.ComposeOutcomeStore.__init__

    def _counting_init(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        count["n"] += 1
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(outcome_store_mod.ComposeOutcomeStore, "__init__", _counting_init)

    rc = run_phase2b_subcommand(
        fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
    )
    assert rc == PHASE2B_COMPLETE_EXIT
    assert count["n"] == 1


# --------------------------------------------------------------------------- #
# Scenario 2: omit preflight → phase2b entry roster fails closed (pre-store)
# --------------------------------------------------------------------------- #
def test_missing_confirmation_manifest_rejects_before_store(tmp_path: Path) -> None:
    fx = build_compose_fixture(tmp_path)
    assert run_phase2a_subcommand(fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir) == 0
    # NO preflight → no seal_confirmation_manifest.json.
    assert not (fx.run_dir / _CONFIRMATION).exists()

    with pytest.raises(RunDirStateError):
        run_phase2b_subcommand(
            fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token="x" * 64
        )
    _no_seal_side_effects(fx.run_dir)


# --------------------------------------------------------------------------- #
# Scenario 3: a run-id-only token → confirmation fails closed (pre-store)
# --------------------------------------------------------------------------- #
def test_run_id_only_token_rejects_before_store(tmp_path: Path) -> None:
    fx = _run_preseal(tmp_path)

    # The run id is trivially recomputable; it is NOT the full confirmation
    # checksum, so the --confirm-seal token guard must fail closed.
    with pytest.raises(ConfirmationError):
        run_phase2b_subcommand(
            fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=fx.run_id
        )
    _no_seal_side_effects(fx.run_dir)


# --------------------------------------------------------------------------- #
# Scenario 4: swapped obs rows → post-claim validator aborts a consumed seal
# --------------------------------------------------------------------------- #
def test_swapped_pair_rows_abort_after_durable_claim(tmp_path: Path) -> None:
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)

    # Swap two pairs' row blocks in the pair index (the source file + its digest
    # are untouched, so the integrity check passes) — now each swapped pair's
    # obs perturbation label canonicalizes to the OTHER pair, which the
    # post-confirmation obs-alignment validator must reject.
    pair_index = fx.sealed_outcome["pair_index"]
    keys = list(pair_index)
    a, b = keys[0], keys[1]
    pair_index[a], pair_index[b] = pair_index[b], pair_index[a]

    rc = run_phase2b_subcommand(
        fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
    )

    assert rc == PHASE2B_NONCOMPLETE_EXIT
    audit_path = fx.run_dir / SEAL_AUDIT_FILENAME
    assert len(audit_path.read_text(encoding="utf-8").splitlines()) == 1
    assert _terminal_artifacts(fx.run_dir) == [fx.run_dir / Phase2bTerminal.ABORTED_ARTIFACT]
    aborted = json.loads((fx.run_dir / Phase2bTerminal.ABORTED_ARTIFACT).read_bytes())
    assert aborted["terminal_state"] == "ABORTED_AFTER_SEAL"
    assert aborted["sealed_access_count"] == 1
    assert aborted["exception_class"] == "ComposeSealingError"
    assert (fx.run_dir / DURABLE_COMMIT_FILENAME).is_file()


def test_verified_descriptor_survives_source_path_replacement(tmp_path: Path) -> None:
    """The bytes later opened are the hashed inode, not a replaced pathname."""
    source_path = tmp_path / "source.h5ad"
    original = b"original-sealed-source"
    replacement = b"replacement-source"
    source_path.write_bytes(original)
    replacement_path = tmp_path / "replacement.h5ad"
    replacement_path.write_bytes(replacement)

    expected_sha = hashlib.sha256(original).hexdigest()
    with phase2b_mod._open_verified_sealed_source(source_path, expected_sha) as descriptor_path:
        replacement_path.replace(source_path)
        assert source_path.read_bytes() == replacement
        assert descriptor_path.read_bytes() == original


# --------------------------------------------------------------------------- #
# Guard: a tampered sealed source (wrong bytes) fails the integrity check
# --------------------------------------------------------------------------- #
def test_tampered_source_bytes_fail_integrity_before_store(tmp_path: Path) -> None:
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)

    # Corrupt the source bytes; its declared digest no longer matches, so the
    # O_NOFOLLOW integrity check must fail closed before any store construction.
    Path(fx.sealed_outcome["source_path"]).write_bytes(b"not-an-h5ad")

    with pytest.raises(Phase2bSubcommandError):
        run_phase2b_subcommand(
            fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
        )
    _no_seal_side_effects(fx.run_dir)


# --------------------------------------------------------------------------- #
# Guard: exit code maps non-COMPLETE to 30 (an already-consumed audit rejects)
# --------------------------------------------------------------------------- #
def test_reject_when_audit_already_present(tmp_path: Path) -> None:
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)

    # A pre-existing (non-empty) audit destination means the seal was (or is being)
    # consumed elsewhere; phase2b must fail closed before constructing a store. The
    # phase2b entry roster forbids audit.jsonl outright.
    #
    # 2026-08-03: the FAIL-CLOSED requirement is unchanged and still checked below --
    # no store is constructed. What changed is the SIGNAL. This used to raise
    # RunDirStateError, which the CLI maps to exit 10, "pre-seal rejection, the seal
    # was NOT consumed" -- contradicting this test's own first sentence. A burned
    # audit with no terminal is exactly the state ``_assert_recover_roster`` ACCEPTS
    # as post-seal, so phase2b now reports 30 and points at ``recover``. The
    # concurrent-consumption case ("or is being") is the driver lock's job, not the
    # roster's, and is covered separately.
    (fx.run_dir / SEAL_AUDIT_FILENAME).write_text("{}\n", encoding="utf-8")

    seen_stores: list[object] = []
    real_init = outcome_store_mod.ComposeOutcomeStore.__init__

    def _spy_init(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        seen_stores.append(self)
        real_init(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(outcome_store_mod.ComposeOutcomeStore, "__init__", _spy_init)
        rc = run_phase2b_subcommand(
            fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
        )

    assert rc == PHASE2B_NONCOMPLETE_EXIT
    assert seen_stores == [], "phase2b constructed a sealed store despite a burned audit"


# --------------------------------------------------------------------------- #
# Guard: a PRESENT-but-CORRUPT durable marker at step 6 is a POST-seal failure —
# it must RETURN the non-COMPLETE exit (30), not RAISE. Step 6 runs AFTER the
# seal is consumed (step 5 opened it, wrote a COMPLETE terminal + audit); a raise
# here would let the CLI mislabel a genuinely-consumed-seal failure as pre-seal
# exit 10 ("no seal consumed"). The ABSENT-marker case already returns 30 via
# pass-through, so the present-but-corrupt case must be made symmetric.
# --------------------------------------------------------------------------- #
def test_corrupt_durable_marker_returns_thirty_post_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)

    # Wrap the real fixture dispatch (step 5) so the seal is genuinely consumed —
    # a COMPLETE terminal + audit + a real durable marker are written — THEN flip
    # a recorded file-SHA in the marker (leaving the self-checksum stale) so the
    # independent step-6 re-read sees a present-but-corrupt marker.
    real_fixture = phase2b_mod.run_phase2b_fixture

    def _dispatch_then_corrupt(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        result = real_fixture(*args, **kwargs)
        marker_path = fx.run_dir / DURABLE_COMMIT_FILENAME
        marker = json.loads(marker_path.read_bytes())
        marker["terminal"]["sha256"] = "0" * 64  # corrupt a recorded file SHA
        marker_path.write_bytes(
            json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        return result

    monkeypatch.setattr(phase2b_mod, "run_phase2b_fixture", _dispatch_then_corrupt)

    rc = run_phase2b_subcommand(
        fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
    )

    # RETURNS 30 (does not raise) — a genuinely-consumed-seal post-seal failure.
    assert rc == PHASE2B_NONCOMPLETE_EXIT
    # The seal WAS consumed: a COMPLETE terminal + audit are present (step 5 ran).
    assert _terminal_artifacts(fx.run_dir) == [fx.run_dir / Phase2bTerminal.COMPLETE_ARTIFACT]
    assert (fx.run_dir / SEAL_AUDIT_FILENAME).is_file()
    # A single stderr diagnostic names the failure; stdout stays clean.
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Phase2bSubcommandError" in captured.err


# --------------------------------------------------------------------------- #
# Guard: a library RAISE from step 5 AFTER the seal is consumed is a POST-seal
# failure — it must RETURN the non-COMPLETE exit (30), never propagate. The abort
# path re-raises the boundary exception (e.g. ComposeSealingError) and a normal-
# path durable-finalize failure raises DurableLedgerError; unwrapped, the CLI
# would mislabel the FIRST as pre-seal exit 10 ("no seal consumed") and crash on
# the SECOND (unlisted → traceback + exit 1). Both are made SYMMETRIC with the
# step-6 corrupt-marker case: emit ONE stderr line and RETURN 30 (recover can
# then salvage the consumed-seal terminal).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: ComposeSealingError("boundary abort re-raised after the seal was consumed"),
        lambda: DurableLedgerError("durable export incomplete after the seal was consumed"),
    ],
    ids=["abort-reraise", "durable-finalize"],
)
def test_post_seal_step5_raise_returns_thirty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    exc_factory,  # noqa: ANN001
) -> None:
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)

    # Run the REAL fixture dispatch first (genuinely consuming the seal — a
    # COMPLETE terminal + a non-empty audit are written), THEN raise a post-seal
    # library exception, exactly as the abort / durable-finalize paths do.
    real_fixture = phase2b_mod.run_phase2b_fixture

    def _dispatch_then_raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        real_fixture(*args, **kwargs)
        assert (fx.run_dir / SEAL_AUDIT_FILENAME).stat().st_size > 0  # seal consumed
        raise exc_factory()

    monkeypatch.setattr(phase2b_mod, "run_phase2b_fixture", _dispatch_then_raise)

    rc = run_phase2b_subcommand(
        fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
    )

    # RETURNS 30 (does not raise) — a genuinely-consumed-seal post-seal failure.
    assert rc == PHASE2B_NONCOMPLETE_EXIT
    assert (fx.run_dir / SEAL_AUDIT_FILENAME).is_file()
    # A single stderr diagnostic names the exception class; stdout stays clean
    # (no scientific value ever reaches either stream).
    captured = capsys.readouterr()
    assert captured.out == ""
    assert type(exc_factory()).__name__ in captured.err


# --------------------------------------------------------------------------- #
# Guard: a genuinely PRE-seal raise from step 5 (nothing consumed — no non-empty
# audit) must PROPAGATE so the CLI's pre-seal mapping (exit 10) stays correct.
# The post-seal guard gates on seal-consumption and must never swallow a pre-seal
# failure as exit 30.
# --------------------------------------------------------------------------- #
def test_preseal_step5_raise_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fx = _run_preseal(tmp_path)
    token = _confirmation_token(fx.run_dir)

    def _raise_before_seal(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        # Raise WITHOUT running the real dispatch → the seal is never opened and
        # no audit content is written.
        raise ComposeSealingError("failed before opening the seal")

    monkeypatch.setattr(phase2b_mod, "run_phase2b_fixture", _raise_before_seal)

    with pytest.raises(ComposeSealingError):
        run_phase2b_subcommand(
            fx, approved_artifacts_root=tmp_path, run_dir=fx.run_dir, confirm_seal_token=token
        )
    # Nothing was consumed: the audit is absent or empty (the guard's own signal).
    audit = fx.run_dir / SEAL_AUDIT_FILENAME
    assert not (audit.exists() and audit.stat().st_size > 0)


# --------------------------------------------------------------------------- #
# Sanity: exit-code constants are the documented 0 / 30
# --------------------------------------------------------------------------- #
def test_exit_code_constants() -> None:
    assert PHASE2B_COMPLETE_EXIT == 0
    assert PHASE2B_NONCOMPLETE_EXIT == 30
