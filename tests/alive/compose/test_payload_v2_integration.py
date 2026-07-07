# tests/alive/compose/test_payload_v2_integration.py
"""SYNTHETIC-ONLY payload-v2 end-to-end: real fit-role .h5ad + operator stub.

No gears/cpa, no seal, no real Norman. Every fixture builds a synthetic
Norman-shaped AnnData under an approved root in ``tmp_path`` (``*.h5ad`` is
gitignored), writes a real fit-role artifact via the A1 extractor +
``generate_fit_role_artifact``, serializes the ``ResponseSpace`` operator, and
drives a combined double+single request through ``SubprocessBaselineBackend``
against ``scripts/baselines/stub_worker.py`` (the payload-v2 reference worker).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import sparse

from alive.compose.baseline_subprocess import (
    ExecutionIdentityLock,
    PayloadError,
    SubprocessBaselineBackend,
)
from alive.compose.baselines_combo import BaselineUnavailable
from alive.compose.fit_role import (
    FitRoleExtraction,
    build_response_projection,
    generate_fit_role_artifact,
)
from alive.compose.response import fit_response_space, verify_response_artifact

_STUB = str(Path(__file__).resolve().parents[3] / "scripts" / "baselines" / "stub_worker.py")
_RAW_DATA_SHA256 = "raw-shared-across-artifact-and-projection"
_RESPONSE_DIM = 4

# The exact fixed-constant execution identity ``stub_worker.py`` emits. A
# controller lock MUST mirror these or ``_verify_execution_manifest`` fails.
_STUB_ADAPTER_VERSION = "stub-2"
_STUB_ADAPTER_SHA256 = hashlib.sha256(b"stub-response-operator-v2").hexdigest()
_STUB_CONFIG_SHA256 = hashlib.sha256(b"stub-config").hexdigest()
_STUB_RESOURCE_SHA256 = hashlib.sha256(b"stub-resource").hexdigest()
_STUB_ENVIRONMENT_LOCK_SHA256 = hashlib.sha256(b"stub-environment").hexdigest()

# Sealed double + single-unseen request (canonical, disjoint from calibration).
_DOUBLE = ("AAA", "BBB")
_SINGLE = ("AAA", "CCC")
# The two combo_calibration groups present in the artifact.
_CALIB = [["DDD", "EEE"], ["FFF", "GGG"]]
_SINGLE_GENE_IDS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]


def _stub_lock() -> ExecutionIdentityLock:
    """The controller lock whose identities mirror ``stub_worker.py`` exactly."""
    return ExecutionIdentityLock(
        prediction_representation="cell_raw_counts",
        adapter_version=_STUB_ADAPTER_VERSION,
        adapter_sha256=_STUB_ADAPTER_SHA256,
        config_sha256=_STUB_CONFIG_SHA256,
        resource_sha256=_STUB_RESOURCE_SHA256,
        environment_lock_sha256=_STUB_ENVIRONMENT_LOCK_SHA256,
    )


def _make_fixture(out_path: str, *, seed: int = 0) -> dict:
    """Build a real fit-role ``.h5ad`` + a consistent v2 payload at ``out_path``.

    The AnnData carries control + single rows (the response-space fit set) plus
    two distinct ``combo_calibration`` groups (``DDD_EEE`` / ``FFF_GGG``) with
    multiple cells each and deliberately distinct native profiles, so a
    shared-delta or swapped pair mapping cannot pass accidentally. The
    ``var_names`` are the ``gene_order`` passed to ``build_response_projection``,
    so all three ``gene_order_sha256`` values agree; the payload's aggregate
    ``pca_components``/``control_mean`` are the projection's arrays.

    Parameters
    ----------
    out_path : str
        Destination ``.h5ad`` path (must not already exist).
    seed : int, default 0
        RNG seed for the synthetic counts.

    Returns
    -------
    dict
        ``{"payload", "combined", "response_dim", "out_path", "gene_order"}``.
    """
    rng = np.random.default_rng(1000 + seed)
    n_genes = 6
    gene_order = [f"G{i}" for i in range(n_genes)]
    n_control, n_single = 12, 8
    n_calib_a, n_calib_b = 5, 5
    n_cells = n_control + n_single + n_calib_a + n_calib_b
    counts = rng.integers(1, 40, size=(n_cells, n_genes)).astype(np.float64)
    # deliberately distinct native profiles for the two calibration groups so
    # their projected means (and δ̂) differ.
    a0 = n_control + n_single
    a1 = a0 + n_calib_a
    counts[a0:a1, 0] += 60.0
    counts[a1:, n_genes - 1] += 60.0
    X = sparse.csr_matrix(counts)

    control_idx = np.arange(0, n_control)
    single_idx = np.arange(n_control, n_control + n_single)
    space = fit_response_space(
        X,
        control_idx=control_idx,
        eligible_single_idx=single_idx,
        n_hvg=n_genes,
        pca_dim=_RESPONSE_DIM,
        seed=seed,
    )
    control_mean = space.project(X, control_idx).mean(axis=0)
    _, _, combined = verify_response_artifact(space, control_mean)
    proj = build_response_projection(
        space, gene_order=gene_order, control_mean=control_mean, raw_data_sha256=_RAW_DATA_SHA256
    )

    # singles-cell tokens are drawn from the governed single-gene universe
    # (``_SINGLE_GENE_IDS``): a `singles` perturbation targets a gene in the
    # universe, and the fit-role validator now rejects any `singles` token outside
    # it (the sealed-combo-as-single leak guard).
    rows = (
        [(f"c{i}", "control", "control") for i in range(n_control)]
        + [
            (f"s{i}", "singles", _SINGLE_GENE_IDS[i % len(_SINGLE_GENE_IDS)])
            for i in range(n_single)
        ]
        + [(f"da{i}", "combo_calibration", "DDD_EEE") for i in range(n_calib_a)]
        + [(f"db{i}", "combo_calibration", "FFF_GGG") for i in range(n_calib_b)]
    )
    extraction = FitRoleExtraction(
        X=X,
        var_names=tuple(gene_order),
        rows=tuple(rows),
        role_counts={
            "control": n_control,
            "singles": n_single,
            "combo_calibration": n_calib_a + n_calib_b,
        },
        raw_data_sha256=_RAW_DATA_SHA256,
        pair_manifest_sha256="pair-manifest-v2",
        eligibility_hash="eligibility-v2",
    )
    spec = generate_fit_role_artifact(
        extraction=extraction,
        out_path=out_path,
        config_sha256="config-sha",
        data_card_sha256="data-card-sha",
        calibration_gene_set_hash="cal-set-sha",
        generator_code_sha256="gen-code-sha",
        writer_environment_sha256="writer-env-sha",
    )

    payload = {
        "schema_version": 2,
        "response_dim": _RESPONSE_DIM,
        "seed": 11,
        "allowed_roles": ["combo_calibration", "singles"],
        "pair_ids": [list(_DOUBLE), list(_SINGLE)],
        "single_gene_ids": list(_SINGLE_GENE_IDS),
        "singles_response": [[0.0] * _RESPONSE_DIM for _ in _SINGLE_GENE_IDS],
        "control_mean": proj["control_mean"],
        "calibration_pair_ids": [list(p) for p in _CALIB],
        "calibration_delta": [[0.1] * _RESPONSE_DIM, [0.2] * _RESPONSE_DIM],
        "pca_components": proj["pca_components"],
        "oof_folds": [0, 0],
        "fit_role_artifact": spec.to_payload_block(),
        "response_projection": proj,
    }
    return {
        "payload": payload,
        "combined": combined,
        "response_dim": _RESPONSE_DIM,
        "out_path": out_path,
        "gene_order": gene_order,
    }


def _backend(
    approved_root: Path,
    combined: str,
    *,
    lock: ExecutionIdentityLock | None = None,
) -> SubprocessBaselineBackend:
    """A stub-backed subprocess backend bound to ``approved_root`` + ``combined``."""
    return SubprocessBaselineBackend(
        name="stub",
        env_python=sys.executable,
        worker_script=_STUB,
        import_name="json",
        approved_artifacts_root=str(approved_root),
        expected_response_artifact_sha256=combined,
        execution_identity_lock=lock or _stub_lock(),
    )


def test_operator_path_predicts_both_pairs_with_nontrivial_pair_associated_delta(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    fx = _make_fixture(str(approved / "fit_role.h5ad"))
    backend = _backend(approved, fx["combined"])
    backend.configure_payload(fx["payload"])

    out = backend.predict(None, [_DOUBLE, _SINGLE], fx["response_dim"])

    assert set(out) == {_DOUBLE, _SINGLE}
    for vec in out.values():
        assert vec.shape == (fx["response_dim"],)
        assert np.all(np.isfinite(vec))
    # the projection path ran: δ̂ is not identically zero for calibration-cell preds
    assert any(np.linalg.norm(v) > 1e-9 for v in out.values())
    # pair-to-native-group association is exercised (not one shared delta)
    assert not np.array_equal(out[_DOUBLE], out[_SINGLE])

    # the verified execution manifest enters the provenance manifest post-predict.
    prov = backend.provenance_manifest
    assert prov["execution_manifest"]["prediction_representation"] == "cell_raw_counts"
    assert prov["execution_manifest"]["adapter_version"] == _STUB_ADAPTER_VERSION
    assert len(prov["execution_manifest"]["checkpoint_sha256"]) == 64
    assert len(prov["execution_manifest"]["predictions_sha256"]) == 64


def test_artifact_byte_tamper_aborts_before_predictions(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    fx = _make_fixture(str(approved / "fit_role.h5ad"))
    backend = _backend(approved, fx["combined"])
    backend.configure_payload(fx["payload"])
    # mutate the artifact bytes AFTER the payload is built: the worker's file-SHA
    # check no longer matches the spec, so it fails closed before any prediction.
    with open(fx["out_path"], "ab") as fh:
        fh.write(b"\x00tampered-trailing-bytes")
    with pytest.raises(BaselineUnavailable):
        backend.predict(None, [_DOUBLE, _SINGLE], fx["response_dim"])


def test_manifest_identity_divergence_from_lock_is_rejected(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    fx = _make_fixture(str(approved / "fit_role.h5ad"))
    # a controller-verifiable manifest identity (environment lock) diverges from
    # the worker's emitted constant -> _verify_execution_manifest fails closed.
    bad_lock = ExecutionIdentityLock(
        prediction_representation="cell_raw_counts",
        adapter_version=_STUB_ADAPTER_VERSION,
        adapter_sha256=_STUB_ADAPTER_SHA256,
        config_sha256=_STUB_CONFIG_SHA256,
        resource_sha256=_STUB_RESOURCE_SHA256,
        environment_lock_sha256="0" * 64,
    )
    backend = _backend(approved, fx["combined"], lock=bad_lock)
    backend.configure_payload(fx["payload"])
    with pytest.raises(PayloadError, match="environment_lock_sha256"):
        backend.predict(None, [_DOUBLE, _SINGLE], fx["response_dim"])


def test_artifact_outside_approved_root_is_rejected(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    # the artifact is otherwise valid (real file SHA + content manifest) but lives
    # outside the backend's approved root, so the worker's path policy rejects it.
    fx = _make_fixture(str(outside / "fit_role.h5ad"))
    backend = _backend(approved, fx["combined"])
    backend.configure_payload(fx["payload"])
    with pytest.raises(BaselineUnavailable):
        backend.predict(None, [_DOUBLE, _SINGLE], fx["response_dim"])
