# COMPOSE dev-pod — real GEARS/CPA workers + activation-evidence regeneration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **⚠️ POD-EXECUTION PLAN, not a local-TDD plan.** Unlike the other COMPOSE plans, most of this work runs on an **A100 development pod** — `gears`/`cpa` are installed ONLY in the two locked envs, the GEARS GO-graph and real Norman data live in pod object storage, and the fits need a GPU. The subprocess backend + protocol + leakage guards + stub worker are already **merged and locally-verified** (sub-project A/B). This plan builds the pieces that the design spec (`specs/2026-07-01-compose-deep-baselines-design.md` §0.36, §1.5, §7) explicitly defers to the pod. Verification for pod tasks is a **pod smoke/integration test**, not local `pytest`. Only the worker *scaffold contract test* and the config-schema edits are locally checkable. **This is a DEVELOPMENT pod, NOT the sealed run — it opens NO seal.**

**Goal:** Produce, review, and commit to `main` everything the sealed-run runbook (`runbooks/2026-07-02-compose-k562-pod-sealed-run.md`) §2.2/§4/§2.5 still lists as BLOCKED — the real `gears_worker.py`/`cpa_worker.py`, their pinned locked envs + GO-graph resource manifest, and the activation evidence regenerated under the **active** config with every null activation-requirement established — so a subsequent separate sealed-run pod can open the COMPOSE seal exactly once against a clean, owner-approved Git SHA.

**Architecture:** The real workers are the stub worker's scaffold (`scripts/baselines/stub_worker.py`: `read_payload` → `validate_fit_role_artifact` → load fit-role `.h5ad` → fit on `{singles, combo_calibration}` native cells → `apply_response_projection` → `write_predictions` envelope) with the deterministic stub fit replaced by a real GEARS/CPA fit in the locked env. The controller (`SubprocessBaselineBackend`, merged) and the payload/prediction/manifest contract are UNCHANGED — the workers plug into the existing seam. Evidence regeneration re-runs the two committed report scripts (`scripts/compose_phi_rank_report.py`, `scripts/compose_detectable_effect_report.py`) on real Norman data under the finalized active config, and fills the config's null activation-blocker fields.

**Tech Stack:** Python 3.12 main env (`.venv`); two locked envs `gears_env`/`cpa_env` (from `docs/activation-evidence/compose/requirements.{gears,cpa}_env.lock`); `gears`, `cpa-tools`, torch+CUDA (pod GPU); existing `alive.compose.baseline_subprocess` / `fit_role` contract; `uv` for env sync.

## Global Constraints

Copied verbatim from the runbook (§1/§2.2/§4/§2.5), the B design spec, and `CLAUDE.md`. Every task's requirements implicitly include this section.

- **This is a DEVELOPMENT pod. It opens NO seal.** No task reads a sealed pair outcome, calls `evaluate_sealed_once`, or constructs a `ComposeOutcomeStore`. Workers receive only the non-sealed fit-role artifact + response projection; sealed pair IDs enter ONLY as `sealed_pair_ids` for the leakage guard, never as fit rows.
- **Training roles are EXACTLY `{singles, combo_calibration}`** (`ALLOWED_ADAPTER_ROLES`). `control` is payload reference data (response-space projection + δ baseline), NEVER a training role and NEVER in `allowed_roles`.
- **Workers are committed BEFORE the sealed run.** Per runbook §2.2, the sealed session MUST NOT write or modify a worker. Every deliverable here lands on `main` via PR review + local checks first.
- **Do not download resources at fit time.** The GEARS GO-graph/gene2go and both locked envs are acquired/pinned in Phase 0 and recorded (license · version · URL · SHA-256). Workers read only pre-acquired, manifested resources.
- **No published-baseline weakening.** GEARS/CPA run their published/default config on `{singles, combo_calibration}`; no knob is chosen from any outcome; the only outcome-free tuning input allowed is the supplied calibration gene-disjoint OOF fold assignment (`oof_folds` in the payload).
- **Payload contract is frozen (do NOT change the schema).** `read_payload` requires EXACTLY `_REQUIRED_KEYS` (`src/alive/compose/baseline_subprocess.py:31`): `{schema_version, response_dim, seed, allowed_roles, pair_ids, single_gene_ids, singles_response, control_mean, calibration_pair_ids, calibration_delta, pca_components, oof_folds, fit_role_artifact, response_projection}`. A worker that adds/drops a key fails `configure_payload`.
- **Prediction representation is method-locked in config, not worker-selected.** `gears.prediction_representation = raw_pseudobulk_approximation`; `cpa.prediction_representation = cell_raw_counts` (`configs/compose_k562_v1_phase2.yaml`). The worker receives it via `--prediction-representation` and must honor it.
- **The execution manifest must mirror the controller lock.** `ExecutionIdentityLock` recomputes `adapter_version`/`adapter_sha256`/`config_sha256`/`resource_sha256`/`environment_lock_sha256` and fails closed on divergence (`_verify_execution_manifest`). Worker-reported digests must equal the committed lock values, not runtime `__version__` (dependency-lock pinned specs are the source of truth; runbook §4 / B spec §2).
- **⚑ Config finalization precedes evidence regeneration.** `config_sha256 = sha256_json(raw)` over the whole config. Filling the null activation-blocker fields (`regimes.power_status`, `baselines.{gears,cpa}.{revision,environment_status}`, `baselines.gears.approximation_bias_report_sha256`) CHANGES the config digest away from the current active `a47001946f4b74265b29357467bffaef83d8d15bc1ea8868cc46abd51bfbb4f1`. Therefore establish those fields FIRST, commit the finalized config, and ONLY THEN regenerate evidence — so the embedded `config_sha256` binds the FINAL run identity (runbook §2.5 "config digest 바뀌면 evidence 결속 재생성"; §4 lineage note). Regenerating under an intermediate config would repeat the very drift this fixes.
- **Clean tree + owner-approved exact Git SHA.** `git status --porcelain` empty; the runbook flips to `READY` only after the owner approves the exact SHA (Global §2.5).
- **DRY/YAGNI/frequent commits.** Reuse `baseline_subprocess`/`fit_role`/the report scripts. Commit only the named files per task (never `-A`/`.`). No raw/processed data, checkpoints, or credentials committed (`CLAUDE.md` #data-eval).

---

## Open decisions to settle BEFORE Phase 1 (owner + pod)

These are the B spec §7 open questions; the plan pins the contract, not these values. **Hard Phase-0 entry gate — Phase 1 MUST NOT begin until all five are recorded** (owner-supplied values + pod acquisition); this is a gate, not a preamble:

1. **GEARS published config + revision.** Exact `epoch/batch/optimizer/early-stop/seed` and the pinned `gears` package revision to record in `configs/…yaml::baselines.gears.revision` and the dependency lock. Source: GEARS paper/repo default for K562 Perturb-seq.
2. **GEARS GO-graph / gene2go source.** Exact URL + version + license + SHA-256 to record in the resource manifest (Phase 0). Must be pre-acquired, not fetched at fit time.
3. **CPA (`cpa-tools`) setup.** Published/default config for combo prediction + pinned revision for `baselines.cpa.revision`.
4. **`approximation_bias` measurement for GEARS.** `gears.prediction_representation = raw_pseudobulk_approximation` requires the pseudobulk-approximation bias to be measured and its report SHA recorded in `approximation_bias_report_sha256` (currently null = explicit activation blocker). Define how bias is quantified (design task in Phase 2). CPA is `cell_raw_counts` (exact) → its `approximation_bias_report_sha256` stays null by design.
5. **Dev-pod provider/instance** (prior A100 pattern: RunPod A100, torch cu124 — see [[cartographer-mvp-built-merged]]).

---

## File Structure

- `scripts/baselines/gears_worker.py` — real GEARS worker (pod-authored against the stub contract). CREATE.
- `scripts/baselines/cpa_worker.py` — real CPA worker. CREATE.
- `docs/activation-evidence/compose/go_resource_manifest.json` — GO-graph/gene2go license·version·URL·SHA-256. CREATE.
- `docs/activation-evidence/compose/requirements.gears_env.lock` / `requirements.cpa_env.lock` — MODIFY only if the pinned revisions change vs the committed locks.
- `docs/activation-evidence/compose/gears_cpa_dependency_lock.json` — MODIFY: pin the confirmed `gears`/`cpa` revisions.
- `configs/compose_k562_v1_phase2.yaml` — MODIFY: fill `regimes.power_status`, `baselines.{gears,cpa}.{revision,environment_status}`, `baselines.gears.approximation_bias_report_sha256`.
- `docs/activation-evidence/compose/real_norman_phi_rank_report.json` — REGENERATE under the finalized config.
- `docs/activation-evidence/compose/real_norman_detectable_effect_report.json` — REGENERATE under the finalized config.
- `docs/activation-evidence/compose/README.md` — MODIFY: record the regeneration provenance (git SHA, config_sha256, pod instance).
- `scripts/compose/measure_pseudobulk_approximation_bias.py` — CREATE (Phase 2): quantify GEARS pseudobulk-approximation bias on non-sealed roles; emit the report whose SHA fills `approximation_bias_report_sha256`.
- `tests/alive/compose/test_worker_contract.py` — CREATE (Phase 1, LOCAL): assert each real worker's CLI + manifest fields + envelope match the frozen contract, using a tiny synthetic fit-role artifact and a **fake env** (the fit body is import-guarded so the contract surface is testable without `gears`/`cpa`).
- Runbook `runbooks/2026-07-02-compose-k562-pod-sealed-run.md` — MODIFY (final): flip status BLOCKED → READY at §2.5 owner sign-off.

---

## Phase 0 — pod provisioning (pod, no seal)

### Task 0.1: locked envs + import probe

**Files:** none committed (provisioning); may MODIFY `requirements.{gears,cpa}_env.lock` if revisions change.

**Steps:**
- [ ] Clone the current `main` (`1c46708` or later) to the A100 pod, detached checkout; `git rev-parse HEAD` recorded; `git status --porcelain` empty.
- [ ] `uv sync --frozen` the main env from the committed lock; record instance/GPU/image/CUDA/start-time.
- [ ] Create `gears_env` and `cpa_env` fresh from `docs/activation-evidence/compose/requirements.{gears,cpa}_env.lock`; fresh-sync verify.
- [ ] Probe: `<gears_env>/python -c "import gears, torch; print(torch.cuda.is_available())"` and `<cpa_env>/python -c "import cpa, torch"`. Both import + CUDA True.
- [ ] **RUN-smoke (NOT just import) — the committed lock only verified imports and misses runtime landmines.** In each env, run the actual published workflow on a small real-Norman slice: GEARS `pert_data.load('norman')` + a 1-epoch `train`; CPA `CPA.setup_anndata(...)` with the Norman gene-combo keys (`deg_uns_key`, no `smiles_key`, `max_comb_len=2`) + a 1-epoch `train`. **Known landmine (decision #3):** `cpa-tools==0.7.2` + the committed `numpy==1.26.4` will likely raise `AttributeError: module 'numpy' has no attribute 'int'` in `setup_anndata`'s `deg_uns_key` branch (`.astype(np.int)`, removed in numpy ≥1.24) — so this smoke, not the import probe, decides the cpa version pin. **Recommended target: `cpa-tools==0.8.5`** (earliest tagged version with the `np.int`+smiles fixes, closest to the verified 0.7.2-era stack → minimal delta; see the decision-proposals doc §3). 0.8.2 still has `np.int`; 0.8.8 works but is untagged + more dep drift.
- [ ] **Acceptance:** both imports succeed AND both RUN-smokes complete (setup + 1-epoch fit, no crash) on real Norman. Record the resolved package revisions (for Task 2.1's dependency-lock pin). If the cpa 0.7.2 RUN-smoke fails on np.int/SMILES, either patch/adjust the env or move to a cpa 0.8.x that runs Norman, and MODIFY `requirements.cpa_env.lock` + the dependency lock accordingly; commit `fix(compose): pin confirmed gears/cpa env revisions (RUN-verified on Norman)`.

### Task 0.2: GO-graph/gene2go acquisition + resource manifest

**Files:** Create `docs/activation-evidence/compose/go_resource_manifest.json`.

**Steps:**
- [ ] Pre-acquire the GEARS GO-graph/gene2go resource (decision #2) to pod object storage. Do NOT fetch at fit time.
- [ ] Emit `go_resource_manifest.json` = canonical JSON `{schema, resource, url, version, license, sha256, retrieved_git_sha}`; SHA-256 over the resource bytes.
- [ ] **Acceptance:** manifest bytes SHA recorded; the file is committed on the pod branch. `commit docs/activation-evidence/compose/go_resource_manifest.json` — `feat(compose): pin GEARS GO-graph resource manifest`.

### Task 0.3: Norman data + sequences sync + integrity

**Files:** none committed (raw data never committed — `CLAUDE.md` #data-eval).

**Steps:**
- [ ] Sync Norman `.h5ad` + ESM sequence JSON from object storage; byte-for-byte verify each SHA-256 against the committed data-card (`docs/data-cards/norman_compose_k562_v1.json`) / manifest. Mismatch → abort.
- [ ] **Acceptance:** every synced asset's SHA matches the committed manifest; paths recorded for Phase 1/2 CLIs.

---

## Phase 1 — real GEARS/CPA workers (pod-authored, local contract test)

### Task 1.1: local worker-contract test (LOCAL, TDD)

**Files:** Create `tests/alive/compose/test_worker_contract.py`.

**Interfaces (frozen — from `stub_worker.py` + `baseline_subprocess.py`):**
- Worker CLI: `--in <work_dir> --out <out_path> --approved-root <root> --prediction-representation {cell_raw_counts,raw_pseudobulk_approximation}`.
- Input: `read_payload(work_dir)` → dict with `_REQUIRED_KEYS` (14). Output: `write_predictions(out, preds: dict[(g,h)->np.ndarray(response_dim)], execution_manifest=manifest)`.
- Manifest keys (must match stub, `stub_worker.py:139-157`): `prediction_representation, adapter_version, adapter_sha256, expected_gene_order_sha256, observed_gene_order_sha256, checkpoint_sha256, worker_sha256, config_sha256, resource_sha256, environment_lock_sha256, fit_artifact_content_sha256, combined_request_sha256, predictions_sha256`.
- Worker MUST call `validate_fit_role_artifact(path, spec=…, approved_root=…, calibration_pair_ids=…, sealed_pair_ids=payload["pair_ids"], single_gene_ids=…)` before any fit (leakage guard).

- [ ] **Step 1: Write the failing test.** Build a tiny synthetic fit-role artifact (reuse `scripts/compose/build_fit_role_artifact.py` helpers or the existing fixture builders) with `{control, singles, combo_calibration}` rows; a minimal valid payload; then invoke each real worker with `--prediction-representation` set per config, with the fit body **import-guarded** so the *contract surface* runs without `gears`/`cpa`. Assert: (a) the envelope round-trips via `read_payload`/`write_predictions`; (b) manifest has exactly the 13 keys above — assert `predictions_sha256` is emitted as an empty placeholder by the worker and **filled by `write_predictions` downstream** (placeholder-then-filled, not a static value snapshot, so the test is not brittle to the fill); (c) `validate_fit_role_artifact` is invoked with `sealed_pair_ids == payload["pair_ids"]` (spy); (d) missing `gears`/`cpa` import raises a clear `WorkerUnavailable`-style error, not a silent stub. Run: `.venv/bin/python -m pytest tests/alive/compose/test_worker_contract.py -v` → FAIL (workers absent).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3–4:** (workers created in 1.2/1.3) → PASS; ruff.
- [ ] **Step 5: Commit** `tests/alive/compose/test_worker_contract.py` — `test(compose): real-worker contract surface (env-agnostic)`.

### Task 1.2: `gears_worker.py` (pod-authored)

**Files:** Create `scripts/baselines/gears_worker.py`.

**Contract (unchanged from stub; ONLY the fit body differs):** copy the stub scaffold — argparse (identical flags), `read_payload`, `FitRoleArtifactSpec` reconstruction + `validate_fit_role_artifact(...)`, load `.h5ad`, `apply_response_projection`, `write_predictions(out, preds, execution_manifest=manifest)`. Replace stub steps 2–4 with:
- Fit **GEARS** (published/default config, decision #1) on native full-gene cells with `role ∈ {singles, combo_calibration}` (NEVER `control`, NEVER a `sealed_pair_ids` cell), using the pre-acquired GO-graph (Task 0.2) and the supplied `oof_folds` for any OOF-only tuning. No outcome-based knob selection.
- Predict each requested `pair_ids` in native gene space; because `prediction_representation == raw_pseudobulk_approximation`, reduce to pseudobulk (`operator_input = native.mean(axis=0, keepdims=True)`) before `apply_response_projection`, mirroring the stub's representation branch. Return `(z.mean(axis=0) - control_mean)[:dim]`.
- Manifest: `adapter_version`/`adapter_sha256`/`config_sha256`/`resource_sha256`/`environment_lock_sha256` from the committed dependency lock + GO resource manifest (NOT runtime `__version__`); `worker_sha256` = this file's bytes; `checkpoint_sha256` = the fitted-model checkpoint bytes.

**Landmines:** `allowed_roles` stays `{singles, combo_calibration}`; the requested pairs are SEALED → passed only as `sealed_pair_ids` to the guard; a GEARS resource must exist on disk (fail closed if absent, never download).

- [ ] **Step 1:** Author the worker from the stub scaffold + GEARS fit body.
- [ ] **Step 2 (pod acceptance):** outcome-free Norman fit-role smoke in `gears_env` — build a real fit-role artifact from synced Norman (Task 0.3) via `scripts/compose/build_fit_role_artifact.py`, a small requested-pair set, run `<gears_env>/python scripts/baselines/gears_worker.py --in … --out … --approved-root … --prediction-representation raw_pseudobulk_approximation`; assert a valid `{predictions, execution_manifest}` envelope, correct pair roster/shape (`response_dim`), finite δ, and `validate_fit_role_artifact` passing (no sealed rows). The local Task-1.1 contract test also passes.
- [ ] **Step 3:** ruff on the worker.
- [ ] **Step 4: Commit** `scripts/baselines/gears_worker.py` — `feat(compose): real GEARS subprocess worker (pod)`.

### Task 1.3: `cpa_worker.py` (pod-authored)

**Files:** Create `scripts/baselines/cpa_worker.py`.

**Contract:** identical scaffold; fit **CPA** (`cpa-tools`, decision #3) on `{singles, combo_calibration}` native cells; `prediction_representation == cell_raw_counts` → `operator_input = native` (per-cell, no pseudobulk reduction), then `apply_response_projection`. Manifest digests from the committed lock; CPA needs no GO-graph (its `resource_sha256` records the committed CPA resource/config bytes).

- [ ] **Step 1:** Author from the stub scaffold + CPA fit body.
- [ ] **Step 2 (pod acceptance):** outcome-free Norman smoke in `cpa_env` (`--prediction-representation cell_raw_counts`); same envelope/roster/shape/finite/guard assertions; Task-1.1 contract test passes.
- [ ] **Step 3:** ruff. **Step 4: Commit** `scripts/baselines/cpa_worker.py` — `feat(compose): real CPA subprocess worker (pod)`.

### Task 1.4: two-env integration through the merged controller

**Files:** none new (exercises merged `SubprocessBaselineBackend` + `_verify_execution_manifest`).

- [ ] **Step 1 (pod acceptance):** run each worker through `SubprocessBaselineBackend`/`BaselineAdapter` end-to-end on the Norman fit-role artifact; assert `_validate_backend_output` passes (no missing/extra pair, correct dim, finite) and `_verify_execution_manifest` accepts the manifest (controller `ExecutionIdentityLock` mirrors the worker digests). Confirm `is_available` True in each env, and that a forced-unavailable env → `BaselineUnavailable` → Phase-2a freeze rejects the incomplete roster (INVALID), never a silent skip.
- [ ] **Step 2: Commit** (if any lock/manifest digest was corrected to make the controller mirror hold) the named file(s) — `fix(compose): reconcile worker manifest digests with committed lock`.

---

## Phase 2 — finalize config + regenerate activation evidence (pod)

### Task 2.1: establish env + revision + power activation-requirements (config edit)

**Files:** MODIFY `configs/compose_k562_v1_phase2.yaml`; MODIFY `docs/activation-evidence/compose/gears_cpa_dependency_lock.json`.

**Steps:**
- [ ] Pin `baselines.gears.revision` / `baselines.cpa.revision` to the confirmed env revisions (Task 0.1) in BOTH the config and the dependency lock.
- [ ] Set `baselines.{gears,cpa}.environment_status` from `unpinned_activation_blocker` → the pinned/established value once both locked envs are fresh-sync-verified (Task 0.1).
- [ ] Run the detectable-effect report (Task 2.3 tooling) to establish `regimes.power_status`; set it from `unestablished_activation_blocker` → the established value (double-unseen power passed / SNR per the report). **Consistency guard:** this is the SAME computation Task 2.3 regenerates under the finalized config — the `power_status` set here MUST equal what the Task-2.3 regenerated detectable-effect report shows. If they differ, the intermediate config drifted between 2.1 and 2.3; reconcile (re-read power under the finalized config) before committing the finalized config.
- [ ] **⚑ Do NOT regenerate evidence yet** — Task 2.2 must land the `approximation_bias_report_sha256` first so the config is FULLY finalized before evidence binds it (Global ⚑).

### Task 2.2: GEARS pseudobulk-approximation bias report

**Files:** Create `scripts/compose/measure_pseudobulk_approximation_bias.py`; MODIFY `configs/compose_k562_v1_phase2.yaml` (`baselines.gears.approximation_bias_report_sha256`).

**Steps:**
- [ ] **Pre-register the bias metric first** (decision #4): fix what is measured (the `raw_pseudobulk_approximation` vs per-cell discrepancy), on which **non-sealed** roles, and its direction/aggregation — BEFORE running it, so the report SHA that binds the final `config_sha256` is not outcome-shaped (it is an activation requirement, not a tunable).
- [ ] Author a script that quantifies, on **non-sealed** roles only, the pre-registered bias for GEARS; emit a canonical-JSON report with the bias metric + provenance.
- [ ] Run it on the pod; set `baselines.gears.approximation_bias_report_sha256` = the report file SHA-256 (CPA stays null — exact representation).
- [ ] **Acceptance + Commit:** `configs/compose_k562_v1_phase2.yaml` is now fully finalized (no `*_activation_blocker` / null activation field remains for the active roster). Record the new `config_sha256` (`load_compose_phase2_config(...).config_sha256`). Commit `configs/compose_k562_v1_phase2.yaml docs/activation-evidence/compose/gears_cpa_dependency_lock.json scripts/compose/measure_pseudobulk_approximation_bias.py <bias_report>` — `feat(compose): establish activation requirements (env/revision/power/bias) → finalize active config`. **This commit mints the FINAL run identity.**

### Task 2.3: regenerate the two evidence reports under the finalized config

**Files:** REGENERATE `docs/activation-evidence/compose/real_norman_phi_rank_report.json`, `docs/activation-evidence/compose/real_norman_detectable_effect_report.json`; MODIFY `docs/activation-evidence/compose/README.md`.

**Steps:**
- [ ] `<.venv or pod py> scripts/compose_phi_rank_report.py --config configs/compose_k562_v1_phase2.yaml --h5ad <norman.h5ad> --sequences <seqs.json> --out docs/activation-evidence/compose/real_norman_phi_rank_report.json --git-sha <finalized SHA>` — verify the embedded `config_sha256` equals the **finalized** active digest (NOT `d8c65ac4…`, NOT the pre-Task-2.2 `a4700194…`) and `activation` no longer reads `BLOCKED` for the active roster.
- [ ] `scripts/compose_detectable_effect_report.py --config configs/compose_k562_v1_phase2.yaml --phase1-config configs/compose_k562_v1_phase1.yaml --h5ad <norman> --sequences <seqs> --out docs/activation-evidence/compose/real_norman_detectable_effect_report.json --git-sha <finalized SHA>` — same config-binding check.
- [ ] Update `README.md` with the regeneration provenance (finalized git SHA, `config_sha256`, pod instance/date).
- [ ] **Acceptance:** both evidence files embed the finalized `config_sha256`; the runbook §4 `ActivationRecord.evidence_files` roster (6 files) each now carries a non-empty hash bound to the active run identity. Commit the regenerated evidence + README — `feat(compose): regenerate activation evidence under finalized active config`.

---

## Phase 3 — §2.5 release gate + runbook READY

### Task 3.1: full-suite + locked-env integration + independent review

- [ ] Run the approved full test suite on the pod main env (green) + each worker's locked-env integration test (Task 1.4) green.
- [ ] Assemble the complete checksum manifest: fit-role artifact, both workers, worker configs, GO resource, both env locks, dependency lock, regenerated evidence — all SHA-recorded.
- [ ] Independent reviewer confirms (runbook §2.5): leakage (workers touch no sealed outcome), exact `{singles, combo_calibration}` roster, response projection fidelity, pair alignment, single-seal-open path intact, final-ledger recovery — on the pod state.

### Task 3.2: owner Git-SHA approval → flip runbook to READY

**Files:** MODIFY `runbooks/2026-07-02-compose-k562-pod-sealed-run.md` (status line + §2.5).

- [ ] Owner approves the **exact Git SHA** to run. ONLY at this point:
- [ ] Change the runbook `현재 실행 상태` from `BLOCKED` to `READY (exact SHA <sha>, owner-approved <date>)`; note that §2.1(A)/§2.2(real workers)/§2.3(C driver)/§2.4(D) are all satisfied and the config/evidence lineage is bound to the finalized run identity.
- [ ] Commit `runbooks/2026-07-02-compose-k562-pod-sealed-run.md` — `docs(compose): runbook READY — dev-pod blockers cleared, owner-approved SHA`.
- [ ] **Handoff:** a SEPARATE sealed-run pod session executes the runbook (`phase2a → preflight → phase2b --confirm-seal`) and opens the COMPOSE seal exactly once. That is out of scope for this plan.

---

## Definition of Done

- Real `gears_worker.py` + `cpa_worker.py` committed, each passing the local contract test + the pod outcome-free Norman smoke in its locked env, and integrating through the merged controller with `_verify_execution_manifest` accepting the manifest.
- GO resource manifest + finalized dependency lock committed.
- `configs/compose_k562_v1_phase2.yaml` has NO remaining `*_activation_blocker`/null activation field for the active roster; `power_status`/`environment_status`/`revision`/gears `approximation_bias_report_sha256` all established; the FINAL `config_sha256` recorded.
- Both evidence reports regenerated so every `ActivationRecord` requirement (runbook §4, 6 files) carries a non-empty hash bound to the FINAL config; no `d8c65ac4…`/`activation=BLOCKED` lineage remains.
- Full suite + locked-env integration green; independent review passed; owner-approved exact Git SHA; runbook flipped to `READY`.
- **No seal opened.** The sealed run is a separate pod session.

## Self-Review notes (author)

- **Runbook coverage:** §2.2 (Tasks 0.1–0.2, 1.2–1.4), §2.1 fit-role already merged (used by Task 1.x), §2.3 driver merged, §2.4 ledger merged, §4 evidence lineage (Tasks 2.1–2.3), §2.5 release gate (Tasks 3.1–3.2). B spec §7 open questions surfaced as the pre-Phase-1 decisions.
- **Ordering landmine encoded:** config finalization (Task 2.1–2.2) STRICTLY precedes evidence regeneration (Task 2.3) so the embedded `config_sha256` binds the final run identity — the exact drift the runbook §4 note flags.
- **Contract fidelity:** workers reuse the frozen `read_payload`/`write_predictions`/`validate_fit_role_artifact`/`apply_response_projection` seam and the 14-key `_REQUIRED_KEYS` payload; the stub is the scaffold template; only the fit body is pod-authored.
- **Local vs pod split honored:** only the contract test (Task 1.1) + config-schema edits are locally checkable; every real fit + evidence regen is pod-verified, per B spec §1.5/§7 and `CLAUDE.md` #compute.
- **Not a scientific run:** opens no seal; establishes activation lineage only; the single seal opens later on a separate sealed-run pod after owner SHA approval.
