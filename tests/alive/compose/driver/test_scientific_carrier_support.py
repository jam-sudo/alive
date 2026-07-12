"""Self-test: the test-only scientific corpus is valid + loads under the current loader.

The scientific carrier path is not built yet (Task 8); here we only prove the SUPPORT
module produces a byte-consistent scientific ResolvedRunSpec that the EXISTING
``load_resolved_run_spec`` accepts, and a clean synthetic git repo whose HEAD equals the
spec's ``approved_git_sha``. Every later task-test builds on this.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from alive.compose.driver.run_spec import load_resolved_run_spec
from tests.alive.compose.driver.scientific_carrier_support import (
    ScientificCarrierBundle,
    build_scientific_carrier_fixture,
)


def test_scientific_corpus_loads_under_current_loader(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    root = tmp_path / "artifacts"
    bundle = build_scientific_carrier_fixture(root, repo_root=repo_root)
    assert isinstance(bundle, ScientificCarrierBundle)

    spec = load_resolved_run_spec(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        mode_expected="scientific",
    )
    assert spec.mode == "scientific"
    assert spec.approved_git_sha == bundle.approved_git_sha
    assert spec.scientific is not None
    assert set(spec.scientific["activation_evidence"]["requirements"]) == set(
        bundle.activation_requirements
    )
    assert spec.scientific["sealed_input"]["snapshot_id"]
    assert spec.fixture is None


def test_synthetic_repo_is_clean_at_approved_head(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    root = tmp_path / "artifacts"
    bundle = build_scientific_carrier_fixture(root, repo_root=repo_root)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert head == bundle.approved_git_sha
    assert status == ""
