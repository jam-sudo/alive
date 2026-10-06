# Seal-safe extraction of a Seurat RDS (0a §5). Two modes:
#   names  <rds>                         -> prints slot/assay/layer/meta.data column NAMES only (no values)
#   export <rds> <map.json> <open_dir> <sealed_dir>
#       map.json: {"barcode": null|"col", "guide": "col", "target": "col", "batch": "col", "ntc_label": "..."}
#       open_dir   <- NTC cells only: counts (CSC slots, binary), genes, allowlisted meta, nCount
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
dropped_assays <- setdiff(Assays(obj), "RNA"); dropped_red <- Reductions(obj); md_names <- colnames(md)
rm(obj); invisible(gc())
stopifnot(identical(colnames(counts), rownames(md)))
genes <- rownames(counts)
write_part <- function(dir, idx, with_ncount, chunk = as.integer(Sys.getenv("CHUNK", "20000"))) {
  # genes x cells CSC slots in binary, appended chunk by chunk to bound memory
  ci <- file(file.path(dir, "counts_i.int32"), "wb"); cx <- file(file.path(dir, "counts_x.float64"), "wb")
  p <- 0; nnz <- 0; ncount <- numeric(0)
  for (s in seq(1, max(length(idx), 1), by = chunk)) {
    if (!length(idx)) break
    m <- as(counts[, idx[s:min(s + chunk - 1, length(idx))], drop = FALSE], "CsparseMatrix")
    writeBin(as.integer(m@i), ci, size = 4); writeBin(as.numeric(m@x), cx, size = 8)
    p <- c(p, nnz + m@p[-1]); nnz <- nnz + length(m@x)
    if (with_ncount) ncount <- c(ncount, Matrix::colSums(m))
    rm(m); invisible(gc())
  }
  close(ci); close(cx)
  writeBin(as.integer(p), file.path(dir, "counts_p.int32"), size = 4)
  writeLines(as.character(c(length(genes), length(idx))), file.path(dir, "counts_dim.txt"))
  writeLines(genes, file.path(dir, "genes.txt"))
  meta <- keep[idx, ]
  if (with_ncount) meta$nCount <- ncount
  write.csv(meta, file.path(dir, "meta.csv"), row.names = FALSE)
}
write_part(open_dir, which(is_ntc), TRUE)
write_part(sealed_dir, which(!is_ntc), FALSE)
# integer check on NTC rows only (raw counts)
ntc_x <- readBin(file.path(open_dir, "counts_x.float64"), "double", n = 2^31 - 1)
cat("ntc_cells:", sum(is_ntc), " sealed_cells:", sum(!is_ntc),
    " ntc_counts_integer:", all(ntc_x == round(ntc_x)), "\n")
writeLines(c(sprintf("dropped_meta_columns=%s", paste(setdiff(md_names, unlist(m[c("barcode","guide","target","batch")])), collapse = ",")),
             sprintf("dropped_assays=%s", paste(dropped_assays, collapse = ",")),
             sprintf("dropped_reductions=%s", paste(dropped_red, collapse = ","))),
           file.path(open_dir, "dropped_names.txt"))
