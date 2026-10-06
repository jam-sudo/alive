"""Track K (CART-K562-VIP-X1) definitions shared by the power model and the run (0a §3, §7)."""

import gzip

import numpy as np

from alive.experiment import v3_protocol as v3
from alive.experiment.day8_protocol import _boot_means, _per_target_mean


def features(h, n_cells, noise_var, ctrl_mean, n_ref, p1_test, token_sd, set_sd, tau):
    """V3.1 ALIVE-L features with ``exposure_stratum`` replaced by one P1-test indicator."""
    h = np.asarray(h, float)
    sigma = np.sqrt(noise_var * (1.0 / n_cells + 1.0 / n_ref))
    X = np.column_stack(
        [
            np.abs(h),
            h > tau,
            h < -tau,
            np.full(len(h), np.log(n_cells)),
            sigma,
            ctrl_mean,
            np.full(len(h), float(p1_test)),
            token_sd,
            set_sd,
        ]
    ).astype(float)
    return X, sigma


def primary_tss(gtf_gz):
    """{gene_id: (chrom, pos)} and {gene_name: (chrom, pos)}: MANE_Select, else Ensembl_canonical."""
    best = {}
    with gzip.open(gtf_gz, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.split("\t")
            if f[2] != "transcript":
                continue
            a = f[8]
            pri = 0 if 'tag "MANE_Select"' in a else (1 if 'tag "Ensembl_canonical"' in a else None)
            if pri is None:
                continue
            gid = a.split('gene_id "')[1].split('"')[0].split(".")[0]
            name = a.split('gene_name "')[1].split('"')[0]
            pos = int(f[3]) if f[6] == "+" else int(f[4])
            if gid not in best or pri < best[gid][3]:
                best[gid] = (f[0], pos, name, pri)
    by_id = {g: (c, p) for g, (c, p, _, _) in best.items()}
    by_name = {}
    for c, p, n, _ in best.values():
        by_name.setdefault(n, (c, p))
    return by_id, by_name


def cis_keep(target, axis_ids, axis_names, by_id, by_name, window=1_000_000):
    """Outputs kept in the main event: not the target gene, not within +-window of its TSS.

    Returns (keep mask, whether the target TSS was found). Without a TSS only the exact
    symbol is removed.
    """
    keep = np.array([n != target for n in axis_names])
    t = by_name.get(target)
    if t is None:
        return keep, False
    for i, g in enumerate(axis_ids):
        c = by_id.get(g)
        if c is not None and c[0] == t[0] and abs(c[1] - t[1]) <= window:
            keep[i] = False
    return keep, True


def tertiles(values):
    """Outcome-free noise stratum per target: 0/1/2 by the 1/3 and 2/3 quantiles."""
    v = np.asarray(values, float)
    return np.digitize(v, np.quantile(v, [1 / 3, 2 / 3]), right=True)


def subgroup_calibration(p, z, targets, groupings, thresholds, alpha, n_boot, seed, min_n=30):
    """Subgroup rule (a): every subgroup with >= ``min_n`` targets passes the calibration margin.

    ``groupings`` maps a name to {target: level}. Alpha is Bonferroni-split over every supported
    bin of every evaluated subgroup. Subgroups below ``min_n`` are reported as not established.
    """
    p, z, targets = np.asarray(p, float), np.asarray(z, float), np.asarray(targets)
    subsets = []
    for gname, lv in groupings.items():
        lab = np.array([lv[t] for t in targets])
        for level in np.unique(lab):
            m = lab == level
            if len(np.unique(targets[m])) >= min_n:
                subsets.append((f"{gname}={level}", m))
    sup = {k: v3.supported_bins(p[m], targets[m], thresholds) for k, m in subsets}
    fam = max(1, sum(len(b) for b in sup.values()))
    a = alpha / fam
    out, ok = {}, True
    for i, (k, m) in enumerate(subsets):
        pm, zm, tm = p[m], z[m], targets[m]
        uniq, inv = np.unique(tm, return_inverse=True)
        bins = v3._bin_index(pm, thresholds["bins"])
        res = {}
        for b in sup[k]:
            per = _per_target_mean(zm - pm, inv, len(uniq), bins == b)
            lo, hi = np.quantile(
                _boot_means(per, n_boot, seed + 10_000 * (i + 1) + b), [a / 2, 1 - a / 2]
            )
            res[b] = [float(lo), float(hi)]
            ok &= -thresholds["calibration_margin"] <= lo and hi <= thresholds["calibration_margin"]
        out[k] = res
    return {"pass": bool(ok), "alpha_per_interval": a, "subgroups": out}
