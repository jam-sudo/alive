# Cartographer 50% milestone disposition — 2026-09-23

> **2026-09-23 correction:** The conclusion below that historical reporting gaps
> necessarily require a new comparison is under applicability review under the
> [owner-directed goal alignment](../plans/2026-09-22-cartographer-realignment.md#goal-alignment).
> Preserve all findings; neither completion nor a mandatory new holdout follows
> from this audit alone. Reassess the actual development-report milestone first.

## Decision and scope

**Completion not established.** Actual-data baseline comparison, development errors
and limitations have been delivered, but registered reporting and reproducibility
gaps remain. The owner's 50% milestone is not a measured percentage of every ALIVE
capability and does not require superiority. Nevertheless, a completed exploratory
supplement cannot by itself waive missing required evidence from the comparison.

The [current plan](../plans/2026-09-22-cartographer-realignment.md) permits reuse of
preserved evidence. The [original milestone definition](../plans/2026-09-21-endpoint-real-data-milestone.md)
does not require a favorable result and permits justified exploratory disposition.
The endpoint-specific dataset route was subsequently deferred. This assessment uses
the preserved confirmatory comparison **with its known gaps** and a separately labeled
complete six-method descriptive development comparison; it does not merge their Ns,
replace missing sealed values with development values, or recertify the old evaluation.

## Requirement-by-requirement evidence

| Requirement | Verified evidence | Scope of completion |
| --- | --- | --- |
| Actual permitted data | TG run `d18c601b6855b3b1`; Replogle K562 essential CRISPRi; retained manifest, data card, predictor, locks and reports | All 21 custody-manifest files checked again on this date and matched; no raw outcome or new sealed access |
| Frozen predictor baseline comparison | Six methods on common N=247 evaluation IDs in the preserved report; all six on aligned N=411 development IDs in the supplement | Existing negative comparison retained; new descriptive comparison uses retained scores/errors only, no new fit or selection |
| Predictor error report | Supplement reports unnormalized mean/SD/median/quartiles/MAD/range, all-method AURC, raw and normalized risks at 25/50/70/100% requested coverage | Complete descriptive development report; exact k=103/206/288/411 and tie convention reported, not claimed as missing confirmatory outputs |
| Units, exclusions and limitations | Audit records eligible 1645 and split 740/411/247/247, ordered exclusions 354 then 58; report distinguishes perturbation IDs, cells, seeds and unknown biological N | No biological replication or seed-wise uncertainty invented; no filtering of the development reporting universe |
| Uncertainty/adequacy disposition | Preserved simultaneous bounds and negative verdict; supplement explicitly exploratory with no inferential testing | No retrospective power claim or unsupported CI. Development selection and legacy precision prevent independent confirmatory interpretation |
| Purpose and model limitations | Frozen additive mean-shift predictor, measured energy-distance error, scalar conformal bound and trust ranking are distinguished | Not a new predictor, learned distributional/heterogeneity model, causal model, per-query correctness probability or prospective validation |
| Auditable handoff | Input hashes, current dirty source identity, module/script hashes, runtime versions, commands and separate output identities retained | Supplement can be reproduced separately; original exact invocation/runtime/cost gaps remain disclosed, not inferred from runbooks |
| Software verification for delivered repairs | Full local regression 4600 passed/51 skipped/4 warnings; JUnit 4651 tests, zero failures/errors; Ruff/format checks; documentation tests | Local regression only; Linux isolation proof remains outstanding and is not required to describe the preserved artifacts |

## Delivered evidence packet

1. [Preserved TG evidence and gap audit](2026-09-22-cartographer-evidence-gaps.md):
   actual comparator values, primary/secondary bounds, exact units and scientific limitations.
2. Local handoff `2026-09-23-cartographer-dev-supplement.md` and companion JSON:
   complete descriptive development error/coverage report, not a confirmatory replacement.
   JSON SHA256 `b48244534421ae6f35b5475deb451df2f830fe05c886e265075240cc447bcf57`.
3. Local handoff `cartographer-dev-supplement-20260923.py`: bounded, checksum-bound
   reporter using existing production metrics and verified loader; constant/tie/scale
   self-check and actual-data alignment/roster/scaling assertions passed.
   SHA256 `fd5e0531897f4fe6ce0288cba55f21d0dc7ff11e31ae08f22fe0f70916497c34`.
4. `artifacts/cartographer-regression-20260922/RETENTION02.md`, log and JUnit:
   completed regression evidence including the CI retention repair.

The supplement's mean error is 1.14306216 and median 0.80298959 (energy-distance scale).
Development AURC is 0.89895230 for gate and 0.83928479 for ensemble disagreement;
these point estimates are not a superiority test. The preserved scientific verdict
remains `NO_DISTINCT_WIN`. An honest negative result can meet a reporting milestone;
the unresolved issue here is evidence completeness, not the unfavorable verdict.

## Additional review 1 — avoid an easier substitute

Synthetic tests and infrastructure were not accepted as the milestone. Actual
predictor errors and all registered trust methods are reported on a common actual
development set, alongside the preserved evaluation evidence. No comparator was
removed, no dataset was substituted, no outcome-selected subset became the benchmark,
and a negative result was not converted to a positive claim. The exploratory
disposition is allowed by the original reporting milestone and is explicitly scoped.
However, that allowance does not establish that all the historical comparison's
required outputs may be omitted. Do not turn an exploratory supplement into a
substitute benchmark without resolving this evidence requirement.

## Additional review 2 — do not waive scientific requirements

The historical confirmatory packet remains incomplete in specific respects:
comparator fixed-coverage outputs, raw sealed risk summaries, descriptive pairwise
intervals, seed-wise variability and original exact invocation are unavailable in
the inspected custody. Added-value family wording also requires reconciliation
before future scientific use. These are **not repaired by this milestone decision**.
The report makes no new confirmatory inference, biological replication, adequacy,
heterogeneity or deployment claim. A future independent scientific comparison needs
its own authorization and applicable contract; TG's consumed seal cannot be reused.

No protocol/release state changed: TG COMPLETE / `NO_DISTINCT_WIN`; COMPOSE ACTIVE /
RELEASE-BLOCKED / UNOPENED; CT-RPE1 DEFERRED. The working changes remain uncommitted.
Future public report schema work, Linux proof and scientific validation remain
separate next steps, not hidden completed work.

## Completion-blocking disposition

The first optimistic draft treated missing historical outputs as limitations only.
The second review rejected that completion claim: the milestone explicitly rejects
incomplete comparisons as completed benchmarks, and the current evidence does not
prove all registered error/adequacy outputs. No goal-complete state was emitted.

Remaining evidence cannot be recovered by more unit tests or by repeating the same
artifact summaries. A complete resolution needs either additional preserved original
outputs from outside the inspected custody, or a separately authorized scientific
comparison with complete preregistered reporting. The latter must reconcile the
added-value family contract, freeze predictor/roster/roles, specify adequacy and
replication limits, and retain all required outputs. Do not reopen TG, repurpose
COMPOSE's unopened seal, or activate CT-RPE1 by inference from general autonomy.

Recommendation: preserve this packet as a completed evidence audit, not a completed
50% benchmark; prepare the smallest separate frozen-predictor comparison contract
before requesting its required scientific authorization. No new dataset, predictor,
cloud deployment or scientific run is selected or activated by this recommendation.
