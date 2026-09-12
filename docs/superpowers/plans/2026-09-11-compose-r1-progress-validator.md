# R1 synthetic progress validator — local increment

> 2026-09-11. COMPOSE-K562-v1 ACTIVE / RELEASE-BLOCKED / seal UNOPENED.
> Extends the [reviewed progress contract](../specs/2026-09-11-compose-r1-scientific-report-contract-draft.md)
> after the [coverage increment](2026-09-11-compose-r1-coverage-validator.md).

## Contract before implementation

Validate exactly the five progress keys and the KNOWN/UNKNOWN tagged counters. Requested counts are
nonnegative integers (bool forbidden). Known counters are nonnegative integers; unknown counters have
nonempty sorted unique reason codes from the draft registry and no numeric value. Candidate and external
expected progress must both be structurally valid and match exactly. Unit status comes from the caller,
not from an untrusted extra field in progress.

Known completed controls cannot exceed requested controls. Known attempted/completed repeats cannot
exceed requested repeats even when the other counter is UNKNOWN. When both are known, completed cannot
exceed attempted. COMPLETE requires all counters known and completed/attempted=requested.
NOT_EXECUTED requires all observed counts KNOWN zero. FAILED may retain partial known or unknown counts;
it is not coerced into NOT_EXECUTED or a scientific negative result. COMPLETE permits a registered
zero-public-repeat count; that does not establish an approved budget or scientific eligibility.

This is synthetic structural validation only. External expectations are caller assertions, not a durable
ledger witness. No I/O, source-role proof, actual runtime start/completion evidence, exact_n/report assembly,
scientific schema acceptance, admission, config or seal changes. Real progress needs independent ledger
custody and unit/roster binding before scientific use. Return None, never a receipt or eligibility status.

## Verification plan

Known-answer COMPLETE/FAILED/NOT_EXECUTED and zero-repeat examples; own-frame negative assertions for
malformed counters, extra/missing fields, bool/nonfinite/negative values, unknown reason codes, count
inequalities, UNKNOWN-as-zero, inconsistent terminal status and altered external expectations.
Targeted tests precede full COMPOSE regression, Ruff and documentation checks.

## Local implementation record — 2026-09-11

Added `validate_synthetic_log_sampling_progress` to the
[development coverage module](../../../src/alive/compose/log_sampling_coverage.py), with
[62 progress cases](../../../tests/alive/compose/test_log_sampling_progress.py).
No scientific consumer imports or new exception classes were added.

Command:
`uv run --locked pytest -q tests/alive/compose/test_log_sampling_progress.py tests/alive/compose/test_log_sampling_coverage.py tests/alive/compose/driver/test_exit_code_contract.py tests/test_claude_md_anchors.py tests/test_documentation_hygiene.py`
returned 150 passed in 3.04 seconds. Repository Ruff check passed and format check reported 280 files
already formatted; `git diff --check` passed. Full COMPOSE regression has started; no completion is
claimed yet. Linux isolation, mutation harness and actual runtime/ledger custody were not verified here.

Next integration requires independently verified unit-bound row/repeat ledgers, not the report's own
progress fields. This increment neither authenticates those records nor establishes a scientific verdict.
