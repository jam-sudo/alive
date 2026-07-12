"""Cross-process mini end-to-end suite for the COMPOSE production driver (spec §11).

This is the culminating DoD item 4 of spec §11: the THREE-INDEPENDENT-PROCESS
``phase2a → preflight → phase2b`` e2e. Unlike the subcommand-level tests (which
call ``run_*_subcommand`` in-process, sharing a live in-memory carrier), this
suite invokes the REAL CLI (``scripts/run_compose_k562_phase2.py``) as SEPARATE
OS PROCESSES via :func:`subprocess.run`. Process memory is NOT shared, so each
process must reconstruct its stage-1 carrier from disk via Task 11.5's
:func:`~alive.compose.driver.carrier_loader.load_run_spec_carrier` — this is what
proves the spec §4 seal-isolation contract holds across true process boundaries
(no in-memory carrier can be smuggled between stages).

Architecture. The synthetic corpus + the fixture ResolvedRunSpec are produced
ONCE up-front by :func:`~alive.compose.driver.fixture_builder.build_compose_fixture`
(a write-once one-time producer). Because the harness Python is out of the
project's supported range, EVERY invocation — including the corpus build — runs
under the repo venv interpreter (``.venv/bin/python``) with ``cwd`` at the repo
root so ``import alive`` resolves. The corpus for the (read-only) positive path
is built once and reused; each state-mutating negative gets its OWN fresh corpus.

Coverage discipline. The cross-process-SPECIFIC negatives (omit preflight,
delete/tamper the persisted ledger between processes, the audit/recover crash
path, scientific-mode fail-closed) are implemented HERE as subprocess tests — they
are the invariants ONLY this e2e can prove. Negatives already thoroughly unit-
tested at the subcommand level (obs-row swap, token-swap after confirmation,
attestation SHA mismatch, single-store-construction + audit_path) are represented
by at most a small propagation subset here; the full assertion→coverage map lives
in the Task 13 report accompanying this change.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §11.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

# Repo root: tests/alive/compose/driver/test_mini_e2e.py -> up 4 -> repo root
# (driver -> compose -> alive -> tests -> repo root).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_VENV_PYTHON = _REPO_ROOT / ".venv" / "bin" / "python"
_DRIVER_SCRIPT = "scripts/run_compose_k562_phase2.py"

#: Per-subprocess wall-clock ceiling. The bounded synthetic corpus keeps each
#: stage fast; a generous cap guards against a hung subprocess without letting a
#: single slow stage stall the whole suite.
_STAGE_TIMEOUT_S = 240

#: Run-produced artifact basenames (mirrored from the committed constants; the
#: e2e asserts on-disk names, so it references the values, not the modules).
_FROZEN_BUNDLE = "frozen_prediction_bundle.json"
_OOF_MANIFEST = "oof_fold_manifest.json"
_PHASE2A_SEED_VARIABILITY = "phase2a_development_seed_variability.json"
_PHASE2A_LEDGER = "phase2a_run_ledger.json"
_CONFIRMATION = "seal_confirmation_manifest.json"
_DURABLE_COMMIT = "phase2b_durable_commit.json"
_FINAL_LEDGER = "phase2b_final_ledger.json"
_REGISTERED_SUMMARY = "phase2b_registered_summary.json"
_AUDIT = "audit.jsonl"
_TERMINAL_COMPLETE = "terminal_complete.json"
_TERMINAL_INVALID = "terminal_invalid.json"
_TERMINAL_ABORTED = "terminal_aborted.json"

#: The three CLI exit codes this suite asserts (spec §1.1).
_SUCCESS = 0
_PRESEAL_REJECT = 10
_POSTSEAL_NONCOMPLETE = 30

_TERMINALS = (_TERMINAL_COMPLETE, _TERMINAL_INVALID, _TERMINAL_ABORTED)


# --------------------------------------------------------------------------- #
# subprocess plumbing
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _CliResult:
    """The captured outcome of one CLI subprocess invocation."""

    returncode: int
    stdout: str
    stderr: str


def _run_cli(*args: str, timeout: float = _STAGE_TIMEOUT_S) -> _CliResult:
    """Invoke the real driver CLI as a SEPARATE OS process under the repo venv.

    Runs ``.venv/bin/python scripts/run_compose_k562_phase2.py <args>`` with
    ``cwd`` at the repo root (so ``import alive`` resolves) and captures
    stdout/stderr. No in-process ``main()`` call — each stage is a genuinely
    independent process that reconstructs its carrier from disk (spec §11).
    """
    completed = subprocess.run(  # noqa: S603 — fixed interpreter + committed script
        [str(_VENV_PYTHON), _DRIVER_SCRIPT, *args],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return _CliResult(completed.returncode, completed.stdout, completed.stderr)


def _build_corpus(dest_root: Path) -> dict[str, str]:
    """Produce the synthetic corpus + fixture ResolvedRunSpec ONCE under ``dest_root``.

    Runs :func:`build_compose_fixture` in a venv subprocess (the harness Python is
    out of range) and returns the paths the CLI needs (spec / root / run_dir). The
    builder is a write-once producer, so this is called exactly once per corpus.
    """
    dest_root.mkdir(parents=True, exist_ok=True)
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from alive.compose.driver.fixture_builder import build_compose_fixture\n"
        "fx = build_compose_fixture(Path(sys.argv[1]))\n"
        "print(json.dumps({\n"
        "    'spec_path': str(fx.spec_path),\n"
        "    'root': str(fx.approved_artifacts_root),\n"
        "    'run_dir': str(fx.run_dir),\n"
        "    'audit_path': str(fx.audit_path),\n"
        "    'run_id': fx.run_id,\n"
        "}))\n"
    )
    completed = subprocess.run(  # noqa: S603 — fixed interpreter + inline builder
        [str(_VENV_PYTHON), "-c", script, str(dest_root)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=_STAGE_TIMEOUT_S,
    )
    assert completed.returncode == 0, (
        f"corpus build failed (rc={completed.returncode})\n"
        f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
    )
    # The builder prints exactly one JSON line to stdout; anndata may emit
    # warnings to stderr, which we ignore.
    info = json.loads(completed.stdout.strip().splitlines()[-1])
    return info


def _run_spec_flags(info: dict[str, str]) -> list[str]:
    """The three shared ``--run-spec/--approved-artifacts-root/--run-dir`` flags."""
    return [
        "--run-spec",
        info["spec_path"],
        "--approved-artifacts-root",
        info["root"],
        "--run-dir",
        info["run_dir"],
    ]


def _confirmation_token(run_dir: Path) -> str:
    """Read the installed manifest's FULL ``confirmation_checksum`` (the phase2b token)."""
    manifest = json.loads((run_dir / _CONFIRMATION).read_bytes())
    return manifest["confirmation_checksum"]


def _present_terminals(run_dir: Path) -> list[str]:
    return [name for name in _TERMINALS if (run_dir / name).exists()]


def _assert_no_seal_side_effects(run_dir: Path) -> None:
    """Assert a fail-closed pre-seal run consumed no seal and left no terminal/store."""
    assert not (run_dir / _AUDIT).exists(), "a burned audit.jsonl means the seal was opened"
    assert _present_terminals(run_dir) == [], "no terminal artifact may exist pre-seal"
    assert not (run_dir / _DURABLE_COMMIT).exists(), "no durable commit marker may exist pre-seal"


def _drive_to_confirmation(info: dict[str, str], run_dir: Path) -> str:
    """Run the two independent pre-seal processes (phase2a, preflight); return the token."""
    flags = _run_spec_flags(info)
    assert _run_cli("phase2a", *flags).returncode == _SUCCESS
    assert _run_cli("preflight", *flags).returncode == _SUCCESS
    return _confirmation_token(run_dir)


def _reduce_to_audit_only(run_dir: Path) -> None:
    """Reduce a COMPLETE run to the ``audit=1 / terminal=0`` post-crash state.

    Removes the terminal AND every durable finalize artifact (the recover roster
    forbids a durable-without-terminal partial), leaving the burned ``audit.jsonl``
    + its causally-prior pre-access provenance + the seed-variability report. This
    is the faithful crash state ``recover`` synthesizes ``ABORTED_AFTER_SEAL`` from
    (matches the reduction the T10 recover unit test performs).
    """
    (run_dir / _TERMINAL_COMPLETE).unlink()
    (run_dir / _DURABLE_COMMIT).unlink()
    (run_dir / _FINAL_LEDGER).unlink()
    (run_dir / _REGISTERED_SUMMARY).unlink()


# --------------------------------------------------------------------------- #
# Shared read-only corpus for the positive path (built ONCE per module)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def positive_corpus(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Build the corpus ONCE and drive the full 3-process COMPLETE path over it.

    The bounded synthetic corpus is expensive to build under subprocesses, so it
    is produced a single time; the positive-path assertions all read the same
    completed ``run_dir``. State-mutating NEGATIVES never use this fixture — they
    each build their own fresh corpus so no test observes another's mutations.
    """
    root = tmp_path_factory.mktemp("compose_e2e_positive")
    info = _build_corpus(root)
    run_dir = Path(info["run_dir"])

    # Three independent OS processes, canonical order phase2a -> preflight -> phase2b.
    flags = _run_spec_flags(info)
    r_a = _run_cli("phase2a", *flags)
    assert r_a.returncode == _SUCCESS, f"phase2a rc={r_a.returncode}\nSTDERR:\n{r_a.stderr}"
    r_p = _run_cli("preflight", *flags)
    assert r_p.returncode == _SUCCESS, f"preflight rc={r_p.returncode}\nSTDERR:\n{r_p.stderr}"
    token = _confirmation_token(run_dir)
    r_b = _run_cli("phase2b", "--confirm-seal", token, *flags)
    assert r_b.returncode == _SUCCESS, f"phase2b rc={r_b.returncode}\nSTDERR:\n{r_b.stderr}"
    return info


# --------------------------------------------------------------------------- #
# The MANDATORY positive path (spec §11 DoD item 4)
# --------------------------------------------------------------------------- #
def test_phase2a_process_installs_frozen_bundle_oof_ledger_and_distinct_seed_report(
    positive_corpus: dict[str, str],
) -> None:
    """Step 1: the independent phase2a process installs the four phase2a artifacts.

    In particular the DISTINCT ``phase2a_development_seed_variability.json`` (NOT
    the canonical ``development_seed_variability.json`` phase2b later installs) is
    on disk — proving the phase2a process wrote its own seed-variability report.
    """
    run_dir = Path(positive_corpus["run_dir"])
    for name in (_FROZEN_BUNDLE, _OOF_MANIFEST, _PHASE2A_SEED_VARIABILITY, _PHASE2A_LEDGER):
        assert (run_dir / name).is_file(), f"phase2a did not install {name}"


def test_preflight_process_installs_confirmation_manifest_with_token(
    positive_corpus: dict[str, str],
) -> None:
    """Step 2: the independent preflight process installs the confirmation manifest.

    Its ``confirmation_checksum`` is the FULL token phase2b consumes (a non-empty
    64-hex digest), read from disk by the NEXT process — never shared in memory.
    """
    run_dir = Path(positive_corpus["run_dir"])
    manifest_path = run_dir / _CONFIRMATION
    assert manifest_path.is_file(), "preflight did not install the confirmation manifest"
    token = _confirmation_token(run_dir)
    assert isinstance(token, str) and len(token) == 64
    # It is the full confirmation checksum, NOT the (short) recomputable run id.
    assert token != positive_corpus["run_id"]


def test_phase2b_process_completes_with_durable_marker_terminal_and_audit(
    positive_corpus: dict[str, str],
) -> None:
    """Step 3: the independent phase2b process reaches COMPLETE with the whole seal path.

    Proves the entire 3-process seal path works: the durable commit marker, the
    COMPLETE terminal, and the burned ``audit.jsonl`` are all on disk after the
    third process exited 0. (The module fixture already asserted every stage
    exited 0; this asserts the on-disk seal outcome the fixture produced.)
    """
    run_dir = Path(positive_corpus["run_dir"])
    assert (run_dir / _DURABLE_COMMIT).is_file(), "no durable commit marker after phase2b"
    assert _present_terminals(run_dir) == [_TERMINAL_COMPLETE], "expected a COMPLETE terminal only"
    assert (run_dir / _AUDIT).is_file(), "the seal audit must be burned after phase2b"


def test_positive_phase2b_emits_nothing_to_stdout(tmp_path: Path) -> None:
    """Output discipline (spec §3.3): phase2b emits NO scientific outcome to stdout.

    A fresh corpus is built so this can capture the third process's OWN stdout (the
    module fixture reuses an already-completed run_dir). Nothing scientific — no
    aggregate, verdict, or per-pair value — may be written to stdout on success.
    """
    info = _build_corpus(tmp_path / "corpus")
    run_dir = Path(info["run_dir"])
    token = _drive_to_confirmation(info, run_dir)
    result = _run_cli("phase2b", "--confirm-seal", token, *_run_spec_flags(info))
    assert result.returncode == _SUCCESS
    assert result.stdout == "", f"phase2b wrote to stdout: {result.stdout!r}"


# --------------------------------------------------------------------------- #
# Cross-process negative (a): omit preflight → phase2b fails closed before seal
# --------------------------------------------------------------------------- #
def test_omitting_preflight_process_makes_phase2b_fail_closed_before_seal(
    tmp_path: Path,
) -> None:
    """Run phase2a then phase2b DIRECTLY (no preflight process) → phase2b rejects.

    Without the intervening preflight process there is no confirmation manifest,
    so phase2b's entry roster fails closed (non-zero) BEFORE any seal: no burned
    audit, no terminal, no store. This is a cross-process invariant — an in-process
    caller could not have installed the manifest either, but the point here is that
    an INDEPENDENT phase2b process reconstructing from disk still refuses.
    """
    info = _build_corpus(tmp_path / "corpus")
    run_dir = Path(info["run_dir"])
    flags = _run_spec_flags(info)

    assert _run_cli("phase2a", *flags).returncode == _SUCCESS
    assert not (run_dir / _CONFIRMATION).exists()

    result = _run_cli("phase2b", "--confirm-seal", "x" * 64, *flags)
    assert result.returncode == _PRESEAL_REJECT, f"STDERR:\n{result.stderr}"
    assert result.stdout == ""
    _assert_no_seal_side_effects(run_dir)


# --------------------------------------------------------------------------- #
# Cross-process negative (b): delete / tamper phase2a's ledger between processes
# --------------------------------------------------------------------------- #
def test_deleting_phase2a_ledger_makes_preflight_fail_closed(tmp_path: Path) -> None:
    """Delete the persisted phase2a ledger between processes → preflight rejects.

    The ledger is round-tripped THROUGH DISK across the process boundary (never a
    shared in-memory object), so its absence fails closed (exit 10) with no
    confirmation manifest installed.
    """
    info = _build_corpus(tmp_path / "corpus")
    run_dir = Path(info["run_dir"])
    flags = _run_spec_flags(info)

    assert _run_cli("phase2a", *flags).returncode == _SUCCESS
    (run_dir / _PHASE2A_LEDGER).unlink()

    result = _run_cli("preflight", *flags)
    assert result.returncode == _PRESEAL_REJECT, f"STDERR:\n{result.stderr}"
    assert not (run_dir / _CONFIRMATION).exists()
    _assert_no_seal_side_effects(run_dir)


def test_tampering_phase2a_ledger_binding_makes_preflight_fail_closed(tmp_path: Path) -> None:
    """Tamper the persisted ledger's recorded spec SHA → preflight rejects.

    A CONTENT-level tamper (flip the recorded ``resolved_run_spec`` artifact SHA)
    breaks the driver's ledger↔spec binding cross-check, which re-derives the
    expected SHAs from the loaded ResolvedRunSpec — so preflight fails closed
    (exit 10) with no confirmation. (A trailing-whitespace edit would be a no-op:
    JSON parsing strips it and the binding reads content, not file bytes — so this
    negative flips a value the binding actually consumes.)
    """
    info = _build_corpus(tmp_path / "corpus")
    run_dir = Path(info["run_dir"])
    flags = _run_spec_flags(info)

    assert _run_cli("phase2a", *flags).returncode == _SUCCESS

    ledger_path = run_dir / _PHASE2A_LEDGER
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    flipped = False
    for artifact in ledger["artifacts"]:
        if artifact["name"] == "resolved_run_spec":
            artifact["sha256"] = "0" * 64
            flipped = True
            break
    assert flipped, "expected a resolved_run_spec artifact entry in the phase2a ledger"
    ledger_path.write_text(
        json.dumps(ledger, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    result = _run_cli("preflight", *flags)
    assert result.returncode == _PRESEAL_REJECT, f"STDERR:\n{result.stderr}"
    assert not (run_dir / _CONFIRMATION).exists()
    _assert_no_seal_side_effects(run_dir)


def test_deleting_ledger_after_confirmation_makes_phase2b_fail_closed(tmp_path: Path) -> None:
    """Delete the ledger AFTER a valid confirmation → phase2b fails closed pre-seal.

    Even with a genuine confirmation token in hand, an independent phase2b process
    RE-READS the persisted phase2a ledger (never reconstructing it from the bundle)
    to re-run the preflight gate + rebuild the confirmation inputs; its absence
    fails closed (exit 10) BEFORE the seal opens — no audit, no terminal.
    """
    info = _build_corpus(tmp_path / "corpus")
    run_dir = Path(info["run_dir"])
    flags = _run_spec_flags(info)

    token = _drive_to_confirmation(info, run_dir)
    (run_dir / _PHASE2A_LEDGER).unlink()

    result = _run_cli("phase2b", "--confirm-seal", token, *flags)
    assert result.returncode == _PRESEAL_REJECT, f"STDERR:\n{result.stderr}"
    assert result.stdout == ""
    _assert_no_seal_side_effects(run_dir)


# --------------------------------------------------------------------------- #
# ⚑ Cross-process negative (c): the AUDIT / RECOVER crash path (highest value)
# --------------------------------------------------------------------------- #
def test_recover_process_synthesizes_aborted_after_seal_from_crash_state(tmp_path: Path) -> None:
    """After a real seal-consuming phase2b, an ``audit=1 / terminal=0`` crash recovers.

    Drive the full 3-process COMPLETE path (the seal is genuinely consumed — a
    burned ``audit.jsonl`` exists), then simulate a crash between opening the seal
    and finalizing the durable terminal by removing the terminal + durable finalize
    artifacts. An INDEPENDENT ``recover`` process then SUCCEEDS at salvaging the
    consumed seal: it synthesizes the sole ``ABORTED_AFTER_SEAL`` terminal (exit 30
    — a valid non-COMPLETE salvage, NOT a failure) + a fresh durable marker, and
    NEVER resurrects a COMPLETE terminal. ``recover`` reconstructs the audit at the
    EXACT ``<run_dir>/audit.jsonl`` path phase2b's store was built with.
    """
    info = _build_corpus(tmp_path / "corpus")
    run_dir = Path(info["run_dir"])
    flags = _run_spec_flags(info)

    token = _drive_to_confirmation(info, run_dir)
    assert _run_cli("phase2b", "--confirm-seal", token, *flags).returncode == _SUCCESS
    assert (run_dir / _AUDIT).stat().st_size > 0, "phase2b must have burned the audit"

    _reduce_to_audit_only(run_dir)
    # Sanity: this really is the audit=1 / terminal=0 crash state.
    assert (run_dir / _AUDIT).stat().st_size > 0
    assert _present_terminals(run_dir) == []
    assert not (run_dir / _DURABLE_COMMIT).exists()

    result = _run_cli("recover", "--run-dir", info["run_dir"])
    assert result.returncode == _POSTSEAL_NONCOMPLETE, f"STDERR:\n{result.stderr}"
    # recover FOUND the audit at <run_dir>/audit.jsonl and salvaged the seal:
    assert (run_dir / _TERMINAL_ABORTED).is_file(), "recover did not synthesize ABORTED_AFTER_SEAL"
    assert (run_dir / _DURABLE_COMMIT).is_file(), "recover did not publish a durable marker"
    assert (run_dir / _FINAL_LEDGER).is_file()
    # The reduced abort publish carries NO registered summary and never resurrects
    # the COMPLETE terminal.
    assert not (run_dir / _REGISTERED_SUMMARY).exists()
    assert not (run_dir / _TERMINAL_COMPLETE).exists()


def test_recover_process_on_completed_run_is_verify_only(tmp_path: Path) -> None:
    """``recover`` over a fully COMPLETE run is VERIFY-ONLY → exit 0, no rewrite.

    Proves the positive side of the recover contract across a process boundary: an
    independent ``recover`` process finds the audit + the intact terminal/marker
    and re-verifies them WITHOUT rewriting a byte or synthesizing an ABORTED
    terminal.
    """
    info = _build_corpus(tmp_path / "corpus")
    run_dir = Path(info["run_dir"])
    flags = _run_spec_flags(info)

    token = _drive_to_confirmation(info, run_dir)
    assert _run_cli("phase2b", "--confirm-seal", token, *flags).returncode == _SUCCESS

    terminal_before = (run_dir / _TERMINAL_COMPLETE).read_bytes()
    marker_before = (run_dir / _DURABLE_COMMIT).read_bytes()

    result = _run_cli("recover", "--run-dir", info["run_dir"])
    assert result.returncode == _SUCCESS, f"STDERR:\n{result.stderr}"
    # VERIFY ONLY: neither the terminal nor the durable marker is rewritten, and no
    # ABORTED terminal is fabricated when a real COMPLETE terminal is present.
    assert (run_dir / _TERMINAL_COMPLETE).read_bytes() == terminal_before
    assert (run_dir / _DURABLE_COMMIT).read_bytes() == marker_before
    assert not (run_dir / _TERMINAL_ABORTED).exists()


# --------------------------------------------------------------------------- #
# scientific-mode spec via the CLI with no --trusted-repo-root → fails closed
# --------------------------------------------------------------------------- #
def test_scientific_mode_spec_fails_closed_via_cli_with_no_store(tmp_path: Path) -> None:
    """A ``scientific``-mode ResolvedRunSpec with no ``--trusted-repo-root`` fails closed.

    Scientific-mode carrier assembly (spec §5) requires the out-of-band
    ``--trusted-repo-root`` CLI flag; omitting it (the flag's default is ``None``)
    fails closed in ``load_run_spec_carrier`` as a ``RunSpecError`` BEFORE the spec
    body is even loaded — so the CLI reports the pre-seal-reject exit (10) with NO
    store, NO terminal, NO seal. A full scientific carrier assembly (with
    ``--trusted-repo-root`` supplied) is covered by
    ``test_scientific_carrier_load.py``, not this CLI-level fixture-mode-focused
    suite.
    """
    corpus = tmp_path / "sci_corpus"
    run_dir = corpus / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    spec_path = corpus / "scientific_spec.json"
    spec_path.write_text(json.dumps({"mode": "scientific"}), encoding="utf-8")

    result = _run_cli(
        "phase2a",
        "--run-spec",
        str(spec_path),
        "--approved-artifacts-root",
        str(corpus),
        "--run-dir",
        str(run_dir),
    )
    assert result.returncode == _PRESEAL_REJECT, f"STDERR:\n{result.stderr}"
    assert result.stdout == ""
    # The fail-closed mechanism is named on stderr (T10 diagnostic convention).
    assert "RunSpecError" in result.stderr
    assert "trusted_repo_root" in result.stderr
    # No store / terminal / seal was constructed; the run dir stays empty.
    assert list(run_dir.iterdir()) == []


# --------------------------------------------------------------------------- #
# Representative chain-propagation of a subcommand-unit negative (obs-row swap is
# T9-covered; token-swap-after-confirmation is T9-covered). Here we prove ONE such
# failure PROPAGATES through an independent phase2b process: a run-id-only token is
# rejected by the confirmation gate → exit 10, no seal. (We do NOT re-run every
# unit negative via slow subprocesses — see the report's coverage map.)
# --------------------------------------------------------------------------- #
def test_run_id_only_token_rejected_by_phase2b_process_before_seal(tmp_path: Path) -> None:
    """A run-id-only ``--confirm-seal`` token is rejected by the phase2b process.

    The run id is trivially recomputable and is NOT the full confirmation checksum,
    so an independent phase2b process fails the confirmation gate closed (exit 10)
    BEFORE any store construction — proving the token guard survives the process
    boundary (the full manifest-reconstruction check is T9-unit-covered).
    """
    info = _build_corpus(tmp_path / "corpus")
    run_dir = Path(info["run_dir"])
    flags = _run_spec_flags(info)

    _drive_to_confirmation(info, run_dir)  # installs a real confirmation manifest
    run_id = info["run_id"]

    result = _run_cli("phase2b", "--confirm-seal", run_id, *flags)
    assert result.returncode == _PRESEAL_REJECT, f"STDERR:\n{result.stderr}"
    assert result.stdout == ""
    _assert_no_seal_side_effects(run_dir)
