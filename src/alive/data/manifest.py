"""Deterministic four-way perturbation split manifest.

Produces a stable, content-addressed :class:`SplitManifest` that partitions
eligible perturbation IDs into the four registered roles.  Assignment depends
**only** on the sorted IDs, the integer seed, and the fraction spec — never on
expression values or cell-level data.  This is a leakage-critical artifact.

Public API
----------
ManifestError
    Raised for invalid inputs or queries on an unknown role/ID.
SPLIT_ROLES
    Ordered tuple of the four role names.
SplitManifest
    Frozen dataclass representing a complete manifest.
build_manifest(eligible_perturbation_ids, fractions, seed, *, exclusions)
    Core builder; the sole entry point that owns the split algorithm.
build_manifest_from_index(index, fractions, seed)
    Thin convenience wrapper that unpacks a :class:`~alive.data.replogle.ReplogleIndex`.

Algorithm
---------
1. Deduplicate and **sort** the eligible IDs (order-independence guarantee).
2. Seed ``numpy.random.default_rng(seed)`` and permute with ``rng.permutation``.
3. Compute per-role integer counts via the **largest-remainder (Hamilton)** method:
   ``base = floor(n * frac)`` per role; distribute remaining units (``n - sum(base)``)
   one each to the roles with the largest fractional remainders, ties broken by
   ``SPLIT_ROLES`` order.  Counts are deterministic and sum exactly to *n*.
4. Partition the permuted array into roles in ``SPLIT_ROLES`` order by those counts.
5. Store each role's IDs as a **sorted** tuple for a canonical representation.

Examples
--------
>>> from alive.config import SplitFractions
>>> from alive.data.manifest import build_manifest
>>> fracs = SplitFractions(
...     base_train=0.45,
...     method_development=0.25,
...     conformal_calibration=0.15,
...     sealed_evaluation=0.15,
... )
>>> ids = [f"gene_{i}" for i in range(100)]
>>> m = build_manifest(ids, fracs, seed=42)
>>> m.counts["eligible_total"]
100
>>> sum(m.counts[r] for r in m.assignments) == 100
True
"""

from __future__ import annotations

import json
import types
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from alive.provenance import sha256_json

if TYPE_CHECKING:
    from alive.config import SplitFractions
    from alive.data.replogle import ReplogleIndex

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPLIT_ROLES: tuple[str, str, str, str] = (
    "base_train",
    "method_development",
    "conformal_calibration",
    "sealed_evaluation",
)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ManifestError(ValueError):
    """Raised for invalid manifest inputs or queries on unknown roles/IDs.

    Parameters
    ----------
    message : str
        Human-readable description of the problem.
    """


# ---------------------------------------------------------------------------
# SplitManifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SplitManifest:
    """Immutable record of a four-way perturbation split.

    Parameters
    ----------
    seed : int
        The integer seed used to permute the sorted IDs.
    fractions : Mapping[str, float]
        Mapping from each role in :data:`SPLIT_ROLES` to its target fraction.
        Stored internally as a :class:`types.MappingProxyType` so callers cannot
        mutate it in place and silently invalidate the cached checksum.
    assignments : Mapping[str, tuple[str, ...]]
        Mapping from each role to a **sorted** tuple of assigned perturbation IDs.
        Also stored as a :class:`types.MappingProxyType`.
    exclusions : Mapping[str, str]
        Mapping from excluded perturbation ID to a human-readable reason.
        Also stored as a :class:`types.MappingProxyType`.
    counts : Mapping[str, int]
        Per-role counts plus ``"excluded"`` and ``"eligible_total"``.
        Also stored as a :class:`types.MappingProxyType`.
    """

    seed: int
    fractions: Mapping[str, float]
    assignments: Mapping[str, tuple[str, ...]]
    exclusions: Mapping[str, str]
    counts: Mapping[str, int]

    def __post_init__(self) -> None:
        """Convert all mutable dict fields to read-only MappingProxyType.

        Uses ``object.__setattr__`` because the dataclass is frozen.  A fresh
        ``dict(value)`` copy is made first so the proxy never aliases a caller's
        dict, preventing any indirect mutation path.
        """
        for field_name in ("fractions", "assignments", "exclusions", "counts"):
            value = getattr(self, field_name)
            if not isinstance(value, types.MappingProxyType):
                object.__setattr__(self, field_name, types.MappingProxyType(dict(value)))

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    @cached_property
    def _id_to_role(self) -> dict[str, str]:
        """Reverse index: perturbation ID → role (built once on first access)."""
        mapping: dict[str, str] = {}
        for role in SPLIT_ROLES:
            for pid in self.assignments[role]:
                mapping[pid] = role
        return mapping

    def split_of(self, perturbation_id: str) -> str:
        """Return the role assigned to *perturbation_id*.

        Parameters
        ----------
        perturbation_id : str
            A perturbation ID that must appear in one of the four roles.

        Returns
        -------
        str
            One of the :data:`SPLIT_ROLES` values.

        Raises
        ------
        ManifestError
            If *perturbation_id* is not assigned to any role.
        """
        try:
            return self._id_to_role[perturbation_id]
        except KeyError:
            raise ManifestError(
                f"Perturbation ID {perturbation_id!r} is not assigned to any role in this manifest."
            )

    def ids_for(self, role: str) -> tuple[str, ...]:
        """Return the sorted tuple of IDs assigned to *role*.

        Parameters
        ----------
        role : str
            One of the :data:`SPLIT_ROLES` values.

        Returns
        -------
        tuple[str, ...]
            Sorted perturbation IDs for that role.

        Raises
        ------
        ManifestError
            If *role* is not one of the four registered roles.
        """
        if role not in SPLIT_ROLES:
            raise ManifestError(f"Unknown role {role!r}.  Valid roles are: {list(SPLIT_ROLES)}.")
        return self.assignments[role]

    # ------------------------------------------------------------------
    # Checksum (cached, deterministic)
    # ------------------------------------------------------------------

    @cached_property
    def checksum(self) -> str:
        """SHA-256 hex digest of the canonical content of this manifest.

        Computed from ``seed``, ``fractions``, ``assignments`` (role → sorted list),
        and ``exclusions`` (sorted by key).  No non-deterministic fields are included.
        Two manifests built from the same inputs (regardless of input ID order) will
        have identical checksums.

        Returns
        -------
        str
            64-character lowercase hexadecimal SHA-256 digest.
        """
        canonical = {
            "seed": self.seed,
            "fractions": {r: self.fractions[r] for r in SPLIT_ROLES},
            "assignments": {r: sorted(self.assignments[r]) for r in SPLIT_ROLES},
            "exclusions": {k: self.exclusions[k] for k in sorted(self.exclusions)},
        }
        return sha256_json(canonical)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dictionary representation.

        Returns
        -------
        dict
            All manifest fields plus the pre-computed checksum.
        """
        return {
            "seed": self.seed,
            "fractions": dict(self.fractions),
            "assignments": {role: list(ids) for role, ids in self.assignments.items()},
            "exclusions": dict(self.exclusions),
            "counts": dict(self.counts),
            "checksum": self.checksum,
        }

    def write(self, path: str | Path) -> None:
        """Write the manifest to *path* as canonical JSON.

        Uses ``sort_keys=True`` and compact separators so the output is
        byte-identical for identical manifest state, regardless of dict
        iteration order.

        Parameters
        ----------
        path : str or Path
            Destination file path.  Parent directory must already exist.
        """
        text = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        Path(path).write_text(text, encoding="utf-8")

    @classmethod
    def read(cls, path: str | Path) -> "SplitManifest":
        """Deserialise a :class:`SplitManifest` from a JSON file.

        Parameters
        ----------
        path : str or Path
            Path to a JSON file produced by :meth:`write`.

        Returns
        -------
        SplitManifest
            Reconstructed manifest.  The :attr:`checksum` of the returned
            object is recomputed from content and must equal the stored value.

        Raises
        ------
        ManifestError
            If the file is malformed or the stored checksum does not match.
        """
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            raise ManifestError(f"Failed to read manifest from {path!r}: {exc}") from exc

        try:
            seed: int = raw["seed"]
            fractions: dict[str, float] = raw["fractions"]
            assignments: dict[str, tuple[str, ...]] = {
                role: tuple(raw["assignments"][role]) for role in SPLIT_ROLES
            }
            exclusions: dict[str, str] = raw["exclusions"]
            counts: dict[str, int] = {k: int(v) for k, v in raw["counts"].items()}
            stored_checksum: str = raw["checksum"]
        except (KeyError, TypeError) as exc:
            raise ManifestError(f"Manifest JSON is missing required field: {exc}") from exc

        manifest = cls(
            seed=seed,
            fractions=fractions,
            assignments=assignments,
            exclusions=exclusions,
            counts=counts,
        )
        if manifest.checksum != stored_checksum:
            raise ManifestError(
                f"Manifest checksum mismatch: stored {stored_checksum!r} "
                f"!= recomputed {manifest.checksum!r}.  "
                "The file may have been modified after writing."
            )
        return manifest


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_manifest(
    eligible_perturbation_ids: Collection[str],
    fractions: "SplitFractions",
    seed: int,
    *,
    exclusions: Mapping[str, str] | None = None,
) -> SplitManifest:
    """Build a deterministic :class:`SplitManifest` for the given perturbation IDs.

    Assignment depends **only** on the sorted IDs, the integer seed, and the
    fraction spec — never on expression values or cell-level data.

    Parameters
    ----------
    eligible_perturbation_ids : Collection[str]
        Non-empty collection of perturbation IDs to split.  Duplicates are
        deduplicated before splitting.
    fractions : SplitFractions
        Fractional sizes for the four roles.
    seed : int
        Integer seed for ``numpy.random.default_rng``.  Using the same seed
        with the same (deduplicated, sorted) IDs always produces the same split.
    exclusions : Mapping[str, str] or None, optional
        Mapping from excluded perturbation IDs to human-readable reasons.  These
        IDs are recorded in the manifest but are not assigned to any role.

    Returns
    -------
    SplitManifest
        Frozen, content-addressed manifest.

    Raises
    ------
    ManifestError
        If *eligible_perturbation_ids* is empty after deduplication.

    Notes
    -----
    **Algorithm:**

    1. Deduplicate and sort the eligible IDs.
    2. Seed ``numpy.random.default_rng(seed)`` and permute the sorted array
       with ``rng.permutation``.
    3. Compute per-role integer counts using the **largest-remainder (Hamilton)**
       method: ``base[i] = floor(n * frac[i])``.  Distribute the remainder
       ``n - sum(base)`` one unit each to the roles with the largest fractional
       remainders, ties broken by ``SPLIT_ROLES`` order.
    4. Partition the permuted array into the four roles in ``SPLIT_ROLES`` order.
    5. Store each role's IDs as a **sorted** tuple for canonical representation.
    """
    # ------------------------------------------------------------------
    # 1. Deduplicate and sort
    # ------------------------------------------------------------------
    unique_sorted: list[str] = sorted(set(eligible_perturbation_ids))
    n = len(unique_sorted)
    if n == 0:
        raise ManifestError(
            "eligible_perturbation_ids must be non-empty after deduplication.  "
            "Cannot build a split manifest with no eligible perturbations."
        )

    # ------------------------------------------------------------------
    # 2. Permute using a seeded RNG
    # ------------------------------------------------------------------
    rng = np.random.default_rng(seed)
    id_array = np.array(unique_sorted, dtype=object)
    permuted: np.ndarray = rng.permutation(id_array)

    # ------------------------------------------------------------------
    # 3. Largest-remainder (Hamilton) integer counts
    # ------------------------------------------------------------------
    frac_values = [
        fractions.base_train,
        fractions.method_development,
        fractions.conformal_calibration,
        fractions.sealed_evaluation,
    ]
    bases = [int(n * f) for f in frac_values]
    remainders = [n * f - int(n * f) for f in frac_values]
    leftover = n - sum(bases)

    # Sort by descending remainder; ties broken by SPLIT_ROLES index order (stable)
    role_indices_by_remainder = sorted(
        range(len(frac_values)),
        key=lambda i: (-remainders[i], i),
    )
    int_counts = list(bases)
    for k in range(leftover):
        int_counts[role_indices_by_remainder[k]] += 1

    # Sanity — should never fail given valid SplitFractions (not stripped by -O)
    if sum(int_counts) != n:
        raise ManifestError(
            f"Largest-remainder counts sum to {sum(int_counts)}, expected {n}; split-algorithm bug."
        )

    # ------------------------------------------------------------------
    # 4. Partition the permuted array
    # ------------------------------------------------------------------
    assignments: dict[str, tuple[str, ...]] = {}
    offset = 0
    for i, role in enumerate(SPLIT_ROLES):
        chunk: list[str] = permuted[offset : offset + int_counts[i]].tolist()
        # 5. Store as sorted tuple for canonical representation
        assignments[role] = tuple(sorted(chunk))
        offset += int_counts[i]

    # ------------------------------------------------------------------
    # 6. Build counts dict
    # ------------------------------------------------------------------
    excl_dict: dict[str, str] = dict(exclusions) if exclusions is not None else {}
    counts: dict[str, int] = {role: int_counts[i] for i, role in enumerate(SPLIT_ROLES)}
    counts["excluded"] = len(excl_dict)
    counts["eligible_total"] = n

    # ------------------------------------------------------------------
    # 7. Build fractions dict (role → float)
    # ------------------------------------------------------------------
    fractions_dict: dict[str, float] = {role: frac_values[i] for i, role in enumerate(SPLIT_ROLES)}

    return SplitManifest(
        seed=seed,
        fractions=fractions_dict,
        assignments=assignments,
        exclusions=excl_dict,
        counts=counts,
    )


def build_manifest_from_index(
    index: "ReplogleIndex",
    fractions: "SplitFractions",
    seed: int,
) -> SplitManifest:
    """Build a :class:`SplitManifest` directly from a :class:`~alive.data.replogle.ReplogleIndex`.

    Convenience wrapper that unpacks ``index.eligible_perturbations`` and
    ``index.exclusions`` so the caller does not need to re-plumb them.

    Parameters
    ----------
    index : ReplogleIndex
        Validated metadata index from :func:`~alive.data.replogle.build_index`.
    fractions : SplitFractions
        Fractional sizes for the four roles.
    seed : int
        Integer seed passed to :func:`build_manifest`.

    Returns
    -------
    SplitManifest
        Deterministic, content-addressed manifest.
    """
    return build_manifest(
        index.eligible_perturbations,
        fractions,
        seed,
        exclusions=index.exclusions,
    )
