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
   The engine below exits nonzero for anchor failures and for module-reexecution
   crashes too, so the exit code alone cannot tell a kill from a broken harness.
5. The mutable file set must cover every site that ENFORCES the contract.
6. The kill must be by the test whose OWN NAME makes the claim -- anything else
   is ``IRRELEVANT``, not a kill. This harness pins ONE nodeid per case and
   scores nothing else, so rule 6 is structural here rather than a discipline.
7. A contract with REDUNDANT enforcement only dies when EVERY site enforcing it
   dies. A single-site mutation that SURVIVES may be measuring the redundancy;
   measure WHICH LINE raised before blaming the test. The producer row in
   ``NOT_HARNESSED_CASES`` is exactly such a case, and its standing record says
   which line raised.

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
    raise SystemExit(pytest.main(["-q", "-rf", nodeid]))

The tracked tree is never written, so this harness does NOT require a clean
worktree the way its siblings do -- but run it from one anyway, because a kill
recorded against uncommitted source is evidence about a tree nobody else has.

The same machinery mutates TEST modules (the kernel-isolation digest pin): the
child imports the test module under the dotted name pytest itself computes, so
``pytest.main`` finds it already in ``sys.modules`` and reuses the mutated copy.

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
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: The child exits with this when an anchor does not occur exactly once. Distinct
#: from every pytest exit code so a missing target can never be read as a result.
ANCHOR_EXIT = 97

KILLED = "KILLED"
SURVIVED = "SURVIVED"
HARNESS_FAILURE = "HARNESS_FAILURE"
NOT_HARNESSED = "NOT_HARNESSED"

_CHILD_PROGRAM = r"""
import importlib
import json
import sys
from pathlib import Path

payload = json.loads(sys.argv[1])
sys.path.insert(0, payload["repo"])

import pytest  # noqa: E402  (after sys.path so the repo's own packages resolve)

module = importlib.import_module(payload["module"])
source = Path(module.__file__).read_text(encoding="utf-8")
for old, new in payload["edits"]:
    occurrences = source.count(old)
    if occurrences != 1:
        print(f"ANCHOR: mutation target occurs {occurrences} times, expected exactly 1")
        print(f"ANCHOR: target={old!r}")
        raise SystemExit(97)
    source = source.replace(old, new)
# In-memory only: the file on disk is never written.
exec(compile(source, module.__file__, "exec"), module.__dict__)
raise SystemExit(pytest.main(["-q", "-rf", "-p", "no:cacheprovider", payload["nodeid"]]))
"""


@dataclass(frozen=True)
class CaseRun:
    """One pytest invocation: its exit code AND the node IDs that really failed."""

    returncode: int
    failed: frozenset[str]
    summary: str


@dataclass(frozen=True)
class Case:
    """One mutation, its module, and the single test whose name makes the claim."""

    name: str
    module: str
    old: str
    new: str
    nodeid: str
    extra_edits: tuple[tuple[str, str], ...] = field(default=())


@dataclass(frozen=True)
class NotHarnessedCase:
    """An enforcement point this engine deliberately cannot reach, and why."""

    name: str
    reason: str
    standing_record: str


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
        "tests/alive/compose/test_outcome_store.py"
        "::TestExactUnionEnforcement::test_unknown_id_refused",
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
        "::test_an_os_error_on_the_manifest_re_read_is_an_assembler_error[error0]",
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
)


NOT_HARNESSED_CASES: tuple[NotHarnessedCase, ...] = (
    NotHarnessedCase(
        name="producer's early admission refusal "
        "(scripts/compose/measure_pseudobulk_approximation_bias.py)",
        reason=(
            "the producer is a SCRIPT, and its test loads it with "
            "importlib.util.spec_from_file_location on the file path -- so it re-reads the "
            "bytes from disk every call and an in-memory module mutation is invisible to it. "
            "Reaching it would mean writing the tracked file, which this engine refuses to do."
        ),
        standing_record=(
            "Task 1 report §C 'Mutation runs' M2 (sandbox copy, tracked tree never mutated): "
            "admission_status stamped ADMITTED unconditionally -> "
            "FAILED tests/alive/compose/test_approximation_bias_metric.py"
            "::test_a_log_normalized_probe_a_pass_does_not_admit_a_raw_count_report, and with "
            "BOTH enforcement sites removed the same named test still dies by its own "
            "assertion ('assert admitted == NOT_ADMISSIBLE') -- rule 7 measured, not assumed."
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


def run_case_detail(
    module_name: str,
    old: str,
    new: str,
    nodeid: str,
    *,
    extra_edits: tuple[tuple[str, str], ...] = (),
) -> CaseRun:
    """Mutate ``module_name`` in memory inside a subprocess and run one nodeid.

    An empty ``old`` means "apply no edit": that is the BASELINE control, which
    still imports and re-executes the module through the identical machinery.

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
        Further anchored substitutions applied in order, for a contract whose
        coherent mutation needs more than one site inside the same module.

    Returns
    -------
    CaseRun
        Exit code, the set of node IDs pytest reported as FAILED, and the
        summary line.
    """
    edits = [[old, new]] if old else []
    edits.extend([list(edit) for edit in extra_edits])
    payload = json.dumps(
        {"repo": str(REPO), "module": module_name, "edits": edits, "nodeid": nodeid}
    )
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_PROGRAM, payload],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    stdout = proc.stdout or ""
    failed, summary = _parse(stdout)
    if proc.returncode == ANCHOR_EXIT:
        anchor = [line for line in stdout.splitlines() if line.startswith("ANCHOR:")]
        summary = anchor[0] if anchor else summary
    elif not stdout.strip() and proc.stderr:
        summary = (proc.stderr.strip().splitlines() or ["(no output)"])[-1]
    return CaseRun(returncode=proc.returncode, failed=failed, summary=summary)


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
    """Score one case. ``KILLED`` requires a named failure of ``nodeid`` itself.

    A kill is exactly: baseline green through this machinery, then the SAME node
    ID reported FAILED by the mutant run. Everything else -- collection errors,
    usage errors, a crash while re-executing the module, an anchor miss, or a
    different test going red -- is a harness failure, not a kill.
    """
    if baseline.returncode != 0 or baseline.failed:
        return HARNESS_FAILURE
    if mutant.returncode == 0 and not mutant.failed:
        return SURVIVED
    if mutant.returncode == 1 and nodeid in mutant.failed:
        return KILLED
    return HARNESS_FAILURE


def main() -> int:
    """Run every registered case and print the kill ledger."""
    print(f"cases: {len(CASES)} harnessed, {len(NOT_HARNESSED_CASES)} not harnessed\n")
    verdicts: list[tuple[Case, str, CaseRun, CaseRun]] = []
    for case in CASES:
        baseline = run_case_detail(case.module, "", "", case.nodeid)
        mutant = run_case_detail(
            case.module, case.old, case.new, case.nodeid, extra_edits=case.extra_edits
        )
        verdict = classify(baseline=baseline, mutant=mutant, nodeid=case.nodeid)
        verdicts.append((case, verdict, baseline, mutant))
        print(f"{verdict:<16} {case.name}")
        print(f"{'':<16} nodeid   {case.nodeid}")
        print(
            f"{'':<16} exit     baseline={baseline.returncode} mutant={mutant.returncode}"
            f"  |  {mutant.summary}"
        )
        if verdict != KILLED:
            print(f"{'':<16} baseline {baseline.summary}")
            print(f"{'':<16} failed   {sorted(mutant.failed)}")
        print()

    for row in NOT_HARNESSED_CASES:
        print(f"{NOT_HARNESSED:<16} {row.name}")
        print(f"{'':<16} why      {row.reason}")
        print(f"{'':<16} record   {row.standing_record}\n")

    killed = [c for c, v, _, _ in verdicts if v == KILLED]
    survived = [c for c, v, _, _ in verdicts if v == SURVIVED]
    broken = [c for c, v, _, _ in verdicts if v == HARNESS_FAILURE]
    print(
        f"{len(killed)} killed / {len(survived)} survived / {len(broken)} harness-failed "
        f"/ {len(NOT_HARNESSED_CASES)} not harnessed"
    )
    if survived:
        print("SURVIVED: " + "; ".join(c.name for c in survived))
    if broken:
        print("HARNESS_FAILURE: " + "; ".join(c.name for c in broken))
    if not survived and not broken:
        print("every harnessed mutation was killed by the test whose own name makes the claim")
    print(
        "\nThis is a mutation ledger for local enforcement points. It is NOT a "
        "readiness signal: COMPOSE-K562-v1 stays RELEASE-BLOCKED with the seal UNOPENED."
    )
    return 0 if not survived and not broken else 1


if __name__ == "__main__":
    raise SystemExit(main())
