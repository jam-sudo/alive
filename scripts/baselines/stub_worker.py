# scripts/baselines/stub_worker.py
"""SYNTHETIC-ONLY deterministic additive-delta stub worker (protocol reference).

Runs in any python; predicts, per requested pair (g,h), the additive delta
singles_response[g] + singles_response[h] projected trivially to response_dim,
then emits the ``{predictions, execution_manifest}`` envelope with a checkpoint
sidecar. The additive body and manifest are transitional: Task 7 replaces the
body with the real operator and starts *using* ``--approved-root`` for artifact
validation. The real gears/cpa workers replace this under the locked envs
(pod-only).
"""

from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np

from alive.compose.baseline_subprocess import read_payload, write_predictions


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="work_dir", required=True)
    ap.add_argument("--out", dest="out", required=True)
    # Accepted now (the Task-5 backend always sends it); Task 7 uses it in
    # ``validate_fit_role_artifact``. The transitional additive body does not
    # open the artifact yet.
    ap.add_argument("--approved-root", required=True)
    a = ap.parse_args()
    p = read_payload(a.work_dir)
    ids = list(p["single_gene_ids"])
    singles = np.asarray(p["singles_response"], dtype=float)
    idx = {g: i for i, g in enumerate(ids)}
    dim = int(p["response_dim"])
    preds = {}
    for g, h in p["pair_ids"]:
        vec = singles[idx[g]] + singles[idx[h]]
        preds[(g, h)] = vec[:dim]
    fit_role = p["fit_role_artifact"]
    proj = p["response_projection"]
    checkpoint_bytes = json.dumps(
        {"stub": "additive-envelope-transition"}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    with open(a.out + ".checkpoint", "xb") as fh:
        fh.write(checkpoint_bytes)
    manifest = {
        "prediction_representation": "cell_raw_counts",
        "adapter_version": "stub-1",
        "adapter_sha256": hashlib.sha256(b"stub-1").hexdigest(),
        "expected_gene_order_sha256": proj["gene_order_sha256"],
        "observed_gene_order_sha256": proj["gene_order_sha256"],
        "checkpoint_sha256": hashlib.sha256(checkpoint_bytes).hexdigest(),
        "worker_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
        "config_sha256": hashlib.sha256(b"stub-config").hexdigest(),
        "resource_sha256": hashlib.sha256(b"stub-resource").hexdigest(),
        "environment_lock_sha256": hashlib.sha256(b"stub-environment").hexdigest(),
        "fit_artifact_content_sha256": fit_role["content_manifest_sha256"],
        "combined_request_sha256": hashlib.sha256(
            json.dumps(p["pair_ids"], sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "predictions_sha256": "",  # write_predictions fills this
    }
    write_predictions(a.out, preds, execution_manifest=manifest)


if __name__ == "__main__":
    main()
