# COMPOSE-K562-v1 — Sealed-Run Readiness Index

> **역할:** COMPOSE sealed A100 run까지 남은 작업의 단일 human-facing 인덱스.
> **이 문서는 아무것도 정의하지 않는다** — 세부(task)는 plan, claim은 spec, exact param은 config,
> 시간순 audit는 git이 authoritative다(sources-of-truth: `CLAUDE.md`#sources). 상태 행이 authoritative
> 문서와 어긋나면 **authoritative 문서가 옳다**; 이 인덱스를 갱신한다.
> **Updated:** 2026-07-14 @ `09065ee` (branch `main`)
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
| B | real GEARS/CPA deep baselines (pod-only) | ⏳ subprocess backend + stub merged; **real worker(`gears_worker`/`cpa_worker`) + `.pyz` execution bundle + worker-identity 검증 + GO v2 manifest + pinned env 빌드·4-lens 적대 리뷰(APPROVE-WITH-FIXES; §4.3 guards byte-unchanged; seal 안 열림)·branch `compose-phase1-real-workers`@`dfcab2b` 커밋 완료**; **real-pod rerun 대기**(dep-lock `INCOMPLETE`); real fit은 sealed-run phase2a에서 실행 | `specs/2026-07-01-compose-deep-baselines-design.md`; `plans/2026-07-01-compose-deep-baselines-backend.md`, `plans/2026-07-01-compose-deep-baselines-provenance.md` |
| G | driver-guards — scientific-boundary wiring | ✅ merged (PR #10) | `specs/2026-07-04-compose-driver-guards-design.md` |
| D1 | durable-publish + non-circular provenance | ✅ merged | `specs/2026-07-05-compose-durable-ledger-design.md`; `plans/2026-07-06-compose-durable-ledger-d1.md` |
| D2 | development seed-variability (Task 1–6) | ✅ merged | `plans/2026-07-06-compose-durable-ledger-d2.md` |
| C0 | seal-critical library fixes (7) | ✅ merged (via C merge `1c46708`) | `plans/2026-07-07-compose-c0-library-fixes.md` |
| C | 단일 production driver | ✅ **fixture orchestration merged** (merge commit `1c46708`, 2026-07-09) — T1–T14 완료; whole-branch 2-lens 리뷰(seal-safety + correctness) → Important 2건 fix(phase2b step-5 post-seal raise → exit 30 `6761428`; 미연결 pre-seal pair-index/attestation validator를 preflight에 연결 `4deee1a`); driver 211 / compose 1106 green. **Scientific PREPARE carrier = ✅ 구현 완료 + 리뷰 통과 → main 병합** (branch `compose-scientific-prepare-carrier` @ `a777ea2`): `load_run_spec_carrier`의 `mode="scientific"` 경로를 sub-project-B 경계까지 구현 — discriminated `RunSpecCarrier`(mode+6 scientific fields, `__post_init__` 검증), trusted-repo-root git identity(`resolve_scientific_runtime_context`, no caller-asserted clean; 정확한 HEAD==`approved_git_sha` + clean tree + config 사전등록 seed roster를 `EnvironmentInfo`에 기록), lexical sealed-input attestation equality(source 미개봉), typed `ActivationProvenanceInputs`. **B 경계 fail-closed**: 전체 CLI 조립이 `assemble_execution_identity_lock`의 미커밋 scientific `adapter_version`에서 정지(run 산출물 0·store 0·seal 0). 리뷰 = 10-task subagent-driven(per-task spec+quality + 최종 opus whole-branch Ready-to-merge=YES) + owner 증분(registered_seeds provenance) 세션 리뷰(0 Critical/0 Important; Minor 1건 §5 assembly-order doc-fix 반영). full `tests/alive/compose` **1347 green**, ruff clean. **B-blocked, seal-ready 아님** — §7 release blocker 잔존(B versioned `adapter_version`+real worker; pod PREPARE real Norman evidence; GU roster `full_var_order_sha256`↔response `gene_order_sha256`를 ResolvedRunSpec/execution-identity에 bind; clean-SHA 독립리뷰 + evidence 재생성). **seal 안 열림** | `specs/2026-07-11-compose-scientific-prepare-carrier-design.md`; `plans/2026-07-12-compose-scientific-prepare-carrier.md`; `specs/2026-07-07-compose-production-driver-design.md` |
| GU | outcome-free GEARS gene-roster generator (full response universe 보존 · M-first · exact `N_target` · alias · fail-closed) | ✅ **PASS — exact-committed-SHA 독립 리뷰 통과 → main 병합** — 커밋된 SHA `7f6595f`(branch `compose-gene-universe`, 4 commits off `68001fc`)를 **3개 독립 adversarial lens**(seal-safety/leakage/governance · correctness/logic · spec/test-adequacy)로 리뷰 → **0 Critical / 0 Important**. 유일한 non-APPROVE는 Minor 5건(전부 방어 분기의 test-adequacy이며 런타임 동작은 세 리뷰어가 확인); 4건은 guard별 negative test 추가로 종결(구현 `src/`·`scripts/`는 리뷰 SHA와 byte-identical, test 파일만 추가), 5번째(identity-alias)는 `:144` chain/cycle guard에 subsumed된 unreachable로 문서화. full compose suite green. verifier output(3개 리뷰 보고서 verbatim)+승격 근거는 committed audit `audits/2026-07-11-compose-gu-exact-sha-independent-review.md`; 이전 3회 working-tree 리뷰(`audits/2026-07-11-compose-gu-local-adversarial-review.md`, INVALIDATED)를 대체. **seal 안 열림.** | `specs/2026-07-11-compose-gene-universe-design.md`; `audits/2026-07-11-compose-gu-exact-sha-independent-review.md`; `runbooks/2026-07-11-compose-gears-decision-probe-rerun.md` |
| — | **pod sealed confirmatory run (opens seal once)** | ⛔ blocked — **development pod 선행 필요**(§2.2 real worker + §4 evidence 재생성 + §2.5 gate). C/C0/A/D 완료 | `runbooks/2026-07-02-compose-k562-pod-sealed-run.md` |

**GU review-status promotion rule:** `PASS`로 다시 올리려면 reviewed spec Git SHA, gate profile/iteration,
verifier verdict summary와 verifier-output SHA-256(또는 같은 내용을 담은 committed audit artifact)을 이
branch에서 추적 가능하게 기록한다. `LOCAL` ledger ID만으로는 이 sealed-readiness 인덱스의 PASS 근거가
되지 않는다.

## Critical path to seal

1. ~~C0 마무리~~ ✅ **done** (7/7 fixes, merged via C).
2. ~~C production driver fixture orchestration 구현~~ ✅ **done** — 단일 committed driver(`phase2a`/`preflight`/`phase2b --confirm-seal`/`recover`), synthetic fixture로 orchestration·fail-closed 전량 검증. Scientific ResolvedRunSpec/PREPARE carrier assembly는 ✅ 별도 구현·리뷰·main 병합 완료(C row); pod PREPARE 완성(real Norman evidence + B real worker)은 step 4에 남는다. *Gate PASS ≠ scientific verdict.*
3. ~~branch → main 병합~~ ✅ **done** (merge commit `1c46708`, 2026-07-09; whole-branch 리뷰 + Important 2건 fix; clean git tree 확보).
4. **development pod + PREPARE completion** — scientific ResolvedRunSpec/PREPARE carrier assembly는 ✅ 구현·리뷰·main 병합 완료(B 경계 fail-closed, seal 미개봉); 남은 것은 plan `plans/2026-07-09-compose-dev-pod-real-workers.md`에 따라 real workers + evidence를 완성하는 것이다. **GO resource identity는 해결됨:** v2 manifest가 Harvard Dataverse DOI/version/datafile roster/CC0-1.0/byte hashes를 고정한다. **pre-seal hardening + approximation-bias v1 LOCAL 코드는 ✅ 구현·리뷰·main 병합 완료**(merge `09065ee`, 2026-07-13): protocol-global scientific seal audit(`driver/seal_boundary.py`, §4.1 filesystem 강제), GI-secondary 정의 정정, 그리고 8-task #4 bias-metric(측정 스크립트 `compose_approximation_bias_report_v1` + one-way finalization tool `finalize_approximation_bias_config.py`(no report→config→report cycle) + verdict-invariant durable fairness carry(phase2b build-time, never ComposeSealedResult) + Phase-1-entry gate-decision record). 최종 opus whole-branch 리뷰가 2개 Important 통합버그(loader nesting·report-hash recipe, pod에서 seal 소각 잠재)를 잡아 수정+end-to-end round-trip 테스트 추가; full compose 1388 green; §4.3+config2+fit_role byte-불변; seal 미개봉. **남은 선행 gate(전부 POD):** GEARS/CPA published config·revision, conforming Probe A + reviewed output bridge, **real Norman에서 bias report 생성 + `sha256_file(report)`를 config에 finalize(real SHA→새 run identity)**, pod provider, fit-role-only smoke의 row-roster/zero-overlap/log/checkpoint 증거, package artifact hashes, immutable image digest. 현재 dependency lock은 runtime compatibility 관찰을 정직하게 `INCOMPLETE`로 기록하며 scientific guard가 이를 거부한다. §2.2 real `gears_worker`/`cpa_worker` + pinned env 구현·검증·commit; §4 activation-evidence를 **finalized active config로 real Norman data에서 재생성** + null requirement(config `power_status` · gears/cpa `environment_status`/`revision` · GEARS `approximation_bias_report_sha256`) 확립. Bias report는 final config SHA를 내장하지 않고 bias-null basis config SHA를 결속한 뒤 report SHA만 config에 단방향으로 채운다. ⚑ config 확정(null 채움 → 새 run identity) **후** evidence 재생성. real fit은 pod-only. *(현재 committed 분석 evidence는 pre-activation lineage이므로 §2.5 재생성 규칙이 적용된다.)* **2026-07-11 dev-pod probe**(`2026-07-11-compose-gears-decision-probe-results.md`)는 **QUARANTINED/NONCONFORMING**: 공식 one-time evaluation gateway는 소비되지 않았지만 Probe B prep가 dev role 확정 전에 전체 source `X`를 물질화하고 `U_full` 정규화 전에 gene subset을 만들었다. 따라서 기록된 Option 1 선호·`N_target≈2k`·coarse timing은 decision evidence가 아니다. 재실행은 `runbooks/2026-07-11-compose-gears-decision-probe-rerun.md`만 따른다. **GU**는 exact-committed-SHA(`7f6595f`) 3-lens 독립 리뷰 통과 → main 병합으로 **PASS**(seal 안 열림). 이후 pod-stage 순서: real candidate/GO/alias artifact → report mode(|M|) → exact candidate roster freeze → conforming Probe A → reviewed output bridge → Probe-B timing subcommand/반복 benchmark → owner 결정.
5. **§2.5 release gate** — worker locked-env integration green + 독립 검토 + **owner의 exact Git SHA 승인** → runbook을 `READY`로.
6. **A100 sealed-run pod: runbook 실행** — 유효한 `ActivationRecord`(requirement별 non-empty evidence) + clean tree 하에 `phase2a → preflight → phase2b --confirm-seal`. **COMPOSE seal 1회 개봉** — `TG-K562`와 독립.

## 이 문서가 *아닌* 것 (중복 금지)

- **governance / safety invariant / seal 규칙** → `CLAUDE.md` (§1 sources-of-truth, §3 invariants, §4 seal)
- **scientific claim 정의** → 각 sub-project **spec**
- **task 세부 · 체크박스 · 구현 순서** → 각 **plan**
- **exact split / threshold / seed / metric** → **config** (`configs/compose_k562_v1_phase2.yaml`)
- **시간순 audit trail** → **git log**
- **agent session-start recall** → private MEMORY (repo 밖)

<!-- maintainer note: index-only. 새 sub-project나 상태 전이 시 위 표의 '상태' 열과 critical-path만 갱신하고,
     Updated 스탬프(date @ commit)를 함께 바꾼다. 세부/claim/param을 여기에 복제하지 않는다. seal 개봉 시 frozen. -->
