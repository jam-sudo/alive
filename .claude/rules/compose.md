---
paths:
  - "src/alive/compose/**"
  - "tests/alive/compose/**"
  - "scripts/compose/**"
  - "scripts/baselines/gears_worker.py"
  - "scripts/baselines/cpa_worker.py"
  - "scripts/baselines/stub_worker.py"
  - "scripts/run_compose_k562_phase2.py"
  - "configs/compose*.yaml"
  - "docs/**/*compose*.md"
  - "docs/**/COMPOSE-*.md"
---

# COMPOSE-K562-v1 rules

- Lifecycle is ACTIVE, execution is RELEASE-BLOCKED, and the COMPOSE seal is UNOPENED. ACTIVE does
  not authorize a run by itself.
- Current state and blockers: `docs/superpowers/COMPOSE-SEAL-READINESS.md`. One-time execution
  contract: `docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md`.
- The study is Norman K562 CRISPRa pair-level GI prediction. Do not import Replogle CRISPRi data,
  identifiers, assumptions, or claims into this protocol.
- The committed config still contains release-blocking null/unestablished fields. Do not fill them
  from local guesses, compatibility observations, quarantined evidence, or sealed outcomes.
- Scientific execution requires a finalized config and evidence lineage, valid current
  `ActivationRecord`, clean owner-approved exact Git SHA, passing release gate, and canonical
  protocol-global seal audit path.
- PREPARE/development reads only registered non-sealed roles. The sealed source is not opened,
  stat-derived for selection, materialized, or used for normalization/model/baseline choice.
- Do not weaken `driver/seal_boundary.py`, `run_spec.py`, `phase2b_cmd.py`, outcome-store, freeze,
  preflight, pair-index, write-once, terminal, or durable-publish guards.
- Config/data-card/evidence field changes alter scientific lineage and require a new run identity;
  comment-only documentation cleanup must not be mixed with config mutations.
- Use targeted COMPOSE tests first, then `uv run pytest -q tests/alive/compose`; report pod-only
  checks as unrun rather than substituting a local mock.
