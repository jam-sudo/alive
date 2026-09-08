# COMPOSE-K562-v1 — decision: what to do about gene sharing in the pair bootstrap

> **STATUS: APPROVED 2026-08-29 and IMPLEMENTED.** Owner instruction: proceed with the
> recommendation. The recommendation, its reasoning, and the two options it rejects are recorded
> below so the choice can be re-examined rather than re-litigated.
>
> **`config_sha256` MOVES with this decision** — `5fea3b9e…` → `0d207746…`. That is a **new run
> identity**, and it is the point of doing this before the seal rather than after. It remains a
> **floor, not the target**: the six activation blockers are still null, so the digest moves again.

**Owner sign-off — Jae Min Yoon / 2026-08-29.** Approves the recommendation in §4, the two
registered config values in §5, and the digest move. Does **not** approve an exact Git SHA, fill any
activation blocker, or open the seal.

---

## 1. What was found, and what was measured

The external audit reported `stats.pair-gene-dependence` as a **logical** argument: if pairs sharing
a gene have non-zero error covariance, the pair-i.i.d. bootstrap's effective sample size and
max-deviation quantile *could* be wrong. Nothing was measured. Adjudicating it by measurement
(evidence: `evidence/2026-08-26-pair-gene-dependence-coverage/`) produced three results.

**The structural premise is true, and not marginally so.** Reproducing the registered split from the
real data — obs labels only, `.X` never opened — and checking it against committed pod evidence
(7/7: singles 105 · pairs 131 · z-universe genes 73 · calibration genes 44 · roles 41/22/68), the
headline `sealed_double_unseen` role is **22 pairs drawn from 21 genes**, mean gene degree 2.10, and
**not one of the 22 is gene-disjoint from all the others**. The pair-i.i.d. assumption is not
approximately satisfied here; it is violated by construction.

**The channel the audit's wording suggests does not bite.** θ is a ratio, `1 - mean(e_L1)/mean(e_C)`.
A gene effect common to every method is a shared multiplier that largely cancels between numerator
and denominator; what is left is extra marginal dispersion, which the i.i.d. bootstrap absorbs by
widening the band. Twenty conditions — the real graph at ICC 0 → 0.41 and a synthetic ladder from
degree 1.0 to 5.5 — all landed in 0.955–0.967, at or above nominal.

**The channel that does bite is method-differential.** Give each method its own gene effect; that
component does not cancel out of `d_i = e_C - e_L1` and is correlated across every pair containing
the gene. On the real structure, with the registered estimator (n=22, 10 000 replicates, five
comparators, 95% family confidence, 1500 trials per cell), family-wise coverage falls to
**0.9307 / 0.9240 / 0.9373**. A control with identical added variance and **zero** gene sharing does
not move (0.966–0.972), so the loss is caused by the sharing, not by the variance.

## 2. Why the obvious remedy is unavailable

`sealed_double_unseen` has **two** connected components, sizes 19 and 3 — 86.4% of pairs in one. A
cluster bootstrap would have an effective cluster count of **2**. A gene-level resample over 21 genes
changes n per replicate and with it the registered estimand. **This design has no resampling unit
that absorbs the dependence.**

## 3. How much band would repair it — measured, not assumed

Because the coverage event is `max_C (θ̂_C − θ_C) ≤ q`, coverage under a band inflated by λ is
`P(m ≤ λq)`, which can be swept from the **same** trials without re-running the estimator.

| σ_gene_diff | λ=1.0 | λ=1.1 | λ=1.15 | λ=1.25 | λ=1.5 | minimum λ restoring 0.95 |
|---|---|---|---|---|---|---|
| 0.00 | 0.9620 | 0.9760 | 0.9807 | 0.9893 | 0.9987 | **1.0** |
| 0.30 | 0.9307 | 0.9553 | 0.9613 | 0.9773 | 0.9907 | **1.10** |
| 0.60 | 0.9240 | 0.9447 | 0.9533 | 0.9640 | 0.9827 | **1.15** |
| 0.90 | 0.9373 | 0.9513 | 0.9573 | 0.9653 | 0.9853 | **1.10** |

Two things matter here. The whole measured degradation is repaired by **inflating the band 15%** —
the exposure is bounded and modest. And **the worst case is interior**: coverage is lowest at
σ=0.60 and recovers at σ=0.90, because q grows faster than the dependence effect (0.73 → 1.27). The
measured range therefore brackets the worst case rather than running off its edge.

## 4. Decision

**Limit the confirmatory claim to the registered resampling assumption, and pre-register a
band-inflation sensitivity report — enforced by the config loader, not by prose.**

The primary verdict is **unchanged**: `GI_LEARNABLE_WIN` / `PARTIAL` / `NO_DISTINCT_WIN` are decided
on the registered bound (λ = 1.0) exactly as spec §10.5 already says. Alongside it, the verdict is
re-reported at each registered λ, so the report states where the verdict flips instead of asserting
that it does not.

**Two alternatives were considered and rejected.**

**A design-effect band inflation calibrated on `combo_calibration`** was rejected on three grounds.
(i) An ICC estimated from 41 pairs over 37 genes is very noisy, and that noise would *multiply* the
headline band. (ii) Decisively, `combo_calibration` is the role GEARS and CPA **train on**; their
`d_i` there reflects in-sample behaviour while `sealed_double_unseen` is extrapolation. Carrying an
intraclass correlation across that boundary is the cross-role transfer invariant 7 forbids. (iii) A
deliberately conservative λ would avoid a false win — it can only err toward `NO_DISTINCT_WIN`,
which invariant 14 accepts as a result — but the number would come from the simulation's invented
data-generating process. Pre-registering an unanchored constant is the move this repository has
repeatedly refused.

**Stating the assumption and changing nothing else** was rejected because it is honest labelling
with no analysis. The verdict gates would still consume a bound measured to undercover by up to
~1.5× the registered family-wise error rate under a plausible channel, and a footnote does not tell
a reader whether *this* win survives it. It also uses none of the advantage of the seal being
closed — everything it does could be done afterwards.

The chosen option reports a curve rather than a point, cannot become an always-fail gate (the
primary verdict is untouched), cannot manufacture a win (it makes fragility visible), requires no
cross-role extrapolation, and is fixed before outcome access as invariants 1 and 17 require.

**Stated limitation of the anchor.** The λ ladder is anchored to a *model-based* measurement, not to
Norman data: the true size of the method-differential component is unmeasured and needs Phase-2a dev
outcomes. That is exactly why the decision reports the verdict at each λ rather than asserting the
true λ.

## 5. What is registered

```yaml
inference:
  simultaneous_coverage_claim: conditional_on_registered_resampling_unit
  sensitivity_band_inflation: [1.0, 1.1, 1.15, 1.25]
```

Both are enforced exactly by `ComposePhase2Config`'s loader, in the same shape as
`shared_resamples_across_contrasts`, `secondary_are_verdict_gates` and decision #7's
`factor_bank_normalization` — a config edit cannot turn them off, and a missing key fails closed at
two sites (`_close_schema` and `_require`).

Each ladder value has a reason, from §3: **1.0** is the registered bound and the only value the
verdict is decided on; **1.1** restores nominal at σ=0.30 and σ=0.90; **1.15** restores nominal at
the worst measured point; **1.25** carries roughly 1.7× headroom beyond that worst point, which the
interior-worst-case structure makes a meaningful bound rather than an arbitrary one.

## 6. What this decision does not do

It does not fill an activation blocker, approve an exact Git SHA, advance the runbook past §2.5, or
open the seal. It does not change the estimator, the comparator family, the margins, the multiplicity
correction, or any verdict threshold. The sensitivity report is **descriptive-only** and can never
be a verdict gate.

## 7. Still open after this decision

The reporting implementation — computing and emitting the verdict at each registered λ, and the
flip point per comparator — is **not** in this change. This decision registers and freezes the
contract; the report that consumes it is the next increment.

**headline wording 은 더 이상 열려 있지 않다.** 결과군별 headline 문장은 D4(2026-09-07, "모두 권장사항으로
진행")로 아래 §8 에 사전 확정되었다. 이 §7 에 남는 열린 항목은 위의 보고 구현뿐이다.

## 8. seal 전에 확정된 headline 문장 (2026-09-07, D4)

verdict 는 등록된 밴드(λ=1.0)에서만 내려진다. 아래 세 문장은 **결과를 보기 전에** 확정한다. 사다리는 등록된
`sensitivity_band_inflation` 이고 flip 표기는 `phase2b.py` 의 `NEVER_FLIPS`·`FAILS_AT_REGISTERED_BAND` 를
그대로 쓴다 — 문장이 코드 어휘에서 떠내려가지 않게 하기 위해서다.

**(i) `flip_point == NEVER_FLIPS`.** "headline contrast 는 등록된 sensitivity 사다리 전 구간에서 material margin 을 유지한다. 이는 등록된 resampling 단위
(`perturbation_pair`) 가정 아래의 결과이며, 22 pairs/21 genes 의 구성상 pair-i.i.d. 위배를 흡수할 재표본 단위가 이 설계에 없다는 제한과
실제 method-specific dependence 의 크기가 미측정이라는 제한은 그대로다."

**(ii) 등록 밴드에서는 승리, 상위 λ 에서 뒤집힘.** "등록 밴드에서는 승리했으나 등록된 상위 inflation λ=<flip> 에서 유지되지 않았다. 이는 pair resampling
가정에 조건부인 결과이며 unconditional efficacy 또는 unconditional 95% coverage 를 주장하지 않는다. 저장소 simulation 의 method-differential coverage
(명목 0.95 대비 0.9240~0.9373)는 특정 생성모형의 값이지 실제 Norman coverage 측정이 아니다."

**(iii) `FAILS_AT_REGISTERED_BAND`.** "등록된 밴드에서 material margin 미달 — `NO_DISTINCT_WIN`. 불변식 14 에 따라 이는 결과이며 threshold 를 사후 변경하거나
sensitivity 사다리의 다른 λ 를 verdict gate 로 승격하지 않는다."

세 문장 어디에도 "mechanistic" · "causal" · "context transfer" · "unconditional 95%" 를 **긍정 claim 으로** 쓰지 않는다(명시적 비주장 절에서만 등장한다).
calibration in-sample ICC 의 double-unseen 이식과 λ=1.15 를 새 nominal gate 로 쓰는 것은 금지(결정문 §2, 불변식 7).
