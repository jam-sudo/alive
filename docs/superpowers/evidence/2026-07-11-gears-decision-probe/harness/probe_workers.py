#!/usr/bin/env python
"""Prototype: does raising the GEARS train DataLoader num_workers cut wall-time?

The committed worker builds its train/val loaders with num_workers=0 (single
process) in ``_install_deterministic_cell_split``; the host has 252 cores but
GEARS uses ~22 (GPU idle). This driver monkeypatches ``torch_geometric.loader.
DataLoader`` to inject ``num_workers=$NW`` (+ persistent_workers/pin_memory)
BEFORE the worker imports it, runs a 1-epoch fit on the existing 2k fit-role
artifact, and lets GEARS print its per-step train loss. An external sampler reads
the step-rate. The committed worker is byte-unchanged; this opens no seal and
writes only a throwaway checkpoint. NW=0 reproduces the current behavior.

Usage: NW=<n> probe_workers.py <worker.py> <work_dir> <representation>
"""

import importlib.util
import inspect
import os
import sys

# --- inject num_workers into every torch_geometric.loader.DataLoader --------- #
NW = int(os.environ.get("NW", "0"))
import torch_geometric.loader as _tgl  # noqa: E402

_orig_dl = _tgl.DataLoader


def _patched_dl(dataset, batch_size=1, **kw):
    if NW > 0:
        kw.setdefault("num_workers", NW)
        kw.setdefault("persistent_workers", True)
        kw.setdefault("pin_memory", True)
    return _orig_dl(dataset, batch_size=batch_size, **kw)


_tgl.DataLoader = _patched_dl
print("NUM_WORKERS_PATCH nw=%d omp=%s" % (NW, os.environ.get("OMP_NUM_THREADS", "unset")), flush=True)

WORKER, WORK_DIR, REPRESENTATION = sys.argv[1:4]
_spec = importlib.util.spec_from_file_location("_dev_worker", WORKER)
worker = importlib.util.module_from_spec(_spec)
sys.modules["_dev_worker"] = worker
_spec.loader.exec_module(worker)

worker._GEARS_EPOCHS = 1  # measurement-only; committed file unchanged (step-rate probe)

from alive.compose.baseline_subprocess import read_payload  # noqa: E402
from alive.compose.fit_role import (  # noqa: E402
    FitRoleArtifactSpec,
    read_verified_fit_role_artifact,
    validate_fit_role_artifact,
)

payload = read_payload(WORK_DIR, require_expected_sha256=False)
fit_role = payload["fit_role_artifact"]
proj = payload["response_projection"]
spec = FitRoleArtifactSpec(
    path=fit_role["path"], sha256=fit_role["sha256"],
    content_manifest_sha256=fit_role["content_manifest_sha256"],
    raw_data_sha256=fit_role["raw_data_sha256"],
    pair_manifest_sha256=fit_role["pair_manifest_sha256"],
    eligibility_hash=fit_role["eligibility_hash"],
    row_identity_sha256=fit_role["row_identity_sha256"],
    gene_order_sha256=fit_role["gene_order_sha256"],
    n_cells=int(fit_role["n_cells"]), n_genes=int(fit_role["n_genes"]),
    role_counts=dict(fit_role["role_counts"]),
)
approved_root = os.path.dirname(os.path.abspath(fit_role["path"]))
validate_fit_role_artifact(
    fit_role["path"], spec=spec, approved_root=approved_root,
    calibration_pair_ids=[tuple(p) for p in payload["calibration_pair_ids"]],
    sealed_pair_ids=[tuple(p) for p in payload["pair_ids"]],
    single_gene_ids=[str(g) for g in payload["single_gene_ids"]],
)
adata = read_verified_fit_role_artifact(fit_role["path"], spec=spec, approved_root=approved_root)
gene_order = [str(v) for v in adata.var_names]
print("FIT_ARTIFACT cells=%d genes=%d nw=%d" % (adata.n_obs, adata.n_vars, NW), flush=True)

ckpt = os.path.join(WORK_DIR, f"workers_nw{NW}.checkpoint")
if os.path.lexists(ckpt):
    os.remove(ckpt)
kw = {"checkpoint_path": ckpt}
if "fit_artifact_content_sha256" in inspect.signature(worker._fit_and_predict).parameters:
    kw["fit_artifact_content_sha256"] = fit_role["content_manifest_sha256"]
worker._fit_and_predict(payload, adata, proj, gene_order, REPRESENTATION, **kw)
print("PROBE_WORKERS_DONE nw=%d" % NW, flush=True)
