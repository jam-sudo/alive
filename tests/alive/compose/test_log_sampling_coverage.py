"""Synthetic-only draft coverage checks; no runtime/guard mocks."""

from copy import deepcopy

import pytest

from alive.compose.log_sampling_coverage import validate_synthetic_log_sampling_coverage
from alive.compose.log_sampling_report import LogSamplingDiagnosticError


@pytest.fixture
def coverage():
    models = [
        {"training_seed": seed, "checkpoint_sha256": "a" * 64, "frozen_state_sha256": "b" * 64}
        for seed in (11, 12)
    ]
    units = []
    for seed in (11, 12):
        for condition, role in (
            ({"kind": "single", "gene_id": "A_with_separator"}, "singles"),
            ({"kind": "combo", "gene_ids": ["A", "B"]}, "combo_calibration"),
        ):
            units.append(
                {
                    "unit": {"condition": condition, "role": role, "training_seed": seed},
                    "public_schedule": [
                        {
                            "repeat_index": i,
                            "sampling_seed": 40 + i,
                            "initial_rng_state_sha256": "c" * 64,
                            "call_order": i,
                        }
                        for i in range(2)
                    ],
                }
            )
    return units, models


def test_exact_synthetic_coverage_returns_no_admission_and_does_not_mutate(coverage):
    units, models = coverage
    before = deepcopy(coverage)
    result = validate_synthetic_log_sampling_coverage(
        units, models, expected_units=before[0], expected_models=before[1]
    )
    assert result is None
    assert coverage == before


def test_empty_public_schedule_is_only_structurally_accepted(coverage):
    units, models = coverage
    for unit in units:
        unit["public_schedule"] = []
    assert (
        validate_synthetic_log_sampling_coverage(
            units, models, expected_units=deepcopy(units), expected_models=deepcopy(models)
        )
        is None
    )


@pytest.mark.parametrize(
    "fault",
    [
        "empty",
        "tuple",
        "duplicate_unit",
        "missing_model",
        "extra_model",
        "duplicate_model",
        "bool_seed",
        "negative_seed",
        "extra_key",
        "missing_key",
        "unit_checkpoint",
        "wrong_role",
        "unknown_kind",
        "padded_gene",
        "surrogate_gene",
        "combo_order",
        "combo_duplicate",
        "combo_shape",
        "bad_sha",
        "uppercase_sha",
        "null_schedule",
        "duplicate_repeat",
        "duplicate_order",
        "bool_sampling_seed",
        "negative_index",
        "nan",
        "cycle",
    ],
)
@pytest.mark.parametrize("side", ["candidate", "expected"])
def test_malformed_records_reject_in_own_frame(coverage, fault, side):
    units, models = deepcopy(coverage)
    if fault == "empty":
        units.clear()
    elif fault == "tuple":
        units = tuple(units)
    elif fault == "duplicate_unit":
        units.append(deepcopy(units[0]))
    elif fault == "missing_model":
        models.pop()
    elif fault == "extra_model":
        models.append({**models[0], "training_seed": 13})
    elif fault == "duplicate_model":
        models.append(deepcopy(models[0]))
    elif fault == "bool_seed":
        models[0]["training_seed"] = True
    elif fault == "negative_seed":
        units[0]["unit"]["training_seed"] = -1
    elif fault == "extra_key":
        units[0]["admission"] = "ELIGIBLE"
    elif fault == "missing_key":
        del units[0]["unit"]["role"]
    elif fault == "unit_checkpoint":
        units[0]["checkpoint_sha256"] = "d" * 64
    elif fault == "wrong_role":
        units[0]["unit"]["role"] = "combo_calibration"
    elif fault == "unknown_kind":
        units[0]["unit"]["condition"]["kind"] = "control"
    elif fault == "padded_gene":
        units[0]["unit"]["condition"]["gene_id"] = " A"
    elif fault == "surrogate_gene":
        units[0]["unit"]["condition"]["gene_id"] = "\ud800"
    elif fault == "combo_order":
        units[1]["unit"]["condition"]["gene_ids"] = ["B", "A"]
    elif fault == "combo_duplicate":
        units[1]["unit"]["condition"]["gene_ids"] = ["A", "A"]
    elif fault == "combo_shape":
        units[1]["unit"]["condition"]["gene_ids"] = ["A"]
    elif fault == "bad_sha":
        models[0]["checkpoint_sha256"] = "bad"
    elif fault == "uppercase_sha":
        models[0]["checkpoint_sha256"] = "A" * 64
    elif fault == "null_schedule":
        units[0]["public_schedule"] = None
    elif fault == "duplicate_repeat":
        units[0]["public_schedule"][1]["repeat_index"] = 0
    elif fault == "duplicate_order":
        units[0]["public_schedule"][1]["call_order"] = 0
    elif fault == "bool_sampling_seed":
        units[0]["public_schedule"][0]["sampling_seed"] = False
    elif fault == "negative_index":
        units[0]["public_schedule"][0]["repeat_index"] = -1
    elif fault == "nan":
        units[0]["public_schedule"][0]["sampling_seed"] = float("nan")
    else:
        units[0]["cycle"] = units
    candidates = (units, models) if side == "candidate" else coverage
    expected = coverage if side == "candidate" else (units, models)
    caught = None
    try:
        validate_synthetic_log_sampling_coverage(
            *candidates, expected_units=expected[0], expected_models=expected[1]
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, f"accepted malformed {side}: {fault}"


@pytest.mark.parametrize(
    "fault", ["checkpoint", "state", "gene", "seed", "schedule", "unit_order", "model_order"]
)
def test_structurally_valid_changes_cannot_replace_external_expectations(coverage, fault):
    units, models = deepcopy(coverage)
    if fault == "checkpoint":
        models[0]["checkpoint_sha256"] = "d" * 64
    elif fault == "state":
        models[0]["frozen_state_sha256"] = "d" * 64
    elif fault == "gene":
        units[0]["unit"]["condition"]["gene_id"] = "Other"
    elif fault == "seed":
        models[0]["training_seed"] = 99
        for unit in units[:2]:
            unit["unit"]["training_seed"] = 99
    elif fault == "schedule":
        units[0]["public_schedule"][0]["sampling_seed"] = 99
    elif fault == "unit_order":
        units.reverse()
    else:
        models.reverse()
    caught = None
    try:
        validate_synthetic_log_sampling_coverage(
            units, models, expected_units=coverage[0], expected_models=coverage[1]
        )
    except LogSamplingDiagnosticError as error:
        caught = error
    assert caught is not None, f"external {fault} binding was bypassed"
