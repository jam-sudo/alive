"""ActivationRecord assembly + scientific-mode re-validation (spec §2.1 / §5 step 4)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from alive.compose.config2 import (
    ActivationRecord,
    ScientificModeError,
    assert_scientific_mode_allowed,
    load_compose_phase2_config,
)
from alive.compose.driver.carrier_loader import _assemble_activation_record
from alive.compose.driver.run_spec import RunSpecError, load_resolved_run_spec
from tests.alive.compose.driver.scientific_carrier_support import (
    _CANON_CONFIG,
    build_scientific_carrier_fixture,
)


def _spec_config(bundle):
    spec = load_resolved_run_spec(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        mode_expected="scientific",
    )
    config = load_compose_phase2_config(spec.pre_seal["config"].path)
    return spec, config


def _with_evidence(spec, **overrides):
    """Return a ``spec`` with ``scientific.activation_evidence`` shallow-overridden.

    ``spec`` is a frozen dataclass and ``scientific`` is an immutable
    ``MappingProxyType`` loaded straight from disk (Task 2 already validated it),
    so this builds a genuine (non-mock) ``ResolvedRunSpec`` variant carrying an
    in-memory-only mutated evidence block — the minimal way to reach
    ``_assemble_activation_record``'s own config-aware roster check without
    fighting the spec file's self-checksum.
    """
    evidence = {**spec.scientific["activation_evidence"], **overrides}
    scientific = {**spec.scientific, "activation_evidence": evidence}
    return dataclasses.replace(spec, scientific=scientific)


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
    report_req = "real_norman_phi_rank_and_condition_report"
    report_path = Path(reqs[report_req]["path"])
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["config_sha256"] = "deadbeef" * 8
    mutated_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    report_path.write_bytes(mutated_bytes)

    # assert_scientific_mode_allowed ALSO re-verifies each evidence file's bytes against the
    # record's own evidence_hashes (independent of run_spec's Task-2 check, which already ran
    # and passed when `spec` was loaded above, before this mutation). If the record still carried
    # the pre-mutation digest, that byte-hash self-check would fire first and mask the
    # config-bound lineage guard this test targets — so the digest is recomputed here to keep
    # the record internally consistent and let the intended config_sha256-mismatch check fire.
    evidence_hashes = {r: reqs[r]["sha256"] for r in config.activation_requirements}
    evidence_hashes[report_req] = "sha256:" + hashlib.sha256(mutated_bytes).hexdigest()
    record = ActivationRecord(
        owner="owner@example.org",
        approved_protocol=config.protocol,
        approved_phase=config.phase,
        approved_git_sha=spec.approved_git_sha,
        approved_sequence_mapping_sha256=spec.sequence_mapping_digest,
        evidence_hashes=evidence_hashes,
        evidence_files={r: reqs[r]["path"] for r in config.activation_requirements},
    )
    with pytest.raises(ScientificModeError, match="config_sha256 mismatch"):
        assert_scientific_mode_allowed(config, activation_record=record, git_is_clean=True)


def test_missing_requirement_rejects(tmp_path):
    # A roster missing one requirement config.activation_requirements declares. Task 2's
    # per-entry checks (run_spec) never see this — it is config-unaware — so this must be
    # caught by _assemble_activation_record's own roster == config.activation_requirements
    # exactness check, ahead of any call into assert_scientific_mode_allowed.
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, config = _spec_config(bundle)
    dropped = sorted(config.activation_requirements)[0]
    requirements = dict(spec.scientific["activation_evidence"]["requirements"])
    del requirements[dropped]
    mutated_spec = _with_evidence(spec, requirements=requirements)
    with pytest.raises(RunSpecError, match=rf"missing=\['{dropped}'\]"):
        _assemble_activation_record(mutated_spec, config, git_is_clean=True)


def test_extra_requirement_rejects(tmp_path):
    # A roster with one requirement config.activation_requirements does NOT declare. Same
    # config-aware exactness check as the missing-requirement case, the other direction.
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, config = _spec_config(bundle)
    requirements = dict(spec.scientific["activation_evidence"]["requirements"])
    any_entry = next(iter(requirements.values()))
    requirements["unexpected_extra_requirement"] = dict(any_entry)
    mutated_spec = _with_evidence(spec, requirements=requirements)
    with pytest.raises(RunSpecError, match=r"extra=\['unexpected_extra_requirement'\]"):
        _assemble_activation_record(mutated_spec, config, git_is_clean=True)


def test_wrong_digest_rejects(tmp_path):
    # Roster + config agree at assembly time (Step-1 check passes), but the evidence FILE's
    # bytes are tampered after spec-load — Task 2's byte-SHA check already ran (and passed)
    # when `spec` was loaded above, so this specifically proves
    # assert_scientific_mode_allowed's OWN independent evidence-bytes re-verification (not a
    # mere restatement of Task 2) also fails closed against a since-tampered file.
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, config = _spec_config(bundle)
    reqs = spec.scientific["activation_evidence"]["requirements"]
    store_req = "independent_compose_outcome_store_and_access_audit"
    store_path = Path(reqs[store_req]["path"])
    store_path.write_bytes(store_path.read_bytes() + b"\n# tampered after spec load\n")
    with pytest.raises(ScientificModeError, match=rf"file hash mismatch for \['{store_req}'\]"):
        _assemble_activation_record(spec, config, git_is_clean=True)


def test_wrong_owner_rejects(tmp_path):
    # The guard's only owner rule is non-empty-after-strip; a blank owner is the "wrong owner"
    # this layer can reject (activation_evidence.owner is sourced verbatim, spec §2.1).
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, config = _spec_config(bundle)
    mutated_spec = _with_evidence(spec, owner="   ")
    with pytest.raises(ScientificModeError, match="owner is empty"):
        _assemble_activation_record(mutated_spec, config, git_is_clean=True)


def test_blocker_present_rejects(tmp_path):
    # A config with exactly ONE unresolved activation blocker: `regimes.power_status` is left
    # at its canonical `..._activation_blocker` value (config2.py:472-484 documents the
    # blocker rule; ..._write_activated_config's mirror in scientific_carrier_support.py always
    # resolves it, which is why no existing test here reaches config2.py:1323-1327's
    # `if config.activation_blockers:` guard). Every other baseline field is resolved exactly
    # like the fully-activated corpus config, so this is otherwise as valid as
    # `_spec_config(bundle)`'s config.
    #
    # Non-tautology: this reuses `spec` from a fully-valid `bundle` unmodified — owner,
    # requirement roster, evidence-hash syntax, and on-disk evidence-file bytes are all exactly
    # as valid as `test_activation_record_assembles_and_validates`. `_assemble_activation_record`
    # passes this SAME blocked config object to both `ActivationRecord` construction (so
    # approved_protocol/approved_phase trivially match `config.protocol`/`config.phase`) and to
    # `assert_scientific_mode_allowed`, which checks status/owner/protocol/phase/roster/
    # digest-syntax/evidence-bytes (config2.py:1236-1321) strictly BEFORE the blocker check
    # (config2.py:1323-1327) and only reaches the config-bound report config_sha256 lineage
    # check (config2.py:~1350-1357) AFTER it — so this blocked config's different
    # `config_sha256` (from the mutated YAML) is never compared to anything, and the blocker
    # check is guaranteed to be the first (and only) guard that can fire.
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec, _config = _spec_config(bundle)

    raw = yaml.safe_load(Path(_CANON_CONFIG).read_text(encoding="utf-8"))
    raw["status"] = "active"
    # raw["regimes"]["power_status"] intentionally left unresolved (canonical
    # "unestablished_activation_blocker") — the single blocker under test.
    raw["baselines"]["gears"]["revision"] = "cell-gears==0.1.2"
    raw["baselines"]["gears"]["environment_status"] = "pinned_and_fresh_sync_verified"
    raw["baselines"]["gears"]["approximation_bias_report_sha256"] = "a" * 64
    raw["baselines"]["cpa"]["revision"] = "cpa-tools==0.8.5"
    raw["baselines"]["cpa"]["environment_status"] = "pinned_and_fresh_sync_verified"
    blocked_config_path = tmp_path / "blocked_config.yaml"
    blocked_config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    blocked_config = load_compose_phase2_config(blocked_config_path)
    assert blocked_config.activation_blockers == ("regimes.power_status",)

    with pytest.raises(ScientificModeError, match="unresolved activation blockers"):
        _assemble_activation_record(spec, blocked_config, git_is_clean=True)
