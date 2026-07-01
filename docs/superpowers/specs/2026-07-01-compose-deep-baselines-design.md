# COMPOSE Deep-Baseline Backends + Phase-2b Activation Bindings — Implementation Design

> **문서 역할:** activation-time **구현 설계**. 새 과학 주장이 아니다.
> **상태:** DRAFT (rev 2, spec-review iteration 1 반영) — owner 검토 대기.
> **개정일:** 2026-07-01
> **상위 계약:** `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md`(이하 "상위 spec")의 §10.5 comparator family, §10.6 seal-once, §7 immutability. 본 문서는 그 계약의 미완 실행 배선을 정의할 뿐, claim·metric·verdict 정의를 바꾸지 않는다.
> **거버넌스 앵커:** immutability·write-once는 `CLAUDE.md` §11, seal은 `CLAUDE.md` §6, baseline governance는 `CLAUDE.md` §9, fit-role/seal 불변식은 `CLAUDE.md` §5.
> **참조 표기 규약:** `CLAUDE.md §N`(거버넌스), `상위 spec §N`(claim 계약), `본 문서 §N`(이 설계). 접두사 없는 `§N`은 사용하지 않는다.
> **선행:** COMPOSE-K562-v1 ACTIVE (2026-06-30 activation). 실제 sealed run은 A100 + 유효한 `ActivationRecord` + clean tree로 1회.

---

## 0. 목적과 범위

COMPOSE-K562-v1이 ACTIVE가 됐지만, sealed Phase-2b run을 실제로 돌리기 전에 세 가지 activation-time 배선이 남아 있다.

- **A. Deep-baseline backends.** comparator family(상위 spec §10.5)의 GEARS·CPA가 현재 `src/alive/compose/baselines_combo.py`의 *guarded seam*(`BaselineAdapter`)일 뿐이고 실제 backend가 없다. verdict가 `GI_LEARNABLE_WIN`이 되려면 headline이 GEARS·CPA·ID-only·L3를 simultaneous로 이겨야 하므로(상위 spec §10.5), 두 backend를 공정·강하게 실행할 수 있어야 한다.
- **B. Phase-2b provenance digests.** `src/alive/compose/phase2b.py`의 provenance 조립이 scientific digest(data-card / raw / processed / sequence-mapping / feature-bank / dependency-lock / gears·cpa revision / device / precision / git commit)를 빈 문자열로 둔 `TODO(activation)` 상태다.
- **C. Persisted-ledger post-access consistency.** `phase2b.py`의 post-access 정합성 검사가 in-memory provenance를 자기 자신과 비교해 production에서 절대 실패할 수 없는 `TODO(activation)` 상태다.

### In scope

- `SubprocessBaselineBackend`와 GEARS·CPA subprocess worker 계약(로컬 stub까지), leakage guard, response-space 사영 전달, determinism/provenance 기록.
- B: provenance digest를 **기존 upstream ledger/preflight 경로와 조화**시키며(단일 진실원천) 채우는 typed 주입 경로.
- C: seal 접근 전 write-once ledger에 **pre-access provenance digest subset**의 checksum을 기록하고 접근 후 그 persisted 값과 교차검증.
- 위 전부에 대한 **로컬 실행 가능** 테스트(단위·leakage·프로토콜·결정론·tamper).

### Out of scope

- 실제 GEARS/CPA fit 실행과 그 로컬 재현: gears/cpa 패키지는 잠긴 A100 env에만 설치되므로 real worker 실행·mini fixture 검증·sealed run은 pod 단계(별도)에서 한다.
- comparator family 구성, primary/secondary metric, verdict 규칙, split, seal 개봉 횟수 변경. 이들은 상위 spec이 고정한다.
- L1/L2/L3·additive·ID-only(이미 구현된 in-process method)의 재설계.
- `phase2b.py` module docstring의 stale 문구("BLOCKED candidate config makes this fail" 등) 정리는 B/C 구현 시 함께 갱신하는 follow-up으로 두되, 별도 claim 변경은 아니다.

### 구현계획 분할

A(subprocess backend 하위시스템)와 B+C(provenance/ledger 무결성)는 분리 가능하다. writing-plans 단계에서 **Plan 1 = A**, **Plan 2 = B+C**로 나눌 수 있다(각각 독립 테스트 가능). B와 C는 provenance 기록·검증을 공유하므로 함께 둔다.

### 거버넌스

본 작업은 dev-stage 배선이다. seal은 열지 않는다(로컬 stub과 단위 테스트는 실제 Norman·실제 seal을 만지지 않는다). backend는 fit-role 데이터만 받고 sealed outcome에 접근할 수 없다. 게이트 PASS는 과학 verdict가 아니다.

---

## 1. A — Deep-baseline subprocess backend

### 1.1 seam 계약 (기존, 불변)

`BaselineAdapter(name, backend)`는 backend 객체에 `is_available: bool`과 `predict(context, pair_ids, response_dim) -> Mapping[pair, ndarray]`만 요구한다. `context`는 `BaselineTrainingContext`(identities·checksums·`training_pair_ids`·`single_gene_ids`만; outcome-store 핸들 없음, sealed 경로 없음)이며 adapter는 backend 호출 **전** 모든 leakage guard(`_assert_no_sealed_reference`, role 일치)를 돌리고 **후** 출력을 요청과 정확히 대조한다(`baselines_combo.py`의 `_validate_backend_output`: 누락·초과·차원·비유한 값 실패). 본 설계는 이 seam을 바꾸지 않고 그 뒤에 붙는 구체 backend를 정의한다.

**role 계약(중요).** seam은 `context.allowed_roles`가 `ALLOWED_ADAPTER_ROLES == {singles, combo_calibration}`와 **정확히 일치**할 것을 요구하며 superset(예: control 추가)을 거부한다(`baselines_combo.py`). 따라서 **GEARS/CPA의 학습 role은 `singles`와 `combo_calibration` 둘뿐**이다. `control`은 학습 role이 아니라 §1.3의 payload 참조 데이터(응답공간 사영·δ 기준)이며 `allowed_roles`에 절대 넣지 않는다.

### 1.2 `SubprocessBaselineBackend`

잠긴 env(gears_env / cpa_env)는 main `.venv`와 공존할 수 없으므로 각 backend를 **별도 subprocess**로 실행한다(dependency-lock 커밋이 정한 실행모델). backend는 다음을 보유하고 구성된다.

- `env_python`: 잠긴 env의 python 실행 경로.
- `worker_script`: env 안에서 도는 스크립트 경로(`scripts/baselines/{gears,cpa}_worker.py`).
- `training_payload`: fit-role 데이터 묶음(§1.3). **비-sealed만.**
- `work_dir`, `seed`, `device`, `precision`.

동작:

- `is_available`: `env_python`으로 대상 패키지 import 가능 여부를 1회 프로브(`python -c "import gears"` / `import cpa`)하고 캐시한다. 실패하면 `False`.
- `predict(context, pair_ids, response_dim)`:
  1. `training_payload` + `pair_ids` + `response_dim`을 `work_dir`의 입력 파일로 직렬화하기 **전에** payload 전체를 sealed-reference 스캔한다(§1.4). sealed token이 있으면 즉시 예외.
  2. `env_python worker_script --in <payload> --out <preds>`를 subprocess로 실행.
  3. `<preds>`를 역직렬화. adapter가 이어서 요청 pair_ids·response_dim과 정확히 대조한다.
  4. worker manifest(package revision·device·precision·seed·worker checksum·payload checksum·prediction checksum)를 반환값 옆에 남겨 provenance(§2)로 전달.

**fail-closed 강제 지점.** `is_available`가 `False`거나 subprocess가 실패하면 adapter는 `BaselineUnavailable`을 던진다. GEARS/CPA 예측은 **Phase-2a에서 frozen bundle로 동결된 뒤** Phase-2b에 들어오므로, roster 불완전(예측 누락)에 대한 fail-closed는 **Phase-2a freeze/roster-assembly**에서 강제된다(`freeze.py`가 불완전 method roster를 거부). 즉 `BaselineUnavailable` → Phase-2a에서 roster 미완 → **INVALID**로 귀결되며(상위 spec §10.5: roster 불완전은 INVALID, 조용한 제외 금지), Phase-2b scoring 단계에서 조용히 빠지는 경로는 없다.

### 1.3 subprocess 데이터 계약 (payload / prediction)

payload는 **비-sealed 데이터만** 담는다. 학습 role은 `singles`·`combo_calibration`이고, `control`은 학습 role이 아니라 응답공간 사영과 δ 기준을 위한 참조 데이터로 포함된다.

- `singles`·`combo_calibration`의 응답공간 표현(또는 원 cell 행렬)과 gene id — **학습 role.**
- `control`의 응답공간 표현/평균 — **참조**(사영·δ 기준), 학습 role 아님.
- calibration pair의 관측 δ(비-sealed dev 역할).
- frozen 응답공간 사영(상위 spec §10.4/§10.5의 `fit_roles=[control, singles]`로 outcome 없이 적합한 PCA components + control mean). 이 사영은 비-sealed이므로 worker에 전달해도 안전하다.
- 요청 `pair_ids`, `response_dim`, `seed`, 제공된 OOF fold 배정(§1.6).

prediction은 요청 각 canonical pair에 대한 길이-`response_dim` δ 벡터의 매핑이다. worker는 GEARS/CPA를 native gene space로 학습·예측하되 **제공된 PCA 사영으로 응답공간 δ를 반환**한다. 이로써 모든 method가 동일 응답공간에서 비교되어(상위 spec §10.5의 `e = p^{-1}||δ̂ − δ||^2`) 공정하다.

payload·prediction은 JSON 헤더 + 배열 파일(예: `.npz`)로 직렬화하고 각각 checksum을 기록한다. 스키마는 버전 필드를 갖고, 알 수 없는 키·누락 키는 실패시킨다.

### 1.4 leakage 불변식

- payload는 **sealed role/token 0**이어야 한다. 직렬화 직전 `baselines_combo.py`의 재귀 sealed-reference 스캐너로 검증한다.
- `context.allowed_roles`는 `{singles, combo_calibration}`와 정확히 일치해야 한다. `control`은 payload 참조 데이터일 뿐 `allowed_roles`에 넣지 않는다(넣으면 seam이 superset으로 거부).
- worker는 outcome-store 핸들이나 sealed 경로를 받지 않는다. 오직 파일로 전달된 비-sealed 데이터만 본다.
- 로컬 stub·단위 테스트는 실제 Norman·실제 seal을 만지지 않는다.

### 1.5 로컬 stub vs pod real

- **로컬(이번 구현):** adapter + subprocess 프로토콜(payload/prediction 스키마·checksum) + leakage guard + orchestration + **stub worker**(`scripts/baselines/stub_worker.py`, 메인 env에서 도는 결정론적 backend — 예: singles로부터의 가산 δ)를 빌드하고 단위·leakage·프로토콜·결정론 테스트로 검증한다. `is_available` 프로브는 존재/부재 fake env로 테스트한다.
- **pod(별도 단계):** real `gears_worker.py`·`cpa_worker.py`를 잠긴 env에서 mini fixture로 검증한 뒤 sealed run에 투입한다. 실제 gears/cpa fit만 pod 전용이며, leakage·프로토콜·orchestration 로직은 100% 로컬에서 검증된다.

### 1.6 published-default 충실도 (owner 결정)

GEARS·CPA는 각자 published/기본 config로 `singles`+`combo_calibration`에 학습한다(sealed 미접촉). 어떤 튜닝 knob도 outcome 기반으로 고르지 않으며, 필요한 경우 상위가 제공한 calibration gene-disjoint OOF fold 배정만 사용한다(`CLAUDE.md` §9, 상위 spec §10.5). GEARS는 GO-graph·gene2go 등 외부 리소스가 필요하며, 이 리소스 취득·구성은 worker 안에서 pod 단계에 이뤄진다. 로컬 stub은 이 외부 리소스를 요구하지 않는다.

---

## 2. B — Phase-2b provenance digests

`phase2b.py`의 provenance 조립은 현재 scientific digest를 빈 문자열/`UNKNOWN`으로 둔다. 활성 run에서 다음을 실제 값으로 채운다.

- `data_card_sha256` ← 커밋된 Norman data-card(`docs/data-cards/norman_compose_k562_v1.json`)의 checksum.
- `raw_or_source_sha256`, `processed_sha256` ← data-card의 해당 필드.
- `sequence_mapping_sha256`, `feature_bank_sha256` ← 활성 run에서 생성되는 ESM sequence-mapping / feature-bank 아티팩트(data-card에는 ESM feature-bank digest가 없으므로 그 아티팩트를 진실원천으로 삼는다; 존재 확인은 구현계획에서).
- `dependency_lock_sha256` ← `docs/activation-evidence/compose/gears_cpa_dependency_lock.json`.
- `gears_revision`, `cpa_revision` ← **dependency-lock의 고정 패키지 spec**(lock은 두 패키지를 런타임 `__version__` 없이 기록하므로 런타임 버전 문자열이 아니라 lock의 pinned 항목을 진실원천으로 삼는다). §1.2 worker manifest는 보조 확인용.
- `device`, `precision` ← run 환경.
- `git_commit` ← run 시점 git SHA.

**단일 진실원천.** run-identity에 쓰이는 digest(data_card / raw / sequence_mapping 등) 중 일부는 이미 preflight의 `_required_digest`와 run-id 재계산 경로로 upstream ledger에서 흐른다(`phase2b.py`). typed 입력 객체(가칭 `ActivationProvenanceInputs`)는 그 기존 원천과 **조화**시켜 같은 digest가 두 진실원천을 갖지 않게 한다(정확한 필드·원천 매핑은 구현계획에서 확정). 조립된 provenance의 pre-access subset(§3)은 **seal 접근 전** write-once ledger에 기록된다.

---

## 3. C — Persisted-ledger post-access consistency

현재 post-access 정합성 검사는 in-memory provenance 객체를 자기 자신과 대조하므로 provenance leg가 production에서 결코 실패하지 않는다(run-id·request-checksum leg만 실제 교차검증).

**제약(검증됨).** `Phase2bProvenance`의 full self-checksum은 **post-access** result checksum(`regime_result_double/single_sha256`, terminal-report checksum)을 포함한다. 이 값들은 `evaluate_sealed_once` 이후에만 계산되므로 full provenance checksum을 seal 접근 **전** 등록할 수는 없다. 따라서 C는 full checksum이 아니라 **pre-access digest subset**을 등록한다.

- **pre-access digest subset** = §2의 scientific/upstream digest(config·data-card·raw·processed·sequence-mapping·feature-bank·dependency-lock·gears/cpa revision·device·precision·git-commit·upstream artifact checksums) — 즉 **post-access result/terminal checksum을 제외한** 접근 전 계산 가능한 필드 집합. 정확한 필드 열거는 구현계획에서 확정한다.
- **seal 접근 전:** 이 subset의 canonical checksum을 write-once ledger에 등록한다.
- **seal 접근 후:** subset을 재계산해 ledger에서 읽어온 persisted 값과 대조한다. 불일치면 결과를 **INVALID**로 만든다.
- post-access result/terminal checksum은 접근 후 scoring에서만 알 수 있으므로 지금처럼 접근 후 write-once로 기록한다(구조 유지).

이로써 provenance leg가 자기참조를 벗어나 실제 tamper-detecting 무결성 검사가 된다(`CLAUDE.md` §11, 상위 spec §7). "모든 무결성 검증 완료"로 표현하지 않는다(구조적 self-check 한계 유지, 상위 spec §10.6).

---

## 4. 테스트 (전부 로컬 실행 가능, `CLAUDE.md` §13)

- **프로토콜 round-trip:** payload↔prediction 직렬화/역직렬화 왕복이 값·checksum을 보존한다.
- **leakage:** sealed role/token을 주입한 payload는 직렬화 전 스캐너가 예외를 던진다; `allowed_roles`에 `control`을 넣으면 seam이 거부한다; 정상 payload는 학습 role `{singles, combo_calibration}`만 갖는다.
- **stub end-to-end:** `BaselineAdapter` + `SubprocessBaselineBackend` + stub worker가 요청 pair에 대해 유효 δ를 반환하고 adapter 대조를 통과한다.
- **`is_available` fail-closed:** 부재/깨진 env → `BaselineUnavailable`; Phase-2a freeze/roster-assembly가 불완전 roster를 거부해 **INVALID**로 귀결(조용한 skip 없음)임을 검증.
- **provenance known-answer:** 주어진 data-card·lock·환경 입력에 대해 조립된 digest와 pre-access subset checksum이 기대값과 일치한다.
- **persisted-ledger tamper:** 접근 전 등록한 pre-access subset을 접근 후 변조하면 post-access가 **INVALID**를 낸다(현재는 잡지 못하는 것을 잡게 됨).
- **결정론:** 동일 seed·동일 payload → 동일 stub 예측.

pod 단계에서만 가능한 것(real gears/cpa import·GO-graph·real fit·mini fixture e2e·sealed run)은 명시적으로 로컬 테스트에서 제외하고 pod runbook으로 넘긴다.

---

## 5. 보존되는 거버넌스 불변식

- sealed 미접근: backend·worker·stub 어느 것도 sealed outcome을 만지지 않는다(`CLAUDE.md` §5.3, §6).
- 학습 role 한정: GEARS/CPA는 `singles`·`combo_calibration`에만 학습한다(`CLAUDE.md` §5.4, 상위 spec §10.5). `control`은 비-sealed 참조(응답공간 사영·δ 기준)이며 학습 role이 아니다.
- fail-closed: 사용 불가 backend는 Phase-2a freeze에서 roster 미완으로 INVALID이며 조용히 제외하지 않는다(상위 spec §10.5).
- write-once·immutability: pre-access provenance subset은 접근 전 기록되고 이후 tamper-detecting이다(`CLAUDE.md` §11).
- published-default·OOF-only 튜닝: outcome 기반 baseline 튜닝 금지(`CLAUDE.md` §9).
- PASS는 과학 verdict가 아니다: 본 작업은 실행 배선이며 claim을 바꾸지 않는다.

---

## 6. 완료 정의

- 본 문서 §1–§3의 코드가 로컬에서 구현되고 §4 테스트가 전부 green이다.
- comparator family에 대해 `SubprocessBaselineBackend`가 stub worker로 end-to-end 통과하고, 부재 backend가 Phase-2a freeze에서 INVALID로 fail-closed한다.
- `phase2b.py`의 두 `TODO(activation)`가 해소된다: provenance digest가 typed 입력으로(기존 upstream 원천과 조화되어) 채워지고, post-access 정합성이 pre-access subset의 persisted ledger 값과 교차검증한다.
- 로컬 전체 suite + ruff green. 이후 `science-dev` loop-gate로 각 구현 increment를 게이트한다.
- pod 전용 잔여 작업(real gears/cpa worker·GO-graph·mini fixture·sealed run)은 pod runbook에 명시적으로 이관된다.

## 7. Out of scope / open questions

- real GEARS/CPA worker의 정확한 published config·GO-graph 소스·CPA setup 세부는 pod 단계에서 각 worker와 함께 확정한다(로컬 stub은 무관).
- 응답공간 사영을 worker에 넘길지, worker가 gene-space 예측을 반환하고 main이 사영할지: 본 설계는 **사영을 worker에 전달**해 backend가 응답공간 δ를 반환하는 쪽으로 고정한다(adapter 계약 단순화).
- `ActivationProvenanceInputs`의 정확한 필드 이름과, 어느 digest가 기존 preflight/run-id 경로에서 오고 어느 것이 새로 조립되는지의 매핑은 구현계획에서 확정한다(본 설계는 채울 digest 목록·원천 종류와 pre-access subset 경계를 고정한다).
- pre-access subset의 정확한 필드 열거(어느 provenance 필드가 접근 전 계산 가능한 scientific digest이고 어느 것이 본질적으로 post-access인지)는 구현계획에서 확정한다.

## 참고

- 상위 계약: 상위 spec §10.5–§10.6, §7.
- 거버넌스: `CLAUDE.md` §5, §6, §9, §11.
- seam·guard: `src/alive/compose/baselines_combo.py`.
- 바인딩 지점: `src/alive/compose/phase2b.py`(provenance 조립, post-access 정합성), `src/alive/compose/provenance2.py`(`Phase2bProvenance`, self-checksum), `src/alive/compose/freeze.py`(roster-completeness fail-closed).
- env lock: `docs/activation-evidence/compose/gears_cpa_dependency_lock.json`.
