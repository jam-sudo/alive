# COMPOSE-K562-v1 — Sealed-Run Readiness Index

> **역할:** COMPOSE sealed A100 run까지 남은 작업의 단일 human-facing 인덱스.
> **현재 상태:** lifecycle **ACTIVE** · execution **RELEASE-BLOCKED** · seal **UNOPENED**.
> **이 문서는 아무것도 정의하지 않는다** — 세부(task)는 plan, claim은 spec, exact param은 config,
> 시간순 audit는 git이 authoritative다([sources of truth](../../CLAUDE.md#sources)). 상태 행이 authoritative
> 문서와 어긋나면 **authoritative 문서가 옳다**; 이 인덱스를 갱신한다.
> **Updated:** 2026-07-28 @ `45ad067` (branch `compose-ci-receipt-hardening`)
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
   **2026-07-29 unrepresentable-ridge guard (closes correction (1) above):** the open item is resolved
   without registering a new numerical criterion. Reachability was measured first, at the real geometry
   recorded in `activation-evidence/compose/real_norman_phi_rank_report.json` (41 combo-calibration pairs;
   `sym_dim` 10/21/36): the registered `lambda_grid` first degrades at factor scale `|z| ~ 1.4e3` and vanishes
   outright at `~4.6e3` (`lam=0.001`) through `~1.4e4` (`lam=0.1`). Factor scores are an orthonormal projection
   of their input, so `|z_i| <= ||centered input||`; under the registered response space
   (`normalize_total_median` + `log1p`, `n_hvg: 1500`) that bounds a single-gene shift by
   `sqrt(1500) * log1p(1e4) ~= 356` regardless of biology, which the production `build_gene_factors` turns into
   `|z| <= ~202` — still ~7x below first degradation. At the magnitudes actually recorded in
   `real_norman_detectable_effect_report.json` (`mean_pair_eps_l2 = 3.046`) `|z| ~ 3.8`, ~370x below. **The
   bypass is therefore not reachable on the registered data**; the residual gap is that the ESM block's scale
   is bounded by nothing in the repository and recorded in no report (the recorded `condition_number` is
   scale-invariant and cannot detect this class of defect at all). The guard added in `identify.py` is an
   exact-representability check, not a tolerance: for `lam > 0` it rejects a Gram whose every diagonal entry is
   unchanged by `lam*I`, i.e. the case where the matrix that would be solved is the unregularized one.
   It registers no threshold, so `config_sha256` and the run identity **do not move**. Instrumenting the whole
   compose suite recorded 2106 positive-`lambda` fits, all with the penalty fully applied (worst case `|z|`
   2.33), so the guard fires nowhere the existing corpus reaches. Two further findings are recorded rather
   than acted on. (a) The earlier reading that a bypassed candidate would merely produce garbage and lose
   selection is **withdrawn**: with the guard mutated out, the bypassed `lam=0.001` candidate ties on theta and
   the registered tie-break resolves ties to the LARGER lambda, so selection actively *prefers* it and the run
   would record a `selected_lambda` it never applied. (b) At `k_total=8` the OOF train folds are structurally
   rank-deficient on the real 41-pair calibration set (`sym_dim` 36, and a gene-disjoint train fold drops both
   the held-out and the cross-group pairs), so the `lam=0.0` candidate at `k=8` is expected to be recorded
   non-viable on real data — a pre-seal-observable prediction, and the regime where the ridge is load-bearing.
   Scope of the guard: it detects a penalty that vanished outright; it does not certify the conditioning of a
   partially-rounded ridge, which remains the rank/condition gates' job. Seal state remains **UNOPENED**;
   execution remains **RELEASE-BLOCKED**.
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
