# COMPOSE-K562-v1 — activation-blocker evidence

> **Status:** protocol configuration is **ACTIVE**, but this evidence set is **not
> release-ready**. The dependency/runtime evidence is intentionally `INCOMPLETE`:
> compatibility smokes were observed, but the role-restricted row roster, sealed-pair
> zero-overlap proof, immutable logs/checkpoints, package artifact hashes, and container
> image digest were not captured. `assert_scientific_mode_allowed` therefore rejects this
> evidence. No seal was opened and no sealed outcomes were read.

> **Runtime authority notice (2026-07-21):** this tracked directory contains historical development
> snapshots and committed source contracts. Production PREPARE must not overwrite these files or point an
> `ActivationRecord` at them. It publishes a fresh, immutable evidence roster under the external approved-
> artifacts root; the owner-approved ResolvedRunSpec activation block binds those staged bytes and the staged
> finalized config, while the publication manifest records the immutable object version and one exact clean
> execution commit. Post-generation evidence commits are forbidden because they
> would invalidate report `git_sha == approved_git_sha == runtime HEAD`.

Real data: scPerturb `NormanWeissman2019_filtered.h5ad`, sha256
`efde6f5301fe256725dce1d980f37bd96a13481a9a16135515897368e631affc` (== committed
data-card). K562 CRISPRa. Generated on a rented A100 (torch 2.6.0+cu124).

## §10.1 activation_requirements — current evidence

| # | requirement | status | evidence |
|---|---|---|---|
| 1 | `real_norman_phi_rank_and_condition_report` | ⚠️ historical snapshot only | `real_norman_phi_rank_report.json` |
| 2 | `regime_specific_detectable_effect_analysis` | ⚠️ historical snapshot only | `real_norman_detectable_effect_report.json` |
| 3 | `finalized_norman_data_card_and_sha256` | ✅ done | `docs/data-cards/norman_compose_k562_v1.json` |
| 4 | `gears_cpa_reproducible_dependency_lock` | ⛔ `INCOMPLETE` | `gears_cpa_dependency_lock.json` + `requirements.{gears,cpa}_env.lock` |
| 5 | `independent_compose_outcome_store_and_access_audit` | ✅ built (Phase 2b) | `src/alive/compose/outcome_store.py` (+ tests) |
| 6 | `phase2_plan_metric_leakage_and_seal_integration_tests` | ✅ built | plans + `tests/alive/compose/` |

## Results summary (git_sha at generation in each JSON)

**1. Φ rank / condition** (`real_norman_phi_rank_report.json`, git 82a9c83) — Rank
gate **PASS** on the real `combo_calibration` design (41 pairs, z-universe 73 genes):

| k_total | sym_dim | rank | full rank | condition |
|---|---|---|---|---|
| 4 | 10 | 10 | yes | 15.8 |
| 6 | 21 | 21 | yes | 32.9 |
| 8 | 36 | 36 | yes | 484.2 |

Algebraically identifiable at all candidate dimensions; conditioning worsens with
`k` (k=8 is the most ill-conditioned → hardest noisy recovery).

**2. Regime detectable-effect / measurability** (`real_norman_detectable_effect_report.json`,
git 79b01e0) — ε computed on `combo_calibration` (dev role) only; sealed regimes
contribute outcome-independent counts only:

- measurability split-half ε ceiling **0.918** (PASS, floor 0.2)
- effect mean‖ε‖ 3.05, split-half noise 0.71, **SNR 4.28**
- power gate (floors: ≥20 pairs, ≥50 cells/pair) — `sealed_double_unseen` n=22
  cells=286 **PASS** (marginal, just above the 20 floor; seed-sensitive per the
  Phase-1 seed survey); `sealed_single_unseen` n=68 cells=300 **PASS**.

**3. GEARS/CPA dependency and compatibility record** (`gears_cpa_dependency_lock.json`,
full generation SHA in the JSON) — version-pinned, import-verified environments for the
two black-box comparator baselines, captured on the A100 (driver 550.127.05, uv 0.9.0). Two
**isolated per-baseline** environments (the activation-time guarded seam runs
each as a separate subprocess backend; neither shares the main ALIVE `.venv`):

| env | python | key pins | `import` | CUDA |
|---|---|---|---|---|
| `gears_env` (76 pkgs) | system 3.12 | cell-gears 0.1.2, torch 2.6.0+cu124, torch-geometric 2.8.0 | ✅ `import gears` | ✅ A100 |
| `cpa_env` (115 pkgs) | **managed 3.10.18** | cpa-tools 0.8.5, scvi-tools 0.20.3, jax/jaxlib 0.4.38, anndata 0.10.9, numpy 1.26.4, torch 2.6.0+cu124 | ✅ `import cpa` / `from cpa import CPA` | ✅ A100 |

The CPA lock was **verified by `uv pip sync`-ing it into a fresh managed env and
re-importing `cpa`** (`lock_verified_by_fresh_sync: true`). Compatibility smokes exposed
and repaired the CPA 0.7.2/`np.int` failure and GEARS' pandas/scipy incompatibilities;
the resolved CPA pin is 0.8.5. Reproducing the stack required pinning scvi
0.20.3 for `parse_use_gpu_arg`, jax 0.4.38 for `jaxlib.xla_extension`, anndata
<0.11 for `SparseDataset`, seaborn ≥0.13, excluding the abandoned rdkit-pypi);
the full rationale is in each env's `runtime_notes`. These flat locks pin versions but
do **not** pin wheel/sdist bytes, so the documented `unsafe-best-match` install is not yet
a release-grade reconstruction recipe. Runtime: set `MPLBACKEND=Agg` (headless).

**4. GO resource identity** (`go_resource_manifest.json`) — schema
`compose_go_resource_manifest_v2` binds the exact Harvard Dataverse dataset
`doi:10.7910/DVN/Q2ZV3E`, CC0-1.0 license, datafile IDs, dataset/file versions, byte
counts, upstream MD5 values, acquired SHA-256 values, and the extracted CSV SHA-256.
Its file SHA is in the dependency lock.

Both JSON contracts carry a checksum over all fields except `manifest_checksum`. Validate
them locally without accessing external data:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from alive.compose.activation_evidence import validate_dependency_lock
e = validate_dependency_lock(
    "docs/activation-evidence/compose/gears_cpa_dependency_lock.json"
)
print(e["run_gate"]["evidence_status"])
PY
```

The expected result for the currently committed evidence is `INCOMPLETE`. Validation
success means the record is internally honest and immutable; it does **not** mean the
scientific release gate passes.

## Linux kernel-isolation CI archives

`kernel_isolation_ci_<full-head-sha>.json` files are durable archive wrappers around
canonical CI receipts. Each archive binds the exact workflow/head SHA, GitHub run,
Linux kernel and architecture, JUnit content SHA, exact required testcase roster,
source artifact ID/name/archive digest/expiry, and nested/self checksums.

The committed `...614017b....json` archive preserves historical proof profile
`x86_64_seccomp_primitives_v1` from run `30154404171`. It proves the low-level
seccomp/receipt test at that exact code revision; it does **not** claim the newer
launcher-wiring profile. Every candidate using
`x86_64_seccomp_primitives_and_launcher_wiring_v2` requires its own later archive
containing both the primitive and real launcher→`execve`→driver tests. GitHub
artifacts remain transport and may expire; the version-controlled archive is the
durable review record. Neither profile substitutes for a production pod's own
runtime capture or authorizes scientific execution.

For a v2 run, an independent reviewer downloads the GitHub artifact and runs
`scripts/compose/archive_kernel_isolation_ci_receipt.py` with the observed artifact
ID/name/expiry and review timestamp/identity. The importer reads the ZIP itself,
requires its exact `junit.xml` + `kernel-isolation-ci-receipt.json` roster, binds
both files to the reviewed receipt, and writes the archive once. Hand-assembling a
v2 archive or recording only a run URL is not an accepted path.

To become `COMPLETE`, each backend must reference a committed
`compose_smoke_pair_roster_v1` file. The validator reads the actual sorted pair lists,
recomputes both roster hashes and their intersection, and requires zero overlap. It also
reads `compose_python_artifact_manifest_v1`, requires exactly one hashed selected artifact
for every package/version in both requirements locks, and rejects relative-path symlink
escapes. Finally, each backend's `compose_backend_smoke_artifact_manifest_v1` must give a
durable URI, immutable object version, and matching SHA-256 for every input/script/log/
checkpoint artifact. Scalar assertions, discarded objects, or unattached hashes are
insufficient.

## Honest caveats

- Evidence, **not** a green light: the runtime observations found useful compatibility
  faults, but they are not auditable seal-safe run evidence. A release-quality rerun must
  use only the COMPOSE fit-role artifact and populate every field in
  `run_gate.required_evidence`, with overlap count zero and exit code zero.
- Exact version pins are not exact package artifacts. A content-addressed wheelhouse
  manifest and immutable container image digest remain mandatory.
- `|combo_calibration|` = 41 and double-unseen = 22 are small; the double-unseen
  power margin is thin (registered seed 11; other seeds vary 12–27).
- Drivers: `src/alive/compose/{phi_rank,detectable_effect}.py` (pure, unit-tested)
  + `scripts/compose_{phi_rank,detectable_effect}_report.py` (real-input CLIs).
