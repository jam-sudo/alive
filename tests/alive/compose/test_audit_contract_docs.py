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


_HISTORICAL_START = "[HISTORICAL"
_HISTORICAL_END = "<!-- /HISTORICAL -->"

# 결정 #7 이 뒤집은 두 진술. spec 은 as-built 이므로 지우지 않지만, HISTORICAL 로 격리된
# 블록 **밖**의 현행 본문에서는 한 번도 나오면 안 된다.
_WITHDRAWN = {
    "bank scale 을 묶는 config field 가 없다": _flat("그 scale은 어떤 config field도 묶지 않는다"),
    "bank 정규화는 split 의존을 만든다": _flat(
        "bank를 정규화하면 bank artifact가 split에 의존하게 되어"
    ),
}


def _partition_historical(current: str) -> tuple[list[str], str]:
    """Split the pre-appendix body into its HISTORICAL blocks and the live prose.

    A block starts at its ``[HISTORICAL …]`` marker and ends at the first
    ``<!-- /HISTORICAL -->`` sentinel after it — an explicit end marker, so the
    boundary does not depend on where a paragraph happens to wrap.
    """
    blocks: list[str] = []
    live: list[str] = []
    cursor = 0
    while True:
        start = current.find(_HISTORICAL_START, cursor)
        if start < 0:
            live.append(current[cursor:])
            return blocks, "".join(live)
        end = current.find(_HISTORICAL_END, start)
        assert end > start, f"{_HISTORICAL_START} 표시에 짝이 되는 {_HISTORICAL_END} 가 없다"
        end += len(_HISTORICAL_END)
        live.append(current[cursor:start])
        blocks.append(current[start:end])
        cursor = end


def test_the_current_normalization_contract_is_separate_from_its_history():
    text = _MAIN_SPEC.read_text(encoding="utf-8")
    current, history = text.split("## 부록 H — historical 문단 색인", 1)

    # 현행 계약이 현행 본문에 — HISTORICAL 표시 문구가 아니라 결정 #7 amendment 를 싣는
    # §3.1 본문에 — 있다. 표시 문구에도 같은 문자열이 있으므로 범위를 좁힌다.
    assert "sigma_max_z_unit" in current
    assert "sigma_max_z_unit" in _section(current, "3. 모델", "4. 평가")

    blocks, live = _partition_historical(current)
    assert len(blocks) == 2, f"HISTORICAL 블록이 2개가 아니다: {len(blocks)}"
    assert "결정 #7 이전의 검토" in blocks[0]
    assert "한계 (2026-08-07 독립 리뷰)" in blocks[1]

    # 폐기된 진술은 격리 블록 안에 as-built 로 남아 있고, appendix 이전 현행 본문의
    # 나머지 전체(§10.5 를 포함해)에는 어디에도 없다.
    flat_blocks = _flat("".join(blocks))
    flat_live = _flat(live)
    for name, claim in _WITHDRAWN.items():
        assert claim in flat_blocks, name
        assert claim not in flat_live, name

    assert "HISTORICAL" in history
