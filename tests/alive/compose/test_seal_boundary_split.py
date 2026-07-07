"""Task 0 (D1): durable-audit consumption-boundary split tests.

TDD order: written FIRST (RED), then the implementation makes them GREEN.

Prerequisite Task 0 restructures THE one-time-seal consumption boundary. The old
``evaluate_sealed_once`` conflated an in-memory ``claim_access`` (the terminal
went ``ACCESS_CLAIMED`` in memory) with the durable audit write. A crash in
between wrote a FALSE ``ABORTED_AFTER_SEAL`` with ``sealed_access_count == 0`` —
a recorded seal consumption that never happened.

The consumption boundary is split into two store operations:

* :meth:`ComposeOutcomeStore.claim_sealed_access` (validate the exact union,
  refuse prior access, write the durable audit FIRST) returns an IMMUTABLE
  :class:`SealedAccessClaim` carrying an ``audit_reference`` derived from the
  persisted record; and
* :meth:`ComposeOutcomeStore.materialize_claimed` (verify the claim matches the
  persisted audit, then materialise) returns ``{pair -> ObservedPair}``.

The terminal gains an ``ACCESS_ATTEMPTED`` state (post-``acquire``,
pre-durable-audit) reached by :meth:`Phase2bTerminal.attempt_access`, and a
:meth:`Phase2bTerminal.confirm_durable_access` transition
(``ACCESS_ATTEMPTED -> ACCESS_CLAIMED``). An exception in ``ACCESS_ATTEMPTED``
writes NO terminal (count 0). Only a confirmed durable reference reaches
``ACCESS_CLAIMED``, from which every exit writes exactly one terminal.

SYNTHETIC-ONLY: a tiny in-memory synthetic source; NO real Norman, NO real seal.
"""

from __future__ import annotations

import dataclasses
import json
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from alive.compose.outcome_store import (
    ComposeOutcomeStore,
    ComposeSealingError,
    ObservedPair,
    SealedAccessClaim,
)
from alive.compose.split import build_split_manifest
from alive.compose.terminal import (
    Phase2bTerminal,
    TerminalError,
    TerminalState,
)
from alive.provenance import (
    EnvironmentInfo,
    RunLedger,
    sha256_json,
)
from tests.alive.compose._terminal_bodies import minimal_v2_terminal_body

# ---------------------------------------------------------------------------
# Synthetic outcome-store fixtures (mirrors test_outcome_store.py)
# ---------------------------------------------------------------------------

_N_GENES = 4
_ELIGIBLE_PAIRS: list[tuple[str, str]] = [
    ("GENEA", "GENEB"),
    ("GENEA", "GENEC"),
    ("GENEB", "GENEC"),
    ("GENEC", "GENED"),
    ("GENED", "GENEE"),
    ("GENEE", "GENEF"),
    ("GENEA", "GENED"),
    ("GENEB", "GENEF"),
]
_SEED = 7
_CAL_FRACTION = 0.5


class _InMemorySource:
    """Tiny stand-in for an AnnData source exposing only an ``.X`` matrix."""

    def __init__(self, n_rows: int, n_genes: int = _N_GENES) -> None:
        self.X = (np.arange(n_rows, dtype=np.float64) + 1.0)[:, None] * np.ones(
            (1, n_genes), dtype=np.float64
        )


def _build_manifest() -> dict:
    return build_split_manifest(_ELIGIBLE_PAIRS, seed=_SEED, calibration_fraction=_CAL_FRACTION)


def _canonical_pairs(manifest: dict, role: str) -> list[tuple[str, str]]:
    return [tuple(p) for p in manifest["roles"][role]]


def _build_pair_index(manifest: dict) -> tuple[_InMemorySource, dict[tuple[str, str], np.ndarray]]:
    all_pairs: list[tuple[str, str]] = []
    for role in ("combo_calibration", "sealed_double_unseen", "sealed_single_unseen"):
        all_pairs.extend(_canonical_pairs(manifest, role))
    rows_per_pair = 3
    pair_index: dict[tuple[str, str], np.ndarray] = {}
    cursor = 0
    for pair in all_pairs:
        pair_index[pair] = np.arange(cursor, cursor + rows_per_pair, dtype=np.int64)
        cursor += rows_per_pair
    return _InMemorySource(n_rows=cursor), pair_index


def _store_on(audit_path: Path, manifest: dict) -> ComposeOutcomeStore:
    source, pair_index = _build_pair_index(manifest)
    return ComposeOutcomeStore(
        pair_index=pair_index, source=source, manifest=manifest, audit_path=audit_path
    )


def _build_store(tmp_path: Path) -> tuple[ComposeOutcomeStore, dict]:
    manifest = _build_manifest()
    return _store_on(tmp_path / "compose_audit.jsonl", manifest), manifest


def _sealed_union(manifest: dict) -> list[tuple[str, str]]:
    return _canonical_pairs(manifest, "sealed_double_unseen") + _canonical_pairs(
        manifest, "sealed_single_unseen"
    )


# ---------------------------------------------------------------------------
# Terminal fixtures (mirrors test_terminal.py)
# ---------------------------------------------------------------------------


def _environment() -> EnvironmentInfo:
    return EnvironmentInfo(
        python_version="3.12.0",
        platform="test-platform",
        git_commit="0" * 40,
        lockfile_sha256="lock-sha-eeee",
        registered_seeds=(0, 1, 2),
    )


def _ledger() -> RunLedger:
    return RunLedger(run_id="run-aaaa", config_sha256="config-sha-bbbb", environment=_environment())


def _terminal(run_dir: Path, *, audit_path: Path | None) -> Phase2bTerminal:
    run_dir.mkdir(parents=True, exist_ok=True)
    return Phase2bTerminal(run_dir, ledger=_ledger(), audit_path=audit_path)


def _existing_terminal_artifacts(run_dir: Path) -> list[Path]:
    return [
        p
        for p in (
            run_dir / Phase2bTerminal.COMPLETE_ARTIFACT,
            run_dir / Phase2bTerminal.INVALID_ARTIFACT,
            run_dir / Phase2bTerminal.ABORTED_ARTIFACT,
        )
        if p.exists()
    ]


def _open_seal(
    term: Phase2bTerminal,
    store: object,
    run_id: str,
    union: list[tuple[str, str]],
) -> SealedAccessClaim:
    """Drive the new seal-open sequence exactly as phase2b will."""
    term.acquire()
    term.attempt_access()
    claim = store.claim_sealed_access(run_id, union)
    term.confirm_durable_access(claim.audit_reference)
    return claim


# ---------------------------------------------------------------------------
# Store-side wrappers to inject a materialisation failure AFTER the audit write
# ---------------------------------------------------------------------------


class _MaterializeBoom:
    """Wraps a real store; ``claim_sealed_access`` burns the audit, materialise fails."""

    def __init__(self, inner: ComposeOutcomeStore) -> None:
        self._inner = inner
        self._audit_path = inner._audit_path
        self._compose_fixture_marker = True

    def claim_sealed_access(self, run_id, pair_ids) -> SealedAccessClaim:
        return self._inner.claim_sealed_access(run_id, pair_ids)

    def materialize_claimed(self, claim) -> Mapping[tuple[str, str], ObservedPair]:
        raise RuntimeError("synthetic materialisation failure")

    @property
    def sealed_access_count(self) -> int:
        return self._inner.sealed_access_count

    def audit_records(self) -> tuple[dict, ...]:
        return self._inner.audit_records()


# ===========================================================================
# A. Store-level: claim / materialize semantics
# ===========================================================================


def test_claim_then_materialize_matches_evaluate_sealed_once(tmp_path: Path) -> None:
    store, manifest = _build_store(tmp_path)
    union = _sealed_union(manifest)
    claim = store.claim_sealed_access("run-ok", union)
    assert isinstance(claim, SealedAccessClaim)
    assert store.sealed_access_count == 1  # durable audit written by claim
    release = store.materialize_claimed(claim)
    assert isinstance(release, Mapping)
    assert set(release.keys()) == set(union)
    for pid, obs in release.items():
        assert isinstance(obs, ObservedPair)
        assert obs.pair_id == pid
        assert obs.cells.shape == (3, _N_GENES)


def test_audit_reference_is_derived_from_persisted_record(tmp_path: Path) -> None:
    store, manifest = _build_store(tmp_path)
    claim = store.claim_sealed_access("run-ref", _sealed_union(manifest))
    assert isinstance(claim.audit_reference, str) and claim.audit_reference
    record = store.audit_records()[0]
    assert claim.audit_reference == sha256_json(record)
    assert claim.run_id == "run-ref"
    assert claim.request_checksum == record["request_checksum"]
    assert claim.manifest_checksum == record["manifest_checksum"]


def test_evaluate_sealed_once_still_works_via_split(tmp_path: Path) -> None:
    store, manifest = _build_store(tmp_path)
    union = _sealed_union(manifest)
    result = store.evaluate_sealed_once("run-compat", union)
    assert set(result.keys()) == set(union)
    assert store.sealed_access_count == 1


def test_claim_pre_audit_failure_leaves_count_zero(tmp_path: Path) -> None:
    """An exact-union mismatch raises BEFORE the audit write; nothing is burned."""
    store, _ = _build_store(tmp_path)
    with pytest.raises(ComposeSealingError):
        store.claim_sealed_access("run-empty", [])
    assert store.sealed_access_count == 0
    assert not (tmp_path / "compose_audit.jsonl").exists()


def test_second_claim_same_store_fails_closed(tmp_path: Path) -> None:
    store, manifest = _build_store(tmp_path)
    union = _sealed_union(manifest)
    store.claim_sealed_access("run-1", union)
    with pytest.raises(ComposeSealingError, match="run-1"):
        store.claim_sealed_access("run-1", union)
    assert store.sealed_access_count == 1


def test_process_restart_fresh_store_sees_burned_claim(tmp_path: Path) -> None:
    """A fresh store on the same audit path observes the burned access; a second
    claim_sealed_access fails closed (durable JSONL audit enforces once-only)."""
    manifest = _build_manifest()
    audit_path = tmp_path / "compose_audit.jsonl"
    union = _sealed_union(manifest)

    store_a = _store_on(audit_path, manifest)
    store_a.claim_sealed_access("run-cross", union)
    assert store_a.sealed_access_count == 1

    store_b = _store_on(audit_path, manifest)
    assert store_b.sealed_access_count == 1  # durable audit already burned
    with pytest.raises(ComposeSealingError, match="run-cross"):
        store_b.claim_sealed_access("run-cross", union)
    assert store_b.sealed_access_count == 1


def test_materialize_run_id_mismatch_fails_closed(tmp_path: Path) -> None:
    store, manifest = _build_store(tmp_path)
    claim = store.claim_sealed_access("run-real", _sealed_union(manifest))
    tampered = dataclasses.replace(claim, run_id="run-forged")
    with pytest.raises(ComposeSealingError):
        store.materialize_claimed(tampered)


def test_materialize_request_checksum_mismatch_fails_closed(tmp_path: Path) -> None:
    store, manifest = _build_store(tmp_path)
    claim = store.claim_sealed_access("run-real", _sealed_union(manifest))
    tampered = dataclasses.replace(claim, request_checksum="d" * 64)
    with pytest.raises(ComposeSealingError):
        store.materialize_claimed(tampered)


def test_materialize_audit_reference_mismatch_fails_closed(tmp_path: Path) -> None:
    store, manifest = _build_store(tmp_path)
    claim = store.claim_sealed_access("run-real", _sealed_union(manifest))
    tampered = dataclasses.replace(claim, audit_reference="f" * 64)
    with pytest.raises(ComposeSealingError):
        store.materialize_claimed(tampered)


def test_materialize_without_backing_audit_fails_closed(tmp_path: Path) -> None:
    """A claim whose audit was never persisted must not materialise."""
    store, manifest = _build_store(tmp_path)
    union = _sealed_union(manifest)
    canon = tuple(tuple(p) for p in union)
    forged = SealedAccessClaim(
        run_id="run-forged",
        audit_reference="a" * 64,
        request_checksum="b" * 64,
        manifest_checksum=manifest["checksum"],
        pair_ids=canon,
    )
    with pytest.raises(ComposeSealingError):
        store.materialize_claimed(forged)
    assert store.sealed_access_count == 0


def test_materialize_forged_pair_ids_fails_closed(tmp_path: Path) -> None:
    """Defense-in-depth on the seal backstop: a claim whose ``run_id`` /
    ``request_checksum`` / ``audit_reference`` are genuine but whose ``pair_ids``
    have been swapped for a DIFFERENT in-index set must fail closed, not slice
    the forged pairs.

    The forged set below keeps every entry inside the store's pair index (so the
    old raw ``_materialise_pairs`` would happily slice it) but swaps a sealed pair
    for an in-index NON-sealed calibration pair, so it re-derives a different
    request checksum than the persisted sealed union.
    """
    store, manifest = _build_store(tmp_path)
    union = _sealed_union(manifest)
    claim = store.claim_sealed_access("run-real", union)

    non_sealed = _canonical_pairs(manifest, "combo_calibration")  # in index, not sealed
    assert non_sealed, "fixture must expose an in-index non-sealed pair"
    forged_pairs = tuple(non_sealed) + tuple(union[:-1])  # in-index, != sealed union
    assert set(forged_pairs) != set(union)
    forged = dataclasses.replace(claim, pair_ids=forged_pairs)
    # The identity fields are untouched, so the three legacy checks all pass.
    assert forged.run_id == claim.run_id
    assert forged.request_checksum == claim.request_checksum
    assert forged.audit_reference == claim.audit_reference

    with pytest.raises(ComposeSealingError):
        store.materialize_claimed(forged)


def test_materialize_genuine_claim_returns_sealed_union(tmp_path: Path) -> None:
    """Regression: the authenticated materialise path returns exactly the sealed
    union for a genuine claim (payload sliced from the persisted record)."""
    store, manifest = _build_store(tmp_path)
    union = _sealed_union(manifest)
    claim = store.claim_sealed_access("run-genuine", union)
    release = store.materialize_claimed(claim)
    assert set(release.keys()) == set(union)
    for pid, obs in release.items():
        assert isinstance(obs, ObservedPair)
        assert obs.pair_id == pid


def test_concurrent_claims_one_audit_one_winner(tmp_path: Path, monkeypatch) -> None:
    manifest = _build_manifest()
    audit_path = tmp_path / "compose_audit.jsonl"
    stores = [_store_on(audit_path, manifest) for _ in range(2)]
    union = _sealed_union(manifest)
    barrier = threading.Barrier(2)
    original = ComposeOutcomeStore._assert_not_previously_accessed

    def synchronized_check(store, run_id):
        original(store, run_id)
        barrier.wait()

    monkeypatch.setattr(ComposeOutcomeStore, "_assert_not_previously_accessed", synchronized_check)

    def attempt(item):
        run_id, store = item
        try:
            store.claim_sealed_access(run_id, union)
            return "success"
        except ComposeSealingError:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [("run-a", stores[0]), ("run-b", stores[1])]))
    assert sorted(results) == ["refused", "success"]
    assert len(audit_path.read_text(encoding="utf-8").splitlines()) == 1


# ===========================================================================
# B. Terminal-level: ACCESS_ATTEMPTED and confirm_durable_access
# ===========================================================================


def test_attempt_access_from_prepared_enters_access_attempted(tmp_path: Path) -> None:
    term = _terminal(tmp_path / "run", audit_path=None)
    term.acquire()
    assert term.state is TerminalState.PREPARED
    term.attempt_access()
    assert term.state is TerminalState.ACCESS_ATTEMPTED


def test_confirm_durable_access_requires_attempted_state(tmp_path: Path) -> None:
    term = _terminal(tmp_path / "run", audit_path=None)
    term.acquire()  # PREPARED, not ACCESS_ATTEMPTED
    with pytest.raises(TerminalError):
        term.confirm_durable_access("a" * 64)


def test_confirm_durable_access_rejects_empty_reference(tmp_path: Path) -> None:
    term = _terminal(tmp_path / "run", audit_path=None)
    term.acquire()
    term.attempt_access()
    with pytest.raises(TerminalError):
        term.confirm_durable_access("")
    assert term.state is TerminalState.ACCESS_ATTEMPTED


def test_confirm_without_durable_audit_refused(tmp_path: Path) -> None:
    """With an audit_path but NO durable record yet, confirm refuses — you cannot
    reach ACCESS_CLAIMED (whence ABORTED is written) without a real burn. This is
    the anti-false-ABORTED direction of the bug fix."""
    store, _ = _build_store(tmp_path)
    run_dir = tmp_path / "run"
    term = _terminal(run_dir, audit_path=store._audit_path)
    term.acquire()
    term.attempt_access()
    # No claim_sealed_access has run, so the durable audit has no records.
    with pytest.raises(TerminalError):
        term.confirm_durable_access("a" * 64)
    assert term.state is TerminalState.ACCESS_ATTEMPTED
    assert store.sealed_access_count == 0
    assert _existing_terminal_artifacts(run_dir) == []


def test_protect_refuses_in_access_attempted(tmp_path: Path) -> None:
    """protect() only wraps ACCESS_CLAIMED work; ACCESS_ATTEMPTED is pre-audit."""
    term = _terminal(tmp_path / "run", audit_path=None)
    term.acquire()
    term.attempt_access()
    with pytest.raises(TerminalError):
        with term.protect(stage="preflight"):
            raise RuntimeError("boom before durable audit")
    assert _existing_terminal_artifacts(term.run_dir) == []


def test_exception_in_access_attempted_writes_no_terminal(tmp_path: Path) -> None:
    """The core bug fix: a failure between attempt_access and the durable audit
    leaves NO terminal artifact (the seal was never durably consumed)."""
    store, manifest = _build_store(tmp_path)
    run_dir = tmp_path / "run"
    term = _terminal(run_dir, audit_path=store._audit_path)
    term.acquire()
    term.attempt_access()
    # Simulate a pre-audit claim failure (empty union raises before any write).
    with pytest.raises(ComposeSealingError):
        store.claim_sealed_access("run-x", [])
    assert store.sealed_access_count == 0
    assert not (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).exists()
    assert _existing_terminal_artifacts(run_dir) == []
    assert term.state is TerminalState.ACCESS_ATTEMPTED


# ===========================================================================
# C. Integration: store + terminal wired as phase2b will wire them
# ===========================================================================


def test_happy_path_claim_confirm_materialize_complete(tmp_path: Path) -> None:
    store, manifest = _build_store(tmp_path)
    union = _sealed_union(manifest)
    run_dir = tmp_path / "run"
    term = _terminal(run_dir, audit_path=store._audit_path)
    claim = _open_seal(term, store, "run-happy", union)
    assert term.state is TerminalState.ACCESS_CLAIMED
    with term.protect(stage="scoring"):
        release = store.materialize_claimed(claim)
        assert len(release) > 0  # the union of both sealed roles was materialised
        term.complete(minimal_v2_terminal_body())
    assert term.state is TerminalState.COMPLETE
    assert store.sealed_access_count == 1
    assert _existing_terminal_artifacts(run_dir) == [run_dir / Phase2bTerminal.COMPLETE_ARTIFACT]


def test_materialization_failure_writes_one_aborted_with_reference(tmp_path: Path) -> None:
    inner, manifest = _build_store(tmp_path)
    union = _sealed_union(manifest)
    store = _MaterializeBoom(inner)
    run_dir = tmp_path / "run"
    term = _terminal(run_dir, audit_path=inner._audit_path)
    claim = _open_seal(term, store, "run-boom", union)
    assert store.sealed_access_count == 1  # audit burned by claim
    with pytest.raises(RuntimeError, match="materialisation failure"):
        with term.protect(stage="materialise"):
            store.materialize_claimed(claim)
    assert store.sealed_access_count == 1
    aborted = run_dir / Phase2bTerminal.ABORTED_ARTIFACT
    assert _existing_terminal_artifacts(run_dir) == [aborted]
    body = json.loads(aborted.read_text(encoding="utf-8"))
    assert body["terminal_state"] == TerminalState.ABORTED_AFTER_SEAL.value
    assert body["audit_reference"] == claim.audit_reference


def test_pre_audit_failure_leaves_count_zero_and_no_terminal(tmp_path: Path) -> None:
    store, manifest = _build_store(tmp_path)
    run_dir = tmp_path / "run"
    term = _terminal(run_dir, audit_path=store._audit_path)
    term.acquire()
    term.attempt_access()
    with pytest.raises(ComposeSealingError):
        store.claim_sealed_access("run-x", [])  # pre-audit validation failure
    assert store.sealed_access_count == 0
    assert _existing_terminal_artifacts(run_dir) == []


def test_process_restart_second_run_refuses(tmp_path: Path) -> None:
    manifest = _build_manifest()
    audit_path = tmp_path / "compose_audit.jsonl"
    union = _sealed_union(manifest)

    store_a = _store_on(audit_path, manifest)
    term_a = _terminal(tmp_path / "run_a", audit_path=audit_path)
    claim = _open_seal(term_a, store_a, "run-1", union)
    with term_a.protect(stage="scoring"):
        store_a.materialize_claimed(claim)
        term_a.complete(minimal_v2_terminal_body())
    assert store_a.sealed_access_count == 1

    # Fresh store + fresh terminal (new run dir) on the SAME audit path: the
    # terminal's acquire refuses because the durable audit already has records.
    store_b = _store_on(audit_path, manifest)
    assert store_b.sealed_access_count == 1
    term_b = _terminal(tmp_path / "run_b", audit_path=audit_path)
    with pytest.raises(TerminalError):
        term_b.acquire()
    assert store_b.sealed_access_count == 1
