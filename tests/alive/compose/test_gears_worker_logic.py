"""Focused unit tests for the real GEARS worker's leakage/provenance logic.

The real ``cell-gears`` package is not installed in the repository environment.
These tests install a narrow fake module surface that exercises the committed fit
body itself: offline resource staging, exact-role loaders, RNG binding, fixed
epochs, trained-state checkpoint ordering, and temporary-directory cleanup.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import sys
import types
from importlib import metadata as importlib_metadata
from pathlib import Path
from types import SimpleNamespace

import anndata as ad
import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from alive.provenance import sha256_json

_REPO = Path(__file__).resolve().parents[3]
_WORKER = _REPO / "scripts" / "baselines" / "gears_worker.py"


def _load_worker():
    spec = importlib.util.spec_from_file_location("_gears_worker_logic", _WORKER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_resource_bundle(tmp_path: Path, monkeypatch) -> tuple[Path, dict[str, bytes]]:
    root = tmp_path / "resources"
    (root / "go_essential_all").mkdir(parents=True)
    content = {
        "gene2go_all.pkl": b"gene2go-pinned",
        "essential_all_data_pert_genes.pkl": b"essential-pinned",
        "go_essential_all.tar.gz": b"archive-pinned",
        "go_essential_all/go_essential_all.csv": b"source,target,importance\nA,B,1.0\n",
    }
    for relative, data in content.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    resources = []
    for name in (
        "gene2go_all.pkl",
        "essential_all_data_pert_genes.pkl",
        "go_essential_all.tar.gz",
    ):
        entry = {
            "name": name,
            "bytes": len(content[name]),
            "sha256": _sha(content[name]),
        }
        if name == "go_essential_all.tar.gz":
            extracted = content["go_essential_all/go_essential_all.csv"]
            entry["extracted_artifact"] = {
                "name": "go_essential_all/go_essential_all.csv",
                "bytes": len(extracted),
                "sha256": _sha(extracted),
            }
        resources.append(entry)
    manifest = {
        "schema": "compose_go_resource_manifest_v2",
        "protocol": "COMPOSE-K562-v1",
        "resources": resources,
    }
    manifest["manifest_checksum"] = sha256_json(manifest)
    manifest_path = root / "go_resource_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALIVE_WORKER_RESOURCE_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("ALIVE_WORKER_RESOURCE_SHA256", _sha(manifest_path.read_bytes()))
    return manifest_path, content


def _fit_adata() -> ad.AnnData:
    conditions = ["control"] * 4 + ["AAA"] * 4 + ["BBB"] * 4 + ["AAA_BBB"] * 4
    counts = sparse.csr_matrix(np.arange(1, len(conditions) * 4 + 1).reshape(-1, 4))
    return ad.AnnData(
        X=counts,
        obs=pd.DataFrame(
            {"perturbation": conditions},
            index=[f"cell-{index}" for index in range(len(conditions))],
        ),
        var=pd.DataFrame(index=["G0", "G1", "G2", "G3"]),
    )


def _install_fake_gears(
    monkeypatch,
    events: list[object],
    work_paths: list[str],
    *,
    seed: int = 11,
) -> None:
    monkeypatch.setattr(importlib_metadata, "version", lambda name: "0.1.2")
    monkeypatch.setenv("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    monkeypatch.setenv("PYTHONHASHSEED", str(seed))
    fake_gears = types.ModuleType("gears")
    fake_gears.__path__ = []
    fake_gears.__file__ = str(Path(sys.prefix) / "pyvenv.cfg")
    fake_pertdata = types.ModuleType("gears.pertdata")
    fake_utils = types.ModuleType("gears.utils")

    def _unexpected_download(*_args, **_kwargs):
        events.append("network-download")
        raise AssertionError("network download must be replaced by the offline guard")

    fake_pertdata.dataverse_download = _unexpected_download
    fake_pertdata.tar_data_download_wrapper = _unexpected_download
    fake_pertdata.zip_data_download_wrapper = _unexpected_download
    fake_utils.dataverse_download = _unexpected_download
    fake_utils.tar_data_download_wrapper = _unexpected_download
    fake_utils.zip_data_download_wrapper = _unexpected_download

    class FakePertData:
        def __init__(self, data_path):
            self.data_path = data_path
            work_paths.append(data_path)
            for relative in (
                "gene2go_all.pkl",
                "essential_all_data_pert_genes.pkl",
                "go_essential_all.tar.gz",
                "go_essential_all/go_essential_all.csv",
            ):
                resource = Path(data_path) / relative
                assert resource.is_file()
                assert not resource.is_symlink()
            assert not (Path(data_path) / "go_essential_all").is_symlink()
            # GEARS calls this unconditionally; the worker's offline guard must
            # return only because the verified file is already staged.
            fake_pertdata.dataverse_download(
                "https://forbidden.invalid/gene2go",
                os.path.join(data_path, "gene2go_all.pkl"),
            )

        def new_data_process(self, _name, *, adata):
            self.adata = adata
            self.pert_names = np.asarray(["AAA", "BBB"])
            fake_pertdata.dataverse_download(
                "https://forbidden.invalid/essential",
                os.path.join(self.data_path, "essential_all_data_pert_genes.pkl"),
            )
            self.dataset_processed = {
                condition: [(condition, index) for index in range(20)]
                for condition in adata.obs["condition"].astype(str).unique()
            }

    class FakeTensor:
        def __init__(self, value):
            self.value = value

        def detach(self):
            return self

        def cpu(self):
            return self

    class FakeBestModel:
        def state_dict(self):
            return {"layer.weight": FakeTensor(7)}

    class FakeGEARS:
        def __init__(self, pert_data, *, device):
            self.pert_data = pert_data
            self.device = device
            assert device == "cuda"
            assert pert_data.node_map == {"G0": 0, "G1": 1, "G2": 2, "G3": 3}
            self.pert_list = ["AAA", "BBB"]
            self.best_model = None

        def model_initialize(self, **kwargs):
            fake_utils.tar_data_download_wrapper(
                "https://forbidden.invalid/go",
                os.path.join(self.pert_data.data_path, "go_essential_all"),
                self.pert_data.data_path,
            )
            events.append(("initialize", dict(kwargs)))
            self.model = FakeBestModel()

        def train(self, **kwargs):
            events.append(("train", dict(kwargs)))
            assert len(self.pert_data.dataloader["train_loader"].data) == 60
            assert len(self.pert_data.dataloader["val_loader"].data) == 6
            train_conditions = {
                condition for condition, _index in self.pert_data.dataloader["train_loader"].data
            }
            val_conditions = {
                condition for condition, _index in self.pert_data.dataloader["val_loader"].data
            }
            assert "ctrl" not in train_conditions
            assert train_conditions == {"AAA+ctrl", "BBB+ctrl", "AAA+BBB"}
            assert val_conditions == train_conditions
            assert self.pert_data.set2conditions["train"] == sorted(train_conditions)
            self.best_model = FakeBestModel()

        def predict(self, requests):
            events.append(("predict", tuple(tuple(pair) for pair in requests)))
            assert "checkpoint" in events
            return {"AAA_BBB": np.array([4.0, -3.0, 2.0, 1.0])}

    fake_gears.GEARS = FakeGEARS
    fake_gears.PertData = FakePertData
    fake_gears.pertdata = fake_pertdata
    fake_gears.utils = fake_utils

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = SimpleNamespace(
        is_available=lambda: True,
        manual_seed_all=lambda seed: events.append(("cuda-seed", seed)),
    )
    fake_torch.backends = SimpleNamespace(
        cudnn=SimpleNamespace(deterministic=False, benchmark=True)
    )
    fake_torch.manual_seed = lambda seed: events.append(("torch-seed", seed))
    fake_torch.use_deterministic_algorithms = lambda enabled: events.append(
        ("deterministic-algorithms", enabled)
    )

    def _save(obj, file_obj):
        assert obj["schema"] == "compose_gears_trained_model_v1"
        assert obj["model_state_dict"]
        assert obj["training_device"] == "cuda"
        assert obj["numeric_precision"] == "float32"
        assert obj["training_config"]["model_selection_policy"] == "fixed_final_epoch"
        assert obj["split_manifest"]["monitoring_policy"].endswith("no_holdout")
        events.append("checkpoint")
        file_obj.write(b"actual-trained-state")

    fake_torch.save = _save

    fake_torch_geometric = types.ModuleType("torch_geometric")
    fake_torch_geometric.__path__ = []
    fake_loader = types.ModuleType("torch_geometric.loader")

    class FakeDataLoader:
        def __init__(self, data, **kwargs):
            self.data = list(data)
            self.kwargs = dict(kwargs)

    fake_loader.DataLoader = FakeDataLoader
    fake_torch_geometric.loader = fake_loader

    monkeypatch.setitem(sys.modules, "gears", fake_gears)
    monkeypatch.setitem(sys.modules, "gears.pertdata", fake_pertdata)
    monkeypatch.setitem(sys.modules, "gears.utils", fake_utils)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "torch_geometric", fake_torch_geometric)
    monkeypatch.setitem(sys.modules, "torch_geometric.loader", fake_loader)


def test_resource_bundle_requires_controller_identity(tmp_path, monkeypatch):
    worker = _load_worker()
    monkeypatch.delenv("ALIVE_WORKER_RESOURCE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("ALIVE_WORKER_RESOURCE_SHA256", raising=False)
    with pytest.raises(ValueError, match="fit-time resource download"):
        worker._validate_gears_resource_bundle()

    manifest_path, _content = _write_resource_bundle(tmp_path, monkeypatch)
    monkeypatch.setenv("ALIVE_WORKER_RESOURCE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="resource manifest SHA-256"):
        worker._validate_gears_resource_bundle()
    assert manifest_path.is_file()


def test_resource_manifest_is_parsed_from_verified_descriptor_bytes(tmp_path, monkeypatch):
    worker = _load_worker()
    _write_resource_bundle(tmp_path, monkeypatch)

    def _forbid_reopen(*_args, **_kwargs):
        raise AssertionError("verified manifest path must not be reopened for parsing")

    monkeypatch.setattr(Path, "read_text", _forbid_reopen)
    bundle = worker._validate_gears_resource_bundle()
    assert bundle["manifest_bytes"]


def test_resource_bundle_rejects_mutated_resource(tmp_path, monkeypatch):
    worker = _load_worker()
    manifest_path, _content = _write_resource_bundle(tmp_path, monkeypatch)
    bundle = worker._validate_gears_resource_bundle()
    (manifest_path.parent / "gene2go_all.pkl").write_bytes(b"substituted")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    with pytest.raises(ValueError, match="byte count|SHA-256"):
        worker._stage_gears_resource_bundle(bundle, str(snapshot))


def test_resource_snapshot_isolated_from_later_source_mutation(tmp_path, monkeypatch):
    worker = _load_worker()
    manifest_path, content = _write_resource_bundle(tmp_path, monkeypatch)
    bundle = worker._validate_gears_resource_bundle()
    snapshot_root = tmp_path / "snapshot"
    snapshot_root.mkdir()
    snapshot = worker._stage_gears_resource_bundle(bundle, str(snapshot_root))

    (manifest_path.parent / "gene2go_all.pkl").write_bytes(b"later-source-replacement")
    staged = snapshot_root / "gene2go_all.pkl"
    assert staged.read_bytes() == content["gene2go_all.pkl"]
    assert staged.is_file() and not staged.is_symlink()
    worker._revalidate_gears_resource_bundle(snapshot)


def test_real_fit_is_offline_seeded_role_exact_and_checkpointed_before_predict(
    tmp_path,
    monkeypatch,
):
    worker = _load_worker()
    _write_resource_bundle(tmp_path, monkeypatch)
    # A stale smoke override must have no effect on the production worker.
    monkeypatch.setenv("COMPOSE_GEARS_SMOKE_EPOCHS", "1")
    events: list[object] = []
    work_paths: list[str] = []
    _install_fake_gears(monkeypatch, events, work_paths, seed=23)
    monkeypatch.setattr(
        worker,
        "apply_response_projection",
        lambda _proj, native, _genes, *, representation: np.asarray(native)[:, :2],
    )

    seed = 23
    checkpoint = tmp_path / "trained.checkpoint"
    payload = {
        "seed": seed,
        "pair_ids": [["AAA", "BBB"]],
        "response_dim": 2,
    }
    projection = {"control_mean": [0.0, 0.0]}
    result = worker._fit_and_predict(
        payload,
        _fit_adata(),
        projection,
        ["G0", "G1", "G2", "G3"],
        "raw_pseudobulk_approximation",
        fit_artifact_content_sha256="c" * 64,
        checkpoint_path=str(checkpoint),
    )

    assert checkpoint.read_bytes() == b"actual-trained-state"
    prediction_index = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, tuple) and event[0] == "predict"
    )
    assert events.index("checkpoint") < prediction_index
    train_event = next(
        event for event in events if isinstance(event, tuple) and event[0] == "train"
    )
    assert train_event[1] == {"epochs": 20, "lr": 1e-3, "weight_decay": 5e-4}
    initialize_event = next(
        event for event in events if isinstance(event, tuple) and event[0] == "initialize"
    )
    assert initialize_event[1]["hidden_size"] == 64
    assert initialize_event[1]["uncertainty"] is False
    assert initialize_event[1]["direction_lambda"] == 0.1
    assert ("torch-seed", seed) in events
    assert ("cuda-seed", seed) in events
    assert ("deterministic-algorithms", True) in events
    assert "network-download" not in events
    pair_seed = worker._pair_prediction_seed(seed, ("AAA", "BBB"))
    assert random.random() == random.Random(pair_seed).random()
    assert np.random.random() == np.random.RandomState(pair_seed).random_sample()
    np.testing.assert_allclose(result[("AAA", "BBB")], [4.0, 0.0])
    assert len(work_paths) == 1
    assert not os.path.exists(work_paths[0])


def test_existing_checkpoint_fails_before_fit(tmp_path, monkeypatch):
    worker = _load_worker()
    _write_resource_bundle(tmp_path, monkeypatch)
    events: list[object] = []
    work_paths: list[str] = []
    _install_fake_gears(monkeypatch, events, work_paths)
    checkpoint = tmp_path / "trained.checkpoint"
    checkpoint.write_bytes(b"preexisting")
    with pytest.raises(ValueError, match="already exists"):
        worker._fit_and_predict(
            {"seed": 11, "pair_ids": [["AAA", "BBB"]], "response_dim": 2},
            _fit_adata(),
            {"control_mean": [0.0, 0.0]},
            ["G0", "G1", "G2", "G3"],
            "raw_pseudobulk_approximation",
            fit_artifact_content_sha256="c" * 64,
            checkpoint_path=str(checkpoint),
        )


def test_missing_nonrequest_fit_gene_is_rejected_before_training(tmp_path, monkeypatch):
    worker = _load_worker()
    _write_resource_bundle(tmp_path, monkeypatch)
    events: list[object] = []
    work_paths: list[str] = []
    _install_fake_gears(monkeypatch, events, work_paths)
    source = _fit_adata()
    source.obs.loc[source.obs["perturbation"] == "AAA_BBB", "perturbation"] = "AAA_CCC"
    checkpoint = tmp_path / "trained.checkpoint"
    with pytest.raises(ValueError, match="PertData.pert_names.*CCC"):
        worker._fit_and_predict(
            {"seed": 11, "pair_ids": [["AAA", "BBB"]], "response_dim": 2},
            source,
            {"control_mean": [0.0, 0.0]},
            ["G0", "G1", "G2", "G3"],
            "raw_pseudobulk_approximation",
            fit_artifact_content_sha256="c" * 64,
            checkpoint_path=str(checkpoint),
        )
    assert not checkpoint.exists()
    assert not any(isinstance(event, tuple) and event[0] == "train" for event in events)


def test_cell_level_prediction_representation_is_rejected(tmp_path, monkeypatch):
    worker = _load_worker()
    events: list[object] = []
    work_paths: list[str] = []
    _install_fake_gears(monkeypatch, events, work_paths)
    with pytest.raises(ValueError, match="method-locked raw pseudobulk"):
        worker._fit_and_predict(
            {"seed": 11, "pair_ids": [["AAA", "BBB"]], "response_dim": 2},
            _fit_adata(),
            {"control_mean": [0.0, 0.0]},
            ["G0", "G1", "G2", "G3"],
            "cell_raw_counts",
            fit_artifact_content_sha256="c" * 64,
            checkpoint_path=str(tmp_path / "trained.checkpoint"),
        )
    assert not events


def test_raw_input_scale_remains_explicitly_activation_blocked():
    worker = _load_worker()
    assert worker._GEARS_NATIVE_INPUT_SCALE == "raw_counts"
    assert worker._GEARS_NATIVE_INPUT_SCALE_STATUS.startswith("ACTIVATION_BLOCKED")


def test_pair_prediction_rng_is_request_order_independent():
    worker = _load_worker()

    class _Model:
        @staticmethod
        def predict(requests):
            pair = requests[0]
            return {"_".join(pair): np.asarray([np.random.random()])}

    fake_torch = SimpleNamespace(
        manual_seed=lambda _seed: None,
        cuda=SimpleNamespace(manual_seed_all=lambda _seed: None),
    )
    forward = worker._predict_pairs_order_independent(
        _Model(),
        [["AAA", "BBB"], ["AAA", "CCC"]],
        seed=19,
        torch_module=fake_torch,
    )
    reverse = worker._predict_pairs_order_independent(
        _Model(),
        [["AAA", "CCC"], ["AAA", "BBB"]],
        seed=19,
        torch_module=fake_torch,
    )
    assert set(forward) == set(reverse)
    for key in forward:
        np.testing.assert_array_equal(forward[key], reverse[key])
