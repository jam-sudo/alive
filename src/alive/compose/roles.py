"""Canonical COMPOSE pair-role vocabulary.

This module is intentionally dependency-free so every controller, verifier,
and isolated worker can share one exact role roster without importing the
split-construction implementation or its filesystem and NumPy dependencies.
"""

from __future__ import annotations

__all__ = [
    "CALIBRATION_ROLE_NAME",
    "ROLE_NAMES",
    "SEALED_DOUBLE_UNSEEN_ROLE_NAME",
    "SEALED_ROLE_NAMES",
    "SEALED_SINGLE_UNSEEN_ROLE_NAME",
]

CALIBRATION_ROLE_NAME = "combo_calibration"
SEALED_DOUBLE_UNSEEN_ROLE_NAME = "sealed_double_unseen"
SEALED_SINGLE_UNSEEN_ROLE_NAME = "sealed_single_unseen"

# Manifest role keys, emitted in this fixed order.
ROLE_NAMES = (
    CALIBRATION_ROLE_NAME,
    SEALED_DOUBLE_UNSEEN_ROLE_NAME,
    SEALED_SINGLE_UNSEEN_ROLE_NAME,
)

# Exact sealed outcome roster. Keep this semantic roster explicit rather than
# deriving it positionally from ROLE_NAMES: a future non-sealed role must not
# become sealed merely because it was appended to the manifest.
SEALED_ROLE_NAMES = (
    SEALED_DOUBLE_UNSEEN_ROLE_NAME,
    SEALED_SINGLE_UNSEEN_ROLE_NAME,
)
