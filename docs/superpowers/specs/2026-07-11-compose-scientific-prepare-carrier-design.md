# COMPOSE production driver — Scientific PREPARE carrier design

> **Status:** DESIGN (awaiting owner spec review) · 2026-07-11
> **Protocol:** `COMPOSE-K562-v1` (ACTIVE). Opens **no** seal; the COMPOSE seal remains UNOPENED.
> **Sub-project:** completion of driver sub-project **C**'s deferred scientific carrier path.
> **Authoritative parents:** driver spec `specs/2026-07-07-compose-production-driver-design.md`
> (its §0 "Out of scope" deferred exactly this); governance `CLAUDE.md` §3/§4; readiness
> `COMPOSE-SEAL-READINESS.md` row C + critical-path step 4.

---

## 0. Scope {#scope}

**In scope.** Replace the `UnsupportedModeError` raised for `mode="scientific"` at
`src/alive/compose/driver/carrier_loader.py:161-166` with a scientific branch of
`load_run_spec_carrier` that reconstructs a `RunSpecCarrier` from an already-schema-validated
scientific `ResolvedRunSpec`, exposing the five existing carrier fields **plus** the five
scientific attributes the driver stages read. Add a hermetic, MacBook-runnable **scientific
no-seal assembly test** that verifies activation / provenance / D2-report wiring and the precise
point at which the path fails closed pending sub-project B.

**Out of scope (deferred, with rationale in §7).**
- Real raw-Norman → stage-1 artifact production (that is the pod PREPARE sub-project; here the
  synthetic stage-1 corpus stands in, exactly as the fixture path already does).
- Sub-project B's versioned `adapter_version` manifest for the real `gears`/`cpa` workers. The
  scientific `ExecutionIdentityLock` assembly at `preflight_cmd.py:434` fails closed until B ships;
  this design **asserts** that boundary rather than papering over it.
- Binding GU's `ordered_roster_sha256` into the scientific `ResolvedRunSpec` schema (§7.2).
- Any change to `load_resolved_run_spec` schema validation — it **already** validates the
  scientific block (`run_spec.py:645-684`); only carrier *reconstruction* is missing.

**Non-negotiable invariants.** No `ComposeOutcomeStore` constructed; no AnnData / obs / X / layer
materialization (digest-only `sha256_file`); no §4.3 code guard weakened, bypassed, or mocked; the
fixture path stays byte-for-byte unchanged.

---

## 1. Current state {#current}

- `load_run_spec_carrier(spec_path, *, approved_artifacts_root) -> RunSpecCarrier`
  (`carrier_loader.py:121-125`) peeks the mode and, for anything other than `"fixture"`, raises
  `UnsupportedModeError` (`:161-166`, a `RunSpecError` subclass → CLI exit 10). Fixture mode builds
  a **5-field** frozen `RunSpecCarrier` (`carrier_loader.py:83-118`): `spec_path`,
  `phase2a_inputs` (`Phase2aInputs`), `dev_store_audit`, `response_artifact`, `sealed_outcome`.
- `load_resolved_run_spec` already accepts and validates a scientific spec: mode-block exclusivity
  and key rosters `_SCIENTIFIC_BLOCK_KEYS = {activation_evidence, dependency_manifest, device,
  precision, sealed_input}` and `_SCIENTIFIC_SEALED_INPUT_KEYS = {source_path, expected_file_sha256,
  snapshot_id, audit_path}` (`run_spec.py:179-190`, `:645-684`). The 14 pre-seal path fields it
  byte-verifies are `PRE_SEAL_PATH_FIELDS` (`run_spec.py:100-115`).
- The driver stages read **five scientific-only attributes off the carrier that the current
  `RunSpecCarrier` does not carry**:
  - `phase2a_cmd.py:215-218` — `run_spec.activation_record`, `run_spec.git_is_clean`,
    `run_spec.data_card_path`, `run_spec.raw_asset_path` (direct attribute access, scientific branch
    only; the fixture branch never reaches these lines).
  - `phase2b_cmd.py:334-336` — `run_spec.activation_record`, `git_is_clean` (via
    `_resolve_git_clean` → `run_spec.git_is_clean`), `getattr(run_spec, "provenance_inputs", None)`.
  - `preflight_cmd.py:555` — `getattr(run_spec, "git_is_clean", None)` (required `True` in
    scientific mode).

---

## 2. The scientific carrier contract {#contract}

The scientific branch returns a `RunSpecCarrier` populated with **ten** attributes: the five
existing fields (assembled by the SAME private deserializers the fixture path uses, since the
declared pre-seal artifacts have identical on-disk schemas), plus five scientific attributes.

| attribute | type | source (all from already-SHA-verified declared artifacts) | consumer |
|---|---|---|---|
| `spec_path` | `Path` | the spec | all stages |
| `phase2a_inputs` | `Phase2aInputs` | `spec.pre_seal["phase2a_inputs"].path` (`_load_phase2a_inputs`) | phase2a |
| `dev_store_audit` | `Mapping` | `development_outcome_source`+`_manifest` (`_load_dev_store_audit`) | phase2a |
| `response_artifact` | `Mapping` | `response_artifact` path (`_load_response_artifact`; checksum-fidelity gate retained) | phase2a/preflight/phase2b |
| `sealed_outcome` | `Mapping` | `pair_index_manifest`+`pair_manifest`+scientific `sealed_input` (§2.1) | phase2b only |
| `activation_record` | `ActivationRecord` | `ActivationRecord` assembled from the scientific block's `activation_evidence` (owner + requirement→evidence roster) with `approved_protocol`/`approved_phase` from `config`, validated by `assert_scientific_mode_allowed` (`config2.py:1195`) | phase2a/phase2b |
| `git_is_clean` | `bool` | runtime git state resolved by the driver (scientific requires exactly `True`) | phase2a/phase2b/preflight |
| `data_card_path` | `Path` | `spec.pre_seal["data_card"].path` | phase2a |
| `raw_asset_path` | `Path` | `spec.pre_seal["raw_asset"].path` | phase2a |
| `provenance_inputs` | `Mapping` | the CLAUDE.md §4.2 provenance bundle (§3.2) | phase2b |

The five scientific attributes are added to `RunSpecCarrier` as `Optional[...] = None` fields
(owner-approved carrier shape). The fixture path leaves them `None`; the fixture builder and the
four fixture deserializers are unchanged, so every existing fixture test remains byte-identical.

**Signature.** `load_run_spec_carrier` gains one keyword argument, `git_is_clean: bool | None =
None`, resolved by the CLI (`_build_run_spec_carrier`, `cli.py:194-214`) from the runtime git state
and threaded in — the loader stays a pure disk-loader with no git subprocess side-effect (`git_is_clean`
is a runtime fact about the working tree vs `approved_git_sha`, not derivable from the spec). The
fixture branch ignores it (carrier field stays `None`; fixture consumers hardcode `git_clean=True`).
The scientific branch requires it to be an actual `bool` and fails closed otherwise.

### 2.1 Scientific `sealed_outcome` differs from fixture {#sealed}

The fixture `sealed_outcome` carries a fixture-only attestation triple (`corpus_id`,
`source_sha256`, `builder_code_sha256`) sourced from the committed `FIXTURE_CORPUS_V1` constant
(`carrier_loader.py:363-365`). The scientific path **must not** carry that triple: phase2b builds a
plain `ComposeOutcomeStore` for scientific (`phase2b_cmd.py:493-498`), not the allowlisted
`build_fixture_outcome_store`. The scientific `sealed_outcome` binds the snapshot-scoped
`sealed_input` (`source_path`, `expected_file_sha256`, `snapshot_id`, `audit_path`) and the
`approved_sealed_input_attestation` instead. Store construction remains phase2b's sole
responsibility; the carrier assembles bindings only.

---

## 3. Assembly algorithm (the scientific branch) {#assembly}

All inputs are the already-byte-verified declared artifacts from `load_resolved_run_spec`; the
branch performs **no** new digesting of raw data beyond `sha256_file` on declared paths and
constructs **no** store.

1. **Guard.** Confirm `mode == "scientific"`; reject if any fixture block/corpus/source-digest is
   present (belt-and-suspenders over the schema-level mode-block exclusivity).
2. **Five base fields.** Reuse `_load_phase2a_inputs`, `_load_dev_store_audit`,
   `_load_response_artifact`, and a scientific `_load_sealed_outcome` variant (§2.1).
3. **`ActivationRecord`.** Assemble and validate via `assert_scientific_mode_allowed`
   (`config2.py:1195`), which requires (`config2.py:1250-1261`, `:1271-1337`): non-empty `owner`;
   `approved_protocol == config.protocol`; `approved_phase == config.phase`; `evidence_hashes` keyset
   == `config.activation_requirements` exactly; each digest `sha256:`-prefixed; each declared file's
   bytes hash to its digest. Field sourcing: `owner`, `evidence_hashes`, and `evidence_files` come
   from the scientific block's `activation_evidence` (which carries the `owner` plus the
   requirement→`{path, sha256:digest}` roster — the exact sub-key names are pinned in the plan against
   the `activation_evidence` block schema); `approved_protocol`/`approved_phase` are taken from
   `config` (the validator re-checks equality as the guard). Fail closed on any mismatch. **Schema
   note:** the scientific `activation_evidence` block must expose `owner`; today `run_spec.py`
   (`:183`) validates only the scientific block's top-level keys, so the plan adds the
   `owner`-presence check where the carrier reads it.
4. **`git_is_clean`.** Take the `git_is_clean` kwarg (threaded from the CLI's runtime git check, §2);
   require an actual `bool` in scientific mode and fail closed otherwise. Scientific requires exactly
   `True` downstream (`preflight_cmd.py:544-560`, `phase2b_cmd.py:737-741`).
5. **`data_card_path` / `raw_asset_path`.** The declared `spec.pre_seal["data_card"].path` and
   `spec.pre_seal["raw_asset"].path`.
6. **`provenance_inputs`.** Assemble the mapping in the exact shape `run_phase2b`'s `provenance_inputs`
   parameter expects (`phase2b_cmd.py:336`) — its precise key names are pinned in the plan against
   `run_phase2b`'s signature — carrying the CLAUDE.md §4.2 provenance fields already validated on the
   spec: `config_digest`, `data_card_digest`, `raw_or_source_digest`, `sequence_mapping_digest`, the
   seven `expected_hashes`, the scientific block's `dependency_manifest` / `device` / `precision`, and
   `approved_git_sha`. (The runtime `execution_id` is computed downstream, not stored — `run_spec.py`
   §2.1; the carrier supplies its inputs only.)

---

## 4. Scientific stage-1 test data {#fixture}

Extend `src/alive/compose/driver/fixture_builder.py` (which "faithfully mirrors scientific stage-1
assembly", `fixture_builder.py:7`) to also emit a **scientific-mode** `ResolvedRunSpec` + scientific
block pointing at the **same synthetic stage-1 artifacts** it already builds. One synthetic corpus,
two spec modes (DRY). The scientific variant adds: the `activation_evidence` roster (synthetic
evidence files whose bytes hash to their declared `sha256:` digests, keyed to
`config.activation_requirements`), a `dependency_manifest`, `device`, `precision`, a snapshot-scoped
`sealed_input`, and an `approved_sealed_input_attestation`. This keeps the no-seal test hermetic and
CPU-only — no Norman data, no gears/cpa env. The synthetic worker blocks are built exactly as far as
they can go without B's versioned adapter manifest (§5).

---

## 5. Governance & fail-closed invariants {#governance}

- **No store, no materialization.** The scientific branch constructs no `ComposeOutcomeStore` and
  reads no obs/X/layer — digest-only `sha256_file` on declared paths. Store construction stays the
  sole responsibility of phase2b's `_build_sealed_store` (`phase2b_cmd.py:421-498`), structurally
  asserted by `test_seal_safety_structure.py`.
- **§4.3 guards untouched.** `outcome_store.py`, `gates.py`, `freeze.py`, `preflight.py::run_preflight`,
  `io.atomic_write_once`, `durable.py`/`terminal.py` are not modified. `run_preflight` stays
  structurally outcome-free.
- **Structural fixture↔scientific separation.** The scientific path rejects the fixture attestation
  triple and vice versa; mode-block exclusivity is enforced at the schema (`run_spec.py:452-459`)
  and re-asserted in the branch. "mode as a mutable marker" is not treated as a security boundary
  (driver spec §4).
- **B fail-closed boundary — asserted, not bypassed.** The scientific `ExecutionIdentityLock`
  assembly (`assemble_execution_identity_lock`, invoked at `preflight_cmd.py:434` via `_worker_identity`)
  requires a versioned `adapter_version` manifest that sub-project B has not yet shipped (driver spec
  §5/§415-417). The scientific path deliberately does **not** reuse the fixture stub adapter
  (`_STUB_ADAPTER_VERSION`) to force a green run. The no-seal test asserts the path fails closed at
  exactly this boundary with an explicit marker for B.

---

## 6. Testing {#testing}

Mirror `tests/alive/compose/driver/test_carrier_loader.py` (build → load → deep-equal the consumed
surface). New tests:

1. **Scientific carrier assembly.** Build the scientific fixture (§4), `load_run_spec_carrier`,
   assert all ten attributes are populated: base five deep-equal the built bundle (incl. the
   response-space checksum-fidelity gate); `activation_record` validates and its evidence roster ==
   `config.activation_requirements`; `git_is_clean is True`; `data_card_path`/`raw_asset_path` are
   the declared files; `provenance_inputs` carries the §4.2 keys.
2. **Fixture stays inert.** A fixture-mode carrier still has the five scientific attributes `None`;
   all existing `test_carrier_loader.py` assertions unchanged.
3. **Fail-closed negatives.** Scientific spec with a fixture block/corpus/source-digest → rejected;
   activation evidence keyset ≠ `config.activation_requirements` → rejected; an evidence file whose
   bytes don't match its digest → rejected; `git_is_clean=False` → rejected downstream.
4. **No-seal assembly wiring (DoD gate 5).** A hermetic test that drives the scientific carrier
   through activation/provenance/D2-report wiring **without opening a store**, and asserts the path
   fails closed at the B worker-identity boundary (§5) — never reaching sealed access.
5. **Structure.** `test_seal_safety_structure.py` still passes: no new store-construction site.

Full compose suite must stay green.

---

## 7. Scope decisions (owner-confirmed) {#decisions}

1. **Carrier shape = Optional fields on the existing `RunSpecCarrier`** (not a separate type).
   Matches the existing consumer contract; one type, one loader; fixture byte-unchanged.
2. **GU `ordered_roster_sha256` — deferred.** It is not in the current `ResolvedRunSpec` schema, is a
   B/worker-side concern, and GU's scientific output bridge is itself Probe-A-blocked. Binding it now
   would be a premature schema change that widens the run-identity surface. Left as a B follow-up.
3. **B boundary asserted, not stubbed.** Scope is "carrier loader + no-seal assembly test up to the
   B boundary." No fixture stub adapter on the scientific path.

---

## 8. Out of scope / follow-ups {#followups}

- Sub-project B: versioned `adapter_version` manifest for real `gears`/`cpa` workers → unblocks the
  scientific `ExecutionIdentityLock` assembly and a full green scientific e2e.
- Pod PREPARE: real raw-Norman → stage-1 artifact production.
- GU roster binding into the scientific spec (gated on Probe A + a schema-evolution decision).

---

## 9. Definition of done {#dod}

- `load_run_spec_carrier` reconstructs a ten-attribute scientific carrier from a schema-validated
  scientific `ResolvedRunSpec`; no `UnsupportedModeError` for well-formed scientific specs.
- `RunSpecCarrier` gains five `Optional` scientific fields; fixture path byte-unchanged.
- `fixture_builder.py` emits a scientific-mode spec variant over the same synthetic corpus.
- Tests §6.1–§6.5 pass; full compose suite green; ruff clean.
- No store constructed, no obs/X materialized, no §4.3 guard touched, no seal opened.
