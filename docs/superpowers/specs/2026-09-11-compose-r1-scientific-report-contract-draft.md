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

Verifier receipt의 PASS는 report의 기록·판정을 정확히 검증했다는 뜻이다. Report의 ELIGIBLE과 다르며,
어느 것도 activation, release READY, exact-SHA 승인 또는 seal 승인이 아니다.
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

## 7. Nested schema 구체화 제안 — 2026-09-11

§2–6의 미결 항목에 대한 후속 제안이다. **DRAFT / NOT EFFECTIVE**를 유지한다.
아래 `{a, b}` 표기는 정확한 object key 집합, `T[]`는 ordered array다.
`SHA`는 실제 artifact bytes의 lowercase 64-hex digest, `N`은 bool이 아닌 nonnegative integer다.
ID는 nonempty unpadded string이며 normalize/alias/trim하지 않고 외부 roster와 정확히 비교한다.
등록 n/p/m은 양수다. Digest가 형식에 맞는 것과 외부 pin에 일치하는 것은 별도 검사다.

### 7.1 Identity와 registration

Report `identity`의 정확한 key 집합을 다음으로 제안한다.

`{basis_config_sha256, producer_git_commit, measurement_contract_sha256, runtime_sha256,
worker_sha256, package_lock_sha256, resource_manifest_sha256, response_sha256, roster_sha256}`

`producer_git_commit`은 저장소가 사용하는 full commit ID이며 나머지는 SHA다.
Checkpoint는 seed별 model binding에 한 번만 정의하고 모든 condition에서 같은 binding을 참조한다.
Runtime/resource manifest는 image·device·precision·external resource identity를 bytes로 고정하며
그 내부 schema는 별도 versioned 계약이 필요하다. 이름만 보고 임의 JSON을 허용하지 않는다.

| Record | 정확한 key 집합과 제약 |
|---|---|
| Single condition | `{kind, gene_id}`; kind=`single`, gene_id는 registered singles member |
| Combo condition | `{kind, gene_ids}`; kind=`combo`, 두 distinct ID는 UTF-8 byte order이며 registered calibration pair |
| Unit identity | `{condition, role, training_seed}`; single↔`singles`, combo↔`combo_calibration`; seed는 등록 N |
| Control row | `{row_id, source_cell_id}`; row_id는 unique, source_cell_id는 외부 source identity |
| Seed model binding | `{training_seed, checkpoint_sha256, frozen_state_sha256}`; seed별 정확히 하나 |
| Registered unit | `{unit, public_schedule}`; unit.training_seed로 Seed model binding 참조 |
| Public schedule entry | `{repeat_index, sampling_seed, initial_rng_state_sha256, call_order}`; index/order는 등록 N |

위 condition은 report의 새 표현 제안이지 기존 worker payload 변경이 아니다.
[Fit-role 검증](../../../src/alive/compose/fit_role.py)은 single roster membership을 separator parsing보다
먼저 확인하며 combo는 canonical pair를 요구한다. [GEARS worker](../../../scripts/baselines/gears_worker.py)의
backend condition naming은 별개다. Producer가 두 표현의 명시적 bijection을 검증해야 하며,
single에 가짜 두 번째 gene/control token을 넣어 diagnostic pair validator를 통과시키지 않는다.

Registration의 정확한 top-level key 후보:

`{schema, protocol, identity, models, units, controls, response_dim, draw_count, fit_counts_sha256,
control_policy_sha256, numeric_policy_sha256, public_policy_sha256, verifier_contract_sha256,
parent_negative_evidence_sha256, self_checksum}`

Schema는 `compose_gears_log_sampling_registration_v1`, protocol은 COMPOSE literal이다.
`units`는 Registered unit[], `controls`는 Control row[]다. Unit identity 중복과 빈 roster는 거부한다.
`models`는 Seed model binding[]이며 seed 집합은 units의 seed 집합과 정확히 같다.
중복·미참조·누락 binding을 거부한다. 같은 seed의 모든 condition/reference/public 호출은 같은
checkpoint와 frozen model state를 사용했음을 actual runtime evidence로 확인한다.
Sampling RNG state는 이 model binding과 분리한다. Condition별 checkpoint 선택이나 재학습은 금지한다.
`public_schedule`은 사전 zero-budget이면 빈 array다. RNG state encoding/seed domain은 pinned runtime
계약으로 제한하고 서로 다른 seed 숫자만으로 독립성을 인정하지 않는다.
각 policy SHA는 외부에서 승인·고정한 versioned artifact를 요구한다. Null/unknown schema는 실행 불가다.
Fit counts artifact는 condition별 optimizer/validation/reference 행 수를 구분하고 actual fit 증거와 대조한다.
중복 source_cell_id가 있으면 등록 multiplicity를 유지한다. Uniform sampling은 control row index에 대한
것이다. 임의 weight/nonuniform sampler에는 현재 V 식을 적용하지 않는다.

### 7.2 Unit 결과와 실패 보존

모든 unit record의 공통 key는 `{unit, status, evidence_ids, progress}`다.
`evidence_ids`는 manifest entry ID[]다. Progress는 실패·미실행에도 필수다.

| status | 공통 key에 추가되는 정확한 key | 의미 |
|---|---|---|
| `COMPLETE` | `{exact_n, analytic, public}` | 등록된 측정 모두 완료; 구조 검증 PASS라는 뜻 아님 |
| `FAILED` | `{failure}` | 계약 위반 또는 실행 오류; partial output은 evidence로 보존 |
| `NOT_EXECUTED` | `{failure}` | 선행 실패로 미실행; roster에서 제거하지 않음 |

`exact_n = {control_rows, unique_controls, response_dim, draw_count, requested_repeats, completed_repeats}`.
모든 count를 외부 registration과 manifest에서 재계산한다. COMPLETE에서는 요청/완료 반복이 같아야 한다.
`progress = {requested_control_rows, completed_control_rows, requested_repeats,
attempted_repeats, completed_repeats}`다. Requested 값은 registration에서 구하고,
Requested 값은 N이며 관측 count는 `{status: KNOWN, value: N}` 또는
`{status: UNKNOWN, reason_codes: ID[]}`로 표현한다.
KNOWN은 durable row/repeat ledger로 검증한 count다. Row ID와 repeat_index를 등록 roster/schedule에
대조하며 중복 완료를 별개 수행으로 세지 않고 계약 위반으로 거부한다. UNKNOWN은 미실행 0이 아니라 crash 등으로
정확한 횟수를 증명할 수 없음을 뜻하며 eligibility를 차단한다. Unknown reason_codes는 비어 있지 않은
등록 code 집합이고 관련 evidence를 unit.evidence_ids에 남긴다. Known 값끼리는
`completed_control_rows <= requested_control_rows`, `completed_repeats <= attempted_repeats <= requested_repeats`다.
COMPLETE는 모든 count KNOWN, control 완료=요청, 반복 시도=완료=요청이며 exact_n과 일치해야 한다.
NOT_EXECUTED는 시작하지 않았다는 durable 증거와 모든 관측 count KNOWN 0을 요구한다.
시작 여부를 알 수 없으면 FAILED/UNKNOWN으로 남긴다. 자동 재시도는 허용하지 않는다.
`analytic = {reference_mean, centered_squared_sum, V, B}`이며 mean 길이는 p, scalar는 finite/nonnegative다.
`public = {status, repeats}`; repeats는 아래 Completed repeat[]이며 등록 순서를 그대로 따른다.
`Completed repeat = {repeat_index, output_entry_id, rng_trace_entry_id, squared_discrepancy}`.
Status는 `WITHIN_PRECISION | DISCREPANCY | INCONCLUSIVE | NOT_RUN_BUDGET` 중 하나다.
Finite/nonnegative discrepancy를 모두 재계산하며 clipping하지 않는다.
`failure = {stage, reason_codes, evidence_ids}`; stage는
`INPUT | PROJECTION | RUNTIME | ANALYTIC | PUBLIC | UPSTREAM` 후보 enum이다.
NOT_EXECUTED의 stage는 UPSTREAM이고 선행 실패 evidence를 참조한다. 실패를 zero-valued analytic으로 채우지 않는다.

`disposition = {validity, public_status, eligibility, reason_codes}`를 제안한다.
Validity 후보는 `VALID_CONDITIONAL | INVALID | UNVERIFIED`, eligibility는 `ELIGIBLE | BLOCKED`다.
전체 public_status는 위 네 상태와 `INCOMPLETE`를 허용한다. 미완료 unit가 하나라도 있으면 INCOMPLETE이며
eligibility는 BLOCKED다. 그 외에는 DISCREPANCY가 우선, 모두 0회면 NOT_RUN_BUDGET,
모든 unit가 WITHIN_PRECISION이면 그 상태, 나머지는 INCONCLUSIVE다.
여러 이유를 모두 보존하고 sorted unique reason_codes를 요구한다. ELIGIBLE에도 미결/예산 제한 설명은 남긴다.

Reason-code 후보 registry는 `IDENTITY_MISMATCH`, `ROLE_VIOLATION`, `EVIDENCE_MISSING`,
`EVIDENCE_HASH_MISMATCH`, `ROSTER_COVERAGE_MISMATCH`, `PROJECTION_MISMATCH`,
`RUNTIME_CONTRACT_MISMATCH`, `NUMERIC_UNREPRESENTABLE`, `MEASUREMENT_INCOMPLETE`,
`PUBLIC_DISCREPANCY`, `PUBLIC_INCONCLUSIVE`, `PUBLIC_NOT_RUN_BUDGET`, `VERIFICATION_PENDING`이다.
원인 발생 stage·외부 증거와 함께 기록한다. `PUBLIC_INCONCLUSIVE`와 `PUBLIC_NOT_RUN_BUDGET`을
제외한 위 코드는 eligibility를 차단한다. ELIGIBLE은 모든 unit COMPLETE, validity VALID_CONDITIONAL,
필수 identity/role/runtime/analytic 검증 충족, public DISCREPANCY 부재가 모두 확인된 경우에만 가능하다.
Validity는 증명된 계약 위반이 있으면 INVALID, 위반은 아직 없으나 필수 증거가 미충족이면 UNVERIFIED,
모든 필수 가정이 충족되면 VALID_CONDITIONAL이다. Public 보조 상태로 필수 검증을 생략하지 못한다.
Wire/schema 자체가 손상되면 이 report를 억지로 생성하지 않고 별도 durable verifier failure를 남긴다.

## 8. Evidence manifest·resolver·receipt 제안

Manifest schema는 `compose_gears_log_sampling_evidence_v1`, 정확한 key 후보는
`{schema, protocol, registration_sha256, entries, self_checksum}`다.
Entry는 `{entry_id, kind, sha256, byte_length, media_type, scope}`이며 entry_id는 unique ID,
byte_length는 N이다. Scope는 `{kind: global}` 또는 `{kind: unit, unit: Unit identity}`의 tagged object다.
Kind 후보는 `CONTROL_OUTPUTS | PUBLIC_OUTPUT | RNG_TRACE | RUNTIME_TRACE | PROJECTION_TRACE |
ROLE_READ_AUDIT | FIT_COUNTS | FAILURE_TRACE`다. Content schema·encoding은 kind별 계약에 고정한다.
Opaque blob을 선언만으로 증거로 인정하지 않는다. Output의 row order·shape·dtype·unit·repeat binding을
검증하며 entry 참조의 dangling/duplicate assignment/wrong scope를 거부한다.

Manifest에는 file path·URL이 없다. Resolver는 외부 allowlist로 entry_id를 immutable source에 매핑한다.
총 byte/entry/decompressed-size 상한과 각 format의 bounded decoder를 사전 설정한다. 상한 초과는
실패이며 silent truncation하지 않는다. Content-addressed 이름도 실제 bytes 검증을 대신하지 않는다.
Hash와 decode가 동일 snapshot을 소비해야 한다. Descriptor pinning만으로 in-place mutation을 막는다고
주장하지 않는다. 기존 [preseal read 계약](../../../src/alive/compose/driver/preseal_read.py)의 제한처럼
immutable runtime/custody 전제가 필요하다. Existing guard는 변경하지 않는다.

생성 순서는 registration → raw evidence/measurement manifest → report → final verifier receipt다.
Manifest는 report나 final receipt hash를 포함하지 않고 report도 final receipt hash를 포함하지 않는다.
이 순서로 report/receipt 상호 해시 순환을 피한다. Runtime trace는 report 전 증거, final receipt는
report까지 재검증한 후 증거로 구분한다.

Receipt schema 후보는 `compose_gears_log_sampling_verification_v1`, 정확한 key 후보는
`{schema, protocol, registration_sha256, evidence_manifest_sha256, report_sha256,
verifier_contract_sha256, verifier_code_sha256, verifier_image_digest, verifier_lock_sha256,
status, checks, reason_codes, self_checksum}`다. Image digest는 `sha256:` + SHA다.
Status는 `PASS | FAIL | INCOMPLETE`; check는 `{check_id, status, evidence_ids, reason_codes}`다.
Required check IDs는 `IDENTITY, ROLE, COVERAGE, PROJECTION, RUNTIME, ANALYTIC, PUBLIC`로 제안한다.
모든 check의 status는 해당 영역의 기록·판정 정확성에 대한 것이다. 증거로 확인된 실패를
report가 올바르게 기록했으면 그 check는 PASS일 수 있다. 판정이 증거와 다르면 FAIL,
판정 정확성을 확인할 증거가 부족하면 INCOMPLETE다. PUBLIC의 PASS는 WITHIN_PRECISION 달성 뜻이 아니다.
Consumer는 외부 verifier pin과 actual bytes를 확인하고 모든 필수 check·reason을 재검증한다.
Receipt의 PASS만으로 report eligibility를 ELIGIBLE로 덮어쓰지 않는다.

Receipt status는 필수 check 중 FAIL이 있으면 FAIL, 없고 INCOMPLETE가 있으면 INCOMPLETE,
모두 PASS이면 PASS다. Check ID는 정확한 필수 집합이며 중복·추가·누락을 거부한다.
FAIL/INCOMPLETE receipt도 write-once evidence로 보존한다. 구조적으로 유효한 BLOCKED report를
정확하게 검증한 receipt가 PASS일 수 있으므로 소비자는 두 status를 반드시 따로 확인한다.

## 9. 이번 단계의 결론

Nested key·tagged identity·failure coverage·manifest/receipt의 단방향 구조를 구체화했다.
Policy/resource/runtime artifact와 kind별 content schema, numeric/zero-V/budget 수치, custody/runtime
증명 및 consumer 채택은 여전히 미결이다. 이번 문서는 실행용 registration이나 evidence가 아니다.
다음 구현은 이 제안에 대한 계약 검토 후 synthetic-only strict encoding/coverage validator부터 진행한다.
허위 runtime receipt나 미결 policy default를 만들지 않는다.

## 10. 계약 검토 후 정정 — 2026-09-11

이번 검토는 문서의 의미·정합성 검토이며 executable validator나 runtime proof가 아니다.

- Receipt PASS와 report ELIGIBLE을 분리하고 모든 receipt check에 같은 의미를 적용했다.
- Seed별 model binding으로 condition별 checkpoint 대체를 차단하는 계약을 명시했다.
- 실패/미실행에도 structured progress를 요구하고 UNKNOWN과 실제 0을 분리했다.

정정 후 다음 반례를 문서 기준으로 재검토했다: 정확하게 기록한 실패의 PASS/BLOCKED 조합,
잘못 선언한 ELIGIBLE의 거부, 동일 seed의 서로 다른 condition checkpoint, 중복/누락 model binding,
반복 중 crash의 UNKNOWN, 미시작 증거 없는 NOT_EXECUTED, 중복 완료 ledger, 사전 zero-budget의 COMPLETE.
이 범위에서 추가적인 blocking 모순은 발견하지 못했다. Numeric/runtime/content schema 및 consumer의
미결사항은 해소되지 않았으며 실행 가능성이나 독립 review 완료를 주장하지 않는다.
