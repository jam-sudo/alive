# Cartographer purpose and development realignment — 2026-09-22

> **2026-09-23 current direction:** The [goal-alignment contract](#goal-alignment)
> below supersedes the later historical next-action recommendations to select a new
> comparison/source first. Reaudit milestone applicability first; no completion or
> scientific execution authorization is granted by this correction.

현재 구현·완료 조건·다음 작업은 [Cartographer milestone](2026-09-23-cartographer-milestones.md)을 따른다.
50%는 실데이터 비교·오차·한계 보고, 100%는 명시된 적용 범위의 연구용 Cartographer 전달 단계다.

## Purpose and preserved boundaries

The owner clarified the current product: evaluate **when a frozen perturbation
predictor can be trusted**, rather than require a new predictor or chemical dataset.
Chemical treatment is a perturbation, but chemical perturbations are not mandatory
for this purpose. The long-term virtual-cell vision remains separate from current delivery.

The existing [TG design](../specs/2026-06-20-cartographer-design.md) defines risk ranking
against measured errors, a scalar global conformal error bound, and PREDICT/ABSTAIN.
Neither a trust score nor marginal coverage is a per-query probability of correctness;
coverage alone does not demonstrate useful error ranking. Active experiment acquisition
is later work, not a prerequisite for this milestone.

This plan changes development priority, not scientific registration:

- `TG-K562-v1` remains COMPLETE / `NO_DISTINCT_WIN`; its seal was opened once.
  Reuse preserved reports, not sealed outcomes for tuning or a fresh evaluation.
- `COMPOSE-K562-v1` remains ACTIVE / RELEASE-BLOCKED / UNOPENED. Predictor research
  is not proof of Cartographer utility; this plan grants no real fit or sealed run.
- `CT-RPE1-v1` remains DEFERRED. Existing [governance](../../../CLAUDE.md#invariants)
  and [release readiness](../COMPOSE-SEAL-READINESS.md) remain authoritative.
- Tahoe endpoint, drug structure/dose and solver preparation are preserved auxiliary
  work, deferred from the critical path. No further downloads, fits or cloud work
  are authorized here. Resume only for a specific registered evidence gap.

## Next work, in order

1. **Audit existing evidence without reopening evaluation.** Trace the frozen predictor,
   gate, calibration and evaluation/report path to preserved TG artifacts. Inventory
   what is implemented, what was actually measured, comparator results, exact claim-unit
   N, exclusions, uncertainty and limitations. Separate missing artifacts from missing capability.
2. **Review applicability before reuse.** Check role isolation, predictor/version binding,
   measured-error risk curves/AURC and calibration assumptions. Specifically audit the
   small-calibration-sample rank clipping in `src/alive/conformal/error_bound.py` before
   making general nominal-coverage claims; this plan does not establish whether the
   completed TG run was affected. Do not silently alter its recorded result.
3. **Deliver the evidence-backed gap report.** Reuse an adequate preserved result rather
   than rerun it. If new scientific evidence is necessary, draft the smallest separate
   protocol with a frozen predictor, registered trust comparators, allowed development /
   calibration / evaluation roles, estimand, power or detectable effect and exclusions.
   Obtain the required authorization before outcome access; do not reuse TG's consumed seal.

The owner's 50% milestone remains **actual-data baseline comparison, errors and limitations
report**. For the clarified Cartographer purpose, show both the underlying predictor errors
and the trust-layer comparison, including a negative result if that is what the evidence says.
The [endpoint-specific route](2026-09-21-endpoint-real-data-milestone.md) is no longer mandatory.
This does not add Active Cartographer or deep-model requirements, and does not declare 50%
achieved: existing evidence must first be audited against this deliverable. Synthetic tests,
metadata preparation and infrastructure success alone do not satisfy it.

## Additional review 1 — scientific claims

Retain the completed negative routing verdict; do not equate functioning code with scientific
superiority. Separate marginal calibration, measured-error ranking and per-query reliability.
New datasets, predictors or claims require their own applicable contract, not a renamed old run.

## Additional review 2 — scope and execution

Avoid replacing the chemical detour with another architecture project. Start with existing
artifacts and code, preserve preparation work, and implement only a demonstrated delivery gap.
Protocol states, signed decisions, config values and seal counts are unchanged by this plan.

## Evidence checkpoint — 2026-09-22

The [TG evidence audit](../audits/2026-09-22-cartographer-evidence-gaps.md) located the
existing actual-data comparison and verified retained-file custody. It records
reporting gaps and an added-value interval scope discrepancy; no new evaluation
was run and the 50% milestone is not yet certified. Follow its next safe checks.

## Completion audit and next reporting step — 2026-09-23

The local retention repair now passes the full regression; that is software
evidence, not the actual-data milestone. The current evidence disposition is:

| Milestone component | Established evidence | Remaining limitation |
| --- | --- | --- |
| Actual-data lineage and units | Preserved TG run identity, source/checksum lineage, role counts, ordered exclusions | Biological replication and exact original invocation remain unverified |
| Frozen predictor and trust comparators | Preserved six-method comparison, N=247 sealed IDs, negative verdict and family bounds | No superiority or cross-context claim; added-value scope needs reconciliation for future scientific use |
| Predictor errors | Energy-distance definition, conformal bound/coverage, normalized gate curve, selected development error examples | Cohort-level unnormalized error summary and complete comparator fixed-coverage reporting missing from the sealed sidecar |
| Uncertainty and limitations | Recorded simultaneous bounds, disclosed missing seed variability/adequacy, legacy precision qualification | Missing outputs cannot be inferred from a passing test or recreated by reopening the seal |
| Reproducibility | Retained artifact custody, source/environment identifiers, repaired serialization and retention | Repairs apply forward; they cannot reconstruct discarded historical information |

Next safe action is a **descriptive development-artifact supplement** within the
existing TG spec section 11.5 development-only diagnostic boundary. Inputs are the
preserved, checksum-verified `methodlock.json` and `dev_errors.npz` for
`d18c601b6855b3b1`, not raw expression or sealed outcomes. Use the verified existing
loader and registered metric implementations. Do not call fit, develop, calibrate,
evaluate-once or overwrite any original run artifact.

Before calculation, fix this reporting scope:

- All 411 retained development IDs, all six methods; no outcome-selected universe
  or method roster. Report ID alignment, finite-value validation and exact count.
- Summarize existing unnormalized errors (mean, median, range and quartiles), and
  report mean-normalized AURC plus the already-registered fixed coverage points
  25%, 50%, 70% and 100%, using the implementation's tie convention.
- Label every result **retrospective / exploratory / development-only**. These
  scores were involved in method selection, and legacy persisted scores may differ
  from the lost pre-rounding values. Never present the supplement as an independent
  test, exact reproduction of all historical OOF metrics, or recovered sealed results.
- Do not manufacture seed-wise variance, biological N, power, uncertainty intervals
  or nominal conditional coverage. Report their absence; no new inference is planned.
- Save a new, clearly named supplement outside the immutable run directory, with
  input file hashes, command, code revision/dirty-state qualification and limitations.
  It supplements, but does not repair or replace, the historical confirmatory report.

Additional review 1: descriptive summaries of retained development errors do not
need a new predictor or chemical dataset. Restrict claims to the fixed artifacts;
no hyperparameter tuning or reuse of the consumed scientific seal is permitted.
Additional review 2: the supplement must not be used to conceal missing registered
confirmatory outputs. Reaudit the milestone after delivery; if genuinely new
scientific evidence remains necessary, use the separate-protocol authorization
path above rather than continuing unrelated infrastructure work.

### Reporting step completed — 2026-09-23

The [development supplement checkpoint](../audits/2026-09-22-cartographer-evidence-gaps.md#development-error-supplement-delivered--2026-09-23)
records the completed bounded artifact analysis, including all methods, error
distribution, fixed coverage points, provenance and limitations. Next is the
requirement-by-requirement milestone disposition; do not rerun this analysis or
replace missing confirmatory outputs with its development-only values.

## Milestone disposition — 2026-09-23

After the development supplement and two additional completion reviews, the
[requirement-by-requirement disposition](../audits/2026-09-23-cartographer-milestone-disposition.md)
finds **completion not established**. The review rejected treating the exploratory
supplement as a waiver of missing registered outputs. The current evidence packet
is delivered, but the 50% milestone is not certified. Next is a minimal separate
comparison contract or recovery of additional original evidence, not further
repetition of completed tests or artifact summaries.

The [minimal follow-up contract draft](2026-09-23-cartographer-followup-contract-draft.md)
now separates recommended paired-comparison/reporting rules from unresolved source,
exposure, replication, adequacy and authorization inputs. Its next step is metadata-only
source feasibility, not a scientific run or a new predictor implementation.

<a id="goal-alignment"></a>

## Goal alignment contract — owner-directed correction, 2026-09-23

Until the owner changes the objective, pursue the frozen-predictor Cartographer:
measure where its predictions are reliable, using actual predictor errors and trust
comparators. The 50% milestone remains **actual-data baseline comparison, errors and
limitations report**, not predictor superiority, a new dataset, or a complete virtual cell.

- Before choosing work, name the missing deliverable it resolves and the artifact
  that would demonstrate resolution. Reuse adequate permitted evidence and existing
  code first; tests, infrastructure and metadata alone do not meet the milestone.
- Assess each alleged blocker against the actual deliverable and applicable scientific
  contract. Separate historical confirmatory-report defects, current development-report
  requirements and optional future validation. Do not import every missing historical
  output into this milestone by default; do not waive a genuinely applicable requirement.
- An explicitly exploratory report can only support its stated development scope.
  It cannot repair old confirmatory results, establish independent validation, or hide
  invalid comparisons. Negative results are acceptable; completeness is evidence-based.
- New predictor development, drug/Tahoe expansion, day-6-to-day-8 transfer, new cell
  lines and fresh holdouts are not mandatory by default. Require a demonstrated gap
  and justification that the smallest in-scope alternative cannot resolve it before
  promoting such work to the critical path. Do not shrink the owner's deliverable either.
- Within authorized autonomy, make substantive decisions after two additional reviews:
  first check goal relevance/scope inflation, then scientific validity/authority and
  the smallest sufficient implementation. Apply findings and continue without routine
  reapproval. Explicit scientific access, seal and release approvals remain mandatory.
- If one action is blocked, continue independent work that advances the same goal.
  Do not declare the whole goal blocked on approval for an optional detour. Do not
  loop over unchanged summaries/tests/approval requests as a substitute for progress.

**Immediate next action:** reassess the existing six-method actual-data comparison
and development supplement against the owner-defined reporting milestone, tracing
each unmet requirement to its authority and scope. The prior conclusion that a new
independent comparison is necessarily required is under review, not established.
GWPS route selection is deferred and no longer a required owner decision for that
reassessment. Only demonstrated remaining gaps determine subsequent implementation
or a separately authorized minimal comparison. The goal is not declared achieved.

Additional review 1: rejected requiring time-shift generalization or a new holdout
merely to repair reporting. Also rejected treating a scope correction as proof of 50%.
Additional review 2: preserved all protocol states, sealed-access rules, signed records,
registered comparisons and negative verdicts; this changes work prioritization and
milestone applicability review, not scientific results or execution permission.
