# COMPOSE GEARS pseudobulk-approximation bias metric — Design

> **Milestone:** `COMPOSE-K562-v1` (ACTIVE). Dev-pod PREPARE sub-task; settles B-spec §7 open
> decision #4 (`docs/superpowers/specs/2026-07-01-compose-deep-baselines-design.md` §7) and the
> dev-pod plan Phase-2 Task 2.2 (`docs/superpowers/plans/2026-07-09-compose-dev-pod-real-workers.md`).
> **Opens no seal.** Model-free measurement on observed non-sealed roles only.
> **Status:** implementation contract merged; real Norman measurement, config finalization, and release evidence
> remain pod-blocked. COMPOSE execution is RELEASE-BLOCKED and the seal is UNOPENED.
> **개정일:** 2026-07-14. Implementation contract synchronized with the shared validator and
> scientific pre-seal carrier.

---

## 0. Purpose & scope {#purpose}

The registered GEARS bridge **targets** a pseudobulk prediction — one population-level vector that
must be proven equivalent to a raw-count mean before it can enter the response operator — and is
declared as `prediction_representation = raw_pseudobulk_approximation`
(`configs/compose_k562_v1_phase2.yaml::baselines.gears`). This config label is a contract, **not yet
empirical proof of the native GEARS output scale**. Conforming Probe A in
`docs/superpowers/runbooks/2026-07-11-compose-gears-decision-probe-rerun.md` must first establish the
native scale, negative-output policy, and bridge equivalence within its preregistered tolerance. Its config field
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
- Not a new activation gate beyond "the report exists" **after Probe A and the output bridge pass**: once
  `approximation_bias_report_sha256` is non-null the activation blocker clears regardless of the bias
  magnitude (`config2.py` §6). The bias magnitude governs *interpretation of the sealed GEARS
  comparison* (§5), not activation.
- Not a claim about GEARS model accuracy. The floor measured here is the representation's irreducible
  contribution, present even for a perfect pseudobulk predictor.
- The measurement is **pod-only** (needs real Norman per-cell counts); only its unit tests run locally. It
  must not be promoted to activation evidence when Probe A fails or leaves the native output scale unresolved.

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
(`raw_pseudobulk_approximation`) carries this representation floor **conditional on Probe A validating
the raw-count-mean bridge**. If Probe A establishes a different native scale, this formula is inapplicable;
the bridge and this spec must be revised pre-seal rather than coercing that output into raw counts.

**Probe-A candidate correction (2026-07-19).** The frozen Probe-A owner policy tests
`log_normalized_pseudobulk`: GEARS receives full-library normalized/log1p input and its native regression output
is projected by HVG subset + centering + PCA with no second normalization and no signed-value clipping. A PASS
therefore does **not** validate the raw-count Jensen-floor formula below and does not admit this report by itself.
The committed GEARS scientific config remains activation-blocked until a separate pre-seal amendment either
adopts the candidate and revises this metric or supplies evidence for the existing raw representation.

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

- `δ_i`  ← `apply_response_projection(cells_raw, …, representation="cell_raw_counts")`
  once on the full cell matrix, then mean over rows, minus `control_mean`.
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

**Admission prerequisite (before measurement).** A conforming Probe A v3 admission, v2 verifier receipt, exact
owner-frozen registration bytes, and reviewed output-bridge
contract must establish that the GEARS population vector is a raw-count pseudobulk mean within an externally
frozen tolerance. The registration and receipt SHA-256 values are independently anchored outside the evidence
bundle. The admission binds the registration, exhaustive evidence manifest, and receipt; the receipt additionally
binds the report, externally pinned worker payload, externally pinned selected roster receipt, and verifier-code
closure. A tolerance declared only by the observed Probe-A report is not
preregistration. A quarantined, missing, failed, legacy, pin-mismatched, or cross-binding-inconsistent probe makes
this measurement `NOT_ADMISSIBLE`; no report SHA may be inserted into the active config.

**Inputs.**
- The authoritative fit-role artifact may contain the exact non-sealed roster
  `{control, singles, combo_calibration}`. `control` rows are accepted only as reference provenance;
  they are excluded before population grouping and never appear in either measured stratum. Any role
  outside that roster is rejected. The actually measured rows are restricted to
  `{singles, combo_calibration}`.
- The committed frozen `response_projection` block (the same one the fit-role artifact carries).
- The single-role δ_g values and calibration double truth δ_i (computed from observed cells) needed for
  the GI signal `ε_i = δ_i − (δ_g + δ_h)` on combo_calibration doubles.

**Seal safety (fail-closed).**
- Accept `control` rows in the authoritative artifact but prove they are reference-only: no control
  identifier may enter a measured stratum, the GI roster, or the measured-pair overlap computation.
  An unknown role or a `sealed_pair_ids` member in a measured stratum aborts (`ValueError`).
- Recompute and assert **zero overlap** between the measured pair roster and `sealed_pair_ids`, and
  record the overlap count (must be 0) in the report — mirroring the dev-pod plan's independent-overlap
  evidence.
- Verify the projection block's `gene_order_sha256` against the cells' gene order before projecting.
- No `ComposeOutcomeStore`, no `evaluate_sealed_once`, no sealed read.

**Point-estimate determinism.** Pure numpy over frozen arrays; no RNG in the point arithmetic. Row order is
canonicalized (sorted pair IDs) so the point report is byte-reproducible.

**Finite-sample uncertainty.** The observed cells, single-perturbation effects, and calibration pairs are
samples, so the fairness ratio is not treated as known without error. Each registered bootstrap replicate
(1) resamples combo-calibration pair IDs with replacement, (2) resamples cells within every sampled combo,
and (3) independently resamples cells within every single-gene population and recomputes every `δ_g` before
recomputing the additive null and `ε_i`. Holding point-estimate single effects fixed is forbidden because it
would omit uncertainty in the denominator. The config's registered seed roster and bootstrap replicate count
drive this procedure. The report includes a percentile 95% interval for `floor_median`,
`gi_signal_median`, and `R`. `fairness_flag` uses the point estimate; the interval is mandatory context,
not a second post-hoc decision rule. Degenerate replicates with zero GI denominator are recorded as
`NON_FINITE` and their count is reported; they are never silently dropped.

---

## 4. Report schema `compose_approximation_bias_report_v3` {#report}

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
- `bootstrap_95_interval`: intervals for `floor_median`, `gi_signal_median`, and
  `bias_to_signal_ratio_R`, plus `replicates_requested`, `replicates_finite`, and
  `replicates_non_finite`.
- `R_star`: `0.5` (the pre-registered threshold, embedded for auditability).
- `fairness_flag`: `"representation_confounded"` if the finite
  `bias_to_signal_ratio_R ≥ R_star`, `"clear"` if the finite ratio is below the threshold, and
  `"indeterminate"` if the point ratio is `"NON_FINITE"`. A non-finite ratio must never be mapped to
  `"clear"`.

**Provenance / integrity:**
- `measurement_contract_sha256` (this reviewed spec's file SHA), `basis_config_sha256`, `git_commit`,
  `norman_source_sha256`, `fit_role_artifact_sha256`,
  `response_projection_sha256`, `gene_order_sha256`, `pca_dim` (`p`), `registered_seeds`,
  `probe_a_evidence_sha256` (exact immutable Probe-A file bytes),
  `probe_a_evidence_manifest_sha256` (the independently reviewed manifest named inside Probe-A),
  `probe_a_registration_sha256` (exact owner-frozen registration bytes),
  `probe_a_verification_sha256` (exact independently anchored verifier-receipt bytes),
  `sealed_pair_overlap_count` (must be `0`), `pod_instance`.
- `self_checksum`: SHA-256 of the canonical JSON of every field above except `self_checksum`.

Every producer and consumer uses the same exact-schema validator. It requires exact top-level and nested
key rosters; unique byte-sorted pair IDs; exact equality between the combo-calibration and GI pair rosters;
non-negative squared-error/signal magnitudes; signed-PC vector dimension consistency; closed bootstrap
accounting; exact recomputation of every distribution, median, and ratio from the per-pair values;
flag/ratio coherence; zero sealed overlap; all content/provenance digests; and the canonical
`self_checksum`. Empty or wholly non-finite source rosters require `NON_FINITE` derived aggregates.
A merely non-empty flag, a freshly checksummed inconsistent aggregate, or a bare partial JSON object is
not admissible evidence.

Probe-A admission is not a CLI-only convention. The report producer requires immutable admission, registration,
and verification-receipt byte snapshots even for direct library calls. It revalidates their canonical bytes,
self-checksums, protocol, Git commit, representation, tolerance and verdict; checks every shared identity and
bridge value across all three objects; and binds all four Probe-A digests above. Admission self-checksum is
integrity only, not authentication. Both CLI and direct-library entry points therefore require the externally
anchored registration and verification SHA values as independent arguments and compare them to the exact byte
snapshots; reading either expected value back from the evidence bundle is forbidden.
There is no default
`"admitted"` argument that a direct caller can select.

`basis_config_sha256` is the canonical config whose
`baselines.gears.approximation_bias_report_sha256` is still `null`. The report **must not contain the
final config SHA**: the final config contains the report SHA, so recording that final SHA back inside the
report would create the impossible cycle `report → final config → report`. Finalization is one-way:

1. freeze and hash the bias-null basis config;
2. measure and self-checksum the report against that basis config + this contract;
3. hash the report and fill that SHA into a copy of the config, with **no other semantic change**;
4. hash the resulting final config and regenerate all activation evidence against it.

The finalization tool must mechanically prove that step 3 changed only
`baselines.gears.approximation_bias_report_sha256`; otherwise it fails closed and a fresh measurement lineage
is required.

The scientific `ResolvedRunSpec` additionally carries
`scientific.approximation_bias_report = {path, sha256}` (or `null` exactly while the config field is null).
Before runtime identity capture and again before any sealed-store construction, the carrier/driver require:
the declaration SHA equals the config-pinned SHA and the file bytes; the full report validates; the report's
`git_commit` equals `approved_git_sha`; the measurement-contract SHA equals this file; and
`basis_config_sha256` equals the independently reconstructed config obtained by changing only the final
report-SHA leaf back to null. The final driver read returns an immutable byte-bound snapshot rather than a
mutable path. `run_phase2b` revalidates and extracts the scalar fairness carry from that snapshot before
any store access, and the post-seal summary builder performs no report I/O. Any mismatch is a pre-seal
rejection and consumes no seal.

`p`, gene order and projection digests must equal the verified fit-role/response artifacts, binding the
report to the same evaluation space and run identity. The report's Norman-source SHA, fit-role file SHA,
and registered seed roster must likewise equal the scientific carrier inputs and final config.

---

## 5. Pre-registered fairness flag {#fairness}

The measurement is on `combo_calibration` doubles. Because sealed pairs are in the **same perturbation
regime** (double-unseen combos), `bias_to_signal_ratio_R` is the registered **pre-seal proxy** for the floor
that may apply to sealed GEARS δ. This is not an exchangeability proof: cell-count, expression-strength, and
pair-composition shift between calibration and sealed roles remain explicit limitations and are summarized
without reading sealed outcomes.

**Pre-registered rule (fixed now, pre-seal; no post-hoc change — §14).** A finite
`R ≥ R* = 0.5` ⇒ **`representation_confounded`**; a finite `R < R*` ⇒ **`clear`**;
`R = NON_FINITE` ⇒ **`indeterminate`**.

**What the flag does.** When confounded, a computational `GI_LEARNABLE_WIN` verdict that includes beating
GEARS may **not** be narrated as a *clean representation-matched GEARS win*. The registered exact method
roster, simultaneous family, margins, multiplicity correction, and verdict logic remain unchanged. The flag
adds a mandatory limitation to the scientific interpretation; it never deletes GEARS, demotes its margin, or
substitutes a post-hoc comparator.

**What the flag does NOT threaten.** The **primary** estimand `θ_{L1,additive}` (operator vs additive
null, margin 0.05) is measured entirely in exact response space and carries **no** pseudobulk floor.
The fairness flag therefore does not change the primary estimate; it constrains only the GEARS
family-comparator interpretation. `R* = 0.5` is a preregistered material-contamination heuristic, not a
hypothesis test or proof that a comparison is invalid.

The flag is **recorded pre-seal** in this spec and the report so it is genuinely pre-registered. The durable
summary integration carries the report SHA, flag, ratio, threshold, and registered interval without changing
the verdict. Scientific driver activation is nevertheless permitted only when the full report carrier and
one-way lineage checks above pass before the sealed store exists.

---

## 6. Known-answer tests (local, no pod) {#tests}

Per `CLAUDE.md`#data-eval/#verify (metric direction + toy known-answer). All run locally against synthetic cells and
a synthetic frozen projection block (no `gears`, no Norman):

1. **Degenerate (zero floor).** All cells identical ⇒ `mean_cells(z) = z(mean)` ⇒ `bias_i = 0` exactly.
2. **Analytic small case.** 2 cells with hand-chosen counts and a hand-computed `z` ⇒ the script's
   `bias_i`, `b_i` equal the by-hand values.
3. **Jensen direction.** For the concave `log1p` on a spread population, the population-mean projection
   over/under-shoots in the analytically-known direction ⇒ `signed_pc_bias` sign matches.
4. **Signal ratio + flag.** Construct floor and ε so `R` straddles `R*=0.5` ⇒ `fairness_flag` flips at
   the threshold (both branches tested); zero-denominator bootstrap replicates become counted
   `NON_FINITE`, never silently disappear.
5. **Seal-safety negatives.** Control rows in the authoritative artifact are accepted but excluded from
   every measured roster; an unknown role or a `sealed_pair_ids` member among measured inputs aborts; a
   nonzero sealed overlap aborts; a projection-block `gene_order_sha256` mismatch aborts.
6. **Self-checksum / determinism.** Re-running with the same registered seeds yields byte-identical JSON;
   tampering any field fails `self_checksum`.
7. **One-way provenance.** The report binds the bias-null `basis_config_sha256`; finalization changes only
   the GEARS report-SHA field and proves the final config SHA does not appear inside the report.
8. **Probe-A admission.** A bare `{status: pass}` is rejected. Admission requires the exact versioned v3 schema,
   protocol, approved Git commit, externally frozen registration SHA, exhaustive evidence-manifest SHA,
   independently anchored v1 verification-receipt SHA, raw-pseudobulk bridge representation, `verdict=pass`,
   finite non-negative tolerance/error with `max_abs_error ≤ tolerance`, and canonical self-checksums. Tests
   also forge a self-consistent admission with a changed tolerance and prove that the original receipt pin rejects
   it. Missing/failed/quarantined/tampered or cross-binding-inconsistent evidence refuses report promotion.

---

## 7. File structure & integration {#files}

- **MODIFY/REPLACE** the existing legacy
  `scripts/compose/measure_pseudobulk_approximation_bias.py` contract — it currently emits an earlier
  aggregate-only report and is **not** an implementation of this v1 schema. The upgraded pod measurement
  reads non-sealed role cells + frozen projection block, emits `compose_approximation_bias_report_v3`, and
  uses `cell_raw_counts` for the exact path. Pure library calls
  (`fit_role.apply_response_projection`); import-light so its contract is unit-tested locally.
- **CREATE** `docs/activation-evidence/compose/real_norman_approximation_bias_report.json` — the
  regenerated report (pod, under the finalized config); its SHA fills the config field.
- **MODIFY** `configs/compose_k562_v1_phase2.yaml::baselines.gears.approximation_bias_report_sha256`
  — null → the report SHA (part of dev-pod Task 2.2, BEFORE evidence regeneration per the plan's ⚑
  config-finalization-precedes-evidence ordering).
- **CREATE** `tests/alive/compose/test_approximation_bias_metric.py` — the §6 known-answer + seal-safety
  tests (LOCAL).
- **MODIFY** the durable summary/interpretation path to carry (not decide from) the registered
  `fairness_flag`, ratio, interval, and report SHA (§5). This integration is required before activation.
  The existing `config2.py` null→SHA rule remains the report-existence gate; it does not by itself prove
  the interpretation integration is complete.

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
