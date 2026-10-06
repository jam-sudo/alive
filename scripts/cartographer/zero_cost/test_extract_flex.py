"""Synthetic test: guide calls follow the registered rule; only NTC GEX lands in open/."""

import csv
import os
import subprocess
import sys
import tempfile

import h5py
import numpy as np
import scipy.sparse as sp

here = os.path.dirname(os.path.abspath(__file__))
T = tempfile.mkdtemp()
genes = [f"G{i}" for i in range(10)]
guides = [("ntc1", "Non-Targeting"), ("gA", "A"), ("gI", "Ignore")]
feat_id = genes + [g for g, _ in guides]
ftype = ["Gene Expression"] * 10 + ["CRISPR Guide Capture"] * 3
tname = [""] * 10 + [t for _, t in guides]
# cells: 0 ntc(10 umi), 1 target A (6 umi), 2 ignore (9), 3 ambiguous (5 vs 5 -> frac .5), 4 low (3 umi)
guide_umi = {0: {10: 10}, 1: {11: 6}, 2: {12: 9}, 3: {10: 5, 11: 5}, 4: {10: 3}}
rows, cols, vals = [], [], []
rng = np.random.default_rng(0)
for c in range(5):
    for g in range(10):
        rows.append(g)
        cols.append(c)
        vals.append(int(rng.integers(1, 5)))
    for r, u in guide_umi[c].items():
        rows.append(r)
        cols.append(c)
        vals.append(u)
M = sp.csc_matrix((vals, (rows, cols)), shape=(13, 5))
bcs = [
    ("ACGT" * 4) + s + "-1" for s in ["AAAAAAAA", "AAAAAAAA", "CCCCCCCC", "CCCCCCCC", "GGGGGGGG"]
]
with h5py.File(f"{T}/t.h5", "w") as f:
    g = f.create_group("matrix")
    g["barcodes"] = np.array(bcs, dtype="S")
    g["data"] = M.data
    g["indices"] = M.indices
    g["indptr"] = M.indptr
    g["shape"] = np.array(M.shape)
    fe = g.create_group("features")
    fe["id"] = np.array(feat_id, dtype="S")
    fe["feature_type"] = np.array(ftype, dtype="S")
    fe["target_gene_name"] = np.array(tname, dtype="S")
subprocess.run(
    [sys.executable, f"{here}/extract_flex.py", f"{T}/t.h5", f"{T}/open", f"{T}/sealed", "2"],
    check=True,
)
calls = list(csv.DictReader(open(f"{T}/open/guide_calls.csv")))
assert [c["call"] for c in calls] == ["ntc", "target", "ignore", "unassigned", "unassigned"], calls
assert calls[0]["batch"] == "AAAAAAAA" and calls[4]["batch"] == "GGGGGGGG"
ntc = sp.load_npz(f"{T}/open/ntc_gex.npz")
assert ntc.shape == (10, 1), ntc.shape
sealed = sum(
    sp.load_npz(os.path.join(f"{T}/sealed", x)).shape[1]
    for x in os.listdir(f"{T}/sealed")
    if x.endswith(".npz")
)
assert sealed == 4, sealed
print("SYNTHETIC FLEX TEST PASS")
