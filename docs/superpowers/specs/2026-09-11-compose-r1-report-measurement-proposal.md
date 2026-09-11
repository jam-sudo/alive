# COMPOSE R1 — report 및 측정 설정 선택안

> **2026-09-11 후속 상태: 검증 역할·처분 정책 채택.** Owner의 “채택할게”에 따른 범위는 §4다.
> 아래 작성 당시 PROPOSED 표기는 수치·strict schema·runtime 실행 계약에 대해서는 계속 유효하다.

> **PROPOSED / NOT EFFECTIVE — 2026-09-11.** Owner의 “순서대로 진행”에 따라
> report 계약(1)과 측정 설정의 근거(2)를 작성한다. 아래 schema·판정·수치는 채택 전 제안이다.
> COMPOSE-K562-v1 ACTIVE / RELEASE-BLOCKED / seal UNOPENED.
> [채택된 방향](../2026-09-11-compose-baseline-design-direction.md)과
> [상세 초안](2026-09-11-compose-baseline-checkpoint-r1-draft.md)을 구체화하며,
> 기존 raw bias report 또는 과거 failed Probe-A를 대체·승격하지 않는다.

## 1. Report 계약 권고

### 1.1 세 축을 분리

주 측정값은 frozen model·control pool에 조건부인 analytic sampling MSE V(q)다.
Projection known-answer는 adapter 정확성이고, public 반복은 sampler의 보조 검증이다.
V(q)를 biological noise, model-free representation floor, GI signal 또는 prediction accuracy로
부르지 않는다. Conditional expectation이므로 V 자체에 Monte Carlo CI를 붙이지 않는다.
Control population·training seed·pair population의 불확실성은 V의 조건부 범위 밖이다.

제안 schema identifier는 `compose_gears_log_sampling_report_v1`이다. 기존
`compose_approximation_bias_report_v4`에 payload만 넣지 않는다. 현재 consumer가 이 schema를
지원한다는 뜻은 아니며, 최종 schema와 admission wiring은 별도 채택·구현이 필요하다.

| 필드 묶음 | 필요한 내용 |
|---|---|
| identity | protocol, method=log_normalized_pseudobulk, basis config/contract/code/checkpoint/response/roster/runtime digest |
| registration | 외부에서 고정한 registration·verifier digest, approved pair/control roster, RNG/precision/cost 정책 |
| exact_n | measured pair 수, training seed 수, control 행/unique identity 수, condition별 fit/validation 수, p, m, 요청/완료 public 반복 수 |
| structural_checks | input scale, full→subset mapping, finite signed projection, state/cache/batch/RNG 검증별 결과와 raw evidence |
| analytic_per_pair | q, n, p, m, projected reference mean, sum of squared centered outputs, V, bound B, 단위·계산 dtype |
| public_per_pair | 반복별 seed/state·output digest, discrepancy, 요청/실행 수, mean·interval·precision 및 검증 상태 |
| disposition | validity, verification status, narrative limitations, admission eligibility와 reason codes |

Fields는 필요한 semantic 목록이며, strict JSON key/type/finite encoding·canonical checksum 규칙을
아직 구현한 것이 아니다. Missing과 zero를 구분하고 pair·seed 누락을 집계에서 조용히 버리지 않는다.
실측 raw outputs는 repo 밖 immutable archive에 두며, validator는 scalar 자기선언만 신뢰하지 않고
V·집계·identity를 재계산한다. Report 자체 checksum은 외부 승인/authentication을 대신하지 않는다.

### 1.2 제안 판정 규칙

- `INVALID`: role/identity/finite/mapping/state/cache/sampler 계약 위반. Admission 불가이며
  측정값과 실패 원인을 보존한다. Stats를 계산할 수 없다고 zero로 채우지 않는다.
- `VALID_CONDITIONAL`: 모든 구조적 가정이 증명되고 analytic V가 재계산 가능함.
  그 값의 크기는 continuous diagnostic으로 보고한다. 작은 값도 scientific win이 아니다.
- Public corroboration은 `WITHIN_PRECISION`, `DISCREPANCY`, `INCONCLUSIVE`, `NOT_RUN_BUDGET`를
  별도로 기록한다. 불일치가 검출되지 않았다는 사실을 sampler 동등성의 증명으로 쓰지 않는다.

권고하는 **새 설계 선택**은 analytic/structural 검증을 필수로, public Monte Carlo 정밀도 달성을
보조로 두는 것이다. `INCONCLUSIVE`/`NOT_RUN_BUDGET` 자체를 실패나 PASS로 바꾸지 않고 제한을
붙인다. 단, 구조적 sampler 증명이 빠진 것을 public 반복 생략으로 대체할 수 없다.
`DISCREPANCY`는 원인 조사 전 admission eligibility를 보류한다. 유효한 V가 크다는 사실만으로
reject하거나 comparator를 제거하지 않는다. Error magnitude와 contract contradiction은 다르다.

이 역할 구분은 **미승인**이며, 기존 Probe-A 실패 gate의 완화가 아니다. 별도 신규 등록으로만
채택할 수 있다. Report eligibility가 충족되어도 현재 finalizer는 새 report를 admit할 수 없고,
consumer 계약 변경·새 evidence lineage·release gate가 별도로 필요하다. 기존 R_star/flag나
scientific verdict의 threshold를 이 보고서로 변경하지 않는다.

## 2. 측정 설정 권고와 도출 근거

### 2.1 Roster, reference 및 randomization

측정 pair는 승인된 non-sealed singles/combo_calibration roster 전체를 우선 제안한다. 비용 때문에
subset이 필요하면 model output과 무관한 metadata-only 선정 규칙·exact roster를 실행 전 별도
고정한다. Control reference는 등록 pool 전체를 bounded blocks로 계산한다. Training seed roster와
production m은 새로 최적화하지 않고 method의 승인된 설정에 결속한다.

Public 반복은 같은 checkpoint의 fresh state에서 수행하고, 전체 seed/호출 순서를 output 접근 전
고정한다. 사용한 모든 반복을 보고하며 성공할 때까지 seed를 바꾸지 않는다. Fresh seed라는 사실만으로
IID 증명을 대체하지 않는다. Sampler 소스·runtime·cache·batch 증거가 선행한다.

### 2.2 기대 오차와 분포에 의존하지 않는 보수적 반복 수

기존 초안의 y(q,j), mu(q), n, m, p에 대해

`V(q) = sum_j ||y(q,j)-mu(q)||^2 / (n*m*p)`

`B(q) = max_j ||y(q,j)-mu(q)||^2 / p`

라 하자. 검증된 동일 per-control 출력의 convex average인 public mean에 대해 반복별
`Z(q,r) = ||public_mean(q,r)-mu(q)||^2/p`는 exact arithmetic에서 `[0,B(q)]`에 속한다.
Target sampler 가정하에서는 `E[Z]=V`다. 관측 Z가 증명된 수치오차 여유를 포함한 bound 밖이면
clip하지 않고 contract discrepancy로 보존한다. Bound 자체의 가정은 통계적 비기각으로 증명하지 않는다.

R개 독립 반복의 mean을 Zbar, 사전등록한 전체 pair×training-seed 검증 수를 H, family error budget을
alpha라 하면 보수적인 half-width는

`h(q,R) = B(q) * sqrt(log(2*H/alpha)/(2*R))`

이다. 이는 bounded independent variables의 Hoeffding inequality와 union bound를 적용한 도출이다.
Pair 간 독립은 필요 없지만 각 pair의 반복 독립과 bounds는 필요하다.
[원논문: Hoeffding (1963)](https://doi.org/10.1080/01621459.1963.10500830).
이 구간은 Monte Carlo 반복의 평균에 대한 것이며 biological/pair-generalization CI가 아니다.

V>0에서 relative tolerance eta에 대해 `h <= eta*V/2`를 원하는 경우 필요한 보수적 반복 수는

`R_req(q) = ceil(2 * B(q)^2 * log(2*H/alpha) / (eta^2 * V(q)^2))`

다. Floating-point error allowance는 이 식에 포함되지 않는다. 적용 전에 별도 상계로 interval을
확장하고 precision 예산에서 차감해야 한다. Numeric error가 precision 예산을 소진하면 판정 불가다.
V=0은 위 나눗셈을 하지 않는다. 정확히 constant pool이면 analytic 값 0을 기록하며, runtime public
검증의 반복 수와 numeric allowance는 별도 사전등록이 없으면 `INCONCLUSIVE`로 둔다.

Public CI가 `(1±eta)*V` 범위 안에 포함되면 `WITHIN_PRECISION`, 두 구간이 겹치지 않으면
`DISCREPANCY`, 나머지는 `INCONCLUSIVE`로 제안한다. 단순히 V가 CI에 있다는 이유로 PASS하지 않는다.
이 비교는 conditional expected squared discrepancy라는 **한 moment의 정합성**만 다루며,
sampler 전체 분포의 equivalence를 증명하지 않는다.

### 2.3 수치 선택안과 비용 제한

비교용 기본 선택안은 **family alpha=0.05, eta=0.10**이다. 각각 전체 Monte Carlo interval의
오류 예산과 conditional expected sampling MSE의 상대 정밀도 목표다. 이는 scientific material
margin이 아니며, ALIVE 목적에서 자동 도출된 상수도 아니다. 95% family coverage와 ±10% 진단
해상도를 제안하는 owner 선택이며 아직 승인되지 않았다. 더 엄격한 목표는 비용을 증가시킨다.

이 식은 매우 보수적이다. Local 산술 예시(H=1, alpha=0.05, eta=0.10)에서 B/V=1이면 R_req=738,
B/V=300이면 R_req=66,399,831이다. H=10이면 각각 1,199와 107,846,362다. 이는 실데이터·runtime
측정이 아닌 공식 계산이며, 이 횟수로 pod를 실행하라는 권고가 아니다.
V>0이면 `B/V >= m`이므로 m=300인 target sampler에서 B/V=1 예시는 성립하지 않는다.
그 예시는 식의 단위 확인용일 뿐이다. m=300에서는 최소한 B/V=300의 보수적 비용부터 고려해야 한다.
따라서 이 bound의 precision 달성을 무조건 admission 요건으로 삼는 안은 권고하지 않는다.

권고는 **무제한 precision 추구 대신 사전 예산 cap + 정직한 미결 보고**다. 승인할 항목은 전체
wall-time/비용 cap과 pair별 배분 규칙이다. Output-independent timing evidence와 등록된 식을 이용해
실행 전에 R_budget을 고정한다. 이 실행에는 `R_budget >= R_req` 달성을 보장하지 않는다.
실행 후 목표를 못 채우면 `INCONCLUSIVE`, 반복 자체가 없으면 `NOT_RUN_BUDGET`을 남긴다.
Observed public discrepancy를 보고 cap/반복 수를 늘려 PASS를 얻는 optional stopping은 금지한다.

Reference 출력으로 얻은 B/V는 precision adequacy를 보고하는 데 사용하며 model·roster·seed나
이번 실행의 R_budget을 선택하는 데 사용하지 않는 안을 권고한다. 이후 더 효율적인 bound 또는
새 budget 설계를 검토하더라도 기존 실행 결과는 보존하고 새 사전등록 없이는 재실행하지 않는다.

### 2.4 Numeric tolerance는 별도 결정

Float64 reference reduction의 오차, public float32 aggregation의 오차, backend forward의 batch
차이를 따로 다룬다. 연산 길이·dtype·scale을 근거로 synthetic stress/known-answer에서 bound 정책을
사전 고정한다. 기존 실패의 1e-5를 그대로 가져오거나 measured maximum에 맞춰 여유를 정하지 않는다.
단순 dtype epsilon만으로 전체 neural forward 오차를 증명했다고 주장하지 않는다.
이 numeric policy와 budget 숫자는 아직 미결이므로 현재 문서는 실행용 registration이 아니다.

## 3. 구현 전 채택해야 할 선택

1. 새 report에서 structural/analytic 검증은 필수, public precision은 보조로 둘지.
2. Alpha=0.05·eta=0.10의 제안, 예산 cap·배분·R_budget, zero-V runtime 검증 정책.
3. Numeric bound 정책, strict schema·reason codes, eligibility와 consumer/admission의 연결.

이 선택들이 채택되면 schema/validator, bounded analytic accumulator, RNG/cache/batch evidence 및
known-answer/negative tests 구현으로 넘어간다. 현재는 문서 제안 단계에서 멈추며 code/config,
registered threshold, pod, scientific seal을 변경하지 않는다. Basis config → external report →
report-SHA-only finalization → activation evidence의 기존 단방향 lineage를 유지한다.

## 4. Owner 채택 — 2026-09-11

Owner의 “채택할게”에 따라 다음 검증 역할과 처분 정책을 채택한다. 기존 §3의 첫 번째 미결
선택은 이 기록으로 결정됐으며, 전체 선택안의 모든 수치와 구현 세부를 일괄 승인한 것은 아니다.

- Structural/analytic 검증은 필수다. Input·projection·sampler·RNG·cache·batch 계약 증명과
  analytic 오차 재계산 중 하나라도 미충족이면 admission 불가다.
- Public 반복은 사전 예산이 제한된 보조 검증이다. Precision 부족은 `INCONCLUSIVE`,
  budget상 미실행은 `NOT_RUN_BUDGET`으로 보존하며, 어느 것도 PASS나 sampler 증명이 아니다.
  보조 검증을 생략해서 필수 구조적 증명의 부재를 감출 수 없다.
- Public 결과가 분석적 설명과 모순되면 구조적 검증 통과 여부와 무관하게 admission을 보류한다.
  모순의 판정 규칙은 사전 고정하고, 원인 규명 없이 재실행·제외로 성공 처리하지 않는다.
- 유효한 큰 sampling 오차는 수치와 비교 한계로 보고한다. Comparator 제거, 기존 FAIL 삭제,
  scientific verdict threshold 변경에 사용하지 않는다.
- Alpha=0.05·eta=0.10은 진단 목표 **후보**로 유지한다. Exact budget·반복 수는 timing 근거와
  사전 승인으로 고정하고, numeric bound·zero-V 정책도 실행 전에 확정해야 한다.

이 정책의 authoritative 반영은 [bias spec §10](2026-07-13-compose-approximation-bias-metric-design.md)이다.
다음 작업은 이 정책을 strict schema·validator·실패 테스트로 구체화하는 로컬 구현이다. 미결 수치를
default로 발명하거나 현재 finalizer를 새 schema에 대해 열어 두는 것은 허용하지 않는다.
Schema·numeric 정책·runtime evidence가 완성되기 전 scientific admission은 계속 불가다.
이 채택은 config 변경, report finalization, pod 실행, exact SHA 또는 seal 승인이 아니다.

## 5. Local implementation increment — 2026-09-11

Owner의 “커밋하고 다음으로 넘어가자”에 따라
[diagnostic kernel 계약](../plans/2026-09-11-compose-r1-diagnostic-kernel.md)을 작성하고
[strict 개발용 모듈](../../../src/alive/compose/log_sampling_report.py)과
[negative/known-answer tests](../../../tests/alive/compose/test_log_sampling_report.py)를 추가했다.
별도 `compose_gears_log_sampling_diagnostic_v1` schema로 한 pair × training seed의 arithmetic,
exact N, ordered-input digest와 외부 expected registration을 결속한다.

이 schema는 항상 `UNVERIFIED` / `NOT_ADMISSIBLE`이며 성공해도 structural/runtime 증명이 아니다.
Scientific `compose_gears_log_sampling_report_v1`, multi-pair/seed 통합, attestations, actual sampler
검증, numeric/budget 정책과 consumer/admission wiring은 구현되지 않았다. Raw bias validator나
finalizer를 수정하지 않았으므로 개발용 report는 기존 scientific 경로에서 거부된다.
