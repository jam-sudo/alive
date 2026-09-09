"""The audit mutation harness may never record a non-kill as a kill.

``scripts/compose_audit_mutation_harness.py`` exists to certify that the
enforcement points this remediation wave changed are actually held by named
tests. That certificate is worthless if the harness scores a case on something
weaker than the claim.

Two levels of that failure are pinned here, and the second was found by an
external review of the first version of this harness.

**Rule 4** -- a kill is a NAMED FAILING TEST, never a nonzero exit code. A mutant
that breaks collection, or that explodes while the module is being re-executed,
exits nonzero with **zero failing tests**, and an exit-code scorer records it as
"killed": a statement about the process, not about the tests.

**Rule 8** -- a kill must be attested by the test's OWN ASSERTION, not merely by
the test going red. A mutant can make an unrelated exception escape from deep
inside the call, and the named test then fails for a reason it never claimed.
That is not a measurement of the claim in its name. Measured, not hypothetical:
deleting the exact-sealed-union guard left a downstream ``KeyError``, and
narrowing the manifest re-read's ``except`` let a raw ``FileNotFoundError``
escape -- both were being scored as kills. Only ``AssertionError`` and pytest's
``Failed`` (``pytest.fail``; an unfulfilled ``pytest.raises``) count now.

**Rule 6** is pinned too: the kill must be by the test whose OWN NAME makes the
claim, so the harness pins one nodeid per case and scores nothing else.

These tests are the harness's own instrument check. They assert the classifier's
contract directly (cheap, exhaustive) and then run the engine end-to-end on real
cases -- the only thing that proves the subprocess mutates what it says it does,
records the real exception kind, and leaves the tracked files alone.
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
_IO_TEST_MODULE = _IO_NODEID.split("::")[0]
_SYNTHETIC_TEST_MODULE = "_synthetic_frame_test_module"


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


def _load_module(name: str, path: Path):
    """Import a synthetic module from ``path`` under ``name``."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _run(
    harness,
    returncode: int,
    failed: frozenset[str],
    kind: str | None = None,
    frame: str | None = None,
):
    return harness.CaseRun(
        returncode=returncode,
        failed=failed,
        summary="x",
        call_kind=kind,
        call_repr="",
        call_frame=frame,
    )


def _green_baseline(harness):
    return harness.CaseRun(returncode=0, failed=frozenset(), summary="1 passed")


# --------------------------------------------------------------------------- #
# Rule 4 — a kill is a NAMED FAILING TEST, never a nonzero exit code.
# --------------------------------------------------------------------------- #
def test_a_mutant_that_only_produced_a_collection_error_is_not_recorded_as_killed(harness):
    """Exit 2 with zero failing tests is the canonical rule-4 trap."""
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 2, frozenset()),
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
        mutant=_run(harness, 1, frozenset()),
        nodeid=_IO_NODEID,
    )
    assert verdict != harness.KILLED
    assert verdict == harness.HARNESS_FAILURE


def test_a_pytest_usage_error_for_a_missing_nodeid_is_not_recorded_as_killed(harness):
    """A nodeid that no longer exists makes pytest exit 4 and collect nothing.
    Scoring on the code would turn a renamed test into permanent evidence."""
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 4, frozenset()),
        nodeid=_IO_NODEID,
    )
    assert verdict == harness.HARNESS_FAILURE


# --------------------------------------------------------------------------- #
# Rule 8 — the kill must be the test's OWN assertion, not any red at all.
# --------------------------------------------------------------------------- #
def test_a_named_failure_on_a_stray_exception_is_not_recorded_as_killed(harness):
    """The finding that produced this rule: the named test goes red, but on an
    exception it never claimed, so the case measured nothing it asserts."""
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 1, frozenset({_IO_NODEID}), kind="RuntimeError"),
        nodeid=_IO_NODEID,
    )
    assert verdict != harness.KILLED
    assert verdict.startswith(harness.HARNESS_FAILURE)
    assert "non-assertion: RuntimeError" in verdict


@pytest.mark.parametrize("kind", ["KeyError", "FileNotFoundError", "ValueError", "TypeError"])
def test_no_stray_exception_type_can_be_scored_as_a_kill(harness, kind):
    """`KeyError` and `FileNotFoundError` are the two real ones this roster hit."""
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 1, frozenset({_IO_NODEID}), kind=kind),
        nodeid=_IO_NODEID,
    )
    assert verdict != harness.KILLED
    assert f"non-assertion: {kind}" in verdict


def test_a_call_phase_assertion_error_is_a_kill(harness):
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(
            harness, 1, frozenset({_IO_NODEID}), kind="AssertionError", frame=_IO_TEST_MODULE
        ),
        nodeid=_IO_NODEID,
    )
    assert verdict == harness.KILLED


def test_a_did_not_raise_failure_is_a_kill(harness):
    """pytest's `Failed` is the test's own assertion machinery, so it counts."""
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 1, frozenset({_IO_NODEID}), kind="Failed", frame=_IO_TEST_MODULE),
        nodeid=_IO_NODEID,
    )
    assert verdict == harness.KILLED


def test_a_setup_phase_assertion_can_never_be_scored_as_a_kill(harness):
    """A fixture blowing up is not the test's claim, even when it is an
    `AssertionError`; the recorder prefixes the phase so it cannot match."""
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 1, frozenset({_IO_NODEID}), kind="setup:AssertionError"),
        nodeid=_IO_NODEID,
    )
    assert verdict != harness.KILLED


# --------------------------------------------------------------------------- #
# Rule 8, second level — the assertion must be raised in the TEST's own frame.
# --------------------------------------------------------------------------- #
def test_a_kill_requires_the_failing_frame_to_be_the_tests_own_module(harness):
    """`AssertionError` alone does not identify WHOSE assertion failed.

    Production code carries bare `assert` statements of its own. A mutation that
    flips one of them reddens the pinned test with a genuine call-phase
    `AssertionError` -- the kind rule 8 accepts -- while the test's own
    assertions were never reached. Measured on the real tree before this clause
    existed: flipping `assert self.weights_ is not None` in
    `src/alive/compose/models.py` scored `KILLED`, and the last repository-owned
    traceback frame was `src/alive/compose/models.py`, not the test module.
    """
    killed = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(
            harness, 1, frozenset({_IO_NODEID}), kind="AssertionError", frame=_IO_TEST_MODULE
        ),
        nodeid=_IO_NODEID,
    )
    assert killed == harness.KILLED

    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(
            harness,
            1,
            frozenset({_IO_NODEID}),
            kind="AssertionError",
            frame="src/alive/compose/models.py",
        ),
        nodeid=_IO_NODEID,
    )
    assert verdict != harness.KILLED
    assert verdict.startswith(harness.HARNESS_FAILURE)
    assert "frame outside the test module: src/alive/compose/models.py" in verdict


def test_an_assertion_raised_in_a_synthetic_production_module_is_not_a_kill(
    harness, tmp_path, monkeypatch
):
    """The same trap through the real frame SELECTION, on a synthetic tree.

    Synthetic rather than `models.py` on purpose: that production assert is
    being removed, and evidence that stops reproducing is not evidence. A
    production module with a bare `assert` and a test module that calls it are
    written under `tmp_path`, `REPO` is pointed at that root, and the assertion
    is really raised -- so `_repo_frame` runs on a real traceback rather than a
    hand-written list. The two directions are measured together: an assertion
    raised in the test module's own frame is a kill; the identical
    `AssertionError` raised one frame deeper, inside production, is not.
    """
    src = tmp_path / "src"
    tests = tmp_path / "tests"
    src.mkdir()
    tests.mkdir()
    (src / "synthetic_production.py").write_text(
        "def fit(weights):\n"
        "    assert weights is not None  # production's own bare assert\n"
        "    return weights\n",
        encoding="utf-8",
    )
    (tests / "test_synthetic.py").write_text(
        "import synthetic_production\n"
        "\n"
        "\n"
        "def test_calls_production():\n"
        "    synthetic_production.fit(None)\n"
        "\n"
        "\n"
        "def test_asserts_for_itself():\n"
        "    assert synthetic_production.fit(1) == 2\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(src))
    monkeypatch.setattr(harness, "REPO", tmp_path)
    try:
        module = _load_module(_SYNTHETIC_TEST_MODULE, tests / "test_synthetic.py")
        with pytest.raises(AssertionError) as production_exc:
            module.test_calls_production()
        with pytest.raises(AssertionError) as own_exc:
            module.test_asserts_for_itself()
        production_frames = [str(entry.path) for entry in production_exc.traceback]
        own_frames = [str(entry.path) for entry in own_exc.traceback]
    finally:
        sys.modules.pop(_SYNTHETIC_TEST_MODULE, None)
        sys.modules.pop("synthetic_production", None)

    production_frame = harness._repo_frame(production_frames)
    own_frame = harness._repo_frame(own_frames)
    assert production_frame == "src/synthetic_production.py"
    assert own_frame == "tests/test_synthetic.py"

    nodeid = "tests/test_synthetic.py::test_calls_production"
    killed = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 1, frozenset({nodeid}), kind="AssertionError", frame=own_frame),
        nodeid=nodeid,
    )
    assert killed == harness.KILLED

    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 1, frozenset({nodeid}), kind="AssertionError", frame=production_frame),
        nodeid=nodeid,
    )
    assert verdict != harness.KILLED
    assert "frame outside the test module: src/synthetic_production.py" in verdict


def test_repo_frame_skips_venv_frames_and_picks_the_test_module(harness):
    """The `.venv/` exclusion is what makes the frame rule usable at all.

    `pytest.fail` and an unfulfilled `pytest.raises` leave `_pytest/outcomes.py`
    as the DEEPEST traceback frame, and the virtualenv lives INSIDE `REPO` -- so
    without the exclusion the last "repository-owned" frame of a legitimate kill
    would be pytest's own module and those cases would all be scored
    `HARNESS_FAILURE (frame outside the test module: .venv/...)`. The full 20/20
    run exercises the branch on the 9 cases that end there; a smaller run would
    not, so the branch is pinned directly rather than only incidentally.
    """
    test_module = "tests/alive/compose/test_x.py"
    venv_module = ".venv/lib/python3.11/site-packages/_pytest/outcomes.py"
    frames = [str(harness.REPO / test_module), str(harness.REPO / venv_module)]

    assert harness._repo_frame(frames) == test_module

    # Anti-tautology: the venv frame really is under `REPO` (so it is the exclusion
    # that drops it, not a failed prefix match), and a traceback of nothing but venv
    # frames owns no repository frame at all.
    assert str(harness.REPO / venv_module).startswith(str(harness.REPO) + "/")
    assert harness._repo_frame([str(harness.REPO / venv_module)]) is None


# --------------------------------------------------------------------------- #
# Rule 6 — the killer must be the test whose own name makes the claim.
# --------------------------------------------------------------------------- #
def test_a_failure_of_some_other_test_is_not_a_kill_for_this_case(harness):
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 1, frozenset({_OTHER_NODEID}), kind="AssertionError"),
        nodeid=_IO_NODEID,
    )
    assert verdict != harness.KILLED
    assert verdict == harness.HARNESS_FAILURE


def test_a_green_mutant_is_a_survivor_not_a_kill(harness):
    verdict = harness.classify(
        baseline=_green_baseline(harness),
        mutant=_run(harness, 0, frozenset()),
        nodeid=_IO_NODEID,
    )
    assert verdict == harness.SURVIVED


def test_a_red_baseline_invalidates_the_case_even_when_the_mutant_dies(harness):
    """Without a green baseline through the SAME machinery, a "kill" could be the
    module re-execution breaking the test rather than the mutation."""
    verdict = harness.classify(
        baseline=_run(harness, 1, frozenset({_IO_NODEID}), kind="AssertionError"),
        mutant=_run(harness, 1, frozenset({_IO_NODEID}), kind="AssertionError"),
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
    assert baseline.call_kind is None
    assert mutant.returncode == 1
    assert _IO_NODEID in mutant.failed
    assert mutant.call_kind == "Failed"  # pytest.raises DID NOT RAISE
    assert harness.classify(baseline=baseline, mutant=mutant, nodeid=_IO_NODEID) == harness.KILLED


def test_the_engine_reports_a_real_stray_exception_as_a_harness_failure(harness):
    """The rule-8 trap, measured rather than simulated: a mutation that makes the
    named test raise `RuntimeError` reddens it, and must NOT be scored a kill."""
    baseline = harness.run_case_detail("alive.io", "", "", _IO_NODEID)
    mutant = harness.run_case_detail(
        "alive.io",
        "    destination = Path(path)",
        '    raise RuntimeError("mutant: red, but not this test\'s assertion")\n'
        "    destination = Path(path)",
        _IO_NODEID,
    )
    assert mutant.returncode == 1
    assert _IO_NODEID in mutant.failed  # rule 4 would have called this a kill
    assert mutant.call_kind == "RuntimeError"
    verdict = harness.classify(baseline=baseline, mutant=mutant, nodeid=_IO_NODEID)
    assert verdict != harness.KILLED
    assert "non-assertion: RuntimeError" in verdict


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
# The roster itself: no invented names, no silently skipped enforcement point.
# --------------------------------------------------------------------------- #
def _nodeid_exists(nodeid: str) -> bool:
    path, _, rest = nodeid.partition("::")
    function = rest.split("::")[-1].split("[")[0]
    file_path = _REPO / path
    return file_path.exists() and f"def {function}" in file_path.read_text(encoding="utf-8")


def test_every_registered_case_pins_a_nodeid_that_really_exists(harness):
    """A case whose killer name was invented would report `HARNESS_FAILURE` at run
    time, but only when someone runs it. Pin it statically as well."""
    missing = [
        case.nodeid
        for case in (*harness.CASES, *harness.SANDBOX_CASES)
        if not _nodeid_exists(case.nodeid)
    ]
    assert not missing, f"registered killer nodeids that do not exist: {missing}"


def test_the_producer_script_is_harnessed_in_a_sandbox_rather_than_skipped(harness):
    """A script's test loads it from a path, so an in-memory module mutation is
    invisible to it -- but that does NOT require writing the tracked file, and the
    first version of this harness wrongly said it did. The sandbox case is the
    correction, so pin that it exists and that its target is a real repo file."""
    assert harness.SANDBOX_CASES, "the producer enforcement point must stay measured"
    for case in harness.SANDBOX_CASES:
        assert (_REPO / case.relative_target).exists()
        assert harness.SANDBOX_TOKEN in case.redirect_new
        redirect_target = _REPO / case.redirect_module.replace(".", "/")
        assert redirect_target.with_suffix(".py").exists()


def test_the_sandbox_case_kills_by_assertion_and_leaves_the_tracked_script_alone(harness):
    """End-to-end for finding #2: baseline green with the redirect alone, mutant
    killed by the named test's own assertion, tracked producer byte-identical."""
    case = harness.SANDBOX_CASES[0]
    tracked = _REPO / case.relative_target
    before = hashlib.sha256(tracked.read_bytes()).hexdigest()

    baseline, mutant = harness.run_sandbox_case(case)

    assert hashlib.sha256(tracked.read_bytes()).hexdigest() == before
    assert baseline.returncode == 0, f"redirect alone must be green: {baseline.summary}"
    assert mutant.call_kind == "AssertionError"
    assert harness.classify(baseline=baseline, mutant=mutant, nodeid=case.nodeid) == harness.KILLED
