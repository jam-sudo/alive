"""PIE inference without the Replogle/Nadig directory (0a §2, 0b §2; runs in the PIE env).

The checkpoint's training config lists ``pie_replogle_nadig_essential`` (weight 0, not an evidence
dataset). This adapter swaps the config's data paths for the pinned local copies of the four
evidence datasets, splits and sources, then calls PIE's own ``predict_loaded``. PIE itself refuses
to run unless the rebuilt evidence key and train.json sha256 equal the checkpoint's pinned values,
so the 0a gate "evidence key reproduces without the replogle dir" is enforced by PIE's code.
Usage: pie_predict.py <assets_root> <query_dir> <query.json> <out.parquet> [device]
"""

import dataclasses
import hashlib
import json
import sys
from pathlib import Path

from pie.predict import RowSource, load_checkpoint, predict_loaded, write_predictions_parquet
from pie.utils import load_common_env

CKPT_SHA256 = "e60a1304d074706405939bde94c5edf9851e78070f2d584c6b5025a002ed9a7c"
EVIDENCE_KEY = "87a01957365041383ac2cbae3a9cf44be6f48e5dbc69ca045f14fa270441d151"
DATASETS = {
    "pie_tahoe100m": "597d6ded9f9a148331388484ffb193489121c702",
    "pie_jiang": "99242356dfcf58e049d867703c5743df8d1790bf",
    "pie_arc_vcc_25": "e7dda6065316959958b87583ddf0a15f6e69c37d",
    "pie_x_atlas_orion": "0950c8aa5ce5b33dc9d6f0c5eade3ae445ca0ffb",
}

load_common_env()  # $PIE_ENV_FILE, as the pie CLI does
root, qdir, qjson, out = map(Path, sys.argv[1:5])
device = sys.argv[5] if len(sys.argv) > 5 else "mps"
ckpt = root / "xdataset/best_auprc.ckpt"
h = hashlib.sha256()
with open(ckpt, "rb") as f:
    for b in iter(lambda: f.read(1 << 24), b""):
        h.update(b)
if h.hexdigest() != CKPT_SHA256:
    raise SystemExit("checkpoint sha256 differs from 0a §2")
loaded = load_checkpoint(ckpt)
if loaded.stats.evidence_key != EVIDENCE_KEY:
    raise SystemExit("checkpoint evidence key differs from 0a §2")
d = loaded.config.data
pre = list(d.preprocessed_dirs)
if not any("pie_replogle_nadig_essential" in p for p in pre):
    raise SystemExit("unexpected training config")
local = []
for p in pre:
    name = next((n for n in DATASETS if f"/{n}@" in p), None)
    if name is None:
        continue  # the replogle dir (weight 0, no evidence)
    if DATASETS[name] not in p:
        raise SystemExit(f"{name}: revision differs from 0a §2")
    local.append(str(root / name / "preprocessed"))
src = {k: str(root / "pie_sources" / k) for k in d.source_dirs}
weights = {k: v for k, v in (d.dataset_weights or {}).items() if k != "replogle"}
data = d.model_copy(
    update={
        "preprocessed_dirs": local,
        "dataset_weights": weights,
        "split_dir": str(root / "splits/replogle_xdataset"),
        "source_dirs": src,
        "gene_text_dir": str(root / "pie_sources/gene_text"),
    }
)
loaded = dataclasses.replace(loaded, config=loaded.config.model_copy(update={"data": data}))
preds = predict_loaded(loaded, RowSource("query", qjson), [qdir], device, 16)
write_predictions_parquet(preds, out)
print(json.dumps({"rows": sum(len(b.contexts) for b in preds.blocks), "out": str(out)}))
