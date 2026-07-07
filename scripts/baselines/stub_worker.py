# scripts/baselines/stub_worker.py
"""SYNTHETIC-ONLY payload-v2 reference worker (protocol reference, not a baseline).

Reads + validates the fit-role artifact, fits once (a deterministic checkpoint
over the ``combo_calibration`` cells), predicts each requested pair's native
full-gene expression as those calibration cells, applies the registered §2.3
response operator, and returns the ``{predictions, execution_manifest}``
envelope with real digests. The synthetic reference deterministically maps each
requested pair to one fitted calibration group, so its δ̂ is observable,
pair-associated and non-zero — but it makes NO scientific baseline claim. The
real gears/cpa workers replace this under the locked envs (pod-only).
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

# Fixed-constant execution identity. The controller's ``ExecutionIdentityLock``
# MUST mirror these exactly or ``_verify_execution_manifest`` fails closed.
_ADAPTER_VERSION = "stub-2"
_ADAPTER_SHA256 = hashlib.sha256(b"stub-response-operator-v2").hexdigest()
_CONFIG_SHA256 = hashlib.sha256(b"stub-config").hexdigest()
_RESOURCE_SHA256 = hashlib.sha256(b"stub-resource").hexdigest()
_ENVIRONMENT_LOCK_SHA256 = hashlib.sha256(b"stub-environment").hexdigest()


def main() -> None:
    """Run the reference operator path once and emit the prediction envelope."""
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
    dim = int(payload["response_dim"])

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

    # 2. load the artifact; group native full-gene combo_calibration cells only.
    adata = ad.read_h5ad(fit_role["path"])
    gene_order = [str(v) for v in adata.var_names]
    roles = [str(r) for r in adata.obs["role"]]
    perts = [str(v) for v in adata.obs["perturbation"]]
    calibration_groups: dict[str, np.ndarray] = {}
    tokens = sorted({tok for tok, role in zip(perts, roles) if role == "combo_calibration"})
    for token in tokens:
        idx = np.array(
            [
                i
                for i, (tok, role) in enumerate(zip(perts, roles))
                if tok == token and role == "combo_calibration"
            ]
        )
        calibration_groups[token] = np.asarray(adata.X[idx].todense(), dtype=np.float64)
    if not calibration_groups:
        raise ValueError("reference worker requires combo_calibration cells")

    # 3. fit once -> write-once deterministic checkpoint sidecar over the bank.
    checkpoint_obj = {
        "schema": "stub_calibration_bank_v1",
        "gene_order_sha256": canonical_gene_order_sha256(gene_order),
        "groups": {
            token: [[float(v).hex() for v in row] for row in matrix]
            for token, matrix in calibration_groups.items()
        },
    }
    checkpoint_bytes = json.dumps(checkpoint_obj, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    with open(a.out + ".checkpoint", "xb") as fh:
        fh.write(checkpoint_bytes)
    checkpoint = hashlib.sha256(checkpoint_bytes).hexdigest()

    # 4. predict the combined pair union once. Each request is deterministically
    #    mapped to one fitted calibration group, preserving pair association.
    control_mean = np.asarray(proj["control_mean"], dtype=np.float64)
    group_keys = sorted(calibration_groups)
    preds: dict[tuple[str, str], np.ndarray] = {}
    representation = a.prediction_representation
    for g, h in payload["pair_ids"]:
        request_digest = hashlib.sha256(f"{g}\0{h}".encode()).digest()
        token = group_keys[int.from_bytes(request_digest[:8], "big") % len(group_keys)]
        native = calibration_groups[token]
        operator_input = (
            native.mean(axis=0, keepdims=True)
            if representation == "raw_pseudobulk_approximation"
            else native
        )
        z = apply_response_projection(
            proj, operator_input, gene_order, representation=representation
        )
        preds[(g, h)] = (z.mean(axis=0) - control_mean)[:dim]

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
