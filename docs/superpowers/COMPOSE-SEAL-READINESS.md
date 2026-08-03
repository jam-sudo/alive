# COMPOSE-K562-v1 — Sealed-Run Readiness Index

> **역할:** COMPOSE sealed A100 run까지 남은 작업의 단일 human-facing 인덱스.
> **현재 상태:** lifecycle **ACTIVE** · execution **RELEASE-BLOCKED** · seal **UNOPENED**.
> **이 문서는 아무것도 정의하지 않는다** — 세부(task)는 plan, claim은 spec, exact param은 config,
> 시간순 audit는 git이 authoritative다([sources of truth](../../CLAUDE.md#sources)). 상태 행이 authoritative
> 문서와 어긋나면 **authoritative 문서가 옳다**; 이 인덱스를 갱신한다.
> **Updated:** 2026-08-03 @ `9eb1b1f` (branch `compose-seal-consumed-hardening`)
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
   check; budget the re-archive rather than the deletion. **Open item:** record the actual interpreter in the
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
