#!/usr/bin/env python
"""Probe A — GEARS 0.1.2 source + output-scale characterization (opens no seal).

Resolves the GEARS native-scale linchpin (recommendation doc §1). Dumps the exact
installed source of the load-bearing symbols so the P1-P4 facts are read from the
wheel, not assumed, plus a source-derived heuristic verdict. The dumped source text
is the AUTHORITATIVE artifact; the JSON heuristics are a convenience — the owner/I
read the .txt to apply the Option-1-vs-2 decision rule.

Runs on the era stack (cell-gears 0.1.2). No fit, no data, no GPU required — this is
pure introspection, so it always runs even if a benchmark stage is flaky.

Usage: probe_gears_source.py <out_dir>
"""

import hashlib
import importlib.metadata as im
import inspect
import json
import os
import sys

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)

report = {"schema": "compose_probe_a_gears_scale_v1", "errors": []}

# --- distribution identity + source fingerprint ---------------------------- #
try:
    import gears

    report["gears_version"] = getattr(gears, "__version__", None)
    report["gears_dist_version"] = im.version("cell-gears")
    pkg_dir = os.path.dirname(os.path.abspath(gears.__file__))
    report["gears_package_dir"] = pkg_dir
    h = hashlib.sha256()
    files = []
    for root, _dirs, names in os.walk(pkg_dir):
        for name in sorted(names):
            if name.endswith(".py"):
                p = os.path.join(root, name)
                with open(p, "rb") as fh:
                    b = fh.read()
                h.update(os.path.relpath(p, pkg_dir).encode())
                h.update(b)
                files.append(os.path.relpath(p, pkg_dir))
    report["source_fingerprint_sha256"] = h.hexdigest()
    report["source_py_files"] = files
except Exception as exc:  # noqa: BLE001
    report["errors"].append(f"import/fingerprint: {exc!r}")
    with open(os.path.join(OUT, "probe_a_gears_scale.json"), "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    raise SystemExit("PROBE_A_FAIL: gears not importable")

# --- dump the load-bearing source symbols ---------------------------------- #
from gears import GEARS, PertData  # noqa: E402

targets = {
    "GEARS.predict": getattr(GEARS, "predict", None),
    "PertData.new_data_process": getattr(PertData, "new_data_process", None),
    "PertData.set_pert_genes": getattr(PertData, "set_pert_genes", None),
    "PertData.__init__": getattr(PertData, "__init__", None),
    "GEARS.__init__": getattr(GEARS, "__init__", None),
}
dumped = {}
for name, obj in targets.items():
    if obj is None:
        report["errors"].append(f"symbol missing: {name}")
        continue
    try:
        dumped[name] = inspect.getsource(obj)
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"getsource {name}: {exc!r}")
combined = "\n\n# ===================================================== #\n\n".join(
    f"# ---- {name} ----\n{src}" for name, src in dumped.items()
)
with open(os.path.join(OUT, "probe_a_gears_source.txt"), "w") as fh:
    fh.write(combined)
report["dumped_symbols"] = sorted(dumped)

# --- source-derived heuristics (NOT authoritative; read the .txt) ---------- #
predict_src = dumped.get("GEARS.predict", "")
process_src = dumped.get("PertData.new_data_process", "")


def _has(src, *tokens):
    return {t: (t in src) for t in tokens}


report["heuristics"] = {
    "P2_predict_output_transform": _has(predict_src, "expm1", "log1p", "np.exp", "torch.exp", "np.log"),
    "P3_predict_per_control_mean": _has(predict_src, "np.mean", ".mean(", "for ", "300", "batch"),
    "P1_P4_process_normalization": _has(
        process_src, "normalize", "sc.pp", "log1p", "total", "sum", "size_factor", "median"
    ),
    "note": (
        "Authoritative source is probe_a_gears_source.txt. Apply the doc-§1 decision rule by READING it: "
        "Option 1 iff predict returns log-space (P2), constructs per-control rows before np.mean over the "
        "first <=300-control batch (P3), and GEARS normalizes each cell by full-gene library to a GLOBAL "
        "constant BEFORE gene subsetting (P1/P4). Otherwise fall back to Option 2."
    ),
}

with open(os.path.join(OUT, "probe_a_gears_scale.json"), "w") as fh:
    json.dump(report, fh, indent=2, sort_keys=True)
print("PROBE_A_DONE version=%s fingerprint=%s errors=%d"
      % (report.get("gears_dist_version"), report.get("source_fingerprint_sha256", "?")[:12],
         len(report["errors"])), flush=True)
print("  wrote probe_a_gears_scale.json + probe_a_gears_source.txt (READ the .txt)", flush=True)
