# COMPOSE-K562-v1 — Sealed-Run Readiness Index

> **역할:** COMPOSE sealed A100 run까지 남은 작업의 단일 human-facing 인덱스.
> **현재 상태:** lifecycle **ACTIVE** · execution **RELEASE-BLOCKED** · seal **UNOPENED**.
> **kernel-isolation proof: STALE** — pending re-proof for `src/alive/compose/approximation_bias.py`
> (R1, `aed26aa`); Linux kernel-isolation CI re-run required (POD-GATED). Enforced by
> `tests/alive/compose/test_kernel_isolation_ci.py::_PENDING_REPROOF`.
> **이 문서는 아무것도 정의하지 않는다** — 세부(task)는 plan, claim은 spec, exact param은 config,
> 시간순 audit는 git이 authoritative다([sources of truth](../../CLAUDE.md#sources)). 상태 행이 authoritative
> 문서와 어긋나면 **authoritative 문서가 옳다**; 이 인덱스를 갱신한다.
> **Updated:** 2026-09-08 @ `fd9a16d` (branch `compose-factor-bank-normalization`)
> `scripts/bump-readiness-stamp.sh` / the pre-commit hook from `HEAD` at commit time, so it names the
> **parent** of the commit that carries it and can never name itself. Reading it as "one commit stale" is a
> misreading; git is authoritative for when this file actually changed.
> **갱신 트리거:** sub-project/gate **상태가 바뀔 때만**(커밋마다 아님).
> **종결 상태:** COMPOSE seal이 정확히 한 번 열리면 이 인덱스는 **frozen/은퇴**한다. 이후 진행상황은
> seal 결과와 post-hoc analysis가 대신한다.

## 목표

`COMPOSE-K562-v1` (ACTIVE)의 **pod sealed confirmatory run** — A100에서 유효한 `ActivationRecord`
(requirement별 non-empty evidence hash) + clean git tree로 seal을 **정확히 한 번** 연다.
실행 계약(runbook): `runbooks/2026-07-02-compose-k562-pod-sealed-run.md`.

상태 범례: ✅ merged(main) · 🟡 in-progress(branch) · 🔴 needs-implementation · ⏳ pod-stage · ⛔ blocked

## Sub-project 상태 (dev-stage)

| # | Sub-project | 상태 | authoritative 문서 (docs/superpowers/…) |
|---|---|---|---|
| P1 | Phase 1 — identifiability 증명 + Norman pre-check | ✅ merged | `plans/2026-06-23-compose-phase1.md` |
| P2a | Phase 2a — dev pipeline | ✅ merged | `plans/2026-06-24-compose-phase2a-dev-pipeline.md` |
| P2b | Phase 2b — seal 기계 + inference | ✅ merged | `plans/2026-06-24-compose-phase2b-seal-eval.md` |
| A | fit-data contract (A1 fit-role artifact + A2 payload-v2) | ✅ merged (PR #9) | `specs/2026-07-02-compose-fit-data-contract-design.md`; `plans/2026-07-03-compose-fit-role-artifact-a1.md`, `plans/2026-07-04-compose-payload-v2-a2.md` |
| B | real GEARS/CPA deep baselines (pod-only) | ⏳ subprocess backend + real worker/`.pyz` bundle + GO v2 manifest 커밋 완료; **adapter 해석의 로컬 절반 닫힘**(committed method manifest `configs/compose_adapter_versions_v1.json`, `a33d04a`·`b23e018` — declared↔manifest 불일치는 assembly 에서 fail-closed). **남은 것은 POD**: real pod-built `.pyz` 의 self-report parity, dep-lock(`INCOMPLETE`), real fit | `specs/2026-07-01-compose-deep-baselines-design.md`; `plans/2026-07-01-compose-deep-baselines-backend.md`, `plans/2026-07-01-compose-deep-baselines-provenance.md` |
| G | driver-guards — scientific-boundary wiring | ✅ merged (PR #10) | `specs/2026-07-04-compose-driver-guards-design.md` |
| D1 | durable-publish + non-circular provenance | ✅ merged | `specs/2026-07-05-compose-durable-ledger-design.md`; `plans/2026-07-06-compose-durable-ledger-d1.md` |
| D2 | development seed-variability (Task 1–6) | ✅ merged | `plans/2026-07-06-compose-durable-ledger-d2.md` |
| C0 | seal-critical library fixes (7) | ✅ merged (via C merge `1c46708`) | `plans/2026-07-07-compose-c0-library-fixes.md` |
| C | 단일 production driver + scientific PREPARE carrier | ✅ merged (`1c46708` 2026-07-09, carrier `a777ea2`) — 전체 scientific CLI 조립은 sub-project-B 경계에서 **fail-closed**(run 산출물 0 · store 0 · seal UNOPENED) | `specs/2026-07-07-compose-production-driver-design.md`; `specs/2026-07-11-compose-scientific-prepare-carrier-design.md`; `plans/2026-07-12-compose-scientific-prepare-carrier.md` |
| GU | outcome-free GEARS gene-roster generator (full response universe 보존 · M-first · exact `N_target` · alias · fail-closed) | ✅ **PASS** — exact-committed-SHA `7f6595f` 를 3개 독립 adversarial lens 로 리뷰(0 Critical / 0 Important) → main 병합. **seal 안 열림** | `specs/2026-07-11-compose-gene-universe-design.md`; `audits/2026-07-11-compose-gu-exact-sha-independent-review.md`; `runbooks/2026-07-11-compose-gears-decision-probe-rerun.md` |
| — | **pod sealed confirmatory run (opens seal once)** | ⛔ blocked — 아래 release matrix 의 모든 행이 GREEN 이 되기 전에는 시작하지 않는다 | `runbooks/2026-07-02-compose-k562-pod-sealed-run.md` |

**GU review-status promotion rule:** `PASS`로 다시 올리려면 reviewed spec Git SHA, gate profile/iteration,
verifier verdict summary와 verifier-output SHA-256(또는 같은 내용을 담은 committed audit artifact)을 이
branch에서 추적 가능하게 기록한다. `LOCAL` ledger ID만으로는 이 sealed-readiness 인덱스의 PASS 근거가
되지 않는다.

## Critical path to seal

R1 수정 → 계약/config 정합 → `D1`~`D4` 서명 → adapter/runtime → 별도 pod evidence → 최종 owner gate.
아래 표의 모든 행이 GREEN 이 되기 전에는 sealed run 을 시작하지 않는다.

The committed config still carries **six** activation blockers, exactly as
`ComposePhase2Config.activation_blockers` measures them, at config digest `a9dc9410…`. 아래 여섯 행의
키는 그 loader 출력을 `sorted()` 순서 그대로 옮긴 것이다.

| gate | 현재 | 해소 산출물 | 실행 위치 | 책임 |
|---|---|---|---|---|
| `baselines.approximation_bias_report_sha256` | BLOCKED (`a246389` 2026-06-23 이후 값 불변, 2026-09-06 감사 snapshot) | real Norman 에서 생성한 `compose_approximation_bias_report_v4` + `sha256_file(report)` 단방향 finalize | POD-GATED | baselines owner |
| `baselines.cpa.environment_status` | BLOCKED (`a246389` 2026-06-23 이후 값 불변, 2026-09-06 감사 snapshot) | pinned image 에서 실행한 dependency-lock/runtime 관찰(현재 lock 은 정직하게 `INCOMPLETE`) | POD-GATED | baselines owner |
| `baselines.cpa.revision` | BLOCKED (`a246389` 2026-06-23 이후 값 불변, 2026-09-06 감사 snapshot) | published upstream config·revision 고정 + pod-built `.pyz` 와의 일치 증명 | POD-GATED | baselines owner |
| `baselines.gears.environment_status` | BLOCKED (`a246389` 2026-06-23 이후 값 불변, 2026-09-06 감사 snapshot) | pinned image 에서 실행한 dependency-lock/runtime 관찰(현재 lock 은 정직하게 `INCOMPLETE`) | POD-GATED | baselines owner |
| `baselines.gears.revision` | BLOCKED (`a246389` 2026-06-23 이후 값 불변, 2026-09-06 감사 snapshot) | published upstream config·revision 고정 + pod-built `.pyz` 와의 일치 증명 | POD-GATED | baselines owner |
| `regimes.power_status` | BLOCKED (`a246389` 2026-06-23 이후 값 불변, 2026-09-06 감사 snapshot) | real Norman 에서의 detectable-effect / power 분석 | POD-GATED | scientific owner |
| `adapter_resolution` | 🟡 로컬 manifest 해석 **완료**(`a33d04a`, `b23e018`) — `adapter_version` 은 committed method manifest 에서 해석되고 declared 값과 다르면 assembly 에서 fail-closed | real pod-built `.pyz` worker 의 **self-reported** `_ADAPTER_VERSION`↔manifest parity(runtime predict 시점) | 로컬 완료 · parity POD-GATED | driver owner |
| `source_consumption` | `D3` SIGNED: a → **`POLICY_SIGNED / RUNTIME_UNVERIFIED`** — `seal.transient-inode-mutation-restoration` 은 승인 runtime 전제 아래 수용된 잔여다. [2026-09-08 정정 — C1] 소비 중 변조의 탐지는 **materialization 경계**(`materialize_claimed` 의 `post_materialization_check`)에서 돌며 durable witness 는 `ABORTED_AFTER_SEAL`(phase2b·recover 모두 30); 소비 **후** 변조는 stderr 진단 한 줄뿐이고 durable witness 가 없다(D3-a 전제가 덮는다) | 그 전제의 실제 storage / mount / actor 증거 | POD-GATED | runtime owner |
| `kernel_isolation_reproof` | ⚠ STALE — `src/alive/compose/approximation_bias.py` 가 R1(`aed26aa`)로 바뀌어 v2 커널 격리 증명(`2dd23d6`)이 더 이상 덮지 않음(`test_kernel_isolation_ci.py` 의 `_PENDING_REPROOF` 에 digest 로 등록) | Linux kernel-isolation CI 재실행 + 새 archive + pin 이동 | POD-GATED | runtime owner |
| `D1` / `D2` / `D4` | SIGNED → **GO-LOCAL** (Task 11 / 12 / 14, 2026-09-07) — 서명은 선택이지 릴리스가 아니다 | 서명된 claim 결정문 `2026-09-07-compose-audit-release-decisions.md` (D1 λ\* 측정은 POD) | 로컬 완료 | scientific owner |
| `owner_release` | ⛔ **NO-GO** | 위 모든 행 GREEN + finalized lineage + 유효 `ActivationRecord` + clean exact SHA 에 대한 owner 승인 | 별도 승인 | owner |

**POD-GATED / 로컬** — POD: real Norman power · GEARS/CPA revision+environment 증명 · bias report 생성과
finalize · adapter parity · `D1` λ\* 측정 · kernel-isolation CI 재실행 · source-consumption runtime 증거.
로컬: 계약 정합 · claim 상한 문서 · unit/synthetic · 변이 확인.

⚑ config 확정(null 채움)은 **새 run identity**를 만든다. activation evidence 는 finalized config 뒤에
재생성한다 — 현재 committed 분석 evidence 는 pre-activation lineage 다.

## 열린 결정 (seal 전 필수)

결정 id 는 backtick 으로 쓴다(`D1`~`D4`). 위 sub-project 표의 D1/D2 는 이름이 겹칠 뿐 **별개의**
sub-project id 다.

| id | 무엇 | 상태 | 문서 |
|---|---|---|---|
| `D1` | ladder attribution claim 상한 | SIGNED: a → GO-LOCAL (Task 11) | `2026-09-07-compose-audit-release-decisions.md` |
| `D2` | ESM ID-null | SIGNED: b → GO-LOCAL (Task 12) | 〃 |
| `D3` | R2 위협 모델 | SIGNED: a → GO-LOCAL (Task 13); runtime 증거 POD-GATED | 〃 |
| `D4` | pair dependence headline 문장 | SIGNED: a → GO-LOCAL (Task 14) | 〃 |
| Amendment D | bias spec §1 — bridge representation + report v4 | SIGNED → EFFECTIVE (Task 2) | 〃 |
| Amendment E | main spec §10.5 — primary metric 식 | SIGNED → EFFECTIVE (Task 3) | 〃 |
| Amendment F | main spec §3.3 — ladder claim 상한 | SIGNED → EFFECTIVE (Task 11) | 〃 |
| Amendment G | `CLAUDE.md` (+ D2-b 의 `#data-eval` ablation-의무 처분) | SIGNED → EFFECTIVE (Task 8 + 12) | 〃 |

서명·처분·digest 이동의 authoritative 기록은 결정문 자신이다. 이 표는 인덱스일 뿐이며 어긋나면
결정문이 옳다.

**닫힌 결정 — 2026-08-20 이후 (포인터만; 본문은 각 결정문이 authoritative).**

| 닫힌 것 | 서명 | 문서 |
|---|---|---|
| dev-pod gate #1 · #3 · #4 · #5 | CONFIRMED 2026-08-29 | `2026-07-13-compose-dev-pod-gate-decisions.md` |
| 결정 #6 (`l3_hypernetwork` 이름) · 결정 #7 (ladder λ 비교가능성) | APPROVED 2026-08-20/21 | `2026-08-17-compose-ablation-ladder-decisions.md` |
| 수정안 A (main spec §10.6 access-count) · B (§10.5 band sensitivity) · C (driver stdout) | SIGNED 2026-09-03 / 09-05 | `2026-08-30-compose-spec-10-5-amendments.md` |

**config digest 체인** — `3faacaff…`(#4 정규화) → `c25734d5…`(결정 #6) → `5fea3b9e…`(결정 #7) →
`0d207746…`(pair dependence, `2026-08-29-compose-pair-dependence-decision.md`) → `a9dc9410…`(F-A3
`measurability_ceiling_floor`, `2026-09-07-compose-audit-release-decisions.md`). 각 단계의 근거는
그 결정문이며 현재 값은 위 표의 `a9dc9410…` 다.

## Go/No-Go (2026-09-07, 로컬 검증 결과)

로컬 ladder 는 **닫힌 것**만 증명한다. 아래는 seal 을 열기 위한 인수조건이며, 한 행이라도
미충족이면 판정은 `RELEASE-BLOCKED` / seal `UNOPENED` 다.

| 묶음 | 인수조건 | 현재 |
|---|---|---|
| representation (R1 후속) | raw 유지: 별도 raw bridge/equivalence evidence. log 채택: signed config·projection·metric amendment + known-answer. 현 log PASS 만으로 어느 쪽도 자동 승인되지 않는다 | ⛔ 미결 |
| analytical evidence | 최종 config 의 phi-rank/condition, regime detectable-effect, data card/source/feature hashes | ⏳ POD-GATED |
| deep workers | method 별 revision, dependency/image/wheel hashes, row roster, fresh-sync smoke, `adapter_resolution` manifest parity | ⏳ POD-GATED |
| `D1` 결판 | 승인된 nonsealed gene-disjoint OOF 의 k\*, λ\*, arm sensitivity | ⏳ 서명 GO-LOCAL · 측정 POD-GATED |
| `D3` | `source_consumption` 의 실제 storage/actor/mount evidence 또는 kernel snapshot negative | ⏳ 서명 GO-LOCAL · 증거 POD-GATED |
| one-way identity | 모든 과학 config field 확정 → bias-null basis + code/spec commit `C` 고정 → 외부 report → finalized YAML 의 report SHA leaf 만 변경 → activation evidence 재생성 | 🔴 미착수 |
| 최종 `owner_release` gate | 위 모든 행 + 현재 `ActivationRecord` · finalized evidence/config identity · clean exact SHA · runbook READY | ⛔ NO-GO |

**판정: RELEASE-BLOCKED / seal UNOPENED.** 이유 다섯, 전부 로컬에서 닫을 수 없다 — (1) 위
critical-path 표의 config activation blocker 여섯, (2) real pod-built `.pyz` 의 `adapter_resolution`
parity, (3) `kernel_isolation_reproof`, (4) `source_consumption` 의 runtime 증거, (5) representation
결정. `D1`~`D4` 네 절 모두 서명됐지만 서명은 릴리스가 아니다.

로컬에서 닫힌 것(2026-09-07): 이번 웨이브가 바꾼 강제 지점 17개가 각각 **자기 이름이 그 주장을 하는**
named test 의 **자기 assertion** 으로 죽는다(17 killed / 0 survived / 0 harness-failed) —
`scripts/compose_audit_mutation_harness.py`, ledger 는 결정문의 `## 검증 ledger (Task 15)`.
unit green 을 READY 로 번역하지 않는다.

## 시간순 서술

→ `journal/2026-09-07-compose-readiness-narrative-archive.md` (비-authoritative) 및 `git log`.

## 이 문서가 *아닌* 것 (중복 금지)

- **governance / safety invariant / seal 규칙** → `CLAUDE.md`#sources, #invariants, #seal
- **scientific claim 정의** → 각 sub-project **spec**
- **task 세부 · 체크박스 · 구현 순서** → 각 **plan**
- **exact split / threshold / seed / metric** → **config** (`configs/compose_k562_v1_phase2.yaml`)
- **시간순 audit trail** → **git log**
- **agent session-start recall** → private MEMORY (repo 밖)

<!-- maintainer note: index-only. 새 sub-project나 상태 전이 시 위 표의 '상태' 열과 critical-path만 갱신하고,
     Updated 스탬프(date @ commit)를 함께 바꾼다. 세부/claim/param을 여기에 복제하지 않는다. seal 개봉 시 frozen. -->
