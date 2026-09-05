"""Producer for the dev-pod smoke evidence the committed validator already demands.

`alive.compose.activation_evidence` validates this evidence strictly but nothing
produces it, so the dependency lock has been `activation=BLOCKED` /
`evidence_status=INCOMPLETE` with every `required_evidence` field null. Filling
those by hand on the pod is how a measurement and its record drift apart -- this
repository's dominant defect. These tests drive a producer that derives both
sides of every cross-check from one computation.
"""

from __future__ import annotations

import json

import pytest

from alive.compose.activation_evidence import (
    ActivationEvidenceError,
    _validate_pair_roster_manifest,
)
from alive.compose.smoke_evidence import build_smoke_pair_roster


def _write(tmp_path, payload):
    path = tmp_path / "roster.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_emitted_roster_and_record_are_accepted_by_the_committed_validator(tmp_path):
    """One call emits both sides, so the validator's cross-checks cannot disagree.

    `_validate_pair_roster_manifest` requires the record's
    `training_pair_roster_sha256` / `sealed_pair_roster_sha256` /
    `sealed_pair_overlap_count` to match the manifest it is handed. Producing the
    two separately means getting the same thing right twice; producing them from
    one computation makes the cross-check true by construction.
    """
    roster, record = build_smoke_pair_roster(
        backend="gears",
        training_pair_ids=["A+B", "C+D"],
        sealed_pair_ids=["W+X", "Y+Z"],
    )
    _validate_pair_roster_manifest(_write(tmp_path, roster), backend="gears", record=record)


def test_the_roster_is_canonicalised_sorted_and_unique(tmp_path):
    """Task 0.1 requires canonical sorted unique rosters; the caller must not have to.

    The validator refuses `values != sorted(set(values))`. Normalising here rather
    than at every call site means one place can be wrong instead of many, and the
    hashes in the record are taken from the SAME normalised list the manifest
    carries.
    """
    roster, record = build_smoke_pair_roster(
        backend="cpa",
        training_pair_ids=["C+D", "A+B", "C+D"],
        sealed_pair_ids=["Y+Z", "W+X", "W+X"],
    )
    assert roster["training_pair_ids"] == ["A+B", "C+D"]
    assert roster["sealed_pair_ids"] == ["W+X", "Y+Z"]
    _validate_pair_roster_manifest(_write(tmp_path, roster), backend="cpa", record=record)


def test_a_sealed_pair_in_the_training_roster_fails_closed(tmp_path):
    """Task 0.1's named acceptance condition: one sealed pair in training refuses.

    The producer must REPORT the overlap, never launder it. A "helpful"
    implementation that silently dropped overlapping pairs from the training
    roster would hand the validator a clean roster while the smoke had in fact
    fitted on a sealed pair -- evidence that certifies the opposite of what
    happened. That mutation is what this test exists to kill.
    """
    roster, record = build_smoke_pair_roster(
        backend="gears",
        training_pair_ids=["A+B", "W+X"],
        sealed_pair_ids=["W+X", "Y+Z"],
    )
    assert record["sealed_pair_overlap_count"] == 1
    assert "W+X" in roster["training_pair_ids"]
    with pytest.raises(ActivationEvidenceError, match="overlaps sealed pairs"):
        _validate_pair_roster_manifest(_write(tmp_path, roster), backend="gears", record=record)
