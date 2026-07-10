# scripts/baselines/cpa_worker.py
"""Real CPA deep-baseline worker (fit body pod-authored).

COMPLETE contract surface for the fit-role-only subprocess protocol: reads +
validates the fit-role artifact (the SEALED requested pairs enter ONLY as
``sealed_pair_ids`` to the leakage guard — never as fit rows), delegates the
model fit + prediction to :func:`_fit_and_predict`, and returns the
``{predictions, execution_manifest}`` envelope with real digests.

``_fit_and_predict`` is import-guarded and pod-authored: on a host without the
real ``cpa`` package it raises :class:`WorkerUnavailable`, and on the GPU pod its
body (plan Task 1.2/1.3) fits CPA and predicts each requested pair. This scaffold
opens NO seal, reads NO sealed outcome, and fits NO real model on the MacBook.
Recommended pin: CPA ``cpa-tools==0.8.5``.
"""

from __future__ import annotations

import argparse
import hashlib
import json

import anndata as ad
import numpy as np

from alive.compose.baseline_subprocess import read_payload, write_predictions
from alive.compose.fit_role import (
    FitRoleArtifactSpec,
    apply_response_projection,
    canonical_gene_order_sha256,
    validate_fit_role_artifact,
)

# Published CPA defaults for combo prediction (plan decision #3; cpa-tools
# defaults). Named constants, not outcome-tuned knobs. The dev smoke may lower the
# epoch cap via COMPOSE_CPA_SMOKE_EPOCHS purely to speed plumbing iteration.
_CPA_N_LATENT = 32
_CPA_MAX_EPOCHS = 100
_CPA_BATCH_SIZE = 128
_CPA_MAX_COMB_LEN = 2
_CPA_COV = "K562"
_CONTROL_TOKEN = "control"
_COMBO_SEP = "_"

# Fixed-constant execution identity. The controller's ``ExecutionIdentityLock``
# MUST mirror these exactly or ``_verify_execution_manifest`` fails closed. These
# are 64-hex placeholders so the manifest validates locally; the pod binds them
# to the real committed identities.
# POD-FILL from committed dependency lock / GO manifest (plan Task 1.2/2.1)
_ADAPTER_VERSION = "cpa-pod-scaffold-1"
# POD-FILL from committed dependency lock / GO manifest (plan Task 1.2/2.1)
_ADAPTER_SHA256 = hashlib.sha256(b"POD-FILL-cpa-adapter").hexdigest()
# POD-FILL from committed dependency lock / GO manifest (plan Task 1.2/2.1)
_CONFIG_SHA256 = hashlib.sha256(b"POD-FILL-cpa-config").hexdigest()
# POD-FILL from committed dependency lock / GO manifest (plan Task 1.2/2.1)
_RESOURCE_SHA256 = hashlib.sha256(b"POD-FILL-cpa-resource").hexdigest()
# POD-FILL from committed dependency lock / GO manifest (plan Task 1.2/2.1)
_ENVIRONMENT_LOCK_SHA256 = hashlib.sha256(b"POD-FILL-cpa-environment").hexdigest()


class WorkerUnavailable(RuntimeError):
    """Raised when the real ``cpa`` package is absent (real fit is pod-authored)."""


def _fit_and_predict(
    payload: dict,
    fit_role: dict,
    proj: dict,
    gene_order: list[str],
    representation: str,
) -> dict[tuple[str, str], np.ndarray]:
    """Fit real CPA and predict each requested pair's response-space delta.

    POD-AUTHORED. The committed scaffold only proves the ``cpa`` package is
    importable, then defers to the GPU pod. The real body (plan Task 1.2/1.3)
    must, using ONLY fit roles (control + singles + combo_calibration; the sealed
    requested pairs are NEVER rows):

    1. load the fit-role ``.h5ad`` from ``fit_role["path"]``;
    2. fit CPA on those rows (recommended pin: ``cpa-tools==0.8.5``);
    3. predict each ``payload["pair_ids"]`` pair's native full-gene expression;
    4. map native -> response space with ``apply_response_projection`` honoring
       ``representation`` (``raw_pseudobulk_approximation`` ->
       ``native.mean(axis=0, keepdims=True)``; ``cell_*`` -> ``native``), then
       ``delta = mean(z) - control_mean``;
    5. return ``{pair: delta[:response_dim]}`` over ``payload["pair_ids"]``.

    Returns
    -------
    dict
        Mapping from each requested canonical pair to its length-``response_dim``
        response-space prediction vector.

    Raises
    ------
    WorkerUnavailable
        If the ``cpa`` package is not installed (real fit is authored on the GPU
        pod).
    NotImplementedError
        On a host where ``cpa`` IS importable but the pod fit body is not yet
        authored.
    """
    try:
        import cpa
        import torch  # noqa: F401
    except ImportError as exc:
        raise WorkerUnavailable(
            "cpa not installed; real CPA fit is authored on the GPU pod"
        ) from exc

    import os

    import anndata as ad
    import pandas as pd
    import scanpy as sc
    from scipy import sparse

    # 1. load the leakage-validated fit-role artifact (raw counts; control +
    #    singles + combo_calibration rows — sealed combos never present).
    adata = ad.read_h5ad(fit_role["path"])
    art_genes = [str(v) for v in adata.var_names]
    if art_genes != list(gene_order):
        raise ValueError("fit-role artifact gene order diverges from the observed gene order")
    tokens = [str(p) for p in adata.obs["perturbation"]]

    def _condition(token: str) -> str:
        if token == _CONTROL_TOKEN:
            return "ctrl"
        if _COMBO_SEP in token:
            a, b = token.split(_COMBO_SEP, 1)
            return f"{a}+{b}"
        return f"{token}+ctrl"

    def _decorate(obj) -> None:
        """Attach the CPA obs covariates (condition, dose, covariate, cov_cond)."""
        cond = obj.obs["condition"].astype(str)
        obj.obs["dose_value"] = ["+".join(["1.0"] * len(c.split("+"))) for c in cond]
        obj.obs["cov"] = _CPA_COV
        obj.obs["cov_cond"] = _CPA_COV + "_" + cond
        for key in ("condition", "cov", "cov_cond"):
            obj.obs[key] = obj.obs[key].astype("category")

    # 2. build the CPA AnnData. Base rows = the fit-role artifact ({control,
    #    singles, combo_calibration}). For each SEALED combo we ALSO append a block
    #    of CONTROL cells relabeled to that combo condition, marked split='ood':
    #    the counterfactual substrate (control expression, target label). This
    #    registers each sealed-combo category WITH cells — CPA weights every drug by
    #    n_obs/n_positive, which zero-divides on a zero-cell category, and scvi's
    #    field transfer rejects an unseen category — while HOLDING those cells out of
    #    training. Their expression is control; no sealed cell/outcome is ever read.
    counts = sparse.csr_matrix(adata.X, dtype="float32")
    base_conditions = [_condition(t) for t in tokens]
    base_index = [str(s) for s in adata.obs_names]

    ctrl_positions = [i for i, t in enumerate(tokens) if t == _CONTROL_TOKEN]
    if not ctrl_positions:
        raise ValueError("CPA counterfactual prediction requires control cells")
    ctrl_counts = counts[ctrl_positions]

    rng = np.random.default_rng(int(payload["seed"]))
    r = rng.random(counts.shape[0])
    # base cells: train / valid only (no base ood — ood is the counterfactual set).
    base_split = np.where(r < 0.9, "train", "test")

    blocks = [counts]
    all_conditions = list(base_conditions)
    all_index = list(base_index)
    all_split = list(base_split)
    cf_rows_of_pair: dict[tuple[str, str], list[int]] = {}
    for g, h in payload["pair_ids"]:
        start = sum(b.shape[0] for b in blocks)
        n = ctrl_counts.shape[0]
        blocks.append(ctrl_counts)
        all_conditions += [f"{g}+{h}"] * n
        all_index += [f"cf::{g}_{h}::{k}" for k in range(n)]
        all_split += ["ood"] * n
        cf_rows_of_pair[(g, h)] = list(range(start, start + n))

    train_adata = ad.AnnData(
        X=sparse.vstack(blocks).tocsr(),
        obs=pd.DataFrame({"condition": all_conditions}, index=all_index),
        var=pd.DataFrame(index=art_genes),
    )
    _decorate(train_adata)
    train_adata.layers["counts"] = train_adata.X.copy()
    train_adata.obs["split"] = pd.Categorical(all_split)

    # DEGs per cov_cond group (setup deg branch) on a log-normalized copy. The
    # counterfactual ood groups carry control expression; their DEG is a harmless
    # mask (ood cells never enter the train/valid loss).
    norm = train_adata.copy()
    sc.pp.normalize_total(norm, target_sum=1e4)
    sc.pp.log1p(norm)
    sc.tl.rank_genes_groups(norm, groupby="cov_cond", method="wilcoxon", n_genes=50)
    deg_names = norm.uns["rank_genes_groups"]["names"]
    train_adata.uns["rank_genes_groups_cov"] = {
        grp: list(deg_names[grp][:50]) for grp in train_adata.obs["cov_cond"].cat.categories
    }

    cpa.CPA.setup_anndata(
        train_adata,
        perturbation_key="condition",
        control_group="ctrl",
        dosage_key="dose_value",
        categorical_covariate_keys=["cov"],
        is_count_data=True,
        deg_uns_key="rank_genes_groups_cov",
        deg_uns_cat_key="cov_cond",
        max_comb_len=_CPA_MAX_COMB_LEN,
    )
    model = cpa.CPA(
        train_adata,
        split_key="split",
        train_split="train",
        valid_split="test",
        test_split="ood",
        n_latent=_CPA_N_LATENT,
    )
    epochs = int(os.environ.get("COMPOSE_CPA_SMOKE_EPOCHS", _CPA_MAX_EPOCHS))
    model.train(
        max_epochs=epochs,
        use_gpu=torch.cuda.is_available(),
        batch_size=_CPA_BATCH_SIZE,
        early_stopping_patience=max(5, epochs // 10),
        check_val_every_n_epoch=1,
    )

    # 3. predict the registered adata; each sealed pair's held-out counterfactual
    #    rows carry its per-cell predicted raw counts -> response space -> delta.
    model.predict(train_adata, batch_size=_CPA_BATCH_SIZE)
    cpa_pred = np.asarray(train_adata.obsm["CPA_pred"], dtype=np.float64)
    control_mean = np.asarray(proj["control_mean"], dtype=np.float64)
    dim = int(payload["response_dim"])
    preds: dict[tuple[str, str], np.ndarray] = {}
    for g, h in payload["pair_ids"]:
        native = np.clip(cpa_pred[cf_rows_of_pair[(g, h)]], 0.0, None)
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
    payload = read_payload(a.work_dir)
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

    # 2. observe the on-disk gene order (drift detection) and hand it to the fit.
    adata = ad.read_h5ad(fit_role["path"])
    gene_order = [str(v) for v in adata.var_names]
    representation = a.prediction_representation

    # 3. pod-authored fit + prediction (import-guarded; raises off-pod).
    preds = _fit_and_predict(payload, fit_role, proj, gene_order, representation)

    # 4. write-once checkpoint sidecar + its digest, exactly as the stub does.
    #    The fit body is pod-authored, so the scaffold derives a deterministic
    #    sidecar from the returned predictions and the fit-role identity.
    #    POD-FILL: a real run SHOULD fold the trained-model digest in (plan 2.1).
    checkpoint_obj = {
        "schema": "cpa_worker_prediction_bank_v1",
        "gene_order_sha256": canonical_gene_order_sha256(gene_order),
        "fit_artifact_content_sha256": fit_role["content_manifest_sha256"],
        "predictions": {
            "\0".join(pair): [float(v).hex() for v in np.asarray(vec, dtype=np.float64).ravel()]
            for pair, vec in sorted(preds.items())
        },
    }
    checkpoint_bytes = json.dumps(checkpoint_obj, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    with open(a.out + ".checkpoint", "xb") as fh:
        fh.write(checkpoint_bytes)
    checkpoint = hashlib.sha256(checkpoint_bytes).hexdigest()

    with open(__file__, "rb") as fh:
        worker_sha256 = hashlib.sha256(fh.read()).hexdigest()
    manifest = {
        "prediction_representation": representation,
        "adapter_version": _ADAPTER_VERSION,
        "adapter_sha256": _ADAPTER_SHA256,
        "expected_gene_order_sha256": proj["gene_order_sha256"],
        "observed_gene_order_sha256": canonical_gene_order_sha256(gene_order),
        "checkpoint_sha256": checkpoint,
        "worker_sha256": worker_sha256,
        "config_sha256": _CONFIG_SHA256,
        "resource_sha256": _RESOURCE_SHA256,
        "environment_lock_sha256": _ENVIRONMENT_LOCK_SHA256,
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
