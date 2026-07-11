#!/bin/bash
# COMPOSE dev-pod decision probe orchestrator (opens no seal).
#   Probe A: GEARS 0.1.2 source/scale characterization -> Option 1 vs 2.
#   Probe B: 2k/5k full-cell fit-cost benchmark          -> N_target.
# Faithfully drives the committed gears_worker; extrapolates epochs for cost control.
set -uo pipefail

NORMAN="${1:?usage: run_decision_probe.sh <norman.h5ad> <gene2go.pkl> <go_manifest.json> <out_dir>}"
GENE2GO="${2:?gene2go.pkl}"
GO_MANIFEST="${3:?go_resource_manifest.json}"
OUT="${4:?out_dir}"

# Interpreters (override via env). GEARS runs ONLY on the era stack; the newest
# stack crashes GEARS at runtime ('Series' object has no attribute 'nonzero').
ERA_PY="${ERA_PY:-/root/gears_env_era/bin/python}"      # gears 0.1.2
BUILD_PY="${BUILD_PY:-/workspace/cpa_env_085/bin/python}"  # anndata+alive for prep/build
ALIVE_SRC="${ALIVE_SRC:-/workspace/ALIVE_git/src}"
WORKER="${WORKER:-/workspace/ALIVE_git/scripts/baselines/gears_worker.py}"
BUILDER_DIR="$(dirname "$0")"
CALIB="${CALIB:-8}"          # combo_calibration pairs in the fit (representative)
SEALED="${SEALED:-4}"        # dev-smoke sealed pairs (NOT the real COMPOSE seal)

export PYTHONPATH="$ALIVE_SRC"
export CUBLAS_WORKSPACE_CONFIG=":4096:8"
export PYTHONHASHSEED=11
export ALIVE_WORKER_RESOURCE_MANIFEST_PATH="$GO_MANIFEST"
export ALIVE_WORKER_RESOURCE_SHA256="$(sha256sum "$GO_MANIFEST" | cut -d' ' -f1)"

mkdir -p "$OUT"
# background GPU utilization log (B4) — proves GEARS is CPU-bound
( nvidia-smi --query-gpu=timestamp,utilization.gpu,memory.used --format=csv -l 5 > "$OUT/gpu_util.log" 2>&1 ) &
SMI_PID=$!
trap 'kill "$SMI_PID" 2>/dev/null' EXIT

echo "===== PROBE A: GEARS 0.1.2 source/scale ====="
"$ERA_PY" "$BUILDER_DIR/probe_gears_source.py" "$OUT" || echo "PROBE_A_ERROR (continuing to B)"

for N in ${SIZES:-2000 5000}; do
  echo "===== PROBE B: size=$N (full non-sealed cells) ====="
  REDUCED="$OUT/norman_bench_${N}.h5ad"
  WORK="$OUT/work_${N}"
  ART="$OUT/approved_${N}/fit_role.h5ad"
  rm -rf "$WORK" "$OUT/approved_${N}"; mkdir -p "$WORK" "$OUT/approved_${N}"

  echo "--- prep (control-var roster, NO cap) ---"
  "$BUILD_PY" "$BUILDER_DIR/bench_prep.py" "$NORMAN" "$REDUCED" "$N" 0 0 5 "$GENE2GO" \
    || { echo "PREP_FAIL size=$N"; continue; }

  echo "--- build payload (committed build_dev_smoke_payload) ---"
  N_HVG=1500; [ "$N" -lt 1600 ] && N_HVG=$((N - 100))
  "$BUILD_PY" "$BUILDER_DIR/build_payload.py" "$REDUCED" "$WORK" "$ART" \
    "$OUT/manifest_${N}.json" "$N_HVG" "$CALIB" "$SEALED" \
    || { echo "BUILD_FAIL size=$N"; continue; }

  echo "--- GEARS timing (era stack, epochs 3+6 -> extrapolate 20) ---"
  "$ERA_PY" "$BUILDER_DIR/bench_gears_timing.py" "$WORKER" "$WORK" \
    raw_pseudobulk_approximation "$N" "$OUT" \
    || echo "BENCH_FAIL size=$N (continuing)"
done

echo "===== DECISION PROBE DONE ====="
echo "collect: $OUT/probe_a_gears_scale.json  $OUT/probe_a_gears_source.txt"
echo "         $OUT/probe_b_scale_benchmark_2000.json  $OUT/probe_b_scale_benchmark_5000.json"
echo "         $OUT/gpu_util.log"
ls -la "$OUT"/*.json "$OUT"/*.txt 2>/dev/null
