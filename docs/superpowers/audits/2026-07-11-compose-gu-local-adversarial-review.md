# COMPOSE GU local adversarial implementation review — iteration 3 (INVALIDATED)

> **Status:** HISTORICAL RECORD ONLY. Post-review changes to the spec, implementation, and tests invalidated the
> byte identities below. The former CONDITIONAL PASS does not apply to the current working tree. A new clean-commit
> exact-SHA review is required. This document is **NOT** a readiness PASS, does not approve a scientific GEARS
> output bridge or pod benchmark, and opens no seal.

## Historical reviewed byte identities (no longer current)

| artifact | SHA-256 |
|---|---|
| `specs/2026-07-11-compose-gene-universe-design.md` | `e66f5e4d6a57b78280e79e27f0c2861b2a4d22b84dade63fd8f8b3707e915f23` |
| `src/alive/compose/gene_universe.py` | `67895ac455171acf8a2873550d0e4ba07f538f33ed60cec9e360954fcf051ebb` |
| `src/alive/compose/response.py` | `05922f04570ee159a31b5e09fc970c7a70b203f29989c0b95792abdac339b0ab` |
| `scripts/compose/gears_decision_probe.py` | `952a2b4563029f5c85065dcb65026e33100f8f4bbe4a98195c9dce4de4484ad8` |
| `tests/alive/compose/test_gene_universe.py` | `2847effaa7b8cb68125d43ef4cac561557238bdf8ef7c56b6ae1d0dd552fe3b6` |
| `tests/alive/compose/test_gears_decision_probe_cli.py` | `2a09de6614b9ef24315023a111a2aba53f8d9265cf4cf05a5e703be2607e73d5` |

These content hashes make the local review reproducible but do not substitute for the readiness index's required
reviewed Git SHA and independent verifier-output hash. Any listed-byte change invalidates this review.

## Adversarial findings and disposition

1. **Resolved P1 — scientific universe drift.** `R_gears` no longer replaces the full fit-role/response universe.
   Response HVGs/PCA/truth remain fixed on `U_full`; exact GEARS rosters are method-specific downstream objects.
2. **Resolved P1 — impossible prediction renormalization.** GEARS emits only `R_gears`, so omitted-gene library
   mass is unknowable. The prior statement that fit *and prediction* rows are normalized on `U_full` was unsound.
   The implementation normalizes allowed raw **fit-input** rows on `U_full` before subset. Scientific output
   projection is blocked until Probe A proves the reduced output already has the registered full-library log scale.
3. **Resolved P1 — dev-seal materialization.** The maintained CLI cannot accept the original outcome/source
   `.h5ad`; it consumes a stable-descriptor-verified fit-role artifact that already excludes dev-sealed rows.
4. **Resolved P2 — 2,088-vs-2,000 overflow.** Frozen response HVGs and globally eligible perturbation genes form
   `M` first; fill count is exactly `N_target - |M|`; overflow fails closed.
5. **Resolved P2 — ordering drift.** Response HVG selection and GEARS fill share
   `response.rank_gene_indices_by_variance` for descending variance/ascending full-index ordering. Sparse control
   variance uses bounded column blocks with NumPy `var(axis=0)` arithmetic matching the dense response operator.
6. **Resolved P2 — mutable/replaceable roster identity.** Alias/roster loaders use stable non-symlink regular-file
   descriptors, exact file/self checksums, canonical JSON, exact key rosters, deep read-only provenance mappings,
   and byte-identical-only re-emission.
7. **Resolved P2 — probe-input provenance.** Roster building binds candidate, gene2go, alias, fit-role, response,
   control-row, generator, and exact-size identities. Probe input generation revalidates source bytes and emits a
   separately typed log-normalized AnnData plus canonical manifest; offline verification rechecks stable H5AD,
   roster, row/role/gene identity, and checksums.

## Remaining blockers — intentionally not papered over

- The working tree needs a clean commit followed by an independent exact-SHA review. This document alone cannot
  promote GU to readiness PASS.
- Real pre-split perturbation-candidate, canonical alias, and gene2go-node artifacts have not yet been generated
  and hash-bound from Norman/GO inputs; therefore real `|M|` and candidate rosters do not exist yet.
- The maintained CLI has roster/report and probe-input prepare/verify subcommands, but the fresh GEARS timing
  subcommand, raw CPU/GPU/RSS sampler, repeat/noise gate, and durable command log still require implementation
  before Probe B.
- The scientific worker/payload does not yet consume `R_gears`. That integration and the output negative-value
  policy are correctly blocked on Probe A scale/equivalence evidence; the current raw-pseudobulk path remains
  activation-blocked.
- No real GEARS environment, A100 behavior, Norman input, or external resource was exercised in this local review.

## Historical local verification (no longer evidence for the current bytes)

- Focused seal/fit/response/roster/worker/probe/evidence suite: **163 passed**.
- Full repository suite after all edits: **1938 passed, 1 skipped**; no failures.
- `ruff check --no-cache .`: PASS.
- `ruff format --check --no-cache .`: PASS, 207 maintained Python files formatted.
- `git diff --check`: PASS.
- Tests used `PYTHONDONTWRITEBYTECODE=1`, a `/tmp` bytecode prefix, and pytest cache was disabled.

## Current local remediation snapshot — NOT an independent review

This section records the locally verified post-iteration-3 remediation bytes. It does not revive the historical
CONDITIONAL PASS because the worktree is not yet a clean reviewed commit and the verifier is not independent.

| artifact | current SHA-256 |
|---|---|
| `specs/2026-07-11-compose-gene-universe-design.md` | `d1b12ce927503de927cee3a4a4217b9796361a77672f47ce646b8fb60be6c0a4` |
| `src/alive/compose/gene_universe.py` | `9fa2fa1d0c29af38bc9015adf5b41ad45790d6dc1cd2c10f41f83c504493b5e1` |
| `src/alive/compose/response.py` | `05922f04570ee159a31b5e09fc970c7a70b203f29989c0b95792abdac339b0ab` |
| `src/alive/compose/fit_role.py` | `18d17feb7d0dbf5030567cbdfb806cfdbe793409cc0f6b7bcc7eacd4adb10a5d` |
| `scripts/compose/gears_decision_probe.py` | `ee889ccac20410bce83e4ef8f08b4e85a1b1c77906873d1c393d6a84b726fc93` |
| `tests/alive/compose/test_gene_universe.py` | `293728421025b531ddf6dd914e72bfaf7a156a10823122f936230f2139944b81` |
| `tests/alive/compose/test_gears_decision_probe_cli.py` | `e8549a30c4b2f98e4bdfd925e11d855ba050e0e07f35b2249389182d3b2db82e` |
| `runbooks/2026-07-11-compose-gears-decision-probe-rerun.md` | `3d51d6e9c05df671a8c0522b14602278eae865298d0fc1b557ca63a61de8b87a` |

Local remediation adds: exact frozen-HVG re-binding at load and consumption; mandatory external roster digest;
canonical list/order/exclusion/type validation; biologically valid legacy-synonym handling with contextual collapse
guards; malformed self/control combos rejected; receipt-last roster generation; externally pinned
manifest→receipt→roster→H5AD verification; source-closure, dependency-lock, driver, and producer/verifier runtime
identities; pre-publication hashes that avoid re-open TOCTOU; and distinct multi-artifact destinations.

Current local gates on these bytes:

- Full repository suite: **1959 passed, 1 skipped**; 2 pre-existing/intentional warnings, no failures.
- Focused response/fit-role/roster/probe/worker/evidence suite: **130 passed** with AnnData implicit-modification
  warnings promoted to errors.
- `ruff check --no-cache .`: PASS.
- `ruff format --check --no-cache .`: PASS, 207 maintained Python files formatted.
- `git diff --check`: PASS.
- No sealed evaluation, real scientific fit, external data access, or pod/GPU work was performed.

## Promotion rule

Commit the reviewed contents without unrelated changes, record the resulting Git SHA, run the full local gate,
obtain an independent review against that exact SHA, and store its verifier output/hash. Only then may the GU row
move from “local implementation” to PASS. Probe A can follow on a dev pod; Probe B additionally requires the
maintained timing/evidence subcommand. Neither authorizes the sealed confirmatory run.
