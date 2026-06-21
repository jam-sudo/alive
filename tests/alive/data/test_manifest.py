"""Tests for src/alive/data/manifest.py — deterministic four-way perturbation split manifest.

All tests use small synthetic fixtures; no real data is required.

TDD order: tests are written first; the implementation must pass all of them.
"""

from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path

import anndata
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from alive.config import SplitFractions
from alive.data.manifest import (
    SPLIT_ROLES,
    ManifestError,
    SplitManifest,
    build_manifest,
    build_manifest_from_index,
)
from alive.data.replogle import DatasetSchema, build_index

# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

# Registered split fractions from the project config
_FRACTIONS = SplitFractions(
    base_train=0.45,
    method_development=0.25,
    conformal_calibration=0.15,
    sealed_evaluation=0.15,
)

_SEED = 42


def _make_ids(n: int, prefix: str = "pert_") -> list[str]:
    """Generate *n* unique perturbation IDs."""
    return [f"{prefix}{i:04d}" for i in range(n)]


def _make_manifest(ids: list[str] | None = None, seed: int = _SEED) -> SplitManifest:
    """Build a default manifest from a list of IDs."""
    if ids is None:
        ids = _make_ids(100)
    return build_manifest(ids, _FRACTIONS, seed)


def _make_adata_for_index(
    pert_labels: list[str],
    n_ctrl: int = 50,
    n_cells_per_pert: int = 30,
    n_genes: int = 5,
    data_value: float = 1.0,
) -> anndata.AnnData:
    """Build a minimal AnnData with the given perturbation labels."""
    all_labels = ["ctrl"] * n_ctrl + [p for p in pert_labels for _ in range(n_cells_per_pert)]
    n_cells = len(all_labels)
    X = sp.random(n_cells, n_genes, density=0.3, format="csr", dtype=np.float32)
    X.data[:] = data_value
    obs = pd.DataFrame({"target": all_labels}, index=[f"c{i}" for i in range(n_cells)])
    var = pd.DataFrame(index=[f"g{i}" for i in range(n_genes)])
    return anndata.AnnData(X=X, obs=obs, var=var)


# ---------------------------------------------------------------------------
# SPLIT_ROLES constant
# ---------------------------------------------------------------------------


def test_split_roles_constant() -> None:
    """SPLIT_ROLES must list the four expected role names in order."""
    assert SPLIT_ROLES == (
        "base_train",
        "method_development",
        "conformal_calibration",
        "sealed_evaluation",
    )


# ---------------------------------------------------------------------------
# Disjointness: role sets are pairwise disjoint
# ---------------------------------------------------------------------------


def test_disjointness() -> None:
    """The four role ID sets must be pairwise disjoint."""
    m = _make_manifest()
    sets = [set(m.assignments[role]) for role in SPLIT_ROLES]
    for i, si in enumerate(sets):
        for j, sj in enumerate(sets):
            if i != j:
                overlap = si & sj
                assert not overlap, (
                    f"Roles {SPLIT_ROLES[i]!r} and {SPLIT_ROLES[j]!r} share IDs: {overlap}"
                )


# ---------------------------------------------------------------------------
# Full coverage: union of roles == set of eligible IDs
# ---------------------------------------------------------------------------


def test_full_coverage() -> None:
    """Every eligible ID must appear in exactly one role (no drops, no extras)."""
    ids = _make_ids(100)
    m = build_manifest(ids, _FRACTIONS, _SEED)
    assigned = set()
    for role in SPLIT_ROLES:
        assigned.update(m.assignments[role])
    assert assigned == set(ids)


# ---------------------------------------------------------------------------
# Counts sum: role counts sum to eligible_total; match actual lengths
# ---------------------------------------------------------------------------


def test_counts_sum() -> None:
    """Role counts must sum to eligible_total; each must equal len(assignments[role])."""
    ids = _make_ids(80)
    m = build_manifest(ids, _FRACTIONS, _SEED)

    total_from_roles = sum(m.counts[role] for role in SPLIT_ROLES)
    assert total_from_roles == m.counts["eligible_total"]
    assert m.counts["eligible_total"] == len(ids)

    for role in SPLIT_ROLES:
        assert m.counts[role] == len(m.assignments[role]), (
            f"counts[{role!r}] = {m.counts[role]} but len(assignments) = {len(m.assignments[role])}"
        )


# ---------------------------------------------------------------------------
# Fraction proportions: largest-remainder counts are exact with n=1000
# ---------------------------------------------------------------------------


def test_fraction_proportions_exact() -> None:
    """With n=1000 and the registered fractions (0.45/0.25/0.15/0.15), each role count
    must equal the largest-remainder expectation exactly."""
    n = 1000
    ids = _make_ids(n)
    m = build_manifest(ids, _FRACTIONS, _SEED)

    # Compute expected counts via largest-remainder (Hamilton) method
    fracs = [
        _FRACTIONS.base_train,
        _FRACTIONS.method_development,
        _FRACTIONS.conformal_calibration,
        _FRACTIONS.sealed_evaluation,
    ]
    bases = [int(n * f) for f in fracs]
    remainders = [(n * f - int(n * f), i) for i, f in enumerate(fracs)]
    leftover = n - sum(bases)
    # Sort by remainder descending, ties broken by SPLIT_ROLES order (stable sort by index)
    remainders_sorted = sorted(remainders, key=lambda x: (-x[0], x[1]))
    expected = list(bases)
    for k in range(leftover):
        expected[remainders_sorted[k][1]] += 1

    assert sum(expected) == n, "Test logic error: expected counts must sum to n"

    for i, role in enumerate(SPLIT_ROLES):
        assert m.counts[role] == expected[i], (
            f"Role {role!r}: expected {expected[i]} but got {m.counts[role]}"
        )


# ---------------------------------------------------------------------------
# Order independence: shuffled input → same checksum and assignments
# ---------------------------------------------------------------------------


def test_order_independence() -> None:
    """Building from a shuffled copy of the same IDs must yield an identical manifest."""
    ids = _make_ids(120)
    shuffled = ids[:]
    random.seed(7)
    random.shuffle(shuffled)
    assert shuffled != ids, "Shuffle must actually change the order for this test to be meaningful"

    m1 = build_manifest(ids, _FRACTIONS, _SEED)
    m2 = build_manifest(shuffled, _FRACTIONS, _SEED)

    assert m1.checksum == m2.checksum
    assert m1.assignments == m2.assignments


# ---------------------------------------------------------------------------
# Determinism: same inputs → identical checksum; different seed → different checksum
# ---------------------------------------------------------------------------


def test_determinism_same_inputs() -> None:
    """Two calls with identical inputs must produce identical checksums."""
    ids = _make_ids(60)
    m1 = build_manifest(ids, _FRACTIONS, _SEED)
    m2 = build_manifest(ids, _FRACTIONS, _SEED)
    assert m1.checksum == m2.checksum


def test_determinism_different_seed() -> None:
    """A different seed must produce a different assignment (and checksum)."""
    ids = _make_ids(60)
    m1 = build_manifest(ids, _FRACTIONS, _SEED)
    m2 = build_manifest(ids, _FRACTIONS, _SEED + 1)
    assert m1.checksum != m2.checksum


# ---------------------------------------------------------------------------
# Expression cannot affect assignment (outcome-independence end-to-end)
# ---------------------------------------------------------------------------


def test_expression_independence() -> None:
    """Two ReplogleIndex fixtures with the SAME eligible IDs but DIFFERENT expression
    values must yield identical manifests (same checksum)."""
    pert_labels = [f"gene_{i}" for i in range(20)]
    schema = DatasetSchema(perturbation_key="target", control_value="ctrl")
    min_cells = 10

    adata1 = _make_adata_for_index(pert_labels, data_value=1.0)
    adata2 = _make_adata_for_index(pert_labels, data_value=999.0)

    idx1 = build_index(adata1, schema, min_cells=min_cells)
    idx2 = build_index(adata2, schema, min_cells=min_cells)

    assert idx1.eligible_perturbations == idx2.eligible_perturbations, (
        "Fixtures must have the same eligible IDs for this test to be meaningful"
    )

    m1 = build_manifest_from_index(idx1, _FRACTIONS, _SEED)
    m2 = build_manifest_from_index(idx2, _FRACTIONS, _SEED)

    assert m1.checksum == m2.checksum


# ---------------------------------------------------------------------------
# Exclusions: recorded and counted; excluded IDs not in any role
# ---------------------------------------------------------------------------


def test_exclusions_recorded() -> None:
    """Exclusions must be propagated to the manifest; excluded IDs must not be in any role."""
    eligible_ids = _make_ids(50)
    excluded = {"bad_pert_1": "below min_cells", "bad_pert_2": "no external feature"}
    m = build_manifest(eligible_ids, _FRACTIONS, _SEED, exclusions=excluded)

    assert m.exclusions == excluded
    assert m.counts["excluded"] == 2

    all_assigned = set()
    for role in SPLIT_ROLES:
        all_assigned.update(m.assignments[role])

    for excl_id in excluded:
        assert excl_id not in all_assigned, f"Excluded ID {excl_id!r} must not appear in any role"


def test_exclusions_none_default() -> None:
    """With no exclusions passed, counts['excluded'] must be 0 and exclusions must be empty."""
    m = _make_manifest()
    assert m.exclusions == {}
    assert m.counts["excluded"] == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_eligible_ids_raises() -> None:
    """Empty eligible IDs must raise ManifestError."""
    with pytest.raises(ManifestError, match="empty"):
        build_manifest([], _FRACTIONS, _SEED)


def test_ids_for_unknown_role_raises() -> None:
    """ids_for with an unknown role must raise ManifestError."""
    m = _make_manifest()
    with pytest.raises(ManifestError):
        m.ids_for("nonexistent_role")


def test_split_of_unassigned_id_raises() -> None:
    """split_of for an unassigned ID must raise ManifestError."""
    m = _make_manifest()
    with pytest.raises(ManifestError):
        m.split_of("completely_unknown_pert_xyz")


def test_ids_for_known_roles() -> None:
    """ids_for must return the correct tuple for every known role."""
    m = _make_manifest()
    for role in SPLIT_ROLES:
        result = m.ids_for(role)
        assert result == m.assignments[role]


def test_split_of_assigned_ids() -> None:
    """split_of must return the correct role for each assigned ID."""
    ids = _make_ids(40)
    m = build_manifest(ids, _FRACTIONS, _SEED)
    for role in SPLIT_ROLES:
        for pid in m.assignments[role]:
            assert m.split_of(pid) == role


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_deduplication() -> None:
    """Duplicate IDs in input must be silently deduplicated before splitting."""
    ids = _make_ids(30)
    ids_with_dups = ids + ids[:10]  # add 10 duplicates
    m = build_manifest(ids_with_dups, _FRACTIONS, _SEED)
    # The manifest must treat the 30 unique IDs only
    total_assigned = sum(m.counts[role] for role in SPLIT_ROLES)
    assert total_assigned == len(set(ids_with_dups))


# ---------------------------------------------------------------------------
# Round-trip: write/read preserves manifest and checksum
# ---------------------------------------------------------------------------


def test_round_trip() -> None:
    """SplitManifest.read(write(m)) must reproduce the original manifest and checksum."""
    ids = _make_ids(80)
    excluded = {"excl_1": "test exclusion"}
    m = build_manifest(ids, _FRACTIONS, _SEED, exclusions=excluded)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "manifest.json"
        m.write(path)

        m2 = SplitManifest.read(path)

    assert m2.seed == m.seed
    assert m2.fractions == m.fractions
    assert m2.assignments == m.assignments
    assert m2.exclusions == m.exclusions
    assert m2.counts == m.counts
    assert m2.checksum == m.checksum


def test_round_trip_json_is_canonical() -> None:
    """Written JSON must be parseable and contain the expected top-level keys."""
    m = _make_manifest(_make_ids(20))
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "manifest.json"
        m.write(path)
        raw = json.loads(path.read_text())

    for key in ("seed", "fractions", "assignments", "exclusions", "counts", "checksum"):
        assert key in raw, f"Missing key {key!r} in written JSON"


# ---------------------------------------------------------------------------
# build_manifest_from_index helper
# ---------------------------------------------------------------------------


def test_build_manifest_from_index() -> None:
    """build_manifest_from_index must produce the same result as build_manifest
    called with index.eligible_perturbations and index.exclusions."""
    pert_labels = [f"g{i}" for i in range(15)]
    schema = DatasetSchema(perturbation_key="target", control_value="ctrl")
    adata = _make_adata_for_index(pert_labels, n_cells_per_pert=20)
    idx = build_index(adata, schema, min_cells=10)

    m_from_index = build_manifest_from_index(idx, _FRACTIONS, _SEED)
    m_direct = build_manifest(
        idx.eligible_perturbations, _FRACTIONS, _SEED, exclusions=idx.exclusions
    )

    assert m_from_index.checksum == m_direct.checksum
    assert m_from_index.assignments == m_direct.assignments


# ---------------------------------------------------------------------------
# to_dict: check structure
# ---------------------------------------------------------------------------


def test_to_dict_structure() -> None:
    """to_dict must return a dict with all expected keys and correct types."""
    m = _make_manifest()
    d = m.to_dict()
    assert isinstance(d["seed"], int)
    assert isinstance(d["fractions"], dict)
    assert isinstance(d["assignments"], dict)
    assert isinstance(d["exclusions"], dict)
    assert isinstance(d["counts"], dict)
    assert isinstance(d["checksum"], str)
    assert len(d["checksum"]) == 64  # SHA-256 hex
    for role in SPLIT_ROLES:
        assert role in d["assignments"]
        assert isinstance(d["assignments"][role], list)
