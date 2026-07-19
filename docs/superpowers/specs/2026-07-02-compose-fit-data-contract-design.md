# COMPOSE-K562-v1 — Fit-Data Contract (payload-v2) Design Spec

> **문서 역할:** dev-pod 작업 sub-project **A**의 과학적/구현 계약. published GEARS/CPA가
> leakage-safe한 실입력(real-input) fit 데이터로 학습하고, L1과 동일한 PCA-50 응답공간에서
> 비교 가능한 예측을 반환하도록 하는 fit-data 계약을 정의한다.
> **개정일:** 2026-07-19 (status sanitization; contract unchanged)
> **상태:** IMPLEMENTED + MERGED (sub-project A; fit-role artifact A1 + payload-v2 A2). 이 문서는
> as-built 계약이며 current release 상태는 `docs/superpowers/COMPOSE-SEAL-READINESS.md` row A가 추적한다.
> **코드 기준점:** `main` merge commit `8321af3` (PR #7 이후).
> **상위 계약:** runbook `docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md` §2.1,
> deep-baseline design `docs/superpowers/specs/2026-07-01-compose-deep-baselines-design.md` §1,
> COMPOSE spec `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md` §10,
> `CLAUDE.md`#invariants/#seal/#data-eval/#provenance/#compute.
> **seal 관계:** sub-project A의 개발·테스트는 어떤 seal도 열지 않으며 real Norman에 접근하지 않는다.
> production artifact 생성기는 full raw AnnData handle을 받지 않고 §4의 audited fit-role extractor만
> 소비한다. extractor도 sealed row의 expression block을 materialize할 수 없다.

---

## 0. 등록된 결정 (source of truth)

- **A는 §2.1의 real-input fit-data 계약 하나만 구현한다.** PR #7이 aggregate-only 재구현(경로 B)을
  삭제했으므로 A에 대안 경로는 없다. `GI_LEARNABLE_WIN`은 real-input published GEARS/CPA를 이긴
  경우에만 성립한다(runbook §0/§2.1).
- **container = AnnData `.h5ad`, raw counts 보존**(`CLAUDE.md`#data-eval). full 측정 gene universe를
  싣는다(baseline native 전처리 = strongest eligible baseline, §9).
- **payload-v2 = 기존 aggregate payload(변경 없음) + 두 신규 블록**(`fit_role_artifact`,
  `response_projection`). L1/L2/L3(in-process `model_factories`)는 subprocess payload를 쓰지 않으므로
  영향받지 않는다. subprocess payload는 gears/cpa/stub worker만 소비한다.
- **definition of done:** A는 MacBook에서 synthetic Norman-shaped fixture로 build + 전 테스트 green +
  science-dev loop gate PASS 시 `main`에 merge한다. real Norman 생성/검증은 dev pod에서 수행하고 그
  아티팩트 SHA를 data-card/manifest에 기록하며, real 검증은 runbook §2.5 release gate가 담보한다.
- **projection operator의 single source of truth는 `alive.compose.response.ResponseSpace`다.** A는 새
  수식을 만들지 않고 이 객체의 encoder를 직렬화·재구성·검증한다.
- **과학적 identity는 path나 HDF5 bytes 하나가 아니라 canonical content manifest다.** 파일 SHA는
  immutability/transport 검증에 사용하고, row·gene·split·source identity는 별도 canonical digest로 결속한다.
- **GEARS/CPA는 method별 한 번만 fit한다.** 동일 immutable checkpoint가 double/single-unseen을 함께
  예측하며, regime별 worker 재실행·재학습은 허용하지 않는다.

---

## 1. 범위

### 1.1 A가 구현하는 것

- payload-v2 계약: `_SCHEMA_VERSION` 2로 상향, `_REQUIRED_KEYS`/`_validate_payload`에 두 신규 블록 검증
  추가(`src/alive/compose/baseline_subprocess.py`).
- 결정론적 fit-role artifact 생성기: audited fit-role extractor + committed split → immutable fit-role `.h5ad`.
- artifact validator: SHA-256 + gene-order + obs-role whitelist + no-sealed-reference 재검사.
- `response_projection` 블록 직렬화 + worker-side 재구성 + known-answer 테스트.
- negative-leakage 테스트, payload-v2 schema 테스트, projection known-answer 테스트.
- in-test synthetic Norman-shaped fixture 빌더(커밋된 `.h5ad` 아님 — `*.h5ad`는 gitignore).
- `phase2a.build_subprocess_fit_payload`의 payload-v2 배선(생성된 artifact를 path+sha로 참조 +
  `ResponseSpace`에서 `response_projection` 구성).
- response artifact와 fit-role/outcome source의 raw-data SHA·canonical gene order가 동일함을 pre-seal에서
  검증하는 source-binding 계약. A는 **주어진 digest의 equality 강제**를 구현·검증하며, 실제 source에서
  digest를 도출·조립하는 것은 driver C와 pod의 몫이다(§7.3/§10.1). synthetic fixture 테스트는 equality
  enforcement를 증명하지 digest derivation을 증명하지 않는다.

### 1.2 A가 구현하지 않는 것 (계약만 정의)

- gears/cpa worker (sub-project **B**, pod-only real fit). A는 worker가 소비할 계약과 projection
  operator를 정의한다.
- production driver (sub-project **C**).
- durable final-ledger / seed-variability (sub-project **D**).
- baseline **정확성** 검증. A는 계약·leakage·projection을 증명하며 stub worker는 protocol reference일
  뿐 baseline이 아니다.

단, B/C는 이 문서가 정의한 **단일 fit/checkpoint**, source binding, prediction-scale 선언과 output
manifest를 변경할 수 없다. 변경이 필요하면 sealed 실행 전에 본 spec을 version-up하고 owner 승인을 다시 받는다.

---

## 2. payload-v2 계약

`_SCHEMA_VERSION = 2`. v2 = v1 aggregate key 전체(응답공간 projection·δ 참조용으로 유지) + 아래 두 블록.
`_validate_payload`는 `set(payload) == set(_REQUIRED_KEYS)` 정확 일치를 계속 강제하므로 stub worker와
기존 subprocess 테스트는 v2 key set으로 migrate한다(stub은 aggregate key만 읽어 동작 불변).

### 2.1 `fit_role_artifact` (cell-level 데이터 포인터)

```
"fit_role_artifact": {
  "format": "anndata_h5ad",
  "artifact_schema_version": 1,  # artifact 포맷 버전 (payload _SCHEMA_VERSION=2와 별개)
  "path": <str>,                 # resolved absolute path; approved artifacts_root 내부, symlink 금지
  "sha256": <str>,               # ".h5ad" 파일 bytes의 "sha256:"+hex; worker가 fit 전 재검증
  "content_manifest_sha256": <str>, # canonical logical content identity (§3.2)
  "raw_data_sha256": <str>,      # data card/RunSpec/ledger의 exact raw-data digest
  "pair_manifest_sha256": <str>, # verified committed split manifest checksum
  "eligibility_hash": <str>,     # split manifest의 outcome-independent eligibility hash
  "row_identity_sha256": <str>,  # role+perturbation+source row ID의 canonical ordered digest
  "role_obs_key": "role",
  "perturbation_obs_key": "perturbation",
  "allowed_obs_roles": ["control", "singles", "combo_calibration"],
  "gene_order_sha256": <str>,    # canonical var_names 리스트의 sha256
  "n_cells": <int>, "n_genes": <int>,
  "role_counts": {"control": <int>, "singles": <int>, "combo_calibration": <int>},
  "counts_location": "X"
}
```

`path`는 runtime locator일 뿐 과학적 identity가 아니다. serialized payload의 transport SHA에는 포함될 수
있지만 run identity, checkpoint/model identity와 `content_manifest_sha256`은 path 문자열을 제외하고 위
content digest들로 계산한다. worker는 `path`가 absolute·normalized이고 승인된
`artifacts_root` 아래의 regular file이며 symlink가 아님을 확인한 뒤 파일 SHA와 content manifest를 검증한다.
`allowed_obs_roles`는 artifact에 존재 가능한 **input role**이고, 기존 aggregate
`allowed_roles == {singles, combo_calibration}`는 outcome-bearing fit target role이다. control은
reference/preprocessing 입력이며 control cell이 optimization loss에 들어가는지는 worker별 registered config에서
별도로 선언한다.

### 2.2 `response_projection` (native → PCA-50 응답공간 operator)

Finding B(§12) 해결. worker는 native full-gene 예측을 L1과 동일한 PCA-50 δ-공간으로 사상해야 하며, 이
operator는 `alive.compose.response.ResponseSpace`(`project`/`mean_shift`, §6)에서 직렬화한다.

```
"response_projection": {
  "response_artifact_sha256": <str>, # verified ResponseSpace+control_mean artifact digest
  "raw_data_sha256": <str>,          # fit-role artifact/ledger와 exact equality
  "gene_order_sha256": <str>,     # fit-role artifact와 exact equality
  "hvg_gene_ids": [<str>, ...],  # ResponseSpace.hvg_idx를 canonical gene_order로 사상한 gene 이름(순서 보존)
  "transform": ["normalize_total_median", "log1p"],   # alive.compose.response.RESPONSE_TRANSFORM
  "median_library": <float>,     # ResponseSpace.median_library (normalize_total target scalar)
  "pca_mean": [<float>, ...],    # ResponseSpace.pca_mean, len == n_hvg
  "pca_components": [[<float>, ...]],   # ResponseSpace.pca_components, shape (response_dim, n_hvg)
  "control_mean": [<float>, ...],       # z-공간 control 중심, len == response_dim
  "delta_convention": "z_minus_control_mean"
}
```

`pca_components`·`control_mean`은 aggregate key에도 존재한다. divergence 방지를 위해 validator는
`response_projection.pca_components == payload["pca_components"]`,
`response_projection.control_mean == payload["control_mean"]`, 두 블록의 `raw_data_sha256`/
`gene_order_sha256` equality, 그리고 frozen response artifact checksum equality를 강제한다(불일치 →
`PayloadError`). float equality는 canonical float64 hex serialization으로 비교한다.

### 2.3 operator 정의 (등록)

임의의 native full-gene 발현 벡터 `x`(gene_order 정렬)에 대해:

```
z(x)   = ((normalize_log1p(x, median_library)[hvg_gene_ids] - pca_mean) @ pca_components.T)
δ̂(x)  = z(x) - control_mean
```

`normalize_log1p`는 full gene 총합으로 library-size normalize한 뒤 HVG를 subset하므로 artifact가 full
gene universe여야 한다(§0). 이는 `ResponseSpace.project`(response.py:107-132)와 동일한 frozen transform +
PCA basis다. truth δ는 항상 `mean_i(z(x_i)) - control_mean`이다.

### 2.4 native prediction representation 계약

`mean_i(z(x_i))`와 `z(mean_i(x_i))`는 normalize/log1p 비선형성 때문에 일반적으로 같지 않다. 이 차이를
"modeling error"로 처리하거나 sub-project B가 임의 선택해서는 안 된다. worker manifest는 아래 enum 중
하나를 선언하고 해당 registered adapter만 사용한다.

- `cell_raw_counts`: predicted cell별 full-gene non-negative counts에 §2.3 전체 operator를 적용한 뒤 평균.
- `cell_log_normalized`: worker가 선언·검증한 동일 median-library `log1p` scale의 cell별 prediction에
  HVG subset + PCA centering만 적용한 뒤 평균. raw-count normalize/log를 재적용하지 않는다.
- `raw_pseudobulk_approximation`: published implementation이 condition-level(pseudobulk) 예측만 native로
  내보내는 경우에 한해 사용한다. per-cell 예측을 내보내는 baseline에는 금지한다.

**per-method 사전등록 (owner 승인 2026-07-03).** native로 pseudobulk만 내보내는 published baseline(예상:
GEARS)은 `raw_pseudobulk_approximation`을 **사전등록된 경로**로 사용하되, calibration role(non-sealed)에서
`mean_i(project(x_i))` 대비 `project(pseudobulk)`의 approximation bias 분포를 **필수로 사전 산출·보고**한다
(silent 흡수 금지 — 이 bias는 baseline 오차의 일부로 보고된다). per-cell counterfactual을 내보내는
baseline(예상: CPA)은 `cell_raw_counts` 또는 `cell_log_normalized`를 사용한다. 목록에 없는 새 method가
pseudobulk 경로를 쓰려면 sealed 실행 전에 spec version-up + owner 재승인이 필요하다. 어느 경우에도 truth δ는
`mean_i(z(x_i)) - control_mean`으로 불변이다(§2.3).

worker output은 `prediction_representation`, adapter version/checksum, expected/observed gene-order digest를
포함한다. scale이 선언과 다르거나 full-gene universe가 아니면 prediction 생성 전에 실패한다.

### 2.5 단일 fit/checkpoint 및 combined prediction

method별 worker lifecycle은 `validate → fit once → write immutable checkpoint → predict combined pair union once`
순서다. double/single-unseen별로 worker를 두 번 호출하거나 재학습하지 않는다. worker output manifest는
checkpoint SHA, worker/config/resource/environment-lock SHA, fit artifact content SHA, combined ordered request SHA,
prediction representation과 전체 prediction SHA를 포함한다. Phase2a는 combined output을 검증한 뒤 role별로
분할하며 이 manifest를 model checksum과 method lock에 결속한다.

---

## 3. fit-role `.h5ad` 스키마

- **`X`** — raw integer UMI counts `(n_cells, n_genes)`, sparse CSR. full 측정 gene universe(`CLAUDE.md`#data-eval).
- **`obs.role`** — categorical, `{control, singles, combo_calibration}`. **sealed role은 절대 부재.**
- **`obs.perturbation`** — token(`control` / `GENE` / canonical `GENEA_GENEB`). 모든 `combo_calibration`
  cell의 pair는 calibration pair 집합에 속하며 **sealed pair는 부재.**
- **`var_names`** — canonical 순서의 gene ID, `gene_order_sha256`로 결속.
- **`obs.source_row_id`** — 원본 row identity의 opaque ID. 중복·결측 금지; expression outcome은 포함하지 않음.
- **`uns.provenance`** — `{data_card_sha256, raw_data_sha256, pair_manifest_sha256, eligibility_hash,
  calibration_gene_set_hash, row_identity_sha256, gene_order_sha256, generator_code_sha256,
  writer_environment_sha256, config_sha256}`. sealed outcome 값은 없음.

### 3.1 두 하드 보장

1. **Role closure.** artifact obs role ⊆ `{control, singles, combo_calibration}` 정확. 생성기가 assert,
   validator가 재검사, negative-leakage 테스트가 방어. sealed pair **ID**는 예측되나(`pair_ids`),
   sealed **cell/outcome**은 artifact에 절대 존재하지 않는다.
2. **Immutability + identity.** `.h5ad`는 write-once. `sha256`·`gene_order_sha256`을 validator가 지금,
   worker가 fit 직전 재검증한다.

### 3.2 canonical hashing

- `gene_order_sha256 = sha256_json([str(var_name), ...])`. UTF-8 원문, case-sensitive, Unicode normalization
  없음, 중복/empty ID 금지.
- `row_identity_sha256 = sha256_json([[source_row_id, role, canonical_perturbation], ...])`; artifact row order
  그대로 사용한다.
- `content_manifest_sha256`는 schema version, shape/dtype, CSR `indptr/indices/data` canonical byte digests,
  위 row/gene/provenance digest와 role counts를 포함한다. CSR은 digest 전에 `sort_indices` +
  `sum_duplicates` + 고정 dtype으로 canonical화한다(동일 논리 행렬의 storage layout 차이가 digest를 바꾸지
  않도록). HDF5 metadata/chunk layout/path는 제외한다.
- `pair_manifest_sha256`·`eligibility_hash`는 artifact-internal digest가 아니라 committed split manifest에서
  가져온 값이며(§2.1), validator는 이들이 split manifest·source binding과 일치하는지 확인한다.
- 파일 `sha256`는 byte immutability/transport용이다. 동일 논리 입력의 필수 재현성 판정은
  `content_manifest_sha256` equality다. byte-identical H5AD는 pinned writer stack에서만 보조 검사한다.

---

## 4. 생성 (audited extractor + committed split → fit-role `.h5ad`)

`generate_fit_role_artifact`는 raw AnnData/path를 직접 받지 않는다. 입력은 `FitRoleExtraction`과 verified
split/config뿐이다. production `ComposeFitRoleExtractor`가 raw source와 metadata를 소유하되 expression
matrix API를 외부로 노출하지 않고 다음 순서로 동작한다.

1. raw file SHA·data card·exact split checksum/eligibility hash를 검증하고 metadata만 읽는다.
2. metadata로 control/single/combo-calibration row IDs를 산출한다. sealed union과 겹치거나 label이 pair key와
   다르면 **X를 읽기 전에** 중단한다.
3. 허용 row만 backed/chunked slice한다. sealed row의 expression block을 materialize하는 public/private
   실행 경로를 두지 않는다. global densify 금지.
4. 각 row의 canonical perturbation·role·source row ID를 재검사하고 immutable `.h5ad`를 작성한다.
5. §3.2 digest와 파일 SHA를 산출·read-back 검증하고 extractor audit에 request/source/output digest를 기록한다.

**결정론:** 동일 raw-data digest + config + exact split + row/gene identity → 동일 content manifest. 고정 split
외 무작위성 없음. real Norman은 dev pod에서, MacBook은 §8의 synthetic fixture(`tmp_path`에서 조립, 커밋
안 함)로 실행한다.

---

## 5. 검증 & leakage

- **extractor측 assert:** exact split checksum; source metadata label↔row identity; role closure; sealed union과
  selected rows의 교집합 0. 이 검증 전 expression slice 금지.
- **생성기측 assert:** role ⊆ allowed; `obs.perturbation`에 sealed pair 없음; `X` 유한·비음의 정수;
  canonical gene 순서. sparse `data`를 chunk-wise 검사하며 full matrix를 densify하지 않는다.
- **`validate_fit_role_artifact(path, spec, approved_root)`:** `.h5ad`를 재독해 위 전부 + file/content/source/
  split/row/gene digest와 canonical path 정책을 재검사(worker가 fit 전 실행하는 것과 동일 guard). 실패 →
  `FitRoleArtifactError`.
- **payload-v2 `_validate_payload` 확장:** 두 블록 검증 — role subset; sha 형식; `hvg_gene_ids` 유일·
  gene universe 부분집합·순서 보존; `pca_mean` len == n_hvg; `pca_components` shape == (response_dim,
  n_hvg); `control_mean` len == response_dim; enum 필드; §2.2의 aggregate 일치; source/split/row/gene digest
  equality.
- **`_assert_no_sealed_reference`**(`baselines_combo.py:203`)는 신규 key를 포함한 payload 전체를 계속
  스캔한다(sealed token 부재).

### 5.1 negative-leakage 테스트(전부 reject 기대)

1. sealed role이 섞인 artifact → validator reject.
2. `obs.perturbation`에 sealed pair가 있는 artifact → reject.
3. sha 불일치 → reject.
4. gene-order 불일치 → reject.
5. 잘못된 projection shape(`pca_mean`/`pca_components`/`control_mean` 차원) → reject.
6. full raw handle 또는 sealed row를 extractor/generator에 요청 → X materialization 전 reject.
7. pair label과 source row metadata가 바뀐/swapped-row extraction → reject.
8. raw-data/pair-manifest/eligibility/row/content digest 중 하나라도 불일치 → reject.
9. gene column permutation 또는 duplicate/empty `var_names` → reject.
10. relative/path traversal/symlink/artifacts-root 밖 path → reject.

---

## 6. projection 계약과 known-answer

`build_response_projection(response_space, gene_order)`는 `ResponseSpace`의
`{median_library, hvg_idx, pca_mean, pca_components}` + z-공간 `control_mean`을 §2.2 블록으로 직렬화한다
(`hvg_idx`는 `gene_order`로 사상해 `hvg_gene_ids` 이름으로 저장). worker-side 재구성 함수는 §2.3의 operator를
순수 numpy로 구현한다.

**known-answer 테스트(핵심):** synthetic fixture의 fit-role cell 한 행 `x`에 대해 worker-side operator
`z(x)`가 `ResponseSpace.project(X, [i])`(response.py:107)와 수치 tol 내 동일함을 assert한다. 여러 cell에
대해서는 `mean(worker_project(x_i)) == mean(ResponseSpace.project(X, idx))`를 검증한다. raw-count와
log-normalized representation 각각에 대해 중복 transform이 없음을 검증한다. `project(mean(x_i))`가 다른
비선형 반례도 고정해 pseudobulk 경로가 우발적으로 허용되지 않게 한다. 생성 결정론은 동일 입력의
`content_manifest_sha256` equality로 검증한다.

---

## 7. 파일 & 인터페이스

### 7.1 신규

- `src/alive/compose/fit_role.py`
  - `ComposeFitRoleExtractor(source_path, *, data_card, pair_index, split, perturbation_obs_key)`
  - `extract_fit_roles(*, extractor, split, config) -> FitRoleExtraction`
  - `generate_fit_role_artifact(*, extraction, split, config, out_path) -> FitRoleArtifactSpec`
  - `validate_fit_role_artifact(path, *, spec, approved_root) -> None` (실패 시 `FitRoleArtifactError`)
  - `build_response_projection(response_space, *, gene_order) -> dict`
  - `class FitRoleArtifactSpec` (runtime path + file/content/raw/split/eligibility/row/gene digest + counts)
  - `class FitRoleArtifactError(ValueError)`
- `scripts/compose/build_fit_role_artifact.py` — 라이브러리 위 thin CLI(pod 진입점).

### 7.2 수정

- `src/alive/compose/baseline_subprocess.py` — `_SCHEMA_VERSION → 2`; `_REQUIRED_KEYS`에 두 블록 key 추가;
  `_validate_payload`에 §2.1/§2.2/§2.3 검증 추가. prediction format은 bare pair mapping이 아니라
  `{predictions, execution_manifest}` envelope로 version-up하고 둘을 함께 검증한다. 이 envelope 전환은
  `read_predictions`/`write_predictions` 서명과 기존 subprocess 테스트 전체를 migrate시키며(schema-v2 key
  bump보다 넓은 변경 표면), reference worker(아래 stub 항목)도 native full-gene output + operator +
  representation 선언 + envelope를 요구해 더 이상 trivial하지 않다.
- `src/alive/compose/phase2a.py` — `build_subprocess_fit_payload`가 `schema_version:2` 출력,
  `fit_role_artifact`·`response_projection` 부착. adapter를 combined pair union으로 method당 한 번 호출하고
  검증된 output을 role별로 분할.
- `src/alive/compose/response.py` — response artifact에 canonical gene-order digest와 raw-data digest를 결속;
  Phase2a/2b에서 fit-role/outcome source digest와 exact equality 검증.
- `scripts/baselines/stub_worker.py` — v2 key set을 수용하고 §2.3 operator를 **반드시** 실행하는 reference
  worker. aggregate-only additive 동작만으로 integration을 통과할 수 없음.

### 7.3 참조(변경 없음, 계약 소비처)

- gears/cpa worker(B): `fit_role_artifact`로 native fit을 한 번 수행하고 immutable checkpoint로 combined
  pair union을 예측한 뒤 `response_projection`으로 δ̂ 반환.
- production driver(C): raw/data-card/split/row/gene identity를 조립하고 approved artifacts root를 제공하며,
  full raw handle을 generator/worker에 전달하지 않는다.

---

## 8. 테스트 (전부 CPU / MacBook, synthetic fixture)

- **fixture 빌더:** tiny Norman-shaped AnnData를 `tmp_path`에 조립(control/singles/combo_calibration +
  일부 sealed pair를 포함해 제외 로직을 시험; full 대비 축소 gene universe). 커밋된 `.h5ad` 아님.
- **unit:** `generate_fit_role_artifact` on fixture; `validate_fit_role_artifact` happy path;
  `build_response_projection`.
- **leakage/identity(negative):** §5.1의 10개 reject. 특히 sealed row의 X 접근이 0회임을 spy source로 검증.
- **known-answer:** §6의 cell-level projection round-trip + scale별 transform + pseudobulk 비선형 반례 +
  생성 content determinism.
- **schema:** 유효 v2 accept; v1/추가/누락 key·잘못된 shape reject.
- **integration:** v2 하의 reference worker를 `SubprocessBaselineBackend`로 combined double/single request 한 번에
  실행한다. fit 호출 1회, checkpoint 1개, output manifest/checksum 검증, role별 분할과 projection 경로를 시험.
- **crash/tamper:** artifact bytes·content manifest·source/split/row/gene digest·worker checkpoint/output 중 하나를
  변경하면 prediction 전에 실패하며 comparator drop이나 sealed verdict를 만들지 않음.

real gears/cpa·real Norman은 A 범위 밖(B, pod-only).

---

## 9. 에러 처리 — fail-closed, 조용한 skip 없음

모든 artifact/payload/source/projection/worker 검증 실패는 **pre-seal Phase2a abort**다. 현재 구현 기준으로
activation/backend 부재는 `ScientificModeError`, payload/artifact 문제는 `PayloadError`/
`FitRoleArtifactError`, worker 실행 문제는 `BaselineUnavailable`로 raise된다. 이 경우
`FrozenPredictionBundle`, Phase2b terminal, sealed verdict를 생성하지 않고 sealed access count는 0이어야 한다.

`verdict2 INVALID`는 seal이 실제로 소비된 뒤 발견된 audit/provenance/integrity 불일치에만 사용한다.
pre-seal 실패를 INVALID sealed verdict로 표현하지 않는다. 어떤 실패도 GEARS/CPA comparator drop, aggregate
stand-in 대체 또는 roster 축소로 완화하지 않는다.

fail-closed integration/e2e 테스트는 이 수명주기대로 **pre-seal abort**(위 예외) + `sealed_access_count == 0`
+ terminal/sealed-verdict 부재를 assert하며 "terminal INVALID"로 표현하지 않는다. claude_science e2e
skeleton의 `forces_terminal_invalid` 가정은 이 수명주기상 틀렸으므로 verbatim 재사용을 금한다(§12).

---

## 10. 완료 정의

A는 다음 충족 시 `main`에 merge한다.

- audited extractor + `fit_role.py` + payload-v2 + source binding + validator + §8 전 테스트가 synthetic
  fixture에서 green.
- combined worker invocation이 method별 fit/checkpoint를 정확히 한 번 수행하고 checkpoint/prediction digest를
  method lock에 결속.
- response artifact, fit-role artifact, Phase2b outcome source가 같은 raw-data SHA와 gene-order SHA에 결속.
- ruff clean.
- 증분에 대한 **science-dev loop gate PASS**.

A는 **seal을 열지 않고 real Norman에 접근하지 않는다.** real artifact 생성(real Norman에서 생성기 실행 →
real `.h5ad` + sha를 data-card/manifest에 기록)은 dev pod에서 수행하며 runbook §2.5 release gate가 담보한다.

### 10.1 이 spec 완료가 해제하지 않는 release blocker

본 spec의 merge는 sealed-run `READY`나 scientific activation의 충분조건이 아니다. production driver(C)는
Phase2b outcome-store의 pair→source-row label 결속과 raw/gene-order equality를 구현해야 한다. 별도 작업에서
다음 기존 blocker도 해결되어야 한다.

- active config의 `power_status`, GEARS/CPA revision/environment 상태와 activation evidence 의미 검증
- Phase-1 method-axis artifact/checksum 결속(`METHOD_VALIDATED` hardcode 금지)
- terminal artifact와 durable final ledger의 부분 실패 원자성(동시에 COMPLETE/ABORTED 생성 금지)
- published worker config/resource/checkpoint/prediction manifest와 development seed-variability 보고

하나라도 미완료면 runbook 상태는 계속 `BLOCKED`다.

### 10.2 science-dev gate 앵커(예상)

`seal_access_zero`(extractor가 sealed expression row를 materialize하지 않음),
`no_outcome_selected_test_set`(role은 metadata와 committed split 기반, response 강도 아님),
`fit_on_training_roles_only`(control/reference, singles, combo-calibration 역할을 명시적으로 분리),
`protocol_versioned`/`baseline_registered`(계약·worker scale/config/checkpoint 결속) → 대부분 yes/n-a 예상.

---

## 11. 리스크

1. **projection 충실도(최우선).** known-answer가 파이프라인 δ encoder를 정확히 고정해야 한다
   (median_library normalize target, log1p, HVG 순서, centering). `build_response_projection`은 파이프라인이
   쓰는 동일 `ResponseSpace`에서 파생되므로 single source of truth다.
2. **source/pair/gene 정렬.** raw SHA만 맞아도 row/gene order가 바뀌면 truth가 달라진다. exact row/gene
   digest와 source metadata 대조 없이는 release 금지.
3. **비선형 representation.** cell-level prediction과 pseudobulk projection을 혼용하면 모델 간 평가 편향이
   생긴다. worker별 scale adapter와 known-answer 없이는 release 금지.
4. **artifact 크기(full transcriptome).** object-storage 전용, 커밋 안 함 → 허용.
5. **범위 정직성.** A는 계약·leakage·projection을 증명하며 GEARS/CPA **정확성**은 증명하지 않는다(B,
   pod-only). stub은 protocol reference이지 baseline이 아니다.

---

## 12. claude_science 초안 및 audit findings와의 관계

이 spec은 `claude_science/`(로컬 gitignore 참조 초안, `main @ c324b33` 기준 작성)의 검증 결과를 반영한다.

- **Finding A(반영):** 초안 REMEDIATION_PLAN §1a는 경로 A/B를 열린 결정으로 제시하나 PR #7이 경로 B를
  삭제했다. 본 spec §0은 경로 A를 유일 계약으로 확정한다.
- **Finding B(반영):** 초안 worker skeleton의 projection(`components @ native_pred`)은 차원·공간 불일치이며
  docstring이 `control_mean_native`를 가정하나 payload의 `control_mean`은 z-공간(len=response_dim)이다. 본
  spec §2.2/§2.3/§6은 `ResponseSpace` 전체 operator(HVG 선택·normalize·centering 포함)를 직렬화하고
  known-answer로 고정해 이를 해결한다.
- **Independent review findings(2026-07-03, 반영):** raw AnnData 직접 전달의 seal-boundary 우회,
  pseudobulk/cell-level 비선형 혼용, run-relative path, exact split/row/source/gene provenance 누락,
  byte-identical H5AD 과잉 요구, `X`/`counts_layer` 모순, 잘못된 pre-seal→INVALID 수명주기,
  regime별 worker 재학습 가능성을 §2–§9에서 명시적으로 닫았다.
- **Critical-review Finding 1(2026-07-03, 반영):** §2.4 pseudobulk 기본 금지가 pseudobulk-only published
  baseline(GEARS)을 amendment 경로로 몰 수 있음을 지적 → GEARS의 `raw_pseudobulk_approximation` 경로를
  approximation-bias 정량화 조건으로 **사전등록**(owner 승인 2026-07-03), CPA는 cell-level 경로, truth δ 불변.
  minor 노트도 반영: CSR canonicalization(§3.2), prediction-envelope migration 표면(§7.2), source-binding
  scope 경계(§1.1), fail-closed e2e의 pre-seal abort 수명주기(§9).
- worker/driver/e2e-test skeleton은 sub-project B/C의 출발점으로 재사용하되 구현 시 정식 위치
  (`src/`·`scripts/`·`tests/`)로 이전한다. 특히 e2e skeleton의 `forces_terminal_invalid` 가정은 §9대로
  pre-seal abort로 교정한다.
