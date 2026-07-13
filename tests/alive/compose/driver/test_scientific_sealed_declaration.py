"""Sealed-input ↔ attestation equality at pre-seal (spec §2.2) — no source access."""

from __future__ import annotations

import builtins
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from alive.compose.driver.pair_index import validate_scientific_sealed_declaration
from alive.compose.driver.phase2b_cmd import (
    Phase2bSubcommandError,
    _assert_audit_destination_free,
    _resolve_seal_audit_destination,
)
from alive.compose.driver.run_spec import RunSpecError, load_resolved_run_spec
from alive.compose.driver.seal_boundary import scientific_protocol_seal_audit_path
from alive.provenance import sha256_json
from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture


def _parts(bundle):
    spec = load_resolved_run_spec(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        mode_expected="scientific",
    )
    attestation = json.loads(
        Path(spec.pre_seal["approved_sealed_input_attestation"].path).read_bytes()
    )
    pim = json.loads(Path(spec.pre_seal["pair_index_manifest"].path).read_bytes())
    return spec, attestation, pim


def test_valid_declaration_passes(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, attestation, pim = _parts(bundle)
    validate_scientific_sealed_declaration(
        sealed_input=spec.scientific["sealed_input"],
        attestation=attestation,
        pair_index_manifest=pim,
        pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
        protocol=spec.protocol,
        approved_artifacts_root=spec.approved_artifacts_root,
    )  # no raise


@pytest.mark.parametrize(
    "key,bad",
    [
        ("source_path", "/tmp/other.h5ad"),
        ("expected_file_sha256", "0" * 64),
        ("snapshot_id", "wrong_snapshot"),
    ],
)
def test_sealed_input_field_mismatch_rejects(tmp_path, key, bad):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, attestation, pim = _parts(bundle)
    sealed = dict(spec.scientific["sealed_input"])
    sealed[key] = bad
    with pytest.raises(RunSpecError):
        validate_scientific_sealed_declaration(
            sealed_input=sealed,
            attestation=attestation,
            pair_index_manifest=pim,
            pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
            protocol=spec.protocol,
            approved_artifacts_root=spec.approved_artifacts_root,
        )


def test_audit_path_mismatch_rejects(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, attestation, pim = _parts(bundle)
    sealed = dict(spec.scientific["sealed_input"])
    sealed["audit_path"] = str(Path(spec.run_dir) / "not_audit.jsonl")
    with pytest.raises(RunSpecError, match="audit"):
        validate_scientific_sealed_declaration(
            sealed_input=sealed,
            attestation=attestation,
            pair_index_manifest=pim,
            pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
            protocol=spec.protocol,
            approved_artifacts_root=spec.approved_artifacts_root,
        )


def test_pair_index_row_identity_mismatch_rejects(tmp_path):
    """Row-identity mismatch (manifest.obs_row_identity_sha256 vs attestation's

    declared value) must be rejected by the equality check in
    ``validate_pair_index_manifest_preseal`` (pair_index.py:336-341) — NOT merely
    by the attestation's ``self_checksum`` shape-guard. The attestation's
    ``self_checksum`` is recomputed over the tampered body so that guard passes
    and control actually reaches the row-identity equality check; otherwise the
    raise observed here would be the (unrelated) self-checksum mismatch and the
    test would pass even if the row-identity check were deleted.
    """
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, attestation, pim = _parts(bundle)
    bad_attestation = dict(attestation)
    bad_attestation["source_row_identity_sha256"] = "1" * 64
    body = {k: v for k, v in bad_attestation.items() if k != "self_checksum"}
    bad_attestation["self_checksum"] = sha256_json(body)
    with pytest.raises(RunSpecError, match="obs_row_identity_sha256"):
        validate_scientific_sealed_declaration(
            sealed_input=spec.scientific["sealed_input"],
            attestation=bad_attestation,
            pair_index_manifest=pim,
            pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
            protocol=spec.protocol,
            approved_artifacts_root=spec.approved_artifacts_root,
        )


def test_nonexistent_source_path_still_validates_lexically(tmp_path):
    """A source_path pointing at a file that does not exist on disk must still validate.

    All the bindings this validator checks are STRING/digest equalities declared in
    already-parsed mappings — never a stat/open of the described source. Pointing
    ``source_path`` at a nonexistent path and re-syncing the attestation's declared
    string (+ its ``self_checksum``, which is itself just a hash of declared JSON, not
    a file read) to match proves the source is never touched: if any stat/open of the
    source occurred, this would raise ``OSError``/``FileNotFoundError`` instead of
    returning normally.
    """
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, attestation, pim = _parts(bundle)
    missing_path = str(tmp_path / "does_not_exist" / "phantom_source.h5ad")
    assert not os.path.exists(missing_path)

    sealed = dict(spec.scientific["sealed_input"])
    sealed["source_path"] = missing_path

    bad_attestation = dict(attestation)
    bad_attestation["canonical_source_path"] = missing_path
    body = {k: v for k, v in bad_attestation.items() if k != "self_checksum"}
    bad_attestation["self_checksum"] = sha256_json(body)

    validate_scientific_sealed_declaration(
        sealed_input=sealed,
        attestation=bad_attestation,
        pair_index_manifest=pim,
        pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
        protocol=spec.protocol,
        approved_artifacts_root=spec.approved_artifacts_root,
    )  # no raise — proves no stat/open of source_path occurred


def test_source_path_never_opened_or_statted(tmp_path, monkeypatch):
    """Monkeypatch guard: fail loudly if the validator ever opens/stats the sealed source."""
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, attestation, pim = _parts(bundle)
    source_path = spec.scientific["sealed_input"]["source_path"]

    real_open = builtins.open
    real_stat = os.stat

    def guarded_open(file, *args, **kwargs):
        if isinstance(file, (str, os.PathLike)) and os.fspath(file) == source_path:
            raise AssertionError(f"validator opened the sealed source: {file!r}")
        return real_open(file, *args, **kwargs)

    def guarded_stat(path, *args, **kwargs):
        if isinstance(path, (str, os.PathLike)) and os.fspath(path) == source_path:
            raise AssertionError(f"validator statted the sealed source: {path!r}")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(os, "stat", guarded_stat)

    validate_scientific_sealed_declaration(
        sealed_input=spec.scientific["sealed_input"],
        attestation=attestation,
        pair_index_manifest=pim,
        pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
        protocol=spec.protocol,
        approved_artifacts_root=spec.approved_artifacts_root,
    )  # no raise, and the guards above must never trip


def test_protocol_audit_is_independent_of_run_directory(tmp_path):
    root = tmp_path / "approved"
    first = scientific_protocol_seal_audit_path(root, "COMPOSE-K562-v1")
    second = scientific_protocol_seal_audit_path(root, "COMPOSE-K562-v1")
    assert first == second
    assert first.parent == root.resolve()
    assert "COMPOSE-K562-v1" not in first.name


def test_second_run_directory_cannot_mint_a_fresh_scientific_seal(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, _, _ = _parts(bundle)
    second_run_dir = bundle.approved_artifacts_root / "second-run"
    second_run_dir.mkdir()
    second_spec = replace(spec, run_dir=str(second_run_dir))

    first_audit, first_parent = _resolve_seal_audit_destination(
        spec,
        run_dir=Path(spec.run_dir),
    )
    second_audit, second_parent = _resolve_seal_audit_destination(
        second_spec,
        run_dir=second_run_dir,
    )
    assert first_audit == second_audit
    assert first_parent == second_parent

    first_audit.write_text('{"run_id":"already-consumed"}\n', encoding="utf-8")
    with pytest.raises(Phase2bSubcommandError, match="already exists"):
        _assert_audit_destination_free(second_audit, expected_parent=second_parent)
