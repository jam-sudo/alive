"""Tests for durable Linux kernel-isolation CI receipts."""

from __future__ import annotations

import json
import os
import subprocess
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
    CI_WORKFLOW_PATH,
    KernelIsolationCIError,
    build_kernel_isolation_ci_archive,
    build_kernel_isolation_ci_receipt,
    validate_kernel_isolation_ci_archive,
    validate_kernel_isolation_ci_receipt,
)
from alive.provenance import sha256_json

_REPO = Path(__file__).resolve().parents[3]
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


def _run_git(root: Path, *args: str) -> str:
    """Run git against ``root`` only, immune to an inherited ``GIT_*`` environment.

    Sanitising just ``GIT_CONFIG_*`` is not enough. With ``GIT_DIR`` exported,
    these helpers init, add and commit into *that* repository instead of the
    throwaway one — running this file under a stray ``GIT_DIR`` has already
    written a commit into a real checkout. Fixtures must not be able to reach
    outside ``root``.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env |= {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True, env=env
    ).stdout.strip()


def _synthetic_repo(root: Path, *, workflow_body: str = "name: synthetic\non: push\n") -> str:
    """Commit a canonical workflow into a throwaway repo; return its HEAD sha."""
    root.mkdir(parents=True, exist_ok=True)
    _run_git(root, "init", "-q")
    _run_git(root, "config", "user.email", "test@example.invalid")
    _run_git(root, "config", "user.name", "compose-test")
    workflow = root / CI_WORKFLOW_PATH
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(workflow_body, encoding="utf-8")
    _run_git(root, "add", CI_WORKFLOW_PATH)
    _run_git(root, "commit", "-q", "-m", "workflow")
    return _run_git(root, "rev-parse", "HEAD")


def _build(junit: Path, repo: Path, head_sha: str, **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "junit_path": junit,
        "workflow_path": repo / CI_WORKFLOW_PATH,
        "repository": "jam-sudo/alive",
        "head_sha": head_sha,
        "run_id": 123,
        "run_attempt": 1,
        "runner_os": "Linux",
        "runner_architecture": "x86_64",
        "kernel_release": "6.17.0-test",
        "proof_profile": CI_PROOF_PROFILE_V2,
    }
    kwargs.update(overrides)
    return build_kernel_isolation_ci_receipt(**kwargs)


def _receipt(tmp_path: Path, **junit_kwargs: object) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    junit = tmp_path / "junit.xml"
    _write_junit(junit, **junit_kwargs)
    repo = tmp_path / "repo"
    return _build(junit, repo, _synthetic_repo(repo))


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
    repo = tmp_path / "repo"
    with pytest.raises(KernelIsolationCIError, match="direct child of the single testsuite"):
        _build(junit, repo, _synthetic_repo(repo))


def test_workflow_must_match_the_blob_recorded_at_the_commit_under_test(tmp_path):
    junit = tmp_path / "junit.xml"
    _write_junit(junit)
    repo = tmp_path / "repo"
    head_sha = _synthetic_repo(repo)
    (repo / CI_WORKFLOW_PATH).write_text("name: swapped after commit\n", encoding="utf-8")
    with pytest.raises(KernelIsolationCIError, match="differs from the blob recorded"):
        _build(junit, repo, head_sha)


def test_rejects_a_workflow_at_a_suffix_matching_path_inside_the_worktree(tmp_path):
    """The canonical suffix alone must not admit an arbitrary file (attack G)."""
    junit = tmp_path / "junit.xml"
    _write_junit(junit)
    repo = tmp_path / "repo"
    head_sha = _synthetic_repo(repo)
    decoy = repo / "nested" / CI_WORKFLOW_PATH
    decoy.parent.mkdir(parents=True, exist_ok=True)
    decoy.write_text("totally not the real workflow\n", encoding="utf-8")
    with pytest.raises(KernelIsolationCIError, match="workflow path is not canonical"):
        _build(junit, repo, head_sha, workflow_path=decoy)


def test_rejects_a_workflow_outside_any_git_worktree(tmp_path):
    junit = tmp_path / "junit.xml"
    _write_junit(junit)
    loose = tmp_path / "loose" / CI_WORKFLOW_PATH
    loose.parent.mkdir(parents=True, exist_ok=True)
    loose.write_text("name: ungoverned\n", encoding="utf-8")
    with pytest.raises(KernelIsolationCIError):
        _build(junit, tmp_path / "loose", "b" * 40, workflow_path=loose)


def test_workflow_binding_ignores_a_hostile_git_environment(tmp_path, monkeypatch):
    """``GIT_*`` must not let a non-worktree directory answer as a repository.

    ``GIT_DIR``/``GIT_WORK_TREE`` redirect repository discovery, so an inherited
    environment could otherwise make an arbitrary staging directory pass the
    "must be a real Git worktree" check using an unrelated repository's objects.
    """
    junit = tmp_path / "junit.xml"
    _write_junit(junit)
    repo = tmp_path / "repo"
    head_sha = _synthetic_repo(repo)
    stage = tmp_path / "stage"
    (stage / CI_WORKFLOW_PATH).parent.mkdir(parents=True, exist_ok=True)
    (stage / CI_WORKFLOW_PATH).write_bytes((repo / CI_WORKFLOW_PATH).read_bytes())
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(stage))
    with pytest.raises(KernelIsolationCIError, match="not a git repository"):
        _build(junit, stage, head_sha, workflow_path=stage / CI_WORKFLOW_PATH)


def test_committed_historical_kernel_receipt_is_valid():
    archive = json.loads(_ARCHIVE.read_text(encoding="utf-8"))
    validated = validate_kernel_isolation_ci_archive(archive)
    receipt = validated["receipt"]
    assert receipt["head_sha"] == "614017b67e35e9cc07f68d5b512213d8356cf1b2"
    assert receipt["run_id"] == 30154404171
    assert receipt["junit"]["sha256"] == (
        "f3f68e0172d0b54eaeb1cdc5c510a7d0d638d9cd151da1e878c0b1118585826b"
    )
