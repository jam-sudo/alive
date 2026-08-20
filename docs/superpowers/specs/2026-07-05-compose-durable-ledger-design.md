# COMPOSE Durable Final-Ledger + Seed-Variability (sub-project D) Design

> **문서 역할:** dev-stage 설계 계약 (scientific claim contract 아님)
> **개정일:** 2026-07-06
> **상태:** IMPLEMENTED + MERGED (D1 durable publish/final ledger; D2 seed variability). 이 문서는
> as-built 계약이며 current release 상태는 readiness index가 추적한다.
> **상위 protocol:** `COMPOSE-K562-v1`
> **상위 계약:** pod sealed-run runbook
> `docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md` §2.4, §2.5, §7–§8
> **거버넌스:** `CLAUDE.md`#invariants, #data-eval, #provenance, #compute, #agent

## 0. 목적과 범위

이 서브프로젝트는 다음 두 release blocker를 해결한다.

1. seal 소비 후 terminal artifact만 남고 최종 ledger/registered summary가 유실될 수 있는 crash gap
2. stochastic deep comparator의 non-sealed development seed variability 미보고

이 작업은 실제 seal을 열거나 sealed 결과를 재계산하지 않는다. D1은 Phase2b terminal artifact를
권위 있는 복구 원본으로 삼아 파생 산출물을 내구화하고, D2는 Phase2a의 고정 calibration
gene-disjoint OOF 설계에서만 수행한다. Gate PASS는 scientific verdict가 아니다.

### In scope

- **D1:** terminal payload의 registered aggregate summary 완결, final ledger/summary의 recovery-safe
  write-once publish, 단일 durable commit marker
- **D2:** GEARS/CPA의 registered-seed calibration OOF variability report와 pre-seal provenance 결속

### Out of scope

- 실제 GEARS/CPA 수치 산출, 실제 Norman load, 실제 sealed run, object-storage upload
- verdict threshold나 primary inference 방식 변경
- Phase2b outcome-store source/pair/gene binding, Phase-1 method-axis binding 등 다른 release blocker

## 1. D1 원칙: terminal이 권위 있는 복구 원본이다

여러 파일을 순서대로 `atomic_write_once`하는 것만으로는 파일 집합 전체가 원자적이지 않다. 따라서
다음 두 수준을 구분한다.

- 각 파일은 `atomic_write_once`로 개별 원자·write-once 설치한다.
- 파일 집합의 완결성은 마지막에 설치되는 단일
  `phase2b_durable_commit.json`으로 판정한다. 이 marker가 없으면 durable export는 **미완료**이며
  recovery-only 경로로만 복구한다. sealed evaluation을 다시 실행하지 않는다.

정확히 하나의 terminal artifact(`COMPLETE`, `INVALID`, `ABORTED_AFTER_SEAL`)가 seal 소비 상태의
권위 있는 원본이다. final ledger와 registered summary는 terminal을 덮어쓰거나 terminal state를
변경하지 않는 파생 산출물이다.

모든 terminal artifact는 `terminal_payload_checksum`을 포함한다. 이는 해당 필드 자체를 제외한
canonical terminal payload의 SHA-256이다. Recovery는 외부 ledger가 아직 없어도 이 checksum으로
terminal bytes의 내부 무결성을 먼저 확인한다.

### 1.1 비순환 checksum 계층

terminal과 provenance가 서로의 SHA를 포함하면 고정점이 필요한 순환 참조가 생긴다. 이를 금지하고
checksum 방향을 다음과 같이 단방향으로 고정한다.

1. `pre_access_provenance`는 seal 전 입력과 upstream artifact만 포함한다. persisted pre-access ledger는
   이 canonical payload의 self-checksum을 write-once entry로 보존한다. payload 자체는 이후 terminal의
   embedded provenance에 포함되므로 기존 `RunLedger` schema를 임의 확장하지 않는다.
2. `terminal_embedded_provenance`는 검증된 `pre_access_provenance` payload에 seal audit identity와
   double/single regime-result checksum을 추가한다. `provenance_checksum`은 이 payload의
   self-excluding checksum이다.
3. terminal은 `terminal_embedded_provenance` **payload와 checksum을 모두** 포함하고, 그 terminal
   전체를 `terminal_payload_checksum`으로 결속한다.
4. final ledger와 durable commit marker가 terminal file SHA를 바깥에서 결속한다.

따라서 `terminal_embedded_provenance`에는 `terminal_report_sha256`, final-ledger SHA, commit-marker SHA를
넣지 않는다. 기존 `Phase2bProvenance.terminal_report_sha256` 필드는 이 embedded schema에서 제거하거나
명시적 `null/not_applicable`로 schema-version을 올려야 하며, 빈 문자열을 complete provenance처럼
취급하지 않는다. terminal 안에는 checksum만 단독으로 남겨서는 안 된다. Recovery는 embedded payload를
재해시해 `provenance_checksum`을 검증하고 그 payload로 final ledger의 개별 provenance entry를 복원한다.

## 2. terminal payload 계약

모든 terminal JSON은 `schema="compose_phase2b_terminal_v2"`를 사용하고 unknown/missing key를 거부한다.
JSON number는 finite 값만 허용하며 checksum 입력은 정수·문자열·boolean과 IEEE-754 `float.hex()` 문자열로
canonicalize한다. `NaN`, `Infinity`, platform-dependent repr, 비정렬 mapping은 금지한다.

공통 exact fields는 다음과 같다.

- `schema`, `protocol`, `run_id`, `terminal_state`
- `sealed_access_count`, `seal_audit_reference`
- `pre_access_ledger_sha256`, `pre_access_provenance_checksum`
- `terminal_payload_checksum`

state별 허용 필드는 아래 절에 열거한 집합과 공통 fields의 합집합뿐이다. finalizer는 filename과
`terminal_state`의 일치도 검증한다.

### 2.1 COMPLETE/INVALID

Phase2b는 terminal 전이 전에 최종 state와 최종 verdict를 먼저 결정하고, outcome-free
`RegisteredEvaluationSummary`를 한 번 구성한다. 이 summary는 다음을 포함한다.

- protocol, run ID, terminal state, sealed access count
- double/single regime별 sample count
- method별 aggregate pair MSE (`mean(pair_errors[method])`을 protected evaluation 안에서 한 번 계산)
- comparator별 theta와 simultaneous lower bound, family confidence, bootstrap replicate count
- GI-explained point/interval 및 `gi_structure_recovery="NOT_EVALUABLE"`
- 최종 sealed/method axes, 모든 verdict clause, integrity disclaimer
- bundle/manifest/provenance/regime-result/bounds checksum
- seed-variability report checksum

COMPLETE/INVALID의 state-specific exact fields는 `registered_summary`,
`registered_summary_checksum`, `final_verdict_checksum`, `terminal_embedded_provenance`,
`provenance_checksum`, `evaluation_payload_checksum`, `final_result_checksum`이다.
`registered_summary`와 `terminal_embedded_provenance`는 checksum만이 아니라 canonical payload 자체를
포함한다.

per-pair error 배열, per-pair CI, raw cell/count matrix는 terminal payload에 넣지 않는다. Aggregate 값의
계산은 exporter가 사후 재계산하지 않는다. protected evaluation에서 생성해 terminal checksum으로
고정하고, exporter는 terminal에서 그대로 복사한다.

`INVALID`도 정상 verdict를 INVALID로 교체한 **후** summary와 checksum을 만든다. 다음 checksum을
구분한다.

- `evaluation_payload_checksum`: scoring 직후의 regime/bounds 결과 결속
- `final_result_checksum`: 정확히 `{terminal_state, final_verdict_checksum,
  registered_summary_checksum, evaluation_payload_checksum, provenance_checksum}`를 결속한 checksum
- `terminal_payload_checksum`: 위 필드를 포함한 terminal 전체에서 자기 필드만 제외한 checksum

`Phase2bResult.result_checksum`은 `final_result_checksum`이어야 한다. INVALID 결과가 정상 verdict
payload의 checksum을 재사용해서는 안 된다.

### 2.2 ABORTED_AFTER_SEAL

abort 경로는 원래 예외를 재발생시키므로 `Phase2bResult`가 존재하지 않는다. 따라서 abort export는
`Phase2bResult`를 입력으로 받지 않는다. ABORTED terminal 자체가 다음 최소 summary를 포함한다.

- run ID, terminal state, sealed access count/audit reference
- exception class, scrubbed message, failing stage
- 사용 가능한 preflight/run/bundle/manifest checksum
- aggregate 결과가 없으면 `registered_results_status="NOT_AVAILABLE_DUE_TO_ABORT"`

abort artifact는 raw outcome이나 부분 계산 배열을 포함하지 않는다.
ABORTED의 state-specific exact fields는 `exception_class`, `message`, `stage`,
`preflight_checksums`, `registered_results_status`다. audit가 실제로 durable claim됐는지는
`sealed_access_count`와 audit record로 판정한다. 단순히 `claim_access()`가 호출됐다는 이유만으로 count를
1로 만들지 않는다. audit claim 전 예외라면 별도 pre-access failure여야 하며
`ABORTED_AFTER_SEAL`로 과장하지 않는다.

## 3. D1 durable publish와 recovery

공개 진입점은 메모리 객체가 아니라 durable 파일만 입력으로 받는다.

```python
finalize_phase2b_durable_outputs(
    *,
    run_dir: str | Path,
    terminal_path: str | Path,
    pre_access_ledger_path: str | Path,
    seed_variability_path: str | Path,
) -> DurableFinalizeResult
```

네 경로는 resolve 후 모두 `run_dir`의 직접 자식이어야 한다. symlink, directory, device, FIFO와
허용 roster 밖 filename을 거부한다. `terminal_path`는 state에 대응하는 세 terminal filename 중 하나,
`pre_access_ledger_path`는 정확히 `phase2b_pre_access_ledger.json`, `seed_variability_path`는 정확히
`development_seed_variability.json`이어야 한다. finalizer는 caller가 준 경로만 신뢰하지 않고
`run_dir`을 독립 scan해 terminal이 정확히 하나인지 확인한다.

### 3.1 publish 순서

1. terminal file을 읽고 canonical JSON, 정확한 terminal roster, run ID, self-checksum을 검증한다.
2. persisted pre-access ledger를 읽고 run ID, embedded pre-access provenance payload/checksum과 upstream
   checksum을 terminal과 대조한다.
3. terminal payload에서 `phase2b_registered_summary.json` bytes를 **복사·정규화만** 하여 생성한다.
4. terminal의 `terminal_embedded_provenance` payload를 개별 canonical provenance entry로 펼치고,
   pre-access ledger snapshot에 terminal, summary, seed-variability artifact의 파일 SHA를 write-once
   entry로 추가해 `phase2b_final_ledger.json`을 생성한다.
5. 두 파일을 재독출하고 intended canonical bytes 및 SHA와 대조한다.
6. 다음을 결속한 `phase2b_durable_commit.json`을 **마지막에** atomic write-once 설치한다.
   - run ID와 terminal state
   - terminal filename/SHA
   - registered summary filename/SHA/self-checksum
   - final ledger filename/SHA
   - pre-access ledger SHA
   - development seed-variability filename/SHA/self-checksum
   - 위 필드를 결속한 self-excluding `commit_checksum`
7. commit marker를 재독출해 self-checksum, 모든 파일 SHA와 run ID/state를 다시 검증한다.

final ledger는 commit marker를 자기 artifact로 기록하지 않는다. 이는 self-reference를 피하기 위한
의도적 비순환 구조이며, marker가 final ledger를 바깥에서 결속한다.

Reporter, uploader와 runbook release gate는 terminal 파일 존재만으로 durable completion을 선언하지
않고 commit marker 전체 검증을 요구한다. Marker가 없는 terminal은 seal 소비 사실과 terminal state의
증거이지만 export-complete 상태는 아니다.

### 3.2 retry/recovery 규칙

`install_or_verify_exact(path, intended_bytes)`를 사용한다.

- 파일이 없으면 `atomic_write_once`로 설치한다.
- 파일이 이미 있으면 덮어쓰지 않고 byte-identical/SHA-identical인지 검증한다.
- 기존 bytes가 다르면 `DurableLedgerError`로 영구 실패한다.

commit marker가 없고 terminal이 하나 존재하면 recovery는 §3.1을 다시 수행할 수 있다. 이는 파생
파일 복구이며 seal 재개방·재채점·terminal 재전이가 아니다. marker가 존재하면 모든 파일을 검증만
하고 변경하지 않는다. terminal이 0개 또는 2개 이상이면 fail-closed한다.

Recovery는 pre-access ledger에 기록된 seed-variability artifact의 실제 regular-file bytes와 SHA도
검증한다. digest 주장만 있고 파일이 없거나 bytes가 다르면 commit marker를 만들지 않는다.

### 3.3 Phase2b 배선

- 정상/INVALID 경로: terminal write 완료 후 `finalize_phase2b_durable_outputs`를 호출한다.
- abort 경로: `run_phase2b`의 단일 최상위 `except BaseException` owner가 `protect`가 남긴 terminal을
  확인한 뒤 동일 finalizer를 호출하고 원래 traceback을 보존해 재발생시킨다. context manager 내부와
  caller가 중복 호출하지 않는다. Finalizer 실패는 원래 evaluation 예외를 대체하지 않고 exception
  note/log에 부가하며, commit marker 부재가 incomplete durable export를 나타낸다.
- finalizer 자체가 실패해도 기존 terminal을 변경하거나 두 번째 terminal을 만들지 않는다. commit
  marker 부재가 incomplete durable export를 명확히 나타내며 recovery-only 명령이 이를 복구한다.

## 4. D2 development seed-variability 계약

### 4.1 대상 method

현재 코드에서 외부 seed로 재적합 가능한 stochastic comparator는 `gears`, `cpa`다. 현재
`l3_symmetric_mlp`는 module-fixed seed를 사용하는 결정론적 구현이므로 deterministic single-shot으로
분류한다. L3에 외부 seed parameter를 추가하려면 별도 protocol amendment와 model checksum schema
revision이 필요하다.

현재 deterministic roster는 다음과 같다.

- `l1_bilinear_identifiable`, `l2_saturation`, `l3_symmetric_mlp`, `id_only`
- `additive`, `no_change`, `perturbation_mean`

### 4.2 평가 설계

Seed variability는 in-sample training error가 아니라 Phase2a와 동일한 고정 calibration
gene-disjoint OOF assignment에서 계산한다.

각 `(method, registered_seed, fold)`에 대해:

1. Phase2a selection이 실제 사용한 train/test/cross-group position과 pair ID를 **그 selection 호출에서
   직접** canonical `OOFFoldManifest`로 만들고 self-checksummed write-once artifact로 persist한다.
   D2는 이 manifest를 검증·소비하며 fold를 재생성하거나 caller-supplied per-pair 배정을 받지 않는다.
2. controller가 **fold-scoped fit-role artifact와 payload를 새로 생성**한다. singles는 등록 계약대로
   사용할 수 있지만 combo rows/targets는 train pair만 포함한다.
3. held-out test와 cross-group pair의 row ID, target, aggregate, validation/early-stopping signal을 worker
   payload에서 완전히 제외한다.
4. 해당 fold의 held-out test pair 전체를 한 번 예측한다. worker는 pair ID/features만 받고 truth는
   controller에 남긴다.
5. controller가 frozen response space에서 pair별 MSE를 계산한다.
6. 모든 fold의 held-out prediction을 canonical **covered OOF pair order**로 재조립한다.
7. seed별 scalar는 동일 covered OOF pair 집합의 mean MSE로 고정한다.

OOF manifest, calibration pair order, response checksum, base 및 fold-scoped fit-role artifact checksum,
worker/config/resource/environment lock과 seed는 report에 결속한다. sealed pair identity나 sealed
outcome store를 입력으로 받지 않는다.

현재 gene-disjoint fold는 cross-group pair를 OOF test에서 제외할 수 있다. Report는 전체 calibration
pair count, covered/uncovered count와 fraction, ordered covered/uncovered pair-ID checksum,
`uncovered_tolerance`를 기록한다. 모든 method/seed는 **동일한 covered pair 집합**을 사용해야 하며
누락 pair를 method별로 다르게 버릴 수 없다. Coverage가 Phase2a selection artifact와 다르거나 tolerance를
초과하면 `INCOMPLETE`다.

### 4.3 요약과 실패 정책

등록 seed는 config의 exact ordered roster `(11, 23, 37)`를 사용한다. Comparator별로 다음을 기록한다.

- ordered `seed -> oof_mean_pair_mse`
- mean, sample standard deviation (`ddof=1`), min, max, range
- 성공/실패 seed와 scrubbed failure class
- prediction/checkpoint checksum per seed

실패 seed를 삭제하고 성공 seed만 요약하지 않는다. 하나라도 실패하면 report status는 `INCOMPLETE`이며
Phase2b preflight를 차단한다. 모든 seed가 성공해야 `COMPLETE`다.

```python
development_seed_variability(
    *,
    inputs: Phase2aInputs,
    development_outcome_store: DevelopmentOutcomeStore,
    oof_manifest: OOFFoldManifest,
    baseline_adapters: Mapping[str, BaselineAdapter],
    config: ComposePhase2Config,
    response_artifact,
    fit_role_spec,
    gene_order,
    raw_data_sha256,
) -> SeedVariabilityReport
```

`inputs`는 frozen `Phase2aInputs`, `development_outcome_store`는 audited-unsealed 또는 bounded synthetic
`DevelopmentOutcomeStore`, `oof_manifest`는 Phase2a selection·bundle·method lock·ledger가 동일 checksum으로
결속한 exact manifest여야 한다. D2는 이를 재구성하지 않는다. 임의 outcome 배열/dict/path와
`ComposeOutcomeStore`는 받지 않는다.
Calibration truth는 `inputs.additive_cal + development_outcome_store.combo_calibration_eps`로 한 번
재구성하며 pair ID alignment와 outcome-store content checksum을 검증한다. Seed/pair/response checksum은
`inputs`와 activated config의 exact equality로 가져온다.

production entry는 caller-supplied payload/factory를 받지 않고 내부 fold-job builder만 호출한다. fixture
전용 private injection seam은 scientific entry에서 구조적으로 도달할 수 없어야 한다. Worker payload는
기존 payload-v2 exact key roster를 유지하고 train pair/target만 포함한다. test/cross-group ID와 fold/source
checksum은 controller-side `FoldJob` 및 report에 기록한다. worker hyperparameter 선택, checkpoint selection, early
stopping에는 train payload 밖 outcome을 사용할 수 없다. seed는 Python/NumPy/framework/CUDA RNG 설정과
fresh backend instance identity에 전달하며, fold 간 mutable payload state를 공유하지 않는다. 동일 seed
재실행의 determinism 또는 알려진 nondeterministic backend 상태를 report한다.

실제 GEARS/CPA 숫자는 locked pod environments에서 산출한다. 로컬 stub은 seed 전달·fold exclusion·
alignment/checksum wiring known-answer만 검증하며, spread 0을 실제 stochastic stability 근거로 사용하지
않는다.

### 4.4 pre-seal 결속

Seed variability report는 Phase2b 이후 사후 첨부물이 아니다.

- Phase2a/final-pause 전에 self-checksummed write-once artifact로 생성한다.
- upstream/pre-access ledger에 `development_seed_variability`로 기록한다.
- Phase2b scientific preflight는 regular-file artifact 존재와 실제 bytes checksum, status `COMPLETE`,
  exact method/seed roster 및 OOF coverage checksum을 검증한다.
- registered summary와 durable commit marker는 이 report checksum을 참조한다.

## 5. 거버넌스 불변식

- D2는 non-sealed calibration outcomes만 사용하며 sealed store type을 받지 않는다.
- D1은 terminal 이후 파생 파일만 복구하며 seal·scoring·verdict를 재실행하지 않는다.
- per-pair CI를 만들지 않는다. Primary inference는 기존 pair-resampled aggregate simultaneous bound다.
- 모든 파일은 write-once이며 existing mismatch를 덮어쓰지 않는다.
- durable completion은 commit marker 존재와 전체 hash verification으로만 선언한다.
- terminal state 또는 seal access 후 upstream stage를 재실행하지 않는다.

## 6. 테스트

### 6.1 D1

- COMPLETE/INVALID terminal에서 summary/final-ledger/commit marker 생성 및 재독출 검증
- abort fixture가 `Phase2bResult` 없이 abort terminal에서 최소 summary를 생성
- summary, ledger, marker 각 publish 경계의 crash injection 후 recovery
- partial existing file이 intended bytes와 같으면 verify-only, 다르면 fail-closed
- marker가 마지막에 설치되며 marker 없이는 durable-complete로 판정하지 않음
- terminal 0개/2개, run-ID mismatch, checksum tamper, second terminal 생성 시도 거부
- terminal↔provenance checksum 순환이 없고 embedded provenance payload만으로 개별 final-ledger entry 복원
- run_dir 밖 경로, symlink, 잘못된 filename과 non-regular input 거부
- INVALID `final_result_checksum`이 최종 INVALID verdict/state 변화에 민감함
- terminal/summary에 raw outcome, per-pair error, per-pair CI가 없음

### 6.2 D2

- held-out/cross-group pair의 ID·row·target이 해당 fold의 fit/validation/early-stopping payload에 들어가지 않음
- OOF prediction이 canonical covered-pair order로 정확히 재조립되고 모든 method/seed coverage가 동일함
- uncovered count/fraction/ID checksum이 Phase2a selection artifact(covered/uncovered)와 불일치 시 `INCOMPLETE`
- seed가 worker lock/manifest/checkpoint/prediction checksum에 결속됨
- stub known-answer는 동일 결과를 내되 이를 stability evidence로 해석하지 않음
- 실패 seed 보존 및 `INCOMPLETE` preflight 차단
- L3와 나머지 deterministic roster는 single-shot으로 분류되고 seed loop에서 제외됨
- sealed store/object/path 주입 거부

전체 suite와 `ruff check`, `ruff format --check`가 통과해야 한다. 실제 scientific run, sealed evaluation,
외부 데이터 접근은 이 테스트에 포함하지 않는다.

## 7. 완료 정의

- §2–§4 계약이 구현되고 §6 테스트가 모두 통과한다.
- recovery가 모든 crash boundary에서 seal 재개방 없이 동일 commit marker를 생성한다.
- real GEARS/CPA seed report와 object-storage upload는 pod runbook 절차로 남는다.
- 다른 release blocker가 남아 있는 동안 runbook 상태를 `READY`로 변경하지 않는다.

## 참고

- `alive.io.atomic_write_once`
- `alive.compose.terminal.Phase2bTerminal`
- `alive.compose.provenance2.persist_pre_access_ledger`
- `alive.compose.phase2b.Phase2bResult`
- `alive.compose.scoring2.RegimeScore`
- pod sealed-run runbook §2.4, §2.5, §7–§8
