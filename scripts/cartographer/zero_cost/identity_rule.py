"""10x K562 Flex identity rule (0a §5): design-only, outcome-free.

Every guide of a target must align exactly to GRCh38 (first 19 nt: the 20th base is a constant
library base, C in all 6,903 guides, not genomic; step-1 record E) within +-500 bp of the target gene's
primary TSS (GENCODE v46 basic, MANE_Select tag, else Ensembl_canonical), and no other gene's
primary TSS may lie within +-1 kb of any of its guides.
"""

import bisect
import collections
import csv
import gzip
import hashlib
import json
import subprocess
import sys

FR, GTF, IDX, P1, OUT = sys.argv[1:6]

# primary TSS per gene from GENCODE v46 basic
tss = {}  # gene_id -> (chrom, pos, strand, name, priority)
with gzip.open(GTF, "rt") as fh:
    for line in fh:
        if line.startswith("#"):
            continue
        f = line.rstrip("\n").split("\t")
        if f[2] != "transcript":
            continue
        a = f[8]
        pri = 0 if 'tag "MANE_Select"' in a else (1 if 'tag "Ensembl_canonical"' in a else None)
        if pri is None:
            continue
        gid = a.split('gene_id "')[1].split('"')[0].split(".")[0]
        name = a.split('gene_name "')[1].split('"')[0]
        pos = int(f[3]) if f[6] == "+" else int(f[4])
        if gid not in tss or pri < tss[gid][4]:
            tss[gid] = (f[0], pos, f[6], name, pri)
by_chrom = collections.defaultdict(list)
for gid, (c, p, s, n, _) in tss.items():
    by_chrom[c].append((p, gid))
for c in by_chrom:
    by_chrom[c].sort()

guides = []
with open(FR) as fh:
    for r in csv.DictReader(fh):
        if r["feature_type"] != "CRISPR Guide Capture":
            continue
        guides.append(r)
fa = OUT + ".guides.fa"
with open(fa, "w") as fh:
    for r in guides:
        fh.write(f">{r['id']}\n{r['sequence']}\n")
sam = subprocess.run(
    [
        "bowtie2",
        "-f",
        "-x",
        IDX,
        "-U",
        fa,
        "--end-to-end",
        "--very-sensitive",
        "--score-min",
        "C,0,0",
        "-k",
        "2",
        "-3",
        "1",
        "--no-unal",
        "--no-hd",
        "-p",
        "8",
    ],
    capture_output=True,
    text=True,
    check=True,
).stdout
hits = collections.defaultdict(list)
for line in sam.splitlines():
    f = line.split("\t")
    if int(f[1]) & 4:
        continue
    strand = "-" if int(f[1]) & 16 else "+"
    cut = int(f[3]) + (17 if strand == "+" else 3)  # approx Cas9 cut site within 20-nt protospacer
    hits[f[0]].append((f[2], cut))


def near(chrom, pos, w):
    lst = by_chrom.get(chrom, [])
    i = bisect.bisect_left(lst, (pos - w, ""))
    out = []
    while i < len(lst) and lst[i][0] <= pos + w:
        out.append(lst[i][1])
        i += 1
    return out


by_target = collections.defaultdict(list)
for r in guides:
    by_target[(r["target_gene_id"], r["target_gene_name"])].append(r["id"])
p1 = set(json.load(open(P1))["supported"])
res = {}
for (gid, gname), ids in by_target.items():
    if gname in ("Ignore", "Non-Targeting"):
        continue
    gid0 = gid.split(".")[0]
    ok, why = True, ""
    if gid0 not in tss:
        ok, why = False, "no_primary_tss"
    else:
        c, p, _, _, _ = tss[gid0]
        for g in ids:
            h = hits.get(g, [])
            if len(h) != 1:
                ok, why = False, f"alignments={len(h)}"
                break
            hc, hp = h[0]
            if hc != c or abs(hp - p) > 500:
                ok, why = False, "guide_far_from_tss"
                break
            others = [x for x in near(hc, hp, 1000) if x != gid0]
            if others:
                ok, why = False, "other_tss_within_1kb"
                break
    res[gname] = {
        "gene_id": gid,
        "n_guides": len(ids),
        "pass": ok,
        "reason": why,
        "p1_supported": gname in p1,
    }
json.dump(res, open(OUT, "w"), indent=1, sort_keys=True)
c = collections.Counter((v["p1_supported"], v["pass"]) for v in res.values())
print("targets", len(res), "pass", sum(v["pass"] for v in res.values()))
print("P1-supported pass/total", c[(True, True)], c[(True, True)] + c[(True, False)])
print("non-P1 pass/total", c[(False, True)], c[(False, True)] + c[(False, False)])
print(
    "reasons", collections.Counter(v["reason"] for v in res.values() if not v["pass"]).most_common()
)
print("sha256", hashlib.sha256(open(OUT, "rb").read()).hexdigest())
