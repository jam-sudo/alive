# V3.1 confirmation power run (definition fixed before running, 2026-10-04)

Purpose: report P(PASS via B0) for the chosen V3.1 design on the ACTUAL V3.1 roster support
structure (579/960 supported) instead of resampled 240-target counts. Not a design search.

- Design: N=960, T=2, D/C/E 30/30/40, b0_policy accept_all (only this design).
- Roster: target-roster-v3-1-draft-02.json (510ab8a8...), counts from P1 predictions only.
- Grid, interim blanks, sims (500/cell), seeds scheme and criterion: identical to the design doc
  712ea331... (sections 3, 4, 6). Sensitivity cells (shift 0.03, dropout 0.10) included.
- The result is reported as-is. If the criterion fails (P(PASS) < 0.80 at mu 0.91 / sd 0.185 for
  either rho, or > 0.05 at mu 0.83), the design is NOT changed in response; the owner is told.
