# CART-K562-D8-v2 — provenance audit for the as-run code commit (2026-10-04)

> **This is a post-hoc preservation of the as-run snapshot.** It does not make the 2026-09-28 run a
> clean-SHA run. The run's code identity remains the per-file SHA256 recorded in the freeze record
> ([copy](2026-09-28-cart-k562-d8-v2-freeze-v2.json), SHA256 `deff8395…4908`, `git_head` `d4dca83`,
> note "working tree dirty; code identity is per-file SHA256"). Verdicts and results are unchanged:
> [results](../2026-09-28-cart-k562-d8-v2-results.md).

## Freeze record re-check (2026-10-04)

- **28/29 pinned files match byte-for-byte.** This covers configs, `day8_protocol.py`, the five
  freeze-pinned D8 scripts, `manifest.py`, `outcome_store.py`, and the prediction and control
  artifacts outside Git.
- **The 29th file is the protocol document.** It differs only by the dated 3-line status banner added
  in `b6303ab`. The blob at `d4dca83` hashes to the pinned value `82d4ad29…3037`.
- **V3 adapter.** `scripts/cartographer/state_predict.py` hashes to `202c34c7…449e`, matching
  `configs/cart_k562_v3.yaml` `predictor.adapter_sha256`.

## Files committed (bytes as they exist in the working tree)

- **Contract:** `docs/contracts/2026-09-23-cartographer-scientific-validity.md`. Committed D8/V3
  documents link to it as their governing contract. All of its internal links resolve in HEAD.
- **Library:** `src/alive/experiment/day8_protocol.py`, plus `src/alive/eval/events.py` (the event
  reference that a D8 test imports; its only dependency is the tracked `alive.metrics.selective`).
- **Scripts:** `scripts/cartographer/` — `d8_prepare`, `d8_observe`, `d8_develop`, `d8_develop_v2`,
  `d8_evaluate`, `d8_evaluate_v2`, `state_predict`, `state_se_predict`, `tg_predict`.
- **Tests:** `tests/alive/experiment/test_{d8_develop,d8_develop_v2,d8_observe,d8_prepare,day8_acceptance,day8_protocol,state_predict,tg_predict}.py`
  and `tests/alive/eval/test_events.py`.

## Identity gaps (stated, not resolved)

- **Three scripts have no independent pin:** `d8_prepare.py`, `state_se_predict.py` and
  `tg_predict.py`. Their file mtimes predate the outputs they produced (prepare 19:00 vs 20:39;
  SE 23:54 vs 01:34; TG 18:12:47 vs 18:12:49). That is consistent with no later edit, but it is not
  proof.
- **`tg_predict.py` ran against an uncommitted `src/alive/data/features.py`.** That file is not
  part of this commit. The diff adds integrity checks to `FeatureBank.read` and does not change the
  values it returns for a valid bank. The test passes against the HEAD version.

## Verification

Checked in a detached worktree at `535af8b` with only the files above added:
- the targeted tests passed (83);
- `ruff check` and `ruff format --check` passed.

`tests/test_documentation_hygiene.py` **fails on a clean `535af8b` checkout even without these
files**. Three tracked plan/audit documents link to untracked files:
- `2026-09-21-endpoint-real-data-milestone.md` (two links);
- `test_methodlock_precision.py`.

That failure predates this commit and is outside its scope. Before this commit, the full suite on
the dirty working tree passed: 4706 passed, 24 skipped.

## Not done

- No push. External timestamping is a separate owner gate.
- No second copy of `d8-run-01/` exists on this machine. It is still the only copy of
  `evaluation.json` and `seal-audit.jsonl`.
