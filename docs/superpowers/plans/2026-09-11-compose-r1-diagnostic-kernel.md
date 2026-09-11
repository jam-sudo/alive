# R1 diagnostic kernel — local implementation increment

> 2026-09-11. COMPOSE-K562-v1 ACTIVE / RELEASE-BLOCKED / seal UNOPENED.
> Implements the next local step authorized after [report-policy adoption](../specs/2026-09-11-compose-r1-report-measurement-proposal.md).
> Not a runtime verifier, scientific report/admission producer, or config finalizer.

## Contract before implementation

The scientific `compose_gears_log_sampling_report_v1` remains unimplemented. This increment uses a distinct
`compose_gears_log_sampling_diagnostic_v1` schema for one registered pair × training seed. It consumes only
caller-supplied bounded projected arrays, never paths, models, outcome stores or source data. Its validity means
strict syntax and recomputable arithmetic, not verified source roles or runtime behavior.

Registration has exactly `pair_id`, `role`, `training_seed`, `control_ids`, `draw_count`, `response_dim`,
`binding_sha256`. Pair IDs are two distinct nonempty strings; role is `singles` or `combo_calibration`.
Control IDs are nonempty unique strings in registered order. Seed is a nonnegative JSON integer; draw count
and response dimension are positive JSON integers. Binding is a nonempty strict object of the required SHA-256
fields: `basis_config`, `contract`, `checkpoint`, `response`, `roster`. These are caller expectations, not
authenticated scientific identities. Missing/extra keys, bool-as-number, strings-as-numbers and nonfinite
values fail closed. Pair orientation is preserved and compared exactly with external registration.

Report has exactly `schema`, `protocol`, `method`, `scope`, `registration`, `inputs_sha256`, `exact_n`,
`analytic`, `public`, `structural_status`, `admission_status`, `self_checksum`. Its scope is
`development_diagnostic`, structural status is always `UNVERIFIED`, admission is always `NOT_ADMISSIBLE`.
There is no API for promoting these statuses. Public status is `NOT_RUN_BUDGET` for zero supplied means and
`INCONCLUSIVE` otherwise. No numeric tolerance/alpha/eta defaults or confidence intervals are introduced.

The report recomputes mu, centered squared sum, V and B from the complete supplied control-output matrix.
Public discrepancy is computed for every supplied mean, with no clipping/exclusion or scientific threshold.
Exact N includes control rows, p, m and public mean count. Input hashes bind the ordered matrices via strict
canonical JSON. Validation requires external expected registration and both matrices, not just report-declared
digests. It rejects tampering even if a modified report has a newly recomputed self-checksum. Deterministic
float64 recomputation uses exact canonical serialized equality, not an unapproved scientific tolerance.

Arithmetic overflow or underflow that erases a nonzero squared contribution is a diagnostic error, not zero
noise. A singleton/constant finite pool is valid and gives V=0. Invalid numeric inputs raise; this increment
does not claim to durably archive failures. Persistent evidence custody remains a later producer task.

## Verification and boundary

Tests: known-answer, constant/singleton, exact replacement enumeration, cell-order binding, report/input/
registration tamper with fresh checksum, extra/missing nested keys, invalid types, nonfinite/overflow,
admission/structural status forgery, duplicate JSON keys and rejection by the existing scientific validator.
Negative arms capture exceptions and assert in the named test; no guard mocks. No mutation-harness proof is
claimed unless separately run. Targeted tests precede COMPOSE regression and Ruff.

Remaining: multi-pair/seed aggregation and role/source attestations, RNG/cache/batch verifier, bounded on-disk
producer, strict scientific schema/admission wiring, budget/numeric policy, runtime evidence and separate
execution approval. A green diagnostic kernel closes none of the activation blockers.

## Local verification record — 2026-09-11

Environment: local macOS, locked Python environment; development-only synthetic inputs.
No pod execution, real-data access, config mutation or seal opening was performed for this increment.

- The first COMPOSE regression attempt found three exception-inventory failures:
  `test_every_exception_class_under_src_is_classified`,
  `test_modules_outside_the_driver_graph_are_classified_unreachable`, and
  `test_the_enumeration_counts_are_pinned`. It was interrupted after 340 passed and three failed.
  Cause: the new diagnostic exception was missing from the exhaustive classification table.
  Added its `UNREACHABLE_FROM_DRIVER` classification and advanced the exact class count from 77 to 78;
  the scientific CLI rejection roster remains 42. No production guard or admission path was changed.
- Targeted command:
  `uv run --locked pytest -q tests/alive/compose/driver/test_exit_code_contract.py tests/alive/compose/test_log_sampling_report.py tests/alive/compose/test_r1_log_sampling_contract.py tests/test_claude_md_anchors.py tests/test_documentation_hygiene.py`
  — 91 passed after registration correction (including 48 new diagnostic cases).
- Full retry: `uv run --locked pytest -q -rs tests/alive/compose`
  — 2570 passed, 2 skipped, 1 warning in 1213.07 seconds.
  Both skips are Linux seccomp checks in `test_network_isolation.py` (lines 369 and 489 at execution);
  Mac results do not supply the pending Linux kernel-isolation proof.
  The warning was an AnnData string-index conversion in the CPA Scanpy control-test fixture.
- Final targeted/documentation rerun: 91 passed in 2.31 seconds. Repository Ruff check passed;
  format check reported 277 files already formatted; `git diff --check` passed. New increment files
  were also checked for whitespace errors with `git diff --no-index --check /dev/null <file>`.
  Full cross-protocol pytest, mutation-harness proof and pod/runtime evidence are not
  claimed by this record. The diagnostic remains `UNVERIFIED` / `NOT_ADMISSIBLE`.
