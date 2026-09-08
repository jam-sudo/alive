"""같은 coverage 측정을, 합성 사다리가 아니라 **실제 headline pair 그래프** 위에서.

구조는 pair_structure.py 가 커밋된 evidence 와 7/7 일치로 재현한 그것이다
(sealed_double_unseen: 22 pairs / 21 genes / mean degree 2.10 / 독립 행 0개).
유전자 이름은 쓰지 않는다 — 인접 구조만 쓴다.
"""

from __future__ import annotations

import json
import time

import anndata as ad
import numpy as np
import pairdep_probe as P  # 같은 생성모형·같은 등록 추정량을 재사용한다

from alive.compose.split import build_pair_split
from alive.data.norman import eligible_genes, eligible_pairs, parse_labels

H5AD = "/Users/jam/ALIVE-data/norman/NormanWeissman2019_filtered.h5ad"
adata = ad.read_h5ad(H5AD, backed="r")
labels = np.asarray(adata.obs["perturbation"].values, dtype=object)
adata.file.close()
singles, doubles, _ = parse_labels(labels, control_token="control", combo_sep="_")
genes_ok = eligible_genes(singles, min_cells=50, available_feature_ids=set(singles))
pairs = eligible_pairs(doubles, set(genes_ok), min_cells=50)
split = build_pair_split(pairs, seed=11, calibration_fraction=0.6)

real = split.sealed_double_unseen
assert len(real) == 22, len(real)
gidx = {g: i for i, g in enumerate(sorted({g for p in real for g in p}))}
edges = [(gidx[a], gidx[b]) for a, b in real]
n_genes = len(gidx)
st = P.degree_stats(edges, n_genes)
print(
    f"실제 headline 그래프: n_pairs={len(edges)} genes={n_genes} "
    f"mean_deg={st['mean_degree']:.2f} share={st['shared_gene_pair_fraction']:.3f}",
    flush=True,
)

n_trials = 1500
sigma_pair, sigma_meth = 0.35, 0.45
out = {"structure": st, "n_trials": n_trials, "rows": []}
for sigma_gene in (0.0, 0.30, 0.60, 0.90, 1.20):
    t0 = time.time()
    cov = P.coverage(edges, n_genes, sigma_gene, sigma_pair, sigma_meth, n_trials, 990001)
    icc = (sigma_gene**2 / 2) / (sigma_gene**2 + sigma_pair**2 + sigma_meth**2)
    row = {
        "sigma_gene": sigma_gene,
        "icc_one_shared_gene": icc,
        **cov,
        "secs": round(time.time() - t0, 1),
    }
    out["rows"].append(row)
    print(
        f"REAL sg={sigma_gene:.2f} icc={icc:.3f}  coverage={cov['coverage']:.4f} "
        f"[{cov['ci95'][0]:.4f},{cov['ci95'][1]:.4f}]  q={cov['mean_band_halfwidth']:.4f} "
        f"{row['secs']}s",
        flush=True,
    )
print(json.dumps(out, indent=1))
