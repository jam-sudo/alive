"""Scientific phase2a dispatch forwards the real EnvironmentInfo, never UNKNOWN (spec §6.6)."""

from __future__ import annotations

import pytest

from alive.compose.driver import phase2a_cmd
from alive.compose.driver.carrier_loader import load_run_spec_carrier
from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture


class _Sentinel(RuntimeError):
    pass


def test_scientific_dispatch_forwards_environment(tmp_path, monkeypatch):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    carrier = load_run_spec_carrier(
        bundle.spec_path,
        approved_artifacts_root=bundle.approved_artifacts_root,
        trusted_repo_root=bundle.repo_root,
    )
    assert carrier.environment.git_commit == bundle.approved_git_sha
    assert carrier.environment.git_commit != "UNKNOWN"

    captured: dict = {}

    # Isolate the dispatch: bypass the sub-project-B adapter boundary (not under test here)…
    monkeypatch.setattr(phase2a_cmd, "_assemble_adapters", lambda *a, **k: {})

    # …and spy the library entry point to capture the environment kwarg.
    def _spy(*args, **kwargs):
        captured["environment"] = kwargs.get("environment")
        raise _Sentinel

    monkeypatch.setattr(phase2a_cmd, "run_phase2a", _spy)

    with pytest.raises(_Sentinel):
        phase2a_cmd.run_phase2a_subcommand(
            carrier,
            approved_artifacts_root=bundle.approved_artifacts_root,
            run_dir=bundle.run_dir,
        )
    assert captured["environment"] is carrier.environment
    assert captured["environment"].git_commit == bundle.approved_git_sha
