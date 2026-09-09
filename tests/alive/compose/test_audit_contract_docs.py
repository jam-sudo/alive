"""Doc-contracts for the 2026-09-07 audit-debate remediation.

These pin STRUCTURE (a pending decision must carry NO-GO; a signed decision must carry its
sentence), never the owner's choice. A pending decision is a valid state, not a failing test.

A signed decision whose implementing task has LANDED must additionally carry the record that
task left — otherwise the contract measures the template Task 0 shipped rather than the
implementation, which is how four of these assertions were found vacuous (D2/D3/D4 in Task 12,
D1 in the final review). Re-opening such a decision means moving ``status:`` back, not only
``release:``.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from alive.compose.config2 import load_compose_phase2_config
from alive.compose.phase2b import (
    _FLIP_ALREADY_FAILED,
    _FLIP_NEVER,
    preregistered_headline_branch,
)

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


def _flat(text: str) -> str:
    """Drop every whitespace character and blockquote marker.

    Markdown hard-wraps sentences across ``> `` continuation lines, so a literal
    substring search is sensitive to where a line happens to break. Flattening both
    haystack and needle makes the assertion measure the sentence, not the layout.
    """
    return "".join(text.replace(">", " ").split())


def test_the_spec_primary_formula_is_the_registered_config_string():
    r"""등록된 식은 본문에 있고 철회된 형태는 없다 — needle 을 haystack 과 같게 평탄화한다.

    정정 전에는 negative needle 만 공백을 품은 채 ``text.replace(" ", "")`` 를 뒤졌다. 그래서
    철회된 식이 **실제로 들어 있던** base ``2eef47a`` 에서도 ``needle in old.replace(" ","")``
    는 False 였다(실측) — 이 줄은 어떤 spec 에 대해서도 참이라 R5 를 잡은 적이 없고(그 RED 는
    positive assertion 이 냈다) 재발도 잡지 못한다. 부록 H 의 ``\max(\overline e_C,\epsilon)``
    형태는 이 needle 과 충돌하지 않는다(실측: 평탄화 후에도 불일치).
    """
    text = _flat(_MAIN_SPEC.read_text(encoding="utf-8"))
    registered = "(mean(error_comparator) - mean(error_l1)) / max(mean(error_comparator), 1e-12)"
    assert _flat(registered) in text
    assert _flat(r"1-\overline e_M/\max(\overline e_C,10^{-12})") not in text


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


_DOC_RULES = Path(".claude/rules/documentation.md")


def _missing_historical_sentinel_tokens(rule_text: str) -> list[str]:
    """Return the tokens a written documentation rule must carry, in order.

    Pure predicate: the assertion stays in the named test's own frame so a kill is
    attested there (변이 규칙 6). The two markers are the very constants
    ``_partition_historical`` computes the block extent with, so the written rule
    cannot drift away from the enforced contract.
    """
    required = (_HISTORICAL_START, _HISTORICAL_END, "never sentence heuristics")
    return [token for token in required if token not in rule_text]


def test_documentation_rule_requires_the_explicit_historical_closing_sentinel():
    """작성 규칙이 HISTORICAL 블록의 **종료 sentinel** 을 명시적으로 요구한다.

    이 계약은 ``_partition_historical`` 의 범위 계산에만 살아 있었고 작성 규칙에는
    없었다. sentinel 을 요구하지 않으면 배너만 단 문서가 규칙을 통과하고 격리 범위가
    문장 추정(sentence heuristics)으로 넓어진다.
    ``tests/test_claude_md_anchors.py`` 는 이 규칙 파일의 **존재**만 확인한다.
    """
    missing = _missing_historical_sentinel_tokens(_DOC_RULES.read_text(encoding="utf-8"))
    assert not missing, (
        f"{_DOC_RULES} 가 HISTORICAL 종료 sentinel 규칙의 토큰을 담지 않는다: {missing}"
    )


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
    """D1 이 SIGNED 면 **구현 기록**까지 담아야 한다 — claim 문장만으로는 아무것도 재지 않는다.

    claim 문장 "순수 architecture 효과로 해석하지 않는다" 는 Task 0 이 심은 "측정된 사실" 문단에
    이미 있었다: ``29d9e70`` 의 D1 절은 ``status: SIGNED`` 이면서 그 문장을 담고 있었다(실측).
    즉 이 검사는 Task 11 구현 여부와 무관하게 같은 답을 냈다 — D2·D3·D4 에서 이미 좁힌 것과 같은
    공허 계열이다. 그래서 구현이 남긴 두 흔적을 함께 요구한다: 상한을 싣는 amendment 이름
    (``수정안 F``)과 release 기록(``release: GO-LOCAL``). 둘 다 ``29d9e70`` 에 없었다(실측).
    D1 을 다시 여는 올바른 방법은 ``release:`` 를 되돌리는 것이 아니라 ``status:`` 를 되돌리는
    것이고, 그 상태는 위 parametrized 검사가 덮는다.
    """
    d1 = _section(_DECISIONS.read_text(encoding="utf-8"), "D1", "D2")
    if "status: SIGNED" not in d1:
        assert "release: NO-GO" in d1
        return
    assert "순수 architecture 효과로 해석하지 않는다" in d1
    assert "수정안 F" in d1
    assert "release: GO-LOCAL" in d1


def test_the_decisions_doc_names_the_current_config_digest():
    """결정문이 "현재값" 이라고 부르는 digest 는 loader 가 계산한 현재 digest 여야 한다.

    STATUS blockquote 는 Task 5 의 digest 이동(``0d207746…`` → ``a9dc9410…``) 뒤에도 옛 값을
    "현재" 로 부르고 있었고, 같은 문서의 ``## Task 5 digest 이동`` 절과 D2 의 "digest 불변" 이
    새 값을 적고 있었다 — 서명된 결정 기록이 run identity 를 두고 자기모순이었다. 기대값을
    hardcode 하지 않고 committed config 를 **읽어서** 만들므로, digest 가 다시 움직이면 이
    검사가 먼저 실패한다.
    """
    digest = load_compose_phase2_config(str(_PHASE2_CONFIG)).config_sha256
    flat = _flat(_DECISIONS.read_text(encoding="utf-8"))
    assert digest[:8] in flat, (
        f"결정문이 현재 `config_sha256` `{digest[:8]}…` 를 어디에서도 부르지 않는다"
    )
    assert _flat(f"현재값은 `{digest}`") in flat, (
        "결정문의 '현재값' 문장이 loader 가 계산한 digest 와 다르다 — "
        f"현재 config_sha256 은 `{digest}` 다"
    )


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

    Read as text rather than through the loader: this doc-contract is about the one
    registered list, not about activation. ``load_compose_phase2_config`` does load the
    committed config (it *reports* six activation blockers rather than raising); it is
    ``assert_scientific_mode_allowed`` that refuses while a blocker stands. Reading the
    YAML keeps the needle on the registered line itself.
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
    # 줄번호가 아니라 anchor 를 요구한다: ``CLAUDE.md:132`` 는 CLAUDE.md 가 한 줄만 자라도
    # 가리키는 곳이 달라지는 반면 ``#data-eval`` 은 의무 문장을 담은 절 자체를 가리킨다.
    # 좁히기 전과 같은 비-공허성을 유지한다 — ``29d9e70`` 의 D2 산문에는 둘 다 없었다(실측).
    assert "#data-eval" in body


def test_a_signed_source_threat_model_names_the_consumption_residual():
    """D3 가 SIGNED 면 위협 모델은 **결정문 본문**에 적혀 있어야 한다.

    ``seal.transient-inode-mutation-restoration`` 은 코드로 막지 않고 **승인 runtime 의 전제**로
    수용한 잔여다. 전제를 적지 않으면 "수용"은 근거 없는 면제가 된다. haystack 이 D3 절의
    **산문**인 이유는 D2·D4 와 같다: ``D3-a`` 선택지 행이 이미 "동시 writer"·"mount" 를 모두
    담고 있어(실측), 표를 읽는 검사는 구현 여부와 무관하게 같은 답을 낸다.
    """
    d3 = _section(_DECISIONS.read_text(encoding="utf-8"), "D3", "D4")
    if "status: SIGNED" not in d3:
        assert "release: NO-GO" in d3
        return
    body = _prose(d3)
    assert "검증 시점의 obs label 정합은 consumed X 불변 보증이 아니다" in body
    assert "동시 writer" in body and "mount" in body


_OUTCOME_STORE_SOURCE = Path("src/alive/compose/outcome_store.py")
_TERMINAL_SOURCE = Path("src/alive/compose/terminal.py")
_SEALED_SOURCE_E2E = Path("tests/alive/compose/driver/test_sealed_source_integrity_e2e.py")


def _between(source: str, start: str, end: str) -> str:
    """Return the slice between two literals, or ``""`` when the opening one is gone."""
    if start not in source:
        return ""
    tail = source.split(start, 1)[1]
    return tail.split(end, 1)[0] if end in tail else tail


def _opening_docstring(source: str, header: str) -> str:
    """Return the docstring that opens the block ``header`` introduces.

    Scope matters here. ``terminal.py`` already names ``ComposeSealingError`` once —
    in ``TerminalError``'s own docstring — so a whole-file search would be satisfied
    without ``_ProtectBoundary`` saying anything about the consumption boundary.
    """
    if header not in source:
        return ""
    parts = source.split(header, 1)[1].split('"""')
    return parts[1] if len(parts) >= 3 else ""


def _missing_consumption_role_tokens() -> list[str]:
    """Return ``site: token`` for every enforcement role not written AT ITS OWN site.

    Pure predicate — the assertion stays in the named test's frame (변이 규칙 6).
    """
    consumption = _between(
        _OUTCOME_STORE_SOURCE.read_text(encoding="utf-8"),
        "CONSUMPTION ENDS HERE",
        "return release",
    )
    protect = _opening_docstring(
        _TERMINAL_SOURCE.read_text(encoding="utf-8"), "class _ProtectBoundary:"
    )
    arm = _opening_docstring(
        _SEALED_SOURCE_E2E.read_text(encoding="utf-8"),
        "def test_an_io_error_in_the_materialization_recheck_still_aborts_after_seal(",
    )
    scoped = {
        "outcome_store consumption boundary": (
            consumption,
            ("TYPED CONTEXT", "_ProtectBoundary"),
        ),
        "terminal._ProtectBoundary docstring": (protect, ("DURABLE ABORT", "ComposeSealingError")),
        "sealed-source e2e arm docstring": (arm, ("_seal_consumed", "EXIT CODE")),
    }
    return [
        f"{site}: {token}"
        for site, (scope, tokens) in scoped.items()
        for token in tokens
        if token not in scope
    ]


def test_the_three_consumption_failure_enforcement_roles_are_documented():
    """소비 경계의 실패를 처리하는 **세 강제 지점**이 각자의 자리에 역할로 적혀 있다.

    exit code 30 을 결정하는 것은 store 의 래핑도 ``protect()`` 도 아니라
    ``phase2b_cmd._seal_consumed(audit_path)`` 다 — durable audit 의 존재만 본다.
    그래서 store 의 ``except Exception`` 을 무력화하는 **단일** 변이는 exit-code 단언을
    그대로 통과시킨다(실측). 기록이 없으면 그 SURVIVED 를 "테스트가 공허하다" 로 오독한다
    (변이 규칙 7: 중복 강제는 모든 site 가 죽어야 죽는다).

    각 역할은 그 역할을 수행하는 파일에 적혀야 의미가 있으므로 haystack 을 site 별로 좁힌다.
    """
    missing = _missing_consumption_role_tokens()
    assert not missing, f"소비 경계의 강제 역할이 자기 site 에 기록되지 않았다: {missing}"


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
#: (iv) 는 금지 토큰을 담지 않지만 여기 등록한다 — 등록의 두 번째 효과가 ``count == 1`` 이기
#: 때문이다: 사전등록 문장의 비주장 절이 사라지거나 두 번 복제되면 이 검사가 먼저 실패한다.
#: haystack 은 ``>`` 를 지우지 않으므로 등록 절은 blockquote **한 줄 안**에 있어야 한다 —
#: 줄을 걸치면 ``> `` 가 needle 을 끊어 count 가 0 이 된다(실측; (iv) 를 그래서 rewrap 했다).
_HEADLINE_NON_CLAIM_CLAUSES = (
    '"mechanistic" · "causal" · "context transfer" · "unconditional 95%" 를 '
    "**긍정 claim 으로** 쓰지 않는다(명시적 비주장 절에서만 등장한다)",
    "unconditional efficacy 또는 unconditional 95% coverage 를 주장하지 않는다",
    "이는 등록된 verdict 조건의 통과이지 architecture attribution 이 아니며(수정안 F), "
    "L1↔L2·L1↔L3 의 구조 기여는 exploratory 로만 보고한다. "
    "unconditional efficacy 를 주장하지 않는다",
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
    """§8 이 부르는 flip/사다리 토큰과 **분기 함수**가 코드에 실재해야 한다.

    토큰 존재만 확인하던 검사는 PR #15 finding I3 이 실측한 구멍을 못 봤다: 두 sentinel 은
    zero-width band 의 ``±inf`` 만 encoding 하는데 일반적인 ``q > 0`` 은 **유한** flip 을 내고,
    유한 2.5(사다리 밖)·0.5(밴드 미통과)는 §8 의 어느 조건에도 배정되지 않았다(**1 passed** 였다).
    그래서 이제 §8 이 **분기 함수 이름과 세 경계**를 부르고, 그 함수가 소스에 실재할 것을 요구한다 —
    분기를 문서가 아니라 코드가 소유한다는 것이 정정의 내용이기 때문이다.
    """
    section = _headline_section()
    source = _PHASE2B_SOURCE.read_text(encoding="utf-8")
    for token in ("NEVER_FLIPS", "FAILS_AT_REGISTERED_BAND", "sensitivity_band_inflation"):
        assert token in section, f"§8 이 `{token}` 를 부르지 않는다"
        assert token in source, f"`{token}` 가 {_PHASE2B_SOURCE} 에 없다 — 문장이 코드와 어긋난다"

    # 분기를 소유하는 함수: §8 이 이름으로 부르고, 그 이름이 소스에 정의되어 있어야 한다.
    assert "preregistered_headline_branch" in section, (
        "§8 이 결과군 분기를 소유하는 함수를 이름으로 부르지 않는다"
    )
    assert "def preregistered_headline_branch(" in source, (
        f"`preregistered_headline_branch` 가 {_PHASE2B_SOURCE} 에 정의돼 있지 않다"
    )
    # 세 경계 — 이것들이 없으면 (i)/(ii)/(iii) 의 적용 구간이 다시 미정이 된다.
    flat_section = " ".join(section.split())
    for boundary in ("1.0", "ladder_max", "1.25"):
        assert boundary in flat_section, f"§8 이 경계 `{boundary}` 를 적지 않는다"


#: §8 의 2026-09-08 정정 문단이 (i)/(ii)/(iii) 각각에 붙인 **적용 조건 절**, 공백 정규화 후.
#: 토큰 존재 검사는 이 절들을 **뒤집어도** 통과한다: PR #15 재검토 R2 가 실측했다 — (ii) 의
#: ``유한 `1.0 < flip ≤ ladder_max``` 를 ``유한 `1.0 > flip ≥ ladder_max``` 로 바꾼 §8 사본에서
#: 기존 검사는 **1 passed** 였다. 부등호는 분기의 전부이므로, 절을 통째로 고정한다.
_HEADLINE_BRANCH_CONDITIONS = {
    "i": "`band_passes=True` 이고 (`flip == NEVER_FLIPS` **또는** 유한 flip > `ladder_max`)",
    "ii": "`band_passes=True` 이고 유한 `1.0 < flip ≤ ladder_max`",
    "iii": "`band_passes=False` — 등록 밴드 미통과 **전체**",
}

_HEADLINE_CORRECTION_MARK = "**[2026-09-08 정정 — 결과군 완전성 (Codex PR 리뷰 I3)]**"


def _headline_branch_conditions() -> dict[str, str]:
    """§8 정정 문단의 (i)/(ii)/(iii) 적용 조건 절만 뽑아 공백 정규화한다.

    조건은 각 bullet 의 **첫 문장**이다(그 뒤는 그 분기에서 무엇을 쓰는지에 대한 설명이며
    분기 자체가 아니다). ``". "`` 로만 자르므로 ``1.0`` 의 소수점은 문장 경계로 오인되지
    않는다(뒤가 공백이 아니다 — 실측).
    """
    section = _headline_section()
    assert _HEADLINE_CORRECTION_MARK in section, (
        f"§8 에 결과군 완전성 정정 문단({_HEADLINE_CORRECTION_MARK})이 없다"
    )
    paragraph = section.split(_HEADLINE_CORRECTION_MARK, 1)[1]
    conditions: dict[str, str] = {}
    for match in re.finditer(
        r"^- \*\*\((i{1,3})\)\*\*(.*?)(?=^- |\n\n|\Z)", paragraph, re.M | re.S
    ):
        flat = " ".join(match.group(2).split())
        conditions[match.group(1)] = re.split(r"\.\s", flat, maxsplit=1)[0]
    return conditions


def test_the_headline_correction_states_the_same_partition_the_code_implements():
    """§8 정정 문단의 세 조건 절이 `preregistered_headline_branch` 의 분할과 **같아야** 한다.

    D4 가 닫으려는 자유는 "결과를 본 뒤 문구를 고르는 것"이다. 그 자유는 분기 함수가 아니라
    **문서의 조건 절**이 흐릿할 때 열린다 — 그래서 여기서는 토큰이 아니라 절 자체를 고정하고,
    같은 입력을 함수에도 먹여 문서가 서술하는 분할이 코드가 구현하는 분할과 일치함을 실행으로
    확인한다. 어느 한쪽만 바뀌면 이 검사가 먼저 실패한다.
    """
    assert _headline_branch_conditions() == _HEADLINE_BRANCH_CONDITIONS, (
        "§8 정정 문단의 (i)/(ii)/(iii) 적용 조건이 등록된 절과 다르다 — 부등호 하나만 뒤집혀도 "
        "분기가 바뀐다"
    )

    ladder_max = 1.25
    # (iii): 밴드 미통과 **전체** — flip 이 무엇이든 같은 문장.
    for flip in (_FLIP_ALREADY_FAILED, 0.5, 1.0, 2.5, -math.inf):
        assert (
            preregistered_headline_branch(band_passes=False, flip=flip, ladder_max=ladder_max)
            == "iii"
        ), f"밴드 미통과인데 flip={flip!r} 가 (iii) 가 아니다"
    # (i): NEVER_FLIPS, 또는 유한 flip > ladder_max.
    for flip in (_FLIP_NEVER, math.inf, 2.5, 1.2500001):
        assert (
            preregistered_headline_branch(band_passes=True, flip=flip, ladder_max=ladder_max) == "i"
        ), f"사다리 전 구간 유지인데 flip={flip!r} 가 (i) 가 아니다"
    # (ii): 유한 1.0 < flip ≤ ladder_max — 상한은 **포함**이다.
    for flip in (1.0000001, 1.1, ladder_max):
        assert (
            preregistered_headline_branch(band_passes=True, flip=flip, ladder_max=ladder_max)
            == "ii"
        ), f"등록 사다리 안에서 뒤집히는데 flip={flip!r} 가 (ii) 가 아니다"


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


def test_the_preregistered_headline_covers_the_learned_family_leg():
    """`GI_LEARNABLE_WIN` 의 learned-family 다리도 문장이 사전등록되어 있어야 한다.

    §8 의 (i)~(iii) 은 headline additive contrast 의 결과군만 덮었다. 그런데
    `GI_LEARNABLE_WIN` 은 learned comparator 조건을 하나 더 요구하고, 그 조건이 통과했을 때
    쓸 문장은 **수정안 F 가 강등한 바로 그 문장**("식별가능 구조가 비-bilinear 함수족을
    이긴다")이다. 문장이 없으면 결과를 본 뒤에 고르게 되는데, 그 자유를 없애려고 D4 가
    만들어졌다. 그래서 (iv) 의 존재와, spec §3.3 수정안 F 에서 그리로 가는 역참조를 함께
    요구한다 — 둘 중 하나만 있으면 ladder 를 읽는 사람이 상한을 못 본다.
    """
    section = _headline_section()
    assert "**(iv) `GI_LEARNABLE_WIN`" in section, "§8 이 learned-family 다리를 사전등록하지 않았다"
    assert "{GEARS, CPA, ID-only, L3}" in section
    assert "architecture attribution 이 아니며(수정안 F)" in section
    assert "네 문장" in section, "§8 머리말이 아직 세 문장만 사전등록한다고 말한다"

    amendment = _spec_section_3_3(_MAIN_SPEC.read_text(encoding="utf-8"))
    assert "pair-dependence decision §8 (iv)" in amendment, (
        "수정안 F 가 verdict 문장의 사전등록 위치를 가리키지 않는다"
    )


def test_readiness_names_every_release_gate_and_stays_an_index():
    """readiness 는 **모든** release gate 를 이름으로 부르는 인덱스여야 한다.

    감사가 잡은 실패 모드는 두 개가 한 몸이다. (1) `## Critical path to seal` 아래가
    시간순 서술 2,400여 줄로 자라 자기 maintainer note("index-only … 시간순 audit trail →
    git log")를 위반했고, (2) 그렇게 자란 서술이 release 경계를 **열거하지 않아서** —
    adapter 해석, source 소비, kernel 격리 재증명, 그리고 최종 owner gate 가 어디에도
    한 목록으로 서 있지 않았다. 길이 상한만 걸면 서술을 지우는 것으로 통과할 수 있고,
    토큰만 걸면 서술이 다시 자라도 통과한다. 둘을 한 검사에 둔다.
    """
    text = _READINESS.read_text(encoding="utf-8")
    for token in (
        "adapter_resolution",
        "source_consumption",
        "kernel_isolation_reproof",
        "owner_release",
        "D1",
        "D2",
        "D3",
        "D4",
    ):
        assert f"`{token}`" in text, (
            f"readiness 가 release gate `{token}` 를 이름으로 부르지 않는다"
        )
    lines = len(text.splitlines())
    assert lines <= 250, (
        f"readiness 가 {lines} 줄이다 — 자기 maintainer note 가 선언한 index-only 형태가 아니다; "
        "시간순 서술은 journal 아카이브와 git log 가 authoritative 다"
    )
