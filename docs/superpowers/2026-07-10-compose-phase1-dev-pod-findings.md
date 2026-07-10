# COMPOSE dev-pod Phase 1 — real GEARS/CPA workers: findings and current status

> **Scope and status:** This note separates an earlier A100 development-pod
> observation from the worker and dev-smoke code that exists now. It is not
> activation evidence, a scientific acceptance report, or permission to open the
> COMPOSE seal. No real-pod rerun has been performed after the current worker,
> checkpoint, resource, identity, split, and held-out-read fixes.

## 1. Evidence classes — do not merge them

### 1.1 Historical dev-pod observation (pre-fix code only)

An earlier development-pod smoke used 18,843 Norman cells reduced to 2,000
top-variable genes, 105 singles, 6 calibration combos, 3 development-held-out
combos, and response dimension 50. Under deliberately shortened 1–5-epoch runs,
the then-current GEARS and CPA workers emitted finite, non-trivial predictions and
the then-current controller accepted their envelopes.

| backend | historical representation | held-out pairs | historical observation |
|---|---|---:|---|
| GEARS | `raw_pseudobulk_approximation` | 3 | finite output; old controller integration completed |
| CPA | `cell_raw_counts` | 3 | finite output; old controller integration completed |

This observation established only that those old code paths could execute. It
does **not** validate the current workers because all of the following changed
afterward:

- GEARS resource acquisition, train/validation splitting, RNG binding, checkpoint
  contents, and fit-artifact loading;
- CPA defaults, control optimization boundary, validation split, DEG-mask source,
  RNG binding, checkpoint contents, and fit-artifact loading;
- dev-smoke expression access and source-content identity;
- controller-side worker identity propagation and durable checkpoint handling.

The 2,000-gene selection procedure and its ordered roster were not committed as a
registered, outcome-independent artifact. The historical smoke therefore cannot
settle the real-run gene universe or be promoted into current acceptance
evidence. Its finite outputs say nothing about model quality, comparator strength,
calibration, or generalization.

The earlier operational observation that a cold CPA import on a network-mounted
environment could exceed the availability-probe timeout also remains historical;
it must be rechecked in the final local-filesystem environment rather than treated
as a property of the current worker.

### 1.2 Current local verification (contract/logic only)

Current local synthetic and mock tests verify, without `gears`, `cpa`, a GPU,
Norman outcomes, external downloads, or seal access:

- stable-descriptor loading of the exact fit-role bytes after full role/leakage
  validation; neither fit body reopens the artifact pathname;
- deterministic seed propagation and role-exact optimization loaders;
- real trained-state checkpoint creation before requested-pair prediction;
- GEARS offline resource-manifest checks, staging, download guards, post-use
  revalidation, deterministic training/monitoring loaders, fixed-final-epoch
  selection, and temporary directory cleanup;
- CPA 0.8.5 defaults, reference-only controls, target-independent DEG masks, and
  OOD counterfactual construction;
- metadata-first dev split selection followed by expression reads of allowed rows
  only, including a guarded matrix test that raises on any held-out row access and
  a mutation-invariance test for held-out expression.

These tests support the code contracts. They do **not** demonstrate that the
current workers successfully fit real Norman data in the locked pod environments,
produce scientifically adequate predictions, or satisfy activation evidence.

## 2. Current scientific semantics

### 2.1 GEARS: raw-count path is activation-blocked

The current worker deliberately supplies the verified artifact's raw-count matrix
to GEARS and maps its pseudobulk output through
`raw_pseudobulk_approximation`. This is a compatibility/plumbing path only.

It is **not a reproduction of the published/default GEARS pipeline**. The
official GEARS data tutorial normalizes total counts, applies `log1p`, and selects
highly variable genes before `PertData.new_data_process`; the current raw-count
path changes differential-expression ranking, the training loss scale, and the
co-expression graph. The worker records this state as
`ACTIVATION_BLOCKED_PENDING_PUBLISHED_SCALE_DECISION`. Neither the historical
finite smoke result nor the method-locked output representation resolves the
native input-scale question.

Scientific activation therefore requires an owner-reviewed, preregistered
decision that either:

1. reproduces the published normalized/HVG GEARS pipeline and defines a valid
   bridge into COMPOSE response space; or
2. registers the raw-count variant as a distinct comparator, stops calling it the
   published/default baseline, and validates its behavior and approximation bias.

No worker may silently choose between those alternatives at runtime.

### 2.2 GEARS loaders: all fit graphs train, monitoring is not validation

The old statement that `split="no_test"` fits all non-sealed conditions with a
gene-based validation holdout was incorrect and is withdrawn. In
`cell-gears==0.1.2`, `no_test` withholds complete perturbation conditions at
random; `train_gene_set_size` does not provide the claimed gene-based behavior.

The current worker does not use `no_test`. `cell-gears==0.1.2` computes DE/nonzero
metadata before loaders exist and later constructs coexpression/GO graphs from
the processed fit data. A held-out cell subset would therefore not be an
independent validation set. The worker now states this limitation directly and
installs deterministic custom loaders under the payload seed:

- every non-control processed graph enters training;
- a deterministic 10% duplicate subset of those same training graphs supplies
  the `val_loader` GEARS requires, but is labeled monitoring-only;
- controls remain reference data and never enter optimization loaders;
- prediction fails if either requested gene lacks a trained single condition.
- the worker discards GEARS' monitoring-selected `best_model` and binds the fixed
  final-epoch `model` into the checkpoint and prediction path.

This closes the accidental whole-condition holdout and prevents monitoring data
from selecting the checkpoint. It does not claim an independent internal
generalization estimate; COMPOSE's registered outer calibration OOF evaluation
remains the comparator assessment. Loader counts and selection policy are
inspectable in the checkpoint. The design is still subject to real-pod rerun.

### 2.3 CPA: version-exact defaults and target-independent validation

The current CPA worker targets `cpa-tools==0.8.5`, verifies that installed
distribution version at runtime, and explicitly passes that version's model and
trainer defaults. These include the NB likelihood, latent/encoder/decoder/doser
architecture, batch size 128, the data-dependent maximum-epoch formula,
validation interval 10, and patience 10. The complete `CPATrainingPlan` default
roster is also explicit: autoencoder/adversary/doser learning rates and weight
decays, adversary depth/width/normalization/dropout, update cadence and loss,
warmups, mixup, StepLR schedule, and clipping policy are passed through
`plan_kwargs` and stored in the checkpoint config. DEG preprocessing likewise
registers and passes the reference+train row scope, 10,000-count normalization,
`log1p`, and top-50 absolute-effect ranking of every non-control condition
against the same-covariate `K562_ctrl` reference. The registered `t-test` matches
the Scanpy default used by the CPA/chemCPA preprocessing convention; the worker
passes it and all remaining ranking options explicitly rather than comparing a
condition against a biologically mixed `rest` pool. The
payload seed is passed to Python, NumPy, Torch/CUDA, and the CPA module. There is
no production smoke-epoch environment override. CPA's implicit `save_path="./"`
side effect is disabled because the worker writes its own governed checkpoint.

Optimization roles are exactly `{singles, combo_calibration}`. Verified control
rows remain reference-only. Train/validation assignment is deterministic within
each perturbation condition. The control reference and every non-control DEG
group must retain at least two cells because Scanpy's registered t-test rejects a
one-sample target or reference. Two-cell conditions are train-only; conditions
with at least three cells may contribute validation cells while retaining two
training cells; singleton conditions fail closed. At least one validation cell is
still required globally. The exact per-condition counts enter the checkpoint.
DEG masks are computed from reference controls plus optimization-train rows only;
internal validation expression cannot alter preprocessing.

Requested combinations are absent from `setup_anndata`, model construction, DEG
selection, and training. This matters because CPA 0.8.5 sizes its perturbation
adversary and condition weights from every condition category, including OOD
rows. Only after the fitted state is checkpointed does the adapter copy registered
control rows into a query, validate that control-only query against the trained
manager, and replace the model-facing perturbation id/dose arrays with the two
already-trained single-gene embeddings at dose 1.0. Thus changing the requested
pair roster cannot change the fitted state. Negative native means are clipped to
zero before response projection, as declared in the exact worker config.
Queries are processed one pair × control block at a time and projected
immediately, bounding peak prediction memory independently of the number of
requested pairs while retaining one shared fit/checkpoint. Predictions remain
per-cell NB means in the registered `cell_raw_counts` representation.

This is a code-level contract, not current real-pod evidence. A rerun must also
confirm that cpa-tools 0.8.5's transferred AnnData manager preserves the modified
registered perturbation arrays during `predict`, in addition to the exact locked
environment, memory behavior, convergence, output scale, and controller
integration.

## 3. Held-out expression and fit boundary

The dev-smoke builder now determines development-held-out and calibration pair
IDs from perturbation metadata before reading expression. It then reads only
control, single, and calibration rows. In CLI use the source AnnData is opened in
backed mode, and the raw-count slicer receives the already allowed row indices;
held-out expression is never eagerly materialized or placed in an intermediate
matrix.

The allowed-source digest is path-independent and binds canonical CSR counts,
ordered source-row IDs, perturbation tokens, and gene order. Mutating a held-out
expression row leaves this identity and the artifact content identity unchanged;
attempting to access such a row fails the guarded-reader test. Thus the current
dev-smoke claim is narrower and auditable: the development-held-out expression is
not read. The pair IDs still enter metadata guards and counterfactual prediction,
as they must, but their outcomes do not enter the fit payload.

This dev-held-out split is not itself the production sealed manifest. It proves a
read boundary on synthetic/local inputs and opens no COMPOSE seal.

## 4. Checkpoint, identity, and resource hardening now present

- GEARS persists the fixed final-epoch `model.state_dict()` together with the
  seed, fit-artifact content digest, gene-order digest, resource-manifest digest,
  input-scale status, training constants, and monitoring-loader manifest before
  any requested-pair prediction. The duplicated monitoring subset never selects
  this checkpoint.
- CPA persists the trained `model.module.state_dict()` together with its seed and
  code-registered optimization contract before prediction.
- The controller verifies the worker-reported checkpoint digest and, in current
  local/fixture execution, atomically installs the exact bytes into a read-only,
  content-addressed checkpoint store. It re-verifies the durable path whenever
  backend provenance is read.
- The controller re-hashes actual worker-config, resource-manifest,
  requirements-lock, adapter-artifact, and worker-script files. Identity paths
  and expected digests are passed through a sanitized private environment rather
  than inherited ambient values. Each worker requires exact equality between the
  registered JSON and the code's runtime constants, checks the installed package
  version, and reports only those observed identities. Scientific worker sources
  are packaged as deterministic `.pyz` archives whose outer worker SHA binds the
  entrypoint plus the exact ALIVE helper roster. The controller executes a fresh
  read-only snapshot of that verified bundle, injects only that snapshot as the
  trusted Python path, and rejects helper modules loaded from an installed or
  editable checkout.
- Worker launch uses controller-fixed environment values rather than an ambient
  denylist or scheduler-variable allowlist: loader injection, Python path/home,
  user-site, virtual-environment, CUDA routing, locale/temp, and unrelated
  process variables are not inherited. UTF-8, UTC, headless Matplotlib, no bytecode
  writes, `PYTHONHASHSEED=<payload seed>`, and
  `CUBLAS_WORKSPACE_CONFIG=:4096:8` are set explicitly. The availability probe
  uses the same environment. Both workers require CUDA, deterministic Torch
  algorithms, float32, their exact installed distribution version, and a regular
  backend module origin below the launched `sys.prefix`.
- GEARS requires a controller-bound resource manifest, hashes every required
  bundle file, stages only those verified bytes into regular files in a fresh
  temporary directory, rejects package-internal download/substitution attempts,
  and re-hashes the staged snapshot after use.

These are material improvements, but the scientific identity chain is not yet
complete. Both scientific workers now consume the exact controller-bound config,
resource, environment-lock, and adapter identities; no worker-side `POD-FILL`
identity remains. The scientific assembler still intentionally fails closed
because no committed, versioned adapter manifest and corresponding final config
files are wired. Fixture-mode assembly is not scientific approval.

There is also an explicit storage-architecture gap: scientific
`approved_artifacts_root` is a content-addressed read-only input snapshot, while
the current content-addressed checkpoint installer is local/fixture-only and
would create `.worker_checkpoints` below its supplied root. The production
assembler never enables that local write for scientific mode; the backend fails
before worker launch with “no registered durable checkpoint output” instead of
mutating even a mistakenly writable input snapshot. A separately registered
writable staging destination plus immutable object-store
publication/version/SHA contract is still required for activation.

## 5. Remaining activation blockers

All of the following must be resolved and rerun before a GO decision:

1. **GEARS native scale and method claim.** Settle published normalized/HVG versus
   separately named raw-count comparator; bind the choice and transformation into
   the worker config and run identity. Complete the registered
   pseudobulk-approximation bias analysis where applicable.
2. **Gene universe.** Preregister an outcome-independent ordered gene roster that
   is computationally feasible, contains the required response/perturbation
   genes, defines missing-gene behavior, and is bound by digest. The historical
   2,000 top-variable set is not that artifact.
3. **Scientific assembler and adapter identity.** Commit and wire the versioned
   adapter manifest and real adapter artifacts for both methods. The workers
   already verify exact registered worker-config/resource/environment bytes; the
   scientific assembler must now supply those real artifacts and pass without
   fixture trust.
4. **Method configuration artifacts.** Materialize and commit the exact JSON
   objects already enforced by code, including version, preprocessing, roles,
   within-condition split, seed, all training defaults, post-fit CPA query policy,
   representation, negative-value policy, resource roster, and gene universe.
   Registered bytes and runtime code must remain equal fail-closed.
5. **Dependencies and resources.** Finalize package revisions and environment
   status in the active config; provide the content-addressed wheel/sdist
   manifest, container image digest, and immutable GEARS resource bundle used by
   the run. The worker itself must be the deterministic method-specific `.pyz`
   execution bundle built from the exact approved Git SHA: its existing
   `worker_script.sha256` binds the entrypoint, exact eight-file ALIVE helper
   roster, and canonical internal manifest, so neither a repo `PYTHONPATH` nor an
   editable/manual ALIVE install is accepted. A full project wheel is unsuitable
   for CPA because ALIVE declares Python >=3.11 while the locked CPA environment
   requires Python 3.10. Bind the canonical interpreter node/build/digest and
   every third-party wheel `RECORD` identity, not only the top-level package
   version and requirements text. No fit-time external access is permitted.
6. **Current real-pod rerun.** On a clean checkout of the exact owner-approved
   Git SHA, rerun both unshortened workers under their locked environments and
   capture immutable command logs, pair rosters, fit-role/row identities, actual
   checkpoints, predictions, execution manifests, resource identities, GPU/env
   details, and controller verification. Historical smoke files cannot be
   relabeled as this evidence.
7. **Config and activation evidence.** Fill every active-config blocker only
   after the scientific decisions above, then regenerate rank, detectable-effect,
   power/measurability, approximation-bias, and dependency evidence against the
   final config digest and exact Git SHA. Any later config/code/gene-roster change
   invalidates that evidence.
8. **Durable checkpoint/provenance destination.** Add a separately registered
   destination that does not mutate the read-only approved-input snapshot;
   atomically stage each checkpoint there, then publish every required artifact
   to immutable object storage with object version and matching SHA-256. The
   dependency lock remains `INCOMPLETE` until its validator accepts the complete
   evidence set.

Only after these blockers pass may the owner review a separate sealed-run GO
manifest. The seal must then be opened once on the approved scientific identity;
none of the development work or historical observations in this note authorizes
that action.
