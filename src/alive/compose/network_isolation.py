"""Kernel-enforced network isolation for maintained COMPOSE producers.

Two fail-closed modes are accepted:

* a Linux network namespace exposing only loopback; or
* a committed seccomp filter that permits only ``AF_UNIX socketpair`` local
  IPC, blocks all ``socket`` creation plus ``connect``, ``io_uring_setup`` and
  ``pidfd_getfd``, and is installed after ``PR_SET_NO_NEW_PRIVS``.

The seccomp path exists for standard managed containers that do not grant
``CAP_SYS_ADMIN``/``CAP_NET_ADMIN`` and therefore cannot create a network
namespace.  It is a property-based contract: every maintained producer checks
the kernel status and actively proves that IPv4/IPv6 stream and datagram socket
creation returns ``EPERM``.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import json
import os
import platform
import re
import socket
import stat
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

from alive.provenance import sha256_bytes, sha256_file, sha256_json

LOOPBACK_NAMESPACE_METHOD = "linux_network_namespace_loopback_only"
SECCOMP_SOCKET_METHOD = "linux_seccomp_socketpair_only_behavior_v2"
LAUNCHER_RECEIPT_SCHEMA = "compose_network_isolation_launcher_receipt_v2"
LAUNCHER_RECEIPT_ENV = "ALIVE_NETWORK_ISOLATION_RECEIPT_FD"
LAUNCHER_RELATIVE_PATH = "scripts/compose/run_network_isolated.py"
DRIVER_RELATIVE_PATH = "scripts/compose/gears_decision_probe.py"
PYTHON_ISOLATION_FLAGS = {
    "ignore_environment": 1,
    "isolated": 1,
    "no_user_site": 1,
    "safe_path": 1,
}
SECCOMP_CAPABILITY_FIELDS = (
    "effective_capabilities_hex",
    "permitted_capabilities_hex",
    "inheritable_capabilities_hex",
    "bounding_capabilities_hex",
    "ambient_capabilities_hex",
)
SECCOMP_PRIVILEGE_CAPABILITY_FIELDS = (
    "effective_capabilities_hex",
    "permitted_capabilities_hex",
    "inheritable_capabilities_hex",
    "ambient_capabilities_hex",
)

LOOPBACK_NAMESPACE_KEYS = frozenset(
    {
        "method",
        "network_namespace",
        "interfaces",
        "ipv4_non_loopback_route_count",
        "ipv6_non_loopback_route_count",
    }
)
SECCOMP_SOCKET_KEYS = frozenset(
    {
        "method",
        "collector_implementation_sha256",
        "policy_sha256",
        "architecture",
        "no_new_privs",
        "seccomp_mode",
        "seccomp_filter_count",
        *SECCOMP_CAPABILITY_FIELDS,
        "af_inet_stream_errno",
        "af_inet_dgram_errno",
        "af_inet6_stream_errno",
        "af_inet6_dgram_errno",
        "af_unix_socket_errno",
        "af_unix_dgram_errno",
        "af_unix_socketpair_available",
    }
)
LAUNCHER_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "pid",
        "method",
        "architecture",
        "collector_implementation_sha256",
        "policy_sha256",
        "launcher_path",
        "launcher_sha256",
        "launcher_argv",
        "python_executable",
        "python_executable_realpath",
        "python_executable_sha256",
        "python_prefix",
        "python_isolation_flags",
        "loader_environment",
        "driver_path",
        "driver_sha256",
        "exec_argv",
        "exec_argv_sha256",
        "proof",
        "proof_sha256",
        "self_checksum",
    }
)

_AF_UNIX = socket.AF_UNIX
_AUDIT_ARCH_X86_64 = 0xC000003E
_SOCKET_SYSCALL_X86_64 = 41
_CONNECT_SYSCALL_X86_64 = 42
_SOCKETPAIR_SYSCALL_X86_64 = 53
_IO_URING_SETUP_SYSCALL_X86_64 = 425
_PIDFD_GETFD_SYSCALL_X86_64 = 438

_BPF_LD_W_ABS = 0x20
_BPF_JMP_JEQ_K = 0x15
_BPF_JMP_JGE_K = 0x35
_BPF_RET_K = 0x06
_SECCOMP_DATA_NR_OFFSET = 0
_SECCOMP_DATA_ARCH_OFFSET = 4
_SECCOMP_DATA_ARG0_LO_OFFSET = 16
_SECCOMP_RET_KILL_PROCESS = 0x80000000
_SECCOMP_RET_ALLOW = 0x7FFF0000
_SECCOMP_RET_ERRNO = 0x00050000
_SECCOMP_SET_MODE_FILTER = 1
_PR_SET_NO_NEW_PRIVS = 38
_X32_SYSCALL_BIT = 0x40000000
# Standard Docker's deliberately narrow default capability roster. Rootless
# containers may expose any subset in privilege-bearing sets. The bounding set
# is recorded separately and may contain additional inert bits under
# ``no_new_privs``.
SECCOMP_ALLOWED_CAPABILITIES_MASK = 0x00000000A80425FB
_F_ADD_SEALS = 1033
_F_GET_SEALS = 1034
_F_SEAL_SEAL = 0x0001
_F_SEAL_SHRINK = 0x0002
_F_SEAL_GROW = 0x0004
_F_SEAL_WRITE = 0x0008
_REQUIRED_MEMFD_SEALS = _F_SEAL_SEAL | _F_SEAL_SHRINK | _F_SEAL_GROW | _F_SEAL_WRITE
_MFD_ALLOW_SEALING = 0x0002


class NetworkIsolationError(ValueError):
    """The process cannot prove the required kernel network isolation."""


class _SockFilter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint32),
    ]


class _SockFprog(ctypes.Structure):
    _fields_ = [
        ("len", ctypes.c_ushort),
        ("filter", ctypes.POINTER(_SockFilter)),
    ]


def _normalized_machine() -> str:
    machine = platform.machine().lower()
    if machine == "amd64":
        return "x86_64"
    return machine


def isolation_implementation_sha256() -> str:
    """Return the committed collector/launcher-policy implementation identity."""
    return sha256_file(Path(__file__).resolve(strict=True))


def _loader_environment() -> dict[str, str]:
    library_path = os.environ.get("LD_LIBRARY_PATH", "")
    if library_path:
        for token in library_path.split(os.pathsep):
            candidate = Path(token)
            if not token or not candidate.is_absolute():
                raise NetworkIsolationError(
                    "LD_LIBRARY_PATH must contain only non-empty absolute directories"
                )
            resolved = candidate.resolve(strict=True)
            if not resolved.is_dir():
                raise NetworkIsolationError("LD_LIBRARY_PATH entry is not a directory")
            if resolved.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise NetworkIsolationError(
                    "LD_LIBRARY_PATH must not contain group/world-writable directories"
                )
    return {"LD_LIBRARY_PATH": library_path}


def python_runtime_identity() -> dict[str, object]:
    """Return the exact isolated interpreter and loader identity."""
    executable = Path(sys.executable)
    if not executable.is_absolute():
        raise NetworkIsolationError("active Python executable path must be absolute")
    real_executable = executable.resolve(strict=True)
    if not real_executable.is_file():
        raise NetworkIsolationError("active Python executable is not a regular file")
    prefix = Path(sys.prefix).resolve(strict=True)
    if not prefix.is_dir():
        raise NetworkIsolationError("active Python prefix is not a directory")
    flags = {
        "ignore_environment": int(sys.flags.ignore_environment),
        "isolated": int(sys.flags.isolated),
        "no_user_site": int(sys.flags.no_user_site),
        "safe_path": int(getattr(sys.flags, "safe_path", 0)),
    }
    if flags != PYTHON_ISOLATION_FLAGS:
        raise NetworkIsolationError("maintained isolation requires Python -I")
    return {
        "python_executable": str(executable),
        "python_executable_realpath": str(real_executable),
        "python_executable_sha256": sha256_file(real_executable),
        "python_prefix": str(prefix),
        "python_isolation_flags": flags,
        "loader_environment": _loader_environment(),
    }


def seccomp_policy_sha256() -> str:
    """Hash the expected x86_64 cBPF instruction roster.

    This identifies the policy the launcher requests.  Linux does not expose
    the installed cBPF program back to this unprivileged process, so this value
    must never be described as a read-back hash of the kernel filter.
    """
    return sha256_json(
        {
            "architecture": "x86_64",
            "instructions": [list(item) for item in _filter_instructions("x86_64")],
        }
    )


def _filter_instructions(machine: str) -> tuple[tuple[int, int, int, int], ...]:
    """Build the architecture-bound classic-BPF policy.

    The architecture check kills an unexpected ABI, closing the 32-bit
    ``socketcall`` compatibility path on x86.  Syscall numbers carrying the
    x32 ABI bit are denied separately because x32 shares ``AUDIT_ARCH_X86_64``.
    ``socket`` is always denied; ``socketpair`` accepts only ``AF_UNIX``.
    ``connect`` is denied even for an inherited descriptor. ``io_uring_setup``
    is denied so it cannot be used as an alternate socket-creation path, and
    ``pidfd_getfd`` is denied so a child cannot acquire another process's
    pre-existing network descriptor.
    """
    if machine != "x86_64":
        raise NetworkIsolationError(
            f"seccomp network isolation is validated only for x86_64; observed {machine!r}"
        )
    return (
        (_BPF_LD_W_ABS, 0, 0, _SECCOMP_DATA_ARCH_OFFSET),
        (_BPF_JMP_JEQ_K, 1, 0, _AUDIT_ARCH_X86_64),
        (_BPF_RET_K, 0, 0, _SECCOMP_RET_KILL_PROCESS),
        (_BPF_LD_W_ABS, 0, 0, _SECCOMP_DATA_NR_OFFSET),
        (_BPF_JMP_JGE_K, 9, 0, _X32_SYSCALL_BIT),
        (_BPF_JMP_JEQ_K, 8, 0, _SOCKET_SYSCALL_X86_64),
        (_BPF_JMP_JEQ_K, 0, 3, _SOCKETPAIR_SYSCALL_X86_64),
        (_BPF_LD_W_ABS, 0, 0, _SECCOMP_DATA_ARG0_LO_OFFSET),
        (_BPF_JMP_JEQ_K, 6, 0, _AF_UNIX),
        (_BPF_RET_K, 0, 0, _SECCOMP_RET_ERRNO | errno.EPERM),
        (_BPF_JMP_JEQ_K, 3, 0, _CONNECT_SYSCALL_X86_64),
        (_BPF_JMP_JEQ_K, 2, 0, _IO_URING_SETUP_SYSCALL_X86_64),
        (_BPF_JMP_JEQ_K, 1, 0, _PIDFD_GETFD_SYSCALL_X86_64),
        (_BPF_RET_K, 0, 0, _SECCOMP_RET_ALLOW),
        (_BPF_RET_K, 0, 0, _SECCOMP_RET_ERRNO | errno.EPERM),
        (_BPF_RET_K, 0, 0, _SECCOMP_RET_ALLOW),
    )


def close_inherited_fds() -> None:
    """Reject socket stdio and close every descriptor above stderr."""
    for descriptor in range(3):
        try:
            metadata = os.fstat(descriptor)
        except OSError as exc:
            raise NetworkIsolationError(
                f"standard file descriptor {descriptor} is unavailable: {exc}"
            ) from exc
        if stat.S_ISSOCK(metadata.st_mode):
            raise NetworkIsolationError(
                "standard file descriptors must not be sockets; use a pipe, PTY, or file"
            )
    try:
        descriptor_names = os.listdir("/proc/self/fd")
    except OSError as exc:
        raise NetworkIsolationError(f"cannot enumerate inherited file descriptors: {exc}") from exc
    for name in descriptor_names:
        if not name.isdigit():
            raise NetworkIsolationError("inherited file-descriptor inventory is malformed")
        descriptor = int(name)
        if descriptor > 2:
            try:
                os.close(descriptor)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise NetworkIsolationError(
                        f"cannot close inherited file descriptor {descriptor}: {exc}"
                    ) from exc


def install_seccomp_socket_isolation() -> None:
    """Install the irreversible socketpair-only policy in this process."""
    if platform.system() != "Linux":
        raise NetworkIsolationError("seccomp network isolation requires Linux")
    machine = _normalized_machine()
    instructions = _filter_instructions(machine)
    filters = (_SockFilter * len(instructions))(
        *(_SockFilter(*instruction) for instruction in instructions)
    )
    program = _SockFprog(len=len(filters), filter=filters)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        observed_errno = ctypes.get_errno()
        raise NetworkIsolationError(
            f"cannot set PR_SET_NO_NEW_PRIVS: {os.strerror(observed_errno)}"
        )
    libc.syscall.restype = ctypes.c_long
    syscall_number = 317
    if (
        libc.syscall(
            syscall_number,
            _SECCOMP_SET_MODE_FILTER,
            0,
            ctypes.byref(program),
        )
        != 0
    ):
        observed_errno = ctypes.get_errno()
        raise NetworkIsolationError(
            f"cannot install seccomp network filter: {os.strerror(observed_errno)}"
        )


def _required_text(path: Path, *, label: str) -> str:
    if path.is_symlink():
        raise NetworkIsolationError(f"{label} must not be a symlink")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NetworkIsolationError(f"cannot read {label}: {exc}") from exc


def _status_integer(status: str, field: str) -> int:
    matches = re.findall(rf"^{re.escape(field)}:\s*([0-9]+)\s*$", status, re.MULTILINE)
    if len(matches) != 1:
        raise NetworkIsolationError(f"process status {field} is unavailable or ambiguous")
    return int(matches[0])


def _status_capabilities(status: str) -> dict[str, str]:
    fields = {
        "CapEff": "effective_capabilities_hex",
        "CapPrm": "permitted_capabilities_hex",
        "CapInh": "inheritable_capabilities_hex",
        "CapBnd": "bounding_capabilities_hex",
        "CapAmb": "ambient_capabilities_hex",
    }
    observed: dict[str, str] = {}
    for status_field, output_field in fields.items():
        matches = re.findall(
            rf"^{status_field}:\s*([0-9A-Fa-f]{{16}})\s*$",
            status,
            re.MULTILINE,
        )
        if len(matches) != 1:
            raise NetworkIsolationError(
                f"process status {status_field} is unavailable or ambiguous"
            )
        value = matches[0].lower()
        if (
            output_field in SECCOMP_PRIVILEGE_CAPABILITY_FIELDS
            and int(value, 16) & ~SECCOMP_ALLOWED_CAPABILITIES_MASK
        ):
            raise NetworkIsolationError(
                f"seccomp mode {status_field} exceeds the exact admitted allowlist"
            )
        observed[output_field] = value
    if int(observed["permitted_capabilities_hex"], 16) & ~int(
        observed["bounding_capabilities_hex"], 16
    ):
        raise NetworkIsolationError("seccomp mode permitted capabilities exceed the bounding set")
    return observed


def _probe_socket_denial(family: int, socket_type: int, label: str) -> int:
    try:
        candidate = socket.socket(family, socket_type)
    except OSError as exc:
        if exc.errno != errno.EPERM:
            raise NetworkIsolationError(
                f"{label} socket probe failed with errno {exc.errno}, expected EPERM"
            ) from exc
        return exc.errno
    candidate.close()
    raise NetworkIsolationError(f"{label} socket creation was not denied")


def _probe_seccomp_socket_policy() -> dict[str, object]:
    results: dict[str, object] = {
        "af_inet_stream_errno": _probe_socket_denial(
            socket.AF_INET, socket.SOCK_STREAM, "AF_INET/SOCK_STREAM"
        ),
        "af_inet_dgram_errno": _probe_socket_denial(
            socket.AF_INET, socket.SOCK_DGRAM, "AF_INET/SOCK_DGRAM"
        ),
        "af_inet6_stream_errno": _probe_socket_denial(
            socket.AF_INET6, socket.SOCK_STREAM, "AF_INET6/SOCK_STREAM"
        ),
        "af_inet6_dgram_errno": _probe_socket_denial(
            socket.AF_INET6, socket.SOCK_DGRAM, "AF_INET6/SOCK_DGRAM"
        ),
        "af_unix_socket_errno": _probe_socket_denial(
            socket.AF_UNIX, socket.SOCK_STREAM, "AF_UNIX/SOCK_STREAM"
        ),
        "af_unix_dgram_errno": _probe_socket_denial(
            socket.AF_UNIX, socket.SOCK_DGRAM, "AF_UNIX/SOCK_DGRAM"
        ),
    }
    try:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    except OSError as exc:
        raise NetworkIsolationError(f"AF_UNIX socketpair is unavailable: {exc}") from exc
    else:
        left.close()
        right.close()
    results["af_unix_socketpair_available"] = True
    return results


def _collect_loopback_namespace(
    proc: Path,
    interfaces: list[str],
) -> dict[str, object] | None:
    if interfaces != ["lo"]:
        return None
    try:
        namespace = os.readlink(proc / "self/ns/net")
    except OSError as exc:
        raise NetworkIsolationError(
            f"cannot read runtime network namespace identity: {exc}"
        ) from exc
    if re.fullmatch(r"net:\[[0-9]+\]", namespace) is None:
        raise NetworkIsolationError("runtime network namespace identity is malformed")
    ipv4 = _required_text(proc / "net/route", label="runtime IPv4 route table").splitlines()
    if not ipv4 or ipv4[0].split()[:2] != ["Iface", "Destination"]:
        raise NetworkIsolationError("runtime IPv4 route table header is malformed")
    ipv4_non_loopback = sum(1 for line in ipv4[1:] if line.strip() and line.split()[0] != "lo")
    ipv6_non_loopback = 0
    for line in _required_text(
        proc / "net/ipv6_route", label="runtime IPv6 route table"
    ).splitlines():
        fields = line.split()
        if len(fields) < 10:
            raise NetworkIsolationError("runtime IPv6 route table row is malformed")
        if fields[-1] != "lo":
            ipv6_non_loopback += 1
    if ipv4_non_loopback or ipv6_non_loopback:
        raise NetworkIsolationError("runtime network namespace has a non-loopback route")
    return {
        "method": LOOPBACK_NAMESPACE_METHOD,
        "network_namespace": namespace,
        "interfaces": interfaces,
        "ipv4_non_loopback_route_count": ipv4_non_loopback,
        "ipv6_non_loopback_route_count": ipv6_non_loopback,
    }


def collect_network_isolation(
    proc_root: str | Path = "/proc",
    net_class_root: str | Path = "/sys/class/net",
    *,
    seccomp_probe: Callable[[], dict[str, object]] = _probe_seccomp_socket_policy,
    require_seccomp: bool = False,
) -> dict[str, object]:
    """Collect one exact, kernel-backed network-isolation proof."""
    proc = Path(proc_root)
    interfaces_root = Path(net_class_root)
    if interfaces_root.is_symlink() or not interfaces_root.is_dir():
        raise NetworkIsolationError("network interface root must be a real directory")
    try:
        interfaces = sorted(path.name for path in interfaces_root.iterdir())
    except OSError as exc:
        raise NetworkIsolationError(f"cannot enumerate network interfaces: {exc}") from exc
    if not require_seccomp:
        namespace = _collect_loopback_namespace(proc, interfaces)
        if namespace is not None:
            return namespace

    status = _required_text(proc / "self/status", label="process status")
    no_new_privs = _status_integer(status, "NoNewPrivs")
    seccomp_mode = _status_integer(status, "Seccomp")
    seccomp_filter_count = _status_integer(status, "Seccomp_filters")
    capabilities = _status_capabilities(status)
    if no_new_privs != 1 or seccomp_mode != 2 or seccomp_filter_count < 1:
        raise NetworkIsolationError("runtime lacks no_new_privs plus an active seccomp filter")
    probes = seccomp_probe()
    if set(probes) != {
        "af_inet_stream_errno",
        "af_inet_dgram_errno",
        "af_inet6_stream_errno",
        "af_inet6_dgram_errno",
        "af_unix_socket_errno",
        "af_unix_dgram_errno",
        "af_unix_socketpair_available",
    }:
        raise NetworkIsolationError("seccomp socket probe returned an invalid field roster")
    if (
        any(probes[field] != errno.EPERM for field in probes if field.endswith("_errno"))
        or probes["af_unix_socketpair_available"] is not True
    ):
        raise NetworkIsolationError("seccomp socket probe did not prove the required policy")
    return {
        "method": SECCOMP_SOCKET_METHOD,
        "collector_implementation_sha256": isolation_implementation_sha256(),
        "policy_sha256": seccomp_policy_sha256(),
        "architecture": _normalized_machine(),
        "no_new_privs": no_new_privs,
        "seccomp_mode": seccomp_mode,
        "seccomp_filter_count": seccomp_filter_count,
        **capabilities,
        **probes,
    }


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _receipt_body(
    *,
    launcher_path: Path,
    launcher_argv: Sequence[str],
    exec_argv: Sequence[str],
    proof: Mapping[str, object],
) -> dict[str, object]:
    launcher_tokens = list(launcher_argv)
    exec_tokens = list(exec_argv)
    if any(not isinstance(token, str) or not token for token in (*launcher_tokens, *exec_tokens)):
        raise NetworkIsolationError("launcher and exec argv must contain non-empty strings")
    if proof.get("method") != SECCOMP_SOCKET_METHOD:
        raise NetworkIsolationError("launcher receipt requires the seccomp behavioral proof")
    launcher = launcher_path.resolve(strict=True)
    repository_root = launcher.parents[2]
    driver = repository_root / DRIVER_RELATIVE_PATH
    if driver.is_symlink() or not driver.is_file():
        raise NetworkIsolationError("maintained probe driver must be a regular non-symlink file")
    python_identity = python_runtime_identity()
    if (
        len(exec_tokens) < 4
        or exec_tokens[:3]
        != [
            python_identity["python_executable"],
            "-I",
            str(driver),
        ]
        or launcher_tokens != [str(launcher), "--", *exec_tokens]
    ):
        raise NetworkIsolationError(
            "launcher receipt requires exact Python -I and maintained-driver argv"
        )
    return {
        "schema": LAUNCHER_RECEIPT_SCHEMA,
        "pid": os.getpid(),
        "method": SECCOMP_SOCKET_METHOD,
        "architecture": "x86_64",
        "collector_implementation_sha256": isolation_implementation_sha256(),
        "policy_sha256": seccomp_policy_sha256(),
        "launcher_path": LAUNCHER_RELATIVE_PATH,
        "launcher_sha256": sha256_file(launcher),
        "launcher_argv": launcher_tokens,
        **python_identity,
        "driver_path": str(driver),
        "driver_sha256": sha256_file(driver),
        "exec_argv": exec_tokens,
        "exec_argv_sha256": sha256_json(exec_tokens),
        "proof": dict(proof),
        "proof_sha256": sha256_json(dict(proof)),
    }


def create_sealed_launcher_receipt(
    *,
    launcher_path: str | Path,
    launcher_argv: Sequence[str],
    exec_argv: Sequence[str],
    proof: Mapping[str, object],
) -> tuple[int, dict[str, object]]:
    """Create a sealed same-PID receipt inherited across ``execve``."""
    if platform.system() != "Linux":
        raise NetworkIsolationError("sealed launcher receipts require Linux")
    memfd_create = getattr(os, "memfd_create", None)
    if memfd_create is None:
        raise NetworkIsolationError("Linux runtime lacks os.memfd_create")
    body = _receipt_body(
        launcher_path=Path(launcher_path),
        launcher_argv=launcher_argv,
        exec_argv=exec_argv,
        proof=proof,
    )
    receipt = {**body, "self_checksum": sha256_json(body)}
    encoded = _canonical_bytes(receipt)
    fd = memfd_create("alive-network-isolation-receipt", _MFD_ALLOW_SEALING)
    try:
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise NetworkIsolationError("launcher receipt write made no progress")
            remaining = remaining[written:]
        os.fsync(fd)
        fcntl.fcntl(fd, _F_ADD_SEALS, _REQUIRED_MEMFD_SEALS)
        if fcntl.fcntl(fd, _F_GET_SEALS) != _REQUIRED_MEMFD_SEALS:
            raise NetworkIsolationError("launcher receipt memfd does not have the exact seals")
        os.set_inheritable(fd, True)
    except Exception:
        os.close(fd)
        raise
    return fd, receipt


def _validate_receipt_payload(
    payload: object,
    *,
    current_argv: Sequence[str],
    repository_root: str | Path,
    current_proof: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != set(LAUNCHER_RECEIPT_KEYS):
        raise NetworkIsolationError("launcher receipt has an invalid field roster")
    receipt = dict(payload)
    body = {key: value for key, value in receipt.items() if key != "self_checksum"}
    if receipt["self_checksum"] != sha256_json(body):
        raise NetworkIsolationError("launcher receipt self-checksum mismatch")
    if (
        receipt["schema"] != LAUNCHER_RECEIPT_SCHEMA
        or receipt["pid"] != os.getpid()
        or receipt["method"] != SECCOMP_SOCKET_METHOD
        or receipt["architecture"] != "x86_64"
        or receipt["collector_implementation_sha256"] != isolation_implementation_sha256()
        or receipt["policy_sha256"] != seccomp_policy_sha256()
        or receipt["proof"] != dict(current_proof)
        or receipt["proof_sha256"] != sha256_json(dict(current_proof))
    ):
        raise NetworkIsolationError("launcher receipt identity differs from the active process")
    if receipt["launcher_path"] != LAUNCHER_RELATIVE_PATH:
        raise NetworkIsolationError("launcher receipt path is not the maintained launcher")
    root = Path(repository_root).resolve(strict=True)
    launcher = root / LAUNCHER_RELATIVE_PATH
    if launcher.is_symlink() or not launcher.is_file():
        raise NetworkIsolationError("maintained launcher must be a regular non-symlink file")
    if receipt["launcher_sha256"] != sha256_file(launcher):
        raise NetworkIsolationError("launcher receipt code digest mismatch")
    driver = root / DRIVER_RELATIVE_PATH
    if driver.is_symlink() or not driver.is_file():
        raise NetworkIsolationError("maintained probe driver must be a regular non-symlink file")
    current_python = python_runtime_identity()
    if any(receipt[field] != current_python[field] for field in current_python):
        raise NetworkIsolationError("launcher receipt Python runtime identity mismatch")
    if receipt["driver_path"] != str(driver) or receipt["driver_sha256"] != sha256_file(driver):
        raise NetworkIsolationError("launcher receipt driver identity mismatch")
    launcher_argv = receipt["launcher_argv"]
    exec_argv = receipt["exec_argv"]
    argv = list(current_argv)
    expected_exec_argv = [
        current_python["python_executable"],
        "-I",
        *argv,
    ]
    if (
        not isinstance(launcher_argv, list)
        or not isinstance(exec_argv, list)
        or any(not isinstance(token, str) or not token for token in (*launcher_argv, *exec_argv))
        or not argv
        or argv[0] != str(driver)
        or launcher_argv != [str(launcher), "--", *exec_argv]
        or exec_argv != expected_exec_argv
        or receipt["exec_argv_sha256"] != sha256_json(exec_argv)
    ):
        raise NetworkIsolationError("launcher receipt argv binding is invalid")
    return receipt


def validate_sealed_launcher_receipt(
    *,
    current_argv: Sequence[str],
    repository_root: str | Path,
    current_proof: Mapping[str, object],
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Validate the inherited sealed receipt and its active-process bindings."""
    environment = os.environ if environ is None else environ
    descriptor_text = environment.get(LAUNCHER_RECEIPT_ENV, "")
    if re.fullmatch(r"[0-9]+", descriptor_text) is None:
        raise NetworkIsolationError("sealed launcher receipt descriptor is missing or malformed")
    fd = int(descriptor_text)
    try:
        if not os.get_inheritable(fd):
            raise NetworkIsolationError("launcher receipt descriptor is not inherited")
        if fcntl.fcntl(fd, _F_GET_SEALS) != _REQUIRED_MEMFD_SEALS:
            raise NetworkIsolationError("launcher receipt descriptor lacks the exact seals")
        target = os.readlink(f"/proc/self/fd/{fd}")
        if not target.startswith("/memfd:") and not target.startswith("memfd:"):
            raise NetworkIsolationError("launcher receipt descriptor is not a memfd")
        size = os.fstat(fd).st_size
        if size <= 0 or size > 128 * 1024:
            raise NetworkIsolationError("launcher receipt exceeds its bounded envelope")
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                raise NetworkIsolationError("launcher receipt read ended before its declared size")
            chunks.append(chunk)
            remaining -= len(chunk)
        encoded = b"".join(chunks)
        if os.read(fd, 1):
            raise NetworkIsolationError("launcher receipt read was not stable")
        payload = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NetworkIsolationError(f"cannot read sealed launcher receipt: {exc}") from exc
    if encoded != _canonical_bytes(payload):
        raise NetworkIsolationError("launcher receipt is not canonical JSON")
    return _validate_receipt_payload(
        payload,
        current_argv=current_argv,
        repository_root=repository_root,
        current_proof=current_proof,
    )


def launcher_receipt_sha256(receipt: Mapping[str, object]) -> str:
    """Return the digest stored beside the replayable receipt in the ledger."""
    return sha256_bytes(_canonical_bytes(receipt))
