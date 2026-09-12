# Sealed-roster binding at the gate — a decision the freeze forces

> **STATUS: PROPOSED — owner decision required.** Nothing here changes the estimator, the
> comparator family, the margins, the multiplicity correction or any verdict threshold. It
> decides **where** an existing binding is enforced, and the choice has a real cost either way.
>
> `config_sha256` unchanged. Seal **UNOPENED**. Execution **RELEASE-BLOCKED**.

**Evidence:** `docs/superpowers/evidence/2026-09-12-sealed-roster-gate-residual/` — a three-arm
probe, re-runnable, exit 0 when the residual reproduces.

## 1. What was measured

`activation_evidence._validate_pair_roster_manifest` compares the declared `training_pair_ids`
and `sealed_pair_ids` **against each other** and never against the protocol's canonical split.
A hand-written roster that trains on a genuinely sealed pair and omits it from its own sealed
declaration is certified `VERIFIED_ZERO_OVERLAP`; the honest roster naming that pair is refused.

```
A  hidden  : ACCEPTED   sealed_pair_overlap_count=0
B  control : REFUSED    "gears smoke training roster overlaps sealed pairs"
C  truth   : verify_split_manifest passes; the hidden pair IS sealed
```

**Concealment passes and honesty fails.** Arm B makes A non-vacuous; arm C makes A a defect
rather than an opinion — the canonical answer existed, self-verifying, and the gate never
consulted it.

## 2. This is not an oversight

Two pieces of the design are already right, and the third is deliberate.

**The producer is closed.** `build_smoke_pair_roster` (owner-delegated judgment 3, 2026-09-10)
derives the sealed roster from the split manifest: it requires `verify_split_manifest` to pass,
requires that verified checksum to equal the fit-role artifact's `pair_manifest_sha256`, and
unions BOTH sealed roles. A caller's `sealed_pair_ids` is optional cross-check only. The probe
does not attack that path — it bypasses it.

**Promotion checks the binding.** `promote_lock_to_complete` requires `pair_manifest_sha256` on
both backend records and refuses when they disagree, with the right reason recorded: one
protocol has one pair universe.

**And then the checksum is dropped, on purpose.** The code says why:

> `pair_manifest_sha256` is established above and then left out here.
> `activation_evidence._RUN_EVIDENCE_KEYS` is an EXACT key roster and that module is a member of
> the frozen kernel-isolation closure, so the lock has no slot for the split-manifest checksum:
> it is spent as a check on this promotion rather than carried as a field.

So the residual is a **consequence of the freeze**, not a missed sibling. The binding lives only
inside the producing process; the durable artifact the seal depends on does not record which
split the smoke was cut against, and the gate that later reads that artifact cannot re-derive it.

This repository has the general form of this lesson already: enforcement belongs at the site that
**gates**, not the site that **generates** (`preseal_read`, 2026-08-30). Here the gate was frozen
before the binding existed.

## 3. The options, with their costs

### A — carry the checksum in the lock (edit the frozen module)

Add `pair_manifest_sha256` to `_RUN_EVIDENCE_KEYS`/`_DIGEST_EVIDENCE_KEYS`, stop dropping it, and
have the validator derive the sealed roster from a digest-bound split manifest.

*Cost:* `activation_evidence.py` is closure member 13 of the frozen set. Editing it invalidates
the archived Linux CI proof, which must be re-run and re-archived on the target platform. That is
a pod/CI task and an owner decision, not a local edit. **Not recommended as the first move.**

### B — bind at the consumer, outside the closure *(recommended)*

Enforce in `config2.py:1744-1760`, which already calls `validate_dependency_lock` in scientific
mode and raises `ScientificModeError`. Measured this pin: `config2.py` is **not** in the closure
(`grep -c config2 tests/alive/compose/test_kernel_isolation_ci.py` → 0), and both sides of the
comparison are already in hand there — `pair_manifest` is a declared pre-seal input
(`run_spec.py:113`) read digest-bound via `carrier_loader.py:779`.

The rule: the lock's `sealed_pair_roster_sha256` must equal `sha256_json` of the sealed tokens
derived from the run spec's verified `pair_manifest`. Concealment then fails at the only place
that matters — the door to scientific mode.

*Cost:* the token encoding (`combo_sep`, byte-ordered `A_B`) must be stated once and shared, not
re-implemented; two encoders that drift would make the comparison empty for the wrong reason.
`smoke_evidence._canonical_sealed_tokens` already carries that rule and its reasoning — the
shared home should be `split.py`, which both sides already import and which is outside the
closure.

### C — accept and register

Record the residual as a known limitation of the lock artifact and rely on the producer path.

*Cost:* the lock stops being self-sufficient evidence. Anyone validating it later — including a
future auditor — must trust that it came from the producer, which is precisely what an artifact
is supposed to remove the need for.

## 4. Recommendation

**B.** It closes the measured path at the gate, needs no change to any frozen module, invents no
new artifact, and uses only bindings the protocol already declares. A is the eventual tidy end
state and should follow whenever the closure is next re-archived for another reason; C leaves the
seal depending on a process nobody can re-check.

Whichever is chosen, the probe in the evidence directory is the acceptance test: it must flip
from exit 0 to exit 1 at the site where the binding lands.

## 5. What this does not claim

- Not a demonstration that any real evidence was forged. No pod run has produced release
  evidence; the lock is `INCOMPLETE` and the six activation blockers are unfilled.
- Not a defect in the producer. The producer path refuses the same construction.
- Not a change to any registered value. `config_sha256` stays `0d207746…`; seal **UNOPENED**;
  execution **RELEASE-BLOCKED**.
