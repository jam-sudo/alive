# R1 synthetic coverage validator — local increment

> 2026-09-11. COMPOSE-K562-v1 ACTIVE / RELEASE-BLOCKED / seal UNOPENED.
> Implements the next synthetic-only step after the reviewed
> [report contract draft](../specs/2026-09-11-compose-r1-scientific-report-contract-draft.md).

## Scope before implementation

Validate the draft's Registered unit, Unit identity, condition, public schedule and Seed model binding
records as caller-supplied strict JSON-compatible lists. Require independently supplied expected units
and models and compare exact ordered content after validating both sides. Reject malformed/extra/missing
keys, bool-as-integer, invalid digests, noncanonical combo order, role mismatch, duplicate units/models,
duplicate repeat IDs/call orders within a unit and missing/unreferenced model seeds.

No scientific registration/report schema is accepted or emitted. No policy, provenance, source-role,
RNG independence, runtime, progress ledger or admission is verified. A syntactically valid digest is not
authenticated evidence. Condition membership and model expectations are caller assertions; real source
verification remains outside this increment. Call-order uniqueness is per-unit only; cross-unit scheduling
and seed-domain constraints await the pinned runtime contract. Empty public schedules are syntactically
allowed but do not establish an approved zero budget. No numeric policy/default is introduced.

Use the existing development diagnostic error and strict canonical JSON helper; no new exception class,
scientific driver imports or guard changes. Successful validation returns None, not a PASS/ELIGIBLE report.

## Verification

Synthetic known-valid singles/combo with multiple seeds; negative own-frame assertions for each malformed
record/coverage case, externally changed checkpoint/schedule/condition/order and malformed expected inputs.
Targeted tests → full COMPOSE regression → repository Ruff and documentation checks.

## Implementation and local checks — 2026-09-11

Implemented [coverage validator](../../../src/alive/compose/log_sampling_coverage.py) with
[63 synthetic cases](../../../tests/alive/compose/test_log_sampling_coverage.py). Caller inputs are not
mutated. Both candidate and independently supplied expected records are structurally validated; neither
a self-consistent candidate nor a malformed expected record can bypass coverage checks.

`uv run --locked pytest -q tests/alive/compose/test_log_sampling_coverage.py tests/alive/compose/driver/test_exit_code_contract.py tests/test_claude_md_anchors.py tests/test_documentation_hygiene.py`
returned 88 passed in 2.62 seconds. Repository Ruff check passed; format check reported 279 files already
formatted; `git diff --check` passed.

Full regression: `uv run --locked pytest -q -rs tests/alive/compose` returned
2633 passed, 2 skipped, 1 warning in 1183.97 seconds (19m43s).
Both skips are Linux seccomp tests in `test_network_isolation.py` (lines 369 and 489 at execution);
the warning is an AnnData string-index conversion in the CPA Scanpy control-test fixture.
This Mac run does not supply Linux kernel-isolation proof. Full cross-protocol pytest and a mutation
harness were not run for this increment; the own-frame negative tests are not a mutation-proof claim.
No real source data, pod, config, scientific validator/finalizer or seal was changed.
