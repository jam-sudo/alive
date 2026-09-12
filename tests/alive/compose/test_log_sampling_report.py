"""Known-answer and own-frame rejection tests for the development-only schema."""

import hashlib
import json
from copy import deepcopy
from itertools import product

import numpy as np
import pytest

from alive.compose.approximation_bias import (
    ApproximationBiasValidationError,
    validate_approximation_bias_report,
)
from alive.compose.log_sampling_report import (
    LogSamplingDiagnosticError,
    build_log_sampling_diagnostic,
    decode_log_sampling_diagnostic,
    validate_log_sampling_diagnostic,
)


def _rehash(report):
    content = {k: v for k, v in report.items() if k != "self_checksum"}
    report["self_checksum"] = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


@pytest.fixture
def case():
    registration = {
        "pair_id": ["A", "B"],
        "role": "combo_calibration",
        "training_seed": 11,
        "control_ids": ["cell-1", "cell-2"],
        "draw_count": 2,
        "response_dim": 2,
        "binding_sha256": {
            key: str(i) * 64
            for i, key in enumerate(
                ["basis_config", "contract", "checkpoint", "response", "roster"]
            )
        },
    }
    return registration, [[4.0, 4.0], [6.0, -2.0]], [[5.0, 1.0], [4.0, 4.0]]


def test_known_answer_and_canonical_json_roundtrip(case):
    registration, controls, public = case
    report = build_log_sampling_diagnostic(*case)
    assert report["analytic"] == {
        "reference_mean": [5.0, 1.0],
        "centered_squared_sum": 20.0,
        "V": 2.5,
        "B": 5.0,
    }
    assert report["public"] == {"status": "INCONCLUSIVE", "squared_discrepancies": [0.0, 5.0]}
    assert report["exact_n"] == {
        "control_rows": 2,
        "response_dim": 2,
        "draw_count": 2,
        "public_repeats": 2,
    }
    decoded = decode_log_sampling_diagnostic(json.dumps(report))
    validate_log_sampling_diagnostic(
        decoded, expected_registration=registration, control_outputs=controls, public_means=public
    )
    assert report["admission_status"] == "NOT_ADMISSIBLE"
    assert report["structural_status"] == "UNVERIFIED"


@pytest.mark.parametrize("n", [1, 2])
def test_constant_or_singleton_pool_with_no_public_repeats_stays_nonadmissible(case, n):
    registration, _, _ = case
    registration["control_ids"] = registration["control_ids"][:n]
    report = build_log_sampling_diagnostic(registration, [[-2.0, 3.0]] * n, [])
    assert report["analytic"]["V"] == report["analytic"]["B"] == 0.0
    assert report["public"] == {"status": "NOT_RUN_BUDGET", "squared_discrepancies": []}
    assert report["admission_status"] == "NOT_ADMISSIBLE"


@pytest.mark.parametrize("m", [1, 2, 3])
def test_analytic_variance_matches_complete_replacement_enumeration(case, m):
    registration, controls, _ = case
    registration["draw_count"] = m
    public = [
        np.asarray(controls)[list(draw)].mean(axis=0).tolist()
        for draw in product(range(2), repeat=m)
    ]
    report = build_log_sampling_diagnostic(registration, controls, public)
    assert abs(report["analytic"]["V"] - 5.0 / m) < 1e-12
    assert abs(np.mean(report["public"]["squared_discrepancies"]) - report["analytic"]["V"]) < 1e-12


@pytest.mark.parametrize(
    "fault",
    ["V", "N", "mean", "public", "admission", "structural", "extra", "missing", "bool", "binding"],
)
def test_tampered_report_with_fresh_checksum_is_rejected_in_own_frame(case, fault):
    registration, controls, public = case
    report = build_log_sampling_diagnostic(*case)
    if fault == "V":
        report["analytic"]["V"] = 0.0
    elif fault == "N":
        report["exact_n"]["draw_count"] = 3
    elif fault == "mean":
        report["analytic"]["reference_mean"][0] += 1
    elif fault == "public":
        report["public"]["status"] = "WITHIN_PRECISION"
    elif fault == "admission":
        report["admission_status"] = "admitted"
    elif fault == "structural":
        report["structural_status"] = "VERIFIED"
    elif fault == "extra":
        report["analytic"]["confidence"] = 1.0
    elif fault == "missing":
        del report["analytic"]["B"]
    elif fault == "bool":
        report["analytic"]["V"] = True
    else:
        report["registration"]["binding_sha256"]["checkpoint"] = "f" * 64
    _rehash(report)
    caught = None
    try:
        validate_log_sampling_diagnostic(
            report,
            expected_registration=registration,
            control_outputs=controls,
            public_means=public,
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, f"fresh checksum hid {fault}"


@pytest.mark.parametrize(
    "fault",
    [
        "extra",
        "missing",
        "sealed",
        "bool",
        "negative_seed",
        "zero_m",
        "duplicate_control",
        "bad_digest",
        "extra_binding",
        "pair",
    ],
)
def test_malformed_registration_fails_closed(case, fault):
    registration, controls, public = case
    if fault == "extra":
        registration["allow_seal"] = True
    elif fault == "missing":
        del registration["draw_count"]
    elif fault == "sealed":
        registration["role"] = "sealed_double_unseen"
    elif fault == "bool":
        registration["response_dim"] = True
    elif fault == "negative_seed":
        registration["training_seed"] = -1
    elif fault == "zero_m":
        registration["draw_count"] = 0
    elif fault == "duplicate_control":
        registration["control_ids"] = ["same", "same"]
    elif fault == "bad_digest":
        registration["binding_sha256"]["checkpoint"] = "not-a-sha"
    elif fault == "extra_binding":
        registration["binding_sha256"]["unexpected"] = "f" * 64
    else:
        registration["pair_id"] = ["A", "A"]
    caught = None
    try:
        build_log_sampling_diagnostic(registration, controls, public)
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, f"accepted malformed registration: {fault}"


@pytest.mark.parametrize(
    "fault", ["nan", "inf", "bool", "string", "shape", "rows", "overflow", "underflow"]
)
def test_invalid_or_unrepresentable_numeric_inputs_are_not_zero_noise(case, fault):
    registration, controls, public = case
    if fault in {"nan", "inf"}:
        controls[0][0] = float(fault)
    elif fault == "bool":
        controls[0][0] = True
    elif fault == "string":
        controls[0][0] = "4.0"
    elif fault == "shape":
        controls[0].pop()
    elif fault == "rows":
        controls.pop()
    elif fault == "overflow":
        controls[0][0] = 1e308
    else:
        controls = [[0.0, 0.0], [1e-200, 0.0]]
    caught = None
    try:
        build_log_sampling_diagnostic(registration, controls, public)
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, f"accepted {fault}"


@pytest.mark.parametrize(
    "fault", ["control_order", "control_value", "public_value", "registration"]
)
def test_external_expectations_bind_inputs_independently_of_report(case, fault):
    registration, controls, public = case
    report = build_log_sampling_diagnostic(*case)
    if fault == "control_order":
        controls.reverse()
    elif fault == "control_value":
        controls[0][0] += 1
    elif fault == "public_value":
        public[0][0] += 1
    else:
        registration["training_seed"] += 1
    caught = None
    try:
        validate_log_sampling_diagnostic(
            report,
            expected_registration=registration,
            control_outputs=controls,
            public_means=public,
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, f"external {fault} was not bound"


@pytest.mark.parametrize(
    "payload",
    ['{"x":1,"x":2}', '{"x":{"y":0,"y":1}}', '{"x":NaN}', '{"x":1e999}', "[]", "not json"],
)
def test_ambiguous_or_nonfinite_json_is_rejected(payload):
    caught = None
    try:
        decode_log_sampling_diagnostic(payload)
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None


def test_scientific_bias_validator_rejects_development_report_even_if_admission_forged(case):
    report = build_log_sampling_diagnostic(*case)
    forged = deepcopy(report)
    forged["admission_status"] = "admitted"
    _rehash(forged)
    caught = None
    try:
        validate_approximation_bias_report(forged)
    except ApproximationBiasValidationError as error:
        caught = error
    assert caught is not None, "development diagnostic entered scientific bias evidence"


def test_integer_rounding_cannot_silently_change_projected_inputs(case):
    registration, controls, public = case
    controls[0][0] = 2**53 + 1
    caught = None
    try:
        build_log_sampling_diagnostic(registration, controls, public)
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None


def test_json_underflow_cannot_turn_nonzero_signal_into_zero():
    caught = None
    try:
        decode_log_sampling_diagnostic('{"value": 1e-999}')
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None


def test_recursive_report_is_rejected_as_invalid_json(case):
    registration, controls, public = case
    report = build_log_sampling_diagnostic(*case)
    report["recursive"] = report
    caught = None
    try:
        validate_log_sampling_diagnostic(
            report,
            expected_registration=registration,
            control_outputs=controls,
            public_means=public,
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None


@pytest.mark.parametrize("token", ["1e-9999999999999999999999999", "-0e-9999999999999999999999999"])
def test_extreme_decimal_conversion_uses_the_documented_error_type(token):
    caught = None
    try:
        decode_log_sampling_diagnostic('{"value":' + token + "}")
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None
