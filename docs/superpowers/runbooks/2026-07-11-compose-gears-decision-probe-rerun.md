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

- [ ] Revised `specs/2026-07-11-compose-gene-universe-design.md` receives independent review PASS tied to an
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
- [ ] Before Probe B, extend the same maintained CLI with the reviewed GEARS timing subcommand and complete raw
  command/resource sampling. Do not copy the archived timing harness.
- [ ] After Probe A, define and review the scientific output bridge/negative-value policy. This is an activation
  gate, not a prerequisite for running Probe A itself.

Probe A may run after the first four completed implementation gates, exact-SHA review, and §3 identity checks.
Probe B additionally requires the timing subcommand. No scientific GEARS prediction may be activated until the
last output-bridge gate passes.

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

Record the final test counts and exact Git SHA in the pod evidence manifest.

## 3. Pod admission and identity capture

The owner supplies a temporary SSH key through a local file/agent, host, port, username, pod lifetime, and maximum
GPU-hours/cost. Never place credentials in the repository or transcript artifacts. On connection:

1. create a fresh work root on durable storage; abort if only ephemeral storage is available for evidence;
2. capture provider/pod ID, GPU model/UUID, driver/CUDA, CPU/RAM, filesystem capacity, UTC timestamps, and cost
   rate/limit;
3. transfer a Git bundle or archive from the exact reviewed clean commit; do not develop directly on the pod;
4. verify bundle commit, clean tree, `uv.lock`, GEARS era lock, container/image digest, Python/package roster, GO
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
- Require the receipt-last completion marker, record its externally anchored SHA, and use only that pin for
  `prepare-input`; a roster/report without its receipt is an incomplete failed attempt.
- Verify the receipt's generator source-closure, `uv.lock`, and generator runtime fingerprint; record the separate
  preparation/runtime fingerprint rather than assuming local and pod numerical environments are identical.

### Phase A — scale/behavior characterization

- Dump and hash the pinned GEARS source surfaces used by preprocessing, target construction, and prediction.
- Use a tiny synthetic or explicitly non-sealed fit-role artifact to measure P1–P4.
- Fit the same deterministic tiny input twice; require checkpoint and output equality under the registered
  determinism policy, or record a reproducibility failure.
- Compare public `predict` with the candidate per-control reconstruction on identical inputs. Record negative
  predictions, control-count sensitivity, output scale, and inference-equivalence error without choosing a bridge
  after seeing downstream scientific outcomes.

Probe A must emit a mechanical PASS/FAIL against a preregistered tolerance. A failed bridge routes to the named
raw comparator; it does not trigger a post-hoc alternate transform.

### Phase B — exact-roster resource benchmark

- Consume the already validated non-sealed `U_full` fit-role and frozen response artifacts.
- For each owner-approved candidate `R_gears` (initially the exact-size 2k-ish and 5k-ish artifacts), verify every
  lineage digest and mandatory gene before model construction.
- Run graph preparation and two preregistered epoch counts with identical seed/config, fresh output directories,
  no checkpoint reuse, and the maintained measurement hook. Do not mutate worker module constants in place;
  pass measurement epoch count through the dedicated probe-only API.
- Record graph-build time, each epoch time, peak/trace host RSS, peak/trace GPU memory/utilization, CPU load,
  checkpoint bytes/SHA, processed roster SHA, and extrapolation assumptions. Preserve raw samples, not only
  summaries.
- Run each candidate twice. Report variability and refuse extrapolation when timing is non-monotone or noisy
  beyond the preregistered tolerance.

### Phase C — collection and independent verification

- Stop all background samplers in a trap and record their exit status.
- Hash every output, raw log, command transcript, and environment record into a canonical evidence manifest.
- Copy evidence back to the MacBook before terminating the pod; verify local bytes against the pod manifest.
- Re-run the offline verifier locally. Only its PASS output may promote the archive to decision-grade evidence.
- Shut down the pod and revoke the temporary SSH key after local verification.

## 5. Durable evidence contract

The rerun creates a new timestamped directory; it never modifies the quarantined 2026-07-11 archive. Required
contents:

```text
manifest.json                 canonical schema, self-checksum, complete file roster + SHA-256
commands.jsonl                argv/cwd/env allowlist/start/end/exit code per command
runtime.json                  pod/GPU/driver/CUDA/CPU/RAM/image/package/lock identities
inputs.json                   source/GO/pair/alias/fit-role/response/roster identities
roster_receipts/              receipt-last generation records and their externally anchored SHA-256 values
role_attestation.json         metadata-derived roles, counts, zero overlap, reader-spy proof
probe_a.json                  P1-P4 measurements + equivalence verdict + raw-sample references
probe_a_admission.json        exact promotion object consumed by the bias-metric admission gate
probe_b_<roster>.json         B1-B4 measurements, repeats, extrapolation status
logs/                         stdout/stderr and raw CPU/GPU/RSS samples for every run
verify.json                   local offline verifier result and verifier code SHA-256
```

Every JSON uses canonical serialization and schema versioning. The manifest must reject missing/extra files,
duplicate logical run keys, absolute source paths presented as identities, non-finite measurements, mismatched
rosters, unbound overrides, and evidence produced from a different commit or runtime.

The offline verifier emits `probe_a_admission.json` only after every raw Probe-A artifact and the complete
evidence manifest verify. Its exact schema is `compose_gears_probe_a_admission_v1` with exactly
`{schema, protocol, status, git_commit, evidence_manifest_sha256, output_bridge, self_checksum}`;
`output_bridge` has exactly `{representation, verdict, tolerance, max_abs_error}`. Promotion requires
`status=pass`, `protocol=COMPOSE-K562-v1`, the approved Git commit,
`representation=raw_pseudobulk_approximation`, `verdict=pass`, finite non-negative error/tolerance,
`max_abs_error ≤ tolerance`, and a canonical checksum over every field except `self_checksum`. A raw
`probe_a.json`, command-result line, or bare `{status: pass}` is not admission evidence.

## 6. Decision and stop rules

- **Representation:** Option 1 is eligible only if all preregistered scale assumptions and inference-equivalence
  tolerance pass. Otherwise retain the named raw-pseudobulk comparator and its approximation-bias limitation.
- **Roster size:** choose only among exact, digest-bound candidate rosters whose repeated measured runtime and
  memory fit the owner's budget with declared safety margin. Predictive performance never selects `N_target`.
- **Immediate STOP:** any sealed row read/materialization, `ComposeOutcomeStore` construction, dirty/mismatched
  identity, attempted download, failed determinism/equivalence gate, OOM, truncated log, missing raw sample,
  unexpected file, or cost-limit breach.
- A STOP or negative result is preserved as evidence. It is never silently rerun with changed parameters.

## 7. Promotion boundary

Successful probes only make the representation and resource-size decisions eligible for owner freeze. They do
not complete GU/adapter implementation, finalize `configs/compose_k562_v1_phase2.yaml`, regenerate activation
evidence, satisfy scientific PREPARE, or authorize the sealed run. Those remain separate gates in
`../COMPOSE-SEAL-READINESS.md`.
