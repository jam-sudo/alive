# scripts/baselines/gears_worker.py
"""Real GEARS deep-baseline worker (fit body pod-authored).

COMPLETE contract surface for the fit-role-only subprocess protocol: reads +
validates the fit-role artifact (the SEALED requested pairs enter ONLY as
``sealed_pair_ids`` to the leakage guard — never as fit rows), delegates the
model fit + prediction to :func:`_fit_and_predict`, and returns the
``{predictions, execution_manifest}`` envelope with real digests.

``_fit_and_predict`` is import-guarded and pod-authored: on a host without the
real ``gears`` package it raises :class:`WorkerUnavailable`, and on the GPU pod
its body (plan Task 1.2/1.3) fits GEARS and predicts each requested pair. This
scaffold opens NO seal, reads NO sealed outcome, and fits NO real model on the
MacBook. Recommended pin: GEARS ``cell-gears==0.1.2``.
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

# Published GEARS defaults for K562 Perturb-seq (plan decision #1; GEARS paper /
# repo defaults). Named constants, not tuned knobs — no outcome selects any of
# these. The dev smoke may lower epochs via COMPOSE_GEARS_SMOKE_EPOCHS purely to
# speed plumbing iteration; the committed default is the published value.
_GEARS_HIDDEN_SIZE = 64
_GEARS_EPOCHS = 20
_GEARS_BATCH_SIZE = 32
_GEARS_TEST_BATCH_SIZE = 128
_GEARS_TRAIN_GENE_SET_SIZE = 0.75
_CONTROL_TOKEN = "control"
_COMBO_SEP = "_"

# Fixed-constant execution identity. The controller's ``ExecutionIdentityLock``
# MUST mirror these exactly or ``_verify_execution_manifest`` fails closed. These
# are 64-hex placeholders so the manifest validates locally; the pod binds them
# to the real committed identities.
# POD-FILL from committed dependency lock / GO manifest (plan Task 1.2/2.1)
_ADAPTER_VERSION = "gears-pod-scaffold-1"
# POD-FILL from committed dependency lock / GO manifest (plan Task 1.2/2.1)
_ADAPTER_SHA256 = hashlib.sha256(b"POD-FILL-gears-adapter").hexdigest()
# POD-FILL from committed dependency lock / GO manifest (plan Task 1.2/2.1)
_CONFIG_SHA256 = hashlib.sha256(b"POD-FILL-gears-config").hexdigest()
# POD-FILL from committed dependency lock / GO manifest (plan Task 1.2/2.1)
_RESOURCE_SHA256 = hashlib.sha256(b"POD-FILL-gears-resource").hexdigest()
# POD-FILL from committed dependency lock / GO manifest (plan Task 1.2/2.1)
_ENVIRONMENT_LOCK_SHA256 = hashlib.sha256(b"POD-FILL-gears-environment").hexdigest()


class WorkerUnavailable(RuntimeError):
    """Raised when the real ``gears`` package is absent (real fit is pod-authored)."""


def _fit_and_predict(
    payload: dict,
    fit_role: dict,
    proj: dict,
    gene_order: list[str],
    representation: str,
) -> dict[tuple[str, str], np.ndarray]:
    """Fit real GEARS and predict each requested pair's response-space delta.

    POD-AUTHORED. The committed scaffold only proves the ``gears`` package is
    importable, then defers to the GPU pod. The real body (plan Task 1.2/1.3)
    must, using ONLY fit roles (control + singles + combo_calibration; the sealed
    requested pairs are NEVER rows):

    1. load the fit-role ``.h5ad`` from ``fit_role["path"]``;
    2. fit GEARS on those rows (recommended pin: ``cell-gears==0.1.2``);
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
        If the ``gears`` package is not installed (real fit is authored on the
        GPU pod).
    NotImplementedError
        On a host where ``gears`` IS importable but the pod fit body is not yet
        authored.
    """
    try:
        import torch
        from gears import GEARS, PertData
    except ImportError as exc:
        raise WorkerUnavailable(
            "gears not installed; real GEARS fit is authored on the GPU pod"
        ) from exc

    import os
    import tempfile

    import anndata as ad
    import pandas as pd
    from scipy import sparse

    # 1. load the leakage-validated fit-role artifact (raw counts; control +
    #    singles + combo_calibration rows — sealed combos are never present).
    adata = ad.read_h5ad(fit_role["path"])
    art_genes = [str(v) for v in adata.var_names]
    if art_genes != list(gene_order):
        raise ValueError("fit-role artifact gene order diverges from the observed gene order")
    tokens = [str(p) for p in adata.obs["perturbation"]]

    # 2. build a GEARS-format AnnData: raw counts, GEARS condition naming
    #    (ctrl / GENE+ctrl / GENEA+GENEB), gene_name var column, cell_type obs.
    def _condition(token: str) -> str:
        if token == _CONTROL_TOKEN:
            return "ctrl"
        if _COMBO_SEP in token:
            a, b = token.split(_COMBO_SEP, 1)
            return f"{a}+{b}"
        return f"{token}+ctrl"

    conditions = [_condition(t) for t in tokens]
    gears_obs = pd.DataFrame(
        {
            "condition": pd.Categorical(conditions),
            "cell_type": pd.Categorical(["K562"] * len(conditions)),
        },
        index=[str(s) for s in adata.obs_names],
    )
    gears_var = pd.DataFrame({"gene_name": art_genes}, index=art_genes)
    gears_adata = ad.AnnData(
        X=sparse.csr_matrix(adata.X, dtype="float32"), obs=gears_obs, var=gears_var
    )

    work = tempfile.mkdtemp(prefix="compose_gears_")
    pert_data = PertData(work)
    pert_data.new_data_process("compose_smoke", adata=gears_adata)

    # 3. GEARS 'no_test' split: fit on ALL non-sealed conditions with a gene-based
    #    train/val holdout for early stopping (GEARS's published convention). There
    #    is NO held-out test set — GEARS.train() skips test evaluation when no test
    #    loader exists. The sealed pairs are absent from the data entirely and are
    #    predicted counterfactually below; every sealed gene occurs as a trained
    #    single, so it stays in GEARS.pert_list and remains predictable.
    pert_data.prepare_split(
        split="no_test",
        seed=int(payload["seed"]),
        train_gene_set_size=_GEARS_TRAIN_GENE_SET_SIZE,
    )
    pert_data.get_dataloader(batch_size=_GEARS_BATCH_SIZE, test_batch_size=_GEARS_TEST_BATCH_SIZE)

    # 4. fit GEARS with the published defaults (no outcome-based knob selection).
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = GEARS(pert_data, device=device)
    model.model_initialize(hidden_size=_GEARS_HIDDEN_SIZE)
    epochs = int(os.environ.get("COMPOSE_GEARS_SMOKE_EPOCHS", _GEARS_EPOCHS))
    model.train(epochs=epochs)

    # 5. predict each SEALED requested combo (both genes are trained singles, so
    #    GEARS composes the unseen combo). GEARS returns one pseudobulk vector per
    #    request in the training-X (raw-count) gene space.
    predictable = set(getattr(model, "pert_list", []) or [])
    requests: list[list[str]] = []
    for g, h in payload["pair_ids"]:
        if predictable and (g not in predictable or h not in predictable):
            raise ValueError(f"sealed pair ({g!r},{h!r}) has a gene absent from GEARS.pert_list")
        requests.append([g, h])
    raw_pred = model.predict(requests)

    gears_genes = [str(x) for x in pert_data.adata.var["gene_name"]]
    name_to_col = {g: i for i, g in enumerate(gears_genes)}
    try:
        remap = [name_to_col[g] for g in gene_order]
    except KeyError as exc:
        raise ValueError(
            f"GEARS output is missing gene {exc} from the response gene order"
        ) from exc

    control_mean = np.asarray(proj["control_mean"], dtype=np.float64)
    dim = int(payload["response_dim"])
    preds: dict[tuple[str, str], np.ndarray] = {}
    for g, h in payload["pair_ids"]:
        vec = np.asarray(raw_pred[f"{g}_{h}"], dtype=np.float64)[remap]
        # predicted expression is a raw-count approximation → clamp negatives; the
        # single pseudobulk vector already satisfies the representation reduction.
        native = np.clip(vec, 0.0, None)[None, :]
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
        "schema": "gears_worker_prediction_bank_v1",
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
