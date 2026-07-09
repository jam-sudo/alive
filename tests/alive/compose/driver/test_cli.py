"""Tests for the ``main(argv)`` CLI entry point (spec §1.1 / Task 11).

Written FIRST per TDD. ``main`` is the single committed CLI entrypoint that
argparse-dispatches to the four already-committed subcommand functions (Tasks
7-10) and maps their results/exceptions to process exit codes. It opens NO
seal and constructs NO :class:`~alive.compose.outcome_store.ComposeOutcomeStore`
itself — it only parses args, builds the run_spec carrier (validating via
``load_resolved_run_spec`` first — a fail-closed pre-seal gate), calls a
subcommand, and maps the outcome to an exit code.

These tests drive the REAL fixture chain via ``main([...])`` (no mocks) except
a single monkeypatch forcing the ``phase2a`` FUTILITY_STOPPED branch — the
SAME technique ``test_phase2a_cmd.py`` uses directly against
``run_phase2a_subcommand``, since the committed fixture corpus
(``build_compose_fixture``) is CONTINUE-only (no futility knob).

``main``'s own carrier construction calls ``build_compose_fixture`` exactly
once (spec §1.1 / ``cli.py`` module docstring: write-once fit-role artifact, so
it cannot be called twice on the same ``--approved-artifacts-root``). Tests
that need a WORKING carrier therefore learn ``build_compose_fixture``'s
deterministic ``spec_path``/``run_dir`` naming via ``_fixture_cli_args`` (one
THROWAWAY build, immediately wiped) rather than pre-building a bundle
``main()`` would then collide with.

Coverage (the four brief scenarios):

  1. ``phase2a`` on the fixture spec -> 0;
  2. a pre-seal validation failure (``--run-spec`` pointing at a file that was
     never written, which the CLI's own ``_peek_mode`` rejects as a
     ``RunSpecError`` before any carrier is built) -> 10, with stderr carrying
     the exception class name + the subcommand stage, and NO outcome value on
     stdout;
  3. a futility fixture via ``phase2a`` (forced by monkeypatching
     ``run_phase2a_fixture``) -> 20;
  4. an unknown subcommand -> argparse's own error (``SystemExit(2)``).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from alive.compose.diagnostics2 import FutilityResult
from alive.compose.driver.cli import main
from alive.compose.driver.fixture_builder import build_compose_fixture
from alive.compose.gates import GateResult
from alive.compose.identify import RankReport
from alive.compose.phase2a import Phase2aResult


def _fixture_cli_args(tmp_path: Path) -> tuple[str, str, str]:
    """Learn ``build_compose_fixture``'s deterministic paths, then wipe them.

    ``build_compose_fixture`` writes a write-once fit-role ``.h5ad`` (spec
    §2.1), so it cannot be called twice on the same root — and ``main()``'s
    own carrier construction IS the one real build per test. This throwaway
    call only harvests the deterministic ``spec_path``/``run_dir`` naming
    (never hardcoded here), then removes everything so ``main()`` starts from
    a clean, empty ``--approved-artifacts-root``.
    """
    bundle = build_compose_fixture(tmp_path)
    spec_path = str(bundle.spec_path)
    approved_root = str(bundle.approved_artifacts_root)
    run_dir = str(bundle.run_dir)
    shutil.rmtree(bundle.approved_artifacts_root)
    return spec_path, approved_root, run_dir


def _real_futility_result() -> Phase2aResult:
    """A REAL FUTILITY_STOPPED result (production dataclasses, no mocks).

    Mirrors ``test_phase2a_cmd.py``'s ``_real_futility_result`` helper exactly
    (the committed fixture corpus never produces FUTILITY_STOPPED on its own).
    """
    futility = FutilityResult(
        status="FUTILITY_STOPPED",
        sealed_access_count=0,
        rank_report=RankReport(sym_dim=10, rank=6, is_full_rank=False, condition_number=1.0e6),
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


# --------------------------------------------------------------------------- #
# Scenario 1: phase2a on the fixture spec -> 0
# --------------------------------------------------------------------------- #
def test_phase2a_on_fixture_spec_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    spec_path, approved_root, run_dir = _fixture_cli_args(tmp_path)

    rc = main(
        [
            "phase2a",
            "--run-spec",
            spec_path,
            "--approved-artifacts-root",
            approved_root,
            "--run-dir",
            run_dir,
        ]
    )

    assert rc == 0
    present = sorted(p.name for p in Path(run_dir).iterdir())
    assert present == sorted(
        [
            "frozen_prediction_bundle.json",
            "oof_fold_manifest.json",
            "phase2a_development_seed_variability.json",
            "phase2a_run_ledger.json",
        ]
    )
    captured = capsys.readouterr()
    assert captured.out == ""


# --------------------------------------------------------------------------- #
# Scenario 2: a pre-seal validation failure -> 10, stderr diagnostic, no stdout
# --------------------------------------------------------------------------- #
def test_preseal_validation_failure_returns_ten(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    # NOT "resolved_run_spec.json" — build_compose_fixture's own carrier
    # construction (main()'s first internal step) writes exactly that name, so
    # a deliberately different, never-written filename is what actually
    # exercises the CLI's --run-spec validation gate (step 2/3) rather than a
    # write-once collision (step 1).
    never_written_spec = root / "not-the-real-spec.json"
    run_dir = root / "run"

    rc = main(
        [
            "phase2a",
            "--run-spec",
            str(never_written_spec),
            "--approved-artifacts-root",
            str(root),
            "--run-dir",
            str(run_dir),
        ]
    )

    assert rc == 10
    captured = capsys.readouterr()
    assert captured.out == ""  # NO outcome value on stdout
    assert "phase2a: RunSpecError:" in captured.err


# --------------------------------------------------------------------------- #
# Scenario 3: a futility fixture via phase2a -> 20
# --------------------------------------------------------------------------- #
def test_futility_via_phase2a_returns_twenty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    spec_path, approved_root, run_dir = _fixture_cli_args(tmp_path)
    monkeypatch.setattr(
        "alive.compose.driver.phase2a_cmd.run_phase2a_fixture",
        lambda *args, **kwargs: _real_futility_result(),
    )

    rc = main(
        [
            "phase2a",
            "--run-spec",
            spec_path,
            "--approved-artifacts-root",
            approved_root,
            "--run-dir",
            run_dir,
        ]
    )

    assert rc == 20
    present = sorted(p.name for p in Path(run_dir).iterdir())
    assert present == ["phase2a_futility.json"]
    captured = capsys.readouterr()
    assert captured.out == ""


# --------------------------------------------------------------------------- #
# Scenario 4: unknown subcommand -> argparse error (SystemExit code 2)
# --------------------------------------------------------------------------- #
def test_unknown_subcommand_raises_systemexit_two(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["not-a-real-subcommand"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""


def test_missing_required_flag_raises_systemexit_two() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["phase2a", "--run-spec", "/tmp/x"])

    assert exc_info.value.code == 2


# --------------------------------------------------------------------------- #
# recover: argparse wiring dispatches with only --run-dir (no run-spec flags)
# --------------------------------------------------------------------------- #
def test_recover_dispatches_with_run_dir_only_and_maps_library_result(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """``recover`` takes no ``--run-spec``; an empty ``run_dir`` fails the
    ``recover`` roster (``RunDirStateError``, one of the KNOWN pre-seal
    rejections) -> 10, proving argparse wired ``--run-dir`` through to
    ``run_recover_subcommand`` rather than silently no-op'ing."""
    empty_run_dir = tmp_path / "run"
    empty_run_dir.mkdir()

    rc = main(["recover", "--run-dir", str(empty_run_dir)])

    assert rc == 10
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "recover: RunDirStateError:" in captured.err


# --------------------------------------------------------------------------- #
# Known limitation (pinned, not silently worked around — see cli.py module
# docstring "KNOWN LIMITATION"): main()'s carrier construction re-invokes
# build_compose_fixture on every call, so a SECOND subcommand call against the
# SAME --approved-artifacts-root (the canonical phase2a -> preflight -> phase2b
# process-per-stage sequence) currently fails with an uncaught, unmapped
# FitRoleArtifactError rather than dispatching to preflight. This test pins
# that exact behaviour so a future carrier-loader fix must consciously update
# it rather than silently leaving a stale assumption in place.
# --------------------------------------------------------------------------- #
def test_second_call_against_same_root_currently_fails_closed_uncaught(
    tmp_path: Path,
) -> None:
    from alive.compose.fit_role import FitRoleArtifactError

    spec_path, approved_root, run_dir = _fixture_cli_args(tmp_path)
    rc = main(
        [
            "phase2a",
            "--run-spec",
            spec_path,
            "--approved-artifacts-root",
            approved_root,
            "--run-dir",
            run_dir,
        ]
    )
    assert rc == 0

    with pytest.raises(FitRoleArtifactError):
        main(
            [
                "preflight",
                "--run-spec",
                spec_path,
                "--approved-artifacts-root",
                approved_root,
                "--run-dir",
                run_dir,
            ]
        )
