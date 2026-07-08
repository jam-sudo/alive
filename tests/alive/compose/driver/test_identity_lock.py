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
import os
import sys
from pathlib import Path

import pytest

from alive.compose.baseline_subprocess import (
    ExecutionIdentityLock,
    SubprocessBaselineBackend,
)
from alive.compose.driver.identity_lock import (
    DEEP_BASELINE_METHODS,
    AssemblerError,
    assemble_baseline_backends,
    assemble_execution_identity_lock,
    build_subprocess_backend,
)
from alive.compose.driver.run_spec import PathSha, ResolvedRunSpec, WorkerBlock

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
        schema="compose_resolved_run_spec_v1",
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
    assert backend.seed == 11
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
    # Valid files + matching digests, so we reach the adapter_version step and
    # fail there: no committed versioned adapter manifest exists (sub-project B).
    block = _worker_block(tmp_path)
    with pytest.raises(AssemblerError):
        assemble_execution_identity_lock(
            block, config_representation=_GEARS_REPRESENTATION, fixture=False
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
    assert backends["gears"].name == "gears"
