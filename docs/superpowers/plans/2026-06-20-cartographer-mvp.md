# CARTOGRAPHER Trust-Gate MVP Implementation Plan

> **Status update (2026-07-19): COMPLETE historical implementation plan.** `TG-K562-v1`의 seal은
> 이미 한 번 열렸고 verdict는 `NO_DISTINCT_WIN`이다. 아래 task를 재실행하거나 체크리스트를 current
> work queue로 사용하지 않는다.

> **For agentic workers:** REQUIRED SUB-SKILL: use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans`.
> Execute tasks in order. Do not open sealed outcomes, change registered analysis choices,
> or reinterpret a failed criterion after the decisive run.

**Original status:** implementation-ready specification
**Revision:** 2026-06-21, audit v2
**Scope:** K562 retrospective Trust-Gate MVP
**Non-claim:** this MVP is not an Active Cartographer and does not select wet-lab experiments.

---

## 1. Scientific question and claim boundary

### 1.1 Question

Given a frozen perturbation-response predictor, can an error-aware gate rank genuinely
held-out K562 perturbations by prediction error better than every preregistered uncertainty
baseline, while maintaining a calibrated scalar prediction-error bound?

The gate emits:

- `PREDICT`: the query falls below a threshold fixed without evaluation outcomes.
- `ABSTAIN`: prediction is returned for audit, but is not recommended for use.

`MEASURE` and adaptive acquisition are reserved for the separate Active Cartographer plan.

### 1.2 Primary endpoint

Selective AURC on one sealed K562 perturbation split. Risk is the measured, noise-audited
energy distance between the frozen base prediction and the observed perturbed population in
a train-fitted response space. Lower AURC is better.

For comparator `m`:

```text
delta_m = AURC_m - AURC_gate
```

The gate satisfies the primary endpoint only when the simultaneous one-sided family-wise
95% lower bound for **every** preregistered `delta_m` is greater than zero.

### 1.3 Explicit non-claims

- The scalar conformal error bound is not a distribution-valued prediction set.
- Local residual prediction is error-aware UQ, not causal identifiability.
- Random perturbation splits test interpolation/generalization within K562, not transfer to
  RPE1 or a new biological context.
- A translated control population is a deliberately simple frozen base model, not a virtual
  cell.
- Synthetic results validate software behavior only.

### 1.4 Regime scope, pre-registered expectation, and primary deliverable

The gate's only hypothesized advantage over a supervised error regressor given the same
features is an *epistemic* one: `R1` flags where the error regressor itself extrapolates. That
signal is concentrated under distribution shift and is weak in the in-distribution K562 regime
tested here, where held-out perturbations come from the same essential-gene pool.

- **Pre-registered expectation.** A flat development signal is expected to produce the
  operational status `FUTILITY_STOPPED`. Conditional on passing futility and completing the
  confirmatory branch, the modal scientific verdict is `NO_DISTINCT_WIN`. Neither outcome
  falsifies the recoverability hypothesis under shift; the gate's out-of-distribution edge is
  tested only by a separate shift-powered protocol. `GATE_WINS` here would be a strong,
  surprising positive.
- **Primary endpoint vs primary deliverable.** The selective-AURC family test (§1.2) remains the
  primary statistical *endpoint* when the confirmatory branch runs. Independently, the scalar
  conformal artifact (§6.1) is the primary shippable *deliverable* when the endpoint is negative
  or the preregistered futility rule stops the confirmatory branch. It is a
  calibration-derived **global error bound applicable to each eligible perturbation**, not a
  query-adaptive or perturbation-specific bound. A futility-stopped run makes no empirical
  sealed-coverage or routing claim.

---

## 2. Preregistered analysis contract

The decisive run consumes a committed YAML config. Changing any registered field creates a
new run ID and cannot replace the original result.

```yaml
experiment: cartographer_trust_gate_k562_v1
manifest_seed: 20260621
split_fractions:
  base_train: 0.45
  method_development: 0.25
  conformal_calibration: 0.15
  sealed_evaluation: 0.15

response_space:
  normalization: library_size_10000_log1p
  hvg_count: 2000
  pca_dims: 50
  cell_cap: 96
  min_cells: 64
  cell_sampling_repeats: 8
  energy_block_size: 256

perturbation_features:
  primary: esm2_t33_650M_UR50D_mean_pool
  standardize_on: base_train
  missing_policy: exclude_before_split

base_model:
  family: additive_ridge
  ridge_grid: [0.01, 0.1, 1.0, 10.0, 100.0]
  cv_folds: 5
  ensemble_members: 20

method_development:
  cv_folds: 5
  k_grid: [5, 10, 20, 40]
  feature_weight_grid: [0.25, 0.5, 0.75, 1.0]
  gbm_estimators_grid: [50, 100, 200]
  ridge_grid: [0.01, 0.1, 1.0, 10.0, 100.0]
  registered_seeds: [11, 23, 47, 71, 101]

decision:
  target_selection_coverage: 0.70
  conformal_alpha: 0.10
  minimum_sealed_perturbations: 200

inference:
  bootstrap_replicates: 10000
  family_confidence: 0.95
  secondary_augrc_noninferiority_margin: 0.02

futility:
  enabled: true
  comparators: [gbm_error, residual_only]
  minimum_relevant_delta: 0.01
  family_confidence: 0.90
  rule: stop_if_any_simultaneous_upper_bound_le_minimum
```

The config validator rejects unrecognized fields, invalid fractions, fewer than 2,000
bootstrap replicates in a scientific run, and a sealed cohort below the registered minimum.

---

## 3. Data, leakage, and provenance contracts

### 3.1 Four-way perturbation split

Split by unique perturbation ID, never by cell:

1. `base_train`: fit response-space transform and base predictor.
2. `method_development`: compute held-out base errors; tune and fit gate/baselines by fixed
   five-fold out-of-fold evaluation.
3. `conformal_calibration`: calibrate the scalar error bound and PREDICT threshold.
4. `sealed_evaluation`: first outcome access occurs inside `evaluate_sealed_once`.

The manifest is generated from eligible perturbation IDs and a registered seed before any
response-dependent filtering. Eligibility may use only schema validity, external-feature
availability, and cell count. All exclusions and counts are written to the manifest.

### 3.2 Structural sealing

Passing a full `oracle: list[np.ndarray]` to fitting code is forbidden. `OutcomeStore` exposes:

```python
class OutcomeStore(Protocol):
    def read_unsealed(self, perturbation_ids: Sequence[str]) -> dict[str, Population]: ...
    def evaluate_sealed_once(self, run_id: str, perturbation_ids: Sequence[str]) \
            -> dict[str, Population]: ...
```

The store knows the manifest, denies ordinary reads of sealed IDs, logs the first sealed
access, and refuses a second access for the same run ID. Unit tests use a spy store and fail
if `fit_base`, `develop_methods`, or `calibrate` touches a sealed outcome.

### 3.3 Required provenance

Every scientific result contains:

- raw-data URI and SHA-256;
- eligible-ID list and exclusion reasons;
- split manifest and SHA-256;
- feature-bank model/source versions and SHA-256;
- preprocessing state SHA-256;
- locked config SHA-256 and Git commit;
- package lockfile SHA-256, Python version, platform, and registered seeds;
- sealed-access audit record and result artifact SHA-256.

---

## 4. Real-data representation

### 4.1 Sparse ingestion and QC

The loader reads metadata and sparse matrices without global densification. It validates:

- required observation keys and a nonempty control group;
- unique, nonempty perturbation labels;
- finite, nonnegative expression values where the source schema requires counts;
- consistent gene axis and unique gene identifiers;
- minimum cells per perturbation;
- external feature availability before splitting.

Dense arrays are materialized only after fixed gene selection and only for one sampled
population at a time.

### 4.2 Train-fitted response space

Fit normalization metadata, HVG selection, centering, and PCA using controls plus
`base_train` cells only. Apply the frozen transform to all later splits. Do not refit or
recenter on method, conformal, or sealed outcomes.

The primary response vector is 50-dimensional PCA. Store loadings, selected genes, means,
scales, explained variance, fit IDs, and checksum. A transform test verifies byte-identical
results after serialization.

### 4.3 Equal-cell and noise contract

Energy distance is sample-size-sensitive and quadratic. For each population:

- require at least 64 cells;
- draw 96 cells without replacement when available, otherwise use the registered eligible
  count;
- compare equal-sized samples by taking the smaller eligible size for the pair;
- repeat deterministic sampling eight times and average the distances;
- compute pairwise distances blockwise;
- report observed-population self-distance floors from deterministic half-splits.

Primary risk is raw repeated-sample energy distance. The self-distance floor is a mandatory
reliability diagnostic, not an outcome-dependent exclusion rule. If the sealed cohort's
registered reliability precondition fails, return `INVALID_EVALUATION` and still publish all
computed diagnostics; never silently remove hard perturbations.

### 4.4 Perturbation feature bank

The primary bank is a pinned ESM-2 `t33_650M_UR50D` mean-pooled embedding generated from a
versioned protein-sequence mapping. Feature construction may run on the rented A100. The bank
builder records model revision, sequence database release, ID mapping, pooling rule, dtype,
and checksums.

Genes without an unambiguous sequence mapping are excluded **before** the split and listed.
Feature dimensions must be identical and finite. Standardization parameters are fitted on
`base_train` perturbations only. No response labels enter feature construction or scaling.

---

## 5. Models and fair comparison

### 5.1 Frozen base predictor

The base predicts a translated control population:

```text
predicted_population(q) = transformed_control + standardized_features(q) @ W
```

`W` is ridge-fitted on mean response shifts in `base_train`; ridge is chosen by fixed
five-fold CV inside `base_train`. A 20-member paired perturbation bootstrap ensemble is fitted
with the same resampled indices for features and outcomes. The base and response transform
are frozen before method-development errors are computed.

### 5.2 Trust-gate components

For a query, using only the method-development bank:

- `R1`: mean kNN distance in standardized perturbation-feature space.
- `R4`: median measured base error among feature-space neighbors.
- each component is ECDF-normalized against leave-one-out method-development references;
- the full gate is `w * R1 + (1 - w) * R4`, with `w > 0`.

Select `(k, w)` by fixed OOF AURC inside `method_development`. Ties choose larger `w`, then
smaller `k`, as preregistered. Refit reference banks after selection. `w=0` is never called the
full gate; it is the mandatory residual-only ablation.

### 5.3 Preregistered comparators

All learned methods receive the same standardized features, method-development errors, folds,
seeds, and tuning budget:

1. nearest-feature distance;
2. ensemble disagreement;
3. Ridge error regressor;
4. gradient-boosted error regressor;
5. residual-only kNN error score (`w=0`).

Hyperparameters are selected by OOF AURC only. Registered stochastic seeds are aggregated
into one score per perturbation before sealed evaluation. No baseline is added, removed, or
selected after evaluation outcomes are opened.

---

## 6. Calibration, metrics, and inference

### 6.1 Scalar conformal error bound

Using base errors on `conformal_calibration`, compute the finite-sample split-conformal
quantile:

```text
k = ceil((n_cal + 1) * (1 - alpha))
bound = kth_order_statistic(calibration_errors, min(k, n_cal))
```

Call it `error_bound`, not radius or prediction set. Report:

- `marginal_error_bound_coverage`;
- `selective_error_bound_coverage`;
- `selection_coverage`;
- `effective_covered_fraction`;
- `abstain_rate`.

The PREDICT threshold is the registered quantile of conformal-calibration **gate scores**
computed against the frozen method-development bank. Evaluation errors never set a threshold.

Because all sealed indicators share one random calibration quantile, a naive Binomial interval
is not exact. The nominal coverage check therefore uses the preregistered central 99% **exact
split-conformal beta-binomial predictive interval** implied by calibration size and order-statistic
rank (verified against an exchangeable-rank simulation). A miss yields `CALIBRATION_FAILURE`;
results remain visible and cannot be rerun with a wider tolerance.

### 6.2 Risk metrics

Normalize sealed risks by the sealed cohort mean only to make AURC/AUGRC margins
dimensionless; this deterministic transformation is applied equally to all methods and does
not affect ranking. The development-stage AURC consumed by the futility rule (§7.1) is
normalized analogously by the `method_development` cohort mean, so `delta_min` is interpreted on
the same dimensionless scale. This normalization is likewise ranking-invariant and therefore
does not affect `MethodLock` selection.

- Primary: AURC over all nonzero coverage points.
- Secondary: AUGRC and risk at 25%, 50%, 70%, and 100% coverage.
- Reliability: self-distance floor summaries and perturbation cell-count summaries.

Metric code explicitly defines the discrete integration convention and tests constant-risk,
perfect-ranking, reverse-ranking, ties, and duplicate bootstrap samples.

### 6.3 Simultaneous inference

Resample perturbation IDs with replacement. Within each replicate, recompute every method's
AURC on the identical sampled indices. Use a max-deviation bootstrap over the complete
comparator family to obtain simultaneous one-sided 95% lower bounds for all primary deltas.

For AUGRC, compute simultaneous upper bounds for
`AUGRC_gate - AUGRC_comparator`. No material degradation means every upper bound is at most
the registered `0.02` margin.

Directly compare the full gate with residual-only:

```text
delta_added_value = AURC_residual_only - AURC_full_gate
```

Its simultaneous lower bound must exceed zero. Merely showing that residual-only fails to beat
another baseline is not evidence that the full gate adds value.

---

## 7. Single authoritative verdict

`compute_verdict()` is the only function allowed to emit a scientific verdict.

Before sealed evaluation, the workflow may emit one of two **operational statuses**:

```text
CONTINUE_CONFIRMATORY
FUTILITY_STOPPED
```

These are not scientific verdicts. In particular, `FUTILITY_STOPPED` must never be translated
to `NO_DISTINCT_WIN`, `CALIBRATION_FAILURE`, or any statement about sealed performance.

```text
INVALID_EVALUATION
    integrity/provenance/leakage failure, sealed n below minimum, nonfinite metric,
    or registered measurement-reliability precondition failure

CALIBRATION_FAILURE
    integrity valid, but scalar error-bound coverage misses the registered acceptance band

GATE_WINS
    integrity valid
    AND calibration valid
    AND every simultaneous primary AURC lower bound > 0
    AND every AUGRC degradation upper bound <= 0.02
    AND full gate directly beats residual-only with simultaneous lower bound > 0
    AND selected full-gate feature weight > 0

NO_DISTINCT_WIN
    every other valid completed result
```

The result object stores a Boolean and evidence field for every clause. Tests construct one
failure at a time and prove that no failed clause can produce `GATE_WINS`.

The primary manifest produces the only confirmatory verdict. Five additional manifests may be
generated and committed before opening outcomes for descriptive split sensitivity; they are
reported as robustness analyses and never replace the primary result.

### 7.1 Preregistered futility rule

After `MethodLock`, compute OOF development deltas against `gbm_error` and `residual_only`:

```text
delta_m_dev = AURC_m_dev - AURC_gate_dev
```

Use a perturbation-level max-deviation bootstrap to obtain simultaneous one-sided 90% **upper**
bounds for both deltas. Let `delta_min = 0.01` on the dimensionless development-risk scale
defined in §6.2 (development AURC normalized by the `method_development` cohort mean).

- Emit `FUTILITY_STOPPED` if **any** comparator's simultaneous upper bound is `<= delta_min`.
  The data then do not support a plausible minimum-relevant advantage over every required
  comparator.
- Otherwise emit `CONTINUE_CONFIRMATORY`.

The rule, confidence level, comparator family, normalization, bootstrap seed, and
`delta_min` are locked in config. Visual inspection, point-estimate language such as “within
fold noise,” and discretionary override are prohibited. The futility calculation uses OOF
predictions already fixed by `MethodLock`; it never uses conformal or sealed outcomes.

If stopped, complete the scalar conformal artifact, write a futility report, leave sealed-access
count at zero, and close the run ID permanently. A later confirmatory attempt requires a new
preregistered run ID and must be reported alongside the stopped run.

---

## 8. Repository structure

```text
ALIVE/
├── pyproject.toml
├── uv.lock
├── configs/cartographer_trust_gate_k562_v1.yaml
├── src/alive/
│   ├── types.py
│   ├── config.py
│   ├── provenance.py
│   ├── data/
│   │   ├── manifest.py
│   │   ├── replogle.py
│   │   ├── outcome_store.py
│   │   ├── features.py
│   │   └── preprocess.py
│   ├── metrics/
│   │   ├── distance.py
│   │   └── selective.py
│   ├── base/predictor.py
│   ├── gate/recoverability.py
│   ├── baselines/uq.py
│   ├── conformal/error_bound.py
│   ├── eval/
│   │   ├── coverage.py
│   │   ├── bootstrap.py
│   │   └── verdict.py
│   └── experiment/
│       ├── develop.py
│       └── real_runner.py
├── tests/alive/
└── artifacts/cartographer/<run_id>/
```

Core dependencies: Python 3.11+, NumPy, SciPy, scikit-learn, anndata, scanpy, h5py,
PyYAML, pytest, and Ruff. The optional `features` group pins PyTorch, Transformers, and the
ESM model tooling used on A100. Runtime analysis after feature construction remains CPU-safe.

---

## 9. Implementation tasks

Every task follows red-green-refactor: write the listed failing tests, run them, implement the
minimum contract, rerun targeted tests, run Ruff, and commit. Scientific code must not be
implemented from prose assumptions absent from the locked config or interfaces below.

### Task 1 — Scaffold, config, and shared types

Create `pyproject.toml`, config schema, `Query`, `PopulationRef`, `BasePrediction`, and result
dataclasses. Validate the complete YAML and reject unknown keys. Tests cover round-trip,
invalid fractions, small bootstrap counts, and deterministic run-ID hashing.

### Task 2 — Provenance ledger

Implement streaming SHA-256, environment capture, immutable `RunLedger`, and artifact hashes.
Tests detect changed data, config, manifest, feature bank, lockfile, and duplicate artifact
names. No timestamp is included in deterministic run-ID hashing.

### Task 3 — Sparse Replogle index and schema validation

Build a metadata index without loading all expression values. Validate schema, controls, gene
axis, counts, feature availability, and eligible cell counts. Tests use sparse fixtures and a
sentinel matrix that raises on global `.toarray()`/`.todense()`.

### Task 4 — Four-way manifest

Implement the registered perturbation split, exclusions, class counts, and stable checksum.
Tests prove disjointness, full eligible-ID coverage, order independence, determinism, and that
expression values cannot affect assignment.

### Task 5 — Sealed outcome store

Implement split-aware lazy population reads and `evaluate_sealed_once`. Tests prove fitting and
calibration cannot read sealed IDs, first access is logged, second access fails, and unsealed
reads remain available.

### Task 6 — External feature bank

Implement pinned sequence mapping, ESM batching, mean pooling, validation, provenance, and
serialization. Feature extraction runs on the rented A100; a tiny mocked encoder runs in CI.
Tests cover ambiguous/missing IDs, fixed dimensions, finite values, deterministic pooling,
checksum changes, and base-train-only standardization.

### Task 7 — Train-fitted response preprocessing

Implement normalization, HVG selection, PCA, serialization, and one-population-at-a-time
transform. Fit only on controls plus `base_train`. Tests use split-coded sentinel expression to
prove no method/conformal/sealed outcome contributes to fit statistics.

### Task 8 — Population sampling and distances

Implement deterministic equal-cell sampling, repeated blockwise energy distance, sliced
Wasserstein as a diagnostic, and self-distance floors. Compare against a dense reference on
small arrays. Test symmetry, identity, shifts, unequal cell counts, memory blocks, seed keys,
and too-few-cell errors.

### Task 9 — Frozen additive base and paired ensemble

Fit ridge mean shifts with CV restricted to `base_train`; predict translated control
populations; build paired-index bootstrap members. Tests recover a known linear shift, prove
query/target indices remain paired, and prove method-development labels cannot affect the base.

### Task 10 — Selective metrics

Implement the registered discrete AURC/AUGRC convention and coverage-point risks. Tests cover
perfect, random, reverse, constant, tied, empty, nonfinite, and duplicated samples. Never use a
conformal error bound as the risk axis.

### Task 11 — Gate and comparators

Implement LOO kNN feature distance, LOO local residual score, ECDF normalization, Ridge/GBM
error regressors, ensemble disagreement, and residual-only ablation. Standardized features and
identical development folds are mandatory. Tests cover self-exclusion, feature-scale
invariance after standardization, and identical method budgets.

### Task 12 — OOF method development

Select all hyperparameters using fixed five-fold OOF AURC inside `method_development`; lock
tie-breaking and aggregate registered seeds. Emit a `MethodLock` artifact containing the full
search table, selected parameters, folds, seeds, and checksum. Tests prove shuffled sealed
outcomes cannot alter it.

Apply the preregistered futility rule in §7.1. Because that rule needs simultaneous bounds, this
task creates the shared max-deviation perturbation-bootstrap primitive in
`src/alive/eval/bootstrap.py` (one-sided simultaneous upper/lower bounds over a comparator family
on identical resampled indices, fixed registered seed); Task 14 later extends the same module for
the sealed confirmatory family rather than reimplementing it. Emit an immutable `FutilityDecision`
artifact containing both development deltas, simultaneous upper bounds, threshold, operational
status, config hash, and `MethodLock` hash. Tests cover the primitive (nominal coverage on a
known-delta simulation, identical sampled indices across methods, byte-identical output under
fixed seed) and exact-status cases: clear continuation, clear futility, boundary equality,
comparator-family multiplicity, and invariance to conformal/sealed outcomes.

### Task 13 — Scalar conformal error bound and threshold

Implement the finite-sample order statistic, scalar coverage report, exact split-conformal
beta-binomial predictive acceptance band, and gate-score threshold. Tests cover off-by-one
quantiles, small samples, agreement with exchangeable-rank simulation, selection-induced
inflation, and invariance to shuffled sealed outcomes.

### Task 14 — Simultaneous bootstrap

This task is required only for `CONTINUE_CONFIRMATORY`. It reuses the shared max-deviation
bootstrap primitive created in Task 12 (`src/alive/eval/bootstrap.py`) and does not reimplement
it. Extend that module with pairwise descriptive intervals, max-deviation simultaneous AURC lower
bounds, simultaneous AUGRC upper bounds, and the direct full-vs-residual test. Tests prove:

- a gate equal to one comparator cannot pass the family;
- adding weak comparators cannot create a false win;
- duplicate resamples and ties remain finite;
- all methods use identical sampled perturbation indices;
- fixed seed reproduces byte-identical inference output.

### Task 15 — Verdict engine

Implement the truth table in Section 7. Parameterized tests toggle every clause independently.
The positive fixture must return exactly `GATE_WINS`; negative, calibration-failure, leakage,
low-n, and residual-only fixtures must return their exact registered verdicts. Tests that merely
assert membership in a set of possible verdicts are prohibited.

### Task 16 — Real fit, calibration, and sealed evaluation

Implement three explicit stages:

```python
base_artifact = fit_base(index, store, manifest, preprocessing, config)
method_artifact = develop_methods(index, store, manifest, base_artifact, config)
calibration_artifact = calibrate(index, store, manifest, base_artifact,
                                 method_artifact, config)
result = evaluate_sealed_once(index, store, manifest, base_artifact,
                              method_artifact, calibration_artifact, config)
```

Only the final call receives the sealed capability. It computes all method scores before
reading risks, checks completeness/nonfiniteness, performs registered inference, calls the
verdict engine, writes the immutable result and audit ledger, and exits. Integration tests use
a spy store and synthetic data before the real run. This final call is forbidden when the
operational status is `FUTILITY_STOPPED`.

### Task 17 — Reproducible runner and report

Add CLI commands:

```bash
uv run alive cartographer prepare --config configs/cartographer_trust_gate_k562_v1.yaml
uv run alive cartographer fit --run-id <run_id>
uv run alive cartographer develop --run-id <run_id>
uv run alive cartographer futility --run-id <run_id>
uv run alive cartographer calibrate --run-id <run_id>
uv run alive cartographer evaluate-once --run-id <run_id>
uv run alive cartographer report --run-id <run_id>
```

`evaluate-once` checks the immutable `FutilityDecision` and refuses to run unless its status is
`CONTINUE_CONFIRMATORY`. `calibrate` runs in either branch so a stopped run can ship its scalar
conformal artifact.

`report` has two locked schemas:

- `FUTILITY_STOPPED`: config, provenance, flow counts, MethodLock, futility bounds, scalar
  conformal artifact, sealed-access count `0`, and an explicit `scientific_verdict: null`.
- confirmatory: config, provenance, risk-coverage curves, simultaneous intervals, scalar
  error-bound diagnostics, reliability plots, ablations, verdict evidence, and sealed-access
  count `1`.

It never recomputes a decision or verdict. A schema test prohibits confirmatory plots, empirical
sealed coverage, or negative-performance language in a futility report.

---

## 10. Mandatory test gates

Before preparing real data:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
```

Before sealed evaluation:

```text
[ ] config and manifest committed; hashes match
[ ] raw-data and feature-bank hashes match
[ ] exclusions occurred before splitting
[ ] response transform fitted only on control + base_train
[ ] base fitted only on base_train
[ ] MethodLock created only from method_development OOF results
[ ] FutilityDecision matches locked config and MethodLock hashes
[ ] conformal artifact created only from conformal_calibration
[ ] sealed outcome access log is empty
[ ] sealed n >= 200
[ ] all synthetic exact-verdict tests pass
[ ] simultaneous-inference tests pass
[ ] full pipeline dry-run passes on a mini dataset
[ ] operational status is CONTINUE_CONFIRMATORY
```

After `evaluate-once`, no criterion, comparator, seed, margin, split, or exclusion may change.
A failed result is a result, not permission to redefine the experiment.

---

## 11. Compute plan

- **MacBook Pro:** Phase 0 scaffolding, unit tests, synthetic fixtures, configs, reports, and
  mini-data end-to-end runs.
- **Rented A100:** raw-data preparation, pinned ESM feature-bank generation, and full-data
  preprocessing. A100 use is acceptable even when a step is CPU-heavy; no separate cloud CPU
  rental is required.
- **MacBook Pro:** pull only the versioned mini dataset and artifacts needed for local pipeline
  testing.
- **Rented A100:** after the mini pipeline passes and hashes/config are frozen, run full-data
  preparation, fit, development, futility decision, and calibration. Run the single sealed
  evaluation only when status is `CONTINUE_CONFIRMATORY`; otherwise generate the futility report
  with sealed-access count zero.

The MVP does not depend on an RTX 4070-class desktop. CPU implementations remain authoritative
for distance and inference reproducibility; GPU-derived ESM artifacts are checked by checksum.

---

## 12. Stop/go interpretation

- `FUTILITY_STOPPED`: publish the development/calibration artifact with
  `scientific_verdict: null`; make no sealed-performance claim and permanently close the run ID.
- `GATE_WINS`: proceed to causal masking and an independently specified Active Cartographer
  falsification plan; do not yet claim prospective value.
- `NO_DISTINCT_WIN`: retain conformal error-bound calibration if valid, report the gate as not
  superior to error regression, and do not cosmetically rename it active mapping.
- `CALIBRATION_FAILURE`: investigate exchangeability, preprocessing, and model misspecification
  in a newly registered experiment; preserve the original result.
- `INVALID_EVALUATION`: repair only the documented integrity/reliability failure and register a
  new run ID. Never overwrite the invalid run.

RPE1 transfer, distribution-valued heterogeneity, causal masking, EPIG/GO-CBED/IterPert
acquisition, and prospective wet-lab validation are intentionally deferred. Any future Active
Cartographer must beat random, diversity, pathway-stratified, graph one-shot, IterPert, and
uncertainty-only acquisition under its own sealed budgeted protocol.

---

## 13. Definition of done

The MVP has two mutually exclusive valid completion modes.

### 13.1 Calibration-deliverable completion

1. Tasks 1–13 and the futility-report branch of Task 17 pass.
2. `FutilityDecision.status == FUTILITY_STOPPED` under the exact registered rule.
3. Frozen manifest, config, feature bank, preprocessing state, MethodLock, conformal artifact,
   and provenance ledger exist.
4. Sealed outcomes were accessed zero times.
5. The immutable report contains `scientific_verdict: null` and makes no empirical sealed
   coverage, routing, or `NO_DISTINCT_WIN` claim.

### 13.2 Confirmatory completion

1. Tasks 1–17 and all mandatory tests pass.
2. `FutilityDecision.status == CONTINUE_CONFIRMATORY`.
3. All frozen artifacts and provenance records exist and match their hashes.
4. Sealed outcomes were accessed exactly once by the authorized evaluator.
5. The complete immutable result is published regardless of scientific verdict.
6. Every scientific statement is entailed by verdict evidence and the claim boundary in §1.

This plan makes a negative result first-class. Its purpose is not to force CARTOGRAPHER to win;
it is to make any win difficult to fake and any failure useful enough to guide the next model.
