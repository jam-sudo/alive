"""Tests for durable Linux kernel-isolation CI receipts."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from alive.compose.kernel_isolation_ci import (
    CI_ARCHIVE_SCHEMA,
    CI_E2E_TEST,
    CI_PRIMITIVE_TEST,
    CI_PROOF_PROFILE_V2,
    CI_RECEIPT_SCHEMA,
    CI_TEST_CLASSNAME,
    KernelIsolationCIError,
    build_kernel_isolation_ci_archive,
    build_kernel_isolation_ci_receipt,
    validate_kernel_isolation_ci_archive,
    validate_kernel_isolation_ci_receipt,
)
from alive.provenance import sha256_json

_REPO = Path(__file__).resolve().parents[3]
_WORKFLOW = _REPO / ".github/workflows/test-suite.yml"
_ARCHIVE = (
    _REPO
    / "docs/activation-evidence/compose"
    / "kernel_isolation_ci_614017b67e35e9cc07f68d5b512213d8356cf1b2.json"
)


def _write_junit(
    path: Path,
    *,
    second_outcome: str = "",
    tests: int = 2,
    skipped: int = 0,
    second_time: str = "0.2",
) -> None:
    second = (
        f'<testcase classname="{CI_TEST_CLASSNAME}" name="{CI_E2E_TEST}" time="{second_time}">'
        f"{second_outcome}</testcase>"
    )
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest tests">'
        f'<testsuite name="pytest" errors="0" failures="0" skipped="{skipped}" '
        f'tests="{tests}" time="0.3" timestamp="2026-07-25T00:00:00+00:00" '
        'hostname="runner">'
        f'<testcase classname="{CI_TEST_CLASSNAME}" name="{CI_PRIMITIVE_TEST}" time="0.1" />'
        f"{second}</testsuite></testsuites>",
        encoding="utf-8",
    )


def _receipt(tmp_path: Path, **junit_kwargs: object) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    junit = tmp_path / "junit.xml"
    _write_junit(junit, **junit_kwargs)
    return build_kernel_isolation_ci_receipt(
        junit_path=junit,
        workflow_path=_WORKFLOW,
        repository="jam-sudo/alive",
        head_sha="a" * 40,
        run_id=123,
        run_attempt=1,
        runner_os="Linux",
        runner_architecture="x86_64",
        kernel_release="6.17.0-test",
        proof_profile=CI_PROOF_PROFILE_V2,
    )


def test_builds_v2_receipt_only_when_both_kernel_tests_pass(tmp_path):
    receipt = _receipt(tmp_path)
    assert receipt["schema"] == CI_RECEIPT_SCHEMA
    assert receipt["proof_profile"] == CI_PROOF_PROFILE_V2
    assert [case["name"] for case in receipt["required_test_cases"]] == [
        CI_PRIMITIVE_TEST,
        CI_E2E_TEST,
    ]
    assert validate_kernel_isolation_ci_receipt(receipt) == receipt


def test_rejects_skipped_end_to_end_test(tmp_path):
    with pytest.raises(KernelIsolationCIError, match="testcase failed"):
        _receipt(
            tmp_path,
            second_outcome='<skipped type="pytest.skip" message="no Linux" />',
            skipped=1,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"tests": 3}, "totals differ"),
        ({"second_time": "nan"}, "duration is malformed"),
    ],
)
def test_rejects_inconsistent_junit_or_nonfinite_duration(tmp_path, kwargs, message):
    with pytest.raises(KernelIsolationCIError, match=message):
        _receipt(tmp_path, **kwargs)


def test_receipt_and_archive_tampering_fail_closed(tmp_path):
    receipt = _receipt(tmp_path)
    receipt["runner"]["architecture"] = "aarch64"
    with pytest.raises(KernelIsolationCIError, match="checksum"):
        validate_kernel_isolation_ci_receipt(receipt)

    valid = _receipt(tmp_path / "second")
    archive_body = {
        "schema": CI_ARCHIVE_SCHEMA,
        "archived_at_utc": "2026-07-25T13:00:00Z",
        "archived_by": "independent review",
        "receipt": valid,
        "receipt_sha256": sha256_json(valid),
        "source_artifact": {
            "artifact_id": 1,
            "artifact_name": f"junit-{valid['head_sha']}",
            "archive_sha256": "b" * 64,
            "junit_sha256": valid["junit"]["sha256"],
            "expires_at_utc": "2026-08-24T13:00:00Z",
        },
    }
    archive = {**archive_body, "self_checksum": sha256_json(archive_body)}
    assert validate_kernel_isolation_ci_archive(archive) == archive
    archive["source_artifact"]["junit_sha256"] = "c" * 64
    with pytest.raises(KernelIsolationCIError, match="checksum"):
        validate_kernel_isolation_ci_archive(archive)


def test_archive_builder_binds_the_downloaded_zip_junit_and_receipt(tmp_path):
    receipt = _receipt(tmp_path)
    receipt_path = tmp_path / "kernel-isolation-ci-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    artifact = tmp_path / "artifact.zip"
    with zipfile.ZipFile(artifact, "w") as bundle:
        bundle.write(tmp_path / "junit.xml", "junit.xml")
        bundle.write(receipt_path, "kernel-isolation-ci-receipt.json")

    archive = build_kernel_isolation_ci_archive(
        receipt_path=receipt_path,
        artifact_archive_path=artifact,
        artifact_id=1234,
        artifact_name=f"junit-{receipt['head_sha']}",
        expires_at_utc="2026-08-24T13:00:00Z",
        archived_at_utc="2026-07-25T13:00:00Z",
        archived_by="independent reviewer",
    )
    assert validate_kernel_isolation_ci_archive(archive) == archive
    assert archive["receipt_sha256"] == sha256_json(receipt)


@pytest.mark.parametrize("include_receipt", [False, True])
def test_archive_builder_rejects_missing_receipt_or_unrelated_junit(tmp_path, include_receipt):
    receipt = _receipt(tmp_path)
    receipt_path = tmp_path / "kernel-isolation-ci-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    artifact = tmp_path / "artifact.zip"
    with zipfile.ZipFile(artifact, "w") as bundle:
        bundle.writestr("junit.xml", b"<unrelated />")
        if include_receipt:
            bundle.write(receipt_path, "kernel-isolation-ci-receipt.json")

    message = "member roster" if not include_receipt else "JUnit differs"
    with pytest.raises(KernelIsolationCIError, match=message):
        build_kernel_isolation_ci_archive(
            receipt_path=receipt_path,
            artifact_archive_path=artifact,
            artifact_id=1234,
            artifact_name=f"junit-{receipt['head_sha']}",
            expires_at_utc="2026-08-24T13:00:00Z",
            archived_at_utc="2026-07-25T13:00:00Z",
            archived_by="independent reviewer",
        )


@pytest.mark.parametrize(
    ("second_outcome", "message"),
    [
        ('<rerunFailure message="flaky" />', "unrecognised child element"),
        ('<flakyFailure message="flaky" />', "unrecognised child element"),
        ('<system-err><failure message="boom" /></system-err>', "must not contain nested"),
        ('<system-out><error message="boom" /></system-out>', "must not contain nested"),
        ('<failure message="boom"><nested /></failure>', "must not contain nested"),
        ("<properties><unexpected /></properties>", "only contain property elements"),
    ],
)
def test_unknown_or_buried_failure_markup_fails_closed(tmp_path, second_outcome, message):
    """A tag scan that only knows three bad names reads these forgeries as a pass.

    ``rerunFailure``/``flakyFailure`` are what rerun plugins emit, and a
    ``failure`` under captured output is not a direct child, so neither is seen
    by a blacklist. Both must be rejected instead of counted as a clean run.
    """
    with pytest.raises(KernelIsolationCIError, match=message):
        _receipt(tmp_path, second_outcome=second_outcome)


def test_accepts_the_legitimate_xunit2_child_vocabulary(tmp_path):
    """The allowlist must not reject output pytest genuinely emits."""
    receipt = _receipt(
        tmp_path,
        second_outcome=(
            "<system-out>captured stdout</system-out>"
            "<system-err>captured stderr</system-err>"
            '<properties><property name="k" value="v" /></properties>'
        ),
    )
    assert [case["status"] for case in receipt["required_test_cases"]] == ["passed", "passed"]


def test_rejects_testcase_smuggled_outside_the_single_testsuite(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest tests">'
        '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="2" time="0.3" '
        'timestamp="2026-07-25T00:00:00+00:00" hostname="runner">'
        f'<testcase classname="{CI_TEST_CLASSNAME}" name="{CI_PRIMITIVE_TEST}" time="0.1" />'
        f'<testcase classname="{CI_TEST_CLASSNAME}" name="{CI_E2E_TEST}" time="0.2">'
        f'<properties><testcase classname="{CI_TEST_CLASSNAME}" name="smuggled" time="0.1">'
        '<failure message="boom" /></testcase></properties>'
        "</testcase></testsuite></testsuites>",
        encoding="utf-8",
    )
    with pytest.raises(KernelIsolationCIError, match="direct child of the single testsuite"):
        build_kernel_isolation_ci_receipt(
            junit_path=junit,
            workflow_path=_WORKFLOW,
            repository="jam-sudo/alive",
            head_sha="a" * 40,
            run_id=123,
            run_attempt=1,
            runner_os="Linux",
            runner_architecture="x86_64",
            kernel_release="6.17.0-test",
            proof_profile=CI_PROOF_PROFILE_V2,
        )


def test_committed_historical_kernel_receipt_is_valid():
    archive = json.loads(_ARCHIVE.read_text(encoding="utf-8"))
    validated = validate_kernel_isolation_ci_archive(archive)
    receipt = validated["receipt"]
    assert receipt["head_sha"] == "614017b67e35e9cc07f68d5b512213d8356cf1b2"
    assert receipt["run_id"] == 30154404171
    assert receipt["junit"]["sha256"] == (
        "f3f68e0172d0b54eaeb1cdc5c510a7d0d638d9cd151da1e878c0b1118585826b"
    )
