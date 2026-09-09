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

`[2026-09-08 정정: Amendment B 보고 구현은 eb8d707 로 완료; §8 분기 함수는 이 정정으로 추가]`

**headline wording 은 더 이상 열려 있지 않다.** 결과군별 headline 문장은 D4(2026-09-07, "모두 권장사항으로
진행")로 아래 §8 에 사전 확정되었다. 이 §7 에 남는 열린 항목은 위의 보고 구현뿐이다.

## 8. seal 전에 확정된 headline 문장 (2026-09-07, D4)

verdict 는 등록된 밴드(λ=1.0)에서만 내려진다. 아래 네 문장은 **결과를 보기 전에** 확정한다. 사다리는 등록된
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

**(iv) `GI_LEARNABLE_WIN` — learned-family 다리 (2026-09-08 추가, spec §3.3 수정안 F 정합).** (i)~(iii) 은 headline additive contrast 의 결과군만 덮었다.
`GI_LEARNABLE_WIN` 은 그 위에 learned comparator 조건을 하나 더 요구하는데, 그 조건이 통과했을 때 쓸 문장이 사전등록되어 있지 않았다 — 수정안 F 가
강등한 바로 그 문장("식별가능 구조가 비-bilinear 함수족을 이긴다")을 결과를 본 뒤에 고를 자유가 남아 있었다. 그 자유를 여기서 닫는다:

> "등록된 learned comparator family({GEARS, CPA, ID-only, L3}) 각각에 대한 simultaneous lower bound 이 0 을 넘었다 —
> 이는 등록된 verdict 조건의 통과이지 architecture attribution 이 아니며(수정안 F), L1↔L2·L1↔L3 의 구조 기여는 exploratory 로만 보고한다. unconditional efficacy 를 주장하지 않는다."

이 문장은 (i)·(ii) 를 대체하지 않고 더한다: 밴드/flip 표기는 여전히 (i)·(ii) 가 정하고, (iv) 는 learned-family 다리에만 적용된다. arm 별 유효 penalty 가
같은 단위가 아니라는 것(결정 #7 §5.1, 수정안 F)이 이 문장의 근거이며, D1-c 잔여(real λ\* 에서의 θ 부호, POD)는 그대로 열려 있다.

**[2026-09-08 정정 — 결과군 완전성 (Codex PR 리뷰 I3)]** (i)~(iii) 의 적용 조건이 **두 sentinel 만** 다뤘다.
그 둘은 zero-width band(`q == 0`)의 `±inf` 만 encoding 하며, 일반적인 `q > 0` 에서 flip 은 **유한**하다:
실측 두 예 — q=0.1, learned θ=0.3 에서 additive θ=0.30 → `GI_LEARNABLE_WIN`, flip **2.5**(등록 사다리 최대
1.25 **밖**); additive θ=0.10 → `NO_DISTINCT_WIN`, flip **0.5** — 는 위 세 문장의 어느 조건에도 배정되지
않았고, 그만큼 결과를 본 뒤 문구를 고를 자유가 남아 있었다. **분기는 이제 코드가 소유하고 이 문서가 인용한다:**
`alive.compose.phase2b.preregistered_headline_branch(band_passes=, flip=, ladder_max=)` 가
`"i"`/`"ii"`/`"iii"` 를 돌려주며, 그 분할은 전역적이고 배타적이다.

- **(i)** `band_passes=True` 이고 (`flip == NEVER_FLIPS` **또는** 유한 flip > `ladder_max`). 등록 사다리
  전 구간에서 margin 이 유지된다. flip 이 유한하면 `λ=<flip>` 외삽점을 **병기**하되, claim 은 등록 사다리
  구간(λ ≤ `ladder_max`)에 한정한다 — 사다리 밖 λ 는 보고값이지 주장이 아니다.
- **(ii)** `band_passes=True` 이고 유한 `1.0 < flip ≤ ladder_max`. 문장의 `λ=<flip>` 은 이 구간의 값이다.
- **(iii)** `band_passes=False` — 등록 밴드 미통과 **전체**. flip 이 `FAILS_AT_REGISTERED_BAND` 이든
  유한 ≤1.0 이든 같은 문장이다.
- `band_passes=True` + 유한 flip ≤ 1.0 은 구성상 도달 불가(밴드 통과 = λ=1 에서 lower bound 가 threshold
  위 → flip 은 1.0 초과 또는 `+inf`)이므로 함수가 `ValueError("inconsistent band verdict and flip")` 를 낸다.
- `ladder_max` 는 등록 config 의 `sensitivity_band_inflation` 최대값(현재 **1.25**)이며 **호출자가 넘긴다** —
  production source 에 사다리를 hardcode 하지 않는다.

네 문장의 본문과 (iv) 는 그대로다. 이 정정은 어느 문장이 언제 적용되는지만 완전하게 만든다.

**[2026-09-09 정정 — 유효한 verdict 가 없는 terminal]** 위 네 문장은 verdict 가 실제로 내려진
결과군에만 적용된다. `sealed_axis` 가 `INVALID` 또는 `FUTILITY_STOPPED` 인 terminal 에는 사전등록
문장을 **싣지 않는다**: `INVALID` 는 무결성 precondition 실패로 신뢰할 수 없다고 선언된 run 이고
(COMPLETE 와 같은 terminal body 를 쓰므로 그대로 두면 그 run 에 headline 이 붙는다), futility 로
멈춘 run 은 negative verdict 가 아니다(`CLAUDE.md#seal`). 두 경우에 남는 것은 문장이 아니라 적용
불가 marker 뿐이다. 분기 함수와 네 문장은 leaf 모듈 `alive.compose.headline` 로 옮겼고
`alive.compose.phase2b` 가 그대로 re-export 하므로 위에서 인용한 경로는 유효하다 — `durable` 이
문장을 재도출해야 하는데 `phase2b` 가 이미 `durable` 을 import 하므로 순환이기 때문이다(실측).
이 정정은 네 문장의 본문도 (i)~(iii) 의 분기 조건도 바꾸지 않고, 문장이 **적용되지 않는** 두 axis
를 명시할 뿐이다. (오너 승인 2026-09-09.)

**[2026-09-09 정정 — 문장 emission 과 적용 범위]** 위 네 문장은 지금까지 **문서 안에만** 있었다. 어느
문장이 실제로 선택되었는지는 artifact 어디에도 남지 않았고, (ii) 의 `λ=<flip>` 치환은 보고 시점의 손에
달려 있었다. 이 정정은 그 자리를 고정한다 — 문장의 본문도 (i)~(iii) 의 분기 조건도 바꾸지 않는다.

- **어디에 실리는가.** 선택된 문장은 terminal body 의 `band_sensitivity.headline` 에 **중첩되어** 실린다.
  Amendment B 의 기존 `band_sensitivity_checksum` 이 그대로 묶으므로 terminal 최상위 roster(설계 spec §2.1)
  는 한 필드도 늘지 않는다. 블록 schema 는 `compose_band_sensitivity_v1` → **`compose_band_sensitivity_v2`**
  로 올린다. 블록은 여전히 `descriptive_only` 이며, 문장은 verdict 를 **다시 말할 뿐** 결정하지 않는다.
- **누가 재검증하는가.** durable finalizer 는 publish 전에 terminal 자신의 `sealed_axis` ·
  `verdict_clauses.additive_clears` · `flip_lambda["additive"]` 와 블록 자신의 `by_lambda` 최대 λ 로 문장을
  **재도출**해 **정확 일치**를 요구한다. checksum 은 블록을 결속할 뿐 블록이 참인지는 말하지 않으므로,
  그 전까지는 자기일관적인 잘못된 문장이 그대로 published 되었다(다섯 경우를 실측했다). 분기와 flip 이
  모순인 입력에는 renderer 가 예외 대신 `inconsistent: true` marker 를 기록하고(정당한 terminal write 를
  중단시키지 않기 위해서다), durable 은 그 marker 를 성공 artifact 로 승인하지 않는다.
- **λ 값의 표기.** (ii) 의 `<flip>` 과 아래 병기 문구의 `<flip>` · `<ladder_max>` 는 `repr(float(...))`
  하나로만 치환한다. 한 값에 한 표기이므로 사람이 읽는 문장과 durable 이 재도출하는 문장이 같은 바이트다.

**(i-note) 유한 flip 외삽 병기 문구 (2026-09-09 등록).** 위 2026-09-08 정정의 (i) bullet 은 유한 flip 일 때
`λ=<flip>` 을 **병기**하라고만 적고 문구를 등록하지 않았다 — 그만큼 문구를 결과를 본 뒤 고를 자유가 남아
있었다. 그 자유를 여기서 닫는다: "외삽 flip 은 λ=<flip> 이며 등록 사다리 밖이다 — claim 은 등록 사다리 구간(λ ≤ <ladder_max>)에 한정하고 사다리 밖 λ 는 보고값이지 주장이 아니다."
이 문구는 (i) 문장에 **더해질 뿐** 대체하지 않으며, 유한 flip 이 없으면 실리지 않는다.
(오너 승인 2026-09-09.)

네 문장 어디에도 "mechanistic" · "causal" · "context transfer" · "unconditional 95%" 를 **긍정 claim 으로** 쓰지 않는다(명시적 비주장 절에서만 등장한다).
calibration in-sample ICC 의 double-unseen 이식과 λ=1.15 를 새 nominal gate 로 쓰는 것은 금지(결정문 §2, 불변식 7).
