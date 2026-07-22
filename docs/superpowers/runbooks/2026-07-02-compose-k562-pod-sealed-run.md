# COMPOSE-K562-v1 — A100 Pod Sealed-Run Runbook

> **문서 역할:** COMPOSE-K562-v1의 일회성 sealed evaluation을 위한 운영 계약.
> **개정일:** 2026-07-21 (external evidence publication; execution remains blocked)
> **protocol 상태:** lifecycle **ACTIVE** · execution **RELEASE-BLOCKED** · seal **UNOPENED**.
> **현재 실행 상태:** **BLOCKED — §2의 pre-seal release blocker가 모두 해결·검토·commit되기 전에는 실행 금지.**
> **코드 기준점:** release 시 owner가 승인한 clean exact Git SHA만 사용한다. 과거 snapshot SHA는 실행
> floor가 아니다. Current `main`에는 §2.1 fit-role artifact(A1)+payload-v2(A2), §2.4 durable
> final-ledger+seed-variability(D1/D2), 그리고 §2.3 단일 production driver(sub-project C, `phase2a`/
> `preflight`/`phase2b --confirm-seal`/`recover`)가 모두 **main에 병합됐다**(C = merge commit `1c46708`;
> whole-branch 2-lens 리뷰 + Important 2건 fix 후 관련 suites green). Local dev-pod
> scientific ResolvedRunSpec/PREPARE carrier assembly까지 main에 병합됐지만 실제 fit body와 activation
> evidence는 아직 미완료다. **남은 blocker: §2.2 real GEARS/CPA worker(+GO graph·pinned env), conforming
> Probe A와 reviewed output bridge, approximation-bias v3 report/integration, §4 activation-evidence를 finalized active config로
> 재생성 + null requirement 확립, §2.5 release gate(worker locked-env green + owner의 exact Git SHA 승인).**
> 이들이 별도 development pod에서 해결·검토·commit되기 전에는 runbook은 계속 BLOCKED다.
> **상위 계약:** COMPOSE spec §7/§10.5–§10.6, deep-baseline design §1/§7,
> `CLAUDE.md`#invariants/#seal/#data-eval/#provenance/#compute.
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

committed driver를 제공한다. Python REPL이나 수동 객체 조립은 허용하지 않는다. 단일 CLI entrypoint
`scripts/run_compose_k562_phase2.py`는 네 subcommand를 노출한다: `phase2a`, `preflight`, `phase2b`,
`recover`. `phase2a`/`preflight`/`phase2b`는 `--run-spec PATH --approved-artifacts-root PATH
--run-dir PATH`를 받고, `phase2b`는 추가로 `--confirm-seal <confirmation_checksum>`을 받는다.
`recover`는 `--run-dir PATH`와 scientific일 때 필수인 `--seal-audit-path PATH`를 받는다. **실행 순서는
canonical `phase2a → preflight → phase2b`다**
(`preflight`는 phase2a가 만든 frozen bundle을 `futility_status=='CONTINUE'`일 때만 검증하므로 phase2a
뒤에 실행된다):

```text
python scripts/run_compose_k562_phase2.py phase2a    --run-spec RUN_SPEC --approved-artifacts-root ARTIFACTS_ROOT --run-dir RUN_DIR
python scripts/run_compose_k562_phase2.py preflight  --run-spec RUN_SPEC --approved-artifacts-root ARTIFACTS_ROOT --run-dir RUN_DIR
python scripts/run_compose_k562_phase2.py phase2b    --run-spec RUN_SPEC --approved-artifacts-root ARTIFACTS_ROOT --run-dir RUN_DIR --confirm-seal <confirmation_checksum>
```

`recover`는 seal이 이미 소비된 run의 crash-recovery 전용 경로다. Fixture audit은
`<run_dir>/audit.jsonl`; scientific audit은 ResolvedRunSpec에 고정된 protocol-global path다:

```text
python scripts/run_compose_k562_phase2.py recover --run-dir RUN_DIR --seal-audit-path SCIENTIFIC_PROTOCOL_AUDIT
```

`SCIENTIFIC_PROTOCOL_AUDIT`은 임의로 재구성하거나 새 위치로 바꾸지 않는다. 실행에 사용한 canonical
ResolvedRunSpec의 `scientific.sealed_input.audit_path` 값을 그대로 사용하며, 그 값은 승인 root 아래
`.compose-protocol-seal-<sha256(protocol UTF-8)>.jsonl`과 loader가 정확히 대조한다.

⚑ `--confirm-seal`에 넣는 값은 **`<run_id>`가 아니다.** `preflight`가 성공 시 `<run_dir>/
seal_confirmation_manifest.json`을 write-once로 설치하며, 그 manifest의 `confirmation_checksum`
필드값이 유일하게 유효한 토큰이다. run-id-only 토큰은 driver가 명시적으로 거부한다(§6 human
confirmation 절차 참조).

driver는 `Phase2aInputs`, development/sealed stores, manifest, response artifact, exact OOF fold assignment,
`EnvironmentInfo`, expected hashes, `ActivationRecord`, run directory와 ledger를 한 곳에서 조립한다.
`preflight`와 `phase2a`는 seal handle을 생성하거나 열 수 없어야 한다. `phase2b`는 Phase-2a CONTINUE,
frozen bundle checksum, clean tree와 confirmation token을 재검증해야 한다.

exit code 계약: `0` 성공, `20` phase2a futility(`FUTILITY_STOPPED`, `phase2b` 금지), `30` phase2b/recover의
post-seal non-COMPLETE(durable export 미완료 포함), `10` pre-seal rejection.

> **Note (2026-07-07, sub-project C 설계 조정).** 위 stage-1 입력(`Phase2aInputs`/fit-role/response/
> manifest)은 driver 상위의 **PREPARE**(별도 sub-project)가 만들며 §3 step 8처럼 pre-built로 sync된다.
> `scripts/compose/build_fit_role_artifact.py`의 "source/split assembly = sub-project C" 문구는
> stale이다. 설계 계약: `docs/superpowers/specs/2026-07-07-compose-production-driver-design.md`.

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
- seed-variability 계약을 명시적으로 해결한다. CLAUDE.md#data-eval은 seed variability 보고를 요구하고,
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
- `validate_dependency_lock`가 `run_gate.evidence_status == "COMPLETE"`를 반환해야 한다.
  즉 두 backend 모두 fit-role row identity, training/sealed pair roster, zero-overlap,
  smoke script/log/checkpoint/exit-code hash가 있고, 각 artifact의 durable URI와 immutable
  object version을 담은 manifest, wheelhouse manifest SHA, immutable container image
  digest가 있어야 한다. Import 성공이나 관찰자 서술만으로 대체할 수 없다.
- config의 `power_status`, GEARS/CPA `revision`·`environment_status`와 실제 activation overlay의 관계를
  문서화하고, config digest가 바뀌면 새 run identity와 evidence 결속을 재생성.
- Probe-A exact admission evidence와 approximation-bias report가 shared full-schema validator를
  통과해야 한다. Final config의 GEARS report SHA, report file SHA, ResolvedRunSpec의
  `scientific.approximation_bias_report.{path,sha256}`가 모두 같아야 하며, report의 contract SHA,
  `approved_git_sha`, bias-null basis config SHA도 독립 재검증한다.
- 독립 검토자가 leakage, exact roster, response projection, pair alignment, single seal open,
  final-ledger recovery를 확인.
- 실행할 exact Git SHA `C`를 owner가 승인한다. `C`는 실행 repository의 **마지막 commit**이다. `C` 이후
  report, finalized config, owner-approved ResolvedRunSpec 또는 READY 표기를 repository에 commit하면 HEAD가 이동해
  `approved_git_sha == runtime HEAD == report producer git_sha` 결속이 깨지므로 금지한다.
- owner 승인은 approved-artifacts root 안의 canonical ResolvedRunSpec으로 게시한다. 그 spec의
  `scientific.activation_evidence` block이 owner activation registration이고, whole-file SHA는 execution
  identity에 결속된다. 이 runbook의 repository 상태는 단독 release authority가 아니며, runtime은 run
  spec, evidence bytes, clean detached `C`를 함께 검증해 release를 결정한다.

## 3. Final PREPARE publication과 sealed-run pod provisioning

1. owner-candidate exact Git SHA `C`를 PREPARE pod에 clone하고 detached checkout한다. Owner 승인 후
   sealed-run pod도 정확히 같은 `C`를 사용한다.
2. `git rev-parse HEAD`가 `C`와 같은지 확인한다.
3. `git status --porcelain`이 비어 있지 않으면 중단한다.
4. instance/GPU/image/driver/CUDA/시작 시각을 기록한다.
5. committed main lock으로 `uv sync --frozen`한다. 승인된 전체 suite 명령을 실행한다.
6. GEARS/CPA 환경을 committed requirements lock으로 각각 새로 생성하고 fresh-sync한다.
7. `import gears`, `import cpa`, CUDA device와 worker integration test를 확인한다.
8. Norman raw data와 모든 fit-role/feature/GO resource를 object storage에서 sync하고 committed manifest의
   SHA-256과 byte-for-byte 대조한다. 불일치 시 중단한다.
9. raw/processed data, credentials, checkpoints를 repo에 복사하거나 commit하지 않는다.

### 3.1 External publication root

Production PREPARE 산출물은 Git checkout과 분리된 durable filesystem/object snapshot에만 쓴다. 아래 변수는
모두 absolute canonical non-symlink path여야 한다.

```bash
export APPROVED_GIT_SHA="$(git rev-parse HEAD)"
export APPROVED_ARTIFACTS_ROOT="/absolute/durable/compose-k562-v1/<release-id>"
export ACTIVATION_EVIDENCE_STAGE="${APPROVED_ARTIFACTS_ROOT}/stage1/activation-evidence/compose"
export FINAL_CONFIG_PATH="${APPROVED_ARTIFACTS_ROOT}/stage1/configs/compose_k562_v1_phase2.finalized.yaml"
```

`APPROVED_ARTIFACTS_ROOT`와 `ACTIVATION_EVIDENCE_STAGE`는 repository root 밖이어야 한다. PREPARE 중에는
fresh staging root에 write-once로 조립하고, manifest와 owner-approved ResolvedRunSpec이 완성되면 immutable object
version으로 승격한 뒤 byte-for-byte read-back한다. 그 immutable version만 ResolvedRunSpec의
`approved_artifacts_root`가 될 수 있다. Pod ephemeral disk는 유일본이 될 수 없다.

승인 commit `C`에는 producer code/spec, dependency lock, data card와 **bias-null basis config**가 들어간다.
clean detached `C`에서 approximation-bias report를 stage에 생성하고, finalizer가 basis config의
`baselines.gears.approximation_bias_report_sha256` leaf 하나만 바꾼 `FINAL_CONFIG_PATH`를 stage에 생성한다.
최종 config와 report를 Git에 추가하지 않는다. 이 one-way publication이 report SHA → final config SHA →
analytical evidence 순서를 보존하면서 Git-SHA 고정점 문제를 피한다.

## 4. ActivationRecord와 provenance 조립

`ActivationRecord.evidence_files`는 정확히 아래 **staged runtime roster**를 사용한다. 각 digest는 파일 bytes의
`"sha256:" + sha256`이며 scientific gate가 파일을 다시 읽어 검증한다.
`ActivationRecord.approved_git_sha`는 run spec에서 이미 runtime HEAD와 대조한 **full exact commit**을
사용한다. 두 analytical report의 `git_sha`도 이 값과 정확히 같아야 한다.
`ActivationRecord.approved_sequence_mapping_sha256`는 같은 run spec의 frozen
`sequence_mapping_digest`를 사용하며, phi-rank report의 `sequence_mapping_sha256`와 정확히 같아야 한다.
또한 report의 `esm_model`은 등록 config의 `factor_z.esm_model`에 지정된 mean-pooling encoder와 일치해야 한다.

| requirement | evidence file |
|---|---|
| `real_norman_phi_rank_and_condition_report` | `$ACTIVATION_EVIDENCE_STAGE/real_norman_phi_rank_report.json` |
| `regime_specific_detectable_effect_analysis` | `$ACTIVATION_EVIDENCE_STAGE/real_norman_detectable_effect_report.json` |
| `finalized_norman_data_card_and_sha256` | `$ACTIVATION_EVIDENCE_STAGE/norman_compose_k562_v1.json` |
| `gears_cpa_reproducible_dependency_lock` | `$ACTIVATION_EVIDENCE_STAGE/gears_cpa_dependency_lock.json` |
| `independent_compose_outcome_store_and_access_audit` | `$ACTIVATION_EVIDENCE_STAGE/outcome_store.py` |
| `phase2_plan_metric_leakage_and_seal_integration_tests` | `$ACTIVATION_EVIDENCE_STAGE/test_phase2b.py` |

마지막 네 정적 evidence는 clean detached `C`의 해당 tracked bytes를 stage로 byte-identical 복제한다. 앞의
두 report는 `--out "$ACTIVATION_EVIDENCE_STAGE/<name>.json" --git-sha "$APPROVED_GIT_SHA"`로 **직접**
생성한다. 어느 production command도 `docs/activation-evidence/`에 쓰지 않는다. 그 tracked 디렉터리의
기존 파일은 historical development snapshot이며 runtime source가 아니다.

ResolvedRunSpec의 `scientific.activation_evidence`는 위 여섯 absolute normalized staged path와 각 byte SHA,
owner identity를 결속하고, spec identity는 `APPROVED_GIT_SHA`, `FINAL_CONFIG_PATH`의 canonical config SHA와
함께 검증된다. Spec 승인 뒤에는 stage의 어떤 byte도 바꾸지 않는다. 변경이 필요하면 새 fresh root,
새 spec/approval, 필요 시 새 `C`를 사용한다.

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

**Activation evidence lineage 주의 (2026-07-21).** 현재 committed `real_norman_phi_rank_report.json`·
`real_norman_detectable_effect_report.json`은 canonical `config_sha256=d8c65ac4…`, `activation=BLOCKED`,
git `79b01e0`/`82a9c83`를 내장한 **pre-activation development snapshot**이다. 최종 실행 config의
authoritative canonical digest는 `load_compose_phase2_config`가 최종 bytes에서 다시 계산한다.
approximation-bias report SHA finalization(null→값)이 config raw bytes를 바꿔 과거 `a4700194…`도 실행
digest로 재사용하지 않는다. (GI secondary 정의 정정은 config2 코드 상수·YAML 주석만 바꾸므로
`config_sha256 = sha256_json(raw)`에는 영향이 없다.) 기존 evidence값(`d8c65ac4…`)은 activation flip
(`d507a09`) 이후에도 config parsed 구조가 A2 task 5(`42d71ce`: gears/cpa에 `prediction_representation`·
`approximation_bias_report_sha256` 추가)에서 바뀌어 canonical digest가 재차 이동했다. (raw file-bytes sha는
canonical `config_sha256`과 다른 값이니 lineage 비교에는 쓰지 않는다.) Scientific guard는 evidence 파일
*bytes*를 recorded hash에 대조한 뒤 두 config-bound Norman report의 versioned schema,
`protocol`·`config_sha256`·owner-approved exact `git_sha`·`activation=READY`를 파싱한다. Rank/full-grid,
measurability, 20-pair/50-cell power booleans은 재계산하고 data-card digest 및 두 report의 split counts도
교차 검증한다. 따라서 old-config, old-code 또는 `activation=BLOCKED` evidence는 fail-closed된다.
§2.5의 "config digest가 바뀌면 evidence 결속 재생성" 규칙은 **이미 발효**됐다:
pod에서 real Norman data로 두 evidence를 **staged final active config** 하에 재생성하고, 아직 null인
requirement(config `power_status`, GEARS/CPA `environment_status`, GEARS `approximation_bias_report_sha256`)를
실데이터로 확립해 모든 ActivationRecord requirement가 active run identity에 결속된 non-empty evidence hash를
갖도록 한다. rank/power/bias는 어차피 pod-only Norman data가 필요하므로 재생성은 자연스러운 pod 단계다.
재생성한 bytes를 tracked snapshot에 덮어쓰거나 후속 evidence commit을 만들지 않는다.

**Approximation-bias one-way carrier.** Probe-A 통과 후 bias-null config를 canonical hash하고 report를
생성한다. Finalizer로 config의 GEARS report-SHA leaf 하나만 채운 다음, ResolvedRunSpec에 같은 report의
absolute path와 byte SHA를 선언한다. Carrier load와 `phase2b` 진입은 seal 전에 report 전체 schema,
self-checksum, pair/GI roster 정렬, bootstrap accounting, fairness coherence, contract/basis/Git provenance를
재검증한다. Config가 SHA를 pin했는데 선언/path가 없거나 어느 결속이라도 다르면 즉시 중단한다. 이 단계에서
sealed source를 열거나 audit을 생성해서는 안 된다.

## 5. Phase-2a — seal closed

production driver의 `phase2a` subcommand(`--run-spec --approved-artifacts-root --run-dir`)를 실행한다.
내부적으로 다음을 수행·검증해야 한다.

1. run directory entry roster, 모든 digest, role count, pair alignment, response dimension,
   exact roster와 backend availability를 검증한다.
2. `build_subprocess_fit_payload`는 keyword-only로 호출한다. §2.1의 확장 schema가 merge된 뒤에는
   driver가 canonical OOF fold assignment와 fit-role artifact를 함께 결속해야 한다.
3. 각 backend에 `configure_payload(payload)`를 호출하고 `provenance_manifest`를 확인한다.
4. `run_phase2a(..., baseline_adapters={"gears": ..., "cpa": ...})`를 실행한다.
5. `model_factories`에는 L1/L2/L3/id_only만 둔다. GEARS/CPA stand-in은 금지한다.
6. 결과가 `FUTILITY_STOPPED`(exit 20)이면 artifact를 백업·보고하고 종료한다. **Phase-2b 금지.**
7. `CONTINUE`(exit 0)일 때만 frozen bundle, method lock, ledger, worker/payload/prediction checksum과
   `sealed_access_count == 0`을 독립 검증한다.
8. Phase-2a 산출물을 object storage에 업로드하고 다운로드 재검증을 수행한다.

`CONTINUE` 확인 후, canonical order대로 production driver의 `preflight` subcommand를 실행한다.
`preflight`는 `phase2a`가 만든 frozen prediction bundle(`futility_status=='CONTINUE'`)을 검증하고,
성공하면 §6의 `seal_confirmation_manifest.json`을 write-once로 설치한다. `preflight`가 실패(exit 10)하면
Phase-2b를 호출하지 않는다.

## 6. Final pause — human confirmation

`preflight` subcommand가 성공하면 seal 접근 전 마지막 단계로 `<run_dir>/seal_confirmation_manifest.json`을
write-once로 설치한다. 이 manifest가 화면과 파일에 다음을 담아 출력해야 한다.

- exact Git SHA와 clean status
- run ID/config/data/manifest/sequence/feature/factor/response/model/bundle checksums
- exact method/comparator roster와 selected hyperparameters
- GEARS/CPA worker/config/resource/env/payload/prediction checksums
- double/single pair counts와 ordered seal request checksum
- Phase-2a CONTINUE 및 access count 0
- 비어 있는 run directory, 존재하지 않는 terminal/pre-access snapshot, 비어 있는 seal audit
- artifact backup destination과 가용성
- self-excluding `confirmation_checksum` (manifest payload 전체의 SHA-256; manifest 자신은 제외하고 계산)

두 번째 운영자가 manifest를 대조한 후, `seal_confirmation_manifest.json`에 적힌 정확한
`confirmation_checksum` 값을 `phase2b`의 `--confirm-seal`에 confirmation token으로 입력한다.
**run ID나 다른 값을 대신 입력하지 않는다** — driver는 run-id-only 토큰이나 checksum 불일치를
명시적으로 거부한다(pre-seal rejection, seal 미소비). 불일치하거나 확신할 수 없으면 중단한다.
“일단 열고 확인”은 금지한다.

## 7. Phase-2b — single seal open

production driver가 내부적으로 다음 순서를 강제해야 한다.

1. activation evidence 파일과 clean SHA 재검증.
2. `run_phase2b` preflight와 composite upstream gate.
3. pre-access provenance payload+checksum과 seed-variability artifact의 실제 file SHA를
   `phase2b_pre_access_ledger.json`에 원자적 write-once 저장하고 재독출.
4. double/single exact union에 대해 outcome store의 durable audit claim을 먼저 원자적으로 설치·검증하고,
   그 audit reference로 terminal의 access를 확정한 뒤 claim-bound materialization을 한 번 수행한다.
   audit 설치 전 실패는 pre-access failure(count 0)이며 `ABORTED_AFTER_SEAL`로 기록하지 않는다.
   confirmation 뒤 source는 `O_NOFOLLOW` regular-file descriptor로 한 번 열어 hash하고, 그 descriptor를
   닫지 않은 채 fd-backed path(`/proc/self/fd/N` 또는 `/dev/fd/N`)로 obs 검증과 row materialization을
   수행해야 한다. 따라서 hash 후 원래 pathname이 교체되어도 검증·채점 바이트가 바뀌지 않는다.
   obs label 해석은 audit claim 전에는 금지하며, 불일치는 seal이 소비된
   `ABORTED_AFTER_SEAL`(count 1)이다.
5. 두 regime을 분리 채점하고 double-unseen만 verdict에 사용.
6. on-disk pre-access checksum, seal audit run/request checksum, result checksums 교차검증.
7. complete provenance payload를 내장하고 terminal SHA를 내부 provenance에서 제외한 비순환 구조로
   정확히 하나의 terminal artifact(`COMPLETE`, `INVALID`, `ABORTED_AFTER_SEAL`) 기록.
8. §2.4의 finalizer로 registered summary와 최종 ledger를 write-once 저장·재독출하고, terminal/summary/
   ledger SHA를 결속한 durable commit marker를 마지막에 설치·검증한다.

`INVALID`나 `ABORTED_AFTER_SEAL`도 seal 소비 결과다. 수정 후 재실행하지 않는다.

### 7.1 Crash recovery — `recover` subcommand

`phase2b` 실행 중 프로세스가 죽어 seal은 소비됐지만(protocol-global audit 존재) durable terminal/commit
marker가 미완결일 수 있다. 이 경우 upstream stage를 재실행하지 않고
`recover --run-dir RUN_DIR --seal-audit-path SCIENTIFIC_PROTOCOL_AUDIT`만
실행한다. `recover`는 새 seal을 열지 않으며 기존 audit로부터 다음만 수행한다.

- terminal과 durable commit marker(`phase2b_durable_commit.json`)가 이미 있으면 재검증만 하고 아무것도
  다시 쓰지 않는다.
- terminal은 있으나 marker가 없으면 byte-identical 재파생으로 marker만 write-once 설치한다(divergence는
  fail-closed).
- mode-specific audit은 있으나 terminal이 없는 crash 상태(`audit=1 / terminal=0`)면 `ABORTED_AFTER_SEAL`
  terminal을 합성해 기록한다.

`recover`가 `phase2b_durable_commit.json` 존재+검증까지 확인해 COMPLETE로 판정하면 exit 0, 그 외
non-COMPLETE 종결이나 실패는 exit 30이다. `recover`도 seal을 다시 열지 않으므로 §1의 write-once/재실행
금지 불변식이 그대로 적용된다.

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
