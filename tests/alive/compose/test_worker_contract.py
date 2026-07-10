# tests/alive/compose/test_worker_contract.py
"""SYNTHETIC-ONLY local contract tests for the real GEARS/CPA workers.

No ``gears``/``cpa`` import, no real data, no seal access. Exercises ONLY the
frozen worker contract surface (payload -> validate_fit_role_artifact ->
``_fit_and_predict`` -> ``write_predictions`` envelope) with a tiny synthetic
fit-role artifact. The two SEALED requested pairs enter the worker exclusively as
``sealed_pair_ids`` to the leakage guard and are NEVER fit rows.  The model-fit
bodies are import-guarded, so a host without the pinned backend must raise
``WorkerUnavailable``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import sparse

from alive.compose.baseline_subprocess import EXECUTION_MANIFEST_KEYS, write_payload
from alive.compose.fit_role import (
    ComposeFitRoleExtractor,
    build_response_projection,
    extract_fit_roles,
    generate_fit_role_artifact,
)
from alive.compose.response import fit_response_space

_REPO = Path(__file__).resolve().parents[3]
_WORKER_PATHS = {
    "gears": _REPO / "scripts" / "baselines" / "gears_worker.py",
    "cpa": _REPO / "scripts" / "baselines" / "cpa_worker.py",
}

# Synthetic universe. Expression features (var_names) are a distinct namespace
# from perturbation-target ids (single_gene_ids), matching the real data.
_VAR_NAMES = [f"G{i}" for i in range(8)]
_SINGLE_GENE_IDS = ["AAA", "BBB", "CCC", "DDD"]
_CALIBRATION = [("AAA", "BBB")]  # combo_calibration (fit) pair, canonical
_REQUESTED = [("CCC", "DDD")]  # sealed double-unseen request; ONLY a sealed_pair_id
_RESPONSE_DIM = 3


def _load_worker(name: str):
    """Import a worker script by path (its ``main()`` never runs on import)."""
    path = _WORKER_PATHS[name]
    spec = importlib.util.spec_from_file_location(f"_contract_worker_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _representation(worker_name: str) -> str:
    return "raw_pseudobulk_approximation" if worker_name == "gears" else "cell_raw_counts"


def _configure_worker_identity(worker, worker_name: str, approved_root: str, monkeypatch) -> None:
    """Install real byte-backed identity files matching the worker's exact config."""
    root = Path(approved_root)
    adapter_version = f"{worker_name}-contract-adapter-v1"
    config = worker._registered_worker_config(adapter_version)
    artifacts = {
        "CONFIG": (
            root / f"{worker_name}.worker-config.json",
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        ),
        "RESOURCE": (
            root / f"{worker_name}.resource-manifest.json",
            json.dumps(
                {"schema": "compose_contract_resource_manifest_v1", "method": worker_name},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        ),
        "ENVIRONMENT_LOCK": (
            root / f"{worker_name}.requirements.lock",
            f"{worker_name}==contract-only\n".encode(),
        ),
        "ADAPTER": (
            root / f"{worker_name}.adapter.bin",
            f"{worker_name}:{adapter_version}".encode(),
        ),
    }
    path_env = {
        "CONFIG": "ALIVE_WORKER_CONFIG_PATH",
        "RESOURCE": "ALIVE_WORKER_RESOURCE_MANIFEST_PATH",
        "ENVIRONMENT_LOCK": "ALIVE_WORKER_REQUIREMENTS_LOCK_PATH",
        "ADAPTER": "ALIVE_WORKER_ADAPTER_ARTIFACT_PATH",
    }
    digest_env = {
        "CONFIG": "ALIVE_WORKER_CONFIG_SHA256",
        "RESOURCE": "ALIVE_WORKER_RESOURCE_SHA256",
        "ENVIRONMENT_LOCK": "ALIVE_WORKER_ENVIRONMENT_LOCK_SHA256",
        "ADAPTER": "ALIVE_WORKER_ADAPTER_SHA256",
    }
    for field, (path, content) in artifacts.items():
        path.write_bytes(content)
        monkeypatch.setenv(path_env[field], str(path))
        monkeypatch.setenv(digest_env[field], hashlib.sha256(content).hexdigest())
    executable = Path(worker.__file__).resolve()
    monkeypatch.setenv("ALIVE_WORKER_EXECUTABLE_PATH", str(executable))
    monkeypatch.setenv(
        "ALIVE_WORKER_EXECUTABLE_SHA256",
        hashlib.sha256(executable.read_bytes()).hexdigest(),
    )
    payload_bytes = (root.parent / "work" / "payload.json").read_bytes()
    monkeypatch.setenv("ALIVE_WORKER_PAYLOAD_SHA256", hashlib.sha256(payload_bytes).hexdigest())
    monkeypatch.setenv("ALIVE_WORKER_ADAPTER_VERSION", adapter_version)


def _synthetic_fit(preds: dict[tuple[str, str], np.ndarray]):
    """Return a fit seam that obeys the real write-before-return checkpoint contract."""

    def _fit(*_args, **kwargs):
        Path(kwargs["checkpoint_path"]).write_bytes(b"synthetic-trained-model-state")
        return dict(preds)

    return _fit


def _build_fit_role_artifact(tmp_path: Path):
    """Write a valid synthetic fit-role .h5ad with NO sealed combo cell."""
    approved = tmp_path / "approved"
    approved.mkdir()
    obs_src = [f"r{i}" for i in range(6)]
    # control + 4 singles + the AAA_BBB calibration combo. No CCC_DDD combo cell:
    # the sealed requested pair is never materialised as a fit row.
    obs_pert = ["control", "AAA", "BBB", "CCC", "DDD", "AAA_BBB"]
    full = sparse.csr_matrix(np.arange(1, 6 * 8 + 1, dtype=np.float64).reshape(6, 8))
    extractor = ComposeFitRoleExtractor(
        obs_source_row_id=obs_src,
        obs_perturbation=obs_pert,
        var_names=_VAR_NAMES,
        calibration_pair_ids=_CALIBRATION,
        sealed_pair_ids=_REQUESTED,
        control_token="control",
        raw_data_sha256="raw-synth",
        pair_manifest_sha256="pm-synth",
        eligibility_hash="elig-synth",
        row_reader=lambda idx: full[idx],
    )
    extraction = extract_fit_roles(extractor=extractor)
    spec = generate_fit_role_artifact(
        extraction=extraction,
        out_path=str(approved / "fit_role.h5ad"),
        config_sha256="cfg",
        data_card_sha256="dc",
        calibration_gene_set_hash="cg",
        generator_code_sha256="gen",
        writer_environment_sha256="env",
    )
    return spec, str(approved)


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


def _build_payload(spec, block: dict) -> dict:
    """A minimal valid 14-key payload binding the artifact + projection."""
    return {
        "schema_version": 2,
        "response_dim": _RESPONSE_DIM,
        "seed": 11,
        "allowed_roles": ["combo_calibration", "singles"],
        "pair_ids": [list(p) for p in _REQUESTED],
        "single_gene_ids": list(_SINGLE_GENE_IDS),
        "singles_response": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9], [1.0, 1.1, 1.2]],
        "control_mean": block["control_mean"],
        "calibration_pair_ids": [list(p) for p in _CALIBRATION],
        "calibration_delta": [[0.5, 0.5, 0.5]],
        "pca_components": block["pca_components"],
        "oof_folds": [0],
        "fit_role_artifact": spec.to_payload_block(),
        "response_projection": block,
    }


def _setup(tmp_path: Path):
    spec, approved_root = _build_fit_role_artifact(tmp_path)
    block = _build_projection()
    payload = _build_payload(spec, block)
    work_dir = tmp_path / "work"
    write_payload(str(work_dir), payload)
    return spec, payload, str(work_dir), approved_root


def _argv(worker_name: str, work_dir: str, out: str, approved_root: str, representation: str):
    return [
        str(_WORKER_PATHS[worker_name]),
        "--in",
        work_dir,
        "--out",
        out,
        "--approved-root",
        approved_root,
        "--prediction-representation",
        representation,
    ]


@pytest.mark.parametrize("worker_name", ["gears", "cpa"])
def test_worker_emits_bound_envelope(worker_name, tmp_path, monkeypatch):
    # (a) With _fit_and_predict monkeypatched to synthetic preds, the worker
    # produces a {predictions, execution_manifest} envelope that round-trips and
    # whose manifest has EXACTLY the 14 keys; predictions_sha256 is emitted as ""
    # by the worker and FILLED (non-empty 64-hex) by write_predictions.
    worker = _load_worker(worker_name)
    spec, payload, work_dir, approved_root = _setup(tmp_path)
    _configure_worker_identity(worker, worker_name, approved_root, monkeypatch)

    # payload contract: control is reference data only; fit roles never include it.
    assert set(payload["allowed_roles"]) == {"singles", "combo_calibration"}
    assert "control" not in payload["allowed_roles"]
    assert spec.role_counts["control"] >= 1

    preds = {("CCC", "DDD"): np.array([0.3, 0.4, 0.5])}
    monkeypatch.setattr(worker, "_fit_and_predict", _synthetic_fit(preds))

    real_write = worker.write_predictions
    seen: dict[str, object] = {}

    def _spy_write(path, preds_arg, *, execution_manifest):
        seen["incoming_predictions_sha256"] = execution_manifest["predictions_sha256"]
        return real_write(path, preds_arg, execution_manifest=execution_manifest)

    monkeypatch.setattr(worker, "write_predictions", _spy_write)

    out = str(tmp_path / "preds")
    representation = _representation(worker_name)
    argv = _argv(worker_name, work_dir, out, approved_root, representation)
    monkeypatch.setattr(sys, "argv", argv)
    worker.main()

    # placeholder-then-filled: the worker emitted "" before write_predictions bound it.
    assert seen["incoming_predictions_sha256"] == ""

    with open(out + ".json") as fh:
        envelope = json.load(fh)
    assert set(envelope) == {"schema_version", "predictions", "execution_manifest"}
    manifest = envelope["execution_manifest"]
    assert set(manifest) == set(EXECUTION_MANIFEST_KEYS)
    assert len(manifest) == 14
    filled = manifest["predictions_sha256"]
    assert len(filled) == 64 and all(c in "0123456789abcdef" for c in filled)
    assert manifest["prediction_representation"] == representation
    assert (
        manifest["worker_sha256"]
        == hashlib.sha256(_WORKER_PATHS[worker_name].read_bytes()).hexdigest()
    )

    got = {tuple(pair): vec for pair, vec in envelope["predictions"]}
    assert set(got) == {("CCC", "DDD")}
    np.testing.assert_allclose(got[("CCC", "DDD")], [0.3, 0.4, 0.5])


@pytest.mark.parametrize("worker_name", ["gears", "cpa"])
def test_requested_pairs_passed_as_sealed_to_guard(worker_name, tmp_path, monkeypatch):
    # (b) validate_fit_role_artifact is invoked with sealed_pair_ids ==
    # payload["pair_ids"] (the requested pairs). Spy the guard to capture the kwarg.
    worker = _load_worker(worker_name)
    _spec, payload, work_dir, approved_root = _setup(tmp_path)
    _configure_worker_identity(worker, worker_name, approved_root, monkeypatch)

    preds = {("CCC", "DDD"): np.array([0.3, 0.4, 0.5])}
    monkeypatch.setattr(worker, "_fit_and_predict", _synthetic_fit(preds))

    captured: dict[str, object] = {}

    def _spy_validate(path, **kwargs):
        captured["path"] = path
        captured["kwargs"] = kwargs
        return None

    monkeypatch.setattr(worker, "validate_fit_role_artifact", _spy_validate)

    out = str(tmp_path / "preds")
    monkeypatch.setattr(
        sys,
        "argv",
        _argv(worker_name, work_dir, out, approved_root, _representation(worker_name)),
    )
    worker.main()

    kw = captured["kwargs"]
    assert kw["sealed_pair_ids"] == [tuple(p) for p in payload["pair_ids"]]
    assert kw["sealed_pair_ids"] == [("CCC", "DDD")]
    assert kw["calibration_pair_ids"] == [tuple(p) for p in payload["calibration_pair_ids"]]
    assert kw["single_gene_ids"] == [str(g) for g in payload["single_gene_ids"]]
    assert kw["approved_root"] == approved_root
    # the sealed requested pair is NEVER a calibration (fit) pair
    assert set(kw["sealed_pair_ids"]).isdisjoint(set(kw["calibration_pair_ids"]))


@pytest.mark.parametrize("worker_name", ["gears", "cpa"])
def test_real_fit_body_raises_worker_unavailable_without_backend(worker_name, tmp_path):
    # (c) Without monkeypatching, the real fit path is import-guarded. gears/cpa is
    # absent on this host, so _fit_and_predict raises the clear typed
    # WorkerUnavailable (NOT a silent stub, NOT a leaking NotImplementedError).
    # If a pinned backend is installed, the separately isolated worker logic
    # tests cover its pre-fit contract without starting a real scientific fit.
    if importlib.util.find_spec(worker_name) is not None:
        pytest.skip(f"{worker_name} installed; do not start a real fit in a local contract test")
    worker = _load_worker(worker_name)
    _spec, payload, _work_dir, _approved_root = _setup(tmp_path)
    with pytest.raises(worker.WorkerUnavailable):
        worker._fit_and_predict(
            payload,
            payload["fit_role_artifact"],
            payload["response_projection"],
            _VAR_NAMES,
            _representation(worker_name),
        )
