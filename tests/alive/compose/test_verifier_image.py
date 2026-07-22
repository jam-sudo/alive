from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from alive.compose.verifier_image import (
    OWNER_APPROVAL_MODE,
    OWNER_APPROVAL_NAMESPACE,
    VERIFIER_IMAGE_BUILD_CANDIDATE_SCHEMA,
    VERIFIER_IMAGE_LOCK_SCHEMA,
    VERIFIER_IMAGE_OWNER_APPROVAL_EVIDENCE_SCHEMA,
    VERIFIER_IMAGE_SIGNATURE_SCHEMA,
    VerifierImageLockError,
    build_verifier_image_candidate,
    build_verifier_owner_approval,
    build_verifier_signature_subject,
    canonical_json,
    load_verifier_image_candidate,
    load_verifier_image_lock,
    load_verifier_owner_approval,
    owner_public_key_identity,
    self_checksum,
    validate_verifier_image_lock,
    validate_verifier_signature_subject,
    verify_verifier_owner_approval_signature,
)

ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "scripts/compose/run_gears_probe_a_verifier_oci.py"
LOCK_BUILDER = ROOT / "scripts/compose/build_probe_a_verifier_image_lock.py"
SUBJECT_BUILDER = ROOT / "scripts/compose/build_probe_a_verifier_signature_subject.py"
CANDIDATE_BUILDER = ROOT / "scripts/compose/build_probe_a_verifier_image_candidate.py"
OWNER_APPROVAL_BUILDER = ROOT / "scripts/compose/build_probe_a_verifier_owner_approval.py"
COMMIT = "1" * 40
CODE_SHA = "2" * 64
IMAGE_DIGEST = "sha256:" + "3" * 64
OWNER_FINGERPRINT = "SHA256:" + "A" * 43


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


def _load_candidate_builder():
    spec = importlib.util.spec_from_file_location(
        "build_probe_a_verifier_image_candidate", CANDIDATE_BUILDER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_owner_approval_builder():
    spec = importlib.util.spec_from_file_location(
        "build_probe_a_verifier_owner_approval", OWNER_APPROVAL_BUILDER
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
        "owner_approval": {
            "schema": VERIFIER_IMAGE_OWNER_APPROVAL_EVIDENCE_SCHEMA,
            "mode": OWNER_APPROVAL_MODE,
            "namespace": OWNER_APPROVAL_NAMESPACE,
            "candidate_sha256": "c" * 64,
            "statement_sha256": "d" * 64,
            "signature_sha256": "e" * 64,
            "public_key_sha256": "f" * 64,
            "public_key_fingerprint": OWNER_FINGERPRINT,
            "ssh_keygen_executable_sha256": "0" * 64,
            "build_run_id": "123456",
        },
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


def _candidate() -> dict[str, str]:
    return build_verifier_image_candidate(
        git_commit=COMMIT,
        image_reference=f"ghcr.io/example/alive-verifier@{IMAGE_DIGEST}",
        platform="linux/amd64",
        python_base_image="docker.io/library/python@sha256:" + "4" * 64,
        uv_build_image="ghcr.io/astral-sh/uv@sha256:" + "5" * 64,
        dockerfile_sha256="6" * 64,
        uv_lock_sha256="7" * 64,
        verifier_code_sha256=CODE_SHA,
        build_repository="example/alive",
        build_workflow_ref=(
            "example/alive/.github/workflows/build-compose-probe-a-verifier.yml@refs/heads/main"
        ),
        build_run_id="123456",
    )


def _write_candidate(path: Path, candidate: dict[str, str]) -> str:
    data = (canonical_json(candidate) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _owner_material(
    tmp_path: Path, candidate: dict[str, str], candidate_sha256: str
) -> dict[str, Path | str]:
    private_key = tmp_path / "test-owner-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "", "-f", str(private_key)],
        check=True,
    )
    public_key = private_key.with_suffix(".pub")
    fields = public_key.read_text(encoding="ascii").split()
    public_key.write_text(f"{fields[0]} {fields[1]}\n", encoding="ascii")
    key = owner_public_key_identity(public_key)
    approval = build_verifier_owner_approval(
        candidate=candidate,
        candidate_sha256=candidate_sha256,
        approved_at_utc="2026-07-20T00:00:00Z",
        approval_id="probe-a-verifier-2026-07-20",
        owner_key_fingerprint=key["public_key_fingerprint"],
    )
    approval_path = tmp_path / "owner-approval.json"
    approval_path.write_text(canonical_json(approval) + "\n", encoding="utf-8")
    subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(private_key),
            "-n",
            OWNER_APPROVAL_NAMESPACE,
            str(approval_path),
        ],
        check=True,
        capture_output=True,
    )
    signature = Path(str(approval_path) + ".sig")
    return {
        "private_key": private_key,
        "approval": approval_path,
        "approval_sha256": hashlib.sha256(approval_path.read_bytes()).hexdigest(),
        "signature": signature,
        "signature_sha256": hashlib.sha256(signature.read_bytes()).hexdigest(),
        "public_key": public_key,
        "public_key_sha256": key["public_key_sha256"],
        "fingerprint": key["public_key_fingerprint"],
        "ssh_keygen": str(Path(shutil.which("ssh-keygen") or "").resolve(strict=True)),
    }


def test_loads_canonical_owner_frozen_image_lock(tmp_path):
    path = tmp_path / "verifier-image-lock.json"
    external_sha = _write_lock(path, _lock())
    loaded = load_verifier_image_lock(
        path,
        expected_sha256=external_sha,
        expected_git_commit=COMMIT,
        expected_verifier_code_sha256=CODE_SHA,
        expected_owner_key_fingerprint=OWNER_FINGERPRINT,
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
            expected_owner_key_fingerprint=OWNER_FINGERPRINT,
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
            expected_owner_key_fingerprint=OWNER_FINGERPRINT,
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
            expected_owner_key_fingerprint=OWNER_FINGERPRINT,
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
            expected_owner_key_fingerprint=OWNER_FINGERPRINT,
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
            expected_owner_key_fingerprint=OWNER_FINGERPRINT,
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
            expected_owner_key_fingerprint=OWNER_FINGERPRINT,
        )


def test_non_regular_lock_is_rejected(tmp_path):
    with pytest.raises(VerifierImageLockError, match="must be a regular file"):
        load_verifier_image_lock(
            tmp_path,
            expected_sha256="0" * 64,
            expected_git_commit=COMMIT,
            expected_verifier_code_sha256=CODE_SHA,
            expected_owner_key_fingerprint=OWNER_FINGERPRINT,
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
        owner_approval_sha256="d" * 64,
        owner_signature_sha256="e" * 64,
        owner_key_fingerprint=OWNER_FINGERPRINT,
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
    dockerfile_sha256 = hashlib.sha256(inputs["Dockerfile"].read_bytes()).hexdigest()
    uv_lock_sha256 = hashlib.sha256(inputs["uv.lock"].read_bytes()).hexdigest()
    candidate = build_verifier_image_candidate(
        git_commit=COMMIT,
        image_reference=f"registry.example/alive/probe-a@{IMAGE_DIGEST}",
        platform="linux/amd64",
        python_base_image="docker.io/library/python@sha256:" + "4" * 64,
        uv_build_image="ghcr.io/astral-sh/uv@sha256:" + "5" * 64,
        dockerfile_sha256=dockerfile_sha256,
        uv_lock_sha256=uv_lock_sha256,
        verifier_code_sha256=CODE_SHA,
        build_repository="example/alive",
        build_workflow_ref=(
            "example/alive/.github/workflows/build-compose-probe-a-verifier.yml@refs/heads/main"
        ),
        build_run_id="123456",
    )
    candidate_path = tmp_path / "candidate.json"
    candidate_sha256 = _write_candidate(candidate_path, candidate)
    owner = _owner_material(tmp_path, candidate, candidate_sha256)
    subject = build_verifier_signature_subject(
        git_commit=COMMIT,
        image_reference=f"registry.example/alive/probe-a@{IMAGE_DIGEST}",
        platform="linux/amd64",
        python_base_image="docker.io/library/python@sha256:" + "4" * 64,
        uv_build_image="ghcr.io/astral-sh/uv@sha256:" + "5" * 64,
        dockerfile_sha256=dockerfile_sha256,
        uv_lock_sha256=uv_lock_sha256,
        verifier_code_sha256=CODE_SHA,
        owner_approval_sha256=str(owner["approval_sha256"]),
        owner_signature_sha256=str(owner["signature_sha256"]),
        owner_key_fingerprint=str(owner["fingerprint"]),
    )
    subject_path = tmp_path / "signature-subject.json"
    subject_path.write_text(canonical_json(subject) + "\n", encoding="utf-8")
    argv = [
        "--candidate",
        str(candidate_path),
        "--candidate-sha256",
        candidate_sha256,
        "--expected-git-commit",
        COMMIT,
        "--expected-build-repository",
        "example/alive",
        "--expected-build-workflow-ref",
        "example/alive/.github/workflows/build-compose-probe-a-verifier.yml@refs/heads/main",
        "--dockerfile",
        str(inputs["Dockerfile"]),
        "--uv-lock",
        str(inputs["uv.lock"]),
        "--owner-approval",
        str(owner["approval"]),
        "--owner-approval-sha256",
        str(owner["approval_sha256"]),
        "--owner-signature",
        str(owner["signature"]),
        "--owner-signature-sha256",
        str(owner["signature_sha256"]),
        "--owner-public-key",
        str(owner["public_key"]),
        "--expected-owner-key-fingerprint",
        str(owner["fingerprint"]),
        "--ssh-keygen-executable",
        str(owner["ssh_keygen"]),
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
        "--out",
        str(output),
    ]
    assert builder.main(argv) == 0
    external_pin = capsys.readouterr().out.strip()
    assert external_pin == hashlib.sha256(output.read_bytes()).hexdigest()
    assert output.read_bytes().endswith(b"\n")
    lock = json.loads(output.read_bytes())
    assert lock["owner_approval"]["candidate_sha256"] == candidate_sha256
    assert lock["owner_approval"]["public_key_fingerprint"] == owner["fingerprint"]
    with pytest.raises(FileExistsError):
        builder.main(argv)


def test_owner_approval_is_canonical_candidate_bound_and_cryptographically_verified(tmp_path):
    candidate = _candidate()
    candidate_path = tmp_path / "candidate.json"
    candidate_sha256 = _write_candidate(candidate_path, candidate)
    owner = _owner_material(tmp_path, candidate, candidate_sha256)
    loaded = load_verifier_owner_approval(
        owner["approval"],
        expected_sha256=str(owner["approval_sha256"]),
        expected_candidate=candidate,
        expected_candidate_sha256=candidate_sha256,
        expected_owner_key_fingerprint=str(owner["fingerprint"]),
    )
    assert loaded["candidate_sha256"] == candidate_sha256
    evidence = verify_verifier_owner_approval_signature(
        statement=owner["approval"],
        signature=owner["signature"],
        public_key=owner["public_key"],
        expected_statement_sha256=str(owner["approval_sha256"]),
        expected_signature_sha256=str(owner["signature_sha256"]),
        expected_public_key_sha256=str(owner["public_key_sha256"]),
        expected_owner_key_fingerprint=str(owner["fingerprint"]),
        ssh_keygen=str(owner["ssh_keygen"]),
    )
    assert evidence["public_key_fingerprint"] == owner["fingerprint"]


def test_owner_approval_builder_writes_once_and_reproduces_exact_statement(tmp_path, capsys):
    builder = _load_owner_approval_builder()
    candidate = _candidate()
    candidate_path = tmp_path / "candidate.json"
    candidate_sha256 = _write_candidate(candidate_path, candidate)
    owner = _owner_material(tmp_path, candidate, candidate_sha256)
    output = tmp_path / "rebuilt-owner-approval.json"
    argv = [
        "--candidate",
        str(candidate_path),
        "--candidate-sha256",
        candidate_sha256,
        "--expected-git-commit",
        COMMIT,
        "--expected-build-repository",
        "example/alive",
        "--expected-build-workflow-ref",
        "example/alive/.github/workflows/build-compose-probe-a-verifier.yml@refs/heads/main",
        "--owner-public-key",
        str(owner["public_key"]),
        "--approved-at-utc",
        "2026-07-20T00:00:00Z",
        "--approval-id",
        "probe-a-verifier-2026-07-20",
        "--out",
        str(output),
    ]
    assert builder.main(argv) == 0
    assert output.read_bytes() == Path(str(owner["approval"])).read_bytes()
    assert capsys.readouterr().out.strip() == hashlib.sha256(output.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        builder.main(argv)


def test_owner_approval_rejects_candidate_substitution_even_when_json_is_canonical(tmp_path):
    candidate = _candidate()
    candidate_path = tmp_path / "candidate.json"
    candidate_sha256 = _write_candidate(candidate_path, candidate)
    owner = _owner_material(tmp_path, candidate, candidate_sha256)
    substituted = dict(candidate)
    substituted["image_manifest_digest"] = "sha256:" + "9" * 64
    with pytest.raises(VerifierImageLockError, match="image_manifest_digest mismatch"):
        load_verifier_owner_approval(
            owner["approval"],
            expected_sha256=str(owner["approval_sha256"]),
            expected_candidate=substituted,
            expected_candidate_sha256=candidate_sha256,
            expected_owner_key_fingerprint=str(owner["fingerprint"]),
        )


def test_owner_approval_rejects_wrong_signature(tmp_path):
    candidate = _candidate()
    candidate_path = tmp_path / "candidate.json"
    candidate_sha256 = _write_candidate(candidate_path, candidate)
    owner = _owner_material(tmp_path, candidate, candidate_sha256)
    signature_path = Path(str(owner["signature"]))
    signature_path.write_bytes(signature_path.read_bytes().replace(b"A", b"B", 1))
    tampered_sha256 = hashlib.sha256(signature_path.read_bytes()).hexdigest()
    with pytest.raises(VerifierImageLockError, match="signature verification failed"):
        verify_verifier_owner_approval_signature(
            statement=owner["approval"],
            signature=signature_path,
            public_key=owner["public_key"],
            expected_statement_sha256=str(owner["approval_sha256"]),
            expected_signature_sha256=tampered_sha256,
            expected_public_key_sha256=str(owner["public_key_sha256"]),
            expected_owner_key_fingerprint=str(owner["fingerprint"]),
            ssh_keygen=str(owner["ssh_keygen"]),
        )


def test_owner_approval_rejects_another_valid_ed25519_key(tmp_path):
    candidate = _candidate()
    candidate_path = tmp_path / "candidate.json"
    candidate_sha256 = _write_candidate(candidate_path, candidate)
    owner = _owner_material(tmp_path, candidate, candidate_sha256)
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = _owner_material(other_root, candidate, candidate_sha256)
    with pytest.raises(VerifierImageLockError, match="signature verification failed"):
        verify_verifier_owner_approval_signature(
            statement=owner["approval"],
            signature=owner["signature"],
            public_key=other["public_key"],
            expected_statement_sha256=str(owner["approval_sha256"]),
            expected_signature_sha256=str(owner["signature_sha256"]),
            expected_public_key_sha256=str(other["public_key_sha256"]),
            expected_owner_key_fingerprint=str(other["fingerprint"]),
            ssh_keygen=str(owner["ssh_keygen"]),
        )


def test_owner_approval_rejects_signature_from_wrong_namespace(tmp_path):
    candidate = _candidate()
    candidate_path = tmp_path / "candidate.json"
    candidate_sha256 = _write_candidate(candidate_path, candidate)
    owner = _owner_material(tmp_path, candidate, candidate_sha256)
    wrong_statement = tmp_path / "wrong-namespace-approval.json"
    wrong_statement.write_bytes(Path(str(owner["approval"])).read_bytes())
    subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(owner["private_key"]),
            "-n",
            "wrong-alive-namespace",
            str(wrong_statement),
        ],
        check=True,
        capture_output=True,
    )
    wrong_signature = Path(str(wrong_statement) + ".sig")
    with pytest.raises(VerifierImageLockError, match="signature verification failed"):
        verify_verifier_owner_approval_signature(
            statement=wrong_statement,
            signature=wrong_signature,
            public_key=owner["public_key"],
            expected_statement_sha256=hashlib.sha256(wrong_statement.read_bytes()).hexdigest(),
            expected_signature_sha256=hashlib.sha256(wrong_signature.read_bytes()).hexdigest(),
            expected_public_key_sha256=str(owner["public_key_sha256"]),
            expected_owner_key_fingerprint=str(owner["fingerprint"]),
            ssh_keygen=str(owner["ssh_keygen"]),
        )


def test_owner_approval_public_key_must_be_comment_free_ed25519(tmp_path):
    key = tmp_path / "owner.pub"
    key.write_text("ssh-rsa invalid comment\n", encoding="ascii")
    with pytest.raises(VerifierImageLockError, match="comment-free canonical ssh-ed25519"):
        owner_public_key_identity(key)


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
        "--owner-approval-sha256",
        "d" * 64,
        "--owner-signature-sha256",
        "e" * 64,
        "--owner-key-fingerprint",
        OWNER_FINGERPRINT,
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


def test_build_candidate_handoff_is_canonical_externally_pinned_and_unsigned(tmp_path):
    candidate = _candidate()
    assert candidate["schema"] == VERIFIER_IMAGE_BUILD_CANDIDATE_SCHEMA
    assert "signature" not in candidate
    path = tmp_path / "candidate.json"
    data = (canonical_json(candidate) + "\n").encode()
    path.write_bytes(data)
    loaded = load_verifier_image_candidate(
        path,
        expected_sha256=hashlib.sha256(data).hexdigest(),
        expected_git_commit=COMMIT,
        expected_build_repository="example/alive",
        expected_build_workflow_ref=(
            "example/alive/.github/workflows/build-compose-probe-a-verifier.yml@refs/heads/main"
        ),
    )
    assert loaded == candidate


def test_non_regular_candidate_is_rejected(tmp_path):
    with pytest.raises(VerifierImageLockError, match="must be a regular file"):
        load_verifier_image_candidate(
            tmp_path,
            expected_sha256="0" * 64,
            expected_git_commit=COMMIT,
            expected_build_repository="example/alive",
            expected_build_workflow_ref=(
                "example/alive/.github/workflows/build-compose-probe-a-verifier.yml@refs/heads/main"
            ),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("git_commit", "0" * 40, "Git commit mismatch"),
        ("build_repository", "attacker/alive", "repository mismatch"),
        (
            "build_workflow_ref",
            "example/alive/.github/workflows/other.yml@refs/heads/main",
            "workflow ref mismatch",
        ),
        ("build_run_id", "0", "run ID is malformed"),
    ],
)
def test_build_candidate_rejects_identity_substitution(tmp_path, field, value, message):
    candidate = _candidate()
    candidate[field] = value
    candidate["self_checksum"] = self_checksum(candidate)
    path = tmp_path / "candidate.json"
    data = (canonical_json(candidate) + "\n").encode()
    path.write_bytes(data)
    with pytest.raises(VerifierImageLockError, match=message):
        load_verifier_image_candidate(
            path,
            expected_sha256=hashlib.sha256(data).hexdigest(),
            expected_git_commit=COMMIT,
            expected_build_repository="example/alive",
            expected_build_workflow_ref=(
                "example/alive/.github/workflows/build-compose-probe-a-verifier.yml@refs/heads/main"
            ),
        )


def test_candidate_builder_writes_once_and_prints_external_pin(tmp_path, capsys):
    builder = _load_candidate_builder()
    output = tmp_path / "candidate.json"
    argv = [
        "--git-commit",
        COMMIT,
        "--image-reference",
        f"ghcr.io/example/alive-verifier@{IMAGE_DIGEST}",
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
        "--build-repository",
        "example/alive",
        "--build-workflow-ref",
        "example/alive/.github/workflows/build.yml@refs/heads/main",
        "--build-run-id",
        "123456",
        "--out",
        str(output),
    ]
    assert builder.main(argv) == 0
    assert capsys.readouterr().out.strip() == hashlib.sha256(output.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        builder.main(argv)
