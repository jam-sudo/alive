"""End-to-end gene-disjoint OOF hyperparameter selection (Task 2a-8, plan §2.4).

SYNTHETIC-ONLY. Pure ``numpy``; no sealed access. Out-of-fold (OOF)
hyperparameter selection runs on **development calibration pairs only**: the
folds mirror the sealed gene-disjoint regime so the selected ``(k_total, lambda)``
is chosen the way the sealed double-unseen claim will be scored, but no sealed
outcome is ever read.

Selection executes the COMPLETE path for every ``(k_total, lambda)`` candidate
(brief steps 1–7):

1. build deterministic gene-disjoint fold train/test PAIR indices — a fold's TEST
   pairs have BOTH genes in the held-out gene group, TRAIN pairs have NEITHER
   held-out gene, and CROSS-GROUP pairs (exactly one held-out gene) are EXCLUDED
   from that fold (never silently trained on, plan §2.4);
2. fit a fresh model on the TRAIN combo outcomes only;
3. predict the held-out (test) pairs;
4. add the registered additive prediction (RESPONSE-shaped) to the model's eps
   prediction to form the double-shift prediction ``delta_hat`` — the additive is
   the comparator and is length ``p`` (response dim), never length ``k_total``
   (factor dim);
5. compute aligned per-pair errors and ``theta`` (vs additive) via
   :mod:`alive.compose.metric2` (alignment by pair ID);
6. aggregate OOF errors by pair ID across folds (each pair appears as a test pair
   in at most one fold under a disjoint gene partition);
7. select the candidate with maximum ``theta``, with the registered deterministic
   tie-break: lower ``k_total`` first, then LARGER regularization (``lambda``).

An unregularized candidate is non-viable if any OOF train fold is not full rank
under the registered rank rule; it is excluded with an explicit reason rather
than represented by a non-finite score. Empty folds (a retained fold must have
non-empty train AND test), an uncovered-pair fraction above the registered
tolerance, or a grid with no viable candidate INVALIDATE selection and raise
:class:`SelectionError`. The result reports the union of OOF test pairs, the
uncovered calibration pairs and the per-fold exclusions (plan §2.4).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.random import PCG64, Generator

from alive.compose.identify import SingularDesignError, rank_diagnostics
from alive.compose.metric2 import paired_relative_error_reduction
from alive.compose.models import L1Model
from alive.io import atomic_write_once
from alive.provenance import sha256_json

#: Immutable schema tag for the persisted OOF fold manifest (D2 Task 1).
OOF_FOLD_MANIFEST_SCHEMA = "compose_oof_fold_manifest_v1"

#: Exact config-bound OOF estimator-domain policy and its numerical-rank rule.
UNREGULARIZED_OOF_RANK_POLICY = "require_full_rank_each_train_fold"
OOF_RANK_TOLERANCE_RULE = "max_shape_times_float64_eps_times_sigma_max"

#: Prefix of the ``nonviable_candidates`` reason written by the registered
#: conditioning screen. ``diagnostics2`` matches on it to attribute a futility stop
#: to the screen; keeping one constant means the two cannot drift apart silently.
CEILING_REASON_PREFIX = "conditioning above the registered ceiling"

#: Distinguishes the screen's two arms inside a reason that already carries
#: :data:`CEILING_REASON_PREFIX`. ``diagnostics2`` treats them identically -- both
#: mean "removed before scoring, for a numerical reason" -- but they remove
#: different amounts (a whole ``k_total`` versus its ``lam=0.0`` candidate alone),
#: so a reader that must tell them apart matches this constant instead of prose.
FOLD_CEILING_MARKER = "OOF train fold"

#: A typed model factory: a zero-arg callable returning a fresh symmetric model
#: exposing ``fit(Z, pairs, eps_obs, *, lam)`` and ``predict_eps(Z, g, h)``.
ModelFactory = Callable[[], object]

#: The ONE estimator whose singular design OOF selection may read as hyperparameter
#: non-viability. ``phase2a`` binds selection to ``L1Model`` through a hard-coded
#: ``model_factories["l1_bilinear_identifiable"]`` lookup; this makes that binding
#: assertable at the only point where getting it wrong would corrupt a recorded
#: result (see the ``SingularDesignError`` handler in :func:`select_hyperparams`).
_OOF_SELECTION_MODEL: type = L1Model


class SelectionError(ValueError):
    """Raised on any invalid OOF-selection input or an invalidating fold layout.

    Covers empty/ill-typed grids, missing factor banks, dimension mismatches
    (including a factor-shaped additive added to a response-shaped prediction),
    empty folds and an uncovered-pair fraction above the registered tolerance.
    """


class FoldConditioningError(SelectionError):
    """Raised when an unregularized OOF TRAIN fold exceeds the registered ceiling.

    Signals ONE candidate's non-viability, not an invalid selection: the caller
    catches it, records the reason and moves on. It subclasses
    :class:`SelectionError` only so that an escape — impossible on today's single
    call path — would still land in the driver's registered pre-seal rejection
    roster rather than as an uncontracted bug.

    Its message begins with :data:`CEILING_REASON_PREFIX`, which is how
    ``diagnostics2`` recognises a screened candidate; do not reword the opening.
    """


class OOFFoldManifestError(ValueError):
    """Raised on an invalid, inconsistent or tampered :class:`OOFFoldManifest`.

    Covers unknown / missing keys, a wrong schema tag, non-canonical or duplicate
    pair IDs, a position↔ID disagreement, overlapping or incomplete
    train/test/excluded partitions, coverage that is not the union of the folds'
    test IDs, and a self-excluding-checksum mismatch (tampering). Loading a
    manifest that fails ANY of these checks fails closed.
    """


@dataclass(frozen=True)
class GeneDisjointFold:
    """One deterministic gene-disjoint OOF fold over calibration PAIR indices.

    Attributes
    ----------
    held_out_genes : tuple of int
        Gene indices held out for this fold (the test gene group).
    train_idx : tuple of int
        Indices (into the calibration pair list) of TRAIN pairs — both genes are
        OUTSIDE ``held_out_genes``.
    test_idx : tuple of int
        Indices of TEST pairs — both genes are INSIDE ``held_out_genes``.
    excluded_idx : tuple of int
        Indices of CROSS-GROUP pairs — exactly one gene in ``held_out_genes`` —
        excluded from this fold (never trained on, plan §2.4).
    """

    held_out_genes: tuple[int, ...]
    train_idx: tuple[int, ...]
    test_idx: tuple[int, ...]
    excluded_idx: tuple[int, ...]


@dataclass(frozen=True)
class SelectionResult:
    """Outcome of end-to-end gene-disjoint OOF hyperparameter selection.

    Attributes
    ----------
    selected_k_total : int
        Chosen total factor dimension.
    selected_lambda : float
        Chosen ridge regularization.
    theta_by_candidate : dict
        Map each *viable* ``(k_total, lambda)`` to its finite OOF theta (paired
        relative error reduction of ``delta_hat`` vs the additive comparator,
        aggregated over OOF test pairs).
    nonviable_candidates : dict
        Map each excluded ``(k_total, lambda)`` to the deterministic reason it was
        excluded before scoring. Two reasons occur: the estimator could not be
        defined on that candidate (the registered unregularized rank policy), or
        the candidate's design is inadmissible under the registered conditioning
        ceiling (``CEILING_REASON_PREFIX``). The latter is a property of
        ``k_total`` alone, so it appears once per ``lambda`` at that dimension.
        Such candidates are absent from ``theta_by_candidate``; no NaN or infinity
        sentinel enters selection or persisted diagnostics.
    union_test_pair_ids : tuple of tuple of str
        Sorted union of canonical pair IDs that appear as some fold's OOF test
        pair (the covered calibration pairs).
    uncovered_pair_ids : tuple of tuple of str
        Sorted canonical pair IDs that never appear as an OOF test pair (e.g.
        cross-group pairs); their fraction is bounded by ``uncovered_tolerance``.
    uncovered_fraction : float
        Fraction of calibration pairs that are uncovered.
    fold_exclusions : tuple of tuple of tuple of str
        Per-fold tuple of the canonical pair IDs excluded from that fold.
    n_folds : int
        Number of retained folds (every retained fold has non-empty train+test).
    oof_manifest : OOFFoldManifest or None
        The canonical, checksummed record of the EXACT folds built at this single
        selection call (never a second, independently rebuilt fold set). Bound so
        later development tasks LOAD and VERIFY it instead of re-deriving folds.
    """

    selected_k_total: int
    selected_lambda: float
    theta_by_candidate: dict[tuple[int, float], float]
    nonviable_candidates: dict[tuple[int, float], str]
    union_test_pair_ids: tuple[tuple[str, str], ...]
    uncovered_pair_ids: tuple[tuple[str, str], ...]
    uncovered_fraction: float
    fold_exclusions: tuple[tuple[tuple[str, str], ...], ...] = field(default=())
    n_folds: int = 0
    oof_manifest: OOFFoldManifest | None = None


# --------------------------------------------------------------------------- #
# persisted OOF fold manifest (D2 Task 1)
# --------------------------------------------------------------------------- #

#: Top-level keys of a serialised :class:`OOFFoldManifest` (exact set; extra or
#: missing keys fail closed on load).
_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "schema",
        "calibration_pair_ids",
        "n_genes",
        "n_folds",
        "split_seed",
        "folds",
        "covered_pair_ids",
        "uncovered_pair_ids",
        "manifest_checksum",
    }
)

#: Keys of a serialised :class:`OOFFoldRecord` (exact set).
_FOLD_KEYS: frozenset[str] = frozenset(
    {
        "fold_index",
        "held_out_gene_indices",
        "train_pair_positions",
        "test_pair_positions",
        "excluded_pair_positions",
        "train_pair_ids",
        "test_pair_ids",
        "excluded_pair_ids",
    }
)


def _as_pair(value: object) -> tuple[str, str]:
    """Coerce a JSON pair (list/tuple of two strings) to a canonical 2-tuple."""
    if not isinstance(value, (list, tuple)):
        raise OOFFoldManifestError(f"pair ID must be a two-element list, got {value!r}")
    pair = tuple(value)
    if len(pair) != 2 or not all(isinstance(x, str) for x in pair):
        raise OOFFoldManifestError(f"pair ID must be a (str, str) tuple, got {value!r}")
    return (pair[0], pair[1])


def _is_canonical_pair(pair: tuple[str, str]) -> bool:
    """Return ``True`` if ``pair`` is canonical ``(min, max)`` by UTF-8 bytes."""
    return pair[0].encode("utf-8") <= pair[1].encode("utf-8")


@dataclass(frozen=True)
class OOFFoldRecord:
    """One fold of the gene-disjoint OOF layout — positions AND aligned IDs.

    Attributes
    ----------
    fold_index : int
        Zero-based position of this fold in the manifest's fold tuple.
    held_out_gene_indices : tuple of int
        Gene indices held out for this fold (the test gene group).
    train_pair_positions, test_pair_positions, excluded_pair_positions : tuple of int
        Positions (indices into ``calibration_pair_ids``) of the fold's TRAIN /
        TEST / EXCLUDED (cross-group) pairs.
    train_pair_ids, test_pair_ids, excluded_pair_ids : tuple of tuple of str
        The canonical pair IDs at those positions, aligned one-for-one so a later
        loader can VERIFY ``*_pair_ids == [calibration_pair_ids[i] for i in
        *_pair_positions]`` without re-deriving folds.
    """

    fold_index: int
    held_out_gene_indices: tuple[int, ...]
    train_pair_positions: tuple[int, ...]
    test_pair_positions: tuple[int, ...]
    excluded_pair_positions: tuple[int, ...]
    train_pair_ids: tuple[tuple[str, str], ...]
    test_pair_ids: tuple[tuple[str, str], ...]
    excluded_pair_ids: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict:
        """Return a canonical JSON-serialisable representation of this fold."""
        return {
            "fold_index": int(self.fold_index),
            "held_out_gene_indices": [int(g) for g in self.held_out_gene_indices],
            "train_pair_positions": [int(i) for i in self.train_pair_positions],
            "test_pair_positions": [int(i) for i in self.test_pair_positions],
            "excluded_pair_positions": [int(i) for i in self.excluded_pair_positions],
            "train_pair_ids": [list(p) for p in self.train_pair_ids],
            "test_pair_ids": [list(p) for p in self.test_pair_ids],
            "excluded_pair_ids": [list(p) for p in self.excluded_pair_ids],
        }


@dataclass(frozen=True)
class OOFFoldManifest:
    """Canonical, checksummed record of the EXACT single-call OOF fold layout.

    Persisted at the single :func:`select_hyperparams` selection call and bound
    into the run identity so later development tasks LOAD and VERIFY it instead of
    re-deriving folds. The :attr:`manifest_checksum` is a self-excluding SHA-256
    over :meth:`_payload` (every field except the checksum itself), so any content
    change moves it and :meth:`load` fails closed on tampering.

    Attributes
    ----------
    schema : str
        Immutable schema tag (:data:`OOF_FOLD_MANIFEST_SCHEMA`).
    calibration_pair_ids : tuple of tuple of str
        The full development calibration pair-ID tuple, in the selection call's
        row order (fold positions index into this tuple).
    n_genes : int
        Total number of genes passed to :func:`select_hyperparams`.
    n_folds : int
        Number of gene-disjoint folds passed to :func:`select_hyperparams`.
    split_seed : int
        The fold-construction seed passed to :func:`select_hyperparams`.
    folds : tuple of OOFFoldRecord
        The per-fold positions + aligned IDs.
    covered_pair_ids : tuple of tuple of str
        Sorted canonical union of the folds' TEST pair IDs (the covered pairs).
    uncovered_pair_ids : tuple of tuple of str
        Sorted canonical calibration pairs never used as an OOF test pair.
    manifest_checksum : str
        Self-excluding SHA-256 over :meth:`_payload` (set by :meth:`from_folds`).
    """

    schema: str
    calibration_pair_ids: tuple[tuple[str, str], ...]
    n_genes: int
    n_folds: int
    split_seed: int
    folds: tuple[OOFFoldRecord, ...]
    covered_pair_ids: tuple[tuple[str, str], ...]
    uncovered_pair_ids: tuple[tuple[str, str], ...]
    manifest_checksum: str = ""

    # -- construction ----------------------------------------------------- #
    @classmethod
    def from_folds(
        cls,
        folds: Sequence[GeneDisjointFold],
        *,
        pair_ids: Sequence[tuple[str, str]],
        n_genes: int,
        n_folds: int,
        split_seed: int,
    ) -> OOFFoldManifest:
        """Build the manifest from the EXACT ``folds`` of a single selection call.

        Parameters
        ----------
        folds : sequence of GeneDisjointFold
            The folds already built at the single selection call — reused, never
            rebuilt.
        pair_ids : sequence of (str, str)
            The calibration pair IDs (row order), aligned with the pair indices
            the folds reference.
        n_genes, n_folds, split_seed : int
            The selection call's gene count, fold count and fold-construction seed.

        Returns
        -------
        OOFFoldManifest
            The sealed, self-checksummed manifest.
        """
        ids = tuple(tuple(p) for p in pair_ids)
        records = tuple(
            OOFFoldRecord(
                fold_index=i,
                held_out_gene_indices=tuple(int(g) for g in fold.held_out_genes),
                train_pair_positions=tuple(int(j) for j in fold.train_idx),
                test_pair_positions=tuple(int(j) for j in fold.test_idx),
                excluded_pair_positions=tuple(int(j) for j in fold.excluded_idx),
                train_pair_ids=tuple(ids[j] for j in fold.train_idx),
                test_pair_ids=tuple(ids[j] for j in fold.test_idx),
                excluded_pair_ids=tuple(ids[j] for j in fold.excluded_idx),
            )
            for i, fold in enumerate(folds)
        )
        covered = tuple(sorted({pid for rec in records for pid in rec.test_pair_ids}))
        uncovered = tuple(sorted(set(ids) - set(covered)))
        manifest = cls(
            schema=OOF_FOLD_MANIFEST_SCHEMA,
            calibration_pair_ids=ids,
            n_genes=int(n_genes),
            n_folds=int(n_folds),
            split_seed=int(split_seed),
            folds=records,
            covered_pair_ids=covered,
            uncovered_pair_ids=uncovered,
        )
        object.__setattr__(manifest, "manifest_checksum", sha256_json(manifest._payload()))
        return manifest

    # -- canonical payload + serialisation -------------------------------- #
    def _payload(self) -> dict:
        """Canonical checksum input (every field EXCEPT ``manifest_checksum``)."""
        return {
            "schema": self.schema,
            "calibration_pair_ids": [list(p) for p in self.calibration_pair_ids],
            "n_genes": int(self.n_genes),
            "n_folds": int(self.n_folds),
            "split_seed": int(self.split_seed),
            "folds": [rec.to_dict() for rec in self.folds],
            "covered_pair_ids": [list(p) for p in self.covered_pair_ids],
            "uncovered_pair_ids": [list(p) for p in self.uncovered_pair_ids],
        }

    def to_dict(self) -> dict:
        """Return the canonical payload augmented with the sealed checksum."""
        payload = self._payload()
        payload["manifest_checksum"] = self.manifest_checksum
        return payload

    def write_once(self, path: str | Path) -> None:
        """Serialise the manifest to ``path`` as canonical JSON (write-once).

        Parameters
        ----------
        path : str or Path
            Destination file; must not already exist (write-once, CLAUDE.md#provenance).

        Raises
        ------
        OOFFoldManifestError
            If ``path`` already exists.
        """
        try:
            atomic_write_once(
                path,
                json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")),
            )
        except FileExistsError as exc:
            raise OOFFoldManifestError(
                f"refusing to overwrite existing OOF fold manifest at {path}: write-once"
            ) from exc

    # -- loading (fail closed) -------------------------------------------- #
    @classmethod
    def load(cls, path: str | Path) -> OOFFoldManifest:
        """Load and fully VERIFY a manifest written by :meth:`write_once`.

        Fails closed (:class:`OOFFoldManifestError`) on: unknown / missing keys, a
        wrong schema tag, non-canonical or duplicate pair IDs, a position↔ID
        disagreement, overlapping / incomplete train/test/excluded partitions,
        coverage that is not the union of the folds' test IDs, and a
        self-excluding-checksum mismatch.

        Parameters
        ----------
        path : str or Path
            Path to a manifest JSON file.

        Returns
        -------
        OOFFoldManifest
            The verified manifest (its recorded checksum matches the recomputation).
        """
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise OOFFoldManifestError(f"failed to read OOF fold manifest: {exc}") from exc
        if not isinstance(data, dict):
            raise OOFFoldManifestError("manifest root must be a JSON object")

        keys = set(data)
        if keys != set(_MANIFEST_KEYS):
            raise OOFFoldManifestError(
                f"manifest key set mismatch (missing={sorted(_MANIFEST_KEYS - keys)}, "
                f"unknown={sorted(keys - _MANIFEST_KEYS)})"
            )
        if data["schema"] != OOF_FOLD_MANIFEST_SCHEMA:
            raise OOFFoldManifestError(f"unexpected schema tag {data['schema']!r}")

        n_genes = _as_int(data["n_genes"], field="n_genes")
        n_folds = _as_int(data["n_folds"], field="n_folds")
        split_seed = _as_int(data["split_seed"], field="split_seed")
        if n_genes <= 0 or n_folds < 1:
            raise OOFFoldManifestError("n_genes must be > 0 and n_folds must be >= 1")

        calibration = _load_pair_tuple(data["calibration_pair_ids"], field="calibration_pair_ids")
        n_pairs = len(calibration)
        positions_universe = set(range(n_pairs))

        records = _load_fold_records(data["folds"], calibration, n_genes, positions_universe)
        if len(records) != n_folds:
            raise OOFFoldManifestError(
                f"manifest has {len(records)} folds but declares n_folds={n_folds}"
            )

        covered = _load_pair_tuple(data["covered_pair_ids"], field="covered_pair_ids")
        uncovered = _load_pair_tuple(data["uncovered_pair_ids"], field="uncovered_pair_ids")
        expected_covered = tuple(sorted({pid for rec in records for pid in rec.test_pair_ids}))
        if covered != expected_covered:
            raise OOFFoldManifestError(
                "covered_pair_ids is not the sorted union of the folds' test pair IDs"
            )
        expected_uncovered = tuple(sorted(set(calibration) - set(covered)))
        if uncovered != expected_uncovered:
            raise OOFFoldManifestError(
                "uncovered_pair_ids is not the sorted calibration remainder of coverage"
            )

        manifest = cls(
            schema=OOF_FOLD_MANIFEST_SCHEMA,
            calibration_pair_ids=calibration,
            n_genes=n_genes,
            n_folds=n_folds,
            split_seed=split_seed,
            folds=records,
            covered_pair_ids=covered,
            uncovered_pair_ids=uncovered,
        )
        recomputed = sha256_json(manifest._payload())
        stored_checksum = data["manifest_checksum"]
        if not isinstance(stored_checksum, str) or stored_checksum != recomputed:
            raise OOFFoldManifestError(
                "manifest checksum mismatch: content was tampered after sealing"
            )
        object.__setattr__(manifest, "manifest_checksum", recomputed)
        return manifest


def _as_int(value: object, *, field: str) -> int:
    """Coerce a JSON integer scalar (rejecting bools) or fail closed."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise OOFFoldManifestError(f"{field} must be an integer, got {value!r}")
    return int(value)


def _load_pair_tuple(
    raw: object, *, field: str, require_canonical: bool = True, require_unique: bool = True
) -> tuple[tuple[str, str], ...]:
    """Coerce and validate a list of canonical, unique pair IDs."""
    if not isinstance(raw, list):
        raise OOFFoldManifestError(f"{field} must be a list of pair IDs")
    pairs = tuple(_as_pair(item) for item in raw)
    if require_canonical:
        noncanonical = [p for p in pairs if not _is_canonical_pair(p)]
        if noncanonical:
            raise OOFFoldManifestError(f"{field} contains non-canonical pair IDs: {noncanonical}")
    if require_unique and len(set(pairs)) != len(pairs):
        raise OOFFoldManifestError(f"{field} contains duplicate pair IDs")
    return pairs


def _load_positions(raw: object, *, field: str, universe: set[int]) -> tuple[int, ...]:
    """Coerce a list of unique in-range integer positions or fail closed."""
    if not isinstance(raw, list):
        raise OOFFoldManifestError(f"{field} must be a list of integer positions")
    positions = tuple(_as_int(item, field=field) for item in raw)
    if len(set(positions)) != len(positions):
        raise OOFFoldManifestError(f"{field} contains duplicate positions")
    out_of_range = [p for p in positions if p not in universe]
    if out_of_range:
        raise OOFFoldManifestError(f"{field} positions out of range: {out_of_range}")
    return positions


def _load_fold_records(
    raw: object,
    calibration: tuple[tuple[str, str], ...],
    n_genes: int,
    positions_universe: set[int],
) -> tuple[OOFFoldRecord, ...]:
    """Parse and fully validate every fold record (positions, IDs, partition)."""
    if not isinstance(raw, list):
        raise OOFFoldManifestError("folds must be a list")
    records: list[OOFFoldRecord] = []
    for expected_index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise OOFFoldManifestError("each fold must be a JSON object")
        if set(item) != set(_FOLD_KEYS):
            raise OOFFoldManifestError(
                f"fold {expected_index} key set mismatch "
                f"(missing={sorted(_FOLD_KEYS - set(item))}, "
                f"unknown={sorted(set(item) - _FOLD_KEYS)})"
            )
        if _as_int(item["fold_index"], field="fold_index") != expected_index:
            raise OOFFoldManifestError(
                f"fold_index {item['fold_index']!r} is not the sequential position {expected_index}"
            )
        held = _load_positions(
            item["held_out_gene_indices"],
            field=f"fold {expected_index} held_out_gene_indices",
            universe=set(range(n_genes)),
        )
        train_pos = _load_positions(
            item["train_pair_positions"],
            field=f"fold {expected_index} train_pair_positions",
            universe=positions_universe,
        )
        test_pos = _load_positions(
            item["test_pair_positions"],
            field=f"fold {expected_index} test_pair_positions",
            universe=positions_universe,
        )
        excl_pos = _load_positions(
            item["excluded_pair_positions"],
            field=f"fold {expected_index} excluded_pair_positions",
            universe=positions_universe,
        )
        # partitions must be disjoint AND cover every calibration position exactly.
        train_s, test_s, excl_s = set(train_pos), set(test_pos), set(excl_pos)
        if train_s & test_s or train_s & excl_s or test_s & excl_s:
            raise OOFFoldManifestError(
                f"fold {expected_index} train/test/excluded partitions overlap"
            )
        if train_s | test_s | excl_s != positions_universe:
            raise OOFFoldManifestError(
                f"fold {expected_index} partitions do not cover every calibration pair"
            )
        # position↔ID alignment: recorded IDs must equal the calibration IDs at
        # the recorded positions (never a re-derived or drifted set).
        train_ids = _load_pair_tuple(
            item["train_pair_ids"], field=f"fold {expected_index} train_pair_ids"
        )
        test_ids = _load_pair_tuple(
            item["test_pair_ids"], field=f"fold {expected_index} test_pair_ids"
        )
        excl_ids = _load_pair_tuple(
            item["excluded_pair_ids"],
            field=f"fold {expected_index} excluded_pair_ids",
            require_unique=True,
        )
        for name, pos, got in (
            ("train", train_pos, train_ids),
            ("test", test_pos, test_ids),
            ("excluded", excl_pos, excl_ids),
        ):
            expected = tuple(calibration[j] for j in pos)
            if got != expected:
                raise OOFFoldManifestError(
                    f"fold {expected_index} {name}_pair_ids disagree with the positions"
                )
        records.append(
            OOFFoldRecord(
                fold_index=expected_index,
                held_out_gene_indices=held,
                train_pair_positions=train_pos,
                test_pair_positions=test_pos,
                excluded_pair_positions=excl_pos,
                train_pair_ids=train_ids,
                test_pair_ids=test_ids,
                excluded_pair_ids=excl_ids,
            )
        )
    return tuple(records)


# --------------------------------------------------------------------------- #
# fold construction
# --------------------------------------------------------------------------- #


def build_gene_disjoint_folds(
    idx_pairs: Sequence[tuple[int, int]],
    *,
    n_genes: int,
    n_folds: int,
    seed: int,
) -> list[GeneDisjointFold]:
    """Build deterministic gene-disjoint OOF folds over calibration pair indices.

    The set of genes that actually appear in ``idx_pairs`` is partitioned into
    ``n_folds`` disjoint gene groups by a seeded ``PCG64`` permutation (genes are
    first sorted so the permutation is reproducible across processes). For each
    group, a pair is a TEST pair iff BOTH its genes are in the group, a TRAIN pair
    iff NEITHER gene is in the group, and an EXCLUDED (cross-group) pair iff
    exactly one gene is in the group (plan §2.4).

    Parameters
    ----------
    idx_pairs : sequence of (int, int)
        Calibration gene-index pairs (canonical or not; treated as unordered).
    n_genes : int
        Total number of genes (the factor matrices have this many rows).
    n_folds : int
        Number of gene-disjoint folds; must be ``>= 1``.
    seed : int
        Seed for the ``PCG64`` gene-permutation generator.

    Returns
    -------
    list of GeneDisjointFold
        One fold per gene group, in group order.

    Raises
    ------
    SelectionError
        If ``n_folds < 1``, ``n_genes`` is non-positive, a pair references a gene
        index outside ``range(n_genes)``, or a pair is a self-pair.
    """
    if n_folds < 1:
        raise SelectionError(f"n_folds must be >= 1, got {n_folds}")
    if n_genes <= 0:
        raise SelectionError(f"n_genes must be positive, got {n_genes}")

    for g, h in idx_pairs:
        if not (0 <= g < n_genes) or not (0 <= h < n_genes):
            raise SelectionError(f"pair ({g}, {h}) references a gene outside [0, {n_genes})")
        if g == h:
            raise SelectionError(f"self-pair not allowed: ({g}, {h})")

    # Only genes that actually appear in calibration pairs can drive a fold.
    present = sorted({g for pair in idx_pairs for g in pair})
    rng = Generator(PCG64(seed))
    permuted = list(rng.permutation(present)) if present else []
    # round-robin into n_folds groups so groups stay balanced and deterministic
    groups: list[list[int]] = [[] for _ in range(n_folds)]
    for position, gene in enumerate(permuted):
        groups[position % n_folds].append(int(gene))

    folds: list[GeneDisjointFold] = []
    for group in groups:
        held = set(group)
        train_idx: list[int] = []
        test_idx: list[int] = []
        excluded_idx: list[int] = []
        for pi, (g, h) in enumerate(idx_pairs):
            g_in = g in held
            h_in = h in held
            if g_in and h_in:
                test_idx.append(pi)
            elif not g_in and not h_in:
                train_idx.append(pi)
            else:
                excluded_idx.append(pi)
        folds.append(
            GeneDisjointFold(
                held_out_genes=tuple(sorted(held)),
                train_idx=tuple(train_idx),
                test_idx=tuple(test_idx),
                excluded_idx=tuple(excluded_idx),
            )
        )
    return folds


# --------------------------------------------------------------------------- #
# input validation
# --------------------------------------------------------------------------- #


def _validate_inputs(
    idx_pairs: Sequence[tuple[int, int]],
    pair_ids: Sequence[tuple[str, str]],
    eps_obs: np.ndarray,
    additive: np.ndarray,
    factors_by_k: dict[int, np.ndarray],
    k_total_grid: Sequence[int],
    lambda_grid: Sequence[float],
    uncovered_tolerance: float,
    condition_ceiling: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Validate every selection input; return ``(eps_obs, additive, p)``.

    Raises
    ------
    SelectionError
        On empty grids, mismatched lengths, a missing factor bank, a factor bank
        whose column count disagrees with its ``k_total`` key, a non-2-D / empty
        target, or — the load-bearing guard — a factor-shaped ``additive`` whose
        response dimension does not match ``eps_obs`` (length ``p``). The additive
        added to the model eps MUST be response-dimensional, never factor-shaped.
    """
    if len(k_total_grid) == 0:
        raise SelectionError("k_total_grid is empty")
    if len(lambda_grid) == 0:
        raise SelectionError("lambda_grid is empty")
    normalized_lambdas: list[float] = []
    for raw_lam in lambda_grid:
        if isinstance(raw_lam, bool):
            raise SelectionError("lambda_grid values must be finite non-negative numbers")
        try:
            lam = float(raw_lam)
        except (TypeError, ValueError) as exc:
            raise SelectionError("lambda_grid values must be finite non-negative numbers") from exc
        if not np.isfinite(lam) or lam < 0.0:
            raise SelectionError(f"lambda_grid values must be finite and non-negative, got {lam!r}")
        normalized_lambdas.append(lam)
    if len(set(normalized_lambdas)) != len(normalized_lambdas):
        raise SelectionError("lambda_grid contains duplicate numeric values")
    if not (0.0 <= float(uncovered_tolerance) <= 1.0):
        raise SelectionError(f"uncovered_tolerance must be in [0, 1], got {uncovered_tolerance}")
    # Both directions are unusable and they fail in OPPOSITE ways, which is why
    # neither is admitted: ``cond > nan`` and ``cond > inf`` are always False, so
    # such a ceiling silences the screen on every candidate; a non-positive one is
    # always True, so it rejects every candidate including a perfect design.
    ceiling = float(condition_ceiling)
    if not np.isfinite(ceiling) or ceiling <= 0.0:
        raise SelectionError(
            "condition_ceiling must be finite and positive -- a nan or infinite "
            "ceiling silences the conditioning screen and a non-positive one "
            f"rejects every candidate, got {condition_ceiling!r}"
        )

    n_pairs = len(idx_pairs)
    if n_pairs == 0:
        raise SelectionError("idx_pairs is empty")
    if len(pair_ids) != n_pairs:
        raise SelectionError(f"pair_ids has {len(pair_ids)} entries for {n_pairs} pairs")
    if len(set(pair_ids)) != n_pairs:
        raise SelectionError("pair_ids contains duplicate canonical pair IDs")

    eps = np.asarray(eps_obs, dtype=np.float64)
    add = np.asarray(additive, dtype=np.float64)
    if eps.ndim != 2 or eps.shape[0] != n_pairs or eps.shape[1] == 0:
        raise SelectionError(f"eps_obs must be ({n_pairs}, p) non-empty; got shape {eps.shape}")
    p = eps.shape[1]
    # Load-bearing guard: the additive comparator/prediction is RESPONSE-shaped.
    # A factor-shaped additive (length k_total) would be silently broadcast or
    # add a factor-dim vector to a response-dim prediction; refuse it.
    if add.ndim != 2 or add.shape != (n_pairs, p):
        raise SelectionError(
            "additive must be response-dimensional (n_pairs, p) matching eps_obs "
            f"({n_pairs}, {p}); got shape {add.shape}. A factor-shaped additive "
            "(length k_total) must never be added to a response-shaped prediction."
        )
    if not np.all(np.isfinite(eps)) or not np.all(np.isfinite(add)):
        raise SelectionError("eps_obs / additive contain non-finite values")

    for k_total in k_total_grid:
        if k_total not in factors_by_k:
            raise SelectionError(f"no factor bank in factors_by_k for k_total={k_total}")
        Z = np.asarray(factors_by_k[k_total], dtype=np.float64)
        if Z.ndim != 2 or Z.shape[1] != k_total:
            raise SelectionError(
                f"factors_by_k[{k_total}] must be (n_genes, {k_total}); got shape {Z.shape}"
            )
    return eps, add, p


# --------------------------------------------------------------------------- #
# single-candidate OOF evaluation
# --------------------------------------------------------------------------- #


def _screen_unregularized_folds(
    *,
    folds: Sequence[GeneDisjointFold],
    idx_pairs: Sequence[tuple[int, int]],
    Z: np.ndarray,
    condition_ceiling: float,
) -> None:
    """Registered fold-level guards for the unregularized (``lam == 0.0``) solve.

    A PRE-PASS over every fold, before any fit. Rank is checked across ALL folds
    before conditioning is checked on ANY, so within this function a rank failure
    in any fold outranks a conditioning failure in any other.

    That precedence is LOCAL to this function and does not hold for selection as a
    whole. ``select_hyperparams`` screens the FULL calibration design against the
    same ceiling before it ever calls into here, so a full-design conditioning
    failure still masks a fold-level rank failure. Measured: full design
    ``cond 9.21e12`` over the ceiling with train fold 1 at ``rank 6/10`` records
    only the conditioning reason. That is deliberate and is NOT the defect fixed
    here: the two arms examine different objects, the candidate arm's reason is
    true, and it justifies removing the candidate at EVERY lambda whereas the fold
    rank policy justifies removing only ``lam=0.0``. Recording the narrower reason
    as primary would under-justify the removal that actually happens. The loss is
    diagnostic, not decisional, and it is not fold-order dependent.

    Checking the two fold by fold inside the fit loop looked equivalent and was
    not. The loop raises on the first offending fold, so a conditioning raise in
    fold 0 short-circuited a rank failure in fold 1 and the candidate was recorded
    "numerically inadmissible" when it was in fact NON-IDENTIFIABLE — the stronger
    diagnosis, silently lost, and the recorded reason made to depend on fold order.
    Losing it that way is exactly the reason-misattribution this screen exists to
    prevent. Found by independent review; the fold-order case is pinned in
    ``test_condition_ceiling.py``.

    Applies only at ``lam == 0.0`` because that is where ``identify_operator``
    takes the unregularized ``lstsq`` branch and ``cond(Phi)`` IS the conditioning
    of the solve. At ``lam > 0`` the ridge filter factors bound it, so the
    unregularized number is the wrong statistic to reject on. NOTE that this
    bound is in the units of ``Phi``: ``cond`` is invariant to a uniform rescale of
    ``z`` while the registered ``lambda_grid`` is absolute, so the size of the
    protection at ``lam > 0`` depends on a factor-bank scale nothing registers.
    That limitation is recorded in the readiness index, not closed here.

    Raises
    ------
    SingularDesignError
        If any train fold is rank-deficient under the registered rank rule.
    FoldConditioningError
        Otherwise, if any train fold's condition number exceeds the registered
        ceiling. Every offending fold is named, not just the first.
    """
    reports = [rank_diagnostics(Z, [idx_pairs[i] for i in fold.train_idx]) for fold in folds]

    deficient = [(index, report) for index, report in enumerate(reports) if not report.is_full_rank]
    if deficient:
        first_index, first_report = deficient[0]
        # Same argument as the conditioning arm below: an operator needs the extent
        # of the degeneracy, not one arbitrary index. Leaving this arm reporting
        # only its first offender while the sibling reports all of them was an
        # asymmetry in the arm this screen calls the STRONGER diagnosis.
        also = ""
        if len(deficient) > 1:
            also = "; also rank-deficient: " + ", ".join(
                f"fold {index} at rank {report.rank}/{report.sym_dim}"
                for index, report in deficient[1:]
            )
        raise SingularDesignError(
            f"OOF train fold {first_index}: unregularized calibration design "
            "is non-identifiable under the registered rank rule: "
            f"rank={first_report.rank}, sym_dim={first_report.sym_dim}, lam={0.0!r}{also}"
        )

    ceiling = float(condition_ceiling)
    # ``isfinite`` is NOT redundant with the rank pass above, and the reason is
    # narrower than an earlier version of this comment claimed. ``rank_diagnostics``
    # returns ``inf`` when ``rank < sym_dim`` OR ``pos.size == 0``; at ``k_total == 0``
    # the second fires while ``is_full_rank`` is ``True`` (``0 >= 0``), so a zero-width
    # factor bank reaches here full-rank AND infinitely conditioned. Screening it as
    # a conditioning failure would file a degenerate bank under the wrong arm. The
    # registered ``total_k_grid`` excludes 0, so this is unreachable through config —
    # it is reachable, and tested, through this function directly.
    over = [
        (index, float(report.condition_number))
        for index, report in enumerate(reports)
        if np.isfinite(report.condition_number) and float(report.condition_number) > ceiling
    ]
    if over:
        first_index, first_condition = over[0]
        also = ""
        if len(over) > 1:
            also = "; also over the ceiling: " + ", ".join(
                f"fold {index} at {condition}" for index, condition in over[1:]
            )
        raise FoldConditioningError(
            f"{CEILING_REASON_PREFIX}: {FOLD_CEILING_MARKER} {first_index} "
            f"condition_number={first_condition} > "
            f"condition_ceiling={ceiling} at lam=0.0 "
            "(registered identification.condition_ceiling; the fold design is full "
            f"rank but numerically inadmissible){also}"
        )


def _oof_theta_for_candidate(
    *,
    folds: Sequence[GeneDisjointFold],
    idx_pairs: Sequence[tuple[int, int]],
    pair_ids: Sequence[tuple[str, str]],
    eps_obs: np.ndarray,
    additive: np.ndarray,
    Z: np.ndarray,
    lam: float,
    p: int,
    model_factory: ModelFactory,
    require_full_rank_unregularized: bool,
    condition_ceiling: float,
) -> tuple[float, set[tuple[str, str]]]:
    """OOF ``theta`` (vs additive) for one ``(Z, lambda)`` over all folds.

    For every fold: fit a fresh model on TRAIN combo outcomes only, predict the
    held-out TEST pairs, add the RESPONSE-shaped additive prediction to the
    model's eps prediction to form ``delta_hat`` (and the additive truth target
    ``delta = additive + eps_obs``), then accumulate the OOF predictions, the
    additive-comparator predictions and the truth — all by pair ID. ``theta`` is
    computed once over the aggregated OOF rows (alignment by pair ID).

    Two registered guards run before any fold is fitted, and BOTH only at
    ``lam == 0.0`` — the one branch that solves unregularized, so the fold design's
    own spectrum is what the solve sees: the rank policy (``SingularDesignError``)
    and the conditioning ceiling (``FoldConditioningError``). They run as a
    whole-candidate pre-pass, not per fold, so that a rank failure in ANY fold
    outranks a conditioning failure in any other; see
    :func:`_screen_unregularized_folds` for why that is not the same thing.

    Returns
    -------
    (float, set)
        OOF theta and the set of covered (OOF test) canonical pair IDs.
    """
    pred_rows: list[np.ndarray] = []
    comp_rows: list[np.ndarray] = []
    truth_rows: list[np.ndarray] = []
    row_ids: list[tuple[str, str]] = []
    covered: set[tuple[str, str]] = set()

    if require_full_rank_unregularized and float(lam) == 0.0:
        _screen_unregularized_folds(
            folds=folds, idx_pairs=idx_pairs, Z=Z, condition_ceiling=condition_ceiling
        )

    for fold_index, fold in enumerate(folds):
        model = model_factory()
        train_pairs = [idx_pairs[i] for i in fold.train_idx]
        train_eps = eps_obs[list(fold.train_idx)]
        try:
            model.fit(Z, train_pairs, train_eps, lam=float(lam))
        except SingularDesignError as exc:
            raise SingularDesignError(f"OOF train fold {fold_index}: {exc}") from exc

        for pi in fold.test_idx:
            g, h = idx_pairs[pi]
            eps_pred = np.asarray(model.predict_eps(Z, g, h), dtype=np.float64)
            if eps_pred.shape != (p,):
                raise SelectionError(
                    f"model eps prediction for pair {pair_ids[pi]} has shape "
                    f"{eps_pred.shape}, expected ({p},)"
                )
            # delta_hat = additive + model eps  (BOTH response-dimensional)
            delta_hat = additive[pi] + eps_pred
            # additive comparator prediction == additive (eps = 0)
            delta_truth = additive[pi] + eps_obs[pi]
            pred_rows.append(delta_hat)
            comp_rows.append(additive[pi])
            truth_rows.append(delta_truth)
            row_ids.append(pair_ids[pi])
            covered.add(pair_ids[pi])

    if not pred_rows:
        # no OOF test pair was scored for this candidate -> cannot select on it
        raise SelectionError("candidate produced no OOF test predictions (empty coverage)")

    pred = np.vstack(pred_rows)
    comp = np.vstack(comp_rows)
    truth = np.vstack(truth_rows)
    # pair_ids are stringified for the metric (alignment by ID, never by position)
    str_ids = [f"{a}|{b}" for a, b in row_ids]
    theta = paired_relative_error_reduction(
        pred,
        comp,
        truth,
        pair_ids=str_ids,
        comparator_ids=str_ids,
        truth_ids=str_ids,
    )
    return float(theta), covered


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #


def select_hyperparams(
    *,
    idx_pairs: Sequence[tuple[int, int]],
    pair_ids: Sequence[tuple[str, str]],
    eps_obs: np.ndarray,
    additive: np.ndarray,
    factors_by_k: dict[int, np.ndarray],
    k_total_grid: Sequence[int],
    lambda_grid: Sequence[float],
    n_genes: int,
    n_folds: int,
    seed: int,
    model_factory: ModelFactory,
    uncovered_tolerance: float,
    condition_ceiling: float,
    unregularized_oof_rank_policy: str = UNREGULARIZED_OOF_RANK_POLICY,
    rank_tolerance_rule: str = OOF_RANK_TOLERANCE_RULE,
) -> SelectionResult:
    """Select ``(k_total, lambda)`` by end-to-end gene-disjoint OOF (plan §2.4).

    Builds deterministic gene-disjoint folds once, then for every
    ``(k_total, lambda)`` candidate runs the COMPLETE fit -> predict -> additive ->
    metric path on calibration pairs and records the OOF ``theta`` (vs additive).
    The candidate with maximum ``theta`` is selected; ties resolve to lower
    ``k_total`` first, then LARGER regularization (``lambda``).

    Parameters
    ----------
    idx_pairs : sequence of (int, int)
        Calibration gene-index pairs (treated as unordered).
    pair_ids : sequence of (str, str)
        Canonical pair IDs (one per ``idx_pairs`` entry); must be unique.
    eps_obs : numpy.ndarray
        Observed GI (epsilon) targets, shape ``(n_pairs, p)`` — RESPONSE space.
    additive : numpy.ndarray
        Registered additive prediction per pair, shape ``(n_pairs, p)`` — must be
        RESPONSE-dimensional (length ``p``), never factor-shaped (length
        ``k_total``).
    factors_by_k : dict
        Map ``k_total -> Z`` factor matrix of shape ``(n_genes, k_total)``.
    k_total_grid : sequence of int
        Candidate total factor dimensions (e.g. the config ``total_k_grid``).
    lambda_grid : sequence of float
        Candidate ridge regularizations (e.g. the config ``lambda_grid``).
    n_genes : int
        Total number of genes.
    n_folds : int
        Number of gene-disjoint folds.
    seed : int
        Seed for deterministic fold construction.
    model_factory : callable
        Zero-arg callable returning a fresh model implementing
        ``fit(Z, pairs, eps_obs, *, lam)`` and ``predict_eps(Z, g, h)``.
    uncovered_tolerance : float
        Maximum allowed fraction of calibration pairs that are never an OOF test
        pair. An uncovered fraction strictly above this invalidates selection.
    condition_ceiling : float
        Registered admissibility bound on ``cond(Phi)`` (config
        ``identification.condition_ceiling``), applied as a per-candidate screen:
        a ``k_total`` whose full-calibration design has a FINITE condition number
        above this is excluded before scoring and recorded in
        ``nonviable_candidates``. Restricted to finite condition numbers on
        purpose — ``rank_diagnostics`` returns ``inf`` exactly for a rank-deficient
        design, which the registered rank futility gate owns. Must itself be finite
        and positive.
    unregularized_oof_rank_policy, rank_tolerance_rule : str
        Exact config-bound estimator-domain policy. The only registered values
        require every unregularized OOF train design to be full rank under the
        ``max(shape) * float64-eps * sigma_max`` rule.

    Returns
    -------
    SelectionResult
        Selected hyperparameters, per-candidate OOF theta, and the coverage /
        exclusion report (union test pairs, uncovered pairs, fold exclusions).
        Candidates excluded by either admissibility rule are scored by neither the
        complete fit path nor the metric, and appear only in
        ``nonviable_candidates``.

    Raises
    ------
    SelectionError
        On invalid inputs (see :func:`_validate_inputs`, which also refuses a
        non-finite or non-positive ``condition_ceiling``), an empty fold (a
        retained fold must have non-empty train AND test), an uncovered-pair
        fraction strictly above ``uncovered_tolerance``, or a grid in which every
        candidate is non-viable — including the case where the registered
        conditioning screen leaves nothing admissible.
    """
    if unregularized_oof_rank_policy != UNREGULARIZED_OOF_RANK_POLICY:
        raise SelectionError(
            "unregularized_oof_rank_policy must match the registered value "
            f"{UNREGULARIZED_OOF_RANK_POLICY!r}"
        )
    if rank_tolerance_rule != OOF_RANK_TOLERANCE_RULE:
        raise SelectionError(
            f"rank_tolerance_rule must match the registered value {OOF_RANK_TOLERANCE_RULE!r}"
        )

    eps, add, p = _validate_inputs(
        idx_pairs,
        pair_ids,
        eps_obs,
        additive,
        factors_by_k,
        k_total_grid,
        lambda_grid,
        uncovered_tolerance,
        condition_ceiling,
    )

    folds = build_gene_disjoint_folds(idx_pairs, n_genes=n_genes, n_folds=n_folds, seed=seed)

    # Every RETAINED fold must have non-empty train AND test (plan §2.4). An empty
    # train or test fold invalidates selection rather than being silently skipped.
    for f_i, fold in enumerate(folds):
        if len(fold.train_idx) == 0 or len(fold.test_idx) == 0:
            raise SelectionError(
                f"fold {f_i} (held-out genes {fold.held_out_genes}) has empty "
                f"train ({len(fold.train_idx)}) or test ({len(fold.test_idx)}); "
                "selection invalidated"
            )

    # Coverage: union of OOF test pairs across folds, and the uncovered remainder.
    all_pair_ids = set(pair_ids)
    covered_all: set[tuple[str, str]] = set()
    for fold in folds:
        covered_all.update(pair_ids[i] for i in fold.test_idx)
    uncovered = all_pair_ids - covered_all
    uncovered_fraction = len(uncovered) / len(all_pair_ids)
    if uncovered_fraction > float(uncovered_tolerance):
        raise SelectionError(
            f"uncovered-pair fraction {uncovered_fraction:.4f} exceeds tolerance "
            f"{float(uncovered_tolerance):.4f}; selection invalidated"
        )

    theta_by_candidate: dict[tuple[int, float], float] = {}
    nonviable_candidates: dict[tuple[int, float], str] = {}
    for k_total in k_total_grid:
        Z = np.asarray(factors_by_k[k_total], dtype=np.float64)
        if Z.shape[0] != n_genes:
            raise SelectionError(
                f"factors_by_k[{k_total}] has {Z.shape[0]} gene rows, expected {n_genes}"
            )
        # Registered conditioning screen (spec, identification section). ``cond(Phi)``
        # is a function of ``Z`` and the calibration pair roster only -- no outcome
        # enters it -- so screening every CANDIDATE is exactly as pre-registrable as
        # screening the winner, and it records WHY a dimension was dropped instead of
        # terminating a run that had an admissible alternative in the same registered
        # grid. It is the same shape as the unregularized rank policy below.
        #
        # Deliberately restricted to FINITE condition numbers. ``rank_diagnostics``
        # returns ``inf`` exactly when the design is rank-deficient, and rank
        # deficiency is owned by the registered rank futility gate in
        # ``diagnostics2``. Screening it out here would make that gate unreachable:
        # selection would quietly move to a full-rank dimension and the run would
        # CONTINUE where the protocol says it must stop.
        candidate_condition = float(rank_diagnostics(Z, list(idx_pairs)).condition_number)
        inadmissible: str | None = None
        if np.isfinite(candidate_condition) and candidate_condition > float(condition_ceiling):
            inadmissible = (
                f"{CEILING_REASON_PREFIX}: "
                f"condition_number={candidate_condition} > "
                f"condition_ceiling={float(condition_ceiling)} "
                "(registered identification.condition_ceiling; the design is full rank "
                "but numerically inadmissible)"
            )
        for lam in lambda_grid:
            candidate = (int(k_total), float(lam))
            if inadmissible is not None:
                nonviable_candidates[candidate] = inadmissible
                continue
            # The estimator decides unregularized rank viability before LAPACK.
            # Keep an explicit audit reason and omit the candidate from the finite
            # score map; ``-inf`` is neither a measurement nor strict JSON.
            try:
                theta, _ = _oof_theta_for_candidate(
                    folds=folds,
                    idx_pairs=idx_pairs,
                    pair_ids=pair_ids,
                    eps_obs=eps,
                    additive=add,
                    Z=Z,
                    lam=float(lam),
                    p=p,
                    model_factory=model_factory,
                    require_full_rank_unregularized=True,
                    condition_ceiling=float(condition_ceiling),
                )
            except FoldConditioningError as exc:
                # No estimator guard here, unlike the singular-design branch below.
                # ``cond(Phi)`` is a function of ``Z`` and the fold's train pair
                # roster alone -- no model, no outcome -- so it means the same thing
                # whatever ``model_factory`` returns.
                nonviable_candidates[candidate] = str(exc)
                continue
            except SingularDesignError as exc:
                # Reading a singular design as "this HYPERPARAMETER is non-viable"
                # is only correct for the REGISTERED headline estimator, whose
                # unregularized rank policy is what defines viability. ``phase2a``
                # binds ``model_factory`` through a hard-coded
                # ``model_factories["l1_bilinear_identifiable"]`` lookup that
                # nothing asserted, so for any other estimator this branch would
                # silently record a singular comparator as a bad lambda and drop it
                # from the score map. Unreachable today; pinned so it stays that way
                # if the comparator roster ever becomes configurable. The check
                # lives HERE, not at entry, so known-answer stubs that never raise
                # SingularDesignError keep working.
                if type(model_factory()) is not _OOF_SELECTION_MODEL:
                    raise SelectionError(
                        "OOF non-viability is registered for "
                        f"{_OOF_SELECTION_MODEL.__name__} only; candidate {candidate} "
                        f"used {type(model_factory()).__name__}, whose singular design "
                        f"would be misrecorded as a non-viable hyperparameter: {exc}"
                    ) from exc
                nonviable_candidates[candidate] = str(exc)
                continue
            if not np.isfinite(theta):
                raise SelectionError(
                    f"candidate {candidate} produced non-finite OOF theta {theta!r}"
                )
            theta_by_candidate[candidate] = theta

    if not theta_by_candidate:
        detail = "; ".join(
            f"{candidate}: {reason}" for candidate, reason in sorted(nonviable_candidates.items())
        )
        raise SelectionError(f"no viable hyperparameter candidate; {detail}")

    # Select max theta; deterministic tie-break: lower k_total, then LARGER lambda.
    # Sort key maximizes theta, then minimizes k_total, then maximizes lambda. We
    # encode "maximize" as negation so the plain min over the key is the winner.
    def _key(candidate: tuple[int, float]) -> tuple[float, int, float]:
        k_total, lam = candidate
        theta = theta_by_candidate[candidate]
        return (-theta, k_total, -lam)

    best = min(theta_by_candidate, key=_key)

    fold_exclusions = tuple(tuple(pair_ids[i] for i in fold.excluded_idx) for fold in folds)

    # Persist the EXACT folds built above (reuse ``folds`` — do NOT rebuild) as a
    # canonical, checksummed manifest bound into the selection result.
    oof_manifest = OOFFoldManifest.from_folds(
        folds,
        pair_ids=pair_ids,
        n_genes=int(n_genes),
        n_folds=int(n_folds),
        split_seed=int(seed),
    )

    return SelectionResult(
        selected_k_total=best[0],
        selected_lambda=best[1],
        theta_by_candidate=theta_by_candidate,
        nonviable_candidates=nonviable_candidates,
        union_test_pair_ids=tuple(sorted(covered_all)),
        uncovered_pair_ids=tuple(sorted(uncovered)),
        uncovered_fraction=float(uncovered_fraction),
        fold_exclusions=fold_exclusions,
        n_folds=len(folds),
        oof_manifest=oof_manifest,
    )
