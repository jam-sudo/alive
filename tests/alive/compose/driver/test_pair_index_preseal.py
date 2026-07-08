"""Pre-seal validation tests for the pair-index manifest v1 schema.

Builds real dicts for both the pair-index manifest and its
``approved_sealed_input_attestation`` (spec §2.3 / §2.2's attestation
paragraph), self-checksums them for real via ``sha256_json``, and exercises the
real validator directly — no mocks, and the sealed source is never opened
(pre-seal capability restriction; there is no source file on disk anywhere in
this test module).
"""

from __future__ import annotations

import pytest

from alive.compose.driver.pair_index import (
    ATTESTATION_SCHEMA,
    PAIR_INDEX_MANIFEST_SCHEMA,
    validate_pair_index_manifest_preseal,
)
from alive.compose.driver.run_spec import RunSpecError
from alive.provenance import sha256_json

_HEX_SOURCE = "a" * 64
_HEX_ROW_IDENTITY = "b" * 64
_HEX_ROW_ID_1 = "c" * 64
_HEX_ROW_ID_2 = "d" * 64
_HEX_PAIR_INDEX_FILE = "e" * 64

#: Sentinel meaning "delete this key" when passed as an override value.
_MISSING = object()


def _pair_entry(gene_a: str, gene_b: str, role: str, rows: list[int], row_id_sha: str) -> dict:
    return {
        "gene_a": gene_a,
        "gene_b": gene_b,
        "role": role,
        "row_indices": rows,
        "row_id_sha256": row_id_sha,
    }


def _apply(payload: dict, overrides: dict) -> dict:
    self_checksum_override = overrides.pop("self_checksum", _MISSING)
    for key, value in overrides.items():
        if value is _MISSING:
            payload.pop(key, None)
        else:
            payload[key] = value
    if self_checksum_override is _MISSING:
        payload["self_checksum"] = sha256_json(payload)
    else:
        payload["self_checksum"] = self_checksum_override
    return payload


def _manifest(**overrides: object) -> dict:
    """A canonical, self-checksummed pair-index manifest v1 (spec §2.3)."""
    payload: dict = {
        "schema": PAIR_INDEX_MANIFEST_SCHEMA,
        "source_file_sha256": _HEX_SOURCE,
        "obs_row_identity_sha256": _HEX_ROW_IDENTITY,
        "perturbation_column": "perturbation",
        "control_token": "control",
        "combo_sep": "_",
        "pairs": [
            _pair_entry("GENEA", "GENEB", "combo_calibration", [0, 1, 2], _HEX_ROW_ID_1),
            _pair_entry("GENEC", "GENED", "sealed_double_unseen", [3, 4], _HEX_ROW_ID_2),
        ],
    }
    return _apply(payload, dict(overrides))


def _attestation(**overrides: object) -> dict:
    """A canonical, self-checksummed ``approved_sealed_input_attestation`` (spec §2.2)."""
    payload: dict = {
        "schema": ATTESTATION_SCHEMA,
        "canonical_source_path": "/approved/root/sealed/source.h5ad",
        "expected_source_file_sha256": _HEX_SOURCE,
        "snapshot_id": "snap-1",
        "source_row_identity_sha256": _HEX_ROW_IDENTITY,
        "pair_index_file_sha256": _HEX_PAIR_INDEX_FILE,
    }
    return _apply(payload, dict(overrides))


# ---------------------------------------------------------------------------
# (a) happy path
# ---------------------------------------------------------------------------


def test_happy_manifest_binds_to_attestation() -> None:
    validate_pair_index_manifest_preseal(_manifest(), attestation=_attestation())  # no raise


# ---------------------------------------------------------------------------
# (b) self-checksum
# ---------------------------------------------------------------------------


def test_tampered_self_checksum_raises() -> None:
    manifest = _manifest(self_checksum="0" * 64)
    with pytest.raises(RunSpecError, match="self_checksum"):
        validate_pair_index_manifest_preseal(manifest, attestation=_attestation())


# ---------------------------------------------------------------------------
# (c) attestation binding
# ---------------------------------------------------------------------------


def test_manifest_source_sha_mismatch_attestation_raises() -> None:
    attestation = _attestation(expected_source_file_sha256="9" * 64)
    with pytest.raises(RunSpecError, match="source_file_sha256"):
        validate_pair_index_manifest_preseal(_manifest(), attestation=attestation)


def test_manifest_row_identity_sha_mismatch_attestation_raises() -> None:
    attestation = _attestation(source_row_identity_sha256="8" * 64)
    with pytest.raises(RunSpecError, match="obs_row_identity_sha256"):
        validate_pair_index_manifest_preseal(_manifest(), attestation=attestation)


def test_attestation_missing_field_raises() -> None:
    attestation = _attestation(expected_source_file_sha256=_MISSING)
    with pytest.raises(RunSpecError, match="expected_source_file_sha256"):
        validate_pair_index_manifest_preseal(_manifest(), attestation=attestation)


def test_attestation_tampered_self_checksum_raises() -> None:
    attestation = _attestation(self_checksum="0" * 64)
    with pytest.raises(RunSpecError, match="self_checksum"):
        validate_pair_index_manifest_preseal(_manifest(), attestation=attestation)


# ---------------------------------------------------------------------------
# (d) v1 schema shape — missing / unknown keys
# ---------------------------------------------------------------------------


def test_missing_perturbation_column_raises() -> None:
    manifest = _manifest(perturbation_column=_MISSING)
    with pytest.raises(RunSpecError, match="perturbation_column"):
        validate_pair_index_manifest_preseal(manifest, attestation=_attestation())


def test_missing_combo_sep_raises() -> None:
    manifest = _manifest(combo_sep=_MISSING)
    with pytest.raises(RunSpecError, match="combo_sep"):
        validate_pair_index_manifest_preseal(manifest, attestation=_attestation())


def test_missing_control_token_raises() -> None:
    manifest = _manifest(control_token=_MISSING)
    with pytest.raises(RunSpecError, match="control_token"):
        validate_pair_index_manifest_preseal(manifest, attestation=_attestation())


def test_unknown_top_level_key_raises() -> None:
    manifest = _manifest(unexpected_field="surprise")
    with pytest.raises(RunSpecError, match="unexpected"):
        validate_pair_index_manifest_preseal(manifest, attestation=_attestation())


def test_wrong_schema_constant_raises() -> None:
    manifest = _manifest(schema="compose_pair_index_manifest_v0")
    with pytest.raises(RunSpecError, match="schema"):
        validate_pair_index_manifest_preseal(manifest, attestation=_attestation())


# ---------------------------------------------------------------------------
# (e) per-pair shape — role / row indices / canonical order
# ---------------------------------------------------------------------------


def test_invalid_role_raises() -> None:
    manifest = _manifest(
        pairs=[_pair_entry("GENEA", "GENEB", "not_a_real_role", [0, 1], _HEX_ROW_ID_1)]
    )
    with pytest.raises(RunSpecError, match="role"):
        validate_pair_index_manifest_preseal(manifest, attestation=_attestation())


def test_non_canonical_pair_order_raises() -> None:
    manifest = _manifest(
        pairs=[_pair_entry("GENEB", "GENEA", "combo_calibration", [0, 1], _HEX_ROW_ID_1)]
    )
    with pytest.raises(RunSpecError, match="canonical"):
        validate_pair_index_manifest_preseal(manifest, attestation=_attestation())


def test_duplicate_row_index_within_pair_raises() -> None:
    manifest = _manifest(
        pairs=[_pair_entry("GENEA", "GENEB", "combo_calibration", [0, 0, 1], _HEX_ROW_ID_1)]
    )
    with pytest.raises(RunSpecError, match="duplicate"):
        validate_pair_index_manifest_preseal(manifest, attestation=_attestation())


def test_duplicate_canonical_pair_raises() -> None:
    manifest = _manifest(
        pairs=[
            _pair_entry("GENEA", "GENEB", "combo_calibration", [0, 1], _HEX_ROW_ID_1),
            _pair_entry("GENEA", "GENEB", "sealed_double_unseen", [2, 3], _HEX_ROW_ID_2),
        ]
    )
    with pytest.raises(RunSpecError, match="duplicate"):
        validate_pair_index_manifest_preseal(manifest, attestation=_attestation())


def test_empty_pairs_list_raises() -> None:
    manifest = _manifest(pairs=[])
    with pytest.raises(RunSpecError, match="pairs"):
        validate_pair_index_manifest_preseal(manifest, attestation=_attestation())
