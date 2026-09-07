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

``adapter_version`` is resolved from the committed, method-keyed manifest
``configs/compose_adapter_versions_v1.json`` (schema
``compose_adapter_versions_v1``, roster exactly ``{gears, cpa}``): the
**scientific** assembler reads it out of the repository, requires the declared
lock's ``adapter_version`` to equal the manifest's value for the method, and
fails closed on an unknown method or a malformed / absent manifest. It is a
separate committed file from the phase-2 config, so wiring it moves no
``config_sha256``. The **fixture** assembler still uses the fixture-trusted
value declared in the worker block (which mirrors the committed stub worker's
``_ADAPTER_VERSION``). The manifest pins the adapter **API semantic identity**,
not a model hyperparameter; agreement between it and a real pod-built ``.pyz``
worker's self-reported ``_ADAPTER_VERSION`` remains a pod-side parity check
performed by ``baseline_subprocess._verify_execution_manifest`` at predict time.

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
from typing import Any, Mapping

from alive.compose.baseline_subprocess import (
    PREDICTION_REPRESENTATIONS,
    ExecutionIdentityLock,
    SubprocessBaselineBackend,
)
from alive.compose.driver.preseal_read import read_verified_json
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

#: Repository root, resolved from this module's own location (the pattern
#: ``driver/fixture_builder.py`` already uses for ``scripts/baselines/``); never a
#: caller-supplied or hardcoded absolute path.
_REPO_ROOT = Path(__file__).resolve().parents[4]

#: The committed, versioned adapter manifest that pins each method's
#: ``adapter_version``. A SEPARATE committed file from the phase-2 config, so it
#: carries its own identity and moves no ``config_sha256`` (spec §5).
_COMMITTED_ADAPTER_MANIFEST: Path = _REPO_ROOT / "configs" / "compose_adapter_versions_v1.json"

#: The exact schema string the committed adapter manifest must declare.
_ADAPTER_MANIFEST_SCHEMA = "compose_adapter_versions_v1"

#: The exact top-level key set the committed adapter manifest must carry.
_ADAPTER_MANIFEST_KEYS = frozenset({"schema", "methods"})

_HASH_CHUNK = 1 << 20


class AssemblerError(ValueError):
    """Raised on ANY ExecutionIdentityLock / backend assembly failure (fail-closed).

    Subclasses :class:`ValueError`. Raised for an unregistered / mismatched
    prediction representation, a declared digest that diverges from the actual
    re-hashed worker bytes, a worker file that violates the node-kind policy, an
    absent / malformed committed adapter manifest (or a declared
    ``adapter_version`` that diverges from it) in scientific mode, or a
    subprocess method roster that is not exactly ``{'gears', 'cpa'}``.
    """


# --------------------------------------------------------------------------- #
# Node-kind-safe streaming hash
# --------------------------------------------------------------------------- #


def _hash_regular_file(path: str, *, field: str, noun: str = "worker file") -> str:
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
    noun : str, optional
        What the file is, for diagnostics only. Defaults to ``"worker file"``;
        the committed adapter-manifest lane passes its own noun so its
        fail-closed messages name what actually failed.

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
        raise AssemblerError(f"{field}: {noun} path must be absolute: {path!r}")
    if ".." in Path(path).parts:
        raise AssemblerError(f"{field}: {noun} path must not contain '..': {path}")
    try:
        pre = os.lstat(path)
    except OSError as exc:
        raise AssemblerError(f"{field}: cannot stat {noun} {path}: {exc}") from exc
    if stat.S_ISLNK(pre.st_mode):
        raise AssemblerError(f"{field}: {noun} is a symlink (node-kind policy): {path}")
    if not stat.S_ISREG(pre.st_mode):
        raise AssemblerError(f"{field}: {noun} is not a regular file (node-kind policy): {path}")
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise AssemblerError(f"{field}: cannot open {noun} {path}: {exc}") from exc
    try:
        post = os.fstat(fd)
        if not stat.S_ISREG(post.st_mode):
            raise AssemblerError(
                f"{field}: {noun} is not a regular file (node-kind policy): {path}"
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


def _require_equal(
    declared: str,
    actual: str,
    *,
    field: str,
    subject: str = "digest",
    source: str = "actual worker bytes",
) -> None:
    """Fail closed unless a declared (expected) value equals the controller-resolved one.

    The defaults reproduce the digest lane's message verbatim. The
    ``adapter_version`` lane compares a semantic version string against the
    committed manifest rather than against a re-hash, so it overrides both nouns:
    an accurate message is part of failing closed legibly, and a second near-copy
    of this helper is exactly the duplication this repository keeps paying for.
    """
    if declared != actual:
        raise AssemblerError(
            f"{field}: declared {subject} diverges from {source} "
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


def _read_committed_adapter_manifest() -> dict[str, Any]:
    """Read the committed adapter manifest, binding the parsed bytes to their digest.

    The file is hashed with this module's node-kind-safe streamer (so a symlink /
    device / FIFO / absent manifest fails closed exactly as a worker file does),
    and the parse then goes through
    :func:`~alive.compose.driver.preseal_read.read_verified_json` against that
    digest. That is deliberate rather than ceremonial: a plain re-open would let a
    swap between the hash and the parse go unnoticed, which is the defect shape
    ``preseal_read`` exists to close. Here it means the object returned is parsed
    from the same bytes that were hashed, or nothing is returned at all.

    Returns
    -------
    dict
        The parsed manifest object (not yet validated).

    Raises
    ------
    AssemblerError
        If the manifest is absent, a non-regular node, unreadable, changed between
        the hash and the parse, or is not a JSON object.
    """
    path = _COMMITTED_ADAPTER_MANIFEST
    digest = _hash_regular_file(
        str(path), field="adapter_manifest", noun="committed adapter manifest"
    )
    try:
        return read_verified_json(path, digest, field="adapter_manifest")
    except ValueError as exc:  # PresealBytesError (swap / non-object) or a JSON error
        raise AssemblerError(
            f"adapter_manifest: committed adapter manifest {path} is unusable: {exc}"
        ) from exc


def _scientific_adapter_version(method: str) -> str:
    """Resolve a method's ``adapter_version`` from the committed adapter manifest (§5).

    The scientific ``adapter_version`` has exactly one trusted source: the
    committed, method-keyed manifest at :data:`_COMMITTED_ADAPTER_MANIFEST`. The
    worker's own self-report is never that source — it is the thing being checked
    (module docstring; the runtime compares it to this lock at predict time).

    The manifest must declare schema ``compose_adapter_versions_v1``, carry
    exactly the top-level keys ``{schema, methods}``, and key its ``methods``
    roster to exactly :data:`DEEP_BASELINE_METHODS` with non-empty string values.
    The roster is required *exactly* — an extra method would let an unregistered
    worker acquire a committed identity, and a missing one would let a method run
    with no pinned adapter API at all.

    Parameters
    ----------
    method : str
        The registered deep-baseline method name (``"gears"`` / ``"cpa"``).

    Returns
    -------
    str
        The manifest's ``adapter_version`` for ``method``.

    Raises
    ------
    AssemblerError
        If ``method`` is not a non-empty string or is not a method the manifest
        registers, or if the manifest is absent / malformed in any way.
    """
    if not isinstance(method, str) or not method:
        raise AssemblerError("adapter_manifest: a scientific lock must name its method")
    manifest = _read_committed_adapter_manifest()
    if set(manifest) != set(_ADAPTER_MANIFEST_KEYS):
        raise AssemblerError(
            "adapter_manifest: committed adapter manifest must carry exactly "
            f"{{'methods', 'schema'}}; got {sorted(manifest)}"
        )
    if manifest["schema"] != _ADAPTER_MANIFEST_SCHEMA:
        raise AssemblerError(
            f"adapter_manifest: schema must be {_ADAPTER_MANIFEST_SCHEMA!r}; "
            f"got {manifest['schema']!r}"
        )
    methods = manifest["methods"]
    if not isinstance(methods, dict):
        raise AssemblerError("adapter_manifest: 'methods' must be a JSON object")
    if set(methods) != set(DEEP_BASELINE_METHODS):
        raise AssemblerError(
            "adapter_manifest: the manifest method roster must be exactly "
            f"{{'cpa', 'gears'}}; got {sorted(methods)}"
        )
    for name in sorted(methods):
        version = methods[name]
        if not isinstance(version, str) or not version:
            raise AssemblerError(
                f"adapter_manifest: adapter_version for method {name!r} must be a "
                f"non-empty string; got {version!r}"
            )
    if method not in methods:
        raise AssemblerError(
            f"adapter_manifest: the committed adapter manifest registers no method "
            f"{method!r} (registered: {sorted(methods)})"
        )
    return str(methods[method])


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
        worker block); ``False`` for the scientific path (``adapter_version`` from
        the committed method manifest, cross-checked against the declaration).
    expected_worker_method : str, optional
        Registered method name used to validate a scientific execution bundle's
        internal manifest and to key the committed adapter manifest. Required for
        scientific mode; ignored for a direct fixture ``.py`` worker.

    Returns
    -------
    ExecutionIdentityLock
        The controller-trusted, out-of-band worker execution identity.

    Raises
    ------
    AssemblerError
        On an unregistered / mismatched representation, a declared-vs-actual
        digest divergence, a node-kind violation on any worker file, or (in
        scientific mode) an absent / malformed committed adapter manifest, an
        unregistered method, or a declared ``adapter_version`` that diverges from
        the manifest.
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
    # Scientific mode has already required ``expected_worker_method`` to be a
    # member of DEEP_BASELINE_METHODS above, so the manifest lookup is always
    # keyed by a named method; the declared value is an *expectation* that must
    # agree with the committed manifest, never the source of it.
    if fixture:
        adapter_version = _fixture_adapter_version(declared)
    else:
        adapter_version = _scientific_adapter_version(expected_worker_method)
        _require_equal(
            declared["adapter_version"],
            adapter_version,
            field="adapter_version",
            subject="version",
            source="the committed adapter manifest",
        )

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
