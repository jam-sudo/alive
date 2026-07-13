# COMPOSE dev-pod — Phase-1-entry gate-decision record (B-spec §7 #1–#5)

> **STATUS: PROPOSED — pending owner sign-off (§6).** This record settles the dev-pod plan's
> "Open decisions to settle BEFORE Phase 1 (owner + pod)" gate — the B-spec §7 decisions —
> citing only evidence already committed on this branch, with exact revision strings verified
> byte-for-byte against the committed locks (§7, this document's own reference-integrity check).
> Each decision is `PROPOSED` until the owner flips it to `CONFIRMED` in §6. **This record makes
> NO config edit.** `configs/compose_k562_v1_phase2.yaml` keeps every null/unestablished
> activation-blocker field untouched (`regimes.power_status`,
> `baselines.{gears,cpa}.{revision,environment_status}`,
> `baselines.gears.approximation_bias_report_sha256`). Those encodings land later — per the
> dev-pod plan's ⚑ "config finalization precedes evidence regeneration" ordering — in Phase-0
> Task 0.1 (reproducibility/artifact-hash evidence) and Phase-2 Tasks 2.1/2.2 (writing the config
> fields and minting the FINAL `config_sha256` / run identity). Writing the *decision* here, and
> the *config encoding* later, is intentional: it keeps the gate settlement auditable
> independent of, and strictly before, the commit that mints the final run identity.

## 0. Scope and cross-links

- **Settles:** dev-pod plan §"Open decisions to settle BEFORE Phase 1 (owner + pod)"
  (`docs/superpowers/plans/2026-07-09-compose-dev-pod-real-workers.md:31-45`), which the plan
  itself frames as "the B spec §7 decisions" and as a **Hard Phase-0 entry gate**: *"Phase 1 MUST
  NOT begin until every unresolved decision and every Task-0 acceptance condition is recorded."*
- **Feeds:** the sealed-run runbook release gate
  `docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md` §2.5 ("Release gate" —
  full-suite + worker-integration green, complete evidence manifest, documented
  `power_status`/`revision`/`environment_status` relationship to the activation overlay,
  independent review, and an owner-approved exact Git SHA before the runbook may flip to READY).
  This record is upstream of §2.5, not a substitute for it.
- **Background (not itself cited as evidence):**
  `docs/superpowers/2026-07-09-compose-dev-pod-decision-proposals.md` carries the external
  research and full reasoning behind #1/#3/#4 (GEARS hyperparameter provenance, the CPA
  0.7.2→0.8.5 fix timeline, the pseudobulk-bias derivation) and is worth reading for *why*; this
  record is the citable settlement, restricted to committed, hash-verified evidence.
- **Governance:** this document opens no seal, reads no sealed outcome, and constructs no
  `ComposeOutcomeStore`. It is prose only — no code, no test surface.

---

## 1. Decision #1 — GEARS published config + revision

**Decision.** Train GEARS on its published/default configuration for K562 Perturb-seq (dev-pod
plan Global Constraint: *"No published-baseline weakening… GEARS/CPA run their published/default
config… no knob is chosen from any outcome"*). Pin the environment to `cell-gears==0.1.2` plus the
era-consistent stack recorded in the committed lock.

**Cited evidence** — `docs/activation-evidence/compose/requirements.gears_env.lock`
(SHA-256 `2d55a062cd8de0ac9b13299049848836e0917c7ef2027f9daa2554d88b53b8bf`, verified in §7).
Exact pins (verbatim lines from the committed file):

```
cell-gears==0.1.2
numpy==1.26.4
pandas==2.2.3
scipy==1.11.4
scanpy==1.11.5
anndata==0.10.9
torch==2.6.0+cu124
torch-geometric==2.8.0
```

(76 lines total pin every transitive dependency; the excerpt above is the subset named in the
task brief.)

**Durable-revision note.** `cell-gears` has no runtime `__version__` attribute, and the dev-pod
plan's Global Constraint is explicit that "*Worker-reported digests must equal the committed lock
values, not runtime `__version__`*." The durable pin is therefore not a package attribute but
either (a) the upstream repo commit/tag corresponding to `cell-gears==0.1.2`, or (b) the
Task-0.1 wheel/sdist artifact SHA-256 recorded in
`docs/activation-evidence/compose/python_artifact_manifest.json` (schema
`compose_python_artifact_manifest_v1`, per the dev-pod plan's File Structure list). That
manifest has not yet been produced on this branch — Task 0.1 remains a **separate, still-open
acceptance condition**; this record settles the *choice* of revision, not the wheel-hash
reproducibility evidence for it.

**Training config.** Source: GEARS paper/repo default for K562 Perturb-seq (no K562-specific
override chosen; no outcome-based knob selection — per plan decision #1 and the Global
"no published-baseline weakening" constraint). The exact `epoch/batch/optimizer/early-stop/seed`
values must be read from the **installed 0.1.2 wheel** (not a later repo `master`, which may have
drifted) — this pod-side verification is Phase-1 worker-authoring work
(`docs/superpowers/plans/2026-07-09-compose-dev-pod-real-workers.md` Task "real GEARS/CPA workers"),
not settled by this record.

**Status:** `PROPOSED`.

---

## 2. Decision #2 — GEARS GO-graph / gene2go source — **RESOLVED**

**Decision.** The GEARS GO-graph/gene2go resources are bound to the Harvard Dataverse **PertNet**
dataset, persistent ID `doi:10.7910/DVN/Q2ZV3E`, license CC0-1.0.

**Cited evidence** — `docs/activation-evidence/compose/go_resource_manifest.json`
(schema `compose_go_resource_manifest_v2`; `manifest_checksum`
`fcd48bac0d9722a6446fc5534df0a29bd4a98979cca40f8b518bbe58bb9bbd1b`; the file's own SHA-256,
independently recomputed in §7, is `e9e724ebe77d55dc4c8bc9f18a832b8bcebdddc59af554c4af45ff3c2b6896cc`,
matching the value the dependency lock cites for it — see §7). Exact roster (verbatim from the
manifest):

| resource | Dataverse datafile ID | dataset version | bytes | upstream MD5 | SHA-256 |
|---|---|---|---|---|---|
| `gene2go_all.pkl` | 6153417 | 3.0 | 9,462,558 | `77c9af0c61c30ea4d7a85680f4d122dc` | `f145c5e84a53048d87942a417d870a4f2d8db50200b96e492b358c13aba8c771` |
| `essential_all_data_pert_genes.pkl` | 6934320 | 7.0 | 558,811 | `b7bc2a91ca513b86f27f090d963711a6` | `46c3dfe354d8ad5c0da22c69f3d0ca451987b1a61ed9d984279b22b9565ff8d7` |
| `go_essential_all.tar.gz` (extracted → `go_essential_all.csv`) | 6934319 | 7.0 | 60,654,049 (archive) / 354,733,543 (extracted CSV) | `b8bff0d53407f26648330d264df7fe16` | `98a14a60e8b76f76fd172570d023a6036775f151604ec01340b3fec7d36693da` (archive) / `99622d9215462e7bbea99a5f6c0b1e86febfef9f57226269418053484fcb3f9f` (extracted) |

Acquisition method: `cell-gears==0.1.2` built-in Dataverse loaders; `retrieved_git_sha`
`a89f89e9a0252d86393464a6b61bd806eae714e1`; pod `"RunPod A100 80GB PCIe; NVIDIA driver
550.127.05; gears_env_era"`; `opened_seal: false`.

**#2 RESOLVED.** Per the dev-pod plan: *"Decision #2 is now resolved by the committed v2
manifest… The committed v2 manifest binds Harvard Dataverse `doi:10.7910/DVN/Q2ZV3E`, CC0-1.0,
exact datafile/dataset/file versions, sizes, upstream MD5s, acquired SHA-256s, and extracted-CSV
SHA-256. Phase 0 must only reproduce and verify those bytes; it may not silently select another
resource."* Task 0.2 (pod) still has to reproduce these exact bytes into pod object storage and
recheck size + MD5 + SHA-256 — that is bytes-reproduction, not an open *decision*.

**Status:** RESOLVED (no owner sign-off needed to confirm the *choice*; §6 records the sign-off
line anyway for completeness/audit).

---

## 3. Decision #3 — CPA (`cpa-tools`) setup + revision

**Decision.** Pin `cpa-tools==0.8.5` for the combo-prediction baseline — **not** `0.7.2` (crashes
on the Norman setup) and **not** `0.8.8` (untagged, larger dependency drift from the
paper-contemporaneous stack). Run CPA's published/default configuration for combo prediction.

**Cited evidence** — `docs/activation-evidence/compose/requirements.cpa_env.lock`
(SHA-256 `7d4d034bd91e276c737b51415c4443954fc6439f31068725b6a80115deebe29c`, verified in §7).
Exact pins (verbatim lines from the committed file):

```
cpa-tools==0.8.5
numpy==1.26.4
anndata==0.10.9
scvi-tools==0.20.3
jax==0.4.38
jaxlib==0.4.38
scanpy==1.11.5
torch==2.6.0+cu124
```

**Why not 0.7.2 / not 0.8.8** — `docs/activation-evidence/compose/gears_cpa_dependency_lock.json`
`run_gate.observations.cpa` (verbatim): *"cpa-tools 0.7.2 crashed in setup_anndata's deg_uns_key
branch because it used np.int with numpy 1.26.4. cpa-tools 0.8.5 completed setup_anndata plus a
1-epoch GPU smoke on a Norman combo slice."* 0.8.5 is the earliest tagged release carrying both
the `np.int`→`int` fix and the no-SMILES (gene-perturbation) guard, and is the minimal-delta env
change from the paper-era stack (full reasoning:
`docs/superpowers/2026-07-09-compose-dev-pod-decision-proposals.md` §3). This lock's
`environment_reproducibility.status` is currently *"INCOMPLETE — exact versions are pinned, but
wheel/sdist hashes and the pod image digest were not captured"* — Task 0.1 (pod) still owes that
reproducibility evidence; it does not reopen the version *choice*.

**Combo config.** Published/default `cpa-tools==0.8.5` configuration for combo prediction, read
from the installed 0.8.5 wheel and its contemporaneous tutorial (not transplanted from the 0.8.8
tutorial, which uses different defaults) — pod-side worker-authoring verification, not settled by
this record.

**Status:** `PROPOSED`.

---

## 4. Decision #4 — `approximation_bias` measurement for GEARS

**Decision.** The *method* by which GEARS's `raw_pseudobulk_approximation` representation's bias
is quantified is settled by this session's design spec:
`docs/superpowers/specs/2026-07-13-compose-approximation-bias-metric-design.md` — a model-free,
representation-floor measurement over non-sealed roles only (`control`, `singles`,
`combo_calibration`), with a pre-registered fairness rule (§5 of that spec): `R_star = 0.5`;
`fairness_flag = "representation_confounded"` if the bias-to-signal ratio `R ≥ R_star`, else
`"clear"`. (Verbatim from the spec: *"`R_star`: `0.5` (the pre-registered threshold, embedded for
auditability)."* and *"`fairness_flag`: `"representation_confounded"` if
`bias_to_signal_ratio_R ≥ R_star`, else `"clear"`."*)

**Implementation status (this branch).** The metric's point-estimate core, bootstrap, seal-safety
guards, report assembly/provenance, Probe-A admission gate, one-way config-finalization tool, and
durable fairness-flag carry are already built and committed (`f06f387`, `874fd51`, `e162b22`,
`7a43959`, `f34583d`, `6303a4f`, `db6792e`, `cc48ed5`, `f7de7f8` on this branch) — the **method is
implemented**, matching the plan's Task 1–7 scope. What remains pod-only:

- The report is **pod-generated**: it needs real Norman per-cell counts and is not produced by
  this record or by any local task.
- It is **Probe-A-gated**: `docs/superpowers/runbooks/2026-07-11-compose-gears-decision-probe-rerun.md`
  must first establish GEARS's native output scale, negative-output policy, and bridge
  equivalence within a pre-registered tolerance (spec §0: *"Conforming Probe A… must first
  establish the native scale, negative-output policy, and bridge equivalence within its
  preregistered tolerance."*). The prior probe session
  (`docs/superpowers/2026-07-11-compose-gears-decision-probe-results.md`) records its own
  top-level status as *"QUARANTINED PARTIAL OBSERVATIONS — Probe B NONCONFORMING; scientific
  decisions remain PROVISIONAL"*, and its Probe-A section heading itself reads *"owner preference
  Option 1, NOT YET LOCKED."* Its compliance-finding section further shows the shared prep
  pipeline feeding both probes materialized all source expression before any dev
  sealed/calibration split existed — a violation that predates the Probe A/B split, so Probe A's
  own observations were produced under that same non-conforming prep. A conforming rerun
  (`docs/superpowers/runbooks/2026-07-11-compose-gears-decision-probe-rerun.md`) is still
  outstanding.
- Until the report exists, `configs/compose_k562_v1_phase2.yaml::baselines.gears.approximation_bias_report_sha256`
  stays `null`, and the durable carry built in Task 7 honestly records
  `fairness_flag = "unavailable"` for a null config field (implementation plan
  `docs/superpowers/plans/2026-07-13-compose-approximation-bias-implementation.md:249`: *"When
  the config field is null (not yet finalized), the block records
  `{report_sha256: null, fairness_flag: "unavailable", ...}` — the CARRY exists but is honestly
  empty."*). CPA's exact `cell_raw_counts` representation keeps its
  `approximation_bias_report_sha256` null **by design** (not an open item).

**This record settles the DEFINITION only** (what is measured, on which roles, how it aggregates,
the pre-registered `R_star` fairness rule) — not the pod execution, not the report SHA, and not
the config write.

**Status:** `PROPOSED` (definition); execution remains pod/Probe-A-gated and out of scope here.

---

## 5. Decision #5 — Dev-pod provider/instance

**Decision.** RunPod, A100 80GB (PCIe), torch `2.6.0+cu124`, matching the prior A100 pattern (see
`[[cartographer-mvp-built-merged]]`).

**Cited evidence** — `docs/activation-evidence/compose/go_resource_manifest.json`
`acquisition.pod` (verbatim): `"RunPod A100 80GB PCIe; NVIDIA driver 550.127.05; gears_env_era"`.
Corroborated by `docs/activation-evidence/compose/gears_cpa_dependency_lock.json` `host` block
(verbatim): `"gpu": "NVIDIA A100 80GB PCIe"`, `"nvidia_driver": "550.127.05"`,
`"uv_version": "uv 0.9.0"`; and `indexes` block: `"torch_index_url":
"https://download.pytorch.org/whl/cu124"`, `"torch_pin": "torch==2.6.0 (resolves to 2.6.0+cu124
via the cu124 index)"`. Both environments' requirements locks confirm `torch==2.6.0+cu124`
(§1, §3 above). `generated_at_utc` `2026-07-09T22:38:20Z`; `git_sha`
`a89f89e9a0252d86393464a6b61bd806eae714e1` (matches the GO manifest's `retrieved_git_sha`,
same acquisition session).

**Status:** `PROPOSED` (provider/instance choice; owner may substitute an equivalent A100 instance
without reopening #1–#4).

---

## 6. Owner sign-off

Each decision is `PROPOSED` until the owner initials/dates the corresponding line below, flipping
its status to `CONFIRMED`. Confirmation here authorizes Phase-1 entry per the dev-pod plan's Hard
Phase-0 gate; it does **not** by itself edit `configs/compose_k562_v1_phase2.yaml` or advance the
sealed-run runbook past §2.5 (owner-approved exact Git SHA is a separate, later step).

| # | decision | current status | owner sign-off (flip to CONFIRMED — name / date) |
|---|---|---|---|
| 1 | GEARS revision `cell-gears==0.1.2` + published/default K562 training config | PROPOSED | ______________________ |
| 2 | GEARS GO-graph/gene2go — Harvard Dataverse `doi:10.7910/DVN/Q2ZV3E`, v2 manifest | **RESOLVED** | ______________________ |
| 3 | CPA revision `cpa-tools==0.8.5` + published/default combo config | PROPOSED | ______________________ |
| 4 | `approximation_bias` metric DEFINITION (spec `2026-07-13-compose-approximation-bias-metric-design.md`) | PROPOSED | ______________________ |
| 5 | Dev-pod provider: RunPod A100 80GB PCIe, torch cu124 | PROPOSED | ______________________ |

---

## 7. Reference-integrity verification (performed while drafting this record)

Every citation above was checked against the committed file, not transcribed from memory:

- `requirements.gears_env.lock` exists at the cited path; recomputed SHA-256
  `2d55a062cd8de0ac9b13299049848836e0917c7ef2027f9daa2554d88b53b8bf` matches the value quoted in
  §1 (independently recomputed with `shasum -a 256`, not copied from any manifest); `cell-gears==0.1.2`,
  `torch==2.6.0+cu124`, `numpy==1.26.4`, `pandas==2.2.3`, `scipy==1.11.4`, `scanpy==1.11.5`,
  `anndata==0.10.9` all appear verbatim in the file (lines 7, 68, 32, 47, 59, 57, 4).
- `requirements.cpa_env.lock` exists at the cited path; recomputed SHA-256
  `7d4d034bd91e276c737b51415c4443954fc6439f31068725b6a80115deebe29c` matches §3; `cpa-tools==0.8.5`,
  `torch==2.6.0+cu124`, `numpy==1.26.4`, `anndata==0.10.9`, `scvi-tools==0.20.3`, `jax==0.4.38`,
  `jaxlib==0.4.38`, `scanpy==1.11.5` all appear verbatim (lines 14, 105, 53, 6, 94, 29, 30, 90).
- `go_resource_manifest.json` exists at the cited path; recomputed file SHA-256
  `e9e724ebe77d55dc4c8bc9f18a832b8bcebdddc59af554c4af45ff3c2b6896cc` matches the value
  `gears_cpa_dependency_lock.json::go_resource_manifest.sha256` records for it — cross-file
  consistency confirmed, not just single-file existence. All datafile IDs, dataset versions,
  byte counts, MD5s, and SHA-256s in the §2 table are copied verbatim from the manifest.
- `gears_cpa_dependency_lock.json` exists at the cited path; `requirements_lock_sha256` fields for
  both envs (lines 95, 149) match the independently recomputed lock-file hashes above; `git_sha`
  (line 179) matches `go_resource_manifest.json::acquisition.retrieved_git_sha` (line 20) —
  both point to the same acquisition session (`2026-07-09T22:38:20Z`).
- `docs/superpowers/specs/2026-07-13-compose-approximation-bias-metric-design.md` exists; the
  `R_star`/`fairness_flag` quotes in §4 are copied verbatim from its §5 (lines 170–171).
- `docs/superpowers/plans/2026-07-13-compose-approximation-bias-implementation.md` exists; the
  `"unavailable"` carry-block quote in §4 is copied verbatim from line 249.
- `docs/superpowers/plans/2026-07-09-compose-dev-pod-real-workers.md` exists; the Open-decisions
  gate text and Global Constraint quotes in §0/§1/§2/§3 are copied verbatim from lines 20–21, 25,
  33–45.
- `docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md` §2.5 exists (lines
  152–167) as cross-linked in §0.
- `docs/superpowers/runbooks/2026-07-11-compose-gears-decision-probe-rerun.md` and
  `docs/superpowers/2026-07-11-compose-gears-decision-probe-results.md` exist, cited in §4 for
  Probe-A status.
- `git status --porcelain` was run immediately before drafting and again before committing this
  file: the only change in the working tree is this new document. **No edit was made to
  `configs/compose_k562_v1_phase2.yaml`** or to any other committed file — verified directly, not
  inferred.
