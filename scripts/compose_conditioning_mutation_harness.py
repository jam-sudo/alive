"""Mutation harness for the registered conditioning ceiling (both arms).

Committed because its ABSENCE was a named root cause. Three review rounds each
found surviving mutations in this feature; the harness that proved the previous
round's kills lived only in a scratch directory, so it could not be re-run,
extended, or regression-tested, and each round rediscovered the same family one
seat over. The evidence for "all mutations killed" has to be re-runnable or it is
just a sentence in a commit message.

Each entry applies a textual mutation to ONE file under `src/` or `tests/`, runs
the targeted suite, and restores the file. (M6 additionally injects a helper class
it needs; that second substitution is anchor-checked like the first.)

A mutation that leaves the suite GREEN survived and is a defect in the tests, not
in the source. A mutation that produces no failing test at all is reported INVALID
-- neither a kill nor a survivor -- because it is evidence about the process.

FIVE RULES, every one of them learned by this harness getting it wrong:

1. For every test, run the mutation its own NAME describes and confirm it dies.
2. An index- or value-to-constant mutation must use the constant the CORRECT
   ANSWER actually takes -- never a conspicuous sentinel like ``99``. A sentinel
   dies against any assertion that mentions the real value, so it certifies the
   class while the real defect lives. See the retired M8 below: it did exactly
   that for two review rounds. Better still, build the fixture so the correct
   answer is not a constant any mutation would guess -- which is why the degenerate
   fold is parameterised rather than always fold 0. This is the strongest of the
   rules, not a footnote to rule 2: it is what actually closed the constant class.
4. A kill must be attested by a NAMED FAILING TEST, never by a nonzero exit code.
   A mutant that breaks collection exits nonzero with zero failing tests, and
   scoring on the exit code records that as a kill -- a statement about the
   process, not about the tests. Demonstrated by review with a one-character
   syntax break: three collection errors, no assertion, recorded "killed". This
   harness now reports such a run as INVALID, which is neither a kill nor a
   survivor.
5. The mutable file set must cover every site that ENFORCES the contract, not
   only the two where it is implemented. Rules 1-4 govern how an entry is written;
   none of them governs which sites have an entry at all. Sites currently
   enforcing the ceiling and NOT mutated here: `phi_rank.py`, `phase2a.py`,
   `config2.py`, `driver/preflight_cmd.py`. The suite does cover them
   (`test_phase2a_forwards_the_registered_ceiling_rather_than_a_literal` catches a
   hardcoded literal), but that coverage is asserted, not measured here.

Run: ``uv run python scripts/compose_conditioning_mutation_harness.py``

The ``# noqa: E501`` markers below are deliberate: those strings are VERBATIM
source fragments and must match the file byte-for-byte, so they cannot be wrapped.
An anchor that stops matching is reported as ``SKIP``/``ANCHOR`` rather than as a
kill — silently counting a non-applied mutation as killed is the failure this
harness exists to prevent.

SAFETY. This script edits files under ``src/`` AND ``tests/`` in place and restores
them from a backup in ``finally``. It refuses to start on a dirty worktree, so an
interrupted run can always be recovered with ``git checkout --``. It never touches
``configs/`` and never runs a scientific command: every mutation here is
synthetic-suite only.

**It must not share a worktree with anything else.** A concurrent reader — an
independent review, another agent, an editor — will observe a mutated tree
mid-run. That happened during a review of this branch. A concurrent on-disk
mutation can only produce a spurious FAILURE and never a spurious pass, so it does
not corrupt evidence, but it will confuse anyone reading `git status`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRATCH = REPO / "artifacts" / "mutation-harness-backup"
SELECT = REPO / "src/alive/compose/select.py"
DIAG = REPO / "src/alive/compose/diagnostics2.py"
TESTS_FILE = REPO / "tests/alive/compose/test_condition_ceiling.py"
TESTS = [
    "tests/alive/compose/test_condition_ceiling.py",
    "tests/alive/compose/test_select.py",
    "tests/alive/compose/test_diagnostics2.py",
]

RANK_BLOCK = (
    "    deficient = [(index, report) for index, report in enumerate(reports)"
    " if not report.is_full_rank]"
)

OVER_EXPR = """    over = [
        (index, float(report.condition_number))
        for index, report in enumerate(reports)
        if np.isfinite(report.condition_number) and float(report.condition_number) > ceiling
    ]"""

MUTATIONS = [
    (
        "M1  the fold ceiling never fires",
        SELECT,
        "if np.isfinite(report.condition_number) and float(report.condition_number) > ceiling",
        "if False and np.isfinite(report.condition_number)",
    ),
    (
        "M2  applied at every lambda, not only the unregularized one",
        SELECT,
        "    if require_full_rank_unregularized and float(lam) == 0.0:\n        _screen_unregularized_folds(",  # noqa: E501
        "    if require_full_rank_unregularized:\n        _screen_unregularized_folds(",
    ),
    (
        "M3  FOLD arm bound becomes exclusive (> -> >=)",
        SELECT,
        "and float(report.condition_number) > ceiling",
        "and float(report.condition_number) >= ceiling",
    ),
    (
        # Renamed to what it DOES. It was called "conditioning checked BEFORE rank"
        # while deleting the rank pre-pass outright -- a strict superset, so its kill
        # was evidence for the larger defect and said nothing about ordering. A live
        # Rule-1 violation, in the harness committed after the rules were written.
        # M4b below performs the reorder the old name claimed.
        "M4  the rank pre-pass is deleted outright",
        SELECT,
        RANK_BLOCK,
        "    deficient = []  # rank pass disabled: conditioning now decides first",
    ),
    (
        "M4b TRUE reorder: the conditioning arm is evaluated BEFORE the rank arm",
        SELECT,
        RANK_BLOCK,
        "    _ceiling_first = float(condition_ceiling)\n"
        "    _over_first = [\n"
        "        (i, float(r.condition_number))\n"
        "        for i, r in enumerate(reports)\n"
        "        if np.isfinite(r.condition_number) and float(r.condition_number) > _ceiling_first\n"  # noqa: E501
        "    ]\n"
        "    if _over_first:\n"
        "        raise FoldConditioningError(\n"
        '            f"{CEILING_REASON_PREFIX}: {FOLD_CEILING_MARKER} {_over_first[0][0]} "\n'
        '            f"condition_number={_over_first[0][1]} > "\n'
        '            f"condition_ceiling={_ceiling_first} at lam=0.0 (mutant reorder)"\n'
        "        )\n" + RANK_BLOCK,
    ),
    (
        "M5  the reason drops the prefix diagnostics2 keys on",
        SELECT,
        'f"{CEILING_REASON_PREFIX}: {FOLD_CEILING_MARKER} {first_index} "',
        'f"{FOLD_CEILING_MARKER} {first_index} "',
    ),
    (
        "M6  the fold screen is swallowed without recording a reason",
        SELECT,
        "            except FoldConditioningError as exc:",
        "            except FoldConditioningError:\n                continue\n            except _Never as exc:",  # noqa: E501
    ),
    (
        "M7  the context line names k_total instead of the candidate",
        DIAG,
        "        (int(candidate[0]), float(candidate[1]))",
        "        int(candidate[0])",
    ),
    # M8 RETIRED, and the reason is the most instructive entry in this file.
    # It mutated this same site to the sentinel `99` and was recorded as KILLED in
    # round 1 -- but `99` died only because a test asserted the literal substring
    # "OOF train fold 0". The constant that mattered, `0`, SURVIVED two further
    # rounds under a name ("the reported fold index is a constant") that claimed the
    # whole class. The harness had acquired the exact defect it exists to find:
    # asserting a weaker property than the name claims, then recording the name.
    # M23 below supersedes it with the correct-answer constant.
    (
        "M9  FOLD arm isfinite guard is deleted",
        SELECT,
        "if np.isfinite(report.condition_number) and float(report.condition_number) > ceiling",
        "if float(report.condition_number) > ceiling",
    ),
    (
        "M10 only the first over-ceiling fold is named",
        SELECT,
        "        if len(over) > 1:",
        "        if False:",
    ),
    (
        "M11 [reviewer] prefix contract weakened to a substring match",
        DIAG,
        "if reason.startswith(CEILING_REASON_PREFIX)",
        "if CEILING_REASON_PREFIX in reason",
    ),
    (
        "M12 [reviewer] the estimator guard is added to the fold branch",
        SELECT,
        "            except FoldConditioningError as exc:\n",
        "            except FoldConditioningError as exc:\n"
        "                if type(model_factory()) is not _OOF_SELECTION_MODEL:\n"
        '                    raise SelectionError("estimator guard") from exc\n',
    ),
    (
        "M13 [r2] RANK arm fold index is a constant",
        SELECT,
        'f"OOF train fold {first_index}: unregularized calibration design "',
        'f"OOF train fold 0: unregularized calibration design "',
    ),
    (
        "M14 [r2] rank arm reports the FIRST fold's rank for all",
        SELECT,
        'f"rank={first_report.rank}, sym_dim={first_report.sym_dim}, lam={0.0!r}{also}"',
        'f"rank={reports[0].rank}, sym_dim={reports[0].sym_dim}, lam={0.0!r}{also}"',
    ),
    (
        "M15 [r2] rank pre-pass skips the LAST fold",
        SELECT,
        "(index, report) for index, report in enumerate(reports) if not report.is_full_rank",
        "(index, report) for index, report in enumerate(reports[:-1]) if not report.is_full_rank",
    ),
    (
        "M16 [r2] also-clause names a fold that does not exist",
        SELECT,
        'f"fold {index} at {condition}" for index, condition in over[1:]',
        'f"fold {index + 1} at {condition}" for index, condition in over[1:]',
    ),
    (
        "M17 [r2] also-clause names ALL folds, not the over-ceiling ones",
        SELECT,
        "for index, condition in over[1:]",
        "for index, condition in [(i, float(r.condition_number)) for i, r in enumerate(reports)][1:]",  # noqa: E501
    ),
    (
        "M18 [r2] 'every' becomes 'the second'",
        SELECT,
        "for index, condition in over[1:]",
        "for index, condition in over[1:2]",
    ),
    (
        "M19 [r2] rank arm raises the conditioning type",
        SELECT,
        '        raise SingularDesignError(\n            f"OOF train fold {first_index}',
        '        raise FoldConditioningError(\n            f"OOF train fold {first_index}',
    ),
    (
        "M20 [r2] the estimator escalation is removed",
        SELECT,
        "                if type(model_factory()) is not _OOF_SELECTION_MODEL:",
        "                if False:",
    ),
    (
        "M21 [r2] rank arm names only the first deficient fold",
        SELECT,
        "        if len(deficient) > 1:",
        "        if False:",
    ),
    (
        "M22 [r2] the noise default is silently zeroed",
        TESTS_FILE,
        "noise: float = 1e-2, degenerate_fold: int = 0",
        "noise: float = 0.0, degenerate_fold: int = 0",
    ),
    (
        "M9b CANDIDATE arm isfinite guard is deleted",
        SELECT,
        "if np.isfinite(candidate_condition) and candidate_condition > float(condition_ceiling):",
        "if candidate_condition > float(condition_ceiling):",
    ),
    (
        "M3b CANDIDATE arm bound becomes exclusive (> -> >=)",
        SELECT,
        "and candidate_condition > float(condition_ceiling):",
        "and candidate_condition >= float(condition_ceiling):",
    ),
    (
        "M23 [r3] CONDITIONING arm primary fold index is a constant",
        SELECT,
        'f"{CEILING_REASON_PREFIX}: {FOLD_CEILING_MARKER} {first_index} "',
        'f"{CEILING_REASON_PREFIX}: {FOLD_CEILING_MARKER} 0 "',
    ),
    (
        "M24 [r3] RANK also-clause 'every' becomes 'the second'",
        SELECT,
        "for index, report in deficient[1:]",
        "for index, report in deficient[1:2]",
    ),
    (
        "M25 [r3] RANK also-clause values taken from the first fold",
        SELECT,
        'f"fold {index} at rank {report.rank}/{report.sym_dim}"',
        'f"fold {index} at rank {first_report.rank}/{first_report.sym_dim}"',
    ),
    (
        "M26 [r3] RANK also-clause swaps rank and sym_dim",
        SELECT,
        'f"fold {index} at rank {report.rank}/{report.sym_dim}"',
        'f"fold {index} at rank {report.sym_dim}/{report.rank}"',
    ),
    (
        "M27 [r3] RANK also-clause header loses its meaning",
        SELECT,
        'also = "; also rank-deficient: " + ", ".join(',
        'also = "; also: " + ", ".join(',
    ),
    (
        "M28 [r3] CONDITIONING also-clause values misattributed",
        SELECT,
        'f"fold {index} at {condition}" for index, condition in over[1:]',
        'f"fold {index} at {first_condition}" for index, condition in over[1:]',
    ),
    (
        "M29 [r3] candidate arm's measured value is a constant",
        SELECT,
        'f"condition_number={candidate_condition} > "',
        'f"condition_number=0.0 > "',
    ),
    (
        "M30 [r3] context line reports every removal as lam=0.0",
        DIAG,
        "        (int(candidate[0]), float(candidate[1]))",
        "        (int(candidate[0]), 0.0)",
    ),
    (
        "M31 [r3] fold reason rewritten for an unregistered estimator",
        SELECT,
        "                nonviable_candidates[candidate] = str(exc)\n                continue\n            except SingularDesignError as exc:",  # noqa: E501
        "                nonviable_candidates[candidate] = str(exc) + (\n"
        '                    "" if type(model_factory()) is _OOF_SELECTION_MODEL else " [rewritten]"\n'  # noqa: E501
        "                )\n                continue\n            except SingularDesignError as exc:",  # noqa: E501
    ),
]


def _key(path: Path) -> str:
    """Backup name keyed by RELATIVE PATH, not basename.

    Two mutable files sharing a basename would otherwise restore each other's
    contents into the wrong file.
    """
    return str(path.relative_to(REPO)).replace("/", "__")


def run_suite() -> tuple[frozenset[str], str]:
    """Run the suite and return the set of FAILED test node IDs, plus the summary.

    Returning the FAILURES rather than the exit code is the whole point. A mutant
    that makes a module unimportable produces collection ERRORS and a nonzero exit
    with ZERO failing tests; scoring on ``returncode`` records that as a kill,
    which is a statement about the process and not about the tests. Independent
    review demonstrated it with a one-character syntax break: three collection
    errors, no assertion, recorded "killed". Every kill in the old logs meant only
    "the process exited nonzero".
    """
    proc = subprocess.run(
        ["uv", "run", "pytest", "-q", "-rf", *TESTS], cwd=REPO, capture_output=True, text=True
    )
    out = proc.stdout or ""
    failed = frozenset(
        line.split()[1]
        for line in out.splitlines()
        if line.startswith("FAILED ") and len(line.split()) > 1
    )
    lines = [line for line in out.strip().splitlines() if line.strip()]
    return failed, lines[-1] if lines else "(no output)"


def main() -> int:
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    if dirty:
        print("REFUSING: worktree is dirty. This harness edits src/ in place.")
        print(dirty)
        return 2
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for path in (SELECT, DIAG, TESTS_FILE):
        shutil.copy2(path, SCRATCH / _key(path))

    failed, line = run_suite()
    if failed:
        print(f"BASELINE RED -- aborting: {line}")
        return 2
    print(f"baseline green: {line}\n")

    survived: list[str] = []
    invalid: list[str] = []
    try:
        for name, path, old, new in MUTATIONS:
            original = (SCRATCH / _key(path)).read_text(encoding="utf-8")
            n = original.count(old)
            if n != 1:
                print(f"SKIP      {name}: anchor matched {n} times")
                survived.append(f"{name} (ANCHOR)")
                continue
            mutant = original.replace(old, new)
            if "_Never" in new:
                helper = "class _Never(Exception):\n    pass\n\n\n"
                target = "class FoldConditioningError(SelectionError):"
                if mutant.count(target) != 1:
                    print(f"SKIP      {name}: _Never helper anchor matched {mutant.count(target)}")
                    survived.append(f"{name} (ANCHOR)")
                    continue
                mutant = mutant.replace(target, helper + target)
            path.write_text(mutant, encoding="utf-8")
            killers, line = run_suite()
            path.write_text(original, encoding="utf-8")

            if killers:
                shown = ", ".join(sorted(k.split("::")[-1] for k in killers)[:3])
                extra = f" (+{len(killers) - 3} more)" if len(killers) > 3 else ""
                print(f"killed    {name}\n          by: {shown}{extra}")
            elif line.startswith("(no output)") or "error" in line.lower():
                # nonzero exit with NO failing test: the mutant broke collection or
                # the environment. That is not evidence about the tests.
                print(f"INVALID   {name}: no test failed -- {line}")
                invalid.append(name)
            else:
                print(f"SURVIVED  {name}\n          {line}")
                survived.append(name)
    finally:
        for path in (SELECT, DIAG, TESTS_FILE):
            shutil.copy2(SCRATCH / _key(path), path)

    failed, line = run_suite()
    print(f"\nrestored, suite clean: {not failed} ({line})")
    if survived or invalid:
        if survived:
            print("\nSURVIVING:")
            for name in survived:
                print(f"  - {name}")
        if invalid:
            print("\nINVALID (no assertion fired -- not evidence of a kill):")
            for name in invalid:
                print(f"  - {name}")
        return 1
    print(f"\nall {len(MUTATIONS)} mutations killed, each by a named failing test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
