# COMPOSE managed-pod network-isolation design

**Status:** implementation contract; operational use remains `RELEASE-BLOCKED` until a clean exact commit,
fresh verifier image/owner lock, and independent review are complete.

## Problem

The original Probe-A runtime contract required a new Linux network namespace exposing only `lo`. That is a
strong boundary when the execution environment grants the required namespace capability, but standard managed
RunPod containers do not necessarily grant `CAP_SYS_ADMIN` or `CAP_NET_ADMIN`. A caller flag cannot substitute
for a kernel-enforced boundary, and failure to create a namespace must not be treated as proof that the network
is disabled.

The goal is to retain a fail-closed, replayable isolation property without requiring privilege escalation. This
design changes no scientific parameter, data role, seal boundary, outcome policy, or release state.

## Admitted modes

Runtime schema `compose_gears_probe_runtime_v5` accepts exactly one of two discriminated modes:

1. `linux_network_namespace_loopback_only`
   - the namespace exposes exactly `lo`;
   - IPv4 and IPv6 route tables contain no non-loopback route;
   - the Linux network-namespace inode is recorded and rechecked.
2. `linux_seccomp_socketpair_only_behavior_v2`
   - `PR_SET_NO_NEW_PRIVS=1` is active;
   - seccomp filter mode is active with at least one filter;
   - effective, permitted, inheritable, and ambient capability sets are each subsets of the exact admitted
     standard-container allowlist `0x00000000a80425fb`; the bounding set is recorded and must contain the
     permitted set, but bounding-only bits are inert under `no_new_privs` and are not misclassified as held
     privilege;
   - the collector implementation SHA and expected x86_64 cBPF policy SHA equal the verifier's bytes;
   - the architecture is exactly `x86_64`; unvalidated architectures, including `aarch64`, fail closed;
   - active IPv4/IPv6 and `AF_UNIX` stream/datagram socket probes each fail with `EPERM`;
   - an `AF_UNIX` stream socketpair remains usable for endpoint-free local process communication.

The two modes have separate exact-key rosters. Hybrid, partial, caller-asserted, unknown, or extra-field
representations fail validation.

## Seccomp policy

`scripts/compose/run_network_isolated.py` is the only maintained launcher for the seccomp mode. Before executing
the requested command it:

1. before importing ALIVE code, requires Python isolated mode (`-I`), disabled user-site loading, the exact
   maintained launcher source, and no `PYTHONPATH`/`PYTHONHOME`/user-base/startup/inspection/breakpoint or
   `LD_PRELOAD`/`LD_AUDIT` override;
2. permits only the same absolute active Python executable, literal `-I`, and the canonical non-symlink
   `scripts/compose/gears_decision_probe.py`; arbitrary executables, wrappers, alternate interpreters, driver
   aliases, and extra pre-driver flags fail closed;
3. rejects socket-backed stdin/stdout/stderr (closing the `SCM_RIGHTS` descriptor-transfer path), and closes every
   inherited descriptor above stderr;
4. sets irreversible `PR_SET_NO_NEW_PRIVS`;
5. installs the exact x86_64 classic-BPF seccomp policy and kills an unexpected audit architecture;
6. returns `EPERM` for every `socket` call, including `AF_UNIX`, preventing local proxy/agent socket use;
7. permits `socketpair` only for `AF_UNIX`, preserving endpoint-free local IPC;
8. returns `EPERM` for `connect`, including on an inherited descriptor;
9. returns `EPERM` for `io_uring_setup`, preventing an alternate async socket-creation path;
10. returns `EPERM` for `pidfd_getfd`, preventing acquisition of another process's pre-existing descriptor;
11. denies x32-ABI syscall numbers explicitly;
12. runs the full active behavioral proof before `exec`; and
13. writes a canonical launcher receipt to a same-PID `memfd`, applies the exact
    `F_SEAL_{WRITE,GROW,SHRINK,SEAL}` roster, and inherits only that receipt descriptor across `exec`.

The filter is inherited across `exec` and descendants and cannot be removed. Non-socket stdin/stdout/stderr remain
available as the explicitly accepted operator command channel; the contract prevents the scientific process from opening a
new IP transport or connecting to a local Unix proxy. It is not a general filesystem sandbox, process sandbox, or
confidentiality boundary. Linux does not expose the installed classic-BPF program back to this unprivileged
process. Consequently, `policy_sha256` identifies the exact instruction roster requested by the launcher; it is
not a kernel read-back hash. Kernel state and effect are established separately by status fields and active
negative/positive probes.

## Same-PID launcher receipt

Before `exec`, receipt v2 binds the launcher and driver source SHAs; exact outer and inner argv; current PID;
Python invocation path, resolved executable path and binary SHA; `sys.prefix`; exact isolated-mode flags;
`LD_LIBRARY_PATH`; x86_64 policy/collector identities; and the complete active behavioral proof. The maintained
driver inherits the sealed descriptor in the same PID, checks its memfd identity and exact seal roster,
recomputes every locally observable digest, requires exact `[same-python, -I, canonical-driver, ...]` structure,
and repeats this check immediately before command-ledger append. All command receipts must use one identical
Python/loader identity.

Command-record schema `compose_gears_probe_command_record_v2` stores both the canonical receipt object and its
SHA-256. The offline verifier therefore replays the launcher path/source, outer and inner argv relationship,
expected-policy digest, exact capability allowlist, and behavioral proof without trusting a transient
environment flag. During a trusted maintained-producer execution, the live memfd check establishes same-PID
continuity and detects argv/code/runtime drift. The archived JSON is replayable provenance, not independent remote
attestation: its self-checksum alone cannot prove historical PID or memfd kernel state against a malicious
producer/operator. Such a threat model requires an independently signed supervisor/provider/TPM witness. The
receipt also does not turn the unprivileged behavioral proof into byte-for-byte kernel-filter introspection.

## Stateful revalidation

`capture-runtime` collects the selected mode after isolation is active. Every later maintained stateful command
reopens and validates `runtime.json`, then recollects the current cgroup, GPU, clean exact commit, and network
isolation:

- once before work; and
- once immediately before its success record is committed to `commands.jsonl`.

For seccomp mode, recollection reruns all six denied-socket probes and verifies the collector/policy identities
and kernel status. The sealed launcher receipt is independently revalidated at both driver boundaries. Any mode
change, implementation or expected-policy change, receipt/argv drift, filter-count change, missing `NoNewPrivs`, newly available
network/Unix socket, cgroup drift, GPU drift, or commit drift is a hard failure. A failed command is not appended
to the success-only ledger.

## Invocation

After immutable resources and provider evidence are present, every recorded command, beginning with
`capture-runtime`, is invoked as:

```text
<pinned-python> -I scripts/compose/run_network_isolated.py -- \
  <pinned-python> -I scripts/compose/gears_decision_probe.py <subcommand> ...
```

The same exact interpreter and clean checkout are used for both processes; both processes fail unless Python
reports the complete `-I` flag set, user-site is disabled, and import/loader overrides are absent. No shell evaluation, command
substitution, proxy exception, network fallback, or unwrapped stateful command is allowed. Environments capable
of creating a proved lo-only namespace may retain that stronger outer boundary, but every maintained command
still uses this launcher and records its additional seccomp receipt. Runtime mode may not switch within one
evidence root.

## Verification and release consequences

Local tests must cover exact BPF construction, non-x86 rejection, both runtime schemas, missing kernel
preconditions, invalid probe results, collector/policy mismatch, capability allowlist violations, sealed-receipt
and launcher-argv tampering, non-isolated Python, import/loader overrides, alternate interpreter/wrapper/driver,
cross-command Python drift, and command-boundary drift. The Linux gate has two independently named tests:

1. a primitive test installs the real filter, proves closure of an inherited descriptor, creates and
   live-validates a genuinely sealed receipt, and proves IPv4/IPv6 and Unix stream/datagram denial, denial of a
   pre-existing socket's `connect`, non-`AF_UNIX` `socketpair`, x32 socket, `io_uring_setup`, and `pidfd_getfd`,
   while retaining `AF_UNIX socketpair`; and
2. an end-to-end test invokes the exact maintained launcher and driver as subprocesses, crosses the real
   `execve` boundary, and requires the driver to live-validate the same-PID receipt before emitting a bounded,
   non-scientific `isolation-self-check`. It reads no scientific input and writes no command ledger.

Those two Linux tests jointly establish the kernel primitives and activation-time launcher wiring; every other
test in the roster exercises schema, argv, receipt, and validator logic against recorded values. Both are
`skipif`-ed off any non-Linux host, so **a green suite on macOS or any other non-Linux developer machine is not
evidence that the complete isolation gate holds**. A non-Linux run is therefore never recorded as isolation
verification.

The kernel property is consequently established by CI on a real x86_64 Linux kernel, not by a developer host.
`.github/workflows/test-suite.yml` asserts the runner architecture before doing anything else, and then builds a
canonical `compose_kernel_isolation_ci_receipt_v1` from its JUnit report. Receipt profile
`x86_64_seccomp_primitives_and_launcher_wiring_v2` requires the exact classname/name roster for both tests and
fails on a skip, failure, error, duplicate, missing case, architecture mismatch, or inconsistent suite total. The
receipt binds the exact head/workflow SHAs, run identity, kernel release, JUnit SHA and required case results.
The uploaded JUnit/receipt artifact is expiring transport only. Before operational approval, an independent
reviewer must download it, verify the source artifact digest and receipt, and commit a self-checksummed
`compose_kernel_isolation_ci_archive_v1` under `docs/activation-evidence/compose`. A run URL or green badge alone
is not durable evidence. The registered archive importer must read the downloaded ZIP itself, require its exact
JUnit/receipt member roster, cross-bind both files to the reviewed receipt, and publish the archive write-once;
manual reconstruction is not accepted for v2. Dated historical/current status belongs in
`../COMPOSE-SEAL-READINESS.md`; even a durable CI receipt never substitutes for a production pod's own
`capture-runtime` evidence.

Because this implementation changes producer and verifier decision code, every earlier verifier source closure,
OCI digest, owner approval, image lock, and verifier pin is historical. Operational use requires a new clean
commit, a freshly built and signed verifier image, a new owner-frozen image lock, and independent recomputation.
It does not authorize Probe A, a sealed evaluation, or a scientific run by itself.
