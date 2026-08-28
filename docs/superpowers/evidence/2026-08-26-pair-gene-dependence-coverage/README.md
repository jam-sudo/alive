# `stats.pair-gene-dependence` — 재현 판정과 실측 크기

**protocol** COMPOSE-K562-v1 · **일자** 2026-08-26 · **seal** UNOPENED (이 측정은 seal 을
열지 않았고 sealed outcome 을 읽지 않았다) · **config_sha256** 불변 `5fea3b9e…`

외부 감사(`stats.pair-gene-dependence`)는 **논증**만 제시했다: "동일 gene 을 공유하는 pair 들의
error covariance 가 0 이 아니면 pair-i.i.d. bootstrap 의 effective sample size 와 max-deviation
quantile 이 **잘못될 수 있다**." 측정은 없었다. 여기서 등록된 추정량을 그대로 돌려 잰다.

---

## 0. 무엇을 읽었나 (경계)

`adata.obs['perturbation']` **라벨만** 읽었다. `.X` 는 열지 않았다(`backed='r'`). eligibility 와
split 은 spec §2.2 가 outcome-independent 로 못박은 단계이며, 여기서 계산한 것은 pair 의
**구조**뿐이다. outcome store 를 호출하지 않았고 sealed access count 는 0 이다.

## 1. 구조 — 실측이고, 정답 대조를 통과했다

커밋된 pod evidence(`docs/activation-evidence/compose/real_norman_phi_rank_report.json`)와
**7/7 일치**: singles 105 · eligible pairs 131 · z-universe genes 73 · calibration genes 44 ·
roles 41 / 22 / 68. 같은 split 을 재현한 것이 맞다.

| role | n_pairs | distinct genes | mean/max degree | gene 공유 pair 쌍 | **유전자를 하나도 공유하지 않는 pair** | 연결성분 |
|---|---|---|---|---|---|---|
| **sealed_double_unseen (headline)** | 22 | **21** | 2.10 / 5 | 35/231 = 15.2% | **0 개** | **2 개 (19, 3)** |
| sealed_single_unseen | 68 | 58 | 2.34 / 7 | 155/2278 = 6.8% | 1 개 | 4 개 (62, 3, 2, 1) |
| combo_calibration | 41 | 37 | 2.22 / 7 | 92/820 = 11.2% | 2 개 | 5 개 (30, 5, 4, 1, 1) |

headline 22 pair 를 21 개 유전자에서 뽑았다. **독립인 행이 하나도 없다** — pair-i.i.d. 가정은
근사적으로 성립하는 것이 아니라 **구성상 위배**된다. 감사의 전제는 참이다.

## 2. 왜 CI 미용 문제가 아닌가

spec §10.5 의 verdict gate 가 이 lower bound 의 **직접 함수**다: `GI_LEARNABLE_WIN` 은
additive lower bound > 0.05 **그리고** {GEARS, CPA, ID-only, L3} 각각 > 0. bound 가 낙관적이면
verdict 가 낙관적이 된다. spec 어디에도 pair-i.i.d. 가정이나 그 한계는 적혀 있지 않다.

## 3. 측정 설계

등록값 그대로: n=22 · `bootstrap_replicates` **10000** · comparator family 5 개 ·
`family_confidence` **0.95** · `shared_resamples_across_contrasts: true`. 조건당 **1500 trials**.
실제 production 함수 `alive.compose.inference2.simultaneous_theta_bounds` 를 호출한다.

coverage event = 5 개 comparator **전부**의 lower bound 가 참 theta 이하 (family-wise).

생성 모형:

    e[m,i] = mu[m] * exp( sgs*(G_a+G_b)/sqrt2      # (A) 공통 pair 난이도 — 모든 method 공유
                        + sgd*(H^m_a+H^m_b)/sqrt2  # (B) method-differential 유전자 효과
                        + sp*P_i + se*E[m,i] - corr )

`G` 는 유전자마다 하나로 같은 유전자를 쓰는 pair 들이 공유한다. `H^m` 은 **method 마다 독립**이다.

## 4. 결과 (A) 공통 통로 — **영향 없음**

실제 그래프 5 조건 + 합성 사다리(공유 강도 degree 1 → 5.5) 15 조건, 총 **20 조건**:

    coverage 범위 0.9547 ~ 0.9673 — 전부 명목 0.95 이상, 공유 강도와의 추세 없음
    실제 그래프: ICC 0.000 → 0.408 에서 0.9580 / 0.9587 / 0.9600 (변화 없음)
    band halfwidth q 는 0.3082 → 0.4461 로 **함께 커진다**

**이유:** theta 는 비율 `1 - mean(e_L1)/mean(e_C)` 이라 모든 method 에 공통인 배수는 분자·분모에서
대부분 상쇄된다. 남는 것은 주변분산 증가뿐이고 i.i.d. bootstrap 이 그것을 밴드 확대로 흡수한다.

이 통로만 켠 설계는 **하락을 보여줄 수 없다** — 참일 때와 거짓일 때 출력이 같다. 그래서 이 20 조건은
음성 결과이자, 아래 (B) 의 비-공허성 대조군이다.

## 5. 결과 (B) method-differential 통로 — **CONFIRMED**

`sgs=0.60` 고정, `sgd` 를 키운다. 대조군은 **분산은 같고 공유만 없는** 완전매칭이다.

| arm | 구조 | sgd | coverage [95% CI] | q |
|---|---|---|---|---|
| **실제 headline** | 22p/21g, deg 2.10 | 0.00 | 0.9620 [0.9523, 0.9717] | 0.347 |
| **실제 headline** | 〃 | 0.30 | **0.9307 [0.9178, 0.9435]** | 0.446 |
| **실제 headline** | 〃 | 0.60 | **0.9240 [0.9106, 0.9374]** | 0.734 |
| **실제 headline** | 〃 | 0.90 | **0.9373 [0.9251, 0.9496]** | 1.271 |
| 대조군 (공유 0) | 22p/44g, deg 1.00 | 0.00 | 0.9660 [0.9568, 0.9752] | 0.355 |
| 대조군 (공유 0) | 〃 | 0.30 | 0.9700 [0.9614, 0.9786] | 0.452 |
| 대조군 (공유 0) | 〃 | 0.60 | 0.9693 [0.9606, 0.9781] | 0.723 |
| 대조군 (공유 0) | 〃 | 0.90 | 0.9720 [0.9637, 0.9803] | 1.188 |

- 실제 구조에서 family-wise coverage 가 **0.924 ~ 0.937** 로 내려간다. 세 조건 모두 95% CI 가
  명목 0.95 **아래**다. family-wise 오류율이 등록된 5% 대비 **최대 약 1.5 배**(7.6%).
- **같은 분산, 공유만 없는 대조군은 0.966 ~ 0.972 로 전혀 내려가지 않는다** — 하락의 원인은
  분산 증가가 아니라 **유전자 공유**다.
- q 는 여기서도 커지지만(0.347 → 1.271) **충분히 커지지는 않는다.**

## 6. 판정

| | 판정 | 근거 |
|---|---|---|
| 구조적 전제 ("공유가 있다") | **CONFIRMED, 실측** | 22 pairs / 21 genes / 독립 행 **0 개** |
| 감사가 서술한 기제 (error covariance) | **부분 REFUTED** | 공통 pair-난이도 통로는 비율에서 상쇄된다 — 20 조건 무영향 |
| 실제로 무는 기제 | **CONFIRMED (교정)** | **method-differential** 유전자 효과만 d_i 에 남는다 |
| 영향 크기 | **측정됨(모형 하)** | 0.95 → **0.924~0.937**, 대조군은 무하락 |
| 실제 데이터의 그 성분 크기 | **미측정** | Phase 2a dev(`combo_calibration`)에서만 잴 수 있다 |

**감사의 결론은 옳다. 다만 이유가 다르다** — 그리고 그 차이가 다음 행동을 바꾼다. 무엇을 재야
하는지가 "error covariance" 일반이 아니라 **method-differential 성분** 하나로 좁혀졌다.

## 7. 자연스러운 수정안이 이 설계에서는 **불가능**하다

"dependency-aware bootstrap 을 쓰라"는 처방은 headline 에 적용되지 않는다:

    sealed_double_unseen 의 연결성분 = 2 개 (크기 19, 3) — 86.4% 가 한 성분

cluster bootstrap 의 유효 클러스터 수가 **2** 다. gene-level resample 도 21 개 유전자 위에서
replicate 마다 n 이 흔들려 등록된 estimand 를 바꾼다. 즉 **이 split 은 의존성을 흡수하는
재표본 단위를 갖고 있지 않다.** 이것 자체가 owner 가 알아야 할 사실이다.

## 8. 남은 선택지 (owner 결정, 여기서 정하지 않는다)

1. **주장 제한 + 사전등록된 sensitivity** — confirmatory coverage 주장을 pair-i.i.d. 가정 아래로
   명시하고, Phase 2a 에서 잰 성분 크기로 이 표를 채워 함께 보고한다. outcome 접근 전에 등록.
2. **design-effect 밴드 팽창** — `combo_calibration`(41 pairs / 37 genes, 구조 유사)에서 d_i 의
   유전자 급내상관을 dev 단계에 측정해 밴드 배율을 사전등록한다.
3. **현행 유지 + 한계 명시** — 아무것도 바꾸지 않되 §10.5 verdict 문구에 가정을 적는다.

어느 쪽이든 **outcome 접근 전에** 확정해야 한다(불변식 1·17). seal 은 아직 UNOPENED 이므로
지금이 그 시점이다.

## 9. 재현

    uv run python pair_structure.py          # 구조 + 정답 대조 7/7
    uv run python pairdep_probe.py 1500      # (A) 합성 사다리
    uv run python pairdep_real.py            # (A) 실제 그래프
    uv run python pairdep_diff.py            # (B) method-differential + 대조군

원자료: `structure.json` · `coverage_shared_channel*.txt` · `coverage_method_differential.txt`.
