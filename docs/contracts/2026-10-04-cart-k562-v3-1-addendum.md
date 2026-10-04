# CART-K562-V3.1 — prospective independent validation, revised design (REGISTERED, awaiting data)

> **Status 2026-10-04: REGISTERED before any new data exists.** The owner adopted the drafted
> revision on 2026-10-04 ("진행"). It is a new lineage: config
> [`configs/cart_k562_v3_1.yaml`](../../configs/cart_k562_v3_1.yaml), run id `CART-K562-V3.1`.
>
> It supersedes [CART-K562-V3](2026-09-29-cart-k562-v3-preregistration.md). V3 was never executed;
> no V3 data exist. The claim, the product rule and every acceptance threshold are inherited from V3
> unchanged, except where §2 says otherwise. Governing contract:
> [scientific validity](2026-09-23-cartographer-scientific-validity.md).
>
> **This document does not authorize data generation, cost or outcome access.** Those are separate
> owner actions. An external timestamp (push) must exist before any data-generation approval takes
> effect, and it does not retroactively certify V3's date.

## 1. Why the revision (outcome-free evidence)

- **The V3 design as registered had about a 10% chance of PASS.** The power table was run once
  against design candidates and a selection criterion fixed beforehand
  ([design](evidence/2026-10-04-cart-v3-power-design.md), SHA256 `712ea331…2a44`;
  [results](evidence/2026-10-04-cart-v3-power-results.md)). Code: `v3_protocol.py` (`d909970`).
  - It reports P(PASS via B0) at a true sign rate of 0.91: **0.096–0.098** for V3 as registered.
  - At the known-bad rate 0.83, P(PASS) was **0.000** in every design.
- **Confirmation on the actual V3.1 roster.** This run was also defined before running
  ([definition](evidence/2026-10-04-cart-v3-1-power-confirm-definition.md), `cc083b7f…64dc`).
  - P(PASS) is **0.902** (independent transductions) and **0.828** [0.792, 0.859] (identical target
    rates across transductions).
  - The adequacy criterion (≥ 0.80) is met, but only **borderline**.
- **P(PASS) is a lower bound,** because B1/ALIVE-L were not simulated.

## 2. Changes from V3 (each disclosed)

| Element | V3 | V3.1 | Reason |
|---|---|---|---|
| Targets | 240 (`28d57589…`) | **960**, nested superset (`510ab8a8…`, seed 20261004) | Power |
| D/C/E | 40/20/40 | **30/30/40** (seed 20260930, stratified by P1-support indicator) | About 30 supported C targets sat at the 30-target bin floor |
| B0 operating point | C budget gate | **Accept-all**. B0 still needs requirements 1–2 on C and the E risk UCB ≤ 0.15 | **Rule change made after seeing v2.** True failure ≈ 0.09 against budget 0.10 made the gate close to a coin flip |
| Transductions | ≥ 2 | 2 | A third lowers P(PASS): every unit must pass, and Bonferroni grows |

Notes on the roster and thresholds:
- The extension samples uniformly from the remaining pool targets with ≥ 2 GWPS guides. A first draw
  that included guide-less targets was superseded before any use.
- Generator: `scripts/cartographer/v3_roster.py`. It also reproduces the V3 roster byte-for-byte.
- Thresholds are **unchanged**: ±0.10 calibration with 30-target bins; risk UCB 0.15; use LCB 0.30;
  α 0.05; 2,000 target-cluster bootstraps.

## 3. Rules V3 left open (now registered)

| Rule | Registered value |
|---|---|
| B0 constant | Target-equal D sign rate, pooled over transductions |
| C selection | Pooled over transductions, target cluster; Bonferroni over the candidate's intervals |
| E multiplicity | α / Σ over transductions of (supported bins + risk + use [+ Brier]). Every interval is adjusted, including the "95% UCB" |
| Operating point | Exhaustive largest-coverage search, as [D8 erratum](2026-10-04-cart-k562-d8-v2-erratum.md) recommends |
| Target eligible in one transduction only | Evaluated in that transduction only; roles are global |
| Predictions | One shared P1 prediction set, with `C_input` pooled equally over transductions |
| Verdicts | Per transduction. Any FAIL → FAIL; else any INCONCLUSIVE → INCONCLUSIVE; else PASS |
| No candidate on C | Terminal `NO_PRODUCT`. E is still opened once for the registered descriptive estimands |
| ALIVE-L features | The v1 list. `n_cells`, `control_noise_sd` and `control_mean` come from the new experiment, per transduction |
| Single-guide target | NOL12 (inherited from V3) stays in and is flagged |

These rules are executable in `alive.experiment.v3_protocol`. It refuses to run without them, and
`configs/cart_k562_v3_1.yaml` supplies them.

## 4. Intake (to agree with the lab before any experiment)

`alive.experiment.v3_manifest.validate_intake_manifest` must accept the lab manifest before data
intake. The manifest must contain:
- protocol id; roster SHA256; K562 with an authentication id;
- per transduction: `transduction_id`, `culture_id`, `transduction_date`, `virus_lot`;
- per library: `library_id`, `transduction_id`, `lane_id`;
- a guide → target table that matches the roster, plus non-targeting guides.

The validator rejects a shared culture, a reused 10x lane, fewer than 2 transductions, and guide
mismatches.

**Scale:** at least 150 cells per target per transduction (about 288,000 targeted cells over two
transductions), and at least 5,000 non-targeting cells per transduction. The wet-lab sheet
(`v3-design-01/wetlab-sheet-v3-1-draft.csv`, `fe1aeba0…`) lists the GWPS guide ids. **Guide
sequences still have to be resolved** before ordering.

## 5. Accepted limits

- **Adequacy is borderline** (0.828 under identical cross-transduction rates).
- **A 0.03 mean shift in one transduction** drops P(PASS) to about 0.32–0.36.
- **A between-target SD of 0.25** drops it to 0.57–0.63.
- **The power model is parametric** (Beta rates, Bernoulli outputs).

Under any of these, FAIL or INCONCLUSIVE is an honest outcome and is reported as-is.

## Non-claims

Unchanged from V3:
- query-specific trust, unless ALIVE-L is selected and passes;
- magnitude reliability;
- gene sets, other cell lines, causal or temporal claims, other predictors.
