"""The audit mutation harness may never record a non-kill as a kill.

``scripts/compose_audit_mutation_harness.py`` exists to certify that the
enforcement points this remediation wave changed are actually held by named
tests. That certificate is worthless if the harness scores on the process exit
code: a mutant that breaks collection, or that explodes while the module is being
re-executed, exits nonzero with **zero failing tests**, and an exit-code scorer
records it as "killed" -- a statement about the process, not about the tests.
That is the project's mutation rule 4, and it was learned by getting it wrong
(a one-character syntax break once produced three collection errors, no
assertion, and was recorded as a kill).

Rule 6 is pinned here too: the kill must be by the test whose OWN NAME makes the
claim. A mutation that reddens some *other* test has measured a different
contract, so this harness pins one nodeid per case and refuses anything else.

These tests are the harness's own instrument check. They assert the classifier's
contract directly (cheap, exhaustive) and then run the engine end-to-end on one
real case (slow-ish, but it is the only thing that proves the subprocess actually
mutates what it says it does and leaves the tracked file alone).
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_HARNESS = _REPO / "scripts/compose_audit_mutation_harness.py"

_IO_NODEID = "tests/alive/test_io.py::test_a_second_write_to_the_same_destination_is_refused"
_OTHER_NODEID = "tests/alive/test_io.py::test_some_other_test"


def _load_harness():
    """Import the harness script by path (it is a script, not a package module).

    Registered in ``sys.modules`` before execution because the harness defines
    dataclasses, and ``dataclasses`` resolves annotations through
    ``sys.modules[cls.__module__]``.
    """
    name = "_compose_audit_mutation_harness"
    spec = importlib.util.spec_from_file_location(name, _HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness():
    return _load_harness()


def _run(harness, returncode: int, failed: frozenset[str], summary: str = "x"):
    return harness.CaseRun(returncode=returncode, failed=failed, summary=summary)


def _green_baseline(harness):
    return _run(harness, 0, frozenset(), "1 passed")


# --------------------------------------------------------------------------- #
# Rule 4 — a kill is a NAMED FAILING TEST, never a nonzero exit code.
# --------------------------------------------------------------------------- #
def test_a_mutant_that_only_produced_a_collection_error_is_not_recorded_as_killed(harness):
    """Exit 2 with zero failing tests is the canonical rule-4 trap."""
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 2, frozenset(), "1 error"),
        nodeid=_IO_NODEID,
    )
    assert verdict != harness.KILLED
    assert verdict == harness.HARNESS_FAILURE


def test_a_nonzero_exit_with_no_named_failure_is_not_recorded_as_killed(harness):
    """The engine re-executes the module source; a mutant that explodes there
    exits 1 with an empty failure list. Exit 1 is exactly what a real kill also
    returns, so the failure list -- not the code -- has to be the discriminator."""
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 1, frozenset(), "(no output)"),
        nodeid=_IO_NODEID,
    )
    assert verdict != harness.KILLED
    assert verdict == harness.HARNESS_FAILURE


def test_a_pytest_usage_error_for_a_missing_nodeid_is_not_recorded_as_killed(harness):
    """A nodeid that no longer exists makes pytest exit 4 and collect nothing.
    Scoring on the code would turn a renamed test into permanent evidence."""
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 4, frozenset(), "ERROR: not found"),
        nodeid=_IO_NODEID,
    )
    assert verdict == harness.HARNESS_FAILURE


# --------------------------------------------------------------------------- #
# Rule 6 — the killer must be the test whose own name makes the claim.
# --------------------------------------------------------------------------- #
def test_a_failure_of_some_other_test_is_not_a_kill_for_this_case(harness):
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 1, frozenset({_OTHER_NODEID}), "1 failed"),
        nodeid=_IO_NODEID,
    )
    assert verdict != harness.KILLED
    assert verdict == harness.HARNESS_FAILURE


def test_a_named_failure_of_the_pinned_nodeid_is_the_only_thing_scored_as_a_kill(harness):
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 1, frozenset({_IO_NODEID}), "1 failed"),
        nodeid=_IO_NODEID,
    )
    assert verdict == harness.KILLED


def test_a_green_mutant_is_a_survivor_not_a_kill(harness):
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 0, frozenset(), "1 passed"),
        nodeid=_IO_NODEID,
    )
    assert verdict == harness.SURVIVED


def test_a_red_baseline_invalidates_the_case_even_when_the_mutant_dies(harness):
    """Without a green baseline through the SAME machinery, a "kill" could be the
    module re-execution breaking the test rather than the mutation."""
    verdict = harness.classify(
        baseline=_run(harness, 1, frozenset({_IO_NODEID}), "1 failed"),
        mutant=_run(harness, 1, frozenset({_IO_NODEID}), "1 failed"),
        nodeid=_IO_NODEID,
    )
    assert verdict == harness.HARNESS_FAILURE


# --------------------------------------------------------------------------- #
# Engine contract, measured end-to-end.
# --------------------------------------------------------------------------- #
def test_an_anchor_that_does_not_occur_exactly_once_is_a_harness_failure(harness):
    """A missing target must never silently score; `count(old) == 1` is enforced
    in the child and reported with its own exit code."""
    detail = harness.run_case_detail(
        "alive.io", "NOT_PRESENT_IN_THE_SOURCE_ZZZ", "pass", _IO_NODEID
    )
    assert detail.returncode == harness.ANCHOR_EXIT
    assert detail.failed == frozenset()
    verdict = harness.classify(baseline=_green_baseline(harness), mutant=detail, nodeid=_IO_NODEID)
    assert verdict == harness.HARNESS_FAILURE


def test_the_engine_kills_a_real_mutation_without_writing_the_tracked_module(harness):
    """`src/alive/io.py` is a pinned file this wave must not modify, so the whole
    engine mutates an in-memory copy of the source inside the subprocess. Both
    halves are measured here: the kill happens, and the bytes on disk do not move.
    """
    target = _REPO / "src/alive/io.py"
    before = hashlib.sha256(target.read_bytes()).hexdigest()

    baseline = harness.run_case_detail("alive.io", "", "", _IO_NODEID)
    mutant = harness.run_case_detail(
        "alive.io",
        "os.link(temporary, destination)",
        "os.replace(temporary, destination)",
        _IO_NODEID,
    )

    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
    assert baseline.returncode == 0
    assert mutant.returncode == 1
    assert _IO_NODEID in mutant.failed
    assert harness.classify(baseline=baseline, mutant=mutant, nodeid=_IO_NODEID) == harness.KILLED


def test_run_case_returns_the_mutant_exit_code(harness):
    """The briefed interface `run_case(module, old, new, nodeid) -> int`."""
    code = harness.run_case(
        "alive.io",
        "os.link(temporary, destination)",
        "os.replace(temporary, destination)",
        _IO_NODEID,
    )
    assert code == 1


# --------------------------------------------------------------------------- #
# The roster itself: no invented names.
# --------------------------------------------------------------------------- #
def test_every_registered_case_pins_a_nodeid_that_really_exists(harness):
    """A case whose killer name was invented would report `HARNESS_FAILURE` at run
    time, but only when someone runs it. Pin it statically as well."""
    missing: list[str] = []
    for case in harness.CASES:
        path, _, rest = case.nodeid.partition("::")
        function = rest.split("::")[-1].split("[")[0]
        file_path = _REPO / path
        if not file_path.exists() or f"def {function}" not in file_path.read_text(encoding="utf-8"):
            missing.append(case.nodeid)
    assert not missing, f"registered killer nodeids that do not exist: {missing}"


def test_the_not_harnessed_rows_say_why_and_cite_their_standing_record(harness):
    """A skipped case is only honest if the reason and the evidence it defers to
    are written down beside it."""
    assert harness.NOT_HARNESSED_CASES, "the producer row must stay declared, not deleted"
    for row in harness.NOT_HARNESSED_CASES:
        assert row.reason.strip()
        assert row.standing_record.strip()
