"""Trust-gate scorers for the ALIVE CARTOGRAPHER Trust-Gate MVP.

Public API
----------
GateError
    Raised for invalid gate configuration (w<=0, k out of range, etc.).
feature_knn_mean_distance
    Mean Euclidean distance to k nearest reference features.
local_residual
    Median error over k nearest reference items.
ecdf_normalize
    ECDF-rank normalization: fraction of reference <= value.
TrustGate
    Full trust gate: R1 (feature-kNN) + R4 (local-residual), ECDF-normalized.
"""

from alive.gate.recoverability import (
    GateError,
    TrustGate,
    ecdf_normalize,
    feature_knn_mean_distance,
    local_residual,
)

__all__ = [
    "GateError",
    "TrustGate",
    "ecdf_normalize",
    "feature_knn_mean_distance",
    "local_residual",
]
