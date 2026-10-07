# CART 무비용 트랙 K·P — 1단계 기록 (작성 중, 부분 push)

[0a 사전 명세](../2026-10-06-cart-zero-cost-0a-prespec.md)를 따르는 outcome 없는 1단계 기록이다.
항목은 **해당 자료를 읽기 전에** 추가하고 push한다. 이미 push된 항목은 고치지 않는다. 정정은 날짜를 붙여 덧붙인다.

## A. 10x K562 Flex 파일 고정 (2026-10-06, 다운로드 전)

출처: https://www.10xgenomics.com/datasets/16-plex_GEM-X_Flex_1M_human_K562_CRISPR_aggregate (Cell Ranger 9.0.0, CC BY 4.0)

| 파일 | 크기(B) | ETag | 용도 |
|---|---|---|---|
| `…_count_filtered_feature_bc_matrix.h5` | 5,267,211,233 | `0ac76b001e7b3ecb7adb2f66fbefdeb2-628` | 유전자·CRISPR UMI. 봉인 추출의 유일한 입력 |
| `…_count_feature_reference.csv` | 3,365,193 | `78d311bd6fed396082e7989a87dc4034` | guide 목록과 서열(결과값 없음) |

**받지 않는 파일:** 아래는 outcome에서 나온 요약(군집, DE, perturbation 효율)이 들어 있을 수 있으므로 받지도 열지도 않는다.
- `count_analysis.tar.gz`
- `count_crispr_analysis.tar.gz`
- `web_summary.html`
- `count_summary.json`
- `cloupe`
- `filtered_feature_bc_matrix.tar.gz`(h5와 중복)

받은 직후 sha256을 이 기록에 덧붙인다.

**실험 구조(10x 페이지):**
- KRAB-dCas9 K562, transduction 1회, day 6 정지.
- 16 probe barcode로 나눈 뒤 GEM lane 4개에서 처리했다. 깊이는 GEX 10,000 reads/cell, CRISPR 5,000 reads/cell이다.
- library는 sgRNA 약 6,903개다: lncRNA 280개, 단백질 코딩 567개, non-targeting 177개, "Ignore" 2,681개.

## B. 10x Flex guide 호출 규칙 (CRISPR UMI를 읽기 전에 고정)

- feature_type이 "CRISPR Guide Capture"인 feature만 쓴다.
- **세포별 호출:** 그 세포에서 UMI가 가장 많은 guide g1이 UMI ≥ 5이고 그 세포 guide UMI 합의 80% 이상이면 g1을 할당한다. 아니면 미할당이다.
- g1의 `target_gene_name`이 "Ignore"이면 그 세포는 봉인 store로 보내고 어떤 분석에도 쓰지 않는다.
- "Non-Targeting"이면 NTC다. 그 밖에는 target 세포이며, target은 정체 규칙(0a §5)을 통과해야 쓴다.
- batch 단위는 probe-barcode 시료다. barcode 접미사에서 추출하며, 추출 방식은 이 기록 C절에 덧붙인다.
- 이 규칙은 VIPerturb에는 적용하지 않는다(VIPerturb는 RDS의 저자 할당을 허용 목록 열로 쓴다).

## C. PIE 고정 확인 (2026-10-06)

- checkpoint `best_auprc.ckpt` sha256 `e60a1304d074706405939bde94c5edf9851e78070f2d584c6b5025a002ed9a7c` — 고정값과 일치한다.
- code: `ArcInstitute/pie` commit `b26dd17e72ce25b6dbc17568d4f626c8050aea29`(tag v1.0.0).
  격리 venv(Python 3.12, torch 2.10.0, MPS 사용 가능)에 설치했으며, ALIVE의 lock은 바꾸지 않았다.
- **alias 해석:** config의 legacy 경로 `data/sources/aliases.yaml`를 코드가 `src/pie/sources/curated_aliases.yaml`로 연결한다(`src/pie/config.py` `LEGACY_ALIASES_PATH`).
  그 sha256은 `17505cb3c77ab265345ad8982a84e3d0313acc6f7d18ee38329296894015b8e5`이다. 0a의 alias 규칙은 이 파일로 충족된다.
- `PIE_splits@0eeae378…/replogle_xdataset/train.json` sha256 `8d050f28aebf482135d42f758f6b440e0333b3dec8efc0dddab9dcc3099d4be4` — checkpoint의 `train_json_sha256`과 일치한다.
- **학습·검증 맥락:** train과 val에 K562(CVCL_0004)가 없다.
  - train: VCC25 H1, Jiang A549·BXPC3·HAP1·HT29·MCF7, Orion HCT116·HEK293T, Tahoe 45개 세포주.
  - val: VCC25 H1_VAL, Jiang HT29, Orion, Tahoe 4개 세포주.
  - VIPerturb와 10x Flex 자료는 어디에도 없다. PIE 적격성 조건을 충족한다.
- 받은 PIE 학습 자산은 pie_jiang·pie_arc_vcc_25·pie_x_atlas_orion·pie_tahoe100m(`preprocessed/`)과 pie_sources로, 모두 고정 revision이다. **pie_replogle_nadig_essential는 받지 않았다.**

## D. 자료 파일 hash와 봉인 추출 script 고정 (2026-10-06, 추출 전)

- **10x Flex sha256:**
  - `count_filtered_feature_bc_matrix.h5`: `e5f26ef95ef7ff5194fd84f80cb0ebde02a34e21f23a0994171c311ba816d2ad`
  - `count_feature_reference.csv`: `5d13b79d3cd159bd68dce60d6e952e0ca341adbc024a9e060f094b185e4a609e`
- **10x Flex 구조(이름·모양만 확인):**
  - 행렬은 25,349 feature × 1,233,421 세포다. Gene Expression이 18,446개, CRISPR Guide Capture가 6,903개다.
  - barcode는 24 nt에 `-N` 접미사가 붙는다. **batch 단위(probe-barcode 시료)는 24 nt 중 17–24번째 8 nt다.** 이 항목은 B절의 "C절에 덧붙인다"를 대신한다.
- **VIPerturb:** manifest의 md5가 일치한다. bin A–C는 받는 중이며, 다 받은 뒤 이 기록에 sha256을 덧붙인다.
- **봉인 추출 script:** `scripts/cartographer/zero_cost/`, 합성 자료 시험 통과.
```
aedf0113bf60e1d31973326a52c8ca5403477a495395286d0b026d2655027fb7  extract_seurat.R
3f44ad89acbd13f20d84867e7821d13fafe2ae6348b0f195417608f99df5e07f  extract_flex.py
a43db2e9d43ae8b08cf488f46173e0efce6b12fa6d665b3909b704be63a57631  identity_rule.py
3b205422a498d73a4613b026d448870973c307120d17f83c58af5d841b1d9bcb  test_extract_seurat.sh
8dca188257e751c5aa840c346f8db3d386bd29d0172f0200e6cbf988c2f2db64  test_extract_flex.py
```
  - VIPerturb용 `extract_seurat.R`는 먼저 `names` 모드로 열 이름만 본다. 그 이름으로 허용 목록 대응(map.json)을 이 기록에 덧붙인 뒤에 `export` 모드를 쓴다.

## E. 10x Flex 정체 규칙 결과 (2026-10-06, 설계 정보만 사용, outcome 미사용)

- **참조:**
  - GRCh38 no-alt bowtie2 index `GRCh38_noalt_as.zip` sha256 `f12495639adbc9bc676eba68044c6bfb1145e0ca587beaf6c7c41446f9d3c573`
  - GENCODE v46 basic GTF sha256 `d620d548ad23dad6c2d67486b7679d12f00f02f66dd5787183d8e6678dceb9b4`
  - 주 TSS는 MANE_Select, 없으면 Ensembl_canonical로 정한다.
- **기술 정정 (날짜 붙임, outcome 무관):**
  - 첫 실행에서는 20 nt 그대로 정렬했고, 정확히 정렬된 guide가 약 27%뿐이었다. 정체 규칙 통과 target은 847개 중 5개였다.
  - 원인: feature reference 서열 6,903개가 **모두 C로 끝난다.** 20번째 염기는 library의 고정 염기이며 게놈 서열이 아니다.
  - 그래서 앞 19 nt로 정렬한다(bowtie2 `-3 1`, 정확 일치). 그러면 97.4%가 정렬된다(87% 유일).
  - 이 정정은 설계 정보(서열 조성)만으로 정했다.
- **결과(정정 후):** 정체 규칙 통과 target은 847개 중 75개다.
  - P1 지원 target: 74개 중 **1개** 통과.
  - P1 지원 밖: 773개 중 74개 통과.
  - 탈락 사유: guide가 TSS ±500 bp 밖 439개, 다중 정렬 186개, ±1 kb 안에 다른 유전자 TSS 97개, 주 TSS 없음 50개.
  - 해석: 이 library의 단백질 코딩 유전자 이름은 대부분 lncRNA TSS guide에 붙은 근처 유전자 재주석이다.
  - 결과 파일 sha256 `82117960ed5f4c34020394b7a0f36a7d6c03628fe070f555707ede892d3fb070`.
- script(정정 후):
```
15d0f4a556259a3536c3a0726dc71540c1e5574dd90f12a90d7e3a806cfdb664  scripts/cartographer/zero_cost/identity_rule.py
```
- **0a 규칙에 따른 기계적 귀결:**
  1. **δ 측정:** 정체 규칙을 통과한 P1 지원 target이 1개(30개 미만)다. 그래서 Flex 기반 δ 측정을 쓰지 않고, 대체 규칙(TG/D8 + assay 0.1)을 적용한다. 10x Flex의 δ용 행은 열지 않는다.
  2. **트랙 P:** T의 상한은 13개다. 이는 Flex 정체 통과 74개 중 VIPerturb에 있고 30 cells 이상인 target 수이며, VIPerturb manifest 세포 수(이미 읽은 메타데이터)로 계산했다.
     D/C/E로 나누면 bin당 최소 30 target(G-A(i))을 원리상 채울 수 없다. **트랙 P는 등록하지 않는다**(seal 없음, ledger #6 "미등록(실현성)").
     후보 집합 중 GWPS를 포함하는 것은 owner 판정(§1a)으로 쓰지 않는다.
  3. **트랙 K의 PIE 팔:** 트랙 P가 등록되지 않으므로 고정 순서 gatekeeping으로 판정에 참여한다(1b S11).
- 10x Flex 봉인 store는 열지 않은 채 audit count 0으로 유지한다.

## F. 10x Flex 봉인 추출 (2026-10-06T16:23:29Z 완료)

- script: `extract_flex.py`(기록 D의 hash). chunk 50,000. 등록 guide 호출 규칙(기록 B)을 썼다.
- 세포 1,233,421개:
  - NTC 17,612
  - target 393,560
  - Ignore 260,133
  - 미할당 562,116
- 공개 영역(NTC GEX와 guide 메타데이터만) sha256:
  - `ntc_gex.npz` `c2cfd953fae3da1ef3d7b1d9be3f1f6a51d3b784e35e00b5e0b0596fc145f807`
  - `ntc_meta.csv` `b79e6e401bd7823b33c161a82569a6619527db6c8a38027cb89f8097941f0bba`
  - `guide_calls.csv` `f55e2516c17c6864000c0e09b38228f7212d9b76efe5b528300956f3850a17f4`
  - `genes.txt` `d97c3df0ccb22401b5081424f47ced99cfd237aa4bf0bb20d6d5ad72d54d4aac`
- 봉인 store `tenx_flex_prestore`: 50개 파일, 쓰기 금지(`a-w`), audit count 0.
  - 정렬한 파일별 sha256 목록의 sha256: `01df526ea1ef607addba7c27aa37c1491007c0ddaaf325ed7f2c398ba2c4ae67`
- 트랙 P는 등록하지 않으므로(기록 E) 이 store는 열지 않는다. δ용 행도 열지 않는다(Flex 기반 δ 미사용).

## G. VIPerturb 파일 고정·봉인 추출·트랙 K 설계값 (2026-10-06)

- **파일:** md5는 모두 0a §2와 일치한다. sha256:
  - manifest `753a9215bfd693e8b5af47e4312bf53c5c7bae1f6625e463bd61dffb6354417b`
  - binA `eb88c050ffd9f757092f6c3747e19f0b63337e9ac79ab7de64d6c9384e514585`
  - binB `990da0c47fd7c6619e70e5aca57ffa7ff75b0c30c5525afeee808791ea52ab31`
  - binC `0f24d2839285c98d5d7d8217a16c77af376102d279b1797055220828f037954b`
- **이름 검사(`names` 모드, 값 미열람):**
  - assay: RNA(counts), GDO(counts, data)
  - meta 열: orig.ident, nCount_RNA, nFeature_RNA, nCount_GDO, guide, gene, sample, nFeature_GDO
  - binA: 321,022 cells × 19,068 genes
- **허용 목록 대응** `viperturb_map.json` (sha256 `86f07b00949d2f07b6be7ee9b2502d00fe6e36fc28a53a4d70856951a3efb4de`):
  - guide=`guide`, target=`gene`, batch=`sample`, NTC 표지 `NO-TARGET`
  - batch는 GEM lane 단위다. sample 이름(예: FXB1A01_L1)이 well과 lane을 함께 담는다.
- **구조(메타데이터):**
  - binA sample 48개가 모두 `FXB1` 단일 batch다(24 well × lane 2개).
  - Zenodo 설명에 따르면 각 bin은 NTC 전체와 perturbation의 무작위 부분집합을 담는다.
  - 따라서 VIPerturb는 **독립 단위 1개**다. 1b S1과 일치하며, P1의 반복 근거가 되지 않는다.
- **추출:**
  - script 정정 2건(날짜 붙임, outcome 무관): MatrixMarket 대신 binary CSC를 쓰고, 메모리 상한 때문에 chunk로 나눠 쓴다. 실행 시 `R_MAX_VSIZE=60Gb`.
  - 첫 두 시도는 메모리 한도로 중단됐고, 봉인 store에는 아무것도 쓰지 않았다(빈 디렉터리를 지웠다).
  - script sha256: `b85e4fcaf0d3a8b1c4e6abf11d08ba39980019da9ebe312ab4ae1b03d4d39334`
- **결과:**
  - NTC: bin마다 7,949개이며 세 bin의 공개 영역 파일이 byte 단위로 같다 → 한 벌(binA)만 쓴다.
  - 봉인 세포: A 313,073 · B 333,233 · C 252,582. target 18,885개는 bin 간에 겹치지 않는다.
  - 봉인 store `viperturb_prestore/bin{A,B,C}`: 쓰기 금지, audit count 0. 디렉터리 hash:
    - A `3f3239b3dfeac6112a2af5e6bc798eeb540aaec65c15d19d26d7d1219fa57785`
    - B `861a11ed383609e60f7d542b1c628ca3d0b2dea0f19d9038ca9f4c5f3f50ea42`
    - C `a27ee74cc46c000a984d2013167892b37daf781b147acc6ebc70539204072ce4`
- **트랙 K 설계값(guide 할당 메타데이터만 사용):**
  - P1 지원 2,022 중 VIPerturb에 정확한 기호로 있는 target 1,980개, 30 cells 이상 **1,090개**(P1-test 499).
  - 세포 수 중앙값 47(하위 10% 33, 상위 10% 74).
  - slot 파일 sha256 `82a44c0e0568fd64881197b41d5dec598e110ae2f87cb21e4af77f44b52f5815`
- **G-A 부분 판정:**
  - (iii) P1 HVG 결측: 기호 일치 기준 154/2000 = 7.7% ≤ 10% → **통과**. 결측 출력은 평가 행에서 뺀다.
  - (iv) NTC 7,949 ≥ 5,000 → **통과**. C_ref는 약 3,180이다.
- **GWPS pilot 추출(분석 없음, 자료 이동만):**
  - D8의 `read_unsealed`로 D/C만 읽는다. 소모된 E 911개는 D8 seal audit을 우회해야 읽을 수 있어 쓰지 않는다. 0a §2 대비 **보수적 편차**다(pilot이 작아진다).
  - D8 seal audit은 추출 전후로 1줄, sha256 `fc8a71fb…1558` 그대로다.
  - C_ref(P1 축) `pilot_REF.npz` sha256 `9dbc8f4aa10fd7eef6770129b5ec9876338fb5834b34f93030ed863c5faeed77`
  - script sha256 `59fbcf3bc5265c07defa4b8605f975c701af504af99965cf7f88b22a4d63f210`
  - 추출은 이 기록보다 먼저 시작했다. 검정력 계산은 이 기록을 push한 뒤에 한다.
- **후보 탐색(노출 기록):** Gasperini 2019 GEO GSE120861의 `grna_groups.at_scale.txt.gz`(설계 표, sha256 `40e996f072c0ca3664d6aea92f2b85d996f6ce0c17f0808ef09ab4ff8953da82`)만 읽었다.
  - TSS target 381개 중 P1 지원 135개(P1-test 61)다.
  - 결과 파일(deg_results, pair_table)과 발현 자료는 열지 않았다.
  - 0a 범위 밖이므로 쓰려면 새 사전 명세가 필요하다.

## H. 트랙 K G-A 판정: 미등록(실현성) (2026-10-06)

- **입력:**
  - pilot은 GWPS D/C 중 P1 지원 target이다: D 774개(152,708 cells, `pilot_D.npz` `293f5cd27ff535f01b99f5c4e7ab5d39fe9a360717585bfce5a1ffd987343231`), C 398개(79,548 cells, `801943eab6470556981384bc99ebf7225d8bce7948f8960c94665802292294b8`). D8 audit은 전후 모두 1이다.
  - slot은 기록 G를 따른다. NTC 7,949개.
  - V3.1 판정 기준을 쓰며 단위는 1개다.
- **코드:**
  - `power_k.py` sha256 `f03353ee31853b2bc16b8abceae7dae6afc2867d34cd69af294a182dd981d373`
  - 라이브러리는 main checkout HEAD `e29e6e6`의 수정되지 않은 파일이다. 이 파일들은 아직 push하지 않았다.
    - `v3_run.py` `d899038d7dbef10229e1b8ba23c0734db9656d9a616915fcbbe1ab461d377321`
    - `v3_protocol.py` `decd0018fef68b00fb889cbba77cb1e14c161579008da16b602c00e188d9a59b`
    - `day8_protocol.py` `0cfd6698deac86b29a03a363db52a76c444ef1dbcbc4026ce6fe43f16b6061d4`
- **평가 가능 구조(outcome 무관):**
  - slot 1,090개 중 P1이 |h|>0.2인 출력을 하나라도 예측하는 target은 511개다.
  - on-target·cis를 빼도 511개로 그대로다. VIPerturb에서 측정되지 않는 출력을 빼면 **425개**(D/C/E = 127/127/171)가 남는다.
  - 평가 행은 9,584개이고 target당 중앙값은 9다.
- **상한(실측 δ = 0, test δ 0.2 / train δ 0.3, G-B 없음), seed 20261006, 시뮬레이션 200회:**
  - **P(PASS) = 0/200**(95% 상한 약 1.8%). 200회 모두 NO_PRODUCT. `power.json` sha256 `c0d60cdc0dd4ff57e8984a38c04f43a795b9b95ffe6454a7406329b319ae5388`
  - B0: 성공률 test 0.68 / train 0.55, risk UCB 중앙값 0.43 > 0.15.
  - B1: calibration 통과 0/200.
  - ALIVE-L: calibration 통과 18/200, use LCB 중앙값 0.0, distinct win 2/200.
- **판정:** G-A(i)의 검정력 기준 0.8에 미달한다. **트랙 K는 등록하지 않는다**(seal 없음, ledger #5 "미등록(실현성)", 1b S5에 따라 시도 1회를 소모).
  - 실측 δ는 상한을 더 낮추기만 하므로 TG/D8 측정은 하지 않는다.
  - PIE 팔은 P1 PASS가 고정 순서의 선행 조건이므로 함께 미등록이다.
- **탐색 진단(판정 아님, 표기 EXPLORATORY):** test δ 0, train δ 0.1로, 곧 자료 간 전이 손실이 없다고 가정해 200회를 돌렸다.
  - P(PASS) = 1/200. `power.json` sha256 `4bdf27549ce9f84995da4cae3c61e5cd853c244698ee561b195f5befc63cd1ce`
  - 성공률은 test 0.89 / train 0.76, B0 risk UCB 중앙값은 0.22다.
  - ALIVE-L은 calibration 71/200, use LCB 중앙값 0.17, distinct win 17/200이다.
  - 해석: 미달의 주원인은 δ 가정이 아니다. **단위 하나(평가 가능 target 425개, target당 세포 중앙값 47)로는 V3.1 유용성 기준(risk UCB ≤ 0.15, use LCB ≥ 0.30)과 bin별 calibration을 동시에 넘을 수 없다**는 점이다.
- 0a의 두 트랙(K·P)이 모두 미등록으로 끝났다. 봉인 store 4개(Flex 1, VIPerturb 3)는 audit count 0인 채 열지 않는다.

## I. 0b 서명 전 설계값: Gasperini 2019(GSE120861) 노출 범위와 정체 규칙 (2026-10-06, outcome 미사용)

- **읽은 파일(그 밖은 열지 않았다):**
  - `GSE120861_grna_groups.at_scale.txt.gz` 127,092 B, sha256 `40e996f072c0ca3664d6aea92f2b85d996f6ce0c17f0808ef09ab4ff8953da82`
  - `GSE120861_at_scale_screen.genes.txt.gz` 43,493 B, sha256 `4abc4df4f755147856f5921eb68cb5994d5cc75e7a27d061012e9c5624b7a020`, Ensembl ID 13,135개(측정 축)
  - 크기 확인만 한 파일(HEAD 요청): phenoData 86,726,316 B, exprs 9,574,113,337 B
  - 결과 파일, 세포 메타데이터, 논문·보충표는 열지 않았다.
- **설계 표 구조:** group 13,189행(spacer 1개 = 1행). TSS group 381개 × spacer 2개, `pos_control_*` 14, `scrambled_*` 50, `random_*` 50, `bassik_mch` 1, 나머지 `chr*` enhancer 12,312.
- **spacer 형식:**
  - 모두 20 nt다. 전체의 3′ 말단 염기는 G 6,335 · A 4,811 · T 1,190 · C 853으로 치우쳐 있다.
  - TSS spacer 762개의 정확 정렬 수는 다음과 같다. 20 nt 전체 244, 5′ 1 nt 제거 247, **3′ 1 nt 제거 730**, 양끝 1 nt씩 제거 730.
  - 결론: 3′ 말단 1 nt는 게놈 서열이 아니다. 따라서 0b 규칙은 **3′ 1 nt를 자르고 19 nt를 정렬**한다(서명 전 확정, outcome 무관).
  - 20 nt 전체로 돌린 첫 실행(통과 24/365, sha256 `6a6c60f2b5c2bf10a22aa6c4e57a74a9268cc6471cafd4354561139dfe50e06e`)은 대체됐다.
- **기호 대응:** TSS group 이름을 GENCODE v46 `gene_name`과 정확히 맞추면 381 중 365가 일치한다.
  - 일치하지 않는 구 기호 16개는 뺀다: ATP5F1, ATP5J2, ATPIF1, C16orf91, C21orf59, C6orf48, CCDC58, FAM96A, FAM96B, H3F3B, MTRNR2L8, NARS, SEPT11, TARS, TMEM99, WDR61.
  - 다대일 대응은 0개다.
  - 정체 규칙 입력 `tss_feature_reference.csv` sha256 `0cf00b24a47bc510d0a70e169f1acd8afecf1401848ca36480c44fd20994edd0`
- **정체 규칙(script sha256 `15b273864b4fa4eabf5073bd93abfd23f9f5df1f52b70b885628dce25ed234fc`, trim 인자 추가):**
  - 기본값 trim 1로 Flex 결과가 재현된다(`82117960…` byte 일치).
  - Gasperini(trim 1) 통과는 **188/365**다. P1 지원 63/132, P1 지원 밖 125/233.
  - 탈락 사유: ±1 kb 안 다른 TSS 142, TSS에서 먼 guide 22, 다중 정렬 13.
  - 결과 파일 sha256 `d5239f02099b82101277f4abc3aeb8fe0dabbf8fd7f251d37b4210f3cb277922`
- **트랙 PG 후보(PIE vocab, CPM, U2 세포 수 적용 전):**
  - P1 지원 밖 ∩ 정체 통과 ∩ VIPerturb 30 cells 이상 = **99개**
  - 목록 sha256 `6b7793a6e88e679c1d77dd35fca9299585664ba3f0430fdf53dbd615e909ec88`
  - 0.3/0.3/0.4로 나누면 단위당 E는 약 39 target이라 판정 bin이 1개 이하다.
- **0b §1의 "P1 87"의 산출식:**
  - 조건: TSS 이름이 P1 지원 vocab과 정확히 일치(135) ∩ P1 예측(GWPS 대조 기준) |h| > 0.2 ∩ on-target·cis(±1 Mb) 밖 ∩ Gasperini 측정 축(Ensembl ID)에 있는 출력이 1개 이상. 결과는 87(P1-test 39)이다.
  - 쓴 자료는 P1 예측, GENCODE v46, `genes.at_scale`뿐이다. 세포 수는 쓰지 않았다.
  - 정체 규칙을 적용하면 이 수는 더 줄어든다(P1 지원 정체 통과 63). 결론(P1 반복 불가)은 그대로다.
- 외장 SSD를 다시 연결한 뒤 봉인 store hash를 다시 확인했다. Flex 1개와 VIPerturb 3개 모두 기록 F·G와 같다.

## J. 트랙 PG(0b) 판정: 미등록(실현성, futility 규칙 §5 (3)) (2026-10-06)

- **outcome 무관 설계값(U1 = VIPerturb):**
  - C_input 역할 hash의 `{dataset}`은 `viperturb_k562`로 정했다(계산 전에 고정). 그 결과 C_ref 3,174 · C_input 3,201 · C_audit 1,574.
  - 유전자 적격성(C_input 평균 CPM ≥ 5)을 통과한 유전자는 9,412/19,068.
  - **T 근사**는 다음 조건을 모두 충족하는 **91개**다: 후보 99(기록 I) ∩ target 유전자 C_input CPM ≥ 5 ∩ PIE 지원.
    - PIE 지원은 "PIE가 예측을 낸다"로 해석했다. PIE는 빠진 knowledge source를 mask로 처리하므로 99/99가 해당한다. 모든 source가 있어야 한다고 엄격하게 읽으면 `perturbation_text`가 54/99를 덮어 더 적어진다.
  - 세포 수 중앙값은 45다. 설계 파일 `u1_design.json` sha256 `ae603f91547b622c02199008dab3bf8c20f11534bd53a43d17aa58187fdc789b`
- **split:** `CART-K562-PIE-X2|{gene_name}` hash로 나누면 D 28 · **C 21** · E 42다.
- **판정 근거(결정적, 시뮬레이션 불필요):**
  - 실제 T는 근사 T에 U2 세포 수 조건만 더한 부분집합이다. split은 target마다 고정된 hash로 정해지므로 실제 C도 21개 이하다.
  - pooled C에서 같은 target은 한 cluster로 센다(0b §4). 따라서 C의 distinct target도 21개 이하다.
  - V3.1 제품 규칙은 C에 `min_targets_per_bin` 30 이상인 bin이 하나는 있어야 calibration을 통과한다(`requirements`: `cal_pass = bool(sup) and …`). 그러므로 모든 후보가 NO_PRODUCT이고 **P(PASS) = 0**이다.
  - 코드 확인: `v3_protocol.select_product`에 성공률 0.97의 B0를 넣었을 때, C가 21 target이면 product None·supported bins []이다. 대조로 40 target이면 B0가 선택된다(bins [9]).
- **결과:**
  - 트랙 PG는 등록하지 않는다(ledger #7 "미등록(실현성)", T5에 따라 시도 1회 소모).
  - **U2 발현 자료(Gasperini 9.7 GB)는 받지 않았다.**
  - PIE pilot 예측과 G-A (ii)는 판정에 불필요해져 실행하지 않았다.
- **실행 흔적(공개):**
  - **로컬 PIE smoke 실행:** 메모리 부족으로 중단됐고 parquet 출력은 없다.
    - evidence cache 디렉터리가 key `87a01957365041383ac2cbae3a9cf44be6f48e5dbc69ca045f14fa270441d151`로 생성됐다. 이는 Replogle 디렉터리 없이 계산한 key가 pin과 같다는 관찰이다.
    - 이후 owner 지시(2026-10-06)에 따라 RAM이 많이 드는 작업은 Explorer HPC로 옮겼다.
  - **Explorer:**
    - setup job 10883807: PIE 고정 commit `b26dd17e…` clone, alias sha 일치, 자산 일부 다운로드.
    - inference job 10883934: 시작 전에 취소했다.
    - 올린 파일은 대조군 평균 `ctrl_means.npy` 2개, query 2개, adapter뿐이다. 봉인 자료는 올리지 않았다.
  - **GWPS 전체 축 pilot 추출:** 판정이 확정돼 중단했다. 부분 파일만 SSD에 남아 있다.
  - D8 seal audit은 1줄, `fc8a71fb…1558` 그대로다.
- **script sha256:**
  - `pie_controls.py` `41b3fa8650a715cbe594d11d0489343b341d747953c3bed7269bed14c131eb13`
  - `pie_predict.py` `32b058a308470b5a7777692ce06bd5ae4c5e0ba5e903f12395c6291455009c39`
  - `pilot_counts_full.py` `cd5e6b4af2058c96e3ffa461ff0482098f62f447fb2d5eca11091ee175485b7e`
  - `identity_rule.py` `15b273864b4fa4eabf5073bd93abfd23f9f5df1f52b70b885628dce25ed234fc`
