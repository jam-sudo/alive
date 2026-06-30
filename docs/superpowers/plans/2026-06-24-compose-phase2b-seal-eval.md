# COMPOSE-K562-v1 Phase 2b Seal and Verdict — Corrected Implementation Plan

> **Status:** PRE-REGISTERED, ACTIVATION BLOCKED
> **Scope:** seal machinery and inference tested only with synthetic/tiny fixtures. No real Norman
> sealed outcome may be opened under this plan.
> **Contract:** `CLAUDE.md`, COMPOSE design spec §10.5–§10.6,
> `configs/compose_k562_v1_phase2.yaml`, and the corrected Phase-2a plan.

## 1. Goal

Build the confirmatory evaluator with a real structural seal boundary:

1. predictions and all non-outcome validation are frozen before access;
2. the evaluator receives an outcome store, never raw sealed truth;
3. one audited call releases both registered regimes;
4. headline and secondary regimes are scored separately;
5. the exact comparator family receives simultaneous inference;
6. every consumed seal produces a terminal immutable result, including failure/invalid cases;
7. provenance binds the result to the complete composite run identity.

## 2. Security and scientific invariants

### 2.1 Structural outcome boundary

The scientific `run_phase2b` API must not accept:

- `sealed_truth`;
- an outcome dictionary or array;
- a path to a sealed outcome file;
- an AnnData object exposing sealed rows.

It accepts only a `ComposeOutcomeStore` implementing:

```python
evaluate_sealed_once(run_id, pair_ids) -> Mapping[pair_id, ObservedPair]
sealed_access_count -> int
audit_records() -> tuple[...]
```

The store is constructed from an index/source/manifest outside the evaluator. Ordinary reads reject
both sealed roles. The audit record is durably claimed before materialisation, so a crash burns the
run ID.

### 2.2 One access, two regimes

`sealed_double_unseen` and `sealed_single_unseen` are opened in one audited call, but retain their role
labels from the immutable pair manifest.

- Only double-unseen drives the sealed-axis verdict.
- Single-unseen is a registered secondary result.
- Metrics, sample counts, intervals and failures are reported separately by regime.
- Pooling regimes for a larger apparent sample size is prohibited.

### 2.3 Preflight before seal access

Before calling the store, validate everything that does not require outcomes:

- active protocol authorization for scientific mode;
- futility status is `CONTINUE`;
- exact composite run ID and clean ledger;
- exact required method roster:
  `l1_bilinear_identifiable`, `additive`, `gears`, `cpa`, `id_only`,
  `l3_hypernetwork`;
- exact pair-ID sets for both regimes;
- no missing or extra predictions;
- canonical pair IDs, shapes and finite values;
- response dimension;
- method-lock and frozen-bundle checksums;
- config, manifest, data-card, sequence mapping, raw/source, environment and dependency hashes;
- output paths do not already exist;
- sealed access count is zero.

No `all([])` or “available comparator” behavior is allowed. Missing one registered comparator is a
preflight failure and the seal remains closed.

### 2.4 Post-access failure semantics

The access audit is written before materialisation. Once access is claimed, every exit path must leave
a terminal write-once artifact:

- normal result;
- `INVALID` result for completeness, finiteness, alignment, provenance or metric failures;
- `EVALUATION_ABORTED_AFTER_SEAL` failure record for unexpected exceptions.

The failure record includes run ID, audit checksum, exception class/message, stage and all preflight
artifact checksums, but never raw outcomes. A consumed run ID is never retried.

## 3. Planned modules

| File | Responsibility |
|---|---|
| `src/alive/compose/outcome_store.py` | Manifest-backed sealed store and append-only audit |
| `src/alive/compose/preflight.py` | Outcome-free validation of frozen evaluation inputs |
| `src/alive/compose/inference2.py` | Validated shared-resample simultaneous bounds |
| `src/alive/compose/secondary2.py` | Regime-specific registered secondary metrics |
| `src/alive/compose/verdict2.py` | Exact-roster headline verdict and two-axis result |
| `src/alive/compose/terminal.py` | Write-once result/failure artifacts |
| `src/alive/compose/phase2b.py` | Preflight → one access → regime scoring → terminal result |

## 4. Task sequence

### Task 1 — Manifest-backed outcome store

Mirror the established `ReplogleOutcomeStore` integrity pattern rather than persisting an outcome
dictionary inside the run directory.

`ComposeOutcomeStore` takes:

- pair index mapping canonical pair IDs to bounded source row indices;
- source AnnData/path;
- immutable pair manifest with both sealed roles;
- append-only audit path.

Required behavior:

1. `read_unsealed` refuses every ID assigned to either sealed role.
2. `evaluate_sealed_once` validates the complete requested set before reading any row.
3. It refuses empty, duplicate, unknown, unsealed, missing or extra pair IDs.
4. It refuses any previous audit record on the same audit path, regardless of process or run ID.
5. It appends an audit record before materialisation containing run ID, sorted IDs, role counts,
   manifest checksum and request checksum.
6. It slices only requested rows; no global densification.
7. Audit corruption or a partial line fails closed.

Fixture tests use a tiny in-memory source hidden behind the store. Tests never pass truth to
`run_phase2b`.

Required tests include second access from a fresh store instance, different-run-ID reuse, wrong role,
partial request, extra ID, materialisation crash after audit claim and audit tampering.

### Task 2 — Frozen bundle and outcome-free preflight

Load the Phase-2a `FrozenPredictionBundle` and the pair manifest. Require exact equality between:

- registered method roster and bundle roster;
- manifest pair IDs and prediction IDs for each regime;
- expected response dimension and every prediction vector;
- bundle run ID and recomputed composite run ID;
- bundle/ledger artifact checksums.

Preflight returns a frozen `EvaluationLock` containing only IDs, role labels, predictions, thresholds,
hashes and seeds. It contains no measured outcomes.

Tests must verify each missing/extra method and pair fails before a spy store records any access.

### Task 3 — Simultaneous inference

Implement one-sided non-studentized max-deviation bounds for the exact comparator sequence from config.

For each regime and comparator:

```text
theta_C = (mean(e_C) - mean(e_L1)) / max(mean(e_C), 1e-12)
q = quantile_confidence(max_C(theta_C - theta_C_boot))
lower_C = theta_C - q
```

Validation must require:

- non-empty exact comparator family;
- equal non-zero lengths;
- one-dimensional, finite and non-negative errors;
- `0 < confidence < 1`;
- registered replicate count;
- deterministic per-replicate indices using
  `SeedSequence(entropy=seed, spawn_key=(replicate,))`.

The returned artifact records point estimates, bounds, common half-width, comparator order, seed,
replicate count and checksum.

Known-answer tests include strong win, exact null, one degraded comparator, small samples,
zero-comparator error, non-finite values, missing comparator and process-stable determinism.

### Task 4 — Regime-specific primary and secondary scoring

After the single store access:

1. preserve manifest order and role;
2. transform observed populations using the frozen response-space artifact;
3. align each method prediction by canonical pair ID;
4. compute pair MSE;
5. run simultaneous inference independently for double-unseen and single-unseen.

Secondary reporting per regime:

- GI explained fraction with an interval;
- GI structure recovery only if the registered class-label manifest and prediction-to-class rule pass
  provenance checks; otherwise explicit `NOT_EVALUABLE`;
- the exact interval method and any material-regression margin must come from the activated config;
  absence or conflict with `CLAUDE.md` governance is an activation/preflight failure;
- pair-level errors and effect-size summaries;
- sample count and failed/missing IDs.

Secondary metrics never affect the sealed verdict.

### Task 5 — Exact-roster verdict mapping

`sealed_verdict` accepts:

- headline double-unseen bounds;
- the explicit registered comparator tuple;
- additive and learned margins;
- an `IntegrityReport`.

It must:

- return `INVALID` if integrity is invalid;
- reject absent or extra comparator keys;
- return `GI_LEARNABLE_WIN` only if additive lower bound `> 0.05` and every registered learned
  comparator lower bound `> 0`;
- return `PARTIAL` if additive clears 0.05 but any learned comparator fails;
- otherwise return `NO_DISTINCT_WIN`.

An empty learned family is an error, never a win. Single-unseen results cannot enter this function.

The combined result always reports method and sealed axes separately. `METHOD_VALIDATED` is never
described as evidence of real generalization.

### Task 6 — Complete provenance and run identity

Before access, recompute:

```text
run_id = compute_run_id(
    config_digest,
    canonical_data_card_digest,
    raw_or_source_sha256,
    sequence_mapping_sha256,
)
```

Verify and record:

- active protocol and resolved config;
- pair manifest and exclusion manifest;
- data-card and raw/processed hashes;
- sequence mapping and feature-bank hashes;
- response-space and factor artifacts;
- model lock and frozen prediction bundle;
- Git SHA and clean-state policy;
- dependency lock, GEARS/CPA revisions, Python/platform, device and precision;
- registered seeds;
- seal audit;
- regime result and terminal report checksums.

Use `RunLedger` write-once artifact names. Upstream ledger absence or mismatch detected during
preflight aborts before access and leaves the seal closed. Audit/result mismatches detectable only
after access make the consumed evaluation `INVALID`.

### Task 7 — Terminal artifact writer

Implement a single-owner terminal state machine:

```text
PREPARED -> ACCESS_CLAIMED -> COMPLETE
                         \-> INVALID
                         \-> ABORTED_AFTER_SEAL
```

Requirements:

- acquire an exclusive evaluation lock before preflight;
- refuse an existing terminal artifact or prior audit;
- write canonical JSON through a same-directory temporary file, flush/fsync, then install without
  overwriting an existing destination;
- append ledger entries only after the corresponding file exists and verifies;
- record an abort artifact in a `try/except/finally` boundary after access claim;
- never include raw outcome matrices in report, provenance or exception text.

Crash-injection tests cover every stage before and after access.

### Task 8 — Phase-2b orchestrator

Scientific interface:

```python
run_phase2b(
    *,
    run_dir,
    outcome_store,
    frozen_bundle,
    pair_manifest,
    response_artifact,
    config,
    ledger,
    activation_record,
) -> Phase2bResult
```

Execution order:

1. acquire exclusive lock;
2. run outcome-free preflight;
3. ensure access count zero;
4. persist `EvaluationLock`/intent checksum;
5. enter the terminal-result protection boundary;
6. call `evaluate_sealed_once` exactly once for the union of registered sealed IDs inside that
   boundary;
7. derive truth in the frozen response space;
8. score each regime separately;
9. compute headline inference and descriptive secondary inference;
10. build integrity report and verdict;
11. verify audit/run ID/provenance;
12. write terminal result and ledger entries once.

The orchestrator never seals data, never accepts truth, never fits models and never changes the
frozen bundle.

## 5. Required integration tests

At minimum:

1. preflight failure keeps access count zero;
2. missing GEARS/CPA/ID-only/L3 keeps access count zero;
3. raw truth cannot be supplied through the public API;
4. predictions are computed/frozen before access;
5. one access releases both roles and preserves role separation;
6. headline verdict uses double-unseen only;
7. changing single-unseen outcomes cannot change the headline verdict;
8. second access fails across fresh processes/store instances;
9. post-access metric failure writes `INVALID` or `ABORTED_AFTER_SEAL`;
10. materialisation failure burns the run and writes a failure record;
11. provenance tampering yields `INVALID`;
12. no terminal artifact contains raw outcome arrays;
13. result/report/ledger hashes verify;
14. futility-stopped runs cannot invoke Phase 2b.

## 6. Verification commands

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/alive/compose
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
git diff --check
```

No real sealed evaluation, external data access or write-mode formatter is permitted while executing
this implementation plan.

## 7. Exit criteria

Phase 2b implementation is complete only when:

- the evaluator has no raw-truth parameter;
- preflight is exhaustive and outcome-free;
- exact comparator and pair rosters are enforced;
- one access covers both regimes without pooling them;
- every consumed access leaves a terminal artifact;
- the headline verdict is double-unseen-only;
- registered secondary results are reported per regime;
- complete composite provenance and audit checks pass;
- all integration and crash-injection tests pass.

Even then, real execution remains blocked until the owner activation commit and every §10.1
activation requirement are complete.
