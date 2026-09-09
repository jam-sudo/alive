# tests/alive/compose/test_finalize_approximation_bias_config.py
"""Task 6 of the COMPOSE approximation-bias v1 implementation plan (design spec
``docs/superpowers/specs/2026-07-13-compose-approximation-bias-metric-design.md``):
the LOCAL one-way tool
(``scripts/compose/finalize_approximation_bias_config.py``) that binds a
completed ``compose_approximation_bias_report_v4`` report's content SHA into
the bias-NULL Phase-2 config, while MECHANICALLY proving it changed exactly
one leaf (``baselines.gears.approximation_bias_report_sha256``) and nothing
else, and that the resulting finalized config's own SHA never leaks back into
the report it is derived from (the one-way / no-cycle invariant).

2026-09-09 (PR #15 follow-up item 2): the tool no longer takes the report's word
for its own Probe-A provenance. Three Probe-A byte sources are REQUIRED keyword
arguments, their digests are compared against the report's three
``probe_a_*_sha256`` fields, and the representation the evidence ACTUALLY
validated must both admit this method and be the one the report declares.
Because the committed Probe-A owner policy validates ``log_normalized_pseudobulk``
while every admissible report must declare ``raw_pseudobulk_approximation``, the
tool admits NOTHING today -- so the tests that used to end in a finalized config
now end in a refusal. That is the honest state of the evidence, pinned by
``test_the_finalizer_cannot_succeed_under_the_current_owner_policy``; the pure
leaf write those tests used to prove is still proven, by ``_write_single_leaf``
in the ``test_phase2b.py`` round-trip.

This tool does not measure anything (that is
``scripts/compose/measure_pseudobulk_approximation_bias.py``, Tasks 1-5) and
does not run on real Norman data -- every fixture here is a small hand-built
config/report pair. It opens no seal, imports no ``gears``/``cpa``, and
constructs no outcome store.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from alive.compose import config2
from alive.compose.approximation_bias import (
    ADMITTED,
    APPROXIMATION_BIAS_SCHEMA,
    NON_FINITE,
    NOT_ADMISSIBLE,
    PROBE_A_REPRESENTATION,
    PROTOCOL,
    REPRESENTATION,
    ApproximationBiasValidationError,
    bridge_admits,
    load_probe_a_evidence,
    measurement_contract_sha256,
    probe_a_from_evidence,
    self_checksum,
)
from alive.provenance import sha256_json

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "compose" / "finalize_approximation_bias_config.py"


def _load_finalize_module():
    """Import the finalization script by path (mirrors the metric test's loader)."""
    spec = importlib.util.spec_from_file_location("_finalize_bias_config_tool", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _expected_report_sha(report_path: Path) -> str:
    """The single authoritative content-SHA recipe: SHA-256 of the EXACT on-disk
    report bytes, computed HERE via plain ``hashlib`` (not the tool's own
    ``sha256_file``) so the expectation is independent of the code under test --
    anti-tautology. The tool now pins ``sha256_file(report_path)``, and ``phase2b``
    re-verifies with the same recipe, so all three agree on the raw file bytes."""
    return hashlib.sha256(Path(report_path).read_bytes()).hexdigest()


def _probe_a_paths(tmp_path: Path, *, git_commit: str = "b" * 40) -> dict[str, Path]:
    """The three Probe-A byte sources the finalizer now REQUIRES.

    Built by the shared producer fixture (``_write_probe_a_evidence``) so these
    tests and the metric tests consume the same admission/registration/receipt
    bytes -- there is no second, more convenient Probe-A in this repository.
    """
    from tests.alive.compose import test_approximation_bias_metric as metric_tests

    evidence = metric_tests._write_probe_a_evidence(tmp_path, "pass", git_commit=git_commit)
    return {
        "probe_a_evidence_path": evidence,
        "probe_a_registration_path": evidence.with_name("probe_a_registration.json"),
        "probe_a_verification_path": evidence.with_name("verify.json"),
    }


def _probe_a_digests(probe: dict[str, Path]) -> dict[str, str]:
    """The three provenance digests a report MUST declare for these exact bytes.

    Computed here with plain ``hashlib`` rather than the tool's own
    ``sha256_file`` -- anti-tautology, as ``_expected_report_sha`` already is.
    """
    return {
        "probe_a_evidence_sha256": _expected_report_sha(probe["probe_a_evidence_path"]),
        "probe_a_registration_sha256": _expected_report_sha(probe["probe_a_registration_path"]),
        "probe_a_verification_sha256": _expected_report_sha(probe["probe_a_verification_path"]),
    }


def _refused(call, *, expected_type: type, expected_message: str) -> BaseException:
    """Run ``call``, assert HERE that it refused with this exact type and message.

    Capture-and-assert instead of ``pytest.raises``: both claims (the TYPE and
    the reason) are then made by assertions in THIS module, so a mutation that
    disables the guard under test fails with this test module's own
    ``AssertionError`` -- the only thing the mutation harness scores as a kill
    (rule 8). ``type(...) is`` is exact on purpose:
    ``ApproximationBiasValidationError`` subclasses ``ValueError``, and this
    file's negatives distinguish the finalizer's own refusal from the shared
    library's typed one.
    """
    try:
        call()
    except Exception as exc:
        assert type(exc) is expected_type, (
            f"expected exactly {expected_type.__name__}, got {type(exc).__name__}: {exc}"
        )
        assert expected_message in str(exc), (
            f"expected message containing {expected_message!r}, got {str(exc)!r}"
        )
        return exc
    raise AssertionError(
        f"expected {expected_type.__name__} containing {expected_message!r}, "
        "but the call returned without raising"
    )


#: The refusal every well-formed, correctly-pinned report earns today: the only
#: Probe-A evidence that can exist bridges ``log_normalized_pseudobulk``.
_BRIDGE_REFUSAL = (
    f"finalize_bias_config: the Probe-A bridge validated {PROBE_A_REPRESENTATION!r}, "
    f"which does not admit a {REPRESENTATION!r} report"
)


def _basis_dict() -> dict:
    """A small, bias-NULL config shaped like the real ``baselines`` block
    (``configs/compose_k562_v1_phase2.yaml``), plus a couple of unrelated sibling
    blocks so the leaf-diff proof is meaningful rather than a trivial one-key dict."""
    return {
        "protocol": "COMPOSE-K562-v1",
        "phase": 2,
        "seeds": {"registered_seeds": [11, 23, 37], "split_seed": 11},
        "baselines": {
            "additive": "delta_g + delta_h",
            "lower_bounds": ["no_change", "perturbation_mean"],
            "gears": {
                "package": "gears",
                "revision": None,
                "environment_status": "unpinned_activation_blocker",
                "prediction_representation": "raw_pseudobulk_approximation",
                "approximation_bias_report_sha256": None,
            },
            "cpa": {
                "package": "cpa-tools",
                "revision": None,
                "environment_status": "unpinned_activation_blocker",
                "prediction_representation": "cell_raw_counts",
                "approximation_bias_report_sha256": None,
            },
        },
    }


def _write_basis_yaml(tmp_path: Path, basis: dict) -> Path:
    path = tmp_path / "basis_config.yaml"
    path.write_text(yaml.safe_dump(basis, sort_keys=False), encoding="utf-8")
    return path


def _write_report_json(tmp_path: Path, report: dict, *, name: str = "report.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _bound_report(basis_sha: str) -> dict:
    """A complete, integrity-valid v2 report bound to ``basis_sha``."""
    empty_stratum = {
        "n_pairs": 0,
        "per_pair": [],
        "b_distribution": dict.fromkeys(("median", "mean", "max", "q90"), NON_FINITE),
        "signed_pc_bias": [],
    }
    body = {
        "schema": APPROXIMATION_BIAS_SCHEMA,
        "deliverable": "gears_pseudobulk_approximation_bias_report",
        "protocol": PROTOCOL,
        "seal_status": "unopened",
        "method": REPRESENTATION,
        "admission_status": "admitted",
        "strata": {"combo_calibration": empty_stratum, "singles": empty_stratum},
        "gi_and_fairness": {
            "gi_signal_per_pair": [],
            "gi_signal_median": NON_FINITE,
            "floor_median": NON_FINITE,
            "bias_to_signal_ratio_R": NON_FINITE,
            "bias_to_signal_ratio_per_pair_median": NON_FINITE,
            "R_star": 0.5,
            "fairness_flag": "indeterminate",
            "bootstrap_95_interval": {
                "floor_median": NON_FINITE,
                "gi_signal_median": NON_FINITE,
                "bias_to_signal_ratio_R": NON_FINITE,
            },
            "replicates_requested": 10,
            "replicates_finite": 0,
            "replicates_non_finite": 10,
        },
        "provenance": {
            "measurement_contract_sha256": measurement_contract_sha256(),
            "basis_config_sha256": basis_sha,
            "git_commit": "b" * 40,
            "norman_source_sha256": "1" * 64,
            "fit_role_artifact_sha256": "2" * 64,
            "response_projection_sha256": "3" * 64,
            "gene_order_sha256": "4" * 64,
            "pca_dim": 2,
            "registered_seeds": [11, 23, 37],
            "probe_a_evidence_sha256": "5" * 64,
            "probe_a_evidence_manifest_sha256": "6" * 64,
            "probe_a_registration_sha256": "7" * 64,
            "probe_a_verification_sha256": "8" * 64,
            "probe_a_output_representation": REPRESENTATION,
            "sealed_pair_overlap_count": 0,
            "pod_instance": "unit-test-local",
        },
    }
    return {**body, "self_checksum": self_checksum(body)}


# ---------------------------------------------------------------------------
# The former success path (2026-09-09). The finalizer now re-opens the Probe-A
# bytes, and the only Probe-A evidence that can exist under the committed owner
# policy bridges ``log_normalized_pseudobulk`` -- which does not admit a
# ``raw_pseudobulk_approximation`` report. So "it wrote the one leaf" became
# "it refused before any leaf could be written", and the leaf write itself is
# proven on the guardless helper the round-trip in ``test_phase2b.py`` uses.
# ---------------------------------------------------------------------------


def test_the_single_leaf_write_never_happens_under_the_current_owner_policy(tmp_path):
    """A complete, correctly-pinned report is refused, and nothing is mutated.

    Every earlier guard passes here -- basis binding, report integrity, and all
    three Probe-A digests -- so the refusal belongs to the bridge and to no
    other check.
    """
    module = _load_finalize_module()
    basis = _basis_dict()
    basis_yaml_path = _write_basis_yaml(tmp_path, basis)
    # basis_sha computed via yaml round-trip, exactly as the tool computes it,
    # so the report is genuinely bound to what `yaml.safe_load` will produce.
    basis_sha = sha256_json(yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8")))
    probe = _probe_a_paths(tmp_path)
    report = _bound_report_with(basis_sha, provenance=_probe_a_digests(probe))
    report_path = _write_report_json(tmp_path, report)

    _refused(
        lambda: module.finalize_bias_config(
            basis_config_path=basis_yaml_path, report_path=report_path, **probe
        ),
        expected_type=ValueError,
        expected_message=_BRIDGE_REFUSAL,
    )

    # No finalized config exists, and the bias-NULL basis is untouched in memory
    # and on disk (no in-place mutation on the refusal path either).
    assert basis["baselines"]["gears"]["approximation_bias_report_sha256"] is None
    on_disk = yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8"))
    assert on_disk["baselines"]["gears"]["approximation_bias_report_sha256"] is None


def test_the_pure_leaf_write_changes_exactly_the_one_leaf(tmp_path):
    """The claim the former happy path made, on the guardless helper that keeps it.

    ``_write_single_leaf`` is what ``finalize_bias_config`` calls once every
    guard has passed, and what the ``test_phase2b.py`` round-trip calls to prove
    the ONE content-SHA recipe. Every other leaf is checked independently of the
    tool's own leaf-diff guard.
    """
    module = _load_finalize_module()
    basis = _basis_dict()
    basis_yaml_path = _write_basis_yaml(tmp_path, basis)
    basis_sha = sha256_json(yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8")))
    report_path = _write_report_json(tmp_path, _bound_report(basis_sha))
    on_disk = yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8"))

    expected_report_sha = _expected_report_sha(report_path)
    final = module._write_single_leaf(on_disk, expected_report_sha)

    assert final != on_disk
    assert final["baselines"]["gears"]["approximation_bias_report_sha256"] == expected_report_sha
    assert final["baselines"]["cpa"] == basis["baselines"]["cpa"]
    assert final["baselines"]["additive"] == basis["baselines"]["additive"]
    assert final["baselines"]["lower_bounds"] == basis["baselines"]["lower_bounds"]
    assert final["seeds"] == basis["seeds"]
    assert final["protocol"] == basis["protocol"]
    assert final["baselines"]["gears"]["package"] == basis["baselines"]["gears"]["package"]
    assert final["baselines"]["gears"]["revision"] == basis["baselines"]["gears"]["revision"]
    # The input is untouched (no in-place mutation).
    assert on_disk["baselines"]["gears"]["approximation_bias_report_sha256"] is None


def test_finalization_rejects_tampered_report_self_checksum(tmp_path):
    module = _load_finalize_module()
    basis = _basis_dict()
    basis_path = _write_basis_yaml(tmp_path, basis)
    basis_sha = sha256_json(yaml.safe_load(basis_path.read_text(encoding="utf-8")))
    report = _bound_report(basis_sha)
    report["gi_and_fairness"]["fairness_flag"] = "representation_confounded"
    report_path = _write_report_json(tmp_path, report)

    with pytest.raises(ValueError, match="fairness_flag|self_checksum|integrity"):
        module.finalize_bias_config(
            basis_config_path=basis_path, report_path=report_path, **_probe_a_paths(tmp_path)
        )


# ---------------------------------------------------------------------------
# test_finalization_fails_closed_on_extra_diff
# ---------------------------------------------------------------------------


def test_finalization_fails_closed_on_extra_diff():
    """Construct a GENUINE second leaf change (not a monkeypatch of the guard
    itself) and assert the production leaf-diff guard raises. This exercises the
    real ``_assert_single_leaf_diff`` helper the tool calls internally, fed a
    ``final`` that a hypothetical buggy implementation might have produced."""
    module = _load_finalize_module()
    basis = _basis_dict()
    final = copy.deepcopy(basis)
    final["baselines"]["gears"]["approximation_bias_report_sha256"] = "a" * 64
    # A second, genuinely different leaf -- a buggy implementation might also
    # touch `revision` (or anything else) while it was in there.
    final["baselines"]["gears"]["revision"] = "v1.2.3"

    # Anti-tautology: the second leaf really does differ before we even touch
    # the guard under test.
    assert final["baselines"]["gears"]["revision"] != basis["baselines"]["gears"]["revision"]

    with pytest.raises(ValueError, match="expected exactly one leaf diff"):
        module._assert_single_leaf_diff(basis, final)


# ---------------------------------------------------------------------------
# test_basis_binding_mismatch_fails
# ---------------------------------------------------------------------------


def test_basis_binding_mismatch_fails(tmp_path):
    module = _load_finalize_module()
    basis = _basis_dict()
    basis_yaml_path = _write_basis_yaml(tmp_path, basis)
    real_basis_sha = sha256_json(yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8")))

    wrong_sha = "0" * 64
    assert wrong_sha != real_basis_sha
    report = _bound_report(wrong_sha)
    report_path = _write_report_json(tmp_path, report)

    with pytest.raises(ValueError, match="basis_config_sha256"):
        module.finalize_bias_config(
            basis_config_path=basis_yaml_path,
            report_path=report_path,
            **_probe_a_paths(tmp_path),
        )


def test_basis_not_bias_null_fails(tmp_path):
    """Companion negative case for guard (ii): a basis whose bias field is
    ALREADY non-null must be rejected even if the report's binding is correct,
    since finalizing again would silently discard the already-recorded SHA."""
    module = _load_finalize_module()
    basis = _basis_dict()
    basis["baselines"]["gears"]["approximation_bias_report_sha256"] = "e" * 64
    basis_yaml_path = _write_basis_yaml(tmp_path, basis)
    basis_sha = sha256_json(yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8")))
    report = _bound_report(basis_sha)
    report_path = _write_report_json(tmp_path, report)

    with pytest.raises(ValueError, match="bias-NULL"):
        module.finalize_bias_config(
            basis_config_path=basis_yaml_path,
            report_path=report_path,
            **_probe_a_paths(tmp_path),
        )


# ---------------------------------------------------------------------------
# test_final_sha_absent_from_report
# ---------------------------------------------------------------------------


def test_no_final_config_can_leak_into_the_report_because_none_is_produced(tmp_path):
    """The one-way invariant, still measured with a REAL computed final-config SHA.

    The guarded path refuses (the bridge does not admit this method), so the SHA
    is computed from the guardless leaf write the tool would have used -- still
    the real value the real recipe produces, never a fabricated placeholder.
    """
    module = _load_finalize_module()
    basis = _basis_dict()
    basis_yaml_path = _write_basis_yaml(tmp_path, basis)
    basis_sha = sha256_json(yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8")))
    probe = _probe_a_paths(tmp_path)
    report = _bound_report_with(basis_sha, provenance=_probe_a_digests(probe))
    report_path = _write_report_json(tmp_path, report)

    _refused(
        lambda: module.finalize_bias_config(
            basis_config_path=basis_yaml_path, report_path=report_path, **probe
        ),
        expected_type=ValueError,
        expected_message=_BRIDGE_REFUSAL,
    )

    on_disk = yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8"))
    final = module._write_single_leaf(on_disk, _expected_report_sha(report_path))
    final_sha = sha256_json(final)
    assert final_sha not in json.dumps(report)


def test_final_sha_leak_into_report_fails():
    """Genuine failure path for guard (v), exercised directly against the
    production ``_assert_no_final_sha_leak`` helper (the same one
    ``finalize_bias_config`` calls internally) -- not monkeypatched.

    Note: constructing an end-to-end ``finalize_bias_config`` call whose
    REPORT INPUT already contains its own eventual output SHA is a genuine
    fixed-point/self-reference problem (the final SHA depends on the report's
    bytes, so planting it changes those bytes, which changes the SHA again);
    it is not a feasible test fixture. Testing the guard directly with a
    ``final`` dict and a ``report`` dict that genuinely, literally embeds
    ``sha256_json(final)`` as a substring is the real, checkable shape of the
    invariant this guard enforces.
    """
    module = _load_finalize_module()
    final = {"baselines": {"gears": {"approximation_bias_report_sha256": "b" * 64}}}
    final_sha = sha256_json(final)

    # The leaked value is genuinely, literally present in the report's JSON --
    # not a fabricated string coincidentally matching test expectations.
    report = {
        "provenance": {"basis_config_sha256": "a" * 64},
        "note": f"unrelated evidence mentions {final_sha} verbatim",
    }
    assert final_sha in json.dumps(report)

    with pytest.raises(ValueError, match="one-way"):
        module._assert_no_final_sha_leak(final, report)

    # Sanity: a report that genuinely does NOT contain the SHA passes cleanly.
    clean_report = {"provenance": {"basis_config_sha256": "a" * 64}, "note": "no leak here"}
    assert final_sha not in json.dumps(clean_report)
    module._assert_no_final_sha_leak(final, clean_report)  # must not raise


# ---------------------------------------------------------------------------
# test_bias_requirement_not_config_bound
# ---------------------------------------------------------------------------


def test_bias_requirement_not_config_bound():
    """Guards the no-cycle invariant at its source: adding the approximation-bias
    requirement to ``config2._CONFIG_BOUND_EVIDENCE_REQUIREMENTS`` would make a
    FUTURE finalized config's SHA get embedded (via that requirement's
    config-bound evidence check) back into evidence that itself feeds the report
    -- the forbidden cycle this whole tool exists to avoid. ``config2.py`` is
    read-only for this task; this test only asserts the existing frozenset."""
    assert "approximation_bias_report_sha256" not in config2._CONFIG_BOUND_EVIDENCE_REQUIREMENTS
    assert not any(
        "bias" in requirement.lower() for requirement in config2._CONFIG_BOUND_EVIDENCE_REQUIREMENTS
    )
    # Sanity: the frozenset is real and non-empty (not vacuously satisfied).
    assert len(config2._CONFIG_BOUND_EVIDENCE_REQUIREMENTS) > 0


# ---------------------------------------------------------------------------
# The thin CLI. It refuses for the same reason the API does, and -- because a
# guard that can be omitted is not a guard -- it will not even parse without the
# three Probe-A paths.
# ---------------------------------------------------------------------------


def test_main_cli_writes_no_file_when_the_bridge_does_not_admit(tmp_path):
    module = _load_finalize_module()
    basis_yaml_path = _write_basis_yaml(tmp_path, _basis_dict())
    basis_sha = sha256_json(yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8")))
    probe = _probe_a_paths(tmp_path)
    report_path = _write_report_json(
        tmp_path, _bound_report_with(basis_sha, provenance=_probe_a_digests(probe))
    )
    out_path = tmp_path / "finalized_config.yaml"

    _refused(
        lambda: module.main(
            [
                "--basis-config",
                str(basis_yaml_path),
                "--report",
                str(report_path),
                "--probe-a-evidence",
                str(probe["probe_a_evidence_path"]),
                "--probe-a-registration",
                str(probe["probe_a_registration_path"]),
                "--probe-a-verification",
                str(probe["probe_a_verification_path"]),
                "--out",
                str(out_path),
            ]
        ),
        expected_type=ValueError,
        expected_message=_BRIDGE_REFUSAL,
    )

    assert not out_path.exists()


def test_the_cli_refuses_to_run_without_the_three_probe_a_paths(tmp_path):
    """``required=True``, measured: the same argv that used to work now cannot parse.

    This is the arm that makes the evidence binding unbypassable. There is
    deliberately no companion "no-arguments still works" case -- that test would
    pin the bypass open.
    """
    module = _load_finalize_module()
    basis_yaml_path = _write_basis_yaml(tmp_path, _basis_dict())
    basis_sha = sha256_json(yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8")))
    report_path = _write_report_json(tmp_path, _bound_report(basis_sha))
    out_path = tmp_path / "finalized_config.yaml"

    with pytest.raises(SystemExit) as excinfo:
        module.main(
            [
                "--basis-config",
                str(basis_yaml_path),
                "--report",
                str(report_path),
                "--out",
                str(out_path),
            ]
        )

    assert excinfo.value.code == 2
    assert not out_path.exists()


# ---------------------------------------------------------------------------
# R1 (2026-09-07 audit debate): admission is what this tool converts into a config
# leaf, so the two ways a report can fail the Probe-A bridge contract must both die
# HERE as well as inside the producer -- redundant enforcement, one shared function.
# ---------------------------------------------------------------------------


def _bound_report_with(basis_sha: str, **overrides) -> dict:
    """``_bound_report`` with top-level/provenance overrides and a REBUILT self_checksum."""
    report = _bound_report(basis_sha)
    provenance_overrides = overrides.pop("provenance", {})
    report.update(overrides)
    report["provenance"].update(provenance_overrides)
    return {
        **{key: value for key, value in report.items() if key != "self_checksum"},
        "self_checksum": self_checksum(
            {key: value for key, value in report.items() if key != "self_checksum"}
        ),
    }


def _round_tripped_basis(tmp_path: Path) -> tuple[Path, str]:
    """Write the basis config and return it with the SHA the tool will recompute."""
    basis_path = _write_basis_yaml(tmp_path, _basis_dict())
    basis_sha = sha256_json(yaml.safe_load(basis_path.read_text(encoding="utf-8")))
    return basis_path, basis_sha


def test_a_report_whose_bridge_representation_differs_is_refused_by_the_finalizer(tmp_path):
    """The finalizer revalidates: an ADMITTED report whose Probe-A bridge validated another
    representation cannot reach ``baselines.gears.approximation_bias_report_sha256``."""
    basis_path, basis_sha = _round_tripped_basis(tmp_path)
    report = _bound_report_with(
        basis_sha,
        admission_status=ADMITTED,
        provenance={"probe_a_output_representation": PROBE_A_REPRESENTATION},
    )
    report_path = _write_report_json(tmp_path, report)

    with pytest.raises(ApproximationBiasValidationError, match="representation mismatch"):
        _load_finalize_module().finalize_bias_config(
            basis_config_path=basis_path, report_path=report_path, **_probe_a_paths(tmp_path)
        )


def test_a_not_admissible_report_never_reaches_the_config_leaf(tmp_path):
    """The honest refusal record the producer writes today must not be finalizable either."""
    basis_path, basis_sha = _round_tripped_basis(tmp_path)
    report = _bound_report_with(
        basis_sha,
        admission_status=NOT_ADMISSIBLE,
        provenance={"probe_a_output_representation": PROBE_A_REPRESENTATION},
    )
    report_path = _write_report_json(tmp_path, report)

    with pytest.raises(ApproximationBiasValidationError, match="must be 'admitted'"):
        _load_finalize_module().finalize_bias_config(
            basis_config_path=basis_path, report_path=report_path, **_probe_a_paths(tmp_path)
        )


def test_a_log_probe_chain_cannot_clear_the_collective_bias_blocker(tmp_path):
    """End to end, through the REAL producer CLI and the REAL committed config.

    A log-normalized Probe-A PASS still measures and still writes a report, but that report
    is ``NOT_ADMISSIBLE``, so the finalizer has nothing to admit and the committed config
    keeps its collective approximation-bias activation blocker (6 blockers, not 5).
    """
    from alive.compose.config2 import load_compose_phase2_config_from_text
    from tests.alive.compose import test_approximation_bias_metric as metric_tests

    basis_text = (_REPO / "configs" / "compose_k562_v1_phase2.yaml").read_text(encoding="utf-8")
    fixture = metric_tests._write_main_cli_fixture(tmp_path)
    Path(fixture["basis_config"]).write_text(basis_text, encoding="utf-8")
    evidence = metric_tests._write_probe_a_evidence(
        tmp_path, "pass", git_commit=fixture["git_commit"]
    )
    out = tmp_path / "report.json"

    exit_code = metric_tests._load_metric_module().main(
        metric_tests._main_cli_argv(fixture, evidence, out)
    )

    assert exit_code == 0
    assert out.exists()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["admission_status"] == NOT_ADMISSIBLE
    assert written["provenance"]["probe_a_output_representation"] == PROBE_A_REPRESENTATION

    with pytest.raises(ApproximationBiasValidationError, match="must be 'admitted'"):
        _load_finalize_module().finalize_bias_config(
            basis_config_path=fixture["basis_config"],
            report_path=out,
            probe_a_evidence_path=evidence,
            probe_a_registration_path=evidence.with_name("probe_a_registration.json"),
            probe_a_verification_path=evidence.with_name("verify.json"),
        )
    assert (
        "baselines.approximation_bias_report_sha256"
        in load_compose_phase2_config_from_text(basis_text).activation_blockers
    )


# ---------------------------------------------------------------------------
# 2026-09-09, PR #15 follow-up item 2: the finalizer used to take the report's
# word for its own Probe-A provenance. It now re-opens the three byte sources
# and refuses on five distinct grounds. Each arm below is a capture-and-assert
# negative: the TYPE and the REASON are asserted in this module, so a mutation
# that disables one guard fails with this module's own AssertionError.
# ---------------------------------------------------------------------------


def test_a_report_whose_probe_a_admission_digest_differs_from_the_bytes_is_refused(tmp_path):
    """(a) The admission digest. Cross-wired to the registration's REAL digest --
    a hex64 value the report could plausibly carry -- not a conspicuous sentinel
    (mutation rule 2). Nothing else validates this field, so this guard is the
    only thing standing between a report and a set of admission bytes it never
    described."""
    module = _load_finalize_module()
    basis_path, basis_sha = _round_tripped_basis(tmp_path)
    probe = _probe_a_paths(tmp_path)
    digests = _probe_a_digests(probe)
    wrong = digests["probe_a_registration_sha256"]
    assert wrong != digests["probe_a_evidence_sha256"]
    report_path = _write_report_json(
        tmp_path,
        _bound_report_with(basis_sha, provenance={**digests, "probe_a_evidence_sha256": wrong}),
    )

    _refused(
        lambda: module.finalize_bias_config(
            basis_config_path=basis_path, report_path=report_path, **probe
        ),
        expected_type=ValueError,
        expected_message=(
            "finalize_bias_config: Probe-A admission bytes do not match the report's "
            "probe_a_evidence_sha256"
        ),
    )


def test_a_report_whose_probe_a_registration_digest_differs_from_the_bytes_is_refused(tmp_path):
    """(b) The registration digest, cross-wired to the verification's REAL digest.

    Redundantly enforced downstream (``load_probe_a_evidence`` is handed the same
    field as its external pin), so the assertion here is exact on TYPE: if this
    guard is removed, the call dies on the library's typed error instead and this
    module's own assertion is what reports it."""
    module = _load_finalize_module()
    basis_path, basis_sha = _round_tripped_basis(tmp_path)
    probe = _probe_a_paths(tmp_path)
    digests = _probe_a_digests(probe)
    wrong = digests["probe_a_verification_sha256"]
    assert wrong != digests["probe_a_registration_sha256"]
    report_path = _write_report_json(
        tmp_path,
        _bound_report_with(basis_sha, provenance={**digests, "probe_a_registration_sha256": wrong}),
    )

    _refused(
        lambda: module.finalize_bias_config(
            basis_config_path=basis_path, report_path=report_path, **probe
        ),
        expected_type=ValueError,
        expected_message=(
            "finalize_bias_config: Probe-A registration bytes do not match the report's "
            "probe_a_registration_sha256"
        ),
    )


def test_a_report_whose_probe_a_verification_digest_differs_from_the_bytes_is_refused(tmp_path):
    """(c) The verification-receipt digest, cross-wired to the registration's REAL
    digest. Same redundancy note as (b)."""
    module = _load_finalize_module()
    basis_path, basis_sha = _round_tripped_basis(tmp_path)
    probe = _probe_a_paths(tmp_path)
    digests = _probe_a_digests(probe)
    wrong = digests["probe_a_registration_sha256"]
    assert wrong != digests["probe_a_verification_sha256"]
    report_path = _write_report_json(
        tmp_path,
        _bound_report_with(basis_sha, provenance={**digests, "probe_a_verification_sha256": wrong}),
    )

    _refused(
        lambda: module.finalize_bias_config(
            basis_config_path=basis_path, report_path=report_path, **probe
        ),
        expected_type=ValueError,
        expected_message=(
            "finalize_bias_config: Probe-A verification bytes do not match the report's "
            "probe_a_verification_sha256"
        ),
    )


def test_the_finalizer_refuses_when_the_probe_a_bridge_does_not_admit_this_method(tmp_path):
    """(e) The R1 relation, on real bytes: the evidence bridges
    ``log_normalized_pseudobulk`` and this report measures
    ``raw_pseudobulk_approximation``. Every earlier guard passes, so this is the
    refusal a correctly-assembled report earns today."""
    module = _load_finalize_module()
    basis_path, basis_sha = _round_tripped_basis(tmp_path)
    probe = _probe_a_paths(tmp_path)
    report_path = _write_report_json(
        tmp_path, _bound_report_with(basis_sha, provenance=_probe_a_digests(probe))
    )

    _refused(
        lambda: module.finalize_bias_config(
            basis_config_path=basis_path, report_path=report_path, **probe
        ),
        expected_type=ValueError,
        expected_message=_BRIDGE_REFUSAL,
    )


def test_the_finalizer_refuses_a_representation_the_probe_a_evidence_did_not_validate(
    tmp_path, monkeypatch
):
    """(d) Defense in depth: even if the R1 relation admitted this method, the
    representation the report DECLARES must still be the one the evidence
    actually validated.

    ``bridge_admits`` refuses first today, so this comparison is unreachable
    while that holds. Patching the relation permissive ON THE FINALIZER'S OWN
    MODULE is the same "make the redundant site fall so the named site can be
    measured" move the mutation harness makes (rule 7); nothing else is patched
    -- the report, the three byte sources and every validator are the real ones.
    """
    module = _load_finalize_module()
    basis_path, basis_sha = _round_tripped_basis(tmp_path)
    probe = _probe_a_paths(tmp_path)
    report_path = _write_report_json(
        tmp_path, _bound_report_with(basis_sha, provenance=_probe_a_digests(probe))
    )

    # Measure the premise in both directions rather than assuming it.
    assert (
        module.bridge_admits(method=REPRESENTATION, probe_representation=PROBE_A_REPRESENTATION)
        is False
    )
    monkeypatch.setattr(module, "bridge_admits", lambda **_kwargs: True)
    assert (
        module.bridge_admits(method=REPRESENTATION, probe_representation=PROBE_A_REPRESENTATION)
        is True
    )

    _refused(
        lambda: module.finalize_bias_config(
            basis_config_path=basis_path, report_path=report_path, **probe
        ),
        expected_type=ValueError,
        expected_message=(
            "finalize_bias_config: the report's probe_a_output_representation "
            f"({REPRESENTATION!r}) is not what the Probe-A evidence actually validated "
            f"({PROBE_A_REPRESENTATION!r})"
        ),
    )


def test_the_finalizer_cannot_succeed_under_the_current_owner_policy(tmp_path):
    """Not deleted coverage -- the honest record: with the log-normalized Probe-A
    owner policy no raw report can be admitted; the success path is POD-GATED
    behind the R1 representation decision (readiness ``:118``).

    Both halves of the impossibility are MEASURED here rather than quoted:
    (1) the only Probe-A evidence that validates bridges
    ``log_normalized_pseudobulk``, which does not admit this method; and
    (2) a report that instead declares that very representation is refused by the
    shared library, before the finalizer's own guards are reached. No report can
    satisfy both, so there is no input on which this tool returns a config.
    """
    probe = _probe_a_paths(tmp_path)
    registration_sha = _expected_report_sha(probe["probe_a_registration_path"])
    verification_sha = _expected_report_sha(probe["probe_a_verification_path"])
    evidence = load_probe_a_evidence(
        probe["probe_a_evidence_path"],
        registration_path=probe["probe_a_registration_path"],
        verification_path=probe["probe_a_verification_path"],
        expected_git_commit="b" * 40,
        expected_registration_sha256=registration_sha,
        expected_verification_sha256=verification_sha,
    )
    payload = probe_a_from_evidence(
        evidence,
        expected_git_commit="b" * 40,
        expected_registration_sha256=registration_sha,
        expected_verification_sha256=verification_sha,
    )

    # (1) What the one admissible Probe-A actually validated.
    bridged = payload["output_bridge"]["representation"]
    assert bridged == PROBE_A_REPRESENTATION
    assert bridged != REPRESENTATION
    assert bridge_admits(method=REPRESENTATION, probe_representation=bridged) is False

    # (2) The only report that would MATCH those bytes is refused upstream.
    basis_path, basis_sha = _round_tripped_basis(tmp_path)
    report_path = _write_report_json(
        tmp_path,
        _bound_report_with(
            basis_sha,
            admission_status=ADMITTED,
            provenance={**_probe_a_digests(probe), "probe_a_output_representation": bridged},
        ),
    )

    _refused(
        lambda: _load_finalize_module().finalize_bias_config(
            basis_config_path=basis_path, report_path=report_path, **probe
        ),
        expected_type=ApproximationBiasValidationError,
        expected_message="representation mismatch",
    )
