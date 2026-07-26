"""Canonical, durable receipts for the COMPOSE Linux isolation CI gate.

GitHub Actions artifacts are transport, not permanent scientific provenance.
This module turns the exact JUnit result plus immutable workflow/run identity
into a small canonical receipt that can be reviewed and committed under
``docs/activation-evidence/compose`` before operational approval.
"""

from __future__ import annotations

import io
import json
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from alive.io import atomic_write_once
from alive.provenance import sha256_bytes, sha256_file, sha256_json

CI_RECEIPT_SCHEMA = "compose_kernel_isolation_ci_receipt_v1"
CI_ARCHIVE_SCHEMA = "compose_kernel_isolation_ci_archive_v1"
CI_PROOF_PROFILE_V1 = "x86_64_seccomp_primitives_v1"
CI_PROOF_PROFILE_V2 = "x86_64_seccomp_primitives_and_launcher_wiring_v2"
CI_WORKFLOW_PATH = ".github/workflows/test-suite.yml"
CI_TEST_CLASSNAME = "tests.alive.compose.test_network_isolation"
CI_PRIMITIVE_TEST = "test_linux_policy_and_sealed_receipt_validate_in_the_active_process"
CI_E2E_TEST = "test_linux_launcher_executes_driver_self_check_end_to_end"
CI_JUNIT_ARTIFACT_NAME = "junit.xml"
CI_RECEIPT_ARTIFACT_NAME = "kernel-isolation-ci-receipt.json"

_PROFILE_TESTS = {
    CI_PROOF_PROFILE_V1: (CI_PRIMITIVE_TEST,),
    CI_PROOF_PROFILE_V2: (CI_PRIMITIVE_TEST, CI_E2E_TEST),
}
_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "proof_profile",
        "repository",
        "workflow_path",
        "workflow_sha256",
        "head_sha",
        "run_id",
        "run_attempt",
        "source_run_url",
        "runner",
        "junit",
        "required_test_cases",
        "status",
        "self_checksum",
    }
)
_RUNNER_KEYS = frozenset({"os", "architecture", "kernel_release"})
_JUNIT_KEYS = frozenset(
    {
        "sha256",
        "tests",
        "passed",
        "failures",
        "errors",
        "skipped",
        "timestamp",
    }
)
_TEST_CASE_KEYS = frozenset({"classname", "name", "time_seconds", "status"})
_TERMINAL_CASE_TAGS = frozenset({"skipped", "failure", "error"})
_TEXT_ONLY_CASE_TAGS = frozenset({"system-out", "system-err"})
_ARCHIVE_KEYS = frozenset(
    {
        "schema",
        "archived_at_utc",
        "archived_by",
        "receipt",
        "receipt_sha256",
        "source_artifact",
        "self_checksum",
    }
)
_SOURCE_ARTIFACT_KEYS = frozenset(
    {
        "artifact_id",
        "artifact_name",
        "archive_sha256",
        "junit_sha256",
        "expires_at_utc",
    }
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")
_MAX_ARTIFACT_MEMBER_BYTES = 64 << 20
_MAX_ARTIFACT_ARCHIVE_BYTES = 128 << 20


class KernelIsolationCIError(ValueError):
    """The CI receipt or its source JUnit does not prove the registered gate."""


def _exact_mapping(value: object, keys: frozenset[str], label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise KernelIsolationCIError(f"{label} has an invalid field roster")
    return dict(value)


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise KernelIsolationCIError(f"{label} must be a lowercase SHA-256")
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise KernelIsolationCIError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise KernelIsolationCIError(f"{label} must be a non-negative integer")
    return value


def _required_tests(profile: object) -> tuple[str, ...]:
    if not isinstance(profile, str) or profile not in _PROFILE_TESTS:
        raise KernelIsolationCIError("kernel-isolation CI proof profile is unsupported")
    return _PROFILE_TESTS[profile]


def _duration(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise KernelIsolationCIError(f"{label} duration is malformed")
    try:
        parsed = float(value)
    except ValueError as exc:
        raise KernelIsolationCIError(f"{label} duration is malformed") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise KernelIsolationCIError(f"{label} duration is malformed")
    return value


def _aware_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise KernelIsolationCIError(f"{label} timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KernelIsolationCIError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise KernelIsolationCIError(f"{label} timestamp must include a timezone")
    return parsed


def _reject_nested_elements(element: ET.Element, label: str) -> None:
    if len(element):
        raise KernelIsolationCIError(f"JUnit {label} must not contain nested elements")


def _case_outcomes(case: ET.Element) -> list[str]:
    """Return a testcase's terminal outcome tags, failing closed on unknown markup.

    Only the xunit2 vocabulary pytest actually emits is accepted. Scanning for a
    fixed set of *bad* tag names instead would read two forgeries as a pass: a
    rerun plugin's ``rerunFailure`` element, whose tag is simply not in the set,
    and a ``failure`` buried under ``system-err``, which is not a direct child.
    Unrecognised markup is therefore rejected rather than ignored.
    """
    outcomes: list[str] = []
    for child in case:
        if child.tag in _TERMINAL_CASE_TAGS:
            _reject_nested_elements(child, f"{child.tag} element")
            outcomes.append(child.tag)
        elif child.tag in _TEXT_ONLY_CASE_TAGS:
            _reject_nested_elements(child, f"{child.tag} element")
        elif child.tag == "properties":
            for prop in child:
                if prop.tag != "property":
                    raise KernelIsolationCIError(
                        "JUnit properties may only contain property elements"
                    )
                _reject_nested_elements(prop, "property element")
        else:
            raise KernelIsolationCIError(
                f"JUnit testcase has an unrecognised child element {child.tag!r}"
            )
    if len(outcomes) > 1:
        raise KernelIsolationCIError("a JUnit testcase has multiple terminal outcomes")
    return outcomes


def _parse_junit(
    path: str | Path,
    *,
    required_tests: Sequence[str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    junit_path = Path(path)
    try:
        raw = junit_path.read_bytes()
        root = ET.fromstring(raw)
    except (OSError, ET.ParseError) as exc:
        raise KernelIsolationCIError(f"cannot parse kernel-isolation JUnit: {exc}") from exc
    suites = list(root.iter("testsuite"))
    if len(suites) != 1:
        raise KernelIsolationCIError("kernel-isolation JUnit must contain exactly one testsuite")
    suite = suites[0]
    try:
        totals = {
            field: int(suite.attrib[field]) for field in ("tests", "failures", "errors", "skipped")
        }
    except (KeyError, ValueError) as exc:
        raise KernelIsolationCIError(
            "kernel-isolation JUnit totals are missing or malformed"
        ) from exc
    if any(value < 0 for value in totals.values()):
        raise KernelIsolationCIError("kernel-isolation JUnit totals must be non-negative")
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    if passed < 0:
        raise KernelIsolationCIError("kernel-isolation JUnit totals are inconsistent")
    timestamp = suite.attrib.get("timestamp", "")
    _aware_timestamp(timestamp, "kernel-isolation JUnit")

    cases: list[dict[str, object]] = []
    all_cases = list(root.iter("testcase"))
    if len(suite.findall("testcase")) != len(all_cases):
        raise KernelIsolationCIError(
            "every JUnit testcase must be a direct child of the single testsuite"
        )
    observed = {"tests": len(all_cases), "failures": 0, "errors": 0, "skipped": 0}
    for case in all_cases:
        outcomes = _case_outcomes(case)
        if outcomes:
            outcome = outcomes[0]
            observed[f"{outcome}s" if outcome != "skipped" else "skipped"] += 1
    if observed != totals:
        raise KernelIsolationCIError("kernel-isolation JUnit totals differ from testcase outcomes")

    for name in required_tests:
        matches = [
            case
            for case in all_cases
            if case.attrib.get("classname") == CI_TEST_CLASSNAME and case.attrib.get("name") == name
        ]
        if len(matches) != 1:
            raise KernelIsolationCIError(
                f"expected exactly one clean JUnit testcase {CI_TEST_CLASSNAME}.{name}"
            )
        case = matches[0]
        outcomes = _case_outcomes(case)
        if outcomes:
            raise KernelIsolationCIError(f"required kernel-isolation testcase failed: {outcomes}")
        time_seconds = _duration(case.attrib.get("time", ""), "required testcase")
        cases.append(
            {
                "classname": CI_TEST_CLASSNAME,
                "name": name,
                "time_seconds": time_seconds,
                "status": "passed",
            }
        )
    junit = {
        "sha256": sha256_bytes(raw),
        **totals,
        "passed": passed,
        "timestamp": timestamp,
    }
    return junit, cases


def build_kernel_isolation_ci_receipt(
    *,
    junit_path: str | Path,
    workflow_path: str | Path,
    repository: str,
    head_sha: str,
    run_id: int,
    run_attempt: int,
    runner_os: str,
    runner_architecture: str,
    kernel_release: str,
    proof_profile: str = CI_PROOF_PROFILE_V2,
) -> dict[str, object]:
    """Build and validate one canonical receipt from an actual JUnit result."""
    required = _required_tests(proof_profile)
    if not isinstance(repository, str) or _REPOSITORY_RE.fullmatch(repository) is None:
        raise KernelIsolationCIError("repository must be an owner/name identifier")
    if _COMMIT_RE.fullmatch(head_sha) is None:
        raise KernelIsolationCIError("head SHA must be a full lowercase Git commit")
    _positive_int(run_id, "run_id")
    _positive_int(run_attempt, "run_attempt")
    if runner_os != "Linux" or runner_architecture != "x86_64" or not kernel_release:
        raise KernelIsolationCIError("kernel-isolation receipt requires a real Linux x86_64 runner")
    workflow = Path(workflow_path)
    if workflow.as_posix() != CI_WORKFLOW_PATH and not workflow.as_posix().endswith(
        f"/{CI_WORKFLOW_PATH}"
    ):
        raise KernelIsolationCIError("kernel-isolation receipt workflow path is not canonical")
    junit, cases = _parse_junit(junit_path, required_tests=required)
    body = {
        "schema": CI_RECEIPT_SCHEMA,
        "proof_profile": proof_profile,
        "repository": repository,
        "workflow_path": CI_WORKFLOW_PATH,
        "workflow_sha256": sha256_file(workflow),
        "head_sha": head_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "source_run_url": f"https://github.com/{repository}/actions/runs/{run_id}",
        "runner": {
            "os": runner_os,
            "architecture": runner_architecture,
            "kernel_release": kernel_release,
        },
        "junit": junit,
        "required_test_cases": cases,
        "status": "passed",
    }
    receipt = {**body, "self_checksum": sha256_json(body)}
    validate_kernel_isolation_ci_receipt(receipt)
    return receipt


def validate_kernel_isolation_ci_receipt(
    value: object,
    *,
    expected_head_sha: str | None = None,
    expected_workflow_sha256: str | None = None,
) -> dict[str, object]:
    """Validate one canonical CI receipt without trusting its stored verdict."""
    receipt = _exact_mapping(value, _RECEIPT_KEYS, "kernel-isolation CI receipt")
    body = {key: item for key, item in receipt.items() if key != "self_checksum"}
    if receipt["schema"] != CI_RECEIPT_SCHEMA or receipt["self_checksum"] != sha256_json(body):
        raise KernelIsolationCIError("kernel-isolation CI receipt checksum or schema mismatch")
    required = _required_tests(receipt["proof_profile"])
    repository = receipt["repository"]
    head_sha = receipt["head_sha"]
    if not isinstance(repository, str) or _REPOSITORY_RE.fullmatch(repository) is None:
        raise KernelIsolationCIError("kernel-isolation CI repository identity is invalid")
    if not isinstance(head_sha, str) or _COMMIT_RE.fullmatch(head_sha) is None:
        raise KernelIsolationCIError("kernel-isolation CI head SHA is invalid")
    if expected_head_sha is not None and head_sha != expected_head_sha:
        raise KernelIsolationCIError("kernel-isolation CI head SHA differs from its external pin")
    workflow_sha = _sha(receipt["workflow_sha256"], "workflow_sha256")
    if expected_workflow_sha256 is not None and workflow_sha != expected_workflow_sha256:
        raise KernelIsolationCIError(
            "kernel-isolation CI workflow SHA differs from its external pin"
        )
    if receipt["workflow_path"] != CI_WORKFLOW_PATH:
        raise KernelIsolationCIError("kernel-isolation CI workflow path is invalid")
    run_id = _positive_int(receipt["run_id"], "run_id")
    _positive_int(receipt["run_attempt"], "run_attempt")
    if receipt["source_run_url"] != f"https://github.com/{repository}/actions/runs/{run_id}":
        raise KernelIsolationCIError("kernel-isolation CI source URL is inconsistent")

    runner = _exact_mapping(receipt["runner"], _RUNNER_KEYS, "kernel-isolation runner")
    if (
        runner["os"] != "Linux"
        or runner["architecture"] != "x86_64"
        or not isinstance(runner["kernel_release"], str)
        or not runner["kernel_release"]
    ):
        raise KernelIsolationCIError("kernel-isolation CI runner is not Linux x86_64")
    junit = _exact_mapping(receipt["junit"], _JUNIT_KEYS, "kernel-isolation JUnit")
    _sha(junit["sha256"], "JUnit SHA-256")
    totals = {
        field: _nonnegative_int(junit[field], f"JUnit {field}")
        for field in ("tests", "passed", "failures", "errors", "skipped")
    }
    if (
        totals["passed"] + totals["failures"] + totals["errors"] + totals["skipped"]
        != totals["tests"]
    ):
        raise KernelIsolationCIError("kernel-isolation JUnit totals are inconsistent")
    if totals["failures"] or totals["errors"]:
        raise KernelIsolationCIError("kernel-isolation JUnit contains a failure or error")
    _aware_timestamp(junit["timestamp"], "kernel-isolation JUnit")
    cases = receipt["required_test_cases"]
    if not isinstance(cases, list) or len(cases) != len(required):
        raise KernelIsolationCIError("kernel-isolation required-test roster is incomplete")
    for case, expected_name in zip(cases, required, strict=True):
        parsed = _exact_mapping(case, _TEST_CASE_KEYS, "kernel-isolation testcase")
        if (
            parsed["classname"] != CI_TEST_CLASSNAME
            or parsed["name"] != expected_name
            or parsed["status"] != "passed"
        ):
            raise KernelIsolationCIError("kernel-isolation required testcase is invalid")
        _duration(parsed["time_seconds"], "kernel-isolation testcase")
    if receipt["status"] != "passed":
        raise KernelIsolationCIError("kernel-isolation CI receipt is not passing")
    return receipt


def validate_kernel_isolation_ci_archive(value: object) -> dict[str, object]:
    """Validate a version-controlled archive wrapper around one CI receipt."""
    archive = _exact_mapping(value, _ARCHIVE_KEYS, "kernel-isolation CI archive")
    body = {key: item for key, item in archive.items() if key != "self_checksum"}
    if archive["schema"] != CI_ARCHIVE_SCHEMA or archive["self_checksum"] != sha256_json(body):
        raise KernelIsolationCIError("kernel-isolation CI archive checksum or schema mismatch")
    archived_at = archive["archived_at_utc"]
    if not isinstance(archived_at, str) or _UTC_RE.fullmatch(archived_at) is None:
        raise KernelIsolationCIError("kernel-isolation CI archive timestamp is invalid")
    archived_datetime = _aware_timestamp(archived_at, "kernel-isolation CI archive")
    if not isinstance(archive["archived_by"], str) or not archive["archived_by"]:
        raise KernelIsolationCIError("kernel-isolation CI archive reviewer is missing")
    receipt = validate_kernel_isolation_ci_receipt(archive["receipt"])
    if archive["receipt_sha256"] != sha256_json(receipt):
        raise KernelIsolationCIError("kernel-isolation CI archived receipt digest mismatch")
    source = _exact_mapping(
        archive["source_artifact"],
        _SOURCE_ARTIFACT_KEYS,
        "kernel-isolation CI source artifact",
    )
    _positive_int(source["artifact_id"], "source artifact ID")
    _sha(source["archive_sha256"], "source artifact archive SHA-256")
    expires_at = source["expires_at_utc"]
    if (
        not isinstance(source["artifact_name"], str)
        or source["artifact_name"] != f"junit-{receipt['head_sha']}"
        or source["junit_sha256"] != dict(receipt["junit"])["sha256"]
        or not isinstance(expires_at, str)
        or _UTC_RE.fullmatch(expires_at) is None
    ):
        raise KernelIsolationCIError("kernel-isolation CI source artifact binding is invalid")
    expires_datetime = _aware_timestamp(expires_at, "source artifact expiry")
    junit_datetime = _aware_timestamp(
        dict(receipt["junit"])["timestamp"],
        "kernel-isolation JUnit",
    )
    if not junit_datetime <= archived_datetime < expires_datetime:
        raise KernelIsolationCIError(
            "kernel-isolation archive time must follow the run and precede artifact expiry"
        )
    return archive


def build_kernel_isolation_ci_archive(
    *,
    receipt_path: str | Path,
    artifact_archive_path: str | Path,
    artifact_id: int,
    artifact_name: str,
    expires_at_utc: str,
    archived_at_utc: str,
    archived_by: str,
) -> dict[str, object]:
    """Build a durable archive from one actually downloaded GitHub artifact.

    The artifact ZIP is read directly. Its JUnit bytes must match the receipt,
    and v2 artifacts must also contain the exact canonical receipt. This avoids
    constructing a plausible archive record from unrelated files or metadata.
    """
    try:
        receipt_value = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KernelIsolationCIError(f"cannot read kernel-isolation CI receipt: {exc}") from exc
    receipt = validate_kernel_isolation_ci_receipt(receipt_value)

    try:
        artifact_bytes = Path(artifact_archive_path).read_bytes()
        if len(artifact_bytes) > _MAX_ARTIFACT_ARCHIVE_BYTES:
            raise KernelIsolationCIError("kernel-isolation source artifact exceeds the size limit")
        with zipfile.ZipFile(io.BytesIO(artifact_bytes), "r") as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)):
                raise KernelIsolationCIError(
                    "kernel-isolation source artifact contains duplicate members"
                )
            expected_names = {CI_JUNIT_ARTIFACT_NAME}
            if receipt["proof_profile"] == CI_PROOF_PROFILE_V2:
                expected_names.add(CI_RECEIPT_ARTIFACT_NAME)
            if set(names) != expected_names or any(item.is_dir() for item in infos):
                raise KernelIsolationCIError(
                    "kernel-isolation source artifact has an invalid member roster"
                )
            if any(
                item.file_size < 0 or item.file_size > _MAX_ARTIFACT_MEMBER_BYTES for item in infos
            ):
                raise KernelIsolationCIError(
                    "kernel-isolation source artifact member exceeds the size limit"
                )
            junit_bytes = archive.read(CI_JUNIT_ARTIFACT_NAME)
            if sha256_bytes(junit_bytes) != dict(receipt["junit"])["sha256"]:
                raise KernelIsolationCIError(
                    "source artifact JUnit differs from the canonical receipt"
                )
            if receipt["proof_profile"] == CI_PROOF_PROFILE_V2:
                try:
                    archived_receipt = json.loads(
                        archive.read(CI_RECEIPT_ARTIFACT_NAME).decode("utf-8")
                    )
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise KernelIsolationCIError(
                        "source artifact receipt is not valid UTF-8 JSON"
                    ) from exc
                if validate_kernel_isolation_ci_receipt(archived_receipt) != receipt:
                    raise KernelIsolationCIError(
                        "source artifact receipt differs from the reviewed receipt"
                    )
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise KernelIsolationCIError(
            f"cannot read kernel-isolation source artifact: {exc}"
        ) from exc

    body = {
        "schema": CI_ARCHIVE_SCHEMA,
        "archived_at_utc": archived_at_utc,
        "archived_by": archived_by,
        "receipt": receipt,
        "receipt_sha256": sha256_json(receipt),
        "source_artifact": {
            "artifact_id": artifact_id,
            "artifact_name": artifact_name,
            "archive_sha256": sha256_bytes(artifact_bytes),
            "junit_sha256": dict(receipt["junit"])["sha256"],
            "expires_at_utc": expires_at_utc,
        },
    }
    result = {**body, "self_checksum": sha256_json(body)}
    return validate_kernel_isolation_ci_archive(result)


def write_kernel_isolation_ci_receipt(path: str | Path, receipt: Mapping[str, object]) -> None:
    """Validate and write a canonical receipt exactly once."""
    validated = validate_kernel_isolation_ci_receipt(receipt)
    atomic_write_once(
        path,
        json.dumps(validated, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_kernel_isolation_ci_archive(path: str | Path, archive: Mapping[str, object]) -> None:
    """Validate and write a durable archive exactly once."""
    validated = validate_kernel_isolation_ci_archive(archive)
    atomic_write_once(
        path,
        json.dumps(validated, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
