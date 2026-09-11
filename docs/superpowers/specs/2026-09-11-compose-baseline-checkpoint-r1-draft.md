# COMPOSE — checkpoint/OOF 및 R1 상세 계약 초안

> **2026-09-11 후속 상태:** 일부 정책 채택, 상세 실행 계약은 미완. §7의 채택 범위가 아래
> 작성 당시 DRAFT 표기와 §5의 결정 목록에 대한 최신 처분이다. 전체 초안을 실행 가능 protocol로
> 승격한 것이 아니다.

> **DRAFT / NOT EFFECTIVE — 2026-09-11.** 설계 작성은 owner-approved
> [방향 기록](../2026-09-11-compose-baseline-design-direction.md)에 따른다.
> 아래 제안 조문·측정 설계는 아직 채택된 protocol이 아니다. 미결값이 있는 상태로 실행하지 않는다.
> COMPOSE-K562-v1 ACTIVE / RELEASE-BLOCKED / seal UNOPENED.
> 기존 spec·config·서명·실패 기록을 대체하지 않으며 config digest를 이동하지 않는다.

## 1. Checkpoint 계약 제안

### 1.1 권고하는 처분

[Deep-baseline spec §1.6](2026-07-01-compose-deep-baselines-design.md)의 후속 amendment로
아래 구분을 명시할 것을 제안한다. 기존 문장을 해석만으로 무효화하지 않는다.

1. **Outer selection:** COMPOSE operator의 hyperparameter 선택에는 등록된 calibration
   gene-disjoint OOF 계약을 그대로 적용한다. Deep baseline의 설정을 outcome을 보고 탐색하거나
   선택하지 않는다. 향후 baseline tuning/OOF 성능 주장이 필요하면 별도 fold-isolated 설계가 선행한다.
2. **Inner fitting:** CPA에 한하여 version-bound library checkpoint callback을 사전 고정된
   학습 알고리즘의 일부로 허용하는 명시적 예외를 제안한다. 내부 validation outcome이 checkpoint를
   선택한다는 사실을 숨기지 않는다. 그것을 outcome-free 선택이나 gene-disjoint OOF라고 부르지 않는다.
3. **GEARS:** 현 fixed-final-epoch 정책을 유지하는 안을 권고한다. Duplicate monitoring을
   독립 validation으로 재명명하지 않고, monitoring-selected best model은 사용하지 않는다.
   이는 COMPOSE adapter의 명시적 upstream 차이이며 완전한 published-pipeline 재현 주장과 구분한다.
4. **No adaptive retries:** callback/epoch/split/seed를 관측 결과에 맞춰 바꾸거나 좋은 checkpoint를
   여러 실행에서 고르지 않는다. 실패·미수렴은 보존하고, 변경은 새 사전등록과 lineage로 처리한다.

CPA 예외의 채택은 owner의 authoritative amendment가 필요하다. Owner가 이를 채택하지 않으면
CPA를 임의로 final-epoch로 바꾸거나 새 validation 구조를 구현하지 않고, 대체 설계를 별도 검토한다.
GEARS에 독립 validation을 추가하는 안도 이번 권고에 포함하지 않는다.

### 1.2 데이터 경계와 정확한 학습 설정

| 데이터 | 허용 용도 | 금지 용도 |
|---|---|---|
| singles + combo_calibration | 등록된 worker 학습; CPA의 사전 고정 내부 split | outcome을 본 설정 탐색, 새로운 claim-unit 평가로 위장 |
| control reference | 등록된 preprocessing/reference 및 post-fit query | optimizer/validation loader로 편입 |
| 내부 validation expression | 제안된 CPA checkpoint 선택만 | train-only DEG preprocessing, 독립 pair-generalization 주장 |
| 내부 validation metadata | 등록된 split/category 및 epoch 행 수 계산 | expression을 metadata로 위장한 선택·전처리 |
| sealed pair identity | 고정된 request의 post-fit 예측 | 요청 조건을 fit category·epoch 계산·DEG mask에 포함 |
| sealed expression | 이번 설계/개발에서 사용 없음 | 조회·materialization·선택·전처리 |

CPA의 내부 split은 현 worker의 deterministic within-condition 계약을 후보로 유지한다.
`test`라는 내부 split 이름은 protocol의 sealed evaluation role이 아니다. 조건별 train/validation 수,
reference 수, 총 fit-artifact 행 수를 별도로 기록한다. Epoch 공식의 N은 현재 구현상 reference와
validation을 포함하는 `train_adata.n_obs`이며 optimizer 행 수와 구분한다. 이 값들은 effective
configuration에 명시하고 installed wheel 기본값·adapter 변경·payload seed를 각각 추적한다.
여기서 train-only DEG 격리는 worker 내부 경계다. Shared response basis까지 internal validation으로부터
독립적으로 적합됐다는 주장은 아니다. Response basis의 적합 role은 기존 상위 계약을 따르고,
내부 validation은 독립 generalization 추정치로 보고하지 않는다.

### 1.3 현재 구현과 후속 검증의 경계

[phase2a.py](../../../src/alive/compose/phase2a.py)의 현재 경로는 L1 factory로 futility/OOF를
수행한 뒤, CONTINUE일 때 `_predict_combined_adapters`에서 GEARS/CPA를 각 한 번 호출한다.
현재 deep-baseline별 fold 재학습/OOF 평가가 구현됐다고 주장하지 않는다.
[기존 findings §2.2](../2026-07-10-compose-phase1-dev-pod-findings.md)의 outer OOF 문장은
이 구분 없이 GEARS/CPA의 OOF 성능 증거로 인용하지 않는다. 기존 기록 자체는 보존한다.

채택 후 검증해야 할 항목은 checkpoint bytes와 최종 예측의 동일 모델 결속, duplicate monitoring이
GEARS checkpoint를 선택하지 못함, CPA validation expression이 train-only DEG 입력을 바꾸지 못함,
request roster가 fitted state를 바꾸지 못함, seed/split/config tamper 거부다. 기존 테스트의 존재는
locked real runtime에서의 통과나 독립 review를 대신하지 않는다.

## 2. R1 입력·출력 계약 제안

등록된 full-gene raw row를 x, frozen normalization target을 L, response HVG selector를 H,
PCA mean을 a, components를 W라 하자. Full-library transformation을
`t(x) = log1p(x * L / safe_library(x))`, affine response map을
`A(u) = (u_H - a) W^T`로 정의한다. Zero-library 처리는 기존 response 계약을 따른다.
Truth는 계속 `mean_cells(A(t(x))) - control_mean`이며 변경하지 않는다.

입력 후보는 기존 `normalize_full_then_subset`와 동일하게 full-gene library에서 먼저 t를 계산하고
등록된 GEARS roster로 subset한다. L은 frozen response artifact의 `median_library`를 사용한다.
이를 upstream의 다른 normalization target과 동일하다고 주장하지 않으며, version-specific
preprocessing 비교표에서 차이를 밝혀야 한다. Roster는 outcome-independent 등록 절차를 유지하고
response HVG와 필요한 perturbation gene의 포함·순서·alias·누락 정책을 검증한다.

GEARS fitted model의 control-row별 native log-scale 출력은 signed finite 값으로 보존한다.
출력에는 raw normalization/log를 다시 적용하지 않고 A만 적용한다. 현재
[projection helper](../../../src/alive/compose/fit_role.py)는 log 후보를 지원하지만 full gene-order
digest를 요구한다. Subset roster 출력은 HVG의 정확한 identity mapping을 증명하는 adapter가 필요하다.
전체 유전자 예측이 존재한다고 가장하거나 missing HVG를 zero-fill하지 않는다. Helper 변경 여부와
schema는 후속 구현안에서 정하되 기존 full-order guard를 우회하지 않는다.
생산 예측의 delta는 `A(native_public_mean(q)) - control_mean`으로 제안한다. p는 payload의 실제
평가 response dimension으로 고정하고 A·reference·sampling 식에 동일 좌표만 사용한다. 전체 PCA
좌표로 계산한 오차를 앞 p개 좌표의 평가 오차라고 보고하지 않는다. Truth와 control_mean의 lineage는
기존 response artifact에 결속하며 이 probe 결과를 보고 다시 적합하지 않는다.

## 3. R1 측정안 — 서로 다른 세 오차를 분리

### 3.1 Projection known-answer

같은 row 집합과 같은 가중치에서는 `A(mean(u)) = mean(A(u))`다. 이는 affine 계산의 identity일
뿐 GEARS 정확도, whole-control equivalence 또는 population 일반화의 증명이 아니다.
Signed input, 비영 PCA mean, column permutation, 누락 HVG, double-log/clip 오류를 synthetic
known-answer와 negative test로 검증한다. Float tolerance는 dtype·연산 경로를 근거로 사전 고정하며
과거 실패값에 맞춰 정하지 않는다.

### 3.2 Conditional control-sampling discrepancy

새 설계의 기준은 **고정된 한 fitted model과 등록된 전체 control pool**이다. Pair q에 대해
각 control의 projected model output을 y(q,j), pool 크기를 n, response dimension을 p라 하자.
기준 평균은 `mu(q) = sum_j y(q,j)/n`이다. 이 값은 관측 perturbation truth가 아니라 model reference다.
여기서 q는 사전등록한 singles/combo_calibration의 pair identity만이며 sealed pair에 대한 측정은
포함하지 않는다. Control pool의 행 identity·순서·중복 의미·제외 정책을 고정하고 `n >= 1`,
`m >= 1`, `p >= 1` 및 모든 y의 finite 값을 요구한다. Pair 선택·제외는 model output을 사용하지 않는다.

Pinned public backend의 m개 uniform replacement draw가 IID이고 동일 per-control 함수를 계산함이
확인된 경우에만 다음 식을 사용한다.

`V(q) = sum_j ||y(q,j) - mu(q)||^2 / (n * m * p)`

이는 한 public sample mean의 **conditional expected squared sampling error**다. Replacement이므로
finite-population correction을 적용하지 않는다. `control_mean` 차감은 두 경로에 같아서 상쇄된다.
Pinned backend의 역사적 m은 300이지만, 새 runtime의 sample count와 sampler 의미를 artifact로
검증해야 한다. Nonuniform draw, batch-dependent model output 또는 state mutation이면 식을 적용하지
않고 contract mismatch로 중단한다. Reference도 bounded control blocks로 계산한다.
고정 모델에는 weight뿐 아니라 eval mode·BatchNorm buffer 등 예측에 영향을 주는 상태가 포함된다.
Reference와 public 경로의 batch 분할 불변성은 float tolerance 내에서 검증하고, 수치 반올림을
제외한 batch 의존성은 허용하지 않는다. V는 finite pool이 주어졌을 때의 이론적 기대 오차이지
각 draw의 상한이나 모든 draw가 만족해야 할 tolerance가 아니다.

새로 사전등록한 반복에서 public mean과 mu의 discrepancy를 보존해 이 sampling 설명을 점검한다.
반복 횟수·seed roster·pair roster·aggregate 통계·구간 및 판정 기준은 실행 전에 고정해야 한다.
과거 public index를 replay하거나 관측 draw에 맞춰 reference를 바꿔 exact equality를 만드는 설계가
아니다. 반복 결과를 평균해 production GEARS의 300-draw 예측을 몰래 다른 estimator로 바꾸지 않는다.
반복마다 같은 checkpoint에서 fresh prediction state를 만들고 예측 cache 재사용이 없음을 확인한다.
모델을 재학습하지 않으며, training RNG와 sampling RNG를 분리해 seed·state·호출 순서를 기록한다.
별도 observer의 RNG 소비가 public draw를 바꾸지 못하게 한다. 서로 다른 반복이 같은 seed를
재설정해 동일 draw를 재생한 경우 독립 반복으로 세지 않는다. 이 조건을 runtime에서 입증할 수 없으면
sampling 검증을 수행하지 않는다. 현재 backend가 이 조건을 충족한다는 주장은 아니다.

### 3.3 Model prediction error와 non-claim

`mu(q)`와 observed transformed response의 차이는 model error를 포함하므로 model-free representation
floor라 부르지 않는다. 학습에 사용한 singles/calibration pair의 오차는 in-sample diagnostic이며
held-out 성능·GI 학습·sealed adequacy의 증거가 아니다. 이 설계에서는 새 성능 평가를 추가하지 않는다.

V(q)는 과거 raw-pseudobulk Jensen gap과 estimand가 다르다. 기존 ratio·`R_star`·flag를 자동 승계하지
않는다. 현 [bias spec](2026-07-13-compose-approximation-bias-metric-design.md)의 raw metric은 그대로
두고 새 metric/schema/admission 소비 계약을 별도 amendment로 정해야 한다. Projection identity만
확인하고 bias report를 0으로 채워 blocker를 해소해서는 안 된다.
Integrity/bridge mismatch로 인한 invalid evidence와, 유효한 측정에서 큰 sampling discrepancy가
나온 결과를 구분한다. 후자의 admission·narrative 처분은 아직 미결이며, 유한한 큰 오차를 숨기거나
기존 comparator를 대체하는 규칙을 이 초안에서 추가하지 않는다.

## 4. Provenance, 실패 및 검증 설계

신규 registration은 기존 [2026-07-20 FAIL](../audits/2026-07-20-compose-probe-a-negative-result.md)을
parent negative evidence로 명시하고 새 질문·estimator·실행 identity를 구분한다. 기존 registration,
threshold, 결과, seal audit는 덮어쓰지 않는다. 그 기록의 verifier/runtime 선행조건도 유지한다.

Exact N은 fit condition/pair 수, condition별 optimizer/validation cell 수, reference controls,
measured pair 수, response dimension, draw 수, 반복 수, training seed 수를 분리한다. 같은 control을
replacement로 여러 번 뽑은 것은 biological replicate 증가가 아니다. 등록된 finite pool 조건부 V와
pair population의 불확실성을 구분하고 shared-gene pair dependence를 무시한 독립 표본 CI를 주장하지 않는다.

Required lineage는 config/worker/package artifact/image/resource/roster/response/checkpoint/registration/
raw-output/verification digest와 role/read audit다. Missing·nonfinite·identity mismatch는 제외 후
성공 처리하지 않고 실패로 보존한다. Guard와 signed evidence는 additive-only 원칙을 따른다.

| 검증 | 기대 성질 |
|---|---|
| Affine known-answer | 동일 row·가중치에서 두 projection 경로 일치 |
| Constant per-control outputs | V=0; 모든 sample mean이 reference와 일치 |
| 작은 두-control 열거 예제 | 모든 replacement draw를 열거한 평균 squared error와 V 일치 |
| RNG/cache/batch negative | repeated cache를 독립 draw로 집계하지 않음; observer RNG·batch 분할의 부당한 영향 검출 |
| Signed/column/tamper negative | clipping·double-log·wrong order·missing HVG·digest mismatch 검출 |
| Role/request isolation | forbidden expression read 0; request 변화가 fitted state에 영향 없음 |
| Evidence negative | 기존 failed receipt와 representation mismatch를 admission으로 승격 불가 |

이 표는 테스트 **계획**이지 실행 결과가 아니다. Mutation harness로 검증할 때 kill은 named test의
own-frame AssertionError여야 하고 guard mock은 금지한다. Negative arm은 capture-and-assert한다.

## 5. 채택 전 필요한 결정과 구현 순서

| 결정 | 이 초안의 권고 | 아직 필요한 것 |
|---|---|---|
| Checkpoint | GEARS fixed final epoch; CPA predefined callback 예외 | authoritative spec amendment의 명시적 채택 |
| R1 scale | response L로 full-normalize/log 후 registered roster | upstream 대비 adaptation 수용 및 exact mapping/schema |
| R1 report | projection identity와 conditional sampling error 분리 | metric/flag/admission 의미와 schema 승인; 기존 R_star 자동 사용 금지 |
| Sampling validation | fresh preregistered repeats + finite-pool analytic reference | exact repeats/seeds/roster/tolerance/interval·판정 기준 |
| Execution | 기존 실패·seal·lineage 보존 | runtime/verifier 선행조건, exact artifact 증명, 별도 실행 승인 |

문서 채택 → signed additive amendment → library/worker/schema 및 synthetic negative 구현 →
targeted/COMPOSE/Ruff 및 관련 isolation 검증 순으로 진행한다. 이후 실행 계약은 현 bias spec의
one-way identity 순서를 보존하도록 새 metric 계약에도 명시해야 한다.

1. 승인된 모든 scientific field와 새 report 계약을 먼저 확정하고, report SHA leaf만 null인 basis
   config와 producer code/spec을 실행 commit C에 고정한다. 이는 별도 config 변경 승인 대상이다.
2. 별도 승인된 측정은 C와 basis config를 입력으로 새 durable evidence를 Git worktree 밖에 생성한다.
   Report에 자신을 포함하는 final config SHA를 기록해 순환 결속을 만들지 않는다.
3. Finalizer는 그 report SHA leaf만 채운 derived final config를 immutable runtime artifact로
   생성한다. 다른 semantic field 변경은 거부하며, report/derived config를 commit해 C를 이동하지 않는다.
4. Final config 기준 activation evidence를 재생성하고 current ActivationRecord, exact SHA 승인,
   readiness와 최종 owner release gate를 확인한다.

앞 단계의 완료로 뒷 단계 승인을 추정하지 않는다. 미결값을 임의로 채우지 않으며 현재 scientific
run은 계속 보류한다. 신규 schema의 leaf·검증 계약 자체가 미결인 동안 현 finalizer로 log report를
생성·admit하려 하지 않는다.

## 6. 초안 self-review 기록 — 2026-09-11

수렴 기준은 수정 후 연속 두 라운드에서 새로운 문서 수정사항이 없는 것이다. Owner의 미결 결정,
real-runtime 검증, 독립 review 또는 scientific readiness의 완료 기준이 아니다.

| 라운드 | 관점 | 결과 |
|---|---|---|
| 1 | 계약·실행 순서·측정 가정 | basis-config 선행 고정, validation metadata 경계, delta/p 정의, non-sealed 측정 roster, RNG/cache/batch 상태, invalid evidence와 큰 오차의 구분을 보완 |
| 2 | authoritative 계약·과거 FAIL·sampling 수식 | 새 수정사항 없음; conditional sampling 식의 작은 정확 열거 확인 |
| 3 | projection 반례·승인 범위·구현 경계 | 새 수정사항 없음; signed affine 예제와 clipping 반례 확인 |

실행한 검증:

- `uv run --locked pytest -q tests/test_claude_md_anchors.py tests/test_documentation_hygiene.py`:
  7 passed. 링크·governance anchor·현재 상태 문서 검사이며 scientific 검증이 아니다.
- `uv run --locked python -`의 임시 표준라이브러리 `fractions.Fraction`/`itertools.product` 계산:
  두 control `(-2,1), (4,3)`, p=2, m=1/2/3의 모든 replacement draw를 열거했다.
  평균 squared error와 V가 각각 `5`, `5/2`, `5/3`으로 정확히 일치했다.
  두 control 모두 `(5,-1)`인 상수 경우에는 같은 세 m에서 모두 0이었다.
- 같은 방식의 affine 예제: 위 비상수 control에 가중치 `(1/4,3/4)`, center `(2,-3)`,
  components `((1,2),(-1,1))`를 사용해 두 경로가 `(23/2,5)`로 일치했다.
  Native 음수를 zero-clip하면 결과가 달라지는 반례도 확인했다.
- `git diff --check`: 통과.

임시 산술 확인은 production projection/worker 테스트를 호출한 것이 아니고 §4의 테스트 계획을
구현·완료한 것도 아니다. 코드·config 변경, pod 접속, real data 읽기, 학습·seal 실행은 하지 않았다.
따라서 §5의 미결사항과 DRAFT / NOT EFFECTIVE 상태를 유지한다.

## 7. 부분 채택 — 2026-09-11

Owner의 후속 “그렇게 진행해”에 따라 checkpoint 정책은
[deep-baseline spec §8](2026-07-01-compose-deep-baselines-design.md)에, R1 log 설계 방향과
유효성/오차 해석의 분리는 [bias spec §9](2026-07-13-compose-approximation-bias-metric-design.md)에
additive amendment로 반영했다. §5의 checkpoint **정책 선택**과 R1 scale **설계 방향**은 채택됐으나
exact config·mapping/schema·runtime evidence의 완료를 뜻하지 않는다.

Sampling 반복 수·seed/roster·수치 tolerance·정밀도/오류율·interval, metric/schema/flag/admission의
상세 소비 규칙은 미결이다. Source/sampler/cache/batch 검증과 기존 negative의 보존도 계속 필요하다.
Synthetic 검증은 기존 production projection의 수치 계약과 작은 replacement 열거를 다루며,
GEARS sampling runtime 또는 production report 생성·admission 구현을 대신하지 않는다.
