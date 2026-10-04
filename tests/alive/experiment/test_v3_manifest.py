"""Forged-manifest tests for the CART-K562-V3.1 intake validator (synthetic metadata only)."""

from __future__ import annotations

import copy
import re

import pytest

from alive.experiment.v3_manifest import validate_intake_manifest

ROSTER = {
    "targets": [
        {"target": "AARS", "gwps_guide_ids": ["AARS_a", "AARS_b"]},
        {"target": "NOL12", "gwps_guide_ids": ["NOL12_a"]},
    ]
}
KW = {
    "protocol_id": "CART-K562-V3.1",
    "roster_sha256": "r" * 64,
    "cell_line": "K562",
    "min_units": 2,
}


def _valid():
    return {
        "protocol_id": "CART-K562-V3.1",
        "roster_sha256": "r" * 64,
        "cell_line": {"name": "K562", "authentication_id": "STR-001"},
        "transductions": [
            {
                "transduction_id": "TD1",
                "culture_id": "CUL-A",
                "transduction_date": "2026-11-02",
                "virus_lot": "V1",
            },
            {
                "transduction_id": "TD2",
                "culture_id": "CUL-B",
                "transduction_date": "2026-11-09",
                "virus_lot": "V2",
            },
        ],
        "libraries": [
            {"library_id": "L1", "transduction_id": "TD1", "lane_id": "chip1-ch1"},
            {"library_id": "L2", "transduction_id": "TD2", "lane_id": "chip1-ch2"},
        ],
        "guides": [
            {"guide_id": "AARS_a", "target": "AARS"},
            {"guide_id": "AARS_b", "target": "AARS"},
            {"guide_id": "NOL12_a", "target": "NOL12"},
            {"guide_id": "NT_1", "target": "non-targeting"},
        ],
    }


def _forge(path, value):
    m = copy.deepcopy(_valid())
    node = m
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return m


def test_valid_manifest_passes():
    validate_intake_manifest(_valid(), ROSTER, **KW)


@pytest.mark.parametrize(
    ("forged", "message"),
    [
        (_forge(("transductions", 1, "culture_id"), "CUL-A"), "culture shared"),
        (_forge(("libraries", 1, "lane_id"), "chip1-ch1"), "10x lane used by more than one"),
        (_forge(("libraries", 1, "transduction_id"), "TD1"), "transductions without a library"),
        (_forge(("libraries", 1, "transduction_id"), "TD9"), "unknown transductions"),
        (_forge(("transductions", 1, "transduction_id"), "TD1"), "duplicate transduction_id"),
        (_forge(("transductions",), _valid()["transductions"][:1]), "< registered 2"),
        (_forge(("transductions", 0, "virus_lot"), " "), "missing/blank ['virus_lot']"),
        (_forge(("guides", 2, "target"), "AARS"), "wrong target"),
        (_forge(("guides",), _valid()["guides"][1:]), "roster guides missing"),
        (_forge(("guides", 3, "target"), "ACTB"), "outside the roster"),
        (_forge(("roster_sha256",), "x" * 64), "roster_sha256"),
        (_forge(("cell_line", "name"), "HEK293T"), "cell_line"),
        (_forge(("cell_line", "authentication_id"), ""), "cell_line"),
        (_forge(("protocol_id",), "CART-K562-V3"), "protocol_id"),
    ],
)
def test_forged_manifest_is_rejected(forged, message):
    with pytest.raises(ValueError, match=r"(?s)" + re.escape(message)):
        validate_intake_manifest(forged, ROSTER, **KW)


def test_missing_non_targeting_controls_rejected():
    m = _valid()
    m["guides"] = m["guides"][:3]
    with pytest.raises(ValueError, match="non-targeting"):
        validate_intake_manifest(m, ROSTER, **KW)


def test_all_problems_are_reported_together():
    m = _forge(("transductions", 1, "culture_id"), "CUL-A")
    m["libraries"][1]["lane_id"] = "chip1-ch1"
    with pytest.raises(ValueError) as e:
        validate_intake_manifest(m, ROSTER, **KW)
    assert "culture shared" in str(e.value) and "10x lane" in str(e.value)
