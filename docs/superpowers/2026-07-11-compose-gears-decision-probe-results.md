# COMPOSE dev-pod — GEARS decision-probe RESULTS (2026-07-11)

> **STATUS: QUARANTINED PARTIAL OBSERVATIONS — Probe B NONCONFORMING; scientific decisions remain
> PROVISIONAL.** The official one-time `ComposeOutcomeStore` evaluation gateway was not consumed and no
> outcome-based selection was demonstrated. However, the as-run prep loaded all source expression before the dev
> sealed/calibration split, violating metadata-before-expression and invalidating the stronger “sealed expression
> never materialized / opened no seal” claim. The `2026-07-10-compose-gears-decision-probe-plan.md` was only
> partially executed on an A100 dev pod. §4.3 production guards were not invoked by the prep path;
> committed worker byte-unchanged (measurement harness monkeypatched `_GEARS_EPOCHS`/DataLoader in-process
> only). Probe A's recoverable source JSON/text and the full as-run harness are version-controlled, but Probe B's
> raw JSON/log/GPU outputs were not preserved. Probe A's empirical output-scale/equivalence checks and Probe B's
> conforming 2k/5k/resource measurements are incomplete; nothing here may finalize config or activation evidence.

## -1. Compliance finding and disposition

- `evidence/2026-07-11-gears-decision-probe/harness/bench_prep.py:37` used in-memory `read_h5ad`, materializing
  all source `X` before any dev sealed/calibration identity existed.
- Its lines 64–76 and 106 selected/copy-materialized all measurable perturbation rows. Only afterward did
  `build_payload.py` invoke `build_dev_smoke_payload` to assign and exclude dev-sealed pairs. That exclusion was
  too late to satisfy the non-materialization contract.
- The same prep selected a reduced gene matrix before the full-universe normalization/response artifact and used
  “top N, then force-add”, so it is also incompatible with the revised `U_full`/`R_gears` architecture and exact
  `N_target` rule.
- **Disposition:** retain the recovered bytes as forensic evidence; do not repair or rerun them in place; do not
  cite Probe B timing for `N_target`; execute only the replacement runbook
  `runbooks/2026-07-11-compose-gears-decision-probe-rerun.md` after its local gates pass.

## 0. Environment reality (for the next pod session)

- **`/workspace` mfs volume is OUT OF QUOTA** (`EDQUOT` on any write; memory fine). Prior envs (3× cpa ≈ 28G,
  gears_env 8.3G) + data fill it. The GEARS era env and all probe outputs were built/run on **local `/root`**
  (overlay, 25G free), reading Norman/gears_data from `/workspace` (reads unaffected). ⇒ the era env is on
  **ephemeral `/root`** and is **lost when the pod stops**; persisting it needs `/workspace` quota freed/expanded.
- The on-volume `gears_era_build.sh` pins `pandas==2.0.3` (no py3.12 wheel → sdist build fails on `pkg_resources`).
  **Use the frozen `gears_era.lock` (pandas 2.2.3)** — installs clean. Verified stack: gears 0.1.2 / numpy 1.26.4 /
  scipy 1.11.4 / pandas 2.2.3 / anndata 0.10.9 / sklearn 1.9.0 / torch 2.6.0+cu124, cuda True.
- Host = **252 CPU cores**, 1× A100 80GB.

## 1. Probe A — GEARS scale linchpin → owner preference **Option 1**, NOT YET LOCKED

From the installed `cell-gears==0.1.2` source (dumped, fingerprint `f63e48d67616…`):
- `GEARS.predict` asks `create_cell_graph_dataset_for_prediction` for its default 300 graphs, but that helper
  draws 300 indices **with replacement** from `ctrl_adata`; it does not build one graph for every supplied
  control exactly once. `predict` then takes the single 300-row batch, runs the model, and returns
  `np.mean(p, axis=0)`. This corrects the earlier overstatement that the public result was the first ≤300 supplied
  controls; the old run remains quarantined and this source correction is not decision evidence.
- `PertData.new_data_process` does **NOT normalize** the caller AnnData (only `get_DE_genes` + dropout metadata,
  graphs from `X` as-is).

⇒ GEARS trains/predicts in **whatever scale the worker feeds**. Option 1's feared package-internal risk
("GEARS normalizes on the reduced matrix") does not apply because GEARS normalizes on neither. This makes a
worker-controlled full-library normalize→`log1p` Option 1 **architecturally viable**, but does not yet establish
that an actual fitted model returns the expected scale, obeys the negative-output contract, or reproduces the
public mean through the per-control adapter. Nor does it place output "directly" in COMPOSE space without the
registered target, negative policy, full-gene/HVG remap, and frozen PCA. **Owner preference: pursue Option 1
(published-scale, worker-normalize), while activation remains blocked.**

### Probe-A completion against the registered plan

| Gate | Current evidence | Status needed for lock |
|---|---|---|
| P1: package normalization/order | Source shows `new_data_process` leaves caller `X` as supplied; no durable processed-`X` measurement is present | **PARTIAL** — retain source finding, recover/redo empirical processed-`X` check |
| P2: fitted prediction output scale | No min/median/max, near-integer fraction, negative fraction, or `expm1` diagnostic is recorded | **NOT RUN / NOT RECOVERED** |
| P3: per-control rows + first ≤300 behavior | Source establishes a 300-draw replacement sample, one batch, and mean—not first-prefix semantics; the planned `n_control ∈ {1,8,300,301,400}` instrumentation is absent | **PARTIAL / PREMISE CORRECTED** |
| P4: `T_gears` | Package does not choose it; it becomes a worker-controlled normalization target, but no exact value is frozen here | **PENDING OWNER RECORD** |
| Inference equivalence | No adapter-row mean versus public `GEARS.predict` tolerance result | **NOT RUN / NOT RECOVERED** |
| Negative-output contract | No fitted-output diagnostic or acceptance threshold | **NOT RUN / NOT FROZEN** |

Therefore this section supports **Option-1 development**, not Option-1 scientific activation or an unqualified
"published-strength" label. The comparator-adequacy and bridge-fidelity gates also remain open.

## 2. Probe B — partial full-cell cost observation → `N_target` UNRESOLVED

Full non-sealed fit-role (no cap; config has only `min_cells_per_gene/pair=50`, **no per-perturbation cap**):
- **70,987 cells** (control 11,855 + singles 56,012 + combo_calibration 3,120) × 2,088 genes.
- **59,132 train cells** (control excluded from optimization loaders), ~1,847 steps/epoch (batch 32, drop_last).
- Graph build (`create_dataset_file`) ≈ **94 s**.

The measured artifact had **2,088 genes, not 2,000**. That is incompatible with the exact-size gene-universe
contract unless `N_target` is explicitly redefined. A likely explanation is "select 2,000, then force-add
missing perturbation genes," but the generator contract instead requires mandatory set `M` first, exact
`N_target`, and failure when `|M| > N_target`. The exact `|M|`, overlap counts, selection order, and reason for
the extra 88 genes were not preserved here. Consequently this run cannot lock `N_target=2000`.

### Probe-B completion against the registered plan

| Gate | 2,088-gene observation | 5k candidate | Status |
|---|---|---|---|
| B1 graph-build wall time | ≈94 s summary only | not recorded | **PARTIAL** |
| B2 k=3 epoch mean/stdev + 20-epoch extrapolation | coarse ~2.0 steps/s and component estimate; no k=3 mean/stdev/raw timings | not recorded | **PARTIAL / MISSING** |
| B3 peak host RSS + peak GPU memory | GPU allocation snapshot only; peak RSS absent | not recorded | **MISSING** |
| B4 host/GPU utilization + bottleneck | 252 cores and coarse 0–11% GPU observation | not recorded at 5k; raw `gpu_util.log` absent | **PARTIAL** |
| owner wall-time/cost budget | not stated | not stated | **MISSING DECISION INPUT** |

The plan's rule requires both candidate sizes (or a recorded, predeclared budget reason that rules one out).
The statement "5k ≈2×" is an unverified extrapolation and cannot substitute for the missing 5k B1–B4 run.
Until the mandatory-set size and resource evidence are available, record `N_target: unresolved`.

## 3. Tractability — provisional observations, not yet a production optimization decision

**`num_workers` showed no visible benefit in this coarse sweep.** Train DataLoader
`num_workers ∈ {0,16,32}` (persistent_workers, pin_memory, OMP=2) on the 2,088-gene artifact reported
approximately **2.0 steps/sec** at every setting; GPU 0–11%, 1,985 MiB. Without raw timings, precision, repeats,
or uncertainty, this supports shelving `num_workers` tuning but not a universal claim that the DataLoader can
never contribute to cost.

**Per-epoch cost decomposition:**

| component | cost | notes |
|---|---|---|
| training (1,847 steps @ 2.0/s) | **~15 min/epoch** | GPU idle (6–11%) → per-step framework/CPU overhead, not data loading; batch=32 underfeeds the GPU but batch size is a locked hyperparameter |
| GEARS per-epoch **eval** | **~15–20 min/epoch** | `evaluate(train_loader)` = a FULL forward over all 59k train cells + `evaluate(val_loader)` + `compute_metrics` (MSE + DE), **every epoch** (gears.py `train()`) |

⇒ The observed components suggest **~30–35 min/epoch → a 20-epoch GEARS fit near this 2,088-gene setup of
roughly ~10–12 hr**. This is a planning estimate, not release evidence: raw per-epoch samples and variance were
not preserved. The previous "5k ≈ ~2×" statement is not a measurement and must not drive `N_target`.

**Candidate lever: remove or replace per-epoch monitoring evaluation.** The worker uses `fixed_final_epoch`
and rebinds `model.best_model = final_model` (gears_worker.py:918), **discarding** GEARS's val-selected
`best_model`. So the
per-epoch metrics do not select COMPOSE's saved checkpoint. A registered training loop without those full
forwards could plausibly remove much of the estimated monitoring cost, but **zero scientific/execution cost is
not established**.

**Caveats before adopting (do NOT just patch):**

- The current training DataLoader is `shuffle=True`. Even if `model.eval()` + `no_grad` does not mutate weights,
  iterating `evaluate(train_loader)` creates another shuffled iterator and can consume RNG/sampler state,
  changing the next epoch's optimization order and final weights. Bit-identical A/B verification is therefore
  a **load-bearing and plausibly failing** gate, not a formality.
- A literal no-op also must preserve GEARS's expected metric/control flow. If bit identity fails, removing eval
  is a distinct registered training algorithm and run identity, not a zero-cost implementation optimization.
- It is a change to the production worker (`_fit_and_predict`), so it goes through the normal dev process
  (spec/plan/review + determinism test), not an ad-hoc patch. The existing offline-download monkeypatches are the
  precedent for patching GEARS internals inside the worker.
- `num_workers` is shelved for now (no observed benefit in the coarse sweep, while changing it could perturb
  data-loading determinism without demonstrated gain).
- Provider conclusion is provisional. Low sampled utilization suggests CPU/framework overhead, but raw GPU
  utilization logs and a controlled provider comparison are absent. Do not make a procurement/provider lock
  from this summary alone.

## 4. What this unblocks / next

- **What is supported now:** pursue Option 1 in development; GEARS consumes caller-provided scale; public
  prediction aggregates internal per-control rows; full-cell cost near 2,088 genes is substantial; extra
  `num_workers` did not visibly help in the coarse observation.
- **What is not unlocked:** scientific Option-1 activation, an unqualified published-strength claim, exact
  `N_target`, provider choice, eval removal, config finalize, or activation-evidence regeneration.
- **Required next, in order:**

  1. Keep the recovered archive quarantined and immutable; it is already marked non-durable/nonconforming. Never
     infer or reconstruct the lost Probe B logs.
  2. The exact-size generator and full-normalize-then-subset **fit-input** adapter are implemented in the current
     local working tree. Bind them to an exact clean Git SHA and complete independent review; do not confuse this
     with the still Probe-A-blocked scientific output bridge.
  3. On verified real candidate/GO/alias/fit-role/response inputs, run GU report mode to record canonical `M` and
     component/overlap counts, then freeze digest-bound candidate rosters. The historical 2,088-gene artifact is
     not a candidate.
  4. Complete conforming Probe A fitted-output scale, negative-output, control-count instrumentation, exact
     `T_gears`, determinism, and inference-equivalence gates using the replacement runbook.
  5. Run repeated Probe B B1–B4 on the exact candidate rosters with full raw logs and identities; then let the
     owner freeze representation/`N_target` using only preregistered behavior/resource criteria.
  6. Treat eval removal as an independent optimization experiment. Adopt it only if its registered A/B gate
     passes; otherwise keep upstream evaluation or register a scientifically distinct training loop. Finalize
     config only after all upstream decisions and evidence are durable.
- **Downstream remains unchanged:** config finalize → activation-evidence regeneration → dep-lock → §5 #6
  unshortened full-universe rerun → scientific PREPARE/release gates → separately authorized sealed run.
- **No official one-time evaluation claim was consumed.** Probe B nevertheless failed the stricter dev-sealed
  non-materialization boundary and remains quarantined.

## 5. Evidence durability and current limitations

The registered plan named `probe_a_gears_scale.json`, `probe_a_gears_source.txt`,
`probe_b_scale_benchmark_{2000,5000}.json`, and `gpu_util.log`. Of these, **Probe A's
`probe_a_gears_scale.json` + `probe_a_gears_source.txt` and the full measurement harness are now
version-controlled** at `evidence/2026-07-11-gears-decision-probe/` (see its README; full source fingerprint
`f63e48d676169ba5be94ebdd4dfe96ad7834ba7273d5bfe46b65b7a5a486a57e` recorded there, plus sha256 of each archived
output). The **Probe B benchmark JSONs, all raw `bench_*`/`workers_*` logs, and `gpu_util.log` were never
written or lived under ephemeral `/root` and are lost with the (now stopped) pod**; the timing/step-rate numbers
in §2–§3 are coarse live-sampled estimates, not preserved raw measurements. Input-data and runtime-image hashes,
and exact command logs, were not captured.

Accordingly, this Markdown file is a human observation record, **not durable decision evidence**. It may be
promoted only with full hashes, raw measurements, immutable harness/source, exact command/runtime identity,
and explicit links from the finalized config/activation record. Missing evidence must be rerun, never inferred
from the summary or replaced with extrapolated values.
