"""Population-distance machinery for the ALIVE Trust-Gate MVP.

Public names
------------
DistanceError
    Raised for insufficient cells or invalid inputs.
energy_distance
    Székely energy distance (V-statistic, blocked).
sliced_wasserstein
    Sliced Wasserstein-1 (diagnostic).
equal_cell_sample
    Deterministic equal-cell subsampler.
repeated_energy_distance
    Repeat-averaged, equal-cell energy distance (primary risk metric).
self_distance_floor
    Half-split noise-floor estimator (reliability diagnostic).
"""

from alive.metrics.distance import (
    DistanceError,
    energy_distance,
    equal_cell_sample,
    repeated_energy_distance,
    self_distance_floor,
    sliced_wasserstein,
)

__all__ = [
    "DistanceError",
    "energy_distance",
    "sliced_wasserstein",
    "equal_cell_sample",
    "repeated_energy_distance",
    "self_distance_floor",
]
