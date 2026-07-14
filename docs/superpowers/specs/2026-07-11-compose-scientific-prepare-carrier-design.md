# COMPOSE production driver — Scientific PREPARE carrier design

> **Status:** IMPLEMENTED + MERGED on `main` (carrier B-boundary); scientific activation remains BLOCKED · 2026-07-13
> **Protocol:** `COMPOSE-K562-v1` (ACTIVE). Opens **no** seal; the COMPOSE seal remains UNOPENED.
> **Sub-project:** completion of driver sub-project **C**'s deferred scientific carrier path.
> **Authoritative parents:** driver spec `specs/2026-07-07-compose-production-driver-design.md`;
> governance `CLAUDE.md` §3/§4; readiness `COMPOSE-SEAL-READINESS.md` row C + critical-path
> step 4.

---

## 0. Scope {#scope}

**In scope.** Replace the `UnsupportedModeError` raised for `mode="scientific"` by
`load_run_spec_carrier` with a fail-closed scientific reconstruction path. The path:

1. validates the scientific block's exact nested schema and every non-sealed evidence byte;
2. proves the runtime repository is clean **and** at the exact `approved_git_sha`;
3. reconstructs the existing five carrier values plus a complete scientific runtime surface;
4. binds the scientific sealed-input declaration to the owner-approved attestation without opening
   the source;
5. passes the captured `EnvironmentInfo` into Phase-2a and supplies a typed
   `ActivationProvenanceInputs` to Phase-2b; and
6. demonstrates hermetically that the current CLI reaches and fails closed at sub-project B's
   missing scientific adapter-version boundary, with no store, seal access, or run-produced output.

This sub-project makes the **carrier and runtime identity wiring** production-capable. It does not
claim that the real Norman stage-1 corpus or real GEARS/CPA execution environment is ready.

**Out of scope.**

- Real raw/processed Norman → stage-1 artifact production (pod PREPARE).
- Sub-project B's versioned `adapter_version` manifest and real `gears`/`cpa` workers.
- A green scientific Phase-2a/D2/Phase-2b integration run. The current call graph resolves worker
  identity before Phase-2a activation and D2; therefore this is impossible until B ships.
- Opening or materializing the sealed source, constructing a `ComposeOutcomeStore`, or running a
  real scientific fit.
- Freezing the final GU roster value. Nevertheless, §7 makes the GU receipt→response gene-order
  equality a release blocker so completion of B alone cannot make the sealed path ready.

**Non-negotiable invariants.** No `ComposeOutcomeStore` is constructed; no sealed AnnData / obs / X /
layer is opened or materialized; no §4.3 guard is weakened, bypassed, or mocked; runtime Git state is
measured independently in every CLI process; fixture **serialized artifacts and fixture execution
semantics** remain unchanged.

---

## 1. Current state and gaps {#current}

- `load_run_spec_carrier` accepts only fixture mode and reconstructs five fields:
  `spec_path`, `phase2a_inputs`, `dev_store_audit`, `response_artifact`, `sealed_outcome`.
- `load_resolved_run_spec` validates the scientific block's top-level key roster and
  `sealed_input`, but does **not** validate the nested `activation_evidence` or
  `dependency_manifest` contracts.
- Scientific consumers also require activation, runtime Git state, data paths, environment and
  Phase-2b provenance. In particular, `run_phase2b` requires the dataclass
  `ActivationProvenanceInputs`, not an arbitrary mapping.
- `phase2a_cmd` currently omits `environment=` when it dispatches `run_phase2a`; this would persist
  the fixture placeholder (`git_commit="UNKNOWN"`) into a scientific ledger and later conflict with
  Phase-2b provenance.
- `_assemble_adapters` runs before `run_phase2a`. Until B supplies a scientific adapter-version
  manifest, the first full-CLI scientific failure is therefore the B identity boundary—not D2.
- The committed fixture development audit declares `source_kind="synthetic_fixture"`; scientific
  Phase-2a correctly requires `source_kind="audited_unsealed"`. A test must not relabel the existing
  fixture artifact in place or claim that fixture execution is scientific evidence.

---

## 2. Closed schemas and trust boundaries {#schemas}

### 2.1 Scientific block

The exact nested schema is:

```text
scientific = {
  activation_evidence: {
    owner: non-empty string,
    requirements: {
      <activation requirement>: {
        path: absolute normalized path,
        sha256: "sha256:<64 lowercase hex>"
      }
    }
  },
  dependency_manifest: {
    path: absolute normalized path,
    sha256: <64 lowercase hex>
  },
  device: non-empty string,
  precision: non-empty string,
  sealed_input: {
    source_path: absolute normalized lexical path,
    expected_file_sha256: <64 lowercase hex>,
    snapshot_id: non-empty string,
    audit_path: absolute normalized lexical path
  }
}
```

`run_spec.py::_validate_mode_block` is expanded; nested-schema validation is no longer out of scope.
For activation evidence and the dependency manifest it must enforce the same approved-root policy as
other pre-seal artifacts: absolute normalized path, lexical containment, existing regular file,
non-symlink final component, and actual byte-SHA equality. These are non-sealed inputs and may be read.

After loading the config, the carrier requires
`activation_evidence.requirements.keys() == config.activation_requirements` exactly. No missing,
extra, duplicate-after-parsing, relative, cwd-dependent, or outside-root evidence path is accepted.
`ActivationRecord` is then constructed with:

- `owner` from `activation_evidence.owner`;
- `approved_protocol` / `approved_phase` from the loaded config;
- `evidence_hashes` and `evidence_files` from the exact requirement roster.

`assert_scientific_mode_allowed` re-validates status, blockers, owner, protocol/phase, roster, digest
syntax, evidence bytes and config-bound report lineage.

### 2.2 Sealed-input attestation equality (no source access)

The already-byte-verified `approved_sealed_input_attestation` is parsed before any stage dispatch.
Pure mapping/path-string validation must prove:

- `sealed_input.source_path == attestation.canonical_source_path`;
- `sealed_input.expected_file_sha256 == attestation.expected_source_file_sha256`;
- `sealed_input.snapshot_id == attestation.snapshot_id` in scientific mode;
- `attestation.pair_index_file_sha256` equals the loader-verified pair-index file SHA;
- pair-index source/row digests equal the attested source/row digests; and
- `sealed_input.audit_path` equals the canonical protocol-global path
  `.compose-protocol-seal-<sha256(protocol UTF-8)>.jsonl` directly under the approved artifacts root.

The source path is checked lexically only at this stage: no `resolve`, `stat`, hash, AnnData parse or
source open is permitted. Source node identity and byte integrity remain Phase-2b-after-confirmation
work. This closes the current gap where source digest equality is checked but canonical path,
snapshot and protocol-global audit equality are not. This prevents a new run directory from minting a fresh
scientific seal boundary for the same registered protocol; fixtures retain their run-local audit.

### 2.3 Runtime Git/environment identity

The CLI resolves a frozen `ScientificRuntimeContext` for **each** independent scientific command:

```text
ScientificRuntimeContext {
  repo_root: canonical trusted repository root,
  head_sha: full 40- or 64-character lowercase hex,
  git_is_clean: bool,
  environment: EnvironmentInfo  # includes config.registered_seeds exactly
}
```

The repository root is an out-of-band CLI/runtime configuration, never selected by the run spec.
Resolution must use argv-based subprocess calls (no shell) and fail closed unless:

1. `git rev-parse --show-toplevel` equals the trusted canonical repository root;
2. `git rev-parse HEAD == spec.approved_git_sha` exactly;
3. `git status --porcelain=v1 --untracked-files=all --ignore-submodules=none` is empty;
4. the SHA has the exact full-hex form; and
5. environment capture succeeds from that same repository/runtime; and
6. `environment.registered_seeds == config.registered_seeds` exactly and is non-empty.

No `--git-is-clean` user assertion is accepted. Run artifacts must live outside the repository or in
an already-ignored location; the clean-tree check receives no run-specific exclusion. Every command
rechecks the state, so a change between Phase-2a, preflight and Phase-2b fails closed.

The public signature becomes
`load_run_spec_carrier(..., trusted_repo_root: Path | None = None)`. Scientific mode requires the
out-of-band root and constructs `ScientificRuntimeContext` internally **after** loading the spec and
config; it never accepts a caller-asserted context or clean boolean. Fixture mode requires
`trusted_repo_root is None`, preserving its disk-only behavior and preventing ambiguous mixed-mode
construction. The CLI adds/threads the trusted root only for scientific commands.

---

## 3. Carrier contract {#contract}

Keep one `RunSpecCarrier` type, but make it a discriminated, construction-validated type rather than
an arbitrary combination of optional fields. It gains `mode` plus six scientific fields:

| field | fixture | scientific source / type |
|---|---|---|
| existing five DATA fields | required | required; same schema deserializers, scientific sealed variant |
| `mode` | `"fixture"` | `"scientific"` |
| `activation_record` | `None` | validated `ActivationRecord` |
| `git_is_clean` | `None` | exactly `True`, from `ScientificRuntimeContext` |
| `environment` | `None` | `ScientificRuntimeContext.environment` (`EnvironmentInfo`) |
| `data_card_path` | `None` | verified `pre_seal.data_card.path` |
| `raw_asset_path` | `None` | verified `pre_seal.raw_asset.path` |
| `provenance_inputs` | `None` | `ActivationProvenanceInputs` |

`RunSpecCarrier.__post_init__` enforces exact population by `mode`: all six scientific fields are
`None` in fixture mode and all six have their exact runtime types in scientific mode. Use private
mode-specific constructors so a partially populated scientific carrier cannot exist.

The scientific `sealed_outcome` contains only the fields `_build_sealed_store` consumes:
split manifest, pair index, pair-index manifest, declared source path/SHA, perturbation column and
combo separator. It never carries the fixture corpus attestation triple. The owner attestation is
validated by §2.2 and remains a pre-seal artifact; store construction remains Phase-2b's sole site.

---

## 4. Typed provenance and Phase-2a environment plumbing {#provenance}

The carrier constructs `ActivationProvenanceInputs` only through the existing
`build_activation_provenance_inputs` helper:

| helper argument | authoritative source |
|---|---|
| `processed_path` | `pre_seal.raw_asset.path` only if the validated data card identifies that exact file as the processed analysis asset |
| `feature_bank_path` | `pre_seal.feature_bank.path` |
| `dependency_lock_path` | `scientific.dependency_manifest.path` |
| `gears_requirements_path` | `worker_blocks.gears.requirements_lock.path` |
| `cpa_requirements_path` | `worker_blocks.cpa.requirements_lock.path` |
| `environment` | `ScientificRuntimeContext.environment` |
| `device`, `precision` | scientific block |

This pins the actual dataclass fields: processed/feature/dependency digests, GEARS/CPA revisions,
Python/platform/device/precision and Git commit. Config/data-card/raw/sequence/expected hashes do not
belong in this object; their existing spec/ledger paths remain the single sources of truth.
If `raw_asset` is genuinely a raw rather than processed asset in the real PREPARE output, the final
schema must add a separately verified `processed_asset` path+SHA field; it may not silently record a
raw-file digest as `processed_sha256`.

`phase2a_cmd` must pass `environment=run_spec.environment` on the scientific call to `run_phase2a`.
Phase-2b reconstructs the carrier in its own process and passes its typed `provenance_inputs`; the
existing provenance validator then requires Python/platform/Git to match the Phase-2a ledger. This
also proves that `approved_git_sha`, runtime HEAD, ledger environment and Phase-2b provenance agree.
The runtime resolver receives the config-validated seed roster and passes it unchanged to
`capture_environment`; an empty placeholder roster is forbidden in scientific mode.

---

## 5. Assembly order {#assembly}

For scientific mode:

1. Fully load and validate the canonical `ResolvedRunSpec` and all declared pre-seal bytes.
2. Validate the nested scientific block (§2.1) and sealed attestation equality (§2.2).
3. Load the config, then resolve the runtime context from the trusted repository root — capturing
   `EnvironmentInfo` with the config's registered seeds — and validate it against `approved_git_sha`
   (§2.3); no asserted context is accepted.
4. Build and validate the `ActivationRecord` from the loaded config.
5. Reuse the existing phase2a/dev-store/response deserializers and the scientific sealed-data
   deserializer. Validate deserialized schema/checksum fidelity as today.
6. Build typed `ActivationProvenanceInputs` (§4).
7. Construct the carrier through its scientific-only constructor; `__post_init__` rejects partial or
   mixed-mode state.
8. CLI stage dispatch continues unchanged except for scientific environment plumbing.

This work hashes only declared non-sealed files. It does not open the sealed source or construct any
outcome store.

---

## 6. Hermetic tests and honest boundary claims {#testing}

Test support lives under `tests/` rather than changing the production fixture builder's fixture
semantics. It may reuse deterministic serializers/content generators, but produces separate
mode-specific artifacts:

- the existing fixture artifact keeps `source_kind="synthetic_fixture"` byte-for-byte;
- a scientific-carrier test artifact uses `source_kind="audited_unsealed"`, an exact scientific
  block, and a synthetic **test-only** activated config with all activation blockers resolved;
- config-bound activation reports embed that test config's actual SHA and protocol;
- no test-only adapter version is admitted on the scientific identity path.

Required tests:

1. **Scientific schema and carrier assembly:** all fields and exact types; ActivationRecord roster;
   typed provenance values; response checksum fidelity; environment/head agreement.
2. **Discriminated shape:** fixture has all scientific fields `None`; scientific requires all;
   partial/mixed construction fails.
3. **Git identity negatives:** dirty tracked, untracked, submodule-dirty, wrong HEAD, malformed SHA,
   wrong repo root, absent Git and user-supplied-context mismatch all reject.
4. **Activation/dependency negatives:** missing/extra requirement, wrong digest, relative/outside-root,
   symlink/non-regular file, malformed dependency manifest and stale config-bound report reject.
5. **Sealed declaration negatives:** source path, source SHA, snapshot ID, pair-index SHA, row identity
   or audit destination mismatch reject without source access.
6. **Environment/provenance plumbing:** scientific Phase-2a receives the exact `EnvironmentInfo` and
   never writes the `UNKNOWN` placeholder; typed Phase-2b inputs agree with the persisted ledger.
7. **Current B boundary:** full scientific CLI assembly reaches `assemble_execution_identity_lock`,
   fails on the absent committed scientific `adapter_version`, creates no run-produced file/store,
   and leaves the seal/audit untouched. The test does **not** claim D2 was reached.
8. **Structural seal safety:** the sole store-construction site and §4.3 structural tests remain
   unchanged and green.

After B ships, add a separate no-seal integration test covering scientific Phase-2a → D2 report →
preflight binding. That future test must stop before `_build_sealed_store`; it is not a DoD item for
this B-blocked sub-project.

---

## 7. Release blockers and follow-ups {#release}

Completion of this carrier sub-project is **not** seal readiness. The following remain mandatory:

1. B: committed versioned adapter manifest, real workers, immutable environments and integration.
2. Pod PREPARE: real Norman stage-1 artifact production and reviewed evidence.
3. GU: the roster's `full_var_order_sha256` must equal the response/fit-role `gene_order_sha256`
   (both digest the full `U_full` gene order) with matching raw-data identity — this is the coherent
   gene-order binding. The receipt's `ordered_roster_sha256` digests the `R_gears` **subset** (⊆
   `U_full`) and must **not** be used for this check, since a subset digest can never equal the full
   order digest. The receipt already binds `full_var_order_sha256`, `response_artifact_sha256`, and
   `fit_artifact_content_sha256`; bind this equality into the final ResolvedRunSpec/execution identity
   or prove it transitively via those already-bound artifact SHAs plus an explicit pre-seal verifier.
   B may not make the scientific path seal-ready while this is absent.
4. Independent review of the exact clean Git SHA and regenerated activation evidence.

---

## 8. Definition of done {#dod}

- Scientific nested schemas, evidence paths and sealed-attestation equality are fail-closed.
- Every scientific CLI process proves clean tree **and exact HEAD equality** to `approved_git_sha`.
- The discriminated carrier cannot represent a partial/mixed scientific state.
- Phase-2a records the real `EnvironmentInfo`; Phase-2b receives a real
  `ActivationProvenanceInputs`; registered seeds equal the config exactly and survive ledger
  write/read; ledger/environment equality is tested.
- Current full CLI path fails exactly at B's missing scientific adapter version, with zero
  run-produced artifact, zero store construction and zero sealed access; no false D2 claim is made.
- Existing fixture serialized artifacts and execution semantics remain unchanged.
- Focused driver tests, full Compose suite, Ruff check/format-check and structural seal-safety tests
  pass with caches/bytecode disabled where applicable.
- No real data access, pod/GPU work, external dependency fetch, scientific fit or seal opening occurs.
