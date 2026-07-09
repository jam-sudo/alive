# COMPOSE-K562-v1 — Sealed-Run Readiness Index

> **역할:** COMPOSE sealed A100 run까지 남은 작업의 단일 human-facing 인덱스.
> **이 문서는 아무것도 정의하지 않는다** — 세부(task)는 plan, claim은 spec, exact param은 config,
> 시간순 audit는 git이 authoritative다(sources-of-truth: `CLAUDE.md`#sources). 상태 행이 authoritative
> 문서와 어긋나면 **authoritative 문서가 옳다**; 이 인덱스를 갱신한다.
> **Updated:** 2026-07-09 @ `48bc22a` (branch `compose-c-driver`)
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
| B | real GEARS/CPA deep baselines (pod-only) | ⏳ subprocess backend merged; **real fit은 pod-stage**(sealed run 중 실행) | `specs/2026-07-01-compose-deep-baselines-design.md`; `plans/2026-07-01-compose-deep-baselines-backend.md`, `plans/2026-07-01-compose-deep-baselines-provenance.md` |
| G | driver-guards — scientific-boundary wiring | ✅ merged (PR #10) | `specs/2026-07-04-compose-driver-guards-design.md` |
| D1 | durable-publish + non-circular provenance | ✅ merged | `specs/2026-07-05-compose-durable-ledger-design.md`; `plans/2026-07-06-compose-durable-ledger-d1.md` |
| D2 | development seed-variability (Task 1–6) | ✅ merged | `plans/2026-07-06-compose-durable-ledger-d2.md` |
| C0 | seal-critical library fixes (7) | 🟡 **7/7 done** — branch `compose-production-driver`, main 미병합 | `plans/2026-07-07-compose-c0-library-fixes.md` |
| C | 단일 production driver | 🟡 **in-progress** — branch `compose-c-driver`, T1–T13 + Task 11.5 carrier-loader 완료(cross-process gap CLOSED, driver suite **206 green**, ruff clean); 잔여 **T14 마무리**(whole-branch 리뷰 → fix wave → `finishing-a-development-branch`로 →main 병합; runbook reconcile은 `6a06a4c`에서 완료) | `specs/2026-07-07-compose-production-driver-design.md`; `plans/2026-07-08-compose-c-production-driver.md` |
| — | **pod sealed confirmatory run (opens seal once)** | ⛔ not started (C 완료가 선행) | `runbooks/2026-07-02-compose-k562-pod-sealed-run.md` |

## Critical path to seal

1. ~~C0 마무리~~ ✅ **done** (7/7 fixes, branch `compose-production-driver`).
2. **C production driver 구현** — 단일 committed driver(`phase2a`/`preflight`/`phase2b --confirm-seal`/`recover`),
   MacBook synthetic fixture로 orchestration·fail-closed 전량 검증(spec §0의 acceptance gate). *Gate PASS ≠ scientific verdict.*
3. **branch → main 병합** — clean git tree 확보.
4. **A100 pod: runbook 실행** — 유효한 `ActivationRecord` 하에 `phase2a → preflight → phase2b --confirm-seal`.
   이때 real GEARS/CPA(sub-project B, pod-only)가 실제 fit. **COMPOSE seal 1회 개봉** — `TG-K562`와 독립.

## 이 문서가 *아닌* 것 (중복 금지)

- **governance / safety invariant / seal 규칙** → `CLAUDE.md` (§1 sources-of-truth, §3 invariants, §4 seal)
- **scientific claim 정의** → 각 sub-project **spec**
- **task 세부 · 체크박스 · 구현 순서** → 각 **plan**
- **exact split / threshold / seed / metric** → **config** (`configs/compose_k562_v1_phase2.yaml`)
- **시간순 audit trail** → **git log**
- **agent session-start recall** → private MEMORY (repo 밖)

<!-- maintainer note: index-only. 새 sub-project나 상태 전이 시 위 표의 '상태' 열과 critical-path만 갱신하고,
     Updated 스탬프(date @ commit)를 함께 바꾼다. 세부/claim/param을 여기에 복제하지 않는다. seal 개봉 시 frozen. -->
