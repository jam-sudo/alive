# COMPOSE-K562-v1 — A100 Pod Sealed-Run Runbook

> **문서 역할:** COMPOSE-K562-v1의 일회성 sealed evaluation을 위한 운영 계약.
> **개정일:** 2026-07-02
> **현재 실행 상태:** **BLOCKED — §2의 pre-seal release blocker가 모두 해결·검토·commit되기 전에는 실행 금지.**
> **코드 기준점:** `main` `62a2bd4` 이상(2026-07-04). `c324b33`(PR #5) 이후 PR #6–#8이 §2.1 fit-role
> artifact(A1)와 payload-v2(A2) 계약을 추가했다. worker/driver/durable-ledger(sub-project B/C/D)는
> 여전히 미구현이므로 runbook은 BLOCKED 유지.
> **상위 계약:** COMPOSE spec §7/§10.5–§10.6, deep-baseline design §1/§7,
> `CLAUDE.md` §5/§6/§9/§10/§11/§14.2.
> **seal 계약:** COMPOSE seal은 TG-K562와 독립이며 정확히 한 번만 연다. 재실행·resume 없음.

---

## 0. 등록된 과학적 결정

- headline regime: `sealed_double_unseen`; `sealed_single_unseen`은 descriptive secondary다.
- primary error: `e = p^{-1} ||δ̂ − δ||²`(낮을수록 좋음).
- headline: `l1_bilinear_identifiable`.
- simultaneous comparator family: `additive`, `gears`, `cpa`, `id_only`,
  `l3_hypernetwork`. L1은 headline이며 L2는 ablation roster에는 있지만 verdict comparator family에는 없다.
- `GI_LEARNABLE_WIN`: additive lower bound `> 0.05`이고 모든 learned comparator lower
  bound `> 0`이며 integrity가 valid일 때만 가능하다.
- additive 조건만 통과하면 `PARTIAL`; additive 조건도 실패하면 `NO_DISTINCT_WIN`;
  integrity 실패는 `INVALID`다.
- `FUTILITY_STOPPED`는 development 종료 상태이며 sealed negative verdict가 아니다.

## 1. 절대 불변식

1. Phase-2a까지 sealed outcome access count는 0이다.
2. Phase-2b는 double/single-unseen union을 한 번의 `evaluate_sealed_once` 호출로 연다.
3. run directory, lock, pre-access ledger, terminal artifact는 write-once다. **byte-identical이어도
   resume·재실행하지 않는다.** lineage가 달라지면 새 run identity가 필요하지만 소비된 seal은 복구되지 않는다.
4. GEARS/CPA fit 역할은 정확히 `{singles, combo_calibration}`다. control은 응답공간과 기준값
   계산에만 사용한다. sealed pair outcome은 worker·fit·selection에 들어가지 않는다.
5. exact method roster와 모든 worker/config/data digest는 seal 접근 전에 동결한다.
6. clean tree 여부는 실제 `git status --porcelain` 결과로 확인한다. caller가 임의로
   `git_is_clean=True`라고 선언하는 것만으로 충족되지 않는다.
7. Phase-2a가 `FUTILITY_STOPPED`이면 즉시 종료하고 Phase-2b를 호출하지 않는다. seal은 닫힌 채로
   유지하며 futility artifact만 보고한다.

## 2. Pre-seal release blocker — 현재 미완료

아래 항목은 sealed-run pod 세션에서 즉석으로 해결하지 않는다. 별도 development pod에서 구현·검증한
뒤 PR review와 green CI를 거쳐 `main`에 commit한다. 하나라도 미완료면 이 runbook은 계속 BLOCKED다.

### 2.1 GEARS/CPA fit-data 계약

현재 subprocess schema는 집계된 `singles_response`와 `calibration_delta`만 전달한다. published
GEARS/CPA 학습에는 cell-level expression, perturbation label, control population 등 추가 입력이
필요하므로 현재 schema만으로 published baseline을 구현했다고 주장할 수 없다.

`GI_LEARNABLE_WIN`(§0)은 real-input published GEARS/CPA를 이긴 경우에만 성립한다. 따라서 다음
real-input fit-data 계약을 반드시 구현·등록한다. 이는 선택지가 아니라 headline verdict의 전제다.

- payload v2가 immutable fit-role AnnData artifact의 경로와 SHA-256, 허용 obs role,
  feature/gene order를 전달한다. worker는 SHA-256을 재검증하고 `{control, singles,
  combo_calibration}` 이외의 row가 있으면 중단한다. sealed roles/outcomes는 artifact에 존재하지 않아야 한다.

aggregate 입력 전용 재구현은 verdict comparator family의 published GEARS/CPA를 대체하지 못한다.
집계 schema만으로 얻은 우위는 `GI_LEARNABLE_WIN`이 아니며, real-input 계약을 구현하지 못하면 해당
comparator에 대해 `NO_DISTINCT_WIN` 또는 `NOT_EVALUABLE`로 보고한다. 이 milestone은 real GEARS/CPA에
대한 정직한 negative를 견디도록 설계됐으므로 strawman 우위로 대체하지 않는다.

fit-role artifact의 생성 코드, schema validator, negative leakage tests와 checksum이 commit돼야 한다.

### 2.2 실제 worker와 외부 리소스

- `gears_worker.py`와 `cpa_worker.py`를 구현·review·commit한다. sealed session 중 repo 내부에서
  worker를 작성하거나 수정하지 않는다.
- published config의 정확한 epoch/batch/optimizer/early-stop/seed를 versioned config로 고정한다.
- GEARS GO graph/gene2go 등 외부 리소스는 미리 취득하고 license·version·URL·SHA-256을 기록한다.
  worker 실행 중 최신 리소스를 내려받지 않는다.
- worker manifest는 worker bytes, model config, fit-role artifact, GO resource, environment lock,
  seed, payload 및 prediction digest를 결속해야 한다.
- 두 locked environment에서 tiny fixture뿐 아니라 outcome-free Norman fit-role smoke test를 수행한다.

### 2.3 단일 production driver

committed driver를 제공한다. Python REPL이나 수동 객체 조립은 허용하지 않는다. 최소 인터페이스:

```text
python scripts/run_compose_k562_phase2.py preflight --run-spec RUN_SPEC
python scripts/run_compose_k562_phase2.py phase2a   --run-spec RUN_SPEC
python scripts/run_compose_k562_phase2.py phase2b   --run-spec RUN_SPEC --confirm-seal <run_id>
```

driver는 `Phase2aInputs`, development/sealed stores, manifest, response artifact, exact OOF fold assignment,
`EnvironmentInfo`, expected hashes, `ActivationRecord`, run directory와 ledger를 한 곳에서 조립한다.
`preflight`와 `phase2a`는 seal handle을 생성하거나 열 수 없어야 한다. `phase2b`는 Phase-2a CONTINUE,
frozen bundle checksum, clean tree와 confirmation token을 재검증해야 한다.

> **Note (2026-07-07, sub-project C 설계 조정).** (1) 실행 순서: `run_preflight`은 phase2a가 만든 frozen
> bundle(`futility_status=='CONTINUE'`)을 검증하므로 `preflight` subcommand는 **phase2a 뒤에** 실행된다
> (canonical **phase2a → preflight → phase2b**). 위 나열 순서는 subcommand 목록일 뿐 실행 순서가 아니다.
> (2) 위 stage-1 입력(`Phase2aInputs`/fit-role/response/manifest)은 driver 상위의 **PREPARE**(별도
> sub-project)가 만들며 §3 step 8처럼 pre-built로 sync된다. `scripts/compose/build_fit_role_artifact.py`의
> "source/split assembly = sub-project C" 문구는 stale이다. 설계 계약:
> `docs/superpowers/specs/2026-07-07-compose-production-driver-design.md`.

### 2.4 내구 artifact와 보고

- pre-access snapshot 외에 terminal 전이가 반영된 **최종 ledger**를 write-once 파일로 내보내고
  재독출 검증하는 구현이 필요하다. 현재 `Phase2bResult.ledger`는 프로세스 메모리 객체다.
- terminal artifact를 권위 있는 recovery source로 삼아 registered aggregate summary와 final ledger를
  파생하고, 두 파일과 terminal SHA를 결속한 단일 durable commit marker를 마지막에 원자적으로 설치한다.
  Marker가 없으면 seal은 소비됐더라도 durable export는 미완료이며 recovery-only 경로로 복구한다.
  필수 항목은 per-method aggregate error, theta, simultaneous lower bounds, GI-explained secondary interval,
  sample counts, integrity clauses, audit/checksums다.
- 현재 등록 추론은 pair-resampled **aggregate simultaneous bound**다. 등록되지 않은 “per-pair CI”를
  사후 생성하거나 verdict 근거로 사용하지 않는다.
- seed-variability 계약을 명시적으로 해결한다. CLAUDE.md §10은 seed variability 보고를 요구하고,
  외부 seed로 재적합 가능한 stochastic learned comparator(`gears`, `cpa`)의 seed 민감도는 non-sealed
  development role에서 실제로 평가 가능하므로 이를 `gi_structure_recovery`처럼 `NOT_EVALUABLE`로 처리하지
  않는다. seed별 재적합으로 development-phase seed-variability 요약(comparator별 error spread)을 산출·보고하는
  구현이 **§2 release blocker**다. 이 분석은 non-sealed role에서만 수행하며 seal을 다시 열지 않는다.
- deterministic component는 단일 실행으로 충분함을 명시한다. 현재 L1/L2/L3/ID-only와 `additive`,
  `no_change`, `perturbation_mean`은 구성상 seed-불변이다(L3는 module-fixed seed). 일회성 sealed open은
  method별 동결 prediction만 소비한다. 이 single-shot
  성격을 결과에 명시하되, stochastic comparator의 development seed-variability 보고를 대체하는 근거로 쓰지 않는다.
- `gi_structure_recovery`는 현재 `NOT_EVALUABLE`이며 그대로 보고한다.

### 2.5 Release gate

위 구현을 포함한 새 commit에서 다음을 모두 충족해야 한다.

- 전체 suite 및 worker별 locked-env integration test green.
- real fit-role artifact/worker/config/resource/env checksum manifest 완성.
- config의 `power_status`, GEARS/CPA `revision`·`environment_status`와 실제 activation overlay의 관계를
  문서화하고, config digest가 바뀌면 새 run identity와 evidence 결속을 재생성.
- 독립 검토자가 leakage, exact roster, response projection, pair alignment, single seal open,
  final-ledger recovery를 확인.
- 실행할 exact Git SHA를 owner가 승인. 이 시점에만 본 문서 상태를 `READY`로 변경한다.

## 3. READY 이후 pod provisioning

1. 승인된 exact Git SHA를 A100 pod에 clone하고 detached checkout한다.
2. `git rev-parse HEAD`가 승인 SHA와 같은지 확인한다.
3. `git status --porcelain`이 비어 있지 않으면 중단한다.
4. instance/GPU/image/driver/CUDA/시작 시각을 기록한다.
5. committed main lock으로 `uv sync --frozen`한다. 승인된 전체 suite 명령을 실행한다.
6. GEARS/CPA 환경을 committed requirements lock으로 각각 새로 생성하고 fresh-sync한다.
7. `import gears`, `import cpa`, CUDA device와 worker integration test를 확인한다.
8. Norman raw data와 모든 fit-role/feature/GO resource를 object storage에서 sync하고 committed manifest의
   SHA-256과 byte-for-byte 대조한다. 불일치 시 중단한다.
9. raw/processed data, credentials, checkpoints를 repo에 복사하거나 commit하지 않는다.

## 4. ActivationRecord와 provenance 조립

`ActivationRecord.evidence_files`는 정확히 아래 roster를 사용한다. 각 digest는 파일 bytes의
`"sha256:" + sha256`이며 scientific gate가 파일을 다시 읽어 검증한다.

| requirement | evidence file |
|---|---|
| `real_norman_phi_rank_and_condition_report` | `docs/activation-evidence/compose/real_norman_phi_rank_report.json` |
| `regime_specific_detectable_effect_analysis` | `docs/activation-evidence/compose/real_norman_detectable_effect_report.json` |
| `finalized_norman_data_card_and_sha256` | `docs/data-cards/norman_compose_k562_v1.json` |
| `gears_cpa_reproducible_dependency_lock` | `docs/activation-evidence/compose/gears_cpa_dependency_lock.json` |
| `independent_compose_outcome_store_and_access_audit` | `src/alive/compose/outcome_store.py` |
| `phase2_plan_metric_leakage_and_seal_integration_tests` | `tests/alive/compose/test_phase2b.py` |

`build_activation_provenance_inputs`는 keyword-only로 호출한다.

```python
provenance_inputs = build_activation_provenance_inputs(
    processed_path=processed_path,
    feature_bank_path=feature_bank_path,
    dependency_lock_path=dependency_lock_path,
    gears_requirements_path=gears_requirements_path,
    cpa_requirements_path=cpa_requirements_path,
    environment=environment,
    device=device,
    precision=precision,
)
```

builder가 생성한 digest/revision 및 `environment.python_version/platform/git_commit`이 upstream ledger와
일치해야 한다. worker-specific resource/config digest도 §2 구현 후 provenance에 포함돼야 한다.

**Activation evidence lineage 주의 (2026-07-06).** 현재 committed `real_norman_phi_rank_report.json`·
`real_norman_detectable_effect_report.json`은 canonical `config_sha256=d8c65ac4…`, `activation=BLOCKED`,
git `79b01e0`/`82a9c83`를 내장한 **pre-activation development snapshot**이다. 현재 active config의
authoritative canonical digest는 `config_sha256 = sha256_json(raw) = a4700194…`
(`load_compose_phase2_config`, config2.py:692)로 evidence값(`d8c65ac4…`)과 다르다 — activation flip
(`d507a09`) 이후에도 config parsed 구조가 A2 task 5(`42d71ce`: gears/cpa에 `prediction_representation`·
`approximation_bias_report_sha256` 추가)에서 바뀌어 canonical digest가 재차 이동했다. (raw file-bytes sha는
canonical `config_sha256`과 다른 값이니 lineage 비교에는 쓰지 않는다.) `ActivationRecord`는 evidence 파일
*bytes*를 recorded hash에 대조할 뿐 파일 내부 config_sha를 검사하지 않으므로(`config2.py`) old-config
evidence로도 기계적으로는 통과하나, 그럴 경우 일회성 seal의 activation lineage가 pre-activation·pre-A2
snapshot에 결속된다. 따라서 §2.5의 "config digest가 바뀌면 evidence 결속 재생성" 규칙은 **이미 발효**됐다:
pod에서 real Norman data로 두 evidence를 현재 active config(`a4700194…`) 하에 **재생성**하고, 아직 null인
requirement(config `power_status`, GEARS/CPA `environment_status`, GEARS `approximation_bias_report_sha256`)를
실데이터로 확립해 모든 ActivationRecord requirement가 active run identity에 결속된 non-empty evidence hash를
갖도록 한다. rank/power/bias는 어차피 pod-only Norman data가 필요하므로 재생성은 자연스러운 pod 단계다.

## 5. Phase-2a — seal closed

1. production driver의 `preflight`를 실행하고 모든 digest, role count, pair alignment, response dimension,
   exact roster와 backend availability를 검증한다.
2. `build_subprocess_fit_payload`는 keyword-only로 호출한다. §2.1의 확장 schema가 merge된 뒤에는
   driver가 canonical OOF fold assignment와 fit-role artifact를 함께 결속해야 한다.
3. 각 backend에 `configure_payload(payload)`를 호출하고 `provenance_manifest`를 확인한다.
4. `run_phase2a(..., baseline_adapters={"gears": ..., "cpa": ...})`를 실행한다.
5. `model_factories`에는 L1/L2/L3/id_only만 둔다. GEARS/CPA stand-in은 금지한다.
6. 결과가 `FUTILITY_STOPPED`이면 artifact를 백업·보고하고 종료한다. **Phase-2b 금지.**
7. `CONTINUE`일 때만 frozen bundle, method lock, ledger, worker/payload/prediction checksum과
   `sealed_access_count == 0`을 독립 검증한다.
8. Phase-2a 산출물을 object storage에 업로드하고 다운로드 재검증을 수행한다.

## 6. Final pause — human confirmation

seal 직전에 자동화가 멈춰 다음 manifest를 화면과 파일로 출력해야 한다.

- exact Git SHA와 clean status
- run ID/config/data/manifest/sequence/feature/factor/response/model/bundle checksums
- exact method/comparator roster와 selected hyperparameters
- GEARS/CPA worker/config/resource/env/payload/prediction checksums
- double/single pair counts와 seal request checksum
- Phase-2a CONTINUE 및 access count 0
- 비어 있는 run directory, 존재하지 않는 terminal/pre-access snapshot, 비어 있는 seal audit
- artifact backup destination과 가용성

두 번째 운영자가 manifest를 대조한 후 exact run ID를 confirmation token으로 입력한다. 불일치하거나
확신할 수 없으면 중단한다. “일단 열고 확인”은 금지한다.

## 7. Phase-2b — single seal open

production driver가 내부적으로 다음 순서를 강제해야 한다.

1. activation evidence 파일과 clean SHA 재검증.
2. `run_phase2b` preflight와 composite upstream gate.
3. pre-access provenance payload+checksum과 seed-variability artifact의 실제 file SHA를
   `phase2b_pre_access_ledger.json`에 원자적 write-once 저장하고 재독출.
4. double/single exact union에 대해 outcome store의 durable audit claim을 먼저 원자적으로 설치·검증하고,
   그 audit reference로 terminal의 access를 확정한 뒤 claim-bound materialization을 한 번 수행한다.
   audit 설치 전 실패는 pre-access failure(count 0)이며 `ABORTED_AFTER_SEAL`로 기록하지 않는다.
5. 두 regime을 분리 채점하고 double-unseen만 verdict에 사용.
6. on-disk pre-access checksum, seal audit run/request checksum, result checksums 교차검증.
7. complete provenance payload를 내장하고 terminal SHA를 내부 provenance에서 제외한 비순환 구조로
   정확히 하나의 terminal artifact(`COMPLETE`, `INVALID`, `ABORTED_AFTER_SEAL`) 기록.
8. §2.4의 finalizer로 registered summary와 최종 ledger를 write-once 저장·재독출하고, terminal/summary/
   ledger SHA를 결속한 durable commit marker를 마지막에 설치·검증한다.

`INVALID`나 `ABORTED_AFTER_SEAL`도 seal 소비 결과다. 수정 후 재실행하지 않는다.

## 8. 결과 회수와 보고

- terminal, pre/final ledger, durable commit marker, bundle/method lock, provenance, audit, registered
  summaries와 모든 manifest를
  object storage에 업로드한다.
- 각 파일의 SHA-256 manifest를 별도로 저장하고 fresh download로 검증한다.
- 보고에는 primary 방향, theta와 simultaneous bounds, registered secondary, sample counts,
  stochastic comparator development seed-variability 요약(§2.4), `gi_structure_recovery=NOT_EVALUABLE`,
  integrity clauses, failed/invalid state와 noise ceiling을 포함한다.
- 사후 threshold 변경, comparator 제외, pair 제외, 재개봉은 금지한다.
- negative/PARTIAL/INVALID 결과도 보존하고 원인과 함께 등록한다.
- 업로드·재검증 완료 후에만 pod를 teardown하고 instance/image/cost/wall time을 기록한다.

## 9. Fail-closed 표

| 조건 | seal 전 동작 |
|---|---|
| Git SHA/clean status 불일치 | abort |
| activation evidence roster/path/hash 불일치 | `ScientificModeError`, abort |
| fit-role artifact에 허용 외 role 또는 checksum 불일치 | abort |
| worker/config/GO/env manifest 불일치 | abort |
| GEARS/CPA unavailable 또는 prediction roster/shape 불일치 | abort |
| Phase-2a futility | 종료, Phase-2b 금지 |
| frozen roster/upstream/preflight 불일치 | abort |
| run lock, pre-access snapshot, terminal 또는 audit가 이미 존재 | abort |
| final human confirmation 불일치/부재 | abort |

seal 접근 이후의 모든 예외는 terminal `INVALID` 또는 `ABORTED_AFTER_SEAL`을 남기고 재실행하지 않는다.
