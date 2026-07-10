# scripts/baselines/cpa_worker.py
"""Real CPA deep-baseline worker with a frozen fit contract.

COMPLETE contract surface for the fit-role-only subprocess protocol: reads +
validates the fit-role artifact (the SEALED requested pairs enter ONLY as
``sealed_pair_ids`` to the leakage guard — never as fit rows), delegates the
model fit + prediction to :func:`_fit_and_predict`, and returns the
``{predictions, execution_manifest}`` envelope with real digests.

``_fit_and_predict`` is import-guarded: on a host without the pinned ``cpa``
package it raises :class:`WorkerUnavailable`; in the registered environment it
fits CPA from the verified fit-role snapshot and predicts each requested pair.
This worker opens no seal and reads no sealed outcome. Exact pin: CPA
``cpa-tools==0.8.5``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random

import numpy as np

from alive.compose.baseline_subprocess import (
    canonical_payload_sha256,
    read_payload,
    write_predictions,
)
from alive.compose.fit_role import (
    FitRoleArtifactSpec,
    apply_response_projection,
    canonical_gene_order_sha256,
    read_verified_fit_role_artifact,
    validate_fit_role_artifact,
)
from alive.compose.worker_identity import (
    VerifiedWorkerIdentity,
    load_verified_worker_identity,
    require_distribution_version,
    require_exact_worker_config,
    require_module_from_environment,
)


class CPAWorkerConfig:
    """Code-registered CPA 0.8.5 optimization contract.

    The worker-script digest binds this object into the execution identity.  In
    particular, control expression is reference/counterfactual substrate only:
    it is present in the verified artifact but never receives a ``train`` or
    ``test`` (validation) split, so the optimizer cannot consume control outcome
    rows contrary to the frozen ``{singles, combo_calibration}`` training-role
    contract.

    The cpa-tools 0.8.5 data-dependent epoch formula, validation interval, and
    patience are represented explicitly and passed explicitly at runtime.  This
    preserves the upstream values while binding them into the registered config.
    """

    __slots__ = ()

    schema = "compose_cpa_worker_config_v1"
    package = "cpa-tools"
    package_version = "0.8.5"
    device_policy = "cuda_required"
    numeric_precision = "float32"
    deterministic_algorithms = True
    module_origin_policy = "regular_non_symlink_under_sys_prefix"
    cublas_workspace_config = ":4096:8"
    python_hash_seed_source = "payload_seed"
    n_latent = 128
    recon_loss = "nb"
    doser_type = "logsigm"
    n_hidden_encoder = 256
    n_layers_encoder = 3
    n_hidden_decoder = 256
    n_layers_decoder = 3
    n_hidden_doser = 128
    n_layers_doser = 2
    use_batch_norm_encoder = True
    use_layer_norm_encoder = False
    use_batch_norm_decoder = True
    use_layer_norm_decoder = False
    dropout_rate_encoder = 0.0
    dropout_rate_decoder = 0.0
    variational = False
    batch_size = 128
    prediction_batch_size = 128
    max_epochs_policy = "min(round((20000/n_fit_rows)*400),400)"
    check_val_every_n_epoch = 10
    early_stopping_patience = 10
    library_save_after_train = False
    train_size = 0.9
    validation_size = None
    optimizer = "Adam"
    autoencoder_lr = 5e-4
    autoencoder_weight_decay = 1e-6
    n_steps_pretrain_ae = None
    n_epochs_pretrain_ae = None
    n_steps_kl_warmup = None
    n_epochs_kl_warmup = None
    n_steps_adv_warmup = None
    n_epochs_adv_warmup = None
    n_epochs_mixup_warmup = None
    n_epochs_verbose = 10
    mixup_alpha = 0.0
    adv_steps = 3
    reg_adv = 1.0
    pen_adv = 1.0
    n_hidden_adv = 64
    n_layers_adv = 3
    use_batch_norm_adv = True
    use_layer_norm_adv = False
    dropout_rate_adv = 0.1
    adv_lr = 3e-4
    adv_weight_decay = 4e-7
    doser_lr = 3e-4
    doser_weight_decay = 4e-7
    lr_scheduler = "StepLR"
    lr_scheduler_step_size = 45
    lr_scheduler_gamma = 0.9
    do_clip_grad = False
    gradient_clip_value = 3.0
    gradient_clip_algorithm = "norm"
    adversarial_loss = "cce"
    focal_gamma = 2.0
    model_selection_policy = "upstream_cpa_metric_callbacks"
    max_comb_len = 2
    n_deg_r2 = 10
    deg_mask_r2_policy = "repair_cpa_tools_0_8_5_cov_cond_map_bug_then_verify_manager"
    deg_input_roles = ("reference", "train")
    min_deg_train_cells_per_condition = 2
    min_deg_reference_cells = 2
    deg_normalize_target_sum = 1e4
    deg_transform = "log1p"
    deg_groupby = "cov_cond"
    deg_groups_policy = "all_noncontrol_conditions"
    deg_reference_policy = "same_covariate_control"
    deg_method = "t-test"
    deg_n_genes = 50
    deg_use_raw = False
    deg_rankby_abs = True
    deg_corr_method = "benjamini-hochberg"
    deg_tie_correct = False
    deg_pts = False
    deg_layer = None
    layer = None
    batch_key = None
    smiles_key = None
    use_rdkit_embeddings = False
    covariate = "K562"
    control_token = "control"
    combo_sep = "_"
    condition_encoding = "control=ctrl;single=gene;combo=gene+gene"
    optimization_roles = ("singles", "combo_calibration")
    control_optimization = "reference_only"
    reference_split = "reference"
    train_split = "train"
    validation_split = "test"
    counterfactual_split = "ood"
    validation_fraction = 0.1
    split_policy = "deterministic_within_condition_cell_level"
    counterfactual_query_policy = "postfit_registered_control_query_with_perturbation_override"
    request_categories_in_fit = False
    query_uses_trained_single_embeddings_only = True
    query_dose = 1.0
    prediction_n_samples = 20
    prediction_return_mean = True
    query_chunk_size_pairs = 1
    streaming_response_projection = True
    negative_prediction_policy = "clip_zero_before_response_projection"
    prediction_representation = "cell_raw_counts"

    def to_dict(self) -> dict[str, object]:
        """Return the canonical checkpoint representation of this contract."""
        keys = (
            "schema",
            "package",
            "package_version",
            "device_policy",
            "numeric_precision",
            "deterministic_algorithms",
            "module_origin_policy",
            "cublas_workspace_config",
            "python_hash_seed_source",
            "n_latent",
            "recon_loss",
            "doser_type",
            "n_hidden_encoder",
            "n_layers_encoder",
            "n_hidden_decoder",
            "n_layers_decoder",
            "n_hidden_doser",
            "n_layers_doser",
            "use_batch_norm_encoder",
            "use_layer_norm_encoder",
            "use_batch_norm_decoder",
            "use_layer_norm_decoder",
            "dropout_rate_encoder",
            "dropout_rate_decoder",
            "variational",
            "batch_size",
            "prediction_batch_size",
            "max_epochs_policy",
            "check_val_every_n_epoch",
            "early_stopping_patience",
            "library_save_after_train",
            "train_size",
            "validation_size",
            "optimizer",
            "autoencoder_lr",
            "autoencoder_weight_decay",
            "n_steps_pretrain_ae",
            "n_epochs_pretrain_ae",
            "n_steps_kl_warmup",
            "n_epochs_kl_warmup",
            "n_steps_adv_warmup",
            "n_epochs_adv_warmup",
            "n_epochs_mixup_warmup",
            "n_epochs_verbose",
            "mixup_alpha",
            "adv_steps",
            "reg_adv",
            "pen_adv",
            "n_hidden_adv",
            "n_layers_adv",
            "use_batch_norm_adv",
            "use_layer_norm_adv",
            "dropout_rate_adv",
            "adv_lr",
            "adv_weight_decay",
            "doser_lr",
            "doser_weight_decay",
            "lr_scheduler",
            "lr_scheduler_step_size",
            "lr_scheduler_gamma",
            "do_clip_grad",
            "gradient_clip_value",
            "gradient_clip_algorithm",
            "adversarial_loss",
            "focal_gamma",
            "model_selection_policy",
            "max_comb_len",
            "n_deg_r2",
            "deg_mask_r2_policy",
            "deg_input_roles",
            "min_deg_train_cells_per_condition",
            "min_deg_reference_cells",
            "deg_normalize_target_sum",
            "deg_transform",
            "deg_groupby",
            "deg_groups_policy",
            "deg_reference_policy",
            "deg_method",
            "deg_n_genes",
            "deg_use_raw",
            "deg_rankby_abs",
            "deg_corr_method",
            "deg_tie_correct",
            "deg_pts",
            "deg_layer",
            "layer",
            "batch_key",
            "smiles_key",
            "use_rdkit_embeddings",
            "covariate",
            "control_token",
            "combo_sep",
            "condition_encoding",
            "optimization_roles",
            "control_optimization",
            "reference_split",
            "train_split",
            "validation_split",
            "counterfactual_split",
            "validation_fraction",
            "split_policy",
            "counterfactual_query_policy",
            "request_categories_in_fit",
            "query_uses_trained_single_embeddings_only",
            "query_dose",
            "prediction_n_samples",
            "prediction_return_mean",
            "query_chunk_size_pairs",
            "streaming_response_projection",
            "negative_prediction_policy",
            "prediction_representation",
        )
        return {key: getattr(self, key) for key in keys}


CPA_WORKER_CONFIG = CPAWorkerConfig()


def _registered_worker_config(adapter_version: str) -> dict[str, object]:
    """Return the exact JSON config this worker implementation accepts."""
    training = CPA_WORKER_CONFIG.to_dict()
    training["optimization_roles"] = list(CPA_WORKER_CONFIG.optimization_roles)
    training["deg_input_roles"] = list(CPA_WORKER_CONFIG.deg_input_roles)
    return {
        "schema": "compose_deep_worker_config_v1",
        "method": "cpa",
        "adapter_version": adapter_version,
        "prediction_representation": CPA_WORKER_CONFIG.prediction_representation,
        "training": training,
    }


def _verify_runtime_identity(representation: str) -> VerifiedWorkerIdentity:
    """Re-hash identity files and bind their config to this exact fit body."""
    identity = load_verified_worker_identity(method="cpa")
    require_exact_worker_config(
        identity,
        expected=_registered_worker_config(identity.adapter_version),
    )
    _validate_worker_config(CPA_WORKER_CONFIG, representation)
    return identity


class WorkerUnavailable(RuntimeError):
    """Raised when the pinned ``cpa`` backend is absent."""


def _validate_worker_config(config: CPAWorkerConfig, representation: str) -> None:
    """Fail closed if the code-registered scientific contract is inconsistent."""
    if config.package_version != "0.8.5":
        raise ValueError("CPA worker supports exactly cpa-tools 0.8.5")
    if config.device_policy != "cuda_required" or config.numeric_precision != "float32":
        raise ValueError("CPA device/precision policy diverges from registration")
    if config.n_latent != 128 or config.batch_size != 128:
        raise ValueError("CPA worker defaults diverge from cpa-tools 0.8.5")
    if config.recon_loss != "nb" or config.doser_type != "logsigm":
        raise ValueError("CPA likelihood/doser defaults diverge from cpa-tools 0.8.5")
    if config.condition_encoding != "control=ctrl;single=gene;combo=gene+gene":
        raise ValueError("CPA condition encoding diverges from registration")
    if config.library_save_after_train is not False:
        raise ValueError("CPA library-side checkpointing must remain disabled")
    if (
        config.optimizer != "Adam"
        or config.autoencoder_lr != 5e-4
        or config.autoencoder_weight_decay != 1e-6
        or config.adv_lr != 3e-4
        or config.adv_weight_decay != 4e-7
        or config.doser_lr != 3e-4
        or config.doser_weight_decay != 4e-7
    ):
        raise ValueError("CPA optimizer contract diverges from cpa-tools 0.8.5")
    if (
        config.adv_steps != 3
        or config.reg_adv != 1.0
        or config.pen_adv != 1.0
        or config.adversarial_loss != "cce"
        or config.mixup_alpha != 0.0
    ):
        raise ValueError("CPA adversary training plan diverges from cpa-tools 0.8.5")
    if (
        config.lr_scheduler != "StepLR"
        or config.lr_scheduler_step_size != 45
        or config.lr_scheduler_gamma != 0.9
        or config.do_clip_grad is not False
        or config.gradient_clip_value != 3.0
        or config.gradient_clip_algorithm != "norm"
    ):
        raise ValueError("CPA scheduler/clipping contract diverges from cpa-tools 0.8.5")
    if (
        config.deg_input_roles != ("reference", "train")
        or config.min_deg_train_cells_per_condition != 2
        or config.min_deg_reference_cells != 2
        or config.deg_normalize_target_sum != 1e4
        or config.deg_transform != "log1p"
        or config.deg_groups_policy != "all_noncontrol_conditions"
        or config.deg_reference_policy != "same_covariate_control"
        or config.deg_method != "t-test"
        or config.deg_n_genes != 50
        or config.n_deg_r2 != 10
        or config.deg_mask_r2_policy
        != "repair_cpa_tools_0_8_5_cov_cond_map_bug_then_verify_manager"
        or config.deg_rankby_abs is not True
    ):
        raise ValueError("CPA DEG preprocessing contract diverges from registration")
    if config.optimization_roles != ("singles", "combo_calibration"):
        raise ValueError("CPA optimization roles must be exactly singles + combo_calibration")
    if config.control_optimization != "reference_only":
        raise ValueError("CPA control rows must remain reference-only")
    if not 0.0 < config.validation_fraction < 1.0:
        raise ValueError("CPA validation_fraction must lie strictly between zero and one")
    if config.split_policy != "deterministic_within_condition_cell_level":
        raise ValueError("CPA split policy is not the registered within-condition policy")
    if config.request_categories_in_fit is not False:
        raise ValueError("CPA requested categories must remain absent from fit")
    if config.query_uses_trained_single_embeddings_only is not True or config.query_dose != 1.0:
        raise ValueError("CPA counterfactual query contract diverges from registration")
    if config.negative_prediction_policy != "clip_zero_before_response_projection":
        raise ValueError("CPA negative prediction policy diverges from registration")
    if config.query_chunk_size_pairs != 1 or config.streaming_response_projection is not True:
        raise ValueError("CPA streaming query policy diverges from registration")
    if representation != config.prediction_representation:
        raise ValueError(
            "CPA prediction representation diverges from the registered cell_raw_counts contract"
        )


def _seed_everything(seed: int, torch_module) -> None:
    """Seed Python, NumPy, torch and CUDA deterministically before any split/fit."""
    if seed < 0:
        raise ValueError("CPA seed must be non-negative")
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != CPA_WORKER_CONFIG.cublas_workspace_config:
        raise WorkerUnavailable("CPA CUBLAS workspace configuration is not registered")
    if os.environ.get("PYTHONHASHSEED") != str(seed):
        raise WorkerUnavailable("CPA PYTHONHASHSEED does not match the payload seed")
    random.seed(seed)
    np.random.seed(seed)
    torch_module.manual_seed(seed)
    cuda = getattr(torch_module, "cuda", None)
    if cuda is None or not callable(getattr(cuda, "is_available", None)) or not cuda.is_available():
        raise WorkerUnavailable("CPA registered execution requires CUDA")
    cuda.manual_seed_all(seed)
    deterministic = getattr(torch_module, "use_deterministic_algorithms", None)
    if not callable(deterministic):
        raise WorkerUnavailable("CPA runtime lacks deterministic-algorithm enforcement")
    deterministic(True)
    cudnn = getattr(getattr(torch_module, "backends", None), "cudnn", None)
    if cudnn is not None:
        cudnn.deterministic = True
        cudnn.benchmark = False


def _training_plan_kwargs(config: CPAWorkerConfig) -> dict[str, object]:
    """Return every configurable CPATrainingPlan 0.8.5 default explicitly."""
    return {
        "lr": config.autoencoder_lr,
        "wd": config.autoencoder_weight_decay,
        "n_steps_pretrain_ae": config.n_steps_pretrain_ae,
        "n_epochs_pretrain_ae": config.n_epochs_pretrain_ae,
        "n_steps_kl_warmup": config.n_steps_kl_warmup,
        "n_epochs_kl_warmup": config.n_epochs_kl_warmup,
        "n_steps_adv_warmup": config.n_steps_adv_warmup,
        "n_epochs_adv_warmup": config.n_epochs_adv_warmup,
        "n_epochs_mixup_warmup": config.n_epochs_mixup_warmup,
        "n_epochs_verbose": config.n_epochs_verbose,
        "mixup_alpha": config.mixup_alpha,
        "adv_steps": config.adv_steps,
        "reg_adv": config.reg_adv,
        "pen_adv": config.pen_adv,
        "n_hidden_adv": config.n_hidden_adv,
        "n_layers_adv": config.n_layers_adv,
        "use_batch_norm_adv": config.use_batch_norm_adv,
        "use_layer_norm_adv": config.use_layer_norm_adv,
        "dropout_rate_adv": config.dropout_rate_adv,
        "adv_lr": config.adv_lr,
        "adv_wd": config.adv_weight_decay,
        "doser_lr": config.doser_lr,
        "doser_wd": config.doser_weight_decay,
        "step_size_lr": config.lr_scheduler_step_size,
        "do_clip_grad": config.do_clip_grad,
        "gradient_clip_value": config.gradient_clip_value,
        "adv_loss": config.adversarial_loss,
    }


def _optimization_split(
    roles: list[str],
    conditions: list[str],
    *,
    seed: int,
    config: CPAWorkerConfig,
) -> tuple[list[str], dict[str, object]]:
    """Assign deterministic within-condition train/validation rows.

    Control rows remain ``reference``. Every optimization condition retains at
    least two train rows because the registered control-referenced t-test cannot
    estimate a condition from one cell. Two-cell conditions are train-only;
    conditions with at least three cells contribute a deterministic validation
    subset while still retaining two train rows. At least one validation row
    overall is required.
    """
    if len(roles) != len(conditions):
        raise ValueError("CPA role and condition vectors must have equal length")
    allowed = set(config.optimization_roles) | {"control"}
    unexpected = set(roles) - allowed
    if unexpected:
        raise ValueError(f"CPA verified artifact contains non-governed roles: {sorted(unexpected)}")
    optimization_idx = [i for i, role in enumerate(roles) if role in config.optimization_roles]
    if len(optimization_idx) < 2:
        raise ValueError("CPA requires at least two non-control optimization rows")

    by_condition: dict[str, list[int]] = {}
    role_by_condition: dict[str, str] = {}
    for index in optimization_idx:
        condition = conditions[index]
        if not isinstance(condition, str) or not condition:
            raise ValueError("CPA optimization conditions must be non-empty strings")
        role = roles[index]
        prior_role = role_by_condition.setdefault(condition, role)
        if prior_role != role:
            raise ValueError(f"CPA condition {condition!r} appears under multiple fit roles")
        by_condition.setdefault(condition, []).append(index)

    rng = np.random.default_rng(seed)
    split = [config.reference_split] * len(roles)
    condition_counts: dict[str, dict[str, object]] = {}
    total_validation = 0
    for condition in sorted(by_condition):
        indices = by_condition[condition]
        if len(indices) < config.min_deg_train_cells_per_condition:
            raise ValueError(
                f"CPA condition {condition!r} has {len(indices)} cell(s); "
                f"at least {config.min_deg_train_cells_per_condition} are required "
                "for the registered control-referenced t-test"
            )
        order = [indices[i] for i in rng.permutation(len(indices))]
        n_validation = 0
        if len(order) > config.min_deg_train_cells_per_condition:
            n_validation = max(1, int(round(len(order) * config.validation_fraction)))
            n_validation = min(
                n_validation,
                len(order) - config.min_deg_train_cells_per_condition,
            )
        validation = set(order[:n_validation])
        for index in indices:
            split[index] = config.validation_split if index in validation else config.train_split
        n_train = len(indices) - n_validation
        if n_train < config.min_deg_train_cells_per_condition:
            raise ValueError(f"CPA condition {condition!r} has too few optimization train rows")
        total_validation += n_validation
        condition_counts[condition] = {
            "role": role_by_condition[condition],
            "total": len(indices),
            "train": n_train,
            "validation": n_validation,
        }
    if total_validation < 1:
        raise ValueError(
            "CPA requires at least one condition with three cells for validation "
            "while retaining two train rows for the registered t-test"
        )
    manifest: dict[str, object] = {
        "schema": "compose_cpa_cell_split_v2",
        "seed": int(seed),
        "validation_fraction": config.validation_fraction,
        "min_train_cells_per_condition": config.min_deg_train_cells_per_condition,
        "min_reference_cells": config.min_deg_reference_cells,
        "reference_count": sum(role == "control" for role in roles),
        "conditions": condition_counts,
        "control_in_optimization": False,
    }
    return split, manifest


def _binary_mask(value: object, *, shape: tuple[int, int], field: str) -> np.ndarray:
    """Return a validated C-contiguous uint8 mask with exactly ``shape``."""
    observed = np.asarray(value)
    if observed.shape != shape:
        raise ValueError(f"CPA {field} has shape {observed.shape}, expected {shape}")
    if not np.isfinite(observed).all() or not np.isin(observed, (0, 1)).all():
        raise ValueError(f"CPA {field} must be a finite binary matrix")
    return np.ascontiguousarray(observed, dtype=np.uint8)


def _mask_sha256(mask: np.ndarray) -> str:
    """Hash a binary mask together with its exact two-dimensional shape."""
    if mask.ndim != 2:
        raise ValueError("CPA mask digest requires a two-dimensional matrix")
    header = f"{mask.shape[0]}x{mask.shape[1]}\0".encode("ascii")
    return hashlib.sha256(header + np.ascontiguousarray(mask, dtype=np.uint8).tobytes()).hexdigest()


def _repair_cpa_085_deg_mask_r2(
    train_adata,
    registry,
    *,
    config: CPAWorkerConfig,
) -> tuple[np.ndarray, dict[str, object]]:
    """Repair and bind cpa-tools 0.8.5's ``DEG_MASK_R2`` construction bug.

    Upstream 0.8.5 builds both ``cov_cond_map`` (the full top-50 mask) and
    ``cov_cond_map_r2`` (the registered top-10 mask), but accidentally constructs
    ``mask_r2`` from the former.  That changes the validation ``cpa_metric`` and
    therefore best-state selection.  We accept only the two known upstream
    states (buggy full mask or already-correct top-N mask), replace the registered
    array with the exact top-N mask, and return an auditable manifest plus the
    expected bytes for a post-model AnnDataManager check.
    """
    if config.package_version != "0.8.5" or config.n_deg_r2 != 10:
        raise ValueError("CPA DEG-mask repair is defined only for the registered 0.8.5/top-10 pin")
    full_key = getattr(registry, "DEG_MASK", None)
    r2_key = getattr(registry, "DEG_MASK_R2", None)
    if (full_key, r2_key) != ("deg_mask", "deg_mask_r2"):
        raise ValueError("CPA 0.8.5 DEG registry keys diverge from the registered repair")
    rankings = train_adata.uns.get("rank_genes_groups_cov")
    if not isinstance(rankings, dict) or not rankings:
        raise ValueError("CPA DEG-mask repair requires the registered DEG ranking map")

    genes = [str(value) for value in train_adata.var_names]
    if len(genes) != len(set(genes)) or not genes:
        raise ValueError("CPA DEG-mask repair requires unique non-empty genes")
    gene_array = np.asarray(genes, dtype=object)
    gene_set = set(genes)
    categories = [str(value) for value in train_adata.obs[config.deg_groupby]]
    shape = (train_adata.n_obs, train_adata.n_vars)
    expected_full_rows: list[np.ndarray] = []
    expected_r2_rows: list[np.ndarray] = []
    r2_roster: dict[str, object] = {}
    for category in categories:
        raw_ranked = rankings.get(category)
        if raw_ranked is None:
            full = np.ones(train_adata.n_vars, dtype=np.uint8)
            r2 = full.copy()
            prior = r2_roster.setdefault(category, {"mode": "all_genes"})
            if prior != {"mode": "all_genes"}:
                raise ValueError("CPA DEG-mask category has inconsistent ranking semantics")
        else:
            if not isinstance(raw_ranked, (list, tuple, np.ndarray)):
                raise ValueError(f"CPA DEG ranking for {category!r} is not a sequence")
            ranked = [str(value) for value in raw_ranked]
            max_ranked = min(config.deg_n_genes, train_adata.n_vars)
            if not ranked or len(ranked) > max_ranked or len(ranked) != len(set(ranked)):
                raise ValueError(f"CPA DEG ranking for {category!r} has invalid cardinality")
            if any(gene not in gene_set for gene in ranked):
                raise ValueError(f"CPA DEG ranking for {category!r} contains an unknown gene")
            r2_genes = ranked[: min(config.n_deg_r2, len(ranked))]
            full = np.isin(gene_array, ranked).astype(np.uint8)
            r2 = np.isin(gene_array, r2_genes).astype(np.uint8)
            prior = r2_roster.setdefault(category, {"mode": "ranked_top_n", "genes": r2_genes})
            if prior != {"mode": "ranked_top_n", "genes": r2_genes}:
                raise ValueError("CPA DEG-mask category has inconsistent ranked genes")
        expected_full_rows.append(full)
        expected_r2_rows.append(r2)

    expected_full = np.ascontiguousarray(np.vstack(expected_full_rows), dtype=np.uint8)
    expected_r2 = np.ascontiguousarray(np.vstack(expected_r2_rows), dtype=np.uint8)
    observed_full = _binary_mask(train_adata.obsm[full_key], shape=shape, field=full_key)
    observed_r2 = _binary_mask(train_adata.obsm[r2_key], shape=shape, field=r2_key)
    if not np.array_equal(observed_full, expected_full):
        raise ValueError("CPA upstream full DEG mask differs from the registered ranking map")
    if not (np.array_equal(observed_r2, expected_full) or np.array_equal(observed_r2, expected_r2)):
        raise ValueError("CPA upstream R2 DEG mask is neither the known 0.8.5 bug nor top-N")

    train_adata.obsm[r2_key] = expected_r2.astype(int, copy=False)
    repaired = _binary_mask(train_adata.obsm[r2_key], shape=shape, field=r2_key)
    if not np.array_equal(repaired, expected_r2):
        raise ValueError("CPA top-N R2 DEG mask did not survive AnnData assignment")
    manifest: dict[str, object] = {
        "schema": "compose_cpa_deg_mask_r2_v1",
        "package_version": config.package_version,
        "policy": config.deg_mask_r2_policy,
        "full_mask_key": full_key,
        "r2_mask_key": r2_key,
        "n_deg_r2": config.n_deg_r2,
        "shape": list(shape),
        "gene_order_sha256": canonical_gene_order_sha256(genes),
        "row_category_order_sha256": hashlib.sha256(
            json.dumps(categories, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "full_mask_sha256": _mask_sha256(expected_full),
        "r2_mask_sha256": _mask_sha256(expected_r2),
        "r2_roster": {key: r2_roster[key] for key in sorted(r2_roster)},
    }
    return expected_r2, manifest


def _verify_model_deg_mask_r2(model, registry, expected: np.ndarray) -> None:
    """Prove the initialized CPA manager reads the repaired top-N mask bytes."""
    manager = getattr(model, "adata_manager", None)
    getter = getattr(manager, "get_from_registry", None)
    if not callable(getter):
        raise ValueError("CPA model lacks an inspectable AnnDataManager registry")
    observed = _binary_mask(
        getter(registry.DEG_MASK_R2),
        shape=expected.shape,
        field="model DEG_MASK_R2",
    )
    if not np.array_equal(observed, expected):
        raise ValueError("CPA model manager did not bind the repaired top-N R2 DEG mask")


def _write_model_checkpoint(
    model,
    checkpoint_path: str,
    *,
    seed: int,
    config: CPAWorkerConfig,
    split_manifest: dict[str, object],
    deg_mask_manifest: dict[str, object],
    torch_module,
) -> None:
    """Write-once the actual trained CPA module state before any prediction."""
    state_dict = {
        str(key): value.detach().cpu()
        if callable(getattr(value, "detach", None)) and callable(getattr(value, "cpu", None))
        else value
        for key, value in model.module.state_dict().items()
    }
    checkpoint = {
        "schema": "compose_cpa_state_dict_v1",
        "seed": seed,
        "training_device": "cuda",
        "numeric_precision": config.numeric_precision,
        "worker_config": config.to_dict(),
        "optimization_split": split_manifest,
        "deg_mask_r2": deg_mask_manifest,
        "state_dict": state_dict,
    }
    with open(checkpoint_path, "xb") as fh:
        torch_module.save(checkpoint, fh)
        fh.flush()
        os.fsync(fh.fileno())


def _fit_and_predict(
    payload: dict,
    adata,
    proj: dict,
    gene_order: list[str],
    representation: str,
    *,
    checkpoint_path: str | None = None,
) -> dict[tuple[str, str], np.ndarray]:
    """Fit real CPA and predict each requested pair's response-space delta.

    The implementation uses only fit roles (control + singles +
    combo_calibration); sealed requested pairs are never fit rows. It must:

    1. consume the already-verified, stable-descriptor AnnData snapshot supplied
       by :func:`main` (the fit body never reopens a pathname);
    2. fit CPA on those rows (recommended pin: ``cpa-tools==0.8.5``);
    3. predict each ``payload["pair_ids"]`` pair's native full-gene expression;
    4. map native -> response space with ``apply_response_projection`` honoring
       ``representation`` (``raw_pseudobulk_approximation`` ->
       ``native.mean(axis=0, keepdims=True)``; ``cell_*`` -> ``native``), then
       ``delta = mean(z) - control_mean``;
    5. write the actual trained ``model.module.state_dict()`` checkpoint before
       prediction, then return ``{pair: delta[:response_dim]}``.

    Returns
    -------
    dict
        Mapping from each requested canonical pair to its length-``response_dim``
        response-space prediction vector.

    Raises
    ------
    WorkerUnavailable
        If the pinned ``cpa`` package is not installed.
    ValueError
        If the registered CPA configuration, representation, roles, gene order,
        seed, or checkpoint path is invalid.
    """
    try:
        import cpa
        import torch  # noqa: F401
        from cpa._utils import CPA_REGISTRY_KEYS
    except ImportError as exc:
        raise WorkerUnavailable("pinned cpa-tools backend is not installed") from exc
    require_distribution_version(
        distribution=CPA_WORKER_CONFIG.package,
        expected=CPA_WORKER_CONFIG.package_version,
    )
    require_module_from_environment(cpa, expected_name="cpa")

    import anndata as ad
    import pandas as pd
    import scanpy as sc
    from scipy import sparse

    config = CPA_WORKER_CONFIG
    _validate_worker_config(config, representation)
    if checkpoint_path is None:
        raise ValueError("CPA fit requires a write-once checkpoint_path")
    seed = int(payload["seed"])
    _seed_everything(seed, torch)

    # 1. consume the already leakage- and byte-identity-verified in-memory
    #    snapshot (raw counts; control + singles + combo_calibration only).
    art_genes = [str(v) for v in adata.var_names]
    if art_genes != list(gene_order):
        raise ValueError("fit-role artifact gene order diverges from the observed gene order")
    tokens = [str(p) for p in adata.obs["perturbation"]]
    roles = [str(r) for r in adata.obs["role"]]
    if len(tokens) != len(roles):
        raise ValueError("fit-role perturbation/role columns have unequal lengths")

    def _condition(token: str) -> str:
        if token == config.control_token:
            return "ctrl"
        if config.combo_sep in token:
            a, b = token.split(config.combo_sep, 1)
            return f"{a}+{b}"
        return token

    def _decorate(obj) -> None:
        """Attach the CPA obs covariates (condition, dose, covariate, cov_cond)."""
        cond = obj.obs["condition"].astype(str)
        obj.obs["dose_value"] = ["+".join(["1.0"] * len(c.split("+"))) for c in cond]
        obj.obs["cov"] = config.covariate
        obj.obs["cov_cond"] = config.covariate + "_" + cond
        for key in ("condition", "cov", "cov_cond"):
            obj.obs[key] = obj.obs[key].astype("category")

    # 2. Build CPA's fit AnnData from the verified fit-role rows only. Requested
    #    categories are deliberately absent until after training so the adversary,
    #    condition weights, epoch cap, validation metric, and checkpoint cannot
    #    depend on the sealed request roster.
    counts = sparse.csr_matrix(adata.X, dtype="float32")
    base_conditions = [_condition(t) for t in tokens]
    base_index = [str(s) for s in adata.obs_names]

    ctrl_positions = [i for i, role in enumerate(roles) if role == "control"]
    if len(ctrl_positions) < config.min_deg_reference_cells:
        raise ValueError(
            "CPA counterfactual/DEG reference requires at least "
            f"{config.min_deg_reference_cells} control cells"
        )
    if any(tokens[i] != config.control_token for i in ctrl_positions):
        raise ValueError("CPA control role/token mismatch")
    # Only singles + combo_calibration rows enter optimization. Controls remain
    # explicit reference rows and are used solely as counterfactual substrate.
    base_split, split_manifest = _optimization_split(
        roles,
        base_conditions,
        seed=seed,
        config=config,
    )

    train_adata = ad.AnnData(
        X=counts.copy(),
        obs=pd.DataFrame({"condition": base_conditions}, index=base_index),
        var=pd.DataFrame(index=art_genes),
    )
    _decorate(train_adata)
    train_adata.layers["counts"] = train_adata.X.copy()
    train_adata.obs["split"] = pd.Categorical(base_split)

    # DEGs are computed from reference controls plus optimization-TRAIN rows.
    # Internal validation expression is excluded from preprocessing, and
    # counterfactual query rows do not exist yet, so masks are independent of
    # both validation outcomes and the sealed request roster.
    split_by_deg_role = {
        "reference": config.reference_split,
        "train": config.train_split,
    }
    deg_splits = {split_by_deg_role[role] for role in config.deg_input_roles}
    deg_positions = [
        index for index, split_value in enumerate(base_split) if split_value in deg_splits
    ]
    norm = train_adata[deg_positions].copy()
    for key in ("condition", "cov", "cov_cond"):
        norm.obs[key] = norm.obs[key].cat.remove_unused_categories()
    sc.pp.normalize_total(norm, target_sum=config.deg_normalize_target_sum)
    if config.deg_transform != "log1p":
        raise ValueError("CPA supports exactly the registered log1p DEG transform")
    sc.pp.log1p(norm)
    control_deg_category = f"{config.covariate}_ctrl"
    deg_categories = [str(value) for value in norm.obs[config.deg_groupby].cat.categories]
    if control_deg_category not in deg_categories:
        raise ValueError("CPA DEG preprocessing lacks the registered covariate control")
    deg_groups = [value for value in deg_categories if value != control_deg_category]
    if not deg_groups:
        raise ValueError("CPA DEG preprocessing has no non-control condition")
    sc.tl.rank_genes_groups(
        norm,
        groupby=config.deg_groupby,
        groups=deg_groups,
        reference=control_deg_category,
        n_genes=min(config.deg_n_genes, train_adata.n_vars),
        method=config.deg_method,
        use_raw=config.deg_use_raw,
        corr_method=config.deg_corr_method,
        tie_correct=config.deg_tie_correct,
        rankby_abs=config.deg_rankby_abs,
        pts=config.deg_pts,
        layer=config.deg_layer,
    )
    deg_names = norm.uns["rank_genes_groups"]["names"]
    train_adata.uns["rank_genes_groups_cov"] = {
        group: list(deg_names[group][: config.deg_n_genes]) for group in deg_groups
    }

    cpa.CPA.setup_anndata(
        train_adata,
        perturbation_key="condition",
        control_group="ctrl",
        dosage_key="dose_value",
        batch_key=config.batch_key,
        layer=config.layer,
        smiles_key=config.smiles_key,
        categorical_covariate_keys=["cov"],
        is_count_data=True,
        deg_uns_key="rank_genes_groups_cov",
        deg_uns_cat_key="cov_cond",
        max_comb_len=config.max_comb_len,
        n_deg_r2=config.n_deg_r2,
    )
    expected_deg_mask_r2, deg_mask_manifest = _repair_cpa_085_deg_mask_r2(
        train_adata,
        CPA_REGISTRY_KEYS,
        config=config,
    )
    model = cpa.CPA(
        train_adata,
        split_key="split",
        train_split=config.train_split,
        valid_split=config.validation_split,
        test_split=config.counterfactual_split,
        use_rdkit_embeddings=config.use_rdkit_embeddings,
        n_latent=config.n_latent,
        recon_loss=config.recon_loss,
        doser_type=config.doser_type,
        n_hidden_encoder=config.n_hidden_encoder,
        n_layers_encoder=config.n_layers_encoder,
        n_hidden_decoder=config.n_hidden_decoder,
        n_layers_decoder=config.n_layers_decoder,
        n_hidden_doser=config.n_hidden_doser,
        n_layers_doser=config.n_layers_doser,
        use_batch_norm_encoder=config.use_batch_norm_encoder,
        use_layer_norm_encoder=config.use_layer_norm_encoder,
        use_batch_norm_decoder=config.use_batch_norm_decoder,
        use_layer_norm_decoder=config.use_layer_norm_decoder,
        dropout_rate_encoder=config.dropout_rate_encoder,
        dropout_rate_decoder=config.dropout_rate_decoder,
        variational=config.variational,
        seed=seed,
    )
    _verify_model_deg_mask_r2(model, CPA_REGISTRY_KEYS, expected_deg_mask_r2)
    # Freeze cpa-tools 0.8.5's data-dependent epoch cap and trainer defaults
    # explicitly so runtime values cannot drift independently of config bytes.
    max_epochs = min(round((20000 / train_adata.n_obs) * 400), 400)
    model.train(
        max_epochs=max_epochs,
        use_gpu=True,
        train_size=config.train_size,
        validation_size=config.validation_size,
        batch_size=config.batch_size,
        plan_kwargs=_training_plan_kwargs(config),
        save_path=config.library_save_after_train,
        check_val_every_n_epoch=config.check_val_every_n_epoch,
        early_stopping_patience=config.early_stopping_patience,
    )

    # Bind the actual trained parameters, seed and optimization contract before
    # prediction. The controller independently hashes these exact bytes.
    _write_model_checkpoint(
        model,
        checkpoint_path,
        seed=seed,
        config=config,
        split_manifest=split_manifest,
        deg_mask_manifest=deg_mask_manifest,
        torch_module=torch,
    )

    # 3. Build the counterfactual query only AFTER fit/checkpoint.  Requested
    #    combinations must not enter setup_anndata or model.train: CPA 0.8.5 sizes
    #    its perturbation adversary and computes condition weights over every
    #    condition category in the training AnnData, including rows whose split is
    #    OOD.  Adding requested categories before fit would therefore make the
    #    trained state depend on the sealed request roster.
    request_pairs = [tuple(pair) for pair in payload["pair_ids"]]
    if not request_pairs:
        raise ValueError("CPA requires at least one requested pair")
    n_control = len(ctrl_positions)
    pert_encoder = getattr(model, "pert_encoder", None)
    if not isinstance(pert_encoder, dict):
        raise ValueError("CPA model does not expose its registered perturbation encoder")
    control_mean = np.asarray(proj["control_mean"], dtype=np.float64)
    dim = int(payload["response_dim"])
    preds: dict[tuple[str, str], np.ndarray] = {}
    control_positions_array = np.asarray(ctrl_positions, dtype=int)
    for g, h in request_pairs:
        missing = [gene for gene in (g, h) if gene not in pert_encoder]
        if missing:
            raise ValueError(f"CPA requested gene(s) lack trained embeddings: {missing}")
        # One pair × control block at a time bounds peak memory independently of
        # the sealed request count. The checkpoint remains shared: there is no
        # refit and no request-dependent model mutation between chunks.
        query_adata = train_adata[control_positions_array].copy()
        query_adata.obs_names = [f"cf::{g}_{h}::{index}" for index in range(n_control)]
        # Register/validate the control-only query against the trained manager
        # first; all categorical values are known. Then replace only model-facing
        # perturbation id/dose arrays with already-trained single embeddings.
        query_adata = model._validate_anndata(query_adata)
        pert_ids = np.asarray(query_adata.obsm[CPA_REGISTRY_KEYS.PERTURBATIONS]).copy()
        pert_doses = np.asarray(
            query_adata.obsm[CPA_REGISTRY_KEYS.PERTURBATIONS_DOSAGES], dtype=np.float64
        ).copy()
        pert_ids[:, :] = [int(pert_encoder[g]), int(pert_encoder[h])]
        pert_doses[:, :] = [config.query_dose, config.query_dose]
        query_adata.obsm[CPA_REGISTRY_KEYS.PERTURBATIONS] = pert_ids
        query_adata.obsm[CPA_REGISTRY_KEYS.PERTURBATIONS_DOSAGES] = pert_doses
        control_key = CPA_REGISTRY_KEYS.CONTROL_KEY
        if isinstance(control_key, str) and control_key in query_adata.obs:
            query_adata.obs[control_key] = 0

        model.predict(
            query_adata,
            batch_size=config.prediction_batch_size,
            n_samples=config.prediction_n_samples,
            return_mean=config.prediction_return_mean,
        )
        native = np.clip(
            np.asarray(query_adata.obsm["CPA_pred"], dtype=np.float64),
            0.0,
            None,
        )
        z = apply_response_projection(proj, native, gene_order, representation=representation)
        preds[(g, h)] = (z.mean(axis=0) - control_mean)[:dim]
    return preds


def main() -> None:
    """Validate the fit-role artifact, run the pod fit, emit the envelope."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="work_dir", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--approved-root", required=True)
    ap.add_argument(
        "--prediction-representation",
        required=True,
        choices=("cell_raw_counts", "raw_pseudobulk_approximation"),
    )
    a = ap.parse_args()
    identity = _verify_runtime_identity(a.prediction_representation)
    payload = read_payload(a.work_dir, require_expected_sha256=True)
    payload_sha256 = canonical_payload_sha256(payload)
    fit_role = payload["fit_role_artifact"]
    proj = payload["response_projection"]

    # 1. re-validate the artifact exactly as the guard requires (fails closed).
    #    The requested pair identities are SEALED: their cells must never occur
    #    in the fit artifact, so they are passed as ``sealed_pair_ids``.
    spec = FitRoleArtifactSpec(
        path=fit_role["path"],
        sha256=fit_role["sha256"],
        content_manifest_sha256=fit_role["content_manifest_sha256"],
        raw_data_sha256=fit_role["raw_data_sha256"],
        pair_manifest_sha256=fit_role["pair_manifest_sha256"],
        eligibility_hash=fit_role["eligibility_hash"],
        row_identity_sha256=fit_role["row_identity_sha256"],
        gene_order_sha256=fit_role["gene_order_sha256"],
        n_cells=int(fit_role["n_cells"]),
        n_genes=int(fit_role["n_genes"]),
        role_counts=dict(fit_role["role_counts"]),
    )
    validate_fit_role_artifact(
        fit_role["path"],
        spec=spec,
        approved_root=a.approved_root,
        calibration_pair_ids=[tuple(pr) for pr in payload["calibration_pair_ids"]],
        sealed_pair_ids=[tuple(pr) for pr in payload["pair_ids"]],
        single_gene_ids=[str(g) for g in payload["single_gene_ids"]],
    )

    # 2. Read the exact bytes just validated through one stable descriptor.  The
    #    fit body receives this in-memory snapshot and never reopens the path.
    adata = read_verified_fit_role_artifact(
        fit_role["path"], spec=spec, approved_root=a.approved_root
    )
    gene_order = [str(v) for v in adata.var_names]
    representation = a.prediction_representation

    # 3. Fit, write the actual model checkpoint, then predict.
    checkpoint_path = a.out + ".checkpoint"
    preds = _fit_and_predict(
        payload,
        adata,
        proj,
        gene_order,
        representation,
        checkpoint_path=checkpoint_path,
    )
    if os.path.islink(checkpoint_path) or not os.path.isfile(checkpoint_path):
        raise RuntimeError("CPA fit did not produce the required model checkpoint")
    checkpoint_hash = hashlib.sha256()
    with open(checkpoint_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            checkpoint_hash.update(chunk)
    checkpoint = checkpoint_hash.hexdigest()

    manifest = {
        "prediction_representation": representation,
        "adapter_version": identity.adapter_version,
        "adapter_sha256": identity.adapter_sha256,
        "expected_gene_order_sha256": proj["gene_order_sha256"],
        "observed_gene_order_sha256": canonical_gene_order_sha256(gene_order),
        "checkpoint_sha256": checkpoint,
        "worker_sha256": identity.worker_executable_sha256,
        "config_sha256": identity.config_sha256,
        "resource_sha256": identity.resource_sha256,
        "environment_lock_sha256": identity.environment_lock_sha256,
        "payload_sha256": payload_sha256,
        "fit_artifact_content_sha256": fit_role["content_manifest_sha256"],
        "combined_request_sha256": hashlib.sha256(
            json.dumps([list(pr) for pr in payload["pair_ids"]], separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
        "predictions_sha256": "",  # write_predictions fills this
    }
    write_predictions(a.out, preds, execution_manifest=manifest)


if __name__ == "__main__":
    main()
