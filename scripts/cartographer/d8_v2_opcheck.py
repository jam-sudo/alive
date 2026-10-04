"""CART-K562-D8-v2 erratum check: as-run vs registered operating point on role C only.

Follows a definition fixed before running (its SHA256 is required). Uses frozen ALIVE-L
parameters; no refit, no upstream rerun, and role E is never read.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import yaml

from alive.experiment import v3_protocol
from alive.experiment.day8_protocol import operating_point, predict_trust, target_weighted_rate

HERE = Path(__file__).parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _at(p, z, t, threshold) -> dict:
    keep = p >= threshold
    return {
        "threshold": threshold,
        "use_rate_C": target_weighted_rate(keep.astype(float), t),
        "failure_rate_C": target_weighted_rate(1.0 - z[keep], t[keep]) if keep.any() else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freeze", type=Path, required=True)
    ap.add_argument("--observed-c", type=Path, required=True)
    ap.add_argument("--observed-c-sha256", required=True)
    ap.add_argument("--definition", type=Path, required=True)
    ap.add_argument("--definition-sha256", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if _sha(args.definition) != args.definition_sha256:
        raise SystemExit("definition changed")
    if _sha(args.observed_c) != args.observed_c_sha256:
        raise SystemExit("observed_C changed")
    freeze = json.loads(args.freeze.read_text())
    for rel, digest in freeze["files"].items():
        if rel.endswith("d8-v2-protocol.md"):
            continue  # dated banner added after the run (b6303ab); blob at d4dca83 matches
        if _sha(Path("/" + rel)) != digest:
            raise SystemExit(f"freeze pin mismatch: {rel}")
    paths = {k: Path("/" + v) for k, v in freeze["paths"].items()}

    dev = _load("d8_develop")
    dev2 = _load("d8_develop_v2")
    cfg = yaml.safe_load(paths["config_v1"].read_text())  # v2 inherits events/acceptance
    if yaml.safe_load(paths["config"].read_text())["inherits"] != "configs/cart_k562_d8_v1.yaml":
        raise SystemExit("v2 config no longer inherits v1")
    tau, eps = cfg["events"]["tau"], cfg["events"]["epsilon"]
    budget = cfg["acceptance"]["operating_budget_on_C"]
    prepare = json.loads((paths["prepare"] / "prepare.json").read_text())
    strata = {t: s.split("|")[0] for t, s in prepare["strata"].items()}
    stats = np.load(paths["audit_stats"])
    obs = np.load(args.observed_c)
    method = json.loads(paths["method"].read_text())["predictors"]

    cells = {}
    for key, axis in (("P1", "P1"), ("P2", "P2"), ("P3", "P1")):
        rows = dev2.predictor_rows(
            dev,
            paths[key],
            key,
            axis,
            obs["targets"].tolist(),
            lambda i, t: obs[axis][i],
            prepare,
            strata,
            stats,
            tau,
        )
        for event in ("sign", "magnitude"):
            frozen = method[key][event]
            z = dev2.event_labels(rows, event, eps)
            t = rows[1]
            pc = predict_trust(frozen["params"], rows[0])
            reproduced = operating_point(pc, z, t, budget=budget)
            if reproduced != frozen["threshold"]:
                raise SystemExit(f"{key}/{event}: as-run threshold not reproduced")
            reg = v3_protocol.operating_point(pc, z, t, budget=budget)
            cells[f"{key}/{event}"] = {
                "n_rows_C": int(len(z)),
                "n_targets_C": int(len(np.unique(t))),
                "identical": reg == frozen["threshold"],
                "as_run": _at(pc, z, t, frozen["threshold"]),
                "registered": _at(pc, z, t, reg),
            }
    args.out.mkdir(parents=True, exist_ok=False)
    result = {
        "definition_sha256": args.definition_sha256,
        "freeze_sha256": _sha(args.freeze),
        "observed_C_sha256": args.observed_c_sha256,
        "code_sha256": {p.name: _sha(p) for p in (Path(__file__), Path(v3_protocol.__file__))},
        "role_E_read": False,
        "budget": budget,
        "cells": cells,
    }
    (args.out / "opcheck.json").write_text(json.dumps(result, indent=1, default=float))
    print(json.dumps(cells, indent=1, default=float))


if __name__ == "__main__":
    main()
