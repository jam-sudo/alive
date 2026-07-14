"""Fail-closed loader tests for the ResolvedRunSpec v1 schema.

Every fixture spec written here is canonical JSON (``sort_keys`` + compact
separators) with a correct ``self_checksum`` and real, byte-matching on-disk
files, so the happy path loads and each tamper case fails closed. No mocks: the
real loader stream-hashes real files.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from alive.compose.datacard import compute_compose_run_id
from alive.compose.driver.run_spec import (
    EXPECTED_HASHES_KEYS,
    RESOLVED_RUN_SPEC_SCHEMA,
    RUN_PRODUCED_BASENAMES,
    ResolvedRunSpec,
    RunSpecError,
    compute_execution_id,
    load_resolved_run_spec,
)
from alive.compose.driver.seal_boundary import scientific_protocol_seal_audit_path
from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture

# ---------------------------------------------------------------------------
# Fixture-spec builder
# ---------------------------------------------------------------------------

_HEX = "ab" * 32  # a valid 64-lowercase-hex placeholder digest

_PRE_SEAL_FIELDS = (
    "config",
    "data_card",
    "raw_asset",
    "sequence_mapping",
    "feature_bank",
    "factor_bank",
    "response_artifact",
    "fit_role_artifact",
    "phase2a_inputs",
    "development_outcome_source",
    "development_outcome_manifest",
    "pair_manifest",
    "pair_index_manifest",
    "approved_sealed_input_attestation",
)


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _reseal(payload: dict[str, object]) -> None:
    """Recompute a correct ``self_checksum`` in place after mutating *payload*.

    Isolates a downstream check (path policy, digest, run_id, root) from the
    self-checksum check, so the mutated spec still self-verifies.
    """
    body = {k: v for k, v in payload.items() if k != "self_checksum"}
    payload["self_checksum"] = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def _mkfile(root: Path, name: str, content: bytes | None = None) -> dict[str, str]:
    """Create a real file under *root* and return its ``{path, sha256}`` object."""
    data = content if content is not None else f"content-of-{name}".encode()
    dest = root / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"path": str(dest), "sha256": hashlib.sha256(data).hexdigest()}


def _worker_block(root: Path, method: str) -> dict[str, object]:
    return {
        "env_python": "/usr/bin/python3",
        "worker_script": _mkfile(root, f"workers/{method}_worker.py", b"# worker\n"),
        "import_name": f"{method}_adapter",
        "worker_config": _mkfile(root, f"workers/{method}_config.json", b"{}\n"),
        "resource_manifest": _mkfile(root, f"workers/{method}_resource.json", b"{}\n"),
        "requirements_lock": _mkfile(root, f"workers/{method}_lock.txt", b"pkg==1\n"),
        # ``adapter_artifact`` is the adapter/model content — DISTINCT from the
        # launched ``worker_script`` — and is §5's sole source of adapter_sha256.
        "adapter_artifact": _mkfile(root, f"workers/{method}_adapter.bin", b"# adapter\n"),
        "execution_identity_lock": {
            "prediction_representation": "delta_mean",
            "environment_lock_sha256": _HEX,
            "adapter_version": "0.0.1",
            "adapter_sha256": _HEX,
            "config_sha256": _HEX,
            "resource_sha256": _HEX,
        },
    }


def _write_spec(
    tmp_path: Path,
    *,
    mode: str = "fixture",
    overrides: dict[str, object] | None = None,
    drop: list[str] | None = None,
) -> tuple[Path, Path]:
    """Emit a canonical-JSON fixture ResolvedRunSpec; return (spec_path, root).

    ``overrides`` replace/add top-level keys (applied before ``self_checksum`` is
    computed, unless the override key is ``self_checksum`` itself). ``drop``
    removes top-level keys.
    """
    overrides = dict(overrides or {})
    drop = list(drop or [])

    root = Path(os.path.realpath(str(tmp_path / "root")))
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / "run_dir"
    run_dir.mkdir(parents=True, exist_ok=True)

    config_digest = "c" * 64
    data_card_digest = "d" * 64
    raw_or_source_digest = "e" * 64
    sequence_mapping_digest = "f" * 64
    run_id = compute_compose_run_id(
        config_digest=config_digest,
        data_card_digest=data_card_digest,
        raw_or_source_digest=raw_or_source_digest,
        sequence_mapping_digest=sequence_mapping_digest,
    )

    payload: dict[str, object] = {
        "schema": RESOLVED_RUN_SPEC_SCHEMA,
        "mode": mode,
        "protocol": "COMPOSE-K562-v1",
        "run_id": run_id,
        "approved_git_sha": "0" * 40,
        "run_dir": str(run_dir),
        "approved_artifacts_root": str(root),
        "config_digest": config_digest,
        "data_card_digest": data_card_digest,
        "raw_or_source_digest": raw_or_source_digest,
        "sequence_mapping_digest": sequence_mapping_digest,
        "run_produced_basenames": dict(RUN_PRODUCED_BASENAMES),
        "expected_hashes": {k: _HEX for k in EXPECTED_HASHES_KEYS},
        "worker_blocks": {
            "gears": _worker_block(root, "gears"),
            "cpa": _worker_block(root, "cpa"),
        },
    }
    for field in _PRE_SEAL_FIELDS:
        payload[field] = _mkfile(root, field)

    sealed_source = _mkfile(root, "sealed/source.h5ad", b"synthetic-sealed-source")
    if mode == "fixture":
        payload["fixture"] = {
            "fixture_corpus_id": "compose-fixture-v1",
            "builder_code_digest": _HEX,
            "sealed_input": {
                "source_path": sealed_source["path"],
                "expected_file_sha256": sealed_source["sha256"],
                "audit_path": str(run_dir / "audit.jsonl"),
            },
        }
    else:
        payload["scientific"] = {
            "activation_evidence": {},
            "dependency_manifest": _mkfile(root, "dep_manifest.json", b"{}\n"),
            "approximation_bias_report": None,
            "device": "cuda",
            "precision": "float32",
            "sealed_input": {
                "source_path": sealed_source["path"],
                "expected_file_sha256": sealed_source["sha256"],
                "snapshot_id": "snap-1",
                "audit_path": str(scientific_protocol_seal_audit_path(root, "COMPOSE-K562-v1")),
            },
        }

    payload.update({k: v for k, v in overrides.items() if k != "self_checksum"})
    for key in drop:
        payload.pop(key, None)

    if "self_checksum" not in drop:
        correct = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
        payload["self_checksum"] = overrides.get("self_checksum", correct)

    spec_path = tmp_path / "resolved_run_spec.json"
    spec_path.write_text(_canonical(payload), encoding="utf-8")
    return spec_path, root


# ---------------------------------------------------------------------------
# (a) happy path
# ---------------------------------------------------------------------------


def test_happy_fixture_spec_loads(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path)
    spec = load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")
    assert isinstance(spec, ResolvedRunSpec)
    assert spec.mode == "fixture"
    assert spec.schema == RESOLVED_RUN_SPEC_SCHEMA
    assert spec.approved_artifacts_root == str(root)
    assert spec.fixture is not None
    assert spec.scientific is None
    assert set(spec.expected_hashes) == set(EXPECTED_HASHES_KEYS)
    assert set(spec.pre_seal) == set(_PRE_SEAL_FIELDS)
    assert spec.file_sha256 == hashlib.sha256(spec_path.read_bytes()).hexdigest()
    # run_id is the recomputed composite id, not derived from mode/file-sha
    assert spec.run_id == compute_compose_run_id(
        config_digest=spec.config_digest,
        data_card_digest=spec.data_card_digest,
        raw_or_source_digest=spec.raw_or_source_digest,
        sequence_mapping_digest=spec.sequence_mapping_digest,
    )


def test_wrong_schema_discriminator_rejected(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path, overrides={"schema": "attacker_schema_v0"})
    with pytest.raises(RunSpecError, match="schema must be"):
        load_resolved_run_spec(
            spec_path,
            mode_expected="fixture",
            approved_artifacts_root=root,
        )


def test_execution_id_is_deterministic_and_unstored(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path)
    spec = load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")
    eid = compute_execution_id(spec.run_id, spec.file_sha256, spec.approved_git_sha)
    assert eid == compute_execution_id(spec.run_id, spec.file_sha256, spec.approved_git_sha)
    # execution_id must NOT be embedded in the spec (avoids file-sha circular ref)
    raw = json.loads(spec_path.read_text())
    assert "execution_id" not in raw


def test_mode_expected_mismatch_raises(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path, mode="fixture")
    with pytest.raises(RunSpecError, match="mode"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="scientific")


# ---------------------------------------------------------------------------
# (b) tampered self_checksum
# ---------------------------------------------------------------------------


def test_tampered_self_checksum_raises(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path, overrides={"self_checksum": "0" * 64})
    with pytest.raises(RunSpecError, match="self_checksum"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


def test_non_canonical_bytes_raise(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path)
    payload = json.loads(spec_path.read_text())
    # Re-serialise with indentation → valid JSON but NOT canonical bytes.
    spec_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(RunSpecError, match="canonical"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


# ---------------------------------------------------------------------------
# (c) unknown / missing / extra top-level key
# ---------------------------------------------------------------------------


def test_extra_top_level_key_raises(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path, overrides={"surprise": "x"})
    with pytest.raises(RunSpecError, match="key"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


def test_missing_top_level_key_raises(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path, drop=["config"])
    with pytest.raises(RunSpecError, match="key"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


# ---------------------------------------------------------------------------
# (d) scientific block in a fixture spec (mode-block exclusivity)
# ---------------------------------------------------------------------------


def test_scientific_block_in_fixture_spec_raises(tmp_path: Path) -> None:
    spec_path, root = _write_spec(
        tmp_path,
        mode="fixture",
        overrides={
            "scientific": {
                "activation_evidence": {},
                "dependency_manifest": {"path": "/x", "sha256": _HEX},
                "approximation_bias_report": None,
                "device": "cuda",
                "precision": "float32",
                "sealed_input": {
                    "source_path": "/x",
                    "expected_file_sha256": _HEX,
                    "snapshot_id": "s",
                    "audit_path": "/x",
                },
            }
        },
    )
    with pytest.raises(RunSpecError, match="scientific"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


def test_fixture_block_in_scientific_spec_raises(tmp_path: Path) -> None:
    spec_path, root = _write_spec(
        tmp_path,
        mode="scientific",
        overrides={
            "fixture": {
                "fixture_corpus_id": "x",
                "builder_code_digest": _HEX,
                "sealed_input": {
                    "source_path": "/x",
                    "expected_file_sha256": _HEX,
                    "audit_path": "/x",
                },
            }
        },
    )
    with pytest.raises(RunSpecError, match="fixture"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="scientific")


# ---------------------------------------------------------------------------
# (d2) worker block missing adapter_artifact (spec §2.2 / §5)
# ---------------------------------------------------------------------------


def test_worker_block_missing_adapter_artifact_raises(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path)
    payload = json.loads(spec_path.read_text())
    del payload["worker_blocks"]["gears"]["adapter_artifact"]
    _reseal(payload)
    spec_path.write_text(_canonical(payload), encoding="utf-8")
    with pytest.raises(RunSpecError, match="adapter_artifact"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


@pytest.mark.parametrize("bad_path", ["", "python3", "./python3", "/usr/bin/../bin/python3"])
def test_worker_env_python_requires_absolute_normalized_path(tmp_path: Path, bad_path: str) -> None:
    spec_path, root = _write_spec(tmp_path)
    payload = json.loads(spec_path.read_text())
    payload["worker_blocks"]["gears"]["env_python"] = bad_path
    _reseal(payload)
    spec_path.write_text(_canonical(payload), encoding="utf-8")
    with pytest.raises(RunSpecError, match="absolute normalized path"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


# ---------------------------------------------------------------------------
# (e) expected_hashes missing / extra key
# ---------------------------------------------------------------------------


def test_expected_hashes_missing_key_raises(tmp_path: Path) -> None:
    bad = {k: _HEX for k in EXPECTED_HASHES_KEYS}
    bad.pop("factor_checksum")
    spec_path, root = _write_spec(tmp_path, overrides={"expected_hashes": bad})
    with pytest.raises(RunSpecError, match="expected_hashes"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


def test_expected_hashes_extra_key_raises(tmp_path: Path) -> None:
    bad = {k: _HEX for k in EXPECTED_HASHES_KEYS}
    bad["bogus_checksum"] = _HEX
    spec_path, root = _write_spec(tmp_path, overrides={"expected_hashes": bad})
    with pytest.raises(RunSpecError, match="expected_hashes"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


def test_run_produced_basenames_tampered_raises(tmp_path: Path) -> None:
    bad = dict(RUN_PRODUCED_BASENAMES)
    bad["frozen_bundle"] = "attacker_chosen.json"
    spec_path, root = _write_spec(tmp_path, overrides={"run_produced_basenames": bad})
    with pytest.raises(RunSpecError, match="run_produced_basenames"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


# ---------------------------------------------------------------------------
# (f) declared digest != on-disk file bytes
# ---------------------------------------------------------------------------


def test_declared_digest_mismatch_raises(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path)
    payload = json.loads(spec_path.read_text())
    payload["config"]["sha256"] = "0" * 64  # declared no longer matches file bytes
    _reseal(payload)
    spec_path.write_text(_canonical(payload), encoding="utf-8")
    with pytest.raises(RunSpecError, match="sha256|digest"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


# ---------------------------------------------------------------------------
# (g) recomputed run_id != declared
# ---------------------------------------------------------------------------


def test_run_id_recompute_mismatch_raises(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path, overrides={"run_id": "deadbeefdeadbeef"})
    with pytest.raises(RunSpecError, match="run_id"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


# ---------------------------------------------------------------------------
# (h) path containing ".." or a symlink under root
# ---------------------------------------------------------------------------


def test_dotdot_path_raises(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path)
    payload = json.loads(spec_path.read_text())
    payload["config"]["path"] = str(root / "sub" / ".." / "config")
    _reseal(payload)
    spec_path.write_text(_canonical(payload), encoding="utf-8")
    with pytest.raises(RunSpecError, match=r"\.\.|policy"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


def test_symlink_path_raises(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path)
    target = root / "real_target"
    target.write_bytes(b"content-of-config")
    link = root / "config_link"
    os.symlink(target, link)
    payload = json.loads(spec_path.read_text())
    payload["config"] = {
        "path": str(link),
        "sha256": hashlib.sha256(b"content-of-config").hexdigest(),
    }
    _reseal(payload)
    spec_path.write_text(_canonical(payload), encoding="utf-8")
    with pytest.raises(RunSpecError, match="symlink"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


# ---------------------------------------------------------------------------
# (i) approved_artifacts_root != realpath(cli root)
# ---------------------------------------------------------------------------


def test_root_not_realpath_raises(tmp_path: Path) -> None:
    spec_path, root = _write_spec(tmp_path)
    payload = json.loads(spec_path.read_text())
    payload["approved_artifacts_root"] = str(root / "elsewhere")
    _reseal(payload)
    spec_path.write_text(_canonical(payload), encoding="utf-8")
    with pytest.raises(RunSpecError, match="approved_artifacts_root|root"):
        load_resolved_run_spec(spec_path, approved_artifacts_root=root, mode_expected="fixture")


# ---------------------------------------------------------------------------
# (j) nested scientific-block schema: activation_evidence + dependency_manifest
# ---------------------------------------------------------------------------
#
# Uses the Task-1 synthetic scientific corpus (a real, byte-valid ResolvedRunSpec
# in mode="scientific") and mutates one nested field at a time, re-sealing with a
# correct self_checksum so only the *targeted* invariant fails.


def _load(bundle) -> ResolvedRunSpec:
    return load_resolved_run_spec(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        mode_expected="scientific",
    )


def _rewrite(bundle, mutate) -> None:
    raw = json.loads(Path(bundle.spec_path).read_bytes())
    mutate(raw)
    body = {k: v for k, v in raw.items() if k != "self_checksum"}
    raw["self_checksum"] = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    Path(bundle.spec_path).write_bytes(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def test_scientific_block_loads_clean(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    assert _load(bundle).scientific is not None  # positive baseline


def test_activation_evidence_empty_owner_rejects(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    _rewrite(bundle, lambda raw: raw["scientific"]["activation_evidence"].__setitem__("owner", ""))
    with pytest.raises(RunSpecError, match="owner"):
        _load(bundle)


def test_activation_evidence_missing_owner_key_rejects(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    _rewrite(bundle, lambda raw: raw["scientific"]["activation_evidence"].pop("owner"))
    with pytest.raises(RunSpecError, match="owner"):
        _load(bundle)


def test_activation_evidence_wrong_digest_rejects(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")

    def mutate(raw):
        reqs = raw["scientific"]["activation_evidence"]["requirements"]
        key = sorted(reqs)[0]
        reqs[key]["sha256"] = "sha256:" + "0" * 64

    _rewrite(bundle, mutate)
    with pytest.raises(RunSpecError, match="sha256|digest"):
        _load(bundle)


def test_activation_evidence_relative_path_rejects(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")

    def mutate(raw):
        reqs = raw["scientific"]["activation_evidence"]["requirements"]
        key = sorted(reqs)[0]
        reqs[key]["path"] = "relative/evidence.json"

    _rewrite(bundle, mutate)
    with pytest.raises(RunSpecError, match="absolute|escapes|path"):
        _load(bundle)


def test_activation_evidence_outside_root_path_rejects(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    outside = tmp_path / "outside_evidence.json"

    def mutate(raw):
        reqs = raw["scientific"]["activation_evidence"]["requirements"]
        key = sorted(reqs)[0]
        outside.write_bytes(Path(reqs[key]["path"]).read_bytes())  # same bytes, wrong location
        reqs[key]["path"] = str(outside)

    _rewrite(bundle, mutate)
    with pytest.raises(RunSpecError, match="escapes"):
        _load(bundle)


def test_activation_evidence_symlink_path_rejects(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    link_path = bundle.approved_artifacts_root / "evidence_symlink.json"

    def mutate(raw):
        reqs = raw["scientific"]["activation_evidence"]["requirements"]
        key = sorted(reqs)[0]
        os.symlink(reqs[key]["path"], link_path)  # same bytes via symlink, still under root
        reqs[key]["path"] = str(link_path)

    _rewrite(bundle, mutate)
    with pytest.raises(RunSpecError, match="symlink"):
        _load(bundle)


def test_activation_evidence_requirement_extra_key_rejects(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")

    def mutate(raw):
        reqs = raw["scientific"]["activation_evidence"]["requirements"]
        key = sorted(reqs)[0]
        reqs[key]["unexpected_field"] = "x"

    _rewrite(bundle, mutate)
    with pytest.raises(RunSpecError, match="keys"):
        _load(bundle)


def test_activation_evidence_bad_sha_prefix_rejects(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")

    def mutate(raw):
        reqs = raw["scientific"]["activation_evidence"]["requirements"]
        key = sorted(reqs)[0]
        reqs[key]["sha256"] = reqs[key]["sha256"].removeprefix("sha256:")  # drop the "sha256:" tag

    _rewrite(bundle, mutate)
    with pytest.raises(RunSpecError, match="sha256"):
        _load(bundle)


def test_dependency_manifest_malformed_sha_rejects(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    _rewrite(
        bundle,
        lambda raw: raw["scientific"]["dependency_manifest"].__setitem__("sha256", "nothex"),
    )
    with pytest.raises(RunSpecError, match="sha256"):
        _load(bundle)


def test_dependency_manifest_wrong_digest_rejects(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    _rewrite(
        bundle,
        lambda raw: raw["scientific"]["dependency_manifest"].__setitem__("sha256", "0" * 64),
    )
    with pytest.raises(RunSpecError, match="sha256|digest"):
        _load(bundle)


def test_dependency_manifest_relative_path_rejects(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    _rewrite(
        bundle,
        lambda raw: raw["scientific"]["dependency_manifest"].__setitem__(
            "path", "relative/dep.json"
        ),
    )
    with pytest.raises(RunSpecError, match="absolute|escapes|path"):
        _load(bundle)


def test_dependency_manifest_extra_key_rejects(tmp_path: Path) -> None:
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")

    def mutate(raw):
        raw["scientific"]["dependency_manifest"]["unexpected_field"] = "x"

    _rewrite(bundle, mutate)
    with pytest.raises(RunSpecError, match="keys"):
        _load(bundle)
