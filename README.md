# ALIVE — CARTOGRAPHER Trust-Gate MVP (`TG-K562-v1`, COMPLETE)

> **Status (2026-07-04).** `TG-K562-v1` is **COMPLETE** — the sealed evaluation was opened once and
> registered **`NO_DISTINCT_WIN`** (the conformal error bound was valid and retained, but the gate
> did **not** beat the comparator family). The active protocol is now **`COMPOSE-K562-v1`** (Norman
> K562 CRISPRa non-additive epistasis operator; ACTIVE 2026-06-30, A100 sealed confirmatory run
> pending). **This README documents the now-complete CARTOGRAPHER pipeline and its mechanics** — the
> `evaluate-once` seal described below has already been spent for `TG-K562-v1`. See `CLAUDE.md`#registry
> for the protocol registry.

A retrospective, leakage-controlled **trust-gate** for single-gene CRISPRi perturbation-response
prediction. Given a frozen base predictor, an error-aware gate ranks held-out K562 perturbations by
predicted recoverability and ships a **calibrated scalar prediction-error bound**. The pipeline is
preregistered end-to-end: an outcome-independent split, a single audited access to the sealed
evaluation cohort, a futility stop rule, and one authoritative verdict.

> **Scope / non-claims.** This MVP is a conditional population-transition *surrogate*, not a
> mechanistic, causal, or clinically predictive model. The CLI here is exercised on **synthetic
> fixtures**; the real Replogle K562 run executes on the A100 (data is not included). See
> `CLAUDE.md` and `docs/superpowers/plans/2026-06-20-cartographer-mvp.md` for the full contract.

---

## Requirements & setup

- Python **3.11–3.12** (3.13+ not supported; scientific-stack wheels). [`uv`](https://docs.astral.sh/uv/) for env + lockfile.
- Install the locked environment:

```bash
uv sync
```

- Core deps (numpy/scipy/scikit-learn/anndata/scanpy/h5py/pyyaml) are installed by `uv sync`.
- The real **ESM-2** protein encoder is optional (only needed for the A100 feature-bank step):

```bash
uv sync --extra features   # adds torch, transformers, fair-esm
```

The numpy-only mock encoder is **opt-in only**, via the `--mock-encoder` flag on `prepare`
(synthetic/CI runs). A scientific run (no `--mock-encoder`) requires the real ESM-2: if the
`features` extras are absent, `prepare` fails loudly with a clear `error: …` — it **never silently
falls back** to the mock encoder (see `CLAUDE.md`#data-eval and design spec §4.2).

Run the test suite and linters:

```bash
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

---

## The CLI

The console entry point is `alive` (declared in `pyproject.toml`). Run it through `uv`:

```bash
uv run alive cartographer <command> [options]
```

All commands operate on a single **run**, identified by a `run_id` that is a deterministic composite
hash of the config **plus** the data card, the raw expression file, and the protein-sequence
mapping — so the same config on different data is a different run. Because the `run_id` binds the
declared data card (including its `h5ad` / `sequences` paths), staging the *same* data at a different
path or mount yields a *different* `run_id` and a separate run directory. Artifacts for a run live
under:

```
<artifacts-root>/cartographer/<run_id>/
```

`<artifacts-root>` defaults to `./artifacts` and can be overridden with the global
`--artifacts-root <dir>` flag (it may appear anywhere on the command line). `artifacts/` is
gitignored.

### Commands

| Command | Args | What it does |
|---|---|---|
| `prepare` | `--config <yaml> --data-card <json>` | Build the split manifest + feature bank + provenance ledger; **prints the `run_id`**. |
| `fit` | `--run-id <id>` | Fit the response space (PCA) + base predictor on controls + `base_train` only. |
| `develop` | `--run-id <id>` | OOF method development on `method_development` → `MethodLock` (+ `dev_errors`). |
| `futility` | `--run-id <id>` | Apply the preregistered futility rule → `FutilityDecision`. |
| `calibrate` | `--run-id <id>` | Build the split-conformal scalar error bound + PREDICT threshold → `ConformalArtifact`. |
| `evaluate-once` | `--run-id <id>` | The **single audited** sealed evaluation → prints the verdict. |
| `report` | `--run-id <id>` | Emit the locked report for the run's terminal state (writes `report.json` + `report.md`). |

### Pipeline order

```
prepare → fit → develop → futility → calibrate → evaluate-once → report
```

`prepare` prints the `run_id`; pass it to every later command. Example:

```bash
RUN_ID=$(uv run alive cartographer prepare \
  --config configs/cartographer_trust_gate_k562_v1.yaml \
  --data-card path/to/data_card.json)

uv run alive cartographer fit          --run-id "$RUN_ID"
uv run alive cartographer develop      --run-id "$RUN_ID"
uv run alive cartographer futility     --run-id "$RUN_ID"
uv run alive cartographer calibrate    --run-id "$RUN_ID"
uv run alive cartographer evaluate-once --run-id "$RUN_ID"   # only if CONTINUE_CONFIRMATORY
uv run alive cartographer report       --run-id "$RUN_ID"
```

### The `--data-card` file (`prepare`)

`prepare` reads a small JSON descriptor so no dataset paths are hardcoded in source:

```json
{
  "h5ad": "data/processed/k562_essential.h5ad",
  "sequences": "data/processed/gene_sequences.json",
  "perturbation_key": "gene",
  "control_value": "non-targeting",
  "gene_id_key": null,
  "counts_layer": null,
  "raw_data_uri": "replogle2022:K562_essential",
  "sequence_source": "uniprot-2024-01",
  "id_mapping_version": "ensembl-110"
}
```

| Key | Required | Meaning |
|---|---|---|
| `h5ad` | yes | Path to the Perturb-seq AnnData (`.h5ad`); read sparse, never globally densified. |
| `sequences` | yes | Path to a JSON map `gene → [protein_sequence, ...]` (the gene→protein mapping file). Exactly one sequence = usable; 0 = "missing"; >1 = "ambiguous" (both excluded before the split). |
| `perturbation_key` | yes | `obs` column holding each cell's perturbation/target label. |
| `control_value` | yes | The label in `perturbation_key` marking control (non-targeting) cells. |
| `gene_id_key` | no | `var` column for gene IDs (`null` → use `var_names`). |
| `counts_layer` | no | Layer holding counts (`null` → use `.X`). |
| `raw_data_uri` | no | Provenance string for the expression dataset recorded in the ledger. |
| `sequence_source` | **yes** | Protein-sequence database release recorded in the feature bank provenance (e.g. `"uniprot-2024-01"`). Distinct from the expression data URI — gives the protein-sequence mapping its own provenance. |
| `id_mapping_version` | **yes** | Gene↔protein ID mapping version recorded in the feature bank provenance (e.g. `"ensembl-110"`). Together with `sequence_source`, this is the canonical protein-sequence mapping provenance, separate from the expression source. |

For the exact synthetic fixture format (a runnable end-to-end example), see
`tests/alive/experiment/test_cli.py`, which constructs a tiny AnnData + sequence map + data card on
a temp path and drives the full command sequence.

---

## Integrity behaviors (enforced by the CLI)

- **`prepare` refuses to overwrite an existing run directory** (clean exit `2`). Because the
  `run_id` is the composite hash of config + data card + raw expression file + protein-sequence
  mapping, the same inputs always map to the same directory; runs are immutable.
- **`evaluate-once` refuses** (clean non-zero exit) unless the persisted `FutilityDecision.status`
  is `CONTINUE_CONFIRMATORY` — the sealed cohort never opens otherwise.
- **`calibrate` runs in either branch**, so a futility-stopped run still ships its conformal error
  bound (the primary deliverable when the confirmatory branch does not run).
- **The seal opens exactly once.** A second `evaluate-once` on the same `run_id` is refused
  (durable audit at `<run_dir>/audit.jsonl`).
- **`report` never recomputes** a decision or verdict — it reads persisted artifacts only.
- The `RunLedger` records the full config digest and every artifact checksum; a tampered artifact
  hash makes `evaluate-once` return `INVALID_EVALUATION`.
- Clean user errors (refusals, missing run, tamper-detected checksums) print a one-line
  `error: …` and exit `2` — no traceback.

## Outcomes

`evaluate-once` prints one **verdict**:

| Verdict | Meaning |
|---|---|
| `GATE_WINS` | Integrity + calibration valid; the gate beats every comparator (simultaneous AURC), shows no material AUGRC degradation, beats the residual-only ablation, and uses a positive feature weight. |
| `NO_DISTINCT_WIN` | Valid completed run, but the gate is not distinctly superior. The calibrated error bound is still retained if valid. |
| `CALIBRATION_FAILURE` | Integrity valid, but the scalar error-bound coverage misses the registered beta-binomial acceptance band. |
| `INVALID_EVALUATION` | Integrity/provenance/leakage failure, sealed cohort below the registered minimum, a non-finite metric, or a reliability-precondition failure. |

A **futility-stopped** run produces no scientific verdict: `report` emits the
`mode: "futility_stopped"` schema with `scientific_verdict: null` and sealed-access count `0`. A
**confirmatory** run emits the `mode: "confirmatory"` schema (risk-coverage curves, simultaneous
intervals, error-bound diagnostics, reliability, ablations, verdict evidence) with sealed-access
count `1`.

---

## Run artifacts (`<run_dir>/`)

```
config.snapshot.yaml   data_card.json   run_meta.json   ledger.json   audit.jsonl
manifest.json          feature_bank.npz + feature_bank.json
base.npz/json          base_predictor.npz/json
methodlock.*           dev_errors.npz   futility.json   conformal.json
result.json            report.json      report.md
```

Every artifact carries a checksum and is recorded in `ledger.json`. The MacBook runs scaffolding,
unit tests, and mini/synthetic end-to-end runs; the A100 runs raw-data preparation, the real ESM-2
feature bank, and the full-data fit → develop → futility → calibrate → sealed evaluation.

## Repository layout

```
src/alive/
  config.py          provenance.py        types.py        cli.py
  data/      replogle index · 4-way manifest · sealed outcome store · ESM-2 feature bank · response-space PCA
  metrics/   energy distance · AURC/AUGRC selective metrics
  base/      additive ridge base predictor + paired bootstrap ensemble
  gate/      R1 (feature-kNN) + R4 (local-residual) ECDF trust gate
  baselines/ preregistered UQ comparators (nearest-feature, ensemble disagreement, ridge/GBM error, residual-only)
  conformal/ split-conformal scalar error bound + beta-binomial acceptance band
  eval/      max-deviation bootstrap · verdict truth table · report
  experiment/ OOF development · staged real runner
configs/     committed experiment config (run-ID immutable)
tests/       unit, leakage, metric, reproducibility, integration tests
docs/        vision, research report, plan, design spec
```
