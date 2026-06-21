# ALIVE — Virtual Cell

## Mission

ALIVE is a staged virtual-cell research project. The current MVP is a **conditional
population-transition surrogate** that predicts the distribution of transcriptomic states after a
single-gene CRISPRi knockdown in a new cellular context.

The benchmark is:

```text
K562_essential perturbations + controls (day 6)  → training and validation
RPE1 controls + target identity (day 7)          → inference context
RPE1 perturbed outcomes (day 7)                  → sealed external test only
```

Model target:

$$p(X_{post}\mid P_{control}, A, C)$$

- $P_{control}$ is the control-cell population, not a paired individual cell.
- $A$ is the CRISPRi target.
- $C$ is context derived from the control population and declared metadata.
- $X_{post}$ is a post-perturbation cell-population distribution.

The long-term goal is a causal virtual-cell world model. Do not describe this MVP as mechanistic,
causal, temporally resolved, or clinically predictive without separate evidence.

## Sources of truth

- Vision and scientific principles: @virtual-cell-model-blueprint.md
- Evidence and literature: @virtual-cell-research-report.md
- Current scope and milestones: @virtual-cell-project-plan.md
- Exact split, target universe, preprocessing, and metrics: the versioned protocol/config files

When sources conflict, this file's Scientific invariants and Split contract govern safety and
validity; the project plan governs milestones only when consistent with them. Executable protocols
must conform to both. Report every conflict; never resolve it silently. Do not invent dataset facts,
citations, or metric definitions.

## Current scope

- **In scope:** single-gene CRISPRi; scRNA-seq; one endpoint per screen; shared essential-gene
  targets; K562→RPE1 cross-dataset context transfer; population-distribution prediction.
- **Out of scope without explicit approval:** drugs, combinations, time-series dynamics,
  protein/ATAC/spatial modalities, inverse design, in vivo claims, therapeutic recommendations.
- K562→RPE1 is **not** a clean cell-type split: cell line, experiment, batch, and endpoint differ.
  Describe it as cross-dataset context transfer.

## Scientific invariants

1. **Baseline first.** Build the split manifest, evaluation harness, and registered baselines before
   training or tuning a learned transition model.
2. **Seal the external test.** RPE1 perturbed outcomes may be opened only by evaluation code after
   model selection is frozen. RPE1 controls are allowed as inference context.
3. **Fit on training data only.** Normalization parameters, feature selection, signal filters,
   embeddings, calibration, and hyperparameters must not use RPE1 perturbed outcomes.
4. **No outcome-selected test set.** Define the scored target universe from dataset metadata and
   target intersection, independent of RPE1 response strength. Null/weak/strong RPE1 effects may be
   reported only as post-hoc strata; never use them to decide what is scored.
5. **Match the claim to the split.** The context-transfer benchmark uses overlapping CRISPRi targets
   between K562 and RPE1. A separate, explicitly named split is required for unseen-target claims.
6. **Model distributions, retain means.** The final model must represent population heterogeneity.
   Pseudobulk and means remain required for baselines, diagnostics, DES/PDS, and sanity checks.
7. **No single-metric wins.** Report the preregistered primary metric, PDS, DES, distributional
   metrics, effect sizes, and perturbation-level bootstrap confidence intervals. MAE/Pearson are
   supporting metrics only.
8. **Interrogate systematic variation.** Run Systema-style and mean-collapse checks. Treat strong
   performance as suspect until batch, cell cycle, target-panel bias, and common treatment shifts
   have been examined.
9. **Do not overclaim heterogeneity.** Use “responder/non-responder” only after an operational
   definition is registered. Cell-level variation may reflect sampling, cell cycle, guide efficacy,
   technical noise, or selection.
10. **Uncertainty needs a method.** Do not claim aleatoric/epistemic separation from raw model
    variance. Specify the estimator (for example ensembles/bootstrap), calibration set, and coverage
    metric.

## Split contract

- Use the exact processed assets `K562_essential` (day 6) and `rpe1` (day 7). Do not silently
  substitute `K562_gwps` (genome-wide, day 8).
- The context-transfer test requires shared perturbation targets across K562 and RPE1.
- Cell barcodes never overlap splits. Keep biological replicate/channel groups intact whenever the
  metadata supports it.
- Training and validation come from K562 under a versioned, documented split. RPE1 perturbed cells
  are never a tuning or early-stopping set.
- A leakage test must verify provenance, fitted-preprocessor boundaries, target-universe creation,
  and absence of RPE1 outcome access—not merely barcode overlap.
- Record known confounding: cell identity cannot be separated from experiment and day in this
  two-screen benchmark.

## Data contract

- Source: Replogle et al. 2022 processed Perturb-seq AnnData. Prefer the required processed
  essential-screen assets; do not download the full SRA or genome-wide collection by default.
- Standard container: AnnData (`.h5ad`); preserve raw counts and all provenance metadata.
- Keep expression sparse and use on-disk/chunked access. Densify only bounded minibatches.
- Do not hardcode `200–500 cells/perturbation` or `1000 UMI/cell` as universal exclusion rules.
  Profile the actual distributions, preregister thresholds, and report sensitivity to them.
- Never commit raw/processed data, checkpoints, credentials, or identifiable donor information.
- Confirm download size, destination, and license before any large transfer.

## Registered baselines

Implement and retain at least:

1. no-change / RPE1-control prediction;
2. transferred K562 perturbation effect or perturbation-mean baseline;
3. additive or latent-additive baseline;
4. linear model, including an ID-only variant where appropriate.

ID-only models are valid baselines for context transfer. They may not support a claim of unseen
perturbation generalization. Biological gene/pathway/network encoders require an ablation against
the ID-only baseline.

## Evaluation and success

- Freeze a versioned evaluation protocol before model comparison.
- Select one primary metric aligned with perturbation-specific utility; define secondary metrics and
  directionality explicitly. Metric implementations require toy-data tests with known answers.
- Compare against the **strongest eligible baseline**, not an average baseline score.
- A success claim requires a positive preregistered effect with a perturbation-level bootstrap 95%
  CI excluding zero on the primary metric, with no preregistered material regression on secondary
  biological/distributional metrics.
- Report per-target results, weak/null-effect behavior, seed variability, self-prediction/noise
  ceilings where estimable, and all failed runs.
- Independent experimental hit-rate validation is a later milestone, not an MVP result.

## Repository conventions

```text
src/data/        ingestion, QC, preprocessing, manifests
src/baselines/   registered baselines
src/models/      encoders, conditional transition, decoder
src/eval/        metrics, bootstrap, calibration, reports
configs/         one immutable experiment configuration per run
tests/           unit, leakage, metric, and reproducibility tests
notebooks/       exploration only; no production logic
results/         metrics, figures, resolved config, metadata
data/            gitignored; tracked only through approved data-version metadata
```

- Python 3.11+; type hints for public APIs; NumPy-style public docstrings; Ruff formatting at 100
  columns. Prefer `uv` with `pyproject.toml` and `uv.lock`; do not maintain competing environments.
- No hardcoded paths, splits, feature lists, thresholds, seeds, or hyperparameters in source code.
- Every run records resolved config, dataset/split version, seed, git SHA, dependency lock hash,
  device, precision, metrics, and checkpoint metadata.
- Production logic belongs in `src/`; notebooks call library functions.
- Do not invent commands. Read `pyproject.toml`, `Makefile`, or `README.md` for current entrypoints.
  When stable commands exist, document and test them here.

## Verification before completion

For every relevant change:

1. run targeted unit tests, then the applicable integration tests;
2. run Ruff and type checks configured by the repository;
3. run leakage and metric-sanity tests when data/evaluation code changes;
4. verify that a constant predictor, shuffled labels, and random outputs behave as expected;
5. report exact commands run, results, and checks that could not be completed.

Use hooks/CI—not prose alone—to block data commits, enforce formatting, and require leakage tests
before official training/evaluation runs.

## Compute and execution environments

### MacBook Pro — Phase 0 and mini-dataset validation

- Apple M5 Pro; 24 GB unified memory; macOS/arm64; PyTorch MPS where supported.
- This is the only local development machine. Assume no local CUDA hardware.
- Use it for repository setup, implementation, unit tests, bounded data inspection, CPU/MPS smoke
  tests, mini-dataset end-to-end runs, documentation, and independent reproducibility checks.
- Do not place the full source dataset on the MacBook by default. Keep mini fixtures sparse and small
  enough to run on CPU as well as MPS.
- Keep device selection explicit (`cpu`, `mps`, `cuda`). Do not assume identical kernels,
  determinism, precision support, or performance across MPS and CUDA.
- Tests must have a small CPU fixture. MPS-specific failures must be reported, not hidden by silent
  CPU fallback.

### A100 cloud — Phase 1 data preparation and full-scale execution

- The rented A100 environment is the single cloud environment for original-data download,
  integrity checks, slicing, preprocessing, mini-dataset creation, full-data training, and
  evaluation. Do not provision a separate CPU-only cloud instance for this workflow.
- Create the mini dataset from a versioned manifest without consulting RPE1 outcome strength. It
  must preserve controls, shared targets, provenance, batch/replicate metadata, and split roles.
- Transfer only the mini dataset, manifest, dataset card, and checksums to the MacBook.
- Mini and full runs must use the same production code. Configuration may change paths, scale,
  batch size, precision, and device; it must not create a separate mini-only algorithm.
- Begin full-data GPU training/evaluation only after the mini pipeline passes
  leakage tests, metric sanity, baseline reproducibility, checkpoint-resume, and end-to-end report
  generation.
- Every cloud run records instance/GPU type, image or environment lock, storage inputs, dataset and
  split hashes, git SHA, resolved config, wall time, and cost where available.
- Cloud artifacts are written to versioned object storage. Never rely on an instance's ephemeral
  disk as the sole copy of data, manifests, checkpoints, or results.

## Working style

- Inspect before editing. For multi-file or scientifically consequential changes, write a short plan
  and identify affected invariants first.
- Preserve unrelated user changes. Do not rewrite established protocols silently.
- Prefer the smallest experiment that can falsify the current hypothesis.
- When results look good, first test leakage, batch confounding, mean collapse, metric gaming, and
  seed sensitivity.
- State uncertainty and evidence level explicitly. Preprints and vendor claims are not ground truth.
- If a rule blocks scientifically valid work, stop and report the conflict rather than bypassing it.
