# CARTOGRAPHER Trust-Gate — A100 Real-Run Runbook (`TG-K562-v1`)

> **Scope.** Take a bare A100 instance to a real, decisive K562 scientific run.
> Phases A→E. Two gates (C: ESM smoke, D: mini validation) must pass before the
> full run. **One irreversible step: `evaluate-once`** (opens the sealed cohort
> exactly once). Governance: `CLAUDE.md` §§7, 11, 13, 14.2; spec
> `docs/superpowers/specs/2026-06-20-cartographer-design.md` §§3.2, 4.3, 11.3.
>
> Configs: full = `configs/cartographer_trust_gate_k562_v1.yaml`; mini (plumbing
> validation only) = `configs/cartographer_trust_gate_k562_mini.yaml`.

```
A. code+env     get code to A100 -> uv sync --extra features -> tests green
B. data         acquire K562 essential .h5ad -> inspect -> fetch sequences -> write data-card
C. ESM smoke    real ESM-2 forward on real proteins                          [GATE]
D. mini run     mini subset -> prepare..calibrate with REAL encoder (no seal) [GATE]
E. full run     prepare..futility -> {STOPPED: calibrate,report | CONTINUE: calibrate, evaluate-once, report}
```

Pipeline order (each post-`prepare` command takes `--run-id`):
`prepare → fit → develop → futility → calibrate → evaluate-once → report`.

---

## Phase A — code + environment

### Step 0 — get the code onto the A100
There is currently **no git remote**. Either:
- **Remote (recommended; lets you `git pull` toolkit updates):**
  - local Mac: `gh repo create alive --private --source=. --remote=origin --push`
    (or create an empty private repo and `git remote add origin <URL> && git push -u origin main`)
  - A100: `git clone <URL> alive && cd alive`
- **rsync (no remote):**
  `rsync -av --exclude .git/sdd --exclude artifacts --exclude .venv /path/ALIVE/ user@a100:~/alive/`

Verify the A100 has the expected code:
```bash
cd ~/alive && git log --oneline -1   # expect the latest main (real-run toolkit merged)
```

### Step 1 — environment
```bash
uv sync --extra features    # torch + transformers + fair-esm (Python 3.11–3.12)
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
uv run pytest -q            # build sanity (the torch-only ESM test now runs instead of skipping)
uv run ruff check src tests
```
Do not continue until `torch.cuda.is_available()` is `True` and the suite is green.

---

## Phase B — data + data-card

### Step 2 — acquire the K562 essential AnnData
Obtain the **Replogle et al. 2022 K562 _essential_ (day-6)** processed Perturb-seq
`.h5ad` (e.g. via scPerturb / Zenodo or the Weissman-lab distribution). **Confirm
the exact artifact, version, and license before download (§7).** Preserve raw
counts; read sparse/backed — never globally densify (§7). Note the provenance
string you will record as `raw_data_uri` (and keep the file's SHA-256 — the run
binds it). Place it e.g. at `data/k562_essential.h5ad`.

> Do **not** silently substitute `K562_gwps` for `K562_essential` (§7).

### Step 3 — inspect (choose data-card fields + confirm feasibility)
```bash
# discover obs columns
uv run python scripts/inspect_h5ad.py --h5ad data/k562_essential.h5ad
# full profile once you know the perturbation column + control label
uv run python scripts/inspect_h5ad.py \
  --h5ad data/k562_essential.h5ad \
  --config configs/cartographer_trust_gate_k562_v1.yaml \
  --perturbation-key <gene_col> --control-value <control_label>
```
Read off: the per-perturbation cell-count distribution, how many perturbations
clear `min_cells` (64), and the **four-way feasibility** line — the sealed slice
(15% of eligible) must clear `minimum_sealed_perturbations` (200), i.e. you need
**≥ 1334 eligible** perturbations. Note whether the gene IDs are **symbols** or
**Ensembl IDs** (needed in Step 4). The script prints a data-card stub.

### Step 4 — build the gene→protein-sequence JSON
```bash
uv run python scripts/fetch_sequences.py \
  --h5ad data/k562_essential.h5ad \
  --perturbation-key <gene_col> --control-value <control_label> \
  --id-type symbol \            # or: ensembl
  --out data/k562_gene_sequences.json \
  --provenance-out data/k562_sequence_provenance.json
```
This applies the **exactly-one** rule (1 usable / 0 missing / >1 ambiguous) and
writes a provenance report with `sequence_source` (UniProt release) and
`id_mapping_version`. **Verify coverage:** re-run `inspect_h5ad.py` mentally
against the usable set — `(usable sequence) AND (≥ min_cells)` is the truly
eligible set, and its sealed slice must still clear 200 (spec §3.2:
eligibility-before-split; missing/ambiguous are excluded *before* the split, not
silently skipped after). Spot-check a few sequences against UniProt.

### Step 5 — write the full data-card
`data/k562_data_card.json` (fill from Steps 2–4):
```json
{
  "h5ad": "data/k562_essential.h5ad",
  "sequences": "data/k562_gene_sequences.json",
  "perturbation_key": "<gene_col>",
  "control_value": "<control_label>",
  "gene_id_key": null,
  "counts_layer": null,
  "raw_data_uri": "<expression provenance string>",
  "sequence_source": "<from k562_sequence_provenance.json>",
  "id_mapping_version": "<from k562_sequence_provenance.json>"
}
```

---

## Phase C — Gate C: ESM real-forward smoke test (spec §4.3 / §11.3)

The **sole remaining real-run precondition.** Verify the real ESM-2 loads on the
GPU and produces finite, 1280-dim embeddings under the config batching policy:
```bash
uv run python scripts/esm_smoke.py \
  --config configs/cartographer_trust_gate_k562_v1.yaml \
  --sequences data/k562_gene_sequences.json --n 16
```
Require: `SMOKE OK` (dim 1280, all finite) and a sane GPU peak-memory line. If it
fails, **do not** build the full feature bank — fix the encoder/env first.

---

## Phase D — Gate D: mini end-to-end validation (§14.2)

Build a mini and run it through `prepare → calibrate` with the **real encoder**
and the **mini config** (validation only — no scientific verdict):
```bash
uv run python scripts/make_mini.py \
  --data-card data/k562_data_card.json \
  --config configs/cartographer_trust_gate_k562_mini.yaml \
  --out-dir data/mini --n-perturbations 40 --seed 20260621

RUN_ID=$(uv run alive cartographer prepare \
  --config configs/cartographer_trust_gate_k562_mini.yaml \
  --data-card data/mini/mini_data_card.json)            # REAL encoder (no --mock-encoder)
echo "mini run_id=$RUN_ID"
uv run alive cartographer fit       --run-id "$RUN_ID"
uv run alive cartographer develop   --run-id "$RUN_ID"
uv run alive cartographer futility  --run-id "$RUN_ID"
uv run alive cartographer calibrate --run-id "$RUN_ID"
uv run alive cartographer report    --run-id "$RUN_ID"   # STOP here — do NOT evaluate-once on the mini
```
Confirm: the run completes, `report` emits, and the integrity machinery behaves
(seal stays closed; provenance ledger written). Then run the safety suites:
```bash
uv run pytest tests/alive -k "leakage or provenance or ledger or resume or tamper" -q
```
Only proceed to the full run when the mini pipeline + these tests pass (§14.2).

---

## Phase E — full run (the decisive scientific run)

```bash
RUN_ID=$(uv run alive cartographer prepare \
  --config configs/cartographer_trust_gate_k562_v1.yaml \
  --data-card data/k562_data_card.json)                 # REAL encoder — NEVER --mock-encoder
echo "FULL run_id=$RUN_ID"
uv run alive cartographer fit       --run-id "$RUN_ID"
uv run alive cartographer develop   --run-id "$RUN_ID"
uv run alive cartographer futility  --run-id "$RUN_ID"
uv run alive cartographer calibrate --run-id "$RUN_ID"   # ships the conformal bound in EITHER branch
```

### Step 9 — branch on the futility status
`futility` wrote `<run_dir>/futility.json`.
- **`FUTILITY_STOPPED`** (terminal, not a negative verdict): you already ran
  `calibrate` (the deliverable). Finish:
  ```bash
  uv run alive cartographer report --run-id "$RUN_ID"     # scientific_verdict: null, seal closed
  ```
  Do **not** run `evaluate-once`.
- **`CONTINUE_CONFIRMATORY`**: open the seal **exactly once** (irreversible):
  ```bash
  uv run alive cartographer evaluate-once --run-id "$RUN_ID"   # prints the verdict
  uv run alive cartographer report        --run-id "$RUN_ID"
  ```
  Verdict ∈ {`GATE_WINS`, `NO_DISTINCT_WIN`, `CALIBRATION_FAILURE`,
  `INVALID_EVALUATION`}. Whatever it is, it is the result — keep it (§14, §10).

### Step 10 — persist + record provenance (§14.2)
```bash
uv run python scripts/record_cloud_provenance.py --run-id "$RUN_ID" \
  --instance-type <a100-...> --wall-seconds <N> --cost-usd <N> --notes "full K562 essential"
# copy the run dir OFF the ephemeral instance (do not let it be the only copy)
rsync -av artifacts/cartographer/"$RUN_ID"/ <durable-store>/"$RUN_ID"/
```

---

## Non-negotiables (read before Phase E)

- **Real encoder only** for science: never pass `--mock-encoder` to a scientific
  `prepare`. A config↔feature-bank encoder mismatch is fatal by design (P0-1).
- **The seal opens once.** `evaluate-once` is irreversible and only legal in the
  `CONTINUE_CONFIRMATORY` branch; a second call is refused; upstream stages lock
  after a terminal/sealed state (#4). Do not run it until fit/develop/calibrate
  are final.
- **Immutable run identity.** `run_id` binds config + data-card + raw-data +
  sequence-mapping hashes; `prepare` refuses to reuse a run dir. Re-staging the
  same data at a different path changes the run_id — keep paths stable.
- **Keep every outcome.** Futility-stopped, `NO_DISTINCT_WIN`, `CALIBRATION_FAILURE`,
  `INVALID_EVALUATION` are results — never delete, overwrite, or post-hoc retune
  thresholds (§10, §14).
- **`INVALID_EVALUATION`** means integrity/leakage/provenance failure, sealed
  `n < 200`, a non-finite metric, or a reliability-precondition failure — fix the
  cause and start a **new** run id; do not patch a sealed run.
```
