"""빠진 통로: **method-differential** 유전자 효과.

앞선 측정은 유전자 효과를 "모든 method 공통 pair 난이도"로만 넣었다. theta 는 비율이라
공통 배수는 대부분 상쇄되고, 남은 주변분산 증가는 i.i.d. bootstrap 이 그대로 잡는다 —
그래서 그 설계는 하락을 **보여줄 수 없었다**(참/거짓 출력이 같은 검사).

여기서는 method 마다 **독립인** 유전자 효과 H^m 을 넣는다. 유전자 a 를 어떤 method 는
잘 맞추고 다른 method 는 못 맞춘다. 이 성분은 d_i = e_C,i - e_L1,i 안에 상쇄되지 않고
남고, a 를 포함한 모든 pair 에 걸쳐 상관된다.

    e[m,i] = mu[m] * exp( sgs*(G_a+G_b)/sqrt2            # 공통(상쇄되는) 통로
                        + sgd*(H^m_a+H^m_b)/sqrt2        # method-differential 통로
                        + sp*P_i + se*E[m,i] - corr )

대조군(필수): **공유가 0인** 완전매칭을 같은 sgd 로 함께 돌린다. sgd 는 분산도 늘리므로,
실제 그래프에서 coverage 가 떨어져도 매칭에서 똑같이 떨어진다면 원인은 공유가 아니다.
"""
from __future__ import annotations

import json
import time

import anndata as ad
import numpy as np

from alive.compose.split import build_pair_split
from alive.data.norman import eligible_genes, eligible_pairs, parse_labels
from alive.compose.inference2 import simultaneous_theta_bounds

import pairdep_probe as P

COMPARATORS = P.COMPARATORS
MU_C, MU_H, THETA_TRUE = P.MU_COMP, P.MU_HEADLINE, P.THETA_TRUE
METHODS = ["__headline__"] + COMPARATORS


def coverage_diff(pairs, n_genes, sgs, sgd, sp, se, n_trials, base_seed):
    pa = np.array([p[0] for p in pairs])
    pb = np.array([p[1] for p in pairs])
    n = len(pairs)
    corr = 0.5 * (sgs**2 + sgd**2 + sp**2 + se**2)
    hits, widths = 0, []
    for t in range(n_trials):
        rng = np.random.default_rng(base_seed + t)
        g_shared = rng.standard_normal(n_genes)
        common = sgs * (g_shared[pa] + g_shared[pb]) / np.sqrt(2.0) \
            + sp * rng.standard_normal(n)
        vals = {}
        for m in METHODS:
            h = rng.standard_normal(n_genes)          # method 마다 독립인 유전자 효과
            mu = MU_H if m == "__headline__" else MU_C[m]
            vals[m] = mu * np.exp(
                common + sgd * (h[pa] + h[pb]) / np.sqrt(2.0)
                + se * rng.standard_normal(n) - corr
            )
        res = simultaneous_theta_bounds(
            headline_errors=vals["__headline__"],
            comparator_errors={c: vals[c] for c in COMPARATORS},
            comparators=COMPARATORS, confidence=P.CONFIDENCE,
            n_replicates=P.REPLICATES, seed=7_000_000 + t,
        )
        widths.append(res.band_halfwidth)
        if all(res.lower[c] <= THETA_TRUE[c] for c in COMPARATORS):
            hits += 1
    p = hits / n_trials
    se_ = (p * (1 - p) / n_trials) ** 0.5
    return {"coverage": p, "ci95": [max(0.0, p - 1.96 * se_), min(1.0, p + 1.96 * se_)],
            "mean_band_halfwidth": float(np.mean(widths))}


adata = ad.read_h5ad("/Users/jam/ALIVE-data/norman/NormanWeissman2019_filtered.h5ad", backed="r")
labels = np.asarray(adata.obs["perturbation"].values, dtype=object)
adata.file.close()
s, d, _ = parse_labels(labels, control_token="control", combo_sep="_")
gk = eligible_genes(s, min_cells=50, available_feature_ids=set(s))
split = build_pair_split(eligible_pairs(d, set(gk), min_cells=50),
                         seed=11, calibration_fraction=0.6)
real = split.sealed_double_unseen
gidx = {g: i for i, g in enumerate(sorted({g for p in real for g in p}))}
REAL = [(gidx[a], gidx[b]) for a, b in real]
MATCH = P.matching(22)

ARMS = [("REAL_22p_21g", REAL, len(gidx)), ("CONTROL_matching_no_sharing", MATCH, 44)]
n_trials, sgs, sp, se = 1500, 0.60, 0.35, 0.45
out = {"n_trials": n_trials, "sigma_shared": sgs, "rows": []}
for name, pl, ng in ARMS:
    st = P.degree_stats(pl, ng)
    for sgd in (0.0, 0.30, 0.60, 0.90):
        t0 = time.time()
        cov = coverage_diff(pl, ng, sgs, sgd, sp, se, n_trials, 555001)
        row = {"arm": name, "sigma_gene_diff": sgd, **st, **cov,
               "secs": round(time.time() - t0, 1)}
        out["rows"].append(row)
        print(f"{name:28s} sgd={sgd:.2f} deg={st['mean_degree']:.2f} "
              f"share={st['shared_gene_pair_fraction']:.3f}  "
              f"coverage={cov['coverage']:.4f} "
              f"[{cov['ci95'][0]:.4f},{cov['ci95'][1]:.4f}]  "
              f"q={cov['mean_band_halfwidth']:.4f}  {row['secs']}s", flush=True)
print(json.dumps(out, indent=1))
