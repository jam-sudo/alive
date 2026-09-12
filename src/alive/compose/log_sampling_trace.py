"""Bind synthetic progress to exact transcript bytes, never to runtime authority."""

import hashlib
from typing import Any

from alive.compose.log_sampling_coverage import (
    _condition,
    _keys,
    _name,
    _natural,
    _sha,
    validate_synthetic_log_sampling_progress,
)
from alive.compose.log_sampling_report import (
    LogSamplingDiagnosticError,
    _json,
    decode_log_sampling_diagnostic,
)


def _unit(value: Any) -> None:
    _json(value)
    _keys(value, {"condition", "role", "training_seed"})
    _condition(value["condition"], value["role"])
    _natural(value["training_seed"])


def _roster(value: Any, *, names: bool) -> None:
    if type(value) is not list or (names and not value):
        raise LogSamplingDiagnosticError("trace roster must be a JSON list with controls")
    for item in value:
        (_name if names else _natural)(item)
    if len(set(value)) != len(value):
        raise LogSamplingDiagnosticError("duplicate trace roster identity")


def _derive(events: Any, controls: list[str], repeats: list[int]) -> tuple[str, dict]:
    if type(events) is not list:
        raise LogSamplingDiagnosticError("trace events must be an array")
    started = False
    terminal = None
    control_ids = set(controls)
    done_rows: set[str] = set()
    attempted: set[int] = set()
    done_repeats: set[int] = set()
    for seq, event in enumerate(events):
        if type(event) is not dict or terminal is not None:
            raise LogSamplingDiagnosticError("invalid event or event after terminal")
        kind = event.get("kind")
        if type(kind) is not str or kind not in {
            "START",
            "CONTROL_DONE",
            "REPEAT_ATTEMPT",
            "REPEAT_DONE",
            "TERMINAL",
        }:
            raise LogSamplingDiagnosticError("unknown trace event")
        extra = {
            "START": set(),
            "CONTROL_DONE": {"row_id"},
            "REPEAT_ATTEMPT": {"repeat_index"},
            "REPEAT_DONE": {"repeat_index"},
            "TERMINAL": {"status"},
        }[kind]
        _keys(event, {"seq", "kind"} | extra)
        _natural(event["seq"])
        if event["seq"] != seq:
            raise LogSamplingDiagnosticError("trace sequence has a gap or reordering")
        if kind == "START":
            if started or seq != 0:
                raise LogSamplingDiagnosticError("duplicate or late start")
            started = True
        elif kind == "TERMINAL":
            terminal = event["status"]
            if type(terminal) is not str or terminal not in {"COMPLETE", "FAILED", "NOT_EXECUTED"}:
                raise LogSamplingDiagnosticError("unknown trace terminal")
            if (terminal == "NOT_EXECUTED" and seq != 0) or (
                terminal != "NOT_EXECUTED" and not started
            ):
                raise LogSamplingDiagnosticError("terminal contradicts start history")
        elif not started:
            raise LogSamplingDiagnosticError("work before start")
        elif kind == "CONTROL_DONE":
            row = event["row_id"]
            _name(row)
            if row not in control_ids or row in done_rows or attempted:
                raise LogSamplingDiagnosticError("invalid, duplicate or late control completion")
            done_rows.add(row)
        else:
            repeat = event["repeat_index"]
            _natural(repeat)
            if len(done_rows) != len(controls):
                raise LogSamplingDiagnosticError("public repeat before complete reference")
            if kind == "REPEAT_ATTEMPT":
                if (
                    len(attempted) >= len(repeats)
                    or repeat != repeats[len(attempted)]
                    or len(done_repeats) != len(attempted)
                ):
                    raise LogSamplingDiagnosticError(
                        "unregistered, reordered or overlapping attempt"
                    )
                attempted.add(repeat)
            elif repeat not in attempted or repeat in done_repeats:
                raise LogSamplingDiagnosticError(
                    "completion without attempt or duplicate completion"
                )
            else:
                done_repeats.add(repeat)
    progress = {"requested_control_rows": len(controls), "requested_repeats": len(repeats)}
    for key, value in (
        ("completed_control_rows", len(done_rows)),
        ("attempted_repeats", len(attempted)),
        ("completed_repeats", len(done_repeats)),
    ):
        progress[key] = (
            {"status": "KNOWN", "value": value}
            if terminal is not None
            else {"status": "UNKNOWN", "reason_codes": ["MEASUREMENT_INCOMPLETE"]}
        )
    return terminal or "FAILED", progress


def validate_synthetic_log_sampling_trace(
    progress: Any,
    *,
    unit_status: str,
    transcript_bytes: bytes,
    expected_transcript_sha256: str,
    expected_unit: Any,
    expected_control_rows: list[str],
    expected_repeat_indices: list[int],
) -> None:
    """Derive synthetic counts from independently pinned serial transcript bytes.

    Parameters
    ----------
    progress, unit_status
        Candidate counters and unit status to check, not evidence of execution.
    transcript_bytes
        Caller-bounded UTF-8 JSON bytes; no file or network I/O is performed.
    expected_transcript_sha256
        External digest of those exact bytes, not supplied by the candidate report.
    expected_unit
        Independent condition/role/training-seed identity.
    expected_control_rows, expected_repeat_indices
        Independent unique control IDs and ordered public-repeat roster.

    Raises
    ------
    LogSamplingDiagnosticError
        On byte/identity mismatch, invalid event sequence or progress mismatch.

    Notes
    -----
    A closed fixture supports exact counts only inside that fixture. This function
    does not authenticate runtime custody, completeness, no-start claims or admission.
    """
    _sha(expected_transcript_sha256)
    if type(transcript_bytes) is not bytes:
        raise LogSamplingDiagnosticError("transcript must be immutable bytes")
    if hashlib.sha256(transcript_bytes).hexdigest() != expected_transcript_sha256:
        raise LogSamplingDiagnosticError("transcript differs from external byte pin")
    _unit(expected_unit)
    _roster(expected_control_rows, names=True)
    _roster(expected_repeat_indices, names=False)
    try:
        payload = decode_log_sampling_diagnostic(transcript_bytes.decode("utf-8"))
    except UnicodeError as error:
        raise LogSamplingDiagnosticError("trace must be UTF-8 JSON") from error
    _keys(payload, {"unit", "events"})
    _unit(payload["unit"])
    if _json(payload["unit"]) != _json(expected_unit):
        raise LogSamplingDiagnosticError("trace unit differs from external identity")
    status, expected = _derive(payload["events"], expected_control_rows, expected_repeat_indices)
    if type(unit_status) is not str or unit_status != status:
        raise LogSamplingDiagnosticError("candidate status differs from transcript")
    validate_synthetic_log_sampling_progress(
        progress, unit_status=status, expected_progress=expected
    )
