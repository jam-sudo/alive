# COMPOSE baseline — owner-approved design direction (2026-09-11)

> **상태:** 설계 정합화 방향 승인; 세부 계약·구현·실험 승인 아님.
> **Protocol:** COMPOSE-K562-v1 ACTIVE / RELEASE-BLOCKED / seal UNOPENED.
> **승인 근거:** owner의 2026-09-11 지시 “최종 권고로 진행”. 직전 권고의 범위는
> 버전 유지, checkpoint 정책 정합화, log 기반 R1 새 설계, CPA claim 한계 명시다.
> 기존 서명·실패 기록은 보존한다. 이 문서는 config, threshold, run identity를 변경하지 않는다.

## 1. 승인 범위와 권위

[기존 서명 기록](2026-07-13-compose-dev-pod-gate-decisions.md)의 §6.2가 승인한
`cell-gears==0.1.2`와 `cpa-tools==0.8.5`를 유지한다. 버전 선택을 다시 미결로 돌리지 않는다.
정확한 epoch/batch/optimizer/early-stop/seed와 설치 artifact의 일치 증명은 그 서명에 포함되지 않는다.
Published/default 계약은 version-specific 기본값을 허용하지만, 기본값 확인을 논문 실험의 완전
재현으로 표현하지 않는다. 이후 설정표는 installed wheel 근거와 adapter 변경을 구분해야 한다.

이 승인은 아래 설계를 구체화하는 문서 작업에 적용한다. `configs/`의 null 채움·digest 이동,
checkpoint 정책 변경, 새 probe 등록·실행, real fit, exact Git SHA 또는 seal 승인이 아니다.
[CLAUDE sources](../../CLAUDE.md#sources), [seal](../../CLAUDE.md#seal),
[readiness](COMPOSE-SEAL-READINESS.md)의 기존 계약이 계속 적용된다.

## 2. Checkpoint 정책 — 함께 정합화할 미결 계약

[Deep-baseline spec §1.6](specs/2026-07-01-compose-deep-baselines-design.md)은
published/default 충실도와 outcome 기반 knob 선택 금지, 제공된 calibration gene-disjoint OOF를
규정한다. [현재 worker 설계 기록 §2.2–2.3](2026-07-10-compose-phase1-dev-pod-findings.md)은
다음과 같은 서로 다른 내부 정책을 설명한다.

| 방법 | 현재 정책 | 이번 처분 |
|---|---|---|
| GEARS | training graph의 duplicate monitoring subset; fixed final epoch | best-validation으로 자동 변경하지 않음 |
| CPA | within-condition train/validation split; upstream cpa_metric callbacks | 내부 checkpoint 선택과 OOF 계약의 관계를 명시해야 함 |

내부 cell split 자체는 unseen-perturbation claim을 만드는 evaluation split이 아니다.
따라서 split만 보고 claim-unit 위반이라고 단정하지 않는다. 반대로 sealed 미접촉만으로
checkpoint 선택이 상위 계약에 부합한다고 확정하지도 않는다.

후속 계약안은 (a) 사전 고정된 library-default 내부 checkpoint 선택과 (b) baseline 간/설정 간
outcome 기반 tuning의 경계를 명시하고, 각 데이터 role과 OOF 적용 범위를 정해야 한다.
내부 선택의 예외가 필요하면 authoritative spec의 명시적 owner amendment가 선행되어야 한다.
이번 승인은 그 예외를 부여하지 않는다. GEARS 독립 validation을 제안할 경우 DE·graph·전처리까지
holdout으로부터 격리하는 설계가 필요하며, 현재 final epoch가 baseline을 약화시켰다는 실측 근거는 없다.
계약 정합화 전 affected scientific run은 보류한다. 확인된 구현 결함이라는 판정은 내리지 않는다.

## 3. R1 — log 기반 새 설계를 우선 개발

현재 raw-count GEARS worker는 published/default 재현이 아닌 compatibility 경로다
([설계 기록 §2.1](2026-07-10-compose-phase1-dev-pod-findings.md)). 출력 representation의
문자열만 바꾸는 방식은 채택하지 않는다. 새 설계안은 다음 항목을 하나의 lineage로 결속해야 한다.

- 입력: full-library normalization/log transformation, outcome-independent gene roster와
  허용 role에서만 적합한 preprocessing. Upstream HVG 관행을 이유로 등록된 universe를 조용히 바꾸지 않는다.
- 출력: `log_normalized_pseudobulk` 후보를 frozen response basis로 투영하는 정의.
  후보의 signed finite 출력을 보존하고 두 번째 normalization/log 또는 zero clipping을 하지 않는다.
  이는 새 후보의 요구사항이며, 현재 production worker가 이를 구현했다는 주장이 아니다.
- 집계: public GEARS의 replacement-sampled control 집계와 전체 control 평균을 구분한다.
  동일 표본의 affine projection 교환 가능성은 서로 다른 control 표본의 예측 동등성을 증명하지 않는다.
- 측정: sampling discrepancy와 representation/projection 효과를 구분한 estimand,
  reference population, exact N·반복 구조, RNG 정책, 허용 role, CI·판정 기준을 실행 전에 고정한다.
  수치 threshold·반복 횟수는 이 문서에서 추정해 정하지 않는다.
- 계약: config·projection·bias metric·producer/consumer·known-answer 검증을 함께 설계한다.
  현 raw-count Jensen-gap 공식을 log 결과에 재사용하거나 report method 이름만 바꾸지 않는다.

[2026-07-20 negative result](audits/2026-07-20-compose-probe-a-negative-result.md)의
exact-first-300 후보 FAIL은 유지한다. 같은 registration의 tolerance 변경, index replay 또는
실패를 PASS로 바꾸기 위한 재실행은 승인하지 않는다. 후속은 별도 사전등록 설계이며, 기존 실패와의
차이·한계를 기록하고 해당 기록 §4의 verifier/runtime 선행조건도 충족해야 한다.
[R1 bias spec](specs/2026-07-13-compose-approximation-bias-metric-design.md)의 representation
일치 guard는 유지한다. 설계 방향 승인은 log representation의 scientific admission이 아니다.

## 4. CPA — 예측 의미와 한계

[현재 worker](../../scripts/baselines/cpa_worker.py)와
[설계 기록 §2.3](2026-07-10-compose-phase1-dev-pod-findings.md)에 따르면 예측은 per-cell NB
평균이며 `variational=False`다. `prediction_n_samples=20`을 20회 관측 count sampling의 증거로
쓰지 않는다. 반환된 예측행렬을 cell별로 투영한다는 뜻과 실제 population의 transformed mean에
대해 무편향이라는 뜻은 다르다. 비선형 T에 대해 일반적으로 `T(E[X]) != E[T(X)]`다.

이는 model prediction의 의미에 대한 한계이며 실제 편향 크기나 baseline 열등성의 측정 결과가 아니다.
현재 GEARS raw-pseudobulk aggregation의 representation-floor 정의와 동일시하지 않는다.
CPA의 `approximation_bias_report_sha256`은 현 계약상 null 유지가 맞으며, 이 관찰만으로 새 blocker,
sampling decoder, representation 변경 또는 comparator 교체를 추가하지 않는다.

## 5. 다음 산출물과 완료 경계

다음 단계는 checkpoint/OOF 관계에 대한 authoritative 계약안과 R1 입력·출력·집계·metric의 상세
사전등록 설계안이다. 그 안에서 미결 과학적 선택과 필요한 승인, synthetic known-answer 및 negative
검증을 명시한다. 설계 채택 뒤에만 별도 승인 범위에 따라 구현·검증·pod evidence·config finalization을
진행한다. Report admission과 최종 release gate는 생략할 수 없다.

본 기록은 power 분석 완료, activation blocker 해소, 실험 성공 또는 release readiness를 주장하지 않는다.

## 6. 상세 초안 연결 — 2026-09-11

Owner의 후속 “진행”에 따라 [checkpoint/OOF·R1 상세 계약 초안](specs/2026-09-11-compose-baseline-checkpoint-r1-draft.md)을
작성했다. 초안은 CPA callback 예외의 제안, 현재 deep-baseline OOF 구현 경계, R1 projection과
conditional sampling error의 분리, 미결 수치·admission 정책을 명시한다. 작성 승인은 초안 조문의
채택·config 변경·실험 승인과 구분한다.

## 7. Owner 후속 채택 — 2026-09-11

Owner의 “그렇게 진행해”는 [상세 문서 §7](specs/2026-09-11-compose-baseline-checkpoint-r1-draft.md)에
명시한 제한적 정책 채택과 로컬 synthetic 검증으로 반영한다. Checkpoint 예외와 R1 log 방향을
authoritative spec의 추가 조문에 기록했으며, 앞 절의 그 두 정책에 대한 미결 표기는 이 처분으로
갱신한다. Exact config, sampling 수치, 상세 admission 계약, pod 실행과 seal 승인은 포함하지 않는다.

## 8. 로컬 검증 기록 — 2026-09-11

추가한 [synthetic R1 tests](../../tests/alive/compose/test_r1_log_sampling_contract.py)는 production
`apply_response_projection`을 호출해 signed 값·비영 center·같은 가중치의 affine identity·서로 다른
control 집계의 차이·gene identity/nonfinite 거부를 확인한다. 작은 replacement draw 열거는 p=1/2,
m=1/2/3, constant/nonconstant 입력을 다룬다. 이는 sampling 수식 검증이지 production sampler
구현·runtime·report admission의 증명이 아니다. Guard mock은 사용하지 않는다.

실행 결과:

- `uv run --locked pytest -q tests/alive/compose/test_r1_log_sampling_contract.py tests/alive/compose/test_fit_role.py tests/alive/compose/test_cpa_worker_logic.py tests/alive/compose/test_gears_worker_logic.py tests/test_claude_md_anchors.py tests/test_documentation_hygiene.py` — 96 passed.
- `uv run --locked pytest -q tests/alive/compose` — 2522 passed, 2 skipped, 1 warning;
  1228.24초. Warning은 Scanpy 테스트의 AnnData string-index 변환 알림이다.
- `uv run --locked pytest -q -rs tests/alive/compose/test_kernel_isolation_ci.py` — 69 passed.
- `uv run --locked pytest -q -rs tests/alive/compose/test_network_isolation.py` — 18 passed,
  2 skipped. 두 skip은 `test_linux_policy_and_sealed_receipt_validate_in_the_active_process`와
  `test_linux_launcher_executes_driver_self_check_end_to_end`이며 macOS에서 Linux seccomp API를
  실행할 수 없기 때문이다. Linux kernel-isolation re-proof는 완료되지 않았다.
- `uv run --locked ruff check src tests scripts`,
  `uv run --locked ruff format --check src tests scripts`, `git diff --check` — 통과.

Production code·configs·dependency lock은 변경하지 않았다. 저장소 전체 full suite와 real sampler,
fresh pod smoke, scientific run은 실행하지 않았다. COMPOSE 전체 회귀의 local green을 READY로
승격하지 않으며, 상세 admission/측정 설정과 runtime evidence는 남아 있다.

## 9. Report·측정 선택안 — 2026-09-11

Owner의 “순서대로 진행”에 따라 [R1 report·측정 설정 선택안](specs/2026-09-11-compose-r1-report-measurement-proposal.md)을
작성했다. Structural validity와 analytic V를 주 측정으로, budget-limited public 반복을 보조 검증으로
분리하는 안이다. Schema·admission 연결·alpha/eta·budget·numeric tolerance는 제안이며 미채택이다.
반복 수 공식의 비용 예시를 계산했지만 실제 Norman 결과나 pod timing을 생성하지 않았다.
해당 선택안의 채택 전에는 다음 schema/validator 구현과 scientific 실행으로 넘어가지 않는다.

## 10. Report 검증 역할 채택 — 2026-09-11

Owner의 “채택할게”로 [report 선택안 §4](specs/2026-09-11-compose-r1-report-measurement-proposal.md)의
structural/analytic 필수·public 반복 보조·모순 시 admission 보류 정책을 채택했다.
§9의 해당 역할 구분에 대한 미채택 상태는 이 기록으로 갱신한다. 수치 후보·budget·numeric bound·
strict schema와 consumer 계약은 남아 있다. 다음은 로컬 schema/validator·negative 검증이며
config 변경과 scientific 실행 승인은 포함하지 않는다.
