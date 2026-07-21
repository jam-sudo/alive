# COMPOSE Scientific PREPARE Carrier — Implementation Plan

> **Status update (2026-07-19): IMPLEMENTED + MERGED to the B-boundary.** 아래 task는 as-built
> record이며 current work queue가 아니다. Scientific execution remains RELEASE-BLOCKED.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Each task is written test-first (TDD: RED → GREEN →
> REFACTOR, one behavior per commit) — write the failing test, observe the *specified* failure, write
> the minimal implementation, run green, then commit.

**Goal.** Replace the `UnsupportedModeError` that `load_run_spec_carrier` raises for `mode="scientific"`
with a fail-closed scientific reconstruction path that (1) validates the scientific block's nested
schema and every non-sealed evidence byte, (2) proves the runtime repo is clean **and** at the exact
`approved_git_sha`, (3) reconstructs the five existing carrier values plus a complete scientific
runtime surface, (4) binds the sealed-input declaration to the owner attestation *without opening the
source*, (5) plumbs the captured `EnvironmentInfo` into Phase-2a and supplies a typed
`ActivationProvenanceInputs` for Phase-2b, and (6) demonstrates hermetically that the current CLI
reaches and fails closed at sub-project B's missing scientific `adapter_version` boundary — with no
store, no seal access, and no run-produced output.

**Architecture.** The change is confined to the driver's pre-seal trust boundary:
`src/alive/compose/driver/carrier_loader.py` (assembly), `run_spec.py` (nested schema),
`identity_lock.py` is untouched (it already fails closed at B), `phase2a_cmd.py` (environment
plumbing), `cli.py` (thread the out-of-band trusted repo root for scientific commands), plus a new
`scientific_runtime.py` (git/environment identity). All science is reused: `run_phase2a`,
`assert_scientific_mode_allowed`, `build_activation_provenance_inputs`,
`validate_pair_index_manifest_preseal` are called, never re-implemented. Test support is a new module
under `tests/` that builds a synthetic-but-valid **scientific** corpus by reusing the fixture builder's
deterministic serializers; the committed fixture builder's bytes and semantics are never touched.

**Tech Stack.** Python 3.12 (`.venv`), pytest, numpy, frozen `@dataclass`, `subprocess` (argv, no
shell) for git, `hashlib`/`alive.provenance` for digests. Ruff (line length 100). No new third-party
dependency; no `gears`/`cpa` import; no `anndata` open of the sealed source.

---

## Global Constraints (non-negotiable — apply to EVERY task)

- **Opens NO seal.** The COMPOSE seal stays UNOPENED. Nothing here reads a sealed outcome.
- **NO `ComposeOutcomeStore` is constructed.** Store construction remains Phase-2b's sole site.
- **NO sealed AnnData / obs / X / layer is opened or materialized.** The sealed source is checked
  *lexically only* at this stage — no `resolve`, `stat`, hash, AnnData parse, or open.
- **NO §4.3 guard is weakened, bypassed, or mocked.** `outcome_store.py`, `gates.py`, `freeze.py`,
  `io.atomic_write_once`, `durable.py`, `terminal.py`, `preflight.py`, and the
  `identity_lock.py` scientific `adapter_version` boundary are left intact. If a guard blocks work,
  STOP and report a conflict per `CLAUDE.md`#sources — do not edit the guard.
- **Fixture serialized artifacts + execution semantics remain byte-unchanged.** No test relabels the
  committed fixture artifact in place; `build_compose_fixture` is not modified.
- **Runtime Git state is measured independently in every CLI process** (each of phase2a / preflight /
  phase2b re-resolves it). No `--git-is-clean` user assertion, no caller-supplied context is accepted.
- **Ruff line length 100.** Run `.venv/bin/python -m ruff check <paths>` and
  `.venv/bin/python -m ruff format --check <paths>` before every commit.
- **Run tests with `.venv/bin/python -m pytest`** (the py3.12 venv). Use `-p no:cacheprovider` and
  `PYTHONDONTWRITEBYTECODE=1` on the seal-safety and full-suite runs.
- **Commit only NAMED files** (`git add <path> …`), never `git add -A`. Every task ends with a commit
  carrying the two trailers shown in each task's final step.

---

## Task 1: Test-only scientific carrier fixture support

Build a `tests/`-only module that produces a synthetic-but-valid **scientific** stage-1 corpus + a
`mode="scientific"` `ResolvedRunSpec` and every declared non-sealed artifact, reusing the fixture
builder's deterministic serializers. This is the foundation every later task-test consumes. It must
NOT change the production fixture builder; the committed fixture artifact keeps
`source_kind="synthetic_fixture"` byte-for-byte, while this corpus uses `source_kind="audited_unsealed"`,
an activated **test-only** config with all activation blockers resolved, config-bound activation
reports embedding that config's SHA/protocol, and the exact scientific block.

**Files**
- Create `tests/alive/compose/driver/scientific_carrier_support.py` — the builder + a returned
  `ScientificCarrierBundle` dataclass and a synthetic-git-repo helper.
- Create `tests/alive/compose/driver/test_scientific_carrier_support.py` — the self-test that the
  built spec loads under the *current* loader and has the expected scientific shape.
- Reuse (import, do not modify): `src/alive/compose/driver/fixture_builder.py` private serializers
  (`_build_instance`, `_build_response_and_fit_role`, `_build_phase2a_inputs`,
  `_serialize_phase2a_inputs`, `_build_sealed_source`, `_worker_block`, `_write_json`, `_write_bytes`,
  `_self_checksummed`, `_path_sha`, `_canonical_bytes`) and constants (`PROTOCOL`,
  `PERTURBATION_COLUMN`, `CONTROL_TOKEN`, `COMBO_SEP`, `FIXTURE_CORPUS_V1`, `_ADAPTER_METHODS`,
  `_N_GENES`, `_CALIBRATION_FRACTION`, `STUB_WORKER_PATH`, `_REPO_ROOT`, `build_worker_bundle`).

**Interfaces**
- Consumes: `alive.compose.config2.load_compose_phase2_config`, `.ComposePhase2Config`;
  `alive.compose.datacard.compute_compose_run_id`; `alive.compose.split.build_split_manifest`,
  `.ROLE_NAMES`; `alive.compose.driver.pair_index.{ATTESTATION_SCHEMA, PAIR_INDEX_MANIFEST_SCHEMA}`;
  `alive.compose.driver.run_spec.{RESOLVED_RUN_SPEC_SCHEMA, RUN_PRODUCED_BASENAMES,
  EXPECTED_HASHES_KEYS, PRE_SEAL_PATH_FIELDS, load_resolved_run_spec}`; `alive.provenance.{sha256_file,
  sha256_json}`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class ScientificCarrierBundle:
      spec_path: Path
      approved_artifacts_root: Path
      run_dir: Path
      audit_path: Path
      repo_root: Path            # synthetic clean git repo whose HEAD == approved_git_sha
      approved_git_sha: str
      config_sha256: str         # activated test-only config sha
      activation_requirements: tuple[str, ...]

  def build_scientific_carrier_fixture(root: Path, *, repo_root: Path) -> ScientificCarrierBundle: ...
  def init_synthetic_repo(repo_root: Path) -> str:  # returns the committed HEAD sha
      ...
  ```

Steps:

- [ ] **Step 1: Write the failing self-test.** Create
  `tests/alive/compose/driver/test_scientific_carrier_support.py`:
  ```python
  """Self-test: the test-only scientific corpus is valid + loads under the current loader.

  The scientific carrier path is not built yet (Task 8); here we only prove the SUPPORT
  module produces a byte-consistent scientific ResolvedRunSpec that the EXISTING
  ``load_resolved_run_spec`` accepts, and a clean synthetic git repo whose HEAD equals the
  spec's ``approved_git_sha``. Every later task-test builds on this.
  """

  from __future__ import annotations

  import subprocess
  from pathlib import Path

  from alive.compose.driver.run_spec import load_resolved_run_spec
  from tests.alive.compose.driver.scientific_carrier_support import (
      ScientificCarrierBundle,
      build_scientific_carrier_fixture,
  )


  def test_scientific_corpus_loads_under_current_loader(tmp_path: Path) -> None:
      repo_root = tmp_path / "repo"
      root = tmp_path / "artifacts"
      bundle = build_scientific_carrier_fixture(root, repo_root=repo_root)
      assert isinstance(bundle, ScientificCarrierBundle)

      spec = load_resolved_run_spec(
          bundle.spec_path,
          approved_artifacts_root=bundle.approved_artifacts_root,
          mode_expected="scientific",
      )
      assert spec.mode == "scientific"
      assert spec.approved_git_sha == bundle.approved_git_sha
      assert spec.scientific is not None
      assert set(spec.scientific["activation_evidence"]["requirements"]) == set(
          bundle.activation_requirements
      )
      assert spec.scientific["sealed_input"]["snapshot_id"]
      assert spec.fixture is None


  def test_synthetic_repo_is_clean_at_approved_head(tmp_path: Path) -> None:
      repo_root = tmp_path / "repo"
      root = tmp_path / "artifacts"
      bundle = build_scientific_carrier_fixture(root, repo_root=repo_root)
      head = subprocess.run(
          ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
      ).stdout.strip()
      status = subprocess.run(
          ["git", "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"],
          cwd=repo_root,
          capture_output=True,
          text=True,
          check=True,
      ).stdout
      assert head == bundle.approved_git_sha
      assert status == ""
  ```

- [ ] **Step 2: Run it, expect collection/import FAIL.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_carrier_support.py -q`
  Expected: `ModuleNotFoundError: No module named 'tests.alive.compose.driver.scientific_carrier_support'`
  (the support module does not exist yet).

- [ ] **Step 3: Write the support module — synthetic git repo + activated config helpers.** Create
  `tests/alive/compose/driver/scientific_carrier_support.py`. Begin with imports, the bundle
  dataclass, the git helper, and the activated-config helper:
  ```python
  """Test-only builder for a synthetic-but-valid COMPOSE *scientific* stage-1 corpus.

  Produces a ``mode="scientific"`` ResolvedRunSpec + every declared non-sealed artifact, reusing
  the committed fixture builder's DETERMINISTIC serializers (spec §6). It NEVER modifies the
  production fixture builder: the committed fixture artifact keeps ``source_kind='synthetic_fixture'``
  byte-for-byte, whereas this corpus declares ``source_kind='audited_unsealed'``, an ACTIVATED
  test-only config with every activation blocker resolved, config-bound activation reports embedding
  that config's SHA/protocol, and the exact nested scientific block. It opens no seal and constructs
  no store.
  """

  from __future__ import annotations

  import hashlib
  import json
  import shutil
  import subprocess
  from dataclasses import dataclass
  from pathlib import Path
  from typing import Any, Mapping

  import yaml

  from alive.compose.config2 import load_compose_phase2_config
  from alive.compose.datacard import compute_compose_run_id
  from alive.compose.driver import fixture_builder as fb
  from alive.compose.driver.pair_index import ATTESTATION_SCHEMA, PAIR_INDEX_MANIFEST_SCHEMA
  from alive.compose.driver.run_spec import (
      EXPECTED_HASHES_KEYS,
      PRE_SEAL_PATH_FIELDS,
      RESOLVED_RUN_SPEC_SCHEMA,
      RUN_PRODUCED_BASENAMES,
  )
  from alive.compose.split import ROLE_NAMES, build_split_manifest
  from alive.provenance import sha256_file, sha256_json

  _CANON_CONFIG = "configs/compose_k562_v1_phase2.yaml"
  _EVIDENCE_ROOT = Path("docs/activation-evidence/compose")
  _DATA_CARD_TEMPLATE = "docs/data-cards/norman_compose_k562_v1.json"

  # Committed evidence templates whose bytes/lineage this corpus copies + overrides to READY.
  _CONFIG_BOUND = (
      "real_norman_phi_rank_and_condition_report",
      "regime_specific_detectable_effect_analysis",
  )


  @dataclass(frozen=True)
  class ScientificCarrierBundle:
      spec_path: Path
      approved_artifacts_root: Path
      run_dir: Path
      audit_path: Path
      repo_root: Path
      approved_git_sha: str
      config_sha256: str
      activation_requirements: tuple[str, ...]


  def init_synthetic_repo(repo_root: Path) -> str:
      """Init a clean committed git repo (no shell) and return its HEAD sha."""
      repo_root.mkdir(parents=True, exist_ok=True)
      env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
      run = lambda *a: subprocess.run(  # noqa: E731 - local terse helper
          ["git", *a], cwd=repo_root, capture_output=True, text=True, check=True, env={**_os_environ(), **env}
      )
      run("init", "-q")
      run("config", "user.email", "test@example.invalid")
      run("config", "user.name", "compose-test")
      (repo_root / "README").write_text("compose scientific carrier test repo\n", encoding="utf-8")
      run("add", "README")
      run("commit", "-q", "-m", "init")
      return run("rev-parse", "HEAD").stdout.strip()


  def _os_environ() -> dict[str, str]:
      import os

      return dict(os.environ)


  def _write_activated_config(stage1: Path) -> tuple[Any, Path, str]:
      """Write + load an ACTIVATED test-only config with all local blockers resolved."""
      raw = yaml.safe_load(Path(_CANON_CONFIG).read_text(encoding="utf-8"))
      raw["status"] = "active"
      raw["regimes"]["power_status"] = "established_from_registered_report"
      raw["baselines"]["gears"]["revision"] = "cell-gears==0.1.2"
      raw["baselines"]["gears"]["environment_status"] = "pinned_and_fresh_sync_verified"
      raw["baselines"]["gears"]["approximation_bias_report_sha256"] = "a" * 64
      raw["baselines"]["cpa"]["revision"] = "cpa-tools==0.8.5"
      raw["baselines"]["cpa"]["environment_status"] = "pinned_and_fresh_sync_verified"
      path = stage1 / "config.yaml"
      path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
      cfg = load_compose_phase2_config(path)
      return cfg, path, cfg.config_sha256
  ```
  (The `os` import is deferred into `_os_environ` only to keep the top imports minimal; a direct
  `import os` at module top is equally acceptable — pick one and keep Ruff clean.)

- [ ] **Step 4: Add the activation-evidence builder** to the same module (mirrors the committed
  `_activation_record_for_config` lineage, but writes every evidence file UNDER `root`). Append:
  ```python
  def _build_activation_evidence(
      root: Path, stage1: Path, cfg: Any, *, gears_lock: Path, cpa_lock: Path
  ) -> dict[str, dict[str, str]]:
      """Build all six activation-requirement evidence files under ``root``.

      Returns ``{requirement: {"path": <abs>, "sha256": "sha256:"+hex}}`` — the exact
      ``activation_evidence.requirements`` roster the scientific block declares. Config-bound
      reports embed ``cfg.config_sha256`` + ``cfg.protocol`` and read ``activation="READY"``.
      """
      ev = stage1 / "activation_evidence"
      ev.mkdir(parents=True, exist_ok=True)
      files: dict[str, Path] = {}

      # 1-2. config-bound analytical reports.
      template = {
          "real_norman_phi_rank_and_condition_report": (
              _EVIDENCE_ROOT / "real_norman_phi_rank_report.json"
          ),
          "regime_specific_detectable_effect_analysis": (
              _EVIDENCE_ROOT / "real_norman_detectable_effect_report.json"
          ),
      }
      for req in _CONFIG_BOUND:
          payload = json.loads(template[req].read_text(encoding="utf-8"))
          payload["protocol"] = cfg.protocol
          payload["config_sha256"] = cfg.config_sha256
          payload["activation"] = "READY — synthetic scientific-carrier evidence"
          p = ev / f"{req}.json"
          p.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
          files[req] = p

      # 3. finalized data card (also the pre-seal data_card file).
      files["finalized_norman_data_card_and_sha256"] = stage1 / "data_card.json"

      # 4. dependency lock (COMPLETE run-gate) — copy env locks + build the READY lock.
      files["gears_cpa_reproducible_dependency_lock"] = _build_dependency_lock_evidence(
          ev, gears_lock=gears_lock, cpa_lock=cpa_lock
      )

      # 5-6. outcome-store source + integration tests — COPY under root (every activation
      # evidence file must satisfy the approved-root policy of Task 2; the committed repo paths
      # are outside approved_artifacts_root, so reference in-root copies of their exact bytes).
      store_copy = ev / "outcome_store_evidence.py"
      shutil.copyfile("src/alive/compose/outcome_store.py", store_copy)
      files["independent_compose_outcome_store_and_access_audit"] = store_copy
      tests_copy = ev / "seal_integration_tests_evidence.py"
      shutil.copyfile("tests/alive/compose/test_phase2b.py", tests_copy)
      files["phase2_plan_metric_leakage_and_seal_integration_tests"] = tests_copy

      roster: dict[str, dict[str, str]] = {}
      for req in cfg.activation_requirements:
          fpath = files[req]
          roster[req] = {
              "path": str(fpath.resolve()),
              "sha256": "sha256:" + hashlib.sha256(fpath.read_bytes()).hexdigest(),
          }
      return roster
  ```
  The `_build_dependency_lock_evidence(ev, *, gears_lock, cpa_lock)` helper reproduces the READY
  dependency-lock construction from `tests/alive/compose/test_config2.py::_activation_record_for_config`
  (copy the `requirements.gears_env.lock` / `requirements.cpa_env.lock` / `go_resource_manifest.json`
  from `docs/activation-evidence/compose`, set `both_backends_run_evidence_complete=True`, fill the
  per-backend `required_evidence` digests + rosters + artifact manifests + wheelhouse + reproducibility
  COMPLETE, recompute `manifest_checksum`, write under `ev`), returning the written lock path. Copy
  that helper verbatim into this module (it is deterministic and file-driven), adjusting only the
  output directory to `ev` and returning the `Path`. Keep it under one function.

- [ ] **Step 5: Add the corpus builder** `build_scientific_carrier_fixture`. Append (this mirrors
  `fixture_builder.build_compose_fixture`, swapping in the activated config, `source_kind=
  "audited_unsealed"`, the scientific block, and gears/cpa requirement-lock pins):
  ```python
  def build_scientific_carrier_fixture(root: Path, *, repo_root: Path) -> ScientificCarrierBundle:
      import os

      root = Path(os.path.realpath(str(root)))
      stage1 = root / "stage1"
      workers = root / "workers"
      run_dir = root / "run"
      for d in (stage1, workers, run_dir):
          d.mkdir(parents=True, exist_ok=True)
      audit_path = run_dir / "audit.jsonl"

      approved_git_sha = init_synthetic_repo(repo_root)
      cfg, config_path, config_sha = _write_activated_config(stage1)

      # 1. split manifest + instance (config-independent given split_seed / k_grid).
      gene_ids = [f"G{i:02d}" for i in range(fb._N_GENES)]
      eligible = [
          (gene_ids[i], gene_ids[j])
          for i in range(fb._N_GENES)
          for j in range(i + 1, fb._N_GENES)
      ]
      manifest = build_split_manifest(
          eligible, seed=cfg.split_seed, calibration_fraction=fb._CALIBRATION_FRACTION
      )
      for role in ROLE_NAMES:
          assert manifest["roles"][role], f"empty {role!r} role"
      instance = fb._build_instance(manifest, k_grid=cfg.total_k_grid)

      # 2. response artifact + fit-role h5ad.
      fit_role_raw_sha = fb._fixture_digest("fit_role_raw_data")
      response_artifact, gene_order, fit_role_spec, response_combined = (
          fb._build_response_and_fit_role(
              out_path=stage1 / "fit_role.h5ad",
              response_dim=instance["p"],
              raw_data_sha256=fit_role_raw_sha,
              cal_pair_ids=instance["cal_pairs"],
              single_gene_ids=instance["gene_ids"],
          )
      )

      # 3. run identity from the ACTIVATED config sha.
      data_card_digest = fb._fixture_digest("data_card")
      raw_or_source_digest = fb._fixture_digest("raw_or_source")
      sequence_mapping_digest = fb._fixture_digest("sequence_mapping")
      run_id = compute_compose_run_id(
          config_digest=config_sha,
          data_card_digest=data_card_digest,
          raw_or_source_digest=raw_or_source_digest,
          sequence_mapping_digest=sequence_mapping_digest,
      )
      checksums = {
          "response_space_checksum": response_combined,
          "factor_checksum": fb._fixture_digest("factor_bank"),
          "manifest_checksum": manifest["checksum"],
          "environment_checksum": fb._fixture_digest("environment"),
          "data_card_checksum": data_card_digest,
          "raw_data_checksum": raw_or_source_digest,
          "sequence_mapping_checksum": sequence_mapping_digest,
      }
      assert set(checksums) == set(EXPECTED_HASHES_KEYS)

      phase2a_inputs = fb._build_phase2a_inputs(
          instance, config=cfg, run_id=run_id, checksums=checksums
      )

      # 4. dev-store DATA — source_kind="audited_unsealed" (scientific evidence).
      dev_source = {
          "schema": "compose_development_outcome_source_v1",
          "combo_calibration_pair_ids": [list(p) for p in instance["cal_pairs"]],
          "combo_calibration_eps": __import__("numpy").asarray(instance["eps_cal"]).tolist(),
          "source_kind": "audited_unsealed",
      }
      dev_source_path = fb._write_json(stage1 / "development_outcome_source.json", dev_source)
      access_audit = {
          "role": "combo_calibration",
          "manifest_checksum": manifest["checksum"],
          "source_checksum": sha256_file(dev_source_path),
          "sealed_access_count": 0,
          "source_kind": "audited_unsealed",
      }
      dev_manifest_path = fb._write_json(
          stage1 / "development_outcome_manifest.json",
          {"schema": "compose_development_outcome_manifest_v1", "access_audit": access_audit},
      )

      # 5. sealed-outcome DATA + attestation (with scientific snapshot_id).
      sealed_source_path = stage1 / "sealed_source.h5ad"
      pair_index, pair_entries, obs_row_identity = fb._build_sealed_source(
          manifest, out_path=sealed_source_path, n_source_genes=instance["p"] + 1
      )
      sealed_source_sha = sha256_file(sealed_source_path)
      pair_index_body = {
          "schema": PAIR_INDEX_MANIFEST_SCHEMA,
          "source_file_sha256": sealed_source_sha,
          "obs_row_identity_sha256": obs_row_identity,
          "perturbation_column": fb.PERTURBATION_COLUMN,
          "control_token": fb.CONTROL_TOKEN,
          "combo_sep": fb.COMBO_SEP,
          "pairs": [
              {
                  "gene_a": a,
                  "gene_b": b,
                  "role": role,
                  "row_indices": [int(i) for i in pair_index[(a, b)]],
                  "row_id_sha256": sha256_json(
                      {"pair": [a, b], "rows": [int(i) for i in pair_index[(a, b)]]}
                  ),
              }
              for (a, b, role) in pair_entries
          ],
      }
      pair_index_manifest = fb._self_checksummed(pair_index_body)
      pair_index_manifest_path = fb._write_json(
          stage1 / "pair_index_manifest.json", pair_index_manifest
      )
      snapshot_id = "compose_scientific_carrier_v1_snapshot"
      attestation = fb._self_checksummed(
          {
              "schema": ATTESTATION_SCHEMA,
              "canonical_source_path": str(sealed_source_path),
              "expected_source_file_sha256": sealed_source_sha,
              "snapshot_id": snapshot_id,
              "source_row_identity_sha256": obs_row_identity,
              "pair_index_file_sha256": sha256_file(pair_index_manifest_path),
          }
      )
      attestation_path = fb._write_json(
          stage1 / "approved_sealed_input_attestation.json", attestation
      )

      # 6. remaining pre-seal DATA files.
      pair_manifest_path = fb._write_json(stage1 / "pair_manifest.json", manifest)
      phase2a_inputs_path = fb._write_json(
          stage1 / "phase2a_inputs.json", fb._serialize_phase2a_inputs(phase2a_inputs)
      )
      import numpy as np

      response_artifact_path = fb._write_json(
          stage1 / "response_artifact.json",
          {
              "schema": "compose_response_artifact_fixture_v1",
              "response_space": json.loads(response_artifact["response_space"].artifact_bytes()),
              "control_mean": np.asarray(response_artifact["control_mean"]).tolist(),
              "combined_checksum": response_combined,
              "gene_order": list(gene_order),
              "raw_data_sha256": fit_role_raw_sha,
              "fit_role_artifact": fit_role_spec.to_payload_block(),
          },
      )
      # data card declares the raw asset AS the processed analysis asset (spec §4 caveat).
      raw_asset_path = fb._write_bytes(
          stage1 / "raw_asset.bin", b"compose_scientific_carrier_v1::synthetic-processed-asset"
      )
      data_card_path = fb._write_json(
          stage1 / "data_card.json",
          {
              "schema": "compose_data_card_scientific_v1",
              "raw_or_source": {"kind": "declared_source_digest", "digest": raw_or_source_digest},
              "processed_analysis_asset": {
                  "role": "processed",
                  "sha256": sha256_file(raw_asset_path),
              },
              "data_card_digest": data_card_digest,
          },
      )
      sequence_mapping_path = fb._write_json(
          stage1 / "sequence_mapping.json",
          {"schema": "compose_sequence_mapping_scientific_v1", "digest": sequence_mapping_digest},
      )
      feature_bank_path = fb._write_json(
          stage1 / "feature_bank.json", {"schema": "compose_feature_bank_scientific_v1"}
      )
      factor_bank_path = fb._write_json(
          stage1 / "factor_bank.json",
          {
              "schema": "compose_factor_bank_scientific_v1",
              "factor_checksum": checksums["factor_checksum"],
              "k_grid": [int(k) for k in cfg.total_k_grid],
          },
      )

      # 7. worker files — gears/cpa requirements_lock pin the real revisions.
      worker_bundle = fb.build_worker_bundle(
          source_root=fb._REPO_ROOT,
          entrypoint=fb.STUB_WORKER_PATH,
          output_path=workers / "stub_worker.pyz",
          method="stub",
      )
      gears_lock = fb._write_bytes(
          workers / "requirements.gears.lock", b"cell-gears==0.1.2\nnumpy==1.26.4\n"
      )
      cpa_lock = fb._write_bytes(
          workers / "requirements.cpa.lock", b"cpa-tools==0.8.5\nnumpy==1.26.4\n"
      )
      worker_blocks: dict[str, Any] = {}
      representations = {name: rep for name, rep, _b in cfg.baseline_representations}
      for method, lock in (("gears", gears_lock), ("cpa", cpa_lock)):
          paths = {
              "worker_script": Path(worker_bundle.path),
              "worker_config": fb._write_bytes(workers / f"{method}_config.json", b"stub-config"),
              "resource_manifest": fb._write_bytes(
                  workers / f"{method}_resource.json", b"stub-resource"
              ),
              "requirements_lock": lock,
              "adapter_artifact": fb._write_bytes(workers / f"{method}_adapter.bin", b"stub-adapter"),
          }
          worker_blocks[method] = fb._worker_block(paths, representation=representations[method])

      # 8. dependency manifest for the scientific block (== the dependency evidence lock).
      pre_seal_paths = {
          "config": config_path,
          "data_card": data_card_path,
          "raw_asset": raw_asset_path,
          "sequence_mapping": sequence_mapping_path,
          "feature_bank": feature_bank_path,
          "factor_bank": factor_bank_path,
          "response_artifact": response_artifact_path,
          "fit_role_artifact": stage1 / "fit_role.h5ad",
          "phase2a_inputs": phase2a_inputs_path,
          "development_outcome_source": dev_source_path,
          "development_outcome_manifest": dev_manifest_path,
          "pair_manifest": pair_manifest_path,
          "pair_index_manifest": pair_index_manifest_path,
          "approved_sealed_input_attestation": attestation_path,
      }
      assert set(pre_seal_paths) == set(PRE_SEAL_PATH_FIELDS)

      requirements_roster = _build_activation_evidence(
          root, stage1, cfg, gears_lock=gears_lock, cpa_lock=cpa_lock
      )
      dependency_path = Path(
          requirements_roster["gears_cpa_reproducible_dependency_lock"]["path"]
      )

      # 9. assemble the scientific ResolvedRunSpec.
      spec_body: dict[str, Any] = {
          "schema": RESOLVED_RUN_SPEC_SCHEMA,
          "mode": "scientific",
          "protocol": fb.PROTOCOL,
          "run_id": run_id,
          "approved_git_sha": approved_git_sha,
          "run_dir": str(run_dir),
          "approved_artifacts_root": str(root),
          "config_digest": config_sha,
          "data_card_digest": data_card_digest,
          "raw_or_source_digest": raw_or_source_digest,
          "sequence_mapping_digest": sequence_mapping_digest,
          "run_produced_basenames": dict(RUN_PRODUCED_BASENAMES),
          "expected_hashes": dict(checksums),
          "worker_blocks": worker_blocks,
          "scientific": {
              "activation_evidence": {
                  "owner": "owner@example.org",
                  "requirements": requirements_roster,
              },
              "dependency_manifest": {
                  "path": str(dependency_path),
                  "sha256": sha256_file(dependency_path),
              },
              "device": "cpu",
              "precision": "float32",
              "sealed_input": {
                  "source_path": str(sealed_source_path),
                  "expected_file_sha256": sealed_source_sha,
                  "snapshot_id": snapshot_id,
                  "audit_path": str(audit_path),
              },
          },
      }
      for field in PRE_SEAL_PATH_FIELDS:
          spec_body[field] = fb._path_sha(pre_seal_paths[field])
      spec = fb._self_checksummed(spec_body)
      spec_path = fb._write_bytes(root / "resolved_run_spec.json", fb._canonical_bytes(spec))

      return ScientificCarrierBundle(
          spec_path=spec_path,
          approved_artifacts_root=root,
          run_dir=run_dir,
          audit_path=audit_path,
          repo_root=repo_root,
          approved_git_sha=approved_git_sha,
          config_sha256=config_sha,
          activation_requirements=cfg.activation_requirements,
      )
  ```
  Note `dependency_manifest.sha256` here is the bare 64-hex (`sha256_file`), matching the scientific
  schema (`dependency_manifest.sha256: <64 hex>`), distinct from the `sha256:`-prefixed
  `activation_evidence.requirements[...].sha256`.

- [ ] **Step 6: Run the self-test, expect PASS.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_carrier_support.py -q`
  Expected: `2 passed`. If `load_resolved_run_spec` rejects, fix the corpus (it must be canonical
  JSON, self-checksummed, all pre-seal SHAs matching on-disk bytes, run_id recomputing from the four
  digests). No production code changed yet.

- [ ] **Step 7: Confirm the committed fixture artifact is byte-unchanged + Ruff clean.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_carrier_loader.py -q` → all pass
  (unchanged). `.venv/bin/python -m ruff check tests/alive/compose/driver/scientific_carrier_support.py
  tests/alive/compose/driver/test_scientific_carrier_support.py` and
  `.venv/bin/python -m ruff format --check <same paths>` → clean.

- [ ] **Step 8: Commit.**
  ```
  git add tests/alive/compose/driver/scientific_carrier_support.py \
          tests/alive/compose/driver/test_scientific_carrier_support.py
  git commit -m "test(compose-carrier): scientific stage-1 corpus + synthetic clean-repo support

  Foundation for the scientific PREPARE carrier (spec §6): a tests/-only builder that
  produces a valid mode=scientific ResolvedRunSpec + audited_unsealed dev audit + activated
  test-only config + config-bound activation evidence, reusing the fixture builder's
  deterministic serializers. The committed fixture artifact is untouched.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HPoPEh5tLhsjgavBgmcmXV"
  ```

---

## Task 2: Nested scientific-block schema validation

Expand `run_spec.py::_validate_mode_block` to validate the nested `activation_evidence` and
`dependency_manifest` contracts (§2.1). Today it validates only the scientific block's top-level key
roster + `sealed_input`; the nested contents are accepted with arbitrary values — the gap this task
closes.

**Files**
- Modify `src/alive/compose/driver/run_spec.py` — extend `_validate_mode_block` (:645-684); add a
  helper `_validate_scientific_evidence_block`. `activation_evidence` / `dependency_manifest` are
  non-sealed inputs and MAY be read (byte-SHA equality), reusing `_check_path_policy(kind="file")`.
- Modify `tests/alive/compose/driver/test_run_spec.py` — add the nested-schema negatives.

**Interfaces**
- Consumes: `_check_path_policy(declared, root_real, *, kind, field) -> str`, `_is_hex64`,
  `_parse_path_sha`, `RunSpecError`, `sha256_file`.
- Produces: no signature change to `load_resolved_run_spec`; `_validate_mode_block` now also validates
  `activation_evidence` (owner non-empty; each requirement `{path: abs-normalized, lexically-contained,
  existing regular non-symlink file; sha256: "sha256:"+64hex with byte-SHA equality}`) and
  `dependency_manifest` (`{path, sha256}` under the same approved-root file policy, bare 64-hex with
  byte-SHA equality).

Steps:

- [ ] **Step 1: Write failing negatives** in `tests/alive/compose/driver/test_run_spec.py`. Add a
  helper that rebuilds the scientific spec from the Task-1 corpus after mutating one nested field, then
  asserts `RunSpecError`. Use canonical re-serialization so only the *targeted* invariant fails:
  ```python
  import json
  from pathlib import Path

  import pytest

  from alive.compose.driver.run_spec import RunSpecError, load_resolved_run_spec
  from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture


  def _load(bundle):
      return load_resolved_run_spec(
          bundle.spec_path,
          approved_artifacts_root=bundle.approved_artifacts_root,
          mode_expected="scientific",
      )


  def _rewrite(bundle, mutate) -> None:
      raw = json.loads(Path(bundle.spec_path).read_bytes())
      mutate(raw)
      body = {k: v for k, v in raw.items() if k != "self_checksum"}
      from alive.provenance import sha256_json

      raw["self_checksum"] = sha256_json(body)
      Path(bundle.spec_path).write_bytes(
          json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
      )


  def test_scientific_block_loads_clean(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      assert _load(bundle).scientific is not None  # positive baseline


  def test_activation_evidence_empty_owner_rejects(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      _rewrite(bundle, lambda raw: raw["scientific"]["activation_evidence"].__setitem__("owner", ""))
      with pytest.raises(RunSpecError, match="owner"):
          _load(bundle)


  def test_activation_evidence_wrong_digest_rejects(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")

      def mutate(raw):
          reqs = raw["scientific"]["activation_evidence"]["requirements"]
          key = sorted(reqs)[0]
          reqs[key]["sha256"] = "sha256:" + "0" * 64

      _rewrite(bundle, mutate)
      with pytest.raises(RunSpecError, match="sha256|digest"):
          _load(bundle)


  def test_activation_evidence_relative_path_rejects(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")

      def mutate(raw):
          reqs = raw["scientific"]["activation_evidence"]["requirements"]
          key = sorted(reqs)[0]
          reqs[key]["path"] = "relative/evidence.json"

      _rewrite(bundle, mutate)
      with pytest.raises(RunSpecError, match="absolute|escapes|path"):
          _load(bundle)


  def test_dependency_manifest_malformed_sha_rejects(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      _rewrite(
          bundle,
          lambda raw: raw["scientific"]["dependency_manifest"].__setitem__("sha256", "nothex"),
      )
      with pytest.raises(RunSpecError, match="sha256"):
          _load(bundle)
  ```

- [ ] **Step 2: Run, expect FAIL.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_run_spec.py -q -k "activation_evidence or dependency_manifest or scientific_block_loads_clean"`
  Expected: `test_scientific_block_loads_clean` passes, but the four negatives FAIL (no `RunSpecError`
  raised — the current `_validate_mode_block` never inspects nested `activation_evidence` /
  `dependency_manifest`, so a mutated digest / relative path / empty owner loads successfully).

- [ ] **Step 3: Implement the nested validator.** In `src/alive/compose/driver/run_spec.py`, add the
  helper and call it from `_validate_mode_block`'s scientific branch. Insert after
  `_validate_mode_block`:
  ```python
  def _validate_scientific_evidence_block(block: Mapping[str, Any], *, root_real: str) -> None:
      """Validate a scientific block's nested activation_evidence + dependency_manifest (§2.1).

      These are NON-sealed inputs, so the loader enforces the same approved-root FILE policy as
      other pre-seal artifacts (absolute normalized, lexically contained, existing regular
      non-symlink file) AND actual byte-SHA equality. The sealed SOURCE is never touched here.
      """
      evidence = block["activation_evidence"]
      if not isinstance(evidence, dict) or set(evidence) != {"owner", "requirements"}:
          raise RunSpecError(
              "scientific.activation_evidence must have exactly {'owner', 'requirements'}"
          )
      owner = evidence["owner"]
      if not isinstance(owner, str) or not owner.strip():
          raise RunSpecError("scientific.activation_evidence.owner must be a non-empty string")
      requirements = evidence["requirements"]
      if not isinstance(requirements, dict) or not requirements:
          raise RunSpecError("scientific.activation_evidence.requirements must be a non-empty object")
      for req, entry in requirements.items():
          where = f"scientific.activation_evidence.requirements[{req!r}]"
          if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
              raise RunSpecError(f"{where}: must have exactly keys {{'path', 'sha256'}}")
          digest = entry["sha256"]
          if not isinstance(digest, str) or _PREFIXED_HEX64_RE.match(digest) is None:
              raise RunSpecError(f"{where}: 'sha256' must be 'sha256:'+64 lowercase hex chars")
          _check_path_policy(entry["path"], root_real, kind="file", field=f"{where}.path")
          actual = sha256_file(entry["path"])
          if actual != digest.removeprefix("sha256:"):
              raise RunSpecError(
                  f"{where}: declared sha256 {digest} != actual file digest sha256:{actual}"
              )

      manifest = block["dependency_manifest"]
      dep = _parse_path_sha(manifest, field="scientific.dependency_manifest")
      _check_path_policy(dep.path, root_real, kind="file", field="scientific.dependency_manifest")
      actual = sha256_file(dep.path)
      if actual != dep.sha256:
          raise RunSpecError(
              f"scientific.dependency_manifest: declared sha256 {dep.sha256} != actual {actual}"
          )
  ```
  Add the module-level regex beside `_HEX64_RE` (line 207):
  ```python
  _PREFIXED_HEX64_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
  ```
  In `_validate_mode_block` (:657-684), extend the scientific branch — after the existing
  `sealed_input` checks, before returning — with:
  ```python
      if mode == "scientific":
          _validate_scientific_evidence_block(block, root_real=root_real)
  ```
  (`_validate_mode_block` already has `block` in scope and is only called with the validated key
  roster, so `block["activation_evidence"]` / `block["dependency_manifest"]` are guaranteed present.)

- [ ] **Step 4: Run, expect PASS.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_run_spec.py -q`
  Expected: all pass (the four negatives now raise `RunSpecError`; the positive baseline still loads;
  every pre-existing `test_run_spec.py` case still passes — the fixture-mode path is untouched).

- [ ] **Step 5: Ruff + commit.**
  `.venv/bin/python -m ruff check src/alive/compose/driver/run_spec.py tests/alive/compose/driver/test_run_spec.py`
  and `--format --check`. Then:
  ```
  git add src/alive/compose/driver/run_spec.py tests/alive/compose/driver/test_run_spec.py
  git commit -m "feat(compose-carrier): validate nested scientific activation_evidence + dependency_manifest (§2.1)

  _validate_mode_block now enforces owner non-empty, the requirement roster's per-file
  approved-root policy + sha256:hex byte equality, and the dependency_manifest {path,sha256}
  file policy. Closes the gap where nested scientific evidence bytes were unvalidated.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HPoPEh5tLhsjgavBgmcmXV"
  ```

---

## Task 3: `ScientificRuntimeContext` + independent git/environment resolver

Add a frozen `ScientificRuntimeContext` and a resolver that proves the runtime repo is clean and at
the exact `approved_git_sha`, using argv-based git subprocess (no shell), failing closed on any
divergence. No caller-asserted clean boolean is accepted (§2.3).

**Files**
- Create `src/alive/compose/driver/scientific_runtime.py`.
- Create `tests/alive/compose/driver/test_scientific_runtime.py`.

**Interfaces**
- Consumes: `alive.provenance.{EnvironmentInfo, capture_environment}`; `subprocess`, `os`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class ScientificRuntimeContext:
      repo_root: Path            # canonical trusted repository root (realpath)
      head_sha: str              # full 40- or 64-char lowercase hex
      git_is_clean: bool         # always True on a returned context
      environment: EnvironmentInfo

  class ScientificRuntimeError(RuntimeError): ...

  def resolve_scientific_runtime_context(
      *, trusted_repo_root: Path, approved_git_sha: str, lockfile_path: Path,
      registered_seeds: Sequence[int],
  ) -> ScientificRuntimeContext: ...
  ```

Steps:

- [ ] **Step 1: Write the failing test.** Create `tests/alive/compose/driver/test_scientific_runtime.py`:
  ```python
  """Runtime git/environment identity resolver (spec §2.3) — fail-closed, no shell."""

  from __future__ import annotations

  import subprocess
  from pathlib import Path

  import pytest

  from alive.compose.driver.scientific_runtime import (
      ScientificRuntimeContext,
      ScientificRuntimeError,
      resolve_scientific_runtime_context,
  )
  from tests.alive.compose.driver.scientific_carrier_support import init_synthetic_repo


  def _repo(tmp_path: Path) -> tuple[Path, str]:
      repo = tmp_path / "repo"
      head = init_synthetic_repo(repo)
      return repo, head


  def test_clean_repo_at_approved_head_resolves(tmp_path):
      repo, head = _repo(tmp_path)
      ctx = resolve_scientific_runtime_context(
          trusted_repo_root=repo, approved_git_sha=head, lockfile_path=repo / "README",
          registered_seeds=(11, 23, 37),
      )
      assert isinstance(ctx, ScientificRuntimeContext)
      assert ctx.git_is_clean is True
      assert ctx.head_sha == head
      assert ctx.environment.git_commit == head
      assert ctx.environment.registered_seeds == (11, 23, 37)
      assert Path(ctx.repo_root) == Path(repo).resolve()


  def test_wrong_head_rejects(tmp_path):
      repo, _ = _repo(tmp_path)
      with pytest.raises(ScientificRuntimeError, match="HEAD"):
          resolve_scientific_runtime_context(
              trusted_repo_root=repo, approved_git_sha="a" * 40, lockfile_path=repo / "README",
              registered_seeds=(11, 23, 37),
          )


  def test_dirty_tracked_rejects(tmp_path):
      repo, head = _repo(tmp_path)
      (repo / "README").write_text("dirtied\n", encoding="utf-8")
      with pytest.raises(ScientificRuntimeError, match="clean|dirty|status"):
          resolve_scientific_runtime_context(
              trusted_repo_root=repo, approved_git_sha=head, lockfile_path=repo / "README",
              registered_seeds=(11, 23, 37),
          )


  def test_untracked_file_rejects(tmp_path):
      repo, head = _repo(tmp_path)
      (repo / "stray.txt").write_text("x\n", encoding="utf-8")
      with pytest.raises(ScientificRuntimeError, match="clean|dirty|status"):
          resolve_scientific_runtime_context(
              trusted_repo_root=repo, approved_git_sha=head, lockfile_path=repo / "README",
              registered_seeds=(11, 23, 37),
          )


  def test_malformed_sha_rejects(tmp_path):
      repo, _ = _repo(tmp_path)
      with pytest.raises(ScientificRuntimeError, match="hex|sha|SHA"):
          resolve_scientific_runtime_context(
              trusted_repo_root=repo, approved_git_sha="not-a-sha", lockfile_path=repo / "README",
              registered_seeds=(11, 23, 37),
          )


  def test_wrong_repo_root_rejects(tmp_path):
      repo, head = _repo(tmp_path)
      other = tmp_path / "not-a-repo"
      other.mkdir()
      with pytest.raises(ScientificRuntimeError):
          resolve_scientific_runtime_context(
              trusted_repo_root=other, approved_git_sha=head, lockfile_path=repo / "README",
              registered_seeds=(11, 23, 37),
          )


  def test_status_command_does_not_ignore_submodules(tmp_path):
      # The porcelain status command must carry --ignore-submodules=none so submodule dirt
      # is never silently ignored (spec §2.3.3). Guard the constant directly.
      from alive.compose.driver import scientific_runtime as sr

      assert "--ignore-submodules=none" in sr._STATUS_ARGV
      assert "--untracked-files=all" in sr._STATUS_ARGV
  ```

- [ ] **Step 2: Run, expect import FAIL.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_runtime.py -q`
  Expected: `ModuleNotFoundError: No module named 'alive.compose.driver.scientific_runtime'`.

- [ ] **Step 3: Implement the resolver.** Create `src/alive/compose/driver/scientific_runtime.py`:
  ```python
  """Independent runtime Git/environment identity for a scientific driver process (spec §2.3).

  Each scientific CLI command re-resolves this context, so a change between phase2a, preflight and
  phase2b fails closed. Resolution uses argv-based subprocess calls (NO shell) and fails closed
  unless: the trusted canonical repository root equals ``git rev-parse --show-toplevel``; HEAD equals
  the spec's ``approved_git_sha`` exactly; the working tree is fully clean (tracked + untracked +
  submodules, none ignored); the SHA is exact full-hex; and environment capture succeeds. No
  caller-asserted clean boolean or context is accepted. This module opens no seal and reads no
  outcome.
  """

  from __future__ import annotations

  import os
  import re
  import subprocess
  from collections.abc import Sequence
  from dataclasses import dataclass
  from pathlib import Path

  from alive.provenance import EnvironmentInfo, capture_environment

  __all__ = [
      "ScientificRuntimeContext",
      "ScientificRuntimeError",
      "resolve_scientific_runtime_context",
  ]

  _FULL_HEX_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")

  #: Porcelain status argv — tracked + untracked + submodule changes all surface (none ignored).
  _STATUS_ARGV: tuple[str, ...] = (
      "status",
      "--porcelain=v1",
      "--untracked-files=all",
      "--ignore-submodules=none",
  )
  _GIT_TIMEOUT = 15


  class ScientificRuntimeError(RuntimeError):
      """Raised on ANY runtime git/environment identity failure (fail-closed)."""


  @dataclass(frozen=True)
  class ScientificRuntimeContext:
      repo_root: Path
      head_sha: str
      git_is_clean: bool
      environment: EnvironmentInfo


  def _git(repo_root: Path, *args: str) -> str:
      """Run ``git <args>`` with cwd=repo_root (argv, no shell); return stripped stdout."""
      try:
          result = subprocess.run(
              ["git", *args],
              cwd=str(repo_root),
              capture_output=True,
              text=True,
              timeout=_GIT_TIMEOUT,
          )
      except (OSError, subprocess.SubprocessError) as exc:
          raise ScientificRuntimeError(f"git {args[0]} failed at {repo_root}: {exc}") from exc
      if result.returncode != 0:
          raise ScientificRuntimeError(
              f"git {args[0]} exited {result.returncode} at {repo_root}: {result.stderr.strip()}"
          )
      return result.stdout


  def resolve_scientific_runtime_context(
      *, trusted_repo_root: Path, approved_git_sha: str, lockfile_path: Path,
      registered_seeds: Sequence[int],
  ) -> ScientificRuntimeContext:
      """Resolve + validate the runtime context, or fail closed (§2.3)."""
      if not isinstance(approved_git_sha, str) or _FULL_HEX_RE.match(approved_git_sha) is None:
          raise ScientificRuntimeError(
              f"approved_git_sha must be full 40- or 64-char lowercase hex, got {approved_git_sha!r}"
          )
      root_real = Path(os.path.realpath(str(trusted_repo_root)))
      if not root_real.is_dir():
          raise ScientificRuntimeError(f"trusted repo root is not a directory: {root_real}")
      if isinstance(registered_seeds, (str, bytes)) or not isinstance(
          registered_seeds, Sequence
      ):
          raise ScientificRuntimeError("registered_seeds must be a non-empty sequence of integers")
      seeds = tuple(registered_seeds)
      if not seeds or any(type(seed) is not int for seed in seeds):
          raise ScientificRuntimeError("registered_seeds must be a non-empty sequence of integers")

      toplevel = _git(root_real, "rev-parse", "--show-toplevel").strip()
      if Path(os.path.realpath(toplevel)) != root_real:
          raise ScientificRuntimeError(
              f"git toplevel {toplevel!r} != trusted repo root {str(root_real)!r}"
          )

      head = _git(root_real, "rev-parse", "HEAD").strip()
      if _FULL_HEX_RE.match(head) is None:
          raise ScientificRuntimeError(f"HEAD is not exact full-hex: {head!r}")
      if head != approved_git_sha:
          raise ScientificRuntimeError(
              f"runtime HEAD {head!r} != approved_git_sha {approved_git_sha!r}"
          )

      status = _git(root_real, *_STATUS_ARGV)
      if status.strip() != "":
          raise ScientificRuntimeError(
              "working tree is not clean (tracked/untracked/submodule changes present)"
          )

      try:
          environment = capture_environment(lockfile_path, seeds, repo_dir=root_real)
      except OSError as exc:
          raise ScientificRuntimeError(f"environment capture failed: {exc}") from exc
      if environment.git_commit != approved_git_sha:
          raise ScientificRuntimeError(
              f"captured environment git_commit {environment.git_commit!r} != "
              f"approved_git_sha {approved_git_sha!r}"
          )

      return ScientificRuntimeContext(
          repo_root=root_real,
          head_sha=head,
          git_is_clean=True,
          environment=environment,
      )
  ```

- [ ] **Step 4: Run, expect PASS.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_runtime.py -q`
  Expected: `7 passed`.

- [ ] **Step 5: Ruff + commit.**
  ```
  git add src/alive/compose/driver/scientific_runtime.py \
          tests/alive/compose/driver/test_scientific_runtime.py
  git commit -m "feat(compose-carrier): ScientificRuntimeContext + fail-closed git/env resolver (§2.3)

  Argv-based (no shell) git identity: trusted toplevel == root, HEAD == approved_git_sha,
  fully-clean porcelain status (untracked + submodules, none ignored), exact full-hex, and a
  captured EnvironmentInfo whose git_commit re-confirms HEAD. No caller-asserted clean boolean.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HPoPEh5tLhsjgavBgmcmXV"
  ```

---

## Task 4: Discriminated `RunSpecCarrier`

Turn `RunSpecCarrier` into a construction-validated, discriminated type: add `mode` + six scientific
fields, enforce exact population by mode in `__post_init__`, and provide private mode-specific
constructors so a partially populated scientific carrier cannot exist (§3). The fixture construction
path stays byte-behaviourally unchanged.

**Files**
- Modify `src/alive/compose/driver/carrier_loader.py` — extend the `RunSpecCarrier` dataclass
  (:83-118), add `__post_init__`, add `_fixture` / `_scientific` classmethods, and route the existing
  fixture construction (:170-176) through `_fixture`.
- Modify `tests/alive/compose/driver/test_carrier_loader.py` — add the discriminated-shape tests.

**Interfaces**
- Consumes: `alive.compose.config2.ActivationRecord`; `alive.provenance.EnvironmentInfo`;
  `alive.compose.phase2b.ActivationProvenanceInputs`; `alive.compose.phase2a.Phase2aInputs`.
- Produces (new fields, all default `None`; `mode` default `"fixture"`):
  ```python
  mode: str = "fixture"
  activation_record: ActivationRecord | None = None
  git_is_clean: bool | None = None
  environment: EnvironmentInfo | None = None
  data_card_path: Path | None = None
  raw_asset_path: Path | None = None
  provenance_inputs: ActivationProvenanceInputs | None = None
  ```
  plus classmethods:
  ```python
  @classmethod
  def _fixture(cls, *, spec_path, phase2a_inputs, dev_store_audit, response_artifact,
               sealed_outcome) -> "RunSpecCarrier": ...
  @classmethod
  def _scientific(cls, *, spec_path, phase2a_inputs, dev_store_audit, response_artifact,
                  sealed_outcome, activation_record, git_is_clean, environment,
                  data_card_path, raw_asset_path, provenance_inputs) -> "RunSpecCarrier": ...
  ```

Steps:

- [ ] **Step 1: Write failing discriminated-shape tests** in
  `tests/alive/compose/driver/test_carrier_loader.py`:
  ```python
  def test_fixture_carrier_has_scientific_fields_none(tmp_path):
      bundle = build_compose_fixture(tmp_path)
      carrier = load_run_spec_carrier(
          bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
      )
      assert carrier.mode == "fixture"
      assert carrier.activation_record is None
      assert carrier.git_is_clean is None
      assert carrier.environment is None
      assert carrier.data_card_path is None
      assert carrier.raw_asset_path is None
      assert carrier.provenance_inputs is None


  def test_scientific_carrier_requires_all_fields(tmp_path):
      # A carrier declaring mode="scientific" but leaving the scientific surface None fails closed.
      from alive.compose.driver.carrier_loader import RunSpecCarrier

      bundle = build_compose_fixture(tmp_path)
      base = load_run_spec_carrier(
          bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
      )
      with pytest.raises(ValueError, match="scientific"):
          RunSpecCarrier(
              spec_path=base.spec_path,
              phase2a_inputs=base.phase2a_inputs,
              dev_store_audit=base.dev_store_audit,
              response_artifact=base.response_artifact,
              sealed_outcome=base.sealed_outcome,
              mode="scientific",  # every scientific field left None → reject
          )


  def test_fixture_mode_rejects_populated_scientific_field(tmp_path):
      from alive.compose.driver.carrier_loader import RunSpecCarrier

      bundle = build_compose_fixture(tmp_path)
      base = load_run_spec_carrier(
          bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
      )
      with pytest.raises(ValueError, match="fixture"):
          RunSpecCarrier(
              spec_path=base.spec_path,
              phase2a_inputs=base.phase2a_inputs,
              dev_store_audit=base.dev_store_audit,
              response_artifact=base.response_artifact,
              sealed_outcome=base.sealed_outcome,
              mode="fixture",
              git_is_clean=True,  # a scientific field populated in fixture mode → reject
          )
  ```

- [ ] **Step 2: Run, expect FAIL.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_carrier_loader.py -q -k "scientific_fields_none or requires_all_fields or rejects_populated"`
  Expected: `test_fixture_carrier_has_scientific_fields_none` FAILS with `AttributeError: 'RunSpecCarrier'
  object has no attribute 'mode'`; the two negatives FAIL because `RunSpecCarrier.__init__` currently
  accepts no `mode` kwarg (`TypeError`).

- [ ] **Step 3: Implement the discriminated dataclass.** In
  `src/alive/compose/driver/carrier_loader.py`, extend the imports:
  ```python
  from alive.compose.config2 import ActivationRecord
  from alive.compose.phase2b import ActivationProvenanceInputs
  from alive.provenance import EnvironmentInfo, sha256_bytes
  ```
  (keep the existing `sha256_bytes` import — merge into one line). Replace the field block
  (currently `spec_path … sealed_outcome`) with the discriminated shape + validation:
  ```python
      spec_path: Path
      phase2a_inputs: Phase2aInputs
      dev_store_audit: Mapping[str, Any]
      response_artifact: Mapping[str, Any]
      sealed_outcome: Mapping[str, Any]
      mode: str = "fixture"
      activation_record: ActivationRecord | None = None
      git_is_clean: bool | None = None
      environment: EnvironmentInfo | None = None
      data_card_path: Path | None = None
      raw_asset_path: Path | None = None
      provenance_inputs: ActivationProvenanceInputs | None = None

      _SCIENTIFIC_FIELDS = (
          "activation_record",
          "git_is_clean",
          "environment",
          "data_card_path",
          "raw_asset_path",
          "provenance_inputs",
      )

      def __post_init__(self) -> None:
          """Enforce exact population by ``mode`` (§3): all-None in fixture, all-typed in scientific."""
          if self.mode == "fixture":
              populated = [f for f in self._SCIENTIFIC_FIELDS if getattr(self, f) is not None]
              if populated:
                  raise ValueError(
                      f"fixture carrier must leave every scientific field None; got {populated}"
                  )
              return
          if self.mode == "scientific":
              missing = [f for f in self._SCIENTIFIC_FIELDS if getattr(self, f) is None]
              if missing:
                  raise ValueError(
                      f"scientific carrier requires every scientific field; missing {missing}"
                  )
              if not isinstance(self.activation_record, ActivationRecord):
                  raise ValueError("scientific activation_record must be an ActivationRecord")
              if self.git_is_clean is not True:
                  raise ValueError("scientific git_is_clean must be exactly True")
              if not isinstance(self.environment, EnvironmentInfo):
                  raise ValueError("scientific environment must be an EnvironmentInfo")
              if not isinstance(self.provenance_inputs, ActivationProvenanceInputs):
                  raise ValueError("scientific provenance_inputs must be ActivationProvenanceInputs")
              if not isinstance(self.data_card_path, Path) or not isinstance(self.raw_asset_path, Path):
                  raise ValueError("scientific data_card_path / raw_asset_path must be Path")
              return
          raise ValueError(f"RunSpecCarrier.mode must be 'fixture' or 'scientific', got {self.mode!r}")

      @classmethod
      def _fixture(cls, *, spec_path, phase2a_inputs, dev_store_audit, response_artifact,
                   sealed_outcome) -> "RunSpecCarrier":
          return cls(
              spec_path=spec_path,
              phase2a_inputs=phase2a_inputs,
              dev_store_audit=dev_store_audit,
              response_artifact=response_artifact,
              sealed_outcome=sealed_outcome,
              mode="fixture",
          )

      @classmethod
      def _scientific(cls, *, spec_path, phase2a_inputs, dev_store_audit, response_artifact,
                      sealed_outcome, activation_record, git_is_clean, environment,
                      data_card_path, raw_asset_path, provenance_inputs) -> "RunSpecCarrier":
          return cls(
              spec_path=spec_path,
              phase2a_inputs=phase2a_inputs,
              dev_store_audit=dev_store_audit,
              response_artifact=response_artifact,
              sealed_outcome=sealed_outcome,
              mode="scientific",
              activation_record=activation_record,
              git_is_clean=git_is_clean,
              environment=environment,
              data_card_path=data_card_path,
              raw_asset_path=raw_asset_path,
              provenance_inputs=provenance_inputs,
          )
  ```
  `_SCIENTIFIC_FIELDS` is a class attribute (a tuple), not a dataclass field, so annotate it WITHOUT
  a type hint (a bare assignment) so `@dataclass` does not treat it as a field. Route the fixture
  branch construction (currently `return RunSpecCarrier(spec_path=…, phase2a_inputs=…, …)` at :170)
  through the classmethod:
  ```python
      return RunSpecCarrier._fixture(
          spec_path=spec_path,
          phase2a_inputs=_load_phase2a_inputs(spec),
          dev_store_audit=_load_dev_store_audit(spec),
          response_artifact=_load_response_artifact(spec),
          sealed_outcome=_load_sealed_outcome(spec),
      )
  ```

- [ ] **Step 4: Run, expect PASS.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_carrier_loader.py -q`
  Expected: all pass (the three new tests + every pre-existing fixture test — the fixture surface is
  behaviourally identical). If a circular import surfaces from importing `ActivationProvenanceInputs`
  out of `phase2b`, keep the import at module top (carrier_loader does not import into phase2b), and
  confirm with `.venv/bin/python -c "import alive.compose.driver.carrier_loader"`.

- [ ] **Step 5: Ruff + commit.**
  ```
  git add src/alive/compose/driver/carrier_loader.py tests/alive/compose/driver/test_carrier_loader.py
  git commit -m "feat(compose-carrier): discriminated RunSpecCarrier with mode + scientific surface (§3)

  RunSpecCarrier gains mode + six scientific fields with a __post_init__ that rejects any
  partial/mixed state (all-None in fixture, all-typed in scientific) plus private _fixture /
  _scientific constructors. The fixture construction path is routed through _fixture and stays
  behaviourally unchanged.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HPoPEh5tLhsjgavBgmcmXV"
  ```

---

## Task 5: Sealed-input attestation equality validator (no source access)

Add a pure lexical validator proving the scientific `sealed_input` declaration binds to the
owner-approved attestation and the loader-verified pair index (§2.2). NO `resolve`, `stat`, hash,
AnnData parse, or source open occurs — source node identity + byte integrity remain
Phase-2b-after-confirmation work.

**Files**
- Modify `src/alive/compose/driver/pair_index.py` — add `validate_scientific_sealed_declaration`
  (reusing the existing `validate_pair_index_manifest_preseal` for the manifest↔attestation bindings).
- Create `tests/alive/compose/driver/test_scientific_sealed_declaration.py`.

**Interfaces**
- Consumes: `validate_pair_index_manifest_preseal(manifest, *, attestation,
  pair_index_manifest_file_sha256)`; `RunSpecError`; `alive.compose.durable.SEAL_AUDIT_FILENAME`;
  `os.path.normpath`.
- Produces:
  ```python
  def validate_scientific_sealed_declaration(
      *,
      sealed_input: Mapping[str, Any],       # spec.scientific["sealed_input"]
      attestation: Mapping[str, Any],        # parsed approved_sealed_input_attestation
      pair_index_manifest: Mapping[str, Any],
      pair_index_manifest_file_sha256: str,  # spec.pre_seal["pair_index_manifest"].sha256
      run_dir: str,
  ) -> None: ...  # raises RunSpecError on any mismatch
  ```

Steps:

- [ ] **Step 1: Write the failing test.** Create
  `tests/alive/compose/driver/test_scientific_sealed_declaration.py`:
  ```python
  """Sealed-input ↔ attestation equality at pre-seal (spec §2.2) — no source access."""

  from __future__ import annotations

  import json
  from pathlib import Path

  import pytest

  from alive.compose.driver.pair_index import validate_scientific_sealed_declaration
  from alive.compose.driver.run_spec import RunSpecError, load_resolved_run_spec
  from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture


  def _parts(bundle):
      spec = load_resolved_run_spec(
          bundle.spec_path,
          approved_artifacts_root=bundle.approved_artifacts_root,
          mode_expected="scientific",
      )
      attestation = json.loads(
          Path(spec.pre_seal["approved_sealed_input_attestation"].path).read_bytes()
      )
      pim = json.loads(Path(spec.pre_seal["pair_index_manifest"].path).read_bytes())
      return spec, attestation, pim


  def test_valid_declaration_passes(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      spec, attestation, pim = _parts(bundle)
      validate_scientific_sealed_declaration(
          sealed_input=spec.scientific["sealed_input"],
          attestation=attestation,
          pair_index_manifest=pim,
          pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
          run_dir=spec.run_dir,
      )  # no raise


  @pytest.mark.parametrize(
      "key,bad",
      [
          ("source_path", "/tmp/other.h5ad"),
          ("expected_file_sha256", "0" * 64),
          ("snapshot_id", "wrong_snapshot"),
      ],
  )
  def test_sealed_input_field_mismatch_rejects(tmp_path, key, bad):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      spec, attestation, pim = _parts(bundle)
      sealed = dict(spec.scientific["sealed_input"])
      sealed[key] = bad
      with pytest.raises(RunSpecError):
          validate_scientific_sealed_declaration(
              sealed_input=sealed,
              attestation=attestation,
              pair_index_manifest=pim,
              pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
              run_dir=spec.run_dir,
          )


  def test_audit_path_mismatch_rejects(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      spec, attestation, pim = _parts(bundle)
      sealed = dict(spec.scientific["sealed_input"])
      sealed["audit_path"] = str(Path(spec.run_dir) / "not_audit.jsonl")
      with pytest.raises(RunSpecError, match="audit"):
          validate_scientific_sealed_declaration(
              sealed_input=sealed,
              attestation=attestation,
              pair_index_manifest=pim,
              pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
              run_dir=spec.run_dir,
          )


  def test_pair_index_row_identity_mismatch_rejects(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      spec, attestation, pim = _parts(bundle)
      bad_attestation = dict(attestation)
      bad_attestation["source_row_identity_sha256"] = "1" * 64
      with pytest.raises(RunSpecError):
          validate_scientific_sealed_declaration(
              sealed_input=spec.scientific["sealed_input"],
              attestation=bad_attestation,
              pair_index_manifest=pim,
              pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
              run_dir=spec.run_dir,
          )
  ```

- [ ] **Step 2: Run, expect import FAIL.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_sealed_declaration.py -q`
  Expected: `ImportError: cannot import name 'validate_scientific_sealed_declaration'`.

- [ ] **Step 3: Implement the validator** in `src/alive/compose/driver/pair_index.py`. Add the import
  and the function (after `validate_pair_index_manifest_preseal`):
  ```python
  import os

  from alive.compose.durable import SEAL_AUDIT_FILENAME


  def validate_scientific_sealed_declaration(
      *,
      sealed_input: Mapping[str, Any],
      attestation: Mapping[str, Any],
      pair_index_manifest: Mapping[str, Any],
      pair_index_manifest_file_sha256: str,
      run_dir: str,
  ) -> None:
      """Prove the scientific sealed_input binds to the owner attestation (§2.2) — lexical only.

      Reuses :func:`validate_pair_index_manifest_preseal` for the attestation shape + the
      manifest↔attestation (pair-index file SHA, source-file SHA, row-identity) bindings, then
      adds the sealed_input-specific equalities. The source path is checked as a STRING only: no
      ``resolve``, ``stat``, hash, AnnData parse, or source open. Source node identity + byte
      integrity remain Phase-2b-after-confirmation work.
      """
      validate_pair_index_manifest_preseal(
          pair_index_manifest,
          attestation=attestation,
          pair_index_manifest_file_sha256=pair_index_manifest_file_sha256,
      )
      if sealed_input.get("source_path") != attestation.get("canonical_source_path"):
          raise RunSpecError(
              "scientific sealed_input.source_path != attestation.canonical_source_path"
          )
      if sealed_input.get("expected_file_sha256") != attestation.get("expected_source_file_sha256"):
          raise RunSpecError(
              "scientific sealed_input.expected_file_sha256 != "
              "attestation.expected_source_file_sha256"
          )
      if sealed_input.get("snapshot_id") != attestation.get("snapshot_id"):
          raise RunSpecError("scientific sealed_input.snapshot_id != attestation.snapshot_id")
      expected_audit = os.path.normpath(os.path.join(str(run_dir), SEAL_AUDIT_FILENAME))
      declared_audit = os.path.normpath(str(sealed_input.get("audit_path")))
      if declared_audit != expected_audit:
          raise RunSpecError(
              f"scientific sealed_input.audit_path ({declared_audit}) != "
              f"normalized <run_dir>/{SEAL_AUDIT_FILENAME} ({expected_audit})"
          )
  ```
  Add `validate_scientific_sealed_declaration` to the module `__all__`. If importing
  `alive.compose.durable` risks a cycle, keep it a top-level import (durable does not import
  pair_index); confirm with `.venv/bin/python -c "import alive.compose.driver.pair_index"`.

- [ ] **Step 4: Run, expect PASS.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_sealed_declaration.py -q`
  Expected: `6 passed` (1 positive + 3 parametrized + audit + row-identity).

- [ ] **Step 5: Ruff + commit.**
  ```
  git add src/alive/compose/driver/pair_index.py \
          tests/alive/compose/driver/test_scientific_sealed_declaration.py
  git commit -m "feat(compose-carrier): sealed_input ↔ attestation equality validator, no source access (§2.2)

  validate_scientific_sealed_declaration proves source_path / expected_file_sha256 / snapshot_id
  / run-bound audit_path equality and (via validate_pair_index_manifest_preseal) the pair-index
  file/source/row bindings — lexical only, no resolve/stat/hash/AnnData/open of the sealed source.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HPoPEh5tLhsjgavBgmcmXV"
  ```

---

## Task 6: `ActivationRecord` assembly + `assert_scientific_mode_allowed` validation

Assemble the `ActivationRecord` from the validated scientific block + config, then re-validate it
through the existing `assert_scientific_mode_allowed` guard (§2.1 / §5 step 4).

**Files**
- Modify `src/alive/compose/driver/carrier_loader.py` — add `_assemble_activation_record(spec, config,
  git_is_clean)`.
- Create `tests/alive/compose/driver/test_scientific_activation_assembly.py`.

**Interfaces**
- Consumes: `alive.compose.config2.{ActivationRecord, assert_scientific_mode_allowed,
  load_compose_phase2_config, ScientificModeError}`; the validated `spec.scientific
  ["activation_evidence"]`.
- Produces:
  ```python
  def _assemble_activation_record(
      spec: ResolvedRunSpec, config: ComposePhase2Config, *, git_is_clean: bool
  ) -> ActivationRecord: ...
  ```
  Builds owner from `activation_evidence.owner`, protocol/phase from config, `evidence_hashes` /
  `evidence_files` from the exact requirement roster; requires
  `requirements.keys() == set(config.activation_requirements)`; then calls
  `assert_scientific_mode_allowed(config, activation_record=record, git_is_clean=git_is_clean)`.

Steps:

- [ ] **Step 1: Write the failing test.** Create
  `tests/alive/compose/driver/test_scientific_activation_assembly.py`:
  ```python
  """ActivationRecord assembly + scientific-mode re-validation (spec §2.1 / §5 step 4)."""

  from __future__ import annotations

  import json
  from pathlib import Path

  import pytest

  from alive.compose.config2 import (
      ActivationRecord,
      ScientificModeError,
      load_compose_phase2_config,
  )
  from alive.compose.driver.carrier_loader import _assemble_activation_record
  from alive.compose.driver.run_spec import load_resolved_run_spec
  from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture


  def _spec_config(bundle):
      spec = load_resolved_run_spec(
          bundle.spec_path,
          approved_artifacts_root=bundle.approved_artifacts_root,
          mode_expected="scientific",
      )
      config = load_compose_phase2_config(spec.pre_seal["config"].path)
      return spec, config


  def test_activation_record_assembles_and_validates(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      spec, config = _spec_config(bundle)
      record = _assemble_activation_record(spec, config, git_is_clean=True)
      assert isinstance(record, ActivationRecord)
      assert record.owner == "owner@example.org"
      assert record.approved_protocol == config.protocol
      assert record.approved_phase == config.phase
      assert set(record.evidence_hashes) == set(config.activation_requirements)
      assert set(record.evidence_files) == set(config.activation_requirements)


  def test_git_not_clean_rejects(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      spec, config = _spec_config(bundle)
      with pytest.raises(ScientificModeError, match="clean"):
          _assemble_activation_record(spec, config, git_is_clean=False)


  def test_stale_config_bound_report_rejects(tmp_path):
      # A config-bound report whose config_sha256 no longer matches the activated config rejects.
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      spec, config = _spec_config(bundle)
      reqs = spec.scientific["activation_evidence"]["requirements"]
      report_path = Path(reqs["real_norman_phi_rank_and_condition_report"]["path"])
      payload = json.loads(report_path.read_text(encoding="utf-8"))
      payload["config_sha256"] = "deadbeef" * 8
      report_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
      with pytest.raises(ScientificModeError):
          # note: the byte-SHA check is in run_spec (Task 2); here the record's evidence hash still
          # points at the mutated file, so assert_scientific_mode_allowed's config-lineage parse trips.
          record = ActivationRecord(
              owner="owner@example.org",
              approved_protocol=config.protocol,
              approved_phase=config.phase,
              approved_git_sha=spec.approved_git_sha,
              evidence_hashes={
                  r: reqs[r]["sha256"] for r in config.activation_requirements
              },
              evidence_files={r: reqs[r]["path"] for r in config.activation_requirements},
          )
          from alive.compose.config2 import assert_scientific_mode_allowed

          assert_scientific_mode_allowed(config, activation_record=record, git_is_clean=True)
  ```

- [ ] **Step 2: Run, expect import FAIL.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_activation_assembly.py -q`
  Expected: `ImportError: cannot import name '_assemble_activation_record'`.

- [ ] **Step 3: Implement the assembler** in `src/alive/compose/driver/carrier_loader.py`. Extend the
  config2 import and add the helper:
  ```python
  from alive.compose.config2 import (
      ActivationRecord,
      ComposePhase2Config,
      assert_scientific_mode_allowed,
      load_compose_phase2_config,
  )


  def _assemble_activation_record(
      spec: ResolvedRunSpec, config: ComposePhase2Config, *, git_is_clean: bool
  ) -> ActivationRecord:
      """Build + re-validate the owner ActivationRecord from the scientific block (§2.1)."""
      evidence = spec.scientific["activation_evidence"]
      requirements = evidence["requirements"]
      expected = set(config.activation_requirements)
      if set(requirements) != expected:
          raise RunSpecError(
              "activation_evidence.requirements must equal config.activation_requirements exactly: "
              f"missing={sorted(expected - set(requirements))} "
              f"extra={sorted(set(requirements) - expected)}"
          )
      record = ActivationRecord(
          owner=evidence["owner"],
          approved_protocol=config.protocol,
          approved_phase=config.phase,
          approved_git_sha=spec.approved_git_sha,
          evidence_hashes={req: requirements[req]["sha256"] for req in config.activation_requirements},
          evidence_files={req: requirements[req]["path"] for req in config.activation_requirements},
      )
      assert_scientific_mode_allowed(config, activation_record=record, git_is_clean=git_is_clean)
      return record
  ```

- [ ] **Step 4: Run, expect PASS.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_activation_assembly.py -q`
  Expected: `3 passed`. (The positive path proves the activated test-only config + config-bound
  reports + complete dependency lock satisfy the real guard end-to-end.)

- [ ] **Step 5: Ruff + commit.**
  ```
  git add src/alive/compose/driver/carrier_loader.py \
          tests/alive/compose/driver/test_scientific_activation_assembly.py
  git commit -m "feat(compose-carrier): assemble + re-validate ActivationRecord via assert_scientific_mode_allowed (§2.1)

  Owner from activation_evidence, protocol/phase from config, evidence hashes/files from the exact
  requirement roster (== config.activation_requirements), then the existing scientific-mode guard
  re-checks status/blockers/owner/protocol/phase/roster/digest/bytes/config-bound lineage.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HPoPEh5tLhsjgavBgmcmXV"
  ```

---

## Task 7: Typed `ActivationProvenanceInputs` assembly (§4)

Assemble the typed `ActivationProvenanceInputs` for Phase-2b via the existing
`build_activation_provenance_inputs` helper, mapping each argument to its authoritative source per §4,
honouring the processed-vs-raw asset caveat.

**Files**
- Modify `src/alive/compose/driver/carrier_loader.py` — add `_assemble_provenance_inputs(spec, config,
  environment)` + a `_processed_asset_path` guard.
- Create `tests/alive/compose/driver/test_scientific_provenance_assembly.py`.

**Interfaces**
- Consumes: `alive.compose.phase2b.{ActivationProvenanceInputs, build_activation_provenance_inputs}`;
  `spec.pre_seal["raw_asset"|"feature_bank"]`, `spec.scientific["dependency_manifest"|"device"|
  "precision"]`, `spec.worker_blocks["gears"|"cpa"].requirements_lock`, the validated data card.
- Produces:
  ```python
  def _assemble_provenance_inputs(
      spec: ResolvedRunSpec, config: ComposePhase2Config, *, environment: EnvironmentInfo
  ) -> ActivationProvenanceInputs: ...
  ```

Steps:

- [ ] **Step 1: Write the failing test.** Create
  `tests/alive/compose/driver/test_scientific_provenance_assembly.py`:
  ```python
  """Typed ActivationProvenanceInputs assembly (spec §4)."""

  from __future__ import annotations

  from pathlib import Path

  import pytest

  from alive.compose.config2 import load_compose_phase2_config
  from alive.compose.driver.carrier_loader import _assemble_provenance_inputs
  from alive.compose.driver.run_spec import load_resolved_run_spec
  from alive.compose.phase2b import ActivationProvenanceInputs
  from alive.provenance import capture_environment, sha256_file
  from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture


  def _spec_config_env(bundle):
      spec = load_resolved_run_spec(
          bundle.spec_path,
          approved_artifacts_root=bundle.approved_artifacts_root,
          mode_expected="scientific",
      )
      config = load_compose_phase2_config(spec.pre_seal["config"].path)
      env = capture_environment(
          spec.scientific["dependency_manifest"]["path"],
          config.registered_seeds,
          repo_dir=bundle.repo_root,
      )
      return spec, config, env


  def test_provenance_inputs_map_to_authoritative_sources(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      spec, config, env = _spec_config_env(bundle)
      inputs = _assemble_provenance_inputs(spec, config, environment=env)
      assert isinstance(inputs, ActivationProvenanceInputs)
      # processed_sha256 == raw_asset digest (data card declares raw asset as processed).
      assert inputs.processed_sha256 == sha256_file(spec.pre_seal["raw_asset"].path)
      assert inputs.feature_bank_sha256 == sha256_file(spec.pre_seal["feature_bank"].path)
      assert inputs.gears_revision == "0.1.2"
      assert inputs.cpa_revision == "0.8.5"
      assert inputs.device == "cpu"
      assert inputs.precision == "float32"
      assert inputs.git_commit == bundle.approved_git_sha


  def test_data_card_not_declaring_processed_asset_rejects(tmp_path):
      # If the data card does not identify the raw asset as the processed analysis asset,
      # assembly fails closed rather than recording a raw digest as processed_sha256 (§4).
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      spec, config, env = _spec_config_env(bundle)
      import json

      card_path = Path(spec.pre_seal["data_card"].path)
      card = json.loads(card_path.read_text(encoding="utf-8"))
      card.pop("processed_analysis_asset")
      card_path.write_text(json.dumps(card, sort_keys=True, separators=(",", ":")))
      with pytest.raises(ValueError, match="processed"):
          _assemble_provenance_inputs(spec, config, environment=env)
  ```

- [ ] **Step 2: Run, expect import FAIL.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_provenance_assembly.py -q`
  Expected: `ImportError: cannot import name '_assemble_provenance_inputs'`.

- [ ] **Step 3: Implement the assembler** in `src/alive/compose/driver/carrier_loader.py`. Extend the
  phase2b import and add the helpers:
  ```python
  from alive.compose.phase2b import (
      ActivationProvenanceInputs,
      build_activation_provenance_inputs,
  )


  def _processed_asset_path(spec: ResolvedRunSpec) -> str:
      """Return raw_asset.path ONLY if the validated data card declares it the processed asset (§4).

      The final PREPARE schema must add a separately verified ``processed_asset`` field if the raw
      asset is genuinely raw; until then this refuses to record a raw-file digest as
      ``processed_sha256`` unless the data card binds the raw asset AS the processed analysis asset.
      """
      raw = spec.pre_seal["raw_asset"]
      card = _read_json(spec.pre_seal["data_card"].path)
      declared = card.get("processed_analysis_asset")
      if not isinstance(declared, dict) or declared.get("sha256") != raw.sha256:
          raise RunSpecError(
              "data card does not identify raw_asset as the processed analysis asset; refusing to "
              "record a raw-file digest as processed_sha256 (spec §4 requires a separate "
              "processed_asset field for a genuinely raw asset)"
          )
      return raw.path


  def _assemble_provenance_inputs(
      spec: ResolvedRunSpec, config: ComposePhase2Config, *, environment: EnvironmentInfo
  ) -> ActivationProvenanceInputs:
      """Build the typed Phase-2b provenance via the existing helper (§4 authoritative-source map)."""
      scientific = spec.scientific
      return build_activation_provenance_inputs(
          processed_path=_processed_asset_path(spec),
          feature_bank_path=spec.pre_seal["feature_bank"].path,
          dependency_lock_path=scientific["dependency_manifest"]["path"],
          gears_requirements_path=spec.worker_blocks["gears"].requirements_lock.path,
          cpa_requirements_path=spec.worker_blocks["cpa"].requirements_lock.path,
          environment=environment,
          device=scientific["device"],
          precision=scientific["precision"],
      )
  ```
  `_processed_asset_path` raises `RunSpecError`, but the test expects `ValueError` — `RunSpecError`
  subclasses `ValueError`, so `pytest.raises(ValueError, match="processed")` matches.

- [ ] **Step 4: Run, expect PASS.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_provenance_assembly.py -q`
  Expected: `2 passed`. (`build_activation_provenance_inputs` derives `gears_revision` /
  `cpa_revision` from the worker requirement-lock pins `cell-gears==0.1.2` / `cpa-tools==0.8.5`.)

- [ ] **Step 5: Ruff + commit.**
  ```
  git add src/alive/compose/driver/carrier_loader.py \
          tests/alive/compose/driver/test_scientific_provenance_assembly.py
  git commit -m "feat(compose-carrier): typed ActivationProvenanceInputs assembly via §4 source map

  Maps processed/feature/dependency/gears/cpa/environment/device/precision to their authoritative
  sources through build_activation_provenance_inputs, with a data-card guard that refuses to record
  a raw-file digest as processed_sha256 unless the card binds the raw asset as the processed asset.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HPoPEh5tLhsjgavBgmcmXV"
  ```

---

## Task 8: `load_run_spec_carrier` scientific branch + `trusted_repo_root` + CLI threading

Wire the scientific reconstruction path per the §5 assembly order behind a new
`trusted_repo_root: Path | None = None` parameter (scientific requires it; fixture requires it `None`).
Add the scientific sealed-outcome deserializer, and thread the out-of-band trusted root through the
CLI for scientific commands, mapping the two new fail-closed error types to exit 10.

**Files**
- Modify `src/alive/compose/driver/carrier_loader.py` — add `trusted_repo_root` to
  `load_run_spec_carrier`; scientific branch (replaces the `UnsupportedModeError` raise at :161-166);
  add `_load_scientific_sealed_outcome(spec)`.
- Modify `src/alive/compose/driver/cli.py` — add `--trusted-repo-root` (default `None`) to the
  run-spec subcommands; thread it into `_build_run_spec_carrier`; add `ScientificRuntimeError` and
  `ScientificModeError` to `_KNOWN_PRESEAL_REJECTIONS`.
- Create `tests/alive/compose/driver/test_scientific_carrier_load.py`.

**Interfaces**
- Consumes: everything assembled in Tasks 2-7 + `resolve_scientific_runtime_context`,
  `validate_scientific_sealed_declaration`.
- Produces:
  ```python
  def load_run_spec_carrier(
      spec_path, *, approved_artifacts_root, trusted_repo_root: Path | None = None
  ) -> RunSpecCarrier: ...

  def _load_scientific_sealed_outcome(spec) -> dict[str, Any]:  # NO corpus attestation triple
      ...
  ```

Steps:

- [ ] **Step 1: Write the failing test.** Create `tests/alive/compose/driver/test_scientific_carrier_load.py`:
  ```python
  """Full scientific carrier assembly (spec §5) + trusted_repo_root gating."""

  from __future__ import annotations

  from pathlib import Path

  import pytest

  from alive.compose.config2 import ActivationRecord
  from alive.compose.driver.carrier_loader import (
      RunSpecCarrier,
      load_run_spec_carrier,
  )
  from alive.compose.driver.run_spec import RunSpecError
  from alive.compose.phase2b import ActivationProvenanceInputs
  from alive.provenance import EnvironmentInfo
  from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture


  def test_scientific_carrier_fully_assembles(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      carrier = load_run_spec_carrier(
          bundle.spec_path,
          approved_artifacts_root=bundle.approved_artifacts_root,
          trusted_repo_root=bundle.repo_root,
      )
      assert isinstance(carrier, RunSpecCarrier)
      assert carrier.mode == "scientific"
      assert isinstance(carrier.activation_record, ActivationRecord)
      assert carrier.git_is_clean is True
      assert isinstance(carrier.environment, EnvironmentInfo)
      assert carrier.environment.git_commit == bundle.approved_git_sha
      assert isinstance(carrier.provenance_inputs, ActivationProvenanceInputs)
      assert Path(carrier.data_card_path).is_file()
      assert Path(carrier.raw_asset_path).is_file()
      # scientific sealed_outcome carries the phase2b-consumed keys, NOT the corpus triple.
      assert set(carrier.sealed_outcome) == {
          "manifest",
          "pair_index",
          "pair_index_manifest",
          "source_path",
          "source_file_sha256",
          "perturbation_column",
          "combo_sep",
      }


  def test_scientific_requires_trusted_repo_root(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      with pytest.raises(RunSpecError, match="trusted_repo_root"):
          load_run_spec_carrier(
              bundle.spec_path, approved_artifacts_root=bundle.approved_artifacts_root
          )


  def test_fixture_rejects_trusted_repo_root(tmp_path):
      from alive.compose.driver.fixture_builder import build_compose_fixture

      bundle = build_compose_fixture(tmp_path)
      with pytest.raises(RunSpecError, match="trusted_repo_root"):
          load_run_spec_carrier(
              bundle.spec_path,
              approved_artifacts_root=bundle.approved_artifacts_root,
              trusted_repo_root=tmp_path,
          )


  def test_wrong_head_fails_closed(tmp_path):
      from alive.compose.driver.scientific_runtime import ScientificRuntimeError

      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      import subprocess

      (bundle.repo_root / "extra.txt").write_text("x\n", encoding="utf-8")
      subprocess.run(["git", "add", "extra.txt"], cwd=bundle.repo_root, check=True)
      subprocess.run(
          ["git", "commit", "-q", "-m", "advance"], cwd=bundle.repo_root, check=True,
          env={**__import__("os").environ, "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
      )
      # HEAD moved; the spec's approved_git_sha is now stale → fail closed.
      with pytest.raises(ScientificRuntimeError):
          load_run_spec_carrier(
              bundle.spec_path,
              approved_artifacts_root=bundle.approved_artifacts_root,
              trusted_repo_root=bundle.repo_root,
          )
  ```

- [ ] **Step 2: Run, expect FAIL.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_carrier_load.py -q`
  Expected: `test_scientific_carrier_fully_assembles` FAILS with `UnsupportedModeError` (the loader
  still raises for scientific); `test_scientific_requires_trusted_repo_root` /
  `test_fixture_rejects_trusted_repo_root` FAIL (`load_run_spec_carrier` has no `trusted_repo_root`
  param → `TypeError`).

- [ ] **Step 3: Implement the scientific branch + gating.** In
  `src/alive/compose/driver/carrier_loader.py`, add imports:
  ```python
  from alive.compose.driver.pair_index import validate_scientific_sealed_declaration
  from alive.compose.driver.scientific_runtime import resolve_scientific_runtime_context
  ```
  Replace the `load_run_spec_carrier` signature + mode dispatch (:121-176):
  ```python
  def load_run_spec_carrier(
      spec_path: str | Path,
      *,
      approved_artifacts_root: str | Path,
      trusted_repo_root: str | Path | None = None,
  ) -> RunSpecCarrier:
      """Reconstruct the stage-1 DATA carrier from a ResolvedRunSpec's on-disk artifacts.

      Fixture mode requires ``trusted_repo_root is None`` and reconstructs the five DATA fields.
      Scientific mode requires the out-of-band ``trusted_repo_root`` and, after loading + validating
      the spec, additionally validates the nested scientific block + sealed attestation, resolves the
      runtime git/environment identity against ``approved_git_sha``, builds + re-validates the owner
      ActivationRecord, assembles typed Phase-2b provenance, and constructs a scientific carrier via
      its scientific-only constructor. It opens no seal and constructs no store.
      """
      spec_path = Path(spec_path)
      mode = _peek_mode(spec_path)
      if mode == "fixture":
          if trusted_repo_root is not None:
              raise RunSpecError(
                  "fixture mode does not accept trusted_repo_root (disk-only carrier); pass None"
              )
          spec = load_resolved_run_spec(
              spec_path, approved_artifacts_root=approved_artifacts_root, mode_expected="fixture"
          )
          return RunSpecCarrier._fixture(
              spec_path=spec_path,
              phase2a_inputs=_load_phase2a_inputs(spec),
              dev_store_audit=_load_dev_store_audit(spec),
              response_artifact=_load_response_artifact(spec),
              sealed_outcome=_load_sealed_outcome(spec),
          )

      # scientific -----------------------------------------------------------
      if trusted_repo_root is None:
          raise RunSpecError(
              "scientific mode requires an out-of-band trusted_repo_root (never selected by the "
              "run spec); got None"
          )
      # §5.1: load + fully validate the spec (validates nested scientific schema + pre-seal bytes).
      spec = load_resolved_run_spec(
          spec_path, approved_artifacts_root=approved_artifacts_root, mode_expected="scientific"
      )
      # §5.2: sealed attestation equality (no source access).
      attestation = _read_json(spec.pre_seal["approved_sealed_input_attestation"].path)
      pair_index_manifest = _read_json(spec.pre_seal["pair_index_manifest"].path)
      validate_scientific_sealed_declaration(
          sealed_input=spec.scientific["sealed_input"],
          attestation=attestation,
          pair_index_manifest=pair_index_manifest,
          pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
          run_dir=spec.run_dir,
      )
      config = load_compose_phase2_config(spec.pre_seal["config"].path)
      # §5.3: runtime git/environment identity (fail closed vs approved_git_sha).
      context = resolve_scientific_runtime_context(
          trusted_repo_root=Path(trusted_repo_root),
          approved_git_sha=spec.approved_git_sha,
          lockfile_path=Path(spec.scientific["dependency_manifest"]["path"]),
          registered_seeds=config.registered_seeds,
      )
      # §5.4: config + ActivationRecord (re-validated through assert_scientific_mode_allowed).
      activation_record = _assemble_activation_record(
          spec, config, git_is_clean=context.git_is_clean
      )
      # §5.5-6: reuse deserializers + typed provenance.
      provenance_inputs = _assemble_provenance_inputs(spec, config, environment=context.environment)
      # §5.7: construct through the scientific-only constructor.
      return RunSpecCarrier._scientific(
          spec_path=spec_path,
          phase2a_inputs=_load_phase2a_inputs(spec),
          dev_store_audit=_load_dev_store_audit(spec),
          response_artifact=_load_response_artifact(spec),
          sealed_outcome=_load_scientific_sealed_outcome(spec),
          activation_record=activation_record,
          git_is_clean=context.git_is_clean,
          environment=context.environment,
          data_card_path=Path(spec.pre_seal["data_card"].path),
          raw_asset_path=Path(spec.pre_seal["raw_asset"].path),
          provenance_inputs=provenance_inputs,
      )
  ```
  Keep `UnsupportedModeError` in `__all__` and defined (it remains a valid subclass for any future
  unknown mode, and `_peek_mode` still rejects unrecognised modes via `RunSpecError`). Add the
  scientific sealed-outcome deserializer (§3: the phase2b-consumed keys only, source from the
  scientific block, NO corpus triple):
  ```python
  def _load_scientific_sealed_outcome(spec: ResolvedRunSpec) -> dict[str, Any]:
      """Rehydrate the scientific sealed-outcome DATA ``phase2b`` builds its store FROM (§3).

      Carries only the fields ``_build_sealed_store`` consumes — split manifest, pair index,
      pair-index manifest, declared source path/SHA (from the scientific ``sealed_input``),
      perturbation column and combo separator. It NEVER carries the fixture corpus attestation
      triple. No outcome bytes are read (``phase2b`` opens the source ``O_NOFOLLOW`` at seal time).
      """
      pair_index_manifest = _read_json(spec.pre_seal["pair_index_manifest"].path)
      split_manifest = _read_json(spec.pre_seal["pair_manifest"].path)
      pair_index = {
          (str(entry["gene_a"]), str(entry["gene_b"])): np.asarray(
              entry["row_indices"], dtype=np.int64
          )
          for entry in pair_index_manifest["pairs"]
      }
      sealed_input = spec.scientific["sealed_input"]
      return {
          "manifest": split_manifest,
          "pair_index": pair_index,
          "pair_index_manifest": pair_index_manifest,
          "source_path": Path(sealed_input["source_path"]),
          "source_file_sha256": str(sealed_input["expected_file_sha256"]),
          "perturbation_column": str(pair_index_manifest["perturbation_column"]),
          "combo_sep": str(pair_index_manifest["combo_sep"]),
      }
  ```

- [ ] **Step 4: Thread the trusted root through the CLI.** In `src/alive/compose/driver/cli.py`:
  - In `_add_run_spec_flags` add: `sp.add_argument("--trusted-repo-root", type=Path, default=None)`.
  - Change `_build_run_spec_carrier`:
    ```python
    def _build_run_spec_carrier(
        spec_path: Path, approved_artifacts_root: Path, trusted_repo_root: Path | None
    ) -> RunSpecCarrier:
        return load_run_spec_carrier(
            spec_path,
            approved_artifacts_root=approved_artifacts_root,
            trusted_repo_root=trusted_repo_root,
        )
    ```
    and its single call site in `main`:
    ```python
        carrier = _build_run_spec_carrier(
            args.run_spec, args.approved_artifacts_root, args.trusted_repo_root
        )
    ```
  - Import and register the two fail-closed error types:
    ```python
    from alive.compose.config2 import ScientificModeError
    from alive.compose.driver.scientific_runtime import ScientificRuntimeError
    ```
    and add both to `_KNOWN_PRESEAL_REJECTIONS` (they are pre-seal, fail-closed → exit 10):
    ```python
        AssemblerError,
        ScientificModeError,      # scientific-mode guard rejection (pre-seal, exit 10)
        ScientificRuntimeError,   # runtime git/environment identity rejection (pre-seal, exit 10)
    ```

- [ ] **Step 5: Run, expect PASS.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_carrier_load.py -q`
  Expected: `4 passed`. Then confirm no import cycle and the fixture path still green:
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_carrier_loader.py -q` → all pass.

- [ ] **Step 6: Ruff + commit.**
  ```
  git add src/alive/compose/driver/carrier_loader.py src/alive/compose/driver/cli.py \
          tests/alive/compose/driver/test_scientific_carrier_load.py
  git commit -m "feat(compose-carrier): scientific load_run_spec_carrier branch + trusted_repo_root + CLI wiring (§5)

  Replaces the scientific UnsupportedModeError with the §5 assembly: nested schema + sealed
  attestation + runtime git identity + ActivationRecord + typed provenance + scientific-only
  carrier construction. Adds trusted_repo_root (scientific requires it, fixture requires None),
  a corpus-triple-free scientific sealed_outcome, CLI --trusted-repo-root threading, and maps
  ScientificModeError / ScientificRuntimeError to the exit-10 pre-seal rejection family.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HPoPEh5tLhsjgavBgmcmXV"
  ```

---

## Task 9: Phase-2a environment plumbing (kill the `UNKNOWN` placeholder)

Make `phase2a_cmd`'s scientific dispatch pass `environment=run_spec.environment` so the run records the
real captured `EnvironmentInfo` (not the fixture `git_commit="UNKNOWN"` placeholder), which Phase-2b
provenance later cross-checks (§4 / §6.6). Because `_assemble_adapters` fails closed at sub-project B
BEFORE `run_phase2a` in the full path, this behaviour is verified with a focused unit test that
isolates the dispatch plumbing.

**Files**
- Modify `src/alive/compose/driver/phase2a_cmd.py` — add `environment=run_spec.environment` to the
  scientific `run_phase2a(...)` call (:207-220).
- Create `tests/alive/compose/driver/test_phase2a_env_plumbing.py`.

**Interfaces**
- Consumes: `run_spec.environment` (the carrier's `EnvironmentInfo`).
- Produces: the scientific `run_phase2a` call now forwards `environment=run_spec.environment`.

Steps:

- [ ] **Step 1: Write the failing test** isolating the dispatch. `_assemble_adapters` is stubbed to
  bypass the (unrelated-to-this-task) B boundary, and `run_phase2a` is replaced by a spy that captures
  the `environment` kwarg then raises a sentinel so no persistence runs. Create
  `tests/alive/compose/driver/test_phase2a_env_plumbing.py`:
  ```python
  """Scientific phase2a dispatch forwards the real EnvironmentInfo, never UNKNOWN (spec §6.6)."""

  from __future__ import annotations

  import pytest

  from alive.compose.driver import phase2a_cmd
  from alive.compose.driver.carrier_loader import load_run_spec_carrier
  from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture


  class _Sentinel(RuntimeError):
      pass


  def test_scientific_dispatch_forwards_environment(tmp_path, monkeypatch):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      carrier = load_run_spec_carrier(
          bundle.spec_path,
          approved_artifacts_root=bundle.approved_artifacts_root,
          trusted_repo_root=bundle.repo_root,
      )
      assert carrier.environment.git_commit == bundle.approved_git_sha
      assert carrier.environment.git_commit != "UNKNOWN"

      captured: dict = {}

      # Isolate the dispatch: bypass the sub-project-B adapter boundary (not under test here)…
      monkeypatch.setattr(phase2a_cmd, "_assemble_adapters", lambda *a, **k: {})

      # …and spy the library entry point to capture the environment kwarg.
      def _spy(*args, **kwargs):
          captured["environment"] = kwargs.get("environment")
          raise _Sentinel

      monkeypatch.setattr(phase2a_cmd, "run_phase2a", _spy)

      with pytest.raises(_Sentinel):
          phase2a_cmd.run_phase2a_subcommand(
              carrier,
              approved_artifacts_root=bundle.approved_artifacts_root,
              run_dir=bundle.run_dir,
          )
      assert captured["environment"] is carrier.environment
      assert captured["environment"].git_commit == bundle.approved_git_sha
  ```

- [ ] **Step 2: Run, expect FAIL.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_phase2a_env_plumbing.py -q`
  Expected: FAILS with `assert captured["environment"] is carrier.environment` — the current
  scientific `run_phase2a(...)` call omits `environment=`, so the spy captures `None`.

- [ ] **Step 3: Implement the one-line plumbing.** In `src/alive/compose/driver/phase2a_cmd.py`, the
  scientific `run_phase2a(...)` call, add the `environment` argument:
  ```python
          result = run_phase2a(
              inputs,
              dev_store,
              expected_hashes=dict(spec.expected_hashes),
              config=config,
              bundle_path=bundle_path,
              baseline_adapters=adapters,
              oof_manifest_path=oof_manifest_path,
              environment=run_spec.environment,
              activation_record=run_spec.activation_record,
              git_is_clean=run_spec.git_is_clean,
              data_card_path=run_spec.data_card_path,
              raw_asset_path=run_spec.raw_asset_path,
              response_artifact=scientific_response,
          )
  ```

- [ ] **Step 4: Run, expect PASS.**
  `.venv/bin/python -m pytest tests/alive/compose/driver/test_phase2a_env_plumbing.py -q`
  Expected: `1 passed`. The fixture dispatch (`run_phase2a_fixture`) is untouched and its call takes
  no `environment` argument (it uses the placeholder deliberately), so
  `tests/alive/compose/driver/test_carrier_loader.py` stays green.

- [ ] **Step 5: Ruff + commit.**
  ```
  git add src/alive/compose/driver/phase2a_cmd.py \
          tests/alive/compose/driver/test_phase2a_env_plumbing.py
  git commit -m "fix(compose-carrier): scientific phase2a forwards captured EnvironmentInfo (§4/§6.6)

  The scientific run_phase2a dispatch now passes environment=run_spec.environment so the ledger
  records the real git_commit instead of the fixture UNKNOWN placeholder, which Phase-2b
  provenance later cross-checks against the ledger environment.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HPoPEh5tLhsjgavBgmcmXV"
  ```

---

## Task 10: Hermetic B-boundary through the full CLI + structural seal safety

Demonstrate that the full scientific CLI assembles the carrier, reaches
`assemble_execution_identity_lock`, and fails closed on the absent committed scientific
`adapter_version` (sub-project B) — creating NO run-produced file/store, leaving the seal/audit
untouched, and making NO false D2 claim (§6.7). Confirm the §4.3 structural seal-safety tests remain
unchanged and green (§6.8).

**Files**
- Create `tests/alive/compose/driver/test_scientific_cli_b_boundary.py`.
- No production change (this task is verification-only; the B boundary is already fail-closed in
  `identity_lock.py::_scientific_adapter_version`).

**Interfaces**
- Consumes: `alive.compose.driver.cli.main`; `alive.compose.driver.cli.PRESEAL_REJECT_EXIT` (10);
  `alive.compose.driver.identity_lock.AssemblerError`.

Steps:

- [ ] **Step 1: Write the B-boundary + safety test.** Create
  `tests/alive/compose/driver/test_scientific_cli_b_boundary.py`:
  ```python
  """Full scientific CLI reaches + fails closed at sub-project B's adapter_version (spec §6.7/§6.8).

  This does NOT claim D2 (or any Phase-2a/D2/Phase-2b) was reached: _assemble_adapters resolves
  worker identity BEFORE run_phase2a, so the first scientific failure IS the B boundary. No store
  is constructed, no seal is opened, no audit is written, and no run-produced artifact appears.
  """

  from __future__ import annotations

  from pathlib import Path

  import pytest

  from alive.compose.driver import cli
  from alive.compose.driver.identity_lock import _COMMITTED_ADAPTER_MANIFEST
  from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture


  def _argv(bundle, subcommand="phase2a"):
      return [
          subcommand,
          "--run-spec",
          str(bundle.spec_path),
          "--approved-artifacts-root",
          str(bundle.approved_artifacts_root),
          "--run-dir",
          str(bundle.run_dir),
          "--trusted-repo-root",
          str(bundle.repo_root),
      ]


  def test_committed_adapter_manifest_still_absent():
      # The B boundary is exactly this: no committed scientific adapter manifest exists yet.
      assert _COMMITTED_ADAPTER_MANIFEST is None


  def test_full_scientific_cli_fails_closed_at_b(tmp_path, capsys):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      rc = cli.main(_argv(bundle))
      assert rc == cli.PRESEAL_REJECT_EXIT  # 10
      err = capsys.readouterr().err
      assert "AssemblerError" in err
      assert "adapter" in err.lower()


  def test_no_run_produced_artifact_no_seal_no_audit(tmp_path):
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      rc = cli.main(_argv(bundle))
      assert rc == cli.PRESEAL_REJECT_EXIT
      # run_dir holds NO run-produced artifact and NO audit.jsonl (the seal never opened).
      present = sorted(p.name for p in Path(bundle.run_dir).iterdir())
      assert present == []
      assert not (Path(bundle.run_dir) / "audit.jsonl").exists()
      assert not (Path(bundle.run_dir) / "seal_confirmation_manifest.json").exists()


  def test_b_boundary_is_reached_not_a_spec_rejection(tmp_path, monkeypatch, capsys):
      # Prove the failure is the B ADAPTER boundary, not an earlier carrier-validation reject:
      # a monkeypatched committed manifest path would let assembly proceed past _scientific_adapter_version
      # into its (still-unimplemented) resolver — which raises a DISTINCT AssemblerError. We assert the
      # UNPATCHED message names the missing committed manifest, i.e. B specifically.
      bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
      rc = cli.main(_argv(bundle))
      assert rc == cli.PRESEAL_REJECT_EXIT
      err = capsys.readouterr().err
      assert "no committed" in err.lower() and "adapter_version" in err
  ```

- [ ] **Step 2: Run, expect PASS.**
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/alive/compose/driver/test_scientific_cli_b_boundary.py -q -p no:cacheprovider`
  Expected: `4 passed`. (`_assemble_adapters` → `assemble_baseline_backends` →
  `assemble_execution_identity_lock` → `_scientific_adapter_version` raises `AssemblerError` because
  `_COMMITTED_ADAPTER_MANIFEST is None`; the CLI maps it to exit 10 and prints one stderr line. No
  bundle/ledger/OOF/futility/seal-confirmation/audit file is written.)

- [ ] **Step 3: Confirm §4.3 structural seal-safety + the full compose/driver suites are green.**
  Run, and record the exact counts in the completion report:
  ```
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
      tests/alive/compose/test_outcome_store.py \
      tests/alive/compose/test_freeze.py \
      tests/alive/compose/test_gates.py \
      tests/alive/compose/driver -q -p no:cacheprovider
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/alive/compose -q -p no:cacheprovider
  ```
  Expected: all green, no regressions vs the pre-task baseline; the single store-construction site and
  the §4.3 guards are unchanged (this sub-project never edited them).

- [ ] **Step 4: Ruff (whole changed surface) + full-suite gate.**
  ```
  .venv/bin/python -m ruff check src/alive/compose/driver tests/alive/compose/driver
  .venv/bin/python -m ruff format --check src/alive/compose/driver tests/alive/compose/driver
  ```
  Expected: clean.

- [ ] **Step 5: Commit.**
  ```
  git add tests/alive/compose/driver/test_scientific_cli_b_boundary.py
  git commit -m "test(compose-carrier): full scientific CLI fails closed at sub-project-B adapter boundary (§6.7/§6.8)

  The end-to-end scientific CLI assembles the carrier, reaches assemble_execution_identity_lock,
  and exits 10 on the absent committed scientific adapter_version — writing no run-produced
  artifact, opening no seal, writing no audit, constructing no store, and claiming no D2. Confirms
  the §4.3 structural seal-safety tests remain unchanged and green.

  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HPoPEh5tLhsjgavBgmcmXV"
  ```

---

## Self-review — spec-coverage map (§0-§8 → task)

| Spec requirement | Task(s) |
|---|---|
| §0 In-scope 1: nested scientific schema + every non-sealed evidence byte | Task 2 (schema), Task 1 (valid corpus) |
| §0 In-scope 2: runtime repo clean **and** exact `approved_git_sha` | Task 3 (resolver), Task 8 (wired), Task 8 §5.3 negative |
| §0 In-scope 3: five carrier values + complete scientific runtime surface | Task 4 (shape), Task 8 (assembly) |
| §0 In-scope 4: bind sealed_input ↔ attestation, no source open | Task 5, Task 8 §5.2 |
| §0 In-scope 5: `EnvironmentInfo` → Phase-2a; typed `ActivationProvenanceInputs` → Phase-2b | Task 9 (env plumbing), Task 7 (provenance) |
| §0 In-scope 6: hermetic B-boundary, no store/seal/output | Task 10 |
| §0 Out-of-scope (B manifest, real workers, green D2/2b, GU roster) | Respected — no task implements them; §7 GU binding deliberately excluded |
| §0 Non-negotiable invariants (no store/seal/materialize; guards intact; git per-process; fixture bytes unchanged) | Global Constraints; enforced in every task; Task 10 asserts |
| §1 Current gaps (nested unvalidated; `run_phase2b` needs typed inputs; `phase2a_cmd` omits `environment`; `_assemble_adapters` before `run_phase2a`; fixture `synthetic_fixture`) | Task 2, Task 7, Task 9, Task 10, Task 1 |
| §2.1 Scientific block nested schema + roster == `config.activation_requirements` + `ActivationRecord` + `assert_scientific_mode_allowed` | Task 2 (schema), Task 6 (record + guard) |
| §2.2 Sealed-input attestation equality (lexical only) | Task 5 |
| §2.3 `ScientificRuntimeContext` + fail-closed resolver + `trusted_repo_root` (scientific required / fixture None) | Task 3, Task 8 |
| §3 Discriminated `RunSpecCarrier` + `__post_init__` + private constructors; scientific `sealed_outcome` sans corpus triple | Task 4 (type), Task 8 (`_load_scientific_sealed_outcome`) |
| §4 Typed provenance source-map + processed-vs-raw caveat; `phase2a_cmd` passes `environment` | Task 7, Task 9 |
| §5 Assembly order (1 load → 2 attestation → 3 runtime → 4 config/record → 5 deserialize → 6 provenance → 7 construct → 8 dispatch) | Task 8 |
| §6.1 schema + carrier assembly | Tasks 1, 8 |
| §6.2 discriminated shape | Task 4 |
| §6.3 git identity negatives (dirty tracked, untracked, submodule flag, wrong HEAD, malformed SHA, wrong root, absent-git) | Task 3, Task 8 §5.3 |
| §6.4 activation/dependency negatives (missing/extra req, wrong digest, relative/outside-root, symlink/non-regular, malformed dependency manifest, stale config-bound report) | Task 2, Task 6 |
| §6.5 sealed declaration negatives (source path/SHA/snapshot/pair-index SHA/row identity/audit dest) | Task 5 |
| §6.6 environment/provenance plumbing | Task 9, Task 7 |
| §6.7 current B boundary (full CLI, no store/seal/output, no D2 claim) | Task 10 |
| §6.8 structural seal safety unchanged + green | Task 10 |
| §6 (post-B future no-seal 2a→D2→preflight integration test) | Explicitly NOT a DoD item; noted in Task 10 as deferred until B ships |
| §7.1-2, §7.4 release blockers (B manifest, pod PREPARE, independent SHA review) | Out of scope — called out, not implemented |
| §7.3 GU `full_var_order_sha256` == response `gene_order_sha256` binding | Deliberately EXCLUDED per brief (follow-up/release-blocker, not this sub-project) |
| §8 DoD (fail-closed schemas/attestation; per-process clean+HEAD; no partial carrier; real env/provenance tested; B fail-closed zero-artifact; fixture unchanged; suites+Ruff green; no data/GPU/seal) | Tasks 2-10; Task 10 Step 3-4 gate |

**Gaps / non-mappings (intentional):** §7.3 GU gene-order binding and §7.1/§7.2/§7.4 release blockers
are out of scope by the brief and by spec §0; the post-B no-seal `2a→D2→preflight` integration test is
explicitly deferred (spec §6 "After B ships"). The `git status --ignore-submodules=none` submodule-dirty
negative is covered structurally (Task 3 asserts the flag is present in `_STATUS_ARGV`) rather than by
constructing a live dirty submodule, since a hermetic submodule fixture is disproportionate; the flag
guarantees submodule dirt is never ignored.
