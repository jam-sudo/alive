"""Band-inflation sensitivity: descriptive-only, and it must agree with the verdict.

Decision `docs/superpowers/2026-08-29-compose-pair-dependence-decision.md`. The
headline pair set violates the registered pair-i.i.d. resampling assumption by
construction (22 pairs over 21 genes, no gene-disjoint row, two connected
components), and no cluster resample is available. The decision keeps the
estimator and every threshold unchanged and re-reports the bounds at a frozen
ladder of band inflations, so the report states WHERE the verdict flips instead
of asserting that it does not.

The load-bearing tests are the ones that check the report against the REAL
`sealed_verdict`, not against a reimplementation of its clauses. A report that
quietly disagreed with the function that decides the run would be worse than no
report.
"""

from __future__ import annotations

import math

import pytest

from alive.compose.inference2 import (
    ComposeInferenceError,
    ComposeSimultaneousBounds,
    band_sensitivity,
    inflate_bounds,
)
from alive.compose.verdict2 import (
    ComposeIntegrityReport,
    MethodAxis,
    SealedAxis,
    sealed_verdict,
)

FAMILY = ("additive", "gears", "cpa", "id_only", "l3_symmetric_mlp")
DOUBLE_UNSEEN = "sealed_double_unseen"
ADDITIVE_MARGIN = 0.05
LEARNED_MARGIN = 0.0
LADDER = (1.0, 1.1, 1.15, 1.25)


def _bounds(theta: dict[str, float], q: float) -> ComposeSimultaneousBounds:
    return ComposeSimultaneousBounds(
        comparators=FAMILY,
        theta=dict(theta),
        lower={c: theta[c] - q for c in FAMILY},
        band_halfwidth=q,
        confidence=0.95,
        n_replicates=10000,
        seed=1234,
    )


def _winning_bounds() -> ComposeSimultaneousBounds:
    """Comfortably a GI_LEARNABLE_WIN at lambda = 1.0, so a flip is meaningful."""
    return _bounds(
        {"additive": 0.30, "gears": 0.24, "cpa": 0.26, "id_only": 0.34, "l3_symmetric_mlp": 0.22},
        q=0.10,
    )


def _integrity() -> ComposeIntegrityReport:
    return ComposeIntegrityReport(
        provenance_ok=True,
        leakage_ok=True,
        all_metrics_finite=True,
        sealed_access_consistent=True,
        sealed_n=64,
        minimum_sealed=10,
        disclaimer="structural run-internal self-check, NOT an independent audit",
    )


def _verdict(bounds) -> SealedAxis:
    return sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=bounds,
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_integrity(),
        method_axis=MethodAxis.METHOD_VALIDATED,
    ).sealed_axis


def test_lambda_one_reproduces_the_registered_bounds_exactly():
    """The report must not perturb the value the verdict is decided on."""
    b = _winning_bounds()
    s = band_sensitivity(
        bounds=b,
        band_inflation=LADDER,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
    )
    assert s.lower_by_lambda[1.0] == b.lower


def test_inflation_only_widens_and_never_moves_the_point_estimate():
    b = _winning_bounds()
    for lam in (1.1, 1.15, 1.25):
        inflated = inflate_bounds(b, lam)
        assert inflated.theta == b.theta
        assert inflated.band_halfwidth == pytest.approx(b.band_halfwidth * lam)
        for c in FAMILY:
            assert inflated.lower[c] < b.lower[c]


def test_a_factor_below_one_is_refused():
    """Narrowing the registered band is the one thing this must never do."""
    with pytest.raises(ComposeInferenceError, match="narrow the registered band"):
        inflate_bounds(_winning_bounds(), 0.99)


def test_the_flip_point_is_exact_for_every_comparator():
    """At lambda = flip, the bound sits exactly on its threshold (closed form)."""
    b = _winning_bounds()
    s = band_sensitivity(
        bounds=b,
        band_inflation=LADDER,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
    )
    for c in FAMILY:
        threshold = ADDITIVE_MARGIN if c == "additive" else LEARNED_MARGIN
        at_flip = b.theta[c] - s.flip_lambda[c] * b.band_halfwidth
        assert at_flip == pytest.approx(threshold, abs=1e-12)


def _zero_width_bounds(**theta_overrides: float) -> ComposeSimultaneousBounds:
    """q = 0 bounds; every comparator wins comfortably unless overridden."""
    theta = {
        "additive": 0.30,
        "gears": 0.24,
        "cpa": 0.26,
        "id_only": 0.34,
        "l3_symmetric_mlp": 0.22,
    }
    theta.update(theta_overrides)
    return _bounds(theta, q=0.0)


def test_a_zero_width_winner_never_flips():
    """Every theta strictly above its threshold: the clause holds at every lambda.

    ``+inf`` exactly, not merely "infinite" -- the sign is the encoding.
    """
    b = _zero_width_bounds()
    s = band_sensitivity(
        bounds=b,
        band_inflation=LADDER,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
    )
    assert all(v == math.inf for v in s.flip_lambda.values())
    assert s.verdict_holds_below_lambda == math.inf
    assert _verdict(b) is SealedAxis.GI_LEARNABLE_WIN
    assert _verdict(inflate_bounds(b, LADDER[-1])) is SealedAxis.GI_LEARNABLE_WIN


def test_a_zero_width_loser_fails_at_the_registered_band_not_at_inf():
    """theta below its threshold with q = 0: the clause never held at any lambda.

    The docstring encoding is explicit: a value at or below 1.0 means the clause
    does not hold at the registered band either. Reporting inf here would claim
    an already-lost conjunction holds at every finite inflation.
    """
    b = _zero_width_bounds(additive=0.03)
    assert _verdict(b) is SealedAxis.NO_DISTINCT_WIN

    s = band_sensitivity(
        bounds=b,
        band_inflation=LADDER,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
    )
    assert s.flip_lambda["additive"] == -math.inf
    assert all(s.flip_lambda[c] == math.inf for c in FAMILY if c != "additive")
    assert s.verdict_holds_below_lambda <= 1.0


@pytest.mark.parametrize(
    ("comparator", "threshold", "expected_axis"),
    [
        ("additive", ADDITIVE_MARGIN, SealedAxis.NO_DISTINCT_WIN),
        ("gears", LEARNED_MARGIN, SealedAxis.PARTIAL),
    ],
)
def test_a_zero_width_equality_fails_under_the_strict_clause(comparator, threshold, expected_axis):
    """theta exactly at the threshold with q = 0: the strict ``>`` clause fails.

    This is the audited misreport: `sealed_verdict` already decides against the
    conjunction at lambda = 1, so the report must not answer ``inf``.
    """
    b = _zero_width_bounds(**{comparator: threshold})
    assert _verdict(b) is expected_axis

    s = band_sensitivity(
        bounds=b,
        band_inflation=LADDER,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
    )
    assert s.flip_lambda[comparator] == -math.inf
    assert s.verdict_holds_below_lambda <= 1.0


def test_the_reported_flip_is_the_earliest_clause_to_fail():
    b = _winning_bounds()
    s = band_sensitivity(
        bounds=b,
        band_inflation=LADDER,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
    )
    assert s.verdict_holds_below_lambda == min(s.flip_lambda.values())


@pytest.mark.parametrize(
    ("ladder", "match"),
    [
        ((), "non-empty"),
        ((1.1, 1.25), "must start at the registered band"),
        ((1.0, 1.0, 1.25), "strictly increasing"),
        ((1.0, 1.25, 1.1), "strictly increasing"),
        ((1.0, 0.9), "finite and >= 1.0"),
        ((1.0, float("inf")), "finite and >= 1.0"),
    ],
)
def test_a_malformed_ladder_is_refused(ladder, match):
    with pytest.raises(ComposeInferenceError, match=match):
        band_sensitivity(
            bounds=_winning_bounds(),
            band_inflation=ladder,
            additive_margin=ADDITIVE_MARGIN,
            learned_margin=LEARNED_MARGIN,
        )


def test_the_report_agrees_with_the_real_sealed_verdict_at_the_flip():
    """The report is checked against the function that decides the run.

    Just inside the reported flip the verdict still stands; just outside it does
    not. If `band_sensitivity` ever reimplemented the clause logic and drifted
    from `sealed_verdict`, this is what would notice.
    """
    b = _winning_bounds()
    s = band_sensitivity(
        bounds=b,
        band_inflation=LADDER,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
    )
    flip = s.verdict_holds_below_lambda
    assert 1.0 < flip < 10.0, "fixture must flip somewhere above the registered band"

    assert _verdict(inflate_bounds(b, flip * 0.999)) is SealedAxis.GI_LEARNABLE_WIN
    assert _verdict(inflate_bounds(b, flip * 1.001)) is not SealedAxis.GI_LEARNABLE_WIN


def test_the_registered_ladder_from_the_committed_config_is_accepted():
    """A report the committed config cannot drive is not a report."""
    from alive.compose.config2 import load_compose_phase2_config

    cfg = load_compose_phase2_config("configs/compose_k562_v1_phase2.yaml")
    s = band_sensitivity(
        bounds=_winning_bounds(),
        band_inflation=cfg.sensitivity_band_inflation,
        additive_margin=cfg.material_margin_vs_additive,
        learned_margin=cfg.learned_comparator_margin,
    )
    assert s.band_inflation == cfg.sensitivity_band_inflation
    assert set(s.lower_by_lambda) == set(cfg.sensitivity_band_inflation)


# ---------------------------------------------------------------------------
# The pre-registered headline branch (D4 §8), PR #15 finding I3
#
# §8's first three sentences were written against the two NON-FINITE flip labels,
# which only a zero-width band produces. A normal `q > 0` run produces a FINITE
# flip, and Codex measured two such results that no sentence claimed. The branch
# now lives in `phase2b.preregistered_headline_branch`; these tests drive it from
# the REAL `band_sensitivity` -> `_band_sensitivity_block` -> `sealed_verdict`
# chain rather than from a reimplementation of any of them.
# ---------------------------------------------------------------------------
LADDER_MAX = max(LADDER)


def _measured_branch(theta: dict[str, float], q: float) -> tuple[object, object, str]:
    """Run the real chain and return ``(serialised flip, verdict, branch)``."""
    from alive.compose.phase2b import _band_sensitivity_block, preregistered_headline_branch

    bounds = _bounds(theta, q)
    sensitivity = band_sensitivity(
        bounds=bounds,
        band_inflation=LADDER,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
    )
    block = _band_sensitivity_block(sensitivity)
    flip = block["flip_lambda"]["additive"]
    verdict = _verdict(bounds)
    band_passes = verdict is not SealedAxis.NO_DISTINCT_WIN
    return (
        flip,
        verdict,
        preregistered_headline_branch(band_passes=band_passes, flip=flip, ladder_max=LADDER_MAX),
    )


def test_a_finite_flip_beyond_the_ladder_selects_sentence_one():
    """Codex's first measured input: `GI_LEARNABLE_WIN` with a finite flip of 2.5.

    2.5 is outside the registered ladder (max 1.25), so the margin holds across
    every registered lambda -- sentence (i) -- even though the flip is not the
    `NEVER_FLIPS` sentinel the document originally named.
    """
    theta = {
        "additive": 0.30,
        "gears": 0.30,
        "cpa": 0.30,
        "id_only": 0.30,
        "l3_symmetric_mlp": 0.30,
    }
    flip, verdict, branch = _measured_branch(theta, q=0.1)
    assert flip == pytest.approx(2.5)
    assert verdict is SealedAxis.GI_LEARNABLE_WIN
    assert branch == "i"


def test_a_finite_flip_at_or_below_the_registered_band_selects_sentence_three():
    """Codex's second measured input: `NO_DISTINCT_WIN` with a finite flip of 0.5."""
    theta = {
        "additive": 0.10,
        "gears": 0.30,
        "cpa": 0.30,
        "id_only": 0.30,
        "l3_symmetric_mlp": 0.30,
    }
    flip, verdict, branch = _measured_branch(theta, q=0.1)
    assert flip == pytest.approx(0.5)
    assert verdict is SealedAxis.NO_DISTINCT_WIN
    assert branch == "iii"


def test_the_zero_width_band_sentinels_keep_their_sentences():
    """`q == 0` is the only case the document's original wording covered."""
    from alive.compose.phase2b import preregistered_headline_branch

    assert (
        preregistered_headline_branch(band_passes=True, flip="NEVER_FLIPS", ladder_max=LADDER_MAX)
        == "i"
    )
    assert (
        preregistered_headline_branch(band_passes=True, flip=math.inf, ladder_max=LADDER_MAX) == "i"
    )
    assert (
        preregistered_headline_branch(
            band_passes=False, flip="FAILS_AT_REGISTERED_BAND", ladder_max=LADDER_MAX
        )
        == "iii"
    )
    assert (
        preregistered_headline_branch(band_passes=False, flip=-math.inf, ladder_max=LADDER_MAX)
        == "iii"
    )


@pytest.mark.parametrize("flip", [1.0000001, 1.1, 1.25])
def test_a_flip_inside_the_registered_ladder_selects_sentence_two(flip: float):
    """The whole half-open interval ``(1.0, ladder_max]`` is sentence (ii).

    The endpoint matters: 1.25 IS a registered lambda, so a flip exactly there
    flips inside the ladder and must not be reported as "holds throughout".
    """
    from alive.compose.phase2b import preregistered_headline_branch

    assert preregistered_headline_branch(band_passes=True, flip=flip, ladder_max=LADDER_MAX) == "ii"


def test_a_flip_just_beyond_the_ladder_max_is_sentence_one():
    """Non-vacuity for the boundary above: 1.25 is (ii) and 1.2500001 is (i)."""
    from alive.compose.phase2b import preregistered_headline_branch

    assert (
        preregistered_headline_branch(band_passes=True, flip=1.2500001, ladder_max=LADDER_MAX)
        == "i"
    )


@pytest.mark.parametrize("flip", [0.9, 1.0, -math.inf, "FAILS_AT_REGISTERED_BAND"])
def test_a_passing_band_with_a_failing_flip_is_refused(flip):
    """Unreachable by construction, so it is a bug -- not a fourth sentence."""
    from alive.compose.phase2b import preregistered_headline_branch

    with pytest.raises(ValueError, match="inconsistent band verdict and flip"):
        preregistered_headline_branch(band_passes=True, flip=flip, ladder_max=LADDER_MAX)


def test_the_branch_partition_is_total_over_the_measured_flip_range():
    """Every (band_passes, flip) the encoding can produce lands in exactly one arm.

    A partition that is merely "documented" can leave a hole; this sweeps the
    encoding's own range -- both sentinels plus a grid of finite flips on both
    sides of both boundaries -- and requires a branch for each reachable pair.
    """
    from alive.compose.phase2b import preregistered_headline_branch

    reachable = 0
    for band_passes in (True, False):
        for flip in [
            "NEVER_FLIPS",
            "FAILS_AT_REGISTERED_BAND",
            math.inf,
            -math.inf,
            0.0,
            0.5,
            1.0,
            1.0001,
            1.1,
            1.25,
            2.5,
            1e9,
        ]:
            try:
                branch = preregistered_headline_branch(
                    band_passes=band_passes, flip=flip, ladder_max=LADDER_MAX
                )
            except ValueError:
                continue
            assert branch in {"i", "ii", "iii"}
            reachable += 1
    # 12 refusals are impossible: the failing band always has a sentence.
    assert reachable >= 12, f"only {reachable} of the encoding's pairs have a sentence"
