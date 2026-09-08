# COMPOSE dev-pod — real GEARS/CPA workers + activation-evidence regeneration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **⚠️ POD-EXECUTION PLAN, not a local-TDD plan.** Unlike the other COMPOSE plans, most of this work runs on an **A100 development pod** — `gears`/`cpa` are installed ONLY in the two locked envs, the GEARS GO-graph and real Norman data live in pod object storage, and the fits need a GPU. The subprocess backend + protocol + leakage guards + stub worker are already **merged and locally-verified** (sub-project A/B). This plan builds the pieces that the design spec (`specs/2026-07-01-compose-deep-baselines-design.md` §0.36, §1.5, §7) explicitly defers to the pod. Verification for pod tasks is a **pod smoke/integration test**, not local `pytest`. Only the worker *scaffold contract test* and the config-schema edits are locally checkable. **This is a DEVELOPMENT pod, NOT the sealed run — it opens NO seal.**

**Goal:** Commit and review the real worker/code/contracts and bias-null basis config, freeze one owner-candidate
execution commit `C`, then publish the approximation-bias report, mechanically finalized config, analytical
activation evidence and owner-approved ResolvedRunSpec to a durable external approved-artifacts root. A subsequent separate
sealed-run pod may open the COMPOSE seal exactly once only against clean detached `C` and those immutable bytes.

**Architecture:** The real workers are the stub worker's scaffold (`scripts/baselines/stub_worker.py`: `read_payload` → `validate_fit_role_artifact` → load fit-role `.h5ad` → fit on `{singles, combo_calibration}` native cells → `apply_response_projection` → `write_predictions` envelope) with the deterministic stub fit replaced by a real GEARS/CPA fit in the locked env. The controller (`SubprocessBaselineBackend`, merged) and the payload/prediction/manifest contract are UNCHANGED — the workers plug into the existing seam. After `C` is frozen, PREPARE generates the bias report directly outside Git, derives the final config by changing its single report-SHA leaf, then runs the two committed report scripts (`scripts/compose_phi_rank_report.py`, `scripts/compose_detectable_effect_report.py`) against that final config at the same `C`.

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
- **⚑ Freeze commit, then one-way external finalization.** `config_sha256 = sha256_json(raw)` over the whole config.
  Commit `C` contains all established env/revision/power fields but keeps
  `baselines.gears.approximation_bias_report_sha256: null` as the bias-null basis. At clean detached `C`, generate
  the bias report into a fresh external stage, derive the final config there by changing only that leaf, and only
  then generate config-bound evidence. Never commit these generated bytes afterward: report `git_commit`, owner
  `approved_git_sha`, and runtime HEAD must remain exactly `C`. This avoids both config drift and an impossible
  Git/report fixed point.
- **Clean tree + owner-approved exact Git SHA.** `git status --porcelain` empty. Owner approval is an immutable
  external ResolvedRunSpec whose `scientific.activation_evidence` block is the owner registration; no
  post-approval READY/evidence commit may move HEAD.
- **DRY/YAGNI/frequent commits.** Reuse `baseline_subprocess`/`fit_role`/the report scripts. Commit only the named files per task (never `-A`/`.`). No raw/processed data, checkpoints, or credentials committed (`CLAUDE.md` #data-eval).

---

## Open decisions to settle BEFORE Phase 1 (owner + pod)

These are the B spec §7 decisions. Decision #2 is now resolved by the committed v2
manifest; #1, #3–#5 and the reproducibility evidence in Task 0.1 remain open. **Hard
Phase-0 entry gate — Phase 1 MUST NOT begin until every unresolved decision and every
Task-0 acceptance condition is recorded.** This is a gate, not a preamble:

1. **GEARS published config + revision.** Exact `epoch/batch/optimizer/early-stop/seed` and the pinned `gears` package revision to record in `configs/…yaml::baselines.gears.revision` and the dependency lock. Source: GEARS paper/repo default for K562 Perturb-seq.
2. **GEARS GO-graph / gene2go source — RESOLVED.** The committed v2 manifest binds Harvard
   Dataverse `doi:10.7910/DVN/Q2ZV3E`, CC0-1.0, exact datafile/dataset/file versions,
   sizes, upstream MD5s, acquired SHA-256s, and extracted-CSV SHA-256. Phase 0 must only
   reproduce and verify those bytes; it may not silently select another resource.
3. **CPA (`cpa-tools`) setup.** Published/default config for combo prediction + pinned revision for `baselines.cpa.revision`.
4. **`approximation_bias` measurement for GEARS.** `gears.prediction_representation = raw_pseudobulk_approximation` requires the pseudobulk-approximation bias to be measured and its report SHA recorded in `approximation_bias_report_sha256` (currently null = explicit activation blocker). Define how bias is quantified (design task in Phase 2). CPA is `cell_raw_counts` (exact) → its `approximation_bias_report_sha256` stays null by design.
5. **Dev-pod provider/instance** (prior A100 pattern: RunPod A100, torch cu124 — see [[cartographer-mvp-built-merged]]).

---

## File Structure

- `scripts/baselines/gears_worker.py` — real GEARS worker (pod-authored against the stub contract). CREATE.
- `scripts/baselines/cpa_worker.py` — real CPA worker. CREATE.
- `docs/activation-evidence/compose/go_resource_manifest.json` — committed v2 GO-resource identity contract. VERIFY; MODIFY only through an owner-reviewed protocol change.
- `docs/activation-evidence/compose/requirements.gears_env.lock` / `requirements.cpa_env.lock` — MODIFY only if the pinned revisions change vs the committed locks.
- `docs/activation-evidence/compose/gears_cpa_dependency_lock.json` — MODIFY: pin the confirmed `gears`/`cpa` revisions.
- `docs/activation-evidence/compose/{gears,cpa}_smoke_pair_roster.json` — CREATE in
  Task 0.1: outcome-free sorted training/sealed pair rosters used for independent overlap
  recomputation; schema `compose_smoke_pair_roster_v1`.
- `docs/activation-evidence/compose/{gears,cpa}_smoke_artifacts.json` — CREATE in
  Task 0.1: durable URI, immutable object version, and SHA-256 for the Norman source,
  fit-role artifact, row-identity manifest, smoke script, command log, and checkpoint;
  schema `compose_backend_smoke_artifact_manifest_v1`.
- `docs/activation-evidence/compose/python_artifact_manifest.json` — CREATE in Task 0.1:
  exact wheel/sdist artifact selected for every package in both requirements locks; schema
  `compose_python_artifact_manifest_v1`.
- `configs/compose_k562_v1_phase2.yaml` — MODIFY before `C`: fill `regimes.power_status` and
  `baselines.{gears,cpa}.{revision,environment_status}`; retain the GEARS bias-report SHA as null basis.
- `$APPROVED_ARTIFACTS_ROOT/stage1/configs/compose_k562_v1_phase2.finalized.yaml` — DERIVE after `C`,
  changing only the GEARS bias-report SHA leaf; never commit.
- `$APPROVED_ARTIFACTS_ROOT/stage1/activation-evidence/compose/real_norman_approximation_bias_report.json`
  — GENERATE after `C`; never commit.
- `$APPROVED_ARTIFACTS_ROOT/stage1/activation-evidence/compose/real_norman_phi_rank_report.json` —
  GENERATE under the staged finalized config; never commit.
- `$APPROVED_ARTIFACTS_ROOT/stage1/activation-evidence/compose/real_norman_detectable_effect_report.json`
  — GENERATE under the staged finalized config; never commit.
- `docs/activation-evidence/compose/README.md` — MODIFY before `C` only to document that tracked reports are
  historical snapshots; runtime regeneration provenance belongs in the external manifest/registration.
- `scripts/compose/measure_pseudobulk_approximation_bias.py` — CREATE (Phase 2): quantify GEARS pseudobulk-approximation bias on non-sealed roles; emit the report whose SHA fills `approximation_bias_report_sha256`.
- `tests/alive/compose/test_worker_contract.py` — CREATE (Phase 1, LOCAL): assert each real worker's CLI + manifest fields + envelope match the frozen contract, using a tiny synthetic fit-role artifact and a **fake env** (the fit body is import-guarded so the contract surface is testable without `gears`/`cpa`).
- Runbook `runbooks/2026-07-02-compose-k562-pod-sealed-run.md` — MODIFY before `C` to define the external
  publication contract. Do not make a post-`C` READY commit; the external owner-approved ResolvedRunSpec is
  authoritative.

---

## Phase 0 — pod provisioning (pod, no seal)

### Task 0.1: locked envs + auditable, seal-safe run evidence

**Files:** MODIFY `gears_cpa_dependency_lock.json`; may MODIFY
`requirements.{gears,cpa}_env.lock` if revisions change. Store logs/checkpoints outside
Git and bind their bytes by SHA-256 in the dependency lock.

**Steps:**
- [ ] Clone the owner-approved exact SHA to the A100 pod, detached checkout; record the full
  `git rev-parse HEAD`; require `git status --porcelain` empty.
- [ ] `uv sync --frozen` the main env from the committed lock; record
  instance/GPU/image **digest**/driver/CUDA/uv/start-time. A mutable image tag is not a digest.
- [ ] Create `gears_env` and `cpa_env` fresh from `docs/activation-evidence/compose/requirements.{gears,cpa}_env.lock`; fresh-sync verify.
- [ ] Resolve every wheel/sdist into a content-addressed wheelhouse, record filename +
  package/version + source index + SHA-256 in a canonical manifest, verify the manifest
  before install, and put its safe relative path + file SHA-256 in
  `environment_reproducibility`. Its exact environment/package roster must equal both
  requirements locks. Version-only flat
  locks and `--index-strategy unsafe-best-match` are insufficient for release evidence.
- [ ] Probe: `<gears_env>/python -c "import gears, torch; print(torch.cuda.is_available())"` and `<cpa_env>/python -c "import cpa, torch"`. Both import + CUDA True.
- [x] **Compatibility diagnosis observed (not acceptance evidence):** CPA 0.7.2 failed on
  `np.int` and CPA 0.8.5 completed an observed one-epoch smoke; GEARS required the
  era-consistent pandas/scipy stack and then completed an observed one-epoch smoke. These
  observations justify the current pins but did not capture immutable input rows, logs,
  checkpoints, or sealed-pair disjointness. The dependency lock therefore remains
  `INCOMPLETE`.
- [ ] Build each smoke input **only** from the COMPOSE fit-role artifact. Training rows are
  exactly `{singles, combo_calibration}`; controls are reference-only. For GEARS, construct
  a new `PertData` dataset from that role-filtered AnnData (do not accept
  `PertData.load('norman')` plus GEARS' own published split as release evidence). For CPA,
  call `setup_anndata` on the same role-filtered artifact. No sealed outcome column or
  sealed response may enter either process.
- [ ] Before fitting, emit one committed `compose_smoke_pair_roster_v1` per backend with
  exact training roles `['singles', 'combo_calibration']` and canonical sorted unique
  training-pair and sealed-pair rosters; hash both;
  compute their exact set intersection; require `sealed_pair_overlap_count == 0`. Also hash
  the Norman source, fit-role artifact, fit-role row identity, exact smoke script, complete
  stdout/stderr command log, and resulting checkpoint; retain each in durable storage and
  emit a committed `compose_backend_smoke_artifact_manifest_v1` with a durable URI,
  immutable object version, and matching SHA-256; record the exit code. A hash for a
  discarded or unlocatable object is not evidence.
- [ ] Populate both backends' exact fields in `run_gate.required_evidence`, set per-backend
  completion flags, remove `missing_evidence`, and change `seal_safety_status` to
  `VERIFIED_ZERO_OVERLAP` only after the checks above pass. Recompute `manifest_checksum`.
  Do this with `scripts/compose_smoke_evidence.py promote --inputs <bundle> --evidence-dir
  docs/activation-evidence/compose` (`alive.compose.smoke_evidence`), not by hand: it derives
  both sides of every cross-check from one computation, refuses sealed overlap, a non-zero
  exit code, a BLOCKED activation text or a malformed identity before building anything,
  validates a staged copy with `validate_dependency_lock`, and publishes the sidecars
  write-once with the lock last. A refusal leaves the directory byte-identical. The training
  roster is derived from the fit-role artifact through the worker's own verified reader
  (`read_verified_fit_role_artifact`), so the roster and `fit_role_artifact_sha256` describe
  one object; `exit_code`, the sealed pair list (`sealed_pair_ids`, the payload's `pair_ids`)
  and the content of the row-identity object remain the harness's attestation.
- [ ] **Acceptance:**
  `validate_dependency_lock(...)` returns `run_gate.evidence_status == "COMPLETE"`; a
  negative test that inserts one sealed pair into the training roster fails closed; both
  fresh environments reproduce from the verified wheelhouse; no seal was opened. Commit as
  auditable **fit-role smoke evidence**, never as a generic "RUN-verified on Norman" claim.

### Task 0.2: GO-graph/gene2go acquisition + resource manifest

**Files:** Verify the committed `docs/activation-evidence/compose/go_resource_manifest.json`.

**Steps:**
- [x] Exact dataset DOI, CC0-1.0 license, three Dataverse datafile IDs/versions/sizes,
  upstream MD5s, acquired SHA-256s, and extracted-CSV SHA-256 are committed in schema v2.
- [ ] Pre-acquire those exact bytes to pod object storage. Do NOT fetch at fit time. Verify
  byte count, upstream MD5, and SHA-256 for every resource and the extracted CSV.
- [ ] **Acceptance:** `validate_go_resource_manifest(...)` passes; the observed local hashes
  equal the committed values; the dependency lock's GO-manifest file SHA matches; no
  resource or manifest byte changes during fit.

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

## Phase 2 — freeze commit + publish finalized config/evidence externally (pod)

### Task 2.1: establish env + revision + power in the committed bias-null basis

**Files:** MODIFY `configs/compose_k562_v1_phase2.yaml`; MODIFY `docs/activation-evidence/compose/gears_cpa_dependency_lock.json`.

**Steps:**
- [ ] Pin `baselines.gears.revision` / `baselines.cpa.revision` to the confirmed env revisions (Task 0.1) in BOTH the config and the dependency lock.
- [ ] Set `baselines.{gears,cpa}.environment_status` from `unpinned_activation_blocker` → the pinned/established value once both locked envs are fresh-sync-verified (Task 0.1).
- [ ] Run the detectable-effect computation (Task 2.3 tooling, scratch output outside Git) to establish
  `regimes.power_status`; set it from `unestablished_activation_blocker` to the registered established value.
  **Consistency guard:** Task 2.3 must recompute the same status under the staged finalized config. If it differs,
  do not publish registration; reconcile the basis and create a new candidate `C`.
- [ ] Keep `baselines.gears.approximation_bias_report_sha256: null`. Do not regenerate authoritative evidence
  yet; Task 2.2 creates the report and single-leaf finalized config only after commit `C` is frozen.

### Task 2.2: GEARS pseudobulk-approximation bias report

**Files:** Commit producer code/spec and the bias-null basis config; then generate report/final config only under
the external approved-artifacts stage.

**Steps:**
- [ ] **Pre-register the bias metric first** (decision #4): fix what is measured (the `raw_pseudobulk_approximation` vs per-cell discrepancy), on which **non-sealed** roles, and its direction/aggregation — BEFORE running it, so the report SHA that binds the final `config_sha256` is not outcome-shaped (it is an activation requirement, not a tunable).
- [ ] Author a script that quantifies, on **non-sealed** roles only, the pre-registered bias for GEARS; emit a canonical-JSON report with the bias metric + provenance.
- [ ] Complete local/pod tests and review, then commit every execution source, contract, dependency lock and the
  bias-null basis config. Record this clean full SHA as candidate `C`; detached-checkout `C` and require an empty
  tracked+untracked status. No repository mutation is permitted after this point.
- [ ] Set a fresh absolute external `APPROVED_ARTIFACTS_ROOT`, `ACTIVATION_EVIDENCE_STAGE`, and
  `FINAL_CONFIG_PATH` as defined by the sealed-run runbook §3.1. Prove all resolve outside the repository.
- [ ] Run the bias measurement on the pod with `git_commit=C`, writing directly to
  `$ACTIVATION_EVIDENCE_STAGE/real_norman_approximation_bias_report.json` (CPA stays null — exact representation).
- [ ] Run `finalize_approximation_bias_config.py` with the tracked bias-null config as input and
  `--out "$FINAL_CONFIG_PATH"`. It must prove exactly one changed leaf and the staged config's GEARS SHA must
  equal the report bytes.
- [ ] **Acceptance:** report `git_commit == C`; staged final config passes the normal config loader with no
  activation blocker attributable to the report; the tracked basis bytes and Git status are unchanged. Upload
  both to durable storage and read back their byte hashes. Do not commit either artifact.

### Task 2.3: regenerate the two evidence reports under the finalized config

**Files:** GENERATE the two reports under `$ACTIVATION_EVIDENCE_STAGE`; do not modify tracked snapshots.

**Steps:**
- [ ] `<pod py> scripts/compose_phi_rank_report.py --config "$FINAL_CONFIG_PATH" --h5ad <norman.h5ad> --sequences <seqs.json> --out "$ACTIVATION_EVIDENCE_STAGE/real_norman_phi_rank_report.json" --git-sha "$APPROVED_GIT_SHA"` — verify the embedded `config_sha256` equals the staged final digest and `activation == READY`.
- [ ] `<pod py> scripts/compose_detectable_effect_report.py --config "$FINAL_CONFIG_PATH" --phase1-config configs/compose_k562_v1_phase1.yaml --h5ad <norman> --sequences <seqs> --out "$ACTIVATION_EVIDENCE_STAGE/real_norman_detectable_effect_report.json" --git-sha "$APPROVED_GIT_SHA"` — same config/code binding check.
- [ ] Copy the four static runbook §4 requirement sources byte-identically from clean detached `C` into the
  fresh stage. Hash all six files, publish the complete stage to an immutable object version, and read it back.
- [ ] **Acceptance:** both reports embed `C` and the staged final `config_sha256`; the six-file roster has exact
  non-empty byte hashes; repository status remains empty; no report/final-config/README commit is created.

---

## Phase 3 — §2.5 release gate + external owner authorization

### Task 3.1: full-suite + locked-env integration + independent review

- [ ] Run the approved full test suite on the pod main env (green) + each worker's locked-env integration test (Task 1.4) green.
- [ ] Assemble the complete checksum manifest: fit-role artifact, both workers, worker configs, GO resource, both env locks, dependency lock, regenerated evidence — all SHA-recorded.
- [ ] Independent reviewer confirms (runbook §2.5): leakage (workers touch no sealed outcome), exact `{singles, combo_calibration}` roster, response projection fidelity, pair alignment, single-seal-open path intact, final-ledger recovery — on the pod state.

### Task 3.2: owner Git-SHA approval → freeze external ResolvedRunSpec

**Files:** CREATE the canonical ResolvedRunSpec under the external approved-artifacts root; its
`scientific.activation_evidence` block is the owner activation registration. Modify no repository file.

- [ ] Owner approves exact `C`, staged final-config SHA, six-file evidence roster, approximation-bias report SHA,
  immutable object version, worker/image pins and release review receipts.
- [ ] Publish the canonical ResolvedRunSpec with owner identity and the exact six-path/hash activation block.
  Independently rehash the spec and every referenced byte from the immutable snapshot; record storage object
  versions in the separate PREPARE publication manifest.
- [ ] Reconfirm repository HEAD is `C` and status is empty. Any post-`C` commit, stage mutation or object-version
  change invalidates approval and requires a fresh candidate/registration.
- [ ] **Handoff:** a SEPARATE sealed-run pod session executes the runbook (`phase2a → preflight → phase2b --confirm-seal`) and opens the COMPOSE seal exactly once. That is out of scope for this plan.

---

## Definition of Done

- Real `gears_worker.py` + `cpa_worker.py` committed, each passing the local contract test + the pod outcome-free Norman smoke in its locked env, and integrating through the merged controller with `_verify_execution_manifest` accepting the manifest.
- GO resource manifest + dependency lock committed, with the dependency lock validator
  returning `COMPLETE` (zero-overlap run evidence + wheelhouse manifest + image digest).
- The tracked basis config at `C` has established `power_status`/`environment_status`/`revision` and a null GEARS
  bias-report leaf; the staged final config changes only that leaf, has no activation blocker, and its canonical
  SHA is recorded in the owner-approved ResolvedRunSpec/publication manifest.
- Both analytical reports are generated outside Git so every `ActivationRecord` requirement (runbook §4, 6 files)
  carries a non-empty staged byte hash bound to `C` and the staged final config; no historical
  `d8c65ac4…`/`activation=BLOCKED` snapshot is used at runtime.
- Full suite + locked-env integration green; independent review passed; owner-approved exact `C`; immutable
  external ResolvedRunSpec and publication manifest reverified; repository still clean at `C`.
- **No seal opened.** The sealed run is a separate pod session.

## Self-Review notes (author)

- **Runbook coverage:** §2.2 (Tasks 0.1–0.2, 1.2–1.4), §2.1 fit-role already merged (used by Task 1.x), §2.3 driver merged, §2.4 ledger merged, §4 evidence lineage (Tasks 2.1–2.3), §2.5 release gate (Tasks 3.1–3.2). B spec §7 open questions surfaced as the pre-Phase-1 decisions.
- **Ordering landmine encoded:** commit `C` → external bias report → single-leaf external final config → external
  analytical evidence → external owner-approved ResolvedRunSpec. This binds the final config without moving HEAD or creating
  a report/config/Git fixed point.
- **Contract fidelity:** workers reuse the frozen `read_payload`/`write_predictions`/`validate_fit_role_artifact`/`apply_response_projection` seam and the 14-key `_REQUIRED_KEYS` payload; the stub is the scaffold template; only the fit body is pod-authored.
- **Local vs pod split honored:** only the contract test (Task 1.1) + config-schema edits are locally checkable; every real fit + evidence regen is pod-verified, per B spec §1.5/§7 and `CLAUDE.md` #compute.
- **Not a scientific run:** opens no seal; establishes activation lineage only; the single seal opens later on a separate sealed-run pod after owner SHA approval.
