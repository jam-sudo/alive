"""Pure/mock scientific-logic tests for the CPA 0.8.5 worker.

No CPA installation, GPU, real data, external access, or seal is used.  The
tests exercise the code-registered defaults, seed propagation, control-role
boundary, stable verified-AnnData handoff, and real-state checkpoint ordering.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from importlib import metadata as importlib_metadata
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from alive.compose.fit_role import canonical_gene_order_sha256

_REPO = Path(__file__).resolve().parents[3]
_WORKER_PATH = _REPO / "scripts" / "baselines" / "cpa_worker.py"


def _load_worker():
    """Load exactly as the existing contract tests do (without sys.modules registration)."""
    spec = importlib.util.spec_from_file_location("_cpa_worker_logic", _WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verified_adata() -> ad.AnnData:
    genes = [f"G{i}" for i in range(6)]
    perturbations = [
        "control",
        "control",
        "AAA",
        "AAA",
        "AAA",
        "BBB",
        "BBB",
        "CCC",
        "CCC",
        "DDD",
        "DDD",
        "AAA_BBB",
        "AAA_BBB",
    ]
    roles = [
        "control",
        "control",
        "singles",
        "singles",
        "singles",
        "singles",
        "singles",
        "singles",
        "singles",
        "singles",
        "singles",
        "combo_calibration",
        "combo_calibration",
    ]
    counts = sparse.csr_matrix(
        np.arange(1, len(perturbations) * len(genes) + 1, dtype=np.float64).reshape(
            len(perturbations), len(genes)
        )
    )
    return ad.AnnData(
        X=counts,
        obs=pd.DataFrame(
            {"perturbation": perturbations, "role": roles},
            index=[f"row-{i}" for i in range(len(perturbations))],
        ),
        var=pd.DataFrame(index=genes),
    )


def _payload() -> dict:
    return {
        "seed": 17,
        "response_dim": 2,
        "pair_ids": [["CCC", "DDD"]],
    }


def _install_fake_science_modules(monkeypatch, records: dict[str, object]) -> None:
    events: list[str] = records.setdefault("events", [])
    monkeypatch.setattr(importlib_metadata, "version", lambda name: "0.8.5")
    monkeypatch.setenv("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    monkeypatch.setenv("PYTHONHASHSEED", "17")

    fake_torch = types.ModuleType("torch")

    def _manual_seed(seed):
        records["torch_seed"] = seed
        events.append("torch_seed")

    def _cuda_seed(seed):
        records["cuda_seed"] = seed
        events.append("cuda_seed")

    def _save(obj, fh):
        records["checkpoint"] = obj
        events.append("checkpoint")
        fh.write(b"mock-cpa-state-dict\n")
        fh.write(repr(sorted(obj)).encode("utf-8"))

    fake_torch.manual_seed = _manual_seed
    fake_torch.save = _save
    fake_torch.cuda = types.SimpleNamespace(manual_seed_all=_cuda_seed, is_available=lambda: True)
    fake_torch.use_deterministic_algorithms = lambda enabled: records.__setitem__(
        "deterministic_algorithms", enabled
    )
    fake_torch.backends = types.SimpleNamespace(
        cudnn=types.SimpleNamespace(deterministic=False, benchmark=True)
    )

    registry = types.SimpleNamespace(
        PERTURBATIONS="perts",
        PERTURBATIONS_DOSAGES="perts_doses",
        CONTROL_KEY=None,
        DEG_MASK=None,
        DEG_MASK_R2=None,
        PADDING_IDX=0,
    )

    class _Module:
        @staticmethod
        def state_dict():
            return {"decoder.weight": [1.0, 2.0]}

    class _CPA:
        pert_encoder = None

        @staticmethod
        def setup_anndata(adata, **kwargs):
            records["setup_adata"] = adata
            records["setup_kwargs"] = kwargs
            events.append("setup")
            perturbation_key = kwargs["perturbation_key"]
            control_group = kwargs["control_group"]
            conditions = [str(value) for value in adata.obs[perturbation_key]]
            names = sorted(
                {
                    gene
                    for condition in conditions
                    for gene in condition.split("+")
                    if gene != control_group
                }
            )
            _CPA.pert_encoder = {
                name: index for index, name in enumerate(["", control_group, *names])
            }
            perts = []
            doses = []
            for condition in conditions:
                genes = [gene for gene in condition.split("+") if gene in _CPA.pert_encoder]
                ids = [_CPA.pert_encoder[gene] for gene in genes][:2]
                perts.append(ids + [registry.PADDING_IDX] * (2 - len(ids)))
                doses.append([1.0] * len(ids) + [0.0] * (2 - len(ids)))
            adata.obsm[registry.PERTURBATIONS] = np.asarray(perts, dtype=int)
            adata.obsm[registry.PERTURBATIONS_DOSAGES] = np.asarray(doses, dtype=float)
            registry.CONTROL_KEY = f"CPA_{control_group}"
            adata.obs[registry.CONTROL_KEY] = [
                int(condition == control_group) for condition in conditions
            ]
            registry.DEG_MASK = "deg_mask"
            registry.DEG_MASK_R2 = "deg_mask_r2"
            rankings = adata.uns[kwargs["deg_uns_key"]]
            categories = [str(value) for value in adata.obs[kwargs["deg_uns_cat_key"]]]
            full_rows = []
            for category in categories:
                ranked = rankings.get(category)
                full_rows.append(
                    np.ones(adata.n_vars, dtype=int)
                    if ranked is None
                    else np.isin(adata.var_names, ranked).astype(int)
                )
            full_mask = np.vstack(full_rows)
            adata.obsm[registry.DEG_MASK] = full_mask
            # Reproduce cpa-tools 0.8.5's cov_cond_map/cov_cond_map_r2 typo:
            # the nominal R2 mask incorrectly receives the full ranked mask.
            adata.obsm[registry.DEG_MASK_R2] = full_mask.copy()

        def __init__(self, adata, **kwargs):
            records["model_adata"] = adata
            records["model_kwargs"] = kwargs
            events.append("model_init")
            self.module = _Module()
            self.pert_encoder = dict(_CPA.pert_encoder)
            self.adata_manager = types.SimpleNamespace(
                get_from_registry=lambda key: adata.obsm[key]
            )
            records["pert_encoder"] = dict(self.pert_encoder)

        def train(self, **kwargs):
            records["train_kwargs"] = kwargs
            events.append("train")

        def _validate_anndata(self, adata):
            records["query_adata"] = adata
            records.setdefault("query_adatas", []).append(adata)
            events.append("query_validate")
            return adata

        def predict(self, adata, **kwargs):
            records["predict_kwargs"] = kwargs
            events.append("predict")
            values = np.asarray(adata.X.toarray(), dtype=np.float64) + 1.0
            values[:, 0] = -5.0
            adata.obsm["CPA_pred"] = values

    fake_cpa = types.ModuleType("cpa")
    fake_cpa.__file__ = str(Path(sys.prefix) / "pyvenv.cfg")
    fake_cpa.CPA = _CPA
    fake_cpa_utils = types.ModuleType("cpa._utils")
    fake_cpa_utils.CPA_REGISTRY_KEYS = registry

    fake_scanpy = types.ModuleType("scanpy")

    def _normalize_total(_adata, **kwargs):
        records["deg_normalize_kwargs"] = kwargs

    def _log1p(_adata, **kwargs):
        records["deg_log1p_kwargs"] = kwargs

    fake_scanpy.pp = types.SimpleNamespace(
        normalize_total=_normalize_total,
        log1p=_log1p,
    )

    def _rank_genes_groups(adata, **kwargs):
        records["rank_adata"] = adata
        records["deg_rank_kwargs"] = kwargs
        genes = np.asarray([str(v) for v in adata.var_names], dtype=object)
        categories = kwargs["groups"]
        adata.uns["rank_genes_groups"] = {
            "names": {str(category): genes.copy() for category in categories}
        }

    fake_scanpy.tl = types.SimpleNamespace(rank_genes_groups=_rank_genes_groups)

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "cpa", fake_cpa)
    monkeypatch.setitem(sys.modules, "cpa._utils", fake_cpa_utils)
    monkeypatch.setitem(sys.modules, "scanpy", fake_scanpy)


def test_cpa_085_defaults_seed_control_boundary_and_checkpoint_order(tmp_path, monkeypatch):
    worker = _load_worker()
    records: dict[str, object] = {}
    _install_fake_science_modules(monkeypatch, records)
    source = _verified_adata()
    genes = [str(v) for v in source.var_names]
    checkpoint = tmp_path / "cpa.state"

    # A stale smoke variable must have no effect on the production worker.
    monkeypatch.setenv("COMPOSE_CPA_SMOKE_EPOCHS", "1")
    monkeypatch.setattr(
        worker,
        "apply_response_projection",
        lambda _proj, native, _genes, *, representation: np.asarray(native)[:, :2],
    )

    predictions = worker._fit_and_predict(
        _payload(),
        source,
        {"control_mean": [0.0, 0.0]},
        genes,
        "cell_raw_counts",
        checkpoint_path=str(checkpoint),
    )

    assert set(predictions) == {("CCC", "DDD")}
    assert predictions[("CCC", "DDD")][0] == 0.0
    assert checkpoint.read_bytes().startswith(b"mock-cpa-state-dict")
    assert records["torch_seed"] == 17
    assert records["cuda_seed"] == 17
    assert records["deterministic_algorithms"] is True

    # Exact cpa-tools 0.8.5 model, trainer and CPATrainingPlan defaults are all
    # passed explicitly rather than inherited from the installed package.
    model_kwargs = records["model_kwargs"]
    assert model_kwargs["n_latent"] == 128
    assert model_kwargs["seed"] == 17
    assert records["train_kwargs"] == {
        "max_epochs": 400,
        "use_gpu": True,
        "train_size": 0.9,
        "validation_size": None,
        "batch_size": 128,
        "plan_kwargs": {
            "lr": 5e-4,
            "wd": 1e-6,
            "n_steps_pretrain_ae": None,
            "n_epochs_pretrain_ae": None,
            "n_steps_kl_warmup": None,
            "n_epochs_kl_warmup": None,
            "n_steps_adv_warmup": None,
            "n_epochs_adv_warmup": None,
            "n_epochs_mixup_warmup": None,
            "n_epochs_verbose": 10,
            "mixup_alpha": 0.0,
            "adv_steps": 3,
            "reg_adv": 1.0,
            "pen_adv": 1.0,
            "n_hidden_adv": 64,
            "n_layers_adv": 3,
            "use_batch_norm_adv": True,
            "use_layer_norm_adv": False,
            "dropout_rate_adv": 0.1,
            "adv_lr": 3e-4,
            "adv_wd": 4e-7,
            "doser_lr": 3e-4,
            "doser_wd": 4e-7,
            "step_size_lr": 45,
            "do_clip_grad": False,
            "gradient_clip_value": 3.0,
            "adv_loss": "cce",
        },
        "save_path": False,
        "check_val_every_n_epoch": 10,
        "early_stopping_patience": 10,
    }
    assert records["predict_kwargs"] == {
        "batch_size": 128,
        "n_samples": 20,
        "return_mean": True,
    }
    assert records["setup_kwargs"]["n_deg_r2"] == 10
    assert records["setup_kwargs"]["layer"] is None
    assert model_kwargs["use_rdkit_embeddings"] is False
    assert records["deg_normalize_kwargs"] == {"target_sum": 1e4}
    assert records["deg_log1p_kwargs"] == {}
    assert records["deg_rank_kwargs"] == {
        "groupby": "cov_cond",
        "groups": ["K562_AAA", "K562_AAA+BBB", "K562_BBB", "K562_CCC", "K562_DDD"],
        "reference": "K562_ctrl",
        "n_genes": 6,
        "method": "t-test",
        "use_raw": False,
        "corr_method": "benjamini-hochberg",
        "tie_correct": False,
        "rankby_abs": True,
        "pts": False,
        "layer": None,
    }

    checkpoint_obj = records["checkpoint"]
    assert checkpoint_obj["schema"] == "compose_cpa_state_dict_v1"
    assert checkpoint_obj["seed"] == 17
    assert checkpoint_obj["training_device"] == "cuda"
    assert checkpoint_obj["numeric_precision"] == "float32"
    assert checkpoint_obj["worker_config"]["n_latent"] == 128
    assert checkpoint_obj["worker_config"]["autoencoder_lr"] == 5e-4
    assert checkpoint_obj["worker_config"]["deg_method"] == "t-test"
    assert checkpoint_obj["worker_config"]["deg_reference_policy"] == "same_covariate_control"
    assert checkpoint_obj["worker_config"]["deg_mask_r2_policy"].startswith("repair_cpa_tools")
    assert checkpoint_obj["deg_mask_r2"]["schema"] == "compose_cpa_deg_mask_r2_v1"
    assert checkpoint_obj["deg_mask_r2"]["n_deg_r2"] == 10
    assert len(checkpoint_obj["deg_mask_r2"]["r2_mask_sha256"]) == 64
    assert checkpoint_obj["state_dict"] == {"decoder.weight": [1.0, 2.0]}
    assert records["events"].index("checkpoint") < records["events"].index("predict")
    assert records["events"].index("checkpoint") < records["events"].index("query_validate")

    # Only singles/calibration rows may optimize. Verified controls remain
    # reference-only; copied controls for the requested pair are prediction OOD.
    train_adata = records["model_adata"]
    n_source = source.n_obs
    source_splits = list(train_adata.obs["split"].astype(str)[:n_source])
    source_roles = list(source.obs["role"].astype(str))
    assert {split for role, split in zip(source_roles, source_splits) if role == "control"} == {
        "reference"
    }
    assert {split for role, split in zip(source_roles, source_splits) if role != "control"} <= {
        "train",
        "test",
    }
    assert set(source_splits) >= {"reference", "train", "test"}
    assert train_adata.n_obs == n_source
    aaa_rows = np.flatnonzero(train_adata.obs["condition"].astype(str).to_numpy() == "AAA")
    aaa_id = records["pert_encoder"]["AAA"]
    assert np.unique(train_adata.obsm["perts"][aaa_rows], axis=0).tolist() == [[aaa_id, 0]]
    assert np.unique(train_adata.obsm["perts_doses"][aaa_rows], axis=0).tolist() == [[1.0, 0.0]]

    split_conditions = checkpoint_obj["optimization_split"]["conditions"]
    assert split_conditions
    assert all(counts["train"] >= 2 for counts in split_conditions.values())
    assert all(
        counts["validation"] >= 1 for counts in split_conditions.values() if counts["total"] >= 3
    )

    # Requested-pair pseudo-controls never enter DEG selection; otherwise the
    # target roster could alter validation masks and early stopping.
    rank_adata = records["rank_adata"]
    expected_deg_rows = sum(split in {"reference", "train"} for split in source_splits)
    assert rank_adata.n_obs == expected_deg_rows
    assert set(rank_adata.obs_names).isdisjoint(
        {
            train_adata.obs_names[index]
            for index, split in enumerate(source_splits)
            if split == "test"
        }
    )
    assert "K562_CCC+DDD" not in set(rank_adata.obs["cov_cond"].astype(str))
    assert "K562_CCC+DDD" not in train_adata.uns["rank_genes_groups_cov"]

    # The sealed request is materialized only after checkpointing as a
    # control-expression query whose model-facing perturbation ids are the two
    # already-trained single-gene embeddings. It never expands fit categories.
    query_adata = records["query_adata"]
    assert query_adata.n_obs == 2
    assert set(query_adata.obs["condition"].astype(str)) == {"ctrl"}
    assert set(query_adata.obs["CPA_ctrl"]) == {0}
    expected_ids = [records["pert_encoder"]["CCC"], records["pert_encoder"]["DDD"]]
    assert np.unique(query_adata.obsm["perts"], axis=0).tolist() == [expected_ids]
    assert np.all(query_adata.obsm["perts_doses"] == 1.0)


def test_cpa_085_deg_mask_r2_bug_is_repaired_and_manager_verified():
    worker = _load_worker()
    genes = [f"G{i:02d}" for i in range(15)]
    adata = ad.AnnData(
        X=np.ones((3, len(genes))),
        obs=pd.DataFrame(
            {"cov_cond": ["K562_ctrl", "K562_AAA", "K562_AAA"]},
            index=["ctrl", "aaa-1", "aaa-2"],
        ),
        var=pd.DataFrame(index=genes),
    )
    ranked = genes.copy()
    adata.uns["rank_genes_groups_cov"] = {"K562_AAA": ranked}
    full_mask = np.vstack(
        [
            np.ones(len(genes), dtype=int),
            np.ones(len(genes), dtype=int),
            np.ones(len(genes), dtype=int),
        ]
    )
    registry = types.SimpleNamespace(DEG_MASK="deg_mask", DEG_MASK_R2="deg_mask_r2")
    adata.obsm[registry.DEG_MASK] = full_mask
    adata.obsm[registry.DEG_MASK_R2] = full_mask.copy()

    expected, manifest = worker._repair_cpa_085_deg_mask_r2(
        adata,
        registry,
        config=worker.CPA_WORKER_CONFIG,
    )

    assert int(expected[0].sum()) == len(genes)  # upstream all-gene control fallback
    assert int(expected[1].sum()) == int(worker.CPA_WORKER_CONFIG.n_deg_r2) == 10
    np.testing.assert_array_equal(adata.obsm[registry.DEG_MASK_R2], expected)
    assert manifest["r2_roster"]["K562_AAA"]["genes"] == genes[:10]
    assert manifest["r2_mask_sha256"] != manifest["full_mask_sha256"]

    model = types.SimpleNamespace(
        adata_manager=types.SimpleNamespace(get_from_registry=lambda key: adata.obsm[key])
    )
    worker._verify_model_deg_mask_r2(model, registry, expected)
    adata.obsm[registry.DEG_MASK_R2] = full_mask
    with pytest.raises(ValueError, match="did not bind"):
        worker._verify_model_deg_mask_r2(model, registry, expected)


def test_condition_split_preserves_two_deg_train_cells_and_requires_validation():
    worker = _load_worker()
    roles = [
        "control",
        "control",
        "singles",
        "singles",
        "combo_calibration",
        "combo_calibration",
        "combo_calibration",
    ]
    conditions = ["ctrl", "ctrl", "AAA", "AAA", "AAA+BBB", "AAA+BBB", "AAA+BBB"]
    split, manifest = worker._optimization_split(
        roles,
        conditions,
        seed=3,
        config=worker.CPA_WORKER_CONFIG,
    )
    assert split[:2] == ["reference", "reference"]
    assert split[2:4] == ["train", "train"]
    assert sorted(split[4:]) == ["test", "train", "train"]
    assert manifest["conditions"]["AAA"] == {
        "role": "singles",
        "total": 2,
        "train": 2,
        "validation": 0,
    }
    assert manifest["conditions"]["AAA+BBB"]["train"] == 2
    assert manifest["conditions"]["AAA+BBB"]["validation"] == 1
    assert manifest["schema"] == "compose_cpa_cell_split_v2"
    assert manifest["min_train_cells_per_condition"] == 2
    assert manifest["min_reference_cells"] == 2
    assert manifest["reference_count"] == 2

    with pytest.raises(ValueError, match="at least 2 are required"):
        worker._optimization_split(
            ["singles", "singles", "singles"],
            ["AAA", "BBB", "BBB"],
            seed=3,
            config=worker.CPA_WORKER_CONFIG,
        )

    with pytest.raises(ValueError, match="at least one condition with three cells"):
        worker._optimization_split(
            ["singles", "singles", "combo_calibration", "combo_calibration"],
            ["AAA", "AAA", "AAA+BBB", "AAA+BBB"],
            seed=3,
            config=worker.CPA_WORKER_CONFIG,
        )


def test_registered_split_is_valid_for_real_scanpy_control_t_test() -> None:
    """Guard the sample-count seam that fake Scanpy cannot reproduce."""
    import scanpy as sc

    worker = _load_worker()
    conditions = ["ctrl", "ctrl", "AAA", "AAA", "BBB", "BBB", "BBB"]
    roles = ["control", "control", *(["singles"] * 5)]
    split, _manifest = worker._optimization_split(
        roles,
        conditions,
        seed=5,
        config=worker.CPA_WORKER_CONFIG,
    )
    deg_positions = [index for index, value in enumerate(split) if value in {"reference", "train"}]
    rng = np.random.default_rng(7)
    norm = ad.AnnData(
        X=rng.poisson(3, size=(len(deg_positions), 8)).astype(np.float64),
        obs=pd.DataFrame(
            {"cov_cond": pd.Categorical([f"K562_{conditions[index]}" for index in deg_positions])}
        ),
    )
    sc.pp.normalize_total(norm, target_sum=worker.CPA_WORKER_CONFIG.deg_normalize_target_sum)
    sc.pp.log1p(norm)
    sc.tl.rank_genes_groups(
        norm,
        groupby="cov_cond",
        groups=["K562_AAA", "K562_BBB"],
        reference="K562_ctrl",
        n_genes=norm.n_vars,
        method="t-test",
        use_raw=False,
        corr_method="benjamini-hochberg",
        tie_correct=False,
        rankby_abs=True,
        pts=False,
        layer=None,
    )
    assert norm.uns["rank_genes_groups"]["names"].dtype.names == ("K562_AAA", "K562_BBB")


def test_requested_pair_roster_does_not_enter_fit_or_checkpoint(tmp_path, monkeypatch):
    worker = _load_worker()
    monkeypatch.setattr(
        worker,
        "apply_response_projection",
        lambda _proj, native, _genes, *, representation: np.asarray(native)[:, :2],
    )

    def _run(pair: tuple[str, str], filename: str) -> dict[str, object]:
        records: dict[str, object] = {}
        _install_fake_science_modules(monkeypatch, records)
        payload = _payload()
        payload["pair_ids"] = [list(pair)]
        source = _verified_adata()
        worker._fit_and_predict(
            payload,
            source,
            {"control_mean": [0.0, 0.0]},
            [str(value) for value in source.var_names],
            "cell_raw_counts",
            checkpoint_path=str(tmp_path / filename),
        )
        return records

    first = _run(("CCC", "DDD"), "first.state")
    second = _run(("AAA", "DDD"), "second.state")
    assert list(first["model_adata"].obs["condition"].astype(str)) == list(
        second["model_adata"].obs["condition"].astype(str)
    )
    assert first["checkpoint"] == second["checkpoint"]
    assert "CCC+DDD" not in set(first["model_adata"].obs["condition"].astype(str))
    assert "AAA+DDD" not in set(second["model_adata"].obs["condition"].astype(str))
    assert first["events"].index("checkpoint") < first["events"].index("query_validate")
    assert second["events"].index("checkpoint") < second["events"].index("query_validate")


def test_deg_preprocessing_is_invariant_to_validation_expression(tmp_path, monkeypatch):
    worker = _load_worker()
    monkeypatch.setattr(
        worker,
        "apply_response_projection",
        lambda _proj, native, _genes, *, representation: np.asarray(native)[:, :2],
    )
    base = _verified_adata()
    roles = [str(value) for value in base.obs["role"]]
    conditions = [
        "ctrl" if token == "control" else token.replace("_", "+")
        for token in base.obs["perturbation"].astype(str)
    ]
    split, _manifest = worker._optimization_split(
        roles,
        conditions,
        seed=17,
        config=worker.CPA_WORKER_CONFIG,
    )
    validation_index = split.index("test")

    def _run(source: ad.AnnData, filename: str) -> dict[str, object]:
        records: dict[str, object] = {}
        _install_fake_science_modules(monkeypatch, records)
        worker._fit_and_predict(
            _payload(),
            source,
            {"control_mean": [0.0, 0.0]},
            [str(value) for value in source.var_names],
            "cell_raw_counts",
            checkpoint_path=str(tmp_path / filename),
        )
        return records

    first = _run(base.copy(), "first-deg.state")
    mutated = base.copy()
    changed = mutated.X.tolil()
    changed[validation_index, :] = np.asarray(changed[validation_index, :].toarray()) + 10_000
    mutated.X = changed.tocsr()
    second = _run(mutated, "second-deg.state")
    assert list(first["rank_adata"].obs_names) == list(second["rank_adata"].obs_names)
    np.testing.assert_array_equal(
        first["rank_adata"].X.toarray(),
        second["rank_adata"].X.toarray(),
    )


def test_counterfactual_queries_stream_one_pair_at_a_time(tmp_path, monkeypatch):
    worker = _load_worker()
    records: dict[str, object] = {}
    _install_fake_science_modules(monkeypatch, records)
    monkeypatch.setattr(
        worker,
        "apply_response_projection",
        lambda _proj, native, _genes, *, representation: np.asarray(native)[:, :2],
    )
    payload = _payload()
    payload["pair_ids"] = [["CCC", "DDD"], ["AAA", "DDD"]]
    source = _verified_adata()
    predictions = worker._fit_and_predict(
        payload,
        source,
        {"control_mean": [0.0, 0.0]},
        [str(value) for value in source.var_names],
        "cell_raw_counts",
        checkpoint_path=str(tmp_path / "streamed.state"),
    )
    assert set(predictions) == {("CCC", "DDD"), ("AAA", "DDD")}
    assert len(records["query_adatas"]) == 2
    assert {query.n_obs for query in records["query_adatas"]} == {2}
    assert records["events"].count("checkpoint") == 1
    assert records["events"].count("predict") == 2


@pytest.mark.parametrize(
    ("representation", "bad_role", "message"),
    [
        ("raw_pseudobulk_approximation", None, "representation diverges"),
        ("cell_raw_counts", "sealed", "non-governed roles"),
    ],
)
def test_cpa_fit_fails_closed_on_representation_or_role(
    representation, bad_role, message, tmp_path, monkeypatch
):
    worker = _load_worker()
    records: dict[str, object] = {}
    _install_fake_science_modules(monkeypatch, records)
    source = _verified_adata()
    if bad_role is not None:
        source.obs.iloc[2, source.obs.columns.get_loc("role")] = bad_role
    with pytest.raises(ValueError, match=message):
        worker._fit_and_predict(
            _payload(),
            source,
            {"control_mean": [0.0, 0.0]},
            [str(v) for v in source.var_names],
            representation,
            checkpoint_path=str(tmp_path / "cpa.state"),
        )
    assert not (tmp_path / "cpa.state").exists()


def test_cpa_fit_rejects_one_cell_control_reference(tmp_path, monkeypatch) -> None:
    worker = _load_worker()
    records: dict[str, object] = {}
    _install_fake_science_modules(monkeypatch, records)
    source = _verified_adata()[1:].copy()
    with pytest.raises(ValueError, match="at least 2 control cells"):
        worker._fit_and_predict(
            _payload(),
            source,
            {"control_mean": [0.0, 0.0]},
            [str(value) for value in source.var_names],
            "cell_raw_counts",
            checkpoint_path=str(tmp_path / "one-control.state"),
        )
    assert not (tmp_path / "one-control.state").exists()


def test_main_passes_stable_verified_snapshot_and_hashes_model_checkpoint(tmp_path, monkeypatch):
    worker = _load_worker()
    adapter_version = "cpa-adapter-test-v1"
    identity = types.SimpleNamespace(
        adapter_version=adapter_version,
        adapter_sha256="a" * 64,
        config_sha256="b" * 64,
        resource_sha256="c" * 64,
        environment_lock_sha256="d" * 64,
        worker_executable_sha256="e" * 64,
        worker_config=worker._registered_worker_config(adapter_version),
    )
    monkeypatch.setattr(worker, "load_verified_worker_identity", lambda *, method: identity)
    verified = _verified_adata()
    fit_role = {
        "path": str(tmp_path / "fit-role.h5ad"),
        "sha256": "sha256:" + "1" * 64,
        "content_manifest_sha256": "sha256:" + "2" * 64,
        "raw_data_sha256": "raw",
        "pair_manifest_sha256": "pairs",
        "eligibility_hash": "eligibility",
        "row_identity_sha256": "sha256:" + "3" * 64,
        "gene_order_sha256": canonical_gene_order_sha256(verified.var_names),
        "n_cells": verified.n_obs,
        "n_genes": verified.n_vars,
        "role_counts": {"control": 2, "singles": 9, "combo_calibration": 2},
    }
    payload = {
        "seed": 17,
        "response_dim": 2,
        "pair_ids": [["CCC", "DDD"]],
        "calibration_pair_ids": [["AAA", "BBB"]],
        "single_gene_ids": ["AAA", "BBB", "CCC", "DDD"],
        "fit_role_artifact": fit_role,
        "response_projection": {
            "gene_order_sha256": canonical_gene_order_sha256(verified.var_names),
            "control_mean": [0.0, 0.0],
        },
    }
    monkeypatch.setattr(worker, "read_payload", lambda _path, **_kwargs: payload)
    monkeypatch.setattr(worker, "canonical_payload_sha256", lambda _payload: "f" * 64)
    monkeypatch.setattr(worker, "validate_fit_role_artifact", lambda *_args, **_kwargs: None)

    reads: list[object] = []

    def _read_verified(path, *, spec, approved_root):
        reads.append((path, spec, approved_root))
        return verified

    monkeypatch.setattr(worker, "read_verified_fit_role_artifact", _read_verified)
    fit_inputs: list[object] = []

    def _fit(payload_arg, adata_arg, _proj, _genes, representation, *, checkpoint_path):
        fit_inputs.append((payload_arg, adata_arg, representation, checkpoint_path))
        Path(checkpoint_path).write_bytes(b"actual-model-state")
        return {("CCC", "DDD"): np.array([0.2, 0.3])}

    monkeypatch.setattr(worker, "_fit_and_predict", _fit)
    emitted: list[object] = []
    monkeypatch.setattr(
        worker,
        "write_predictions",
        lambda path, preds, *, execution_manifest: emitted.append(
            (path, preds, execution_manifest)
        ),
    )

    out = tmp_path / "predictions"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_WORKER_PATH),
            "--in",
            str(tmp_path / "work"),
            "--out",
            str(out),
            "--approved-root",
            str(tmp_path),
            "--prediction-representation",
            "cell_raw_counts",
        ],
    )
    worker.main()

    assert len(reads) == 1
    assert fit_inputs[0][1] is verified
    assert fit_inputs[0][2] == "cell_raw_counts"
    assert fit_inputs[0][3] == str(out) + ".checkpoint"
    assert (
        emitted[0][2]["checkpoint_sha256"]
        == __import__("hashlib").sha256(b"actual-model-state").hexdigest()
    )
    assert emitted[0][2]["worker_sha256"] == "e" * 64
