"""The pre-registered headline renderer (D4 §8) -- branch, sentence, and the two axes that get none.

``preregistered_headline_branch`` decided WHICH sentence a result selects, but nothing in the
tree ever emitted the sentence: the ``λ=<flip>`` substitution the decision document registers was
left to a human hand at report time, which is exactly the freedom D4 was written to close.
``render_preregistered_headline`` performs it.

Two properties are load-bearing and are measured here rather than argued:

1. **It never raises during terminal assembly.** An inconsistent ``(band_passes, flip)`` pair is
   unreachable by construction, so the branch function treats it as a bug and raises. A raise on
   the terminal-writing path would abort a legitimate write, so the renderer records the
   inconsistency as a marker; ``durable`` refuses that marker as a publishable artifact
   (Task 7b), which is where fail-closed belongs.
2. **A terminal with no valid verdict carries no claim sentence.** ``COMPLETE`` and ``INVALID``
   share the same terminal body, and the ``INVALID`` swap carries clauses through at their
   original values -- so without this branch a run declared "not trustworthy" would ship a
   pre-registered headline claim. ``FUTILITY_STOPPED`` is not a negative verdict either
   (CLAUDE.md#seal), so it gets no sentence for the same reason.

**Why the module is imported inside each test rather than at file scope.** The module's whole
reason to exist is that it imports nothing from the terminal stack. A file-scope
``from alive.compose.headline import ...`` would make the FALSE case of that claim unmeasurable:
introducing the forbidden ``phase2b`` import would abort COLLECTION with an ``ImportError``, and
an ImportError is not a kill in this repository -- the named test would never get to run its own
assertion. Deferring the import (the idiom ``test_band_sensitivity.py`` already uses) keeps every
claim here measurable by the test whose name makes it.
"""

from __future__ import annotations

import math
import pathlib
import subprocess
import sys

import pytest

#: The registered ladder maximum the caller passes in (committed config value, never hardcoded
#: in production source). 1.25 and the finite flip 2.5 are the two values D4's correction names.
LADDER_MAX = 1.25

_HEADLINE_SOURCE = pathlib.Path("src/alive/compose/headline.py")


def test_branch_i_sentinel_renders_the_registered_sentence():
    """``NEVER_FLIPS`` -> sentence (i) verbatim, with no extrapolation note attached."""
    from alive.compose.headline import REGISTERED_HEADLINE_SENTENCES, render_preregistered_headline

    result = render_preregistered_headline(
        band_passes=True, flip="NEVER_FLIPS", ladder_max=LADDER_MAX, sealed_axis="PARTIAL"
    )
    assert result["applicable"] is True
    assert result["reason"] is None
    assert result["band_branch"] == "i", f"sentinel flip 이 (i) 로 가지 않았다: {result!r}"
    assert result["band_sentence"] == REGISTERED_HEADLINE_SENTENCES["i"]
    assert result["finite_flip_note"] is None, "sentinel flip has no extrapolation point to report"
    assert result["learned_family_sentence"] is None
    assert result["inconsistent"] is False


def test_branch_i_finite_above_the_ladder_adds_the_extrapolation_note():
    """A finite flip beyond the ladder is still (i), but §8's correction requires λ=<flip> too.

    The correction (`…pair-dependence-decision.md` (i) bullet) says the extrapolation point is
    reported ALONGSIDE sentence (i) while the claim stays inside the registered ladder. Codex's
    measured input was exactly this: flip 2.5 with ladder_max 1.25.
    """
    from alive.compose.headline import (
        FLIP_PLACEHOLDER,
        REGISTERED_HEADLINE_SENTENCES,
        render_preregistered_headline,
    )

    result = render_preregistered_headline(
        band_passes=True, flip=2.5, ladder_max=LADDER_MAX, sealed_axis="GI_LEARNABLE_WIN"
    )
    assert result["band_branch"] == "i"
    assert result["band_sentence"] == REGISTERED_HEADLINE_SENTENCES["i"]
    note = result["finite_flip_note"]
    assert note is not None, "유한 flip 인데 외삽점을 병기하지 않았다"
    assert FLIP_PLACEHOLDER not in note, f"치환되지 않은 placeholder 가 남았다: {note!r}"
    assert "λ=2.5" in note, f"canonical repr(float(flip)) 이 아니다: {note!r}"
    assert "λ ≤ 1.25" in note, f"claim 을 등록 사다리로 한정하지 않는다: {note!r}"


def test_branch_ii_substitutes_the_canonical_flip_value():
    """(ii) is the ONLY sentence carrying ``λ=<flip>``; no placeholder may survive rendering."""
    from alive.compose.headline import (
        FLIP_PLACEHOLDER,
        REGISTERED_HEADLINE_SENTENCES,
        render_preregistered_headline,
    )

    for flip, canonical in ((1.25, "1.25"), (1.1, "1.1")):
        result = render_preregistered_headline(
            band_passes=True, flip=flip, ladder_max=LADDER_MAX, sealed_axis="PARTIAL"
        )
        assert result["band_branch"] == "ii"
        sentence = result["band_sentence"]
        assert FLIP_PLACEHOLDER not in sentence, f"placeholder 가 남았다: {sentence!r}"
        assert f"λ={canonical}" in sentence, f"canonical 치환이 아니다: {sentence!r}"
        assert sentence == REGISTERED_HEADLINE_SENTENCES["ii"].replace(
            FLIP_PLACEHOLDER, canonical
        ), "(ii) 는 서명된 문장의 placeholder 치환본이어야 한다"
        assert result["finite_flip_note"] is None, "(ii) 의 flip 은 문장 안에 이미 있다"


def test_branch_iii_renders_the_registered_band_failure_sentence():
    """A failing band is (iii) for EVERY flip encoding -- the sentence does not vary."""
    from alive.compose.headline import REGISTERED_HEADLINE_SENTENCES, render_preregistered_headline

    for flip in ("FAILS_AT_REGISTERED_BAND", 0.5, 1.0, 2.5, -math.inf):
        result = render_preregistered_headline(
            band_passes=False, flip=flip, ladder_max=LADDER_MAX, sealed_axis="NO_DISTINCT_WIN"
        )
        assert result["band_branch"] == "iii", f"flip={flip!r} 가 (iii) 가 아니다"
        assert result["band_sentence"] == REGISTERED_HEADLINE_SENTENCES["iii"], (
            f"flip={flip!r} 가 등록된 밴드-미통과 문장을 싣지 않았다"
        )
        assert result["finite_flip_note"] is None
        assert result["learned_family_sentence"] is None
        assert result["inconsistent"] is False


def test_the_learned_family_sentence_appears_only_for_gi_learnable_win():
    """(iv) ADDS to (i)/(ii); it neither replaces the band sentence nor appears off-axis."""
    from alive.compose.headline import REGISTERED_HEADLINE_SENTENCES, render_preregistered_headline

    on = render_preregistered_headline(
        band_passes=True, flip="NEVER_FLIPS", ladder_max=LADDER_MAX, sealed_axis="GI_LEARNABLE_WIN"
    )
    assert on["learned_family_sentence"] == REGISTERED_HEADLINE_SENTENCES["iv"], (
        "GI_LEARNABLE_WIN 인데 learned-family 문장이 실리지 않았다"
    )
    assert on["band_sentence"] == REGISTERED_HEADLINE_SENTENCES["i"], "(iv) 가 (i) 를 대체했다"

    for axis in ("PARTIAL", "NO_DISTINCT_WIN"):
        off = render_preregistered_headline(
            band_passes=True, flip="NEVER_FLIPS", ladder_max=LADDER_MAX, sealed_axis=axis
        )
        assert off["learned_family_sentence"] is None, (
            f"{axis} 는 learned-family 조건을 통과하지 않았는데 (iv) 가 실렸다"
        )
        assert off["band_sentence"] == REGISTERED_HEADLINE_SENTENCES["i"]


def test_an_invalid_axis_renders_no_preregistered_sentence():
    """``INVALID`` = integrity precondition failed. A run declared untrustworthy claims nothing."""
    from alive.compose.headline import REGISTERED_HEADLINE_SENTENCES, render_preregistered_headline

    result = render_preregistered_headline(
        band_passes=True, flip="NEVER_FLIPS", ladder_max=LADDER_MAX, sealed_axis="INVALID"
    )
    assert result == {"applicable": False, "reason": "INVALID"}, (
        "INVALID marker 는 claim text key 자체가 없는 최소 2-key schema 여야 한다"
    )
    blob = repr(result)
    for key, sentence in REGISTERED_HEADLINE_SENTENCES.items():
        assert sentence not in blob, f"INVALID terminal 에 사전등록 문장 ({key}) 이 실렸다"


def test_a_futility_stopped_axis_renders_no_preregistered_sentence():
    """Futility is not a negative verdict (CLAUDE.md#seal), so it is not a headline either."""
    from alive.compose.headline import REGISTERED_HEADLINE_SENTENCES, render_preregistered_headline

    result = render_preregistered_headline(
        band_passes=False,
        flip="FAILS_AT_REGISTERED_BAND",
        ladder_max=LADDER_MAX,
        sealed_axis="FUTILITY_STOPPED",
    )
    assert result == {"applicable": False, "reason": "FUTILITY_STOPPED"}, (
        "futility-stopped terminal 이 적용 불가 marker 대신 다른 것을 냈다"
    )
    blob = repr(result)
    for key, sentence in REGISTERED_HEADLINE_SENTENCES.items():
        assert sentence not in blob, f"futility-stopped terminal 에 사전등록 문장 ({key}) 이 실렸다"


@pytest.mark.parametrize("flip", [0.5, 1.0, -math.inf, "FAILS_AT_REGISTERED_BAND", "WAT"])
def test_an_inconsistent_band_and_flip_is_recorded_not_raised(flip):
    """The renderer records the bug; it does not abort the terminal write.

    The "not raised" half is CAPTURED, not left to propagate: an escaped exception fails the test
    with that exception's own type from the renderer's frame, and this repository does not accept
    anything but a named ``AssertionError`` as a kill. Catching it here and re-raising as an
    assertion is what makes the claim in this test's name measurable when it is false.

    Non-vacuity: the branch function itself DOES raise on the same input, so the marker is the
    renderer's own containment rather than an input that was never inconsistent.
    """
    from alive.compose.headline import preregistered_headline_branch, render_preregistered_headline

    with pytest.raises(ValueError):
        preregistered_headline_branch(band_passes=True, flip=flip, ladder_max=LADDER_MAX)

    try:
        result = render_preregistered_headline(
            band_passes=True, flip=flip, ladder_max=LADDER_MAX, sealed_axis="PARTIAL"
        )
    except Exception as exc:
        raise AssertionError(
            f"renderer 가 terminal 조립 중 예외를 냈다 (flip={flip!r}): {type(exc).__name__}: {exc}"
        ) from exc

    assert result["applicable"] is False
    assert result["inconsistent"] is True, f"불일치가 기록되지 않았다: {result!r}"
    assert isinstance(result["reason"], str) and result["reason"]
    assert result["band_branch"] is None
    assert result["band_sentence"] is None
    assert result["finite_flip_note"] is None
    assert result["learned_family_sentence"] is None


def test_the_renderer_module_is_a_leaf_of_the_terminal_stack():
    """The module exists to be importable FROM ``durable``; importing back would be circular.

    ``phase2b`` already imports ``durable`` at module scope, so a renderer living in ``phase2b``
    cannot be imported by ``durable`` -- measured as ``ImportError: ... partially initialized
    module 'alive.compose.phase2b'``. This pins the property that made a new module necessary.

    Both arms are written so that the FALSE case reaches this function. The source arm greps
    rather than imports; the behavioural arm runs the import in a SEPARATE interpreter and turns
    a non-zero exit into an assertion here, because a cycle inside this interpreter would
    otherwise surface as an ``ImportError`` at collection time -- which is not a kill. That is
    also why no test in this module imports ``alive.compose.headline`` at file scope.
    """
    source = _HEADLINE_SOURCE.read_text(encoding="utf-8")
    for forbidden in ("alive.compose.phase2b", "alive.compose.durable", "alive.compose.terminal"):
        assert f"import {forbidden}" not in source and f"from {forbidden}" not in source, (
            f"headline.py 가 {forbidden} 을 import 한다 — durable 이 이 모듈을 쓰면 순환이 된다"
        )

    # 실행 arm: 아무것도 먼저 import 하지 않은 인터프리터에서 headline 만 import 한다. leaf 면
    # 성공하고, phase2b 를 끌어들이면 phase2b 가 부분 초기화된 headline 을 다시 import 해 실패한다.
    probe = subprocess.run(
        [sys.executable, "-c", "import alive.compose.headline"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, (
        "headline 을 단독으로 import 하지 못한다 — leaf 가 아니다:\n"
        f"{probe.stderr.strip() or probe.stdout.strip()}"
    )
