# COMPOSE dev-pod — open-decision proposals (#1–#5)

> **STATUS: PROPOSED — pending owner confirmation. NOT yet encoded into `configs/compose_k562_v1_phase2.yaml`
> or any manifest.** These values will (after owner confirmation) be pinned into the config that binds the
> COMPOSE seal's activation lineage — every pin is a governance-consequential reproducibility decision.
> Nothing here changes `config_sha256` until the owner confirms and the values are written per the dev-pod
> plan's ⚑ ordering (config finalize → new run identity → THEN regenerate evidence).
>
> **⚠️ SELF-CORRECTED 2026-07-09.** The first draft relied on external PyPI-latest
> metadata. Subsequent dev-pod diagnosis established that CPA 0.7.2 crashes on the Norman
> setup under numpy 1.26.4, while CPA 0.8.5 and both cu124 environments complete observed
> compatibility smokes. The committed v2 lock now records those candidate pins but marks
> release evidence `INCOMPLETE`; a compatibility observation is not a seal-safe run attestation.

---

## AUTHORITATIVE ANCHOR: the committed dependency lock

`docs/activation-evidence/compose/gears_cpa_dependency_lock.json` records a full generation SHA and the
**NVIDIA A100 80GB** compatibility diagnosis. The committed requirements locks pin exact versions, and the
operator observed both backends complete one-epoch smokes after resolving CPA/GEARS compatibility faults.
However, schema v2 correctly marks the record `INCOMPLETE`: it lacks the fit-role row roster, sealed-pair
zero-overlap proof, immutable logs/checkpoints, package artifact hashes, and container image digest. Decisions
#1/#3 are therefore *candidate pins with compatibility evidence*, not release-verified scientific-run pins.
External research below is a cross-reference to published defaults, not a substitute for Task 0.1 evidence.

| env | package (verified) | Python | torch / CUDA | key stack |
|---|---|---|---|---|
| `gears_env` | **cell-gears 0.1.2** | 3.12 (system) | **2.6.0+cu124** | torch_geometric 2.8.0, numba 0.65, numpy 2.4.4 |
| `cpa_env` | **cpa-tools 0.8.5** | 3.10 (uv-managed cpython-3.10.18) | **2.6.0+cu124** | scvi-tools 0.20.3, lightning 2.6.5, jax/jaxlib 0.4.38, anndata 0.10.9, rdkit 2026.03.3 |

Committed `cpa_env` runtime landmines (Phase 0 MUST honor — from the lock's `runtime_notes`):
- Requires a **uv-managed** CPython 3.10 (the selected numba/llvmlite stack needs `>=3.7,<3.11`; the pod's system
  python3.10 lacks `_tkinter`, which `cpa/_model.py` imports).
- **Exclude `rdkit-pypi`** (cpa-tools declares the abandoned pkg → Boost.Python converter error); use modern `rdkit`.
- The 2023-era pin stack (`scvi-tools==0.20.3`, `jax/jaxlib==0.4.38`, `anndata<0.11`, `numpy 1.26.4`) is load-bearing.
- Set `MPLBACKEND=Agg` for headless matplotlib.

---

## #1 — GEARS published config + revision

**Revision (→ `baselines.gears.revision`): `cell-gears 0.1.2`.** CONFIRMED by the committed lock (gears_env
runtime_notes: "GEARS (cell-gears 0.1.2) imports cleanly … on 3.12"). Matches external research.
- ⚠️ config currently reads `baselines.gears.package: gears` — that is the *import* name; the *pip* name is
  `cell-gears`. Recommend clarifying and pinning `revision: "cell-gears==0.1.2"`.
- No GitHub release tag for 0.1.2 → also record a SHA in the dependency lock; the installed **0.1.2 wheel** is
  authoritative (not master), so **POD-VERIFY** the installed bytes.

**Published default training config** — external research read these from repo **master `f374e43`** (`gears/gears.py`
signatures + README): epochs=20, lr=1e-3, weight_decay=5e-4, Adam, StepLR(step_size=1,gamma=0.5), hidden_size=64,
num_go_gnn_layers=1, num_gene_gnn_layers=1, decoder_hidden_size=16, num_similar_genes_{go,co}=20,
coexpress_threshold=0.4, uncertainty=False, direction_lambda=1e-1; batch_size=32/test_batch_size=128 (get_dataloader
args); early-stop = best val `mse_de` (no patience); seeds module `manual_seed(0)` + split seed=1; **no K562-specific
override exists.**
- **CAVEATS (POD-VERIFY):** (a) master `f374e43` (2025-02-01) is POST the installed **0.1.2 wheel** (2023-12-13) —
  the wheel's defaults may differ; the worker should pin EXPLICIT hyperparameters read from the installed 0.1.2
  version, not rely on master. (b) "repo default" (epochs=20 etc.) is not confirmed to equal the paper's exact
  Norman-benchmark training config; if a paper-faithful run is intended, verify against the paper on the pod.
- Source root: `https://raw.githubusercontent.com/snap-stanford/GEARS/master/gears/gears.py`.

## #2 — GEARS GO-graph / gene2go source — RESOLVED

The committed `compose_go_resource_manifest_v2` closes the former provenance gap. It
binds Harvard Dataverse dataset **PertNet**, persistent ID `doi:10.7910/DVN/Q2ZV3E`,
dataset license **CC0-1.0**, exact datafile IDs 6153417/6934320/6934319, dataset versions
3.0/7.0/7.0, file versions, byte counts, upstream MD5 values, acquired SHA-256 values,
and the extracted GO CSV SHA-256. The dependency lock binds the manifest file bytes.

This resolves *identity and license*, not fit-time acquisition: Task 0.2 must reproduce
those exact bytes into pod object storage and recheck size + MD5 + SHA-256. Workers may
not download or substitute a resource at fit time. The co-expression graph remains a
derivative of the role-restricted training AnnData, not a precomputed external outcome.

## #3 — CPA (cpa-tools) setup + revision — compatibility candidate 0.8.5

**Revision candidate (→ `baselines.cpa.revision`): `cpa-tools 0.8.5`.** The dev pod
observed `setup_anndata` plus a one-epoch GPU smoke succeed after 0.7.2 failed on
`np.int`. Env: Python 3.10 uv-managed + torch 2.6.0+cu124 + scvi-tools 0.20.3 +
lightning 2.6.5 + jax 0.4.38 + anndata 0.10.9. This is compatibility evidence;
Task 0.1 must rerun on the role-restricted artifact and capture immutable evidence.

**Combo config for 0.8.5 = POD-VERIFY (not yet sourced).** The external research config (n_latent=32, doser=linear,
seed=8206, the specific trainer_params, max_epochs=2000/batch=2048) came from the **0.8.8** Norman tutorial — the
wrong version for the selected 0.8.5 env. Do not use those values as-is. Read the exact
defaults from the installed 0.8.5 wheel and its contemporaneous tutorial, then pin them
explicitly before the seal-safe smoke.
- Output representation (per-cell, NB raw counts → `cpa.prediction_representation = cell_raw_counts`) holds for CPA
  generally; that part of the research is version-robust.
**"0.7.2로 해도 문제 없나?" — investigated (v0.7.2…main code diff + PyPI timeline + the committed lock):**
- **Science (core model): 0.7.2 is NOT a weakened baseline.** The compositional latent `z = z_basal + z_pert +
  z_covs` in `cpa/_module.py` is IDENTICAL across 0.7.2→0.8.8; the 137-commit delta is dominated by
  packaging/python-version/docs/tutorials + a new autotuner (`_tuner.py`, purely additive) + optional prediction
  flexibility (`covars_to_add`, `z_no_pert` latents). No combo-algorithm change. 0.7.2 is also paper-contemporaneous
  (Sep 2023, same era as the MSB-2023 paper). (Timeline caveat: 0.8.0 branched the SAME DAY as 0.7.2 — 0.8.x is the
  maintained line; 0.7.x ended at 0.7.2.)
- **⚠️ Historical runtime landmine — 0.7.2 cannot run the selected Norman setup.** The 0.7.2→main
  diff shows two fixes in `cpa/_model.py::setup_anndata` that 0.7.2 lacks: (1) `.astype(np.int)` → `.astype(int)` —
  `np.int` was removed in numpy ≥1.24; the prior lock paired `cpa-tools==0.7.2` with
  `numpy==1.26.4`, so the `deg_uns_key` branch raised
  `AttributeError: module 'numpy' has no attribute 'int'`; (2) a `if smiles_key is not None:` guard for the
  no-SMILES (gene) perturbation path 0.7.2 lacks. The pod observation confirmed the
  failure and the current lock now pins 0.8.5.
- **So compatibility does not by itself settle the release pin.** Governance (§6 baseline:
  the baseline must actually run at published strength) requires a dev-pod Phase-0 gate
  on the role-restricted COMPOSE artifact with immutable input/log/checkpoint evidence
  and a proved-zero sealed-pair intersection.
- **Fix timeline (verified via `cpa/_model.py` at each tag):** v0.7.2 has `np.int` + no smiles guard; **v0.8.2** still
  has `np.int` (smiles guard added); **v0.8.5** (2023-11-03, tag `7cda37e`) is the **earliest release with BOTH fixes**
  (`np.int`→`int`, smiles guard). v0.8.8 (2024-08) also has them but is untagged (pin a SHA) and 9 months of dep drift.
- **SELECTED COMPATIBILITY CANDIDATE: `cpa-tools==0.8.5`.** It is the earliest tagged
  version with both runtime fixes AND closest to the fresh-sync-verified 0.7.2-era stack (scvi 0.20.3 / jax 0.4.38 /
  anndata 0.10.9), so the env change is the **minimal delta** — bump cpa `0.7.2→0.8.5`, keep the rest of the committed
  stack, and numpy 1.26.4 now works. 0.8.8 is the fallback if the current documented Norman tutorial is preferred, at
  the cost of more dep re-resolution. The observed generic Norman smoke selected 0.8.5
  as the compatibility candidate. It becomes release-verified only after the
  fit-role-only, zero-overlap, hash-bound Task-0.1 gate passes.
- **0.8.5 is numpy-clean EVERYWHERE (verified):** grepped ALL 9 `cpa/*.py` at tag v0.8.5 for every alias numpy 1.24
  removed (`np.int/float/bool/object/str`) → ZERO hits. So the numpy-1.26.4 override that CRASHED 0.7.2 is code-safe
  on 0.8.5.
- **⚠️ dev-pod build instruction — do NOT naive-install.** v0.8.5's pyproject DECLARES conservative bounds
  (`numpy>=1.22.4,<1.24`, `anndata>=0.9.0,<0.10.0`, `torch>1.8.0,<=2.0.1`). A plain `pip install cpa-tools==0.8.5`
  would pull numpy `<1.24` (which HAS `np.int`) and conflict with numba 0.65 / torch 2.6. REBUILD
  `requirements.cpa_env.lock` with `cpa-tools==0.8.5`, numpy 1.26.4, anndata 0.10.9,
  and torch 2.6.0+cu124. The recorded `unsafe-best-match` reconstruction is acceptable
  for diagnosis only; release reproduction additionally needs artifact hashes.
- **Residual to release-verify:** 0.8.5 was observed to tolerate the forced anndata 0.10.9
  despite its declared `<0.10.0` bound. That unsupported combination and its exact package
  artifacts must be reconstructed and captured by the stricter Phase-0 gate.

## #4 — GEARS pseudobulk-approximation bias metric (→ `baselines.gears.approximation_bias_report_sha256`)

**Designed against the ALIVE code; pre-registered per the plan's Task-2.2 open_item.**

Grounding: `RESPONSE_TRANSFORM = ("normalize_total_median", "log1p")` (`response.py:45`) is **nonlinear**, and it is
applied per-cell after a **per-cell library-size normalization** (`_normalize_log1p`). In `apply_response_projection`
(`fit_role.py:924`) the ONLY difference between the two representations is the input:
- `raw_pseudobulk_approximation`: `operator_input = native.mean(axis=0)` → `PCA(log1p(normalize(mean(raw))))`
- `cell_raw_counts`: per-cell → caller means → `mean_i[PCA(log1p(normalize(raw_i)))]`
Because PCA projection is affine, `mean_i` commutes with it, so the bias reduces to the PCA image of the HVG-space gap
`log1p(normalize(mean raw)) − mean_i[log1p(normalize(raw_i))]`. This gap has **TWO systematic sources**: (a) the
library-size normalization is per-cell (each cell scaled by its own inverse total) vs applied once to the raw mean —
`normalize(mean(raw)) ≠ mean_i(normalize(raw_i))`; and (b) the `log1p` Jensen gap (`log1p` concave → `log1p(mean) ≥
mean(log1p)`). **Do NOT assume the total gap is one-signed** — (b) is one-signed but (a) reshuffles mass and need not
be; the metric measures the empirical sign structure rather than assuming it. This is exactly "the bias introduced by
`raw_pseudobulk_approximation` vs per-cell."

**Metric (non-sealed roles ONLY: control · singles · combo_calibration; model-independent — no GEARS fit needed):**
For each non-sealed group with real cells, using the frozen `response_projection` block:
- `δ_pb = apply_response_projection(mean(raw over the group)) − ctrl_proj`  (pseudobulk path)
- `δ_pc = mean_i[apply_response_projection(raw_i)] − ctrl_proj`  (per-cell path)
- bias `b = δ_pb − δ_pc` (a `pca_dim` vector).

Report (canonical JSON): **directional component** `mean_g b` per dim + `‖mean_g b‖` (the non-cancelling bias,
whatever its sign) AND **magnitude** median/max over groups of `‖b‖ / ‖δ_pc‖`; **per-dim profile** of `mean_g b`;
provenance = frozen projection `gene_order_sha256`/pca digest, non-sealed role manifest hash, group roster, git SHA.

Properties: computed from the representation transform + real **non-sealed** cells only → cannot read a sealed
outcome; an activation *requirement* (a pipeline property), NOT a tunable / not outcome-selected; pre-registering the
definition before any sealed access prevents post-hoc shaping. CPA (`cell_raw_counts`) is exact → its
`approximation_bias_report_sha256` stays **null** by design. **NOTE:** this metric is a *proposed definition* for an
open design task (plan decision #4 explicitly leaves it open) — it interprets "approximation bias" as the
representation transform's systematic error, since GEARS cannot produce a per-cell prediction to compare against.
Owner/spec may refine the definition.

## #5 — Dev-pod provider/instance (OWNER decision) — CORRECTED

**The first draft's "cpa cannot use cu124 / needs torch≤2.0.1" constraint is RETRACTED — it was a false
extrapolation from cpa-tools 0.8.8's declared pyproject bounds and is contradicted by the verified lock.** The
committed lock runs **both envs on torch 2.6.0+cu124** on an A100 80GB, fresh-sync-verified. **The prior A100 cu124
pattern works.** Real provisioning specifics (from the lock, not new constraints):
- `gears_env`: system Python 3.12 + torch 2.6.0+cu124 + torch_geometric 2.8.0 + cell-gears 0.1.2.
- `cpa_env`: uv-managed CPython 3.10 + torch 2.6.0+cu124 + cpa-tools 0.8.5 on the era-consistent stack (see anchor +
  runtime_notes: tkinter, rdkit-pypi exclusion, scvi/jax/anndata pins, MPLBACKEND=Agg).
- Owner picks provider/instance; the verified reference is **RunPod A100 80GB, cu124, uv 0.9.0, driver 550.127.05**.

---

## Config-field mapping (once owner confirms)

| decision | config field / artifact | value | source / remaining |
|---|---|---|---|
| #1 | `baselines.gears.revision` (+ dep lock) | `cell-gears==0.1.2` + SHA | **committed lock (verified)**; clarify `package` (import `gears` vs pip `cell-gears`); pod-verify wheel |
| #1 | GEARS hyperparams (worker + dep lock) | master defaults above as REFERENCE | **pod-verify against installed 0.1.2 wheel**; worker pins explicit values |
| #2 | `go_resource_manifest.json` | DOI `10.7910/DVN/Q2ZV3E`, CC0-1.0, exact 3-file roster + hashes | **resolved in v2 manifest; pod must reproduce bytes** |
| #3 | `baselines.cpa.revision` (+ dep lock) | **`cpa-tools==0.8.5`** (recommended; NOT 0.7.2 — np.int crash) | earliest tagged w/ both fixes + minimal stack delta; **dev-pod Phase-0 RUN-gate confirms** |
| #3 | CPA combo config (worker + dep lock) | **POD-VERIFY (version-matched)** | read and pin exact 0.8.5 defaults; do not transplant 0.8.8 tutorial values |
| #4 | `baselines.gears.approximation_bias_report_sha256` | Task-2.2 report SHA (metric above) | run on pod, non-sealed |
| #4 | `baselines.cpa.approximation_bias_report_sha256` | **null** (exact representation) | none |
| #5 | env locks / provider | 2 version-pinned envs, both cu124 | compatibility observed; wheelhouse/image digest missing; **owner picks provider** |
| — | `baselines.{gears,cpa}.environment_status` | promote from verified lock, re-verify on pod | pod fresh-sync |
| — | `regimes.power_status` | established by Task-2.1 detectable-effect report | pod (Phase 2, not a #1–5 decision) |

**⚑ Reminder:** confirmed values → write config (fills null blockers → **new `config_sha256` = new run identity**) →
commit finalized config → **THEN** regenerate the two evidence reports (else `config_sha256` re-drifts). See the plan's
Global ⚑ constraint and Task 2.1–2.3.
