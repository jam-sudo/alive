# COMPOSE 단일 production driver (sub-project C) Design

> **문서 역할:** dev-stage 구현·검증 계약 (scientific claim contract 아님)
> **개정일:** 2026-07-07
> **상태:** NEEDS-IMPLEMENTATION — §0.1 선행 blocker와 본 문서 acceptance gate가 모두 구현·검증되기 전
> production sealed run 금지
> **상위 protocol:** `COMPOSE-K562-v1` (ACTIVE)
> **상위 계약:** pod sealed-run runbook
> `docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md` §2.3, §5, §6, §7
> **거버넌스:** `CLAUDE.md`#invariants, #provenance, #compute, #agent

## 0. 목적과 범위

이 서브프로젝트는 runbook §2.3의 release blocker를 해결한다: sealed run을 REPL이나 수동 객체
조립 없이 재현 가능하게 실행하는 **단일 committed production driver**가 없다는 것. Driver는 과학 계산을
재구현하지 않지만, 어떤 bytes·identity·승인 manifest가 실행됐는지를 terminal까지 끊김 없이 결속한다.

driver의 세 normal subcommand(`phase2a`/`preflight`/`phase2b --confirm-seal`)는 immutable
**ResolvedRunSpec** 하나를 공유한다. `recover`는 오직 `run_dir`의 write-once recovery artifacts를 소비한다.
각 command는 이미 존재하는 library entry point(`run_preflight`, `run_phase2a[_fixture]`,
`run_phase2b[_fixture]`, `recover_phase2b_durable_outputs`)와 D1(durable ledger)/D2(seed variability) 기계를
조립·호출할 뿐, 과학 계산을 재구현하지 않는다.

이 작업은 실제 seal을 열거나 sealed 결과를 재계산하지 않는다. driver의 orchestration·assembly·
fail-closed 로직 전체를 MacBook에서 synthetic fixture로 검증한다(`CLAUDE.md`#compute). pod에서의 유일한 차이는
ResolvedRunSpec이 실제 artifact를 가리키는 것이다. Fixture template의 `mode`를 현장에서 바꿔 scientific
run으로 승격하는 행위는 금지한다. Gate PASS는 scientific verdict가 아니다.

### 0.1 선행 library blocker(C0, driver 구현 전 필수)

> **상태(2026-07-08): C0 COMPLETE + MERGED.** 아래 7개 code-fix(#1 preflight leg·#3·#4·#5·#6·#7·#8)가
> 모두 구현·독립 review·science-dev gate(13/13 PASS)를 거쳐 `compose-production-driver`(@ `66c2dfb`)에
> 병합됐다. 따라서 driver의 library blocker는 해소됐고 scientific `phase2b` 구현이 인가된다. **#5는 forward
> terminal lifecycle이 crash 상태(burned audit + 잔존 lock)를 설계상 거부하므로, owner 승인 아래 seal-critical
> `terminal.py`에 recovery 전용 sanctioned API `Phase2bTerminal.recover_aborted_after_seal`를 추가해
> 해소했다**(ABORTED-only, seal 미개봉, burned audit에서 count 유도). 이는 아래 #5의 행위 계약(audit
> claim+pre-access ledger로 `ABORTED_AFTER_SEAL` 생성 후 finalize)과 일치하며, 구현 위치만 durable.py에서
> terminal.py API로 확장된 것이다.

Driver는 아래 결함을 우회하거나 wrapper에서 숨기지 않는다. 해당하는 library 결함은 driver 구현 전 library
계층에서 먼저 수정되고 negative test가 green이어야 한다(어느 항목이 code-fix 대상이고 어느 것이
설계규칙·기구현인지는 아래 'Code-fix 범위 정리' 참조).

1. `run_preflight`가 `ledger.run_id == bundle.run_id == recomputed_run_id`와
   `ledger.config_sha256 == config.config_sha256`를 명시적으로 검증한다(현재 `preflight.py:398-425`는
   recomputed를 `bundle.run_id`에만 비교하고 ledger 자체 header는 안 본다). Durable finalizer의
   pre-access-header↔terminal-provenance 재대조는 **이미 구현**되어 있으므로(`durable.py:788-819`) 이 항목의
   대상이 아니다.
2. **(library 수정 아님 — C 설계규칙)** phase2a의 cross-process ledger 영속화는 `RunLedger.write`(평범한
   overwrite)가 아니라 canonical bytes를 `atomic_write_once`로 설치하고 byte-for-byte 재독출하는 기존 패턴
   (`persist_pre_access_ledger` `provenance2.py:502-517`)을 재사용한다. COMPOSE cross-process path는 이미
   `RunLedger.write`를 쓰지 않으므로(그것은 legacy TG-K562 CLI 전용) merged code 수정 대상이 아니고, 재독출은
   `RunLedger.read`와 byte-호환된다(`durable._canonical_bytes`). 이 항목은 §1 설계규칙으로만 두고 C0
   code-fix 목록에서 제외한다.
3. `ComposeOutcomeStore` 생성 전에 pair-index의 각 row **perturbation label이 source obs의 canonical pair와
   일치**하는지 검증한다. 현재 store는 dtype·range·**cross-pair row 중복**(`outcome_store.py:334-339`)·manifest
   key 집합까지는 검사하나 `source.obs` label 정합은 전혀 안 본다(`298-384`). 즉 누락된 건 중복이 아니라
   **obs-label 정합**뿐이므로 그 검증만 추가한다.
4. fixture 판정을 caller가 추가할 수 있는 `_compose_fixture_marker` boolean 하나에 맡기지 않는다. 전용
   fixture store/factory와 committed synthetic corpus digest allowlist를 사용한다.
5. D1 recovery가 durable audit claim 이후 terminal 확인 전 process death(`audit=1, terminal=0`)를 처리한다.
   이 상태에서는 immutable audit claim + pre-access ledger만으로 `ABORTED_AFTER_SEAL` terminal을 생성한 뒤
   durable finalize한다. Outcome을 다시 열거나 verdict를 재계산하지 않는다.
6. **(defense-in-depth, 낮은 severity)** Durable finalizer가 terminal의 `final_result_checksum`을 구성하는
   정확한 5개 field를 재계산하고, registered-summary 내부 schema/roster도 version별로 검증한다. 현재는
   whole-body `terminal_payload_checksum`에 transitive 결속되어 post-hoc tamper는 이미 잡히고
   (`durable.py:732-748`), self-consistent한 buggy/malicious **writer**만 통과하므로 우선순위는
   #3/#4/#5/#8보다 낮다.
7. **(구조강화, 실무완화)** D2 preflight가 `(method, seed, fold)` execution record의 중복을 거부하고 exact
   Cartesian product와 top-level/summary seed·artifact roster 일치를 검증한다. 현재는 membership+count만
   검사해(`seed_variability.py:2000-2012/2025-2030`) 중복 1+누락 1이 통과 가능하나, 정상 생성 report는
   dup이 없어 실무 위험은 낮다.
8. Sealed scoring은 verdict용 5-comparator family와 별개로 frozen 9-method roster 전체의 descriptive MSE를
   두 regime에서 계산·보고하고 summary validator가 exact roster를 강제한다.

**Code-fix 범위 정리(코드 대조 결과).** merged code에서 실제 수정이 필요한 항목은 #1(preflight leg만)·#3
(obs-label leg만)·#4·#5·#6·#7·#8이다. #2는 설계규칙(§1)이고 #1의 durable leg는 이미 구현되어 있어
code-fix에서 제외한다. #6/#7은 defense-in-depth이라 #3/#4/#5/#8보다 우선순위가 낮다. 이 7개 library
fix는 seal-critical merged code(`outcome_store`/`durable`/`seed_variability`/`scoring2`/`preflight`)를
건드리므로 **driver와 한 plan에 묶지 않고 별도 `C0` plan(SDD→review→science-dev gate)으로 먼저 처리하고
그 다음 driver(C) plan을 실행한다** — D1/D2 선례대로 coherent unit당 plan 하나. 단 C0의 #1 preflight-leg
fix는 driver가 ledger에 추가하는 artifact name(`resolved_run_spec` SHA, runtime `execution_id`, pair-index
SHA, phase2a seed-report SHA; §3.1)과 lockstep이어야 하므로, 두 plan은 **ledger artifact-name roster를 공유
계약으로 고정**한다.

하나라도 미완료면 sub-project C는 fixture integration까지만 수행할 수 있고 scientific `phase2b` command는
활성화하지 않는다.

### In scope

- `scripts/run_compose_k562_phase2.py` — `phase2a`/`preflight`/
  `phase2b --confirm-seal <confirmation_checksum>`/`recover` 네 subcommand + testable `main(argv) -> int`
- committed **RunSpecTemplate** schema + PREPARE가 생성하는 immutable **ResolvedRunSpec** loader/validator
- write-once `seal_confirmation_manifest.json` 생성·검증과 exact manifest checksum confirmation
- versioned pair-index manifest 검증 및 source obs↔pair row alignment 인증
- 각 method의 `ExecutionIdentityLock`을 실제 파일 digest에서 조립하는 assembler + subprocess
  `BaselineAdapter` 조립
- committed **fixture builder** — bounded synthetic stage-1 artifact set + fixture ResolvedRunSpec 생성.
  **1회성 corpus 생산자**다(write-once fit-role 포함, §7.1). driver의 세 process는 이걸 재실행하지 않는다.
- committed **carrier loader** — 각 독립 process가 ResolvedRunSpec의 pre-seal on-disk stage-1 artifact
  (`phase2a_inputs`·response artifact·dev-store source/manifest·pair-index manifest)에서 필요한 in-memory
  객체(`Phase2aInputs`·`ResponseSpace`·`FitRoleArtifactSpec`·pair-index dict)를 declared digest 검증과
  함께 **재조립**한다 — §1.1 step 3의 구현. fixture builder가 한 번 disk에 쓴 산출물을 세 process가
  rebuild가 아니라 이 loader로 load한다. **raw→artifact 조립만 PREPARE(아래 out-of-scope)이고, 선언된
  artifact를 ResolvedRunSpec path+digest로 disk-load하는 것은 driver(C)의 몫**이다(§10 문서 충돌 조정 참조).
- local **mini e2e** — 실제 CLI를 세 독립 subprocess로 실행해 `phase2a → preflight → phase2b`를
  fixture mode·stub `{gears,cpa}` adapter로 구동하는 integration test. 각 process는 carrier loader로
  stage-1을 disk에서 재조립한다(in-memory carrier 공유 없음 → §4 seal 격리 유지).

### Out of scope (PREPARE는 별도 sub-project)

- **raw Norman → `Phase2aInputs`/factor bank/response artifact/fit-role artifact/pair manifest/pair-index
  manifest 조립(= PREPARE)**. 이 stage-1 산출물은 driver에게 ResolvedRunSpec 입력(path+digest)으로 들어온다.
  로컬에서는 fixture builder가 synthetic으로 만들고, pod에서는 별도 PREPARE sub-project가 실데이터로
  만든다. §10의 문서 충돌 조정을 참조.
- 실제 GEARS/CPA worker 구현(sub-project B, pod-only)·GO-graph·실제 worker-side digest·실제 Norman
  load·실제 sealed run·object-storage upload
- verdict threshold와 primary inference 방법 변경. 단 §0.1의 D1/D2 안전·검증 결함 수정은 선행 in-scope

## 1. 아키텍처 — thin verify-and-assemble, 3개의 독립 normal process + recovery

### 1.1 CLI와 종료 의미

```text
python scripts/run_compose_k562_phase2.py phase2a  --run-spec RESOLVED --approved-artifacts-root ROOT
python scripts/run_compose_k562_phase2.py preflight --run-spec RESOLVED --approved-artifacts-root ROOT
python scripts/run_compose_k562_phase2.py phase2b   --run-spec RESOLVED --approved-artifacts-root ROOT \
  --confirm-seal <confirmation_checksum>
python scripts/run_compose_k562_phase2.py recover   --run-dir RUN_DIR
```

Fixture tests만 fixture builder가 반환한 tmp root와 fixture ResolvedRunSpec을 사용한다. `main(argv)`는
`0=요청 단계 성공`, `10=pre-seal validation 거부(seal 미소비)`, `20=FUTILITY_STOPPED(정상 종료,
phase2b 금지)`, `30=post-seal INVALID/ABORTED 또는 durable export 미완료`를 반환한다. 예외 class와 stage는
stderr에 기록하되 outcome array·cell value·per-pair error는 출력하지 않는다.

Normal path의 세 subcommand는 하나의 ResolvedRunSpec과 하나의 `run_dir`을 공유하되 **독립 프로세스**로
호출된다. `recover`는 run_dir의 immutable terminal/pre-access/audit artifact만 소비하며(단
audit=1·terminal=0이면 §3.4대로 `ABORTED_AFTER_SEAL` terminal을 write-once로 **생성**할 수 있다)
ResolvedRunSpec이나 outcome store를 다시 열지 않는다. Normal subcommand는 동일한 4단계를 따른다. 이 문서의 **MUST**, **MUST
NOT**, **SHOULD**는 각각 필수, 금지, 정당화가 있어야 이탈 가능한 요구사항이다.

1. ResolvedRunSpec의 canonical bytes, schema, self-checksum과 파일 SHA를 검증한다.
2. 해당 command가 허용받은 pre-built artifact만 읽고 실제 bytes digest와 선언값을 대조한다. `phase2a`와
   `preflight`의 raw asset 접근은 provenance용 sequential byte-hash capability로 제한하고, AnnData/backed
   parser·row materialization·outcome-store capability는 부여하지 않는다(§2.2).
3. 해당 command에 필요한 in-memory 객체만 조립한다. `phase2a`는 non-sealed development store,
   `preflight`는 store 없음, `phase2b`만 sealed store를 조립한다. 공통 객체는
   `FrozenPredictionBundle`, `Phase2aInputs`, `RunLedger`, adapters, `ExecutionIdentityLock` 중 필요한 부분집합이다.
4. subcommand별 exact state roster(§7)를 검증하고 library entry point를 호출한 뒤 산출물을 write-once로
   저장·재독출한다. 허용되지 않은 기존 파일 하나라도 있으면 entry point 호출 전에 abort한다.

`phase2a`는 `run_phase2a`의 `bundle_path`로 `FrozenPredictionBundle`을 canonical JSON으로
persist하고(`freeze.FrozenPredictionBundle.write`), OOF manifest와 development seed-variability report도
함께 쓴다. `preflight`와 `phase2b`는 `FrozenPredictionBundle.load(path)`로 다시 읽어 checksum을 재검증한
뒤 소비한다. 프로세스를 분리하는 이유는 `preflight`/`phase2a`가 어떤 sealed store와도 메모리를 공유하지
못하게 하기 위함이다(§4).

**upstream `RunLedger` cross-process 전달(필수).** `run_preflight`과 `run_phase2b`는 모두 phase2a가
fit 뒤에 채운 upstream ledger(특히 `effective_model_checksum`, frozen bundle/pair_manifest/response_space/
factor_bank checksum)를 요구한다(preflight.py, phase2b.py). 이 값들은 fit 이후에만 존재하므로 뒤의
프로세스에서 재조립할 수 없다. 따라서 phase2a는 완성된 `RunLedger`의 canonical bytes를 atomic
write-once로 `run_dir`에 persist하고, preflight와 phase2b는 이를 **`RunLedger.read`로 다시 읽는다.** ledger를 frozen
bundle에서 재구성하는 것은 **금지한다** — 그러면 preflight의 ledger↔bundle checksum 일치 검사가
tautology가 되어 무의미해진다. 재독출 후 artifact SHA뿐 아니라 ledger header의 run/config/environment
identity를 ResolvedRunSpec·bundle·현재 environment와 대조한다. Ledger 파일 SHA는 confirmation manifest와
pre-access provenance에 결속한다.

**실행 순서(data-flow 확인).** `run_preflight`은 `bundle.futility_status == "CONTINUE"`와 regime별
prediction을 검증하므로 **phase2a가 만든 frozen bundle을 소비한다** — 즉 preflight는 phase2a **뒤에**
독립 pre-seal gate로 실행된다. 따라서 driver의 canonical 순서는 **phase2a → preflight → phase2b**이며,
subcommand 이름의 나열 순서(preflight/phase2a/phase2b)와 다르다. `run_phase2b`는 동일한 `run_preflight`
gate를 내부에서 다시 실행한 뒤 seal을 연다(phase2b.py). runbook §5의 "preflight 먼저" 서술은 fitting 전
입력 sanity(digest/roster/backend availability) 개념 단계를 가리키며, frozen-bundle gate인
`run_preflight`과 구분된다 — 이 조정을 §10에 기록한다.

대안으로 검토했으나 기각한 설계: fit-role→phase2a→phase2b를 한 프로세스에서 수행하는 "fat" driver.
배선은 단순하나 seal 인접 phase들을 결합하고 runbook §5/§7이 요구하는 phase 간 upload→re-download→
verify 내구성을 무너뜨린다.

## 2. RunSpec 계약

### 2.1 Template과 resolved 실행물 분리

저장소에는 경로 변수·schema·허용 roster를 정의한 `RunSpecTemplate`을 commit한다. Concrete pod path와
실제 artifact digest를 담은 `ResolvedRunSpec`은 PREPARE가 생성하고 두 번째 운영자가 승인한 뒤 절대
수정하지 않는다. Fixture template의 `mode`를 편집해 scientific resolved spec을 만드는 방식은 금지한다.

ResolvedRunSpec은 canonical JSON(`sort_keys=True`, `separators=(",", ":")`)이고 exact top-level/nested
key roster를 가진다. `self_checksum`은 자신을 제외한 payload의 `sha256_json`; 별도로 파일 bytes SHA를
계산한다. 둘 다 phase2a ledger와 confirmation manifest에 기록하고, phase2b pre-access provenance와
terminal/durable marker까지 전달한다.

Scientific `run_id`의 기존 정의(config/data-card/raw/sequence)는 바꾸지 않는다. Final canonical file을
설치한 뒤 runtime에서
`execution_id = sha256_json({run_id, resolved_run_spec_file_sha256, approved_git_sha})`를 계산한다. 이 값은
ResolvedRunSpec **안에 저장하지 않아** file-SHA 순환참조를 피하고, phase2a ledger와 confirmation manifest에
기록한다. Bundle/model이 만들어진 뒤의 최종 실행 identity는 confirmation manifest checksum이 담당한다.

### 2.2 ResolvedRunSpec v1 exact schema

- identity: `schema="compose_resolved_run_spec_v1"`, `mode`, `protocol`, `run_id`,
  `approved_git_sha`, `run_dir`, `approved_artifacts_root`, `self_checksum`
- pre-seal path+file-SHA: `config`, `data_card`, `raw_asset`, `sequence_mapping`, `feature_bank`, `factor_bank`,
  `response_artifact`, `fit_role_artifact`, `phase2a_inputs`, `development_outcome_source`,
  `development_outcome_manifest`, `pair_manifest`, `pair_index_manifest`,
  `approved_sealed_input_attestation`
- run-produced fixed basenames(값까지 schema constant):
  `frozen_bundle="frozen_prediction_bundle.json"`, `oof_manifest="oof_fold_manifest.json"`,
  `phase2a_seed_variability_report="phase2a_development_seed_variability.json"`,
  `run_ledger="phase2a_run_ledger.json"`,
  `futility_report="phase2a_futility.json"`, `seal_confirmation_manifest="seal_confirmation_manifest.json"`;
  caller가 임의 basename을 선택하지 못한다
- run-identity digest: `config_digest`, `data_card_digest`, `raw_or_source_digest`,
  `sequence_mapping_digest`
- `expected_hashes`: 정확히
  `{response_space_checksum, factor_checksum, manifest_checksum, environment_checksum,
  data_card_checksum, raw_data_checksum, sequence_mapping_checksum}`
- method별 worker block: `env_python`, `worker_script` path+SHA, `import_name`, `worker_config` path+SHA,
  `resource_manifest` path+SHA, `requirements_lock` path+SHA, `adapter_artifact` path+SHA, 그리고 §5의 6-field
  identity lock. `adapter_artifact`는 launch되는 `worker_script`와 **구분되는** adapter/model 콘텐츠이며
  §5의 `adapter_sha256` 출처다(worker self-report의 adapter identity와 대조; runtime은 launched
  `worker_script` 파일을 별도 `worker_sha256`으로 검증한다, `baseline_subprocess.py`)
- scientific 전용: activation requirement→evidence path+`sha256:` digest exact roster, dependency manifest,
  device, precision, `sealed_input={source_path, expected_file_sha256, snapshot_id, audit_path}`. Fixture
  mode에서는 이 block이 없어야 한다
- fixture 전용: committed fixture corpus ID, builder-code digest와
  `sealed_input={source_path, expected_file_sha256, audit_path}`. Scientific mode에서는 이 block이 없어야 한다

각 pre-seal path+SHA field는 exact `{"path": str, "sha256": 64-lowercase-hex}` object다. Scientific driver는
out-of-band CLI `--approved-artifacts-root`를 필수로 받고, ResolvedRunSpec의 root가 그 canonical realpath와
정확히 같아야 한다. Spec이 스스로 trust root를 선택하게 두지 않는다. 모든 path와 run_dir는 이 root 아래의
normalized regular file/directory여야 한다. Symlink, device, FIFO, `..`, root 이탈을 거부한다. Fixture root는
test가 만든 tmp directory로 고정한다. Digest는 command-aware loader가 실제 bytes를 stream-hash해 대조하며
선언값만 신뢰하지 않는다.

`approved_sealed_input_attestation`은 PREPARE/owner가 승인한 canonical source path, expected source file SHA,
snapshot ID, source row-identity SHA와 pair-index file SHA를 담은 self-checksummed manifest다. ResolvedRunSpec의
`sealed_input` 값은 이 attestation과 byte-for-byte 의미가 같아야 한다. 단, `phase2a`/`preflight` loader는
sealed block에 대해 exact schema·lexical containment·attestation equality를 검사한다. `raw_asset`과 source가
같은 file이면 pre-seal에서 허용되는 유일한 추가 동작은 기존 `sha256_file`과 동등한 sequential byte-hash다;
H5AD/AnnData parser, backed access, obs/X/layer materialization은 금지한다. Source regular-file/root/digest는
pre-seal ledger에 결속하되, semantic row validation은 confirmation 이후 `phase2b` step 4에서만 수행한다.
따라서 preflight confirmation은 검증된 expected digest를 승인하고, phase2b가 승인 뒤 실제 bytes와 row
identity를 다시 확립한다.

### 2.3 Pair-index manifest v1

`pair_index_manifest`는 source file SHA, obs row-identity SHA, perturbation column, control/combo token 규칙,
canonical pair별 row indices와 row-ID digest, role, self-checksum을 포함한다. Pre-seal path는 manifest 내부
schema/self-checksum과 attestation binding까지만 검증한다. `phase2b`만 confirmation 이후 source를 backed
mode로 열어 각 row의 perturbation label이 해당 canonical pair와 일치하는지, row가 pair 간 중복되지 않는지,
pair union이 split manifest와 정확히 같은지 검증한다. 검증된 manifest file SHA는 ledger·pre-access
provenance·confirmation manifest에 기록한다.

### 2.4 Loader fail-closed

알 수 없는/누락/초과 key, mode별 forbidden block, command별 read-capability 위반, path 정책 위반, digest
mismatch, run ID 재계산 불일치,
또는 runtime `execution_id`와 downstream ledger/manifest의 불일치, stage-1 artifact 간
raw/gene/row/manifest identity 불일치는 entry point 호출 전에 abort한다.

## 3. subcommand와 §7 순서

### 3.1 `phase2a`

- `Phase2aInputs`(stage-1에서 조립) + **non-sealed `DevelopmentOutcomeStore`** + method별 stub-or-real
  `{gears,cpa}` `BaselineAdapter`를 조립한다.
- 각 adapter는 §5의 driver-assembled `ExecutionIdentityLock`을 실은 `SubprocessBaselineBackend`이며,
  `build_subprocess_fit_payload(...)` → `backend.configure_payload(payload)` → `BaselineAdapter(...)`
  순으로 만든다(runbook §5 step 2–3).
- `mode: fixture` → `run_phase2a_fixture(inputs, dev_store, expected_hashes=, config=, bundle_path=,
  baseline_adapters=, oof_manifest_path=)`; `mode: scientific` → `run_phase2a(...)`에 추가로
  `activation_record=`, `git_is_clean=`, `data_card_path=`, `raw_asset_path=`, `response_artifact=`를
  전달한다.
- **fixture/scientific 비대칭(자기검토에서 확인):** scientific은 `response_artifact=`를 별도
  인자로 넘기고, fixture는 `Phase2aInputs`에 내장된 `response_space_checksum`에 의존한다
  (`run_phase2a_fixture`에는 `response_artifact` 인자가 없다). driver의 dispatch가 이 차이를 처리한다.
- 결과가 `CONTINUE`이면 frozen bundle + OOF manifest를 atomic write-once persist·(pod에서) upload하고
  재독출·재검증한다. Post-fit `RunLedger`는 아직 in-memory로 유지하며 D2 결속 뒤 마지막에 설치한다. Ledger
  header는 ResolvedRunSpec의 run/config/environment identity와 같아야 한다. `FUTILITY_STOPPED`이면 exact
  schema `compose_phase2a_futility_v1`의
  `phase2a_futility.json`만 write-once 설치하고 **종료한다. phase2b 금지.**
- CONTINUE 후, frozen bundle에 고정된 OOF manifest 위에서 merge된 D2 harness
  `development_seed_variability(...)`를 dev roles·동일 `{gears,cpa}` adapter로 실행해 seed-variability
  report를 만든다. 이는 D2 기계의 orchestration일 뿐 새 과학 계산이 아니다. **filename 예약:** phase2a는 이
  report를 **canonical `development_seed_variability.json`이 아닌 고정 distinct path
  `phase2a_development_seed_variability.json`**에 쓴다 — canonical 이름은 phase2b의
  `bind_development_seed_variability`가 shared `run_dir`에 write-once로 쓰는 이름이므로 phase2a가 같은
  이름을 쓰면 e2e에서 write-once 충돌이 난다(seed_variability.py). **scientific `run_phase2b`는 phase2a의
  distinct-path report를 `seed_variability_report_path=`로 받아 pre-access ledger에 결속하며, 그 bind
  단계가 canonical 이름을 쓴다. Fixture mini-e2e만으로 이 scientific wiring을 대체하지 않는다. 별도
  no-seal integration test가 phase2a distinct report를 scientific pre-access binder에 전달해 canonical
  copy·byte SHA·ledger binding까지 검증한다.
- D2 report write/re-read가 끝난 뒤 in-memory ledger에 `resolved_run_spec` file SHA, runtime `execution_id`,
  pair-index file SHA, phase2a seed-report file SHA를 기록하고 `phase2a_run_ledger.json`을 **마지막으로**
  atomic write-once 설치한다. 따라서 preflight가 읽는 ledger는 모든 pre-seal 산출물을 결속한다. Phase2a 중간
  crash로 bundle/OOF/report 일부만 남은 run_dir는 재개하지 않고 abandoned 상태로 보존하며, 새
  ResolvedRunSpec/new run_dir로 다시 시작한다.
- **어떤 `ComposeOutcomeStore`도 생성하지 않는다.**

`{gears,cpa}` adapter 취급은 `_validate_baseline_adapters(required=not fixture_execution)`를 따른다:
fixture에서 adapter는 필수는 아니나, **공급하면 정확히 `{gears,cpa}`여야 한다.** mini e2e는 반드시
stub adapter를 공급한다(§6) — 그래야 `ExecutionIdentityLock` assembler와 payload-v2/worker-manifest
검증 경로가 실제로 실행된다.

### 3.2 `preflight`

**phase2a 뒤에** 실행되는 독립 pre-seal gate다(§1). Phase2a가 `run_dir`에 쓴 frozen bundle을
`FrozenPredictionBundle.load(path)`로 읽어 checksum을 재검증하고, phase2a가 persist한 upstream ledger를
`RunLedger.read`로 다시 읽어(재조립 금지, §1) `pair_manifest`/`config`와 함께
`run_preflight(bundle=, pair_manifest=, config=, data_card_digest=, raw_or_source_digest=,
sequence_mapping_digest=, ledger=, expected_response_dim=)`를 호출해 `EvaluationLock`을 받는다.
`run_preflight`은 `futility_status == "CONTINUE"`, method roster exact 일치, regime별 pair set/prediction
key/vector, response dimension, 재계산 run ID, bundle↔ledger checksum과 ledger header run/config/environment
identity를 검증한다. **어떤 종류의 outcome store도 생성하지 않는다.**

성공하면 exact schema `compose_seal_confirmation_manifest_v1`을 canonical JSON으로 write-once 설치한다.
Manifest는 run/execution ID, ResolvedRunSpec file SHA, exact Git SHA+clean status, config/data/manifest/
sequence/feature/factor/response/model/bundle/ledger/pair-index/seed-report checksum, method/comparator roster,
selected hyperparameters, worker/config/resource/env identity, double/single pair count와 ordered seal-request
checksum, `CONTINUE`, access count 0, forbidden-output absence, owner-approved `accepted_limitations` exact
roster를 포함한다. Method roster는 정확히
`[l1_bilinear_identifiable,l2_saturation,l3_hypernetwork,additive,no_change,perturbation_mean,id_only,gears,cpa]`,
verdict comparator roster는 정확히 `[additive,gears,cpa,id_only,l3_hypernetwork]`이며 order까지 고정한다.
이 두 roster는 `config2._EXPECTED_METHOD_ROSTER`/`_EXPECTED_COMPARATOR_FAMILY`와 정확히 같고 config가 이미
강제하므로, driver는 하드코딩 대신 config 상수를 참조해 drift를 피한다.
`confirmation_checksum`은 자신을
제외한 payload의 `sha256_json`이다. 화면에는 canonical payload와 full checksum을 출력한다.

### 3.3 `phase2b --confirm-seal <confirmation_checksum>`

seal 직전(runbook §6/§7) 순서로 재검증한다.

0. `run_dir/phase2b.lock`에 non-blocking OS exclusive lock(`flock`/동등물)을 획득해 phase2b/recover 동시
   실행을 막고 terminal handoff까지 유지한다. Process death가 lock을 자동 해제해야 하며 lock-file 존재
   자체를 prior execution 증거로 해석하지 않는다. Scientific artifact root는 PREPARE가 만든
   content-addressed **read-only mount/snapshot**이어야 한다. Driver는 mount read-only 상태와 snapshot identity를
   attestation/confirmation과 대조한다. 이 단계에서는 sealed source file 자체를 open/stat/hash하지 않는다.
1. scientific이면 clean-git + `activation_evidence` roster/hash를 재검증한다.
2. frozen bundle(`FrozenPredictionBundle.load`)과 upstream ledger(`RunLedger.read`)를 다시 읽어 Phase-2a
   `CONTINUE`, frozen bundle checksum, ledger header·artifact↔bundle 일치를 재검증한다.
3. write-once confirmation manifest를 읽고 exact schema/self-checksum/file SHA를 검증한다.
   `--confirm-seal` 토큰은 manifest의 full `confirmation_checksum`과 먼저 정확히 같아야 한다. Run ID만 입력한
   confirmation은 거부한다. 그 다음 현재 non-sealed files/environment와 attested sealed-input identity에서
   manifest를 재구성해 byte equality를 요구한다. 이 단계까지 sealed source access count는 0이다.
4. confirmation 성공 후에만 source를 `O_NOFOLLOW` regular-file descriptor로 열어 hash 전후
   `(device,inode,size,mtime_ns)`를 비교하고 attestation의 expected source digest와 실제 bytes의 일치를
   검증한다. Store는 같은 immutable snapshot만 소비해야 하며, 이를 보증할 수 없으면 생성 전에 abort한다.
   이어 pair-index manifest를 source obs에 대조하고 sealed store를 **이 함수에서만** 생성한다 —
   ResolvedRunSpec/fixture가 제공한 source + verified pair-index + manifest + audit path를 사용한다. **이때
   store의 `audit_path`는 고정된 run-상대 경로 `<run_dir>/audit.jsonl`(`SEAL_AUDIT_FILENAME`)이어야 한다:
   §3.4 `recover`가 live store 없이 동일 경로에서 burned audit을 독립 재구성하므로, 다른 경로로 생성하면 실제로
   소비된 seal이 fail-closed로 복구 불능이 된다(안전하되 stuck). TG-K562 CLI(`cli.py:167,288`)와 같은 규약이다.**
   Fixture면 §4 전용 factory를, scientific이면 일반 store를 사용한다.
   **`ComposeOutcomeStore`가 import·생성되는 유일한 함수이며 phase2b에서만 도달 가능하다(§4).** fixture
   builder는 store 객체가 아니라 sealed-outcome DATA만 만든다(§6).
5. `run_phase2b[_fixture](run_dir=, outcome_store=, frozen_bundle=, pair_manifest=, response_artifact=,
   config=, ledger=, ...)`를 호출한다. 내부에서 D1/D2 §7 전체(pre-access ledger → durable audit claim →
   terminal → durable finalize + commit marker)가 이미 강제된다.
6. Driver는 `phase2b_durable_commit.json`을 독립 재독출해 terminal/summary/final-ledger/pre-access-ledger/
   seed-report SHA와 marker self-checksum을 모두 재검증한 뒤에만 exit 0을 반환한다. 그 전에는 aggregate metric,
   verdict, per-pair 값 어느 것도 stdout/stderr로 내보내지 않는다. 성공 후에도 기본 출력은 terminal state와
   durable artifact paths/checksums뿐이며 scientific 내용을 보려면 별도 승인된 report command를 사용한다.

phase2b는 어떤 audit이든 소비할 수 있는 유일한 subcommand다.

### 3.4 `recover`

`recover`는 동일한 `phase2b.lock`을 획득한 뒤 recovery library entry point만 호출한다. 두 상태만 허용한다.

1. exactly-one terminal이 있으면 pre-access ledger, canonical seed report와 partial durable outputs를 검증하고
   byte-identical finalize를 재개한다.
2. terminal은 없지만 exact run-bound durable audit claim이 하나 있으면, audit claim과 pre-access provenance를
   검증해 `ABORTED_AFTER_SEAL` terminal을 write-once 생성하고 finalize한다. Audit은 §3.3이 고정한
   `<run_dir>/audit.jsonl`에서 재구성하며, 파일이 없거나 record가 0이면 pre-access failure로 fail-closed한다.
   Terminal 생성은 sanctioned `Phase2bTerminal.recover_aborted_after_seal`(ABORTED-only·seal 미개봉·burned
   audit에서 count/`seal_audit_reference` 유도·`pre_access_provenance_checksum`을 pre-access ledger의
   subset checksum에 결속)만 사용하고, `_finalize_aborted_terminal` 경로로 durable 마무리한다.

그 밖의 `terminal=0` 상태는 pre-access failure로 보고 아무 terminal도 만들지 않는다. 어느 경로도 outcome
source, pair-index, bundle prediction 또는 `ComposeOutcomeStore`를 로드하지 않으며 seal 재실행·verdict 재계산을
금지한다.

## 4. seal-safety (정밀)

**구조적 단일 생성점.** `ComposeOutcomeStore`는 phase2b에서만 도달 가능한 정확히 하나의 함수에서
import·생성된다. 한 test가 `preflight`/`phase2a` 코드 경로가 `ComposeOutcomeStore`를 참조하지 않음을
단언한다. 이로써 runbook §2.3의 "preflight와 phase2a는 seal handle을 생성·개봉할 수 없다"를 단언이
아니라 구조로 강제한다. 같은 test는 두 command에서 raw asset 접근이 digest-only reader로 제한되고
AnnData/backed parser·obs/X/layer materialization·sealed store 생성이 0회임을 spy로 단언한다. Pair-index의
source-row validation도 phase2b에만 존재한다.

**fixture는 real seal을 열지 않는다(구조적 보증).** Fixture path는 전용 `FixtureOutcomeStore`/factory만
받고, committed fixture corpus ID·source SHA·builder-code SHA allowlist를 검증한다. Scientific data-card,
raw digest, approved artifacts root 또는 activation evidence가 fixture spec에 나타나면 거부한다. 반대로
scientific path는 fixture block/type/source digest를 거부한다. 단순 `mode`, mutable marker, host에 real data가
없다는 가정은 보안 경계로 인정하지 않는다. Fixture는 tmp run_dir의 synthetic per-run audit만 소비한다.

## 5. `ExecutionIdentityLock` assembler (C forward-obligation #2 해소)

driver는 method별 6-field lock을 **실제 파일을 다시 해시한 controller-side 값**에서 조립해
`SubprocessBaselineBackend`에 out-of-band ground truth로 전달한다. ResolvedRunSpec 선언값은 expected
value일 뿐 ground truth 자체가 아니다. Worker self-report가 이 lock에 대조되어 divergence는 fail-closed된다.

| 필드 | 출처 | 로컬/pod |
|---|---|---|
| `prediction_representation` | config `baseline_representations[name]` | 로컬(committed config) |
| `environment_lock_sha256` | 실제 requirements lock bytes를 driver가 stream-hash | 로컬/pod |
| `adapter_version` | 별도 committed adapter manifest의 exact version | 로컬/pod |
| `adapter_sha256` | 실제 **`adapter_artifact`** bytes를 driver가 stream-hash(launched `worker_script`가 아님 — 그것은 runtime이 `worker_sha256`으로 별도 검증) | 로컬/pod |
| `config_sha256` | 실제 worker-config bytes를 driver가 stream-hash | 로컬/pod |
| `resource_sha256` | 실제 resource-manifest bytes를 driver가 stream-hash | 로컬/pod |

현재 dependency manifest에는 `adapter_version`이 없으므로 sub-project B가 versioned adapter manifest를
추가하기 전 scientific assembler는 fail-closed한다. `adapter_sha256`은 **launched `worker_script`가 아니라
별도 `adapter_artifact` bytes를 해시**한다: committed runtime(`baseline_subprocess.py`)은 lock의
`adapter_sha256`을 worker self-report의 adapter identity(`stub_worker.py`의 `_ADAPTER_SHA256`)와 대조하고,
launched `worker_script` 파일은 **별개 field `worker_sha256`으로** 재해시·검증한다 — 둘은 서로 다른 identity다.
Fixture ResolvedRunSpec도 stub 선언값만 믿지 않고 `adapter_artifact`(bytes가 stub의 self-reported
`_ADAPTER_SHA256`와 일치하도록 fixture builder가 기록)·stub config/resource/requirements-lock bytes를 직접
해시한다. 선언값·실제 digest·worker self-report 세 값이 모두 같아야 한다.

## 6. fixture builder + mini e2e

**fixture builder(committed).** bounded synthetic Norman-like **stage-1 입력과 store 구성 DATA**만 만든다:
`Phase2aInputs`(OOF selection 파라미터 포함), fit-role `.h5ad`, response artifact, pair manifest,
pair-index manifest,
non-sealed dev-store 구성용 `source_kind='synthetic_fixture'` 감사 DATA, sealed-outcome DATA(synthetic
source + pair_index + manifest + audit_path), 그리고 이들을 가리키는 fixture ResolvedRunSpec. **store 객체는 만들지
않는다** — `DevelopmentOutcomeStore`는 phase2a subcommand가, `ComposeOutcomeStore`는 phase2b subcommand가
이 DATA로부터 구성한다(§3.1/§3.3; sealed store 단일 생성점 §4 유지). frozen bundle·OOF manifest·
seed-variability report·terminal·ledger·commit marker는 fixture builder가 아니라 e2e가 driver를 실행해
만든다(run-produced).

**fixture run_id 고정.** `compute_compose_run_id`는 `config_sha256` + data-card/raw/sequence digest
네 값을 받는다(datacard.py). `config_sha256`은 committed config로 고정되고, builder는 나머지 세 digest를
한 곳에서 정한 뒤 그 네 값으로 `Phase2aInputs.run_id`(= `compute_compose_run_id`)와 fixture ResolvedRunSpec의
대응 digest를 파생한다. Phase2a가 결속한 run_id와 preflight/phase2b recompute가 일치한 뒤, e2e의
`--confirm-seal` 토큰은 preflight가 생성한 confirmation manifest checksum에서 별도로 얻는다.

기존 per-test fixture 조립을 하나의 committed 함수로 승격해 e2e가 scientific 조립을 충실히 반영하게 한다.
payload는 fixture bound(`_assert_fixture_payload`)를 넘지 않는다.

**mini e2e.** Parser/unit test는 `main(argv)`를 직접 호출한다. Cross-process integration은 실제 CLI를
`subprocess.run`으로 세 번 호출해 process memory가 공유되지 않음을 보장하며 다음을 단언한다.

- `CONTINUE` → frozen bundle + OOF manifest + durable commit marker + `COMPLETE` terminal
- seal-consumption count 의미(pre-audit 실패 → count 0/no terminal)
- futility → 종료, phase2b 미실행
- **activation 없는 scientific ResolvedRunSpec → sealed store 생성 이전에 fail-closed(count 0)**
- stub `{gears,cpa}` adapter가 공급되어 lock assembler + worker-manifest 검증이 실제로 실행됨
- **upstream ledger가 phase2a→preflight→phase2b 프로세스 간 round-trip되어 preflight의 ledger↔bundle
  checksum 일치 검사가 실제로 작동함**(phase2a가 쓴 ledger를 삭제/변조하면 preflight/phase2b가 fail-closed)
- preflight subcommand를 생략하면 confirmation manifest 부재로 phase2b가 store 생성 전에 거부됨
- confirmation 뒤 bundle/ledger/worker identity 중 하나를 바꾸면 기존 token이 거부됨
- phase2a/preflight에서 raw asset은 digest-only read만 발생하고 AnnData/backed row materialization은 0회임
- attestation source SHA와 실제 immutable snapshot bytes가 다르면 store 생성 전에 거부됨
- 실제 source digest/pair-index를 fixture mode에 넣거나 marker만 추가해도 fixture factory가 거부함
- pair 두 개의 row block을 교환하면 source obs alignment gate가 거부함
- wrong ledger run/config/environment header가 artifact SHA 일치 여부와 무관하게 거부됨

이는 새 coverage다 — 현재 committed된 phase2a→preflight→phase2b 연쇄 test는 없다.

## 7. fail-closed 표 (driver 계층, runbook §9 반영)

### 7.1 run-directory 상태 머신

Blanket "run_dir가 비어 있어야 한다" 규칙은 phase 간 공유 artifact와 모순되므로 사용하지 않는다. 각
subcommand는 direct-child basename의 exact required/allowed/forbidden roster를 검사한다.

- `phase2a`: `run_dir`에는 run-produced artifact가 없어야 한다(stage-1 입력은 approved root의 별도 immutable
  paths). CONTINUE 성공 시 정확히 `frozen_prediction_bundle.json`, `oof_fold_manifest.json`,
  `phase2a_development_seed_variability.json`, `phase2a_run_ledger.json`을 설치한다. FUTILITY_STOPPED이면 정확히
  `phase2a_futility.json` 하나만 허용하고 bundle/ledger/confirmation/seal artifacts를 금지한다. Pre-seal
  partial crash output은 재개·덮어쓰기하지 않고 abandoned로 보존한다.
- `preflight`: 위 네 phase2a artifact required; confirmation/terminal/audit/pre-access/durable 파일 forbidden;
  성공 시 `seal_confirmation_manifest.json` 하나만 새로 설치한다.
- `phase2b`: 위 네 artifact+confirmation required; terminal/audit/pre-access/durable 파일 forbidden;
  `phase2b.lock`은 ephemeral 허용. Confirmation 재검증 뒤에만 store를 생성한다. Audit destination은
  run-dir roster와 별도로 absent/empty·run-bound임을 검사한다.
- `recover`: `phase2b.lock`만 ephemeral 허용. exactly-one terminal 상태 또는
  `terminal=0 + exactly-one durable audit claim` 상태 중 하나여야 한다. 이미 생성된 registered summary/final
  ledger/commit marker의 부분집합은 crash-recovery 입력으로 허용하되 모든 existing byte가 intended byte와
  같아야 한다. Outcome store 생성과 seal 재개방은 forbidden이다.

모든 설치는 atomic write-once다. 이미 존재하는 intended bytes와 동일하더라도 normal subcommand는 재실행하지
않고 거부한다. Byte-identical idempotence는 명시적 `recover` 경로에만 허용한다.

| 조건 | 동작 |
|---|---|
| 알 수 없는/불일치 `mode` | abort |
| ResolvedRunSpec schema/self/file checksum 또는 artifact digest 불일치 | abort |
| `expected_hashes` key 집합(7개) 누락·초과 | abort(loader) |
| upstream ledger 부재 / header identity / bundle↔ledger checksum 불일치 | abort |
| command별 required/allowed/forbidden basename roster 불일치 | abort |
| phase2a `FUTILITY_STOPPED` 후 phase2b 호출 | 거부 |
| confirmation manifest 부재·변경 또는 token ≠ confirmation checksum | abort |
| scientific인데 activation evidence roster/path/hash 불일치 | `ScientificModeError`, abort |
| fixture corpus/type/digest allowlist 불일치 또는 payload bound 초과 | abort |
| pair-index row label/source identity/split union 불일치 | abort |
| execution lock 선언값 ≠ 실제 file digest 또는 worker self-report | abort |

seal 접근 이후 예외는 terminal `INVALID`/`ABORTED_AFTER_SEAL`을 남기고 재실행하지 않는다(D1이 강제).

## 8. pod 경계 / non-goal

C가 로컬에서 검증하는 것은 driver의 orchestration·assembly·dispatch·fail-closed **로직**이다. pod에서만
가능한 것: 실제 Norman data, 실제 GEARS/CPA worker(sub-project B), GO-graph, 실제 worker-side digest,
그리고 실제 일회성 seal 개봉. C는 template/loader/fixture e2e를 산출하고, PREPARE는 pod artifact로 별도의
scientific ResolvedRunSpec을 생성한다. Fixture spec을 편집해 재사용하지 않는다.

**PREPARE 의존성 증가(기록).** §2.2/§2.3의 capability 분리 때문에 PREPARE(별도 sub-project)는 이제
non-sealed `development_outcome_source`/`development_outcome_manifest`, `approved_sealed_input_attestation`,
versioned `pair_index_manifest`, content-addressed read-only snapshot까지 산출해야 한다. driver는 이들을
소비·인증만 하며 만들지 않는다 — PREPARE sub-project 범위가 그만큼 커졌음을 C0/C의 선행 의존성으로
기록한다.

## 9. 거버넌스와 검증

- SDD로 구현하며 seal 인접이므로 implementer·reviewer 모두 OPUS.
- 어떤 실제 seal도 열지 않는다. `src/`에 gears/cpa import 없음(driver는 `scripts/` 아래, `BaselineAdapter`
  seam + `stub_worker.py`만 사용).
- per-pair CI 없음. 실패/negative 결과 보존.
- §0.1·§6·§7의 positive/negative test를 모두 실제로 작성한다. 최소한 store 단일 생성점, fixture-real
  source 혼입, ledger header, pair-row swap, confirmation 생략/TOCTOU, ResolvedRunSpec/path/symlink,
  execution-lock 실제 file digest, D2 report binding, audit-terminal crash-window를 포함한다.
- Pair bootstrap의 평가 pair 간 gene-sharing 의존성은 독립 pair resampling의 coverage를 약화할 수 있다.
  Seal 전 owner가 (a) preregistered dependency-aware sensitivity amendment를 승인하거나 (b) primary 분석은
  유지하되 non-verdict sensitivity와 명시적 accepted limitation을 confirmation manifest에 포함해야 한다.
- 빌드 후 science-dev loop gate 실행(LOCAL ONLY).
- 관련 변경마다 CLAUDE.md#verify(unit/integration/leakage/provenance) 실행.

## 10. 문서 충돌 조정 (CLAUDE.md#sources)

`scripts/compose/build_fit_role_artifact.py`는 "real source/split assembly is the production driver's
job (sub-project C)"라고 적혀 있으나, runbook §3 step 8은 fit-role/feature/GO resource를 **pre-built
상태로 object storage에서 sync**한다고 규정하고, §5는 `Phase2aInputs`가 이미 존재한다고 가정하며,
결정된 pod-prep 순서의 C e2e는 `phase2a→preflight→phase2b`(prepare 없음)다. 따라서 이 spec은
**A1 stub의 "C's job" 문구를 stale로 판정**하고 PREPARE를 driver 상위(별도 sub-project)로 귀속시킨다.
이 조정을 runbook에도 한 줄 note로 반영한다(§2.3 옆). 이 변경 후 A1 stub 문구도 다음 별도 작업에서
갱신한다.

**preflight 순서 조정.** runbook §5는 "preflight를 먼저 실행"이라 서술하지만, library `run_preflight`은
`futility_status == "CONTINUE"`와 regime별 prediction을 검증하므로 phase2a가 만든 frozen bundle을
요구한다 — 즉 frozen-bundle gate로서의 `run_preflight`은 phase2a **뒤에**만 의미가 있다. 따라서 이 spec은
runbook §5 step-1의 "preflight"를 fitting 전 입력 sanity(개념 단계)로 읽고, driver의 `preflight`
subcommand를 phase2a 뒤의 독립 frozen-bundle gate로 규정한다(canonical 실행 순서 phase2a → preflight →
phase2b). 이 해석을 조용히 남기지 않고 runbook에서 두 gate의 이름을 각각 `input-sanity`와
`frozen-bundle preflight`로 바꾼다.

**runbook 필수 동기화.** 구현 PR은 같은 변경에서 runbook §2.3/§6/§9를 다음과 같이 고친다.

- `--confirm-seal <run_id>` → `--confirm-seal <confirmation_checksum>`; confirmation manifest와 `recover`
  command를 명시한다.
- blanket "빈 run directory" → 본 문서 §7.1의 command별 exact state roster로 바꾼다.
- production driver가 PREPARE를 수행한다는 표현 → pre-built immutable ResolvedRunSpec을 소비한다고 바꾼다.

이 문서 동기화가 끝나지 않으면 코드가 green이어도 release 상태는 `NEEDS-IMPLEMENTATION`이다.

## 11. Definition of Done / release gate

아래를 **모두** 만족해야 문서 상태를 `READY`로 바꿀 수 있다.

1. §0.1 C0 code-fix 항목(#1 preflight leg·#3·#4·#5·#6·#7·#8; #2는 설계규칙, #1 durable leg는 기구현)이
   production code와 regression test로 해결됨.
2. RunSpecTemplate/ResolvedRunSpec/pair-index/confirmation manifest의 versioned exact schema와 loader가 구현됨.
3. Scientific ResolvedRunSpec file SHA가 phase2a ledger→confirmation→pre-access provenance→terminal→durable
   marker에서 동일하게 확인됨.
4. `phase2a → preflight → phase2b` 세 독립 process e2e가 green이고(각 process는 carrier loader로 stage-1을
   disk에서 재조립하며 in-memory carrier를 공유하지 않는다) preflight 생략은 fail-closed함. 또한
   driver가 scientific store를 `audit_path=<run_dir>/audit.jsonl`로 생성하고, `audit=1/terminal=0` crash를
   재현한 뒤 `recover`가 `ABORTED_AFTER_SEAL`를 합성하는 e2e가 green이며, 다른 audit 경로로 생성하면 recover가
   복구 불능(fail-closed)임을 negative test로 고정한다.
5. Fixture e2e와 별도로 scientific no-seal assembly test가 activation/provenance/D2 report wiring을 검증함.
6. C의 로컬 gate에서는 **stub worker/config/resource/lock bytes**가 assembled lock과 일치하고, adapter
   manifest 부재 시 scientific assembler가 fail-closed함을 검증한다. 실제 GEARS/CPA
   worker/config/resource/requirements/adapter-manifest bytes와 lock 일치는 sub-project B가 versioned
   adapter manifest를 ship한 뒤 pod에서 확립하는 항목이며 C의 로컬 완료 조건이 아니다.
7. Exact 9-method roster는 freeze/scoring/descriptive summary까지 유지되고, verdict comparator family는 등록된
   5개와 정확히 일치함.
8. 전체 pytest, Ruff check, Ruff format check, worker locked-env integration, science-dev/spec-review gate green.
9. 독립 reviewer가 leakage, pair-row alignment, fixture separation, run/config identity, single seal, crash recovery,
   artifact schema versioning과 gene-sharing bootstrap limitation 처리를 확인함.
10. Runbook/CLAUDE.md/관련 A·D spec의 CLI, phase order, filename, recovery, seal-boundary 용어가 본 계약과
    일치하고 migration 설명을 제외한 실행 가능한 CLI/지시문에서 stale `<run_id>` confirmation이 0건임.
11. Owner가 exact Git SHA, scientific ResolvedRunSpec SHA, confirmation-manifest schema를 승인함.

PASS는 실행 준비가 됐다는 뜻일 뿐 scientific win을 뜻하지 않는다. Negative/FUTILITY/INVALID 결과도 같은
내구·provenance 계약으로 보존한다.
