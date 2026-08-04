"""Tests for the persisted Phase-2a OOF fold manifest — written FIRST (TDD, D2 Task 1).

The :class:`~alive.compose.select.OOFFoldManifest` is the canonical, checksummed
record of the EXACT gene-disjoint OOF folds built at the single selection call
(``select.py`` inside :func:`~alive.compose.select.select_hyperparams`). Later D2
tasks LOAD and VERIFY it instead of re-deriving folds, so it must:

  * record exactly the folds produced by the single selection call (positions AND
    IDs, aligned) — never a second, independently rebuilt fold set;
  * bind a self-excluding checksum that moves when any recorded content moves but
    preserves position↔ID alignment across a pair-row shuffle;
  * fail closed on load for tampered positions / IDs / coverage / seed / checksum
    and for unknown / missing keys; and
  * be byte-identical across two runs on identical inputs.

SYNTHETIC-ONLY: pure ``numpy``; NO seal access, NO sealed store. Development-role
only (this task opens no seal and touches no sealed outcome).

The fixture DERIVES the seed-11 gene groups first (never hardcodes ``(0, 1, 2,
-1)``): it reproduces the ``build_gene_disjoint_folds`` partition, then builds at
least one within-group pair per group and at least one cross-group pair, and
asserts every retained fold has non-empty train AND test.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from numpy.random import PCG64, Generator

from alive.compose.models import L1Model
from alive.compose.select import (
    OOFFoldManifest,
    OOFFoldManifestError,
    build_gene_disjoint_folds,
    select_hyperparams,
)
from alive.provenance import sha256_json

# Effectively unbounded: this module tests the OOF fold manifest, not the
# registered conditioning screen (see ``test_condition_ceiling.py``). Finite
# because selection refuses a nan/inf ceiling -- an infinite one would silence
# the screen, which is exactly the failure that refusal exists to stop.
_NO_CEILING = 1e300


# --------------------------------------------------------------------------- #
# fixture — DERIVE the seed-11 gene groups, then build deliberate pairs
# --------------------------------------------------------------------------- #

_SEED = 11
_N_FOLDS = 3
_N_GENES = 6


def _canon(a: str, b: str) -> tuple[str, str]:
    """Canonical UTF-8 pair ID ``(min, max)``."""
    return (a, b) if a.encode("utf-8") <= b.encode("utf-8") else (b, a)


def _seed_groups(n_genes: int, n_folds: int, seed: int) -> list[list[int]]:
    """Reproduce ``build_gene_disjoint_folds``'s gene partition (round-robin)."""
    present = sorted(range(n_genes))
    rng = Generator(PCG64(seed))
    permuted = list(rng.permutation(present))
    groups: list[list[int]] = [[] for _ in range(n_folds)]
    for position, gene in enumerate(permuted):
        groups[position % n_folds].append(int(gene))
    return [sorted(g) for g in groups]


def _instance(rng, *, p: int = 3, k: int = 2):
    """A valid synthetic OOF instance built from the DERIVED seed-11 groups.

    Every gene appears in a pair (so the partition ``build_gene_disjoint_folds``
    sees matches the derived groups), each group contributes exactly one
    within-group (test) pair, and one cross-group pair is added (an uncovered,
    excluded pair). This guarantees every retained fold has non-empty train AND
    test.
    """
    groups = _seed_groups(_N_GENES, _N_FOLDS, _SEED)
    assert all(len(g) >= 2 for g in groups), "each seed-11 group must hold >=2 genes"
    gene_ids = [f"G{i}" for i in range(_N_GENES)]

    idx_pairs: list[tuple[int, int]] = []
    # one within-group pair per group (both genes held out together -> a test pair)
    for group in groups:
        idx_pairs.append((group[0], group[1]))
    # one cross-group pair (exactly one gene held out per fold -> always excluded)
    idx_pairs.append((groups[0][0], groups[1][0]))

    pair_ids = [_canon(gene_ids[g], gene_ids[h]) for g, h in idx_pairs]
    n_pairs = len(idx_pairs)
    Z = rng.normal(size=(_N_GENES, k))
    eps = rng.normal(size=(n_pairs, p))
    additive = rng.normal(size=(n_pairs, p))
    return {
        "gene_ids": gene_ids,
        "groups": groups,
        "idx_pairs": idx_pairs,
        "pair_ids": pair_ids,
        "Z": Z,
        "eps": eps,
        "additive": additive,
        "k": k,
        "p": p,
    }


def _select(inst):
    return select_hyperparams(
        idx_pairs=inst["idx_pairs"],
        pair_ids=inst["pair_ids"],
        eps_obs=inst["eps"],
        additive=inst["additive"],
        factors_by_k={inst["k"]: inst["Z"]},
        k_total_grid=[inst["k"]],
        lambda_grid=[0.1],
        n_genes=_N_GENES,
        n_folds=_N_FOLDS,
        seed=_SEED,
        model_factory=lambda: L1Model(),
        uncovered_tolerance=0.75,
        condition_ceiling=_NO_CEILING,
    )


def test_fixture_is_a_valid_oof_layout():
    """Sanity: derived groups give >=1 within-group + >=1 cross-group pair; folds non-empty."""
    inst = _instance(np.random.default_rng(0))
    folds = build_gene_disjoint_folds(
        inst["idx_pairs"], n_genes=_N_GENES, n_folds=_N_FOLDS, seed=_SEED
    )
    # >=1 within-group (test) pair per group and >=1 cross-group pair overall
    for fold in folds:
        assert len(fold.test_idx) >= 1
        assert len(fold.train_idx) >= 1  # non-empty train AND test
    total_excluded = {i for fold in folds for i in fold.excluded_idx}
    assert len(total_excluded) >= 1  # at least one cross-group pair


# --------------------------------------------------------------------------- #
# 1. records exactly the folds returned by the single selection call
# --------------------------------------------------------------------------- #
def test_manifest_records_exactly_the_single_call_folds():
    inst = _instance(np.random.default_rng(1))
    result = _select(inst)
    manifest = result.oof_manifest
    assert isinstance(manifest, OOFFoldManifest)
    assert manifest.schema == "compose_oof_fold_manifest_v1"
    assert manifest.n_genes == _N_GENES
    assert manifest.n_folds == _N_FOLDS
    assert manifest.split_seed == _SEED
    assert manifest.calibration_pair_ids == tuple(tuple(p) for p in inst["pair_ids"])

    # the manifest must mirror the deterministic single fold set exactly
    folds = build_gene_disjoint_folds(
        inst["idx_pairs"], n_genes=_N_GENES, n_folds=_N_FOLDS, seed=_SEED
    )
    assert len(manifest.folds) == len(folds) == _N_FOLDS
    pair_ids = tuple(tuple(p) for p in inst["pair_ids"])
    for i, (record, fold) in enumerate(zip(manifest.folds, folds)):
        assert record.fold_index == i
        assert record.held_out_gene_indices == tuple(fold.held_out_genes)
        assert record.train_pair_positions == tuple(fold.train_idx)
        assert record.test_pair_positions == tuple(fold.test_idx)
        assert record.excluded_pair_positions == tuple(fold.excluded_idx)
        # position -> ID alignment holds within the record
        assert record.train_pair_ids == tuple(pair_ids[j] for j in fold.train_idx)
        assert record.test_pair_ids == tuple(pair_ids[j] for j in fold.test_idx)
        assert record.excluded_pair_ids == tuple(pair_ids[j] for j in fold.excluded_idx)
        # retained folds are non-empty train AND test
        assert record.train_pair_positions and record.test_pair_positions

    # coverage == union of test pair IDs, consistent with the selection result
    covered = tuple(sorted({pid for f in manifest.folds for pid in f.test_pair_ids}))
    assert manifest.covered_pair_ids == covered
    assert manifest.covered_pair_ids == result.union_test_pair_ids
    assert manifest.uncovered_pair_ids == result.uncovered_pair_ids
    assert len(manifest.manifest_checksum) == 64


# --------------------------------------------------------------------------- #
# 2. shuffling pair rows changes the checksum, preserves position<->ID alignment
# --------------------------------------------------------------------------- #
def test_shuffle_changes_checksum_but_preserves_alignment():
    inst = _instance(np.random.default_rng(2))
    base = _select(inst).oof_manifest

    order = [3, 0, 2, 1]  # a non-trivial permutation of the 4 pair rows
    shuffled = {
        "idx_pairs": [inst["idx_pairs"][i] for i in order],
        "pair_ids": [inst["pair_ids"][i] for i in order],
        "eps": inst["eps"][order],
        "additive": inst["additive"][order],
        "Z": inst["Z"],
        "k": inst["k"],
        "p": inst["p"],
    }
    shuffled_manifest = _select(shuffled).oof_manifest

    # row order is part of the manifest identity -> the checksum moves
    assert shuffled_manifest.manifest_checksum != base.manifest_checksum

    # ...but every fold's positions still map to the right IDs in each manifest
    for manifest, ids in (
        (base, tuple(tuple(p) for p in inst["pair_ids"])),
        (shuffled_manifest, tuple(tuple(p) for p in shuffled["pair_ids"])),
    ):
        for record in manifest.folds:
            assert record.test_pair_ids == tuple(ids[j] for j in record.test_pair_positions)
            assert record.train_pair_ids == tuple(ids[j] for j in record.train_pair_positions)
            assert record.excluded_pair_ids == tuple(ids[j] for j in record.excluded_pair_positions)
    # the SET of covered pairs is invariant to row order (canonical sorted)
    assert shuffled_manifest.covered_pair_ids == base.covered_pair_ids


# --------------------------------------------------------------------------- #
# 3. load fail-closed on tampering + unknown/missing keys
# --------------------------------------------------------------------------- #
def _rechecksum(data: dict) -> dict:
    """Re-seal the manifest checksum so a tamper is NOT caught merely by the hash."""
    out = dict(data)
    payload = {k: v for k, v in out.items() if k != "manifest_checksum"}
    out["manifest_checksum"] = sha256_json(payload)
    return out


def _write(tmp_path, name, data) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")))
    return str(path)


def test_untampered_manifest_loads_and_matches(tmp_path):
    manifest = _select(_instance(np.random.default_rng(3))).oof_manifest
    path = tmp_path / "manifest.json"
    manifest.write_once(path)
    loaded = OOFFoldManifest.load(path)
    assert loaded.manifest_checksum == manifest.manifest_checksum
    assert loaded.to_dict() == manifest.to_dict()


def test_load_rejects_tampered_positions(tmp_path):
    manifest = _select(_instance(np.random.default_rng(4))).oof_manifest
    data = manifest.to_dict()
    # break position<->ID alignment: point a test position at a different pair,
    # then re-seal the checksum so ONLY the structural check can catch it.
    n = len(data["calibration_pair_ids"])
    fold = data["folds"][0]
    fold["test_pair_positions"] = [(fold["test_pair_positions"][0] + 1) % n]
    tampered = _rechecksum(data)
    with pytest.raises(OOFFoldManifestError):
        OOFFoldManifest.load(_write(tmp_path, "positions.json", tampered))


def test_load_rejects_tampered_ids(tmp_path):
    manifest = _select(_instance(np.random.default_rng(5))).oof_manifest
    data = manifest.to_dict()
    # a test_pair_id that no longer matches its recorded position
    other = data["calibration_pair_ids"][-1]
    data["folds"][0]["test_pair_ids"] = [list(other)]
    tampered = _rechecksum(data)
    with pytest.raises(OOFFoldManifestError):
        OOFFoldManifest.load(_write(tmp_path, "ids.json", tampered))


def test_load_rejects_tampered_coverage(tmp_path):
    manifest = _select(_instance(np.random.default_rng(6))).oof_manifest
    data = manifest.to_dict()
    # drop a covered pair so coverage != union of the folds' test IDs
    data["covered_pair_ids"] = data["covered_pair_ids"][:-1]
    tampered = _rechecksum(data)
    with pytest.raises(OOFFoldManifestError):
        OOFFoldManifest.load(_write(tmp_path, "coverage.json", tampered))


def test_load_rejects_tampered_seed(tmp_path):
    manifest = _select(_instance(np.random.default_rng(7))).oof_manifest
    data = manifest.to_dict()
    data["split_seed"] = data["split_seed"] + 1  # NOT re-sealed -> checksum mismatch
    with pytest.raises(OOFFoldManifestError):
        OOFFoldManifest.load(_write(tmp_path, "seed.json", data))


def test_load_rejects_tampered_checksum(tmp_path):
    manifest = _select(_instance(np.random.default_rng(8))).oof_manifest
    data = manifest.to_dict()
    data["manifest_checksum"] = "0" * 64
    with pytest.raises(OOFFoldManifestError):
        OOFFoldManifest.load(_write(tmp_path, "checksum.json", data))


def test_load_rejects_unknown_key(tmp_path):
    manifest = _select(_instance(np.random.default_rng(9))).oof_manifest
    data = manifest.to_dict()
    data["surprise"] = 1
    with pytest.raises(OOFFoldManifestError):
        OOFFoldManifest.load(_write(tmp_path, "unknown.json", data))


def test_load_rejects_missing_key(tmp_path):
    manifest = _select(_instance(np.random.default_rng(10))).oof_manifest
    data = manifest.to_dict()
    del data["split_seed"]
    with pytest.raises(OOFFoldManifestError):
        OOFFoldManifest.load(_write(tmp_path, "missing.json", data))


def test_load_rejects_noncanonical_pair_id(tmp_path):
    manifest = _select(_instance(np.random.default_rng(11))).oof_manifest
    data = manifest.to_dict()
    a, b = data["calibration_pair_ids"][0]
    data["calibration_pair_ids"][0] = [b, a]  # reversed -> non-canonical
    tampered = _rechecksum(data)
    with pytest.raises(OOFFoldManifestError):
        OOFFoldManifest.load(_write(tmp_path, "noncanon.json", tampered))


# --------------------------------------------------------------------------- #
# 5. re-running with identical inputs -> byte-identical manifest bytes
# --------------------------------------------------------------------------- #
def test_reruns_produce_byte_identical_manifest(tmp_path):
    inst = _instance(np.random.default_rng(12))
    m1 = _select(inst).oof_manifest
    inst2 = _instance(np.random.default_rng(12))  # identical inputs
    m2 = _select(inst2).oof_manifest
    p1 = tmp_path / "a.json"
    p2 = tmp_path / "b.json"
    m1.write_once(p1)
    m2.write_once(p2)
    assert p1.read_bytes() == p2.read_bytes()
    assert m1.manifest_checksum == m2.manifest_checksum


def test_write_once_refuses_overwrite(tmp_path):
    manifest = _select(_instance(np.random.default_rng(13))).oof_manifest
    path = tmp_path / "once.json"
    manifest.write_once(path)
    with pytest.raises((OOFFoldManifestError, FileExistsError)):
        manifest.write_once(path)
