# CART-K562-V3 — prospective independent validation (PRE-REGISTERED, awaiting data)

> **2026-10-04: SUPERSEDED before any data by [CART-K562-V3.1](2026-10-04-cart-k562-v3-1-addendum.md).**
> The power analysis gave this design about a 10% chance of PASS, so it is not executed. The
> registered text below is unchanged.

> **Status 2026-09-29: PRE-REGISTERED before any new data exists.** The owner adopted option (a) on
> 2026-09-29 (“진행”): a **predictor-level, direction-only, gene-level** reliability card is the minimum
> S6 product. Query-specific trust, magnitude reliability and gene-set claims remain future work.
> Exact values: [`configs/cart_k562_v3.yaml`](../../configs/cart_k562_v3.yaml). Evidence basis:
> [v2 results](2026-09-28-cart-k562-d8-v2-results.md). Governing contract:
> [scientific validity](2026-09-23-cartographer-scientific-validity.md). This document does not
> authorize data generation, cost or outcome access; those are separate owner actions.

## Claim to be tested

For the fixed predictor **P1** (Arc State ST-HVG-Replogle `fewshot/k562/final.ckpt`, SHA256
`121ff54d…2618`, with the unchanged anchored adapter `scripts/cartographer/state_predict.py`), a single
**predictor-level probability that the observed sign of a predicted non-negligible gene-level change
(|h| > 0.2) matches the prediction** is calibrated and useful. It must hold **in each of at least two
independent transductions** of a new K562 CRISPRi Perturb-seq experiment.

Magnitude is reported as a **warning estimand** (magnitude success and the attenuation slope), not as a
product.

## Pre-registered product rule

Candidates for the sign event, in order of simplicity:
1. **B0**, a constant equal to the D-role sign rate;
2. **B1**, noise-analytic Φ(|h|/σ);
3. **ALIVE-L**, logistic on D with isotonic on C.

The product is the first candidate meeting requirements 1–2 on role C of the new data. ALIVE-L may be
selected only if it also has a distinct win over B1 (requirement 4). The selection is recorded and
frozen before E.

## Acceptance on role E (per independent transduction, separately; Bonferroni across transductions)

1. **Calibration:** every supported probability bin (≥ 30 targets) has a target-cluster bootstrap CI of
   (observed − predicted) within ±0.10. For B0 this is a single bin. For B1/ALIVE-L, Brier must also
   beat the constant.
2. **Practicality:** at the C-fixed operating point (budget 0.10), the selected-risk one-sided 95% UCB
   is ≤ 0.15 and the use-rate LCB is ≥ 0.30.

**PASS** means both requirements hold in every independent transduction. The pooled analysis, with
transduction as the cluster, is reported. Otherwise the verdict is FAIL or INCONCLUSIVE (unsupported
bins), reported as-is.

## Design (fixed)

| Element | Registered value |
|---|---|
| Targets | **240**, uniform random (seed 20260929) from 1,731 P1-supported, day-6-labelled targets; `v3-design-01/target-roster.json` SHA256 `28d57589f2722e6b4e8a1124eab45a433f2cd32fb8a7e13042744f08a35825bd`; GWPS library guides, 2 per target. **N fixed; no adaptive change after pilot** |
| Replication | ≥ 2 independent lentiviral transductions in separate cultures, separate 10x lanes. The transduction is the independent unit |
| Depth / eligibility | Aim ≥ 150 cells per target per transduction. Eligibility is ≥ 30 cells per target per transduction (label metadata only). Controls: ≥ 5,000 non-targeting cells per transduction |
| Roles | Targets split D/C/E 40/20/40 (seed 20260930) by metadata. Controls split within each transduction and gem group 40/40/20 into `C_ref`/`C_input`/`C_audit` (seed 20260925 rule) |
| Scale | log1p(CP10k over all genes of the Cell Ranger filtered matrix) on P1 HVGs by gene name. The day-8 8,248-gene-axis variant is a sensitivity analysis |
| Events | τ = ε = 0.2; sign event on predicted-non-negligible outputs; magnitude warning estimand |
| Comparator | Unfiltered, batch-matched `C_ref` (option A) |
| Inference | Target-cluster bootstrap with 2,000 draws; α = 0.05 Bonferroni over the family × transductions |

**Adequacy.** E ≈ 96 targets, of which about 58 have non-negligible P1 predictions. The v2 variance
(target SD ≈ 0.185) gives a sign-rate lower bound ≥ 0.85 at a true rate ≈ 0.91 with about 50 such
targets. The design has little margin; a true rate below about 0.89 would likely give FAIL or
INCONCLUSIVE, and that is accepted as an honest outcome.

## Non-claims

- Query-specific trust, unless ALIVE-L is selected and passes.
- Magnitude reliability: expected to fail; v2 accept-all risk was 0.284.
- Gene sets, other cell lines, causal or temporal claims, other predictors.

## Reviews

- **Review 1 (goal):** implements the owner-adopted minimum S6 scope and directly tests S5
  (independent biological replication). Registering before data prevents post-hoc narrowing.
- **Review 2 (validity):** the product rule is informed by v2 and disclosed. Thresholds are inherited
  from v1/v2. Targets and roles are outcome-independent. N is fixed without adaptive stopping.
  Replication is required per independent transduction, not only pooled.
