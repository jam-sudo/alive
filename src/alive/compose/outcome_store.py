"""Structurally sealed outcome store for COMPOSE-K562-v1 combo outcomes.

This module is THE seal boundary for COMPOSE-K562-v1 Phase 2b (CLAUDE.md#seal
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
SealedAccessClaim
    Immutable receipt for a DURABLY consumed sealed access, returned by
    :meth:`ComposeOutcomeStore.claim_sealed_access`. The consumption boundary is
    split into ``claim_sealed_access`` (validate + write the durable audit FIRST)
    and ``materialize_claimed`` (verify the claim against the persisted audit,
    then materialise); ``evaluate_sealed_once`` is retained as a façade over both.
OutcomeStore
    Runtime-checkable protocol that :class:`ComposeOutcomeStore` satisfies.
ComposeOutcomeStore
    Concrete store backed by a canonical ``pair_index``, a source AnnData/path,
    an immutable pair-split manifest and an append-only JSONL audit.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np
import scipy.sparse as sp

from alive.compose.split import (
    SEALED_DOUBLE_UNSEEN_ROLE_NAME,
    SEALED_ROLE_NAMES,
    SEALED_SINGLE_UNSEEN_ROLE_NAME,
    verify_split_manifest,
)
from alive.io import atomic_write_once
from alive.provenance import sha256_json

if TYPE_CHECKING:
    import anndata as _anndata

#: The sealed roles whose union forms the sealed cohort.
_SEALED_ROLES = SEALED_ROLE_NAMES

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
# SealedAccessClaim value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SealedAccessClaim:
    """Immutable receipt for a DURABLY consumed sealed access.

    Produced ONLY by :meth:`ComposeOutcomeStore.claim_sealed_access` AFTER the
    durable audit record has been written (the atomic once-only consumption
    point). Its existence is proof the seal was durably burned; a pre-audit
    failure raises before any claim is ever constructed.

    The claim carries a durable ``audit_reference`` derived FROM the persisted
    audit record so that :meth:`ComposeOutcomeStore.materialize_claimed` can
    cross-verify the claim against the on-disk audit (run/request/reference
    mismatch → fail closed) before materialising any observed row.

    Parameters
    ----------
    run_id : str
        The run identifier recorded in the durable audit.
    audit_reference : str
        Durable identity of the written audit record (its canonical SHA-256).
    request_checksum : str
        The audit record's ``request_checksum`` over the sorted canonical union.
    manifest_checksum : str
        The immutable split-manifest checksum recorded in the audit.
    pair_ids : tuple of tuple of str
        The canonical sealed union to materialise (pair ids only — never data).
    """

    run_id: str
    audit_reference: str
    request_checksum: str
    manifest_checksum: str
    pair_ids: tuple[PairID, ...]


# ---------------------------------------------------------------------------
# Synthetic-fixture corpus attestation + committed allowlist
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixtureCorpusAttestation:
    """Immutable identity of a sanctioned synthetic-fixture corpus.

    Carried by a :class:`FixtureOutcomeStore` and validated against the committed
    :data:`_FIXTURE_CORPUS_ALLOWLIST` by :func:`build_fixture_outcome_store` — the
    only sanctioned fixture-store constructor. It replaces the old mutable
    ``_compose_fixture_marker`` boolean (which any caller could set on a REAL
    store), so fixture-vs-scientific routing is a type + allowlist decision, not a
    spoofable attribute.

    Parameters
    ----------
    corpus_id : str
        Stable identifier of the synthetic fixture corpus.
    source_sha256 : str
        Committed digest identifying the synthetic-source bytes of the corpus.
    builder_code_sha256 : str
        Committed digest identifying the fixture-builder code that produced it.
    """

    corpus_id: str
    source_sha256: str
    builder_code_sha256: str


# C0-forward-declared synthetic-fixture corpus identity. Sub-project C (§6) will
# replace these with the real synthetic-source / builder digests and wire
# build_fixture_outcome_store to compute source_sha256 from the passed source and
# compare (fixture-vs-real-source binding). At C0 the factory only checks that the
# passed triple is one of these committed allowlisted triples; it does NOT yet
# digest the actual source bytes.
_FIXTURE_CORPUS_V1_SOURCE_SHA = hashlib.sha256(
    b"compose_c_fixture_v1::synthetic-source::c0-forward-declared"
).hexdigest()
_FIXTURE_CORPUS_V1_BUILDER_SHA = hashlib.sha256(
    b"compose_c_fixture_v1::builder-code::c0-forward-declared"
).hexdigest()

#: The single forward-declared allowlisted fixture corpus (see note above).
FIXTURE_CORPUS_V1 = FixtureCorpusAttestation(
    corpus_id="compose_c_fixture_v1",
    source_sha256=_FIXTURE_CORPUS_V1_SOURCE_SHA,
    builder_code_sha256=_FIXTURE_CORPUS_V1_BUILDER_SHA,
)

#: Committed allowlist of sanctioned synthetic fixture corpora (extend as new
#: fixture corpora are added). :func:`build_fixture_outcome_store` fails closed
#: for any attestation triple not in this set.
_FIXTURE_CORPUS_ALLOWLIST: frozenset[FixtureCorpusAttestation] = frozenset({FIXTURE_CORPUS_V1})


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

    def claim_sealed_access(self, run_id: str, pair_ids: Sequence[PairID]) -> SealedAccessClaim:
        """Durably CLAIM the sealed access (the atomic consumption point).

        Validates the exact union, refuses prior access and writes the durable
        audit record FIRST, then returns an immutable :class:`SealedAccessClaim`.

        Parameters
        ----------
        run_id : str
            Deterministic run identifier; the cohort may be claimed once per
            ``audit_path``.
        pair_ids : Sequence[tuple of str]
            Must equal the registered sealed UNION exactly.

        Returns
        -------
        SealedAccessClaim
            The durable claim receipt (carries the ``audit_reference``).

        Raises
        ------
        ComposeSealingError
            On any integrity violation BEFORE the audit write, or if the cohort
            was already claimed.
        """
        ...

    def materialize_claimed(self, claim: SealedAccessClaim) -> Mapping[PairID, ObservedPair]:
        """Materialise the observed pairs for a durable claim.

        Verifies ``claim`` matches the persisted audit (run/request/reference
        mismatch → fail closed), then materialises the claim's union.

        Parameters
        ----------
        claim : SealedAccessClaim
            A claim produced by :meth:`claim_sealed_access`.

        Returns
        -------
        Mapping[tuple of str, ObservedPair]
            Mapping from pair id to materialised :class:`ObservedPair`.

        Raises
        ------
        ComposeSealingError
            If the claim does not match the persisted audit.
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
    materialization_validator : callable or None, optional
        Driver-supplied source/row validator invoked only after a durable claim
        has been verified and immediately before the first source row is read.
        This keeps sealed-source semantic parsing on the consumed side of the
        audit boundary. It may return a validated source object, which atomically
        replaces the lazy path before row materialisation; ``None`` retains the
        original source.

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
        materialization_validator: Callable[[], object | None] | None = None,
    ) -> None:
        try:
            verify_split_manifest(dict(manifest))
        except ValueError as exc:
            raise ComposeSealingError(f"invalid split manifest: {exc}") from exc

        # Canonicalise without silently collapsing reversed duplicate keys, and
        # freeze validated row vectors so callers cannot retarget a pair later.
        self._pair_index = {}
        claimed_rows: set[int] = set()
        source_rows = getattr(getattr(source, "X", None), "shape", (None,))[0]
        for raw_pair, raw_rows in pair_index.items():
            pair = self._canonical(raw_pair)
            if pair in self._pair_index:
                raise ComposeSealingError(
                    f"pair_index contains a canonical key collision: {pair!r}"
                )
            rows = np.asarray(raw_rows)
            if rows.ndim != 1 or rows.size == 0:
                raise ComposeSealingError(f"pair_index[{pair!r}] must be a non-empty 1-D array")
            if rows.dtype.kind not in {"i", "u"} or rows.dtype.kind == "b":
                raise ComposeSealingError(f"pair_index[{pair!r}] must contain integer row indices")
            rows = np.array(rows, dtype=np.int64, copy=True)
            if np.any(rows < 0) or len(np.unique(rows)) != len(rows):
                raise ComposeSealingError(
                    f"pair_index[{pair!r}] contains negative or duplicate row indices"
                )
            if source_rows is not None and np.any(rows >= int(source_rows)):
                raise ComposeSealingError(f"pair_index[{pair!r}] contains an out-of-range row")
            overlap = claimed_rows.intersection(int(row) for row in rows)
            if overlap:
                raise ComposeSealingError(
                    f"pair_index rows overlap across pairs; first overlap={min(overlap)}"
                )
            claimed_rows.update(int(row) for row in rows)
            rows.setflags(write=False)
            self._pair_index[pair] = rows
        self._source = source
        self._manifest = manifest
        self._audit_path = Path(audit_path)
        self._materialization_validator = materialization_validator
        self._source_validated = False

        # Guard the manifest at construction: a malformed manifest must fail
        # closed via ComposeSealingError, never a raw KeyError mid-access.
        try:
            roles = manifest["roles"]
            self._sealed_ids_by_role: dict[str, frozenset[PairID]] = {
                role: frozenset(self._canonical(p) for p in roles[role]) for role in _SEALED_ROLES
            }
            self._double_ids = self._sealed_ids_by_role[SEALED_DOUBLE_UNSEEN_ROLE_NAME]
            self._single_ids = self._sealed_ids_by_role[SEALED_SINGLE_UNSEEN_ROLE_NAME]
            self._manifest_checksum: str = manifest["checksum"]
        except KeyError as exc:
            raise ComposeSealingError(
                f"malformed manifest: missing required key {exc}. "
                f"Expected 'roles' (with {list(_SEALED_ROLES)!r}) and 'checksum'."
            ) from exc
        self._sealed_ids: frozenset[PairID] = frozenset().union(*self._sealed_ids_by_role.values())
        manifest_pairs = {self._canonical(pair) for role in roles.values() for pair in role}
        if set(self._pair_index) != manifest_pairs:
            missing = sorted(manifest_pairs - set(self._pair_index))
            extra = sorted(set(self._pair_index) - manifest_pairs)
            raise ComposeSealingError(
                "pair_index keys must equal the complete manifest role union "
                f"(missing={missing!r}, extra={extra!r})"
            )

        # Fail closed BEFORE any access: every sealed pair must be present in the
        # pair_index. Otherwise _materialise_pairs would raise a raw KeyError only
        # AFTER evaluate_sealed_once has already burned the audit. Reject the
        # misconfigured index here so no access can ever be consumed.
        missing_sealed = sorted(self._sealed_ids - set(self._pair_index))
        if missing_sealed:
            raise ComposeSealingError(
                f"pair_index is missing {len(missing_sealed)} sealed pair(s): "
                f"{missing_sealed!r}. Every sealed pair (sealed_double_unseen ∪ "
                "sealed_single_unseen) must have bounded rows in pair_index before "
                "the seal boundary can be constructed."
            )

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
        if not isinstance(a, str) or not isinstance(b, str) or not a or not b:
            raise ComposeSealingError(f"pair genes must be non-empty strings, got {items!r}")
        if a == b:
            raise ComposeSealingError(f"self-pair is not valid: {items!r}")
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

        Notes
        -----
        Retained as a thin façade over the consumption-boundary split
        (:meth:`claim_sealed_access` then :meth:`materialize_claimed`) so the
        exact-union / refuse-prior / write-once-audit semantics are unchanged for
        existing non-terminal callers. The durable audit is still written BEFORE
        any row is materialised.
        """
        claim = self.claim_sealed_access(run_id, pair_ids)
        return self.materialize_claimed(claim)

    def claim_sealed_access(self, run_id: str, pair_ids: Sequence[PairID]) -> SealedAccessClaim:
        """Durably CLAIM the sealed access — the atomic once-only consumption point.

        Performs the pre-materialisation half of the sealed gateway: validate the
        exact union, refuse any prior access, then write the durable audit record
        FIRST. The written record IS the consumption boundary: a crash after this
        returns still leaves the audit path permanently burned. The returned
        :class:`SealedAccessClaim` carries a durable ``audit_reference`` derived
        from the persisted record.

        Parameters
        ----------
        run_id : str
            Deterministic run identifier; the sealed cohort may be claimed once
            per ``audit_path``.
        pair_ids : Sequence[tuple of str]
            Must equal the sealed union exactly.

        Returns
        -------
        SealedAccessClaim
            The durable claim receipt.

        Raises
        ------
        ComposeSealingError
            On empty/duplicate/unknown/unsealed/missing/extra requests, on any
            prior access on this audit path, or on any other integrity violation.
            Every such failure is raised BEFORE the audit write, so no access is
            consumed.
        """
        canon = [self._canonical(p) for p in pair_ids]

        # 1. Validate the COMPLETE requested set == sealed union, exactly.
        self._assert_exact_sealed_union(canon)

        # 2. Refuse if ANY prior access exists on this audit path (fails closed
        #    on corrupt/partial audit lines).
        self._assert_not_previously_accessed(run_id)

        # 3. Claim the access by writing the durable audit record FIRST. This is
        #    THE consumption boundary: a crash during materialisation still burns
        #    the audit path. Never reopen by crash-retrying.
        record = self._write_audit_record(run_id, canon)

        return SealedAccessClaim(
            run_id=run_id,
            audit_reference=self._audit_reference(record),
            request_checksum=record["request_checksum"],
            manifest_checksum=record["manifest_checksum"],
            pair_ids=tuple(canon),
        )

    def materialize_claimed(self, claim: SealedAccessClaim) -> dict[PairID, ObservedPair]:
        """Materialise the observed pairs backing a durable claim.

        Verifies the ``claim`` against the persisted audit (a run_id, request or
        reference mismatch fails closed) BEFORE materialising any row, then slices
        only the claim's bounded pair rows (no global densification).

        Parameters
        ----------
        claim : SealedAccessClaim
            A claim produced by :meth:`claim_sealed_access` for this audit path.

        Returns
        -------
        dict[tuple of str, ObservedPair]
            One :class:`ObservedPair` per claimed pair.

        Raises
        ------
        ComposeSealingError
            If the persisted audit is absent, does not match the claim's
            ``run_id`` / ``request_checksum`` / ``audit_reference``, or if the
            claim's ``pair_ids`` do not re-derive the persisted sealed union
            (the payload selector is authenticated before any row is sliced).
        """
        records = self._read_audit_records()
        if not records:
            raise ComposeSealingError(
                "materialize_claimed refused: no durable audit record backs this "
                f"claim (run {claim.run_id!r}). The seal was never durably consumed."
            )
        record = records[0]
        persisted_reference = self._audit_reference(record)
        if (
            record.get("run_id") != claim.run_id
            or record.get("request_checksum") != claim.request_checksum
            or persisted_reference != claim.audit_reference
        ):
            raise ComposeSealingError(
                "materialize_claimed refused: the claim does not match the persisted "
                f"audit (claim run {claim.run_id!r}, audit run "
                f"{record.get('run_id')!r}). Fail-closed: a mismatched claim cannot "
                "materialise sealed outcomes."
            )
        # Authenticate the PAYLOAD SELECTOR, not just the claim's identity. The
        # checks above validate run_id/request/reference, but the pairs actually
        # materialised must be proven to be the sealed union — re-derive the
        # request checksum from the claim's pair_ids exactly as _write_audit_record
        # does and require it equals the persisted checksum. Otherwise a claim with
        # genuine identity strings but forged (in-index) pair_ids could slice
        # non-sealed rows.
        claim_sorted = sorted([list(p) for p in claim.pair_ids])
        if sha256_json(claim_sorted) != record["request_checksum"]:
            raise ComposeSealingError(
                "materialize_claimed refused: the claim's pair_ids do not re-derive "
                "the persisted sealed union (payload-selector checksum mismatch). "
                "Fail-closed: a mismatched claim cannot materialise sealed outcomes."
            )
        # Slice from the AUTHENTICATED source of truth — the persisted record's
        # pair_ids — so no unauthenticated field feeds the materialised payload.
        # A genuine claim is unchanged: claim.pair_ids canonicalises to record's.
        sealed_pairs = [tuple(p) for p in record["pair_ids"]]
        if self._materialization_validator is not None and not self._source_validated:
            validated_source = self._materialization_validator()
            if validated_source is not None:
                self._source = validated_source
            self._source_validated = True
        return self._materialise_pairs(sealed_pairs)

    @staticmethod
    def _audit_reference(record: Mapping) -> str:
        """Return the durable identity (canonical SHA-256) of an audit record.

        Parameters
        ----------
        record : Mapping
            A durable audit record (as written, or as read back from disk).

        Returns
        -------
        str
            Lowercase hex SHA-256 over the record's canonical JSON — stable across
            a write / json round-trip so a persisted record recomputes the same
            reference the claim carries.
        """
        return sha256_json(dict(record))

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

    def _write_audit_record(self, run_id: str, canon: list[PairID]) -> dict:
        """Append an immutable audit record to the durable JSONL audit file.

        Called by :meth:`claim_sealed_access` BEFORE materialisation so that a
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

        Returns
        -------
        dict
            The exact record written (so the caller can derive a durable
            ``audit_reference`` from it).
        """
        sorted_pairs = sorted([list(p) for p in canon])
        record = {
            "run_id": run_id,
            "pair_ids": sorted_pairs,
            "role_counts": {role: len(self._sealed_ids_by_role[role]) for role in _SEALED_ROLES},
            "manifest_checksum": self._manifest_checksum,
            "request_checksum": sha256_json(sorted_pairs),
        }
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        try:
            atomic_write_once(self._audit_path, line, encoding="utf-8")
        except FileExistsError as exc:
            raise ComposeSealingError(
                f"sealed cohort was claimed concurrently at {str(self._audit_path)!r}; "
                "the seal may be opened exactly once"
            ) from exc
        return record


# ---------------------------------------------------------------------------
# Synthetic-fixture store subtype + sanctioned constructor
# ---------------------------------------------------------------------------


class FixtureOutcomeStore(ComposeOutcomeStore):
    """A synthetic-fixture sealed store — the ONLY store type the bounded fixture
    Phase-2b path (:func:`alive.compose.phase2b.run_phase2b_fixture`) accepts.

    Built solely by :func:`build_fixture_outcome_store`, which validates the
    carried :class:`FixtureCorpusAttestation` against the committed
    :data:`_FIXTURE_CORPUS_ALLOWLIST`. There is no mutable marker: fixture-vs-
    scientific routing is decided by ``isinstance`` + an allowlisted attestation,
    so setting an attribute on a REAL :class:`ComposeOutcomeStore` can never make
    it read as a fixture store. The subtype ADDS only the attestation; the seal
    boundary (:class:`ComposeOutcomeStore`) is inherited unchanged.

    Parameters
    ----------
    *args
        Positional arguments forwarded to :class:`ComposeOutcomeStore`
        (``pair_index``, ``source``, ``manifest``).
    fixture_corpus_attestation : FixtureCorpusAttestation
        The corpus identity this fixture store attests to.
    **kwargs
        Keyword arguments forwarded to :class:`ComposeOutcomeStore` (e.g.
        ``audit_path``).
    """

    def __init__(
        self,
        *args,
        fixture_corpus_attestation: FixtureCorpusAttestation,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_fixture_corpus_attestation", fixture_corpus_attestation)

    @property
    def fixture_corpus_attestation(self) -> FixtureCorpusAttestation:
        """The validated synthetic-fixture corpus attestation this store carries."""
        return self._fixture_corpus_attestation


def build_fixture_outcome_store(
    pair_index: Mapping[PairID, np.ndarray],
    source: _anndata.AnnData | str | Path | object,
    manifest: Mapping,
    *,
    audit_path: str | Path,
    corpus_id: str,
    source_sha256: str,
    builder_code_sha256: str,
    materialization_validator: Callable[[], object | None] | None = None,
) -> FixtureOutcomeStore:
    """Build the ONLY sanctioned :class:`FixtureOutcomeStore`.

    Validates the ``(corpus_id, source_sha256, builder_code_sha256)`` triple
    against the committed :data:`_FIXTURE_CORPUS_ALLOWLIST` and FAILS CLOSED
    (:class:`ComposeSealingError`) if it is not allowlisted. This is the single
    place a fixture store may be minted, so the bounded fixture Phase-2b path can
    trust the type without a spoofable marker.

    Parameters
    ----------
    pair_index, source, manifest, audit_path
        Forwarded verbatim to :class:`ComposeOutcomeStore` (see its docstring).
    corpus_id : str
        Identifier of the synthetic fixture corpus; must be allowlisted.
    source_sha256 : str
        Committed synthetic-source digest; the full triple must match an
        allowlisted entry.
    builder_code_sha256 : str
        Committed fixture-builder-code digest; the full triple must match an
        allowlisted entry.

    Returns
    -------
    FixtureOutcomeStore
        A fixture store carrying the validated attestation.

    Raises
    ------
    ComposeSealingError
        If the attestation triple is not in the committed allowlist.
    """
    attestation = FixtureCorpusAttestation(
        corpus_id=corpus_id,
        source_sha256=source_sha256,
        builder_code_sha256=builder_code_sha256,
    )
    if attestation not in _FIXTURE_CORPUS_ALLOWLIST:
        raise ComposeSealingError(
            f"fixture corpus {attestation!r} is not in the committed allowlist; "
            "build_fixture_outcome_store refuses to mint an unattested fixture store"
        )
    return FixtureOutcomeStore(
        pair_index,
        source,
        manifest,
        audit_path=audit_path,
        materialization_validator=materialization_validator,
        fixture_corpus_attestation=attestation,
    )


# ---------------------------------------------------------------------------
# Standalone obs-label alignment validator (phase2b, post-claim)
# ---------------------------------------------------------------------------


def validate_pair_index_against_source_obs(
    source: object,
    pair_index: Mapping[PairID, np.ndarray],
    manifest: Mapping,
    *,
    perturbation_col: str = "perturbation",
    combo_sep: str = "_",
) -> None:
    """Verify each pair-index row's obs perturbation label canonicalizes to its pair.

    The production driver invokes this validator through
    ``materialization_validator`` only after the durable access claim has been
    installed. Callers outside that driver remain responsible for placing it on
    the consumed side of their own seal boundary.

    Reads ``source.obs[perturbation_col]`` (a str label per row) and, for every
    (canonical pair -> row indices) entry, asserts every indexed row's label
    parses (on ``combo_sep``) and canonicalizes to that exact pair. Fails closed
    on a missing obs column, an unparsable label, or any mismatch. Reuses
    :meth:`ComposeOutcomeStore._canonical` so the parsed label and the pair key
    use the SAME canonicalization.

    This is deliberately a STANDALONE function, not part of
    :meth:`ComposeOutcomeStore.__init__`: the store ctor / preflight / phase2a
    never read ``source.obs`` (a capability restriction). Only the phase2b
    production driver calls this, AFTER confirmation and BEFORE constructing the
    sealed store. The ``manifest`` argument is part of that driver's call
    contract; the manifest key-set is already validated inside
    :meth:`ComposeOutcomeStore.__init__`, so this validator does not re-read it.

    Parameters
    ----------
    source : object
        Any object exposing ``.obs`` with a ``perturbation_col`` column of str
        labels aligned to source rows (duck-typed; anndata is never imported).
    pair_index : Mapping[tuple of str, np.ndarray]
        Canonical pair -> bounded int row-index array.
    manifest : Mapping
        The pair-split manifest (part of the driver call contract; not re-read
        here because the store ctor already validates its key-set).
    perturbation_col : str, optional
        Name of the obs column holding per-row perturbation labels.
    combo_sep : str, optional
        Separator joining the two gene ids inside a combo label.

    Raises
    ------
    ComposeSealingError
        If the obs column is missing/absent, a label is not a 2-gene combo
        token, or any indexed row's label canonicalizes to a different pair.
    """
    obs = getattr(source, "obs", None)
    if obs is None or perturbation_col not in getattr(obs, "columns", ()):
        raise ComposeSealingError(
            f"source obs is missing the {perturbation_col!r} perturbation column"
        )
    labels = obs[perturbation_col].to_numpy()
    for raw_pair, rows in pair_index.items():
        pair = ComposeOutcomeStore._canonical(raw_pair)
        for i in rows:
            label = str(labels[int(i)])
            parts = label.split(combo_sep)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ComposeSealingError(
                    f"row {int(i)} perturbation label {label!r} is not a 2-gene "
                    f"combo token on {combo_sep!r}"
                )
            observed = ComposeOutcomeStore._canonical((parts[0], parts[1]))
            if observed != pair:
                raise ComposeSealingError(
                    f"row {int(i)} perturbation label {label!r} canonicalizes to "
                    f"{observed!r}, but it is indexed under pair {pair!r}"
                )
