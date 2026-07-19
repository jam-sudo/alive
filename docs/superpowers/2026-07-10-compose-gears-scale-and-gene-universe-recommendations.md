# COMPOSE dev-pod — GEARS native-scale & gene-universe recommendations (+ smoke-updated #1/#3/#5)

> **STATUS: PROPOSED — pending owner decision. NOT encoded into `configs/compose_k562_v1_phase2.yaml`
> or any manifest.** Builds on `2026-07-09-compose-dev-pod-decision-proposals.md` (#1–#5) with evidence from
> the 2026-07-10 dev-pod smoke (`2026-07-10-compose-phase1-dev-pod-findings.md`). Nothing here changes
> `config_sha256`; the two linchpins below are the owner's scientific-claim decisions that gate dev-pod
> Phase 2. No seal is opened by any of this. (Adversarially reviewed twice on 2026-07-10: the revised
> recommendation now distinguishes GEARS's public aggregate API from its internal per-control predictions,
> removes the claimed unavoidable Jensen gap, and closes the roster/alias/request-identity contracts. See
> the changelog at the end.)

---

## 0. New decision inputs from the 2026-07-10 dev-pod smoke — scope carefully

**What today's smoke was:** the reworked GEARS/CPA workers were run on **real backends** (cell-gears 0.1.2,
cpa-tools 0.8.5, A100) against a **shortened, gene-reduced Norman subset**, driving `_fit_and_predict`
directly. Both produced finite δ over the requested sealed pairs (rc=0, "SMOKE_OK").

**What it establishes — and what it does NOT.** It establishes only that the current code paths **execute**
on the real backends and that the three off-pod-unverifiable assumptions from the code review **hold as
runtime behavior** (CPA `predict` preserves the swapped obsm arrays; GEARS `train` mutates `self.model` to
the final epoch; CPA's DEG-mask control-row assumption). Per the findings doc's own discipline (§1.1: finite
smokes "say nothing about model quality, comparator strength, calibration, or generalization"), it is **NOT**
quality/adequacy validation and is **NOT** the §5 #6 release rerun (which requires a clean checkout of the
exact approved SHA, **unshortened** workers, the **full** registered gene universe, locked envs, and
immutable evidence). **§5 #6 still stands as an open blocker.** The findings doc predates today's run; treat
its "no real-pod rerun after the current fixes" as referring to that release rerun, which today's shortened
code-path smoke does not satisfy.

**Concrete inputs to the decisions below (pod-observed 2026-07-10, mark as such — not independently
re-verified from the MacBook):**
- **GEARS runs only on the committed era stack.** cell-gears 0.1.2 fits + predicts under numpy 1.26.4 /
  pandas 2.2.3 / scipy 1.11.4 — **exactly `requirements.gears_env.lock`**. A stale newest-stack env
  (numpy 2.4.4 / scipy 1.18) crashed GEARS at runtime (`'Series' object has no attribute 'nonzero'`). ⇒ the
  committed lock is correct; build gears_env FROM it. (The 2026-07-09 proposal's anchor table listing gears
  numpy 2.4.4 describes the broken env → superseded.)
- **GEARS perturbation composability** (not the predicted roster — see §2 CRITICAL fix) requires a
  perturbation's gene to be in **both** measured `var` and `gene2go` (the GO graph). Norman carries
  perturbation labels absent from `gene2go` (`IER5L`; `KIAA1804` = legacy symbol for `MAP3K21`) → GEARS
  drops them → the reworked worker fail-closes (`_require_fit_genes_in_gears_roster`, gears_worker.py:848).
  Pod-observed sizes: `gene2go` ≈ 67 832 keys, Norman `var` = 33 694.
- **GEARS is CPU-bound** on per-cell graph loading (GPU ~1 %). Full 33 k genes / ~9 k cells was
  time-infeasible; ~2 k genes / ~1 k cells ≈ 25 s/epoch (pod-observed). Raw-count train MSE is large,
  dominated by high-count genes — the scale distortion findings §2.1 predicts.
- **CPA 0.8.5 executed the full path** (`setup_anndata` on fit-only categories, DEG t-test, training to
  val-plateau, then the registered post-fit control query with perturbation-array override) with the reworked
  worker's registered defaults unmodified. Requested OOD pair categories did not enter `setup_anndata` or
  model fitting.

**Load-bearing source anchors:** `cell-gears==0.1.2` wheel `gears/gears.py::GEARS.predict` (per-control `p`,
first batch ≤300, public mean), `gears/pertdata.py::PertData.new_data_process` (no caller-data normalization),
and `PertData.set_pert_genes` (`gene2go`-filtered perturbation roster). The maintained worker explicitly uses
`default_pert_graph=False`, making that roster the exact method input roster intersected with pinned `gene2go`;
the upstream default's separate legacy essential-symbol list is not an additional silent eligibility gate. Local
`src/alive/compose/fit_role.py::apply_response_projection`,
`src/alive/compose/response.py::_select_hvg`, and the two real workers. The activation evidence must record the
wheel SHA-256 and source-symbol checks; line numbers in this note are explanatory, not identity anchors.

---

## 1. LINCHPIN — GEARS native input scale (findings §5 #1 / §2.1)

**The decision.** The merged GEARS worker feeds **raw counts** to GEARS and maps its raw pseudobulk output
through the config-locked `raw_pseudobulk_approximation` (the response operator then
`normalize_total_median`+`log1p`+PCA's it). This is a plumbing path, **not the published GEARS pipeline**
(published normalizes + `log1p` + HVG *before* `new_data_process`). The worker records
`ACTIVATION_BLOCKED_PENDING_PUBLISHED_SCALE_DECISION` and refuses to choose at runtime.

**Structural fact that shapes the decision (corrected after exact 0.1.2 source inspection):** the public
`GEARS.predict` API returns a mean profile, but the implementation first constructs one prediction row per
control input (`p`) and only then calls `np.mean(p, axis=0)`. In 0.1.2 it consumes the first DataLoader batch
(up to 300 controls), not an abstract population pseudobulk. Therefore GEARS does **not** intrinsically make
COMPOSE's per-row mean-of-projections impossible. The worker can use a version-pinned inference adapter to
apply the bridge and frozen response projection to each predicted row before averaging.

This distinction matters mathematically:

- on a common log-normalized scale, HVG selection + centering + frozen PCA is affine, so
  `mean(PCA(y_i)) == PCA(mean(y_i))`; there is no Jensen gap from PCA;
- raw-count averaging followed by `normalize_total` + `log1p`, or target-rescaling an already averaged log
  profile, is nonlinear and does create an approximation gap;
- applying target reconciliation **per predicted row before averaging** removes that avoidable bridge gap.

The remaining question is a comparator-policy choice, not an impossibility: preserve official 0.1.2's
deterministic first-≤300-control substrate, or deliberately iterate the full registered control roster. The
choice changes predictions and must be config-locked; it may not be selected after inspecting outcomes.

### Options
- **(1) Published-scale, adapted-roster GEARS + a per-control bridge into COMPOSE response space.** The worker,
  not `PertData.new_data_process`, must perform the exact registered normalize→`log1p`→gene-subset pipeline;
  `new_data_process` does not normalize an arbitrary caller-supplied AnnData. GEARS predicts one normalized-log
  row per registered control substrate. For each row `y_i`, the adapter:

  1. validates finiteness and applies the pre-registered negative-output policy below;
  2. reconciles GEARS target `T_gears` to COMPOSE `median_library = T_compose` **before aggregation** via
     `b_i = log1p(expm1(y_i) · T_compose / T_gears)`;
  3. places the predicted response-HVG values into a full canonical gene-order row (all non-HVG slots are
     exactly `0.0` and are ignored by the frozen projection; this filler rule is identity-bound);
  4. calls the existing `cell_log_normalized` response projection; and
  5. returns `δ = mean_i(PCA(b_i)) − control_mean`.

  No new prediction-representation enum is needed: `cell_log_normalized` already skips the raw transform
  because its input is at the frozen COMPOSE log-normalized target. A new **adapter version/SHA**, control-
  substrate policy, GEARS target, predicted-gene-roster SHA, and bridge-fidelity report SHA are nevertheless
  part of run identity.

  **Negative-output policy (mandatory before activation):** the GEARS decoder is not support-constrained, while
  `expm1(y)` and ALIVE's current `cell_log_normalized` contract require non-negative log-expression. The
  recommended adapter clips each predicted row at zero **before** target reconciliation, emits the count and
  fraction of negative entries, negative L1 mass / positive L1 mass, per-pair maximum negative magnitude, and
  a SHA-bound diagnostic report. Non-finite values always fail. The owner freezes a non-sealed diagnostic
  acceptance threshold before scientific activation; exceeding it is `INVALID`, never a silent clip-only pass.

  - **Load-bearing premise to POD-VERIFY *first* (this makes or breaks the bridge):** GEARS 0.1.2 must
    normalize each cell by its **full-gene** library size **before** HVG subsetting (same basis as COMPOSE's
    `_normalize_log1p_full`, fit_role.py:1060) **and** `GEARS.predict` must return **log-space** values. If
    GEARS instead normalizes on the reduced HVG matrix, the per-cell scale ratio is not a global constant and
    the reconciliation is ill-defined. Verify the **ordering + output space**, not just `T_gears`.
  - **Control-substrate policy to freeze:** primary recommendation is exact 0.1.2 compatibility — stable fit-
    artifact row order, first `min(300, n_control)` controls, no shuffle — because that preserves the public
    API's prediction substrate. A full-control variant is scientifically reasonable but is a distinct adapted
    comparator and requires a different method ID/run identity. Never benchmark both and choose by outcome.
- **(2) Named raw-count comparator + approximation-bias report.** Keep the merged raw-count worker, but
  **stop labeling it "published/default GEARS"** — register it as a distinct comparator (e.g.
  `gears_rawpseudobulk`) and run the pre-registered bias report (#4, already built at
  `scripts/compose/measure_pseudobulk_approximation_bias.py`) to quantify + disclose the distortion.

### Recommendation
**Primary: Option 1**, on §6 grounds (the comparator should retain GEARS's published normalization regime; a
raw-count variant is weakened/distorted, and beating it risks a strawman win) — **conditional on the premise
above verifying on the pod.** Because ALIVE requires a custom roster containing its response HVGs, the honest
name before an equivalence result is **"GEARS published-scale, COMPOSE-adapted roster"**, not unqualified
"published/default GEARS". If the normalization/output-space premise breaks the bridge, **fall back to
Option 2**.

**Symmetric honesty requirement (do not skip):** Option 1 requires three non-sealed checks:

1. **Inference equivalence:** before bridging, the mean of adapter-exposed per-control rows must equal public
   `GEARS.predict` for the same registered ≤300-control substrate, with identical gene order/shape and
   `rtol=1e-6, atol=1e-7` on the same checkpoint/device/runtime.
2. **Bridge fidelity:** per-row target reconciliation + projection must equal an independently implemented
   float64 direct reference, including negative handling and HVG remapping, at `rtol=1e-10, atol=1e-12`.
3. **Comparator adequacy:** on non-sealed roles, compare the adapted-roster model with the official Norman
   GEARS preprocessing/model on common genes and registered metrics. A projection-equivalence report alone
   cannot establish that a custom 2k/5k training roster preserves published comparator strength. The owner
   must freeze the common-gene metrics and non-inferiority margins before the adequacy run; without margins,
   the report is descriptive and the unqualified published-strength claim remains blocked.

Until all three pass, use the adapted label above. Option 2 analogously requires the existing approximation-
bias report and a distinct raw-comparator method ID. Neither option may be presented as faithful without its
applicable report.

**This is the owner's scientific-claim call** — I give the tradeoff (Option 1 = strongest + honest, worker
rework + premise risk; Option 2 = minimal work, honest only if renamed + bias-reported).

### Governance check
Representation stays config-locked (no runtime choice → new run identity). Option 1's bridge constants are
frozen from non-sealed data (no sealed outcome). Option 2 requires honest renaming + bias disclosure (§2
no-overclaim, §6 no-baseline-weakening). No seal implication.

### Residual / POD-VERIFY
Option 1: verify normalize-before-subset, log output, internal per-control tensor shape/order, and exact public-
mean equivalence against the installed 0.1.2 wheel FIRST. Then implement the per-control adapter via
`cell_log_normalized`; emit inference-equivalence, negative-output, bridge-fidelity, and comparator-adequacy
reports. Option 2: run the bias report on non-sealed roles; rename in config + spec.

---

## 2. LINCHPIN — gene universe (findings §5 #2)

**The decision.** Preregister the outcome-independent, digest-bound, **ordered** roster GEARS predicts on.
**Two distinct roles must not be conflated** (this was a real error in the first draft):

- **Predicted-gene roster** (what GEARS outputs expression for, and what the response PCA needs) — gated by
  measured **`var` only**. GEARS predicts every `var` gene regardless of GO annotation; a response HVG needs
  no GO term. It must therefore contain **all response-operator HVG genes** unconditionally.
- **Perturbation-gene eligibility** (which singles/combos are learnable) — gated by **`var ∩ gene2go`**,
  because that is the *sole* thing the worker fail-closes on (`_require_fit_genes_in_gears_roster` →
  `pert_names`/`pert_list`, gears_worker.py:848–887). A single/combo whose gene is outside `var ∩ gene2go`
  is **excluded from the eligible perturbation universe with a recorded reason** (e.g. `IER5L`,
  `KIAA1804`), never silently dropped.

### Recommended construction (every step outcome-free and request-roster invariant)

The generator has exactly these inputs: canonical full `var` order; response-artifact HVG IDs/SHA; normalized
CONTROL rows only; a pre-split, source-level perturbation-candidate artifact; a versioned alias artifact; and
the pinned `gene2go` artifact. It must not read sealed expression, combo effect sizes, role-specific outcomes,
or `payload["pair_ids"]`. Changing the requested sealed pair roster must not change the generated roster or
fitted checkpoint.

1. **Canonicalize identities before scientific artifacts are built.** Apply a versioned, provenance-bound
   alias map to perturbation tokens, `var`, `gene_order`, pair manifest, and `gene2go` lookup before creating
   the response or fit-role artifact. Each record stores `{raw_symbol, canonical_symbol, source, version}`.
   Mapping must be one-to-one on measured `var`; empty names, one-to-many mappings, or two measured columns
   collapsing to one canonical symbol fail closed. An alias change requires regenerating the response artifact,
   fit-role artifact, pair manifest, and every dependent digest — never runtime renaming. Example:
   `KIAA1804 → MAP3K21` is effective only if the post-canonicalization symbol is represented once in measured
   `var` and is a key in pinned `gene2go`; otherwise record an exclusion.
2. **Global perturbation eligibility** is computed from the pre-split source-level candidate artifact: a
   single/pair is eligible only when every canonical perturbation gene is in `var ∩ gene2go`. Record every
   exclusion and reason. This artifact is global and fixed before role assignment; the requested/sealed pair
   subset never enters it.
3. **Mandatory predicted set** `M` is the union of all response-HVG genes and every gene occurring in the
   global eligible perturbation artifact. GO membership is irrelevant for response-only HVGs.
4. **Freeze one target size `N_target` before fitting.** It is selected only from pod feasibility/resource
   evidence, not predictive outcomes. If `|M| > N_target`, generation fails and the owner must register a
   larger target/new run identity; never silently exceed the target or drop a mandatory gene.
5. **Deterministic fill:** normalize CONTROL cells at the frozen COMPOSE median library, `log1p`, rank all
   non-mandatory measured genes by descending control variance, break ties by ascending canonical full-`var`
   index, and take exactly `N_target - |M|`. This matches the response operator's actual control-variance HVG
   statistic; no perturbation response enters the ranking.
6. **Canonical final order:** select the mandatory+fill set, then emit genes in canonical full-`var` order.
   The roster therefore has exactly `N_target` unique entries. Emit alongside it the full gene-order SHA,
   response-HVG SHA, global eligibility SHA, alias SHA, `gene2go` SHA, generator-code SHA, control-row identity
   SHA, normalization constants, `N_target`, and ordered-roster SHA.
7. **Fail-closed consumption:** worker output must contain exactly this ordered roster before remapping. Any
   missing/extra/duplicate gene, order mismatch, or digest mismatch is `INVALID`.

The smoke's working filter (`var ∩ gene2go` for perturbation genes + a reduced predicted roster) is only the
**prototype**. The seven-step artifact above is the scientific contract.

### Governance check
Outcome-independent (control-only variance; no perturbation response; sealed expression never touched) and
request-roster invariant → §3.5 (no outcome-selected universe) + §6 (global eligibility fixed before the
split, missing/ambiguous genes recorded not silently skipped). Digest-bound + fail-closed identity/roster
mismatch → reproducible run identity. Add a regression test that changes only requested `pair_ids` and asserts
identical generated-roster SHA, training rows, model initialization, and checkpoint SHA.

### Residual / POD-VERIFY
- **Feasibility of ~5 k at FULL non-sealed cell count is NOT established** — the smoke measured ~2 k genes /
  ~1 k cells; GEARS is CPU-bound per-cell, and the real run has far more cells. Pod-measure the epoch time at
  the candidate gene count × full non-sealed cells before committing the size.
- Build the outcome-free generator + provenance block; confirm exact size/order, mandatory coverage, alias
  injectivity, and request-roster invariance. Freeze `N_target` only after the full-non-sealed-cell benchmark.

---

## 3. Smoke-updates to the 2026-07-09 proposals (#1 / #3 / #5)

- **#1 GEARS revision** — `cell-gears==0.1.2` **executed the full fit+predict path** on the era stack (not
  just import). **Env correction:** build gears_env from the committed lock (numpy 1.26.4 / pandas 2.2.3 /
  scipy 1.11.4); the newest-stack env crashes at runtime. Hyperparameters still POD-VERIFY against the
  installed 0.1.2 wheel for whichever scale option §1 selects.
- **#3 CPA** — `cpa-tools==0.8.5` **executed the full setup+DEG+train+obsm-swap-predict path** on real
  Norman; the reworked worker's registered 0.8.5 defaults ran unmodified → the "POD-VERIFY combo config"
  item is satisfied at the *code-contract* level. Release evidence (immutable input/log/checkpoint + artifact
  hashes) still pending — not a scientific pin change.
- **#5 provider** — the A100 80 GB / cu124 pattern worked again; owner picks the sealed-run provider.

(All three are **code-path execution** updates, per §0 — not quality/adequacy or release evidence.)

---

## 4. What stays owner-gated / release-gated after these decisions

Before implementation becomes a scientific activation candidate, the owner decision record must freeze:

- `scale_option`: Option 1 (recommended) or Option 2;
- exact method ID and honest display label;
- for Option 1, `T_gears`, `compat_first_300` versus `full_registered_controls`, adapter version/SHA, negative
  policy and acceptance threshold, equivalence tolerances, and adequacy metrics/non-inferiority margins;
- `N_target`, alias-artifact SHA, global-eligibility SHA, ordered predicted-roster SHA, and generator-code SHA;
- the fallback rule if any premise/equivalence/adequacy gate fails. Failure selects the predeclared fallback or
  leaves GEARS blocked; it never triggers outcome-guided retuning of the same run identity.

Settling §1 + §2 unblocks dev-pod Phase 2, but the full path to seal still requires (findings §5, unchanged):
config finalize (`power_status`, both `revision`/`environment_status`, chosen GEARS method ID/representation,
adapter/control-substrate policy, gene-roster artifact SHA, and the option-appropriate evidence SHA — Option 1
inference/negative/bridge/adequacy reports or Option 2 approximation-bias report) → **then** regenerate the two
activation-evidence reports under the finalized `config_sha256` → dep-lock COMPLETE (durable object storage +
content-addressed wheelhouse + container image digest) → the **§5 #6 unshortened real-pod rerun** on the full
registered gene universe → scientific PREPARE carrier (still `UnsupportedModeError`) → §2.5 release gate +
owner exact-Git-SHA approval → the separate sealed-run pod opens the COMPOSE seal exactly once. **No seal is
opened by settling §1/§2.**

---

## Changelog (adversarial review 2026-07-10)
- **Fixed (correctness):** §2 no longer gates the whole roster by `var ∩ gene2go`; predicted roster = `var`
  (contains all response HVGs), `gene2go` applies only to perturbation eligibility — the first draft would
  have produced an infeasible, self-contradictory roster if any response HVG lacked a GO term.
- **Fixed (honesty):** downgraded "END-TO-END VALIDATED" → "executed on real backends (shortened, reduced
  Norman) — code-path execution only," reconciled with the findings doc's §1.1 discipline; the §5 #6 release
  rerun explicitly still stands.
- **Added:** §1 bridge's normalize-before-HVG + log-output premise as the gating pod-verify; a symmetric
  Option-1 bridge-fidelity requirement; noted the existing `cell_log_normalized` representation lowers
  Option-1 cost; pinned §2 fill to one control-only rule; ~5 k feasibility marked pod-measure; alias applied
  across all gene-name surfaces; pod-observed numbers marked as such.
- **Second review correctness fix:** replaced the false claim that GEARS can only produce a pseudobulk and
  therefore every mapping has an unavoidable Jensen gap. Exact 0.1.2 source retains per-control predictions
  before the public mean; Option 1 now bridges/projects each row before averaging and freezes the ≤300-control
  compatibility substrate.
- **Second review contract closure:** added negative-output policy/diagnostics; separated inference equivalence,
  bridge fidelity, and comparator adequacy; downgraded the honest label to "published-scale, adapted-roster";
  made `N_target`, mandatory-union overflow, variance fill, tie/order rules, alias collision handling, full
  provenance, and request-roster invariance explicit; corrected the CPA post-fit query description and made
  the release evidence field option-specific.
