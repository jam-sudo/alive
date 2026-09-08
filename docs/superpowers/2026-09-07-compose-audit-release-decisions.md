# COMPOSE-K562-v1 — 2026-09-06/07 적대적 감사 토론이 남긴 쟁점 4건과 amendment 3건

> **STATUS: SIGNED 2026-09-07 — 오너 지시: "모두 권장사항으로 진행".** 두 하네스가 재현을 마치고도 합의하지
> 못한 4건에 대해 오너가 각 절의 권장 선택지(D1-a · D2-b · D3-a · D4-a)와 amendment D·E·F·G 를 서명했다.
> 서명은 선택이지 구현이 아니다 — `status: SIGNED` 절도 그 구현 task(Task 11·12·13·14)가 착지하기 전에는
> `release: NO-GO` 다. (일반 규칙은 그대로 유지한다: `status: PENDING` 이나 `DEFER` 인 절은 `release: NO-GO` 다.)
> 서명 시점(2026-09-07, Task 5 착지 전)의 `config_sha256` 은
> `0d20774637775eda79cb682a5d28bf7df40bf5b0a3f5768ef109ba7fa37c6c99` 였다; Task 5 이후
> 현재값은 `a9dc9410d1b7fe1580e179b1fa5f9f3756688e059247a6d63322edf642b44767` 다
> (아래 `## Task 5 digest 이동` 절 참조) — 선택지마다 이동 여부가 다르다. 옛 값은 서명 시점의
> dated snapshot 으로만 남긴다.

## D1 — F-A1(ladder penalty 비대칭)의 성격
status: SIGNED: a — 오너 지시 2026-09-07 "모두 권장사항으로 진행"
release: GO-LOCAL (Task 11, 2026-09-07 — spec §3.3 수정안 F)

| | 선택지 | claim 결과 | digest | task |
|---|---|---|---|---|
| D1-a | claim-scope 결함: L1↔L2/L3 를 **exploratory** 로 강등(결정 #7 §3.3 option D) | ladder 질문 미답 | 불변 | Task 11 변형 a |
| D1-b | 등록된 estimator 차이: §10.5 "적용 범위(비주장)" 에 arm 별 penalty 단위를 표로 등록 | confirmatory 유지, 상한 명시 | 불변 | Task 11 변형 b |
| D1-c | 보류: pod 에서 real bank 의 λ* 로 θ(L1,L2) 부호를 양쪽 penalty 로 측정한 뒤 결정 | seal 전 미결 | 불변 | Task 11 변형 c (POD-GATED) |

**측정된 사실 — 이 저장소에서 재현된 것.** 2026-09-07 에 저장소 함수만으로 재측정한 구성은 **비-gene-disjoint**
합성 40 seed(37 genes / 41 calibration pairs / 22 held-out pairs, `k=6`, `p=8`, λ=0.1)이며, 거기서 θ(L1,L2) 는
현행 40/40 > 0, L2 에도 같은 scale 을 준 반사실 0/40 > 0 으로 **부호가 완전히 뒤집힌다**; 원인의 크기는
σmax(Φ)² = 0.0452, 즉 유효 penalty 비 **≈22×** 다. 재현 절차와 코드 블록은
`2026-08-17-compose-ablation-ladder-decisions.md` Addendum(2026-09-07) 에 있다. 이것이 D1 의 **현행 근거**다.
`src/alive/compose/phase2a.py:1554-1567` 이 `headline_lambda_scale` 을 `HEADLINE_MODEL_NAME` 에만 적용한다. **은폐가 아니다** —
spec `:522-528` "적용 범위(비주장)" 과 `test_lambda_scaling.py::test_the_final_fit_scales_the_headline_operator_and_leaves_the_baseline_alone` 가
고정한다. 새로 측정된 것은 그 **크기가 spec §3.3 질문의 부호를 정한다**는 점이다. 순수 architecture 효과로 해석하지 않는다.

**외부 보고(재현되지 않음) — gene-disjoint 구성.** 2026-09-06 감사 토론에서 검토자 A 가 커밋된 실제 구조를 세워
(z-universe 73 genes · calibration 44 genes · 41 cal pairs · sealed 22 pairs over 21 genes, 유전자 교집합 0)
40 seed 로 다시 돌린 값을 보고했다: σmax(Φ)² = 0.0145, 유효 penalty 비 **≈69×**, λ=0.1 의 40/40 ↔ 0/40 반전 유지.
**이것은 저장소 밖의 비재현 재실행 값이다** — 어떤 커밋도 이를 재측정하지 않았고, 근거 파일은 저장소에 없다.
두 값은 **구성이 다르므로** 서로 치환하거나 혼용하지 않는다(22.1× 를 gene-disjoint 결과로 다시 쓰지 않는다).
D1 의 결론은 위 재현된 22.1× 만으로도 같다 — 부호 반전이 두 구성 모두에서 관찰된다.

**[2026-09-07 Task 11 정정 — 수치는 그대로, 구성 라벨만 정확히.]** Task 11 이전의 이 절은 40/40 ↔ 0/40 을 라벨 없이
적었다. 위 두 문단이 그 라벨을 붙인다: 재현된 것은 비-gene-disjoint(≈22×), 외부 보고는 gene-disjoint(≈69×) 다.
**[2026-09-08 PR 리뷰 정정 — I2/M3]** 위 외부 보고의 출처를 `artifacts/…` 파일시스템 경로로 인용하던 문장을
제거했다: `artifacts/` 는 gitignored 이므로 어떤 clone 에서도 그 경로가 해석되지 않는다. 수치·구성·상태는 불변이고,
바뀐 것은 출처 표기뿐이다.

## D2 — ESM ID-null
status: SIGNED: b — 오너 지시 2026-09-07 "모두 권장사항으로 진행"
release: GO-LOCAL (Task 12, 2026-09-07 — claim 제한 + CLAUDE.md #data-eval 처분)

| | 선택지 | digest | task |
|---|---|---|---|
| D2-a | ESM-off arm(matched total-k, `esm_projection_dim: 0`) 을 comparator roster 에 **등록** | **이동** | 별도 spec+plan (부록 A), Task 12 변형 a 는 진입 조건만 |
| D2-b | claim 제한: "ESM added value" 를 주장하지 않고 `IDOnlyModel` 을 *symmetric non-bilinear factor ridge* 로 재등록 **+ `CLAUDE.md:132` 의 ablation 의무를 COMPOSE 한정으로 deferred 처분(governance amendment 서명)** | 불변 | Task 12 변형 b |
| D2-c | 보류 | 불변 | Task 12 변형 c |

**측정된 사실.** `models.py:216-309` `IDOnlyModel` 은 `[z_g + z_h, |z_g − z_h|]` + intercept — L1 과 같은 factor bank 를 소비한다.
마지막 2 factor 열만 gene 간 permute 하면 prediction 최대 절대차 1.2829885330394641(양쪽 일치). `include_esm: false` 를 YAML 에 넣는 것만으로는
ablation 이 구성되지 않는다(C01, Task 6).

**결정(D2-b) 구현 — 2026-09-07, Task 12.** claim 을 제한하고 governance 의무를 함께 처분했다. 둘 중 하나만
하면 D2 는 닫히지 않는다: CLAUDE.md 의 ablation 의무는 claim 과 무관하게 성립하므로, spec 문장만 낮추면
governance 충돌이 남는다.

1. **claim.** main spec §3.1 이 이제 "본 protocol 은 ESM의 marginal signal을 검증했다고 주장하지 않는다(결정
   D2-b, 2026-09-07); ID-only 는 같은 factor bank 위의 non-bilinear comparator 로 bilinear 구조의 기여만
   격리한다" 를 등록한다. 같은 자리에 있던 "이번엔 식별가능 구조 안에서 검증"은 삭제하지 않고 dated bracket
   으로 superseded 격리했다(`:179-180`).
2. **comparator 재등록.** §4.1 과 §10.5 의 roster 항목이 `ID-only(= symmetric non-bilinear factor ridge;
   encoder ablation 아님)` 다. `src/alive/compose/models.py` `IDOnlyModel` docstring 도 같은 등록 역할
   (STRUCTURE comparator, ESM 열 포함 동일 bank)을 적는다.
3. **governance 처분.** biological-prior encoder 의 ID-null ablation 의무를 `CLAUDE.md:132-136 (#data-eval)`
   에서 **COMPOSE-K562-v1 한정 deferred** 로 처분했다(수정안 G). 정본 참조는 anchor `#data-eval` 이며 줄번호는
   2026-09-07 기준 snapshot 이다 — 의무 문장과 그 처분은 `:133-136`. CLAUDE.md 는 198 줄(상한 200) 이다.
4. **regression.** `tests/alive/compose/test_models.py::test_the_id_only_comparator_consumes_the_same_factor_bank_as_the_operator`
   가 위 측정치(Δ=1.2829885330394641 > 1.0)를 고정한다 — 현행 동작의 GREEN pin 이다.

**digest 불변.** `a9dc9410d1b7fe1580e179b1fa5f9f3756688e059247a6d63322edf642b44767` 전후 동일(실측). config 는
건드리지 않았다.

**닫지 않은 것.** ESM-off arm 은 **여전히 미등록**이다. encoder ablation 을 실제로 수행하려면 matched
total-$k$ 의 ESM-off arm 이 필요하고, 그것은 comparator roster·digest·POD 를 움직이므로 CLAUDE.md #data-eval
의 "새 comparator" 요건에 따라 **별도 spec + plan**(부록 A)을 요구한다. 이 문서는 그 arm 을 등록하지 않는다.

## D3 — R2 위협 모델
status: SIGNED: a — 오너 지시 2026-09-07 "모두 권장사항으로 진행"
release: GO-LOCAL (Task 13, 2026-09-07 — 위협 모델 문서 종결; runtime 증거 POD-GATED)

| | 선택지 | digest | task |
|---|---|---|---|
| D3-a | 문서로 종결: 승인 runtime 의 동시 writer·mount 전제를 명시하고 `seal.transient-inode-mutation-restoration` 을 **수용된 잔여**로 확정. runtime owner 서명 | 불변 | Task 13 변형 a |
| D3-b | consumption 불변 경계 구현(claim 이후 sealed snapshot 에서 소비) | 불변(코드) | 별도 plan (부록 B), Task 13 변형 b 는 preflight 선언 검사까지 |
| D3-c | 보류 | 불변 | Task 13 변형 c |

**측정된 사실.** `driver/preseal_read.py:214-243` post-hash 는 소비 중 in-place 변경 **후 복원**을 탐지하지 못한다(복원 없는 대조군은
`PresealDescriptorError`). `phase2b_cmd.py:567` post-claim 검사는 obs 라벨만 재검증하고 X 값은 보지 않는다(B 3-arm). 등록·공시된 잔여다.

**결정(D3-a) 구현.** `seal.transient-inode-mutation-restoration` 은 **수용된 잔여**다. 코드로 막지 않고
승인 runtime 의 전제 아래에서 수용한다. 전제는 셋이다: (i) sealed source 가 놓인 mount 는 run 기간 동안
프로세스 그룹 **외부**에 write 권한을 주지 않는다; (ii) 같은 pod 안에서 sealed source 에 write 하는 프로세스는
driver 자신뿐이며 driver 는 consumption 중 그 파일에 쓰지 않는다 — 즉 소비 구간에 **동시 writer 가 없다**;
(iii) 두 전제가 성립함을 확인할 수 없는 runtime 에서는 sealed run 을 시작하지 않는다. post-hash 는 이 전제
**아래에서만** "소비한 바이트 = 검증한 바이트" 를 보장한다. 검증 시점의 obs label 정합은 consumed X 불변 보증이 아니다 — `phase2b_cmd.py:567` 의
post-claim 검사는 obs 라벨만 재검증하고 X 값은 보지 않으므로, 라벨이 그대로라는 사실은 X 가 그대로라는
증거가 아니다.

**위협 모델 — 전제가 배제하는 actor(따로 열거).**

1. **같은 inode 에 in-place write 할 수 있는 actor.** descriptor pinning 은 *pathname* swap 을 막을 뿐
   우리가 열어 둔 inode 로의 write 를 막지 못한다(`seal.verified-fd-posthash-mutation`, 2026-08-30 실측:
   `same_inode=True`).
2. **read-only mount 를 pod 밖에서 rw 로 보는 external host writer.** 컨테이너 안의 read-only mount 는
   host 쪽 write 를 배제하지 않는다.
3. **root 또는 동일 UID 프로세스.** 소유자로서 다시 열거나 권한 비트를 되돌릴 수 있다. 그래서 단순
   chmod 0444 는 충분조건이 **아니다** — 이 actor 가 그것을 우회한다.
4. **materialization 도중의 transient modify-restore.** 재검증 **전에** 원래 바이트로 되돌리면 post-hash 는
   등호를 보고 통과한다(복원하지 않는 대조군만 `PresealDescriptorError` 를 낸다).

이 넷은 (i)·(ii) 가 배제하는 대상이며, 배제의 근거는 코드가 아니라 runtime 구성이다.
(위 `:214-243` 은 이번 task 가 같은 블록에 주석 4줄을 더한 뒤의 줄번호다 — 이전 인용 `:210-239` 와 같은 코드다.)

**서명·상태·미확인.** runtime owner 는 **저장소 오너**다. 종결에는 오너가 object identity·mount
access-policy·actor roster·증거 위치를 검토해 서명하는 것이 필요하다. 로컬 row 상태:
`POLICY_SIGNED / RUNTIME_UNVERIFIED` — 정책 문장은 이 문서로 서명됐고, 실제 storage/mount/actor 증거
확인은 **POD-GATED** 다(로컬에서 측정한 것이 없다). `COMPOSE-SEAL-READINESS.md` 의 `source_consumption`
행에 이 상태를 싣는 것은 Task 7 의 재작성이 수행한다. **코드 잔여 자체는 바뀌지 않았다** — 동작·config
무변경이고, 문서 계약만 닫힌다. main spec §10.6 수정안 A 블록 뒤의 D3-a 한 줄과
`src/alive/compose/driver/preseal_read.py` post-hash 주석의 예외 문장이 이 절을 역참조한다. 변형 b(claim
이후 sealed snapshot 에서 소비)는 여기서 채택하지 않았고 **별도 plan**(부록 B)으로 남는다.

**[2026-09-08 PR 리뷰 정정 — C1]** 위 "측정된 사실" 은 재검사가 **소비 종료 시점**에 돈다고 전제했지만,
2026-09-08 두 독립 PR 리뷰가 실제 배치를 실측했다: 재검사는 `verified_descriptor` 의 context 종료에서
돌았고 driver 는 그 context 로 library 호출 전체를 감쌌으므로, 검사는 COMPLETE terminal 과 durable marker
가 이미 기록된 **뒤에** 돌았다. 실패 예외는 `with` 문 자체의 exit 에서 나와 post-seal 처리(exit 30)를
지나쳤고 CLI 는 pre-seal exit 10 으로 분류했으며 `recover` 는 그 COMPLETE 를 읽어 **0** 을 돌려줬다 —
탐지된 무결성 실패가 durable witness 없이 사라졌다. 정정 사항은 셋이다.
(1) **탐지 위치 = materialization 경계.** 재해시는 이제 `ComposeOutcomeStore.materialize_claimed` 가
claim 된 모든 pair 를 numpy 로 물질화한 직후, 반환 직전에 `post_materialization_check` 로 정확히 한 번
돈다(`outcome_store.py`, `phase2b_cmd._build_sealed_store`). 이 지점은 terminal 보호 경계 안이다.
(2) **durable witness = `ABORTED_AFTER_SEAL`.** 소비 중 in-place 변조는 이제 `ComposeSealingError` 로
전파되어 `ABORTED_AFTER_SEAL` terminal 을 남기고 phase2b·`recover` 모두 **30** 을 돌려준다
(`tests/alive/compose/driver/test_sealed_source_integrity_e2e.py`, 변이 harness M18).
(3) **소비 *후* 변조 = stderr 진단만.** 소비가 끝난 뒤의 파일 상태는 "소비한 바이트 = 검증한 바이트"
계약의 대상이 아니며(terminal 이 소비 시점의 검증을 기록한다), 거기서 예외를 내면 durable COMPLETE 와
exit code 가 다시 모순된다. 그래서 한 줄 진단만 stderr 에 쓰고 terminal 은 건드리지 않는다 —
조용한 swallow 가 아니라 테스트로 고정된 선언 동작이다. 이 창의 writer 자체는 위 (i)·(ii) 전제가 배제하며
D3-a 의 처분이 그대로 덮는다. **수용된 잔여(`seal.transient-inode-mutation-restoration`)와 D3-a 서명 문장은
바뀌지 않는다** — 바뀐 것은 재검사가 *언제* 도는가와 실패가 *무엇을 남기는가* 뿐이고, config·digest 는 불변이다.

## D4 — pair dependence 아래 headline 문장
status: SIGNED: a — 오너 지시 2026-09-07 "모두 권장사항으로 진행"
release: GO-LOCAL (Task 14, 2026-09-07 — pair-dependence decision §8)

| | 선택지 | digest | task |
|---|---|---|---|
| D4-a | seal 전 headline 문장 **사전 확정**(세 결과군) | 불변 | Task 14 변형 a |
| D4-b | 보류 | 불변 | Task 14 변형 b |

**사실상 합의.** A 의 P1(calibration design effect 로 밴드 팽창)은 `2026-08-29-compose-pair-dependence-decision.md:79-88` 이 불변식 7 위반을 포함한
세 근거로 기각했고 A 가 전면 철회했다. 남는 것은 문장 사전 확정뿐이다.

**결정(D4-a) 구현.** 세 결과군의 문구는 `docs/superpowers/2026-08-29-compose-pair-dependence-decision.md`
§8 「seal 전에 확정된 headline 문장」에 결과를 보기 전에 고정했고, main spec §10.5 의 band-sensitivity 문단이
그 절을 역참조한다. 승리 문장은 등록된 resampling 단위 가정에 **조건부**이며 unconditional efficacy 를
주장하지 않는다 — 0.9240~0.9373 은 특정 생성모형의 simulation 값이지 Norman 에서 측정한 coverage 가 아니다.
verdict 는 그대로 λ=1.0 에서만 판정하며 사다리의 다른 λ 는 verdict gate 가 되지 않는다. digest 불변.

**[2026-09-08 — 사전등록 문장 하나 추가, digest 불변.]** 최종 whole-branch 리뷰가 남은 구멍을 잡았다: (i)~(iii) 은
headline additive contrast 의 결과군만 덮는데 `GI_LEARNABLE_WIN` 은 learned comparator 조건을 하나 더 요구하고,
그 조건이 통과했을 때 쓸 문장이 없었다 — 수정안 F 가 강등한 문장을 결과를 본 뒤에 고를 자유가 남아 있었다.
§8 에 **(iv)** 를 더해 그 자유를 닫았다(사전등록 문장은 이제 넷). spec §3.3 수정안 F 가 그 위치를 역참조하고,
`test_the_preregistered_headline_covers_the_learned_family_leg` 가 둘의 존재를 함께 고정한다.

## 열린 것 (이 문서가 결정하지 않는 것)

1. R1 후속 evidence 의 목표(raw bridge 입증 vs log candidate 채택)는 pod 단계 결정이며 Task 1·2 의 선행조건이 아니다.
2. D3-a 의 runtime owner 는 저장소 오너이며 실제 storage/mount/actor 증거는 POD-GATED.

## Amendment 서명 표

| amendment | subject | vehicle | before digest | after digest | status |
|---|---|---|---|---|---|
| **D** | bias spec §1 — bridge representation 을 강제 계약으로, report v4 | Task 2 | `3a8919076eedcb205df7be7c890a46e8da6cc927f8c18e3821ad44c8e8d6c364` | `54bed129d412e1169ff3113e526ff67da1bb24c7692b27aa7e18a028775082cb` | SIGNED (오너 지시 2026-09-07) — EFFECTIVE (Task 2, 2026-09-07) |
| **E** | main spec §10.5 — primary metric 식을 등록된 형태로 | Task 3 | — | — | SIGNED (오너 지시 2026-09-07) — EFFECTIVE (Task 3, 2026-09-07) |
| **F** | main spec §3.3 — ladder attribution claim 상한 | Task 11 | — | — | SIGNED (오너 지시 2026-09-07) — EFFECTIVE (Task 11, 2026-09-07) |
| **G** | CLAUDE.md `:23-24,147,156-157,161-162` (+ D2-b 의 `#data-eval` ablation-의무 처분) | Task 8 · 12 | — | — | SIGNED (오너 지시 2026-09-07) — EFFECTIVE (Task 8 + Task 12, 2026-09-07) |

## 서명
| 항목 | 선택 | 서명 | 날짜 |
|---|---|---|---|
| D1 | ☑ a ☐ b ☐ c | 오너 (지시: "모두 권장사항으로 진행") | 2026-09-07 |
| D2 | ☐ a ☑ b ☐ c | 오너 (지시: "모두 권장사항으로 진행") | 2026-09-07 |
| D3 | ☑ a ☐ b ☐ c | 오너 (지시: "모두 권장사항으로 진행") | 2026-09-07 |
| D4 | ☑ a ☐ b | 오너 (지시: "모두 권장사항으로 진행") | 2026-09-07 |
| Amendment D / E / F / G | ☑ ☑ ☑ ☑ | 오너 (지시: "모두 권장사항으로 진행") | 2026-09-07 |

## Task 5 digest 이동

`config_sha256` `0d207746…` → `a9dc9410d1b7fe1580e179b1fa5f9f3756688e059247a6d63322edf642b44767` (Task 5, 2026-09-07, 오너 승인: "모두 권장사항으로 진행").

futility measurability floor `0.2` 를 `futility.measurability_ceiling_floor` 로 등록한 결과다(F-A3).
새 run identity이며 activation blocker 는 여전히 **여섯**, seal 은 **UNOPENED**, execution 은
**RELEASE-BLOCKED** 다. Phase-1 config 에도 같은 값을 등록했기 때문에 source 에 고정돼 있던
`REGISTERED_PHASE1_CONFIG_SHA256` 도 함께 `2e044e75…` → `732f43fe…` 로 이동했다 — 이 두 번째
이동은 첫 번째의 기계적 결과이며 별도 선택이 아니다.

## 검증 ledger (Task 15)

`scripts/compose_audit_mutation_harness.py` 를 clean worktree 에서 실행한 결과다(2026-09-07,
`uv run python scripts/compose_audit_mutation_harness.py` → exit 0).
**17 killed / 0 survived / 0 harness-failed (17 cases).**

엔진은 추적 파일을 쓰지 않는다: subprocess 안에서 `importlib` 로 모듈을 올리고 `m.__file__` 의 소스를
읽어 `count(old) == 1` 을 확인한 뒤 메모리 사본만 치환해 `m.__dict__` 에 `exec` 하고 그 nodeid 하나를
돌린다. 이 방식이어야 pinned 파일(`src/alive/io.py`, `src/alive/compose/approximation_bias.py`)의 강제
지점도 파일을 건드리지 않고 잴 수 있다. **script**(producer)는 자기 테스트가 `spec_from_file_location`
으로 경로에서 다시 읽으므로 in-memory 변이가 보이지 않는데, 그렇다고 추적 파일을 써야 하는 것은
아니다 — 저장소 상대 레이아웃을 임시 루트로 복사해 **사본**을 변이하고 테스트 모듈의 경로 상수를
sandbox 로 돌린다(그 redirect 는 baseline 에도 똑같이 적용하므로 redirect 자체를 효과로 오독할 수 없다).

**kill 의 정의는 exit code 도, "빨개졌다"도 아니다.** 같은 machinery 로 돌린 baseline 이 green 이고,
그다음 **그 nodeid 자신이 자기 assertion 으로** 죽어야 kill 이다. child 가 pytest plugin 으로 대상
nodeid 의 call-phase 예외 **종류**를 기록하고, `AssertionError` 와 pytest 의 `Failed`(`pytest.fail`,
`pytest.raises` DID-NOT-RAISE)만 kill 로 센다. 그 밖의 예외는
`HARNESS_FAILURE (non-assertion: <Type>)` 이고, collection/usage error·모듈 재실행 예외·anchor
불일치·다른 테스트의 실패도 전부 harness 실패다(변이 규칙 4·6·8). 이 판정 규칙 자체는
`tests/alive/compose/test_audit_mutation_harness.py` 가 고정한다.

| # | 변이 (module) | named killer (nodeid) | exit base→mutant · call-phase kind | 판정 |
|---|---|---|---|---|
| M01 | `gates` role allowlist 제거 (`if _role != CALIBRATION_ROLE_NAME:` → `if False:`) | `test_gates.py::test_measurability_gate_refuses_sealed_array` | 0→1 · `Failed` | KILLED |
| M02 | `gates` floor 를 source 상수로 (`> ceiling_floor` → `> 0.2`) | `test_gates.py::test_the_measurability_floor_comes_from_the_config_not_from_the_source` | 0→1 · `AssertionError` | KILLED |
| M03 | `detectable_effect` floor 를 source 상수로 (`> ceiling_floor` → `> 0.2`) | `test_detectable_effect.py::test_the_activation_validator_recomputes_against_the_registered_floor` | 0→1 · `AssertionError` | KILLED |
| M04 | `freeze` upstream checksum 비교 제거 | `test_freeze.py::test_verify_fails_when_upstream_checksum_mutated` | 0→1 · `Failed` | KILLED |
| M05 | `outcome_store` exact sealed union 검사 제거 | `test_outcome_store.py::TestExactUnionEnforcement::test_an_unknown_pair_is_refused_by_the_contracted_error_not_a_downstream_crash` | 0→1 · `AssertionError` | KILLED |
| M06 | `outcome_store` once-only precheck 조기 return | `test_outcome_store.py::TestOnceOnly::test_second_call_same_run_id_refused` | 0→1 · `AssertionError` | KILLED |
| M07 | `io` write-once 를 `os.replace` 로 | `tests/alive/test_io.py::test_a_second_write_to_the_same_destination_is_refused` | 0→1 · `Failed` | KILLED |
| M08 | `phase2a` headline-only scaling → 모든 arm (`if True:`) | `test_lambda_scaling.py::test_the_final_fit_scales_the_headline_operator_and_leaves_the_baseline_alone` | 0→1 · `AssertionError` | KILLED |
| M09 | `approximation_bias` validator 의 `validate_bias_method_bridge(...)` 호출 제거 | `test_approximation_bias_metric.py::test_a_probe_a_bridge_of_a_different_representation_does_not_admit_this_report` | 0→1 · `Failed` | KILLED |
| M10 | `approximation_bias` `ADMISSION_STATUSES` 에 세 번째 값 추가 | `test_approximation_bias_metric.py::test_the_admission_status_roster_is_exactly_admitted_and_not_admissible` | 0→1 · `AssertionError` | KILLED |
| M11 | `config2` `include_esm` 값 검사 제거 (`if False:`) | `test_config2.py::test_an_unregistered_include_esm_value_is_refused_instead_of_only_moving_the_digest[False]` | 0→1 · `Failed` | KILLED |
| M12 | `driver.fixture_builder` key-roster guard 제거 | `driver/test_fixture_builder.py::test_the_fixture_key_roster_guard_survives_python_optimize[EXPECTED_HASHES_KEYS]` | 0→1 · `Failed` | KILLED |
| M13 | `driver.identity_lock` adapter_version 을 declared 값에서 (manifest 조회 제거) | `driver/test_identity_lock.py::test_scientific_declared_adapter_version_mismatch_fails_closed` | 0→1 · `Failed` | KILLED |
| M14 | `driver.identity_lock` `except (OSError, ValueError)` → `except ValueError` | `driver/test_identity_lock.py::test_an_os_error_on_the_manifest_re_read_is_converted_not_merely_re_raised` | 0→1 · `AssertionError` | KILLED |
| M15 | `models` `IDOnlyModel` 이 마지막 2 factor 열을 무시 (`_design` + `predict_eps` 둘 다) | `test_models.py::test_the_id_only_comparator_consumes_the_same_factor_bank_as_the_operator` | 0→1 · `AssertionError` | KILLED |
| M16 | `test_kernel_isolation_ci` 의 pinned `_PENDING_REPROOF` digest 를 오답으로 | `test_kernel_isolation_ci.py::test_the_v2_kernel_proof_still_covers_the_shipped_isolation_closure` | 0→1 · `AssertionError` | KILLED |
| M17 | **sandbox**: producer 사본의 `bridge_admits(...)` → `True` **+** validator 호출 제거 | `test_approximation_bias_metric.py::test_a_log_normalized_probe_a_pass_does_not_admit_a_raw_count_report` | 0→1 · `AssertionError` | KILLED |

### 규칙 8 — "빨개졌다"가 아니라 "자기 assertion 으로 죽었다"

외부 교차검토가 잡은 결함이다. 처음 판정기는 `named FAILED + exit 1` 만 봤고, 그래서 **테스트가 주장한
적 없는 예외**로 죽어도 kill 로 셌다. 실측으로 확인한 두 자리:

* M05 의 옛 killer(`test_unknown_id_refused`, `pytest.raises(ComposeSealingError)`)는 union 검사를
  없애면 `outcome_store.py:834` 의 `KeyError(('NOPE','ZZZZ'))` 로 죽는다 →
  새 판정기에서 `HARNESS_FAILURE (non-assertion: KeyError)`.
* M14 의 옛 killer(`..._is_an_assembler_error[error0]`)는 `except` 를 좁히면
  `FileNotFoundError(2, 'gone')` 로 죽는다 → `HARNESS_FAILURE (non-assertion: FileNotFoundError)`.

두 계약은 **타입 자체가 계약**이므로, 타입을 직접 assert 하는 killer 를 새로 썼다
(`test_an_unknown_pair_is_refused_by_the_contracted_error_not_a_downstream_crash`,
`test_an_os_error_on_the_manifest_re_read_is_converted_not_merely_re_raised`). 이제 같은 변이가
`AssertionError` 로 죽는다 — 즉 이름이 하는 주장이 실제로 측정된다.

### 어느 줄이 raise 했는가 (규칙 7)

* **M05** — union 검사가 사라져도 downstream 은 여전히 fail-closed 다(`KeyError`). exact-union 검사의
  고유 기여는 *계약된 타입*(`ComposeSealingError`)과 `sealed_access_count == 0` 이고, 새 killer 가
  그것을 잰다.
* **M06** — precheck 이 빠져도 durable concurrent-claim backstop 이 거부하지만 메시지에서 run id 가
  사라져 테스트가 자기 `match="run-1"` 으로 죽는다. precheck 의 고유 기여는 run-id 로 귀속된 거부다.
* **M15** — 한 곳만 바꾸면 shape 오류로 죽으므로 `_design` 과 `predict_eps` 를 함께 바꿔야 하며,
  그렇게 하면 Δ 가 정확히 `0.0` 으로 붕괴해 `assert 0.0 > 1.0` 으로 죽는다.
* **M17** — producer 와 validator 는 같은 predicate 를 두 번 강제한다. 실측: validator 만 없애면 이
  테스트는 **green**(rc=0), producer 만 바꾸면 validator 의 `ApproximationBiasValidationError` 로 죽는다
  (non-assertion). 둘을 함께 없애야 `assert 'admitted' == 'NOT_ADMISSIBLE'` 로 죽는다. Task 1 이
  full-tree sandbox 에서 같은 쌍을 측정한 기록은 이제 근거가 아니라 **보조 이력**이다.

**이 ledger 는 readiness 신호가 아니다.** 로컬 강제 지점이 테스트로 잡혀 있다는 것만 말한다.
`COMPOSE-K562-v1` 은 그대로 `RELEASE-BLOCKED`, seal 은 `UNOPENED` 이며 config digest 는 움직이지 않았다
(`a9dc9410…`). 남은 인수조건은 readiness 의 `## Go/No-Go (2026-09-07, 로컬 검증 결과)` 표에 있다.
