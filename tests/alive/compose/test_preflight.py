"""Tests for alive.compose.preflight — the OUTCOME-FREE Phase-2b preflight.

TDD order: tests written first; the implementation must pass all of them.

Phase 2b opens the COMPOSE seal exactly once and produces the confirmatory
verdict. This module is Task 2 of 8 — the preflight that validates everything
BEFORE the seal is touched and freezes the validated NON-outcome evaluation
inputs into an :class:`EvaluationLock`. The lock carries predictions / IDs /
hashes / thresholds / seeds but NO measured outcomes.

Load-bearing contracts under test (Task 2b-2 brief):

  * :func:`run_preflight` is structurally OUTCOME-FREE — it never accepts or
    touches a :class:`ComposeOutcomeStore`, a sealed truth or any observed data;
  * it FAILS CLOSED with :class:`PreflightError` on the FIRST reasonable
    violation (no ``all([])`` / "available comparator" behaviour: a missing OR
    extra registered method / pair / prediction is a FAILURE, not a pass);
  * on success it returns a fully-populated :class:`EvaluationLock` carrying only
    role-labelled pair IDs, predictions, thresholds, verified hashes and seeds —
    and NO measured outcomes;
  * outcome-freedom is proven STRUCTURALLY: ``run_preflight`` has no
    outcome-store / observed-data parameter, so there is nothing to access. This
    is asserted directly against :func:`inspect.signature` rather than via a spy
    store the function never receives (which could only ever be vacuously true).

SYNTHETIC-ONLY: pure ``numpy`` on synthetic fixtures only; NO real Norman,
NO seal open, NO sealed-outcome read.
"""

from __future__ import annotations

import dataclasses
import inspect

import numpy as np
import pytest

from alive.compose.config2 import load_compose_phase2_config
from alive.compose.freeze import FrozenPredictionBundle, OutcomeLeakageError
from alive.compose.outcome_store import ComposeOutcomeStore
from alive.compose.phase2a import Phase2aResult, run_phase2a_fixture
from alive.compose.preflight import EvaluationLock, PreflightError, run_preflight

# Reuse the Phase-2a synthetic fixture builders so the bundle is real and
# self-consistent (full control of roster / pairs / predictions / checksums).
from tests.alive.compose.test_phase2a import (
    _HASHES,
    _build_instance,
    _inputs,
    _store,
)

_CONFIG_PATH = "configs/compose_k562_v1_phase2.yaml"

# Fixture provenance digests — must match the Phase-2a fixture's so the
# recomputed composite run id equals the bundle's.
_DATA_CARD_DIGEST = "data-card-checksum"
_RAW_DIGEST = "raw-data-checksum"
_SEQ_DIGEST = "sequence-mapping-checksum"
_EXPECTED_RESPONSE_DIM = 7  # _build_instance default p


# --------------------------------------------------------------------------- #
# fixture builders
# --------------------------------------------------------------------------- #
def _phase2a_result(seed: int = 0) -> tuple[Phase2aResult, dict]:
    """Run the Phase-2a fixture and return its CONTINUE result + instance."""
    rng = np.random.default_rng(seed)
    inst = _build_instance(rng)
    res = run_phase2a_fixture(_inputs(inst), _store(inst), expected_hashes=_HASHES)
    assert res.futility_status == "CONTINUE"
    assert res.bundle is not None
    assert res.ledger is not None
    return res, inst


def _pair_manifest_for(bundle: FrozenPredictionBundle) -> dict:
    """Build a pair manifest whose roles match the bundle and whose checksum
    equals the bundle's bound ``manifest_checksum`` (the fixture literal).
    """
    return {
        "roles": {
            "combo_calibration": [],
            "sealed_double_unseen": [list(p) for p in bundle.pair_ids_double_unseen],
            "sealed_single_unseen": [list(p) for p in bundle.pair_ids_single_unseen],
        },
        "checksum": bundle.manifest_checksum,
    }


def _tampered_ledger(res: Phase2aResult, *, artifact: str, value: str):
    """Rebuild a RunLedger identical to ``res.ledger`` except one artifact sha.

    Used to prove the bundle/ledger checksum-agreement check fails closed when
    a recorded artifact disagrees with the bundle.
    """
    from alive.provenance import EnvironmentInfo, RunLedger

    src = res.ledger.to_dict()
    env_raw = src["environment"]
    env = EnvironmentInfo(
        python_version=env_raw["python_version"],
        platform=env_raw["platform"],
        git_commit=env_raw["git_commit"],
        lockfile_sha256=env_raw["lockfile_sha256"],
        registered_seeds=tuple(env_raw["registered_seeds"]),
    )
    led = RunLedger(
        run_id=src["run_id"],
        config_sha256=src["config_sha256"],
        environment=env,
    )
    for art in src["artifacts"]:
        sha = value if art["name"] == artifact else art["sha256"]
        led.record_artifact(art["name"], sha)
    return led


def _preflight_kwargs(res: Phase2aResult, *, manifest=None, ledger=None, **overrides):
    """Assemble the standard run_preflight kwargs from a Phase-2a result."""
    bundle = res.bundle
    config = load_compose_phase2_config(_CONFIG_PATH)
    kwargs = dict(
        bundle=bundle,
        pair_manifest=manifest if manifest is not None else _pair_manifest_for(bundle),
        config=config,
        data_card_digest=_DATA_CARD_DIGEST,
        raw_or_source_digest=_RAW_DIGEST,
        sequence_mapping_digest=_SEQ_DIGEST,
        ledger=ledger if ledger is not None else res.ledger,
        expected_response_dim=_EXPECTED_RESPONSE_DIM,
    )
    kwargs.update(overrides)
    return kwargs


# --------------------------------------------------------------------------- #
# happy path
# --------------------------------------------------------------------------- #
def test_happy_path_returns_valid_lock(tmp_path):
    res, inst = _phase2a_result(seed=0)

    lock = run_preflight(**_preflight_kwargs(res))

    assert isinstance(lock, EvaluationLock)

    bundle = res.bundle
    config = load_compose_phase2_config(_CONFIG_PATH)

    # thresholds
    assert lock.material_margin_vs_additive == config.material_margin_vs_additive
    assert lock.learned_comparator_margin == config.learned_comparator_margin
    # seeds
    assert lock.registered_seeds == bundle.registered_seeds
    assert lock.split_seed == config.split_seed
    # hashes
    assert lock.run_id == bundle.run_id
    assert lock.bundle_checksum == bundle.bundle_checksum
    assert lock.manifest_checksum == bundle.manifest_checksum
    assert lock.response_space_checksum == bundle.response_space_checksum
    assert lock.factor_checksum == bundle.factor_checksum
    assert lock.model_checksum == bundle.model_checksum
    # response dim
    assert lock.response_dim == _EXPECTED_RESPONSE_DIM
    # role-labelled pair IDs
    assert lock.pair_ids_double_unseen == bundle.pair_ids_double_unseen
    assert lock.pair_ids_single_unseen == bundle.pair_ids_single_unseen
    assert set(lock.pair_ids_double_unseen) == set(inst["sealed_double_id"])
    assert set(lock.pair_ids_single_unseen) == set(inst["sealed_single_id"])
    # predictions carried for both regimes, every roster method
    for method in config.method_roster:
        assert set(lock.predictions_double_unseen[method]) == set(bundle.pair_ids_double_unseen)
        assert set(lock.predictions_single_unseen[method]) == set(bundle.pair_ids_single_unseen)
    # a representative prediction vector round-trips exactly
    g, h = bundle.pair_ids_double_unseen[0]
    np.testing.assert_array_equal(
        lock.predictions_double_unseen["additive"][(g, h)],
        bundle.predictions_double_unseen["additive"][(g, h)],
    )


def test_lock_is_frozen_and_outcome_free(tmp_path):
    res, _ = _phase2a_result(seed=1)
    lock = run_preflight(**_preflight_kwargs(res))
    assert dataclasses.is_dataclass(lock)
    with pytest.raises(dataclasses.FrozenInstanceError):
        lock.split_seed = 99  # type: ignore[misc]
    # explicit outcome-free assertion (delegates to the freeze leakage scanner)
    lock.assert_no_outcomes()


def test_lock_prediction_arrays_are_independent_read_only_snapshots():
    res, _ = _phase2a_result(seed=101)
    lock = run_preflight(**_preflight_kwargs(res))
    pair = lock.pair_ids_double_unseen[0]
    locked = lock.predictions_double_unseen["additive"][pair]
    bundled = res.bundle.predictions_double_unseen["additive"][pair]

    assert locked is not bundled
    assert not locked.flags.writeable
    with pytest.raises(ValueError, match="read-only"):
        locked[0] = 123.0


def test_lock_with_smuggled_outcome_marker_is_rejected(tmp_path):
    # The lock's own outcome-free check must fire if a measured-outcome marker is
    # forced into its contents (proving the check is non-vacuous). The check runs
    # in __post_init__, so constructing a tampered lock fails closed.
    res, _ = _phase2a_result(seed=2)
    lock = run_preflight(**_preflight_kwargs(res))
    with pytest.raises(OutcomeLeakageError):
        dataclasses.replace(lock, run_id="run-y_true-xyz")


# --------------------------------------------------------------------------- #
# structural outcome-freedom (the load-bearing safety property)
# --------------------------------------------------------------------------- #
def test_run_preflight_signature_is_structurally_outcome_free():
    """``run_preflight`` exposes NO outcome-store / observed-data parameter.

    This is the genuine, non-vacuous proof of outcome-freedom: if the function
    cannot receive a sealed outcome store / truth / observed population, it
    cannot access one. The test inspects the live signature, so it FAILS the
    moment a future edit adds, e.g., an ``outcome_store`` parameter or a
    :class:`ComposeOutcomeStore`-annotated argument.
    """
    # Names that would smuggle in (or hint at) a measured-outcome / sealed-data
    # input. Substring match, case-insensitive.
    forbidden_substrings = (
        "store",
        "outcome",
        "truth",
        "sealed",
        "observed",
        "population",
        "cells",
    )
    forbidden_annotations = {ComposeOutcomeStore, ComposeOutcomeStore.__name__}

    sig = inspect.signature(run_preflight)
    assert sig.parameters, "run_preflight should take parameters"
    for name, param in sig.parameters.items():
        lowered = name.lower()
        offending = [s for s in forbidden_substrings if s in lowered]
        assert not offending, (
            f"run_preflight parameter {name!r} contains an outcome/store substring "
            f"{offending!r}; the function must be structurally outcome-free"
        )
        ann = param.annotation
        # Tolerate string ('from __future__ import annotations') and real-class
        # annotations alike.
        assert ann not in forbidden_annotations, (
            f"run_preflight parameter {name!r} is annotated as an outcome store "
            f"({ann!r}); the function must be structurally outcome-free"
        )


# --------------------------------------------------------------------------- #
# roster: missing / extra / reordered method
# --------------------------------------------------------------------------- #
def test_missing_method_fails_closed(tmp_path):
    res, _ = _phase2a_result(seed=3)
    bundle = res.bundle
    # drop one roster method from the bundle (and its predictions)
    short_roster = bundle.method_roster[:-1]
    bad = dataclasses.replace(
        bundle,
        method_roster=short_roster,
        predictions_double_unseen={m: bundle.predictions_double_unseen[m] for m in short_roster},
        predictions_single_unseen={m: bundle.predictions_single_unseen[m] for m in short_roster},
    )
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, bundle=bad))


def test_extra_method_fails_closed(tmp_path):
    res, _ = _phase2a_result(seed=4)
    bundle = res.bundle
    extra_roster = bundle.method_roster + ("rogue_method",)
    extra_double = dict(bundle.predictions_double_unseen)
    extra_double["rogue_method"] = dict(bundle.predictions_double_unseen["additive"])
    extra_single = dict(bundle.predictions_single_unseen)
    extra_single["rogue_method"] = dict(bundle.predictions_single_unseen["additive"])
    bad = dataclasses.replace(
        bundle,
        method_roster=extra_roster,
        predictions_double_unseen=extra_double,
        predictions_single_unseen=extra_single,
    )
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, bundle=bad))


def test_reordered_roster_fails_closed(tmp_path):
    res, _ = _phase2a_result(seed=5)
    bundle = res.bundle
    reordered = (bundle.method_roster[1], bundle.method_roster[0]) + bundle.method_roster[2:]
    bad = dataclasses.replace(bundle, method_roster=reordered)
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, bundle=bad))


# --------------------------------------------------------------------------- #
# pairs / predictions: missing / extra / per-method missing prediction
# --------------------------------------------------------------------------- #
def test_missing_pair_in_regime_fails_closed(tmp_path):
    # manifest role has MORE pairs than the bundle predicts (bundle missing one).
    res, _ = _phase2a_result(seed=6)
    bundle = res.bundle
    manifest = _pair_manifest_for(bundle)
    # add a phantom pair to the manifest's double role only.
    manifest["roles"]["sealed_double_unseen"].append(["ZZZ1", "ZZZ2"])
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, manifest=manifest))


def test_extra_pair_in_bundle_fails_closed(tmp_path):
    # bundle has a pair the manifest role does not list.
    res, _ = _phase2a_result(seed=7)
    bundle = res.bundle
    manifest = _pair_manifest_for(bundle)
    # drop a pair from the manifest's double role so the bundle is now a superset.
    manifest["roles"]["sealed_double_unseen"] = manifest["roles"]["sealed_double_unseen"][:-1]
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, manifest=manifest))


def test_method_missing_one_prediction_fails_closed(tmp_path):
    res, _ = _phase2a_result(seed=8)
    bundle = res.bundle
    # remove a single (method, pair) prediction from the double regime.
    double = {m: dict(d) for m, d in bundle.predictions_double_unseen.items()}
    victim_pair = bundle.pair_ids_double_unseen[0]
    del double["additive"][victim_pair]
    bad = dataclasses.replace(bundle, predictions_double_unseen=double)
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, bundle=bad))


def test_method_extra_prediction_fails_closed(tmp_path):
    res, _ = _phase2a_result(seed=18)
    bundle = res.bundle
    double = {m: dict(d) for m, d in bundle.predictions_double_unseen.items()}
    double["additive"][("PHANTOM1", "PHANTOM2")] = np.zeros(_EXPECTED_RESPONSE_DIM)
    bad = dataclasses.replace(bundle, predictions_double_unseen=double)
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, bundle=bad))


# --------------------------------------------------------------------------- #
# prediction validity: wrong shape / non-finite
# --------------------------------------------------------------------------- #
def test_wrong_shape_prediction_fails_closed(tmp_path):
    res, _ = _phase2a_result(seed=9)
    bundle = res.bundle
    double = {m: dict(d) for m, d in bundle.predictions_double_unseen.items()}
    victim = bundle.pair_ids_double_unseen[0]
    double["additive"][victim] = np.zeros(_EXPECTED_RESPONSE_DIM + 1)
    bad = dataclasses.replace(bundle, predictions_double_unseen=double)
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, bundle=bad))


def test_nonfinite_prediction_fails_closed(tmp_path):
    res, _ = _phase2a_result(seed=10)
    bundle = res.bundle
    double = {m: dict(d) for m, d in bundle.predictions_double_unseen.items()}
    victim = bundle.pair_ids_double_unseen[0]
    vec = np.array(double["additive"][victim], dtype=float)
    vec[0] = np.nan
    double["additive"][victim] = vec
    bad = dataclasses.replace(bundle, predictions_double_unseen=double)
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, bundle=bad))


def test_response_dim_mismatch_fails_closed(tmp_path):
    # the caller's expected_response_dim disagrees with the bundle's.
    res, _ = _phase2a_result(seed=19)
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, expected_response_dim=_EXPECTED_RESPONSE_DIM + 1))


# --------------------------------------------------------------------------- #
# run-id recompute mismatch
# --------------------------------------------------------------------------- #
def test_run_id_recompute_mismatch_fails_closed(tmp_path):
    res, _ = _phase2a_result(seed=11)
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, data_card_digest="WRONG-DIGEST"))


# --------------------------------------------------------------------------- #
# ledger / bundle checksum mismatch
# --------------------------------------------------------------------------- #
def test_ledger_bundle_checksum_mismatch_fails_closed(tmp_path):
    res, _ = _phase2a_result(seed=12)
    bad_ledger = _tampered_ledger(res, artifact="frozen_prediction_bundle", value="TAMPERED")
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, ledger=bad_ledger))


def test_ledger_upstream_artifact_mismatch_fails_closed(tmp_path):
    # a mismatch on a non-bundle artifact (response_space) must also fail closed.
    res, _ = _phase2a_result(seed=20)
    bad_ledger = _tampered_ledger(res, artifact="response_space", value="TAMPERED")
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, ledger=bad_ledger))


# --------------------------------------------------------------------------- #
# futility status guard
# --------------------------------------------------------------------------- #
def test_futility_stopped_bundle_fails_closed(tmp_path):
    res, _ = _phase2a_result(seed=13)
    # a frozen bundle whose dev run was futility-stopped must be refused.
    bad = dataclasses.replace(res.bundle, futility_status="FUTILITY_STOPPED")
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, bundle=bad))


# --------------------------------------------------------------------------- #
# manifest checksum mismatch
# --------------------------------------------------------------------------- #
def test_manifest_checksum_mismatch_fails_closed(tmp_path):
    res, _ = _phase2a_result(seed=14)
    manifest = _pair_manifest_for(res.bundle)
    manifest["checksum"] = "DIFFERENT-CHECKSUM"
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, manifest=manifest))


# --------------------------------------------------------------------------- #
# bundle tamper (checksum integrity) fails the bundle.verify() gate
# --------------------------------------------------------------------------- #
def test_tampered_bundle_checksum_fails_closed(tmp_path):
    res, _ = _phase2a_result(seed=15)
    # mutate a recorded checksum without recomputing -> bundle.verify() raises.
    bad = dataclasses.replace(res.bundle, model_checksum="MUTATED-AFTER-FREEZE")
    with pytest.raises(PreflightError):
        run_preflight(**_preflight_kwargs(res, bundle=bad))
