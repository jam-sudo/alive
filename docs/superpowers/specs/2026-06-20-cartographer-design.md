# CARTOGRAPHER — 신뢰·결정 레이어 · FINAL 설계 스펙

> 상태: 설계 확정안 (project owner 검토용 / design doc 저장 예정). CARTOGRAPHER는 base predictor(형제 스펙 Model #1: encoder + 저랭크 operator + OT-CFM + NB decoder) **위에 얹는 TRUST/DECISION 레이어**다. 학습된 base는 1개, CARTOGRAPHER는 **held-out calibration만** 소비(N-ensemble 재학습 불필요).
>
> 이 문서는 4개 컴포넌트(conformal-formulation / recoverability-gate / real-win-defense / experiments-simloop-killgates)를 통합하고, critique panel 3인(category-error / coverage-under-shift / simloop-feasibility, 전원 verdict=fixable·win-survives=true)의 **모든 fatal_flaw를 (a) 설계에 직접 반영하거나 (b) accepted risk + 완화책으로 명시**한 결과다. 가장 무거운 비판 — **"AURC는 score의 단조변환에 불변이고 conformal radius는 단조변환이므로, conformalized-baseline은 raw-distance와 byte-identical(검증: AURC 0.50127966 == 0.50127966)인 phantom이다"** — 을 §1·§3에 정면으로 박았다.

---

## 1. 한 줄 정의 + 진짜 win + 무엇이 table-stakes인가

### 1.1 한 줄 정의
CARTOGRAPHER는 base perturbation predictor의 각 쿼리 $q=(A,X_{\text{ctrl}},C)$ 출력에 대해 **(i) 분포값 conformal 공(in-distribution marginal 보장), (ii) recoverability 기반 PREDICT/ABSTAIN 라우팅**을 부여하는 신뢰·결정 레이어다. ABSTAIN = "예측 말고 실험하라". 1차 산출물은 coverage 숫자가 아니라 **predict-or-experiment 결정**이다.

### 1.2 카테고리 오류 (acid test) — 무엇이 table-stakes이고 무엇이 win이 아닌가
> **Conformal coverage의 marginal validity는 임의의 nonconformity score에 대해 성립한다(exchangeability만 가정).** 따라서 "우리는 90% coverage를 달성했고 baseline은 못 했다"는 **카테고리 오류**다. base predictor의 raw E-distance·ensemble variance·아무 score든 held-out calibration에 split-conformal을 씌우면 정확히 같은 marginal coverage가 나온다.

그러므로 **coverage 달성 자체는 win이 아니라 입장료(table stakes)**다. 모든 비교 대상은 동일 base predictor를 wrap하고, 동일 calibration split에서, 동일 target coverage $1-\alpha$로 conformalize된 상태에서 출발한다(**Fair-Comparison Protocol, FCP**). coverage가 다르면 비교 무효.

**[FIX — category-error critique 1: BASELINE PHANTOM]** 더 날카롭게: **AURC(risk-coverage 곡선 면적)는 gate score의 임의 단조변환에 불변**이고, conformal radius는 calibration-quantile에 의한 단조변환이다. 따라서 "raw-distance"와 "conformalized raw-distance(=conformalized-baseline)"는 **AURC가 기계적으로 동일**하다(critique가 수치로 검증: 0.50127966 == 0.50127966). 즉 "category-error를 직격한다"던 별도 baseline B3는 **B2와 구별 불가능한 phantom**이다.
- **결정:** 헤드라인 win은 **오직 두 실제 상대** — (i) raw-distance/base-radius, (ii) ensemble-variance(MC-dropout/flow-sample 분산) — 에 대해서만 측정한다. "conformalized baseline을 이겼다"를 **별도의 scalp으로 광고 금지**(같은 곡선, 같은 면적이므로). conformalized-baseline은 "coverage parity가 어떤 score든 달성됨"을 보여주는 sanity 표지로만 남긴다.

### 1.3 진짜 win (category error를 피한, 측정가능 우위)
coverage validity가 **건드릴 수 없는** 유일한 비환원적 양은 **같은 coverage·같은 예산에서의 라우팅 품질**이다. 헤드라인:

> **WIN A — Selective Risk–Coverage (AURC).** recoverability gate가 abstain 순서를 매겨 만든 risk-coverage 곡선의 AURC가, FCP 하의 raw-distance·ensemble-variance보다 **perturbation-level bootstrap 95% CI 하한 > 0**으로 낮다. **risk = 채택(=PREDICT)한 쿼리들의 실측 oracle E-distance**(conformal radius 아님 — radius로 재면 self-fulfilling 동어반복), coverage = 1−abstain율.

이것이 category error로 환원 불가능한 이유: 두 score가 같은 marginal coverage를 줘도 AURC는 자유롭게 다르다. AURC 우위는 validity가 못 건드리는 측정량이다.

**그러나 — 진짜 novelty 서사의 정직한 한계 (category-error critique 2,3):**
- **R4(local calibration residual = dual-manifold kNN 이웃의 실측 base-error 중앙값)는 held-out base error 위에 직접 적합한 kNN 회귀자**다. "geometry를 식별성으로 읽는다"가 아니라 **목표(error)를 직접 추정**하는 것이다. R2/R4 ablation에서 R4가 win을 캐리하면(가장 가능성 높은 결과: a posteriori 잔차가 a priori geometry를 이긴다), **"operator-aware dual-manifold recoverability" novelty는 증발하고 "더 나은 error-ranking score"로 정직하게 relabel**한다. win은 real-but-mundane(더 나은 오차 랭킹)이며 category-distinct가 아니다.
- **유일한 진짜 category-distinct 메커니즘(M1: amortized hypernetwork는 support 밖에서 low-variance·high-bias로 자신있게 틀린다 → ensemble-variance가 epistemic gap을 구조적으로 underestimate; R2 operator-projected identifiability가 이를 포착)은 base 모델이 곱셈 operator $U_gV_g^\top$를 비자명하게 쓴다는 데 contingent**하다. **그러나 형제 스펙(§2.4)이 인정하듯 base는 bias-only(CPA+CFM)로 self-reduce할 가능성이 높고**, 그러면 $V_g$가 underdetermined → R2는 노이즈 → S축이 generic OOD(R3)로 붕괴 → 헤드라인이 ensemble-variance와 동률일 공산이 크다. 이 contingency를 §3·§5·§7에 명시한다.

### 1.4 table-stakes로 강등되는 것
- **coverage 달성**(KILL-GATE #1) — 자격일 뿐 win 아님.
- **"conformalized baseline을 이김"** — phantom이므로 win 주장에서 삭제.
- **K562→RPE1 cross-context의 "finite-sample distribution-free coverage 보장"** — 아래 §3.4·§7에서 보듯 **존재하지 않으므로 모든 framing에서 삭제**.

---

## 2. 시스템 구조 (math 포함)

### 2.0 파이프라인
```
base predictor(frozen, 1개) ── 쿼리 q=(A, X_ctrl, C) ──▶ 예측 집단 P̂_q = {x̂_1..x̂_m}
                                                            │
        held-out calibration scores {s_i} ─────────────────┤
                                                            ▼
   (1) 분포값 conformal:  공 B(P̂_q, r̂_α)          [table-stakes, in-dist marginal]
   (2) recoverability gate:  s(q) ──▶ PREDICT / ABSTAIN   [WIN A engine]
                                                            ▼
                              PREDICT → 공 + 보장 보고
                              ABSTAIN → "run experiment" (triage)
```
**전부 post-hoc**: base forward 1회 + calibration score 배열 연산. 재학습 0 → M5 24GB MPS에서 전량 실행 가능.

### 2.1 Base predictor wrap + nonconformity score
한 데이터 포인트 = cell이 아니라 **쿼리** $q$. nonconformity score = **집단-대-집단 분포거리**(per-gene scalar 아님):
$$s(q)=D\big(\hat P_q,\,X^\star_{\text{post}}(q)\big),\quad D\in\{\text{E-distance(주)},\ \text{sliced-Wasserstein(부)},\ \text{MMD(감사)}\}.$$
**주 score = E-distance**(scPerturb 표준, 기존 eval primitive 존재). SW는 covariance/다봉성 민감도 때문에 보조로 둔다 — 단 **SW를 주 score로 올리지 않는 이유는 critique의 self-falsification 함정**(§5·§7)이다.

차원은 raw gene이 아니라 **train-only로 동결한 임베딩(PCA/HVG)**에서 측정(RPE1 outcome 절대 미사용, invariant #3). 임베딩은 사실상 score의 일부 → 동결하지 않으면 누출/불안정.

추정 잡음 보정: $\hat P_q$·$X^\star$ 모두 유한표본이라 sampling bias가 있다. **self-distance floor**(같은 집단을 절반으로 쪼갠 거리; self-prediction 상한과 연결)를 noise ceiling으로 빼거나 동일 크기 subsample U-statistic 보정.

### 2.2 Distribution-valued split-conformal (table-stakes 층)
base는 **train fold에서만** 학습(RPE1 perturbed outcome 봉인). calibration fold $\mathcal{I}_{\text{cal}}$의 각 쿼리에서 $s_i=D(\hat P_{q_i}, X^\star_{q_i})$. 보정 분위수
$$\hat r_\alpha=\mathrm{Quantile}\Big(\{s_i\};\ \tfrac{\lceil(n_c+1)(1-\alpha)\rceil}{n_c}\Big),\qquad B(\hat P_q,\hat r_\alpha)\ \text{출력}.$$
보장: $\Pr[D(\hat P_q, X^\star_q)\le\hat r_\alpha]\ge 1-\alpha$.

**exchangeability 단위 = (perturbation×cell-line) 쿼리. cell 아님.** 한 쿼리 = score 1개. cell barcode는 split 불침범(split contract). calibration 쿼리는 RPE1 outcome 강도로 선택 금지(invariant #4).

**커버리지 타입 3층 등급화 (정직성 축):**
- **L1 split = MARGINAL.** in-distribution(K562 held-out pert)에서만 정확. 기본 출력, "marginal"이라 명시 라벨.
- **L2 Mondrian/group-conditional = per-cell-line/per-stratum.** 군별 $\hat r_\alpha^{(g)}$ → 군 내 조건부 보장(더 강한 주장). **단 §3.4·§6에서 보듯 n이 작아 사실상 무용**.
- **L3 weighted = covariate-shift용 — 본 스펙에서 보장에서 강등(§3.4).**

### 2.3 Recoverability gate (WIN A engine)
두 매니폴드를 **base가 실제 쓰는 좌표계**에서 정의(별도 임베딩 학습 금지 — 누출·정렬어긋남 차단):
- **P-manifold** = hypernetwork 입력 frozen feature $\phi_g$(ESM/GO/network; **cell-line 의존 baseline-expr은 분리** — 누출 C-5).
- **S-manifold** = encoder 잠재 $z_{\text{ctrl}}$.

non-recoverability 신호(높을수록 abstain):
$$\textbf{R1 (P-거리):}\ r_P^{\text{knn}}(q)=\tfrac1k\!\sum_{j\in\text{kNN}(\phi_g)}\!\|\phi_g-\phi_{g_j}\|_{\Sigma^{-1}}\big/\rho_k(\phi_{g_j})\quad(\text{density-relative extrapolation})$$
$$\textbf{R2 (operator-aware, contingent):}\ r_S^{\text{op}}(q)=\sum_{c}\frac{\|V_g^{(c)}\|^2}{\widehat{\mathrm{Var}}_{z\sim P_0^q}[V_g^{(c)\top}z]+\epsilon}\quad(\text{control이 operator read 좌표에 신호 없으면↑})$$
$$\textbf{R3 (control OOD):}\ r_S^{\text{ood}}(q)=-\log\hat p_{\mathcal Z_{tr}}(P_0^q)\qquad\textbf{R4 (local residual):}\ r^{\text{loc}}(q)=\operatorname{median}_{g'\in\mathcal N_{PS}(q)}e_{g'}$$
합성: 기본 = **transparent OR-게이트 + 단조결합** $s(q)=\max(\text{정규화 P축},\ \text{S축})$ 를 base로 $r^{\text{loc}}$로 보정. learned는 isotonic/monotone GBM 최소로만(calibration의 base error $e_{g'}$만 입력 — 그건 K562 held-out에서 계산, RPE1 outcome 미접촉).

**[FIX — category-error 2: R4 relabel]** R4·및 MVP의 "kNN E-distance to calibration manifold"는 **error 위에 적합한 kNN 회귀자**임을 명시한다. R4가 win driver면 "더 나은 error-regressor"로 보고하고 identifiability novelty를 **철회**한다(§5 ablation 사전등록).

### 2.4 라우팅 규칙
- $s(q)$ 작고 covariate support 충분 → **PREDICT** + 공 보장.
- $s(q)$ 크거나(공이 responder/non-responder를 둘 다 포함해 결정 무의미) support 부족 → **ABSTAIN → run experiment**.

**[FIX — coverage-under-shift 2: selection-laundering 명시]** support 비중첩 영역을 ABSTAIN으로 보내면 **coverage가 깨질 cell들이 측정에서 제거**된다(selection-induced coverage inflation). 따라서 KILL-GATE #1은 coverage를 **triple로** 보고한다(§5): full-set(would-be-abstain을 uncovered로) / conditional-on-PREDICT / abstain-rate.

---

## 3. 진짜 측정가능 우위 3종 + 강한 baseline + 헤드라인 win

**FCP 공통:** 모든 비교 대상은 동일 base wrap + 동일 calibration split + 동일 marginal coverage. 차이는 score/gate에서만. coverage parity 깨지면 비교 무효.

### WIN A — Selective Risk–Coverage (★ 헤드라인, ROBUST)
- **Falsifiable claim:** gate $g$로 정렬한 risk-coverage 곡선의 **AURC**(risk=실측 oracle E-distance)가 baseline AURC보다 perturbation-level bootstrap 95% CI 하한 > 0으로 낮다.
- **이겨야 할 강한 baseline (phantom 제거 후 실제 2종):**
  1. **raw-distance / base-radius** (= conformalized-baseline과 byte-identical AURC, 둘은 한 상대).
  2. **ensemble-variance** (MC-dropout/flow-sample 분산; **cost-adjusted** — single-model이 강점이므로 K배 비용 치르고도 우리를 못 이겨야 진짜 win, 동률이어도 비용으로 win).
  - 정규화용: random abstention(floor) / oracle abstention(ceiling).
- **선행 floor 진단 [FIX — category-error 6]:** 곡선 전에 $\mathrm{corr}(s_{\text{gate}}, e_q) > \mathrm{corr}(s_{\text{base-radius}}, e_q)$ 를 perturbation-level bootstrap CI 하한 > 0으로 먼저 보인다. 단순 base radius가 라우팅을 대부분 설명하면 gate는 메커니즘 무관하게 무의미.
- **AUGRC 동반 보고** [FIX — simloop critique]: AURC가 작동점 위험을 평균으로 희석한다는 알려진 결함 대응. 단일 작동점 cherry-pick 금지.
- **헤드라인 측정 위치 [FIX — simloop critique]:** powered 헤드라인은 **in-distribution K562 held-out perturbation 풀**(쿼리 수 충분)에서 측정. **여기서 WIN A가 죽으면(gate == raw-distance) registered negative**이고 shift 질문은 moot.

### WIN B — Distribution-valued가 heterogeneity를 포착 (MODERATE→FRAGILE, 보조)
**[FIX — category-error 3 + coverage-under-shift 5: coverage 비교가 아니라 decision-region informativeness로 재정의]** scalar-interval(2603.02204류)은 per-gene **marginal** coverage를, distribution-ball은 **joint-distance** coverage를 통제한다 — 서로 다른 event라 "ball이 conditional coverage가 더 낫다"는 apples-to-oranges이고 score-choice 우위를 coverage 라벨로 밀반입한다. 따라서:
- **재정의:** **같은 event(held-out 집단의 joint coverage)를 matched operational coverage로 맞춘 뒤, decision-region informativeness(ball volume / sliced-W radius / 유효 결정폭) 비교.** "conditional coverage" 주장 폐기.
- **이겨야 할 baseline:** per-gene conformalized scalar interval(2603.02204 재현), pseudobulk-mean+conformalized scalar(invariant #6 직격), distribution-distance-but-unconditional(내부 ablation).
- **치명적 전제 [invariant #9]:** responder/non-responder stratum은 **control/base만으로, RPE1 outcome 없이 사전등록**되어야 하고 **null/shuffle 대조**(라벨 섞으면 우위 소멸)를 통과해야 사용 가능. Replogle은 ~41% 유전자만 측정가능 신호 + E-test 검정력 200–500 cells/pert → bimodality가 cell-cycle/guide-efficacy/sampling과 교란.
- **운명 결정 [FIX — coverage-under-shift 5: 조기·저비용 audit]:** 합성 bimodal + Norman 이질 쿼리에서 **SW/E-dist/MMD score-agreement check를 투자 전에 먼저** 실행. **이질성 우위가 SW에서만 나타나면 score artifact로 registered negative.** outcome-독립 stratum 정의가 신호 floor 위에서 존재하지 않으면 **WIN B를 synthetic-only로 강등하거나 완전 폐기.**

### WIN C — Simulated-loop sample-efficiency (FRAGILE→가장 약함, 마지막)
- **Claim:** gate가 abstain한(=식별불가) 쿼리를 먼저 실험으로 reveal하면 고정 예산에서 누적 hit-rate(area-under-hit-curve)가 baseline보다 빠르게 오른다.
- **baseline:** random / uncertainty(raw 분산) / ensemble-variance(BALD류) / largest-predicted-effect(greedy).
- **[FIX — 3 critiques 공통: tautology 차단]** (a) loop에 **실제 calibration/base 갱신 단계** 필수(없으면 "abstain=고불확실=고오차" 동어반복), (b) "hit"을 **oracle effect-size로만** 정의(E-distance > 사전등록 null-specificity threshold), **절대 "base가 틀림"으로 정의 금지**(U2 tautology). 갱신 없는 offline replay는 **exploratory only**로만 보고.

### 헤드라인 win (한 줄)
> **CARTOGRAPHER의 recoverability gate는, FCP 하의 raw-distance·ensemble-variance(cost-adjusted) 대비 selective risk-coverage AURC(risk=실측 oracle E-distance)를 perturbation-level bootstrap 95% CI 하한 > 0으로 낮춘다 — in-distribution K562에서 powered로 측정.** category error로 환원 불가능하고, single-base-model로 측정 가능하며, 1차 산출물(predict-or-experiment)과 직결되는 유일한 robust win. cross-context RPE1는 directional·underpowered로만 보고. WIN B/C는 supporting, 무너지면 registered negative.

---

## 4. 실험계획 (공개데이터 only, wet-lab 0) + 시뮬레이션 closed-loop + 데이터셋/split

### 4.1 데이터셋 × 일반화 그리드
| 데이터셋 | 역할 | CARTOGRAPHER 쓰임 | 그리드 |
|---|---|---|---|
| Replogle **K562**(day6, essential) | base 학습 + calibration pool | **powered 헤드라인(WIN A) 측정처** | A(seen), B(held-out gene) |
| Replogle **RPE1**(day7, 공유 essential) | sealed external test | cross-context, **underpowered·directional만** | C, D |
| **Norman**(K562 combos) | OOD stress | gate가 abstain해야 정답 → routing falsifier | combinatorial |
| **Tahoe**(drugs) | 극단 OOD | 약물 modality=거의 전량 abstain이 정답 | modality-OOD |

Norman/Tahoe는 base를 "이기는" 데이터가 아니라 **gate가 모름을 abstain하는지** 측정하는 negative-control. circular하면 OOD에서도 high-confidence를 줄 것 → OOD가 순환성 falsifier.

### 4.2 leakage 계약 (split contract 상속)
calibration = base 미학습 held-out pert의 집단거리 score만. RPE1 outcome 미접촉(invariant #3). barcode/replicate/channel은 calibration↔test 분리. **baseline-expr feature는 P-거리에서 제외(C-5).** threshold/isotonic fit이 RPE1 outcome 보면 무효 — provenance 점검.

### 4.3 시뮬레이션 closed-loop + 순환성 해소법
"oracle" = sealed RPE1(+Norman+Tahoe)를 한 번에 하나씩 공개하는 함수(wet-lab 없음). 예산 $B$ round: acquisition이 $q_t$ 선택 → oracle이 $X^\star(q_t)$ 공개 → calibration/base 갱신 → 누적 hit 기록.

**순환성 4겹 방어 + 추가 fix:**
1. **oracle 독립성:** hit/miss ground truth는 base 출력이 아니라 **sealed 실측** $X^\star$.
2. **score-agnostic 동축 baseline:** 모든 정책이 같은 base 사용 → "base가 잘하는 영역" 이점은 공통 상쇄 → gate가 이기면 차이는 routing 품질에서만 옴.
3. **OOD negative-control(Norman/Tahoe):** circular면 OOD에서 abstain 못 함 → 노출.
4. **counterfactual masking(KILL-GATE #3):** calibration에서 특정 pert군 마스킹 → recoverability 판정이 인과적으로 바뀌어야 함.
5. **[FIX — simloop critique: closed-loop tautology 제거]** per-round 재캘리브레이션은 exchangeability를 깬다. → batch(per-round 아님) 재캘리브레이션 + held-out exchangeable block, 또는 명시적 online/adaptive-conformal 채택. hit은 oracle effect-size로만 정의.
6. **잔여 순환성 = accepted limitation:** base와 gate가 feature space 공유. base-독립 통계량(calibration-manifold kNN density)으로 최소화하되 완전 분리 불가 → ablation으로 누출 bound 정량화(gate-only-geometry vs gate-with-R2).

---

## 5. kill-gates (3종, go/no-go) — 실행순서 #1 → #3 → #2

**[FIX — simloop critique: #3를 PRIMARY go/no-go로 승격]** #2는 cross-context n에서 underpowered, #1은 shift로 soft. **#3만이 잘 powered되고(마스킹 설계·seed 반복 가능) "recoverability gate"가 이름값을 하는지 가르는 sharp falsifier** → 프로젝트 go/no-go를 #3에 건다.

### KILL-GATE #1 — Coverage validity (table-stakes, win 아님)
- **가설:** 분포값 radius가 명목 $1-\alpha$ 달성.
- **[FIX — coverage-under-shift 2: selection-laundering 차단] triple 보고 필수:** (i) full test set coverage(would-be-abstain을 worst-case/uncovered 할당), (ii) coverage-conditional-on-PREDICT, (iii) abstain rate. conditional만 통과 + 높은 abstain = gate가 자기 실패를 검열 → 그렇게 보고. 추가 체크: abstain threshold를 풀수록 coverage가 단조 degrade하는가? 아주 높은 abstain에서만 성립하면 보장은 vacuous.
- **실패 시:** conformal/exchangeability 붕괴 → 디버그. 통과해도 win 아님.

### KILL-GATE #3 — Recoverability의 인과 falsification (★ PRIMARY go/no-go)
- **가설:** gate 판정은 calibration geometry의 인과적 함수. 특정 pathway/pert cluster를 마스킹하면 그 영역 abstain율이 유의 상승. placebo(랜덤) 마스킹에선 $\Delta\approx0$.
- **임계:** $\Delta_{\text{target}}-\Delta_{\text{placebo}}$의 95% CI 하한 > 0.
- **실패 시:** gate는 식별성 아닌 base-confidence proxy → "recoverability gate" 명칭 철회, "conformalized-UQ"로 재명명(정직 보고). **+ R2/R4 ablation 동반 사전등록:** R4(local residual)가 win 캐리하면 "더 나은 error-ranking score"로 relabel, identifiability novelty 철회. R2가 category-distinct로 인정되려면 **R4를 ablate한 상태에서 R2가 ensemble-variance를 CI>0로 이겨야** 함.

### KILL-GATE #2 — Selective risk-coverage 우위 (헤드라인 win의 1차 측정)
- **가설:** $\mathrm{AURC}_{\text{gate}} < \mathrm{AURC}_{\text{best-baseline}}$, 차이 perturbation-level bootstrap 95% CI 하한 > 0. **risk = 실측 oracle E-distance**(radius 아님). AUGRC 동반.
- **baseline:** raw-distance(=conformalized-baseline, 한 상대) + ensemble-variance(cost-adjusted). conformalized-baseline을 별도 scalp으로 광고 금지.
- **[FIX — simloop critique: 위치·검정력]** powered 측정은 **in-distribution K562**. **Cell C(K562→RPE1)는 $n_{\text{test}}\sim40\text{–}100$이라 최소검출 Cohen-d $\sim0.31\text{–}0.44$ → modest edge는 CI 안에 묻힘 → descriptive/directional로만 보고.**
- **실패 시(in-dist에서):** "calibrated이나 routing은 baseline 동급" = category error 현실화 → **registered negative result**("conformal coverage 달성하나 selective utility는 baseline 못 이김"). CARTOGRAPHER 핵심 주장 사망.

**무결성 가드(모든 곡선 공통):** coverage parity check(empirical coverage가 $1-\alpha$ bootstrap CI 안), self-reference 차단(risk=실측), null/shuffle 대조(섞으면 우위 소멸), cross-context 유지 검사(K562→RPE1 부호/유의 — 단 underpowered 인정), self-prediction 상한·random+transform sanity 동반.

---

## 6. MVP 범위 + M5/A100 feasibility

### 6.1 MVP — 헤드라인 win만 테스트하는 최소판
- **목표:** "in-distribution K562에서 selective risk-coverage 우위(KILL-GATE #2)"를 가장 싸게 falsify. 단 **실행순서는 #1 → #3 → #2.**
- **데이터:** K562 mini(calibration pool) + RPE1 공유 essential mini(sealed, directional only) + Norman/Tahoe 소량(abstain sanity).
- **base:** 가장 가벼운 검증된 것(CFM-GP 또는 형제 Model #1 MVP, operator off·$b_g$만). 새 base 학습 금지, 단일 base + held-out calibration.
- **gate:** calibration score 분포의 local density / kNN E-distance to calibration manifold + conformal radius. **이 MVP gate는 본질적으로 error 위 kNN 회귀**임을 명시(category-error 2) — 따라서 MVP에서 win이 나와도 "geometry/identifiability" 주장 금지, "better error-ranking"으로만 보고.
- **simloop:** offline 시뮬레이션(전체 sealed 미리 보유, acquisition 순서만 재생) — **단 base 갱신 없으므로 WIN C는 exploratory only.**
- **합격:** #1 triple 통과 + #3 target>placebo(CI>0) + #2 in-dist AURC CI>0 + corr-floor 진단 통과. 하나라도 실패 → registered negative 후 scope 재조정.

### 6.2 n_cal 사전 사이징 (build 전 필수) [FIX — simloop critique: 지배적 feasibility 사실]
**[S5] "200–500 cells/pert"는 한 score 계산용 cells-per-query이지 calibration set 크기가 아니다.** 실제 $n_{\text{cal}}$ = 쿼리(=score) 수다. ~41% measurable-null 필터 + cells/pert QC 후 **공유 essential K562↔RPE1 pert는 총 ~82(200 cells)–~820(2000 cells) scores**, 이걸 train/cal/test로 쪼갠다.
- **결정:** 실제 manifest에서 **measurable 공유-essential pert 수 + in-dist held-out K562 pert 수를 build 전에 계산·사전등록**하고, 그 n에서 bootstrap-detectable AURC effect size를 보고한 뒤 실행.
- **L2 Mondrian/L3 weighted는 이 n에서 산술적으로 거의 사망:** ~205 scores를 cell-line×effect-size×pathway로 쪼개면 군당 ~10–20 → 90% radius는 $n\ge9$여야 존재하고 $n\sim10\text{–}20$에서 분산 폭증 → radius 무용. **Mondrian/weighted는 사전등록 최소 군크기(≥30 scores/group) 미충족 시 비활성, L1 marginal + abstain-routing만 보고.** cross-context 쿼리 중 abstain되는 비율을 명시(=새 context use case가 얼마나 살아남는지).

### 6.3 M5 Pro(24GB) / A100 feasibility
- conformal·gate·simloop 전부 post-hoc: base forward 1회 + calibration 배열 연산 → **재학습 없음** → 24GB MPS에서 도는 결정적 이유.
- **mini(M5):** sparse AnnData chunked, frozen forward. E-distance/sliced-W는 calibration 집단(수백 cell)에 $\mathcal O(n^2d)$ 또는 sliced $\mathcal O(nL\log n)$. geomloss/POT는 단일 코드경로 고정 + **device-parity 수치 테스트**(cpu/mps/cuda 일치) 후 사용 — 안 그러면 mini win이 full에서 사라짐.
- **full(A100):** 전체 Replogle+Norman+Tahoe + ensemble-variance baseline(seed 5–10 forward, 재학습 아닌 inference) + 전체 simloop. bootstrap(perturbation×seed) embarrassingly parallel.
- **same code, config-only**(device/n/L/α). mini-only 분기 금지.

---

## 7. 정직한 risk + reframe + 유효 음성결과

### 7.1 baseline phantom (category-error 1) — 처리
conformalize는 AURC 랭킹을 안 바꾼다(검증 0.50127966==). → 실제 상대는 raw-distance + ensemble-variance 2종. "conformalized baseline을 이김"을 별도 win으로 광고 금지. **[설계 반영, 해결]**

### 7.2 R4 = error-regression (category-error 2) — accepted relabel
R4·MVP gate는 error 위 kNN 회귀. R4가 win 캐리하면 "더 나은 UQ score"로 relabel, identifiability novelty 철회. R2가 R4-ablate 후 ensemble-variance를 CI>0로 이겨야 category-distinct. **[사전등록 ablation, accepted risk]**

### 7.3 R2가 base self-reduce에 contingent (category-error 3) — gated
형제 Model #1이 bias-only로 self-reduce하면(자체 문헌이 예측) R2는 노이즈, S축이 R3로 붕괴, 헤드라인이 ensemble-variance와 동률. → **R2/operator 스토리를 base의 operator-vs-bias-only kill-gate 뒤에 gate.** base가 self-reduce하면 **사전등록된 negative**: "S축 differentiator dead, gate는 generic OOD로 후퇴, 헤드라인은 ensemble-variance와 tie 가능성." **[accepted risk + 명시]**

### 7.4 coverage-under-shift — L3 정직 강등 (가장 중요한 reframe)
**[FIX — coverage-under-shift 1: NOT-A-COVARIATE-SHIFT]** K562→RPE1은 cell-line+experiment+batch+endpoint(day6 vs day7) 동시 변동(CLAUDE.md line 47)이고, **invariant인 $P(\text{post-pop}\mid\text{pert,control,cell-line})$의 조건부가 cell-line에 따라 바뀌는 것이 곧 과학적 질문**이다. 이는 covariate shift가 아니라 **concept/conditional shift**다. Weighted conformal(Tibshirani 2019)은 $P(Y|X)$ 불변 하의 $P(X)$ 변화에만 finite-sample 보장을 준다. → **여기서는 가중치를 완벽히 알아도 어떤 차원의 distribution-free 보장도 없다.** L3 self-grade "weight 알면 정확"은 이 벤치마크에서 **거짓**.
- **reframe:** L3 출력을 **"calibrated applicability-domain score"로 재명명. coverage 보장 아님. 이 정직한 reframe은 footnote가 아니라 헤드라인에 둔다.**
- support 비중첩 영역은 $w$ 미정의/폭발 → gate ABSTAIN으로 라우팅(coverage 보장 강행 금지) → 단 이것이 selection bias이므로 §5 triple 보고로 노출.

### 7.5 coverage-under-shift — calibration 검정력 부족
$n_{\text{cal}}$이 low-hundreds, weighted-ESS $=(\sum w)^2/\sum w^2$가 <50 가능 → $\alpha=0.1$ 분위수가 넓고 불안정, KILL-GATE #1의 유한표본 slack $\epsilon$이 주장을 통째로 삼킬 수 있음. → **§6.2 사전 사이징. ESS가 안정 분위수를 못 받치면(radius CI 폭 > self-distance floor) 분포값 conformal 층을 단일 marginal radius로 축소하거나 폐기 — 불안정 radius를 보장으로 포장 금지.** **[accepted risk + 사전 게이트]**

### 7.6 WIN B self-falsification (coverage-under-shift 4) — 조기 audit
SW는 covariance 민감도 때문에 선택되었으므로 WIN B 우위가 SW에서만 나타날 prior가 높고, 그러면 자체 규칙상 score artifact = self-falsification. → **§3 WIN B audit를 투자 전 조기·저비용 실행, SW-only면 negative.** outcome-독립 stratum 정의 부재면 WIN B를 synthetic-only로 강등/폐기. **[설계 반영]**

### 7.7 WIN C tautology (3 critiques 공통)
abstain==high-error는 closed-loop 갱신 없으면 동어반복. → base/calibration 실제 갱신 + oracle effect-size hit 정의. 갱신 전엔 exploratory. **[설계 반영, C는 마지막·가장 약함]**

### 7.8 그때의 reframe (win 무너질 때)
- WIN A가 in-dist에서 죽으면 → **registered negative: "calibrated but not better at routing."** CARTOGRAPHER 핵심 주장 사망, 정직 공개.
- WIN A가 in-dist 생존·cross-context 죽으면 → **"gate는 in-distribution K562에서 routing 개선(powered); cross-context RPE1는 directional, n 부족."** genuine win(라우팅 품질, coverage 비환원) 유지, cross-context trust layer는 overclaim 안 함.
- R2 dead → **"gate = conformalized-UQ"로 재명명, identifiability 서사 폐기, 헤드라인은 better-error-ranking으로만.**
- L3 → **"applicability-domain heuristic"으로만 판매. 보장 아님. decision layer를 팔고 guarantee를 팔지 않는다.**

### 7.9 유효 음성결과 (registered negatives — overclaim 금지)
1. **"conformal coverage는 달성하나 selective utility는 baseline 못 이김"**(category error 현실화).
2. **"gate = base-confidence proxy, not identifiability"**(#3 실패).
3. **"distribution-valued heterogeneity 우위는 SW score artifact"**(WIN B audit 실패).
4. **"K562→RPE1는 covariate shift 아닌 concept shift → distribution-free coverage 보장 불가, applicability-domain만"**.
5. **"R4(error-regression)가 win 캐리 → category-distinct novelty 없음, better UQ score일 뿐"**.

---

## 8. 미해결 질문 (owner 결정 필요)

1. **[가장 중요] 헤드라인 측정 위치 확정.** simloop critique의 권고대로 powered 헤드라인을 **in-distribution K562**로 옮기고 cross-context RPE1를 directional로 강등하는가? 이는 "새 context 신뢰층"이라는 원래 selling point를 약화시킨다. owner가 (a) in-dist powered + cross-context directional(권장, 정직), 또는 (b) cross-context를 헤드라인 유지(높은 underpowered 실패확률 수용) 중 결정.

2. **risk metric 최종 고정.** WIN A의 risk를 E-distance(주) vs sliced-Wasserstein(부) — 둘이 AURC 순위를 다르게 매기면 어느 것을 primary로 preregister하고, 충돌 시 사전 규칙은? (E-dist는 gene-gene 의존성 미포착[S11], SW는 임베딩/projection 의존·self-falsification 위험.)

3. **R2/operator 스토리의 운명을 base kill-gate에 거는가.** 형제 Model #1의 operator-vs-bias-only kill-gate가 통과해야 R2가 의미. 통과 못 하면(자체 문헌이 예측) S축을 R3-only로 운영해도 B1/B2를 이기는지 — 그 경우 헤드라인이 ensemble-variance와 tie면 프로젝트 핵심 win이 약해진다. 사전 입장 결정 필요.

4. **selective risk target $\alpha^*$의 정규화.** E-distance 절대값은 effect-size 의존(약효과 pert는 작은 E-dist가 정상) → effect-size 정규화 relative risk를 써야 abstain이 "effect 큰데 못 맞춤"을 타게팅. 정규화 정의 미확정.

5. **분포값 conformal 층 유지 vs 단일 marginal radius로 축소.** §6.2/§7.5의 ESS 사이징 결과에 따라 — distribution-valued radius가 불안정하면 cut. build 전 manifest 사이징 후 결정.

6. **WIN B의 outcome-독립 responder stratum 정의가 존재하는가.** control/base만으로 noise floor 위에서 real bimodality를 잡는 데이터-비의존 기준(control 대비 effect-size 분위 / GMM 성분 수)이 invariant #9·#4를 안 깨고 가능한가? 없으면 WIN B는 synthetic-only로 강등.

7. **simloop 갱신 정책.** ABSTAIN→실험으로 얻은 데이터를 calibration만 갱신(저비용·exchangeability 주의) vs base도 업데이트(루프 정합·비용↑). 솔로+A100 1장 제약 하 갱신 주기와 online conformal 채택 여부.

8. **gate 합성 g_θ.** transparent OR-게이트 vs 작은 learned monotone(isotonic/GBM) — learned는 AURC↑이나 small calibration에서 누출·과적합. bootstrap CI 하 win을 더 안정적으로 주는 쪽을 mini-data로 결정(단 RPE1 outcome 미접촉 절차 명시).

9. **abstain ≠ 고정보이득.** recoverability-gate를 acquisition으로 직결하는 게 최적인가, 아니면 별도 정보이득 항과 결합해야 하는가(이미 충분히 본 영역=식별가능=PREDICT지만 정보이득 낮음).

---

### 부록: 한 줄 요약 (owner용)
**CARTOGRAPHER는 단일 base predictor 위에 분포값 conformal 공(table-stakes, in-dist marginal)과 recoverability gate(PREDICT/ABSTAIN)를 post-hoc로 얹는 신뢰·결정 레이어다. coverage는 어떤 score든 달성하므로 win이 아니라 입장료이고, conformalized-baseline은 raw-distance와 AURC가 byte-identical한 phantom이다. 유일한 비환원적 헤드라인 win = in-distribution K562에서 selective risk-coverage AURC(risk=실측 oracle E-distance)가 raw-distance·ensemble-variance(cost-adjusted)를 perturbation-level bootstrap CI 하한>0으로 이기는 라우팅 품질이다. K562→RPE1는 covariate shift가 아니라 concept shift이므로 weighted conformal은 가중치를 알아도 보장이 없다 — L3는 coverage 보장이 아닌 applicability-domain heuristic으로 강등하고, cross-context는 underpowered directional로만 보고한다. go/no-go는 비싸고 underpowered한 AURC 비교(#2)가 아니라, 잘 powered되고 gate가 이름값을 하는지 가르는 causal-masking falsifier(#3)에 건다. R4(local residual)·MVP gate는 error 위 kNN 회귀이므로 win이 나도 identifiability가 아닌 better-error-ranking으로 정직 relabel하고, R2/operator 스토리는 base의 operator-vs-bias-only kill-gate에 contingent다. 무너지는 모든 축은 registered negative로 공개한다 — wet-lab 0, 공개데이터 only.**

---

## 9. Active Cartography 결정 (능동 확장 검증 결과, 2026-06-20)

**판정: keep-passive.** 능동학습 acquisition으로 "distribution-valued recoverability"를 쓰는 Active Cartography는 검증 결과 **EPIG(arXiv 2304.08151) + GO-CBED(2507.07359)의 재매개변수화로 환원**되고(점수 4–5 < passive 6), R4 error-regressor가 win을 캐리하면 BALD/uncertainty-sampling 동어반복으로 더 얇아진다. in-context(PFN) 루프 시너지는 실재하나 PFNs4BO/Tab-AICL 선행 → 비용 절감일 뿐 통계적 novelty 아님. wet-lab 없는 시뮬 루프는 일반화 순환을 **원리적으로 해소 불가** → 최대 정직 주장 = "fixed public-oracle 하 sample-efficiency benchmark", discovery-acceleration 아님.

**채택 형태 = 조건부 hybrid (adopt 아님).** passive CARTOGRAPHER를 본체로 유지하고, 능동 layer는 **단일 사전등록 falsification 실험(P5 gate)으로만** 추가한다:
> P5: distribution-valued recoverability acquisition이 **EPIG와 GO-CBED-lite를 둘 다**, 동일 frozen base/oracle/budget, **R4 ablate(R2-only)**, effect-size-stratified hit-curve(hit=oracle E-dist>τ, "base가 틀림" 정의 금지), perturbation-level bootstrap 95% CI 하한>0으로 이겨야 함. + corr(recoverability,hit) > corr(base-radius,hit), CI>0.
> 하나라도 fail → **registered negative**("reparametrization, no distinct gain") — 이것이 ALIVE가 줄 수 있는 정직한 가치.

**비협상 전제:** online-conformal(ACI) 명시 채택, oracle-effect-size hit 정의(절대 base-error 아님). 가장 가능성 높은 결과 = 동률 = registered negative.

### 9.1 Active Cartography 2회차 iterate (환원 재확인, 2026-06-20)

distribution-free / misspecification 각도로 환원을 정면 공격한 결과: **여전히 reduces-but-useful-niche (점수 5 < passive 6).** trust-acquisition 통합은 ASPEST/OCS-ARC/SCRC로 완전 환원(정리-형태 기여 아님 → engineering). coverage-story도 conformal-AL(CoPAL)로 환원.

**유일하게 살아남은 비환원 축 (genuine, 단 가설):**
> 분포값(cell population) 출력에서, frozen·misspecified base 하에, conformal-recoverability를 **acquisition TARGET 자체**로 쓰는 것이 conformalize된 misspecified-EIG-ranking보다 selective-AURC에서 낫고 gap이 misspecification에 단조 확대.

regime-match는 real(단일세포엔 calibrated population posterior 부재 → EPIG가 틀린 모델 위 계산). 그러나 **경험적 ranking claim일 뿐 증명 불가**, modal 결과 = tie, 가장 가까운 위협 = Stanton(BO+conformal)·LOCBO·RIAD(2506.07805, misspec-robust Bayesian AL).

**P5 ladder (이 한 축을 falsify하는 유일한 길 — 빌드 필요):**
- misspecification ladder(x): K562→RPE1 concept shift / operator-off under-param / pathway masking / HVG-PCA distortion.
- comparator(필수): **conformalized-EPIG**(빼면 straw-man) + GO-CBED-lite + conformal-recoverability, frozen base/oracle/budget 동일.
- 측정(y): selective-AURC(risk=oracle E-dist) + effect-size-stratified hit-curve.
- GO 조건: gap이 misspecification에 단조 확대 + perturbation-level bootstrap 95% CI 하한>0 (in-dist tie 허용).
- KILL: conformalized-EPIG가 모든 level에서 tie → coverage-fix뿐 / gap이 misspec-무관 → generic-AL / R4가 win 캐리 → uncertainty-sampling 동어반복. 어느 하나라도 → registered negative.
- cap: active loop가 exchangeability를 깸 → win 주장 구간(OOD, n_cal 수백, ESS<50)에서 보장이 vacuous할 수 있음. claim 상한.

**결론: 개념적 iteration 소진. 이 한 축은 데이터로만 답한다 → P5 실험을 빌드해야 resolve됨.**
