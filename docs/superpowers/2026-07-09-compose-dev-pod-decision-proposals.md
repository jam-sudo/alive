# COMPOSE dev-pod — open-decision proposals (#1–#5)

> **STATUS: PROPOSED — pending owner confirmation. NOT yet encoded into `configs/compose_k562_v1_phase2.yaml`
> or any manifest.** These values will (after owner confirmation) be pinned into the config that binds the
> COMPOSE seal's activation lineage, so every pin here is a governance-consequential reproducibility decision.
> Nothing in this file changes `config_sha256` until the owner confirms and the values are written per the
> dev-pod plan's ⚑ ordering (config finalize → new run identity → THEN regenerate evidence).
>
> **역할:** the `docs/superpowers/plans/2026-07-09-compose-dev-pod-real-workers.md` "Open decisions to settle
> BEFORE Phase 1" gate (#1–#5 = B-spec §7 open questions), researched with sources. Sourced facts carry a URL +
> verbatim quote; anything unverifiable is marked **POD-VERIFY** — no value was guessed.
> **Method:** two grounded web-research passes (GEARS: `snap-stanford/GEARS` master `f374e43`; CPA:
> `theislab/cpa` main HEAD == 0.8.8) with a fabrication ban; #4 designed against the ALIVE code.

---

## #1 — GEARS published config + revision

**Package / revision (→ `baselines.gears.revision` + dependency lock).**
- PyPI **install name = `cell-gears`** (import name = `gears`). ⚠️ config currently reads `baselines.gears.package: gears`
  — that is the *import* name; the *pip* name is `cell-gears`. Recommend pinning `revision: "cell-gears==0.1.2"`
  and clarifying the package field.
  - Source: `https://pypi.org/pypi/cell-gears/json` — `"name": "cell-gears"`, `"latest version: 0.1.2"` (uploaded 2023-12-13).
  - In-repo confirm: `https://raw.githubusercontent.com/snap-stanford/GEARS/master/gears/version.py` — `__version__ = '0.1.2'`.
- **No GitHub release tag exists** for 0.1.2 (GitHub `/releases/latest` = Not Found). Current `master` SHA
  `f374e43e197b295016d80395d7a54ddb81cc6769` (2025-02-01). → pin `cell-gears==0.1.2` **and** record the SHA in the
  dependency lock; the PyPI wheel and master are not tag-guaranteed identical → **POD-VERIFY** the installed bytes.

**Published default training config** (dataset-agnostic; `gears.py` signatures + README tutorial). **No K562-specific
override exists** — Norman is loaded via `pert_data.load('norman')` under the same defaults (**POD-VERIFY** if a
K562-tuned config was ever expected — it is not published).
- `epochs = 20` — `gears/gears.py:478` `"def train(self, epochs = 20,"` (README: `"gears_model.train(epochs = 20)"`)
- `lr = 1e-3` (`:479`), `weight_decay = 5e-4` (`:480`), optimizer **Adam** (`:505`), scheduler **StepLR(step_size=1, gamma=0.5)** (`:506`)
- `hidden_size = 64` (`:122`, README), `num_go_gnn_layers = 1` (`:123`), `num_gene_gnn_layers = 1` (`:124`),
  `decoder_hidden_size = 16` (`:125`), `num_similar_genes_go_graph = 20` / `..._co_express_graph = 20` (`:126-127`),
  `coexpress_threshold = 0.4` (`:128`), `uncertainty = False` (`:129`), `direction_lambda = 1e-1` (`:131`)
- `batch_size = 32`, `test_batch_size = 128` — `get_dataloader()` args (README), **not** `train()` args; `predict()`
  hardcodes a 300-cell loader (`:349`).
- **Early stopping:** no patience; best checkpoint = min validation `mse_de`, full `epochs` run (`:571-573`).
- **Seeds:** module-level `torch.manual_seed(0)` (`:18`); data-split seed is separate (`prepare_split(seed=1)`, README).
  `train()` has no seed arg.
- Confidence: **HIGH** (every value confirmed in raw source AND/OR README). Source root:
  `https://raw.githubusercontent.com/snap-stanford/GEARS/master/gears/gears.py`.

## #2 — GEARS GO-graph / gene2go source (→ `go_resource_manifest.json`)

Only the **GO `gene2go` pickle is downloaded**; the co-expression graph is computed from the training AnnData
(`coexpress_threshold=0.4`), not fetched.
- Primary resource: `gene2go.pkl` — `https://dataverse.harvard.edu/api/access/datafile/6153417` (Harvard Dataverse).
  - `pertdata.py:92-94` `"server_path = 'https://dataverse.harvard.edu/api/access/datafile/6153417'"` → `gene2go_all.pkl`.
  - File API `https://dataverse.harvard.edu/api/files/6153417`: label `gene2go.pkl`, **MD5 `77c9af0c61c30ea4d7a85680f4d122dc`**,
    size `9462558` bytes, published `2022-03-24`, `restricted: false`.
- Companion (perturbable-gene universe): `essential_all_data_pert_genes.pkl` — `datafile/6934320` (`pertdata.py:119`).
- Underlying DB identity: Gene Ontology Consortium (GEARS Methods cite GO, Nucleic Acids Res. 2004).
- **GAPS (owner/pod):**
  - **License = POD-VERIFY** — not stated in code or the Dataverse file API. Upstream GO is generally CC BY 4.0 but
    the redistributed pickle's terms were not confirmed. The manifest's `license` field needs the Dataverse parent
    dataset's terms — **owner should resolve/accept before acquisition.**
  - **GO version = POD-VERIFY** — no release string anywhere; only the 2022-03-24 file date is known.
  - **SHA-256 = POD-VERIFY** — Dataverse gives only MD5; the manifest wants SHA-256 → compute over the acquired bytes
    on the pod (and cross-check the MD5 above to confirm identity).

## #3 — CPA (cpa-tools) setup + revision

**Package / revision (→ `baselines.cpa.revision` + dependency lock).**
- `pip install cpa-tools`, **version 0.8.8** (PyPI + `pyproject.toml`). **No `v0.8.8` git tag** (latest tag = v0.8.5,
  `7cda37e`) → pin `cpa-tools==0.8.8` **and** record SHA `fbd7c0250edc23eff003a10c99655579c53afd63` (main HEAD == 0.8.8).
  - Source: `https://pypi.org/project/cpa-tools/` + `https://raw.githubusercontent.com/theislab/cpa/main/pyproject.toml`.

**Published default combo config** — the official Norman-2019 combinatorial tutorial (readthedocs + raw `.ipynb`,
byte-identical). API splits `model_params`(→`cpa.CPA`) and `trainer_params`(→`plan_kwargs`).
- model_params: `n_latent=32`, `recon_loss="nb"`, `doser_type="linear"`, encoder `256×4`, decoder `256×2`,
  `dropout_rate_encoder=0.2`, `variational=False`, `seed=8206`.
- trainer_params: `lr=1e-4`, `wd=3.217e-06`, `n_epochs_adv_warmup=50`, `n_epochs_pretrain_ae=10`, `adv_steps=3`,
  `reg_adv=10.0`, `pen_adv=20.0`, `adv_lr=1e-4`, `n_hidden_adv=128`, `n_layers_adv=2`, `dropout_rate_adv=0.3`,
  `step_size_lr=25`, `adv_loss="cce"`, `gradient_clip_value=5.0`.
- `model.train(max_epochs=2000, batch_size=2048, early_stopping_patience=5, check_val_every_n_epoch=5)`.
- `setup_anndata(..., is_count_data=True, max_comb_len=2)`; latent composition `z=z_basal+z_pert+z_covs` → unseen A+B
  from single-gene embeddings.
- Confidence: **HIGH** for the tutorial combo values (two independent fetches identical). Library `_module.py` defaults
  (n_latent=128, doser "logsigm") DIFFER — use the tutorial values; **POD-VERIFY** `_module.py` verbatim in the wheel.
  - Source: `https://cpa-tools.readthedocs.io/en/latest/tutorials/Norman.html`.
- Output confirms `cpa.prediction_representation = cell_raw_counts`: per-cell autoencoder, NB likelihood on raw counts.

## #4 — GEARS pseudobulk-approximation bias metric (→ `baselines.gears.approximation_bias_report_sha256`)

**Designed against the ALIVE code (not external research); pre-registered per the plan's Task-2.2 open_item.**

Grounding: `RESPONSE_TRANSFORM = ("normalize_total_median", "log1p")` (`response.py:45`) is **nonlinear**. In
`apply_response_projection` (`fit_role.py:924`) the ONLY difference between the two representations is the input:
- `raw_pseudobulk_approximation`: `operator_input = native.mean(axis=0)` → `PCA(log1p(normalize(mean(raw))))`
- `cell_raw_counts`: per-cell → caller means → `mean_i[PCA(log1p(normalize(raw_i)))]`
Because `log1p` is concave, `log1p(mean(x)) ≥ mean(log1p(x))` (Jensen) → the pseudobulk path is a **one-signed
systematic bias** relative to per-cell. That gap is exactly "the bias introduced by `raw_pseudobulk_approximation`
vs per-cell." GEARS emits a mean/pseudobulk vector (`predict()` `np.mean(...,axis=0)` over 300 control cells), so
consuming it via the pseudobulk path is faithful — this metric quantifies the handicap that faithfulness imposes.

**Metric (non-sealed roles ONLY: control · singles · combo_calibration; model-independent — no GEARS fit needed):**
For each non-sealed group with real cells, using the frozen `response_projection` block:
- `δ_pb = apply_response_projection(mean(raw over the group)) − ctrl_proj`  (pseudobulk path)
- `δ_pc = mean_i[apply_response_projection(raw_i)] − ctrl_proj`  (per-cell path)
- bias `b = δ_pb − δ_pc` (a `pca_dim` vector).

Report (canonical JSON):
- **directional (systematic) bias:** `mean_g b` per dim and `‖mean_g b‖` — the component that does NOT cancel across
  perturbations (the key number, since the Jensen gap is one-signed).
- **relative magnitude:** median and max over groups of `‖b‖ / ‖δ_pc‖` (fraction of response displacement due to the
  approximation).
- **per-dim profile** of `mean_g b` (does the bias concentrate in a few PCA dims?).
- **provenance:** frozen projection `gene_order_sha256`/pca digest, non-sealed role manifest hash, group roster, git SHA.

Properties: computed from the representation transform + real **non-sealed** cells only → **cannot read a sealed
outcome**; it is an activation *requirement* (a pipeline property), **not a tunable / not outcome-selected**;
pre-registering the definition before any sealed access prevents it being shaped to explain a result. Used in the
sealed comparison to read GEARS's known representation handicap. CPA (`cell_raw_counts`) is exact → its
`approximation_bias_report_sha256` stays **null** by design.

## #5 — Dev-pod provider/instance (OWNER decision)

Prior pattern: RunPod A100. **New constraint surfaced by #1/#3 research — the two locked envs likely need different
torch/CUDA:**
- CPA (`cpa-tools` 0.8.8): **Python `<3.11, >=3.9`**, **torch `>1.8.0,<=2.0.1`**, scvi-tools `<1.0.0`, lightning
  `>=2.2.0,<2.3.0` → `cpa_env` = Python 3.9/3.10 + torch 2.0.1 (cu117/cu118). **CANNOT reuse the prior cu124 pattern
  (torch 2.4+).**
- GEARS (`cell-gears` 0.1.2): needs PyTorch Geometric (PyG must be installed before GEARS) → `gears_env` torch/CUDA
  must match a PyG build; **POD-VERIFY** the exact torch/PyG/CUDA combination.
- Implication: two distinct locked envs with possibly different CUDA; the A100 image/driver must support the older
  CUDA that torch 2.0.1 needs. **Owner picks provider/instance with this in mind.**

---

## Config-field mapping (once owner confirms)

| decision | config field / artifact | proposed value | remaining |
|---|---|---|---|
| #1 | `baselines.gears.revision` (+ dep lock) | `cell-gears==0.1.2` + SHA `f374e43…` | verify wheel==master on pod; clarify `package` (import `gears` vs pip `cell-gears`) |
| #1 | GEARS hyperparams (worker + dep lock) | the published defaults above | none (sourced) |
| #2 | `go_resource_manifest.json` | url `datafile/6153417`, MD5 `77c9af0c…`, 2022-03-24 | **license + GO version + SHA-256 = pod** |
| #3 | `baselines.cpa.revision` (+ dep lock) | `cpa-tools==0.8.8` + SHA `fbd7c02…` | verify `_module.py` on pod |
| #3 | CPA combo config (worker + dep lock) | tutorial `model_params`/`trainer_params` above | none (sourced) |
| #4 | `baselines.gears.approximation_bias_report_sha256` | Task-2.2 report SHA (metric above) | run on pod, non-sealed |
| #4 | `baselines.cpa.approximation_bias_report_sha256` | **null** (exact representation) | none |
| #5 | env locks / provider | two envs, distinct torch/CUDA | **owner picks provider** |
| — | `baselines.{gears,cpa}.environment_status` | pinned after fresh-sync (Phase 0) | pod |
| — | `regimes.power_status` | established by Task-2.1 detectable-effect report | pod (Phase 2, not a #1–5 decision) |

**⚑ Reminder:** confirmed values → write config (fills null blockers → **new `config_sha256` = new run identity**) →
commit finalized config → **THEN** regenerate the two evidence reports (else `config_sha256` re-drifts). See the plan's
Global ⚑ constraint and Task 2.1–2.3.
