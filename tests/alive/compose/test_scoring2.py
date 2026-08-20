"""Tests for COMPOSE-K562-v1 Phase-2b regime-specific scoring (Task 2b-4).

SYNTHETIC-ONLY: pure-``numpy`` / synthetic fixtures only — NO real Norman,
NO seal access, NO real outcomes. ``score_regime`` receives ALREADY-OBSERVED
populations (whatever the single sealed access yielded) plus already-computed
per-method predictions and scores exactly ONE regime: it transforms observed
populations through the frozen response space, aligns predictions by canonical
pair ID, computes per-pair MSE, runs the registered simultaneous inference for
THAT regime, and assembles a STRUCTURALLY-SEPARATE secondary block that NEVER
enters the primary simultaneous bounds (the verdict input).

The two regimes (double-unseen, single-unseen) are scored INDEPENDENTLY — the
orchestrator (Task 8) calls ``score_regime`` twice. Pooling is impossible here:
``score_regime`` only ever sees one regime's pairs.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from alive.compose.config2 import (
    _EXPECTED_METHOD_ROSTER,
    SecondaryMetricSpec,
    load_compose_phase2_config,
)
from alive.compose.inference2 import ComposeSimultaneousBounds
from alive.compose.metric2 import NOT_EVALUABLE, per_pair_mse
from alive.compose.response import fit_response_space
from alive.compose.scoring2 import (
    ComposeScoringError,
    RegimeScore,
    SecondaryBlock,
    score_regime,
)

_CONFIG_PATH = "configs/compose_k562_v1_phase2.yaml"

HEADLINE = "l1_bilinear_identifiable"
FAMILY = ("additive", "gears", "cpa", "id_only", "l3_symmetric_mlp")
# Numeric-test bootstrap value; the 10000 floor is enforced by the config loader.
REPS = 200
SEED = 4321
CONF = 0.95


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _config():
    """Load the real (preregistered, blocked) Phase-2 config.

    Loading is allowed under activation-blocked: it is the same config object
    the orchestrator passes, and it carries the registered secondary specs and
    ``secondary_are_verdict_gates=False`` governance flag.
    """
    return load_compose_phase2_config(_CONFIG_PATH)


def _counts(seed: int, n_cells: int, n_genes: int) -> np.ndarray:
    """Deterministic positive-library raw-count matrix (dense ndarray)."""
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 8, size=(n_cells, n_genes)).astype(np.float64)
    base[:, 0] += 1.0  # guarantee every cell a positive library size
    return base


def _fixture_space(seed: int = 0):
    """A small fitted ResponseSpace plus a control mean vector in PCA space.

    Returns
    -------
    (space, control_mean, control_cells)
        ``control_mean`` is the EXPLICIT ``(pca_dim,)`` control mean ``score_regime``
        consumes (the artifact's ``_control_mean`` cache does not survive reload).
    """
    X = _counts(seed, 16, 6)
    control_idx = np.arange(0, 6)
    single_idx = np.arange(6, 12)
    space = fit_response_space(
        X, control_idx=control_idx, eligible_single_idx=single_idx, n_hvg=4, pca_dim=2, seed=7
    )
    control_cells = X[control_idx]
    control_mean = space.project(control_cells, np.arange(control_cells.shape[0])).mean(axis=0)
    return space, control_mean, control_cells


def _observed_population(space, control_mean, target_delta, seed, n_cells=20, n_genes=6):
    """Build a raw-count population whose observed PCA mean-shift ≈ target_delta.

    We do NOT need an exact delta for most tests; the tests recompute the true
    observed δ_gh via the response space, so any well-defined population works.
    """
    return _counts(seed, n_cells, n_genes)


def _observed_delta(space, control_mean, cells) -> np.ndarray:
    """Recompute the true observed δ_gh exactly as ``score_regime`` must."""
    proj = space.project(cells, np.arange(cells.shape[0]))
    return proj.mean(axis=0) - control_mean


def _build_regime(seed_base: int = 100, pair_ids=None):
    """Assemble a complete, well-formed single-regime scoring input bundle.

    Returns a dict of kwargs ready to splat into ``score_regime`` plus the
    ground-truth observed deltas (for hand cross-checks).
    """
    space, control_mean, _ = _fixture_space(seed=0)
    if pair_ids is None:
        pair_ids = (("A", "B"), ("C", "D"), ("E", "F"))
    observed = {}
    observed_delta = {}
    for k, pid in enumerate(pair_ids):
        cells = _counts(seed_base + k, 20, 6)
        observed[pid] = cells
        observed_delta[pid] = _observed_delta(space, control_mean, cells)

    # additive baseline prediction per pair (the GI identity uses this directly).
    rng = np.random.default_rng(seed_base)
    additive_pred = {pid: rng.normal(size=2) for pid in pair_ids}

    # headline = additive + a small true-ish GI component close to observed eps.
    # The bundle carries the FULL 9-method roster (freeze validates all nine per
    # regime). The verdict consumes only headline + FAMILY (6); the remaining three
    # (l2_saturation, no_change, perturbation_mean) are DESCRIPTIVE-only. Their draws
    # are appended AFTER the six verdict methods so the verdict methods' predictions
    # (and thus pair_errors) stay byte-identical.
    predictions = {
        HEADLINE: {},
        "additive": {},
        "gears": {},
        "cpa": {},
        "id_only": {},
        "l3_symmetric_mlp": {},
        "l2_saturation": {},
        "no_change": {},
        "perturbation_mean": {},
    }
    for pid in pair_ids:
        eps_truth = observed_delta[pid] - additive_pred[pid]
        predictions["additive"][pid] = additive_pred[pid]
        # headline predicts most of eps → low error, high gi-explained
        predictions[HEADLINE][pid] = additive_pred[pid] + 0.9 * eps_truth
        # other comparators are deliberately worse
        predictions["gears"][pid] = additive_pred[pid] + 5.0 * rng.normal(size=2)
        predictions["cpa"][pid] = additive_pred[pid] + 5.0 * rng.normal(size=2)
        predictions["id_only"][pid] = additive_pred[pid] + 5.0 * rng.normal(size=2)
        predictions["l3_symmetric_mlp"][pid] = additive_pred[pid] + 5.0 * rng.normal(size=2)
        # descriptive-only roster methods (never enter the verdict pair_errors).
        predictions["l2_saturation"][pid] = additive_pred[pid] + 3.0 * rng.normal(size=2)
        predictions["no_change"][pid] = np.zeros(2)
        predictions["perturbation_mean"][pid] = additive_pred[pid].copy()

    kwargs = dict(
        regime="sealed_double_unseen",
        pair_ids=tuple(pair_ids),
        observed=observed,
        response_space=space,
        control_mean=control_mean,
        predictions=predictions,
        headline=HEADLINE,
        comparators=FAMILY,
        confidence=CONF,
        n_replicates=REPS,
        seed=SEED,
        config=_config(),
    )
    return kwargs, observed_delta, additive_pred


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_full_score():
    kwargs, observed_delta, additive_pred = _build_regime()
    score = score_regime(**kwargs)

    assert isinstance(score, RegimeScore)
    assert score.regime == "sealed_double_unseen"
    assert score.pair_ids == kwargs["pair_ids"]
    assert score.sample_count == 3
    assert score.missing_pairs == ()

    # primary bounds present, over the EXACT family, headline excluded.
    assert isinstance(score.bounds, ComposeSimultaneousBounds)
    assert score.bounds.comparators == FAMILY
    assert HEADLINE not in score.bounds.comparators

    # per-method pair-error arrays for headline + every comparator.
    assert set(score.pair_errors) == {HEADLINE, *FAMILY}
    for name, arr in score.pair_errors.items():
        assert arr.shape == (3,)
        assert np.all(arr >= 0.0)

    # secondary block present and structurally separate.
    assert isinstance(score.secondary, SecondaryBlock)
    assert isinstance(score.secondary.gi_explained_point, float)
    assert len(score.secondary.gi_explained_interval) == 2
    lo, hi = score.secondary.gi_explained_interval
    assert lo <= hi
    assert score.secondary.gi_structure is NOT_EVALUABLE


def test_score_regime_descriptive_covers_full_roster():
    """DESCRIPTIVE per-pair MSE spans the FULL 9-method roster; the VERDICT set stays 6.

    ``descriptive_pair_errors`` is a non-verdict surface reported for EVERY roster
    method present in ``predictions`` (all nine). The verdict ``pair_errors`` remain
    exactly headline + the five registered comparators, and the shared-method
    descriptive values are byte-identical to their verdict values.
    """
    kwargs, _, _ = _build_regime()
    rs = score_regime(**kwargs)

    # descriptive covers every roster method present in predictions (all 9).
    assert set(rs.descriptive_pair_errors) == set(_EXPECTED_METHOD_ROSTER)
    # verdict set is UNCHANGED: headline + the five registered comparators only (6).
    assert set(rs.pair_errors) == {HEADLINE, *FAMILY}
    # the six shared methods' descriptive arrays are byte-identical to the verdict arrays.
    for name in rs.pair_errors:
        np.testing.assert_array_equal(rs.descriptive_pair_errors[name], rs.pair_errors[name])
    # each descriptive array is per-pair (one entry per scored pair) and non-negative.
    for arr in rs.descriptive_pair_errors.values():
        assert arr.shape == (rs.sample_count,)
        assert np.all(arr >= 0.0)


def test_per_pair_mse_matches_hand_computation():
    """Cross-check ONE method's per-pair MSE against the metric primitive directly."""
    kwargs, observed_delta, _ = _build_regime()
    score = score_regime(**kwargs)

    pair_ids = kwargs["pair_ids"]
    # Build the prediction & truth matrices in manifest order for the headline.
    pred = np.vstack([kwargs["predictions"][HEADLINE][pid] for pid in pair_ids])
    truth = np.vstack([observed_delta[pid] for pid in pair_ids])
    str_ids = [str(p) for p in pair_ids]
    expected = per_pair_mse(pred, truth, pair_ids=str_ids, truth_ids=str_ids)

    np.testing.assert_allclose(score.pair_errors[HEADLINE], expected, rtol=0, atol=1e-12)
    # and the bounds' headline_errors are exactly these.
    np.testing.assert_allclose(score.headline_errors_view(), expected, rtol=0, atol=1e-12)


def test_gi_explained_uses_eps_identity():
    """GI-explained point uses eps_pred = headline - additive, eps_truth = obs - additive."""
    from alive.compose.metric2 import gi_explained_fraction

    kwargs, observed_delta, additive_pred = _build_regime()
    score = score_regime(**kwargs)

    pair_ids = kwargs["pair_ids"]
    eps_pred = np.vstack(
        [kwargs["predictions"][HEADLINE][pid] - additive_pred[pid] for pid in pair_ids]
    )
    eps_truth = np.vstack([observed_delta[pid] - additive_pred[pid] for pid in pair_ids])
    str_ids = [str(p) for p in pair_ids]
    expected = gi_explained_fraction(eps_pred, eps_truth, pair_ids=str_ids, truth_ids=str_ids)

    assert score.secondary.gi_explained_point == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Order / role preservation
# ---------------------------------------------------------------------------


def test_manifest_order_preserved():
    order = (("Z", "Y"), ("M", "N"), ("A", "B"), ("C", "D"))
    kwargs, _, _ = _build_regime(pair_ids=order)
    score = score_regime(**kwargs)
    assert score.pair_ids == tuple(order)
    # error arrays are indexed in the same manifest order: shuffling the input
    # mapping order must not change the output ordering.


def test_role_label_preserved():
    kwargs, _, _ = _build_regime()
    kwargs["regime"] = "sealed_single_unseen"
    score = score_regime(**kwargs)
    assert score.regime == "sealed_single_unseen"


def test_alignment_is_by_canonical_pair_id_not_insertion_order():
    """Shuffling a method's prediction-dict insertion order leaves pair_errors unchanged.

    Alignment is by canonical pair ID, never positional: reordering the entries
    of one method's prediction mapping (same pairs, different insertion order)
    must produce byte-identical per-method MSE arrays. We also present the SAME
    pairs in a reversed insertion order to be doubly sure no positional indexing
    leaks in.
    """
    kwargs, _, _ = _build_regime()
    base = score_regime(**kwargs)

    # Reorder the headline method's prediction dict: same pairs, shuffled
    # insertion order (and reversed for the comparator to vary the pattern).
    shuffled_predictions = {}
    for method, block in kwargs["predictions"].items():
        items = list(block.items())
        if method == HEADLINE:
            # rotate the insertion order
            items = items[1:] + items[:1]
        elif method == "gears":
            items = list(reversed(items))
        shuffled_predictions[method] = {pid: vec for pid, vec in items}

    perturbed_kwargs = dict(kwargs)
    perturbed_kwargs["predictions"] = shuffled_predictions
    perturbed = score_regime(**perturbed_kwargs)

    # Every per-method MSE array is UNCHANGED — alignment is by pair ID.
    assert set(perturbed.pair_errors) == set(base.pair_errors)
    for name in base.pair_errors:
        np.testing.assert_array_equal(perturbed.pair_errors[name], base.pair_errors[name])
    # and the whole regime checksum is identical (order had no effect anywhere).
    assert perturbed.checksum == base.checksum


# ---------------------------------------------------------------------------
# Missing / failed pairs — fail-closed-but-reported policy
# ---------------------------------------------------------------------------


def test_missing_observed_population_raises_fail_closed():
    """A manifest pair with NO observed population is a fail-closed error, reported."""
    kwargs, _, _ = _build_regime()
    del kwargs["observed"][("C", "D")]
    with pytest.raises(ComposeScoringError) as exc:
        score_regime(**kwargs)
    assert "('C', 'D')" in str(exc.value)
    assert "observed" in str(exc.value).lower()


def test_missing_prediction_raises_fail_closed():
    """A manifest pair missing a method prediction is a fail-closed error, reported."""
    kwargs, _, _ = _build_regime()
    del kwargs["predictions"]["gears"][("E", "F")]
    with pytest.raises(ComposeScoringError) as exc:
        score_regime(**kwargs)
    msg = str(exc.value)
    assert "('E', 'F')" in msg
    assert "gears" in msg


def test_missing_pairs_reported_on_dataclass_when_allowed():
    """When ``require_complete=False`` a missing pair is EXCLUDED-AND-REPORTED, never dropped."""
    kwargs, _, _ = _build_regime()
    del kwargs["observed"][("C", "D")]
    score = score_regime(**kwargs, require_complete=False)
    # ('C','D') is reported missing; the scored pairs preserve manifest order minus it.
    assert ("C", "D") in score.missing_pairs
    assert ("C", "D") not in score.pair_ids
    assert score.pair_ids == (("A", "B"), ("E", "F"))
    assert score.sample_count == 2


# ---------------------------------------------------------------------------
# Regime independence / no pooling
# ---------------------------------------------------------------------------


def test_regime_independence_no_cross_contamination():
    """Scoring two DISTINCT regimes shares/merges nothing — distinct pairs stay distinct."""
    double = _build_regime(seed_base=100, pair_ids=(("A", "B"), ("C", "D")))[0]
    double["regime"] = "sealed_double_unseen"
    single = _build_regime(seed_base=500, pair_ids=(("G", "H"), ("I", "J")))[0]
    single["regime"] = "sealed_single_unseen"

    s_double = score_regime(**double)
    s_single = score_regime(**single)

    assert set(s_double.pair_ids).isdisjoint(set(s_single.pair_ids))
    assert s_double.regime != s_single.regime
    # arrays are independent objects, not shared references.
    assert s_double.pair_errors[HEADLINE] is not s_single.pair_errors[HEADLINE]
    assert s_double.checksum != s_single.checksum


def test_score_regime_sees_only_one_regime():
    """The function signature forbids pooling: it takes ONE regime's pairs only."""
    kwargs, _, _ = _build_regime(pair_ids=(("A", "B"), ("C", "D")))
    score = score_regime(**kwargs)
    # exactly the two pairs handed in — nothing from any other regime.
    assert score.sample_count == 2
    assert len(score.pair_errors[HEADLINE]) == 2


# ---------------------------------------------------------------------------
# Secondary is structurally separate from the bounds
# ---------------------------------------------------------------------------


def test_secondary_does_not_touch_bounds():
    """Perturbing only the GI/secondary class-manifest path leaves the bounds identical."""
    kwargs, _, _ = _build_regime()
    base = score_regime(**kwargs)
    # Pass a genuinely DIFFERENT secondary input (a non-None class manifest +
    # rule). The deferred structure metric still returns NOT_EVALUABLE, and —
    # crucially — the primary bounds are byte-identical: the secondary path is
    # structurally separate from the verdict input.
    perturbed = score_regime(
        **kwargs,
        class_manifest={"version": "x", "labels": {"AB": 1}},
        prediction_to_class_rule=lambda v: int(v[0] > 0),
    )
    assert perturbed.bounds.checksum == base.bounds.checksum
    np.testing.assert_array_equal(perturbed.pair_errors[HEADLINE], base.pair_errors[HEADLINE])
    # gi_structure stays NOT_EVALUABLE in both (Phase-2 deferral).
    assert base.secondary.gi_structure is NOT_EVALUABLE
    assert perturbed.secondary.gi_structure is NOT_EVALUABLE


def test_secondary_isolation_no_public_input_can_move_gi_without_moving_primary():
    """Structural fact: the secondary GI anchor double-duties as a primary input.

    The brief asked, ideally, for a perturbation that MOVES ``gi_explained``
    while leaving every primary error array byte-identical. That is provably
    impossible through the public ``score_regime`` inputs, and this test
    DOCUMENTS WHY rather than faking it:

    * ``gi_explained`` is computed from
      ``eps_pred = headline_pred - additive_pred`` and
      ``eps_truth = observed_δ_gh - additive_pred``.
    * The ONLY public inputs to those terms are the ``headline`` prediction, the
      ``additive`` prediction and the ``observed`` populations.
    * ``headline_pred`` feeds the PRIMARY ``pair_errors[headline]`` (the bounds'
      headline input); ``additive_pred`` feeds the PRIMARY ``pair_errors`` of
      the ``additive`` COMPARATOR; ``observed`` feeds EVERY primary error.

    So every public input that moves the secondary also moves a primary error
    array — secondary isolation is enforced by the call ordering (bounds built
    first), not by an input that the verdict ignores. We demonstrate the
    coupling concretely: translating only the ``additive`` prediction moves
    ``gi_explained`` AND moves the ``additive`` comparator's primary error.
    """
    kwargs, _, _ = _build_regime()
    base = score_regime(**kwargs)
    pair_ids = kwargs["pair_ids"]

    # Move ONLY the additive anchor (the smallest input that touches the GI eps
    # identity). This shifts the secondary GI-explained point...
    shift = np.array([0.6, -0.3])
    moved_predictions = {m: dict(block) for m, block in kwargs["predictions"].items()}
    for pid in pair_ids:
        moved_predictions["additive"][pid] = kwargs["predictions"]["additive"][pid] + shift

    moved_kwargs = dict(kwargs)
    moved_kwargs["predictions"] = moved_predictions
    moved = score_regime(**moved_kwargs)

    # ...the secondary genuinely moved...
    assert moved.secondary.gi_explained_point != base.secondary.gi_explained_point
    # ...AND, inseparably, so did the PRIMARY additive-comparator error and the
    # bounds: there is no public input that isolates the two. The verdict input
    # is protected by construction order, not by an inert input.
    assert not np.array_equal(moved.pair_errors["additive"], base.pair_errors["additive"])
    assert moved.bounds.checksum != base.bounds.checksum
    # The headline primary error is unchanged (we only touched the additive
    # anchor), confirming the move was localized to the additive coupling.
    np.testing.assert_array_equal(moved.pair_errors[HEADLINE], base.pair_errors[HEADLINE])


def test_bounds_constructed_before_any_secondary_computation():
    """Structural guarantee: the bounds are built strictly before the secondary block.

    Documents (and locks in) WHY no secondary value can feed back into the
    verdict input: ``score_regime`` constructs the
    :class:`ComposeSimultaneousBounds` from the primary per-pair MSE arrays
    BEFORE the secondary GI-explained / eps computation runs. A read of the
    module source confirms the ordering: ``simultaneous_theta_bounds(`` precedes
    the ``# --- 6. Secondary block`` section and every eps / gi_* computation.
    """
    import inspect

    from alive.compose import scoring2

    body = inspect.getsource(scoring2.score_regime)
    # Anchor on unique CODE substrings (the docstring uses different wording, so
    # these match the executable statements, not prose references).
    idx_bounds = body.index("bounds = simultaneous_theta_bounds(")
    idx_secondary = body.index("# --- 6. Secondary block")
    idx_eps = body.index("eps_pred = pred_matrices[headline]")
    idx_gi_point = body.index("gi_point = gi_explained_fraction(")
    # bounds are constructed strictly before the secondary block and any eps / GI math.
    assert idx_bounds < idx_secondary < idx_eps < idx_gi_point


def test_bounds_only_consume_primary_errors():
    """The bounds' headline_errors equal the headline per-pair MSE (no secondary leakage)."""
    kwargs, observed_delta, _ = _build_regime()
    score = score_regime(**kwargs)
    pair_ids = kwargs["pair_ids"]
    pred = np.vstack([kwargs["predictions"][HEADLINE][pid] for pid in pair_ids])
    truth = np.vstack([observed_delta[pid] for pid in pair_ids])
    str_ids = [str(p) for p in pair_ids]
    expected = per_pair_mse(pred, truth, pair_ids=str_ids, truth_ids=str_ids)
    np.testing.assert_allclose(score.headline_errors_view(), expected, atol=1e-12)


# ---------------------------------------------------------------------------
# NOT_EVALUABLE cannot be laundered
# ---------------------------------------------------------------------------


def test_gi_structure_not_evaluable_cannot_be_floated():
    kwargs, _, _ = _build_regime()
    score = score_regime(**kwargs)
    with pytest.raises(TypeError):
        float(score.secondary.gi_structure)
    assert str(score.secondary.gi_structure) == "NOT_EVALUABLE"


# ---------------------------------------------------------------------------
# Governance failures
# ---------------------------------------------------------------------------


def test_secondary_as_verdict_gate_raises():
    """A config flagged ``secondary_are_verdict_gates=True`` is an activation failure."""
    kwargs, _, _ = _build_regime()
    bad = dataclasses.replace(kwargs["config"], secondary_are_verdict_gates=True)
    kwargs["config"] = bad
    with pytest.raises(ComposeScoringError) as exc:
        score_regime(**kwargs)
    assert "verdict gate" in str(exc.value).lower() or "secondary" in str(exc.value).lower()


def test_missing_secondary_spec_raises():
    """A config without the GI-explained secondary spec cannot silently default."""
    kwargs, _, _ = _build_regime()
    # drop gi_explained_fraction from the registered secondary specs.
    kept = tuple(s for s in kwargs["config"].secondary_metrics if s.name != "gi_explained_fraction")
    bad = dataclasses.replace(kwargs["config"], secondary_metrics=kept)
    kwargs["config"] = bad
    with pytest.raises(ComposeScoringError) as exc:
        score_regime(**kwargs)
    assert "gi_explained_fraction" in str(exc.value)


def test_primary_confidence_must_match_family_confidence():
    """A primary ``confidence`` != ``config.family_confidence`` is a fail-closed seam error.

    The primary simultaneous band uses the passed ``confidence`` while the
    secondary GI interval uses ``config.family_confidence`` directly. If the
    orchestrator ever passes a divergent value the two would silently disagree,
    so ``score_regime`` must refuse to score.
    """
    kwargs, _, _ = _build_regime()
    assert kwargs["confidence"] == kwargs["config"].family_confidence  # baseline is consistent
    kwargs["confidence"] = kwargs["config"].family_confidence - 0.05
    with pytest.raises(ComposeScoringError) as exc:
        score_regime(**kwargs)
    msg = str(exc.value).lower()
    assert "family_confidence" in msg
    assert "confidence" in msg


def test_secondary_interval_method_and_margin_come_from_config():
    """The reported interval method + material margin are copied from the config spec."""
    kwargs, _, _ = _build_regime()
    score = score_regime(**kwargs)
    spec = next(s for s in kwargs["config"].secondary_metrics if s.name == "gi_explained_fraction")
    assert isinstance(spec, SecondaryMetricSpec)
    assert score.secondary.interval_method == spec.interval_method
    assert score.secondary.material_regression_margin == spec.material_regression_margin
    assert score.secondary.governance_note == spec.governance_note


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism_identical_checksum():
    kwargs_a, _, _ = _build_regime()
    kwargs_b, _, _ = _build_regime()
    a = score_regime(**kwargs_a)
    b = score_regime(**kwargs_b)
    assert a.checksum == b.checksum
    assert a.bounds.checksum == b.bounds.checksum


def test_different_seed_changes_bounds_checksum():
    kwargs, _, _ = _build_regime()
    a = score_regime(**kwargs)
    kwargs2 = dict(kwargs)
    kwargs2["seed"] = SEED + 1
    b = score_regime(**kwargs2)
    assert a.bounds.checksum != b.bounds.checksum


# ---------------------------------------------------------------------------
# Effect-size summaries
# ---------------------------------------------------------------------------


def test_effect_size_summaries_present():
    kwargs, _, _ = _build_regime()
    score = score_regime(**kwargs)
    sec = score.secondary
    # per-pair GI error array + mean/median theta summaries are reported.
    assert sec.gi_per_pair_error.shape == (3,)
    assert np.all(sec.gi_per_pair_error >= 0.0)
    assert isinstance(sec.theta_mean, float)
    assert isinstance(sec.theta_median, float)


def test_empty_pair_ids_raises():
    kwargs, _, _ = _build_regime()
    kwargs["pair_ids"] = ()
    kwargs["observed"] = {}
    kwargs["predictions"] = {m: {} for m in kwargs["predictions"]}
    with pytest.raises(ComposeScoringError):
        score_regime(**kwargs)
