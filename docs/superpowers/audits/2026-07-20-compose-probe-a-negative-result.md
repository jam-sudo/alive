# COMPOSE Probe A — preregistered candidate negative result (2026-07-20)

> **Status:** valid non-sealed measurement; **candidate rejected**; formal promotion incomplete.
> This record does not open the COMPOSE scientific seal, does not amend the frozen owner policy, and is not a
> Probe-A admission receipt.

## 1. Bound identities

- Executed clean Git commit: `daff92dbb053d27954f94c5b86fd0884ba8722d6`.
- Frozen owner-policy bytes: `bca70995117135367f3aadf77a551ba63b40fcbb426095611d0d63de7669a962`.
- Prepared-input manifest: `c5cf3889f61d431d756fef8bc903798bea3632e133554ded9fd2e883a7af3309`.
- Derived write-once registration: `771cbfd8a4287578fd5a69570785653ce0db14377aeaf7da360f6bad17b94f74`.
- Raw measurement artifact: `ca9dbc16788042c90439a6b8aaed833c952506013d6d66375a5b52e90aa432ce`.
- Checkpoint 1 and checkpoint 2: both
  `4b6c1e4884982a6d243724fee36f660662ec7246dcfb72909f515f55488bc9cf`.
- Input, role-attestation, and source-closure support files:
  `f80f8df490b36186d13a3dcc06181ce76da7c29674cdb5cb22ac68bddff1c8a9`,
  `a4fd1f74000c98cc79db7275b16ec66082e9c2601790fd7165adf4c75b20b4e3`, and
  `c1d39e1977f47dca14cfbffdbe9d1cbb65721631eab4d254607d7bb55706545e` respectively.

The source was the pinned Norman K562 artifact. The prepared non-sealed roles contained 400 controls, 404
single-perturbation rows, and 32 combo-calibration rows. Maintained validators confirmed identical
input-manifest/H5AD/row/control identities, zero sealed-pair overlap, zero forbidden source-row reads, and a
passing reader-spy attestation. The successful command ledger records build-roster, prepare-input, verify-input,
registration, and one Probe-A measurement. No sealed outcome gateway was constructed or consumed.

## 2. Preregistered result

| Gate | Frozen tolerance | Observed maximum absolute error | Result |
|---|---:|---:|---|
| two fresh fits/checkpoints/predictions | exactly `0` | `0.0` | **PASS** |
| public prediction vs exact-prefix/control-cap contract | `1e-5` | `0.19060921669006348` | **FAIL** |
| public prediction vs registered direct first-300 output bridge | `1e-5` | `0.13841108322143558` | **FAIL** |

The public-versus-exact-prefix reconstruction errors for control counts `[1, 8, 300, 301, 400]` were
`[0.00014675408601760864, 0.12339472025632858, 0.10370064854621885,
0.09286497672398886, 0.13841108322143558]`. Public-count differences for `300→301` and `300→400` were
`0.1340341567993164` and `0.19060921669006348`.

This is the behavior the probe was designed to distinguish. Pinned `cell-gears==0.1.2` public `predict()` asks
its helper for 300 control graphs; that helper draws 300 control indices with replacement and then averages the
model outputs. The maintained direct observer instead evaluated each exact frozen prepared control row once and
in order. Therefore public replacement sampling is not the registered exact first-prefix aggregation. Replaying
or post-selecting public random indices, relaxing the tolerance, or revising the same registration after seeing
these values is forbidden.

Exploratory, non-gating diagnostics for the 400-control public-versus-direct comparison were MAE
`0.025830409108306338`, RMSE `0.03246983344774054`, median absolute error
`0.02176469621558985`, 95th-percentile absolute error `0.06440838142794869`, and Pearson correlation
`0.9971932372470711`. High correlation does not rescue the preregistered equivalence claim.

The public output itself was finite and signed: minimum `-0.1075151190161705`, median
`0.80816450715065`, maximum `5.418663501739502`, negative fraction `0.0125`, and near-integer fraction `0.0`.
These descriptive values do not override either failed gate.

## 3. Formal-promotion status and evidence custody

The raw artifact and both checkpoints were copied byte-for-byte from the pod to the local, non-repository
archive `/Users/jam/alive_probe_evidence/20260720T010800Z/`; all 45 copied-file SHA-256 values matched the remote
tree. The archive is approximately 94 MiB. Earlier stopped attempts remain quarantined separately and were not
combined with this root.

No canonical `probe_a.json`, evidence manifest, verification receipt, or admission was published. Even with a
complete runtime identity, recomputation rejects the candidate at the first-300 gate and the output-bridge gate.
The container's authoritative immutable image digest was not exposed inside the pod and was not guessed, so no
`runtime.json` was fabricated. `logs/runtime_unresolved.json` is diagnostic only and is not admissible runtime
evidence.

The diagnostic runtime capture also exposed an implementation requirement for any later probe: host-visible
`os.cpu_count()`/`MemTotal` reported 252 CPUs and 1,014,082,285,568 bytes, whereas the container cgroup limited
memory to 116,999,999,488 bytes and CPU quota to 26.35 cores (`RUNPOD_CPU_COUNT=31`). A future maintained runtime
collector must distinguish provider allocation, cgroup-effective limits, and host-visible capacity instead of
silently labeling the last as pod resources.

## 4. Disposition

1. Reject the frozen `log_normalized_pseudobulk` exact-first-300 bridge candidate for this backend/runtime/input.
2. Do not rerun Probe A with altered tolerance, random-index replay, a revised registration, or an alternate
   transform chosen from these measurements.
3. Keep the currently named `raw_pseudobulk_approximation` comparator path activation-blocked. Its next design
   must explicitly define how the public replacement-sampled GEARS condition-level output is projected and how
   approximation bias is measured without claiming exact per-control equivalence.
4. Before another decision-grade pod attempt, add a reviewed first-class negative-result receipt and a
   cgroup-aware, provider-image-bound runtime evidence producer. Probe B was not run and remains separately
   blocked on its maintained timing/archive contract.
5. The scientific seal remains unopened.
