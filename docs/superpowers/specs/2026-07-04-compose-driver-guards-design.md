# COMPOSE Driver Guards — scientific-boundary wiring (as-built) Design

> **문서 역할:** dev-stage 설계 계약 (scientific claim contract 아님)
> **개정일:** 2026-07-04
> **상태:** IMPLEMENTED/MERGED as-built guard design. Protocol은 ACTIVE / RELEASE-BLOCKED / seal UNOPENED.
> **상위 protocol:** `COMPOSE-K562-v1` (ACTIVE, 2026-06-30 lifecycle activation)
> **상위 runbook:** `docs/superpowers/specs/2026-07-01-compose-deep-baselines-design.md` (Changes A/B/C — 전부 완료)
> **거버넌스:** `CLAUDE.md`#invariants, #seal, #data-eval, #provenance, #agent
> **선행:** deep-baselines A(=A1 fit-role + A2 payload-v2), B+C(provenance/ledger) 모두 merged. 실제 sealed
> run은 current release gate와 owner-approved exact SHA가 추가로 필요하다.

---

## 0. 목적과 범위

deep-baselines runbook(Changes A/B/C)이 로컬에서 완결된 뒤, **실제 sealed run이 통과해야 하는
누수·activation 경계 배선**을 dev-stage에서 마저 닫는다. 이 문서는 그 배선을 **as-built**로
기록한다 — 코드는 이미 구현·검증되어 있고(전 스위트 green), 본 문서는 계약과 불변식을 명문화한다.

이 서브프로젝트는 새 이름을 갖는다("Driver Guards"). runbook의 "Change C"(persisted-ledger
post-access consistency, 이미 완료)와는 **다른 것**이므로 letter를 재사용하지 않는다.

### In scope (as-built, 완료)
- 응답공간 사영 operator의 **execution-identity 바인딩**을 sealed bundle까지 전파(§1).
- Phase-2a orchestrator에서 subprocess backend의 **run/config 정합성 검증**(§2).
- Subprocess payload의 **불변 스냅샷**과 approved-root **절대경로 강제**(§3).
- Baseline representation을 lock→worker로 **명시 전달**하고 controller가 대조(§4).
- pseudobulk-approx representation의 **scientific-mode fail-closed 가드**(§5).
- **fit-role `singles` universe 멤버십 가드**로 sealed-combo-as-single 누수 차단(§6).

### Out of scope (driver/pod 잔여)
- `ExecutionIdentityLock`을 committed config에서 조립하는 **driver assembler**(§2.4). 본 문서는
  그 lock을 caller가 공급받아 **검증**하는 쪽만 완결한다.
- 실제 GEARS/CPA worker·GO-graph·mini fixture·sealed run — pod runbook 소관.
- token 어휘(`control_token`/`combo_sep`)를 payload/data-card로 실어 worker가 소비하는 것.
  본 문서의 §6 universe 가드는 이 어휘 정확성과 **무관하게** 누수를 닫으므로 이는 편의 개선이다.
- pseudobulk 가드를 1급 activation-requirement(evidence-file-backed)로 승격(§5의 한계).

### 거버넌스
dev-stage 배선이다. **seal은 열지 않는다.** backend는 fit-role 데이터만 받고 sealed outcome에
접근하지 않는다. 로컬 stub·단위 테스트는 실제 Norman·실제 seal을 만지지 않는다. **게이트 PASS는
과학 verdict가 아니다.**

---

## 1. Change 1 — model-artifact checksum 바인딩 (`freeze.py`)

`FrozenPredictionBundle`이 per-method **fitted-model / adapter-execution checksum roster**
(`model_artifact_checksums`)를 실어, 집계 `model_checksum`을 그 roster + 선택된 hyperparameter에서
재유도(`_validate_model_artifact_binding`)한다.

- roster 키 = `set(method_roster) − NON_ARTIFACT_METHODS`, 여기서
  `NON_ARTIFACT_METHODS = {additive, no_change, perturbation_mean}` (analytic baseline; 적합 산출물
  없음). 나머지 6개(`l1/l2/l3, id_only, gears, cpa`)는 각각 fitted checksum 또는 adapter provenance
  digest를 갖는다.
- 각 값은 **정확히 64 lowercase hex**로 강제된다 — raw sealed 토큰이 이 필드에 숨을 수 없다(그
  자체가 누수 가드).
- 집계 공식: `sha256_json({"schema": "compose_model_set_v1", "methods": <정렬 snapshot>,
  "selected_k_total": int, "selected_lambda": float.hex()})`. `sha256_json`이 `sort_keys=True`
  (`provenance.py`)이므로 orchestrator의 삽입순서 dict와 validator의 정렬 snapshot이 바이트 동일.
- create·verify·roundtrip 3중 검사. adapter digest = `sha256_json(provenance_manifest)` — 검증된
  execution manifest를 포함하므로, subprocess worker 신원이 `model_checksum → bundle_checksum`으로
  전파된다.

**불변식:** per-method 산출물 digest 또는 집계 checksum 변조는 `FreezeError`로 즉시 실패한다.

---

## 2. Change 2 — Phase-2a subprocess 런타임 바인딩 (`phase2a.py`)

`_validate_adapter_runtime_bindings`가 freeze 전에 모든 subprocess backend를 활성 run/config에
대조한다.

- `backend.expected_response_artifact_sha256 == inputs.response_space_checksum` (run 권위값).
- `backend.execution_identity_lock.prediction_representation ==
  config.baseline_representations[name]`.
- 불일치 → `ScientificModeError` fail-closed. `adapters` 키는 `config.baseline_representations`
  키(=gears/cpa)의 부분집합이며, lock/response 속성이 없는 객체는 `None` 비교로 즉시 거부된다.

### 2.4 driver 잔여 (out of scope)
lock은 여전히 **caller가 공급**한다. prod에서는 driver가 committed config로부터
`ExecutionIdentityLock`을 조립해야 하며, 그 assembler는 pod/driver 단계 소관이다. 본 §2는 조립된
lock이 run/config와 **정합함을 강제**하는 안전망을 완결한다(더 중요한 절반).

**비순환성:** payload는 configure 시 `expected_response_artifact_sha256`에 검증되고, 이 값이
`inputs.response_space_checksum`(expected_hashes로 바인딩되는 run 권위값)과 같아야 하므로
`payload → backend → inputs` 사슬이 self-consistent가 아니라 독립 권위값에 묶인다.

---

## 3. Change 3 — payload 스냅샷 + approved-root (`baseline_subprocess.py`)

- `configure_payload`가 `json.loads(_canonical_json(candidate))`로 **detached deep snapshot**을
  만들고 재검증한 뒤 저장한다. 얕은 `dict()`는 중첩 블록 alias를 남겨 검증 후 변조(TOCTOU)를 허용
  하므로 제거. reconfigure 시 stale `_last_execution_manifest`를 리셋한다.
- `predict`가 **공급된** `approved_artifacts_root`에 `os.path.isabs`를 강제한다(realpath 결과는 항상
  절대경로라 기존 검사는 무의미했음). 비-str/상대경로 → `PayloadError`.

---

## 4. Change 4 — representation 전달·대조 (`baseline_subprocess.py` + `stub_worker.py`)

- backend가 worker를 `--prediction-representation <lock.prediction_representation>`로 호출한다
  (신뢰된 lock에서). worker는 그 값으로 예측하고 manifest에 echo하며, controller의
  `_verify_execution_manifest`가 manifest ↔ lock을 대조한다.
- stub worker는 `raw_pseudobulk_approximation`이면 native를 count-space에서 선평균(pseudobulk) 후
  사영하고, `cell_raw_counts`면 per-cell 사영한다. `apply_response_projection`은 두 representation을
  내부적으로 동일 처리하므로(정규화/log1p/HVG/center/project), **pseudobulk vs cell 구분은 worker의
  선집계에 있다**. stub(신뢰)엔 정확하며, **실제 pod worker가 이 의미를 강제**해야 한다(pod 잔여).

config→lock→arg→manifest echo→controller 대조로 representation 루프가 orchestrator에서 닫힌다.

---

## 5. Change 5 — pseudobulk activation 가드 (`config2.py`)

`assert_scientific_mode_allowed`가 모든 ActivationRecord evidence 검사 뒤에, config의
`pseudobulk_representation_activation_blocked`가 True면 `ScientificModeError`로 fail-closed한다.

- 자연 조건부: `raw_pseudobulk_approximation` baseline이 `approximation_bias_report_sha256: null`일
  때만 True. 현재 config(gears=pseudobulk-approx, bias null)는 **차단**된다 — 근사 오차가 미측정이므로
  올바른 상태다. config에 실제 bias-report SHA를 커밋하면 해제된다.
- fixture 모드와 활성화 evidence 경로는 영향 없음(scientific-mode 경로에서만 평가).

**알려진 한계(spec 명시):** 이 가드는 config 필드 non-null만 확인하고 bias 파일의 실재/일치는
검증하지 않는다. 더 강한 형태 — bias 리포트를 1급 activation-requirement로 등록해 ActivationRecord가
파일-바이트 해시로 검증 — 는 후속 업그레이드로 이관한다.

---

## 6. Change 6 — fit-role `singles` universe 가드 (`fit_role.py`, Unit 1) 🔴 누수 픽스

**취약점(재현·확인).** `_required_role_for_token`은 `combo_sep`이 토큰에 없으면 `singles`를 반환한다.
control+singles-only fit-role 아티팩트(응답공간 사영은 `fit_roles=[control, singles]`로 적합 —
combo 없음)에서, sealed combo `GENEA+GENEB`가 잘못된/누락된 `combo_sep`(`_`)로 인해 `singles`로
오분류되면 sealed-membership 검사가 건너뛰어지고 `role_counts`도 (combo_calibration=0) 정합하여
**조용히 통과**한다 — sealed outcome cell이 fit set에 유입.

**픽스.** `validate_fit_role_artifact`에 **필수** `single_gene_ids`(governed single-gene universe)를
추가하고, `singles`로 분류된 모든 토큰이 그 universe의 원소임을 강제한다. `GENEA+GENEB`는 등록된
single-gene id가 아니므로 **separator 정확성과 무관하게** 거부된다. 이 universe는 이미
governed·validated된 payload 입력이다(`baseline_subprocess`: 모든 pair 유전자는 `single_gene_ids`에
존재해야 함). 따라서 pair 유전자 ⊆ universe이고 `singles` 토큰 ⊆ universe다.

- `control_token`/`combo_sep` 기본값은 유지하되 **이제 위험하지 않다**: 틀린 separator면 legit
  combo조차 non-member 토큰이 되어 fail-closed된다.
- data-card는 token 어휘 필드를 갖지 않고 그 파일은 activation-evidence이므로(재해싱은 무거운 거버넌스
  작업), 어휘를 data-card에서 조달하는 대신 **universe 멤버십**으로 닫는다 — 더 견고하다.

**재현 증거.** 로컬 스크립트로 픽스 전 아티팩트가 `AAA+BBB`(sealed cell)를 `singles`로 통과시킴을
확인했고, 픽스 후 `token 'AAA+BBB' classified 'singles' is not a registered single-gene id`로
거부됨을 확인했다. 영구 회귀 테스트로 인코딩.

---

## 7. 테스트 (전부 로컬 실행 가능, `CLAUDE.md`#verify)

- **freeze:** create/verify/roundtrip에서 model-artifact 바인딩; 집계·per-method digest 변조 거부.
- **phase2a:** subprocess가 freeze로 배선; response-space 발산·representation 발산 거부(2 신규 음성).
- **baseline_subprocess:** payload 스냅샷 detach; 상대경로 approved-root 거부.
- **config2:** 현재 canonical config는 pseudobulk 미측정으로 차단; bias SHA 커밋 시 통과.
- **fit_role:** happy-path; **sealed-combo-as-single 누수 회귀**; universe 밖 singles 거부;
  빈/중복 universe 거부.
- **integration:** stub_worker end-to-end operator 경로.
- fixture 정합: singles-cell 토큰을 governed universe에서 조달(3 fixture 정정 — 이전 `S{i}`는
  domain-unfaithful이었고 새 가드가 이를 노출).

전 스위트 green(repo 1386 passed / 1 skipped, compose 702, leakage/fail-closed 95) + ruff clean.

---

## 8. 보존되는 거버넌스 불변식

- backend는 fit-role 데이터만 본다(sealed 경로 없음). §6 universe 가드는 sealed cell 유입을 차단.
- freeze 시 두 leakage wall(`_assert_no_sealed_reference`, `_assert_no_outcome_reference`) 유지;
  model_artifact_checksums는 64-hex 강제로 추가 방어.
- run identity/immutability(§11): model_checksum이 per-method 산출물·hyperparameter를 바인딩.
- seal은 열리지 않음; 게이트 PASS ≠ 과학 verdict.

## 9. 완료 정의
- §1–§6 코드가 로컬에서 구현·검증되고 §7 테스트가 전부 green이다. ✅
- driver/pod 잔여(§2.4 assembler, 실제 worker, 어휘 payload화, §5 승격)는 pod runbook/후속으로
  명시 이관된다.

## 참고
- 상위 runbook: `2026-07-01-compose-deep-baselines-design.md` §1–§3.
- 상위 계약: COMPOSE spec `2026-06-22-compose-epistasis-operator-design.md` §10.4–§10.6.
- 거버넌스: `CLAUDE.md`#invariants, #seal, #data-eval, #provenance, #agent.
