# CART-K562-D8-v1 — frozen-predictor trust protocol (REGISTERED)

> **Status 2026-09-27: REGISTERED / E SEALED / development roles open.** Owner approval “승인”
> (2026-09-27) covered registration with every proposed value, inclusion of the 246 TG
> sealed-evaluation targets as a disclosed stratum, and acquisition of the day-8 H5AD accessed
> only through `ReplogleOutcomeStore` with E sealed. Exact values:
> [`configs/cart_k562_d8_v1.yaml`](../../configs/cart_k562_d8_v1.yaml). Governing contract:
> [scientific validity](2026-09-23-cartographer-scientific-validity.md). Opening E requires the
> method, operating points and code SHA to be frozen and recorded first; E is opened once per
> protocol. A registered protocol is not scientific completion (Section 9).
## 1. Question and claim

For two fixed perturbation predictors, does a trust estimate ALIVE computes **without** seeing
the evaluated outcome correctly state the probability that a predicted gene-level expression
change is correct in direction class and magnitude? Is it useful, meaning it selects a
lower-risk subset at a useful rate?

Setting: day-8 K562 GWPS (Figshare 35775507), predictors frozen on non-GWPS data, trust layer
target-setting calibrated on day-8 development/calibration roles. The claim is conditional on this
experiment. It is not zero-shot calibration transfer, not a causal effect of time, not a
new-cell-line claim, and not gene-set or pathway certification (Section 9).

## 2. Frozen predictors (identity recorded before any outcome)

| ID | Artifact | Output | Exposure |
|---|---|---|---|
| **P1** | Arc State ST-HVG-Replogle `fewshot/k562/final.ckpt` (SHA256 `121ff54d…2618`), fixed adapter `scripts/cartographer/state_predict.py`. The adapter anchors on non-targeting, averages all 56 batch tokens uniformly, uses R=16 fixed `C_input` control sets (seed 20260925/20260927) and the scale log1p(CP10k over the 8,248-gene axis) | Mean change on 2,000 State HVGs | Trained on knockdown-filtered Replogle-Nadig without GWPS (evidenced, not proven); the 968 K562 few-shot test targets selected `best.ckpt`, but `final.ckpt` is used; 291 targets seen only in other cell lines |
| **P2** | TG-K562-v1 base ridge (bundle-01; `base.json` `dc526f52…`), decoded `h = s @ C` by `scripts/cartographer/tg_predict.py` | Mean change on the TG 2,000 selected genes (log1p CP10k) | Fit on 740 day-6 `base_train` targets; ESM features |

Prediction freeze: both prediction tables are generated before any perturbed outcome access, and
their hashes are recorded in the registration record. No predictor is retrained, re-selected or
re-tuned.

## 3. Query population, eligibility and strata

- **Unit:** query `q` = (predictor, day-8 target, output gene). The **claim unit** is the target
  (perturbation). Every output of one target shares that target's role.
- **Attempted roster:** every non-control day-8 target label with at least **30 assigned cells
  [REGISTERED]** according to label metadata (outcome-independent). Targets outside a predictor's
  support are recorded as unsupported attempts in operational accounting, not dropped.
- **Primary population per predictor:** supported targets that also carry day-6 labels, i.e. the
  same-target/new-experiment claim.
  - Secondary strata, reported and never pooled into the primary claim: P1 other-cell-line-only
    targets; P1 selection-exposed K562 targets; TG exposure groups.
  - The 246 TG sealed-evaluation targets are **included** in the primary population as a
    disclosed stratum (owner decision 2026-09-27). Their day-8 observations were never opened.
- **Output genes:**
  - each predictor's own 2,000-gene axis for its own claim;
  - a paired comparison on the common panel of **542** genes present on both axes.
- **Cell-count strata** (label metadata): <100, 100–259, ≥260 cells.

## 4. Observed comparator (adopted option A)

`d(q,u)` = mean over **all** cells assigned to the target (unfiltered, registered QC only) minus
the **batch-matched `C_ref`** reference, on each predictor's scale.

- **Batch matching:** `C_ref` cells are weighted so each gem group carries the target's cell
  share in that group. A group with no `C_ref` cells falls back to pooled `C_ref`, and the
  fallback is recorded.
- **Scales:** `C_ref` = 30,031 frozen control cells. P1 uses log1p(CP10k over 8,248 genes) on
  State HVGs. P2 uses log1p(CP10k over 8,248 genes) on TG genes. The day-6 denominator was 8,563
  genes; that residual is recorded and cancels to first order in differences.

## 5. Events

`C_τ(z)` ∈ {DOWN, NEGLIGIBLE, UP} with margin τ; `Z_dir = 1[C_τ(h) = C_τ(d)]`;
`E = |h − d|`; `Z_mag = 1[E ≤ ε]`; `Z_joint = Z_dir ∧ Z_mag`. The primary trust output is
`p_joint`.

- **τ = 0.2 [REGISTERED]** (natural-log units, ≈1.22-fold). It is resolvable from control noise
  across the eligible cell-count range: the null rate of |d| > 0.2 is ≤ 0.6% at 40 cells
  (`noise-audit01.json`). Interpretive rationale: roughly a 20% change in normalized expression
  is the smallest change the owner-adopted use would interpret.
- **ε = 0.2 [REGISTERED]**, the same resolution as τ, so a correct magnitude means the error is
  within the smallest interpretable change.
- **Sensitivity** at (τ, ε) ∈ {0.1, 0.3}² is reported as secondary and never used to choose the
  primary.

## 6. Trust estimators and baselines (same inputs, roles and budget)

Permitted inputs (no evaluated outcome):
- predicted |h| and predicted class;
- target cell count;
- per-gene control noise SD from `C_audit` at that cell count;
- per-gene control mean expression;
- predictor-internal spread (P1 per-token/per-set SD);
- exposure stratum.

| Method | Definition |
|---|---|
| **ALIVE-L** | Logistic model for `Z_joint` on the inputs above, fit on role D, calibrated by isotonic regression on role C |
| B0 constant | Role-D event rate |
| B1 noise-analytic | P(observed stays within the predicted class and within ε) under Gaussian control noise, assuming the prediction were exact; no outcome fitting |
| B2 random ranking | Seeded random scores for the risk–coverage comparison |
| B3 no-change predictor | Diagnostic: predicted h = 0 |

## 7. Roles, sealing and adequacy

- **Split:** target-level seeded split (seed **20260928 [REGISTERED]**), stratified by exposure
  stratum × cell-count stratum: **D 40% / C 20% / E 40% [REGISTERED]**.
- **Access:**
  - D and C outcomes are opened for development after registration.
  - E outcomes are sealed until the method, thresholds and code SHA are frozen; then evaluated
    **once**.
  - A failed E is final for v1.
- **Dependence:** CIs use target-cluster bootstrap with **Bonferroni** allocation of α = 0.05
  across every primitive interval in the family (supported bins, Brier, selected risk, use-rate,
  comparative; per predictor and stratum). Bonferroni replaces the earlier Holm proposal because
  bootstrap intervals give no p-values; it is valid under arbitrary dependence and conservative.
  - Culture/transduction independence is **unresolved** (author inquiry pending). Results are
    experiment-conditional; S5 independent replication remains open.
- **Synthetic power check (2026-09-27, idealized):** a correctly calibrated model passed ±0.10
  bin calibration in 6/8 replicates at 400 E targets and 8/8 at 800 and 1,200. The simulation
  used 40 independent outputs per target; real within-target output correlation lowers the
  effective N, so this is an upper bound.
- **Adequacy:** with about 800 P1 primary targets in E, a single binary-rate half-width is about
  0.03–0.035. Per-bin calibration half-widths at 10 bins are about 0.07–0.10. Bins with fewer than
  30 targets are **unsupported**, not passed.

## 8. Acceptance (per predictor; all must hold on role E) [REGISTERED]

The contract's design starting values (bin calibration ±0.05, selected risk 0.10 at use-rate
0.50) are **not resolvable** at the available N: expected per-bin half-widths are 0.07–0.10.
The thresholds below are relaxed on that precision ground alone, stated before any outcome and
adopted by the owner on 2026-09-27.

1. **Calibration:** in every supported probability bin (10 fixed bins), the simultaneous CI of
   (observed rate − mean `p_joint`) lies within ±0.10, and Brier(ALIVE) < Brier(B0) with the paired
   upper CI below 0.
2. **Selected risk:** at the operating point fixed on C (the largest coverage whose C-estimated
   risk ≤ 0.10), the E failure risk one-sided 95% UCB ≤ **0.15** and the use-rate one-sided 95% LCB
   ≥ **0.30**.
3. **Non-trivial classes (co-primary):** requirements 1–2 must **also** pass on the
   predicted-non-negligible outputs (UP or DOWN at τ). A per-predictor PASS requires both the
   all-output and the non-negligible results.
   Rationale (outcome-free, 2026-09-27): at τ = 0.2, 98.54% of P1 and 99.54% of P2 predicted
   outputs are NEGLIGIBLE, so all-output success is dominated by predicting no change. There are
   59,050 P1 non-negligible outputs over 1,204 targets and 18,215 P2 outputs over 1,494 targets.
   Operating point and bins for this stratum are fixed on C separately.
4. **Comparative value:** at matched coverage, ALIVE risk minus B1 risk has a paired upper CI
   < 0 (a distinct win). If not, the verdict is `NO_DISTINCT_WIN`, and the simplest adequate
   method (B1) may be adopted only if it alone meets requirements 1–2.

Weighting: every rate gives each target equal total weight, split equally across its outputs
in the reported stratum. Missing outputs stay in the denominators; available ones are not
renormalized. Counts of outputs are not biological N.

Verdicts: `PASS` / `FAIL` / `INCONCLUSIVE` per predictor and claim, with all strata and failures
reported. Global mean-panel RMSE and the no-change diagnostic are always reported, never
decisive.

## 9. Explicit non-claims and open items

- Gene-set summaries are **not covered by v1**. This is declared before outcomes: identifier and
  version qualification is incomplete, and the 504 MB Reactome mapping is unapproved.
- S5 independent replication and S6 completion are **not satisfied by v1** alone.
- Pairing P1/P2 on 542 common genes compares trust layers per predictor, not predictors.
