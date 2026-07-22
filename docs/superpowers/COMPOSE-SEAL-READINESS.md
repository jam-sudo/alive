# COMPOSE-K562-v1 — Sealed-Run Readiness Index

> **역할:** COMPOSE sealed A100 run까지 남은 작업의 단일 human-facing 인덱스.
> **현재 상태:** lifecycle **ACTIVE** · execution **RELEASE-BLOCKED** · seal **UNOPENED**.
> **이 문서는 아무것도 정의하지 않는다** — 세부(task)는 plan, claim은 spec, exact param은 config,
> 시간순 audit는 git이 authoritative다([sources of truth](../../CLAUDE.md#sources)). 상태 행이 authoritative
> 문서와 어긋나면 **authoritative 문서가 옳다**; 이 인덱스를 갱신한다.
> **Updated:** 2026-07-22 @ `9969fb1` (branch `main`)
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
   **2026-07-14 hardening update:** 위 v1 병합 이력 이후 현재 계약은
   `compose_approximation_bias_report_v3`로 승격되었다. v3는 Probe-A admission/registration/verification
   provenance를 필수화하고, 모든 per-pair 파생 통계를 재계산하며, driver가 report를 한 번만
   읽은 immutable snapshot을 `run_phase2b`가 seal 전에 재검증한다. 따라서 pod에서 생성할
   신규 report와 ResolvedRunSpec은 v3 계약만 사용한다.
   **2026-07-19 Probe-A local production update:** commits `f62bd8c` and `589bc1b` implement the maintained
   `prepare/verify → build-probe-a-registration → probe-a → build-probe-a-report → build-evidence-manifest`
   write-once chain, canonical CSR float32 input boundary,
   separate preparation/GEARS lock identities with full installed-package-roster verification, actual clean-HEAD
   enforcement, and offline recomputation of matrix/row-role/sealed-overlap/reader-spy bindings. `589bc1b`
   additionally freezes the outcome-independent owner policy (`log_normalized_pseudobulk`, no second
   normalization, signed output preserved, exact determinism, `1e-5` numerical tolerances) and derives
   registration-v2's only run-specific scalar from the pinned prepared manifest. Local verification: full
   `tests/alive/compose` 1470 green, Ruff/format/diff clean. This satisfies the local implementation and owner-policy
   portions of conforming Probe A only. Pod measurement remains blocked until an independent exact-SHA review and
   the prepared-input-derived registration's external pin; it does not change `RELEASE-BLOCKED`, activate the
   scientific worker, validate the raw Jensen-floor metric, or open the seal.
   **2026-07-20 Probe-A graph/source correction:** the first conforming-pod attempt stopped before training or
   checkpoint publication when GEARS rejected `IER5L`; the failed evidence root is retained and is not eligible
   for promotion. Exact code commit `98bc2fe0a6e2dd65abc4f86e0ca4dfcf741bbb17` now makes `build-roster`
   independently compare the derived GO-node roster with the activation-pinned resource manifest and complete
   `gene2go_all.pkl` key set, requires that node artifact to remain inside the manifested evidence inventory, and
   freezes `perturbation_graph_policy=method_roster_intersect_gene2go` via upstream
   `PertData(..., default_pert_graph=False)`. This removes the unregistered legacy-essential symbol filter and
   aligns runtime composability with the existing canonical `var ∩ gene2go` contract. The independently
   follow-up commit `a568d0c` removes GEARS' implicit relative `./data/go_essential_<dataset>.csv` cache by
   computing in a private empty cwd with `make_GO(..., save=False)`; any relative cache artifact is fatal. This
   is a cache/provenance correction only and does not alter the GO similarity calculation.
   The independently
   pre-run-pinned offline-verifier source closure for this code is
   `23bff1ff50883dcbe034e88c297088452272cb9bb4228833c251d9d031c74756`; generator closure is
   `0f31e98a262901185efba973d9dcb27316e8ac86e6a8cd97c8933d025c35d536`. Owner policy bytes remain frozen at
   `bca70995117135367f3aadf77a551ba63b40fcbb426095611d0d63de7669a962`; the corrected run must derive a new
   registration bound to its final clean Git SHA and prepared manifest. Local verification: 79 core + 193
   focused/adjacent tests green; Ruff check/format and `git diff --check` clean. Seal remains unopened and the
   release state remains `RELEASE-BLOCKED` until the fresh pod evidence and offline verification pass.
   **2026-07-20 Probe-A direct-control correction:** a subsequent fresh-root attempt completed one 20-epoch fit
   and checkpoint, then stopped before raw publication because the instrumentation reused GEARS'
   `create_cell_graph_dataset_for_prediction`. That upstream helper always draws 300 controls with replacement,
   so it cannot supply the registered exact 1/8/300/301/400 prepared prefixes. The failed evidence root is retained
   and its command was not appended to the success-only ledger. The maintained direct path now uses the pinned
   helper's exposed single-cell constructor once per exact ordered prepared row, while public `predict` is left
   untouched. This preserves the preregistered test: public replacement-sampled output may legitimately fail the
   frozen first-prefix equivalence tolerance; neither owner policy nor observed values are changed. A new clean
   Git SHA, verifier-source pin, registration, and fresh evidence root are required before another fit.
   The correction is implementation commit `6a0d2776cc37da763b3c59c708c4c18af8b9e282`; its maintained Probe-A
   CLI SHA-256 is `692ad889fc019e295ee9178712ad4e970f3e3c5910035c8b86ee817d72f792ae`.
   The verifier closure is unchanged at the independently reviewed pre-run pin
   `23bff1ff50883dcbe034e88c297088452272cb9bb4228833c251d9d031c74756`; owner-policy bytes remain
   `bca70995117135367f3aadf77a551ba63b40fcbb426095611d0d63de7669a962`. The next registration must bind
   the final clean documentation commit containing this record, not the implementation commit alone.
   **2026-07-20 Probe-A repeated-fit correction:** the next fresh-root run completed fit 1, exact-prefix
   observation, and a 3.31 MB checkpoint, then stopped during fit 2 graph initialization before raw publication.
   The no-cache `make_GO` override had not been restored after fit 1, so fit 2 wrapped the override recursively
   and failed closed. The failed root remains quarantined and its `probe-a` command is absent from the success-only
   ledger. Commit `1a928b3fe63ff7c97d4c89c18c6fce2056f277fa` scopes the override to
   `model_initialize` and restores the exact original callable in `finally`; a same-process two-fit regression
   test now exercises this boundary. Worker SHA-256 is
   `716a70f3c86f1d0e51cbf46b54a1f73fd30d6cbb5bdcc67bc61b85a0918b2595`. Verifier and owner-policy pins remain
   unchanged. Another fresh root and registration bound to the final clean documentation commit are mandatory.
   **2026-07-20 Probe-A preregistered negative result:** the fresh run bound to clean commit `daff92d` completed
   both fits, published two byte-identical checkpoints, retained exact ordered per-control observations, and
   passed the zero-error determinism gate. It then mechanically rejected the frozen Option-1 bridge candidate:
   control-cap maximum absolute error `0.19060921669006348 > 1e-5`; public-vs-direct-first-300 bridge error
   `0.13841108322143558 > 1e-5`. Registration SHA is `771cbfd8…`, raw SHA is `ca9dbc16…`, and both checkpoint
   SHAs are `4b6c1e48…`. No tolerance, registration, public sampling, or transform was changed after observation.
   No canonical report/admission was published; the provider's immutable image digest was unavailable and was
   not guessed. Full identities, leakage checks, evidence-custody status, and disposition are recorded in
   `audits/2026-07-20-compose-probe-a-negative-result.md`. The scientific seal remains unopened. The
   `log_normalized_pseudobulk` exact-first-300 candidate is rejected; the named raw-pseudobulk comparator remains
   activation-blocked pending a separately reviewed representation/bias contract. Do not rerun this registration
   with altered parameters. The maintained local verifier now derives `pass|failed` from the three frozen gates,
   emits a hash-bound negative `verify.json`, and makes admission structurally absent on failure. This closes the
   negative-result software contract but does not retroactively complete the archived run or clear any activation
   blocker. That revision's now-retired verifier source-closure SHA-256 was
   `577c754dc72681aed8ad531ae3a3c2671a4c8cd11a1d941ee97ba44b5e4ff036`; it was never an operational image pin
   and must not be reused.
   **2026-07-20 Probe-A runtime-attestation hardening:** commit
   `d8e34bb10160e1825ed526097ce0cdbd141ab495` replaces ambiguous host CPU/RAM evidence with runtime-v3's
   separate provider-allocation, cgroup-effective, and host-visible views. It adds a write-once maintained
   `capture-runtime` command, rejects unlimited/malformed cgroup v1/v2 limits and allocation/GPU/image mismatch,
   and requires exactly one provider attestation plus its manifested raw control-plane source. Admission now
   requires the provider attestation SHA as an independent pre-run CLI pin; the verifier closure now includes the
   runtime producer driver and GEARS worker rather than only downstream validators. Focused/adjacent verification
   is 195 passing tests with Ruff check/format and `git diff --check` clean. The resulting candidate verifier
   source-closure SHA-256 is
   `54540ab4eb913a0fa82c4fb34ccdd2d8ddf27600fe309d990e6a31efa41eb760`; independent review is still mandatory
   before operational use. This hardening does not validate the archived negative run retroactively, authorize a
   new Probe-A registration, clear `RELEASE-BLOCKED`, or open the scientific seal.
   **2026-07-20 recursive-review correction (candidate, not operationally pinned):** the candidate implementation further
   upgrades runtime evidence to `compose_gears_probe_runtime_v4`; resolves cgroup CPU/memory from the current
   process leaf plus tighter ancestors; records a replayable network-namespace observation; rechecks loopback-only
   isolation plus captured cgroup/GPU identity before every stateful command commits its canonical ledger record;
   linearizes ledger append and manifest closure with a shared exclusive inode lock;
   independently binds the Probe-A CUDA determinism setting and `PYTHONHASHSEED` to the raw producer seed;
   validates recorded pod paths against their captured execution root without confusing them with the relocated
   offline-review path;
   rechecks the runtime-bound clean exact commit before and after every post-capture stateful command;
   binds preparation/verification commands, provider-assertion freshness, and the manifested `gene2go_all.pkl`
   bytes; and expands verifier closure
   to every `src/alive/**/*.py` decision dependency. Its pre-commit source-closure candidate is
   `4c36d77d07ea318e443503c5179f39de1dc95367a24aafa5cf5ecdbb7e848330`; the required local/adjacent contract
   roster passes 217 tests plus full Ruff check/format and `git diff --check`. The prior candidate pin is therefore
   retired for future runs. A clean implementation commit, full verification, recomputed pin, and independent acceptance
   are mandatory; this correction does not authorize a pod run or alter the archived negative result.
   **2026-07-20 upstream-custody/runtime-origin correction (candidate, not operationally pinned):** the next
   verifier revision archives the exact worker payload, fit-role H5AD, alias map, response projection, and selected
   roster as fixed manifest roles; derives `inputs.json`/role attestation from those bytes; and requires independent
   payload and selected-receipt pins. It binds the payload/approved-root/alias/roster paths across roster,
   preparation, verification, and measurement commands; rejects a truncated final JSONL record; includes all
   `src/alive` Python plus `pyproject.toml`, `uv.lock`, the Python executable identity, and the complete active
   verifier environment's installed distribution file bytes (not selected version labels alone) in
   the verifier closure; and rejects `PYTHONPATH`, user-site loading, or an unexpected module origin before ALIVE
   decision imports; an operational CLI invocation also computes and compares that byte-level closure before
   importing any ALIVE or scientific dependency. Authenticated private snapshots close pathname replacement races for prepared H5AD,
   fit-role H5AD, and checkpoint reads. Schemas advance to evidence-manifest v8, inputs v4, role-attestation v3,
   roster-receipt v3, and positive/negative verification v2. The previous `4c36…` pin is retired. The recomputed
   candidate closure pin is `dbcb8053a4c4310860792336542751f20c6176349debc85c11be157614204876`; the complete
   local Compose suite passes 1539 tests with one pre-existing AnnData warning, plus clean Ruff check/format and
   `git diff --check`. A clean commit and independent exact-commit/pin acceptance remain mandatory; no pod or seal
   authorization follows from this local correction.
   **2026-07-20 verifier root-of-trust correction (local implementation; image not frozen):** independent review
   established that Python self-hashing starts too late to authenticate `.pth` startup hooks, stdlib, loader, and
   native libraries. The operational verifier is therefore moved to a single-platform digest-qualified OCI image,
   with owner-canonical image lock, digest-qualified build images, signed canonical Cosign approval subject,
   pinned Cosign executable and trusted root, no-network/read-only/non-root runtime, one evidence-only writable bind, and positive/negative
   receipt schemas v3 that bind the verifier image digest and external image-lock SHA. The previous `dbcb…` value
   is retained only as a historical diagnostic candidate. An isolated Linux image builder—not a scientific pod's
   own root filesystem—must still build, sign, independently verify, preload, and owner-freeze the real image and
   external lock pin. Until that occurs this is
   **RELEASE-BLOCKED** and authorizes neither a Probe-A rerun nor any seal opening. The governing design is
   `specs/2026-07-20-compose-probe-a-verifier-root-of-trust-design.md`.
   **2026-07-21 separated-builder correction (build gate executed; signing gate blocked):** the isolated image
   path is now a two-dispatch GitHub Actions gate. The first exact-SHA Buildx/GHCR workflow has no OIDC permission
   and emits only a canonical externally pinned unsigned candidate receipt. The second downloads that exact run's
   receipt by run ID, requires its external SHA, independently re-pulls the digest and recomputes labels/closure on
   a fresh runner, then signs a canonical subject under a distinct GitHub OIDC identity. It preserves exact Cosign
   and trusted-root bytes but deliberately does not create the owner image lock. Both workflows are present on
   `origin/main` at `6d8f141b047be7b4a4c4cb08429d088bbfb729c4`. Build run `29837916921` succeeded and
   emitted unsigned candidate receipt SHA-256
   `5de6310259a8ee58ce75541790dbd8e99a42c91ba1e9ba26a5f813934575d9ae`, image digest
   `sha256:8fc740a39895dbbec6378b7b3ce70f88914f13c55afd44b62a3b0f7a9cfec117`, and verifier closure
   `07c139b896aab2f79147fe060441df41e78f83737948dda55e3aef4e30ec15fa`. The signing dispatch was
   **not** run because the required independently protected `compose-verifier-signing` approval gate could not be
   established under the current private-repository environment capability. The replacement contract requires a
   dedicated offline owner Ed25519 signature over the complete canonical candidate identity before the OIDC step,
   plus an externally registered owner-key fingerprint and a v2 lock that binds all approval evidence. This contract
   is implemented locally. **2026-07-22 offline owner-key registration:** the owner-generated, comment-free public
   key is registered at `configs/compose_probe_a_verifier_owner_approval.pub`; its independently recomputed
   fingerprint is `SHA256:74j8HDNk+/psRVtv31L7wQGPmTKGd827dEoujQua5IU` and its canonical public-key-file SHA-256
   is `2d23c87d551aff2b77ab3ff87b5f208465921fde50af3d39939654848a5a5831`. The private key is not repository
   evidence and must remain owner-controlled outside the repository, pods, GitHub, and transcript artifacts. Before
   operational use, the repository fingerprint must match the separately retained owner record. Every earlier
   candidate remains unsigned/historical and there is still no owner image lock, candidate-bound owner signature,
   or accepted external verifier pin. Status remains **RELEASE-BLOCKED**; a registered key or unsigned digest alone
   is never seal authorization.
5. **§2.5 release gate** — worker locked-env integration green + 독립 검토 후 exact commit `C`를 마지막
   repository commit으로 동결한다. Clean detached `C`에서 bias report → single-leaf finalized config →
   analytical reports를 external durable stage에 게시하고, owner가 `C`·모든 byte hash·immutable object
   version을 canonical ResolvedRunSpec과 publication manifest로 승인한다. Generated evidence/final config/
   READY 표기를 후속 commit하지 않는다(HEAD 이동 및 Git/report 자기참조 방지).
6. **A100 sealed-run pod: runbook 실행** — 유효한 owner-approved external ResolvedRunSpec,
   `ActivationRecord`(requirement별 non-empty staged evidence), staged finalized config와 clean detached `C`
   하에 `phase2a → preflight → phase2b --confirm-seal`. **COMPOSE seal 1회 개봉** — `TG-K562`와 독립.

## 이 문서가 *아닌* 것 (중복 금지)

- **governance / safety invariant / seal 규칙** → `CLAUDE.md`#sources, #invariants, #seal
- **scientific claim 정의** → 각 sub-project **spec**
- **task 세부 · 체크박스 · 구현 순서** → 각 **plan**
- **exact split / threshold / seed / metric** → **config** (`configs/compose_k562_v1_phase2.yaml`)
- **시간순 audit trail** → **git log**
- **agent session-start recall** → private MEMORY (repo 밖)

<!-- maintainer note: index-only. 새 sub-project나 상태 전이 시 위 표의 '상태' 열과 critical-path만 갱신하고,
     Updated 스탬프(date @ commit)를 함께 바꾼다. 세부/claim/param을 여기에 복제하지 않는다. seal 개봉 시 frozen. -->
