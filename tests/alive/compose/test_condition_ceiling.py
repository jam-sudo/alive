"""The registered conditioning ceiling on the calibration design matrix Phi.

The 2026-07-29 representability guard was removed with the ridge normal equations
(commit ``04d74ca``). That guard was the only thing in the pipeline that ever
fired on **block-scale imbalance** between the expression block of ``z`` and the
ESM block — and it fired by accident, as a side effect of a penalty-loss check.
Nothing replaced it, and nothing upstream bounds the two blocks' relative scale.

This file pins the replacement: a registered ceiling on ``cond(Phi)``, applied as
a **per-candidate admissibility screen inside selection** — the same shape as the
sibling ``unregularized_oof_rank_policy``. An over-ceiling ``k_total`` is recorded
in ``nonviable_candidates`` with its reason and selection proceeds among the rest;
only when EVERY candidate is inadmissible does selection itself become invalid
(``SelectionError``, a contracted pre-seal rejection, exit 10, runbook category D
"investigate, do not re-run").

The first implementation enforced it on the WINNER as a futility condition. Three
independent reviews (2026-08-04) showed that was wrong on both axes:

* it terminated the study permanently whenever the best-scoring dimension was
  over the ceiling, even when the same registered grid held an admissible one;
* the justification for futility did not survive checking — the runbook does not
  say exit 10 means "fix and retry" (category D says the opposite), the durable
  futility report does not persist the spectrum it was said to preserve, and the
  registered futility vocabulary was never extended while the sibling threshold
  in the same config block (``uncovered_tolerance``) is a ``SelectionError``.

Two things the screen deliberately does NOT do. It never fires on a non-finite
condition number: that is exactly the rank-deficient case, which the registered
rank futility gate owns, and screening it here would make that gate unreachable.
And it does not police uniform factor magnitude — the statistic is invariant to a
uniform rescale of ``z`` (to round-off), so uniform-scale penalty immateriality is
recorded separately and is not closed by this.

SYNTHETIC-ONLY: pure ``numpy`` except the forwarding test, which drives the
``phase2a`` fixture path (and so builds a DEVELOPMENT outcome store). No sealed
access, no seal, in any test here.
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
from alive.compose.phi_rank import (
    PHI_RANK_ACTIVATION_SCHEMA,
    validate_phi_rank_activation_report,
)
from alive.compose.select import SelectionError
from tests.alive.compose.test_config2 import CANON, _raw, _write
from tests.alive.compose.test_diagnostics2 import _full_rank_instance, _run

# The registered value, restated here so a silent config edit breaks THIS file's
# margin claims rather than passing unnoticed. Bound to config2 by the first test.
_REGISTERED_CEILING = 1.0e8

_REAL_PHI_REPORT = Path("docs/activation-evidence/compose/real_norman_phi_rank_report.json")

_CEILING_MARKER = "conditioning above the registered ceiling"


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

    The numbers this reproduces are the ones the readiness index and the spec
    register, so the construction has to be byte-faithful. A first version of this
    test dropped ``_make``'s ``coef_true`` draw as unused — it IS unused, but it
    advances the RNG, so the pair set changed (37 pairs to 39) and the exhibit
    silently became ``9.91 -> 4.15e12`` while the documents kept quoting
    ``10.42 -> 3.71e12``. Two independent reviews caught it. The draw stays.
    """
    rng = np.random.default_rng(6)
    n_genes, k, p = 20, 4, 3
    Z = rng.normal(size=(n_genes, k))
    rng.normal(size=(p, sym_basis_dim(k)))  # `_make`'s coef_true: consumed, not used
    pairs = [(int(a), int(b)) for a, b in rng.integers(0, n_genes, size=(40, 2)) if a != b]

    baseline = rank_diagnostics(Z, pairs).condition_number
    uniform = rank_diagnostics(Z * 1e6, pairs).condition_number
    Z_block = Z.copy()
    Z_block[:, 2:] *= 1e6
    imbalanced = rank_diagnostics(Z_block, pairs).condition_number

    # the design is FULL RANK in every case -- this is not a rank test
    assert rank_diagnostics(Z_block, pairs).is_full_rank
    assert uniform == pytest.approx(baseline, rel=1e-9)

    # the exact values the spec and the readiness index register
    assert len(pairs) == 37
    assert baseline == pytest.approx(10.421787979549746, rel=1e-12)
    assert uniform == pytest.approx(10.421787979549734, rel=1e-12)
    assert imbalanced == pytest.approx(3.7131219108597812e12, rel=1e-12)

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
# the screen, inside selection
# --------------------------------------------------------------------------- #
def _nonviable_reasons(result) -> list[str]:
    return [r for _, _, r in result.nonviable_candidates if r.startswith(_CEILING_MARKER)]


def test_a_well_conditioned_design_continues_and_screens_nothing():
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert res.status == "CONTINUE"
    assert res.rank_report.condition_number < _REGISTERED_CEILING
    assert not _nonviable_reasons(res)


def test_an_over_ceiling_dimension_is_dropped_and_an_admissible_one_is_selected():
    """The finding this design exists to answer.

    Enforcing the ceiling on the WINNER meant a single over-ceiling ``k_total``
    permanently terminated the study — count 0, no re-run — even when the same
    registered grid held an admissible alternative. Screened per candidate, the
    bad dimension is recorded with its reason and selection moves on.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng, k=4)
    Z4 = inst["factors_by_k"][4]
    Z6 = np.hstack([Z4, rng.normal(size=(Z4.shape[0], 2)) * 1e6])  # imbalanced block

    inst["factors_by_k"] = {4: Z4, 6: Z6}
    inst["k_total_grid"] = [4, 6]

    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert rank_diagnostics(Z6, inst["idx_pairs"]).condition_number > _REGISTERED_CEILING
    assert res.status == "CONTINUE", "an admissible dimension existed; the run must not die"
    assert res.selected_k_total == 4
    dropped = [(k, lam) for k, lam, r in res.nonviable_candidates if r.startswith(_CEILING_MARKER)]
    assert {k for k, _ in dropped} == {6}, "every lambda at the bad k_total is dropped"
    assert len(dropped) == len(inst["lambda_grid"])
    assert not res.failures


def test_when_every_dimension_is_inadmissible_selection_itself_is_invalid():
    """All candidates screened out is a REJECTION, not a futility verdict.

    ``SelectionError`` is already rostered as a contracted pre-seal rejection
    (exit 10) and already sits in the runbook's category D — "scientifically
    invalid, investigate rather than re-run" — which is the instruction this
    situation needs. No new exception class and no new futility condition.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k].copy()
    Z[:, 2:] *= 1e6  # ESM block only
    inst["factors_by_k"] = {k: Z}

    assert rank_diagnostics(Z, inst["idx_pairs"]).is_full_rank, "conditioning, not rank"
    with pytest.raises(SelectionError) as excinfo:
        _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert "no viable hyperparameter candidate" in str(excinfo.value)
    assert _CEILING_MARKER in str(excinfo.value), "the reason must reach the operator"


def test_the_screen_never_swallows_rank_deficiency():
    """The trap in moving the ceiling into selection.

    ``rank_diagnostics`` returns ``inf`` exactly for a rank-deficient design, and
    ``inf > ceiling`` is True. A screen that fired on it would drop every
    rank-deficient dimension as merely "non-viable" — selection would quietly move
    to a full-rank one and the run would CONTINUE, making the registered rank
    futility gate unreachable. The screen is restricted to FINITE condition
    numbers so rank deficiency still stops the run.
    """
    rng = np.random.default_rng(2)
    inst = _full_rank_instance(rng)
    k = inst["selected_k_total"]
    Z = inst["factors_by_k"][k]
    v = rng.normal(size=Z.shape[1])
    inst["factors_by_k"] = {k: np.outer(rng.normal(size=Z.shape[0]), v)}

    res = _run(inst, condition_ceiling=_REGISTERED_CEILING)
    assert not np.isfinite(res.rank_report.condition_number)
    assert res.status == "FUTILITY_STOPPED"
    assert any("rank" in f.lower() for f in res.failures)
    assert not _nonviable_reasons(res), "rank deficiency is the rank gate's, not the screen's"


def test_the_bound_is_inclusive_and_the_comparison_is_one_ulp_sharp():
    """The registered wording is "at or below", so the comparison is ``>``.

    Found by mutation: flipping ``>`` to ``>=`` changed nothing, because no test
    went near the boundary. A design whose condition number is exactly ``1.0e8``
    cannot be constructed, so the ceiling is moved onto the measured value
    instead — the same comparison, from the other side.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    measured = rank_diagnostics(
        inst["factors_by_k"][inst["selected_k_total"]], inst["idx_pairs"]
    ).condition_number

    at_the_bound = _run(inst, condition_ceiling=measured)
    assert at_the_bound.status == "CONTINUE", "the bound is inclusive"
    assert not _nonviable_reasons(at_the_bound)

    with pytest.raises(SelectionError, match=_CEILING_MARKER):
        _run(inst, condition_ceiling=float(np.nextafter(measured, 0.0)))


def test_phase2a_forwards_the_registered_ceiling_rather_than_a_literal():
    """The screen is only as good as the value production actually hands it.

    Deleting the argument in ``phase2a`` is a ``TypeError`` the parameter's
    requiredness already catches. Passing a WRONG one — a hardcoded ``inf``, say —
    is caught by nothing: the screen would be dead in production with every test
    green.

    Checked with a SENTINEL config value, so a literal is caught even when it
    equals the registered one; comparing against the canonical config alone would
    not, and a hardcoded ``1.0e8`` passed that weaker form under mutation.

    The two sibling config-bound policies keep the weaker assertion on purpose:
    ``select.py`` pins both to registered constants and raises ``SelectionError``
    on anything else, so a literal there cannot diverge without failing loudly,
    and a sentinel is refused before it can prove anything. A sentinel CEILING is
    accepted (any finite positive value is legal), which is what makes the strong
    form possible here.
    """
    import dataclasses

    from alive.compose import phase2a
    from tests.alive.compose.test_phase2a import _HASHES, _build_instance, _inputs, _store

    canonical = load_compose_phase2_config(CANON)
    assert canonical.condition_ceiling == _REGISTERED_CEILING
    # distinct from the registered value, and permissive enough not to change the
    # verdict -- this test is about plumbing, not about the screen firing
    altered = dataclasses.replace(canonical, condition_ceiling=1.0e30)

    seen: dict = {}
    real = phase2a.real_calibration_diagnostics

    def _spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    phase2a.real_calibration_diagnostics = _spy
    try:
        rng = np.random.default_rng(0)
        inst = _build_instance(rng)
        phase2a.run_phase2a_fixture(
            _inputs(inst), _store(inst), expected_hashes=_HASHES, config=altered
        )
    finally:
        phase2a.real_calibration_diagnostics = real

    assert seen["condition_ceiling"] == 1.0e30, "phase2a is not forwarding the config value"
    assert seen["rank_tolerance_rule"] == canonical.rank_tolerance_rule
    assert seen["unregularized_oof_rank_policy"] == canonical.unregularized_oof_rank_policy


# --------------------------------------------------------------------------- #
# the screen cannot be silenced by an unusable ceiling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ceiling",
    [float("nan"), float("inf"), -float("inf"), 0.0, -1.0],
    ids=["nan", "inf", "neg_inf", "zero", "negative"],
)
def test_an_unusable_ceiling_is_refused_by_selection(ceiling):
    """Two opposite failures, one refusal.

    ``cond > nan`` and ``cond > inf`` are always False, so such a ceiling silences
    the screen on every candidate — a guard that is present, passes its tests, and
    never fires. A non-positive ceiling is always True, so it rejects every
    candidate including a perfect design. An earlier draft's message called ALL of
    these "silently disables", which is wrong for three of the five.
    """
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    with pytest.raises(SelectionError, match="must be finite and positive"):
        _run(inst, condition_ceiling=ceiling)


def test_the_refusal_still_sits_behind_the_leakage_gate():
    """A call that is both requesting a sealed role and carrying an unusable
    ceiling must report the LEAKAGE attempt, not the config-integrity failure that
    would hide it. Selection runs after ``measurability_gate``, so this holds by
    construction — pinned because an earlier draft placed the check at the top of
    the function and inverted it."""
    rng = np.random.default_rng(0)
    inst = _full_rank_instance(rng)
    assert not issubclass(LeakageError, ValueError), (
        "if LeakageError were a ValueError this assertion could not tell the two apart"
    )
    with pytest.raises(LeakageError):
        _run(inst, condition_ceiling=float("nan"), measurability_role="sealed_double_unseen")


# --------------------------------------------------------------------------- #
# the activation gate and the run's screen must agree
# --------------------------------------------------------------------------- #
def _envelope_under_test(**block_overrides):
    """The committed phi-rank evidence, repaired only where it is not under test.

    Three fields are normalised because they are not what this exercises and each
    would trip an earlier check: ``schema`` predates the current envelope,
    ``git_sha`` is the short form, and ``activation`` is ``BLOCKED`` (the committed
    report deliberately records a blocked lineage — the run it belongs to never
    opened a seal). Every other field is the committed value, and the expectations
    below are read FROM the envelope, so the conditioning check is the only thing
    left that can fail.
    """
    env = json.loads(_REAL_PHI_REPORT.read_text(encoding="utf-8"))
    env["schema"] = PHI_RANK_ACTIVATION_SCHEMA
    env["git_sha"] = env["git_sha"].ljust(40, "0")
    env["activation"] = "READY — normalised for this test only"
    for block in env["report"]["per_k_total"]:
        block.update(block_overrides)
    return env


def _validate(env):
    return validate_phi_rank_activation_report(
        env,
        expected_protocol=env["protocol"],
        expected_config_sha256=env["config_sha256"],
        expected_git_sha=env["git_sha"],
        expected_data_sha256=env["data_sha256"],
        expected_sequence_mapping_sha256=env["sequence_mapping_sha256"],
        expected_split_seed=11,
        expected_calibration_fraction=env["report"]["calibration_fraction"],
        expected_total_k_grid=[b["k_total"] for b in env["report"]["per_k_total"]],
        expected_esm_model=env["esm_model"],
        expected_esm_dim=env["report"]["esm_dim"],
        expected_condition_ceiling=_REGISTERED_CEILING,
    )


def test_the_committed_activation_evidence_still_passes_the_bound_validator():
    """Adding the ceiling must not invalidate evidence already in hand."""
    _validate(_envelope_under_test())


@pytest.mark.parametrize(
    "condition", [1.0e8 + 1.0, 1.0e12, 1.7e308], ids=["just_over", "1e12", "max"]
)
def test_the_activation_gate_refuses_what_the_run_would_screen_out(condition):
    """The gap two reviews found independently: two gates, one statistic, no
    agreement.

    ``compute_phi_rank_report`` calls the SAME ``rank_diagnostics`` on the SAME
    full-calibration design as the run's admissibility screen, but the validator
    only ever checked full rank and finiteness. A report certifying "READY" for a
    dimension the run then refuses costs an owner approval and a pod trip to
    discover. It is now bound, and the message is separate from the rank one so an
    operator is not sent looking for the wrong defect.
    """
    with pytest.raises(ValueError, match="conditioned above the registered ceiling"):
        _validate(_envelope_under_test(condition_number=condition))


def test_the_ceiling_the_activation_gate_uses_comes_from_the_config():
    """Not a literal in `phi_rank.py`: a stricter ceiling must reject more."""
    env = _envelope_under_test()
    worst = max(float(b["condition_number"]) for b in env["report"]["per_k_total"])
    kwargs = dict(
        expected_protocol=env["protocol"],
        expected_config_sha256=env["config_sha256"],
        expected_git_sha=env["git_sha"],
        expected_data_sha256=env["data_sha256"],
        expected_sequence_mapping_sha256=env["sequence_mapping_sha256"],
        expected_split_seed=11,
        expected_calibration_fraction=env["report"]["calibration_fraction"],
        expected_total_k_grid=[b["k_total"] for b in env["report"]["per_k_total"]],
        expected_esm_model=env["esm_model"],
        expected_esm_dim=env["report"]["esm_dim"],
    )
    validate_phi_rank_activation_report(env, expected_condition_ceiling=worst, **kwargs)
    with pytest.raises(ValueError, match="conditioned above the registered ceiling"):
        validate_phi_rank_activation_report(
            env, expected_condition_ceiling=float(np.nextafter(worst, 0.0)), **kwargs
        )


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
