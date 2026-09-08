"""Headline pair 집합(sealed_double_unseen, n=22)의 **실제** 유전자 공유 구조를 잰다.

읽는 것은 `adata.obs['perturbation']` 라벨뿐이다. `.X` 는 열지 않는다 —
sealed outcome 을 읽지 않으며 seal 을 건드리지 않는다(CLAUDE.md#seal, spec §2.2 는
eligibility/split 을 outcome-independent 로 못박는다). backed='r' 로 연다.

재현이 맞는지 **커밋된 evidence 로 알려진 정답 대조**를 한다:
  real_norman_phi_rank_report.json → singles 105 · pairs 131 · z-universe genes 73
                                     calibration genes 44 · roles 41/22/68
다섯 값이 전부 맞으면 이 재현은 pod 이 돌린 것과 같은 split 이다.
"""

from __future__ import annotations

import json

import anndata as ad
import numpy as np

from alive.compose.split import build_pair_split
from alive.data.norman import eligible_genes, eligible_pairs, parse_labels

H5AD = "/Users/jam/ALIVE-data/norman/NormanWeissman2019_filtered.h5ad"
PERT_KEY, CONTROL, SEP = "perturbation", "control", "_"
MIN_CELLS_GENE = MIN_CELLS_PAIR = 50
CAL_FRACTION, SPLIT_SEED = 0.6, 11
EXPECTED = {
    "n_singles": 105,
    "n_pairs": 131,
    "n_genes_in_pairs": 73,
    "n_calibration_genes": 44,
    "n_combo_calibration": 41,
    "n_sealed_double_unseen": 22,
    "n_sealed_single_unseen": 68,
}

adata = ad.read_h5ad(H5AD, backed="r")
labels = np.asarray(adata.obs[PERT_KEY].values, dtype=object)
adata.file.close()

singles, doubles, control = parse_labels(labels, control_token=CONTROL, combo_sep=SEP)
genes_ok = eligible_genes(singles, min_cells=MIN_CELLS_GENE, available_feature_ids=set(singles))
pairs = eligible_pairs(doubles, set(genes_ok), min_cells=MIN_CELLS_PAIR)
split = build_pair_split(pairs, seed=SPLIT_SEED, calibration_fraction=CAL_FRACTION)

genes_in_pairs = sorted({g for p in pairs for g in p})
got = {
    "n_singles": len(genes_ok),
    "n_pairs": len(pairs),
    "n_genes_in_pairs": len(genes_in_pairs),
    "n_calibration_genes": len(split.combo_genes),
    "n_combo_calibration": len(split.combo_calibration),
    "n_sealed_double_unseen": len(split.sealed_double_unseen),
    "n_sealed_single_unseen": len(split.sealed_single_unseen),
}
print("=== 알려진 정답 대조 (커밋된 evidence) ===")
ok = True
for k, want in EXPECTED.items():
    hit = got[k] == want
    ok &= hit
    print(f"  {'OK ' if hit else 'MISMATCH'} {k:26s} 기대={want:4d}  실측={got[k]:4d}")
print(f"재현 일치: {ok}\n")
if not ok:
    raise SystemExit("재현이 커밋된 evidence 와 다르다 — 구조 수치를 신뢰할 수 없다.")


def structure(name, plist):
    deg: dict[str, int] = {}
    for a, b in plist:
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    n = len(plist)
    total = n * (n - 1) // 2
    shared = sum(d * (d - 1) // 2 for d in deg.values())
    # 유전자를 하나도 공유하지 않는 pair 가 몇 개인가 (완전히 독립인 행)
    isolated = sum(1 for a, b in plist if deg[a] == 1 and deg[b] == 1)
    d = np.array(sorted(deg.values()))
    return {
        "role": name,
        "n_pairs": n,
        "n_genes_used": len(deg),
        "mean_degree": float(d.mean()),
        "max_degree": int(d.max()),
        "degree_histogram": {int(v): int((d == v).sum()) for v in np.unique(d)},
        "shared_gene_pair_fraction": shared / total if total else 0.0,
        "n_shared_gene_pair_couples": int(shared),
        "n_pairs_sharing_no_gene": isolated,
    }


rows = [
    structure("sealed_double_unseen (HEADLINE)", split.sealed_double_unseen),
    structure("sealed_single_unseen", split.sealed_single_unseen),
    structure("combo_calibration", split.combo_calibration),
]
print("=== 실제 유전자 공유 구조 ===")
for r in rows:
    print(f"\n{r['role']}  n_pairs={r['n_pairs']}")
    print(f"  distinct genes      : {r['n_genes_used']}")
    print(f"  mean / max degree   : {r['mean_degree']:.2f} / {r['max_degree']}")
    print(f"  degree histogram    : {r['degree_histogram']}")
    print(
        f"  유전자 공유하는 pair 쌍: {r['n_shared_gene_pair_couples']} "
        f"/ {r['n_pairs'] * (r['n_pairs'] - 1) // 2} = {r['shared_gene_pair_fraction']:.3f}"
    )
    print(f"  아무 유전자도 안 겹치는 pair: {r['n_pairs_sharing_no_gene']}")
print()
print(json.dumps({"known_answer_match": ok, "rows": rows}, indent=1))
