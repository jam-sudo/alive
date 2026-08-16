#!/usr/bin/env python
"""Mutation harness for the phi-rank factor-block rejection causes (decision #5).

A sibling of ``compose_conditioning_mutation_harness.py``,
``compose_receipt_interpreter_mutation_harness.py`` and
``compose_lambda_scaling_mutation_harness.py`` — separate rather than a refactor
because each backs its own standing kill record. Kill semantics are copied
verbatim.

The five rules this project earned, each because the previous set was not enough:

1. For every test, RUN the mutation its own NAME describes and confirm it dies.
2. An index/value-to-constant mutation must use the constant the CORRECT ANSWER
   takes, never a conspicuous sentinel.
3. Better still, build the fixture so the correct answer is not a constant any
   mutation would guess.
4. A kill must be attested by a NAMED FAILING TEST, never a nonzero exit code.
5. The mutable file set must cover every site that ENFORCES the contract -- here
   that is TWO files. ``phi_rank`` raises the named causes; ``config2`` is what
   carries the cause to the driver, and a wrapper that drops ``{exc}`` would make
   every message in ``phi_rank`` invisible to the operator while leaving all of
   this file's validator-level tests green.

The contract under test has two halves and both are mutated:

* each of the eleven factor-block clauses refuses, with its OWN message naming the
  cause and the offending ``k_total`` (M1-M14); and
* the ASYMMETRY that decision #5 registered -- rank is ALL, the ceiling is ANY --
  in BOTH directions (M3/M4 remove the ALL; M17 removes the ANY).

Run from a CLEAN worktree: this edits ``src/`` in place and restores in a
``finally``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRATCH = REPO / "artifacts" / "phi-rank-cause-mutation-backup"
PHI_RANK = REPO / "src/alive/compose/phi_rank.py"
CONFIG2 = REPO / "src/alive/compose/config2.py"
TESTS = [
    "tests/alive/compose/test_phi_rank_block_causes.py",
    "tests/alive/compose/test_config2.py",
    "tests/alive/compose/test_condition_ceiling.py",
]

_RANK_MESSAGE = (
    "            f\"{at}: RANK-DEFICIENT — rank {block['rank']!r} is below the identifiable \"\n"
    '            f"subspace dimension sym_dim={sym_dim}, so this registered grid point is "\n'
    '            "not identifiable on the calibration design"\n'
)
_SYM_DIM_CHECK = (
    '    if block["sym_dim"] != sym_dim:\n'
    "        raise ValueError("
    "f\"{at}: reported sym_dim {block['sym_dim']!r} is not k(k+1)/2 = {sym_dim}\")\n"
)
_RANK_CHECK = (
    '    if block["rank"] != sym_dim:\n        raise ValueError(\n' + _RANK_MESSAGE + "        )\n"
)
_N_GENES_CHECK = (
    '    if _nonnegative_int(block["n_genes"], "phi-rank factor n_genes") != n_z_universe_genes:'
)
_N_GENES_MUTANT = '    if _nonnegative_int(block["n_genes"], "phi-rank factor n_genes") < 0:'

MUTATIONS = [
    (
        "M1  the k_total position clause never fires",
        PHI_RANK,
        '    if block["k_total"] != expected_k:',
        "    if False:",
    ),
    (
        "M2  the sym_dim clause never fires",
        PHI_RANK,
        '    if block["sym_dim"] != sym_dim:',
        "    if False:",
    ),
    (
        "M3  DECISION #5 REMOVED: the rank clause never fires",
        PHI_RANK,
        '    if block["rank"] != sym_dim:',
        "    if False:",
    ),
    (
        "M4  the rank clause is relaxed to accept a DEFICIENT rank",
        PHI_RANK,
        '    if block["rank"] != sym_dim:',
        '    if block["rank"] > sym_dim:',
    ),
    (
        "M5  is_full_rank accepts a truthy 1 instead of the boolean True",
        PHI_RANK,
        '    if block["is_full_rank"] is not True:',
        '    if not block["is_full_rank"]:',
    ),
    (
        "M6  the scored-pair-count clause never fires",
        PHI_RANK,
        '    if block["n_calibration_pairs_scored"] != expected_scored_pairs:',
        "    if False:",
    ),
    (
        "M7  the skipped-pair clause never fires",
        PHI_RANK,
        '    if block["n_calibration_pairs_skipped"] != 0:',
        "    if False:",
    ),
    (
        "M8  the gene-count comparison is dropped (non-negativity kept)",
        PHI_RANK,
        _N_GENES_CHECK,
        _N_GENES_MUTANT,
    ),
    (
        "M9  a boolean condition_number is accepted as a number",
        PHI_RANK,
        "    if isinstance(condition, bool):",
        "    if False:",
    ),
    (
        "M10 a non-numeric condition_number is accepted",
        PHI_RANK,
        "    if not isinstance(condition, (int, float)):",
        "    if False:",
    ),
    (
        "M11 a non-finite condition_number is accepted",
        PHI_RANK,
        "    if not math.isfinite(float(condition)):",
        "    if False:",
    ),
    (
        "M12 a non-positive condition_number is accepted",
        PHI_RANK,
        "    if float(condition) <= 0.0:",
        "    if False:",
    ),
    (
        "M13 the rank cause collapses back to the old ambiguous message",
        PHI_RANK,
        _RANK_MESSAGE,
        '            f"{at}: invalid or non-full-rank factor block"\n',
    ),
    (
        "M14 the messages stop naming the offending k_total",
        PHI_RANK,
        '    at = f"phi-rank factor block k_total={expected_k}"',
        '    at = "phi-rank factor block"',
    ),
    (
        "M15 the sym_dim and rank clauses swap order",
        PHI_RANK,
        _SYM_DIM_CHECK + _RANK_CHECK,
        _RANK_CHECK + _SYM_DIM_CHECK,
    ),
    (
        "M16 config2 drops the cause when wrapping (operator sees only 'invalid')",
        CONFIG2,
        'f"scientific mode blocked: phi-rank evidence is invalid: {exc}"',
        '"scientific mode blocked: phi-rank evidence is invalid"',
    ),
    (
        "M17 DECISION #5 INVERTED: the ceiling becomes ALL like rank",
        PHI_RANK,
        "    if over_ceiling and len(over_ceiling) == len(expected_grid):",
        "    if over_ceiling:",
    ),
]


def _key(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("/", "__")


def run_suite() -> tuple[frozenset[str], str]:
    """Return the set of FAILED node IDs plus the summary line (rule 4)."""
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
    # TRACKED files only -- a deliberate narrowing of the sibling harnesses'
    # check, matched to the reason the check exists. The hazard is that this
    # harness edits src/ in place and restores in a ``finally``: an UNCOMMITTED
    # edit to a mutated file is what a crash would lose. Untracked scratch output
    # elsewhere in the tree cannot be lost that way, and refusing on it makes the
    # harness unrunnable in any worktree that has some. The mutated files are all
    # tracked, so this still refuses every state that could actually lose work.
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        print("REFUSING: tracked files are dirty. This harness edits src/ in place.")
        print(dirty)
        return 2
    files = (PHI_RANK, CONFIG2)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for path in files:
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
            path.write_text(original.replace(old, new), encoding="utf-8")
            killers, line = run_suite()
            path.write_text(original, encoding="utf-8")
            if killers:
                print(f"killed    {name}\n            by: {', '.join(sorted(killers)[:3])}")
            elif line.startswith("(no output)") or "error" in line.lower():
                print(f"INVALID   {name}: nonzero exit with NO failing test -- {line}")
                invalid.append(name)
            else:
                print(f"SURVIVED  {name}: {line}")
                survived.append(name)
    finally:
        for path in files:
            shutil.copy2(SCRATCH / _key(path), path)

    print(f"\n{len(MUTATIONS)} mutations attempted")
    if invalid:
        print(f"INVALID ({len(invalid)}): " + "; ".join(invalid))
    if survived:
        print(f"SURVIVED ({len(survived)}): " + "; ".join(survived))
        return 1
    if not invalid:
        print("all mutations killed, each by a named failing test")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
