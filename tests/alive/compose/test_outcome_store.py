"""Tests for src/alive/compose/outcome_store.py — COMPOSE sealed outcome store.

TDD order: tests written first; the implementation must pass all of them.

This store is THE seal boundary for COMPOSE-K562-v1 Phase 2b. It mirrors the
``ReplogleOutcomeStore`` integrity discipline but has TWO sealed roles
(``sealed_double_unseen`` and ``sealed_single_unseen``); the "sealed set" is
their UNION, and ``evaluate_sealed_once`` opens BOTH regimes in a single
audited call requiring the requested set to equal the union EXACTLY.

SYNTHETIC-ONLY: all fixtures use a tiny in-memory synthetic source hidden
behind the store. The real Norman dataset is NEVER touched and no real seal is
ever opened.
"""

from __future__ import annotations

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
    OutcomeStore,
)
from alive.compose.split import build_split_manifest

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_N_GENES = 4

# Eligible gene pairs engineered (with seed below) to populate ALL three roles.
# After canonicalization the partition with seed=7 / fraction=0.5 yields a
# non-empty combo_calibration, sealed_double_unseen and sealed_single_unseen.
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
    """Tiny stand-in for an AnnData source exposing only an ``.X`` matrix.

    The store reads ``source.X[row_indices]``; this double exposes a dense
    ``np.ndarray`` so the test never imports anndata. Each row carries its row
    index in every column so a slice is trivially identifiable.
    """

    def __init__(self, n_rows: int, n_genes: int = _N_GENES) -> None:
        # Row r has value (r + 1) in every gene column → identifiable per row.
        self.X = (np.arange(n_rows, dtype=np.float64) + 1.0)[:, None] * np.ones(
            (1, n_genes), dtype=np.float64
        )


def _build_manifest() -> dict:
    """Build a pair-split manifest populating all three roles."""
    return build_split_manifest(_ELIGIBLE_PAIRS, seed=_SEED, calibration_fraction=_CAL_FRACTION)


def _canonical_pairs(manifest: dict, role: str) -> list[tuple[str, str]]:
    return [tuple(p) for p in manifest["roles"][role]]


def _build_pair_index(manifest: dict) -> tuple[_InMemorySource, dict[tuple[str, str], np.ndarray]]:
    """Assign each pair (across all roles) a small disjoint block of source rows.

    Returns the in-memory source plus a ``pair_index`` mapping canonical pair
    tuples to bounded ``np.ndarray`` row-index slices.
    """
    all_pairs: list[tuple[str, str]] = []
    for role in ("combo_calibration", "sealed_double_unseen", "sealed_single_unseen"):
        all_pairs.extend(_canonical_pairs(manifest, role))

    rows_per_pair = 3
    pair_index: dict[tuple[str, str], np.ndarray] = {}
    cursor = 0
    for pair in all_pairs:
        pair_index[pair] = np.arange(cursor, cursor + rows_per_pair, dtype=np.int64)
        cursor += rows_per_pair

    source = _InMemorySource(n_rows=cursor)
    return source, pair_index


def _build_store(tmp_path: Path) -> tuple[ComposeOutcomeStore, dict]:
    manifest = _build_manifest()
    source, pair_index = _build_pair_index(manifest)
    store = ComposeOutcomeStore(
        pair_index=pair_index,
        source=source,
        manifest=manifest,
        audit_path=tmp_path / "compose_audit.jsonl",
    )
    return store, manifest


def _sealed_union(manifest: dict) -> list[tuple[str, str]]:
    return _canonical_pairs(manifest, "sealed_double_unseen") + _canonical_pairs(
        manifest, "sealed_single_unseen"
    )


# Sanity check the fixture itself: all three roles must be non-empty so the
# tests below actually exercise both sealed regimes and the calibration role.
def test_fixture_populates_all_three_roles() -> None:
    manifest = _build_manifest()
    assert len(_canonical_pairs(manifest, "combo_calibration")) >= 1
    assert len(_canonical_pairs(manifest, "sealed_double_unseen")) >= 1
    assert len(_canonical_pairs(manifest, "sealed_single_unseen")) >= 1


# ---------------------------------------------------------------------------
# 1. Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_store_satisfies_protocol(self, tmp_path: Path) -> None:
        store, _ = _build_store(tmp_path)
        assert isinstance(store, OutcomeStore)


# ---------------------------------------------------------------------------
# 2. read_unsealed refuses BOTH sealed roles + unknown ids; allows calibration
# ---------------------------------------------------------------------------


class TestReadUnsealed:
    def test_calibration_pair_is_allowed(self, tmp_path: Path) -> None:
        store, manifest = _build_store(tmp_path)
        cal = _canonical_pairs(manifest, "combo_calibration")
        result = store.read_unsealed(cal[:1])
        assert isinstance(result, Mapping)
        assert set(result.keys()) == {cal[0]}
        pair = result[cal[0]]
        assert isinstance(pair, ObservedPair)
        assert pair.pair_id == cal[0]
        assert pair.cells.shape == (3, _N_GENES)

    def test_double_unseen_pair_refused(self, tmp_path: Path) -> None:
        store, manifest = _build_store(tmp_path)
        dbl = _canonical_pairs(manifest, "sealed_double_unseen")
        with pytest.raises(ComposeSealingError):
            store.read_unsealed([dbl[0]])

    def test_single_unseen_pair_refused(self, tmp_path: Path) -> None:
        store, manifest = _build_store(tmp_path)
        sgl = _canonical_pairs(manifest, "sealed_single_unseen")
        with pytest.raises(ComposeSealingError):
            store.read_unsealed([sgl[0]])

    def test_unknown_pair_refused(self, tmp_path: Path) -> None:
        store, _ = _build_store(tmp_path)
        with pytest.raises(ComposeSealingError):
            store.read_unsealed([("NOPE", "ZZZZ")])

    def test_mixed_request_fails_closed(self, tmp_path: Path) -> None:
        """[calibration, sealed] → refuse and return NOTHING."""
        store, manifest = _build_store(tmp_path)
        cal = _canonical_pairs(manifest, "combo_calibration")
        dbl = _canonical_pairs(manifest, "sealed_double_unseen")
        returned: Mapping | None = None
        try:
            returned = store.read_unsealed([cal[0], dbl[0]])
        except ComposeSealingError:
            pass
        assert returned is None


# ---------------------------------------------------------------------------
# 3. sealed_access_count: 0 before, 1 after a successful evaluate_sealed_once
# ---------------------------------------------------------------------------


class TestSealedAccessCount:
    def test_count_zero_before(self, tmp_path: Path) -> None:
        store, _ = _build_store(tmp_path)
        assert store.sealed_access_count == 0

    def test_count_one_after_success(self, tmp_path: Path) -> None:
        store, manifest = _build_store(tmp_path)
        store.evaluate_sealed_once("run-1", _sealed_union(manifest))
        assert store.sealed_access_count == 1


# ---------------------------------------------------------------------------
# 4. evaluate_sealed_once: successful exact-union access
# ---------------------------------------------------------------------------


class TestEvaluateSealedOnceSuccess:
    def test_returns_one_observed_pair_per_pair(self, tmp_path: Path) -> None:
        store, manifest = _build_store(tmp_path)
        union = _sealed_union(manifest)
        result = store.evaluate_sealed_once("run-ok", union)
        assert isinstance(result, Mapping)
        assert set(result.keys()) == set(union)
        for pair_id, obs in result.items():
            assert isinstance(obs, ObservedPair)
            assert obs.pair_id == pair_id
            assert obs.cells.shape == (3, _N_GENES)
            assert isinstance(obs.cells, np.ndarray)

    def test_role_labels_preserved_via_manifest_counts(self, tmp_path: Path) -> None:
        """Counts of returned pairs match the manifest's two sealed roles exactly."""
        store, manifest = _build_store(tmp_path)
        dbl = set(_canonical_pairs(manifest, "sealed_double_unseen"))
        sgl = set(_canonical_pairs(manifest, "sealed_single_unseen"))
        result = store.evaluate_sealed_once("run-roles", _sealed_union(manifest))
        returned = set(result.keys())
        assert len(returned & dbl) == len(dbl)
        assert len(returned & sgl) == len(sgl)
        assert returned == dbl | sgl

    def test_returned_rows_are_only_the_requested_pair_rows(self, tmp_path: Path) -> None:
        """Each ObservedPair holds exactly its pair_index rows, nothing else."""
        manifest = _build_manifest()
        source, pair_index = _build_pair_index(manifest)
        store = ComposeOutcomeStore(
            pair_index=pair_index,
            source=source,
            manifest=manifest,
            audit_path=tmp_path / "compose_audit.jsonl",
        )
        union = _sealed_union(manifest)
        result = store.evaluate_sealed_once("run-rows", union)
        for pair_id in union:
            rows = pair_index[pair_id]
            expected = source.X[rows]
            np.testing.assert_array_equal(result[pair_id].cells, expected)


# ---------------------------------------------------------------------------
# 5. Exact-union enforcement: empty / dup / unknown / unsealed / partial / extra
# ---------------------------------------------------------------------------


class TestExactUnionEnforcement:
    def test_empty_request_refused(self, tmp_path: Path) -> None:
        store, _ = _build_store(tmp_path)
        with pytest.raises(ComposeSealingError):
            store.evaluate_sealed_once("run-empty", [])
        assert store.sealed_access_count == 0

    def test_duplicate_id_refused(self, tmp_path: Path) -> None:
        store, manifest = _build_store(tmp_path)
        union = _sealed_union(manifest)
        with pytest.raises(ComposeSealingError):
            store.evaluate_sealed_once("run-dup", [union[0], *union])
        assert store.sealed_access_count == 0

    def test_unknown_id_refused(self, tmp_path: Path) -> None:
        store, manifest = _build_store(tmp_path)
        union = _sealed_union(manifest)
        # Replace one member with an unknown pair → set != union.
        bad = [*union[1:], ("NOPE", "ZZZZ")]
        with pytest.raises(ComposeSealingError):
            store.evaluate_sealed_once("run-unknown", bad)
        assert store.sealed_access_count == 0

    def test_unsealed_calibration_id_refused(self, tmp_path: Path) -> None:
        store, manifest = _build_store(tmp_path)
        union = _sealed_union(manifest)
        cal = _canonical_pairs(manifest, "combo_calibration")
        # Union plus an unsealed calibration pair → extra/unsealed.
        with pytest.raises(ComposeSealingError):
            store.evaluate_sealed_once("run-cal", [*union, cal[0]])
        assert store.sealed_access_count == 0

    def test_partial_subset_refused(self, tmp_path: Path) -> None:
        """A strict subset of the union (missing members) is refused."""
        store, manifest = _build_store(tmp_path)
        union = _sealed_union(manifest)
        assert len(union) >= 2
        with pytest.raises(ComposeSealingError):
            store.evaluate_sealed_once("run-partial", union[:-1])
        assert store.sealed_access_count == 0

    def test_extra_id_refused(self, tmp_path: Path) -> None:
        """The union plus an extra unknown pair is refused (superset)."""
        store, manifest = _build_store(tmp_path)
        union = _sealed_union(manifest)
        with pytest.raises(ComposeSealingError):
            store.evaluate_sealed_once("run-extra", [*union, ("NOPE", "ZZZZ")])
        assert store.sealed_access_count == 0


# ---------------------------------------------------------------------------
# 6. Once-only enforcement (durable, cross-instance, cross-run-id)
# ---------------------------------------------------------------------------


class TestOnceOnly:
    def test_concurrent_claim_has_exactly_one_winner(self, tmp_path: Path, monkeypatch) -> None:
        manifest = _build_manifest()
        source, pair_index = _build_pair_index(manifest)
        audit_path = tmp_path / "compose_audit.jsonl"
        stores = [
            ComposeOutcomeStore(
                pair_index=pair_index,
                source=source,
                manifest=manifest,
                audit_path=audit_path,
            )
            for _ in range(2)
        ]
        union = _sealed_union(manifest)
        barrier = threading.Barrier(2)
        original = ComposeOutcomeStore._assert_not_previously_accessed

        def synchronized_check(store, run_id):
            original(store, run_id)
            barrier.wait()

        monkeypatch.setattr(
            ComposeOutcomeStore,
            "_assert_not_previously_accessed",
            synchronized_check,
        )

        def attempt(item):
            run_id, store = item
            try:
                store.evaluate_sealed_once(run_id, union)
                return "success"
            except ComposeSealingError:
                return "refused"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [("run-a", stores[0]), ("run-b", stores[1])]))
        assert sorted(results) == ["refused", "success"]
        assert len(audit_path.read_text(encoding="utf-8").splitlines()) == 1

    def test_second_call_same_run_id_refused(self, tmp_path: Path) -> None:
        store, manifest = _build_store(tmp_path)
        union = _sealed_union(manifest)
        store.evaluate_sealed_once("run-1", union)
        with pytest.raises(ComposeSealingError, match="run-1"):
            store.evaluate_sealed_once("run-1", union)
        assert store.sealed_access_count == 1

    def test_second_call_fresh_store_same_audit_path_refused(self, tmp_path: Path) -> None:
        """A fresh store instance (simulating a new process) on the same audit
        path must refuse a second access — the durable JSONL audit enforces it."""
        manifest = _build_manifest()
        source, pair_index = _build_pair_index(manifest)
        audit_path = tmp_path / "compose_audit.jsonl"
        union = _sealed_union(manifest)

        store_a = ComposeOutcomeStore(
            pair_index=pair_index, source=source, manifest=manifest, audit_path=audit_path
        )
        store_a.evaluate_sealed_once("run-cross", union)

        store_b = ComposeOutcomeStore(
            pair_index=pair_index, source=source, manifest=manifest, audit_path=audit_path
        )
        with pytest.raises(ComposeSealingError, match="run-cross"):
            store_b.evaluate_sealed_once("run-cross", union)
        assert store_b.sealed_access_count == 1

    def test_different_run_id_refused_after_first(self, tmp_path: Path) -> None:
        store, manifest = _build_store(tmp_path)
        union = _sealed_union(manifest)
        store.evaluate_sealed_once("run-first", union)
        with pytest.raises(ComposeSealingError):
            store.evaluate_sealed_once("run-second", union)
        assert store.sealed_access_count == 1


# ---------------------------------------------------------------------------
# 7. Materialisation crash AFTER audit claim still burns the run
# ---------------------------------------------------------------------------


class TestFailSafeAuditOrdering:
    def test_crash_after_audit_still_burns_run(self, tmp_path: Path) -> None:
        """If the row-slice raises AFTER the audit record is written, the run is
        burned: sealed_access_count == 1 and a later access is refused.

        The crash is injected via a source whose ``.X`` slicing raises.
        """
        manifest = _build_manifest()
        _, pair_index = _build_pair_index(manifest)
        union = _sealed_union(manifest)

        class _ExplodingX:
            def __getitem__(self, _key: object) -> object:
                raise RuntimeError("simulated OOM during materialisation")

        class _ExplodingSource:
            X = _ExplodingX()

        audit_path = tmp_path / "compose_audit.jsonl"
        store = ComposeOutcomeStore(
            pair_index=pair_index,
            source=_ExplodingSource(),
            manifest=manifest,
            audit_path=audit_path,
        )

        with pytest.raises(RuntimeError, match="simulated OOM"):
            store.evaluate_sealed_once("run-burned", union)

        # Audit was written BEFORE materialisation → access consumed.
        assert store.sealed_access_count == 1

        # A fresh, non-exploding store on the same audit path must still refuse.
        good_source, good_index = _build_pair_index(manifest)
        store2 = ComposeOutcomeStore(
            pair_index=good_index,
            source=good_source,
            manifest=manifest,
            audit_path=audit_path,
        )
        with pytest.raises(ComposeSealingError):
            store2.evaluate_sealed_once("run-burned", union)
        assert store2.sealed_access_count == 1


# ---------------------------------------------------------------------------
# 8. Audit record contents
# ---------------------------------------------------------------------------


class TestAuditRecordContents:
    def test_audit_record_fields(self, tmp_path: Path) -> None:
        store, manifest = _build_store(tmp_path)
        union = _sealed_union(manifest)
        store.evaluate_sealed_once("run-rec", union)

        records = store.audit_records()
        assert isinstance(records, tuple)
        assert len(records) == 1
        rec = records[0]

        assert rec["run_id"] == "run-rec"
        # sorted canonical [a, b] pair list
        sorted_pairs = sorted([list(p) for p in union])
        assert rec["pair_ids"] == sorted_pairs
        # role counts
        n_dbl = len(_canonical_pairs(manifest, "sealed_double_unseen"))
        n_sgl = len(_canonical_pairs(manifest, "sealed_single_unseen"))
        assert rec["role_counts"] == {
            "sealed_double_unseen": n_dbl,
            "sealed_single_unseen": n_sgl,
        }
        # manifest checksum and a request checksum
        assert rec["manifest_checksum"] == manifest["checksum"]
        assert "request_checksum" in rec
        assert isinstance(rec["request_checksum"], str)

    def test_audit_record_on_disk_matches_accessor(self, tmp_path: Path) -> None:
        manifest = _build_manifest()
        source, pair_index = _build_pair_index(manifest)
        audit_path = tmp_path / "compose_audit.jsonl"
        store = ComposeOutcomeStore(
            pair_index=pair_index, source=source, manifest=manifest, audit_path=audit_path
        )
        store.evaluate_sealed_once("run-disk", _sealed_union(manifest))

        lines = [ln for ln in audit_path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        on_disk = json.loads(lines[0])
        assert on_disk == store.audit_records()[0]


# ---------------------------------------------------------------------------
# 9. Audit tampering / corruption fails closed
# ---------------------------------------------------------------------------


class TestAuditTamperFailsClosed:
    def test_corrupt_line_raises_on_count(self, tmp_path: Path) -> None:
        store, manifest = _build_store(tmp_path)
        store.evaluate_sealed_once("run-good", _sealed_union(manifest))
        # Append a corrupt (non-JSON) line.
        audit_path = tmp_path / "compose_audit.jsonl"
        with audit_path.open("a", encoding="utf-8") as fh:
            fh.write("{ this is not valid json\n")

        with pytest.raises(ComposeSealingError):
            _ = store.sealed_access_count

    def test_partial_line_fails_closed_on_next_access(self, tmp_path: Path) -> None:
        """A partially written JSONL line must not silently deflate the count or
        allow a fresh access. The next evaluate_sealed_once must fail closed."""
        manifest = _build_manifest()
        source, pair_index = _build_pair_index(manifest)
        audit_path = tmp_path / "compose_audit.jsonl"
        # Write a truncated/partial JSON line directly (no valid record).
        audit_path.write_text('{"run_id": "partial", "pair_ids', encoding="utf-8")

        store = ComposeOutcomeStore(
            pair_index=pair_index, source=source, manifest=manifest, audit_path=audit_path
        )
        with pytest.raises(ComposeSealingError):
            store.evaluate_sealed_once("run-after-partial", _sealed_union(manifest))


# ---------------------------------------------------------------------------
# 9b. Constructor fails closed BEFORE any access can be consumed
# ---------------------------------------------------------------------------


class TestConstructorGuards:
    @pytest.mark.parametrize(
        "bad_rows",
        [np.array([-1], dtype=np.int64), np.array([0, 0], dtype=np.int64), np.array([0.5])],
    )
    def test_invalid_pair_rows_rejected_at_construction(self, tmp_path: Path, bad_rows) -> None:
        manifest = _build_manifest()
        source, pair_index = _build_pair_index(manifest)
        pair_index[next(iter(pair_index))] = bad_rows
        with pytest.raises(ComposeSealingError, match="row|integer|duplicate|negative"):
            ComposeOutcomeStore(
                pair_index=pair_index,
                source=source,
                manifest=manifest,
                audit_path=tmp_path / "compose_audit.jsonl",
            )

    def test_pair_rows_cannot_overlap(self, tmp_path: Path) -> None:
        manifest = _build_manifest()
        source, pair_index = _build_pair_index(manifest)
        first, second = list(pair_index)[:2]
        pair_index[second] = pair_index[first].copy()
        with pytest.raises(ComposeSealingError, match="overlap"):
            ComposeOutcomeStore(
                pair_index=pair_index,
                source=source,
                manifest=manifest,
                audit_path=tmp_path / "compose_audit.jsonl",
            )

    def test_missing_sealed_pair_in_index_raises_at_construction(self, tmp_path: Path) -> None:
        """A pair_index missing a sealed pair must be rejected at construction —
        BEFORE any audit can be burned. Today a missing sealed pair would surface
        as a raw KeyError only after evaluate_sealed_once has already written the
        audit record; the seal boundary must instead reject the misconfigured
        index at __init__."""
        manifest = _build_manifest()
        source, pair_index = _build_pair_index(manifest)
        # Drop one sealed pair from the index so a sealed id has no rows.
        union = _sealed_union(manifest)
        missing = union[0]
        del pair_index[missing]

        audit_path = tmp_path / "compose_audit.jsonl"
        with pytest.raises(ComposeSealingError, match="pair_index"):
            ComposeOutcomeStore(
                pair_index=pair_index,
                source=source,
                manifest=manifest,
                audit_path=audit_path,
            )
        # Raised at CONSTRUCTION: no evaluate_sealed_once was ever called, and the
        # audit file was never created (the once-only access was not consumed).
        assert not audit_path.exists()

    def test_manifest_missing_roles_raises_at_construction(self, tmp_path: Path) -> None:
        manifest = _build_manifest()
        source, pair_index = _build_pair_index(manifest)
        bad = dict(manifest)
        del bad["roles"]
        with pytest.raises(ComposeSealingError, match="roles"):
            ComposeOutcomeStore(
                pair_index=pair_index,
                source=source,
                manifest=bad,
                audit_path=tmp_path / "compose_audit.jsonl",
            )

    def test_manifest_missing_checksum_raises_at_construction(self, tmp_path: Path) -> None:
        manifest = _build_manifest()
        source, pair_index = _build_pair_index(manifest)
        bad = dict(manifest)
        del bad["checksum"]
        with pytest.raises(ComposeSealingError, match="checksum"):
            ComposeOutcomeStore(
                pair_index=pair_index,
                source=source,
                manifest=bad,
                audit_path=tmp_path / "compose_audit.jsonl",
            )


# ---------------------------------------------------------------------------
# 10. No global densification — only requested bounded rows are materialised
# ---------------------------------------------------------------------------


class TestNoGlobalDensification:
    def test_only_requested_rows_are_sliced(self, tmp_path: Path) -> None:
        """A spy source records which row indices were requested; the store must
        only ever request the exact union of requested-pair rows, never the
        full matrix."""
        manifest = _build_manifest()
        base_source, pair_index = _build_pair_index(manifest)
        union = _sealed_union(manifest)

        requested_rows: list[np.ndarray] = []

        class _SpyX:
            def __init__(self, inner: np.ndarray) -> None:
                self._inner = inner

            def __getitem__(self, key: object) -> np.ndarray:
                arr = np.asarray(key)
                # Refuse a full-matrix densify: a slice covering ALL rows fails.
                if arr.ndim == 1 and arr.size == self._inner.shape[0]:
                    raise AssertionError("full-matrix slice attempted")
                requested_rows.append(arr)
                return self._inner[key]

        class _SpySource:
            def __init__(self, inner: np.ndarray) -> None:
                self.X = _SpyX(inner)

        store = ComposeOutcomeStore(
            pair_index=pair_index,
            source=_SpySource(base_source.X),
            manifest=manifest,
            audit_path=tmp_path / "compose_audit.jsonl",
        )
        store.evaluate_sealed_once("run-bounded", union)

        # Exactly one slice per requested pair, and the union of sliced rows
        # equals exactly the union pairs' rows (no extra rows materialised).
        assert len(requested_rows) == len(union)
        sliced = np.sort(np.concatenate(requested_rows))
        expected = np.sort(np.concatenate([pair_index[p] for p in union]))
        np.testing.assert_array_equal(sliced, expected)
