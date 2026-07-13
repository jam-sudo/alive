# COMPOSE GEARS pseudobulk-approximation bias metric — Design

> **Milestone:** `COMPOSE-K562-v1` (ACTIVE). Dev-pod PREPARE sub-task; settles B-spec §7 open
> decision #4 (`docs/superpowers/specs/2026-07-01-compose-deep-baselines-design.md` §7) and the
> dev-pod plan Phase-2 Task 2.2 (`docs/superpowers/plans/2026-07-09-compose-dev-pod-real-workers.md`).
> **Opens no seal.** Model-free measurement on observed non-sealed roles only.
> **개정일:** 2026-07-13.

---

## 0. Purpose & scope {#purpose}

The GEARS baseline emits a **pseudobulk** prediction — a single population mean in raw gene space —
carried by `prediction_representation = raw_pseudobulk_approximation`
(`configs/compose_k562_v1_phase2.yaml::baselines.gears`). Its config field
`approximation_bias_report_sha256` is `null`, which `config2.py::pseudobulk_representation_activation_blocked`
treats as an explicit activation blocker until the pseudobulk-approximation bias is **measured** and
its report SHA recorded.

This spec defines that measurement: a **model-free, seal-safe** quantification of the response-space
δ error that the pseudobulk representation induces *by construction* (independent of GEARS model
quality), plus a **pre-registered fairness rule** for how a large bias constrains the eventual sealed
GEARS comparison.

**In scope.** The bias definition (§2); the measurement procedure over non-sealed roles (§3); the
report schema (§4); the pre-registered fairness flag (§5); known-answer tests (§6).

**Out of scope / non-claims.**
- Not a bias *correction* of GEARS's predictions (§8). The report characterizes; it does not alter a
  baseline.
- Not a new activation gate beyond "the report exists": once
  `approximation_bias_report_sha256` is non-null the activation blocker clears regardless of the bias
  magnitude (`config2.py` §6). The bias magnitude governs *interpretation of the sealed GEARS
  comparison* (§5), not activation.
- Not a claim about GEARS model accuracy. The floor measured here is the representation's irreducible
  contribution, present even for a perfect pseudobulk predictor.
- The measurement is **pod-only** (needs real Norman per-cell counts); only its unit tests run locally.

**Governance.** This work opens no seal, constructs no `ComposeOutcomeStore`, calls no
`evaluate_sealed_once`, and never reads a sealed pair outcome or a `control`-as-training row. It hashes
only observed non-sealed cells and the committed frozen projection block. It preserves every §4.3
`CLAUDE.md` guard.

---

## 1. Authoritative definitions (inherited) {#defs}

From the operator spec (`docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md`) and
`fit_role.py`:

- **Response operator** `z(x)` (`fit_role.apply_response_projection`): frozen library-size normalize to
  `median_library` → `log1p` → HVG subset → center by `pca_mean` → project by `pca_components`. It is
  **nonlinear** (the `log1p` step). Output dimension `p` (PCA response space).
- **Truth δ** for a perturbed population is representation-invariant:
  `δ = mean_cells(z(x_raw)) − control_mean` (`fit_role.py:1082`).
- **Single effect** `δ_g`; **additive null** `δ_g + δ_h`; **GI component**
  `ε_gh = δ_gh − (δ_g + δ_h)` (operator spec §2.1, line 50–52). ε is the primary scientific target.
- **Per-pair evaluation error** (operator spec line 429–430):
  `e_{M,i} = p^{-1} ‖ δ̂_{M,i} − δ_i ‖₂²`.
- **Primary estimand** = paired relative error reduction of the operator vs the **additive null**,
  `θ_{L1,additive}`, with pre-registered **material margin 0.05** (operator spec line 432). GEARS and
  CPA are **comparator-family** members under simultaneous inference, not the primary comparator.

**Representation carried by each method.** The operator predicts δ **directly in response space** →
no representation floor. The additive null is `δ_g + δ_h` in response space → no floor. CPA
(`cell_raw_counts`) predicts per-cell → `z` applied per cell → no floor. **Only GEARS**
(`raw_pseudobulk_approximation`) carries a representation floor.

---

## 2. The bias — representation floor (model-free) {#bias}

For a perturbed population with observed raw cells `X = {x_raw}` the two response-space δ's are:

- exact (per-cell): `δ = mean_cells(z(x_raw)) − control_mean`
- pseudobulk approximation: `δ̃ = z(mean_cells(x_raw)) − control_mean`

Because `z` is nonlinear (`log1p` after per-cell library normalization), `z(mean(X)) ≠ mean(z(X))`
(a Jensen-type gap). The **representation-floor bias** for pair `i` is the response-space vector

```
bias_i = δ̃_i − δ_i = z(mean_cells(x_raw)) − mean_cells(z(x_raw))          # control_mean cancels
```

`control_mean` cancels exactly, so the bias is the **pure Jensen gap on the perturbed population**,
independent of the reference. It is present even if GEARS predicts the true population raw-mean
perfectly — hence "floor". It is measured directly on **observed** non-sealed cells (no model, no
GEARS run), reusing `fit_role.apply_response_projection`:

- `δ_i`  ← `apply_response_projection(cells_raw, …, representation="raw_pseudobulk_approximation")`
  per row, then mean over rows, minus `control_mean`.
- `δ̃_i` ← `apply_response_projection(mean_row, …, representation="raw_pseudobulk_approximation")` on the
  single population-mean row, minus `control_mean`.

Both use the **same committed frozen projection block** (identical `median_library`, `hvg_gene_ids`,
`pca_mean`, `pca_components`, `gene_order_sha256`) that the evaluation uses, so the floor is measured in
the exact space the sealed comparison will score in.

---

## 3. Measurement procedure {#procedure}

**Populations (stratified — §Q2 decision).**
- **Primary:** `combo_calibration` doubles — same regime as the sealed double-unseen pairs.
- **Secondary:** `singles` — broader characterization; also the roles from which the operator fits δ_g.
- Reported **separately**, never pooled (regime mixing would blur the floor).

**Inputs.**
- Observed raw per-cell counts for each non-sealed pair (from the Norman source synced in dev-pod plan
  Task 0.3), restricted to roles `∈ {singles, combo_calibration}`.
- The committed frozen `response_projection` block (the same one the fit-role artifact carries).
- The single-role δ_g values and calibration double truth δ_i (computed from observed cells) needed for
  the GI signal `ε_i = δ_i − (δ_g + δ_h)` on combo_calibration doubles.

**Seal safety (fail-closed).**
- Assert every pair's role is in `{singles, combo_calibration}`; a `control` or a `sealed_pair_ids`
  member as an input pair aborts (`ValueError`).
- Recompute and assert **zero overlap** between the measured pair roster and `sealed_pair_ids`, and
  record the overlap count (must be 0) in the report — mirroring the dev-pod plan's independent-overlap
  evidence.
- Verify the projection block's `gene_order_sha256` against the cells' gene order before projecting.
- No `ComposeOutcomeStore`, no `evaluate_sealed_once`, no sealed read.

**Determinism.** Pure numpy over frozen arrays; no RNG in the arithmetic. Seeds are recorded for
provenance only. Row order is canonicalized (sorted pair IDs) so the report is byte-reproducible.

---

## 4. Report schema `compose_approximation_bias_report_v1` {#report}

A single JSON object whose SHA-256 fills `baselines.gears.approximation_bias_report_sha256`.

**Per stratum** (`combo_calibration`, `singles`):
- `n_pairs`
- `per_pair`: sorted list of `{pair_id, b_i}` where `b_i = p^{-1} ‖bias_i‖₂²` (same units as `e_{M,i}`).
- `b_distribution`: `{median, mean, max, q90}` of `b_i`.
- `signed_pc_bias`: length-`p` vector = per-PC mean of `bias_i` (systematic direction; over/under).

**GI-signal & fairness (combo_calibration only):**
- `gi_signal_per_pair`: sorted list of `{pair_id, g_i}` where `g_i = p^{-1} ‖ε_i‖₂²`.
- `gi_signal_median`: `median_i(g_i)`.
- `floor_median`: `median_i(b_i)` over combo_calibration doubles.
- `bias_to_signal_ratio_R`: `floor_median / gi_signal_median` (**ratio of medians** — the pre-registered
  primitive; stable when some `g_i ≈ 0`, unlike per-pair ratios).
- `bias_to_signal_ratio_per_pair_median`: `median_i(b_i / g_i)` (secondary robustness view; not the
  flag primitive).
- `R_star`: `0.5` (the pre-registered threshold, embedded for auditability).
- `fairness_flag`: `"representation_confounded"` if `bias_to_signal_ratio_R ≥ R_star`, else `"clear"`.

**Provenance / integrity:**
- `config_sha256`, `git_commit`, `norman_source_sha256`, `fit_role_artifact_sha256`,
  `response_projection_sha256`, `gene_order_sha256`, `pca_dim` (`p`), `registered_seeds`,
  `sealed_pair_overlap_count` (must be `0`), `pod_instance`.
- `self_checksum`: SHA-256 of the canonical JSON of every field above except `self_checksum`.

`p`, gene order and projection digests must equal the fit-role artifact's, binding the report to the
same evaluation space and run identity.

---

## 5. Pre-registered fairness flag {#fairness}

The measurement is on `combo_calibration` doubles; because the sealed pairs are the **same regime**
(double-unseen combos), `bias_to_signal_ratio_R` is the honest **pre-seal proxy** for the floor that
would apply to the sealed GEARS δ.

**Pre-registered rule (fixed now, pre-seal; no post-hoc change — §14).**
`R ≥ R* = 0.5` ⇒ the sealed GEARS family-comparison is declared **`representation_confounded`**.

**What the flag does.** When confounded, a `GI_LEARNABLE_WIN` verdict that *relies on beating GEARS*
may **not** be reported as a *clean* GEARS win. To claim a GEARS win under a confounded flag the
sealed analysis must either (a) bias-correct GEARS's δ onto exact-representation footing (a separate,
separately-reviewed method), or (b) demote the GEARS margin and headline the operator's
primary (vs-additive) and CPA comparisons instead.

**What the flag does NOT threaten.** The **primary** estimand `θ_{L1,additive}` (operator vs additive
null, margin 0.05) is measured entirely in exact response space and carries **no** pseudobulk floor.
The fairness flag therefore never blocks or weakens the primary headline; it constrains only the
GEARS family-comparator interpretation. `R* = 0.5` means "a floor ≥ half the GI signal it must resolve
makes the GEARS comparison untrustworthy."

The flag is **recorded pre-seal** in this spec and the report so it is genuinely pre-registered; the
sealed-eval verdict machinery consumes the report's `fairness_flag` at verdict time.

---

## 6. Known-answer tests (local, no pod) {#tests}

Per `CLAUDE.md` §6 (metric direction + toy known-answer). All run locally against synthetic cells and
a synthetic frozen projection block (no `gears`, no Norman):

1. **Degenerate (zero floor).** All cells identical ⇒ `mean_cells(z) = z(mean)` ⇒ `bias_i = 0` exactly.
2. **Analytic small case.** 2 cells with hand-chosen counts and a hand-computed `z` ⇒ the script's
   `bias_i`, `b_i` equal the by-hand values.
3. **Jensen direction.** For the concave `log1p` on a spread population, the population-mean projection
   over/under-shoots in the analytically-known direction ⇒ `signed_pc_bias` sign matches.
4. **Signal ratio + flag.** Construct floor and ε so `R` straddles `R*=0.5` ⇒ `fairness_flag` flips at
   the threshold (both branches tested).
5. **Seal-safety negatives.** A `control` or `sealed_pair_ids` pair among inputs aborts; a nonzero
   sealed overlap aborts; a projection-block `gene_order_sha256` mismatch aborts.
6. **Self-checksum / determinism.** Re-running yields byte-identical JSON; tampering any field fails
   `self_checksum`.

---

## 7. File structure & integration {#files}

- **CREATE** `scripts/compose/measure_pseudobulk_approximation_bias.py` — the pod measurement script:
  reads non-sealed role cells + frozen projection block, emits `compose_approximation_bias_report_v1`.
  Pure library calls (`fit_role.apply_response_projection`); import-light so its contract is unit-tested
  locally.
- **CREATE** `docs/activation-evidence/compose/real_norman_approximation_bias_report.json` — the
  regenerated report (pod, under the finalized config); its SHA fills the config field.
- **MODIFY** `configs/compose_k562_v1_phase2.yaml::baselines.gears.approximation_bias_report_sha256`
  — null → the report SHA (part of dev-pod Task 2.2, BEFORE evidence regeneration per the plan's ⚑
  config-finalization-precedes-evidence ordering).
- **CREATE** `tests/alive/compose/test_approximation_bias_metric.py` — the §6 known-answer + seal-safety
  tests (LOCAL).
- Consumed by: the sealed-eval verdict path reads `fairness_flag` (§5). No change to `config2.py`
  validation is required — the existing null→SHA rule already gates on the field.

---

## 8. What this is NOT {#not}

- **Not a correction.** GEARS's pseudobulk output is its honest representation; we measure its floor,
  we do not silently subtract it. Any correction is a separate, separately-reviewed method invoked only
  under a confounded flag (§5).
- **Not model error.** The floor is present for a perfect pseudobulk predictor; it never claims
  anything about GEARS's learned accuracy.
- **Not a fresh activation gate.** Report existence clears the activation blocker; the magnitude only
  shapes the pre-registered GEARS interpretation.
- **Not local-runnable end-to-end.** Real cells are pod-only; only the known-answer tests run on the
  MacBook (`CLAUDE.md` #compute).
