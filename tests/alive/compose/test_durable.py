"""D1 Task 5 — durable-publish finalizer (:mod:`alive.compose.durable`).

The finalizer reads the ALREADY-WRITTEN durable inputs — the single sealed
terminal artifact, the persisted pre-access ledger snapshot and the D2
seed-variability report — and publishes three DERIVED files: the outcome-free
registered summary, the final ledger, and the single durable commit marker (the
marker installed LAST). It opens NO seal and constructs NO outcome store.

These tests are SYNTHETIC-ONLY: a real ``Phase2bTerminal`` writes a genuine v2
``COMPLETE`` terminal body (so its ``terminal_payload_checksum`` is produced by
the shared canonicalizer, floats and all), and a real
:class:`~alive.provenance.RunLedger` snapshot plays the persisted pre-access
ledger. No real Norman data, no seal, no sealed outcome.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from alive.compose.durable import (  # noqa: E402  (module under test — imported last)
    DurableFinalizeResult,
    DurableLedgerError,
    finalize_phase2b_durable_outputs,
)
from alive.compose.provenance2 import (
    PRE_ACCESS_LEDGER_FILENAME,
    PRE_ACCESS_PROVENANCE_ARTIFACT,
    Phase2bProvenance,
)
from alive.compose.seed_variability import DEVELOPMENT_SEED_VARIABILITY_FILENAME
from alive.compose.terminal import Phase2bTerminal
from alive.provenance import EnvironmentInfo, RunLedger, sha256_json

_RUN_ID = "deadbeefdeadbeef"
_PROTOCOL = "COMPOSE-K562-v1"


def _environment() -> EnvironmentInfo:
    return EnvironmentInfo(
        python_version="3.12.0",
        platform="test-platform",
        git_commit="0" * 40,
        lockfile_sha256="lock-sha-eeee",
        registered_seeds=(0, 1, 2),
    )


def _provenance() -> Phase2bProvenance:
    """A fully-populated synthetic COMPLETE provenance (finite scalars only)."""
    return Phase2bProvenance(
        protocol=_PROTOCOL,
        config_digest="config-sha-bbbb",
        pair_manifest_sha256="11" * 32,
        exclusion_manifest_sha256="22" * 32,
        data_card_sha256="33" * 32,
        raw_or_source_sha256="44" * 32,
        processed_sha256="55" * 32,
        sequence_mapping_sha256="66" * 32,
        feature_bank_sha256="77" * 32,
        response_space_sha256="88" * 32,
        factor_bank_sha256="99" * 32,
        model_lock_sha256="aa" * 32,
        frozen_prediction_bundle_sha256="bb" * 32,
        git_commit="0" * 40,
        git_clean=True,
        dependency_lock_sha256="cc" * 32,
        gears_revision="gears-1.2.3",
        cpa_revision="cpa-4.5.6",
        python_version="3.12.0",
        platform="test-platform",
        device="cpu",
        precision="float32",
        registered_seeds=(0, 1, 2),
        split_seed=7,
        seal_audit_reference="audit-ref-xyz",
        regime_result_double_sha256="dd" * 32,
        regime_result_single_sha256="ee" * 32,
    )


def _registered_summary() -> dict:
    """A minimal outcome-free registered summary (finite floats only, no per-pair)."""
    return {
        "protocol": _PROTOCOL,
        "run_id": _RUN_ID,
        "terminal_state": "COMPLETE",
        "sealed_access_count": 1,
        "sample_counts": {"double": 4, "single": 4},
        "per_method_aggregate_mse": {"l1_bilinear_identifiable": 0.40, "additive": 0.55},
        "theta": {"additive": 0.42},
        "simultaneous_lower_bounds": {"additive": 0.10},
        "family_confidence": 0.95,
        "bootstrap_replicates": 3,
        "gi_explained_point": 0.12,
        "gi_explained_interval": [0.05, 0.20],
        "gi_structure_recovery": "NOT_EVALUABLE",
        "sealed_axis": "NO_DISTINCT_WIN",
        "method_axis": "METHOD_VALIDATED",
        "verdict_clauses": {"integrity_valid": True},
        "integrity_disclaimer": "structural run-internal self-check only",
        "bundle_checksum": "a" * 64,
        "manifest_checksum": "b" * 64,
        "provenance_checksum": "c" * 64,
        "regime_result_double_checksum": "d" * 64,
        "regime_result_single_checksum": "e" * 64,
        "bounds_checksum": "f" * 64,
        "seed_variability_report_checksum": "0" * 64,
    }


def _write_seed_variability(run_dir: Path) -> tuple[Path, str, str]:
    """Write a synthetic seed-variability report with a self-excluding checksum."""
    payload = {
        "schema": "compose_development_seed_variability_v1",
        "protocol": _PROTOCOL,
        "run_id": _RUN_ID,
        "methods": {"gears": {"seed_mse": [0.1, 0.2]}, "cpa": {"seed_mse": [0.3, 0.4]}},
    }
    report_checksum = sha256_json(payload)
    doc = {**payload, "report_checksum": report_checksum}
    text = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    path = run_dir / DEVELOPMENT_SEED_VARIABILITY_FILENAME
    path.write_text(text, encoding="utf-8")
    byte_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return path, byte_sha, report_checksum


def _persist_pre_access_ledger(
    run_dir: Path, *, provenance: Phase2bProvenance, seed_byte_sha: str
) -> Path:
    """Persist a pre-access ledger snapshot whose shared digests match ``provenance``."""
    ledger = RunLedger(run_id=_RUN_ID, config_sha256="config-sha-bbbb", environment=_environment())
    # Upstream run-identity + frozen-bundle digests that a real pre-access ledger
    # already carries, byte-identical to the terminal's embedded provenance.
    ledger.record_artifact("data_card", provenance.data_card_sha256)
    ledger.record_artifact("raw_data", provenance.raw_or_source_sha256)
    ledger.record_artifact("sequence_mapping", provenance.sequence_mapping_sha256)
    ledger.record_artifact("pair_manifest", provenance.pair_manifest_sha256)
    ledger.record_artifact("response_space", provenance.response_space_sha256)
    ledger.record_artifact("factor_bank", provenance.factor_bank_sha256)
    ledger.record_artifact("frozen_prediction_bundle", provenance.frozen_prediction_bundle_sha256)
    ledger.record_artifact("development_seed_variability", seed_byte_sha)
    ledger.record_artifact(PRE_ACCESS_PROVENANCE_ARTIFACT, provenance.pre_access_checksum)
    path = run_dir / PRE_ACCESS_LEDGER_FILENAME
    ledger.write(path)
    return path


def _write_complete_terminal(
    run_dir: Path, *, tmp_path: Path, provenance: Phase2bProvenance, pre_access_sha: str
) -> Path:
    """Drive a real ``Phase2bTerminal`` to write a genuine v2 COMPLETE terminal."""
    summary = _registered_summary()
    registered_summary_checksum = sha256_json(summary)
    embedded = provenance.to_dict()
    provenance_checksum = provenance.self_checksum
    final_result_checksum = sha256_json(
        {
            "terminal_state": "COMPLETE",
            "final_verdict_checksum": "2" * 64,
            "registered_summary_checksum": registered_summary_checksum,
            "evaluation_payload_checksum": "1" * 64,
            "provenance_checksum": provenance_checksum,
        }
    )
    body = {
        "registered_summary": summary,
        "registered_summary_checksum": registered_summary_checksum,
        "final_verdict_checksum": "2" * 64,
        "terminal_embedded_provenance": embedded,
        "provenance_checksum": provenance_checksum,
        "evaluation_payload_checksum": "1" * 64,
        "final_result_checksum": final_result_checksum,
    }

    audit_path = tmp_path / "audit.jsonl"
    term = Phase2bTerminal(
        run_dir,
        ledger=RunLedger(
            run_id=_RUN_ID, config_sha256="config-sha-bbbb", environment=_environment()
        ),
        audit_path=audit_path,
        protocol=_PROTOCOL,
        run_id=_RUN_ID,
        pre_access_ledger_sha256=pre_access_sha,
        pre_access_provenance_checksum=provenance.pre_access_checksum,
    )
    term.acquire()
    term.attempt_access()
    audit_path.write_text(json.dumps({"run_id": _RUN_ID, "pair_ids": []}) + "\n", encoding="utf-8")
    term.confirm_durable_access("durable-audit-reference-xyz")
    term.complete(body)
    return run_dir / Phase2bTerminal.COMPLETE_ARTIFACT


def _build_scenario(tmp_path: Path) -> dict:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    provenance = _provenance()
    seed_path, seed_byte_sha, seed_report_checksum = _write_seed_variability(run_dir)
    pre_access_path = _persist_pre_access_ledger(
        run_dir, provenance=provenance, seed_byte_sha=seed_byte_sha
    )
    pre_access_sha = hashlib.sha256(pre_access_path.read_bytes()).hexdigest()
    terminal_path = _write_complete_terminal(
        run_dir, tmp_path=tmp_path, provenance=provenance, pre_access_sha=pre_access_sha
    )
    return {
        "run_dir": run_dir,
        "terminal_path": terminal_path,
        "pre_access_path": pre_access_path,
        "seed_path": seed_path,
        "seed_report_checksum": seed_report_checksum,
        "provenance": provenance,
    }


def _file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _finalize(scenario: dict) -> DurableFinalizeResult:
    return finalize_phase2b_durable_outputs(
        run_dir=scenario["run_dir"],
        terminal_path=scenario["terminal_path"],
        pre_access_ledger_path=scenario["pre_access_path"],
        seed_variability_path=scenario["seed_path"],
    )


# ---------------------------------------------------------------------------
# Step 1 (brief §6.1): synthetic COMPLETE terminal -> publish -> all three
# derived files re-read + verify, and the marker binds every file SHA.
# ---------------------------------------------------------------------------


def test_finalize_publishes_and_marker_binds_every_file_sha(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)
    result = _finalize(scenario)

    assert isinstance(result, DurableFinalizeResult)
    assert result.terminal_state == "COMPLETE"

    run_dir = scenario["run_dir"]
    summary_path = run_dir / "phase2b_registered_summary.json"
    final_ledger_path = run_dir / "phase2b_final_ledger.json"
    marker_path = run_dir / "phase2b_durable_commit.json"

    assert result.registered_summary_path == summary_path
    assert result.final_ledger_path == final_ledger_path
    assert result.commit_marker_path == marker_path
    for p in (summary_path, final_ledger_path, marker_path):
        assert p.is_file()

    # --- the published summary is a byte-faithful copy+normalise of the terminal's
    # registered_summary (no recomputation).
    terminal_body = json.loads(scenario["terminal_path"].read_text(encoding="utf-8"))
    expected_summary = terminal_body["registered_summary"]
    published_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert published_summary == expected_summary
    # canonical bytes
    assert summary_path.read_bytes() == json.dumps(
        expected_summary, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    # --- the final ledger re-reads as a valid RunLedger carrying the file-SHA
    # entries + the expanded provenance entries.
    final_ledger = RunLedger.read(final_ledger_path)
    assert final_ledger.to_dict()["run_id"] == _RUN_ID
    assert final_ledger.artifact_sha("terminal_complete.json") == _file_sha(
        scenario["terminal_path"]
    )
    assert final_ledger.artifact_sha("phase2b_registered_summary.json") == _file_sha(summary_path)
    assert final_ledger.artifact_sha(DEVELOPMENT_SEED_VARIABILITY_FILENAME) == _file_sha(
        scenario["seed_path"]
    )
    # expanded provenance entry (from the embedded provenance, reused mapping)
    assert final_ledger.artifact_sha("regime_result_double") == "dd" * 32
    assert final_ledger.artifact_sha("model_lock") == "aa" * 32

    # --- the marker re-reads, its self-checksum recomputes, and it binds EVERY
    # published/consumed file SHA.
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    core = {k: v for k, v in marker.items() if k != "commit_checksum"}
    assert sha256_json(core) == marker["commit_checksum"] == result.commit_checksum
    assert marker["run_id"] == _RUN_ID
    assert marker["terminal_state"] == "COMPLETE"

    assert marker["terminal"]["sha256"] == _file_sha(scenario["terminal_path"])
    assert marker["registered_summary"]["sha256"] == _file_sha(summary_path)
    assert marker["final_ledger"]["sha256"] == _file_sha(final_ledger_path)
    assert marker["pre_access_ledger"]["sha256"] == _file_sha(scenario["pre_access_path"])
    assert marker["seed_variability"]["sha256"] == _file_sha(scenario["seed_path"])
    # self-checksums the marker binds (summary registered_summary_checksum + seed report_checksum)
    assert (
        marker["registered_summary"]["self_checksum"]
        == terminal_body["registered_summary_checksum"]
    )
    assert marker["seed_variability"]["self_checksum"] == scenario["seed_report_checksum"]


def test_final_ledger_does_not_record_the_commit_marker_and_marker_is_last(
    tmp_path: Path,
) -> None:
    """Non-self-reference: the marker binds the final ledger externally; the final
    ledger records neither the marker nor itself (deliberate non-circular order)."""
    scenario = _build_scenario(tmp_path)
    result = _finalize(scenario)

    final_ledger = RunLedger.read(result.final_ledger_path)
    names = {rec["name"] for rec in final_ledger.to_dict()["artifacts"]}
    assert "phase2b_durable_commit.json" not in names
    assert "phase2b_final_ledger.json" not in names

    # marker last: it records the final ledger's on-disk SHA, i.e. it was written
    # AFTER the final ledger was fully installed.
    marker = json.loads(result.commit_marker_path.read_text(encoding="utf-8"))
    assert marker["final_ledger"]["sha256"] == _file_sha(result.final_ledger_path)


def test_published_summary_has_no_per_pair_arrays_or_ci(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)
    result = _finalize(scenario)
    published = json.loads(result.registered_summary_path.read_text(encoding="utf-8"))

    forbidden_substrings = ("per_pair", "pair_error", "pair_ci", "raw", "matrix", "cells")

    def _walk(obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                assert not any(frag in str(key).lower() for frag in forbidden_substrings), (
                    f"forbidden per-pair/raw key in published summary: {key!r}"
                )
                _walk(value)
        elif isinstance(obj, list):
            # no per-pair array (a per-pair CI would be a list-of-pairs); intervals
            # stay short (<= a handful).
            assert len(obj) <= 8, "unexpectedly long array in published summary"
            for item in obj:
                assert not isinstance(item, list), "nested list (matrix/per-pair CI) forbidden"
                _walk(item)

    _walk(published)


def test_second_finalize_is_write_once_and_fails_closed(tmp_path: Path) -> None:
    """Forward publish is write-once (idempotent recovery is Task 6): a second
    call over already-published derived files fails closed, never overwriting."""
    scenario = _build_scenario(tmp_path)
    _finalize(scenario)
    with pytest.raises(DurableLedgerError):
        _finalize(scenario)


def test_symlinked_terminal_is_rejected(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)
    run_dir = scenario["run_dir"]
    # A terminal path that is a symlink (even to the real terminal) must be refused.
    link = run_dir / "terminal_complete_link.json"
    # place the link OUTSIDE the roster name so the roster check would otherwise
    # be the failure; use the real roster name in a sibling dir to isolate symlink.
    other = tmp_path / "other"
    other.mkdir()
    real_copy = other / "terminal_complete.json"
    real_copy.write_bytes(scenario["terminal_path"].read_bytes())
    link.symlink_to(real_copy)
    with pytest.raises(DurableLedgerError):
        finalize_phase2b_durable_outputs(
            run_dir=run_dir,
            terminal_path=link,
            pre_access_ledger_path=scenario["pre_access_path"],
            seed_variability_path=scenario["seed_path"],
        )
