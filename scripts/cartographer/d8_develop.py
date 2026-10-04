"""CART-K562-D8-v1 development fit on roles D and C, producing the frozen method.

For each predictor and co-primary stratum (all outputs; predicted non-negligible): builds
outcome-free features, registered joint-event labels, fits ALIVE-L on D, isotonic on C, and
fixes the operating point on C. Writes a JSON method whose hash must be recorded before E.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import yaml

from alive.experiment.day8_protocol import (
    evaluate_acceptance,
    fit_trust_model,
    joint_event,
    noise_analytic_probability,
    operating_point,
    predict_trust,
)

EXPOSURE_GROUPS = (
    "base_train",
    "conformal_calibration",
    "method_development",
    "sealed_evaluation",
    "day6_outside_registered_eligible",
)
PRIMARY_EXCLUDED_GROUP = "absent_from_day6_source_labels"


def build_features(h, n_cells, noise_var, ctrl_mean, n_ref, exposure, tau, extra=None):
    """Outcome-free trust features for one target's outputs (rows = genes).

    Returns ``(features, sigma)``; ``sigma`` is the analytic null SD of the observed change
    (target mean vs reference) used by feature and by baseline B1.
    """
    h = np.asarray(h, float)
    sigma = np.sqrt(noise_var * (1.0 / n_cells + 1.0 / n_ref))
    onehot = [1.0 if exposure == g else 0.0 for g in EXPOSURE_GROUPS]
    cols = [
        np.abs(h),
        (h > tau).astype(float),
        (h < -tau).astype(float),
        np.full(len(h), np.log(n_cells)),
        sigma,
        ctrl_mean,
        *(np.full(len(h), v) for v in onehot),
    ]
    if extra is not None:
        cols.extend(np.asarray(e, float) for e in extra)
    return np.column_stack(cols), sigma


def main() -> None:  # pragma: no cover - real-data entry point
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--prepare", type=Path, required=True)
    parser.add_argument("--observed", type=Path, required=True, help="dir with observed_D/C npz")
    parser.add_argument(
        "--audit-stats", type=Path, required=True, help="npz noise_var/mean per axis"
    )
    parser.add_argument("--p1", type=Path, required=True)
    parser.add_argument("--p2", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text())
    tau, eps = cfg["events"]["tau"], cfg["events"]["epsilon"]
    acc = cfg["acceptance"]
    prepare = json.loads((args.prepare / "prepare.json").read_text())
    strata = {t: s.split("|")[0] for t, s in prepare["strata"].items()}
    cells = prepare["cells"]
    stats = np.load(args.audit_stats)
    n_ref = int(stats["n_ref"])
    preds = {}
    for key, d in (("P1", args.p1), ("P2", args.p2)):
        rec = json.loads((d / "record.json").read_text())
        preds[key] = {
            "index": {t: i for i, t in enumerate(rec["supported"])},
            "h": np.load(d / "predicted_change.npy"),
        }
    preds["P1"]["token_sd"] = np.load(args.p1 / "per_token_sd.npy")
    preds["P1"]["set_sd"] = np.load(args.p1 / "per_set_sd.npy")
    obs = {r: np.load(args.observed / f"observed_{r}.npz") for r in ("D", "C")}
    method = {"protocol_id": cfg["protocol_id"], "tau": tau, "epsilon": eps, "predictors": {}}
    diagnostics = {}
    for key in ("P1", "P2"):
        P = preds[key]
        rows = {}
        for role in ("D", "C"):
            X, Z, T, H, S = [], [], [], [], []
            for i, t in enumerate(obs[role]["targets"].tolist()):
                if t not in P["index"] or strata[t] == PRIMARY_EXCLUDED_GROUP:
                    continue
                j = P["index"][t]
                h, d = P["h"][j], obs[role][key][i]
                extra = [P["token_sd"][j], P["set_sd"][j]] if key == "P1" else None
                x, sigma = build_features(
                    h,
                    cells[t],
                    stats[f"{key}_var"],
                    stats[f"{key}_mean"],
                    n_ref,
                    strata[t],
                    tau,
                    extra,
                )
                X.append(x)
                Z.append(joint_event(h, d, tau=tau, epsilon=eps)["z_joint"].astype(float))
                T.append(np.full(len(h), t))
                H.append(h)
                S.append(sigma)
            rows[role] = [np.concatenate(v) for v in (X, Z, T, H, S)]
        entry = {}
        for stratum in acc["co_primary_strata"]:
            sel = {
                r: (np.abs(rows[r][3]) > tau)
                if stratum == "predicted_non_negligible"
                else slice(None)
                for r in rows
            }
            (xd, zd, td, hd, _), (xc, zc, tc, hc, sc) = (
                [a[sel[r]] for a in rows[r]] for r in ("D", "C")
            )
            params = fit_trust_model(xd, zd, td, xc, zc, tc)
            pc = predict_trust(params, xc)
            threshold = operating_point(pc, zc, tc, budget=acc["operating_budget_on_C"])
            b0 = float(zd.mean())
            entry[stratum] = {
                "params": params,
                "threshold": threshold,
                "b0_constant": b0,
                "n_rows": {"D": int(len(zd)), "C": int(len(zc))},
                "n_targets": {"D": int(len(np.unique(td))), "C": int(len(np.unique(tc)))},
            }
            diagnostics[f"{key}/{stratum}"] = evaluate_acceptance(
                p=pc,
                z=zc,
                targets=tc,
                baseline_constant=b0,
                comparator=noise_analytic_probability(hc, sc, tau=tau, epsilon=eps),
                threshold=threshold,
                thresholds={
                    "calibration_margin": acc["calibration_margin"],
                    "risk_ucb": acc["risk_ucb_max"],
                    "use_lcb": acc["use_lcb_min"],
                },
                n_boot=acc["n_boot"],
                alpha=acc["alpha"],
                seed=cfg["split"]["seed"],
            )
        method["predictors"][key] = entry
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "method.json").write_text(json.dumps(method, indent=1, sort_keys=True))
    (args.out / "development_diagnostics_C.json").write_text(
        json.dumps(diagnostics, indent=1, default=str)
    )
    digest = hashlib.sha256((args.out / "method.json").read_bytes()).hexdigest()
    print("method sha256", digest)
    for k, v in diagnostics.items():
        print(
            k,
            v["verdict"],
            "cal",
            v["calibration"]["pass"],
            "sel",
            v["selected"],
            "comp",
            v["comparative"],
        )


if __name__ == "__main__":
    main()
