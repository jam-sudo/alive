# COMPOSE — 식별가능한 Interaction-Composition Operator (Epistasis) Design

> **문서 역할:** milestone의 scientific claim 계약
> **상태:** **ACTIVE (Phase 2)** — owner 승인 2026-06-23. Phase 1 완료(method `METHOD_VALIDATED`); §9 prerequisite 충족(prior-art §6.1=NOVELTY_NARROWED, 데이터 CC BY 4.0, Phase-1 gate). Phase-2 pre-registration은 §10 + `configs/compose_k562_v1_phase2.yaml`.
> **개정일:** 2026-06-23
> **protocol 이름:** `COMPOSE-K562-v1`
> **선행 milestone:** `TG-K562-v1` (COMPLETE, verdict `NO_DISTINCT_WIN`; 본 milestone은 그 결과에 소급 주장하지 않음, seal 영구 독립 §6.3)

---

## 0. 문서 역할, source-of-truth, 활성화 prerequisite

본 문서는 **조합 perturbation의 비가산(genetic-interaction) 성분을 식별가능한 composition
operator로 예측**하는 차기 milestone의 과학 계약 *설계안*이다. CLAUDE.md(safety/governance) 하위,
milestone claim 도메인의 최상위 문서로 의도되나, **아직 활성 protocol이 아니다.**

이 milestone은 다음이 모두 충족되기 전까지 활성화하지 않는다(§9):

1. owner 승인
2. 별도 versioned config (split·thresholds·seeds·metrics 확정)
3. **prior-art gate 통과**(§6) — novelty가 살아남는 범위 확정
4. **데이터 survey gate**(§2.1) — combo 데이터 power 현실 확정
5. `TG-K562-v1` seal과 독립된 신규 seal·run-identity·audit lifecycle
6. adequate sample-size / detectable-effect 분석(§2.4)

`COMPOSE-K562-v1` seal은 `TG-K562-v1` seal과 **교체 불가**다(CLAUDE.md §6.3). 하나의 run ID·audit·
report가 두 seal을 동시에 대표할 수 없다.

본 milestone은 다음 durable finding 위에 선다([[alive-operator-design-incremental]]):
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
- `secondary_sealed` — single-unseen, both-seen (보고용).

그래프 제약: GI 그래프를 분할해 test-쌍 유전자를 training combo에서 격리한다. 이 격리가 power를
제한한다(§2.4).

### 2.4 Pre-check gates (사전등록, fit 전, development 단계)

- **Power gate.** valid double-unseen 쌍 수·쌍당 cell 수 → additive-vs-model 대비의 detectable
  effect. 미달 시 **headline을 가장 잘-powered된 regime(예: single-unseen)으로 강등**하고
  double-unseen은 exploratory로 보고한다(§14.2 sample-size 분석).
- **Measurability / noise-ceiling gate.** split-half(또는 replicate) 추정기로 $\varepsilon$의
  noise floor와 추정가능 분산(천장)을 산출·보고한다. 이 gate는 `combo_calibration`/unsealed
  development pairs 또는 outcome-independent cell-count metadata만 사용한다. `sealed_double_unseen`
  및 `secondary_sealed`의 expression/outcome을 사용해 noise ceiling을 추정하지 않는다. 신호 ≈
  noise면 **FUTILITY_STOPPED**(§4), 합성 결과를 deliverable로, seal은 닫힌 채 종료.
- **Rank gate.** calibration 설계행렬 $\Phi$(§3.2)의 rank를 보고; 미달이면 식별 부분공간을
  명시하고 그 밖의 double-unseen 예측은 주장하지 않는다.

### 2.5 Seal (신규·독립; §6.3)

`sealed_double_unseen`(및 secondary) outcome은 model/method freeze 후 **정확히 1회** 개방한다.
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

ESM는 bolt-on이 아니라 **고정 입력 factor**로 재도입한다([[cartographer-mvp-built-merged]]의 OOF
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

쌍별 $\hat\delta_{gh}$의 응답공간 오차. 핵심 = **additive 대비 paired error reduction**
$\Delta=\text{err}_{\text{additive}}-\text{err}_{L1}$ (쌍-level). additive가 큰 효과를 이미 잡으므로
$\Delta$는 **비가산 성분만 격리** → metric gaming 방지. GI 부분공간에서 별도 보고. noise-ceiling
(§2.4)으로 정규화한 "설명한 GI 분산 비율"을 2차로 보고.

### 4.3 Scientific event 위계 (CARTOGRAPHER 교훈 반영)

- **(real 1차)** double-unseen(또는 강등된 powered regime)에서 $L1$이 additive를 쌍-level
  bootstrap 95% CI 하한 > 사전등록 material margin으로 이김.
- **(비교, simultaneous)** $L1$ vs learned family{GEARS, CPA, ID-only, L3}를 **family-wise
  동시추론**으로만 우위 주장(사후 최강 comparator 선택 금지).
- **(구조, 2차)** held-out 쌍의 GI 부호/class 복원 > chance(등록 metric·chance 기준).

### 4.4 Known-answer metric tests (§13.5)

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
run 내부 자기검증이며 독립 audit이 아님을 명시한다([[cartographer-mvp-built-merged]] 교훈).

---

## 5. Phasing (I5; §15 최소 falsifying 실험)

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

CLAUDE.md §11(write-once run identity)·§12(repo conventions)·§14(compute) 전부 적용. 기존
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

활성화 시 CLAUDE.md §4 protocol registry에 본 protocol을 등재하고, 현재 결과에 소급해 주장하지
않는다.

---

## 10. Phase-2 활성화 & pre-registration (2026-06-23, owner-approved)

§9 prerequisite 충족으로 `COMPOSE-K562-v1`을 **ACTIVE (Phase 2)**로 활성화한다. exact 값은
`configs/compose_k562_v1_phase2.yaml`가 source-of-truth(CLAUDE.md §3.1); 본 절은 claim·정직성
계약을 고정한다.

### 10.1 Headline regime — marquee이되 underpowered로 사전등록

Phase-1 gate(실 Norman)는 **measurability를 강하게 통과**(split-half ε corr 0.868)했으나 **power는
marginal**(double-unseen ≈ 22쌍, seed 12–27, median 22). win 조건(additive 격파 + family
동시추론)은 CARTOGRAPHER가 n=247에서도 못 넘긴 바, n≈22에서는 band가 ~3.3× 넓어 **거의 확실히
인증 불가**. 따라서:

- **double-unseen = marquee headline**(owner 결정)이되, **"underpowered, NO_DISTINCT_WIN이 *예상*
  결과이며 방법을 falsify하지 않는다"를 사전등록**한다.
- **single-unseen(~68) = powered secondary** — real win이 통계적으로 *가능*한 regime. 두 regime
  모두 power와 함께 보고(§10.4).

### 10.2 Value-robust 계약 (real null에도 milestone 가치 유지)

double-unseen이 `NO_DISTINCT_WIN`이어도 산출물은: (a) `METHOD_VALIDATED`(합성 식별가능성 = §6.1
narrowed novelty의 실제 기여), (b) **학습가능 GI 특성화**(noise ceiling 0.868, calibration/
single-unseen에서 bilinear-from-singles가 잡는 GI 양), (c) single-unseen powered 결과. milestone은
double-unseen 단일 인증에 좌우되지 않는다.

### 10.3 고정 split & 식별 제약

split seed = **11 a priori**(count로 선택하지 않음; 단일 sealed partition). rank 조건
`|Cal| ≥ k(k+1)/2`, `|Cal|≈41` → `k_grid=[4,6,8]`. calibration **gene-disjoint OOF**로 k·λ 선택
(sealed regime과 동일 난이도). both-seen test는 보류(|Cal| 잠식 → rank floor 위협).

### 10.4 Baselines·metric·inference (roster outcome 전 고정)

family = {additive(null floor), GEARS(published SOTA, GO-graph 사용 — 우리 차별점), CPA(latent-
additive), ID-only, L1(headline)/L2/L3}. **GEARS/CPA는 singles+combo_calibration에만 학습**(sealed
미노출, leakage 차단). primary metric = additive 대비 Δ(δ_gh, response-space), **material margin =
상대오차 감소 5%**; secondary = GI-explained(noise-ceiling 정규화)·구조 복원. 동시추론 =
max-deviation bootstrap(`alive.eval.bootstrap` 재사용), family-confidence 0.95.

### 10.5 2-phase 실행 & seal

- **Phase 2a (dev, seal 무접촉):** real δ/ε + z_g(+ESM) + L1/L2/L3·ID-only 적합 + GEARS·CPA 학습 +
  dev 지표·noise-ceiling·rank 진단. **futility checkpoint**(dev Δ 미달 / rank 실패 / measurability
  실패 → `FUTILITY_STOPPED`, seal 닫힘).
- **Phase 2b (freeze + seal-once):** 전 method 동결 → `sealed_double_unseen`+`sealed_single_unseen`
  **1회** 개방 → Δ + 동시추론 + secondary → verdict → report.

seal·run-identity는 TG-K562와 **영구 독립**(§6.3): `artifacts/compose/<run_id>`, composite run_id =
config+Norman data-card(sha256)+sequence-mapping+raw sha256, sealed access 0(2a/futility)→1(2b),
write-once. verdict 2축(method × sealed); "모든 무결성 검증 완료"로 표현하지 않는다(구조적 self-check
한계 명시).
