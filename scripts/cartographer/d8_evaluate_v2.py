"""CART-K562-D8-v2 single sealed evaluation of role E (sign and magnitude events, P1-P3).

Before any E access: verifies every frozen file hash and the manifest checksum, and refuses if the
protocol-global seal audit already holds any record (E is shared with the closed v1). Then calls
``evaluate_sealed_once(run_id="CART-K562-D8-v2")`` for E targets supported by some predictor.
"""

from __future__ import annotations

import argparse
import importlib.util as spec_util
import json
from pathlib import Path


def _load(name: str, path: Path):
    s = spec_util.spec_from_file_location(name, path)
    m = spec_util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def audit_is_empty(path: Path) -> bool:
    """True if the seal audit file is absent or contains no record."""
    return not path.exists() or not path.read_text().strip()


def main() -> None:  # pragma: no cover - real-data entry point
    import numpy as np
    import yaml

    from alive.data.manifest import SplitManifest
    from alive.data.outcome_store import ReplogleOutcomeStore
    from alive.experiment.day8_protocol import (
        _boot_means,
        _per_target_mean,
        attenuation_slope,
        evaluate_acceptance,
        joint_event,
        predict_trust,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--h5ad", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.freeze.read_text())
    ev1 = _load("d8_evaluate", Path(__file__).parent / "d8_evaluate.py")
    ev1.verify_freeze(record, args.root)
    p = {k: args.root / v for k, v in record["paths"].items()}
    cfg = yaml.safe_load(p["config_v1"].read_text())
    cfg2 = yaml.safe_load(p["config"].read_text())
    method = json.loads(p["method"].read_text())
    prepare = json.loads((p["prepare"] / "prepare.json").read_text())
    manifest = SplitManifest.read(p["prepare"] / "manifest.json")
    if (
        manifest.checksum != record["manifest_checksum"]
        or manifest.checksum != cfg2["manifest_checksum"]
    ):
        raise ValueError("manifest does not match freeze record / registered config")
    audit = p["prepare"] / "seal-audit.jsonl"
    if not audit_is_empty(audit):
        raise ValueError("protocol-global seal audit is not empty; E was already opened")

    obs_mod = _load("d8_observe", p["d8_observe"])
    dev = _load("d8_develop", p["d8_develop"])
    v2 = _load("d8_develop_v2", p["d8_develop_v2"])
    pdirs = {"P1": (p["P1"], "P1"), "P2": (p["P2"], "P2"), "P3": (p["P3"], "P1")}
    supported = set()
    for key, (d, _) in pdirs.items():
        supported |= set(json.loads((d / "record.json").read_text())["supported"])
    targets = [t for t in manifest.ids_for("sealed_evaluation") if t in supported]
    index, gem = obs_mod.build_index(args.h5ad, cfg, prepare)
    store = ReplogleOutcomeStore(index, args.h5ad, manifest, audit_path=audit)
    pops = store.evaluate_sealed_once(cfg2["sealing"]["run_id"], targets)  # the single opening

    axes = {k: list(v) for k, v in json.loads(p["axes"].read_text()).items()}
    ref = obs_mod.reference_matrices(cfg, p["controls"], gem, axes)
    observed = {a: {} for a in axes}
    for t in targets:
        groups = gem[index.cell_indices(t)]
        for a, cols in axes.items():
            observed[a][t], _ = obs_mod.observed_change(
                pops[t].cells, groups, ref[a][0], ref[a][1], cols
            )
    stats = np.load(p["audit_stats"])
    strata = {t: s.split("|")[0] for t, s in prepare["strata"].items()}
    tau, eps, acc = cfg["events"]["tau"], cfg["events"]["epsilon"], cfg["acceptance"]
    thresholds = {
        "calibration_margin": acc["calibration_margin"],
        "risk_ucb": acc["risk_ucb_max"],
        "use_lcb": acc["use_lcb_min"],
    }
    seed = cfg["split"]["seed"]
    report = {
        "protocol_id": cfg2["protocol_id"],
        "n_E_targets_read": len(targets),
        "n_E_targets_roster": len(manifest.ids_for("sealed_evaluation")),
        "sealed_access_count": store.sealed_access_count,
        "results": {},
    }

    def rate_ci(values, tgt):
        uniq, inv = np.unique(tgt, return_inverse=True)
        per = _per_target_mean(values.astype(float), inv, len(uniq))
        lo, hi = np.quantile(_boot_means(per, acc["n_boot"], seed), [0.025, 0.975])
        return {
            "rate": float(np.nanmean(per)),
            "ci95": [float(lo), float(hi)],
            "n_targets": int(len(uniq)),
        }

    for key, (pdir, axis) in pdirs.items():
        rows = v2.predictor_rows(
            dev,
            pdir,
            key,
            axis,
            targets,
            lambda i, t, a=axis: observed[a][t],
            prepare,
            strata,
            stats,
            tau,
        )
        X, T, H, D, S = rows
        for event in ("sign", "magnitude"):
            frozen = method["predictors"][key][event]
            z = v2.event_labels(rows, event, eps)
            comp = v2.b1_sign(H, S) if event == "sign" else v2.b1_magnitude(S, eps)
            report["results"][f"{key}/{event}"] = evaluate_acceptance(
                p=predict_trust(frozen["params"], X),
                z=z,
                targets=T,
                baseline_constant=frozen["b0_constant"],
                comparator=comp,
                threshold=frozen["threshold"],
                thresholds=thresholds,
                n_boot=acc["n_boot"],
                alpha=acc["alpha"],
                seed=seed,
            ) | {"descriptive_rate": rate_ci(z, T)}
        joint = joint_event(H, D, tau=tau, epsilon=eps)["z_joint"]
        report["results"][f"{key}/descriptive"] = {
            "n_outputs": int(len(H)),
            "joint_rate_secondary": rate_ci(joint, T),
            "attenuation": attenuation_slope(H, D, T, n_boot=acc["n_boot"], seed=seed, alpha=0.05),
            "mean_abs_error": float(np.abs(H - D).mean()),
            "no_change_mean_abs_error": float(np.abs(D).mean()),
        }
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "evaluation.json").write_text(json.dumps(report, indent=1, default=str))
    for k, v in report["results"].items():
        print(
            k,
            v.get("verdict", ""),
            json.dumps(v.get("descriptive_rate") or v.get("attenuation"), default=str),
        )


if __name__ == "__main__":
    main()
