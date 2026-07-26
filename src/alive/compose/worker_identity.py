"""Runtime verification of deep-worker config/resource/environment identities.

The production driver hashes these files independently when it assembles an
``ExecutionIdentityLock``.  It passes their paths and expected digests to the
isolated worker through a private environment contract; the worker reopens only
regular, non-symlink files, re-hashes their bytes, and reports those observed
identities.  A worker therefore cannot silently substitute a config or resource
while echoing a hard-coded placeholder digest.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import stat
import sys
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

_HEX = frozenset("0123456789abcdef")
_EXECUTABLE_PATH_ENV = "ALIVE_WORKER_EXECUTABLE_PATH"
_EXECUTABLE_SHA_ENV = "ALIVE_WORKER_EXECUTABLE_SHA256"
_BUNDLED_ALIVE_ORIGINS: Mapping[str, str] = MappingProxyType(
    {
        "alive": "alive/__init__.py",
        "alive.compose": "alive/compose/__init__.py",
        "alive.compose.baseline_subprocess": "alive/compose/baseline_subprocess.py",
        "alive.compose.baselines_combo": "alive/compose/baselines_combo.py",
        "alive.compose.fit_role": "alive/compose/fit_role.py",
        "alive.compose.response": "alive/compose/response.py",
        "alive.compose.roles": "alive/compose/roles.py",
        "alive.compose.worker_identity": "alive/compose/worker_identity.py",
        "alive.provenance": "alive/provenance.py",
    }
)


class WorkerIdentityError(RuntimeError):
    """Raised when runtime identity files do not match the controller lock."""


@dataclass(frozen=True)
class VerifiedWorkerExecutable:
    """Stable identity of the controller-selected worker executable snapshot."""

    path: str
    sha256: str
    is_bundle: bool


@dataclass(frozen=True)
class VerifiedWorkerIdentity:
    """Observed worker identity and parsed immutable worker config."""

    adapter_version: str
    adapter_sha256: str
    config_sha256: str
    resource_sha256: str
    environment_lock_sha256: str
    worker_config: Mapping[str, Any]
    resource_manifest: Mapping[str, Any]
    worker_executable_path: str
    worker_executable_sha256: str


def require_exact_worker_config(
    identity: VerifiedWorkerIdentity,
    *,
    expected: Mapping[str, Any],
) -> None:
    """Require exact agreement between registered JSON and worker semantics.

    Re-hashing a config proves byte identity, but not that the launched code
    implements the registered values. Real workers call this before reading fit
    data, so missing, unknown, or semantically divergent fields fail closed.
    """
    observed = dict(identity.worker_config)
    wanted = dict(expected)
    if not _json_values_exact(observed, wanted):
        raise WorkerIdentityError(
            "worker_config does not exactly match the launched worker contract "
            f"(expected_keys={sorted(wanted)}, observed_keys={sorted(observed)})"
        )


def _json_values_exact(observed: object, expected: object) -> bool:
    """Compare JSON-domain values without Python's bool/int coercions.

    Python considers ``True == 1`` and ``False == 0``.  A scientific config must
    not inherit that equivalence: JSON type, mapping/list structure, and even the
    sign bit of a floating zero are part of the registered runtime semantics.
    """
    if isinstance(observed, Mapping) and isinstance(expected, Mapping):
        if set(observed) != set(expected):
            return False
        return all(_json_values_exact(observed[key], expected[key]) for key in observed)
    if isinstance(observed, list) and isinstance(expected, list):
        return len(observed) == len(expected) and all(
            _json_values_exact(left, right) for left, right in zip(observed, expected)
        )
    if type(observed) is not type(expected):
        return False
    if isinstance(observed, float):
        return observed.hex() == expected.hex()
    return observed == expected


def require_distribution_version(*, distribution: str, expected: str) -> None:
    """Require the imported worker backend to come from the pinned distribution."""
    try:
        observed = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError as exc:
        raise WorkerIdentityError(
            f"required worker distribution is not installed: {distribution}"
        ) from exc
    if observed != expected:
        raise WorkerIdentityError(
            f"worker distribution {distribution!r} is {observed!r}, expected {expected!r}"
        )


def require_module_from_environment(module: object, *, expected_name: str) -> None:
    """Reject backend imports shadowed outside the launched Python environment."""
    if getattr(module, "__name__", None) != expected_name:
        raise WorkerIdentityError(f"worker backend module is not {expected_name!r}")
    origin = getattr(module, "__file__", None)
    if not isinstance(origin, str) or not os.path.isabs(origin):
        raise WorkerIdentityError(f"worker backend {expected_name!r} lacks an absolute origin")
    try:
        node = os.lstat(origin)
    except OSError as exc:
        raise WorkerIdentityError(f"cannot stat worker backend origin: {exc}") from exc
    if stat.S_ISLNK(node.st_mode) or not stat.S_ISREG(node.st_mode):
        raise WorkerIdentityError("worker backend origin must be a regular non-symlink file")
    prefix = os.path.realpath(sys.prefix)
    resolved = os.path.realpath(origin)
    try:
        within = os.path.commonpath([prefix, resolved]) == prefix and resolved != prefix
    except ValueError:
        within = False
    if not within:
        raise WorkerIdentityError(
            f"worker backend {expected_name!r} was imported outside sys.prefix"
        )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value:
        raise WorkerIdentityError(f"required worker identity variable is missing: {name}")
    return value


def _expected_digest(name: str) -> str:
    value = _required_env(name)
    if len(value) != 64 or any(char not in _HEX for char in value):
        raise WorkerIdentityError(f"{name} must be a lowercase 64-hex SHA-256")
    return value


def load_verified_worker_executable(
    *,
    require_argv_match: bool = True,
) -> VerifiedWorkerExecutable:
    """Re-hash the controller-selected executable and bind it to this process.

    Normal worker execution requires ``sys.argv[0]`` to be the exact snapshot
    path.  The isolated availability probe imports helpers from the verified
    archive rather than executing its entrypoint, so it explicitly disables that
    argv check and subsequently proves every loaded ALIVE helper origin belongs
    to this archive.
    """
    path = _required_env(_EXECUTABLE_PATH_ENV)
    if not os.path.isabs(path) or path != os.path.normpath(path):
        raise WorkerIdentityError("worker executable path must be absolute and normalized")
    if os.path.realpath(path) != path:
        raise WorkerIdentityError("worker executable path must be canonical and non-symlinked")
    if not path.endswith((".pyz", ".py")):
        raise WorkerIdentityError("worker executable must be a .pyz bundle or local .py fallback")
    if require_argv_match and os.path.abspath(sys.argv[0]) != path:
        raise WorkerIdentityError("running process does not match controller worker executable")

    expected = _expected_digest(_EXECUTABLE_SHA_ENV)
    observed = hashlib.sha256(_read_regular_bytes(path, field="worker_executable")).hexdigest()
    if observed != expected:
        raise WorkerIdentityError(
            "worker_executable SHA-256 differs from the controller lock "
            f"(expected={expected}, observed={observed})"
        )
    return VerifiedWorkerExecutable(
        path=path,
        sha256=observed,
        is_bundle=path.endswith(".pyz"),
    )


def require_loaded_alive_helpers_from_executable(
    executable: VerifiedWorkerExecutable,
) -> None:
    """Require every loaded ``alive`` module to originate inside one bundle.

    Direct ``.py`` execution is an explicitly local-only compatibility path and
    cannot provide a helper archive.  Production/fixture ``.pyz`` execution must
    load no ALIVE module from site-packages, an editable checkout, or a second
    archive.
    """
    if not isinstance(executable, VerifiedWorkerExecutable):
        raise WorkerIdentityError("executable must be a VerifiedWorkerExecutable")
    if not executable.is_bundle:
        return

    loaded: set[str] = set()
    archive_prefix = executable.path + os.sep
    for module_name, module in tuple(sys.modules.items()):
        if module_name != "alive" and not module_name.startswith("alive."):
            continue
        relative = _BUNDLED_ALIVE_ORIGINS.get(module_name)
        if relative is None:
            raise WorkerIdentityError(
                f"loaded ALIVE helper {module_name!r} is outside the exact bundle roster"
            )
        origin = getattr(module, "__file__", None)
        expected = archive_prefix + relative.replace("/", os.sep)
        if not isinstance(origin, str) or os.path.normpath(origin) != expected:
            raise WorkerIdentityError(
                f"loaded ALIVE helper {module_name!r} does not originate in worker bundle"
            )
        loaded.add(module_name)

    required = {"alive", "alive.compose", "alive.compose.worker_identity"}
    if not required.issubset(loaded):
        raise WorkerIdentityError("worker bundle did not load the required ALIVE identity helpers")


def _stable_stat_tuple(value: os.stat_result) -> tuple[int, ...]:
    """Return every inode attribute that must remain fixed during a trusted read."""
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_nlink),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _read_regular_bytes(path: str, *, field: str) -> bytes:
    if not os.path.isabs(path) or path != os.path.normpath(path):
        raise WorkerIdentityError(f"{field} path must be absolute and normalized")
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise WorkerIdentityError(f"cannot stat {field}: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise WorkerIdentityError(f"{field} must be a regular non-symlink file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise WorkerIdentityError(f"cannot open {field}: {exc}") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or _stable_stat_tuple(opened) != _stable_stat_tuple(
            before
        ):
            raise WorkerIdentityError(f"{field} changed before stable open")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        if _stable_stat_tuple(after) != _stable_stat_tuple(opened):
            raise WorkerIdentityError(f"{field} changed while being read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _read_and_match(path_env: str, digest_env: str, *, field: str) -> bytes:
    data = _read_regular_bytes(_required_env(path_env), field=field)
    observed = hashlib.sha256(data).hexdigest()
    expected = _expected_digest(digest_env)
    if observed != expected:
        raise WorkerIdentityError(
            f"{field} SHA-256 differs from the controller lock "
            f"(expected={expected}, observed={observed})"
        )
    return data


def _json_object(data: bytes, *, field: str) -> dict[str, Any]:
    def _object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise WorkerIdentityError(f"{field} contains duplicate key {key!r}")
            value[key] = item
        return value

    def _reject_constant(value: str) -> None:
        raise WorkerIdentityError(f"{field} contains non-finite JSON number {value!r}")

    try:
        text = data.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_object_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerIdentityError(f"{field} must be a UTF-8 JSON object: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkerIdentityError(f"{field} must be a JSON object")
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    if data != canonical:
        raise WorkerIdentityError(f"{field} must use canonical JSON bytes")
    return value


def load_verified_worker_identity(*, method: str) -> VerifiedWorkerIdentity:
    """Verify the controller-supplied identity files for ``method``.

    ``worker_config`` must be schema ``compose_deep_worker_config_v1`` and bind
    both the method name and semantic adapter version.  Other config fields are
    method-specific and are validated by the worker before use.
    """
    executable = load_verified_worker_executable()
    config_bytes = _read_and_match(
        "ALIVE_WORKER_CONFIG_PATH", "ALIVE_WORKER_CONFIG_SHA256", field="worker_config"
    )
    resource_bytes = _read_and_match(
        "ALIVE_WORKER_RESOURCE_MANIFEST_PATH",
        "ALIVE_WORKER_RESOURCE_SHA256",
        field="resource_manifest",
    )
    _read_and_match(
        "ALIVE_WORKER_REQUIREMENTS_LOCK_PATH",
        "ALIVE_WORKER_ENVIRONMENT_LOCK_SHA256",
        field="requirements_lock",
    )
    _read_and_match(
        "ALIVE_WORKER_ADAPTER_ARTIFACT_PATH",
        "ALIVE_WORKER_ADAPTER_SHA256",
        field="adapter_artifact",
    )

    config = _json_object(config_bytes, field="worker_config")
    resource = _json_object(resource_bytes, field="resource_manifest")
    if config.get("schema") != "compose_deep_worker_config_v1":
        raise WorkerIdentityError("worker_config has an unsupported schema")
    if config.get("method") != method:
        raise WorkerIdentityError(
            f"worker_config method {config.get('method')!r} does not match {method!r}"
        )
    version = _required_env("ALIVE_WORKER_ADAPTER_VERSION")
    if config.get("adapter_version") != version:
        raise WorkerIdentityError("worker_config adapter_version differs from controller lock")
    require_loaded_alive_helpers_from_executable(executable)

    return VerifiedWorkerIdentity(
        adapter_version=version,
        adapter_sha256=_expected_digest("ALIVE_WORKER_ADAPTER_SHA256"),
        config_sha256=_expected_digest("ALIVE_WORKER_CONFIG_SHA256"),
        resource_sha256=_expected_digest("ALIVE_WORKER_RESOURCE_SHA256"),
        environment_lock_sha256=_expected_digest("ALIVE_WORKER_ENVIRONMENT_LOCK_SHA256"),
        worker_config=MappingProxyType(config),
        resource_manifest=MappingProxyType(resource),
        worker_executable_path=executable.path,
        worker_executable_sha256=executable.sha256,
    )
