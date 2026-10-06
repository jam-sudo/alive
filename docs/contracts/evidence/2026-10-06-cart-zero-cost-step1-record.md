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
