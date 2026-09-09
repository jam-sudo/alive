#!/usr/bin/env python
"""Mutation harness for the enforcement points the 2026-09-07 audit wave changed.

A sibling of ``compose_conditioning_mutation_harness.py``,
``compose_lambda_scaling_mutation_harness.py`` and
``compose_receipt_interpreter_mutation_harness.py``. Deliberately separate rather
than a refactor of any of them: each backs its own standing kill record, and
rewriting shared machinery would invalidate committed evidence to save sixty
lines.

The rules this project earned, each added because the previous set was not
enough -- and each time the defect had moved one level OUT: code, tests, the
instrument that checks the tests, the instrument's own blind spot.

1. For every test, RUN the mutation its own NAME describes and confirm it dies.
2. An index/value-to-constant mutation must use the constant the CORRECT ANSWER
   takes, never a conspicuous sentinel.
3. Better still, build the fixture so the correct answer is not a constant any
   mutation would guess.
4. A kill must be attested by a NAMED FAILING TEST, never a nonzero exit code.
5. The mutable file set must cover every site that ENFORCES the contract.
6. The kill must be by the test whose OWN NAME makes the claim -- anything else
   is ``IRRELEVANT``, not a kill. This harness pins ONE nodeid per case and
   scores nothing else, so rule 6 is structural here rather than a discipline.
7. A contract with REDUNDANT enforcement only dies when EVERY site enforcing it
   dies. A single-site mutation that SURVIVES may be measuring the redundancy;
   measure WHICH LINE raised before blaming the test.
8. **A kill must be attested by the ASSERTION the test makes, not merely by the
   test going red.** Rule 4 stopped at "a named FAILED line", and that is not
   enough: a mutant can make an unrelated exception escape from deep inside the
   call and the named test then fails for a reason it never claimed. Two cases
   in this very roster did exactly that -- removing the exact-sealed-union guard
   left a downstream ``KeyError``, and narrowing the manifest re-read's ``except``
   let a raw ``FileNotFoundError`` escape -- and both were being recorded as
   kills. So the child now records the call-phase exception KIND for the pinned
   nodeid and only ``AssertionError`` / pytest's ``Failed`` (``pytest.fail``,
   ``pytest.raises`` DID-NOT-RAISE) count. Anything else is
   ``HARNESS_FAILURE (non-assertion: <Type>)``. Where a contract IS a typed
   error, the fix is a killer that asserts the TYPE, so the mutant's stray
   exception becomes an assertion-level failure.
   **Second level: the KIND does not say WHOSE assertion failed.** Production
   code carries bare ``assert`` statements, and a mutation that flips one gives
   the pinned test a genuine call-phase ``AssertionError`` while the test's own
   assertions were never reached -- measured on ``models.py``'s
   ``assert self.weights_ is not None``, which today's classifier would have
   scored ``KILLED``. So the child records the traceback's files too, and a kill
   additionally requires the LAST repository-owned frame to BE the pinned node
   ID's test module (:func:`_repo_frame`). Anything else is
   ``HARNESS_FAILURE (frame outside the test module: <path>)``.

**How this engine differs from its siblings, and why.** The siblings edit ``src/``
in place and restore in a ``finally``. This wave must not modify pinned files at
all (``src/alive/io.py``, ``src/alive/compose/approximation_bias.py``, both
``__init__.py``, ``uv.lock``), and two of the enforcement points under test live
in exactly those files. So every mutation here is applied to an **in-memory copy**
of the module source inside a subprocess:

    m = importlib.import_module(module_name)
    source = Path(m.__file__).read_text(encoding="utf-8")     # read only
    if source.count(old) != 1: raise SystemExit(ANCHOR_EXIT)
    exec(compile(source.replace(old, new), m.__file__, "exec"), m.__dict__)
    raise SystemExit(pytest.main(["-q", "-rf", nodeid], plugins=[recorder]))

The tracked tree is never written, so this harness does NOT require a clean
worktree the way its siblings do -- but run it from one anyway, because a kill
recorded against uncommitted source is evidence about a tree nobody else has.

The same machinery mutates TEST modules (the kernel-isolation digest pin): the
child imports the test module under the dotted name pytest itself computes, so
``pytest.main`` finds it already in ``sys.modules`` and reuses the mutated copy.
A case may name several modules; they are imported and re-executed in the order
given, which is how a dependency can be mutated before the test module that
imports names from it.

SCRIPTS are reached a different way (:data:`SANDBOX_CASES`). A script has no
importable module identity, and its test loads it with
``spec_from_file_location`` from a path constant -- so it re-reads the bytes from
disk on every call and an in-memory module mutation is invisible to it. That does
NOT mean the tracked file must be written: the harness copies the repo-relative
layout into a temporary root, mutates the COPY, and redirects the test module's
path constant at the sandbox (itself an in-memory edit). Baseline runs the same
redirect without the mutation, so the redirect cannot be mistaken for the effect.

BASELINE. Every case runs the *unmutated* source through the identical machinery
first. That control is what separates "the mutation killed the test" from "the
module re-execution broke the test"; a red baseline invalidates the case.

KNOWN LIMIT of the in-memory approach, stated because it is asymmetric. Re-exec
rebinds names in ``m.__dict__``, so anything imported *before* the exec that
captured the old object (``from x import f`` in an already-loaded module) keeps
the pre-mutation version. The baseline control catches the direction where
re-execution BREAKS a test; it cannot catch the direction where a stale binding
HIDES a mutation. So a ``KILLED`` here is sound, but a ``SURVIVED`` is not
automatically a defect in the tests -- re-measure it against a file-level
mutation (a sandbox copy of the tree) before recording a survivor. Every case in
the roster today is ``KILLED``, so nothing currently rests on that caveat.

Run: ``uv run python scripts/compose_audit_mutation_harness.py``
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: The child exits with this when an anchor does not occur exactly once. Distinct
#: from every pytest exit code so a missing target can never be read as a result.
ANCHOR_EXIT = 97

KILLED = "KILLED"
SURVIVED = "SURVIVED"
HARNESS_FAILURE = "HARNESS_FAILURE"

#: Call-phase exception types that ARE the test's own assertion (rule 8).
#: ``Failed`` is ``_pytest.outcomes.Failed`` -- ``pytest.fail`` and the
#: DID-NOT-RAISE of an unfulfilled ``pytest.raises``.
ASSERTION_KINDS = frozenset({"AssertionError", "Failed"})

#: Placeholder replaced with the sandbox root inside a :class:`SandboxCase` edit.
SANDBOX_TOKEN = "{sandbox}"

_CHILD_PROGRAM = r'''
import importlib
import json
import sys
from pathlib import Path

payload = json.loads(sys.argv[1])
sys.path.insert(0, payload["repo"])

import pytest  # noqa: E402  (after sys.path so the repo's own packages resolve)


class _CallPhaseRecorder:
    """Record the exception KIND of each failing phase, not just that it failed.

    ``pytest_runtest_makereport`` is a firstresult hook; returning ``None`` lets
    pytest's own implementation build the report as usual, so this observes
    without changing any outcome.
    """

    def __init__(self):
        self.records = []

    def pytest_runtest_makereport(self, item, call):
        if call.excinfo is not None:
            self.records.append(
                {
                    "nodeid": item.nodeid,
                    "when": call.when,
                    "type": call.excinfo.type.__name__,
                    "repr": repr(call.excinfo.value)[:400],
                    # Rule 8, second level: the KIND alone cannot tell the
                    # test's own assertion from a bare ``assert`` in the
                    # production code the test calls. Keep the frames so the
                    # parent can attest WHERE the assertion was raised.
                    "frames": [str(entry.path) for entry in call.excinfo.traceback],
                }
            )
        return None


for step in payload["plan"]:
    module = importlib.import_module(step["module"])
    source = Path(module.__file__).read_text(encoding="utf-8")
    for old, new in step["edits"]:
        occurrences = source.count(old)
        if occurrences != 1:
            print(
                f"ANCHOR: {step['module']}: target occurs {occurrences} times, expected exactly 1"
            )
            print(f"ANCHOR: target={old!r}")
            raise SystemExit(97)
        source = source.replace(old, new)
    # In-memory only: the file on disk is never written.
    exec(compile(source, module.__file__, "exec"), module.__dict__)

recorder = _CallPhaseRecorder()
code = pytest.main(["-q", "-rf", "-p", "no:cacheprovider", payload["nodeid"]], plugins=[recorder])
Path(payload["record_path"]).write_text(json.dumps(recorder.records), encoding="utf-8")
raise SystemExit(code)
'''


@dataclass(frozen=True)
class CaseRun:
    """One pytest invocation.

    Attributes
    ----------
    returncode
        The pytest process exit code. Never a verdict on its own (rule 4).
    failed
        Node IDs pytest reported on a ``FAILED`` line.
    summary
        Last non-blank output line, for the ledger.
    call_kind
        Exception type name raised in the *call* phase of the pinned node ID, or
        ``None`` if it did not fail there. A setup/teardown failure is reported
        as ``"<phase>:<Type>"`` so it can never be read as an assertion.
    call_repr
        ``repr`` of that exception, truncated. Evidence for the ledger.
    call_frame
        Repo-relative POSIX path of the LAST repository-owned traceback frame of
        that exception (see :func:`_repo_frame`), or ``None`` when nothing was
        recorded. A kill requires this to be the pinned node ID's own test
        module: an ``AssertionError`` raised inside production code is the
        production module's assertion, not the test's.
    """

    returncode: int
    failed: frozenset[str]
    summary: str
    call_kind: str | None = None
    call_repr: str = ""
    call_frame: str | None = None


@dataclass(frozen=True)
class Case:
    """One in-memory mutation, and the single test whose name makes the claim."""

    name: str
    module: str
    old: str
    new: str
    nodeid: str
    extra_edits: tuple[tuple[str, str], ...] = field(default=())
    #: ``(module, old, new)`` applied BEFORE ``module``'s own edits, in order.
    cross_module_edits: tuple[tuple[str, str, str], ...] = field(default=())


@dataclass(frozen=True)
class SandboxCase:
    """A mutation of a SCRIPT, measured in a temporary copy of the repo layout.

    Attributes
    ----------
    relative_target
        Repo-relative path of the script to mutate inside the sandbox.
    old, new
        The mutation, applied to the sandbox COPY (never the tracked file).
    redirect_module, redirect_old, redirect_new
        In-memory edit that points the test module's path constant at the
        sandbox. Applied to BOTH baseline and mutant, so it cannot be confused
        with the mutation's effect. ``redirect_new`` may contain
        :data:`SANDBOX_TOKEN`.
    cross_module_edits
        Further in-memory ``(module, old, new)`` edits applied only to the
        MUTANT run -- for a contract with redundant enforcement, whose other
        sites must fall too before the named test can reach its own assertion
        (rule 7 + rule 8).
    """

    name: str
    relative_target: str
    old: str
    new: str
    nodeid: str
    redirect_module: str
    redirect_old: str
    redirect_new: str
    cross_module_edits: tuple[tuple[str, str, str], ...] = field(default=())
    #: Directories copied into the sandbox root, preserving the repo layout.
    copy_dirs: tuple[str, ...] = ("scripts", "src")
    note: str = ""


# --------------------------------------------------------------------------- #
# Cases. One nodeid per case; the nodeid is the claim (rule 6).
# --------------------------------------------------------------------------- #
CASES: tuple[Case, ...] = (
    Case(
        "M01 measurability gate accepts a non-calibration role",
        "alive.compose.gates",
        "    if _role != CALIBRATION_ROLE_NAME:",
        "    if False:",
        "tests/alive/compose/test_gates.py::test_measurability_gate_refuses_sealed_array",
    ),
    Case(
        "M02 gate's measurability floor is a source literal, not the config's",
        "alive.compose.gates",
        "    passed = ceiling > ceiling_floor",
        "    passed = ceiling > 0.2",
        "tests/alive/compose/test_gates.py"
        "::test_the_measurability_floor_comes_from_the_config_not_from_the_source",
    ),
    Case(
        "M03 activation validator's floor is a source literal, not the config's",
        "alive.compose.detectable_effect",
        "    expected_measurable = ceiling > ceiling_floor",
        "    expected_measurable = ceiling > 0.2",
        "tests/alive/compose/test_detectable_effect.py"
        "::test_the_activation_validator_recomputes_against_the_registered_floor",
    ),
    Case(
        "M04 freeze accepts a mutated upstream bundle checksum",
        "alive.compose.freeze",
        "        if recomputed != self.bundle_checksum:",
        "        if False:",
        "tests/alive/compose/test_freeze.py::test_verify_fails_when_upstream_checksum_mutated",
    ),
    Case(
        "M05 sealed read no longer requires the EXACT sealed union",
        "alive.compose.outcome_store",
        "self._assert_exact_sealed_union(canon)",
        "pass",
        "tests/alive/compose/test_outcome_store.py::TestExactUnionEnforcement"
        "::test_an_unknown_pair_is_refused_by_the_contracted_error_not_a_downstream_crash",
    ),
    Case(
        "M06 once-only precheck returns before reading the durable audit",
        "alive.compose.outcome_store",
        "    def _assert_not_previously_accessed(self, run_id: str) -> None:\n"
        '        """Raise if ANY prior access exists on this audit path.',
        "    def _assert_not_previously_accessed(self, run_id: str) -> None:\n"
        "        return\n"
        '        """Raise if ANY prior access exists on this audit path.',
        "tests/alive/compose/test_outcome_store.py"
        "::TestOnceOnly::test_second_call_same_run_id_refused",
    ),
    Case(
        "M07 atomic write-once replaces instead of linking (a second write wins)",
        "alive.io",
        "os.link(temporary, destination)",
        "os.replace(temporary, destination)",
        "tests/alive/test_io.py::test_a_second_write_to_the_same_destination_is_refused",
    ),
    Case(
        "M08 the final fit scales EVERY arm, not the headline operator alone",
        "alive.compose.phase2a",
        "        if name == HEADLINE_MODEL_NAME:\n            lam_applied *= headline_lambda_scale",
        "        if True:\n            lam_applied *= headline_lambda_scale",
        "tests/alive/compose/test_lambda_scaling.py"
        "::test_the_final_fit_scales_the_headline_operator_and_leaves_the_baseline_alone",
    ),
    Case(
        "M09 the validator stops checking the Probe-A representation bridge",
        "alive.compose.approximation_bias",
        "    validate_bias_method_bridge(\n"
        '        method=str(obj["method"]),\n'
        '        probe_representation=str(provenance["probe_a_output_representation"]),\n'
        '        admission_status=str(obj["admission_status"]),\n'
        "    )",
        "    pass",
        "tests/alive/compose/test_approximation_bias_metric.py"
        "::test_a_probe_a_bridge_of_a_different_representation_does_not_admit_this_report",
    ),
    Case(
        "M10 the admission-status roster admits a third, invented status",
        "alive.compose.approximation_bias",
        "ADMISSION_STATUSES = frozenset({ADMITTED, NOT_ADMISSIBLE})",
        'ADMISSION_STATUSES = frozenset({ADMITTED, NOT_ADMISSIBLE, "provisionally_admitted"})',
        "tests/alive/compose/test_approximation_bias_metric.py"
        "::test_the_admission_status_roster_is_exactly_admitted_and_not_admissible",
    ),
    Case(
        "M11 an unregistered include_esm value loads and only moves the digest",
        "alive.compose.config2",
        "    if include_esm is not _EXPECTED_INCLUDE_ESM:",
        "    if False:",
        "tests/alive/compose/test_config2.py"
        "::test_an_unregistered_include_esm_value_is_refused_instead_of_only_moving_the_digest"
        "[False]",
    ),
    Case(
        "M12 the fixture key-roster guard stops refusing a roster it does not fill",
        "alive.compose.driver.fixture_builder",
        '        raise ValueError("fixture key roster: expected hashes mismatch")',
        "        pass",
        "tests/alive/compose/driver/test_fixture_builder.py"
        "::test_the_fixture_key_roster_guard_survives_python_optimize[EXPECTED_HASHES_KEYS]",
    ),
    Case(
        "M13 adapter_version comes from the DECLARED value, not the committed manifest",
        "alive.compose.driver.identity_lock",
        "        adapter_version = _scientific_adapter_version(expected_worker_method)",
        '        adapter_version = str(declared["adapter_version"])',
        "tests/alive/compose/driver/test_identity_lock.py"
        "::test_scientific_declared_adapter_version_mismatch_fails_closed",
    ),
    Case(
        "M14 an OSError on the digest-bound manifest re-read escapes untyped",
        "alive.compose.driver.identity_lock",
        "    except (OSError, ValueError) as exc:",
        "    except ValueError as exc:",
        "tests/alive/compose/driver/test_identity_lock.py"
        "::test_an_os_error_on_the_manifest_re_read_is_converted_not_merely_re_raised",
    ),
    Case(
        "M15 the ID-only comparator stops consuming the ESM columns (both sites)",
        "alive.compose.models",
        '        """Symmetric design matrix with an intercept column, shape ``(n, d+1)``."""\n'
        "        feats = np.vstack([_sym_id_feature(Z[g], Z[h]) for g, h in pairs])",
        '        """Symmetric design matrix with an intercept column, shape ``(n, d+1)``."""\n'
        "        feats = np.vstack([_sym_id_feature(Z[g][:-2], Z[h][:-2]) for g, h in pairs])",
        "tests/alive/compose/test_models.py"
        "::test_the_id_only_comparator_consumes_the_same_factor_bank_as_the_operator",
        extra_edits=(
            (
                "        feat = np.append(_sym_id_feature(Z[g], Z[h]), 1.0)  # intercept",
                "        feat = np.append(_sym_id_feature(Z[g][:-2], Z[h][:-2]), 1.0)  # intercept",
            ),
        ),
    ),
    Case(
        "M16 the pinned kernel-reproof digest no longer names the shipped bytes",
        "tests.alive.compose.test_kernel_isolation_ci",
        '"af0dab18086bcdf5adc3d19815ac6fa4a7695efa9f6dd1f6d58138c83f6c31c2"',
        '"' + "0" * 64 + '"',
        "tests/alive/compose/test_kernel_isolation_ci.py"
        "::test_the_v2_kernel_proof_still_covers_the_shipped_isolation_closure",
    ),
    Case(
        "M18 the sealed source is not re-hashed when consumption ends",
        "alive.compose.outcome_store",
        "        if self._post_materialization_check is not None:\n            try:",
        "        if False:\n            try:",
        "tests/alive/compose/driver/test_sealed_source_integrity_e2e.py"
        "::test_in_place_mutation_during_materialization_aborts_and_recover_agrees",
    ),
    Case(
        # The finalizer verified the block's CHECKSUM and nothing else, so a
        # self-consistent-but-WRONG pre-registered sentence published without a word
        # (measured 2026-09-09: five such terminals, all successful). Deleting the
        # re-derivation restores exactly that state -- and the pinned test, whose whole
        # subject is a sentence its own flip contradicts, must be the one that notices.
        "M20 durable takes the terminal's word for the pre-registered sentence it carries",
        "alive.compose.durable",
        "    if headline != expected_headline:",
        "    if False:",
        "tests/alive/compose/test_durable.py"
        "::test_a_headline_whose_branch_disagrees_with_the_flip_fails_closed",
    ),
)


SANDBOX_CASES: tuple[SandboxCase, ...] = (
    SandboxCase(
        name="M17 the producer stamps ADMITTED whatever the Probe-A bridge says",
        relative_target="scripts/compose/measure_pseudobulk_approximation_bias.py",
        old="        if bridge_admits(method=REPRESENTATION, "
        "probe_representation=bridge_representation)",
        new="        if True",
        nodeid="tests/alive/compose/test_approximation_bias_metric.py"
        "::test_a_log_normalized_probe_a_pass_does_not_admit_a_raw_count_report",
        redirect_module="tests.alive.compose.test_approximation_bias_metric",
        redirect_old='_SCRIPT = _REPO / "scripts" / "compose" '
        '/ "measure_pseudobulk_approximation_bias.py"',
        redirect_new='_SCRIPT = Path("' + SANDBOX_TOKEN + "/scripts/compose"
        '/measure_pseudobulk_approximation_bias.py")',
        cross_module_edits=(
            (
                "alive.compose.approximation_bias",
                "    validate_bias_method_bridge(\n"
                '        method=str(obj["method"]),\n'
                '        probe_representation=str(provenance["probe_a_output_representation"]),\n'
                '        admission_status=str(obj["admission_status"]),\n'
                "    )",
                "    pass",
            ),
        ),
        note=(
            "Redundant enforcement (rule 7): the producer's decision is re-checked by "
            "`validate_approximation_bias_report`, so the validator site falls in the same "
            "run -- otherwise the named test dies on the validator's typed error instead of "
            "its own assertion (rule 8). Task 1 measured the identical pair in a full-tree "
            "sandbox on 2026-09-07; that record is now supporting history, not the evidence."
        ),
    ),
    SandboxCase(
        name="M19 the finalizer takes the report's word for the representation it declares",
        relative_target="scripts/compose/finalize_approximation_bias_config.py",
        old="    if bridged != report_leaf:",
        new="    if False:",
        nodeid="tests/alive/compose/test_finalize_approximation_bias_config.py"
        "::test_the_finalizer_refuses_a_representation_the_probe_a_evidence_did_not_validate",
        redirect_module="tests.alive.compose.test_finalize_approximation_bias_config",
        redirect_old='_SCRIPT = _REPO / "scripts" / "compose" '
        '/ "finalize_approximation_bias_config.py"',
        redirect_new='_SCRIPT = Path("' + SANDBOX_TOKEN + "/scripts/compose"
        '/finalize_approximation_bias_config.py")',
        note=(
            "(d) is defense in depth BEHIND (e), not a live check: the validator pins the "
            "report leaf to `REPRESENTATION` and `bridge_admits` is equality, so whenever (e) "
            "passes `bridged == report_leaf` and this comparison cannot be reached THROUGH "
            "`finalize_bias_config` -- by construction, under every owner policy, not only "
            "today's. The fix for that is not "
            "to mock the admission guard in front of it (a test that mocks a guard measures "
            "the mock). The comparison is a guard-free helper and the named test calls it "
            "directly, so this mutation removes the real operator the finalizer invokes: the "
            "helper then returns instead of raising and the capture-and-assert helper in the "
            "test module reports it -- the AssertionError is the TEST's (rule 8). The call "
            "site itself is pinned by "
            "`test_the_finalizer_actually_calls_the_representation_comparison`."
        ),
    ),
)


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
def _parse(stdout: str) -> tuple[frozenset[str], str]:
    """Return the FAILED node IDs plus the last non-blank line (rule 4)."""
    failed = frozenset(
        line.split()[1]
        for line in stdout.splitlines()
        if line.startswith("FAILED ") and len(line.split()) > 1
    )
    lines = [line for line in stdout.strip().splitlines() if line.strip()]
    return failed, lines[-1] if lines else "(no output)"


def _repo_frame(frames: list[str]) -> str | None:
    """Return the LAST repository-owned traceback frame, repo-relative.

    Frames inside the virtualenv are excluded, and that exclusion is the whole
    design: ``pytest.fail`` and an unfulfilled ``pytest.raises`` both leave
    ``_pytest/outcomes.py`` / ``_pytest/raises.py`` as the deepest frame -- 9 of
    the 18 cases registered when this rule was added end there, all of them
    in-memory ones (measured 2026-09-09, not cited; later cases add to the roster
    without re-measuring it). A naive "the last frame must be the test module"
    rule would therefore break those 9 while proving nothing. What identifies
    the assertion's owner is the last frame the REPOSITORY owns: the test module
    for the test's own assertion, the production module for a bare ``assert``
    the test merely called into.

    Parameters
    ----------
    frames : list of str
        Absolute file paths of the traceback entries, outermost first.

    Returns
    -------
    str or None
        Repo-relative POSIX path, or ``None`` if no frame is repository-owned.
    """
    repo = str(REPO) + "/"
    owned = [
        frame[len(repo) :]
        for frame in frames
        if frame.startswith(repo) and not frame[len(repo) :].startswith(".venv/")
    ]
    return owned[-1] if owned else None


def _call_phase(records: list[dict], nodeid: str) -> tuple[str | None, str, str | None]:
    """Return ``(kind, repr, frame)`` for ``nodeid``'s failing phase (rule 8).

    A call-phase failure reports the bare exception type; a setup/teardown
    failure is prefixed with its phase so it can never match
    :data:`ASSERTION_KINDS`. ``frame`` is :func:`_repo_frame` of that failure.
    """
    for record in records:
        if record["nodeid"] == nodeid and record["when"] == "call":
            return (
                str(record["type"]),
                str(record["repr"]),
                _repo_frame(list(record.get("frames", []))),
            )
    for record in records:
        if record["nodeid"] == nodeid:
            return (
                f"{record['when']}:{record['type']}",
                str(record["repr"]),
                _repo_frame(list(record.get("frames", []))),
            )
    return None, "", None


def run_plan(plan: Sequence[tuple[str, Sequence[tuple[str, str]]]], nodeid: str) -> CaseRun:
    """Apply an ordered per-module edit plan in a subprocess and run one nodeid.

    Parameters
    ----------
    plan : sequence of (str, sequence of (str, str))
        ``(module, edits)`` in application order. Each module is imported, its
        source read, its anchored edits applied to an in-memory copy, and the
        result re-executed into the live module namespace. A module with no
        edits is still imported and re-executed -- that is the baseline control.
    nodeid : str
        The single pytest node ID whose own name makes the claim under test.

    Returns
    -------
    CaseRun
    """
    with tempfile.TemporaryDirectory(prefix="compose-mutation-") as scratch:
        record_path = Path(scratch) / "call_phase.json"
        payload = json.dumps(
            {
                "repo": str(REPO),
                "nodeid": nodeid,
                "record_path": str(record_path),
                "plan": [
                    {"module": module, "edits": [list(edit) for edit in edits]}
                    for module, edits in plan
                ],
            }
        )
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD_PROGRAM, payload],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        records: list[dict] = []
        if record_path.exists():
            records = json.loads(record_path.read_text(encoding="utf-8"))

    stdout = proc.stdout or ""
    failed, summary = _parse(stdout)
    if proc.returncode == ANCHOR_EXIT:
        anchor = [line for line in stdout.splitlines() if line.startswith("ANCHOR:")]
        summary = anchor[0] if anchor else summary
    elif not stdout.strip() and proc.stderr:
        summary = (proc.stderr.strip().splitlines() or ["(no output)"])[-1]
    kind, detail, frame = _call_phase(records, nodeid)
    return CaseRun(
        returncode=proc.returncode,
        failed=failed,
        summary=summary,
        call_kind=kind,
        call_repr=detail,
        call_frame=frame,
    )


def run_case_detail(
    module_name: str,
    old: str,
    new: str,
    nodeid: str,
    *,
    extra_edits: tuple[tuple[str, str], ...] = (),
    cross_module_edits: tuple[tuple[str, str, str], ...] = (),
) -> CaseRun:
    """Mutate ``module_name`` in memory inside a subprocess and run one nodeid.

    An empty ``old`` means "apply no edit to ``module_name``": that is the
    BASELINE control, which still imports and re-executes the module through the
    identical machinery.

    Parameters
    ----------
    module_name : str
        Importable dotted name of the module to mutate (test modules included).
    old, new : str
        The mutation. ``old`` must occur exactly once in the module source; if it
        does not, the child exits :data:`ANCHOR_EXIT` and nothing is scored.
    nodeid : str
        The single pytest node ID whose own name makes the claim under test.
    extra_edits : tuple of (str, str), optional
        Further anchored substitutions in ``module_name``, for a contract whose
        coherent mutation needs more than one site inside the same module.
    cross_module_edits : tuple of (str, str, str), optional
        ``(module, old, new)`` applied, in order, BEFORE ``module_name`` -- so a
        dependency can be mutated before the module that imports names from it.

    Returns
    -------
    CaseRun
    """
    plan: list[tuple[str, list[tuple[str, str]]]] = [
        (module, [(o, n)]) for module, o, n in cross_module_edits
    ]
    own: list[tuple[str, str]] = ([(old, new)] if old else []) + list(extra_edits)
    plan.append((module_name, own))
    return run_plan(plan, nodeid)


def run_case(
    module_name: str,
    old: str,
    new: str,
    nodeid: str,
    *,
    extra_edits: tuple[tuple[str, str], ...] = (),
) -> int:
    """Return the pytest exit code of the mutant run (see :func:`run_case_detail`).

    The exit code alone is NOT a verdict -- :func:`classify` is. This is the
    briefed interface and it is kept honest by returning only the code.
    """
    return run_case_detail(module_name, old, new, nodeid, extra_edits=extra_edits).returncode


def classify(*, baseline: CaseRun, mutant: CaseRun, nodeid: str) -> str:
    """Score one case. ``KILLED`` requires the pinned nodeid's OWN assertion.

    A kill is exactly: baseline green through this machinery, then the SAME node
    ID reported FAILED by the mutant run **because its own assertion failed**
    (``AssertionError``, or pytest's ``Failed`` from ``pytest.fail`` / an
    unfulfilled ``pytest.raises``) **in its own module's frame**. Everything else
    -- collection errors, usage errors, a crash while re-executing the module, an
    anchor miss, a different test going red, the named test dying on a stray
    exception it never claimed, or an ``AssertionError`` that belongs to a bare
    ``assert`` in the production code the test called -- is a harness failure,
    not a kill (rules 4, 6 and 8).
    """
    if baseline.returncode != 0 or baseline.failed:
        return HARNESS_FAILURE
    if mutant.returncode == 0 and not mutant.failed:
        return SURVIVED
    if mutant.returncode == 1 and nodeid in mutant.failed:
        if mutant.call_kind not in ASSERTION_KINDS:
            return f"{HARNESS_FAILURE} (non-assertion: {mutant.call_kind})"
        test_module = nodeid.split("::")[0]
        if mutant.call_frame != test_module:
            return f"{HARNESS_FAILURE} (frame outside the test module: {mutant.call_frame})"
        return KILLED
    return HARNESS_FAILURE


def _sandbox_plan(case: SandboxCase, sandbox: Path, *, mutant: bool) -> list:
    """Edit plan for a sandbox case. The redirect is in BOTH arms."""
    plan: list[tuple[str, list[tuple[str, str]]]] = []
    if mutant:
        plan.extend((module, [(o, n)]) for module, o, n in case.cross_module_edits)
    else:
        plan.extend((module, []) for module, _, _ in case.cross_module_edits)
    redirect = case.redirect_new.replace(SANDBOX_TOKEN, str(sandbox))
    plan.append((case.redirect_module, [(case.redirect_old, redirect)]))
    return plan


def run_sandbox_case(case: SandboxCase) -> tuple[CaseRun, CaseRun]:
    """Measure a SCRIPT mutation in a temporary copy of the repo layout.

    The tracked file is never written: the repo-relative layout is copied into a
    temporary root, the COPY is mutated, and the test module's path constant is
    redirected at the sandbox. The baseline arm gets the same redirect and no
    mutation, so the redirect itself cannot be read as the effect.

    Returns
    -------
    (CaseRun, CaseRun)
        Baseline and mutant runs.
    """
    sandbox = Path(tempfile.mkdtemp(prefix="compose-script-sandbox-"))
    try:
        for name in case.copy_dirs:
            shutil.copytree(
                REPO / name,
                sandbox / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        baseline = run_plan(_sandbox_plan(case, sandbox, mutant=False), case.nodeid)

        target = sandbox / case.relative_target
        source = target.read_text(encoding="utf-8")
        occurrences = source.count(case.old)
        if occurrences != 1:
            return baseline, CaseRun(
                returncode=ANCHOR_EXIT,
                failed=frozenset(),
                summary=f"ANCHOR: {case.relative_target}: target occurs {occurrences} times",
            )
        target.write_text(source.replace(case.old, case.new), encoding="utf-8")
        mutant = run_plan(_sandbox_plan(case, sandbox, mutant=True), case.nodeid)
        return baseline, mutant
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _report(name: str, nodeid: str, verdict: str, baseline: CaseRun, mutant: CaseRun) -> None:
    print(f"{verdict:<16} {name}")
    print(f"{'':<16} nodeid   {nodeid}")
    print(
        f"{'':<16} exit     baseline={baseline.returncode} mutant={mutant.returncode}"
        f"  |  kind={mutant.call_kind}  |  frame={mutant.call_frame}"
        f"  |  {mutant.summary}"
    )
    print(f"{'':<16} raised   {mutant.call_repr or '(none)'}")
    if not verdict.startswith(KILLED):
        print(f"{'':<16} baseline {baseline.summary}")
        print(f"{'':<16} failed   {sorted(mutant.failed)}")
    print()


def main() -> int:
    """Run every registered case and print the kill ledger."""
    print(f"cases: {len(CASES)} in-memory, {len(SANDBOX_CASES)} sandboxed script\n")
    verdicts: list[tuple[str, str]] = []

    for case in CASES:
        baseline = run_case_detail(
            case.module, "", "", case.nodeid, cross_module_edits=case.cross_module_edits
        )
        mutant = run_case_detail(
            case.module,
            case.old,
            case.new,
            case.nodeid,
            extra_edits=case.extra_edits,
            cross_module_edits=case.cross_module_edits,
        )
        verdict = classify(baseline=baseline, mutant=mutant, nodeid=case.nodeid)
        verdicts.append((case.name, verdict))
        _report(case.name, case.nodeid, verdict, baseline, mutant)

    for sandbox_case in SANDBOX_CASES:
        baseline, mutant = run_sandbox_case(sandbox_case)
        verdict = classify(baseline=baseline, mutant=mutant, nodeid=sandbox_case.nodeid)
        verdicts.append((sandbox_case.name, verdict))
        _report(sandbox_case.name, sandbox_case.nodeid, verdict, baseline, mutant)
        if sandbox_case.note:
            print(f"{'':<16} note     {sandbox_case.note}\n")

    killed = [name for name, verdict in verdicts if verdict == KILLED]
    survived = [name for name, verdict in verdicts if verdict == SURVIVED]
    broken = [(name, v) for name, v in verdicts if v.startswith(HARNESS_FAILURE)]
    print(
        f"{len(killed)} killed / {len(survived)} survived / {len(broken)} harness-failed "
        f"(of {len(verdicts)} cases)"
    )
    if survived:
        print("SURVIVED: " + "; ".join(survived))
    if broken:
        print("HARNESS_FAILURE: " + "; ".join(f"{name} -> {v}" for name, v in broken))
    if not survived and not broken:
        print(
            "every mutation was killed by the ASSERTION of the test whose own name makes the claim"
        )
    print(
        "\nThis is a mutation ledger for local enforcement points. It is NOT a "
        "readiness signal: COMPOSE-K562-v1 stays RELEASE-BLOCKED with the seal UNOPENED."
    )
    return 0 if not survived and not broken else 1


if __name__ == "__main__":
    raise SystemExit(main())
