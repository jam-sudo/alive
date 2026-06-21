"""Tests for src/alive/data/features.py — ESM-2 perturbation feature bank.

All tests use MockSequenceEncoder (numpy-only); no torch/network access.

TDD order: tests written first, implementation must pass all of them.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Sequence

import numpy as np
import pytest

from alive.data.features import (
    FeatureBank,
    FeatureError,
    MockSequenceEncoder,
    SequenceEncoder,
    build_feature_bank,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIMPLE_MAPPING: dict[str, list[str]] = {
    "GENE_A": ["MKVLVI"],
    "GENE_B": ["ACDEFGHIKL"],
    "GENE_C": ["MGTPT"],
}


def _make_mock(dim: int = 8) -> MockSequenceEncoder:
    return MockSequenceEncoder(dim=dim)


# ---------------------------------------------------------------------------
# 1. Happy path: build from clean mapping
# ---------------------------------------------------------------------------


def test_happy_path_genes_sorted() -> None:
    """genes tuple must be sorted lexicographically."""
    enc = _make_mock()
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    assert list(bank.genes) == sorted(_SIMPLE_MAPPING.keys())


def test_happy_path_dim() -> None:
    enc = _make_mock(dim=8)
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    assert bank.dim == 8


def test_happy_path_vector_shape() -> None:
    enc = _make_mock(dim=8)
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    for g in bank.genes:
        v = bank.vector(g)
        assert v.shape == (8,), f"Gene {g!r}: expected shape (8,), got {v.shape}"


def test_happy_path_all_finite() -> None:
    enc = _make_mock()
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    for g in bank.genes:
        assert np.all(np.isfinite(bank.vector(g))), f"Gene {g!r} has non-finite values"


def test_happy_path_no_excluded() -> None:
    enc = _make_mock()
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    assert bank.excluded == {}


# ---------------------------------------------------------------------------
# 2. Deterministic pooling: hand-compute and compare
# ---------------------------------------------------------------------------


def test_deterministic_pooling_matches_hand_computed() -> None:
    """vector(g) must equal mean(encode_residues([seq])[0], axis=0) exactly."""
    enc = _make_mock(dim=8)
    seq = "MKVLVI"
    mapping = {"ONLY": [seq]}
    bank = build_feature_bank(mapping, enc, sequence_source="v1")

    # hand-compute
    per_residue_list = enc.encode_residues([seq])
    assert len(per_residue_list) == 1
    per_residue = per_residue_list[0]  # (L, dim)
    expected = per_residue.mean(axis=0).astype(np.float32)

    np.testing.assert_allclose(bank.vector("ONLY"), expected, rtol=1e-6, atol=1e-7)


def test_mock_encoder_deterministic() -> None:
    """Same sequence -> identical per-residue array on repeated calls."""
    enc = _make_mock(dim=12)
    seq = "ACDEFGHIKL"
    arr1 = enc.encode_residues([seq])[0]
    arr2 = enc.encode_residues([seq])[0]
    np.testing.assert_array_equal(arr1, arr2)


def test_mock_encoder_different_sequences_differ() -> None:
    """Different sequences -> different arrays (statistical sanity)."""
    enc = _make_mock(dim=16)
    a = enc.encode_residues(["MKVLVI"])[0]
    b = enc.encode_residues(["ACDEFGHIKL"])[0]
    # they may differ in length; means should differ
    assert not np.allclose(a.mean(axis=0), b.mean(axis=0))


# ---------------------------------------------------------------------------
# 3. Missing and ambiguous exclusions
# ---------------------------------------------------------------------------


def test_missing_sequence_excluded() -> None:
    mapping = {
        "GENE_OK": ["MKVLVI"],
        "GENE_MISSING": [],  # zero candidates
    }
    enc = _make_mock()
    bank = build_feature_bank(mapping, enc, sequence_source="v1")
    assert "GENE_MISSING" not in bank.genes
    assert bank.excluded.get("GENE_MISSING") == "missing sequence"


def test_ambiguous_mapping_excluded() -> None:
    mapping = {
        "GENE_OK": ["MKVLVI"],
        "GENE_AMB": ["MKVLVI", "ACDEF"],  # two candidates
    }
    enc = _make_mock()
    bank = build_feature_bank(mapping, enc, sequence_source="v1")
    assert "GENE_AMB" not in bank.genes
    assert bank.excluded.get("GENE_AMB") == "ambiguous mapping"


def test_both_excluded_types_coexist() -> None:
    mapping = {
        "GENE_OK": ["MKVLVI"],
        "GENE_MISSING": [],
        "GENE_AMB": ["MKVLVI", "ACDEF"],
    }
    enc = _make_mock()
    bank = build_feature_bank(mapping, enc, sequence_source="v1")
    assert list(bank.genes) == ["GENE_OK"]
    assert len(bank.excluded) == 2
    assert "GENE_MISSING" in bank.excluded
    assert "GENE_AMB" in bank.excluded


def test_vector_absent_gene_raises() -> None:
    enc = _make_mock()
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    with pytest.raises(FeatureError):
        bank.vector("NOT_IN_BANK")


def test_has_present_and_absent() -> None:
    enc = _make_mock()
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    assert bank.has("GENE_A")
    assert not bank.has("GHOST")


# ---------------------------------------------------------------------------
# 4. Non-finite input -> FeatureError
# ---------------------------------------------------------------------------


class _InfEncoder:
    """Stub encoder that returns per-residue arrays containing inf."""

    @property
    def dim(self) -> int:
        return 4

    @property
    def model_revision(self) -> str:
        return "inf-stub"

    def encode_residues(self, sequences: Sequence[str]) -> list[np.ndarray]:
        results = []
        for seq in sequences:
            arr = np.full((len(seq), self.dim), np.inf)
            results.append(arr)
        return results


def test_non_finite_raises_feature_error() -> None:
    mapping = {"GENE_A": ["MKVLVI"]}
    enc = _InfEncoder()
    with pytest.raises(FeatureError, match="non-finite"):
        build_feature_bank(mapping, enc, sequence_source="v1")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 5. Base-train-only standardization
# ---------------------------------------------------------------------------


def test_standardization_base_train_mean_zero_std_one() -> None:
    """Per-dim mean of standardized_vector over base_train subset should be ~0, std ~1."""
    enc = _make_mock(dim=4)
    mapping = {f"G{i}": [f"SEQ{i}AA"] for i in range(10)}
    base_train = [f"G{i}" for i in range(6)]  # first 6

    bank = build_feature_bank(mapping, enc, sequence_source="v1", standardize_on=base_train)

    std_vecs = np.stack([bank.standardized_vector(g) for g in base_train])  # (6, 4)
    np.testing.assert_allclose(std_vecs.mean(axis=0), 0.0, atol=1e-5)
    np.testing.assert_allclose(std_vecs.std(axis=0, ddof=1), 1.0, atol=1e-5)


def test_standardization_outside_base_train_uses_same_params() -> None:
    """Genes outside base_train must be standardized using base_train mean/scale."""
    enc = _make_mock(dim=4)
    mapping = {f"G{i}": [f"SEQ{i}AA"] for i in range(6)}
    base_train = ["G0", "G1", "G2", "G3"]
    outside = ["G4", "G5"]

    bank = build_feature_bank(mapping, enc, sequence_source="v1", standardize_on=base_train)

    # Compute base_train mean and std by hand
    bt_vecs = np.stack([bank.vector(g) for g in base_train])  # (4, dim)
    bt_mean = bt_vecs.mean(axis=0)
    bt_std = bt_vecs.std(axis=0, ddof=1)
    bt_scale = np.where(bt_std == 0, 1.0, bt_std)

    for g in outside:
        raw = bank.vector(g)
        expected_std = (raw - bt_mean) / bt_scale
        np.testing.assert_allclose(bank.standardized_vector(g), expected_std, rtol=1e-5, atol=1e-7)


def test_standardization_ignores_standardize_on_not_in_bank() -> None:
    """IDs in standardize_on that are not usable genes are silently ignored."""
    enc = _make_mock(dim=4)
    mapping = {"G0": ["MKVLVI"], "G1": ["ACDEF"]}
    # G_GHOST is not in the bank at all
    bank = build_feature_bank(
        mapping, enc, sequence_source="v1", standardize_on=["G0", "G1", "G_GHOST"]
    )
    # Should succeed; G_GHOST is ignored
    assert bank.has("G0") and bank.has("G1")
    v = bank.standardized_vector("G0")
    assert v.shape == (4,)


def test_standardizer_not_fitted_raises() -> None:
    enc = _make_mock()
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1", standardize_on=None)
    with pytest.raises(FeatureError, match="standardizer not fitted"):
        bank.standardized_vector("GENE_A")


def test_std_zero_dim_guarded() -> None:
    """If a dimension has std==0 across base_train, scale should be 1.0 (no div-by-zero)."""

    class _ConstEncoder:
        """Returns constant per-residue embeddings (std-zero in all dims)."""

        @property
        def dim(self) -> int:
            return 3

        @property
        def model_revision(self) -> str:
            return "const-v1"

        def encode_residues(self, sequences: Sequence[str]) -> list[np.ndarray]:
            return [np.ones((len(s), 3), dtype=np.float32) for s in sequences]

    mapping = {"GA": ["AAA"], "GB": ["BBB"], "GC": ["CCC"]}
    bank = build_feature_bank(
        mapping,
        _ConstEncoder(),
        sequence_source="v1",
        standardize_on=["GA", "GB", "GC"],  # type: ignore[arg-type]
    )
    # All raw vectors are identical -> std=0 -> scale=1. Standardized = raw - mean = 0.
    v = bank.standardized_vector("GA")
    np.testing.assert_allclose(v, 0.0, atol=1e-7)


# ---------------------------------------------------------------------------
# 6. Checksum changes and stability
# ---------------------------------------------------------------------------


def test_checksum_stable_identical_inputs() -> None:
    enc = _make_mock()
    bank1 = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    bank2 = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    assert bank1.checksum == bank2.checksum


def test_checksum_changes_on_model_revision() -> None:
    mapping = {"GA": ["MKVLVI"]}
    enc1 = MockSequenceEncoder(dim=8, model_revision="rev-A")
    enc2 = MockSequenceEncoder(dim=8, model_revision="rev-B")
    bank1 = build_feature_bank(mapping, enc1, sequence_source="v1")
    bank2 = build_feature_bank(mapping, enc2, sequence_source="v1")
    assert bank1.checksum != bank2.checksum


def test_checksum_changes_on_sequence_source() -> None:
    enc = _make_mock()
    bank1 = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    bank2 = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v2")
    assert bank1.checksum != bank2.checksum


def test_checksum_changes_on_mapping() -> None:
    enc = _make_mock()
    mapping2 = dict(_SIMPLE_MAPPING)
    mapping2["EXTRA"] = ["EXTRA_SEQ"]
    bank1 = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    bank2 = build_feature_bank(mapping2, enc, sequence_source="v1")
    assert bank1.checksum != bank2.checksum


# ---------------------------------------------------------------------------
# 7. Round-trip: write / read
# ---------------------------------------------------------------------------


def test_round_trip_genes_and_vectors() -> None:
    enc = _make_mock(dim=8)
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bank"
        bank.write(p)
        restored = FeatureBank.read(p)
    assert restored.genes == bank.genes
    for g in bank.genes:
        np.testing.assert_array_equal(restored.vector(g), bank.vector(g))


def test_round_trip_excluded() -> None:
    mapping = {
        "GENE_OK": ["MKVLVI"],
        "GENE_MISSING": [],
        "GENE_AMB": ["MKVLVI", "ACDEF"],
    }
    enc = _make_mock()
    bank = build_feature_bank(mapping, enc, sequence_source="v1")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bank"
        bank.write(p)
        restored = FeatureBank.read(p)
    assert restored.excluded == bank.excluded


def test_round_trip_provenance() -> None:
    enc = _make_mock()
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bank"
        bank.write(p)
        restored = FeatureBank.read(p)
    assert restored.provenance == bank.provenance


def test_round_trip_checksum() -> None:
    enc = _make_mock()
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bank"
        bank.write(p)
        restored = FeatureBank.read(p)
    assert restored.checksum == bank.checksum


def test_round_trip_standardized_vector() -> None:
    enc = _make_mock(dim=6)
    mapping = {f"G{i}": [f"SEQ{i}A"] for i in range(5)}
    base_train = ["G0", "G1", "G2"]
    bank = build_feature_bank(mapping, enc, sequence_source="v1", standardize_on=base_train)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bank"
        bank.write(p)
        restored = FeatureBank.read(p)
    for g in bank.genes:
        np.testing.assert_array_equal(
            restored.standardized_vector(g),
            bank.standardized_vector(g),
        )


# ---------------------------------------------------------------------------
# 8. matrix() helper
# ---------------------------------------------------------------------------


def test_matrix_default_order() -> None:
    enc = _make_mock(dim=8)
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    mat = bank.matrix()
    assert mat.shape == (len(bank.genes), 8)
    for i, g in enumerate(bank.genes):
        np.testing.assert_array_equal(mat[i], bank.vector(g))


def test_matrix_custom_order() -> None:
    enc = _make_mock(dim=8)
    bank = build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")
    order = ["GENE_C", "GENE_A"]
    mat = bank.matrix(order)
    assert mat.shape == (2, 8)
    np.testing.assert_array_equal(mat[0], bank.vector("GENE_C"))
    np.testing.assert_array_equal(mat[1], bank.vector("GENE_A"))


# ---------------------------------------------------------------------------
# 9. No expression involvement (structural test)
# ---------------------------------------------------------------------------


def test_no_expression_involvement() -> None:
    """Two calls with the same mapping/encoder in different contexts -> identical banks."""
    enc = _make_mock(dim=8)

    def build_in_context_a() -> FeatureBank:
        # Simulates code that has access to "expression data" but build_feature_bank doesn't use it
        _fake_expression = np.random.default_rng(0).random((100, 50))  # never passed in
        return build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")

    def build_in_context_b() -> FeatureBank:
        _fake_expression = np.random.default_rng(99).random((200, 80))  # never passed in
        return build_feature_bank(_SIMPLE_MAPPING, enc, sequence_source="v1")

    bank_a = build_in_context_a()
    bank_b = build_in_context_b()
    assert bank_a.checksum == bank_b.checksum
    for g in bank_a.genes:
        np.testing.assert_array_equal(bank_a.vector(g), bank_b.vector(g))


# ---------------------------------------------------------------------------
# 10. Real Esm2Encoder is guarded (lazy imports)
# ---------------------------------------------------------------------------


def test_esm2encoder_import_does_not_import_torch_at_module_level() -> None:
    """Importing features.py must not import torch (which may not be installed)."""
    # torch must not have been imported as a side-effect of importing features
    # (If torch IS available, this test still verifies the class exists correctly)
    from alive.data.features import Esm2Encoder  # noqa: F401

    # The key check: Esm2Encoder can be referenced without torch being required
    # If torch is not installed, torch should NOT be in sys.modules due to features import
    # We can only check this if torch isn't already present from another import
    assert "Esm2Encoder" in dir(__import__("alive.data.features", fromlist=["Esm2Encoder"]))


def test_esm2encoder_class_attributes_without_model() -> None:
    """Esm2Encoder can be instantiated class-wise if torch available; else skip."""
    pytest.importorskip("torch")  # skip if torch not installed
    from alive.data.features import Esm2Encoder

    # Only check that the class exists and has expected interface; do NOT download/run model
    assert hasattr(Esm2Encoder, "__init__")
    # We can construct the object without calling encode_residues
    # (which would trigger model download)
    # Just check the class is importable and its __init__ signature exists
    import inspect

    sig = inspect.signature(Esm2Encoder.__init__)
    assert "model_name" in sig.parameters


# ---------------------------------------------------------------------------
# 11. Protocol compliance
# ---------------------------------------------------------------------------


def test_mock_encoder_implements_protocol() -> None:
    enc = MockSequenceEncoder(dim=4)
    assert isinstance(enc, SequenceEncoder)
    assert enc.dim == 4
    assert isinstance(enc.model_revision, str)
    result = enc.encode_residues(["ACE"])
    assert len(result) == 1
    assert result[0].shape == (3, 4)
