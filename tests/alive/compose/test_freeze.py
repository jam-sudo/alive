"""Tests for alive.compose.freeze — written FIRST per TDD protocol (Task 2a-11).

The :class:`FrozenPredictionBundle` is the Phase-2a -> Phase-2b handoff (plan §2.5).
It carries the method roster, the sealed pair IDs grouped by role, the *predictions
only* (NEVER measured pair outcomes), the upstream checksums, the selected
hyperparameters/seeds and the development diagnostics + futility status. It is
written ONCE and its checksum binds every upstream artifact.

Load-bearing contracts under test (brief steps 6-8, plan §2.5):

  * the bundle contains NO measured outcomes — only predictions
    (:meth:`FrozenPredictionBundle.assert_no_outcomes` and a structural scan);
  * a recursively-injected sealed reference (sealed role / sealed key / sealed
    path) anywhere in the bundle inputs is REJECTED;
  * :meth:`verify` recomputes the bundle checksum and the per-prediction checks,
    so mutating ANY upstream artifact / prediction after freezing FAILS
    verification;
  * every prediction is finite, correctly shaped and keyed by a canonical pair ID
    drawn from the registered sealed pair set for its role;
  * the method roster must be the complete registered roster;
  * the bundle round-trips through ``to_dict`` / ``from_dict`` byte-stably.
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.compose.freeze import (
    FreezeError,
    FrozenPredictionBundle,
    OutcomeLeakageError,
)

# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

RESPONSE_DIM = 5

ROSTER = (
    "l1_bilinear_identifiable",
    "l2_saturation",
    "l3_hypernetwork",
    "additive",
    "no_change",
    "perturbation_mean",
    "id_only",
    "gears",
    "cpa",
)

DOUBLE_PAIRS = (("g0", "g1"), ("g0", "g2"))
SINGLE_PAIRS = (("g3", "g4"),)


def _preds_for(pairs, *, offset: float = 0.0) -> dict[tuple[str, str], np.ndarray]:
    return {p: np.arange(RESPONSE_DIM, dtype=float) + offset + i for i, p in enumerate(pairs)}


def _roster_preds(pairs) -> dict[str, dict[tuple[str, str], np.ndarray]]:
    return {name: _preds_for(pairs, offset=float(j)) for j, name in enumerate(ROSTER)}


def _bundle(**overrides) -> FrozenPredictionBundle:
    kwargs = dict(
        run_id="deadbeefcafef00d",
        method_roster=ROSTER,
        pair_ids_double_unseen=DOUBLE_PAIRS,
        pair_ids_single_unseen=SINGLE_PAIRS,
        predictions_double_unseen=_roster_preds(DOUBLE_PAIRS),
        predictions_single_unseen=_roster_preds(SINGLE_PAIRS),
        response_space_checksum="rs-checksum",
        factor_checksum="zf-checksum",
        model_checksum="model-checksum",
        manifest_checksum="manifest-checksum",
        selected_k_total=4,
        selected_lambda=1e-3,
        registered_seeds=(11, 23, 37),
        futility_status="CONTINUE",
        dev_diagnostics={"oof_theta": 0.42, "rank": 10, "sym_dim": 10},
        response_dim=RESPONSE_DIM,
    )
    kwargs.update(overrides)
    return FrozenPredictionBundle.create(**kwargs)


# --------------------------------------------------------------------------- #
# happy path + checksum
# --------------------------------------------------------------------------- #
def test_create_seals_a_checksum_and_verifies():
    b = _bundle()
    assert isinstance(b.bundle_checksum, str) and len(b.bundle_checksum) == 64
    # verify() must pass on a freshly created, untampered bundle
    b.verify()


def test_create_is_deterministic_checksum():
    assert _bundle().bundle_checksum == _bundle().bundle_checksum


def test_roundtrip_to_from_dict_preserves_checksum_and_predictions():
    b = _bundle()
    d = b.to_dict()
    b2 = FrozenPredictionBundle.from_dict(d)
    assert b2.bundle_checksum == b.bundle_checksum
    b2.verify()
    np.testing.assert_array_equal(
        b2.predictions_double_unseen["additive"][("g0", "g1")],
        b.predictions_double_unseen["additive"][("g0", "g1")],
    )


def test_write_and_load_roundtrip(tmp_path):
    b = _bundle()
    path = tmp_path / "bundle.json"
    b.write(path)
    assert path.exists()
    loaded = FrozenPredictionBundle.load(path)
    assert loaded.bundle_checksum == b.bundle_checksum
    loaded.verify()


def test_write_is_once_only(tmp_path):
    b = _bundle()
    path = tmp_path / "bundle.json"
    b.write(path)
    with pytest.raises(FreezeError, match="write-once|already exists"):
        b.write(path)


# --------------------------------------------------------------------------- #
# NO measured outcomes in the bundle
# --------------------------------------------------------------------------- #
def test_assert_no_outcomes_passes_for_predictions_only():
    _bundle().assert_no_outcomes()  # does not raise


def test_no_measured_outcome_keys_anywhere_in_dict():
    d = _bundle().to_dict()
    # structurally scan the serialised bundle for any measured-outcome marker
    forbidden = ("measured", "truth", "eps_obs", "observed", "outcome", "y_true", "sealed_eps")

    def _scan(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert not any(tok in str(k).casefold() for tok in forbidden), (
                    f"measured-outcome key leaked into bundle: {k!r}"
                )
                _scan(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                _scan(v)

    _scan(d)


def test_create_rejects_a_measured_outcome_field():
    # any attempt to smuggle an outcome-bearing mapping must be refused
    with pytest.raises(OutcomeLeakageError):
        _bundle(dev_diagnostics={"oof_theta": 0.1, "measured_outcomes": [[1.0, 2.0]]})


# --------------------------------------------------------------------------- #
# recursive sealed-reference rejection (injected at multiple nesting levels)
# --------------------------------------------------------------------------- #
def test_rejects_sealed_token_in_diagnostics_top_level():
    with pytest.raises(OutcomeLeakageError):
        _bundle(dev_diagnostics={"note": "loaded sealed_double_unseen outcomes"})


def test_rejects_sealed_token_nested_deep_in_diagnostics():
    deep = {"a": {"b": [{"c": ["x", "path/to/sealed_single_unseen.npy"]}]}}
    with pytest.raises(OutcomeLeakageError):
        _bundle(dev_diagnostics=deep)


def test_rejects_sealed_token_in_method_roster():
    with pytest.raises(OutcomeLeakageError):
        _bundle(
            method_roster=ROSTER + ("sealed_double_unseen_reader",),
            predictions_double_unseen={
                **_roster_preds(DOUBLE_PAIRS),
                "sealed_double_unseen_reader": _preds_for(DOUBLE_PAIRS),
            },
            predictions_single_unseen={
                **_roster_preds(SINGLE_PAIRS),
                "sealed_double_unseen_reader": _preds_for(SINGLE_PAIRS),
            },
        )


# --------------------------------------------------------------------------- #
# tamper detection — mutating any upstream artifact fails verify()
# --------------------------------------------------------------------------- #
def test_verify_fails_when_upstream_checksum_mutated():
    b = _bundle()
    # mutate a recorded upstream checksum on the frozen dataclass after sealing
    object.__setattr__(b, "response_space_checksum", "tampered")
    with pytest.raises(FreezeError, match="checksum"):
        b.verify()


def test_verify_fails_when_a_prediction_mutated():
    b = _bundle()
    b.predictions_double_unseen["additive"][("g0", "g1")][0] = 999.0
    with pytest.raises(FreezeError, match="checksum"):
        b.verify()


def test_verify_fails_when_run_id_mutated():
    b = _bundle()
    object.__setattr__(b, "run_id", "0000000000000000")
    with pytest.raises(FreezeError, match="checksum"):
        b.verify()


def test_loaded_then_tampered_file_fails_verify(tmp_path):
    import json

    b = _bundle()
    path = tmp_path / "bundle.json"
    b.write(path)
    raw = json.loads(path.read_text())
    # flip a single recorded checksum in the on-disk file
    raw["manifest_checksum"] = "tampered-on-disk"
    path.write_text(json.dumps(raw))
    loaded = FrozenPredictionBundle.load(path)
    with pytest.raises(FreezeError, match="checksum"):
        loaded.verify()


# --------------------------------------------------------------------------- #
# prediction / roster validation
# --------------------------------------------------------------------------- #
def test_rejects_non_finite_prediction():
    preds = _roster_preds(DOUBLE_PAIRS)
    preds["additive"][("g0", "g1")][0] = np.inf
    with pytest.raises(FreezeError, match="finite"):
        _bundle(predictions_double_unseen=preds)


def test_rejects_wrong_shape_prediction():
    preds = _roster_preds(DOUBLE_PAIRS)
    preds["additive"][("g0", "g1")] = np.zeros(RESPONSE_DIM + 1)
    with pytest.raises(FreezeError, match="shape|dimension"):
        _bundle(predictions_double_unseen=preds)


def test_rejects_non_canonical_pair_id():
    bad = (("g1", "g0"),)  # not (min, max) by UTF-8
    with pytest.raises(FreezeError, match="canonical"):
        _bundle(
            pair_ids_double_unseen=bad,
            predictions_double_unseen=_roster_preds(bad),
        )


def test_rejects_prediction_for_unregistered_pair():
    preds = _roster_preds(DOUBLE_PAIRS)
    preds["additive"][("g0", "g9")] = np.zeros(RESPONSE_DIM)  # not a registered pair
    with pytest.raises(FreezeError, match="unregistered|extra|registered"):
        _bundle(predictions_double_unseen=preds)


def test_rejects_method_missing_a_registered_pair():
    preds = _roster_preds(DOUBLE_PAIRS)
    del preds["additive"][("g0", "g1")]
    with pytest.raises(FreezeError, match="missing"):
        _bundle(predictions_double_unseen=preds)


def test_rejects_incomplete_method_roster():
    incomplete = ("l1_bilinear_identifiable", "additive")
    with pytest.raises(FreezeError, match="roster"):
        _bundle(
            method_roster=incomplete,
            predictions_double_unseen={k: _preds_for(DOUBLE_PAIRS) for k in incomplete},
            predictions_single_unseen={k: _preds_for(SINGLE_PAIRS) for k in incomplete},
        )


def test_rejects_unregistered_extra_method():
    extra = ROSTER + ("post_hoc_model",)
    with pytest.raises(FreezeError, match="exactly|roster"):
        _bundle(
            method_roster=extra,
            predictions_double_unseen={k: _preds_for(DOUBLE_PAIRS) for k in extra},
            predictions_single_unseen={k: _preds_for(SINGLE_PAIRS) for k in extra},
        )


def test_rejects_roster_method_without_predictions():
    preds = _roster_preds(DOUBLE_PAIRS)
    del preds["l3_hypernetwork"]
    with pytest.raises(FreezeError, match="l3_hypernetwork|missing|method"):
        _bundle(predictions_double_unseen=preds)
