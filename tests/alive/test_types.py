"""Tests for alive.types — shared dataclasses and enums.

Run with: uv run pytest -q tests/alive/test_types.py
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.types import (
    BasePrediction,
    OperationalStatus,
    PopulationRef,
    Query,
    Verdict,
)

# ---------------------------------------------------------------------------
# Enums: exact members
# ---------------------------------------------------------------------------


def test_verdict_members():
    expected = {"INVALID_EVALUATION", "CALIBRATION_FAILURE", "GATE_WINS", "NO_DISTINCT_WIN"}
    actual = {v.name for v in Verdict}
    assert actual == expected


def test_verdict_is_str_enum():
    assert isinstance(Verdict.GATE_WINS, str)
    assert Verdict.GATE_WINS == "GATE_WINS"


def test_operational_status_members():
    expected = {"CONTINUE_CONFIRMATORY", "FUTILITY_STOPPED"}
    actual = {v.name for v in OperationalStatus}
    assert actual == expected


def test_operational_status_is_str_enum():
    assert isinstance(OperationalStatus.CONTINUE_CONFIRMATORY, str)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def test_query_constructs():
    vec = np.zeros(10)
    q = Query(perturbation_id="gene_A", features=vec)
    assert q.perturbation_id == "gene_A"
    assert q.features is vec


def test_query_is_frozen():
    vec = np.zeros(10)
    q = Query(perturbation_id="gene_A", features=vec)
    with pytest.raises((AttributeError, TypeError)):
        q.perturbation_id = "other"  # type: ignore[misc]


def test_query_features_1d():
    """Features should be a 1-D ndarray (validate the contract)."""
    vec = np.ones(20)
    q = Query(perturbation_id="gene_B", features=vec)
    assert q.features.ndim == 1


# ---------------------------------------------------------------------------
# PopulationRef
# ---------------------------------------------------------------------------


def test_population_ref_constructs():
    ref = PopulationRef(perturbation_id="gene_C", split="base_train", n_cells=128)
    assert ref.perturbation_id == "gene_C"
    assert ref.split == "base_train"
    assert ref.n_cells == 128


def test_population_ref_is_frozen():
    ref = PopulationRef(perturbation_id="gene_C", split="base_train", n_cells=128)
    with pytest.raises((AttributeError, TypeError)):
        ref.n_cells = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BasePrediction
# ---------------------------------------------------------------------------


def test_base_prediction_constructs_without_ensemble():
    cells = np.zeros((96, 50))
    pred = BasePrediction(perturbation_id="gene_D", predicted_cells=cells)
    assert pred.perturbation_id == "gene_D"
    assert pred.predicted_cells.shape == (96, 50)
    assert pred.ensemble_member_means is None


def test_base_prediction_constructs_with_ensemble():
    cells = np.zeros((96, 50))
    ens = np.zeros((20, 50))
    pred = BasePrediction(
        perturbation_id="gene_D",
        predicted_cells=cells,
        ensemble_member_means=ens,
    )
    assert pred.ensemble_member_means is not None
    assert pred.ensemble_member_means.shape == (20, 50)


def test_base_prediction_is_frozen():
    cells = np.zeros((96, 50))
    pred = BasePrediction(perturbation_id="gene_D", predicted_cells=cells)
    with pytest.raises((AttributeError, TypeError)):
        pred.perturbation_id = "other"  # type: ignore[misc]
