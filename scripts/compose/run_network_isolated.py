#!/usr/bin/env python
"""Run one command under ALIVE's irreversible socketpair-only seccomp policy."""

from __future__ import annotations

import argparse
import importlib.util
import os
import site
import stat
import sys
from pathlib import Path

_FORBIDDEN_ENVIRONMENT = (
    "LD_AUDIT",
    "LD_PRELOAD",
    "PYTHONBREAKPOINT",
    "PYTHONHOME",
    "PYTHONINSPECT",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "PYTHONUSERBASE",
)
_EXPECTED_PYTHON_FLAGS = {
    "ignore_environment": 1,
    "isolated": 1,
    "no_user_site": 1,
    "safe_path": 1,
}


def _bootstrap_runtime_identity() -> None:
    """Reject Python/import injection before loading maintained project code."""
    flags = {
        "ignore_environment": int(sys.flags.ignore_environment),
        "isolated": int(sys.flags.isolated),
        "no_user_site": int(sys.flags.no_user_site),
        "safe_path": int(getattr(sys.flags, "safe_path", 0)),
    }
    if flags != _EXPECTED_PYTHON_FLAGS or site.ENABLE_USER_SITE:
        raise RuntimeError("network-isolation launcher requires Python -I")
    contaminated = [name for name in _FORBIDDEN_ENVIRONMENT if os.environ.get(name)]
    if contaminated:
        raise RuntimeError(
            "network-isolation launcher forbids import/loader overrides: " + ", ".join(contaminated)
        )
    library_path = os.environ.get("LD_LIBRARY_PATH", "")
    if library_path:
        for token in library_path.split(os.pathsep):
            candidate = Path(token)
            if not token or not candidate.is_absolute():
                raise RuntimeError(
                    "LD_LIBRARY_PATH must contain only non-empty absolute directories"
                )
            resolved = candidate.resolve(strict=True)
            if not resolved.is_dir() or resolved.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise RuntimeError("LD_LIBRARY_PATH contains an unsafe directory")
    launcher = Path(__file__)
    if launcher.is_symlink() or not launcher.resolve(strict=True).is_file():
        raise RuntimeError("network-isolation launcher must be a regular non-symlink file")
    if Path(sys.argv[0]).resolve(strict=True) != launcher.resolve(strict=True):
        raise RuntimeError("network-isolation launcher argv does not identify this source file")
    repository = launcher.resolve(strict=True).parents[2]
    expected_alive = (repository / "src/alive/__init__.py").resolve(strict=True)
    alive_spec = importlib.util.find_spec("alive")
    if alive_spec is None or alive_spec.origin is None:
        raise RuntimeError("network-isolation launcher cannot resolve the alive package")
    if Path(alive_spec.origin).resolve(strict=True) != expected_alive:
        raise RuntimeError(
            "network-isolation launcher alive import does not originate from this checkout"
        )
    executable = Path(sys.executable)
    if not executable.is_absolute() or not executable.resolve(strict=True).is_file():
        raise RuntimeError("network-isolation launcher requires an absolute Python executable")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="command and arguments; prefix them with --",
    )
    return parser


def _network_api():
    from alive.compose import network_isolation

    return network_isolation


def main(argv: list[str] | None = None) -> int:
    _bootstrap_runtime_identity()
    network = _network_api()

    launcher_argv = list(sys.argv) if argv is None else [str(Path(__file__).resolve()), *argv]
    args = _parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command or not command[0]:
        raise network.NetworkIsolationError("an isolated command is required after --")
    if not os.path.isabs(command[0]):
        raise network.NetworkIsolationError("isolated command executable must be an absolute path")
    executable = Path(command[0])
    if not executable.exists() or not executable.resolve(strict=True).is_file():
        raise network.NetworkIsolationError("isolated command executable is not a regular file")
    active_python = Path(sys.executable)
    if executable != active_python:
        raise network.NetworkIsolationError(
            "isolated command must use the exact active Python executable"
        )
    repository = Path(__file__).resolve(strict=True).parents[2]
    driver = repository / network.DRIVER_RELATIVE_PATH
    if driver.is_symlink() or not driver.is_file():
        raise network.NetworkIsolationError("maintained probe driver is missing or unsafe")
    if len(command) < 4 or command[1:3] != ["-I", str(driver)]:
        raise network.NetworkIsolationError(
            "isolated command must be exact Python -I plus the maintained probe driver"
        )
    launcher_argv = [str(Path(__file__).resolve(strict=True)), "--", *command]
    network.close_inherited_fds()
    network.install_seccomp_socket_isolation()
    proof = network.collect_network_isolation(require_seccomp=True)
    if proof["method"] != network.SECCOMP_SOCKET_METHOD:
        raise network.NetworkIsolationError(
            "isolated launcher produced an unsupported kernel proof"
        )
    receipt_fd, _receipt = network.create_sealed_launcher_receipt(
        launcher_path=Path(__file__).resolve(strict=True),
        launcher_argv=launcher_argv,
        exec_argv=command,
        proof=proof,
    )
    environment = os.environ.copy()
    environment[network.LAUNCHER_RECEIPT_ENV] = str(receipt_fd)
    os.execve(command[0], command, environment)
    raise AssertionError("os.execvpe returned unexpectedly")


if __name__ == "__main__":
    raise SystemExit(main())
