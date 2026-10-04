# ALIVE — 과학적으로 신뢰 가능한 Cartographer 목표와 milestone

2026-09-23 owner 정정: 최종목표는 **perturbation predictor에 이어붙였을 때 실제로 믿을 만한
신뢰값을 제공하는 과학적 도구**다. 기능 전달만으로 100%를 선언한 이전 판정은 철회한다.
이 문서는 현재 목표·완료 기준·개발 순서의 원문이며 [governance](../../CLAUDE.md#mission)를 따른다.
기존 scientific protocol의 claim/config/봉인을 소급 변경하거나 새 실험을 승인하지 않는다.

2026-09-24 보존 경로 변경: owner가 작업 초안과 확정 계약의 분리를 채택하여
`docs/superpowers/plans/`에서 `docs/contracts/`로 이동했다. 목표·판정 기준·기존 제안과
미확정 사항은 보존하며, 이 이동은 과학적 승인이나 milestone 통과를 의미하지 않는다.

> **2026-09-24 owner 채택:** 주 사용 목적은 사전 지정 유전자·유전자집합의 **발현 변화 방향과 크기에 대한 신뢰 평가**다.
> 전체 평균 발현 패턴 검증은 필수 진단으로 유지하고, 실험 우선순위 선정은 후속 응용으로 둔다.
> 아래의 scalar loss/ε와 mean-response 제안은 이 목적에 맞는 event 계약으로 구체화해야 하며,
> 전체 panel RMSE만으로 주 사용 목적의 성공을 판정하지 않는다.
> [채택 내용과 검증 영향](../superpowers/plans/2026-09-23-cartographer-followup-contract-draft.md#owner-adopted-use-contract--2026-09-24)이 현재 사용 목적의 원문이다.
> S1–S6의 독립 검증·두 predictor·실제 사용 인수 요건은 유지되며 과학적 실행 승인은 아니다.

## 1. 최종목표와 100%의 의미

고정된 predictor `f`의 예측에 대해, **무엇을 얼마나 믿는지 정의된 숫자**를 출력하고,
그 숫자가 실제 관측 error와 맞는지 독립 데이터로 검증한다. 숫자가 낮은 위험을 말할 때 실제
위험도 낮아야 하며, 충분한 수의 유용한 예측을 남겨야 한다. 모르면 근거 부족/지원 외로 보류한다.
원래 TrustGate 알고리즘을 유지하거나 새 알고리즘의 우월성을 주장하는 것 자체가 목표는 아니다.
단순 baseline이 가장 잘 검증되면 그것을 ALIVE의 신뢰 추정기로 채택할 수 있다.

100%는 아래 S1–S6의 **과학적 타당성과 실제 사용 인수 모두**가 충족된 상태다.
기능 완료, 문서 완비, error의 재현, 한계 공개, 음성 결과 보고만으로 대체하지 않는다.
반대로 모든 세포·모든 predictor에 대한 무조건적 보장을 약속하지 않는다. 지원 범위는 검증 전에
정하고, 실패를 본 뒤 범위를 줄여 성공 판정을 만들지 않는다. 실패하면 같은 목표를 미완료로 남긴다.

기존 50/75/100은 소프트웨어·보고 단계의 역사적 라벨로만 보존한다. 새 과학적 목표의 진척률로
변환하거나 테스트 수로 새 백분율을 계산하지 않는다. 현재 상태는 **기술 기반 확보 / 과학적 인수 미달**이다.

## 2. 신뢰값의 의미 — 제안하는 1차 제품 계약

입력 단위는 `(predictor version, perturbation, context)`다. 실제 예측값과 observed response의
거리 `E=L(f(x),y)`를 error로 정의하고, 사용 목적상 허용 가능한 오차 `ε`를 사전등록한다.
1차 신뢰값은 `p_good(x) ≈ P(E ≤ ε | 허용된 query 정보)`라는 **추정 확률**을 권장한다.
`ε`, loss, response representation, query population이 없으면 “90% 신뢰”라는 표현을 쓰지 않는다.
현재 gate score나 `1-score`는 이 확률이 아니며 이름만 바꿔 재사용할 수 없다.

| 출력 | 필요한 의미·검증 |
| --- | --- |
| `p_good` | 허용 error 이내일 확률 추정; 독립 probability calibration 및 proper score 검증 |
| `error_bound`를 제공할 경우 | error에 대한 bound와 nominal level, marginal/group/selected 중 보장 대상·가정 명시 |
| 사용/보류 | 사전 고정된 정책으로 선택한 집합의 실제 위험과 사용률을 별도 검증 |
| 적용 가능성 | predictor/feature/context identity, validated scope, evidence level, 지원 외/근거 부족 사유 |
| 근거 | 실제 검증 cohort/claim-unit N, calibration 및 risk CI, 실패 지역, 버전·provenance |

개별 query의 진짜 조건부 확률을 유한 표본으로 직접 인증했다고 주장하지 않는다. 사전 정의한
확률 구간/지원 subgroup에서 calibration을 검증하고 그 해상도·N·불확실성을 공개한다.
Distribution-free marginal 보장을 개별 조건부 보장으로 승격하는 것은 허용하지 않는다.[1]
선택된 집합의 risk 제어도 marginal conformal만 붙이면 자동 성립하지 않는다. 실제 선택 규칙에 맞는
방법과 별도 평가가 필요하며, 기대 risk 제어와 high-probability 보장도 구분한다.[2]

Observed `E` 자체도 finite-cell sampling/biological variability를 가진다. Controls·replicate·sampling
noise audit를 먼저 수행하고 latent biological truth와의 동일성을 가정하지 않는다. 기존 energy
distance는 후보일 뿐 새 사용 목적의 충분한 endpoint라고 자동 간주하지 않는다.

## 3. 과학적 인수 항목 — 모두 사전 잠금, 모두 통과 필요

| 항목 | 측정·판정 | 가짜 성공 방지 |
| --- | --- | --- |
| 숫자 의미 | loss/ε/population/단위·허용 입력·신뢰값 event 동결 | 정답 확률이 아닌 rank를 확률로 표시 금지 |
| 확률 calibration | 고정 probability bins의 관측 성공률과 평균 예측 확률 차이, simultaneous CI; Brier/log loss | ECE 점추정 하나로 통과 금지; bins의 N·폭·빈 구간 공개 |
| Risk ranking | paired target-level risk–coverage/AURC와 사전 operating points의 실제 error 및 failure-event rate | 같은 coverage 비교, random/constant 및 강한 단순 baseline 포함 |
| 실용성 | 선택 집합 failure risk의 one-sided upper bound ≤ 등록 risk budget, 사용률 lower bound ≥ 최소 사용률 | 전부 ABSTAIN, 무한/너무 넓은 bound로 통과 금지 |
| 비교 가치 | risk 감소가 사전 최소 유용 효과를 넘거나, 검증된 최선의 단순 방법을 제품 방법으로 채택 | `NO_DISTINCT_WIN`을 동등성/유용성으로 오해 금지; 비열등성은 별도 margin/검정 |
| 영역별 안전성 | outcome-independent subgroup/거리·batch·perturbation 유형별 동일 평가, simultaneous uncertainty | 전체 평균으로 중요한 실패 영역 은폐 금지; 표본 부족은 통과 아닌 미확립 |
| 독립 재현 | 동결 후 untouched evaluation과 추가 독립 검증 단위에서 재현 | seed·cell 수·같은 target 재분할을 독립 biological N으로 계산 금지 |
| 배포 연계 | 검증한 checkpoint→adapter→신뢰 추정기→정책→report가 동일 lineage | predictor 변경 시 기존 calibration의 자동 상속 금지 |

**설계 시작값(권고안, 미등록 실험값):** 최대 selected failure risk 0.10, one-sided confidence 0.95,
최소 사용률 0.50, 중요한 probability-bin calibration 오차 허용폭 0.05, 최소 검출 power 0.80을
feasibility 계산의 출발점으로 삼는다. 이는 보편적 생물학 상수가 아니며 기존 TG config를 바꾸지 않는다.
`ε`, 최소 유용 risk 감소 `Δ`, comparator 비열등성 margin, 주요 subgroup, multiplicity allocation,
정확한 N은 **아직 미확정**이다. 용도·noise floor·실패 비용·허용 자료의 pilot 기반으로 정당화하고
S1/S2에서 잠근다. 미확정 항목이 남으면 confirmatory 실행은 금지하며 현재 값을 통과 기준처럼 쓰지 않는다.
확률 bin의 동등성 판정은 CI가 허용폭 내부에 들어오는 것으로 정의하며 “유의한 차이가 없음”으로
대체하지 않는다. Clustered/dependent unit에 단순 iid binomial CI를 적용하지 않는다.

## 4. Milestone와 직접 입증 산출물

| 단계 | 해야 할 일 | 통과 증거 | 현재 상태 |
| --- | --- | --- | --- |
| S0 — 기반과 정직한 상태 | 기존 코드·actual error·baseline·음성 결과·검증 결손을 연결 | 기존 M2/M3/M4/M5와 기능 검증은 기술 자산으로 재분류 | 기반 확보; 과학적 성공 아님 |
| S1 — 신뢰 event·사용 계약 | primary predictor/context, loss/ε, user decision, 지원 범위·실패 비용·필수 claims 확정 | 별도 protocol spec + 빈칸 없는 estimand/acceptance/claim matrix | **다음 작업** |
| S2 — 적법한 독립 검증 설계 | source/checksum/license/exposure·unit/cluster 감사, 역할 split, control/noise, adequacy | exposure ledger, split manifest, registered baseline/analysis/power plan, 필요한 승인 | 미완료 |
| S3 — 신뢰 추정·보정 개발 | 기존 gate 및 단순 대안 비교, p_good calibration, risk-aware abstention; 개발 자료만 사용 | OOF 개발 결과·calibration 역할 격리·sanity/negative tests·동결 artifact | 기존 rank kernel 재사용 가능; probability/risk 인증 미완료 |
| S4 — 독립 과학적 인수 | 동결 방법을 untouched evaluation에서 등록 기준으로 1회 평가 | exact N·CI·전체 baseline·risk/coverage·subgroup·실패 포함 PASS/FAIL/INCONCLUSIVE 보고 | 미실행 |
| S5 — predictor 연결·재현 | 주 사용 predictor와 별도 frozen predictor에 실제 연결, 각자 calibration/held-out 인수 및 독립 replicate/cohort 검증 | predictor별 evidence card, 추가 독립 검증 결과, 잘못된 checkpoint/context 거부 | 현재는 단일 TG retrospective replay만 확보 |
| S6 — 과학적 도구 인수 **100%** | S1–S5 전부 충족, 실제 사용 E2E·재현·환경·지원/보류·drift 대응 전달 | 요구사항별 직접 증거, supported-use model card, 독립 재현 command/artifact | **미완료** |

S5의 두 번째 predictor는 새로운 predictor 연구 과제가 아니다. 기존 frozen checkpoint를 재사용해
신뢰 레이어의 연결 계약이 첫 모델에만 맞춘 replay인지 확인한다. 각 predictor에 독립 calibration/
평가가 필요하며 두 사례로 모든 모델에 일반화했다고 주장하지 않는다. 새로운 cell line/약물 데이터가
자동 필수는 아니지만, 독립 검증 cohort 또는 replicate는 최종 신뢰 주장에 필요한 증거로 계획한다.
같은 데이터 사용이 허용되는지는 claim과 노출 이력·독립 단위에 따라 판단한다.

## 5. 데이터 역할과 평가 오염 방지

1. Predictor 학습 노출까지 포함한 exposure ledger를 작성한다. 이미 본 TG evaluation 247개는
   어떤 새 이름/seed/split으로도 untouched test가 되지 않는다. 기존 411개 개발 요약은 탐색 자료다.
2. Predictor checkpoint를 freeze한다. 신뢰 모델 development/selection, probability/risk calibration,
   final evaluation 역할을 분리한다. Calibration 안에서도 확률 보정과 threshold 탐색의 재사용이
   이론적으로 정당하지 않으면 split 또는 적법한 cross-fitting/동시 제어를 설계한다.
3. Target·pair·replicate·batch 공유와 controls 공유를 기록한다. 같은 unit의 예측을 모든 comparator에
   paired로 적용한다. CI/resampling/power는 dependency 단위를 반영한다. 특정 biological N을 꾸며내지 않는다.
4. Calibration bins·subgroups·운영 coverage·failure thresholds·multiplicity·중단 규칙을 outcome 전에
   등록한다. Adaptive peeking 뒤 ordinary CI를 쓰지 않는다. N 부족은 INCONCLUSIVE로 판정한다.
5. 모든 baseline은 동일 input access·split·tuning budget을 사용한다. Constant event-rate probability,
   random ranking/no trust routing, nearest-feature/local-error, predictor native uncertainty(있을 때),
   허용된 supervised error/probability estimator를 roster 후보로 삼고 S1에서 확정한다.
6. 실패하면 artifact를 보존한다. 방법을 수정하려면 개발 단계로 돌아가고, 소모된 final evaluation을
   다시 최종 검증으로 사용하지 않는다. 새 claim에는 새 protocol/run/합법적 독립 평가가 필요하다.

## 6. 바로 이어질 작업과 결정 목록

첫 산출물은 **S1 계약 초안**이다. 구현을 늘리기 전에 다음 표를 빈칸 없이 완성할 근거를 조사한다.

진행 기록(2026-09-23): [기존 follow-up 초안의 S1 계약](../superpowers/plans/2026-09-23-cartographer-followup-contract-draft.md#s1-working-contract--subsequent-scientific-use-definition-2026-09-23)에
mean-response 사용 목적, event/loss 후보, 데이터 역할·결측 denominator와 미확정 결정을 구체화했다.
초안 작성은 S1 통과가 아니며 exact source/checkpoint·epsilon·독립 N은 아직 미확정이다.
후속 [checkpoint 감사](../superpowers/audits/2026-09-23-cartographer-source-feasibility.md#public-checkpoint-triage--2026-09-23)는
GEARS 공개 모델의 `no_test` 노출 위험과 scGPT foundation/task checkpoint 구분을 확인했다.
모델명만으로 실행 후보를 확정하지 않으며, 두 후보 모두 새 독립 평가 적격성은 아직 미확립이다.
후속 owner 결정(2026-09-23): **K562 CRISPRi cross-experiment/day-shift 검증 범위 채택**.
[구체화 계약](../superpowers/plans/2026-09-23-cartographer-followup-contract-draft.md#adopted-cross-experiment-validation-scope--2026-09-23)에
기록했다. 범위 선택 대기는 해소됐으며 metadata·pilot 계약 준비를 진행한다. Outcome 접근·학습·seal 실행
승인이 아니고, source 적격성·오차 허용값·독립 N·S1–S6 인수 기준은 여전히 충족해야 한다.

| 결정 | 결정 근거/담당 작업 | 완료 전 금지 |
| --- | --- | --- |
| 실제 사용 결정과 loss/ε | 예측을 무엇에 사용할지, noise audit·최소 유의미 변화와 연결한 선택지 제안; owner의 목적 선택 필요시 한 번에 확인 | test 결과로 ε 최적화 |
| 첫/두 번째 frozen predictor | 보유 checkpoint·training exposure·adapter/identity/입력 접근성 조사 | 재학습을 자동 선행조건으로 추가 |
| 검증 source와 독립 unit | metadata-only inventory + 노출/복제/controls 구조와 라이선스 확인 | 미승인 perturbed outcomes 열기 |
| 정량 acceptance·N | 위 시작값의 feasibility, 독립 unit별 precision/power·최소 선택 N 계산 | cells/seeds를 N으로 대체, 임의 margin 확정 |
| 신규 protocol/실행 권한 | 기존 draft를 검토해 재사용 가능 여부 확인 후 고유 ID·spec/plan/config·owner 승인 | TG seal 재개, COMPOSE/CT-RPE1 경계 우회 |

일상적인 문서·코드·synthetic 검증 승인을 반복 요청하지 않는다. Scientific access·새 protocol·config
lineage와 비용 결정은 기존 권한을 따른다. 이번 요청은 목표와 milestone 구체화이며 scientific run 승인이 아니다.
현재 configs/·source·seal·historical metric/verdict는 수정하지 않는다.

진행 기록(2026-09-28): 등록 protocol [CART-K562-D8-v1](2026-09-27-cart-k562-d8-v1-protocol.md)(개발 단계 종료, E 미개봉)과
[CART-K562-D8-v2](2026-09-28-cart-k562-d8-v2-protocol.md)로 S1–S4를 실데이터에서 수행했다. E를 1회 개봉한
[결과](2026-09-28-cart-k562-d8-v2-results.md)는 세 predictor × 두 event 모두 **FAIL**이다. State 방향 성공률 0.908,
크기 과대(기울기 0.716 [0.666, 0.764])는 확정 추정치로 남는다. S5 독립 반복과 S6는 **미완료**이며,
과학적 100%로 해석하지 않는다.

owner 결정(2026-09-29, “진행”): v2 결과를 바탕으로 **S6 최소 범위**를 채택했다. 범위는
**predictor 수준 · 방향(부호) · gene 단위의 검증된 신뢰 카드**이며, 계약 1절의 "단순 baseline 채택" 조항에 따른다.
이 범위는 새 독립 자료를 보기 전에 [CART-K562-V3](2026-09-29-cart-k562-v3-preregistration.md)로 사전 등록했다.
query별 신뢰, 크기 신뢰성, gene-set은 이 최소 범위에 포함되지 않으며 후속 과제로 남는다.
최소 범위를 달성해도 "S6 최소 범위 완료"로만 표기한다.

진행 기록(2026-10-04): 사전 기준을 고정한 power 분석에서 V3 원설계의 PASS 확률이 약 0.10으로 나왔다.
owner는 데이터가 생기기 전에 [CART-K562-V3.1](2026-10-04-cart-k562-v3-1-addendum.md)을 채택했다. 변경 내용은
N 960 nested, D/C/E 30/30/40, B0 accept-all이다. 임계값은 바꾸지 않았다. 확인 power는 0.828–0.902로,
기준은 넘지만 경계선 수준이다. 이 기록은 데이터 생성 승인이 아니다.

## 7. 연결 후보와 실제 Cartographer 검증 실험

권장 순서는 **기존 frozen linear/ridge 기준선 → GEARS → perturbation용 scGPT**다.
첫 기준선은 빠른 plumbing/sanity용이고, 최종 인수는 실제 predictor별 독립 과학적 검증을 요구한다.
모델 유명세·크기·논문 점수를 신뢰 레이어의 유효성 증거로 사용하지 않는다.

| 후보 | ALIVE 연결 방식·역할 | 선택 전 확인할 조건 |
| --- | --- | --- |
| 기존 additive-ridge | 현재 feature/predictor identity 경로를 재사용하는 연결 대조군; 새 적법한 평가 자료에서 검증 | TG 247 replay는 새 독립 검증 아님; mean-shift의 표현 한계 유지 |
| **GEARS — 첫 외부 predictor 권고** | genetic single/multi-gene perturbation의 expression prediction을 고정; 해당 모델의 실제 error를 ALIVE가 예측/보정 | checkpoint SHA·training split·gene axis·normalization 확보; 기존 COMPOSE worker/자료의 사용 승인과 분리 |
| **scGPT perturbation model — 다음 후보** | perturbation task로 준비된 checkpoint의 response prediction에 같은 평가 계약 적용 | base foundation checkpoint만으로 완료된 perturbation predictor라 부르지 않음; pretraining/fine-tuning exposure 및 gene vocabulary 감사 |
| scFoundation/CPA/기타 | 앞 후보가 접근성·독립 평가 요건을 만족하지 못하거나 다른 모델 계열의 검증이 필요할 때 검토 | 추가 모델/약물 데이터 수집을 진척의 대리변수로 삼지 않음 |

GEARS 공식 구현은 single/multi-gene prediction, 저장 모델 load와 prediction API를 제공한다.[3]
다만 cross-cell-type transfer용으로 설계되지 않았고 singles-only 학습으로 조합 예측 신뢰성을
가정할 수 없다고 명시한다. 따라서 첫 실험을 cross-cell-line이나 그 조건의 pair 일반화로 확장하지 않는다.
scGPT는 perturbation response prediction을 지원하지만 실제 task checkpoint와 학습 노출 검사가 필요하다.[4]
단순 linear 방법을 강한 대조군에 포함하는 것은 기존 benchmark 결과로도 정당화된다.[5]
현재 어떤 외부 checkpoint도 이번 계획에서 다운로드·검증·실행 완료한 것은 아니다.

**최소 실험의 질문:** “동일한 고정 GEARS 예측 중 ALIVE가 믿을 만하다고 선택한 것은 실제로
더 정확하며, 출력 확률과 실제 성공률이 맞고, 충분한 수를 남기는가?” Predictor 자체를 개선하지 않는다.

1. **계약·대상 잠금:** 1차로 한 cell context의 genetic perturbation claim을 권장한다. Single unseen-target와
   pair-held-out을 섞지 말고 하나를 S1에서 택한다. Pair의 constituent-gene seen/unseen 상태도 별도 명시한다.
   Replogle/Adamson/Norman은 후보 데이터일 뿐이며 exact source·노출·승인·unit/N을 감사하기 전 선택하지 않는다.
2. **오차 정의:** 예측 response와 observed response를 동일 gene axis/scale에서 비교한다. Mean-response
   predictor에는 control 대비 effect의 사전 고정 gene panel error를 primary 후보로 두고, 방향·effect-size
   오류를 보조 지표로 검토한다. 실제 distribution output을 주지 않는 모델에 distribution fidelity를
   주장하지 않는다. Test outcome으로 DE gene panel·HVG·표적 eligibility·ε를 선택하지 않는다.
3. **prediction freeze:** 적법한 역할별 query prediction, checkpoint/preprocessing hash와 uncertainty feature
   접근 예산을 고정한다. ALIVE에는 prediction, 허용 metadata/feature/native uncertainty만 제공하며
   평가 query의 실제 response/error는 제공하지 않는다. Predictor를 교체하거나 재학습하지 않는다.
4. **trust-layer 비교:** 같은 predictor·같은 query에서 ALIVE, native uncertainty(있을 때), feature-distance,
   local residual, supervised error/probability baseline, constant probability/random selection을 비교한다.
   서로 다른 predictor의 raw error 차이를 ALIVE의 개선으로 세지 않는다. 확률 보정과 selection budget을 맞춘다.
5. **한 번의 잠긴 평가:** prediction/error pair와 p_good로 calibration curve/CI·Brier·risk–coverage·선택 집합
   failure UCB/사용률 LCB를 계산한다. “p≈0.9 구간이 실제 약 90% 허용 error 이내인가”, “동일 사용률에서
   random/단순 baseline보다 실제 error가 줄었나”, “90% 성공을 얻으려 모두 보류한 것은 아닌가”를 함께 판정한다.
6. **실패 지도:** 사전에 정의한 feature 거리·batch·perturbation 종류 등에서 과신 영역을 드러낸다.
   Error 큰 영역을 사후 제외해 전체 점수를 개선하지 않는다. Probability calibration은 global constant만큼인
   경우 query-specific 신뢰 정보가 입증됐다고 보지 않는다. Synthetic shuffled-score/constant/mismatch
   검사는 evaluator sanity일 뿐 실제 데이터 성능 증거를 대신하지 않는다.
7. **독립 반복·두 번째 연결:** 개발에 노출되지 않은 별도 cohort/replicate에서 동결 정책을 검증하고,
   같은 계약으로 두 번째 frozen predictor에 ALIVE를 연결한다. 각 predictor의 calibration을 별도로 수행한다.
   새 setting의 recalibration이 필요하면 transfer 보장과 구분하고 해당 evaluation은 다시 독립 분리한다.

이 실험에서 과신·무용한 보류·baseline 대비 가치 부재가 드러나면 **FAIL/INCONCLUSIVE**다.
Adapter가 실행됐다는 사실로 성공시키지 않는다. 다음 산출물은 모델별 checkpoint/exposure/접근 가능성
목록과 S1 spec 초안이며, 지금은 outcome 접근·GEARS fit·scGPT fine-tuning·pod 생성 없이 조사한다.

## 8. 정정·self-review

정정: 이전 M4/M5의 테스트·wheel·지도·재현 결과는 유효한 기술 증거다. 그러나 제한을 표시했다는 이유로
과학적 유효성 입증을 제외한 **100% 추론은 철회**한다. 기존 보고 본문/수치/서명은 보존하고 정정 배너로 연결한다.

검토 1(목표): 확률 calibration만으로 constant score를 성공 처리하거나, ranking만 좋아도 잘못된
확률을 제공하거나, all-abstain으로 risk 목표를 통과하는 세 가지 탈출구를 차단했다.
검토 2(과학/권한): finite-sample conditional guarantee를 과장하지 않고, independent N·multiplicity·
선택/calibration 재사용·predictor exposure를 필수 설계 항목으로 넣었다. 음성 결과는 보존하지만
도구의 최종 과학적 성공으로 승격하지 않는다. 미등록 수치와 실행 승인은 명확히 분리했다.

## 근거와 사용한 skill

[1] Barber, Candès, Ramdas & Tibshirani. [The limits of distribution-free conditional predictive inference](https://arxiv.org/abs/1903.04684).
Marginal/conditional 구분과 가정 없는 정확한 조건부 보장의 한계를 반영했다.

[2] Angelopoulos, Bates, Fisch, Lei & Schuster. [Conformal Risk Control](https://arxiv.org/abs/2208.02814).
Risk 대상·가정·기대값 보장의 수준을 명시해야 한다는 설계 근거이며 자동 적용을 주장하지 않는다.

[3] Roohani, Huang & Leskovec. [GEARS 논문](https://www.nature.com/articles/s41587-023-01905-6),
[공식 구현·사용 제한](https://github.com/snap-stanford/GEARS).

[4] Cui et al. [scGPT](https://www.nature.com/articles/s41592-024-02201-0),
[공식 구현](https://github.com/bowang-lab/scGPT).

[5] [Deep-learning-based gene perturbation effect prediction does not yet outperform simple linear baselines](https://www.nature.com/articles/s41592-025-02772-6), Nature Methods (2025).

Scientific-critical-thinking과 experimental-design skill로 claim/증거·replication·역할 분리를 검토했다.
Kassis, T., Agarwal, V., He, Y., Patel, D., & Brueckner, A. M. (2026).
[Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents](https://doi.org/10.48550/arXiv.2609.00065).
2026-09-23 현재 v2 metadata 확인. Skill은 실제 과학적 검증 결과를 대신하지 않는다.
