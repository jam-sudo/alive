from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
BUILD_WORKFLOW = ROOT / ".github/workflows/build-compose-probe-a-verifier.yml"
SIGN_WORKFLOW = ROOT / ".github/workflows/sign-compose-probe-a-verifier.yml"
DOCKERFILE = ROOT / "containers/compose-probe-a-verifier/Dockerfile"
FULL_SHA_USE = re.compile(r"^[a-z0-9-]+/[a-z0-9-]+@[0-9a-f]{40}$")


def _workflow(path: Path) -> dict:
    loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict)
    return loaded


def _steps(path: Path, job: str) -> list[dict]:
    workflow = _workflow(path)
    steps = workflow["jobs"][job]["steps"]
    assert isinstance(steps, list)
    return steps


def test_all_third_party_actions_are_immutable_commit_pins():
    for path, job in ((BUILD_WORKFLOW, "build"), (SIGN_WORKFLOW, "sign")):
        for step in _steps(path, job):
            if "uses" in step:
                assert FULL_SHA_USE.fullmatch(step["uses"]), (path, step["uses"])


def test_build_and_sign_are_distinct_manual_workflows():
    build = _workflow(BUILD_WORKFLOW)
    sign = _workflow(SIGN_WORKFLOW)
    assert set(build["on"]) == {"workflow_dispatch"}
    assert set(sign["on"]) == {"workflow_dispatch"}
    build_text = BUILD_WORKFLOW.read_text(encoding="utf-8")
    assert "id-token: write" not in build_text
    assert "cosign sign" not in build_text
    sign_text = SIGN_WORKFLOW.read_text(encoding="utf-8")
    assert "environment: compose-verifier-signing" in sign_text
    assert '--candidate-sha256 "$CANDIDATE_SHA256"' in sign_text
    assert "--offline" in sign_text
    assert "owner image lock and external lock pin are still absent" in sign_text


def test_build_is_single_platform_digest_handoff_without_attached_provenance():
    text = BUILD_WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "TARGET_PLATFORM: linux/amd64",
        "no-cache: true",
        "provenance: false",
        "sbom: false",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--user 65532:65532",
        "{{.Os}}/{{.Architecture}}",
    ):
        assert required in text


def test_signing_recomputes_source_labels_and_runtime_closure():
    text = SIGN_WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "sha256sum containers/compose-probe-a-verifier/Dockerfile",
        "sha256sum uv.lock",
        "org.opencontainers.image.base.name",
        "dev.alive.uv-build-image",
        "dev.alive.dockerfile-sha256",
        "dev.alive.uv-lock-sha256",
        "--print-verifier-code-sha256",
        "cosign sign-blob --yes",
        '--certificate-identity "$CERTIFICATE_IDENTITY"',
        '--certificate-oidc-issuer "$OIDC_ISSUER"',
    ):
        assert required in text


def test_both_base_arguments_are_global_before_the_first_from():
    instructions = [
        line.strip()
        for line in DOCKERFILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    first_from = next(index for index, line in enumerate(instructions) if line.startswith("FROM "))
    assert set(instructions[:first_from]) == {"ARG UV_IMAGE", "ARG PYTHON_BASE_IMAGE"}
    assert instructions[first_from] == "FROM ${UV_IMAGE} AS uv_binary"
    assert instructions[first_from + 1] == "FROM ${PYTHON_BASE_IMAGE}"
