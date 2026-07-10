# COMPOSE dev-pod Phase 1 — real GEARS/CPA workers: findings

> **Scope:** dev-pod authoring + outcome-free Norman fit-role smoke of the real
> `gears_worker.py` / `cpa_worker.py` fit bodies (plan
> `docs/superpowers/plans/2026-07-09-compose-dev-pod-real-workers.md`, Phase 1).
> **Opens NO seal.** Reads no sealed outcome; fits no model on any sealed pair.
> This is a development-pod findings note, not release-gate evidence.

## What Phase 1 established

- Both real `_fit_and_predict` bodies are authored against the frozen worker
  contract (the stub scaffold's `read_payload` → `validate_fit_role_artifact` →
  `_fit_and_predict` → `write_predictions` seam is unchanged; only the fit body
  differs) and run end-to-end under their locked envs on a real Norman fit-role
  smoke, emitting a contract-valid `{predictions, execution_manifest}` envelope
  that the merged `SubprocessBaselineBackend` + `_verify_execution_manifest`
  accepts.
- The sealed requested pairs enter each worker ONLY as `sealed_pair_ids` to the
  leakage guard; the fit-role artifact materialises no sealed combo cell
  (recomputed zero sealed/calibration overlap).

## Smoke results (dev pod, reduced 2,000-gene universe)

On a Norman fit-role smoke (18,843 cells → 2,000 top-variable genes; 105 singles,
6 calibration + 3 sealed combos, recomputed zero overlap; response_dim 50):

| backend | representation | sealed pairs | dim | finite | full backend integration |
|---|---|---|---|---|---|
| GEARS | raw_pseudobulk_approximation | 3 | 50 | yes | `is_available` True → `CONTROLLER_INTEGRATION_OK` |
| CPA | cell_raw_counts | 3 | 50 | yes | `is_available` True → `CONTROLLER_INTEGRATION_OK` |

Each worker runs end-to-end through the merged `SubprocessBaselineBackend`
(`configure_payload` → `predict` → `read_predictions` →
`_verify_execution_manifest`): the controller recomputes the worker / checkpoint /
ordered-request / fit-artifact digests and mirrors the adapter / config / resource /
environment / representation against the `ExecutionIdentityLock`, and accepts the
manifest. The per-pair deltas are finite and non-trivial; their near-uniform
magnitude reflects the deliberately tiny 1–5-epoch smoke fits — this smoke proves
the plumbing + leakage boundary, not scientific fit quality.

## Design decisions confirmed against the real APIs

- **GEARS prediction space.** GEARS' `new_data_process` does not normalise `X`;
  it trains/predicts in the space of the supplied matrix. Feeding the raw-count
  fit-role artifact makes GEARS output a raw-count pseudobulk, which is exactly
  what the config-locked `gears.prediction_representation =
  raw_pseudobulk_approximation` expects (the projection then normalises +
  log1p's; the Task-2.2 bias metric documents the pseudobulk-vs-per-cell
  discrepancy). This is a committed design, not a worker choice.
- **GEARS split.** `split="no_test"` fits on all non-sealed conditions with a
  gene-based train/val holdout for early stopping and no held-out test set —
  `GEARS.train()` skips test evaluation when no test loader exists. The sealed
  pairs are absent from the data entirely; each sealed gene occurs as a trained
  single, so it stays in `GEARS.pert_list` and the unseen combo is predicted
  counterfactually.
- **CPA prediction.** CPA composes an unseen combo `g+h` from the per-gene
  embeddings learned for the singles `g+ctrl` / `h+ctrl`; the counterfactual is
  control cells relabeled to `g+h`, predicted to per-cell raw counts
  (`obsm["CPA_pred"]`), consistent with `cpa.prediction_representation =
  cell_raw_counts` (exact).

## Findings / landmines (the reason a RUN-gate exists)

1. **Full gene universe is infeasible for GEARS.** GEARS builds a per-cell graph
   and a full-transcriptome output head; on the full 33,694-gene Norman universe
   the co-expression / GO-graph construction did not complete in a practical time
   (>9 min, GPU idle). GEARS is designed for a reduced gene set (~5k in the
   published pipeline). The dev smoke reduces the universe to the top-variable
   genes to exercise the plumbing. **Real-run implication:** the COMPOSE gene
   universe fed to GEARS must be a pre-registered reduced set that contains the
   response HVGs — a genuine gene-universe-sizing decision, not settled here.
2. **Worker import under the minimal locked env (integration landmine).** The
   workers import only the pure-python contract modules
   (`baseline_subprocess` / `fit_role` / `response`), but `alive/compose/__init__.py`
   eagerly imported the full Phase-1 stack (`config` → `yaml`, gates, identify,
   phase1, synthetic) that the isolated gears/cpa science envs do not carry.
   Fixed by making the package init lazy (PEP 562 `__getattr__`); both env
   pythons now import `alive.compose` cleanly and the full compose suite stays
   green. The controller still needs `alive` importable in the worker env
   (PYTHONPATH or an install) — an integration point for the sealed run.
3. **Empty-test split crash.** A `custom` split with `test: []` builds an empty
   test loader; `GEARS.train()` then crashes in its post-train test evaluation
   (`torch.stack([])`). `no_test` is the correct mode.
4. **CPA counterfactual needs the sealed category registered — with cells.** CPA
   composes an unseen combo from per-gene embeddings, but two lower-level checks
   reject a naive counterfactual: scvi's `transfer_fields` rejects an unseen
   `condition` category (`Category CEBPE+RUNX1T1 not found in source registry`),
   and a zero-cell category then zero-divides CPA's per-drug class weight
   (`n_obs / n_positive`). The correct pattern (and CPA's documented OOD flow) is
   to append, for each sealed combo, a block of CONTROL cells relabeled to that
   combo condition and marked `split='ood'`: the counterfactual substrate. This
   registers the category WITH cells (no transfer error, no zero-division) but
   HOLDS those cells out of training; their expression is control, so no sealed
   cell, outcome, or expression row is ever read — it opens no leak. Prediction
   slices those ood rows' `obsm["CPA_pred"]`.

5. **CPA `is_available` probe can flake on a network-mounted env.** GEARS runs
   fully through the merged `SubprocessBaselineBackend` (`is_available` True →
   `predict` → `_verify_execution_manifest` accepts the manifest). CPA's worker
   runs identically and its manifest passes the same verification, but the
   backend's availability probe (`python -c "import cpa"`, `timeout=120`)
   intermittently returned False when the `cpa_env` lives on the `/workspace`
   network mount: `import cpa` pulls the heavy scvi/jax/torch chain, which is ~29 s
   warm but can exceed the 120 s probe on a cold/contended network-volume cache.
   The worker is correct — this is an env-placement + probe-timeout concern.
   **Sealed-run implication:** place `cpa_env` on a local (non-network) filesystem
   and/or warm the import (a `BaselineUnavailable` here fails the Phase-2a freeze
   as INVALID rather than silently skipping — so it is safe, but it would abort a
   real run). Confirmed: with a warm cache the CPA backend integration passes.

## The dependency-lock COMPLETE flip remains infra-blocked (by design)

`src/alive/compose/activation_evidence.py` fail-closes: flipping the dependency
lock from `INCOMPLETE` to `COMPLETE` requires, per backend, **durable immutable
object storage** for six artifacts (Norman source, fit-role artifact, row-identity
manifest, smoke script, command log, checkpoint) — each with a non-`file:` URI +
an immutable object version + a matching SHA-256 — plus a **content-addressed
wheelhouse** (every wheel/sdist SHA-256 for both env locks) and a **container
image digest**. These require owner-provided infrastructure (an object store, a
pushed container image); the validator rightly refuses a hash for an unlocatable
object. **The lock therefore stays honestly `INCOMPLETE`**; the achievable
Phase-1 deliverable is the real workers + the outcome-free Norman smoke +
controller integration + the pair roster (with recomputed zero-overlap),
checkpoint, and command log that a dev pod can genuinely produce.

## Not done here (owner-gated / later)

- Real-run gene-universe sizing + the published GEARS/CPA revisions (decisions
  #1/#3 remain POD-VERIFY against the installed wheels).
- Config finalization + activation-evidence regeneration (Phase 2).
- The COMPLETE-evidence infrastructure above.
- The seal — opened once on a separate owner-SHA-approved sealed-run pod.
