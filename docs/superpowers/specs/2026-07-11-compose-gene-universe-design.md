# COMPOSE-K562 GEARS gene-roster generator — design spec

> **Protocol:** `COMPOSE-K562-v1` (ACTIVE / RELEASE-BLOCKED; seal UNOPENED). **Date:** 2026-07-11.
> **Status update (2026-07-19 sanitization):** generator and fit-input preprocessing are IMPLEMENTED + MERGED;
> exact-committed-SHA independent review passed for `7f6595f` and is recorded in
> `docs/superpowers/audits/2026-07-11-compose-gu-exact-sha-independent-review.md`. The scientific GEARS output
> bridge remains explicitly blocked on conforming Probe A and the current readiness gate.
> **Opens NO seal.** Formalizes §2 of `docs/superpowers/2026-07-10-compose-gears-scale-and-gene-universe-recommendations.md`
> into an implementable contract, incorporating the rigor corrections in
> `docs/superpowers/2026-07-11-compose-gears-decision-probe-results.md` (the 2,088-vs-2,000 root cause) and the
> CLAUDE.md invariants it must satisfy (`CLAUDE.md`#invariants/#data-eval/#provenance).

---

## 0. Scientific-claim scope and two-universe architecture {#scope}

This spec defines **how the ordered, method-specific GEARS prediction roster is produced**, not a new scientific
claim and not a replacement for COMPOSE's registered response universe. Two objects are deliberately separate:

1. **Scientific fit-role / response universe `U_full`:** the canonical full measured `var` order carried by the
   fit-role `.h5ad`. The response operator computes its full-library normalization target, selects its HVGs, and
   fits its frozen PCA on this universe exactly as registered in the fit-data contract. CPA also consumes this
   full universe. This scientific target is upstream of, and invariant to, GEARS feasibility choices.
2. **GEARS roster `R_gears ⊂ U_full`:** an outcome-free, digest-bound subset used only to make GEARS training and
   prediction tractable. It must contain every frozen response HVG and every globally eligible perturbation gene.
   The fit-input adapter normalizes each allowed raw fit row on `U_full` first and subsets to `R_gears` second.
   GEARS predicts only `R_gears`, so a reduced prediction can never be renormalized as though omitted `U_full`
   genes were zero. A scientific output bridge is eligible only if Probe A establishes that GEARS predictions
   already inhabit the same full-library-normalized log scale; otherwise the registered named-raw comparator
   remains in force. The bridge and its negative-value policy are not defined by this spec.

Fixing `R_gears` is a reproducibility/provenance requirement, not a redefinition of truth δ. It opens no seal,
reads no sealed outcome, and does not change `config_sha256` by itself (freezing `N_target` and the roster SHA
into config is a separate, owner-gated act that mints a new run identity).

**What it must NOT do (invariants it exists to enforce):** select genes using any perturbation response, effect
size, or sealed expression (`CLAUDE.md`#invariants); let the requested/sealed pair roster influence `R_gears`;
silently drop ineligible perturbations (`CLAUDE.md`#data-eval); subset `U_full` before full-library normalization; or let
GEARS/GO/resource constraints alter the frozen response HVGs/PCA used to define truth and score every method;
or infer a missing full-library denominator by summing a reduced GEARS prediction.

---

## 1. Motivation — the 2,088-vs-2,000 root cause {#motivation}

The dev-pod benchmark built its GEARS roster ad-hoc (`bench_prep.py`: "select top-2,000 by control variance, then
force-add the 88 perturbation genes not already present"), producing **2,088 genes with no audited mandatory-set
size**. That "select-then-force-add" pattern is exactly what this contract forbids: the mandatory set `M` must be
computed **first**, `N_target` frozen `≥ |M|`, and the fill sized to `N_target − |M|`, so the final roster has
**exactly `N_target`** unique entries with a recorded reason for every gene. Making `|M|` a first-class output of
an audited generator (report mode) is the fix.

The first review revision tried to avoid recomputing response HVGs under a mismatched normalization median by
dropping them from `M` and fitting the response operator downstream on the reduced roster. That diagnosis was
correct but the remedy was not: subsetting before response normalization changes per-cell library sizes, HVGs,
PCA, and therefore truth δ, while contradicting the registered full-gene fit-data contract. This revision instead
consumes the already frozen full-universe response artifact and includes its `hvg_gene_ids` in `M`; no HVG is
recomputed or required to be invariant across medians.

---

## 2. Inputs — all outcome-free, all digest-bound {#inputs}

The generator reads only:

| input | provenance / digest | notes |
|---|---|---|
| verified full fit-role artifact | `fit_artifact_content_sha256` | raw counts over canonical full measured `U_full`; no sealed rows |
| canonical **full `var`** order | `full_var_order_sha256` | exactly the fit-role `gene_order_sha256`; every measured gene ID |
| frozen response projection | `response_artifact_sha256` | must bind the same `raw_data_sha256` and full gene order; supplies `hvg_gene_ids`, `median_library`, PCA identity |
| **CONTROL cells** raw counts over `U_full` | `control_row_identity_sha256` | used only for deterministic non-mandatory fill; never perturbed/sealed rows |
| pre-split **perturbation-candidate list** | `perturbation_candidate_sha256` | source-level single/combo tokens, BEFORE role assignment; NOT `payload["pair_ids"]` |
| pinned **`gene2go`** | `gene2go_sha256` | GO-graph node set (GEARS perturbation composability) |
| **alias artifact** (§6) | `alias_sha256` | hand-curated, committed; must match the upstream canonical fit-role/response lineage |
| `N_target` | **owner-frozen; freeze mode only** | `≥ |M|`; recorded in config → new run identity |

The generator MUST NOT derive a second response normalization target or recompute HVGs. It verifies that the
frozen response projection's `gene_order_sha256` equals `full_var_order_sha256`, takes its exact
`hvg_gene_ids`/`median_library`, and binds their digests into the GEARS roster artifact. For the optional fill
ranking only, CONTROL rows are normalized over **all columns of `U_full`** to that frozen median and `log1p`-ed.
This keeps the ranking on the same full-library basis without claiming that the generator reproduces the response
operator's HVG selection.

The generator MUST NOT open `ComposeOutcomeStore`, read `payload["pair_ids"]`, or read any perturbed/sealed
expression. Reading the already frozen response artifact is permitted because it was fit only on registered
non-sealed roles. **Request-roster invariance:** re-running with a different requested/sealed pair roster and
identical upstream inputs MUST yield a byte-identical GEARS roster artifact.

---

## 3. Pipeline — one path; report mode stops at `M` {#pipeline}

Steps 1–3 are **report mode** (need no `N_target`); steps 4–6 are the **freeze** continuation; step 7 is
consumption. Every step is outcome-free and request-roster-invariant.

1. **Verify upstream canonical identity.** The alias map (§6) is applied across perturbation tokens, full `var`,
   `gene2go` keys, and the pair manifest **before** the full fit-role and response artifacts are created. The
   roster generator never renames a frozen artifact at runtime; it verifies `alias_sha256`, exact full gene order,
   uniqueness, and response↔fit-role source identity. Empty names, many-to-one mappings, two measured columns
   collapsing to one canonical symbol, or lineage mismatch → **fail closed**.
2. **Global perturbation eligibility** (computed from the pre-split candidate list): a single/combo is eligible
   iff **every** canonical perturbation gene ∈ `var ∩ gene2go`. Record every exclusion with one of the two
   machine reasons the generator emits — `absent_from_full_var` (canonical symbol is not a measured column) or
   `absent_from_gene2go` (measured but not GO-composable) — e.g. `IER5L: absent_from_gene2go`. A symbol with no
   alias entry is simply canonicalized to itself and then judged by the same two reasons (there is no separate
   `unmapped_alias` reason). This set is global and fixed before role assignment; the requested/sealed subset
   never enters it. The standalone control token is ignored as a candidate, but control-containing combos,
   raw self-combos, and combos whose aliases collapse to one canonical gene are malformed inputs and fail closed.
   The derived node artifact is not trusted on its own: the maintained builder validates the activation-pinned
   GO resource manifest, hashes the manifested sibling `gene2go_all.pkl`, decodes its complete key set, and
   requires the artifact's byte-sorted roster and `source_gene2go_sha256` to match exactly before reading any
   fit-role expression.
3. **Mandatory set `M`** = `frozen_response_hvg_genes ∪ eligible_perturbation_genes`.
   `frozen_response_hvg_genes` are read verbatim from the full-universe response projection; the generator does
   not rank or recompute them, so no cross-median equality assumption exists. GO membership is irrelevant for a
   response-only HVG. Eligible perturbation genes are mandatory because GEARS fail-closes on a fit perturbation
   gene absent from its roster (`gears_worker.py:848,884`).
   **→ Report mode emits `|M|`, `response_hvg_sha256`, `response_artifact_sha256`, `eligibility_sha256`, the
   exclusion table, candidate/eligible/excluded counts, and component/overlap counts, and stops.**
4. **Freeze** `N_target` (owner-supplied). If `|M| > N_target` → raise `GeneUniverseError` (owner must register a
   larger `N_target` and a new run identity). Never silently exceed `N_target` or drop a mandatory gene.
5. **Deterministic fill:** normalize CONTROL rows over **all `U_full` genes** to the frozen response
   `median_library` + `log1p`, rank all **non-mandatory** measured genes by descending control variance, tie-break
   by ascending full-`var` index, and take exactly `N_target − |M|`. No perturbation response enters the ranking.
6. **Canonical final order:** emit the mandatory+fill set in full-`var` order → exactly `N_target` unique entries.
   Emit the **GEARS roster artifact** (§4).
7. **Fail-closed GEARS fit-input consumption:** the full raw fit-role artifact remains `U_full`. The maintained
   adapter verifies fit-role/response/roster lineage, normalizes allowed fit rows over all `U_full` columns, then
   subsets to this exact ordered roster before `PertData.new_data_process`. It constructs
   `PertData(..., default_pert_graph=False)`, the upstream-supported method-roster graph mode, so perturbation
   nodes are exactly the canonical method roster intersected with the pinned gene2go mapping. The legacy
   `default_pert_graph=True` path is forbidden because it silently applies the separate, non-canonical
   `essential_all_data_pert_genes.pkl` symbol list and can contradict the registered `var ∩ gene2go`
   eligibility decision. The graph policy string is frozen in the worker config and every checkpoint. The
   resulting probe/model input and
   GEARS prediction roster must equal `R_gears`; any missing/extra/duplicate gene, order mismatch, response-HVG
   omission, or digest mismatch → `INVALID`. CPA and the response operator do not consume this subset. A reduced
   GEARS prediction is not passed to the raw-count response projector; its scientific bridge is Probe-A-gated.

**Response operator scientific behavior is UNCHANGED**, via a single behavior-preserving refactor of
`response.py`. Its HVG selection and frozen PCA fit once over `U_full`, before `R_gears` is generated, and its
artifact checksum/HVG list/PCA remain byte-identical regardless of `N_target`, `gene2go`, GEARS resources, or
requested pairs. The only `response.py` change is extraction of the shared descending-variance/ascending-index
ordering into `rank_gene_indices_by_variance` (§8): `_select_hvg` now delegates to it and reproduces the prior
`np.lexsort` ordering exactly for finite non-negative variance (the sole realistic case for `log1p`-normalized
control counts); the helper adds an input-validation raise-path that real control-derived variance never
triggers. The earlier draft's attempted generator-side response-HVG equality was unsound because normalization
medians differed; this design avoids the comparison entirely by consuming the one authoritative frozen response
artifact.

---

## 4. Output — the method-specific GEARS roster artifact {#output}

A single immutable artifact (JSON; write-once per `CLAUDE.md`#provenance via `io.atomic_write_once`):

```
gears_gene_roster.v1:
  schema:                    "compose_gears_gene_roster_v1"
  ordered_roster:            [canonical gene IDs, length N_target, full-var order]
  n_target:                  int
  mandatory_genes:           [...]             # M in full-var order (frozen HVGs ∪ eligible perturbation genes)
  mandatory_size:            |M|
  response_hvg_ids:          [...]             # verbatim frozen response HVGs
  eligible_perturbation_genes: [...]           # ⊆ mandatory_genes; verified on load
  eligibility_exclusions:    [{token, gene, canonical_gene, reason}, ...]
  fill_count:                N_target - |M|
  normalization_basis:       {gene_order: "U_full", median_library: float, transform: ["normalize_total_median","log1p"], subset_after_normalize: true}
  provenance:
    fit_artifact_content_sha256, raw_data_sha256, full_var_order_sha256, control_row_identity_sha256,
    response_artifact_sha256, response_hvg_sha256,
    eligibility_sha256, alias_sha256, gene2go_sha256, generator_code_sha256,
    perturbation_candidate_sha256, n_target
  ordered_roster_sha256:     canonical digest over ordered_roster (binds GEARS input/output var order)
  artifact_checksum:         canonical digest over every other field (self-excluding; tamper-evident on load)
```

The maintained builder also writes `compose_gears_roster_receipt_v1` **last**, after the roster and mandatory
report are durable. The receipt is the completion marker and binds the roster/report file SHA-256 values,
roster/self/order identities, fit/response/payload identities, candidate/GO/alias artifact SHA-256 values,
`N_target`, the generator source-closure digest, maintained-driver code SHA-256, dependency-lock SHA-256, and a
canonical runtime fingerprint (Python/platform + numerical package versions). A missing receipt means an incomplete
generation and is never repairable in place. Preparation records its own runtime fingerprint separately; a
generator/pod runtime difference is evidence, not silently collapsed into one identity.

Report mode emits a distinct `compose_gears_mandatory_report_v1` object: `full_var`, `mandatory_genes`,
`mandatory_size`, `response_hvg_ids`, `eligible_perturbation_genes`, `eligible_tokens`, the exclusion table,
`median_library`, all upstream identity digests, `n_candidates`/`n_eligible`/`n_excluded`, and the
response-HVG/perturbation overlap count. The maintained CLI wraps that object with a self-excluding
`report_checksum`. It does **not** pretend to be the freeze artifact with three fields removed.

---

## 5. Invariants → CLAUDE.md mapping {#invariants}

- **Outcome-free** (§3.5): control-variance only; no perturbation response, effect size, or sealed expression is
  read at any step. Enforced by construction (inputs §2 exclude them) and by a test that runs the generator with
  the sealed store absent.
- **Eligibility fixed before the split** (§6): global eligibility is computed from the pre-split candidate list;
  exclusions are recorded, never silently skipped.
- **Request-roster invariant:** the artifact and every digest are independent of `payload["pair_ids"]`.
- **Scientific-target invariant:** response artifact/HVG/PCA identity is fixed over `U_full` before GEARS roster
  generation and cannot vary with `N_target`, `gene2go`, alias eligibility, or GEARS availability.
- **Normalize before subset:** every allowed raw GEARS **fit-input** row is library-normalized over `U_full`;
  slicing to `R_gears` first is forbidden because the per-cell full/reduced library ratio is not globally
  constant. A GEARS prediction contains only `R_gears` and is never renormalized by its reduced row sum.
- **Write-once provenance** (§4.2): the artifact is written via `atomic_write_once`; re-emission is allowed only
  if byte-identical.
- **Roster authenticity is anchored, not self-derived:** the loader authenticates content only *relative to* a
  trusted external digest. The builder emits a write-once receipt last; `prepare-input` accepts the receipt plus
  its independently recorded SHA-256, derives `roster_file_sha256` from that verified receipt, and refuses a raw
  caller-supplied roster digest. The probe manifest binds the receipt SHA; `verify-input` separately requires the
  externally pinned probe-manifest SHA and replays the manifest → receipt → roster → H5AD chain. Internal
  self-checksums prove consistency, not authenticity. The CLI can verify a supplied pin but cannot prove where the
  caller obtained it, so pod admission MUST source receipt/manifest pins from the immutable command/evidence
  ledger and MUST NOT calculate them inline from the candidate files being consumed. Each successful maintained
  CLI command emits a canonical `compose_gears_probe_command_result_v1` line containing its primary artifact SHA
  and the executing runtime fingerprint at the publication boundary for direct capture by that ledger. Offline
  verification checks the producer fingerprint stored in both manifest and H5AD but does not require the verifier
  machine to equal the producer; its separate runtime fingerprint is emitted in the verifier command result. At
  config freeze, the
  selected roster/receipt identity becomes part of the new run identity. Re-deriving the entire variance fill at
  consumption remains optional defense-in-depth; it is not a substitute for the external trust anchor.
- **Fail-closed:** alias/lineage violations, `|M| > N_target`, response-HVG omission, and any GEARS consumption
  mismatch raise, never warn-and-proceed.

---

## 6. Alias artifact {#alias}

Hand-curated, committed (e.g. `configs/compose_gene_aliases_v1.json`), digest-pinned by `alias_sha256`. Schema:
`[{raw_symbol, canonical_symbol, source, version, reason}]`. Multiple registered legacy synonyms may legitimately
map to one canonical symbol, but the mapping must be one-to-one on the actual measured `var` and perturbation
candidate roster: two measured columns or two source candidates collapsing to one canonical target fail closed.
A canonical symbol must be a single measured column; unmapped symbols that then fail `var ∩ gene2go` are recorded as
eligibility exclusions (not silently dropped). Alias canonicalization occurs before the full fit-role/response
artifacts are frozen. Adding/changing an alias regenerates those full artifacts, the GEARS roster, and every
dependent digest — never a runtime rename. Initial content is the minimal known Norman set (`KIAA1804 →
MAP3K21`, plus any other symbol that canonicalization resolves); genuinely unmappable tokens (e.g. `IER5L`) get
**no** alias and surface as recorded exclusions.

---

## 7. Integration order and method boundary {#integration}

The required order is:

1. apply and bind canonical aliases to source metadata/gene IDs;
2. generate and validate the fit-role artifact over full measured `U_full` (existing contract unchanged);
3. fit and freeze the response artifact over `U_full` using registered non-sealed roles;
4. generate `R_gears` from that response artifact + global perturbation eligibility;
5. in the GEARS fit-input adapter, verify full fit-role/response/roster lineage, normalize allowed raw rows over
   `U_full`, then subset to `R_gears`;
6. run Probe A on the pinned GEARS environment. Only a preregistered scale/equivalence PASS may authorize a
   separate output bridge that directly consumes already-full-library-normalized `R_gears` log values; never
   normalize a reduced prediction by its own sum;
7. keep CPA and every in-process scientific model on their existing full-universe/response contracts.

`ordered_roster_sha256` is therefore a **GEARS method identity**, not `fit_role.gene_order_sha256`. The roster
artifact additionally records and verifies the full fit-role gene-order/content SHA and response artifact SHA.
Changing `R_gears` never rewrites the write-once fit-role or response artifact; it creates a new method/run identity.

---

## 8. Module & API surface {#api}

New module `src/alive/compose/gene_universe.py`. Public API (type-hinted, NumPy-style docstrings):

- `GeneUniverseError(Exception)` — fail-closed signal for all violations.
- `AliasMap` — loaded, digest-verified alias artifact; `AliasMap.load(path, *, expected_sha256) -> AliasMap`;
  `.canonicalize(symbol) -> str` (fail-closed on collision/empty).
- `MandatoryReport` (dataclass): `mandatory_size`, frozen `response_hvg_ids`,
  `eligible_perturbation_genes`, overlap/component counts, `eligibility_exclusions`, `n_candidates`, `n_eligible`,
  `n_excluded`, and the fit-role/response/eligibility/alias/GO digests.
- `compute_mandatory_report(*, full_var, fit_artifact_identity, response_projection,
  perturbation_candidates, gene2go, gene2go_sha256, alias, perturbation_candidate_source_sha256) ->
  MandatoryReport` — **report mode** (steps 1–3). It verifies response source/gene order, binds the pre-split
  candidate and GO-resource identities, and consumes frozen HVGs verbatim. No control-expression input,
  `N_target`, or sealed access is needed.
- `GearsGeneRosterArtifact` (dataclass) — the §4 object; `.write(path)` via `atomic_write_once`.
- `generate_gears_gene_roster(*, mandatory_report, control_counts_full, control_row_identity_sha256,
  generator_code_sha256, n_target, out_path) -> GearsGeneRosterArtifact` — **freeze mode** (steps 4–6); verifies
  full-row shape, uses the report's frozen median/lineage, and raises if `|M| > n_target`.
- `load_gears_gene_roster(path, *, expected_file_sha256) -> GearsGeneRosterArtifact` — mandatory external file
  digest (supplied from a trusted pin per §5, never recomputed from the candidate file), exact schema,
  self-checksum, size accounting, canonical subsequence order, normalization basis, and provenance validation. It
  recomputes `response_hvg_sha256` from `response_hvg_ids`; a newly hashed but semantically inconsistent artifact
  still fails closed.
- `assert_gears_roster_matches(var_names, artifact) -> None` — the §7/§3.7 fail-closed GEARS input/output check.
- `normalize_full_then_subset(counts_full, *, full_gene_order, response_projection, roster)` — sparse-safe
  fit-input transform. It accepts only raw non-negative integer counts over `U_full`, binds response/roster
  lineage, normalizes on the full row, then returns exactly `R_gears`.
- Maintained CLI identity chain — `build-roster` writes report + roster + receipt (receipt last); `prepare-input`
  requires the receipt and its trusted SHA rather than a naked roster SHA; `verify-input` requires the trusted
  probe-manifest SHA and the receipt, then verifies the complete chain offline.

Shared helpers reused (no drift): `response.rank_gene_indices_by_variance` owns the response-HVG/GEARS-fill
descending-variance + ascending-full-index ordering; `provenance.sha256_json` and
`fit_role.canonical_gene_order_sha256` own canonical identities. The sparse fit transform implements the same
registered normalize-total-median/log1p arithmetic without densifying the full fit matrix and is checked against
dense known answers. `generator_code_sha256` is not a single-file hash: it is the canonical digest of the exact
source-hash map for `gene_universe.py`, `response.py`, `fit_role.py`, `provenance.py`, and `io.py`, so changes to a
shared ranking, identity, checksum, or publication primitive mint a new generator identity. No hardcoded gene
lists, thresholds, or `N_target` exist in source (`CLAUDE.md`#repo).

---

## 9. Verification / test plan {#tests}

- **Known-answer:** a tiny synthetic full-`var` + control matrix + candidate list with a hand-computed `M`,
  fill order, and final roster → assert exact `ordered_roster`, `mandatory_size`, `fill_count`.
- **Frozen-response coverage:** every `response_projection.hvg_gene_ids` entry is present in `M` and
  `ordered_roster`; exact `response_artifact_sha256`/`response_hvg_sha256` are recorded. Missing/reordered HVG or
  response↔fit-role gene-order/source mismatch fails closed.
- **Self-consistent semantic forgery:** replace the response HVG list and roster, then recompute the roster hash,
  self-checksum, and external file SHA. Loading still fails because the embedded frozen-response HVG digest no
  longer matches; fit-input consumption separately requires exact equality with the response projection.
- **Pin-origin separation:** mutate a roster and recompute both roster and receipt self-checksums. Preparation with
  the previously anchored receipt SHA fails before reading the roster; offline verification similarly rejects a
  probe manifest whose candidate-file SHA was recomputed after mutation.
- **Scientific-target invariance:** generating different valid GEARS rosters leaves the full fit-role artifact,
  response artifact checksum, HVG IDs, PCA, and truth projection byte-identical.
- **Normalize-before-subset counterexample:** construct two cells whose `L_full/L_roster` ratios differ; assert
  that normalize-then-subset follows the registered reference and subset-then-normalize is rejected (no global
  target ratio can reconcile them).
- **Sizing guard:** freeze mode raises when `N_target < |M|`; response HVGs can never be traded away for fill.
- **Alias:** empty names, chains/cycles, measured-column collapse, and duplicate canonical candidates fail closed;
  multiple unused/alternative legacy synonyms for one canonical symbol remain valid. A mapped symbol is
  canonicalized on every relevant surface.
- **Eligibility:** a candidate with a gene outside `var ∩ gene2go` is excluded with the right reason and never
  appears in `eligible_perturbation_genes`; nothing is silently dropped.
- **Combo semantics:** `A_A`, `control_A`, and alias-induced canonical self-combos fail closed rather than being
  reinterpreted as a valid single-gene perturbation or ordinary eligibility exclusion.
- **`|M| > N_target`** raises `GeneUniverseError`.
- **Request-roster invariance (regression):** candidate ordering and any external requested-pair roster yield an
  identical report/`ordered_roster_sha256`; the generator API has no `payload["pair_ids"]` input. Checkpoint
  identity belongs to the later Probe-A-approved scientific adapter test, not this generator.
- **Outcome-independence:** the generator produces the identical roster with the sealed outcome store absent /
  unreadable (proves no sealed access path).
- **Determinism / write-once:** two runs on identical inputs are byte-identical; re-emitting over an existing
  artifact with different bytes fails (`atomic_write_once`).

---

## 10. Non-goals / out of scope {#non-goals}

- The **value** of `N_target`. This spec provides the mechanism, not the number. The intended flow: run **report
  mode** once to get `|M|` and the exclusion provenance; run **freeze mode** at candidate `N_target`s (each
  `≥ |M|`, e.g. a 2k-ish and a 5k-ish size) to emit contract-correct GEARS rosters; a *correct* Probe B benchmarks
  those rosters; the owner then freezes the final `N_target` into config (new run identity).
- Any change to the response operator's **scientific behavior** or its full measured input universe: its HVG
  selection + frozen PCA run upstream over `U_full`, unchanged. `response.py` receives exactly one
  behavior-preserving refactor — extraction of the shared `rank_gene_indices_by_variance` helper (§8) that
  `_select_hvg` delegates to — with byte-identical HVG output for real inputs; no numeric drift, no
  seal/checksum impact.
- The scientific Option-1 GEARS **output bridge** and negative-value policy. The locally implemented adapter is
  fit-input preprocessing only; output activation requires Probe A scale/equivalence evidence and a separate
  reviewed contract.
- The GEARS per-epoch eval-noop wall-time optimization (separate experiment; determinism-gated).
- Any change to the sealed-run seal/leakage machinery.
