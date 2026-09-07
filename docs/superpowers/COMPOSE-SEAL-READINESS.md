# COMPOSE-K562-v1 — Sealed-Run Readiness Index

> **역할:** COMPOSE sealed A100 run까지 남은 작업의 단일 human-facing 인덱스.
> **현재 상태:** lifecycle **ACTIVE** · execution **RELEASE-BLOCKED** · seal **UNOPENED**.
> **kernel-isolation proof: STALE** — pending re-proof for `src/alive/compose/approximation_bias.py`
> (R1, `aed26aa`); Linux kernel-isolation CI re-run required (POD-GATED). Enforced by
> `tests/alive/compose/test_kernel_isolation_ci.py::_PENDING_REPROOF`.
> **이 문서는 아무것도 정의하지 않는다** — 세부(task)는 plan, claim은 spec, exact param은 config,
> 시간순 audit는 git이 authoritative다([sources of truth](../../CLAUDE.md#sources)). 상태 행이 authoritative
> 문서와 어긋나면 **authoritative 문서가 옳다**; 이 인덱스를 갱신한다.
> **Updated:** 2026-09-07 @ `13ba250` (branch `compose-factor-bank-normalization`)
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
   `compose_approximation_bias_report_v3`(v3, superseded 2026-09-07 → v4)로 승격되었다. v3는 Probe-A admission/registration/verification
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
   **2026-07-23 managed-pod isolation correction (working tree, not operationally pinned):** a standard RunPod
   preflight proved that `unshare --net` is unavailable without `CAP_SYS_ADMIN`/`CAP_NET_ADMIN`; no scientific
   command or evidence publication was attempted and that pod was terminated. Runtime v5 therefore retains the
   lo-only namespace proof and adds an exact `no_new_privs` + seccomp alternative that permits only endpoint-free
   `AF_UNIX socketpair` IPC, denies all `socket`/`connect` plus `io_uring_setup`/`pidfd_getfd`, restricts execution
   to the validated x86_64 ABI and an exact allowlist for privilege-bearing capability sets, and actively
   re-probes IPv4/IPv6/Unix
   stream/datagram denial at capture and every stateful command boundary. The launcher now passes a same-PID
   sealed-memfd receipt whose canonical bytes are embedded in command-record v2 and replayed by the offline
   verifier. Receipt v2 also fail-closes non-`-I`/import-loader overrides, arbitrary wrappers or interpreters, and
   cross-command Python/driver drift. Its live memfd check establishes continuity inside the trusted producer; the
   archived self-checksummed JSON is explicitly not represented as independent remote attestation. The collector
   and expected-policy SHAs bind the committed request; they are deliberately not
   called a kernel-filter read-back because Linux exposes no such unprivileged introspection. Governing design:
   `specs/2026-07-23-compose-managed-pod-network-isolation-design.md`. All earlier verifier/image/owner-lock pins
   are historical after this code change; a clean commit, fresh signed verifier image/owner lock, and independent
   review remain mandatory. Seal state remains **UNOPENED** and execution remains **RELEASE-BLOCKED**.
   **2026-07-25 kernel-property verification (supersedes the "outstanding" status recorded above):** the single
   test that establishes the kernel property is `skipif`-ed off non-Linux hosts, so it had never executed anywhere
   — every green result this project had recorded came from a developer macOS host reporting `1 skipped`, and no
   CI ran the suite at all. `.github/workflows/test-suite.yml` (commit `614017b`) now runs the full suite on
   `ubuntu-24.04`, asserts the runner is a real x86_64 Linux kernel, and fails unless that test actually executed.
   Run `30154404171` succeeded on `Linux 6.17.0-1020-azure x86_64`: **2336 passed, 1 skipped** (the remaining skip
   is `test_features.py` `importorskip("torch")`), with the kernel-isolation test **executed and passed**. IPv4/
   IPv6 and Unix stream/datagram denial, x32 denial, `io_uring_setup`/`pidfd_getfd` denial, and same-PID sealed-
   memfd receipt validation are therefore kernel-proven. This establishes that the seccomp policy behaves as
   specified on x86_64 Linux; it does **not** establish that any production pod is correctly configured, which
   still requires that pod's own `capture-runtime` evidence. It does not clear `RELEASE-BLOCKED`, substitute for
   the exact-SHA independent review, or open the seal. The downloaded JUnit SHA, workflow SHA, run/kernel/test
   identity and original artifact archive digest are now preserved in
   `docs/activation-evidence/compose/kernel_isolation_ci_614017b67e35e9cc07f68d5b512213d8356cf1b2.json`
   as historical proof profile `x86_64_seccomp_primitives_v1`; the expiring GitHub artifact is no longer the only
   review record.
   **2026-07-25 launcher-wiring/durable-receipt correction (working tree, not operationally pinned):** the Linux
   gate now additionally requires a real maintained launcher → `execve` → driver self-check, pre-existing
   `connect` denial, non-Unix `socketpair` denial, and inherited-FD closure. CI profile
   `x86_64_seccomp_primitives_and_launcher_wiring_v2` fails unless both exact Linux tests pass and emits a
   canonical receipt that must be independently archived in version control. The historical v1 archive cannot
   satisfy this stronger gate. A clean exact commit, successful v2 Linux run, durable v2 archive, fresh verifier
   image/owner lock and independent acceptance remain mandatory.
   **2026-07-26 v2 launcher-wiring verification (closes the v2 run and archive items above; the rest stand):**
   run `30200634662` at commit `2dd23d627fc0e31a7d5005a3e81ff20b8dcd9472` succeeded on
   `Linux 6.17.0-1020-azure x86_64`: **2346 passed, 1 skipped** (the remaining skip is the same
   `test_features.py` `importorskip("torch")`). Both profile-required tests **executed and passed** —
   `test_linux_policy_and_sealed_receipt_validate_in_the_active_process` (0.068 s) and
   `test_linux_launcher_executes_driver_self_check_end_to_end` (1.434 s) — so the maintained launcher →
   `execve` → driver self-check path is kernel-proven, which the v1 one-test roster never covered. The
   canonical receipt and its GitHub artifact (id `8631825177`, expiring `2026-10-24T11:42:20Z`) are preserved
   durably as proof profile `x86_64_seccomp_primitives_and_launcher_wiring_v2` in
   `docs/activation-evidence/compose/kernel_isolation_ci_2dd23d627fc0e31a7d5005a3e81ff20b8dcd9472.json`.
   **Scope:** `alive.compose.network_isolation` is imported only by `gears_probe_a.py`, the
   `gears_decision_probe.py` driver, and the `run_network_isolated.py` launcher; the phase2b driver,
   `run_spec`, and the seal boundary do not use it. This evidence covers the GEARS Probe-A driver path, not
   COMPOSE scientific execution generally. **Review standing:** the archive was built by subagents dispatched
   from the session that authored the workflow and triggered the run, and the end-to-end test was introduced
   in this same commit, so this run is its first and only execution — this is *not* the independent
   third-party review the v1 archive recorded, and the archive's `archived_by` field says so. Three latent
   receipt-builder weaknesses were found and are **unexploited here**: `rerunFailure`-class tags are not
   treated as failures, a `failure` element nested below a non-`testcase` parent is not seen, and
   `--workflow` is validated by path suffix only. All three are forged-input paths, inert under the current
   lock (no rerun plugin installed), and are hardening items rather than defects in this run's evidence. This
   does **not** clear `RELEASE-BLOCKED`, substitute for the exact-SHA independent review, establish that any
   production pod is correctly configured, or open the seal. A fresh verifier image/owner lock and independent
   acceptance at a clean exact commit remain mandatory. Seal state remains **UNOPENED**.
   **2026-07-26 receipt-builder hardening (branch `compose-ci-receipt-hardening`, not operationally pinned):**
   the three forged-input paths recorded in the entry above are closed. (1) Testcase outcome detection was a
   blacklist of three tag names, so a rerun plugin's `rerunFailure`/`flakyFailure` element and a `failure`
   buried under `system-err` both read as a pass; it is now an allowlist over the xunit2 vocabulary pytest
   actually emits, nested elements under those children are refused, and every testcase must be a direct child
   of the single testsuite. (2) `--workflow` accepted any path ending in the canonical suffix; the file must
   now be a real Git worktree's canonical workflow and byte-identical to the blob that `--head-sha` records at
   that path, which removes "any file anywhere" from the trust base but still does **not** prove GitHub
   executed that workflow — only Actions' own execution integrity does. *(The "trust base" phrasing here is
   narrowed by the adversarial-review entry below: it does not make a receipt harder to fabricate.)* Every
   new negative test was checked
   against the pre-fix builder and fails there; one acceptance test guards the opposite direction, that the
   allowlist does not start rejecting real pytest output. The archive published at `ccc5a2e` stays
   reproducible: rebuilding its receipt from the downloaded run-`30200634662` JUnit under the hardened builder
   still yields `a6e6c024…a06b`. This is a development-boundary correction with no config, lineage, or
   evidence mutation; it does not clear `RELEASE-BLOCKED` or open the seal, and independent review at a clean
   exact commit remains mandatory. Seal state remains **UNOPENED**.
   **2026-07-26 adversarial review of that hardening (same branch):** two independent reviews of the pushed
   commit returned APPROVE-WITH-FINDINGS, and four findings were material enough to fix rather than record.
   (1) The git helper inherited the process environment, so `GIT_DIR`/`GIT_WORK_TREE` made a directory that is
   not a worktree answer as one — the "real Git worktree" property was defeated by an environment variable.
   This was not hypothetical: a reviewer exercising it wrote a commit into the working checkout, because the
   test fixtures had the same weakness. Both the production helper and the fixtures now run git with the
   `GIT_*` namespace stripped, so only the path argument selects a repository. (2) `<testsuite>` children were
   unvalidated, leaving the same class of hole one level above the one just closed. (3) A mode-`120000` tree
   entry was read as a workflow, yielding a receipt for a symlink GitHub would never execute; the entry must
   now be a regular-file blob. (4) The claim that the binding raises the bar against forged receipts was too
   strong and is withdrawn: anyone holding the repository can still produce a valid receipt for a real commit
   with the genuine workflow hash, because `repository`, `run_id` and the runner fields are self-declared. The
   binding only stops `workflow_sha256` from naming a workflow the commit never contained. **Reproducing an
   archived receipt now requires checking out that commit** — rebuilding run-`30200634662`'s receipt from a
   worktree at `2dd23d6` yields `a6e6c024…a06b`, while the same command at a later tip fails with *"workflow
   differs from the blob recorded at the commit under test"*, which a verifier must not misread as tampering.
   Known and deliberately unfixed: a JUnit truncated to only passing cases still reconciles, because the
   receipt does not attest suite size — that property is carried by the pinned workflow content, not the
   schema. Seal state remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.
   **2026-07-26 review of those fixes (same branch):** a third review confirmed the three fixes close what
   they claim, that each new negative test fails against the commit before its fix, and that the recorded
   "18 failed → green under a hostile `GIT_DIR`" figure reproduces exactly. It found the markup guard still
   stopped one level short — suite-level `properties`/`system-out` contents and the report root's own children
   were unvalidated — and that `head_sha` was never required to name a commit, so a 40-hex *tree* satisfied
   both `ls-tree` and `cat-file`. Both are now closed by one child-validation rule applied at root, suite and
   testcase, plus an explicit commit-object check. It also caught the environment fix repeating the very
   overclaim the entry above withdraws: stripping `GIT_*` makes the call environment-independent, **not**
   unspoofable, because `PATH` still selects the `git` binary — a shim on `PATH` defeats it with no `GIT_*`
   set at all. The docstring now says so. Confirmed not broken by the strip: `actions/checkout` writes
   `safe.directory` into `$HOME/.gitconfig` by argv, not through `GIT_CONFIG_*`, so it survives; a container
   image that carried it via `GIT_CONFIG_COUNT` would not, which this job does not use. Seal state remains
   **UNOPENED**; execution remains **RELEASE-BLOCKED**.
   **2026-07-29 v2 archive provenance, binding, and the falsifiability clock:** the committed v2 archive was
   re-derived from primary bytes, and the "review standing" caveat above **understates** the receipt's
   provenance. The receipt embedded in the archive equals, field for field, the
   `kernel-isolation-ci-receipt.json` inside GitHub artifact `8631825177`, which the workflow itself builds on
   the runner (`test-suite.yml` invokes the builder with `--output kernel-isolation-ci-receipt.json`) and
   uploads beside the JUnit. (The builder compares the two as dicts, and the archive's `receipt_sha256` is a
   canonical-JSON digest while the CI file is written indented — so "byte-identical", used in an earlier version
   of this entry, is the wrong word for a value equality that no byte comparison would pass.) The archiving
   session therefore transcribed a receipt the CI job produced rather than authoring one. That narrows the trust
   base by removing hand-transcription of the receipt BODY; it does **not** remove workflow authorship, which
   the same session holds, so Actions' own execution integrity remains what backs the run. It also does not
   cover the wrapper: `artifact_id`, `artifact_name`, `expires_at_utc`, `archived_at_utc` and `archived_by`
   remain hand-supplied archiver arguments — including `expires_at_utc`, which the clock argument below rests
   on. And it does not transfer to v1: the workflow at `614017b` had no receipt step, so the
   independently-graded archive's receipt **is** hand-authored, the opposite of the property credited here. Verified against the live
   artifact: run `30200634662` conclusion `success`, `head_sha` `2dd23d6…`, `run_attempt` 1; artifact zip
   SHA-256 `1707a4dc…22ad` = `source_artifact.archive_sha256`; `junit.xml` SHA-256 `77c0262a…b84f` = both
   `junit_sha256` fields; `sha256_json` of the CI receipt = `receipt_sha256` `a6e6c024…a06b`; and both roster
   tests present in the JUnit as passes at the recorded 0.068 s / 1.434 s, inside a suite of 2347 with 0
   failures and 0 errors. This re-verification was performed by the same authoring lineage and is **not**
   independent; its value is that the evidence is still recoverable and internally consistent, and that the
   exact coordinates a third party would need are now recorded. **The open question is not the grade but the
   clock.** While the artifact lives, `archived_by` is nearly irrelevant, because anyone with repository read
   access can refute the archive by repeating the above; once it expires the JSON is the sole record,
   unfalsifiable, and the grade becomes the entire trust basis. Actions retention here is 90 days, so the
   **v1** artifact — the one carrying the independent grade — expires `2026-08-08`, and the **v2** artifact
   expires `2026-10-24`. **Correction (independent review):** an earlier version of this entry attributed both
   dates to a single 90-day repository retention, which cannot produce v1's (2026-07-25 + 90 d is 2026-10-23).
   The dates are right, the mechanism was wrong and generalized from the v2 measurement alone: the workflow at
   `614017b` uploaded with `retention-days: 14`, and `2dd23d6` changed it to 90. **Owner-approved resolution,
   as corrected.** Repository Actions retention was raised 90 → 400 days, which measurably did **not** move
   either existing artifact's expiry — both were re-queried afterwards and are unchanged. Raising it alone also
   protected no FUTURE run, because the workflow hard-coded `retention-days: 90` on the upload step and an
   explicit per-upload value overrides the repository setting downward; that line is now `400`, so the claim
   that the raise protects the seal-backing run is true only from that fix forward. The primary
   bytes were therefore downloaded while both artifacts were still live and committed beside their archives as
   `kernel_isolation_junit_<head_sha>.xml` (v1 `f3f68e01…5826b` from artifact `8618766602`, v2
   `77c0262a…b84f` from `8631825177`); a parametrized test re-derives each receipt's whole `junit` block and
   required-testcase roster from those committed bytes through the builder's own parser. **Scope, corrected.**
   "Both archives stay reproducible from committed data" was too strong and is withdrawn. What the committed
   bytes establish permanently is the `junit` block, the required-testcase roster, and — via a second new test
   reading `git cat-file blob <head_sha>:<workflow>` — `workflow_sha256`. The committed JUnit carries **no
   runner identity at all**: zero occurrences of `Linux`, `6.17.0` or `azure`, and no head SHA; its only runner
   trace is `hostname="runnervmvrwv9"`. So `runner.os`, `runner.architecture`, `runner.kernel_release`,
   `head_sha`, `run_id`, `run_attempt` and every `source_artifact` field remain unfalsifiable from the
   repository once the artifact expires — and those are exactly the fields carrying the claim "these two tests
   executed on a real x86_64 Linux kernel at commit X", which is the whole point of the proof. **This makes the
   independent review grade MORE important than the entry below concluded, not less**, because after expiry the
   grade is the only thing standing behind precisely those fields. The honest property of the committed bytes is
   tamper-evidence and reproducibility of the parts they cover, not falsifiability of the archive as a whole.
   One thing checked and cleared: the validator compares only recorded fields (no `datetime.now` anywhere in
   `src/alive/compose/`), so the committed archives do **not** start failing when their artifacts expire; the
   side effect is that `archived_at_utc` is bounded above only by a self-declared field, so an archive assembled
   later can backdate itself into a closed window and pass. The archive is now bound by tests, which
   nothing previously did for the v2 file:
   its digests and launcher roster are pinned, and `archived_by` — free text that no validator constrains
   beyond non-emptiness, and the only field separating v1's independent review from v2's self-review — is
   pinned to its honest wording, so a grade cannot be upgraded silently. The v2 archive's own grade stands as
   recorded, by owner decision: retrofitting an independent grade onto a transitional artifact buys less than
   requiring one on the archive that will actually back the seal, so the kernel archive is now an explicit
   runbook §2.5 release-gate item — it previously was not, that gate's independent-review line covering only
   leakage, exact roster, response projection, pair alignment, single seal open and final-ledger recovery.
   **Correction (independent review): the impossibility argument this entry originally used is unsound and is
   withdrawn.** It claimed an archive at exact SHA `C` cannot exist because archiving a receipt takes a commit
   that moves HEAD past `C`. But §2.5 and this index already prescribe the construction that defeats it, for the
   analytical reports: publish to the **external durable stage** under the approved-artifacts root instead of
   committing, and have the owner approve `C` plus every byte hash and immutable object version. HEAD then stays
   at `C` and the binding holds. Nothing requires this archive to be in-repo — it is not among the config's
   `activation_requirements`, and `_CONFIG_BOUND_EVIDENCE_REQUIREMENTS` contains only the two analytical
   reports. So a run at `C` archived externally is achievable, and it is the strong form of the gate; a weaker
   one was adopted on a false premise. The gate now requires an independent `archived_by`, committed or durably
   published primary bytes, and — where the archive's `head_sha` precedes `C` — byte-identity of the isolation
   closure between that commit and `C`. **That enumeration was also incomplete** and is corrected: beyond
   `network_isolation.py`, `run_network_isolated.py`, `gears_decision_probe.py`, `gears_probe_a.py` and
   `test_network_isolation.py`, the transitive `alive` import closure adds `provenance.py` (every receipt
   checksum), `io.py`, `roles.py`, `response.py`, `fit_role.py`, `gene_universe.py` (the self-check's exception
   branch), `worker_bundle.py`, `activation_evidence.py`, `approximation_bias.py`, `baseline_subprocess.py` and
   `baselines_combo.py`, plus the interpreter axis (`.python-version`, `uv.lock`, and `requires-python`) that
   the tests' syscall-level assertions depend on. The whole corrected closure is byte-identical between
   `2dd23d6` and current `main`, so the v2 kernel property still covers today's isolation code even though the
   workflow and receipt builder have since changed (which is why the archived receipt reproduces only from a
   worktree at `2dd23d6`). That identity was asserted in prose only, which meant editing a closure file left the
   suite green while this entry went on claiming the proof applied; it is now enforced by a test that fails
   closed and tells the reader to re-establish the evidence rather than delete the check.
   **2026-07-30 corrections to the entry above, from a second review round on the corrections themselves.**
   (1) **The "strong form preferred" gate was not executable and is withdrawn.** Withdrawing the impossibility
   argument was right, but the replacement was not: the owner-approval carrier has no slot for the archive's byte
   hash — `run_spec.py`'s `_SCIENTIFIC_BLOCK_KEYS` is a six-key exact roster that raises on any extra, and
   `carrier_loader.py:447` requires `activation_evidence.requirements` to equal `config.activation_requirements`
   exactly — so adding one means editing the config, whose commit moves HEAD past `C` and reinstates the same
   circularity a level up. `publication_manifest` has no implementation at all. An externally published archive
   also gets neither `validate_kernel_isolation_ci_archive` nor any test, so the committed path is the only
   machine-checked one. The runbook now records a `head_sha == C` archive as an **unresolved owner decision**
   rather than a preferred path. (2) **The closure enumeration was still incomplete** — both package
   `__init__.py` files were missing, and `alive/compose/__init__.py` is the one importer node from which growth
   could hide, being a PEP-562 lazy-import gate that exists to keep the subprocess workers off the Phase-1
   stack; the exact mutation a review said went undetected now fails. (3) **2026-07-30 correction:** `uv.lock`
   is included in the pin after all. The proof runs after `uv sync --locked`, and the probe driver the launcher
   execs (`scripts/compose/gears_decision_probe.py`, module-scope `anndata` / `numpy` / `pandas` / `scipy.sparse`
   at lines 100-103) pulls the numeric stack in under the seccomp filter, so the resolved dependency graph is
   part of what passed even though the lock does not identify the CPython build. (`run_network_isolated.py`
   itself imports only the standard library; an earlier draft of this entry attributed those imports to the
   launcher.) This is an intentional conservative superset: a dependency-only change requires a fresh proof.
   **Operational cost, stated so it is not discovered at the wrong moment:** any `uv sync` that rewrites
   `uv.lock` — including a routine dependency refresh — turns the closure test red until a fresh Linux
   kernel-isolation CI run is archived and the pin moved to it. The test says so and says not to delete the
   check; budget the re-archive rather than the deletion. **Open item [CLOSED 2026-08-12 — see the L4 entry at
   the end of this file]:** record the actual interpreter in the
   receipt schema; `.python-version` is a minor series and identifies no patch release. (4) **The three history-reading tests would have failed on CI and
   taken the kernel gate down with them.** The workflow checked out at `fetch-depth: 1`, where the commits the
   archives name do not exist; they pass on any full clone, which is why local green did not catch it. Worse, the
   receipt-build step had no `if:`, so a failing suite skipped it and the upload then failed closed — the only
   kernel-property gate this project has would have gone permanently red and stopped emitting evidence. Checkout
   is now `fetch-depth: 0`, and those tests carry a `repo_history` marker: deselected from the receipt-producing
   run and executed after the upload, because the receipt requires a zero-failure JUnit and one of them fires
   exactly when the archived evidence has gone stale — leaving the check self-blocking, with deletion as the only
   way to produce the evidence its own failure message demands.
   **2026-07-30 NEW BLOCKER — the exit-code contract is incomplete beyond the estimator.** Closing the
   `id_only` singular ridge completed the `.fit` axis (only two `.fit(` call sites exist in `src`; L1 goes
   through `identify_operator`, L2 delegates to L1, L3 performs no solve, `id_only` is now normalized), but the
   declared sibling sweep stopped there. Review enumerated the rest of the same `phase2a` path and verified by
   monkeypatching the real `main()` that each still propagates to a **traceback and exit 1**, outside the
   registered 0/10/20/30 contract and outside the one-line-stderr output discipline: `HashMismatchError`
   (stale/tampered factor bank or response artifact), a bare `ValueError` from `_validate_config_contract`
   (drift between `phase2a_inputs.json` and the pinned config — note `phase2a.py:1416` is present but
   unreachable; the reachable site is `:678`), **`BaselineUnavailable`** (a GEARS/CPA worker exiting non-zero —
   arguably the likeliest real pod failure), the seed-variability family on the CONTINUE path,
   `OutcomeLeakageError` (the project's highest-severity guard, its rejection path uncontracted), `LeakageError`
   from the measurability gate (not even a `ValueError`, so no broad handler sees it), `FreezeError`, and
   `Phase2ConfigError`. The spec and runbook define `main`'s returns TOTALLY as 0/10/20/30; the
   "propagate an unrecognised exception" carve-out exists only in `cli.py`'s docstring. On the pod an operator
   receiving exit 1 cannot distinguish a documented pre-seal rejection from a driver bug. **Deliberately not
   fixed here:** admitting eight types into the roster is a change to the registered exit-code contract and
   needs its own scoped design, spec update and review, not an append inside a guard fix. Related latent item:
   `select.py`'s per-candidate `except SingularDesignError` is keyed to the exception TYPE, and OOF selection is
   bound to L1 only by a hard-coded map that nothing asserts — if a non-L1 factory ever reaches
   `select_hyperparams`, a singular comparator would be recorded as a non-viable hyperparameter candidate. Not
   reachable today; assert the binding when that roster becomes configurable.
   **2026-07-31 addendum — the 2026-07-30 solver replacement widened this blocker's surface.** The new input
   guards in `identify_operator` (non-2-D/empty `Z`, misaligned `eps_obs`, non-finite `Z`/`eps_obs`) and in
   `IDOnlyModel.fit` (invalid `lam`, non-finite factors/targets, misaligned targets) raise a BARE `ValueError`,
   which is neither a `SingularDesignError` nor covered by any other roster entry, so they land in exactly the
   traceback-and-exit-1 hole enumerated above. This is a widening of the recorded blocker, **not a new defect
   and not an inconsistency in the new code**: the module's convention is that an INPUT-contract violation is a
   bare `ValueError` (as the pre-existing `lam must be finite and non-negative` has always been) while a
   non-finite DECOMPOSITION or ESTIMATE is a `SingularDesignError`, and the new guards follow it. They are also
   defense-in-depth for conditions rejected upstream — `deserialize_factor_bank_collection`'s
   `_validated_factor_array` and `_verify_factor_banks` both reject a non-finite factor bank before Phase 2a —
   and exit 1 is not a contracted success, so the path fails closed. Deliberately **not** remapped here for the
   same reason the eight types above were not: choosing the type and exit code for these is a change to the
   registered exit-code contract. Fold them into that scoped design rather than appending a mapping.
   Seal state remains **UNOPENED**; execution
   remains **RELEASE-BLOCKED**.
   **2026-08-01 — the exit-code blocker above and its 2026-07-31 widening are CLOSED.** The scoped design the
   two entries asked for was done as a spec amendment plus a mechanically-enumerated roster, not as an append.
   Four owner decisions were registered first: leakage keeps exit `10` and the severity distinction moves to a
   runbook exception-name table (D1); the condition ceiling is registered at `1.0e8` on `rank_diagnostics(Φ)`
   (D2, not yet implemented — that is the next wave); the uniform-scale "immaterial λ" band is recorded as a
   registered limitation rather than invented as a criterion (D3); the receipt's interpreter identity is done
   now (D4). Plan: `plans/2026-08-01-compose-pre-pod-local-closure.md`.
   > **[2026-08-12 wording correction.]** "the receipt's interpreter identity is done now (D4)" records the
   > **decision** — *do it now* — and was written before any code existed. Read as a completion claim it was
   > false for eleven days: the receipt schema stayed `..._v1` with a runner block of `os`/`architecture`/
   > `kernel_release` and no interpreter anywhere. It became true on 2026-08-12; see the L4 entry at the end of
   > this file. A decision and its implementation are separate states and this document should not spell them
   > the same way.
   **The contract is no longer stated as total.** Driver design spec 1.1 now registers exit `1` as the
   uncontracted-driver-bug escape — full traceback on stderr, stdout empty, blind retry forbidden — because the
   carve-out previously existed only in `cli.py`'s docstring while the spec and runbook described `main`'s
   returns as totally 0/10/20/30. It also registers the ADMISSION RULE, which is what the earlier entry's
   "admit eight types" framing got wrong: `src/alive/compose` raises a bare `ValueError` in **218** places,
   nearly all of them internal-invariant violations, so admitting the builtin — or wrapping a whole library
   call in `except ValueError` — would report unclassified BUGS as documented pre-seal rejections. Only typed
   classes defined under `src/alive` may enter the roster. The contracted raise sites were therefore TYPED
   first: 28 of `phase2a.py`'s 29 bare-`ValueError` sites became `InputContractError` (PREPARE-supplied
   artifact structure/alignment) or `ConfigContractError` (runtime-vs-preregistration drift). The 29th
   (`model_factories` missing the headline model) stays bare on purpose — `_validate_config_contract` shadows
   it because `config2` pins the ladder to start at `l1_bilinear_identifiable`, so reaching it means an
   internal invariant broke, which the registered classification calls a BUG. `carrier_loader`'s
   `Phase2aInputs` construction is wrapped narrowly (untrusted-payload deserialization only) with typed
   rejections re-raised FIRST, so a leakage rejection is never re-labelled as a `RunSpecError`.
   **The enumeration is mechanical, because hand-enumeration has failed twice here** (this roster, and the
   kernel-isolation closure). All **72** exception classes under `src/alive` are now classified
   `PRESEAL_REJECTION` / `POSTSEAL` / `BUG` / `UNREACHABLE_FROM_DRIVER` with a one-line justification each, and
   the tests fail closed both ways: an unclassified new class, and a `PRESEAL_REJECTION` no roster entry
   catches. Reachability is computed from a STATIC AST import graph, not a `sys.modules` probe — the probe
   misses `config2`'s function-local import of `activation_evidence` and would have called it unreachable — and
   a test asserts the static graph is a superset of what a FRESH interpreter loads (64 modules ⊇ 59; empty
   difference — the static side deliberately over-approximates, counting the PEP-562 lazy-export gate's
   targets, which an import never triggers). The roster grew from **15 to 41** entries, covering **43** classified `PRESEAL_REJECTION`
   classes (two are reached through a base: `UnsupportedModeError` via `RunSpecError`,
   `ApproximationBiasReportError` via `Phase2bError`). Each classified type, injected **at the CLI dispatch
   seam**, produces the contracted exit code, exactly one stderr line, and an empty stdout across all four
   subcommands (172 parametrized cases); an unclassified exception propagates with stdout still empty. Note
   what that injection does and does not show: it pins the catch/report/exit mapping, **not** that each type is
   genuinely pre-seal at its real raise site. Dropping a roster entry, and the base-class swallow described
   below, are both mutation-verified to fail.
   **One structural fact made this safe to do at all:** `phase2b_cmd` already branches on
   `_seal_consumed(audit_path)` — filesystem evidence, not the exception type — returning `30` when the seal
   was consumed and re-raising otherwise. So widening the roster cannot mislabel a consumed seal as a pre-seal
   rejection. **The `recover` semantic was NOT merely recorded — it was corrected (see the review entry
   below).** Also closed: `select.py`'s latent OOF↔L1 binding, now asserted at the `SingularDesignError`
   handler — the only point where a non-L1 estimator's singular design would be misrecorded as a non-viable
   hyperparameter — rather than at entry, so known-answer stubs still work. Seal state remains **UNOPENED**;
   execution remains **RELEASE-BLOCKED**; nothing here authorizes a run.
   **2026-08-01 independent adversarial review of the entry above, and the corrections it forced.** Three
   independent reviewers read the committed branch tip under distinct lenses (seal-safety/leakage/governance;
   classification correctness; test adequacy), read-only, against a `git archive` snapshot rather than a
   moving working tree. Verdict: **0 Critical on seal safety**, but **1 Critical on the mechanism itself** plus
   several classification and documentation defects — most of them introduced by the wave, not pre-existing.
   Reviewers disagreed on one point and the disagreement was resolved by reading the code, not by preferring a
   reviewer: `TerminalError` DOES escape `recover` unwrapped, via
   `recover_cmd` → `recover_phase2b_durable_outputs` → `finalize_phase2b_durable_outputs` →
   `_assert_no_raw_outcomes`; the wrap one reviewer cited covers `recover_aborted_after_seal`, a different call.
   **Corrections applied.** (1) **`recover` now returns `30`, not `10`.** Exit `10` asserts "the seal was NOT
   consumed" and `recover` runs only on a run whose seal may already be burned; two of its rejections are
   reachable *only* post-seal (`run_dir_state` on two terminal artifacts; the `TerminalError` path above).
   `recover_cmd` already mapped the one type it catches itself to `30` = "durable export incomplete", so this
   makes the wrapper agree with the subcommand. The stderr line is unchanged. (2) **The classification table
   was missing its contrapositive** — nothing asserted that a `BUG`/`POSTSEAL` class is NOT caught by the
   roster, so a one-token base change (`NoTerminalWritten(TerminalError)`) made a BUG sentinel report as a
   documented rejection with every test still green. Now asserted and mutation-verified against that exact
   attack. (3) **`metric2.MetricError` was misclassified `POSTSEAL`**; it is reachable pre-seal from `phase2a`
   via `select.py`'s OOF theta call, whose handler catches `SingularDesignError` only, through `diagnostics2`
   (no `except` clauses at all). Reclassified and admitted. (4) **Four justification strings asserted things
   the code contradicts** (`ComposeSealingError`, `Phase2bError`/`ApproximationBiasReportError`,
   `TerminalError`) — each is saved in effect by `_seal_consumed`, not by the stated reason — and
   `BootstrapError` was `POSTSEAL` when COMPOSE imports only a helper that raises nothing. The table's value is
   its reasons, so all five were corrected. (5) **The `_LAZY_EXPORTS` branch was dead code**: the assignment is
   an `ast.AnnAssign`, which `ast.Assign` never matches, so the documented PEP-562 safeguard did not exist.
   (6) **Discovery rested on a hand-written 9-name seed**, so `class X(FileNotFoundError)` would never have been
   discovered and never required to be classified — the exact hand-enumeration failure this file exists to
   prevent. It now fails closed on any unresolved base name. (7) **The loader's stated re-raise ordering had no
   test**; deleting the clause changed no exit code and no stderr shape. Now pinned and mutation-verified.
   (8) Enumeration counts are pinned, the runbook operator table was re-bucketed (a `RunDirStateError` on
   `phase2b` reads as "delete `audit.jsonl` and the terminal, then re-run" under the old bucket C wording), and
   the overclaimed prose above was narrowed. **Recorded, NOT fixed here, and each needs its own scope:**
   `_seal_consumed` fails open on an `OSError` from `Path.exists` and has a TOCTOU inside its own handler
   (`phase2b_cmd.py` is a `CLAUDE.md#enforcement` guard file); `_reread_durable_commit` can raise `KeyError`/
   `OSError` post-seal and exit `1` where `30` is the registered signal; `identify.py:150` still raises a bare
   `ValueError` for a non-finite factor bank, an operator-facing PREPARE rejection that exits `1`; and two
   `OutcomeLeakageError` raise sites are self-declared internal-invariant violations, so a BUG reports as a
   contracted rejection. What the reviewers tried and could NOT break: the claim that widening the roster
   cannot mislabel a consumed seal, for `phase2a`/`preflight`/`phase2b`. Seal state remains **UNOPENED**;
   execution remains **RELEASE-BLOCKED**.
   **2026-08-01 re-review of those corrections (mutation-executed, not read-only).** A second independent
   round re-ran the first round's attacks against the fixes. **Closed and mutation-verified:** the
   contrapositive (five variants, including a new class added WITH its table entry and the pinned counts
   bumped — it still fired), and the pinned counts (dropping a roster entry fails six tests). The `recover`
   change is pinned end to end: reverting it fails 45 cases, including two real-CLI tests, not just table
   lookups. **Fixed in response to this round:** a class under `src/alive` whose NAME collides with a builtin
   exception was silently dropped from discovery — unclassified, invisible to the contrapositive, yet still
   caught by the roster — now failed on at the source; the `AnnAssign` repair had no regression test, so
   reverting it left the suite green, now pinned; the loader-ordering test pinned only one of the clause's two
   arms; `ComposeSealingError`'s replacement justification traded one inaccuracy for another (it is raised both
   pre- and post-claim); and the runbook's `TerminalError` message claim, its "recover 실패는 전부 durable
   export 미완료" flag, and `main`'s public `Returns` docstring were all corrected. The runbook's bucket C also
   still sanctioned deleting `phase2a`'s own write-once outputs — its entry roster requires an EMPTY `run_dir`,
   so after a CONTINUE the "condition to fix" is the frozen bundle, run ledger, OOF manifest and
   seed-variability report; the protected list now covers every run-produced write-once artifact and says a
   non-empty `run_dir` is a new-run-identity signal, not a cleanup target.
   **NEW Important, recorded and NOT fixed here — `phase2b` has the same defect `recover` just had.**
   `phase2b_cmd` runs `assert_run_dir_roster(run_dir, "phase2b")` at step 0, BEFORE the
   `except Exception`/`_seal_consumed` wrapper, and the phase2b entry roster forbids terminal and audit
   artifacts. So a leftover `phase2b_complete.json` — itself proof that a seal WAS consumed — raises
   `RunDirStateError`, reaches the CLI, and returns exit `10`, "the seal was NOT consumed". That is the exact
   argument used to move `recover` to 30, unapplied to the subcommand a real scientific run will actually hit,
   and it falsifies the "an exception reaching the CLI from phase2b is pre-seal too" reasoning the
   classification module states. It is deliberately not fixed in this wave because the correction belongs in
   `phase2b_cmd.py`, a `CLAUDE.md#enforcement` guard file, and guard changes must not ride along inside a
   contract-tidying wave; it is queued with the four items above for the owner-approved guard branch. The
   runbook already routes this case to "stop and report". Two accepted residuals: a class created by `type()`
   or with a computed base is still invisible to discovery, and the static graph's over-approximation moves two
   classes from machine-checked to justification-only. Seal state remains **UNOPENED**; execution remains
   **RELEASE-BLOCKED**.
   **2026-08-02/03 — the four recorded residuals are closed (owner-approved guard work).** All four items the
   2026-08-01 entries listed as "recorded, NOT fixed here" are done on a separate branch, deliberately kept out
   of the contract wave because two of them edit `CLAUDE.md#enforcement` guard files. Three shared one failure
   DIRECTION: given absent or ambiguous filesystem evidence they concluded the seal was NOT consumed, which is
   the single answer that puts a false statement about a one-shot seal into an operator's hands. The directions
   are not symmetric — guessing "consumed" costs a `recover`, guessing "not consumed" invites a retry on a
   burned seal — so all three now fail CLOSED. (1) `_seal_consumed` was
   `audit_path.exists() and audit_path.stat().st_size > 0`; `Path.exists()` SWALLOWS `OSError`, so an audit
   that was merely unreadable (EACCES after a remount, ESTALE on an NFS-backed approved root, EIO, EMFILE) read
   as "nothing consumed" and a post-seal exception was re-raised as exit `10`. Only `FileNotFoundError` may now
   be read that way, and the single `stat()` also closes the TOCTOU where the file vanishing between `exists()`
   and `stat()` raised `FileNotFoundError` from inside the caller's own `except` block, replacing the original
   exception. (2) `phase2b`'s step-0 roster check runs before that wrapper and the roster FORBIDS a terminal,
   so the artifact proving consumption was the artifact tripping the check; step 0 now decides on the same kind
   of evidence the dispatch does — terminal present ⇒ `30` and point at `recover` — and a roster violation
   WITHOUT a terminal still raises, with the widen-to-everything mutation caught. (3) step 6's handler caught
   only `Phase2bSubcommandError` while `_reread_durable_commit` reads the marker and every file it records, so
   a missing `filename`/`sha256` entry (`KeyError`) or an unreadable recorded file (`OSError`) escaped as exit
   `1` where `recover` is the operator's next action. (4) `identify.py`'s non-finite/misshapen input rejections
   are now `EstimatorInputError` and rostered: nothing upstream checks factor-bank finiteness, so a NaN in a
   PREPARE bank was an ordinary bad input exiting `1`. **One planned change was NOT made, on inspection.** The
   two `OutcomeLeakageError` sites whose messages began "invariant violated" are not the same thing: the
   CONTINUE-without-OOF-manifest check is a pure code invariant and became `Phase2aInvariantError`, classified
   `BUG` and deliberately outside the roster; but step 9's `sealed_access_count != 0` is a GENUINE leakage
   detection — downgrading it would have weakened the highest-severity guard — so it keeps its class and
   instead gained the forensics its message lacked (both counts, the role, the source kind, and "preserve every
   artifact and do not re-run"), which matters now that the driver catches it and the traceback is gone. Every
   fix is mutation-verified, including the mutations that widen a gate too far. Guard files were touched in the
   fail-CLOSED direction only. Seal state remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.
   **2026-08-03 independent review of the guard branch, and a CORRECTION to the entry above.** The reviewer
   executed rather than read, and refuted two things the previous entry asserted. **(a) The recorded premise
   for editing `_seal_consumed` was false.** That entry, the commit message, the guard-file comment and a test
   docstring all claimed `Path.exists()` "SWALLOWS `OSError`" and named EACCES/ESTALE/EIO/EMFILE. On the pinned
   interpreter (3.12, `requires-python >=3.11,<3.13`) `Path.exists()` ignores exactly
   ENOENT/ENOTDIR/EBADF/ELOOP; the four errnos named all RAISE, so they never produced a false "not consumed" —
   they escaped as the uncontracted exit `1`, replacing the caller's original post-seal exception. Re-verified
   here independently. Both behaviours are defects and the fix is still right, but the false-`10` path was the
   IGNORED errnos and the raising ones were an exit-`1` path; the claim as written did not survive execution
   (`CLAUDE.md#invariants` 18). All four sites are corrected. **(b) The step-9 `sealed_access_count != 0` check
   is unreachable by construction, so the basis for keeping `OutcomeLeakageError` there is withdrawn.**
   `FutilityResult` has one construction site hardcoding `0`, and `DevelopmentOutcomeStore.__post_init__` — the
   REAL detection — refuses a non-zero count on a frozen dataclass. That is the same argument used to demote
   its sibling, so the previous entry reached opposite conclusions from identical reachability. It is now
   `Phase2aInvariantError` too: exit `1` with its traceback, which is louder than the rostered `10` it had, and
   the genuine detection is untouched. **Also fixed from this round:** the step-0 evidence gate consulted
   terminals only and so still reported the audit-burned / terminal-absent crash state — precisely the state
   `_assert_recover_roster` ACCEPTS as post-seal — as a pre-seal rejection, two rosters in one module
   disagreeing about one directory; it now consults the run-local seal audit as well. The step-0 diagnostic had
   dropped the exception class name, which is the key the runbook's operator table is looked up by. Runbook row
   A still said "stop, do not re-run" for a `phase2b` `RunDirStateError` that the code now routes to `30` +
   "use `recover`". `models.py` implemented the SAME three estimator-input checks as `identify.py` and was left
   untyped one module away — the fixed-here-missed-the-sibling pattern, for the third time in this work.
   **Accepted and recorded, not fixed:** `_assert_audit_destination_free` keeps the ignoring `exists()`
   (harmless today because `os.link` fails `EEXIST`, but the two now apply different evidence rules to one
   path); a genuine internal bug inside the step-6 re-read is swallowed as a documented `30` with its class
   name but without its traceback; and two `solve_ridge_svd` checks are internal invariants on the
   `identify_operator` path. Independently recomputed: **74** exception classes, symmetric difference against
   the table empty both ways. No other `CLAUDE.md#enforcement` guard file was modified — and `run_dir_state.py`
   is not on that list, contrary to how this branch's own review brief described it. Seal state remains
   **UNOPENED**; execution remains **RELEASE-BLOCKED**.
   **2026-07-25 pre-pod local gate:** the probe-rerun runbook's §2.2 verification roster was run at clean exact
   commit `614017b67e35e9cc07f68d5b512213d8356cf1b2` — **254 passed**, plus `ruff check`/`ruff format --check`
   over the whole repository, `git diff --check`, and an empty `git status --short`. This records local
   implementation readiness only; the verifier OCI image, owner-frozen image lock, exact-SHA independent review,
   and pod-stage gates all remain outstanding.
   **2026-07-27 singular-design estimator-domain correction (branch
   `compose-oof-estimator-domain-gate`, not operationally pinned):** the first correction normalized only
   the branch where `np.linalg.solve` actually raised. That was incomplete: for the same rank-deficient
   `lam=0` Gram matrix another LAPACK build could return an arbitrary vector, score it, and potentially change
   not only `selected_lambda` but the selected `k_total` and downstream futility status. The prior statement
   that “the verdict was never wrong” was therefore stronger than the code justified and is withdrawn.
   The corrected contract now applies the already-defined
   `max(Phi.shape) * float64_eps * sigma_max` rank rule **before** every unregularized OOF train-fold solve.
   A deficient candidate is recorded with a deterministic fold/reason and omitted from the finite score map;
   if none remain, selection fails closed. Passing unregularized fits and Phase-1 rank-deficient recovery
   characterization use an explicitly registered SVD minimum-norm least-squares solver, not singular normal
   equations. No `-Infinity` sentinel can become a winner or leak into JSON.
   The futility artifact is schema v2, serializes a non-finite condition number as `null` plus an explicit
   `condition_number_is_finite=false`, and uses strict JSON (`allow_nan=false`). The policy and tolerance-rule
   names are frozen in the config and confirmation manifest. This is a scientific selection-contract change,
   not a no-op exception wrapper: the config digest/run identity moves, and all config-bound activation
   evidence, ResolvedRunSpec/carrier material, exact-SHA review and owner pin must be regenerated. It removes
   platform-dependent singular-solve behavior; it does not claim bitwise portability for arbitrary near-rank-
   boundary SVD inputs, which still depend on the exact pinned runtime/BLAS evidence.
   **Corrections to this entry after adversarial review at the pushed SHAs.** (1) The gate keys on the literal
   `lam == 0.0`, while the tolerance rule is relative to `sigma_max` and `lam` is an absolute penalty on an
   unnormalized Gram. A factor bank scaled large enough makes `Phi^T Phi + lam I` byte-identical to
   `Phi^T Phi`, so a registered positive `lambda` can be numerically unregularized, bypass the gate, and be
   scored — reviewers demonstrated this on a synthetic bank at scale `1e4`. Nothing in `_verify_factor_banks`
   constrains factor scale, and no reviewer showed the real pipeline produces such a bank. **Open item:**
   deciding when a positive `lambda` counts as unregularized is a registered numerical criterion, i.e. a
   scientific decision, and is deliberately not invented here. Until it is registered, read the guarantee as
   "no arbitrary LAPACK solution enters selection **at `lam == 0`**". (2) The preflight claim that two runs
   differing only in solver or rank policy produced the same manifest is **withdrawn**: the seal confirmation
   manifest already carried `config_checksum` and `run_id`, both of which move with any config change. Only
   the `selected_hyperparameters` sub-block was blind, so binding the policy there is legibility and
   defence-in-depth, not the closure of an identity hole. (3) The `SelectionError` raised when the policy
   leaves no viable candidate was outside the driver's exit-code contract and wrote no artifact; it is now a
   registered pre-seal rejection whose exclusion reasons travel in the one contracted stderr line. (4) The
   `rank_tolerance_rule` is the same rule in `rank_diagnostics` and in the `lam=0` solver, but the two use
   different LAPACK drivers (`gesdd` vs `gelsd`), so identical *threshold* does not mean identical computed
   rank at the boundary; reviewers measured 9 disagreements in 4000 random matrices and 0 in 22,500 real
   design-matrix shapes. Seal state remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.
   **2026-07-30 supersession — stable registered ridge solver:** the 2026-07-29 exact-equality guard described
   below is no longer the shipped solver. It rejected only complete penalty loss, still allowed quantized or
   numerically immaterial penalties, and left ID-only on the same normal-equation hazard. Positive bilinear and
   ID-only ridge now use SVD filter factors on the design matrix (ID-only first eliminates its unpenalised
   intercept by centering), never form `Phi.T @ Phi + lambda I`, and fail closed on non-finite inputs/results or
   LAPACK failure. `identification.regularized_solver: svd_ridge_filter_factors` is now config-registered and
   copied into `selected_hyperparameters`; this intentionally moves the config digest and makes all prior
   config-bound evidence stale. The resulting canonical config digest is
   `2a8b1bc37b4b952b29dd57cf128d2aa27a2a698693e1376e569544ff119e85eb`; it must be the config axis of
   any replacement evidence and run identity.
   **2026-08-07 CLOSED — fold-level conditioning is gated, at `lam == 0.0` only (owner decision).** The item the
   2026-08-04 and 2026-08-05 entries below carried as *recorded, not closed* now has a registered disposition.
   Measured first, decided second, and the measurement **narrowed the premise the decision was going to be made
   on**. Three things were established on synthetic designs this session (`n_genes=12/18`, `k=3/4`, 3 folds;
   probes are scratch, the exhibits are pinned in `tests/alive/compose/test_condition_ceiling.py`):
   (1) *the gap is real* — confining one factor's magnitude to a single fold's held-out genes leaves the full
   design at `cond = 6.47` (admitted by the candidate screen) with **full-rank** train folds at
   `(3.03e12, 5.17, 7.13)`, invisible to the `is_full_rank`-only fold policy and, for the three positive registered
   lambdas, to any fold diagnostic at all; (2) *on NOISY data the over-ceiling candidate loses* — conditioning
   bounds noise AMPLIFICATION, so a degenerate fold inflates held-out error while selection takes the **max**:
   **0 counterexamples in 37 designs** at relative noise 0.01. **This is conditional and was first recorded as
   though it were not — see the review entry below, which falsified the unconditional form against this branch's
   own exhibit.** (3) *at `lam > 0` the unregularized number is the wrong statistic* — the ridge filter factors
   bound the effective conditioning, so rejecting on `cond(Φ)` there would discard a healthy candidate. The
   residual risk this arm addresses is therefore **misattribution** — the dead candidate is filed as a legitimate
   low score, and a stop that follows is named
   `dev_oof_delta_below_threshold`, a claim about the biology, for a numerical cause. That is the same defect class
   the 2026-08-05 entry fixed one level up. **Registered:** the ceiling is now also applied to each unregularized
   OOF **train fold** design, at `lam == 0.0` only — the one place `identify_operator` takes the `lstsq` branch and
   `cond(Φ)` *is* the conditioning of the solve, and the same boundary the sibling `unregularized_oof_rank_policy`
   already uses. Applying it at every lambda was **rejected**: it would discard candidates whose actual solve is
   well conditioned, relocating the ALL-vs-ANY over-strictness the 2026-08-05 review caught. The screened candidate
   is recorded with the same reason prefix, so the `diagnostics2` context line covers it; that line now names
   `(k_total, lambda)` **candidates** rather than `k_total` dimensions, because the two arms remove different
   amounts and reporting a `lam=0.0`-only removal as a whole screened dimension would itself be a misattribution.
   Verification: **12 mutations, all killed** after the review fix wave — screen deleted · applied at every lambda ·
   `>` → `>=` · conditioning checked before rank · reason prefix dropped · exception swallowed unrecorded · context
   line reverted to `k_total` · fold index replaced by a constant · `isfinite` guard deleted · only the first
   over-ceiling fold named · prefix contract weakened to a substring · estimator guard added to the fold branch.
   The last five are the reviewers' own proposed mutations. **A first pass claimed "7 mutations, all killed" and
   that was wrong**: the ordering mutation as written also deleted the `isfinite` guard, and with the guard kept
   the reordering is an EQUIVALENT mutant. Two reviewers found it independently.
   The fold arm raises `FoldConditioningError`, a `SelectionError` **subclass**, so `except` still routes an escape
   (impossible on today's single call path) to exit 10 rather than exit 1; the roster stays 42 entries for the same
   reason, while the classification table moves **74 → 75**. That table is what noticed the new class: the targeted
   selection suites were green without it, and only the full `tests/alive/compose` run — 2 failed, 2000 passed —
   flagged the unclassified exception. **This is the fail-closed registry from 2026-08-01 (L1-T4) doing exactly its
   job**, and the second time on this work that a green targeted suite was not evidence of anything. A second full
   run then caught a third: `_REJECTIONS` in `test_exit_code_paths.py`, derived from the same table, moved **44 →
   45**, so the new class is now injected end to end through every driver stage like the other 44. All three counts
   bound to the classification were then enumerated rather than discovered one run at a time. Final state:
   `tests/alive/compose/driver` 537 passed; ruff check and format clean. Linux CI on `9865f6e` (the pre-review
   commit) passed as run `31149597512`; the post-review full-suite figure is recorded in the review entry below.
   **What this does NOT close.** The phi-rank activation evidence reports the FULL design's condition number only,
   so the fold arm is enforced at run time and is **not** pre-certified by evidence — recorded as a limitation, not
   a blocker. The config digest is **unchanged** (`b158417a…`): no config field moved, the registered bound is
   reused. Task #14 (regenerate the two config-bound activation reports at the current digest) and the missing
   **owner-decision artifact** for the 2026-08-04 ceiling disposition **and for the 2026-08-07 fold-arm
   disposition recorded here** both remain open. A convention for exactly this exists and was overlooked when the
   gap was first described as having none: `2026-07-13-compose-dev-pod-gate-decisions.md` (PROPOSED → owner
   CONFIRMED in its §6). Seal state remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.

   > **[2026-08-12 update to the paragraph above.]** The owner-decision artifact now exists:
   > `docs/superpowers/2026-08-12-compose-conditioning-ceiling-decisions.md`, covering the ceiling value, both
   > application points, and — as `OPEN` with no proposal — the `‖z‖` gap of item 4b. It is **PROPOSED**; §6 is
   > unsigned, so the gap is recorded, not closed. Task #14 is unaffected and remains open.

   **2026-08-07 three independent adversarial reviews of the fold arm (numerics · governance · test adequacy), and
   the corrections they forced.** Linux CI on `9865f6e` passed (run `31149597512`) and was, as on 2026-08-05,
   the weakest of the signals: it cannot see a false claim. All three reviewers converged on **do not merge — the
   code is sound, the record is not**. Confirmed by re-running each finding rather than accepting it:
   **(a) the headline claim was false as written and this branch's own exhibit was the counterexample.**
   `_fold_local_degeneracy_instance` regenerated `eps_obs` exactly and noiselessly from the degenerate `Z`. With no
   noise there is nothing to amplify, an ill-conditioned but consistent `lstsq` is exact, and the over-ceiling
   `lam=0` candidate WON at `theta = 0.9999999993` — so the screen moved the winner (`0.99999999933 → 0.81009349246`),
   in direct contradiction of the "neither arm can change the WINNER" sentence written into the spec, the readiness
   index, a test docstring and the commit message. The exhibit now carries relative noise; the noiseless case is
   pinned as the explicit boundary rather than hidden. **This also matters beyond bookkeeping**: `oof_theta` is a
   registered futility input, so an arm that can move it can move `CONTINUE` → `FUTILITY_STOPPED`.
   **(b) four numbers were attributed to an artifact that does not produce them.** `1.5e1`, `2.9e12`, the `-5e21`
   theta scale and the `0.7867 / 0.7928` pair came from scratch probes at `n_genes=12, k=3`, while the cited test
   file runs `n_genes=18, k=4` and produces `6.47`, `3.03e12` and `+0.99999999933`. The standing rule was written
   as "never record a number you did not produce this session"; this is its second failure mode — a number the
   writer DID produce, attributed to an artifact that reproduces something else. Both halves now apply.
   **(c) one real code defect.** The ordering guarantee held per fold but not per CANDIDATE: `_oof_theta_for_candidate`
   raised on the first offending fold, so a conditioning raise in fold 0 short-circuited a rank failure in fold 1 and
   a NON-IDENTIFIABLE candidate was recorded "numerically inadmissible", with the reason depending on fold order.
   Reproduced (`fold 0: cond 2.92e12 full-rank · fold 1: rank-deficient` → recorded as conditioning). Fixed by
   moving both guards into a whole-candidate pre-pass, `_screen_unregularized_folds`, that checks rank across ALL
   folds before conditioning on any.
   **(d) a scope limit that is NOT closed.** `cond(Φ)` is invariant to a uniform rescale of `z` while the registered
   `lambda_grid` is ABSOLUTE: `Φ` is bilinear in `z`, so `z → cz` makes the effective penalty `λ/c⁴`. **How much
   protection `lam > 0` actually provides is therefore a property of `‖z‖`, which no config field, code path or
   activation evidence bounds.** Recorded as a registered limitation; the `lam == 0.0` restriction is retained as
   the conservative choice. **It is filed here, inside a correction narrative, and NOT in the pre-seal blocker
   enumeration — round 4 flagged that placement as wrong for something that can flip a REGISTERED futility
   condition (`dev_oof_delta_below_threshold`) by a numerical cause. Surfacing it where a pod operator reads
   blockers is task #43 and is NOT closed by this entry.** Measured (2026-08-07 re-measurement, `lam=0.001`, `eps` rescaled by `c²` with the
   design, `cond(Φ) = 6.4732…` in all four cells):

   | | `c = 1` | `c = 100` |
   |---|---|---|
   | noise = 0 | `0.8100934924563623` | `0.9577101250921993` |
   | noise = 0.01 (the fixture default) | `0.8103235465139835` | **`-3340344.0205271696`** |

   The `λ/c⁴` identity is confirmed to ten significant figures (`c=100, λ=1e-3` ≡ `c=1, λ=1e-11`). Also fixed: the reported fold index was asserted nowhere (a constant passed the suite) while
   the sibling rank arm pinned its own; only the first over-ceiling fold was named; the reason string silently
   dropped the "the unregularized solver applies no filter that could bound it" clause — deliberately, because it is
   false (`lstsq` applies an `rcond` truncation), but the removal went unrecorded while the string lands verbatim in
   a checksummed futility report; the `isfinite` guard's stated justification was wrong (`rank_diagnostics` returns `inf` when `rank < sym_dim` **or** `pos.size == 0`, and the
   second fires at `k_total == 0` with `is_full_rank` TRUE — so the guard is reachable, and is now tested directly
   rather than kept as untestable defence-in-depth); and the config comment still described a `k_total`-only screen.
   The config fix is comment-only and **digest-neutral by owner decision** — recomputed after the edit as
   `b158417a76e888bff2bf6836bea622e0cbf596f0743f3fe89aea2ffe0864a9fd`, unchanged, so no new run identity is created.
   Post-fix state at `28cd0a0`: 12 mutations killed, full `tests/alive/compose` 2013 passed 2 skipped, ruff clean,
   Linux CI green (run `31152897312`). **That state was then reviewed again and did not survive — see the entry
   below.** Seal state remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.

   **2026-08-07 SECOND review round on the fix wave (closure · new code · new tests), and the third correction
   wave.** Verdict again **do not merge**: `28cd0a0` had green Linux CI and a green 2013-test suite, and both were
   green on a commit whose own record was still wrong. Ten of the twelve round-1 findings were judged genuinely
   closed — a reviewer independently rebuilt the true reorder mutation and confirmed it is now killable, and
   reproduced every repinned number bit-for-bit. Three were not.
   **F12 was WRONGLY CLOSED, and it is the same misattribution the fix wave claimed to eliminate.** The recorded
   scale exhibit `0.8103 → 0.9577` pairs numbers from TWO different fixtures — `0.8103` is the noisy default,
   `0.9577` is the noiseless one — under the words "동일 설계" (same design); no `(noise, c)` setting produces both,
   and the noiseless baseline is `0.8101`. Worse, a reviewer's `theta ≈ -3.3e6` had been dismissed as unreproducible
   "because scaling `Z` without scaling `eps` conflates a representation mismatch with conditioning". **That reason
   is false**: `theta` is a relative-error-reduction ratio and is invariant to a uniform rescale of the outcomes
   (stated WITH its construction, because every
   value-only version of this figure has been wrong: on the plain exhibit, rescaling the outcomes alone changes
   `theta` by **exactly 0**; in the setting actually at issue — bank at `c=100`, `eps` scaled by `c²` versus not —
   by relative **5.019e-15**, i.e. round-off, not a mechanism). The real cause of the non-reproduction was measuring against the
   pre-fix, noiseless exhibit. The dismissal is **withdrawn**, the reviewer's measurement is adopted, and the table
   above is repinned from a single stated configuration. The correction matters: the recorded severity understated
   the collapse by roughly seven orders of magnitude on a quantity that feeds a registered futility condition.
   **A thirteenth mutation existed, in the arm the fix wave itself created.** `select.py`'s RANK pre-pass reported
   `f"OOF train fold {fold_index}"`, and replacing that index with a constant `0` survived the FULL compose suite at
   2013 passed — identical to clean. The only fixture in the repo where the deficient fold is not fold 0 is the new
   `test_a_rank_failure_in_any_fold_outranks_a_conditioning_failure_in_another`, and it never asserted which fold
   the reason named. Eight further survivors were found in the same family (rank value taken from fold 0; rank pass
   skipping the last fold; the also-clause naming a nonexistent fold, or healthy folds, or only the second; the rank
   raise switched to the conditioning exception type, which routes it past the estimator escalation).
   **Five of the six new tests were weaker than their names.** The boundary test's boundary was measured at noise
   `≈ 6e-12` while its nearest probe sat at `1e-6`; `approx(1.0, abs=1e-6)` asserted seven digits of a quantity out
   of a `cond 3.03e12` solve, the same over-precise shape as the `rel=1e-12` pin that went red on Linux; the
   "owns the zero-width bank" test showed no such ownership (the actual refusal is `EstimatorInputError`, three
   layers down); the monkeypatched prefix test passed verbatim with its monkeypatch deleted; and the rewritten
   fixture fed the SAME noise realization into both split halves, so `measurability_gate` — a split-half correlation
   — would have scored injected noise as reproducible GI signal.
   **The recurring failure mode, named.** Across both rounds the code fixes held; what failed each time was
   asserting a weaker property than the name claims, then recording the name. The standing rule added here is
   mechanical rather than aspirational: **for every new test, run the mutation its own name describes and confirm it
   dies.** Every finding above would have been caught by that check before commit, without a reviewer.
   Also corrected: `_screen_unregularized_folds`'s docstring asserted its rank-before-conditioning precedence
   without qualification, but the CANDIDATE-level screen still masks fold-level rank failures one level up
   (measured: full design `cond 9.21e12` over the ceiling with train fold 1 at `rank 6/10` records only the
   conditioning reason). That is deliberate, not the same defect — the two arms examine different objects, the
   candidate arm's reason is true, and it justifies removal at every lambda where the fold rank policy justifies
   removing only `lam=0.0` — so the docstring is scoped rather than the code restructured. The RANK arm now names
   every deficient fold, matching the conditioning arm. `diagnostics2`'s two `sorted(...)` calls remain mutable to
   `list(...)` with the suite green; that is **equivalent-by-config** (the registered grids are ascending, so
   insertion order equals sorted order) and is recorded here as knowingly-surviving rather than left silent for a
   third round. **F10 remains OPEN and is recorded as such:** the decision NOT to register a policy name for the new
   scope was minuted only as its benefit ("no config field moved, so no new run identity"); its counterpart is that
   the 2026-08-06 and 2026-08-07 selection contracts are now indistinguishable from config, digest and
   `selected_hyperparameters`, and separable only by Git SHA. Post-wave state: **22 mutations all killed** (the
   twelve from round 1 plus the nine round-2 survivors and one per new test name), full `tests/alive/compose`
   2016 passed 2 skipped, ruff clean, Linux CI green on `c22db82` (run `31188255447`). **That state was reviewed a
   third time and again did not survive — see below.** Seal state remains **UNOPENED**; execution remains
   **RELEASE-BLOCKED**.

   **2026-08-11 FOURTH review round (verification apparatus · round-3 closure · whole-branch merge readiness), and
   the fifth correction wave.** The merge lens returned MERGE-WITH-FIXES with four record items and zero code
   changes. The other two found that **the failure had moved into the instrument, and that the previous wave's
   "class-level" fix covered one arm again.**
   **(a) A mutation "kill" meant only that the process exited nonzero.** `run_suite` scored on `returncode`.
   Reproduced with a one-character syntax break in `select.py`: three collection ERRORS, **zero failing tests**,
   nonzero exit — recorded `killed`. Every kill this branch has logged was therefore a statement about the process,
   not the tests, and a transient environment failure mid-run would have converted every remaining entry to
   "killed" and printed `all mutations killed`, exit 0. `run_suite` now returns the SET OF FAILED NODE IDS; a kill
   requires it non-empty and PRINTS the tests that produced it; a nonzero exit with no failing test is reported
   **INVALID** — neither kill nor survivor. Two rules become **five**: (4) a kill must be attested by a named
   failing test, never an exit code; (5) the mutable file set must cover every site that ENFORCES the contract —
   rules 1–3 govern how an entry is written, none governs which sites have an entry at all. The four enforcing
   sites still unmutated (`phi_rank`, `phase2a`, `config2`, `preflight_cmd`) are now named as such.
   **(b) The harness violated its own Rule 1.** `M4` was named "conditioning checked BEFORE rank" while DELETING
   the rank pre-pass — a strict superset, so its kill was evidence for the larger defect and said nothing about
   ordering. Renamed to what it does; `M4b` performs the reorder the old name claimed. `M3`/`M9` named no arm and
   mutated only the FOLD arm; the CANDIDATE arm's own `>` and `isfinite` had no entry (`M3b`/`M9b` added). The
   `_Never` helper injection had no anchor count check — one drift from a `NameError` recorded as a kill, the
   retired M8's class one level down. Backups were keyed by BASENAME. The summary printed no count, so deleting an
   entry left the output byte-identical.
   **(c) The "class-level" field fix covered the conditioning arm only — the fifth time on this branch that the
   instance was fixed and the class was not.** Four survivors in the RANK arm: its also-clause could name ALL folds
   rather than only the deficient ones (reporting a FULL-RANK fold as rank-deficient, inside a checksummed report),
   and its `rank`/`sym_dim` could be replaced by the literals they take in every fixture in the file — a direct
   violation of the harness's own Rule 2. Root cause: `_assert_rank_fields` had ONE call site whose fixture makes
   all three folds deficient, so "name every offender" and "name every fold" were indistinguishable — exactly the
   trap the conditioning sibling documents and defends against with a second fixture, whose comment reads "Both are
   needed; either alone leaves a mutant alive". The rank arm had only the first half. Closed with a second rank
   fixture at `k=3` (so `sym_dim` is 6, not the usual 10) that leaves one fold HEALTHY and gives the primary
   offender a rank other than the usual 6.
   **(d) The `5e-9` figure was corrected into a different wrong number.** It was never fixed where it lives — the
   SPEC, which outranks this index for scientific claims, still carried it, because the withdrawal touched only the
   readiness. And the replacement stated a value without its construction: `theta`'s invariance to a uniform outcome
   rescale is **exactly 0** on the plain exhibit, while the sentence is about a different setting (bank at `c=100`,
   `eps` scaled by `c²` versus not) where it is `5.019e-15`. Both documents now state the construction alongside the
   value — the omission that made this figure wrong four times running.
   Also: "(owner decision)" was asserted unqualified in three places while this same document records its artifact
   as missing — now qualified with a pointer to the pending artifact and its convention. The harness matched none of
   the ten path globs in `.claude/rules/compose.md` despite existing solely to rewrite COMPOSE production source —
   added. Its safety notice said it edits `src/` when it also edits `tests/`, and omitted the concurrency hazard
   that fired twice during these reviews — both corrected in the file a future user actually reads.
   Post-wave: **37 mutations all killed, each by a named failing test**; full `tests/alive/compose` **2017 passed,
   2 skipped**; ruff check and format clean. Seal state remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.
   **2026-08-08 THIRD review round (closure · whole-branch merge readiness · new tests), and the fourth correction
   wave.** All three CI runs green, 2016 tests green, 22/22 mutations killed — and **six more mutations survived the
   full suite at counts byte-identical to clean**. The whole-branch lens returned MERGE-WITH-FIXES; the other two
   returned defects. Every finding was re-run before acceptance.
   **The recurring failure was diagnosed one level too shallow.** Round 2 was recorded as "asserting a weaker
   property than the test name claims". The truer statement is that **each wave fixed the INSTANCE and not the
   CLASS**: wave 3 closed the constant-fold-index mutation in the rank arm, wrote a comment stating that "every" is
   only falsifiable with three or more offenders — and then created the same two defects in the *conditioning* arm's
   primary index and in the rank arm's own also-clause, in the same commit. Six survivors, all of one family: a
   generated message field that no assertion pins. The fix is now class-level: `_assert_ceiling_fields` and
   `_assert_rank_fields` pin EVERY generated field of both reasons — index, measured value, clause header, and the
   exact membership of the also-clause — against substitution by a constant or by another field's value. Fixtures
   were changed to make that falsifiable at all: the degenerate fold is parameterised (it was always fold 0, so no
   fixture in the repo could distinguish a reported index from the literal `0`), the rank fixture now produces
   THREE deficient folds not all sharing one rank (three were needed for "every"; distinct ranks were needed or
   substituting fold 0's values yields a byte-identical message), and the conditioning also-clause is asserted with
   its per-fold values.
   Also closed: the fold-arm "same reason for any estimator" test never compared reasons; the candidate arm's
   measured value could be replaced by `0.0`; the `diagnostics2` context line could report a candidate-arm removal
   (every lambda) as a `lam=0.0`-only one — the mirror of the misattribution that line exists to prevent; a
   test whose name said the finiteness guard "refuses" a zero-width bank when its body asserts nothing is raised
   (renamed); and a seed-0 margin that could silently degrade to a single-element identity. **Harness now 31
   mutations, all killed.**
   Corrections to this document and to source: the falsified claim that `rank_diagnostics` returns `inf` **exactly**
   for a rank-deficient design still stood in three places including the PUBLIC `select_hyperparams` docstring;
   `select_hyperparams` and `diagnostics2` still documented a one-arm screen; `preflight_cmd`'s comment still said
   the screen removes "dimensions", the exact `k_total`/candidate conflation this protocol registers as a
   misattribution. Two unreproducible numbers introduced by the previous correction are withdrawn: the withdrawal
   paragraph's own "relative `5e-9`" invariance figure is off by six orders, and a `cond 9.21e12` quoted in a source
   docstring came from a construction committed nowhere — both are unreproducible numbers *inside the corrections
   for unreproducible numbers*, and the second is removed rather than repinned.
   **Recorded, NOT closed.** `diagnostics2`'s `sorted(...)` sites were recorded as equivalent-by-config; that
   justification covers `sorted` → `list` but **not** reversal, which also survives, and a third such site exists at
   `select.py`'s `"; ".join(sorted(...))`. `measurability_gate` still cannot fail on this fixture — the fix removed
   a false-pass mechanism (the shared noise realization) rather than making the gate load-bearing here. And the
   **lineage asymmetry F10 half-states**: the 2026-07-27 entry registered a structurally identical guard as a config
   field precisely because "a scientific selection-contract change moves the config digest/run identity", and the
   same review dismissed `selected_hyperparameters` blindness **because** `config_checksum` and `run_id` "both move
   with any config change". This branch removes that premise, and F10 records the consequence without saying the
   earlier mitigation no longer applies. It does now.
   The mutation harness is now **committed** (`scripts/compose_conditioning_mutation_harness.py`) because its
   absence was itself a named root cause: the evidence for "all mutations killed" existed only as prose in a commit
   message, so it could not be re-run or extended and each round rediscovered the same family one seat over. It
   refuses to start on a dirty worktree, since it edits `src/` in place and restores in `finally`. Post-wave state:
   **31 mutations all killed**, full `tests/alive/compose` **2016 passed, 2 skipped**, ruff check and format clean.

   **The most instructive finding of the third round arrived after it: the failure mode had migrated INTO the
   mutation harness.** Round 1's `M8` mutated the reported fold index to the sentinel `99` and was recorded KILLED —
   but `99` died only because a test asserted the literal substring `"OOF train fold 0"`. The constant that
   mattered, `0`, survived two further rounds, under a mutation NAME ("the reported fold index is a constant") that
   claimed the whole class. So the harness itself was asserting a weaker property than its name and then recording
   the name — the exact defect it exists to find — and its false kill is *why* the class stayed open across rounds
   2 and 3. Verified at this SHA: both `99` and `0` now die, because wave 4 parameterised the degenerate fold.
   `M8` is retired in favour of the correct-answer mutation, and the harness now carries the rule explicitly:
   **an index- or value-to-constant mutation must use the constant the correct answer actually takes, never a
   conspicuous sentinel** — better still, build the fixture so the correct answer is not a constant any mutation
   would guess. **Process hazard recorded:** the in-place harness was run while independent reviewers were reading
   the same checkout, which briefly showed a mutated `select.py` in `git status`. It restored correctly and a
   concurrent on-disk mutation can only produce a spurious FAILURE, never a spurious pass — but the harness and
   read-only review must not share a worktree.
   Branch state at `50e7bc7`: 30 mutations all killed (M8 retired), full `tests/alive/compose` 2016 passed
   2 skipped, ruff clean, Linux CI green at `50e7bc7` (run `31263820204`) and at `bb185b6` (run `31265250187`) — naming both, since
   "the tip" stopped being unambiguous the moment another commit landed. Note `2256f6d`'s own run
   (`31263666233`) was **cancelled** when the next commit was pushed on top of it — superseded, so neither a pass
   nor a failure, and that commit has no CI verdict of its own; the tip contains its changes. **`2256f6d` and
   `50e7bc7` have had no independent review.** Rounds 1/2/3 found 12 / 9+ / 6 defects: converging, not converged,
   and the last two findings came from reviewers examining the VERIFICATION rather than the code. Seal state
   remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.
   **2026-08-05 second independent review of the redesign, and the corrections it forced.** Three reviewers
   re-ran against the redesigned branch; two were the round-1 reviewers, asked to judge their own findings
   CLOSED/PARTIAL/OPEN rather than to re-derive. **The highest-risk item held.** That the screen must not fire
   on a non-finite condition number — otherwise selection moves quietly to a full-rank dimension and the
   registered rank futility gate becomes unreachable — was found, fixed and tested by the implementer with no
   independent check. It now has one: verified by proof (`isfinite(cond) ⟹ full rank` unconditionally, the
   converse failing only at `k_total=0`, which the config pins out), by 460 random designs across five
   degeneracy modes with 0 divergences, and by a differential sweep over 60 mixed `[4,6]` grids finding 0
   rank-stop→CONTINUE regressions. A structural argument was also supplied that the implementer had not
   articulated: the screen only ever REMOVES candidates, and removing elements cannot demote the existing
   argmin, so a rank-deficient dimension that won before still wins.
   **Two corrections were forced, and both were the implementer's own new defects.** (1) **The activation-gate
   binding overshot.** The run's rule is ANY — an over-ceiling `k_total` is screened out and the study proceeds
   on the rest — but the validator and the producer verdict were written as ALL, rejecting the whole report over
   a single inadmissible dimension. Two reviewers found this independently; it relocates one gate earlier the
   exact over-strictness the redesign had just corrected, and `k_total=8` is its realistic trigger (`sym_dim=36`
   against 41 calibration pairs, already 30× worse conditioned than the others in the committed evidence). The
   only remedy for such a BLOCKED report would have been editing the registered `total_k_grid` after seeing a
   development diagnostic. Both sides now reject only when NO dimension is admissible, name the over-ceiling
   dimensions in the verdict either way, and refuse an unusable ceiling ARGUMENT (`nan`/`inf`/non-positive),
   which the first binding left unguarded. (2) **A screened stop misattributed its own cause.** With the
   signal-bearing dimension screened, the surviving one fails `oof_theta <= threshold`, whose registered
   condition is `dev_oof_delta_below_threshold` — a claim about the BIOLOGY — while the actual cause was
   numerical; the ceiling reason existed only in `nonviable_candidates`, unlinked. Reproduced on 3/3 seeds. A
   stop that follows a screening now carries an explicit context line in `failures` naming the screened
   dimensions and saying it is not independent evidence about them (`CLAUDE.md#invariants` 12/14/18). Four
   mutations against these two fixes, all caught.
   **A recording rule, adopted because this branch broke it five times.** `Path.exists()`'s errno set, the
   exhibit condition numbers, a quoted `grep` output, and a reviewer's θ figure were all written into this file
   or the spec without being executed by the writer. From here: **no number, command output or measurement is
   recorded in a governance document unless the writer produced it in that session, and where a number is
   load-bearing it is pinned by a committed test rather than quoted.** The exhibit values are pinned that way
   now; the θ=0.43 figure was withdrawn rather than re-derived, and the regression it stood for is pinned by a
   test instead.
   **The rule needed a second clause within the hour, and Linux CI supplied it.** Pinning the exhibit values at
   `rel=1e-12` was green on macOS (Accelerate) and RED on Linux x86_64 (OpenBLAS) at `24b0fd7`: the
   block-imbalanced condition number came back `3713365971178.1865` against the recorded
   `3713121910859.7812`, a relative difference of `6.6e-05`. The arithmetic says it must: `cond ≈ 3.7e12`
   destroys 12.6 of float64's 15.65 significant decimal digits, so about three survive, and a twelve-digit pin
   asserted nine digits the number does not carry. The two well-conditioned values in the same test reproduce
   bit-for-bit on both platforms and keep their exact pins. So: **executing a number is not enough — it must be
   pinned at the precision it actually has, and a number whose own conditioning destroys most of its digits is
   reproducible only to what survives.** The imbalanced value is now pinned at `rel=1e-3` (three figures,
   fifteen times the observed cross-BLAS spread); the spec and this index quote it to three figures already, so
   no recorded claim changes. This is also the first defect on this branch that macOS could not have caught,
   which is the argument for the Linux job existing.
   **Also corrected from this round:** `_EXPECTED_CONDITION_CEILING`'s own comment and the validator's comment
   still described the reversed futility design — the two most authoritative places a reader looks for what the
   number means; `select_hyperparams`'s public docstring omitted its new required parameter and still described
   `nonviable_candidates` as estimator-domain only; the `SelectionError` roster comment's registered enumeration
   did not list the new all-inadmissible cause, which is the same criticism round 1 levelled at
   `rank_condition_fail`; `condition_ceiling` is now in the preflight confirmation manifest, because the screen
   can remove dimensions from `total_k_grid` and recording the grid without the bound that filtered it
   misdescribes what was searched; and three assertions the reversal dropped without recording it
   (`sealed_access_count`, the bound reaching the operator, the refusal-before-selection ordering) are restored.
   **Still open, recorded not closed:** fold-level conditioning is ungated — and the earlier description
   understated it: `select.py` computes a fold's condition number ONLY when `lam == 0.0`, so for the three
   positive registered lambdas no fold diagnostic exists at all; the exclusive coverage band is `(1e8, ~1e14)`;
   `LinAlgError` at extreme factor scale still exits `1`, and a NaN factor bank reaches it before the estimator's
   input contract, so the runbook's "this is the first gate" note is false for NaN; `scripts/compose_phi_rank_report.py`
   has no tests (pod-only code) and loads the config only AFTER the GPU encode, so a config failure burns the
   run; the scientific-mode call site's ceiling forwarding has no sentinel test; and the plan's DRAFT/"D1–D4
   미결" gate lines still stand under a banner that says L2 shipped. Seal state remains **UNOPENED**; execution
   remains **RELEASE-BLOCKED**.
   **2026-08-04 CLOSED — the condition ceiling is registered, and the first design of it was WRONG.**
   The open item below is resolved: statistic `rank_diagnostics(Φ).condition_number` on the
   full-calibration `Φ`, bound `identification.condition_ceiling: 1.0e+8`, anchored data-free at
   `1/sqrt(float64 eps) ≈ 6.7e7` rounded up. It is applied as a **per-candidate admissibility screen inside
   `select_hyperparams`** — the same shape as the sibling `unregularized_oof_rank_policy` — recording an
   over-ceiling `k_total` in `nonviable_candidates` and selecting among the rest. Only when EVERY candidate is
   inadmissible does selection become invalid: `SelectionError`, already a contracted pre-seal rejection
   (exit 10) and already in the runbook's category D, so **no new exception class and no new futility
   condition**; the registered `futility.conditions` list is deliberately unchanged. The screen is restricted
   to FINITE condition numbers — `rank_diagnostics` returns `inf` exactly for a rank-deficient design, which
   the registered rank futility gate owns, and screening it here would have made that gate unreachable by
   letting selection move quietly to a full-rank dimension. The same bound is now enforced by the phi-rank
   activation validator and the producer's READY verdict, which compute the identical statistic on the
   identical design; without it a report could certify as READY a dimension the run then refuses, at the cost
   of an owner approval and a pod trip.
   **The first implementation made it a `FUTILITY_STOPPED` condition on the SELECTED `k_total`, and three
   independent adversarial reviews rejected that on both axes.** (a) It terminated the study permanently
   whenever the best-scoring dimension was over the ceiling, even when the same registered grid held an
   admissible alternative. **The θ=0.43 figure previously recorded here is WITHDRAWN**: it was quoted from a
   reviewer's round-1 script and never reproduced by the implementer, and it does not reproduce from the
   construction the committed tests use — the fifth unreproduced measurement on this branch, and the reason
   the rule below now exists. The regression itself is real and is now pinned by a committed test
   (`test_screening_the_winning_dimension_stops_the_run_and_says_so`) rather than by a quoted number. (b) Two of
   the five reasons recorded for choosing futility were **factually false about this repository**, and are
   withdrawn: the runbook does NOT say exit 10 means "fix and retry" (it says the exit code carries only
   seal-consumption, and category D says "investigate, do not re-run"), and the durable futility report does
   NOT persist the `singular_values` spectrum it was said to preserve — the array is built in `diagnostics2` and
   reaches only `diagnostics2`. Two more were weakened: "no rejection slot exists" was a tautology about the
   *futility* vocabulary while the sibling threshold in the same config block (`uncovered_tolerance`) is a
   `SelectionError`, and `EstimatorInputError` was rostered as exit 10 two days earlier on the identical
   "nothing upstream checks this property of the PREPARE factor bank" reasoning; and the "discontinuity at the
   boundary" argument was imprecise, since `is_full_rank ⟺ isfinite(condition_number)` holds identically
   (independently re-verified here over 1500 random designs, 0 divergences) so the two events are mutually
   exclusive by construction. The owner re-decided on the corrected record.
   **Two recorded measurements are corrected, and one of them was introduced by this branch.** (a) The entry
   below says the condition number is "exactly scale-invariant under a UNIFORM rescale". Re-measured:
   `10.421787979549746` at `1x` versus `10.421787979549734` at `1e6x` — invariant to round-off, not exactly.
   (b) **The committed exhibit test did not reproduce the registered numbers at all.** It claimed the same
   construction as the deleted `test_one_over_scaled_factor_block_is_rejected…` but dropped that helper's
   `coef_true` draw as unused — it is unused, and it advances the RNG, so the pair set changed from 37 to 39
   and the exhibit silently became `9.91 → 4.15e12` while the spec and this file kept quoting
   `10.42 → 3.71e12`. Two reviewers found it independently. The draw is restored and the test now asserts the
   registered values exactly (`rel=1e-12`), so the documents and the code cannot drift again. Also corrected:
   the YAML rule is `<digits>.<digits>[eE][+-]<digits>`, not "the `+` is required" (`1e+8` is also a string,
   and a plain integer literal would have worked); and the spec mis-dated the deleted guard, which was
   introduced 2026-07-29 and removed 2026-07-31.
   **This moves the config digest**, as planned:
   `2a8b1bc37b4b952b29dd57cf128d2aa27a2a698693e1376e569544ff119e85eb` →
   `b158417a76e888bff2bf6836bea622e0cbf596f0743f3fe89aea2ffe0864a9fd`. That digest, not the prior one, must be
   the config axis of any replacement evidence and run identity; the two activation-evidence reports pinned to
   `d8c65ac4…` remain stale and their regeneration remains open (task #14). Independently checked against the
   committed `real_norman_phi_rank_report.json`: the recorded real designs sit at `15.82`, `32.86` and
   `484.20` for `k_total` 4/6/8 — more than five orders of magnitude below the ceiling — so the registered
   bound does not trivially reject the study it governs, the committed evidence still passes the newly bound
   validator, and the test reads those values from the evidence file rather than transcribing them.
   **Mutation coverage is stated as of the committed code, not of an earlier draft.** The previous version of
   this entry claimed "fourteen mutations, all caught" for code that had since been repositioned; that claim
   is withdrawn as unsupported. Against the current design six mutations were run and all six caught: deleting
   the selection screen; letting the screen fire on non-finite conditioning (which would make the rank futility
   gate unreachable); `>` → `>=` at the bound; deleting the activation-validator binding; replacing the
   validator's ceiling with a literal; and a `phase2a` call-site literal EQUAL to the registered value. Two
   known-surviving mutations are recorded rather than papered over: replacing `cfg.rank_tolerance_rule` or
   `cfg.unregularized_oof_rank_policy` with their registered string literals is undetectable by the forwarding
   test, because `select.py` re-pins both to registered constants — the property is real, the test is not what
   provides it. **Recorded, not closed:** fold-level conditioning is still ungated (`select.py` computes each
   OOF train fold's condition number and discards it, reading only `is_full_rank`), so a degeneracy confined
   to one gene-disjoint group can leave `cond(full Φ)` at 6.5 while a fold design sits at `3e12` and the run
   CONTINUEs; the ceiling's exclusive coverage band is `(1e8, ~1e14)` because beyond that the same defect
   reports as rank deficiency; a `numpy.linalg.LinAlgError` from `np.linalg.svd` at extreme factor scale still
   exits `1` rather than a contracted code (pre-existing); `condition_ceiling` is absent from the preflight
   confirmation manifest's `selected_hyperparameters`, unlike `dev_oof_threshold`; and a ceiling-screened run's
   report does not mark which statistics were computed before the screen. Seal state remains **UNOPENED**;
   execution remains **RELEASE-BLOCKED**; nothing here authorizes a run.
   **Carried forward, NOT superseded — the registered condition ceiling.** The 2026-07-29 entry below opened
   this as a new item, and removing the representability guard makes it more load-bearing, not less: that guard
   incidentally rejected an extreme block-scale imbalance, and nothing now does. Measured 2026-07-31 on the
   exhibit from the deleted `test_one_over_scaled_factor_block_is_rejected…` (that file's `_make` at seed 6,
   `z` with the ESM block scaled by `1e6`): `rank_diagnostics` reports full rank with condition number
   `3.71e12` against `10.4218` for the same bank unscaled, and `identify_operator(lam=1e-3)` now returns a
   finite estimate with no rejection where it previously raised. That estimate is not wrong — it is the exact
   ridge solution for that design — so this is a scientific admissibility question, not a numerical one, which
   is precisely why the old guard's coarse answer should not be reinstated. The available signal is unchanged:
   the condition number is exactly scale-invariant under a UNIFORM rescale (`10.4218` at `1x` and at `1e6x`)
   but moves 11.55 orders of magnitude under this block imbalance, and `diagnostics2`'s `isfinite` check still
   fires iff `rank < sym_dim` (`rank_diagnostics` returns `inf` exactly then). A ceiling is
   a registered numerical criterion — a new config field that moves the digest — and is still deliberately not
   invented here. **Open item, owner decision.**
   The remainder of this 2026-07-29 entry is retained as historical analysis of
   the replaced guard, not a description of current execution.
   **2026-07-29 unrepresentable-ridge guard (historical; superseded above):** the open item was resolved without
   registering a new numerical criterion. `identify.py` now rejects a positive `lam` that leaves ANY Gram
   diagonal entry unchanged by `lam*I` — on those coordinates the design solved carries no penalty, so it is
   not the registered `(Phi^T Phi + lam I)`. Exact equality, no tolerance, so `config_sha256` and `run_id` do
   not move; `SingularDesignError` is also now a contracted pre-seal rejection (exit 10) because phase2a's
   post-selection fit on the FULL calibration design runs outside OOF selection's handler and, the full pair
   set being a superset of every train fold, trips first as factor scale rises.
   **Rejecting on ANY coordinate rather than all of them is the load-bearing choice.** `z` concatenates an
   expression and an ESM block, so an over-scaled single block loses the penalty only on the basis elements
   involving it; an all-coordinates rule cannot fire while the SMALLER block stays below the loss threshold —
   and that block is the one input whose scale nothing upstream bounds. The stronger phrasing this entry
   previously carried ("provably cannot fire on a block imbalance") is **withdrawn as unproven**; the
   counterexample first offered for it (expression x1e4 AND ESM x1e6) was then shown not to isolate an
   imbalance — it is a uniform x1e4 rescale times a ratio-100 imbalance, and the smaller block alone already
   loses all of its own coordinates — so no counterexample is claimed. The load-bearing conclusion, that ANY is
   strictly more sensitive than ALL, does not depend on either. It also makes the safety argument reproducible from committed evidence: since
   `d_ii <= n_pairs * max||z||^4`, a FLOOR on the firing scale follows from the pair count alone, without the
   Gram spectrum; where the guard actually fires is spectrum-dependent and sits above that floor. That inequality is a theorem, not a sample: `_sym_to_vec` is a Frobenius isometry, so a design row
   satisfies `||row||^2 = (||z_g||^2 ||z_h||^2 + (z_g . z_h)^2)/2 <= max||z||^4` by Cauchy-Schwarz, and
   `d_ii <= sum_i d_ii = sum_pairs ||row||^2`. The constant 1 is sharp (attained by `z_g = z_h = M e_1` on every
   pair). An earlier draft asserted the same inequality with constant 2 and justified it by a sampled worst
   ratio — quoted inconsistently as 0.054 here and 0.094 in the commit message; both are withdrawn. The
   sampled ratio was ~5-9x below the true supremum and would have given false comfort had the constant been
   chosen from it. Combining the sharp constant with the exact rounding law (`fl(d+lam) == d` iff `lam < ulp(d)/2`, or
   `lam == ulp(d)/2` with `d`'s last mantissa bit even — the compressed `<=` form this entry previously used is
   **false at the tie**, e.g. `lam = 2^-53` against `d = 1 + 2^-52`; the derived floors are unaffected because
   `53 + log2 lam` is non-integral for all three registered lambdas, so loss needs `d >= 2^ceil(53 + log2 lam)`) gives the exact floors at 41 calibration
   pairs: `max||z|| = 809.35` for `lam=0.001`, `1361.15` for `0.01`, `2289.17` for `0.1`. The floor is a
   property of the pair set PASSED, not of the guard: at 131 eligible pairs it falls to 605.36. Only
   `cal_idx_pairs` (41) and its OOF train subsets ever reach the estimator, so 41 is the operative count. **Quantitative claims from the first draft of this entry are withdrawn.** Independent review
   refuted them. (i) The thresholds were NOT measured at the real geometry: `real_norman_phi_rank_report.json`
   records pair counts, rank, condition number and a factor-bank *checksum* — no factor values — and no
   factor bank is committed anywhere, so the Gram diagonal spread that sets the upper edge cannot be derived
   from committed evidence. A surrogate matched only on (41 pairs, `sym_dim`) is spectrum-dependent: reviewers
   measured the all-coordinates threshold at `4.6e3` for a flat `Z` but `2.7e4`–`7.7e4` at a spectrum matching
   the recorded `cond(Phi)=484`. (ii) `|z| <= sqrt(1500)*log1p(1e4) ~= 356` and the derived `|z| <= ~202` are
   **not bounds**: `z` is a projection of a GENE-CENTERED shift, so the cap is `2*(1-1/n_genes)*max||delta||`,
   and a reviewer drove the production `build_gene_factors` to `max|z| = 703.66` on an admissible input at the
   same per-gene cap. `median_library` is derived at runtime and registered nowhere, so `1e4` is an assumption
   too. (iii) `|z| ~ 3.8` "recorded in" `real_norman_detectable_effect_report.json` is withdrawn: that report
   records the GI-residual L2 (`mean_pair_eps_l2 = 3.046`), not any delta or factor magnitude, and no committed
   artifact records `z`. **What survives:** no fit in this repository's synthetic corpus fires the guard — instrumentation found
   every non-deliberate positive-`lambda` fit fully penalized. The stronger claim this entry previously
   bolded, "the guard cannot fire on realistic data", is **withdrawn as unsupported and self-contradictory**:
   it is a margin statement against realistic `||z||`, which the same paragraph then says cannot be made. Using
   **A replacement exhibit is deliberately NOT offered.** A later review refuted the one first written here
   (expression at `703.66` plus an ESM norm of `~400`, quoted as firing at `lam=0.001`): `809.35` is a floor
   derived from the UPPER bound `d_ii <= n*max||z||^4`, so reaching it is NECESSARY, not sufficient — equality
   needs the whole diagonal mass in one coordinate, which splitting mass across two blocks forbids. Measured
   through the production `design_matrix`, that configuration gives `d_max = 0.070 * 2^44`, and even the
   all-mass-in-one-coordinate value `41 * 703.66^4 = 0.571 * 2^44` is below the threshold: it does not fire.
   The band where the FULL Gram loses the penalty while no OOF train fold does EXISTS as a theorem (train folds
   are subsets, so the full diagonal dominates elementwise) and its consequence is a contracted pod-time exit 10
   after the futility checkpoint; its WIDTH is surrogate-specific and no figure for it is registered here.
   What remains, therefore, is only this: **the ESM-block scale is bounded by nothing committed, so no statement
   about firing on real data — in either direction — is available, and measuring that scale belongs on the
   pre-pod list.** The only spectrum-free statement available
   is the theorem floor above (`809.35` for `lam=0.001` at 41 pairs); surrogate spectra put the actual ANY
   firing scale higher still, but over 1200 surrogates review measured it spanning `1.5e3`-`4.3e3`, so no
   narrower band is quotable and none is claimed here. No margin is stated against realistic `||z||`, because
   per (iii) no committed artifact records it. `703.66` is reproduced exactly through the production
   `build_gene_factors` and equals `2*(1-1/73)*sqrt(1500)*log1p(1e4)`, and `41 * 703.66^4 = 1.00516e13 < 2^44`,
   so **no coordinate can lose any
   registered lambda at that scale with 41 pairs** — the "704 > 484 leaves partial loss unprovable" claim of the
   previous draft is withdrawn as an artifact of the 2x-loose constant. **But `704` caps the EXPRESSION BLOCK
   only.** `z` concatenates expression and ESM scores, and this entry's own residual gap is that nothing bounds
   the ESM block, so `704` is not a cap on `max||z||` and no global safety statement follows from it. Two
   earlier margin statements are also corrected: they were quoted against the all-coordinates threshold, which
   is not the criterion shipped.
   **Correction to the shipped scope claim.** The first draft said a partially-rounded ridge "remains the
   rank/condition gates' job". That is **false** and both reviews refuted it independently: the OOF rank policy
   is keyed to the literal `lam == 0.0` and never runs for a ridge candidate, and `rank_diagnostics` uses a
   tolerance relative to `sigma_max` and is therefore exactly scale-invariant (identical to 15 digits across 18
   orders of magnitude of `||z||`). There is no condition-number *ceiling* anywhere in the repository:
   `diagnostics2`'s `isfinite(condition_number)` check fires iff `rank < sym_dim`, i.e. it is the rank gate
   restated. **New open item:** a registered condition ceiling would detect block-scale imbalance with wide
   margin (real reports are 15.8 / 32.9 / 484; a pathological bank measured 4.3e12), but it is a registered
   numerical criterion — a new config field that moves the digest — and is deliberately not invented here.
   Note the first draft also claimed the recorded condition number "is scale-invariant and cannot detect this
   class of defect at all"; that holds for a UNIFORM rescale but is false for a block imbalance, where the
   condition number does move.
   Three further findings are recorded rather than acted on. (a) The earlier reading that a bypassed candidate
   would merely produce garbage and lose selection is **withdrawn**: with the guard mutated out, the bypassed
   `lam=0.001` candidate ties on theta and the registered tie-break resolves ties to the LARGER lambda, so
   selection actively *prefers* it and the run records a `selected_lambda` it never applied. Reviewers note the
   exact tie is fixture-specific (the fixture is noiseless); under noise the bypassed candidate ties less often
   but still wins outright in a minority of seeds. (b) On the real 41-pair calibration set at `k_total=8`
   (`sym_dim` 36), `sum_f train_f = n_pairs + S <= 82 < 108` where `S` is the number of pairs internal to a
   single held-out group, so **at least one of the three gene-disjoint folds cannot reach 36 train pairs** and is rank-deficient by construction; the `lam=0.0` candidate at `k=8` is then
   expected to be recorded non-viable on real data, because `_oof_theta_for_candidate` raises on the first
   deficient fold. A previous draft of this entry derived "at most ONE fold can reach 36, so at least two are
   rank-deficient" from the same inequality; that entailment is **false** (`72 <= 82`, and review exhibited a
   layout with two folds at 36 realizable under the production builder) and is withdrawn. The downstream
   prediction is unaffected. This is pre-seal observable, and it is the regime where the ridge is load-bearing;
   it also rules out applying the rank policy to every lambda, which would delete that regime. (c) In the
   swallowed FULL-RANK regime the float result is bit-identical to normal-equation OLS and matches the exact
   ridge to ~1e-15 at the recorded spectra, so there the failure is provenance — a recorded `selected_lambda`
   never materially applied — rather than numerics. A previous draft went further and said numerical damage is
   "confined to the rank-deficient case"; that is **withdrawn**, because full-rank but ill-conditioned swallowed
   designs reach O(1) relative error against the exact ridge. The `~1.6e-4` coefficient-error figure quoted in
   that draft is also **withdrawn**: it is not reproducible at any recorded spectrum (`cond(Phi)` 15.8/32.9/484
   give ~1e-14), requires `cond(Phi) ~ 3e6`, and is ordinary ill-conditioning rather than penalty loss. The
   provenance hazard is likewise not confined to the swallowed regime. On one anisotropic surrogate, review
   measured the ridge ceasing to change the fit by more than `1e-6` relative from `max||z|| ~ 116` while the
   guard did not fire until `~2.3e3`-`5e3` — a band in factor scale where the registered lambda survives this
   check (applied to within the quantization noted in `identify.py`, never exactly) and is nonetheless
   immaterial. The band's width is surrogate-specific and no figure for it is
   registered here; what matters is that it exists and the guard cannot see it, which is a second reason for
   the condition-ceiling open item above. One determinism note, analogous to correction (4) of the preceding
   entry: `n_lost` is computed from the float Gram, so at the exact boundary the verdict can depend on
   summation order. One review reproduced verdict flips by reversing pair row order (902 of 16000 probes); a
   second confirmed that the order changes `d_max` but did not reproduce a flip, so the claim is recorded as
   mechanism-confirmed and **frequency-unsettled**. It requires `d_max` within a few ulps of the boundary and is
   unreachable at the scales real data occupies. No ulp-spread or flip-rate figure is registered here: the "6
   ulps" once recorded was a sample maximum, a later review's "7 ulps / 25.8%" replacement was shown to swing
   from 14.6% to 50.8% with the number of row orders sampled per design — an unrecorded parameter — so both are
   withdrawn rather than re-stated, and the frequency stays unsettled. Finally, "the
   run identity does not move" is literally true but incomplete: the criterion is code-only and therefore
   invisible in the confirmation manifest's `selected_hyperparameters`, unlike the registered
   `unregularized_oof_rank_policy`; scientific mode pins `HEAD == approved_git_sha`, so the owner SHA pin must
   be regenerated regardless. Seal state remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.
   **2026-07-31 — scientific stage-1 `factor_bank.json` is now a bound artifact, not a stub.** Recorded here
   because it changes a MANDATORY pre-seal input contract, independently of the ridge-solver work above. The
   scientific carrier previously left `Phase2aInputs.factor_banks_by_k` unset, which
   `_verify_factor_banks(require_banks=True)` rejects — and scientific execution is exactly
   `fixture_execution=False` (`phase2a.py:1410`), so the scientific path could not have completed Phase 2a.
   `carrier_loader._load_phase2a_inputs` now takes `require_factor_banks` and, for scientific mode,
   deserializes `factor_bank.json` through `zfactor.deserialize_factor_bank_collection`: a closed-schema
   `compose_factor_bank_collection_v1` payload carrying one lossless, self-checksummed `GeneFactorBank` report
   per `k_total`, whose aggregate digest must equal `phase2a_inputs.factor_checksum`. The loader additionally
   re-verifies the reconstructed `Phase2aInputs.content_checksum`, which is the only semantic check standing
   behind the spec's byte digests once a forger re-signs both the file and `self_checksum`; a regression test
   defeating both byte layers now pins it (`test_scientific_carrier_rejects_resigned_phase2a_inputs_field_edit`).
   Fixture mode is untouched (`require_factor_banks=False`, old thin payload). **Consequence for the pod:** any
   producer of a scientific PREPARE carrier must emit the collection via
   `zfactor.serialize_factor_bank_collection`. No such producer exists in `src/` or `scripts/` — as is true of
   every other scientific stage-1 artifact, whose only writer today is the test-support module — so this changes
   what that future producer owes, not the current inventory. The as-built plan snippet in
   `plans/2026-07-12-compose-scientific-prepare-carrier.md` (Task 1) prescribed the retired three-key stub and
   now carries a dated supersession banner.
   **2026-07-29 config-bound evidence lineage (survey only; nothing regenerated):** the two committed
   activation-evidence reports both embed `config_sha256 = d8c65ac4…`, which the current config no longer
   produces. Recomputing `sha256_json(raw)` at every commit that touched
   `configs/compose_k562_v1_phase2.yaml` gives the full lineage: `d8c65ac4…` (the digest the reports were
   generated against at `82a9c83` / `79b01e0`, still current at `0d84d3a`) → `380c4528…` at `d507a09`
   (**the activation commit itself**, `status: preregistered_activation_blocked → active`, which the config header already
   flags as intentionally moving run identity) → `a4700194…` at `42d71ce` (predictions/execution-manifest
   envelope) → `c3e00327…` at `90bc100` (estimator-domain solver and rank policy). **Correction:** an earlier
   note framed this as a single move `a4700194… → c3e00327…` caused by registering the estimator domain. That
   is incomplete — the evidence has been three digests stale since activation on its own, and the
   estimator-domain registration only added the third move. Nothing here is a leakage or seal risk: scientific
   mode is already fail-closed on all three binding axes (`protocol`, `config_sha256`, and
   `git_sha == approved_git_sha`) in `config2.py`, both reports carry `activation: BLOCKED`, and the mismatch
   path has regression tests in `test_config2.py` and `driver/test_scientific_activation_assembly.py`. Exactly
   two requirements carry this JSON lineage contract (`_CONFIG_BOUND_EVIDENCE_REQUIREMENTS`):
   `real_norman_phi_rank_and_condition_report` and `regime_specific_detectable_effect_analysis`; the remaining
   activation requirements point at heterogeneous artifacts and do not. **Regeneration is not a local task.**
   It needs real Norman data (pod) and, because the `git_sha` axis pins the report to
   `activation_record.approved_git_sha`, the reports must be produced at the exact commit the owner approves —
   which is why the §2.5 release-gate ordering (generate at clean detached `C` → publish to the external
   durable stage → owner approves `C` plus every byte hash) exists rather than committing regenerated evidence
   back onto the branch. Seal state remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.
   **2026-07-25 leakage-guard corrections (branch `compose-network-isolation`, merged as `d4c1ea8`):**
   two development-boundary
   guards were found failing open and were fixed with mutation-verified regression tests. (1) The measurability
   gate blacklisted `secondary_sealed`, a role name that exists nowhere else in the protocol; the real second
   sealed role is `sealed_single_unseen`, so the single-unseen regime passed a tripwire that was only ever
   checking a phantom. The gate is now an allowlist over the registered calibration role with a mandatory
   explicit role argument, and decision-bearing sealed-role references are now bound by semantic constants from
   one canonical roster rather than spelled out per call site or indexed positionally out of `ROLE_NAMES`.
   The config loader independently asserts exact parity with that roster. Role label values are
   unchanged, so no run identity moves. (2) Both recursive leakage scanners skipped numpy string/object arrays
   entirely; extending them to scan those arrays exposed a second fail-open, because the visited set is keyed on
   `id()` and the newly materialised temporaries let CPython recycle a freed address into a later temporary that
   was then skipped unscanned. Visited objects are now pinned for the walk. Neither guard is the primary seal —
   the outcome store's one-time claim covered both sealed roles throughout — but both are development-boundary
   walls that must not fail open. A clean commit and independent review at the exact SHA remain mandatory. Seal
   state remains **UNOPENED** and execution remains **RELEASE-BLOCKED**.
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
4b. **✅ CLOSED 2026-08-13 — the registered `lambda_grid` is now RELATIVE** (`identification.lambda_scaling: calibration_sigma_max_squared`; owner-approved, implemented, 13/13 mutations killed; `config_sha256` → `3faacaff…`). Two residuals remain and are listed in `2026-08-13-compose-factor-scale-normalization-proposal.md` §8.1: `id_only` keeps an absolute lambda, and whether the registered grid VALUES suit the real design's `cond` is a separate question, now answerable from committed evidence via `f = 1/(1+λ·cond²)`. The original entry is preserved below as written. ~~⛔ OPEN — the registered `lambda_grid` is an ABSOLUTE penalty and nothing bounds `‖z‖`~~ (task #43,
   owner decision). `cond(Phi)` is invariant to a uniform rescale of `z` while `identification.lambda_grid` is a
   fixed absolute penalty, and `Phi` is bilinear in `z`, so `z → cz` makes the effective penalty `λ/c⁴`. Measured
   2026-08-07 on the committed exhibit at IDENTICAL `cond(Phi) = 6.4732…`: rescaling the factor bank by 100 moves
   `theta(lam=0.001)` from `0.8103235465139835` to **`-3340344.0205271696`**. Nothing bounds `‖z‖` — `zfactor`
   returns raw centered PCA scores concatenated with the ESM block, `factor_z` has no scale field, and no
   activation evidence records a scale statistic. **Consequence:** the registered conditioning ceiling cannot tell
   whether the registered `lambda_grid` lands in a healthy window on the real Norman bank, and a numerical cause
   can therefore flip the REGISTERED futility condition `oof_theta <= dev_oof_threshold`. This is a PRE-EXISTING
   protocol gap (absolute grid + unbounded `‖z‖` predate the fold-conditioning branch, which discovered it), and it
   is **enumerated here rather than left in a correction narrative** because three review rounds judged narrative
   placement wrong for something a pod operator must see. Options, none taken — **and the first one does not
   close the gap**: record a scale statistic in the phi-rank activation evidence (cheapest and
   `config_sha256`-neutral, but **observational only** — no registered rule interprets it, so it makes the gap
   visible without deciding anything); **register an admissibility rule** on a scale-invariant quantity such as
   `lambda_min / sigma_max²` (the option that actually closes it); add a `factor_z` scale field or normalization
   (**moves the config digest, hence `run_id`**); or record explicit owner acceptance as a non-blocker.
   **A concrete proposal for closing this now exists and is unsigned:**
   `2026-08-13-compose-factor-scale-normalization-proposal.md` (normalize so `sigma_max(Phi) = 1`, pin the
   scalar in evidence; measured to leave `cond`/`rank` untouched and to remove the scale-dependent collapse).
   Full costing, and the measurement showing `lambda/sigma_max²` moving eight orders at constant `cond(Φ)`:
   `2026-08-12-compose-conditioning-ceiling-decisions.md` §4. Detail and the `λ/c⁴` derivation: the 2026-08-07
   conditioning-ceiling entry below.

   > **[2026-08-12 correction to the option costs above, and a precision note.]** The three options are now costed
   > in `docs/superpowers/2026-08-12-compose-conditioning-ceiling-decisions.md` §4, which the owner signs. Two
   > corrections, both found by reading the source rather than the record. **(1)** This entry called the first
   > option cheapest "because `sigma_max` is already computed by the registered rank-tolerance rule, and task #14
   > regenerates those reports anyway". `sigma_max` *is* computed (`src/alive/compose/identify.py:70`, as
   > `svals[0]` inside the tolerance) but is **not exposed on `RankReport` and not emitted**, and
   > `_FACTOR_BLOCK_KEYS` is an **exact** roster enforced by `_exact_object` — so requiring the key invalidates the
   > committed `real_norman_phi_rank_report.json` and needs either a schema bump with the validator accepting both
   > versions, or regeneration on the pod against real Norman data. The option is genuinely digest-neutral; it is
   > **not** nearly free, and it is **not** checkable from currently committed evidence. **(2)** The collapse figure
   > is quoted above to 17 significant digits. Re-measured 2026-08-12, θ at this scale carries about **14** digits
   > (relative spread `1.03e-14` across mathematically inert outcome rescales), and the value this construction
   > reproduces differs from the one recorded here by exactly 1 ulp. The magnitude — `θ ≈ -3.34e6` — is the
   > finding; the trailing digits are not evidence, per the precision rule this project adopted after a `rel=1e-12`
   > pin went green on macOS and red on Linux.
   >
   > **[2026-08-12, second correction — from an independent read-only audit.]** Two further defects in the
   > paragraph above, both confirmed by re-running rather than by reading. **(3)** Recording `sigma_max` is
   > **observational and closes nothing**: measured at constant `cond(Φ) = 6.47321643414`, rescaling the bank by
   > `c ∈ {1, 10, 100}` moves `lambda/sigma_max²` from `4.84e-06` to `4.84e-14` while θ goes `0.810` → `0.403` →
   > `-3.34e6`. `sigma_max` is exactly the quantity that tracks the danger, but no registered rule interprets it,
   > so a pod operator reading it gets no verdict. Listing it as "cheapest" invites choosing it and believing the
   > gap closed. A fourth option — a **registered admissibility band on `lambda/sigma_max²`** — is what closes it.
   > **(4)** "digest-neutral" was glossed as "no new run identity". Precisely: the composite `run_id` binds config,
   > data-card, raw/source and sequence-mapping digests and **does not include the Git SHA**, so `run_id` is
   > unchanged — but the Git SHA moves and `phi_rank` validates `git_sha == expected_git_sha`, so the
   > activation-evidence lineage does move. "Digest-neutral" is true of the **config axis** only.

5. **§2.5 release gate** — worker locked-env integration green + 독립 검토 후 exact commit `C`를 마지막
   repository commit으로 동결한다. Clean detached `C`에서 bias report → single-leaf finalized config →
   analytical reports를 external durable stage에 게시하고, owner가 `C`·모든 byte hash·immutable object
   version을 canonical ResolvedRunSpec과 publication manifest로 승인한다. Generated evidence/final config/
   READY 표기를 후속 commit하지 않는다(HEAD 이동 및 Git/report 자기참조 방지).
6. **A100 sealed-run pod: runbook 실행** — 유효한 owner-approved external ResolvedRunSpec,
   `ActivationRecord`(requirement별 non-empty staged evidence), staged finalized config와 clean detached `C`
   하에 `phase2a → preflight → phase2b --confirm-seal`. **COMPOSE seal 1회 개봉** — `TG-K562`와 독립.

---

**2026-08-12 — L4 (owner decision D4) CLOSED: the kernel-isolation receipt now records its interpreter.**
Receipt schema `compose_kernel_isolation_ci_receipt_v1` → `_v2`, adding an `interpreter` block of
`platform.python_version()`, a whitespace-normalised `sys.version` build string, and
`sys.implementation.name`. This closes the open item recorded above: the receipt named the runner's OS,
architecture and kernel release but never the interpreter, and `.python-version` carries only a minor series,
so no committed proof could say which CPython patch release produced it. Read **in-process**, not passed on
the command line, so there is no argument surface through which it could be misdeclared; the honest scope is
the receipt-**building** process, which shares the locked environment with the suite but is not literally the
same process, and the docstring says so.

**`v1` stays readable, deliberately.** Both committed archives embed `v1` receipts, their source artifacts
expire, and the `v1` archive is the one carrying the independent Codex grade — a validator that stopped
reading `v1` would retire durable evidence nobody can regenerate. Both were validated **directly** against the
new validator, not merely via the suite. The roster is selected **by** the declared schema and then enforced
exactly, so a `v1` receipt smuggling an `interpreter` and a `v2` receipt omitting one are both refused, and an
unrecognised schema resolves to no roster at all rather than falling through to one that happens to fit.
**No re-archive is forced:** `kernel_isolation_ci.py` is not in `_ISOLATION_CLOSURE`, so the archived kernel
property is untouched.

**The version/build cross-binding is `startswith`, not equality, and that is load-bearing.** On a release both
fields read `3.12.13` and equality would hold; on a pre-release `sys.version` carries `3.13.0rc1` while
`platform.python_version()` reports `3.13.0`. Because a red suite skips the receipt-build step and the upload
then fails closed, an over-strict check here would not warn — it would take the only kernel-property gate this
project has offline, the same cascade the `fetch-depth: 1` defect produced. The weaker predicate still pins the
full patch level, and a different release is still refused.

**🔑 Two mutations survived the first version of the tests, and they are the reason this entry exists.**
Replacing `platform.python_version()` with the literal `3.12.13`, and `sys.implementation.name` with
`cpython`, passed the whole suite — because on this machine **the constant IS the correct answer**, so every
assertion comparing the receipt to today's interpreter was satisfied, *including* a comparison against
`interpreter_identity()`, which the mutation moves on both sides at once. The interpreter cannot be
parameterised away, so the discriminating property is **FOLLOWS, not MATCHES**: monkeypatch the interpreter to
values no real CPython here reports and require the receipt to move with them. Harness committed at
`scripts/compose_receipt_interpreter_mutation_harness.py` (**14 mutations, all killed, each attested by a
NAMED failing test**); it is a sibling of the conditioning harness rather than a refactor of it, because that
one backs a standing 37-mutation record.

Seal state remains **UNOPENED**; execution remains **RELEASE-BLOCKED**. A receipt schema is dev-boundary
provenance and authorizes no run.

**2026-08-12 — L5 (task #16) LOCAL HALF only: instructions for the independent archiver.**
`runbooks/2026-08-12-compose-kernel-archive-independent-archiver.md`, cross-linked from runbook §2.5. It
gives a third party the procedure, the refusals (no hand-assembly, no metadata-only archive, no archiving
someone else's download), what the tool machine-checks versus what rests on their care, and how to write
`archived_by` — the one field validated only as a non-empty string. **Task #16 stays OPEN:** engaging an
actual independent party is the owner's step and no document substitutes for it. The motivation is now a
measurement rather than a worry — the `614017b6…` archive's source artifact expired `2026-08-08`, so its
`runner.*` / `head_sha` / `run_id` / `source_artifact` are **already** unverifiable by anyone; `2dd23d6…`
expires `2026-10-24`. Both windows predate the 400-day retention raise, which protects only later runs.

**2026-08-12 — independent read-only audit at `1d19729`: two findings that outlive the decision record.**
Six of its findings landed on `2026-08-12-compose-conditioning-ceiling-decisions.md` and are fixed there (§7.1
adjudicates all nine, including one that did **not** reproduce). Two are about the tree and are recorded here:

- **✅ DECIDED 2026-08-16 — the rank rule STAYS `ALL`** (decision #5,
  `2026-08-16-compose-activation-rank-rule-decision.md`; implemented, 20/20 mutations killed). The
  original entry is preserved below as written, followed by the correction that changed its grading.
  ~~⚠️ OPEN (owner decision)~~ — **activation requires full rank at EVERY `k`, runtime does not.**
  `phi_rank.py:249-252` refuses the entire report unless every registered grid point is full rank, while the
  conditioning ceiling **in the same loop** deliberately uses an **ANY** rule — a single over-ceiling `k` is
  screened out of selection and the study proceeds. The code comment argues for ANY on the ceiling, and that
  argument applies verbatim to rank. The mismatch is **fail-closed**: it can only block a run that runtime would
  have tolerated, never admit a bad one — so it is an over-strictness, not a safety hole, and it is graded below
  the audit's IMPORTANT. It is reachable in principle: `rank ≤ min(n_pairs, sym_dim)`, so with fewer calibration
  pairs than `sym_dim(k=8) = 36` that block can never be full rank and the report becomes uncertifiable even
  though `k=4`/`k=6` are admissible. The real pair count is **pod-gated and unmeasured locally**. **Not changed
  here:** making rank use ANY would relax a registered gate, which is an owner decision, not a drafter's.

  > **[2026-08-16 correction — the pair count was neither pod-gated nor unmeasured.]** The clause
  > "pod-gated and unmeasured locally" above is wrong, and correcting it changes how the item should be graded. `n_combo_calibration` is committed
  > at `docs/activation-evidence/compose/real_norman_phi_rank_report.json` (real Norman, A100, `git_sha
  > 82a9c83`): it is **41**, and the same report records `rank = sym_dim` at **every** registered `k`
  > (`10/21/36`) with condition numbers `15.8 / 32.9 / 484.2`, five to seven orders below the registered
  > ceiling `1.0e+8`. **So the ALL rule is dormant on the real design** — it and an ANY rule accept this
  > report identically — and the audit's reachability scenario (fewer than 36 calibration pairs) does not
  > arise. The count is also not a draw: `build_pair_split` is a `PCG64(split_seed=11)` permutation over the
  > UTF-8-sorted gene set at `calibration_fraction: 0.6`, so it moves only if the eligible-pair universe or
  > those fields move — each already a new run identity. **Second, on the measured design the mismatch runs
  > the OPPOSITE way from the grading above.** Activation checks rank on the full 41-pair calibration design
  > at every `k` and no `lambda`; runtime checks `require_full_rank_each_train_fold` on 3 gene-disjoint TRAIN
  > folds and only at `lam == 0.0` — different matrices. By the 2026-07-30 counting bound re-derived here
  > (`sum_f train_f = n_pairs + S <= 82 < 108 = 3·sym_dim(k=8)`), at least one fold has `<= 27` train pairs and
  > is rank-deficient by construction, so `k=8`/`lam=0.0` is expected **non-viable at runtime while activation
  > certifies it**. A costed proposal covering both points is unsigned at
  > `2026-08-16-compose-activation-rank-rule-decision.md`; it recommends keeping ALL and is **task #48**.
  > This correction is to a claim about what is known — no registered value, outcome or hash is refreshed.
- **Mutation-harness limitation, recorded not fixed.** The `returncode`-as-kill defect was fixed on 2026-08-11
  (a kill now requires named failing tests; a nonzero exit with none reports `INVALID`). The residual: a kill is
  not checked for **relevance**, so a mutation that breaks an unrelated test is still recorded as killed. Both
  committed harnesses print their killing tests, so the check is available to a reader but is not mechanical.

The audit's release verdict stands and is independent of all of the above: six registered config blockers and
`INCOMPLETE` dependency evidence keep execution **RELEASE-BLOCKED**; seal remains **UNOPENED**.

**2026-08-13 — task #43 CLOSED: the registered `lambda_grid` is RELATIVE, not absolute.**
`identification.lambda_scaling: calibration_sigma_max_squared`; the applied penalty is
`lambda * sigma_max(Phi_cal)²`. Owner-approved after a costed proposal
(`2026-08-13-compose-factor-scale-normalization-proposal.md`). **⚠️ `config_sha256` moved
`b158417a…` → `3faacafff963b221148a08cb18fb92f084d796fb80c5db2b3b3b25ea295cb3b9` — a NEW run identity,
which this decision was approved to create. Task #14 therefore REGAINS its mechanical trigger:
activation evidence binds on `config_sha256`, so the committed config-bound reports are stale again
and must be regenerated on the pod at the new digest.**

The defect restated: ridge is not scale-invariant and `Phi` is bilinear in `z`, so an absolute penalty
acts as `lambda/c⁴` while nothing bounds `‖z‖`. Measured — at the committed exhibit's own scale the
whole registered grid was nearly inert (weakest filter factors `0.9998/0.998/0.980`); at `c=100` it was
indistinguishable from `lambda=0` and `theta(0.001)` collapsed `0.8103` → `-3.34e6`; and the SAME
absolute lambda was inert on the full design while dominant on a degenerate fold. It also meant
different things across the registered dimension grid (`cond` `2.90 → 6.38 → 19.00` at k=4/6/8),
confounding the dimension choice with regularization strength.

Applied at **both** solve sites — OOF selection and the final fit — since a rule applied to only one
would make the recorded `selected_lambda` different from the penalty that was scored. `sigma_max` is
**not** a new registered quantity: it is what `max_shape_times_float64_eps_times_sigma_max` already
uses. `cond` and `rank` are untouched, so the registered ceiling and rank policy keep their meaning.

**🔑 The verification mattered more than the feature.** The first test set — 18 tests reading as
thorough — left **six** mutations alive, and the two most important survived a second time *after* a
test was written specifically to kill them. Cause: this fixture's design is well conditioned, so
`lambda = 0.0` wins at every noise level tried (0.02–3.0), and with `selected_lambda == 0.0` the
scaled and unscaled penalties are **both exactly 0.0** — the assertion compared two numbers no
mutation could make differ. Guarding `scale != 1.0` had covered the analogous hole one variable over.
Fixed by parameterising the grid off `0.0`. Also: `M4` was not an equivalent mutant (a NaN bank makes
`svd` RAISE; an INFINITE one converges and returns `nan` — two inputs, two branches), and `M5` was
never run at all because its anchor matched three sites, visible only because a skip counts as a
survivor. Final: **13/13 killed, each by a NAMED failing test.**

Two residuals are carried forward, not closed: `id_only` keeps an absolute lambda (its feature is
linear in `z`, so this scale would not make it invariant; changing a baseline's fit needs its own
justification), and whether the registered grid VALUES suit the real design is a separate question —
now answerable from the `cond` already in phi-rank evidence via `f = 1/(1 + lambda·cond²)`.

Verified: full compose **2058 passed, 2 skipped**; ruff check and format clean. Seal remains
**UNOPENED**; execution remains **RELEASE-BLOCKED**.

**2026-08-16 — task #48 DECIDED: activation's rank rule stays ALL, and the audit's premise was
measurable all along.** The audit graded this item on "the real pair count is pod-gated and
unmeasured locally". It is committed, from a real Norman A100 run: `n_combo_calibration = 41`, with
`rank == sym_dim` at every registered `k` (`10/21/36`) and condition numbers `15.8 / 32.9 / 484.2`
against the registered ceiling `1.0e+8`. **The ALL rule is therefore DORMANT on the real design** —
it and an ANY rule accept that report identically — so relaxing a registered fail-closed gate would
have bought nothing measurable. The count is not a draw either: it is a `PCG64(split_seed=11)`
permutation over the UTF-8-sorted gene set at `calibration_fraction: 0.6`, so it moves only if the
eligible-pair universe or those fields move, each already a new run identity.

**⚠️ The mismatch that IS live runs the other way, and is recorded here because a pod operator must
see it.** Activation checks rank on the full 41-pair calibration design, at every `k`, at no
`lambda`. Runtime checks the registered `unregularized_oof_rank_policy:
require_full_rank_each_train_fold` on each of the **3 gene-disjoint TRAIN folds**, and only at
`lam == 0.0`. Different matrices — so matching the quantifier would not have aligned them. By the
2026-07-30 counting bound, re-derived rather than cited (`sum_f train_f = n_pairs + S <= 82 <
108 = 3·sym_dim(k=8)`), at least one fold has `<= floor(82/3) = 27` train pairs and is
rank-deficient by construction at `k=8`. At `lam == 0.0` the guards run as a whole-candidate
pre-pass, so one deficient fold is enough: **`k=8`/`lam=0.0` is expected non-viable at runtime while
activation certifies `k=8` as full rank.** Not closed by this entry. `k=6` needs `S >= 22` and is
neither excluded nor established; both are layout-dependent and pod-observable. If `k=8` does prove
non-viable, dropping it from `total_k_grid` is a **config change with a new run identity** and is not
pre-authorized.

The price paid for keeping ALL was making its refusal legible. Eleven distinct clauses shared one
message, so an operator stopped by this gate could not tell a RANK DEFICIENCY — the one cause whose
remedy is a config change rather than "regenerate the report" — from a pair-count mismatch or a
malformed condition number. They are now eleven messages in `_validate_factor_block`, with the
accepted set **unchanged**: same conditions, same short-circuit order, same `ValueError` type, each
asserted by its own test rather than assumed. An existing `config2` test had been matching the old
shared string and so was really asserting "something about that block was wrong"; it now names its
clause, and a sibling covers the rank cause end to end.

**🔑 The harness gained a sixth rule and it paid for itself on the first run.** The
`returncode`-as-kill defect was fixed on 2026-08-11, but the 2026-08-12 audit recorded a residual
that was left open: **a kill was never checked for RELEVANCE**, so a mutation breaking an unrelated
test still counted. `scripts/compose_phi_rank_cause_mutation_harness.py` closes it — every mutation
names the test whose OWN NAME makes its claim, and a kill by anything else alone reports
`IRRELEVANT`. Building that table found exactly the gap it was designed to find: **three tests had
no mutation at all** (the exception-type assertion, the committed-evidence anchor, and the
`genes_before_condition` ordering case), so nothing had ever confirmed they could fail. They became
M18–M20. Final: **20/20 killed, each by the named test that makes its claim**; M15 and M20 are killed
by their ordering test and nothing else.

The `config_sha256` is **unchanged** at `3faacaff…`: no config field moved, no registered value
changed, and **task #14 is untouched by this wave** — it still owes the regeneration the 2026-08-13
digest move triggered. Verified: full compose **2125 passed, 2 skipped** — exactly the 2058 of
2026-08-13 plus the 66 new cause tests and the one new `config2` test, so nothing was displaced;
ruff check and format clean. Seal remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.

**2026-08-17 — external audit at `4cd2321`: four findings adjudicated by RUNNING them, and closed.**
An independent read-only audit (`docs/GPT audit/comprehensiveaudit.md`) raised 16 active findings.
Four are closed here; **three of the four were defects in this project's own three most recent waves**,
which is the part worth recording.

- **F-10 — the phi-rank artifact did not enforce exact integers, and one message was FALSE.** All three
  of the audit's claims reproduced against the validator: every count/dimension field accepted an
  integer-VALUED float (a report with `k_total: 4.0` certified READY), `n_calibration_pairs_skipped:
  False` passed as `0` because `bool` is an `int` subclass, and `rank > sym_dim` was refused with the
  message *"rank 37 is BELOW the identifiable subspace dimension sym_dim=36"*. **The third is a
  regression introduced by the 2026-08-16 cause-split itself.** The message it replaced — "invalid or
  non-full-rank factor block" — was vague but TRUE for every cause; naming the causes made each one
  specific and made exactly one specifically WRONG. **Precision is only an improvement when it is also
  correct.** Fixed: every count and dimension now goes through `_nonnegative_int` (which already
  rejected `bool` and non-`int` and was simply not being used here), and an over-rank block is its own
  cause — `rank <= min(n_pairs, sym_dim)` holds by construction, so it is an internally inconsistent
  report, not a design that failed to span its subspace. **This narrows the accepted set**, deliberately
  and fail-closed: it is the one place the cause-split wave's "the boundary must not move" rule is
  knowingly set aside, because the boundary was wrong. The committed real-Norman evidence still
  validates unchanged.
- **F-11 — the interpreter binding did not pin the patch level, and its docstring said it did.**
  Measured: pinned at `3.12.14`, a bare `startswith` also accepted `3.12.149` and `3.12.140evil`. The
  `rc1`/`+local` tolerance is intended and correct; the defect was precisely a **digit** after the
  prefix. Closed by merging the pre-existing `fix/interpreter-patch-level-binding` (`1331e6c`), which
  requires a non-numeric suffix. That commit changed the predicate but left the falsified sentence in
  the docstring; **the docstring is corrected here and says why it is now true — the code changed, not
  the wording.**
- **F-13 / F-14 — sensitive and scratch output were untracked AND unignored.** `error.log` (427 bytes,
  carrying auth/account metadata), `output/` (208 KiB) and `tmp/` (6.6 MiB) were not matched by any
  `.gitignore` rule. Closed by merging `fix/gitignore-sensitive-and-scratch` (`362acbd`).
  **⚠️ Half-closed by design: `error.log` still exists on disk.** Ignoring it removes the
  accidental-commit path only; deleting it is the owner's action, not a drafter's.
- **F-16 — the latest readiness changes were not reproducible on `origin/main`.** Closed by merging
  `compose-activation-rank-rule` into `main` (`058e9dc`, tree-identical to the CI-green tip).

Verification: full compose **2173 passed, 2 skipped** — exactly the 2125 of 2026-08-16 plus 41 new
cause/exactness tests and the 7 interpreter-binding cases; mutation harness **27/27 killed, each by
the NAMED test that makes its claim** (M21–M27 added, one per dropped type check plus the over-rank
branch). Several older anchors moved with the refactor and the harness reported them as `ANCHOR`
rather than passing silently — the behaviour rule 6 exists for. Ruff check and format clean.
`config_sha256` is **unchanged** at `3faacaff…`; **task #14 is untouched and still owed.**

**⚠️ OPEN from the same audit, NOT closed here — two HIGH findings that require an owner amendment:**
**F-04** the registered `l3_hypernetwork` and its implementation are different models (spec §3.3 defines
L3 as a hypernetwork learning `z` and the operator end-to-end; `models.py` is a two-hidden-layer `tanh`
MLP on a **fixed** `Z`), and **F-05** the ablation ladder's `lambda` means different things per arm
(`phase2a.py` scales only the headline, so an L1↔L2/L3 comparison confounds architecture with penalty
strength — measured `159x / 557x / 2004x` on synthetic fixtures, fixture-dependent as the audit says).
**F-05 also shows the 2026-08-13 residual record was too narrow:** it named `id_only` and omitted the
ablation ladder, which is the more consequential case because the ladder is exactly what attributes
effects to architecture. Both are carried to a costed decision document. **Not adjudicated here:**
F-01, F-02, F-03, F-06, F-07, F-08, F-09, F-12, F-15. Seal remains **UNOPENED**; execution remains
**RELEASE-BLOCKED**.

**2026-08-20 — the 2026-08-19 audit edition, and a self-contradiction it found one instance of.**
The daily audit replaced its canonical file and ran against `2e60eef` (this branch), so the four
findings closed on 2026-08-17 are gone from its active list. Renumbered, it now carries High 7 /
Medium 5 / Low 2. **F-04 and F-05 remain active HIGH and remain unsigned** — decisions #6/#7 in
`2026-08-17-compose-ablation-ladder-decisions.md`.

Its **F-13** is closed here and is worth recording for the shape of the defect rather than its
severity. `phi_rank.py` asserted *"the accepted set is **unchanged**"* thirty lines above a comment
explaining that the exactness fix **deliberately narrows** it. Both sentences are mine, written a day
apart; the first was never retracted when the second contradicted it. **The audit found one site;
there are five.** Three are live contracts (the validator docstring, the test module docstring, a
section header) and are unified on the invariant that actually holds across both waves: **the
boundary has moved exactly once, and only inward — nothing this validator ever refused is accepted
today.** Two are dated historical records and are **not** retro-edited, because each correctly
describes the wave it belongs to; the 2026-08-16 decision document gets a dated pointer instead.

The general lesson, since this is the second time in four days a correction of mine outran its own
record: **when a later wave reverses an earlier claim, the earlier claim has to be retracted at every
LIVE site in the same commit** — a dated record may keep it, a docstring may not.

Verification: full compose **2173 passed, 2 skipped** (unchanged — this wave is prose only); mutation
harness **27/27 killed, each by the NAMED test that makes its claim**; ruff check and format clean.
`config_sha256` unchanged at `3faacaff…`. Seal remains **UNOPENED**; execution remains
**RELEASE-BLOCKED**.

**2026-08-20 — five registered decisions signed, and task #16 re-scoped after its urgency turned out
to be my own error.**

**Signed (owner, 2026-08-20).** Conditioning-ceiling decisions **#1, #2, #3** → `CONFIRMED`; they
change no code (all three are implemented and mutation-verified) and record the scientific
disposition. **#3 is signed as the ARM only** — the scope note attached to it is explicitly not
endorsed, because what that arm fixes is reason attribution above a noise threshold that is
unregistered and unmeasured on real data. Ablation-ladder **#6 → option B** (rename
`l3_hypernetwork`, amend spec §3.3) and **#7 → option A** (normalize the factor bank so
`σmax(Φ_cal) = 1`). **Both #6 and #7 move `config_sha256`, so task #14's regeneration must run at the
FINAL digest** — the owner has taken #14 and will regenerate once the digest is fixed.

#7's approval is annotated at the sign-off with what it commits: the bank artifact becomes
split-dependent and `_verify_factor_banks`' byte-for-byte binding needs re-plumbing, which is
seal-adjacent. **No guard will be weakened to make A fit**; if that is the only way, implementation
stops and the recorded fallback (option D — restrict the L1↔L2/L3 comparison to exploratory, no code,
digest unchanged) is raised instead.

**Task #16 — the "before 2026-10-24" urgency was wrong and is withdrawn.** This index and several
session summaries described #16 as *engage an independent archiver before the 2026-10-24 artifact
expiry*. The artifact expiring then is `2dd23d6…`, a **development** archive that was never going to
back the seal — the archiver runbook's own §1 already says retention was raised to 400 days and
protects "only runs made after the change, **including, deliberately, the one that will back the
seal**". **The seal-backing run does not exist yet**, and its artifact will live ~400 days. There is
no October deadline on this task and there never was one for the seal's purpose.

**Disposition:** the two committed archives stay as development evidence with their existing honest
`archived_by`; **no third party is engaged for them.** The independence requirement is **re-scoped to
bind when the seal-backing CI run is archived** — after the config is final, around the pod trip. The
justification is stated rather than assumed: this is an **evidence-credibility gate, not a
seal-safety gate** (no guard protecting the seal depends on it), and `archived_by` is the one link
nothing machine-checks (`kernel_isolation_ci.py:617` validates only non-empty-string). **Newly
recorded coupling:** any plan to re-archive from a *current* run for a fresh window changes
`head_sha`, which is exactly the unresolved `head_sha == C` decision (**L6**) — the two must be
decided together, which was not written down anywhere before.

Seal remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.

**2026-08-21 — decisions #6 and #7 are implemented; #7's normalizer was re-signed, and both
costs its approval had priced in did NOT materialize.**

**#6 (committed `dc252d3`).** `l3_hypernetwork` → `l3_symmetric_mlp` in `comparator_family` and
`ablation_ladder`, spec §3.3 amended. The model is untouched. `config_sha256`
`3faacaff…` → `c25734d5…`.

**#7 — the normalizer changed after sign-off, and that is recorded, not smoothed over.** #7 was
signed on 2026-08-20 as *"normalize the factor bank so `σmax(Φ_cal) = 1`"*. Implementation began the
next day and immediately surfaced a fork; it was **raised rather than resolved silently**, and the
owner re-signed with the normalizer changed to **`σmax(Z) = 1`** (decisions doc §5.1). Both
normalizers remove the arbitrary bank scale `c`, which is the whole purpose of #7; they differ only
in cost.

**The two costs annotated on the 2026-08-20 approval did not occur — measured, not assumed.**
`σmax(Φ_cal)` needs the calibration pair roster, which is what would have made the bank artifact
split-dependent and forced a re-plumbing of `phase2a._verify_factor_banks`' byte-for-byte binding.
`σmax(Z)` is computable from `Z` alone. **`phase2a.py` has no diff in this wave** — the seal-adjacent
verifier is untouched, no guard was weakened, and the recorded fallback (option D) is therefore not
raised.

**`config_sha256` `c25734d5…` → `5fea3b9e69112b1f6dfd5f6d33249df9d13156ed46011e3dc46f4f8cf3a66100`,
a new run identity.** This is the **second** move in the wave, so **task #14 must not regenerate at
any earlier digest** — but `5fea3b9e…` is a **floor, not the target.** The config still carries **six**
activation blockers, exactly as `ComposePhase2Config.activation_blockers` measures them —
`regimes.power_status`; `baselines.gears.revision`; `baselines.gears.environment_status`; `baselines.cpa.revision`;
`baselines.cpa.environment_status`; and `baselines.approximation_bias_report_sha256`, a single collective
key the loader raises while any approximate representation lacks its bias report (today: GEARS).
The CPA bias null is **not** a blocker: its representation is exact (`cell_raw_counts`), the config
comments the field *"must stay null for an exact representation"*, and the loader never counts
exact `cell_*` representations toward the collective key.
Step 4 above orders config finalization *before* evidence regeneration. Filling those nulls moves the digest again, so a pod
trip that regenerates #14 now would bind evidence to a lineage guaranteed to move. Both digests were measured directly from
`sha256_json(parsed YAML)` rather than carried over from the decision text.

**Evidence: 13/13 mutations killed**, each attested by the **named failing test** whose own name
makes the claim, across all four sites that enforce the rule (`zfactor.py` builder and deserializer,
`config2.py`, the committed config, and `identify.py`'s rank tolerance). Running it found **two
defects in this wave's own work**, both recorded in the decisions doc §5.2: a cond/rank test that
compared a normalized matrix with itself and so could not fail under any normalizer, and a
single-site mutation that survived because a missing config field is refused **twice** — the
contract only dies when every site enforcing it does.

Neither decision authorizes a run. Seal remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.

**The next gate is not a pod — it is four missing signatures.** `2026-07-13-compose-dev-pod-gate-decisions.md`
§6 still shows **#1 (GEARS `cell-gears==0.1.2`), #3 (CPA `cpa-tools==0.8.5`), #4 (`approximation_bias`
DEFINITION) and #5 (dev-pod provider) as `PROPOSED` with empty signature lines.** Those four gate the
development pod, and the development pod is the only thing that can produce the real-Norman evidence
the config's six null activation blockers need. Every cited fact was re-measured on 2026-08-21 and
recorded in a new **§6.1**: #1/#3/#5 are unchanged (lock SHAs `2d55a062…` / `7d4d034b…` still match),
but **#4's definition has moved since drafting** — schema `v1` → `v3`, §2's per-cell term changed from
`raw_pseudobulk_approximation` per row to `cell_raw_counts` on the full matrix (`4f417f5`), and the
fairness flag now adds a narrative limitation only instead of substituting comparators. `R_star = 0.5`
and the three flag values are unchanged. Signing still edits no config and moves no digest.

**2026-08-22 — the external audit found decision #7's rule was never enforced on consumption, and
it was right.**

The Codex audit reported, and I reproduced by running it, that a factor bank could declare
`sigma_max_z_unit`, record a scale, carry a checksum that verifies against the declaring artifact,
and be **accepted** with an actual `sigma_max(Z)` of `7.0`. Every check that existed compared the
bank with itself: the checksum recomputes from the same declared numbers, and
`phase2a._verify_factor_banks` binds the runtime matrix to those same numbers, so an unnormalized
bank and a matrix copied from it agree perfectly and are both wrong. The owner-approved decision was
in the generator and in the config; nothing on the consumption side made it true.

`zfactor.verify_bank_normalization` now enforces it at all three doors a bank can enter through —
artifact deserialization, `phase2a._verify_factor_banks`, and carrier serialization. The
byte-for-byte binding is **untouched**: this adds a refusal rather than re-plumbing the binding, so
#7's seal-adjacent constraint still holds. Tolerance is **derived rather than sampled** — `5e-13·√(n·k)` plus an SVD
backward-error floor, from Weyl's inequality — and the derivation came from the fix pipeline's
**autonomous agent**, which fixed the same finding independently on `claude/audit-fixes-2026-08-22`
(`d9f4452`). It is 15.6× tighter than the flat `1e-9` I first shipped and grows with the matrix.
The two independent attempts were strong in different places — its tolerance, my three-door
coverage — which is the argument for running both. **19/19 mutations killed**, each
by the named failing test. The change also exposed that `driver/fixture_builder._build_instance` — production code — generated unnormalized factor
matrices, so every scientific-carrier fixture bound banks that named a rule they broke; it now
normalizes. Full compose suite **2202 passed, 2 skipped**. Detail in `2026-08-17-compose-ablation-ladder-decisions.md` §5.3.

**`config_sha256` is unchanged at `5fea3b9e…`** — code only, no new run identity, and this
authorizes no run. Seal remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.

**Recorded about the loop, not the code:** this is the third time the external audit's asymmetric
view caught a defect in my own most recent wave, and the second time the defect had moved one level
out from where my own verification was looking — §5.2's 13 mutations were thorough about the
generator and silent about the consumer. A contract that no test claims cannot be mutated, so
mutation coverage measures the tests that exist, never the ones missing.

**2026-08-23 — the trust object's immutability was shallow. Reproduced, and made deep.**

The external audit reported `carrier.resolved-run-spec-shallow-immutability`. **Reproduced here, and
its probe matched line for line:** on a fully validated scientific spec, `MappingProxyType` blocked
top-level assignment but every nested dict stayed the original mutable object, so
`spec.scientific["sealed_input"]["source_path"]` became `/tmp/EVIL` and
`activation_evidence["owner"]` became `mallory` — with `self_checksum` and `file_sha256`
**unchanged**.

**The audit left one thing unmeasured and it matters, so I measured it: the mutation reaches a
consumer.** `_assemble_activation_record` on the mutated spec produced `owner='mallory'` against a
control of `owner='owner@example.org'`. A mutated nested value flows into a provenance field.

**What it is NOT, stated as plainly as what it is.** `carrier_loader.load_run_spec_carrier` takes a
*path* and calls `load_resolved_run_spec` itself (verified in code, not assumed), so an in-process
mutation of an already-loaded spec cannot enter the shipped entry point. This is a documented
guarantee that was shallow, with a measured mutation→provenance path — not a demonstrated exploit
through the CLI. The audit scoped it the same way and did not raise it as a release blocker.

**Fix.** `run_spec._deep_freeze` recursively freezes the mode block: mappings become read-only
proxies whose values are themselves frozen, sequences become tuples. Measured scope first — of the
spec's mapping fields **only the mode block was shallow** (11 mutable nodes); `pre_seal`,
`worker_blocks`, `expected_hashes` and `run_produced_basenames` were already deep because their
values are frozen dataclasses or scalars. So the change is surgical rather than sweeping.

**`run_spec.py` is a registered seal guard ([CLAUDE.md#enforcement](../../CLAUDE.md#enforcement)), and this STRENGTHENS it** — it adds
immutability, weakens no check, and changes no registered value. Codex correctly declined to file a
fix request for it and escalated to the owner; the owner authorized this change.

**Verified.** The original reproduction no longer reproduces (`nested mutation NOT possible`).
Three mutations, each killed by the **named** test whose own name makes the claim: reverting to the
shallow form, stopping the recursion after one level, and a freeze that drops values instead of
preserving them — the last exists because a freeze that changed the data would be a worse defect
than the one it fixes. `config_sha256` unchanged; no new run identity; seal remains **UNOPENED** and
execution **RELEASE-BLOCKED**.

**2026-08-25 — pre-seal reads are digest-bound: the bytes that were verified are the bytes that
get consumed.**

The external audit reported `provenance.preseal-hash-reopen-toctou`. **Adjudicated by running it, and
the verdict split.** `load_resolved_run_spec` hashes every pre-seal pathname during validation, and
`carrier_loader` then REOPENED the same pathnames to parse them — two separate reads, so "the
declared digest was verified" said nothing about the bytes that were parsed.

| | verdict | evidence |
|---|---|---|
| the audit's written reproduction (swap **before** the carrier call) | **REFUTED** | `RunSpecError: config: declared sha256 … != actual file digest …`. The carrier takes a *path* and reloads the spec itself, so a sequential swap never reaches it. |
| the structural claim (swap **inside** the call, after hashing) | **CONFIRMED** | carrier loaded a config whose bytes no longer matched the digest the run identity is built from |

**The window is intra-call, not sequential.** The audit's write-up missed that distinction and so read
as more severe than it is. The independent daily reviewer reached the same split verdict from its own
probes (`toctou_in_window` succeeded, `toctou_sequential` rejected) — the fourth time the loop's
asymmetric view has converged on a finding, and the first time a finding's **claim was true while its
reproduction was false**.

**Fix.** `carrier_loader._read_verified_bytes` reads a pre-seal file ONCE and hashes the bytes it
actually read; `_preseal_json` wraps it for the eleven JSON artifacts, and the config now parses
through `config2.load_compose_phase2_config_from_text` from those same verified bytes. "Verified
bytes == consumed bytes" is now true by construction rather than by timing — it no longer assumes the
filesystem holds still, which the previous arrangement assumed without saying so.

**Scope, stated rather than implied.** This covers every pre-seal artifact `carrier_loader` itself
parses. Pre-seal *paths* handed onward (`data_card_path`, `raw_asset_path`, `feature_bank_path`) are
hashed by their consumer at use time (`phase2b.py:490-493`) — measured, not assumed — but those
digests are recorded for provenance rather than compared against the run spec's declared values.
Binding them is a separate question and is **not** closed here.

**`run_spec.py` and `carrier_loader.py` are both registered seal guards
([CLAUDE.md#enforcement](../../CLAUDE.md#enforcement)); this strengthens them** — it adds a refusal,
removes no check, and moves no registered value. The owner authorized it after the adjudication.

**Verified.** The in-window swap is now refused; the sequential swap is still refused by the spec
loader; an untouched carrier still loads (non-vacuity). Two mutations killed by the **named** test —
dropping the digest check entirely, and leaving just the config on the old reopen path, which is the
one-site-missed shape this repository keeps producing. One existing test needed updating: it mutated
a data card on disk and now trips the digest guard first, so it re-declares the digest and keeps
testing what its name claims. `config_sha256` unchanged; seal remains **UNOPENED**; execution remains
**RELEASE-BLOCKED**.

**2026-08-26 — the headline pair set has no independent rows, and the registered bootstrap
undercovers through one specific channel.**

The external audit reported `stats.pair-gene-dependence` as a **logical** argument: if pairs sharing a
gene have non-zero error covariance, the pair-i.i.d. bootstrap's effective sample size and
max-deviation quantile *could* be wrong. Nothing was measured. Measuring it split the verdict, and
changed what has to be measured next. Full evidence, scripts and raw output:
[`evidence/2026-08-26-pair-gene-dependence-coverage/`](evidence/2026-08-26-pair-gene-dependence-coverage/README.md).

**Structure — measured, and reproduced against committed pod evidence (7/7).** Reading only
`obs['perturbation']` labels (never `.X`; eligibility and split are outcome-independent by spec §2.2),
the registered split reproduces `singles 105 · pairs 131 · z-universe genes 73 · calibration genes 44 ·
roles 41/22/68`. The headline `sealed_double_unseen` role is **22 pairs drawn from 21 genes**: mean
gene degree 2.10, and **not one of the 22 pairs is gene-disjoint from all the others**. The
pair-i.i.d. assumption is not approximately satisfied here; it is violated by construction.

| | verdict | evidence |
|---|---|---|
| structural premise ("sharing exists") | **CONFIRMED, measured** | 22 pairs / 21 genes / **0 independent rows** |
| the mechanism as the audit worded it | **partly REFUTED** | shared pair-difficulty cancels in the ratio — 20 conditions, no effect |
| the channel that actually bites | **CONFIRMED (corrected)** | only **method-differential** gene effects survive into `d_i` |
| magnitude under that channel | **measured (model)** | 0.95 → **0.924–0.937**; zero-sharing control does not move |
| that channel's real size in Norman | **UNMEASURED** | needs Phase 2a dev outcomes on `combo_calibration` |

**Why the audit's own mechanism does not bite.** θ is a ratio, `1 - mean(e_L1)/mean(e_C)`. A gene
effect common to every method is a shared multiplier that largely cancels between numerator and
denominator; what remains is extra marginal dispersion, which the i.i.d. bootstrap absorbs by widening
the band (q 0.308 → 0.446). Twenty conditions — the real graph at ICC 0 → 0.41, plus a synthetic
ladder from degree 1.0 to 5.5 — all landed in 0.955–0.967, at or above nominal. **A design that only
opens that channel cannot show a loss**; it prints the same answer whether the finding is true or
false. Those twenty conditions are therefore both a negative result and the non-vacuity control for
the arm below.

**The channel that does bite.** Give each method its own gene effect — a gene one method handles well
and another handles badly. That component does not cancel out of `d_i = e_C - e_L1` and is correlated
across every pair containing the gene. Run on the **real** headline structure with the registered
estimator (n=22, 10 000 replicates, five comparators, family confidence 0.95, 1500 trials per cell),
family-wise coverage falls to **0.9307 / 0.9240 / 0.9373** — every CI below nominal, a family-wise
error rate up to roughly **1.5×** the registered 5%. The control with identical added variance and
**zero** gene sharing does not move at all (0.966–0.972). The loss is caused by the sharing, not by
the variance.

**The obvious remedy does not exist for this split.** `sealed_double_unseen` has **two** connected
components, sizes 19 and 3 — 86.4% of pairs in one. A cluster bootstrap would have an effective
cluster count of 2; a gene-level resample over 21 genes changes n per replicate and with it the
registered estimand. This design has no resampling unit that absorbs the dependence, which is itself
something the owner needs to know before choosing.

**Why this is not cosmetic, and why now.** The verdict gates in spec §10.5 are a direct function of
these lower bounds (`GI_LEARNABLE_WIN` = additive lower bound > 0.05 AND each of the other four > 0).
An optimistic bound is an optimistic verdict. The spec states no pair-i.i.d. assumption anywhere, so
the confirmatory coverage claim currently reads as unconditional. Invariants 1 and 17 require the
evaluation harness to be fixed before outcome access, so this cannot be revisited after the seal.

**Open — owner decision, deliberately not taken here.** (1) limit the confirmatory claim to the
pair-i.i.d. assumption and pre-register a sensitivity report; (2) pre-register a design-effect band
inflation calibrated on `combo_calibration` (41 pairs / 37 genes, comparable structure) during Phase
2a; (3) leave the inference unchanged and state the assumption in §10.5. All three touch spec/config
and are therefore a **new run identity** requiring sign-off. No registered inference value was
changed here: `config_sha256` unchanged, sealed access count **0**, seal remains **UNOPENED**,
execution remains **RELEASE-BLOCKED**.

**2026-08-28 — claim replay: the audit's reproduction holds, its severity does not, and the
real gap was that nothing wrote the contract down.**

The external audit reported `seal.claim-materialization-replay` with a stated reproduction:
materialise one claim twice and both calls return a payload while the durable audit holds a single
record. **Reproduced verbatim** — sequentially and concurrently.

**Everything replay could exploit is already closed, and measured.**

| what a replay would need | state |
|---|---|
| widen or narrow the payload selector | refused — `test_materialize_forged_pair_ids_fails_closed` |
| a second claim under any `run_id` | refused — pinned by two tests |
| win a concurrent claim | one winner — `atomic_write_once` + `FileExistsError` |
| production calling it twice | it does not — `test_phase2b` pins the exact event sequence |
| serve different bytes | the source is fd-pinned (below) |

The consumption boundary is `claim_sealed_access`, which writes the durable audit record **first**
so that a crash during materialisation still burns the path. Materialisation is idempotent by
design, and the code says so — but only in a comment.

**A correction to an earlier reading of this finding.** An in-memory probe appeared to show that a
replay re-reads the source and can therefore serve different data under one audit record. That is a
property of the *stub*, not of the pipeline. `phase2b_cmd._open_verified_sealed_source` refuses a
symlink and a non-regular node, streams SHA-256 through an open descriptor, requires
`(dev, ino, size, mtime_ns)` unchanged across the hash, compares against the declared digest, and
then hands downstream an **fd-backed path** — its docstring names the purpose, "closing the
hash-then-reopen pathname race". The validator opens that descriptor once and the store retains the
resulting object, so a replay re-slices the same verified inode. That property is already tested:
`test_verified_descriptor_survives_source_path_replacement`.

**So the residual was documentary.** Nothing in the spec defines whether "opened exactly once"
counts claims or materialisations, and — measured by walking every test with `ast` — **no test in
the repository called `materialize_claimed` twice.** The contract was unstated and unprotected
against drift.

**Done here (tests only; no registered value moved, no guard behaviour changed).** Four tests in
`test_seal_boundary_split.py` pin the replay contract: a replay returns a byte-identical payload; a
replay does not inflate the durable access count; the validator is latched so a replay re-slices the
**validated** source rather than the constructed one; and one test records the residual honestly —
at the store layer alone the payload bytes are not bound, and the binding lives one layer up in the
driver. Four mutations, each killed by the test whose own name makes the claim, including an
inverted one: giving the store a payload cache turns the residual test red, so that record notices a
fix instead of quietly aging.

**Proposed for sign-off — one sentence for spec §10.5, not written by me into the spec:**

> The sealed cohort is *consumed* by `claim_sealed_access`, which durably records the access before
> any row is materialised; `materialize_claimed` is idempotent and MAY be called more than once for
> a single claim. The registered access count therefore counts claims, not materialisations, and the
> identity of the bytes served is pinned by the run's `processed_sha256` together with the
> descriptor-pinned sealed source, not by the audit record.

**Severity, stated against the audit's.** The audit marked this "seal open 직접 차단". It is **not a
blocker**: no measured path lets a replay read anything the single claim did not authorise. The
documentation and test items *were* pre-seal work, because neither can be done retroactively once
the seal opens — and both are now done except the signature.

**Not fixed, recorded.** In-place mutation of the already-open inode would defeat descriptor
pinning, and `_open_verified_sealed_source` does not re-check identity at materialisation time. That
requires a hostile local writer, is outside this finding, and is **not** closed here.

`config_sha256` unchanged; sealed access count **0**; seal remains **UNOPENED**; execution remains
**RELEASE-BLOCKED**.

**2026-08-29 — the four dev-pod signatures are given, and the pair-dependence decision moves the
config digest to `0d20774637775eda79cb682a5d28bf7df40bf5b0a3f5768ef109ba7fa37c6c99`.**

**Signatures (A1).** The owner signed dev-pod gate decisions **#1, #3, #4 and #5** together on
2026-08-29; the record is `2026-07-13-compose-dev-pod-gate-decisions.md` §6.2, with §6's table
flipped to CONFIRMED. #4 is recorded explicitly against the **§6.1 v3 definition**, not the v1 text
the row was drafted against, so the signature cannot be read as approving the older definition. The
record also enumerates what the signatures do **not** cover — config edits, activation blockers,
`config_sha256`, an exact Git SHA, the seal, Task 0.1's wheel/sdist hashes and pod image digest, and
the exact `epoch / batch / optimizer / early-stop / seed`, which are read off the installed wheel on
the pod. That last carve-out is the scope the standing finding
`docs.dev-pod-signature-scope-overclaim` names, cut out at the moment of signing rather than left to
be argued afterwards.

**Decision (A2).** `2026-08-29-compose-pair-dependence-decision.md`. The confirmatory coverage claim
is now conditional on the registered resampling unit, and a band-inflation ladder is frozen so the
report states where the verdict flips instead of asserting that it does not. The primary verdict is
untouched: it is decided at λ = 1.0 exactly as spec §10.5 says, and the sensitivity report is
descriptive-only.

Two alternatives were rejected on the record. A design-effect inflation calibrated on
`combo_calibration` fails because that role is where GEARS and CPA **train** — carrying an
intraclass correlation from in-sample behaviour to the extrapolating sealed role is the cross-role
transfer invariant 7 forbids — and because an ICC from 41 pairs over 37 genes would multiply the
headline band by a very noisy number. Stating the assumption and changing nothing else fails because
it is labelling without analysis and uses none of the advantage of the seal being closed.

The ladder `[1.0, 1.1, 1.15, 1.25]` is anchored, not guessed: sweeping λ from the same simulated
trials (coverage(λ) = P(m ≤ λq), so no re-run of the estimator) the minimum inflation restoring
nominal coverage measured **1.0 / 1.10 / 1.15 / 1.10** across the σ ladder. The whole measured
degradation is repaired by widening the band 15%, and the worst case is **interior** (σ=0.60, with
recovery at σ=0.90 as q outgrows the dependence), so the measured range brackets it. The anchor is
model-based, not Norman-based — which is exactly why the decision reports the verdict at each λ
rather than asserting the true one.

**Registered, and loader-enforced** — `inference.simultaneous_coverage_claim` and
`inference.sensitivity_band_inflation`, in the same shape as `shared_resamples_across_contrasts` and
decision #7's `factor_bank_normalization`: exact match, failing closed at two sites. Ten tests pin
them, including one that pins the ladder CONSTANT's own invariants (leads with 1.0, climbs, never
below 1) because an exact-match config check cannot notice the constant itself going wrong, and one
that asserts the verdict thresholds did **not** move.

**`config_sha256` moves: `5fea3b9e…` → `0d207746…`** — a **new run identity**, re-derived
independently (`sha256_json(yaml.safe_load(config))`) and agreeing with the loader. It is still a
**floor, not the target**: the config still carries **six** activation blockers, so the digest moves
again when they are filled, and task #14's regeneration still belongs at that later digest. Every
current-state document that quoted the old digest was updated (both decision banners, the runbook's
dated chain, the pair-dependence evidence README); the historical statements inside dated entries
were left alone, because they were true when written.

**One thing this change surfaced by tripping it.** Moving the digest made
`test_activation_blocker_doc_contract` **skip** on this document — the standing finding
`tests.activation-blocker-contract-skips-on-config-change`, demonstrated live by the very change it
warns about. The skip is now a hard failure: a document that enumerates the blockers must carry the
committed digest, or it is stale rather than exempt.

Seal remains **UNOPENED**; execution remains **RELEASE-BLOCKED**; sealed access count **0**.

**2026-08-30 — the post-hash window: descriptor pinning stops a pathname swap, not a write into
the inode it pins.**

This one was on the record as an unfixed residual before it was a finding. The 2026-08-28 claim-replay
entry closed with it in plain words: in-place mutation of an already-open inode defeats descriptor
pinning, `_open_verified_sealed_source` does not re-check identity at consumption time, it needs a
hostile local writer, and it was **not** closed there. The daily reviewer then reproduced it against
the real function and raised it as a **High** (`seal.verified-fd-posthash-mutation`), and reproducing
it here independently gives the same three facts: `same_inode=True`, the verified digest and the
digest of the bytes actually read back differ, and what comes back is the tampered content. The
function has no diff against `origin/main`, so the shape is on main too.

**The boundary is exact, and narrower than it first looks.** Mutation *before* or *during* hashing is
still refused — the existing `(dev, ino, size, mtime_ns)` comparison across the hash catches it. The
gap is strictly the window *after* the digest is taken and the descriptor handed on.

**Prevention is not available at this layer and pretending otherwise would be the wrong fix.** A local
writer with write permission can modify a file this process holds open read-only; nothing here stops
that. What the seal's evidence actually rests on is narrower and is achievable: *the bytes recorded as
verified are the bytes consumed*. So the digest is re-streamed through the **same descriptor** after
consumption and must still equal the declared one. Divergence stops being silent and becomes a
fail-closed abort. Cost measured on the real sealed source — 0.70 GB, **0.2 s**, once per run.

**Two design choices, both pinned by tests rather than by comment.** The re-check is digest-based, not
stat-based, because an adversary willing to mutate the inode will also restore `(size, mtime)` with
`utime` — a test does exactly that and still gets a refusal. And the re-check runs on the **normal
path only, never in `finally`**: on a consumer failure the original exception is the one that matters,
and a `finally` would replace it with a digest complaint. A mutation that moves the block into
`finally` is killed by the test whose name makes that claim.

**Verified.** Four mutations, each killed by the named test: removing the re-check entirely (restores
the reproduction), degrading it to an identity-only check (defeated by the mtime restore), moving it
into `finally` (masks the consumer's exception), and making it always fail (caught by the non-vacuity
control, because a guard that refuses everything is an outage). `phase2b_cmd.py` is a registered seal
guard — this **adds a refusal, removes no check, and moves no registered value.**

`config_sha256` unchanged at `0d207746…`; seal remains **UNOPENED**; execution remains
**RELEASE-BLOCKED**; sealed access count **0**.

**2026-08-30 — the sensitivity report the 2026-08-29 decision registered now exists, and it is
checked against the verdict function rather than against a copy of its rules.**

The decision froze the contract (`inference.sensitivity_band_inflation`) and said in §7 that the
report consuming it was the next increment. It is here: `inference2.inflate_bounds` and
`inference2.band_sensitivity`.

**What it computes.** Inflation widens the shared band and never touches `theta`, so the result is
shaped exactly like `ComposeSimultaneousBounds` and can be handed to `verdict2.sealed_verdict`
unchanged. The flip point is **closed form, not searched**: the clause holds while
`theta_C - lambda*q > t_C`, so the crossing sits at `lambda = (theta_C - t_C)/q`, with the additive
contrast measured against the material margin and the learned family against theirs. The report also
carries `verdict_holds_below_lambda = min(flip)`, the inflation at which the first clause fails and
the conjunction stops holding.

**The load-bearing test compares the report with the real decision function.** Just inside the
reported flip, `sealed_verdict` still returns `GI_LEARNABLE_WIN`; just outside it does not. A report
that reimplemented the clause logic and drifted from the function that decides the run would be worse
than no report, and this is what would notice. It earned its place immediately: the mutation that
aggregates the flip with `max` instead of `min` is caught by that test as well as by the one whose
name makes the claim.

**Boundaries kept.** `lambda = 1.0` reproduces the registered bounds byte for byte — the value the
verdict is decided on is not perturbed by the thing reporting around it. A factor below 1 is refused
outright, because narrowing the registered band is the single thing this must never do. A zero-width
band reports `inf` rather than `0`, since no inflation moves it.

**Verified.** Fourteen tests; eight mutations, each killed by the test whose own name makes the
claim — inflating at λ=1.0, dragging `theta` along with the band, admitting a factor below 1, solving
the flip against the wrong threshold, aggregating with `max`, dropping the leading-1.0 check,
dropping strict monotonicity, and mapping a zero band to 0 instead of `inf`.

Nothing registered moved: `config_sha256` unchanged at `0d207746…`, thresholds unchanged, the report
is descriptive-only. Seal remains **UNOPENED**; execution remains **RELEASE-BLOCKED**.

**Still open on this thread.** Wiring the report into the Phase-2b run output (it is a library
function today, called by nothing in the driver) and the spec §10.5 sentence, which the daily reviewer
correctly notes still lives only in a readiness proposal and is unsigned.

**2026-08-30 — every pre-seal read lane is digest-bound now, in ONE place, and a frozen kernel
proof decided how the last one was closed.**

The audit re-raised `provenance.preseal-hash-reopen-toctou` as "only some lanes are closed", and
named the lines. It was right, and the first one it named is the sharpest: `carrier_loader:621` read
`phase2a_inputs` with a plain path read while its eleven siblings in the same file went through the
digest-bound helper. **The 2026-08-25 fix missed a sibling inside the very file it was fixing.**

**So the helper stopped living in a consumer.** `driver/preseal_read.py` now holds it and every lane
calls it: the `phase2a_inputs` lane, `preflight_cmd`'s config plus its two raw byte reads plus the
pair manifest, the config load in `phase2a_cmd` and `phase2b_cmd`, and the bias lane. Fixing this in
one place is now the only way to fix it at all — the same structural move made twice on the
collaboration side this week for the worktree pin and the agent timeout. `carrier_loader._read_json`
lost its last caller and was deleted rather than left as a path anyone could reach for.

Each caller converts `PresealBytesError` into the error its own contract already raises. Widening a
caller's exception type to import a new one would redefine an existing contract in order to add a
check, which this repository has already recorded as its own mistake.

**Three drift guards fired, and the point was not to bump their numbers.** A new driver module has to
join the structural-scan roster or the §4 scan silently stops covering the package. A new exception
class has to be classified. The classification took thought: `PRESEAL_REJECTION` in that registry
means *actually maps to exit 10*, and these classes must never reach the CLI — every call site
converts them, and one arriving at the CLI would mean a site forgot, which must surface as a bug
rather than be dressed up as a clean pre-seal rejection. They are `UNREACHABLE_FROM_DRIVER`, and the
label is made true by a **behavioural** test that trips a real digest mismatch per module rather than
grepping for an `except` clause.

**The last lane could not be closed the obvious way, and a guard is why.** The bias lane's
reconstruction helper lives in `src/alive/compose/approximation_bias.py`, which is inside the
**frozen kernel-isolation closure**. Adding a text-taking variant there invalidated the archived
Linux CI proof at `2dd23d6`, and `test_kernel_isolation_ci` said so — that evidence can only be
re-established by a fresh Linux run, which is not something to spend on a refactor's convenience. The
edit was reverted. Instead the descriptor-pinned reader moved out of `phase2b_cmd` into the shared
module, and the bias lane hands the reconstruction helper a **descriptor path**: same "verified bytes
== consumed bytes" property, zero bytes changed inside the proof.

**Two defects were introduced during that relocation and caught by the tests written for it.**
Widening the signature to `str | Path` while the body kept calling `Path` methods meant the bias lane
raised `AttributeError` instead of verifying — a widened parameter type the body does not honour is
not a widened type. And the first version of the bias conversion test called the shared function
directly, exercising no conversion at all: it would have passed whatever `bias_report_preseal` did.

**Verified.** Five mutations killed by the named test, including restoring the missed
`phase2a_inputs` lane and dropping the conversion in two different modules. Full repository suite
**2945 passed / 3 skipped**; ruff clean. `config_sha256` unchanged at `0d207746…`; seal remains
**UNOPENED**; execution remains **RELEASE-BLOCKED**.

**Not closed here, and named rather than implied.** `data_card_path` and `feature_bank_path` are
still handed onward as paths and hashed by their consumer for provenance rather than compared against
the run spec's declared digests. `raw_asset_path` is already descriptor-pinned. Binding the other two
means changing what their consumers promise, and that is a separate question.

**A process correction worth keeping.** A mutation battery was killed by a 10-minute tool timeout
before its `finally` ran, leaving a mutation in the tree — the roster entry it had deleted stayed
deleted. The "restored byte-for-byte" line these batteries print only appears when the battery
survives. Restoration has to be checked from OUTSIDE the battery; `git status` caught it, and
batteries now run in the background where a timeout cannot kill them mid-mutation.

**2026-08-30 — the two §10.5 sentences that were settled everywhere except in the spec.**

Both of these came out of adjudications the owner has already settled, and in both the settlement
landed in code, config and this index but **not in the spec** — which is the claim contract, so until
it says them the claim is not what the repository actually does. The daily reviewer named the first
gap exactly: the "materialise MAY repeat" wording exists only as a readiness proposal, unsigned, and
it recorded that as a standing Medium.

Drafted signature-ready in `2026-08-30-compose-spec-10-5-amendments.md`, not written into the spec:

- **A — the consumption boundary is the claim.** `claim_sealed_access` records the durable audit
  before any row is materialised, so a crash mid-materialisation still burns the path;
  `materialize_claimed` is idempotent. The registered access count therefore counts **claims**, and
  the identity of the bytes served is pinned by `processed_sha256` plus the descriptor-pinned source
  rather than by the audit record. Signing does not authorise repeated materialisation as a practice
  — production calls it once and a test pins that — it removes the reader-dependence in "opened
  exactly once".
- **B — the coverage claim is conditional, and the sensitivity's placement.** The 2026-08-29 decision
  registered the config values and `inference2.band_sensitivity` computes the report, but the spec
  still reads unconditionally and does not say where the report goes.

**B carries the one implementation consequence, and that is why it is held.**
`Phase2bResult.result_checksum` is a registered five-component composition (spec §2.1). The
sensitivity is descriptive-only, so it must **not** enter that composition — putting it there would
make a descriptive report part of the run's registered identity, the opposite of what the decision
says. The proposal is that it is computed from the same bounds the verdict used and written into the
report payload OUTSIDE those five components, with its own checksum. Where a result is recorded is a
spec question, not a coding preference, so the wiring waits for the signature rather than being
chosen by whoever writes the code.

**2026-08-30 (same day) — a third sentence joined them, and adjudicating it reversed the finding's
direction.** `driver.preflight-output-contract` is **CONFIRMED as a fact**: the driver design spec
§3.2 ends with "화면에는 canonical payload와 full checksum을 출력한다" and `preflight_cmd.py`
contains no `print` at all. The audit offered two remedies — add the stdout, or amend the spec to an
artifact-only contract — and measuring the runbook decides between them rather than leaving it to
taste. The runbook makes the flow file-mediated **by design**: a *second operator* reconciles
`seal_confirmation_manifest.json` and reads `confirmation_checksum` from it. CLAUDE.md#sources ranks the
runbook above a design spec for execution contracts, and "print to screen" is operator UX, not a
scientific claim. Dumping the canonical payload to a terminal would also make a screen transcript
resemble a record of a two-person reconciliation that is supposed to happen against the file. **The
implementation is right; the spec sentence is the defect**, and adding the stdout would have made the
code match a sentence that contradicts the operating procedure. The replacement text is drafted in
the same amendments document — not applied, because removing a "print this" requirement from an
owner-approved spec is exactly what should not be done by whoever finds it inconvenient, even when
the evidence says the requirement was the mistake.

None of the three amendments moves `config_sha256`; seal remains **UNOPENED**; execution remains
**RELEASE-BLOCKED**.

**2026-09-03 — amendment A asserted a property the tree measurably lacks; it is now conditional.**

The 09/02 audit and the 09/03 review both stopped at the same sentence. As drafted, A said
`materialize_claimed`는 **멱등이며** — unconditionally idempotent. The repository pins the opposite
at this very pin: `test_the_store_alone_does_not_bind_the_payload_bytes`, added by `91616d5` as an
honest residual record, requires that changing the source between two materialisations produce
*different* payloads while the audit stays one row. The review ran it (`1 passed`) rather than
reading it, and refused the sentence as unsignable. That is the right outcome — an amendment may not
assert what the code does not do, and this one was mine.

The sentence is reworded to be true as written: `materialize_claimed` may be called more than once
for a claim, this is **not** called idempotent, and identical bytes across two calls hold only while
the sealed source's bytes are unchanged — a condition bound by the run's `processed_sha256` and the
descriptor-pinned, post-consumption-re-verified source. Two residuals are named in the amendment as
explicitly **not** closed by signing it: `seal.claim-materialization-replay` and
`seal.transient-inode-mutation-restoration` (the latter reproduced with a control arm on 09/03 — the
non-restored control is refused by name, the restored one is not).

Also on this date, the branch was **red** and I had not noticed: two fragile numeric-section
references to `CLAUDE.md` that I wrote (this file `:2205`, the amendments document `:111`) failed
`test_live_documentation_has_no_fragile_section_number_refs`. Fixed to `CLAUDE.md#sources` in
`60a3f96`; full suite **2945 passed / 3 skipped / 0 failed**. The failure was found by the external
audit and reproduced by the review, not by me — I ran targeted tests again after touching docs, which
is the exact mistake this repository has already recorded once. And writing *this* paragraph
reintroduced the very pattern it describes — the literal offending string, inside the sentence
explaining it, turned the suite red again for one edit cycle. The guard is a regex over live docs:
prose *about* the pattern is indistinguishable from a use of it, so describe it, never quote it.

A remains PROPOSED and unsigned; B and C are unchanged. `config_sha256` still `0d207746…`; seal
**UNOPENED**; execution **RELEASE-BLOCKED**.

**2026-09-03 (later) — the provenance TOCTOU is closed BEFORE the pod run, not after; amendment A is
signed; the zero-width report fix is adopted.**

Ordering was the point. `build_activation_provenance_inputs` hashed the requirements pathnames with
`sha256_file` and then **reopened the same pathnames** to parse the pinned revisions — two reads, with
a window between them. A writer landing in that window makes `dependency_lock_sha256` and
`gears_revision`/`cpa_revision` describe different bytes, and nothing refuses it. Two of the six
registered activation blockers ARE those revisions (`baselines.gears.revision`,
`baselines.cpa.revision`), so a dev-pod run executed against the old shape would have produced exactly
the evidence the seal depends on, with a defect inside it. Fixing after regenerating would have meant
regenerating twice.

Closed by reading once: the small requirements/lock files are read a single time and both the digest
and the parsed revisions come from those bytes. `processed_path` and `feature_bank_path` stay on
streaming `sha256_file` — they are hashed once already and can be multi-GB. **The recorded values do
not move**: `sha256_bytes(raw)` and `sha256_file(path)` over the same bytes were measured equal
(`b38e1af1…` both ways), so no existing provenance digest changes.

Measured, not asserted. The probe injects a writer at the second open of the requirements file and
asserts the file is opened exactly once. Before the fix: `opens=2, fired=True` — the window
reproduced by name. After: `opens=1`, the swap never fires, the revision is the original.
**The control arm earned its place twice over.** The first version of the probe patched only
`builtins.open`, which `sha256_file` uses but `Path.read_text` does not — it counted one of the two
reads and **passed against the unfixed code**. `test_the_swap_probe_is_not_vacuous` failed and
exposed it; the injection now covers `io.open` as well. A probe that cannot see the defect is worth
less than no probe, because it reports safety.

Also in this wave:

- **Amendment A signed (Jae Min Yoon, 2026-09-03)** — on the reworded sentence. The signature record
  in the amendments document enumerates what it does *not* close: `seal.claim-materialization-replay`
  and `seal.transient-inode-mutation-restoration` both stay registered and open. B and C remain
  PROPOSED.
- **`f338925` adopted** (`908446d`, cherry-picked with owner approval) — the zero-width-band report no
  longer reports a clause that already lost at the registered band as unmovable. It was the fix
  pipeline's first unattended commit; the pipeline does not merge its own work and the owner side did
  not either until the red/green was reproduced independently, twice.

`config_sha256` remains `0d207746…`; seal **UNOPENED**; execution **RELEASE-BLOCKED**. The critical
path is unchanged and is now unobstructed: regenerate the six activation blockers on the dev pod at
this digest.

**2026-09-05 — the activation evidence had a strict validator and no producer; it has one now,
and an independent review of it found the producer's first draft claiming more than it did.**

`alive.compose.activation_evidence` has validated the dev-pod smoke evidence exactly since it was
written, and nothing produced it. The consequence sat in the committed lock the whole time:
`activation=BLOCKED`, `run_gate.evidence_status=INCOMPLETE`, and all 28 `required_evidence` fields
null. The only path to filling them was by hand on the pod, which is the shape this repository keeps
finding — a measurement and its record written separately, free to drift.

`alive.compose.smoke_evidence` + `scripts/compose_smoke_evidence.py` close that path
(`f76231e`…`5ce8533`, then the review wave below). Each builder derives BOTH sides of a cross-check
the validator performs, from one computation: the pair roster's ids and the record's hashes of them;
the artifact digests, **measured rather than accepted**; the wheelhouse roster, derived from the
requirements locks with the validator's own parser. Task 0.1's acceptance condition
(`validate_dependency_lock` → `COMPLETE`; one sealed pair in training fails closed) passes on the
real committed lock in a staged copy.

**The independent review** (opus, 2026-09-05, prompted with the seven mutation rules) verified the
six mutation kills I had claimed and then found two Critical and eight Important defects I had not:

- **C1 — a refused run destroyed a successful one.** The first CLI validated a candidate lock before
  replacing the committed one, and I described that as leaving the directory untouched. It did not:
  the five sidecar manifests were written *before* validation, under the names the next run would
  use. Run 1 (valid) → COMPLETE; run 2 (refused) → run 1's sidecars overwritten, run 1's lock no
  longer validated. Closed: promotion writes nothing; `publish_promotion` copies the evidence
  directory to a temporary staging area, validates the staged lock, and only then publishes the
  sidecars write-once (`io.atomic_write_once`, existence established for every name before the first
  write) with the lock last by atomic rename. A refusal leaves the directory **byte-identical**,
  which is now what the tests measure (whole-directory snapshot before/after, I7) rather than what
  the docstring said. A COMPLETE input lock is refused before anything is built (I8).
- **C2 — `VERIFIED_ZERO_OVERLAP` was certified on an operator-typed roster.** `training_pair_ids`
  came from the bundle; the producer hashed it and measured its overlap with the sealed pairs, but
  nothing bound it to what the smoke actually fitted on. Closed (owner chose the recommended
  option): the roster is now **derived** from the fit-role artifact named by the payload's
  `fit_role_artifact` block, read through the worker's own guard
  (`read_verified_fit_role_artifact`: SHA on a stable descriptor, re-hash after read, snapshot
  identity rebound to the spec). The training roster is the sorted unique perturbation tokens of
  the `singles` / `combo_calibration` rows; both roles must be present or the producer refuses
  (`training_roles` is established, not asserted); sealed pairs are canonicalised to the artifact's
  own token form so the intersection is measured in one encoding; a harness-reported roster, if
  supplied, must equal the derived one; and `fit_role_artifact_sha256` is the digest of the bytes
  the roster came from, cross-checked at the record merge against the manifest builder's own hash
  of the file. Task 0.1's negative test now runs on a real artifact carrying a sealed row, and the
  producer reports the overlap rather than laundering it (a mutation that dropped sealed tokens
  from the derived roster is killed by the test whose name says so).
- **Important, all closed:** the four run-identity/prose fields were inherited from the INCOMPLETE
  lock (I1: now inputs; `activation` must not say BLOCKED, the one contradiction the validator's
  COMPLETE branch never reads); sidecar names now the plan's `{gears,cpa}_smoke_pair_roster.json` /
  `{gears,cpa}_smoke_artifacts.json` (I2); establish-before-write carried to its siblings — `git_sha`,
  image digest, backend membership, a record filed under the other backend, non-durable `uri` (I3);
  wheelhouse keys normalised once with the validator's rule and duplicates refused (I4: `Cell_GEARS`
  passed the roster comparison and raised `KeyError` a line later); declared `filename` must be the
  hashed file's name (I5); the two test lock builders that hand-rolled the contract in duplicate now
  go through the producer (I6); unknown entry keys refused (a caller-supplied `sha256` was silently
  ignored); CLI usage errors exit 2, not a traceback.

**What this does NOT close** — stated because the first draft of this very entry said "atomically"
and "leaves the committed lock untouched" about code that did neither, and the review measured it:

- What C2's closure still takes on attestation, stated so nobody reads "derived" as "everything":
  `exit_code`; the sealed pair list itself (the bundle's `sealed_pair_ids`, i.e. the payload's
  `pair_ids`, is canonicalised and measured against the roster but not re-derived from the committed
  split manifest whose digest the artifact's provenance names — that is the natural next binding);
  and the content of the `fit_role_row_identity` object, which has no producer or schema in this
  repository and is bound by bytes only.
- `readiness.activation-evidence-incomplete` stays OPEN. A producer exists; the lock is unchanged
  and still reads `activation=BLOCKED`. The blockers are filled by a pod run, not by these commits.
- `provenance.activation-input-snapshot-mismatch` — the boundary window is **closed for all five
  lanes** (third commit of this wave). `60a8c5f` had closed the double read INSIDE
  `build_activation_provenance_inputs`; the window that remained was at the boundary that calls
  it: `driver/carrier_loader.py` `_assemble_provenance_inputs` unwrapped five declared `PathSha`
  objects to bare `.path` and the builder recorded whatever the files hashed to by then. The
  feature-bank residual and the worker-requirements lane the review reported on separate days
  were that one window in two of the five lanes. Now each input crosses the boundary as
  `(path, sha256)` and the builder refuses bytes that do not hash to the declaration, naming the
  lane, before any digest is recorded — `sha256_bytes` on the one read for the three small files,
  streamed `sha256_file` for the two large ones. The check lives in the builder rather than in
  `driver/preseal_read` because no core module imports from `driver/`; it is the same comparison.
  Ten tests, five per side; the mutation that re-hashes the file at the boundary instead of
  passing the declaration is killed by the five driver-lane tests alone, which is the claim they
  make. Still OPEN: `seal.transient-inode-mutation-restoration` below, and nothing further is
  claimed — a consumer that re-reads one of these paths later is outside what these ten tests
  measure.
- `seal.transient-inode-mutation-restoration` stays OPEN. Different lane (`verified_descriptor`,
  post-consumption re-verification), untouched here.

`config_sha256` remains `0d207746…`; seal **UNOPENED**; execution **RELEASE-BLOCKED**. Full suite
per commit: the review wave is three commits (`a5a258e` C1·I1~I8, `73cb60d` C2, then the provenance boundary), each validated by one run of the tree it commits — `a5a258e` 2991 passed / 3 skipped / 0 failed (18m15s); `73cb60d` 2996 passed / 3 skipped / 0 failed (18m17s); boundary 3006 passed / 3 skipped / 0 failed (18m18s); the numbers on this line were filled in after each run and are the only bytes that differ from it.

**2026-09-05 (late) — the pending owner-decision list, decided under delegation, each on a
measurement.**

The owner delegated the five pending decisions in writing ("오너 결정 목록에 대한 권한을 너에게
위임한다. 최고의 권장사항 도출 후 진행해라"). What was decided, what was measured first, and what
each does not do:

- **§10.5 Amendment A — inserted and clause-revised.** Signed 2026-09-03, but the sentence was
  not in the spec (`grep` returned nothing): the claim contract still did not say what the
  access count counts. Inserted into §10.6, beside "sealed access 0→1", not §10.5 — the
  delegation is to derive the best placement, and the record says why. The disputed clause
  "함께 보증한다" became "함께 확보하도록 설계돼 있다 — … 열려 있는 동안 조건부" because
  `seal.transient-inode-mutation-restoration` is open and a guarantee is not delivered while it is.
- **§10.5 Amendment B — signed and implemented.** Measured: the config fields exist and are
  loader-enforced; `band_sensitivity` exists with tests; the connectivity numbers come from the
  08-29 decision's measurement. The placement was **not implemented** — nothing in `phase2b.py`,
  `durable.py` or `terminal.py` mentioned sensitivity. Now: computed in the sealed run from the
  same `bounds` the verdict used, carried on `Phase2bResult.band_sensitivity`, written into the
  terminal body as `band_sensitivity` + `band_sensitivity_checksum`, **outside** the five
  components of `final_result_checksum` (composition unchanged, still pinned), and the durable
  finalizer refuses a block whose checksum does not bind it. The durable-ledger spec's exact
  COMPLETE/INVALID roster names the two new fields. Mutations: sensitivity from the single-unseen
  bounds, a checksum over a different dict, the block folded into `final_result_checksum`, and
  the finalizer's check removed — each killed by the test whose name makes the claim (two of them
  also refused the fixture run itself, because the finalizer caught the writer).
- **Amendment C — signed.** Measured: no `print`/stdout write in `preflight_cmd.py`; the runbook's
  two-operator control is file-mediated; the spec sentence was present verbatim. Replaced, and
  `test_preflight_writes_nothing_to_stdout` pins it (fails by name when a `print` is added).
- **Seal guard 21 → 23** (`smoke_evidence.py` and its CLI; audit-log `048642b`): criterion (c),
  what the evidence records; the CLI by the `driver/cli.py` precedent.
- **Daily-review wrapper — audit identity and age gate** (audit-log `048642b`): measured, one
  audit (09/02 15:38 EDT) was reviewed three times on three days. An already-reviewed stamp is
  not reviewed again; if it is also older than 24h the state file records `DEGRADED_STALE_AUDIT`
  without spending an agent run; a late but unreviewed audit is still reviewed. Eight executed
  checks in the gate suite (six decisions, the age arithmetic, the wiring order).
- **Guard fan-in ≥ 4 — adjudicate, not block** (audit-log `048642b`): the classifier marks such
  paths ⚖ and the fix run leaves an `Owner-Adjudication:` trailer; the list is re-measured by the
  gate suite each run. The first hand-copied list (four modules) was already stale — adding two
  guards had pushed `fit_role.py` to four — and the measurement caught it before commit. Five now.

**What this does NOT close:** `seal.transient-inode-mutation-restoration`; the true magnitude of the
method-differential gene effect (§10.5 B reports at each λ *because* it is unmeasured); the
attestation residuals of the smoke producer (exit code, sealed pair list, row-identity object
content); and the wrapper's identity is the stamp string — a same-stamp content change is caught by
the verbatim snapshot comparison, not by this gate. `config_sha256` remains `0d207746…`; seal
**UNOPENED**; execution **RELEASE-BLOCKED**. Full suite on the committed tree: 3010 passed / 3 skipped / 0 failed (18m49s); this line's numbers were filled in after the run and are the only bytes that differ from it.

**2026-09-06 — the 09/06 review's three REFUTE requests, answered by execution; one more consumer
closed.**

The 09/06 review (`d980595`, first cross-audit in three days) reproduced none of the five 09/05 commits'
defects at the pin and filed no fix request. It asked three things of this side, and each was measured:

- **"Is there another consumer that re-reads a provenance path after the builder verified it?"**
  Yes, one. The cited `worker_identity.py:348-352` does not exist, and `identity_lock.py:312`
  re-hashes but compares with the declaration. `resolve_scientific_runtime_context` →
  `capture_environment(lockfile_path)`, however, hashes the dependency manifest by pathname before
  provenance assembly and the RunLedger serialises that digest into the pre-access ledger as
  `environment.lockfile_sha256`, compared with nothing. Probe with a control arm: swap during the
  capture, restore before provenance → load succeeds, provenance passes, ledger digest ≠ declared.
  Closed (fourth commit of this wave): `load_run_spec_carrier` refuses when the captured digest is not
  the declared `scientific.dependency_manifest.sha256`; the removal mutant is killed by name. Not
  claimed: that lane 3 now has no other consumer — the review's method is the way to find one.
- **"Any path that binds `sealed_pair_ids` outside the bundle?"** None (grep, confirmed). The material
  is the split manifest, whose digest the fit-role artifact's provenance carries as
  `pair_manifest_sha256` and the verified reader re-binds — the next binding, on seal-guard paths.
- **"A meaningful mutation the three roster tests survive?"** Byte-order → code-point order is an
  equivalent mutant (UTF-8 preserves code-point order; 0 disagreements in 200k random pairs).
  Ignoring `combo_sep` survived, because every test used the default; `ae8b8b0` adds an artifact
  written with `"+"` and the test that requires both rosters spelled with it.

Still with the owner (the review's DISPUTED and design items): whether B·C's delegated signatures and
A's post-signature correction are to be re-signed in the owner's hand (§6.1; Codex M1 recommends it);
whether crash-left unbound sidecars stay fail-closed with manual cleanup or move to an atomic
directory publish with failure injection (§6.3); and the go-ahead for deriving the sealed roster from
the split manifest (seal-guard paths). Full suite on the committed tree: 3013 passed / 3 skipped / 0 failed (18m30s); this line's numbers were filled in after the run and are the only bytes that differ from it.

## 이 문서가 *아닌* 것 (중복 금지)

- **governance / safety invariant / seal 규칙** → `CLAUDE.md`#sources, #invariants, #seal
- **scientific claim 정의** → 각 sub-project **spec**
- **task 세부 · 체크박스 · 구현 순서** → 각 **plan**
- **exact split / threshold / seed / metric** → **config** (`configs/compose_k562_v1_phase2.yaml`)
- **시간순 audit trail** → **git log**
- **agent session-start recall** → private MEMORY (repo 밖)

<!-- maintainer note: index-only. 새 sub-project나 상태 전이 시 위 표의 '상태' 열과 critical-path만 갱신하고,
     Updated 스탬프(date @ commit)를 함께 바꾼다. 세부/claim/param을 여기에 복제하지 않는다. seal 개봉 시 frozen. -->
