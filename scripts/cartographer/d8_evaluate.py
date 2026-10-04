"""CART-K562-D8-v1 single sealed evaluation of role E against the frozen method.

Before any E access, verifies the freeze record: method, config, manifest and every code file
hash. Only then calls ``evaluate_sealed_once`` with ``run_id = protocol_id``, so E opens at most
once per protocol and audit path. Any mismatch aborts before the seal is touched.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util as spec
import json
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_freeze(record: dict, root: Path) -> None:
    """Raise unless every frozen file still has its recorded SHA256."""
    bad = [name for name, want in record["files"].items() if sha256(root / name) != want]
    if bad:
        raise ValueError(f"freeze violation, changed files: {bad}")


def main() -> None:  # pragma: no cover - real-data entry point
    import numpy as np
    import yaml

    from alive.data.manifest import SplitManifest
    from alive.data.outcome_store import ReplogleOutcomeStore
    from alive.experiment.day8_protocol import (
        evaluate_acceptance,
        joint_event,
        noise_analytic_probability,
        predict_trust,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, required=True, help="freeze record JSON")
    parser.add_argument("--root", type=Path, required=True, help="base for relative file paths")
    parser.add_argument("--h5ad", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.freeze.read_text())
    verify_freeze(record, args.root)
    p = {k: args.root / v for k, v in record["paths"].items()}
    cfg = yaml.safe_load(p["config"].read_text())
    method = json.loads(p["method"].read_text())
    prepare = json.loads((p["prepare"] / "prepare.json").read_text())
    manifest = SplitManifest.read(p["prepare"] / "manifest.json")
    if manifest.checksum != record["manifest_checksum"]:
        raise ValueError("manifest changed after freeze")

    def load(name):
        s = spec.spec_from_file_location(name, p[name])
        m = spec.module_from_spec(s)
        s.loader.exec_module(m)
        return m

    obs_mod, dev_mod = load("d8_observe"), load("d8_develop")
    index, gem = obs_mod.build_index(args.h5ad, cfg, prepare)
    store = ReplogleOutcomeStore(
        index, args.h5ad, manifest, audit_path=p["prepare"] / "seal-audit.jsonl"
    )
    supported = set()
    for key in ("P1", "P2"):
        supported |= set(json.loads((p[key] / "record.json").read_text())["supported"])
    # Only targets some predictor supports; unsupported E outcomes are never materialized.
    targets = [t for t in manifest.ids_for("sealed_evaluation") if t in supported]
    pops = store.evaluate_sealed_once(cfg["sealing"]["run_id"], targets)  # single audited opening
    axes = {k: list(v) for k, v in json.loads(p["axes"].read_text()).items()}
    stats = np.load(p["audit_stats"])
    ref = obs_mod.reference_matrices(cfg, p["controls"], gem, axes)
    tau, eps, acc = cfg["events"]["tau"], cfg["events"]["epsilon"], cfg["acceptance"]
    strata = {t: s.split("|")[0] for t, s in prepare["strata"].items()}
    report = {
        "protocol_id": cfg["protocol_id"],
        "n_E_targets_read": len(targets),
        "n_E_targets_roster": len(manifest.ids_for("sealed_evaluation")),
        "results": {},
    }
    for key in ("P1", "P2"):
        rec = json.loads((p[key] / "record.json").read_text())
        idx = {t: i for i, t in enumerate(rec["supported"])}
        H = np.load(p[key] / "predicted_change.npy")
        extra_src = (
            (np.load(p[key] / "per_token_sd.npy"), np.load(p[key] / "per_set_sd.npy"))
            if key == "P1"
            else None
        )
        cols = {"X": [], "Z": [], "T": [], "H": [], "S": [], "E": [], "A": []}
        for t in targets:
            if t not in idx or strata[t] == dev_mod.PRIMARY_EXCLUDED_GROUP:
                continue
            j = idx[t]
            d, _ = obs_mod.observed_change(
                pops[t].cells, gem[index.cell_indices(t)], ref[key][0], ref[key][1], axes[key]
            )
            extra = [extra_src[0][j], extra_src[1][j]] if extra_src else None
            x, sigma = dev_mod.build_features(
                H[j],
                prepare["cells"][t],
                stats[f"{key}_var"],
                stats[f"{key}_mean"],
                int(stats["n_ref"]),
                strata[t],
                tau,
                extra,
            )
            cols["X"].append(x)
            cols["Z"].append(joint_event(H[j], d, tau=tau, epsilon=eps)["z_joint"].astype(float))
            cols["T"].append(np.full(len(d), t))
            cols["H"].append(H[j])
            cols["S"].append(sigma)
            cols["E"].append(np.abs(H[j] - d))
            cols["A"].append(np.abs(d))
        X, Z, T, Hh, S, E, A = (np.concatenate(v) for v in cols.values())
        for stratum, frozen in method["predictors"][key].items():
            m = np.abs(Hh) > tau if stratum == "predicted_non_negligible" else np.ones(len(Z), bool)
            report["results"][f"{key}/{stratum}"] = evaluate_acceptance(
                p=predict_trust(frozen["params"], X[m]),
                z=Z[m],
                targets=T[m],
                baseline_constant=frozen["b0_constant"],
                comparator=noise_analytic_probability(Hh[m], S[m], tau=tau, epsilon=eps),
                threshold=frozen["threshold"],
                thresholds={
                    "calibration_margin": acc["calibration_margin"],
                    "risk_ucb": acc["risk_ucb_max"],
                    "use_lcb": acc["use_lcb_min"],
                },
                n_boot=acc["n_boot"],
                alpha=acc["alpha"],
                seed=cfg["split"]["seed"],
            ) | {
                "mean_abs_error": float(E[m].mean()),
                "no_change_mean_abs_error_diag": float(A[m].mean()),
            }
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "evaluation.json").write_text(json.dumps(report, indent=1, default=str))
    for k, v in report["results"].items():
        print(k, v["verdict"])


if __name__ == "__main__":
    main()
