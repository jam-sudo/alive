import sys

import numpy as np
import pytest

from alive.eval.events import classify_direction_magnitude
from alive.metrics.selective import MetricError


@pytest.mark.parametrize(
    ("predicted", "observed", "direction", "magnitude", "joint"),
    [
        (2, 2.5, True, True, True),
        (2, 4, True, False, False),
        (1.25, 1, False, True, False),
        (-0.25, 0.25, True, True, True),
        (2, -2, False, False, False),
    ],
)
def test_contract_examples(predicted, observed, direction, magnitude, joint):
    result = classify_direction_magnitude(predicted, observed, tau=1, epsilon=0.5)

    assert result["direction_success"] is direction
    assert result["magnitude_success"] is magnitude
    assert result["joint_success"] is joint
    assert result["magnitude_error"] == abs(predicted - observed)


def test_exact_boundaries_and_zero_margins():
    assert classify_direction_magnitude(1, -1, tau=1, epsilon=2) == {
        "predicted_class": "NEGLIGIBLE",
        "observed_class": "NEGLIGIBLE",
        "direction_success": True,
        "magnitude_error": 2.0,
        "magnitude_success": True,
        "joint_success": True,
    }
    assert classify_direction_magnitude(0, 0, tau=0, epsilon=0)["joint_success"] is True


def test_signed_change_not_absolute_effect_magnitude():
    result = classify_direction_magnitude(2, -2, tau=0, epsilon=0)

    assert result["magnitude_error"] == 4
    assert result["magnitude_success"] is False


def test_signed_symmetry():
    positive = classify_direction_magnitude(2, 2.5, tau=1, epsilon=0.5)
    negative = classify_direction_magnitude(-2, -2.5, tau=1, epsilon=0.5)

    assert (positive["predicted_class"], positive["observed_class"]) == ("UP", "UP")
    assert (negative["predicted_class"], negative["observed_class"]) == ("DOWN", "DOWN")
    assert positive["magnitude_error"] == negative["magnitude_error"]
    assert positive["joint_success"] == negative["joint_success"] is True


@pytest.mark.parametrize(
    ("predicted", "observed", "predicted_class", "observed_class"),
    [(None, 2, None, "UP"), (-2, None, "DOWN", None), (None, None, None, None)],
)
def test_missing_axis_retains_available_class(predicted, observed, predicted_class, observed_class):
    result = classify_direction_magnitude(predicted, observed, tau=1, epsilon=0.5)

    assert result == {
        "predicted_class": predicted_class,
        "observed_class": observed_class,
        "direction_success": None,
        "magnitude_error": None,
        "magnitude_success": None,
        "joint_success": None,
    }


@pytest.mark.parametrize("name", ["predicted_change", "observed_change", "tau", "epsilon"])
@pytest.mark.parametrize("invalid", [True, np.bool_(True), "1", np.nan, np.inf, -np.inf])
def test_invalid_each_argument(name, invalid):
    values = {"predicted_change": 1, "observed_change": 1, "tau": 1, "epsilon": 1}
    values[name] = invalid

    with pytest.raises(MetricError):
        classify_direction_magnitude(**values)


@pytest.mark.parametrize("name", ["tau", "epsilon"])
def test_negative_margin(name):
    margins = {"tau": 1, "epsilon": 1}
    margins[name] = -1

    with pytest.raises(MetricError):
        classify_direction_magnitude(0, 0, **margins)


@pytest.mark.parametrize("name", ["tau", "epsilon"])
def test_missing_margin_is_invalid(name):
    margins = {"tau": 1, "epsilon": 1}
    margins[name] = None

    with pytest.raises(MetricError):
        classify_direction_magnitude(0, 0, **margins)


def test_invalid_nonmissing_axis_raises_when_other_is_missing():
    with pytest.raises(MetricError):
        classify_direction_magnitude(None, np.nan, tau=1, epsilon=1)


def test_integer_too_large_for_finite_float_is_rejected():
    with pytest.raises(MetricError):
        classify_direction_magnitude(10**1000, None, tau=1, epsilon=1)


def test_subtraction_overflow_is_rejected():
    with pytest.raises(MetricError, match="subtraction"):
        classify_direction_magnitude(sys.float_info.max, -sys.float_info.max, tau=0, epsilon=0)


def test_nextafter_values_straddle_direction_boundary():
    below = np.nextafter(1.0, 0.0)
    above = np.nextafter(1.0, np.inf)

    result = classify_direction_magnitude(below, above, tau=1, epsilon=above - below)
    assert result["predicted_class"] == "NEGLIGIBLE"
    assert result["observed_class"] == "UP"
    assert result["direction_success"] is False
    assert result["magnitude_success"] is True


def test_nextafter_value_exceeds_magnitude_boundary():
    result = classify_direction_magnitude(np.nextafter(0.5, np.inf), 0, tau=1, epsilon=0.5)

    assert result["magnitude_success"] is False
