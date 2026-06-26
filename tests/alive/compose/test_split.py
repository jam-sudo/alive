"""Tests for alive.compose.split — written FIRST per TDD protocol.

Enforces the double-unseen gene-isolation invariant (spec §2.3), deterministic
canonicalization, round-half-to-even calibration sizing, manifest serialization,
and leakage boundaries (plan §2.1).
"""

from __future__ import annotations

import json

import pytest

from alive.compose.split import (
    PAIR_SPLIT_ALGORITHM,
    PAIR_SPLIT_VERSION,
    ComposeSplit,
    build_pair_split,
    build_split_manifest,
    write_split_manifest,
)


def _pairs():
    genes = [chr(ord("A") + i) for i in range(8)]
    return [(genes[i], genes[j]) for i in range(8) for j in range(i + 1, 8)]


# --------------------------------------------------------------------------- #
# Roles, coverage, isolation invariant
# --------------------------------------------------------------------------- #


def test_roles_disjoint_and_cover():
    sp = build_pair_split(_pairs(), seed=0, calibration_fraction=0.6)
    assert isinstance(sp, ComposeSplit)
    all_pairs = set(_pairs())
    union = set(sp.combo_calibration) | set(sp.sealed_double_unseen) | set(sp.sealed_single_unseen)
    assert union == all_pairs  # every eligible pair gets exactly one role
    assert not (set(sp.combo_calibration) & set(sp.sealed_double_unseen))
    assert not (set(sp.combo_calibration) & set(sp.sealed_single_unseen))
    assert not (set(sp.sealed_double_unseen) & set(sp.sealed_single_unseen))


def test_double_unseen_genes_isolated_from_calibration():
    sp = build_pair_split(_pairs(), seed=1, calibration_fraction=0.6)
    cal_genes = {g for pair in sp.combo_calibration for g in pair}
    for a, b in sp.sealed_double_unseen:
        assert a not in cal_genes and b not in cal_genes  # gene isolation invariant


def test_double_unseen_genes_isolated_across_many_seeds():
    """sealed-double-unseen genes must never appear in ANY calibration pair."""
    for seed in range(25):
        sp = build_pair_split(_pairs(), seed=seed, calibration_fraction=0.5)
        cal_genes = {g for pair in sp.combo_calibration for g in pair}
        double_genes = {g for pair in sp.sealed_double_unseen for g in pair}
        assert not (double_genes & cal_genes)


def test_sealed_single_unseen_has_exactly_one_calibration_gene():
    sp = build_pair_split(_pairs(), seed=2, calibration_fraction=0.5)
    cal_genes = sp.combo_genes
    for a, b in sp.sealed_single_unseen:
        assert (a in cal_genes) ^ (b in cal_genes)  # exactly one


# --------------------------------------------------------------------------- #
# Canonicalization and deduplication
# --------------------------------------------------------------------------- #


def test_reversed_duplicates_are_canonicalized_and_deduped():
    pairs = [("B", "A"), ("A", "B"), ("C", "D"), ("D", "C")]
    sp = build_pair_split(pairs, seed=0, calibration_fraction=0.5)
    all_roles = sp.combo_calibration + sp.sealed_double_unseen + sp.sealed_single_unseen
    # canonical (min, max) ordering only, deduplicated
    assert sorted(all_roles) == [("A", "B"), ("C", "D")]
    for a, b in all_roles:
        assert a <= b


def test_canonical_ordering_uses_utf8_bytes_not_locale():
    # 'Z' (0x5A) < 'a' (0x61) by UTF-8 bytes; many locales sort case-insensitively.
    pairs = [("a", "Z")]
    sp = build_pair_split(pairs, seed=0, calibration_fraction=0.5)
    all_roles = sp.combo_calibration + sp.sealed_double_unseen + sp.sealed_single_unseen
    assert all_roles == [("Z", "a")]  # byte order: 'Z' first


def test_unicode_gene_ids():
    pairs = [("β", "α"), ("α", "β"), ("γ", "α")]
    sp = build_pair_split(pairs, seed=3, calibration_fraction=0.5)
    all_roles = set(sp.combo_calibration + sp.sealed_double_unseen + sp.sealed_single_unseen)
    # (α,β) canonical by utf-8 bytes; (α,γ) canonical
    assert all_roles == {("α", "β"), ("α", "γ")}
    manifest = build_split_manifest(pairs, sp, seed=3, calibration_fraction=0.5)
    # manifest is JSON-serializable with unicode preserved
    text = json.dumps(manifest, ensure_ascii=False)
    assert "α" in text


# --------------------------------------------------------------------------- #
# Round-half-to-even calibration sizing
# --------------------------------------------------------------------------- #


def test_exact_half_round_half_to_even_down():
    # 5 genes * 0.5 = 2.5 -> round-half-to-even -> 2 (nearest even)
    genes = ["A", "B", "C", "D", "E"]
    pairs = [(genes[i], genes[j]) for i in range(5) for j in range(i + 1, 5)]
    sp = build_pair_split(pairs, seed=0, calibration_fraction=0.5)
    assert len(sp.combo_genes) == 2


def test_exact_half_round_half_to_even_up():
    # 7 genes * 0.5 = 3.5 -> round-half-to-even -> 4 (nearest even)
    genes = [chr(ord("A") + i) for i in range(7)]
    pairs = [(genes[i], genes[j]) for i in range(7) for j in range(i + 1, 7)]
    sp = build_pair_split(pairs, seed=0, calibration_fraction=0.5)
    assert len(sp.combo_genes) == 4


# --------------------------------------------------------------------------- #
# Input validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("frac", [0.0, 1.0, -0.1, 1.5])
def test_invalid_calibration_fraction_rejected(frac):
    with pytest.raises(ValueError):
        build_pair_split(_pairs(), seed=0, calibration_fraction=frac)


def test_self_pairs_rejected():
    with pytest.raises(ValueError):
        build_pair_split([("A", "A")], seed=0, calibration_fraction=0.5)


def test_self_pairs_rejected_after_canonicalization():
    # reversed-equal also a self pair
    with pytest.raises(ValueError):
        build_pair_split([("A", "B"), ("X", "X")], seed=0, calibration_fraction=0.5)


def test_empty_gene_id_rejected():
    with pytest.raises(ValueError):
        build_pair_split([("A", "")], seed=0, calibration_fraction=0.5)
    with pytest.raises(ValueError):
        build_pair_split([("", "B")], seed=0, calibration_fraction=0.5)


def test_empty_input_rejected():
    with pytest.raises(ValueError):
        build_pair_split([], seed=0, calibration_fraction=0.5)


def test_non_tuple_pair_length_rejected():
    with pytest.raises(ValueError):
        build_pair_split([("A", "B", "C")], seed=0, calibration_fraction=0.5)  # type: ignore[list-item]


# --------------------------------------------------------------------------- #
# Determinism (incl. cross-process)
# --------------------------------------------------------------------------- #


def test_same_seed_identical_manifest_in_process():
    pairs = _pairs()
    m1 = build_split_manifest(pairs, seed=7, calibration_fraction=0.6)
    m2 = build_split_manifest(pairs, seed=7, calibration_fraction=0.6)
    assert m1 == m2
    assert m1["checksum"] == m2["checksum"]


def test_different_seed_changes_assignment():
    pairs = _pairs()
    m1 = build_split_manifest(pairs, seed=1, calibration_fraction=0.5)
    m2 = build_split_manifest(pairs, seed=2, calibration_fraction=0.5)
    # very likely different partition -> different checksum
    assert m1["checksum"] != m2["checksum"]


def test_cross_process_determinism(tmp_path):
    """A fresh interpreter with the same seed must produce an identical checksum."""
    import subprocess
    import sys

    script = (
        "import json\n"
        "from alive.compose.split import build_split_manifest\n"
        "genes=[chr(ord('A')+i) for i in range(8)]\n"
        "pairs=[(genes[i],genes[j]) for i in range(8) for j in range(i+1,8)]\n"
        "m=build_split_manifest(pairs, seed=7, calibration_fraction=0.6)\n"
        "print(m['checksum'])\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    child_checksum = out.stdout.strip()
    parent = build_split_manifest(_pairs(), seed=7, calibration_fraction=0.6)
    assert child_checksum == parent["checksum"]


# --------------------------------------------------------------------------- #
# Manifest contents and write helper
# --------------------------------------------------------------------------- #


def test_manifest_structure_and_checksum():
    pairs = _pairs()
    manifest = build_split_manifest(pairs, seed=0, calibration_fraction=0.6)
    assert manifest["algorithm"] == PAIR_SPLIT_ALGORITHM
    assert manifest["version"] == PAIR_SPLIT_VERSION
    assert "eligibility_hash" in manifest
    assert set(manifest["roles"]) == {
        "combo_calibration",
        "sealed_double_unseen",
        "sealed_single_unseen",
    }
    # role membership serialized as lists of [a, b]
    for members in manifest["roles"].values():
        for pair in members:
            assert len(pair) == 2
    assert "checksum" in manifest
    assert manifest["seed"] == 0
    assert manifest["calibration_fraction"] == 0.6


def test_manifest_checksum_excludes_self():
    """Checksum is over the payload; recomputing it must reproduce the stored value."""
    from alive.provenance import sha256_json

    manifest = build_split_manifest(_pairs(), seed=0, calibration_fraction=0.6)
    stored = manifest["checksum"]
    payload = {k: v for k, v in manifest.items() if k != "checksum"}
    assert sha256_json(payload) == stored


def test_eligibility_hash_is_canonicalization_invariant():
    """Reversed-order input pairs hash to the same eligibility universe."""
    m1 = build_split_manifest([("A", "B"), ("C", "D")], seed=0, calibration_fraction=0.5)
    m2 = build_split_manifest([("B", "A"), ("D", "C")], seed=0, calibration_fraction=0.5)
    assert m1["eligibility_hash"] == m2["eligibility_hash"]


def test_write_split_manifest_roundtrip(tmp_path):
    out = tmp_path / "split_manifest.json"
    manifest = build_split_manifest(_pairs(), seed=0, calibration_fraction=0.6)
    write_split_manifest(out, _pairs(), seed=0, calibration_fraction=0.6)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded == manifest


def test_write_split_manifest_refuses_overwrite(tmp_path):
    out = tmp_path / "split_manifest.json"
    write_split_manifest(out, _pairs(), seed=0, calibration_fraction=0.6)
    with pytest.raises(FileExistsError):
        write_split_manifest(out, _pairs(), seed=0, calibration_fraction=0.6)
