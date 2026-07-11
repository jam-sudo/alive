#!/bin/bash
# Sweep GEARS train DataLoader num_workers on the reused 2k fit-role artifact.
# For each NW: launch a 1-epoch fit, wait past the graph build, sample the
# per-step rate over a fixed window, kill. Reports steps/sec -> projected
# training-only per-epoch (1847 steps). Opens no seal; committed worker unchanged.
set -uo pipefail

ERA_PY=/root/gears_env_era/bin/python
D=/root/decision_probe
WORK=$D/out/work_2000
WORKER=/workspace/ALIVE_git/scripts/baselines/gears_worker.py
GO_MANIFEST=/workspace/gears_data/go_resource_manifest.json
export PYTHONPATH=/workspace/ALIVE_git/src
export CUBLAS_WORKSPACE_CONFIG=":4096:8"
export PYTHONHASHSEED=11
export ALIVE_WORKER_RESOURCE_MANIFEST_PATH="$GO_MANIFEST"
export ALIVE_WORKER_RESOURCE_SHA256="$(sha256sum "$GO_MANIFEST" | cut -d' ' -f1)"
STEPS_PER_EPOCH=1847
SAMPLE_S=100

echo "host_cores=$(nproc)"
( nvidia-smi --query-gpu=timestamp,utilization.gpu,memory.used --format=csv -l 5 > $D/out/gpu_util_sweep.log 2>&1 ) &
SMI_PID=$!
trap 'kill "$SMI_PID" 2>/dev/null' EXIT
for NW in 0 16 32; do
  echo "===== NW=$NW ====="
  LOG=$D/out/workers_nw${NW}.log
  if [ "$NW" -gt 0 ]; then OMP=2; else OMP=""; fi
  # launch 1-epoch fit detached
  OMP_NUM_THREADS=$OMP NW=$NW setsid bash -c "$ERA_PY $D/probe_workers.py $WORKER $WORK raw_pseudobulk_approximation > $LOG 2>&1" < /dev/null &
  PID=$!
  # wait until training steps begin (setup+graph ~4min), cap ~7min
  for i in $(seq 1 84); do
    grep -aq "Epoch 1 Step" "$LOG" 2>/dev/null && break
    grep -aqE "Traceback|WorkerUnavailable|Error" "$LOG" 2>/dev/null && { echo "NW=$NW ERROR"; tail -6 "$LOG"; break; }
    sleep 5
  done
  if ! grep -aq "Epoch 1 Step" "$LOG" 2>/dev/null; then
    echo "NW=$NW no training steps seen"; pkill -f "probe[_]workers.py" 2>/dev/null; sleep 3; continue
  fi
  sleep 20  # settle: let workers spawn / warm before sampling steady-state
  # sample step rate over SAMPLE_S
  S0=$(grep -a "Epoch 1 Step" "$LOG" | tail -1 | awk '{print $4}')
  sleep "$SAMPLE_S"
  S1=$(grep -a "Epoch 1 Step" "$LOG" | tail -1 | awk '{print $4}')
  # capture CPU% (sum across python procs) + GPU util WHILE still running
  CPU=$(ps -o pcpu= -C python 2>/dev/null | paste -sd+ | bc 2>/dev/null)
  UTIL=$(tail -1 $D/out/gpu_util_sweep.log 2>/dev/null)
  # kill this NW's run
  pkill -f "probe[_]workers.py" 2>/dev/null; sleep 3
  SPS=$(awk "BEGIN{d=$S1-$S0; if(d>0) printf \"%.3f\", d/$SAMPLE_S; else print 0}")
  PEREP=$(awk "BEGIN{if($SPS>0) printf \"%.1f\", $STEPS_PER_EPOCH/$SPS; else print -1}")
  T20=$(awk "BEGIN{if($SPS>0) printf \"%.2f\", (94+20*$STEPS_PER_EPOCH/$SPS)/3600; else print -1}")
  echo "RESULT NW=$NW steps0=$S0 steps1=$S1 steps_per_sec=$SPS train_per_epoch_s=$PEREP proj_20ep_hours=$T20 cpu_pct=$CPU gpu=[$UTIL]"
done
echo "===== WORKERS SWEEP DONE ====="
