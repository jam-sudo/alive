"""Track K G-A power through the 0a unified model (0a §6 steps 1-7).

Per simulation: (6) outer target bootstrap of the GWPS D/C pilot within P1-test/train and a δ
draw; (1) each Track K target slot takes a pilot target of its stratum, subsampled to the slot's
VIPerturb cell count; (2) labels and features at that depth (on-target/cis outputs removed);
(3) target-weighted logistic p(success | features); (4) per-stratum intercept shift lowering the
target-weighted mean by δ, floored at 0.5; (5) new successes; (7) the registered product rule on the
real Track K split (develop on D/C, E acceptance with one unit, subgroup rule (a)).

``--gb none`` omits G-B; since G-B can only stop runs, that result is an UPPER BOUND on power.
Usage: see ``--help``.
"""

import argparse
import json
import math
import multiprocessing as mp
import sys
import tomllib
from pathlib import Path

import numpy as np
import yaml
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parent))
import track_k as tk  # noqa: E402

from alive.experiment import v3_protocol as v3  # noqa: E402
from alive.experiment import v3_run as run  # noqa: E402
from alive.experiment.day8_protocol import _target_weights, split_roles  # noqa: E402

TAU, ASSAY, RESIDUAL, TRAIN_EXTRA = 0.2, 0.1, 0.1, 0.1
G = {}  # read-only state shared with forked workers


def shift_to(eta, targets, goal):
    """Intercept c with target-weighted mean of sigmoid(eta + c) == goal (bisection)."""
    w = _target_weights(targets)
    w = w / w.sum()
    lo, hi = -30.0, 30.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if (w / (1 + np.exp(-(eta + mid)))).sum() > goal:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def batch_ref(gem_cells):
    gm, pooled = G["ref_group_mean"], G["ref_pooled"]
    groups, counts = np.unique(gem_cells, return_counts=True)
    return (
        sum(gm.get(g, pooled) * c for g, c in zip(groups.tolist(), counts.tolist())) / counts.sum()
    )


def one_sim(i):
    rng = np.random.default_rng(np.random.SeedSequence([G["seed"], i]))
    pool = {s: rng.choice(ts, len(ts)) for s, ts in G["pilot_by_stratum"].items()}
    dm = G["delta_measured"][rng.integers(len(G["delta_measured"]))]
    delta = {1: dm + ASSAY + RESIDUAL, 0: dm + ASSAY + RESIDUAL + TRAIN_EXTRA}
    acc = {k: [] for k in ("X", "T", "H", "S", "z", "role", "s")}
    capped = 0
    for slot, (n_t, s, role) in G["slots"].items():
        p = pool[s][rng.integers(len(pool[s]))]
        lo, hi = G["offsets"][p], G["offsets"][p + 1]
        n = min(n_t, hi - lo)
        capped += n < n_t
        pick = lo + rng.choice(hi - lo, n, replace=False)
        rows = G["rows"][p]
        d = G["cells"][pick][:, rows].mean(0) - batch_ref(G["gem"][pick])[rows]
        h = G["h"][p][rows]
        X, sig = tk.features(
            h,
            n,
            G["audit_var"][rows],
            G["audit_mean"][rows],
            G["n_ref"],
            s,
            G["token_sd"][p][rows],
            G["set_sd"][p][rows],
            TAU,
        )
        for k, v in zip(
            acc,
            (
                X,
                np.full(len(h), slot),
                h,
                sig,
                ((np.sign(d) == np.sign(h)) & (d != 0)),
                np.full(len(h), role),
                np.full(len(h), s),
            ),
        ):
            acc[k].append(v)
    A = {k: np.concatenate(v) for k, v in acc.items()}
    if A["z"].all() or not A["z"].any():  # one class: constant model at the (clipped) observed rate
        q = min(max(float(A["z"].mean()), 1e-3), 1 - 1e-3)
        eta = np.full(len(A["z"]), math.log(q / (1 - q)))
    else:
        lr = LogisticRegression(C=1.0, max_iter=1000).fit(
            A["X"], A["z"], sample_weight=_target_weights(A["T"])
        )
        eta = A["X"] @ lr.coef_[0] + lr.intercept_[0]
    for s in (0, 1):
        m = A["s"] == s
        if not m.any():
            continue
        w = _target_weights(A["T"][m])
        mean = float((w / (1 + np.exp(-eta[m]))).sum() / w.sum())
        if mean > 0.5:
            eta[m] += shift_to(eta[m], A["T"][m], max(mean - delta[s], 0.5))
    z = (rng.random(len(eta)) < 1 / (1 + np.exp(-eta))).astype(float)
    D = A["H"] * (2 * z - 1)
    rows_by_role = {
        r: {"X": A["X"][m], "T": A["T"][m], "H": A["H"][m], "D": D[m], "S": A["S"][m]}
        for r in ("D", "C", "E")
        for m in [A["role"] == r]
    }
    rules, seed = G["rules"], G["eval_seed"]
    method = run.develop({"u": rows_by_role["D"]}, {"u": rows_by_role["C"]}, rules, seed=seed)
    res = {
        "sim": i,
        "delta_measured": float(dm),
        "capped_slots": int(capped),
        "product": method["product"],
        "c_checks": [
            {
                "candidate": c["candidate"],
                "supported_bins": len(c["supported_bins"]),
                "calibration": c["calibration"]["pass"],
                "brier": c.get("brier_vs_constant", {}).get("pass"),
                "risk_ucb": round(c["selected"]["risk_ucb"], 4),
                "use_lcb": round(c["selected"]["use_lcb"], 4),
                "distinct_win": c.get("distinct_win", {}).get("pass"),
            }
            for c in method["selection_checks"]
        ],
        "z_mean": {s: float(z[A["s"] == s].mean()) for s in (0, 1) if (A["s"] == s).any()},
    }
    if method["product"] is None:
        return res | {"verdict": "NO_PRODUCT"}
    E = rows_by_role["E"]
    p_e = run.product_probability(method, E)
    z_e = (np.sign(E["D"]) == np.sign(E["H"])).astype(float)
    acc_e = v3.evaluate_units(
        {"u": (p_e, z_e, E["T"])},
        product=method["product"],
        threshold=method["threshold"],
        b0_value=method["b0_value"],
        rules=rules,
        seed=seed,
    )
    sub = tk.subgroup_calibration(
        p_e,
        z_e,
        E["T"],
        G["groupings"],
        rules["thresholds"],
        rules["thresholds"]["alpha"],
        rules["thresholds"]["n_boot"],
        seed,
    )
    verdict = acc_e["verdict"]
    if verdict == "PASS" and not sub["pass"]:
        verdict = "FAIL_SUBGROUP"
    return res | {"verdict": verdict}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--pilot-dir", type=Path, required=True, help="pilot_D/C/REF.npz")
    ap.add_argument("--audit", type=Path, required=True, help="D8 audit_stats.npz (C_audit)")
    ap.add_argument("--pred-dir", type=Path, required=True, help="P1 predictions on GWPS controls")
    ap.add_argument("--hvg", type=Path, required=True, help="p1-hvg-table.json")
    ap.add_argument("--state-toml", type=Path, required=True, help="State fewshot k562 split toml")
    ap.add_argument("--gtf", type=Path, required=True)
    ap.add_argument(
        "--slots", type=Path, required=True, help="JSON {target: n_cells} Track K targets"
    )
    ap.add_argument("--n-ctrl", type=int, required=True, help="unit NTC count (C_ref = 0.4 of it)")
    ap.add_argument("--v31-config", type=Path, required=True)
    ap.add_argument("--delta-measured", type=Path, required=True, help="npy of δ_measured draws")
    ap.add_argument(
        "--unit-genes", type=Path, required=True, help="gene symbols measured in the unit"
    )
    ap.add_argument("--gb", choices=["none"], required=True)
    ap.add_argument("--n-sim", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261006)
    ap.add_argument("--workers", type=int, default=max(1, mp.cpu_count() - 1))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.out.exists():
        raise SystemExit("output exists (write-once)")

    cfg = yaml.safe_load(a.v31_config.read_text())
    rules = v3.resolve_rules(cfg)
    rules["min_units"] = 1  # 0a 1b S1
    test = set(tomllib.load(a.state_toml.open("rb"))["fewshot"]["replogle.k562"]["test"])
    rec = json.loads((a.pred_dir / "record.json").read_text())
    sup = {t: j for j, t in enumerate(rec["supported"])}
    H = np.load(a.pred_dir / "predicted_change.npy")
    tok, sset = np.load(a.pred_dir / "per_token_sd.npy"), np.load(a.pred_dir / "per_set_sd.npy")
    hvg = json.loads(a.hvg.read_text())["genes"]
    ids, names = [g["gene_id"] for g in hvg], [g["gene_name"] for g in hvg]
    by_id, by_name = tk.primary_tss(a.gtf)
    unit_genes = set(a.unit_genes.read_text().split())
    measured = np.array([n in unit_genes for n in names])  # outputs the unit cannot observe drop
    audit = np.load(a.audit)

    def rows_for(t):
        keep, found = tk.cis_keep(t, ids, names, by_id, by_name)
        return np.flatnonzero((np.abs(H[sup[t]]) > TAU) & keep & measured), found

    # pilot
    parts = [np.load(a.pilot_dir / f"pilot_{r}.npz", allow_pickle=True) for r in ("D", "C")]
    targets = np.concatenate([p["targets"] for p in parts])
    cells, gem, offs = [], [], [0]
    for p in parts:
        cells.append(p["X"])
        gem.append(p["gem"])
        offs += (p["offsets"][1:] + offs[-1]).tolist()
    keep_idx, prow, ph, ptok, pset = [], [], [], [], []
    for k, t in enumerate(targets):
        if t not in sup:
            continue
        r, _ = rows_for(t)
        if not len(r):
            continue
        keep_idx.append(k)
        prow.append(r)
        ph.append(H[sup[t]])
        ptok.append(tok[sup[t]])
        pset.append(sset[sup[t]])
    offsets = np.array(offs)
    ref = np.load(a.pilot_dir / "pilot_REF.npz", allow_pickle=True)
    rgem = ref["gem"]
    G.update(
        cells=np.concatenate(cells),
        gem=np.concatenate(gem),
        offsets=np.concatenate([[0], np.cumsum([offsets[k + 1] - offsets[k] for k in keep_idx])]),
        rows=prow,
        h=ph,
        token_sd=ptok,
        set_sd=pset,
        audit_var=audit["P1_var"],
        audit_mean=audit["P1_mean"],
        n_ref=0.4 * a.n_ctrl,
        ref_group_mean={g: ref["X"][rgem == g].mean(0) for g in np.unique(rgem).tolist()},
        ref_pooled=ref["X"].mean(0),
        rules=rules,
        eval_seed=int(cfg["split"]["seed"]),
        seed=a.seed,
        delta_measured=np.load(a.delta_measured),
    )
    # contiguous pilot cells for the kept targets only
    sel = np.concatenate([np.arange(offsets[k], offsets[k + 1]) for k in keep_idx])
    G["cells"], G["gem"] = G["cells"][sel], G["gem"][sel]
    kept_t = targets[keep_idx]
    G["pilot_by_stratum"] = {
        s: np.array([i for i, t in enumerate(kept_t) if (t in test) == s]) for s in (0, 1)
    }

    # Track K slots and the real split (strata: support after on-target/cis removal)
    slots_in = json.loads(a.slots.read_text())
    slot_t = sorted(t for t in slots_in if t in sup)
    support = {t: str(int(len(rows_for(t)[0]) > 0)) for t in slot_t}
    roles = split_roles(
        slot_t,
        support,
        fractions=(cfg["split"]["fractions"]["D"], cfg["split"]["fractions"]["C"]),
        seed=int(cfg["split"]["seed"]),
    )
    role_of = {t: r for r, ts in roles.items() for t in ts}
    G["slots"] = {
        t: (int(slots_in[t]), int(t in test), role_of[t]) for t in slot_t if support[t] == "1"
    }
    noise = {t: float(np.sqrt(audit["P1_var"][rows_for(t)[0]]).mean()) for t in G["slots"]}
    ter = dict(zip(noise, tk.tertiles(list(noise.values())).tolist()))
    G["groupings"] = {"p1_test": {t: v[1] for t, v in G["slots"].items()}, "noise": ter}
    tss_missing = sum(not rows_for(t)[1] for t in slot_t)

    ctx = mp.get_context("fork")
    with ctx.Pool(a.workers) as pool:
        sims = pool.map(one_sim, range(a.n_sim), chunksize=4)
    k = sum(s["verdict"] == "PASS" for s in sims)
    tally = {}
    for s in sims:
        tally[s["verdict"]] = tally.get(s["verdict"], 0) + 1
    z = 1.959964
    p = k / a.n_sim
    half = z * math.sqrt(p * (1 - p) / a.n_sim)
    summary = {
        "kind": "UPPER_BOUND_no_GB" if a.gb == "none" else "G-A",
        "p_pass": p,
        "p_pass_normal_ci95": [p - half, p + half],
        "tally": tally,
        "n_slots": len(G["slots"]),
        "roles": {r: sum(v[2] == r for v in G["slots"].values()) for r in "DCE"},
        "slots_by_stratum": {s: sum(v[1] == s for v in G["slots"].values()) for s in (0, 1)},
        "pilot_targets_by_stratum": {s: len(v) for s, v in G["pilot_by_stratum"].items()},
        "targets_without_tss": tss_missing,
        "n_sim": a.n_sim,
        "seed": a.seed,
        "delta_measured_draws": len(G["delta_measured"]),
        "outputs_unmeasured_in_unit": int((~measured).sum()),
    }
    a.out.mkdir(parents=True)
    (a.out / "power.json").write_text(
        json.dumps({"summary": summary, "sims": sims}, indent=1, default=str)
    )
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
