"""Synthetic R1 algebra checks, not a public GEARS or admission proof."""

from itertools import product

import numpy as np
import pytest

from alive.compose.fit_role import (
    FitRoleArtifactError,
    apply_response_projection,
    canonical_gene_order_sha256,
)


@pytest.fixture
def projection_case():
    # B is outside the response HVGs; its large value must not renormalize A/C.
    genes = ["A", "B", "C"]
    block = {
        "gene_order_sha256": canonical_gene_order_sha256(genes),
        "hvg_gene_ids": ["A", "C"],
        "median_library": 10000.0,
        "pca_mean": [2.0, -3.0],
        "pca_components": [[0.0, 1.0], [-1.0, 0.0]],
    }
    rows = np.array([[-2.0, 100.0, 1.0], [4.0, 200.0, 3.0]])
    return genes, block, rows


def _project(genes, block, rows):
    return apply_response_projection(block, rows, genes, representation="log_normalized_pseudobulk")


def test_log_projection_known_answer_preserves_signed_values_and_nonzero_center(projection_case):
    genes, block, rows = projection_case
    observed = _project(genes, block, rows)
    assert np.array_equal(observed, [[4.0, 4.0], [6.0, -2.0]])
    clipped = _project(genes, block, np.maximum(rows, 0.0))
    assert not np.array_equal(observed, clipped)


def test_log_projection_commutes_with_same_weighted_rows_not_different_controls(projection_case):
    genes, block, rows = projection_case
    projected = _project(genes, block, rows)
    weights = np.array([0.25, 0.75])
    left = _project(genes, block, (weights @ rows)[None, :])[0]
    right = weights @ projected
    assert np.array_equal(left, [5.5, -0.5])
    assert np.array_equal(left, right)
    assert not np.array_equal(left, projected.mean(axis=0))


@pytest.mark.parametrize("draw_count", [1, 2, 3])
@pytest.mark.parametrize("response_dim", [1, 2])
@pytest.mark.parametrize("constant", [False, True])
def test_conditional_sampling_formula_matches_all_replacement_draws(
    projection_case, draw_count, response_dim, constant
):
    genes, block, rows = projection_case
    if constant:
        rows = np.repeat(rows[:1], 2, axis=0)
    outputs = _project(genes, block, rows)[:, :response_dim]
    reference = outputs.mean(axis=0)
    # Use the selected response coordinates, not the full PCA dimension.
    formula = float(np.square(outputs - reference).sum()) / (
        len(outputs) * draw_count * response_dim
    )
    errors = []
    for indices in product(range(len(outputs)), repeat=draw_count):
        sample_mean = outputs[list(indices)].mean(axis=0)
        errors.append(float(np.square(sample_mean - reference).mean()))
    enumerated = float(np.mean(errors))
    expected = 0.0 if constant else (1.0 if response_dim == 1 else 5.0) / draw_count
    # Fixture arithmetic tolerance only; not a scientific admission threshold.
    assert abs(formula - expected) < 1e-12
    assert abs(enumerated - expected) < 1e-12


@pytest.mark.parametrize("fault", ["gene_order", "missing_hvg", "nan", "inf"])
def test_log_projection_rejects_identity_and_nonfinite_inputs(projection_case, fault):
    genes, block, rows = projection_case
    if fault == "gene_order":
        genes = genes[::-1]
    elif fault == "missing_hvg":
        block["hvg_gene_ids"] = ["A", "MISSING"]
    else:
        rows[0, 0] = np.nan if fault == "nan" else np.inf
    caught = None
    try:
        _project(genes, block, rows)
    except FitRoleArtifactError as error:
        caught = error
    assert caught is not None, f"log projection accepted {fault}"
