"""Seal-safe extraction of the 10x K562 Flex filtered h5 (0a §5, step-1 record B).

Guide call (registered): top guide UMI >= 5 and >= 80% of the cell's guide UMIs.
Outputs:
  open/   NTC cells: GEX counts (npz CSC, genes x cells), barcodes, batch, nCount; guide_calls.csv (all cells,
          guide metadata only: barcode, top_guide, top_umi, frac, call, target, batch)
  sealed/ target cells and Ignore/unassigned cells: GEX counts in chunks; nothing is summarised here.
Usage: extract_flex.py <h5> <open_dir> <sealed_dir> [chunk]
"""

import csv
import os
import sys

import h5py
import numpy as np
import scipy.sparse as sp

H5, OPEN, SEALED = sys.argv[1:4]
CHUNK = int(sys.argv[4]) if len(sys.argv) > 4 else 50000
os.makedirs(OPEN, exist_ok=True)
os.makedirs(SEALED, exist_ok=True)
f = h5py.File(H5, "r")
m = f["matrix"]
ft = m["features"]["feature_type"][:].astype(str)
gex = np.where(ft == "Gene Expression")[0]
crispr = np.where(ft == "CRISPR Guide Capture")[0]
gid = m["features"]["id"][:].astype(str)
tgt = m["features"]["target_gene_name"][:].astype(str)
bcs = m["barcodes"][:].astype(str)
n_feat, n_cell = m["shape"][:]
indptr = m["indptr"][:]
np.savetxt(os.path.join(OPEN, "genes.txt"), gid[gex], fmt="%s")
is_crispr = np.zeros(n_feat, bool)
is_crispr[crispr] = True
gex_pos = -np.ones(n_feat, int)
gex_pos[gex] = np.arange(len(gex))

calls = open(os.path.join(OPEN, "guide_calls.csv"), "w", newline="")
w = csv.writer(calls)
w.writerow(["barcode", "top_guide", "top_umi", "frac", "call", "target", "batch"])
ntc_blocks, ntc_bc, ntc_batch = [], [], []
counts = {"ntc": 0, "target": 0, "ignore": 0, "unassigned": 0}
for start in range(0, n_cell, CHUNK):
    end = min(start + CHUNK, n_cell)
    lo, hi = indptr[start], indptr[end]
    idx = m["indices"][lo:hi]
    dat = m["data"][lo:hi]
    ip = indptr[start : end + 1] - lo
    sealed_cols, sealed_bc = [], []
    for j in range(end - start):
        a, b = ip[j], ip[j + 1]
        r, v = idx[a:b], dat[a:b]
        cm = is_crispr[r]
        bc = bcs[start + j]
        batch = bc.split("-")[0][16:24]
        gr, gv = r[cm], v[cm]
        top_g, top_u, frac, call, target = "", 0, 0.0, "unassigned", ""
        if gv.size and gv.sum() > 0:
            k = int(np.argmax(gv))
            top_g, top_u = gid[gr[k]], int(gv[k])
            frac = float(gv[k] / gv.sum())
            if top_u >= 5 and frac >= 0.8:
                target = tgt[gr[k]]
                call = (
                    "ntc"
                    if target == "Non-Targeting"
                    else ("ignore" if target == "Ignore" else "target")
                )
        counts[call] += 1
        w.writerow(
            [bc, top_g, top_u, f"{frac:.4f}", call, target if call != "unassigned" else "", batch]
        )
        gm = ~cm
        col = sp.csc_matrix((v[gm], (gex_pos[r[gm]], np.zeros(gm.sum(), int))), shape=(len(gex), 1))
        if call == "ntc":
            ntc_blocks.append(col)
            ntc_bc.append(bc)
            ntc_batch.append(batch)
        else:
            sealed_cols.append(col)
            sealed_bc.append(bc)
    if sealed_cols:
        sp.save_npz(os.path.join(SEALED, f"gex_{start:08d}.npz"), sp.hstack(sealed_cols).tocsc())
        np.savetxt(os.path.join(SEALED, f"barcodes_{start:08d}.txt"), sealed_bc, fmt="%s")
calls.close()
ntc = sp.hstack(ntc_blocks).tocsc() if ntc_blocks else sp.csc_matrix((len(gex), 0))
sp.save_npz(os.path.join(OPEN, "ntc_gex.npz"), ntc)
with open(os.path.join(OPEN, "ntc_meta.csv"), "w", newline="") as fh:
    ww = csv.writer(fh)
    ww.writerow(["barcode", "batch", "nCount"])
    for bc, bt, nc in zip(ntc_bc, ntc_batch, np.asarray(ntc.sum(0)).ravel()):
        ww.writerow([bc, bt, int(nc)])
print("cells", int(n_cell), counts)
