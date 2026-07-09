# COMPOSE Durable-Publish + Non-Circular Provenance (D1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the one-time Phase-2b sealed-run artifacts crash-safe and recoverable: a non-circular checksum hierarchy, a v2 terminal payload that embeds the full registered summary + embedded provenance, and an atomic durable-publish + recovery step gated by a single commit marker.

**Architecture:** Migrate the terminal↔provenance checksum layering to break the Change-C-deferred self-reference (terminal embeds provenance; provenance no longer embeds a hash of the terminal). Add a new `durable.py` publish/recovery module that consumes only durable files, republishes derived artifacts idempotently, and declares completion ONLY via a last-written commit marker. Wire it into `run_phase2b` for the normal, INVALID, and abort paths.

**Tech Stack:** Python 3.11–3.12, `uv`, `pytest`, `ruff` (line-length 100), stdlib `hashlib`/`json`/`os`, `dataclasses`, `alive.io.atomic_write_once`, `alive.provenance.sha256_json`.

**Design source:** `docs/superpowers/specs/2026-07-05-compose-durable-ledger-design.md` §1–§3, §5, §6.1. This plan is **D1 only**, but D2 is an explicit prerequisite for Tasks 3, 5 and 7: the verified `development_seed_variability.json` and its pre-access-ledger SHA must already exist. There is no placeholder or post-seal backfill.

## Global Constraints

- **No seal is opened.** D1 stores/recovers artifacts of an ALREADY-consumed `Phase2bResult` (or an abort). No scoring, verdict, or seal re-run. `sealed_access_count` is never incremented by D1.
- **Non-circular checksum direction (spec §1.1), one-way only:** `pre_access_provenance` (seal-pre inputs + upstream only) → `terminal_embedded_provenance` (= verified pre_access payload + seal audit identity + `regime_result_double/single_sha256`; `provenance_checksum` = self-excluding) → terminal embeds that payload+checksum and binds the whole terminal with `terminal_payload_checksum` → the final ledger + commit marker bind the terminal file SHA from OUTSIDE. `terminal_embedded_provenance` MUST NOT contain `terminal_report_sha256`, final-ledger SHA, or commit-marker SHA.
- **Terminal schema = `"compose_phase2b_terminal_v2"`.** Reject unknown/missing keys. Checksum canonicalization: ints/str/bool verbatim and IEEE-754 floats as `float.hex()` strings; reject `NaN`/`Infinity`/non-finite/unsorted mappings. State-specific fields = the state's set ∪ the common set only. Finalizer verifies filename ↔ `terminal_state`.
- **`Phase2bResult.result_checksum` MUST equal `final_result_checksum`** = `sha256_json({terminal_state, final_verdict_checksum, registered_summary_checksum, evaluation_payload_checksum, provenance_checksum})`. INVALID must not reuse a normal-verdict payload checksum.
- **No per-pair error arrays, no per-pair CI, no raw cell/count matrices** in any terminal / summary / ledger payload. Aggregates are computed ONCE in the protected evaluation and COPIED verbatim by the exporter — never recomputed.
- **Write-once everywhere:** all installs use `atomic_write_once`; recovery uses `install_or_verify_exact` (install if absent, else verify byte-identical, else fail closed). Never overwrite an existing artifact; never write a second terminal.
- **Durable completion is declared ONLY by a fully-verified `phase2b_durable_commit.json`.** A terminal without a marker is evidence of seal consumption, not of export completeness.
- **Seal-critical migration (spec F3):** Task 8 re-runs the full CLAUDE.md#verify suite (leakage/provenance/tamper/resume) + `ruff`. Every task runs the compose suite.

## Prerequisite Task 0: durable audit defines the consumed-seal boundary

The current `phase2b.py` calls `terminal.claim_access()` before
`ComposeOutcomeStore.evaluate_sealed_once()` writes its durable audit. That in-memory transition is
not proof of seal consumption and must be removed before terminal-v2 work.

Split the outcome-store operation into an atomic durable claim and a claim-bound materialization:

```python
claim = outcome_store.claim_sealed_access(run_id, exact_union)  # audit write + fsync/verify
terminal.confirm_durable_access(claim.audit_reference)
release = outcome_store.materialize_claimed(claim)
```

The terminal may enter an internal `ACCESS_ATTEMPTED` state before the claim, but only a verified
audit record may transition it to `ACCESS_CLAIMED`. An exception before the durable audit leaves no
`ABORTED_AFTER_SEAL` artifact and is reported as a pre-access failure. An exception after audit write
(including materialization failure) writes exactly one `ABORTED_AFTER_SEAL` terminal with
`sealed_access_count=1` and the matching audit reference. Recovery derives consumption from the
audit record, never from an in-memory method call.

Required tests: pre-audit validation/I/O failure → count 0 and no post-seal terminal; audit-written
materialization failure → count 1 and ABORTED; process restart observes the same claim; run/request
digest mismatch fails closed; concurrent claims produce one audit record and one winner.

---

## File Structure

- Modify `src/alive/compose/outcome_store.py` — split durable audit claim from claim-bound
  materialization and expose an immutable claim identity.
- Modify `src/alive/compose/provenance2.py` — split `Phase2bProvenance` into a pre-access field set + a v2 embedded-provenance schema that drops `terminal_report_sha256`; update `check_post_access_consistency`.
- Modify `src/alive/compose/terminal.py` — attempted/durably-claimed state boundary, v2 terminal bodies
  (common fields + `terminal_payload_checksum`), state-field rosters, canonicalization,
  filename↔state check; `aborted()` gains `registered_results_status`.
- Modify `src/alive/compose/phase2b.py` — build `RegisteredEvaluationSummary` once inside the protected boundary; embedded-provenance + the three checksums; `result_checksum = final_result_checksum`; wire the finalizer into the normal/INVALID/abort paths.
- Create `src/alive/compose/durable.py` — `finalize_phase2b_durable_outputs`, `install_or_verify_exact`, `DurableFinalizeResult`, `DurableLedgerError`, commit-marker build/verify, recovery.
- Create `tests/alive/compose/test_durable.py` — publish/recovery/crash-injection/path-safety.
- Modify `tests/alive/compose/test_provenance2.py`, `test_terminal.py`, `test_phase2b.py` — schema-v2, checksum-layering, wiring tests.

---

## Task 1: Non-circular embedded provenance schema (`provenance2.py`)

**Files:**
- Modify: `src/alive/compose/provenance2.py:168-368` (`Phase2bProvenance`, `to_dict`, record mapping, `check_post_access_consistency`)
- Test: `tests/alive/compose/test_provenance2.py`

**Interfaces:**
- Consumes: the existing pre-access fields (protocol … `seal_audit_reference`) and `regime_result_double_sha256` / `regime_result_single_sha256`.
- Produces: a v2 `Phase2bProvenance` whose `to_dict()` (and thus `self_checksum`/`provenance_checksum`) **excludes `terminal_report_sha256`**; a bumped `schema` field (`"compose_phase2b_provenance_v2"`); `terminal_embedded_provenance` = this v2 `to_dict()`.

- [ ] **Step 1: Write the failing test** — the v2 embedded provenance excludes `terminal_report_sha256` and the empty-string trap is gone.

```python
def test_embedded_provenance_v2_excludes_terminal_report_sha():
    prov = _provenance()  # existing fixture (no terminal_report_sha256 arg)
    d = prov.to_dict()
    assert d["schema"] == "compose_phase2b_provenance_v2"
    assert "terminal_report_sha256" not in d
    # regime-result checksums remain (they precede the terminal, no circularity)
    assert "regime_result_double_sha256" in d and "regime_result_single_sha256" in d
    # self_checksum is a hash of the content only, stable across identical inputs
    assert prov.self_checksum == _provenance().self_checksum
```

- [ ] **Step 2: Run it, expect FAIL** — `pytest tests/alive/compose/test_provenance2.py::test_embedded_provenance_v2_excludes_terminal_report_sha -v` (KeyError/`terminal_report_sha256` still present).

- [ ] **Step 3: Implement** — remove the `terminal_report_sha256` field + docstring + `to_dict` entry from `Phase2bProvenance`; add a `"schema": "compose_phase2b_provenance_v2"` entry as the first key of `to_dict`. Remove the `("terminal_report_report", "terminal_report_sha256")` pair from the record mapping (`provenance2.py:366-368`) and any `terminal_report_sha256=""` construction site (`phase2b.py:521`). Update `check_post_access_consistency` so it no longer reads/compares `terminal_report_sha256` (the terminal↔provenance link now runs the other way: the terminal carries the provenance, verified by re-hashing the embedded payload — see Task 5).

- [ ] **Step 4: Run tests** — the new test + the existing provenance2 suite pass; the pre-access-subset/self-checksum tests still hold (the pre-access subset never contained `terminal_report_sha256`).

- [ ] **Step 5: Commit** — `git commit -m "feat(compose): drop terminal_report_sha256 from embedded provenance (D1 non-circular schema)"`

---

## Task 2: v2 terminal payload + `terminal_payload_checksum` (`terminal.py`)

**Files:**
- Modify: `src/alive/compose/terminal.py:472-586` (`complete`/`invalid`/`aborted` bodies), `_write_terminal:667` (add checksum + canonicalization)
- Test: `tests/alive/compose/test_terminal.py`

**Interfaces:**
- Consumes: the caller-supplied report/evidence payloads.
- Produces: every terminal body carries the common exact fields (`schema="compose_phase2b_terminal_v2"`, `protocol`, `run_id`, `terminal_state`, `sealed_access_count`, `seal_audit_reference`, `pre_access_ledger_sha256`, `pre_access_provenance_checksum`) plus `terminal_payload_checksum` (self-excluding SHA-256 over the canonical body). Canonicalization rejects non-finite floats and serialises floats as `float.hex()`.

- [ ] **Step 1: Write the failing test**

```python
def test_terminal_v2_has_common_fields_and_self_excluding_checksum(tmp_path):
    term = _durably_claimed_terminal(tmp_path)  # verified audit -> ACCESS_CLAIMED
    term.complete(_v2_complete_payload(run_id="deadbeef...", ...))
    body = json.loads((tmp_path / Phase2bTerminal.COMPLETE_ARTIFACT).read_text())
    for k in ("schema","protocol","run_id","terminal_state","sealed_access_count",
              "seal_audit_reference","pre_access_ledger_sha256",
              "pre_access_provenance_checksum","terminal_payload_checksum"):
        assert k in body
    assert body["schema"] == "compose_phase2b_terminal_v2"
    # self-excluding: writer and verifier share the same recursive canonicalizer
    checksum_input = canonicalize_terminal_checksum_input(
        {k: v for k, v in body.items() if k != "terminal_payload_checksum"}
    )
    recomputed = sha256_json(checksum_input)
    assert recomputed == body["terminal_payload_checksum"]

def test_terminal_rejects_nonfinite_float(tmp_path):
    term = _durably_claimed_terminal(tmp_path)
    with pytest.raises(TerminalError, match="finite"):
        term.complete(_v2_complete_payload(..., theta=float("nan")))
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** — add one public-to-module `canonicalize_terminal_checksum_input` used by writer, reader, finalizer and tests. It recursively sorts mappings, preserves int/str/bool, converts finite floats to `float.hex()` strings, and rejects non-finite/unsupported values. Persisted JSON retains finite JSON numbers; only the checksum input uses hex strings. In `_write_terminal`, before install: (a) validate the body against the common+state roster (unknown/missing key → `TerminalError`); (b) canonicalize the self-excluding checksum input with that function; (c) compute and insert `terminal_payload_checksum`; (d) verify filename↔state. Never verify by applying raw `sha256_json` directly to the decoded body.

- [ ] **Step 4: Run tests** — new tests + existing terminal suite pass.

- [ ] **Step 5: Commit** — `git commit -m "feat(compose): v2 terminal payload + self-excluding terminal_payload_checksum (D1)"`

---

## Task 3: `RegisteredEvaluationSummary` + COMPLETE/INVALID checksums (`phase2b.py`)

**Files:**
- Modify: `src/alive/compose/phase2b.py` (`_terminal_payload:525`, `_evaluate_inside_boundary` complete/invalid calls, `Phase2bResult` construction)
- Test: `tests/alive/compose/test_phase2b.py`

**Interfaces:**
- Consumes: `regime_double`/`regime_single` (`RegimeScore`), the sealed verdict + `ComposeIntegrityReport`, the verified `terminal_embedded_provenance` payload + `provenance_checksum` (Task 1), the pre-seal seed-variability report checksum.
- Produces: a `build_registered_evaluation_summary(...) -> dict` (outcome-free, built ONCE) with the exact §2.1 fields; `evaluation_payload_checksum`, `final_result_checksum`; `Phase2bResult.result_checksum == final_result_checksum`.

**Registered summary exact fields (spec §2.1):** protocol, run_id, terminal_state, sealed_access_count; double/single per-regime sample counts; per-method aggregate pair MSE (`mean(pair_errors[method])`, computed once in the protected eval); per-comparator theta + simultaneous lower bound, family confidence, bootstrap replicate count; GI-explained point/interval + `gi_structure_recovery="NOT_EVALUABLE"`; final sealed/method axes + all verdict clauses + integrity disclaimer; bundle/manifest/provenance/regime-result/bounds checksums; seed-variability report checksum. **No per-pair arrays or CI.**

- [ ] **Step 1: Write the failing test**

```python
def test_complete_terminal_embeds_summary_and_final_result_checksum(...):
    result = run_phase2b_fixture(...)  # COMPLETE
    body = _read_terminal(result, "complete")
    summ = body["registered_summary"]
    assert set(summ) >= {"per_method_aggregate_mse","theta","simultaneous_lower_bounds",
        "family_confidence","bootstrap_replicates","gi_explained_interval",
        "gi_structure_recovery","sample_counts","seed_variability_report_checksum"}
    assert summ["gi_structure_recovery"] == "NOT_EVALUABLE"
    assert not any("per_pair" in k or k.endswith("_ci") for k in _flatten_keys(body))
    assert body["registered_summary_checksum"] == sha256_json(summ)
    assert body["final_result_checksum"] == sha256_json({
        "terminal_state": body["terminal_state"],
        "final_verdict_checksum": body["final_verdict_checksum"],
        "registered_summary_checksum": body["registered_summary_checksum"],
        "evaluation_payload_checksum": body["evaluation_payload_checksum"],
        "provenance_checksum": body["provenance_checksum"]})
    assert result.result_checksum == body["final_result_checksum"]

def test_invalid_final_result_checksum_differs_from_complete(...):
    # same inputs, one forced INVALID -> different final_result_checksum & terminal_state
    assert _invalid_run(...).result_checksum != _complete_run(...).result_checksum
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement** — add `build_registered_evaluation_summary(*, regime_double, regime_single, sealed_verdict, integrity, provenance_checksum, seed_variability_report_checksum, ...) -> dict`. In `_evaluate_inside_boundary`, after scoring + verdict (and, for INVALID, AFTER the verdict is replaced with INVALID), build the summary ONCE; compute `evaluation_payload_checksum` (over the regime/bounds payload), `registered_summary_checksum`, `final_verdict_checksum`, then `final_result_checksum`. Pass a v2 body (common fields + `registered_summary` payload + `terminal_embedded_provenance` payload + all four checksums) to `terminal.complete(...)` / `terminal.invalid(...)`. Set `Phase2bResult.result_checksum = final_result_checksum`.

- [ ] **Step 4: Run tests** — new tests + existing phase2b suite pass.

- [ ] **Step 5: Commit** — `git commit -m "feat(compose): RegisteredEvaluationSummary + final_result_checksum in COMPLETE/INVALID terminal (D1)"`

---

## Task 4: `ABORTED_AFTER_SEAL` without a `Phase2bResult` (`terminal.py`, `phase2b.py`)

**Files:**
- Modify: `src/alive/compose/terminal.py:529-586` (`aborted` body: add common fields + `registered_results_status`)
- Test: `tests/alive/compose/test_terminal.py`, `tests/alive/compose/test_phase2b.py`

**Interfaces:**
- Consumes: the exception + stage + preflight checksums (already) + the common fields.
- Produces: an abort terminal with the §2.2 state-specific fields (`exception_class`, `message`, `stage`, `preflight_checksums`, `registered_results_status="NOT_AVAILABLE_DUE_TO_ABORT"`) + the common fields + `terminal_payload_checksum`. No `Phase2bResult`.

- [ ] **Step 1: Write the failing tests** — use the Task-0 split store API, not a fixture that manually calls the old in-memory `claim_access()`. Prove both sides of the boundary: (a) an exception before `claim_sealed_access` durably installs an audit writes no post-seal terminal; (b) an exception after a verified claim writes an abort terminal carrying `registered_results_status`, the common v2 fields, `sealed_access_count=1`, and the exact audit reference.

```python
def test_aborted_terminal_has_status_and_no_result(tmp_path, claimed_store):
    term = _terminal(tmp_path)
    term.acquire()
    claim = claimed_store.claim_sealed_access(RUN_ID, EXACT_UNION)
    term.confirm_durable_access(claim.audit_reference)
    with pytest.raises(RuntimeError):
        with term.protect(stage="scoring"):
            raise RuntimeError("boom in scoring")
    body = json.loads((tmp_path / Phase2bTerminal.ABORTED_ARTIFACT).read_text())
    assert body["terminal_state"] == "ABORTED_AFTER_SEAL"
    assert body["sealed_access_count"] == 1
    assert body["seal_audit_reference"] == claim.audit_reference
    assert body["registered_results_status"] == "NOT_AVAILABLE_DUE_TO_ABORT"
    assert body["schema"] == "compose_phase2b_terminal_v2" and "terminal_payload_checksum" in body
```

Add a companion `test_pre_audit_failure_writes_no_aborted_terminal` that injects failure before the
audit write and asserts access count 0 plus no `ABORTED_AFTER_SEAL` file.

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — add `registered_results_status="NOT_AVAILABLE_DUE_TO_ABORT"` + the common fields to the `aborted()` body; route through the same v2 `_write_terminal` (Task 2). Keep the `OMITTED_UNSAFE` fallback for an unsafe `preflight_checksums`.
- [ ] **Step 4: Run tests** — pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(compose): v2 ABORTED_AFTER_SEAL terminal + registered_results_status (D1)"`

---

## Task 5: Durable-publish module — `finalize_phase2b_durable_outputs` (`durable.py`)

**Files:**
- Create: `src/alive/compose/durable.py`
- Test: `tests/alive/compose/test_durable.py`

**Interfaces (spec §3, §3.1):**
```python
class DurableLedgerError(RuntimeError): ...

@dataclass(frozen=True)
class DurableFinalizeResult:
    run_dir: Path
    terminal_state: str
    terminal_path: Path
    registered_summary_path: Path
    final_ledger_path: Path
    commit_marker_path: Path
    commit_checksum: str

def finalize_phase2b_durable_outputs(
    *, run_dir, terminal_path, pre_access_ledger_path, seed_variability_path,
) -> DurableFinalizeResult
```

Behaviour (publish order §3.1): resolve all paths and require each to be a **regular file that is a direct child of `run_dir`** (reject symlink/dir/device/FIFO and any filename outside the roster: terminal ∈ the three terminal filenames, pre-access ledger = `phase2b_pre_access_ledger.json`, seed-variability = `development_seed_variability.json`). Independently scan `run_dir` and require **exactly one** terminal file. Then: (1) read+verify the terminal (canonical JSON, roster, run_id, `terminal_payload_checksum`); (2) read+verify the pre-access ledger (run_id, embedded pre-access provenance payload/checksum, upstream checksums cross-checked vs the terminal's embedded provenance); (3) build `phase2b_registered_summary.json` by **copy+normalise** of the terminal's `registered_summary` bytes; (4) build `phase2b_final_ledger.json` = the pre-access ledger snapshot + the terminal's `terminal_embedded_provenance` expanded into individual canonical provenance entries + write-once file-SHA entries for {terminal, summary, seed-variability}; (5) re-read both files and compare to intended canonical bytes+SHA; (6) install `phase2b_durable_commit.json` LAST (run_id/state, terminal+summary+final-ledger+pre-access-ledger+seed-variability filenames/SHAs, self-excluding `commit_checksum`) — the final ledger does NOT record the marker (deliberate non-self-reference); (7) re-read the marker and re-verify self-checksum + every file SHA + run_id/state.

- [ ] **Step 1: Write the failing test** — a synthetic COMPLETE terminal + pre-access ledger + seed-variability file publishes summary+final-ledger+commit-marker; all three re-read and verify; the marker binds every file SHA. (§6.1 items: publish + re-read; marker last; no per-pair CI in outputs.)
- [ ] **Step 2: Run, expect FAIL** (module absent).
- [ ] **Step 3: Implement** `durable.py` per the interface above. Use `atomic_write_once` for installs; `sha256_json` for canonical checksums; `hashlib.sha256(path.read_bytes())` for file SHAs.
- [ ] **Step 4: Run tests** — pass; compose suite green.
- [ ] **Step 5: Commit** — `git commit -m "feat(compose): durable finalize + commit-marker publish (D1)"`

---

## Task 6: `install_or_verify_exact` + recovery (`durable.py`)

**Files:**
- Modify: `src/alive/compose/durable.py`
- Test: `tests/alive/compose/test_durable.py`

**Interfaces (spec §3.2):**
```python
def install_or_verify_exact(path: str | Path, intended_bytes: str) -> None
    # absent -> atomic_write_once; present & byte-identical -> no-op;
    # present & different -> DurableLedgerError (permanent).
def recover_phase2b_durable_outputs(*, run_dir) -> DurableFinalizeResult
    # 0 or >=2 terminals -> fail closed; 1 terminal + no marker -> re-run §3.1;
    # marker present -> verify-only (never rewrite). Verifies the seed-variability
    # artifact's regular-file bytes+SHA recorded in the pre-access ledger.
```

- [ ] **Step 1: Write the failing tests** — crash-injection at each publish boundary (summary written but not ledger; ledger but not marker) → `recover_*` reproduces the SAME commit marker without reopening the seal; a partial file matching intended bytes is verify-only; a mismatching partial file fails closed; marker-present is verify-only; 0/2-terminal fails closed. (§6.1 D1 items.)
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — refactor Task 5's installs to route through `install_or_verify_exact`; add `recover_phase2b_durable_outputs` that re-scans, branches on marker presence, and re-runs §3.1 idempotently (byte-identical re-derivation ⇒ same marker).
- [ ] **Step 4: Run tests** — pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(compose): idempotent recovery via install_or_verify_exact (D1)"`

---

## Task 7: `run_phase2b` wiring — normal / INVALID / abort (`phase2b.py`)

**Files:**
- Modify: `src/alive/compose/phase2b.py` (`run_phase2b`, `_run_phase2b_core`, `_evaluate_inside_boundary`)
- Test: `tests/alive/compose/test_phase2b.py`

**Interfaces (spec §3.3):**
- Prerequisite: Task 0 and D2 are complete. The scientific entry receives explicit verified
  `oof_manifest_path/checksum` and `seed_variability_path/checksum`; both must match the persisted
  pre-access ledger before any access attempt.
- Normal/INVALID: write the terminal inside the protection boundary, exit the context, then call
  `finalize_phase2b_durable_outputs(...)`. `Phase2bResult` carries the resulting commit-marker
  path/checksum. The finalizer never runs while outcome-bearing evaluation frames are active.
- Abort: a single top-level `except BaseException` in `run_phase2b` locates the terminal `protect` left, calls the SAME finalizer, then re-raises preserving the original traceback (`raise` bare inside the handler after finalize). The context manager and the caller must not double-call. A finalizer failure is attached as an exception note / logged and does NOT replace the original evaluation exception; a missing commit marker signals an incomplete durable export.

- [ ] **Step 1: Write the failing tests** — a COMPLETE fixture run leaves a verified commit marker + `Phase2bResult.durable_commit_checksum`; an abort fixture (raise inside the boundary) re-raises the ORIGINAL exception AND leaves an abort terminal that the finalizer published (marker present); a finalizer that itself raises does not mask the evaluation exception and leaves no marker.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — replace the old pre-audit `terminal.claim_access()` path with Task 0's
  attempted→durably-confirmed transition. Wrap the protected evaluation in a top-level
  `try/except BaseException`; on success call finalize after the protection context has exited; on
  exception call finalize only when a durable post-seal terminal exists, then use bare `raise`.
  A pre-audit failure has no post-seal terminal and therefore does not call the D1 finalizer. Ensure
  exactly one finalize call per terminal path.
- [ ] **Step 4: Run tests** — pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(compose): wire durable finalize into run_phase2b normal/INVALID/abort (D1)"`

---

## Task 8: Seal-critical verification sweep (F3)

**Files:** none new (verification only).

- [ ] **Step 1** — run the full CLAUDE.md#verify suite touched by the migration: `uv run pytest tests/alive/compose/test_provenance2.py tests/alive/compose/test_terminal.py tests/alive/compose/test_phase2b.py tests/alive/compose/test_durable.py tests/alive/compose/test_outcome_store.py tests/alive/test_provenance.py -v` (leakage / provenance / tamper / resume). Expected: all pass.
- [ ] **Step 2** — full suite + lint: `uv run pytest -q && uv run ruff check src tests && uv run ruff format --check src tests`. Expected: green.
- [ ] **Step 3** — confirm the invariants by grep/inspection: no `terminal_report_sha256` remains in the embedded provenance path; no per-pair CI/array key appears in any terminal/summary/ledger payload; `Phase2bResult.result_checksum == final_result_checksum` at every terminal state.
- [ ] **Step 4** — report the commands, results, and any skips. Then hand off to `science-dev` loop-gate (LOCAL) before merge.

---

## Self-Review Notes

- **Ordering** breaks the circularity first (Task 1) so Task 3's embedded provenance is already non-circular. Tasks 5–6 consume the v2 terminals from Tasks 2–4. Task 7 wires the whole thing; Task 8 is the seal-critical net.
- **Types are consistent:** `terminal_embedded_provenance` = `Phase2bProvenance.to_dict()` (v2, no `terminal_report_sha256`); `final_result_checksum` binds exactly the five named checksums; `Phase2bResult.result_checksum` is redefined to it.
- **No placeholders:** each task states exact files, interfaces, checksum formulas, and the §6.1 test cases as acceptance criteria. Greenfield `durable.py` (Tasks 5–6) carries full interfaces; the migration tasks carry the exact field/checksum contracts + representative test code the implementer completes against the real modules.
