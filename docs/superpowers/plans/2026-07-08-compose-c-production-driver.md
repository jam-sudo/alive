# COMPOSE sub-project C — production driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the single committed COMPOSE production driver `scripts/run_compose_k562_phase2.py` (`phase2a`/`preflight`/`phase2b --confirm-seal`/`recover`) driven by an immutable ResolvedRunSpec, orchestrating the existing (post-C0) library entry points into three independent processes + recovery, without ever re-implementing science or opening a seal outside the one sanctioned phase2b construction point.

**Architecture:** Thin verify-and-assemble. A thin CLI script delegates to a new importable package `src/alive/compose/driver/`. Each subcommand: (1) validate ResolvedRunSpec canonical bytes/schema/self-checksum/file-SHA; (2) read only its allowed pre-built artifacts, stream-hashing bytes vs declared digests; (3) assemble only the in-memory objects it needs (phase2a→non-sealed dev store; preflight→no store; phase2b→the sole sealed store); (4) validate the exact run-dir basename roster (§7.1), call the library entry point, persist run-produced artifacts write-once and re-read them. Canonical execution order is **phase2a → preflight → phase2b** (preflight consumes phase2a's frozen bundle; phase2b internally re-runs preflight then opens the seal). `recover` consumes only immutable run_dir artifacts.

**Tech Stack:** Python 3.12, existing `alive.compose.*` library (post-C0), `argparse`, `subprocess` (cross-process e2e), pytest, ruff. No new third-party deps.

## Global Constraints

Every task's requirements implicitly include these (copied from the C spec 2026-07-07-compose-production-driver-design.md and CLAUDE.md):

- **Single sealed-store construction point (§4).** `ComposeOutcomeStore` / `build_fixture_outcome_store` is imported and constructed in EXACTLY ONE phase2b-only driver function. `phase2a`/`preflight`/`recover` code paths MUST NOT import or reach it. A structural test asserts this.
- **⚑ audit_path contract (spec §3.3/§3.4/§11, whole-branch review).** The phase2b scientific store MUST be constructed with `audit_path = <run_dir>/audit.jsonl` (the `SEAL_AUDIT_FILENAME` convention, matching TG `cli.py:167,288`), because `recover` independently reconstructs `<run_dir>/audit.jsonl`. Any other audit path leaves a consumed seal fail-closed unrecoverable. An e2e negative pins this.
- **No seal opened outside phase2b.** No task opens/reopens a real seal. `recover`'s ABORTED synthesis uses the sanctioned `Phase2bTerminal.recover_aborted_after_seal` (added in C0) — ABORTED-only, seal never opened.
- **run_id is NOT RunSpec-derived.** `run_id = compute_compose_run_id(config_digest, data_card_digest, raw_or_source_digest, sequence_mapping_digest)` (datacard.py). `mode: fixture|scientific` is a dispatch selector, NOT a seal gate and NOT part of run identity. `execution_id = sha256_json({run_id, resolved_run_spec_file_sha256, approved_git_sha})` is computed at runtime and NOT stored inside the ResolvedRunSpec (avoids file-SHA self-reference).
- **Cross-process ledger handoff.** phase2a persists the fully-populated post-fit `RunLedger` canonical bytes via `atomic_write_once` as `phase2a_run_ledger.json` (installed LAST, after the 4 driver-added artifact SHAs: `resolved_run_spec` file SHA, runtime `execution_id`, pair-index file SHA, phase2a seed-report file SHA). preflight/phase2b re-read it via `RunLedger.read`. Reconstructing the ledger from the frozen bundle is FORBIDDEN (it would make preflight's ledger↔bundle checksum check a tautology).
- **Canonical JSON everywhere:** `sort_keys=True, separators=(",",":")`; self_checksum = `sha256_json(payload excluding self_checksum)`; file bytes SHA computed separately. Reuse `alive.io.atomic_write_once`, `alive.compose.durable._canonical_bytes`, `sha256_json`, `sha256_file`.
- **Fixture/scientific are structural, not conventional (§4).** Fixture path accepts ONLY `FixtureOutcomeStore`/`build_fixture_outcome_store` with an allowlisted corpus attestation; scientific spec rejects any fixture block/type/source-digest and vice versa. `mode` string, a mutable marker, or "host has no real data" are NOT security boundaries.
- **pre-seal capability restriction (§2.2/§4).** `phase2a`/`preflight` raw-asset access is a digest-only sequential byte-hash (`sha256_file` equivalent) — NO AnnData/backed parser, NO obs/X/layer materialization, NO outcome-store capability. Semantic pair-index↔obs row validation (C0's `validate_pair_index_against_source_obs`) runs ONLY in phase2b step 4, after confirmation.
- **Exit codes:** `0` step success; `10` pre-seal validation reject (seal unconsumed); `20` FUTILITY_STOPPED (normal, phase2b forbidden); `30` post-seal INVALID/ABORTED or durable export incomplete. stderr records exception class + stage; NEVER outcome arrays / cell values / per-pair errors on stdout/stderr.
- **Path policy (§2.2).** Scientific `--approved-artifacts-root` is required; the ResolvedRunSpec root MUST equal its canonical realpath; every path + run_dir is a normalized regular file/dir under that root; reject symlink/device/FIFO/`..`/root-escape. Fixture root is a test tmp dir.
- **Write-once & idempotence (§7.1).** All installs are `atomic_write_once`. A normal subcommand refuses to re-run even if intended bytes already exist. Byte-identical idempotence is allowed ONLY on the explicit `recover` path.
- **DRY/YAGNI/TDD, frequent commits.** Commit ONLY the named files per task (never `-A`/`.`). Reuse existing library APIs — do not re-implement freeze/scoring/ledger/terminal logic in the driver.

---

## File Structure

- `scripts/run_compose_k562_phase2.py` — thin CLI: `main(argv) -> int`, argparse with 4 subcommands, dispatch into `alive.compose.driver`, map exceptions → exit codes. No business logic.
- `src/alive/compose/driver/__init__.py` — package exports.
- `src/alive/compose/driver/run_spec.py` — `RunSpecTemplate` constants + `ResolvedRunSpec` v1 dataclass + `load_resolved_run_spec(path, *, approved_artifacts_root, mode_expected) -> ResolvedRunSpec` (canonical/schema/self-checksum/file-SHA, mode-forbidden-block, path policy, expected_hashes 7-key, digest verify, run_id recompute) + `compute_execution_id(...)`.
- `src/alive/compose/driver/run_dir_state.py` — `assert_run_dir_roster(run_dir, subcommand, *, phase)` per §7.1 required/allowed/forbidden basename rosters.
- `src/alive/compose/driver/identity_lock.py` — `assemble_execution_identity_lock(worker_block, *, fixture) -> ExecutionIdentityLock` (6 fields from real file digests) + `assemble_baseline_adapters(run_spec, ...) -> dict[str, BaselineAdapter]`.
- `src/alive/compose/driver/confirmation.py` — `build_seal_confirmation_manifest(...)` + `verify_seal_confirmation_manifest(path, token, ...)` (v1 schema, self-checksum, reconstruction byte-equality).
- `src/alive/compose/driver/phase2a_cmd.py` / `preflight_cmd.py` / `phase2b_cmd.py` / `recover_cmd.py` — the four orchestrations.
- `src/alive/compose/driver/fixture_builder.py` — committed `build_compose_fixture(tmp_root) -> FixtureBundle` (synthetic stage-1 DATA + fixture ResolvedRunSpec; NO store objects).
- Tests under `tests/alive/compose/driver/` — unit per module + `test_mini_e2e.py` (cross-process subprocess).

---

## Task 1: ResolvedRunSpec v2 schema + fail-closed loader

**Files:**
- Create: `src/alive/compose/driver/__init__.py`, `src/alive/compose/driver/run_spec.py`
- Test: `tests/alive/compose/driver/__init__.py`, `tests/alive/compose/driver/test_run_spec.py`

**Interfaces:**
- Consumes: `alive.compose.datacard.compute_compose_run_id(config_digest, data_card_digest, raw_or_source_digest, sequence_mapping_digest) -> str`; `alive.io.sha256_file`; `sha256_json`; `alive.compose.durable._canonical_bytes` (or `json.dumps(sort_keys, separators)`).
- Produces:
  - `RESOLVED_RUN_SPEC_SCHEMA = "compose_resolved_run_spec_v2"`.
  - `RUN_PRODUCED_BASENAMES` constant dict pinning the exact values (`frozen_bundle="frozen_prediction_bundle.json"`, `oof_manifest="oof_fold_manifest.json"`, `phase2a_seed_variability_report="phase2a_development_seed_variability.json"`, `run_ledger="phase2a_run_ledger.json"`, `futility_report="phase2a_futility.json"`, `seal_confirmation_manifest="seal_confirmation_manifest.json"`).
  - `EXPECTED_HASHES_KEYS = frozenset({...7 keys...})` (`response_space_checksum, factor_checksum, manifest_checksum, environment_checksum, data_card_checksum, raw_data_checksum, sequence_mapping_checksum`).
  - `class ResolvedRunSpec` (frozen dataclass mirroring §2.2) with `.mode`, `.run_id`, `.run_dir`, `.approved_artifacts_root`, `.self_checksum`, digests, `expected_hashes`, per-method worker blocks, and the mode-specific `sealed_input`/activation/fixture blocks.
  - `load_resolved_run_spec(path, *, approved_artifacts_root, mode_expected) -> ResolvedRunSpec` — validates and returns; raises `RunSpecError` (new, subclass `ValueError`) on ANY violation before returning.
  - `compute_execution_id(run_id, resolved_run_spec_file_sha256, approved_git_sha) -> str = sha256_json({...})`.

**Landmines:** self_checksum excludes itself; file SHA is separate; `run_id` must RECOMPUTE via `compute_compose_run_id` and equal the declared value; the fixture block and scientific block are mutually exclusive (presence of the wrong one → reject); path policy rejects symlink/device/FIFO/`..`/root-escape and requires realpath == declared root.

- [ ] **Step 1: Write failing tests** — in `test_run_spec.py`: a helper `_write_spec(tmp_path, **overrides)` that emits a canonical-JSON fixture ResolvedRunSpec with a correct self_checksum. Tests: (a) happy fixture spec loads; (b) tampered self_checksum → `RunSpecError`; (c) unknown/missing/extra top-level key → raise; (d) scientific block present in a `mode:fixture` spec → raise; (e) `expected_hashes` missing/extra key → raise; (f) a declared digest not matching the on-disk file bytes → raise; (g) recomputed `run_id != declared` → raise; (h) a path containing `..` or a symlink under root → raise; (i) `approved_artifacts_root != realpath` → raise. Each asserts `pytest.raises(RunSpecError, match=...)`.
- [ ] **Step 2: Run tests, verify they fail** — `.venv/bin/python -m pytest tests/alive/compose/driver/test_run_spec.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement `run_spec.py`** — the dataclass + constants + loader with each fail-closed check in the order above; digest checks stream-hash real bytes via `sha256_file`. Provide `compute_execution_id`.
- [ ] **Step 4: Run tests → PASS**; ruff check + format on both files.
- [ ] **Step 5: Commit** `src/alive/compose/driver/__init__.py src/alive/compose/driver/run_spec.py tests/alive/compose/driver/__init__.py tests/alive/compose/driver/test_run_spec.py` — `feat(compose-driver): ResolvedRunSpec v2 schema + fail-closed loader`.

## Task 2: Pair-index manifest v1 pre-seal validation

**Files:**
- Modify: `src/alive/compose/driver/run_spec.py` (add `validate_pair_index_manifest_preseal(...)`) — OR a new `driver/pair_index.py` if run_spec.py grows unwieldy.
- Test: `tests/alive/compose/driver/test_pair_index_preseal.py`

**Interfaces:**
- Produces: `validate_pair_index_manifest_preseal(manifest: Mapping, *, attestation: Mapping) -> None` — verifies the v1 schema (source file SHA, obs row-identity SHA, perturbation column, control/combo token rules, per-canonical-pair row indices + row-ID digest, role, self-checksum) AND its binding to `approved_sealed_input_attestation` (source file SHA + row-identity SHA equal). Fails closed (`RunSpecError`). Does NOT open source (that is phase2b step 4 via C0's `validate_pair_index_against_source_obs`).

**Landmine:** pre-seal validation is schema + self-checksum + attestation-binding ONLY; NO source obs read here (capability restriction).

- [ ] **Step 1:** Failing tests — happy manifest binds; tampered self-checksum → raise; manifest source-SHA ≠ attestation source-SHA → raise; missing perturbation column / combo-token rule → raise.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement the pre-seal validator.
- [ ] **Step 4:** run → PASS; ruff.
- [ ] **Step 5:** Commit the named files — `feat(compose-driver): pair-index manifest v1 pre-seal validation`.

## Task 3: run-dir state machine (§7.1 basename rosters)

**Files:**
- Create: `src/alive/compose/driver/run_dir_state.py`
- Test: `tests/alive/compose/driver/test_run_dir_state.py`

**Interfaces:**
- Produces: `assert_run_dir_roster(run_dir, subcommand: str, *, phase2a_outcome: str | None = None) -> None` — checks direct-child basenames against the exact required/allowed/forbidden roster per §7.1:
  - `phase2a`: no run-produced artifact present initially; (CONTINUE) exactly the 4 artifacts; (FUTILITY) only `phase2a_futility.json`.
  - `preflight`: the 4 phase2a artifacts required; confirmation/terminal/audit/pre-access/durable forbidden; installs only `seal_confirmation_manifest.json`.
  - `phase2b`: the 4 + confirmation required; terminal/audit/pre-access/durable forbidden; `phase2b.lock` ephemeral allowed. (Audit destination absence/empty is checked separately.)
  - `recover`: only `phase2b.lock` ephemeral allowed; exactly-one-terminal OR (terminal=0 + one durable audit claim); a byte-identical partial durable subset allowed.
- Raises `RunDirStateError` (subclass `ValueError`).

**Landmine:** it checks DIRECT-CHILD basenames only; no blanket "run_dir empty" rule (phase-shared artifacts). Reuse the pinned basenames from `run_spec.RUN_PRODUCED_BASENAMES` + terminal/durable filename constants (`Phase2bTerminal.*_ARTIFACT`, `durable.*_FILENAME`, `SEAL_AUDIT_FILENAME`).

- [ ] **Step 1:** Failing tests — one per subcommand: correct roster passes; a forbidden file present (e.g. a terminal in the preflight run_dir) → raise; a missing required (e.g. no frozen bundle for preflight) → raise.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS + ruff.
- [ ] **Step 5:** Commit — `feat(compose-driver): run-dir basename state machine (spec §7.1)`.

## Task 4: ExecutionIdentityLock assembler + adapter assembly

**Files:**
- Create: `src/alive/compose/driver/identity_lock.py`
- Test: `tests/alive/compose/driver/test_identity_lock.py`

**Interfaces:**
- Consumes: `alive.compose.baseline_subprocess.SubprocessBaselineBackend`, `ExecutionIdentityLock`, `configure_payload`; `alive.compose.phase2a.build_subprocess_fit_payload`; `alive.compose.baselines_combo.BaselineAdapter`; committed config `baseline_representations`.
- Produces:
  - `assemble_execution_identity_lock(worker_block: Mapping, *, config_representation: str, fixture: bool) -> ExecutionIdentityLock` — the 6 fields from REAL file digests (driver stream-hashes `requirements_lock`, worker/adapter code, worker config, resource manifest bytes); `adapter_version` from the committed adapter manifest. Scientific: FAIL CLOSED (`RunSpecError`/`AssemblerError`) if `adapter_version` is absent (sub-project B has not shipped a versioned adapter manifest). Fixture: hash `scripts/baselines/stub_worker.py` + stub config/resource/lock bytes; declared value, actual digest, and worker self-report must all agree.
  - `assemble_baseline_adapters(run_spec, *, fixture) -> dict[str, BaselineAdapter]` for exactly `{gears, cpa}` via `build_subprocess_fit_payload(...)` → `backend.configure_payload(payload)` → `BaselineAdapter(...)`.

**Landmine:** ResolvedRunSpec declared values are EXPECTED, not ground truth — the lock is assembled from re-hashed real bytes; worker self-report divergence is fail-closed. `_validate_baseline_adapters(required=not fixture)`: fixture adapters optional but if supplied MUST be exactly `{gears,cpa}`.

- [ ] **Step 1:** Failing tests — happy fixture lock assembles from stub bytes (declared==actual); a declared worker digest ≠ actual stub bytes → raise; scientific block with no `adapter_version` → fail closed. Use a tmp stub worker + stub config/resource/lock files.
- [ ] **Step 2:** FAIL. **Step 3:** implement (verify the real `ExecutionIdentityLock` field names + `SubprocessBaselineBackend`/`configure_payload`/`build_subprocess_fit_payload` signatures by reading `baseline_subprocess.py`/`phase2a.py`). **Step 4:** PASS + ruff.
- [ ] **Step 5:** Commit — `feat(compose-driver): ExecutionIdentityLock assembler from real digests + adapter assembly`.

## Task 5: seal-confirmation manifest build + verify

**Files:**
- Create: `src/alive/compose/driver/confirmation.py`
- Test: `tests/alive/compose/driver/test_confirmation.py`

**Interfaces:**
- Produces:
  - `build_seal_confirmation_manifest(*, run_id, execution_id, resolved_run_spec_file_sha256, approved_git_sha, git_clean, config/data/manifest/... checksums, ledger_file_sha256, ...) -> dict` (exact schema `compose_seal_confirmation_manifest_v1`, self-checksummed) and its write-once install helper.
  - `verify_seal_confirmation_manifest(path, token: str, *, reconstruct_inputs) -> None` — reads the manifest, checks exact schema/self-checksum/file-SHA; requires `token == manifest["confirmation_checksum"]` FIRST (a run-id-only token is rejected); then reconstructs the manifest from current non-sealed files/environment + attested sealed-input identity and requires byte equality. Sealed source access count stays 0 through this. Raises `ConfirmationError`.

**Landmine:** the `--confirm-seal` token is the full `confirmation_checksum`, NOT the recomputable run_id. Reconstruction proves the manifest still binds the current pre-seal reality without opening the seal.

- [ ] **Step 1:** Failing tests — build→verify round-trips with the right token; a run-id-only token → raise; a tampered manifest self-checksum → raise; a changed non-sealed input (so reconstruction diverges) → raise.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS + ruff.
- [ ] **Step 5:** Commit — `feat(compose-driver): seal-confirmation manifest v1 build + token verify`.

## Task 6: fixture builder (committed synthetic stage-1 DATA + fixture ResolvedRunSpec)

**Files:**
- Create: `src/alive/compose/driver/fixture_builder.py`
- Test: `tests/alive/compose/driver/test_fixture_builder.py`

**Interfaces:**
- Produces: `build_compose_fixture(tmp_root: Path) -> FixtureBundle` — writes bounded synthetic DATA (a `Phase2aInputs` payload incl. OOF selection params, fit-role `.h5ad`, response artifact, pair manifest, pair-index manifest, non-sealed dev-store audit DATA with `source_kind='synthetic_fixture'`, sealed-outcome DATA = synthetic source + pair_index + manifest + `audit_path`) and a fixture ResolvedRunSpec pointing at them. Returns paths + the spec path + the fixed `run_id`. **Builds NO store objects** (phase2a builds the dev store, phase2b builds the sealed store).
- `FIXTURE_CORPUS` attestation must match the C0 `FIXTURE_CORPUS_V1` allowlist entry so `build_fixture_outcome_store` accepts it downstream.

**Landmine:** fixed `run_id` — pick the 3 non-config digests (data_card/raw/sequence) in ONE place; derive both `Phase2aInputs.run_id` (= `compute_compose_run_id(config_sha256, ...)`) and the fixture ResolvedRunSpec digests from those 4 values so phase2a's bound run_id == preflight/phase2b recompute. The fixture `audit_path` MUST be `<run_dir>/audit.jsonl`. payload stays within `_assert_fixture_payload` bounds.

- [ ] **Step 1:** Failing test — `build_compose_fixture(tmp)` produces a spec that `load_resolved_run_spec(..., mode_expected="fixture")` accepts, with all declared digests matching on-disk bytes and a recomputable run_id; no store object created.
- [ ] **Step 2:** FAIL. **Step 3:** implement (promote the existing per-test fixture assembly into this one committed function; read `_assert_fixture_payload`, `Phase2aInputs`, `FIXTURE_CORPUS_V1`). **Step 4:** PASS + ruff.
- [ ] **Step 5:** Commit — `feat(compose-driver): committed COMPOSE fixture builder`.

## Task 7: `phase2a` subcommand

**Files:**
- Create: `src/alive/compose/driver/phase2a_cmd.py`
- Test: `tests/alive/compose/driver/test_phase2a_cmd.py`

**Interfaces:**
- Consumes: `run_phase2a` / `run_phase2a_fixture` (phase2a.py:1230/1281), `FrozenPredictionBundle.write` (freeze.py), `development_seed_variability` (seed_variability.py), `DevelopmentOutcomeStore` (data/outcome_store.py), `RunLedger`, `atomic_write_once`, Task 1/2/3/4 helpers.
- Produces: `run_phase2a_subcommand(run_spec, *, approved_artifacts_root, run_dir) -> int` — assembles `Phase2aInputs` + non-sealed `DevelopmentOutcomeStore` + `{gears,cpa}` adapters (Task 4); dispatches fixture vs scientific (scientific adds `activation_record=`, `git_is_clean=`, `data_card_path=`, `raw_asset_path=`, `response_artifact=`; fixture relies on the inputs' embedded `response_space_checksum` — `run_phase2a_fixture` has no `response_artifact` arg); on CONTINUE persists frozen bundle + OOF manifest write-once, runs D2 `development_seed_variability` on the frozen OOF → writes `phase2a_development_seed_variability.json` (DISTINCT path, NOT the canonical name), records the 4 driver-added artifact SHAs into the in-memory ledger, and installs `phase2a_run_ledger.json` LAST; on FUTILITY_STOPPED writes only `phase2a_futility.json` (schema `compose_phase2a_futility_v1`) and returns 20. Returns 0 (CONTINUE) / 20 (FUTILITY). Constructs NO `ComposeOutcomeStore`.

**Landmines:** ledger installed LAST (so preflight sees all pre-seal artifacts bound); the seed report is the DISTINCT `phase2a_development_seed_variability.json` (canonical name is phase2b's `bind_development_seed_variability` write-once target — collision otherwise); fixture/scientific `response_artifact` asymmetry; run-dir roster asserted (Task 3) before the entry call.

- [ ] **Step 1:** Failing test — with `build_compose_fixture` (Task 6), `run_phase2a_subcommand(...)` on a fresh run_dir → returns 0 and installs exactly the 4 CONTINUE artifacts; the ledger (re-read via `RunLedger.read`) carries the 4 driver-added artifact SHAs; NO `ComposeOutcomeStore` constructed (spy). A futility-forcing fixture → returns 20 + only `phase2a_futility.json`.
- [ ] **Step 2:** FAIL. **Step 3:** implement (read the real `run_phase2a[_fixture]` signatures + `development_seed_variability` + `DevelopmentOutcomeStore`). **Step 4:** PASS + ruff.
- [ ] **Step 5:** Commit — `feat(compose-driver): phase2a subcommand orchestration`.

## Task 8: `preflight` subcommand

**Files:**
- Create: `src/alive/compose/driver/preflight_cmd.py`
- Test: `tests/alive/compose/driver/test_preflight_cmd.py`

**Interfaces:**
- Consumes: `FrozenPredictionBundle.load`, `RunLedger.read`, `run_preflight(bundle=, pair_manifest=, config=, data_card_digest=, raw_or_source_digest=, sequence_mapping_digest=, ledger=, expected_response_dim=) -> EvaluationLock` (preflight.py:289), Task 5 `build_seal_confirmation_manifest`, Task 3 roster.
- Produces: `run_preflight_subcommand(run_spec, *, approved_artifacts_root, run_dir) -> int` — asserts the preflight roster (4 phase2a artifacts required, confirmation/terminal/audit/pre-access/durable forbidden); loads the frozen bundle + re-reads the ledger (NO reconstruction); calls `run_preflight`; on success installs `seal_confirmation_manifest.json` write-once; returns 0 or 10 (reject). Constructs NO outcome store of any kind.

**Landmine:** ledger MUST come from `RunLedger.read` of phase2a's persisted file (reconstruction forbidden — it would make preflight's ledger↔bundle check a tautology). preflight builds NO store.

- [ ] **Step 1:** Failing test — after Task 7 phase2a, `run_preflight_subcommand(...)` → returns 0 + installs the confirmation manifest; deleting/tampering the persisted ledger → fail closed (10); a run_dir with a forbidden terminal present → roster raise.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS + ruff.
- [ ] **Step 5:** Commit — `feat(compose-driver): preflight subcommand orchestration`.

## Task 9: `phase2b` subcommand — the single sealed-store construction point

**Files:**
- Create: `src/alive/compose/driver/phase2b_cmd.py`
- Test: `tests/alive/compose/driver/test_phase2b_cmd.py`

**Interfaces:**
- Consumes: Task 5 `verify_seal_confirmation_manifest`, C0 `validate_pair_index_against_source_obs`, `build_fixture_outcome_store`/`ComposeOutcomeStore` (the SOLE construction site), `run_phase2b` / `run_phase2b_fixture` (phase2b.py:742/860), `durable` commit-marker re-read, Task 3 roster.
- Produces: `run_phase2b_subcommand(run_spec, *, approved_artifacts_root, run_dir, confirm_seal_token) -> int` following spec §3.3 steps 0-6: (0) acquire `run_dir/phase2b.lock` non-blocking OS exclusive lock; (1) scientific → re-verify clean-git + activation evidence; (2) reload frozen bundle + `RunLedger.read`, re-verify CONTINUE + checksums; (3) `verify_seal_confirmation_manifest(path, token=confirm_seal_token, ...)` (token == confirmation_checksum first, then reconstruction byte-equality) — access count still 0; (4) ONLY after confirmation: open source `O_NOFOLLOW` regular-file fd, compare `(device,inode,size,mtime_ns)` around hashing, verify expected digest, run `validate_pair_index_against_source_obs`, then **construct the sealed store in THIS function only** with **`audit_path = <run_dir>/audit.jsonl`** (fixture → `build_fixture_outcome_store` with allowlisted attestation; scientific → `ComposeOutcomeStore`); (5) call `run_phase2b[_fixture](run_dir=, outcome_store=, frozen_bundle=, pair_manifest=, response_artifact=, config=, ledger=, seed_variability_report_path=<phase2a distinct report>, ...)`; (6) independently re-read `phase2b_durable_commit.json`, re-verify all SHAs + marker self-checksum, then return 0. Returns 0 / 30 (INVALID/ABORTED or incomplete export). Default output: terminal state + durable artifact paths/checksums only — never aggregate/verdict/per-pair.

**Landmines:** this is the ONLY function that imports/constructs `ComposeOutcomeStore`/`build_fixture_outcome_store` (§4). ⚑ `audit_path = <run_dir>/audit.jsonl` (recover depends on it). Audit destination checked absent/empty + run-bound before store construction. Nothing scientific to stdout before the durable re-read.

- [ ] **Step 1:** Failing tests — full fixture path (Task 6→7→8→this) → returns 0, `COMPLETE` terminal + durable marker present, store constructed with `audit_path == run_dir/audit.jsonl`; omitting preflight (no confirmation manifest) → reject before store construction; a run-id-only token → reject; swapping two pairs' obs rows → `validate_pair_index_against_source_obs` rejects before store construction.
- [ ] **Step 2:** FAIL. **Step 3:** implement (read the real `run_phase2b[_fixture]` signatures). **Step 4:** PASS + ruff.
- [ ] **Step 5:** Commit — `feat(compose-driver): phase2b subcommand — sole sealed-store construction point`.

## Task 10: `recover` subcommand

**Files:**
- Create: `src/alive/compose/driver/recover_cmd.py`
- Test: `tests/alive/compose/driver/test_recover_cmd.py`

**Interfaces:**
- Consumes: `recover_phase2b_durable_outputs(run_dir=)` (durable.py:1100, post-C0 — already handles both the 1-terminal resume and the 0-terminal+1-audit synthesis via `Phase2bTerminal.recover_aborted_after_seal`), Task 3 roster.
- Produces: `run_recover_subcommand(*, run_dir) -> int` — acquire `phase2b.lock`; assert the recover roster; call `recover_phase2b_durable_outputs(run_dir=run_dir)`; map result → exit 0 (recovered/verified) / 30 (ABORTED terminal published or fail-closed). Loads NO outcome source/pair-index/bundle/store; opens NO seal.

**Landmine:** the driver `recover` is a THIN wrapper over the C0 library `recover_phase2b_durable_outputs` — it does NOT re-implement synthesis. The audit it reconstructs is `<run_dir>/audit.jsonl` (bound by Task 9's construction contract).

- [ ] **Step 1:** Failing tests — after a full phase2b run, `run_recover_subcommand(run_dir=...)` → verify-only, exit 0, byte-identical (no rewrite); a synthesized `audit=1/terminal=0` run_dir (from Task 9's store audit + a suppressed terminal) → recover publishes an `ABORTED_AFTER_SEAL` terminal + marker; a run_dir with pre-access ledger but 0 audit records + 0 terminals → fail closed.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS + ruff.
- [ ] **Step 5:** Commit — `feat(compose-driver): recover subcommand (thin over durable recovery)`.

## Task 11: `main(argv)` CLI + exit-code mapping

**Files:**
- Create: `scripts/run_compose_k562_phase2.py`
- Modify: `src/alive/compose/driver/__init__.py` (export the 4 subcommand entry points)
- Test: `tests/alive/compose/driver/test_cli.py`

**Interfaces:**
- Produces: `main(argv: list[str] | None = None) -> int` — argparse with 4 subparsers (`phase2a`/`preflight`/`phase2b`/`recover`), the CLI flags from §1.1 (`--run-spec`, `--approved-artifacts-root`, `--confirm-seal`, `--run-dir`), loads the ResolvedRunSpec (Tasks 1) for the normal subcommands, dispatches, and maps driver exceptions → exit codes 0/10/20/30 (10 = pre-seal reject before seal; 20 = futility; 30 = post-seal/durable). stderr gets exception class + stage only. The `scripts/` file is thin: `import` + `sys.exit(main())`.

- [ ] **Step 1:** Failing tests — `main(["phase2a","--run-spec",spec,"--approved-artifacts-root",root])` returns 0 on the fixture; a pre-seal validation failure returns 10; a futility fixture via phase2a returns 20; unknown subcommand → argparse error. Assert NO outcome value on captured stdout.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS + ruff.
- [ ] **Step 5:** Commit `scripts/run_compose_k562_phase2.py src/alive/compose/driver/__init__.py tests/alive/compose/driver/test_cli.py` — `feat(compose-driver): main(argv) CLI + exit-code mapping`.

## Task 11.5: from-disk carrier loader (AMENDMENT 2026-07-08 — owner-authorized)

**Why (added after Task 11):** the four subcommands consume a fuller in-memory DATA carrier
(`FixtureBundle`), not a bare `ResolvedRunSpec`; the only committed carrier source
(`build_compose_fixture`) writes a write-once fit-role artifact and is callable once per
approved-root. So the spec §0/§1.1/§11 three-INDEPENDENT-process e2e (Task 13) is impossible until a
loader reconstructs the carrier from disk per process. Scoping verdict = **LOADER-ONLY**: every carrier
field is already serialized to disk by the fixture builder and declared in `PRE_SEAL_PATH_FIELDS`
(SHA-verified by `load_resolved_run_spec`); no fixture-builder serialization change, no
`PRE_SEAL_PATH_FIELDS` change, no subcommand change. `recover` takes no carrier (only `run_dir`) — 3
subcommands consume it (phase2a/preflight/phase2b).

**Files:**
- Create: `src/alive/compose/driver/carrier_loader.py`
- Test: `tests/alive/compose/driver/test_carrier_loader.py`
- Modify: `src/alive/compose/driver/cli.py` (`_build_run_spec_carrier` → call the loader, not `build_compose_fixture`) + `tests/alive/compose/driver/test_cli.py` (flip the `test_second_call_...` pin: a 2nd process now SUCCEEDS)
- (deserializer homes — implementer's choice, no new bytes written) may add `ResponseSpace.load`/`from_payload` in `compose/response.py`, `FitRoleArtifactSpec.from_payload_block` in `compose/fit_role.py`, a pair-index dict reconstructor in `driver/pair_index.py`, and a `Phase2aInputs` from-JSON reader (in the loader or beside `_serialize_phase2a_inputs`).

**Interfaces:**
- Produces: `load_run_spec_carrier(spec_path, *, approved_artifacts_root) -> Carrier` returning an object
  **duck-compatible with the attributes the subcommands read**: `.spec_path`, `.phase2a_inputs`
  (`Phase2aInputs`), `.dev_store_audit` (dict w/ `combo_calibration_eps`/`combo_calibration_pair_ids`/
  `access_audit:OutcomeAccessAudit`), `.response_artifact` (dict w/ `response_space:ResponseSpace`,
  `control_mean`, `combined_checksum`, `gene_order`, `raw_data_sha256`, `fit_role_spec:FitRoleArtifactSpec`),
  `.sealed_outcome` (dict w/ `manifest`, `pair_index:dict[(a,b)->np.ndarray]`, `source_path`,
  `source_file_sha256`, `perturbation_column`, `combo_sep`, `pair_index_manifest`, `corpus_id`,
  `source_sha256`, `builder_code_sha256`). Loads the ResolvedRunSpec via `load_resolved_run_spec`, then
  reconstructs each field from its declared pre-seal on-disk artifact.
- **Bucket A (thin `**dict`/JSON reads, data already exact on disk):** spec_path; dev_store_audit
  (`development_outcome_source.json` + `development_outcome_manifest.json`→`OutcomeAccessAudit(**dict)`);
  response_artifact scalars (`control_mean` via `np.asarray(list)`, `combined_checksum`, `gene_order`,
  `raw_data_sha256`); sealed_outcome dicts (`pair_manifest.json`, `pair_index_manifest.json`,
  `perturbation_column`, `combo_sep`); `source_path`/`source_file_sha256` from `spec.fixture["sealed_input"]`;
  `corpus_id`/`source_sha256`/`builder_code_sha256` from `FIXTURE_CORPUS_V1`.
- **Bucket B (NEW deserializers — data on disk, no reconstructor today):** (1) `phase2a_inputs.json` →
  `Phase2aInputs`, re-binding `model_roster` names → `_MODEL_CLASS_BY_NAME` factories; (2)
  response-space payload → live `alive.compose.response.ResponseSpace` (map payload→ctor, RECOMPUTE
  `checksum`); (3) `fit_role_artifact` block → `FitRoleArtifactSpec` (block→11 dataclass fields); (4)
  `pair_index_manifest.pairs[*]{gene_a,gene_b,row_indices}` → `dict[(gene_a,gene_b),np.array(row_indices)]`.
- **⚑ FIDELITY GATE (seal-critical):** the response-space payload is written through `_round_array`/
  `_round_float` (response.py). A rehydrated `ResponseSpace` is NOT guaranteed byte-identical to the
  built one. The loader MUST make the reconstructed `response_space_checksum` equal the value in
  `expected_hashes` / `Phase2aInputs.response_space_checksum` (checksum is over the rounded
  `artifact_bytes()`, so recompute from the reconstructed payload) — else the phase2a hash gate fails
  closed. Test this explicitly.

- [ ] **Step 1:** Failing test — `build_compose_fixture(root)` once, then `load_run_spec_carrier(spec_path, approved_artifacts_root=root)` returns a carrier whose consumed attributes deep-equal the built `FixtureBundle`'s (arrays `allclose`/`array_equal`; `response_space_checksum` EXACT-equal; `Phase2aInputs` factories callable). Then drive `run_phase2a_subcommand(loaded_carrier, ...)` on a fresh run_dir → same result as with the built carrier.
- [ ] **Step 2:** FAIL. **Step 3:** implement the loader + the 4 Bucket-B deserializers; rewire `cli.py::_build_run_spec_carrier` to build-corpus-once then load-per-call (peek mode BEFORE any disk write — fixes the Task-11 build-then-peek Minor); flip the `test_second_call_...` pin. **Step 4:** PASS + full `tests/alive/compose/driver/` green + ruff.
- [ ] **Step 5:** Commit — `feat(compose-driver): from-disk carrier loader (per-process stage-1 reconstruction)`.

## Task 12: seal-safety structural test

**Files:**
- Test: `tests/alive/compose/driver/test_seal_safety_structure.py`

**Interfaces:** no new production code — a structural assertion suite.

- [ ] **Step 1:** Write tests — assert (a) `ComposeOutcomeStore`/`build_fixture_outcome_store` is imported/constructed by EXACTLY the phase2b_cmd function (grep the driver package AST / import graph, or a runtime spy that fails if a store is constructed during `run_phase2a_subcommand`/`run_preflight_subcommand`/`run_recover_subcommand`); (b) during phase2a/preflight, raw-asset access is digest-only — spy asserts 0 AnnData/backed-parser/obs-materialization calls; (c) the phase2b store's `audit_path == run_dir/audit.jsonl`.
- [ ] **Step 2:** Run — some assertions may pass immediately (good); any that fail reveal a real leak → fix the offending subcommand (coordinate: report as a cross-task finding). **Step 3:** ensure green + ruff.
- [ ] **Step 4:** Commit — `test(compose-driver): structural seal-safety assertions`.

## Task 13: cross-process mini e2e

**Files:**
- Test: `tests/alive/compose/driver/test_mini_e2e.py`

**Interfaces:** drives the real CLI via `subprocess.run` three times (phase2a → preflight → phase2b) on a tmp root where `build_compose_fixture` produced the corpus ONCE up-front; each process reconstructs its carrier from disk via Task 11.5's `load_run_spec_carrier` (process memory is not shared → §4 seal isolation holds).

- [ ] **Step 1:** Write tests asserting the full §6 list: CONTINUE → frozen bundle + OOF + durable commit marker + COMPLETE terminal; futility → phase2b not run; **activation-less scientific spec → fail closed (count 0) before store construction**; stub `{gears,cpa}` adapters exercise the lock assembler; **upstream ledger round-trips (delete/tamper phase2a's ledger → preflight/phase2b fail closed)**; omitting preflight → phase2b rejects before store construction; changing bundle/ledger/worker identity after confirmation → token rejected; phase2a/preflight raw access is digest-only (0 materialization); attestation source SHA ≠ actual snapshot bytes → reject before store; real source digest/pair-index in fixture mode (or marker-only) → fixture factory rejects; **swapping two pairs' row blocks → obs alignment gate rejects**; wrong ledger run/config/environment header → reject regardless of artifact SHAs; **⚑ constructing the store with an audit_path ≠ `<run_dir>/audit.jsonl` → a subsequent `recover` of an audit=1/terminal=0 crash cannot find the audit and fails closed (unrecoverable)**.
- [ ] **Step 2:** Run — iterate until green (this is where cross-task integration bugs surface; fix the offending subcommand and re-run). **Step 3:** ruff.
- [ ] **Step 4:** Commit — `test(compose-driver): cross-process phase2a→preflight→phase2b mini e2e`.

## Task 14: doc reconciliation + DoD gate sweep (§10/§11)

**Files:**
- Modify: `docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md` (CLI, phase order, filenames, recovery, seal-boundary terms == this contract; 0 stale `<run_id>` confirmation text in executable CLI/instructions).
- Modify (owner-applied for CLAUDE.md if ARS-guarded — otherwise flag): any A/D spec term drift.
- Verify: full pytest, ruff check+format, and (LOCAL ONLY) the science-dev + spec-review loop gates.

- [ ] **Step 1:** Reconcile runbook terms to the driver contract; confirm the `--confirm-seal <confirmation_checksum>` token wording (no stale `<run_id>`).
- [ ] **Step 2:** Run the full compose suite + full repo suite + ruff; run the science-dev loop gate LOCAL ONLY (materialize harness → gate `--phase compose-c-driver` → record ledger to `loop-engineering-local` → remove harness; NEVER commit the harness; branch-safety grep empty before any commit).
- [ ] **Step 3:** Commit the runbook/doc changes (named files only) — `docs(compose): reconcile runbook + DoD with the C driver contract`.
- [ ] **Final:** whole-branch review (OPUS) → one consolidated fix wave → finishing-a-development-branch. DoD §11 gates 1-11 checked; note gate 6 (real GEARS/CPA lock) + gate 11 (owner approval of Git SHA + scientific ResolvedRunSpec SHA + confirmation-manifest schema) as pod/owner items, NOT local completion blockers.

---

## Self-Review notes (author)
- Spec coverage: §1 (Tasks 7-11,13), §2 (Tasks 1-2,6), §3.1-3.4 (Tasks 7-10), §4 (Tasks 9,12), §5 (Task 4), §6 (Tasks 6,13), §7.1 (Task 3), §10/§11 (Task 14). The ⚑ audit_path contract appears in Tasks 9 (construction), 10 (recover), 12 (structural), 13 (e2e negative).
- Out-of-scope preserved: PREPARE (raw Norman → stage-1) is NOT built — the fixture builder (Task 6) provides synthetic stage-1 DATA; pod PREPARE is a separate sub-project.
- Type consistency: `ResolvedRunSpec`, `RUN_PRODUCED_BASENAMES`, `EXPECTED_HASHES_KEYS`, `compute_execution_id` (Task 1) are consumed by Tasks 6-11; `assemble_*` (Task 4) by Task 7/9; `verify_seal_confirmation_manifest` (Task 5) by Task 9.
- Not a scientific run: every task is fixture/synthetic + unit/integration; opens no real seal; the single real seal opens only on the A100 via a scientific ResolvedRunSpec after owner approval (out of scope here).
