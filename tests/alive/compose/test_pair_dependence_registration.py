"""Decision 2026-08-29 (pair dependence): the coverage claim and the band ladder
are REGISTERED values the loader enforces exactly.

`docs/superpowers/2026-08-29-compose-pair-dependence-decision.md` settles that the
simultaneous coverage claim is conditional on the registered resampling unit, and
freezes a band-inflation ladder that the report walks. Prose does not enforce
anything; this pins both to the loader, in the same shape as decision #7's
`factor_bank_normalization` and the existing `shared_resamples_across_contrasts`.

Why the ladder is not arbitrary (evidence:
`docs/superpowers/evidence/2026-08-26-pair-gene-dependence-coverage/`): on the real
headline structure the minimum band inflation restoring nominal coverage was
measured at 1.0 / 1.10 / 1.15 / 1.10 across the sigma ladder -- worst case interior
at 1.15 -- so the registered values are an anchor, not a guess.
"""

from __future__ import annotations

import math

import pytest
import yaml

from alive.compose.config2 import (
    _EXPECTED_SENSITIVITY_BAND_INFLATION,
    _EXPECTED_SIMULTANEOUS_COVERAGE_CLAIM,
    Phase2ConfigError,
    load_compose_phase2_config,
)

CONFIG = "configs/compose_k562_v1_phase2.yaml"


def _raw() -> dict:
    with open(CONFIG, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _write(tmp_path, raw, name="mutated.yaml") -> str:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return str(path)


def test_the_committed_config_registers_both_values():
    cfg = load_compose_phase2_config(CONFIG)
    assert (
        cfg.simultaneous_coverage_claim
        == _EXPECTED_SIMULTANEOUS_COVERAGE_CLAIM
        == "conditional_on_registered_resampling_unit"
    )
    assert cfg.sensitivity_band_inflation == _EXPECTED_SENSITIVITY_BAND_INFLATION


def test_the_registered_ladder_is_well_formed():
    """Pins the CONSTANT, not the config: the verdict is decided at the first
    value, so it must be exactly the registered band, and the ladder must climb.
    An exact-match config check cannot notice the constant itself going wrong."""
    ladder = _EXPECTED_SENSITIVITY_BAND_INFLATION
    assert ladder[0] == 1.0, "the verdict is decided at lambda = 1.0; it must lead the ladder"
    assert all(math.isfinite(x) for x in ladder)
    assert all(x >= 1.0 for x in ladder), "a lambda below 1 would NARROW the registered band"
    assert list(ladder) == sorted(ladder) and len(set(ladder)) == len(ladder)


def test_an_unregistered_coverage_claim_is_refused(tmp_path):
    raw = _raw()
    raw["inference"]["simultaneous_coverage_claim"] = "unconditional"
    with pytest.raises(Phase2ConfigError, match="simultaneous_coverage_claim must be"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_a_missing_coverage_claim_is_refused(tmp_path):
    """Silence is not a default: an absent key must fail closed, not fall back to
    the unconditional reading the decision exists to remove."""
    raw = _raw()
    del raw["inference"]["simultaneous_coverage_claim"]
    with pytest.raises(Phase2ConfigError, match="simultaneous_coverage_claim"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_an_unregistered_ladder_is_refused(tmp_path):
    raw = _raw()
    raw["inference"]["sensitivity_band_inflation"] = [1.0, 2.0]
    with pytest.raises(Phase2ConfigError, match="sensitivity_band_inflation must match"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_a_ladder_that_drops_the_registered_band_is_refused(tmp_path):
    """Dropping 1.0 would leave the verdict with no registered band to be decided
    on -- the failure mode that turns a descriptive report into the gate."""
    raw = _raw()
    raw["inference"]["sensitivity_band_inflation"] = [1.1, 1.15, 1.25]
    with pytest.raises(Phase2ConfigError, match="sensitivity_band_inflation must match"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_a_missing_ladder_is_refused(tmp_path):
    raw = _raw()
    del raw["inference"]["sensitivity_band_inflation"]
    with pytest.raises(Phase2ConfigError, match="sensitivity_band_inflation"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_a_non_numeric_ladder_is_refused(tmp_path):
    raw = _raw()
    raw["inference"]["sensitivity_band_inflation"] = ["1.0", "1.1"]
    with pytest.raises(Phase2ConfigError, match="must be a list of numbers"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_a_boolean_ladder_entry_is_refused(tmp_path):
    """`True` is an int in Python; without an explicit bool check it would pass
    the numeric test and then compare equal to 1.0."""
    raw = _raw()
    raw["inference"]["sensitivity_band_inflation"] = [True, 1.1, 1.15, 1.25]
    with pytest.raises(Phase2ConfigError, match="must be a list of numbers"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_the_verdict_thresholds_did_not_move(tmp_path):
    """The decision changes what is REPORTED, never what is DECIDED. If this test
    ever fails, the sensitivity report has become a verdict gate."""
    cfg = load_compose_phase2_config(CONFIG)
    assert cfg.material_margin_vs_additive == 0.05
    assert cfg.learned_comparator_margin == 0.0
    assert cfg.family_confidence == 0.95
    assert cfg.bootstrap_replicates == 10000
    assert cfg.resampling_unit == "perturbation_pair"
    assert cfg.secondary_are_verdict_gates is False
