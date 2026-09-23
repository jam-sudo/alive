# Cartographer evidence audit — 2026-09-22

Status: incomplete milestone audit, not a new scientific evaluation or release.
Scope: preserved TG reports and historical source, without outcome-store access.
Development priority follows the [realignment plan](../plans/2026-09-22-cartographer-realignment.md).
`TG-K562-v1` remains COMPLETE / `NO_DISTINCT_WIN`; its consumed seal is unchanged.

## Existing actual-data comparison

Run `d18c601b6855b3b1`, source SHA `a087d7df76114b5f46cca8675036bbb1c79a2f7d`,
Replogle K562 essential CRISPRi. Preserved `report.json` file SHA256:
`70c8d17e265d91bf23c7d3f5288969790a9e66d2f61969f335b75d3dd6619407`.
The retained per-run custody manifest matched all 21 files during this audit.
This validates retained bytes, not every scientific assumption.

Eligible perturbation IDs: 1645; base_train 740, method_development 411,
conformal_calibration 247, sealed_evaluation 247. Excluded: 354 first failed the
minimum-cell check, 58 subsequently failed external-feature availability. These
are ordered exclusion categories, not independent missingness prevalence estimates.
Perturbation IDs, cells, sampling repeats and biological replicates are distinct units.

The frozen additive-ridge predictor translates control cells by a predicted mean
shift in a train-fitted 50-dimensional response space. Risk is repeat-averaged
equal-cell energy distance, not percent error or mechanistic accuracy. Routing
uses risk divided by the cohort mean; conformal coverage uses the unnormalized risk.

| Method | Normalized AURC | Comparator minus gate | Family lower bound |
| --- | ---: | ---: | ---: |
| gate | 0.89140482 | — | — |
| ensemble_disagreement | 0.83261254 | -0.05879228 | -0.20347479 |
| gbm_error | 0.87267982 | -0.01872500 | -0.16340751 |
| nearest_feature | 0.94318009 | 0.05177527 | -0.09290724 |
| residual_only | 0.89588899 | 0.00448417 | -0.14019835 |
| ridge_error | 0.91155364 | 0.02014882 | -0.12453369 |

AURC is lower-is-better. Gate AURC is the discrete mean of the persisted curve;
comparator AURCs add the stored deltas. Bounds are recorded simultaneous one-sided
95% family bounds, not newly computed intervals. All are negative: registered
superiority was not established; equivalence is not established either.

Calibration N=247, alpha=0.1, rank=224, bound=2.2834480471. The rank does not hit
the implementation's small-N clipping edge. Observed marginal coverage=0.8987854251;
177/247 predictions selected. Neither coverage nor trust score is a per-query
probability of correctness. Recorded conformal pass does not prove routing superiority.

## Gaps requiring disposition

1. **Added-value interval scope:** the as-run plan §6.3 requests a simultaneous bound;
   `src/alive/eval/bootstrap.py` separately uses only `residual_only`, producing
   -0.0340797466 instead of the five-comparator lower bound -0.1401983466. The same
   code path remains today. Both fail in this run; preserve the verdict. Before any
   future scientific use, reconcile the family interpretation against the authoritative
   contract and verify the implementation on synthetic inputs. Do not patch old artifacts.
2. **Seed reporting:** development averages five registered OOF seed scores; final
   GBM refit uses the first seed (11). No retained seed-wise variability report was
   found. This is not five independent confirmatory runs.
3. **Secondary reporting:** the sidecar retains a gate curve and summarized contrasts,
   not every comparator curve, raw risk scale summary or descriptive pairwise interval.
   The registered comparator-specific fixed-coverage metrics cannot all be recovered
   from this report. Do not reopen outcomes to fill them.
4. **Adequacy and reproducibility:** N exceeds the registered 200 minimum, but that
   alone is not an effect-size-specific power justification. Exact executed command
   logs, biological replicate structure and seed variability remain unverified;
   recorded runtime/cost are null. Do not infer them from a runbook.
5. **Historical diagnostic discrepancy:** the existing exploratory OOF diagnostic
   reports nearest-feature AURC=0.8856826145 while MethodLock records 0.885635814749;
   residual-only also differs slightly. Thus the historical spec's statement of exact
   reproduction needs a dated qualification, not silent acceptance or rewritten evidence.
   Cause has not been established; rounding/ties are hypotheses only.

The OOF diagnostic (N=411) is explicitly exploratory in the
[TG spec](../specs/2026-06-20-cartographer-design.md); it supplies neither missing
confirmatory statistics nor independent replication. The local search of retained
run directories and handoff text found no additional exact TG invocation log.
This is a bounded search result, not proof no other copy exists.

## Two additional reviews and next action

Scientific review: preserve negative verdict, distinguish marginal calibration from
ranking, and flag single-comparator versus full-family inference. Reporting review:
preserve historical provenance and identify absent outputs rather than inventing them.
The 50% milestone is **not yet certified**; primary results exist but the complete
baseline/error/limitations evidence contract has unresolved gaps.

Next: resolve the added-value contract interpretation and test it synthetically;
trace OOF serialization/metric history without new outcome access. These are safe
development actions, not permission to rerun TG or start another scientific protocol.

## Synthetic serialization proof — 2026-09-22

A two-item synthetic MethodLock passed `write -> read -> checksum` validation while
changing ranking semantics. Original scores `[1.0, 1.0000000000001]` became
`[1.0, 1.0]`; risks `[0.5, 1.5]` gave original AURC=0.75 but reloaded-score AURC=1.0.
The stored AURC remained 0.75. All probe assertions passed. No scientific artifact
or outcome was read by the probe.

Root mechanism: `experiment/develop.py` computes OOF AURC before `_canonical()`
rounds score values to 12 decimals; `metrics/selective.py` groups exact equal scores.
The as-run SHA has the same rounding code. Checksum round-trip therefore proves
rounded-byte consistency, not preservation of score ordering or metric semantics.
This establishes a reproducibility defect in the serialization path, but **does not
prove the exact cause of the historical OOF discrepancy**: pre-rounding scores were
not retained. Do not reverse-engineer them or replace recorded values.

Review 1: retain historical lock checksums; a precision change must not silently
invalidate or reinterpret old artifacts. Future corrected persistence needs an
explicit compatible/versioned contract, with exact score round-trip and a regression
check for induced ties. Review 2: distinguish the confirmed serialization defect
from the added-value **contract ambiguity**. The latter is a single-comparator bound
in code and a broadly worded simultaneous requirement in the plan; no changed
scientific inference is authorized by this audit. The existing primary family gate
independently prevents a superiority claim in the preserved run.

## Reader integrity extension — 2026-09-22

The same synthetic probe then changed a stored score by 1e-13 without changing the
checksum. `MethodLock.read` accepted it and its AURC changed from 1.0 to 0.75.
Thus verifying the rounded reconstructed checksum is insufficient to bind exact
score semantics. This is not evidence of tampering in the retained scientific run.
The [precision repair contract](../plans/2026-09-22-methodlock-precision-repair.md)
sets the minimal compatible writer/reader repair and required negative tests after
two additional reviews. Production implementation and regression are still pending.

## Repair verification update — 2026-09-23

The preceding pending statement records the pre-implementation checkpoint.
The compatible precision/integrity repair is now implemented and its
[full local regression completed](../plans/2026-09-22-methodlock-precision-repair.md#full-regression-completion--2026-09-23).
Historical artifacts remain untouched; lost precision was not recovered. The five
reporting/contract gaps above remain distinct from the repaired serialization defect.
The 50% milestone remains uncertified; this update supplies software verification,
not new scientific evidence or a changed verdict.

## Added-value scope disposition draft — 2026-09-23

This is a reviewed recommendation, **not owner reconciliation of the historical
contract**. The [as-run plan](../plans/2026-06-20-cartographer-mvp.md), section 6.3,
requests a simultaneous lower bound for the direct residual-only contrast after
defining the complete comparator family. The [spec](../specs/2026-06-20-cartographer-design.md),
sections 10.1–10.3, requires full-family primary success and a direct residual-only
win. In `src/alive/eval/bootstrap.py::confirmatory_inference`, the primary family
includes residual-only, but the added-value field is computed with a singleton
family. The two scopes must not be represented as interchangeable.

For this implementation, with identical data, seeds, replicates and confidence,
each replicate's maximum deviation across the full family is at least its
residual-only deviation. The quantile is therefore no smaller, and subtracting
it from the same point contrast yields a full-family residual lower bound no
larger than the singleton lower bound. Thus full-family primary success already
implies a positive singleton residual bound when residual-only is in that family.
This is a property of the inspected calculation, not a proof of bootstrap coverage
or a substitute for reconciling the reporting contract.

Synthetic check: N=32, 200 replicates, input RNG seed 20260923, bootstrap seed 71.
Full-family residual lower=-0.2862711023690464; singleton lower=-0.2367298942745822.
Assertions verified the inequality and identical point contrast. A separate
synthetic verdict fixture verified that failed primary and secondary clauses
prevent a win for either value of `added_value_passes`. No guard was mocked and
no scientific outcomes or preserved artifacts were used as probe inputs.

Reproducible local command (exit 0):

```sh
UV_OFFLINE=true UV_CACHE_DIR=/private/tmp/alive-uv-cache UV_PROJECT_ENVIRONMENT=/Users/jam/ALIVE-handoff/dependency-preflight-20260916/local-native-runtime-01/venv uv run --locked --no-sync python /Users/jam/ALIVE-handoff/cartographer-family-scope-probe-20260923.py
```

**Recommendation:** preserve TG's recorded singleton field with its actual scope,
and separately quote its already-persisted full-family residual lower bound.
For any future reconciled contract, use the primary family's residual-only bound
for the added-value certification rather than calculate and ambiguously label a
second family. Do not patch the completed run, replace its verdict, or silently
change the present scientific implementation under a documentation repair.

Additional review 1 (claim validity): both recorded bounds are negative, so this
scope difference does not reverse the preserved conclusion. It also does not
establish no residual-independent signal, equivalence, or adequate statistical power.
Additional review 2 (execution/lineage): full-family inclusion of residual-only is
essential to the implication above; it is not a general statement about arbitrary
rosters. Future implementation needs an explicit roster check and synthetic
verification after authoritative reconciliation, with no changes to old artifacts.

## Additional retained error-report evidence — 2026-09-23

The report identified above also retains the secondary AUGRC degradation upper
bounds (gate minus comparator, registered margin 0.02):

| Comparator | Simultaneous upper bound |
| --- | ---: |
| ensemble_disagreement | 0.06976642 |
| gbm_error | 0.07386971 |
| nearest_feature | 0.03797453 |
| residual_only | 0.04645442 |
| ridge_error | 0.07420634 |

Every bound exceeds the margin. This is failure to certify non-degradation, not
proof that every comparator is materially better. Together with primary failure,
it independently prevents `GATE_WINS` in the recorded truth table.

The report also records selected-set scalar-bound coverage 0.9039548023 among
177 selected perturbation IDs, and effective covered fraction 0.6477732794 of all
247 IDs. These are observed summaries, not new conditional guarantees. The minimum
retained self-distance floor is 0.3620109954, with `reliability_ok=true`; neither
that Boolean nor a positive floor establishes that all biological noise is modeled.
No missing raw predictor-error mean, comparator fixed-coverage risk, pairwise CI,
biological-replicate count or seed-variability estimate is inferred from these fields.

The audit now distinguishes (a) available actual-data error/routing evidence,
(b) missing report outputs, and (c) a future-use contract decision. The latter does
not erase the existing negative comparison; the former does not certify a complete
50% deliverable while registered reporting outputs remain missing.

### Review procedure attribution

The `scientific-critical-thinking` skill informed proportionality of the critique
and separation of observations, non-claims and unresolved evidence. Graphify was
used for code navigation, followed by direct source inspection. Neither is evidence
of scientific validity. Skill reference, metadata checked 2026-09-23:
Kassis, T., Agarwal, V., He, Y., Patel, D., & Brueckner, A. M. (2026).
[Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents](https://doi.org/10.48550/arXiv.2609.00065).

## Retention repair checkpoint — 2026-09-23

Field-level inspection of preserved `result.audit.json.confirmatory` confirms that
descriptive pairwise intervals, bootstrap seed and replicate count are not in that
sidecar. The serializer `_confirmatory_to_jsonable` omitted these already-computed
`ConfirmatoryInference` fields. They cannot be recovered by rendering the old report.

The serializer now retains `descriptive_pairwise_intervals`, `n_replicates` and
`seed` for future authorized evaluations. No inference formula, verdict condition,
outcome access or existing artifact was changed. A synthetic regression verifies
exact JSON interval/settings retention and unchanged inference checksum/decision fields.
Targeted runner/bootstrap tests: 53 passed in 13.65 seconds. Broader regression for
this additional change is pending; the earlier full green predates it.

Review 1: descriptive percentile intervals are not simultaneous certification;
the persisted field names distinguish them and they do not enter verdict logic.
Review 2: the public report has a locked top-level schema. Do not put descriptive
intervals under `simultaneous_intervals` or pretend they are verdict evidence just
to avoid a schema decision. This checkpoint repairs retention only; public report
schema reconciliation and other missing error summaries remain open. Existing
reports are not regenerated, and no historic confidence interval is invented.

Follow-up verification: `uv run --locked --no-sync pytest -q tests/alive/experiment
tests/alive/eval tests/test_claude_md_anchors.py tests/test_documentation_hygiene.py`
with the same recorded local runtime passed **215 tests in 26.50 seconds**.
Repository-wide Ruff check and format check (375 files), and `git diff --check`,
passed. Full repository regression after this retention change remains outstanding;
do not extend the earlier 4599-pass result to this later code revision.

## Retention full regression completed — 2026-09-23

The subsequent complete run includes the retention repair: **4600 passed, 51 skipped,
4 warnings in 1544.73 seconds**, exit code 0. JUnit records 4651 tests, no failures
and no errors. Durable local command, logs, hashes and environment limitations are
in `artifacts/cartographer-regression-20260922/RETENTION02.md`, `retention02.log`
and `retention02.xml`. Fifty skips require native Linux/disposable fixtures; one
requires optional torch. This supersedes only the pending local-regression status
above, not any scientific gap, historical result or Linux isolation requirement.

The existing exploratory OOF report was also rechecked by JSON projection, without
new outcome access or recomputation. Its SHA256 remains
`a53205f40293a9023d862146b67b89afe56ecc7f910acdbc70842087bb0aad80`.
The off-repository note `2026-09-23-retained-oof-error-evidence.md` in the handoff
directory records all six method summaries and three explicitly selected error
examples, N=411 development perturbation IDs. This expands available development
error evidence, not independent confirmation or recovery of missing sealed statistics.

## Development error supplement delivered — 2026-09-23

The descriptive supplement specified in the realignment plan was produced from
the retained MethodLock and development-error artifacts only. All 411 unique IDs
were aligned, all six methods included, and input hashes remained unchanged.
No raw expression, outcome-store call, fit, selection or sealed reevaluation occurred.
The handoff directory contains `2026-09-23-cartographer-dev-supplement.md`, its JSON,
and `cartographer-dev-supplement-20260923.py`. JSON SHA256:
`b48244534421ae6f35b5475deb451df2f830fe05c886e265075240cc447bcf57`.

Unnormalized development error mean=1.14306216, median=0.80298959,
SD(ddof=1)=1.05846696; Q1/Q3=0.51144349/1.31806527. These describe observed
energy distances, not percentages or uncertainty intervals. Requested coverage
25/50/70/100% uses k=103/206/288/411, with the production tie-averaging convention.
The supplement reports all six AURCs and raw/normalized fixed-coverage risks.
At the requested 70% point, normalized gate risk=0.96780497 and ensemble risk=
0.91728917. This descriptive development difference is not a superiority test.

Synthetic constant/tie/scale checks, complete ID/roster checks, input hash checks
and raw/normalized scaling checks passed. The existing EDA skill's NPZ safety
inspection also covered all 411 numeric entries, with no nonfinite errors. No
source/test changes were required. The report records the dirty source state,
exact input/script/module hashes and actual Python/NumPy versions.

This closes the development-level error-summary gap, not missing sealed statistics,
independent biological replication, seed variability or original invocation logs.
The legacy precision limitation is explicit. No 50% or scientific-release claim
is made solely from this exploratory supplement.
