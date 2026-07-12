# COMPOSE dev-pod — GEARS 0.1.2 decision probe (superseded as-run plan)

> **STATUS: SUPERSEDED / PARTIALLY EXECUTED / PROBE B NONCONFORMING. DO NOT RUN THIS PLAN.** The official
> one-time `ComposeOutcomeStore` evaluation gateway was not consumed, but the archived Probe B prep materialized
> the full source expression matrix before resolving its dev sealed/calibration roster and subset genes before
> the registered `U_full` normalization/response boundary. Its “opens no seal” assurance and 2k timing evidence
> are therefore invalid. The immutable as-run archive is quarantined at
> `evidence/2026-07-11-gears-decision-probe/`; the only authorized replacement is
> `runbooks/2026-07-11-compose-gears-decision-probe-rerun.md`. All commands and governance claims below are
> historical context, not current instructions.
>
> **Original intent (historical):** This plan defined two
> **decision-enabling** dev-pod measurements that convert the two owner-gated linchpins of
> `2026-07-10-compose-gears-scale-and-gene-universe-recommendations.md` from "premature" to "decidable":
> **Probe A** resolves the GEARS native-scale linchpin (Option 1 published-scale+bridge vs Option 2 named
> raw comparator); **Probe B** resolves `N_target` for the §2 gene universe. Neither reads a sealed outcome,
> neither finalizes config, neither regenerates activation evidence. Both run on a **development pod**
> (readiness-index step 4), never the sealed-run pod. The harness is authored on the MacBook and staged;
> only execution needs a live A100.

---

## 0. Why probe-first (sequencing)

Both measurements sit **upstream** of the builds they gate:

- The §2 gene-universe generator needs a frozen `N_target`; `N_target` is chosen *only* from Probe B's
  feasibility evidence (spec §3.5 forbids an outcome-selected universe; a resource-selected size is legitimate).
  Building the generator first would bake in an unvalidated size and force a rebuild.
- The GEARS-scale linchpin cannot be decided at all without Probe A: the entire Option 1 bridge rests on the
  "normalize-before-HVG + log-output + per-control-predict" premise that the recommendation doc itself marks
  "POD-VERIFY *first* — this makes or breaks the bridge." Choosing before measuring would violate that gate.

So the probes are the true decision-unblockers; the generator, the config-finalize, and the scientific
PREPARE carrier all sit downstream. This plan does **not** decide the linchpins — it produces the evidence the
owner decides from.

---

## 1. Probe A — GEARS 0.1.2 source + output-scale characterization (resolves the scale linchpin)

**Goal:** empirically establish, against the *installed* `cell-gears==0.1.2` wheel on the era stack, the four
facts the Option 1 bridge depends on. Source line numbers are explanatory; the recorded wheel SHA-256 + dumped
source symbols are the identity anchors.

| ID | Question | How measured |
|----|----------|--------------|
| **P1** | Does GEARS normalize each cell by its **full-gene** library size, and does that happen **before** any gene subsetting (same basis as COMPOSE `_normalize_log1p_full`, fit_role.py:1054)? Or does it normalize on the reduced matrix? | Dump `PertData.new_data_process` + the training-target construction source; inspect the processed `.X`/target scale after `new_data_process` on a known raw input (row sums, integer-ness, presence of `log1p`). |
| **P2** | Does `GEARS.predict` return values in **log space** (values ~0–8), linear-normalized (rows≈`T_gears`), or raw-count scale (large)? | Fit a tiny GEARS (small genes/cells/epochs), call `predict`, report min/median/max, row-sum distribution, fraction of near-integers, and whether `expm1` recovers a normalized-count scale. |
| **P3** | Does `predict` construct **one prediction row per control input** (`p` shape `(n_control, n_genes)`) before `np.mean(p, axis=0)`, and consume the **first ≤300-control batch**? | Dump `GEARS.predict` source; then instrument: predict with `n_control ∈ {1, 8, 300, 301, 400}` and confirm outputs stabilize at 300 (first-batch substrate) and that a per-control tensor exists pre-mean. |
| **P4** | What is `T_gears` (the target library size GEARS normalizes to)? Is it a global constant or per-cell? | Read it from the processed-data scale / source; confirm it is a single global constant (required for a well-defined bridge ratio `T_compose / T_gears`). |

**Decision rule (Probe A → linchpin).** Recommend **Option 1** *iff* **P1 ∧ P2 ∧ P3 ∧ (P4 = global constant)**
all hold AND the follow-on inference-equivalence check (recommendation doc §1, requirement 1) can be met — i.e.
the per-control substrate is reproducible and `mean_i(rows)` reproduces public `GEARS.predict`. If **P1 fails**
(normalizes on the reduced matrix → per-cell ratio not constant) **or P2 fails** (predict not log-space so the
`log1p(expm1(·)·ratio)` bridge is ill-posed), the bridge is undefined → **fall back to Option 2** (named
raw-count comparator + the already-built approximation-bias report). P3/P4 failing narrows Option 1 to the
full-control variant (a distinct method ID) rather than killing it. **Record the raw finding regardless of
which way it points** (§14 negative-results-are-results): a probe that sends us to Option 2 is a result.

**Output:** `probe_a_gears_scale.json` — wheel SHA-256, dumped source of `predict` / `new_data_process` /
`set_pert_genes`, the P1–P4 measurements, and the mechanical Option-1-vs-2 verdict from the rule above.

---

## 2. Probe B — 2k/5k full-non-sealed-cell benchmark (resolves `N_target`)

**Goal:** measure GEARS fit cost at **the two candidate roster sizes × the FULL non-sealed cell count**, so the
owner can freeze the largest `N_target` that fits the A100 time/cost budget. The smoke measured ~2k genes /
~1k **capped** cells (~25 s/epoch); that says nothing about full scale, and GEARS is CPU-bound so cost grows
with cells, not GPU.

**Roster construction (outcome-free, matches the §2 contract's fill statistic):** for each `N ∈ {2000, 5000}`,
rank genes by **control-cell variance** on the normalized control rows (the exact `_select_hvg` statistic,
response.py:485 — `control_norm.var(axis=0)`, ascending-index tie-break) and force-include every
`var ∩ gene2go` perturbation gene so GEARS composes each fit perturbation. **No sealed pairs, no perturbation
response, no outcome enters roster selection.** Cell set = **all** control + singles + combo_calibration rows
at their registered per-perturbation counts (no `CAP`).

| ID | Measurement | Why it gates `N_target` |
|----|-------------|-------------------------|
| **B1** | `PertData.new_data_process` (per-cell graph build) wall-time at 2k / 5k × full cells | One-time cost; CPU-bound and can dominate at full cell count |
| **B2** | per-epoch `model.train` wall-time (run k=3 epochs, report mean/‑stdev, extrapolate to the registered `_GEARS_EPOCHS=20`) | Total fit ≈ B1 + 20·B2; the feasibility number |
| **B3** | peak host RSS + peak GPU memory at each size | 5k may OOM host RAM on graph tensors |
| **B4** | host CPU core count + observed GPU utilization + whether the dataloader is the bottleneck | GEARS is ~1% GPU; a high-CPU instance may matter more than the A100 tier — informs provider choice (proposal #5) |

**Decision rule (Probe B → `N_target`).** Freeze `N_target = 5000` if `B1 + 20·B2` at 5k fits the owner's
per-run wall-time/cost budget with B3 within host limits; else fall back to `N_target = 2000` (or an
intermediate size the owner registers). The chosen size becomes a config field → new run identity. `N_target`
is selected from **B1–B4 only**, never from any predictive/outcome signal.

**Cost control:** epochs are extrapolated from k=3, so the benchmark runs ≈ `2 × (graph_build + 3·per_epoch)`
per size, not the full `2 × (graph_build + 20·per_epoch)`. The **production worker's hard-coded 20 epochs is
NOT weakened** — the benchmark is a standalone measurement harness that faithfully replays the worker's GEARS
config (imported constants) but is never the sealed-run path.

**Output:** `probe_b_scale_benchmark.json` — per-size B1–B4, extrapolated total fit time, host/GPU spec, and the
mechanical `N_target` recommendation from the rule.

---

## 3. Governance (why this opens no seal)

- **No sealed access.** Both probes use only control + non-sealed fit roles (Probe B) or a tiny synthetic-scale
  fit (Probe A). `payload["pair_ids"]` sealed set is empty; no `ComposeOutcomeStore` sealed read; the §4.3
  guards are untouched. This is a dev-pod **resource/behavior measurement**, not an evaluation.
- **Not a scientific fit.** Outputs are wall-time / memory / output-scale / source dumps — never a
  model-selection or evaluation outcome. No config finalize, no activation-evidence regen, no `config_sha256`
  change. Those remain the downstream, owner-gated steps.
- **Faithful to the committed config.** Probe B imports the committed `gears_worker` GEARS hyperparameters and
  resource-bundle validation so the measurement reflects the real pipeline (no drift proxy).
- **Provenance if promoted.** If the owner wants these measurements to be citable decision evidence, move the
  two scripts from scratchpad to `scripts/compose/`, commit them, and run under a recorded git SHA + wheel
  SHA-256 + input-data hash (the JSON outputs already record the wheel + data hashes). Until then they are
  staged dev tooling like the 2026-07-10 smoke scripts.

---

## 4. Pod runbook (execute when an A100 dev pod is up)

Environment (learned 2026-07-10; do not vary): GEARS runs **only** on `/root/gears_env_era`
(numpy 1.26.4 / pandas 2.2.3 / scipy 1.11.4 = `requirements.gears_env.lock`); the newest-stack env crashes
GEARS at runtime. Set `CUBLAS_WORKSPACE_CONFIG=:4096:8` and `PYTHONHASHSEED=11` (deterministic-algorithms +
seed guard in `_seed_gears_runtime`). GO manifest must be co-located with its GO files
(`_validate_gears_resource_bundle` uses `manifest.parent` as the bundle root).

Historical harness (**quarantined; never execute or copy forward**; originally staged at MacBook
`scratchpad/decision_probe/`): `run_decision_probe.sh` (orchestrator) ·
`probe_gears_source.py` (Probe A) · `bench_prep.py` (control-variance roster, no cap) · `build_payload.py`
(committed `build_dev_smoke_payload` wrapper) · `bench_gears_timing.py` (Probe B). The benchmark drives the
**committed** `gears_worker._fit_and_predict`; it monkeypatches `_GEARS_EPOCHS` for extrapolation **in-process
only** (the worker file is byte-unchanged; the production subprocess always runs 20).

```bash
# stage (from MacBook): scp the 5 harness files + this plan to /workspace/decision_probe/
# on pod (era stack drives GEARS; cpa_env_085 has anndata+alive for prep/build):
bash /workspace/decision_probe/run_decision_probe.sh \
     /workspace/alive_data/NormanWeissman2019_filtered.h5ad \
     /workspace/gears_data/gene2go_all.pkl \
     /workspace/gears_data/go_resource_manifest.json \
     /workspace/decision_probe/out
# collect (scp back): out/probe_a_gears_scale.json + probe_a_gears_source.txt (READ the .txt),
#                     out/probe_b_scale_benchmark_{2000,5000}.json, out/gpu_util.log
```

**Caveat (honest):** these scripts run only on the pod (GEARS + Norman + A100); they are syntax-checked but
un-executed, so budget one on-pod debug pass (the 2026-07-10 smoke needed several: env selection, scipy
backed-CSR, the `fit_artifact_content_sha256` kwarg asymmetry, the seed env vars). `n_calibration` defaults to
a representative 8 (control + all singles dominate the fit cell count); set `CALIB=<registered>` for an exact
number.

---

## 5. What this unblocks / what stays gated

**Unblocks (after the owner reads the two JSONs and decides):**
- the GEARS-scale linchpin (Option 1 vs 2) — via Probe A's decision rule;
- `N_target` for the §2 gene universe — via Probe B's decision rule;
- therefore the §2 gene-universe generator build and the config-finalize step.

**Still gated afterward (unchanged, recommendation doc §4 / readiness §5 #6):** config finalize (fill the null
blockers → new run identity) → activation-evidence regen under the finalized `config_sha256` → dep-lock
COMPLETE → the §5 #6 unshortened real-pod rerun → scientific PREPARE carrier → §2.5 release gate + owner exact
Git-SHA approval → the separate sealed-run pod opens the COMPOSE seal exactly once. **No seal is opened by
either probe.**
