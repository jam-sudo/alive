# COMPOSE C0 Library Fixes Implementation Plan

> **Status update (2026-07-19): IMPLEMENTED + MERGED (7/7).** 아래 task는 as-built record이며
> current work queue가 아니다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix seven seal-critical residual defects in the already-merged COMPOSE Phase-2b library so the sub-project C driver can rely on their fixed behavior.

**Architecture:** Each task is an isolated library fix in `src/alive/compose/` (plus its negative tests). No driver code, no orchestration, no PREPARE. These are the §0.1 "C0" code-fix items (#1-preflight leg, #3, #4, #5, #6, #7, #8) from the sub-project C design spec; #2 is a design rule (not a code fix) and #1's durable leg is already implemented, so both are excluded.

**Tech Stack:** Python (see `pyproject.toml`), NumPy, AnnData, pytest, Ruff. Tests via `.venv/bin/python -m pytest` (or `uv run pytest`).

**Spec:** `docs/superpowers/specs/2026-07-07-compose-production-driver-design.md` §0.1.

## Global Constraints

- **Opens NO seal.** Every test uses synthetic fixtures/tmp paths. No real Norman data. No gears/cpa import in `src/`.
- **Canonicalizer landmine (terminal):** any recomputation of a terminal's `terminal_payload_checksum` MUST go through `alive.compose.terminal.canonicalize_terminal_checksum_input` (floats → `float.hex()`), never a raw `sha256_json` over the decoded body.
- **Canonicalizer landmine (pairs):** three different pair canonicalizers exist (`outcome_store._canonical` uses `<=`; `fit_role._canonical_pair` uses `<`; `preflight._canonical_pair_set` rejects `>`). For pair-index keys, reuse `ComposeOutcomeStore._canonical`. Do NOT introduce a fourth.
- **Exact rosters (order-fixed, = config2 constants):** full method roster (9) = `config2._EXPECTED_METHOD_ROSTER` = `("l1_bilinear_identifiable","l2_saturation","l3_symmetric_mlp","additive","no_change","perturbation_mean","id_only","gears","cpa")`; verdict comparator family (5) = `config2._EXPECTED_COMPARATOR_FAMILY` = `("additive","gears","cpa","id_only","l3_symmetric_mlp")`.
- **Write-once / atomicity:** durable installs use `atomic_write_once` (`alive.io`); never a plain `RunLedger.write` in a durable/cross-process path.
- **No per-pair CI / no per-pair arrays** leak into any registered summary or terminal.
- **Every fix carries a negative (fail-closed) test**, not only a positive one.
- **Ledger artifact-name lockstep:** the #1 preflight-leg fix checks the ledger's OWN `run_id`/`config_sha256` header (present today). The C driver will later ADD artifact names (`resolved_run_spec` SHA, `execution_id`, pair-index SHA, seed-report SHA) to the same ledger; keep the header-check independent of that future artifact set so C0 and C stay in lockstep.
- **SDD:** implementers AND reviewers on OPUS (seal-critical).

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `src/alive/compose/preflight.py` | ledger-header identity check | T1 |
| `src/alive/compose/outcome_store.py` | pair-index↔obs validator; `FixtureOutcomeStore` type + factory + allowlist | T2, T3 |
| `src/alive/compose/phase2b.py` | `_is_fixture_store` gate; 9-roster descriptive MSE; summary `schema` field | T3, T5 |
| `src/alive/compose/scoring2.py` | full-roster descriptive pair errors on `RegimeScore` | T5 |
| `src/alive/compose/durable.py` | finalizer recompute + summary roster/schema validation; recover ABORTED synthesis | T6, T7 |
| `src/alive/compose/seed_variability.py` | D2 exact-Cartesian `(method,seed,fold)` check | T4 |
| `src/alive/compose/terminal.py` | (consumed, not modified) ABORTED terminal creation API | T7 |
| tests under `tests/alive/compose/` | negative + positive tests per fix | all |

**Task order** (by dependency/risk): T1 (#1) → T2 (#3) → T3 (#4) → T4 (#7) → T5 (#8, changes summary format) → T6 (#6, validates the T5 summary) → T7 (#5, largest) → T8 (verification sweep). T5 precedes T6 because T6's finalizer validates the 9-roster + `schema` field that T5 introduces.

---

### Task 1: #1 — preflight ledger-header identity check

**Files:**
- Modify: `src/alive/compose/preflight.py` (`run_preflight`, after step 7 at lines 411-425)
- Test: `tests/alive/compose/test_preflight.py`

**Interfaces:**
- Consumes: `RunLedger.to_dict()` → `dict` with keys `"run_id"`, `"config_sha256"` (`provenance.py:462-487`); `compute_compose_run_id(...)` recomputed value; `bundle.run_id`; `config.config_sha256`.
- Produces: no new symbol; `run_preflight` now also fails closed when the ledger's own header disagrees with the bundle/config.

**Context:** Today `run_preflight` recomputes the run id and compares it ONLY to `bundle.run_id` (step 6, lines 398-409) and compares `ledger.artifact_sha(name)` to bundle fields (step 7). It never reads `ledger.to_dict()["run_id"]` or `["config_sha256"]`. A ledger vouching for a different run/config than the bundle it accompanies would pass. `RunLedger` has NO public `.run_id`/`.config_sha256` property — use `to_dict()`.

- [ ] **Step 1: Write the failing tests**

Add to `test_preflight.py` (reuse the module's existing bundle/ledger/config fixtures; construct a ledger whose header differs from the bundle):

```python
def test_preflight_rejects_ledger_run_id_mismatch(<existing fixtures>):
    # Build a valid preflight setup, then rebuild the ledger with a wrong header run_id
    # (artifact SHAs still agree with the bundle, so only the header check can catch it).
    ledger = _ledger_with_header(run_id="deadbeef" * 8, config_sha256=config.config_sha256, artifacts=<bundle-agreeing artifacts>)
    with pytest.raises(PreflightError, match="ledger.*run_id"):
        run_preflight(bundle=bundle, pair_manifest=pair_manifest, config=config,
                      data_card_digest=DC, raw_or_source_digest=RAW, sequence_mapping_digest=SEQ,
                      ledger=ledger, expected_response_dim=DIM)

def test_preflight_rejects_ledger_config_sha_mismatch(<existing fixtures>):
    ledger = _ledger_with_header(run_id=bundle.run_id, config_sha256="0"*64, artifacts=<bundle-agreeing artifacts>)
    with pytest.raises(PreflightError, match="ledger.*config_sha256"):
        run_preflight(..., ledger=ledger, ...)
```

`_ledger_with_header` builds a `RunLedger` with the given header + the artifact SHAs the bundle expects (`frozen_prediction_bundle`, `pair_manifest`, `response_space`, `factor_bank`, `model`) so steps 6-7 pass and only the new header check fires. If the existing tests already build a ledger via a helper, extend it to allow header overrides.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_preflight.py -k "ledger_run_id_mismatch or ledger_config_sha_mismatch" -v`
Expected: FAIL (no such check yet — preflight passes and returns an `EvaluationLock`).

- [ ] **Step 3: Implement the header check**

Insert after step 7 in `run_preflight` (before returning the `EvaluationLock`):

```python
    # 8. ledger's OWN identity header must bind the same run/config as the bundle.
    ledger_header = ledger.to_dict()
    if ledger_header["run_id"] != bundle.run_id:
        raise PreflightError(
            f"ledger run_id {ledger_header['run_id']!r} != bundle.run_id {bundle.run_id!r}; "
            "the ledger vouches for a different run identity than the bundle"
        )
    if ledger_header["run_id"] != recomputed:
        raise PreflightError(
            f"ledger run_id {ledger_header['run_id']!r} != recomputed run id {recomputed!r}"
        )
    if ledger_header["config_sha256"] != config.config_sha256:
        raise PreflightError(
            f"ledger config_sha256 {ledger_header['config_sha256']!r} != "
            f"config.config_sha256 {config.config_sha256!r}"
        )
```

- [ ] **Step 4: Run to verify they pass + the happy path still passes**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_preflight.py -v`
Expected: PASS (new negatives pass; all existing preflight tests still green — the standard fixtures build a matching-header ledger).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/preflight.py tests/alive/compose/test_preflight.py
git commit -m "fix(compose): preflight verifies ledger's own run_id/config_sha256 header (C0 #1)"
```

---

### Task 2: #3 — pair-index ↔ source-obs perturbation-label validation

**Files:**
- Modify: `src/alive/compose/outcome_store.py` (add a module-level function; do NOT change `ComposeOutcomeStore.__init__`)
- Test: `tests/alive/compose/test_outcome_store.py`

**Interfaces:**
- Consumes: `ComposeOutcomeStore._canonical(pair)` (the `<=` canonicalizer, lines 390-412); `source.obs[perturbation_col]` (a pandas Series of str labels); `pair_index: Mapping[PairID, np.ndarray]` (canonical pair → bounded int row-index array).
- Produces: `validate_pair_index_against_source_obs(source, pair_index, manifest, *, perturbation_col="perturbation", combo_sep="_") -> None` — raises `ComposeSealingError` on any row whose obs perturbation label does not canonicalize to the pair it is indexed under. The C driver (sub-project C, phase2b step 4) calls this AFTER confirmation and BEFORE constructing the sealed store.

**Context:** `ComposeOutcomeStore.__init__` never reads `source.obs` (only `source.X.shape[0]`); it validates ranges/duplicates/cross-pair overlap/manifest-key-set but NOT that a pair's rows actually carry that pair's perturbation label. The cross-pair overlap half is ALREADY handled (`outcome_store.py:334-339`) — only the obs-label alignment is missing. This is a standalone validator (the capability restriction in the spec keeps obs reads out of preflight/phase2a; only phase2b reads obs).

- [ ] **Step 1: Write the failing tests**

Add a source stub that carries `.obs` (the existing `_InMemorySource` has only `.X`):

```python
import pandas as pd

class _ObsSource:
    def __init__(self, x, labels):  # labels: list[str] aligned to rows
        self.X = x
        self.obs = pd.DataFrame({"perturbation": labels})

def _labels_for(pair_index, combo_sep="_"):
    # Build a correct label array: each row gets the combo token of the pair it belongs to.
    n = 1 + max(int(i) for rows in pair_index.values() for i in rows)
    labels = [""] * n
    for (a, b), rows in pair_index.items():
        for i in rows:
            labels[int(i)] = f"{a}{combo_sep}{b}"
    return labels

def test_validate_pair_index_obs_alignment_passes_on_correct_labels(<manifest+pair_index fixtures>):
    labels = _labels_for(pair_index)
    source = _ObsSource(np.zeros((len(labels), 4), dtype=float), labels)
    validate_pair_index_against_source_obs(source, pair_index, manifest)  # no raise

def test_validate_pair_index_obs_alignment_rejects_mislabeled_row(<fixtures>):
    labels = _labels_for(pair_index)
    # Corrupt ONE row so it carries a different pair's token.
    victim = int(next(iter(pair_index.values()))[0])
    other_pair = list(pair_index.keys())[1]
    labels[victim] = f"{other_pair[0]}_{other_pair[1]}"
    source = _ObsSource(np.zeros((len(labels), 4), dtype=float), labels)
    with pytest.raises(ComposeSealingError, match="perturbation label"):
        validate_pair_index_against_source_obs(source, pair_index, manifest)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_outcome_store.py -k "obs_alignment" -v`
Expected: FAIL with "validate_pair_index_against_source_obs not defined".

- [ ] **Step 3: Implement the validator**

Add to `outcome_store.py` (module level, near `ComposeOutcomeStore`):

```python
def validate_pair_index_against_source_obs(
    source: object,
    pair_index: Mapping[PairID, np.ndarray],
    manifest: Mapping,
    *,
    perturbation_col: str = "perturbation",
    combo_sep: str = "_",
) -> None:
    """Verify each pair-index row's obs perturbation label canonicalizes to its pair.

    Reads ``source.obs[perturbation_col]`` (a str label per row) and, for every
    (canonical pair -> row indices) entry, asserts every indexed row's label
    parses (on ``combo_sep``) and canonicalizes to that exact pair. Fails closed
    on a missing obs column, an unparsable label, or any mismatch. Reuses
    :meth:`ComposeOutcomeStore._canonical` so the parsed label and the pair key
    use the SAME canonicalization.
    """
    obs = getattr(source, "obs", None)
    if obs is None or perturbation_col not in getattr(obs, "columns", ()):
        raise ComposeSealingError(
            f"source obs is missing the {perturbation_col!r} perturbation column"
        )
    labels = obs[perturbation_col].to_numpy()
    for raw_pair, rows in pair_index.items():
        pair = ComposeOutcomeStore._canonical(raw_pair)
        for i in rows:
            label = str(labels[int(i)])
            parts = label.split(combo_sep)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ComposeSealingError(
                    f"row {int(i)} perturbation label {label!r} is not a 2-gene "
                    f"combo token on {combo_sep!r}"
                )
            observed = ComposeOutcomeStore._canonical((parts[0], parts[1]))
            if observed != pair:
                raise ComposeSealingError(
                    f"row {int(i)} perturbation label {label!r} canonicalizes to "
                    f"{observed!r}, but it is indexed under pair {pair!r}"
                )
```

Note: use `split(combo_sep)` and require exactly 2 non-empty parts (rejects tokens with 0 or ≥2 separators), which is stricter than `split(combo_sep, 1)`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_outcome_store.py -k "obs_alignment" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/outcome_store.py tests/alive/compose/test_outcome_store.py
git commit -m "feat(compose): validate_pair_index_against_source_obs (C0 #3)"
```

---

### Task 3: #4 — dedicated `FixtureOutcomeStore` type + corpus allowlist (retire the mutable marker)

**Files:**
- Modify: `src/alive/compose/outcome_store.py` (add `FixtureOutcomeStore` + `build_fixture_outcome_store` factory + `_FIXTURE_CORPUS_ALLOWLIST`)
- Modify: `src/alive/compose/phase2b.py` (`_is_fixture_store`, lines 932-934)
- Test: `tests/alive/compose/test_phase2b.py`, `tests/alive/compose/test_seal_boundary_split.py`, `tests/alive/compose/test_outcome_store.py`

**Interfaces:**
- Consumes: `ComposeOutcomeStore.__init__(pair_index, source, manifest, *, audit_path)`.
- Produces:
  - `class FixtureOutcomeStore(ComposeOutcomeStore)` — carries a validated `fixture_corpus_attestation`.
  - `build_fixture_outcome_store(pair_index, source, manifest, *, audit_path, corpus_id, source_sha256, builder_code_sha256) -> FixtureOutcomeStore` — the ONLY sanctioned constructor; validates `(corpus_id, source_sha256, builder_code_sha256)` against `_FIXTURE_CORPUS_ALLOWLIST` (committed) and fails closed (`ComposeSealingError`) if not allowlisted.
  - `_is_fixture_store(store) -> bool` = `isinstance(store, FixtureOutcomeStore)` AND its attestation is allowlisted.

**Context:** Today `_is_fixture_store` is a single `getattr(store, "_compose_fixture_marker", False) is True` (phase2b.py:932-934); tests set the marker via `object.__setattr__` on a plain `ComposeOutcomeStore` (6 set-sites, all in tests). Any caller can set the attribute on a real store. Replace the mutable-boolean heuristic with a dedicated type + committed corpus allowlist. `ComposeOutcomeStore` is a plain class (no `__slots__`), so subclassing is straightforward.

- [ ] **Step 1: Write the failing tests**

```python
def test_is_fixture_store_true_only_for_fixture_type(<manifest, source, pair_index, audit_path>):
    real = ComposeOutcomeStore(pair_index=pair_index, source=source, manifest=manifest, audit_path=audit_path)
    assert _is_fixture_store(real) is False
    # Old spoof no longer works:
    object.__setattr__(real, "_compose_fixture_marker", True)
    assert _is_fixture_store(real) is False
    fix = build_fixture_outcome_store(pair_index=pair_index, source=source, manifest=manifest,
                                      audit_path=audit_path, corpus_id=_ALLOWLISTED_CORPUS_ID,
                                      source_sha256=_ALLOWLISTED_SOURCE_SHA, builder_code_sha256=_ALLOWLISTED_BUILDER_SHA)
    assert _is_fixture_store(fix) is True

def test_build_fixture_outcome_store_rejects_unallowlisted_corpus(<fixtures>):
    with pytest.raises(ComposeSealingError, match="corpus"):
        build_fixture_outcome_store(..., corpus_id="not-allowlisted", source_sha256="0"*64, builder_code_sha256="0"*64)

def test_run_phase2b_fixture_rejects_spoofed_marker(<fixture run kit>):
    # A plain store with a manually-set marker must NOT pass run_phase2b_fixture anymore.
    store = ComposeOutcomeStore(...)
    object.__setattr__(store, "_compose_fixture_marker", True)
    with pytest.raises(Phase2bError, match="fixture"):
        run_phase2b_fixture(run_dir=..., outcome_store=store, ...)

def test_run_phase2b_rejects_fixture_type(<scientific kit>):
    fix = build_fixture_outcome_store(...)
    with pytest.raises(ScientificModeError, match="fixture"):
        run_phase2b(run_dir=..., outcome_store=fix, ...)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_phase2b.py -k "fixture_store or fixture_type or spoofed_marker" -v`
Expected: FAIL (`FixtureOutcomeStore`/`build_fixture_outcome_store` undefined; `_is_fixture_store` still trusts the marker).

- [ ] **Step 3: Implement the type + factory + allowlist**

In `outcome_store.py`:

```python
@dataclass(frozen=True)
class FixtureCorpusAttestation:
    corpus_id: str
    source_sha256: str
    builder_code_sha256: str

# Committed allowlist of synthetic fixture corpora (extend as new fixture corpora are added).
_FIXTURE_CORPUS_ALLOWLIST: frozenset[FixtureCorpusAttestation] = frozenset({
    FixtureCorpusAttestation(
        corpus_id="compose_c_fixture_v1",
        source_sha256="<committed 64-hex of the synthetic fixture source bytes>",
        builder_code_sha256="<committed 64-hex of the fixture builder code>",
    ),
})

class FixtureOutcomeStore(ComposeOutcomeStore):
    """A synthetic-fixture sealed store; the ONLY store type the bounded fixture
    Phase-2b path accepts. Built solely by :func:`build_fixture_outcome_store`,
    which validates a committed corpus allowlist. There is no mutable marker."""
    def __init__(self, *args, fixture_corpus_attestation: FixtureCorpusAttestation, **kwargs):
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_fixture_corpus_attestation", fixture_corpus_attestation)

    @property
    def fixture_corpus_attestation(self) -> FixtureCorpusAttestation:
        return self._fixture_corpus_attestation

def build_fixture_outcome_store(pair_index, source, manifest, *, audit_path,
                                corpus_id, source_sha256, builder_code_sha256) -> FixtureOutcomeStore:
    att = FixtureCorpusAttestation(corpus_id=corpus_id, source_sha256=source_sha256,
                                   builder_code_sha256=builder_code_sha256)
    if att not in _FIXTURE_CORPUS_ALLOWLIST:
        raise ComposeSealingError(f"fixture corpus {att!r} is not in the committed allowlist")
    return FixtureOutcomeStore(pair_index=pair_index, source=source, manifest=manifest,
                               audit_path=audit_path, fixture_corpus_attestation=att)
```

In `phase2b.py`, replace `_is_fixture_store`:

```python
from alive.compose.outcome_store import FixtureOutcomeStore, _FIXTURE_CORPUS_ALLOWLIST  # adjust import site

def _is_fixture_store(outcome_store: object) -> bool:
    """True only for a FixtureOutcomeStore whose corpus attestation is allowlisted."""
    return (
        isinstance(outcome_store, FixtureOutcomeStore)
        and getattr(outcome_store, "fixture_corpus_attestation", None) in _FIXTURE_CORPUS_ALLOWLIST
    )
```

- [ ] **Step 4: Migrate the 6 test set-sites**

Replace `object.__setattr__(store, "_compose_fixture_marker", True)` and `self._compose_fixture_marker = True` with `FixtureOutcomeStore` construction. Update `_build_store` (test_phase2b.py:200-217) to call `build_fixture_outcome_store(...)` with allowlisted attestation constants. For the wrapper doubles (`_SpyStore`, `_EmptyCellsStore`, `_RaisingAfterClaimStore`, `test_seal_boundary_split.py:200`) that mimic the store interface, make each subclass `FixtureOutcomeStore` (passing an allowlisted `fixture_corpus_attestation`) OR expose a `fixture_corpus_attestation` property returning an allowlisted attestation AND make `isinstance(store, FixtureOutcomeStore)` hold — the simplest is to subclass `FixtureOutcomeStore` and override the wrapper methods. Add the committed fixture allowlist constants (`corpus_id`, source/builder SHAs) as test-visible constants that match the real allowlist entry.

- [ ] **Step 5: Run to verify all pass**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_phase2b.py tests/alive/compose/test_seal_boundary_split.py tests/alive/compose/test_outcome_store.py -v`
Expected: PASS (new negatives pass; migrated existing tests still green).

- [ ] **Step 6: Commit**

```bash
git add src/alive/compose/outcome_store.py src/alive/compose/phase2b.py tests/alive/compose/test_phase2b.py tests/alive/compose/test_seal_boundary_split.py tests/alive/compose/test_outcome_store.py
git commit -m "fix(compose): dedicated FixtureOutcomeStore type + corpus allowlist, retire mutable marker (C0 #4)"
```

---

### Task 4: #7 — D2 preflight rejects duplicate `(method,seed,fold)` (exact Cartesian)

**Files:**
- Modify: `src/alive/compose/seed_variability.py` (`verify_seed_variability_for_preflight`, lines 2000-2030)
- Test: `tests/alive/compose/test_seed_variability.py`

**Interfaces:**
- Consumes: `report.fold_execution_records` (each a `FoldExecutionRecord` with `.method`, `.seed`, `.fold`); `roster` (`{"gears","cpa"}`), `seed_roster` (`(11,23,37)`), `n_folds`.
- Produces: no new symbol; `verify_seed_variability_for_preflight` now fails closed when the `(method,seed,fold)` set is not exactly the Cartesian product.

**Context:** Today the function does per-record membership checks + a bare count check `len(records) == len(roster)*len(seed_roster)*n_folds`. A duplicate `(gears,11,0)` compensated by a missing `(cpa,37,2)` passes both. The tuple set is never checked against the exact product.

- [ ] **Step 1: Write the failing test**

```python
def test_seed_var_preflight_rejects_duplicate_tuple(<a valid COMPLETE report + oof_manifest fixtures>):
    # Take a faithful report, duplicate one (method,seed,fold) and drop another -> count unchanged.
    recs = list(report.fold_execution_records)
    dup = recs[0]
    victim_idx = next(i for i, r in enumerate(recs)
                      if (r.method, int(r.seed), int(r.fold)) != (dup.method, int(dup.seed), int(dup.fold)))
    recs[victim_idx] = dataclasses.replace(dup)  # a second copy of dup's (method,seed,fold)
    bad = dataclasses.replace(report, fold_execution_records=tuple(recs))  # or rebuild with self-checksum
    with pytest.raises(SeedVariabilityPreflightError, match="Cartesian|duplicate|combination"):
        verify_seed_variability_for_preflight(report=bad, oof_manifest=oof_manifest, ...)
```

(If `SeedVariabilityReport` is frozen + self-checksummed, build `bad` via the report constructor with a recomputed self-checksum so it reaches the tuple check rather than failing an earlier integrity gate — mirror the module's existing report-tampering test helper.)

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_seed_variability.py -k "duplicate_tuple" -v`
Expected: FAIL (the doctored report passes preflight because count + membership hold).

- [ ] **Step 3: Implement the exact-Cartesian check**

Replace the count check (lines 2025-2030) with a set-equality check:

```python
    observed = [(rec.method, int(rec.seed), int(rec.fold)) for rec in report.fold_execution_records]
    expected = {(m, s, f) for m in roster for s in seed_roster for f in range(n_folds)}
    observed_set = set(observed)
    if len(observed) != len(observed_set):
        raise SeedVariabilityPreflightError(
            "duplicate (method, seed, fold) execution record(s) present; each combination "
            "must appear exactly once"
        )
    if observed_set != expected:
        missing = sorted(expected - observed_set)
        extra = sorted(observed_set - expected)
        raise SeedVariabilityPreflightError(
            "a COMPLETE report must execute EXACTLY the (method, seed, fold) Cartesian product; "
            f"missing={missing!r} extra={extra!r}"
        )
```

Keep the per-record membership checks above (they give precise messages); this replaces only the coarse count check.

- [ ] **Step 4: Run to verify it passes + existing seed-var tests green**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_seed_variability.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/seed_variability.py tests/alive/compose/test_seed_variability.py
git commit -m "fix(compose): D2 preflight enforces exact (method,seed,fold) Cartesian product (C0 #7)"
```

---

### Task 5: #8 — descriptive per-method MSE over the full 9-method roster (both regimes) + summary `schema` field

**Files:**
- Modify: `src/alive/compose/scoring2.py` (`RegimeScore`, `score_regime` lines 559-603)
- Modify: `src/alive/compose/phase2b.py` (`per_method_aggregate_mse` build lines 1532-1541; `build_registered_evaluation_summary` lines 624-734)
- Test: `tests/alive/compose/test_scoring2.py`, `tests/alive/compose/test_phase2b.py`

**Interfaces:**
- Consumes: `predictions` (all 9 method blocks per regime, validated by `freeze._validate_role_predictions`); `per_pair_mse(...)` from `alive.compose.metrics`; `observed_delta` (local in `score_regime`).
- Produces:
  - `RegimeScore.descriptive_pair_errors: dict[str, NDArray]` — per-pair MSE for EVERY roster method present in `predictions` (all 9), separate from the verdict `pair_errors` (headline + 5 comparators).
  - `per_method_aggregate_mse` now covers 9 methods in both regimes.
  - `build_registered_evaluation_summary` output gains `"schema": "compose_registered_evaluation_summary_v1"`.

**Context:** `score_regime` computes `pair_errors` only for `methods = (headline, *comparators)` = 6. The 3 missing (`l2_saturation, no_change, perturbation_mean`) DO carry predictions in the bundle (freeze validates the full 9-roster per regime) and are already passed into `score_regime` as `predictions`, just ignored. Compute descriptive per-pair MSE for all 9 without touching the verdict `pair_errors` (verdict logic must keep using the 6). Also add a `schema` field so Task 6 can version-gate the summary.

- [ ] **Step 1: Write the failing tests**

```python
def test_score_regime_descriptive_covers_full_roster(<scoring fixtures with all 9 method prediction blocks>):
    rs = score_regime(headline=_HEADLINE, comparators=_COMPARATORS, predictions=preds_9, ...)
    assert set(rs.descriptive_pair_errors) == set(_EXPECTED_METHOD_ROSTER)  # 9
    assert set(rs.pair_errors) == {_HEADLINE, *_COMPARATORS}                # 6 (verdict set unchanged)

def test_per_method_aggregate_mse_covers_9_both_regimes(<phase2b fixture COMPLETE run>):
    summary = <the registered summary from the run>
    assert set(summary["per_method_aggregate_mse"]["double"]) == set(_EXPECTED_METHOD_ROSTER)
    assert set(summary["per_method_aggregate_mse"]["single"]) == set(_EXPECTED_METHOD_ROSTER)

def test_registered_summary_has_schema_v1(<phase2b fixture COMPLETE run>):
    assert summary["schema"] == "compose_registered_evaluation_summary_v1"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_scoring2.py tests/alive/compose/test_phase2b.py -k "descriptive or aggregate_mse_covers_9 or schema_v1" -v`
Expected: FAIL (only 6 methods; no `schema` key).

- [ ] **Step 3: Implement descriptive_pair_errors + schema**

In `scoring2.py`, add `descriptive_pair_errors: dict[str, NDArray]` to `RegimeScore`, and in `score_regime` after the verdict `pair_errors` loop:

```python
    # Descriptive (non-verdict) per-pair MSE over EVERY roster method present in predictions.
    descriptive_pair_errors: dict[str, NDArray] = {}
    for m in sorted(predictions):
        pred = _prediction_matrix(m, scored, predictions, pca_dim)
        descriptive_pair_errors[m] = per_pair_mse(pred, observed_delta, pair_ids=str_ids, truth_ids=str_ids)
    # reuse the already-computed verdict errors to avoid recompute:
    descriptive_pair_errors.update(pair_errors)
```

Return it on `RegimeScore`. In `phase2b.py`, change `per_method_aggregate_mse` to iterate `regime_*.descriptive_pair_errors` (9) instead of `pair_errors` (6). Add `"schema": "compose_registered_evaluation_summary_v1"` as the FIRST key of `build_registered_evaluation_summary`'s output dict.

- [ ] **Step 4: Migrate existing 6-method assertions + run**

Update any test asserting `per_method_aggregate_mse` has 6 keys to expect 9. Run:
`.venv/bin/python -m pytest tests/alive/compose/test_scoring2.py tests/alive/compose/test_phase2b.py -v`
Expected: PASS. Note: `registered_summary` bytes change (9-method MSE + `schema`) → `registered_summary_checksum` and `final_result_checksum` change; any golden-checksum tests must be recomputed, not deleted.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/scoring2.py src/alive/compose/phase2b.py tests/alive/compose/test_scoring2.py tests/alive/compose/test_phase2b.py
git commit -m "feat(compose): descriptive per-method MSE over full 9-roster both regimes + summary schema v1 (C0 #8)"
```

---

### Task 6: #6 — finalizer recomputes `final_result_checksum` + validates summary schema/roster

**Files:**
- Modify: `src/alive/compose/durable.py` (finalizer verification region, lines ~700-822)
- Test: `tests/alive/compose/test_durable.py`

**Interfaces:**
- Consumes: the terminal body's `final_result_checksum` and its 5 constituents (`terminal_state`, `final_verdict_checksum`, `registered_summary_checksum`, `evaluation_payload_checksum`, `provenance_checksum` — all present in the v2 COMPLETE/INVALID body); the `registered_summary`'s `schema` (from Task 5) + `per_method_aggregate_mse`/`theta` keys.
- Produces: the finalizer now fails closed (`DurableLedgerError`) on a self-consistent-but-wrong `final_result_checksum`, an unexpected summary `schema`, or a summary whose descriptive-MSE roster ≠ the 9-roster / whose `theta` roster ≠ the 5-comparator family.

**Context:** Today the finalizer recomputes `terminal_payload_checksum` (via the canonicalizer), `registered_summary_checksum`, and `provenance_checksum`, but NOT `final_result_checksum` — so a buggy/malicious writer producing a self-consistent-but-wrong `final_result_checksum` passes (post-hoc tamper is caught by the whole-body checksum; a wrong-at-write value is not). And the summary roster/schema is unvalidated.

- [ ] **Step 1: Write the failing tests**

```python
def test_finalizer_rejects_wrong_final_result_checksum(<a COMPLETE terminal + pre-access ledger + seed report on disk>):
    # Rewrite the terminal body with a final_result_checksum that does NOT match its 5 fields,
    # then re-derive the whole-body terminal_payload_checksum so the body is internally self-consistent.
    body = <load terminal body>
    body["final_result_checksum"] = "0" * 64
    <re-set body[TERMINAL_PAYLOAD_CHECKSUM_FIELD] via canonicalize_terminal_checksum_input(body_without_that_field)>
    <install the doctored terminal>
    with pytest.raises(DurableLedgerError, match="final_result_checksum"):
        finalize_phase2b_durable_outputs(run_dir=..., ...)

def test_finalizer_rejects_bad_summary_roster(<COMPLETE terminal>):
    # Drop one method from per_method_aggregate_mse["double"], re-checksum summary + terminal consistently.
    ...
    with pytest.raises(DurableLedgerError, match="roster|method"):
        finalize_phase2b_durable_outputs(run_dir=..., ...)

def test_finalizer_rejects_unexpected_summary_schema(<COMPLETE terminal>):
    # Set summary["schema"] to a wrong value (re-checksum consistently).
    with pytest.raises(DurableLedgerError, match="schema"):
        finalize_phase2b_durable_outputs(run_dir=..., ...)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_durable.py -k "final_result_checksum or summary_roster or summary_schema" -v`
Expected: FAIL (finalizer accepts all three doctored-but-self-consistent bodies).

- [ ] **Step 3: Implement the recompute + validation (summary-bearing branch only)**

In the summary-bearing branch of the finalizer (after the existing `registered_summary_checksum`/`provenance_checksum` recomputes), add:

```python
    # (a) recompute final_result_checksum from its 5 constituents (all present in the body).
    recomputed_final = sha256_json({
        "terminal_state": terminal_body["terminal_state"],
        "final_verdict_checksum": terminal_body["final_verdict_checksum"],
        "registered_summary_checksum": terminal_body["registered_summary_checksum"],
        "evaluation_payload_checksum": terminal_body["evaluation_payload_checksum"],
        "provenance_checksum": terminal_body["provenance_checksum"],
    })
    if recomputed_final != terminal_body["final_result_checksum"]:
        raise DurableLedgerError(
            "terminal final_result_checksum does not match its 5 constituent fields (fail closed)"
        )
    # (b) validate registered-summary schema + rosters (version-gated).
    if registered_summary.get("schema") != "compose_registered_evaluation_summary_v1":
        raise DurableLedgerError(
            f"registered summary schema {registered_summary.get('schema')!r} is not the expected v1"
        )
    for regime in ("double", "single"):
        got = set(registered_summary["per_method_aggregate_mse"][regime])
        if got != set(_EXPECTED_METHOD_ROSTER):
            raise DurableLedgerError(
                f"registered summary per_method_aggregate_mse[{regime!r}] roster {sorted(got)!r} "
                f"!= expected 9-method roster"
            )
    theta_roster = set(registered_summary["theta"])
    if theta_roster != set(_EXPECTED_COMPARATOR_FAMILY):
        raise DurableLedgerError(
            f"registered summary theta roster {sorted(theta_roster)!r} != expected 5-comparator family"
        )
```

Import `_EXPECTED_METHOD_ROSTER`/`_EXPECTED_COMPARATOR_FAMILY` from `alive.compose.config2`. `terminal_body` is the decoded terminal dict the finalizer already holds; `registered_summary` is `terminal_body["registered_summary"]`.

- [ ] **Step 4: Run to verify they pass + existing durable tests green**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_durable.py -v`
Expected: PASS. If any existing durable fixture builds a terminal with a 6-method summary or no `schema`, migrate it to the Task-5 v1 format (recompute checksums; do not gut the assertion).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/durable.py tests/alive/compose/test_durable.py
git commit -m "fix(compose): finalizer recomputes final_result_checksum + validates summary schema/roster (C0 #6)"
```

---

### Task 7: #5 — recover synthesizes `ABORTED_AFTER_SEAL` from `audit=1, terminal=0`

> **SUPERSEDED (as-built, owner-approved 2026-07-07).** The approach below — driving the *forward* `Phase2bTerminal`
> lifecycle (`acquire→attempt_access→confirm_durable_access→aborted`) from `durable.py` — is STRUCTURALLY IMPOSSIBLE:
> `acquire()` refuses a burned seal audit (`terminal.py:671-675`) and holds a never-unlinked `O_EXCL` lock
> (`650-659`); `aborted()` needs `ACCESS_CLAIMED`, reachable only via `acquire()`. As built, C0 added a NEW
> recovery-sanctioned classmethod `Phase2bTerminal.recover_aborted_after_seal` in `terminal.py` (the encapsulated,
> ABORTED-only bypass; seal never opened; count/reference derived from the burned audit;
> `pre_access_provenance_checksum` bound to the pre-access ledger subset checksum; `protocol` from the seed report)
> + a `durable.py` 0-terminal branch that calls it. Scope: `terminal.py` + `durable.py` (+ their tests). Behaviorally
> identical to the intent below. Committed `f9b53f5`; reviewed clean (8/8 seal-safety risks refuted); spec §0.1 #5 + §3.4 reconciled.

**Files:**
- Modify: `src/alive/compose/durable.py` (`recover_phase2b_durable_outputs` lines 1100-1191; the terminal-count branch)
- Test: `tests/alive/compose/test_durable.py`

**Interfaces:**
- Consumes: pre-access ledger (`RunLedger.read` → `protocol`/`run_id`/anchors); the durable audit JSONL (≥1 record, `audit_reference` from `records[0]`); `terminal.py` ABORTED creation via `Phase2bTerminal` (`acquire → bind_pre_access → attempt_access → confirm_durable_access(ref) → aborted(...)`), which writes `terminal_aborted.json`.
- Produces: `recover_phase2b_durable_outputs` handles the `terminal=0 + exactly-one durable audit claim` state by synthesizing an `ABORTED_AFTER_SEAL` terminal (no seal reopen, no verdict recompute) then durable-finalizing it via `_finalize_aborted_terminal`.

**Context:** Today `recover_phase2b_durable_outputs` calls `_scan_single_terminal` FIRST, which fails closed on terminal-count ≠ 1 (durable.py:340-344). A hard process death after `claim_sealed_access` writes the audit but before any terminal leaves `audit=1, terminal=0` unrecoverable. The sanctioned in-process `protect().__exit__` finally only fires if the process survives. The required non-empty identity fields for an ABORTED terminal (`protocol, run_id, seal_audit_reference, pre_access_ledger_sha256, pre_access_provenance_checksum`) all come from the pre-access ledger + the audit claim's `audit_reference`.

- [ ] **Step 0: Confirm the audit-file location** (investigation, no code)

Confirm where the durable audit JSONL lives relative to `run_dir` during a real sealed run — the pre-access ledger / provenance2 records the audit destination (see `provenance2` pre-access artifacts and `terminal.py:_audit_has_records`). The recover branch must locate it from `run_dir` + the pre-access ledger, not a live store. Record the resolved path convention in the task report.

- [ ] **Step 1: Write the failing tests**

```python
def test_recover_synthesizes_aborted_from_audit_only(<a run_dir with: a burned audit JSONL (>=1 record), a pre-access ledger, a seed report, and ZERO terminals>):
    result = recover_phase2b_durable_outputs(run_dir=run_dir)
    # An ABORTED_AFTER_SEAL terminal now exists and a durable commit marker was published.
    assert (Path(run_dir) / Phase2bTerminal.ABORTED_ARTIFACT).is_file()
    assert (Path(run_dir) / DURABLE_COMMIT_FILENAME).is_file()
    body = json.loads((Path(run_dir) / Phase2bTerminal.ABORTED_ARTIFACT).read_text())
    assert body["terminal_state"] == TerminalState.ABORTED_AFTER_SEAL.value
    assert body["seal_audit_reference"]  # non-empty, from the audit claim

def test_recover_aborted_is_byte_identical_idempotent(<same run_dir>):
    r1 = recover_phase2b_durable_outputs(run_dir=run_dir)
    r2 = recover_phase2b_durable_outputs(run_dir=run_dir)  # marker present -> verify-only
    # no rewrite; byte-identical terminal + marker

def test_recover_still_fails_closed_with_no_audit_and_no_terminal(<run_dir with pre-access ledger but NO audit records, 0 terminals>):
    with pytest.raises(DurableLedgerError):
        recover_phase2b_durable_outputs(run_dir=run_dir)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_durable.py -k "recover_synthesizes_aborted or aborted_is_byte_identical or no_audit_and_no_terminal" -v`
Expected: FAIL (recover raises on 0 terminals unconditionally).

- [ ] **Step 3: Restructure the recover terminal-count branch**

Replace the unconditional `_scan_single_terminal` call with an explicit 3-way branch:

```python
    terminals = _scan_terminals(run_dir_resolved)  # returns list (0/1/>=2); factor out of _scan_single_terminal
    if len(terminals) == 1:
        # existing summary-bearing / already-aborted recovery path (unchanged)
        ...
    elif len(terminals) == 0:
        # audit=1, terminal=0 : synthesize ABORTED then finalize; else fail closed.
        pre_access = _load_pre_access_ledger(run_dir_resolved)           # RunLedger.read; raise if absent
        audit_records = _read_run_audit_records(run_dir_resolved, pre_access)  # >=1 required
        if len(audit_records) < 1:
            raise DurableLedgerError(
                "no terminal and no durable audit claim; this is a pre-access failure, not ABORTED "
                "(fail closed)"
            )
        audit_reference = audit_records[0]["audit_reference"]  # non-empty required
        _synthesize_aborted_terminal(run_dir_resolved, pre_access=pre_access, audit_reference=audit_reference)
        terminal_name = Phase2bTerminal.ABORTED_ARTIFACT
        # fall through to the abort finalize path (_finalize_aborted_terminal), same as an in-process abort.
        ...
    else:
        raise DurableLedgerError(f"expected 0 or 1 terminal; found {terminals!r} (fail closed).")
```

`_synthesize_aborted_terminal` uses the sanctioned terminal lifecycle:

```python
def _synthesize_aborted_terminal(run_dir_resolved, *, pre_access, audit_reference):
    header = pre_access.to_dict()
    terminal = Phase2bTerminal(
        run_dir_resolved,
        ledger=pre_access,
        audit_path=<resolved audit path>,
        protocol=header["...protocol..."],
        run_id=header["run_id"],
        pre_access_ledger_sha256=<pre-access ledger file sha>,
        pre_access_provenance_checksum=<pre-access provenance checksum from the ledger>,
    )
    terminal.acquire()
    terminal.bind_pre_access(pre_access_ledger_sha256=..., pre_access_provenance_checksum=...)
    terminal.attempt_access()
    terminal.confirm_durable_access(audit_reference)   # requires the audit file to already have records
    terminal.aborted(
        exception=RuntimeError("recovered: process death after seal claim, before terminal"),
        stage="recover_audit_only",
    )
```

The exact `protocol`/`pre_access_provenance_checksum` field names come from the pre-access ledger header + the provenance2 pre-access artifacts (confirm in Step 0). No outcome store, no bundle, no pair-index is loaded. After synthesis, reuse the existing `_finalize_aborted_terminal` path so the durable marker is published.

- [ ] **Step 4: Run to verify they pass + existing recover/durable tests green**

Run: `.venv/bin/python -m pytest tests/alive/compose/test_durable.py -v`
Expected: PASS (new synth-abort + idempotence + fail-closed pass; existing 1-terminal and ≥2-terminal recovery tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/durable.py tests/alive/compose/test_durable.py
git commit -m "fix(compose): recover synthesizes ABORTED_AFTER_SEAL from audit=1/terminal=0 (C0 #5)"
```

---

### Task 8: Verification sweep + gate

**Files:** none (verification only).

- [ ] **Step 1: Full compose suite**

Run: `.venv/bin/python -m pytest tests/alive/compose -q`
Expected: all green.

- [ ] **Step 2: §13 seal-critical subsets** (leakage / provenance / tamper / resume)

Run: `.venv/bin/python -m pytest tests/alive/compose/test_outcome_store.py tests/alive/compose/test_durable.py tests/alive/compose/test_terminal.py tests/alive/compose/test_seal_boundary_split.py tests/alive/compose/test_seed_variability.py tests/alive/compose/test_preflight.py -q`
Expected: all green.

- [ ] **Step 3: Full repo suite + Ruff**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check src tests && .venv/bin/python -m ruff format --check src tests`
Expected: all green.

- [ ] **Step 4: science-dev loop gate (LOCAL ONLY)**

Run the science-dev profile loop gate on the C0 increment per the standing practice (materialize the harness from `loop-engineering-local` via `git archive`, run `loop_gate.py --phase compose-c0 --profile science-dev --review <verifier JSON> --ledger-dir docs/superpowers/loop/feedback --allow-dirty`, worktree-record the ledger back to `loop-engineering-local`, then remove the harness). LOCAL ONLY — never commit the harness to this branch.

- [ ] **Step 5: Report** the commands run, results, and any skips.

---

## Notes for the executor

- These seven fixes are independent enough to review one at a time, but T5→T6 are coupled (T6 validates the v1 summary schema + 9-roster that T5 introduces) — implement T5 before T6.
- Do NOT wire any of these into a driver; the sub-project C driver plan consumes them (`validate_pair_index_against_source_obs` in phase2b step 4; `build_fixture_outcome_store` in the fixture path; the recover branch via the `recover` subcommand).
- Golden-checksum test migrations (T5/T6): recompute the expected checksums from the new v1 summary bytes; never delete the assertion or the golden.
- Branch: create a dedicated branch off `main` (do NOT reuse `compose-production-driver`, which holds the spec). Commit only named files; never `-A`. The branch-safety grep `loop|claude_science|.superpowers|2026-06-30` must be empty before any commit.
