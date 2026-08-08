"""Mutation harness for the registered conditioning ceiling (both arms).

Committed because its ABSENCE was a named root cause. Three review rounds each
found surviving mutations in this feature; the harness that proved the previous
round's kills lived only in a scratch directory, so it could not be re-run,
extended, or regression-tested, and each round rediscovered the same family one
seat over. The evidence for "all mutations killed" has to be re-runnable or it is
just a sentence in a commit message.

Each entry applies ONE textual mutation to a source file, runs the targeted suite,
and restores the file. A mutation that leaves the suite GREEN survived and is a
defect in the tests, not in the source.

TWO RULES, both learned the hard way:

1. For every test, run the mutation its own NAME describes and confirm it dies.
2. An index- or value-to-constant mutation must use the constant the CORRECT
   ANSWER actually takes -- never a conspicuous sentinel like ``99``. A sentinel
   dies against any assertion that mentions the real value, so it certifies the
   class while the real defect lives. See the retired M8 below: it did exactly
   that for two review rounds. Better still, build the fixture so the correct
   answer is not a constant any mutation would guess -- which is why the degenerate
   fold is parameterised rather than always fold 0.

Run: ``uv run python scripts/compose_conditioning_mutation_harness.py``

The ``# noqa: E501`` markers below are deliberate: those strings are VERBATIM
source fragments and must match the file byte-for-byte, so they cannot be wrapped.
An anchor that stops matching is reported as ``SKIP``/``ANCHOR`` rather than as a
kill — silently counting a non-applied mutation as killed is the failure this
harness exists to prevent.

SAFETY. This script edits files under ``src/`` in place and restores them from a
backup in ``finally``. It refuses to start on a dirty worktree, so an interrupted
run can always be recovered with ``git checkout --``. It never touches ``configs/``
and never runs a scientific command: every mutation here is synthetic-suite only.
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
        "M3  the bound becomes exclusive (> -> >=)",
        SELECT,
        "and float(report.condition_number) > ceiling",
        "and float(report.condition_number) >= ceiling",
    ),
    (
        "M4  [reviewer] conditioning checked BEFORE rank, across folds",
        SELECT,
        RANK_BLOCK,
        "    deficient = []  # rank pass disabled: conditioning now decides first",
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
        "M9  [reviewer] the isfinite guard is deleted",
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


def run_suite() -> tuple[bool, str]:
    proc = subprocess.run(
        ["uv", "run", "pytest", "-q", *TESTS], cwd=REPO, capture_output=True, text=True
    )
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout else ""
    return proc.returncode == 0, line


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
        shutil.copy2(path, SCRATCH / path.name)

    ok, line = run_suite()
    if not ok:
        print(f"BASELINE RED -- aborting: {line}")
        return 2
    print(f"baseline green: {line}\n")

    survived = []
    try:
        for name, path, old, new in MUTATIONS:
            original = (SCRATCH / path.name).read_text(encoding="utf-8")
            n = original.count(old)
            if n != 1:
                print(f"SKIP      {name}: anchor matched {n} times")
                survived.append(f"{name} (ANCHOR)")
                continue
            mutant = original.replace(old, new)
            if "_Never" in new:
                mutant = mutant.replace(
                    "class FoldConditioningError(SelectionError):",
                    "class _Never(Exception):\n    pass\n\n\nclass FoldConditioningError(SelectionError):",  # noqa: E501
                )
            path.write_text(mutant, encoding="utf-8")
            green, line = run_suite()
            print(f"{'SURVIVED' if green else 'killed  '}  {name}\n          {line}")
            if green:
                survived.append(name)
            path.write_text(original, encoding="utf-8")
    finally:
        for path in (SELECT, DIAG, TESTS_FILE):
            shutil.copy2(SCRATCH / path.name, path)

    ok, line = run_suite()
    print(f"\nrestored, suite green: {ok} ({line})")
    if survived:
        print("\nSURVIVING:")
        for name in survived:
            print(f"  - {name}")
        return 1
    print("\nall mutations killed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
