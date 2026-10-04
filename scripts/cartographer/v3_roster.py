"""CART-K562-V3/V3.1 target rosters (outcome-independent; metadata and predictions only).

Reproduces the registered V3 roster byte-for-byte (the 2026-09-28 draw, whose generator was not
committed) and draws the V3.1 extension as a nested superset: the 240 V3 targets plus a uniform
sample from the rest of the same pool. Pool: P1-supported targets with day-6 cells > 0. Guide
ids: GWPS feature table, first two by sort order (as in V3). The extension samples only pool
targets with at least two GWPS guides.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import random
from pathlib import Path

V3_NOTE = (
    "uniform random, outcome-independent; guide ids from GWPS feature table (metadata); "
    "240 = ~210 power estimate + margin"
)


def pool_and_guides(root: Path) -> tuple[list[str], dict[str, list[str]]]:
    p1 = json.loads((root / "state-predict-01/full-01/record.json").read_text())["supported"]
    labels = json.loads((root / "h5ad-labels01.jsonl").read_text().splitlines()[0])
    counts = labels["labels"]["target_cell_counts"]
    day6 = {k for k, v in counts.items() if v > 0 and k != "non-targeting"}
    guides = collections.defaultdict(list)
    raw = gzip.decompress((root / "linkage02/members/KD8_p1_0_features.tsv.gz").read_bytes())
    for line in raw.decode().splitlines():
        fid, _, ftype = line.split("\t")
        if ftype == "CRISPR Guide Capture":
            guides[fid.split("_")[0]].append(fid)
    return sorted(set(p1) & day6), guides


def roster_doc(targets, guides, **meta) -> dict:
    rows = [{"target": t, "gwps_guide_ids": sorted(guides.get(t, []))[:2]} for t in targets]
    return {
        **meta,
        "targets": rows,
        "targets_without_gwps_guide": [r["target"] for r in rows if not r["gwps_guide_ids"]],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True, help="external evidence directory")
    ap.add_argument("--v3-sha256", required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    pool, guides = pool_and_guides(args.root)
    v3 = sorted(random.Random(20260929).sample(pool, 240))
    v3_doc = roster_doc(
        v3,
        guides,
        seed=20260929,
        pool="P1-supported ∩ day-6-labelled",
        pool_size=len(pool),
        n=240,
        note=V3_NOTE,
    )
    if hashlib.sha256(json.dumps(v3_doc, indent=1).encode()).hexdigest() != args.v3_sha256:
        raise SystemExit("V3 roster not reproduced; inputs changed")
    # Extension feasibility (metadata): only targets with >= 2 GWPS guides. V3 targets are kept.
    rest = sorted(t for t in set(pool) - set(v3) if len(guides.get(t, [])) >= 2)
    extra = random.Random(args.seed).sample(rest, args.n - 240)
    doc = roster_doc(
        sorted(v3 + extra),
        guides,
        seed=args.seed,
        pool="P1-supported ∩ day-6-labelled",
        pool_size=len(pool),
        n=args.n,
        nested_in={"v3_roster_sha256": args.v3_sha256, "v3_targets": 240},
        note=(
            "V3.1 DRAFT: V3 roster plus a uniform sample of the remaining pool targets with >= 2 "
            "GWPS guides (nested); "
            "outcome-independent; guide ids from GWPS feature table (metadata)"
        ),
    )
    with args.out.open("x") as fh:
        fh.write(json.dumps(doc, indent=1))
    print(args.out, hashlib.sha256(args.out.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
