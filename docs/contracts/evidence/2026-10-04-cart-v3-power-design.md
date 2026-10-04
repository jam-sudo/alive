# CART-K562-V3 — design candidates and selection criterion for the power table (fixed before running)

> **Status 2026-10-04: FIXED BEFORE the power script runs** (P1 precondition of the 2026-10-01
> three-way plan). This document does **not** change the registered V3 protocol
> ([preregistration](../../contracts/2026-09-29-cart-k562-v3-preregistration.md),
> [`configs/cart_k562_v3.yaml`](../../../configs/cart_k562_v3.yaml)). The power table is information
> for the owner's P3 decision; it selects nothing by itself. No new data exist and no outcome is read.
> The power run is executed **once** against this file's SHA256. Any rerun with a changed grid,
> criterion or interim value gets a new run id and is disclosed next to the first.

## 1. Inputs used (all outcome-free or already disclosed)

- **Support structure:** number of P1 predicted-non-negligible outputs (|h| > 0.2) per roster target,
  from `state-predict-01/full-01/predicted_change.npy` (SHA256 `12a3215b…2580`, predictions only).
  151/240 roster targets have ≥ 1 output; median 31 outputs (10–90%: 3–155). Larger N resamples these
  240 counts with replacement.
- **Rate scale:** mean sign success ≈ 0.91 and between-target SD ≈ 0.185 come from v2 results. The
  preregistration already used them; their use here is disclosed, not new.

## 2. Design candidates (24)

| Factor | Values | Registered |
|---|---|---|
| Targets N | 240, 480, 960 | 240 |
| Independent transductions T | 2, 3 | ≥ 2 |
| Role fractions D/C/E | 40/20/40, 30/30/40 | 40/20/40 |
| B0 operating policy (D1) | (a) registered C budget gate; (b) accept-all, C requirements 1–2 kept | (a) |

## 3. Scenario grid (parametric)

- True mean sign rate μ ∈ {0.83, 0.87, 0.89, 0.91, 0.93}. μ = 0.83 (failure 0.17 > 0.15) is the
  **known-bad** scenario.
- Between-target SD σ ∈ {0.185, 0.25}; per-target rates ~ Beta with that mean and SD.
- Cross-transduction dependence ρ ∈ {0, 1}:
  - ρ = 0 draws each target's rate independently per transduction;
  - ρ = 1 gives every transduction the same rate for that target.
  These bracket the dependence; neither is a universal bound (Astra R2: the general lower bound for
  "both pass" is max(0, 2p − 1)).
- Within a target and transduction, outputs are Bernoulli given the target rate.
- **Sensitivity only,** run at the registered design and at any design the criterion recommends:
  - transduction shift: the last transduction's mean is μ − 0.03;
  - eligibility dropout: a target misses a transduction with probability 0.10.
- 500 simulations per cell; proportions are reported with Wilson 95% intervals.

## 4. Interim values for unresolved blanks (not resolutions)

The power code needs a value for each blank. The values below are interim. Each one may change power,
and each is listed in the P3 blank table for an owner decision.

| Blank | Interim value used |
|---|---|
| Split strata | Stratified by the outcome-free P1-support indicator (≥ 1 non-negligible output) |
| B0 constant weighting | Target-equal D sign rate pooled over transductions (registered wording; the v2 code was row-weighted, F5) |
| C selection unit and α | Pooled over transductions, target cluster; Bonferroni over the C family |
| E family / "95% UCB" | α = 0.05 / Σ over transductions of (supported bins + risk + use [+ Brier if not constant]); every interval is Bonferroni-adjusted |
| Operating point | Exhaustive: the lowest threshold whose C target-weighted failure is ≤ budget (largest coverage); `inf` if none |
| Eligibility in one transduction only | The target is evaluated in that transduction only; roles are global |
| Predictions per transduction | One fixed prediction set, so the non-negligible set is shared |
| Verdict aggregation | Any transduction FAIL → FAIL; else any INCONCLUSIVE → INCONCLUSIVE; else PASS |
| No candidate selected on C | Terminal `NO_PRODUCT` (pre-E), counted as not PASS |

## 5. Candidate coverage

Only **B0** is simulated as a product. B1 and ALIVE-L need a generative model for their features that
no outcome-free source supplies. When B0 is rejected on C, the outcome is recorded as
`B0_REJECTED_ON_C`. In reality B1 or ALIVE-L could then be selected. Reported P(PASS) is therefore
P(PASS via B0), a **lower bound** on the total PASS probability.

## 6. Selection criterion (applied separately within each B0 policy)

A design is **adequate** if both hold:
1. P(PASS) ≥ 0.80 at μ = 0.91, σ = 0.185, for **both** ρ = 0 and ρ = 1;
2. P(PASS) ≤ 0.05 at μ = 0.83 for every σ and ρ.

Among adequate designs, the candidate is the one with the smallest N × T (a cell-cost proxy). Ties go
first to the registered role fractions, then to policy (a). A point estimate within 0.80 ± 1 MC
half-width is flagged `borderline`. If no design is adequate under a policy, that is reported as is.
The owner decides at P3 among go as registered, modified go, no-go, or hold. The table is not a
decision.

## 7. Not done here

- No empirical D/C resampling arm (needs owner approval).
- No B1/ALIVE-L simulation.
- No file-format reader and no change to registered thresholds.
- No claim about real V3 efficacy.
