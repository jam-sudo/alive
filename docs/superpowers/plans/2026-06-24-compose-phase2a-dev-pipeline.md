# COMPOSE-K562-v1 Phase 2a Development Pipeline — Corrected Implementation Plan

> **Status:** PRE-REGISTERED, ACTIVATION BLOCKED
> **Scope:** implementation and synthetic/tiny-fixture tests only. No real Norman Phase-2a run,
> no sealed role materialisation, and no scientific verdict.
> **Contract:** `CLAUDE.md`, the COMPOSE design spec §10, and
> `configs/compose_k562_v1_phase2.yaml`.

## 1. Goal

Build the development-only COMPOSE pipeline:

1. deterministic pair manifest and role assignment;
2. training-role-only response space;
3. fixed per-gene factors;
4. L1/L2/L3/ID-only and registered baselines;
5. gene-disjoint OOF selection;
6. actual calibration $\Phi$ rank/conditioning, measurability and futility diagnostics;
7. a frozen prediction bundle for Phase 2b that contains no outcomes;
8. complete data-card, environment and artifact provenance.

All implementation tests use synthetic arrays or tiny toy AnnData. Real execution remains forbidden
until every activation requirement in the config is satisfied and `CLAUDE.md` is committed with the
protocol explicitly marked `ACTIVE`.

## 2. Non-negotiable invariants

### 2.1 Role and leakage boundaries

- Eligibility is fixed before splitting and may use only metadata, cell counts and external-feature
  availability.
- `singles` and `combo_calibration` are development roles.
- `sealed_double_unseen` and `sealed_single_unseen` outcomes must be inaccessible to Phase 2a APIs.
- Public Phase-2a functions accept typed development objects, not arbitrary dictionaries.
- Recursive validation rejects any object carrying a sealed role, sealed outcome array or path to a
  sealed outcome asset.
- Cell-level normalization statistics, HVGs, PCA, factor projections, hyperparameters and thresholds
  are fitted only from explicitly allowed roles.

### 2.2 Response-space fitting

- Library-size normalization target is the median positive library size over
  `control + eligible singles` only.
- HVGs are selected from control cells only, as registered.
- PCA is fitted on `control + eligible singles` only.
- Double cells, including calibration doubles, are projected only after the response space is fixed.
- The response-space artifact records fit-role IDs, normalization target, HVG indices, PCA state,
  input hashes and checksum.

### 2.3 Pair symmetry

Genetic-combination prediction is unordered. Every pair is canonicalized as
`(min_utf8(g, h), max_utf8(g, h))`. L1 is symmetric by construction. ID-only and L3 must use symmetric
features such as `[z_g + z_h, abs(z_g - z_h)]`; concatenating `[z_g, z_h]` is prohibited because it
makes predictions depend on label order.

### 2.4 OOF semantics

- Test pairs in a fold have both genes in the held-out gene group.
- Training pairs have neither held-out gene.
- Cross-group pairs are excluded from that fold; they are not silently assigned to training.
- Every retained fold must contain non-empty train and test sets.
- The union of test pairs, uncovered calibration pairs and fold exclusions is reported.
- Hyperparameter selection executes the complete fit → predict → metric path in tests.
- Per-gene factors may use every eligible single-gene outcome because the confirmatory claim is
  pair/combo-zero-shot, not single-gene-zero-shot. Combo outcomes remain fold-isolated.

### 2.5 Frozen handoff

Phase 2a produces a `FrozenPredictionBundle` containing:

- composite `run_id`;
- exact method roster;
- pair IDs grouped by `sealed_double_unseen` and `sealed_single_unseen`;
- predictions only, never measured pair outcomes;
- response-space, factor, model and manifest checksums;
- selected hyperparameters and seeds;
- development diagnostics and futility status.

The bundle is written once and hashed into `RunLedger`. Phase 2b consumes this artifact without
refitting.

## 3. Planned modules

| File | Responsibility |
|---|---|
| `src/alive/compose/config2.py` | Strict Phase-2 config loader and status/activation validation |
| `src/alive/compose/split.py` | Deterministic canonical pair manifest and roles |
| `src/alive/compose/response.py` | Training-role-only normalization, HVG and PCA |
| `src/alive/compose/zfactor.py` | Fixed expression + ESM factor construction |
| `src/alive/compose/models.py` | Symmetric L1/L2/L3/ID-only models |
| `src/alive/compose/baselines_combo.py` | Lower bounds and guarded GEARS/CPA adapters |
| `src/alive/compose/metric2.py` | Registered primary metric and secondary primitives |
| `src/alive/compose/select.py` | Gene-disjoint OOF selection |
| `src/alive/compose/datacard.py` | Validated Norman data-card and hashes |
| `src/alive/compose/freeze.py` | Frozen prediction bundle and checksum |
| `src/alive/compose/phase2a.py` | No-seal orchestration and futility result |

## 4. Task sequence

### Task 1 — Strict Phase-2 config and execution guard

Implement a frozen config model that rejects unknown or missing keys and validates:

- `status`;
- total factor dimensions and ESM dimension arithmetic;
- exact comparator roster;
- metric formula and margins;
- exact definitions, intervals and any material-regression margin for every registered secondary
  metric, or a versioned governance reconciliation explaining why a secondary is descriptive only;
- bootstrap settings;
- role names;
- activation requirements.

Two explicit modes are allowed:

- `fixture_mode=True`: synthetic/tiny-fixture tests only;
- scientific mode: requires config status `active`, an owner activation record, clean committed
  Git state and all activation evidence hashes.

Tests must prove a blocked config cannot start a real-data pipeline.

### Task 2 — Deterministic pair manifest

Extend `build_pair_split` to:

1. validate `0 < calibration_fraction < 1`;
2. reject self-pairs and empty gene IDs;
3. canonicalize and deduplicate pairs;
4. sort strings by encoded UTF-8 bytes, not locale;
5. use `Generator(PCG64(seed))`;
6. use explicit round-half-to-even for the calibration-gene count;
7. emit named roles `combo_calibration`, `sealed_double_unseen`,
   `sealed_single_unseen`;
8. serialize a manifest with algorithm/version, eligibility hash, role membership and checksum.

Tests must include reversed duplicates, Unicode IDs, exact half cases, empty inputs, self-pairs,
cross-process determinism and the double-unseen isolation invariant.

### Task 3 — Response space without preprocessing leakage

Implement:

```python
fit_response_space(
    X,
    *,
    control_idx,
    eligible_single_idx,
    n_hvg,
    pca_dim,
    seed,
) -> ResponseSpace
```

Required ordering:

1. validate all indices and disjointness;
2. define `fit_idx = control_idx ∪ eligible_single_idx`;
3. compute the positive-library-size median from `X[fit_idx]`, never full `X`;
4. normalize/log-transform using that frozen scalar;
5. select HVGs from normalized controls only with deterministic tie-breaking by gene index;
6. fit PCA on normalized `X[fit_idx, hvg_idx]`;
7. store fit indices only as hashes/counts, not raw cell barcodes in reports;
8. project calibration doubles after fitting.

Required tests:

- changing only sealed rows leaves the complete response artifact byte-identical;
- changing controls or eligible singles changes it;
- zero-library and insufficient-dimension cases fail closed;
- sparse input is never globally densified.

### Task 4 — Fixed factor construction

For each registered `k_total`, construct:

```text
z_g = [PCA_expression(delta_g, k_total - 2);
       PCA_ESM(sequence_feature_g, 2)]
```

Expression PCA is fitted on all eligible single-gene shifts. ESM PCA is outcome-free and fitted on
eligible sequence vectors only. Record gene ordering, PCA signs/orientation policy, explained
variance, encoder revision, sequence-mapping hash and checksum.

Tests must verify dimension arithmetic, input-order invariance, missing-feature failure, deterministic
component orientation and no combo-outcome dependency.

### Task 5 — Symmetric models and known-answer tests

Implement:

- L1: symmetric identifiable bilinear operator;
- L2: preregistered monotone saturation of the L1 score;
- ID-only: ridge on symmetric non-bilinear features;
- L3: higher-capacity symmetric network on symmetric pair features.

The methods share a typed `fit`/`predict_eps` protocol. Tests must verify:

- `predict(g, h) == predict(h, g)` for every model;
- noiseless L1 recovery under full rank;
- finite bounded behavior under rank deficiency;
- false-GI null behavior;
- L2 monotonicity;
- deterministic L3 initialization and training;
- identical input/output shape rules.

### Task 6 — Metrics

Primary primitives:

```text
e_M,i = mean_j((prediction_M,i,j - truth_i,j)^2)
theta_M,C = 1 - mean_i(e_M,i) / max(mean_i(e_C,i), 1e-12)
```

Reject empty, misaligned, duplicated-ID, non-finite and shape-mismatched inputs.

Secondary metrics:

- GI explained fraction:
  `1 - sum(||eps_truth - eps_pred||²) / max(sum(||eps_truth||²), 1e-12)`;
- GI structure recovery: computed only when a versioned, hashed class-label manifest and a fully
  specified prediction-to-class rule exist. Until then it is reported as `NOT_EVALUABLE`, never
  silently omitted or used in a verdict.

Known-answer tests cover perfect, additive truth, worse-than-additive, zero denominator, shuffled pair
IDs and non-finite inputs.

### Task 7 — Guarded GEARS/CPA adapter seam

Use a frozen `BaselineTrainingContext` with exact fields:

- allowed roles;
- pair manifest checksum;
- response-space checksum;
- training pair IDs;
- single-gene IDs;
- no outcome-store handle and no sealed paths.

Adapters must require `allowed_roles == {"singles", "combo_calibration"}` and recursively reject any
sealed role/key/path. Backend output must match the requested canonical pair IDs and response
dimension exactly.

Tests must prove sealed-role contexts, extra pair predictions, missing predictions and arbitrary
untyped dictionaries are rejected.

### Task 8 — End-to-end gene-disjoint OOF selection

Implement deterministic folds and execute the full selection path for every `(k_total, lambda)`:

1. build fold train/test pair indices;
2. fit only on train combo outcomes;
3. predict held-out pairs;
4. add the registered additive prediction;
5. compute aligned pair errors and `theta`;
6. aggregate OOF errors by pair ID;
7. select maximum theta with deterministic tie-breaking:
   lower `k_total`, then larger regularization.

Do not add factor-shaped dummy arrays to response-shaped predictions. Empty folds or uncovered-pair
fractions above a registered tolerance invalidate selection.

Tests must call `select_hyperparams` itself with `p != k`, assert the known best hyperparameter,
exercise empty folds and verify no held-out gene occurs in any training pair.

### Task 9 — Real calibration diagnostics and futility

On development-role inputs only:

- calculate the actual $\Phi$ rank and condition number for the selected total factor dimension;
- retain the singular-value spectrum and tolerance;
- compute split-half measurability with an explicit development role;
- calculate OOF primary theta;
- emit `CONTINUE` only when every registered gate passes.

Rank deficiency, non-finite conditioning, measurability failure or OOF theta `<= 0` produces
`FUTILITY_STOPPED`. The result records sealed access count zero and cannot be converted into a sealed
negative verdict.

### Task 10 — Validated data-card and provenance

The data-card builder consumes separate declared source and processed assets and computes:

- source URI/DOI and license;
- raw asset SHA-256 when a raw asset exists, otherwise a declared immutable source digest;
- processed H5AD SHA-256;
- obs/var schema derived directly from AnnData;
- counts derived directly from parsed labels;
- outcome-independent exclusions and their manifest hash;
- cell line, modality and processing version.

Caller-provided counts cannot overwrite derived values. Mismatches raise.

Create the composite run ID using config digest, canonical data-card digest, raw/source digest and
sequence-mapping digest. Capture Git SHA, dependency-lock hash, Python/platform, device/precision and
registered seeds in `RunLedger`.

### Task 11 — Phase-2a orchestration and freeze

`run_phase2a` accepts typed development inputs and an outcome-store interface that exposes only
unsealed roles. It:

1. verifies blocked/fixture or active/scientific mode;
2. verifies manifest, response, factor and environment hashes;
3. runs selection and diagnostics;
4. stops without predictions for sealed roles if futility fires;
5. otherwise generates predictions for registered sealed pair IDs using identities/features only;
6. validates the complete method roster and every prediction;
7. writes a `FrozenPredictionBundle` and method lock once;
8. records checksums in the ledger;
9. confirms sealed access count remains zero.

Tests recursively inject sealed data at multiple nesting levels and require rejection. Mutating any
upstream artifact after freezing must fail checksum verification.

## 5. Verification commands

Implementation work must finish with:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/alive/compose tests/alive/data/test_norman.py
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
git diff --check
```

No formatter with write mode and no real Norman execution is permitted under this plan.

## 6. Exit criteria

Phase 2a implementation is complete only when:

- all tasks above are tested;
- no sealed outcome can enter a Phase-2a public API;
- changing sealed rows cannot change preprocessing artifacts;
- full OOF selection runs with unequal factor/output dimensions;
- GEARS/CPA guards fail closed;
- real-rank code reports actual $\Phi$ diagnostics on fixtures;
- frozen predictions contain no outcomes;
- the ledger binds every upstream artifact;
- seal access remains zero.

This completion satisfies only the implementation/test portion of activation blocker 6. It does not
satisfy real-data rank, power, dependency-lock, data-card or activation requirements by itself.
