"""ExecutionIdentityLock assembler + subprocess backend factory (spec §5).

This module resolves COMPOSE forward-obligation #2: the driver assembles each
deep-baseline method's 6-field :class:`ExecutionIdentityLock` from
**controller-side re-hashed real file bytes**, not from the ResolvedRunSpec's
declared values. The ResolvedRunSpec declarations are *expected* values; the
ground truth is what the driver hashes off disk. Any divergence between a
declared digest and the actual bytes fails closed. The worker's own self-report
is verified against this lock at predict time by
:func:`alive.compose.baseline_subprocess._verify_execution_manifest` — never the
reverse.

Field sources (spec §5 table), each a controller-side stream-hash of a real
``{path, sha256}`` file a :class:`~alive.compose.driver.run_spec.WorkerBlock`
carries:

======================== ===========================================
lock field                source
======================== ===========================================
prediction_representation committed config ``baseline_representations[name]``
adapter_sha256            stream-hash of the SEPARATE ``adapter_artifact`` file
config_sha256             stream-hash of the worker-config file
resource_sha256           stream-hash of the resource-manifest file
environment_lock_sha256   stream-hash of the requirements-lock file
adapter_version           a SEPARATE committed versioned adapter manifest
======================== ===========================================

``adapter_sha256`` is the digest of the ``adapter_artifact`` (adapter/model
content) — NOT the launched ``worker_script``. The committed runtime keeps these
two identities distinct: ``baseline_subprocess._verify_execution_manifest``
compares the lock's ``adapter_sha256`` against the worker's self-reported
``_ADAPTER_SHA256`` (adapter content), and re-hashes the launched
``worker_script`` file separately as ``worker_sha256`` (spec §2.2 / §5). Hashing
``worker_script`` into ``adapter_sha256`` would make the runtime reject every
real worker. ``worker_script`` is still re-hashed here for its node-kind policy
and declared-digest cross-check, but it feeds no lock field.

``adapter_version`` has no committed versioned source yet (sub-project B ships
it pod-side), so the **scientific** assembler fails closed. The **fixture**
assembler uses the fixture-trusted value declared in the worker block (which
mirrors the committed stub worker's ``_ADAPTER_VERSION``).

Node-kind trust boundary (carry-forward from the Task-1 review): Task 1's loader
applies only *lexical* containment to worker paths. This assembler is the sole
enforcer of the node-kind policy on worker files: when it opens each file to
hash it, a symlink / device / FIFO / non-regular node fails closed
(``lstat`` pre-check + ``O_NOFOLLOW``/``O_NONBLOCK`` open + ``fstat`` verify).

This module opens no seal, constructs no ``ComposeOutcomeStore``, and imports no
``gears`` / ``cpa`` — it only assembles the identity and the (unconfigured)
subprocess backend object; the worker itself runs as a subprocess elsewhere.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §5.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Mapping

from alive.compose.baseline_subprocess import (
    PREDICTION_REPRESENTATIONS,
    ExecutionIdentityLock,
    SubprocessBaselineBackend,
)
from alive.compose.driver.run_spec import (
    EXECUTION_IDENTITY_LOCK_KEYS,
    ResolvedRunSpec,
    WorkerBlock,
)
from alive.compose.worker_bundle import WorkerBundleError, validate_worker_bundle

__all__ = [
    "AssemblerError",
    "DEEP_BASELINE_METHODS",
    "assemble_execution_identity_lock",
    "build_subprocess_backend",
    "assemble_baseline_backends",
]

#: The exact deep-baseline subprocess method roster (mirrors
#: ``phase2a._DEEP_BASELINE_NAMES`` and the config's frozen roster; a governance
#: constant fixed by the ``COMPOSE-K562-v1`` protocol).
DEEP_BASELINE_METHODS: frozenset[str] = frozenset({"gears", "cpa"})

#: The committed, versioned adapter manifest that would pin each method's
#: ``adapter_version``. Sub-project B ships it pod-side; until then it is
#: ``None`` and the scientific assembler fails closed — there is no trusted
#: committed source for the version (spec §5).
_COMMITTED_ADAPTER_MANIFEST: Path | None = None

_HASH_CHUNK = 1 << 20


class AssemblerError(ValueError):
    """Raised on ANY ExecutionIdentityLock / backend assembly failure (fail-closed).

    Subclasses :class:`ValueError`. Raised for an unregistered / mismatched
    prediction representation, a declared digest that diverges from the actual
    re-hashed worker bytes, a worker file that violates the node-kind policy, an
    absent committed adapter manifest in scientific mode, or a subprocess method
    roster that is not exactly ``{'gears', 'cpa'}``.
    """


# --------------------------------------------------------------------------- #
# Node-kind-safe streaming hash
# --------------------------------------------------------------------------- #


def _hash_regular_file(path: str, *, field: str) -> str:
    """Stream the SHA-256 of a *regular* file, failing closed on non-regular nodes.

    The Task-1 loader validated only lexical containment of worker paths, so this
    assembler is the sole enforcer of the node-kind policy on the bytes it hashes
    (spec §2.2 path policy, applied to worker files). A symlink, device, FIFO,
    socket or directory fails closed. ``lstat`` rejects a symlink at the final
    component before opening; ``O_NOFOLLOW`` closes the lstat→open TOCTOU window
    for a symlink swapped in afterwards; ``O_NONBLOCK`` prevents a FIFO swap from
    blocking the open; and a post-open ``fstat`` re-verifies the descriptor is a
    regular file before any bytes are read.

    Parameters
    ----------
    path : str
        Absolute path to the worker file to hash.
    field : str
        Human-readable field name (for diagnostics).

    Returns
    -------
    str
        Lowercase 64-hex SHA-256 of the file's bytes.

    Raises
    ------
    AssemblerError
        If the path is not absolute, contains ``..``, does not exist, is a
        symlink / device / FIFO / non-regular node, or cannot be read.
    """
    if not isinstance(path, str) or not os.path.isabs(path):
        raise AssemblerError(f"{field}: worker file path must be absolute: {path!r}")
    if ".." in Path(path).parts:
        raise AssemblerError(f"{field}: worker file path must not contain '..': {path}")
    try:
        pre = os.lstat(path)
    except OSError as exc:
        raise AssemblerError(f"{field}: cannot stat worker file {path}: {exc}") from exc
    if stat.S_ISLNK(pre.st_mode):
        raise AssemblerError(f"{field}: worker file is a symlink (node-kind policy): {path}")
    if not stat.S_ISREG(pre.st_mode):
        raise AssemblerError(
            f"{field}: worker file is not a regular file (node-kind policy): {path}"
        )
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise AssemblerError(f"{field}: cannot open worker file {path}: {exc}") from exc
    try:
        post = os.fstat(fd)
        if not stat.S_ISREG(post.st_mode):
            raise AssemblerError(
                f"{field}: worker file is not a regular file (node-kind policy): {path}"
            )
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, _HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def _require_equal(declared: str, actual: str, *, field: str) -> None:
    """Fail closed unless a declared (expected) digest equals the actual re-hash."""
    if declared != actual:
        raise AssemblerError(
            f"{field}: declared digest diverges from actual worker bytes "
            f"(declared={declared!r} actual={actual!r})"
        )


# --------------------------------------------------------------------------- #
# adapter_version resolution
# --------------------------------------------------------------------------- #


def _fixture_adapter_version(declared_lock: Mapping[str, str]) -> str:
    """Return the fixture-trusted ``adapter_version`` declared in the worker block.

    In fixture mode the committed fixture builder is the trusted source, so the
    version is taken from the worker block's ``execution_identity_lock``. There
    is no re-hashable "actual" for a semantic version string; the runtime
    manifest verification enforces the worker's self-report agreement later.
    """
    version = declared_lock.get("adapter_version")
    if not isinstance(version, str) or not version:
        raise AssemblerError("fixture adapter_version must be a non-empty string")
    return version


def _scientific_adapter_version() -> str:
    """Fail closed: no committed versioned adapter manifest exists yet (§5).

    Sub-project B must ship a committed versioned adapter manifest before a
    scientific ExecutionIdentityLock can be assembled. Until
    :data:`_COMMITTED_ADAPTER_MANIFEST` is wired, ``adapter_version`` has no
    trusted committed source and the scientific assembler refuses to proceed.
    """
    if _COMMITTED_ADAPTER_MANIFEST is None:
        raise AssemblerError(
            "scientific ExecutionIdentityLock cannot be assembled: no committed "
            "versioned adapter manifest exists yet (sub-project B must ship it); "
            "adapter_version has no trusted committed source"
        )
    # When sub-project B ships the manifest, resolve + verify the version here.
    raise AssemblerError(  # pragma: no cover - unreachable until the manifest is wired
        "scientific adapter_version resolution is not implemented"
    )


# --------------------------------------------------------------------------- #
# Public assembler
# --------------------------------------------------------------------------- #


def assemble_execution_identity_lock(
    worker_block: WorkerBlock,
    *,
    config_representation: str,
    fixture: bool,
    expected_worker_method: str | None = None,
) -> ExecutionIdentityLock:
    """Assemble a method's 6-field :class:`ExecutionIdentityLock` from real bytes.

    Every digest field is the driver's own stream-hash of the actual worker file
    (node-kind-checked), and the worker block's *declared* digests — both the
    ``{path, sha256}`` declaration and the ``execution_identity_lock`` declaration
    — must equal that actual value or the assembly fails closed. Task 1 did not
    verify worker file digests, so both declarations are cross-checked here.

    Parameters
    ----------
    worker_block : WorkerBlock
        The validated per-method worker block from the ResolvedRunSpec loader.
    config_representation : str
        The prediction representation registered for this method in the committed
        config's ``baseline_representations``. Must be a member of
        :data:`~alive.compose.baseline_subprocess.PREDICTION_REPRESENTATIONS` and
        must equal the block's declared ``prediction_representation``.
    fixture : bool
        ``True`` for the fixture path (``adapter_version`` from the fixture-trusted
        worker block); ``False`` for the scientific path (fails closed — no
        committed versioned adapter manifest).
    expected_worker_method : str, optional
        Registered method name used to validate a scientific execution bundle's
        internal manifest. Required for scientific mode; ignored for a direct
        fixture ``.py`` worker.

    Returns
    -------
    ExecutionIdentityLock
        The controller-trusted, out-of-band worker execution identity.

    Raises
    ------
    AssemblerError
        On an unregistered / mismatched representation, a declared-vs-actual
        digest divergence, a node-kind violation on any worker file, or (in
        scientific mode) the absent committed adapter manifest.
    """
    if not isinstance(worker_block, WorkerBlock):
        raise AssemblerError("worker_block must be a WorkerBlock instance")

    # 1. prediction representation -------------------------------------------
    if config_representation not in PREDICTION_REPRESENTATIONS:
        raise AssemblerError(
            f"config prediction representation {config_representation!r} is not registered"
        )
    declared = worker_block.execution_identity_lock
    if set(declared) != set(EXECUTION_IDENTITY_LOCK_KEYS):
        raise AssemblerError("worker block execution_identity_lock has an unexpected key set")
    if declared.get("prediction_representation") != config_representation:
        raise AssemblerError(
            "declared prediction_representation diverges from the config representation "
            f"(declared={declared.get('prediction_representation')!r} "
            f"config={config_representation!r})"
        )

    # 2. re-hash the worker files (node-kind enforced) -----------------------
    # ``adapter_sha256`` is sourced from the SEPARATE ``adapter_artifact`` file,
    # NOT the launched ``worker_script`` (spec §5). ``worker_script`` is still
    # re-hashed for its node-kind policy + declared-digest cross-check, but it
    # feeds no lock field — the runtime verifies it separately as
    # ``worker_sha256``.
    actual_worker_script = _hash_regular_file(
        worker_block.worker_script.path, field="worker_script"
    )
    actual_adapter = _hash_regular_file(
        worker_block.adapter_artifact.path, field="adapter_artifact"
    )
    actual_config = _hash_regular_file(worker_block.worker_config.path, field="worker_config")
    actual_resource = _hash_regular_file(
        worker_block.resource_manifest.path, field="resource_manifest"
    )
    actual_env = _hash_regular_file(worker_block.requirements_lock.path, field="requirements_lock")

    # 3. cross-check the declared {path, sha256} digests (Task 1 skipped these)
    _require_equal(
        worker_block.worker_script.sha256, actual_worker_script, field="worker_script.sha256"
    )
    _require_equal(
        worker_block.adapter_artifact.sha256, actual_adapter, field="adapter_artifact.sha256"
    )
    _require_equal(worker_block.worker_config.sha256, actual_config, field="worker_config.sha256")
    _require_equal(
        worker_block.resource_manifest.sha256, actual_resource, field="resource_manifest.sha256"
    )
    _require_equal(
        worker_block.requirements_lock.sha256, actual_env, field="requirements_lock.sha256"
    )

    # Scientific workers are self-contained deterministic execution bundles:
    # their existing worker_script SHA therefore binds both the entrypoint and
    # every ALIVE runtime helper. Fixture/local unit tests may still exercise a
    # direct .py worker, while fixture bundles are validated whenever supplied.
    is_bundle = worker_block.worker_script.path.endswith(".pyz")
    if not fixture and not is_bundle:
        raise AssemblerError("scientific worker_script must be a deterministic .pyz bundle")
    if not fixture and expected_worker_method not in DEEP_BASELINE_METHODS:
        raise AssemblerError("scientific worker bundle requires its registered method name")
    if is_bundle:
        try:
            validate_worker_bundle(
                worker_block.worker_script.path,
                expected_method=expected_worker_method if not fixture else None,
                expected_sha256=actual_worker_script,
            )
        except WorkerBundleError as exc:
            raise AssemblerError(f"worker execution bundle is invalid: {exc}") from exc

    # 4. cross-check the declared lock digests -------------------------------
    # The declared ``adapter_sha256`` is compared to the re-hashed
    # ``adapter_artifact`` (not the worker_script) — divergence fails closed.
    _require_equal(declared["adapter_sha256"], actual_adapter, field="adapter_sha256")
    _require_equal(declared["config_sha256"], actual_config, field="config_sha256")
    _require_equal(declared["resource_sha256"], actual_resource, field="resource_sha256")
    _require_equal(declared["environment_lock_sha256"], actual_env, field="environment_lock_sha256")

    # 5. adapter_version -----------------------------------------------------
    if fixture:
        adapter_version = _fixture_adapter_version(declared)
    else:
        adapter_version = _scientific_adapter_version()

    return ExecutionIdentityLock(
        prediction_representation=config_representation,
        adapter_version=adapter_version,
        adapter_sha256=actual_adapter,
        config_sha256=actual_config,
        resource_sha256=actual_resource,
        environment_lock_sha256=actual_env,
    )


def build_subprocess_backend(
    worker_block: WorkerBlock,
    lock: ExecutionIdentityLock,
    *,
    name: str,
    approved_artifacts_root: str,
    expected_response_artifact_sha256: str,
    allow_local_approved_root_checkpoint_store: bool = False,
    seed: int = 11,
) -> SubprocessBaselineBackend:
    """Build an **unconfigured** subprocess backend carrying the assembled lock.

    The backend has no fit-role payload yet — Task 7 (phase2a) later calls
    :func:`alive.compose.phase2a.build_subprocess_fit_payload` and
    ``backend.configure_payload(...)`` before wrapping it in a ``BaselineAdapter``.
    This factory only wires the immutable execution identity onto the backend.

    Parameters
    ----------
    worker_block : WorkerBlock
        The per-method worker block (source of ``env_python`` / ``worker_script``
        / ``import_name``).
    lock : ExecutionIdentityLock
        The lock assembled by :func:`assemble_execution_identity_lock`.
    name : str
        The method name (e.g. ``"gears"`` / ``"cpa"``).
    approved_artifacts_root : str
        The out-of-band approved artifacts root.
    expected_response_artifact_sha256 : str
        The response-space checksum the backend is bound to.
    allow_local_approved_root_checkpoint_store : bool, optional
        Fixture/local-only compatibility store. Scientific assembly leaves this
        false so the immutable approved-input root can never be mutated.
    seed : int, optional
        The base seed for the backend (default ``11``).

    Returns
    -------
    SubprocessBaselineBackend
        The unconfigured backend carrying ``lock`` as out-of-band ground truth.
    """
    if not isinstance(lock, ExecutionIdentityLock):
        raise AssemblerError("lock must be an ExecutionIdentityLock instance")
    return SubprocessBaselineBackend(
        name=name,
        env_python=worker_block.env_python,
        worker_script=worker_block.worker_script.path,
        import_name=worker_block.import_name,
        seed=int(seed),
        approved_artifacts_root=approved_artifacts_root,
        expected_response_artifact_sha256=expected_response_artifact_sha256,
        execution_identity_lock=lock,
        expected_worker_sha256=worker_block.worker_script.sha256,
        allow_local_approved_root_checkpoint_store=allow_local_approved_root_checkpoint_store,
        worker_identity_paths={
            "worker_config": worker_block.worker_config.path,
            "resource_manifest": worker_block.resource_manifest.path,
            "requirements_lock": worker_block.requirements_lock.path,
            "adapter_artifact": worker_block.adapter_artifact.path,
        },
    )


def assemble_baseline_backends(
    run_spec: ResolvedRunSpec,
    *,
    fixture: bool,
    representations: Mapping[str, str],
    seed: int = 11,
) -> dict[str, SubprocessBaselineBackend]:
    """Assemble the ``{gears, cpa}`` unconfigured subprocess backends for a run.

    Enforces the exact deep-baseline roster (spec §3.1: the subprocess worker
    blocks must be exactly ``{'gears', 'cpa'}``), then assembles each backend's
    :class:`ExecutionIdentityLock` from re-hashed real bytes and wires it onto an
    unconfigured backend bound to the run's approved root and response-space
    checksum.

    Parameters
    ----------
    run_spec : ResolvedRunSpec
        The validated, immutable run spec (source of ``worker_blocks``,
        ``approved_artifacts_root`` and ``expected_hashes``).
    fixture : bool
        Whether to assemble in fixture mode; MUST agree with ``run_spec.mode``.
    representations : Mapping[str, str]
        Method -> prediction representation, from the committed config's
        ``baseline_representations``.
    seed : int, optional
        The base seed for each backend (default ``11``).

    Returns
    -------
    dict[str, SubprocessBaselineBackend]
        The ``{gears, cpa}`` unconfigured backends, each carrying its lock.

    Raises
    ------
    AssemblerError
        If ``fixture`` disagrees with ``run_spec.mode``, the worker-block roster
        is not exactly ``{'gears', 'cpa'}``, a representation is missing, or any
        per-method lock assembly fails closed.
    """
    if fixture != (run_spec.mode == "fixture"):
        raise AssemblerError(
            f"fixture flag {fixture!r} disagrees with run_spec.mode {run_spec.mode!r}"
        )
    methods = set(run_spec.worker_blocks)
    if methods != DEEP_BASELINE_METHODS:
        raise AssemblerError(
            f"subprocess worker blocks must be exactly {{'gears', 'cpa'}}; got {sorted(methods)}"
        )
    expected_response = run_spec.expected_hashes.get("response_space_checksum")
    if not isinstance(expected_response, str) or not expected_response:
        raise AssemblerError("run_spec.expected_hashes lacks a response_space_checksum")
    root = run_spec.approved_artifacts_root

    backends: dict[str, SubprocessBaselineBackend] = {}
    for method, block in run_spec.worker_blocks.items():
        representation = representations.get(method)
        if not isinstance(representation, str) or not representation:
            raise AssemblerError(f"no config representation registered for method {method!r}")
        lock = assemble_execution_identity_lock(
            block,
            config_representation=representation,
            fixture=fixture,
            expected_worker_method=method,
        )
        backends[method] = build_subprocess_backend(
            block,
            lock,
            name=method,
            approved_artifacts_root=root,
            expected_response_artifact_sha256=expected_response,
            allow_local_approved_root_checkpoint_store=fixture,
            seed=seed,
        )
    return backends
