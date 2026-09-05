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


def _bundle(tmp_path, *, overlap=False):
    """A self-contained inputs bundle: staged evidence dir + files + inputs.json."""
    staged = tmp_path / "compose"
    shutil.copytree(EVIDENCE, staged)

    backends = {}
    for backend in ("gears", "cpa"):
        objects = {}
        for index, name in enumerate(ARTIFACT_NAMES):
            blob = tmp_path / backend / f"{name}.bin"
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_bytes(f"{backend}-{name}-{index}".encode())
            objects[name] = {
                "path": str(blob),
                "uri": f"s3://alive-compose-evidence/{backend}/{name}",
                "immutable_version": f"v{index}Ab9",
            }
        training = ["A+B", "W+X"] if (overlap and backend == "gears") else ["A+B", "C+D"]
        backends[backend] = {
            "training_pair_ids": training,
            "sealed_pair_ids": ["W+X", "Y+Z"],
            "exit_code": 0,
            "artifacts": objects,
        }

    wheelhouse = {}
    for env_name in ("gears_env", "cpa_env"):
        lock = staged / f"requirements.{env_name}.lock"
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


def test_a_lock_that_fails_validation_does_not_replace_the_committed_one(tmp_path):
    """Write-then-validate would leave a broken lock behind on failure.

    `container_image_digest` is checked by the validator, not by promotion, so a
    malformed one gets all the way to the written file. If the tool overwrites the
    committed lock and only then discovers it does not validate, the evidence
    directory is left holding a lock nobody can use and the next operator inherits
    it. Validate first, replace second.
    """
    staged, inputs = _bundle(tmp_path)
    bundle = json.loads(inputs.read_text(encoding="utf-8"))
    bundle["container_image_digest"] = "latest"  # a tag is not a digest
    inputs.write_text(json.dumps(bundle), encoding="utf-8")
    before = (staged / LOCK_NAME).read_bytes()

    result = _run(inputs, staged)

    assert result.returncode != 0
    assert (staged / LOCK_NAME).read_bytes() == before


def test_a_failed_validation_leaves_no_candidate_file_behind(tmp_path):
    """The evidence directory is left as it was found, not littered.

    A `.candidate` left in place is a half-written lock sitting next to the real
    one, and the next reader has to know which is which.
    """
    staged, inputs = _bundle(tmp_path)
    bundle = json.loads(inputs.read_text(encoding="utf-8"))
    bundle["container_image_digest"] = "latest"
    inputs.write_text(json.dumps(bundle), encoding="utf-8")

    assert _run(inputs, staged).returncode != 0
    assert list(staged.glob("*.candidate")) == []
