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
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

VERIFIER_IMAGE_LOCK_SCHEMA = "compose_probe_a_verifier_image_lock_v1"
VERIFIER_IMAGE_SIGNATURE_SCHEMA = "compose_probe_a_verifier_image_signature_v1"
VERIFIER_IMAGE_SIGNATURE_SUBJECT_SCHEMA = "compose_probe_a_verifier_signature_subject_v1"
VERIFIER_IMAGE_BUILD_CANDIDATE_SCHEMA = "compose_probe_a_verifier_build_candidate_v1"
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
        "signature",
        "approved_at_utc",
        "approval_id",
        "self_checksum",
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


def validate_verifier_image_lock(
    payload: Mapping[str, Any],
    *,
    expected_git_commit: str,
    expected_verifier_code_sha256: str,
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

    timestamp = obj["approved_at_utc"]
    if not isinstance(timestamp, str) or _UTC_SECONDS.fullmatch(timestamp) is None:
        raise VerifierImageLockError("verifier image approval time must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerifierImageLockError("verifier image approval time is invalid") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise VerifierImageLockError("verifier image approval time must be UTC")
    approval_id = obj["approval_id"]
    if (
        not isinstance(approval_id, str)
        or not approval_id
        or any(character.isspace() for character in approval_id)
    ):
        raise VerifierImageLockError("verifier image approval_id must be one non-empty token")
    return {**obj, "signature": dict(signature)}


def load_verifier_image_lock(
    path: str | Path,
    *,
    expected_sha256: str,
    expected_git_commit: str,
    expected_verifier_code_sha256: str,
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
