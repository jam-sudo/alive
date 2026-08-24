"""Full scientific carrier assembly (spec §5) + trusted_repo_root gating."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alive.compose.config2 import ActivationRecord, load_compose_phase2_config
from alive.compose.driver.carrier_loader import (
    RunSpecCarrier,
    load_run_spec_carrier,
)
from alive.compose.driver.phase2b_cmd import _resolve_approximation_bias_report
from alive.compose.driver.run_spec import RunSpecError, load_resolved_run_spec
from alive.compose.phase2b import ActivationProvenanceInputs
from alive.provenance import EnvironmentInfo, sha256_file, sha256_json
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
    spec = load_resolved_run_spec(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        mode_expected="scientific",
    )
    config = load_compose_phase2_config(spec.pre_seal["config"].path)
    assert carrier.environment.registered_seeds == config.registered_seeds
    assert isinstance(carrier.provenance_inputs, ActivationProvenanceInputs)
    assert Path(carrier.data_card_path).is_file()
    assert Path(carrier.raw_asset_path).is_file()
    assert carrier.phase2a_inputs.factor_banks_by_k is not None
    assert set(carrier.phase2a_inputs.factor_banks_by_k) == set(carrier.phase2a_inputs.factors_by_k)
    for k_total, bank in carrier.phase2a_inputs.factor_banks_by_k.items():
        matrix = carrier.phase2a_inputs.factors_by_k[k_total]
        for gene, row in carrier.phase2a_inputs.gene_index.items():
            assert (bank.z_by_gene[gene] == matrix[row]).all()
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


def test_phase2b_resolves_the_same_preseal_validated_bias_report(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    carrier = load_run_spec_carrier(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        trusted_repo_root=bundle.repo_root,
    )
    spec = load_resolved_run_spec(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        mode_expected="scientific",
    )
    config = load_compose_phase2_config(spec.pre_seal["config"].path)

    resolved = _resolve_approximation_bias_report(
        spec, config, response_artifact=carrier.response_artifact
    )

    declared = spec.scientific["approximation_bias_report"]
    assert resolved is not None
    assert resolved.content_sha256 == declared["sha256"]
    assert resolved.report_bytes == Path(declared["path"]).read_bytes()


def test_scientific_carrier_rejects_missing_config_pinned_bias_report(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    raw = json.loads(bundle.spec_path.read_text(encoding="utf-8"))
    raw["scientific"]["approximation_bias_report"] = None
    body = {key: value for key, value in raw.items() if key != "self_checksum"}
    raw["self_checksum"] = sha256_json(body)
    bundle.spec_path.write_text(
        json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    with pytest.raises(RunSpecError, match="pins an approximation-bias SHA|carries no report"):
        load_run_spec_carrier(
            bundle.spec_path,
            approved_artifacts_root=bundle.approved_artifacts_root,
            trusted_repo_root=bundle.repo_root,
        )


def test_scientific_carrier_rejects_internally_tampered_factor_bank(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    raw_spec = json.loads(bundle.spec_path.read_text(encoding="utf-8"))
    factor_path = Path(raw_spec["factor_bank"]["path"])
    factor_payload = json.loads(factor_path.read_text(encoding="utf-8"))
    first_k = factor_payload["k_grid"][0]
    first_gene = factor_payload["factor_banks_by_k"][str(first_k)]["gene_order"][0]
    factor_payload["factor_banks_by_k"][str(first_k)]["z_by_gene"][first_gene][0] += 1.0
    factor_path.write_text(
        json.dumps(factor_payload, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    raw_spec["factor_bank"]["sha256"] = sha256_file(factor_path)
    body = {key: value for key, value in raw_spec.items() if key != "self_checksum"}
    raw_spec["self_checksum"] = sha256_json(body)
    bundle.spec_path.write_text(
        json.dumps(raw_spec, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    with pytest.raises(RunSpecError, match="factor-bank checksum does not verify"):
        load_run_spec_carrier(
            bundle.spec_path,
            approved_artifacts_root=bundle.approved_artifacts_root,
            trusted_repo_root=bundle.repo_root,
        )


def test_scientific_carrier_rejects_resigned_phase2a_inputs_field_edit(tmp_path):
    """The carrier's ``content_checksum`` re-verification must be load-bearing on its own.

    Every other layer here is a BYTE check: the run spec declares each pre-seal
    artifact's SHA-256 and seals that list with ``self_checksum``, so an ordinary
    edit is caught before any field is read. This test defeats both — it edits
    ``phase2a_inputs.json``, then recomputes the file digest AND the spec
    self-checksum, exactly as a regeneration would. What is left is the
    reconstructed bundle's own semantic identity, and the field chosen is one no
    other loader check reads, so the ``content_checksum`` comparison is the only
    thing standing between a silently altered Phase-2a input and a valid carrier.

    The committed factor-bank tamper test does not cover this: its edit is caught
    by the per-bank checksum inside the factor artifact, one layer earlier.
    """
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    raw_spec = json.loads(bundle.spec_path.read_text(encoding="utf-8"))
    inputs_path = Path(raw_spec["phase2a_inputs"]["path"])
    payload = json.loads(inputs_path.read_text(encoding="utf-8"))

    # A gene-index permutation: it re-labels which factor row belongs to which
    # gene without changing any digest the loader recomputes from other files.
    genes = sorted(payload["gene_index"], key=lambda gene: int(payload["gene_index"][gene]))
    assert len(genes) >= 2
    first, second = genes[0], genes[1]
    original = dict(payload["gene_index"])
    payload["gene_index"][first], payload["gene_index"][second] = (
        original[second],
        original[first],
    )
    # premise: the edit is real, and the DECLARED checksum is left as a forger
    # would leave it -- stale, describing the pre-edit content.
    assert payload["gene_index"] != original
    assert (
        payload["content_checksum"]
        == json.loads(inputs_path.read_text(encoding="utf-8"))["content_checksum"]
    )

    inputs_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    raw_spec["phase2a_inputs"]["sha256"] = sha256_file(inputs_path)
    body = {key: value for key, value in raw_spec.items() if key != "self_checksum"}
    raw_spec["self_checksum"] = sha256_json(body)
    bundle.spec_path.write_text(
        json.dumps(raw_spec, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    with pytest.raises(RunSpecError, match="content_checksum does not verify"):
        load_run_spec_carrier(
            bundle.spec_path,
            approved_artifacts_root=bundle.approved_artifacts_root,
            trusted_repo_root=bundle.repo_root,
        )


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
        ["git", "commit", "-q", "-m", "advance"],
        cwd=bundle.repo_root,
        check=True,
        env={**__import__("os").environ, "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    # HEAD moved; the spec's approved_git_sha is now stale → fail closed.
    with pytest.raises(ScientificRuntimeError):
        load_run_spec_carrier(
            bundle.spec_path,
            approved_artifacts_root=bundle.approved_artifacts_root,
            trusted_repo_root=bundle.repo_root,
        )


@pytest.mark.parametrize("typed", ["OutcomeLeakageError", "InputContractError"])
def test_a_typed_rejection_escapes_the_carrier_under_its_own_class(tmp_path, monkeypatch, typed):
    """The re-raise ORDERING is the loader's stated safety property; pin it.

    ``_load_phase2a_inputs`` wraps the ``Phase2aInputs`` construction so a malformed
    untrusted payload becomes a contracted ``RunSpecError``. But ``OutcomeLeakageError``
    and ``InputContractError`` are both ``ValueError`` subclasses, so without the
    earlier ``except ... : raise`` clause the widest clause would swallow them and the
    operator would be told ``RunSpecError`` -- erasing the project's highest-severity
    signal (CLAUDE.md#invariants). Deleting that clause changes no exit code and no
    stderr shape, so nothing else in the suite notices (2026-08-01 review).

    Honest about the method: ``Phase2aInputs.__post_init__`` currently raises neither
    class -- it coerces and checksums -- so the clause is defence-in-depth and a
    monkeypatched constructor is the only way to exercise the ordering. Re-review
    confirmed the earlier single-class version left the ``InputContractError`` arm
    unpinned, so both are parametrized here.
    """
    from alive.compose.driver import carrier_loader
    from alive.compose.freeze import OutcomeLeakageError
    from alive.compose.phase2a import InputContractError

    exc_type = {
        "OutcomeLeakageError": OutcomeLeakageError,
        "InputContractError": InputContractError,
    }[typed]
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")

    def _raiser(*_args, **_kwargs):
        raise exc_type("typed rejection from the constructor")

    monkeypatch.setattr(carrier_loader, "Phase2aInputs", _raiser)

    with pytest.raises(exc_type):
        load_run_spec_carrier(
            bundle.spec_path,
            approved_artifacts_root=bundle.approved_artifacts_root,
            trusted_repo_root=bundle.repo_root,
        )


# --------------------------------------------------------------------------- #
# Pre-seal reads are digest-bound: verified bytes == consumed bytes
# --------------------------------------------------------------------------- #
# `load_resolved_run_spec` hashes each pre-seal pathname during validation, and
# every consumer here used to REOPEN the same pathname afterwards. Two separate
# reads, so "the declared digest was verified" said nothing about the bytes that
# were parsed. An external audit reported it on 2026-08-24
# (`provenance.preseal-hash-reopen-toctou`) and this repository reproduced it
# independently. The window is INTRA-CALL, not sequential: a swap performed
# before the carrier runs was already refused by the spec loader, which is the
# half the audit's own write-up had wrong. Both halves are pinned below.
def _swap_config_after_the_spec_is_validated(monkeypatch, bundle, extra=b"\n# swapped\n"):
    """Make the config change in the window between hashing and reopening."""
    from alive.compose.driver import carrier_loader as cl

    real = cl.load_resolved_run_spec
    state = {"n": 0}

    def racing(*args, **kwargs):
        spec = real(*args, **kwargs)  # step 13 hashed every pre-seal path here
        state["n"] += 1
        path = Path(spec.pre_seal["config"].path)
        path.write_bytes(path.read_bytes() + extra)
        return spec

    monkeypatch.setattr(cl, "load_resolved_run_spec", racing)
    return state


def test_a_preseal_file_swapped_inside_the_load_window_is_refused(tmp_path, monkeypatch):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    state = _swap_config_after_the_spec_is_validated(monkeypatch, bundle)

    with pytest.raises(RunSpecError, match="changed after the run spec verified it"):
        load_run_spec_carrier(
            bundle.spec_path,
            approved_artifacts_root=bundle.approved_artifacts_root,
            trusted_repo_root=bundle.repo_root,
        )
    assert state["n"] == 1, "the swap must actually have happened, or this proves nothing"


def test_a_preseal_file_swapped_before_the_call_is_refused_by_the_spec_loader(tmp_path):
    """The boundary the audit's write-up got wrong: a sequential swap never
    reached the carrier at all, because the carrier takes a PATH and reloads."""
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    spec = load_resolved_run_spec(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        mode_expected="scientific",
    )
    path = Path(spec.pre_seal["config"].path)
    path.write_bytes(path.read_bytes() + b"\n# swapped\n")

    with pytest.raises(RunSpecError, match="declared sha256"):
        load_run_spec_carrier(
            bundle.spec_path,
            approved_artifacts_root=bundle.approved_artifacts_root,
            trusted_repo_root=bundle.repo_root,
        )


def test_an_untouched_carrier_still_loads(tmp_path):
    """Non-vacuity for the two refusals above: without a swap the same call
    succeeds, so they are rejecting the swap and not the fixture."""
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    carrier = load_run_spec_carrier(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        trusted_repo_root=bundle.repo_root,
    )
    assert carrier is not None
