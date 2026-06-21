# Virtual Cell 심층조사 보고서 — 블루프린트 구체화 & MVP 실행 결정

> 목적: `virtual-cell-model-blueprint.md`의 첫 MVP("새로운 세포 맥락에서 단일 유전자 억제 24h 후 transcriptome 분포 예측")를 **실제로 시작하기 위한** 데이터셋·모델·split·baseline·지표 결정.
> 방법: deep-research 파이프라인(7개 검색 각도 → 29개 1차 소스 → 주장 추출 → 3표 적대적 검증). 검증 결과 75표 중 단 3표만 단일 반박(killed 없음). 2024–2026 1차 문헌 중심.
> 작성: 2026-06-19.

---

## 0. 핵심 결론 (TL;DR — MVP 실행 권고)

| 결정축 | 권고 | 근거 |
|---|---|---|
| **데이터셋** | **Replogle 2022 genome-scale Perturb-seq** (K562 + RPE1, CRISPRi, 단일유전자) | 단일세포+pseudobulk AnnData 공개, 두 세포주 공유 essential 유전자로 깨끗한 held-out-cell-line split, STATE도 이 데이터(Replogle-Nadig) 사용 [S29,S2] |
| **일반화 축** | **held-out cell line (K562→RPE1)** 우선, held-out perturbation 차순위 | 블루프린트 §5.4의 "unseen cell type" 축, 공유 essential 유전자로 정합 [S29] |
| **출력 단위** | **전체 세포집단 분포** (pseudobulk 평균 아님) | 평균 예측은 mode collapse·metric gaming에 취약, responder/resistant 재현 불가 [S13,S23,S28] |
| **모델 계열** | baseline 통과 후 **flow-matching / OT 분포전이** (CFM-GP·CellFlow·Departures·CellOT) | 파괴적 시퀀싱 → 분포-대-분포 conditional transport가 자연스러운 정식화 [S1,S3,S22,S27] |
| **필수 baseline** | no-change · mean · **additive/Latent-Additive** · linear gene-embedding | 이들이 딥러닝을 일관되게 이김 — 안 이기면 모델/누출/지표 재점검 [S13,S20,S23] |
| **평가 지표** | **PDS + DES + E-distance + weighted-ΔR²** (MAE는 보조, 단독 금지) | VCC 3종 + 분포지표 + mean-baseline을 음수로 만드는 가중지표 조합 [S5,S23,S26] |
| **데이터 위생** | 41% 유전자만 측정 가능 신호 → null 필터; ≥200–500 cells/pert, ~1000 UMI; systematic variation 분리(Systema) | E-test 검정력 + 누출 통제 [S5,S10,S21] |

**한 줄 요약:** 거대 foundation model을 기본값으로 잡지 말 것. **Replogle CRISPRi에서 K562→RPE1 held-out split + 강력한 선형/additive baseline**으로 시작하고, **분포를 직접 모델링하는 flow-matching/OT**를 그 위에 올려 **PDS·DES·E-distance·가중지표 다축**으로 평가하라. 2025년 현재 분야 전체의 합의가 정확히 이 방향이다.

---

## 1. 학술 모델·방법론 (Pillar 1)

### 1.1 핵심 분기: "평균(pseudobulk)" vs "전체 분포"

블루프린트 §5.3의 통찰(파괴적 시퀀싱 → control 집단분포 → perturbed 집단분포의 **조건부 transport**)이 현재 SOTA의 중심 설계 원리로 확립됨. 모델을 이 기준으로 양분:

**(A) 분포를 직접 모델링하는 계열 — 블루프린트 목표에 부합**

| 모델 | 핵심 아이디어 | 일반화 축 | 비고 |
|---|---|---|---|
| **CellOT** (Nat Methods 2023) | input-convex NN의 gradient로 결정론적 OT map $T^*=\nabla g_\theta^*$ 학습, 비대응 control↔perturbed 매핑 | held-out **환자/종**, 동일 perturbation | baseline 대비 MMD·L2에서 ~1 order 우위. 단 "unseen"은 새 perturbation이 아니라 새 donor [S1] |
| **CFM-GP** (2025) | conditional flow matching으로 연속 ODE 분포전이, cell-type embedding 1개로 전 세포유형 예측 | **unseen cell type** (MVP와 정확히 일치) | 3-layer MLP(256)로 매우 가벼움. COVID/PBMC에서 MMD 대폭 개선. **단 완전 novel perturbation은 미검증** [S3] |
| **CellFlow** (2025, Theis/Regev) | flow matching 생성, 이질적 세포집단 분포 생성 | unseen 조건/조합, 발생·organoid까지 | cytokine·약물·KO 다modality, whole-embryo·organoid 확장 [S27] |
| **Departures** (2025) | Neural Schrödinger Bridge(entropy-regularized OT), 이산 유전자활성+연속발현 2모델 joint | **unseen perturbation** (유전자·약물) | Adamson E-dist 0.60 vs GEARS 0.87; Minibatch-OT pairing으로 확장성 [S22,S25] |
| **Meta Flow Matching** (2024) | GNN으로 초기 population 임베딩 → flow를 population에 amortize | **unseen 초기분포/맥락** | Wasserstein manifold 상의 population dynamics [S16] |
| **W1 Neural OT** (2025) | Wasserstein-1 solver로 W2 min-max 회피, 25–45× 가속 | OOD, 고차원 | W2가 고차원에서 붕괴할 때 W1은 안정 [S4] |

**(B) Arc STATE — 산업 표준 참조 모델**
- 2모듈: **SE**(State Embedding, transcriptome→벡터) + **ST**(State Transition, *세포 집합*에 self-attention하는 양방향 transformer). 단일 세포가 아닌 **집합** 단위 → 이질성 모델링 [S2,S15]
- 학습: 관찰 1.67–1.7억 세포 + perturbation 1억+ 세포, 70 세포주 (Tahoe-100M, Parse-PBMC, Replogle-Nadig) [S2,S15]
- 성능: **peer-review 프리프린트는 ">30% discrimination 개선"** 명시 [S15]; Arc 보도자료는 "~50%, DEG 2배" [S2]. ⚠️ **30%(프리프린트) vs 50%(보도) 불일치 — 보수적으로 >30% 채택 권장.** "단순 선형 baseline을 일관되게 이긴 첫 모델"이라 주장 [S2]

**(C) 평균/additive 계열 (= baseline이자 경쟁자)**
- **GEARS** (gene-gene 지식그래프 GNN), **CPA/MultiCPA** (basal+perturbation 분리 autoencoder, dose/조합/시간), **scGPT·Geneformer·scFoundation** (foundation) — 모두 §4의 critique 대상.

### 1.2 결론
- MVP가 "분포 예측"을 목표로 하면 **CFM-GP**(가장 가볍고 cell-type 일반화 일치)가 1차 후보, **CellFlow/Departures**가 분포정확도 상위.
- **STATE는 직접 구현보다 reference baseline**으로 활용(공개 코드, noncommercial).
- ⚠️ 대부분의 분포 모델은 **새 donor/cell-type 일반화는 검증, 완전 novel perturbation 일반화는 약함**(CellOT 명시, CFM-GP 미검증). 블루프린트의 "unseen perturbation" 축은 여전히 미해결 난제.

---

## 2. 상용 제품·기업 (Pillar 2)

| 주체 | 무엇을 제공 | 모달리티 | 성숙도/검증 |
|---|---|---|---|
| **CZI Virtual Cells Platform** | 오픈소스 플랫폼 + 모델 **rBio, GREmLN, TranscriptFormer**; cz-benchmarks(NVIDIA 공동); Billion Cells Project | transcriptome/multi | 2025-10-28 NVIDIA 협력 확대, 페타바이트 규모. 오픈·학술 [S18] |
| **Arc Institute** | Virtual Cell Atlas(>3억 세포), **STATE** 모델, **Virtual Cell Challenge** 벤치마크 | scRNA perturbation | 가장 투명·재현가능(공개 데이터/코드/대회) [S8,S26] |
| **Turbine.ai** | "Simulated Cell" — perturbation 결과·기전 시뮬레이션, ADC payload selector | 기전형 | Bayer/AstraZeneca/Ono 파트너십. ⚠️ **peer-review 검증·정량지표 공개 전무** [S6] |
| **Recursion** | "Predict/Explain/Discover", **MolPhenix**(분자×농도→표현형), MolE(8.4억 분자그래프), Trekseq | **phenomics/imaging**(transcriptome 아님) | 수천억 세포, 주 220만 실험. 데이터 규모 최대급, 단 모달리티 다름 [S24] |
| **Tahoe (Vevo Therapeutics)** | **Tahoe-100M** 데이터셋(1억 세포, 1,100 약물×50 암세포주) | **약물** perturbation | Arc Atlas 첫 기여, 오픈. 단 drug 모달리티 [S7,S8] |
| **NVIDIA BioNeMo** | 모델 호스팅/API 기반. **Evo2**(DNA, 40B, 9조 nt) | DNA/genome (세포 transcriptome 아님) | 인프라 계층. Evo2는 perturbation 모델 아님 [S9] |

**결론:** 학술(Arc/CZI)은 투명·재현가능, **상용(Turbine/Recursion)은 검증 불투명 + 모달리티 불일치**(phenomics/약물). MVP는 **Arc/CZI 오픈 생태계(데이터·벤치마크·STATE)에 정렬**하는 것이 합리적. 상용 제품은 벤치마킹 대상이 아니라 비즈니스 응용 참조용.

---

## 3. 데이터셋·벤치마크 (Pillar 3)

| 데이터셋 | 세포유형 | 모달리티 | 규모 | MVP 적합성 |
|---|---|---|---|---|
| **Replogle 2022** (gwps.wi.mit.edu, PRJNA831566) | K562(~310K), RPE1(~250K) | CRISPRi 유전자KD | genome-scale | ★★★ **최적.** 단일세포+pseudobulk AnnData, 공유 essential 유전자로 K562→RPE1 split, 단일유전자 subset 제공 [S29] |
| **VCC 2025 (H1-hESC)** | H1 배아줄기세포 | CRISPRi (300 pert) | ~300K, ~1000 cell/pert, >50K UMI | ★★★ **모방할 표준 벤치마크.** held-out perturbation, cell_eval(PDS+DES+MAE) [S26] |
| **scPerturb** (Nat Methods 2024) | 44 데이터셋(Norman/Adamson/Replogle 등) | 유전·약물·cytokine 통합 | ~5.7M, 이질적 | ★★ 통합 접근 + **E-distance 지표** 제공 [S5] |
| **Tahoe-100M** | 50 암세포주 | **약물** | ~100M (최대) | ★ held-out-cell-line 약물 확장용(MVP 아님, 유전자KD 아님) [S7] |
| **Norman 2019** | K562 | CRISPRa **조합** | ~100 single+124 double | ★ post-MVP 조합 일반화 축 [S13,S20] |
| **PerturBench** (Altos/UCL) | 6 데이터셋 | 벤치마크 프레임워크 | — | ★★ split/baseline/지표 taxonomy 표준 [S13,S28] |

**핵심 데이터 위생 제약:**
- **41% 유전자만 측정 가능 transcriptome 신호** 생성(Replogle) → 나머지는 사실상 null. **null perturbation 필터링 필수** [S21]
- E-test 검정력: **≥200–500 cells/perturbation, ~1000 UMI/cell** [S5]

**결론:** **Replogle로 학습/개발 → VCC(H1-hESC) 지표·split 철학을 모방 → scPerturb의 E-distance로 분포평가.**

---

## 4. 평가·방법론적 함정 (Pillar 4) — 가장 중요한 경고

### 4.1 딥러닝이 단순 baseline을 못 이긴다 (재확인된 합의)
- **Ahlmann-Eltze et al. (Nat Methods 2025):** foundation model 5종(scGPT·scFoundation·scBERT·Geneformer·UCE) + GEARS·CPA 모두, **unseen 단일 perturbation에서 mean baseline을, 조합에서 additive baseline을 일관되게 이기지 못함** [S20]. ⚠️ 단 제목은 "**아직(yet)** 못 이긴다"이며 "절대 불가"가 아님 — 성숙도 비판 [S20 refute note]
- **PerturBench (Altos/UCL):** 어떤 아키텍처도 명확히 지배하지 못하고, **Latent Additive 같은 단순 모델이 경쟁력+확장성 우위**; CPA*의 adversarial loss·SAMS-VAE의 sparsity 제거가 오히려 성능 향상 [S13,S28]
- **VCC 2025 실제 결과:** 우승은 **하이브리드(딥러닝+고전통계)**(BM_xTVC), pure end-to-end NN은 미달; **거의 모든 모델이 MAE에서 baseline 미만** [S12,S21,S26]
- foundation model 임베딩(scGPT)으로 입력 교체 시 **개선 미미** [S13]

### 4.2 지표 함정 — 단일 지표는 모두 게임 가능
- **mean baseline 역설:** perturbation label 무시하고 전체 평균만 예측해도 현재 지표에서 대부분 딥러닝을 능가 [S23]
- **MAE/MSE:** sparse·저차원 생물 신호를 놓치고 전체 분포만 추종하면 낮은 오차 → **신호 희석** [S23]. VCC는 MAE 페널티를 0으로 cap → 부정확 예측 억제력 상실, 점수 게임 가능(random+변환이 top model보다 높은 점수) [S19]
- **Wasserstein:** 고차원·variance scaling에서 실패; **Energy distance:** 유전자-유전자 의존성 교란 못 잡음 [S11]
- **mode/posterior collapse:** 모든 perturbation에 같은 출력 → RMSE·cosine은 못 잡지만 **rank 지표(PDS류)는 노출** [S13,S28]

### 4.3 처방 — 다축 + 누출통제 + 인과
- **반드시 조합:** PDS(L1 rank 판별) + DES(DE 방향) + **E-distance**(분포) + **Weighted-ΔR²/WMSE**(상수예측은 음수가 되도록 t-score 가중) [S23,S26]. self-prediction(세포 절반→절반) = 현실적 성능 상한 [S23]
- **Systema (Nat Biotech 2025):** "systematic variation"(selection bias·confounder의 일관된 차이)을 분리해야 — 통제하면 겉보기 성능이 급락. unseen perturbation 예측은 표준지표가 시사하는 것보다 훨씬 어려움 [S10]
- **split 누출:** PerturBench taxonomy(covariate/context transfer, combinatorial, inverse-combinatorial). 랜덤 cell split 금지 [S13,S28]
- 블루프린트 §9(인과·aleatoric/epistemic 불확실성)는 이 함정들에 대한 올바른 방어선 — **유지·강화할 것.**

---

## 5. 종합 MVP 실행 계획 (블루프린트 §13 구체화)

```
Phase 1 (데이터·벤치마크):
  - Replogle 2022 다운로드(figshare/SRA PRJNA831566), 단일유전자 subset, AnnData
  - null 필터(측정신호 있는 ~41% 유전자), ≥200 cell/pert, ~1000 UMI QC
  - split: K562(train) → RPE1(test), 공유 DepMap essential 유전자 기준 held-out-cell-line
  - batch/replicate 메타데이터 분리, systematic variation 점검(Systema 방식)

Phase 2 (baseline — 반드시 먼저):
  - no-change, mean(전체 perturbed 평균), Latent-Additive, linear gene-embedding
  - 평가: PDS + DES + E-distance + Weighted-ΔR² (self-prediction 상한 대비)

Phase 3 (분포 모델):
  - 1차: CFM-GP (3-layer MLP velocity field, cell-type embedding) — 가볍고 MVP축 일치
  - 2차: CellFlow / Departures(SB) 로 분포정확도 상향, STATE를 reference로 비교
  - 성공조건: baseline을 PDS·DES·E-distance에서 일관 우위 + RPE1(held-out)에서 유지
        + responder/non-responder 이질성 재현 + 불확실성 보정(epistemic↑ on OOD)
```

**가장 흔한 실패를 피하는 3원칙:** ① 큰 모델부터 만들지 말 것(선형 baseline이 이긴다) ② 단일 지표로 판단 말 것(mean이 게임한다) ③ 랜덤 split 말 것(누출이 성능을 부풀린다).

---

## 6. 신뢰도 & 한계

- **검증 강도:** 29개 1차 소스, 75 검증표 중 반박 3표(모두 단일표, kill 임계 2/3 미달). 대부분 peer-review 또는 Arc/공식 1차.
- **명시적 불일치:** STATE 성능 **>30%(프리프린트) vs ~50%(보도자료)** — 보수치 채택.
- **미해결 난제:** 완전 **novel perturbation** 일반화는 분포 모델들도 대체로 미검증/약함(CellOT는 새 donor만, CFM-GP는 명시적 미검증). 블루프린트의 가장 야심찬 축은 여전히 open problem.
- **프리프린트 주의:** CellFlow·Departures·CFM-GP·Tahoe-100M은 2025 프리프린트(미peer-review).
- **회수 출처:** 이 보고서는 deep-research 워크플로 합성단계 stall 후 검증완료 코퍼스에서 재합성됨(검색·추출·검증 단계는 정상 완료).

## 부록: 주요 소스
S1 CellOT (Nat Methods 2023) · S2/S15 STATE (Arc / bioRxiv 2025.06.26.661135) · S3 CFM-GP (arXiv 2508.08312) · S4 W1 OT (Bioinformatics 2025) · S5 scPerturb/E-distance (Nat Methods 2024) · S6 Turbine.ai · S7/S8 Tahoe-100M · S9 NVIDIA Evo2 · S10 Systema (Nat Biotech 2025, s41587-025-02777-8) · S11 metric failure (bioRxiv 2026) · S12/S26 VCC wrap-up · S13/S14/S28 PerturBench (arXiv 2408.10609) · S16 Meta Flow Matching · S17 VCC Cell perspective (10.1016/j.cell.2025.06.008) · S18 CZI+NVIDIA · S19 VCC metric-gaming critique · S20 Ahlmann-Eltze (Nat Methods 2025, s41592-025-02772-6) · S21 VCC 분석 · S22/S25 Departures (arXiv 2511.13124) · S23 weighted metrics (arXiv 2506.22641) · S24 Recursion · S27 CellFlow (bioRxiv 2025.04.11.648220) · S29 Replogle GWPS (gwps.wi.mit.edu)
