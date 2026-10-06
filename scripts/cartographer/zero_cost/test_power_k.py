"""Synthetic known-answer checks for power_k.py (no real data)."""

import gzip
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

here = os.path.dirname(os.path.abspath(__file__))
repo = os.path.abspath(os.path.join(here, "../../.."))
sys.path.insert(0, here)
from power_k import shift_to  # noqa: E402

# 1. intercept shift hits the target-weighted goal
rng = np.random.default_rng(0)
eta, t = rng.normal(2, 1, 500), rng.integers(0, 40, 500)
c = shift_to(eta, t, 0.7)
w = 1 / np.bincount(t)[t]
assert abs((w / (1 + np.exp(-(eta + c)))).sum() / w.sum() - 0.7) < 1e-6


def build(T, agree):
    """Pilot where observed sign agrees with prediction with probability ``agree`` per output."""
    ng, nt, nc = 40, 150, 60
    genes = [{"gene_id": f"ENSG{i:011d}", "gene_name": f"G{i}"} for i in range(ng)]
    tg = [f"T{i}" for i in range(nt)]
    H = rng.choice([-1, 1], (nt, ng)) * rng.uniform(0.3, 1.0, (nt, ng))
    os.makedirs(f"{T}/pilot")
    os.makedirs(f"{T}/pred")
    for r, sl in (("D", slice(0, 100)), ("C", slice(100, 150))):
        ts = tg[sl]
        X, off = [], [0]
        for k in range(sl.start, sl.stop):
            sgn = np.where(rng.random(ng) < agree, np.sign(H[k]), -np.sign(H[k]))
            X.append(sgn * 0.5 + rng.normal(0, 0.05, (nc, ng)))
            off.append(off[-1] + nc)
        np.savez(
            f"{T}/pilot/pilot_{r}.npz",
            targets=np.array(ts),
            offsets=np.array(off),
            X=np.concatenate(X).astype(np.float32),
            gem=np.zeros(off[-1], int),
            barcodes=np.array([f"b{i}" for i in range(off[-1])]),
        )
    np.savez(f"{T}/pilot/pilot_REF.npz", X=np.zeros((50, ng), np.float32), gem=np.zeros(50, int))
    np.savez(f"{T}/audit.npz", n_ref=50, P1_var=np.full(ng, 0.5), P1_mean=np.ones(ng))
    np.save(f"{T}/pred/predicted_change.npy", H)
    np.save(f"{T}/pred/per_token_sd.npy", np.full((nt, ng), 0.1))
    np.save(f"{T}/pred/per_set_sd.npy", np.full((nt, ng), 0.1))
    json.dump({"supported": tg}, open(f"{T}/pred/record.json", "w"))
    json.dump({"genes": genes}, open(f"{T}/hvg.json", "w"))
    # the unit does not measure G0: its outputs must drop
    open(f"{T}/unit_genes.txt", "w").write("\n".join(g["gene_name"] for g in genes[1:]))
    open(f"{T}/hvg_names.txt", "w").write("\n".join(g["gene_name"] for g in genes))
    open(f"{T}/s.toml", "w").write('[fewshot."replogle.k562"]\ntest = %s\n' % json.dumps(tg[::2]))
    with gzip.open(f"{T}/g.gtf.gz", "wt") as f:  # every gene on its own chromosome: no cis removal
        for i, g in enumerate(genes):
            f.write(
                f'chr{i}\tX\ttranscript\t{1000}\t2000\t.\t+\t.\tgene_id "{g["gene_id"]}.1"; '
                f'gene_name "{g["gene_name"]}"; tag "MANE_Select";\n'
            )
    json.dump({t: 40 for t in tg}, open(f"{T}/slots.json", "w"))
    np.save(f"{T}/delta.npy", np.zeros(1))


def run(T):
    r = subprocess.run(
        [
            sys.executable,
            f"{here}/power_k.py",
            "--pilot-dir",
            f"{T}/pilot",
            "--audit",
            f"{T}/audit.npz",
            "--pred-dir",
            f"{T}/pred",
            "--hvg",
            f"{T}/hvg.json",
            "--state-toml",
            f"{T}/s.toml",
            "--gtf",
            f"{T}/g.gtf.gz",
            "--slots",
            f"{T}/slots.json",
            "--unit-genes",
            f"{T}/unit_genes.txt",
            "--n-ctrl",
            "10000",
            "--v31-config",
            f"{repo}/configs/cart_k562_v3_1.yaml",
            "--delta-measured",
            f"{T}/delta.npy",
            "--gb",
            "none",
            "--n-sim",
            "6",
            "--workers",
            "3",
            "--out",
            f"{T}/out",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if r.returncode:
        raise SystemExit(r.stderr[-3000:])
    return json.load(open(f"{T}/out/power.json"))


# 2. near-perfect pilot: drawn success means sit at 1 - (assay + residual) [test] and one 0.1 lower [train]
T = tempfile.mkdtemp()
build(T, 1.0)
res = run(T)
zt = np.mean([s["z_mean"]["1"] for s in res["sims"]])
zr = np.mean([s["z_mean"]["0"] for s in res["sims"]])
assert res["summary"]["outputs_unmeasured_in_unit"] == 1
assert abs(zt - 0.8) < 0.03 and abs(zr - 0.7) < 0.03, (zt, zr)
# 3. coin-flip pilot: no shift below 0.5, nothing can pass
T = tempfile.mkdtemp()
build(T, 0.5)
res = run(T)
assert res["summary"]["p_pass"] == 0, res["summary"]
assert all(abs(s["z_mean"]["1"] - 0.5) < 0.05 for s in res["sims"])
# 4. positive control: the pipeline can PASS (δ_measured -0.2 cancels the fixed test-stratum 0.2)
T = tempfile.mkdtemp()
build(T, 1.0)
np.save(f"{T}/delta.npy", np.full(1, -0.2))
res = run(T)
assert res["summary"]["p_pass"] > 0.5, res["summary"]
print("SYNTHETIC POWER TEST PASS")
