# COMPOSE-K562-v1 — Fit-Data Contract (payload-v2) Design Spec

> **문서 역할:** dev-pod 작업 sub-project **A**의 과학적/구현 계약. published GEARS/CPA가
> leakage-safe한 실입력(real-input) fit 데이터로 학습하고, L1과 동일한 PCA-50 응답공간에서
> 비교 가능한 예측을 반환하도록 하는 fit-data 계약을 정의한다.
> **개정일:** 2026-07-02
> **상태:** DRAFT — owner 검토 대기.
> **코드 기준점:** `main` merge commit `8321af3` (PR #7 이후).
> **상위 계약:** runbook `docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md` §2.1,
> deep-baseline design `docs/superpowers/specs/2026-07-01-compose-deep-baselines-design.md` §1,
> COMPOSE spec `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md` §10,
> `CLAUDE.md` §5/§6/§7/§9/§11/§14.
> **seal 관계:** sub-project A는 어떤 seal도 열지 않으며 real Norman에 접근하지 않는다.

---

## 0. 등록된 결정 (source of truth)

- **A는 §2.1의 real-input fit-data 계약 하나만 구현한다.** PR #7이 aggregate-only 재구현(경로 B)을
  삭제했으므로 A에 대안 경로는 없다. `GI_LEARNABLE_WIN`은 real-input published GEARS/CPA를 이긴
  경우에만 성립한다(runbook §0/§2.1).
- **container = AnnData `.h5ad`, raw counts 보존**(`CLAUDE.md` §7). full 측정 gene universe를
  싣는다(baseline native 전처리 = strongest eligible baseline, §9).
- **payload-v2 = 기존 aggregate payload(변경 없음) + 두 신규 블록**(`fit_role_artifact`,
  `response_projection`). L1/L2/L3(in-process `model_factories`)는 subprocess payload를 쓰지 않으므로
  영향받지 않는다. subprocess payload는 gears/cpa/stub worker만 소비한다.
- **definition of done:** A는 MacBook에서 synthetic Norman-shaped fixture로 build + 전 테스트 green +
  science-dev loop gate PASS 시 `main`에 merge한다. real Norman 생성/검증은 dev pod에서 수행하고 그
  아티팩트 SHA를 data-card/manifest에 기록하며, real 검증은 runbook §2.5 release gate가 담보한다.
- **projection operator의 single source of truth는 `alive.compose.response.ResponseSpace`다.** A는 새
  수식을 만들지 않고 이 객체의 encoder를 직렬화·재구성·검증한다.

---

## 1. 범위

### 1.1 A가 구현하는 것

- payload-v2 계약: `_SCHEMA_VERSION` 2로 상향, `_REQUIRED_KEYS`/`_validate_payload`에 두 신규 블록 검증
  추가(`src/alive/compose/baseline_subprocess.py`).
- 결정론적 fit-role artifact 생성기: raw Norman AnnData + committed split → immutable fit-role `.h5ad`.
- artifact validator: SHA-256 + gene-order + obs-role whitelist + no-sealed-reference 재검사.
- `response_projection` 블록 직렬화 + worker-side 재구성 + known-answer 테스트.
- negative-leakage 테스트, payload-v2 schema 테스트, projection known-answer 테스트.
- in-test synthetic Norman-shaped fixture 빌더(커밋된 `.h5ad` 아님 — `*.h5ad`는 gitignore).
- `phase2a.build_subprocess_fit_payload`의 payload-v2 배선(생성된 artifact를 path+sha로 참조 +
  `ResponseSpace`에서 `response_projection` 구성).

### 1.2 A가 구현하지 않는 것 (계약만 정의)

- gears/cpa worker (sub-project **B**, pod-only real fit). A는 worker가 소비할 계약과 projection
  operator를 정의한다.
- production driver (sub-project **C**).
- durable final-ledger / seed-variability (sub-project **D**).
- baseline **정확성** 검증. A는 계약·leakage·projection을 증명하며 stub worker는 protocol reference일
  뿐 baseline이 아니다.

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
  "path": <str>,                 # immutable fit-role .h5ad 경로 (run-relative)
  "sha256": <str>,               # ".h5ad" 파일 bytes의 "sha256:"+hex; worker가 fit 전 재검증
  "role_obs_key": "role",
  "perturbation_obs_key": "perturbation",
  "allowed_obs_roles": ["control", "singles", "combo_calibration"],
  "gene_order_sha256": <str>,    # canonical var_names 리스트의 sha256
  "n_cells": <int>, "n_genes": <int>,
  "role_counts": {"control": <int>, "singles": <int>, "combo_calibration": <int>},
  "counts_layer": "raw"
}
```

### 2.2 `response_projection` (native → PCA-50 응답공간 operator)

Finding B(§12) 해결. worker는 native full-gene 예측을 L1과 동일한 PCA-50 δ-공간으로 사상해야 하며, 이
operator는 `alive.compose.response.ResponseSpace`(`project`/`mean_shift`, §6)에서 직렬화한다.

```
"response_projection": {
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
`response_projection.control_mean == payload["control_mean"]`를 강제한다(불일치 → `PayloadError`).

### 2.3 operator 정의 (등록)

임의의 native full-gene 발현 벡터 `x`(gene_order 정렬)에 대해:

```
z(x)   = ((normalize_log1p(x, median_library)[hvg_gene_ids] - pca_mean) @ pca_components.T)
δ̂(x)  = z(x) - control_mean
```

`normalize_log1p`는 full gene 총합으로 library-size normalize한 뒤 HVG를 subset하므로 artifact가 full
gene universe여야 한다(§0). 이는 `ResponseSpace.project`(response.py:107-132)와 동일한 frozen transform +
PCA basis다. baseline이 pseudobulk 발현을 예측하면 `δ̂ = δ̂(x̂_pseudobulk)`이며, truth δ는
`ResponseSpace.mean_shift`(cell별 project 평균 − control_mean, response.py:134-154)로 계산된다. pseudobulk
projection과 cell별 평균의 log1p 비선형 차이는 baseline의 modeling 오차에 흡수되며 truth δ 정의를 바꾸지
않는다(하드닝된 코드 불변). 어떤 예측 수준(cell별 vs pseudobulk)을 쓸지는 sub-project B의 결정이나, 반드시
A가 정의한 이 operator를 사용한다.

---

## 3. fit-role `.h5ad` 스키마

- **`X`** — raw integer UMI counts `(n_cells, n_genes)`, sparse CSR. full 측정 gene universe(`CLAUDE.md` §7).
- **`obs.role`** — categorical, `{control, singles, combo_calibration}`. **sealed role은 절대 부재.**
- **`obs.perturbation`** — token(`control` / `GENE` / canonical `GENEA_GENEB`). 모든 `combo_calibration`
  cell의 pair는 calibration pair 집합에 속하며 **sealed pair는 부재.**
- **`var_names`** — canonical 순서의 gene ID, `gene_order_sha256`로 결속.
- **`uns.provenance`** — `{data_card_sha256, split_seed, calibration_gene_set_hash, generator_version,
  config_sha256}`. **outcome·sealed 정보 없음.**

### 3.1 두 하드 보장

1. **Role closure.** artifact obs role ⊆ `{control, singles, combo_calibration}` 정확. 생성기가 assert,
   validator가 재검사, negative-leakage 테스트가 방어. sealed pair **ID**는 예측되나(`pair_ids`),
   sealed **cell/outcome**은 artifact에 절대 존재하지 않는다.
2. **Immutability + identity.** `.h5ad`는 write-once. `sha256`·`gene_order_sha256`을 validator가 지금,
   worker가 fit 직전 재검증한다.

---

## 4. 생성 (raw Norman + committed split → fit-role `.h5ad`)

결정론적 생성기. 입력: raw Norman AnnData, committed split(`alive.compose.split`, config split seed 11),
config. 단계:

1. raw Norman을 backed/chunked로 로드(`CLAUDE.md` §7; global densify 금지).
2. 각 cell의 `role`을 `obs.perturbation` + calibration gene 집합으로 배정. **모든 sealed-pair cell
   (double/single-unseen)은 완전 제외.**
3. immutable `.h5ad` 작성: `X` = raw counts(full gene universe), `obs = {role, perturbation}`, canonical
   `var_names`, `uns.provenance`.
4. `sha256`(파일 bytes) + `gene_order_sha256` 산출.

**결정론:** 동일 raw data + config + split → byte-identical 출력. 고정 split 외 무작위성 없음. real
Norman은 pod에서, MacBook은 §8의 synthetic fixture(`tmp_path`에서 조립, 커밋 안 함)로 실행한다.

---

## 5. 검증 & leakage

- **생성기측 assert:** role ⊆ allowed; `obs.perturbation`에 sealed pair 없음; `X` 유한·비음의 정수;
  canonical gene 순서.
- **`validate_fit_role_artifact(path, expected_sha256, gene_order)`:** `.h5ad`를 재독해 위 전부 + sha +
  gene-order 재검사(worker가 fit 전 실행하는 것과 동일 guard). 실패 → `FitRoleArtifactError`.
- **payload-v2 `_validate_payload` 확장:** 두 블록 검증 — role subset; sha 형식; `hvg_gene_ids` 유일·
  gene universe 부분집합·순서 보존; `pca_mean` len == n_hvg; `pca_components` shape == (response_dim,
  n_hvg); `control_mean` len == response_dim; enum 필드; §2.2의 aggregate 일치.
- **`_assert_no_sealed_reference`**(`baselines_combo.py:203`)는 신규 key를 포함한 payload 전체를 계속
  스캔한다(sealed token 부재).

### 5.1 negative-leakage 테스트(전부 reject 기대)

1. sealed role이 섞인 artifact → validator reject.
2. `obs.perturbation`에 sealed pair가 있는 artifact → reject.
3. sha 불일치 → reject.
4. gene-order 불일치 → reject.
5. 잘못된 projection shape(`pca_mean`/`pca_components`/`control_mean` 차원) → reject.

---

## 6. projection 계약과 known-answer

`build_response_projection(response_space, gene_order)`는 `ResponseSpace`의
`{median_library, hvg_idx, pca_mean, pca_components}` + z-공간 `control_mean`을 §2.2 블록으로 직렬화한다
(`hvg_idx`는 `gene_order`로 사상해 `hvg_gene_ids` 이름으로 저장). worker-side 재구성 함수는 §2.3의 operator를
순수 numpy로 구현한다.

**known-answer 테스트(핵심):** synthetic fixture의 fit-role cell 한 행 `x`에 대해 worker-side operator
`z(x)`가 `ResponseSpace.project(X, [i])`(response.py:107)와 수치 tol 내 동일함을 assert한다. 이로써 A의
직렬화 operator가 파이프라인 encoder와 정확히 일치함을 증명한다. 추가로 생성 결정론(동일 입력 → 동일 sha)을
assert한다.

---

## 7. 파일 & 인터페이스

### 7.1 신규

- `src/alive/compose/fit_role.py`
  - `generate_fit_role_artifact(*, raw_adata, split, config, out_path) -> FitRoleArtifactSpec`
  - `validate_fit_role_artifact(path, *, expected_sha256, gene_order) -> None`  (실패 시 `FitRoleArtifactError`)
  - `build_response_projection(response_space, *, gene_order) -> dict`
  - `class FitRoleArtifactSpec`  (path, sha256, gene_order_sha256, n_cells, n_genes, role_counts)
  - `class FitRoleArtifactError(ValueError)`
- `scripts/compose/build_fit_role_artifact.py` — 라이브러리 위 thin CLI(pod 진입점).

### 7.2 수정

- `src/alive/compose/baseline_subprocess.py` — `_SCHEMA_VERSION → 2`; `_REQUIRED_KEYS`에 두 블록 key 추가;
  `_validate_payload`에 §2.1/§2.2/§2.3 검증 추가. `read_payload`/`write_predictions` 서명 불변.
- `src/alive/compose/phase2a.py` — `build_subprocess_fit_payload`가 `schema_version:2` 출력,
  `fit_role_artifact`(RunSpec의 path+sha)·`response_projection`(`ResponseSpace`에서 구성) 부착.
- `scripts/baselines/stub_worker.py` — v2 key set 수용(동작 불변); optionally §2.3 operator를 로컬에서
  exercise.

### 7.3 참조(변경 없음, 계약 소비처)

- gears/cpa worker(B): `fit_role_artifact`로 native fit, `response_projection`으로 δ̂ 반환.
- fail-closed 체인: `baselines_combo.BaselineUnavailable`(54) → `freeze.FreezeError`(76) →
  `verdict2` `INVALID`.

---

## 8. 테스트 (전부 CPU / MacBook, synthetic fixture)

- **fixture 빌더:** tiny Norman-shaped AnnData를 `tmp_path`에 조립(control/singles/combo_calibration +
  일부 sealed pair를 포함해 제외 로직을 시험; full 대비 축소 gene universe). 커밋된 `.h5ad` 아님.
- **unit:** `generate_fit_role_artifact` on fixture; `validate_fit_role_artifact` happy path;
  `build_response_projection`.
- **leakage(negative):** §5.1의 5개 reject.
- **known-answer:** §6의 projection round-trip(`z(x)` vs `ResponseSpace.project`) + 생성 결정론(sha).
- **schema:** 유효 v2 accept; v1/추가/누락 key·잘못된 shape reject.
- **integration:** v2 하의 `stub_worker`를 `SubprocessBaselineBackend`(`configure_payload` →
  `predict` → `read_predictions`) 통해 fixture로 end-to-end 실행(gears/cpa 없이 projection 경로 시험).

real gears/cpa·real Norman은 A 범위 밖(B, pod-only).

---

## 9. 에러 처리 — fail-closed, 조용한 skip 없음

모든 검증 실패(`FitRoleArtifactError`/`PayloadError`, sha/gene-order/role/shape)는 raise되어 기존 체인으로
전파된다: `BaselineUnavailable → freeze.FreezeError → verdict2 INVALID`. 누락·무효 artifact가 comparator
drop으로 완화되지 않는다(runbook §2.1, COMPOSE spec §10.5).

---

## 10. 완료 정의

A는 다음 충족 시 `main`에 merge한다.

- `fit_role.py` + payload-v2 + 생성기 + validator + §8 전 테스트가 synthetic fixture에서 green.
- ruff clean.
- 증분에 대한 **science-dev loop gate PASS**.

A는 **seal을 열지 않고 real Norman에 접근하지 않는다.** real artifact 생성(real Norman에서 생성기 실행 →
real `.h5ad` + sha를 data-card/manifest에 기록)은 dev pod에서 수행하며 runbook §2.5 release gate가 담보한다.

### 10.1 science-dev gate 앵커(예상)

`seal_access_zero`(생성기가 sealed cell 제외 — sealed 접근 0), `no_outcome_selected_test_set`(role은
metadata 기반, response 강도 아님), `fit_on_training_roles_only`(projection operator는 control+singles로
fit), `protocol_versioned`/`baseline_registered`(계약 커밋) → 대부분 yes/n-a 예상.

---

## 11. 리스크

1. **projection 충실도(최우선).** known-answer가 파이프라인 δ encoder를 정확히 고정해야 한다
   (median_library normalize target, log1p, HVG 순서, centering). `build_response_projection`은 파이프라인이
   쓰는 동일 `ResponseSpace`에서 파생되므로 single source of truth다.
2. **artifact 크기(full transcriptome).** object-storage 전용, 커밋 안 함 → 허용.
3. **범위 정직성.** A는 계약·leakage·projection을 증명하며 GEARS/CPA **정확성**은 증명하지 않는다(B,
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
- worker/driver/e2e-test skeleton은 sub-project B/C의 출발점으로 재사용하며 구현 시 정식 위치
  (`src/`·`scripts/`·`tests/`)로 이전한다.
