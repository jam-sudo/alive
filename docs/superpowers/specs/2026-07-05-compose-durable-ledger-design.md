# COMPOSE Durable Final-Ledger + Seed-Variability (sub-project D) Design

> **문서 역할:** dev-stage 설계 계약 (scientific claim contract 아님)
> **개정일:** 2026-07-05
> **상위 protocol:** `COMPOSE-K562-v1` (ACTIVE, 2026-06-30 activation)
> **상위 계약:** pod sealed-run runbook `docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md` §2.4 (durable artifact + reporting), §2.5.8 (release gate)
> **거버넌스:** `CLAUDE.md` §5, §10, §11, §14, §15
> **선행:** deep-baselines A/B/C + driver-guards 모두 로컬 완결. 이 서브프로젝트는 그 위에 스택.

---

## 0. 목적과 범위

pod sealed-run runbook이 §2 release blocker로 지정한 두 가지 내구성 요구를 dev-stage에서 구현한다:
현재 `Phase2bResult.ledger`가 프로세스 메모리 객체라 terminal 전이 후 결과가 파일로 보존되지 않고,
stochastic comparator의 development seed-variability(CLAUDE.md §10이 요구)가 산출되지 않는다.

이 서브프로젝트는 **과학적 결과를 재계산하지 않는다.** `Phase2bResult`가 이미 노출하는 값
(`regime_double`/`regime_single`=`RegimeScore`, `sealed_verdict`, provenance/result checksum)을
**내구 저장**하고, seed-variability는 **non-sealed development role에서만** 별도 산출한다.

### In scope
- **D1** — terminal 전이가 반영된 최종 ledger + registered-summary artifact를 원자적 write-once로
  export하고 재독출 검증(§1, §2).
- **D2** — stochastic comparator development seed-variability 요약 하니스(§3).

### Out of scope
- 실제 gears/cpa의 seed-variability **숫자** — 잠긴 env가 필요하므로 pod에서 동일 하니스로 산출.
- 실제 sealed run, 실제 Norman 로드, 실제 worker — pod 소관.
- object-storage 업로드/재검증(runbook §8) — pod teardown 절차.
- verdict/scoring 로직 변경 — D는 기존 결과를 저장·요약만 한다.

### 거버넌스
- **seal은 열지 않는다.** D1은 **이미 소비된** `Phase2bResult`의 아티팩트를 저장하고, D2는 non-sealed
  development outcome store만 사용한다. gate PASS ≠ 과학 verdict.
- 등록되지 않은 **per-pair CI를 생성하지 않는다**(CLAUDE.md §10, runbook §2.4) — 등록된 추론은
  pair-resampled aggregate simultaneous bound다.
- write-once/immutability(§11): 기존 아티팩트를 조용히 덮어쓰지 않는다.

---

## 1. D1 — 최종 ledger 내구 export

`export_final_ledger(*, run_dir, ledger) -> Path`.

- terminal 전이가 반영된 **최종** `RunLedger`(`Phase2bResult.ledger`)를 canonical JSON
  (`json.dumps(ledger.to_dict(), sort_keys=True, separators=(",", ":"))`)으로 직렬화해
  `run_dir/phase2b_final_ledger.json`에 `alive.io.atomic_write_once`로 쓴다.
- 기존 `provenance2.persist_pre_access_ledger`(pre-access snapshot)의 **post-access 짝**이다. 동일
  primitive·동일 직렬화. pre-access 파일과 **다른 이름**이라 둘 다 보존된다.
- **재독출 검증:** 쓴 뒤 파일을 다시 읽어 파싱하고 직렬화 bytes가 byte-identical함을 확인한다.
  불일치 시 `DurableLedgerError`.
- write-once: 대상 파일이 이미 있으면 `atomic_write_once`가 실패한다(재실행 금지, §11).

## 2. D1 — registered-summary artifact

`export_registered_summary(*, run_dir, result) -> Path`.

`Phase2bResult`에서 **추출만** 한 registered summary를 `run_dir/phase2b_registered_summary.json`에
write-once + 재독출 검증한다. 필수 항목(runbook §2.4):

- per-method aggregate error, theta, simultaneous lower bounds — `result.regime_double` /
  `result.regime_single`(`RegimeScore`)에서.
- GI-explained secondary interval — `RegimeScore`의 secondary block에서.
- sample counts — `RegimeScore`의 등록된 sample-count 필드에서.
- integrity clauses — `result.sealed_verdict`(`ComposeIntegrityReport`)에서, integrity disclaimer
  포함(run-internal self-check, NOT audit).
- audit/checksums — `run_id`, `terminal_state`, `sealed_access_count`, `provenance_checksum`,
  `result_checksum`.

summary는 self-excluding checksum을 갖는다(자기 checksum 제외 후 해시). **per-pair CI를 포함하지
않는다.** `gi_structure_recovery`는 `NOT_EVALUABLE`로 그대로 기록한다.

### 1–2 공통: terminal 보호 경계
두 export는 terminal 전이가 확정된 뒤, **`COMPLETE`뿐 아니라 `INVALID`/`ABORTED_AFTER_SEAL`에서도**
호출된다 — 이들도 seal-소비 결과이므로 아티팩트를 보존한다(runbook §2.4, §2.5). 정확한 호출 지점
배선(누가 `run_phase2b` 후 export를 호출하는지)은 구현계획에서 확정하되, 본 설계는 export 함수가
terminal state와 무관하게 주어진 `Phase2bResult`를 저장함을 고정한다.

---

## 3. D2 — development seed-variability 요약

`development_seed_variability(*, inputs, dev_outcome_store, comparators, seeds) -> SeedVariabilityReport`.

- 등록된 `seeds`마다 **stochastic** comparator(`gears`, `cpa`, `l3_hypernetwork`)를 **non-sealed
  development role에서만** 재적합하고, comparator별 development-phase error를 수집한다.
- comparator별 spread 요약(across seeds): mean, std, min, max, 그리고 seed→error 매핑.
- **seal 재개방 없음:** `dev_outcome_store`(development role)만 사용한다. sealed outcome store를 받지
  않는다(구조적으로 seal 미접근 — driver-guards §2와 동일 원칙).
- **deterministic component**(`l1_bilinear_identifiable` headline, `additive`, `id_only`)는 구성상
  seed-불변이므로 재적합하지 않고 **single-shot**로 명시 기록한다. 이 사실을 stochastic seed-variability
  보고의 **대체 근거로 쓰지 않는다**(runbook §2.4).
- report는 self-checksummed하며 D1 registered-summary에 포함되거나 그 옆에 write-once로 저장된다
  (정확한 배치는 구현계획).

### 3.1 로컬 vs pod
하니스(seed 루프·재적합·수집·요약)는 **100% 로컬 빌드·검증**한다: stub adapter(결정론 → spread 0 =
known-answer 테스트) + `l3_hypernetwork`(실제 stochastic → 실제 non-zero spread). **실제 gears/cpa
숫자는 잠긴 env가 필요하므로 동일 하니스로 pod에서** 산출한다(로컬은 stub으로 배선만 증명).

---

## 4. 보존되는 거버넌스 불변식
- seal 미개방(D1=소비된 결과 저장, D2=non-sealed dev 분석). `sealed_access_count`는 D가 증가시키지
  않는다.
- write-once/immutability(§11): 모든 export는 `atomic_write_once`로 기존 파일을 덮지 않고, 쓴 뒤
  재독출 검증한다.
- per-pair CI 금지; 등록된 aggregate simultaneous bound만(§10, runbook §2.4).
- seed-variability는 non-sealed development role에서만; deterministic single-shot을 stochastic 보고의
  대체로 쓰지 않음.
- D는 verdict/scoring 값을 재계산하지 않고 `Phase2bResult`에서 추출만 한다.

## 5. 테스트 (전부 로컬 실행 가능, `CLAUDE.md` §13)
- **D1 export_final_ledger:** 합성 `RunLedger` write→재독출 byte-identical; 두 번째 호출은 write-once
  실패; pre-access 파일과 공존.
- **D1 registered-summary:** 합성 `Phase2bResult`에서 모든 필수 필드 추출·self-checksum 검증; per-pair
  CI 부재 확인; `COMPLETE`/`INVALID`/`ABORTED_AFTER_SEAL` 모두 저장됨; 변조 시 재독출 검증 실패.
- **D2 seed-variability:** stub adapter → 모든 seed 동일 error(spread 0) known-answer; `l3` → non-zero
  spread; deterministic comparator는 재적합 안 됨(single-shot로 표기); `dev_outcome_store`만 접근하고
  sealed store 미접근(leakage 테스트).
- 전 스위트 + ruff green. 이후 `spec-review`/`science-dev` loop-gate로 게이트.

## 6. 완료 정의
- §1–§3 코드가 로컬에서 구현되고 §5 테스트가 전부 green이다.
- 실제 gears/cpa seed-variability 숫자·object-storage 업로드·sealed run은 pod runbook으로 명시 이관된다.

## 참고
- 상위 계약: pod runbook §2.4, §2.5.8, §8.
- 재사용: `alive.io.atomic_write_once`, `alive.compose.provenance2.persist_pre_access_ledger`,
  `alive.compose.phase2b.Phase2bResult`, `RegimeScore`, `ComposeIntegrityReport`.
- 거버넌스: `CLAUDE.md` §5, §10, §11, §14, §15.
