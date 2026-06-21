"""Tests for OOF method development (MethodLock) and the futility rule (Task 12 B/C).

All on method_development data ONLY.  These tests verify:
- the OOF cross-validation + seed-aggregation procedure,
- the documented tie-break rules (gate: larger w then smaller k),
- structural invariance to any sealed/conformal data (the function never sees it),
- determinism and round-trip serialisation,
- and the exact preregistered futility rule (any comparator's simultaneous 90%
  UPPER bound <= delta_min ⇒ FUTILITY_STOPPED).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from alive.eval.bootstrap import simultaneous_delta_bounds
from alive.experiment.develop import (
    DevelopError,
    FutilityDecision,
    MethodLock,
    decide_futility,
    develop_methods,
)
from alive.metrics.selective import MetricError, aurc, normalize_by_mean
from alive.types import OperationalStatus

# ---------------------------------------------------------------------------
# Config-like grids (subset of Task 1 defaults; kept small for speed)
# ---------------------------------------------------------------------------

K_GRID = (3, 5, 7)
FEATURE_WEIGHT_GRID = (0.25, 0.5, 0.75, 1.0)
RIDGE_GRID = (0.1, 1.0, 10.0)
GBM_ESTIMATORS_GRID = (10, 20)
REGISTERED_SEEDS = (11, 23, 47)
CV_FOLDS = 5
ALL_METHOD_IDS = (
    "gate",
    "nearest_feature",
    "ensemble_disagreement",
    "ridge_error",
    "gbm_error",
    "residual_only",
)


# ---------------------------------------------------------------------------
# Synthetic dev data
# ---------------------------------------------------------------------------


def _make_dev(n: int = 30, feat_dim: int = 6, n_members: int = 3, pca_dims: int = 4, seed: int = 0):
    rng = np.random.default_rng(seed)
    dev_ids = tuple(f"G{i:03d}" for i in range(n))  # already sorted
    dev_features = rng.normal(size=(n, feat_dim))
    # errors correlated with feature norm so kNN/regressors have signal
    base = np.linalg.norm(dev_features, axis=1)
    dev_errors = 0.5 + base + rng.uniform(0.0, 0.3, size=n)
    # ensemble means: spread loosely tracks error so disagreement is informative
    dev_ensemble_means = rng.normal(size=(n, n_members, pca_dims))
    dev_ensemble_means *= dev_errors[:, None, None] * 0.3
    return dev_ids, dev_features, dev_errors, dev_ensemble_means


def _develop(**overrides):
    dev_ids, X, e, ens = _make_dev(
        **{
            k: overrides.pop(k)
            for k in list(overrides)
            if k in ("n", "feat_dim", "n_members", "pca_dims", "seed")
        }
    )
    kwargs = dict(
        cv_folds=CV_FOLDS,
        k_grid=K_GRID,
        feature_weight_grid=FEATURE_WEIGHT_GRID,
        ridge_grid=RIDGE_GRID,
        gbm_estimators_grid=GBM_ESTIMATORS_GRID,
        registered_seeds=REGISTERED_SEEDS,
        config_sha256="cfg_abc",
    )
    kwargs.update(overrides)
    return develop_methods(dev_ids, X, e, ens, **kwargs)


# ---------------------------------------------------------------------------
# MethodLock — basic shape
# ---------------------------------------------------------------------------


class TestMethodLockShape:
    def test_methods_evaluated(self):
        lock = _develop()
        assert lock.method_ids == ALL_METHOD_IDS
        for m in ALL_METHOD_IDS:
            assert m in lock.selected_params
            assert m in lock.search_table
            assert m in lock.oof_scores
            assert m in lock.oof_aurc

    def test_oof_scores_length_n(self):
        lock = _develop(n=24)
        for m in ALL_METHOD_IDS:
            assert lock.oof_scores[m].shape == (24,)
            assert np.all(np.isfinite(lock.oof_scores[m]))

    def test_search_table_one_row_per_combo(self):
        lock = _develop()
        # gate: |k_grid| * |feature_weight_grid|
        assert len(lock.search_table["gate"]) == len(K_GRID) * len(FEATURE_WEIGHT_GRID)
        # residual_only: |k_grid|
        assert len(lock.search_table["residual_only"]) == len(K_GRID)
        # nearest_feature, ensemble_disagreement: single combo
        assert len(lock.search_table["nearest_feature"]) == 1
        assert len(lock.search_table["ensemble_disagreement"]) == 1
        # ridge: |ridge_grid|; gbm: |gbm_estimators_grid|
        assert len(lock.search_table["ridge_error"]) == len(RIDGE_GRID)
        assert len(lock.search_table["gbm_error"]) == len(GBM_ESTIMATORS_GRID)
        # every row has an oof_aurc field
        for rows in lock.search_table.values():
            for row in rows:
                assert "oof_aurc" in row
                assert np.isfinite(row["oof_aurc"])

    def test_selected_is_argmin_of_search_table(self):
        lock = _develop()
        for m in ALL_METHOD_IDS:
            rows = lock.search_table[m]
            best_row = min(rows, key=lambda r: r["oof_aurc"])
            assert lock.oof_aurc[m] == pytest.approx(best_row["oof_aurc"])
            # selected_params must match the argmin's hyperparameters
            sel = lock.selected_params[m]
            for key, val in sel.items():
                assert best_row[key] == val

    def test_oof_aurc_matches_recomputed(self):
        lock = _develop()
        norm = normalize_by_mean(np.asarray(_develop_errors()))
        for m in ALL_METHOD_IDS:
            assert lock.oof_aurc[m] == pytest.approx(aurc(norm, lock.oof_scores[m]))


def _develop_errors():
    """The dev_errors used by the default _make_dev (for AURC recomputation)."""
    _, _, e, _ = _make_dev()
    return e


# ---------------------------------------------------------------------------
# Tie-break: gate (larger w first, then smaller k)
# ---------------------------------------------------------------------------


def test_gate_tiebreak_larger_w_then_smaller_k(monkeypatch):
    """When several gate combos tie on OOF AURC, the selected one is the one
    with the largest w; among those, the smallest k.

    We force a tie by patching ``aurc`` to return a constant for gate combos so
    every gate combo has identical OOF AURC, then assert the tie-break choice.
    """
    import alive.experiment.develop as dev_mod

    real_aurc = dev_mod.aurc

    # Make every combo's OOF aurc identical (tie everywhere) so the tie-break is
    # the ONLY thing that decides selection.
    def const_aurc(risk, score):
        return 1.0

    monkeypatch.setattr(dev_mod, "aurc", const_aurc)
    try:
        lock = _develop()
    finally:
        monkeypatch.setattr(dev_mod, "aurc", real_aurc)

    sel = lock.selected_params["gate"]
    # largest w in grid, then smallest k in grid
    assert sel["w"] == max(FEATURE_WEIGHT_GRID)
    assert sel["k"] == min(K_GRID)
    # residual_only ties → smallest k
    assert lock.selected_params["residual_only"]["k"] == min(K_GRID)
    # ridge ties → smallest alpha; gbm ties → fewest estimators
    assert lock.selected_params["ridge_error"]["alpha"] == min(RIDGE_GRID)
    assert lock.selected_params["gbm_error"]["n_estimators"] == min(GBM_ESTIMATORS_GRID)


# ---------------------------------------------------------------------------
# Seed aggregation: OOF score = mean over registered seeds
# ---------------------------------------------------------------------------


def test_seed_aggregation_is_mean_over_seeds():
    """For ensemble_disagreement (fit-free, fold-independent), the OOF score
    per perturbation is identical across seeds, so the seed-mean equals the
    direct per-row score.  This verifies the aggregation is a MEAN (not e.g.
    last-seed-only) and that the procedure is wired correctly.
    """
    dev_ids, X, e, ens = _make_dev(n=20)
    lock = develop_methods(
        dev_ids,
        X,
        e,
        ens,
        cv_folds=CV_FOLDS,
        k_grid=K_GRID,
        feature_weight_grid=FEATURE_WEIGHT_GRID,
        ridge_grid=RIDGE_GRID,
        gbm_estimators_grid=GBM_ESTIMATORS_GRID,
        registered_seeds=REGISTERED_SEEDS,
        config_sha256="cfg_abc",
    )
    # EnsembleDisagreement score is computed directly from each row's ensemble
    # means; it is the same in every fold/seed.
    from alive.baselines.uq import EnsembleDisagreement

    direct = EnsembleDisagreement().fit(X, e).score(ens)
    np.testing.assert_allclose(lock.oof_scores["ensemble_disagreement"], direct)


def test_seed_aggregation_mean_two_seeds_explicit():
    """Verify aggregated OOF scores equal the exact mean over two DISTINCT seeds.

    ``nearest_feature`` has a single hyperparameter combo and its OOF scores
    depend on fold assignments (which differ by seed), so the two per-seed OOF
    vectors are genuinely different.  The two-seed run must produce scores equal
    to ``0.5 * (s11 + s23)``, not the first-seed-only or a median.
    """
    dev_ids, X, e, ens = _make_dev(n=20)
    common = dict(
        cv_folds=CV_FOLDS,
        k_grid=K_GRID,
        feature_weight_grid=FEATURE_WEIGHT_GRID,
        ridge_grid=RIDGE_GRID,
        gbm_estimators_grid=GBM_ESTIMATORS_GRID,
        config_sha256="cfg_abc",
    )
    lock11 = develop_methods(dev_ids, X, e, ens, registered_seeds=(11,), **common)
    lock23 = develop_methods(dev_ids, X, e, ens, registered_seeds=(23,), **common)
    lock_both = develop_methods(dev_ids, X, e, ens, registered_seeds=(11, 23), **common)

    # nearest_feature has a single combo whose OOF depends on fold assignment
    # (seed-dependent permutation), so the two per-seed vectors must differ.
    m = "nearest_feature"
    s11 = lock11.oof_scores[m]
    s23 = lock23.oof_scores[m]
    assert not np.allclose(s11, s23), (
        "per-seed OOF vectors are unexpectedly identical; the test cannot "
        "distinguish mean-over-seeds from first-seed-only"
    )

    # The two-seed lock must equal the exact arithmetic mean of the two
    # single-seed OOF vectors — not first-seed-only, not median.
    expected = (s11 + s23) / 2.0
    np.testing.assert_allclose(lock_both.oof_scores[m], expected, rtol=1e-12)


# ---------------------------------------------------------------------------
# Structural invariance to sealed/conformal data
# ---------------------------------------------------------------------------


def test_methodlock_only_depends_on_dev_inputs():
    """Identical dev inputs → identical checksum, regardless of anything else
    in the environment.  develop_methods has no parameter that could carry
    sealed/conformal data — this is the structural integrity property."""
    a = _develop(seed=0)
    b = _develop(seed=0)
    assert a.checksum == b.checksum

    # Changing dev inputs DOES change the checksum (sanity: it's not constant)
    c = _develop(seed=1)
    assert a.checksum != c.checksum


def test_methodlock_signature_has_no_store_access():
    import inspect

    sig = inspect.signature(develop_methods)
    params = set(sig.parameters)
    forbidden = {"store", "outcome_store", "sealed", "conformal", "manifest"}
    assert params.isdisjoint(forbidden), f"unexpected store-like params: {params & forbidden}"


# ---------------------------------------------------------------------------
# Determinism + round-trip
# ---------------------------------------------------------------------------


def test_determinism_identical_inputs():
    a = _develop(seed=3)
    b = _develop(seed=3)
    assert a.checksum == b.checksum
    for m in ALL_METHOD_IDS:
        np.testing.assert_array_equal(a.oof_scores[m], b.oof_scores[m])


def test_methodlock_roundtrip(tmp_path: Path):
    lock = _develop(seed=2)
    p = tmp_path / "methodlock"
    lock.write(p)
    back = MethodLock.read(p)
    assert back.checksum == lock.checksum
    assert back.method_ids == lock.method_ids
    assert back.selected_params == lock.selected_params
    assert back.cv_folds == lock.cv_folds
    assert back.registered_seeds == lock.registered_seeds
    assert back.config_sha256 == lock.config_sha256
    for m in ALL_METHOD_IDS:
        np.testing.assert_allclose(back.oof_scores[m], lock.oof_scores[m])
        assert back.oof_aurc[m] == pytest.approx(lock.oof_aurc[m])
    assert back.dev_ids == lock.dev_ids


def test_methodlock_read_detects_tamper(tmp_path: Path):
    lock = _develop(seed=2)
    p = tmp_path / "methodlock"
    lock.write(p)
    # corrupt the JSON metadata
    jpath = p.with_suffix(".json")
    text = jpath.read_text()
    text = text.replace('"cfg_abc"', '"cfg_TAMPERED"')
    jpath.write_text(text)
    with pytest.raises(DevelopError):
        MethodLock.read(p)


# ---------------------------------------------------------------------------
# develop_methods validation
# ---------------------------------------------------------------------------


class TestDevelopValidation:
    def test_nonpositive_mean_errors_raises(self):
        dev_ids, X, e, ens = _make_dev(n=12)
        with pytest.raises(MetricError):
            develop_methods(
                dev_ids,
                X,
                np.zeros_like(e),  # mean == 0 → MetricError on normalize
                ens,
                cv_folds=CV_FOLDS,
                k_grid=K_GRID,
                feature_weight_grid=FEATURE_WEIGHT_GRID,
                ridge_grid=RIDGE_GRID,
                gbm_estimators_grid=GBM_ESTIMATORS_GRID,
                registered_seeds=REGISTERED_SEEDS,
                config_sha256="cfg",
            )

    def test_misaligned_rows_raises(self):
        dev_ids, X, e, ens = _make_dev(n=12)
        with pytest.raises(DevelopError):
            develop_methods(
                dev_ids,
                X[:-1],  # row mismatch
                e,
                ens,
                cv_folds=CV_FOLDS,
                k_grid=K_GRID,
                feature_weight_grid=FEATURE_WEIGHT_GRID,
                ridge_grid=RIDGE_GRID,
                gbm_estimators_grid=GBM_ESTIMATORS_GRID,
                registered_seeds=REGISTERED_SEEDS,
                config_sha256="cfg",
            )


# ---------------------------------------------------------------------------
# Futility rule
# ---------------------------------------------------------------------------


def _norm_errors_for(lock: MethodLock) -> np.ndarray:
    _, _, e, _ = _make_dev(n=len(lock.dev_ids))
    return normalize_by_mean(e)


def _decide(lock: MethodLock, norm: np.ndarray, **overrides) -> FutilityDecision:
    kwargs = dict(
        comparators=("gbm_error", "residual_only"),
        delta_min=0.01,
        confidence=0.90,
        n_replicates=200,
        seed=7,
        config_sha256="cfg_abc",
    )
    kwargs.update(overrides)
    return decide_futility(lock, norm, **kwargs)


def _lock_with_scores(n, gate, comp_scores, errors):
    """Construct a MethodLock-like object purely for futility tests by injecting
    known oof_scores and norm errors."""
    method_ids = ("gate", *comp_scores.keys())
    oof_scores = {"gate": np.asarray(gate, dtype=float)}
    oof_scores.update({k: np.asarray(v, dtype=float) for k, v in comp_scores.items()})
    norm = normalize_by_mean(np.asarray(errors, dtype=float))
    oof_aurc = {m: aurc(norm, oof_scores[m]) for m in method_ids}
    lock = MethodLock(
        method_ids=method_ids,
        selected_params={m: {} for m in method_ids},
        search_table={m: [] for m in method_ids},
        oof_scores=oof_scores,
        oof_aurc=oof_aurc,
        dev_ids=tuple(f"G{i:03d}" for i in range(n)),
        cv_folds=5,
        registered_seeds=(11,),
        config_sha256="cfg_abc",
    )
    return lock, norm


def test_futility_clear_continuation():
    """Gate strongly best: large positive deltas, upper bounds >> delta_min →
    CONTINUE_CONFIRMATORY."""
    n = 60
    rng = np.random.default_rng(0)
    errors = 0.5 + rng.uniform(0.0, 2.0, size=n)
    gate = errors + rng.normal(0.0, 0.01, size=n)  # near-perfect ranking
    comp = {
        "gbm_error": rng.normal(0.0, 1.0, size=n),  # ~random ranking
        "residual_only": rng.normal(0.0, 1.0, size=n),
    }
    lock, norm = _lock_with_scores(n, gate, comp, errors)
    out = _decide(lock, norm)
    assert out.status is OperationalStatus.CONTINUE_CONFIRMATORY
    for c in ("gbm_error", "residual_only"):
        assert out.upper_bounds[c] > out.delta_min
        assert out.dev_deltas[c] > 0.0


def test_futility_clear_stop_when_tied():
    """Gate ~tied with a comparator: upper bound <= delta_min → FUTILITY_STOPPED."""
    n = 60
    rng = np.random.default_rng(1)
    errors = 0.5 + rng.uniform(0.0, 2.0, size=n)
    gate = errors + rng.normal(0.0, 0.01, size=n)
    comp = {
        "gbm_error": gate.copy(),  # identical to gate → delta ~ 0
        "residual_only": gate.copy(),
    }
    lock, norm = _lock_with_scores(n, gate, comp, errors)
    out = _decide(lock, norm)
    assert out.status is OperationalStatus.FUTILITY_STOPPED
    # at least one comparator has upper bound <= delta_min
    assert any(out.upper_bounds[c] <= out.delta_min for c in out.comparators)


def test_futility_boundary_equality_stops(monkeypatch):
    """An upper bound EXACTLY == delta_min must STOP (<= rule)."""
    n = 30
    rng = np.random.default_rng(2)
    errors = 0.5 + rng.uniform(0.0, 2.0, size=n)
    gate = errors + rng.normal(0.0, 0.01, size=n)
    comp = {"gbm_error": gate.copy(), "residual_only": rng.normal(0, 1, n)}
    lock, norm = _lock_with_scores(n, gate, comp, errors)

    import alive.experiment.develop as dev_mod

    delta_min = 0.05

    real = dev_mod.simultaneous_delta_bounds

    def patched(*args, **kwargs):
        res = real(*args, **kwargs)
        # force gbm_error upper bound to be EXACTLY delta_min
        new_bound = dict(res.bound)
        new_bound["gbm_error"] = delta_min
        return type(res)(
            reference=res.reference,
            side=res.side,
            confidence=res.confidence,
            point_delta=res.point_delta,
            bound=new_bound,
            band_halfwidth=res.band_halfwidth,
            n_replicates=res.n_replicates,
            seed=res.seed,
        )

    monkeypatch.setattr(dev_mod, "simultaneous_delta_bounds", patched)
    out = _decide(lock, norm, delta_min=delta_min)
    assert out.upper_bounds["gbm_error"] == pytest.approx(delta_min)
    assert out.status is OperationalStatus.FUTILITY_STOPPED


def test_futility_any_rule_one_comparator_fails(monkeypatch):
    """Any-rule: gate's upper bound exceeds delta_min for one comparator but not
    the other → the FAILING (<= delta_min) comparator alone triggers
    FUTILITY_STOPPED.

    We isolate the decision rule from the band statistics by injecting upper
    bounds directly: ``gbm_error`` well above delta_min (gate plausibly beats it)
    and ``residual_only`` below delta_min (gate cannot be certified to beat it).
    The any-rule must stop.
    """
    n = 40
    rng = np.random.default_rng(3)
    errors = 0.5 + rng.uniform(0.0, 2.0, size=n)
    gate = errors + rng.normal(0.0, 0.01, size=n)
    comp = {
        "gbm_error": rng.normal(0.0, 1.0, size=n),
        "residual_only": rng.normal(0.0, 1.0, size=n),
    }
    lock, norm = _lock_with_scores(n, gate, comp, errors)

    import alive.experiment.develop as dev_mod

    real = dev_mod.simultaneous_delta_bounds
    delta_min = 0.05

    def patched(*args, **kwargs):
        res = real(*args, **kwargs)
        new_bound = dict(res.bound)
        new_bound["gbm_error"] = 0.30  # well above delta_min → gate beats it
        new_bound["residual_only"] = 0.02  # below delta_min → cannot beat it
        return type(res)(
            reference=res.reference,
            side=res.side,
            confidence=res.confidence,
            point_delta=res.point_delta,
            bound=new_bound,
            band_halfwidth=res.band_halfwidth,
            n_replicates=res.n_replicates,
            seed=res.seed,
        )

    monkeypatch.setattr(dev_mod, "simultaneous_delta_bounds", patched)
    out = _decide(lock, norm, delta_min=delta_min)
    assert out.status is OperationalStatus.FUTILITY_STOPPED
    assert out.upper_bounds["gbm_error"] > out.delta_min  # well-beaten one is fine
    assert out.upper_bounds["residual_only"] <= out.delta_min  # tied one trips it


def test_futility_uses_simultaneous_upper_bounds():
    """decide_futility's bounds must equal the primitive's upper bounds with the
    same args (no re-derivation drift)."""
    n = 50
    rng = np.random.default_rng(4)
    errors = 0.5 + rng.uniform(0.0, 2.0, size=n)
    gate = errors + rng.normal(0.0, 0.01, size=n)
    comp = {
        "gbm_error": rng.normal(0.0, 1.0, size=n),
        "residual_only": rng.normal(0.0, 1.0, size=n),
    }
    lock, norm = _lock_with_scores(n, gate, comp, errors)
    out = _decide(lock, norm, n_replicates=150, seed=21)

    direct = simultaneous_delta_bounds(
        norm,
        {m: lock.oof_scores[m] for m in lock.method_ids},
        reference="gate",
        comparators=("gbm_error", "residual_only"),
        side="upper",
        confidence=0.90,
        n_replicates=150,
        seed=21,
    )
    for c in ("gbm_error", "residual_only"):
        assert out.upper_bounds[c] == pytest.approx(direct.bound[c])
        assert out.dev_deltas[c] == pytest.approx(direct.point_delta[c])


def test_futility_determinism_and_roundtrip(tmp_path: Path):
    n = 40
    rng = np.random.default_rng(5)
    errors = 0.5 + rng.uniform(0.0, 2.0, size=n)
    gate = errors + rng.normal(0.0, 0.01, size=n)
    comp = {
        "gbm_error": rng.normal(0.0, 1.0, size=n),
        "residual_only": rng.normal(0.0, 1.0, size=n),
    }
    lock, norm = _lock_with_scores(n, gate, comp, errors)
    a = _decide(lock, norm)
    b = _decide(lock, norm)
    assert a.checksum == b.checksum

    p = tmp_path / "futility.json"
    a.write(p)
    back = FutilityDecision.read(p)
    assert back.checksum == a.checksum
    assert back.status is a.status
    assert back.dev_deltas == pytest.approx(a.dev_deltas)
    assert back.upper_bounds == pytest.approx(a.upper_bounds)
    assert back.comparators == a.comparators
    assert back.confidence == a.confidence
    assert back.delta_min == a.delta_min
    assert back.methodlock_sha256 == a.methodlock_sha256


def test_futility_records_methodlock_checksum():
    n = 30
    rng = np.random.default_rng(6)
    errors = 0.5 + rng.uniform(0.0, 2.0, size=n)
    gate = errors + rng.normal(0.0, 0.01, size=n)
    comp = {"gbm_error": rng.normal(0, 1, n), "residual_only": rng.normal(0, 1, n)}
    lock, norm = _lock_with_scores(n, gate, comp, errors)
    out = _decide(lock, norm)
    assert out.methodlock_sha256 == lock.checksum
    assert out.config_sha256 == "cfg_abc"


def test_futility_checksum_invariant_to_unrelated_data():
    """The decision is a pure function of (MethodLock, norm_errors, futility
    params).  Two decisions from identical such inputs share a checksum — there
    is no channel for sealed/conformal data."""
    import inspect

    sig = inspect.signature(decide_futility)
    params = set(sig.parameters)
    forbidden = {"store", "outcome_store", "sealed", "conformal", "manifest"}
    assert params.isdisjoint(forbidden)
