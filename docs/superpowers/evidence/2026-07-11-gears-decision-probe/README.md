# GEARS decision-probe — quarantined as-run archive (2026-07-11)

> **QUARANTINED / NONCONFORMING — DO NOT EXECUTE OR PROMOTE.** The official one-time
> `ComposeOutcomeStore` evaluation gateway was not consumed, and no outcome-based selection was demonstrated.
> However, the as-run Probe B prep loaded the full source `X` before the dev sealed/calibration roster was
> resolved, so it violated ALIVE's stronger metadata-before-expression / sealed-expression-never-materialized
> contract. “Opened NO seal” is therefore not a valid description of Probe B's procedural boundary.
>
> This directory version-controls, **byte-for-byte as recovered**, what survived the 2026-07-11 A100 dev-pod
> session so the observations in
> `../../2026-07-11-compose-gears-decision-probe-results.md` are reproducible-in-method rather than ephemeral.
> It is a forensic observation archive, not executable tooling or durable decision evidence. A conforming rerun
> must follow `../../runbooks/2026-07-11-compose-gears-decision-probe-rerun.md`; none of the archived harness files
> may be copied forward or invoked.

`archive_manifest.json` fixes the exact recovered `harness/` and `out/` byte roster, sizes, and SHA-256 values at
origin commit `6d30af55ce8d97198f39040193d3aa7338c25f9b`. It deliberately excludes this explanatory README and the
manifest itself. Any mismatch is archive corruption; the response is to report it, never regenerate or silently
“repair” the forensic bytes.

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

The `harness/` scripts contain hardcoded pod paths and are archived to record the *as-run method*, including its
defects. They are deliberately excluded from maintained-source formatting/linting, must remain outside `scripts/`,
and must never be imported, copied forward, or invoked. In particular:

- `harness/bench_prep.py:37` eagerly loads the full source AnnData expression matrix;
- `harness/bench_prep.py:64-76,106` retains all measurable perturbation rows and copies their expression before
  `harness/build_payload.py` resolves the dev sealed/calibration roster;
- it also subsets genes before the newly registered `U_full` normalization/response boundary and implements the
  invalid “top N, then force-add” rule that produced 2,088 rather than exactly 2,000 genes.

These defects invalidate Probe B as decision evidence even though no sealed metric was calculated or inspected.

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

## Re-run prohibition and replacement

Do **not** rerun `harness/run_decision_probe.sh`, `bench_prep.py`, `build_payload.py`, or any derivative copied from
them. The replacement run is gated on a reviewed GEARS gene-roster implementation and adapter, constructs the
full-universe fit-role/response artifacts first, resolves roles before any expression read, and preserves raw
logs/hashes. The authoritative execution contract is
`../../runbooks/2026-07-11-compose-gears-decision-probe-rerun.md`.
