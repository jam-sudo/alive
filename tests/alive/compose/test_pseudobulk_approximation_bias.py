# tests/alive/compose/test_pseudobulk_approximation_bias.py
"""SYNTHETIC-ONLY unit test for the GEARS pseudobulk-approximation bias metric.

Model-independent + non-sealed: builds a tiny fit-role ``.h5ad`` (control +
singles + combo_calibration; NO sealed rows — a sealed combo is present in the
source obs only to prove it is EXCLUDED, never read) plus a frozen §2.2
``response_projection`` block, then checks the metric

1. emits the registered report shape with correct types and no bare
   ``NaN``/``Infinity`` (round-trips through ``json`` and every numeric leaf is
   finite or the string sentinel);
2. is a real known-answer discriminator — an all-identical group has NO
   aggregation gap (``b ≈ 0``) while a heterogeneous group (different library
   sizes + compositions) shows the nonlinear normalize+log1p gap (``‖b‖ > 0``);
3. reads ONLY the non-sealed artifact + block: imports no ``gears``/``cpa``,
   constructs no ``ComposeOutcomeStore``, opens no seal, and the report carries
   no sealed pair id.

No ``gears``/``cpa`` import, no real data, no seal access.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
from scipy import sparse

from alive.compose.fit_role import (
    ComposeFitRoleExtractor,
    build_response_projection,
    extract_fit_roles,
    generate_fit_role_artifact,
)
from alive.compose.response import fit_response_space

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "compose" / "measure_pseudobulk_approximation_bias.py"

# Synthetic universe. Expression features (var_names) are a distinct namespace
# from perturbation-target ids, matching the real data.
_VAR_NAMES = [f"G{i}" for i in range(8)]
_RESPONSE_DIM = 3
_SENTINEL = "NON_FINITE"


def _load_metric_module():
    """Import the metric script by path (its ``main()`` never runs on import)."""
    spec = importlib.util.spec_from_file_location("_pb_bias_metric", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_artifact(
    tmp_path: Path,
    obs_pert: list[str],
    rows: list[list[float]],
    *,
    calibration: list[tuple[str, str]],
    sealed: list[tuple[str, str]],
) -> str:
    """Write a valid synthetic fit-role ``.h5ad`` from explicit obs + raw rows."""
    approved = tmp_path / "approved"
    approved.mkdir(exist_ok=True)
    full = sparse.csr_matrix(np.asarray(rows, dtype=np.float64))
    extractor = ComposeFitRoleExtractor(
        obs_source_row_id=[f"r{i}" for i in range(len(obs_pert))],
        obs_perturbation=obs_pert,
        var_names=_VAR_NAMES,
        calibration_pair_ids=calibration,
        sealed_pair_ids=sealed,
        control_token="control",
        raw_data_sha256="raw-synth",
        pair_manifest_sha256="pm-synth",
        eligibility_hash="elig-synth",
        row_reader=lambda idx: full[idx],
    )
    extraction = extract_fit_roles(extractor=extractor)
    out_path = str(approved / "fit_role.h5ad")
    generate_fit_role_artifact(
        extraction=extraction,
        out_path=out_path,
        config_sha256="cfg",
        data_card_sha256="dc",
        calibration_gene_set_hash="cg",
        generator_code_sha256="gen",
        writer_environment_sha256="env",
    )
    return out_path


def _build_projection() -> dict:
    """A frozen §2.2 response_projection block over the synthetic gene order."""
    rng = np.random.default_rng(0)
    counts = rng.integers(1, 40, size=(32, 8)).astype(np.float64)
    X = sparse.csr_matrix(counts)
    control_idx = np.arange(0, 20)
    single_idx = np.arange(20, 32)
    space = fit_response_space(
        X,
        control_idx=control_idx,
        eligible_single_idx=single_idx,
        n_hvg=5,
        pca_dim=_RESPONSE_DIM,
        seed=1,
    )
    control_mean = space.project(X, control_idx).mean(axis=0)
    return build_response_projection(
        space,
        gene_order=_VAR_NAMES,
        control_mean=control_mean,
        raw_data_sha256="raw-synth",
    )


# Control: three IDENTICAL cells -> no aggregation gap -> b ≈ 0.
_CTRL_ROW = [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]
# Single AAA: three HETEROGENEOUS cells (different compositions AND library
# sizes) -> nonlinear normalize+log1p aggregation gap -> ‖b‖ > 0.
_AAA_ROWS = [
    [40.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0],  # lib 54, spike G0
    [2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 80.0],  # lib 94, spike G7
    [2.0, 2.0, 100.0, 2.0, 2.0, 100.0, 2.0, 2.0],  # lib 212, spike G2/G5
]
# Single BBB: two identical cells -> b ≈ 0.
_BBB_ROW = [3.0, 7.0, 3.0, 7.0, 3.0, 7.0, 3.0, 7.0]
# Combo calibration AAA_BBB: a single cell -> b = 0 (no aggregation).
_COMBO_ROW = [4.0, 4.0, 8.0, 8.0, 4.0, 4.0, 8.0, 8.0]
# Sealed combo ZZZ_YYY: present in obs ONLY to prove it is excluded (never read).
_SEALED_ROW = [9.0, 9.0, 9.0, 9.0, 9.0, 9.0, 9.0, 9.0]


def _mixed_artifact(tmp_path: Path) -> str:
    obs_pert = [
        "control",
        "control",
        "control",
        "AAA",
        "AAA",
        "AAA",
        "BBB",
        "BBB",
        "AAA_BBB",
        "ZZZ_YYY",
    ]
    rows = [
        _CTRL_ROW,
        _CTRL_ROW,
        _CTRL_ROW,
        *_AAA_ROWS,
        _BBB_ROW,
        _BBB_ROW,
        _COMBO_ROW,
        _SEALED_ROW,
    ]
    return _build_artifact(
        tmp_path,
        obs_pert,
        rows,
        calibration=[("AAA", "BBB")],
        sealed=[("YYY", "ZZZ")],
    )


def _numeric_leaves(obj):
    """Yield every float/int leaf in a JSON-loaded structure (skip the sentinel)."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield obj
    elif isinstance(obj, list):
        for v in obj:
            yield from _numeric_leaves(v)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _numeric_leaves(v)


def test_report_structure_and_no_non_finite(tmp_path):
    # (1) Report shape + types + canonical-JSON round-trip with no bare NaN/Inf.
    module = _load_metric_module()
    artifact = _mixed_artifact(tmp_path)
    block = _build_projection()

    report = module.measure_pseudobulk_approximation_bias(artifact, block, git_sha="deadbeef")

    expected_keys = {
        "deliverable",
        "protocol",
        "seal_status",
        "method",
        "git_sha",
        "gene_order_sha256",
        "pca_dim",
        "fit_role_artifact_sha256",
        "response_projection_sha256",
        "roles_measured",
        "n_groups",
        "group_roster",
        "directional_bias_l2",
        "directional_bias_per_dim",
        "relative_magnitude_median",
        "relative_magnitude_max",
    }
    assert set(report) == expected_keys

    assert report["protocol"] == "COMPOSE-K562-v1"
    assert report["git_sha"] == "deadbeef"
    assert report["gene_order_sha256"] == block["gene_order_sha256"]
    assert report["pca_dim"] == _RESPONSE_DIM
    assert isinstance(report["method"], str) and report["method"]

    # Four non-sealed groups: control, AAA, BBB, AAA_BBB. The sealed ZZZ_YYY is
    # excluded by construction.
    assert report["n_groups"] == len(report["group_roster"]) == 4
    assert report["group_roster"] == sorted(report["group_roster"])
    assert report["group_roster"] == [
        "combo_calibration::AAA_BBB",
        "control::control",
        "singles::AAA",
        "singles::BBB",
    ]
    assert report["roles_measured"] == ["combo_calibration", "control", "singles"]

    assert isinstance(report["directional_bias_per_dim"], list)
    assert len(report["directional_bias_per_dim"]) == _RESPONSE_DIM
    assert isinstance(report["directional_bias_l2"], float)

    # Canonical-JSON round-trip: every numeric leaf finite, no bare NaN/Infinity,
    # and the raw text carries no JS-style non-finite literals.
    text = json.dumps(report, sort_keys=True, separators=(",", ":"))
    assert "NaN" not in text and "Infinity" not in text
    loaded = json.loads(text)  # would raise on bare NaN/Infinity under strict mode
    for value in _numeric_leaves(loaded):
        assert math.isfinite(value)


def test_known_answer_identical_vs_heterogeneous(tmp_path):
    # (2) The metric distinguishes an all-identical group (no aggregation gap)
    # from a heterogeneous group (the nonlinear normalize+log1p gap).
    module = _load_metric_module()
    artifact = _mixed_artifact(tmp_path)
    block = _build_projection()

    groups = module._group_bias_vectors(artifact, block)
    ctrl_b = np.linalg.norm(groups["control::control"]["b"])
    bbb_b = np.linalg.norm(groups["singles::BBB"]["b"])
    combo_b = np.linalg.norm(groups["combo_calibration::AAA_BBB"]["b"])
    aaa_b = np.linalg.norm(groups["singles::AAA"]["b"])

    # Identical / single-cell groups: exactly no aggregation gap.
    assert ctrl_b < 1e-9
    assert bbb_b < 1e-9
    assert combo_b < 1e-9
    # Heterogeneous group: a materially non-zero, strictly larger gap.
    assert aaa_b > 1e-3
    assert aaa_b > ctrl_b

    # The aggregate report reflects it: the non-cancelling directional component
    # and the relative magnitude are both strictly positive.
    report = module.measure_pseudobulk_approximation_bias(artifact, block, git_sha="sha")
    assert report["directional_bias_l2"] > 1e-6
    assert isinstance(report["relative_magnitude_max"], float)
    assert report["relative_magnitude_max"] > 0.0
    assert isinstance(report["relative_magnitude_median"], float)


def test_relative_magnitude_sentinel_when_all_delta_pc_zero(tmp_path, monkeypatch):
    # Guard: when every group's per-cell delta has zero norm, the ratio is not
    # computable -> the report emits the house sentinel, never a bare NaN/Inf.
    module = _load_metric_module()
    artifact = _mixed_artifact(tmp_path)
    block = _build_projection()

    real = module._group_bias_vectors

    def _zero_delta(path, blk):
        groups = real(path, blk)
        for rec in groups.values():
            rec["delta_pc"] = np.zeros_like(rec["delta_pc"])
        return groups

    monkeypatch.setattr(module, "_group_bias_vectors", _zero_delta)
    report = module.measure_pseudobulk_approximation_bias(artifact, block, git_sha="sha")
    assert report["relative_magnitude_median"] == _SENTINEL
    assert report["relative_magnitude_max"] == _SENTINEL


def test_model_independent_and_no_seal(tmp_path):
    # (3) Source-level model-independence + no-seal guard, plus the report carries
    # no sealed pair id.
    source = _SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "import gears",
        "import cpa",
        "ComposeOutcomeStore",
        "outcome_store",
        "read_unsealed",
        "claim_sealed_access",
        "evaluate_sealed_once",
    ):
        assert forbidden not in source, f"metric script must not reference {forbidden!r}"

    module = _load_metric_module()
    artifact = _mixed_artifact(tmp_path)
    block = _build_projection()
    report = module.measure_pseudobulk_approximation_bias(artifact, block, git_sha="sha")

    blob = json.dumps(report)
    for sealed_token in ("ZZZ", "YYY", "ZZZ_YYY"):
        assert sealed_token not in blob
    assert all("ZZZ" not in key and "YYY" not in key for key in report["group_roster"])
