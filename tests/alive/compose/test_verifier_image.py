from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from alive.compose.verifier_image import (
    VERIFIER_IMAGE_LOCK_SCHEMA,
    VERIFIER_IMAGE_SIGNATURE_SCHEMA,
    VerifierImageLockError,
    build_verifier_signature_subject,
    canonical_json,
    load_verifier_image_lock,
    self_checksum,
    validate_verifier_image_lock,
    validate_verifier_signature_subject,
)

ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "scripts/compose/run_gears_probe_a_verifier_oci.py"
LOCK_BUILDER = ROOT / "scripts/compose/build_probe_a_verifier_image_lock.py"
SUBJECT_BUILDER = ROOT / "scripts/compose/build_probe_a_verifier_signature_subject.py"
COMMIT = "1" * 40
CODE_SHA = "2" * 64
IMAGE_DIGEST = "sha256:" + "3" * 64


def _load_launcher():
    spec = importlib.util.spec_from_file_location("run_gears_probe_a_verifier_oci", LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_lock_builder():
    spec = importlib.util.spec_from_file_location("build_probe_a_verifier_image_lock", LOCK_BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_subject_builder():
    spec = importlib.util.spec_from_file_location(
        "build_probe_a_verifier_signature_subject", SUBJECT_BUILDER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _lock() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": VERIFIER_IMAGE_LOCK_SCHEMA,
        "protocol": "COMPOSE-K562-v1",
        "git_commit": COMMIT,
        "image_reference": f"registry.example/alive/probe-a@{IMAGE_DIGEST}",
        "image_manifest_digest": IMAGE_DIGEST,
        "platform": "linux/amd64",
        "python_base_image": "docker.io/library/python@sha256:" + "4" * 64,
        "uv_build_image": "ghcr.io/astral-sh/uv@sha256:" + "5" * 64,
        "dockerfile_sha256": "6" * 64,
        "uv_lock_sha256": "7" * 64,
        "verifier_code_sha256": CODE_SHA,
        "signature": {
            "schema": VERIFIER_IMAGE_SIGNATURE_SCHEMA,
            "mode": "cosign_keyless_subject_bundle_v1",
            "subject_sha256": "b" * 64,
            "bundle_sha256": "8" * 64,
            "cosign_executable_sha256": "9" * 64,
            "trusted_root_sha256": "a" * 64,
            "certificate_identity": "https://github.com/example/alive/.github/workflows/build.yml@refs/heads/main",
            "oidc_issuer": "https://token.actions.githubusercontent.com",
        },
        "approved_at_utc": "2026-07-20T00:00:00Z",
        "approval_id": "probe-a-verifier-2026-07-20",
        "self_checksum": "",
    }
    payload["self_checksum"] = self_checksum(payload)
    return payload


def _write_lock(path: Path, payload: dict[str, object]) -> str:
    data = (canonical_json(payload) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_loads_canonical_owner_frozen_image_lock(tmp_path):
    path = tmp_path / "verifier-image-lock.json"
    external_sha = _write_lock(path, _lock())
    loaded = load_verifier_image_lock(
        path,
        expected_sha256=external_sha,
        expected_git_commit=COMMIT,
        expected_verifier_code_sha256=CODE_SHA,
    )
    assert loaded["image_manifest_digest"] == IMAGE_DIGEST
    assert loaded["platform"] == "linux/amd64"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("image_reference", "registry.example/alive/probe-a:latest", "digest image"),
        ("image_reference", f"--privileged@{IMAGE_DIGEST}", "digest image"),
        ("python_base_image", "python:3.12-slim", "digest image"),
        ("platform", "linux", "platform is not admitted"),
    ],
)
def test_rejects_mutable_or_ambiguous_image_identity(field, value, message):
    payload = _lock()
    payload[field] = value
    payload["self_checksum"] = self_checksum(payload)
    with pytest.raises(VerifierImageLockError, match=message):
        validate_verifier_image_lock(
            payload,
            expected_git_commit=COMMIT,
            expected_verifier_code_sha256=CODE_SHA,
        )


def test_rejects_digest_mismatch_even_with_recomputed_checksum():
    payload = _lock()
    payload["image_manifest_digest"] = "sha256:" + "9" * 64
    payload["self_checksum"] = self_checksum(payload)
    with pytest.raises(VerifierImageLockError, match="exact OCI manifest/index digest"):
        validate_verifier_image_lock(
            payload,
            expected_git_commit=COMMIT,
            expected_verifier_code_sha256=CODE_SHA,
        )


def test_rejects_unsigned_owner_assertion():
    payload = _lock()
    signature = dict(payload["signature"])
    signature["mode"] = "owner_assertion_only"
    payload["signature"] = signature
    payload["self_checksum"] = self_checksum(payload)
    with pytest.raises(VerifierImageLockError, match="require a signed Cosign subject"):
        validate_verifier_image_lock(
            payload,
            expected_git_commit=COMMIT,
            expected_verifier_code_sha256=CODE_SHA,
        )


def test_external_pin_and_canonical_bytes_are_mandatory(tmp_path):
    path = tmp_path / "verifier-image-lock.json"
    payload = _lock()
    external_sha = _write_lock(path, payload)
    with pytest.raises(VerifierImageLockError, match="external pin"):
        load_verifier_image_lock(
            path,
            expected_sha256="0" * 64,
            expected_git_commit=COMMIT,
            expected_verifier_code_sha256=CODE_SHA,
        )
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    pretty_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert pretty_sha != external_sha
    with pytest.raises(VerifierImageLockError, match="canonical JSON"):
        load_verifier_image_lock(
            path,
            expected_sha256=pretty_sha,
            expected_git_commit=COMMIT,
            expected_verifier_code_sha256=CODE_SHA,
        )


def test_symlink_lock_is_rejected(tmp_path):
    target = tmp_path / "target.json"
    external_sha = _write_lock(target, _lock())
    link = tmp_path / "lock.json"
    link.symlink_to(target)
    with pytest.raises(VerifierImageLockError, match="must not be a symlink"):
        load_verifier_image_lock(
            link,
            expected_sha256=external_sha,
            expected_git_commit=COMMIT,
            expected_verifier_code_sha256=CODE_SHA,
        )


def test_container_command_has_fail_closed_runtime_boundary(tmp_path):
    launcher = _load_launcher()
    args = argparse.Namespace(
        evidence_root=str(tmp_path),
        report_sha256="a" * 64,
        registration_sha256="b" * 64,
        manifest_sha256="c" * 64,
        provider_attestation_sha256="d" * 64,
        payload_sha256="e" * 64,
        roster_receipt_sha256="f" * 64,
        git_commit=COMMIT,
        expected_verifier_code_sha256=CODE_SHA,
        image_lock_sha256="0" * 64,
    )
    command = launcher._container_command(args, engine="/usr/bin/docker", lock=_lock())
    joined = " ".join(command)
    for required in (
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--verifier-image-digest",
        IMAGE_DIGEST,
        "--verifier-image-lock-sha256",
    ):
        assert required in command or required in joined
    assert str(ROOT) not in joined
    mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
    assert mounts == [f"type=bind,src={tmp_path.resolve()},dst=/evidence"]
    assert command[command.index("--user") + 1] == "65532:65532"


def test_signature_command_binds_bundle_identity_issuer_and_digest(tmp_path):
    launcher = _load_launcher()
    bundle = tmp_path / "cosign.bundle"
    subject = tmp_path / "signature-subject.json"
    trusted_root = tmp_path / "trusted-root.json"
    command = launcher._cosign_command("/usr/bin/cosign", _lock(), subject, bundle, trusted_root)
    assert command[1:4] == ["verify-blob", str(subject), "--offline"]
    assert command[command.index("--bundle") + 1] == str(bundle)
    assert command[command.index("--trusted-root") + 1] == str(trusted_root)
    assert "--certificate-identity" in command
    assert "--certificate-oidc-issuer" in command


def test_signed_subject_must_equal_every_decision_bearing_lock_field():
    subject = build_verifier_signature_subject(
        git_commit=COMMIT,
        image_reference=f"registry.example/alive/probe-a@{IMAGE_DIGEST}",
        platform="linux/amd64",
        python_base_image="docker.io/library/python@sha256:" + "4" * 64,
        uv_build_image="ghcr.io/astral-sh/uv@sha256:" + "5" * 64,
        dockerfile_sha256="6" * 64,
        uv_lock_sha256="7" * 64,
        verifier_code_sha256=CODE_SHA,
    )
    subject["git_commit"] = "0" * 40
    with pytest.raises(VerifierImageLockError, match="differs from the owner image lock"):
        validate_verifier_signature_subject(subject, expected_lock=_lock())


def test_lock_builder_writes_canonical_bytes_once_and_prints_external_pin(tmp_path, capsys):
    builder = _load_lock_builder()
    inputs = {}
    for name in ("Dockerfile", "uv.lock", "bundle", "cosign", "trusted-root"):
        path = tmp_path / name
        path.write_bytes(f"{name}\n".encode())
        inputs[name] = path
    output = tmp_path / "verifier-image-lock.json"
    subject = build_verifier_signature_subject(
        git_commit=COMMIT,
        image_reference=f"registry.example/alive/probe-a@{IMAGE_DIGEST}",
        platform="linux/amd64",
        python_base_image="docker.io/library/python@sha256:" + "4" * 64,
        uv_build_image="ghcr.io/astral-sh/uv@sha256:" + "5" * 64,
        dockerfile_sha256=hashlib.sha256(inputs["Dockerfile"].read_bytes()).hexdigest(),
        uv_lock_sha256=hashlib.sha256(inputs["uv.lock"].read_bytes()).hexdigest(),
        verifier_code_sha256=CODE_SHA,
    )
    subject_path = tmp_path / "signature-subject.json"
    subject_path.write_text(canonical_json(subject) + "\n", encoding="utf-8")
    argv = [
        "--git-commit",
        COMMIT,
        "--image-reference",
        f"registry.example/alive/probe-a@{IMAGE_DIGEST}",
        "--platform",
        "linux/amd64",
        "--python-base-image",
        "docker.io/library/python@sha256:" + "4" * 64,
        "--uv-build-image",
        "ghcr.io/astral-sh/uv@sha256:" + "5" * 64,
        "--dockerfile",
        str(inputs["Dockerfile"]),
        "--uv-lock",
        str(inputs["uv.lock"]),
        "--verifier-code-sha256",
        CODE_SHA,
        "--cosign-bundle",
        str(inputs["bundle"]),
        "--cosign-subject",
        str(subject_path),
        "--cosign-executable",
        str(inputs["cosign"]),
        "--trusted-root",
        str(inputs["trusted-root"]),
        "--certificate-identity",
        "https://github.com/example/alive/.github/workflows/build.yml@refs/heads/main",
        "--oidc-issuer",
        "https://token.actions.githubusercontent.com",
        "--approved-at-utc",
        "2026-07-20T00:00:00Z",
        "--approval-id",
        "probe-a-verifier-2026-07-20",
        "--out",
        str(output),
    ]
    assert builder.main(argv) == 0
    external_pin = capsys.readouterr().out.strip()
    assert external_pin == hashlib.sha256(output.read_bytes()).hexdigest()
    assert output.read_bytes().endswith(b"\n")
    with pytest.raises(FileExistsError):
        builder.main(argv)


def test_subject_builder_writes_exact_signed_identity_once(tmp_path, capsys):
    builder = _load_subject_builder()
    output = tmp_path / "signature-subject.json"
    argv = [
        "--git-commit",
        COMMIT,
        "--image-reference",
        f"registry.example/alive/probe-a@{IMAGE_DIGEST}",
        "--platform",
        "linux/amd64",
        "--python-base-image",
        "docker.io/library/python@sha256:" + "4" * 64,
        "--uv-build-image",
        "ghcr.io/astral-sh/uv@sha256:" + "5" * 64,
        "--dockerfile-sha256",
        "6" * 64,
        "--uv-lock-sha256",
        "7" * 64,
        "--verifier-code-sha256",
        CODE_SHA,
        "--out",
        str(output),
    ]
    assert builder.main(argv) == 0
    assert capsys.readouterr().out.strip() == hashlib.sha256(output.read_bytes()).hexdigest()
    subject = json.loads(output.read_bytes())
    assert subject["image_manifest_digest"] == IMAGE_DIGEST
    assert output.read_bytes() == (canonical_json(subject) + "\n").encode()
    with pytest.raises(FileExistsError):
        builder.main(argv)
