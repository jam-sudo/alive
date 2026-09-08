"""stats.pair-gene-dependence 판정 — 감사의 '논리적 증거'를 실측으로 바꾼다.

감사는 "shared-gene 의존성이 있으면 pair-i.i.d. bootstrap 의 유효표본수와 max-deviation
quantile 이 잘못될 수 있다"고 **논증**했다. 측정은 없었다. 여기서 실제 등록 추정량을
그대로 돌려 simultaneous coverage 를 잰다.

실제 구조(커밋된 activation evidence 에서 측정, 인용 아님):
  docs/activation-evidence/compose/real_norman_phi_rank_report.json
    n_eligible_genes 105 · n_calibration_genes 44 · n_eligible_pairs 131
    n_sealed_double_unseen = 22   <- headline regime 의 실제 n
  configs/compose_k562_v1_phase2.yaml
    resampling_unit perturbation_pair · family_confidence 0.95
    bootstrap_replicates 10000 · comparator_family 5개

생성 모형 (gene random effect):
    e[m,i] = mu[m] * exp( sg*(G[a_i]+G[b_i])/sqrt(2) + sp*P[i] + se*E[m,i] - 0.5*(sg^2+sp^2+se^2) )
  G 는 **유전자**마다 하나 — 같은 유전자를 쓰는 pair 들이 이걸 공유한다. sg=0 이면
  구조가 있어도 의존성은 0 이다(= 두 번째 대조군, 기제를 분리한다).
"""

from __future__ import annotations

import itertools
import json
import sys
import time

import numpy as np

from alive.compose.inference2 import simultaneous_theta_bounds

COMPARATORS = ["additive", "gears", "cpa", "id_only", "l3_symmetric_mlp"]
MU_HEADLINE = 1.0
MU_COMP = {"additive": 1.30, "gears": 1.20, "cpa": 1.25, "id_only": 1.60, "l3_symmetric_mlp": 1.15}
THETA_TRUE = {c: (MU_COMP[c] - MU_HEADLINE) / MU_COMP[c] for c in COMPARATORS}
N_PAIRS = 22  # 실측값 (sealed_double_unseen)
CONFIDENCE = 0.95  # 등록값
REPLICATES = 10000  # 등록값 — 줄이지 않는다


def matching(n_edges: int) -> list[tuple[int, int]]:
    """degree 1 — 유전자 공유가 **하나도 없다**. 비-공허성 대조군."""
    return [(2 * i, 2 * i + 1) for i in range(n_edges)]


def cycle(g: int) -> list[tuple[int, int]]:
    """degree 2 — 각 유전자가 정확히 두 pair 에 나온다."""
    return [(i, (i + 1) % g) for i in range(g)]


def circulant(g: int, offsets: tuple[int, ...]) -> list[tuple[int, int]]:
    """degree 2*len(offsets) — 정규 그래프."""
    out = []
    for off in offsets:
        for i in range(g):
            a, b = i, (i + off) % g
            out.append((min(a, b), max(a, b)))
    return sorted(set(out))


def dense_subset(g: int, n_edges: int, seed: int) -> list[tuple[int, int]]:
    """작은 유전자 풀에서 n_edges 개를 결정론적으로 고른다 (거의 완전그래프)."""
    allp = list(itertools.combinations(range(g), 2))
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(allp))[:n_edges]
    return sorted(allp[i] for i in idx)


def degree_stats(pairs, n_genes):
    deg = np.zeros(n_genes, dtype=int)
    for a, b in pairs:
        deg[a] += 1
        deg[b] += 1
    used = deg[deg > 0]
    # 같은 유전자를 공유하는 pair 쌍의 개수 = sum_g C(deg_g, 2)
    shared = int(sum(d * (d - 1) // 2 for d in used))
    total = N_PAIRS * (N_PAIRS - 1) // 2
    return {
        "n_genes_used": int(len(used)),
        "mean_degree": float(used.mean()),
        "max_degree": int(used.max()),
        "shared_gene_pair_fraction": shared / total,
    }


def coverage(pairs, n_genes, sigma_gene, sigma_pair, sigma_meth, n_trials, base_seed):
    pa = np.array([p[0] for p in pairs])
    pb = np.array([p[1] for p in pairs])
    n = len(pairs)
    var_corr = 0.5 * (sigma_gene**2 + sigma_pair**2 + sigma_meth**2)
    hits = 0
    widths = []
    for t in range(n_trials):
        rng = np.random.default_rng(base_seed + t)
        gene = rng.standard_normal(n_genes)
        pair_eff = rng.standard_normal(n)
        shared = sigma_gene * (gene[pa] + gene[pb]) / np.sqrt(2.0) + sigma_pair * pair_eff
        head = MU_HEADLINE * np.exp(shared + sigma_meth * rng.standard_normal(n) - var_corr)
        comp = {
            c: MU_COMP[c] * np.exp(shared + sigma_meth * rng.standard_normal(n) - var_corr)
            for c in COMPARATORS
        }
        res = simultaneous_theta_bounds(
            headline_errors=head,
            comparator_errors=comp,
            comparators=COMPARATORS,
            confidence=CONFIDENCE,
            n_replicates=REPLICATES,
            seed=7_000_000 + t,
        )
        widths.append(res.band_halfwidth)
        if all(res.lower[c] <= THETA_TRUE[c] for c in COMPARATORS):
            hits += 1
    p = hits / n_trials
    se = (p * (1 - p) / n_trials) ** 0.5
    return {
        "coverage": p,
        "se": se,
        "ci95": [max(0.0, p - 1.96 * se), min(1.0, p + 1.96 * se)],
        "mean_band_halfwidth": float(np.mean(widths)),
    }


ARMS = [
    ("A_matching_d1", matching(22), 44),
    ("B_g16_d2.75", dense_subset(16, 22, seed=3), 16),
    ("C_cycle_d2", cycle(22), 22),
    ("D_circulant_d4", circulant(11, (1, 2)), 11),
    ("E_dense_d5.5", dense_subset(8, 22, seed=5), 8),
]

if __name__ == "__main__":
    n_trials = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    sigma_pair, sigma_meth = 0.35, 0.45
    out = {
        "n_pairs": N_PAIRS,
        "confidence": CONFIDENCE,
        "replicates": REPLICATES,
        "n_trials": n_trials,
        "theta_true": THETA_TRUE,
        "sigma_pair": sigma_pair,
        "sigma_meth": sigma_meth,
        "arms": [],
    }
    for name, pairs, g in ARMS:
        assert len(pairs) == N_PAIRS, (name, len(pairs))
        st = degree_stats(pairs, g)
        for sigma_gene in (0.0, 0.60, 0.90):
            t0 = time.time()
            cov = coverage(pairs, g, sigma_gene, sigma_pair, sigma_meth, n_trials, 12345)
            # 유전자 하나를 공유하는 두 pair 의 log-error 급내상관 — sigma_gene 을
            # 해석 가능한 값으로 바꿔 둔다(척도 자체는 임의).
            icc = (sigma_gene**2 / 2) / (sigma_gene**2 + sigma_pair**2 + sigma_meth**2)
            row = {
                "arm": name,
                "sigma_gene": sigma_gene,
                "icc_one_shared_gene": icc,
                **st,
                **cov,
                "secs": round(time.time() - t0, 1),
            }
            out["arms"].append(row)
            print(
                f"{name:16s} sg={sigma_gene:.2f} icc={icc:.3f} deg={st['mean_degree']:.2f} "
                f"share={st['shared_gene_pair_fraction']:.3f}  "
                f"coverage={cov['coverage']:.4f} "
                f"[{cov['ci95'][0]:.4f},{cov['ci95'][1]:.4f}]  "
                f"q={cov['mean_band_halfwidth']:.4f}  {row['secs']}s",
                flush=True,
            )
    print(json.dumps(out, indent=1))
