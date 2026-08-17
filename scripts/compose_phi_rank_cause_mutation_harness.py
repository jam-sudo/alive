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

And a SIXTH, added here, which closes the harness limitation the 2026-08-12 audit
recorded and 2026-08-11 left open ("a kill is not checked for RELEVANCE, so a
mutation that breaks an unrelated test is still recorded as killed"):

6. Every mutation names the test whose OWN NAME describes it
   (``EXPECTED_KILLER``), and a kill by some other test alone is reported
   ``IRRELEVANT``, not ``killed``. This is rule 1 made mechanical: rule 1 says to
   run the mutation each test's name describes, and the only way to know that
   happened is to check the pairing in both directions. It also forces the
   coverage gap into the open -- writing this table is what revealed that three
   tests in the suite (the exception TYPE, the committed-evidence anchor, and the
   ``genes_before_condition`` ordering case) had no mutation at all, which is
   M18-M20 below.

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
    '            f"{at}: RANK-DEFICIENT — rank {rank} is below the identifiable "\n'
    '            f"subspace dimension sym_dim={sym_dim}, so this registered grid point is "\n'
    '            "not identifiable on the calibration design"\n'
)
_SYM_DIM_CHECK = (
    '    if _nonnegative_int(block["sym_dim"], f"{at}: sym_dim") != sym_dim:\n'
    "        raise ValueError("
    "f\"{at}: reported sym_dim {block['sym_dim']!r} is not k(k+1)/2 = {sym_dim}\")\n"
)
_RANK_BLOCK = (
    '    rank = _nonnegative_int(block["rank"], f"{at}: rank")\n'
    "    if rank > sym_dim:\n"
    "        # A SEPARATE cause, not a deficiency. `rank <= min(n_pairs, sym_dim)`\n"
    "        # always holds, so an over-rank block is not a design that failed to span\n"
    "        # its subspace -- it is an internally inconsistent report. Folding it into\n"
    '        # the deficiency branch made the message say "rank 37 is below sym_dim=36".\n'
    "        raise ValueError(\n"
    '            f"{at}: rank {rank} EXCEEDS the identifiable subspace dimension "\n'
    '            f"sym_dim={sym_dim}; rank <= min(n_pairs, sym_dim) holds by construction, "\n'
    '            "so this report is internally inconsistent"\n'
    "        )\n"
    "    if rank != sym_dim:\n        raise ValueError(\n" + _RANK_MESSAGE + "        )\n"
)
_N_GENES_CHECK = (
    '    if _nonnegative_int(block["n_genes"], f"{at}: n_genes") != n_z_universe_genes:'
)
_N_GENES_MUTANT = '    if _nonnegative_int(block["n_genes"], f"{at}: n_genes") < 0:'
_N_GENES_BLOCK = (
    _N_GENES_CHECK + "\n"
    "        raise ValueError(\n"
    "            f\"{at}: factor bank covers {block['n_genes']!r} genes, but the envelope \"\n"
    '            f"declares n_z_universe_genes={n_z_universe_genes}"\n'
    "        )\n"
)
_CONDITION_BOOL_BLOCK = (
    '    condition = block["condition_number"]\n'
    "    if isinstance(condition, bool):\n"
    '        raise ValueError(f"{at}: condition_number is a boolean, not a number")\n'
)

MUTATIONS = [
    (
        "M1  the k_total position clause never fires",
        PHI_RANK,
        '    if _nonnegative_int(block["k_total"], f"{at}: k_total") != expected_k:',
        '    if _nonnegative_int(block["k_total"], f"{at}: k_total") < 0:',
    ),
    (
        "M2  the sym_dim clause never fires",
        PHI_RANK,
        '    if _nonnegative_int(block["sym_dim"], f"{at}: sym_dim") != sym_dim:',
        '    if _nonnegative_int(block["sym_dim"], f"{at}: sym_dim") < 0:',
    ),
    (
        "M3  DECISION #5 REMOVED: the rank clause never fires",
        PHI_RANK,
        "    if rank != sym_dim:",
        "    if False:",
    ),
    (
        "M4  the rank clause is relaxed to accept a DEFICIENT rank",
        PHI_RANK,
        "    if rank != sym_dim:",
        "    if rank < 0:",
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
        "    if scored != expected_scored_pairs:",
        "    if False:",
    ),
    (
        "M7  the skipped-pair clause never fires",
        PHI_RANK,
        "    if skipped != 0:",
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
        _SYM_DIM_CHECK + _RANK_BLOCK,
        _RANK_BLOCK + _SYM_DIM_CHECK,
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
    (
        "M18 a rejection is raised as TypeError (escapes config2's except ValueError)",
        PHI_RANK,
        '        raise ValueError(f"{at}: condition_number is a boolean, not a number")',
        '        raise TypeError(f"{at}: condition_number is a boolean, not a number")',
    ),
    (
        "M19 FAIL-OPEN INVERTED: the rank clause refuses a HEALTHY design",
        PHI_RANK,
        "    if rank != sym_dim:",
        "    if rank == sym_dim:",
    ),
    (
        "M20 the gene-count clause moves BEHIND the condition-number clauses",
        PHI_RANK,
        _N_GENES_BLOCK + _CONDITION_BOOL_BLOCK,
        _CONDITION_BOOL_BLOCK + _N_GENES_BLOCK,
    ),
    (
        "M21 the k_total type check is dropped (integer-valued float accepted)",
        PHI_RANK,
        '_nonnegative_int(block["k_total"], f"{at}: k_total")',
        'block["k_total"]',
    ),
    (
        "M22 the sym_dim type check is dropped",
        PHI_RANK,
        '_nonnegative_int(block["sym_dim"], f"{at}: sym_dim")',
        'block["sym_dim"]',
    ),
    (
        "M23 the rank type check is dropped",
        PHI_RANK,
        '    rank = _nonnegative_int(block["rank"], f"{at}: rank")',
        '    rank = block["rank"]',
    ),
    (
        "M24 the scored-pair type check is dropped",
        PHI_RANK,
        "    scored = _nonnegative_int(\n"
        '        block["n_calibration_pairs_scored"], f"{at}: n_calibration_pairs_scored"\n'
        "    )",
        '    scored = block["n_calibration_pairs_scored"]',
    ),
    (
        "M25 the skipped-pair type check is dropped (False passes as 0)",
        PHI_RANK,
        "    skipped = _nonnegative_int(\n"
        '        block["n_calibration_pairs_skipped"], f"{at}: n_calibration_pairs_skipped"\n'
        "    )",
        '    skipped = block["n_calibration_pairs_skipped"]',
    ),
    (
        "M26 the n_genes type check is dropped",
        PHI_RANK,
        '_nonnegative_int(block["n_genes"], f"{at}: n_genes")',
        'block["n_genes"]',
    ),
    (
        "M27 the over-rank branch is folded back into the deficiency message",
        PHI_RANK,
        "    if rank > sym_dim:",
        "    if False:",
    ),
]

#: Rule 6. The test whose OWN NAME describes each mutation; a kill by anything
#: else alone is ``IRRELEVANT``. Matched as a substring of a pytest node ID.
EXPECTED_KILLER = {
    "M1": "test_each_cause_raises_its_own_message[k_total]",
    "M2": "test_each_cause_raises_its_own_message[sym_dim]",
    "M3": "test_one_rank_deficient_dimension_still_refuses_the_whole_report",
    "M4": "test_one_rank_deficient_dimension_still_refuses_the_whole_report",
    "M5": "test_each_cause_raises_its_own_message[is_full_rank_truthy_1]",
    "M6": "test_each_cause_raises_its_own_message[pairs_scored]",
    "M7": "test_each_cause_raises_its_own_message[pairs_skipped]",
    "M8": "test_each_cause_raises_its_own_message[n_genes]",
    "M9": "test_each_cause_raises_its_own_message[condition_bool]",
    "M10": "test_each_cause_raises_its_own_message[condition_str]",
    "M11": "test_each_cause_raises_its_own_message[condition_inf]",
    "M12": "test_each_cause_raises_its_own_message[condition_zero]",
    "M13": "test_the_rank_message_says_what_the_operator_must_do",
    "M14": "test_every_message_names_the_offending_dimension",
    "M15": "test_the_short_circuit_order_is_unchanged[sym_dim_before_rank]",
    "M16": "test_scientific_mode_names_a_rank_deficiency_as_such",
    "M17": "test_one_over_ceiling_dimension_is_still_accepted",
    "M18": "test_the_refusal_type_is_still_exactly_ValueError[condition_bool]",
    "M19": "test_the_committed_evidence_still_validates",
    "M20": "test_the_short_circuit_order_is_unchanged[genes_before_condition]",
    "M21": "test_no_count_or_dimension_accepts_a_non_int[float-k_total]",
    "M22": "test_no_count_or_dimension_accepts_a_non_int[float-sym_dim]",
    "M23": "test_no_count_or_dimension_accepts_a_non_int[float-rank]",
    "M24": "test_no_count_or_dimension_accepts_a_non_int[float-n_calibration_pairs_scored]",
    "M25": "test_no_count_or_dimension_accepts_a_non_int[bool-n_calibration_pairs_skipped]",
    "M26": "test_no_count_or_dimension_accepts_a_non_int[float-n_genes]",
    "M27": "test_an_over_rank_block_is_not_called_a_deficiency",
}


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
    irrelevant: list[str] = []
    try:
        for name, path, old, new in MUTATIONS:
            mid = name.split()[0]
            expected = EXPECTED_KILLER[mid]
            original = (SCRATCH / _key(path)).read_text(encoding="utf-8")
            n = original.count(old)
            if n != 1:
                print(f"SKIP      {name}: anchor matched {n} times")
                survived.append(f"{name} (ANCHOR)")
                continue
            path.write_text(original.replace(old, new), encoding="utf-8")
            killers, line = run_suite()
            path.write_text(original, encoding="utf-8")
            named = sorted(k for k in killers if expected in k)
            if named:
                others = len(killers) - len(named)
                print(f"killed    {name}\n            by: {named[0]} (+{others} more)")
            elif killers:
                # Rule 6: something failed, but not the test whose name makes the
                # claim. That is a coverage gap wearing a kill's clothing.
                print(f"IRRELEVANT{name}\n            expected: {expected}")
                print(f"            got:      {', '.join(sorted(killers)[:3])}")
                irrelevant.append(name)
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
    if irrelevant:
        print(f"IRRELEVANT ({len(irrelevant)}): " + "; ".join(irrelevant))
    if survived:
        print(f"SURVIVED ({len(survived)}): " + "; ".join(survived))
    if survived or invalid or irrelevant:
        return 1
    print("all mutations killed, each by the NAMED test that makes its claim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
