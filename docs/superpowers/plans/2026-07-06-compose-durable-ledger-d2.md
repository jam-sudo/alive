# COMPOSE Development Seed-Variability (sub-project D2) Implementation Plan

> **Status:** implementation-ready after this revision. Execute tasks in order; D1 consumes the
> completed D2 artifact and therefore must not be wired into scientific Phase-2b before Task 7.

**Goal:** Measure registered-seed variability for the seed-refittable stochastic comparators
`gears` and `cpa` on the exact Phase2a gene-disjoint calibration OOF design, without opening a
seal, and bind the self-checksummed result into the pre-access ledger.

**Design source:**
`docs/superpowers/specs/2026-07-05-compose-durable-ledger-design.md` §4–§6.2.

## 0. Corrected architecture

The previous plan assumed a persisted per-pair `oof_folds` artifact that does not exist and called
`select.build_gene_disjoint_folds` with the wrong argument type. This plan establishes one exact
truth source first:

1. `select_hyperparams` constructs integer-index folds once from
   `Phase2aInputs.cal_idx_pairs`, `n_genes`, `n_folds`, and `seed`.
2. The exact train/test/excluded positions and pair IDs are converted to a canonical
   `OOFFoldManifest`, checksummed, returned by Phase2a, written once, and bound into the method lock
   and ledger.
3. D2 loads and verifies that manifest. It never reconstructs folds and never accepts a caller-made
   per-pair assignment.
4. Each `(method, registered_seed, fold)` uses a fresh backend instance. The backend's immutable
   execution identity is copied, while `seed` and the train-only payload are bound before exactly
   one predict call.
5. Worker payloads retain the existing payload-v2 exact key roster. Fold metadata remains in a
   controller-side `FoldJob`; it is not inserted as extra payload keys.

This removes three ambiguity classes: regenerated folds, mutable-backend state bleed across folds,
and payload schema drift.

## 1. Frozen contracts

- Registered seed order is exactly `config.registered_seeds == (11, 23, 37)`.
- Fold parameters come from `config.oof_folds`, `config.split_seed`, and
  `config.uncovered_tolerance` (direct `ComposePhase2Config` fields).
- Seed loop roster is exactly `("gears", "cpa")`.
- Deterministic single-shot roster is exactly
  `l1_bilinear_identifiable`, `l2_saturation`, `l3_hypernetwork`, `id_only`, `additive`,
  `no_change`, `perturbation_mean`.
- Sample standard deviation uses `ddof=1`.
- A failed seed or fold, coverage mismatch, non-finite statistic, or uncovered fraction above the
  registered tolerance makes the report `INCOMPLETE`; failures are never dropped.
- D2 accepts the exact `phase2a.DevelopmentOutcomeStore` type. It does not accept
  `outcome_store.ComposeOutcomeStore`, arbitrary arrays, paths, dictionaries, or injected payloads.
- Truth is the pair-ID-aligned development delta
  `inputs.additive_cal + store.combo_calibration_eps`. The report names it `delta_truth`, not
  `true_eps`.
- No sealed identity, sealed outcome, per-pair CI, or raw cell/count matrix is written to the report.
- Scientific D2 uses real GEARS/CPA workers in locked pod environments. Local tests use only the
  reference stub and prove wiring, not biological stability.

## 2. Files

- Modify `src/alive/compose/select.py`
- Modify `src/alive/compose/diagnostics2.py`
- Modify `src/alive/compose/phase2a.py`
- Modify `src/alive/compose/baseline_subprocess.py`
- Create `src/alive/compose/seed_variability.py`
- Modify `src/alive/compose/phase2b.py`
- Modify corresponding tests; create `tests/alive/compose/test_seed_variability.py`

## Task 1 — Persist the exact Phase2a OOF fold manifest

### Interfaces

Add immutable objects in `select.py`:

```python
@dataclass(frozen=True)
class OOFFoldRecord:
    fold_index: int
    held_out_gene_indices: tuple[int, ...]
    train_pair_positions: tuple[int, ...]
    test_pair_positions: tuple[int, ...]
    excluded_pair_positions: tuple[int, ...]
    train_pair_ids: tuple[tuple[str, str], ...]
    test_pair_ids: tuple[tuple[str, str], ...]
    excluded_pair_ids: tuple[tuple[str, str], ...]

@dataclass(frozen=True)
class OOFFoldManifest:
    schema: str  # "compose_oof_fold_manifest_v1"
    calibration_pair_ids: tuple[tuple[str, str], ...]
    n_genes: int
    n_folds: int
    split_seed: int
    folds: tuple[OOFFoldRecord, ...]
    covered_pair_ids: tuple[tuple[str, str], ...]
    uncovered_pair_ids: tuple[tuple[str, str], ...]
    manifest_checksum: str
```

`OOFFoldManifest` has strict `to_dict`, self-excluding checksum, `write_once(path)`, and
`load(path)` methods. Loading rejects unknown/missing keys, noncanonical/duplicate pair IDs,
position/ID disagreement, overlapping train/test/excluded partitions, invalid coverage, and checksum
tampering.

Extend `SelectionResult` with `oof_manifest: OOFFoldManifest`. Build it from the exact `folds`
already created at `select.py:442`; do not call `build_gene_disjoint_folds` a second time.
Extend `FutilityResult` and `Phase2aResult` to carry the same manifest.

Add optional `oof_manifest_path` to `run_phase2a`. On `CONTINUE`, write the manifest once, add
`oof_fold_manifest_checksum` to `FrozenPredictionBundle.dev_diagnostics` and method lock, and record
the checksum under ledger artifact `phase2a_oof_fold_manifest`. On futility stop, return the manifest
in memory but do not produce a sealed-prediction bundle; the driver may still persist the development
diagnostic artifact at its registered path.

### Tests

- Manifest records exactly the folds returned by the single selection call.
- Shuffling pair rows changes the manifest checksum but preserves position↔ID alignment.
- Tampered positions, IDs, coverage, seed, or checksum fail loading.
- Phase2a bundle, method lock, ledger, and on-disk manifest share one checksum.
- Re-running with identical inputs produces byte-identical manifest bytes.

Use a valid synthetic fold fixture: derive the seed-11 gene groups first, include at least one
within-group pair per group and at least one cross-group pair, and assert every retained fold has
non-empty train and test. Do not hardcode `(0, 1, 2, -1)` independently of the actual partition.

## Task 2 — Add a fresh-backend spawn contract

The existing `SubprocessBaselineBackend` is mutable: `configure_payload` replaces `_payload`, and
`predict` overwrites payload seed from `self.seed`. Reusing one instance across fold jobs is forbidden.

Add:

```python
def spawn(self, *, seed: int) -> SubprocessBaselineBackend:
    """Return an unconfigured backend with identical immutable execution identity."""
```

The new instance copies `name`, resolved executable/worker paths, import name,
`approved_artifacts_root`, `expected_response_artifact_sha256`, and
`execution_identity_lock`; sets the requested seed; and starts with `_payload=None`,
`_last_execution_manifest=None`. It must not share mutable payload or manifest state.

Add `BaselineAdapter.spawn(seed=...)` which requires a backend exposing this contract and returns a
new adapter with the same method name. Scientific D2 rejects backends without `spawn`; test-only
adapter factories live behind a fixture-only entry point.

### Tests

- Spawned backends do not share payload or execution-manifest state.
- `seed=23` reaches the serialized worker payload and provenance manifest as 23.
- Configuring fold B cannot change a previously spawned fold-A backend.
- A backend without `spawn` is rejected by the scientific entry before fitting.

## Task 3 — Build controller-side fold jobs without payload schema drift

Create in `seed_variability.py`:

```python
@dataclass(frozen=True)
class FoldJob:
    method: str
    seed: int
    fold_index: int
    payload: Mapping[str, object]
    test_pair_ids: tuple[tuple[str, str], ...]
    excluded_pair_ids: tuple[tuple[str, str], ...]
    fit_role_artifact_path: str
    fit_role_artifact_sha256: str
    train_source_checksum: str
    fold_manifest_checksum: str
```

`build_fold_job(...)` consumes a verified `OOFFoldManifest`, `Phase2aInputs`, the exact
`phase2a.DevelopmentOutcomeStore`, response artifact, the validated base fit-role artifact, and an
approved fold-artifact directory.

For the requested fold it:

1. slices `cal_pair_ids`, `cal_idx_pairs`, `additive_cal`, `eps_split_a`, and `eps_split_b` by the
   manifest's train positions;
2. creates a **new write-once fold-scoped fit-role artifact** containing all registered control and
   single rows but only this fold's train combo rows. It validates the artifact and proves that no
   held-out or cross-group combo row/token is present;
3. creates a train-only `DevelopmentOutcomeStore` with a copied `OutcomeAccessAudit` preserving
   role/source/manifest identity and `sealed_access_count=0`;
4. calls `build_subprocess_fit_payload` once using the **fold-scoped** `FitRoleArtifactSpec`;
5. leaves the payload key set exactly equal to `baseline_subprocess._REQUIRED_KEYS`;
6. stores test/excluded IDs, fold artifact SHA, and fold/source checksums only in `FoldJob`.

The base fit-role artifact is never passed to a worker during D2 because it contains every
calibration combo and would leak outer-fold test targets. Fold artifact filenames bind method, seed,
fold, source artifact SHA, and OOF-manifest checksum; a non-identical existing file fails closed.

The train payload's `oof_folds` uses the original manifest-derived test-fold assignment for covered
train rows. Globally uncovered train rows use the nonnegative sentinel `n_folds`, meaning
"training-only; never an outer-fold test row". This remains compatible with the current payload-v2
type validator. The controller cross-checks every label against the verified OOF manifest before
configuration, and the real-worker contract must treat `n_folds` as ineligible for validation or
early stopping. If workers do not consume `oof_folds`, remove this field only in a separately
versioned payload-v3 amendment instead of inventing all-zero labels.

### Tests

- Train payload contains no held-out or excluded pair ID/target.
- Opening the fold fit-role artifact shows no held-out or excluded combo cell/token; its control and
  single universes still satisfy the registered contract.
- Every payload target row aligns with its train pair ID.
- Extra fold metadata keys are absent from the payload and therefore pass the existing exact-key
  validator.
- Store restriction preserves audit identity and recomputes a content checksum over the subset.
- A manifest/input/store alignment mismatch fails before backend creation.

## Task 4 — Execute one isolated `(method, seed, fold)` job

`run_fold_job(adapter, job, response_dim)` performs this sequence without prebuilding mutable
contexts for multiple folds:

1. `fold_adapter = adapter.spawn(seed=job.seed)`;
2. `fold_adapter.backend.configure_payload(job.payload)`;
3. construct `BaselineTrainingContext` from the train IDs and bound checksums;
4. call `fold_adapter.predict(context, list(job.test_pair_ids), response_dim)` exactly once;
5. capture the verified backend `provenance_manifest`, including its execution manifest;
6. return predictions plus the real worker/checkpoint/payload/request checksums.

Never fabricate a checkpoint checksum from `{method, seed}`. Use the checkpoint SHA verified by
`_verify_execution_manifest`. Never construct `context_by_fold` before prediction; doing so would
leave a shared backend configured to the last fold.

Reassembly requires each covered pair exactly once, in `OOFFoldManifest.covered_pair_ids` order.
Missing, duplicate, extra, non-finite, or dimension-mismatched predictions make that seed fail.
The per-seed scalar is mean pair MSE against development **delta** on this fixed covered set.

## Task 5 — Report container and production entry

Implement strict, frozen containers:

- `SeedVariabilityStatus`: `COMPLETE`, `INCOMPLETE`
- `CoverageReport`
- `FoldExecutionRecord(method, seed, fold, fold_fit_role_artifact_sha256, payload_sha256,
  request_sha256, checkpoint_sha256, predictions_sha256, worker_identity_sha256)`
- `SeedComparatorSummary(method, ordered seed→OOF-MSE, mean, sample_std, min, max, range,
  failed seeds/classes, fold execution records)`
- `SeedVariabilityReport`

The report binds protocol, run ID, config SHA, registered seed order, deterministic roster,
OOF-manifest checksum, covered/uncovered pair-ID checksums, response-space checksum, base fit-role
artifact checksum, every fold-scoped fit-role artifact checksum, development-store content checksum,
worker locks, and all fold execution records. It uses
strict schema validation, finite floats, canonical JSON, a self-excluding checksum, atomic
write-once, and read-back verification.

Production entry:

```python
development_seed_variability(
    *,
    inputs: Phase2aInputs,
    development_outcome_store: DevelopmentOutcomeStore,
    oof_manifest: OOFFoldManifest,
    baseline_adapters: Mapping[str, BaselineAdapter],
    config: ComposePhase2Config,
    response_artifact: Mapping[str, object],
    fit_role_spec: FitRoleArtifactSpec,
    gene_order: Sequence[str],
    raw_data_sha256: str,
) -> SeedVariabilityReport
```

Use direct config fields: `config.registered_seeds`, `config.split_seed`, `config.oof_folds`, and
`config.uncovered_tolerance`. Require exact equality with the manifest and `Phase2aInputs`.

Catch expected per-job execution failures, record only a scrubbed exception class, and mark the
report `INCOMPLETE`. Do not catch `BaseException`. Internal contract/provenance violations fail the
whole call rather than being laundered into an ordinary failed-seed result.

## Task 6 — Pre-access ledger and Phase2b preflight binding

Write exactly `development_seed_variability.json` before Phase2b. Record its byte SHA under
`development_seed_variability` in the same in-memory ledger before
`persist_pre_access_ledger`; do not mutate an already-persisted snapshot.

`verify_seed_variability_for_preflight` accepts the report path plus trusted expected values from
the config, Phase2a bundle/method lock, OOF manifest, response artifact, fit-role artifact, and
development-store provenance. It verifies:

- regular direct-child file, no symlink;
- strict schema and embedded checksum;
- `COMPLETE` status;
- protocol/run/config identity;
- exact method and seed rosters;
- exact OOF-manifest and covered/uncovered checksums;
- response, fit-role, development-store, worker-lock and fold-execution bindings;
- the report byte SHA equals the pre-access ledger entry.

The scientific Phase2b signature receives the verified OOF-manifest path/checksum and seed report
path/checksum explicitly. Fixture Phase2b has a separate bounded fixture helper; it must not silently
bypass a scientific preflight branch.

## Task 7 — D1 handoff and ordering

D2 completes before D1 Task 3/5/7 wiring. D1 receives the verified
`development_seed_variability.json` path and its pre-access ledger SHA. The D1 terminal summary copies
only the report checksum and status; the final ledger and commit marker bind the complete file SHA.

If D2 is `INCOMPLETE`, missing, mismatched, or unverified, Phase2b remains seal-closed. There is no
placeholder report and no post-seal backfill.

## Task 8 — Verification

Required tests:

- known-answer fold manifest and coverage;
- shuffled pair-row alignment failure;
- held-out and excluded target leakage rejection;
- mutable backend isolation across folds and seeds;
- seed 11/23/37 observed in worker payload and provenance;
- real checkpoint/prediction checksum binding;
- fixed covered-set reassembly and known MSE;
- one failed fold/seed → `INCOMPLETE`, never partial-success `COMPLETE`;
- sealed-store, arbitrary-object, payload-factory and symlink rejection;
- report tamper, roster, run/config, OOF, response, fit-role and ledger mismatch rejection;
- write-once/read-back and deterministic bytes;
- `sealed_access_count == 0` throughout.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider \
  tests/alive/compose/test_select.py \
  tests/alive/compose/test_phase2a.py \
  tests/alive/compose/test_baseline_subprocess.py \
  tests/alive/compose/test_seed_variability.py \
  tests/alive/compose/test_phase2b.py -q
PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
git diff --check
```

Real GEARS/CPA seed results remain pod-only, but the same production entry and workers must be used;
the pod run may supply environment paths and data, not an alternate evaluation implementation.
