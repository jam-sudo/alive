"""Tests for the COMPOSE-K562-v1 Phase-2b EXACT-ROSTER sealed verdict (Task 2b-5).

Pure decision logic — NO seal, NO real Norman, NO outcomes. The function under
test maps headline DOUBLE-UNSEEN simultaneous lower bounds (from Task 2b-3/2b-4)
onto the registered sealed-axis verdict over the EXACT registered comparator
family, on TWO separate axes (method x sealed).

Governance pins exercised here:

* COMPOSE-SPECIFIC types (CLAUDE.md#seal): the verdict / integrity types are
  defined in ``alive.compose.verdict2`` and are NOT the CARTOGRAPHER
  ``alive.eval.verdict`` / ``alive.types.Verdict`` types.
* Only DOUBLE-UNSEEN drives this verdict; the single-unseen regime fails closed
  (raises) and can never enter this function.
* ``METHOD_VALIDATED`` is reported on a separate axis and is never described as,
  nor upgraded by, evidence of real generalization.
* Every evaluated clause is recorded regardless of which rule fired
  (no single-metric reporting).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from alive.compose.inference2 import ComposeSimultaneousBounds
from alive.compose.verdict2 import (
    ComposeIntegrityReport,
    ComposeSealedResult,
    MethodAxis,
    SealedAxis,
    sealed_verdict,
)

# The EXACT registered comparator family (config inference.comparator_family).
FAMILY = ("additive", "gears", "cpa", "id_only", "l3_hypernetwork")
# Registered double-unseen / single-unseen role names (config split.roles).
DOUBLE_UNSEEN = "sealed_double_unseen"
SINGLE_UNSEEN = "sealed_single_unseen"
# Registered margins (config metric block).
ADDITIVE_MARGIN = 0.05
LEARNED_MARGIN = 0.0
DISCLAIMER = "structural run-internal self-check, NOT an independent audit"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _bounds(lower: dict[str, float], *, comparators=FAMILY) -> ComposeSimultaneousBounds:
    """A ComposeSimultaneousBounds carrying the given per-comparator lower bounds."""
    theta = {c: lower[c] for c in comparators}
    return ComposeSimultaneousBounds(
        comparators=tuple(comparators),
        theta=theta,
        lower=dict(lower),
        band_halfwidth=0.01,
        confidence=0.95,
        n_replicates=200,
        seed=1234,
    )


def _valid_integrity(**overrides) -> ComposeIntegrityReport:
    """A ComposeIntegrityReport whose every clause passes unless overridden."""
    kwargs = dict(
        provenance_ok=True,
        leakage_ok=True,
        all_metrics_finite=True,
        sealed_access_consistent=True,
        sealed_n=64,
        minimum_sealed=10,
        disclaimer=DISCLAIMER,
    )
    kwargs.update(overrides)
    return ComposeIntegrityReport(**kwargs)


def _win_lower() -> dict[str, float]:
    """Lower bounds that, with valid integrity, produce GI_LEARNABLE_WIN."""
    return {"additive": 0.07, "gears": 0.03, "cpa": 0.02, "id_only": 0.04, "l3_hypernetwork": 0.01}


# ---------------------------------------------------------------------------
# COMPOSE-specific types (seal independence, CLAUDE.md#seal)
# ---------------------------------------------------------------------------


def test_types_are_compose_specific_not_cartographer() -> None:
    """COMPOSE enums/report must NOT be the CARTOGRAPHER verdict types."""
    from alive.eval.verdict import IntegrityReport as CartoIntegrity
    from alive.eval.verdict import VerdictResult as CartoVerdict
    from alive.types import Verdict as CartoVerdictEnum

    assert ComposeIntegrityReport is not CartoIntegrity
    assert ComposeSealedResult is not CartoVerdict
    assert SealedAxis is not CartoVerdictEnum
    # Sealed-axis enum carries exactly the registered COMPOSE values.
    assert {m.value for m in SealedAxis} == {
        "GI_LEARNABLE_WIN",
        "PARTIAL",
        "NO_DISTINCT_WIN",
        "FUTILITY_STOPPED",
        "INVALID",
    }
    assert {m.value for m in MethodAxis} == {"METHOD_VALIDATED", "METHOD_NOT_VALIDATED"}


def test_integrity_is_valid_is_logical_and_of_all_clauses() -> None:
    """is_valid is True only when every boolean clause and the sealed_n check pass."""
    assert _valid_integrity().is_valid is True
    assert _valid_integrity(provenance_ok=False).is_valid is False
    assert _valid_integrity(leakage_ok=False).is_valid is False
    assert _valid_integrity(all_metrics_finite=False).is_valid is False
    assert _valid_integrity(sealed_access_consistent=False).is_valid is False
    # sealed_n below minimum invalidates too.
    assert _valid_integrity(sealed_n=9, minimum_sealed=10).is_valid is False


def test_integrity_report_is_frozen() -> None:
    rep = _valid_integrity()
    with pytest.raises(FrozenInstanceError):
        rep.provenance_ok = False  # type: ignore[misc]


def test_sealed_result_is_frozen() -> None:
    res = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(_win_lower()),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    with pytest.raises(FrozenInstanceError):
        res.sealed_axis = SealedAxis.INVALID  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Integrity dominates → INVALID
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"provenance_ok": False},
        {"leakage_ok": False},
        {"all_metrics_finite": False},
        {"sealed_access_consistent": False},
        {"sealed_n": 9, "minimum_sealed": 10},
    ],
)
def test_integrity_invalid_each_clause_forces_invalid_even_when_bounds_would_win(
    override,
) -> None:
    """Any failed integrity clause → INVALID, even with winning bounds."""
    res = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(_win_lower()),  # would otherwise be GI_LEARNABLE_WIN
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(**override),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    assert res.sealed_axis is SealedAxis.INVALID
    assert res.clauses["integrity_valid"] is False
    # Even on INVALID, the bound clauses are still recorded as evidence.
    assert "additive_clears" in res.clauses
    assert "every_learned_beats" in res.clauses
    assert res.clauses["additive_clears"] is True
    assert res.clauses["every_learned_beats"] is True


# ---------------------------------------------------------------------------
# Roster validation — absent / extra comparator keys reject
# ---------------------------------------------------------------------------


def test_absent_comparator_key_raises() -> None:
    """A bounds object missing one of the five registered comparators raises."""
    lower = _win_lower()
    del lower["cpa"]
    bad = _bounds(lower, comparators=("additive", "gears", "id_only", "l3_hypernetwork"))
    with pytest.raises(ValueError):
        sealed_verdict(
            regime=DOUBLE_UNSEEN,
            bounds=bad,
            comparators=FAMILY,
            additive_margin=ADDITIVE_MARGIN,
            learned_margin=LEARNED_MARGIN,
            integrity=_valid_integrity(),
            method_axis=MethodAxis.METHOD_VALIDATED,
        )


def test_extra_comparator_key_raises() -> None:
    """A bounds object carrying an EXTRA comparator not in the roster raises."""
    lower = _win_lower()
    lower["unregistered"] = 0.5
    bad = _bounds(lower, comparators=(*FAMILY, "unregistered"))
    with pytest.raises(ValueError):
        sealed_verdict(
            regime=DOUBLE_UNSEEN,
            bounds=bad,
            comparators=FAMILY,
            additive_margin=ADDITIVE_MARGIN,
            learned_margin=LEARNED_MARGIN,
            integrity=_valid_integrity(),
            method_axis=MethodAxis.METHOD_VALIDATED,
        )


def test_missing_additive_key_raises() -> None:
    """'additive' must be present in the roster (and in the bounds)."""
    no_additive = ("gears", "cpa", "id_only", "l3_hypernetwork")
    lower = {c: 0.03 for c in no_additive}
    with pytest.raises(ValueError):
        sealed_verdict(
            regime=DOUBLE_UNSEEN,
            bounds=_bounds(lower, comparators=no_additive),
            comparators=no_additive,
            additive_margin=ADDITIVE_MARGIN,
            learned_margin=LEARNED_MARGIN,
            integrity=_valid_integrity(),
            method_axis=MethodAxis.METHOD_VALIDATED,
        )


def test_empty_learned_family_raises() -> None:
    """comparators == ('additive',) → empty learned family is an ERROR, never a win."""
    lower = {"additive": 0.07}
    with pytest.raises(ValueError):
        sealed_verdict(
            regime=DOUBLE_UNSEEN,
            bounds=_bounds(lower, comparators=("additive",)),
            comparators=("additive",),
            additive_margin=ADDITIVE_MARGIN,
            learned_margin=LEARNED_MARGIN,
            integrity=_valid_integrity(),
            method_axis=MethodAxis.METHOD_VALIDATED,
        )


# ---------------------------------------------------------------------------
# Single-unseen fails closed
# ---------------------------------------------------------------------------


def test_single_unseen_regime_raises() -> None:
    """Single-unseen results cannot enter this function — fail closed."""
    with pytest.raises(ValueError):
        sealed_verdict(
            regime=SINGLE_UNSEEN,
            bounds=_bounds(_win_lower()),
            comparators=FAMILY,
            additive_margin=ADDITIVE_MARGIN,
            learned_margin=LEARNED_MARGIN,
            integrity=_valid_integrity(),
            method_axis=MethodAxis.METHOD_VALIDATED,
        )


def test_unknown_regime_raises() -> None:
    """Anything other than the double-unseen role raises."""
    with pytest.raises(ValueError):
        sealed_verdict(
            regime="combo_calibration",
            bounds=_bounds(_win_lower()),
            comparators=FAMILY,
            additive_margin=ADDITIVE_MARGIN,
            learned_margin=LEARNED_MARGIN,
            integrity=_valid_integrity(),
            method_axis=MethodAxis.METHOD_VALIDATED,
        )


# ---------------------------------------------------------------------------
# Decision logic — strict inequalities at the registered thresholds
# ---------------------------------------------------------------------------


def test_gi_learnable_win() -> None:
    """additive lower 0.07 (>0.05) AND all learned lowers > 0 → GI_LEARNABLE_WIN."""
    res = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(_win_lower()),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    assert res.sealed_axis is SealedAxis.GI_LEARNABLE_WIN
    assert res.clauses["additive_clears"] is True
    assert res.clauses["every_learned_beats"] is True
    assert res.clauses["integrity_valid"] is True


def test_partial_one_learned_at_zero() -> None:
    """additive clears 0.05 but one learned lower == 0.0 (not >0) → PARTIAL."""
    lower = _win_lower()
    lower["id_only"] = 0.0  # fails strict > 0
    res = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(lower),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    assert res.sealed_axis is SealedAxis.PARTIAL
    assert res.clauses["additive_clears"] is True
    assert res.clauses["every_learned_beats"] is False


def test_no_distinct_win_additive_below_margin() -> None:
    """additive lower 0.04 (≤0.05) even with all learned lowers > 0 → NO_DISTINCT_WIN."""
    lower = _win_lower()
    lower["additive"] = 0.04
    res = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(lower),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    assert res.sealed_axis is SealedAxis.NO_DISTINCT_WIN
    assert res.clauses["additive_clears"] is False
    # learned family still recorded for audit.
    assert res.clauses["every_learned_beats"] is True


def test_boundary_additive_exactly_at_margin_is_no_distinct_win() -> None:
    """additive lower EXACTLY 0.05 → NOT > 0.05 → NO_DISTINCT_WIN."""
    lower = _win_lower()
    lower["additive"] = 0.05
    res = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(lower),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    assert res.sealed_axis is SealedAxis.NO_DISTINCT_WIN
    assert res.clauses["additive_clears"] is False


def test_boundary_learned_exactly_zero_is_partial_when_additive_clears() -> None:
    """A learned lower EXACTLY 0.0 fails strict >0 → PARTIAL (when additive clears)."""
    lower = _win_lower()
    lower["additive"] = 0.07  # clears
    lower["gears"] = 0.0  # exactly at learned margin → fails strict >
    res = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(lower),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    assert res.sealed_axis is SealedAxis.PARTIAL
    assert res.clauses["additive_clears"] is True
    assert res.clauses["every_learned_beats"] is False


# ---------------------------------------------------------------------------
# Two axes are reported and decided independently
# ---------------------------------------------------------------------------


def test_method_validated_does_not_upgrade_no_distinct_win() -> None:
    """METHOD_VALIDATED + NO_DISTINCT_WIN → both reported independently; neither moves."""
    lower = _win_lower()
    lower["additive"] = 0.04  # forces NO_DISTINCT_WIN
    res = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(lower),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    # Method axis unchanged by the sealed axis.
    assert res.method_axis is MethodAxis.METHOD_VALIDATED
    # Sealed axis unchanged by the method axis.
    assert res.sealed_axis is SealedAxis.NO_DISTINCT_WIN
    # Explicit caveat carried in evidence: METHOD_VALIDATED is not real generalization.
    note = res.evidence["method_axis_caveat"]
    assert isinstance(note, str)
    assert "generalization" in note.lower()


def test_method_not_validated_does_not_block_gi_learnable_win() -> None:
    """The sealed axis is decided from bounds+integrity only; method axis is orthogonal."""
    res = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(_win_lower()),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(),
        method_axis=MethodAxis.METHOD_NOT_VALIDATED,
    )
    assert res.method_axis is MethodAxis.METHOD_NOT_VALIDATED
    assert res.sealed_axis is SealedAxis.GI_LEARNABLE_WIN


# ---------------------------------------------------------------------------
# Full-clause auditability and evidence
# ---------------------------------------------------------------------------


def test_every_clause_recorded_regardless_of_fired_rule() -> None:
    """All evaluated clauses present in `clauses` no matter which rule fired."""
    expected = {"integrity_valid", "additive_clears", "every_learned_beats"}
    # INVALID path
    res_invalid = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(_win_lower()),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(provenance_ok=False),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    assert expected <= set(res_invalid.clauses)
    # WIN path
    res_win = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(_win_lower()),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    assert expected <= set(res_win.clauses)


def test_evidence_carries_bounds_margins_comparators_and_disclaimer() -> None:
    """Evidence carries the lower bounds, margins, comparator list, integrity disclaimer."""
    res = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(_win_lower()),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    assert res.evidence["additive_lower"] == 0.07
    assert res.evidence["learned_lower"] == {
        "gears": 0.03,
        "cpa": 0.02,
        "id_only": 0.04,
        "l3_hypernetwork": 0.01,
    }
    assert res.evidence["additive_margin"] == ADDITIVE_MARGIN
    assert res.evidence["learned_margin"] == LEARNED_MARGIN
    assert res.evidence["comparators"] == list(FAMILY)
    assert res.evidence["integrity_disclaimer"] == DISCLAIMER


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_identical_inputs_identical_checksum() -> None:
    """Identical inputs → identical checksum (deterministic, auditable)."""

    def build() -> ComposeSealedResult:
        return sealed_verdict(
            regime=DOUBLE_UNSEEN,
            bounds=_bounds(_win_lower()),
            comparators=FAMILY,
            additive_margin=ADDITIVE_MARGIN,
            learned_margin=LEARNED_MARGIN,
            integrity=_valid_integrity(),
            method_axis=MethodAxis.METHOD_VALIDATED,
        )

    assert build().checksum == build().checksum


def test_different_verdict_different_checksum() -> None:
    """A different sealed axis yields a different checksum."""
    win = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(_win_lower()),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    lose_lower = _win_lower()
    lose_lower["additive"] = 0.04
    lose = sealed_verdict(
        regime=DOUBLE_UNSEEN,
        bounds=_bounds(lose_lower),
        comparators=FAMILY,
        additive_margin=ADDITIVE_MARGIN,
        learned_margin=LEARNED_MARGIN,
        integrity=_valid_integrity(),
        method_axis=MethodAxis.METHOD_VALIDATED,
    )
    assert win.checksum != lose.checksum
