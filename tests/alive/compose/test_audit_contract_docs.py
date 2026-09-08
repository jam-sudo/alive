"""Doc-contracts for the 2026-09-07 audit-debate remediation.

These pin STRUCTURE (a pending decision must carry NO-GO; a signed decision must carry its
sentence), never the owner's choice. A pending decision is a valid state, not a failing test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_DECISIONS = Path("docs/superpowers/2026-09-07-compose-audit-release-decisions.md")
_MAIN_SPEC = Path("docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md")
_READINESS = Path("docs/superpowers/COMPOSE-SEAL-READINESS.md")
_PHASE2_CONFIG = Path("configs/compose_k562_v1_phase2.yaml")


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


def test_a_signed_ladder_decision_carries_its_claim_sentence():
    d1 = _section(_DECISIONS.read_text(encoding="utf-8"), "D1", "D2")
    if "status: SIGNED" not in d1:
        assert "release: NO-GO" in d1
        return
    assert "순수 architecture 효과로 해석하지 않는다" in d1


def _spec_section_3_3(text: str) -> str:
    """Return §3.3's body — from its heading to the next ``##``/``###`` heading.

    The end is found by the next heading of either level rather than by naming
    ``### 3.4``, so a renumbering elsewhere in the spec cannot silently widen the
    window this test measures.
    """
    parts = text.split("### 3.3 Ablation ladder")
    assert len(parts) == 2, f"spec §3.3 제목이 정확히 하나가 아니다: {len(parts) - 1}"
    body = parts[1]
    ends = [i for i in (body.find("\n### "), body.find("\n## ")) if i >= 0]
    assert ends, "spec §3.3 뒤에 다음 제목이 없다"
    return body[: min(ends)]


def test_the_ladder_claim_ceiling_amendment_lives_inside_spec_section_3_3():
    """수정안 F 는 ladder 를 정의하는 절 안에 있어야 한다.

    claim 상한이 ladder 정의에서 떨어져 나가면(다른 절로 이동하거나 사라지면) ladder 를
    읽는 사람이 상한을 보지 못한다. 표식·강등 단어·닫는 문장을 §3.3 범위 안에서 요구한다.
    """
    section = _spec_section_3_3(_MAIN_SPEC.read_text(encoding="utf-8"))
    assert "수정안 F" in section
    assert "exploratory" in section
    assert "순수 architecture 효과로 해석하지 않는다" in section


def _registered_comparator_family() -> list[str]:
    """Members of the registered ``inference.comparator_family``, read from the config.

    Read as text rather than through the loader: the committed config still carries
    activation blockers, so loading it is a different (and failing) contract from
    reading the one registered list this doc-contract is about.
    """
    hits = re.findall(
        r"^\s*comparator_family:\s*\[([^\]]*)\]\s*$",
        _PHASE2_CONFIG.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    assert len(hits) == 1, f"comparator_family 줄이 정확히 하나가 아니다: {len(hits)}"
    return [m.strip() for m in hits[0].split(",") if m.strip()]


def test_the_ladder_amendment_describes_the_family_the_config_registers():
    """수정안 F 의 family 문장은 등록된 ``comparator_family`` 와 어긋나면 안 된다.

    수정안 F 초안은 "learned-family 조건에서 L2·L3 를 제외하지 않되"라고 적었는데, 등록된
    family 에 **L2 는 원래 없다**(ladder arm 일 뿐이다). claim 상한을 등록하면서 등록 사실을
    틀리게 서술하면 상한 자체를 신뢰할 수 없으므로, 문장이 config 와 어긋나면 실패시킨다.
    """
    members = _registered_comparator_family()
    section = _spec_section_3_3(_MAIN_SPEC.read_text(encoding="utf-8"))

    # config 가 말하는 것: L2 는 family 밖, L3 는 family 안.
    assert not [m for m in members if m.startswith("l2") or "saturation" in m]
    assert "l3_symmetric_mlp" in members

    # spec 이 그렇게 말하는가.
    assert "L2 는 원래 family 밖의 ablation arm 이고 L3 는 family 안에 있다" in section
    assert "L2·L3 를 제외하지 않되" not in section


def _prose(section: str) -> str:
    """The section text with its option-menu table rows dropped.

    A decision section carries BOTH a menu of options (markdown table rows, written before
    the owner chose) and the record of what was actually done. Measured on this file before
    the D2 disposition existed, every needle below was already present — in the ``D2-a``/
    ``D2-b`` menu rows. A check that reads the menu therefore returns the same answer whether
    or not the decision was implemented, so it grades nothing. Dropping table rows makes the
    assertion measure the implementation record.
    """
    return "\n".join(ln for ln in section.splitlines() if not ln.lstrip().startswith("|"))


def test_a_signed_esm_decision_names_its_governance_disposition():
    """D2 는 spec 문장만으로 닫히지 않는다 — governance 의무 처분까지 적어야 한다.

    CLAUDE.md 는 claim 과 무관하게 biological-prior encoder 의 ID-null ablation 을 요구한다. spec
    에서 claim 만 낮추고 그 의무를 처분하지 않으면 governance 충돌이 남는다. 그래서 ``status:
    SIGNED`` 인 D2 는 선택지 표가 아니라 **본문**에서 (1) 철회한 claim 문장과 (2) 그 처분이 사는
    위치를 둘 다 명명해야 한다.
    """
    d2 = _section(_DECISIONS.read_text(encoding="utf-8"), "D2", "D3")
    if "status: SIGNED" not in d2:
        assert "release: NO-GO" in d2
        return
    body = _prose(d2)
    assert "ESM의 marginal signal을 검증했다고 주장하지 않는다" in body or "ESM-off arm" in body
    assert "CLAUDE.md:132" in body


_PAIR_DEPENDENCE = Path("docs/superpowers/2026-08-29-compose-pair-dependence-decision.md")
_PHASE2B_SOURCE = Path("src/alive/compose/phase2b.py")
_HEADLINE_SECTION = "8. seal 전에 확정된 headline 문장"

#: §8 이 claim 으로 써서는 안 되는 네 토큰. 결정문 §8 의 금지 문장이 이들을 이름으로 부르므로
#: "§8 에 나오면 안 된다"는 검사는 자기 금지 문장 때문에 반드시 실패한다. 측정해야 하는 성질은
#: 등장 여부가 아니라 **주장으로 등장하는지**다.
_PROHIBITED_HEADLINE_TOKENS = ("mechanistic", "causal", "context transfer", "unconditional 95%")

#: §8 이 **스스로 등록하는** 명시적 비주장 절. 금지 토큰은 오직 이 문자열들 안에서만 등장할 수
#: 있다. 문장 분할 휴리스틱은 쓰지 않는다 — 뒤에 오는 부정이 앞의 토큰을 사면하기 때문이다:
#: 정정 전 검사에 `mechanistic 해석을 지지함.` 을 (ii) 앞에 독립 문장으로 끼워 넣으면 다음
#: 문장의 비주장 절 때문에 **통과했다**(실측). 절을 먼저 걷어내고 잔여를 보면 그 구멍이 없다.
_HEADLINE_NON_CLAIM_CLAUSES = (
    '"mechanistic" · "causal" · "context transfer" · "unconditional 95%" 를 '
    "**긍정 claim 으로** 쓰지 않는다(명시적 비주장 절에서만 등장한다)",
    "unconditional efficacy 또는 unconditional 95% coverage 를 주장하지 않는다",
)


def _headline_section() -> str:
    text = _PAIR_DEPENDENCE.read_text(encoding="utf-8")
    assert f"## {_HEADLINE_SECTION}" in text, (
        f"{_PAIR_DEPENDENCE} 에 '## {_HEADLINE_SECTION}' 절이 없다 — "
        "headline 문장이 seal 전에 확정되지 않았다"
    )
    return _section(text, _HEADLINE_SECTION, None)


def test_a_signed_pair_headline_is_preregistered_and_conditional():
    """D4 가 SIGNED 면 headline 문장은 **결정문 본문**에 사전 확정되어 있어야 한다.

    선택지 표(``D4-a``/``D4-b``)는 오너가 고르기 **전에** 쓰였으므로 표를 읽는 검사는 구현
    여부와 무관하게 같은 답을 낸다(Task 12 실측). 그래서 haystack 은 D4 절의 **산문**이다.
    """
    d4 = _section(_DECISIONS.read_text(encoding="utf-8"), "D4", "Amendment")
    if "status: SIGNED" not in d4:
        assert "release: NO-GO" in d4
        return
    body = _prose(d4)
    assert "unconditional efficacy" in body
    assert "seal 전에 확정된 headline 문장" in body
    text = _PAIR_DEPENDENCE.read_text(encoding="utf-8")
    assert "unconditional efficacy" in text and "seal 전에 확정된 headline 문장" in text


def test_the_preregistered_headline_uses_the_codes_own_flip_vocabulary():
    """§8 이 부르는 flip/사다리 토큰은 코드에 실재해야 한다 — 문장이 코드에서 떠내려가지 않도록."""
    section = _headline_section()
    source = _PHASE2B_SOURCE.read_text(encoding="utf-8")
    for token in ("NEVER_FLIPS", "FAILS_AT_REGISTERED_BAND", "sensitivity_band_inflation"):
        assert token in section, f"§8 이 `{token}` 를 부르지 않는다"
        assert token in source, f"`{token}` 가 {_PHASE2B_SOURCE} 에 없다 — 문장이 코드와 어긋난다"


def test_the_preregistered_headline_never_asserts_a_prohibited_claim():
    """금지 토큰은 §8 이 등록한 비주장 절 **안에서만** 나타난다.

    등록된 절들을 §8 에서 정확히 한 번씩 걷어낸 뒤, 잔여 텍스트 어디에도 네 토큰이 남아 있으면
    안 된다. 문장 경계를 추정하지 않으므로 "뒤에 부정이 오면 사면된다"는 구멍이 없다.
    """
    residue = " ".join(_headline_section().split())
    for clause in _HEADLINE_NON_CLAIM_CLAUSES:
        needle = " ".join(clause.split())
        assert residue.count(needle) == 1, (
            f"§8 이 등록한 비주장 절이 정확히 한 번 나와야 한다 — {needle!r}"
        )
        residue = residue.replace(needle, " ")
    for token in _PROHIBITED_HEADLINE_TOKENS:
        assert token not in residue, (
            f"`{token}` 가 등록된 비주장 절 **밖**에 나온다 — 긍정 claim 이다"
        )
