#!/usr/bin/env python
"""Mutation harness for the kernel-isolation receipt's v2 interpreter block.

A sibling of ``compose_conditioning_mutation_harness.py``, deliberately separate
rather than a refactor of it: that harness backs a standing "37 mutations killed"
record, and rewriting its machinery would invalidate evidence to save sixty lines.
The kill semantics below are copied from it verbatim and on purpose.

The five rules this project earned, each because the previous set was not enough:

1. For every test, RUN the mutation its own NAME describes and confirm it dies. A
   test can assert something weaker than its name claims, and then the name is
   what gets recorded.
2. An index/value-to-constant mutation must use the constant the CORRECT ANSWER
   takes, never a conspicuous sentinel. A sentinel dies against any assertion that
   merely mentions the real value, certifying a class it never tested.
3. Better still, build the fixture so the correct answer is not a constant any
   mutation would guess.
4. A kill must be attested by a NAMED FAILING TEST, never a nonzero exit code. A
   one-character syntax break once produced three collection errors, zero
   failures, a nonzero exit -- and was recorded "killed".
5. The mutable file set must cover every site that ENFORCES the contract. Rules
   1-3 govern how an entry is written; none of them governs which sites have an
   entry at all.

Run from a CLEAN worktree: this edits ``src/`` in place and restores in a
``finally``. Do not run it while an independent review shares the checkout -- a
concurrent on-disk mutation cannot cause a spurious pass, but it will confuse
anyone reading ``git status``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRATCH = REPO / "artifacts" / "receipt-interpreter-mutation-backup"
CI = REPO / "src/alive/compose/kernel_isolation_ci.py"
BUILDER = REPO / "scripts/compose/build_kernel_isolation_ci_receipt.py"
TESTS = ["tests/alive/compose/test_kernel_isolation_ci.py"]

MUTATIONS = [
    (
        "M1  the recorded version is a constant, not the running interpreter",
        CI,
        '"version": platform.python_version(),',
        '"version": "3.12.13",',
    ),
    (
        "M2  the build string is not normalised, so newlines reach the digest",
        CI,
        '"build": " ".join(sys.version.split()),',
        '"build": sys.version,',
    ),
    (
        "M3  the implementation is a constant",
        CI,
        '"implementation": sys.implementation.name,',
        '"implementation": "cpython",',
    ),
    (
        "M4  the builder emits no interpreter block at all",
        CI,
        '        "interpreter": interpreter_identity(),\n',
        "",
    ),
    (
        "M5  the validator never checks the interpreter block",
        CI,
        "    if declared != CI_RECEIPT_SCHEMA_V1:\n"
        '        _validate_interpreter(receipt["interpreter"])\n',
        "",
    ),
    (
        "M6  the version/schema guard is inverted",
        CI,
        "    if declared != CI_RECEIPT_SCHEMA_V1:",
        "    if declared == CI_RECEIPT_SCHEMA_V1:",
    ),
    (
        "M7  v1 receipts are validated against the v2 roster (back-compat broken)",
        CI,
        "    CI_RECEIPT_SCHEMA_V1: _RECEIPT_KEYS_V1,",
        "    CI_RECEIPT_SCHEMA_V1: _RECEIPT_KEYS_V2,",
    ),
    (
        "M8  the v2 roster does not actually require the interpreter key",
        CI,
        '_RECEIPT_KEYS_V2 = _RECEIPT_KEYS_V1 | frozenset({"interpreter"})',
        "_RECEIPT_KEYS_V2 = _RECEIPT_KEYS_V1",
    ),
    (
        "M9  an unknown schema falls back to a roster instead of failing closed",
        CI,
        "    keys = _RECEIPT_KEYS_BY_SCHEMA.get(declared) if isinstance(declared, str) else None",
        "    keys = _RECEIPT_KEYS_BY_SCHEMA.get(declared, _RECEIPT_KEYS_V2)",
    ),
    (
        "M10 the patch level is optional (two components accepted)",
        CI,
        'r"[0-9]+\\.[0-9]+\\.[0-9]+"',
        'r"[0-9]+\\.[0-9]+"',
    ),
    (
        "M11 the version/build cross-binding is dropped",
        CI,
        "    if not build_tokens or not build_tokens[0].startswith(version):",
        "    if False:",
    ),
    (
        "M12 the cross-binding becomes equality, rejecting a legitimate pre-release",
        CI,
        "    if not build_tokens or not build_tokens[0].startswith(version):",
        "    if not build_tokens or build_tokens[0] != version:",
    ),
    (
        "M13 only ONE interpreter field is required non-empty",
        CI,
        '    for field in ("version", "build", "implementation"):',
        '    for field in ("version",):',
    ),
    (
        "M14 the interpreter roster is not exact",
        CI,
        "    interpreter = _exact_mapping("
        'value, _INTERPRETER_KEYS, "kernel-isolation interpreter")',
        "    interpreter = dict(value)",
    ),
]


def _key(path: Path) -> str:
    """Backup name keyed by RELATIVE PATH, not basename."""
    return str(path.relative_to(REPO)).replace("/", "__")


def run_suite() -> tuple[frozenset[str], str]:
    """Run the suite and return the set of FAILED node IDs, plus the summary line.

    Returning FAILURES rather than the exit code is the point -- see rule 4.
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
    for path in (CI, BUILDER):
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
                shown = ", ".join(sorted(killers)[:3])
                print(f"killed    {name}\n            by: {shown}")
            elif line.startswith("(no output)") or "error" in line.lower():
                print(f"INVALID   {name}: nonzero exit with NO failing test -- {line}")
                invalid.append(name)
            else:
                print(f"SURVIVED  {name}: {line}")
                survived.append(name)
    finally:
        for path in (CI, BUILDER):
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
