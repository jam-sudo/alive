---
paths:
  - "README.md"
  - "virtual-cell-*.md"
  - "docs/**/*.md"
---

# Documentation hygiene

- Preserve the source hierarchy: CLAUDE governance; spec claims; plan/runbook execution; config/data
  card exact values; readiness current release state; git/evidence historical record.
- Use stable `CLAUDE.md#sources`, `#registry`, `#invariants`, `#seal`, `#provenance`, `#data-eval`,
  `#repo`, `#verify`, `#compute`, or `#agent` references. Do not add `CLAUDE.md §N` references.
- A live protocol status must distinguish lifecycle, execution readiness, and seal state. `ACTIVE`
  alone never means `READY`.
- Give superseded, quarantined, invalidated, and historical documents a prominent dated banner and
  a pointer to the current authority. Preserve their as-written results below the banner.
- Do not silently refresh immutable evidence, as-run commands, hashes, registered values, owner
  decisions, or scientific outcomes during prose cleanup.
- Avoid volatile test counts, current-HEAD claims, or task status in stable specs unless explicitly
  labeled as a dated snapshot. Put changing progress in the readiness index.
- Distinguish a missing future artifact named by a plan/blocker from a broken link. Do not fabricate
  the artifact or remove the requirement to make a link checker pass.
- When status changes, update every live entry-point banner that claims current state, but do not
  rewrite historical audits to look contemporaneous.
- Isolate a superseded passage with a `[HISTORICAL …]` marker and close it with an explicit
  `<!-- /HISTORICAL -->` sentinel; block extent is the sentinel, never sentence heuristics.
