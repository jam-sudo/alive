# COMPOSE Phase-2b Provenance Digests + Persisted-Ledger Consistency (Changes B+C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the two `TODO(activation)` markers in `src/alive/compose/phase2b.py` — (B) populate the scientific provenance digests from the upstream ledger + a typed inputs object, and (C) make the post-access provenance-consistency check cross-verify a **persisted pre-access digest subset** written to the write-once ledger BEFORE the seal opens, instead of comparing an in-memory record against itself.

**Architecture:** Two changes over one composite-provenance path. (B) `_build_provenance` gains `ledger` + a new `ActivationProvenanceInputs` typed object; on the scientific path it pulls run-identity digests (`data_card` / `raw_data` / `sequence_mapping`) from the upstream ledger (single source of truth) and the remaining scientific digests (processed / feature-bank / dependency-lock / gears+cpa revisions / device / precision / git-commit) from the inputs object; the fixture path keeps synthetic-empty digests. (C) `Phase2bProvenance` gains a `pre_access_digest_subset()` (its `to_dict()` minus the three inherently post-access fields) and a `pre_access_checksum`; the orchestrator records that checksum into the write-once ledger **before** `claim_access()`, and after the single sealed opening `check_post_access_consistency` compares the recomputed `pre_access_checksum` against the **persisted** ledger value — a real tamper detector, not a self-reference.

**Tech Stack:** Python 3.11–3.12, `uv`, `pytest`, `ruff` (line-length 100), stdlib `hashlib`/`json`, `dataclasses`, `functools.cached_property`.

**Design source:** `docs/superpowers/specs/2026-07-01-compose-deep-baselines-design.md` §2 (Change B), §3 (Change C), §5 (invariants) — spec-review PASSED. Provenance record + checks: `src/alive/compose/provenance2.py`. Binding points: `src/alive/compose/phase2b.py` (`_build_provenance`, `_run_phase2b_core`, `_evaluate_inside_boundary`).

## Global Constraints

- **Single source of truth for run-identity digests.** `data_card_sha256`, `raw_or_source_sha256`, `sequence_mapping_sha256` come from the upstream ledger via the existing `_required_digest(ledger, name)` (the same values preflight + `recompute_run_id` consume). They are **never** copied into `ActivationProvenanceInputs` — that object carries only digests NOT already on the run-identity path.
- **Pre-access subset excludes post-access fields.** The pre-access digest subset is `Phase2bProvenance.to_dict()` minus exactly `{regime_result_double_sha256, regime_result_single_sha256, terminal_report_sha256}` — the fields knowable only AFTER the seal opens. This exact set is fixed; do not add or remove members.
- **The consistency check is a persisted cross-check, not a self-reference.** The pre-access subset checksum is recorded into the write-once ledger BEFORE `claim_access()`; the post-access check reads it back from the ledger. It must never compare an in-memory record against a checksum derived from the same in-memory record.
- **Write-once.** The pre-access checksum is recorded under one canonical artifact name exactly once. Any re-record (even same value) raises via the ledger's `DuplicateArtifactError`, surfaced as `ProvenanceError`.
- **Fixture path is behavior-preserving.** `run_phase2b_fixture` passes `provenance_inputs=None` + `fixture_execution=True`; the fixture provenance keeps synthetic-empty scientific digests (`git_commit="UNKNOWN"`). Existing fixture tests must remain green unchanged.
- **Scientific path fails closed on missing evidence.** On the non-fixture path, `_build_provenance` with `inputs=None` raises `Phase2bError` — an activated run must supply real provenance evidence, never assemble a record with empty scientific digests.
- **Dev-stage wiring only.** No seal is opened by this work; the local stub/fixture tests touch no real Norman data and no sealed outcome. A green suite is NOT a scientific verdict (spec §5, CLAUDE.md#invariants/#seal/#provenance).
- ruff clean (line-length 100); NumPy-style docstrings + type hints on public API.

---

## File Structure

- Modify `src/alive/compose/provenance2.py` — add `_POST_ACCESS_FIELDS`, `Phase2bProvenance.pre_access_digest_subset()` + `pre_access_checksum` (Task 1); add `PRE_ACCESS_PROVENANCE_ARTIFACT` + `record_pre_access_provenance()` (Task 2); change `check_post_access_consistency` to a persisted cross-check (Task 4).
- Modify `src/alive/compose/phase2b.py` — add `ActivationProvenanceInputs`; populate `_build_provenance` digests + thread `provenance_inputs`/`fixture_execution` (Task 3); record the pre-access subset before access + read the persisted value post-access (Task 4).
- Modify `tests/alive/compose/test_provenance2.py` — subset/checksum tests (Task 1), record tests (Task 2), post-access kwargs rename (Task 4).
- Modify `tests/alive/compose/test_phase2b.py` — `_build_provenance` populate/raise tests (Task 3), persisted-ledger artifact test (Task 4).

Each task ends with an independently testable deliverable and a commit. **Task order matters:** 1→2 are purely additive to `provenance2.py`; 3 is Change B (threading + populate, the post-access check unchanged); 4 is Change C (the signature change + wiring + test updates land together so the suite is green at the task boundary).

---

### Task 1: `pre_access_digest_subset` + `pre_access_checksum` on `Phase2bProvenance`

**Files:**
- Modify: `src/alive/compose/provenance2.py`
- Test: `tests/alive/compose/test_provenance2.py`

**Interfaces:**
- Produces: module constant `_POST_ACCESS_FIELDS: tuple[str, ...]`; method `Phase2bProvenance.pre_access_digest_subset(self) -> dict` (= `to_dict()` minus the three post-access keys); `cached_property Phase2bProvenance.pre_access_checksum -> str` (64-hex `sha256_json` of the subset).
- Consumes: existing `to_dict()`, `sha256_json`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/alive/compose/test_provenance2.py` (helpers `_provenance`, `_DATA_CARD_DIGEST` already exist in this file):

```python
# ---------------------------------------------------------------------------
# Change C infra: pre-access digest subset (excludes post-access fields)
# ---------------------------------------------------------------------------

_POST_ACCESS_KEYS = (
    "regime_result_double_sha256",
    "regime_result_single_sha256",
    "terminal_report_sha256",
)


def test_pre_access_subset_excludes_post_access_fields():
    sub = _provenance().pre_access_digest_subset()
    for key in _POST_ACCESS_KEYS:
        assert key not in sub
    # a pre-access field survives in the subset.
    assert sub["data_card_sha256"] == _DATA_CARD_DIGEST


def test_pre_access_checksum_ignores_post_access_fields():
    a = _provenance()
    b = _provenance(
        regime_result_double_sha256="X",
        regime_result_single_sha256="Y",
        terminal_report_sha256="Z",
    )
    # The subset checksum is stable across post-access-only changes ...
    assert a.pre_access_checksum == b.pre_access_checksum
    # ... while the FULL self-checksum still moves (post-access fields are in it).
    assert a.self_checksum != b.self_checksum


def test_pre_access_checksum_moves_on_a_pre_access_field():
    a = _provenance()
    b = _provenance(processed_sha256="TAMPERED")
    assert a.pre_access_checksum != b.pre_access_checksum


def test_pre_access_checksum_is_64_hex():
    c = _provenance().pre_access_checksum
    assert len(c) == 64 and all(ch in "0123456789abcdef" for ch in c)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/alive/compose/test_provenance2.py -k pre_access_subset -q`
Expected: FAIL (`Phase2bProvenance` has no `pre_access_digest_subset` / `pre_access_checksum`).

- [ ] **Step 3: Write the implementation**

In `src/alive/compose/provenance2.py`, add the module constant just above the `Phase2bProvenance` class definition (before the `@dataclass(frozen=True)` line):

```python
#: Fields knowable only AFTER the single sealed opening; excluded from the
#: pre-access digest subset (Change C). Fixed set — do not extend.
_POST_ACCESS_FIELDS: tuple[str, ...] = (
    "regime_result_double_sha256",
    "regime_result_single_sha256",
    "terminal_report_sha256",
)
```

Then add these two members to `Phase2bProvenance`, immediately after the existing `self_checksum` cached property:

```python
    def pre_access_digest_subset(self) -> dict:
        """Return the pre-access digest subset (``to_dict`` minus post-access fields).

        The subset is everything computable BEFORE the seal opens: it drops the
        regime-result and terminal-report checksums (:data:`_POST_ACCESS_FIELDS`),
        which are known only after the single sealed access. Recording this
        subset's checksum before access (Change C) turns the post-access
        provenance consistency check into a real tamper detector rather than a
        self-reference (CLAUDE.md#provenance).

        Returns
        -------
        dict
            The content dict with the post-access keys removed.
        """
        subset = self.to_dict()
        for key in _POST_ACCESS_FIELDS:
            subset.pop(key)
        return subset

    @cached_property
    def pre_access_checksum(self) -> str:
        """Canonical-JSON SHA-256 of :meth:`pre_access_digest_subset`.

        Stable across changes to post-access-only fields; moves on any change to
        a pre-access field. This is the value persisted into the write-once
        ledger before seal access and re-checked afterwards (Change C).

        Returns
        -------
        str
            64-character lowercase hex SHA-256 of the pre-access subset.
        """
        return sha256_json(self.pre_access_digest_subset())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_provenance2.py -k pre_access -q`
Expected: PASS (4 new tests). Then `uv run pytest tests/alive/compose/test_provenance2.py -q` — all still green.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/provenance2.py tests/alive/compose/test_provenance2.py
git commit -m "feat(compose): Phase2bProvenance pre-access digest subset + checksum (Change C t1)"
```

---

### Task 2: `record_pre_access_provenance` write-once recorder

**Files:**
- Modify: `src/alive/compose/provenance2.py`
- Test: `tests/alive/compose/test_provenance2.py`

**Interfaces:**
- Produces: module constant `PRE_ACCESS_PROVENANCE_ARTIFACT = "phase2b_pre_access_provenance"`; `record_pre_access_provenance(*, ledger: RunLedger, provenance: Phase2bProvenance) -> str` — records the pre-access checksum under that name into the write-once ledger and returns it; a conflicting re-record raises `ProvenanceError`.
- Consumes: `Phase2bProvenance.pre_access_checksum` (Task 1), `RunLedger.record_artifact`, `DuplicateArtifactError`, `ProvenanceError`.

- [ ] **Step 1: Write the failing tests**

Add the two new names to the existing `from alive.compose.provenance2 import (...)` block in `tests/alive/compose/test_provenance2.py` (`PRE_ACCESS_PROVENANCE_ARTIFACT`, `record_pre_access_provenance`), then append:

```python
# ---------------------------------------------------------------------------
# Change C infra: record_pre_access_provenance (write-once, before access)
# ---------------------------------------------------------------------------


def test_record_pre_access_provenance_records_subset_checksum():
    ledger = RunLedger(
        run_id=_expected_run_id(), config_sha256=_CONFIG_DIGEST, environment=_environment()
    )
    prov = _provenance()
    returned = record_pre_access_provenance(ledger=ledger, provenance=prov)
    assert returned == prov.pre_access_checksum
    assert ledger.artifact_sha(PRE_ACCESS_PROVENANCE_ARTIFACT) == prov.pre_access_checksum


def test_record_pre_access_provenance_is_write_once():
    ledger = RunLedger(
        run_id=_expected_run_id(), config_sha256=_CONFIG_DIGEST, environment=_environment()
    )
    record_pre_access_provenance(ledger=ledger, provenance=_provenance())
    # A second record under the same name (even a different value) is refused.
    with pytest.raises(ProvenanceError):
        record_pre_access_provenance(
            ledger=ledger, provenance=_provenance(processed_sha256="different")
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/alive/compose/test_provenance2.py -k record_pre_access -q`
Expected: FAIL (`record_pre_access_provenance` / `PRE_ACCESS_PROVENANCE_ARTIFACT` undefined).

- [ ] **Step 3: Write the implementation**

In `src/alive/compose/provenance2.py`, add the constant next to the other canonical artifact-name groupings (just above `_DIGEST_ARTIFACTS`):

```python
#: Canonical write-once artifact name for the pre-access provenance subset
#: checksum (Change C). Recorded BEFORE seal access; re-checked afterwards.
PRE_ACCESS_PROVENANCE_ARTIFACT = "phase2b_pre_access_provenance"
```

Then add the recorder function immediately after `record_phase2b_provenance`:

```python
def record_pre_access_provenance(
    *, ledger: RunLedger, provenance: Phase2bProvenance
) -> str:
    """Record the pre-access digest-subset checksum into the ledger BEFORE access.

    Persists :attr:`Phase2bProvenance.pre_access_checksum` under
    :data:`PRE_ACCESS_PROVENANCE_ARTIFACT` in the write-once ledger, so the
    post-access consistency check (Change C) can cross-verify against a PERSISTED
    value rather than the in-memory record (CLAUDE.md#provenance). Called before the
    seal opens; the seal stays closed if this raises.

    Parameters
    ----------
    ledger : RunLedger
        The write-once run ledger to record into.
    provenance : Phase2bProvenance
        The provenance record whose pre-access subset checksum is persisted.

    Returns
    -------
    str
        The recorded pre-access subset checksum.

    Raises
    ------
    ProvenanceError
        If the artifact name is already recorded (write-once violation).
    """
    checksum = provenance.pre_access_checksum
    try:
        ledger.record_artifact(PRE_ACCESS_PROVENANCE_ARTIFACT, checksum)
    except DuplicateArtifactError as exc:
        raise ProvenanceError(
            "write-once violation recording the pre-access provenance subset "
            f"{PRE_ACCESS_PROVENANCE_ARTIFACT!r}: {exc}"
        ) from exc
    return checksum
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_provenance2.py -k record_pre_access -q`
Expected: PASS (2 tests). Then `uv run pytest tests/alive/compose/test_provenance2.py -q` — all green.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/provenance2.py tests/alive/compose/test_provenance2.py
git commit -m "feat(compose): write-once record_pre_access_provenance recorder (Change C t2)"
```

---

### Task 3: Change B — populate provenance digests in `_build_provenance`

**Files:**
- Modify: `src/alive/compose/phase2b.py`
- Test: `tests/alive/compose/test_phase2b.py`

**Interfaces:**
- Produces: frozen dataclass `ActivationProvenanceInputs` with fields `processed_sha256, feature_bank_sha256, dependency_lock_sha256, gears_revision, cpa_revision, python_version, platform, device, precision, git_commit` (all `str`). Revised `_build_provenance(*, bundle, pair_manifest, config, audit_reference, regime_double: RegimeScore | None, regime_single: RegimeScore | None, git_clean, ledger: RunLedger, inputs: ActivationProvenanceInputs | None, fixture_execution: bool) -> Phase2bProvenance`. `run_phase2b` gains keyword `provenance_inputs: ActivationProvenanceInputs | None = None`.
- Consumes: `_required_digest(ledger, name)` (existing), `Phase2bError` (existing).
- Behavior: `fixture_execution=True` ⇒ synthetic-empty scientific digests (`git_commit="UNKNOWN"`) — identical to today. `fixture_execution=False` + `inputs is None` ⇒ raise `Phase2bError`. `fixture_execution=False` + `inputs` ⇒ run-identity digests from the ledger, the rest from `inputs`. `regime_*` `None` ⇒ empty regime-result checksums (used for the pre-access build in Task 4).

- [ ] **Step 1: Write the failing tests**

Add to `tests/alive/compose/test_phase2b.py`. Extend the `from alive.compose.phase2b import (...)` block (currently `Phase2bResult`, `run_phase2b`, `run_phase2b_fixture`) to also import `ActivationProvenanceInputs`, `Phase2bError`, and `_build_provenance` (none of these three are imported yet in this module). Then append:

```python
# ===========================================================================
# Change B: _build_provenance digest population
# ===========================================================================


def _prov_inputs() -> ActivationProvenanceInputs:
    return ActivationProvenanceInputs(
        processed_sha256="proc-sha",
        feature_bank_sha256="fb-sha",
        dependency_lock_sha256="lock-sha",
        gears_revision="gears-9",
        cpa_revision="cpa-9",
        python_version="3.12.3",
        platform="linux-x86_64",
        device="cuda",
        precision="float32",
        git_commit="f" * 40,
    )


def test_build_provenance_fixture_leaves_scientific_digests_empty(tmp_path):
    kit = _make_run(tmp_path)
    prov = _build_provenance(
        bundle=kit["bundle"],
        pair_manifest=kit["manifest"],
        config=kit["cfg"],
        audit_reference="ref",
        regime_double=None,
        regime_single=None,
        git_clean=True,
        ledger=kit["ledger"],
        inputs=None,
        fixture_execution=True,
    )
    assert prov.data_card_sha256 == ""
    assert prov.processed_sha256 == ""
    assert prov.gears_revision == ""
    assert prov.git_commit == "UNKNOWN"
    # upstream (bundle-derived) hashes are still populated on the fixture path.
    assert prov.frozen_prediction_bundle_sha256 == kit["bundle"].bundle_checksum


def test_build_provenance_scientific_requires_inputs(tmp_path):
    kit = _make_run(tmp_path)
    with pytest.raises(Phase2bError, match="ActivationProvenanceInputs"):
        _build_provenance(
            bundle=kit["bundle"],
            pair_manifest=kit["manifest"],
            config=kit["cfg"],
            audit_reference="ref",
            regime_double=None,
            regime_single=None,
            git_clean=True,
            ledger=kit["ledger"],
            inputs=None,
            fixture_execution=False,
        )


def test_build_provenance_scientific_populates_from_ledger_and_inputs(tmp_path):
    kit = _make_run(tmp_path)
    ledger = kit["ledger"]
    # Single source of truth: run-identity digests come from the upstream ledger.
    ledger.record_artifact("data_card", "dc-sha")
    ledger.record_artifact("raw_data", "raw-sha")
    ledger.record_artifact("sequence_mapping", "seq-sha")
    prov = _build_provenance(
        bundle=kit["bundle"],
        pair_manifest=kit["manifest"],
        config=kit["cfg"],
        audit_reference="ref",
        regime_double=None,
        regime_single=None,
        git_clean=True,
        ledger=ledger,
        inputs=_prov_inputs(),
        fixture_execution=False,
    )
    # from the ledger (run-identity path):
    assert prov.data_card_sha256 == "dc-sha"
    assert prov.raw_or_source_sha256 == "raw-sha"
    assert prov.sequence_mapping_sha256 == "seq-sha"
    # from the inputs object (evidence-sourced digests):
    assert prov.processed_sha256 == "proc-sha"
    assert prov.feature_bank_sha256 == "fb-sha"
    assert prov.dependency_lock_sha256 == "lock-sha"
    assert prov.gears_revision == "gears-9"
    assert prov.cpa_revision == "cpa-9"
    assert prov.device == "cuda"
    assert prov.precision == "float32"
    assert prov.git_commit == "f" * 40
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/alive/compose/test_phase2b.py -k build_provenance -q`
Expected: FAIL (`ActivationProvenanceInputs` undefined / `_build_provenance` signature mismatch).

- [ ] **Step 3: Write the implementation**

In `src/alive/compose/phase2b.py`, add the typed inputs object just above `_build_provenance` (import `dataclass` if not already imported at the top — it is used elsewhere in the module; confirm):

```python
@dataclass(frozen=True)
class ActivationProvenanceInputs:
    """Evidence-sourced provenance digests for an activated Phase-2b run.

    Carries the scientific digests that are NOT on the run-identity path (which
    flows from the upstream ledger). Assembled by the caller from the run
    environment and committed activation evidence; passed to :func:`run_phase2b`
    on the activated run. Never carries ``data_card`` / ``raw_data`` /
    ``sequence_mapping`` — those come from the ledger (single source of truth).

    Attributes
    ----------
    processed_sha256, feature_bank_sha256, dependency_lock_sha256 : str
        Processed-AnnData, frozen feature-bank, and dependency-lock digests.
    gears_revision, cpa_revision : str
        Pinned GEARS / CPA baseline revisions (from the dependency lock).
    python_version, platform, device, precision : str
        Run environment tags.
    git_commit : str
        Full Git SHA of the run.
    """

    processed_sha256: str
    feature_bank_sha256: str
    dependency_lock_sha256: str
    gears_revision: str
    cpa_revision: str
    python_version: str
    platform: str
    device: str
    precision: str
    git_commit: str
```

Replace the body of `_build_provenance` (the whole function, keeping its position). New signature + body:

```python
def _build_provenance(
    *,
    bundle: FrozenPredictionBundle,
    pair_manifest: Mapping,
    config: ComposePhase2Config,
    audit_reference: str,
    regime_double: RegimeScore | None,
    regime_single: RegimeScore | None,
    git_clean: bool,
    ledger: RunLedger,
    inputs: ActivationProvenanceInputs | None,
    fixture_execution: bool,
) -> Phase2bProvenance:
    """Assemble the COMPLETE composite provenance record for this run.

    Binds the upstream artifact checksums the run consumed (bundle / manifest /
    response-space / factor / model), the scientific provenance digests, the
    registered seeds and the regime-result checksums.

    On the fixture path the scientific digests are synthetic-empty (they are not
    real evidence). On the scientific path the run-identity digests
    (``data_card`` / ``raw_data`` / ``sequence_mapping``) come from the upstream
    ledger — the same values preflight and the run-id recomputation consume, so
    there is ONE source of truth — and the remaining scientific digests come from
    ``inputs``. A scientific run with ``inputs is None`` fails closed (an
    activated run must supply real evidence, never empty digests).

    ``regime_double`` / ``regime_single`` may be ``None`` to build the pre-access
    record (Change C): the regime-result checksums are then empty, which is
    correct because the pre-access subset excludes them.
    """
    if fixture_execution:
        data_card_sha256 = ""
        raw_or_source_sha256 = ""
        processed_sha256 = ""
        sequence_mapping_sha256 = ""
        feature_bank_sha256 = ""
        dependency_lock_sha256 = ""
        gears_revision = ""
        cpa_revision = ""
        python_version = ""
        platform = ""
        device = ""
        precision = ""
        git_commit = "UNKNOWN"
    else:
        if inputs is None:
            raise Phase2bError(
                "scientific Phase-2b requires ActivationProvenanceInputs to populate the "
                "provenance digests; refusing to assemble a provenance record with empty "
                "scientific evidence on an activated run"
            )
        # Single source of truth: run-identity digests from the upstream ledger.
        data_card_sha256 = _required_digest(ledger, "data_card")
        raw_or_source_sha256 = _required_digest(ledger, "raw_data")
        sequence_mapping_sha256 = _required_digest(ledger, "sequence_mapping")
        processed_sha256 = inputs.processed_sha256
        feature_bank_sha256 = inputs.feature_bank_sha256
        dependency_lock_sha256 = inputs.dependency_lock_sha256
        gears_revision = inputs.gears_revision
        cpa_revision = inputs.cpa_revision
        python_version = inputs.python_version
        platform = inputs.platform
        device = inputs.device
        precision = inputs.precision
        git_commit = inputs.git_commit

    return Phase2bProvenance(
        protocol=config.protocol,
        config_digest=config.config_sha256,
        pair_manifest_sha256=pair_manifest["checksum"],
        exclusion_manifest_sha256=pair_manifest.get("eligibility_hash", ""),
        data_card_sha256=data_card_sha256,
        raw_or_source_sha256=raw_or_source_sha256,
        processed_sha256=processed_sha256,
        sequence_mapping_sha256=sequence_mapping_sha256,
        feature_bank_sha256=feature_bank_sha256,
        response_space_sha256=bundle.response_space_checksum,
        factor_bank_sha256=bundle.factor_checksum,
        model_lock_sha256=bundle.model_checksum,
        frozen_prediction_bundle_sha256=bundle.bundle_checksum,
        git_commit=git_commit,
        git_clean=bool(git_clean),
        dependency_lock_sha256=dependency_lock_sha256,
        gears_revision=gears_revision,
        cpa_revision=cpa_revision,
        python_version=python_version,
        platform=platform,
        device=device,
        precision=precision,
        registered_seeds=tuple(int(s) for s in config.registered_seeds),
        split_seed=int(config.split_seed),
        seal_audit_reference=audit_reference,
        regime_result_double_sha256=regime_double.checksum if regime_double is not None else "",
        regime_result_single_sha256=regime_single.checksum if regime_single is not None else "",
        terminal_report_sha256="",
    )
```

Now thread `provenance_inputs` from the public entry to the boundary (the pre-access recording is Task 4; here we only route the object and keep the post-access build populated):

1. `run_phase2b`: add keyword `provenance_inputs: ActivationProvenanceInputs | None = None` (document it in the docstring's Parameters as "the activated run's evidence-sourced provenance digests; required to populate the scientific provenance on the sealed run"), and pass `provenance_inputs=provenance_inputs` into the `_run_phase2b_core(...)` call.
2. `run_phase2b_fixture`: pass `provenance_inputs=None` into its `_run_phase2b_core(...)` call.
3. `_run_phase2b_core`: add parameter `provenance_inputs: ActivationProvenanceInputs | None`, and pass `provenance_inputs=provenance_inputs` + `fixture_execution=fixture_execution` into the `_evaluate_inside_boundary(...)` call.
4. `_evaluate_inside_boundary`: add parameters `provenance_inputs: ActivationProvenanceInputs | None` and `fixture_execution: bool`, and update the `provenance = _build_provenance(...)` call (currently at the "Step 11" block) to pass `ledger=terminal.ledger, inputs=provenance_inputs, fixture_execution=fixture_execution` (the regime args stay `regime_double=regime_double, regime_single=regime_single`).

The post-access consistency call is left EXACTLY as-is in this task (`expected_provenance_checksum=expected_provenance_checksum`). Change C rewires it in Task 4.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_phase2b.py -q`
Expected: PASS — the three new `build_provenance` tests plus every existing phase2b test (fixture path behavior is unchanged: `inputs=None` + `fixture_execution=True` still yields synthetic-empty digests, so `_provenance()` fixtures and the happy/tamper paths are unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/phase2b.py tests/alive/compose/test_phase2b.py
git commit -m "feat(compose): populate Phase-2b provenance digests via typed inputs (Change B)"
```

---

### Task 4: Change C — persisted pre-access cross-check

**Files:**
- Modify: `src/alive/compose/provenance2.py` (`check_post_access_consistency`)
- Modify: `src/alive/compose/phase2b.py` (`_run_phase2b_core`, `_evaluate_inside_boundary`, imports)
- Modify: `tests/alive/compose/test_provenance2.py` (post-access kwargs rename)
- Test: `tests/alive/compose/test_phase2b.py` (persisted-ledger artifact)

**Interfaces:**
- Changes `check_post_access_consistency`: the keyword `expected_provenance_checksum: str` becomes `persisted_pre_access_checksum: str`, and the provenance leg compares `provenance.pre_access_checksum != persisted_pre_access_checksum` (instead of `provenance.self_checksum != expected_provenance_checksum`). Return type and the run-id / request-checksum / result-checksum legs are unchanged.
- Orchestrator: `_run_phase2b_core` records the pre-access subset checksum via `record_pre_access_provenance` BEFORE `claim_access()`; `_evaluate_inside_boundary` reads it back with `terminal.ledger.artifact_sha(PRE_ACCESS_PROVENANCE_ARTIFACT)` and passes it as `persisted_pre_access_checksum`.
- Consumes: `record_pre_access_provenance`, `PRE_ACCESS_PROVENANCE_ARTIFACT` (Tasks 1–2); `_build_provenance` with `regime_*=None` (Task 3).

- [ ] **Step 1: Write the failing test**

Add to `tests/alive/compose/test_phase2b.py`. Change the single-name line `from alive.compose.provenance2 import Phase2bProvenance` to a grouped import that also brings in `PRE_ACCESS_PROVENANCE_ARTIFACT`. Then append:

```python
# ===========================================================================
# Change C: pre-access provenance subset is PERSISTED write-once before access
# ===========================================================================


def test_pre_access_provenance_persisted_in_ledger(tmp_path):
    kit = _make_run(tmp_path)
    res = run_phase2b_fixture(**_fixture_kwargs(kit))
    # The pre-access digest-subset checksum is recorded write-once BEFORE the seal
    # opens, so the post-access provenance leg cross-checks a PERSISTED value.
    persisted = res.ledger.artifact_sha(PRE_ACCESS_PROVENANCE_ARTIFACT)
    assert isinstance(persisted, str) and len(persisted) == 64
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/alive/compose/test_phase2b.py -k pre_access_provenance_persisted -q`
Expected: FAIL (the ledger has no `phase2b_pre_access_provenance` artifact yet — `LedgerError`).

- [ ] **Step 3: Implement Change C**

**(a) `src/alive/compose/provenance2.py` — `check_post_access_consistency`.** Rename the parameter and swap the compared attribute. In the signature change `expected_provenance_checksum: str,` to `persisted_pre_access_checksum: str,`. In the Parameters docstring, replace the `expected_provenance_checksum` entry with:

```
    persisted_pre_access_checksum : str
        The pre-access digest-subset checksum PERSISTED into the write-once
        ledger before access (:func:`record_pre_access_provenance`). The
        provenance leg cross-checks the recomputed subset checksum against this
        persisted value — a real tamper detector, not a self-reference.
```

Replace the provenance-leg comparison:

```python
    if provenance.self_checksum != expected_provenance_checksum:
        return PostAccessStatus.INVALID
```

with:

```python
    if provenance.pre_access_checksum != persisted_pre_access_checksum:
        return PostAccessStatus.INVALID
```

**(b) `tests/alive/compose/test_provenance2.py` — update the post-access callers** to the new keyword (three sites). In `_consistent_post_access()`:

```python
        provenance=_provenance(),
        persisted_pre_access_checksum=_provenance().pre_access_checksum,
```

In `test_post_access_provenance_checksum_mismatch_returns_invalid`:

```python
    kwargs["persisted_pre_access_checksum"] = "DIFFERENT-provenance-checksum"
```

In `test_post_access_never_raises_on_detected_inconsistency`:

```python
    kwargs["persisted_pre_access_checksum"] = "V"
```

**(c) `src/alive/compose/phase2b.py` — imports.** Add `record_pre_access_provenance` and `PRE_ACCESS_PROVENANCE_ARTIFACT` to the existing `from alive.compose.provenance2 import (...)` block.

**(d) `_run_phase2b_core` — record the pre-access subset before access.** After the Step-4 intent block (`preflight_checksums = {...}`) and BEFORE the Step-5 `terminal.claim_access()`, insert:

```python
    # --- Change C: persist the pre-access provenance subset BEFORE the seal opens.
    # The subset excludes post-access result/terminal checksums, so it is fully
    # computable here; recording it write-once lets the post-access check
    # cross-verify a PERSISTED value instead of a self-reference (CLAUDE.md#provenance).
    audit_reference = str(audit_path) if audit_path is not None else "in-memory"
    pre_access_provenance = _build_provenance(
        bundle=frozen_bundle,
        pair_manifest=pair_manifest,
        config=config,
        audit_reference=audit_reference,
        regime_double=None,
        regime_single=None,
        git_clean=git_clean,
        ledger=ledger,
        inputs=provenance_inputs,
        fixture_execution=fixture_execution,
    )
    record_pre_access_provenance(ledger=ledger, provenance=pre_access_provenance)
```

Then change the `_evaluate_inside_boundary(...)` call so it passes the SAME `audit_reference` local instead of recomputing it inline — replace the argument line
`audit_reference=str(audit_path) if audit_path is not None else "in-memory",`
with
`audit_reference=audit_reference,`.

**(e) `_evaluate_inside_boundary` — read the persisted value and pass it to the check.** After `expected_provenance_checksum = provenance.self_checksum`, add:

```python
    # Change C: cross-check against the PERSISTED pre-access subset (recorded
    # write-once before access), not the in-memory record.
    persisted_pre_access_checksum = terminal.ledger.artifact_sha(PRE_ACCESS_PROVENANCE_ARTIFACT)
```

In the `check_post_access_consistency(...)` call, replace the argument
`expected_provenance_checksum=expected_provenance_checksum,`
with
`persisted_pre_access_checksum=persisted_pre_access_checksum,`.

Leave `expected_provenance_checksum` (the full `self_checksum`) in place for the terminal/result reporting (`_terminal_payload` and `Phase2bResult.provenance_checksum` still report the COMPLETE record's checksum).

**Consistency note (verify while implementing):** the pre-access build (in `_run_phase2b_core`) and the post-access build (in `_evaluate_inside_boundary`) must produce an identical pre-access subset. They share `bundle`, `pair_manifest`, `config`, `audit_reference`, `git_clean`, `ledger`, `inputs`, `fixture_execution`; only the `regime_*` args differ (`None` vs real), and those are excluded from the subset. So on an untampered run the recomputed subset checksum equals the persisted one ⇒ `OK`; the existing tamper test injects a provenance whose pre-access subset differs ⇒ `INVALID`.

- [ ] **Step 4: Run to verify pass + regression**

Run:
```bash
uv run pytest tests/alive/compose/test_provenance2.py tests/alive/compose/test_phase2b.py -q
```
Expected: PASS — including the new `test_pre_access_provenance_persisted_in_ledger`, the updated post-access tests, the unchanged `test_happy_path_complete_terminal_and_one_access` (OK path: recomputed subset == persisted), and the unchanged `test_provenance_tamper_yields_invalid` (INVALID path: now caught by the persisted cross-check, tampering `processed_sha256`, a pre-access-subset field).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/provenance2.py src/alive/compose/phase2b.py \
        tests/alive/compose/test_provenance2.py tests/alive/compose/test_phase2b.py
git commit -m "feat(compose): persisted pre-access provenance cross-check (Change C)"
```

---

## Post-implementation verification (whole change B+C)

- [ ] Run the full compose suite + lint:
```bash
uv run pytest tests/alive/compose -q
uv run ruff check src tests && uv run ruff format --check src tests
```
Expected: all green. Then gate this increment with the `science-dev` loop profile (per the standing loop-gating practice).
- [ ] Confirm both `TODO(activation)` markers are gone from `src/alive/compose/phase2b.py`:
```bash
grep -n "TODO(activation)" src/alive/compose/phase2b.py || echo "no activation TODOs remain"
```
Expected: `no activation TODOs remain`.

## Out of scope (deferred)

- The Phase-2a / pod assembly that constructs a real `ActivationProvenanceInputs` from the live run environment + committed activation evidence (data-card processed digest, ESM feature-bank digest, `gears_cpa_dependency_lock.json`, resolved device/precision, git SHA). This plan defines the typed object and the population logic; the sealed run wires the real producer on the A100 (pod runbook).
- Any change to the comparator family, metric, verdict rules, split, or seal-open count — those are fixed by the upstream spec (`docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md` §10.5–§10.6).
- The `phase2b.py` module-docstring stale wording cleanup ("BLOCKED candidate config makes this fail") — a cosmetic follow-up, not a claim change; fold it in only if trivially adjacent while editing.

## Notes for the executor

- `Phase2bProvenance` is a frozen dataclass; `cached_property` works on it (the existing `self_checksum` proves this), so `pre_access_checksum` is fine.
- The pre-access record MUST land before `claim_access()` / `evaluate_sealed_once` — that ordering is the whole point of Change C. Keep the `record_pre_access_provenance` call in `_run_phase2b_core` strictly before Step 5.
- Do not change what `Phase2bResult.provenance_checksum` and `_terminal_payload` report (they carry the COMPLETE record's `self_checksum`); Change C only alters which value the CONSISTENCY check compares.
- After all tasks: the two `TODO(activation)` markers are resolved and the provenance leg of the post-access check is a genuine, persisted, tamper-detecting comparison — not "all integrity verified" (the result-checksum leg remains structurally post-access by design; spec §3).
