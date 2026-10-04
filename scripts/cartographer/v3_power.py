"""CART-K562-V3 power table (synthetic, outcome-free) through the registered decision rules.

Design candidates, scenarios, interim blank values and the selection criterion are fixed in
``docs/superpowers/plans/2026-10-04-cart-v3-power-design.md`` before this runs; the script
refuses to run unless that file has the expected SHA256. Only the support structure (number of
P1 predicted-non-negligible outputs per roster target) is read from data, and it is
prediction-only. Only B0 is simulated as a product (design doc section 5).
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import multiprocessing as mp
import subprocess
from pathlib import Path

import numpy as np
import yaml

from alive.experiment import v3_protocol as v3
from alive.experiment.day8_protocol import split_roles

# Mirrors of the fixed design doc (sections 2-4, 6). Changing any value is a new run id.
INTERIM = {
    "strata": "p1_support_indicator",
    "b0_policy": None,  # per design
    "b0_weighting": "target_equal",
    "c_selection_unit": "pooled",
    "operating_point": "exhaustive_largest_coverage",
    "e_alpha": "bonferroni_all_intervals",
    "single_unit_eligibility": "evaluate_where_eligible",
    "predictions_per_unit": "shared",
    "verdict_aggregation": "fail_first",
    "no_candidate": "no_product_terminal",
}
DESIGNS = list(
    itertools.product((240, 480, 960), (2, 3), ((0.4, 0.2), (0.3, 0.3)), ("c_gate", "accept_all"))
)
REGISTERED = (240, 2, (0.4, 0.2))
MUS, SDS, RHOS = (0.83, 0.87, 0.89, 0.91, 0.93), (0.185, 0.25), (0, 1)
SENSITIVITY = ({"shift": 0.03, "drop": 0.0}, {"shift": 0.0, "drop": 0.10})
TAU, BASE_SEED = 0.2, 20261004
CRIT = {"mu": 0.91, "sd": 0.185, "power": 0.80, "bad_mu": 0.83, "bad_max": 0.05}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def beta_params(mu: float, sd: float) -> tuple[float, float]:
    k = mu * (1 - mu) / sd**2 - 1
    if k <= 0:
        raise ValueError(f"no Beta with mean {mu} and SD {sd}")
    return mu * k, (1 - mu) * k


def _rows(sel, m, rate_u, rng):
    idx = np.repeat(sel, m[sel])
    return (rng.random(len(idx)) < rate_u[idx]).astype(float), idx


def simulate(counts, design, scen, rules, rng) -> tuple[str, str | None]:
    """One synthetic V3 experiment through C selection and E acceptance; returns the outcome."""
    n, n_units, frac, _ = design
    m = counts if n == len(counts) else rng.choice(counts, n)
    ids = np.arange(n)
    strata = {i: str(int(m[i] > 0)) for i in ids}
    roles = split_roles(list(ids), strata, fractions=frac, seed=int(rng.integers(2**31)))
    sel = {r: np.array([i for i in roles[r] if m[i] > 0], int) for r in ("D", "C", "E")}
    a, b = beta_params(scen["mu"], scen["sd"])
    rate = (
        np.repeat(rng.beta(a, b, n)[:, None], n_units, 1)
        if scen["rho"] == 1
        else rng.beta(a, b, (n, n_units))
    )
    rate[:, -1] = np.clip(rate[:, -1] - scen["shift"], 0.0, 1.0)
    elig = rng.random((n, n_units)) >= scen["drop"]

    def pooled(role):
        parts = [_rows(sel[role][elig[sel[role], u]], m, rate[:, u], rng) for u in range(n_units)]
        return np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts])

    seed = int(rng.integers(2**31))
    z_d, t_d = pooled("D")
    b0 = v3.b0_constant(z_d, t_d, weighting=rules["blanks"]["b0_weighting"])
    z_c, t_c = pooled("C")
    pick = v3.select_product(
        [("B0_constant", np.full(len(z_c), b0))], z_c, t_c, b0_value=b0, rules=rules, seed=seed
    )
    if pick["product"] is None:
        chk = pick["checks"][0]
        reason = (
            "unsupported"
            if not chk["supported_bins"]
            else "gate"
            if math.isinf(chk["selected"]["threshold"])
            else "calibration"
            if not chk["calibration"]["pass"]
            else "risk_use"
        )
        return "B0_REJECTED_ON_C", reason
    units = {}
    for u in range(n_units):
        z, t = _rows(sel["E"][elig[sel["E"], u]], m, rate[:, u], rng)
        units[f"u{u}"] = (np.full(len(z), b0), z, t)
    res = v3.evaluate_units(
        units,
        product="B0_constant",
        threshold=pick["threshold"],
        b0_value=b0,
        rules=rules,
        seed=seed + 7,
    )
    return res["verdict"], None


def wilson(k: int, n: int, z: float = 1.959964) -> list[float]:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def run_cell(job):
    idx, counts, design, scen, base_rules, sims = job
    rules = json.loads(json.dumps(base_rules))
    rules["blanks"]["b0_policy"] = design[3]
    rng = np.random.default_rng(np.random.SeedSequence([BASE_SEED, idx]))
    tally, reasons = {}, {}
    for _ in range(sims):
        out, why = simulate(counts, design, scen, rules, rng)
        tally[out] = tally.get(out, 0) + 1
        if why:
            reasons[why] = reasons.get(why, 0) + 1
    k = tally.get("PASS", 0)
    return {
        "cell": idx,
        "design": {"N": design[0], "T": design[1], "DC": list(design[2]), "b0_policy": design[3]},
        "scenario": scen,
        "sims": sims,
        "outcomes": tally,
        "b0_rejected_reasons": reasons,
        "p_pass": k / sims,
        "p_pass_ci": wilson(k, sims),
    }


def adequacy(cells, policy):
    """Design doc section 6, applied within one B0 policy."""
    by = {}
    for c in cells:
        d = c["design"]
        if d["b0_policy"] == policy and c["scenario"]["shift"] == 0 and c["scenario"]["drop"] == 0:
            by.setdefault((d["N"], d["T"], tuple(d["DC"])), []).append(c)
    rows = []
    for key, cs in sorted(by.items()):
        ref = [
            c for c in cs if (c["scenario"]["mu"], c["scenario"]["sd"]) == (CRIT["mu"], CRIT["sd"])
        ]
        bad = [c for c in cs if c["scenario"]["mu"] == CRIT["bad_mu"]]
        p_ref = min(c["p_pass"] for c in ref)
        half = max((c["p_pass_ci"][1] - c["p_pass_ci"][0]) / 2 for c in ref)
        p_bad = max(c["p_pass"] for c in bad)
        ok = p_ref >= CRIT["power"] and p_bad <= CRIT["bad_max"]
        rows.append(
            {
                "N": key[0],
                "T": key[1],
                "DC": list(key[2]),
                "p_pass_ref_min_rho": p_ref,
                "p_pass_known_bad_max": p_bad,
                "adequate": ok,
                "borderline": abs(p_ref - CRIT["power"]) <= half,
            }
        )
    adequate = [r for r in rows if r["adequate"]]
    adequate.sort(key=lambda r: (r["N"] * r["T"], r["DC"] != list(REGISTERED[2])))
    return rows, (adequate[0] if adequate else None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--design-doc", type=Path, required=True)
    ap.add_argument("--design-sha256", required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--roster", type=Path, required=True)
    ap.add_argument("--predictions", type=Path, required=True, help="P1 full-01 directory")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sims", type=int, required=True)
    ap.add_argument("--workers", type=int, default=max(1, mp.cpu_count() - 1))
    ap.add_argument("--only", help="confirmation run of one design: N,T,D,C,b0_policy")
    ap.add_argument("--run-definition", type=Path, help="required with --only")
    ap.add_argument("--run-definition-sha256", help="required with --only")
    args = ap.parse_args()

    if sha256(args.design_doc) != args.design_sha256:
        raise SystemExit("design doc SHA256 mismatch: the fixed design changed")
    designs = DESIGNS
    if args.only:
        if not args.run_definition or sha256(args.run_definition) != args.run_definition_sha256:
            raise SystemExit("--only needs a run definition with matching SHA256")
        n, t, fd, fc, policy = args.only.split(",")
        designs = [(int(n), int(t), (float(fd), float(fc)), policy)]
        if designs[0] not in DESIGNS:
            raise SystemExit(f"{designs[0]} is not a design candidate of the fixed design doc")
    cfg = yaml.safe_load(args.config.read_text())
    if sha256(args.roster) != cfg["targets"]["roster_sha256"]:
        raise SystemExit("roster SHA256 differs from the registered config")
    rec = json.loads((args.predictions / "record.json").read_text())
    pred = args.predictions / "predicted_change.npy"
    if sha256(pred) != rec["outputs_sha256"]["predicted_change.npy"]:
        raise SystemExit("prediction SHA256 differs from its record")
    args.out.mkdir(parents=True, exist_ok=False)  # write-once run directory

    h = np.load(pred)
    row = {t: i for i, t in enumerate(rec["supported"])}
    roster = [x["target"] for x in json.loads(args.roster.read_text())["targets"]]
    counts = np.array([(np.abs(h[row[t]]) > TAU).sum() for t in roster], int)
    rules = v3.resolve_rules({**cfg, "v3_1_rules": {**INTERIM, "b0_policy": "c_gate"}})

    jobs = []
    for d in designs:
        for mu, sd, rho in itertools.product(MUS, SDS, RHOS):
            jobs.append((d, {"mu": mu, "sd": sd, "rho": rho, "shift": 0.0, "drop": 0.0}))
    n_primary = len(jobs)
    with mp.Pool(args.workers) as pool:
        cells = pool.map(
            run_cell, [(i, counts, d, s, rules, args.sims) for i, (d, s) in enumerate(jobs)]
        )
        picks = {p: adequacy(cells, p) for p in sorted({d[3] for d in designs})}
        sens_designs = set(designs) if args.only else {(*REGISTERED, p) for p in picks}
        for p, (_, best) in picks.items():
            if best and not args.only:
                sens_designs.add((best["N"], best["T"], tuple(best["DC"]), p))
        sens = [
            (d, {"mu": mu, "sd": CRIT["sd"], "rho": rho, **v})
            for d in sorted(sens_designs)
            for mu in (CRIT["mu"], CRIT["bad_mu"])
            for rho in RHOS
            for v in SENSITIVITY
        ]
        cells += pool.map(
            run_cell,
            [(n_primary + i, counts, d, s, rules, args.sims) for i, (d, s) in enumerate(sens)],
        )

    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    code = [Path(v3.__file__), Path(__file__)]
    result = {
        "run_id": args.out.name,
        "design_doc_sha256": args.design_sha256,
        "only": args.only,
        "run_definition_sha256": args.run_definition_sha256,
        "inputs": {
            "config_sha256": sha256(args.config),
            "roster_sha256": sha256(args.roster),
            "predictions_sha256": sha256(pred),
        },
        "code_sha256": {p.name: sha256(p) for p in code},
        "git_head": head.strip(),
        "git_note": "code files above are uncommitted; their SHA256 is the identity",
        "sims_per_cell": args.sims,
        "support": {"targets_with_output": int((counts > 0).sum()), "n": len(counts)},
        "interim_blanks": rules["blanks"] | {"b0_policy": "per design"},
        "criterion": CRIT,
        "adequacy": {p: {"table": rows, "candidate": best} for p, (rows, best) in picks.items()},
        "cells": cells,
    }
    (args.out / "power.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result["adequacy"], indent=1))


if __name__ == "__main__":
    main()
