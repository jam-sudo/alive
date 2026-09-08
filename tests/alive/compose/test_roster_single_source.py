"""Single-source guard for the COMPOSE Phase-2 method roster and headline name.

The 9-method roster, the 5-comparator family and the headline method name
``"l1_bilinear_identifiable"`` are duplicated as plain string literals across
several modules (``config2``, ``freeze``, ``phase2b``, ``inference2``,
``verdict2``). Refactoring the modules to import from one another would risk an
import cycle, so this test is the regression guard instead: it imports the real
module-level constants and asserts they agree. A future edit that changes one
literal without the others will make this test FAIL in CI rather than silently
diverging.
"""

from __future__ import annotations

from alive.compose import config2, freeze, inference2, phase2b, verdict2

#: The exact headline literal pinned across all modules.
HEADLINE = "l1_bilinear_identifiable"

#: The exact registered comparator family (order included).
COMPARATOR_FAMILY = ("additive", "gears", "cpa", "id_only", "l3_symmetric_mlp")


def test_freeze_required_methods_match_config_roster() -> None:
    """``freeze.REQUIRED_METHODS`` is the exact ``config2`` roster, order included."""
    assert freeze.REQUIRED_METHODS == config2._EXPECTED_METHOD_ROSTER
    assert len(config2._EXPECTED_METHOD_ROSTER) == 9


def test_comparator_family_is_the_registered_five() -> None:
    """The comparator family is exactly the 5 registered names in that order."""
    assert config2._EXPECTED_COMPARATOR_FAMILY == COMPARATOR_FAMILY
    assert len(config2._EXPECTED_COMPARATOR_FAMILY) == 5


def test_comparator_family_relates_to_roster() -> None:
    """The family is a subset of the roster and excludes the two L1/L2 learned methods.

    The registered family is NOT simply ``roster - {headline, l2_saturation}``: it
    also drops the naive ``no_change`` / ``perturbation_mean`` baselines. The
    relationship that actually holds is a subset relationship plus explicit
    exclusion of the headline and the saturation method.
    """
    roster = set(config2._EXPECTED_METHOD_ROSTER)
    family = set(config2._EXPECTED_COMPARATOR_FAMILY)
    assert family.issubset(roster)
    assert HEADLINE not in config2._EXPECTED_COMPARATOR_FAMILY
    assert "l2_saturation" not in config2._EXPECTED_COMPARATOR_FAMILY


def test_headline_is_roster_first_entry() -> None:
    """The headline name is the first entry of the registered roster."""
    assert config2._EXPECTED_METHOD_ROSTER[0] == HEADLINE


def test_per_module_headline_constants_agree() -> None:
    """Every per-module headline constant equals the roster head and the pinned literal."""
    assert phase2b._HEADLINE == HEADLINE
    assert inference2.HEADLINE_METHOD == HEADLINE
    assert verdict2._HEADLINE_METHOD == HEADLINE

    assert phase2b._HEADLINE == config2._EXPECTED_METHOD_ROSTER[0]
    assert inference2.HEADLINE_METHOD == config2._EXPECTED_METHOD_ROSTER[0]
    assert verdict2._HEADLINE_METHOD == config2._EXPECTED_METHOD_ROSTER[0]
