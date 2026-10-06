"""GWPS day-8 pilot cells for the 0a unified power model (0a §6), roles D and C only.

Reads D8's already-opened D/C targets only through D8's ``ReplogleOutcomeStore.read_unsealed``;
consumed E rows are not read (doing so would bypass D8's seal audit). Writes, per role, the P1-axis
cells on the registered scale (log1p CP10k over the 8,248-gene axis), gem groups and barcodes.
Usage: pilot_cells.py <d8_config> <h5ad> <d8_prepare_dir> <axes.json> <targets.json> <role> <out_dir> [controls]
Role REF writes D8's frozen C_ref controls on the P1 axis (needs the control-access-01 dir).
"""

import hashlib
import json
import sys
from pathlib import Path

import h5py
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d8_observe import build_index, log_cp10k, reference_matrices  # noqa: E402

from alive.data.manifest import SplitManifest  # noqa: E402
from alive.data.outcome_store import ReplogleOutcomeStore  # noqa: E402

ROLE = {"D": "method_development", "C": "conformal_calibration"}
cfg_p, h5ad, prep_dir, axes_p, targets_p, role, out = sys.argv[1:8]
h5ad, prep_dir, out = Path(h5ad), Path(prep_dir), Path(out)
cfg = yaml.safe_load(Path(cfg_p).read_text())
prepare = json.loads((prep_dir / "prepare.json").read_text())
if prepare["config_sha256"] != hashlib.sha256(Path(cfg_p).read_bytes()).hexdigest():
    raise SystemExit("config differs from the one PREPARE used")
manifest = SplitManifest.read(prep_dir / "manifest.json")
index, gem = build_index(h5ad, cfg, prepare)
store = ReplogleOutcomeStore(index, h5ad, manifest, audit_path=prep_dir / "seal-audit.jsonl")
cols = json.loads(Path(axes_p).read_text())["P1"]
if role == "REF":
    ref, groups = reference_matrices(cfg, Path(sys.argv[8]), gem, {"P1": cols})["P1"]
    out.mkdir(parents=True, exist_ok=False)
    np.savez(out / "pilot_REF.npz", X=ref.astype(np.float32), gem=groups)
    print("REF", ref.shape, hashlib.sha256((out / "pilot_REF.npz").read_bytes()).hexdigest())
    sys.exit(0)
with h5py.File(h5ad, "r") as f:
    barcodes = f["obs"][f["obs"].attrs["_index"]].asstr()[:]
wanted = set(json.loads(Path(targets_p).read_text()))
targets = [t for t in manifest.ids_for(ROLE[role]) if t in wanted]
X, G, B, offsets = [], [], [], [0]
for s in range(0, len(targets), 50):
    batch = targets[s : s + 50]
    pops = store.read_unsealed(batch)
    for t in batch:
        rows = index.cell_indices(t)
        X.append(log_cp10k(pops[t].cells, cols).astype(np.float32))
        G.append(gem[rows])
        B.append(barcodes[rows])
        offsets.append(offsets[-1] + len(rows))
if store.sealed_access_count != 0:
    raise SystemExit("sealed access during pilot read")
out.mkdir(parents=True, exist_ok=False)
np.savez(
    out / f"pilot_{role}.npz",
    targets=np.array(targets),
    offsets=np.array(offsets),
    X=np.concatenate(X),
    gem=np.concatenate(G),
    barcodes=np.concatenate(B),
)
digest = hashlib.sha256((out / f"pilot_{role}.npz").read_bytes()).hexdigest()
(out / f"pilot_{role}.json").write_text(
    json.dumps(
        {
            "role": role,
            "n_targets": len(targets),
            "n_cells": offsets[-1],
            "sealed_access_count": 0,
            "sha256": digest,
        },
        indent=1,
    )
)
print(role, len(targets), offsets[-1], digest)
