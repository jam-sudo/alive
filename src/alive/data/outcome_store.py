"""Structurally sealed outcome store for Replogle Perturb-seq data.

This module is THE central scientific-integrity mechanism of the ALIVE project.
It is the ONLY path for reading observed perturbed cell populations.

- Ordinary perturbation reads (:meth:`ReplogleOutcomeStore.read_unsealed`) are
  blocked for any id assigned to the ``sealed_evaluation`` split.
- The single audited path (:meth:`ReplogleOutcomeStore.evaluate_sealed_once`)
  permits exactly ONE access per ``run_id``, enforced durably across processes
  via a JSONL audit file written BEFORE data is materialised (fail-safe: a
  crash during materialisation still burns the run_id).
- Control cells are accessible via :meth:`ReplogleOutcomeStore.read_controls`.

Global invariant — no global densification
------------------------------------------
Each population is materialised by slicing only its rows from the expression
matrix (``source.X``) and calling ``.toarray()`` on that bounded submatrix.
The full matrix is NEVER densified.

Public API
----------
SealingError
    Raised on any attempt to breach the seal.
Population
    Frozen dataclass holding one perturbation's materialised cell matrix.
OutcomeStore
    Runtime-checkable protocol that :class:`ReplogleOutcomeStore` satisfies.
ReplogleOutcomeStore
    Concrete store backed by a :class:`~alive.data.replogle.ReplogleIndex` and
    a :class:`~alive.data.manifest.SplitManifest`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import anndata as ad
import numpy as np
import scipy.sparse as sp

from alive.io import atomic_write_once
from alive.provenance import sha256_json

if TYPE_CHECKING:
    import anndata as _anndata

    from alive.data.manifest import SplitManifest
    from alive.data.replogle import ReplogleIndex


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class SealingError(RuntimeError):
    """Raised on any attempt to breach the structural seal.

    Parameters
    ----------
    message : str
        Human-readable description of the violation.
    """


# ---------------------------------------------------------------------------
# Population value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Population:
    """Materialised expression for a single perturbation population.

    Parameters
    ----------
    perturbation_id : str
        Label identifying the perturbation (or the control value for controls).
    cells : np.ndarray
        Dense ``(n_cells, n_genes)`` expression matrix for this population only.
        Never the full AnnData matrix.
    """

    perturbation_id: str
    cells: np.ndarray


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class OutcomeStore(Protocol):
    """Protocol that all outcome stores must satisfy.

    Parameters satisfy the :func:`typing.runtime_checkable` check so that
    test doubles (spy stores) and the concrete store can both be validated
    with ``isinstance(obj, OutcomeStore)``.
    """

    def read_unsealed(self, perturbation_ids: Sequence[str]) -> dict[str, Population]:
        """Return populations for unsealed perturbation ids.

        Parameters
        ----------
        perturbation_ids : Sequence[str]
            Ids to materialise.  Must all be non-sealed, non-control, known ids.

        Returns
        -------
        dict[str, Population]
            Mapping from id to materialised :class:`Population`.

        Raises
        ------
        SealingError
            If any requested id is sealed, unknown, or is the control value.
        """
        ...

    def evaluate_sealed_once(
        self, run_id: str, perturbation_ids: Sequence[str]
    ) -> dict[str, Population]:
        """The single audited gateway to sealed outcome data.

        Parameters
        ----------
        run_id : str
            Deterministic run identifier.  Only the first call per run_id ever
            succeeds; subsequent calls (even from a fresh process) raise.
        perturbation_ids : Sequence[str]
            Ids to materialise.  Must all be in the ``sealed_evaluation`` split.

        Returns
        -------
        dict[str, Population]
            Mapping from id to materialised :class:`Population`.

        Raises
        ------
        SealingError
            If any id is not sealed, if the run_id has already been used, or on
            any integrity violation.
        """
        ...


# ---------------------------------------------------------------------------
# Concrete store
# ---------------------------------------------------------------------------


class ReplogleOutcomeStore:
    """Structurally sealed outcome store backed by a Replogle AnnData.

    Parameters
    ----------
    index : ReplogleIndex
        Metadata index built by :func:`~alive.data.replogle.build_index`.
    source : anndata.AnnData or str or Path
        In-memory AnnData or path to an ``.h5ad`` file.  If a path, the file is
        opened with ``backed="r"`` so the full matrix is never loaded into memory.
    manifest : SplitManifest
        Frozen split manifest built by
        :func:`~alive.data.manifest.build_manifest_from_index`.
    audit_path : str or Path
        Path to the durable JSONL audit file.  Each sealed access appends one
        JSON record.  The file is created if absent; the directory must exist.
    """

    def __init__(
        self,
        index: ReplogleIndex,
        source: _anndata.AnnData | str | Path,
        manifest: SplitManifest,
        *,
        audit_path: str | Path,
    ) -> None:
        self._index = index
        self._source = source
        self._manifest = manifest
        self._audit_path = Path(audit_path)
        self._sealed_ids: frozenset[str] = frozenset(manifest.ids_for("sealed_evaluation"))

    # ------------------------------------------------------------------
    # Public read path — unsealed ids only
    # ------------------------------------------------------------------

    def read_unsealed(self, perturbation_ids: Sequence[str]) -> dict[str, Population]:
        """Return populations for unsealed (non-sealed-evaluation) perturbation ids.

        Parameters
        ----------
        perturbation_ids : Sequence[str]
            Ids to materialise.

        Returns
        -------
        dict[str, Population]
            One :class:`Population` per requested id.

        Raises
        ------
        SealingError
            If ANY requested id is in the sealed cohort, is the control value,
            or is unknown.  Fail-closed: no partial results are returned.
        """
        ids = list(perturbation_ids)
        # Validate ALL ids before materialising ANY data (fail-closed)
        violations: list[str] = []
        for pid in ids:
            if pid == self._index.schema.control_value:
                violations.append(pid)
            elif pid in self._sealed_ids:
                violations.append(pid)
            elif pid not in self._index.perturbation_indices:
                violations.append(pid)
        if violations:
            raise SealingError(
                f"read_unsealed denied for id(s): {violations!r}.  "
                "Sealed ids must be accessed via evaluate_sealed_once; "
                "unknown ids are not in this index; "
                "use read_controls() for control cells."
            )

        return self._materialise_populations(ids)

    # ------------------------------------------------------------------
    # Audited sealed access — once per run_id, durable across processes
    # ------------------------------------------------------------------

    def evaluate_sealed_once(
        self, run_id: str, perturbation_ids: Sequence[str]
    ) -> dict[str, Population]:
        """The single audited gateway to sealed outcome data.

        Parameters
        ----------
        run_id : str
            Deterministic run identifier; only one call per run_id is permitted.
        perturbation_ids : Sequence[str]
            Must all be in the ``sealed_evaluation`` split.

        Returns
        -------
        dict[str, Population]
            One :class:`Population` per requested id.

        Raises
        ------
        SealingError
            If any id is not sealed, if run_id already has an audit record, or
            on any other integrity violation.
        """
        ids = list(perturbation_ids)

        # 1. Validate ALL ids are in the sealed split
        non_sealed = [pid for pid in ids if pid not in self._sealed_ids]
        if non_sealed:
            raise SealingError(
                f"evaluate_sealed_once requires all ids to be in the sealed_evaluation split; "
                f"non-sealed id(s): {non_sealed!r}"
            )

        # 2. Check durable audit: refuse if run_id already recorded
        self._assert_not_previously_accessed(run_id)

        # 3. Claim the access by writing the durable audit record FIRST.
        #    A crash during materialisation (step 4) still counts as a consumed
        #    access — the run_id is permanently burned.  Never reopen the seal
        #    by crash-retrying with the same run_id; use a new run_id instead.
        self._write_audit_record(run_id, ids)

        # 4. Materialise data (after the audit is on disk)
        populations = self._materialise_populations(ids)

        return populations

    # ------------------------------------------------------------------
    # Control accessor (not sealed, not a perturbation)
    # ------------------------------------------------------------------

    def read_controls(self) -> Population:
        """Materialise the control population.

        Returns
        -------
        Population
            :class:`Population` with ``perturbation_id`` equal to the schema
            control value and ``cells`` of shape ``(n_control_cells, n_genes)``.
        """
        ctrl_val = self._index.schema.control_value
        ctrl_indices = self._index.control_indices
        cells = self._slice_rows(ctrl_indices)
        return Population(perturbation_id=ctrl_val, cells=cells)

    # ------------------------------------------------------------------
    # Audit count (reads from persisted audit file)
    # ------------------------------------------------------------------

    @property
    def sealed_access_count(self) -> int:
        """Number of recorded sealed accesses (reads the persisted audit file).

        Returns
        -------
        int
            Count of valid JSON records in the audit file, or 0 if the file
            does not exist.  Uses :meth:`_read_audit_records` so that corrupt
            or partially written lines raise rather than inflating the count.
        """
        return len(self._read_audit_records())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _materialise_populations(self, ids: list[str]) -> dict[str, Population]:
        """Materialise one population at a time for each id.

        Parameters
        ----------
        ids : list[str]
            Perturbation ids (assumed already validated by the caller).

        Returns
        -------
        dict[str, Population]
        """
        result: dict[str, Population] = {}
        for pid in ids:
            row_indices = self._index.cell_indices(pid)
            cells = self._slice_rows(row_indices)
            result[pid] = Population(perturbation_id=pid, cells=cells)
        return result

    def _slice_rows(self, row_indices: np.ndarray) -> np.ndarray:
        """Extract and densify exactly the rows at *row_indices*.

        This is the only place where densification occurs.  Only the rows
        corresponding to one population are ever materialised at once.

        Parameters
        ----------
        row_indices : np.ndarray
            Sorted integer row positions to extract.

        Returns
        -------
        np.ndarray
            Dense ``(len(row_indices), n_genes)`` array.
        """
        if isinstance(self._source, (str, Path)):
            # Backed file: open, slice, close
            adata = ad.read_h5ad(Path(self._source), backed="r")
            try:
                expr = adata.X
                chunk = expr[row_indices]
            finally:
                adata.file.close()
        else:
            expr = self._source.X
            chunk = expr[row_indices]

        # Densify only the bounded per-population chunk
        if sp.issparse(chunk):
            return chunk.toarray()
        # Handle backed sparse datasets that return a numpy array on slice
        return np.asarray(chunk)

    def _read_audit_records(self) -> list[dict]:
        """Read all audit records from the persisted JSONL file.

        Returns
        -------
        list[dict]
            Parsed JSON records; empty list if file absent.
        """
        if not self._audit_path.exists():
            return []
        records: list[dict] = []
        for line in self._audit_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
        return records

    def _assert_not_previously_accessed(self, run_id: str) -> None:
        """Raise :class:`SealingError` if *run_id* appears in the audit file.

        This check is done against the durable on-disk audit so that the
        once-only guarantee holds across separate processes.

        Parameters
        ----------
        run_id : str
            The run identifier to check.

        Raises
        ------
        SealingError
            If any audit record carries this run_id, or if ANY prior access
            exists (the sealed cohort may be opened exactly once per audit_path).
        """
        records = self._read_audit_records()
        if records:
            # Any previous access blocks all future accesses (one-and-done)
            existing_run_id = records[0]["run_id"]
            if existing_run_id == run_id:
                raise SealingError(
                    f"sealed cohort already opened for run {run_id!r}: "
                    "evaluate_sealed_once may be called exactly once per run_id."
                )
            else:
                raise SealingError(
                    f"sealed cohort already opened for run {existing_run_id!r}: "
                    f"a second access under run_id {run_id!r} is not permitted. "
                    "The sealed cohort may be opened exactly once."
                )

    def _write_audit_record(self, run_id: str, ids: list[str]) -> None:
        """Append an immutable audit record to the durable JSONL audit file.

        Called by :meth:`evaluate_sealed_once` BEFORE materialisation so that a
        crash during data loading still counts as an access (fail-safe toward
        sealing).  The run_id is permanently burned once this record is written.

        Parameters
        ----------
        run_id : str
            The run identifier.
        ids : list[str]
            The requested perturbation ids.
        """
        sorted_ids = sorted(ids)
        record: dict = {
            "run_id": run_id,
            "perturbation_ids": sorted_ids,
            "count": len(sorted_ids),
            "content_hash": sha256_json({"run_id": run_id, "perturbation_ids": sorted_ids}),
        }
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        try:
            atomic_write_once(self._audit_path, line, encoding="utf-8")
        except FileExistsError as exc:
            raise SealingError(
                f"sealed cohort was claimed concurrently at {str(self._audit_path)!r}; "
                "the cohort may be opened exactly once"
            ) from exc
