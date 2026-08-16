# COMPOSE-K562-v1 — decision #5: activation's all-`k` rank contract vs the runtime rank check

> **STATUS: PROPOSED — owner approval required before any code change.** This document resolves
> task #48 and the ⚠️ OPEN item recorded in `COMPOSE-SEAL-READINESS.md` under
> **"2026-08-12 — independent read-only audit at `1d19729`"**. It **makes no code, config, test or
> evidence change** (it does apply two documentation corrections — §6, which are not owner
> decisions); `configs/compose_k562_v1_phase2.yaml` is untouched and the resolved
> `config_sha256` is unchanged at
> `3faacafff963b221148a08cb18fb92f084d796fb80c5db2b3b3b25ea295cb3b9`. Approving it authorizes an
> implementation wave; it does not authorize a run. COMPOSE remains **RELEASE-BLOCKED** with the
> seal **UNOPENED**.
>
> Every number in §3 was read or recomputed in this session from
> `docs/activation-evidence/compose/real_norman_phi_rank_report.json` (the committed real-Norman
> A100 report, `git_sha 82a9c83`, generated 2026-06-29) or derived from it by the arithmetic shown.
> §3.4 restates a bound first recorded in the readiness index on 2026-07-30 and re-derived here.

## 1. What is being decided

`validate_phi_rank_activation_report` (`src/alive/compose/phi_rank.py:244-282`) walks the registered
`total_k_grid` once. Inside that single loop it applies **two different quantifiers**:

| statistic | rule | code | effect of one bad `k` |
|---|---|---|---|
| `rank == sym_dim` | **ALL** | `phi_rank.py:248-264` — raises inside the loop | the **entire report** is refused |
| `condition_number <= ceiling` | **ANY** | `phi_rank.py:265-282` — collected, raised only if *every* `k` is over | that `k` is dropped, the study proceeds |

The ANY rule on the ceiling carries an eight-line comment (`phi_rank.py:265-271`) arguing that
refusing a whole report over one bad dimension "would block a run that would have succeeded — the
exact over-strictness this ceiling's own design was corrected for, one gate earlier". **The audit's
finding is that this argument applies verbatim to rank, and rank does not follow it.**

The decision: **should the rank check become ANY, or stay ALL?**

## 2. The audit's framing, and where it needs correcting

The audit recorded the item as reachable in principle:

> `rank ≤ min(n_pairs, sym_dim)`, so with fewer calibration pairs than `sym_dim(k=8) = 36` that block
> can never be full rank and the report becomes uncertifiable even though `k=4`/`k=6` are admissible.
> **The real pair count is pod-gated and unmeasured locally.**

The last sentence is **wrong**, and correcting it changes the decision. The real pair count is
neither pod-gated nor unmeasured: it is committed at
`docs/activation-evidence/compose/real_norman_phi_rank_report.json`, produced on an A100 against real
Norman data. It is **41**. The same file records the achieved ranks. The scenario the audit reasoned
about — activation refusing a report that runtime would have tolerated — **does not occur on this
design**, and §3 shows why.

*(The identical "unmeasured" phrasing appears in `2026-08-12-compose-conditioning-ceiling-decisions.md`
§7.1 and in the readiness index. Both are corrected as of 2026-08-16; see §6.)*

## 3. Measured facts

### 3.1 The gate is not binding on the real design

From the committed report, `report.per_k_total`, with the registered `total_k_grid: [4, 6, 8]`:

| `k_total` | `sym_dim` | `rank` | full rank? | `n_calibration_pairs_scored` | `n_pairs - sym_dim` | `condition_number` |
|---|---|---|---|---|---|---|
| 4 | 10 | 10 | ✅ | 41 | 31 | `15.8188` |
| 6 | 21 | 21 | ✅ | 41 | 20 | `32.8584` |
| 8 | 36 | 36 | ✅ | 41 | **5** | `484.1962` |

`n_combo_calibration = 41`, `n_eligible_pairs = 131`. **Every registered `k` is full rank**, so the
ALL rule and the ANY rule accept this report identically. Changing the quantifier changes nothing
about the run that is actually planned.

The rightmost margin column is a margin on the **necessary** condition only: `rank ≤ min(n_pairs,
sym_dim)` needs `n_pairs ≥ 36` for `k=8`, and 41 clears it by 5. Clearing it does not *imply* full
rank — but the report measured `rank = 36`, so sufficiency was observed, not assumed.

### 3.2 The pair count is deterministic, not a draw

`n_combo_calibration` is not a quantity that might come out differently next time.
`build_pair_split` (`src/alive/compose/split.py:185-210`) sorts the gene set by UTF-8 bytes, permutes
it with `Generator(PCG64(split_seed))`, takes the first `rint(0.6 · n_genes)` genes as calibration,
and assigns a pair to `combo_calibration` iff **both** its genes are calibration genes. With
`split_seed: 11` and `calibration_fraction: 0.6` registered, the only inputs that can move 41 are the
eligible-pair universe and those two fields — **and any change to either is itself a new run identity
requiring re-approval.** So "41 might be 35 on the pod" is not the right risk model: 41 is
reproducible, and the case where it is not is a case the owner has already had to approve.

Corroboration that the committed report and this code path agree: `rint(0.6 × 73) = 44`, and the
report independently records `n_z_universe_genes = 73` with `n_calibration_genes = 44`.

None of the config edits since this report was generated (`condition_ceiling`, `lambda_scaling`)
feeds `Φ`, the split, or the encoder, so the quantities in §3.1 are stable across the digest moves.
The report is nonetheless bound to the superseded `config_sha256 d8c65ac4…` and **must be regenerated
under task #14** — this document reads its measurements, it does not certify it.

### 3.3 The ceiling's ANY rule does not fire either

Registered `identification.condition_ceiling: 1.0e+8`; measured condition numbers are `15.8` / `32.9`
/ `484.2`. The real design is **five to seven orders below the ceiling** at every registered `k`. So
on this data neither quantifier is exercised. Both rules are, today, dormant.

### 3.4 The real mismatch is not ALL-vs-ANY — the two gates check different matrices

This is the finding that should drive the decision.

- **Activation** checks `rank(Φ) == sym_dim` on the **full 41-pair calibration design**, at every
  registered `k`, at **no** `lambda`.
- **Runtime** checks the registered `unregularized_oof_rank_policy:
  require_full_rank_each_train_fold` — on each of the **3 gene-disjoint OOF train folds**
  (`oof_folds: 3`), and **only at `lam == 0.0`**.

These are different matrices. Aligning the quantifier would not align the gates.

And on the real design the two are already expected to disagree — in the direction **opposite** to
the audit's scenario. With 3 gene-disjoint folds over the calibration genes, a pair internal to one
held-out group trains in 2 folds and a cross-group pair trains in 1, so

```
sum_f train_f = n_pairs + S,   S = # pairs internal to a single held-out group,   0 <= S <= n_pairs
```

With `n_pairs = 41`, `sum_f train_f <= 82`. Requiring all three folds to reach `sym_dim(k=8) = 36`
needs `sum_f train_f >= 108`. **`82 < 108`, so at least one fold has at most `floor(82/3) = 27` train
pairs and is rank-deficient by construction at `k=8`** — regardless of how the genes are grouped.

At `lam == 0.0` the two registered guards run as a **whole-candidate pre-pass**
(`_screen_unregularized_folds`, called from `_oof_theta_for_candidate` before any fold is fitted, so
that a rank failure in ANY fold outranks a conditioning failure in any other). One deficient fold is
therefore enough: the `k=8`, `lam=0.0` candidate is expected to be recorded **non-viable at runtime**
while activation certifies `k=8` as full rank.

(The bound cuts only at `k=8`. For `k=6` it requires `sum_f >= 63`, i.e. `S >= 22` — not excluded,
not established. For `k=4` it requires `sum_f >= 30`, and `sum_f = 41 + S >= 41` always, so the
counting bound raises no obstruction. Neither is a *guarantee*: the sum condition is necessary, not
sufficient — an adverse gene grouping could still starve a single fold. Both are layout-dependent
and pod-observable, and neither is decided here.)

This bound was first recorded in the readiness index on 2026-07-30 and is re-derived above rather
than cited. What is **new here** is its bearing on #48: the audit graded the mismatch as
"activation blocks what runtime tolerates". On the measured design it is **activation admits what
runtime drops**.

## 4. Options and costs

| | option | closes the audit item? | config digest | relaxes a gate? | cost |
|---|---|---|---|---|---|
| **A** | Make rank **ANY**, matching the ceiling | superficially | unchanged | **yes** | tests + mutation coverage; and it does **not** align activation with runtime (§3.4) |
| **B** | Keep **ALL**; record owner acceptance with the §3 measurement | yes, by decision | unchanged | no | one document, no code |
| **C** | **B**, plus split the rejection into named causes | yes | unchanged | no | small, strictly additive; needs tests |
| **D** | **C**, plus surface the §3.4 object mismatch as its own pre-seal item | yes, and one more | unchanged | no | readiness edit; no code |

Notes that matter for the costing:

- **A buys nothing measurable.** The gate is dormant on the real design (§3.1), the quantity that
  would wake it is deterministic and already approved-if-changed (§3.2), and the alignment it claims
  to achieve is not the alignment that is missing (§3.4). It also spends the one thing this project
  is most reluctant to spend: relaxing a registered fail-closed gate on a drafter's judgement.
- **ALL has a defensible meaning of its own.** Activation is a **readiness** artifact produced
  offline, before an owner approves a SHA and before a pod trip. "Every registered dimension must be
  structurally identifiable on the calibration design" is a coherent bar for a registered grid: if a
  registered `k` is non-identifiable, the honest response is to fix the registered grid — which is a
  config change with a new run identity and a visible record — not to silently run on a subset.
  Under ANY, a misspecified grid would pass activation and shrink at runtime with no pre-seal signal.
- **The existing ANY rule is silent, not merely permissive.** `over_ceiling` (`phi_rank.py:243`) is a
  function-local list, consulted only by the `len(over_ceiling) == len(expected_grid)` check and then
  discarded; `validate_phi_rank_activation_report` returns `pair_counts` alone. So a screened-out
  dimension leaves **no trace in the validator's output**. Copying that rule onto rank would copy the
  silence too — which is the opposite of what a pre-seal readiness artifact should do.
- **C addresses the part that would actually hurt.** The rank rejection at `phi_rank.py:248-264` is a
  **single message for an eleven-clause `or`** (`k_total`, `sym_dim`, `rank`, `is_full_rank`,
  `n_calibration_pairs_scored`, `n_calibration_pairs_skipped`, `n_genes`, and four condition-number
  type/finiteness/positivity clauses). If it ever fires on the pod, the operator is told
  `"phi-rank invalid or non-full-rank factor block for k_total=8"` and cannot tell a rank deficiency
  from a pair-count mismatch. Naming the cause relaxes nothing and is what makes the fail-closed
  direction survivable.
- **D applies the placement rule this project already adopted.** §3.4's consequence — a registered
  dimension that activation certifies and runtime is expected to drop — currently lives only inside a
  2026-07-30 correction narrative. That is the same placement error three review rounds judged wrong
  for the `‖z‖` gap in task #43, which was moved into the enumerated blocker list for exactly this
  reason: **a pod operator must see it.** It is not being escalated to a blocker here; it is being
  made visible.

## 5. Recommendation

**Option D — keep the ALL rule, record acceptance with the measurement, name the rejection causes,
and surface the object mismatch.**

The one-sentence justification: *the audit found a real inconsistency, but the measurement shows it
is dormant and the direction it was graded on is the wrong direction; the useful work is not to
relax the gate but to make its failure legible and to surface the mismatch that is actually live.*

Concretely, approving D authorizes:

1. **No change** to the ALL rule at `phi_rank.py:248-264` — recorded as an owner decision, with §3
   as its evidence.
2. Splitting that eleven-clause `or` into named per-cause rejections, each with its own message and
   test. Digest-neutral, relaxes nothing, fail-closed direction unchanged. Mutation-verified under
   the standing rules (a kill attested by a **named failing test**; the mutable file set must cover
   `phi_rank.py`).
3. A readiness entry recording (a) this decision, (b) the corrected reachability finding, and
   (c) the §3.4 activation↔runtime object mismatch, including that `k=8`'s `lam=0.0` candidate is
   expected non-viable at runtime.

(The §6 corrections are already applied and are not part of what approval authorizes.)

## 6. Corrections carried with this document — APPLIED, not pending approval

| location | as written | correction |
|---|---|---|
| `COMPOSE-SEAL-READINESS.md`, 2026-08-12 audit entry | "The real pair count is **pod-gated and unmeasured locally**." | ✅ applied 2026-08-16 — measured and committed: `n_combo_calibration = 41`, full rank at all three `k`; plus the §3.4 direction reversal |
| `2026-08-12-compose-conditioning-ceiling-decisions.md` §7.1 | "The real pair count is pod-gated and unmeasured here." | ✅ applied 2026-08-16 — same, in short form |

These are applied now rather than held for sign-off because they correct a **claim about what is
known**, which is not an owner decision: no registered value, outcome, threshold or hash is
refreshed, and leaving a known-false statement in the index while the proposal sits unsigned would
give a pod operator the wrong picture. Both original sentences are preserved in place, with the
correction appended below them, per the documentation rule.

The **decisions** in §8 remain unsigned and nothing in the code, config or evidence has changed.

## 7. What this does not decide, and what it does not authorize

- It does **not** decide whether `k=6` is fold-rank-viable on the real split — the counting bound
  leaves that open and it is pod-observable (§3.4).
- It does **not** change `unregularized_oof_rank_policy`, the fold builder, `oof_folds`, or the
  registered `total_k_grid`. If `k=8` proves non-viable at runtime, dropping it from the grid is a
  **config change with a new run identity**, and is not pre-authorized here.
- It does **not** re-certify `real_norman_phi_rank_report.json`. That report is bound to the
  superseded digest `d8c65ac4…` and is regenerated under **task #14** at
  `3faacaff…`; this document reads it.
- It authorizes **no run**. COMPOSE remains **RELEASE-BLOCKED**; the seal remains **UNOPENED**; the
  six registered config blockers and the `INCOMPLETE` dependency evidence are untouched.

## 8. Sign-off

| # | decision | proposed | owner | date |
|---|---|---|---|---|
| 5 | activation's rank rule stays **ALL** (not ANY), for the reasons in §4 | ✅ D | ☐ PROPOSED | — |
| 5a | name the eleven rejection causes at `phi_rank.py:248-264` | ✅ | ☐ PROPOSED | — |
| 5b | record the §3.4 activation↔runtime object mismatch in the readiness index | ✅ | ☐ PROPOSED | — |
| 5c | correct the two "pair count unmeasured" statements (§6) | ✅ | **APPLIED — not an owner decision** | 2026-08-16 |
