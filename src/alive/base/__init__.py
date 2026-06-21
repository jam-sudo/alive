"""Frozen additive ridge base predictor with paired bootstrap ensemble.

This subpackage implements the base (additive-ridge) model used by the
ALIVE CARTOGRAPHER Trust-Gate MVP.  The base predictor is fit exclusively on
``base_train`` perturbations + controls and is frozen before any
method-development error is computed.

Public API
----------
BaseModelError
    Raised for invalid fit inputs.
BasePredictor
    Frozen dataclass holding the fitted weights, ensemble, and control population.
fit_base_predictor
    Builder that fits the ridge model with CV alpha selection and paired bootstrap.
"""

from alive.base.predictor import BaseModelError, BasePredictor, fit_base_predictor

__all__ = [
    "BaseModelError",
    "BasePredictor",
    "fit_base_predictor",
]
