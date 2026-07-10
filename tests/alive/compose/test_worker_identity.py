from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

import alive.compose.worker_identity as worker_identity
from alive.compose.worker_bundle import build_worker_bundle
from alive.compose.worker_identity import (
    WorkerIdentityError,
    load_verified_worker_identity,
    require_distribution_version,
    require_exact_worker_config,
    require_module_from_environment,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _install_identity_env(tmp_path: Path, monkeypatch, *, method: str = "gears") -> dict[str, Path]:
    version = f"{method}-adapter-v1"
    payloads = {
        "CONFIG": _canonical_json(
            {
                "schema": "compose_deep_worker_config_v1",
                "method": method,
                "adapter_version": version,
                "training": {"seed_source": "payload"},
            }
        ),
        "RESOURCE": _canonical_json({"schema": "test_resource_manifest_v1"}),
        "REQUIREMENTS_LOCK": b"package==1.0\n",
        "ADAPTER_ARTIFACT": b"adapter-content-v1\n",
    }
    paths: dict[str, Path] = {}
    path_env = {
        "CONFIG": "ALIVE_WORKER_CONFIG_PATH",
        "RESOURCE": "ALIVE_WORKER_RESOURCE_MANIFEST_PATH",
        "REQUIREMENTS_LOCK": "ALIVE_WORKER_REQUIREMENTS_LOCK_PATH",
        "ADAPTER_ARTIFACT": "ALIVE_WORKER_ADAPTER_ARTIFACT_PATH",
    }
    for key, data in payloads.items():
        path = tmp_path / key.lower()
        path.write_bytes(data)
        paths[key] = path
        monkeypatch.setenv(path_env[key], str(path))
        digest_key = {
            "REQUIREMENTS_LOCK": "ENVIRONMENT_LOCK",
            "ADAPTER_ARTIFACT": "ADAPTER",
        }.get(key, key)
        monkeypatch.setenv(f"ALIVE_WORKER_{digest_key}_SHA256", _sha(data))
    executable = tmp_path / "worker.py"
    executable.write_bytes(b"# local test worker\n")
    paths["EXECUTABLE"] = executable
    monkeypatch.setenv("ALIVE_WORKER_EXECUTABLE_PATH", str(executable))
    monkeypatch.setenv("ALIVE_WORKER_EXECUTABLE_SHA256", _sha(executable.read_bytes()))
    monkeypatch.setattr(worker_identity.sys, "argv", [str(executable)])
    monkeypatch.setenv("ALIVE_WORKER_ADAPTER_VERSION", version)
    return paths


def test_worker_identity_rehashes_controller_bound_files(tmp_path, monkeypatch):
    paths = _install_identity_env(tmp_path, monkeypatch)
    identity = load_verified_worker_identity(method="gears")
    assert identity.adapter_version == "gears-adapter-v1"
    assert identity.worker_config["training"] == {"seed_source": "payload"}
    assert identity.resource_manifest["schema"] == "test_resource_manifest_v1"
    assert identity.worker_executable_path == str(paths["EXECUTABLE"])
    assert identity.worker_executable_sha256 == _sha(paths["EXECUTABLE"].read_bytes())


def test_worker_identity_rejects_tampered_file(tmp_path, monkeypatch):
    paths = _install_identity_env(tmp_path, monkeypatch)
    paths["CONFIG"].write_text("{}", encoding="utf-8")
    with pytest.raises(WorkerIdentityError, match="differs from the controller lock"):
        load_verified_worker_identity(method="gears")


def test_worker_identity_rejects_tampered_or_different_running_executable(tmp_path, monkeypatch):
    paths = _install_identity_env(tmp_path, monkeypatch)
    paths["EXECUTABLE"].write_bytes(b"# replaced worker\n")
    with pytest.raises(WorkerIdentityError, match="worker_executable SHA-256"):
        load_verified_worker_identity(method="gears")

    paths = _install_identity_env(tmp_path, monkeypatch)
    monkeypatch.setattr(worker_identity.sys, "argv", [str(tmp_path / "different.py")])
    with pytest.raises(WorkerIdentityError, match="does not match controller"):
        load_verified_worker_identity(method="gears")


def test_bundle_helper_origins_must_all_come_from_verified_archive(tmp_path):
    root = Path(__file__).resolve().parents[3]
    bundle = build_worker_bundle(
        source_root=root,
        entrypoint=root / "scripts" / "baselines" / "stub_worker.py",
        output_path=tmp_path / "stub.pyz",
        method="stub",
    )
    code = (
        "from alive.compose.worker_identity import "
        "load_verified_worker_executable,require_loaded_alive_helpers_from_executable;"
        "executable=load_verified_worker_executable(require_argv_match=False);"
        "require_loaded_alive_helpers_from_executable(executable)"
    )
    identity_env = {
        "ALIVE_WORKER_EXECUTABLE_PATH": bundle.path,
        "ALIVE_WORKER_EXECUTABLE_SHA256": bundle.sha256,
        "PYTHONNOUSERSITE": "1",
    }

    trusted = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={**identity_env, "PYTHONPATH": bundle.path},
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert trusted.returncode == 0, trusted.stderr

    shadowed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={**identity_env, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert shadowed.returncode != 0
    assert "does not originate in worker bundle" in shadowed.stderr


def test_worker_identity_rejects_method_or_version_drift(tmp_path, monkeypatch):
    _install_identity_env(tmp_path, monkeypatch, method="cpa")
    with pytest.raises(WorkerIdentityError, match="does not match"):
        load_verified_worker_identity(method="gears")
    monkeypatch.setenv("ALIVE_WORKER_ADAPTER_VERSION", "different")
    with pytest.raises(WorkerIdentityError, match="adapter_version"):
        load_verified_worker_identity(method="cpa")


def test_exact_worker_config_rejects_semantic_or_unknown_key_drift(tmp_path, monkeypatch):
    _install_identity_env(tmp_path, monkeypatch)
    identity = load_verified_worker_identity(method="gears")
    require_exact_worker_config(identity, expected=identity.worker_config)

    drifted = dict(identity.worker_config)
    drifted["training"] = {"seed_source": "ambient"}
    with pytest.raises(WorkerIdentityError, match="exactly match"):
        require_exact_worker_config(identity, expected=drifted)

    extended = dict(identity.worker_config)
    extended["unregistered"] = True
    with pytest.raises(WorkerIdentityError, match="exactly match"):
        require_exact_worker_config(identity, expected=extended)

    bool_identity = types.SimpleNamespace(worker_config={"training": {"enabled": True}})
    with pytest.raises(WorkerIdentityError, match="exactly match"):
        require_exact_worker_config(bool_identity, expected={"training": {"enabled": 1}})


@pytest.mark.parametrize(
    "invalid",
    [
        b'{"adapter_version":"gears-adapter-v1","method":"gears","method":"cpa",'
        b'"schema":"compose_deep_worker_config_v1","training":{}}',
        b'{"adapter_version": "gears-adapter-v1", "method": "gears", '
        b'"schema": "compose_deep_worker_config_v1", "training": {}}',
        b'{"adapter_version":"gears-adapter-v1","method":"gears",'
        b'"schema":"compose_deep_worker_config_v1","training":{"x":NaN}}',
    ],
)
def test_worker_identity_rejects_ambiguous_or_noncanonical_json(invalid, tmp_path, monkeypatch):
    paths = _install_identity_env(tmp_path, monkeypatch)
    paths["CONFIG"].write_bytes(invalid)
    monkeypatch.setenv("ALIVE_WORKER_CONFIG_SHA256", _sha(invalid))
    with pytest.raises(WorkerIdentityError):
        load_verified_worker_identity(method="gears")


def test_distribution_version_is_exact(monkeypatch):
    monkeypatch.setattr(worker_identity.importlib.metadata, "version", lambda _name: "0.8.5")
    require_distribution_version(distribution="cpa-tools", expected="0.8.5")
    with pytest.raises(WorkerIdentityError, match="expected"):
        require_distribution_version(distribution="cpa-tools", expected="0.8.4")

    def _missing(_name):
        raise worker_identity.importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(worker_identity.importlib.metadata, "version", _missing)
    with pytest.raises(WorkerIdentityError, match="not installed"):
        require_distribution_version(distribution="cell-gears", expected="0.1.2")


def test_backend_module_origin_must_be_inside_launched_prefix(tmp_path, monkeypatch):
    prefix = tmp_path / "venv"
    package = prefix / "lib" / "python" / "site-packages" / "cpa"
    package.mkdir(parents=True)
    origin = package / "__init__.py"
    origin.write_text("# pinned backend\n", encoding="utf-8")
    monkeypatch.setattr(worker_identity.sys, "prefix", str(prefix))
    module = types.SimpleNamespace(__name__="cpa", __file__=str(origin))
    require_module_from_environment(module, expected_name="cpa")

    outside = tmp_path / "shadow.py"
    outside.write_text("# shadow\n", encoding="utf-8")
    module.__file__ = str(outside)
    with pytest.raises(WorkerIdentityError, match="outside sys.prefix"):
        require_module_from_environment(module, expected_name="cpa")
