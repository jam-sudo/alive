# GEARS decision-probe — archived harness + Probe A evidence (2026-07-11)

> **Opened NO seal. Observation archive, NOT release-grade durable evidence.** This directory version-controls
> what was recoverable from the 2026-07-11 A100 dev-pod session so the observations in
> `../../2026-07-11-compose-gears-decision-probe-results.md` are reproducible-in-method rather than ephemeral.
> Per that doc's §5, promotion to durable decision evidence still requires full input/runtime hashes, raw
> per-run measurements, and a rerun of the un-run gates — none of which this archive supplies.

## Run context

- **Pod:** RunPod A100 80GB PCIe, 252 CPU cores. Env built on **ephemeral `/root`** (the `/workspace` mfs volume
  was out of quota); the pod has since been stopped, so `/root` and all raw run logs there are gone.
- **GEARS env:** installed from the frozen `gears_era.lock` — gears 0.1.2 / numpy 1.26.4 / scipy 1.11.4 /
  pandas 2.2.3 / anndata 0.10.9 / scikit-learn 1.9.0 / torch 2.6.0+cu124 (cuda available).
- **ALIVE worker under test:** `scripts/baselines/gears_worker.py` at pod repo commit `e0c5863` (byte-identical to
  the merged worker on `main`; the harness monkeypatched only `_GEARS_EPOCHS` / the train DataLoader in-process).
- **Inputs (read-only, on `/workspace`, hashes NOT captured here):**
  `alive_data/NormanWeissman2019_filtered.h5ad`, `gears_data/gene2go_all.pkl`, `gears_data/go_resource_manifest.json`.
- **cell-gears 0.1.2 source fingerprint (sha256 over the package `.py` files):**
  `f63e48d676169ba5be94ebdd4dfe96ad7834ba7273d5bfe46b65b7a5a486a57e` — re-derivable by installing
  `cell-gears==0.1.2` and re-running `harness/probe_gears_source.py`.

## Files

```
harness/                       dev-pod measurement scripts, ARCHIVED AS-RUN (hardcoded pod paths / seed=11;
  probe_gears_source.py          Probe A: dump 0.1.2 source symbols + fingerprint (COMPLETE)
  bench_prep.py                  reduce Norman to N genes at full cell count (control-variance roster)
  build_payload.py               build fit-role artifact + payload via committed build_dev_smoke_payload
  bench_gears_timing.py          Probe B: 2-epoch-count fit-cost benchmark (PARTIAL — killed before JSON)
  run_decision_probe.sh          Probe A + Probe B orchestrator
  probe_workers.py               DataLoader num_workers prototype (monkeypatch nw into the train loader)
  run_workers_sweep.sh           num_workers {0,16,32} step-rate sweep (COMPLETE — coarse)
out/                           Probe A outputs (the only run outputs pulled off the pod before shutdown)
  probe_a_gears_scale.json       sha256 dadd5fc978537b13cb6b07d3e0d62910bb0b4912288bbb517cd220c17ff33ef4
  probe_a_gears_source.txt       sha256 7fb01c2935667b987b397199e30117f3761e40f4fe120cc4e7d6a8b8c088019d
                                 (verbatim dump of cell-gears 0.1.2 predict/new_data_process/set_pert_genes/inits)
```

The `harness/` scripts contain hardcoded pod paths and are archived to record the *method*, not as maintainable
production tooling (they are deliberately outside `scripts/`, which forbids hardcoded paths in production source).

## What is / is not here

- **Present & complete:** Probe A source evidence (`out/`) — the load-bearing Option-1 basis (GEARS 0.1.2 does not
  normalize the caller AnnData; `predict` aggregates per-control rows over the first ≤300-control batch). The full
  harness.
- **Not present (never written / lost with `/root`):** `probe_b_scale_benchmark_{2000,5000}.json` (Probe B was
  stopped before writing), raw `bench_*.log` / `workers_*.log`, `gpu_util.log`. The timing/step-rate numbers in the
  results doc came from live log sampling and are coarse planning estimates, not preserved raw measurements.
- **Never run (need a fresh session, not recovery):** Probe A P2 fitted-output-scale / negative-output /
  control-count instrumentation / inference-equivalence; Probe B 5k B1–B4; the exact mandatory-set size `|M|` and
  the 2,088-vs-2,000 gene provenance.

## Re-run

Install `cell-gears==0.1.2` from `gears_era.lock`, then (paths as in `harness/run_decision_probe.sh` /
`run_workers_sweep.sh`) point the scripts at a Norman `.h5ad` + the GO resource bundle. Probe A
(`probe_gears_source.py`) needs only the gears env; Probe B and the workers sweep need the fit-role artifact built
by `bench_prep.py` + `build_payload.py`.
