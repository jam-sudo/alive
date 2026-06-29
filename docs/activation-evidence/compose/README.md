# COMPOSE-K562-v1 — activation-blocker evidence

> **Status:** PRE-REGISTERED, **ACTIVATION BLOCKED**. These are dev-stage evidence
> artifacts produced on real Norman data with **no seal opened** and **no sealed
> outcomes read**. They do **not** activate the protocol. Activation remains the
> owner's explicit act (config `status` → active + ActivationRecord + CLAUDE.md flip).

Real data: scPerturb `NormanWeissman2019_filtered.h5ad`, sha256
`efde6f5301fe256725dce1d980f37bd96a13481a9a16135515897368e631affc` (== committed
data-card). K562 CRISPRa. Generated on a rented A100 (torch 2.6.0+cu124).

## §10.1 activation_requirements — current evidence

| # | requirement | status | evidence |
|---|---|---|---|
| 1 | `real_norman_phi_rank_and_condition_report` | ✅ evidence | `real_norman_phi_rank_report.json` |
| 2 | `regime_specific_detectable_effect_analysis` | ✅ evidence | `real_norman_detectable_effect_report.json` |
| 3 | `finalized_norman_data_card_and_sha256` | ✅ done | `docs/data-cards/norman_compose_k562_v1.json` |
| 4 | `gears_cpa_reproducible_dependency_lock` | ⬜ deferred | — |
| 5 | `independent_compose_outcome_store_and_access_audit` | ✅ built (Phase 2b) | `src/alive/compose/outcome_store.py` (+ tests) |
| 6 | `phase2_plan_metric_leakage_and_seal_integration_tests` | ✅ built | plans + `tests/alive/compose/` |

## Results summary (git_sha at generation in each JSON)

**1. Φ rank / condition** (`real_norman_phi_rank_report.json`, git 82a9c83) — Rank
gate **PASS** on the real `combo_calibration` design (41 pairs, z-universe 73 genes):

| k_total | sym_dim | rank | full rank | condition |
|---|---|---|---|---|
| 4 | 10 | 10 | yes | 15.8 |
| 6 | 21 | 21 | yes | 32.9 |
| 8 | 36 | 36 | yes | 484.2 |

Algebraically identifiable at all candidate dimensions; conditioning worsens with
`k` (k=8 is the most ill-conditioned → hardest noisy recovery).

**2. Regime detectable-effect / measurability** (`real_norman_detectable_effect_report.json`,
git 79b01e0) — ε computed on `combo_calibration` (dev role) only; sealed regimes
contribute outcome-independent counts only:

- measurability split-half ε ceiling **0.918** (PASS, floor 0.2)
- effect mean‖ε‖ 3.05, split-half noise 0.71, **SNR 4.28**
- power gate (floors: ≥20 pairs, ≥50 cells/pair) — `sealed_double_unseen` n=22
  cells=286 **PASS** (marginal, just above the 20 floor; seed-sensitive per the
  Phase-1 seed survey); `sealed_single_unseen` n=68 cells=300 **PASS**.

## Honest caveats

- Evidence, **not** a green light: items 4 (GEARS/CPA lock) remains, and activation
  is the owner's call.
- `|combo_calibration|` = 41 and double-unseen = 22 are small; the double-unseen
  power margin is thin (registered seed 11; other seeds vary 12–27).
- Drivers: `src/alive/compose/{phi_rank,detectable_effect}.py` (pure, unit-tested)
  + `scripts/compose_{phi_rank,detectable_effect}_report.py` (real-input CLIs).
