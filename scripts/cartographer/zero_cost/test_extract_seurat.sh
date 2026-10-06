#!/bin/bash
# Synthetic test for extract_seurat.R: NTC cells go to open_dir, perturbed cells only to sealed_dir.
set -euo pipefail
T=$(mktemp -d)
Rscript -e '
suppressPackageStartupMessages({library(SeuratObject); library(Matrix)})
set.seed(1)
m <- Matrix(rpois(50*20, 2), nrow=50, sparse=TRUE); rownames(m) <- paste0("G",1:50); colnames(m) <- paste0("c",1:20)
o <- CreateSeuratObject(counts=m)
o$guide <- c(rep("NTC_1",6), paste0("g",1:14)); o$gene <- c(rep("non-targeting",6), rep(c("A","B"),7))
o$lane <- rep(c("L1","L2"),10); o$secret_score <- runif(20)
saveRDS(o, file.path("'$T'","toy.rds"))'
echo '{"barcode": null, "guide": "guide", "target": "gene", "batch": "lane", "ntc_label": "non-targeting"}' > $T/map.json
Rscript "$(dirname "$0")/extract_seurat.R" names $T/toy.rds
Rscript "$(dirname "$0")/extract_seurat.R" export $T/toy.rds $T/map.json $T/open $T/sealed
python3 - "$T" <<'PY'
import csv, sys
T = sys.argv[1]
o = list(csv.DictReader(open(f"{T}/open/meta.csv"))); s = list(csv.DictReader(open(f"{T}/sealed/meta.csv")))
assert len(o) == 6 and all(r["target"] == "non-targeting" for r in o), "open must hold NTC only"
assert len(s) == 14 and all(r["target"] != "non-targeting" for r in s), "sealed must hold perturbed only"
assert "nCount" in o[0] and "nCount" not in s[0], "nCount only for NTC"
assert "secret_score" not in o[0] and "secret_score" not in s[0], "non-allowlisted column must be dropped"
assert "secret_score" in open(f"{T}/open/dropped_names.txt").read()
print("SYNTHETIC TEST PASS")
PY
rm -rf "$T"
