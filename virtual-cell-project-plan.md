# Virtual Cell 프로젝트 실행 계획안 (ALIVE)

> **⚠ SUPERSEDED (2026-07-04) — historical planning doc.** 이 계획안은 K562→RPE1 held-out cell-line
> transfer를 1차 MVP로 제시하지만, 현재 governance에서 그 축은 `CT-RPE1-v1` = **DEFERRED**다. 완료된
> `TG-K562-v1`(sealed verdict `NO_DISTINCT_WIN`)과 활성 `COMPOSE-K562-v1`(Norman K562 CRISPRa, ACTIVE
> 2026-06-30)은 이후 결정이다. authoritative protocol 상태는
> [CLAUDE.md registry](CLAUDE.md#registry)를 따른다. 이 문서는
> pre-pivot 기록으로 보존한다.

> **프로젝트:** 세포 수준 causal world model — 개입(유전자 억제) 결과를 실험 전에 예측
> **기반 문서:** `virtual-cell-model-blueprint.md` (비전), `virtual-cell-research-report.md` (근거)
> **작성일:** 2026-06-19 · **상태:** Phase 0 (목적 정의) 진입

---

## 0. 한 문장 정의

> Control scRNA-seq 분포를 입력받아, **처음 보는 세포주에서 단일 유전자 CRISPRi 억제 후의 transcriptome 세포집단 분포**를 예측하고, 강력한 단순 baseline을 다축 지표에서 일관되게 능가하는 조건부 분포전이(conditional transport) 모델을 만든다.

핵심 정식화: $p(X_{t+\Delta t}\mid X_t, A, C)$ — 평균 벡터가 아닌 **집단 분포**를 예측.

---

## 1. 범위 고정 (블루프린트 §4 설계축 결정)

| 설계축 | 이번 프로젝트의 선택 | 이유 |
|---|---|---|
| 생물학적 맥락 | K562 (학습) → RPE1 (held-out 평가) | Replogle에 공유 essential 유전자 존재, 깨끗한 cross-line split |
| 개입 종류 | CRISPRi 단일 유전자 knockdown | 모달리티 단순, 신호 직접 관측, 공개 데이터 풍부 |
| 출력 modality | RNA (scRNA-seq) | 1차 모달리티, 이후 protein/ATAC 확장 |
| 시간 범위 | 단일 endpoint | MVP 단순화 (temporal은 Phase 5+) |
| 예측 단위 | **세포집단 분포** (+ pseudobulk는 baseline용) | mode collapse·지표 게임 방어 |
| **일반화 축** | **2×2 factorial 그리드**: {perturbation seen/unseen} × {cell line seen(K562)/unseen(RPE1)} | 단일 축이 아니라 격자로 분해 — "처음 보는 perturbation 못 함"과 "cross-line domain shift"를 따로 진단 (§1.1) |
| 활용 목적 | perturbation 반응 예측 → 표적 후보 순위화 | closed-loop의 출발점 |

**비범위 (이번엔 안 함):** 약물/조합 perturbation, time series, 역설계, multimodal, in vivo. → 후속 단계로 명시 이관.

---

### 1.1 일반화 그리드 (2×2 factorial)

일반화를 **단일 축(held-out cell line 먼저, perturbation 나중)이 아니라 2×2 격자**로 본다. 두 축을 처음부터 동시에 돌려, 실패가 "처음 보는 perturbation을 못 맞춘다"에서 오는지 "cross-line domain shift"에서 오는지를 **분해**한다.

| 셀 | perturbation | cell line | 정의 | 난이도 | 매핑(선행연구) |
|---|---|---|---|---|---|
| **A** | seen | seen (K562) | K562 학습 유전자 = 평가 유전자 (in-distribution). self-prediction 상한 근처 | 쉬움 (sanity) | 분포모델 검증된 영역, self-prediction 상한 [S23] |
| **B** | **unseen** | seen (K562) | K562에서 **train 유전자 → 평가 유전자**(held-out perturbation, 동일 세포주) | **어려움 (HARD)** | Ahlmann-Eltze 실패 영역 — mean baseline 못 이김 [S20]; Departures가 도전 [S22] |
| **C** | seen | **unseen (RPE1)** | K562→RPE1, **공유 essential 유전자**(held-out cell line, perturbation은 본 것) | 중간 (상대적 쉬움) | **CFM-GP의 "unseen cell type" 축이 MVP와 정확히 일치 [S3]; CellFlow의 unseen 조건/맥락 전이 [S27]**. ⚠️ CellOT[S1]는 직접 근거 아님 — 검증 축이 held-out **donor/종**이라 cross-cell-line과 구별되는 관련 맥락전이(각주 참조) |
| **D** | **unseen** | **unseen (RPE1)** | unseen pert + unseen line 동시 (둘 다 처음) | **가장 어려움** | 블루프린트 최종 목표 = open problem [S20, 보고서 §6] |

> ※ 각주(셀 C): CellOT[S1]의 검증된 "unseen"은 새 perturbation이 아니라 새 **donor/종**(held-out donor/species)으로, cross-cell-line 일반화와는 *관련되지만 구별되는* 맥락전이다. 따라서 셀 C의 직접 근거에서 제외하고, cross-cell-line 일반화의 직접 매칭 증거는 **CFM-GP[S3]·CellFlow[S27]**로 한정한다.

- **B축(held-out perturbation)이 더 어려운 축.** 처음부터 **진단용(DIAGNOSTIC)**으로 돌리되 **기대치를 낮게** 잡는다 — baseline 우위 자체가 어려운 게 정상(Ahlmann-Eltze 실패 영역). B와 C를 비교해 실패의 출처(perturbation 일반화 불가 vs cross-line shift)를 분리한다.
- **C축이 MVP 1차 합격 목표**(기존 계획 유지), **D축이 블루프린트 최종 목표**(달성 시 stretch).
- **A는 sanity 상한**: A에서조차 baseline을 못 넘으면 데이터·신호·구현부터 점검.

---

## 2. 기술 스택

| 영역 | 선택 | 비고 |
|---|---|---|
| 데이터 | `scanpy`, `anndata` | AnnData 표준 |
| 모델 | `pytorch`, `scvi-tools`(VAE baseline·encoder), `torchcfm`/자체 flow-matching | scvi-tools 스킬 활용 가능 |
| OT/분포 | `POT`(Python OT), `geomloss`(Sinkhorn/MMD/energy) | 분포 지표·OT solver |
| 평가 | 자체 `cell_eval` 호환 하니스 (PDS/DES) + `scperturb`(E-distance) | VCC 지표 정합 |
| 파이프라인 | `nextflow`(원시데이터 처리 필요 시), 아니면 순수 python | nextflow-development 스킬 |
| 추적 | `git`, `wandb` 또는 csv 로깅, `DVC`(데이터 버전) | 재현성 |
| 환경 | `conda`/`uv` + `requirements.txt`, GPU(권장 A100/H100급 1장) | flow-matching MLP은 경량 |

---

## 3. 저장소 구조 (제안)

```
ALIVE/
├─ virtual-cell-model-blueprint.md      # 비전 (기존)
├─ virtual-cell-research-report.md      # 근거 (기존)
├─ virtual-cell-project-plan.md         # 이 문서
├─ data/
│  ├─ raw/                              # Replogle 원본 (gitignore)
│  └─ processed/                        # QC·split 후 AnnData
├─ src/
│  ├─ data/        # 로드·QC·null 계층화·2×2 split(§1.1)
│  ├─ baselines/   # no-change, mean, additive, linear
│  ├─ models/      # cell/perturbation/context encoder, flow-matching transition, decoder
│  ├─ eval/        # PDS, DES, E-distance, weighted-ΔR², bio_recovery(gate), null_specificity, 불확실성
│  └─ utils/
├─ configs/        # 실험 설정 (yaml)
├─ notebooks/      # 탐색·시각화
├─ results/        # 지표·그림·체크포인트 메타
└─ README.md
```

---

## 4. 단계별 실행 계획

### Phase 0 — 목적·셋업 (목표: ~3일)
- [ ] 범위 고정(§1) 확정 및 README 작성
- [ ] 환경 구축(conda/uv, pytorch+GPU, scanpy/scvi-tools/POT/geomloss)
- [ ] 저장소 구조 생성, git init
- **산출물:** 실행 가능한 환경 + 확정된 연구 질문 1개

### Phase 1 — 데이터 & 벤치마크 (목표: ~2주) ★가장 중요
- [ ] Replogle 2022 다운로드 (figshare / SRA `PRJNA831566`, gwps.wi.mit.edu)
- [ ] 단일 유전자 perturbation subset 추출 (K562, RPE1)
- [ ] QC: ≥200–500 cells/perturbation, ~1000 UMI/cell, 품질 필터
- [ ] **null 계층화 (단순 41% 필터 금지):** Replogle 기준 ~41%만 transcriptome-wide 신호 → 나머지 ~59% null. null을 무조건 버리지 말고, 먼저 신호 유무로 나눈 뒤 null을 다시 두 계층으로 분리:
  - **상위(upstream) 분리 — 신호 vs null:** "transcriptome-wide 신호 있음(~41%) vs 없음(~59%)" 판정은 **E-test(분포 수준 유의성 검정)로 결정**. E-test가 가르는 것은 여기까지(=신호 유무)뿐임.
  - **하위(downstream) 분리 — null 내부 (i)/(ii):** null(=신호 없음, ~59%) 안에서 (i)와 (ii)를 가른다. ⚠️ **(i)/(ii) 분리에는 E-test를 쓰지 않는다** — (i)도 (ii)도 모두 signal-null(분포 신호 0)이라 E-test로는 구분 불가(순환논리). 대신 표적 자가 knockdown 효율(target self-KD), 표적 baseline 발현량, 가이드 QC로 판정:
    - (i) **knockdown 성공 but 무반응** = 표적은 발현·억제 성공(self-KD 효율 OK, baseline 발현 충분, 가이드 QC 통과)인데 downstream 반응 없음 → **유효한 zero-effect 라벨** (특이도 평가용 정답)
    - (ii) **knockdown/발현 실패** = 표적 미발현(낮은 baseline) or 가이드 효율 저하로 self-KD 미달 → 검출선 이하(below detection) → **결측/불량**, zero-effect 라벨 아님 (학습·평가에서 제외)
- [ ] **평가용 null 대조세트 구축:** (i) 계층 + non-targeting control(NTC)로 **dedicated null control set** 구성 → Phase 2 특이도/위양성-DE 측정 전용. train/test와 누출 없이 분리
- [ ] **학습 주입 시 균형 필수 (caution):** null을 학습 loss에 그대로 넣으면 "control 그대로 예측"(=no-change) 퇴화로 **mode collapse** 위험. 주입 시 **down-weight / class-balance** 필수. 기본 정책은 **null은 주로 EVAL 용도**, 학습엔 균형 후 소량만
- [ ] **누출 없는 2×2 split (§1.1):** 유전자 집합을 K562 내 train/held-out으로 분할(B·D축용) + 세포주 K562/RPE1 분리(C·D축용) + K562·RPE1 **공유 DepMap essential 유전자**로 C축 정합. batch/replicate를 split 경계와 분리
  - 셀 A(K562 seen-pert) · 셀 B(K562 train→held-out gene) · 셀 C(K562→RPE1 공유 essential) · 셀 D(RPE1 held-out gene) 4개 평가 분할을 **모두** 명세
  - ⚠️ B·D(held-out perturbation)는 처음부터 **진단용**으로 생성하되 합격 기준이 아님(기대치 낮음)
- [ ] systematic variation 점검 (Systema 방식: control-vs-perturbed 체계적 차이 정량)
- **산출물:** `data/processed/` 의 train/val/test AnnData + **null 대조세트(계층 i/ii 태그)** + 데이터 카드 (split 명세는 §1.1 2×2 그리드를 따름)

### Phase 2 — Baseline & 평가 하니스 (목표: ~2주) ★모델보다 먼저
- [ ] **Baseline 4종:** ① no-change(=control) ② mean(전체 perturbed 평균) ③ additive/Latent-Additive ④ linear gene-embedding
- [ ] **평가 지표 구현 (정량 리더보드):**
  - PDS (L1 norm 기반 perturbation 판별 rank)
  - DES (up/down DE 유전자 집합 정확도)
  - E-distance (energy distance, 분포 수준)
  - Weighted-ΔR² / WMSE (상수예측이 음수가 되도록 t-score 가중)
  - 보조: MAE(단독 판단 금지), Pearson-delta
  - self-prediction 상한(세포 절반→절반)
- [ ] **2×2 일반화 그리드 (평가는 셀 단위로 분해해 보고, §1.1):** 축 = {perturbation seen vs unseen} × {cell line seen(K562) vs unseen(RPE1)}
  - **Cell A — K562 · seen-pert (in-distribution):** 가장 쉬운 셀, 하한 sanity
  - **Cell B — K562 · train-genes→test-genes (held-out PERTURBATION, HARD):** Ahlmann-Eltze 실패 영역. **기대치를 낮게** 잡고 **진단(diagnostic)** 으로만 운영
  - **Cell C — K562→RPE1 · 공유 essential 유전자 (held-out CELL LINE, pert seen):** 상대적으로 쉬움, 이번 프로젝트 1차 일반화 축
  - **Cell D — unseen pert + unseen line (둘 다 unseen, 가장 어려움):** 블루프린트 최종 목표
  - **held-out-perturbation 축이 더 어려운 축**임을 명시 → "unseen perturbation을 못 맞히는 것"과 "cross-line domain shift"를 **분리(decompose)** 하는 것이 그리드의 목적
  - 모든 정량 지표·bootstrap CI·bio sanity-gate 합격여부를 **각 셀별로** 보고하여 난이도를 분해. 셀별 기대치(특히 **Cell B는 낮게**)를 명시
- [ ] **EVAL 전용 null-control 세트 (specificity / false-positive-DE):**
  - null perturbation(측정 가능 transcriptome 신호 없는 perturbation)으로 **별도 평가 세트** 구성
  - **specificity 지표:** 모델이 null에 대해 **효과≈0** 을 예측하는지, 그리고 genome-wide로 **허위 DE를 환각(hallucinate)하지 않는지**(false-positive-DE율)를 측정
  - **적용 순서:** baseline에 **먼저** 적용 → Phase 3에서 모델에 **자동 동일 적용**
  - ⚠️ **두 종류의 specificity를 혼동 금지:**
    - (a) **null-perturbation specificity** = null에 대해 genome-wide 허위 DE를 만들지 않음 (여기, EVAL null-control)
    - (b) **bio-recovery specificity** = 실제 TP53 knockdown 하에서 off-pathway 모듈이 ~불변 (아래 sanity-gate 항목)
- [ ] **null ground-truth 층화 caveat (zero-effect 라벨 유효성):**
  - null perturbation은 **생물학적으로 null임이 보장되지 않음** → 다음으로 층화:
    - **(i) knockdown 성공 + downstream transcriptome 반응 없음** = **유효 zero-effect 라벨** → specificity 지표에 사용 가능
    - **(ii) knockdown/발현 실패** (표적 미발현 or CRISPRi guide 효율 저조, 신호가 검출 한계 이하) = **유효하지 않은 zero-effect 라벨** → 사용 금지
  - **stratum (i)만** specificity 지표의 zero-effect ground truth로 사용
- [ ] **null TRAINING-injection caveat (mode collapse 방어):**
  - Replogle 기준 perturbation 중 **~41%만 신호 보유 / ~59%는 null** — 이 ~59% null을 **training loss에 그대로 주입하면** 모델이 degenerate한 "predict control / no-change" 모드로 **collapse** 하도록 강하게 끌림
  - null을 학습에 주입할 경우 **반드시 down-weight / class-balance** 필수
  - **안전한 기본값: null은 주로 EVAL에 사용**(학습에는 미주입 또는 강한 가중 보정) — faithfulness 보장
- [ ] **통계적 유의성 (gain은 점추정 금지):**
  - 모든 지표 gain(PDS/DES/E-distance/weighted)은 **perturbation·seed 단위 bootstrap CI**로 보고 — "baseline 대비 +3%"는 노이즈일 수 있음
  - 판정 규칙: **95% CI 하한 > 0** 일 때만 "baseline 우위"로 인정 (점추정 단독 승리 금지)
  - 다중 비교 보정(여러 지표·여러 모델·여러 그리드 셀 동시 비교 시 BH-FDR)
- [ ] **생물학적 recovery 모듈 (sanity gate, 블루프린트 §8.3):**
  - 검사 항목: ① pathway activity recovery(영향받은 경로 점수 방향성) ② known-target/mechanism recovery(표적 직하류 DE 방향성)
  - **CRISPRi knockdown 정합 예시(knockout 아님):** TP53(p53) **억제**는 p53가 transcriptional **activator**이므로 → 직하류 표적 **down-regulation** 기대: CDKN1A(p21)↓, MDM2↓, BAX↓. ⚠️ **단 K562는 p53-null** → 이 점검은 **p53-WT인 RPE1(Cell C)에서만** 유효. baseline-first(K562)에는 K562에서 기능하는 다른 마커로 대체(§5 #8, §6 참조)
  - **음성 대조(off-pathway invariance):** TP53/p53 축과 **진짜로 독립**이고 generic essential-gene stress 반응에 속하지 **않는** 모듈을 사용해 **~불변** 확인(특이성).
    - ⚠️ ribosome/glycolysis 모듈은 Replogle essential-gene knockdown에서 **광범위하게 반응**하므로 TP53 knockdown의 "불변" 대조로는 **취약** → 사용 회피
    - 예시는 **illustrative-only**: 선택한 음성 대조 모듈이 데이터상 TP53 knockdown에서 실제로 **움직이지 않음을 경험적으로 확인**한 뒤에만 채택
  - **적용 순서:** Phase 2에서 **baseline에 먼저** 통과시켜 "모델이 넘어야 할 생물학적 bar"를 baseline이 설정 → Phase 3에서 모델에 **자동 동일 적용**
  - ⚠️ **이것은 sanity gate이지 ranking 지표가 아님.** 교과서 pathway/GO 일치도로 모델을 *순위화*하면, pathway·network prior를 **입력으로 받은** 모델(GEARS 등)이 공짜로 "생물학적으로 맞아 보이는" 이점 → prior 암기를 일반화로 오인하는 **순환 논리**. 합격/불합격만 판정, 리더보드 점수에 합산 금지
- [ ] baseline 리더보드 확립 → **이 점수(+ 그리드 셀별 bootstrap CI, + 생물학 gate 통과 여부, + null specificity)가 모델이 넘어야 할 기준선**
  - baseline 성능표가 **어느 그리드 셀을 커버하는지 명시**(최소 Cell A·C; Cell B는 진단용 낮은 기대치, Cell D는 최종 목표)
- **산출물:** `src/eval/` 하니스(정량 지표 + 2×2 셀별 분해 + bootstrap CI + `bio_recovery` sanity-gate 모듈 + `null_specificity` false-positive-DE 모듈) + (그리드 셀별·CI 포함) baseline 성능표 + 모델 성공/실패 판정 기준

### Phase 3 — 최소 정방향 분포 모델 (목표: ~3–4주)
- [ ] 아키텍처: `cell encoder` + `perturbation(gene) encoder` + `context encoder` → `conditional transition` → `decoder`
- [ ] perturbation encoder는 **gene embedding/pathway/network** 사용 (임의 ID 금지 → zero-shot 위해)
- [ ] **1차 모델: CFM-GP 스타일** (conditional flow matching, 경량 MLP velocity field, cell-type embedding)
- [ ] **2차 모델:** CellFlow / Departures(Schrödinger Bridge) / CellOT 로 분포정확도 상향
- [ ] STATE를 reference baseline으로 비교(공개 가중치/코드)
- **산출물:** 2×2 그리드(A/B/C/D) 셀별 baseline 대비 성능표 + 학습 곡선 + 분포 시각화
  - **셀 C(held-out cell line)** = 1차 합격 목표: baseline 대비 PDS·DES·E-distance에서 **일관 우위 — 단, perturbation/seed에 대한 bootstrap 신뢰구간으로 통계적 유의성이 입증된 경우에만 "우위" 선언**
    - ⚠️ baseline 대비 점추정 향상(예: ~3%)은 노이즈일 수 있음 → **bootstrap CI(perturbation·seed 재표집)**로 PDS/DES/E-distance 각각의 리더보드 차이가 *통계적으로 유의*한지 검정한 뒤에만 합격 판정. 점수가 *수치적으로만* 높은 것은 합격 아님 (검정 절차는 Phase 2 '통계적 유의성' 항목)
  - **셀 A** = sanity 상한 통과
  - **셀 B·D(held-out perturbation)** = **진단 지표**(기대치 낮음): baseline 미달이어도 실패 아님 — B vs C 비교로 "perturbation 일반화 불가 vs cross-line shift" 분해
  - **셀 D(둘 다 unseen)** = 블루프린트 최종 목표, 달성 시 stretch
  - **생물학적 회복 SANITY GATE (랭킹 지표 아님):** 모든 셀에서 pathway 활성 회복·알려진 표적/기전 회복(블루프린트 §8.3)을 **순위가 아닌 통과/불통과 게이트**로 점검. Phase 2에서 baseline에 먼저 적용(생물학적 하한 설정) → Phase 3에서 모델에 자동 적용. 게이트 임계·표적 셋·음성대조 상세는 Phase 2 '생물학적 recovery 모듈' 참조
    - ⚠️ **circularity 주의:** GO/pathway prior를 *부여받은* 모델(예: GEARS)을 textbook pathway 일치로 **랭킹**하면 prior 암기를 보상 → 일반화가 아님. 따라서 생물 회복은 **랭킹 금지, sanity gate 전용**

### Phase 4 — 이질성 & 불확실성 (목표: ~3주)
- [ ] responder/non-responder, subpopulation proportion 재현 검증
- [ ] aleatoric vs epistemic 불확실성 분리 출력
- [ ] OOD(미학습 맥락)에서 epistemic↑ 보정 확인 (calibration, coverage)
- **산출물:** 이질성·불확실성 평가 리포트

### Phase 5+ — 확장 (후속, 범위 외 명시)
- **조합(Norman), dose(Tahoe-100M), temporal, multimodal(protein/ATAC), 역설계(inverse), lab-in-the-loop** — *이것들만* Phase 5+ 범위
  - ✅ **held-out perturbation(셀 B·D)은 Phase 5로 이관하지 않음.** §1.1대로 **Phase 1부터 진단용(DIAGNOSTIC)으로 상시 실행**한다 — 합격 기준이 아닌 *진단 지표*(기대치 낮음)이며, B vs C 비교로 perturbation-vs-cross-line 실패를 분해한다. 단 **완전 일반화(Cell D) 합격**은 Phase 5+ stretch로 둔다 (즉 perturbation 일반화는 *연기/범위 외*가 아니라 *조기 저기대치 진단*, D-level 성공만 stretch)

---

## 5. 성공 기준 (블루프린트 §13)

MVP가 "성공"하려면 **모두** 충족:
1. ✅ 단순 baseline 4종을 **PDS·DES·E-distance에서 일관되게** 능가 (MAE 단독 아님)
2. ✅ baseline 대비 우위가 **통계적으로 유의** — perturbation/seed 단위 **부트스트랩 신뢰구간(95% CI)이 0을 넘지 않음**. "baseline +N%" 점추정만으로는 불충분(노이즈일 수 있음)
3. ✅ 학습에서 제외한 **RPE1(held-out cell line)** 에서 성능 유지
4. ✅ **2×2 일반화 그리드** 전체를 측정: {pert seen↔unseen} × {line seen(K562)↔unseen(RPE1)}. **난이도 순서를 명시**한다:
   - **Cell A** = K562·seen-pert (in-distribution): **필수 통과** (가장 쉬움, 실패 시 MVP 무효)
   - **Cell C** = K562→RPE1·공유 essential(line만 unseen, pert seen): **EASIER → 1차 성공축**
   - **Cell B** = K562 train-genes→test-genes(held-out pert, line seen): **HARDER → 진단축** (Ahlmann-Eltze 실패 regime, 기대치 낮게)
   - **Cell D** = pert·line 둘 다 unseen: **HARDEST = 블루프린트 최종 목표**
   - 즉 **A(필수) < C(1차 성공축, 더 쉬움) < B(진단축, 더 어려움) < D(최종 목표, 가장 어려움)**. B/D는 실패해도 MVP 무효 아님 — 어느 축에서 깨지는지 **분해 보고**가 성공 조건
5. ✅ **특이성(specificity):** null perturbation(검증된 zero-effect = "KD 성공했으나 하류반응 없음" stratum(i))에서 **허위 DE를 만들지 않음** — null 평가셋의 **false-positive-DE rate / DE 특이성 지표**가 baseline 수준 이하
6. ✅ 평균뿐 아니라 **반응 이질성**(responder/non-responder) 재현
7. ✅ 예측 불확실성이 실제 오차와 **보정**됨
8. ✅ **생물학 sanity gate 통과** (랭킹 아님): 알려진 표적/메커니즘·pathway 방향성 회복. **이 게이트는 Phase 2 평가 하니스에 구현하여 baseline에 먼저 적용해 바를 세우고, Phase 3에서 모델에 자동 적용**한다(→ §4 Phase 2/3). baseline이 세운 생물학 바를 모델도 **최소한 동등하게** 충족.
   - **방향성(추상 원리, 셀라인 무관):** p53은 전사 **활성화 인자**이므로 CRISPRi로 TP53 KD → p53 활성표적(CDKN1A/p21·MDM2·BAX) **하향**, 무관 pathway는 ~불변. *(KO 아닌 KD임에 유의)*
   - **실행 예시(셀라인 한정):** 단, **K562는 p53-null**이라 이 표적-하향 반응을 보일 수 없다. 따라서 위 TP53→p21/MDM2/BAX 하향 점검은 **p53 야생형 held-out 라인 RPE1에서만** 평가한다. baseline-first(K562) 적용 단계에서는 **K562에서 기능적으로 발현·작동하는 유전자**(검증된 하류 전사 결과가 있는 표적)로 마커를 대체한다.
   - **마커 선정 단서(셀라인별):** sanity-gate 마커 유전자는 **해당 라인에서 실제로 발현·기능하는 유전자**여야 한다 — 즉 그 perturbation이 **null-stratum (i)**(on-target KD 확인 **AND** 실재하는 하류 반응 존재)에 속해야 하며, 테스트 라인에서 사실상 null인 표적(예: K562의 TP53)은 마커로 쓰지 않는다(§6 null 층화 행 참조).
9. ✅ (확장) 모델 선택 후보가 무작위/기존 대비 높은 hit rate

> ⚠️ baseline을 못 이기면 → 모델 키우기 전에 **데이터 누출·신호 크기·split·문제정의**부터 점검 (분야 1번 교훈).
> ⚠️ 생물학 sanity gate는 **합격/불합격 판정용이며 순위 결정에 쓰지 않는다** — pathway/GO prior를 주입받은 모델(예: GEARS)을 유리하게 만들어 prior 암기를 보상하는 순환논리가 되기 때문(§6 참조).

---

## 6. 리스크 레지스터

| 리스크 | 영향 | 완화 |
|---|---|---|
| 딥러닝이 선형 baseline을 못 이김 (분야 공통) | 높음 | baseline 먼저 구축, 다축 지표, 가중지표로 mean-게임 차단 |
| 지표 게임 / metric collapse | 높음 | PDS+DES+E-dist+weighted 조합, self-prediction 상한, random 변환 sanity check |
| 데이터 누출 (batch/perturbation 혼입) | 높음 | PerturBench split taxonomy, Systema로 systematic variation 분리 |
| **baseline 우위가 노이즈(허위 유의)** — "+3%" 점추정이 통계적으로 무의미 | 높음 | perturbation/seed 단위 **부트스트랩 CI**, 다중 seed, PDS/DES/E-dist 각각 CI 동반 보고 (성공기준 #2) |
| **null에 허위 DE 환각(특이성 실패)** — 효과 없는 perturbation에 가짜 차등발현 생성 | 높음 | 전용 **null 평가셋**으로 false-positive-DE rate 측정, baseline과 비교. zero-effect 라벨은 stratum(i)="KD 성공 but 무반응"만 사용(아래 행 참조) |
| **생물학 검증의 순환논리** — pathway 일치도를 랭킹에 쓰면 prior(GO/network) 주입 모델(GEARS류)을 보상=prior 암기 보상 | 중간 | pathway·known-target 회복은 **sanity gate(합격/불합격)로만** 사용, **순위 결정 금지**. **→ Phase 2 하니스에 구현, baseline에 먼저 적용해 바를 세운 뒤 Phase 3 모델에 자동 적용**(§4). 마커 유전자는 **테스트 라인에서 기능적으로 발현되는 것**만 선정(예: K562는 p53-null이므로 TP53 예시는 p53-WT인 RPE1에서만 적용; 성공기준 #8) |
| **"왜 실패했는지 모름"** — held-out에서 깨졌을 때 원인 미분리 (unseen-pert 무능 vs cross-line 도메인시프트) | 중간 | **2×2 그리드**로 분해 (A/B/C/D, 난이도 A<C<B<D). Cell B(held-out pert)=HARDER 진단축으로 격리, Cell C(공유 essential, line만 unseen, EASIER)와 대조해 원인 귀속 |
| null perturbation 다수(59%) | 중간 | E-test 사전 필터(학습용, §4 Phase 1). **학습에 null 주입 시 mode collapse(=control 예측 퇴화) 위험** → down-weight/class-balance 필수, null은 **주로 EVAL용**으로 한정. **EVAL용 null 셋은 §4 Phase 1의 학습용 E-test 필터로 버려지지 않고 별도로 보존되는 분리된 셋**(특이성 평가 전용) |
| **null의 zero-effect 라벨 오염** — null이 생물학적으로 진짜 null이 아닐 수 있음 | 중간 | null을 stratum (i)KD성공·무반응 / (ii)KD실패·표적 미발현·가이드 비효율(검출한계 이하)로 층화. **(i)만 zero-effect 정답 라벨**로 사용. 이 층화는 sanity-gate 마커 선정에도 적용(라인에서 (i)에 드는 표적만 사용; 성공기준 #8) |
| held-out **perturbation** 일반화 미해결 (open problem, Ahlmann-Eltze 실패 regime) | 중간 | 1차 성공축은 cell-line(Cell C)로 한정, held-out pert(Cell B)는 **진단축**으로 기대치 낮게 운영, 완전 일반화(Cell D) 합격은 Phase 5+ stretch |
| 프리프린트 의존(CFM-GP 등 미검증) | 중간 | reference로 STATE/CellOT(peer-review) 병행 |
| 컴퓨트 비용 | 낮음 | flow-matching MLP은 경량, GPU 1장으로 가능 |

---

## 7. 즉시 다음 액션 (Phase 0→1)

1. 환경 구축 + 저장소 스캐폴딩
2. Replogle 2022 데이터 다운로드 & 1차 탐색 (notebook)
3. QC·null 계층화(i/ii)·2×2 split(A/B/C/D, §1.1) 구현 → `data/processed/` + null 대조세트 생성
4. (병행) baseline 4종 + 평가 하니스 골격(2×2 셀별 분해 + bootstrap CI + null_specificity + bio_recovery gate) 작성

---

### 부록: 핵심 참조
- 데이터: Replogle 2022 (gwps.wi.mit.edu, SRA PRJNA831566) · VCC H1-hESC · scPerturb
- 모델: CFM-GP(arXiv 2508.08312) · CellFlow(bioRxiv 2025.04.11.648220) · Departures(arXiv 2511.13124) · CellOT(Nat Methods 2023) · STATE(bioRxiv 2025.06.26.661135)
- 평가/함정: Ahlmann-Eltze(Nat Methods 2025) · PerturBench(arXiv 2408.10609) · Systema(Nat Biotech 2025) · scPerturb E-distance(Nat Methods 2024) · weighted metrics(arXiv 2506.22641)
- 상세 근거: 동일 디렉터리 `virtual-cell-research-report.md`
- ※ 본 문서의 `[S#]` 인용 키(예: [S1]·[S20]·[S23])는 `virtual-cell-research-report.md` 부록의 소스 번호를 가리킨다. 핵심 매핑: [S1] CellOT · [S3] CFM-GP · [S20] Ahlmann-Eltze(Nat Methods 2025) · [S22] Departures · [S23] weighted metrics · [S27] CellFlow.
