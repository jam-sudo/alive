"""Tests for the gene->protein-sequence mapping logic (A100 prep, step 4).

The pure classification + map-assembly logic is tested here; the live UniProt
fetch is a thin urllib wrapper in ``scripts/fetch_sequences.py``.  The output
JSON encodes the SAME 0/1/>1 convention that ``build_feature_bank`` re-classifies
(0 = missing, 1 = usable, >1 = ambiguous), so it is a single source of truth.
"""

from __future__ import annotations

from alive.data.sequences import build_sequence_map, parse_uniprot_results


def test_parse_uniprot_results_extracts_accession_and_sequence() -> None:
    raw = {
        "results": [
            {"primaryAccession": "P0CG48", "sequence": {"value": "MQIFVK"}},
            {"primaryAccession": "Q99999", "sequence": {"value": "MAAAA"}},
        ]
    }
    entries = parse_uniprot_results(raw)
    assert entries == [
        {"accession": "P0CG48", "sequence": "MQIFVK"},
        {"accession": "Q99999", "sequence": "MAAAA"},
    ]


def test_build_sequence_map_applies_exactly_one_rule() -> None:
    per_gene = {
        "AARS": [{"accession": "P49588", "sequence": "MAAA"}],  # usable (exactly one)
        "GHOST": [],  # missing (zero)
        "DUP": [
            {"accession": "P1", "sequence": "MBBB"},
            {"accession": "P2", "sequence": "MCCC"},
        ],  # ambiguous (>1)
    }
    res = build_sequence_map(per_gene)
    # mapping encodes the 0/1/>1 convention verbatim
    assert res.mapping["AARS"] == ["MAAA"]
    assert res.mapping["GHOST"] == []
    assert res.mapping["DUP"] == ["MBBB", "MCCC"]
    assert res.n_usable == 1
    assert res.n_missing == 1
    assert res.n_ambiguous == 1
    assert res.exclusions["GHOST"] == "missing sequence"
    assert res.exclusions["DUP"] == "ambiguous mapping"
    assert "AARS" not in res.exclusions


def test_build_sequence_map_empty() -> None:
    res = build_sequence_map({})
    assert res.mapping == {}
    assert res.n_usable == res.n_missing == res.n_ambiguous == 0
