# COMPOSE GEARS decision probe — conforming A100 rerun

> **Protocol:** `COMPOSE-K562-v1` (ACTIVE). **Status:** LOCAL GENERATOR + FIT-INPUT PREPARATION IMPLEMENTED;
> Probe A pod admission awaits a clean reviewed Git SHA; Probe B timing runner and scientific output bridge remain
> blocked as specified below.
> **Opens NO official seal.** This runbook replaces the superseded
> `../2026-07-10-compose-gears-decision-probe-plan.md`. The 2026-07-11 as-run harness is quarantined forensic
> evidence and MUST NOT be imported, copied, or executed.

## 0. Objective and authority

Produce decision-grade, durable evidence for two questions only:

1. **Probe A:** characterize the pinned `cell-gears==0.1.2` preprocessing/prediction scale and test whether a
   registered bridge to the frozen COMPOSE response projection is mathematically and empirically valid.
2. **Probe B:** measure GEARS resource cost for candidate method-specific rosters `R_gears` without changing the
   scientific fit-role/response universe `U_full` or touching any sealed expression.

The run may inform the owner's later choice of representation and `N_target`. It may not finalize config, alter
the response operator, regenerate activation evidence, fit a scientific confirmatory run, or access a sealed
outcome. Any such work requires a separate reviewed plan and, for evaluation, explicit owner authorization.

## 1. Non-negotiable architecture

The only permitted data flow is:

1. open the source `.h5ad` in backed/read-only mode and read `obs`/`var` metadata only;
2. resolve the outcome-independent pair manifest and exact development roles before touching `X`;
3. read only control, single, and combo-calibration rows to create and validate the full-gene fit-role artifact
   `U_full`; a reader-spy proof must show that no dev-sealed row index reaches the expression reader;
4. fit/freeze the response projection on its registered non-sealed roles over `U_full`;
5. generate exact-size `R_gears` from the reviewed GEARS roster generator using frozen response HVGs plus the
   globally eligible perturbation genes as mandatory set `M`;
6. normalize allowed raw GEARS fit rows over `U_full` first and subset to `R_gears` second;
7. never renormalize a reduced GEARS prediction by its reduced sum. Probe A must establish that predictions are
   already on the registered full-library log scale before a separate scientific output bridge may be built;
8. run resource/behavior probes without any `ComposeOutcomeStore` construction.

Forbidden shortcuts include eager `read_h5ad` of source expression, reducing source AnnData before role
resolution, selecting top `N` then force-adding genes, deriving roles from sealed request payloads, recomputing
response HVGs on a reduced roster, and monkeypatching a scientific worker without recording the exact harness
identity and overrides.

## 2. Local gates — all must be green before a pod is opened

### 2.1 Design and implementation

- [x] Revised `specs/2026-07-11-compose-gene-universe-design.md` received independent review PASS tied to an
  exact Git SHA and durable verifier-output SHA-256.
- [x] `src/alive/compose/gene_universe.py` implements report/freeze modes, exact `N_target`, lineage binding,
  write-once output, and every negative test in spec §9.
- [x] The fit-input adapter keeps fit-role/response artifacts on `U_full`, normalizes full raw rows before exact
  roster subset, and passes dense/sparse known-answer and lineage tests. This does **not** authorize output
  remapping.
- [x] The maintained dev-preparation path uses backed metadata-first selection. The existing
  `scripts/compose/build_dev_smoke_payload.py` reader-spy and sealed-mutation invariance tests remain green.
- [x] `scripts/compose/gears_decision_probe.py` builds exact roster/report artifacts from digest-bound candidate,
  GO-node, alias, fit-role, and response inputs; then prepares/verifies a probe-only,
  full-normalize-then-subset AnnData. It cannot accept the original outcome source and contains no hardcoded pod
  path. `build-roster` emits a receipt last; preparation consumes the independently pinned receipt rather than a
  roster SHA computed from the candidate file, and offline verification requires the pinned probe-manifest SHA.
- [x] `build-roster` independently binds the derived GO-node JSON to the activation-validated resource manifest
  and exact manifested `gene2go_all.pkl` bytes/key roster. The worker freezes
  `perturbation_graph_policy=method_roster_intersect_gene2go` and invokes upstream
  `PertData(..., default_pert_graph=False)`; the legacy essential-symbol filter may not silently redefine global
  eligibility. Custom GO graph construction uses a private empty cwd and `save=False`; an ambient or persisted
  `./data/go_essential_<dataset>.csv` cache must never be read, written, or accepted as evidence.
- [ ] Before Probe B, extend the same maintained CLI with the reviewed GEARS timing subcommand and complete raw
  command/resource sampling. Do not copy the archived timing harness.
- [x] The outcome-independent candidate decisions are frozen in the committed canonical
  `configs/compose_gears_probe_a_owner_policy_v1.json`: `log_normalized_pseudobulk`, no second
  library normalization, finite signed output preserved, exact determinism (`0`), and `1e-5` numerical
  equivalence tolerances. Probe A may accept or reject this candidate; it may not redefine it.
- [ ] After Phase-0 input preparation and before any Probe-A fit, derive the write-once
  `probe_a_registration.json` through maintained `build-probe-a-registration`. It uses schema
  `compose_gears_probe_a_registration_v2`, the approved Git SHA, the committed owner-policy SHA, and the exact
  positive `normalization_target` copied from the pinned prepared-input manifest. Externally record its emitted
  SHA-256 before fitting. No caller, verifier, or pod harness supplies a target or tolerance.

Probe A may run only after the completed implementation gates, candidate bridge/registration freeze,
exact-SHA review, and §3 identity checks. Probe B additionally requires the timing subcommand. No scientific
GEARS prediction may be activated unless the frozen output-bridge gate passes.

### 2.2 Required local verification

Run with cache/bytecode writes disabled where supported:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider \
  tests/alive/compose/test_fit_role.py \
  tests/alive/compose/test_dev_smoke_payload.py \
  tests/alive/compose/test_gene_universe.py \
  tests/alive/compose/test_gears_decision_probe_cli.py \
  tests/alive/compose/test_gears_worker_logic.py \
  tests/alive/compose/test_worker_contract.py
.venv/bin/ruff check --no-cache .
.venv/bin/ruff format --check --no-cache .
git diff --check
git status --short
```

The earlier 2026-07-19 implementation at commit `f62bd8c` passed the focused Probe-A suite (77), adjacent
contract suite (199), and full `tests/alive/compose` suite (1468), plus Ruff check, Ruff format check, and
`git diff --check`. The later owner-policy/registration-v2 correction must be verified and pinned at its own
clean commit. Its current local full COMPOSE suite is 1470 passing tests with one pre-existing AnnData warning,
plus clean Ruff check/format and `git diff --check`. These counts establish local implementation readiness only;
exact-SHA independent review and the run-specific registration pin remain separate pre-pod gates.

Record the final test counts and exact Git SHA in the pod evidence manifest.

## 3. Pod admission and identity capture

The owner supplies a temporary SSH key through a local file/agent, host, port, username, pod lifetime, and maximum
GPU-hours/cost. Never place credentials in the repository or transcript artifacts. On connection:

1. create a fresh work root on durable storage; abort if only ephemeral storage is available for evidence;
2. capture provider/pod ID, GPU model/UUID, driver/CUDA, CPU/RAM, filesystem capacity, UTC timestamps, and cost
   rate/limit;
3. transfer a Git bundle or archive from the exact reviewed clean commit; do not develop directly on the pod;
4. verify bundle commit, clean tree (including untracked files, replacement refs, and recursive submodules),
   `uv.lock`, the separate `docs/activation-evidence/compose/requirements.gears_env.lock`, container/image
   digest, the complete lock-matched installed package roster, GO
   resource manifest and bytes, Norman source bytes, pair manifest, alias artifact, full fit-role/response inputs,
   and every expected SHA-256;
5. disable network access for the fit after required immutable resources are present; fail on any attempted
   download or unmanifested resource read.

The roster receipt SHA and later probe-manifest SHA must be captured into the durable command/evidence ledger at
their publication boundary and read back from that ledger. The maintained CLI emits a canonical one-line
`compose_gears_probe_command_result_v1` containing the primary artifact SHA after each successful command; capture
that line directly in `commands.jsonl`. Do **not** pass shell command substitution such as
`$(sha256sum roster.json)` or `$(sha256sum probe_manifest.json)` directly into the corresponding consumer; that
would merely authenticate a possibly modified candidate against itself.

Any hash mismatch, dirty tree, missing image digest, unbounded cost, evidence path on ephemeral-only storage, or
unavailable reader-spy attestation is a **STOP**, not a warning.

## 4. Execution phases

### Phase 0 — preflight only

- Render CLI help from the committed maintained probe CLI; commands in the evidence log must come from that help,
  not from this document or memory.
- Run source/manifest/hash validation and metadata-only role resolution.
- Emit the exact row rosters and a zero-overlap proof without reading expression.
- Verify the planned sizes satisfy `N_target ≥ |M|` and record the exact ordered roster SHA for each candidate.
- Pass the activation-pinned GO resource manifest plus its external SHA and the manifested sibling
  `gene2go_all.pkl` plus its SHA to `build-roster`. A derived node artifact whose source claim or complete key
  roster differs is a STOP; never substitute `essential_all_data_pert_genes.pkl` for this input.
- Require the receipt-last completion marker, record its externally anchored SHA, and use only that pin for
  `prepare-input`; a roster/report without its receipt is an incomplete failed attempt.
- Verify the receipt's generator source-closure, `uv.lock`, the separate GEARS environment lock, and generator
  runtime fingerprint; record both lock SHA-256 values and the lock-matched installed-package-roster SHA rather
  than assuming local and pod numerical environments are identical.

### Phase A — registration then scale/behavior characterization

- After `prepare-input` and `verify-input`, run maintained `build-probe-a-registration` exactly once against the
  canonical prepared manifest and committed owner policy. Capture its emitted SHA outside the evidence tree and
  verify it before fitting or prediction. A missing pin or any mismatch is a STOP; the observed report is never
  allowed to define its scale, representation, negative policy, or tolerance.
- Invoke the maintained `probe-a` command with the canonical registration path,
  `--probe-a-registration-sha256`, and the approved full `--git-commit`. The runner validates all three before
  loading the prepared input or fitting GEARS, and binds the registration/input-scale identities into both
  checkpoints and the raw producer envelope.
- Dump and hash the pinned GEARS source surfaces used by preprocessing, target construction, and prediction.
- Use a tiny synthetic or explicitly non-sealed fit-role artifact to measure P1–P4.
- Fit the same deterministic tiny input twice; require checkpoint and output equality under the registered
  determinism policy, or record a reproducibility failure. Archive both real checkpoint files under
  `checkpoints/`; a checkpoint digest written only inside JSON is not evidence.
- Compare public `predict` with the candidate per-control reconstruction on identical inputs. Record negative
  predictions, control-count sensitivity, output scale, and inference-equivalence error without choosing a bridge
  after seeing downstream scientific outcomes. Freeze one ordered roster of at least 400 unique control-row
  identities. Every count uses the exact prefix of that roster and retains every direct per-control prediction.
  The pinned public GEARS helper does **not** consume that prefix once each: it constructs 300 graphs by drawing
  indices with replacement from the supplied control pool (`np.random.randint(0, len(ctrl_adata), 300)`). The
  maintained direct path must therefore bypass that random-sampling dataset helper and invoke its exposed
  single-cell graph constructor once for every exact prepared row, in order. The verifier still reconstructs the
  preregistered first-`min(n,300)` candidate from those direct rows; disagreement with the public resampled mean is
  a real Probe-A failure and must not be hidden by replaying or post-selecting the public random indices.

Probe A's preregistered numerical-bridge candidate is specifically the public-vs-first-300 aggregation
equivalence check; the source-level replacement sampling above makes failure possible and does not authorize a
post-measurement policy change. It does not
run a sealed response projection and must not be described as such. The adapter arithmetic
(`hvg_subset_center_pca_no_renormalization`, including finite signed inputs) is separately covered by local
known-answer tests; scientific usefulness still requires the post-PASS amendment and later sealed evaluation.

Probe A must emit a mechanical PASS/FAIL against a preregistered tolerance. A failed bridge routes to the named
raw comparator; it does not trigger a post-hoc alternate transform.

The owner policy is outcome-independent and repository-frozen. The registration adds only run identity and the
prepared response scale; it has exactly this semantic shape:

```text
schema = compose_gears_probe_a_registration_v2
protocol = COMPOSE-K562-v1
git_commit = <approved full Git SHA>
owner_policy_sha256 = SHA-256(configs/compose_gears_probe_a_owner_policy_v1.json bytes)
input_scale = {normalization_target, transform=full_library_normalize_log1p_then_roster_subset}
determinism = {max_abs_error_tolerance=0}
control_count = {counts=[1,8,300,301,400], first_300_max_abs_error_tolerance=1e-5}
output_bridge = {
  representation=log_normalized_pseudobulk,
  transform=hvg_subset_center_pca_no_renormalization,
  negative_output_policy=preserve_finite_signed_model_output,
  max_abs_error_tolerance=1e-5
}
self_checksum = SHA-256(canonical JSON of every preceding field)
```

`normalization_target` is not a hand-entered constant and is not the fixture value `10000`; the builder copies
the actual prepared manifest's response-projection `median_library`. The canonical file-byte SHA is separately
anchored before the fit. Changing any value requires a new clean commit/policy or prepared-input identity and is
forbidden after any Probe-A measurement is observed; recomputing `self_checksum` does not make a post-hoc change
preregistered.

### Phase B — exact-roster resource benchmark

- Consume the already validated non-sealed `U_full` fit-role and frozen response artifacts.
- For each owner-approved candidate `R_gears` (initially the exact-size 2k-ish and 5k-ish artifacts), verify every
  lineage digest and mandatory gene before model construction.
- Run graph preparation and two preregistered epoch counts with identical seed/config, fresh output directories,
  no checkpoint reuse, and the maintained probe runner. Do not mutate worker module constants in place;
  pass measurement epoch count through the dedicated probe-only API.
- Record graph-build time, each epoch time, peak/trace host RSS, peak/trace GPU memory/utilization, CPU load,
  checkpoint bytes/SHA, processed roster SHA, and extrapolation assumptions. Preserve raw samples, not only
  summaries.
- Run each candidate twice. Report variability and refuse extrapolation when timing is non-monotone or noisy
  beyond the preregistered tolerance.

### Phase C — collection and independent verification

- Stop all background samplers in a trap and record their exit status.
- Derive `probe_a.json` only through maintained `build-probe-a-report`; append that command record to
  `commands.jsonl`, and require its primary SHA to equal the final report bytes.
- Run maintained `build-evidence-manifest` last to hash every pre-admission output, raw log, command transcript,
  and environment record. Do not append its result line to the already closed `commands.jsonl`; externally pin
  the emitted manifest SHA instead.
- Copy evidence back to the MacBook before terminating the pod; verify local bytes against the pod manifest.
- Re-run the offline verifier locally. A verified gate failure is a successful **negative-result finalization**:
  it writes a `failed` `verify.json`, writes no admission, and stops Probe B. Only verifier PASS may create an
  admission or promote the candidate.
- Shut down the pod and revoke the temporary SSH key after local verification.

## 5. Durable evidence contract

The rerun creates a new timestamped directory; it never modifies the quarantined 2026-07-11 archive. Required
contents:

```text
manifest.json                 canonical schema, self-checksum, complete file roster + SHA-256
commands.jsonl                argv/cwd/env allowlist/start/end/exit code per command
runtime.json                  pod/GPU/driver/CUDA/CPU/RAM/image/package/lock identities
inputs.json                   source/GO/pair/alias/fit-role/response/roster identities
probe_input_manifest.json     canonical prepared-input manifest consumed by Probe A
probe_input.h5ad              exact prepared, non-sealed H5AD consumed by both fresh fits
roster_receipts/              receipt-last generation records and their externally anchored SHA-256 values
role_attestation.json         metadata-derived roles, counts, zero overlap, reader-spy proof
probe_a_registration.json     owner-frozen decisions/tolerances + external pre-run SHA-256 pin
probe_a_source.txt            combined pinned GEARS source closure named by the report digest
checkpoints/                  exactly two fresh Probe-A trained-model checkpoint files
probe_a.json                  P1-P4 measurements + mechanically derived pass/failed status + raw references
probe_a_admission.json        PASS-only promotion object; MUST be absent for a negative result
logs/                         stdout/stderr and raw CPU/GPU/RSS samples for every run
verify.json                   write-once local verifier receipt + verifier-code-closure SHA-256
```

Every JSON uses canonical serialization and schema versioning. `manifest.json` uses
`compose_gears_probe_a_evidence_manifest_v7`; every file entry has exactly `{role,path,sha256,bytes}`. It assigns
exactly one role each to `commands`, `runtime`, `inputs`, `role_attestation`, `probe_a_registration`,
`probe_a_report`, `probe_a_source`, `probe_input_manifest`, and `probe_input_h5ad`, at least one each to
`roster_receipt`, `raw_sample`, and `log`, and exactly the two raw-referenced files under the
`probe_a_checkpoint` role.
**Probe B is not a Probe-A manifest role or admission prerequisite.** It receives a separate timestamped archive
and verifier only after the timing runner and raw/statistical contract are reviewed. The declared paths must
equal the recursively enumerated regular-file inventory. Only
`manifest.json` itself and the post-manifest outputs `probe_a_admission.json`/`verify.json` are excluded from that
comparison. Symlinks, missing/extra files, duplicate paths, unknown roles, absolute source paths presented as
identities, non-finite measurements, mismatched rosters, unbound overrides, and evidence produced from a
different commit or runtime are rejected.

The report uses `compose_gears_probe_a_report_v8` and carries `registration_sha256`. Its `status` is mechanically
`pass` iff determinism, control-count, and output-bridge gates all pass; otherwise it is `failed`. A failed gate is
a valid scientific result only after every identity, raw-array, checkpoint, row/role, leakage, finite-value, and
manifest invariant still validates. Integrity/protocol violations remain verifier errors, not negative results.
Its runtime, inputs, source, registration, report-byte, and complete raw-sample path/SHA identities must match the
corresponding manifest roles exactly; neither subset-only nor superset-only raw-sample rosters are accepted.

The prepared manifest/H5AD use `compose_gears_probe_input_manifest_v3` and
`compose_gears_probe_input_v3`. The stored matrix is canonical CSR little-endian float32 before H5AD publication,
matching the worker's numerical boundary; its logical digest is independently recomputed after reopening. Both
artifacts record the exact positive finite `normalization_target`, matrix storage contract, selected source-row
roster digest, preparation-lock SHA, GEARS-lock SHA, and an exact role contract containing the control token,
single-gene roster, calibration-pair roster, and sealed-pair roster. Pair tokens are reconstructed from the
registered pairs rather than parsed by splitting gene IDs on `_`. The offline verifier requires all identities to
agree with the receipt, raw producer, runtime, and owner-frozen registration.

Probe A has exactly one canonical `compose_gears_probe_a_raw_measurements_v6` artifact emitted write-once by the
maintained `probe-a` execution command. That command accepts no arbitrary measurement JSON: it verifies and
directly consumes the archived `probe_input_manifest.json`/`probe_input.h5ad`, invokes the maintained pinned GEARS
worker for two fresh fits, durably writes each checkpoint, and observes the fitted model before publishing raw
measurements. The artifact contains a producer envelope binding the pinned backend/version, driver and worker
source hashes, prepared-input/row/control/roster identities, canonical non-sealed query, seed, and measurement run;
the owner-frozen registration SHA and the exact normalization target/input-scale identity;
canonical logical-CSR identities for `input_before`/`input_after` (shape, nonzero count, a storage-independent
little-endian float64 logical digest of the already float32-bounded values, without densifying the 70,987 × roster
input); the committed GEARS-lock and installed-package-roster digests; two indexed run predictions with checkpoint byte/format and
input/query/seed/worker bindings; one frozen ordered control-row roster; each count's exact prefix and per-control
predictions for `[1,8,300,301,400]`; the corresponding public predictions; the public output-scale prediction; and
the preregistered bridge prediction. The command's primary-file SHA must equal this raw artifact's manifest SHA.
The offline validator independently hashes the actual checkpoint bytes, validates the load-free PyTorch ZIP
envelope and all member CRCs, scans pickle opcodes without executing/deserializing them to require the registered
model/backend/input/query/worker/fit identities, requires the exact two-file manifest roster, reopens the manifested
H5AD and recomputes its row/control identities, role assignment, sealed-pair overlap, reader-spy row roster, and
matrix digest, verifies both committed dependency-lock hashes and the maintained source hashes, and recomputes
input/prediction digests, exact input equality, two-run maximum absolute error, every
public-vs-first-`min(n,300)` reconstruction error, the 300-vs-301/400 first-batch error, output
minimum/median/maximum, negative
fraction, near-integer fraction (distance to the nearest integer `<= 1e-6`), and bridge maximum absolute error.
A self-reported aggregate or verdict cannot substitute for these raw arrays.

The offline verifier requires `--expected-verifier-code-sha256` and compares that independently reviewed pre-run
pin with its actual source closure **before evidence validation**. It always emits one canonical, write-once
`verify.json` receipt. On PASS only, it then emits `probe_a_admission.json` **last**. On a measured gate failure it
returns `NEGATIVE_RESULT`, leaves admission absent, and the receipt is the terminal artifact. A pre-existing
receipt or admission is a failed attempt; neither file may be overwritten or reused. The verifier hashes its
actual source closure (entrypoint plus the shared producer and consumer validators), not a caller-supplied label.
A passing `verify.json` uses `compose_gears_probe_a_verification_v1` with exactly
`{schema, protocol, status, git_commit, registration_sha256, report_sha256,
evidence_manifest_sha256, verifier_code_sha256, output_bridge, self_checksum}`.

A negative `verify.json` uses `compose_gears_probe_a_negative_verification_v1` and adds exactly
`gate_verdicts={determinism,control_count,output_bridge}`. Its status is `failed`, at least one gate must be `fail`,
all three verdicts and the complete bridge object must equal the hash-bound report, and its report, manifest,
registration, Git, and verifier-closure pins follow the same validation rules as PASS. This receipt is durable
negative evidence but is intentionally incompatible with the approximation-bias admission consumer.

Only after the externally pinned registration, every raw Probe-A artifact, the complete evidence manifest, and
the receipt verify may the verifier publish `compose_gears_probe_a_admission_v3` with exactly
`{schema, protocol, status, git_commit, registration_sha256, evidence_manifest_sha256, verification_sha256,
output_bridge, self_checksum}`;
`output_bridge` has exactly `{representation, verdict, tolerance, max_abs_error}`. Promotion requires
`status=pass`, `protocol=COMPOSE-K562-v1`, the approved Git commit, the externally frozen registration SHA,
`representation=log_normalized_pseudobulk`, `verdict=pass`, finite non-negative error/tolerance,
`max_abs_error ≤ tolerance`, and a canonical checksum over every field except `self_checksum`. A raw
`probe_a.json`, command-result line, or bare `{status: pass}` is not admission evidence.
The receipt and admission must agree byte-for-byte on the bridge object and on every shared identity. The
admission's `verification_sha256` must equal the exact receipt-byte SHA. The approximation-bias command receives
the immutable registration and receipt bytes plus both independently anchored pins as
`--probe-a-registration`, `--probe-a-registration-sha256`, `--probe-a-verification`, and
`--probe-a-verification-sha256`; it must not derive either expected value from the evidence it is validating.
A self-consistent admission/registration/receipt rewrite is not authenticated unless its external pins also
match.

Decision-bearing manifest roles are content-validated, not merely inventoried. `commands.jsonl` contains at
least one successful invocation of each maintained CLI subcommand that actually exists:
`{build-roster, prepare-input, verify-input, build-probe-a-registration, probe-a,
build-probe-a-report}`. Prep labels may repeat for multiple candidate rosters;
`build-probe-a-registration` occurs exactly once after prepared-input verification, binds the owner-policy and
prepared-manifest pins, and its primary SHA equals the manifested registration SHA; `probe-a` occurs exactly once
and its primary SHA is the manifested raw artifact SHA;
`build-probe-a-report` occurs exactly once, its arguments bind the raw sample, registration, approved commit and
canonical report path, and its primary SHA is the manifested report SHA;
unknown or fictional subcommands are rejected. Records carry secret-free environment allowlists, UTC intervals,
primary-file SHA values, and one runtime fingerprint.
`runtime.json`, `inputs.json`, and `role_attestation.json` use respectively
`compose_gears_probe_runtime_v2`, `compose_gears_probe_inputs_v3`, and
`compose_gears_probe_role_attestation_v2`; they bind the approved commit, separate preparation/GEARS dependency
locks, the complete installed-package-roster digest, runtime/input
identities, exact fit-role counts, the prepared-manifest/H5AD/row/control-roster SHA identities, zero sealed
overlap/read counts, and a passing reader-spy attestation. Every
`compose_gears_roster_receipt_v2` binds its exact roster and both dependency-lock lineages. Any placeholder JSON
that merely occupies a manifest role is rejected. Until the separate Probe-B runner/archive spec defines raw epoch samples,
the exact CV estimator, extrapolation formula, and cross-roster monotonicity rule, **no Probe-B JSON is
decision-grade and no Probe-B PASS schema is recognized by this verifier**.

## 6. Decision and stop rules

- **Representation:** Option 1 is eligible only if all preregistered scale assumptions and inference-equivalence
  tolerance pass. Otherwise retain the named raw-pseudobulk comparator and its approximation-bias limitation.
- **Roster size:** choose only among exact, digest-bound candidate rosters whose repeated measured runtime and
  memory fit the owner's budget with declared safety margin. Predictive performance never selects `N_target`.
- **Immediate STOP:** any sealed row read/materialization, `ComposeOutcomeStore` construction, dirty/mismatched
  identity, attempted download, failed determinism/equivalence gate, OOM, truncated log, missing raw sample,
  unexpected file, or cost-limit breach.
- A measured gate failure stops all further fitting/probing but does **not** skip evidence closure: finish the
  canonical failed report, manifest, local verification receipt, and archive copy. It never authorizes Probe B.
- A STOP or negative result is preserved as evidence. It is never silently rerun with changed parameters.

## 7. Promotion boundary

Successful probes only make the representation and resource-size decisions eligible for owner freeze. They do
not complete GU/adapter implementation, finalize `configs/compose_k562_v1_phase2.yaml`, regenerate activation
evidence, satisfy scientific PREPARE, or authorize the sealed run. Those remain separate gates in
`../COMPOSE-SEAL-READINESS.md`.
