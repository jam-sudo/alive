"""Pre-registered headline sentences for COMPOSE Phase-2b (D4 §8) and the branch that picks one.

Why this is a module of its own
-------------------------------
``phase2b`` imports ``durable`` at module scope, so a renderer living in ``phase2b`` cannot be
imported by ``durable`` -- measured in-memory as ``ImportError: cannot import name ... from
partially initialized module 'alive.compose.phase2b' (most likely due to a circular import)``,
with the same machinery importing cleanly when the injected import is removed. ``durable`` has to
re-derive the sentence to re-check it (it sees only checksum binding today, which a
self-consistent forgery passes), so the branch and the sentences live in a LEAF module that both
sides may import. Nothing here may import ``phase2b``, ``durable`` or ``terminal``.

What the sentences are
----------------------
:data:`REGISTERED_HEADLINE_SENTENCES` is a **copy** of the four sentences signed into
``docs/superpowers/2026-08-29-compose-pair-dependence-decision.md`` §8 on 2026-09-07 (D4), with
the Markdown label prefix dropped and line breaks normalised to a single space. The document is
the original; ``tests/alive/compose/test_audit_contract_docs.py`` enforces equality after the same
normalisation, so neither side can drift alone. Sentence (ii) carries the registered
:data:`FLIP_PLACEHOLDER`; substituting it is the whole point of this module, because until now the
substitution was left to a human hand at report time -- the freedom D4 exists to close.
"""

from __future__ import annotations

import math
from typing import Literal

from alive.compose.verdict2 import SealedAxis

#: Flip-point labels for the two non-finite cases ``band_sensitivity`` can return: a
#: zero-width band keeps its lambda = 1 state at every inflation, so the clause either
#: never flips (``+inf``) or already fails at the registered band (``-inf``). Encoded
#: as labels rather than the shared NON_FINITE sentinel so the two are distinguishable.
#: §8 writes the sentences against these exact tokens so the prose cannot drift from the code.
_FLIP_NEVER = "NEVER_FLIPS"
_FLIP_ALREADY_FAILED = "FAILS_AT_REGISTERED_BAND"

#: The placeholder sentence (ii) registers for the inflation at which the clause flips, and the
#: one the extrapolation note reuses. Its canonical substitution is ``repr(float(flip))``.
FLIP_PLACEHOLDER = "<flip>"
#: The placeholder for the registered ladder maximum in the extrapolation note.
LADDER_MAX_PLACEHOLDER = "<ladder_max>"

HEADLINE_SENTENCE_I = (
    "headline contrast 는 등록된 sensitivity 사다리 전 구간에서 material margin 을 유지한다. "
    "이는 등록된 resampling 단위 (`perturbation_pair`) 가정 아래의 결과이며, "
    "22 pairs/21 genes 의 구성상 pair-i.i.d. 위배를 흡수할 재표본 단위가 이 설계에 "
    "없다는 제한과 실제 method-specific dependence 의 크기가 미측정이라는 제한은 그대로다."
)

HEADLINE_SENTENCE_II = (
    "등록 밴드에서는 승리했으나 등록된 상위 inflation λ=<flip> 에서 유지되지 않았다. "
    "이는 pair resampling 가정에 조건부인 결과이며 unconditional efficacy 또는 "
    "unconditional 95% coverage 를 주장하지 않는다. 저장소 simulation 의 "
    "method-differential coverage (명목 0.95 대비 0.9240~0.9373)는 특정 생성모형의 "
    "값이지 실제 Norman coverage 측정이 아니다."
)

HEADLINE_SENTENCE_III = (
    "등록된 밴드에서 material margin 미달 — `NO_DISTINCT_WIN`. 불변식 14 에 따라 이는 "
    "결과이며 threshold 를 사후 변경하거나 sensitivity 사다리의 다른 λ 를 verdict gate 로 "
    "승격하지 않는다."
)

HEADLINE_SENTENCE_IV = (
    "등록된 learned comparator family({GEARS, CPA, ID-only, L3}) 각각에 대한 simultaneous "
    "lower bound 이 0 을 넘었다 — 이는 등록된 verdict 조건의 통과이지 architecture "
    "attribution 이 아니며(수정안 F), L1↔L2·L1↔L3 의 구조 기여는 exploratory 로만 "
    "보고한다. unconditional efficacy 를 주장하지 않는다."
)

#: The four signed §8 sentences, keyed by their document label. ``"iv"`` ADDS to the band
#: sentence rather than replacing it (§8, 2026-09-08 addition).
REGISTERED_HEADLINE_SENTENCES: dict[str, str] = {
    "i": HEADLINE_SENTENCE_I,
    "ii": HEADLINE_SENTENCE_II,
    "iii": HEADLINE_SENTENCE_III,
    "iv": HEADLINE_SENTENCE_IV,
}

#: Branch (i) with a FINITE flip: §8's 2026-09-08 correction requires the extrapolation point to
#: be reported alongside sentence (i) while the claim stays inside the registered ladder.
FINITE_FLIP_NOTE = (
    "외삽 flip 은 λ=<flip> 이며 등록 사다리 밖이다 — claim 은 등록 사다리 구간"
    "(λ ≤ <ladder_max>)에 한정하고 사다리 밖 λ 는 보고값이지 주장이 아니다."
)

#: Terminals with no valid verdict carry no pre-registered headline sentence (owner-approved
#: scope correction, 2026-09-09). ``INVALID`` declares the run's integrity precondition failed,
#: and futility is not a negative verdict (CLAUDE.md#seal) -- neither is a result to headline.
NO_HEADLINE_AXES: tuple[str, ...] = (SealedAxis.INVALID.value, SealedAxis.FUTILITY_STOPPED.value)

#: The only axis whose verdict requires the learned-comparator leg, i.e. the only one that
#: carries sentence (iv).
LEARNED_FAMILY_AXIS = SealedAxis.GI_LEARNABLE_WIN.value


def preregistered_headline_branch(
    *, band_passes: bool, flip: float | str, ladder_max: float
) -> Literal["i", "ii", "iii"]:
    """Which pre-registered headline sentence a result selects (D4 §8).

    The decision document pre-registers four sentences so nobody can pick the
    wording after seeing the result. Its first three were written against the two
    NON-FINITE flip labels only, which a zero-width band (``q == 0``) produces --
    and a normal ``q > 0`` run produces a FINITE flip. PR #15 finding I3 measured
    two such results that no sentence claimed: ``flip = 2.5`` with a passing band
    (outside the registered ladder, so it never flips inside it) and
    ``flip = 0.5`` with a failing band. The branch therefore lives here, in code,
    and §8 cites it; the document no longer owns a partition it cannot enumerate.

    Parameters
    ----------
    band_passes : bool
        Did the headline additive contrast clear its registered material margin
        at the REGISTERED band ``lambda = 1.0``? This is the verdict's own
        question and is authoritative for sentence (iii).
    flip : float or str
        ``ComposeBandSensitivity.flip_lambda['additive']``, either as the serialised
        label (:data:`_FLIP_NEVER` / :data:`_FLIP_ALREADY_FAILED`) or as the raw
        float, ``+-inf`` included.
    ladder_max : float
        The largest registered ``sensitivity_band_inflation`` (currently ``1.25``).
        Passed by the caller from the committed config -- never hardcoded here,
        because the ladder is a registered value and this module is production
        source.

    Returns
    -------
    {"i", "ii", "iii"}
        ``"i"``  -- the margin holds across the WHOLE registered ladder
        (``NEVER_FLIPS``, or a finite flip beyond ``ladder_max``);
        ``"ii"`` -- won at the registered band, flips at a registered higher
        ``lambda`` (finite ``1.0 < flip <= ladder_max``);
        ``"iii"`` -- the registered band itself was not cleared.

    Raises
    ------
    ValueError
        If ``band_passes`` is true while the flip says the clause fails at or
        below the registered band (finite ``flip <= 1.0`` or
        ``FAILS_AT_REGISTERED_BAND``). Clearing the band means the lower bound is
        above the threshold at ``lambda = 1``, which forces ``flip > 1.0`` or
        ``+inf``; the pair is unreachable by construction, so it is a bug rather
        than a fourth outcome to name. Callers on the terminal-writing path use
        :func:`render_preregistered_headline`, which records this instead of raising.
    """
    if not band_passes:
        # The verdict is decided at lambda = 1.0 and it did not clear. Whatever the
        # flip encodes (the -inf label, or a finite value at or below 1.0), the
        # sentence is the same one.
        return "iii"

    if isinstance(flip, str):
        if flip == _FLIP_NEVER:
            return "i"
        if flip == _FLIP_ALREADY_FAILED:
            raise ValueError(
                "inconsistent band verdict and flip: the band was cleared at "
                f"lambda = 1.0 but the flip says {_FLIP_ALREADY_FAILED}"
            )
        raise ValueError(f"unknown flip label {flip!r}")

    value = float(flip)
    if math.isnan(value):
        raise ValueError("inconsistent band verdict and flip: flip is NaN")
    if value == math.inf:
        return "i"
    if value == -math.inf or value <= 1.0:
        raise ValueError(
            "inconsistent band verdict and flip: the band was cleared at "
            f"lambda = 1.0 but the flip is {value!r} (<= 1.0)"
        )
    return "ii" if value <= float(ladder_max) else "i"


def render_preregistered_headline(
    *, band_passes: bool, flip: float | str, ladder_max: float, sealed_axis: str
) -> dict[str, object]:
    """Render the pre-registered D4 §8 sentence for a result. Never raises during assembly.

    A terminal with no valid verdict carries no pre-registered sentence (``INVALID`` /
    ``FUTILITY_STOPPED``) -- COMPLETE and INVALID share the same terminal body and the INVALID
    swap carries clauses through at their original values, so leaving the sentence in would
    attach a headline claim to a run declared "not trustworthy". Futility is likewise not a
    negative verdict (CLAUDE.md#seal).

    An inconsistent ``(band_passes, flip)`` pair is a bug, and
    :func:`preregistered_headline_branch` raises on it. Raising HERE would abort a legitimate
    terminal write, so the inconsistency is recorded as a marker; ``durable`` refuses that marker
    as a publishable artifact, which is where fail-closed belongs.

    Parameters
    ----------
    band_passes, flip, ladder_max
        As in :func:`preregistered_headline_branch`.
    sealed_axis : str
        The terminal's ``sealed_axis`` value (:class:`~alive.compose.verdict2.SealedAxis`).

    Returns
    -------
    dict
        ``{"applicable": False, "reason": <axis>}`` -- a two-key marker with no claim-text key
        at all, for the two axes that carry no sentence.
        ``{"applicable": False, "reason": <message>, "inconsistent": True, ...}`` -- every
        sentence key present and ``None``, for an inconsistent input.
        ``{"applicable": True, "reason": None, "band_branch": ..., "band_sentence": ...,
        "finite_flip_note": ..., "learned_family_sentence": ..., "inconsistent": False}``
        otherwise.
    """
    if sealed_axis in NO_HEADLINE_AXES:
        return {"applicable": False, "reason": sealed_axis}

    try:
        branch = preregistered_headline_branch(
            band_passes=band_passes, flip=flip, ladder_max=ladder_max
        )
    except ValueError as exc:  # 불일치는 기록하고 durable 이 fail-closed 로 잡는다
        return {
            "applicable": False,
            "reason": str(exc),
            "band_branch": None,
            "band_sentence": None,
            "finite_flip_note": None,
            "learned_family_sentence": None,
            "inconsistent": True,
        }

    finite_flip: float | None = None
    if not isinstance(flip, str):
        value = float(flip)
        if math.isfinite(value):
            finite_flip = value

    sentence = REGISTERED_HEADLINE_SENTENCES[branch]
    note: str | None = None
    if finite_flip is not None:
        # Canonical substitution: repr(float(flip)) -- one spelling per value, so the sentence a
        # reader sees and the sentence durable re-derives are the same bytes.
        canonical = repr(finite_flip)
        if branch == "ii":
            # (ii) is the only registered sentence carrying the placeholder, and reaching it
            # requires a finite flip -- the branch function refuses every other encoding.
            sentence = sentence.replace(FLIP_PLACEHOLDER, canonical)
        elif branch == "i":
            note = FINITE_FLIP_NOTE.replace(FLIP_PLACEHOLDER, canonical).replace(
                LADDER_MAX_PLACEHOLDER, repr(float(ladder_max))
            )

    return {
        "applicable": True,
        "reason": None,
        "band_branch": branch,
        "band_sentence": sentence,
        "finite_flip_note": note,
        "learned_family_sentence": (
            HEADLINE_SENTENCE_IV if sealed_axis == LEARNED_FAMILY_AXIS else None
        ),
        "inconsistent": False,
    }
