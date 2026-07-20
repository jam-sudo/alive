# COMPOSE Probe-A verifier root-of-trust design

**Status:** IMPLEMENTED LOCALLY / OPERATIONAL IMAGE NOT YET FROZEN
**Scope:** offline verification and PASS-only admission publication; no Probe-A fit, sealed evaluation, or
scientific run is authorized by this document.

## 1. Decision

The operational verifier SHALL run from one owner-approved, single-platform OCI image reference qualified by
an immutable `sha256:` digest. The owner additionally freezes a canonical image-lock file and its external
SHA-256. The lock binds the clean Git commit, verifier source/runtime closure, Dockerfile, `uv.lock`, platform,
digest-qualified Python and uv build images, exact OCI object digest, and Sigstore verification material.

The earlier Python source/runtime closure remains mandatory as a diagnostic and review identity, but it is no
longer sufficient for operational approval. It cannot authenticate `.pth` startup hooks, the Python standard
library, dynamic loader, or native libraries that may execute before the verifier computes its own hash. The OCI
digest covers those bytes before Python starts.

## 2. Threat model and residual trust

This design closes mutable tag resolution, host Python startup injection, unpinned base images, repository
mount substitution, online dependency resolution during verification, and writable verifier-root mutation. It
does **not** claim VM-grade isolation. The owner still trusts the OCI engine/daemon, host kernel, CPU, filesystem,
and the independently approved build/signing controls. A hostile root/daemon can lie about or replace a
container; that threat requires a separately attested VM or confidential-computing boundary.

Cosign is defense in depth around the digest, not a substitute for the external owner digest pin. The signed blob
is a canonical approval subject that binds the image reference/digest, Git commit, platform, build images,
Dockerfile, `uv.lock`, and verifier closure. Its subject, executable, offline bundle, trusted-root file, certificate
identity, and OIDC issuer are all locked. The OCI engine itself is an explicit trusted-computing-base component
because hashing the client binary would not authenticate its daemon.

## 3. Exact contracts

`compose_probe_a_verifier_image_lock_v1` is canonical compact JSON plus one final LF. It has exactly:

```text
schema, protocol, git_commit, image_reference, image_manifest_digest, platform,
python_base_image, uv_build_image, dockerfile_sha256, uv_lock_sha256,
verifier_code_sha256, signature, approved_at_utc, approval_id, self_checksum
```

`image_reference` and both build images use `name@sha256:<64 lowercase hex>`. `platform` is exactly
`linux/amd64` or `linux/arm64`. `image_reference` ends in `image_manifest_digest`; the digest may identify a
single image manifest or a fixed OCI index whose selected platform member is immutable. Multi-platform ambiguity
is avoided operationally by building and approving one target platform at a time.

`signature` is exactly:

```text
schema, mode, subject_sha256, bundle_sha256, cosign_executable_sha256, trusted_root_sha256,
certificate_identity, oidc_issuer
```

Only `cosign_keyless_subject_bundle_v1` is admitted. The subject uses schema
`compose_probe_a_verifier_signature_subject_v1`, exact keys matching the decision-bearing lock identity, compact
canonical JSON, and one final LF. The external image-lock SHA is not stored inside the lock; it is recorded
independently before the verifier is run. Recomputing `self_checksum` never authorizes a changed lock.

Positive receipts use `compose_gears_probe_a_verification_v3`; negative receipts use
`compose_gears_probe_a_negative_verification_v3`. Both add `verifier_image_digest` and
`verifier_image_lock_sha256`. Thus a durable receipt identifies both the exact executing image expected by the
launcher and the separately frozen owner lock.

## 4. Build, approval, and run sequence

1. Start from the final clean exact Git commit. No scientific output has been inspected for this registration.
2. Resolve the Python base and uv build inputs to target-platform digests. Tags alone are forbidden.
3. Build `containers/compose-probe-a-verifier/Dockerfile` for one platform from the restricted `.dockerignore`
   context with `ALIVE_GIT_COMMIT=<exact SHA>`. Network may be used only at build time; `uv sync --frozen` must
   consume the committed lock. The builder must provide an isolated build root through Docker/BuildKit, a
   privileged rootful Buildah environment, or an equivalent dedicated build VM. **Never execute Kaniko directly
   in the scientific pod's own root filesystem**: Kaniko uses the current container root as its build root and can
   delete or replace that runtime filesystem between stages. A scientific/verification pod is not an image builder.
4. Inside the candidate image run only `--print-verifier-code-sha256`, record the result, and independently
   compare it with a second computation from the same candidate. This diagnostic does not approve the image.
5. Push the immutable candidate and record its digest-qualified reference. Use
   `build_probe_a_verifier_signature_subject.py` to create the canonical approval subject, then `cosign sign-blob`
   that subject and export its bundle. Preserve trusted-root bytes and independently pin the Cosign executable.
6. Use `scripts/compose/build_probe_a_verifier_image_lock.py` with that exact subject/bundle to construct canonical write-once image-lock bytes,
   validate every exact key/digest, and record the printed external SHA-256 in the owner registration channel.
   Freeze the lock; any edit requires a new approval ID and new external pin.
7. On the review host, preload the exact image. Verify the lock, Cosign material, identity/issuer, and local
   `RepoDigests`; do not pull during the decision-bearing run.
8. Invoke `scripts/compose/run_gears_probe_a_verifier_oci.py`. It runs the image with no network, read-only root,
   all capabilities dropped, no-new-privileges, resource limits, fixed non-root UID/GID `65532:65532`, and only
   the evidence directory writable. The operator must prepare that bind for UID 65532 without making the broader
   repository writable; the repository is never mounted.
9. Independently validate the resulting v3 receipt against the externally recorded image-lock SHA and image
   digest. PASS may publish admission last; a negative result must leave admission absent.

No operational verifier image lock is committed yet. Until steps 2–7 are completed on an approved Linux build
host, Probe-A remains release-blocked.

## 5. Comparison with the original and alternatives

| Candidate | Closes pre-Python startup gap | Hermetic runtime identity | Independent rebuild potential | Operational cost | Decision |
|---|---:|---:|---:|---:|---|
| Python source/runtime self-closure | No | Partial | Low | Low | Retain as diagnostic only |
| Python `-I`/`-B` alone | No | Partial | Low | Low | Use inside image, never as root of trust |
| PEX/zipapp | No; still uses host interpreter/loader | Partial | Medium | Medium | Reject for operational root |
| PyInstaller/static-style bundle | Partly; still trusts host kernel/loader | Better | Medium/low with native wheels | Medium | Reserve only if OCI unavailable |
| Digest-pinned OCI + signed offline approval subject | Yes for image bytes | High, subject to host engine/kernel | Medium | Medium | **Selected now** |
| Nix/Guix-built OCI with two independent rebuilders | Yes | High | High when bit-reproducible | High | **Best next candidate** |
| Attested VM/microVM/confidential VM | Yes, plus stronger host separation | Highest for hostile-host model | Medium | Very high | Use only if host/daemon leaves trust boundary |

`-I` is still valuable inside the selected image because it ignores `PYTHON*`, excludes the script directory and
user site from `sys.path`, and implies `-E`, `-P`, and `-s`; it is layered defense, not image authentication.

## 6. Better-candidate exploration gate

The next improvement should be a reproducible Nix/Guix derivation that emits the same minimal OCI payload on two
independent builders. Promotion requires byte-identical image/config/layer digests or an explained, owner-approved
normalization delta. This is superior to merely signing one builder's output because it detects a compromised
builder, but it must not delay the current digest-pinned OCI gate unless the owner expands the threat model.

Before adopting a native binary bundle, benchmark whether `anndata`, HDF5, NumPy, SciPy, and their native shared
libraries can be inventoried and reproduced more transparently than in the OCI/Nix path. Packaging convenience
alone is not a scientific-integrity gain.

## 7. Acceptance tests

- Reject tags, digest/reference disagreement, unknown platform, malformed/non-canonical/symlink locks, altered
  external SHA, wrong clean commit, wrong source closure, unsigned modes, and altered Cosign/trusted-root bytes.
- Assert the runtime command contains `--pull=never`, `--network=none`, `--read-only`, `--cap-drop=ALL`,
  `no-new-privileges`, non-root identity, limits, one evidence bind, and no repository bind.
- Assert positive and negative receipts reject either image field when absent, malformed, or inconsistent with
  externally pinned expectations.
- Execute the full local Compose suite plus Ruff check/format-check without producing caches or changing tracked
  files. An actual OCI build/sign/inspect/run test is a separate Linux build-host gate.

## 8. Primary references

- Python isolated mode (`-I` implies `-E`, `-P`, `-s`): <https://docs.python.org/3.12/using/cmdline.html>
- Docker run isolation controls: <https://docs.docker.com/reference/cli/docker/container/run>
- Docker `none` network semantics: <https://docs.docker.com/engine/network/drivers/none/>
- Sigstore blob signing and bundle verification: <https://docs.sigstore.dev/quickstart/quickstart-cosign/>
- Sigstore/Cosign verification claims: <https://docs.sigstore.dev/cosign/verifying/verify/>
- Nix reproducible-build rationale and rebuild checks: <https://reproducible.nixos.org/>
