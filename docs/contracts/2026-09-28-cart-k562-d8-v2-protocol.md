# CART-K562-D8-v2 — direction and magnitude trust protocol (REGISTERED)

> **Status 2026-09-28: REGISTERED / E SEALED until freeze / single E opening.** Registered under
> owner-delegated decision authority ("결정권한 위임한다", 2026-09-28). Exact values:
> [`configs/cart_k562_d8_v2.yaml`](../../configs/cart_k562_d8_v2.yaml).
> [CART-K562-D8-v1](2026-09-27-cart-k562-d8-v1-protocol.md) closed at the development stage with E
> unopened; its development results are preserved. Governing contract:
> [scientific validity](2026-09-23-cartographer-scientific-validity.md). S5 (independent replication)
> and S6 are **not** satisfied by this protocol.

## Question

For three fixed predictors of day-8 K562 GWPS responses, frozen on non-GWPS data, does ALIVE's trust
estimate correctly state, and usefully select on, the probability that a **predicted non-negligible**
gene-level change is correct:
- **in sign**, and
- **in magnitude** (|h − d| ≤ ε)?

Each is evaluated separately. How large are observed changes relative to predicted ones?

## Design inherited unchanged from v1

The following are identical to v1:
- τ = ε = 0.2 and the log1p(CP10k over 8,248 genes) scale;
- eligibility, roster, and the **same PREPARE manifest** (D/C/E; seed 20260928);
- `C_ref`/`C_input`/`C_audit`, the unfiltered batch-matched comparator, features, the ALIVE-L
  specification and baselines;
- every acceptance threshold: calibration ±0.10 with 30-target bins; C budget 0.10; risk UCB ≤ 0.15;
  use LCB ≥ 0.30; α = 0.05 Bonferroni; 2,000 target-cluster bootstraps; comparator B1.

**Change and its disclosed source.** Joint → separate sign and magnitude events. This was informed by
D-role development (sign 0.923 vs 3-class 0.404 for P1) and is also foreseen by the owner-adopted use
contract (2026-09-24). v1's joint event is reported as a secondary result.

## Predictors (predictions frozen before registration)

| ID | Artifact | Output axis |
|---|---|---|
| P1 | State ST-HVG-Replogle `fewshot/k562/final.ckpt`, anchored adapter | 2,000 State HVGs |
| P2 | TG-K562-v1 base ridge, decoded | TG 2,000 genes |
| P3 | State ST-SE-Replogle `fewshot/k562/final.ckpt`; SE-600M `model.safetensors` (verified against training `X_state`, median cosine 0.983); anchored `gene_decoder` outputs; same control sets as P1 | 2,000 State HVGs (P1 axis) |

## Events and estimands (per predictor; predicted-non-negligible outputs |h| > τ)

- `Z_sign = 1[sign(d) = sign(h)]` (observed zero fails); `Z_mag = 1[|h − d| ≤ ε]`.
- ALIVE-L per event: fit on D, isotonic on C, operating point on C. v1 requirements 1–4 apply per
  predictor × event. A PASS needs all four.
- **Attenuation estimand:** E-role OLS slope of d on h, with a target-cluster bootstrap 95% CI.
  "Predictions overestimate magnitude" is claimed only if the CI lies entirely below 1.
- **Descriptive:** E sign and magnitude success rates with target-cluster CIs, and mean absolute
  error versus the no-change diagnostic.

## Verdicts and non-claims

Verdicts are `PASS` / `FAIL` / `NO_DISTINCT_WIN` / `INCONCLUSIVE` per predictor × event, never
pooled. The following are not claimed:
- gene-set or pathway certification;
- new-cell-line, causal or temporal claims;
- independent biological replication (S5);
- transfer of calibration beyond day-8 target-setting calibration.
