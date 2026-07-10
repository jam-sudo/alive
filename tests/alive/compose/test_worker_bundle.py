"""Known-answer and adversarial tests for deterministic worker execution bundles."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from alive.compose.worker_bundle import (
    WORKER_BUNDLE_HELPER_SOURCES,
    WORKER_BUNDLE_MANIFEST_PATH,
    WorkerBundleError,
    build_worker_bundle,
    validate_worker_bundle,
)

_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = stat.S_IFREG | 0o444


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _minimal_source_tree(tmp_path: Path, *, bad_member: str | None = None) -> tuple[Path, Path]:
    root = tmp_path / "source"
    root.mkdir(parents=True)
    entrypoint = root / "worker.py"
    entrypoint.write_text("def main():\n    return 0\n", encoding="utf-8")
    for archive_path, relative_path in WORKER_BUNDLE_HELPER_SOURCES.items():
        source = root / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        text = "VALUE = 1\n"
        if archive_path == bad_member:
            text = "try:\n    pass\nexcept* Exception:\n    pass\n"
        source.write_text(text, encoding="utf-8")
    return root, entrypoint


def _info(name: str, *, compression: int = zipfile.ZIP_STORED) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_FIXED_TIMESTAMP)
    info.compress_type = compression
    info.create_system = 3
    info.create_version = 20
    info.extract_version = 20
    info.external_attr = _FILE_MODE << 16
    info.internal_attr = 0
    info.extra = b""
    info.comment = b""
    return info


def _read_members(path: Path) -> list[tuple[zipfile.ZipInfo, bytes]]:
    with zipfile.ZipFile(path, "r") as archive:
        return [(info, archive.read(info)) for info in archive.infolist()]


def _rewrite(
    path: Path,
    members: list[tuple[zipfile.ZipInfo, bytes]],
    *,
    archive_comment: bytes = b"",
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.comment = archive_comment
        for info, content in members:
            archive.writestr(info, content)
    path.chmod(0o600)
    path.write_bytes(buffer.getvalue())
    path.chmod(0o400)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode()


def _rechecksum_manifest(manifest: dict[str, object]) -> bytes:
    body = {key: value for key, value in manifest.items() if key != "manifest_checksum"}
    manifest["manifest_checksum"] = hashlib.sha256(_canonical(body)).hexdigest()
    return _canonical(manifest)


@pytest.mark.parametrize("method", ["cpa", "gears"])
def test_real_worker_bundle_is_byte_deterministic_and_exact(tmp_path: Path, method: str) -> None:
    root = _repo_root()
    first_path = tmp_path / f"{method}-first.pyz"
    second_path = tmp_path / f"{method}-second.pyz"
    first = build_worker_bundle(
        source_root=root,
        entrypoint=root / f"scripts/baselines/{method}_worker.py",
        output_path=first_path,
        method=method,
    )
    second = build_worker_bundle(
        source_root=root,
        entrypoint=root / f"scripts/baselines/{method}_worker.py",
        output_path=second_path,
        method=method,
    )

    assert len(WORKER_BUNDLE_HELPER_SOURCES) == 8
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first.sha256 == second.sha256 == hashlib.sha256(first_path.read_bytes()).hexdigest()
    assert first.manifest == second.manifest
    assert first.manifest["method"] == method
    assert first.manifest["python_minimum"] == "3.10"
    assert [record["path"] for record in first.manifest["files"]] == sorted(
        {"__main__.py", *WORKER_BUNDLE_HELPER_SOURCES}
    )
    assert first_path.stat().st_mode & 0o777 == 0o400

    with zipfile.ZipFile(first_path, "r") as archive:
        infos = archive.infolist()
        assert [info.filename for info in infos] == sorted(
            {"__main__.py", *WORKER_BUNDLE_HELPER_SOURCES, WORKER_BUNDLE_MANIFEST_PATH}
        )
        assert archive.comment == b""
        assert all(info.compress_type == zipfile.ZIP_STORED for info in infos)
        assert all(info.date_time == _FIXED_TIMESTAMP for info in infos)
        assert all(info.create_system == 3 for info in infos)
        assert all((info.external_attr >> 16) == _FILE_MODE for info in infos)


def test_build_is_exclusive_and_rejects_symlinked_source(tmp_path: Path) -> None:
    root, entrypoint = _minimal_source_tree(tmp_path)
    output = tmp_path / "worker.pyz"
    build_worker_bundle(source_root=root, entrypoint=entrypoint, output_path=output, method="cpa")
    with pytest.raises(WorkerBundleError, match="cannot create"):
        build_worker_bundle(
            source_root=root,
            entrypoint=entrypoint,
            output_path=output,
            method="cpa",
        )

    linked = root / "linked.py"
    linked.symlink_to(entrypoint)
    with pytest.raises(WorkerBundleError, match="regular non-symlink"):
        build_worker_bundle(
            source_root=root,
            entrypoint=linked,
            output_path=tmp_path / "linked.pyz",
            method="cpa",
        )

    external_root, _external_entrypoint = _minimal_source_tree(tmp_path / "external")
    wrapper = tmp_path / "wrapper"
    wrapper.mkdir()
    (wrapper / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    (wrapper / "src").symlink_to(external_root / "src", target_is_directory=True)
    with pytest.raises(WorkerBundleError, match="symlinked parents"):
        build_worker_bundle(
            source_root=wrapper,
            entrypoint=wrapper / "worker.py",
            output_path=tmp_path / "parent-link.pyz",
            method="cpa",
        )


def test_build_rejects_python_newer_than_310(tmp_path: Path) -> None:
    bad_member = next(iter(WORKER_BUNDLE_HELPER_SOURCES))
    root, entrypoint = _minimal_source_tree(tmp_path, bad_member=bad_member)
    with pytest.raises(WorkerBundleError, match="Python 3.10"):
        build_worker_bundle(
            source_root=root,
            entrypoint=entrypoint,
            output_path=tmp_path / "bad.pyz",
            method="cpa",
        )


@pytest.fixture
def valid_bundle(tmp_path: Path) -> Path:
    root, entrypoint = _minimal_source_tree(tmp_path)
    output = tmp_path / "valid.pyz"
    build_worker_bundle(source_root=root, entrypoint=entrypoint, output_path=output, method="gears")
    output.chmod(0o600)
    return output


def test_validate_rejects_duplicate_and_unsafe_archive_members(valid_bundle: Path) -> None:
    original = _read_members(valid_bundle)
    duplicate = list(original)
    duplicate.append((_info(original[0][0].filename), original[0][1]))
    with pytest.warns(UserWarning, match="Duplicate name"):
        _rewrite(valid_bundle, duplicate)
    with pytest.raises(WorkerBundleError, match="duplicate archive"):
        validate_worker_bundle(valid_bundle)

    original_info, original_data = original[0]
    unsafe = [(_info("../escape.py"), original_data), *original[1:]]
    _rewrite(valid_bundle, unsafe)
    with pytest.raises(WorkerBundleError, match="unsafe archive path"):
        validate_worker_bundle(valid_bundle)


@pytest.mark.parametrize("mutation", ["compression", "timestamp", "mode", "order", "comment"])
def test_validate_rejects_noncanonical_zip_metadata(valid_bundle: Path, mutation: str) -> None:
    members = _read_members(valid_bundle)
    archive_comment = b""
    if mutation == "compression":
        info, content = members[0]
        members[0] = (_info(info.filename, compression=zipfile.ZIP_DEFLATED), content)
    elif mutation == "timestamp":
        info, content = members[0]
        changed = _info(info.filename)
        changed.date_time = (2020, 1, 1, 0, 0, 0)
        members[0] = (changed, content)
    elif mutation == "mode":
        info, content = members[0]
        changed = _info(info.filename)
        changed.external_attr = (stat.S_IFREG | 0o644) << 16
        members[0] = (changed, content)
    elif mutation == "order":
        members = list(reversed(members))
    elif mutation == "comment":
        archive_comment = b"not-canonical"
    _rewrite(valid_bundle, members, archive_comment=archive_comment)
    with pytest.raises(WorkerBundleError):
        validate_worker_bundle(valid_bundle)


def test_validate_rejects_missing_extra_and_content_hash_drift(valid_bundle: Path) -> None:
    original = _read_members(valid_bundle)
    missing = original[:-1]
    _rewrite(valid_bundle, missing)
    with pytest.raises(WorkerBundleError, match="roster"):
        validate_worker_bundle(valid_bundle)

    extra = [*original, (_info("extra.py"), b"VALUE = 2\n")]
    _rewrite(valid_bundle, sorted(extra, key=lambda item: item[0].filename))
    with pytest.raises(WorkerBundleError, match="roster"):
        validate_worker_bundle(valid_bundle)

    drifted = list(original)
    for index, (info, content) in enumerate(drifted):
        if info.filename == "__main__.py":
            drifted[index] = (info, content + b"# changed\n")
            break
    _rewrite(valid_bundle, drifted)
    with pytest.raises(WorkerBundleError, match="differs from its manifest"):
        validate_worker_bundle(valid_bundle)


def test_validate_rejects_manifest_self_checksum_and_noncanonical_json(
    valid_bundle: Path,
) -> None:
    original = _read_members(valid_bundle)
    changed: list[tuple[zipfile.ZipInfo, bytes]] = []
    for info, content in original:
        if info.filename == WORKER_BUNDLE_MANIFEST_PATH:
            manifest = json.loads(content)
            manifest["manifest_checksum"] = "0" * 64
            content = _canonical(manifest)
        changed.append((info, content))
    _rewrite(valid_bundle, changed)
    with pytest.raises(WorkerBundleError, match="self-checksum"):
        validate_worker_bundle(valid_bundle)

    noncanonical: list[tuple[zipfile.ZipInfo, bytes]] = []
    for info, content in original:
        if info.filename == WORKER_BUNDLE_MANIFEST_PATH:
            manifest = json.loads(content)
            content = json.dumps(manifest, indent=2).encode()
        noncanonical.append((info, content))
    _rewrite(valid_bundle, noncanonical)
    with pytest.raises(WorkerBundleError, match="not canonical"):
        validate_worker_bundle(valid_bundle)


def test_validate_rejects_manifest_hash_forgery_with_python_311_source(
    valid_bundle: Path,
) -> None:
    original = _read_members(valid_bundle)
    member_name = next(iter(WORKER_BUNDLE_HELPER_SOURCES))
    bad_source = b"try:\n    pass\nexcept* Exception:\n    pass\n"
    manifest: dict[str, object] | None = None
    for info, content in original:
        if info.filename == WORKER_BUNDLE_MANIFEST_PATH:
            manifest = json.loads(content)
            break
    assert manifest is not None
    for record in manifest["files"]:
        if record["path"] == member_name:
            record["sha256"] = hashlib.sha256(bad_source).hexdigest()
            record["size"] = len(bad_source)
            break
    manifest_bytes = _rechecksum_manifest(manifest)

    changed: list[tuple[zipfile.ZipInfo, bytes]] = []
    for info, content in original:
        if info.filename == member_name:
            content = bad_source
        elif info.filename == WORKER_BUNDLE_MANIFEST_PATH:
            content = manifest_bytes
        changed.append((info, content))
    _rewrite(valid_bundle, changed)
    with pytest.raises(WorkerBundleError, match="Python 3.10"):
        validate_worker_bundle(valid_bundle)


def test_validate_checks_outer_sha_and_expected_method(valid_bundle: Path) -> None:
    digest = hashlib.sha256(valid_bundle.read_bytes()).hexdigest()
    info = validate_worker_bundle(valid_bundle, expected_method="gears", expected_sha256=digest)
    assert info.sha256 == digest
    assert info.path == os.path.abspath(valid_bundle)
    with pytest.raises(TypeError):
        info.manifest["method"] = "mutated"
    with pytest.raises(TypeError):
        info.manifest["files"][0]["path"] = "mutated.py"
    with pytest.raises(WorkerBundleError, match="controller expectation"):
        validate_worker_bundle(valid_bundle, expected_sha256="0" * 64)
    with pytest.raises(WorkerBundleError, match="method differs"):
        validate_worker_bundle(valid_bundle, expected_method="cpa")
