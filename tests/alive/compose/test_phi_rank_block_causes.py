"""Each way a phi-rank factor block can be refused says which way it was.

Decision #5 (2026-08-16, ``docs/superpowers/2026-08-16-compose-activation-rank-rule-decision.md``)
kept the activation gate's **ALL** rule on rank while the conditioning ceiling in
the same loop stays **ANY**, and paid for that asymmetry by making the refusal
legible. Before this file, eleven distinct causes shared one message —
``"phi-rank invalid or non-full-rank factor block for k_total=8"`` — so an
operator whose pod run stopped there could not tell a RANK DEFICIENCY (the
registered grid is misspecified; the remedy is a config change with a new run
identity) from a pair-count bookkeeping mismatch or a malformed condition number.

Two properties are pinned here, and the second is the one that matters:

1. every cause raises with its own message, and
2. **the accepted set moves only INWARD.** Splitting a fail-closed gate's message
   must not change which reports it accepts, so the 2026-08-16 split held the
   boundary exactly; the 2026-08-17 exactness fix then narrowed it deliberately,
   after an audit passed a "READY" report carrying ``k_total: 4.0``. The tests
   below assert both halves: the committed evidence still validates, every
   single-field corruption is still refused, the short-circuit ORDER is unchanged,
   the type stays ``ValueError`` — which is what ``config2`` catches to produce a
   contracted ``ScientificModeError`` rather than an uncontracted exit 1 — and no
   count or dimension accepts a non-``int``.

The ALL rule itself is pinned by
:func:`test_one_rank_deficient_dimension_still_refuses_the_whole_report`, so the
decision cannot be flipped to ANY without a named test failing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from alive.compose.phi_rank import (
    PHI_RANK_ACTIVATION_SCHEMA,
    validate_phi_rank_activation_report,
)

_REGISTERED_CEILING = 1.0e8
_REAL_PHI_REPORT = Path("docs/activation-evidence/compose/real_norman_phi_rank_report.json")

#: The block this file corrupts. ``k=8`` is the realistic one: ``sym_dim=36``
#: against 41 calibration pairs is the tightest margin in the registered grid.
_TARGET_K = 8


def _envelope():
    """The committed real-Norman report, repaired only where it is not under test.

    Same three normalisations as ``test_condition_ceiling.py`` — ``schema``
    predates the current envelope, ``git_sha`` is the short form, and
    ``activation`` is ``BLOCKED`` because the run it belongs to never opened a
    seal. Everything else is the committed value.
    """
    env = json.loads(_REAL_PHI_REPORT.read_text(encoding="utf-8"))
    env["schema"] = PHI_RANK_ACTIVATION_SCHEMA
    env["git_sha"] = env["git_sha"].ljust(40, "0")
    env["activation"] = "READY — normalised for this test only"
    return env


def _kwargs(env):
    """Expectations read from the PRISTINE envelope.

    Built before any corruption, so a mutated ``k_total`` mismatches the grid
    instead of silently redefining it.
    """
    return dict(
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


def _block(env, k=_TARGET_K):
    for block in env["report"]["per_k_total"]:
        if block["k_total"] == k:
            return block
    raise AssertionError(f"no k_total={k} block in the committed evidence")


def _validate_corrupted(**overrides):
    """Validate the committed evidence with ``overrides`` applied to one block."""
    env = _envelope()
    kwargs = _kwargs(env)
    _block(env).update(overrides)
    return validate_phi_rank_activation_report(env, **kwargs)


#: (id, block overrides, regex that must match ONLY this cause).
#:
#: The order matches the short-circuit order in ``_validate_factor_block``; the
#: ordering test below depends on that.
_CAUSES = [
    ("k_total", {"k_total": 5}, r"block k_total 5 does not match its registered grid position"),
    ("sym_dim", {"sym_dim": 35}, r"reported sym_dim 35 is not k\(k\+1\)/2 = 36"),
    ("rank", {"rank": 35}, r"RANK-DEFICIENT"),
    ("is_full_rank_false", {"is_full_rank": False}, r"is_full_rank is False, not the boolean True"),
    ("is_full_rank_truthy_1", {"is_full_rank": 1}, r"is_full_rank is 1, not the boolean True"),
    (
        "pairs_scored",
        {"n_calibration_pairs_scored": 40},
        r"scored 40 calibration pairs, but the report declares n_combo_calibration=41",
    ),
    (
        "pairs_skipped",
        {"n_calibration_pairs_skipped": 1},
        r"1 calibration pairs were skipped",
    ),
    (
        "n_genes",
        {"n_genes": 72},
        r"factor bank covers 72 genes, but the envelope declares n_z_universe_genes=73",
    ),
    ("condition_bool", {"condition_number": True}, r"condition_number is a boolean, not a number"),
    ("condition_str", {"condition_number": "484.2"}, r"condition_number '484.2' is not numeric"),
    ("condition_inf", {"condition_number": float("inf")}, r"condition_number inf is not finite"),
    ("condition_nan", {"condition_number": float("nan")}, r"condition_number nan is not finite"),
    ("condition_zero", {"condition_number": 0.0}, r"condition_number 0.0 is not positive"),
    ("condition_negative", {"condition_number": -1.0}, r"condition_number -1.0 is not positive"),
    # Exactness (2026-08-17). An external audit fed this validator `k_total: 4.0`
    # and `n_calibration_pairs_skipped: False` and a "READY" report passed: every
    # count and dimension was compared with a bare `!=`, which accepts an
    # integer-valued float and a bool. One entry per field; the float/bool matrix
    # is covered exhaustively by _INTEGER_FIELDS below.
    ("k_total_not_int", {"k_total": 8.0}, r"k_total must be a non-negative integer"),
    ("sym_dim_not_int", {"sym_dim": 36.0}, r"sym_dim must be a non-negative integer"),
    ("rank_not_int", {"rank": 36.0}, r"rank must be a non-negative integer"),
    (
        "scored_not_int",
        {"n_calibration_pairs_scored": 41.0},
        r"n_calibration_pairs_scored must be a non-negative integer",
    ),
    (
        "skipped_not_int",
        {"n_calibration_pairs_skipped": False},
        r"n_calibration_pairs_skipped must be a non-negative integer",
    ),
    ("n_genes_not_int", {"n_genes": 73.0}, r"n_genes must be a non-negative integer"),
    # An over-rank block is NOT a deficiency: `rank <= min(n_pairs, sym_dim)` holds
    # by construction, so it means the report is internally inconsistent. Folding it
    # into the deficiency branch made the message say "rank 37 is below sym_dim=36".
    ("rank_exceeds", {"rank": 37}, r"rank 37 EXCEEDS the identifiable subspace dimension"),
]

_CAUSE_IDS = [case[0] for case in _CAUSES]

#: Every field that must be an EXACT ``int``. A bare ``!=`` accepts both an
#: integer-valued float and a bool (``False == 0``, ``True == 1``).
_INTEGER_FIELDS = (
    "k_total",
    "sym_dim",
    "rank",
    "n_calibration_pairs_scored",
    "n_calibration_pairs_skipped",
    "n_genes",
)


# --------------------------------------------------------------------------- #
# 1. every cause names itself
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("overrides", "pattern"), [c[1:] for c in _CAUSES], ids=_CAUSE_IDS)
def test_each_cause_raises_its_own_message(overrides, pattern):
    with pytest.raises(ValueError, match=pattern):
        _validate_corrupted(**overrides)


@pytest.mark.parametrize(("overrides", "pattern"), [c[1:] for c in _CAUSES], ids=_CAUSE_IDS)
def test_every_message_names_the_offending_dimension(overrides, pattern):
    """An operator needs to know WHICH ``k_total`` stopped the run.

    The old combined message did carry it; losing it while splitting would be a
    regression the per-cause assertions above would not catch.
    """
    with pytest.raises(ValueError) as excinfo:
        _validate_corrupted(**overrides)
    assert f"k_total={_TARGET_K}" in str(excinfo.value)


def test_no_cause_can_be_mistaken_for_another():
    """The whole point of the split, asserted directly.

    Each cause's regex must match its own message and **no other** — otherwise the
    per-cause tests above would pass while an operator still could not tell a rank
    deficiency from a pair-count mismatch. This is what a naive split (same prefix,
    same wording, different suffix) would fail.
    """
    messages = {}
    for name, overrides, _ in _CAUSES:
        with pytest.raises(ValueError) as excinfo:
            _validate_corrupted(**overrides)
        messages[name] = str(excinfo.value)

    for name, _, pattern in _CAUSES:
        matched = [other for other, text in messages.items() if re.search(pattern, text)]
        assert matched == [name], f"{name}'s pattern also matched {sorted(set(matched) - {name})}"


@pytest.mark.parametrize("field", _INTEGER_FIELDS)
@pytest.mark.parametrize("cast", [float, bool], ids=["float", "bool"])
def test_no_count_or_dimension_accepts_a_non_int(field, cast):
    """The full field x type matrix, stated as exactness rather than as messages.

    ``4 == 4.0`` and ``0 == False`` in Python, so every one of these passed a bare
    ``!=`` and a whole report certified READY on values that are not the exact
    integers the artifact contract claims. Asserting refusal (not wording) is what
    makes this survive a future message rewrite.
    """
    with pytest.raises(ValueError, match="must be a non-negative integer"):
        _validate_corrupted(**{field: cast(_block(_envelope())[field])})


def test_an_over_rank_block_is_not_called_a_deficiency():
    """The regression this file's own split introduced, pinned.

    The message it replaced -- "invalid or non-full-rank factor block" -- was
    vague but TRUE for every cause. Naming the cause made it specific, and for
    ``rank > sym_dim`` specifically WRONG: it read "rank 37 is below the
    identifiable subspace dimension sym_dim=36". Precision is only an improvement
    when it is also correct.
    """
    with pytest.raises(ValueError) as excinfo:
        _validate_corrupted(rank=37)
    text = str(excinfo.value)
    assert "EXCEEDS" in text
    assert "below" not in text, "an over-rank block must not be described as deficient"
    assert "RANK-DEFICIENT" not in text


def test_the_rank_message_says_what_the_operator_must_do():
    """A rank deficiency is the one cause whose remedy is a CONFIG change.

    Every other cause here means the report is malformed and should be
    regenerated. A rank-deficient registered ``k`` means the registered grid is
    misspecified, and fixing it moves ``total_k_grid`` — a new run identity. The
    message has to carry that difference or the split has not earned its keep.
    """
    with pytest.raises(ValueError) as excinfo:
        _validate_corrupted(rank=35)
    text = str(excinfo.value)
    assert "RANK-DEFICIENT" in text
    assert "sym_dim=36" in text
    assert "not identifiable" in text


# --------------------------------------------------------------------------- #
# 2. the accepted set moves only inward
# --------------------------------------------------------------------------- #
def test_the_committed_evidence_still_validates():
    """The equivalence anchor: splitting the message accepted nothing new."""
    env = _envelope()
    assert validate_phi_rank_activation_report(env, **_kwargs(env))


@pytest.mark.parametrize(("overrides", "_pattern"), [c[1:] for c in _CAUSES], ids=_CAUSE_IDS)
def test_every_corruption_is_still_refused(overrides, _pattern):
    """Stated without reference to any message.

    If the split had dropped a clause, the per-cause test for that clause would
    fail on the *pattern* and could be "fixed" by relaxing the regex. This one
    cannot be fixed that way: it asserts refusal, nothing else.
    """
    with pytest.raises(ValueError):
        _validate_corrupted(**overrides)


@pytest.mark.parametrize(("overrides", "_pattern"), [c[1:] for c in _CAUSES], ids=_CAUSE_IDS)
def test_the_refusal_type_is_still_exactly_ValueError(overrides, _pattern):
    """``config2`` catches ``ValueError`` to raise a contracted ``ScientificModeError``.

    A subclass would still be caught, but an unrelated type would escape that
    ``except`` and leave the driver at an uncontracted exit 1 — the same escape
    class already fixed once for ``LinAlgError`` on the estimator path. Pinned as
    an EXACT type so a future refactor cannot narrow it to something the driver
    roster does not admit.
    """
    with pytest.raises(ValueError) as excinfo:
        _validate_corrupted(**overrides)
    assert type(excinfo.value) is ValueError


@pytest.mark.parametrize(
    ("first", "second", "winner"),
    [
        ({"sym_dim": 35}, {"rank": 35}, r"is not k\(k\+1\)/2"),
        ({"rank": 35}, {"is_full_rank": False}, r"RANK-DEFICIENT"),
        ({"rank": 35}, {"condition_number": float("nan")}, r"RANK-DEFICIENT"),
        ({"n_calibration_pairs_scored": 40}, {"n_genes": 72}, r"scored 40 calibration pairs"),
        ({"condition_number": True}, {"n_genes": 72}, r"factor bank covers 72 genes"),
    ],
    ids=[
        "sym_dim_before_rank",
        "rank_before_flag",
        "rank_before_condition",
        "pairs_before_genes",
        "genes_before_condition",
    ],
)
def test_the_short_circuit_order_is_unchanged(first, second, winner):
    """Two causes at once must still report the one the old ``or`` reached first.

    The last case is the discriminating one: ``n_genes`` was clause 7 and the
    condition-number clauses were 8-11, so a corrupt condition number must NOT
    pre-empt a gene-count mismatch. Reordering the checks is invisible to every
    single-cause test in this file.
    """
    with pytest.raises(ValueError, match=winner):
        _validate_corrupted(**{**first, **second})


# --------------------------------------------------------------------------- #
# 3. decision #5: rank is ALL, the ceiling is ANY
# --------------------------------------------------------------------------- #
def test_one_rank_deficient_dimension_still_refuses_the_whole_report():
    """Decision #5, pinned so it cannot be flipped silently.

    The audit proposed making rank use ANY like the ceiling. It was kept as ALL
    because the measurement showed the gate dormant on the real design and the two
    gates check different matrices anyway. Here ``k=8`` alone is rank-deficient and
    ``k=4``/``k=6`` are untouched: the ALL rule refuses the report, an ANY rule
    would accept it.
    """
    env = _envelope()
    kwargs = _kwargs(env)
    _block(env, 8)["rank"] = 35
    assert all(
        b["rank"] == b["sym_dim"] for b in env["report"]["per_k_total"] if b["k_total"] != 8
    ), "the premise: exactly one dimension is rank-deficient"
    with pytest.raises(ValueError, match="RANK-DEFICIENT"):
        validate_phi_rank_activation_report(env, **kwargs)


def test_one_over_ceiling_dimension_is_still_accepted():
    """The other half of the asymmetry, asserted next to it.

    Read together, these two tests ARE the decision: same loop, same report, one
    dimension degraded — rank refuses, the ceiling proceeds.
    """
    env = _envelope()
    kwargs = _kwargs(env)
    _block(env, 8)["condition_number"] = 1.0e12
    assert (
        sum(
            1
            for b in env["report"]["per_k_total"]
            if float(b["condition_number"]) > _REGISTERED_CEILING
        )
        == 1
    ), "the premise: exactly one dimension is over the ceiling"
    assert validate_phi_rank_activation_report(env, **kwargs)
