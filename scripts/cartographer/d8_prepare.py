"""CART-K562-D8-v1 PREPARE: metadata-only roster, strata, split and sealed-store manifest.

Reads only obs metadata (target labels, gem groups) and the X shape of the local day-8 H5AD.
No expression value of any perturbed cell is read here (sealed access count 0). The existing
``build_index`` is not used because it validates every expression value, including role E.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import yaml

from alive.data.manifest import SplitManifest
from alive.experiment.day8_protocol import split_roles


def cell_count_band(n: int, bands: list) -> str:
    """Label the registered cell-count band containing ``n``."""
    for lo, hi in bands:
        if n >= lo and (hi is None or n < hi):
            return f"{lo}-{'' if hi is None else hi}"
    raise ValueError(f"{n} cells is outside every registered band")


def read_obs_labels(path: Path) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Return (target codes, categories, gem_group) from legacy or modern AnnData obs."""
    with h5py.File(path, "r") as f:
        obs = f["obs"]
        gene = obs["gene"]
        if isinstance(gene, h5py.Group):
            codes, cats = gene["codes"][:], gene["categories"].asstr()[:].tolist()
        else:
            codes, cats = gene[:], obs["__categories"]["gene"].asstr()[:].tolist()
        gem = obs["gem_group"]
        gem = gem["codes"][:] if isinstance(gem, h5py.Group) else gem[:]
    return codes, cats, gem


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--h5ad", type=Path, required=True)
    parser.add_argument("--exposure", type=Path, required=True, help="target-exposure01.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text())
    src = cfg["source"]
    if args.h5ad.stat().st_size != src["size_bytes"]:
        raise ValueError("day-8 H5AD size does not match the registered source")
    codes, cats, gem = read_obs_labels(args.h5ad)
    control = cats.index(src["control_value"])
    counts = np.bincount(codes[codes >= 0], minlength=len(cats))
    min_cells = cfg["eligibility"]["min_cells"]
    roster = sorted(c for i, c in enumerate(cats) if i != control and counts[i] >= min_cells)
    excluded = {
        c: f"fewer than {min_cells} cells"
        for i, c in enumerate(cats)
        if i != control and 0 < counts[i] < min_cells
    }
    groups = json.loads(args.exposure.read_text())["groups"]
    exposure = {t: g for g, ts in groups.items() for t in ts}
    n_of = {c: int(counts[i]) for i, c in enumerate(cats)}
    bands = cfg["split"]["cell_count_bands"]
    strata = {t: f"{exposure[t]}|{cell_count_band(n_of[t], bands)}" for t in roster}
    fr = cfg["split"]["fractions"]
    roles = split_roles(roster, strata, fractions=(fr["D"], fr["C"]), seed=cfg["split"]["seed"])
    manifest = SplitManifest(
        seed=cfg["split"]["seed"],
        fractions={
            "base_train": 0.0,
            "method_development": fr["D"],
            "conformal_calibration": fr["C"],
            "sealed_evaluation": fr["E"],
        },
        assignments={
            "base_train": (),
            "method_development": tuple(roles["D"]),
            "conformal_calibration": tuple(roles["C"]),
            "sealed_evaluation": tuple(roles["E"]),
        },
        exclusions=excluded,
        counts={
            "base_train": 0,
            "method_development": len(roles["D"]),
            "conformal_calibration": len(roles["C"]),
            "sealed_evaluation": len(roles["E"]),
            "excluded": len(excluded),
            "eligible_total": len(roster),
        },
    )
    args.out.mkdir(parents=True, exist_ok=False)
    manifest.write(args.out / "manifest.json")
    composition = {}
    for t in roster:
        g, n = np.unique(gem[codes == cats.index(t)], return_counts=True)
        composition[t] = {str(k): int(v) for k, v in zip(g.tolist(), n.tolist())}
    record = {
        "protocol_id": cfg["protocol_id"],
        "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
        "manifest_checksum": manifest.checksum,
        "sealed_access_count": 0,
        "roster_size": len(roster),
        "excluded": len(excluded),
        "role_counts": {r: len(v) for r, v in roles.items()},
        "strata": strata,
        "cells": {t: n_of[t] for t in roster},
        "gem_composition": composition,
    }
    (args.out / "prepare.json").write_text(json.dumps(record, indent=1, sort_keys=True))
    print(json.dumps({k: record[k] for k in ("roster_size", "excluded", "role_counts")}))


if __name__ == "__main__":
    main()
