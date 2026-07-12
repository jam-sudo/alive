# COMPOSE-K562-v1 · GU sub-project — exact-committed-SHA independent review (PASS)

> **Purpose:** satisfy the `COMPOSE-SEAL-READINESS.md` **GU review-status promotion rule** —
> record the reviewed Git SHA, the review method/iteration, the verdict summary, and the
> verifier-output for promoting **GU → PASS** and merging to `main`.
> **This artifact is the committed verifier output** (the rule accepts "verifier-output SHA-256
> **또는** 같은 내용을 담은 committed audit artifact"). The three independent reviewer reports are
> embedded verbatim in §4.
> **Scope:** GU sub-project only. Opens **no** seal. `COMPOSE` seal remains UNOPENED.

## 1. What was reviewed

- **Branch:** `compose-gene-universe`
- **Reviewed implementation SHA:** `7f6595f67f39173fe8cdeb2c6dba51713442d1d1` (`7f6595f`), off `main` `68001fc`.
- **Commits under review (4):** `28e56d6` (generator + tests + spec) · `9b8d0c4` (probe CLI + roster-receipt trust chain) · `b447a0c` (docs/readiness/audit/Probe-B quarantine + rerun runbook) · `7f6595f` (format-only).
- **Working tree state:** clean and checked out at the exact SHA, so the reviewed files ARE the committed code (not a working-tree snapshot).

**Why this review exists.** The three earlier adversarial-workflow reviews of GU (recorded in
`2026-07-11-compose-gu-local-adversarial-review.md`, marked *iteration 3, INVALIDATED — historical
record only*) were all run **pre-commit against the working tree**. Per the promotion rule a `LOCAL`
ledger ID / working-tree review does **not** justify a PASS in the sealed-readiness index. This review
is against the **committed exact Git SHA** and supersedes them for promotion purposes.

## 2. Method

Three **independent** adversarial reviewer subagents, each a distinct lens, dispatched against the
committed exact SHA with no shared context and no knowledge of each other's or the prior reviews'
verdicts (to avoid anchoring). Each was instructed to verify every claim against the actual code,
mark findings CONFIRMED (traced) vs PLAUSIBLE, and emit an explicit verdict. Full reports in §4.

| Lens | Verdict | Critical | Important | Minor |
|---|---|---|---|---|
| seal-safety / outcome-leakage / governance | **APPROVE** | 0 | 0 | 0 |
| correctness / logic | **APPROVE** | 0 | 0 | 0 |
| spec-compliance / test-adequacy | **APPROVE-WITH-FIXES** | 0 | 0 | 5 |

**Aggregate: 0 Critical, 0 Important, 5 Minor** (all Minor are test-adequacy gaps on defensive
branches that all three reviewers verified work correctly at runtime; none is a code defect).

## 3. Verification evidence

- **Full compose suite @ `7f6595f`:** `1270 passed` in 1155.31s (19m15s), exit 0.
- **In-scope focused suites @ `7f6595f`:** `test_gene_universe.py` + `test_gears_decision_probe_cli.py` + `test_gears_probe_evidence_contract.py` → **37 passed**; `test_response.py` → **26 passed**. Ruff check + format-check clean on all changed source files.
- **§4.3 code guards** (`outcome_store.py`, `gates.py`, `freeze.py`) — **not in the diff**; confirmed byte-unchanged and not weakened/bypassed by the new code.
- **No seal opened** anywhere in the changeset.

## 3.1 Resolution of the 5 Minor findings (post-review, test-only)

The `src/` and `scripts/` implementation is **byte-identical to the reviewed SHA `7f6595f`** — only
test files changed. Four findings were closed by adding negative tests that trip each guard's
guard-specific message (non-tautological: the message is emitted only by that guard, so deleting the
guard fails the test). The fifth is confirmed genuinely unreachable and documented rather than tested.

| # | Finding (reviewer 3) | Guard | Resolution |
|---|---|---|---|
| 1 | write-once "different bytes" branch untested (spec §9 lists it) | `gene_universe.py:517` | `test_roster_write_rejects_overwrite_with_different_bytes` |
| 2 | loader exclusion-reason whitelist has no negative test | `gene_universe.py:674` | `test_loader_rejects_exclusion_with_reason_outside_whitelist` |
| 4 | `rank_gene_indices_by_variance` validation raise-paths untested | `response.py:519,531` | `test_rank_gene_indices_by_variance_orders_and_validates` (known-answer order + all 6 raise-paths) |
| 5 | loader size-accounting branch untested in isolation | `gene_universe.py:689-698` | `test_loader_rejects_inconsistent_size_accounting` |
| 3 | AliasMap identity-alias guard untested | `gene_universe.py:146-148` | **Confirmed unreachable** — any `A→A` record trips the chain/cycle guard at `:144` first (`{"A"} & {"A"}` is truthy), so no negative test can reach `:146-148` via the public `AliasMap.load` API. Reviewers 2 and 3 independently agree it is subsumed defensive redundancy. Retained as fail-closed depth; documented here rather than tested. Source left byte-identical. |

**Post-fix verification:** the 4 new tests pass; host suites `test_gene_universe.py` (32) +
`test_response.py` (26 → 27) green; ruff clean. Full compose suite re-run recorded in the commit that
adds these tests.

## 4. Independent reviewer reports (verbatim verifier output)

### 4.1 Lens A — seal-safety / outcome-leakage / governance → VERDICT: APPROVE

> I traced every data path in `gene_universe.py` and `gears_decision_probe.py`, diffed all five source
> files against the branch point, ran the in-scope test suites, and re-derived the trust chain
> adversarially. **No finding.** Each mandated check is CONFIRMED (traced), not merely plausible.
>
> **1. Outcome-free guarantee — CONFIRMED.** `compute_mandatory_report` consumes only `full_var`,
> `fit_artifact_identity` (SHA digests only), `response_projection` (frozen HVG IDs + `median_library`
> + digests — all control-derived, outcome-free), the pre-split `perturbation_candidates` tokens,
> `gene2go`, and `alias`. No post-intervention response magnitude, sealed store, or measured effect
> enters gene selection. `generate_gears_gene_roster` selects fill genes purely from
> `_control_variance(control_counts_full)`, where `control_indices` are exactly `role == "control"`
> rows (`gears_decision_probe.py:329-340,359`). `payload["pair_ids"]`/`calibration_pair_ids` flow
> **only** into `validate_fit_role_artifact(...)` at lines 322-324 and 458-460 — never into
> `compute_mandatory_report` or the variance path. Locked by a test that greps the generator source for
> `outcome_store`, `ComposeOutcomeStore`, `read_unsealed`, `pair_ids` and asserts absence
> (`test_gene_universe.py:483`).
>
> **2. §4.3 code guards untouched — CONFIRMED.** `outcome_store.py`, `gates.py`, `freeze.py`,
> `terminal.py`, `durable.py`, `preflight.py`, `io.py`, `provenance.py` are not in the diff. New code
> imports only benign primitives; nothing weakens the sealed-read block or leakage wall.
>
> **3. No seal opened — CONFIRMED.** No `claim_sealed_access` / `evaluate_sealed_once` / `read_unsealed`
> / sealed-role access anywhere in the changeset.
>
> **4. Roster-receipt trust chain authenticity — CONFIRMED sound.** `prepare-input` anchors on the
> external `--roster-receipt-sha256`, byte-verifies the receipt against it, then derives
> `roster_file_sha256` from the verified receipt (`:449,465-466`) and refuses any naked caller-supplied
> roster digest. `verify-input` anchors on the external `--manifest-sha256` (`:624-625`). No code path
> self-derives the anchor. A self-consistent forged receipt is rejected because its file bytes ≠
> external anchor SHA — exercised by `test_probe_cli_refuses_overwrite_and_tampered_roster_binding` and
> `test_prepare_rejects_receipt_that_passes_file_sha_but_is_internally_inconsistent`. The irreducible
> residual (a caller could pass a self-computed pin) is the fundamental trust root of any pin scheme;
> spec §5 acknowledges it and the rerun runbook mandates ledger-sourced pins and forbids inline
> `$(sha256sum …)` self-authentication. Correctly externalized.
>
> **5. Write-once / provenance (§4.2) — CONFIRMED.** All writers pre-check `exists()`/`is_symlink()`
> and use `io.atomic_write_once` (`os.link`, fails if destination exists) or byte-identical-only
> repeat, else raise. `build_roster` writes the receipt last as completion marker.
>
> **6. Eligibility fixed before split / no outcome-selected universe (#5/#6, §6) — CONFIRMED.** Global
> eligibility is `every canonical perturbation gene ∈ var ∩ gene2go`, computed from pre-split candidate
> tokens; every exclusion recorded with a machine reason and counted (nothing silently dropped). No
> outcome enters the universe definition.
>
> Non-defect operational notes: `--allow-unbound-dev-payload` relaxes only the payload expected-SHA
> sidecar (dev/fixture flag; payload still bound via `canonical_payload_sha256` + fit-role validator;
> production runbook must never pass it). `fit_role.py` obs-index change suppresses an AnnData warning,
> scientific identity `source_row_id` unchanged, artifact SHA unaffected. `response.py` refactor is
> exactly behavior-preserving.
>
> Checks run: 37 passed (in-scope) · ruff clean · full suite zero failures observed.
> **VERDICT: APPROVE** — outcome-free by construction and by test, opens no seal, touches none of the
> §4.3 guards, enforces write-once provenance, correctly externally-anchored trust chain. Supports
> promoting GU to PASS and merging to main.

### 4.2 Lens B — correctness / logic → VERDICT: APPROVE

> No correctness/logic defects found. Every load-bearing claim confirmed by reading the code and
> reproducing behavior with `.venv/bin/python`. Focused suites green: `test_gene_universe` +
> `test_gears_decision_probe_cli` + `test_fit_role` = 75 passed; `test_response` + `test_dev_smoke_payload`
> = 36 passed.
>
> 1. **M-first exact-size construction** — `generate_gears_gene_roster` (`gene_universe.py:531-557`)
> computes `mandatory` first, guards `mandatory_size > n_target` and `n_target > len(full_var)`
> (fail-closed), `fill_count = n_target - len(mandatory)`, fills from non-mandatory only, reconstructs
> in `full_var` order, re-asserts `len(ordered) == n_target`. Reproduced exact size for
> `N_target ∈ {|M|, |M|+1, 10, |full_var|}`; `N_target < |M|`, `0`, `-1`, `True`, `3.0`, `> |full_var|`
> all raise. The "select-then-force-add" 2088 bug cannot recur. CONFIRMED.
> 2. **Exact-size & determinism** — final order derived by iterating `full_var` (not a set); dense vs
> sparse control input → byte-identical `ordered_roster`/`ordered_roster_sha256`/`artifact_checksum`.
> CONFIRMED.
> 3. **AliasMap** — chains, cycles, identity, duplicate raw keys, SHA mismatch all reject.
> Two-measured-column collapse is fail-closed one layer up (`compute_mandatory_report` rejects any
> non-canonical `full_var` column at `:279-284`). Note: identity check `:146-148` is unreachable
> (subsumed by chain/cycle at `:144`) — harmless redundancy. CONFIRMED.
> 4. **`normalize_full_then_subset` arithmetic identity** — dense path literally
> `_normalize_log1p(full)[:, cols]`; bit-exact (`np.array_equal`) vs `response._normalize_log1p` on the
> full matrix then subset, incl a zero-library row; sparse path bit-exact to dense. CONFIRMED.
> 5. **`rank_gene_indices_by_variance` behavior-preservation** — `candidate_indices=None` reduces to
> `np.lexsort((arange, -variance))`, byte-identical to old `_select_hvg` over 2000 random trials with
> heavy ties. CONFIRMED.
> 6. **`fit_role.py` index change** — explicit `index=[str(i)...]` equals AnnData's prior implicit
> default; only effect is suppressing the warning; `source_row_id` unchanged. CONFIRMED.
> 7. **Fail-closed validators** — `load_gears_gene_roster` re-checks file-SHA, canonical-JSON,
> self-checksum, key roster, size accounting, containment, positional ordering, exclusion
> uniqueness/order, provenance key set + SHA shapes; 1-byte tamper rejects. Security boundary is the
> external `expected_file_sha256`, not the self-checksum — correct model. CONFIRMED.
> 8. **Roster-receipt re-derivation** — `prepare_probe_input` (`:471-486`) recomputes 9 bindings and
> compares to the receipt; roster loaded against `receipt["roster_file_sha256"]`, itself pinned by the
> external receipt SHA. `verify_probe_input` independently re-derives row identity, role counts, driver
> SHA, H5AD SHA, all `uns` bindings. CONFIRMED.
>
> Non-blocking notes: `AliasMap.canonicalize` rebuilds its lookup dict per call (negligible at real
> sizes); the identity-alias guard is dead code (subsumed). **VERDICT: APPROVE** — all claims
> reproduced; nothing to change for correctness.

### 4.3 Lens C — spec-compliance / test-adequacy → VERDICT: APPROVE-WITH-FIXES

> **SHA reviewed:** `7f6595f` (clean tree). **Tests @ SHA:** `test_gene_universe.py` +
> `test_gears_decision_probe_cli.py` + `test_gears_probe_evidence_contract.py` → **37 passed** (0
> skipped); `test_response.py` **26 passed** (proves `_select_hvg → rank_gene_indices_by_variance`
> extraction is behavior-preserving); ruff check + format-check clean.
>
> Spec → code → test mapping complete: §3.1–§3.7 (identity/eligibility/M-construction/exact-size/
> fill/consumption), §4 (roster+receipt+report schema, self-excluding `artifact_checksum`,
> `ordered_roster_sha256`), §5 (outcome-free, request-roster invariance, scientific-target invariance,
> normalize-before-subset, write-once, authenticity anchored-not-self-derived), §6 (alias schema/
> one-to-one/no-chains), §8 (`generator_code_sha256` closure; no hardcoded genes/thresholds/N_target),
> §10 (output bridge NOT implemented; response scientific behavior unchanged). **No missing
> requirement, no scope creep, no reachable dead code, no schema drift** (roster 13 keys / provenance
> 12 / receipt 17 / report fields checked field-by-field).
>
> Traced load-bearing forgery tests confirmed **non-tautological**:
> `test_loader_rejects_eligible_gene_absent_from_mandatory` (deleting the guard yields a bare
> `KeyError`, not `GeneUniverseError` → test fails), and
> `test_loader_and_consumer_reject_self_consistent_response_hvg_substitution` (re-hashes a fully
> self-consistent artifact, caught precisely by the frozen `provenance.response_hvg_sha256` binding).
>
> Findings — **all Minor, all test-adequacy** on defensive branches verified to work at runtime:
> (1) write-once "different bytes" branch untested though spec §9 lists it (`gene_universe.py:517`);
> (2) loader exclusion-reason whitelist untested (`:674`); (3) AliasMap identity-alias guard untested
> (`:146-148`, unreachable); (4) `rank_gene_indices_by_variance` raise-paths untested
> (`response.py:513-524`); (5) loader size-accounting branch untested in isolation (`:689-698`).
> **VERDICT: APPROVE-WITH-FIXES** — implementation faithfully realizes the spec and is guarded by real
> negative tests; adding the four/five short negative tests takes the branch to a clean APPROVE.

## 5. Promotion decision

- **Aggregate verdict: PASS** (0 Critical, 0 Important; the sole non-APPROVE verdict is
  APPROVE-WITH-FIXES with only Minor test-adequacy items, now resolved per §3.1).
- **Reviewed implementation SHA:** `7f6595f` (merged implementation byte-identical for all `src/` +
  `scripts/` files; only test files added post-review).
- **Gate profile / iteration:** exact-committed-SHA independent 3-lens adversarial review, iteration 1
  (supersedes the INVALIDATED pre-commit working-tree iterations).
- **Action:** promote **GU → ✅** in `COMPOSE-SEAL-READINESS.md` and merge `compose-gene-universe` to
  `main`. **No seal opened.** `COMPOSE` seal remains UNOPENED and independent of `TG-K562`.
