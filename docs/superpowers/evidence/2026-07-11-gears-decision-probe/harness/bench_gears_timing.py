#!/usr/bin/env python
"""Probe B — GEARS fit-cost benchmark at one roster size (opens no seal).

Drives the REAL committed ``gears_worker._fit_and_predict`` (so the measurement is
the true pipeline, not a proxy) at two epoch counts and extrapolates to the
registered ``_GEARS_EPOCHS=20``:

    total(k) = one_time(staging+graph+checkpoint) + k * per_epoch
    per_epoch    = (total(6) - total(3)) / 3
    one_time     = total(3) - 3 * per_epoch
    total_20     = one_time + 20 * per_epoch          # the feasibility number

``PertData.new_data_process`` is wrapped to isolate the per-cell graph-build time
(B1) and to capture the PROCESSED input scale (empirical P1/P4 for Probe A). Peak
host RSS and peak GPU memory are recorded (B3), plus host CPU/GPU spec (B4).

GOVERNANCE: this in-process measurement harness monkeypatches ``_GEARS_EPOCHS`` for
extrapolation ONLY. The committed worker file is byte-unchanged; the production
subprocess always runs 20 epochs. No seal is opened, no evaluation outcome is
produced, and the written checkpoints are throwaway timing artifacts.

Usage: bench_gears_timing.py <worker.py> <work_dir> <representation> <size_label> <out_dir>
"""

import importlib.util
import inspect
import json
import os
import resource
import sys
from time import perf_counter

import numpy as np

WORKER, WORK_DIR, REPRESENTATION, SIZE_LABEL, OUT = sys.argv[1:6]
os.makedirs(OUT, exist_ok=True)

_spec = importlib.util.spec_from_file_location("_dev_worker", WORKER)
worker = importlib.util.module_from_spec(_spec)
sys.modules["_dev_worker"] = worker
_spec.loader.exec_module(worker)

import torch  # noqa: E402
import gears.pertdata as gears_pertdata  # noqa: E402

from alive.compose.baseline_subprocess import read_payload  # noqa: E402
from alive.compose.fit_role import (  # noqa: E402
    FitRoleArtifactSpec,
    read_verified_fit_role_artifact,
    validate_fit_role_artifact,
)

# --- load the fit-role artifact + payload (same as the smoke driver) -------- #
payload = read_payload(WORK_DIR, require_expected_sha256=False)
fit_role = payload["fit_role_artifact"]
proj = payload["response_projection"]
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
approved_root = os.path.dirname(os.path.abspath(fit_role["path"]))
validate_fit_role_artifact(
    fit_role["path"],
    spec=spec,
    approved_root=approved_root,
    calibration_pair_ids=[tuple(p) for p in payload["calibration_pair_ids"]],
    sealed_pair_ids=[tuple(p) for p in payload["pair_ids"]],
    single_gene_ids=[str(g) for g in payload["single_gene_ids"]],
)
adata = read_verified_fit_role_artifact(fit_role["path"], spec=spec, approved_root=approved_root)
gene_order = [str(v) for v in adata.var_names]
print("FIT_ARTIFACT size=%s cells=%d genes=%d role_counts=%s"
      % (SIZE_LABEL, adata.n_obs, adata.n_vars, dict(fit_role["role_counts"])), flush=True)

# --- instrument PertData.new_data_process (B1 + processed scale capture) ---- #
_graph_times = []
_scale_capture = {}
_orig_ndp = gears_pertdata.PertData.new_data_process


def _timed_ndp(self, *a, **k):
    t0 = perf_counter()
    r = _orig_ndp(self, *a, **k)
    _graph_times.append(perf_counter() - t0)
    if not _scale_capture:  # characterize processed input scale once (P1/P4)
        try:
            import scipy.sparse as sp

            X = self.adata.X
            Xd = (X[:512].toarray() if sp.issparse(X) else np.asarray(X[:512])).astype(np.float64)
            rows = Xd.sum(axis=1)
            _scale_capture.update(
                processed_min=float(Xd.min()),
                processed_median=float(np.median(Xd)),
                processed_max=float(Xd.max()),
                processed_row_sum_median=float(np.median(rows)),
                processed_row_sum_std=float(np.std(rows)),
                processed_frac_near_integer=float(np.mean(np.abs(Xd - np.round(Xd)) < 1e-6)),
                processed_looks_log_space=bool(Xd.max() < 20.0),
            )
        except Exception as exc:  # noqa: BLE001
            _scale_capture["error"] = repr(exc)
    return r


gears_pertdata.PertData.new_data_process = _timed_ndp

# --- run at two epoch counts ------------------------------------------------ #
_kw_extra = {}
if "fit_artifact_content_sha256" in inspect.signature(worker._fit_and_predict).parameters:
    _kw_extra["fit_artifact_content_sha256"] = fit_role["content_manifest_sha256"]

runs = {}
for k in (3, 6):
    worker._GEARS_EPOCHS = k  # measurement-only override; committed file unchanged
    ckpt = os.path.join(WORK_DIR, f"bench_{SIZE_LABEL}_ep{k}.checkpoint")
    if os.path.lexists(ckpt):
        os.remove(ckpt)
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    t0 = perf_counter()
    worker._fit_and_predict(payload, adata, proj, gene_order, REPRESENTATION,
                            checkpoint_path=ckpt, **_kw_extra)
    wall = perf_counter() - t0
    runs[k] = {
        "epochs": k,
        "wall_s": wall,
        "peak_gpu_bytes": int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None,
        "checkpoint_bytes": os.path.getsize(ckpt) if os.path.isfile(ckpt) else None,
    }
    print("  run epochs=%d wall=%.1fs" % (k, wall), flush=True)

t3, t6 = runs[3]["wall_s"], runs[6]["wall_s"]
per_epoch = (t6 - t3) / 3.0
anomaly = per_epoch <= 0
if anomaly:
    per_epoch = t3 / 3.0  # noisy fallback
one_time = t3 - 3.0 * per_epoch
total_20 = one_time + 20.0 * per_epoch

report = {
    "schema": "compose_probe_b_scale_benchmark_v1",
    "size_label": SIZE_LABEL,
    "n_genes": int(adata.n_vars),
    "n_cells": int(adata.n_obs),
    "role_counts": dict(fit_role["role_counts"]),
    "gears_epochs_registered": 20,
    "runs": runs,
    "graph_build_s_B1": float(np.mean(_graph_times)) if _graph_times else None,
    "per_epoch_s_B2": float(per_epoch),
    "one_time_s": float(one_time),
    "extrapolated_total_20ep_s": float(total_20),
    "extrapolated_total_20ep_hours": float(total_20 / 3600.0),
    "per_epoch_extrapolation_anomaly": bool(anomaly),
    "peak_host_rss_kb_B3": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    "peak_gpu_bytes_B3": max((r["peak_gpu_bytes"] or 0) for r in runs.values()) or None,
    "host_cpu_count_B4": os.cpu_count(),
    "gpu_name_B4": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "processed_input_scale_P1_P4": dict(_scale_capture),
    "note_B4": "GEARS is CPU-bound (GPU ~1%); see gpu_util.log for observed utilization.",
}
out_path = os.path.join(OUT, f"probe_b_scale_benchmark_{SIZE_LABEL}.json")
with open(out_path, "w") as fh:
    json.dump(report, fh, indent=2, sort_keys=True)
print("PROBE_B_DONE size=%s genes=%d cells=%d total_20ep~%.2fh graph=%.1fs per_epoch=%.1fs%s"
      % (SIZE_LABEL, adata.n_vars, adata.n_obs, total_20 / 3600.0,
         report["graph_build_s_B1"] or -1, per_epoch,
         " [ANOMALY: noisy per-epoch]" if anomaly else ""), flush=True)
