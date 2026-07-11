#!/usr/bin/env python
"""COMPOSE decision-probe prep: reduce Norman to an N-gene set at FULL cell count.

Outcome-free, dev-only, opens no seal. Differs from the smoke's ``prep_reduced.py``
in two decision-relevant ways:

  * gene ranking uses **control-cell variance on normalized control rows** (the exact
    ``response._select_hvg`` statistic: ``control_norm.var(axis=0)``) so the benchmark
    roster matches the §2 gene-universe fill rule, not dispersion;
  * ``CAP<=0`` means **no per-perturbation cap** — keep every cell so the benchmark
    measures GEARS cost at the true fit-role cell count (the whole point of Probe B).

Every perturbation gene present in ``var ∩ gene2go`` is force-included so GEARS can
compose each fit/sealed perturbation. Genes/tokens are selected with NO reference to
any perturbation response or sealed outcome.

Usage: bench_prep.py <src.h5ad> <out.h5ad> <n_genes> <cap> <ctrl_cap> <min_cells> <gene2go.pkl>
  cap<=0 / ctrl_cap<=0  -> no cap (full cells)
"""

import sys

import anndata as ad
import numpy as np
from scipy import sparse

SRC = sys.argv[1]
OUT = sys.argv[2]
N_GENES = int(sys.argv[3])
CAP = int(sys.argv[4])
CTRL_CAP = int(sys.argv[5])
MIN_CELLS = int(sys.argv[6])
GENE2GO = sys.argv[7]
SEED = 11

rng = np.random.default_rng(SEED)
a = ad.read_h5ad(SRC)  # in-memory (pod scipy backed-CSR fancy-index crash workaround)
X = a.X
X = sparse.csr_matrix(X) if not sparse.issparse(X) else X.tocsr()

# X must be raw non-negative integer counts (the fit-role artifact requires it).
probe = X[:200].toarray()
if not (np.all(probe >= 0) and np.all(probe == np.floor(probe))):
    raise SystemExit("X is not raw integer counts; cannot build a fit-role artifact")

perts = a.obs["perturbation"].astype(str).to_numpy()
var_names_all = np.asarray(a.var_names, dtype=str)

# GEARS composes a perturbation only if its gene is BOTH a measured var gene and a
# gene2go node. Drop perturbations whose gene is outside var ∩ gene2go (IER5L;
# KIAA1804=alias of MAP3K21) so every retained fit gene is GEARS-composable.
import pickle

with open(GENE2GO, "rb") as fh:
    _g2g = pickle.load(fh)
g2g_keys = set(map(str, _g2g.keys() if isinstance(_g2g, dict) else _g2g))
allowed_pert_genes = set(var_names_all) & g2g_keys


def _pert_measurable(tok: str) -> bool:
    return tok == "control" or all(g in allowed_pert_genes for g in tok.split("_"))


# --- cell keep (no cap when CAP<=0) ---------------------------------------- #
keep = []
for tok in np.unique(perts):
    if not _pert_measurable(str(tok)):
        continue
    idx = np.where(perts == tok)[0]
    if tok != "control" and len(idx) < MIN_CELLS:
        continue
    cap = CTRL_CAP if tok == "control" else CAP
    if cap > 0 and len(idx) > cap:
        idx = rng.choice(idx, size=cap, replace=False)
    keep.append(idx)
keep = np.sort(np.concatenate(keep))

# --- gene ranking by CONTROL-cell variance on normalized control rows ------ #
kept_perts = perts[keep]
ctrl_local = np.where(kept_perts == "control")[0]
Xc = X[keep][ctrl_local]  # control cells only
lib = np.asarray(Xc.sum(axis=1)).ravel()
median_library = float(np.median(lib[lib > 0]))
scale = np.divide(median_library, lib, out=np.zeros_like(lib), where=lib > 0)
Xc_norm = Xc.multiply(scale[:, None]).tocsr()
Xc_norm.data = np.log1p(Xc_norm.data)  # log1p on normalized control counts
mean = np.asarray(Xc_norm.mean(axis=0)).ravel()
sq = np.asarray(Xc_norm.multiply(Xc_norm).mean(axis=0)).ravel()
ctrl_var = np.maximum(sq - mean**2, 0.0)
# descending variance, ascending gene index tie-break (matches _select_hvg lexsort)
order = np.lexsort((np.arange(ctrl_var.size), -ctrl_var))
top = order[:N_GENES]

# Force-include every kept perturbation gene present in var.
name_to_idx = {n: i for i, n in enumerate(var_names_all)}
pert_genes = set()
for tok in np.unique(kept_perts):
    if tok == "control":
        continue
    for g in str(tok).split("_"):
        pert_genes.add(g)
pert_idx = [name_to_idx[g] for g in pert_genes if g in name_to_idx]
top = np.sort(np.unique(np.concatenate([top, np.asarray(pert_idx, dtype=np.int64)])))
print(f"gene set: {N_GENES} control-var HVG + {len(pert_idx)} pert genes -> {len(top)} total", flush=True)

sub = a[keep][:, top].copy()
sub.X = sparse.csr_matrix(sub.X)
sub.obs["perturbation"] = sub.obs["perturbation"].astype(str)
sub.obs = sub.obs[["perturbation", "nperts"]].copy()
sub.write_h5ad(OUT)

kp = sub.obs["perturbation"].astype(str).to_numpy()
print(
    f"REDUCED shape={sub.shape} cells={len(keep)} genes={len(top)} "
    f"control={int((kp == 'control').sum())} "
    f"single_cells={int((sub.obs['nperts'].astype(str) == '1').sum())} "
    f"combo_cells={int((sub.obs['nperts'].astype(str) == '2').sum())} "
    f"n_tokens={len(np.unique(kp))} median_control_library={median_library:.1f}",
    flush=True,
)
