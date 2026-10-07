"""Control-cell h5ad for ``pie prep controls_only=true`` (0a §3, 0b §5): C_input cells only.

Roles come from the 0a hash rule: u = top 64 bits of sha256(f"CART-0a-ctrl-20261006|{dataset}|{barcode}")
/ 2^64; u < 0.4 C_ref, < 0.8 C_input, else C_audit. Expression is PIE's scale: CP10k over all genes of
the unit, natural log1p. obs: cell_line=K562, gene=non-targeting (PIE ``replogle`` prep overlay).
Usage: pie_controls.py csc <open_dir> <dataset> <out.h5ad>   (CSC binary from extract_seurat.R)
"""

import hashlib
import json
import sys
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sp


def role(dataset: str, barcode: str) -> str:
    h = hashlib.sha256(f"CART-0a-ctrl-20261006|{dataset}|{barcode}".encode()).digest()
    u = int.from_bytes(h[:8], "big") / 2**64
    return "C_ref" if u < 0.4 else ("C_input" if u < 0.8 else "C_audit")


def load_csc(d: Path) -> sp.csc_matrix:
    g, c = map(int, (d / "counts_dim.txt").read_text().split())
    return sp.csc_matrix(
        (
            np.fromfile(d / "counts_x.float64"),
            np.fromfile(d / "counts_i.int32", np.int32),
            np.fromfile(d / "counts_p.int32", np.int32),
        ),
        shape=(g, c),
    )


def control_h5ad(counts_gc: sp.csc_matrix, genes, barcodes, dataset: str) -> ad.AnnData:
    roles = np.array([role(dataset, b) for b in barcodes])
    keep = np.flatnonzero(roles == "C_input")
    X = counts_gc[:, keep].T.tocsr().astype(np.float64)
    depth = np.asarray(X.sum(1)).ravel()
    if (depth <= 0).any():
        raise ValueError("zero-depth control cell")
    X = sp.diags(1e4 / depth) @ X
    X.data = np.log1p(X.data)
    obs = pd.DataFrame(
        {"cell_line": "K562", "gene": "non-targeting"}, index=np.asarray(barcodes)[keep]
    )
    return ad.AnnData(X=X.astype(np.float32).tocsr(), obs=obs, var=pd.DataFrame(index=list(genes)))


if __name__ == "__main__":
    kind, src, dataset, out = sys.argv[1:5]
    assert kind == "csc"
    src = Path(src)
    import csv

    meta = list(csv.DictReader(open(src / "meta.csv")))
    genes = (src / "genes.txt").read_text().split()
    a = control_h5ad(load_csc(src), genes, [r["barcode"] for r in meta], dataset)
    a.write_h5ad(out)
    counts = {r: 0 for r in ("C_ref", "C_input", "C_audit")}
    for r in meta:
        counts[role(dataset, r["barcode"])] += 1
    print(json.dumps({"dataset": dataset, "roles": counts, "c_input_written": a.n_obs}))
