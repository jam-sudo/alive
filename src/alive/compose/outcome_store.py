"""Structurally sealed outcome store for COMPOSE-K562-v1 combo outcomes.

This module is THE seal boundary for COMPOSE-K562-v1 Phase 2b (CLAUDE.md §6
multiple-seal rule, §11 write-once provenance). It is the ONLY path that will
ever read observed Norman combo cell populations, and it mirrors the integrity
discipline of :mod:`alive.data.outcome_store` (the Replogle store) rather than
persisting an outcome dictionary inside a run directory.

COMPOSE differs from the Replogle store in one structural way: it has TWO
sealed roles — ``sealed_double_unseen`` (the headline combo/pair-zero-shot
regime) and ``sealed_single_unseen`` (a registered secondary regime). The
"sealed set" is their UNION.

- Ordinary reads (:meth:`ComposeOutcomeStore.read_unsealed`) are blocked for any
  pair assigned to EITHER sealed role; only calibration pairs are readable.
- The single audited path (:meth:`ComposeOutcomeStore.evaluate_sealed_once`)
  opens BOTH regimes in one audited call. The requested set must equal the
  registered sealed UNION EXACTLY (refusing empty, duplicate, unknown, unsealed,
  missing-subset or extra IDs). Exactly ONE access per ``audit_path`` is ever
  permitted, enforced durably across processes via a JSONL audit written BEFORE
  data is materialised (fail-safe: a crash during materialisation still burns
  the run).

Global invariant — no global densification
------------------------------------------
Each pair's population is materialised by slicing only its bounded row indices
from the source expression matrix (``source.X``). The full matrix is NEVER
materialised or densified.

Public API
----------
ComposeSealingError
    Raised on any attempt to breach the seal.
ObservedPair
    Frozen value object holding one pair's canonical ID and its materialised
    bounded cell matrix (the raw observed population; downstream Phase-2b
    transforms it into response space — this store does NOT transform it).
OutcomeStore
    Runtime-checkable protocol that :class:`ComposeOutcomeStore` satisfies.
ComposeOutcomeStore
    Concrete store backed by a canonical ``pair_index``, a source AnnData/path,
    an immutable pair-split manifest and an append-only JSONL audit.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np
import scipy.sparse as sp

from alive.provenance import sha256_json

if TYPE_CHECKING:
    import anndata as _anndata

#: The two sealed roles whose union forms the sealed cohort.
_SEALED_ROLES = ("sealed_double_unseen", "sealed_single_unseen")

#: Pair ID type: a canonical 2-tuple ``(a, b)`` (lexicographic min/max).
PairID = tuple[str, str]


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ComposeSealingError(RuntimeError):
    """Raised on any attempt to breach the COMPOSE structural seal.

    Parameters
    ----------
    message : str
        Human-readable description of the violation.
    """


# ---------------------------------------------------------------------------
# ObservedPair value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObservedPair:
    """Materialised observed population for a single combo pair.

    The raw observed population only; downstream Phase-2b code transforms it
    into response space. This store performs no transformation.

    Parameters
    ----------
    pair_id : tuple of str
        Canonical 2-tuple ``(a, b)`` identifying the gene pair.
    cells : np.ndarray
        Dense ``(n_cells, n_genes)`` expression matrix for this pair only.
        Never the full source matrix.
    """

    pair_id: PairID
    cells: np.ndarray


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class OutcomeStore(Protocol):
    """Protocol that COMPOSE outcome stores must satisfy.

    Satisfies :func:`typing.runtime_checkable` so test doubles and the concrete
    store can both be validated with ``isinstance(obj, OutcomeStore)``.
    """

    def read_unsealed(self, pair_ids: Sequence[PairID]) -> Mapping[PairID, ObservedPair]:
        """Return populations for unsealed (calibration) pair ids.

        Parameters
        ----------
        pair_ids : Sequence[tuple of str]
            Canonical pair ids. Must all be non-sealed, known calibration pairs.

        Returns
        -------
        Mapping[tuple of str, ObservedPair]
            Mapping from pair id to materialised :class:`ObservedPair`.

        Raises
        ------
        ComposeSealingError
            If any requested id is sealed (either role) or unknown.
        """
        ...

    def evaluate_sealed_once(
        self, run_id: str, pair_ids: Sequence[PairID]
    ) -> Mapping[PairID, ObservedPair]:
        """The single audited gateway to sealed outcome data (both regimes).

        Parameters
        ----------
        run_id : str
            Deterministic run identifier. Only the first call per ``audit_path``
            ever succeeds; subsequent calls (even from a fresh process or under a
            different run_id) raise.
        pair_ids : Sequence[tuple of str]
            Must equal the registered sealed UNION exactly.

        Returns
        -------
        Mapping[tuple of str, ObservedPair]
            Mapping from pair id to materialised :class:`ObservedPair`.

        Raises
        ------
        ComposeSealingError
            On any integrity violation (non-exact union, prior access, etc.).
        """
        ...


# ---------------------------------------------------------------------------
# Concrete store
# ---------------------------------------------------------------------------


class ComposeOutcomeStore:
    """Structurally sealed outcome store backed by a canonical pair index.

    Parameters
    ----------
    pair_index : Mapping[tuple of str, np.ndarray]
        Mapping from each canonical pair tuple ``(a, b)`` to the bounded source
        row indices (an integer ``np.ndarray``) for that pair's cells.
    source : anndata.AnnData or str or Path or object with ``.X``
        In-memory AnnData (or a path to an ``.h5ad`` file, opened ``backed="r"``
        so the full matrix is never loaded into memory), or any object exposing
        an ``.X`` matrix sliceable by a row-index array.
    manifest : Mapping
        The immutable pair-split manifest built by
        :func:`alive.compose.split.build_split_manifest`. Must contain ``roles``
        with both sealed roles and a self-excluding ``checksum``.
    audit_path : str or Path
        Path to the durable append-only JSONL audit file. The sealed cohort may
        be opened exactly once per audit path. The file is created if absent;
        the parent directory must exist.

    Notes
    -----
    The store never densifies the full source matrix: each pair is materialised
    by slicing only its ``pair_index`` rows.
    """

    def __init__(
        self,
        pair_index: Mapping[PairID, np.ndarray],
        source: _anndata.AnnData | str | Path | object,
        manifest: Mapping,
        *,
        audit_path: str | Path,
    ) -> None:
        # Canonicalise the pair_index keys to plain 2-tuples for stable lookup.
        self._pair_index: dict[PairID, np.ndarray] = {
            self._canonical(pair): np.asarray(rows) for pair, rows in pair_index.items()
        }
        self._source = source
        self._manifest = manifest
        self._audit_path = Path(audit_path)

        roles = manifest["roles"]
        self._double_ids: frozenset[PairID] = frozenset(
            self._canonical(p) for p in roles["sealed_double_unseen"]
        )
        self._single_ids: frozenset[PairID] = frozenset(
            self._canonical(p) for p in roles["sealed_single_unseen"]
        )
        self._sealed_ids: frozenset[PairID] = self._double_ids | self._single_ids
        self._manifest_checksum: str = manifest["checksum"]

    # ------------------------------------------------------------------
    # Pair-id canonicalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical(pair: Sequence[str]) -> PairID:
        """Return the canonical ``(min, max)`` 2-tuple for a pair.

        Parameters
        ----------
        pair : Sequence[str]
            A 2-element pair (tuple or list) of gene ids.

        Returns
        -------
        tuple of str
            Canonical 2-tuple ordered by UTF-8 bytes (locale-free).
        """
        items = tuple(pair)
        if len(items) != 2:
            raise ComposeSealingError(f"pair id must have exactly 2 genes, got {items!r}")
        a, b = items
        return (a, b) if a.encode("utf-8") <= b.encode("utf-8") else (b, a)

    # ------------------------------------------------------------------
    # Public read path — unsealed (calibration) pairs only
    # ------------------------------------------------------------------

    def read_unsealed(self, pair_ids: Sequence[PairID]) -> Mapping[PairID, ObservedPair]:
        """Return populations for unsealed (non-sealed) calibration pairs.

        Parameters
        ----------
        pair_ids : Sequence[tuple of str]
            Canonical pair ids to materialise.

        Returns
        -------
        Mapping[tuple of str, ObservedPair]
            One :class:`ObservedPair` per requested pair.

        Raises
        ------
        ComposeSealingError
            If ANY requested id is in EITHER sealed role, or is unknown.
            Fail-closed: no partial results are returned.
        """
        canon = [self._canonical(p) for p in pair_ids]
        violations: list[PairID] = []
        for pid in canon:
            if pid in self._sealed_ids:
                violations.append(pid)
            elif pid not in self._pair_index:
                violations.append(pid)
        if violations:
            raise ComposeSealingError(
                f"read_unsealed denied for pair(s): {violations!r}. "
                "Sealed pairs (either sealed_double_unseen or sealed_single_unseen) "
                "must be accessed via evaluate_sealed_once; unknown pairs are not in "
                "this pair index."
            )
        return self._materialise_pairs(canon)

    # ------------------------------------------------------------------
    # Audited sealed access — once per audit_path, both regimes at once
    # ------------------------------------------------------------------

    def evaluate_sealed_once(
        self, run_id: str, pair_ids: Sequence[PairID]
    ) -> Mapping[PairID, ObservedPair]:
        """The single audited gateway to sealed outcome data (both regimes).

        Validates the COMPLETE requested set BEFORE materialising any row: the
        requested set must equal the registered sealed UNION exactly.

        Parameters
        ----------
        run_id : str
            Deterministic run identifier; the sealed cohort may be opened once
            per ``audit_path``.
        pair_ids : Sequence[tuple of str]
            Must equal the sealed union exactly.

        Returns
        -------
        Mapping[tuple of str, ObservedPair]
            One :class:`ObservedPair` per requested pair, both regimes.

        Raises
        ------
        ComposeSealingError
            On empty/duplicate/unknown/unsealed/missing/extra requests, on any
            prior access on this audit path, or on any other integrity violation.
        """
        canon = [self._canonical(p) for p in pair_ids]

        # 1. Validate the COMPLETE requested set == sealed union, exactly.
        self._assert_exact_sealed_union(canon)

        # 2. Refuse if ANY prior access exists on this audit path (fails closed
        #    on corrupt/partial audit lines).
        self._assert_not_previously_accessed(run_id)

        # 3. Claim the access by writing the durable audit record FIRST. A crash
        #    during materialisation (step 4) still consumes the access — the
        #    audit path is permanently burned. Never reopen by crash-retrying.
        self._write_audit_record(run_id, canon)

        # 4. Materialise data (after the audit is on disk).
        return self._materialise_pairs(canon)

    # ------------------------------------------------------------------
    # Audit count and records (read from the persisted audit file)
    # ------------------------------------------------------------------

    @property
    def sealed_access_count(self) -> int:
        """Number of recorded sealed accesses (reads the persisted audit file).

        Returns
        -------
        int
            Count of valid JSON records in the audit file, or 0 if the file does
            not exist. Uses :meth:`_read_audit_records`, so a corrupt or
            partially written line raises rather than inflating/deflating count.
        """
        return len(self._read_audit_records())

    def audit_records(self) -> tuple[dict, ...]:
        """Return the persisted audit records as an immutable tuple.

        Returns
        -------
        tuple of dict
            One dict per durable JSONL audit record (empty if none).

        Raises
        ------
        ComposeSealingError
            If any audit line is corrupt or partially written (fails closed).
        """
        return tuple(self._read_audit_records())

    # ------------------------------------------------------------------
    # Private — validation
    # ------------------------------------------------------------------

    def _assert_exact_sealed_union(self, canon: list[PairID]) -> None:
        """Raise unless ``canon`` equals the sealed union exactly.

        Refuses empty requests, duplicates, unknown/unsealed ids, missing
        members (strict subset) and extra ids (superset). Validates the whole
        set before any row is read.

        Parameters
        ----------
        canon : list of tuple of str
            Canonicalised requested pair ids.

        Raises
        ------
        ComposeSealingError
            On any deviation from an exact match with the sealed union.
        """
        if not canon:
            raise ComposeSealingError(
                "evaluate_sealed_once requires the exact sealed union; got an empty request."
            )
        # Duplicate detection (the union itself is duplicate-free).
        seen: set[PairID] = set()
        duplicates: list[PairID] = []
        for pid in canon:
            if pid in seen:
                duplicates.append(pid)
            seen.add(pid)
        if duplicates:
            raise ComposeSealingError(
                f"evaluate_sealed_once received duplicate pair id(s): {duplicates!r}. "
                "The requested set must equal the sealed union exactly."
            )

        requested = seen  # now a true set, duplicate-free
        missing = self._sealed_ids - requested
        extra = requested - self._sealed_ids
        if missing or extra:
            raise ComposeSealingError(
                "evaluate_sealed_once requires the requested set to equal the registered "
                "sealed union (sealed_double_unseen ∪ sealed_single_unseen) exactly. "
                f"missing: {sorted(missing)!r}; extra/unsealed/unknown: {sorted(extra)!r}."
            )

    def _assert_not_previously_accessed(self, run_id: str) -> None:
        """Raise if ANY prior access exists on this audit path.

        Done against the durable on-disk audit so the once-only guarantee holds
        across separate processes and across run ids. Fails closed on corrupt
        audit lines (via :meth:`_read_audit_records`).

        Parameters
        ----------
        run_id : str
            The run identifier attempting access.

        Raises
        ------
        ComposeSealingError
            If any audit record already exists for this audit path.
        """
        records = self._read_audit_records()
        if records:
            existing = records[0]["run_id"]
            if existing == run_id:
                raise ComposeSealingError(
                    f"sealed cohort already opened for run {run_id!r}: "
                    "evaluate_sealed_once may be called exactly once per audit path."
                )
            raise ComposeSealingError(
                f"sealed cohort already opened for run {existing!r}: a second access under "
                f"run_id {run_id!r} is not permitted. The sealed cohort may be opened once."
            )

    # ------------------------------------------------------------------
    # Private — materialisation (bounded, no global densify)
    # ------------------------------------------------------------------

    def _materialise_pairs(self, canon: list[PairID]) -> dict[PairID, ObservedPair]:
        """Materialise one :class:`ObservedPair` per id (bounded per pair).

        Parameters
        ----------
        canon : list of tuple of str
            Canonical pair ids (assumed validated by the caller).

        Returns
        -------
        dict[tuple of str, ObservedPair]
        """
        result: dict[PairID, ObservedPair] = {}
        for pid in canon:
            rows = self._pair_index[pid]
            cells = self._slice_rows(rows)
            result[pid] = ObservedPair(pair_id=pid, cells=cells)
        return result

    def _slice_rows(self, row_indices: np.ndarray) -> np.ndarray:
        """Extract and densify exactly the rows at *row_indices*.

        The only place densification occurs. Only one pair's bounded rows are
        ever materialised at once; the full matrix is never densified.

        Parameters
        ----------
        row_indices : np.ndarray
            Integer row positions to extract.

        Returns
        -------
        np.ndarray
            Dense ``(len(row_indices), n_genes)`` array.
        """
        if isinstance(self._source, (str, Path)):
            import anndata as ad

            adata = ad.read_h5ad(Path(self._source), backed="r")
            try:
                chunk = adata.X[row_indices]
            finally:
                adata.file.close()
        else:
            chunk = self._source.X[row_indices]

        if sp.issparse(chunk):
            return chunk.toarray()
        return np.asarray(chunk)

    # ------------------------------------------------------------------
    # Private — durable audit JSONL
    # ------------------------------------------------------------------

    def _read_audit_records(self) -> list[dict]:
        """Read all audit records from the persisted JSONL file.

        Fails closed: a corrupt or partially written line raises rather than
        being skipped (which would silently deflate the access count).

        Returns
        -------
        list of dict
            Parsed JSON records; empty list if the file is absent.

        Raises
        ------
        ComposeSealingError
            If a non-empty line cannot be parsed as JSON.
        """
        if not self._audit_path.exists():
            return []
        records: list[dict] = []
        for lineno, raw in enumerate(
            self._audit_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = raw.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ComposeSealingError(
                    f"corrupt or partial audit line {lineno} in {self._audit_path!r}: {exc}. "
                    "Refusing access (fail-closed): a tampered audit cannot be trusted."
                ) from exc
        return records

    def _write_audit_record(self, run_id: str, canon: list[PairID]) -> None:
        """Append an immutable audit record to the durable JSONL audit file.

        Called by :meth:`evaluate_sealed_once` BEFORE materialisation so that a
        crash during data loading still consumes the access (fail-safe toward
        sealing). The audit path is permanently burned once this record exists.

        The record contains: ``run_id``, sorted canonical ``pair_ids`` (each a
        ``[a, b]`` list), per-role ``role_counts``, the immutable
        ``manifest_checksum`` and a ``request_checksum`` over the sorted pair
        list.

        Parameters
        ----------
        run_id : str
            The run identifier.
        canon : list of tuple of str
            The (validated) requested canonical pair ids.
        """
        sorted_pairs = sorted([list(p) for p in canon])
        record = {
            "run_id": run_id,
            "pair_ids": sorted_pairs,
            "role_counts": {
                "sealed_double_unseen": len(self._double_ids),
                "sealed_single_unseen": len(self._single_ids),
            },
            "manifest_checksum": self._manifest_checksum,
            "request_checksum": sha256_json(sorted_pairs),
        }
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with self._audit_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
