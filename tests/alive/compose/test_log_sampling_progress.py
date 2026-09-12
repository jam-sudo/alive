"""Own-frame synthetic progress validation; no runtime/ledger proof is implied."""

from copy import deepcopy

import pytest

from alive.compose.log_sampling_coverage import validate_synthetic_log_sampling_progress
from alive.compose.log_sampling_report import LogSamplingDiagnosticError


def known(n):
    return {"status": "KNOWN", "value": n}


def unknown():
    return {"status": "UNKNOWN", "reason_codes": ["MEASUREMENT_INCOMPLETE"]}


@pytest.fixture
def progress():
    return {
        "requested_control_rows": 5,
        "completed_control_rows": known(5),
        "requested_repeats": 3,
        "attempted_repeats": known(3),
        "completed_repeats": known(3),
    }


@pytest.mark.parametrize("status", ["COMPLETE", "FAILED", "NOT_EXECUTED"])
def test_valid_states_preserve_progress_without_admission(progress, status):
    if status == "FAILED":
        progress["completed_repeats"] = unknown()
    elif status == "NOT_EXECUTED":
        for field in ("completed_control_rows", "attempted_repeats", "completed_repeats"):
            progress[field] = known(0)
    before = deepcopy(progress)
    assert (
        validate_synthetic_log_sampling_progress(
            progress, unit_status=status, expected_progress=before
        )
        is None
    )
    assert progress == before


def test_complete_with_zero_public_repeats_does_not_invent_execution(progress):
    progress["requested_repeats"] = 0
    progress["attempted_repeats"] = known(0)
    progress["completed_repeats"] = known(0)
    assert (
        validate_synthetic_log_sampling_progress(
            progress, unit_status="COMPLETE", expected_progress=deepcopy(progress)
        )
        is None
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "extra",
        "bool_requested",
        "negative_requested",
        "float_requested",
        "bool_known",
        "negative_known",
        "nan_known",
        "plain_counter",
        "unknown_tag",
        "unknown_with_value",
        "unknown_empty_reasons",
        "unknown_bad_reason",
        "unknown_duplicate_reasons",
        "unknown_unsorted_reasons",
        "unknown_list_reason",
        "row_overrun",
        "attempt_overrun",
        "completion_overrun_unknown_attempts",
        "completed_exceeds_attempted",
        "cyclic",
    ],
)
@pytest.mark.parametrize("side", ["candidate", "expected"])
def test_malformed_or_impossible_progress_rejects_in_own_frame(progress, fault, side):
    bad = deepcopy(progress)
    field = "completed_repeats"
    if fault == "missing":
        del bad[field]
    elif fault == "extra":
        bad["ELIGIBLE"] = True
    elif fault == "bool_requested":
        bad["requested_repeats"] = True
    elif fault == "negative_requested":
        bad["requested_repeats"] = -1
    elif fault == "float_requested":
        bad["requested_repeats"] = 3.0
    elif fault == "bool_known":
        bad[field] = known(True)
    elif fault == "negative_known":
        bad[field] = known(-1)
    elif fault == "nan_known":
        bad[field] = known(float("nan"))
    elif fault == "plain_counter":
        bad[field] = 3
    elif fault == "unknown_tag":
        bad[field] = {"status": "INFERRED", "value": 3}
    elif fault == "unknown_with_value":
        bad[field] = {**unknown(), "value": 0}
    elif fault.startswith("unknown_"):
        reasons = {
            "unknown_empty_reasons": [],
            "unknown_bad_reason": ["GUESS"],
            "unknown_duplicate_reasons": ["EVIDENCE_MISSING", "EVIDENCE_MISSING"],
            "unknown_unsorted_reasons": ["VERIFICATION_PENDING", "EVIDENCE_MISSING"],
            "unknown_list_reason": [[]],
        }[fault]
        bad[field] = {"status": "UNKNOWN", "reason_codes": reasons}
    elif fault == "row_overrun":
        bad["completed_control_rows"] = known(6)
    elif fault == "attempt_overrun":
        bad["attempted_repeats"] = known(4)
        bad[field] = unknown()
    elif fault == "completion_overrun_unknown_attempts":
        bad["attempted_repeats"] = unknown()
        bad[field] = known(4)
    elif fault == "completed_exceeds_attempted":
        bad["attempted_repeats"] = known(2)
    else:
        bad["cycle"] = bad
    candidate, expected = (bad, progress) if side == "candidate" else (progress, bad)
    caught = None
    try:
        validate_synthetic_log_sampling_progress(
            candidate, unit_status="FAILED", expected_progress=expected
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, f"accepted {side} {fault}"


@pytest.mark.parametrize("status", ["COMPLETE", "NOT_EXECUTED"])
@pytest.mark.parametrize(
    "field", ["completed_control_rows", "attempted_repeats", "completed_repeats"]
)
def test_unknown_cannot_be_promoted_to_complete_or_unstarted(progress, status, field):
    if status == "NOT_EXECUTED":
        for key in ("completed_control_rows", "attempted_repeats", "completed_repeats"):
            progress[key] = known(0)
    progress[field] = unknown()
    caught = None
    try:
        validate_synthetic_log_sampling_progress(
            progress, unit_status=status, expected_progress=deepcopy(progress)
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None


@pytest.mark.parametrize("status", ["COMPLETE", "NOT_EXECUTED"])
def test_partial_known_execution_is_neither_complete_nor_unstarted(progress, status):
    progress["completed_repeats"] = known(1)
    caught = None
    try:
        validate_synthetic_log_sampling_progress(
            progress, unit_status=status, expected_progress=deepcopy(progress)
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None


@pytest.mark.parametrize("fault", ["count", "requested", "unknown_to_zero"])
def test_structurally_valid_rewrite_cannot_replace_external_progress(progress, fault):
    expected = deepcopy(progress)
    if fault == "count":
        progress["completed_repeats"] = known(1)
    elif fault == "requested":
        progress["requested_repeats"] = 4
    else:
        expected["completed_repeats"] = unknown()
        progress["completed_repeats"] = known(0)
    caught = None
    try:
        validate_synthetic_log_sampling_progress(
            progress, unit_status="FAILED", expected_progress=expected
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None


@pytest.mark.parametrize("status", ["ELIGIBLE", "complete", None, True, []])
def test_unknown_status_cannot_enter_the_progress_contract(progress, status):
    caught = None
    try:
        validate_synthetic_log_sampling_progress(
            progress, unit_status=status, expected_progress=deepcopy(progress)
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None
