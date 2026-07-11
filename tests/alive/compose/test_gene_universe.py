"""Contract tests for the outcome-free, exact-size GEARS gene roster."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from scipy import sparse

from alive.compose.fit_role import canonical_gene_order_sha256
from alive.compose.gene_universe import (
    AliasMap,
    GeneUniverseError,
    assert_gears_roster_matches,
    compute_mandatory_report,
    generate_gears_gene_roster,
    load_gears_gene_roster,
    normalize_full_then_subset,
)
from alive.provenance import sha256_file, sha256_json

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64


def _write_alias(tmp_path: Path, aliases: list[dict[str, str]] | None = None) -> AliasMap:
    payload = {"aliases": aliases or [], "schema": "compose_gene_aliases_v1"}
    path = tmp_path / "aliases.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return AliasMap.load(path, expected_sha256=sha256_file(path))


def _projection(genes: list[str], *, hvg: list[str], median: float = 100.0) -> dict:
    return {
        "gene_order_sha256": canonical_gene_order_sha256(genes),
        "hvg_gene_ids": hvg,
        "median_library": median,
        "raw_data_sha256": "raw-source-v1",
        "response_artifact_sha256": _SHA_B,
    }


def _report(
    tmp_path: Path,
    *,
    genes: list[str] | None = None,
    hvg: list[str] | None = None,
    candidates: list[str] | None = None,
    gene2go: set[str] | None = None,
    alias: AliasMap | None = None,
):
    full = genes or ["A", "B", "C", "D", "E", "F"]
    projection = _projection(full, hvg=hvg or ["B", "E"])
    return compute_mandatory_report(
        full_var=full,
        fit_artifact_identity={
            "content_manifest_sha256": _SHA_A,
            "gene_order_sha256": canonical_gene_order_sha256(full),
            "raw_data_sha256": "raw-source-v1",
        },
        response_projection=projection,
        perturbation_candidates=candidates or ["A", "C_D", "MISSING"],
        gene2go=gene2go or {"A", "C", "D"},
        gene2go_sha256=_SHA_C,
        alias=alias or _write_alias(tmp_path),
    )


def test_mandatory_report_is_exact_and_records_exclusions(tmp_path):
    report = _report(tmp_path)

    assert report.response_hvg_ids == ("B", "E")
    assert report.eligible_perturbation_genes == ("A", "C", "D")
    assert report.mandatory_genes == ("A", "B", "C", "D", "E")
    assert report.mandatory_size == 5
    assert (report.n_candidates, report.n_eligible, report.n_excluded) == (3, 2, 1)
    assert [item.to_dict() for item in report.eligibility_exclusions] == [
        {
            "canonical_gene": "MISSING",
            "gene": "MISSING",
            "reason": "absent_from_full_var",
            "token": "MISSING",
        }
    ]
    assert report.response_hvg_perturbation_overlap == 0
    assert report.response_hvg_sha256 == sha256_json(["B", "E"])


def test_alias_is_applied_to_candidates_but_full_var_must_already_be_canonical(tmp_path):
    alias = _write_alias(
        tmp_path,
        [
            {
                "canonical_symbol": "MAP3K21",
                "raw_symbol": "KIAA1804",
                "reason": "registered legacy symbol",
                "source": "project registry",
                "version": "v1",
            }
        ],
    )
    genes = ["A", "MAP3K21", "Z"]
    report = _report(
        tmp_path,
        genes=genes,
        hvg=["Z"],
        candidates=["KIAA1804"],
        gene2go={"MAP3K21"},
        alias=alias,
    )
    assert report.eligible_perturbation_genes == ("MAP3K21",)
    assert report.mandatory_genes == ("MAP3K21", "Z")

    with pytest.raises(GeneUniverseError, match="non-canonical alias"):
        _report(
            tmp_path,
            genes=["A", "KIAA1804", "Z"],
            hvg=["Z"],
            candidates=["KIAA1804"],
            gene2go={"MAP3K21"},
            alias=alias,
        )


def test_alias_file_digest_and_structure_fail_closed(tmp_path):
    path = tmp_path / "aliases.json"
    path.write_text('{"aliases": [], "schema": "compose_gene_aliases_v1"}\n')
    with pytest.raises(GeneUniverseError, match="SHA-256 mismatch"):
        AliasMap.load(path, expected_sha256=_SHA_A)

    duplicate = {
        "aliases": [
            {
                "canonical_symbol": "B",
                "raw_symbol": "A",
                "reason": "r1",
                "source": "s",
                "version": "v",
            },
            {
                "canonical_symbol": "C",
                "raw_symbol": "A",
                "reason": "r2",
                "source": "s",
                "version": "v",
            },
        ],
        "schema": "compose_gene_aliases_v1",
    }
    path.write_text(json.dumps(duplicate))
    with pytest.raises(GeneUniverseError, match="duplicate raw"):
        AliasMap.load(path, expected_sha256=sha256_file(path))

    duplicate["aliases"][1]["raw_symbol"] = "D"
    duplicate["aliases"][1]["canonical_symbol"] = "B"
    path.write_text(json.dumps(duplicate))
    synonyms = AliasMap.load(path, expected_sha256=sha256_file(path))
    assert synonyms.canonicalize("A") == synonyms.canonicalize("D") == "B"

    symlink = tmp_path / "aliases-link.json"
    symlink.symlink_to(path)
    with pytest.raises(GeneUniverseError, match="open alias artifact safely"):
        AliasMap.load(symlink, expected_sha256=sha256_file(path))


def test_report_rejects_response_and_source_lineage_mismatch(tmp_path):
    genes = ["A", "B", "C"]
    projection = _projection(genes, hvg=["B"])
    projection["raw_data_sha256"] = "wrong"
    with pytest.raises(GeneUniverseError, match="raw-data identity"):
        compute_mandatory_report(
            full_var=genes,
            fit_artifact_identity={
                "content_manifest_sha256": _SHA_A,
                "gene_order_sha256": canonical_gene_order_sha256(genes),
                "raw_data_sha256": "raw-source-v1",
            },
            response_projection=projection,
            perturbation_candidates=["A"],
            gene2go={"A"},
            gene2go_sha256=_SHA_C,
            alias=_write_alias(tmp_path),
        )


def test_report_rejects_non_string_genes_and_duplicate_gene2go_nodes(tmp_path):
    with pytest.raises(GeneUniverseError, match="string gene IDs"):
        _report(tmp_path, genes=["A", 2, "C"])
    with pytest.raises(GeneUniverseError, match="gene roster must be unique"):
        compute_mandatory_report(
            full_var=["A", "B", "C"],
            fit_artifact_identity={
                "content_manifest_sha256": _SHA_A,
                "gene_order_sha256": canonical_gene_order_sha256(["A", "B", "C"]),
                "raw_data_sha256": "raw-source-v1",
            },
            response_projection=_projection(["A", "B", "C"], hvg=["B"]),
            perturbation_candidates=["A"],
            gene2go=["A", "A"],
            gene2go_sha256=_SHA_C,
            alias=_write_alias(tmp_path),
        )


def test_exact_size_fill_uses_control_variance_and_full_var_order(tmp_path):
    genes = ["A", "B", "C", "D"]
    report = _report(
        tmp_path,
        genes=genes,
        hvg=["B"],
        candidates=["A"],
        gene2go={"A"},
    )
    counts = np.array([[10, 0, 0, 0], [10, 0, 0, 10]], dtype=np.float64)
    artifact = generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=counts,
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=3,
    )

    assert artifact.mandatory_genes == ("A", "B")
    assert artifact.ordered_roster == ("A", "B", "D")
    assert artifact.fill_count == 1
    assert artifact.ordered_roster_sha256 == sha256_json(["A", "B", "D"])

    sparse_artifact = generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=sparse.csr_matrix(counts),
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=3,
    )
    assert sparse_artifact == artifact


def test_exact_size_guards_and_response_hvg_coverage(tmp_path):
    report = _report(tmp_path)
    counts = sparse.csr_matrix(np.ones((2, 6), dtype=np.float64))
    with pytest.raises(GeneUniverseError, match="exceeds n_target"):
        generate_gears_gene_roster(
            mandatory_report=report,
            control_counts_full=counts,
            control_row_identity_sha256=_SHA_D,
            generator_code_sha256=_SHA_A,
            n_target=4,
        )
    with pytest.raises(GeneUniverseError, match="exceeds the full"):
        generate_gears_gene_roster(
            mandatory_report=report,
            control_counts_full=counts,
            control_row_identity_sha256=_SHA_D,
            generator_code_sha256=_SHA_A,
            n_target=7,
        )


def test_roster_write_load_is_idempotent_and_tamper_evident(tmp_path):
    report = _report(tmp_path)
    artifact_path = tmp_path / "roster.json"
    artifact = generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=sparse.csr_matrix(np.ones((2, 6))),
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=6,
        out_path=artifact_path,
    )
    artifact.write(artifact_path)
    loaded = load_gears_gene_roster(artifact_path, expected_file_sha256=sha256_file(artifact_path))
    assert loaded == artifact
    with pytest.raises(TypeError):
        load_gears_gene_roster(artifact_path)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        loaded.provenance["n_target"] = 999
    assert_gears_roster_matches(artifact.ordered_roster, loaded)
    with pytest.raises(GeneUniverseError, match="differs"):
        assert_gears_roster_matches(tuple(reversed(artifact.ordered_roster)), loaded)

    payload = json.loads(artifact_path.read_text())
    payload["ordered_roster"][0] = "TAMPERED"
    artifact_path.write_text(json.dumps(payload))
    with pytest.raises(GeneUniverseError, match="checksum"):
        load_gears_gene_roster(artifact_path, expected_file_sha256=sha256_file(artifact_path))


def test_roster_loader_rejects_symlink_and_noncanonical_equivalent_json(tmp_path):
    report = _report(tmp_path)
    artifact_path = tmp_path / "roster.json"
    artifact = generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=np.ones((2, 6)),
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=6,
        out_path=artifact_path,
    )
    symlink = tmp_path / "roster-link.json"
    symlink.symlink_to(artifact_path)
    with pytest.raises(GeneUniverseError, match="open GEARS roster artifact safely"):
        load_gears_gene_roster(symlink, expected_file_sha256=sha256_file(artifact_path))

    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(json.dumps(artifact.to_dict()), encoding="utf-8")
    with pytest.raises(GeneUniverseError, match="not canonical JSON"):
        load_gears_gene_roster(noncanonical, expected_file_sha256=sha256_file(noncanonical))


def test_roster_loader_rejects_string_that_masquerades_as_gene_list(tmp_path):
    artifact_path = tmp_path / "roster.json"
    artifact = generate_gears_gene_roster(
        mandatory_report=_report(tmp_path),
        control_counts_full=np.ones((2, 6)),
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=6,
        out_path=artifact_path,
    )
    payload = artifact.to_dict()
    payload["ordered_roster"] = "".join(payload["ordered_roster"])
    core = {key: value for key, value in payload.items() if key != "artifact_checksum"}
    payload["artifact_checksum"] = sha256_json(core)
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(GeneUniverseError, match="ordered_roster must be a list"):
        load_gears_gene_roster(artifact_path, expected_file_sha256=sha256_file(artifact_path))


def test_normalize_full_then_subset_preserves_full_library_basis(tmp_path):
    genes = ["A", "B", "C"]
    report = _report(
        tmp_path,
        genes=genes,
        hvg=["A"],
        candidates=["B"],
        gene2go={"B"},
    )
    projection = _projection(genes, hvg=["A"], median=100.0)
    artifact = generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=np.array([[10, 90, 0], [10, 0, 90]], dtype=np.float64),
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=2,
    )
    counts = np.array([[10, 90, 0], [10, 0, 90]], dtype=np.float64)
    observed = normalize_full_then_subset(
        counts,
        full_gene_order=genes,
        response_projection=projection,
        roster=artifact,
    )
    naive_subset_first = np.log1p(
        counts[:, :2]
        * (
            100.0
            / np.where(
                counts[:, :2].sum(axis=1, keepdims=True) > 0,
                counts[:, :2].sum(axis=1, keepdims=True),
                1.0,
            )
        )
    )

    assert np.allclose(observed[:, 0], np.log1p([10.0, 10.0]))
    assert not np.allclose(observed, naive_subset_first)
    sparse_observed = normalize_full_then_subset(
        sparse.csr_matrix(counts),
        full_gene_order=genes,
        response_projection=projection,
        roster=artifact,
    )
    assert np.allclose(sparse_observed.toarray(), observed)


def test_request_roster_is_not_an_input_and_candidate_order_is_canonical(tmp_path):
    alias = _write_alias(tmp_path)
    kwargs = {
        "full_var": ["A", "B", "C"],
        "fit_artifact_identity": {
            "content_manifest_sha256": _SHA_A,
            "gene_order_sha256": canonical_gene_order_sha256(["A", "B", "C"]),
            "raw_data_sha256": "raw-source-v1",
        },
        "response_projection": _projection(["A", "B", "C"], hvg=["B"]),
        "gene2go": {"A", "C"},
        "gene2go_sha256": _SHA_C,
        "alias": alias,
    }
    first = compute_mandatory_report(perturbation_candidates=["C", "A"], **kwargs)
    second = compute_mandatory_report(perturbation_candidates=["A", "C"], **kwargs)
    assert first.to_dict() == second.to_dict()

    with pytest.raises(GeneUniverseError, match="collapse to one canonical target"):
        compute_mandatory_report(perturbation_candidates=["A_C", "C_A"], **kwargs)

    with pytest.raises(GeneUniverseError, match="self-combo"):
        compute_mandatory_report(perturbation_candidates=["A_A"], **kwargs)
    with pytest.raises(GeneUniverseError, match="control token"):
        compute_mandatory_report(perturbation_candidates=["control_A"], **kwargs)


def test_alias_canonicalization_cannot_turn_combo_into_self_combo(tmp_path):
    alias = _write_alias(
        tmp_path,
        [
            {
                "canonical_symbol": "A",
                "raw_symbol": "AOLD",
                "reason": "legacy symbol",
                "source": "registry",
                "version": "v1",
            }
        ],
    )
    with pytest.raises(GeneUniverseError, match="canonical self-combo"):
        _report(
            tmp_path,
            genes=["A", "B", "C"],
            hvg=["B"],
            candidates=["AOLD_A"],
            gene2go={"A"},
            alias=alias,
        )


def test_legacy_synonyms_are_allowed_but_duplicate_canonical_candidates_fail(tmp_path):
    alias = _write_alias(
        tmp_path,
        [
            {
                "canonical_symbol": "A",
                "raw_symbol": raw,
                "reason": "legacy synonym",
                "source": "registry",
                "version": "v1",
            }
            for raw in ("AOLD1", "AOLD2")
        ],
    )
    with pytest.raises(GeneUniverseError, match="collapse to one canonical target"):
        _report(
            tmp_path,
            genes=["A", "B", "C"],
            hvg=["B"],
            candidates=["AOLD1", "AOLD2"],
            gene2go={"A"},
            alias=alias,
        )


def test_generator_is_outcome_independent_with_sealed_store_absent(tmp_path, monkeypatch):
    """§5/§9: an identical roster with the sealed outcome store absent proves no sealed path."""
    import sys

    counts = sparse.csr_matrix(np.ones((2, 6), dtype=np.float64))
    baseline = generate_gears_gene_roster(
        mandatory_report=_report(tmp_path),
        control_counts_full=counts,
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=6,
    )
    # Any lazy import of the sealed outcome store on the generator path would now raise.
    monkeypatch.setitem(sys.modules, "alive.compose.outcome_store", None)
    guarded = generate_gears_gene_roster(
        mandatory_report=_report(tmp_path),
        control_counts_full=counts,
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=6,
    )
    assert guarded == baseline

    import alive.compose.gene_universe as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for banned in ("outcome_store", "ComposeOutcomeStore", "read_unsealed", "pair_ids"):
        assert banned not in source


def test_eligibility_excludes_gene_absent_from_gene2go(tmp_path):
    report = _report(
        tmp_path,
        genes=["A", "B", "C"],
        hvg=["B"],
        candidates=["A", "C"],  # C is measured (in full_var) but not GO-composable
        gene2go={"A"},
    )
    assert report.eligible_perturbation_genes == ("A",)
    assert [item.to_dict() for item in report.eligibility_exclusions] == [
        {"canonical_gene": "C", "gene": "C", "reason": "absent_from_gene2go", "token": "C"}
    ]
    assert (report.n_candidates, report.n_eligible, report.n_excluded) == (2, 1, 1)


def test_scientific_target_identity_is_invariant_across_rosters(tmp_path):
    """§9: different valid rosters carry the identical frozen response identity."""
    genes = ["A", "B", "C", "D", "E", "F"]
    report = _report(tmp_path, genes=genes, hvg=["B", "E"])
    counts = sparse.csr_matrix(np.ones((2, 6), dtype=np.float64))
    small = generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=counts,
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=5,
    )
    large = generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=counts,
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=6,
    )
    assert small.ordered_roster != large.ordered_roster
    assert small.response_hvg_ids == large.response_hvg_ids == ("B", "E")
    assert (
        small.provenance["response_artifact_sha256"]
        == large.provenance["response_artifact_sha256"]
        == report.response_artifact_sha256
    )
    assert (
        small.provenance["response_hvg_sha256"]
        == large.provenance["response_hvg_sha256"]
        == report.response_hvg_sha256
    )


def test_report_rejects_hvg_outside_full_var_and_misordered_hvg(tmp_path):
    genes = ["A", "B", "C"]
    base = {
        "full_var": genes,
        "fit_artifact_identity": {
            "content_manifest_sha256": _SHA_A,
            "gene_order_sha256": canonical_gene_order_sha256(genes),
            "raw_data_sha256": "raw-source-v1",
        },
        "perturbation_candidates": ["A"],
        "gene2go": {"A"},
        "gene2go_sha256": _SHA_C,
        "alias": _write_alias(tmp_path),
    }
    with pytest.raises(GeneUniverseError, match="HVG outside full_var"):
        compute_mandatory_report(response_projection=_projection(genes, hvg=["Z"]), **base)
    with pytest.raises(GeneUniverseError, match="canonical full_var order"):
        compute_mandatory_report(response_projection=_projection(genes, hvg=["C", "A"]), **base)


def test_alias_chains_and_empty_fields_fail_closed(tmp_path):
    path = tmp_path / "aliases.json"
    chain = {
        "aliases": [
            {
                "canonical_symbol": "B",
                "raw_symbol": "A",
                "reason": "r",
                "source": "s",
                "version": "v",
            },
            {
                "canonical_symbol": "C",
                "raw_symbol": "B",
                "reason": "r",
                "source": "s",
                "version": "v",
            },
        ],
        "schema": "compose_gene_aliases_v1",
    }
    path.write_text(json.dumps(chain))
    with pytest.raises(GeneUniverseError, match="chains/cycles"):
        AliasMap.load(path, expected_sha256=sha256_file(path))

    empty = {
        "aliases": [
            {
                "canonical_symbol": "",
                "raw_symbol": "A",
                "reason": "r",
                "source": "s",
                "version": "v",
            }
        ],
        "schema": "compose_gene_aliases_v1",
    }
    path.write_text(json.dumps(empty))
    with pytest.raises(GeneUniverseError, match="non-empty strings"):
        AliasMap.load(path, expected_sha256=sha256_file(path))


def test_loader_rejects_eligible_gene_absent_from_mandatory(tmp_path):
    report = _report(tmp_path)
    artifact_path = tmp_path / "roster.json"
    generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=np.ones((2, 6)),
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=6,
        out_path=artifact_path,
    )
    payload = json.loads(artifact_path.read_text())
    payload["eligible_perturbation_genes"] = ["A", "GHOST"]  # GHOST is not in mandatory/ordered
    core = {key: value for key, value in payload.items() if key != "artifact_checksum"}
    payload["artifact_checksum"] = sha256_json(core)  # self-consistent forgery
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(GeneUniverseError, match="containment"):
        load_gears_gene_roster(artifact_path, expected_file_sha256=sha256_file(artifact_path))


def test_loader_rejects_self_consistent_duplicate_exclusions(tmp_path):
    artifact_path = tmp_path / "roster.json"
    generate_gears_gene_roster(
        mandatory_report=_report(tmp_path),
        control_counts_full=np.ones((2, 6)),
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=6,
        out_path=artifact_path,
    )
    payload = json.loads(artifact_path.read_text())
    payload["eligibility_exclusions"].append(payload["eligibility_exclusions"][0])
    core = {key: value for key, value in payload.items() if key != "artifact_checksum"}
    payload["artifact_checksum"] = sha256_json(core)
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(GeneUniverseError, match="duplicated or non-canonical"):
        load_gears_gene_roster(artifact_path, expected_file_sha256=sha256_file(artifact_path))


def test_loader_and_consumer_reject_self_consistent_response_hvg_substitution(tmp_path):
    """A newly hashed artifact still cannot substitute the frozen response HVGs."""
    genes = ["A", "B", "C", "D"]
    report = _report(
        tmp_path,
        genes=genes,
        hvg=["B"],
        candidates=["A"],
        gene2go={"A"},
    )
    artifact_path = tmp_path / "roster.json"
    generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=np.array([[10, 0, 0, 0], [10, 0, 0, 10]]),
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=3,
        out_path=artifact_path,
    )
    payload = json.loads(artifact_path.read_text())
    payload["ordered_roster"] = ["A", "C", "D"]
    payload["ordered_roster_sha256"] = sha256_json(payload["ordered_roster"])
    payload["mandatory_genes"] = ["A", "C"]
    payload["response_hvg_ids"] = ["C"]
    core = {key: value for key, value in payload.items() if key != "artifact_checksum"}
    payload["artifact_checksum"] = sha256_json(core)
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(GeneUniverseError, match="response-HVG SHA-256 mismatch"):
        load_gears_gene_roster(artifact_path, expected_file_sha256=sha256_file(artifact_path))

    valid_path = tmp_path / "valid-roster.json"
    valid = generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=np.array([[10, 0, 0, 0], [10, 0, 0, 10]]),
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=3,
        out_path=valid_path,
    )
    reordered_path = tmp_path / "reordered-roster.json"
    reordered = valid.to_dict()
    reordered["mandatory_genes"] = list(reversed(reordered["mandatory_genes"]))
    reordered_core = {key: value for key, value in reordered.items() if key != "artifact_checksum"}
    reordered["artifact_checksum"] = sha256_json(reordered_core)
    reordered_path.write_text(
        json.dumps(reordered, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(GeneUniverseError, match="canonical roster order"):
        load_gears_gene_roster(reordered_path, expected_file_sha256=sha256_file(reordered_path))

    mismatched_projection = _projection(genes, hvg=["C"])
    with pytest.raises(GeneUniverseError, match="frozen response HVGs"):
        normalize_full_then_subset(
            np.ones((1, 4)),
            full_gene_order=genes,
            response_projection=mismatched_projection,
            roster=valid,
        )


def _reseal_roster(base_path, out_path, mutate):
    """Apply ``mutate`` to a roster payload and re-hash it into a self-consistent forgery."""
    payload = json.loads(base_path.read_text())
    mutate(payload)
    core = {key: value for key, value in payload.items() if key != "artifact_checksum"}
    payload["artifact_checksum"] = sha256_json(core)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path


@pytest.mark.parametrize(
    "field",
    [
        "mandatory_genes",
        "response_hvg_ids",
        "eligible_perturbation_genes",
        "eligibility_exclusions",
    ],
)
def test_roster_loader_rejects_non_list_for_each_gene_field(tmp_path, field):
    """Every list-typed roster field, not just ordered_roster, rejects a string masquerade."""
    report = _report(tmp_path)
    base_path = tmp_path / "roster.json"
    generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=np.ones((2, 6)),
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=6,
        out_path=base_path,
    )
    forged = _reseal_roster(
        base_path, tmp_path / "forged.json", lambda payload: payload.__setitem__(field, "ABCDEF")
    )
    with pytest.raises(GeneUniverseError, match=f"{field} must be a list"):
        load_gears_gene_roster(forged, expected_file_sha256=sha256_file(forged))


def test_loader_rejects_duplicate_eligible_and_nonstring_raw_data_sha(tmp_path):
    report = _report(tmp_path)
    base_path = tmp_path / "roster.json"
    generate_gears_gene_roster(
        mandatory_report=report,
        control_counts_full=np.ones((2, 6)),
        control_row_identity_sha256=_SHA_D,
        generator_code_sha256=_SHA_A,
        n_target=6,
        out_path=base_path,
    )

    def _duplicate_eligible(payload):
        payload["eligible_perturbation_genes"] = ["A", "A"]

    dup = _reseal_roster(base_path, tmp_path / "dup.json", _duplicate_eligible)
    with pytest.raises(GeneUniverseError, match="eligible_perturbation_genes are invalid"):
        load_gears_gene_roster(dup, expected_file_sha256=sha256_file(dup))

    def _nonstring_raw_data(payload):
        payload["provenance"]["raw_data_sha256"] = 123

    bad = _reseal_roster(base_path, tmp_path / "bad_raw.json", _nonstring_raw_data)
    with pytest.raises(GeneUniverseError, match="provenance identity is invalid"):
        load_gears_gene_roster(bad, expected_file_sha256=sha256_file(bad))


def test_report_rejects_empty_or_nonstring_gene2go_member(tmp_path):
    genes = ["A", "B", "C"]
    kwargs = dict(
        full_var=genes,
        fit_artifact_identity={
            "content_manifest_sha256": _SHA_A,
            "gene_order_sha256": canonical_gene_order_sha256(genes),
            "raw_data_sha256": "raw-source-v1",
        },
        response_projection=_projection(genes, hvg=["B"]),
        perturbation_candidates=["A"],
        gene2go_sha256=_SHA_C,
        alias=_write_alias(tmp_path),
    )
    with pytest.raises(GeneUniverseError, match="non-empty string gene IDs"):
        compute_mandatory_report(gene2go=["A", ""], **kwargs)
    with pytest.raises(GeneUniverseError, match="non-empty string gene IDs"):
        compute_mandatory_report(gene2go=["A", 123], **kwargs)
