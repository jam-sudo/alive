---
paths:
  - "src/alive/data/**"
  - "src/alive/base/**"
  - "src/alive/gate/**"
  - "src/alive/baselines/**"
  - "src/alive/conformal/**"
  - "src/alive/metrics/**"
  - "src/alive/eval/**"
  - "src/alive/experiment/**"
  - "tests/alive/data/**"
  - "tests/alive/base/**"
  - "tests/alive/gate/**"
  - "tests/alive/baselines/**"
  - "tests/alive/conformal/**"
  - "tests/alive/metrics/**"
  - "tests/alive/eval/**"
  - "tests/alive/experiment/**"
  - "configs/cartographer*.yaml"
  - "scripts/make_mini.py"
  - "scripts/diagnose_dev_oof.py"
  - "docs/**/*cartographer*.md"
  - "docs/A100-real-run-runbook.md"
---

# TG-K562 / CARTOGRAPHER rules

- `TG-K562-v1` is COMPLETE. Its seal was opened once and the registered verdict is
  `NO_DISTINCT_WIN`; never re-run or reinterpret that evaluation as a new protocol.
- This pipeline uses versioned Replogle K562 CRISPRi processed Perturb-seq AnnData and preserves
  raw counts plus source/transformation provenance. It is not the Norman CRISPRa COMPOSE dataset.
- Never silently substitute `K562_gwps` for `K562_essential`, or the reverse. The data card and
  protocol config identify the exact asset.
- Profile real cell-count/UMI distributions before registering QC thresholds. Do not treat a
  dataset-specific threshold as a universal biological fact.
- The real ESM encoder is required for scientific feature generation. The NumPy mock is allowed
  only for synthetic/CI runs and must never be an implicit fallback.
- Preserve the four-way role split, sealed outcome-store contract, immutable run ID, and completed
  artifacts. New claims require a new named protocol, config, run identity, and independent seal.
- Authoritative claim spec: `docs/superpowers/specs/2026-06-20-cartographer-design.md`.
- Historical A100 procedure: `docs/A100-real-run-runbook.md` (provenance only; do not execute).
