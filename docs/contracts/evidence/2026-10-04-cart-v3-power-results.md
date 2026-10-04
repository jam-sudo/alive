# CART-K562-V3 — power table results (run `v3-power-01`, 2026-10-04)

> Synthetic and outcome-free; information for the owner's P3 decision, not a decision. Design,
> scenarios, interim blanks and criterion were fixed beforehand in
> [the design doc](2026-10-04-cart-v3-power-design.md) (SHA256 `712ea331…2a44`, verified by the
> script). This was the single run; there are no reruns.

## Provenance

- Output: `artifacts/cartographer/v3-power-01/power.json`, SHA256 `19a1aca7…8dc0`.
- 500 simulations per cell; 480 primary cells plus 32 sensitivity cells; wall time 3 min 12 s.
- Code: uncommitted, identified by SHA256.
  - `src/alive/experiment/v3_protocol.py` `decd0018…a59b`
  - `scripts/cartographer/v3_power.py` `48b41e8f…9e34`
  - Git HEAD `535af8b`.
- Support structure: 151/240 roster targets have ≥ 1 P1 non-negligible output (predictions only).
- Before the run, a timing check ran 10 simulations on synthetic counts (not the roster). Their
  outcomes were discarded.

## Result (P(PASS via B0); a lower bound because B1/ALIVE-L are not simulated)

At the reference scenario μ = 0.91, σ = 0.185, each value below is the minimum over ρ ∈ {0, 1}.

| Design (N, T, D/C/E) | (a) registered C gate | (b) accept-all |
|---|---|---|
| **240, 2, 40/20/40 (registered)** | **0.098** | **0.096** |
| 240, 3, 40/20/40 | 0.042 | 0.048 |
| 480, 2, 30/30/40 | 0.342 | 0.450 |
| 960, 2, 40/20/40 | 0.638 | 0.772 (borderline) |
| 960, 2, 30/30/40 | 0.696 | **0.896 — adequate** |
| 960, 3, 30/30/40 | 0.696 | 0.856 — adequate |

- **Known-bad control (μ = 0.83):** P(PASS) = 0.000 in every design, policy and dependence setting,
  including the sensitivity cells.
- **Criterion outcome:**
  - Under policy (a), **no design is adequate** (maximum 0.696).
  - Under policy (b), the candidate is **N = 960, T = 2, 30/30/40**.
- **Registered design at μ = 0.91 (policy a, ρ = 0):** B0 was rejected on C in 234/500 simulations
  (182 by the budget gate) and failed on E in 217. Under policy (b) the rejections move from the gate
  to C calibration and risk (231/500). D1 alone does not rescue N = 240.
- **More transductions lower power,** because every transduction must pass and Bonferroni grows.
  This confirms Astra's R2 point.
- **Sensitivity:** a 0.03 mean shift in one transduction drops the adequate candidate to
  0.32–0.43, because the pooled D constant then misses the ±0.10 calibration in that unit. A 0.10
  eligibility dropout costs little (0.84–0.86).
- **Higher between-target SD (0.25)** lowers the candidate's power to 0.62–0.70.

## What this means for P3 (owner)

- **As registered, V3 has about a 10% chance of PASS via B0 even if P1's true sign rate is 0.91.**
  The preregistration's adequacy note did not include the C selection, both-transduction and
  Bonferroni steps.
- Reaching the fixed criterion needs **both** a larger N (4×) and changes to rules or fractions.
  Those are D1 (b), 30/30/40, and a new lineage V3.1.
- Even then, the result is fragile to transduction-level shift. That fragility is a property of a
  single pooled constant under per-transduction calibration. It is not a simulation artifact.

## Limits

- Parametric Beta rates; Bernoulli outputs conditional on the target rate.
- Interim blank values (design doc §4).
- B1/ALIVE-L not simulated.
- MC half-width about ±0.03–0.04.
- No empirical D/C resampling arm.

## 2026-10-04 addendum — confirmation run on the actual V3.1 roster

A second run was defined before running (`v3-1-power-confirm-definition.md`, `cc083b7f…64dc`):
the candidate design only (960, 2, 30/30/40, accept-all), on the actual V3.1 roster support
(579/960), with the same grid, sims and criterion. It is not a design search; the result is reported
as-is. Output `artifacts/cartographer/v3-1-power-confirm-01/power.json` (`7cbe43b2…7c85`), script
`v3_power.py` `073f939d…a8e8` (adds `--only`).

- μ 0.91, σ 0.185: P(PASS) **0.902** (ρ 0), **0.828** [0.792, 0.859] (ρ 1) → criterion met,
  **borderline**.
- μ 0.83: 0.000 everywhere. σ 0.25 at μ 0.91: 0.566–0.628. Shift 0.03: 0.318–0.364. Dropout 0.10:
  0.800–0.818.
