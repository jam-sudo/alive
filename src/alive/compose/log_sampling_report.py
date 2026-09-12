"""Strict, non-admissible R1 development diagnostics over caller-supplied arrays.

This module does not read data, authenticate provenance, prove sampler behavior,
or create scientific admission. Float64 arithmetic is recomputed exactly from
the same canonical inputs. No scientific numerical tolerance is assumed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from decimal import Decimal, DecimalException
from typing import Any

import numpy as np

SCHEMA = "compose_gears_log_sampling_diagnostic_v1"
_REGISTRATION_KEYS = {
    "pair_id",
    "role",
    "training_seed",
    "control_ids",
    "draw_count",
    "response_dim",
    "binding_sha256",
}
_BINDING_KEYS = {"basis_config", "contract", "checkpoint", "response", "roster"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class LogSamplingDiagnosticError(ValueError):
    """Raised when a diagnostic cannot be recomputed under its strict contract."""


def _json(value: Any) -> str:
    def check(item: Any) -> None:
        if type(item) is dict:
            if any(type(k) is not str for k in item):
                raise LogSamplingDiagnosticError("JSON object keys must be strings")
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        elif type(item) not in {str, int, float, bool, type(None)}:
            raise LogSamplingDiagnosticError("value is not a strict JSON type")
        elif type(item) is float and not math.isfinite(item):
            raise LogSamplingDiagnosticError("nonfinite JSON number")

    try:
        check(value)
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
    except (RecursionError, ValueError) as error:
        raise LogSamplingDiagnosticError("value cannot be serialized as strict JSON") from error


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _keys(value: Any, expected: set[str], label: str) -> None:
    if type(value) is not dict or set(value) != expected:
        raise LogSamplingDiagnosticError(f"{label} keys do not match the strict schema")


def _integer(value: Any, minimum: int, label: str) -> None:
    if type(value) is not int or value < minimum:
        raise LogSamplingDiagnosticError(f"{label} must be an integer >= {minimum}")


def _names(value: Any, label: str) -> None:
    if type(value) is not list or not value:
        raise LogSamplingDiagnosticError(f"{label} must be a nonempty list")
    if any(type(s) is not str or not s or s.strip() != s for s in value):
        raise LogSamplingDiagnosticError(f"{label} must contain nonempty unpadded strings")
    if len(set(value)) != len(value):
        raise LogSamplingDiagnosticError(f"{label} contains duplicates")


def _registration(value: Any) -> None:
    _json(value)
    _keys(value, _REGISTRATION_KEYS, "registration")
    _names(value["pair_id"], "pair_id")
    if len(value["pair_id"]) != 2:
        raise LogSamplingDiagnosticError("pair_id must contain two identities")
    if value["role"] not in ("singles", "combo_calibration"):
        raise LogSamplingDiagnosticError("role must be a non-sealed development role")
    _names(value["control_ids"], "control_ids")
    _integer(value["training_seed"], 0, "training_seed")
    _integer(value["draw_count"], 1, "draw_count")
    _integer(value["response_dim"], 1, "response_dim")
    _keys(value["binding_sha256"], _BINDING_KEYS, "binding_sha256")
    for digest in value["binding_sha256"].values():
        if type(digest) is not str or _SHA.fullmatch(digest) is None:
            raise LogSamplingDiagnosticError("binding digest must be lowercase SHA-256")


def _matrix(value: Any, p: int, label: str) -> np.ndarray:
    if type(value) is not list:
        raise LogSamplingDiagnosticError(f"{label} must be a JSON row list")
    for row in value:
        if type(row) is not list or len(row) != p:
            raise LogSamplingDiagnosticError(f"{label} row dimension mismatch")
        if any(type(x) not in {int, float} for x in row):
            raise LogSamplingDiagnosticError(f"{label} entries must be numbers, not bools/strings")
    try:
        array = np.asarray(value, dtype=np.float64).reshape(len(value), p)
    except (ValueError, OverflowError) as error:
        raise LogSamplingDiagnosticError(f"{label} cannot be represented in float64") from error
    if not np.isfinite(array).all():
        raise LogSamplingDiagnosticError(f"{label} contains nonfinite values")
    for original_row, numeric_row in zip(value, array, strict=True):
        for original, numeric in zip(original_row, numeric_row, strict=True):
            if type(original) is int and int(numeric) != original:
                raise LogSamplingDiagnosticError(f"{label} integer loses precision in float64")
    return array


def _squares(difference: np.ndarray) -> np.ndarray:
    squared = np.square(difference)
    if np.any((difference != 0) & (squared == 0)):
        raise LogSamplingDiagnosticError("squared contribution underflowed to zero")
    return squared


def build_log_sampling_diagnostic(
    registration: dict[str, Any],
    control_outputs: list[list[float]],
    public_means: list[list[float]],
) -> dict[str, Any]:
    """Build one non-admissible pair/seed diagnostic without file or model I/O.

    Parameters
    ----------
    registration
        Exact development identities, row order, dimensions and digest bindings.
    control_outputs
        Complete caller-supplied projected control rows in registered order.
    public_means
        Every supplied projected public mean; an empty list means no repeats.

    Returns
    -------
    dict
        Strict checksummed development report with unverified structural status.

    Raises
    ------
    LogSamplingDiagnosticError
        On malformed identities, arrays or unrepresentable arithmetic.
    """
    _registration(registration)
    p, m = registration["response_dim"], registration["draw_count"]
    controls = _matrix(control_outputs, p, "control_outputs")
    public = _matrix(public_means, p, "public_means")
    n = len(registration["control_ids"])
    if len(controls) != n:
        raise LogSamplingDiagnosticError("control row count differs from registration")
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise", under="raise"):
            mu = controls.mean(axis=0)
            squared = _squares(controls - mu)
            total = float(squared.sum())
            variance = total / (n * m * p)
            if total > 0 and variance == 0:
                raise LogSamplingDiagnosticError("sampling variance underflowed to zero")
            bound = float(squared.sum(axis=1).max()) / p
            discrepancies = _squares(public - mu).mean(axis=1).tolist() if len(public) else []
    except (FloatingPointError, OverflowError) as error:
        raise LogSamplingDiagnosticError("nonrepresentable diagnostic arithmetic") from error
    report = {
        "schema": SCHEMA,
        "protocol": "COMPOSE-K562-v1",
        "method": "log_normalized_pseudobulk",
        "scope": "development_diagnostic",
        "registration": deepcopy(registration),
        "inputs_sha256": {
            "control_outputs": _digest(control_outputs),
            "public_means": _digest(public_means),
        },
        "exact_n": {
            "control_rows": n,
            "response_dim": p,
            "draw_count": m,
            "public_repeats": len(public),
        },
        "analytic": {
            "reference_mean": mu.tolist(),
            "centered_squared_sum": total,
            "V": variance,
            "B": bound,
        },
        "public": {
            "status": "INCONCLUSIVE" if len(public) else "NOT_RUN_BUDGET",
            "squared_discrepancies": discrepancies,
        },
        "structural_status": "UNVERIFIED",
        "admission_status": "NOT_ADMISSIBLE",
    }
    report["self_checksum"] = _digest(report)
    return report


def validate_log_sampling_diagnostic(
    report: Any,
    *,
    expected_registration: dict[str, Any],
    control_outputs: list[list[float]],
    public_means: list[list[float]],
) -> None:
    """Recompute every field against external expectations, never just hashes.

    Parameters
    ----------
    report
        Untrusted decoded diagnostic; extra and missing nested fields are errors.
    expected_registration
        Independently supplied expected registration, not read from the report.
    control_outputs, public_means
        Independently supplied ordered inputs used for exact recomputation.

    Raises
    ------
    LogSamplingDiagnosticError
        On any canonical mismatch. Success grants no admission or source proof.
    """
    expected = build_log_sampling_diagnostic(expected_registration, control_outputs, public_means)
    if _json(report) != _json(expected):
        raise LogSamplingDiagnosticError("report differs from independently recomputed diagnostic")


def decode_log_sampling_diagnostic(payload: str) -> dict[str, Any]:
    """Decode strict JSON without treating syntactic validity as verification.

    Parameters
    ----------
    payload
        Caller-bounded JSON text, not a path. Duplicate keys are forbidden.

    Returns
    -------
    dict
        Unverified object; pass it to ``validate_log_sampling_diagnostic`` next.

    Raises
    ------
    LogSamplingDiagnosticError
        On invalid JSON, duplicate keys or nonfinite/non-object content.
    """

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in items:
            if key in obj:
                raise LogSamplingDiagnosticError("duplicate JSON key")
            obj[key] = value
        return obj

    if type(payload) is not str:
        raise LogSamplingDiagnosticError("JSON payload must be text")

    def number(token: str) -> float:
        numeric = float(token)
        if not math.isfinite(numeric) or (numeric == 0 and Decimal(token) != 0):
            raise LogSamplingDiagnosticError("JSON float overflows or underflows")
        return numeric

    try:
        value = json.loads(payload, object_pairs_hook=pairs, parse_float=number)
    except (ValueError, RecursionError, DecimalException) as error:
        raise LogSamplingDiagnosticError("invalid diagnostic JSON") from error
    _json(value)
    if type(value) is not dict:
        raise LogSamplingDiagnosticError("diagnostic must be an object")
    return value
