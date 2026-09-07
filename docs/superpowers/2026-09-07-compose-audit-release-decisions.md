# COMPOSE-K562-v1 — 2026-09-06/07 적대적 감사 토론이 남긴 쟁점 4건과 amendment 3건

> **STATUS: SIGNED 2026-09-07 — 오너 지시: "모두 권장사항으로 진행".** 두 하네스가 재현을 마치고도 합의하지
> 못한 4건에 대해 오너가 각 절의 권장 선택지(D1-a · D2-b · D3-a · D4-a)와 amendment D·E·F·G 를 서명했다.
> 서명은 선택이지 구현이 아니다 — `status: SIGNED` 절도 그 구현 task(Task 11·12·13·14)가 착지하기 전에는
> `release: NO-GO` 다. (일반 규칙은 그대로 유지한다: `status: PENDING` 이나 `DEFER` 인 절은 `release: NO-GO` 다.)
> 현재 `config_sha256` `0d20774637775eda79cb682a5d28bf7df40bf5b0a3f5768ef109ba7fa37c6c99` — 선택지마다 이동 여부가 다르다.

## D1 — F-A1(ladder penalty 비대칭)의 성격
status: SIGNED: a — 오너 지시 2026-09-07 "모두 권장사항으로 진행"
release: GO-LOCAL (Task 11, 2026-09-07 — spec §3.3 수정안 F)

| | 선택지 | claim 결과 | digest | task |
|---|---|---|---|---|
| D1-a | claim-scope 결함: L1↔L2/L3 를 **exploratory** 로 강등(결정 #7 §3.3 option D) | ladder 질문 미답 | 불변 | Task 11 변형 a |
| D1-b | 등록된 estimator 차이: §10.5 "적용 범위(비주장)" 에 arm 별 penalty 단위를 표로 등록 | confirmatory 유지, 상한 명시 | 불변 | Task 11 변형 b |
| D1-c | 보류: pod 에서 real bank 의 λ* 로 θ(L1,L2) 부호를 양쪽 penalty 로 측정한 뒤 결정 | seal 전 미결 | 불변 | Task 11 변형 c (POD-GATED) |

**측정된 사실(양쪽 재현).** gene-disjoint 40 seed 합성, λ=0.1 에서 θ(L1,L2) 는 현행 40/40 > 0, L2 에도 같은 scale 을 준 반사실 0/40 > 0.
`src/alive/compose/phase2a.py:1554-1567` 이 `headline_lambda_scale` 을 `HEADLINE_MODEL_NAME` 에만 적용한다. **은폐가 아니다** —
spec `:522-528` "적용 범위(비주장)" 과 `test_lambda_scaling.py::test_the_final_fit_scales_the_headline_operator_and_leaves_the_baseline_alone` 가
고정한다. 새로 측정된 것은 그 **크기가 spec §3.3 질문의 부호를 정한다**는 점이다. 순수 architecture 효과로 해석하지 않는다.

## D2 — ESM ID-null
status: SIGNED: b — 오너 지시 2026-09-07 "모두 권장사항으로 진행"
release: NO-GO (구현 대기 — Task 12)

| | 선택지 | digest | task |
|---|---|---|---|
| D2-a | ESM-off arm(matched total-k, `esm_projection_dim: 0`) 을 comparator roster 에 **등록** | **이동** | 별도 spec+plan (부록 A), Task 12 변형 a 는 진입 조건만 |
| D2-b | claim 제한: "ESM added value" 를 주장하지 않고 `IDOnlyModel` 을 *symmetric non-bilinear factor ridge* 로 재등록 **+ `CLAUDE.md:132` 의 ablation 의무를 COMPOSE 한정으로 deferred 처분(governance amendment 서명)** | 불변 | Task 12 변형 b |
| D2-c | 보류 | 불변 | Task 12 변형 c |

**측정된 사실.** `models.py:216-309` `IDOnlyModel` 은 `[z_g + z_h, |z_g − z_h|]` + intercept — L1 과 같은 factor bank 를 소비한다.
마지막 2 factor 열만 gene 간 permute 하면 prediction 최대 절대차 1.2829885330394641(양쪽 일치). `include_esm: false` 를 YAML 에 넣는 것만으로는
ablation 이 구성되지 않는다(C01, Task 6).

## D3 — R2 위협 모델
status: SIGNED: a — 오너 지시 2026-09-07 "모두 권장사항으로 진행"
release: NO-GO (구현 대기 — Task 13)

| | 선택지 | digest | task |
|---|---|---|---|
| D3-a | 문서로 종결: 승인 runtime 의 동시 writer·mount 전제를 명시하고 `seal.transient-inode-mutation-restoration` 을 **수용된 잔여**로 확정. runtime owner 서명 | 불변 | Task 13 변형 a |
| D3-b | consumption 불변 경계 구현(claim 이후 sealed snapshot 에서 소비) | 불변(코드) | 별도 plan (부록 B), Task 13 변형 b 는 preflight 선언 검사까지 |
| D3-c | 보류 | 불변 | Task 13 변형 c |

**측정된 사실.** `driver/preseal_read.py:210-239` post-hash 는 소비 중 in-place 변경 **후 복원**을 탐지하지 못한다(복원 없는 대조군은
`PresealDescriptorError`). `phase2b_cmd.py:567` post-claim 검사는 obs 라벨만 재검증하고 X 값은 보지 않는다(B 3-arm). 등록·공시된 잔여다.

## D4 — pair dependence 아래 headline 문장
status: SIGNED: a — 오너 지시 2026-09-07 "모두 권장사항으로 진행"
release: NO-GO (구현 대기 — Task 14)

| | 선택지 | digest | task |
|---|---|---|---|
| D4-a | seal 전 headline 문장 **사전 확정**(세 결과군) | 불변 | Task 14 변형 a |
| D4-b | 보류 | 불변 | Task 14 변형 b |

**사실상 합의.** A 의 P1(calibration design effect 로 밴드 팽창)은 `2026-08-29-compose-pair-dependence-decision.md:79-88` 이 불변식 7 위반을 포함한
세 근거로 기각했고 A 가 전면 철회했다. 남는 것은 문장 사전 확정뿐이다.

## 열린 것 (이 문서가 결정하지 않는 것)

1. R1 후속 evidence 의 목표(raw bridge 입증 vs log candidate 채택)는 pod 단계 결정이며 Task 1·2 의 선행조건이 아니다.
2. D3-a 의 runtime owner 는 저장소 오너이며 실제 storage/mount/actor 증거는 POD-GATED.

## Amendment 서명 표

| amendment | subject | vehicle | before digest | after digest | status |
|---|---|---|---|---|---|
| **D** | bias spec §1 — bridge representation 을 강제 계약으로, report v4 | Task 2 | `3a8919076eedcb205df7be7c890a46e8da6cc927f8c18e3821ad44c8e8d6c364` | `54bed129d412e1169ff3113e526ff67da1bb24c7692b27aa7e18a028775082cb` | SIGNED (오너 지시 2026-09-07) — EFFECTIVE (Task 2, 2026-09-07) |
| **E** | main spec §10.5 — primary metric 식을 등록된 형태로 | Task 3 | — | — | SIGNED (오너 지시 2026-09-07) — EFFECTIVE (Task 3, 2026-09-07) |
| **F** | main spec §3.3 — ladder attribution claim 상한 | Task 11 | — | — | SIGNED (오너 지시 2026-09-07) — EFFECTIVE (Task 11, 2026-09-07) |
| **G** | CLAUDE.md `:23-24,147,156-157,161-162` (+ D2-b 시 `:132` 처분) | Task 8 · 12 | — | — | SIGNED (오너 지시 2026-09-07) — EFFECTIVE (Task 8, 2026-09-07); `:132` 처분(D2-b)은 Task 12 대기 |

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
