"""Deterministic canonical pair manifest and role assignment (COMPOSE Phase 2a).

The headline ``sealed_double_unseen`` role holds pairs whose BOTH genes are
absent from every ``combo_calibration`` pair (combo/pair-zero-shot). The
``sealed_single_unseen`` role holds pairs with exactly one calibration gene.
Selection is outcome-independent — driven only by a seeded gene partition.

Determinism contract (plan §2.3, task brief):

- ``0 < calibration_fraction < 1`` is validated.
- self-pairs and empty gene IDs are rejected.
- pairs are canonicalized to ``(min, max)`` and deduplicated.
- gene strings are ordered by their encoded UTF-8 bytes, never by locale.
- the calibration partition uses ``numpy.random.Generator(PCG64(seed))``.
- the calibration-gene count uses explicit round-half-to-even (``numpy.rint``).
- a serialized manifest records the algorithm/version, eligibility hash, role
  membership and a self-excluding checksum (via :func:`alive.provenance.sha256_json`).

Sealed roles (``sealed_double_unseen``, ``sealed_single_unseen``) are partition
*identities* only; this module never touches sealed outcomes (plan §2.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from numpy.random import PCG64, Generator

from alive.provenance import sha256_json

PAIR_SPLIT_ALGORITHM = "compose_gene_partition_pair_split"
PAIR_SPLIT_VERSION = "2a.1"

#: Manifest role keys, emitted in this fixed order.
ROLE_NAMES = ("combo_calibration", "sealed_double_unseen", "sealed_single_unseen")


@dataclass(frozen=True)
class ComposeSplit:
    """Disjoint pair roles plus the calibration gene set.

    Attributes
    ----------
    combo_calibration : list of tuple of str
        Canonical pairs whose both genes lie in the calibration gene set
        (development role).
    sealed_double_unseen : list of tuple of str
        Canonical pairs whose neither gene lies in the calibration gene set
        (combo/pair-zero-shot; sealed role identity only).
    sealed_single_unseen : list of tuple of str
        Canonical pairs with exactly one calibration gene (sealed role identity).
    combo_genes : frozenset of str
        The calibration gene set.
    """

    combo_calibration: list[tuple[str, str]]
    sealed_double_unseen: list[tuple[str, str]]
    sealed_single_unseen: list[tuple[str, str]]
    combo_genes: frozenset[str]


def _canonicalize_pairs(
    eligible_pairs: Iterable[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Validate, UTF-8-canonicalize and deduplicate eligible pairs.

    Each pair is reordered as ``(min_utf8(g, h), max_utf8(g, h))`` where the
    ordering compares encoded UTF-8 bytes (Python ``str`` comparison is already
    code-point/byte ordered for UTF-8, and explicitly locale-independent).
    Duplicates collapse; the result is sorted for reproducibility.

    Parameters
    ----------
    eligible_pairs : iterable of tuple of str
        Candidate gene pairs; order within a pair is irrelevant.

    Returns
    -------
    list of tuple of str
        Sorted, deduplicated canonical pairs.

    Raises
    ------
    ValueError
        If ``eligible_pairs`` is empty, a pair is not a 2-element sequence,
        a gene ID is empty, or a pair is a self-pair (after canonicalization).
    """
    canon: set[tuple[str, str]] = set()
    saw_any = False
    for pair in eligible_pairs:
        saw_any = True
        items = tuple(pair)
        if len(items) != 2:
            raise ValueError(f"each pair must have exactly 2 gene IDs, got {items!r}")
        g, h = items
        if not isinstance(g, str) or not isinstance(h, str):
            raise ValueError(f"gene IDs must be strings, got {items!r}")
        if g == "" or h == "":
            raise ValueError(f"empty gene ID in pair {items!r}")
        if g == h:
            raise ValueError(f"self-pair is not a valid combination: {items!r}")
        # UTF-8 byte ordering == Python str comparison for valid str (locale-free).
        canon.add((g, h) if g.encode("utf-8") <= h.encode("utf-8") else (h, g))
    if not saw_any:
        raise ValueError("eligible_pairs must be non-empty")
    return sorted(canon, key=lambda p: (p[0].encode("utf-8"), p[1].encode("utf-8")))


def _calibration_gene_count(n_genes: int, calibration_fraction: float) -> int:
    """Round-half-to-even count of calibration genes.

    Uses :func:`numpy.rint`, which implements IEEE round-half-to-even
    ("banker's rounding"), so e.g. ``2.5 -> 2`` and ``3.5 -> 4``.

    Parameters
    ----------
    n_genes : int
        Total number of distinct genes.
    calibration_fraction : float
        Target fraction of genes assigned to calibration.

    Returns
    -------
    int
        Number of calibration genes, clamped to ``[0, n_genes]``.
    """
    raw = float(calibration_fraction) * float(n_genes)
    n_cal = int(np.rint(raw))
    return max(0, min(n_genes, n_cal))


def build_pair_split(
    eligible_pairs: list[tuple[str, str]],
    *,
    seed: int,
    calibration_fraction: float,
) -> ComposeSplit:
    """Partition genes into calibration vs held-out, then assign pairs by role.

    Parameters
    ----------
    eligible_pairs : list of tuple of str
        Eligible gene pairs (order within a pair irrelevant; duplicates and
        reversed duplicates are collapsed).
    seed : int
        Seed for the ``PCG64`` gene-permutation generator.
    calibration_fraction : float
        Fraction of distinct genes assigned to the calibration set. Must satisfy
        ``0 < calibration_fraction < 1``.

    Returns
    -------
    ComposeSplit
        Disjoint role assignment plus the calibration gene set.

    Raises
    ------
    ValueError
        If ``calibration_fraction`` is outside ``(0, 1)`` or the pairs fail
        validation (see :func:`_canonicalize_pairs`).
    """
    if not (0.0 < calibration_fraction < 1.0):
        raise ValueError(
            f"calibration_fraction must satisfy 0 < f < 1, got {calibration_fraction!r}"
        )

    pairs = _canonicalize_pairs(eligible_pairs)
    genes = sorted(
        {g for pair in pairs for g in pair},
        key=lambda s: s.encode("utf-8"),
    )

    rng = Generator(PCG64(seed))
    perm = rng.permutation(len(genes))
    n_cal = _calibration_gene_count(len(genes), calibration_fraction)
    cal_genes = {genes[i] for i in perm[:n_cal]}

    combo_calibration: list[tuple[str, str]] = []
    sealed_double_unseen: list[tuple[str, str]] = []
    sealed_single_unseen: list[tuple[str, str]] = []
    for a, b in pairs:
        a_in, b_in = a in cal_genes, b in cal_genes
        if a_in and b_in:
            combo_calibration.append((a, b))
        elif not a_in and not b_in:
            sealed_double_unseen.append((a, b))  # neither gene in calibration
        else:
            sealed_single_unseen.append((a, b))  # exactly one gene in calibration

    return ComposeSplit(
        combo_calibration=combo_calibration,
        sealed_double_unseen=sealed_double_unseen,
        sealed_single_unseen=sealed_single_unseen,
        combo_genes=frozenset(cal_genes),
    )


def build_split_manifest(
    eligible_pairs: list[tuple[str, str]],
    split: ComposeSplit | None = None,
    *,
    seed: int,
    calibration_fraction: float,
) -> dict:
    """Build a deterministic, serializable manifest for a pair split.

    The manifest binds the eligibility universe, the algorithm identity and the
    full role membership, then seals them with a self-excluding checksum so any
    tampering is detectable.

    Parameters
    ----------
    eligible_pairs : list of tuple of str
        Eligible gene pairs (canonicalized internally).
    split : ComposeSplit, optional
        A pre-computed split. If ``None``, one is built from the same inputs.
        When provided, it must have been produced from the same
        ``eligible_pairs``/``seed``/``calibration_fraction``.
    seed : int
        Seed recorded in the manifest and used to (re)build the split.
    calibration_fraction : float
        Calibration fraction recorded in the manifest.

    Returns
    -------
    dict
        JSON-serializable manifest with keys ``algorithm``, ``version``,
        ``seed``, ``calibration_fraction``, ``eligibility_hash``,
        ``calibration_genes``, ``roles`` and ``checksum``.
    """
    pairs = _canonicalize_pairs(eligible_pairs)
    if split is None:
        split = build_pair_split(pairs, seed=seed, calibration_fraction=calibration_fraction)

    eligibility = [[a, b] for a, b in pairs]
    payload = {
        "algorithm": PAIR_SPLIT_ALGORITHM,
        "version": PAIR_SPLIT_VERSION,
        "seed": int(seed),
        "calibration_fraction": float(calibration_fraction),
        "eligibility_hash": sha256_json(eligibility),
        "calibration_genes": sorted(split.combo_genes, key=lambda s: s.encode("utf-8")),
        "roles": {
            "combo_calibration": [[a, b] for a, b in split.combo_calibration],
            "sealed_double_unseen": [[a, b] for a, b in split.sealed_double_unseen],
            "sealed_single_unseen": [[a, b] for a, b in split.sealed_single_unseen],
        },
    }
    manifest = dict(payload)
    manifest["checksum"] = sha256_json(payload)
    return manifest


def write_split_manifest(
    path: str | Path,
    eligible_pairs: list[tuple[str, str]],
    *,
    seed: int,
    calibration_fraction: float,
) -> dict:
    """Write a split manifest to ``path`` as canonical JSON, write-once.

    Parameters
    ----------
    path : str or Path
        Destination file. Must not already exist (write-once provenance, §11).
    eligible_pairs : list of tuple of str
        Eligible gene pairs (canonicalized internally).
    seed : int
        Seed for the split.
    calibration_fraction : float
        Calibration fraction for the split.

    Returns
    -------
    dict
        The manifest that was written.

    Raises
    ------
    FileExistsError
        If ``path`` already exists.
    """
    import json

    out = Path(path)
    if out.exists():
        raise FileExistsError(f"refusing to overwrite existing manifest: {out}")
    manifest = build_split_manifest(
        eligible_pairs, seed=seed, calibration_fraction=calibration_fraction
    )
    out.write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest
