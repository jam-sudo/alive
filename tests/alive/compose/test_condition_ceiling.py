"""The registered conditioning ceiling on the calibration design matrix Phi.

The 2026-07-29 representability guard was removed with the ridge normal equations
(commit ``04d74ca``). That guard was the only thing in the pipeline that ever
fired on **block-scale imbalance** between the expression block of ``z`` and the
ESM block — and it fired by accident, as a side effect of a penalty-loss check.
Nothing replaced it, and nothing upstream bounds the two blocks' relative scale.

This file pins the replacement: a registered ceiling on ``cond(Phi)`` at the
SELECTED total factor dimension, enforced as a **futility gate** (spec, section
10.4/10.6), not as an input rejection. The distinction is load-bearing:

* the sibling branch (``cond`` non-finite) is already FUTILITY_STOPPED, and
  ``cond = inf`` arises only from rank deficiency, so a rejection here would make
  the verdict discontinuous at the exact boundary where the two are one event;
* a futility stop preserves the rank report, spectrum and selected
  hyperparameters; a rejection would print one stderr line and discard them;
* "rescale the blocks and retry", which is what the retryable exit code invites,
  is a change chosen AFTER seeing a development diagnostic
  (``CLAUDE.md#invariants`` 14).

What the ceiling does NOT cover is recorded in the spec: the statistic is
invariant to a uniform rescale of ``z`` (to round-off), so uniform-scale penalty
immateriality is a separate registered limitation, not something this closes.

SYNTHETIC-ONLY: pure ``numpy``. No sealed access, no outcome store, no seal.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from alive.compose.config2 import (
    _EXPECTED_CONDITION_CEILING,
    Phase2ConfigError,
    load_compose_phase2_config,
)
from alive.compose.gates import LeakageError
from alive.compose.identify import rank_diagnostics
from alive.compose.operator import sym_basis_dim
from tests.alive.compose.test_config2 import CANON, _raw, _write
from tests.alive.compose.test_diagnostics2 import _full_rank_instance, _run

# The registered value, restated here so a silent config edit breaks THIS file's
# margin claims rather than passing unnoticed. Bound to config2 by the first test.
_REGISTERED_CEILING = 1.0e8

_REAL_PHI_REPORT = Path("docs/activation-evidence/compose/real_norman_phi_rank_report.json")

_CEILING_MARKER = "conditioning above the registered ceiling"


def _ceiling_failures(result) -> list[str]:
    return [f for f in result.failures if f.startswith(_CEILING_MARKER)]


# --------------------------------------------------------------------------- #
# the registered value, and the margins it was chosen for
# --------------------------------------------------------------------------- #
def test_the_ceiling_under_test_is_the_one_the_committed_config_registers():
    cfg = load_compose_phase2_config(CANON)
    assert cfg.condition_ceiling == _REGISTERED_CEILING
    assert _EXPECTED_CONDITION_CEILING == _REGISTERED_CEILING
    # The anchor is data-free: 1/sqrt(float64 eps) is where half the significant
    # digits are gone. The ceiling sits above it, so it never rejects a design
    # float64 can still resolve.
    assert _REGISTERED_CEILING > 1.0 / np.sqrt(np.finfo(np.float64).eps)


def test_the_block_imbalance_exhibit_clears_the_ceiling_by_orders_of_magnitude():
    """The exhibit from the guard that ``04d74ca`` deleted, re-measured here.

    Same construction as the removed ``test_one_over_scaled_factor_block_is_
    rejected_though_others_keep_the_penalty``: seed 6, k=4, the last two columns
    (registered ``esm_projection_dim: 2``) scaled by 1e6.
    """
    rng = np.random.default_rng(6)
    n_genes, k = 20, 4
    Z = rng.normal(size=(n_genes, k))
    pairs = [(int(a), int(b)) for a, b in rng.integers(0, n_genes, size=(40, 2)) if a != b]

    baseline = rank_diagnostics(Z, pairs).condition_number
    uniform = rank_diagnostics(Z * 1e6, pairs).condition_number
    Z_block = Z.copy()
    Z_block[:, 2:] *= 1e6
    imbalanced = rank_diagnostics(Z_block, pairs).condition_number

    # the design is FULL RANK in every case -- this is not a rank test
    assert rank_diagnostics(Z_block, pairs).is_full_rank
    assert uniform == pytest.approx(baseline, rel=1e-9)

    assert baseline < _REGISTERED_CEILING
    assert imbalanced > _REGISTERED_CEILING
    # both margins exceed four orders of magnitude, which is why the exact value
    # of the ceiling is not load-bearing between them
    assert np.log10(_REGISTERED_CEILING / baseline) > 4.0
    assert np.log10(imbalanced / _REGISTERED_CEILING) > 4.0


def test_a_uniform_rescale_leaves_the_statistic_where_it_was():
    """The property that makes this a block-imbalance detector, not a size limit.

    NOT exact equality: the two SVDs differ in the last couple of ulps, so an
    ``==`` assertion here would be a lie that happens to pass on one machine.
    """
    rng = np.random.default_rng(6)
    Z = rng.normal(size=(20, 4))
    pairs = [(int(a), int(b)) for a, b in rng.integers(0, 20, size=(40, 2)) if a != b]

    baseline = rank_diagnostics(Z, pairs).condition_number
    for scale in (1e-6, 1e3, 1e6):
        assert rank_diagnostics(Z * scale, pairs).condition_number == pytest.approx(
            baseline, rel=1e-9
        )


def test_the_recorded_real_designs_clear_the_registered_ceiling():
    """The registered ceiling must not trivially reject our own study.

    Read from the evidence file rather than transcribed, so a regenerated report
    is re-checked automatically instead of being compared against numbers frozen
    in a test. That report is bound to an EARLIER config digest (this branch moves
    it); the condition numbers are properties of the data and factor banks, and are
    used here only as an order-of-magnitude margin check, not as a live binding.
    """
    report = json.loads(_REAL_PHI_REPORT.read_text(encoding="utf-8"))
    per_k = report["report"]["per_k_total"]
    assert per_k, "the phi rank report records no dimension"
    for entry in per_k:
        cond = float(entry["condition_number"])
        assert np.isfinite(cond)
        assert cond < _REGISTERED_CEILING, (
            f"k_total={entry['k_total']} records cond={cond}, at or above the "
            "registered ceiling: the real study would futility-stop on conditioning"
        )
        assert np.log10(_REGISTERED_CEILING / cond) > 5.0


# --------------------------------------------------------------------------- #
# the gate, end to end through the futility checkpoint
# --------------------------------------------------------------------------- #
def test_a_well_conditioned_design_continues_under_the_registered_ceiling():
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert res.status == "CONTINUE"
    assert res.rank_report.condition_number < _REGISTERED_CEILING
    assert not _ceiling_failures(res)


def test_block_imbalance_adds_exactly_the_ceiling_failure_and_stops():
    """Isolation by differencing: the same inputs under two ceilings.

    The block-scaled instance may fail other gates too (its ``eps`` was generated
    from the unscaled ``z``), so asserting FUTILITY_STOPPED alone would not show
    the ceiling did anything. Running the identical inputs with the gate disabled
    and taking the difference attributes exactly one failure line to the ceiling.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k].copy()
    Z[:, 2:] *= 1e6  # ESM block only
    inst["factors_by_k"] = {k: Z}

    unbounded = _run(inst, condition_ceiling=float("inf"))
    bounded = _run(inst, condition_ceiling=_REGISTERED_CEILING)

    assert bounded.rank_report.is_full_rank, "this is a conditioning test, not a rank test"
    assert bounded.rank_report.condition_number > _REGISTERED_CEILING
    added = [f for f in bounded.failures if f not in unbounded.failures]
    assert len(added) == 1
    assert added[0].startswith(_CEILING_MARKER)
    assert str(_REGISTERED_CEILING) in added[0]
    assert bounded.status == "FUTILITY_STOPPED"
    # the development record survives the stop -- that is why this is not exit 10
    assert bounded.rank_report.rank == sym_basis_dim(k)
    assert bounded.singular_values.size == sym_basis_dim(k)
    assert bounded.sealed_access_count == 0


def test_a_rank_deficient_design_reports_one_conditioning_failure_not_two():
    """``rank_diagnostics`` returns ``inf`` for a rank-deficient design.

    ``inf > ceiling`` is True, so an unguarded ceiling branch would append a
    second conditioning line to every rank-deficient run, and the ceiling would
    appear to fire on designs whose actual defect is rank. The branches are
    exclusive; this pins that.
    """
    rng = np.random.default_rng(2)
    inst = _full_rank_instance(rng)
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k]
    v = rng.normal(size=Z.shape[1])
    inst["factors_by_k"] = {k: np.outer(rng.normal(size=Z.shape[0]), v)}

    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert res.status == "FUTILITY_STOPPED"
    assert not np.isfinite(res.rank_report.condition_number)
    assert not _ceiling_failures(res)
    assert sum(1 for f in res.failures if "conditioning" in f) == 1


# --------------------------------------------------------------------------- #
# the gate cannot be disabled by an unusable ceiling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ceiling",
    [float("nan"), 0.0, -1.0, -float("inf")],
    ids=["nan", "zero", "negative", "neg_inf"],
)
def test_an_unusable_ceiling_is_refused_rather_than_disabling_the_gate(ceiling):
    """``cond > nan`` is False, so a nan ceiling silences the gate on every input.

    That is the failure this project keeps hitting: a guard that is present,
    passes its tests, and never fires. Non-positive ceilings are refused for the
    opposite reason -- they would reject every design including a perfect one.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    with pytest.raises(ValueError, match="silently disables"):
        _run(inst, condition_ceiling=ceiling)


def test_the_refusal_precedes_selection_but_not_the_leakage_gate():
    """Both orderings around the refusal, because both were choices.

    Ahead of selection: a bad ceiling must be caught before the expensive OOF
    fit, not discovered after it. Behind the measurability gate: a call that is
    BOTH asking for a sealed role and carrying an unusable ceiling has to report
    the leakage attempt, which is the higher-severity event and a contracted
    rejection. An earlier draft of this guard sat at the top of the function and
    would have reported the config bug instead, hiding the leakage attempt.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)

    # ahead of selection: malformed selection inputs are never reached
    poisoned = dict(inst)
    poisoned["eps_obs"] = np.zeros((0, 0))
    with pytest.raises(ValueError, match="silently disables"):
        _run(poisoned, condition_ceiling=float("nan"))

    # behind the leakage gate: the sealed-role refusal wins
    assert not issubclass(LeakageError, ValueError), (
        "if LeakageError were a ValueError this assertion could not tell the two apart"
    )
    with pytest.raises(LeakageError):
        _run(
            inst,
            condition_ceiling=float("nan"),
            measurability_role="sealed_double_unseen",
        )


def test_an_infinite_ceiling_is_allowed_and_documented_as_no_ceiling():
    """``inf`` is the explicit opt-out the test suite uses; it is not an accident."""
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    res = _run(inst, condition_ceiling=float("inf"))
    assert res.status == "CONTINUE"
    assert not _ceiling_failures(res)


# --------------------------------------------------------------------------- #
# config: the ceiling is registered, exact, and cannot arrive unusable
# --------------------------------------------------------------------------- #
def test_the_config_key_is_required(tmp_path):
    raw = _raw()
    del raw["identification"]["condition_ceiling"]
    with pytest.raises(Phase2ConfigError, match="condition_ceiling"):
        load_compose_phase2_config(_write(tmp_path, raw))


@pytest.mark.parametrize(
    "value",
    ["1.0e8", True, None, [1.0e8]],
    ids=["str", "bool", "null", "list"],
)
def test_a_non_numeric_ceiling_is_refused_by_the_loader(tmp_path, value):
    """``"1.0e8"`` is not hypothetical: YAML 1.1 parses an unsigned exponent as a
    STRING, so the committed config must write ``1.0e+8``. The loader refuses the
    string rather than coercing it, which is how that was caught."""
    raw = _raw()
    raw["identification"]["condition_ceiling"] = value
    with pytest.raises(Phase2ConfigError, match="must be numeric"):
        load_compose_phase2_config(_write(tmp_path, raw))


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), -float("inf"), 0.0, -1.0e8],
    ids=["nan", "inf", "neg_inf", "zero", "negative"],
)
def test_an_unusable_numeric_ceiling_is_refused_for_being_unusable(tmp_path, value):
    """Matched on the SPECIFIC message, not on the key name.

    Every one of these also fails the exact-value comparison further down, whose
    message names ``condition_ceiling`` too — so a test keyed on the key name
    would still pass with the finite/positive check deleted, and the loader could
    hand a nan ceiling to a config that happened to register nan.
    """
    raw = _raw()
    raw["identification"]["condition_ceiling"] = value
    with pytest.raises(Phase2ConfigError, match="must be finite and positive"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_a_ceiling_other_than_the_preregistered_value_is_refused(tmp_path):
    raw = _raw()
    raw["identification"]["condition_ceiling"] = 1.0e9
    with pytest.raises(Phase2ConfigError, match="match the preregistration"):
        load_compose_phase2_config(_write(tmp_path, raw))


def test_the_committed_config_writes_the_exponent_form_yaml_can_parse():
    """Pins the trap itself: the raw mapping must yield a float, not a string."""
    raw = yaml.safe_load(Path(CANON).read_text(encoding="utf-8"))
    value = raw["identification"]["condition_ceiling"]
    assert isinstance(value, float), f"YAML parsed condition_ceiling as {type(value).__name__}"
    assert value == _REGISTERED_CEILING
