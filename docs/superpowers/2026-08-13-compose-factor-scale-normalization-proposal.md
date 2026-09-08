# COMPOSE-K562-v1 — proposal for decision #4: fix the factor-bank scale so `lambda_grid` means something

> **STATUS: APPROVED 2026-08-13 and IMPLEMENTED — see §8.** Approved in the equivalent
> penalty-side form: `identification.lambda_scaling: calibration_sigma_max_squared`, applied at
> both solve sites. §8.1 records two residuals that were NOT closed (`id_only` keeps an absolute
> lambda; whether the registered grid VALUES suit the real design's `cond`).
>
> **`config_sha256` HAS moved since this was drafted** — `b158417a…` → `3faacaff…` on this
> implementation, twice more in the 2026-08-20/21 ablation-ladder wave (`c25734d5…`, `5fea3b9e…`),
> and once more on 2026-08-29 for the pair-dependence decision — as of 2026-08-29 `0d207746…`;
> moved again 2026-09-07 (F-A3, `measurability_ceiling_floor`) → `a9dc9410…`.
> The unchanged-digest sentence in the original banner describes the document at drafting time.
> The banner as originally written follows.
>
> **STATUS: PROPOSED — owner approval required before any code or config change.** This document
> proposes one concrete resolution of task #43 / readiness item 4b / decision #4 of
> `2026-08-12-compose-conditioning-ceiling-decisions.md`. It **makes no config edit, no code change
> and no test change**; `configs/compose_k562_v1_phase2.yaml` is untouched and the resolved
> `config_sha256` is unchanged at `b158417a76e888bff2bf6836bea622e0cbf596f0743f3fe89aea2ffe0864a9fd`.
> Approving it authorizes an implementation wave; it does not authorize a run. COMPOSE remains
> **RELEASE-BLOCKED** with the seal **UNOPENED**.
>
> Every number below was produced in this session from the committed exhibit
> `tests/alive/compose/test_condition_ceiling.py::_fold_local_degeneracy_instance` at its registered
> defaults. Constructions are stated with values (§6).

## 1. The defect, stated as a ridge-usage error

Ridge regression is **not scale-invariant**, and this protocol penalizes an **unstandardized** design.
`Phi` is bilinear in `z`, so `z -> cz` gives `Phi -> c²Phi`, and because `solve_ridge_svd` applies the
penalty to the raw `Phi`, the effective penalty is `lambda/c⁴`. Nothing bounds `‖z‖`: `factor_z` has
no scale field, `zfactor.py` performs no normalization, and no activation evidence records a scale
statistic. "Unbounded `‖z‖`" is the *symptom*; the *cause* is that a penalty is applied to a design
whose scale is never fixed.

**The quantity that decides whether a registered `lambda` does anything** is `lambda/sigma_min²` — the
ridge filter factor on the weakest direction is `sigma_min²/(sigma_min²+lambda)`, where a factor of
`1.0` means the ridge did nothing. Measured on the committed exhibit:

| bank scale | design | `lam=0.001` | `lam=0.01` | `lam=0.1` |
|---|---|---|---|---|
| `c=1` | full design | `0.99980` | `0.99797` | `0.98011` |
| `c=100` | full design | `1.0000000000` | `1.0000000000` | `0.99999999980` |
| either | degenerate fold 0 | `0.000000` | `0.000000` | `0.000000` |

So at the exhibit's own scale the **entire registered grid is nearly inert** — the largest registered
`lambda` attenuates the weakest direction by 2% — and at `c=100` it is numerically indistinguishable
from `lambda = 0`. The same `lam=0.001` is simultaneously *inert* on the full design and *dominant*
on the degenerate fold. **One absolute `lambda` spans over twenty orders of materiality inside a
single run.**

## 2. The proposal

**Scale the factor bank by one scalar per `k_total`, computed on the registered calibration design,
so that `sigma_max(Phi) = 1`.**

- `Phi` is bilinear in `z`, so `Z -> Z/s` gives `Phi -> Phi/s²`; taking `s = sqrt(sigma_max(Phi_cal))`
  puts `sigma_max` at exactly 1.
- Computed from `Z` and the registered **calibration** pair roster only. It reads no outcome and no
  sealed role, so it is outcome-independent and role-legal (`CLAUDE.md#invariants` #4, #5).
- **One global scalar, deliberately not per-column standardization.** A uniform scalar leaves
  `cond(Phi)` and `rank` untouched (§3), so the registered `condition_ceiling` and
  `rank_tolerance_rule` keep their exact current meaning. Column-wise standardization would change
  `cond` and would silently redefine the registered ceiling — a much larger change than it looks.
- **The scalar is recorded in the phi-rank activation evidence and pinned**, so the run is auditable
  and a rerun uses the recorded value rather than recomputing it. This absorbs the previously-listed
  "option A" (record `sigma_max`) as the *mechanism* rather than as a standalone observation.

## 3. What it does to the registered gates — measured, not argued

| quantity | raw `c=1` | raw `c=100` | normalized `c=1` | normalized `c=100` |
|---|---|---|---|---|
| `sigma_max` | `14.3692` | `143692` | `1` | `1` |
| `sigma_min` | `2.21979` | `22197.9` | `0.154483` | `0.154483` |
| **`cond(Phi)`** | `6.47322` | `6.47322` | `6.47322` | `6.47322` |
| **`rank`** | `10/10` | `10/10` | `10/10` | `10/10` |
| `lambda/sigma_min²` at `lam=0.001` | `2.03e-04` | `2.03e-12` | `0.0419025` | `0.0419025` |

`cond` and `rank` are **unchanged in all four columns**, so the conditioning ceiling and the rank
policy are untouched. The fold-conditioning arm still fires: fold condition numbers are
`(3.02667e+12, 5.17234, 7.13003)` before and after normalization, and fold 0 is still the one over
the registered ceiling.

**The scale-dependent collapse disappears.** θ at `c=1` versus `c=100`:

| | `lam=0.001` | `lam=0.01` | `lam=0.1` |
|---|---|---|---|
| raw, `c=1` | `0.8103235465` | `0.8103476170` | `0.8102167052` |
| raw, `c=100` | `-3340344.021` | `-152289.5051` | `-2002.299511` |
| **normalized, both** | `0.8096626664` | `0.7737706445` | `0.5344315302` |
| normalized \|diff\| across `c` | `1.11e-16` | `1.11e-16` | `1.11e-16` |

`1.11e-16` is one ulp — the two scales now agree to round-off. (At `lam = 0.0` both remain
`-6.7245e+17`: there is no penalty to normalize, and that value is a garbage unregularized solve on a
`cond 3e12` fold, which is exactly what the fold arm exists to screen.)

**And on this exhibit the registered grid becomes an actual ladder** rather than three
nearly-identical points — but see §5.1 R2 before generalizing that sentence, because whether the grid
is a usable ladder after normalization depends on `cond`, which is a property of the real data:

| design | `lam=0.001` | `lam=0.01` | `lam=0.1` |
|---|---|---|---|
| full design | `0.959783` | `0.704709` | `0.192669` |
| fold 1 train | `0.944762` | `0.631045` | `0.146055` |
| fold 2 train | `0.930997` | `0.574327` | `0.118882` |

## 4. Choice of normalizer — four candidates, measured

All four are scale-invariant (verified `c=1` vs `c=100`). They differ in where the **registered**
grid lands, which is the whole point:

| normalizer | new quantity? | `f(0.001)` | `f(0.01)` | `f(0.1)` | verdict |
|---|---|---|---|---|---|
| **A. `sigma_max(Phi) = 1`** | **none — already computed AND already registered** | `0.9598` | `0.7047` | `0.1927` | **recommended** |
| B. `‖Phi‖_F = 1` | yes — a statistic nothing else in the protocol uses | `0.8549` | `0.3708` | `0.0556` | viable substitute |
| C. `max‖z‖ = 1` | yes | `0.9886` | `0.8965` | `0.4642` | weak — `lam=0.001` nearly inert |
| D. `RMS‖z‖ = 1` | yes | `0.9982` | `0.9819` | `0.8445` | **disqualified by measurement** — the registered grid stays nearly inert, i.e. it would not fix the defect |

**Correction to an earlier framing of this table.** A first version listed A's cost as "needs SVD"
and implied that counted against it. That is wrong on both halves. `rank_diagnostics` **already**
computes `np.linalg.svd(phi, compute_uv=False)` on exactly this design and already reads `svals[0]`
(`identify.py:69-70`), so A adds **zero computation**. And `sigma_max` is **already a registered
quantity** — the registered `rank_tolerance_rule` is literally
`max_shape_times_float64_eps_times_sigma_max`. A therefore introduces no new statistic into the
protocol; B, C and D each would.

**On numerical stability, stated accurately.** B avoids an iterative algorithm entirely. The concern
about A is *not* established: this project measured a `6.6e-05` Accelerate-vs-OpenBLAS divergence on
`cond`, but that quantity is dominated by `sigma_min`; `sigma_max` is the **best**-conditioned
singular value and is typically accurate to near machine precision, so the earlier measurement does
not imply `sigma_max` instability. There is also a consistency argument: the registered rank gate
**already** stakes a fail-closed decision on `sigma_max`, so if `sigma_max` were unstable enough to
matter here, that gate would already be unsound. Pinning the scalar in evidence (§2) removes the
residual question for reruns regardless. If the owner weights BLAS-independence above reusing an
already-registered quantity, **B is the substitute and nothing else in this proposal changes.**

## 5. What this does NOT do — non-claims

1. **It changes results.** θ moves from `0.8103235465` to `0.8096626664` at `lam=0.001` on this
   exhibit, and the registered grid's *meaning* changes, so no previously measured θ carries over.
   The seal is unopened and no scientific claim exists yet, so nothing is invalidated — but this is a
   real change to what the model does, not a refactor.
2. **It does not make the grid values correct**, only stable. Whether `[0.0, 0.001, 0.01, 0.1]` is
   the right ladder *after* normalization is a separate registered choice. Measured here it spans
   `0.96 -> 0.19`, which is a usable ladder on synthetic data.
3. **It is measured on one synthetic exhibit.** The real Norman bank's scale, and therefore where its
   grid lands today, is **unmeasured and pod-gated**.
4. **It does not close the noise-threshold scope issue** recorded in §3 of the decision record (the
   fold arm's "attribution only" claim holds above roughly `6e-12` relative noise, unregistered).
5. **It does not change the estimand, the model class, or any claim boundary** (`CLAUDE.md#mission`).
6. The normalizer depends on the registered calibration pair roster; if that roster changed, the
   scale changes with it. That is correct behaviour, and it is why the scalar is pinned in evidence.

## 5.1 Adversarial review of this proposal (2026-08-13)

The recommendation was reviewed by attacking it rather than restating it. Four findings; the
recommendation survives, with one claim narrowed, one new risk, and one result that makes the whole
decision cheaper than §2 assumed.

**R1 — after normalization the ridge's effect has an exact closed form, and it needs NO new
recorded quantity.** With `sigma_max = 1` we have `sigma_min = 1/cond`, so the filter factor on the
weakest direction is

```
f(lambda) = 1 / (1 + lambda * cond^2)
```

Verified against the measured SVD on four designs and three registered lambdas: `|diff| <= 4.4e-16`
throughout, and exactly `0` on the full design. **`cond` is already computed, already emitted per
`k_total`, and already validated in the phi-rank activation evidence.** So after normalization, grid
adequacy is checkable from the report that already exists. This **corrects §4 of the decision record**:
I wrote there that recording `sigma_max` is a prerequisite for an A′-style admissibility rule. With
normalization it is not — `lambda * cond^2` is computable from committed evidence with no new field.
(Without normalization `sigma_max` *is* still needed, because `sigma_min = sigma_max/cond`.)

**R2 — NARROWS a claim: normalization does not guarantee a usable ladder.** Evaluating the closed
form across `cond`:

| `cond` | `f(0.001)` | `f(0.01)` | `f(0.1)` |
|---|---|---|---|
| 3 | `0.99108` | `0.91743` | `0.52632` |
| 10 | `0.90909` | `0.50000` | `0.09091` |
| 31.6 | `0.50036` | `0.09103` | `0.00992` |
| 100 | `0.09091` | `0.00990` | `0.00100` |
| 1e3 | `0.00100` | `0.00010` | `0.00001` |
| 1e8 | `0.00000` | `0.00000` | `0.00000` |

The registered grid is a graded ladder for `cond` roughly in **10–30**, usable from about 3 to 100,
and **entirely dominant above ~100** — every positive registered lambda crushes the weakest
direction. **The registered `condition_ceiling` admits `cond` up to `1e8`**, so there are six orders
of admissible conditioning in which the grid, even after normalization, does nothing but
over-regularize. Normalization removes the *arbitrary* factor (bank scale); it does **not** make the
grid well-placed. Whether `[0.001, 0.01, 0.1]` suits the real design's `cond` is a **separate
registered question**, and it is now answerable from existing evidence via R1.

**R3 — STRENGTHENS the case: an absolute lambda already means different things across `k_total`.**
Measured on one bank at the registered grid `[4, 6, 8]`:

| `k_total` | `sym_dim` | `sigma_max` | `sigma_min` | `cond` |
|---|---|---|---|---|
| 4 | 10 | `14.9991` | `5.16511` | `2.90393` |
| 6 | 21 | `19.3836` | `3.03665` | `6.38321` |
| 8 | 36 | `24.0904` | `1.26798` | `18.999` |

`cond` rises 6.5x across the registered dimension grid, so by R1 a single absolute lambda is a
materially different relative penalty at each `k_total` — the choice of dimension is currently
**confounded with regularization strength**. Per-`k_total` normalization removes that confound. This
is an argument for the proposal that §2 did not make.

**R4 — NEW RISK: the comparator obeys a different scaling law from the operator.** `IDOnlyModel`'s
feature is `[z_g + z_h, |z_g - z_h|]` plus an intercept — **linear** in `z` — while the operator's
`pair_feature` is **bilinear**. Measured under `Z -> Z/s`:

| `s` | `‖id_only feature‖` | `‖bilinear feature‖` |
|---|---|---|
| 1 | `2.63419` | `1.01029` |
| 2 | `1.31709` | `0.252573` |
| 10 | `0.263419` | `0.0101029` |

i.e. `1/s` against `1/s²`. **One normalizer cannot put both arms of the primary metric on the same
footing**, and the primary metric `theta` is precisely a comparison between them. So normalizing
changes the relative regularization *inside the headline comparison*. The honest framing: that ratio
is **arbitrary today** — set by an unbounded bank scale nobody chose — and normalization makes it
**pinned but still not deliberately chosen**. That is an improvement, not a resolution, and it is a
modeling decision touching the primary metric rather than a neutral repair. It is legitimate to make
it **now**, pre-seal and outcome-blind; it would not be legitimate after any outcome is seen
(`CLAUDE.md#invariants` 1 and 5). *(The operator's own design has no intercept —
`operator.py:43` stacks `pair_feature` only — which is why `cond` and `rank` are exactly invariant
under a uniform scalar. The intercept exists only in the comparator.)*

**Net verdict.** The recommendation stands: normalizing removes an arbitrary, unchosen factor from a
penalty that feeds the registered stopping rule, and R3 shows it also removes a cross-dimension
confound. But it is **necessary, not sufficient** — R2 shows a second registered question (are the
grid values right for the real `cond`?) survives it, and R4 shows the operator/comparator balance
becomes pinned rather than correct. Both are now checkable from evidence that already exists.

## 6. Reference integrity

Every value above was produced this session by importing the committed helpers
(`_fold_local_degeneracy_instance` at defaults: seed 0, `tiny=1e-6`, relative `noise=1e-2`,
`degenerate_fold=0`; `n_genes=18`, `k_total=4`, `n_pairs=153`, `n_folds=3`) and the committed
`design_matrix` / `rank_diagnostics` / `_run`, then applying the candidate normalizer to `Z` before
the call. No committed file was modified; `git status --porcelain` showed only this new document.
Filter factors are `sigma_min²/(sigma_min²+lambda)` computed from the same SVD reported in the table
beside them.

## 7. Implementation cost, if approved

Rides along with the **mandatory** config finalization (`⚑ config 확정(null 채움 → 새 run identity)
후 evidence 재생성`), so the lineage cost is already being paid:

1. `configs/…yaml`: `factor_z.scale_normalization: calibration_sigma_max_unit` (+ spec paragraph).
2. `zfactor.py`: compute and apply the scalar; return it alongside the bank.
3. `phi_rank.py`: emit and validate it (schema bump, validator accepting the committed report).
4. `config2.py`: register and value-pin the new field.
5. Tests: scale-invariance property, `cond`/`rank` invariance, fold-arm still fires, mutation-verified.
6. Readiness 4b `⛔ OPEN -> CLOSED`; decision-record §4 status updated.

## 8. Owner decision

| | | |
|---|---|---|
| **Approve A** | normalize to `sigma_max(Phi) = 1`, pin the scalar in evidence | **APPROVED 2026-08-13 — implemented in the equivalent penalty-side form below** |
| **Approve B** | same, but `‖Phi‖_F = 1` (SVD-free) | not taken |
| **Reject → A′** | leave the bank alone; register an admissibility band on `lambda/sigma_min²` instead | not taken |
| **Reject → C** | accept the gap; caveat any futility verdict as possibly scale-driven | not taken |

### 8.1 What was implemented, and why the form differs from §2

Implementation showed that §2's form — normalizing the factor bank — would require
passing the calibration pair roster into `build_gene_factors`, making the **bank artifact depend on
the split** and conflating encoder lineage with split lineage; it would also require re-plumbing the
byte-for-byte binding in `_verify_factor_banks`. The owner was shown the fork and chose the
equivalent penalty-side form. Registered as:

```yaml
identification:
  lambda_scaling: calibration_sigma_max_squared
```

The applied penalty is `lambda * sigma_max(Phi_cal)²`. **Measured equivalent to §2's bank
normalization to within one ulp** (`|diff|` = 0, 0, 2.22e-16 at the three positive registered
lambdas), so the scientific decision is the one that was approved; only the site changed. `sigma_max`
is not a new registered quantity — it is the value `max_shape_times_float64_eps_times_sigma_max`
already uses, computed on the same design by `rank_diagnostics`.

Applied at **both** solve sites — OOF selection and the final fit — because if only one scaled, the
recorded `selected_lambda` would not be the penalty that was scored.

**`config_sha256` moved `b158417a…` → `3faacafff963b221148a08cb18fb92f084d796fb80c5db2b3b3b25ea295cb3b9`,
the new run identity this decision was approved to create.**

Verified: full compose suite **2058 passed, 2 skipped**; **13/13 mutations killed, each by a NAMED
failing test** (`scripts/compose_lambda_scaling_mutation_harness.py`); ruff check and format clean.

**Residuals, carried forward rather than closed:**

1. **`id_only` keeps an absolute lambda.** Its feature is linear in `z` while the operator's is
   bilinear, so this scale would not make it invariant, and changing a registered baseline's fit
   needs its own justification. (§5.1 R4's claim that this distorts the PRIMARY metric was **wrong**
   and is withdrawn: the OOF `theta` comparator is the parameter-free `additive` baseline, so
   selection's comparison is untouched. `id_only` is a member of the SEALED comparator family, which
   is where the residual lives.)
2. **Grid adequacy is still open** (§5.1 R2). By the closed form `f = 1/(1 + lambda·cond²)` the
   registered grid is a graded ladder only for `cond ≈ 10–30` while the ceiling admits `1e8`.
   Now answerable from the `cond` already in phi-rank evidence.
3. **Task #14 regains a mechanical trigger.** Activation evidence binds on `config_sha256`, which
   just moved, so the committed config-bound reports are stale again and must be regenerated on the
   pod at the new digest.

Approval authorizes an implementation wave only. It does not flip readiness to READY, approve a Git
SHA, or open the seal.
