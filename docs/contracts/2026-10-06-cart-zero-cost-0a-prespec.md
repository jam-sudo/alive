# CART 무비용 트랙 K·P — 0a 사전 명세 (2026-10-06)

> **상태: 0a 사전 명세.** protocol 등록이 아니며, perturbed outcome 접근 승인도 아니다.
> 이 문서는 pilot, δ 측정, 대용량 다운로드보다 **먼저** commit·push해 외부 timestamp를 남긴다.
> 이후 단계의 모든 규칙은 이 문서에 고정된 값과 절차만 쓴다. 바꾸려면 새 사전 명세와 새 시도 기록이 필요하다.
> 1b 항목은 2026-10-06 owner가 일괄 서명했다.
> 기존 claim·verdict·seal은 바꾸지 않는다: TG-K562-v1 COMPLETE, CART-K562-D8-v2 FAIL(E 소모), CART-K562-V3.1 REGISTERED, COMPOSE RELEASE-BLOCKED.
> 근거 문서: [scientific validity contract](2026-09-23-cartographer-scientific-validity.md), [V3.1 addendum](2026-10-04-cart-k562-v3-1-addendum.md), `configs/cart_k562_v3_1.yaml`.

## 1. owner 판정과 서명 대기 항목

**1a. owner 판정 (2026-10-06, 권고에 대한 "진행")**

| 항목 | 판정 | 근거 |
|---|---|---|
| 계약 S5 해석 | **해석 1: 두 predictor 모두 독립 반복이 필요하다** | S5 표 "각자 calibration/held-out 인수 및 독립 replicate/cohort 검증", §3 "모두 통과 필요", S6 "S1–S5 전부 충족". 7항은 개발 순서 조항이므로 인수 기준을 좁히지 않는다. 문언만을 근거로 했다 |
| 진행 범위 | 트랙 K(P1 × VIPerturb-seq K562), 트랙 P(PIE × VIPerturb·10x K562 Flex) | 둘 다 비용이 0이다 |
| 트랙 C(CD4) | 보류. CD4는 받지 않는다 | — |
| GWPS 미읽음 target | 평가 단위로 쓰지 않는다 | D8 "E consumed" 해석 충돌을 피한다 |
| 결과 표기 상한 | P1: S4(단일 독립 검증). PIE: S4와 독립 반복. **S6는 주장하지 않는다** | 해석 1에서 P1의 반복 자료가 없다 |
| 다른 프로젝트 분석 | owner의 다른 프로젝트 분석은 ALIVE 노출로 치지 않는다(2026-10-05 판정). 조건은 결과를 서로 넘기지 않는 것이다 | — |

**1b. owner 서명 완료 (2026-10-06, 11개 항목 일괄 서명)**

| # | 항목 | 서명 내용 |
|---|---|---|
| S1 | 트랙 K 단위 1개(V3.1 `min_units: 2` 대비 편차) | 수용 |
| S2 | 트랙 P 편차: 단위 간 IUT(Bonferroni 대신), 실험별 C_input 예측 | 수용 |
| S3 | 부분 노출 수용: VIPerturb manifest `is_in_filtered_obj` 열람, 10x Flex의 P1 지원 target(상한 74개) δ 측정용 열람 | 수용 |
| S4 | 라이선스(비상업 연구): PIE weights·code, VIPerturb·10x(CC BY 4.0), PIE 학습 자산(1단계에서 확인, 하나라도 금지하면 PIE 팔 미등록) | 수용 |
| S5 | 시도 상한: 트랙마다 1회. futility와 미등록도 센다 | 1회 |
| S6 | 다운로드: PIE 자산(replogle 제외) 약 75 GB, VIPerturb 약 11 GB, 10x Flex(크기는 다운로드 전에 확인). 외장 SSD에 둔다 | 승인 |
| S7 | G-B 멈춤 문턱 0.3, subgroup 판정 (a), V3.1 유용성 기준 재서명 | 수용 |
| S8 | 09-23 범위와 V3 S6 predictor: 유지한다. 트랙 K가 P1·K562 cross-experiment로 그 범위를 잇고, 트랙 P는 별도 protocol로 추가한다 | 유지 |
| S9 | V3.1 on-target 결함(실행 코드가 대상 유전자를 빼지 않음): 트랙 K·P는 고친 사건을 쓴다. V3.1 자체 처리는 별도 결정 기록으로 | 수용 |
| S10 | CART-K562-V3.1 상태: 바꾸지 않는다. 종결은 별도 결정 기록으로 | 유지 |
| S11 | 트랙 P 단독 등록: 트랙 P가 등록되면 트랙 K의 PIE 팔은 기술 보고만 한다 | 수용 |

## 2. 고정 식별자

**predictor**

| 이름 | 고정값 |
|---|---|
| P1 | V3.1 config의 `predictor` 블록 그대로: Arc State ST-HVG-Replogle `fewshot/k562/final.ckpt` sha256 `121ff54db0e6f9f53b2777bbf45139757367ed827a111824213e6bf3777b2618`, adapter sha256 `202c34c736b74885d31485d76dd1296de9a5c3dc0e1d718b929b7cad53e4449e`, estimand `anchored_nontargeting_uniform_56_batch_tokens_R16` |
| PIE | HF `arcinstitute/PIE_replogle_xdataset` revision `f6da9607226139a1040b6992736118c9b5c7c313`, `best_auprc.ckpt` LFS sha256 `e60a1304d074706405939bde94c5edf9851e78070f2d584c6b5025a002ed9a7c`(966,412,013 B), code `ArcInstitute/pie` tag v1.0.0(annotated tag object `83eeca44ea9805fb08955dbdea2bdaf1db5dbfd8`, commit `b26dd17e72ce25b6dbc17568d4f626c8050aea29`). checkpoint의 `train_json_sha256` `8d050f28aebf482135d42f758f6b440e0333b3dec8efc0dddab9dcc3099d4be4`, `evidence_key` `87a01957365041383ac2cbae3a9cf44be6f48e5dbc69ca045f14fa270441d151` |
| PIE 학습 자산 | config가 고정한 revision을 그대로 쓴다. pie_tahoe100m `597d6ded9f9a148331388484ffb193489121c702`, pie_jiang `99242356dfcf58e049d867703c5743df8d1790bf`, pie_arc_vcc_25 `e7dda6065316959958b87583ddf0a15f6e69c37d`, pie_x_atlas_orion `0950c8aa5ce5b33dc9d6f0c5eade3ae445ca0ffb`, pie_sources `cb1aaa4e7655605bdc70a9bd77bbd62016b8c7d7` |
| PIE 제외 자산 | **pie_replogle_nadig_essential는 받지 않는다**(Replogle·Nadig 반응 포함). 이를 뺀 로컬 config로 실행했을 때 evidence key가 `87a01957…d151`과 같아야 한다. 다르면 PIE 팔을 등록하지 않는다 |
| PIE alias | 위 commit의 `src/pie/sources/curated_aliases.yaml`과 `pie_sources@cb1aaa4…`의 source별 `aliases.yaml`(있으면)로 해석한다. 1단계에서 각 sha256을 기록한다. 이 조합으로 위 `train_json_sha256`·`evidence_key`를 재현하지 못하면 PIE 팔을 등록하지 않는다. **유전자 기호 대응:** 트랙 K의 P1↔VIPerturb 대응은 정확한 기호 일치만 쓴다(958개. alias 2개는 쓰지 않는다) |
| PIE split | HF `arcinstitute/PIE_splits` revision `0eeae3789fcc3fbdf26acda1c909e5fe8cecf2cb`. `replogle_xdataset` train 파일 sha256이 `8d050f28…4be4`와 같아야 한다. 검증 split에 K562·VIPerturb·10x 자료가 있으면 PIE 팔은 부적격이다 |

**자료**

| 이름 | 고정값 | 쓰는 파일 |
|---|---|---|
| VIPerturb-seq K562 | Zenodo `10.5281/zenodo.18460279` revision 4, CC BY 4.0 | `genome_wide_binA.RDS` md5 `31d690848cb1d93e04c9bce0c0ad3726`, `genome_wide_binB.RDS` md5 `0b24448645231da466b9059dcc7f3c43`, `genome_wide_binC.RDS` md5 `af9e5908510f6765863d728f5ef18595`, `genome_wide_manifest.txt` md5 `c095c8f2d16136753c22ef5d9b30a22b` |
| VIPerturb 제외 파일 | `genome_wide_filtered.rds`(outcome 기반 필터), `vimentin_screen.rds`(outcome 정렬 세포), `multimodal_cell_line_mixing_pilot.rds` | — |
| 10x K562 Flex | 10x Genomics dataset `16-plex_GEM-X_Flex_1M_human_K562_CRISPR_aggregate`(https://www.10xgenomics.com/datasets/16-plex_GEM-X_Flex_1M_human_K562_CRISPR_aggregate), CC BY 4.0 | 다운로드할 때 모든 파일의 sha256을 **추출 전에** 1단계 기록에 남긴다 |
| GWPS day-8 pilot 자료 | ALIVE가 D8에서 이미 읽은 target(D/C 1,346개와 소모된 E 911개). 미읽음 행은 읽지 않는다 | 로컬 h5ad, D8 기록과 같은 hash |

## 3. 사건과 판정 기준 (V3.1 상속, 차이만 표시)

- **사건:** 질의는 P1이면 τ = ε = 0.2(|h| > 0.2), PIE면 `p_de` ≥ 0.5다. 그 질의 행에서 관측 부호가 예측 부호와 일치하는지 본다. 관측 d = 0은 실패다.
  - **V3.1과 다른 점:** perturbation 대상 유전자와 cis 창(±1 Mb, **GENCODE v46**, MANE Select TSS. 없으면 Ensembl_canonical)의 유전자는 주 사건에서 뺀다.
    on-target 관측 부호는 양성 대조로만 보고한다.
- **관측 척도:** P1은 평균 log1p(CP10k) 차이다. PIE는 target CP10k 평균 − C_ref CP10k 평균의 부호다. guide feature는 분모에서 뺀다.
- **유전자 적격성(outcome-free):** 단위별 C_input 평균 CPM 5 이상.
- **대조군 역할:** batch 단위 안에서 C_ref/C_input/C_audit = 0.4/0.4/0.2.
  - batch 단위: VIPerturb는 RDS 메타데이터의 GEM lane, 10x Flex는 probe-barcode 시료(16-plex), GWPS는 gem_group.
  - 배정은 sha256(f"CART-0a-ctrl-20261006|{dataset}|{barcode}")의 상위 64비트를 2^64로 나눈 값 u로 정한다: u < 0.4이면 C_ref, < 0.8이면 C_input, 나머지는 C_audit.
- **target 적격성:** 단위마다 guide 할당 기준 30 cells 이상(V3.1 `evaluate_where_eligible`).
- **판정 기준(V3.1 값):** bins 10, min_targets_per_bin 30, calibration margin 0.10, operating_budget_on_C 0.10, risk_ucb 0.15, use_lcb 0.30, α 0.05, n_boot 2000.
  - Bonferroni는 단위 안의 구간 전체에 건다.
  - 제품 규칙은 B0 → B1 → ALIVE-L 순서이며, ALIVE-L은 distinct win을 요구하고, 제품 선택은 C에서 한다.
- **ALIVE-L feature:**
  - P1: V3.1 목록에서 State 전용 항목은 그대로 두고 `exposure_stratum`은 P1-test/train으로 바꾼다.
  - PIE: `p_de`, |h|, n_cells, control_noise_sd, control_mean.
- **PIE 질의:** `p_de` ≥ 0.5, 부호는 sign(`lfc_pred`). B1의 h는 ln2·`lfc_pred`, σ는 ln 평균비의 delta-method 표준오차(분산은 C_audit에서).
- **공통 이동 비교자(invariant 11):** 같은 단위의 D target 관측 평균 반응을 모든 E target의 예측 부호로 쓴다.
  비교는 predictor가 고른 행에서, paired target bootstrap(n_boot 2000, 단측 α 0.05)으로 한다. predictor가 유의하게 넘지 못하면 판정 표기를 "PASS; predictor ≤ common-shift"로 한다.
- **subgroup 판정(계약 §3):** N ≥ 30인 subgroup은 calibration margin을 통과해야 한다. subgroup 간에는 Bonferroni를 건다. N < 30이면 "미확립"으로 적는다.
  - 트랙 K: P1-test/train, noise 층.
  - 트랙 P: 실험, noise 층.
  - **noise 층:** 단위별 target C_audit 대조군 noise SD(출력 유전자 평균)의 3분위(하·중·상). outcome-free이며 G-B에도 같은 층을 쓴다.
  - 검정력 계산은 subgroup 판정을 포함한다.

## 4. 노출 기록 (2026-10-06 현재)

- ALIVE: K562 day-6은 TG에서 1,645개를 읽었다. GWPS day-8은 D8에서 2,257개를 읽었다. VIPerturb·10x Flex의 결과 행렬 접근은 0이다.
- 부분 노출:
  - VIPerturb manifest(target별 세포 수, `is_in_filtered_obj`)를 이 작업 세션이 읽었다.
  - 검토 subagent는 그 열을 집계했다(전체 TRUE 6,727, P1-test 958개 중 535).
  - 10x Flex는 feature reference(guide 목록)만 받았다.
- 대응:
  - `is_in_filtered_obj`는 어떤 규칙, 계층, 검정력, feature에도 쓰지 않는다.
  - 세포 수에 의존하는 규칙은 이 문서 값(V3.1 상속)만 쓴다.
  - 검정력 계산의 세포 수 분포는 다운로드 전에는 manifest, 다운로드 후에는 RDS guide 할당을 쓴다.

## 5. 10x Flex 정체 규칙과 봉인 추출

- **정체 규칙(다운로드 전에 이 문서로 고정):** 10x Flex library는 TSS ID 기반의 lncRNA 지향 library다(guide ID 형식 CUFF, ENST, P1P2, NLT).
  - 각 target의 **모든 guide** protospacer를 GRCh38에 정렬한다(GENCODE release는 1단계 기록에 고정).
  - 모든 guide가 그 유전자의 GENCODE 주 TSS로부터 ±500 bp 안에 있고, ±1 kb 안에 다른 유전자의 TSS가 없어야 한다. 하나라도 어긋나면 그 target을 뺀다.
  - "Ignore"·"Non-Targeting" 표지는 그대로 따르며, "Ignore" guide를 가진 세포는 봉인한다.
- **봉인 추출(VIPerturb·Flex 공통):**
  - commit하고 hash를 고정한 비대화형 script로 추출한다. script는 합성 자료로 먼저 시험한다.
  - 내보내는 것은 RNA `counts`와 허용 목록 열(barcode, guide, target, lane·well)뿐이다.
  - `nCount`는 NTC 행만 적재한다. 나머지 열·assay·reduction은 이름만 기록한다.
  - perturbed 세포는 protocol별 봉인 store에 곧바로 쓰며, audit count는 0이다.
- **δ 측정용 열람:** 10x Flex에서는 정체 규칙을 통과한 P1 지원 target(상한 74개)의 행만 δ 측정용으로 연다. 그 목록의 hash를 열기 전에 기록한다.
  나머지 target은 트랙 P 단위로 봉인한다.

## 6. 검정력과 관문 (통일 모형)

- **δ 측정 (평가 단위의 E가 아닌 자료만 사용):**
  - 같은 target에서 GWPS(이미 읽은 30 cells 이상)와 10x Flex의 부호 정확도 차이를 잰다.
  - target별 세포 수는 공통 최소값으로 맞춘다. paired target bootstrap 분포를 쓰고, 0 미만은 0으로 둔다.
  - predictor별로 잰다(P1, PIE).
  - 보조로 TG day-6과 D8 day-8의 P1-test target 차이에 assay 0.1을 더한다.
  - 최종 δ_실측은 두 분포에서 각각 뽑은 값의 max다.
- **가산 요인(실측 불가, 단위별):** VIPerturb 단위 잔여 0.1(repressor, library, Flex 판본, 채취 시점). 트랙 P 모집단 0.1.
- **단위별 δ 합계:** 트랙 K = δ_실측(P1) + VIPerturb 잔여 0.1. 트랙 P의 Flex 단위 = 모집단 0.1 + δ_실측(PIE), VIPerturb 단위 = 모집단 0.1 + δ_실측(PIE) + 잔여 0.1.
  P1은 계층별로 뽑는다: train 계층은 Flex train target에서, test 계층은 max(Flex test target, TG/D8 + assay 0.1)에서 뽑는다.
- **대체:**
  - 정체 규칙 통과 P1 지원 target이 30개 미만이면 Flex 기반 측정을 쓰지 않는다. 이때 실측 성분은 TG/D8 + assay 0.1이다.
  - Flex train target이 10개 미만이면 P1 train 계층 δ는 test 계층 δ + 0.1이다.
  - 측정이 모두 실패하면 요인당 0.1이다(합계: 트랙 K 0.3, 트랙 P Flex 0.3·VIPerturb 0.4).
- **통일 검정력 모형:**
  - (1) pilot 세포를 각 트랙·단위의 target별 세포 수로 subsample한다.
  - (2) 그 깊이에서 label과 feature를 다시 계산한다.
  - (3) logistic p(부호 성공 | feature, n_cells, noise, P1-test/train)를 적합한다.
  - (4) 절편을 옮겨 평균 성공 확률을 δ만큼(확률 척도) 낮추되, 이동 후 평균은 0.5에서 자른다.
  - (5) 새 성공을 뽑는다.
  - (6) 바깥 bootstrap에서 회차마다 δ도 그 분포에서 함께 뽑는다.
  - (7) 제품 규칙 전체(G-B 포함)를 시뮬레이션한다.
  - n_sim 2000, seed 20261006이다. 평가 bootstrap seed는 V3.1과 같이 split seed를 쓴다.
- **관문 (모두 등록 전, outcome 없음):**
  - G-A (i) 평가 가능 target·행 수와 검정력 0.8 이상(통일 모형).
  - (ii) 배선 검사: PIE on-target 예측 부호의 음수 비율 ≥ 0.9.
  - (iii) P1 입력 HVG 결측 ≤ 10%.
  - (iv) NTC ≥ 5,000.
  - (v) 거부 시험: 다른 checkpoint, 다른 vocab, 다른 맥락(트랙 K·P는 `k562` 외 맥락), 다른 gene 축, 미등록 C_input은 모두 거부되어야 한다. 변이 시험으로 확인한다.
  - 하나라도 미달이면 등록하지 않는다(seal 없음, ledger 기록).
- **G-B (등록 뒤, D만 개봉):**
  - noise 상한은 target 안 세포를 hash(sha256(f"CART-0a-half|{barcode}") 짝·홀)로 반분해 층별 부호 일치율 a로 p_half = (1+√(2a−1))/2를 구한다.
    깊이 보정은 p_full = Φ(√2 · Φ⁻¹(p_half))다. 반분의 신호대잡음비를 √2배로 옮긴다.
  - E 조건부 PASS 확률이 0.3 미만이거나 a < 0.5이면 seal 0으로 멈춘다.
  - 멈춤만 할 수 있고, roster·N·임계값은 바꾸지 않는다.

## 7. 트랙별 사항

**트랙 K `CART-K562-VIP-X1` (P1 주 판정, PIE 고정 순서 보조)**
- **target:** P1 지원 ∩ VIPerturb 적격.
- **split:** V3.1 `split_roles`, seed 20260930, D/C/E 30/30/40. 계층은 `p1_support_indicator`로 하되 on-target·cis를 뺀 뒤 계산한다(V3.1 대비 편차).
- **단위:** 1개(V3.1 `min_units: 2` 대비 편차를 owner가 2026-10-06에 수용).
- **다중성:** P1을 α로 먼저 검정하고, P1이 PASS일 때만 PIE를 α로 검정한다. 단, 트랙 P가 등록되면 PIE 팔은 기술 보고만 한다(1b S11).
- **PIE 포함 규칙:** 통일 모형에서 P(P1 PASS ∧ PIE PASS) ≥ 0.8이면 포함한다.
- **기술 비교자 T_GWPS:** GWPS 관측 효과를 예측값으로 쓰는 비교자다. 이미 읽은 행만 쓰고, 판정에는 쓰지 않는다.
- **표기:** "S4 PASS (P1, VIPerturb K562, 독립 단위 1); S5 미충족".

**트랙 P `CART-K562-PIE-X1` (PIE, 두 실험 반복)**
- **단위:** VIPerturb와 10x K562 Flex 2개. GWPS는 쓰지 않는다(§1 D8 판정).
- **T:** P1 지원 밖 ∩ PIE 지원 ∩ 두 단위 모두 30 cells 이상 ∩ 단위별 C_input에서 target 유전자 5 CPM 이상 ∩ Flex 정체 규칙 통과.
- **split:** T를 확정한 뒤(적격성 필터 뒤) 계층 없이 배정한다. u = sha256(f"CART-K562-PIE-X1|{target}") 상위 64비트 / 2^64이고, u < 0.3이면 D, < 0.6이면 C, 나머지는 E다. 두 단위에 같이 쓴다.
- **보정과 판정:** 두 단위의 D/C를 합쳐 보정하고(V3.1 `c_selection_unit: pooled`), 단위마다 판정한다. 둘 다 PASS해야 한다(단위 간 IUT).
  - V3.1 대비 편차 두 가지를 owner가 2026-10-06에 수용했다: 단위 간 Bonferroni 대신 IUT, 예측을 실험별 C_input으로 만드는 것.
- **실험 간 보정:** α 없는 기술 비교자다.
- **표기:** "S4 PASS와 독립 반복 (PIE, K562 두 실험)".

## 8. 실행 순서와 ledger

1. 이 문서를 commit하고 push한다(1b 서명 완료).
2. 다운로드와 1단계(outcome 없음):
   - PIE 자산(replogle 제외)
   - VIPerturb bin A–C와 manifest
   - 10x Flex(sha256 기록)
   - alias·split·GENCODE 고정
   - 정체 규칙 적용
   - 봉인 추출
   - NTC 기반 대조군 분할
3. 1단계 기록(sha256, alias, split, 정체 규칙 결과, δ용 target 목록 hash)을 commit·push한 **뒤** δ 측정과 pilot(이미 읽은 GWPS와 10x Flex의 P1 지원 target).
4. 예측 동결과 G-A(트랙 K·P).
5. 통과한 트랙을 등록한다(spec·config, loop gate spec-review, owner 서명, push).
6. 등록한 모든 protocol의 E는 모든 제품을 동결한 뒤에만 연다. D 개봉 → G-B → C → freeze → E 1회.
7. 보고한다(시도 ledger 포함).

| # | protocol | 상태 |
|---|---|---|
| 1 | D8-v1 | E 개봉 전 종료 |
| 2 | D8-v2 | E 개봉, 전부 FAIL |
| 3 | V3 | 데이터 전 대체 |
| 4 | V3.1 | 등록, 미실행 |
| 5 | CART-K562-VIP-X1 (트랙 K) | 이 사전 명세 |
| 6 | CART-K562-PIE-X1 (트랙 P) | 이 사전 명세 |

## 9. 주장하지 않는 것

- S6, 그리고 계약 해석 1에서의 S5 완료.
- 미학습 perturbation 일반화(트랙 K의 P1-train 계층), 다른 세포주·맥락으로의 일반화.
- 크기 신뢰성, query별 신뢰, gene-set.
- CD4에 관한 어떤 주장.
