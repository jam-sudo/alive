"""Full scientific CLI reaches + fails closed at sub-project B's adapter_version (spec §6.7/§6.8).

This does NOT claim D2 (or any Phase-2a/D2/Phase-2b) was reached: _assemble_adapters resolves
worker identity BEFORE run_phase2a, so the first scientific failure IS the B boundary. No store
is constructed, no seal is opened, no audit is written, and no run-produced artifact appears.

2026-09-07: the boundary MOVED but did not open. ``adapter_version`` now resolves from the
committed method manifest ``configs/compose_adapter_versions_v1.json``, so the CLI no longer stops
at "no committed manifest exists". It stops one step later, on the declared-vs-manifest comparison:
this synthetic carrier fixture declares the stub worker's ``stub-2``, which is not a real pod-built
adapter's version. Closing that last step needs a real ``.pyz`` worker whose self-reported adapter
identity matches the manifest — POD-GATED, not something a local fixture can assert.
"""

from __future__ import annotations

from pathlib import Path

from alive.compose.driver import cli
from alive.compose.driver.identity_lock import (
    _COMMITTED_ADAPTER_MANIFEST,
    _scientific_adapter_version,
)
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


def test_the_committed_adapter_manifest_is_present_and_the_boundary_moved():
    # The local half of the B boundary is closed: the committed method manifest exists and is
    # read from the repository. The remaining half is real-worker parity (POD-GATED).
    assert _COMMITTED_ADAPTER_MANIFEST.is_file()
    assert _scientific_adapter_version("gears") == "compose-gears-adapter-v1"
    assert _scientific_adapter_version("cpa") == "compose-cpa-adapter-v1"


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
    # run_dir holds no output and the protocol-global audit is absent (seal unopened).
    present = sorted(p.name for p in Path(bundle.run_dir).iterdir())
    assert present == []
    assert not bundle.audit_path.exists()
    assert not (Path(bundle.run_dir) / "seal_confirmation_manifest.json").exists()


def test_b_boundary_is_reached_not_a_spec_rejection(tmp_path, capsys):
    # Prove the failure is the B ADAPTER boundary, not an earlier carrier-validation reject: the
    # message must name the adapter_version comparison against the committed manifest, which is
    # only reachable AFTER every carrier / worker-file / bundle check has passed. The declared
    # value is the fixture's stub version; the manifest value is the committed one.
    bundle = build_scientific_carrier_fixture(tmp_path / "a", repo_root=tmp_path / "r")
    rc = cli.main(_argv(bundle))
    assert rc == cli.PRESEAL_REJECT_EXIT
    err = capsys.readouterr().err
    assert "adapter_version: declared version diverges" in err
    assert "the committed adapter manifest" in err
    assert "stub-2" in err
