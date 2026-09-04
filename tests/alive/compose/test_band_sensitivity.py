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
