# R1 ledger-to-progress binding — next local contract

> DRAFT / NOT EFFECTIVE — 2026-09-11.
> COMPOSE-K562-v1 ACTIVE / RELEASE-BLOCKED / seal UNOPENED.
> Follows the [progress validator](2026-09-11-compose-r1-progress-validator.md).

## Next implementation boundary

The progress validator currently compares caller-supplied progress with another caller-supplied object.
The next useful step is deriving those expected counts from a unit-bound synthetic event transcript,
then checking candidate progress against the derivation. This is not an authenticity or runtime proof.

Inputs must be independently supplied expected unit identity, ordered control row IDs, public repeat
IDs and transcript bytes with an external content digest. Parse the exact bytes whose digest matched;
never let candidate report fields select the transcript or its expected digest. Reuse the strict JSON
decoder's duplicate/nonfinite rejection without treating JSON decoding as scientific verification.

## Required semantics before coding

- Bind each transcript to the expected unit; reject a different condition or seed even if counts match.
- Define explicit start, control-completion, repeat-attempt, repeat-completion and terminal events.
  Reject duplicate row/repeat completion, unknown IDs, completion before attempt, events after terminal,
  missing/duplicate/out-of-order event sequence numbers and unregistered retries.
- Counts are counts of registered identities, not arbitrary sums of producer-declared scalars.
- A content hash proves byte identity, not that all real events were recorded. A syntactically closed
  synthetic transcript can support synthetic exact counts only. Actual KNOWN requires independently
  verified runtime/custody completeness; absence of an event alone is not proof of non-execution.
- A truncated/unclosed real transcript supports at most lower bounds on observed events; do not turn
  them into exact KNOWN counts. Preserve UNKNOWN and partial evidence. Do not treat a failed attempt
  as a completed repeat or silently retry it.
- The existing report progress schema has no lower-bound field. Preserve partial event evidence rather
  than adding an unapproved numeric field or substituting a lower bound for the exact count.
- A NOT_EXECUTED claim requires an explicit independently supported no-start disposition, not an empty
  transcript. The synthetic API must state that its fixture assertion is not this runtime evidence.

## Remaining design decisions

Choose exact event tagged-union keys, publication/terminal atomicity and which independently pinned
artifact attests transcript completeness. These are not supplied by the existing semantic report draft.
Define the synthetic-only contract first, and review crash-at-every-boundary cases before implementation.
Do not reuse protocol scientific seal or production terminal files for development transcript tests.

## Acceptance examples

Complete run; failure before/after attempt; crash between output persistence and completion marker;
zero-budget with completed control reference; unknown start; fresh-checksum altered unit; repeated
completion; skipped sequence number; post-terminal event; forged report count; changed external digest.
Negative tests use own-frame capture-and-assert, no guard mocks. No runtime receipt or admission emitted.

## Synthetic transcript contract — local implementation scope

For this bounded fixture increment, the exact JSON object is `{unit, events}`. Unit uses the reviewed
Unit identity keys. Independently supplied expected unit, control row IDs, repeat indices and exact
transcript byte SHA are mandatory. This is not a scientific manifest or a production ledger format.

Events have contiguous zero-based `seq` and `kind`. START has only these keys; CONTROL_DONE adds
`row_id`; REPEAT_ATTEMPT and REPEAT_DONE add `repeat_index`; TERMINAL adds `status` from
COMPLETE/FAILED/NOT_EXECUTED. START occurs once before work, controls precede public attempts, attempts
follow registered repeat order, and each repeat completes before the next attempt. This increment supports
only a serial synthetic transcript, not parallel workers or retries. TERMINAL is last and unique.
NOT_EXECUTED permits only a single terminal event and is a fixture assertion, not real no-start proof.

A closed synthetic transcript produces exact counts *within the supplied transcript*. COMPLETE requires
all registered work; FAILED permits a recorded partial attempt. An unclosed transcript maps to FAILED
and all observed counters UNKNOWN, preserving events as evidence without interpreting missing events
as proof of zero execution. Candidate status/progress must equal the derivation. No report is emitted.
Actual durable publication, custody and completeness attestation remain unimplemented and require their
own contract; the synthetic terminal marker cannot substitute for them.

## Local implementation — 2026-09-11

Implemented [byte-bound synthetic trace validator](../../../src/alive/compose/log_sampling_trace.py)
and [36 tests](../../../tests/alive/compose/test_log_sampling_trace.py). The API validates progress and
status against counts derived from the externally pinned transcript; no receipt or admission is returned.
Empty and every unclosed prefix remain FAILED with UNKNOWN counters. Closed fixture counts are not
assertions about actual execution. No source paths, production terminal files or scientific guards changed.

`uv run --locked pytest -q tests/alive/compose/test_log_sampling_trace.py tests/alive/compose/test_log_sampling_progress.py tests/alive/compose/test_log_sampling_coverage.py tests/alive/compose/driver/test_exit_code_contract.py tests/test_claude_md_anchors.py tests/test_documentation_hygiene.py`
returned 186 passed in 2.78 seconds. Repository Ruff check passed; format check reported 282 files
already formatted; `git diff --check` passed.
The earlier full COMPOSE run was collected before these trace tests existed: it cannot be cited as the
full regression for this increment. A full regression of this increment remains required, as do actual
runtime/custody proof and the independent completeness contract. No mutation-harness proof is claimed.

## Self-review corrections — 2026-09-11

Affected gate: [R1 report/readiness](../COMPOSE-SEAL-READINESS.md).
Owner requested correction of four review findings; scientific role/seal/admission contracts are unchanged.

1. Catch `DecimalException` in the shared strict diagnostic decoder and translate it to the documented
   `LogSamplingDiagnosticError`. Extreme positive/negative mantissas and signed zero with oversized
   negative exponents now follow the typed rejection path. Direct decoder and trace regressions added.
2. Split duplicate START, duplicate row, false NOT_EXECUTED and false COMPLETE into named tests with
   otherwise matching candidate status/counts. Remaining event-negative cases assert the specific
   rejection reason so another rejection cannot silently substitute for the intended check.
3. Add a two-control/two-repeat fixture, ordered completion, isolated wrong-order/overlap/retry/
   missing-control/duplicate-completion negatives and all eight unclosed crash prefixes.
4. Use set membership for controls and attempted repeats, retaining the external repeat list for order.
   Membership work is linear on average over event count, rather than repeated linear-list searches.

Trace tests now contain 54 cases; direct diagnostic tests contain 50. Command from the implementation
record expanded with `tests/alive/compose/test_log_sampling_report.py` returned 254 passed in 2.19 seconds.
Repository Ruff check passed; format check reported 282 files already formatted; `git diff --check` passed.

Repeated the same local synthetic control-only scaling probe (one START, n CONTROL_DONE, one COMPLETE;
zero public repeats). Before: n=1000/4000/8000 took 0.0041/0.0371/0.1398 seconds. After:
0.0016/0.0062/0.0125 seconds. These single-run wall times are diagnostic observations, not a benchmark
guarantee or scientific result; the set-based membership change supplies the algorithmic rationale.

A fresh `uv run --locked pytest -q -rs tests/alive/compose` has started with these trace/regression tests
included. Its result is pending. No mutation-harness proof, five-clean-round convergence, runtime custody
or scientific readiness is claimed. Changes remain uncommitted; next action is full-regression review
and post-fix self-review by the implementation owner.

## Post-fix regression and review closure — 2026-09-11

The pending full command above completed: **2751 passed, 2 skipped, 1 warning in
1188.46 seconds**. Both skips are Linux seccomp checks in `test_network_isolation.py`
(lines 369 and 489), unavailable on this Mac. The warning is AnnData's implicit
string-index conversion in `test_registered_split_is_valid_for_real_scanpy_control_t_test`.
This collection includes the corrected trace and decoder tests; it does not supply Linux
kernel-isolation proof.

Five consecutive post-fix review rounds found no additional actionable finding within this
synthetic increment, stopping at round 5 of the maximum 15:

1. Strict decoder and byte-bound entry review: the JSON/exponent/pinned/bytes subset of
   report and trace tests passed (17 passed, 87 deselected); typed Decimal rejection retained.
2. Serial event grammar review: an independent valid-language construction covered both control
   permutations, every prefix, FAILED closure, full COMPLETE and isolated NOT_EXECUTED.
   Comparing all token sequences of length 0–4 plus valid sequences and their single-event
   deletions/duplications gave 11,301 cases, 30 valid sequences and zero mismatches.
3. External identity, ordered roster and KNOWN/UNKNOWN review: trace, progress and coverage
   tests passed together (179 passed); caller expectations remain independent inputs, not
   authenticated runtime evidence.
4. Regression isolation and membership review: inspected the four isolated negatives and
   multi-item negatives with otherwise matching counts; reviewed set membership with list-based
   repeat ordering. The expanded targeted command recorded above passed again (254 passed in
   2.67 seconds). No mutation harness was run or inferred from these negative tests.
5. Integration and claim-boundary review: compared the implementation/docstrings with this
   synthetic contract and readiness; no production seal, runtime terminal or admission path is
   added. Repository Ruff check passed, format check reported 282 files already formatted, and
   `git diff --check` passed. Documentation anchor/hygiene tests are included in the 254 results.

Convergence means no new finding in these bounded self-review rounds, not exhaustive correctness
or independent review. Changes remain uncommitted. The next implementation boundary requires a
reviewed runtime publication/custody/completeness contract before actual execution evidence can
support KNOWN counts; exact runtime attestation and consumer admission are still unimplemented.
COMPOSE remains RELEASE-BLOCKED / UNOPENED and no activation blocker is cleared by this work.
