# Sealed-roster gate residual — measured 2026-09-12

**What this shows.** `activation_evidence._validate_pair_roster_manifest` — the check the
dependency lock passes through on its way to `COMPLETE` — never compares the declared
`sealed_pair_ids` against the protocol's canonical split. It measures the two supplied lists
against each other. A roster that omits a genuinely sealed pair from its own declaration and
trains on it is therefore certified `VERIFIED_ZERO_OVERLAP`, while the honest roster naming that
pair is refused.

**Concealment passes; honest declaration fails.** That asymmetry is the finding.

## Reproduce

```bash
PYTHONPATH=src .venv/bin/python \
  docs/superpowers/evidence/2026-09-12-sealed-roster-gate-residual/probe_sealed_roster_gate.py
```

Exit 0 means the residual reproduced. `probe_output.txt` is the run captured at the pin below.

| arm | construction | measured |
|---|---|---|
| A | hand-written roster hiding one genuinely sealed pair | **ACCEPTED**, `sealed_pair_overlap_count=0` |
| B | control — same training roster, full sealed declaration | **REFUSED**, "training roster overlaps sealed pairs" |
| C | ground truth — `verify_split_manifest` on the same split | verifies; the hidden pair **is** sealed |

Arm C is what makes A a defect rather than an opinion: the canonical answer exists, is
self-verifying, and the gate simply never consults it. Arm B is what makes A non-vacuous: a
validator that refused everything would satisfy A alone.

## This is not an oversight — it is a consequence of the freeze

`smoke_evidence.build_smoke_pair_roster` already derives the sealed roster correctly
(2026-09-10 owner-delegated judgment 3): it verifies the split manifest, requires the verified
checksum to equal the fit-role artifact's `pair_manifest_sha256`, and takes the union of BOTH
sealed roles. A caller's `sealed_pair_ids` is optional cross-check only. **The producer path is
closed.** This probe bypasses the producer and writes the manifest by hand.

`promote_lock_to_complete` then checks `pair_manifest_sha256` is present and identical across
backends — and deliberately drops it, saying so in a comment: `_RUN_EVIDENCE_KEYS` is an exact
key roster and `activation_evidence.py` is a member of the frozen kernel-isolation closure
(`tests/alive/compose/test_kernel_isolation_ci.py`), so the lock has no slot for the checksum.
It is "spent as a check on this promotion rather than carried as a field."

The consequence is the residual: **the binding exists only inside the producing process.** The
durable artifact the seal depends on does not record which split the smoke was cut against, and
the gate that reads it cannot re-derive the answer.

## Where it can be closed without touching the frozen closure

Measured on this pin:

- `activation_evidence.py`, `roles.py`, `provenance.py`, `io.py`, `fit_role.py` — **in** the
  closure; editing any of them invalidates archived Linux CI evidence.
- `config2.py`, `split.py`, `smoke_evidence.py`, `carrier_loader.py`, `preflight_cmd.py` —
  **outside** it (`grep -c config2 tests/alive/compose/test_kernel_isolation_ci.py` → 0).

`config2.py:1744-1760` is the scientific-mode consumer: it calls `validate_dependency_lock` and
raises `ScientificModeError` when the evidence is not `COMPLETE`. The canonical split is already
a declared pre-seal input — `run_spec.py:113` lists `pair_manifest`, and
`carrier_loader.py:779` reads it digest-bound through `_preseal_json`. Both sides of the needed
comparison are therefore in hand at that point, outside the closure.

Costs of the alternatives are in the decision note that cites this directory.

## Pin

Measured at `main` HEAD `537c535` (2026-09-12). The probe depends only on
`activation_evidence._validate_pair_roster_manifest`, `split.build_split_manifest` /
`verify_split_manifest` and `roles.SEALED_ROLE_NAMES`; it constructs its own synthetic pair
universe and touches no protocol data, no config and no sealed store.
