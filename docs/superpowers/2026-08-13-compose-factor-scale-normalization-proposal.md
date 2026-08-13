# COMPOSE-K562-v1 — proposal for decision #4: fix the factor-bank scale so `lambda_grid` means something

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

**And the registered grid becomes an actual ladder** rather than three nearly-identical points:

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
| **Approve A** | normalize to `sigma_max(Phi) = 1`, pin the scalar in evidence | ______________________ |
| **Approve B** | same, but `‖Phi‖_F = 1` (SVD-free) | ______________________ |
| **Reject → A′** | leave the bank alone; register an admissibility band on `lambda/sigma_min²` instead | ______________________ |
| **Reject → C** | accept the gap; caveat any futility verdict as possibly scale-driven | ______________________ |

Approval authorizes an implementation wave only. It does not flip readiness to READY, approve a Git
SHA, or open the seal.
