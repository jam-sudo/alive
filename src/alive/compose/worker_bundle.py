"""Deterministic, source-only execution bundles for isolated COMPOSE workers.

The GEARS and CPA workers run in mutually incompatible Python environments.  A
worker must nevertheless import a small, exact subset of ALIVE without relying
on an editable checkout or an ambient ``PYTHONPATH``.  This module builds that
subset as a deterministic zip application and validates the complete archive
contract from one stable file snapshot.

The archive is deliberately simple: source files only, ``ZIP_STORED``, one
fixed timestamp and mode, sorted members, and a canonical self-checking
manifest.  Its outer SHA-256 can therefore serve as the existing trusted worker
identity while binding both the entrypoint and every imported ALIVE helper.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

__all__ = [
    "WORKER_BUNDLE_HELPER_SOURCES",
    "WORKER_BUNDLE_MANIFEST_PATH",
    "WORKER_BUNDLE_SCHEMA",
    "WorkerBundleError",
    "WorkerBundleInfo",
    "build_worker_bundle",
    "validate_worker_bundle",
]

WORKER_BUNDLE_SCHEMA = "compose_worker_execution_bundle_v1"
WORKER_BUNDLE_MANIFEST_PATH = "worker_bundle_manifest.json"
_ENTRYPOINT_PATH = "__main__.py"
_PYTHON_MINIMUM = "3.10"
_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = stat.S_IFREG | 0o444
_MAX_BUNDLE_BYTES = 8 << 20
_MAX_MEMBER_BYTES = 2 << 20
_METHOD_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Archive path -> repository-relative source path.  Keep this roster exact: it
# is the complete recursive local import graph of the real CPA/GEARS workers.
WORKER_BUNDLE_HELPER_SOURCES: Mapping[str, str] = MappingProxyType(
    {
        "alive/__init__.py": "src/alive/__init__.py",
        "alive/compose/__init__.py": "src/alive/compose/__init__.py",
        "alive/compose/baseline_subprocess.py": "src/alive/compose/baseline_subprocess.py",
        "alive/compose/baselines_combo.py": "src/alive/compose/baselines_combo.py",
        "alive/compose/fit_role.py": "src/alive/compose/fit_role.py",
        "alive/compose/response.py": "src/alive/compose/response.py",
        "alive/compose/roles.py": "src/alive/compose/roles.py",
        "alive/compose/worker_identity.py": "src/alive/compose/worker_identity.py",
        "alive/provenance.py": "src/alive/provenance.py",
    }
)

_SOURCE_MEMBER_PATHS = frozenset({_ENTRYPOINT_PATH, *WORKER_BUNDLE_HELPER_SOURCES})
_ARCHIVE_MEMBER_PATHS = frozenset({*_SOURCE_MEMBER_PATHS, WORKER_BUNDLE_MANIFEST_PATH})


class WorkerBundleError(ValueError):
    """Raised when worker-bundle construction or validation fails closed."""


@dataclass(frozen=True)
class WorkerBundleInfo:
    """Validated identity and immutable manifest of one worker bundle."""

    path: str
    sha256: str
    manifest: Mapping[str, Any]


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_stat(value: os.stat_result) -> tuple[int, ...]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_nlink),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
    )


def _read_stable_regular(path: str | os.PathLike[str], *, field: str) -> bytes:
    """Read a non-symlink regular file through one unchanged descriptor."""
    raw = os.fspath(path)
    if not raw:
        raise WorkerBundleError(f"{field} path must be non-empty")
    absolute = os.path.abspath(raw)
    try:
        before = os.lstat(absolute)
    except OSError as exc:
        raise WorkerBundleError(f"cannot stat {field}: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise WorkerBundleError(f"{field} must be a regular non-symlink file")
    if os.path.realpath(absolute) != absolute:
        raise WorkerBundleError(f"{field} path must not traverse symlinked parents")
    if before.st_size > _MAX_BUNDLE_BYTES:
        raise WorkerBundleError(f"{field} exceeds the registered size limit")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(absolute, flags)
    except OSError as exc:
        raise WorkerBundleError(f"cannot open {field}: {exc}") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or _stable_stat(opened) != _stable_stat(before):
            raise WorkerBundleError(f"{field} changed before stable open")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_BUNDLE_BYTES:
                raise WorkerBundleError(f"{field} exceeds the registered size limit")
            chunks.append(chunk)
        after = os.fstat(fd)
        if _stable_stat(after) != _stable_stat(opened):
            raise WorkerBundleError(f"{field} changed while being read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _canonical_source_root(path: str | os.PathLike[str]) -> str:
    raw = os.path.abspath(os.fspath(path))
    if os.path.realpath(raw) != raw:
        raise WorkerBundleError("source_root must be canonical and non-symlinked")
    try:
        node = os.lstat(raw)
    except OSError as exc:
        raise WorkerBundleError(f"cannot stat source_root: {exc}") from exc
    if stat.S_ISLNK(node.st_mode) or not stat.S_ISDIR(node.st_mode):
        raise WorkerBundleError("source_root must be a non-symlink directory")
    return raw


def _source_below_root(path: str | os.PathLike[str], *, root: str, field: str) -> str:
    absolute = os.path.abspath(os.fspath(path))
    try:
        within = os.path.commonpath([root, absolute]) == root and absolute != root
    except ValueError:
        within = False
    if not within:
        raise WorkerBundleError(f"{field} must be a strict descendant of source_root")
    return absolute


def _require_python_310(source: bytes, *, member: str) -> None:
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkerBundleError(f"{member} must be UTF-8 Python source") from exc
    try:
        ast.parse(text, filename=member, feature_version=(3, 10))
    except (SyntaxError, ValueError) as exc:
        raise WorkerBundleError(f"{member} is not valid Python 3.10 source: {exc}") from exc


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=_FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.create_version = 20
    info.extract_version = 20
    info.external_attr = _FILE_MODE << 16
    info.internal_attr = 0
    info.extra = b""
    info.comment = b""
    return info


def _manifest(method: str, members: Mapping[str, bytes]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": WORKER_BUNDLE_SCHEMA,
        "method": method,
        "entrypoint": _ENTRYPOINT_PATH,
        "python_minimum": _PYTHON_MINIMUM,
        "files": [
            {"path": path, "sha256": _sha256(members[path]), "size": len(members[path])}
            for path in sorted(members)
        ],
    }
    return {**body, "manifest_checksum": _sha256(_canonical_json(body))}


def _write_exclusive(path: str | os.PathLike[str], data: bytes) -> str:
    destination = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(destination)
    if os.path.realpath(parent) != parent:
        raise WorkerBundleError("worker bundle output parent must be canonical")
    try:
        parent_node = os.lstat(parent)
    except OSError as exc:
        raise WorkerBundleError(f"cannot stat worker bundle output parent: {exc}") from exc
    if stat.S_ISLNK(parent_node.st_mode) or not stat.S_ISDIR(parent_node.st_mode):
        raise WorkerBundleError("worker bundle output parent must already exist")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(destination, flags, 0o400)
    except OSError as exc:
        raise WorkerBundleError(f"cannot create worker bundle: {exc}") from exc
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise WorkerBundleError("short write while creating worker bundle")
            view = view[written:]
        os.fchmod(fd, 0o400)
        os.fsync(fd)
    except Exception:
        try:
            os.unlink(destination)
        except OSError:
            pass
        raise
    finally:
        os.close(fd)
    return destination


def build_worker_bundle(
    *,
    source_root: str | os.PathLike[str],
    entrypoint: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    method: str,
) -> WorkerBundleInfo:
    """Build and revalidate one byte-deterministic worker execution bundle.

    ``source_root`` is the canonical repository root.  ``entrypoint`` must be a
    regular file below it; the eight helper paths are fixed by
    :data:`WORKER_BUNDLE_HELPER_SOURCES`.  The output is created exclusively and
    never overwrites an existing artifact.
    """
    if not isinstance(method, str) or _METHOD_RE.fullmatch(method) is None:
        raise WorkerBundleError("method must match [a-z0-9][a-z0-9_-]*")
    root = _canonical_source_root(source_root)
    entrypoint_path = _source_below_root(entrypoint, root=root, field="entrypoint")

    members: dict[str, bytes] = {
        _ENTRYPOINT_PATH: _read_stable_regular(entrypoint_path, field="entrypoint")
    }
    for archive_path, relative_path in WORKER_BUNDLE_HELPER_SOURCES.items():
        source_path = _source_below_root(
            os.path.join(root, relative_path), root=root, field=f"helper {archive_path}"
        )
        members[archive_path] = _read_stable_regular(source_path, field=f"helper {archive_path}")
    if set(members) != set(_SOURCE_MEMBER_PATHS):
        raise WorkerBundleError("worker bundle source roster is not exact")
    for member, source in members.items():
        _require_python_310(source, member=member)

    manifest = _manifest(method, members)
    archive_members = {**members, WORKER_BUNDLE_MANIFEST_PATH: _canonical_json(manifest)}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
        archive.comment = b""
        for member in sorted(archive_members):
            archive.writestr(_zip_info(member), archive_members[member])
    data = buffer.getvalue()
    if len(data) > _MAX_BUNDLE_BYTES:
        raise WorkerBundleError("worker bundle exceeds the registered size limit")
    destination = _write_exclusive(output_path, data)
    try:
        return validate_worker_bundle(
            destination,
            expected_method=method,
            expected_sha256=_sha256(data),
        )
    except Exception:
        try:
            os.unlink(destination)
        except OSError:
            pass
        raise


def _safe_archive_path(path: str) -> bool:
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    pure = PurePosixPath(path)
    return (
        not pure.is_absolute()
        and path == pure.as_posix()
        and all(part not in {"", ".", ".."} for part in pure.parts)
    )


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerBundleError(f"manifest contains duplicate key {key!r}")
        result[key] = value
    return result


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _parse_manifest(data: bytes) -> dict[str, Any]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkerBundleError("worker bundle manifest must be UTF-8") from exc
    try:
        value = json.loads(text, object_pairs_hook=_object_without_duplicate_keys)
    except WorkerBundleError:
        raise
    except json.JSONDecodeError as exc:
        raise WorkerBundleError(f"worker bundle manifest is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkerBundleError("worker bundle manifest must be an object")
    if _canonical_json(value) != data:
        raise WorkerBundleError("worker bundle manifest is not canonical JSON")
    return value


def _validate_manifest(
    manifest: dict[str, Any],
    *,
    members: Mapping[str, bytes],
    expected_method: str | None,
) -> None:
    required = {
        "schema",
        "method",
        "entrypoint",
        "python_minimum",
        "files",
        "manifest_checksum",
    }
    if set(manifest) != required:
        raise WorkerBundleError("worker bundle manifest key roster is not exact")
    if manifest["schema"] != WORKER_BUNDLE_SCHEMA:
        raise WorkerBundleError("worker bundle manifest schema is unsupported")
    method = manifest["method"]
    if not isinstance(method, str) or _METHOD_RE.fullmatch(method) is None:
        raise WorkerBundleError("worker bundle manifest method is invalid")
    if expected_method is not None and method != expected_method:
        raise WorkerBundleError("worker bundle method differs from controller expectation")
    if manifest["entrypoint"] != _ENTRYPOINT_PATH:
        raise WorkerBundleError("worker bundle entrypoint is not registered")
    if manifest["python_minimum"] != _PYTHON_MINIMUM:
        raise WorkerBundleError("worker bundle Python compatibility is not registered")

    body = {key: value for key, value in manifest.items() if key != "manifest_checksum"}
    checksum = manifest["manifest_checksum"]
    if not isinstance(checksum, str) or checksum != _sha256(_canonical_json(body)):
        raise WorkerBundleError("worker bundle manifest self-checksum mismatch")

    files = manifest["files"]
    if not isinstance(files, list):
        raise WorkerBundleError("worker bundle manifest files must be a list")
    paths: list[str] = []
    for record in files:
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
            raise WorkerBundleError("worker bundle manifest file record is malformed")
        path = record["path"]
        digest = record["sha256"]
        size = record["size"]
        if not isinstance(path, str) or not _safe_archive_path(path):
            raise WorkerBundleError("worker bundle manifest contains an unsafe path")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise WorkerBundleError("worker bundle manifest file SHA-256 is invalid")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise WorkerBundleError("worker bundle manifest file size is invalid")
        paths.append(path)
        observed = members.get(path)
        if observed is None:
            raise WorkerBundleError(f"worker bundle manifest names missing member {path!r}")
        if len(observed) != size or _sha256(observed) != digest:
            raise WorkerBundleError(f"worker bundle member {path!r} differs from its manifest")
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise WorkerBundleError("worker bundle manifest file roster is unsorted or duplicated")
    if set(paths) != set(_SOURCE_MEMBER_PATHS):
        raise WorkerBundleError("worker bundle manifest file roster is not exact")


def validate_worker_bundle(
    path: str | os.PathLike[str],
    *,
    expected_method: str | None = None,
    expected_sha256: str | None = None,
) -> WorkerBundleInfo:
    """Validate an execution bundle from one stable regular-file snapshot."""
    if expected_method is not None and (
        not isinstance(expected_method, str) or _METHOD_RE.fullmatch(expected_method) is None
    ):
        raise WorkerBundleError("expected_method is invalid")
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_sha256)
    ):
        raise WorkerBundleError("expected_sha256 must be exact lowercase SHA-256")

    data = _read_stable_regular(path, field="worker bundle")
    observed_sha256 = _sha256(data)
    if expected_sha256 is not None and observed_sha256 != expected_sha256:
        raise WorkerBundleError("worker bundle SHA-256 differs from controller expectation")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data), mode="r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise WorkerBundleError(f"worker bundle is not a valid ZIP archive: {exc}") from exc
    try:
        if archive.comment != b"":
            raise WorkerBundleError("worker bundle archive comment must be empty")
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise WorkerBundleError("worker bundle contains duplicate archive members")
        for name in names:
            if not _safe_archive_path(name):
                raise WorkerBundleError(f"worker bundle contains unsafe archive path {name!r}")
        if set(names) != set(_ARCHIVE_MEMBER_PATHS):
            raise WorkerBundleError("worker bundle archive roster is not exact")
        if names != sorted(names):
            raise WorkerBundleError("worker bundle archive members are not sorted")

        members: dict[str, bytes] = {}
        for info in infos:
            if info.compress_type != zipfile.ZIP_STORED:
                raise WorkerBundleError(f"worker bundle member {info.filename!r} is compressed")
            if info.date_time != _FIXED_TIMESTAMP:
                raise WorkerBundleError(
                    f"worker bundle member {info.filename!r} has a non-canonical timestamp"
                )
            if info.create_system != 3 or info.external_attr != _FILE_MODE << 16:
                raise WorkerBundleError(
                    f"worker bundle member {info.filename!r} has a non-canonical mode"
                )
            if (
                info.create_version != 20
                or info.extract_version != 20
                or info.internal_attr != 0
                or info.extra != b""
                or info.comment != b""
                or info.flag_bits != 0
            ):
                raise WorkerBundleError(
                    f"worker bundle member {info.filename!r} has non-canonical ZIP metadata"
                )
            if info.file_size > _MAX_MEMBER_BYTES or info.compress_size != info.file_size:
                raise WorkerBundleError(
                    f"worker bundle member {info.filename!r} violates the size contract"
                )
            try:
                content = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise WorkerBundleError(
                    f"cannot read worker bundle member {info.filename!r}: {exc}"
                ) from exc
            if len(content) != info.file_size:
                raise WorkerBundleError(f"worker bundle member {info.filename!r} was truncated")
            members[info.filename] = content
    finally:
        archive.close()

    manifest = _parse_manifest(members.pop(WORKER_BUNDLE_MANIFEST_PATH))
    _validate_manifest(manifest, members=members, expected_method=expected_method)
    for member in sorted(_SOURCE_MEMBER_PATHS):
        _require_python_310(members[member], member=member)
    return WorkerBundleInfo(
        path=os.path.abspath(os.fspath(path)),
        sha256=observed_sha256,
        manifest=_freeze_json(manifest),
    )
