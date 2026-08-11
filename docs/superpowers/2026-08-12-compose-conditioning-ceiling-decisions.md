# COMPOSE-K562-v1 — conditioning-ceiling gate-decision record

> **STATUS: PROPOSED — pending owner sign-off (§6).** This record settles the disposition of the
> registered `identification.condition_ceiling` and its two application points, and it *presents but
> does not settle* the unbounded `‖z‖` scale gap. Each decision is `PROPOSED` until the owner flips
> it to `CONFIRMED` in §6; decision #4 carries **no proposal at all** and is listed as `OPEN` with
> its options costed, because choosing among them is a registered scientific criterion and not the
> drafter's to pick. **This record makes NO config edit.** `configs/compose_k562_v1_phase2.yaml` is
> untouched, every null/unestablished activation-blocker field is left as it stands, and the resolved
> `config_sha256` does not move. Every number below was recomputed in the drafting session against
> the committed artifact named beside it (§7); none is transcribed from a prior document.
>
> Drafted at `dbc360a04f1e4f5642113582056cb7fbaa19270f`. COMPOSE remains **RELEASE-BLOCKED** with the
> seal **UNOPENED**. Signing §6 authorizes no run.

## 0. Scope and cross-links

- **Settles:** the "OWNER-DECISION ARTIFACT MISSING" gap flagged in two independent review rounds —
  `docs/superpowers/COMPOSE-SEAL-READINESS.md` records the ceiling disposition as "resolved by owner
  decision" while no signed record exists, unlike every other registered choice in this protocol.
- **Presents, does not settle:** readiness item 4b (`⛔ OPEN`, the unbounded `‖z‖` scale gap).
- **Registered by:** `configs/compose_k562_v1_phase2.yaml` `identification.condition_ceiling`
  (`1.0e+8`) and the design spec `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md`
  ("Registered conditioning ceiling").
- **Enforced by:** `src/alive/compose/select.py` (both arms), `src/alive/compose/diagnostics2.py`
  (context line), `src/alive/compose/phi_rank.py` (the pre-approval activation check on the same
  statistic).
- **Feeds:** the sealed-run runbook release gate
  `docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md` §2.5. This record is upstream
  of that gate, not a substitute for it.
- **Governance:** prose only. This document opens no seal, reads no sealed outcome, constructs no
  `ComposeOutcomeStore`, and adds no code or test surface. See `CLAUDE.md#seal` and
  `CLAUDE.md#enforcement`.

---

## 1. Decision #1 — the ceiling VALUE and its anchor

**Decision.** Register an admissibility bound on `cond(Φ)` at `identification.condition_ceiling =
1.0e+8`, anchored **data-free** at `1/√ε_f64`, chosen without looking at any outcome.

**Cited evidence** — recomputed this session:

```
float64 eps        = 2.220446049250313e-16
1/sqrt(eps)        = 67108864.0            (~6.71e7)
registered ceiling = 100000000.0
ceiling / anchor   = 1.4901161193847656
```

The anchor is the point at which float64 loses half its significant digits. The registered value is
the next power of ten above it — a factor of **1.49**, not an order of magnitude. (The spec's phrase
"한 자릿수 올림" is correct as "rounded up to the next decade" but reads as "an order of magnitude";
the factor is stated here numerically so no reader has to infer it.)

**What the ceiling covers.** Scale imbalance between the expression block and the ESM block of `z`.
The relative scale of the two blocks is bounded nowhere upstream. Committed exhibit
(`tests/alive/compose/test_condition_ceiling.py::test_the_block_imbalance_exhibit_clears_the_ceiling_by_orders_of_magnitude`,
seed 6, `n_genes=20`, `k=4`, 37 pairs, last two columns = registered `esm_projection_dim: 2`),
recomputed this session:

| construction | `cond(Φ)` |
|---|---|
| baseline | `10.421787979549746` |
| **uniform** ×1e6 | `10.421787979549734` |
| **ESM block only** ×1e6 | `3713121910859.7812` |

The design is **full rank in all three cases** — this is not a rank test. The imbalance moves the
statistic **11.55 orders** and clears the registered ceiling by ~4.6. The uniform rescale moves it
by 1.2e-15 relative, i.e. round-off: the ceiling is a *detector of imbalance*, and deliberately not
a detector of magnitude.

Precision note: the imbalanced value is not reproducible to the last bit. `cond ≈ 3.7e12` destroys
~12.6 of float64's 15.65 significant decimal digits, so ~3 survive; the committed test pins it
loosely for exactly this reason, after a `rel=1e-12` pin went green on macOS/Accelerate and red on
Linux/OpenBLAS (relative difference 6.6e-05).

**Status:** `PROPOSED`.

---

## 2. Decision #2 — first application point: per-candidate screen, NOT a futility condition

**Decision.** A `k_total` whose full-calibration `Φ` exceeds the ceiling is recorded in
`nonviable_candidates` with its reason and dropped from the score map; **selection continues on the
remaining candidates.** Only if **every** candidate is inadmissible does selection itself fail, via
the already-registered `SelectionError` → **exit 10**, runbook category D ("investigate the cause; do
not simply re-run"). No new exception class and no new futility condition; the registered
`futility.conditions` vocabulary is unchanged.

**Cited evidence.** This shape was reached only on the third design, after three independent review
rounds rejected the first two:

1. futility on the **selected** `k_total` — rejected: it terminates the study permanently whenever
   the best-scoring dimension is over the ceiling, even when the same registered grid contains an
   admissible one;
2. the justification for futility did not survive checking — the runbook does not say exit 10 means
   "fix and retry" (category D says the opposite), the durable futility report does not persist the
   spectrum it was claimed to preserve, and the sibling threshold in the same config block
   (`uncovered_tolerance`) is a `SelectionError`, not a futility condition.

The same **ANY** rule is applied before an owner approves a SHA, by
`alive.compose.phi_rank.validate_phi_rank_activation_report` — a single over-ceiling `k_total` is a
dimension the run drops, and only a grid with no admissible dimension at all is uncertifiable. The
screen fires **only on finite** condition numbers; the non-finite case is rank deficiency (and, at
`k_total == 0`, a zero-width bank that reports full rank), which the registered
`unregularized_oof_rank_policy` owns. Screening it here would make that registered gate unreachable.

**Status:** `PROPOSED`.

---

## 3. Decision #3 — second application point: unregularized OOF train folds, at `lam == 0.0` only

**Decision.** Apply the same ceiling to each **unregularized OOF train fold**, restricted to
`lam == 0.0`, recording an over-ceiling fold under the same reason prefix. Rank is screened across
**all** folds before any fold is conditioned on, so an ordering accident cannot let a conditioning
failure in one fold mask a rank failure in another. The arm signals with `FoldConditioningError`, a
**subclass** of `SelectionError`, so an escape would still land on the registered pre-seal rejection
roster (exit 10) rather than becoming an uncontracted bug (exit 1).

**Cited evidence** — committed exhibit
`tests/alive/compose/test_condition_ceiling.py::_fold_local_degeneracy_instance` (defaults: seed 0,
`tiny=1e-6`, relative `noise=1e-2`, `degenerate_fold=0`), recomputed this session:

```
n_genes=18  k_total=4  n_pairs=153  n_folds=3  carriers=(2, 3, 6, 7, 11, 13)

FULL design   rank=10/10  cond=6.4732164341407          <- passes the ceiling
fold 0        rank=10/10  cond=3026665754681.6777       <- OVER, and FULL RANK
fold 1        rank=10/10  cond=5.172335080599498
fold 2        rank=10/10  cond=7.130033793795245
```

A gene-disjoint fold drops every pair touching its held-out genes, so a degeneracy confined to those
genes is invisible to a statistic computed over the whole calibration roster. Fold 0 sits **11.67
orders** below the full design while remaining full rank — the full-design statistic cannot see it.

**Why `lam == 0.0` only.** That is the sole point where `cond(Φ)` *is* the conditioning of the solve.
At `lam > 0` the ridge filter factors bound the effective conditioning, so rejecting on the
unregularized number would discard candidates whose actual solve is healthy. This is the same
boundary the registered `unregularized_oof_rank_policy` already uses.

The all-λ variant was measured and rejected. θ on **the same committed exhibit above**, across the
full registered `lambda_grid`, recomputed this session:

| `lam` | θ |
|---|---|
| `0.0` | `-6.724524089462035e+17` |
| `0.001` | `0.8103235465139835` |
| `0.01` | `0.8103476170258107` |
| `0.1` | `0.8102167052227403` |

The fold that sits at `cond 3.03e12` destroys θ at `lam = 0` and is **immaterial at every positive
registered λ**, where θ is flat to three digits. Gating positive λ on the unregularized condition
number would therefore discard candidates whose actual solve is healthy — which is why the arm is
restricted rather than applied across the grid.

**What this arm actually fixes — reason attribution, not a corrupted winner.** `cond(Φ)` bounds noise
**amplification**. On noisy data a degenerate fold inflates held-out error, lowers θ, and therefore
loses an argmax; the risk was never that a bad candidate wins, but that a *numerical* stop is filed
as `dev_oof_delta_below_threshold` — a claim about **biology**.

**That claim is conditional, and the condition is registered.** With zero noise there is nothing to
amplify, an ill-conditioned but consistent `lstsq` is exact, and the over-ceiling candidate wins.
Recomputed this session:

| exhibit | unscreened | screened | screen moves winner? |
|---|---|---|---|
| noiseless | `lam=0.0`, θ=`0.9999999993324848` | `lam=0.001`, θ=`0.8100934924563623` | **yes** |
| default (rel noise 1e-2) | `lam=0.001`, θ=`0.8103235465139835` | `lam=0.001`, θ=`0.8103235465139835` | no |

An earlier version of the record stated the "cannot change the winner" claim **unconditionally**,
and its own committed fixture was the counterexample. Two independent reviews found it. The scope is
recorded here rather than left to a reader's trust.

**Status:** `PROPOSED`.

---

## 4. Decision #4 — the unbounded `‖z‖` scale gap — **OPEN, no option proposed**

**This decision is not proposed.** It is presented with its options costed. Choosing among them sets
a registered numerical criterion, which per `CLAUDE.md#invariants` is the owner's, not the drafter's.

**The gap.** `cond(Φ)` is invariant to a uniform rescale of `z` (Decision #1 registers exactly that
property as what makes it an imbalance detector), while `identification.lambda_grid` is an
**absolute** penalty. `Φ` is bilinear in `z`, so `z → cz` gives `Φ → c²Φ`, and since
`solve_ridge_svd` applies the penalty to the raw `Φ`, the **effective** penalty is `λ/c⁴`. Nothing
bounds `‖z‖`: `factor_z` has no scale or normalization field (verified — the block registers
`total_k_grid`, `expression_dims`, `include_esm`, `esm_model`, `esm_projection_dim`,
`esm_projection_method`, `esm_projection_fit_roles`, `rank_gate`, `selection`, and nothing else),
`src/alive/compose/zfactor.py` performs no normalization, and no committed activation evidence
records a scale statistic.

**Measured, this session**, on the committed exhibit, factor bank scaled by `c` with the outcome
rescaled by `c²` alongside:

| | `c = 1` | `c = 100` |
|---|---|---|
| noise `= 0` | `0.8100934924563623` | `0.9577101250921993` |
| noise `= 0.01` (default) | `0.8103235465139835` | **`-3340344.02052717`** |

`cond(Φ)` is `6.4732164341407` at `c=1` and `6.473216434140699` at `c=100` — equal to 1.4e-16
relative, i.e. **identical to round-off but not bitwise**. Two supporting measurements, both taken
rather than assumed:

- **The outcome rescale is inert**, as it must be for a ratio: θ = `0.8103235465139835` against
  `0.8103235465139836` under an outcome ×1e4, an absolute difference of `1.11e-16`. (An earlier
  review round dismissed a reviewer's collapse figure on the grounds that rescaling `Z` without
  rescaling `eps` conflates representation mismatch with conditioning. **That reason was false** —
  θ is invariant to a uniform outcome rescale — and the dismissal was withdrawn.)
- **The `λ/c⁴` identity holds**: `c=100, λ=1e-3` gives `-3340344.02052717` against `c=1, λ=1e-11`
  giving `-3340344.020522601`, a relative difference of `1.3678437080108596e-12` (~11.9 digits).

**Precision of the collapse figure.** θ at this scale carries about **14 digits**, measured by
spreading it across mathematically inert outcome rescales: relative spread `1.03e-14` over factors
from 1e-3 to 1e4. The spec and readiness index both cite `-3340344.0205271696`, which is a
legitimate measurement — several inert variants land exactly on it — but it differs from the value
this session's construction produces by exactly **1 ulp**, and both citations carry 17 significant
digits where ~14 exist on one platform and, per the Accelerate-vs-OpenBLAS divergence recorded in
Decision #1, materially fewer across platforms. **Cite this collapse as `θ ≈ -3.34e6`.** The
magnitude is the finding; the trailing digits are not evidence.

**Consequence.** The registered conditioning ceiling cannot tell whether the registered
`lambda_grid` lands in a healthy window on the real Norman bank, so a **numerical** cause can flip
the **registered** futility condition `oof_theta <= dev_oof_threshold` — the exact misattribution
Decision #3 exists to prevent, one level up and not closed by it. For reference, the committed
synthetic bank spans per-gene `‖z‖` of `0.674095682511709` to `2.746297045563981`; the real Norman
bank's span is unmeasured, and that is the point.

**This is a PRE-EXISTING protocol gap.** The absolute grid and the unbounded `‖z‖` both predate the
fold-conditioning work, which discovered rather than introduced them.

### Options, none proposed

| | option | moves `config_sha256`? | cost | pod-gated? |
|---|---|---|---|---|
| **A** | Record a scale statistic (e.g. `sigma_max`) in the phi-rank activation evidence | **no** | see below | **yes** |
| **B** | Add a `factor_z` scale field or normalization | **yes → new run identity** | config + loader + spec + tests | no |
| **C** | Record explicit owner acceptance as a non-blocker | no | prose only | no |

**Correction to the cost of option A, which readiness item 4b currently understates.** `sigma_max`
*is* computed — `src/alive/compose/identify.py:70`, as `svals[0]` inside the registered
`max_shape_times_float64_eps_times_sigma_max` tolerance — but it is **not exposed and not emitted**:
`RankReport` carries only `sym_dim`, `rank`, `is_full_rank`, `condition_number`. Option A therefore
requires a `RankReport` field, emission in `compute_phi_rank_report`, and an addition to
`_FACTOR_BLOCK_KEYS` — which is an **exact** roster enforced by `_exact_object`, so the committed
`docs/activation-evidence/compose/real_norman_phi_rank_report.json` would fail validation the moment
the key is required. That means either a `compose_phi_rank_report_v1` → `v2` schema bump with the
validator accepting both (the pattern already used for the kernel archive), or regeneration of the
report — **which needs real Norman data on the pod**, the same reason task #14 is pod-gated.

Option A is genuinely digest-neutral. It is **not** "nearly free", and it is **not** checkable from
currently committed evidence. An earlier statement of mine to the contrary is withdrawn here.

**Status:** `OPEN` — owner must choose A, B, C, or something else. No option is recommended in this
document.

---

## 5. What this record does NOT settle

- It does not flip readiness to READY, and it does not advance the runbook past §2.5.
- It does not close **uniform-scale penalty immateriality**. Decision #1 registers the ceiling's
  invariance to uniform rescale as a *feature*; that same invariance is why the ceiling cannot close
  decision #4. Reading Decision #1 as a resolution of #4 is the specific misreading this section
  exists to prevent.
- It does not edit the config, regenerate evidence, or move any hash.
- It does not settle task #14 (regenerate config-bound evidence) or task #16 (independent archiver).

---

## 6. Owner sign-off

Each decision is `PROPOSED` until the owner initials and dates its line below, flipping it to
`CONFIRMED`. Confirmation records the scientific disposition; it does **not** by itself edit
`configs/compose_k562_v1_phase2.yaml`, flip readiness to READY, or approve an exact Git SHA — those
are separate, later steps under runbook §2.5.

| # | decision | current status | owner sign-off (flip to CONFIRMED — name / date) |
|---|---|---|---|
| 1 | Ceiling value `1.0e+8`, anchored data-free at `1/√ε_f64` | PROPOSED | ______________________ |
| 2 | First application point: per-candidate screen; all-inadmissible → `SelectionError` (exit 10) | PROPOSED | ______________________ |
| 3 | Second application point: unregularized OOF train folds, `lam == 0.0` only | PROPOSED | ______________________ |
| 4 | Unbounded `‖z‖` scale gap (task #43) | **OPEN — no proposal** | choose A / B / C: ____________ |

---

## 7. Reference-integrity verification (performed while drafting this record)

Every number above was produced in the drafting session from the committed artifact named beside it,
not transcribed from a prior document. This project adopted that rule after five violations on one
branch, and after a case where four figures were attributed to an artifact that does not produce
them.

- **§1 anchor** — `numpy.finfo(np.float64).eps` and `1/sqrt(eps)` evaluated directly; the registered
  ceiling read from `configs/compose_k562_v1_phase2.yaml` via
  `alive.compose.config2`, not from the YAML text.
- **§1 imbalance exhibit** — reconstructed from the committed test's own construction (seed 6, with
  the unused `coef_true` draw retained because it advances the RNG; dropping it changes the pair set
  from 37 to 39 and silently moves the exhibit to `9.91 → 4.15e12`). Recomputed
  `10.421787979549746` / `10.421787979549734` / `3713121910859.7812` at 37 pairs, `is_full_rank`
  True. **Noted, not acted on:** the committed test comment attributes `3713365971178.1865` to
  macOS/Accelerate and `3713121910859.7812` to Linux/OpenBLAS, but this macOS checkout produced the
  latter. The test does not pin this value tightly, so nothing is broken; the attribution is flagged
  for whoever next touches that comment.
- **§3 fold exhibit** — obtained by calling the committed
  `_fold_local_degeneracy_instance()` and `_fold_conditions()` helpers directly at their defaults,
  and `rank_diagnostics` on the full design. Carrier tuple, fold ranks, and all four condition
  numbers are as printed by that call.
- **§3 winner table** — obtained by calling the committed `_run()` harness at
  `condition_ceiling=1e300` (unscreened) and `1.0e8` (screened) on the noiseless and default
  exhibits.
- **§3 λ-grid table** — `_run()` on the same degenerate exhibit at each registered
  `lambda_grid` value in turn. A draft of this section instead carried `0.7867`/`0.7928` at
  `cond 2.9e12`/`2.9e4` forward from a 2026-08-07 working note; those came from an uncommitted
  scratch construction that no artifact in the repository reproduces, so they were **removed and
  re-measured on the committed exhibit** rather than restated. This is the same defect class as the
  four figures once attributed to a test file that runs a different `(n_genes, k)`.
- **§4 scale table, inertness, and `λ/c⁴` identity** — all four cells computed by rescaling the
  factor bank and outcomes of the committed exhibit and re-running `_run()` at `lambda_grid=(0.001,)`.
  The 1-ulp discrepancy against the recorded `-3340344.0205271696` was confirmed to be a genuine
  float difference (exact decimal expansions compared, gap = 1.0 ulp) and not a formatting artifact,
  then bounded by the ~14-digit stability measurement rather than reported as an error.
- **§4 option-A cost** — read directly from source: `RankReport` field list
  (`src/alive/compose/identify.py`), the `svals[0]` tolerance expression, `_FACTOR_BLOCK_KEYS` and
  its `_exact_object` enforcement, `PHI_RANK_ACTIVATION_SCHEMA = "compose_phi_rank_report_v1"` and
  its exact-equality check, and the existence of exactly one committed report
  (`docs/activation-evidence/compose/real_norman_phi_rank_report.json`).
- **§4 `factor_z` field list** — read from the committed config block, not recalled.
- **No file was modified while drafting.** `git status --porcelain` was run before drafting and again
  before committing; the only change in the working tree is this new document. **No edit was made to
  `configs/compose_k562_v1_phase2.yaml`** — verified directly, and the resolved `config_sha256`
  recomputed unchanged at
  `b158417a76e888bff2bf6836bea622e0cbf596f0743f3fe89aea2ffe0864a9fd`.
