# tests/alive/compose/test_finalize_approximation_bias_config.py
"""Task 6 of the COMPOSE approximation-bias v1 implementation plan (design spec
``docs/superpowers/specs/2026-07-13-compose-approximation-bias-metric-design.md``):
the LOCAL one-way tool
(``scripts/compose/finalize_approximation_bias_config.py``) that binds a
completed ``compose_approximation_bias_report_v1`` report's content SHA into
the bias-NULL Phase-2 config, while MECHANICALLY proving it changed exactly
one leaf (``baselines.gears.approximation_bias_report_sha256``) and nothing
else, and that the resulting finalized config's own SHA never leaks back into
the report it is derived from (the one-way / no-cycle invariant).

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
    """A minimal, well-formed report bound to ``basis_sha`` via its
    ``provenance.basis_config_sha256`` -- the ONLY field the tool inspects on the
    report side of the binding check."""
    return {
        "schema": "compose_approximation_bias_report_v1",
        "gi_and_fairness": {"bias_to_signal_ratio_R": 0.12, "fairness_flag": "clear"},
        "provenance": {
            "basis_config_sha256": basis_sha,
            "git_commit": "b" * 40,
            "pod_instance": "unit-test-local",
        },
        "self_checksum": "d" * 64,
    }


# ---------------------------------------------------------------------------
# test_finalization_changes_only_the_one_leaf
# ---------------------------------------------------------------------------


def test_finalization_changes_only_the_one_leaf(tmp_path):
    module = _load_finalize_module()
    basis = _basis_dict()
    basis_yaml_path = _write_basis_yaml(tmp_path, basis)
    # basis_sha computed via yaml round-trip, exactly as the tool computes it,
    # so the report is genuinely bound to what `yaml.safe_load` will produce.
    basis_sha = sha256_json(yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8")))
    report = _bound_report(basis_sha)
    report_path = _write_report_json(tmp_path, report)

    final = module.finalize_bias_config(basis_config_path=basis_yaml_path, report_path=report_path)

    assert final != basis
    expected_report_sha = _expected_report_sha(report_path)
    assert final["baselines"]["gears"]["approximation_bias_report_sha256"] == expected_report_sha
    # Every other leaf is untouched, verified independently of the tool's own
    # leaf-diff guard (which this test does not call at all).
    assert final["baselines"]["cpa"] == basis["baselines"]["cpa"]
    assert final["baselines"]["additive"] == basis["baselines"]["additive"]
    assert final["baselines"]["lower_bounds"] == basis["baselines"]["lower_bounds"]
    assert final["seeds"] == basis["seeds"]
    assert final["protocol"] == basis["protocol"]
    assert final["baselines"]["gears"]["package"] == basis["baselines"]["gears"]["package"]
    assert final["baselines"]["gears"]["revision"] == basis["baselines"]["gears"]["revision"]
    # basis itself must be untouched (no in-place mutation).
    assert basis["baselines"]["gears"]["approximation_bias_report_sha256"] is None


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
        module.finalize_bias_config(basis_config_path=basis_yaml_path, report_path=report_path)


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
        module.finalize_bias_config(basis_config_path=basis_yaml_path, report_path=report_path)


# ---------------------------------------------------------------------------
# test_final_sha_absent_from_report
# ---------------------------------------------------------------------------


def test_final_sha_absent_from_report(tmp_path):
    """Uses the REAL computed final-config SHA (from actually running the tool),
    not a fabricated placeholder, so this genuinely exercises the one-way
    invariant rather than trivially asserting an arbitrary string is absent."""
    module = _load_finalize_module()
    basis = _basis_dict()
    basis_yaml_path = _write_basis_yaml(tmp_path, basis)
    basis_sha = sha256_json(yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8")))
    report = _bound_report(basis_sha)
    report_path = _write_report_json(tmp_path, report)

    final = module.finalize_bias_config(basis_config_path=basis_yaml_path, report_path=report_path)

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
# Bonus: the thin CLI end-to-end (not one of the five named tests, but the
# brief also requires a working `main()`).
# ---------------------------------------------------------------------------


def test_main_cli_writes_finalized_config(tmp_path):
    module = _load_finalize_module()
    basis = _basis_dict()
    basis_yaml_path = _write_basis_yaml(tmp_path, basis)
    basis_sha = sha256_json(yaml.safe_load(basis_yaml_path.read_text(encoding="utf-8")))
    report = _bound_report(basis_sha)
    report_path = _write_report_json(tmp_path, report)
    out_path = tmp_path / "finalized_config.yaml"

    exit_code = module.main(
        [
            "--basis-config",
            str(basis_yaml_path),
            "--report",
            str(report_path),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    assert out_path.exists()
    written = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    expected_report_sha = _expected_report_sha(report_path)
    assert written["baselines"]["gears"]["approximation_bias_report_sha256"] == expected_report_sha
    assert written["baselines"]["cpa"] == basis["baselines"]["cpa"]
