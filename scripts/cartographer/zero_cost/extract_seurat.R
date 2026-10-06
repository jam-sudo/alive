# Seal-safe extraction of a Seurat RDS (0a §5). Two modes:
#   names  <rds>                         -> prints slot/assay/layer/meta.data column NAMES only (no values)
#   export <rds> <map.json> <open_dir> <sealed_dir>
#       map.json: {"barcode": null|"col", "guide": "col", "target": "col", "batch": "col", "ntc_label": "..."}
#       open_dir   <- NTC cells only: counts (MatrixMarket), barcodes, genes, allowlisted meta, nCount
#       sealed_dir <- non-NTC cells: counts + allowlisted meta (no nCount); never summarised here
suppressPackageStartupMessages({ library(SeuratObject); library(Matrix); library(jsonlite) })
args <- commandArgs(trailingOnly = TRUE)
mode <- args[1]; obj <- readRDS(args[2])

if (mode == "names") {
  cat("class:", class(obj), "\n")
  cat("assays:", paste(Assays(obj), collapse = ","), "\n")
  for (a in Assays(obj)) cat("layers[", a, "]:", paste(Layers(obj[[a]]), collapse = ","), "\n")
  cat("reductions:", paste(Reductions(obj), collapse = ","), "\n")
  cat("meta.data columns:", paste(colnames(obj@meta.data), collapse = ","), "\n")
  cat("n_cells:", ncol(obj), " n_features(RNA):", nrow(obj[["RNA"]]), "\n")
  quit(status = 0)
}

stopifnot(mode == "export")
m <- fromJSON(args[3]); open_dir <- args[4]; sealed_dir <- args[5]
dir.create(open_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(sealed_dir, recursive = TRUE, showWarnings = FALSE)
md <- obj@meta.data
bc <- if (is.null(m$barcode)) rownames(md) else as.character(md[[m$barcode]])
keep <- data.frame(barcode = bc, guide = as.character(md[[m$guide]]),
                   target = as.character(md[[m$target]]), batch = as.character(md[[m$batch]]),
                   stringsAsFactors = FALSE)
is_ntc <- !is.na(keep$target) & keep$target == m$ntc_label
counts <- LayerData(obj, assay = "RNA", layer = "counts")
stopifnot(identical(colnames(counts), rownames(md)))
genes <- rownames(counts)
write_part <- function(dir, idx, with_ncount) {
  writeMM(counts[, idx, drop = FALSE], file.path(dir, "counts.mtx"))
  writeLines(genes, file.path(dir, "genes.txt"))
  meta <- keep[idx, ]
  if (with_ncount) meta$nCount <- Matrix::colSums(counts[, idx, drop = FALSE])
  write.csv(meta, file.path(dir, "meta.csv"), row.names = FALSE)
}
write_part(open_dir, which(is_ntc), TRUE)
write_part(sealed_dir, which(!is_ntc), FALSE)
# integer check on NTC rows only (raw counts)
ntc_counts <- counts[, which(is_ntc), drop = FALSE]
cat("ntc_cells:", sum(is_ntc), " sealed_cells:", sum(!is_ntc),
    " ntc_counts_integer:", all(ntc_counts@x == round(ntc_counts@x)), "\n")
writeLines(c(sprintf("dropped_meta_columns=%s", paste(setdiff(colnames(md), unlist(m[c("barcode","guide","target","batch")])), collapse = ",")),
             sprintf("dropped_assays=%s", paste(setdiff(Assays(obj), "RNA"), collapse = ",")),
             sprintf("dropped_reductions=%s", paste(Reductions(obj), collapse = ","))),
           file.path(open_dir, "dropped_names.txt"))
