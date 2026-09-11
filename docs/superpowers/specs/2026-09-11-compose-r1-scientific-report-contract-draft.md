# R1 scientific report — schema 및 verifier 계약 초안

> **DRAFT / NOT EFFECTIVE — 2026-09-11.** Local diagnostic 다음 설계 단계다.
> COMPOSE-K562-v1 ACTIVE / RELEASE-BLOCKED / seal UNOPENED.
> [채택된 검증 역할](2026-07-13-compose-approximation-bias-metric-design.md#10-r1-verification-role-policy--owner-adoption-2026-09-11)을 구체화하는 제안이며
> 새 schema의 채택·scientific admission·config 변경·pod 실행 승인이 아니다.

## 1. 목적과 비목표

Frozen model과 등록된 finite control pool에 조건부인 sampling MSE를 재계산하고,
그 계산의 representation·sampler 가정이 독립적인 증거로 뒷받침되는지 확인한다.
V는 prediction error, biological noise, GI signal, population generalization CI가 아니다.
[측정식과 한계](2026-09-11-compose-r1-report-measurement-proposal.md)는 유지한다.

기존 `compose_gears_log_sampling_diagnostic_v1`은 계속 개발용이다. 필드 추가나 status 변경으로
scientific report로 변환하지 않는다. 기존 raw v4 validator/finalizer도 이 초안으로 변경하지 않는다.

## 2. 제안 wire envelope

Schema identifier는 `compose_gears_log_sampling_report_v1`이다. 아래 top-level key는 정확히 이 집합으로
제안한다. Nested contract가 완성되기 전에는 실행 가능한 strict schema가 아니다.

| Key | 제안 type / 의미 |
|---|---|
| `schema` | 위 literal string |
| `protocol` | `COMPOSE-K562-v1` literal |
| `method` | `log_normalized_pseudobulk` literal |
| `identity` | basis config, producer commit, measurement contract, runtime/worker/package/resource/response/roster의 외부 pin |
| `registration_sha256` | 측정 전에 고정한 registration bytes의 lowercase SHA-256 |
| `evidence_manifest_sha256` | 외부 immutable measurement evidence manifest bytes의 SHA-256 |
| `units` | 등록된 pair × training seed 순서의 record array; 누락·중복·추가 금지 |
| `disposition` | 전체 validity/public corroboration/eligibility와 reason codes; verifier가 재계산 |
| `self_checksum` | 이 key를 제외한 canonical payload의 SHA-256; authenticity가 아님 |

JSON object는 모든 깊이에서 duplicate/unknown/missing key를 거부한다. Bool을 integer로,
numeric string을 number로 허용하지 않는다. Nonfinite와 underflow-to-zero는 거부한다.
Unavailable 값을 0으로 대체하지 않는다. Complete unit와 failed unit는 명시적 tagged union으로
분리하고, failed unit에도 identity·실패 stage·증거 참조를 보존한다. 실패 뒤에 analytic 값을 꾸미지 않는다.

Canonicalization 후보는 diagnostic과 같은 ASCII-escaped, sorted-key, compact JSON이다.
최종 scientific encoding의 float·signed-zero·큰 integer·cross-runtime 재현성은 golden-byte fixture로
고정해야 한다. Raw evidence file SHA는 canonical payload checksum과 구분해 실제 저장 bytes를 해시한다.
Scientific numerical equivalence는 JSON byte equality와 다른 계약이며 numeric policy 없이 추정하지 않는다.

## 3. Unit·registration·exact N

Unit identity는 외부 registration의 pair identity/orientation, non-sealed role, training seed다.
Singles의 identity encoding을 포함한 pair roster 규칙은 authoritative roster와 일치해야 한다.
Diagnostic의 두 distinct-string 표현을 scientific singles에 자동 승계하지 않는다.
Checkpoint는 seed별 실제 frozen model bytes 및 buffer/eval 상태 증거에 결속한다.

Registration은 ordered pair/seed/control roster, p, production m, response mapping, transformation,
numeric policy, requested public repeats와 전체 seed/state/호출 순서, budget policy, verifier/code pins를
실행 전에 고정한다. 임의 tolerance·alpha·eta·반복 수 default는 없다.
측정 control row 수와 unique control identity 수, optimizer/validation/reference 행 수를 구분한다.
의도된 중복 control의 의미·가중치는 등록되어야 하며 조용한 deduplication은 금지한다.
Reported units는 등록 roster를 정확히 덮어야 한다. 실패·미완료 unit도 빠뜨리지 않는다.

Complete unit는 n, p, m, mu, centered squared sum, V, B 및 모든 public repeat의 squared discrepancy를
담는다. Requested/completed repeats와 raw-output digest를 각각 기록한다.
계획된 0회는 `NOT_RUN_BUDGET` 후보이고, 요청된 반복의 crash/누락은 예산상 생략으로 재분류하지 않는다.
미완료 반복의 partial evidence와 실패를 보존하고 eligibility를 보류한다.
단순 pair×seed 평균을 biological 효과나 독립 표본의 CI로 보고하지 않는다.

## 4. Verifier 순서와 신뢰 경계

1. Caller가 report 밖에서 expected registration/contract/code/runtime pins를 제공한다.
   Report가 지정한 임의 URL/path를 검증 근거로 자동 fetch/open하지 않는다.
2. 별도로 승인된 resolver가 pinned manifest 및 bounded raw evidence bytes를 제공한다.
   Manifest의 각 digest를 실제 bytes와 비교한다. Checksum 일치만으로 role·runtime 적법성을 인정하지 않는다.
3. Registration·identity·unit coverage·exact N을 비교한다. Source/read audit가 등록된 non-sealed role만
   사용했는지 검사한다. Verifier 자체도 sealed source를 열거나 materialize하지 않는다.
4. Input scale·full→subset mapping·signed affine projection을 검증한다. Missing HVG zero-fill,
   double-log, clipping, wrong order를 거부한다. 동일 p와 frozen response basis를 사용한다.
5. 별도의 pinned runtime evidence에서 frozen state, batch invariance, uniform IID replacement,
   m, RNG separation, fresh state/cache isolation, observer non-interference를 확인한다.
   Source inspection이나 scalar `VERIFIED` 선언만으로 이 단계를 대체하지 않는다.
6. 전체 등록 control 출력에서 bounded reduction으로 mu/V/B와 모든 discrepancy를 재계산한다.
   Reduction order·dtype·error bound는 사전 numeric contract를 따른다. Threshold를 관측 오차에 맞추지 않는다.
7. Public corroboration과 전체 eligibility를 재계산한다. Declaration과 계산 결과가 다르면 거부한다.
   Unknown schema/version/reason code, 누락 pin, 변조 evidence는 fail-closed다.

Conditional V의 scientific 해석은 3–6의 가정 검증 뒤에만 가능하다. Public moment의 정합성만으로
sampler 전체 분포의 equivalence를 입증하지 않는다.

## 5. 처분과 consumer 경계

Validity, public corroboration, admission eligibility는 별도 축이다.
필수 증거 불충족·계약 위반·미완료 측정은 eligibility를 차단한다.
`INCONCLUSIVE`/사전 예산상 `NOT_RUN_BUDGET`은 구조적 성공도 실패도 대신하지 않는다.
`DISCREPANCY`는 원인 규명 전 eligibility를 보류하며 큰 유효 V만으로 comparator를 제거하지 않는다.
Zero-V·numeric allowance·public interval 판정은 별도 승인 전 실행하지 않는다.

Verifier 성공은 이 report의 적격성이지 activation, release READY, exact-SHA 승인 또는 seal 승인이 아니다.
Consumer 연결은 별도 구현·승인이다. 기존 raw representation guard를 log에 재사용하거나 완화하지 않는다.
Basis config와 code/spec commit C → 외부 report → report-SHA leaf만 채운 derived config → activation
순서를 유지한다. Report가 자신을 포함하는 final config digest에 결속되는 순환 구조는 금지한다.
과거 failed Probe-A는 parent negative evidence로 보존하고 이 결과로 덮어쓰지 않는다.

## 6. 구현 gate와 검증 목록

다음은 아직 필요한 계약이지 완료 주장이나 임의 구현 허가가 아니다.

- Nested key/type/tagged-union 및 reason-code registry, authoritative singles/pair encoding.
- External evidence manifest/resolver의 custody·bounded-read 계약과 verifier receipt schema.
- Numeric error policy·zero-V·alpha/eta·budget·repeat allocation과 runtime 증명 방법.
- 새 schema/consumer 채택 및 exact basis-config leaf 연결 계약.

계약 확정 후 schema/negative validator → bounded accumulator → runtime verifier → consumer 순으로 구현한다.
Tests는 fresh-checksum tamper, wrong/missing external pin, complete/failed unit coverage, false role,
same-seed/cache reuse, batch/state mutation, mapping/precision 오류, missing repeat, forged eligibility,
raw/log representation mismatch와 one-way lineage를 포함한다. Guard mock 없이 capture-and-assert하며,
mutation kill은 named test의 own-frame AssertionError로 확인한다. 이 목록은 미실행 계획이다.
