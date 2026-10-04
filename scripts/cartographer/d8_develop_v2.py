"""CART-K562-D8-v2 (DRAFT) development on roles D and C: separate sign and magnitude events.

Unregistered feasibility development; never touches role E. Reuses the v1 feature builder,
roles, thresholds and ALIVE-L specification unchanged (v2 draft spec, 2026-09-28).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import yaml

from alive.experiment.day8_protocol import (
    attenuation_slope,
    evaluate_acceptance,
    fit_trust_model,
    operating_point,
    predict_trust,
    sign_event,
)


def _phi(x):
    return 0.5 * (1.0 + np.vectorize(math.erf)(np.asarray(x, float) / math.sqrt(2.0)))


def b1_sign(h, sigma):
    """P(sign(d) = sign(h)) if d ~ N(h, sigma^2): Phi(|h| / sigma)."""
    return _phi(np.abs(h) / sigma)


def b1_magnitude(sigma, epsilon):
    """P(|d - h| <= epsilon) if d ~ N(h, sigma^2): 2 Phi(epsilon / sigma) - 1."""
    return 2.0 * _phi(epsilon / np.asarray(sigma, float)) - 1.0


def predictor_rows(dev, pdir, key, axis, targets, observed, prepare, strata, stats, tau):
    """Rows for predicted-non-negligible outputs of one predictor over ``targets``.

    ``observed(i, t)`` returns the observed change on the predictor's axis. Returns
    ``[X, T, H, D, S]`` (features, targets, predicted, observed, analytic sigma).
    """
    rec = json.loads((pdir / "record.json").read_text())
    idx = {t: i for i, t in enumerate(rec["supported"])}
    H = np.load(pdir / "predicted_change.npy")
    extra_src = (
        (np.load(pdir / "per_token_sd.npy"), np.load(pdir / "per_set_sd.npy"))
        if key in ("P1", "P3")
        else None
    )
    X, T, Hs, Ds, S = [], [], [], [], []
    for i, t in enumerate(targets):
        if t not in idx or strata[t] == dev.PRIMARY_EXCLUDED_GROUP:
            continue
        j = idx[t]
        m = np.abs(H[j]) > tau
        if not m.any():
            continue
        extra = [extra_src[0][j][m], extra_src[1][j][m]] if extra_src else None
        x, sigma = dev.build_features(
            H[j][m],
            prepare["cells"][t],
            stats[f"{axis}_var"][m],
            stats[f"{axis}_mean"][m],
            int(stats["n_ref"]),
            strata[t],
            tau,
            extra,
        )
        X.append(x)
        T.append(np.full(m.sum(), t))
        Hs.append(H[j][m])
        Ds.append(observed(i, t)[m])
        S.append(sigma)
    return [np.concatenate(v) for v in (X, T, Hs, Ds, S)]


def event_labels(rows, event: str, epsilon: float) -> np.ndarray:
    """Registered v2 labels on predictor rows: ``sign`` or ``magnitude``."""
    h, d = rows[2], rows[3]
    return (sign_event(h, d) if event == "sign" else np.abs(h - d) <= epsilon).astype(float)


def main() -> None:  # pragma: no cover - real-data entry point
    parser = argparse.ArgumentParser(description=__doc__)
    for a in ("config", "prepare", "observed", "audit_stats", "p1", "p2", "out"):
        parser.add_argument(f"--{a.replace('_', '-')}", type=Path, required=True)
    parser.add_argument("--p3", type=Path, help="optional P3 (ST-SE) dir; scored on the P1 axis")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        "d8_develop", Path(__file__).parent / "d8_develop.py"
    )
    dev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev)
    cfg = yaml.safe_load(args.config.read_text())
    tau, eps, acc = cfg["events"]["tau"], cfg["events"]["epsilon"], cfg["acceptance"]
    prepare = json.loads((args.prepare / "prepare.json").read_text())
    strata = {t: s.split("|")[0] for t, s in prepare["strata"].items()}
    stats = np.load(args.audit_stats)
    obs = {r: np.load(args.observed / f"observed_{r}.npz") for r in ("D", "C")}
    thresholds = {
        "calibration_margin": acc["calibration_margin"],
        "risk_ucb": acc["risk_ucb_max"],
        "use_lcb": acc["use_lcb_min"],
    }
    method, diag = {"draft": "CART-K562-D8-v2", "predictors": {}}, {}
    predictors = [("P1", args.p1, "P1"), ("P2", args.p2, "P2")]
    if args.p3 is not None:
        predictors.append(("P3", args.p3, "P1"))
    for key, pdir, axis in predictors:
        rows = {
            role: predictor_rows(
                dev,
                pdir,
                key,
                axis,
                obs[role]["targets"].tolist(),
                lambda i, t, role=role: obs[role][axis][i],
                prepare,
                strata,
                stats,
                tau,
            )
            for role in ("D", "C")
        }
        entry = {}
        for event in ("sign", "magnitude"):
            z = {r: event_labels(rows[r], event, eps) for r in rows}
            params = fit_trust_model(
                rows["D"][0], z["D"], rows["D"][1], rows["C"][0], z["C"], rows["C"][1]
            )
            pc = predict_trust(params, rows["C"][0])
            t = operating_point(pc, z["C"], rows["C"][1], budget=acc["operating_budget_on_C"])
            comp = (
                b1_sign(rows["C"][2], rows["C"][4])
                if event == "sign"
                else b1_magnitude(rows["C"][4], eps)
            )
            entry[event] = {"params": params, "threshold": t, "b0_constant": float(z["D"].mean())}
            diag[f"{key}/{event}"] = evaluate_acceptance(
                p=pc,
                z=z["C"],
                targets=rows["C"][1],
                baseline_constant=float(z["D"].mean()),
                comparator=comp,
                threshold=t,
                thresholds=thresholds,
                n_boot=acc["n_boot"],
                alpha=acc["alpha"],
                seed=cfg["split"]["seed"],
            ) | {"D_rate": float(z["D"].mean())}
        diag[f"{key}/attenuation_C"] = attenuation_slope(
            rows["C"][2],
            rows["C"][3],
            rows["C"][1],
            n_boot=acc["n_boot"],
            seed=cfg["split"]["seed"],
            alpha=acc["alpha"],
        )
        method["predictors"][key] = entry
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "method_v2_draft.json").write_text(json.dumps(method, indent=1, sort_keys=True))
    (args.out / "development_diagnostics_v2_C.json").write_text(
        json.dumps(diag, indent=1, default=str)
    )
    for k, v in diag.items():
        if "attenuation" in k:
            print(
                k,
                {
                    kk: (round(vv, 3) if isinstance(vv, float) else [round(x, 3) for x in vv])
                    for kk, vv in v.items()
                },
            )
        else:
            print(
                k,
                v["verdict"],
                "D_rate",
                round(v["D_rate"], 3),
                "cal",
                v["calibration"]["pass"],
                "sel",
                {
                    kk: (round(vv, 3) if isinstance(vv, float) else vv)
                    for kk, vv in v["selected"].items()
                },
                "comp",
                v["comparative"],
            )


if __name__ == "__main__":
    main()
