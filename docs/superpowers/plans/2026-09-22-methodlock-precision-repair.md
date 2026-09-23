# MethodLock precision repair — implementation contract, 2026-09-22

Development-only repair scope under the [Cartographer realignment](2026-09-22-cartographer-realignment.md).
No new scientific protocol, outcome access, fit, calibration or seal is authorized.
The [evidence audit](../audits/2026-09-22-cartographer-evidence-gaps.md) records the
synthetic failure and limitations of the historical evidence.

## Observed defect and affected path

`develop_methods -> MethodLock.write -> MethodLock.read -> futility/calibrate/evaluate`
uses rounded score serialization. AURC is calculated before score rounding, while
the checksum also rounds. Synthetic scores `[1, 1+1e-13]` become equal on write;
AURC changes from 0.75 to 1.0 for risks `[0.5,1.5]`. Subsequently adding `1e-13`
to a stored score passes the old reader's checksum comparison yet changes AURC
back to 0.75. This is both semantic loss and a subprecision integrity blind spot.
It does not prove historical artifacts were modified or establish the exact cause
of the historical diagnostic discrepancy.

## Minimal repair

1. Keep existing artifacts untouched. Missing format version means legacy v1.
   Legacy canonical checksums and numerical values remain readable; never silently
   upgrade, round again, or claim recovered pre-rounding precision.
2. New locks use explicit v2, included in the checksum, with Python JSON's float
   round-trip precision for scores, OOF AURCs and search-table values. Keep rounding
   for other artifact classes unchanged; do not alter global `_round_for_json`.
3. On read, validate supported version and the checksum of the supplied payload
   **before any lossy normalization**. Validate canonical structure as well, preserving
   valid v1 files but rejecting subprecision edits even if legacy rounded hashes agree.
   Reject unsupported/malformed versions and nonfinite numeric payloads explicitly.
4. Reader branches only at serialization/checksum interpretation, not scientific
   model selection or metrics. Existing run resume/terminal guards remain unchanged.
   Old locks stay legacy; newly developed v2 artifacts must not be substituted into
   completed or frozen runs. No migration of TG or automatic rerun is permitted.

## Verification before handoff

- Synthetic v2 score arrays, AURC and checksum round-trip exactly, including near-ties.
- Frozen literal synthetic v1 fixture retains its original digest and rounded values.
- A subprecision modification with an unchanged checksum is rejected for both formats.
- Version removal/change, unsupported versions and nonfinite values fail closed.
- Existing development/CLI round-trip, provenance, tamper and resume tests remain green.
- Inspect diagnostics loader separately: it currently reads JSON directly, so report
  readers must use the verified MethodLock boundary instead of duplicating validation.
- Follow targeted integration, full applicable regression and Ruff requirements in
  [verification governance](../../../CLAUDE.md#verify). Do not use real outcome data.

## Additional review 1 — lineage preservation

Rejected globally removing rounding: it would change historical lock and futility
checksums. Explicit new format plus verified legacy read preserves the recorded
scientific lineage; it does not retroactively certify old rounded rankings.

## Additional review 2 — integrity and scope

Rejected only changing the writer: the old reader still accepts subprecision edits.
Also rejected rounding inputs on read as a repair: that silently alters scientific
values. Validate raw payload first, preserve original values and fail closed.
Do not combine this repair with added-value family changes; that interpretation
requires separate contract reconciliation and is not needed to reproduce this defect.

## Implementation checkpoint — 2026-09-22

Implemented v2 exact-precision serialization, verified legacy v1 reads, raw-payload
checksum verification, version/nonfinite rejection and verified-lock use in the OOF
diagnostic loader. Existing artifact bytes and config were not modified. The retained
TG lock was read with its original semantic checksum
`9d86613dda463d234e59f23a34241c0b3c34dbe15dcabe392fa723071a9737e1` unchanged.

Targeted tests: 62 passed; experiment/eval/provenance integration: 234 passed.
Subsequently added nonfinite writer/no-file-created checks; full regression including
those checks is pending. Repository-wide Ruff check/format passed before that final
test addition; final rerun remains required. Local results do not authorize a scientific run.

Implementation review 1: legacy payload checksum is checked before reconstruction,
so rounding cannot hide a tiny score edit; v2 version is checksum-bound. Review 2:
the diagnostic loader no longer bypasses the verified reader; its ID-misalignment
test still reaches that specific failure rather than failing on a malformed fixture.
Historical score precision is not recovered and old confirmatory results are unchanged.

## Regression recovery checkpoint — 2026-09-22

The first full regression's observation was interrupted after 91%; its handle and
process were subsequently absent and the terminal summary was not recovered.
It is **unverified**, not a pass. Four earlier failure markers were reproduced as
four exit-code discovery failures: three pre-existing endpoint exceptions were
unclassified, and three non-exception handler bases were unrecognized. Their actual
inheritance and absence from the COMPOSE driver graph were checked before registration.
Discovery now pins 81 classes while the runtime rejection roster remains 42.
An explicit hierarchy/import-graph test preserves this distinction.

Review 1: no endpoint exception was admitted as a COMPOSE pre-seal rejection.
Review 2: no scanner/assertion was removed; actual base types and graph absence
are tested. Targeted classification/precision/diagnostics: 61 passed; final Ruff
check/format and diff whitespace check passed. Full regression must run again with
durable stdout and JUnit evidence. This is a local regression repair only; the
[COMPOSE release gate](../COMPOSE-SEAL-READINESS.md) remains blocked and unopened.

## Full regression completion — 2026-09-23

The retry completed: **4599 passed, 51 skipped, 4 warnings in 1582.88 seconds**,
exit code 0. JUnit independently records 4650 tests, zero failures and zero errors.
The earlier interrupted run remains unverified. Command from the repository root:

```sh
UV_OFFLINE=true UV_CACHE_DIR=/private/tmp/alive-uv-cache UV_PROJECT_ENVIRONMENT=/Users/jam/ALIVE-handoff/dependency-preflight-20260916/local-native-runtime-01/venv uv run --locked --no-sync pytest -q -ra --junitxml=artifacts/cartographer-regression-20260922/retry01.xml > artifacts/cartographer-regression-20260922/retry01.log 2>&1
```

Local evidence is retained in `artifacts/cartographer-regression-20260922/`:
`RUN.md`, `retry01.log`, and `retry01.xml`. Production/test inputs were unchanged
during execution; the implementation remains uncommitted.

Skip scope: 50 require native Linux kernel capabilities or explicit disposable
fixtures; one requires optional torch, absent here. Warnings comprise anndata
string-index conversion, a duplicate-gene negative fixture, and two pytest
record_property/xunit2 compatibility notices. No failing tests were excluded.
This closes the local regression requirement, not the pending Linux isolation proof.
No scientific run, historical artifact rewrite, config change or seal access occurred.
The remaining actual-data reporting gaps in the evidence audit are not resolved by tests.
