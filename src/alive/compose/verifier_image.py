"""Owner-frozen OCI image contract for the COMPOSE Probe-A verifier.

The image manifest digest is the pre-Python root of trust.  The Python source
closure remains a useful diagnostic and review identity, but cannot authenticate
startup hooks or the standard library that execute before the verifier itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

VERIFIER_IMAGE_LOCK_SCHEMA = "compose_probe_a_verifier_image_lock_v2"
VERIFIER_IMAGE_SIGNATURE_SCHEMA = "compose_probe_a_verifier_image_signature_v1"
VERIFIER_IMAGE_SIGNATURE_SUBJECT_SCHEMA = "compose_probe_a_verifier_signature_subject_v2"
VERIFIER_IMAGE_BUILD_CANDIDATE_SCHEMA = "compose_probe_a_verifier_build_candidate_v1"
VERIFIER_IMAGE_OWNER_APPROVAL_SCHEMA = "compose_probe_a_verifier_owner_approval_v1"
VERIFIER_IMAGE_OWNER_APPROVAL_EVIDENCE_SCHEMA = (
    "compose_probe_a_verifier_owner_approval_evidence_v1"
)
OWNER_APPROVAL_MODE = "openssh_ed25519_detached_v1"
OWNER_APPROVAL_NAMESPACE = "alive-compose-probe-a-verifier-owner-approval-v1"
OWNER_APPROVAL_IDENTITY = "alive-compose-verifier-owner"
PROTOCOL = "COMPOSE-K562-v1"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_DIGEST_REFERENCE = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+@sha256:[0-9a-f]{64}$"
)
_GIT_COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_GITHUB_REPOSITORY = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?/[a-z0-9._-]+$")
_GITHUB_WORKFLOW_REF = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?/[a-z0-9._-]+/"
    r"\.github/workflows/[a-z0-9._-]+\.ya?ml@refs/heads/[a-z0-9._/-]+$"
)
_RUN_ID = re.compile(r"^[1-9][0-9]*$")
_UTC_SECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_APPROVAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OPENSSH_FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")
_OPENSSH_ED25519_KEY = re.compile(r"^ssh-ed25519 ([A-Za-z0-9+/]+={0,2})\n$")
_PLATFORMS = frozenset({"linux/amd64", "linux/arm64"})
_LOCK_KEYS = frozenset(
    {
        "schema",
        "protocol",
        "git_commit",
        "image_reference",
        "image_manifest_digest",
        "platform",
        "python_base_image",
        "uv_build_image",
        "dockerfile_sha256",
        "uv_lock_sha256",
        "verifier_code_sha256",
        "owner_approval",
        "signature",
        "approved_at_utc",
        "approval_id",
        "self_checksum",
    }
)
_OWNER_APPROVAL_EVIDENCE_KEYS = frozenset(
    {
        "schema",
        "mode",
        "namespace",
        "candidate_sha256",
        "statement_sha256",
        "signature_sha256",
        "public_key_sha256",
        "public_key_fingerprint",
        "ssh_keygen_executable_sha256",
        "build_run_id",
    }
)
_SIGNATURE_KEYS = frozenset(
    {
        "schema",
        "mode",
        "subject_sha256",
        "bundle_sha256",
        "cosign_executable_sha256",
        "trusted_root_sha256",
        "certificate_identity",
        "oidc_issuer",
    }
)
_SIGNATURE_SUBJECT_KEYS = frozenset(
    {
        "schema",
        "protocol",
        "git_commit",
        "image_reference",
        "image_manifest_digest",
        "platform",
        "python_base_image",
        "uv_build_image",
        "dockerfile_sha256",
        "uv_lock_sha256",
        "verifier_code_sha256",
        "owner_approval_sha256",
        "owner_signature_sha256",
        "owner_key_fingerprint",
    }
)
_BUILD_CANDIDATE_KEYS = frozenset(
    {
        "schema",
        "git_commit",
        "image_reference",
        "image_manifest_digest",
        "platform",
        "python_base_image",
        "uv_build_image",
        "dockerfile_sha256",
        "uv_lock_sha256",
        "verifier_code_sha256",
        "build_repository",
        "build_workflow_ref",
        "build_run_id",
        "self_checksum",
    }
)
_OWNER_APPROVAL_KEYS = frozenset(
    {
        "schema",
        "protocol",
        "git_commit",
        "candidate_sha256",
        "build_repository",
        "build_workflow_ref",
        "build_run_id",
        "image_reference",
        "image_manifest_digest",
        "platform",
        "python_base_image",
        "uv_build_image",
        "dockerfile_sha256",
        "uv_lock_sha256",
        "verifier_code_sha256",
        "approved_at_utc",
        "approval_id",
        "owner_key_fingerprint",
    }
)


class VerifierImageLockError(ValueError):
    """Raised when an owner-frozen verifier image lock is invalid."""


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Return the one admitted JSON serialization."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def self_checksum(payload: Mapping[str, Any]) -> str:
    """Hash an object excluding its top-level checksum."""
    body = {key: value for key, value in payload.items() if key != "self_checksum"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def build_verifier_signature_subject(
    *,
    git_commit: str,
    image_reference: str,
    platform: str,
    python_base_image: str,
    uv_build_image: str,
    dockerfile_sha256: str,
    uv_lock_sha256: str,
    verifier_code_sha256: str,
    owner_approval_sha256: str,
    owner_signature_sha256: str,
    owner_key_fingerprint: str,
) -> dict[str, str]:
    """Build the canonical blob signed before owner lock construction."""
    reference, image_digest = _digest_reference(
        image_reference, field="verifier image signature subject reference"
    )
    if _GIT_COMMIT.fullmatch(git_commit) is None:
        raise VerifierImageLockError("signature subject Git commit is malformed")
    if platform not in _PLATFORMS:
        raise VerifierImageLockError("signature subject platform is not admitted")
    _digest_reference(python_base_image, field="signature subject Python base image")
    _digest_reference(uv_build_image, field="signature subject uv build image")
    return {
        "schema": VERIFIER_IMAGE_SIGNATURE_SUBJECT_SCHEMA,
        "protocol": PROTOCOL,
        "git_commit": git_commit,
        "image_reference": reference,
        "image_manifest_digest": image_digest,
        "platform": platform,
        "python_base_image": python_base_image,
        "uv_build_image": uv_build_image,
        "dockerfile_sha256": _hex64(dockerfile_sha256, field="signature subject Dockerfile"),
        "uv_lock_sha256": _hex64(uv_lock_sha256, field="signature subject uv.lock"),
        "verifier_code_sha256": _hex64(
            verifier_code_sha256, field="signature subject verifier code"
        ),
        "owner_approval_sha256": _hex64(
            owner_approval_sha256, field="signature subject owner approval"
        ),
        "owner_signature_sha256": _hex64(
            owner_signature_sha256, field="signature subject owner signature"
        ),
        "owner_key_fingerprint": _owner_fingerprint(owner_key_fingerprint),
    }


def build_verifier_image_candidate(
    *,
    git_commit: str,
    image_reference: str,
    platform: str,
    python_base_image: str,
    uv_build_image: str,
    dockerfile_sha256: str,
    uv_lock_sha256: str,
    verifier_code_sha256: str,
    build_repository: str,
    build_workflow_ref: str,
    build_run_id: str,
) -> dict[str, str]:
    """Build one unsigned candidate receipt for separate owner signing review."""
    reference, image_digest = _digest_reference(
        image_reference, field="verifier build candidate image reference"
    )
    candidate = {
        "schema": VERIFIER_IMAGE_BUILD_CANDIDATE_SCHEMA,
        "git_commit": git_commit,
        "image_reference": reference,
        "image_manifest_digest": image_digest,
        "platform": platform,
        "python_base_image": python_base_image,
        "uv_build_image": uv_build_image,
        "dockerfile_sha256": dockerfile_sha256,
        "uv_lock_sha256": uv_lock_sha256,
        "verifier_code_sha256": verifier_code_sha256,
        "build_repository": build_repository,
        "build_workflow_ref": build_workflow_ref,
        "build_run_id": build_run_id,
        "self_checksum": "",
    }
    candidate["self_checksum"] = self_checksum(candidate)
    return validate_verifier_image_candidate(
        candidate,
        expected_git_commit=git_commit,
        expected_build_repository=build_repository,
        expected_build_workflow_ref=build_workflow_ref,
    )


def verifier_signature_subject_from_lock(payload: Mapping[str, Any]) -> dict[str, str]:
    """Derive the exact signed blob from one validated lock-shaped mapping."""
    return build_verifier_signature_subject(
        git_commit=payload["git_commit"],
        image_reference=payload["image_reference"],
        platform=payload["platform"],
        python_base_image=payload["python_base_image"],
        uv_build_image=payload["uv_build_image"],
        dockerfile_sha256=payload["dockerfile_sha256"],
        uv_lock_sha256=payload["uv_lock_sha256"],
        verifier_code_sha256=payload["verifier_code_sha256"],
        owner_approval_sha256=payload["owner_approval"]["statement_sha256"],
        owner_signature_sha256=payload["owner_approval"]["signature_sha256"],
        owner_key_fingerprint=payload["owner_approval"]["public_key_fingerprint"],
    )


def validate_verifier_signature_subject(
    payload: Mapping[str, Any], *, expected_lock: Mapping[str, Any]
) -> dict[str, str]:
    """Require a signed subject to equal the identity derived from its owner lock."""
    obj = _exact_keys(dict(payload), _SIGNATURE_SUBJECT_KEYS, field="verifier signature subject")
    expected = verifier_signature_subject_from_lock(expected_lock)
    if obj != expected:
        raise VerifierImageLockError("verifier signature subject differs from the owner image lock")
    return obj


def validate_verifier_image_candidate(
    payload: Mapping[str, Any],
    *,
    expected_git_commit: str,
    expected_build_repository: str,
    expected_build_workflow_ref: str,
) -> dict[str, str]:
    """Validate an unsigned, externally pinned build-to-sign handoff receipt."""
    obj = _exact_keys(dict(payload), _BUILD_CANDIDATE_KEYS, field="verifier image build candidate")
    if obj["schema"] != VERIFIER_IMAGE_BUILD_CANDIDATE_SCHEMA:
        raise VerifierImageLockError("verifier image build candidate schema mismatch")
    if self_checksum(obj) != obj["self_checksum"]:
        raise VerifierImageLockError("verifier image build candidate checksum mismatch")
    if (
        _GIT_COMMIT.fullmatch(expected_git_commit) is None
        or obj["git_commit"] != expected_git_commit
    ):
        raise VerifierImageLockError("verifier image build candidate Git commit mismatch")
    _, reference_digest = _digest_reference(
        obj["image_reference"], field="verifier image build candidate reference"
    )
    if (
        _digest(obj["image_manifest_digest"], field="verifier build candidate digest")
        != reference_digest
    ):
        raise VerifierImageLockError("verifier image build candidate digest mismatch")
    if obj["platform"] not in _PLATFORMS:
        raise VerifierImageLockError("verifier image build candidate platform is not admitted")
    _digest_reference(obj["python_base_image"], field="candidate Python base image")
    _digest_reference(obj["uv_build_image"], field="candidate uv build image")
    for key, label in (
        ("dockerfile_sha256", "candidate Dockerfile"),
        ("uv_lock_sha256", "candidate uv.lock"),
        ("verifier_code_sha256", "candidate verifier code"),
        ("self_checksum", "candidate self checksum"),
    ):
        _hex64(obj[key], field=label)
    if (
        _GITHUB_REPOSITORY.fullmatch(obj["build_repository"]) is None
        or obj["build_repository"] != expected_build_repository
    ):
        raise VerifierImageLockError("verifier image build candidate repository mismatch")
    if (
        _GITHUB_WORKFLOW_REF.fullmatch(obj["build_workflow_ref"]) is None
        or obj["build_workflow_ref"] != expected_build_workflow_ref
    ):
        raise VerifierImageLockError("verifier image build candidate workflow ref mismatch")
    if not isinstance(obj["build_run_id"], str) or _RUN_ID.fullmatch(obj["build_run_id"]) is None:
        raise VerifierImageLockError("verifier image build candidate run ID is malformed")
    return {key: str(value) for key, value in obj.items()}


def owner_public_key_identity(path: str | Path) -> dict[str, str]:
    """Validate one canonical Ed25519 public key and return its durable identity."""
    data = _read_regular_file(path, field="owner approval public key")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise VerifierImageLockError("owner approval public key must be ASCII") from exc
    match = _OPENSSH_ED25519_KEY.fullmatch(text)
    if match is None:
        raise VerifierImageLockError(
            "owner approval public key must be one comment-free canonical ssh-ed25519 line"
        )
    try:
        blob = b64decode(match.group(1), validate=True)
    except Base64Error as exc:
        raise VerifierImageLockError("owner approval public key base64 is malformed") from exc

    offset = 0

    def field() -> bytes:
        nonlocal offset
        if len(blob) - offset < 4:
            raise VerifierImageLockError("owner approval public key wire blob is truncated")
        length = int.from_bytes(blob[offset : offset + 4], "big")
        offset += 4
        value = blob[offset : offset + length]
        if len(value) != length:
            raise VerifierImageLockError("owner approval public key wire blob is truncated")
        offset += length
        return value

    if field() != b"ssh-ed25519" or len(field()) != 32 or offset != len(blob):
        raise VerifierImageLockError("owner approval public key is not canonical Ed25519")
    fingerprint = "SHA256:" + b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")
    return {
        "public_key_sha256": hashlib.sha256(data).hexdigest(),
        "public_key_fingerprint": fingerprint,
        "public_key": text.rstrip("\n"),
    }


def build_verifier_owner_approval(
    *,
    candidate: Mapping[str, Any],
    candidate_sha256: str,
    approved_at_utc: str,
    approval_id: str,
    owner_key_fingerprint: str,
) -> dict[str, str]:
    """Build the exact offline owner statement authorizing one build candidate."""
    candidate = validate_verifier_image_candidate(
        candidate,
        expected_git_commit=str(candidate.get("git_commit", "")),
        expected_build_repository=str(candidate.get("build_repository", "")),
        expected_build_workflow_ref=str(candidate.get("build_workflow_ref", "")),
    )
    approval = {
        "schema": VERIFIER_IMAGE_OWNER_APPROVAL_SCHEMA,
        "protocol": PROTOCOL,
        "git_commit": candidate["git_commit"],
        "candidate_sha256": candidate_sha256,
        "build_repository": candidate["build_repository"],
        "build_workflow_ref": candidate["build_workflow_ref"],
        "build_run_id": candidate["build_run_id"],
        "image_reference": candidate["image_reference"],
        "image_manifest_digest": candidate["image_manifest_digest"],
        "platform": candidate["platform"],
        "python_base_image": candidate["python_base_image"],
        "uv_build_image": candidate["uv_build_image"],
        "dockerfile_sha256": candidate["dockerfile_sha256"],
        "uv_lock_sha256": candidate["uv_lock_sha256"],
        "verifier_code_sha256": candidate["verifier_code_sha256"],
        "approved_at_utc": approved_at_utc,
        "approval_id": approval_id,
        "owner_key_fingerprint": owner_key_fingerprint,
    }
    return validate_verifier_owner_approval(
        approval,
        expected_candidate=candidate,
        expected_candidate_sha256=candidate_sha256,
        expected_owner_key_fingerprint=owner_key_fingerprint,
    )


def validate_verifier_owner_approval(
    payload: Mapping[str, Any],
    *,
    expected_candidate: Mapping[str, Any],
    expected_candidate_sha256: str,
    expected_owner_key_fingerprint: str,
) -> dict[str, str]:
    """Validate an owner statement against the exact independently pinned candidate."""
    obj = _exact_keys(dict(payload), _OWNER_APPROVAL_KEYS, field="verifier owner approval")
    if obj["schema"] != VERIFIER_IMAGE_OWNER_APPROVAL_SCHEMA or obj["protocol"] != PROTOCOL:
        raise VerifierImageLockError("verifier owner approval identity mismatch")
    expected_candidate_sha256 = _hex64(
        expected_candidate_sha256, field="expected verifier candidate SHA-256"
    )
    if obj["candidate_sha256"] != expected_candidate_sha256:
        raise VerifierImageLockError("verifier owner approval candidate SHA-256 mismatch")
    expected_owner_key_fingerprint = _owner_fingerprint(expected_owner_key_fingerprint)
    if obj["owner_key_fingerprint"] != expected_owner_key_fingerprint:
        raise VerifierImageLockError("verifier owner approval public key fingerprint mismatch")
    expected_fields = {
        key: expected_candidate[key]
        for key in (
            "git_commit",
            "build_repository",
            "build_workflow_ref",
            "build_run_id",
            "image_reference",
            "image_manifest_digest",
            "platform",
            "python_base_image",
            "uv_build_image",
            "dockerfile_sha256",
            "uv_lock_sha256",
            "verifier_code_sha256",
        )
    }
    for key, expected in expected_fields.items():
        if obj[key] != expected:
            raise VerifierImageLockError(f"verifier owner approval {key} mismatch")
    _canonical_utc(obj["approved_at_utc"], field="verifier owner approval time")
    _approval_id(obj["approval_id"], field="verifier owner approval ID")
    return {key: str(value) for key, value in obj.items()}


def load_verifier_owner_approval(
    path: str | Path,
    *,
    expected_sha256: str,
    expected_candidate: Mapping[str, Any],
    expected_candidate_sha256: str,
    expected_owner_key_fingerprint: str,
) -> dict[str, str]:
    """Load canonical owner-approval bytes from a regular file and external pin."""
    data = _read_regular_file(path, field="verifier owner approval statement")
    if hashlib.sha256(data).hexdigest() != _hex64(
        expected_sha256, field="expected owner approval statement SHA-256"
    ):
        raise VerifierImageLockError("verifier owner approval differs from its external pin")
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifierImageLockError(f"cannot parse verifier owner approval: {exc}") from exc
    if not isinstance(payload, dict) or data != (canonical_json(payload) + "\n").encode("utf-8"):
        raise VerifierImageLockError("verifier owner approval must be canonical JSON with final LF")
    return validate_verifier_owner_approval(
        payload,
        expected_candidate=expected_candidate,
        expected_candidate_sha256=expected_candidate_sha256,
        expected_owner_key_fingerprint=expected_owner_key_fingerprint,
    )


def validate_verifier_owner_approval_against_lock(
    payload: Mapping[str, Any], *, expected_lock: Mapping[str, Any]
) -> dict[str, str]:
    """Require durable owner-approval bytes to authorize the exact image lock."""
    obj = _exact_keys(dict(payload), _OWNER_APPROVAL_KEYS, field="verifier owner approval")
    if obj["schema"] != VERIFIER_IMAGE_OWNER_APPROVAL_SCHEMA or obj["protocol"] != PROTOCOL:
        raise VerifierImageLockError("verifier owner approval identity mismatch")
    evidence = expected_lock["owner_approval"]
    if obj["candidate_sha256"] != evidence["candidate_sha256"]:
        raise VerifierImageLockError("verifier owner approval candidate SHA-256 mismatch")
    if obj["build_run_id"] != evidence["build_run_id"]:
        raise VerifierImageLockError("verifier owner approval build run ID mismatch")
    if obj["owner_key_fingerprint"] != evidence["public_key_fingerprint"]:
        raise VerifierImageLockError("verifier owner approval public key fingerprint mismatch")
    for key in (
        "git_commit",
        "image_reference",
        "image_manifest_digest",
        "platform",
        "python_base_image",
        "uv_build_image",
        "dockerfile_sha256",
        "uv_lock_sha256",
        "verifier_code_sha256",
        "approved_at_utc",
        "approval_id",
    ):
        if obj[key] != expected_lock[key]:
            raise VerifierImageLockError(f"verifier owner approval {key} differs from image lock")
    if _GITHUB_REPOSITORY.fullmatch(obj["build_repository"]) is None:
        raise VerifierImageLockError("verifier owner approval build repository is malformed")
    if _GITHUB_WORKFLOW_REF.fullmatch(obj["build_workflow_ref"]) is None:
        raise VerifierImageLockError("verifier owner approval build workflow ref is malformed")
    _canonical_utc(obj["approved_at_utc"], field="verifier owner approval time")
    _approval_id(obj["approval_id"], field="verifier owner approval ID")
    return {key: str(value) for key, value in obj.items()}


def verify_verifier_owner_approval_signature(
    *,
    statement: str | Path,
    signature: str | Path,
    public_key: str | Path,
    expected_statement_sha256: str,
    expected_signature_sha256: str,
    expected_public_key_sha256: str,
    expected_owner_key_fingerprint: str,
    ssh_keygen: str = "ssh-keygen",
) -> dict[str, str]:
    """Verify the detached OpenSSH signature under the fixed ALIVE namespace."""
    statement_data = _read_regular_file(statement, field="owner approval statement")
    signature_data = _read_regular_file(signature, field="owner approval signature")
    if hashlib.sha256(statement_data).hexdigest() != _hex64(
        expected_statement_sha256, field="expected owner approval statement SHA-256"
    ):
        raise VerifierImageLockError("owner approval statement hash mismatch")
    if hashlib.sha256(signature_data).hexdigest() != _hex64(
        expected_signature_sha256, field="expected owner approval signature SHA-256"
    ):
        raise VerifierImageLockError("owner approval signature hash mismatch")
    key_identity = owner_public_key_identity(public_key)
    if key_identity["public_key_sha256"] != _hex64(
        expected_public_key_sha256, field="expected owner approval public key SHA-256"
    ):
        raise VerifierImageLockError("owner approval public key hash mismatch")
    if key_identity["public_key_fingerprint"] != _owner_fingerprint(expected_owner_key_fingerprint):
        raise VerifierImageLockError("owner approval public key fingerprint mismatch")
    executable = shutil.which(ssh_keygen) if os.sep not in ssh_keygen else ssh_keygen
    if not executable:
        raise VerifierImageLockError("ssh-keygen is unavailable for owner approval verification")
    executable_path = Path(executable).resolve(strict=True)
    if not executable_path.is_file():
        raise VerifierImageLockError("ssh-keygen must resolve to a regular file")
    with tempfile.TemporaryDirectory(prefix="alive-owner-approval-") as temporary:
        allowed_signers = Path(temporary) / "allowed_signers"
        allowed_signers.write_text(
            f'{OWNER_APPROVAL_IDENTITY} namespaces="{OWNER_APPROVAL_NAMESPACE}" '
            f"{key_identity['public_key']}\n",
            encoding="ascii",
        )
        command = [
            str(executable_path),
            "-Y",
            "verify",
            "-f",
            str(allowed_signers),
            "-I",
            OWNER_APPROVAL_IDENTITY,
            "-n",
            OWNER_APPROVAL_NAMESPACE,
            "-s",
            str(Path(signature).resolve(strict=True)),
        ]
        completed = subprocess.run(command, input=statement_data, capture_output=True)
    if completed.returncode != 0:
        raise VerifierImageLockError("owner approval detached signature verification failed")
    return {
        **key_identity,
        "statement_sha256": hashlib.sha256(statement_data).hexdigest(),
        "signature_sha256": hashlib.sha256(signature_data).hexdigest(),
        "ssh_keygen_executable_sha256": hashlib.sha256(executable_path.read_bytes()).hexdigest(),
    }


def _exact_keys(value: object, expected: frozenset[str], *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise VerifierImageLockError(f"{field} key roster mismatch")
    return value


def _hex64(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise VerifierImageLockError(f"{field} must be one lowercase SHA-256")
    return value


def _digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise VerifierImageLockError(f"{field} must be one sha256:<64 lowercase hex> digest")
    return value


def _digest_reference(value: object, *, field: str) -> tuple[str, str]:
    if not isinstance(value, str) or _DIGEST_REFERENCE.fullmatch(value) is None:
        raise VerifierImageLockError(
            f"{field} must be one fully qualified lowercase digest image reference"
        )
    _, digest = value.rsplit("@", 1)
    return value, _digest(digest, field=f"{field} digest")


def _owner_fingerprint(value: object) -> str:
    if not isinstance(value, str) or _OPENSSH_FINGERPRINT.fullmatch(value) is None:
        raise VerifierImageLockError(
            "owner approval public key fingerprint must be one OpenSSH SHA256 fingerprint"
        )
    return value


def _approval_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _APPROVAL_ID.fullmatch(value) is None:
        raise VerifierImageLockError(f"{field} must be one bounded non-empty token")
    return value


def _canonical_utc(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _UTC_SECONDS.fullmatch(value) is None:
        raise VerifierImageLockError(f"{field} must be canonical UTC seconds")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerifierImageLockError(f"{field} is invalid") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise VerifierImageLockError(f"{field} must be UTC")
    return value


def _read_regular_file(path: str | Path, *, field: str) -> bytes:
    candidate = Path(path)
    if candidate.is_symlink():
        raise VerifierImageLockError(f"{field} must not be a symlink")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise VerifierImageLockError(f"cannot open {field}: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise VerifierImageLockError(f"{field} must be a regular file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            return stream.read()
    except OSError as exc:
        raise VerifierImageLockError(f"cannot read {field}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def validate_verifier_image_lock(
    payload: Mapping[str, Any],
    *,
    expected_git_commit: str,
    expected_verifier_code_sha256: str,
    expected_owner_key_fingerprint: str,
) -> dict[str, Any]:
    """Validate one signed, platform-specific, digest-pinned image lock."""
    obj = _exact_keys(dict(payload), _LOCK_KEYS, field="verifier image lock")
    if obj["schema"] != VERIFIER_IMAGE_LOCK_SCHEMA or obj["protocol"] != PROTOCOL:
        raise VerifierImageLockError("verifier image lock identity mismatch")
    if self_checksum(obj) != obj["self_checksum"]:
        raise VerifierImageLockError("verifier image lock checksum mismatch")
    if not isinstance(obj["git_commit"], str) or _GIT_COMMIT.fullmatch(obj["git_commit"]) is None:
        raise VerifierImageLockError("verifier image lock git_commit is malformed")
    if obj["git_commit"] != expected_git_commit:
        raise VerifierImageLockError("verifier image lock Git commit differs from the owner pin")
    manifest_digest = _digest(obj["image_manifest_digest"], field="verifier image manifest digest")
    image_reference, reference_digest = _digest_reference(
        obj["image_reference"], field="verifier image reference"
    )
    if reference_digest != manifest_digest:
        raise VerifierImageLockError(
            "verifier image reference must end in the exact OCI manifest/index digest"
        )
    _digest_reference(obj["python_base_image"], field="Python base image")
    _digest_reference(obj["uv_build_image"], field="uv build image")
    if obj["platform"] not in _PLATFORMS:
        raise VerifierImageLockError("verifier image platform is not admitted")
    _hex64(obj["dockerfile_sha256"], field="verifier Dockerfile SHA-256")
    _hex64(obj["uv_lock_sha256"], field="verifier uv.lock SHA-256")
    if _hex64(obj["verifier_code_sha256"], field="verifier code SHA-256") != _hex64(
        expected_verifier_code_sha256, field="expected verifier code SHA-256"
    ):
        raise VerifierImageLockError("verifier image lock code closure differs from the owner pin")

    owner_approval = _exact_keys(
        obj["owner_approval"],
        _OWNER_APPROVAL_EVIDENCE_KEYS,
        field="verifier image owner approval evidence",
    )
    if owner_approval["schema"] != VERIFIER_IMAGE_OWNER_APPROVAL_EVIDENCE_SCHEMA:
        raise VerifierImageLockError("verifier image owner approval evidence schema mismatch")
    if owner_approval["mode"] != OWNER_APPROVAL_MODE:
        raise VerifierImageLockError("verifier image owner approval mode mismatch")
    if owner_approval["namespace"] != OWNER_APPROVAL_NAMESPACE:
        raise VerifierImageLockError("verifier image owner approval namespace mismatch")
    for key, label in (
        ("candidate_sha256", "owner-approved candidate"),
        ("statement_sha256", "owner approval statement"),
        ("signature_sha256", "owner approval signature"),
        ("public_key_sha256", "owner approval public key"),
        ("ssh_keygen_executable_sha256", "owner approval ssh-keygen executable"),
    ):
        _hex64(owner_approval[key], field=f"{label} SHA-256")
    if owner_approval["public_key_fingerprint"] != _owner_fingerprint(
        expected_owner_key_fingerprint
    ):
        raise VerifierImageLockError(
            "verifier image owner approval key differs from the external owner registration"
        )
    if (
        not isinstance(owner_approval["build_run_id"], str)
        or _RUN_ID.fullmatch(owner_approval["build_run_id"]) is None
    ):
        raise VerifierImageLockError("verifier image owner approval build run ID is malformed")

    signature = _exact_keys(obj["signature"], _SIGNATURE_KEYS, field="verifier image signature")
    if signature["schema"] != VERIFIER_IMAGE_SIGNATURE_SCHEMA:
        raise VerifierImageLockError("verifier image signature schema mismatch")
    if signature["mode"] != "cosign_keyless_subject_bundle_v1":
        raise VerifierImageLockError("operational verifier images require a signed Cosign subject")
    _hex64(signature["subject_sha256"], field="Cosign signature subject SHA-256")
    _hex64(signature["bundle_sha256"], field="Cosign bundle SHA-256")
    _hex64(signature["cosign_executable_sha256"], field="Cosign executable SHA-256")
    _hex64(signature["trusted_root_sha256"], field="Sigstore trusted-root SHA-256")
    for field in ("certificate_identity", "oidc_issuer"):
        value = signature[field]
        if (
            not isinstance(value, str)
            or not value
            or any(character.isspace() for character in value)
        ):
            raise VerifierImageLockError(f"signature {field} must be a non-empty token")

    _canonical_utc(obj["approved_at_utc"], field="verifier image approval time")
    _approval_id(obj["approval_id"], field="verifier image approval_id")
    return {
        **obj,
        "owner_approval": dict(owner_approval),
        "signature": dict(signature),
    }


def load_verifier_image_lock(
    path: str | Path,
    *,
    expected_sha256: str,
    expected_git_commit: str,
    expected_verifier_code_sha256: str,
    expected_owner_key_fingerprint: str,
) -> dict[str, Any]:
    """Load canonical lock bytes from one non-symlink regular file."""
    lock_path = Path(path)
    if lock_path.is_symlink():
        raise VerifierImageLockError("verifier image lock must not be a symlink")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(lock_path, flags)
    except OSError as exc:
        raise VerifierImageLockError(f"cannot open verifier image lock: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise VerifierImageLockError("verifier image lock must be a regular file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            data = stream.read()
    except OSError as exc:
        raise VerifierImageLockError(f"cannot read verifier image lock: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    expected = _hex64(expected_sha256, field="expected verifier image lock SHA-256")
    if hashlib.sha256(data).hexdigest() != expected:
        raise VerifierImageLockError("verifier image lock differs from its external pin")
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifierImageLockError(f"cannot parse verifier image lock: {exc}") from exc
    if not isinstance(payload, dict) or data != (canonical_json(payload) + "\n").encode("utf-8"):
        raise VerifierImageLockError("verifier image lock must be canonical JSON with final LF")
    return validate_verifier_image_lock(
        payload,
        expected_git_commit=expected_git_commit,
        expected_verifier_code_sha256=expected_verifier_code_sha256,
        expected_owner_key_fingerprint=expected_owner_key_fingerprint,
    )


def load_verifier_image_candidate(
    path: str | Path,
    *,
    expected_sha256: str,
    expected_git_commit: str,
    expected_build_repository: str,
    expected_build_workflow_ref: str,
) -> dict[str, str]:
    """Load a canonical build candidate from a regular file and external pin."""
    candidate_path = Path(path)
    if candidate_path.is_symlink():
        raise VerifierImageLockError("verifier image build candidate must not be a symlink")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(candidate_path, flags)
    except OSError as exc:
        raise VerifierImageLockError(f"cannot open verifier image build candidate: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise VerifierImageLockError("verifier image build candidate must be a regular file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            data = stream.read()
    except OSError as exc:
        raise VerifierImageLockError(f"cannot read verifier image build candidate: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    expected = _hex64(expected_sha256, field="expected verifier image candidate SHA-256")
    if hashlib.sha256(data).hexdigest() != expected:
        raise VerifierImageLockError("verifier image build candidate differs from its external pin")
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifierImageLockError(f"cannot parse verifier image build candidate: {exc}") from exc
    if not isinstance(payload, dict) or data != (canonical_json(payload) + "\n").encode("utf-8"):
        raise VerifierImageLockError(
            "verifier image build candidate must be canonical JSON with final LF"
        )
    return validate_verifier_image_candidate(
        payload,
        expected_git_commit=expected_git_commit,
        expected_build_repository=expected_build_repository,
        expected_build_workflow_ref=expected_build_workflow_ref,
    )
