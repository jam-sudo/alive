#!/usr/bin/env python
"""Mutation harness for the registered relative-lambda rule.

A sibling of ``compose_conditioning_mutation_harness.py`` and
``compose_receipt_interpreter_mutation_harness.py``, separate rather than a
refactor because each backs its own standing kill record. Kill semantics are
copied verbatim.

The five rules this project earned, each because the previous set was not enough:

1. For every test, RUN the mutation its own NAME describes and confirm it dies.
2. An index/value-to-constant mutation must use the constant the CORRECT ANSWER
   takes, never a conspicuous sentinel.
3. Better still, build the fixture so the correct answer is not a constant any
   mutation would guess.
4. A kill must be attested by a NAMED FAILING TEST, never a nonzero exit code.
5. The mutable file set must cover every site that ENFORCES the contract -- here
   that is three files, because the rule is registered in ``config2``, computed in
   ``identify`` and applied in BOTH ``select`` (OOF) and ``phase2a`` (final fit).
   A rule applied in only one of those two would make the selected hyperparameter
   different from the one that was scored, which no single-file harness would see.

Run from a CLEAN worktree: this edits ``src/`` in place and restores in a
``finally``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRATCH = REPO / "artifacts" / "lambda-scaling-mutation-backup"
IDENTIFY = REPO / "src/alive/compose/identify.py"
SELECT = REPO / "src/alive/compose/select.py"
PHASE2A = REPO / "src/alive/compose/phase2a.py"
CONFIG2 = REPO / "src/alive/compose/config2.py"
TESTS = [
    "tests/alive/compose/test_lambda_scaling.py",
    "tests/alive/compose/test_select.py",
    "tests/alive/compose/test_diagnostics2.py",
    "tests/alive/compose/test_condition_ceiling.py",
    "tests/alive/compose/test_config2.py",
]

MUTATIONS = [
    (
        "M1  the scale is inert (absolute lambda restored)",
        IDENTIFY,
        "    if sigma_max == 0.0:\n        return 1.0\n    return sigma_max * sigma_max",
        "    if sigma_max == 0.0:\n        return 1.0\n    return 1.0",
    ),
    (
        "M2  scale uses sigma_max, not its square (wrong power: c^2 not c^4)",
        IDENTIFY,
        "    return sigma_max * sigma_max",
        "    return sigma_max",
    ),
    (
        "M3  scale taken from sigma_MIN instead of sigma_max",
        IDENTIFY,
        "    sigma_max = float(svals[0]) if svals.size else 0.0",
        "    sigma_max = float(svals[-1]) if svals.size else 0.0",
    ),
    (
        "M4  a non-finite design is coerced instead of refused",
        IDENTIFY,
        "    if not np.isfinite(sigma_max):",
        "    if False:",
    ),
    (
        "M5  LinAlgError escapes untyped (exit 1 instead of the contracted 10)",
        IDENTIFY,
        "    except np.linalg.LinAlgError as exc:",
        "    except _NeverRaised as exc:",
    ),
    (
        "M6  an empty roster is not refused",
        IDENTIFY,
        "    if len(list(pairs)) == 0:",
        "    if False:",
    ),
    (
        "M7  OOF selection ignores the scale",
        SELECT,
        "model.fit(Z, train_pairs, train_eps, lam=float(lam) * float(lambda_scale))",
        "model.fit(Z, train_pairs, train_eps, lam=float(lam))",
    ),
    (
        "M8  the scale is computed per FOLD instead of on the calibration design",
        SELECT,
        "        candidate_lambda_scale = calibration_lambda_scale(Z, list(idx_pairs))",
        "        candidate_lambda_scale = calibration_lambda_scale(Z, list(idx_pairs)[:1])",
    ),
    (
        "M9  the registered rule string is not enforced by selection",
        SELECT,
        "    if lambda_scaling != LAMBDA_SCALING_RULE:",
        "    if False:",
    ),
    (
        "M10 the FINAL fit drops the scale (selection scores a different penalty)",
        PHASE2A,
        "        if name == HEADLINE_MODEL_NAME:\n            lam_applied *= headline_lambda_scale",
        "        if False:\n            lam_applied *= headline_lambda_scale",
    ),
    (
        "M11 the final fit scales EVERY model, silently changing a baseline",
        PHASE2A,
        "        if name == HEADLINE_MODEL_NAME:",
        "        if True:",
    ),
    (
        "M12 the config value is not pinned to the preregistration",
        CONFIG2,
        "    if lambda_scaling != _EXPECTED_LAMBDA_SCALING:",
        "    if False:",
    ),
    (
        "M13 the registered rule string itself drifts",
        IDENTIFY,
        'LAMBDA_SCALING_RULE = "calibration_sigma_max_squared"',
        'LAMBDA_SCALING_RULE = "calibration_sigma_max"',
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
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    if dirty:
        print("REFUSING: worktree is dirty. This harness edits src/ in place.")
        print(dirty)
        return 2
    files = (IDENTIFY, SELECT, PHASE2A, CONFIG2)
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
            mutant = original.replace(old, new)
            if "_NeverRaised" in new:
                mutant = mutant.replace(
                    "class SingularDesignError(ValueError):",
                    "class _NeverRaised(Exception):\n    pass\n\n\n"
                    "class SingularDesignError(ValueError):",
                    1,
                )
            path.write_text(mutant, encoding="utf-8")
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
