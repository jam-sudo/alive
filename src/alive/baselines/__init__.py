"""Preregistered UQ comparators for the ALIVE CARTOGRAPHER Trust-Gate MVP.

Public API
----------
NearestFeatureDistance
    Score = distance to the single nearest reference feature (k=1 R1).
EnsembleDisagreement
    Score = spread of ensemble member means (mean pairwise Euclidean distance).
RidgeErrorRegressor
    Ridge regression of ref_errors on features; score = predicted error.
GbmErrorRegressor
    Gradient boosting regression of ref_errors on features; score = predicted error.
ResidualOnly
    Mandatory ablation: R4 component alone (ECDF-normalized local residual).
"""

from alive.baselines.uq import (
    EnsembleDisagreement,
    GbmErrorRegressor,
    NearestFeatureDistance,
    ResidualOnly,
    RidgeErrorRegressor,
)

__all__ = [
    "EnsembleDisagreement",
    "GbmErrorRegressor",
    "NearestFeatureDistance",
    "ResidualOnly",
    "RidgeErrorRegressor",
]
