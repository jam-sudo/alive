# CART 무비용 트랙 PG — 0b 사전 명세 (2026-10-06)

> **상태: 0b 사전 명세(서명 대기).** protocol 등록이 아니며, perturbed outcome 접근 승인도 아니다.
> PIE pilot, 검정력 계산, Gasperini 발현 자료 다운로드보다 **먼저** commit·push한다.
> 0a([사전 명세](2026-10-06-cart-zero-cost-0a-prespec.md), [1단계 기록](evidence/2026-10-06-cart-zero-cost-step1-record.md))의
> 규칙을 상속하며, 여기 적은 차이만 바뀐다. 0a의 트랙 K·P 판정(둘 다 미등록)은 바꾸지 않는다.
> 서명 전 독립 검토에서 중대한 결함 7개가 나왔고 모두 반영했다(2026-10-06).

## 1. 배경과 범위

- **0a 결과:**
  - 트랙 P는 10x Flex 정체 규칙에서 탈락했다(기록 E).
  - 트랙 K는 G-A에서 탈락했다(기록 H).
- **P1 반복 불가:** P1의 무비용 독립 반복은 산술적으로 불가능하다.
  - Gasperini에서 평가 가능한 P1 target은 87개다(산출은 기록 I). C는 약 26 target이라 bin 최소 30을 못 채운다.
  - VIPerturb 단위는 P(PASS) ≈ 0이다.
  - 따라서 해석 1(owner 판정 2026-10-06)에서 **S6는 이 경로로 도달할 수 없다.**
- **owner 판정(2026-10-06):** "PIE 한정 0b 진행".
- **결과 표기 상한:** "S4 PASS (PIE, VIPerturb K562) 및 고MOI 배경 평균 효과에서의 재현 (Gasperini K562)".
  - 이것을 계약 S5의 "독립 반복"으로 인정할지는 T6에서 owner가 정한다. S6는 주장하지 않는다.

## 2. 트랙 PG `CART-K562-PIE-X2`

**predictor:** PIE. 고정값은 0a §2와 같다(HF revision, checkpoint sha256, code tag, train.json·evidence key, 학습 자산, replogle_nadig 제외, alias, split).

- 1단계에서 evidence key를 replogle 디렉터리 **없이** 재현하지 못하면 등록하지 않는다.

**단위 2개:**

| 단위 | 자료 | batch 단위 |
|---|---|---|
| U1 | VIPerturb-seq K562 genome-wide(0a §2 고정 파일, 기록 G의 봉인 store) | `sample`(기록 G) |
| U2 | Gasperini et al. 2019 at-scale screen, GEO GSE120861(dCas9-KRAB, 고MOI) | 10x 채널(lane). cell ID의 sample 접미사에서 뽑으며, 추출 방식은 1단계 기록에 남긴다 |

- **U2 쓰는 파일:** `GSE120861_at_scale_screen.exprs.mtx.gz`, `.cells.txt.gz`, `.genes.txt.gz`, `.phenoData.txt.gz`, `GSE120861_grna_groups.at_scale.txt.gz`.
  - sha256은 다운로드 즉시, 추출 **전에** 1단계 기록에 남긴다.
- **U2 쓰지 않는 파일:** `all_deg_results.*`, `gene_gRNAgroup_pair_table.*`, `*pilot*`, `50k_reference_cells.rds`, `*_normalized_tpms.tsv`, `zero_inflated_outlier_genes_*`, `at_scale_screen.cds.rds`.
- **U2 봉인 추출:** 0a §5를 따른다.
  - exprs와 phenoData는 commit하고 hash를 고정한 비대화형 script로 추출한다. script는 합성 자료로 먼저 시험한다.
  - 허용 목록 열은 barcode, guide 할당, guide 수, batch뿐이다.
  - 그 밖의 phenoData 열(세포별 UMI, size factor, mito 비율 같은 발현 유래 값)은 이름만 기록한다. 대조 세포가 아닌 행의 그런 값은 적재하지 않는다.
  - target 세포는 `gasperini_at_scale` 봉인 store에 곧바로 쓰며 audit count는 0이다.
  - exprs가 정수 counts가 아니면 트랙을 멈춘다.
- **이미 노출된 것(기록 I):**
  - U2: `grna_groups.at_scale`(설계)과 `genes.at_scale`(측정 축)만 읽었다. ALIVE의 U2 결과 노출은 0이다.
  - 논문과 보충표는 이 작업 세션에서 열지 않았다. 다만 작성자(Claude)의 사전 지식에 출판 내용이 들어 있을 수 있다.

## 3. U2 고MOI 처리(outcome 열람 전에 고정)

- **guide 할당:**
  - phenoData에 게시된 세포별 guide 할당을 그대로 쓴다. 열 이름은 1단계에서 이름만 보고 고정하며, 값 분포는 보지 않는다.
  - 세포별 guide 할당 열이 없으면 자체 호출을 하지 않고 트랙을 멈춘다(미등록).
- **표지(설계 표 `grna_groups` sha256 `40e996f0…da82`의 정확한 문자열):**
  - TSS group: 이름이 `_TSS`로 끝나는 group
  - 양성 대조: `pos_control_`로 시작하는 group
  - 비표적: `scrambled_*`, `random_*`
  - 나머지(`chr*` enhancer, `bassik_mch`)는 배경 guide다.
- **target 세포:** target T의 TSS group guide를 하나 이상 갖고, **다른 TSS group guide와 `pos_control` guide는 하나도 갖지 않은** 세포다. 따라서 한 세포는 많아야 한 target에 속한다.
- **대조 세포:** TSS group guide와 `pos_control` guide를 모두 갖지 않은 세포다.
  - 역할 분할은 0a §3의 hash 규칙(`dataset` = `gasperini_at_scale`)으로 C_ref/C_input/C_audit = 0.4/0.4/0.2.
- **관측:** target CP10k 평균 − 맞춘 C_ref CP10k 평균의 부호다.
  - C_ref는 batch × guide 수 층 안에서 맞춘다.
  - guide 수 층은 batch 안 대조 세포 guide 수의 4분위로 정하고, target 세포의 층 분포로 가중한다.
  - guide 수는 guide 할당 메타데이터에서만 센다.
  - 측정량은 "고MOI 배경 위의 평균 효과"이며, 이를 판정 표기에 명시한다.
- **정체:**
  - 각 TSS group의 spacer 2개가 모두 0a §5 정체 규칙(GRCh38 정확 정렬, 주 TSS ±500 bp, ±1 kb 안 다른 TSS 없음)을 통과해야 한다.
  - spacer는 모두 20 nt이지만 3′ 말단 1 nt는 게놈 서열이 아니다(기록 I: 정확 정렬 244 → 3′ 1 nt를 자르면 730/762). 그래서 **3′ 1 nt를 자르고 19 nt를 정렬**한다. 서명 전에 설계 정보만으로 확정했다.
  - 이 규칙은 서명 전에 적용해 두었다(기록 I). 통과 188/365, P1 지원 밖 125.

## 4. ID 대응, 대상 집합 T, split

- **ID 대응:**
  - U2 TSS group 이름은 GENCODE v46 `gene_name`과 정확한 기호 일치만 쓴다. 출력 유전자는 Ensembl stable ID(버전 제거)를 GENCODE v46 `gene_name`으로 대응한다.
  - 다대일 대응과 결측은 뺀다. VIPerturb·P1·PIE vocab과도 정확한 기호 일치만 쓰며 alias는 쓰지 않는다.
  - 감소 과정(기록 I): 381 → 기호 일치 365 → 정체 통과 188 → P1 지원 밖 125 → VIPerturb 30 cells 이상 **99**. PIE vocab, CPM, U2 세포 수는 아직 적용하지 않았다.
- **T의 조건(모두 충족):**
  - Gasperini TSS target
  - P1 지원 밖
  - U2 정체 규칙 통과
  - PIE 지원(입력 vocab에 있음)
  - **두 단위 모두** 30 cells 이상. U2는 §3의 배타적 target 세포로 센다.
  - 단위별 C_input에서 target 유전자 5 CPM 이상
- **split:**
  - T를 확정한 뒤 u = sha256(f"CART-K562-PIE-X2|{gene_name}")의 상위 64비트 / 2^64로 정한다. `gene_name`은 GENCODE v46 기호다.
  - u < 0.3이면 D, < 0.6이면 C, 나머지는 E이며 두 단위에 같이 쓴다.
- **보정과 판정:**
  - 두 단위의 D/C를 합쳐 보정한다(`c_selection_unit: pooled`).
  - pooled 행의 target 식별자는 단위 접두사가 없는 기호다. 같은 target의 두 단위 행은 한 cluster이며, bin의 distinct target 수에 한 번만 센다.
  - 단위마다 E를 판정하고 둘 다 PASS여야 한다(단위 간 IUT). 0a 1b S2(IUT, 실험별 C_input 예측)를 상속한다.

## 5. 검정력·관문 (0a §6 상속, 차이만)

- **δ:**
  - 0a의 δ 실측 경로는 두 가지인데 PIE에는 둘 다 쓸 수 없다. 10x Flex 경로는 기록 E로 막혔고, TG/D8 경로는 0a에서 P1-test target 전용으로 정의됐다. 그래서 PIE는 바로 요인당 대체값 0.1을 쓴다.
  - 단위별 합계는 다음과 같다.
    - U1 = 모집단 0.1 + 실측 대체 0.1 + assay 0.1 + VIPerturb 잔여 0.1 = **0.4**(0a 트랙 P VIPerturb와 같다).
    - U2 = 모집단 0.1 + 실측 대체 0.1 + assay 0.1 + 고MOI·library·채취 시점 잔여 0.1 = **0.4**.
  - U2 잔여 요인 하나에 library·채취 시점 차이와 고MOI를 함께 넣었다. 0a의 VIPerturb 잔여 0.1도 repressor·library·판본·채취 시점을 하나로 묶었으므로 같은 방식이다.
- **pilot:**
  - GWPS D8 D/C 중 이미 읽은 target 전체다. `read_unsealed`로 읽고 E는 쓰지 않는다(기록 G의 보수적 편차 상속).
  - PIE 예측은 GWPS C_input으로 만든다.
- **단계별 반증(비용 순서):**
  - (1) PIE 실행 경로와 G-A (ii) 배선 검사.
    - (ii)는 U1의 T 근사 집합 target에 대해, U1 C_input으로 예측한 on-target 부호의 음수 비율 ≥ 0.9인지 본다.
  - (2) GWPS pilot에 대해 PIE를 예측한다.
  - (3) **낙관 대리 검정력**(수학적 상한이 아니다).
    - 실제 설계(D/C pooled 보정, C에서 제품 선택, 단위별 E 판정, IUT)를 그대로 시뮬레이션한다.
    - 다만 U2 자리에는 U1과 같은 target, 세포 수, δ를 갖는 독립 복제를 넣는다.
    - T는 U2 세포 수 조건을 뺀 **낙관 근사**다. 단조 상한이 보장되지 않으므로 그렇게 표기한다. U1 C_input CPM 필터와 U2 정체 규칙은 적용한다.
    - 대리 검정력이 0.8 미만이면 트랙 PG는 미등록이고 U2 발현 자료는 받지 않는다.
    - 이는 사전등록한 futility 규칙이다. 오류가 나면 잘못 멈추는 방향뿐이다. 등록은 (4)의 실제 G-A로만 한다.
  - (4) (3)을 통과하면 U2를 다운로드·추출하고, 실제 두 단위로 통일 모형 G-A를 계산한다.
- **G-A의 나머지:**
  - (iv): U1은 NTC 7,949. U2는 §3의 대조 세포 중 C_ref + C_input + C_audit 합계에 같은 문턱 5,000을 적용한다.
  - (v) 거부 시험과 G-B는 0a 그대로다.

## 6. 서명 항목 (owner)

| # | 항목 | 권고 |
|---|---|---|
| T1 | U2 = Gasperini 2019 at-scale, 고MOI 처리 규칙 §3 | 수용 |
| T2 | δ 0.4 / 0.4 (§5) | 수용 |
| T3 | 단계별 반증 순서 §5. (3) 미달 시 U2 미다운로드 | 수용 |
| T4 | 다운로드: Gasperini 위 5개 파일 약 9.7 GB(외장 SSD). 라이선스는 GEO 공개 자료로 1단계에서 확인 | 승인 |
| T5 | 시도 상한 1회. 미등록, futility, 정체·정렬률 멈춤을 모두 센다. ledger #7 | 1회 |
| T6 | 고MOI 단위(U2)를 계약 S5의 독립 replicate로 인정하는지 | owner 판단 |

**실현성 고지(서명 전):**
- 트랙 K는 δ 0에서도 P(PASS)가 1/200이었다.
- δ 0.4에 0.5 하한을 적용하면, pilot의 부호 정확도가 약 0.9 이상이어야 이동 뒤 성공률이 우연 수준을 넘는다.
- 후보는 99개다. 단위당 E는 약 39 target이라 판정 bin이 1개 이하다.
- 따라서 시도 #7은 futility로 끝날 가능성이 높다.

## 7. ledger

0a §8의 #1–4를 상속한다.

| # | protocol | 상태 |
|---|---|---|
| 5 | CART-K562-VIP-X1 (트랙 K) | 미등록(실현성, 기록 H) |
| 6 | CART-K562-PIE-X1 (트랙 P) | 미등록(실현성, 기록 E) |
| 7 | CART-K562-PIE-X2 (트랙 PG) | 이 사전 명세 |

## 8. 주장하지 않는 것

- 0a §9 전부.
- P1의 S4·S5.
- U2를 저MOI 단일 perturbation 효과로 해석하는 것.
- Gasperini enhancer 관련 주장.
