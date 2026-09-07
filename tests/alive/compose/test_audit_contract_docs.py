"""Doc-contracts for the 2026-09-07 audit-debate remediation.

These pin STRUCTURE (a pending decision must carry NO-GO; a signed decision must carry its
sentence), never the owner's choice. A pending decision is a valid state, not a failing test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_DECISIONS = Path("docs/superpowers/2026-09-07-compose-audit-release-decisions.md")
_MAIN_SPEC = Path("docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md")
_READINESS = Path("docs/superpowers/COMPOSE-SEAL-READINESS.md")


def _section(text: str, head: str, next_head: str | None) -> str:
    body = text.split(f"## {head}", 1)[1]
    return body.split(f"## {next_head}", 1)[0] if next_head else body


@pytest.mark.parametrize(
    "head,next_head", [("D1", "D2"), ("D2", "D3"), ("D3", "D4"), ("D4", "Amendment")]
)
def test_every_pending_decision_is_marked_no_go(head, next_head):
    sec = _section(_DECISIONS.read_text(encoding="utf-8"), head, next_head)
    assert "status:" in sec and "release:" in sec
    if "status: PENDING" in sec or "status: DEFER" in sec:
        assert "release: NO-GO" in sec


def test_the_spec_primary_formula_is_the_registered_config_string():
    text = _MAIN_SPEC.read_text(encoding="utf-8")
    assert "(mean(error_comparator) - mean(error_l1)) / max(mean(error_comparator), 1e-12)" in text
    assert r"1-\overline e_M/\max(\overline e_C,10^{-12})" not in text.replace(" ", "")


def _flat(text: str) -> str:
    """Drop every whitespace character and blockquote marker.

    Markdown hard-wraps sentences across ``> `` continuation lines, so a literal
    substring search is sensitive to where a line happens to break. Flattening both
    haystack and needle makes the assertion measure the sentence, not the layout.
    """
    return "".join(text.replace(">", " ").split())


_SUPERSEDED_BANK_SCALE_CLAIM = _flat("그 scale은 어떤 config field도 묶지 않는다")
_HISTORICAL_LIMIT = "[HISTORICAL — 결정 #7(2026-08-21 재서명본) 이후 무효.]"
_HISTORICAL_PENALTY_SIDE = "[HISTORICAL — 결정 #7 이전의 검토.]"


def test_the_current_normalization_contract_is_separate_from_its_history():
    text = _MAIN_SPEC.read_text(encoding="utf-8")
    current, history = text.split("## 부록 H — historical 문단 색인", 1)

    # 현행 계약이 현행 본문에 — HISTORICAL 표시 문구가 아니라 결정 #7 amendment 를 싣는
    # §3.1 본문에 — 있다. 표시 문구에도 같은 문자열이 있으므로 범위를 좁힌다.
    assert "sigma_max_z_unit" in current
    assert "sigma_max_z_unit" in _section(current, "3. 모델", "4. 평가")

    # spec 은 as-built 이므로 폐기된 문장을 지우지 않는다. 다만 HISTORICAL 표시보다
    # 앞에서는 한 번도 나오지 않아야 한다 — 표시를 지우면 이 단언이 깨진다.
    assert _SUPERSEDED_BANK_SCALE_CLAIM in _flat(current)
    assert _SUPERSEDED_BANK_SCALE_CLAIM not in _flat(current.split(_HISTORICAL_LIMIT, 1)[0])

    # 결정 #7 이전의 penalty-side 근거 문단도 바로 앞에 표시를 달고 있다.
    assert _HISTORICAL_PENALTY_SIDE in current
    assert 0 < current.index("bank를 정규화하면") - current.index(_HISTORICAL_PENALTY_SIDE) < 500

    assert "HISTORICAL" in history
