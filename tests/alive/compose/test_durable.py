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

from alive.compose.config2 import _EXPECTED_COMPARATOR_FAMILY, _EXPECTED_METHOD_ROSTER
from alive.compose.durable import (  # noqa: E402  (module under test — imported last)
    _REGISTERED_SUMMARY_SCHEMA_V1,
    DURABLE_COMMIT_FILENAME,
    FINAL_LEDGER_FILENAME,
    REGISTERED_SUMMARY_FILENAME,
    DurableFinalizeResult,
    DurableLedgerError,
    finalize_phase2b_durable_outputs,
    install_or_verify_exact,
    recover_phase2b_durable_outputs,
)
from alive.compose.provenance2 import (
    PRE_ACCESS_LEDGER_FILENAME,
    PRE_ACCESS_PROVENANCE_ARTIFACT,
    Phase2bProvenance,
)
from alive.compose.seed_variability import DEVELOPMENT_SEED_VARIABILITY_FILENAME
from alive.compose.terminal import (
    TERMINAL_PAYLOAD_CHECKSUM_FIELD,
    Phase2bTerminal,
    canonicalize_terminal_checksum_input,
)
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


def _registered_summary(state: str = "COMPLETE") -> dict:
    """A Task-5 v1 outcome-free registered summary (finite floats only, no per-pair).

    Carries the v1 ``schema``, a per-regime ``per_method_aggregate_mse`` over the FULL
    9-method roster, and a ``theta`` / ``simultaneous_lower_bounds`` over the 5-comparator
    family — the exact shape the finalizer's Task-6 validation requires. Rosters are
    sourced from :mod:`alive.compose.config2` (never a divergent hardcoded list).
    """
    per_method_double = {
        method: round(0.40 + 0.01 * idx, 4) for idx, method in enumerate(_EXPECTED_METHOD_ROSTER)
    }
    per_method_single = {
        method: round(value + 0.02, 4) for method, value in per_method_double.items()
    }
    theta = {
        comparator: round(0.30 + 0.01 * idx, 4)
        for idx, comparator in enumerate(_EXPECTED_COMPARATOR_FAMILY)
    }
    return {
        "schema": _REGISTERED_SUMMARY_SCHEMA_V1,
        "protocol": _PROTOCOL,
        "run_id": _RUN_ID,
        "terminal_state": state,
        "sealed_access_count": 1,
        "sample_counts": {"double": 4, "single": 4},
        "per_method_aggregate_mse": {
            "double": per_method_double,
            "single": per_method_single,
        },
        "theta": theta,
        "simultaneous_lower_bounds": {c: round(v - 0.05, 4) for c, v in theta.items()},
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
        # Task 7: the pre-registered approximation-bias fairness carry (§5/§7). Carried
        # verbatim (not decided from) into the durable summary; here the null-config
        # (not-yet-finalized) shape — the honestly-empty "unavailable" block.
        "approximation_bias_fairness": {
            "report_sha256": None,
            "fairness_flag": "unavailable",
            "bias_to_signal_ratio_R": None,
            "bootstrap_95_interval": None,
            "R_star": None,
        },
    }


def _write_seed_variability(
    run_dir: Path, *, break_self_checksum: bool = False
) -> tuple[Path, str, str]:
    """Write a synthetic seed-variability report with a self-excluding checksum.

    Mirrors the EXACT self-checksum derivation of
    :func:`alive.compose.seed_variability.development_seed_variability`:
    ``report_checksum == sha256_json(payload_without_report_checksum)``. When
    ``break_self_checksum`` is set the stored ``report_checksum`` is inconsistent
    with the payload (used to exercise the M1 self-checksum hardening) while the
    on-disk byte SHA still round-trips into the pre-access ledger.
    """
    payload = {
        "schema": "compose_development_seed_variability_v1",
        "protocol": _PROTOCOL,
        "run_id": _RUN_ID,
        "methods": {"gears": {"seed_mse": [0.1, 0.2]}, "cpa": {"seed_mse": [0.3, 0.4]}},
    }
    report_checksum = sha256_json(payload)
    stored_checksum = ("f" * 64) if break_self_checksum else report_checksum
    doc = {**payload, "report_checksum": stored_checksum}
    text = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    path = run_dir / DEVELOPMENT_SEED_VARIABILITY_FILENAME
    path.write_text(text, encoding="utf-8")
    byte_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return path, byte_sha, stored_checksum


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
    run_dir: Path,
    *,
    tmp_path: Path,
    provenance: Phase2bProvenance,
    pre_access_sha: str,
    state: str = "COMPLETE",
) -> Path:
    """Drive a real ``Phase2bTerminal`` to write a genuine v2 summary-bearing terminal.

    ``state`` selects the summary-bearing terminal to write (``"COMPLETE"`` or
    ``"INVALID"``); both share :data:`_COMPLETE_INVALID_STATE_FIELDS`, so the body
    layout is identical and only the terminal writer method / bound state differ.
    """
    summary = _registered_summary(state)
    registered_summary_checksum = sha256_json(summary)
    embedded = provenance.to_dict()
    provenance_checksum = provenance.self_checksum
    final_result_checksum = sha256_json(
        {
            "terminal_state": state,
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
    if state == "INVALID":
        term.invalid(body)
        return run_dir / Phase2bTerminal.INVALID_ARTIFACT
    term.complete(body)
    return run_dir / Phase2bTerminal.COMPLETE_ARTIFACT


def _write_aborted_terminal(
    run_dir: Path,
    *,
    tmp_path: Path,
    provenance: Phase2bProvenance,
    pre_access_sha: str,
) -> Path:
    """Drive a real ``Phase2bTerminal`` to write a genuine v2 ``ABORTED_AFTER_SEAL``.

    An aborted terminal carries NO ``registered_summary`` and NO
    ``terminal_embedded_provenance`` — only the abort state fields (exception class,
    scrubbed message, stage, preflight checksums, audit reference, results status),
    the common identity roster (including the two pre-access identity anchors) and
    the shared ``terminal_payload_checksum``. Its checksum is produced by the SAME
    canonicalizer the summary-bearing terminals use.
    """
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
    term.aborted(
        exception=RuntimeError("scoring stage blew up"),
        stage="scoring",
        preflight_checksums={"pair_manifest": "11" * 32},
    )
    return run_dir / Phase2bTerminal.ABORTED_ARTIFACT


def _build_scenario(
    tmp_path: Path, *, state: str = "COMPLETE", break_seed_self_checksum: bool = False
) -> dict:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    provenance = _provenance()
    seed_path, seed_byte_sha, seed_report_checksum = _write_seed_variability(
        run_dir, break_self_checksum=break_seed_self_checksum
    )
    pre_access_path = _persist_pre_access_ledger(
        run_dir, provenance=provenance, seed_byte_sha=seed_byte_sha
    )
    pre_access_sha = hashlib.sha256(pre_access_path.read_bytes()).hexdigest()
    if state == "ABORTED":
        terminal_path = _write_aborted_terminal(
            run_dir,
            tmp_path=tmp_path,
            provenance=provenance,
            pre_access_sha=pre_access_sha,
        )
    else:
        terminal_path = _write_complete_terminal(
            run_dir,
            tmp_path=tmp_path,
            provenance=provenance,
            pre_access_sha=pre_access_sha,
            state=state,
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


def _install_doctored_terminal(
    terminal_path: Path,
    *,
    summary: dict | None = None,
    final_result_checksum: str | None = None,
) -> None:
    """Doctor an already-written terminal, re-deriving every checksum consistently.

    Loads the real v2 body and, when ``summary`` is given, swaps its
    ``registered_summary`` while recomputing ``registered_summary_checksum`` then
    ``final_result_checksum`` from the five identity fields; when
    ``final_result_checksum`` is given it overrides that field directly. In every
    case the whole-body ``terminal_payload_checksum`` is RE-DERIVED through the SHARED
    canonicalizer, so every EARLIER finalizer check stays self-consistent and only the
    intended NEW check can fire. The whole-body checksum is NEVER recomputed via a raw
    ``sha256_json`` over the decoded body — a real terminal's finite floats are
    ``float.hex()``-canonicalized, which a raw hash would reject.
    """
    body = json.loads(terminal_path.read_text(encoding="utf-8"))
    if summary is not None:
        body["registered_summary"] = summary
        body["registered_summary_checksum"] = sha256_json(summary)
        body["final_result_checksum"] = sha256_json(
            {
                "terminal_state": body["terminal_state"],
                "final_verdict_checksum": body["final_verdict_checksum"],
                "registered_summary_checksum": body["registered_summary_checksum"],
                "evaluation_payload_checksum": body["evaluation_payload_checksum"],
                "provenance_checksum": body["provenance_checksum"],
            }
        )
    if final_result_checksum is not None:
        body["final_result_checksum"] = final_result_checksum
    core = {k: v for k, v in body.items() if k != TERMINAL_PAYLOAD_CHECKSUM_FIELD}
    body[TERMINAL_PAYLOAD_CHECKSUM_FIELD] = sha256_json(canonicalize_terminal_checksum_input(core))
    terminal_path.write_text(
        json.dumps(body, sort_keys=True, separators=(",", ":")), encoding="utf-8"
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


def test_second_finalize_is_idempotent_noop(tmp_path: Path) -> None:
    """Forward publish is now idempotent (Task 6): a second call over
    byte-identical derived files re-verifies and returns the SAME marker, never
    a write-once ``FileExistsError`` and never an overwrite."""
    scenario = _build_scenario(tmp_path)
    first = _finalize(scenario)
    summary_before = first.registered_summary_path.read_bytes()
    ledger_before = first.final_ledger_path.read_bytes()
    marker_before = first.commit_marker_path.read_bytes()

    second = _finalize(scenario)

    assert second.commit_checksum == first.commit_checksum
    assert second.commit_marker_path == first.commit_marker_path
    # No overwrite: every derived file is byte-for-byte unchanged.
    assert first.registered_summary_path.read_bytes() == summary_before
    assert first.final_ledger_path.read_bytes() == ledger_before
    assert first.commit_marker_path.read_bytes() == marker_before


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


def test_roster_named_symlink_terminal_is_rejected(tmp_path: Path) -> None:
    """M3: a ROSTER-NAMED terminal that is itself a symlink is rejected by the
    symlink guard, isolated from the roster/scan name checks.

    The prior test names the symlink OUTSIDE the roster, so the roster check could
    fire first. Here ``terminal_complete.json`` (a roster name) IS the symlink, so
    only the symlink guard can reject it — proving the guard, not the roster check.
    """
    scenario = _build_scenario(tmp_path)
    run_dir = scenario["run_dir"]
    # Move the real terminal to a non-roster regular child, then re-create the
    # roster name terminal_complete.json AS a symlink pointing at that child.
    backing = run_dir / "terminal_real_backing.json"
    scenario["terminal_path"].rename(backing)
    roster_link = run_dir / Phase2bTerminal.COMPLETE_ARTIFACT
    roster_link.symlink_to(backing)

    # Forward finalize resolves the caller-supplied roster-named symlink -> rejected.
    with pytest.raises(DurableLedgerError):
        finalize_phase2b_durable_outputs(
            run_dir=run_dir,
            terminal_path=roster_link,
            pre_access_ledger_path=scenario["pre_access_path"],
            seed_variability_path=scenario["seed_path"],
        )
    # Independent recovery scan must ALSO reject the roster-named symlink.
    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=run_dir)


# ---------------------------------------------------------------------------
# M2: INVALID forward publish (shares the COMPLETE/INVALID state roster).
# ---------------------------------------------------------------------------


def test_finalize_publishes_invalid_terminal(tmp_path: Path) -> None:
    """An INVALID terminal publishes the three derived files and the marker binds
    every file SHA (closes the untested-INVALID-path gap)."""
    scenario = _build_scenario(tmp_path, state="INVALID")
    result = _finalize(scenario)

    assert result.terminal_state == "INVALID"
    run_dir = scenario["run_dir"]
    summary_path = run_dir / REGISTERED_SUMMARY_FILENAME
    final_ledger_path = run_dir / FINAL_LEDGER_FILENAME
    marker_path = run_dir / DURABLE_COMMIT_FILENAME
    for p in (summary_path, final_ledger_path, marker_path):
        assert p.is_file()

    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["terminal_state"] == "INVALID"
    assert marker["terminal"]["filename"] == Phase2bTerminal.INVALID_ARTIFACT
    assert marker["terminal"]["sha256"] == _file_sha(scenario["terminal_path"])
    assert marker["registered_summary"]["sha256"] == _file_sha(summary_path)
    assert marker["final_ledger"]["sha256"] == _file_sha(final_ledger_path)
    assert marker["pre_access_ledger"]["sha256"] == _file_sha(scenario["pre_access_path"])
    assert marker["seed_variability"]["sha256"] == _file_sha(scenario["seed_path"])
    core = {k: v for k, v in marker.items() if k != "commit_checksum"}
    assert sha256_json(core) == marker["commit_checksum"] == result.commit_checksum

    # The published summary is the INVALID summary copied byte-faithfully.
    published = json.loads(summary_path.read_text(encoding="utf-8"))
    assert published["terminal_state"] == "INVALID"


# ---------------------------------------------------------------------------
# Task 6 (C0 #6): the finalizer recomputes final_result_checksum from its 5
# constituents and validates the registered-summary schema + rosters. Each
# negative doctors the terminal so ONLY the intended new check fires — every
# earlier bind + whole-body checksum is re-derived consistently.
# ---------------------------------------------------------------------------


def test_finalizer_rejects_wrong_final_result_checksum(tmp_path: Path) -> None:
    """A self-consistent-but-WRONG final_result_checksum is caught by the finalizer's
    5-field recompute. The whole-body checksum is re-derived so it BINDS the wrong
    value, and the 5 constituents (registered_summary_checksum / provenance_checksum)
    are untouched — so every earlier check passes and only the new recompute fires."""
    scenario = _build_scenario(tmp_path)
    _install_doctored_terminal(scenario["terminal_path"], final_result_checksum="0" * 64)
    with pytest.raises(DurableLedgerError, match="final_result_checksum"):
        _finalize(scenario)


def test_finalizer_rejects_bad_summary_roster(tmp_path: Path) -> None:
    """A summary whose per_method_aggregate_mse['double'] drops a method (roster != the
    9-method roster) fails closed. The summary → registered_summary_checksum →
    final_result_checksum → whole-body checksum cascade is rebuilt consistently, so the
    registered_summary_checksum bind and the final_result recompute both PASS and only
    the roster check fires."""
    scenario = _build_scenario(tmp_path)
    summary = _registered_summary()
    summary["per_method_aggregate_mse"]["double"].pop(_EXPECTED_METHOD_ROSTER[0])
    _install_doctored_terminal(scenario["terminal_path"], summary=summary)
    with pytest.raises(DurableLedgerError, match="roster|method"):
        _finalize(scenario)


def test_finalizer_rejects_unexpected_summary_schema(tmp_path: Path) -> None:
    """A summary carrying a non-v1 schema fails closed. The full checksum cascade is
    rebuilt consistently so only the schema check fires."""
    scenario = _build_scenario(tmp_path)
    summary = _registered_summary()
    summary["schema"] = "not_v1"
    _install_doctored_terminal(scenario["terminal_path"], summary=summary)
    with pytest.raises(DurableLedgerError, match="schema"):
        _finalize(scenario)


def test_finalizer_rejects_bad_theta_roster(tmp_path: Path) -> None:
    """A summary whose theta roster != the 5-comparator family fails closed (the full
    checksum cascade is rebuilt so only the theta check fires)."""
    scenario = _build_scenario(tmp_path)
    summary = _registered_summary()
    summary["theta"].pop(_EXPECTED_COMPARATOR_FAMILY[0])
    _install_doctored_terminal(scenario["terminal_path"], summary=summary)
    with pytest.raises(DurableLedgerError, match="theta"):
        _finalize(scenario)


def test_durable_fails_closed_when_block_absent(tmp_path: Path) -> None:
    """Task 7: a summary lacking the approximation_bias_fairness carry fails closed.

    The finalizer NEVER populates or mutates the block — a summary-bearing terminal
    that omits it is refused (the full checksum cascade is rebuilt so only the new
    presence/shape assertion fires)."""
    scenario = _build_scenario(tmp_path)
    summary = _registered_summary()
    del summary["approximation_bias_fairness"]
    _install_doctored_terminal(scenario["terminal_path"], summary=summary)
    with pytest.raises(DurableLedgerError, match="approximation_bias_fairness"):
        _finalize(scenario)


def test_durable_copy_verbatim_still_holds(tmp_path: Path) -> None:
    """Task 7: with the fairness block present, the durable copy stays byte-verbatim.

    The published registered summary carries the block, equals the terminal's summary
    byte-for-byte, and ``sha256_json(summary) == registered_summary_checksum`` holds
    end-to-end (durable copies, never mutates)."""
    scenario = _build_scenario(tmp_path)
    result = _finalize(scenario)
    terminal_body = json.loads(scenario["terminal_path"].read_text(encoding="utf-8"))
    published = json.loads(result.registered_summary_path.read_text(encoding="utf-8"))
    assert "approximation_bias_fairness" in published
    assert published == terminal_body["registered_summary"]
    assert sha256_json(published) == terminal_body["registered_summary_checksum"]


# ---------------------------------------------------------------------------
# Part A: install_or_verify_exact (spec §3.2).
# ---------------------------------------------------------------------------


def test_install_or_verify_exact_absent_installs(tmp_path: Path) -> None:
    path = tmp_path / "durable.json"
    install_or_verify_exact(path, "hello-durable")
    assert path.read_text(encoding="utf-8") == "hello-durable"


def test_install_or_verify_exact_identical_is_noop(tmp_path: Path) -> None:
    path = tmp_path / "durable.json"
    path.write_text("hello-durable", encoding="utf-8")
    inode_before = path.stat().st_ino

    install_or_verify_exact(path, "hello-durable")  # no error

    assert path.read_text(encoding="utf-8") == "hello-durable"
    # A no-op keeps the SAME inode; an atomic re-install would swap it.
    assert path.stat().st_ino == inode_before


def test_install_or_verify_exact_different_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "durable.json"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(DurableLedgerError):
        install_or_verify_exact(path, "DIFFERENT")
    # The pre-existing file is never overwritten.
    assert path.read_text(encoding="utf-8") == "original"


# ---------------------------------------------------------------------------
# Part B: recover_phase2b_durable_outputs (spec §3.2).
# ---------------------------------------------------------------------------


def test_recover_from_pristine_run_dir_publishes(tmp_path: Path) -> None:
    """Recovery on a never-finalized run (1 terminal, no derived files, no marker)
    performs the §3.1 publish and installs the marker (opens NO seal)."""
    scenario = _build_scenario(tmp_path)
    result = recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])

    run_dir = scenario["run_dir"]
    assert (run_dir / REGISTERED_SUMMARY_FILENAME).is_file()
    assert (run_dir / FINAL_LEDGER_FILENAME).is_file()
    marker = json.loads((run_dir / DURABLE_COMMIT_FILENAME).read_text(encoding="utf-8"))
    core = {k: v for k, v in marker.items() if k != "commit_checksum"}
    assert sha256_json(core) == marker["commit_checksum"] == result.commit_checksum


def test_recover_marker_absent_after_summary_only_reproduces_marker(tmp_path: Path) -> None:
    """Crash boundary (a): the summary was written but neither the final ledger nor
    the marker. Recovery re-derives byte-identically and reproduces the SAME marker
    without reopening the seal; the surviving summary is verify-only."""
    scenario = _build_scenario(tmp_path)
    reference = _finalize(scenario)
    expected_marker = reference.commit_marker_path.read_bytes()
    expected_summary = reference.registered_summary_path.read_bytes()
    summary_inode = reference.registered_summary_path.stat().st_ino

    # Simulate the crash: keep the summary, drop the final ledger + marker.
    reference.final_ledger_path.unlink()
    reference.commit_marker_path.unlink()

    recovered = recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])

    assert recovered.commit_checksum == reference.commit_checksum
    assert recovered.commit_marker_path.read_bytes() == expected_marker
    # The surviving byte-identical summary is verified, never rewritten (same inode).
    assert recovered.registered_summary_path.read_bytes() == expected_summary
    assert recovered.registered_summary_path.stat().st_ino == summary_inode
    assert recovered.final_ledger_path.is_file()


def test_recover_marker_absent_after_final_ledger_reproduces_marker(tmp_path: Path) -> None:
    """Crash boundary (b): the summary + final ledger were written but not the
    marker. Recovery reproduces the SAME marker (the whole point of ordering it
    last)."""
    scenario = _build_scenario(tmp_path)
    reference = _finalize(scenario)
    expected_marker = reference.commit_marker_path.read_bytes()
    reference.commit_marker_path.unlink()

    recovered = recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])

    assert recovered.commit_marker_path.read_bytes() == expected_marker
    assert recovered.commit_checksum == reference.commit_checksum


def test_recover_mismatching_partial_summary_fails_closed(tmp_path: Path) -> None:
    """A surviving partial derived file whose bytes DIFFER from the re-derived
    intended bytes fails closed (install_or_verify_exact never overwrites)."""
    scenario = _build_scenario(tmp_path)
    reference = _finalize(scenario)
    reference.final_ledger_path.unlink()
    reference.commit_marker_path.unlink()
    # Corrupt the surviving summary so it no longer matches the re-derived bytes.
    reference.registered_summary_path.write_bytes(b'{"tampered":true}')

    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])


def test_recover_marker_present_is_verify_only(tmp_path: Path) -> None:
    """A present marker is verified only: nothing is rewritten (same inodes / bytes)."""
    scenario = _build_scenario(tmp_path)
    reference = _finalize(scenario)
    summary_inode = reference.registered_summary_path.stat().st_ino
    ledger_inode = reference.final_ledger_path.stat().st_ino
    marker_inode = reference.commit_marker_path.stat().st_ino
    marker_before = reference.commit_marker_path.read_bytes()

    recovered = recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])

    assert recovered.commit_checksum == reference.commit_checksum
    assert recovered.terminal_state == "COMPLETE"
    assert reference.registered_summary_path.stat().st_ino == summary_inode
    assert reference.final_ledger_path.stat().st_ino == ledger_inode
    assert reference.commit_marker_path.stat().st_ino == marker_inode
    assert reference.commit_marker_path.read_bytes() == marker_before


def test_recover_is_idempotent_across_repeats(tmp_path: Path) -> None:
    """Recovery is idempotent: the first call publishes (marker absent), the second
    verifies only (marker present) and never rewrites the marker."""
    scenario = _build_scenario(tmp_path)
    first = recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])
    marker_bytes = first.commit_marker_path.read_bytes()
    marker_inode = first.commit_marker_path.stat().st_ino

    second = recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])

    assert second.commit_checksum == first.commit_checksum
    assert first.commit_marker_path.read_bytes() == marker_bytes
    assert first.commit_marker_path.stat().st_ino == marker_inode


def test_recover_marker_present_tampered_derived_file_fails_closed(tmp_path: Path) -> None:
    """A tampered derived file under a present marker fails the verify-only path."""
    scenario = _build_scenario(tmp_path)
    reference = _finalize(scenario)
    # Tamper the final ledger AFTER the marker bound its SHA.
    reference.final_ledger_path.write_bytes(b'{"tampered":true}')

    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])


def test_recover_zero_terminals_fails_closed(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)
    scenario["terminal_path"].unlink()
    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])


def test_recover_two_terminals_fails_closed(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)
    run_dir = scenario["run_dir"]
    # A second roster-named terminal (regular file) -> exactly-one scan fails.
    (run_dir / Phase2bTerminal.INVALID_ARTIFACT).write_bytes(scenario["terminal_path"].read_bytes())
    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=run_dir)


def test_recover_malformed_aborted_terminal_fails_closed(tmp_path: Path) -> None:
    """A MALFORMED aborted terminal (a bare ``{"terminal_state": ...}`` body, not a
    real v2 abort artifact) fails closed: reduced-abort recovery (Task 6B) still
    runs the FULL terminal verification (canonical JSON, exact roster, run id and
    the shared payload-checksum), so a bogus abort body is rejected."""
    scenario = _build_scenario(tmp_path)
    run_dir = scenario["run_dir"]
    scenario["terminal_path"].unlink()
    (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).write_text(
        json.dumps({"terminal_state": "ABORTED_AFTER_SEAL"}, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=run_dir)


# ---------------------------------------------------------------------------
# Task 6B: reduced-abort forward publish + recovery (spec §3.3). An
# ABORTED_AFTER_SEAL terminal has NO registered_summary and NO embedded
# provenance; the reduced publish derives provenance from the pre-access ledger
# snapshot and installs a marker whose field set omits every summary field.
# ---------------------------------------------------------------------------


def test_finalize_publishes_aborted_terminal_reduced_set(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path, state="ABORTED")
    result = _finalize(scenario)

    assert isinstance(result, DurableFinalizeResult)
    assert result.terminal_state == "ABORTED_AFTER_SEAL"
    # No registered summary on the abort path.
    assert result.registered_summary_path is None

    run_dir = scenario["run_dir"]
    summary_path = run_dir / REGISTERED_SUMMARY_FILENAME
    final_ledger_path = run_dir / FINAL_LEDGER_FILENAME
    marker_path = run_dir / DURABLE_COMMIT_FILENAME

    # The reduced set: NO registered summary artifact; final ledger + marker present.
    assert not summary_path.exists()
    assert final_ledger_path.is_file()
    assert marker_path.is_file()
    assert result.final_ledger_path == final_ledger_path
    assert result.commit_marker_path == marker_path

    # The final ledger binds {terminal, seed} file SHAs ONLY (no summary entry).
    final_ledger = RunLedger.read(final_ledger_path)
    names = {rec["name"] for rec in final_ledger.to_dict()["artifacts"]}
    assert Phase2bTerminal.ABORTED_ARTIFACT in names
    assert DEVELOPMENT_SEED_VARIABILITY_FILENAME in names
    assert REGISTERED_SUMMARY_FILENAME not in names
    assert FINAL_LEDGER_FILENAME not in names
    assert DURABLE_COMMIT_FILENAME not in names
    assert final_ledger.artifact_sha(Phase2bTerminal.ABORTED_ARTIFACT) == _file_sha(
        scenario["terminal_path"]
    )
    assert final_ledger.artifact_sha(DEVELOPMENT_SEED_VARIABILITY_FILENAME) == _file_sha(
        scenario["seed_path"]
    )

    # The marker: ABORTED state, NO registered_summary field, binds every present
    # file SHA + the seed self-checksum, and its self-checksum recomputes.
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["terminal_state"] == "ABORTED_AFTER_SEAL"
    assert marker["run_id"] == _RUN_ID
    assert "registered_summary" not in marker
    assert marker["terminal"]["filename"] == Phase2bTerminal.ABORTED_ARTIFACT
    assert marker["terminal"]["sha256"] == _file_sha(scenario["terminal_path"])
    # marker last: it binds the on-disk final ledger SHA.
    assert marker["final_ledger"]["sha256"] == _file_sha(final_ledger_path)
    assert marker["pre_access_ledger"]["sha256"] == _file_sha(scenario["pre_access_path"])
    assert marker["seed_variability"]["sha256"] == _file_sha(scenario["seed_path"])
    assert marker["seed_variability"]["self_checksum"] == scenario["seed_report_checksum"]
    core = {k: v for k, v in marker.items() if k != "commit_checksum"}
    assert sha256_json(core) == marker["commit_checksum"] == result.commit_checksum


def test_aborted_published_final_ledger_has_no_per_pair_ci(tmp_path: Path) -> None:
    """The abort reduced set never introduces a per-pair CI / raw array (there is no
    summary to publish at all)."""
    scenario = _build_scenario(tmp_path, state="ABORTED")
    result = _finalize(scenario)
    assert result.registered_summary_path is None
    marker = json.loads(result.commit_marker_path.read_text(encoding="utf-8"))

    def _walk(obj: object) -> None:
        if isinstance(obj, dict):
            for value in obj.values():
                _walk(value)
        elif isinstance(obj, list):
            assert len(obj) <= 8, "unexpectedly long array in abort marker"
            for item in obj:
                assert not isinstance(item, list), "nested list forbidden"
                _walk(item)

    _walk(marker)


def test_finalize_aborted_is_idempotent_noop(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path, state="ABORTED")
    first = _finalize(scenario)
    ledger_before = first.final_ledger_path.read_bytes()
    marker_before = first.commit_marker_path.read_bytes()

    second = _finalize(scenario)

    assert second.commit_checksum == first.commit_checksum
    assert second.registered_summary_path is None
    assert first.final_ledger_path.read_bytes() == ledger_before
    assert first.commit_marker_path.read_bytes() == marker_before


def test_recover_aborted_marker_absent_reproduces_marker(tmp_path: Path) -> None:
    """Crash boundary: the final ledger was written but not the marker. Reduced-abort
    recovery re-derives byte-identically and reproduces the SAME marker without
    reopening the seal."""
    scenario = _build_scenario(tmp_path, state="ABORTED")
    reference = _finalize(scenario)
    expected_marker = reference.commit_marker_path.read_bytes()
    reference.commit_marker_path.unlink()

    recovered = recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])

    assert recovered.terminal_state == "ABORTED_AFTER_SEAL"
    assert recovered.registered_summary_path is None
    assert recovered.commit_checksum == reference.commit_checksum
    assert recovered.commit_marker_path.read_bytes() == expected_marker


def test_recover_aborted_pristine_run_dir_publishes(tmp_path: Path) -> None:
    """Recovery on a never-finalized abort run (1 abort terminal, no derived files)
    performs the reduced publish and installs the marker (opens NO seal)."""
    scenario = _build_scenario(tmp_path, state="ABORTED")
    result = recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])

    run_dir = scenario["run_dir"]
    assert result.terminal_state == "ABORTED_AFTER_SEAL"
    assert result.registered_summary_path is None
    assert not (run_dir / REGISTERED_SUMMARY_FILENAME).exists()
    assert (run_dir / FINAL_LEDGER_FILENAME).is_file()
    marker = json.loads((run_dir / DURABLE_COMMIT_FILENAME).read_text(encoding="utf-8"))
    assert "registered_summary" not in marker
    core = {k: v for k, v in marker.items() if k != "commit_checksum"}
    assert sha256_json(core) == marker["commit_checksum"] == result.commit_checksum


def test_recover_aborted_marker_present_is_verify_only(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path, state="ABORTED")
    reference = _finalize(scenario)
    ledger_inode = reference.final_ledger_path.stat().st_ino
    marker_inode = reference.commit_marker_path.stat().st_ino
    marker_before = reference.commit_marker_path.read_bytes()

    recovered = recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])

    assert recovered.terminal_state == "ABORTED_AFTER_SEAL"
    assert recovered.registered_summary_path is None
    assert recovered.commit_checksum == reference.commit_checksum
    assert reference.final_ledger_path.stat().st_ino == ledger_inode
    assert reference.commit_marker_path.stat().st_ino == marker_inode
    assert reference.commit_marker_path.read_bytes() == marker_before


def test_recover_aborted_marker_present_tampered_seed_fails_closed(tmp_path: Path) -> None:
    """A tampered seed report under a present abort marker fails closed (the
    unconditional seed cross-check applies to the abort path too)."""
    scenario = _build_scenario(tmp_path, state="ABORTED")
    _finalize(scenario)
    scenario["seed_path"].write_text(
        json.dumps({"schema": "x", "report_checksum": "z"}, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])


def test_recover_aborted_marker_present_tampered_final_ledger_fails_closed(tmp_path: Path) -> None:
    """A tampered final ledger under a present abort marker fails the verify-only
    path (the marker bound its SHA)."""
    scenario = _build_scenario(tmp_path, state="ABORTED")
    reference = _finalize(scenario)
    reference.final_ledger_path.write_bytes(b'{"tampered":true}')
    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])


# ---------------------------------------------------------------------------
# Seed-variability cross-check (spec §3.2:199-200) + M1 self-checksum hardening.
# ---------------------------------------------------------------------------


def test_recover_seed_absent_fails_closed(tmp_path: Path) -> None:
    """A pre-access ledger that claims a seed digest whose file is ABSENT fails
    closed (no marker), even with the marker already present."""
    scenario = _build_scenario(tmp_path)
    _finalize(scenario)
    scenario["seed_path"].unlink()
    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])


def test_recover_seed_bytes_differ_fails_closed(tmp_path: Path) -> None:
    """A seed report whose bytes DIFFER from the pre-access ledger digest fails
    closed (unconditional cross-check), even with the marker already present."""
    scenario = _build_scenario(tmp_path)
    _finalize(scenario)
    scenario["seed_path"].write_text(
        json.dumps({"schema": "x", "report_checksum": "z"}, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])


def test_finalize_rejects_seed_self_checksum_mismatch(tmp_path: Path) -> None:
    """M1: a seed report whose report_checksum != sha256_json(payload_without_checksum)
    fails the forward publish even though its byte SHA still matches the pre-access
    ledger digest."""
    scenario = _build_scenario(tmp_path, break_seed_self_checksum=True)
    with pytest.raises(DurableLedgerError):
        _finalize(scenario)


def test_recover_rejects_seed_self_checksum_mismatch(tmp_path: Path) -> None:
    """M1: the seed self-checksum is validated unconditionally in recovery."""
    scenario = _build_scenario(tmp_path, break_seed_self_checksum=True)
    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=scenario["run_dir"])


# ---------------------------------------------------------------------------
# Task 7 (C0 #5): recover synthesizes the missing ABORTED_AFTER_SEAL terminal
# for the audit=1 / terminal=0 post-crash state via the recovery-sanctioned
# Phase2bTerminal.recover_aborted_after_seal, then finalizes the reduced abort
# publish. A hard process death AFTER claim_sealed_access burns the durable
# audit but may land before any terminal is written; recover must record the
# already-consumed seal. Reuses the module's pre-access-ledger / seed-report
# builders; the burned audit lives at the PRODUCTION location run_dir/audit.jsonl.
# ---------------------------------------------------------------------------


def _write_burned_audit(run_dir: Path, *, records: int = 1) -> Path:
    """Write a burned seal audit at run_dir/audit.jsonl (the production location)."""
    audit_path = run_dir / "audit.jsonl"
    lines = "".join(
        json.dumps(
            {"run_id": _RUN_ID, "pair_ids": [], "seq": i}, sort_keys=True, separators=(",", ":")
        )
        + "\n"
        for i in range(records)
    )
    audit_path.write_text(lines, encoding="utf-8")
    return audit_path


def _build_audit_only_scenario(tmp_path: Path, *, audit_records: int = 1) -> dict:
    """A run_dir with a burned audit + pre-access ledger + seed report + ZERO terminals.

    Exactly the audit=1 / terminal=0 post-crash state. When ``audit_records == 0`` no
    audit file is written (the no-seal-consumed fail-closed case).
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    provenance = _provenance()
    seed_path, seed_byte_sha, seed_report_checksum = _write_seed_variability(run_dir)
    pre_access_path = _persist_pre_access_ledger(
        run_dir, provenance=provenance, seed_byte_sha=seed_byte_sha
    )
    if audit_records > 0:
        _write_burned_audit(run_dir, records=audit_records)
    return {
        "run_dir": run_dir,
        "pre_access_path": pre_access_path,
        "seed_path": seed_path,
        "seed_report_checksum": seed_report_checksum,
        "provenance": provenance,
    }


def test_recover_synthesizes_aborted_from_audit_only(tmp_path: Path) -> None:
    """audit=1 / terminal=0: recover synthesizes the missing ABORTED_AFTER_SEAL terminal
    (recording the consumed seal) and publishes the reduced durable set + commit marker,
    opening NO seal."""
    scenario = _build_audit_only_scenario(tmp_path, audit_records=1)
    run_dir = scenario["run_dir"]
    assert not (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).exists()

    result = recover_phase2b_durable_outputs(run_dir=run_dir)

    assert result.terminal_state == "ABORTED_AFTER_SEAL"
    assert result.registered_summary_path is None

    aborted_path = run_dir / Phase2bTerminal.ABORTED_ARTIFACT
    assert aborted_path.is_file()
    assert not (run_dir / REGISTERED_SUMMARY_FILENAME).exists()
    assert (run_dir / FINAL_LEDGER_FILENAME).is_file()
    marker_path = run_dir / DURABLE_COMMIT_FILENAME
    assert marker_path.is_file()

    # The synthesized terminal records the already-consumed seal.
    body = json.loads(aborted_path.read_text(encoding="utf-8"))
    assert body["terminal_state"] == "ABORTED_AFTER_SEAL"
    assert body["sealed_access_count"] >= 1
    assert body["seal_audit_reference"]  # non-empty, derived from the burned audit
    assert body["audit_reference"] == body["seal_audit_reference"]
    assert body["registered_results_status"] == "NOT_AVAILABLE_DUE_TO_ABORT"
    assert body["protocol"] == _PROTOCOL
    assert body["run_id"] == _RUN_ID

    # The reduced marker: ABORTED, NO registered_summary, self-checksum recomputes,
    # binds the on-disk final ledger + pre-access + seed SHAs.
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["terminal_state"] == "ABORTED_AFTER_SEAL"
    assert "registered_summary" not in marker
    assert marker["terminal"]["filename"] == Phase2bTerminal.ABORTED_ARTIFACT
    assert marker["terminal"]["sha256"] == _file_sha(aborted_path)
    assert marker["final_ledger"]["sha256"] == _file_sha(result.final_ledger_path)
    assert marker["pre_access_ledger"]["sha256"] == _file_sha(scenario["pre_access_path"])
    assert marker["seed_variability"]["sha256"] == _file_sha(scenario["seed_path"])
    core = {k: v for k, v in marker.items() if k != "commit_checksum"}
    assert sha256_json(core) == marker["commit_checksum"] == result.commit_checksum


def test_recover_synthesizes_from_external_protocol_audit(tmp_path: Path) -> None:
    scenario = _build_audit_only_scenario(tmp_path, audit_records=1)
    run_dir = scenario["run_dir"]
    external_audit = tmp_path / ".compose-protocol-seal-test.jsonl"
    (run_dir / "audit.jsonl").replace(external_audit)

    result = recover_phase2b_durable_outputs(
        run_dir=run_dir,
        audit_path=external_audit,
    )

    assert result.terminal_state == "ABORTED_AFTER_SEAL"
    body = json.loads((run_dir / Phase2bTerminal.ABORTED_ARTIFACT).read_text(encoding="utf-8"))
    assert body["run_id"] == _RUN_ID
    assert body["sealed_access_count"] == 1


def test_recover_external_audit_run_id_mismatch_fails_closed(tmp_path: Path) -> None:
    scenario = _build_audit_only_scenario(tmp_path, audit_records=1)
    run_dir = scenario["run_dir"]
    external_audit = tmp_path / ".compose-protocol-seal-test.jsonl"
    record = json.loads((run_dir / "audit.jsonl").read_text(encoding="utf-8"))
    record["run_id"] = "wrong-run"
    external_audit.write_text(
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (run_dir / "audit.jsonl").unlink()

    with pytest.raises(DurableLedgerError, match="audit run_id"):
        recover_phase2b_durable_outputs(
            run_dir=run_dir,
            audit_path=external_audit,
        )

    assert not (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).exists()


def test_recover_aborted_from_audit_only_is_byte_identical_idempotent(tmp_path: Path) -> None:
    """A second recover sees the now-1-terminal + marker → verify-only: the synthesized
    terminal, the final ledger and the marker are byte-identical and never rewritten."""
    scenario = _build_audit_only_scenario(tmp_path, audit_records=1)
    run_dir = scenario["run_dir"]

    first = recover_phase2b_durable_outputs(run_dir=run_dir)
    aborted_path = run_dir / Phase2bTerminal.ABORTED_ARTIFACT
    aborted_bytes = aborted_path.read_bytes()
    aborted_inode = aborted_path.stat().st_ino
    ledger_bytes = first.final_ledger_path.read_bytes()
    ledger_inode = first.final_ledger_path.stat().st_ino
    marker_bytes = first.commit_marker_path.read_bytes()
    marker_inode = first.commit_marker_path.stat().st_ino

    second = recover_phase2b_durable_outputs(run_dir=run_dir)

    assert second.terminal_state == "ABORTED_AFTER_SEAL"
    assert second.registered_summary_path is None
    assert second.commit_checksum == first.commit_checksum
    # Nothing rewritten: identical bytes AND identical inodes across the board.
    assert aborted_path.read_bytes() == aborted_bytes
    assert aborted_path.stat().st_ino == aborted_inode
    assert first.final_ledger_path.read_bytes() == ledger_bytes
    assert first.final_ledger_path.stat().st_ino == ledger_inode
    assert first.commit_marker_path.read_bytes() == marker_bytes
    assert first.commit_marker_path.stat().st_ino == marker_inode


def test_recover_still_fails_closed_with_no_audit_and_no_terminal(tmp_path: Path) -> None:
    """Pre-access ledger + seed present, but the burned audit has 0 records AND there are
    0 terminals: the seal was never consumed, so recover fails closed (no synthesized
    terminal, no marker) rather than fabricating an ABORTED_AFTER_SEAL."""
    scenario = _build_audit_only_scenario(tmp_path, audit_records=0)
    run_dir = scenario["run_dir"]
    assert not (run_dir / "audit.jsonl").exists()
    assert not (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).exists()

    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=run_dir)

    # Fail closed: nothing synthesized, no durable marker.
    assert not (run_dir / Phase2bTerminal.ABORTED_ARTIFACT).exists()
    assert not (run_dir / DURABLE_COMMIT_FILENAME).exists()
