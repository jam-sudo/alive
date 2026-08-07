# COMPOSE — 식별가능한 Interaction-Composition Operator (Epistasis) Design

> **문서 역할:** milestone의 scientific claim 계약
> **상태:** **ACTIVE / RELEASE-BLOCKED / seal UNOPENED.** Lifecycle activation은 2026-06-30에
> 완료됐지만 현재 committed config/evidence는 release-ready가 아니다. Real fit과 sealed access는
> current `ActivationRecord`, finalized config/evidence, clean owner-approved exact SHA와
> `docs/superpowers/COMPOSE-SEAL-READINESS.md`의 release gate가 모두 유효할 때만 허용된다.
> **개정일:** 2026-07-24 (sealed secondary role roster를 live config/§10.4와 정합화;
> scientific claim unchanged)
> **protocol 이름:** `COMPOSE-K562-v1`
> **선행 milestone:** `TG-K562-v1` (COMPLETE, verdict `NO_DISTINCT_WIN`; 본 milestone은 그 결과에 소급 주장하지 않음, seal 영구 독립 §6.3)

---

## 0. 문서 역할, source-of-truth, 활성화 prerequisite

본 문서는 **조합 perturbation의 비가산(genetic-interaction) 성분을 식별가능한 composition
operator로 예측**하는 차기 milestone의 과학 계약과 Phase-2 사전등록 후보이다.
CLAUDE.md(safety/governance) 하위, milestone claim 도메인의 최상위 문서이다.
**§10.1의 initial lifecycle activation blocker 6개가 2026-06-30 충족되어 active protocol로
전환됐다**(`CLAUDE.md`#registry). 이 이력은 현재 실행 준비도를 의미하지 않는다. 현재 release
blocker와 seal 상태는 readiness index가 추적하며, release gate 전에는 real fit과 sealed run을 금지한다.

이 milestone의 initial lifecycle activation에는 다음이 모두 필요했다(§9). 현재 실행은 이 조건의
current-lineage 재검증과 별도 release gate를 추가로 요구한다:

1. owner 승인
2. 별도 versioned config (split·thresholds·seeds·metrics 확정)
3. **prior-art gate 통과**(§6) — novelty가 살아남는 범위 확정
4. **데이터 survey gate**(§2.1) — combo 데이터 power 현실 확정
5. `TG-K562-v1` seal과 독립된 신규 seal·run-identity·audit lifecycle
6. adequate sample-size / detectable-effect 분석(§2.4)

`COMPOSE-K562-v1` seal은 `TG-K562-v1` seal과 **교체 불가**다(CLAUDE.md#seal). 하나의 run ID·audit·
report가 두 seal을 동시에 대표할 수 없다.

본 milestone은 다음 durable finding 위에 선다(project-memory *alive-operator-design-incremental*):
function-class-identity상 held-out perturbation의 *평균*에서는 additive가 null이라 architecture로
이길 수 없고, architecture가 additive를 이기는 유일한 자리는 **non-additive 구조(조합·off-origin)**.
따라서 본 milestone의 천장은 "단일 perturbation을 더 잘 맞히기"가 아니라 "**개입의 합성/간섭을
식별가능하게 모델링**"에 있다.

---

## 1. 한 줄 정의, 과학 질문, claims & non-claims

### 1.1 한 줄 정의

단일-유전자 signature로부터 unseen 2-유전자 perturbation의 **비가산 성분**을 예측하는
*식별가능한 interaction-composition operator*를 학습한다. 공개데이터 = Norman et al. 2019
K562 CRISPRa GI Perturb-seq (§2.1에서 추가 combo 데이터 survey).

### 1.2 표기

- $\delta_g$ : 단일 perturbation $g$의 평균 효과(control 대비, 등록된 응답공간에서의 shift).
- additive null : $\delta_g+\delta_h$.
- 비가산(GI) 성분 : $\varepsilon_{gh}=\delta_{gh}-(\delta_g+\delta_h)$.
- regime(=split 단위=claim 강도, GEARS 표기와 일치):
  - **double-unseen** : 테스트 쌍의 *두 유전자 모두* 어떤 training combo에도 나타나지 않음 (headline 지향).
  - **single-unseen** : 한 유전자만 combo에 나타남.
  - **both-seen** : 두 유전자 모두 다른 combo에 나타남(보간).

### 1.3 과학 질문 (falsifiable)

명시한 가정 하에서, pairwise interaction operator가 *singles + doubles의 calibration subset*으로
부터 식별/추정되어 — **(i)** combo-unseen(double-unseen; 두 유전자의 single perturbation은 관측됨)
쌍의 held-out 비가산 효과를 additive null(및 published combo SOTA)보다 잘 예측하고, **(ii)** 합성
데이터에서 알려진 interaction 구조를 복원하는가?

1차 target = **평균(pseudobulk) 비가산 성분** $\varepsilon_{gh}$. 분포-값은 후속.

### 1.4 Claims (입증 대상)

- **claim 1 (식별가능성/recovery, 방법 기여).** *모델 class가 참일 때* 무잡음 full-rank 설계에서는
  대칭 bilinear operator의 식별가능 부분공간이 rank 조건으로 결정된다. 잡음·정규화가 있는 실제
  추정에서는 이를 **합성 parameter-recovery(known-answer)** 로 별도 입증한다.
- **claim 2 (일반화, real 베팅).** bilinear 모델이 real K562에서 근사 참이고 $z_g$가 GI-관련 성질을
  담을 때, double-unseen $\varepsilon$을 additive 대비 쌍-level bootstrap 95% CI 하한 > 사전등록
  margin으로 예측한다.
- **claim 3 (구조, 2차).** held-out 쌍의 알려진 GI 부호/class를 chance 이상으로 복원한다.

> **C3 — 식별가능성/recovery ≠ 일반화 (category error 금지).** claim 1의 대수적 식별가능성은
> *모델 class 가정 하의* 수학적 사실이고, 잡음하 recovery는 synthetic known-answer 검증이며,
> 둘 다 claim 2(real 예측)를 함의하지 않는다. bilinear가 실제로 근사 참인지·$z_g$(단일
> signature)가 GI를 담는지는 별개의 생물학적 베팅이다. GEARS가 GO 그래프를 도입한 사실 자체가
> "single signature만으론 unseen combo가 약하다"는 방증이므로 claim 2의 사전확률은 낮은 편으로
> 본다. 두 claim을 결코 한 문장으로 합치지 않는다.

### 1.5 Non-claims (category-error 방어)

- causal GRN / mechanism-graph 주장 아님 (interaction *합성*을 모델링; gene-regulatory 인과
  그래프가 아님).
- single-cell counterfactual·lineage 주장 아님.
- cross-cell-line transfer 아님 (그것은 별도 `CT-RPE1` milestone).
- 분포-값 주장 아님 (mean-first).
- "bilinear = 진짜 생물학" 주장 아님 — 식별가능 operator가 additive·capacity baseline을 *이기는
  곳에서만* 그렇다고 한다.
- **additive가 null이다.** double-unseen에서 additive를 못 이기면 정직한 negative.
- **Norman = CRISPRa(활성화) ≠ Replogle CRISPRi(억제).** 결과를 KD로 조용히 전이하지 않는다.

---

## 2. 데이터, eligibility, split, seal, pre-check gates

### 2.1 데이터 + survey gate (C1)

기본 = Norman et al. 2019 K562 CRISPRa GI Perturb-seq (공개; source/license는 GEO GSE133344 또는
scPerturb로 확정). singles + ~131 combos + controls. **기존 ESM-2 pipeline 재사용**으로 gene
feature 생성. CRISPRa라 Replogle와 별개의 data-card·manifest·governance.

> **데이터 survey gate (활성화 전 필수).** Norman의 combo는 ~131개의 *설계된 sparse* 쌍이라,
> double-unseen 격리 후 테스트 쌍이 한 자릿수로 줄 수 있다(power 부족). 활성화 전 **다른 공개
> combo Perturb-seq(2023–2025 대형 CRISPR combo set 등) 존재 여부를 조사**하고, 확보 가능하면
> 병합하여 double-unseen power를 보강한다. 단, cell line·CRISPR modality·lab/batch가 다르면
> 이를 같은 K562-CRISPRa claim으로 섞지 않고 dataset-stratified 또는 cross-dataset regime으로
> 별도 사전등록한다. 없으면 §2.4 power gate가 headline을 강등한다.

### 2.2 Eligibility (outcome-independent, split 전 확정; §5/§7)

(a) cell-count/QC 임계 — 실분포 profiling 후 사전등록, (b) 두 유전자 모두 ESM sequence 가용,
(c) test set의 double-unseen 그래프 제약. **GI 강도/response 크기로는 절대 선택하지 않는다(§5
no outcome-selected test set).**

### 2.3 Split (단위 = perturbation PAIR; §6)

disjoint roles:

- `singles_train` — 모든 $\delta_g$ ( → $z_g$ 식별, Stage 1).
- `combo_calibration` — $B$ 식별용 doubles subset (**rank/span 조건 충족 필수**, Stage 2).
- `sealed_double_unseen` — 두 유전자 모두 training combo에 없는 쌍(**headline**, power 충족 시).
  단, 두 유전자의 single perturbation은 `singles_train`에서 관측되므로 이는 gene-zero-shot이 아니라
  combo/pair-zero-shot이다.
- `sealed_single_unseen` — 정확히 한 유전자만 calibration gene set에 속하는 쌍
  (**등록된 secondary evaluation regime**).

두 유전자 모두 calibration gene set에 속하는 both-seen pair는 `combo_calibration`이다. 따라서
COMPOSE-K562-v1에는 별도 both-seen sealed role이 없으며, both-seen test는 deferred다
(`configs/compose_k562_v1_phase2.yaml`). role roster의 정본은
`combo_calibration`, `sealed_double_unseen`, `sealed_single_unseen`의 정확한 3개다.

그래프 제약: GI 그래프를 분할해 test-쌍 유전자를 training combo에서 격리한다. 이 격리가 power를
제한한다(§2.4).

### 2.4 Pre-check gates (사전등록, fit 전, development 단계)

- **Power gate.** valid double-unseen 쌍 수·쌍당 cell 수 → additive-vs-model 대비의 detectable
  effect. 미달 시 **headline을 가장 잘-powered된 regime(예: single-unseen)으로 강등**하고
  double-unseen은 exploratory로 보고한다(sample-size/detectable-effect 분석 — activation blocker `docs/activation-evidence/compose/real_norman_detectable_effect_report.json`).
- **Measurability / noise-ceiling gate.** split-half(또는 replicate) 추정기로 $\varepsilon$의
  noise floor와 추정가능 분산(천장)을 산출·보고한다. 이 gate는 `combo_calibration`/unsealed
  development pairs 또는 outcome-independent cell-count metadata만 사용한다. `sealed_double_unseen`
  및 `sealed_single_unseen`의 expression/outcome을 사용해 noise ceiling을 추정하지 않는다. 신호 ≈
  noise면 **FUTILITY_STOPPED**(§4), 합성 결과를 deliverable로, seal은 닫힌 채 종료.
- **Rank gate.** calibration 설계행렬 $\Phi$(§3.2)의 rank를 보고; 미달이면 식별 부분공간을
  명시하고 그 밖의 double-unseen 예측은 주장하지 않는다.

### 2.5 Seal (신규·독립; §6.3)

`sealed_double_unseen`과 `sealed_single_unseen` outcome은 model/method freeze 후 하나의
등록된 sealed union으로 **정확히 1회** 개방한다.
fit/식별/선택에는 `singles_train` + `combo_calibration`만 사용한다. `TG-K562-v1`과 별도의
run-identity·audit·store. composite run_id = config + data-card + raw + feature-map digest.
futility-stopped run은 sealed access count 0으로 영구 종료한다.

---

## 3. 모델: 2단계 식별 bilinear operator + ablation ladder + 합성 recovery

### 3.1 응답공간 & Stage 1 ($z_g$ 고정 식별)

control에 적합한 basis로 log-normalized expression을 사영(top-DE 또는 PCA, **training role에만
적합**) → 응답공간 차원 $p$ (등록된 config 선택). $\delta_g$ = 그 공간의 평균 shift.
interaction용 per-gene factor:

$$z_g=[\,\mathrm{PCA}_k(\delta_g)\;;\;\text{(optional) ESM 사영}\,]\in\mathbb{R}^k,\quad
\text{singles에서 먼저 고정}.$$

ESM는 bolt-on이 아니라 **고정 입력 factor**로 재도입한다(project-memory *cartographer-mvp-built-merged*의 OOF
탐색적 가설 1: 서열 축이 신호를 가질 수 있음을, 이번엔 식별가능 구조 안에서 검증). $z_g$를 먼저
고정해야 Stage 2가 선형이 된다(end-to-end는 rotation ambiguity로 식별성을 잃음 → ablation L3).

### 3.2 Stage 2 (대수적으로 식별가능한 bilinear operator $B$ = headline A)

$$\varepsilon_{gh}[m]=z_g^\top B_m\,z_h,\quad B_m=B_m^\top\ (k\times k),\quad m=1..p;\qquad
\hat\delta_{gh}=\delta_g+\delta_h+\hat\varepsilon_{gh}.$$

대칭 $B_m$ ⟹ $\varepsilon_{gh}=\varepsilon_{hg}$. 식별 = calibration 쌍에 대한 정규화 최소제곱
$\min_{\{B_m\}}\sum_{(g,h)\in\text{Cal}}\|\varepsilon^{obs}_{gh}-B(z_g,z_h)\|^2+\lambda\mathcal R(B)$
($\mathcal R$ = ridge / nuclear-norm 저랭크).

**대수적 식별가능성 = rank 조건.** 각 출력차원 $m$에 대해
$\varepsilon_{gh}[m]=\langle\mathrm{vecsym}(z_gz_h^\top),\mathrm{vecsym}(B_m)\rangle$ 는 $B_m$에
선형이다. $\Phi=[\mathrm{vecsym}(z_gz_h^\top)]_{(g,h)\in\text{Cal}}$의 rank가
$\dim(\text{sym }k\times k)=k(k+1)/2$ 이상이면 **무잡음·비정규화 선형계에서** $B$의 해당 부분공간이
완전식별된다. 미달이면 식별 부분공간 내에서만(rank gate, §2.4). 잡음·ridge·nuclear-norm이 들어간
실제 추정에서는 rank만으로 충분하지 않으므로 condition number, regularization path, synthetic
known-answer recovery(§3.4)를 함께 보고한다.

> **I6 — $k$는 |Cal|에 강하게 묶임.** 무잡음 완전식별엔 $|\text{Cal}|\ge k(k+1)/2$가 필요한데
> Norman에선 $|\text{Cal}|\sim 60$–$90$ → 작은 $k$ 또는 저랭크가 필수이고, 이는 표현력을 제한해
> claim 2의 위험이 된다. 합성 연구(§3.4)는 **$k$ vs $|\text{Cal}|$ 식별/표현 frontier를 sweep**한다.

### 3.3 Ablation ladder (= 과학 질문)

- **L0** additive null ($\varepsilon=0$).
- **L1 = A (headline)** 2단계 bilinear 식별 operator.
- **L2 = C** + 사전등록된 단조 saturation 비선형 $\varepsilon=\sigma(\text{bilinear})$ — 최소 비선형성이
  이득을 주는지 보는 constrained extension. Claim 1의 대수적 식별가능성 주장은 L1에 한정한다.
- **L3 = B** hypernetwork로 $z$·operator end-to-end 학습 — capacity 최대, **식별가능성 정리 없음**.

답하는 질문: **식별가능한 핵심 구조(L1; L2는 제약 확장)가 additive(L0)와 무제약 capacity(L3)를
둘 다 이기는가?**

### 3.4 합성 recovery 프로토콜 (claim 1 입증, real과 독립)

랜덤 $z_g$·랜덤 저랭크 대칭 $B^\ast$ → $\varepsilon^\ast_{gh}$ 생성 → 무잡음 rank-condition 확인 →
**Norman 쌍당 cell 수를 모사한 noise** 주입 → double-unseen 격리 → 추정 $\hat B$.
Known-answer 검증:
(a) 무잡음 full-rank 조건에서 대수적 복원 확인, (b) 잡음하 식별 부분공간에서
$\|\hat B-B^\ast\|$ 및 double-unseen $\varepsilon$ 예측오차가 사전등록 허용치 이내,
(c) rank/conditioning 악화 시 graceful 저하 + flag, (d) **$\varepsilon^\ast=0$이면
$\hat\varepsilon\approx0$(거짓 GI 안 만듦)**, (e) noise–쌍당cell 대비 recovery 곡선($k$/|Cal|
frontier 포함; 실데이터 기대치 보정).

### 3.5 Leakage 규율 (§4 universal invariant)

응답 basis, $z_g$(PCA/ESM 사영), rank $k$, $\lambda$, output $p$ — 전부 training role
(`singles_train` + `combo_calibration`)에서만 적합/선택. hyperparameter는 calibration 쌍 OOF
cross-validation으로 선택하되, **OOF fold는 sealed와 동일한 gene-disjoint folding**을 써서
난이도 누수를 막는다(I7). `sealed_double_unseen`은 freeze 후 1회만.

---

## 4. 평가, baseline roster, simultaneous inference, futility, verdict

### 4.1 Baseline roster (§9, outcome 보기 전 고정)

1. **additive null** $\delta_g+\delta_h$ — primary null.
2. no-change / control, perturbation-mean — 하한.
3. **GEARS** — published combo SOTA(강한 learned baseline; Phase 2).
4. **CPA** — latent-*additive* baseline(비가산 항의 차별점 정조준; Phase 2).
5. **linear / ID-only** — bilinear 구조 없는 선형.
6. ablation **L2·L3** — "구조 vs capacity" comparator.

### 4.2 Primary metric & 방향

쌍별 $\hat\delta_{gh}$의 응답공간 MSE를 primitive로 둔다. confirmatory estimand는 additive 대비
**paired relative error reduction**
$1-\overline e_{L1}/\overline e_{\mathrm{additive}}$이며, perturbation pair를 resampling unit으로
bootstrap한다. additive가 큰 효과를 이미 잡으므로 이 대비는 비가산 개선을 겨냥한다. 2차
`gi_explained_fraction`은 zero-GI 예측을 기준으로 한
$1-\mathrm{SSE}(\epsilon,\hat\epsilon)/\max(\mathrm{SST}(\epsilon),10^{-12})$이며,
split-half noise ceiling으로 정규화하지 않는다. §2.4 noise ceiling은 별도 측정 신뢰도 진단으로
병기하며 이 2차 지표나 verdict의 분모로 사용하지 않는다.

### 4.3 Scientific event 위계 (CARTOGRAPHER 교훈 반영)

- **(real 1차)** double-unseen(또는 강등된 powered regime)에서 $L1$이 additive를 쌍-level
  bootstrap 95% CI 하한 > 사전등록 material margin으로 이김.
- **(비교, simultaneous)** $L1$ vs learned family{GEARS, CPA, ID-only, L3}를 **family-wise
  동시추론**으로만 우위 주장(사후 최강 comparator 선택 금지).
- **(구조, 2차)** held-out 쌍의 GI 부호/class 복원 > chance(등록 metric·chance 기준).

### 4.4 Known-answer metric tests (CLAUDE.md#verify known-answer 요건)

constant·shuffled-pairs·additive=truth($\Delta\approx0$)·perfect-GI($\Delta$ 최대)를 toy로 검증.

### 4.5 Verdict — 두 축 분리 (C4)

- **방법 축 (합성, development; seal 무관):** `METHOD_VALIDATED` / `METHOD_NOT_VALIDATED`.
- **sealed verdict 축 (real):**
  - `GI_LEARNABLE_WIN` — double-unseen에서 additive 격파(CI>margin) **그리고** learned family를
    동시추론 통과.
  - `PARTIAL` — additive는 이기나 family 전체는 못 이김.
  - `NO_DISTINCT_WIN` — additive를 못 이김(정직한 negative; 합성 방법 입증은 별도로 유지).
  - `FUTILITY_STOPPED` — development 단계 중단(미powered/측정불가/rank 실패; sealed access 0).
  - `INVALID` — provenance/leakage/integrity 실패.

report는 두 축을 모두 싣고, regime은 headline + secondary 전부 보고한다(§10 no single-metric).

### 4.6 무결성 표현 규율

verdict는 구조적 clause를 **한계와 함께** 보고하고 "모든 무결성 검증 완료"라 쓰지 않는다. 이는
run 내부 자기검증이며 독립 audit이 아님을 명시한다(project-memory *cartographer-mvp-built-merged* 교훈).

---

## 5. Phasing (I5; CLAUDE.md#agent 최소 falsifying 실험)

- **Phase 1 (값쌈, go/no-go 결정).** 합성 식별가능성 입증(claim 1, §3.4) + Norman에서
  power·measurability·rank gate(§2.4)만. real 연구의 가치를 *결정*한다. gate 실패 시 GEARS/CPA
  통합에 자원을 쓰지 않고 Phase 1 결과(방법 입증 + 정직한 특성화)로 종료.
- **Phase 2 (gate 통과 시에만).** GEARS/CPA 통합 + real sealed eval + verdict. GEARS 통합이 가장
  비싼 외부 의존성이므로 Phase 1 통과가 그 비용을 정당화해야 한다.

---

## 6. Prior-art gate & novelty scope (C2; 우리 moat)

활성화 전 **focused prior-art check 필수**. 점검 대상: (i) drug-combination synergy의
bilinear/tensor factorization 문헌(DeepSynergy 계열 등), (ii) 고전 유전학의 저랭크 GI 행렬
(Costanzo/Boone yeast), (iii) transcriptomic GI 예측·CPA·GEARS.

이 check 통과 전에는 novelty를 주장하지 않는다. 살아남을 것으로 예상하는 좁은 novelty:

1. scalar synergy가 아닌 **transcriptome-valued(벡터) GI** 예측.
2. **unseen-pair 식별가능성 rank 조건**(대부분 synergy 논문은 식별성을 진술하지 않음).
3. single-perturbation signature로부터 **combo/pair-zero-shot double-unseen** 일반화 + 2단계 식별.

check 결과 선점이 확인되면 novelty scope를 그에 맞게 축소하거나 milestone을 재설계한다.

### 6.1 Gate 실행 결과 (2026-06-23): `NOVELTY_NARROWED`

Audit: `docs/superpowers/audits/2026-06-23-compose-prior-art.md`. 단일 선행이 세 leg를 함께
수행하지 않으므로 `PRECEDED` 아님(재설계 불필요). 가장 가까운 단일 위협 = **RECOVER**(Bertin et
al. 2023, bilinear combination operator)이나 출력이 **scalar Bliss synergy**이고 식별성 진술이
없어 leg 1·2를 비킴. **GEARS**는 벡터 double-unseen을 하나 GO-graph GNN이며 대수적 식별성이 없고,
오히려 "singles만으론 unseen combo가 약하다"는 반대 증거(claim 2 사전확률↓). 활성화 시 강제되는
**축소 scope**:

1. 벡터 출력 자체를 novelty로 주장 금지(GEARS/CPA/Norman 선점) — novelty는 "벡터 *GI 성분의
   식별가능 격리*"에 한정.
2. bilinear 조합 모듈 자체를 novelty로 주장 금지(RECOVER 선점) — "그 operator의 명시적
   unseen-pair rank 식별성 + transcriptome-valued GI 적용"에 한정.
3. 식별성 수학을 신규 정리로 주장 금지(bilinear-inverse-problem 문헌 선점, arXiv 1402.2637) —
   기여는 "그 조건을 GI/perturbation 예측에 최초 명시·적용 + Norman 설계행렬 rank 보고"(방법-적용
   novelty).
4. RECOVER·GEARS·CPA·Norman을 prior-art로 명시 인용하고 claim마다 차별점 대비.
5. real win(`GI_LEARNABLE_WIN`)은 simultaneous inference로 GEARS/CPA/L3를 함께 이길 때만 주장;
   못 이기면 정직한 `NO_DISTINCT_WIN`(합성 `METHOD_VALIDATED`는 별도 유지).

---

## 7. Run-identity, provenance, governance mapping

CLAUDE.md#provenance(write-once run identity)·#repo(repo conventions)·#compute(compute) 전부 적용. 기존
CARTOGRAPHER 인프라(RunLedger, composite run_id, append-only audit, stage-locking, ESM feature
bank, cloud provenance recorder)를 재사용한다. 신규 요소: Norman data-card, pair-level manifest,
bilinear 식별기, 합성 recovery harness, GI metric. 모든 production logic은 `src/alive/`에 두고
tests(unit/leakage/metric/repro/integration)를 동반한다.

---

## 8. Risks & kill-conditions (요약)

- **R-power (C1):** double-unseen이 Norman 단독으로 underpowered → headline 강등 또는 추가 데이터
  필요. *kill:* powered regime이 전무하면 real Phase 2 보류, Phase 1로 종료.
- **R-prior-art (C2):** kernel이 drug-synergy 문헌에 선점 → novelty scope 축소/재설계.
- **R-bio (C3):** GI가 single signature로 예측 불가 → `NO_DISTINCT_WIN`(합성 입증은 유지).
- **R-noise:** GI 신호가 noise 천장 아래 → `FUTILITY_STOPPED`.
- **R-capacity:** L3(capacity)가 L1(구조)를 이김 → 식별가능 구조가 불필요하다는 정직한 결과.

각 위험은 사전등록 gate(§2.4)·verdict(§4.5)·prior-art gate(§6)로 *설계 안에서* 노출되며, 사후
은폐하지 않는다.

---

## 9. 활성화 prerequisites (CT-RPE1과 동급)

`COMPOSE-K562-v1`은 다음 전까지 활성화하지 않는다:

1. owner 승인
2. 별도 scientific config (split·thresholds·seeds·metrics)
3. prior-art gate 통과(§6)
4. 데이터 survey gate 결과(§2.1) + adequate sample-size 분석(§2.4)
5. `TG-K562-v1`과 독립된 신규 seal·run-identity·audit lifecycle
6. (Phase 2 한정) Norman data-card·license 확정 + GEARS/CPA 재현 환경

활성화 시 CLAUDE.md#registry protocol registry에 본 protocol을 등재하고, 현재 결과에 소급해 주장하지
않는다.

---

## 10. Phase-2 registered design (owner-approved; execution release-blocked)

Owner는 2026-06-23 Phase-2 설계와 사전등록 후보 작성을 승인했다. exact 후보 값은
`configs/compose_k562_v1_phase2.yaml`가 source-of-truth(CLAUDE.md#sources)이며, 본 절은
claim·정직성 계약을 고정한다. 이는 sealed scientific run의 승인이 아니다.

### 10.1 Initial activation contract와 current release gate

> **Lifecycle 기록 (2026-06-30): 6개 blocker 충족 — activation 완료.** 당시 evidence는
> `docs/activation-evidence/compose/`(phi-rank, detectable-effect, GEARS/CPA lock)와
> `docs/data-cards/norman_compose_k562_v1.json`, tests는 `tests/alive/compose/`에 기록됐다.
> `CLAUDE.md`#registry는 같은 activation commit에서 `ACTIVE`로 전환됐다. 아래 목록은 initial
> activation 계약을 보존한다. 현재 evidence set은 `INCOMPLETE`이며 scientific guard가 거부하므로,
> finalized config lineage에서 재생성되고 readiness release gate가 통과되기 전에는 실행할 수 없다.

다음은 lifecycle activation과 모든 후속 release lineage에서 유지되어야 한다. Current evidence/artifact가
하나라도 미완료·불일치하면 real Phase-2 fit, sealed outcome 접근과 verdict 산출을 금지한다.

1. 실제 Norman `combo_calibration`에서 각 후보 total factor dimension에 대한
   $\Phi$ rank·condition number 보고.
2. double-unseen과 single-unseen 각각의 detectable-effect/power 분석. 단순 pair count는
   “powered” 판정이 아니다.
3. source URL/DOI, license, raw/processed SHA-256, obs schema와 exclusion summary를 포함한 확정
   Norman data-card.
4. GEARS/CPA package revision, transitive dependencies, device/precision을 고정한 재현 환경.
5. TG-K562와 독립된 COMPOSE outcome store, access audit와 write-once run lifecycle.
6. Phase-2 implementation plan, metric known-answer tests, split reproducibility tests,
   leakage tests와 seal-once integration test.

### 10.2 Regimes and current evidence limits

개발 메모에는 calibration-role split-half $\varepsilon$ correlation 0.868과 seed survey의
double-unseen 약 22쌍·single-unseen 약 68쌍이 기록되어 있다. 그러나 현재 저장소에는 이 수치의
독립 재현에 필요한 immutable input hash와 실제 Norman $\Phi$ rank evidence가 없다. 따라서 이
수치는 provisional planning estimate이며 activation evidence나 power 판정으로 사용하지 않는다.

- **double-unseen = confirmatory headline candidate.**
- **single-unseen = registered secondary candidate; power status unestablished.**
- activation 전 power 분석이 headline의 minimum detectable relative improvement를 충족하지 못하면
  double-unseen을 exploratory로 강등하고 config/run identity를 새로 등록한다. 결과를 본 뒤 regime을
  교체하지 않는다.

### 10.3 Negative-result value without overclaim

double-unseen이 `NO_DISTINCT_WIN`이어도 합성 known-answer 결과와 calibration-only GI
특성화는 별도 산출물로 유지한다. 합성 `METHOD_VALIDATED`는 real 일반화나 생물학적 GI
학습가능성을 입증하지 않는다. single-unseen도 등록된 secondary 결과로 보고하되, power evidence
없이는 “powered” 또는 confirmatory win으로 표현하지 않는다.

### 10.4 Deterministic split and identifiability

split seed = **11 a priori**(단일 sealed partition). eligibility를 먼저 적용하고 pair를
`(min(g,h), max(g,h))`로 canonicalize·중복 제거·UTF-8 lexicographic 정렬한다. eligible gene
목록도 같은 정렬을 사용하고 NumPy `Generator(PCG64(seed))` permutation의 앞
`round-half-to-even(0.6 × n_genes)`개를 calibration genes로 둔다. 두 gene이 calibration이면
`combo_calibration`, 둘 다 아니면 `sealed_double_unseen`, 정확히 하나면
`sealed_single_unseen`이다. NumPy와 lock hash는 run identity에 포함한다.

$z_g$의 **total dimension**만 `k_total_grid=[4,6,8]`로 선택한다. ESM을 사용할 때 각 total
dimension 중 2차원은 eligible single-gene ESM vectors에 outcome 없이 적합한 고정 PCA projection,
나머지 `k_total-2`차원은 expression PCA이다. 따라서 rank 조건은 결합 후 total dimension에 대해
`rank(Φ)=k_total(k_total+1)/2`이며, 단순 pair-count floor가 아니라 실제 $\Phi$ rank와 condition
number를 gate로 사용한다. calibration gene-disjoint OOF로 `k_total`·$\lambda$를 선택한다.

**OOF estimator-domain gate.** `lambda=0` 후보는 각 gene-disjoint OOF **train fold**의 $\Phi$가
`max(Phi.shape) * float64_eps * sigma_max` tolerance로 full column rank일 때만 점수를 계산한다. 어느
train fold라도 미달이면 그 `(k_total, lambda)`는 estimator가 정의되지 않은 **non-viable candidate**로
사유와 함께 기록하고 점수 map에서 제외한다. `NaN`/`±Infinity` 점수나 LAPACK이 우연히 반환한 임의
해를 selection에 넣지 않는다. 모든 후보가 non-viable이면 selection 자체가 무효이며 hard error로
종료한다. 통과한 `lambda=0` 적합과 Phase-1 rank-deficient recovery characterization은 같은 tolerance의
SVD minimum-norm least-squares(`svd_lstsq_minimum_norm`)로 계산해 singular normal equation의 임의 해를
사용하지 않는다. `lambda>0` ridge 후보는 이 unregularized-domain gate의 대상이 아니지만, 선택된
`k_total`은 위의 full-calibration 실제 $\Phi$ rank/condition futility gate를 그대로 통과해야 한다.
양의 ridge는 normal equation을 만들지 않고 $\Phi$의 SVD filter factor
$s/(s^2+\lambda)$를 수치적으로 안전한 분기식으로 계산하는
`svd_ridge_filter_factors`를 사용한다. 이 방식은 condition number를 제곱하지 않으며 큰 factor scale에서
`Phi.T @ Phi + lambda I`의 lambda가 반올림으로 소실되는 경로를 제거한다. 정확한 solver/policy/rule
문자열은 config `identification.unregularized_solver`, `identification.regularized_solver`,
`identification.unregularized_oof_rank_policy`, `identification.rank_tolerance_rule`에 동결한다.

**Registered conditioning ceiling.** 등록된 admissibility 기준으로 $\Phi$의 조건수 상한을 둔다.
통계량은 각 후보 `k_total`의 full-calibration $\Phi$에 대한 `rank_diagnostics(Φ).condition_number`이고,
상한은 config `identification.condition_ceiling`에 동결한다. 값의 근거는 data-free numeric anchor
$1/\sqrt{\varepsilon_{f64}}\approx 6.7\times10^{7}$ — float64가 유효자릿수의 절반을 잃는 지점 — 을
한 자릿수 올림한 값이며, 어떤 outcome도 보지 않고 정한다.

이 기준이 **덮는 것**은 $z$의 expression block과 ESM block 사이의 **scale imbalance**다. 두 block의
상대 scale은 upstream 어디에서도 bound되지 않으며, 2026-07-29에 도입돼 2026-07-31에 삭제된
representability guard가 이를 우연히 탐지하던 유일한 장치였다. 측정된 exhibit: 동일 bank에서 ESM
block만 $\times10^6$하면 조건수가 $10.42\to3.71\times10^{12}$로 움직인다.

이 기준이 **덮지 않는 것**은 uniform scale이다. 조건수는 $z$ 전체의 uniform rescale에 대해 반올림
오차 범위에서 불변이므로(정확히 불변은 아니다), uniform-scale에서의 penalty immateriality는 이 상한으로
**닫히지 않는다**. 그 band는 readiness index에 별도 항목으로 기록되어 있으며, 이 상한을 그것의 해결로
읽어서는 안 된다.

**첫 번째 적용 지점은 selection의 후보별 심사이며 futility condition이 아니다.** 형제 기준인
`unregularized_oof_rank_policy`와 같은 형태로, 상한을 넘는 `k_total`은 그 사유와 함께
`nonviable_candidates`에 기록되고 점수 map에서 제외되며 selection은 나머지 후보로 진행한다. **모든**
후보가 부적격일 때에만 selection 자체가 무효가 되어 `SelectionError`로 종료한다 — 이미 등록된 pre-seal
rejection(exit 10)이자 runbook 카테고리 D("반복 재실행이 아니라 원인 조사")이므로 새 exception class도
새 futility condition도 필요하지 않다. 등록된 `futility.conditions`는 그대로 유지된다.

**두 번째 적용 지점은 비정칙 OOF train fold다.** 위 통계량은 full-calibration roster 전체에 대한
것이므로 하나의 gene-disjoint group에 국한된 degeneracy를 보지 못한다. fold는 held-out gene을 건드리는
pair를 모두 버리므로 fold의 train 설계는 full 설계보다 작고 일반적으로 더 나쁘게 조건화된다. 측정된
exhibit(2026-08-07, synthetic, `tests/alive/compose/test_condition_ceiling.py`의
`_fold_local_degeneracy_instance`): 마지막 factor의 크기를 fold 0의 held-out gene에만 남기면 full 설계는
$\mathrm{cond}=6.47$로 상한을 통과하고 rank도 가득 차 있으나 세 fold의 train 설계는
$(3.03\times10^{12},\ 5.17,\ 7.13)$으로 fold 0만 11.7 order 떨어져 있다. 같은 상한을 fold의 train
설계에도 적용하며, 초과 후보는 후보별 심사와 **같은 사유 접두사**로 `nonviable_candidates`에 기록한다.
이 arm은 selection 내부 신호로 `FoldConditioningError`를 쓴다. `SelectionError`의 **subclass**이며
`select_hyperparams`가 항상 포착하므로 밖으로 나가지 않는다 — subclass인 이유는 만에 하나 escape해도
등록된 pre-seal rejection roster(exit 10)에 걸리고 uncontracted bug(exit 1)가 되지 않게 하기 위해서다.
따라서 위 문단의 "새 exception class가 필요 없다"는 진술은 **모든 후보 부적격 시의 종료 경로**에 대한
것으로 그대로 유효하다: 그 종료는 여전히 `SelectionError`이고 등록된 `futility.conditions`도 불변이다.

이 arm은 **`lam == 0.0`에서만** 적용한다. 그 지점이 `identify_operator`가 비정칙 `lstsq` 분기를 타는
곳, 즉 $\mathrm{cond}(\Phi)$가 곧 solve의 조건수인 유일한 지점이다. `lam > 0`에서는 ridge filter
factor가 실효 조건수를 묶으므로 비정칙 조건수로 거부하면 실제 solve가 멀쩡한 후보를 버리게 된다. 등록된
`unregularized_oof_rank_policy`가 `lam == 0.0`에만 적용되는 것과 같은 경계다.

> **한계 (2026-08-07 독립 리뷰).** 이 보호의 크기는 factor bank의 scale에 의존하며, 그 scale은 어떤 config
> field도 묶지 않는다. $\Phi$는 $z$에 대해 bilinear이므로 $z\to cz$이면 $\Phi\to c^{2}\Phi$이고,
> `solve_ridge_svd`는 penalty를 raw $\Phi$에 걸므로 실효 penalty는 $\lambda/c^{4}$가 된다. 반면
> $\mathrm{cond}(\Phi)$는 uniform rescale에 불변이고(이 문서가 위에서 detector 성질로 등록한 바로 그
> 성질) 등록된 `lambda_grid`는 **절대값**이다. 따라서 "`lam > 0`은 안전하다"는 진술은 등록된 grid가
> 실제 $\lVert z\rVert$에서 healthy window에 들어갈 때에만 성립하며, 조건수만으로는 판정할 수 없다.
> 측정(2026-08-07 재측정, `_fold_local_degeneracy_instance` 기본 exhibit = 상대 noise 0.01, `eps`도
> $c^{2}$로 함께 rescale, `lam=0.001`):
>
> | | $c=1$ | $c=100$ |
> |---|---|---|
> | noise $=0$ | 0.8100934924563623 | 0.9577101250921993 |
> | noise $=0.01$ (기본) | 0.8103235465139835 | **−3340344.0205271696** |
>
> $\mathrm{cond}(\Phi)$는 네 칸 모두에서 6.4732…로 동일하다. $\lambda/c^{4}$ 항등식도 확인했다
> ($c=100,\lambda=10^{-3}$ ≡ $c=1,\lambda=10^{-11}$, 유효숫자 10자리). 즉 기본 exhibit에서 bank를
> $\times100$하면 $\theta$가 **−3.34×10⁶으로 붕괴**하며, 이는 어떤 `dev_oof_threshold`보다도 한참
> 아래다. 이 한계는 **닫히지 않았고** readiness index에 기록한다.
>
> > **2026-08-07 철회.** 최초 기록은 이 이동을 "0.8103 → 0.9577"로 적고 그 위에 "동일 설계"라고
> > 썼다. 두 값은 **서로 다른 exhibit**의 것이다(0.8103은 noisy 기본값, 0.9577은 noiseless). 어떤
> > (noise, c) 조합도 그 쌍을 만들지 않으며, noiseless 기준선은 0.8101이다. 또한 리뷰어가 제시한
> > −3.3e6을 "eps를 함께 rescale하지 않은 혼동"이라며 재현 실패로 기각했는데, 그 근거는 **틀렸다** —
> > $\theta$는 outcome의 uniform rescale에 불변이며(측정 차이 상대 5×10⁻⁹), 실제 차이는 noise였다.
> > 재현 실패의 원인은 내가 fix wave 이전의 noiseless exhibit으로 측정한 것이다. 기각을 철회하고
> > 리뷰어의 측정을 채택한다. 이는 이 commit이 고쳤다고 주장한 misattribution과 **같은 유형**이다.

이 arm이 바로잡는 것은 **일반적으로 승자 오염이 아니라 사유 오귀속**이다. 조건수는 **noise 증폭**을
묶는 양이므로, noise가 있는 데이터에서 조건 악화는 held-out 오차를 키워 $\theta$를 낮추고 따라서 argmax를
이기지 못한다(2026-08-07 측정: 유한 초과 fold를 가진 37개 설계 중 등록 grid의 깨끗한 형제 차원을 이긴
경우 0건, 상대 noise 0.01).

> **이 진술은 무조건적이지 않다 (2026-08-07 독립 리뷰 2건).** noise가 0이면 증폭할 것이 없고 비정칙
> `lstsq`는 정확해지므로 초과 후보가 $\theta=0.9999999993$으로 **이긴다** — 그리고 screen이 승자를
> 바꾼다(0.99999999933 → 0.81009349246). 최초 기록은 이를 무조건적 성질로 서술했고, 그 근거로 제시된
> exhibit 자체가 반례였다. 경계는 test로 고정한다
> (`test_the_winner_claim_is_conditional_on_noise_and_the_boundary_is_pinned`).
> screen이 승자를 바꿀 수 있다는 것은 **등록된 futility 조건**(`oof_theta <= dev_oof_threshold`)의 값도
> 바꿀 수 있다는 뜻이므로, 이 scope는 무해한 세부가 아니다.

문제는 그 후보가 *정당한 낮은 점수*로 기록되어 이어지는 정지가
`dev_oof_delta_below_threshold`(생물학에 관한 주장)라는 이름을 다는 것이다. 심사 기록과 `diagnostics2`의
context 줄이 그 오귀속을 막는다. context 줄은 `k_total`이 아니라 `(k_total, lambda)` 후보를 지목한다 —
후보별 arm은 한 `k_total`을 모든 lambda에서 제거하지만 fold arm은 그 `lam=0.0` 후보만 제거하므로, 차원
단위로 보고하면 그 줄 자체가 또 하나의 오귀속이 된다.

activation-evidence(`phi_rank`)는 full 설계의 조건수만 보고하므로 이 두 번째 arm을 **사전 증거로 닫지
않는다**. fold 단위 조건수는 run 시점에 selection이 강제하며, 그 한계는 readiness index에 기록한다.

두 arm 모두 심사는 **유한한 조건수에만** 적용한다. `rank_diagnostics`는 `rank < sym_dim` **또는**
`pos.size == 0`일 때 $\infty$를 반환한다. 후자는 `k_total == 0`에서 `is_full_rank`가 참인 채로 발생하므로
"rank 결손일 때 **정확히** $\infty$"는 사실이 아니다(2026-08-07 리뷰). 어느 경우든 $\infty$는 등록된 rank
정책의 소관이며, 후보별 arm에서 이를 함께 걸러내면 selection이 조용히 full-rank 차원으로 옮겨가 rank
futility gate가 도달 불가능해진다.

fold arm에서 경계는 **후보 단위 pre-pass**로 보장한다 — 모든 fold의 rank를 먼저 검사하고, 그 뒤에야 어느
fold든 조건수를 검사한다. fold 루프 안에서 fold마다 두 검사를 하면 등가로 보이지만 아니다: 루프는 첫 위반
fold에서 raise하므로 fold 0의 조건수 raise가 fold 1의 rank 실패를 가려, 실제로는 **non-identifiable**인
후보가 "numerically inadmissible"로 기록되고 사유가 fold 순서에 의존하게 된다. 더 강한 진단을 그렇게 잃는
것이 이 screen이 막으려는 오귀속 그 자체다. 2026-08-07 독립 리뷰가 발견했고, 해당 경로는 test로 고정했다.

상한 자체가 `NaN`이나 $\infty$이면 심사가 모든 후보에서 침묵하고(`cond > NaN`은 항상 False), non-positive면
반대로 모든 후보를 거부한다. 두 방향 모두 사용 불가이므로 config loader와 selection 양쪽에서 거부한다.
같은 통계량을 같은 설계에 대해 계산하는 activation-evidence validator(`phi_rank`)와 그 producer의 READY
판정도 이 상한에 결합한다. 결합은 run과 **같은 ANY 규칙**이어야 한다 — 초과 dimension 하나는 run이
screen하고 나머지로 진행하므로, 그것만으로 report 전체를 거부하면 성공했을 run을 막고 유일한 해법이
등록된 `total_k_grid` 수정(=diagnostic을 본 뒤의 사후 변경)이 된다. 거부는 **admissible dimension이
하나도 없을 때에만** 하며, 그 조건은 selection 자체가 무효가 되는 조건과 같다.

> **2026-08-04 개정.** 최초 구현은 이 기준을 *선택된* `k_total`에 대한 `FUTILITY_STOPPED` 조건으로
> 두었다. 독립 리뷰 3건이 두 축 모두에서 그것이 틀렸음을 보였다 — 등록된 grid에 적합한 후보가 있어도
> run이 영구 종료됐고, futility 처분의 근거로 제시된 항목 중 둘이 사실과 달랐다(runbook은 exit 10을
> "고쳐서 재시도"로 규정하지 않으며 카테고리 D가 그 반대를 지시한다; durable futility 보고서는 보존한다고
> 서술된 spectrum을 기록하지 않는다). 위 문단이 현재 계약이다.

> **2026-08-07 개정.** 두 번째 적용 지점(비정칙 OOF train fold)을 추가했다. 2026-08-06까지의 계약은
> full-calibration 설계만 심사했고 fold에 국한된 degeneracy는 어떤 guard에도 걸리지 않았다 —
> `lam == 0.0`에서는 `is_full_rank`만 읽혔고(조건수는 계산된 뒤 버려졌다) `lam > 0`에서는 fold 진단
> 자체가 없었다. 소유자 결정으로 `lam == 0.0`에만 적용하는 안을 등록했다. 측정 근거와 기각된 대안(모든
> lambda에 적용)은 위 문단에 있다.

### 10.5 Baselines, metric and inference

family = {additive(null floor), GEARS(published SOTA, GO-graph 사용 — 우리 차별점), CPA(latent-
additive), ID-only, L1(headline)/L2/L3}. **GEARS/CPA는 singles+combo_calibration에만 학습**(sealed
미노출, leakage 차단).

pair $i$, method $M$의 response-space error는
$e_{M,i}=p^{-1}\|\hat\delta_{M,i}-\delta_i\|_2^2$이다. comparator $C$ 대비 paired relative
improvement는 $\theta_{M,C}=1-\overline e_M/\max(\overline e_C,10^{-12})$로 고정한다. headline
primary estimand은 $\theta_{L1,additive}$이며 material margin은 0.05다. 동일 sealed pair
resample에서 각 replicate의 두 mean error를 다시 계산하고, 그 resample을 모든 contrast에 공유하는
10,000회 max-deviation bootstrap으로 simultaneous 95% lower bounds를 계산한다.

- `GI_LEARNABLE_WIN`: headline에서 additive contrast lower bound $>0.05$이고
  {GEARS, CPA, ID-only, L3} 각각의 contrast lower bound $>0$.
- `PARTIAL`: additive lower bound $>0.05$이나 learned-family 조건 실패.
- `NO_DISTINCT_WIN`: additive lower bound $\le0.05$.
- non-finite/missing pair prediction, roster 불완전, provenance/leakage 실패는 `INVALID`;
  해당 pair/method를 사후 제외하지 않는다.

secondary = GI-explained fraction과 구조 복원이며 verdict gate로 사용하지 않고 effect size,
simultaneous interval, chance/null definition과 함께 전부 보고한다.

위 두 성질은 config에 boolean으로 동결한다: `metric.secondary_are_verdict_gates: false`(secondary는
descriptive-only이며 sealed verdict gate가 될 수 없다)와
`inference.shared_resamples_across_contrasts: true`(등록된 max-deviation bootstrap은 replicate마다
하나의 resample을 모든 contrast에 공유한다). 두 값은 loader가 정확히 강제하며 config 변경으로
뒤집을 수 없다.

### 10.6 Two-phase execution and seal

- **Phase 2a (dev, seal 무접촉):** real calibration-role δ/ε + z_g(+ESM) +
  L1/L2/L3·ID-only 적합 + GEARS·CPA 학습 + calibration gene-disjoint OOF relative improvement,
  noise-ceiling·실 $\Phi$ rank 진단. OOF mean relative improvement $\le0$, rank 실패 또는
  measurability floor 실패면 `FUTILITY_STOPPED`, seal은 닫힌다.
- **Phase 2b (freeze + seal-once):** 전 method 동결 → `sealed_double_unseen`+`sealed_single_unseen`
  **1회** 개방 → Δ + 동시추론 + secondary → verdict → report.

seal·run-identity는 TG-K562와 **영구 독립**(§6.3): `artifacts/compose/<run_id>`, composite run_id =
config+Norman data-card(sha256)+sequence-mapping+raw sha256, sealed access 0(2a/futility)→1(2b),
write-once. verdict 2축(method × sealed); "모든 무결성 검증 완료"로 표현하지 않는다(구조적 self-check
한계 명시).
