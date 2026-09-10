"""The pod-side entry point for the dev-pod smoke evidence.

`scripts/` stays a thin entry point (CLAUDE.md #repo); the assembly logic lives in
`alive.compose.smoke_evidence`. What this layer adds is that the operator cannot
walk away with a lock that does not validate: the tool re-runs the committed
validator on what it wrote and fails loudly if it does not come back COMPLETE.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from alive.compose.activation_evidence import validate_dependency_lock
from tests.alive.compose.smoke_evidence_support import (
    TINY_SEALED_PAIRS,
    write_tiny_fit_role_artifact,
    write_tiny_pair_manifest,
)

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "scripts" / "compose_smoke_evidence.py"
EVIDENCE = REPO / "docs/activation-evidence/compose"
LOCK_NAME = "gears_cpa_dependency_lock.json"
ARTIFACT_NAMES = (
    "norman_source",
    "fit_role_artifact",
    "fit_role_row_identity",
    "smoke_script",
    "command_log",
    "checkpoint",
)


def _bundle(tmp_path, *, overlap=False, drift=False):
    """A self-contained inputs bundle: staged evidence dir + files + inputs.json.

    `overlap` puts a row carrying the sealed pair into gears' fit-role artifact
    (promotion refuses); `drift` resolves cpa's wheelhouse from a lock with one
    extra pin (only the validator, comparing against the evidence directory's
    pins, refuses).
    """
    staged = tmp_path / "compose"
    shutil.copytree(EVIDENCE, staged)
    # The split manifest the tiny artifacts were cut against, on disk where the
    # bundle can point at it: the CLI derives the sealed roster from this file.
    pair_manifest = write_tiny_pair_manifest(tmp_path / "pair_manifest.json")

    backends = {}
    for backend in ("gears", "cpa"):
        artifact = write_tiny_fit_role_artifact(
            tmp_path / backend / "fit_role_artifact.h5ad",
            with_sealed_row=(overlap and backend == "gears"),
        )
        objects = {}
        for index, name in enumerate(ARTIFACT_NAMES):
            if name == "fit_role_artifact":
                blob = Path(artifact.path)
            else:
                blob = tmp_path / backend / f"{name}.bin"
                blob.parent.mkdir(parents=True, exist_ok=True)
                blob.write_bytes(f"{backend}-{name}-{index}".encode())
            objects[name] = {
                "path": str(blob),
                "uri": f"s3://alive-compose-evidence/{backend}/{name}",
                "immutable_version": f"v{index}Ab9",
            }
        backends[backend] = {
            "fit_role_artifact": artifact.to_payload_block(),
            "approved_root": str(tmp_path),
            "pair_manifest": str(pair_manifest),
            "sealed_pair_ids": [list(pair) for pair in TINY_SEALED_PAIRS],
            "exit_code": 0,
            "artifacts": objects,
        }

    wheelhouse = {}
    for env_name in ("gears_env", "cpa_env"):
        lock = staged / f"requirements.{env_name}.lock"
        if drift and env_name == "cpa_env":
            lock = tmp_path / "requirements.cpa_env.drifted.lock"
            lock.write_text(
                (staged / "requirements.cpa_env.lock").read_text(encoding="utf-8")
                + "extra-pkg==1.0\n",
                encoding="utf-8",
            )
        wheels = {}
        for line in lock.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, version = line.split("==", 1)
            key = name.lower().replace("_", "-")
            wheel = tmp_path / "wheels" / env_name / f"{key}-{version}.whl"
            wheel.parent.mkdir(parents=True, exist_ok=True)
            wheel.write_bytes(f"{env_name}/{key}/{version}".encode())
            wheels[key] = {
                "path": str(wheel),
                "filename": wheel.name,
                "source_url": f"https://pypi.org/simple/{key}/{wheel.name}",
            }
        wheelhouse[env_name] = {
            "requirements_lock": str(lock),
            "artifacts": wheels,
        }

    inputs = tmp_path / "inputs.json"
    inputs.write_text(
        json.dumps(
            {
                "git_sha": "a" * 40,
                "container_image_digest": "sha256:" + "b" * 64,
                "generated_at_utc": "2026-09-05T21:00:00Z",
                "host": {"gpu": "NVIDIA A100 80GB PCIe", "nvidia_driver": "550.127.05"},
                "activation": "READY — fit-role smoke evidence captured on the dev pod",
                "summary": "Both backends completed the fit-role smoke; rosters disjoint.",
                "backends": backends,
                "wheelhouse": wheelhouse,
            }
        ),
        encoding="utf-8",
    )
    return staged, inputs


def _run(inputs, staged):
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            "promote",
            "--inputs",
            str(inputs),
            "--evidence-dir",
            str(staged),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def test_the_cli_promotes_an_inputs_bundle_to_a_validated_complete_lock(tmp_path):
    """The operator's one command: bundle in, validated COMPLETE lock out."""
    staged, inputs = _bundle(tmp_path)
    result = _run(inputs, staged)

    assert result.returncode == 0, result.stderr
    lock = json.loads((staged / LOCK_NAME).read_text(encoding="utf-8"))
    assert lock["run_gate"]["evidence_status"] == "COMPLETE"
    assert lock["run_gate"]["seal_safety_status"] == "VERIFIED_ZERO_OVERLAP"
    assert "COMPLETE" in result.stdout


def test_refused_evidence_exits_nonzero_and_leaves_the_lock_incomplete(tmp_path):
    """A roster that overlaps the seal must not end with exit 0.

    The distinctive claim of this layer is the exit code: an operator wiring this
    into a pod script reads `$?`, not the prose. Printing a warning and returning 0
    would let a refused run look like a successful one.
    """
    staged, inputs = _bundle(tmp_path, overlap=True)
    result = _run(inputs, staged)

    assert result.returncode != 0
    lock = json.loads((staged / LOCK_NAME).read_text(encoding="utf-8"))
    assert lock["run_gate"]["evidence_status"] == "INCOMPLETE"


def _snapshot(directory):
    """Every file under `directory` with its exact bytes, so nothing can change unnoticed."""
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_a_run_the_validator_refuses_leaves_the_evidence_directory_byte_identical(tmp_path):
    """Refusal must leave the WHOLE directory as it was found, not just the lock.

    A wheelhouse resolved from a stale requirements lock passes every producer-side
    check and is refused by the validator against the evidence directory's pins.
    The first CLI protected only the lock (validate a candidate, then replace)
    while the five sidecar manifests had already been written into the evidence
    directory before validation ran -- a refused run left its rosters and artifact
    manifests behind under the very names the next successful run would use. The
    claim is stronger and simpler: a refused run changes no byte under the
    evidence directory.
    """
    staged, inputs = _bundle(tmp_path, drift=True)
    before = _snapshot(staged)

    result = _run(inputs, staged)

    assert result.returncode != 0
    assert _snapshot(staged) == before


def test_a_second_run_cannot_disturb_a_published_complete_lock(tmp_path):
    """The reviewer's scenario: a valid run, then another one on the same directory.

    Run 1 publishes a COMPLETE lock whose record binds five sidecar files by SHA.
    Run 2 is another promotion onto it. With sidecars written before
    validation, run 2 overwrote run 1's roster file under the same name, and run
    1's lock -- still on disk, still saying COMPLETE -- no longer validated: a
    later run had destroyed the evidence of a successful one. A COMPLETE lock is a
    published result; a second promotion onto it is refused before anything is
    written.
    """
    staged, inputs = _bundle(tmp_path)
    assert _run(inputs, staged).returncode == 0
    after_first = _snapshot(staged)

    bundle = json.loads(inputs.read_text(encoding="utf-8"))
    bundle["summary"] = "a second run onto the same directory"
    inputs.write_text(json.dumps(bundle), encoding="utf-8")

    result = _run(inputs, staged)

    assert result.returncode != 0
    assert _snapshot(staged) == after_first
    assert validate_dependency_lock(staged / LOCK_NAME)["run_gate"]["evidence_status"] == "COMPLETE"


def test_a_bundle_missing_a_field_is_a_usage_error_not_a_traceback(tmp_path):
    """Exit 2 and the missing key's name; not a `KeyError` traceback and exit 1.

    Exit 1 means "refused": the inputs were understood and found wanting. A bundle
    the tool cannot even read is a different failure and an operator reading `$?`
    must be able to tell them apart.
    """
    staged, inputs = _bundle(tmp_path)
    bundle = json.loads(inputs.read_text(encoding="utf-8"))
    del bundle["git_sha"]
    inputs.write_text(json.dumps(bundle), encoding="utf-8")

    result = _run(inputs, staged)

    assert result.returncode == 2
    assert "git_sha" in result.stderr
    assert "Traceback" not in result.stderr


def test_a_bundle_without_a_pair_manifest_is_a_usage_error(tmp_path):
    """`pair_manifest` is required per backend; a bundle without one cannot be read.

    The sealed roster is derived from the split manifest the fit-role artifact
    names, so a bundle that does not say where that manifest is has not described
    a promotion at all. That is exit 2 (the tool could not read the inputs), not
    exit 1 (the inputs were understood and refused) -- an operator reading `$?`
    must be sent to the bundle, not to the evidence.
    """
    staged, inputs = _bundle(tmp_path)
    bundle = json.loads(inputs.read_text(encoding="utf-8"))
    del bundle["backends"]["cpa"]["pair_manifest"]
    inputs.write_text(json.dumps(bundle), encoding="utf-8")

    result = _run(inputs, staged)

    assert result.returncode == 2, result.stderr
    assert "pair_manifest" in result.stderr
    assert "Traceback" not in result.stderr
    assert json.loads((staged / LOCK_NAME).read_text())["run_gate"]["evidence_status"] == (
        "INCOMPLETE"
    )


def test_a_malformed_lock_is_a_refusal_not_an_inputs_bundle_usage_error(tmp_path):
    """A `KeyError` from the LOCK must not be reported as a missing bundle key.

    `promote_lock_to_complete` indexes `lock["run_gate"]["evidence_status"]`, and the
    CLI used to map every `KeyError` to exit 2 with "inputs bundle is missing" -- so a
    staged lock with no `run_gate` sent the operator to the wrong file (PR #15 fable
    Minor 6). The bundle here is complete; only the lock is broken, so this must come
    back as the refusal it is.
    """
    staged, inputs = _bundle(tmp_path)
    lock_path = staged / LOCK_NAME
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    del lock["run_gate"]
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    result = _run(inputs, staged)

    assert result.returncode == 1, result.stderr
    assert "REFUSED" in result.stderr
    assert LOCK_NAME in result.stderr
    assert "inputs bundle is missing" not in result.stderr
    assert "Traceback" not in result.stderr


def test_a_harness_roster_in_the_bundle_that_disagrees_with_the_artifact_is_refused(tmp_path):
    """`training_pair_ids` in the bundle is optional; if present it must match the artifact."""
    staged, inputs = _bundle(tmp_path)
    bundle = json.loads(inputs.read_text(encoding="utf-8"))
    bundle["backends"]["cpa"]["training_pair_ids"] = ["AAA", "BBB", "CEBPE", "CEBPE_KLF1"]
    inputs.write_text(json.dumps(bundle), encoding="utf-8")

    result = _run(inputs, staged)

    assert result.returncode == 1
    assert "KLF1" in result.stderr
    assert json.loads((staged / LOCK_NAME).read_text())["run_gate"]["evidence_status"] == (
        "INCOMPLETE"
    )


def _run_reclaim(inputs, staged):
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            "reclaim-unbound",
            "--inputs",
            str(inputs),
            "--evidence-dir",
            str(staged),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def test_reclaim_unbound_subcommand_exit_codes(tmp_path):
    """0 when it reclaims a crashed publish's leftover, 1 when it refuses.

    The operator reads `$?`, not the prose. A sidecar left under an INCOMPLETE
    lock is what a publish that died between the write-once sidecars and the
    final lock rename leaves behind, and reclaiming it must report success; the
    same command against the COMPLETE lock the next run publishes must refuse,
    and a refusal that exited 0 would leave the operator believing a published
    evidence directory had just been cleaned up.
    """
    staged, inputs = _bundle(tmp_path)
    leftover = staged / "cpa_smoke_pair_roster.json"
    leftover.write_text("{}\n", encoding="utf-8")

    reclaimed = _run_reclaim(inputs, staged)

    assert reclaimed.returncode == 0, reclaimed.stderr
    assert "cpa_smoke_pair_roster.json" in reclaimed.stdout
    assert not leftover.exists()

    assert _run(inputs, staged).returncode == 0, "the reclaimed name must be free again"
    published = _snapshot(staged)

    refused = _run_reclaim(inputs, staged)

    assert refused.returncode == 1, refused.stdout
    assert "REFUSED" in refused.stderr
    assert "COMPLETE" in refused.stderr
    # The refusal must speak of THIS command: the promotion guard fires first, and
    # without the prefix its message says "promoting" to an operator who ran
    # reclaim-unbound (2026-09-10 whole-branch review, Minor 4).
    assert "reclaim-unbound:" in refused.stderr, refused.stderr
    assert _snapshot(staged) == published
