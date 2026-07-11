# COMPOSE-K562 gene-universe generator — design spec

> **Protocol:** `COMPOSE-K562-v1` (ACTIVE). **Date:** 2026-07-11. **Status:** DESIGN (pre-plan).
> **Opens NO seal.** Formalizes §2 of `docs/superpowers/2026-07-10-compose-gears-scale-and-gene-universe-recommendations.md`
> into an implementable contract, incorporating the rigor corrections in
> `docs/superpowers/2026-07-11-compose-gears-decision-probe-results.md` (the 2,088-vs-2,000 root cause) and the
> CLAUDE.md invariants it must satisfy (§3.5 no outcome-selected universe, §6 eligibility fixed before the split,
> §4.2 write-once provenance).

---

## 0. Scientific-claim scope {#scope}

This spec defines **how the ordered gene roster (the "gene universe") is produced**, not any new scientific
claim. The gene universe is the `var_names` (columns) of the COMPOSE fit-role artifact: the genes GEARS/CPA
predict over and within which the response operator selects its HVGs and fits its frozen PCA. Fixing the universe
by an **outcome-free, digest-bound, reproducible** procedure is a *reproducibility and provenance* requirement,
not a claim about epistasis. It opens no seal, reads no sealed outcome, and does not change `config_sha256` by
itself (freezing `N_target` into config is a separate, owner-gated act that mints a new run identity).

**What it must NOT do (invariants it exists to enforce):** select genes using any perturbation response, effect
size, or sealed expression (CLAUDE.md §3.5); let the requested/sealed pair roster influence the universe;
silently drop ineligible perturbations (CLAUDE.md §6).

---

## 1. Motivation — the 2,088-vs-2,000 root cause {#motivation}

The dev-pod benchmark built its roster ad-hoc (`bench_prep.py`: "select top-2,000 by control variance, then
force-add the 88 perturbation genes not already present"), producing **2,088 genes with no audited mandatory-set
size**. That "select-then-force-add" pattern is exactly what this contract forbids: the mandatory set `M` must be
computed **first**, `N_target` frozen `≥ |M|`, and the fill sized to `N_target − |M|`, so the final roster has
**exactly `N_target`** unique entries with a recorded reason for every gene. Making `|M|` a first-class output of
an audited generator (report mode) is the fix.

---

## 2. Inputs — all outcome-free, all digest-bound {#inputs}

The generator reads only:

| input | provenance / digest | notes |
|---|---|---|
| canonical **full `var`** order | `full_var_order_sha256` | every measured gene ID, the master order |
| **CONTROL cells** raw counts | `control_row_identity_sha256` | control rows only; never perturbed/sealed rows |
| `n_hvg` (response HVG count) | from resolved config | **sizing guidance only** — NOT used to compute `M`; report mode recommends `N_target ≥ |M| + n_hvg`, freeze mode guards `N_target ≥ n_hvg` |
| pre-split **perturbation-candidate list** | `perturbation_candidate_sha256` | source-level single/combo tokens, BEFORE role assignment; NOT `payload["pair_ids"]` |
| pinned **`gene2go`** | `gene2go_sha256` | GO-graph node set (GEARS perturbation composability) |
| **alias artifact** (§6) | `alias_sha256` | hand-curated, committed |
| `N_target` | **owner-frozen; freeze mode only** | `≥ |M|`; recorded in config → new run identity |

The control-variance **median library** for the fill ranking is DERIVED by the generator as the `np.median` of
the control cells' full-`var` library sizes, then applied via `fit_role._normalize_log1p_full` (fit_role.py:1054),
and **recorded** in the artifact for reproducibility — not a separate external input. It is used only for the
outcome-free fill ranking (§3.5). **The generator does not compute or predict the response operator's HVG set**
(see §3): the response operator selects its HVGs downstream, from the generated universe, unchanged.

The generator MUST NOT open `ComposeOutcomeStore`, read `payload["pair_ids"]`, or read any perturbed/sealed
expression. **Request-roster invariance:** re-running with a different requested/sealed pair roster and identical
upstream inputs MUST yield a byte-identical universe artifact.

---

## 3. Pipeline — one path; report mode stops at `M` {#pipeline}

Steps 1–3 are **report mode** (need no `N_target`); steps 4–6 are the **freeze** continuation; step 7 is
consumption. Every step is outcome-free and request-roster-invariant.

1. **Canonicalize** the alias map (§6) across perturbation tokens, full `var`, `gene2go` keys, and the pair
   manifest **before** any downstream artifact. Each record stores `{raw_symbol, canonical_symbol, source,
   version}`. Mapping must be one-to-one on measured `var`; empty names, many-to-one, or two measured columns
   collapsing to one canonical symbol → **fail closed**.
2. **Global perturbation eligibility** (computed from the pre-split candidate list): a single/combo is eligible
   iff **every** canonical perturbation gene ∈ `var ∩ gene2go`. Record every exclusion with a machine reason
   (e.g. `IER5L: absent_from_gene2go`, `KIAA1804: unmapped_alias`). This set is global and fixed before role
   assignment; the requested/sealed subset never enters it.
3. **Mandatory set `M`** = the set of canonical genes appearing in the **global eligible-perturbation set**
   (§3.2). These are the must-include genes (GEARS fail-closes on a fit perturbation gene absent from the roster,
   gears_worker.py:848,884). `M` does **not** include response-HVG genes: the response operator selects its HVGs
   *from* the universe downstream, so they are trivially `⊆` universe (nothing to guarantee here), and the
   §3.5 fill — which is **not** GO-gated — already places the high-variance genes into the universe regardless of
   GO annotation, which is exactly the CRITICAL-1 intent (a response HVG needs no GO term).
   **→ Report mode emits `|M|`, `eligibility_sha256`, the exclusion table, and the candidate/eligible/excluded
   counts (`n_candidates`/`n_eligible`/`n_excluded`), and stops.**
4. **Freeze** `N_target` (owner-supplied). If `|M| > N_target` → raise `GeneUniverseError` (owner must register a
   larger `N_target` and a new run identity). Never silently exceed `N_target` or drop a mandatory gene.
5. **Deterministic fill:** normalize CONTROL cells to the frozen median library + `log1p`, rank all
   **non-mandatory** measured genes by descending control variance, tie-break by ascending full-`var` index, take
   exactly `N_target − |M|`. No perturbation response enters the ranking. (Same control-variance statistic as
   step 3; reuse the shared helper.)
6. **Canonical final order:** the mandatory+fill set, emitted in full-`var` order → exactly `N_target` unique
   entries. Emit the **gene-universe artifact** (§4).
7. **Fail-closed consumption:** any downstream consumer (fit-role extractor, worker output) must contain exactly
   this ordered roster; any missing/extra/duplicate gene, order mismatch, or digest mismatch → `INVALID`.

**Response operator is UNCHANGED (no scientific change).** The response operator continues to select its HVGs and
fit its frozen PCA over the fit-role `var_names` (= the generated universe), with its existing median/normalization
basis (`response.py`). The generator neither predicts nor constrains that selection; it only guarantees the
universe (a) contains every eligible-perturbation gene (`M`) and (b) contains the top-`(N_target − |M|)`
control-variance genes (fill), so the response operator's HVG selection over the universe has a full-variance basis
to draw from. **Sizing:** because the response operator picks `n_hvg` HVGs from the universe, freeze mode guards
`N_target ≥ n_hvg`; report mode additionally recommends `N_target ≥ |M| + n_hvg` so the fill alone can cover the
response basis. No full-`var`-vs-universe reconciliation and no cross-median equality is required — the earlier
draft's response-HVG equality was unsound (HVG variance ranking is not invariant to the `log1p` median target) and
is removed.

---

## 4. Output — the gene-universe artifact {#output}

A single immutable artifact (JSON; write-once per CLAUDE.md §4.2 via `io.atomic_write_once`):

```
gene_universe.v1:
  ordered_roster:            [canonical gene IDs, length N_target, full-var order]
  n_target:                  int
  mandatory_size:            |M|              # = |eligible_perturbation_genes|
  eligible_perturbation_genes: [...]          # the genes of M
  eligibility_exclusions:    [{token, gene, reason}, ...]
  fill_count:                N_target - |M|
  normalization:             {median_library: float, transform: ["normalize_total_median","log1p"]}
  provenance:
    full_var_order_sha256, control_row_identity_sha256,
    eligibility_sha256, alias_sha256, gene2go_sha256, generator_code_sha256,
    perturbation_candidate_sha256, n_hvg, n_target
  ordered_roster_sha256:     canonical digest over ordered_roster (binds fit-role var_names)
```

Report mode emits the same object **without** `n_target`/`fill_count`/`ordered_roster` (a `mandatory_report.v1`
with `mandatory_size`, `eligible_perturbation_genes`, the exclusion table, the step-1–2 digests, and the
`n_candidates`/`n_eligible`/`n_excluded` counts).

---

## 5. Invariants → CLAUDE.md mapping {#invariants}

- **Outcome-free** (§3.5): control-variance only; no perturbation response, effect size, or sealed expression is
  read at any step. Enforced by construction (inputs §2 exclude them) and by a test that runs the generator with
  the sealed store absent.
- **Eligibility fixed before the split** (§6): global eligibility is computed from the pre-split candidate list;
  exclusions are recorded, never silently skipped.
- **Request-roster invariant:** the artifact and every digest are independent of `payload["pair_ids"]`.
- **Write-once provenance** (§4.2): the artifact is written via `atomic_write_once`; re-emission is allowed only
  if byte-identical.
- **Fail-closed:** alias violations, `|M| > N_target`, and any consumption mismatch raise, never warn-and-proceed.

---

## 6. Alias artifact {#alias}

Hand-curated, committed (e.g. `configs/compose_gene_aliases_v1.json`), digest-pinned by `alias_sha256`. Schema:
`[{raw_symbol, canonical_symbol, source, version, reason}]`. Contract: one-to-one on measured `var`; a canonical
symbol must be a single measured column; unmapped symbols that then fail `var ∩ gene2go` are recorded as
eligibility exclusions (not silently dropped). Adding/changing an alias regenerates the universe artifact and
every dependent digest — never a runtime rename. Initial content is the minimal known Norman set (`KIAA1804 →
MAP3K21`, plus any other symbol that canonicalization resolves); genuinely unmappable tokens (e.g. `IER5L`) get
**no** alias and surface as recorded exclusions.

---

## 7. Integration with the fit-role extractor {#integration}

The gene-universe artifact is produced **upstream** of `fit_role.generate_fit_role_artifact`. The extractor
consumes `ordered_roster` as its `var_names` and records `ordered_roster_sha256` in provenance (it may map onto
the existing `calibration_gene_set_hash`/`gene_order_sha256` fields or a new `gene_universe_sha256` — the plan
decides). Consumption is **fail-closed**: if the extractor's resulting `var_names` ≠ `ordered_roster` (missing,
extra, duplicate, or reordered), it raises. No change to the fit-role artifact's write-once/leakage contract.

---

## 8. Module & API surface {#api}

New module `src/alive/compose/gene_universe.py`. Public API (type-hinted, NumPy-style docstrings):

- `GeneUniverseError(Exception)` — fail-closed signal for all violations.
- `AliasMap` — loaded, digest-verified alias artifact; `AliasMap.load(path, *, expected_sha256) -> AliasMap`;
  `.canonicalize(symbol) -> str` (fail-closed on collision/empty).
- `MandatoryReport` (dataclass): `mandatory_size` (= `|eligible_perturbation_genes|`),
  `eligible_perturbation_genes`, `eligibility_exclusions`, `n_candidates`, `n_eligible`, `n_excluded`, `n_hvg`,
  `recommended_min_n_target` (= `mandatory_size + n_hvg`), and the step-1–2 digests.
- `compute_mandatory_report(*, full_var, control_counts, perturbation_candidates, gene2go, alias, n_hvg) ->
  MandatoryReport` — **report mode** (steps 1–3; `M` = the eligible-perturbation genes). `n_hvg` is used only for
  the sizing recommendation, never to compute `M`. No `N_target`, no sealed access.
- `GeneUniverseArtifact` (dataclass) — the §4 object; `.write(path)` via `atomic_write_once`.
- `generate_gene_universe(*, <same inputs>, n_target, out_path) -> GeneUniverseArtifact` — **freeze mode** (steps
  1–6); raises `GeneUniverseError` if `|M| > n_target` or `n_target < n_hvg`.
- `assert_roster_matches(var_names, artifact) -> None` — the §7/§3.7 fail-closed consumption check.

Shared helpers reused (no drift): `response._select_hvg`, `fit_role._normalize_log1p_full` (fit_role.py:1054),
`provenance.sha256_json`, and `fit_role.canonical_gene_order_sha256` (fit_role.py:112). No hardcoded gene lists, thresholds, or `N_target` in
source (CLAUDE.md §7); `n_hvg`, `N_target`, and the alias path come from config/artifacts.

---

## 9. Verification / test plan {#tests}

- **Known-answer:** a tiny synthetic full-`var` + control matrix + candidate list with a hand-computed `M`,
  fill order, and final roster → assert exact `ordered_roster`, `mandatory_size`, `fill_count`.
- **Downstream response-operator validity:** the response operator fits over a generated universe (selects its
  `n_hvg` HVGs from the roster and fits its PCA) with no change to `response.py`; the selected HVGs are `⊆` roster
  by construction.
- **Sizing guards:** freeze mode raises when `N_target < n_hvg`; `compute_mandatory_report` reports
  `recommended_min_n_target = |M| + n_hvg`.
- **Alias:** injectivity holds; a many-to-one / collision / empty-name alias fails closed; a mapped symbol is
  canonicalized on every surface.
- **Eligibility:** a candidate with a gene outside `var ∩ gene2go` is excluded with the right reason and never
  appears in `eligible_perturbation_genes`; nothing is silently dropped.
- **`|M| > N_target`** raises `GeneUniverseError`.
- **Request-roster invariance (regression):** changing only `payload["pair_ids"]` yields an identical
  `ordered_roster_sha256`, identical fit-role training rows, identical model initialization, and identical
  checkpoint SHA.
- **Outcome-independence:** the generator produces the identical artifact with the sealed outcome store absent /
  unreadable (proves no sealed access path).
- **Determinism / write-once:** two runs on identical inputs are byte-identical; re-emitting over an existing
  artifact with different bytes fails (`atomic_write_once`).

---

## 10. Non-goals / out of scope {#non-goals}

- The **value** of `N_target`. This spec provides the mechanism, not the number. The intended flow: run **report
  mode** once to get `|M|` and the exclusion provenance; run **freeze mode** at candidate `N_target`s (each
  `≥ |M|`, e.g. a 2k-ish and a 5k-ish size) to emit contract-correct rosters; a *correct* Probe B benchmarks
  those rosters; the owner then freezes the final `N_target` into config (new run identity).
- Any change to the response operator (`response.py`): its HVG selection + frozen PCA run downstream over the
  generated universe, unchanged.
- The Option-1 published-scale GEARS adapter (separate spec/plan).
- The GEARS per-epoch eval-noop wall-time optimization (separate experiment; determinism-gated).
- Any change to the sealed-run seal/leakage machinery.
