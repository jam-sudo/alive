"""Pure descriptive event labels for frozen scalar changes."""

from numbers import Real

import numpy as np

from alive.metrics.selective import MetricError


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise MetricError(f"{name} must be a finite real number, not a coerced value.")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise MetricError(f"{name} must be a finite real number.") from exc
    if not np.isfinite(result):
        raise MetricError(f"{name} must be a finite real number.")
    return result


def classify_direction_magnitude(
    predicted_change: float | None,
    observed_change: float | None,
    *,
    tau: float,
    epsilon: float,
) -> dict[str, object]:
    """Classify direction agreement and signed-change magnitude accuracy.

    Parameters
    ----------
    predicted_change : float or None
        Frozen predicted scalar change, or ``None`` when unavailable.
    observed_change : float or None
        Finite-reference observed scalar change, not latent biological truth,
        or ``None`` when unavailable.
    tau : float
        Externally supplied nonnegative direction negligibility margin.
    epsilon : float
        Externally supplied nonnegative absolute signed-change error tolerance.

    Returns
    -------
    dict[str, object]
        Direction classes and paired descriptive events. Paired outputs are
        ``None`` if either change is missing. Boundary direction values are
        NEGLIGIBLE and magnitude equality is successful.

    Raises
    ------
    MetricError
        If a supplied nonmissing value or margin is invalid, or subtraction
        does not yield a finite magnitude error.

    Notes
    -----
    This helper provides no calibration, confidence interval, verdict, or
    authorization. The caller enforces common scale, query identity, frozen
    policy lineage, and permitted role/outcome access.
    """
    tau = _finite_number(tau, "tau")
    epsilon = _finite_number(epsilon, "epsilon")
    if tau < 0 or epsilon < 0:
        raise MetricError("tau and epsilon must be nonnegative.")

    predicted = (
        None if predicted_change is None else _finite_number(predicted_change, "predicted_change")
    )
    observed = (
        None if observed_change is None else _finite_number(observed_change, "observed_change")
    )

    def direction(value: float | None) -> str | None:
        if value is None:
            return None
        if value < -tau:
            return "DOWN"
        if value > tau:
            return "UP"
        return "NEGLIGIBLE"

    predicted_class = direction(predicted)
    observed_class = direction(observed)
    result: dict[str, object] = {
        "predicted_class": predicted_class,
        "observed_class": observed_class,
        "direction_success": None,
        "magnitude_error": None,
        "magnitude_success": None,
        "joint_success": None,
    }
    if predicted is None or observed is None:
        return result

    magnitude_error = abs(predicted - observed)
    if not np.isfinite(magnitude_error):
        raise MetricError("Signed-change subtraction must yield a finite magnitude error.")
    direction_success = predicted_class == observed_class
    magnitude_success = magnitude_error <= epsilon
    result.update(
        direction_success=direction_success,
        magnitude_error=magnitude_error,
        magnitude_success=magnitude_success,
        joint_success=direction_success and magnitude_success,
    )
    return result
