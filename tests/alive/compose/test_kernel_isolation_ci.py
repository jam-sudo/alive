"""Tests for durable Linux kernel-isolation CI receipts."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from alive.compose.kernel_isolation_ci import (
    _PROFILE_TESTS,
    CI_ARCHIVE_SCHEMA,
    CI_E2E_TEST,
    CI_PRIMITIVE_TEST,
    CI_PROOF_PROFILE_V2,
    CI_RECEIPT_SCHEMA,
    CI_RECEIPT_SCHEMA_V1,
    CI_RECEIPT_SCHEMA_V2,
    CI_TEST_CLASSNAME,
    CI_WORKFLOW_PATH,
    KernelIsolationCIError,
    _git,
    _parse_junit,
    _validate_interpreter,
    build_kernel_isolation_ci_archive,
    build_kernel_isolation_ci_receipt,
    interpreter_identity,
    validate_kernel_isolation_ci_archive,
    validate_kernel_isolation_ci_receipt,
)
from alive.provenance import sha256_bytes, sha256_json

_REPO = Path(__file__).resolve().parents[3]
_EVIDENCE = _REPO / "docs/activation-evidence/compose"
_V1_SHA = "614017b67e35e9cc07f68d5b512213d8356cf1b2"
_V2_SHA = "2dd23d627fc0e31a7d5005a3e81ff20b8dcd9472"
_ARCHIVE = _EVIDENCE / f"kernel_isolation_ci_{_V1_SHA}.json"
_ARCHIVE_V2 = _EVIDENCE / f"kernel_isolation_ci_{_V2_SHA}.json"
_JUNIT = _EVIDENCE / f"kernel_isolation_junit_{_V1_SHA}.xml"
_JUNIT_V2 = _EVIDENCE / f"kernel_isolation_junit_{_V2_SHA}.xml"


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
    with pytest.raises(KernelIsolationCIError, match="git rev-parse exited"):
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
    with pytest.raises(KernelIsolationCIError, match="git rev-parse exited"):
        _build(junit, stage, head_sha, workflow_path=stage / CI_WORKFLOW_PATH)


def test_rejects_a_symlink_workflow_entry_at_the_commit(tmp_path):
    """A mode-120000 entry hands back its target path, not a workflow.

    GitHub will not execute a symlinked workflow file, so a receipt built from
    one attests a workflow that could never have run.
    """
    junit = tmp_path / "junit.xml"
    _write_junit(junit)
    repo = tmp_path / "repo"
    _synthetic_repo(repo)
    payload = repo / "payload.txt"
    payload.write_text("/some/other/real.yml", encoding="utf-8")
    blob = _run_git(repo, "hash-object", "-w", "payload.txt")
    _run_git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},{CI_WORKFLOW_PATH}")
    tree = _run_git(repo, "write-tree")
    head_sha = _run_git(repo, "commit-tree", tree, "-m", "symlinked workflow")
    (repo / CI_WORKFLOW_PATH).write_text("/some/other/real.yml", encoding="utf-8")
    with pytest.raises(KernelIsolationCIError, match="regular-file workflow"):
        _build(junit, repo, head_sha)


def test_rejects_unrecognised_testsuite_markup(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest tests">'
        '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="2" time="0.3" '
        'timestamp="2026-07-25T00:00:00+00:00" hostname="runner">'
        '<failure message="the suite blew up" />'
        f'<testcase classname="{CI_TEST_CLASSNAME}" name="{CI_PRIMITIVE_TEST}" time="0.1" />'
        f'<testcase classname="{CI_TEST_CLASSNAME}" name="{CI_E2E_TEST}" time="0.2" />'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    with pytest.raises(KernelIsolationCIError, match="testsuite has an unrecognised child"):
        _build(junit, repo, _synthetic_repo(repo))


@pytest.mark.parametrize(
    ("root_extra", "suite_extra", "message"),
    [
        ("", '<failure message="the suite blew up" />', "testsuite has an unrecognised child"),
        ("", "<properties><failure /></properties>", "only contain property elements"),
        ("", "<system-out><failure /></system-out>", "system-out element must not contain nested"),
        ('<failure message="the run blew up" />', "", "report root has an unrecognised child"),
    ],
)
def test_rejects_markup_above_the_testcase_level(tmp_path, root_extra, suite_extra, message):
    """Guarding only the testcase leaves the same forgery available one level up."""
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<testsuites name="pytest tests">{root_extra}'
        '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="2" time="0.3" '
        f'timestamp="2026-07-25T00:00:00+00:00" hostname="runner">{suite_extra}'
        f'<testcase classname="{CI_TEST_CLASSNAME}" name="{CI_PRIMITIVE_TEST}" time="0.1" />'
        f'<testcase classname="{CI_TEST_CLASSNAME}" name="{CI_E2E_TEST}" time="0.2" />'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    with pytest.raises(KernelIsolationCIError, match=message):
        _build(junit, repo, _synthetic_repo(repo))


def test_accepts_suite_level_properties_and_captured_output(tmp_path):
    """``record_testsuite_property`` and ``junit_logging`` output must still pass."""
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest tests">'
        '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="2" time="0.3" '
        'timestamp="2026-07-25T00:00:00+00:00" hostname="runner">'
        '<properties><property name="suite" value="alive" /></properties>'
        "<system-out>suite stdout</system-out>"
        f'<testcase classname="{CI_TEST_CLASSNAME}" name="{CI_PRIMITIVE_TEST}" time="0.1" />'
        f'<testcase classname="{CI_TEST_CLASSNAME}" name="{CI_E2E_TEST}" time="0.2" />'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    receipt = _build(junit, repo, _synthetic_repo(repo))
    assert [case["status"] for case in receipt["required_test_cases"]] == ["passed", "passed"]


def test_rejects_a_head_sha_that_is_not_a_commit(tmp_path):
    """A 40-hex tree resolves for both ls-tree and cat-file; it is not a run."""
    junit = tmp_path / "junit.xml"
    _write_junit(junit)
    repo = tmp_path / "repo"
    _synthetic_repo(repo)
    tree_sha = _run_git(repo, "rev-parse", "HEAD^{tree}")
    with pytest.raises(KernelIsolationCIError, match="git cat-file exited"):
        _build(junit, repo, tree_sha)


def test_rejects_a_non_string_head_sha(tmp_path):
    junit = tmp_path / "junit.xml"
    _write_junit(junit)
    repo = tmp_path / "repo"
    _synthetic_repo(repo)
    with pytest.raises(KernelIsolationCIError, match="head SHA must be"):
        _build(junit, repo, None)


def test_committed_historical_kernel_receipt_is_valid():
    archive = json.loads(_ARCHIVE.read_text(encoding="utf-8"))
    validated = validate_kernel_isolation_ci_archive(archive)
    receipt = validated["receipt"]
    assert receipt["head_sha"] == "614017b67e35e9cc07f68d5b512213d8356cf1b2"
    assert receipt["run_id"] == 30154404171
    assert receipt["junit"]["sha256"] == (
        "f3f68e0172d0b54eaeb1cdc5c510a7d0d638d9cd151da1e878c0b1118585826b"
    )


def test_committed_v2_kernel_archive_is_valid_and_carries_the_launcher_roster():
    """Pin the operative archive, not only the superseded v1 one.

    The v1 archive above was the only committed archive any test read, so the v2
    file -- the one the readiness entry cites as the current proof profile --
    could be edited without the suite noticing. The digests asserted here are the
    coordinates a reviewer needs to re-derive the archive from primary bytes:
    GitHub run ``30200634662``, artifact ``8631825177``, the artifact zip digest
    and the JUnit digest inside it.
    """
    archive = json.loads(_ARCHIVE_V2.read_text(encoding="utf-8"))
    validated = validate_kernel_isolation_ci_archive(archive)
    receipt = validated["receipt"]
    assert receipt["head_sha"] == "2dd23d627fc0e31a7d5005a3e81ff20b8dcd9472"
    assert receipt["run_id"] == 30200634662
    assert receipt["junit"]["sha256"] == (
        "77c0262aaf67f0c337d91a6d53a31c4345f62dc22a8b129664785cda200ab84f"
    )
    source = validated["source_artifact"]
    assert source["artifact_id"] == 8631825177
    assert source["archive_sha256"] == (
        "1707a4dce36c14af50dd1a72fc3276efdb9da48586f9b9828421a2f150ff22ad"
    )
    # The whole point of v2 over v1 is that the launcher -> execve -> driver
    # self-check path executed, so the roster is the claim, not a detail.
    assert receipt["proof_profile"] == CI_PROOF_PROFILE_V2
    executed = {case["name"]: case["status"] for case in receipt["required_test_cases"]}
    assert executed == {CI_PRIMITIVE_TEST: "passed", CI_E2E_TEST: "passed"}


def test_the_v2_archive_still_records_that_it_was_not_independently_reviewed():
    """The review grade is load-bearing, so it may not be upgraded silently.

    ``archived_by`` is free text that no validator constrains beyond
    non-emptiness, and it is the only field distinguishing the v1 archive's
    independent review from the v2 archive's self-review. Nothing else would fail
    if that string were rewritten to claim independence this archive does not
    have, so the honest grade is pinned here: earning a real one is a deliberate
    edit to this test, not a quiet string change.
    """
    v2 = json.loads(_ARCHIVE_V2.read_text(encoding="utf-8"))
    assert v2["archived_by"] == (
        "Claude Code subagent review dispatched by the authoring session "
        "(adversarial audit + from-primary-bytes recomputation); "
        "not an independent third party"
    )


@pytest.mark.parametrize(
    ("archive_path", "junit_path"),
    [(_ARCHIVE, _JUNIT), (_ARCHIVE_V2, _JUNIT_V2)],
    ids=["v1", "v2"],
)
def test_committed_junit_bytes_reproduce_the_archived_receipt(archive_path, junit_path):
    """Keep the archives falsifiable after their GitHub artifacts expire.

    An archive records a JUnit digest, not the JUnit. While the run's artifact is
    downloadable that is enough -- anyone can refute the archive by fetching the
    artifact and recomputing -- but Actions retention is finite, and once the
    artifact is gone the digest has nothing left to be checked against and
    ``archived_by`` becomes the whole trust basis. The primary bytes are
    therefore committed beside each archive, and this test is what makes them
    load-bearing: it re-derives the receipt's entire ``junit`` block and its
    required-testcase roster from those bytes through the same parser the
    builder uses, so the archive stays reproducible from committed data alone.

    Both files were confirmed byte-identical to their GitHub artifacts on
    2026-07-29, while both were still live.
    """
    archive = validate_kernel_isolation_ci_archive(
        json.loads(archive_path.read_text(encoding="utf-8"))
    )
    receipt = archive["receipt"]
    junit, cases = _parse_junit(
        junit_path,
        required_tests=_PROFILE_TESTS[receipt["proof_profile"]],
    )
    assert junit == receipt["junit"]
    assert cases == [dict(case) for case in receipt["required_test_cases"]]


@pytest.mark.repo_history
@pytest.mark.parametrize("archive_path", [_ARCHIVE, _ARCHIVE_V2], ids=["v1", "v2"])
def test_archived_workflow_digest_reproduces_from_the_recorded_commit(archive_path):
    """Check the one receipt digest that has permanent in-repo ground truth.

    ``workflow_sha256`` is re-derivable forever from ``git cat-file blob
    <head_sha>:<workflow>`` — unlike ``run_id``, ``runner`` or
    ``source_artifact``, which no committed byte can ever confirm. It was
    nonetheless the only such digest that nothing checked: rewriting it takes a
    four-field edit inside one JSON (the value plus the three checksums that
    cover it) and no test-file edit at all. That matters because the readiness
    entry names this field as the carrier of the suite-scope property the schema
    deliberately does not enforce, so a forged value re-points the evidence at a
    workflow that never ran these tests.

    Read the blob directly rather than through ``_workflow_bytes_at_commit``:
    that helper additionally requires the WORKING TREE workflow to equal the
    recorded blob, which is false by design here — the workflow has changed since
    both archived runs.
    """
    archive = validate_kernel_isolation_ci_archive(
        json.loads(archive_path.read_text(encoding="utf-8"))
    )
    receipt = archive["receipt"]
    assert receipt["workflow_path"] == CI_WORKFLOW_PATH
    blob = _git(_REPO, "cat-file", "blob", f"{receipt['head_sha']}:{CI_WORKFLOW_PATH}")
    assert sha256_bytes(blob) == receipt["workflow_sha256"]


# The files whose bytes determine what the two Linux kernel-isolation tests
# prove. The five direct participants plus the transitive ``alive`` import
# closure of the launcher and the probe driver: ``network_isolation`` routes
# every receipt checksum through ``provenance``, and ``gears_decision_probe``
# imports nine ``alive`` modules at module scope, so a behaviour change in any of
# them changes what the archived pass means.
_ISOLATION_CLOSURE = (
    "src/alive/compose/network_isolation.py",
    "src/alive/compose/gears_probe_a.py",
    "scripts/compose/run_network_isolated.py",
    "scripts/compose/gears_decision_probe.py",
    "tests/alive/compose/test_network_isolation.py",
    "src/alive/provenance.py",
    "src/alive/io.py",
    "src/alive/compose/roles.py",
    "src/alive/compose/response.py",
    "src/alive/compose/fit_role.py",
    "src/alive/compose/gene_universe.py",
    "src/alive/compose/worker_bundle.py",
    "src/alive/compose/activation_evidence.py",
    "src/alive/compose/approximation_bias.py",
    "src/alive/compose/baseline_subprocess.py",
    "src/alive/compose/baselines_combo.py",
    # Both package __init__ files execute on every `alive.compose.*` import, and
    # `alive/compose/__init__.py` is not inert: it is a PEP-562 lazy-import gate
    # whose stated purpose is to keep the subprocess workers from transitively
    # pulling the Phase-1 stack. Replacing its `_LAZY_EXPORTS` map with eager
    # imports would change the entire import surface running under the seccomp
    # filter, and it is the only importer node from which such growth could hide
    # -- every other importer here is pinned, so closure growth elsewhere trips
    # this check indirectly.
    "src/alive/__init__.py",
    "src/alive/compose/__init__.py",
    # The proof ran after `uv sync --locked`; the resolved import/runtime graph is
    # therefore decision-relevant even though uv.lock does not identify the
    # CPython build. Pin the lock as an intentional conservative superset, and
    # keep exact interpreter patch/build identity as a separate receipt gap.
    "uv.lock",
    ".python-version",
)

#: Closure files whose shipped bytes have INTENTIONALLY moved past the archived proof:
#: ``rel -> (sha256 of the exact shipped bytes that are allowed to differ, the change that
#: made the proof stale, why)``. The second element names the CHANGE, not a commit whose
#: blob equals the digest -- a later follow-up may refine the same file, in which case the
#: digest moves with the shipped bytes while the stale-making change stays what it was.
#:
#: This is not a way to stop checking a file: an entry admits ONE known byte
#: sequence, so any further edit to that file drifts again and fails closed. It exists
#: because re-establishing the proof needs a Linux kernel-isolation CI run (POD-GATED),
#: which cannot happen in the same change that alters the code -- and leaving the suite
#: red in the meantime is how a real drift gets normalised into background noise.
#:
#: An entry may be removed ONLY by moving ``_V2_SHA`` to a fresh archive at the changed
#: code. ``test_a_pending_kernel_reproof_is_declared_in_the_readiness_index`` keeps the
#: human-facing readiness index saying so for as long as this roster is non-empty.
_PENDING_REPROOF: dict[str, tuple[str, str, str]] = {
    "src/alive/compose/approximation_bias.py": (
        "af0dab18086bcdf5adc3d19815ac6fa4a7695efa9f6dd1f6d58138c83f6c31c2",
        "aed26aa",
        "R1 admission contract (2026-09-07): kernel-isolation proof STALE for this file "
        "until the Linux CI is re-run at the changed code and this pin moves",
    )
}

_READINESS_INDEX = _REPO / "docs/superpowers/COMPOSE-SEAL-READINESS.md"
_STALE_PROOF_MARKER = "kernel-isolation proof: STALE"


@pytest.mark.repo_history
def test_the_v2_kernel_proof_still_covers_the_shipped_isolation_closure():
    """Fail closed when the archived kernel proof stops covering today's code.

    The v2 archive proves the seccomp policy and the launcher -> execve -> driver
    path at commit ``2dd23d6``. Its relevance to the shipped code rests entirely
    on those bytes being unchanged since, and that was asserted only in prose:
    editing ``network_isolation.py`` left the whole suite green while the
    readiness entry went on claiming the proof still applied.

    A failure here is not necessarily a defect — it means the kernel evidence
    must be re-established by a fresh Linux CI run and a new archive at the
    changed code, and that this pin must then move to that run's commit.
    """
    drifted = []
    pending = []
    for rel in _ISOLATION_CLOSURE:
        recorded = _git(_REPO, "cat-file", "blob", f"{_V2_SHA}:{rel}")
        shipped = (_REPO / rel).read_bytes()
        if shipped == recorded:
            continue
        allowed = _PENDING_REPROOF.get(rel)
        if allowed is not None and sha256_bytes(shipped) == allowed[0]:
            pending.append(rel)
            continue
        drifted.append(rel)
    assert not drifted, (
        f"the v2 kernel-isolation proof at {_V2_SHA[:7]} no longer covers these shipped files: "
        f"{drifted}. Re-run the Linux kernel-isolation CI at the changed code, archive a new "
        "receipt, and move this pin -- do not delete the check"
    )
    # Not an escape hatch: every exception is one exact digest, so this list can only ever
    # contain files whose bytes are STILL the ones a human declared and pinned.
    assert set(pending) <= set(_PENDING_REPROOF)


@pytest.mark.repo_history
def test_a_pending_kernel_reproof_is_declared_in_the_readiness_index():
    """A pinned exception must be visible to a human, not only to the test suite.

    ``_PENDING_REPROOF`` keeps the suite green while the Linux CI re-run is pending, which
    is exactly the state in which the readiness index must NOT go on implying the kernel
    evidence still covers the shipped code -- the failure mode the closure test was written
    for in the first place. So while the roster is non-empty the index has to say so, and
    name every file it is saying it about.
    """
    if not _PENDING_REPROOF:
        pytest.skip("no pending kernel-isolation re-proof to declare")
    text = _READINESS_INDEX.read_text(encoding="utf-8")
    assert _STALE_PROOF_MARKER in text, (
        f"{_READINESS_INDEX.name} must carry the marker {_STALE_PROOF_MARKER!r} while "
        f"_PENDING_REPROOF is non-empty ({sorted(_PENDING_REPROOF)})"
    )
    for rel in _PENDING_REPROOF:
        assert rel in text, f"{_READINESS_INDEX.name} does not name the pending file {rel}"
    # A pinned exception for a file outside the closure would check nothing at all.
    assert set(_PENDING_REPROOF) <= set(_ISOLATION_CLOSURE)


@pytest.mark.repo_history
def test_the_interpreter_range_the_kernel_proof_assumes_is_unchanged():
    """``requires-python`` is part of the closure but lives in a busy file.

    Pinning all of ``pyproject.toml`` would fire on unrelated tooling edits, so
    only the field that changes which interpreter the proof was established
    against is pinned here.
    """
    recorded = tomllib.loads(
        _git(_REPO, "cat-file", "blob", f"{_V2_SHA}:pyproject.toml").decode("utf-8")
    )
    current = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert current["project"]["requires-python"] == recorded["project"]["requires-python"]


# --------------------------------------------------------------------------- #
# Receipt v2: the interpreter that actually ran the proof.
#
# `.python-version` names a minor series and identifies no patch release, so
# before the v2 block the receipt could not say which CPython produced the
# result. The schema bump is back-compatible on purpose: the two committed
# archives embed v1 receipts and their source artifacts expire, so a validator
# that stopped reading v1 would retire durable evidence nobody can regenerate.
# --------------------------------------------------------------------------- #


def _resign(receipt: dict) -> dict:
    """Re-sign a mutated receipt so the roster, not the checksum, is under test."""
    body = {key: item for key, item in receipt.items() if key != "self_checksum"}
    return {**body, "self_checksum": sha256_json(body)}


def test_the_receipt_records_the_interpreter_that_built_it(tmp_path):
    receipt = _receipt(tmp_path)
    assert receipt["schema"] == CI_RECEIPT_SCHEMA_V2
    interpreter = receipt["interpreter"]
    assert set(interpreter) == {"version", "build", "implementation"}
    # Compared against a FRESH read, not against the same call that built it: a
    # constant-returning `interpreter_identity` would satisfy self-consistency.
    assert interpreter == interpreter_identity()
    assert interpreter["version"] == platform.python_version()
    assert interpreter["implementation"] == sys.implementation.name
    # The patch level is the whole point -- `.python-version` already carries the
    # minor series, so a two-component version records nothing new.
    assert len(interpreter["version"].split(".")) == 3
    assert interpreter["version"] != ".".join(interpreter["version"].split(".")[:2])


def test_the_build_string_is_single_line_so_the_digest_is_format_independent(tmp_path):
    """`sys.version` embeds a newline; an unnormalised copy would leak into the digest."""
    receipt = _receipt(tmp_path)
    build = receipt["interpreter"]["build"]
    assert "\n" not in build and "\r" not in build
    assert build == " ".join(build.split())
    assert build.startswith(receipt["interpreter"]["version"])


def test_both_committed_archives_still_validate_under_the_v2_validator():
    """The back-compat constraint, asserted on the real files rather than a fixture.

    Neither committed archive can be regenerated: their GitHub artifacts expire,
    and the v1 archive is the one carrying the independent Codex review grade. If
    this ever fails, the fix is the validator, never the archives.
    """
    for path in (_ARCHIVE, _ARCHIVE_V2):
        archive = json.loads(path.read_text(encoding="utf-8"))
        validated = validate_kernel_isolation_ci_archive(archive)
        receipt = validated["receipt"]
        assert receipt["schema"] == CI_RECEIPT_SCHEMA_V1
        assert "interpreter" not in receipt


def test_a_v1_receipt_may_not_smuggle_an_interpreter_block(tmp_path):
    """Version and roster move together in BOTH directions, or neither is enforced."""
    receipt = _receipt(tmp_path)
    downgraded = _resign({**receipt, "schema": CI_RECEIPT_SCHEMA_V1})
    with pytest.raises(KernelIsolationCIError, match="field roster"):
        validate_kernel_isolation_ci_receipt(downgraded)


def test_a_v2_receipt_may_not_omit_the_interpreter_block(tmp_path):
    receipt = _receipt(tmp_path)
    stripped = _resign({k: v for k, v in receipt.items() if k != "interpreter"})
    assert stripped["schema"] == CI_RECEIPT_SCHEMA_V2
    with pytest.raises(KernelIsolationCIError, match="field roster"):
        validate_kernel_isolation_ci_receipt(stripped)


def test_an_unknown_schema_resolves_to_no_roster_and_is_refused(tmp_path):
    """Fail closed on an unrecognised version rather than guessing a roster."""
    receipt = _receipt(tmp_path)
    for bogus in ("compose_kernel_isolation_ci_receipt_v3", "", "v2"):
        with pytest.raises(KernelIsolationCIError, match="checksum or schema mismatch"):
            validate_kernel_isolation_ci_receipt(_resign({**receipt, "schema": bogus}))


def test_the_interpreter_block_is_covered_by_the_self_checksum(tmp_path):
    """Editing it without re-signing must be caught; that is what makes it evidence."""
    receipt = _receipt(tmp_path)
    forged = {**receipt, "interpreter": {**receipt["interpreter"], "version": "9.9.9"}}
    with pytest.raises(KernelIsolationCIError, match="checksum or schema mismatch"):
        validate_kernel_isolation_ci_receipt(forged)


def test_the_interpreter_roster_is_exact(tmp_path):
    receipt = _receipt(tmp_path)
    for mutated in (
        {**receipt["interpreter"], "extra": "x"},
        {k: v for k, v in receipt["interpreter"].items() if k != "build"},
        {},
    ):
        with pytest.raises(KernelIsolationCIError, match="interpreter has an invalid field roster"):
            validate_kernel_isolation_ci_receipt(_resign({**receipt, "interpreter": mutated}))


@pytest.mark.parametrize("field", ["version", "build", "implementation"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_every_interpreter_field_must_be_a_non_empty_string(tmp_path, field, blank):
    """Parametrised over ALL THREE fields: a single-field test certifies one seat."""
    receipt = _receipt(tmp_path)
    interpreter = {**receipt["interpreter"], field: blank}
    with pytest.raises(KernelIsolationCIError, match=f"interpreter {field} must be non-empty"):
        validate_kernel_isolation_ci_receipt(_resign({**receipt, "interpreter": interpreter}))


@pytest.mark.parametrize("bad", ["3.12", "3", "3.12.13.1", "x.y.z", "3.12.x", "312"])
def test_the_version_must_carry_a_patch_level(tmp_path, bad):
    receipt = _receipt(tmp_path)
    interpreter = {**receipt["interpreter"], "version": bad, "build": f"{bad} (main) [Clang]"}
    with pytest.raises(KernelIsolationCIError, match="major.minor.patch"):
        validate_kernel_isolation_ci_receipt(_resign({**receipt, "interpreter": interpreter}))


def test_a_version_that_disagrees_with_its_build_string_is_refused(tmp_path):
    """The cross-field binding: `sys.version` starts with the release it reports."""
    receipt = _receipt(tmp_path)
    interpreter = {**receipt["interpreter"], "version": "3.11.99"}
    with pytest.raises(KernelIsolationCIError, match="build string disagrees"):
        validate_kernel_isolation_ci_receipt(_resign({**receipt, "interpreter": interpreter}))

    # An empty build is caught earlier, by the non-empty check -- pinned so the
    # `not build_tokens` branch is not mistaken for dead code.
    blanked = {**receipt["interpreter"], "build": " "}
    with pytest.raises(KernelIsolationCIError, match="build must be non-empty"):
        validate_kernel_isolation_ci_receipt(_resign({**receipt, "interpreter": blanked}))


def test_a_pre_release_interpreter_is_accepted_not_rejected(tmp_path):
    """Why the binding is `startswith` and not equality.

    On a release both fields carry `3.12.13` and equality would hold. On a
    pre-release `sys.version` reports `3.13.0rc1` while `platform.python_version()`
    reports `3.13.0`, so an equality check would reject a legitimate receipt --
    and because a red suite skips the receipt-build step and the upload then fails
    closed, that would take the only kernel-property gate offline rather than warn.
    """
    receipt = _receipt(tmp_path)
    interpreter = {
        **receipt["interpreter"],
        "version": "3.13.0",
        "build": "3.13.0rc1 (main, Jan 1 2026, 00:00:00) [Clang 21.0.0]",
    }
    validated = validate_kernel_isolation_ci_receipt(
        _resign({**receipt, "interpreter": interpreter})
    )
    assert validated["interpreter"]["build"].startswith("3.13.0rc1")

    # ...but a DIFFERENT release is still refused, so the leniency is scoped to a
    # suffix on the same version and is not a hole.
    wrong = {**interpreter, "build": "3.13.1 (main, Jan 1 2026, 00:00:00) [Clang 21.0.0]"}
    with pytest.raises(KernelIsolationCIError, match="build string disagrees"):
        validate_kernel_isolation_ci_receipt(_resign({**receipt, "interpreter": wrong}))


def test_the_recorded_interpreter_follows_the_running_one_rather_than_a_constant(
    tmp_path, monkeypatch
):
    """A literal equal to today's interpreter passes every equality assertion.

    This is the mutation the first version of this file could not kill. On this
    machine ``platform.python_version()`` IS ``3.12.13``, so replacing the call
    with that literal is invisible to any check comparing the receipt against
    today's value -- including a comparison against ``interpreter_identity()``,
    because the mutation changes both sides at once. Two mutations of exactly that
    shape survived, one per field.

    The discriminating property is not "matches the interpreter" but "FOLLOWS the
    interpreter": move the interpreter and the receipt must move with it. The
    asserted values are ones no real CPython here reports, so the monkeypatches
    are load-bearing -- delete any of them and this test fails rather than
    silently passing.
    """
    monkeypatch.setattr(platform, "python_version", lambda: "3.99.7")
    monkeypatch.setattr(sys, "version", "3.99.7 (main, Jan 1 2099, 00:00:00) [Clang 99.0.0]")
    monkeypatch.setattr(sys, "implementation", SimpleNamespace(name="ratpython"))

    assert interpreter_identity() == {
        "version": "3.99.7",
        "build": "3.99.7 (main, Jan 1 2099, 00:00:00) [Clang 99.0.0]",
        "implementation": "ratpython",
    }
    receipt = _receipt(tmp_path)
    assert receipt["interpreter"] == interpreter_identity()
    # Named explicitly too: an `interpreter_identity` that returned a constant
    # would satisfy the line above by making both sides equally wrong.
    assert receipt["interpreter"]["version"] == "3.99.7"
    assert receipt["interpreter"]["implementation"] == "ratpython"
    assert validate_kernel_isolation_ci_receipt(receipt) == receipt


# ---------------------------------------------------------------------------
# Interpreter version<->build binding: the invariant the docstring claims
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build_token, bound",
    [
        ("3.12.14", True),  # release: version == build token
        ("3.12.14rc1", True),  # prerelease: the tolerance the binding exists for
        ("3.12.14+local", True),  # local version label
        ("3.12.140", False),  # DIFFERENT patch level, not a suffix of 14
        ("3.12.149", False),
        ("3.12.140evil", False),  # forged token that a prefix match accepts
        ("3.12.1", False),  # shorter: not a prefix at all
    ],
)
def test_interpreter_build_binding_pins_the_patch_level(build_token, bound):
    """A bare ``startswith`` accepts ``3.12.140`` for version ``3.12.14``.

    The binding's own docstring claims it "still pins the full patch level"; a
    prefix match does not. This pins BOTH halves of the contract at once: every
    legitimate prerelease/local suffix stays accepted, and a numeric continuation
    -- which is a different patch level, not a suffix -- is rejected.
    """
    interpreter = {
        "version": "3.12.14",
        "build": f"{build_token} (main, Jan 1 2026, 00:00:00) [Clang 17.0.0]",
        "implementation": "CPython",
    }
    if bound:
        assert _validate_interpreter(interpreter) == interpreter
    else:
        with pytest.raises(KernelIsolationCIError, match="disagrees with its version"):
            _validate_interpreter(interpreter)
