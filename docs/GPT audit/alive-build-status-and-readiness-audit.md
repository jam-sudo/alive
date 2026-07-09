# ALIVE 빌드 현황 및 Real-Run 준비도 감사

> **⚠ SUPERSEDED (2026-07-04) — 2026-06-21 시점 snapshot.** 이 감사는 TG-K562를 "full-data 미시작 /
> sealed 미실행"으로 기술하지만, 이후 `TG-K562-v1` sealed run이 실행되어 **`NO_DISTINCT_WIN`**을
> registered했고 `COMPOSE-K562-v1`이 ACTIVE(2026-06-30)가 됐다. 현재 상태는 `CLAUDE.md` §5 registry.
> 원본은 point-in-time 기록으로 보존한다.

작성일: 2026-06-21  
대상 저장소: `/Users/jam/ALIVE`  
검토 방식: 코드 수정 없는 읽기 전용 검사, cache-disabled 테스트, 저장소 밖 패키지 빌드

---

## 1. 종합 판정

| 평가 영역 | 점수 | 판정 |
|---|---:|---|
| 소프트웨어 구현 | 9/10 | Tasks 1–17에 대응하는 핵심 모듈과 CLI가 존재함 |
| Synthetic/CI 검증 | 9.5/10 | 전체 테스트와 lint/format 통과 |
| 실제 K562 실행 준비도 | 6/10 | ESM 및 실데이터 준비 경로에 차단점 존재 |
| 전체 현재 상태 | **8/10** | real run 전 P0·P1 해결 필요 |

현재 구현은 synthetic·통합 테스트 수준에서는 매우 완성도가 높다. 그러나 실제 A100
scientific run은 아직 시작되지 않았으며, 아래 P0·P1 문제를 해결하기 전에는 decisive
evaluation을 실행하면 안 된다.

---

## 2. 확인된 빌드 상태

- Git branch: `main`
- 검사 시점 HEAD: `3c41ba1`
- Ruff lint: 통과
- Ruff format: 통과
- Pytest: **583 passed, 1 skipped, 1 warning**
- Skip 사유: 현재 환경에 PyTorch가 없어 실제 ESM encoder 테스트 미실행
- Warning: duplicate gene ID 실패 fixture에서 발생한 의도된 AnnData 경고
- Wheel 빌드: 성공
- Source distribution 빌드: 성공
- CLI 등록 확인:
  - `prepare`
  - `fit`
  - `develop`
  - `futility`
  - `calibrate`
  - `evaluate-once`
  - `report`
- 실제 `data/` 및 `artifacts/`: 확인되지 않음
- 실제 K562 experiment: **미시작**

검증 명령은 bytecode와 pytest cache 생성을 차단했으며, 패키지 산출물은 저장소 밖
`/tmp`에 생성했다.

---

## 3. 우선순위별 문제점

## P0-1. ESM 실패 시 mock encoder로 자동 전환

### 현상

Config는 `esm2_t33_650M_UR50D_mean_pool`을 primary feature로 선언한다. 하지만 CLI의
encoder 선택 함수는 torch·ESM import 또는 ESM model 초기화 과정에서 어떠한 예외가
발생해도 이를 숨기고 8차원 `MockSequenceEncoder`를 반환한다.

근거: [`src/alive/cli.py:125`](/Users/jam/ALIVE/src/alive/cli.py:125)

### 위험

- ESM을 사용한다고 등록된 scientific run이 mock feature로 진행될 수 있다.
- 생성된 mock feature bank 자체에는 checksum이 있으므로 단순 checksum 검증으로는 이
  config-feature 불일치를 탐지하지 못할 수 있다.
- 모델이 최종 verdict까지 계산하더라도 해당 결과는 preregistered experiment가 아니다.

### 권장 조치

- scientific mode에서는 ESM dependency·model·GPU 초기화 실패를 즉시 fatal error로 처리한다.
- mock encoder는 명시적인 `synthetic` 또는 `ci` mode에서만 허용한다.
- config의 primary encoder ID와 feature-bank provenance의 `model_revision`, 차원, pooling을
  준비 단계와 평가 단계에서 모두 대조한다.

---

## P0-2. 실제 ESM embedding 경로에 batching과 장문 서열 정책이 없음

### 현상

`Esm2Encoder.encode_residues()`는 모든 단백질 서열을 하나의 batch로 변환해 한 번에
model forward를 실행한다. 주석에는 chunking이 필요할 수 있다고 적혀 있지만 실제
chunking 구현은 없다. ESM token limit을 초과하는 서열에 대한 reject·truncate·windowing
정책도 정의되지 않았다.

근거: [`src/alive/data/features.py:241`](/Users/jam/ALIVE/src/alive/data/features.py:241)

### 위험

- 약 2,000개 target의 feature bank 생성 시 A100에서도 OOM이 발생할 수 있다.
- batch 내부 최장 서열 길이에 맞춘 padding으로 메모리 낭비가 커진다.
- model token limit을 넘는 단백질에서 준비 단계가 실패하거나 정의되지 않은 결과를 낼 수
  있다.
- 실제 ESM 테스트는 현재 환경에서 skip되어 이 경로가 검증되지 않았다.

### 권장 조치

- token-budget 기반 length-bucketing과 mini-batching을 구현한다.
- batch size/token budget을 config에 등록한다.
- maximum supported length와 장문 서열 정책을 preregister한다.
- 각 batch 완료 후 pooled vector만 CPU로 이동하고 GPU tensor를 해제한다.
- 실제 A100 smoke test와 소규모 real ESM integration test를 통과시킨다.

---

## P1-1. Feature eligibility보다 perturbation split이 먼저 수행됨

### 현상

`prepare`는 feature availability를 `build_index()`에 전달하지 않은 채 manifest를 먼저
생성하고, 이후 sequence mapping과 feature bank를 만든다. 후속 단계는
`feature_bank.has(pid)`가 거짓인 target을 각 split에서 그때그때 건너뛴다.

근거:

- [`src/alive/cli.py:208`](/Users/jam/ALIVE/src/alive/cli.py:208)
- [`src/alive/data/replogle.py:368`](/Users/jam/ALIVE/src/alive/data/replogle.py:368)

### 위험

- 계획서의 “missing-feature exclusion before split” 계약을 위반한다.
- split별 실제 사용 표본 수와 비율이 사후적으로 바뀐다.
- sealed cohort가 등록된 최소 200 perturbations 아래로 줄어들 수 있다.
- sequence availability 패턴이 특정 gene family와 연관되면 split 간 구성 편향이 생길 수 있다.
- manifest의 exclusion 기록이 feature-bank exclusion과 불일치한다.

### 권장 조치

1. sequence mapping을 먼저 검증해 usable feature ID 집합을 확정한다.
2. 해당 집합을 `build_index(..., available_feature_ids=...)`에 전달한다.
3. cell count와 feature availability exclusion을 모두 manifest에 기록한다.
4. 그 후 eligible ID만 대상으로 four-way split을 생성한다.
5. manifest assignment와 feature-bank gene 집합의 일치를 hard assertion으로 검증한다.

---

## P1-2. Run artifact가 실질적으로 immutable하지 않음

### 현상

`run_id`는 config 내용만으로 결정된다. 하지만 `prepare`는 동일 run directory의 존재를
허용하고 config snapshot, data card, manifest, feature bank와 ledger를 덮어쓴다. 후속 stage의
ledger helper도 같은 artifact name의 checksum을 새 값으로 교체할 수 있다.

근거:

- [`src/alive/config.py:377`](/Users/jam/ALIVE/src/alive/config.py:377)
- [`src/alive/cli.py:189`](/Users/jam/ALIVE/src/alive/cli.py:189)
- [`src/alive/cli.py:435`](/Users/jam/ALIVE/src/alive/cli.py:435)

### 위험

- 동일 config와 run ID에 다른 data card 또는 raw dataset을 연결할 수 있다.
- preregistered artifact가 stage 재실행으로 변경될 수 있다.
- 최종 ledger가 현재 artifact와 일치하더라도 과거의 덮어쓰기를 증명하지 못한다.
- `immutable`, `frozen`, `one run ID`라는 과학적 계약과 실제 CLI 동작이 다르다.

### 권장 조치

- run directory가 이미 존재하면 기본적으로 `prepare`를 거부한다.
- resume은 기존 input hash가 모두 동일한 경우에만 명시적으로 허용한다.
- run ID에 config뿐 아니라 data-card digest, raw-data hash, sequence-mapping hash를 포함하거나
  별도의 immutable experiment ID를 도입한다.
- 각 stage는 output이 이미 존재하면 재실행을 거부하거나 byte-identical 결과만 허용한다.
- ledger entry의 교체를 금지하고 append-only state transition을 사용한다.
- terminal state 및 sealed access 이후에는 모든 upstream stage를 영구 잠근다.

---

## P2-1. Sequence provenance에 잘못된 source가 기록됨

### 현상

Feature bank의 `sequence_source`에는 protein sequence database release가 아니라 data card의
`raw_data_uri`가 전달된다.

근거: [`src/alive/cli.py:223`](/Users/jam/ALIVE/src/alive/cli.py:223)

### 위험

- 어떤 UniProt/Ensembl release와 ID mapping을 사용했는지 재현할 수 없다.
- expression dataset provenance와 protein sequence provenance가 혼합된다.

### 권장 조치

- data card에 `sequence_source`, `sequence_mapping_sha256`, `id_mapping_version`을 별도 필드로
  둔다.
- raw expression source와 sequence source를 ledger에 독립 artifact로 기록한다.

---

## P3-1. Base predictor artifact 중복 기록

### 현상

`cmd_fit()`이 동일한 base predictor를 같은 경로에 두 번 연속 기록한다.

근거: [`src/alive/cli.py:267`](/Users/jam/ALIVE/src/alive/cli.py:267)

### 영향

과학적 결과에는 직접적인 영향을 주지 않지만 불필요한 I/O이며, stage가 완전히
write-once라는 인상을 약화한다.

---

## 4. 테스트·검증상의 잔여 공백

- 실제 torch/ESM 경로의 테스트 1개가 dependency 부재로 skip되었다.
- A100에서 real ESM model loading, batching, OOM behavior가 검증되지 않았다.
- 실제 Replogle K562 schema와 sequence ID mapping을 사용한 smoke test가 없다.
- 테스트 수는 충분하지만 coverage percentage는 측정되지 않았다.
- synthetic end-to-end 성공은 real-data preprocessing 및 identifier alignment 성공을 보장하지
  않는다.

---

## 5. 현재 진척도

```text
계획서/통계 계약          완료
핵심 Python 모듈          완료
CLI orchestration         완료
Synthetic unit/integration 완료
Lint/format               완료
Wheel/sdist packaging     완료
Real ESM encoder 경로      미검증 및 보완 필요
Real dataset/data card     미준비
Run artifacts             없음
K562 full-data experiment  미시작
Sealed evaluation          미실행
```

---

## 6. Real Run 전 권장 순서

1. Silent mock fallback 제거 및 config-provenance encoder assertion 추가.
2. ESM length-bucket batching과 장문 서열 정책 구현.
3. Feature eligibility 확정 후 split하도록 prepare 순서 수정.
4. Run directory와 ledger를 write-once state machine으로 강화.
5. Sequence provenance 필드 분리.
6. A100에서 10–20개 real protein sequence smoke test.
7. 전체 target feature bank 생성 후 차원·누락·checksum 검증.
8. Real K562 mini dataset으로 `prepare → fit → develop → futility → calibrate` 수행.
9. mini pipeline과 artifact provenance가 통과한 뒤 full-data run 시작.
10. 모든 P0·P1 해결 및 사전 체크리스트 통과 후에만 `evaluate-once` 허용.

---

## 7. 작업트리 주의사항

감사 시작 시 Git 작업트리는 깨끗했으나 점검 도중 감사자가 생성하지 않은 untracked
`README.md`가 나타났다. 이 파일은 수정하거나 삭제하지 않았다. 최종 관측 상태는 다음과
같았다.

```text
?? README.md
```

이 외에 감사 과정에서 ALIVE 저장소의 코드나 문서는 수정하지 않았다.

---

## 8. 최종 결론

ALIVE CARTOGRAPHER Trust-Gate는 synthetic/CI 소프트웨어 빌드로서는 높은 완성도에
도달했다. Futility, conformal calibration, simultaneous inference, sealed-once protection 및
authoritative verdict 구조도 실제 코드로 구현되어 있다.

그러나 현재는 **software-complete에 가깝지만 real-run-ready는 아니다**. Silent mock
fallback, ESM batching 부재, feature eligibility와 split 순서, artifact immutability 문제는
scientific validity 또는 실제 실행 가능성에 직접 영향을 준다. 이 네 항목을 해결하고 A100
real-ESM smoke test를 통과한 뒤에만 K562 decisive run으로 넘어가는 것이 타당하다.
