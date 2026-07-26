"""Tests for the kernel-enforced COMPOSE network-isolation contract."""

from __future__ import annotations

import errno
import importlib.util
import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from alive.compose.network_isolation import (
    DRIVER_RELATIVE_PATH,
    LOOPBACK_NAMESPACE_METHOD,
    SECCOMP_ALLOWED_CAPABILITIES_MASK,
    SECCOMP_SOCKET_METHOD,
    NetworkIsolationError,
    _filter_instructions,
    close_inherited_fds,
    collect_network_isolation,
    isolation_implementation_sha256,
    seccomp_policy_sha256,
)
from alive.provenance import sha256_json

_REPO = Path(__file__).resolve().parents[3]
_LAUNCHER = _REPO / "scripts/compose/run_network_isolated.py"


def _load_launcher():
    spec = importlib.util.spec_from_file_location("_network_isolated_launcher_test", _LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._bootstrap_runtime_identity = lambda: None
    return module


def _fake_proc_status(root: Path, *, no_new_privs: int = 1, seccomp: int = 2) -> None:
    (root / "self").mkdir(parents=True)
    (root / "self/status").write_text(
        f"NoNewPrivs:\t{no_new_privs}\nSeccomp:\t{seccomp}\n"
        "Seccomp_filters:\t2\n"
        "CapEff:\t0000000000000000\n"
        "CapPrm:\t0000000000000000\n"
        "CapInh:\t0000000000000000\n"
        "CapBnd:\t0000000000000000\n"
        "CapAmb:\t0000000000000000\n",
        encoding="utf-8",
    )


def test_filter_is_architecture_bound_and_denies_alternate_descriptor_paths():
    instructions = _filter_instructions("x86_64")
    assert len(instructions) == 16
    assert instructions[0][3] == 4
    assert instructions[2][3] == 0x80000000
    assert instructions[4][3] == 0x40000000
    assert instructions[9][3] == 0x00050000 | errno.EPERM
    assert instructions[14][3] == 0x00050000 | errno.EPERM
    for machine in ("aarch64", "riscv64"):
        with pytest.raises(NetworkIsolationError, match="only for x86_64"):
            _filter_instructions(machine)


def test_collects_loopback_namespace_without_seccomp_probe(tmp_path):
    proc = tmp_path / "proc"
    (proc / "self/ns").mkdir(parents=True)
    (proc / "self/ns/net").symlink_to("net:[12345]")
    (proc / "net").mkdir()
    (proc / "net/route").write_text(
        "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
        "lo 0000007F 00000000 0001 0 0 0 000000FF 0 0 0\n",
        encoding="utf-8",
    )
    (proc / "net/ipv6_route").write_text("", encoding="utf-8")
    interfaces = tmp_path / "interfaces"
    (interfaces / "lo").mkdir(parents=True)

    proof = collect_network_isolation(
        proc,
        interfaces,
        seccomp_probe=lambda: pytest.fail("seccomp probe must not run in a lo-only namespace"),
    )

    assert proof == {
        "method": LOOPBACK_NAMESPACE_METHOD,
        "network_namespace": "net:[12345]",
        "interfaces": ["lo"],
        "ipv4_non_loopback_route_count": 0,
        "ipv6_non_loopback_route_count": 0,
    }


def test_collects_exact_seccomp_socket_proof(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    _fake_proc_status(proc)
    interfaces = tmp_path / "interfaces"
    (interfaces / "eth0").mkdir(parents=True)
    (interfaces / "lo").mkdir()
    monkeypatch.setattr(
        "alive.compose.network_isolation._normalized_machine",
        lambda: "x86_64",
    )
    probe = {
        "af_inet_stream_errno": errno.EPERM,
        "af_inet_dgram_errno": errno.EPERM,
        "af_inet6_stream_errno": errno.EPERM,
        "af_inet6_dgram_errno": errno.EPERM,
        "af_unix_socket_errno": errno.EPERM,
        "af_unix_dgram_errno": errno.EPERM,
        "af_unix_socketpair_available": True,
    }

    proof = collect_network_isolation(proc, interfaces, seccomp_probe=lambda: probe)

    assert proof == {
        "method": SECCOMP_SOCKET_METHOD,
        "collector_implementation_sha256": isolation_implementation_sha256(),
        "policy_sha256": seccomp_policy_sha256(),
        "architecture": "x86_64",
        "no_new_privs": 1,
        "seccomp_mode": 2,
        "seccomp_filter_count": 2,
        "effective_capabilities_hex": "0000000000000000",
        "permitted_capabilities_hex": "0000000000000000",
        "inheritable_capabilities_hex": "0000000000000000",
        "bounding_capabilities_hex": "0000000000000000",
        "ambient_capabilities_hex": "0000000000000000",
        **probe,
    }


@pytest.mark.parametrize(
    ("no_new_privs", "seccomp"),
    [(0, 2), (1, 0)],
)
def test_seccomp_collection_fails_without_kernel_preconditions(tmp_path, no_new_privs, seccomp):
    proc = tmp_path / "proc"
    _fake_proc_status(proc, no_new_privs=no_new_privs, seccomp=seccomp)
    interfaces = tmp_path / "interfaces"
    (interfaces / "eth0").mkdir(parents=True)
    with pytest.raises(NetworkIsolationError, match="lacks no_new_privs"):
        collect_network_isolation(proc, interfaces, seccomp_probe=lambda: {})


@pytest.mark.parametrize(
    ("status_field", "capability"),
    [
        ("CapEff", 12),
        ("CapPrm", 16),
        ("CapInh", 17),
        ("CapAmb", 39),
    ],
)
def test_seccomp_collection_rejects_capabilities_outside_allowlist(
    tmp_path, status_field, capability
):
    proc = tmp_path / "proc"
    _fake_proc_status(proc)
    status = proc / "self/status"
    status.write_text(
        status.read_text(encoding="utf-8").replace(
            f"{status_field}:\t0000000000000000",
            f"{status_field}:\t{1 << capability:016x}",
        ),
        encoding="utf-8",
    )
    interfaces = tmp_path / "interfaces"
    (interfaces / "eth0").mkdir(parents=True)
    with pytest.raises(NetworkIsolationError, match=f"{status_field} exceeds"):
        collect_network_isolation(proc, interfaces, seccomp_probe=lambda: {})


def test_seccomp_collection_accepts_any_subset_of_capability_allowlist(tmp_path):
    proc = tmp_path / "proc"
    _fake_proc_status(proc)
    status = proc / "self/status"
    status.write_text(
        status.read_text(encoding="utf-8")
        .replace(
            "CapEff:\t0000000000000000",
            f"CapEff:\t{SECCOMP_ALLOWED_CAPABILITIES_MASK:016x}",
        )
        .replace(
            "CapPrm:\t0000000000000000",
            f"CapPrm:\t{SECCOMP_ALLOWED_CAPABILITIES_MASK:016x}",
        )
        .replace(
            "CapBnd:\t0000000000000000",
            f"CapBnd:\t{SECCOMP_ALLOWED_CAPABILITIES_MASK:016x}",
        ),
        encoding="utf-8",
    )
    interfaces = tmp_path / "interfaces"
    (interfaces / "eth0").mkdir(parents=True)
    probe = {
        "af_inet_stream_errno": errno.EPERM,
        "af_inet_dgram_errno": errno.EPERM,
        "af_inet6_stream_errno": errno.EPERM,
        "af_inet6_dgram_errno": errno.EPERM,
        "af_unix_socket_errno": errno.EPERM,
        "af_unix_dgram_errno": errno.EPERM,
        "af_unix_socketpair_available": True,
    }
    proof = collect_network_isolation(proc, interfaces, seccomp_probe=lambda: probe)
    assert proof["effective_capabilities_hex"] == f"{SECCOMP_ALLOWED_CAPABILITIES_MASK:016x}"
    assert proof["permitted_capabilities_hex"] == f"{SECCOMP_ALLOWED_CAPABILITIES_MASK:016x}"
    assert proof["bounding_capabilities_hex"] == f"{SECCOMP_ALLOWED_CAPABILITIES_MASK:016x}"


def test_seccomp_collection_accepts_inert_broad_bounding_set(tmp_path):
    proc = tmp_path / "proc"
    _fake_proc_status(proc)
    status = proc / "self/status"
    status.write_text(
        status.read_text(encoding="utf-8").replace(
            "CapBnd:\t0000000000000000",
            "CapBnd:\t000001ffffffffff",
        ),
        encoding="utf-8",
    )
    interfaces = tmp_path / "interfaces"
    (interfaces / "eth0").mkdir(parents=True)
    probe = {
        "af_inet_stream_errno": errno.EPERM,
        "af_inet_dgram_errno": errno.EPERM,
        "af_inet6_stream_errno": errno.EPERM,
        "af_inet6_dgram_errno": errno.EPERM,
        "af_unix_socket_errno": errno.EPERM,
        "af_unix_dgram_errno": errno.EPERM,
        "af_unix_socketpair_available": True,
    }
    proof = collect_network_isolation(proc, interfaces, seccomp_probe=lambda: probe)
    assert proof["bounding_capabilities_hex"] == "000001ffffffffff"


def test_seccomp_collection_rejects_permitted_set_outside_bounding_set(tmp_path):
    proc = tmp_path / "proc"
    _fake_proc_status(proc)
    status = proc / "self/status"
    status.write_text(
        status.read_text(encoding="utf-8").replace(
            "CapPrm:\t0000000000000000",
            "CapPrm:\t0000000000000001",
        ),
        encoding="utf-8",
    )
    interfaces = tmp_path / "interfaces"
    (interfaces / "eth0").mkdir(parents=True)
    with pytest.raises(NetworkIsolationError, match="exceed the bounding set"):
        collect_network_isolation(proc, interfaces, seccomp_probe=lambda: {})


def test_launcher_requires_a_command():
    launcher = _load_launcher()
    with pytest.raises(NetworkIsolationError, match="command is required"):
        launcher.main([])


def test_inherited_stdio_must_not_be_a_socket(monkeypatch):
    left, right = socket.socketpair()
    real_fstat = os.fstat
    monkeypatch.setattr(
        "alive.compose.network_isolation.os.fstat",
        lambda descriptor: real_fstat(left.fileno()) if descriptor == 0 else real_fstat(descriptor),
    )
    try:
        with pytest.raises(NetworkIsolationError, match="must not be sockets"):
            close_inherited_fds()
    finally:
        left.close()
        right.close()


def test_launcher_requires_an_absolute_executable():
    launcher = _load_launcher()
    with pytest.raises(NetworkIsolationError, match="absolute path"):
        launcher.main(["--", "python"])


def test_launcher_receipt_binds_the_exact_exec_argv(monkeypatch):
    launcher = _load_launcher()
    captured: dict[str, object] = {}
    monkeypatch.setattr("alive.compose.network_isolation.close_inherited_fds", lambda: None)
    monkeypatch.setattr(
        "alive.compose.network_isolation.install_seccomp_socket_isolation", lambda: None
    )
    monkeypatch.setattr(
        "alive.compose.network_isolation.collect_network_isolation",
        lambda **_kwargs: {"method": SECCOMP_SOCKET_METHOD},
    )

    def _create(**kwargs):
        captured.update(kwargs)
        return 99, {}

    monkeypatch.setattr("alive.compose.network_isolation.create_sealed_launcher_receipt", _create)

    def _exec(executable_path, argv, environment):
        captured["executed"] = (executable_path, argv, environment)
        raise RuntimeError("exec intercepted")

    monkeypatch.setattr(launcher.os, "execve", _exec)
    driver = str(_REPO / DRIVER_RELATIVE_PATH)
    command = [sys.executable, "-I", driver, "verify-input"]
    with pytest.raises(RuntimeError, match="exec intercepted"):
        launcher.main(["--", *command])

    assert captured["exec_argv"] == command
    assert captured["launcher_argv"] == [
        str(_LAUNCHER.resolve()),
        "--",
        *command,
    ]


def test_launcher_rejects_wrapper_or_missing_isolated_flag(tmp_path):
    launcher = _load_launcher()
    wrapper = tmp_path / "wrapper"
    wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)
    driver = str(_REPO / DRIVER_RELATIVE_PATH)
    with pytest.raises(NetworkIsolationError, match="exact active Python"):
        launcher.main(["--", str(wrapper), "-I", driver, "verify-input"])
    with pytest.raises(NetworkIsolationError, match="exact Python -I"):
        launcher.main(["--", sys.executable, driver, "verify-input"])
    fake_driver = tmp_path / "gears_decision_probe.py"
    fake_driver.write_text("raise SystemExit(0)\n", encoding="utf-8")
    with pytest.raises(NetworkIsolationError, match="exact Python -I"):
        launcher.main(["--", sys.executable, "-I", str(fake_driver), "verify-input"])


def test_launcher_bootstrap_rejects_nonisolated_python_and_pythonpath(tmp_path):
    command = [sys.executable, str(_LAUNCHER), "--help"]
    observed = subprocess.run(command, check=False, capture_output=True, text=True)
    assert observed.returncode != 0
    assert "requires Python -I" in observed.stderr

    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path)
    observed = subprocess.run(
        [sys.executable, "-I", str(_LAUNCHER), "--help"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert observed.returncode != 0
    assert "PYTHONPATH" in observed.stderr

    env.pop("PYTHONPATH")
    env["LD_LIBRARY_PATH"] = "relative"
    observed = subprocess.run(
        [sys.executable, "-I", str(_LAUNCHER), "--help"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert observed.returncode != 0
    assert "LD_LIBRARY_PATH" in observed.stderr


@pytest.mark.skipif(platform.system() != "Linux", reason="seccomp is a Linux kernel API")
def test_linux_policy_and_sealed_receipt_validate_in_the_active_process():
    child = """
import ctypes, errno, fcntl, json, os, socket, sys
from pathlib import Path
from alive.compose.network_isolation import (
    DRIVER_RELATIVE_PATH,
    LAUNCHER_RELATIVE_PATH,
    close_inherited_fds,
    collect_network_isolation,
    create_sealed_launcher_receipt,
    install_seccomp_socket_isolation,
    validate_sealed_launcher_receipt,
)
root = Path(sys.argv[1]).resolve(strict=True)
launcher = root / LAUNCHER_RELATIVE_PATH
driver = root / DRIVER_RELATIVE_PATH
driver_argv = [str(driver), "verify-input"]
exec_argv = [sys.executable, "-I", *driver_argv]
launcher_argv = [str(launcher), "--", *exec_argv]
extra_fd = os.open("/dev/null", os.O_RDONLY)
close_inherited_fds()
observed = {}
try:
    os.fstat(extra_fd)
except OSError as exc:
    observed["inherited_fd_closed"] = exc.errno
else:
    observed["inherited_fd_closed"] = 0
preexisting_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
install_seccomp_socket_isolation()
proof = collect_network_isolation(require_seccomp=True)
receipt_fd, receipt = create_sealed_launcher_receipt(
    launcher_path=launcher,
    launcher_argv=launcher_argv,
    exec_argv=exec_argv,
    proof=proof,
)
os.environ["ALIVE_NETWORK_ISOLATION_RECEIPT_FD"] = str(receipt_fd)
validated = validate_sealed_launcher_receipt(
    current_argv=driver_argv,
    repository_root=root,
    current_proof=proof,
)
observed["receipt_seals"] = fcntl.fcntl(receipt_fd, 1034)
observed["receipt_same_pid"] = receipt["pid"] == os.getpid()
observed["receipt_method"] = receipt["method"]
observed["receipt_validated"] = validated == receipt
families = (
    ("inet", socket.AF_INET),
    ("inet6", socket.AF_INET6),
    ("unix", socket.AF_UNIX),
)
for family_name, family in families:
    for type_name, socket_type in (("stream", socket.SOCK_STREAM), ("dgram", socket.SOCK_DGRAM)):
        try:
            candidate = socket.socket(family, socket_type)
        except OSError as exc:
            observed[f"{family_name}_{type_name}"] = exc.errno
        else:
            candidate.close()
            observed[f"{family_name}_{type_name}"] = 0
left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
left.close()
right.close()
observed["unix_socketpair"] = True
try:
    socket.socketpair(socket.AF_INET, socket.SOCK_STREAM)
except OSError as exc:
    observed["inet_socketpair"] = exc.errno
else:
    observed["inet_socketpair"] = 0
try:
    preexisting_socket.connect(("127.0.0.1", 9))
except OSError as exc:
    observed["preexisting_connect"] = exc.errno
else:
    observed["preexisting_connect"] = 0
preexisting_socket.close()
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
for name, number in (("io_uring_setup", 425), ("pidfd_getfd", 438)):
    ctypes.set_errno(0)
    result = libc.syscall(number, -1, 0)
    observed[name] = ctypes.get_errno() if result == -1 else 0
ctypes.set_errno(0)
result = libc.syscall(0x40000029, socket.AF_INET, socket.SOCK_STREAM, 0)
observed["x32_socket"] = ctypes.get_errno() if result == -1 else 0
print(json.dumps(observed, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", child, str(_REPO)],
        cwd=_REPO,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "inet_dgram": errno.EPERM,
        "inet_stream": errno.EPERM,
        "inet6_dgram": errno.EPERM,
        "inet6_stream": errno.EPERM,
        "inet_socketpair": errno.EPERM,
        "inherited_fd_closed": errno.EBADF,
        "io_uring_setup": errno.EPERM,
        "pidfd_getfd": errno.EPERM,
        "preexisting_connect": errno.EPERM,
        "receipt_method": SECCOMP_SOCKET_METHOD,
        "receipt_same_pid": True,
        "receipt_seals": 15,
        "receipt_validated": True,
        "unix_dgram": errno.EPERM,
        "unix_socketpair": True,
        "unix_stream": errno.EPERM,
        "x32_socket": errno.EPERM,
    }


@pytest.mark.skipif(platform.system() != "Linux", reason="seccomp is a Linux kernel API")
def test_linux_launcher_executes_driver_self_check_end_to_end():
    """Exercise the real launcher, ``execve``, driver bootstrap and live receipt."""
    driver = str(_REPO / DRIVER_RELATIVE_PATH)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(_LAUNCHER),
            "--",
            sys.executable,
            "-I",
            driver,
            "isolation-self-check",
        ],
        cwd=_REPO,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload) == {
        "schema",
        "pid",
        "method",
        "collector_implementation_sha256",
        "policy_sha256",
        "proof_sha256",
        "receipt_sha256",
        "self_checksum",
    }
    body = {key: value for key, value in payload.items() if key != "self_checksum"}
    assert payload["schema"] == "compose_network_isolation_e2e_self_check_v1"
    assert payload["pid"] > 0
    assert payload["method"] == SECCOMP_SOCKET_METHOD
    assert payload["collector_implementation_sha256"] == isolation_implementation_sha256()
    assert payload["policy_sha256"] == seccomp_policy_sha256()
    assert payload["self_checksum"] == sha256_json(body)
