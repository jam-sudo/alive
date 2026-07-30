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

Since Task 11.5, ``main()`` LOADS the carrier from the ResolvedRunSpec's on-disk
stage-1 artifacts (via ``load_run_spec_carrier``) — it NEVER rebuilds the corpus.
The corpus is therefore produced ONCE up-front by ``_fixture_cli_args`` (a single
``build_compose_fixture`` call, LEFT in place) and every ``main()`` call reads it,
so independent CLI processes can share ONE ``--run-spec`` / ``--run-dir`` (the spec
§11 three-independent-process e2e).

Coverage:

  1. ``phase2a`` on the fixture spec -> 0;
  2. a pre-seal validation failure (``--run-spec`` pointing at a file that was
     never written, which the loader's ``_peek_mode`` rejects as a
     ``RunSpecError`` before any carrier is reconstructed) -> 10, with stderr
     carrying the exception class name + the subcommand stage, and NO outcome
     value on stdout;
  3. a futility fixture via ``phase2a`` (forced by monkeypatching
     ``run_phase2a_fixture``) -> 20;
  4. an unknown subcommand -> argparse's own error (``SystemExit(2)``);
  5. the three-independent-process ``phase2a → preflight → phase2b`` e2e the
     from-disk loader enables (previously impossible while the CLI rebuilt a
     write-once fixture per call).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from alive.compose.diagnostics2 import FutilityResult
from alive.compose.driver.cli import main
from alive.compose.driver.fixture_builder import build_compose_fixture
from alive.compose.driver.identity_lock import AssemblerError
from alive.compose.gates import GateResult
from alive.compose.identify import RankReport, SingularDesignError
from alive.compose.phase2a import Phase2aResult
from alive.compose.select import SelectionError


def _fixture_cli_args(tmp_path: Path) -> tuple[str, str, str]:
    """Build the committed fixture corpus ONCE and return its CLI args.

    Since Task 11.5 ``main()`` LOADS the carrier from disk (it never rebuilds),
    so the corpus must EXIST when ``main()`` runs: this builds it up-front and
    LEAVES it in place (unlike the Task-11 throwaway-then-wipe shape). The
    ``spec_path`` / ``approved_artifacts_root`` / ``run_dir`` are the builder's
    own deterministic values (never hardcoded here).
    """
    bundle = build_compose_fixture(tmp_path)
    return str(bundle.spec_path), str(bundle.approved_artifacts_root), str(bundle.run_dir)


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
    # main() LOADS the carrier from disk; pointing --run-spec at a file no
    # builder ever wrote fails closed in the loader's mode-peek (a RunSpecError:
    # cannot read) before any carrier is reconstructed.
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
# Scenario: an AssemblerError (execution-lock / worker-digest mismatch) raised
# during a subcommand's carrier assembly -> 10 (pre-seal). AssemblerError is a
# ``ValueError`` subclass, NOT a member of any other _KNOWN_PRESEAL_REJECTIONS
# entry, so before the fix it propagated uncaught (traceback + exit 1) instead
# of the contracted single-stderr-line + exit 10. Monkeypatching phase2a's
# ``assemble_baseline_backends`` symbol (the same technique the futility test
# uses for ``run_phase2a_fixture``) forces the reachable §7.1 abort row.
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Scenario: every hyperparameter candidate is excluded by the registered
# estimator-domain rank policy -> SelectionError -> 10 (pre-seal). This is a
# selection INVALIDATION, not FUTILITY_STOPPED: phase2a writes no futility
# report, so the per-candidate exclusion reasons exist only in the contracted
# stderr line. SelectionError is a bare ``ValueError`` subclass covered by no
# other roster entry, so without its entry the run ended in a traceback and
# exit 1, outside the §1.1 contract.
# --------------------------------------------------------------------------- #
def test_selection_error_returns_ten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    spec_path, approved_root, run_dir = _fixture_cli_args(tmp_path)

    def _raise_selection(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise SelectionError(
            "no viable hyperparameter candidate; (4, 0.0): OOF train fold 0: "
            "unregularized calibration design is non-identifiable"
        )

    monkeypatch.setattr(
        "alive.compose.driver.phase2a_cmd.run_phase2a_fixture",
        _raise_selection,
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

    assert rc == 10
    captured = capsys.readouterr()
    assert captured.out == ""  # NO outcome value on stdout
    assert "phase2a: SelectionError:" in captured.err
    # the exclusion reasons are the only record this path leaves
    assert "no viable hyperparameter candidate" in captured.err


# --------------------------------------------------------------------------- #
# Scenario: the estimator refuses to produce an estimate -> SingularDesignError
# -> 10 (pre-seal). OOF selection catches this per candidate, but phase2a's
# post-selection fit runs outside that handler. Like SelectionError it is a bare
# ``ValueError`` subclass covered by no other roster entry, so it must remain in
# the contracted pre-seal rejection roster.
# --------------------------------------------------------------------------- #
def test_singular_design_error_returns_ten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    spec_path, approved_root, run_dir = _fixture_cli_args(tmp_path)

    def _raise_singular(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise SingularDesignError("regularized SVD solver failed at lam=0.001")

    monkeypatch.setattr(
        "alive.compose.driver.phase2a_cmd.run_phase2a_fixture",
        _raise_singular,
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

    assert rc == 10
    captured = capsys.readouterr()
    assert captured.out == ""  # NO outcome value on stdout
    assert "phase2a: SingularDesignError:" in captured.err
    assert "regularized SVD solver failed" in captured.err


def test_assembler_error_returns_ten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    spec_path, approved_root, run_dir = _fixture_cli_args(tmp_path)

    def _raise_assembler(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssemblerError("execution-lock mismatch: declared digest diverges")

    monkeypatch.setattr(
        "alive.compose.driver.phase2a_cmd.assemble_baseline_backends",
        _raise_assembler,
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

    assert rc == 10
    captured = capsys.readouterr()
    assert captured.out == ""  # NO outcome value on stdout
    assert "phase2a: AssemblerError:" in captured.err


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
# recover: argparse wiring dispatches without run-spec flags; scientific recovery
# may additionally name its protocol-global seal audit.
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


def test_recover_accepts_external_seal_audit_path(tmp_path, capsys) -> None:
    empty_run_dir = tmp_path / "empty"
    empty_run_dir.mkdir()
    audit_path = tmp_path / ".compose-protocol-seal-test.jsonl"
    audit_path.write_text("{}\n", encoding="utf-8")

    rc = main(
        [
            "recover",
            "--run-dir",
            str(empty_run_dir),
            "--seal-audit-path",
            str(audit_path),
        ]
    )

    assert rc == 10
    assert "recover: RunDirStateError:" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Scenario 5: the three-independent-process phase2a -> preflight -> phase2b e2e
# the from-disk carrier loader (Task 11.5) enables. This FLIPS the previously-
# pinned second-call failure: because main() now LOADS the carrier from disk
# (no write-once rebuild), a SECOND (and THIRD) CLI process against the SAME
# --run-spec / --run-dir now SUCCEEDS instead of dying on a FitRoleArtifactError.
# Three separate main() invocations share ONE ResolvedRunSpec / run_dir and end
# in a COMPLETE phase2b seal (exit 0) — the spec §11 DoD.
# --------------------------------------------------------------------------- #
def test_three_independent_processes_full_e2e(tmp_path: Path) -> None:
    spec_path, approved_root, run_dir = _fixture_cli_args(tmp_path)
    common = [
        "--run-spec",
        spec_path,
        "--approved-artifacts-root",
        approved_root,
        "--run-dir",
        run_dir,
    ]

    assert main(["phase2a", *common]) == 0
    assert main(["preflight", *common]) == 0

    # the --confirm-seal token is the installed confirmation manifest's FULL
    # confirmation_checksum (never the run id), read from the run_dir preflight
    # just populated — exactly what an independent phase2b process would read.
    manifest = json.loads((Path(run_dir) / "seal_confirmation_manifest.json").read_text())
    token = manifest["confirmation_checksum"]

    assert main(["phase2b", *common, "--confirm-seal", token]) == 0
