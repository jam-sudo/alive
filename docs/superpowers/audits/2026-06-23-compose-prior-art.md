# COMPOSE-K562-v1 — §6 Prior-Art Gate Audit

> **문서 역할:** spec §6 (prior-art gate) deliverable — novelty가 살아남는 범위 확정 전까지 milestone 활성화 금지
> **대상 설계:** `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md` (§1 claims, §3.2 bilinear operator + rank-condition identifiability, §6 novelty points)
> **작성일:** 2026-06-23
> **gate 성격:** go/no-go. `PRECEDED` 판정 시 코드 착수 전 재설계.

이 audit이 적대적으로 검증하는 **3-요소 novelty의 conjunction**:

1. 2-유전자 perturbation의 **transcriptome-valued (벡터)** 비가산/genetic-interaction(GI) 성분 예측 — scalar drug-synergy가 아님.
2. unseen-pair bilinear interaction operator에 대한 **명시적 identifiability rank 조건** (대부분의 synergy/ML 논문은 식별성을 진술하지 않음).
3. single-perturbation signature로부터 **combo/pair-zero-shot (double-unseen)** 일반화 — two-stage identification (singles에서 $z$ 고정 → 정규화 최소제곱으로 대칭 bilinear $B$ 추정).

판정 기준: 한 편의 선행연구가 위 셋을 **사실상 모두** 함께 하면 `PRECEDED`. 셋이 한 논문에 함께 나타나지 않으면 `NOVELTY_SURVIVES` 또는 `NOVELTY_NARROWED`.

---

## 1. 검색 방법 (queries + databases)

**데이터베이스 / 도구**

- **WebSearch** (general web, 2026-06 기준): 8개 쿼리.
- **PubMed MCP** (`search_articles`, `get_article_metadata`): 3개 conjunction 쿼리 + 3개 metadata fetch.
- **bioRxiv MCP**: keyword 검색 미지원(date/category only)이라 사용하지 않음. bioRxiv 선행은 WebSearch로 커버.
- 1차 source는 가능한 한 원문(저널/arXiv/PMC) 확인. RECOVER는 PubMed metadata abstract + Cell Reports Methods로 출력 형태 직접 확인(저널 full-text는 403; arXiv 전신 2202.04202 + abstract로 교차확인).

**쿼리 (실제 실행)**

WebSearch:

1. `bilinear operator predict genetic interaction transcriptome two-gene perturbation unseen pair`
2. `drug combination synergy tensor factorization bilinear DeepSynergy MatchMaker comboFM`
3. `Costanzo Boone yeast genetic interaction map low-rank matrix structure`
4. `GEARS predict combinatorial perturbation gene expression unseen gene pairs Roohani 2023`
5. `RECOVER bilinear synergy model gene embeddings active learning drug combination Bliss score`
6. `CPA compositional perturbation autoencoder Lotfollahi predict combinations latent additive`
7. `Norman 2019 genetic interaction manifold GI prediction transcriptome combinatorial CRISPRa K562`
8. `identifiability rank condition bilinear interaction model unseen combination low-rank symmetric operator`
9. `GEARS genetic interaction prediction ... non-additive epistasis transcriptome unseen combination identifiability`
10. `two-stage identification single-gene signatures predict pair epistasis expression vector zero-shot 2024 2025`
11. `bilinear epistasis operator expression-valued genetic interaction component identifiable Norman double unseen 2025 2026`

PubMed:

1. `bilinear genetic interaction prediction transcriptome combinatorial perturbation identifiability` → **0 hits** (full conjunction 미색인).
2. `predicting combinatorial perturbation transcriptional response unseen gene pairs non-additive` → **0 hits**.
3. `low-rank genetic interaction matrix epistasis decomposition` → **1 hit** (LRSDec, PMID 26273633).

**해석.** 우리 3-요소 conjunction을 정조준한 PubMed 쿼리 2건이 0 hit. 이는 정확한 결합이 단일 논문으로 색인되지 않음을 시사하는 신호(증명은 아님 — 음성 검색은 부재의 약한 증거). 따라서 인접 family를 leg별로 분해해 가장 가까운 선행을 식별했다.

---

## 2. 가장 가까운 선행연구 표 (closest precedents)

열 의미: **scalar-vs-vector GI** = 출력이 scalar synergy인가 transcriptome 벡터인가 / **identifiability stated?** = unseen-pair operator의 명시적 식별성·rank 조건 진술 여부 / **unseen-pair regime** = 본 적 없는 쌍(both-singles-seen)에 대한 zero-shot 처리 여부.

| method | data / modality | scalar vs vector GI | identifiability stated? | unseen-pair regime | how it differs from us (or doesn't) |
|---|---|---|---|---|---|
| **RECOVER** (Bertin et al. 2023, *Cell Rep Methods*; DOI 10.1016/j.crmeth.2023.100599; arXiv 2202.04202) | drug-pair + cell-line features; viability | **Scalar** (Bliss synergy score, viability). transcriptome 아님 | **No.** bilinear "combination module"는 텐서로 정의되나 식별성/rank 조건 진술 없음 | 부분적 (active learning으로 미평가 쌍 enrich; explicit double-unseen split 보장 아님) | **가장 가까운 단일 위협의 "bilinear" leg.** 우리와 핵심 차이: 출력이 scalar viability synergy이지 벡터 GI 성분 $\varepsilon_{gh}$가 아님. 식별성 정리 없음. 약물(구조 임베딩)이지 CRISPRa 유전자 perturbation 아님. → leg 1·2를 둘 다 비킴 |
| **GEARS** (Roohani, Huang, Leskovec 2023, *Nat Biotechnol*; DOI 10.1038/s41587-023-01905-6) | Perturb-seq (Norman 포함); scRNA-seq | **Vector** (전체 transcriptome 예측; 비가산·GI subtype 명시) | **No (대수적 의미로는).** "identifiability"는 Bayesian uncertainty(confidence) metric이지 operator의 rank/식별 부분공간 조건 아님 | **Yes** (double-unseen 포함; both-genes-unseen에서도 보고) | **가장 가까운 "벡터 GI + double-unseen" leg.** 핵심 차이: GO knowledge-graph 위 GNN(생물 사전지식 의존)이지 singles로부터의 식별가능 bilinear operator 아님. GI를 식별가능한 $\varepsilon=z_g^\top B z_h$로 *격리·식별*하지 않음. 대수적 식별성 조건 부재. spec §1.4 C3가 인용하듯, GEARS의 GO 그래프 도입 자체가 "single signature만으론 unseen combo가 약하다"는 방증 → 우리 claim 2의 사전확률을 낮춤(우리 베팅의 위험을 키우지, 우리를 선점하지 않음) |
| **CPA** (Lotfollahi et al. 2023, *Mol Syst Biol*; DOI 10.15252/msb.202211517) | scRNA-seq drug/genetic combos | **Vector** (latent space 출력) | **No** | **Yes** (unseen combination OOD) | latent superposition이 **additive로 제약** — 비가산 항을 explicit·identifiable operator로 모델링하지 않음. 사실상 우리 L0(additive)에 가까운 비교군. 우리 차별점(식별가능 bilinear $\varepsilon$)을 정조준하는 baseline이지 선행이 아님 |
| **Norman et al. 2019** (Norman et al., *Science*; DOI 10.1126/science.aax4438) | K562 CRISPRa GI Perturb-seq (우리 데이터셋) | **Vector** (GI manifold; GI subtype 분류) + recommender-system 예측 | **No** | recommender-style 보간 (observed 쌍 중심; 식별가능한 zero-shot operator 아님) | 우리 데이터의 출처·GI 분류의 ground truth. GI manifold/recommender는 *기술·보간*이지 single signature로부터의 **식별가능 bilinear pair-zero-shot operator** 아님. 식별성 정리 없음 |
| **Drug-synergy DL family** (DeepSynergy; MatchMaker; comboFM; DeepTraSynergy; TensoGraph 등) | drug-pair + cell-line expression; synergy | **Scalar** (synergy score) | **No** | 일부 leave-combo-out 평가 | comboFM/TensoGraph은 텐서 factorization을 쓰나 출력이 **scalar synergy**. 벡터 GI도, operator 식별성도 없음. leg 1·2를 비킴 |
| **고전 yeast 저랭크 GI / LRSDec** (Wang et al. 2015, *BioMed Res Int*; DOI 10.1155/2015/573956; cf. Costanzo et al. 2016 global GI map, *Science*/Nature Methods) | yeast EMAP/SGA fitness GI matrix | **Scalar** (S-score / fitness GI) | **No** (low-rank+sparse 분해는 *기술적* 구조이지 unseen-pair 식별성 정리 아님) | 결측 impute(transduction)이지 hold-out pair-zero-shot 예측 아님 | "GI 행렬이 근사 저랭크"라는 고전 결과는 우리 §3.2 저랭크 $B$ prior의 **동기**이나, scalar fitness이고 transcriptome 벡터가 아니며 식별가능 operator를 unseen 쌍에 일반화하지 않음 |
| **Bilinear inverse-problem 식별성** (Choudhary & Mitra 2014, "Identifiability Scaling Laws in Bilinear Inverse Problems", arXiv 1402.2637; cf. low-rank lifting 문헌) | 일반 signal processing (blind deconv. 등) | N/A (도메인 무관) | **Yes** (bilinear map의 rank/식별성 조건이 핵심 주제) | N/A | rank-조건 수학 자체는 signal processing에 확립. 우리 §3.2 식별성 논증의 수학적 계보. **그러나 GI/perturbation/transcriptome 예측에 적용된 바 없음** → leg 2의 수학 도구는 선행이나, 우리의 *적용 맥락*(vector GI + pair-zero-shot)은 미선점 |

---

## 3. 살아남는 novelty (좁게 scoped)

위 표에서 어떤 단일 선행도 세 leg를 함께 갖지 않는다. leg별 선점 현황:

- **Leg 1 (벡터 GI).** GEARS·CPA·Norman이 transcriptome 벡터 combo를 예측하므로 "벡터 출력" 자체는 **선점됨**. 우리의 좁은 잔여 novelty는 "벡터 *GI 성분* $\varepsilon_{gh}=\delta_{gh}-(\delta_g+\delta_h)$를 explicit한 식별가능 operator로 *격리·예측*"이다. GEARS는 전체 transcriptome을 예측하되 GI를 식별가능 항으로 분리하지 않고, CPA는 비가산을 explicit하게 모델링하지 않는다.
- **Leg 2 (unseen-pair 식별성 rank 조건).** drug-synergy·perturbation 예측 문헌 어디서도 **진술되지 않음**(RECOVER 포함). 식별성 수학은 bilinear-inverse-problem 문헌(arXiv 1402.2637)에 존재하나 GI/perturbation에 적용된 적 없음. → **이 leg가 가장 강하게 생존.**
- **Leg 3 (singles→pair-zero-shot, two-stage).** GEARS가 double-unseen을 *수행*하나 GO 그래프 의존 GNN이며 two-stage 식별(z fix → linear B)이 아니다. CPA의 OOD combo는 additive-제약이다. → two-stage 식별가능 경로로서의 pair-zero-shot은 **미선점**.

**좁게 정의한 생존 novelty (claim 가능 범위):**

> Norman K562 CRISPRa Perturb-seq에서, 단일-유전자 signature로부터 고정한 per-gene factor $z_g$ 위에서, 2-유전자 perturbation의 **transcriptome-valued 비가산 성분 $\varepsilon_{gh}$를 대칭 bilinear operator $B$로 격리·예측**하되, 그 operator에 대해 **명시적 identifiability rank 조건**($\Phi$의 rank $\ge k(k+1)/2$, 미달 시 식별 부분공간 한정)을 진술하고, **calibration 쌍에서 $B$를 추정해 double-unseen(both-singles-seen, pair-never-seen) 쌍으로 일반화**하는 two-stage 식별 절차. claim 1(식별성/recovery)은 모델 class 가정 하의 수학적 사실 + synthetic known-answer로 한정하며, claim 2(real 일반화)와 한 문장으로 합치지 않는다(spec C3).

이 결합 — **벡터 GI 격리 + 명시적 unseen-pair rank 식별성 + two-stage pair-zero-shot** — 는 검색된 어떤 단일 논문에도 함께 등장하지 않는다.

---

## 4. 판정 (Verdict)

### `NOVELTY_NARROWED`

**근거 (한 문단).** 세 leg가 *개별적으로는* 모두 인접 선행에 닿는다: 벡터 combo 예측은 GEARS/CPA/Norman가, bilinear combination operator는 RECOVER와 텐서-synergy family가, 저랭크 GI 구조는 고전 yeast 문헌이, 그리고 rank-조건 식별성 수학은 bilinear-inverse-problem 문헌이 이미 갖고 있다. 그러나 **세 leg의 conjunction을 함께 수행하는 단일 선행은 발견되지 않았다** — 특히 (a) GI를 explicit한 식별가능 항으로 *격리*해 벡터로 예측하고, (b) unseen-pair operator의 *명시적 rank 식별성*을 진술하며, (c) singles로부터 two-stage로 식별해 double-unseen으로 일반화하는 결합은 미선점이다. PubMed에서 정조준 conjunction 쿼리가 0 hit인 점도 이를 약하게 뒷받침한다. 따라서 milestone은 진행 가능하되, **"transcriptome-valued combo 예측" 또는 "bilinear synergy 모델" 자체를 novelty로 광고하지 않고**, 위 §3의 좁은 결합(벡터 GI 격리 + 명시적 식별성 rank 조건 + two-stage pair-zero-shot)으로만 novelty를 주장하는 **축소된 scope**로 진행한다.

**축소된 scope (정확한 reduced scope, 활성화 시 강제):**

1. **벡터 출력 자체를 novelty로 주장 금지.** GEARS/CPA/Norman가 선점. novelty는 "벡터 *GI 성분의 식별가능 격리*"에 한정.
2. **bilinear combination 모듈 자체를 novelty로 주장 금지.** RECOVER가 (scalar이지만) bilinear 조합을 이미 사용. novelty는 "그 operator의 *명시적 unseen-pair rank 식별성 조건* + transcriptome-valued GI 적용"에 한정.
3. **식별성 수학을 신규 정리로 주장 금지.** rank-조건 식별성은 bilinear-inverse-problem 문헌(arXiv 1402.2637 등)에 존재. 기여는 "그 조건을 GI/perturbation 예측 맥락에 *최초로 명시·적용*하고 Norman 설계행렬의 rank를 보고"하는 데 있음(방법-적용 novelty, 수학 novelty 아님).
4. **RECOVER·GEARS·CPA·Norman을 prior-art로 명시 인용**하고, 우리 차별점(식별가능 bilinear $\varepsilon$ 격리 + rank gate + two-stage pair-zero-shot)을 매 claim마다 대비.
5. **GEARS는 baseline이자 *반대 증거*.** GO 그래프 도입이 "single signature만으론 unseen combo가 약함"을 시사하므로 claim 2의 사전확률은 낮음(spec C3). 따라서 real win(`GI_LEARNABLE_WIN`)은 simultaneous inference로 GEARS/CPA/L3를 *함께* 이길 때만 주장. 못 이기면 정직한 `NO_DISTINCT_WIN`(합성 방법 입증 `METHOD_VALIDATED`는 별도 유지).

**redesign 불필요.** 단일 논문 선점이 없으므로 `PRECEDED`는 아니다. 다만 위 5개 축소 조건을 spec §6 novelty 진술과 §4 verdict 표현에 반영해 over-claim을 차단한 채 진행한다.

---

## 부록 — 인용 출처

PubMed에서 검색된 항목은 PubMed 귀속 및 DOI 링크를 포함한다(According to PubMed):

- RECOVER — Bertin et al. 2023, *Cell Reports Methods* 3(10):100599. [DOI](https://doi.org/10.1016/j.crmeth.2023.100599) (preprint arXiv:2202.04202).
- LRSDec — Wang, Yang, Deng 2015, *BioMed Research International* 2015:573956. [DOI](https://doi.org/10.1155/2015/573956).
- GEARS — Roohani, Huang, Leskovec 2023, *Nature Biotechnology*. [DOI](https://doi.org/10.1038/s41587-023-01905-6).
- CPA — Lotfollahi et al. 2023, *Molecular Systems Biology*. [DOI](https://doi.org/10.15252/msb.202211517).
- Norman et al. 2019, *Science* — GI manifold. [DOI](https://doi.org/10.1126/science.aax4438).
- Bilinear inverse-problem 식별성 — Choudhary & Mitra 2014, arXiv:1402.2637.
- Costanzo et al. 2016 — yeast global GI map (저랭크 GI 동기), *Science*/Nature Methods 계열.

> **무결성 표현.** 본 audit은 검색 가능한 공개 문헌에 대한 *유한·시점 한정* 점검이며 독립적 전수조사가 아니다. 음성 검색 결과(0 hit)는 부재의 약한 증거다. 활성화 후 신규 preprint가 세 leg를 결합하면 §3.2 충돌 처리(보고 → 중단 → reconcile)에 따라 scope를 재평가한다.
