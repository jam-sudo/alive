"""Tests for alive.compose.provenance2 — COMPLETE Phase-2b provenance + run identity.

TDD order: tests written first; the implementation must pass all of them.

This module is Task 6 of 8 for COMPOSE-K562-v1 Phase 2b. It is the COMPLETE
composite provenance + run-identity assembly for the sealed evaluation. It

  * recomputes the composite COMPOSE ``run_id`` (one canonical definition);
  * records the COMPLETE provenance chain into a write-once :class:`RunLedger`;
  * ABORTS (raises :class:`ProvenanceError`) BEFORE seal access on any upstream
    absence / mismatch — the seal stays CLOSED; and
  * flags post-access inconsistencies as :class:`PostAccessStatus.INVALID`
    WITHOUT raising — the seal is already consumed, so the terminal writer
    (Task 7) records a terminal artifact rather than crashing.

The CRITICAL distinction under test is the two-path split:

  * a mismatch / absence detectable BEFORE access RAISES (seal closed);
  * a mismatch detectable only AFTER access returns ``INVALID`` (seal consumed).

SYNTHETIC-ONLY: pure synthetic / tiny-fixture values only; NO real Norman,
NO seal open, NO sealed-outcome read.
"""

from __future__ import annotations

import inspect

import pytest

from alive.compose.provenance2 import (
    PRE_ACCESS_LEDGER_FILENAME,
    PRE_ACCESS_PROVENANCE_ARTIFACT,
    Phase2bProvenance,
    PostAccessStatus,
    ProvenanceError,
    check_post_access_consistency,
    persist_pre_access_ledger,
    recompute_run_id,
    record_phase2b_provenance,
    record_pre_access_provenance,
    verify_upstream_before_access,
)
from alive.provenance import (
    DuplicateArtifactError,
    EnvironmentInfo,
    LedgerError,
    RunLedger,
    sha256_json,
)

# ---------------------------------------------------------------------------
# Synthetic fixtures — tiny, deterministic, no real data.
# ---------------------------------------------------------------------------

_CONFIG_DIGEST = "config-digest-aaaa"
_DATA_CARD_DIGEST = "data-card-digest-bbbb"
_RAW_DIGEST = "raw-or-source-digest-cccc"
_SEQ_DIGEST = "sequence-mapping-digest-dddd"


def _environment() -> EnvironmentInfo:
    """A deterministic environment snapshot (no wall-clock)."""
    return EnvironmentInfo(
        python_version="3.12.3",
        platform="macOS-15.0-arm64-arm-64bit",
        git_commit="a" * 40,
        lockfile_sha256="lockfile-sha-eeee",
        registered_seeds=(11, 23, 37),
    )


def _provenance(**overrides) -> Phase2bProvenance:
    """A fully-populated Phase2bProvenance with synthetic hashes; overridable."""
    base = dict(
        protocol="COMPOSE-K562-v1",
        config_digest=_CONFIG_DIGEST,
        pair_manifest_sha256="pair-manifest-sha",
        exclusion_manifest_sha256="exclusion-manifest-sha",
        data_card_sha256=_DATA_CARD_DIGEST,
        raw_or_source_sha256=_RAW_DIGEST,
        processed_sha256="processed-sha",
        sequence_mapping_sha256=_SEQ_DIGEST,
        feature_bank_sha256="feature-bank-sha",
        response_space_sha256="response-space-sha",
        factor_bank_sha256="factor-bank-sha",
        model_lock_sha256="model-lock-sha",
        frozen_prediction_bundle_sha256="frozen-bundle-sha",
        git_commit="a" * 40,
        git_clean=True,
        dependency_lock_sha256="lockfile-sha-eeee",
        gears_revision="gears-rev-1.2.3",
        cpa_revision="cpa-rev-4.5.6",
        python_version="3.12.3",
        platform="macOS-15.0-arm64-arm-64bit",
        device="cpu",
        precision="float32",
        registered_seeds=(11, 23, 37),
        split_seed=11,
        seal_audit_reference="audit/compose_seal.jsonl",
        regime_result_double_sha256="regime-double-sha",
        regime_result_single_sha256="regime-single-sha",
    )
    base.update(overrides)
    return Phase2bProvenance(**base)


def _expected_run_id() -> str:
    return recompute_run_id(
        config_digest=_CONFIG_DIGEST,
        data_card_digest=_DATA_CARD_DIGEST,
        raw_or_source_sha256=_RAW_DIGEST,
        sequence_mapping_sha256=_SEQ_DIGEST,
    )


# All artifact names the COMPLETE record must carry.
_REQUIRED_ARTIFACT_NAMES = (
    "pair_manifest",
    "exclusion_manifest",
    "data_card",
    "raw_data",
    "processed_data",
    "sequence_mapping",
    "feature_bank",
    "response_space",
    "factor_bank",
    "model_lock",
    "frozen_prediction_bundle",
    "gears_revision",
    "cpa_revision",
    "device",
    "precision",
    "seal_audit",
    "regime_result_double",
    "regime_result_single",
    "phase2b_provenance",
)


# ---------------------------------------------------------------------------
# run_id recompute
# ---------------------------------------------------------------------------


def test_recompute_run_id_is_stable_for_known_input():
    rid = recompute_run_id(
        config_digest=_CONFIG_DIGEST,
        data_card_digest=_DATA_CARD_DIGEST,
        raw_or_source_sha256=_RAW_DIGEST,
        sequence_mapping_sha256=_SEQ_DIGEST,
    )
    # Stable: recomputing with the same inputs yields the identical id.
    again = recompute_run_id(
        config_digest=_CONFIG_DIGEST,
        data_card_digest=_DATA_CARD_DIGEST,
        raw_or_source_sha256=_RAW_DIGEST,
        sequence_mapping_sha256=_SEQ_DIGEST,
    )
    assert rid == again
    assert isinstance(rid, str)
    assert len(rid) == 16
    assert all(c in "0123456789abcdef" for c in rid)


def test_recompute_run_id_changes_when_config_changes():
    base = _expected_run_id()
    changed = recompute_run_id(
        config_digest="DIFFERENT-config",
        data_card_digest=_DATA_CARD_DIGEST,
        raw_or_source_sha256=_RAW_DIGEST,
        sequence_mapping_sha256=_SEQ_DIGEST,
    )
    assert changed != base


def test_recompute_run_id_changes_when_data_card_changes():
    base = _expected_run_id()
    changed = recompute_run_id(
        config_digest=_CONFIG_DIGEST,
        data_card_digest="DIFFERENT-data-card",
        raw_or_source_sha256=_RAW_DIGEST,
        sequence_mapping_sha256=_SEQ_DIGEST,
    )
    assert changed != base


def test_recompute_run_id_changes_when_raw_changes():
    base = _expected_run_id()
    changed = recompute_run_id(
        config_digest=_CONFIG_DIGEST,
        data_card_digest=_DATA_CARD_DIGEST,
        raw_or_source_sha256="DIFFERENT-raw",
        sequence_mapping_sha256=_SEQ_DIGEST,
    )
    assert changed != base


def test_recompute_run_id_changes_when_sequence_mapping_changes():
    base = _expected_run_id()
    changed = recompute_run_id(
        config_digest=_CONFIG_DIGEST,
        data_card_digest=_DATA_CARD_DIGEST,
        raw_or_source_sha256=_RAW_DIGEST,
        sequence_mapping_sha256="DIFFERENT-seq",
    )
    assert changed != base


def test_recompute_run_id_matches_compose_run_id_definition():
    """recompute_run_id is the SAME definition as compute_compose_run_id."""
    from alive.compose.datacard import compute_compose_run_id

    direct = compute_compose_run_id(
        config_digest=_CONFIG_DIGEST,
        data_card_digest=_DATA_CARD_DIGEST,
        raw_or_source_digest=_RAW_DIGEST,
        sequence_mapping_digest=_SEQ_DIGEST,
    )
    assert (
        recompute_run_id(
            config_digest=_CONFIG_DIGEST,
            data_card_digest=_DATA_CARD_DIGEST,
            raw_or_source_sha256=_RAW_DIGEST,
            sequence_mapping_sha256=_SEQ_DIGEST,
        )
        == direct
    )


# ---------------------------------------------------------------------------
# Phase2bProvenance record self-checksum
# ---------------------------------------------------------------------------


def test_provenance_self_checksum_is_deterministic():
    p1 = _provenance()
    p2 = _provenance()
    assert p1.self_checksum == p2.self_checksum
    assert isinstance(p1.self_checksum, str)
    assert len(p1.self_checksum) == 64  # full SHA-256 hex


def test_provenance_self_checksum_changes_with_content():
    base = _provenance().self_checksum
    changed = _provenance(model_lock_sha256="DIFFERENT-model-lock").self_checksum
    assert changed != base


def test_provenance_self_checksum_excludes_itself():
    """The self-checksum is computed over the content, not over itself."""
    p = _provenance()
    # Recompute from to_dict (which must NOT include self_checksum) and compare.
    assert "self_checksum" not in p.to_dict()
    assert p.self_checksum == sha256_json(p.to_dict())


def test_embedded_provenance_v2_excludes_terminal_report_sha():
    prov = _provenance()  # existing fixture (no terminal_report_sha256 arg)
    d = prov.to_dict()
    assert d["schema"] == "compose_phase2b_provenance_v2"
    assert "terminal_report_sha256" not in d
    # regime-result checksums remain (they precede the terminal, no circularity)
    assert "regime_result_double_sha256" in d and "regime_result_single_sha256" in d
    # self_checksum is a hash of the content only, stable across identical inputs
    assert prov.self_checksum == _provenance().self_checksum


# ---------------------------------------------------------------------------
# record_phase2b_provenance — COMPLETE write-once ledger
# ---------------------------------------------------------------------------


def test_record_contains_every_required_artifact_name():
    prov = _provenance()
    run_id = _expected_run_id()
    ledger = record_phase2b_provenance(
        prov,
        run_id=run_id,
        config_sha256=_CONFIG_DIGEST,
        environment=_environment(),
    )
    names = {art["name"] for art in ledger.to_dict()["artifacts"]}
    for required in _REQUIRED_ARTIFACT_NAMES:
        assert required in names, f"missing required artifact {required!r}"


def test_record_to_dict_is_deterministic():
    prov = _provenance()
    run_id = _expected_run_id()
    a = record_phase2b_provenance(
        prov, run_id=run_id, config_sha256=_CONFIG_DIGEST, environment=_environment()
    )
    b = record_phase2b_provenance(
        prov, run_id=run_id, config_sha256=_CONFIG_DIGEST, environment=_environment()
    )
    assert a.to_dict() == b.to_dict()


def test_record_captures_git_sha_clean_flag_and_seeds():
    prov = _provenance()
    run_id = _expected_run_id()
    ledger = record_phase2b_provenance(
        prov, run_id=run_id, config_sha256=_CONFIG_DIGEST, environment=_environment()
    )
    d = ledger.to_dict()
    # git SHA recorded via the environment block.
    assert d["environment"]["git_commit"] == "a" * 40
    # registered seeds recorded.
    assert d["environment"]["registered_seeds"] == [11, 23, 37]
    # clean-state flag is captured as an artifact evidence (git_clean=True).
    names = {art["name"] for art in d["artifacts"]}
    assert "git_clean" in names
    assert ledger.artifact_sha("git_clean") == sha256_json(True)


def test_record_string_evidence_is_hashed_consistently():
    """Revisions / device / precision are recorded via sha256_json of the value."""
    prov = _provenance()
    run_id = _expected_run_id()
    ledger = record_phase2b_provenance(
        prov, run_id=run_id, config_sha256=_CONFIG_DIGEST, environment=_environment()
    )
    assert ledger.artifact_sha("gears_revision") == sha256_json("gears-rev-1.2.3")
    assert ledger.artifact_sha("cpa_revision") == sha256_json("cpa-rev-4.5.6")
    assert ledger.artifact_sha("device") == sha256_json("cpu")
    assert ledger.artifact_sha("precision") == sha256_json("float32")
    assert ledger.artifact_sha("seal_audit") == sha256_json("audit/compose_seal.jsonl")


def test_record_self_checksum_recorded_as_provenance_artifact():
    prov = _provenance()
    run_id = _expected_run_id()
    ledger = record_phase2b_provenance(
        prov, run_id=run_id, config_sha256=_CONFIG_DIGEST, environment=_environment()
    )
    assert ledger.artifact_sha("phase2b_provenance") == prov.self_checksum


# ---------------------------------------------------------------------------
# write-once behaviour
# ---------------------------------------------------------------------------


def test_record_into_prepopulated_ledger_different_checksum_raises():
    """A pre-existing artifact name with a DIFFERENT checksum raises (write-once)."""
    prov = _provenance()
    run_id = _expected_run_id()
    ledger = RunLedger(run_id=run_id, config_sha256=_CONFIG_DIGEST, environment=_environment())
    # Pre-record one of the required names with a conflicting value.
    ledger.record_artifact("data_card", "SOME-OTHER-VALUE")
    with pytest.raises((ProvenanceError, DuplicateArtifactError)):
        record_phase2b_provenance(
            prov,
            run_id=run_id,
            config_sha256=_CONFIG_DIGEST,
            environment=_environment(),
            ledger=ledger,
        )


def test_runledger_record_same_checksum_still_raises():
    """Document RunLedger's actual write-once behaviour: re-record ALWAYS raises.

    RunLedger.record_artifact raises DuplicateArtifactError even when the hash is
    identical (verified by reading provenance.py). record_phase2b_provenance must
    therefore record each name exactly once on a fresh ledger.
    """
    env = _environment()
    ledger = RunLedger(run_id="x", config_sha256="c", environment=env)
    ledger.record_artifact("data_card", "same")
    with pytest.raises(DuplicateArtifactError):
        ledger.record_artifact("data_card", "same")


def test_record_on_fresh_ledger_does_not_double_record():
    """record_phase2b_provenance records each name exactly once (no duplicate)."""
    prov = _provenance()
    run_id = _expected_run_id()
    # Must not raise (each name written once).
    ledger = record_phase2b_provenance(
        prov, run_id=run_id, config_sha256=_CONFIG_DIGEST, environment=_environment()
    )
    names = [art["name"] for art in ledger.to_dict()["artifacts"]]
    assert len(names) == len(set(names)), "an artifact name was recorded more than once"


# ---------------------------------------------------------------------------
# PRE-ACCESS gate — verify_upstream_before_access RAISES (seal closed)
# ---------------------------------------------------------------------------


def _upstream_ledger() -> RunLedger:
    """A ledger standing in for the upstream provenance the gate verifies."""
    ledger = RunLedger(
        run_id=_expected_run_id(),
        config_sha256=_CONFIG_DIGEST,
        environment=_environment(),
    )
    ledger.record_artifact("frozen_prediction_bundle", "frozen-bundle-sha")
    ledger.record_artifact("pair_manifest", "pair-manifest-sha")
    ledger.record_artifact("model_lock", "model-lock-sha")
    return ledger


def _required_and_expected():
    required = ("frozen_prediction_bundle", "pair_manifest", "model_lock")
    expected = {
        "frozen_prediction_bundle": "frozen-bundle-sha",
        "pair_manifest": "pair-manifest-sha",
        "model_lock": "model-lock-sha",
    }
    return required, expected


def test_pre_access_passes_when_everything_matches():
    required, expected = _required_and_expected()
    # Should NOT raise.
    verify_upstream_before_access(
        expected_run_id=_expected_run_id(),
        recomputed_run_id=_expected_run_id(),
        upstream_ledger=_upstream_ledger(),
        required_artifacts=required,
        expected_checksums=expected,
    )


def test_pre_access_aborts_on_wrong_run_id():
    required, expected = _required_and_expected()
    with pytest.raises(ProvenanceError):
        verify_upstream_before_access(
            expected_run_id=_expected_run_id(),
            recomputed_run_id="WRONG-run-id",
            upstream_ledger=_upstream_ledger(),
            required_artifacts=required,
            expected_checksums=expected,
        )


def test_pre_access_aborts_on_absent_required_artifact():
    required, expected = _required_and_expected()
    ledger = _upstream_ledger()
    # Ask for an artifact the upstream ledger does NOT carry.
    required = required + ("missing_artifact",)
    expected = dict(expected)
    expected["missing_artifact"] = "whatever"
    with pytest.raises(ProvenanceError):
        verify_upstream_before_access(
            expected_run_id=_expected_run_id(),
            recomputed_run_id=_expected_run_id(),
            upstream_ledger=ledger,
            required_artifacts=required,
            expected_checksums=expected,
        )


def test_pre_access_aborts_on_mismatched_checksum():
    required, expected = _required_and_expected()
    bad = dict(expected)
    bad["model_lock"] = "TAMPERED-model-lock"
    with pytest.raises(ProvenanceError):
        verify_upstream_before_access(
            expected_run_id=_expected_run_id(),
            recomputed_run_id=_expected_run_id(),
            upstream_ledger=_upstream_ledger(),
            required_artifacts=required,
            expected_checksums=bad,
        )


def test_pre_access_empty_required_set_raises_no_vacuous_pass():
    """An empty required-artifact set is itself an error (no all([]) pass)."""
    with pytest.raises(ProvenanceError):
        verify_upstream_before_access(
            expected_run_id=_expected_run_id(),
            recomputed_run_id=_expected_run_id(),
            upstream_ledger=_upstream_ledger(),
            required_artifacts=(),
            expected_checksums={},
        )


def test_pre_access_missing_expected_checksum_raises():
    """A required artifact with no expected checksum supplied is an error."""
    required, expected = _required_and_expected()
    incomplete = dict(expected)
    incomplete.pop("model_lock")
    with pytest.raises(ProvenanceError):
        verify_upstream_before_access(
            expected_run_id=_expected_run_id(),
            recomputed_run_id=_expected_run_id(),
            upstream_ledger=_upstream_ledger(),
            required_artifacts=required,
            expected_checksums=incomplete,
        )


# ---------------------------------------------------------------------------
# POST-ACCESS path — check_post_access_consistency returns OK / INVALID
# ---------------------------------------------------------------------------


def _consistent_post_access():
    run_id = _expected_run_id()
    return dict(
        recomputed_run_id=run_id,
        seal_audit_run_id=run_id,
        seal_audit_request_checksum="req-sha",
        observed_request_checksum="req-sha",
        provenance=_provenance(),
        persisted_pre_access_checksum=_provenance().pre_access_checksum,
        result_checksums={"double": "regime-double-sha", "single": "regime-single-sha"},
        expected_result_checksums={"double": "regime-double-sha", "single": "regime-single-sha"},
    )


def test_post_access_consistent_returns_ok():
    status = check_post_access_consistency(**_consistent_post_access())
    assert status is PostAccessStatus.OK


def test_post_access_run_id_mismatch_returns_invalid_without_raising():
    kwargs = _consistent_post_access()
    kwargs["seal_audit_run_id"] = "DIFFERENT-run-in-audit"
    status = check_post_access_consistency(**kwargs)  # must not raise
    assert status is PostAccessStatus.INVALID


def test_post_access_audit_request_mismatch_returns_invalid():
    kwargs = _consistent_post_access()
    kwargs["observed_request_checksum"] = "TAMPERED-request"
    status = check_post_access_consistency(**kwargs)
    assert status is PostAccessStatus.INVALID


def test_post_access_result_checksum_mismatch_returns_invalid():
    kwargs = _consistent_post_access()
    kwargs["result_checksums"] = {"double": "TAMPERED", "single": "regime-single-sha"}
    status = check_post_access_consistency(**kwargs)
    assert status is PostAccessStatus.INVALID


def test_post_access_provenance_checksum_mismatch_returns_invalid():
    kwargs = _consistent_post_access()
    kwargs["persisted_pre_access_checksum"] = "DIFFERENT-provenance-checksum"
    status = check_post_access_consistency(**kwargs)
    assert status is PostAccessStatus.INVALID


def test_post_access_never_raises_on_detected_inconsistency():
    """The post-access path returns INVALID; it must NEVER raise on a mismatch."""
    kwargs = _consistent_post_access()
    kwargs["seal_audit_run_id"] = "X"
    kwargs["observed_request_checksum"] = "Y"
    kwargs["result_checksums"] = {"double": "Z", "single": "W"}
    kwargs["persisted_pre_access_checksum"] = "V"
    # No exception type expected; a raise here is a contract violation.
    status = check_post_access_consistency(**kwargs)
    assert status is PostAccessStatus.INVALID


# ---------------------------------------------------------------------------
# Structural: the two paths are distinct functions.
# ---------------------------------------------------------------------------


def test_pre_and_post_access_are_distinct_callables():
    assert verify_upstream_before_access is not check_post_access_consistency
    # The pre-access gate returns None (it only raises or passes).
    sig = inspect.signature(verify_upstream_before_access)
    assert sig.return_annotation in (None, "None")
    # The post-access path returns a PostAccessStatus.
    post_sig = inspect.signature(check_post_access_consistency)
    assert post_sig.return_annotation in (PostAccessStatus, "PostAccessStatus")


def test_provenance_error_and_ledger_error_are_distinct():
    """ProvenanceError is the gate's abort type; LedgerError is the ledger's."""
    assert issubclass(ProvenanceError, Exception)
    assert ProvenanceError is not LedgerError


# ---------------------------------------------------------------------------
# Change C infra: pre-access digest subset (excludes post-access fields)
# ---------------------------------------------------------------------------

_POST_ACCESS_KEYS = (
    "regime_result_double_sha256",
    "regime_result_single_sha256",
)


def test_pre_access_subset_excludes_post_access_fields():
    sub = _provenance().pre_access_digest_subset()
    for key in _POST_ACCESS_KEYS:
        assert key not in sub
    # a pre-access field survives in the subset.
    assert sub["data_card_sha256"] == _DATA_CARD_DIGEST


def test_pre_access_checksum_ignores_post_access_fields():
    a = _provenance()
    b = _provenance(
        regime_result_double_sha256="X",
        regime_result_single_sha256="Y",
    )
    # The subset checksum is stable across post-access-only changes ...
    assert a.pre_access_checksum == b.pre_access_checksum
    # ... while the FULL self-checksum still moves (post-access fields are in it).
    assert a.self_checksum != b.self_checksum


def test_pre_access_checksum_moves_on_a_pre_access_field():
    a = _provenance()
    b = _provenance(processed_sha256="TAMPERED")
    assert a.pre_access_checksum != b.pre_access_checksum


def test_pre_access_checksum_is_64_hex():
    c = _provenance().pre_access_checksum
    assert len(c) == 64 and all(ch in "0123456789abcdef" for ch in c)


# ---------------------------------------------------------------------------
# Change C infra: record_pre_access_provenance (write-once, before access)
# ---------------------------------------------------------------------------


def test_record_pre_access_provenance_records_subset_checksum():
    ledger = RunLedger(
        run_id=_expected_run_id(), config_sha256=_CONFIG_DIGEST, environment=_environment()
    )
    prov = _provenance()
    returned = record_pre_access_provenance(ledger=ledger, provenance=prov)
    assert returned == prov.pre_access_checksum
    assert ledger.artifact_sha(PRE_ACCESS_PROVENANCE_ARTIFACT) == prov.pre_access_checksum


def test_record_pre_access_provenance_is_write_once():
    ledger = RunLedger(
        run_id=_expected_run_id(), config_sha256=_CONFIG_DIGEST, environment=_environment()
    )
    record_pre_access_provenance(ledger=ledger, provenance=_provenance())
    # A second record under the same name (even a different value) is refused.
    with pytest.raises(ProvenanceError):
        record_pre_access_provenance(
            ledger=ledger, provenance=_provenance(processed_sha256="different")
        )


def test_persist_pre_access_ledger_round_trip(tmp_path):
    ledger = RunLedger(
        run_id=_expected_run_id(), config_sha256=_CONFIG_DIGEST, environment=_environment()
    )
    record_pre_access_provenance(ledger=ledger, provenance=_provenance())
    path = persist_pre_access_ledger(run_dir=tmp_path, ledger=ledger)
    assert path.name == PRE_ACCESS_LEDGER_FILENAME
    assert RunLedger.read(path) == ledger
    with pytest.raises(ProvenanceError):
        persist_pre_access_ledger(run_dir=tmp_path, ledger=ledger)
