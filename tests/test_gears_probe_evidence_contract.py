"""Regression checks for the quarantined GEARS decision-probe evidence."""

import hashlib
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ARCHIVE = _ROOT / "docs/superpowers/evidence/2026-07-11-gears-decision-probe"
_OLD_PLAN = _ROOT / "docs/superpowers/2026-07-10-compose-gears-decision-probe-plan.md"
_RESULTS = _ROOT / "docs/superpowers/2026-07-11-compose-gears-decision-probe-results.md"
_RERUN = _ROOT / "docs/superpowers/runbooks/2026-07-11-compose-gears-decision-probe-rerun.md"


def test_as_run_probe_is_quarantined_and_not_runnable() -> None:
    """The nonconforming as-run harness cannot masquerade as current instructions."""
    archive = (_ARCHIVE / "README.md").read_text(encoding="utf-8")
    old_plan = _OLD_PLAN.read_text(encoding="utf-8")
    results = _RESULTS.read_text(encoding="utf-8")

    assert "QUARANTINED / NONCONFORMING" in archive
    assert "DO NOT EXECUTE OR PROMOTE" in archive
    assert "SUPERSEDED / PARTIALLY EXECUTED / PROBE B NONCONFORMING" in old_plan
    assert "QUARANTINED PARTIAL OBSERVATIONS" in results
    assert "do not repair or rerun them in place" in results


def test_quarantined_archive_bytes_match_manifest() -> None:
    """Forensic harness/output bytes stay identical to the quarantined origin."""
    manifest = json.loads((_ARCHIVE / "archive_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "compose_quarantined_probe_archive_manifest_v1"
    assert manifest["status"] == "NONCONFORMING_FORENSIC_ARCHIVE"
    assert manifest["origin_commit"] == "6d30af55ce8d97198f39040193d3aa7338c25f9b"

    observed_paths = {
        path.relative_to(_ARCHIVE).as_posix()
        for directory in ("harness", "out")
        for path in (_ARCHIVE / directory).iterdir()
        if path.is_file()
    }
    expected_paths = {entry["path"] for entry in manifest["files"]}
    assert observed_paths == expected_paths
    for entry in manifest["files"]:
        data = (_ARCHIVE / entry["path"]).read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]


def test_replacement_runbook_preserves_metadata_first_boundary() -> None:
    """The replacement must keep the two boundary-ordering rules explicit."""
    rerun = _RERUN.read_text(encoding="utf-8")

    assert "resolve the outcome-independent pair manifest" in rerun
    assert "before touching `X`" in rerun
    assert "normalize allowed raw GEARS fit rows over `U_full` first" in rerun
    assert "subset to `R_gears` second" in rerun
    assert "never renormalize a reduced GEARS prediction" in rerun
    assert "MUST NOT be imported, copied, or executed" in rerun
    assert "receipt-last completion marker" in rerun
    assert "Do **not** pass shell command substitution" in rerun
