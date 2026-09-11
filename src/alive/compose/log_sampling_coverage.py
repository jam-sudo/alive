"""Synthetic structural checks, not scientific registration or source verification."""

from typing import Any

from alive.compose.log_sampling_report import LogSamplingDiagnosticError, _json


def _keys(value: Any, keys: set[str]) -> None:
    if type(value) is not dict or set(value) != keys:
        raise LogSamplingDiagnosticError("coverage record keys differ from the draft")


def _natural(value: Any) -> None:
    if type(value) is not int or value < 0:
        raise LogSamplingDiagnosticError("coverage index/seed must be a nonnegative integer")


def _name(value: Any) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise LogSamplingDiagnosticError("coverage identity must be an unpadded string")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise LogSamplingDiagnosticError("gene identity is not UTF-8 encodable") from error


def _sha(value: Any) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise LogSamplingDiagnosticError("coverage binding must be lowercase SHA-256")


def _condition(value: Any, role: Any) -> None:
    if type(value) is not dict:
        raise LogSamplingDiagnosticError("condition must be an object")
    kind = value.get("kind")
    if kind == "single":
        _keys(value, {"kind", "gene_id"})
        _name(value["gene_id"])
        expected_role = "singles"
    elif kind == "combo":
        _keys(value, {"kind", "gene_ids"})
        genes = value["gene_ids"]
        if type(genes) is not list or len(genes) != 2:
            raise LogSamplingDiagnosticError("combo needs two gene identities")
        for gene in genes:
            _name(gene)
        ordered = genes[0].encode("utf-8") < genes[1].encode("utf-8")
        if not ordered:
            raise LogSamplingDiagnosticError("combo must be distinct and UTF-8 byte ordered")
        expected_role = "combo_calibration"
    else:
        raise LogSamplingDiagnosticError("unknown condition kind")
    if role != expected_role:
        raise LogSamplingDiagnosticError("condition and role disagree")


def _coverage(units: Any, models: Any) -> None:
    _json([units, models])
    if type(units) is not list or not units or type(models) is not list or not models:
        raise LogSamplingDiagnosticError("units/models must be nonempty JSON arrays")
    model_seeds: set[int] = set()
    for model in models:
        _keys(model, {"training_seed", "checkpoint_sha256", "frozen_state_sha256"})
        seed = model["training_seed"]
        _natural(seed)
        if seed in model_seeds:
            raise LogSamplingDiagnosticError("duplicate seed model binding")
        model_seeds.add(seed)
        _sha(model["checkpoint_sha256"])
        _sha(model["frozen_state_sha256"])
    unit_seeds: set[int] = set()
    identities: set[str] = set()
    for record in units:
        _keys(record, {"unit", "public_schedule"})
        unit = record["unit"]
        _keys(unit, {"condition", "role", "training_seed"})
        _condition(unit["condition"], unit["role"])
        _natural(unit["training_seed"])
        unit_seeds.add(unit["training_seed"])
        identity = _json(unit)
        if identity in identities:
            raise LogSamplingDiagnosticError("duplicate unit identity")
        identities.add(identity)
        schedule = record["public_schedule"]
        if type(schedule) is not list:
            raise LogSamplingDiagnosticError("public schedule must be a JSON array")
        repeats: set[int] = set()
        orders: set[int] = set()
        for repeat in schedule:
            _keys(
                repeat, {"repeat_index", "sampling_seed", "initial_rng_state_sha256", "call_order"}
            )
            for key in ("repeat_index", "sampling_seed", "call_order"):
                _natural(repeat[key])
            _sha(repeat["initial_rng_state_sha256"])
            if repeat["repeat_index"] in repeats or repeat["call_order"] in orders:
                raise LogSamplingDiagnosticError("duplicate repeat index/call order within unit")
            repeats.add(repeat["repeat_index"])
            orders.add(repeat["call_order"])
    if unit_seeds != model_seeds:
        raise LogSamplingDiagnosticError("model and unit seed sets differ")


def validate_synthetic_log_sampling_coverage(
    units: Any,
    models: Any,
    *,
    expected_units: Any,
    expected_models: Any,
) -> None:
    """Check draft nested records and exact caller-supplied ordered coverage.

    Parameters
    ----------
    units, models
        Untrusted Registered unit and Seed model binding arrays.
    expected_units, expected_models
        Independently supplied expectations, never extracted from the candidates.

    Raises
    ------
    LogSamplingDiagnosticError
        On malformed records, seed coverage errors or any expected-content mismatch.

    Notes
    -----
    Success establishes only structural equality. It authenticates no source roles,
    policies, checkpoint bytes, sampler behavior or scientific admission.
    """
    _coverage(expected_units, expected_models)
    _coverage(units, models)
    if _json([units, models]) != _json([expected_units, expected_models]):
        raise LogSamplingDiagnosticError("coverage differs from external expectations")
