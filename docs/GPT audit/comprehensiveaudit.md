# ALIVE 종합 감사

- **전체 교체 시점 (미 동부시간):** 08/20/2026 09:26:11 EDT
- **감사 시작:** 08/20/2026 09:01:56 EDT
- **감사 종료:** 08/20/2026 09:26:11 EDT
- **감사 기준 branch:** compose-audit-exactness-fixes
- **감사 기준 exact HEAD:** 2e60eef1f80740fdd310738a44f5f112ceb825ae
- **upstream:** origin/compose-audit-exactness-fixes (0 ahead / 0 behind)
- **origin/main 대비:** 0 behind / 8 ahead
- **시작 git status:** 브랜치 정상 추적, 아래 두 untracked 파일 존재
  - docs/GPT audit/comprehensiveaudit.md
  - docs/superpowers/2026-08-16-codex-claude-collaboration-proposal.md
- **종료 git status:** 시작 상태와 동일. 이번 감사는 canonical audit 파일만 전면 교체했으며 그 밖의 프로젝트 파일을 생성·수정·삭제하지 않았다.

## 결론

ALIVE source HEAD는 전날 감사와 동일하고 정적 검사 및 전체 로컬 테스트를 통과했다. 그러나 activation evidence가 명시적으로 불완전하고, confirmatory inference·seal materialization·L3/ablation 계약에 미해결 과학적 위험이 남아 있으므로 **scientific release readiness는 BLOCKED**, seal은 **UNOPENED / DO NOT OPEN**이다.

활성 finding은 **High 6건, Medium 7건, Low 1건**이다. 전날 High였던 sealed-source TOCTOU, fix sandbox .git, seal-guard closure는 각각 기각 또는 해결됐다. Claude 검수의 지적대로 날짜별 F-NN 대신 아래의 안정된 의미 기반 ID를 사용한다.

## 이번에 실제 확인한 범위와 집중 영역

- 추적 파일 363개 전체 구조를 훑었다: Python 261개, Markdown 66개, JSON/YAML/YML 17개.
- source, tests, configs, CLAUDE.md, spec/plan/runbook/readiness, uv.lock, activation evidence, provenance/artifact 계약을 교차 검토했다.
- 소스 변경이 없어도 compose inference, outcome store, stable-descriptor seal open, Phase2a/2b pair·row alignment, run identity, exact method/comparator roster, model ladder와 penalty 적용을 다시 추적했다.
- 전날 canonical 아래에 추가된 Claude 검수 블록을 읽고 각 주장과 인용 경로를 현재 tree에서 독립 재검증했다.
- 협력 자동화의 최신 audit-log HEAD 2c07a398cb06a0d6f198987d5919f74a695f4890 및 직전 수정 df0ff85cb4270a05de1fcdcb4eaa63e11839a7ae를 검토했다. 해당 저장소는 clean이었다.
- sealed evaluation, 실제 scientific run, 외부 데이터 접근, 네트워크 작업, 비용 발생 작업은 실행하지 않았다.

## 활성 finding

### Critical

없음.

### High

#### readiness.activation-evidence-incomplete — scientific mode의 필수 evidence가 불완전하다

- **근거:** configs/compose_k562_v1_phase2.yaml:127-131의 power_status는 unestablished_activation_blocker다. docs/activation-evidence/compose/gears_cpa_dependency_lock.json:8-10은 activation BLOCKED, run_gate.evidence_status=INCOMPLETE, seal_safety_status=UNVERIFIED를 선언한다. Norman phi-rank와 detectable-effect report는 현재 config SHA가 아닌 d8c65ac4…에 묶여 있다.
- **재현:** loader는 current config SHA 3faacafff963b221148a08cb18fb92f084d796fb80c5db2b3b3b25ea295cb3b9, method roster 9개, comparator 5개를 확인했지만 dependency activation은 BLOCKED였다.
- **영향:** runtime compatibility, row roster, sealed-pair disjointness, command/checkpoint/package/container identity가 release authority로 완결되지 않았다.
- **권고:** seal과 무관한 PREPARE/pod evidence를 최종 config/commit에 맞춰 재생성하고 COMPLETE 및 VERIFIED_ZERO_OVERLAP을 독립 검증한다.
- **현재 차단:** 예. scientific release와 seal open의 직접 blocker.

#### stats.pair-gene-dependence — primary pair bootstrap의 shared-gene 의존성이 coverage를 약화할 수 있다

- **근거:** configs/compose_k562_v1_phase2.yaml:119-125는 perturbation pair를 resampling unit으로 고정한다. src/alive/compose/inference2.py:170-178,252-288은 gene cluster 정보 없이 pair-error row를 alive.eval.bootstrap._replicate_indices로 i.i.d. 재표본한다. 올바른 primitive 경로는 src/alive/eval/bootstrap.py다.
- **증거:** 같은 gene이 여러 평가 pair에 반복되지만 resample은 이를 같은 cluster로 묶지 않는다. src/alive/compose/driver/preflight_cmd.py:102-115와 production-driver spec §9는 이 한계를 명시한다.
- **영향:** pair superpopulation에 대한 nominal simultaneous coverage는 독립성 위반으로 낙관적일 수 있다. limitation 표기는 투명성을 높이지만 coverage를 복구하지는 않는다.
- **권고:** dependency-aware sensitivity amendment를 사전등록하거나 confirmatory coverage 주장의 범위를 제한하고 non-verdict sensitivity를 함께 제시한다.
- **현재 차단:** confirmatory coverage를 그대로 주장할 경우 차단. owner가 spec §9 limitation 경로를 명시 승인한 분석은 제한된 지위로 보고 가능하다.

#### seal.claim-materialization-replay — 한 durable claim으로 observed payload를 반복 materialize할 수 있다

- **근거:** src/alive/compose/outcome_store.py:619-686은 persisted claim 검증 뒤 매 호출마다 pair rows를 다시 slice하며 consumed marker나 immutable cache가 없다. 같은 모듈 :14-22는 audit path당 정확히 한 번의 access를 계약한다.
- **재현:** synthetic-only temporary store에서 동일 claim을 두 번 호출한 결과 first=7, second=7, same_keys=True, audit_records=1이었다.
- **영향:** durable audit에는 한 access만 남지만 observed cells는 여러 번 materialize된다. one-time seal이 claim 횟수인지 payload read 횟수인지 불명확해지고 replay/crash/concurrency 감사성이 약해진다.
- **권고:** claim당 atomic consume-once 또는 한 번 만든 immutable payload cache를 계약하고 replay·동시성·crash recovery 테스트를 추가한다.
- **현재 차단:** 예. seal open 차단.

#### model.l3-contract-mismatch — 구현된 L3가 등록된 end-to-end hypernetwork가 아니다

- **근거:** docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md:209는 z/operator end-to-end hypernetwork를 요구한다. src/alive/compose/models.py:314-425는 fixed-Z symmetric feature 위의 tanh MLP다. docs/superpowers/2026-08-17-compose-ablation-ladder-decisions.md:3,138-141은 rename/spec amendment option B를 proposed로 두고 owner sign-off가 비어 있다.
- **영향:** 동일한 l3_hypernetwork 이름 아래 모델 class와 과학적 가설이 달라 사전등록 해석을 적용할 수 없다.
- **권고:** 등록 설계로 구현하거나 fixed-Z 모델로 이름·spec·config·report를 일괄 변경하고 변경 지위를 동결한다.
- **현재 차단:** 예. L3 confirmatory 해석 차단.

#### model.ablation-penalty-units — headline과 L2/L3 baseline이 같은 penalty 단위로 비교되지 않는다

- **근거:** src/alive/compose/phase2a.py:1537-1557은 headline에만 calibration_lambda_scale을 곱하고 id_only와 L3에는 raw selected lambda를 적용한다. docs/superpowers/2026-08-17-compose-ablation-ladder-decisions.md:69-124,138-141은 이 잔여와 owner 선택 A/D를 열어 둔다.
- **영향:** feature scale에 따라 regularization strength와 ablation ranking이 달라져 ladder의 공정한 비교가 보장되지 않는다.
- **권고:** bank를 공통 단위로 정규화하거나 claim을 제한하는 결정을 owner가 승인하고 config/runtime/report에 동일 반영한다.
- **현재 차단:** 예. ablation confirmatory 해석 차단.

#### collab.reviewer-network-envelope — reviewer write 격리는 개선됐지만 network·credential 경계가 넓다

- **근거:** /Users/jam/ALIVE-audit-log/bin/daily_review.sh:149-184는 reviewer를 sandbox 안에서 실행하고 actual ALIVE 쓰기를 커널 수준으로 차단한다. 그러나 /Users/jam/ALIVE-audit-log/bin/sandboxed.sh:21-25의 agent mode는 network를 명시적으로 열며, profile은 /Users/jam/.ssh만 read-deny하고 나머지는 allow default다. review-settings.json:79-102의 일반 Python/subprocess 허용은 tool-level deny를 우회할 수 있다.
- **증거:** daily_review.sh:164-172도 ALIVE read와 subprocess 우회가 남는다고 인정한다. 환경 scrub은 SSH agent와 Git credential helper만 제거하며 process가 가진 API credential이나 다른 readable credential source를 격리하지 못한다.
- **영향:** 사용자 요구의 ALIVE read-only/write 제한은 크게 개선됐지만 network restricted는 강제되지 않는다. 무인 reviewer가 임의 endpoint로 통신할 수 있다.
- **권고:** Claude API 전용 broker/proxy 또는 egress allowlist를 사용하고 reviewer에 직접 credential을 노출하지 않는다. write는 staging/pending과 tmp로 최소화한다.
- **현재 차단:** 예. unattended collaboration job 활성화 차단.

### Medium

#### collab.publisher-atomicity — canonical publish와 audit-log commit이 원자적이지 않다

- **근거:** /Users/jam/ALIVE-audit-log/bin/publish_review.sh:53-75는 합성/검증 후 canonical copy, audit-log copy, commit 순으로 진행한다.
- **영향:** 첫 copy 뒤 다음 단계가 실패하면 canonical과 history가 갈라지고 copy 도중 reader가 부분 파일을 볼 수 있다.
- **권고:** verified temp를 atomic rename하고 publication/commit을 recovery 가능한 state machine으로 묶는다.
- **현재 차단:** 자동 publish 신뢰성 차단.

#### collab.audit-metadata-schema-coupling — reviewer identity parser가 사람용 문구에 결합돼 있다

- **근거:** /Users/jam/ALIVE-audit-log/bin/daily_review.sh:58-64는 감사 기준.*HEAD라는 사람용 문구를 검색한다. 전날 canonical의 exact HEAD 형식에서는 probe 결과 AUDIT_HEAD=였지만, 이번 canonical을 감사 기준 exact HEAD로 고정한 뒤에는 exact SHA 추출이 통과했다.
- **영향:** 현재 판은 정상이나 문구가 다시 바뀌면 올바른 감사도 STALE 후보가 된다. parser와 audit writer 사이 machine schema가 없다.
- **권고:** machine-readable metadata key를 계약하고 40-hex exact match, missing/duplicate fail-closed 테스트를 추가한다.
- **현재 차단:** 현재 판에는 비차단, 향후 형식 drift 위험.

#### collab.review-job-disabled — ET 10:00 LaunchAgent가 비활성이다

- **근거:** launchctl print gui/501/com.alive.collab.audit-review는 exit 113, service not found였다.
- **영향:** Claude 검수는 수동 실행 없이는 돌지 않는다.
- **권고:** network envelope와 publisher atomicity를 먼저 닫은 뒤 load하고 next run/last exit를 확인한다.
- **현재 차단:** BLOCKED-BY-DESIGN. 현 시점 비활성은 안전한 선택이다.

#### automation.slot-dedup — ET 날짜만으로 scheduled 09시 slot을 중복 판정한다

- **근거:** 현재 heartbeat guard는 같은 ET 날짜의 canonical 교체 여부만 검사한다.
- **영향:** 09시 이전 수동 교체가 정규 09시 감사를 suppress할 수 있다.
- **권고:** metadata에 run_mode와 scheduled slot identity를 기록하고 (ET date, slot=09)로 dedupe한다.
- **현재 차단:** 아니오. 운영 재현성 저하.

#### driver.preflight-output-contract — manifest는 생성되지만 spec의 화면 출력 계약은 구현되지 않았다

- **근거:** docs/superpowers/specs/2026-07-07-compose-production-driver-design.md:369-380은 write-once manifest와 canonical payload/full checksum 화면 출력을 요구한다. src/alive/compose/driver/preflight_cmd.py:237-252는 manifest를 설치한 뒤 exit 0만 반환한다.
- **영향:** 전날의 “payload/checksum을 제공하지 않는다”는 표현은 과했다. durable artifact로는 제공되지만 operator 전달 채널이 spec과 다르다.
- **권고:** confirmation payload/checksum을 deterministic stdout으로 출력하고 snapshot test를 추가하거나 spec을 artifact-only UX로 변경한다.
- **현재 차단:** provenance UX/spec 일치에는 차단, manifest 무결성에는 비차단.

#### docs.collaboration-runtime-drift — proposal이 현재 구현과 권한 상태를 반영하지 않는다

- **근거:** untracked docs/superpowers/2026-08-16-codex-claude-collaboration-proposal.md:42-45,70-75는 남은 permission gap과 과거 역할/워크트리 구조를 기술하며 최신 sandbox, fix pipeline, network 한계를 반영하지 않는다.
- **영향:** 실제 보장보다 강한 격리와 다른 운영 흐름을 암시한다.
- **권고:** runtime 안전성 결정 후 exact scripts, OS envelope, network broker, owner approval, failure recovery를 갱신한다.
- **현재 차단:** proposal 승인 차단.

#### audit.canonical-replacement-atomicity — canonical 전면 교체 atomicity가 자동화 계약으로 강제되지 않는다

- **근거:** Claude 검수는 08/19 교체 때 unlink 후 새 파일 출현까지 약 3분 30초 부재를 관찰했다. 이번 실행은 하나의 apply_patch update로 교체했지만 heartbeat에 temp-write+fsync+rename wrapper가 없다.
- **영향:** watcher가 쓰는 중인 상태를 AUDIT_MISSING으로 오인하고 process failure 시 canonical이 사라질 수 있다.
- **권고:** canonical 디렉터리 내부 temp에 완성본을 쓰고 fsync 후 atomic rename하는 trusted publisher를 사용한다.
- **현재 차단:** 자동 협력 루프 안정성 차단.

### Low

#### record.origin-main-gap — 검증 branch가 origin/main보다 8 commit 앞서 있다

- **근거:** git rev-list --left-right --count origin/main...HEAD 결과 0 8.
- **영향:** 현재 감사 결과와 외부 main record가 일치하지 않는다.
- **권고:** owner review 후 merge 전략과 exact scientific release commit을 기록한다.
- **현재 차단:** release record 확정에는 차단.

## 이전 감사 대비 상태 변화

- **지속:** stats.pair-gene-dependence, seal.claim-materialization-replay, model.l3-contract-mismatch, model.ablation-penalty-units, activation evidence blocker, review job disabled, slot dedupe, proposal drift, main record gap.
- **신규/분리:** collab.audit-metadata-schema-coupling과 audit.canonical-replacement-atomicity. reviewer finding은 write 격리 해결 후 collab.reviewer-network-envelope로 좁혔다. Publisher partial-failure 문제는 별도 stable finding으로 분리했다.
- **해결:** collab.fix-sandbox-git-control — current sandbox/fixrun.sb.template:61-76에서 worktree allow와 mode rule 뒤 .git write를 deny한다. 최신 audit-log unit 53개가 통과했다.
- **해결:** collab.fix-seal-scope — scope.json:71-91의 guard가 20개로 확장돼 carrier loader, Phase2b, verdict engines, preflight/CLI, bias preseal까지 차단한다.
- **기각:** provenance.preseal-toctou의 전날 서술. sealed source는 src/alive/compose/driver/phase2b_cmd.py:491-599에서 O_NOFOLLOW stable descriptor를 hash하고 fd-backed path를 유지하며 path replacement 회귀 테스트도 있다. 다른 pre-seal artifact의 구체적 exploit은 이번에 재현하지 못해 승계하지 않는다.
- **기각:** docs.phi-rank-comment-conflict. src/alive/compose/phi_rank.py:131-139는 message-splitting 변경 범위를 말하고 :167-174는 별도 exact-integer fix의 명시적 예외다.
- **정정:** 전날 bootstrap primitive 경로 src/alive/compose/eval/bootstrap.py는 존재하지 않는다. 올바른 경로는 src/alive/eval/bootstrap.py다.
- **정정/하향:** preflight는 canonical manifest/checksum을 durable artifact로 생성한다. 남은 차이는 stdout 전달 계약이다.

## 실행한 검증과 정확한 결과

1. PYTHONDONTWRITEBYTECODE=1 UV_OFFLINE=1 uv run --frozen ruff check src tests scripts
   - **통과:** All checks passed!
2. PYTHONDONTWRITEBYTECODE=1 UV_OFFLINE=1 uv run --frozen ruff format --check src tests scripts
   - **통과:** 256 files already formatted
3. UV_OFFLINE=1 uv lock --check
   - **통과:** Resolved 101 packages in 4ms
4. PYTHONDONTWRITEBYTECODE=1 UV_OFFLINE=1 uv run --frozen pytest -q -p no:cacheprovider
   - **통과:** 2866 passed, 3 skipped, 2 warnings in 1139.06s (0:18:59)
   - **skip:** macOS의 Linux seccomp 전용 2건, 현재 venv에 torch가 없어 import skip 1건.
   - **warning:** CPA worker AnnData index ImplicitModificationWarning 1건, duplicate gene-id negative fixture의 non-unique var-name UserWarning 1건.
5. Python/JSON/YAML 정적 parse (src, tests, scripts, configs)
   - **통과:** Python 256, JSON 1, YAML 4; parse error 0.
6. git diff --check
   - **통과:** whitespace error 없음.
7. config/evidence loader
   - **통과/차단 확인:** current SHA, exact 9/5 roster, relative lambda scaling 확인; activation BLOCKED, evidence INCOMPLETE, seal safety UNVERIFIED.
   - 첫 probe는 dataclass에 없는 c.inference를 가정해 AttributeError가 났고, top-level comparator_family를 사용한 corrected probe가 성공했다.
8. synthetic claim replay
   - **재현:** first=7, second=7, same_keys=True, audit_records=1.
9. collaboration scripts
   - bash -n 6개 script **통과**.
   - audit-log unit tests **53/53 통과**. 출력의 FAIL 문구는 negative test 기대 출력이며 최종 결과는 OK다.
   - audit-log git diff --check 및 status **clean**.
   - LaunchAgent는 exit 113/service not found로 **비활성 확인**.
   - 전날 canonical 형식에서는 AUDIT_HEAD=로 **실패 재현**했고, 이번의 고정 형식에서는 exact HEAD 추출이 **통과**했다.
   - worktree를 변형하는 gate_violation_suite.sh는 read-only 감사에서 재실행하지 않았다. Claude의 66 pass / 0 fail / 2 known warnings는 참고하되 이번 독립 보증으로 승계하지 않는다.

## scientific release readiness와 seal 상태

- **Scientific release readiness:** BLOCKED
- **Seal:** UNOPENED / DO NOT OPEN
- **직접 blocker:** activation/dependency evidence 미완결, stale real evidence, pair-dependence coverage 범위, claim replay, L3 contract, penalty units.
- **운영 blocker:** reviewer network envelope, publisher/canonical atomicity, disabled LaunchAgent. Metadata parser는 현재 판에서는 통과했으나 schema coupling이 남는다.
- **남은 불확실성:** 로컬 venv에 torch/gears/cpa가 없어 실제 worker integration을 검증하지 않았다. 실제 Norman data와 sealed output은 접근하지 않았다. L3 및 penalty-unit owner decision은 미서명이다. audit-log mutating adversarial suite는 재실행하지 않았다.

## 다음 감사 우선순위

1. Claude API broker 또는 egress allowlist로 reviewer network를 제한하고 credential exposure negative test를 수행한다.
2. publisher와 canonical replacement를 atomic rename/recovery state machine으로 바꾼 뒤 watcher 부재창을 재측정한다.
3. stable metadata parser로 exact HEAD와 scheduled slot을 검증하고 missing/duplicate/stale cases를 fail-closed한다.
4. claim replay를 consume-once/cache 계약으로 닫고 synthetic concurrency/crash tests를 확인한다.
5. pair-dependence sensitivity 및 L3/penalty owner decision이 config/runtime/report에 일치하는지 본다.
6. final config/commit에 맞춘 activation evidence regeneration과 zero-overlap 증거를 검증한다.

## Claude Code 검수 handoff

- [ ] readiness.activation-evidence-incomplete: current config SHA에서 scientific mode가 허용될 수 있다는 반증을 exact evidence bytes로 시도할 것.
- [ ] stats.pair-gene-dependence: pair-i.i.d. bootstrap이 shared-gene 구조에서도 nominal coverage를 갖는 조건 또는 limitation 경로가 충분한 근거를 제시할 것.
- [ ] seal.claim-materialization-replay: 동일 claim의 두 번째 materialization이 one-time access 계약을 위반하지 않는다는 API/spec 근거를 찾을 것.
- [ ] model.l3-contract-mismatch와 model.ablation-penalty-units: owner sign-off 또는 동치성 증거가 있는지 확인할 것.
- [ ] collab.reviewer-network-envelope: sandbox 내부 Python이 임의 endpoint·credential source에 접근하지 못한다는 OS 수준 반증을 시도할 것. 실제 외부 전송은 하지 말 것.
- [ ] collab.publisher-atomicity: canonical 첫 copy 뒤 실패를 안전한 fixture에서 주입해 divergence를 확인할 것.
- [ ] collab.audit-metadata-schema-coupling: 이번 metadata에서 exact 40-hex HEAD를 하나만 추출하고 missing/duplicate/mismatch를 fail-closed하는지 확인할 것.
- [ ] 해결 판정한 .git deny와 20-file seal guard roster를 non-mutating/static 방식으로 재확인할 것.
- [ ] 기각한 sealed-source TOCTOU와 phi-rank finding을 다시 반증할 것.
- [ ] 코드 수정 없이 각 stable ID에 confirmed / refuted / uncertain과 근거 파일·줄을 남길 것.

---

이 문서는 누적 일지가 아니라 08/20/2026 09:26:11 EDT 현재의 단일 canonical 종합 감사이며, 다음 실행에서 전체 교체된다.
