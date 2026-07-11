#!/usr/bin/env python
"""Build the fit-role artifact + worker payload from an in-memory reduced AnnData.

Parameterized copy of the smoke's ``build_payload_inmem.py``: calls the committed
``build_dev_smoke_payload`` (which excludes sealed rows from the artifact + payload —
the leakage boundary is unchanged) with size-specific n_hvg / n_calibration / n_sealed.
In-memory load only (pod scipy backed-CSR fancy-index crash workaround); the reduced
set is non-sealed Norman, so relaxing the never-materialize defense is irrelevant.

Usage: build_payload.py <reduced.h5ad> <work_dir> <artifact_path> <manifest_out>
                        <n_hvg> <n_calibration> <n_sealed>
"""

import importlib.util
import json
import sys

import anndata as ad

BUILDER = "/workspace/ALIVE_git/scripts/compose/build_dev_smoke_payload.py"
REDUCED, WORK, ART, MANIFEST_OUT = sys.argv[1:5]
N_HVG, N_CALIB, N_SEALED = (int(x) for x in sys.argv[5:8])

_spec = importlib.util.spec_from_file_location("_bdsp", BUILDER)
_m = importlib.util.module_from_spec(_spec)
sys.modules["_bdsp"] = _m
_spec.loader.exec_module(_m)

manifest = _m.build_dev_smoke_payload(
    ad.read_h5ad(REDUCED),
    out_dir=WORK,
    artifact_path=ART,
    control_token="control",
    combo_sep="_",
    n_hvg=N_HVG,
    pca_dim=50,
    seed=11,
    n_sealed=N_SEALED,
    n_calibration=N_CALIB,
)
with open(MANIFEST_OUT, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, sort_keys=True)
print("BUILD_OK n_hvg=%d n_calibration=%d n_sealed=%d" % (N_HVG, N_CALIB, N_SEALED), flush=True)
