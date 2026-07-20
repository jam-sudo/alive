# COMPOSE approximation-bias metric v1 — Implementation Plan

> **Status update (2026-07-19): local implementation + v3 hardening MERGED.** Real Norman
> measurement, config finalization, and release evidence remain pod-blocked. 아래 completed local task는
> current work queue가 아니다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Updated 2026-07-20 — Probe-A admission model superseded.** The single-`status` Probe-A admission gate described below was hardened into a THREE-ARTIFACT anti-forgery chain: an outcome-independent committed owner policy plus a run-specific `compose_gears_probe_a_registration_v2`, a verifier-code-bound `compose_gears_probe_a_verification_v2` receipt, and a `compose_gears_probe_a_admission_v3` admission that binds both by externally anchored SHA. Verification v2 additionally binds independently pinned worker-payload and selected-roster-receipt bytes. The registration-v2 scale is derived from the prepared manifest and the candidate is explicitly `log_normalized_pseudobulk`; it does not validate the raw Jensen-floor metric or activate the still-blocked scientific config. Where this plan differs from the authoritative spec and runbook, those govern.

**Goal:** Implement the LOCAL, seal-safe parts of the COMPOSE #4 approximation-bias design (`docs/superpowers/specs/2026-07-13-compose-approximation-bias-metric-design.md`): upgrade the measurement script to `compose_approximation_bias_report_v3`, add its known-answer/seal-safety tests, a one-way config finalization tool, the verdict-invariant durable fairness carry, and the committed Phase-1-entry gate-decision record.

**Architecture:** A pure-numpy, model-free measurement (`scripts/compose/measure_pseudobulk_approximation_bias.py`) reuses `fit_role.apply_response_projection` BYTE-UNCHANGED to compute the representation-floor bias on observed non-sealed `{singles, combo_calibration}` cells, emits a stratified v1 report with a pre-registered fairness flag, and a separate finalization tool binds the report SHA one-way into config. A phase2b build-time summary block carries the fairness values into the durable registered summary WITHOUT touching the verdict. Everything here opens no seal and runs on the MacBook against synthetic fixtures; the real measurement is pod-only and out of scope.

**Tech Stack:** Python 3.12 (`.venv`), numpy, anndata (`ad.read_h5ad`), pytest, ruff. Reuse `alive.compose.fit_role.apply_response_projection`, `alive.provenance.sha256_json`/`sha256_file`.

## Global Constraints

Every task's requirements implicitly include this section. Values are verbatim from the spec + the understand-phase seal-safety risk map.

- **Opens no seal.** No task constructs a `ComposeOutcomeStore`, calls `evaluate_sealed_once`, reads a sealed pair outcome, or imports `gears`/`cpa`. The authoritative artifact may include observed non-sealed `{control, singles, combo_calibration}` rows; `control` is accepted as reference-only provenance and excluded from every measured pair roster.
- **§4.3 guard files stay byte-untouched:** `src/alive/compose/outcome_store.py`, `gates.py`, `freeze.py`, `preflight.py`, `identity_lock.py`, and `io.atomic_write_once`. Do not weaken, bypass, or mock any guard.
- **`fit_role.apply_response_projection` is reused BYTE-UNCHANGED.** Do NOT fork or modify the projection math (`src/alive/compose/fit_role.py` is READ-ONLY). The exact per-cell truth path uses `representation="cell_raw_counts"`; the pseudobulk path uses `representation="raw_pseudobulk_approximation"` on the single population-mean row.
- **`config2.py` is touched READ-ONLY** (reuse `sha256_json`). The bias report MUST NOT be added to `config2._CONFIG_BOUND_EVIDENCE_REQUIREMENTS` — that would force `report.config_sha256 == final_config_sha256`, the forbidden report→final-config→report cycle.
- **One-way provenance:** the report binds `basis_config_sha256` (the bias-NULL config, hashed with the identical `alive.provenance.sha256_json`); the FINAL config SHA must not appear anywhere in the report JSON. Finalization fails closed on any config diff other than the single `baselines.gears.approximation_bias_report_sha256` leaf.
- **Anti-tautology (seal-safety negatives):** the standard builder `fit_role.extract_fit_roles` already excludes sealed rows and raises `FitRoleArtifactError('sealed pair present')`. A negative test that goes through it credits the BUILDER, not the METRIC. Seal-safety negative fixtures MUST bypass `extract_fit_roles` (hand-built roster/AnnData) and assert on the METRIC's OWN guard message.
- **Verdict invariance (LW7):** the fairness block lives in the registered-summary dict, NOT in `ComposeSealedResult`; `final_verdict_checksum` and every verdict axis/clause stay byte-unchanged. It is added at phase2b BUILD time (before `registered_summary_checksum` is computed), never in `durable.py` (durable stays copy-verbatim + re-verifies).
- **Non-finite honesty:** degenerate/zero-denominator results become the counted sentinel `"NON_FINITE"` (never silently dropped) and route through `_finite_or_sentinel` before the terminal canonicalizer (`terminal.py` rejects NaN/Inf).
- **POD-blocked, out of scope (do NOT attempt):** running the real measurement on Norman, Probe-A execution (running GEARS), filling the config with a REAL report SHA, regenerating activation evidence, the sealed run. Only the GATE LOGIC / carry CODE / schema is built + tested locally on synthetic fixtures.
- **Determinism:** the point estimate is RNG-free and byte-reproducible (sorted pair IDs). Only the bootstrap interval consumes `registered_seeds`.
- **Mechanics:** tests via `.venv/bin/python -m pytest`; ruff clean (`ruff check` + `ruff format`); commit only NAMED files (never `-A`/`.`); no data/checkpoint/credential commits. Commit trailers:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HPoPEh5tLhsjgavBgmcmXV
  ```

## File Structure

- `scripts/compose/measure_pseudobulk_approximation_bias.py` — MODIFY/REPLACE: legacy aggregate report → `compose_approximation_bias_report_v3` (Tasks 1–5).
- `scripts/compose/finalize_approximation_bias_config.py` — CREATE: one-way finalization tool (Task 6).
- `tests/alive/compose/test_approximation_bias_metric.py` — CREATE: §6 known-answer + seal-safety + provenance tests (Tasks 1–6).
- `tests/alive/compose/test_pseudobulk_approximation_bias.py` — RETIRE/REPLACE the legacy test whose key-set + control-in-roster assertions contradict v1 (Task 4).
- `src/alive/compose/phase2b.py` — MODIFY: `build_registered_evaluation_summary` gains an `approximation_bias_fairness` block + a fail-closed SHA-verified report loader (Task 7).
- `src/alive/compose/durable.py` — MODIFY: fail-closed presence/shape assertion for the new block; stays copy-verbatim (Task 7).
- `src/alive/compose/config2.py` — READ-ONLY reuse of `sha256_json`; assert bias requirement NOT in `_CONFIG_BOUND_EVIDENCE_REQUIREMENTS` (Tasks 6–7).
- `docs/superpowers/2026-07-13-compose-dev-pod-gate-decisions.md` — CREATE: committed gate-decision record (Task 8).

---

## The v3 report object (authoritative shape — referenced by Tasks 1–7)

`compose_approximation_bias_report_v3` is one canonical-JSON object (`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` + trailing `\n`). A stratum block appears for `combo_calibration` and `singles`; the GI/fairness/bootstrap blocks are `combo_calibration`-only.

```text
{
  "schema": "compose_approximation_bias_report_v3",
  "deliverable": "gears_pseudobulk_approximation_bias_report",
  "protocol": "COMPOSE-K562-v1",
  "seal_status": "unopened",
  "method": "raw_pseudobulk_approximation",
  "admission_status": "admitted",                         # only after immutable Probe-A validation
  "strata": {
    "combo_calibration": {                                # Task 1
      "n_pairs": int,
      "per_pair": [{"pair_id": str, "b_i": float}, ...],  # sorted by pair_id; b_i = p^-1 * ||bias_i||_2^2
      "b_distribution": {"median": f, "mean": f, "max": f, "q90": f},
      "signed_pc_bias": [f, ... length p]                 # per-PC mean of bias_i over the stratum
    },
    "singles": { ...same shape... }
  },
  "gi_and_fairness": {                                    # Task 1 (point) + Task 2 (interval), combo_calibration only
    "gi_signal_per_pair": [{"pair_id": str, "g_i": float}, ...],   # g_i = p^-1 * ||eps_i||_2^2
    "gi_signal_median": f,
    "floor_median": f,                                    # median_i(b_i) over combo_calibration
    "bias_to_signal_ratio_R": f,                          # floor_median / gi_signal_median (ratio of medians)
    "bias_to_signal_ratio_per_pair_median": f,            # median_i(b_i / g_i) — secondary
    "R_star": 0.5,
    "fairness_flag": "representation_confounded" | "clear" | "indeterminate",
    "bootstrap_95_interval": {                            # Task 2
      "floor_median": [lo, hi] | "NON_FINITE",
      "gi_signal_median": [lo, hi] | "NON_FINITE",
      "bias_to_signal_ratio_R": [lo, hi] | "NON_FINITE"
    },
    "replicates_requested": int,
    "replicates_finite": int,
    "replicates_non_finite": int
  },
  "provenance": {                                         # Task 4
    "measurement_contract_sha256": str,                   # sha256_file(the 2026-07-13 spec)
    "basis_config_sha256": str,                           # sha256_json(bias-NULL config); final SHA must NOT appear in report
    "git_commit": str,                                    # no "UNKNOWN" default for a binding v1
    "norman_source_sha256": str,
    "fit_role_artifact_sha256": str,
    "response_projection_sha256": str,
    "gene_order_sha256": str,
    "pca_dim": int,                                       # p
    "registered_seeds": [int, ...],
    "probe_a_evidence_sha256": str,                       # exact immutable Probe-A bytes
    "probe_a_evidence_manifest_sha256": str,              # manifest digest carried by Probe-A
    "sealed_pair_overlap_count": 0,
    "pod_instance": str
  },
  "self_checksum": str                                    # sha256 of canonical JSON of every field above except self_checksum
}
```

Any float that is NaN/Inf (or a zero-denominator ratio) is replaced by the string sentinel `"NON_FINITE"` via `_finite_or_sentinel` before serialization.

---

## Task 1: Metric point-estimate core (stratify + bias + GI + ratio + flag)

**Files:**
- Modify: `scripts/compose/measure_pseudobulk_approximation_bias.py`
- Test: `tests/alive/compose/test_approximation_bias_metric.py` (create)

**Interfaces:**
- Consumes: `fit_role.apply_response_projection(block, x, gene_order, *, representation)` (unchanged); a `block` = the frozen `response_projection` mapping (`median_library`, `hvg_gene_ids`, `pca_mean`, `pca_components`, `gene_order_sha256`, `control_mean`).
- Produces:
  - `_stratum_bias(rows_by_pair, block, gene_order) -> dict` returning `{n_pairs, per_pair:[{pair_id,b_i}], b_distribution, signed_pc_bias}` for a set of `{pair_id: raw_cell_matrix}`. `bias_i = apply_response_projection(mean_row, ..., "raw_pseudobulk_approximation")[0] - apply_response_projection(cells, ..., "cell_raw_counts").mean(axis=0)`; `b_i = float(np.mean(bias_i**2))` (= `p^-1||bias_i||_2^2`).
  - `_gi_and_fairness(combo_pairs, single_effects, block) -> dict` computing `eps_i`, `g_i`, medians, `bias_to_signal_ratio_R` (ratio of medians), `fairness_flag` with `R_STAR = 0.5`.
  - `_single_effects(singles_rows_by_gene, block) -> dict[str, np.ndarray]` mapping gene → `delta_g = mean_cells(z(cells_raw)) - control_mean` (using `"cell_raw_counts"`).

- [ ] **Step 1: Write failing tests** (`test_approximation_bias_metric.py`) — build a HAND-BUILT identity projection block helper `_identity_block(genes, median_library, control_mean)` (pca_mean=0, pca_components=I over HVG=all genes, so `z(x)=log1p(normalize(x))`), plus `_cells(...)` raw-count matrices.
  - `test_degenerate_identical_cells_zero_floor`: ≥2 IDENTICAL cells in a pair ⇒ every `b_i == 0.0` exactly (mean(z)=z(mean)). Not the trivial 1-cell case.
  - `test_analytic_two_cell_bias_matches_by_hand`: 2 cells, hand-compute `z(mean)` and `mean(z)` for the identity block, assert `per_pair[0]["b_i"]` equals the by-hand `mean((z(mean)-mean(z))**2)` within 1e-12.
  - `test_bias_to_signal_ratio_is_ratio_of_medians`: construct combos + singles with known `b_i` and `g_i` so `R = median(b_i)/median(g_i)`; assert the reported `R` equals that (NOT `median(b_i/g_i)`).
  - `test_fairness_flag_flips_at_R_star`: build one dataset with `R` just below 0.5 → `"clear"`, one just above → `"representation_confounded"` (from real floor+eps arithmetic; never monkeypatch R/g_i).
  - `test_control_is_not_a_measured_pair`: a roster containing `control` rows ⇒ control appears in NO stratum's `per_pair` (control is reference-only).
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/alive/compose/test_approximation_bias_metric.py -q` → FAIL (functions missing).
- [ ] **Step 3: Implement** the three helpers + stratification in the script. Drop `control` from the measured roster; split rows into `combo_calibration` and `singles` strata by `obs["role"]`; group by pair/gene id; reuse `apply_response_projection` for both paths; compute per-pair `b_i`, distribution (`np.median/mean/max` + `np.quantile(...,0.9)`), `signed_pc_bias = np.mean(np.stack(bias_vectors), axis=0).tolist()`. Decompose each `combo_calibration` pair id into its two constituent genes (`perturbation` split on the config combo separator `_`), form `eps_i = delta_i - (delta_g + delta_h)`, `g_i = float(np.mean(eps_i**2))`, medians, `R`. Keep DRY with the existing `_finite_or_sentinel`.
- [ ] **Step 4: Run** the tests → PASS.
- [ ] **Step 5: Commit**
```bash
git add scripts/compose/measure_pseudobulk_approximation_bias.py tests/alive/compose/test_approximation_bias_metric.py
git commit -F <msg>   # feat(compose): approximation-bias v1 point-estimate core (stratified bias/GI/ratio/flag)
```

---

## Task 2: Two-stage bootstrap + NON_FINITE accounting + determinism

**Files:**
- Modify: `scripts/compose/measure_pseudobulk_approximation_bias.py`
- Test: `tests/alive/compose/test_approximation_bias_metric.py`

**Interfaces:**
- Consumes: Task 1's per-pair `b_i`, `g_i`, `floor_median`, `gi_signal_median`, `R`; `registered_seeds` (list of int); a registered replicate count.
- Produces: `_bootstrap_intervals(combo_pairs, singles_rows_by_gene, block, *, seeds, replicates) -> dict` returning `{bootstrap_95_interval:{floor_median,gi_signal_median,bias_to_signal_ratio_R}, replicates_requested,replicates_finite,replicates_non_finite}`. Each replicate (a) resamples `combo_calibration` pairs with replacement, (b) resamples cells within each sampled combo, and (c) independently resamples every single-gene population and recomputes `delta_g`; holding single effects fixed is forbidden. Recompute the three statistics per replicate; a zero-GI-denominator replicate ⇒ `R` counted `replicates_non_finite` (never dropped). Interval = 2.5/97.5 percentiles over FINITE replicates, else `"NON_FINITE"`.

- [ ] **Step 1: Write failing tests**
  - `test_bootstrap_determinism_byte_identical`: two runs with the SAME `registered_seeds` yield byte-identical interval fields.
  - `test_zero_gi_denominator_counted_non_finite`: include a combo whose `eps_i ≈ 0` so some replicate's `gi_signal_median` denominator is ~0 ⇒ `replicates_non_finite >= 1` and `replicates_finite + replicates_non_finite == replicates_requested` (nothing silently dropped).
  - `test_point_estimate_is_rng_free`: `signed_pc_bias`/`per_pair` unchanged regardless of `registered_seeds`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the two-stage bootstrap using `np.random.default_rng(seed)` per seed in `registered_seeds`, aggregating replicate stats; route non-finite through the sentinel; keep the point estimate RNG-free. Pin the replicate count decision in the plan: **use a dedicated `--bootstrap-replicates` CLI arg (default 2000) recorded as `replicates_requested`; do NOT silently reuse `baselines.method.bootstrap_replicates`** (that is the eval bootstrap, a different estimand — document the choice in the script docstring).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `feat(compose): approximation-bias v1 two-stage bootstrap + NON_FINITE accounting`

---

## Task 3: Metric-owned seal-safety guards (role / overlap / gene-order aborts)

**Files:**
- Modify: `scripts/compose/measure_pseudobulk_approximation_bias.py`
- Test: `tests/alive/compose/test_approximation_bias_metric.py`

**Interfaces:**
- Produces: the v3 measurement entry `measure_approximation_bias_v3(*, fit_role_artifact, response_projection, sealed_pair_ids, probe_a_evidence, ...)` requires explicit `sealed_pair_ids: Sequence[str]` and immutable Probe-A evidence. Guards run BEFORE any projection: (a) artifact roles must be a subset of `{control, singles, combo_calibration}`, while only `{singles, combo_calibration}` enter measured rosters; (b) recompute `sealed_pair_overlap_count = len(measured_ids & set(sealed_pair_ids))`, assert `== 0` else `ValueError("approximation-bias: measured roster overlaps sealed_pair_ids")`; (c) assert `canonical_gene_order_sha256(gene_order) == block["gene_order_sha256"]` up front else `ValueError("approximation-bias: gene_order digest mismatch")`.

- [ ] **Step 1: Write failing tests** (ANTI-TAUTOLOGY — bypass `extract_fit_roles`; build the roster/AnnData by hand so the forbidden pair survives to the metric):
  - `test_control_is_reference_only`: a hand-built authoritative roster containing control rows succeeds, while control appears in neither stratum nor the GI roster; an unknown role still fails at the metric boundary.
  - `test_sealed_pair_member_aborts`: a measured id also in `sealed_pair_ids` ⇒ raises match=`"overlaps sealed_pair_ids"`; assert `sealed_pair_overlap_count` never reported > 0 (fail-closed before report).
  - `test_gene_order_mismatch_aborts`: block `gene_order_sha256` altered ⇒ raises match=`"gene_order digest mismatch"` up front (prove it fires before projection by using a block whose arrays would otherwise project fine).
  - `test_zero_overlap_recorded`: clean roster ⇒ `sealed_pair_overlap_count == 0` in the report.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the three guards at the top of the v1 entry; thread `sealed_pair_ids` through the CLI (`--sealed-pair-ids PATH` → JSON list). Verify guard-uniqueness by deleting each guard and confirming the matching test fails (record in the task report).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `feat(compose): approximation-bias v1 metric-owned seal-safety guards`

---

## Task 4: Report v3 assembly + provenance + self_checksum (retire legacy)

**Files:**
- Modify: `scripts/compose/measure_pseudobulk_approximation_bias.py`
- Delete/replace: `tests/alive/compose/test_pseudobulk_approximation_bias.py`
- Test: `tests/alive/compose/test_approximation_bias_metric.py`

**Interfaces:**
- Produces: `measure_approximation_bias_v3(...) -> dict` returns the FULL v3 object (see "The v3 report object"). `self_checksum = sha256(canonical_json(obj_without_self_checksum))`. Provenance fields per the schema; `git_commit` has no `"UNKNOWN"` default (raise if unresolved). `measurement_contract_sha256 = sha256_file(<2026-07-13 spec path>)`. `basis_config_sha256` is a caller-supplied arg (the bias-NULL config's `sha256_json`); the FINAL config SHA must never be embedded.

- [ ] **Step 1: Write failing tests**
  - `test_report_has_v2_schema_and_strata`: top-level `schema == "compose_approximation_bias_report_v3"`; both strata present; legacy keys (`directional_bias_l2`, `relative_magnitude_*`) ABSENT.
  - `test_self_checksum_detects_tampering`: mutate a covered field, recompute `self_checksum` over the MUTATED object, assert it differs from the stored value (mutate a covered field, not an excluded one).
  - `test_final_config_sha_absent_from_report`: given a `basis_config_sha256` and a distinct fabricated `final_sha`, assert `final_sha` does not appear anywhere in `json.dumps(report)`.
  - `test_canonical_json_byte_reproducible`: re-run with same inputs+seeds ⇒ byte-identical serialization.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the assembler + `self_checksum`; wire `main()` CLI (`--fit-role-artifact --response-projection --sealed-pair-ids --basis-config --norman-source-sha256 --git-commit --pod-instance --bootstrap-replicates --out`). **Retire** the legacy test file (its control-in-roster + legacy-key assertions contradict v1) — replace with a short note test or delete; do not leave a contradictory green test.
- [ ] **Step 4: Run** the new suite + `.venv/bin/python -m pytest tests/alive/compose -q` (no legacy contradiction) → PASS.
- [ ] **Step 5: Commit** — `feat(compose): approximation-bias v1 report assembly + provenance + self_checksum; retire legacy`

---

## Task 5: Probe-A admission gate (NOT_ADMISSIBLE)

**Files:**
- Modify: `scripts/compose/measure_pseudobulk_approximation_bias.py`
- Test: `tests/alive/compose/test_approximation_bias_metric.py`

**Interfaces:**
- Produces: `_probe_a_admission(evidence: Mapping) -> str` returning `"admitted"` when the Probe-A evidence `status == "pass"`, else raising `ValueError("approximation-bias: Probe-A <status>; measurement NOT_ADMISSIBLE")` for `status ∈ {"missing","failed","quarantined"}` (unknown status ⇒ treated as `"missing"`, fail-closed). Wired via `--probe-a-evidence PATH` (JSON with a `status` field). When admission fails, NO report is written (the script exits non-zero). The admission vocabulary matches `docs/superpowers/runbooks/2026-07-11-compose-gears-decision-probe-rerun.md`.

- [ ] **Step 1: Write failing tests** — a synthetic 4-state evidence fixture:
  - `test_probe_a_pass_admits`: `status="pass"` ⇒ report emitted, `admission_status == "admitted"`.
  - `test_probe_a_missing_failed_quarantined_refuse` (parametrized over the 3): raises match=`"NOT_ADMISSIBLE"`, no output file written.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the gate at the TOP of `main()` (before measurement); set `admission_status`. (Real Probe-A EXECUTION is pod-blocked; only the gate logic is built here.)
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `feat(compose): approximation-bias Probe-A admission gate`

---

## Task 6: LOCAL one-way finalization tool

**Files:**
- Create: `scripts/compose/finalize_approximation_bias_config.py`
- Test: `tests/alive/compose/test_approximation_bias_metric.py`
- Read-only: `src/alive/compose/config2.py`

**Interfaces:**
- Produces: `finalize_bias_config(*, basis_config_path, report_path) -> dict` that: (i) `basis_sha = sha256_json(yaml.safe_load(basis_config_path))`; (ii) assert `report["provenance"]["basis_config_sha256"] == basis_sha` AND basis `baselines.gears.approximation_bias_report_sha256 is None`; (iii) `final = deepcopy(basis)`; set ONLY `final["baselines"]["gears"]["approximation_bias_report_sha256"] = sha256(canonical_json(report))`; (iv) MECHANICALLY PROVE the single-leaf change: a recursive leaf-path diff of `basis` vs `final` yields EXACTLY `["baselines","gears","approximation_bias_report_sha256"]`, else `ValueError`; (v) assert `sha256_json(final)` (the FINAL config SHA) does not appear as a substring anywhere in `json.dumps(report)`. Uses the SAME `alive.provenance.sha256_json` as `config2.py:735`.

- [ ] **Step 1: Write failing tests**
  - `test_finalization_changes_only_the_one_leaf`: basis (bias=null) + matching report ⇒ `final` differs from basis at exactly the one leaf.
  - `test_finalization_fails_closed_on_extra_diff`: a report/basis pair where a second field would also change ⇒ `ValueError` (simulate by passing a basis whose non-bias field the tool would touch — assert the leaf-diff guard fires).
  - `test_basis_binding_mismatch_fails`: `report.basis_config_sha256 != sha256_json(basis)` ⇒ `ValueError`.
  - `test_final_sha_absent_from_report`: `sha256_json(final)` not a substring of the report JSON.
  - `test_bias_requirement_not_config_bound`: assert `"approximation_bias_report_sha256"`-style requirement is NOT in `config2._CONFIG_BOUND_EVIDENCE_REQUIREMENTS` (guards the no-cycle invariant).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the tool + a thin `main()` (`--basis-config --report --out`). config2.py is READ-ONLY (import `sha256_json`; read the frozenset for the assertion).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `feat(compose): one-way approximation-bias config finalization tool`

---

## Task 7: Durable fairness carry (phase2b build-time, verdict-invariant)

**Files:**
- Modify: `src/alive/compose/phase2b.py` (`build_registered_evaluation_summary` ~L709-755; call site ~L1603-1620)
- Modify: `src/alive/compose/durable.py` (fail-closed presence/shape assertion near the roster checks)
- Read-only: `src/alive/compose/config2.py`
- Test: `tests/alive/compose/test_phase2b.py`, `tests/alive/compose/test_durable.py`

**Interfaces:**
- Consumes: `config.baselines.gears.approximation_bias_report_sha256` (may be null pre-finalization) + an immutable report byte snapshot captured before sealed-store construction.
- Produces: an `approximation_bias_fairness` block `{report_sha256, fairness_flag, bias_to_signal_ratio_R, bootstrap_95_interval, R_star}` inside the dict returned by `build_registered_evaluation_summary`, populated from NEW kwargs at the call site. A NEW fail-closed pre-seal loader verifies the snapshot SHA and full v3 contract before extracting values (an unpinned report's values must not leak in); the post-seal summary builder performs no report I/O. Ratio/interval endpoints route through `_finite_or_sentinel` (mirror `gi_explained_interval`). When the config field is null (not yet finalized), the block records `{report_sha256: null, fairness_flag: "unavailable", ...}` — the CARRY exists but is honestly empty. Decide additive-under-`_v1` (no schema-version bump) since only an OPTIONAL block is added; if a bump is required, edit BOTH the `phase2b.py` literal and the `durable.py` constant identically.

- [ ] **Step 1: Write failing tests** (existing synthetic phase2b/durable harnesses; no seal, no store):
  - `test_fairness_block_sourced_from_pinned_report`: config SHA == report content SHA ⇒ block carries the report's flag/ratio/interval.
  - `test_fairness_block_fails_closed_on_sha_mismatch`: report content SHA != config SHA ⇒ loader raises; values never leak.
  - `test_final_verdict_checksum_byte_unchanged`: build a summary with vs without the block wiring ⇒ `final_verdict_checksum` and every verdict axis/clause byte-identical (the block lives in the summary dict only).
  - `test_durable_fails_closed_when_block_absent`: durable presence assertion raises if the summary lacks the block; durable NEVER populates/mutates it.
  - `test_durable_copy_verbatim_still_holds`: `sha256_json(summary) == registered_summary_checksum` end-to-end after the block is present.
  - `test_null_config_field_yields_unavailable_block`: null config field ⇒ `fairness_flag == "unavailable"`, no crash.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the loader + block at phase2b BUILD time (BEFORE `registered_summary_checksum`), the null-safe path, and the durable presence/shape assertion (durable stays copy-verbatim). Do NOT add the bias requirement to `_CONFIG_BOUND_EVIDENCE_REQUIREMENTS`.
- [ ] **Step 4: Run** the two test files + `.venv/bin/python -m pytest tests/alive/compose -q` → PASS.
- [ ] **Step 5: Commit** — `feat(compose): verdict-invariant durable carry of the approximation-bias fairness flag`

---

## Task 8: Committed gate-decision record (prose)

**Files:**
- Create: `docs/superpowers/2026-07-13-compose-dev-pod-gate-decisions.md`
- Read-only: dependency lock, requirements locks, the #4 spec, the dev-pod plan, the runbook.

**Interfaces:** none (prose doc). Settles B-spec §7 Phase-1-entry decisions with cited evidence.

- [ ] **Step 1: Draft** the record: **#1** GEARS `cell-gears==0.1.2` + era-consistent stack (cite `requirements.gears_env.lock`; pin durable revision by repo commit/tag or Task-0.1 wheel/sdist SHA since GEARS has no runtime `__version__`); **#2** GO v2 manifest RESOLVED (cite `go_resource_manifest.json` sha); **#3** `cpa-tools==0.8.5` (not 0.7.2 np.int-crash, not 0.8.8; cite `requirements.cpa_env.lock`); **#4** bias-quantification method = this session's spec (DEFINITION satisfied; report SHA is pod-generated + Probe-A-gated); **#5** RunPod A100 / torch cu124. Each decision: `PROPOSED` with an owner sign-off line to flip to `CONFIRMED`. Note config/lock encodings land later (Phase-2 Task 2.1/2.2 + Phase-0 Task 0.1). Cross-link the plan's Open-decisions gate + runbook §2.5.
- [ ] **Step 2: Verify reference integrity** — every cited file/line exists; cited revision strings match the committed locks; `git diff` confirms NO edit to `configs/compose_k562_v1_phase2.yaml` (must not mint the final config identity out of order).
- [ ] **Step 3: Commit** — `docs(compose): dev-pod Phase-1-entry gate-decision record (B-spec §7 #1–#5)`

---

## Self-Review notes (author)

- **Spec coverage:** §2 bias → Task 1; §3 procedure + seal-safety → Tasks 1/3; §4 report schema + one-way provenance → Tasks 4/6; §5 fairness flag + durable carry → Tasks 1/7; §6 known-answer tests 1–8 → Tasks 1–6; §7 files (script MODIFY, finalization, durable integration) → Tasks 4/6/7; Probe-A admission → Task 5. Dev-pod plan Open-decisions gate → Task 8.
- **POD boundary:** every task is LOCAL-testable on synthetic fixtures; the real Norman measurement, Probe-A execution, config finalization with a real SHA, evidence regen, and the sealed run are explicitly out of scope (Global Constraints).
- **Type consistency:** `b_i = p^-1||bias_i||_2^2` (mean of squares), `g_i = p^-1||eps_i||_2^2`, `R = median(b_i)/median(g_i)` (ratio of medians), `R_star = 0.5`, report `fairness_flag ∈ {representation_confounded, clear, indeterminate}`; durable null-config carry alone uses `unavailable`.
- **Anti-tautology** is a Global Constraint and is re-stated in Task 3 (bypass `extract_fit_roles`, assert the metric's own message, verify by guard deletion).
