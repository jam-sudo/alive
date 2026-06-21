"""Shared dataclasses and enumerations used across the ALIVE pipeline.

All public types defined here are forward-compatible stubs; later tasks add
predictor, metric, and outcome-store logic on top without touching this module.

Examples
--------
>>> from alive.types import Verdict, Query
>>> import numpy as np
>>> q = Query(perturbation_id="TP53", features=np.zeros(1280))
>>> Verdict.GATE_WINS
<Verdict.GATE_WINS: 'GATE_WINS'>
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class Verdict(str, Enum):
    """Outcome categories emitted by the Trust-Gate evaluation logic.

    Members
    -------
    INVALID_EVALUATION
        The evaluation could not be completed (insufficient data, preprocessing failure, etc.).
    CALIBRATION_FAILURE
        Conformal calibration did not meet coverage requirements.
    GATE_WINS
        The candidate method clears the Trust-Gate (positive primary metric result, CI above 0).
    NO_DISTINCT_WIN
        Evaluation completed but no method achieved a statistically distinct win.
    """

    INVALID_EVALUATION = "INVALID_EVALUATION"
    CALIBRATION_FAILURE = "CALIBRATION_FAILURE"
    GATE_WINS = "GATE_WINS"
    NO_DISTINCT_WIN = "NO_DISTINCT_WIN"


class OperationalStatus(str, Enum):
    """High-level pipeline operational status returned after each decision cycle.

    Members
    -------
    CONTINUE_CONFIRMATORY
        Futility check passed; proceed to confirmatory evaluation.
    FUTILITY_STOPPED
        Futility rule triggered; pipeline halted before sealed evaluation.
    """

    CONTINUE_CONFIRMATORY = "CONTINUE_CONFIRMATORY"
    FUTILITY_STOPPED = "FUTILITY_STOPPED"


@dataclass(frozen=True)
class Query:
    """A single perturbation query carrying its standardized feature vector.

    Parameters
    ----------
    perturbation_id : str
        Stable identifier for the CRISPRi target gene (e.g. HGNC symbol).
    features : np.ndarray
        1-D array of standardized perturbation features (e.g. ESM-2 mean-pool
        embedding after z-score normalization over the base-train split).

    Notes
    -----
    ``features`` is expected to be 1-D; the caller is responsible for ensuring
    shape correctness before constructing a Query.
    """

    perturbation_id: str
    features: np.ndarray


@dataclass(frozen=True)
class PopulationRef:
    """Lightweight handle to a cell population; actual matrices are loaded lazily.

    Parameters
    ----------
    perturbation_id : str
        Stable identifier for the CRISPRi target gene.
    split : str
        Name of the data split this population belongs to (e.g. ``"base_train"``).
    n_cells : int
        Number of cells in the referenced population after sampling/capping.

    Notes
    -----
    The outcome store (Task 5) resolves this handle to actual cell matrices.
    No array data is stored here to keep serialization lightweight.
    """

    perturbation_id: str
    split: str
    n_cells: int


@dataclass(frozen=True)
class BasePrediction:
    """Output of the base (additive-ridge) model for one perturbation.

    Parameters
    ----------
    perturbation_id : str
        Stable identifier for the CRISPRi target gene.
    predicted_cells : np.ndarray
        Array of shape ``(n_cells, pca_dims)`` representing the translated-control
        prediction in response space (PCA coordinates).
    ensemble_member_means : np.ndarray or None
        Array of shape ``(n_members, pca_dims)`` containing per-member ensemble
        means, filled in by Task 9.  ``None`` when the ensemble has not yet been
        computed.
    """

    perturbation_id: str
    predicted_cells: np.ndarray
    ensemble_member_means: np.ndarray | None = None
