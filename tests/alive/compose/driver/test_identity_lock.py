"""Tests for the ExecutionIdentityLock assembler + subprocess backend factory.

These tests exercise the driver's worker-identity trust boundary (spec §5):
the 6-field :class:`ExecutionIdentityLock` is assembled from **re-hashed real
file bytes**, never from the ResolvedRunSpec's declared values alone. Any
divergence between the declared digest and the actual on-disk bytes fails
closed; a worker file that is a symlink / device / FIFO fails closed on the
node-kind policy that Task 1's lexical-only loader deliberately left to this
assembler.

Real files + real objects, no mocks (RED -> GREEN).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from alive.compose.baseline_subprocess import (
    ExecutionIdentityLock,
    SubprocessBaselineBackend,
)
from alive.compose.driver import identity_lock as identity_lock_module
from alive.compose.driver.identity_lock import (
    DEEP_BASELINE_METHODS,
    AssemblerError,
    assemble_baseline_backends,
    assemble_execution_identity_lock,
    build_subprocess_backend,
)
from alive.compose.driver.run_spec import PathSha, ResolvedRunSpec, WorkerBlock
from alive.compose.worker_bundle import build_worker_bundle

# --------------------------------------------------------------------------- #
# Stub identity bytes — chosen so the hashed file digests equal the fixed
# constants that ``scripts/baselines/stub_worker.py`` self-reports
# (``_ADAPTER_SHA256`` .. ``_ENVIRONMENT_LOCK_SHA256`` / ``_ADAPTER_VERSION``).
#
# ``adapter_sha256`` is sourced from the SEPARATE ``adapter_artifact`` file
# (spec §5), NOT the launched ``worker_script``. ``_ADAPTER_BYTES`` are therefore
# the adapter_artifact's bytes, and ``sha256(_ADAPTER_BYTES)`` equals the stub's
# ``_ADAPTER_SHA256 = sha256(b"stub-response-operator-v2")`` — so the three-way
# agreement (declared value == actual re-hash of adapter_artifact == worker
# self-report) is now GENUINELY true for adapter_sha256, whereas the pre-fix
# assembler hashed the worker_script by mistake. ``_WORKER_SCRIPT_BYTES`` are
# distinct launcher bytes; the runtime verifies them separately as
# ``worker_sha256``, and they feed no lock field.
# --------------------------------------------------------------------------- #
_WORKER_SCRIPT_BYTES = b"# stub worker launch script\n"
_ADAPTER_BYTES = b"stub-response-operator-v2"
_CONFIG_BYTES = b"stub-config"
_RESOURCE_BYTES = b"stub-resource"
_ENV_BYTES = b"stub-environment"
_ADAPTER_VERSION = "stub-2"
# The versions the COMMITTED manifest registers (configs/compose_adapter_versions_v1.json).
_GEARS_ADAPTER_VERSION = "compose-gears-adapter-v1"
_CPA_ADAPTER_VERSION = "compose-cpa-adapter-v1"
_GEARS_REPRESENTATION = "raw_pseudobulk_approximation"
_CPA_REPRESENTATION = "cell_raw_counts"


def _h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_worker_files(
    tmp: Path,
    *,
    worker_script: bytes = _WORKER_SCRIPT_BYTES,
    adapter: bytes = _ADAPTER_BYTES,
    config: bytes = _CONFIG_BYTES,
    resource: bytes = _RESOURCE_BYTES,
    env: bytes = _ENV_BYTES,
) -> tuple[Path, Path, Path, Path, Path]:
    """Create the five worker files: launched worker_script, separate
    adapter_artifact, worker_config, resource_manifest, requirements_lock."""
    ws = tmp / "worker_code"
    aa = tmp / "adapter_artifact"
    wc = tmp / "worker_config.json"
    rm = tmp / "resource_manifest.json"
    rl = tmp / "requirements.lock"
    ws.write_bytes(worker_script)
    aa.write_bytes(adapter)
    wc.write_bytes(config)
    rm.write_bytes(resource)
    rl.write_bytes(env)
    return ws, aa, wc, rm, rl


def _worker_block(
    tmp: Path,
    *,
    representation: str = _GEARS_REPRESENTATION,
    adapter_version: str = _ADAPTER_VERSION,
    files: tuple[Path, Path, Path, Path, Path] | None = None,
    lock_overrides: dict[str, str] | None = None,
    pathsha_overrides: dict[str, str] | None = None,
) -> WorkerBlock:
    """Build a real WorkerBlock whose declared digests match its files' bytes."""
    if files is None:
        files = _make_worker_files(tmp)
    ws, aa, wc, rm, rl = files
    w = _h(ws.read_bytes())
    a = _h(aa.read_bytes())
    c = _h(wc.read_bytes())
    r = _h(rm.read_bytes())
    e = _h(rl.read_bytes())
    lock = {
        "prediction_representation": representation,
        "environment_lock_sha256": e,
        "adapter_version": adapter_version,
        # adapter_sha256 is the adapter_artifact digest, NOT the worker_script's.
        "adapter_sha256": a,
        "config_sha256": c,
        "resource_sha256": r,
    }
    if lock_overrides:
        lock.update(lock_overrides)
    ps = {
        "worker_script": w,
        "adapter_artifact": a,
        "worker_config": c,
        "resource_manifest": r,
        "requirements_lock": e,
    }
    if pathsha_overrides:
        ps.update(pathsha_overrides)
    return WorkerBlock(
        env_python=sys.executable,
        worker_script=PathSha(str(ws), ps["worker_script"]),
        import_name="stub_worker",
        worker_config=PathSha(str(wc), ps["worker_config"]),
        resource_manifest=PathSha(str(rm), ps["resource_manifest"]),
        requirements_lock=PathSha(str(rl), ps["requirements_lock"]),
        adapter_artifact=PathSha(str(aa), ps["adapter_artifact"]),
        execution_identity_lock=lock,
    )


def _dummy_block() -> WorkerBlock:
    """A WorkerBlock with non-existent paths — for checks that fire before hashing."""
    z = "0" * 64
    ps = PathSha("/nonexistent/f", z)
    lock = {
        "prediction_representation": _GEARS_REPRESENTATION,
        "environment_lock_sha256": z,
        "adapter_version": "v",
        "adapter_sha256": z,
        "config_sha256": z,
        "resource_sha256": z,
    }
    return WorkerBlock(
        env_python="/py",
        worker_script=ps,
        import_name="w",
        worker_config=ps,
        resource_manifest=ps,
        requirements_lock=ps,
        adapter_artifact=ps,
        execution_identity_lock=dict(lock),
    )


def _minimal_run_spec(
    worker_blocks: dict[str, WorkerBlock],
    root: Path,
    *,
    mode: str = "fixture",
    response_checksum: str | None = None,
) -> ResolvedRunSpec:
    z = "0" * 64
    return ResolvedRunSpec(
        schema="compose_resolved_run_spec_v2",
        mode=mode,
        protocol="COMPOSE-K562-v1",
        run_id="run",
        approved_git_sha="deadbeef",
        run_dir=str(root),
        approved_artifacts_root=str(root),
        self_checksum=z,
        file_sha256=z,
        config_digest=z,
        data_card_digest=z,
        raw_or_source_digest=z,
        sequence_mapping_digest=z,
        pre_seal={},
        run_produced_basenames={},
        expected_hashes={"response_space_checksum": response_checksum or _h(b"resp")},
        worker_blocks=worker_blocks,
        fixture={} if mode == "fixture" else None,
        scientific=None if mode == "fixture" else {},
    )


# --------------------------------------------------------------------------- #
# Happy fixture assembly
# --------------------------------------------------------------------------- #


def test_fixture_lock_from_hashed_stub_bytes(tmp_path: Path) -> None:
    block = _worker_block(tmp_path, representation=_GEARS_REPRESENTATION)
    lock = assemble_execution_identity_lock(
        block, config_representation=_GEARS_REPRESENTATION, fixture=True
    )
    assert isinstance(lock, ExecutionIdentityLock)
    # Six fields: representation + version + four re-hashed file digests.
    assert lock.prediction_representation == _GEARS_REPRESENTATION
    assert lock.adapter_version == _ADAPTER_VERSION
    # adapter_sha256 comes from the SEPARATE adapter_artifact, NOT worker_script.
    assert lock.adapter_sha256 == _h(_ADAPTER_BYTES)
    assert lock.adapter_sha256 != _h(_WORKER_SCRIPT_BYTES)
    # Genuine three-way agreement: the assembled adapter_sha256 equals the stub
    # worker's self-reported _ADAPTER_SHA256 == sha256(b"stub-response-operator-v2").
    assert lock.adapter_sha256 == hashlib.sha256(b"stub-response-operator-v2").hexdigest()
    assert lock.config_sha256 == _h(_CONFIG_BYTES)
    assert lock.resource_sha256 == _h(_RESOURCE_BYTES)
    assert lock.environment_lock_sha256 == _h(_ENV_BYTES)


def test_build_subprocess_backend_carries_lock(tmp_path: Path) -> None:
    block = _worker_block(tmp_path)
    lock = assemble_execution_identity_lock(
        block, config_representation=_GEARS_REPRESENTATION, fixture=True
    )
    backend = build_subprocess_backend(
        block,
        lock,
        name="gears",
        approved_artifacts_root=str(tmp_path),
        expected_response_artifact_sha256=_h(b"resp"),
        seed=11,
    )
    assert isinstance(backend, SubprocessBaselineBackend)
    assert backend.execution_identity_lock is lock
    assert backend.name == "gears"
    assert backend.env_python == block.env_python
    assert backend.worker_script == block.worker_script.path
    assert backend.import_name == "stub_worker"
    assert backend.approved_artifacts_root == str(tmp_path)
    assert backend.expected_response_artifact_sha256 == _h(b"resp")
    assert backend.expected_worker_sha256 == block.worker_script.sha256
    assert backend.allow_local_approved_root_checkpoint_store is False
    assert backend.seed == 11
    assert backend.worker_identity_paths == {
        "worker_config": block.worker_config.path,
        "resource_manifest": block.resource_manifest.path,
        "requirements_lock": block.requirements_lock.path,
        "adapter_artifact": block.adapter_artifact.path,
    }
    # Unconfigured: no payload bound yet (Task 7 configures it).
    assert backend._payload is None


# --------------------------------------------------------------------------- #
# Divergence fails closed
# --------------------------------------------------------------------------- #


def test_declared_lock_digest_divergence_fails_closed(tmp_path: Path) -> None:
    block = _worker_block(tmp_path, lock_overrides={"adapter_sha256": _h(b"WRONG")})
    with pytest.raises(AssemblerError):
        assemble_execution_identity_lock(
            block, config_representation=_GEARS_REPRESENTATION, fixture=True
        )


def test_declared_pathsha_digest_divergence_fails_closed(tmp_path: Path) -> None:
    block = _worker_block(tmp_path, pathsha_overrides={"worker_config": _h(b"WRONG")})
    with pytest.raises(AssemblerError):
        assemble_execution_identity_lock(
            block, config_representation=_GEARS_REPRESENTATION, fixture=True
        )


def test_representation_mismatch_fails_closed(tmp_path: Path) -> None:
    # Declared representation is cpa's, but config says gears' — divergence.
    block = _worker_block(tmp_path, representation=_CPA_REPRESENTATION)
    with pytest.raises(AssemblerError):
        assemble_execution_identity_lock(
            block, config_representation=_GEARS_REPRESENTATION, fixture=True
        )


def test_unregistered_representation_fails_closed(tmp_path: Path) -> None:
    block = _worker_block(tmp_path, representation="not_a_real_representation")
    with pytest.raises(AssemblerError):
        assemble_execution_identity_lock(
            block, config_representation="not_a_real_representation", fixture=True
        )


# --------------------------------------------------------------------------- #
# Scientific fail-closed on adapter_version
# --------------------------------------------------------------------------- #


def test_scientific_fails_closed_on_adapter_version(tmp_path: Path) -> None:
    # A direct source script is never a scientific execution identity even when
    # its bytes and all other lock files match.
    block = _worker_block(tmp_path)
    with pytest.raises(AssemblerError, match="deterministic .pyz bundle"):
        assemble_execution_identity_lock(
            block,
            config_representation=_GEARS_REPRESENTATION,
            fixture=False,
            expected_worker_method="gears",
        )


def _scientific_bundle_block(
    tmp_path: Path,
    *,
    bundle_method: str,
    adapter_version: str = _GEARS_ADAPTER_VERSION,
) -> WorkerBlock:
    """A scientific worker block: a real ``.pyz`` bundle + a declared adapter_version.

    The declared version defaults to the value the COMMITTED manifest registers
    for ``gears`` — a scientific lock only assembles when the declaration agrees
    with the manifest.
    """
    block = _worker_block(tmp_path, adapter_version=adapter_version)
    repo = Path(__file__).resolve().parents[4]
    bundle = build_worker_bundle(
        source_root=repo,
        entrypoint=repo / "scripts" / "baselines" / "gears_worker.py",
        output_path=tmp_path / f"{bundle_method}.pyz",
        method=bundle_method,
    )
    return replace(
        block,
        worker_script=PathSha(path=bundle.path, sha256=bundle.sha256),
    )


def _write_manifest(tmp: Path, payload: object, *, name: str = "adapter_versions.json") -> Path:
    """Write a candidate adapter manifest; a ``str`` payload is written verbatim."""
    path = tmp / name
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    return path


def test_the_committed_adapter_manifest_is_the_repository_configs_file() -> None:
    """The manifest is located from the module, never from a hardcoded absolute path."""
    repo = Path(__file__).resolve().parents[4]
    assert identity_lock_module._COMMITTED_ADAPTER_MANIFEST == (
        repo / "configs" / "compose_adapter_versions_v1.json"
    )
    assert identity_lock_module._COMMITTED_ADAPTER_MANIFEST.is_file()


def test_adapter_manifest_roster_must_be_exactly_gears_and_cpa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An extra OR a missing method fails closed even when the asked-for method resolves.

    Both manifests below would happily answer ``"gears"`` if the roster were not
    required exactly, so this test measures the roster check and nothing else.
    """
    for payload in (
        {
            "schema": "compose_adapter_versions_v1",
            "methods": {
                "gears": _GEARS_ADAPTER_VERSION,
                "cpa": _CPA_ADAPTER_VERSION,
                "stub": "stub-2",
            },
        },
        {
            "schema": "compose_adapter_versions_v1",
            "methods": {"gears": _GEARS_ADAPTER_VERSION},
        },
    ):
        manifest = _write_manifest(tmp_path, payload, name=f"{len(payload['methods'])}.json")
        monkeypatch.setattr(
            identity_lock_module, "_COMMITTED_ADAPTER_MANIFEST", manifest, raising=True
        )
        with pytest.raises(AssemblerError, match="roster must be exactly"):
            identity_lock_module._scientific_adapter_version("gears")


@pytest.mark.parametrize(
    ("case", "payload"),
    [
        (
            "wrong_schema",
            {
                "schema": "compose_adapter_versions_v2",
                "methods": {"gears": _GEARS_ADAPTER_VERSION, "cpa": _CPA_ADAPTER_VERSION},
            },
        ),
        (
            "extra_top_level_key",
            {
                "schema": "compose_adapter_versions_v1",
                "methods": {"gears": _GEARS_ADAPTER_VERSION, "cpa": _CPA_ADAPTER_VERSION},
                "note": "not part of the schema",
            },
        ),
        (
            "missing_top_level_key",
            {"methods": {"gears": _GEARS_ADAPTER_VERSION, "cpa": _CPA_ADAPTER_VERSION}},
        ),
        (
            "empty_version",
            {
                "schema": "compose_adapter_versions_v1",
                "methods": {"gears": "", "cpa": _CPA_ADAPTER_VERSION},
            },
        ),
        (
            "non_string_version",
            {
                "schema": "compose_adapter_versions_v1",
                "methods": {"gears": 1, "cpa": _CPA_ADAPTER_VERSION},
            },
        ),
        (
            "methods_not_an_object",
            {"schema": "compose_adapter_versions_v1", "methods": ["gears", "cpa"]},
        ),
        ("not_a_json_object", "[1, 2, 3]"),
        ("not_json_at_all", "{schema: compose_adapter_versions_v1"),
    ],
)
def test_malformed_adapter_manifest_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, payload: object
) -> None:
    manifest = _write_manifest(tmp_path, payload, name=f"{case}.json")
    monkeypatch.setattr(identity_lock_module, "_COMMITTED_ADAPTER_MANIFEST", manifest, raising=True)
    with pytest.raises(AssemblerError):
        identity_lock_module._scientific_adapter_version("gears")


@pytest.mark.parametrize("error", [FileNotFoundError(2, "gone"), PermissionError(13, "denied")])
def test_an_os_error_on_the_manifest_re_read_is_an_assembler_error(
    monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    """The digest-bound re-read is a SECOND open, and it can fail on its own.

    ``_hash_regular_file`` wraps the first open's OS errors, but
    ``read_verified_json`` calls ``Path(path).read_bytes()`` — if the manifest
    disappears or becomes unreadable between the hash and the re-read, a raw
    ``OSError`` would escape the assembler's single fail-closed error type. The
    window is real precisely because there are two opens.
    """

    def _boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise error

    monkeypatch.setattr(identity_lock_module, "read_verified_json", _boom, raising=True)
    with pytest.raises(AssemblerError, match="is unusable"):
        identity_lock_module._scientific_adapter_version("gears")


def test_scientific_assembly_fails_closed_when_the_committed_manifest_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-manifest fail-closed behaviour is preserved as an explicit negative."""
    block = _scientific_bundle_block(tmp_path, bundle_method="gears")
    monkeypatch.setattr(
        identity_lock_module,
        "_COMMITTED_ADAPTER_MANIFEST",
        tmp_path / "no-such-adapter-manifest.json",
        raising=True,
    )
    with pytest.raises(AssemblerError, match="committed adapter manifest"):
        assemble_execution_identity_lock(
            block,
            config_representation=_GEARS_REPRESENTATION,
            fixture=False,
            expected_worker_method="gears",
        )


def test_non_regular_adapter_manifest_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symlinked manifest fails the same node-kind policy the worker files face."""
    real = _write_manifest(
        tmp_path,
        {
            "schema": "compose_adapter_versions_v1",
            "methods": {"gears": _GEARS_ADAPTER_VERSION, "cpa": _CPA_ADAPTER_VERSION},
        },
    )
    link = tmp_path / "linked_manifest.json"
    link.symlink_to(real)
    monkeypatch.setattr(identity_lock_module, "_COMMITTED_ADAPTER_MANIFEST", link, raising=True)
    with pytest.raises(AssemblerError, match="node-kind policy"):
        identity_lock_module._scientific_adapter_version("gears")


def test_scientific_bundle_assembles_adapter_version_from_the_committed_manifest(
    tmp_path: Path,
) -> None:
    """The scientific lock now ASSEMBLES: the code-level adapter blocker is closed."""
    block = _scientific_bundle_block(tmp_path, bundle_method="gears")
    lock = assemble_execution_identity_lock(
        block,
        config_representation=_GEARS_REPRESENTATION,
        fixture=False,
        expected_worker_method="gears",
    )
    assert lock.adapter_version == _GEARS_ADAPTER_VERSION
    assert lock.adapter_sha256 == _h(_ADAPTER_BYTES)


def test_scientific_declared_adapter_version_mismatch_fails_closed(tmp_path: Path) -> None:
    """The manifest is the source; the declaration is only an expectation."""
    block = _scientific_bundle_block(tmp_path, bundle_method="gears", adapter_version="stub-2")
    with pytest.raises(AssemblerError, match="adapter_version: declared version diverges"):
        assemble_execution_identity_lock(
            block,
            config_representation=_GEARS_REPRESENTATION,
            fixture=False,
            expected_worker_method="gears",
        )


def test_the_scientific_adapter_version_comes_from_the_committed_method_manifest() -> None:
    from alive.compose.driver.identity_lock import _scientific_adapter_version

    assert _scientific_adapter_version("gears") == "compose-gears-adapter-v1"
    assert _scientific_adapter_version("cpa") == "compose-cpa-adapter-v1"
    with pytest.raises(AssemblerError, match="method"):
        _scientific_adapter_version("stub")


def test_scientific_bundle_method_mismatch_fails_closed(tmp_path: Path) -> None:
    block = _scientific_bundle_block(tmp_path, bundle_method="cpa")
    with pytest.raises(AssemblerError, match="bundle is invalid"):
        assemble_execution_identity_lock(
            block,
            config_representation=_GEARS_REPRESENTATION,
            fixture=False,
            expected_worker_method="gears",
        )


# --------------------------------------------------------------------------- #
# Node-kind policy: a symlinked worker file fails closed
# --------------------------------------------------------------------------- #


def test_symlink_worker_file_fails_closed(tmp_path: Path) -> None:
    ws, aa, wc, rm, rl = _make_worker_files(tmp_path)
    # Replace worker_config with a symlink to a real regular file whose bytes
    # equal the declared config bytes, so the ONLY reason to reject is node-kind.
    target = tmp_path / "real_config_target"
    target.write_bytes(_CONFIG_BYTES)
    wc.unlink()
    os.symlink(target, wc)
    assert Path(wc).is_symlink()
    block = _worker_block(tmp_path, files=(ws, aa, wc, rm, rl))
    with pytest.raises(AssemblerError):
        assemble_execution_identity_lock(
            block, config_representation=_GEARS_REPRESENTATION, fixture=True
        )


def test_symlink_worker_script_fails_closed(tmp_path: Path) -> None:
    ws, aa, wc, rm, rl = _make_worker_files(tmp_path)
    target = tmp_path / "real_worker_target"
    target.write_bytes(_WORKER_SCRIPT_BYTES)
    ws.unlink()
    os.symlink(target, ws)
    block = _worker_block(tmp_path, files=(ws, aa, wc, rm, rl))
    with pytest.raises(AssemblerError):
        assemble_execution_identity_lock(
            block, config_representation=_GEARS_REPRESENTATION, fixture=True
        )


def test_symlink_adapter_artifact_fails_closed(tmp_path: Path) -> None:
    # A symlinked adapter_artifact (bytes equal to the declared adapter bytes, so
    # the ONLY reason to reject is the node-kind policy) fails closed — the
    # assembler is the sole enforcer of node-kind on the adapter_artifact it hashes.
    ws, aa, wc, rm, rl = _make_worker_files(tmp_path)
    target = tmp_path / "real_adapter_target"
    target.write_bytes(_ADAPTER_BYTES)
    aa.unlink()
    os.symlink(target, aa)
    assert Path(aa).is_symlink()
    block = _worker_block(tmp_path, files=(ws, aa, wc, rm, rl))
    with pytest.raises(AssemblerError):
        assemble_execution_identity_lock(
            block, config_representation=_GEARS_REPRESENTATION, fixture=True
        )


def test_declared_adapter_artifact_pathsha_divergence_fails_closed(tmp_path: Path) -> None:
    block = _worker_block(tmp_path, pathsha_overrides={"adapter_artifact": _h(b"WRONG")})
    with pytest.raises(AssemblerError):
        assemble_execution_identity_lock(
            block, config_representation=_GEARS_REPRESENTATION, fixture=True
        )


# --------------------------------------------------------------------------- #
# {gears, cpa} membership + full backend assembly
# --------------------------------------------------------------------------- #


def test_deep_baseline_methods_constant() -> None:
    assert DEEP_BASELINE_METHODS == frozenset({"gears", "cpa"})


def test_assemble_baseline_backends_rejects_extra_method(tmp_path: Path) -> None:
    blocks = {"gears": _dummy_block(), "cpa": _dummy_block(), "rogue": _dummy_block()}
    run_spec = _minimal_run_spec(blocks, tmp_path)
    with pytest.raises(AssemblerError):
        assemble_baseline_backends(
            run_spec,
            fixture=True,
            representations={"gears": _GEARS_REPRESENTATION, "cpa": _CPA_REPRESENTATION},
        )


def test_assemble_baseline_backends_rejects_missing_method(tmp_path: Path) -> None:
    blocks = {"gears": _dummy_block()}
    run_spec = _minimal_run_spec(blocks, tmp_path)
    with pytest.raises(AssemblerError):
        assemble_baseline_backends(
            run_spec,
            fixture=True,
            representations={"gears": _GEARS_REPRESENTATION, "cpa": _CPA_REPRESENTATION},
        )


def test_assemble_baseline_backends_rejects_mode_flag_mismatch(tmp_path: Path) -> None:
    blocks = {"gears": _dummy_block(), "cpa": _dummy_block()}
    run_spec = _minimal_run_spec(blocks, tmp_path, mode="fixture")
    with pytest.raises(AssemblerError):
        assemble_baseline_backends(
            run_spec,
            fixture=False,  # contradicts run_spec.mode == "fixture"
            representations={"gears": _GEARS_REPRESENTATION, "cpa": _CPA_REPRESENTATION},
        )


def test_assemble_baseline_backends_happy(tmp_path: Path) -> None:
    gdir = tmp_path / "gears"
    cdir = tmp_path / "cpa"
    gdir.mkdir()
    cdir.mkdir()
    gblock = _worker_block(gdir, representation=_GEARS_REPRESENTATION)
    cblock = _worker_block(cdir, representation=_CPA_REPRESENTATION)
    run_spec = _minimal_run_spec({"gears": gblock, "cpa": cblock}, tmp_path)
    backends = assemble_baseline_backends(
        run_spec,
        fixture=True,
        representations={"gears": _GEARS_REPRESENTATION, "cpa": _CPA_REPRESENTATION},
    )
    assert set(backends) == {"gears", "cpa"}
    assert isinstance(backends["gears"], SubprocessBaselineBackend)
    assert backends["gears"].execution_identity_lock.prediction_representation == (
        _GEARS_REPRESENTATION
    )
    assert backends["cpa"].execution_identity_lock.prediction_representation == _CPA_REPRESENTATION
    assert backends["gears"].expected_response_artifact_sha256 == _h(b"resp")
    assert backends["gears"].approved_artifacts_root == str(tmp_path)
    assert backends["gears"].allow_local_approved_root_checkpoint_store is True
    assert backends["cpa"].allow_local_approved_root_checkpoint_store is True
    assert backends["gears"].name == "gears"
    assert backends["gears"].worker_identity_paths == {
        "worker_config": gblock.worker_config.path,
        "resource_manifest": gblock.resource_manifest.path,
        "requirements_lock": gblock.requirements_lock.path,
        "adapter_artifact": gblock.adapter_artifact.path,
    }
