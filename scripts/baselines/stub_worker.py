# scripts/baselines/stub_worker.py
"""SYNTHETIC-ONLY deterministic additive-delta stub worker (protocol reference).

Runs in any python; predicts, per requested pair (g,h), the additive delta
singles_response[g] + singles_response[h] projected trivially to response_dim.
The real gears/cpa workers replace this under the locked envs (pod-only).
"""

from __future__ import annotations

import argparse

import numpy as np

from alive.compose.baseline_subprocess import read_payload, write_predictions


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="work_dir", required=True)
    ap.add_argument("--out", dest="out", required=True)
    a = ap.parse_args()
    p = read_payload(a.work_dir)
    ids = list(p["single_gene_ids"])
    singles = np.asarray(p["singles_response"], dtype=float)
    idx = {g: i for i, g in enumerate(ids)}
    dim = int(p["response_dim"])
    preds = {}
    for g, h in p["pair_ids"]:
        vec = singles[idx[g]] + singles[idx[h]]
        preds[(g, h)] = vec[:dim]
    write_predictions(a.out, preds)


if __name__ == "__main__":
    main()
