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
