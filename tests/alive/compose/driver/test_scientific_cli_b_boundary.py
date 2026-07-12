"""Full scientific CLI reaches + fails closed at sub-project B's adapter_version (spec §6.7/§6.8).

This does NOT claim D2 (or any Phase-2a/D2/Phase-2b) was reached: _assemble_adapters resolves
worker identity BEFORE run_phase2a, so the first scientific failure IS the B boundary. No store
is constructed, no seal is opened, no audit is written, and no run-produced artifact appears.
"""

from __future__ import annotations

from pathlib import Path

from alive.compose.driver import cli
from alive.compose.driver.identity_lock import _COMMITTED_ADAPTER_MANIFEST
from tests.alive.compose.driver.scientific_carrier_support import build_scientific_carrier_fixture


def _argv(bundle, subcommand="phase2a"):
    return [
        subcommand,
        "--run-spec",
        str(bundle.spec_path),
        "--approved-artifacts-root",
        str(bundle.approved_artifacts_root),
        "--run-dir",
        str(bundle.run_dir),
        "--trusted-repo-root",
        str(bundle.repo_root),
    ]


def test_committed_adapter_manifest_still_absent():
    # The B boundary is exactly this: no committed scientific adapter manifest exists yet.
    assert _COMMITTED_ADAPTER_MANIFEST is None


def test_full_scientific_cli_fails_closed_at_b(tmp_path, capsys):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    rc = cli.main(_argv(bundle))
    assert rc == cli.PRESEAL_REJECT_EXIT  # 10
    err = capsys.readouterr().err
    assert "AssemblerError" in err
    assert "adapter" in err.lower()


def test_no_run_produced_artifact_no_seal_no_audit(tmp_path):
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    rc = cli.main(_argv(bundle))
    assert rc == cli.PRESEAL_REJECT_EXIT
    # run_dir holds NO run-produced artifact and NO audit.jsonl (the seal never opened).
    present = sorted(p.name for p in Path(bundle.run_dir).iterdir())
    assert present == []
    assert not (Path(bundle.run_dir) / "audit.jsonl").exists()
    assert not (Path(bundle.run_dir) / "seal_confirmation_manifest.json").exists()


def test_b_boundary_is_reached_not_a_spec_rejection(tmp_path, monkeypatch, capsys):
    # Prove the failure is the B ADAPTER boundary, not an earlier carrier-validation reject: a
    # monkeypatched committed manifest path would let assembly proceed past
    # _scientific_adapter_version into its (still-unimplemented) resolver — which raises a
    # DISTINCT AssemblerError. We assert the UNPATCHED message names the missing committed
    # manifest, i.e. B specifically.
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    rc = cli.main(_argv(bundle))
    assert rc == cli.PRESEAL_REJECT_EXIT
    err = capsys.readouterr().err
    assert "no committed" in err.lower() and "adapter_version" in err
