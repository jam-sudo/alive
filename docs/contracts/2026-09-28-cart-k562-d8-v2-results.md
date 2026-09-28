# CART-K562-D8-v2 — registered evaluation results (role E, single opening)

> **2026-09-28. Registered verdicts: FAIL for all 6 predictor × event cells.** E was opened
> once under run_id `CART-K562-D8-v2`: 911 supported E targets out of a 3,885-target E roster, seal
> audit count 1. Protocol: [CART-K562-D8-v2](2026-09-28-cart-k562-d8-v2-protocol.md). S4 has now
> been executed for this protocol. **S5 and S6 are not satisfied.**

## Provenance

- Freeze record `freeze-v2.json` SHA256 `deff83952d6ecce4537f2e4ab1a9ef2e0b5c6cee830057fc4c594aae99794908`
  pins 29 files (config, protocol, method, manifest, predictions, controls, code, sealing modules).
- A dry-run of the identical evaluation path with role C as sealed reproduced all six development
  acceptance results exactly before E was opened.
- Outputs (outside Git): `evaluation-E-v2/evaluation.json` SHA256
  `cec8b3475373bb632a04ba5aedb0536e58a587a8daecb6463804d38932d456aa`; `prepare/seal-audit.jsonl`
  SHA256 `fc8a71fb83bee4f03e66d079a8b99881c6071ab1ee0940fb41fa01d3d6211558`.
- v1 (joint event) closed at the development stage with E unopened; E was opened exactly once overall.

## Registered acceptance (predicted-non-negligible outputs, τ = ε = 0.2)

| Predictor / event | Verdict | Calibration (±0.10) | Brier < constant | Selected risk / use | Comparative vs B1 |
|---|---|---|---|---|---|
| P1 State HVG / sign | FAIL | fail: bin 8 gap +0.107 [0.011, 0.162] | fail (UCB +0.0012) | pass: accept all, risk UCB 0.113, use 1.0 | undefined at full coverage |
| P1 / magnitude | FAIL | fail: bins 3–4 gaps +0.08/+0.11 | pass | fail: use LCB 0.001 | pass |
| P2 TG ridge / sign | FAIL | fail: bin 2 gap +0.39 | pass | fail: use LCB 0.145 | pass |
| P2 / magnitude | FAIL | fail | pass | fail: no usable set | fail |
| P3 State SE / sign | FAIL | fail: bins 7–8 | pass | fail: use LCB 0.003 | pass |
| P3 / magnitude | FAIL | pass | pass | fail: no usable set | fail |

No predictor × event passes all four requirements. Where Brier improvement and comparative value
do pass, selection cannot hold failure risk ≤ 0.15 while keeping ≥ 30% use. Calibration fails mainly
through positive gaps (observed success above predicted) in middle bins. The trust layer is
conservative there, not overconfident.

## Confirmatory estimates (registered estimands; target-cluster bootstrap 95% CI)

| Predictor | Outputs (targets) | Sign success | Magnitude success | Attenuation slope d ~ h | MAE vs no-change |
|---|---|---|---|---|---|
| **P1** | 21,426 (403) | **0.908 [0.888, 0.924]** | 0.716 [0.690, 0.741] | **0.716 [0.666, 0.764]** | 0.147 vs 0.224 |
| P2 | 6,443 (603) | 0.718 [0.690, 0.745] | 0.478 [0.451, 0.507] | 0.682 [0.599, 0.761] | 0.186 vs 0.215 |
| P3 | 140,794 (658) | 0.583 [0.574, 0.592] | 0.258 [0.249, 0.268] | 0.116 [0.106, 0.127] | 0.276 vs **0.077** |

**Supported claims (within this experiment and scope):**
1. For Arc State ST-HVG `fewshot/k562` (`final.ckpt` with the registered adapter), about 91% of
   predicted non-negligible gene-level changes in K562 day-8 GWPS have the correct observed sign.
2. That predictor **overestimates magnitude**: the observed change is about 0.72× the predicted one,
   with a CI entirely below 1. The same holds for P2 and, more strongly, for P3.
3. The ST-SE variant with public SE-600M embeddings is worse than predicting no change in absolute
   error on these outputs.

**Not established:**
- query-specific calibrated trust for any predictor (every registered PASS failed);
- gene-set or pathway certification;
- independent biological replication, since culture-level units are unresolved;
- transfer beyond day-8 target-setting calibration;
- any causal, temporal or cross-cell-line claim.

## Status against the scientific-validity contract (S0–S6)

| Stage | Status after this evaluation |
|---|---|
| S1 event/use contract | Registered (v1 joint; v2 sign/magnitude) |
| S2 independent validation design | Registered roles, controls, noise audit and adequacy. Culture-level independence unresolved |
| S3 development | Done on D/C for three predictors |
| S4 independent acceptance | **Executed once: FAIL** (all cells) |
| S5 predictor linkage and independent replication | Three frozen predictors linked. **No independent cohort** (GEO sweep found none) |
| S6 scientific tool acceptance | **Not met** |

These negative verdicts are final for this protocol. Any new method must return to development on
new data, because day-8 E is now consumed.
