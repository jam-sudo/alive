"""Tests for the ``phase2a`` subcommand orchestration (spec §3.1 / §7.1).

Written FIRST per TDD. The ``phase2a`` subcommand assembles the in-memory
development objects (``Phase2aInputs`` + a non-sealed ``DevelopmentOutcomeStore``
+ the ``{gears, cpa}`` subprocess ``BaselineAdapter``s), dispatches the library
entry point (``run_phase2a_fixture`` for the committed fixture), and — on
``CONTINUE`` — persists exactly the four pre-seal artifacts write-once with the
run ledger installed LAST. These tests exercise the REAL objects end-to-end (no
mocks) except a single spy asserting a ``ComposeOutcomeStore`` is NEVER
constructed on the phase2a code path (§4 single-creation-point invariant).

Coverage:

  1. ``CONTINUE`` → returns 0; run_dir holds EXACTLY the four CONTINUE artifacts
     (frozen bundle, OOF manifest, the DISTINCT-path seed-variability report, and
     the run ledger); the re-read ledger carries the four driver-added artifact
     SHAs (``resolved_run_spec`` file SHA, runtime ``execution_id``, pair-index
     file SHA, phase2a seed-report file SHA); NO ``ComposeOutcomeStore`` built.
  2. the run-dir entry roster is asserted BEFORE the entry call (a non-empty
     run_dir fails closed before any fit).
  3. ``FUTILITY_STOPPED`` → the persistence helper writes ONLY
     ``phase2a_futility.json`` (schema ``compose_phase2a_futility_v2``) and
     returns 20 — no bundle / ledger / seal artifacts. NOTE: the committed
     ``build_compose_fixture`` corpus is CONTINUE-only (full-rank, measurable,
     no futility knob), so this exercises the futility branch with a REAL
     ``Phase2aResult`` (real ``FutilityResult`` / ``RankReport`` / ``GateResult``
     dataclasses) rather than a futility-forcing fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import alive.compose.outcome_store as outcome_store_mod
from alive.compose.diagnostics2 import FutilityResult
from alive.compose.driver.fixture_builder import build_compose_fixture
from alive.compose.driver.phase2a_cmd import (
    FUTILITY_REPORT_SCHEMA,
    Phase2aSubcommandError,
    _persist_futility_report,
    run_phase2a_subcommand,
)
from alive.compose.driver.run_dir_state import RunDirStateError
from alive.compose.driver.run_spec import (
    compute_execution_id,
    load_resolved_run_spec,
)
from alive.compose.gates import GateResult
from alive.compose.identify import RankReport
from alive.compose.phase2a import Phase2aResult
from alive.provenance import RunLedger, sha256_file

_CONTINUE_ARTIFACTS = (
    "frozen_prediction_bundle.json",
    "oof_fold_manifest.json",
    "phase2a_development_seed_variability.json",
    "phase2a_run_ledger.json",
)


def _forbid_compose_outcome_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spy: fail closed if the phase2a code path ever constructs a sealed store."""

    def _boom(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError(
            "ComposeOutcomeStore must NOT be constructed on the phase2a code path (spec §4)"
        )

    monkeypatch.setattr(outcome_store_mod.ComposeOutcomeStore, "__init__", _boom)


# --------------------------------------------------------------------------- #
# Contract 1: CONTINUE — exactly four artifacts, driver-added ledger SHAs
# --------------------------------------------------------------------------- #
def test_continue_installs_exactly_four_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = build_compose_fixture(tmp_path)
    _forbid_compose_outcome_store(monkeypatch)

    rc = run_phase2a_subcommand(bundle, approved_artifacts_root=tmp_path, run_dir=bundle.run_dir)
    assert rc == 0

    present = sorted(p.name for p in bundle.run_dir.iterdir())
    assert present == sorted(_CONTINUE_ARTIFACTS)
    # the seed-variability report is on the DISTINCT path, never the canonical
    # phase2b name (write-once collision otherwise).
    assert not (bundle.run_dir / "development_seed_variability.json").exists()


def test_continue_seed_variability_report_is_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The REAL D2 ``development_seed_variability`` over the committed fixture is
    ``COMPLETE`` — the phase2b-fixture / mini-e2e prerequisite (T9/T13).

    The fixture fit-role carries one ``combo_calibration`` cell per calibration
    pair, so every ``(method, seed, fold)`` job's fold-scoped fit-role artifact
    (restricted to that fold's TRAIN pairs) retains combo cells and the reference
    worker fits — no seed fails, so the written report is ``COMPLETE`` (a short
    combo slice left most folds with zero combo cells → BaselineUnavailable per
    seed → INCOMPLETE, which ``verify_seed_variability_binding_bounded`` rejects).
    """
    bundle = build_compose_fixture(tmp_path)
    _forbid_compose_outcome_store(monkeypatch)

    rc = run_phase2a_subcommand(bundle, approved_artifacts_root=tmp_path, run_dir=bundle.run_dir)
    assert rc == 0

    report = json.loads((bundle.run_dir / "phase2a_development_seed_variability.json").read_text())
    assert report["status"] == "COMPLETE"
    assert report["registered_seeds"] == [11, 23, 37]
    # every seed-refittable comparator produced a finite OOF scalar for every seed.
    assert {s["method"] for s in report["summaries"]} == {"gears", "cpa"}
    for summary in report["summaries"]:
        assert summary["failed_seeds"] == []
        assert summary["failure_class_by_seed"] == []
        # every registered seed contributed a finite OOF scalar (none dropped).
        seeds_scored = [seed for seed, _ in summary["oof_mse_by_seed"]]
        assert seeds_scored == [11, 23, 37]
        assert all(np.isfinite(value) for _, value in summary["oof_mse_by_seed"])


def test_continue_ledger_carries_driver_added_shas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = build_compose_fixture(tmp_path)
    _forbid_compose_outcome_store(monkeypatch)

    rc = run_phase2a_subcommand(bundle, approved_artifacts_root=tmp_path, run_dir=bundle.run_dir)
    assert rc == 0

    ledger = RunLedger.read(bundle.run_dir / "phase2a_run_ledger.json")
    spec = load_resolved_run_spec(
        bundle.spec_path, approved_artifacts_root=tmp_path, mode_expected="fixture"
    )
    # 1. resolved_run_spec file SHA
    assert ledger.artifact_sha("resolved_run_spec") == spec.file_sha256
    # 2. runtime execution_id (not stored in the spec; recomputed here)
    assert ledger.artifact_sha("execution_id") == compute_execution_id(
        run_id=spec.run_id,
        resolved_run_spec_file_sha256=spec.file_sha256,
        approved_git_sha=spec.approved_git_sha,
    )
    # 3. pair-index manifest file SHA (the declared+verified pre-seal digest)
    assert ledger.artifact_sha("pair_index_manifest") == spec.pre_seal["pair_index_manifest"].sha256
    # 4. phase2a seed-report file SHA (the DISTINCT-path report's byte SHA)
    seed_report = bundle.run_dir / "phase2a_development_seed_variability.json"
    assert ledger.artifact_sha("phase2a_seed_variability_report") == sha256_file(seed_report)
    # ledger header identity mirrors the run/config identity.
    assert ledger.to_dict()["run_id"] == spec.run_id


# --------------------------------------------------------------------------- #
# Contract 2: the run-dir entry roster is asserted BEFORE the entry call
# --------------------------------------------------------------------------- #
def test_nonempty_run_dir_fails_closed_before_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = build_compose_fixture(tmp_path)
    _forbid_compose_outcome_store(monkeypatch)
    # a stray run-produced artifact already present -> entry roster fails closed.
    (bundle.run_dir / "frozen_prediction_bundle.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RunDirStateError):
        run_phase2a_subcommand(bundle, approved_artifacts_root=tmp_path, run_dir=bundle.run_dir)


# --------------------------------------------------------------------------- #
# Contract 3: FUTILITY_STOPPED — only the futility report, return 20
# --------------------------------------------------------------------------- #
def _real_futility_result() -> Phase2aResult:
    """A REAL FUTILITY_STOPPED result (production dataclasses, no mocks)."""
    futility = FutilityResult(
        status="FUTILITY_STOPPED",
        sealed_access_count=0,
        rank_report=RankReport(
            sym_dim=10, rank=6, is_full_rank=False, condition_number=float("inf")
        ),
        singular_values=np.array([1.0, 0.5, 0.0]),
        rank_tolerance=1.0e-8,
        measurability=GateResult(
            name="measurability", passed=False, detail={}, recommendation="stop"
        ),
        oof_theta=0.9,
        selected_k_total=4,
        selected_lambda=1.0e-3,
        oof_manifest=None,
        failures=("rank_deficient",),
        nonviable_candidates=((4, 0.0, "OOF train fold 0: non-identifiable"),),
    )
    return Phase2aResult(
        futility_status="FUTILITY_STOPPED",
        sealed_access_count=0,
        bundle=None,
        futility=futility,
        selected_k_total=4,
        selected_lambda=1.0e-3,
        ledger=None,
        method_lock=None,
        oof_manifest=None,
    )


def test_futility_report_refuses_a_non_finite_value(tmp_path: Path) -> None:
    """A non-finite value must fail typed, not as a bare ValueError.

    ``allow_nan=False`` rejects it while ``sha256_json`` does not, so an
    unhandled one would escape the driver's exit-code contract and leave no
    report at all.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result = _real_futility_result()
    object.__setattr__(result.futility, "oof_theta", float("inf"))

    with pytest.raises(Phase2aSubcommandError, match="not strictly serializable"):
        _persist_futility_report(run_dir, run_id="fixture-run-id", result=result)
    assert sorted(p.name for p in run_dir.iterdir()) == []


def test_futility_writes_only_the_futility_report(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result = _real_futility_result()

    rc = _persist_futility_report(run_dir, run_id="fixture-run-id", result=result)

    assert rc == 20
    present = sorted(p.name for p in run_dir.iterdir())
    assert present == ["phase2a_futility.json"]
    body = json.loads((run_dir / "phase2a_futility.json").read_text())
    assert body["schema"] == FUTILITY_REPORT_SCHEMA
    assert body["futility_status"] == "FUTILITY_STOPPED"
    assert body["run_id"] == "fixture-run-id"
    assert body["sealed_access_count"] == 0
    assert body["is_full_rank"] is False
    assert body["condition_number"] is None
    assert body["condition_number_is_finite"] is False
    assert body["nonviable_candidates"] == [
        {
            "k_total": 4,
            "lambda": 0.0,
            "reason": "OOF train fold 0: non-identifiable",
        }
    ]
    assert "Infinity" not in (run_dir / "phase2a_futility.json").read_text()
    # self-checksum excludes itself.
    from alive.provenance import sha256_json

    recomputed = sha256_json({k: v for k, v in body.items() if k != "self_checksum"})
    assert body["self_checksum"] == recomputed
