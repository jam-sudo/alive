"""CART-K562-D8-v1 development observation: observed changes for one unsealed role (D or C).

Opens the day-8 H5AD only through ``ReplogleOutcomeStore`` built from the PREPARE manifest,
so any role-E target raises ``SealingError``. For each target: validates raw counts, applies
the registered scale (log1p CP10k over the 8,248-gene axis) on each predictor's gene axis and
subtracts the batch-matched ``C_ref`` control mean (unfiltered comparator, option A).
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
from alive.data.outcome_store import ReplogleOutcomeStore
from alive.data.replogle import DatasetSchema, ReplogleIndex
from alive.experiment.day8_protocol import batch_matched_reference

_ROLE = {"D": "method_development", "C": "conformal_calibration"}


def log_cp10k(counts: np.ndarray, columns) -> np.ndarray:
    """Registered model scale; rejects non-finite, negative or zero-depth cells."""
    counts = np.asarray(counts, dtype=np.float64)
    if not np.isfinite(counts).all() or (counts < 0).any():
        raise ValueError("invalid raw counts")
    depth = counts.sum(1, keepdims=True)
    if (depth <= 0).any():
        raise ValueError("zero-depth cell")
    return np.log1p(1e4 * counts / depth)[:, columns]


def observed_change(cells, cell_groups, ref_scaled, ref_groups, columns):
    """Target mean on the model scale minus the batch-matched reference mean."""
    ref, fallback = batch_matched_reference(ref_scaled, ref_groups, cell_groups)
    return log_cp10k(cells, columns).mean(axis=0) - ref, fallback


def reference_matrices(cfg: dict, controls: Path, gem: np.ndarray, axes: dict) -> dict:
    """Frozen ``C_ref`` controls on each predictor axis: {key: (scaled matrix, gem groups)}."""
    man = json.loads((controls / "attempt02-role-manifest.json").read_text())
    rows = np.load(controls / "attempt02-control_rows.npy")
    pos = {int(r): i for i, r in enumerate(rows.tolist())}
    ref_rows = np.array(sorted(man["roles"][cfg["controls"]["reference_role"]]))
    X = np.load(controls / "attempt05-control_X.npy", mmap_mode="r")
    counts = np.asarray(X[[pos[int(r)] for r in ref_rows]], dtype=np.float64)
    return {k: (log_cp10k(counts, cols), gem[ref_rows]) for k, cols in axes.items()}


def build_index(h5ad: Path, cfg: dict, prepare: dict) -> tuple[ReplogleIndex, np.ndarray]:
    """Metadata-only index over eligible roster targets (no expression value read)."""
    with h5py.File(h5ad, "r") as f:
        obs = f["obs"]
        gene = obs["gene"]
        if isinstance(gene, h5py.Group):
            codes, cats = gene["codes"][:], gene["categories"].asstr()[:].tolist()
        else:
            codes, cats = gene[:], obs["__categories"]["gene"].asstr()[:].tolist()
        gem = obs["gem_group"]
        gem = gem["codes"][:] if isinstance(gem, h5py.Group) else gem[:]
        var = f["var"]
        gene_ids = tuple(var[var.attrs["_index"]].asstr()[:].tolist())
        n_cells, n_genes = f["X"].shape
    src = cfg["source"]
    roster = sorted(prepare["cells"])
    index = ReplogleIndex(
        schema=DatasetSchema(
            perturbation_key=src["perturbation_key"], control_value=src["control_value"]
        ),
        gene_ids=gene_ids,
        n_cells=int(n_cells),
        n_genes=int(n_genes),
        control_indices=np.flatnonzero(codes == cats.index(src["control_value"])),
        perturbation_indices={t: np.flatnonzero(codes == cats.index(t)) for t in roster},
        eligible_perturbations=tuple(roster),
        exclusions={},
    )
    return index, gem


def main() -> None:  # pragma: no cover - real-data entry point
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--h5ad", type=Path, required=True)
    parser.add_argument("--prepare", type=Path, required=True, help="PREPARE output directory")
    parser.add_argument("--controls", type=Path, required=True, help="control-access-01 directory")
    parser.add_argument(
        "--axes", type=Path, required=True, help="JSON {P1: [...], P2: [...]} columns"
    )
    parser.add_argument("--role", choices=sorted(_ROLE), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--only", type=Path, required=True, help="JSON list: read only these targets (supported)"
    )
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text())
    prepare = json.loads((args.prepare / "prepare.json").read_text())
    if prepare["config_sha256"] != hashlib.sha256(args.config.read_bytes()).hexdigest():
        raise ValueError("config changed after PREPARE")
    manifest = SplitManifest.read(args.prepare / "manifest.json")
    index, gem = build_index(args.h5ad, cfg, prepare)
    store = ReplogleOutcomeStore(
        index, args.h5ad, manifest, audit_path=args.prepare / "seal-audit.jsonl"
    )
    axes = {k: list(v) for k, v in json.loads(args.axes.read_text()).items()}
    ref = reference_matrices(cfg, args.controls, gem, axes)
    wanted = set(json.loads(args.only.read_text()))
    targets = [t for t in manifest.ids_for(_ROLE[args.role]) if t in wanted]
    out = {k: np.zeros((len(targets), len(v)), dtype=np.float32) for k, v in axes.items()}
    fallback = {}
    for start in range(0, len(targets), 50):
        batch = targets[start : start + 50]
        pops = store.read_unsealed(batch)
        for i, t in enumerate(batch, start=start):
            groups = gem[index.cell_indices(t)]
            for k, cols in axes.items():
                out[k][i], fb = observed_change(pops[t].cells, groups, ref[k][0], ref[k][1], cols)
                if fb:
                    fallback.setdefault(t, fb)
    args.out.mkdir(parents=True, exist_ok=False)
    np.savez(args.out / f"observed_{args.role}.npz", targets=np.array(targets), **out)
    record = {
        "role": args.role,
        "n_targets": len(targets),
        "sealed_access_count": store.sealed_access_count,
        "fallback_groups": fallback,
        "observed_sha256": hashlib.sha256(
            (args.out / f"observed_{args.role}.npz").read_bytes()
        ).hexdigest(),
    }
    (args.out / "record.json").write_text(json.dumps(record, indent=1))
    print(
        json.dumps({k: v for k, v in record.items() if k != "fallback_groups"}),
        len(fallback),
        "targets used fallback",
    )


if __name__ == "__main__":
    main()
