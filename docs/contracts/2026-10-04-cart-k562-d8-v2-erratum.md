# CART-K562-D8-v2 — implementation-deviation erratum (2026-10-04)

> **Additive erratum. The registered verdicts (FAIL for all six cells) and the
> [results](2026-09-28-cart-k562-d8-v2-results.md) text are unchanged and are not relabelled.**
> Owner-approved scope (P2/D3, 2026-10-04): role C only. Role E was not read. There was no refit
> and no upstream rerun. Provenance of the as-run code:
> [audit](evidence/2026-10-04-cart-k562-d8-v2-provenance-audit.md).

## Deviation 1 — operating-point search (measured: no effect on D8-v2)

- **Registered definition** ([v1 protocol §8](2026-09-27-cart-k562-d8-v1-protocol.md), line 130):
  the operating point is the largest coverage whose C-estimated risk is ≤ 0.10.
- **As-run code** (`day8_protocol.operating_point`): scans thresholds from the top and **stops at
  the first one that exceeds the budget**. If the risk curve is non-monotone, that can miss a lower
  qualifying threshold. Counterexample: p = (.99, .95, .90), z = (0, 1, 1), budget .4. The code
  returns `inf`; the registered definition gives 0.90.
- **Check:** a definition was fixed before running (SHA256 `67398e76…cd5c`). The check used
  `scripts/cartographer/d8_v2_opcheck.py`. For each predictor × event it
  1. recomputed the as-run threshold from the frozen ALIVE-L parameters on role C — reproduced in
     6/6 cells;
  2. computed the registered threshold with an exhaustive search
     (`alive.experiment.v3_protocol.operating_point`).
- **Output:** outside Git.
  - First run: `run/opcheck.json` `da7b9663…3f35`, script SHA256 `1e149d17…c084`.
  - The script was then `ruff format`-ed only and rerun identically: `run-02/opcheck.json`
    `77250784…21d0`, script `66e82051…bed9` (the committed bytes).
  - Both runs give identical cell results.
- τ, ε and the budget were read from `cart_k562_d8_v1.yaml`, which the v2 config inherits; this is
  the as-run evaluation path. Budget = 0.10.

| Cell | C targets | As-run threshold | Registered threshold | C use / failure at threshold |
|---|---|---|---|---|
| P1 / sign | 206 | 0.000 | 0.000 | 1.000 / 0.085 |
| P1 / magnitude | 206 | 1.000 | 1.000 | 0.0015 / 0.000 |
| P2 / sign | 266 | 0.888 | 0.888 | 0.168 / 0.042 |
| P2 / magnitude | 266 | 0.935 | 0.935 | 0.0010 / 0.063 |
| P3 / sign | 327 | 0.838 | 0.838 | 0.0030 / 0.087 |
| P3 / magnitude | 327 | none (`inf`) | none (`inf`) | 0 / — |

**Result:**
- The as-run and registered thresholds are **identical in all six cells**.
- Every selected-risk, use-rate and comparative number in the results therefore stands as
  registered.
- For P3/magnitude, no usable set exists under either definition. This settles by measurement the
  point the 2026-10-01 review left open.
- The defect is real in general. CART-K562-V3 uses the exhaustive search, and the tests pin the
  counterexample.

## Deviation 2 — B0 constant weighting (candidate; E-side effect not evaluated)

- **Registered wording** (v1 protocol, line 144): every rate weights each target equally.
- **As-run code** (`d8_develop_v2.py:144`): the B0 constant is the row mean of role-D labels.
- **Effect:** B0 enters D8-v2 only as the Brier-comparison baseline. Measuring the effect would
  need role E, which is consumed, so it is **not evaluated**. Every cell's Brier comparison is recorded as
  "registered B0 weighting not evaluated". That includes P1/sign, which failed narrowly (UCB
  +0.0012); its FAIL verdict also rests on calibration, which is not affected.
- **V3:** the weighting is an explicit, fail-closed rule (`b0_weighting`).
