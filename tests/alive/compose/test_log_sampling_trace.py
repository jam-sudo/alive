"""Synthetic event-to-progress checks, not ledger custody proof."""

import hashlib
import json
from copy import deepcopy

import pytest

from alive.compose.log_sampling_report import LogSamplingDiagnosticError
from alive.compose.log_sampling_trace import validate_synthetic_log_sampling_trace


@pytest.fixture
def case():
    unit = {"condition": {"kind": "single", "gene_id": "A"}, "role": "singles", "training_seed": 11}
    events = [
        {"seq": 0, "kind": "START"},
        {"seq": 1, "kind": "CONTROL_DONE", "row_id": "c1"},
        {"seq": 2, "kind": "REPEAT_ATTEMPT", "repeat_index": 7},
        {"seq": 3, "kind": "REPEAT_DONE", "repeat_index": 7},
        {"seq": 4, "kind": "TERMINAL", "status": "COMPLETE"},
    ]
    progress = {"requested_control_rows": 1, "requested_repeats": 1}
    for key in ("completed_control_rows", "attempted_repeats", "completed_repeats"):
        progress[key] = {"status": "KNOWN", "value": 1}
    return unit, {"unit": deepcopy(unit), "events": events}, progress


def invoke(case, status="COMPLETE", **overrides):
    unit, payload, progress = case
    raw = json.dumps(payload).encode()
    kwargs = {
        "unit_status": status,
        "transcript_bytes": raw,
        "expected_transcript_sha256": hashlib.sha256(raw).hexdigest(),
        "expected_unit": unit,
        "expected_control_rows": ["c1"],
        "expected_repeat_indices": [7],
    }
    kwargs.update(overrides)
    return validate_synthetic_log_sampling_trace(progress, **kwargs)


def test_complete_transcript_recomputes_without_mutation_or_admission(case):
    before = deepcopy(case)
    assert invoke(case) is None
    assert case == before


def test_closed_failed_attempt_preserves_zero_completed_repeats(case):
    case[1]["events"].pop(3)
    case[1]["events"][-1] = {"seq": 3, "kind": "TERMINAL", "status": "FAILED"}
    case[2]["completed_repeats"]["value"] = 0
    assert invoke(case, "FAILED") is None


@pytest.mark.parametrize("prefix", range(5))
def test_every_unclosed_prefix_stays_unknown_including_empty_trace(case, prefix):
    case[1]["events"] = case[1]["events"][:prefix]
    for key in ("completed_control_rows", "attempted_repeats", "completed_repeats"):
        case[2][key] = {"status": "UNKNOWN", "reason_codes": ["MEASUREMENT_INCOMPLETE"]}
    assert invoke(case, "FAILED") is None


def test_explicit_synthetic_no_start_marker_is_not_a_runtime_proof(case):
    case[1]["events"] = [{"seq": 0, "kind": "TERMINAL", "status": "NOT_EXECUTED"}]
    for key in ("completed_control_rows", "attempted_repeats", "completed_repeats"):
        case[2][key]["value"] = 0
    assert invoke(case, "NOT_EXECUTED") is None


def test_zero_budget_completes_reference_without_public_calls(case):
    case[1]["events"] = case[1]["events"][:2] + [
        {"seq": 2, "kind": "TERMINAL", "status": "COMPLETE"}
    ]
    case[2]["requested_repeats"] = 0
    case[2]["attempted_repeats"]["value"] = 0
    case[2]["completed_repeats"]["value"] = 0
    assert invoke(case, expected_repeat_indices=[]) is None


@pytest.mark.parametrize(
    "fault",
    [
        "unit",
        "extra",
        "seq_gap",
        "bool_seq",
        "unknown_row",
        "completion_before_attempt",
        "wrong_repeat",
        "duplicate_done",
        "post_terminal",
        "unknown_kind",
        "no_start",
        "forged_count",
        "unknown_to_zero",
    ],
)
def test_bad_trace_with_fresh_byte_hash_is_rejected_in_own_frame(case, fault):
    events = case[1]["events"]
    if fault == "unit":
        case[1]["unit"]["training_seed"] = 12
    elif fault == "extra":
        events[1]["trusted"] = True
    elif fault == "seq_gap":
        events[1]["seq"] = 9
    elif fault == "bool_seq":
        events[0]["seq"] = False
    elif fault == "unknown_row":
        events[1]["row_id"] = "other"
    elif fault == "completion_before_attempt":
        events[2]["kind"] = "REPEAT_DONE"
    elif fault == "wrong_repeat":
        events[2]["repeat_index"] = 8
    elif fault == "duplicate_done":
        events[4] = {"seq": 4, "kind": "REPEAT_DONE", "repeat_index": 7}
    elif fault == "post_terminal":
        events.append({"seq": 5, "kind": "START"})
    elif fault == "unknown_kind":
        events[0]["kind"] = "GUESS"
    elif fault == "no_start":
        events[0] = {"seq": 0, "kind": "CONTROL_DONE", "row_id": "c1"}
    elif fault == "forged_count":
        case[2]["completed_repeats"]["value"] = 0
    else:
        events.pop()
    caught = None
    try:
        invoke(case, "FAILED" if fault == "unknown_to_zero" else "COMPLETE")
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, f"accepted {fault} with fresh checksum"
    expected_error = {
        "unit": "trace unit differs from external identity",
        "extra": "coverage record keys differ from the draft",
        "seq_gap": "trace sequence has a gap or reordering",
        "bool_seq": "coverage index/seed must be a nonnegative integer",
        "unknown_row": "invalid, duplicate or late control completion",
        "completion_before_attempt": "completion without attempt or duplicate completion",
        "wrong_repeat": "unregistered, reordered or overlapping attempt",
        "duplicate_done": "completion without attempt or duplicate completion",
        "post_terminal": "invalid event or event after terminal",
        "unknown_kind": "unknown trace event",
        "no_start": "work before start",
        "forged_count": "COMPLETE requires known fully completed counts",
        "unknown_to_zero": "progress differs from external expectations",
    }[fault]
    assert str(caught) == expected_error, "a different rejection must not mask the target check"


@pytest.mark.parametrize(
    "fault", ["pin", "control", "repeat", "duplicate_controls", "duplicate_repeats", "status"]
)
def test_external_expectations_cannot_be_replaced_by_trace(case, fault):
    overrides = {
        "pin": {"expected_transcript_sha256": "0" * 64},
        "control": {"expected_control_rows": ["other"]},
        "repeat": {"expected_repeat_indices": [8]},
        "duplicate_controls": {"expected_control_rows": ["c1", "c1"]},
        "duplicate_repeats": {"expected_repeat_indices": [7, 7]},
        "status": {"unit_status": "ELIGIBLE"},
    }[fault]
    caught = None
    try:
        invoke(case, **overrides)
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None


def _set_counts(case, rows, attempted, completed):
    for key, value in zip(
        ("completed_control_rows", "attempted_repeats", "completed_repeats"),
        (rows, attempted, completed),
        strict=True,
    ):
        case[2][key] = {"status": "KNOWN", "value": value}


def test_duplicate_start_is_rejected_without_another_status_or_count_error(case):
    case[1]["events"] = [
        {"seq": 0, "kind": "START"},
        {"seq": 1, "kind": "START"},
        {"seq": 2, "kind": "TERMINAL", "status": "FAILED"},
    ]
    _set_counts(case, 0, 0, 0)
    caught = None
    try:
        invoke(case, "FAILED")
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, "duplicate START alone must reject"


def test_duplicate_row_is_rejected_without_a_later_unattempted_completion(case):
    case[1]["events"] = case[1]["events"][:2] + [
        {"seq": 2, "kind": "CONTROL_DONE", "row_id": "c1"},
        {"seq": 3, "kind": "TERMINAL", "status": "FAILED"},
    ]
    _set_counts(case, 1, 0, 0)
    caught = None
    try:
        invoke(case, "FAILED")
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, "duplicate control alone must reject"


def test_false_no_start_is_rejected_with_matching_candidate_status_and_zero_counts(case):
    case[1]["events"] = [
        {"seq": 0, "kind": "START"},
        {"seq": 1, "kind": "TERMINAL", "status": "NOT_EXECUTED"},
    ]
    _set_counts(case, 0, 0, 0)
    caught = None
    try:
        invoke(case, "NOT_EXECUTED")
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, "START contradicts NOT_EXECUTED even with matching report fields"


def test_false_complete_rejects_even_when_candidate_matches_derived_partial_counts(case):
    case[1]["events"] = [
        {"seq": 0, "kind": "START"},
        {"seq": 1, "kind": "TERMINAL", "status": "COMPLETE"},
    ]
    _set_counts(case, 0, 0, 0)
    caught = None
    try:
        invoke(case, "COMPLETE")
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, "matching candidate counts cannot make partial work COMPLETE"


@pytest.fixture
def multi_case(case):
    case[1]["events"] = [
        {"seq": 0, "kind": "START"},
        {"seq": 1, "kind": "CONTROL_DONE", "row_id": "c1"},
        {"seq": 2, "kind": "CONTROL_DONE", "row_id": "c2"},
        {"seq": 3, "kind": "REPEAT_ATTEMPT", "repeat_index": 7},
        {"seq": 4, "kind": "REPEAT_DONE", "repeat_index": 7},
        {"seq": 5, "kind": "REPEAT_ATTEMPT", "repeat_index": 9},
        {"seq": 6, "kind": "REPEAT_DONE", "repeat_index": 9},
        {"seq": 7, "kind": "TERMINAL", "status": "COMPLETE"},
    ]
    case[2]["requested_control_rows"] = 2
    case[2]["requested_repeats"] = 2
    _set_counts(case, 2, 2, 2)
    return case


def test_multiple_controls_and_serial_repeats_complete(multi_case):
    before = deepcopy(multi_case)
    assert (
        invoke(multi_case, expected_control_rows=["c1", "c2"], expected_repeat_indices=[7, 9])
        is None
    )
    assert multi_case == before


@pytest.mark.parametrize(
    "fault", ["wrong_order", "overlap", "retry", "missing_control", "duplicate_done"]
)
def test_multi_item_sequence_fault_is_not_masked_by_candidate_counts(multi_case, fault):
    events = multi_case[1]["events"]
    if fault == "wrong_order":
        events = events[:3] + [{"kind": "REPEAT_ATTEMPT", "repeat_index": 9}]
        counts = (2, 1, 0)
    elif fault == "overlap":
        events = events[:4] + [{"kind": "REPEAT_ATTEMPT", "repeat_index": 9}]
        counts = (2, 2, 0)
    elif fault == "retry":
        events = events[:5] + [{"kind": "REPEAT_ATTEMPT", "repeat_index": 7}]
        counts = (2, 1, 1)
    elif fault == "missing_control":
        events = events[:2] + [{"kind": "REPEAT_ATTEMPT", "repeat_index": 7}]
        counts = (1, 1, 0)
    else:
        events = events[:5] + [{"kind": "REPEAT_DONE", "repeat_index": 7}]
        counts = (2, 1, 1)
    events.append({"kind": "TERMINAL", "status": "FAILED"})
    multi_case[1]["events"] = [dict(event, seq=i) for i, event in enumerate(events)]
    _set_counts(multi_case, *counts)
    caught = None
    try:
        invoke(
            multi_case, "FAILED", expected_control_rows=["c1", "c2"], expected_repeat_indices=[7, 9]
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, f"isolated {fault} must reject"


@pytest.mark.parametrize("prefix", range(8))
def test_multi_item_crash_boundaries_do_not_claim_exact_counts(multi_case, prefix):
    multi_case[1]["events"] = multi_case[1]["events"][:prefix]
    for key in ("completed_control_rows", "attempted_repeats", "completed_repeats"):
        multi_case[2][key] = {"status": "UNKNOWN", "reason_codes": ["MEASUREMENT_INCOMPLETE"]}
    assert (
        invoke(
            multi_case, "FAILED", expected_control_rows=["c1", "c2"], expected_repeat_indices=[7, 9]
        )
        is None
    )


@pytest.mark.parametrize(
    "token",
    [
        "1e-9999999999999999999999999",
        "-1e-9999999999999999999999999",
        "0e-9999999999999999999999999",
        "-0e-9999999999999999999999999",
    ],
)
def test_extreme_decimal_exponent_is_a_typed_trace_rejection(case, token):
    raw = ('{"unit":' + token + ',"events":[]}').encode()
    caught = None
    try:
        invoke(
            case, transcript_bytes=raw, expected_transcript_sha256=hashlib.sha256(raw).hexdigest()
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, "Decimal failures must use the public diagnostic error"


@pytest.mark.parametrize("raw", [b'{"unit":0,"unit":1}', b"\xff", b'{"x":NaN}', b"[]"])
def test_invalid_pinned_bytes_do_not_pass_decoding(case, raw):
    caught = None
    try:
        invoke(
            case, transcript_bytes=raw, expected_transcript_sha256=hashlib.sha256(raw).hexdigest()
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None
