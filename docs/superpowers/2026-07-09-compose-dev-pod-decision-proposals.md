# COMPOSE dev-pod — open-decision proposals (#1–#5)

> **STATUS: PROPOSED — pending owner confirmation. NOT yet encoded into `configs/compose_k562_v1_phase2.yaml`
> or any manifest.** These values will (after owner confirmation) be pinned into the config that binds the
> COMPOSE seal's activation lineage — every pin is a governance-consequential reproducibility decision.
> Nothing here changes `config_sha256` until the owner confirms and the values are written per the dev-pod
> plan's ⚑ ordering (config finalize → new run identity → THEN regenerate evidence).
>
> **⚠️ SELF-CORRECTED 2026-07-09.** The first draft of this file researched external PyPI-latest packages WITHOUT
> first consulting the repo's own committed, A100-fresh-sync-verified `docs/activation-evidence/compose/gears_cpa_dependency_lock.json`.
> That produced two errors, now fixed: (1) CPA was proposed as `cpa-tools==0.8.8`, but the verified lock pins
> **`cpa-tools 0.7.2`**; (2) a "#5 cpa cannot use cu124 / needs torch≤2.0.1" constraint was asserted, but the
> verified lock runs **both** envs on **torch 2.6.0+cu124**. The committed lock — not external PyPI — is the
> authoritative env record; this file is now anchored on it.

---

## AUTHORITATIVE ANCHOR: the committed dependency lock

`docs/activation-evidence/compose/gears_cpa_dependency_lock.json` (git `79b01e0`, generated 2026-06-29 on an
**NVIDIA A100 80GB**, `both_backends_import_ok: true`, `lock_verified_by_fresh_sync: true`) already pins both envs.
The committed `requirements.gears_env.lock` (sha `f0a62c63…`) and `requirements.cpa_env.lock` (sha `50d26900…`)
exist. So decisions #1/#3 (revision) and #5 (env/provider) are **largely already answered and verified** — the
dev-pod work PROMOTES these into the config, then re-verifies on the dev pod (plan Task 0.1). External research
below is a *cross-reference* to the published defaults, NOT the source of the pins.

| env | package (verified) | Python | torch / CUDA | key stack |
|---|---|---|---|---|
| `gears_env` | **cell-gears 0.1.2** | 3.12 (system) | **2.6.0+cu124** | torch_geometric 2.8.0, numba 0.65, numpy 2.4.4 |
| `cpa_env` | **cpa-tools 0.7.2** | 3.10 (uv-managed cpython-3.10.18) | **2.6.0+cu124** | scvi-tools 0.20.3, lightning 2.6.5, jax/jaxlib 0.4.38, anndata 0.10.9, rdkit 2026.03.3 |

Committed `cpa_env` runtime landmines (Phase 0 MUST honor — from the lock's `runtime_notes`):
- Requires a **uv-managed** CPython 3.10 (cpa-tools 0.7.2's numba/llvmlite pin needs `>=3.7,<3.11`; the pod's system
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

## #2 — GEARS GO-graph / gene2go source (→ `go_resource_manifest.json`)

Unchanged (env install does NOT fetch this; GEARS downloads it at data-load time — a separate Task-0.2 resource).
Only the GO `gene2go` pickle is downloaded; the co-expression graph is computed from the training AnnData.
- Primary: `gene2go.pkl` — `https://dataverse.harvard.edu/api/access/datafile/6153417` (Harvard Dataverse;
  `pertdata.py:92-94`). File API: MD5 `77c9af0c61c30ea4d7a85680f4d122dc`, size `9462558`, published `2022-03-24`,
  `restricted:false`.
- Companion: `essential_all_data_pert_genes.pkl` — `datafile/6934320` (`pertdata.py:119`).
- **GAPS (owner/pod):** **license = POD-VERIFY** (not in code or Dataverse file API; upstream GO generally CC BY 4.0
  but unconfirmed for this pickle — owner resolves the manifest `license`); **GO version = POD-VERIFY** (only the
  2022-03-24 date known); **SHA-256 = POD-VERIFY** (Dataverse gives only MD5 → compute SHA-256 over acquired bytes).

## #3 — CPA (cpa-tools) setup + revision — CORRECTED to 0.7.2

**Revision (→ `baselines.cpa.revision`): `cpa-tools 0.7.2`** (committed lock, verified). **NOT `0.8.8`** — that was
the first draft's error (0.8.8 is PyPI-latest but is NOT what the repo's verified env pins). Env: Python 3.10
uv-managed + torch 2.6.0+cu124 + scvi-tools 0.20.3 + lightning 2.6.5 + jax 0.4.38 + anndata 0.10.9 (see anchor table).

**Combo config for 0.7.2 = POD-VERIFY (not yet sourced).** The external research config (n_latent=32, doser=linear,
seed=8206, the specific trainer_params, max_epochs=2000/batch=2048) came from the **0.8.8** Norman tutorial — the
**WRONG version** for the pinned 0.7.2 env. Do NOT use those values as-is. The 0.7.2 combo config must be read from
the **installed 0.7.2 wheel + its contemporaneous tutorial** on the dev pod. (I can re-research the 0.7.2-era combo
tutorial on request, but a version-matched pod read is safer.)
- Output representation (per-cell, NB raw counts → `cpa.prediction_representation = cell_raw_counts`) holds for CPA
  generally; that part of the research is version-robust.
**"0.7.2로 해도 문제 없나?" — investigated (v0.7.2…main code diff + PyPI timeline + the committed lock):**
- **Science (core model): 0.7.2 is NOT a weakened baseline.** The compositional latent `z = z_basal + z_pert +
  z_covs` in `cpa/_module.py` is IDENTICAL across 0.7.2→0.8.8; the 137-commit delta is dominated by
  packaging/python-version/docs/tutorials + a new autotuner (`_tuner.py`, purely additive) + optional prediction
  flexibility (`covars_to_add`, `z_no_pert` latents). No combo-algorithm change. 0.7.2 is also paper-contemporaneous
  (Sep 2023, same era as the MSB-2023 paper). (Timeline caveat: 0.8.0 branched the SAME DAY as 0.7.2 — 0.8.x is the
  maintained line; 0.7.x ended at 0.7.2.)
- **⚠️ Runtime landmine — 0.7.2 + the committed env likely CANNOT run the Norman gene-combo setup.** The 0.7.2→main
  diff shows two fixes in `cpa/_model.py::setup_anndata` that 0.7.2 lacks: (1) `.astype(np.int)` → `.astype(int)` —
  `np.int` was REMOVED in numpy ≥1.24, and the committed `requirements.cpa_env.lock` pins **`cpa-tools==0.7.2` +
  `numpy==1.26.4` together**, so the `deg_uns_key` branch the Norman combo tutorial exercises would raise
  `AttributeError: module 'numpy' has no attribute 'int'`; (2) a `if smiles_key is not None:` guard for the
  no-SMILES (gene) perturbation path 0.7.2 lacks. **The committed lock verified IMPORT only** (`both_backends_import_ok`),
  NOT running `setup_anndata`/fit on Norman — so these landmines were not caught. (High confidence from the files;
  not yet executed → RUN-verify on the dev pod.)
- **So the cpa version is NOT actually settled by the "verified" lock.** Governance (§6 baseline: the baseline must
  actually RUN at published strength) requires a dev-pod Phase-0 gate that **runs the Norman gene-combo
  `setup_anndata` + a short fit end-to-end** (not just import). Whichever version passes THAT is the pin.
- **Fix timeline (verified via `cpa/_model.py` at each tag):** v0.7.2 has `np.int` + no smiles guard; **v0.8.2** still
  has `np.int` (smiles guard added); **v0.8.5** (2023-11-03, tag `7cda37e`) is the **earliest release with BOTH fixes**
  (`np.int`→`int`, smiles guard). v0.8.8 (2024-08) also has them but is untagged (pin a SHA) and 9 months of dep drift.
- **RECOMMENDATION: pin `cpa-tools==0.8.5`** (reversed from the first draft's "keep 0.7.2"). It is the earliest TAGGED
  version with both runtime fixes AND closest to the fresh-sync-verified 0.7.2-era stack (scvi 0.20.3 / jax 0.4.38 /
  anndata 0.10.9), so the env change is the **minimal delta** — bump cpa `0.7.2→0.8.5`, keep the rest of the committed
  stack, and numpy 1.26.4 now works. 0.8.8 is the fallback if the current documented Norman tutorial is preferred, at
  the cost of more dep re-resolution. **Either way the pin is CONFIRMED by the dev-pod Phase-0 Norman RUN-gate**
  (setup+1-epoch fit end-to-end, not import) — this cannot be finalized on the MacBook (no Norman data / GPU). 0.7.2
  is disqualified unless it somehow passes that gate.
- **0.8.5 is numpy-clean EVERYWHERE (verified):** grepped ALL 9 `cpa/*.py` at tag v0.8.5 for every alias numpy 1.24
  removed (`np.int/float/bool/object/str`) → ZERO hits. So the numpy-1.26.4 override that CRASHED 0.7.2 is code-safe
  on 0.8.5.
- **⚠️ dev-pod build instruction — do NOT naive-install.** v0.8.5's pyproject DECLARES conservative bounds
  (`numpy>=1.22.4,<1.24`, `anndata>=0.9.0,<0.10.0`, `torch>1.8.0,<=2.0.1`). A plain `pip install cpa-tools==0.8.5`
  would pull numpy `<1.24` (which HAS `np.int`) and conflict with numba 0.65 / torch 2.6. REBUILD
  `requirements.cpa_env.lock` the SAME WAY as the committed 0.7.2 one — `uv pip sync … --index-strategy
  unsafe-best-match` forcing **numpy 1.26.4 + anndata 0.10.9 + torch 2.6.0+cu124** — just with `cpa-tools==0.8.5`.
  That override machinery is already proven on the 0.7.2 env; 0.8.5 being numpy-clean makes the numpy override safe.
- **Residual to RUN-verify (why "0.8.5 = no problem" is NOT assertable without the gate):** 0.8.5's code must tolerate
  the FORCED anndata 0.10.9 (declared bound `<0.10.0`; the 0.7.2 stack proved 0.7.2 tolerates 0.10.9, 0.8.5 is
  adjacent but unverified) — the Phase-0 RUN-gate confirms it.

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
- `cpa_env`: uv-managed CPython 3.10 + torch 2.6.0+cu124 + the 2023-era cpa-tools 0.7.2 stack (see anchor +
  runtime_notes: tkinter, rdkit-pypi exclusion, scvi/jax/anndata pins, MPLBACKEND=Agg).
- Owner picks provider/instance; the verified reference is **RunPod A100 80GB, cu124, uv 0.9.0, driver 550.127.05**.

---

## Config-field mapping (once owner confirms)

| decision | config field / artifact | value | source / remaining |
|---|---|---|---|
| #1 | `baselines.gears.revision` (+ dep lock) | `cell-gears==0.1.2` + SHA | **committed lock (verified)**; clarify `package` (import `gears` vs pip `cell-gears`); pod-verify wheel |
| #1 | GEARS hyperparams (worker + dep lock) | master defaults above as REFERENCE | **pod-verify against installed 0.1.2 wheel**; worker pins explicit values |
| #2 | `go_resource_manifest.json` | url `datafile/6153417`, MD5 `77c9af0c…` | **license + GO version + SHA-256 = pod** |
| #3 | `baselines.cpa.revision` (+ dep lock) | **`cpa-tools==0.8.5`** (recommended; NOT 0.7.2 — np.int crash) | earliest tagged w/ both fixes + minimal stack delta; **dev-pod Phase-0 RUN-gate confirms** |
| #3 | CPA combo config (worker + dep lock) | **POD-VERIFY (version-matched)** | 0.8.8 research applies only if 0.8.x chosen; 0.7.2 config = read from 0.7.2 |
| #4 | `baselines.gears.approximation_bias_report_sha256` | Task-2.2 report SHA (metric above) | run on pod, non-sealed |
| #4 | `baselines.cpa.approximation_bias_report_sha256` | **null** (exact representation) | none |
| #5 | env locks / provider | 2 verified envs, both cu124 | committed lock; **owner picks provider** |
| — | `baselines.{gears,cpa}.environment_status` | promote from verified lock, re-verify on pod | pod fresh-sync |
| — | `regimes.power_status` | established by Task-2.1 detectable-effect report | pod (Phase 2, not a #1–5 decision) |

**⚑ Reminder:** confirmed values → write config (fills null blockers → **new `config_sha256` = new run identity**) →
commit finalized config → **THEN** regenerate the two evidence reports (else `config_sha256` re-drifts). See the plan's
Global ⚑ constraint and Task 2.1–2.3.
