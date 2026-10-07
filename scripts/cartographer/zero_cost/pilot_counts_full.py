"""GWPS day-8 pilot raw counts on the full 8,248-gene axis for the PIE power model (0b §5).

Same access path as pilot_cells.py: D8's ``read_unsealed`` for roles D and C only, guarded by D8's
persisted audit count before/after. Writes sparse raw counts (cells x genes, CSR) per role plus target
offsets, gem groups and barcodes, and D8's C_ref / C_audit control counts (role CTRL).
Usage: pilot_counts_full.py <d8_config> <h5ad> <d8_prepare_dir> <targets.json> <role> <out_dir> [controls]
"""

import hashlib
import json
import sys
from pathlib import Path

import h5py
import numpy as np
import scipy.sparse as sp
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d8_observe import build_index  # noqa: E402

from alive.data.manifest import SplitManifest  # noqa: E402
from alive.data.outcome_store import ReplogleOutcomeStore  # noqa: E402

ROLE = {"D": "method_development", "C": "conformal_calibration"}
cfg_p, h5ad, prep_dir, targets_p, role, out = sys.argv[1:7]
h5ad, prep_dir, out = Path(h5ad), Path(prep_dir), Path(out)
cfg = yaml.safe_load(Path(cfg_p).read_text())
prepare = json.loads((prep_dir / "prepare.json").read_text())
if prepare["config_sha256"] != hashlib.sha256(Path(cfg_p).read_bytes()).hexdigest():
    raise SystemExit("config differs from the one PREPARE used")
out.mkdir(parents=True, exist_ok=False)

if role == "CTRL":  # D8's frozen control roles (controls are not sealed)
    c = Path(sys.argv[7])
    man = json.loads((c / "attempt02-role-manifest.json").read_text())
    rows = np.load(c / "attempt02-control_rows.npy")
    gem = np.load(c / "attempt02-control_gem_group.npy")
    X = np.load(c / "attempt05-control_X.npy", mmap_mode="r")
    pos = {int(r): i for i, r in enumerate(rows.tolist())}
    for r in ("C_ref", "C_audit"):
        idx = np.sort([pos[int(x)] for x in man["roles"][r]])
        for k, s in enumerate(range(0, len(idx), 2000)):  # chunk files bound memory
            sp.save_npz(
                out / f"{r}_counts_{k:04d}.npz", sp.csr_matrix(np.asarray(X[idx[s : s + 2000]]))
            )
        np.save(out / f"{r}_gem.npy", gem[idx])
    print("CTRL written")
    sys.exit(0)

manifest = SplitManifest.read(prep_dir / "manifest.json")
index, gem = build_index(h5ad, cfg, prepare)
store = ReplogleOutcomeStore(index, h5ad, manifest, audit_path=prep_dir / "seal-audit.jsonl")
with h5py.File(h5ad, "r") as f:
    barcodes = f["obs"][f["obs"].attrs["_index"]].asstr()[:]
wanted = set(json.loads(Path(targets_p).read_text()))
targets = [t for t in manifest.ids_for(ROLE[role]) if t in wanted]
audit_before = store.sealed_access_count  # D8 persisted count (its single E opening)
G, B, offsets = [], [], [0]
for k, s in enumerate(range(0, len(targets), 50)):  # one chunk file per batch bounds memory
    batch = targets[s : s + 50]
    pops = store.read_unsealed(batch)
    sp.save_npz(
        out / f"counts_{role}_{k:04d}.npz",
        sp.vstack(
            [sp.csr_matrix(np.asarray(pops[t].cells, dtype=np.float32)) for t in batch]
        ).tocsr(),
    )
    for t in batch:
        rows = index.cell_indices(t)
        G.append(gem[rows])
        B.append(barcodes[rows])
        offsets.append(offsets[-1] + len(rows))
if store.sealed_access_count != audit_before:
    raise SystemExit("sealed access during pilot read")
np.savez(
    out / f"meta_{role}.npz",
    targets=np.array(targets),
    offsets=np.array(offsets),
    gem=np.concatenate(G),
    barcodes=np.concatenate(B),
)
rec = {
    "role": role,
    "n_targets": len(targets),
    "n_cells": offsets[-1],
    "d8_audit_count_before_after": [audit_before, store.sealed_access_count],
}
(out / f"pilot_{role}.json").write_text(json.dumps(rec, indent=1))
print(json.dumps(rec))
