# ALIVE Repository Documentation Sanitization Audit

> **Audit date:** 2026-07-19
> **Scope:** repository Markdown tracked by Git plus new, non-ignored Markdown in this change
> **Current state:** `COMPOSE-K562-v1` lifecycle **ACTIVE** · execution **RELEASE-BLOCKED** · seal
> **UNOPENED**
> **Non-claim:** this is a documentation/integrity audit. It authorizes no fit, outcome access, or
> scientific run and changes no registered result.

## 1. Review boundary

The review covered root entry points, project governance, `.claude/rules/`, active and historical
specifications, implementation plans, runbooks, readiness indexes, audits, and Markdown links.
Git-ignored personal loop drafts and unrelated in-progress Probe-A implementation changes were not
rewritten. Historical claims, hashes, commands, verdicts, and evidence payloads were preserved.

## 2. Sanitization decisions

| Finding | Resolution |
|---|---|
| Root `CLAUDE.md` mixed always-on governance with TG-specific data details | Kept the root under 200 lines and moved CARTOGRAPHER/COMPOSE/documentation detail into path-scoped rules |
| `ACTIVE` could be read as execution authorization | Standardized the live entry points on lifecycle / readiness / seal: ACTIVE / RELEASE-BLOCKED / UNOPENED |
| COMPOSE lifecycle activation history obscured current blockers | Preserved the 2026-06-30 activation history while making the current ActivationRecord, evidence/config, exact-SHA approval, and release gate mandatory |
| Completed implementation plans looked like current task queues | Added dated completion/history banners without deleting the original tasks or as-built record |
| Stable documents used fragile `CLAUDE.md §N` references | Replaced live references with stable named anchors; retained only explicitly historical as-written references |
| A historical audit contained checkout-specific `/Users/...` links | Converted them to repository-relative links while preserving audit-time source labels and line anchors |
| Universal research reporting requirements were incomplete | Added experimental-unit/replicate, adequacy/power, exclusions/missingness, exploratory/confirmatory, exact-N/effect-size/CI reporting rules |

## 3. Intentionally preserved items

- Missing paths that name a required future artifact or implementation are blockers, not broken
  links. In particular, no placeholder evidence/report/config/module was fabricated merely to make
  a path check green.
- Historical audits and superseded designs keep their point-in-time findings below prominent
  status banners. They were not rewritten to look current.
- The TG sealed verdict remains `NO_DISTINCT_WIN`; the COMPOSE seal remains unopened. No threshold,
  roster, metric, config value, evidence hash, or scientific outcome was altered.
- Concurrent local Probe-A/runbook and worker changes were left intact and outside this edit set.

## 4. Integrity outcome

- Repository Markdown has no local absolute/file-editor links and no unresolved relative Markdown
  links.
- Live documentation has no fragile numbered reference to `CLAUDE.md`; named anchors resolve.
- Root governance is 192 lines and carries the current three-axis state.
- Current state is synchronized across `README.md`, root governance, the COMPOSE readiness index,
  scientific spec, and sealed-run runbook.
- Automated guards now cover anchor resolution, root concision/protocol separation, portable links,
  and current-state synchronization.

## 5. Remaining operational blockers

This cleanup does not change COMPOSE readiness. Real workers/environment evidence, conforming Probe
A and bridge evidence, approximation-bias report/integration, finalized active config/evidence,
current ActivationRecord, clean exact-SHA owner approval, and the release gate remain authoritative
blockers in `docs/superpowers/COMPOSE-SEAL-READINESS.md`. Until they are resolved, real fit and the
one-time sealed run remain forbidden.

## 6. Verification record

- `uv run pytest -q tests/test_claude_md_anchors.py tests/test_documentation_hygiene.py` — **6 passed**.
- `uv run ruff check src tests` — passed.
- `uv run ruff format --check src tests` — **207 files already formatted**.
- `git diff --check` — passed.
- A full `uv run pytest -q` attempt reached approximately 10% without a failure, but was manually
  interrupted because the existing subprocess-heavy suite was disproportionate to this
  documentation-only change. It is not reported as a full-suite pass.
- Pod-only, real-data, and sealed-run checks were not run.
