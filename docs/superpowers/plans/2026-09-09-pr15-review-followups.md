# PR #15 리뷰 잔여 후속 — Implementation Plan (수렴본)

> **For agentic workers:** 이 플랜은 task 단위로 실행한다. Step 은 checkbox (`- [ ]`) 문법을 쓴다.
> 각 task 는 **실패 테스트 → red 실측 → 구현 → green 실측 → 커밋** 순서를 지키고, 새 테스트마다
> "참일 때와 거짓일 때 출력이 다른지" 를 실제로 실행해 보고서에 남긴다. kill 은 **이름 붙은 테스트의
> `AssertionError`** 로만 인정한다.

**작성:** 2026-09-09 · **기준 트리:** HEAD `595697b` (= `main` 병합 커밋 `8c3437d` 의 트리)
**상태:** **승인됨 (오너, 2026-09-09)** — GATE-1 = **a**, GATE-2 = **a**, D4 범위 정정 확인. 브랜치 `compose-pr15-followups` 에서 실행한다.

---

<!-- R4-b: 협력 workflow 서술을 §0 밖에서 제거하고 목표를 병합 후 잔여 항목 자체로 한정했다. -->
**Goal:** PR #15 병합 뒤 "follow-up / deferred / observation" 으로 남은 15 개 항목을,
저장소가 실제로 무엇을 잃는지를 기준으로 닫는다. `config_sha256` `a9dc9410…` 를 움직이지 않고, seal 을 열지 않고,
어떤 guard 도 약화하지 않는다. 로컬 구현 완료와 scientific release 완료를 분리한다 — 이 플랜이 전부 green 이어도
COMPOSE-K562-v1 은 **ACTIVE / RELEASE-BLOCKED / seal UNOPENED** 그대로다.

**Architecture:** 변경은 다섯 층에만 닿는다.
1. **pre-seal 증거 경계** — producer 의 admission 신호(`scripts/compose/measure_pseudobulk_approximation_bias.py`)와
   finalizer 의 evidence 결속(`scripts/compose/finalize_approximation_bias_config.py`). 둘 다 과학 라이브러리 **밖**의
   스크립트이며, byte-pinned `src/alive/compose/approximation_bias.py` 는 **호출만** 한다.
2. **개발 계측기** — 변이 harness 의 kill 인증(`scripts/compose_audit_mutation_harness.py`)과 lint 규칙(`pyproject.toml`).
3. **production 불변식** — `src/alive/compose/models.py` 의 두 내부 assert 를 `-O` 에서도 사는 검사로 승격.
4. **사전등록 문장의 결속** — 분기·문장 renderer 를 **leaf 모듈** `src/alive/compose/headline.py` 로 두고
   (`durable` ↔ `phase2b` 순환 회피), 결과를 기존 `band_sensitivity` 블록 **안에 중첩**해 checksum 에 묶고,
   durable finalizer 가 그 의미를 재계산한다.
5. **governance 문서** — `CLAUDE.md` 정합, `.claude/rules/documentation.md` 의 sentinel 규칙, 현행 v4 naming.

**Tech Stack:** Python 3.12 · `uv` (모든 명령 `uv run --locked`) · pytest · Ruff. `uv.lock` 과 `.python-version` 은
불변이다(lint 규칙 추가는 lock 을 움직이지 않는다).

<!-- R4-b: documentation_hygiene가 실제로 검사할 수 있도록 authoritative 문서 경로를 상대 Markdown 링크로 만들었다. -->
**Spec:**
- 원 리뷰·판정: PR #15 본문 "Follow-ups after merge" 절과 그 아래 리뷰 보고서들(저장소 밖 `artifacts/`).
- 결정문: [audit release decisions](../2026-09-07-compose-audit-release-decisions.md) (D1~D4, 수정안 D·E·F·G),
  [pair-dependence decision](../2026-08-29-compose-pair-dependence-decision.md) §8 (`:141-190`).
- spec: [COMPOSE design](../specs/2026-06-22-compose-epistasis-operator-design.md) (`:717-718` 두 필드 등록,
  부록 H `:771-778` sentinel 서술), [durable-ledger design](../specs/2026-07-05-compose-durable-ledger-design.md#21-completeinvalid) (`:107`
  descriptive-only 블록), [approximation-bias design](../specs/2026-07-13-compose-approximation-bias-metric-design.md).
- readiness: [COMPOSE-SEAL-READINESS](../COMPOSE-SEAL-READINESS.md) (`:11-15` stamp 정책, `:55` digest, `:67` `source_consumption`).
- governance: [CLAUDE.md](../../../CLAUDE.md#sources) (`#sources`, `#invariants`, `#seal`, `#provenance`, `#data-eval`, `#repo`, `#verify`, `#agent`).

---

## Global Constraints

이 플랜의 **모든 task 에 적용되는 구현 제약**이다. 위반은 task 실패다.

1. **`configs/` 변경 = 새 run identity**(`config_sha256` `a9dc9410…`). 오너 결정 없이 어떤 task 도 config 를 바꾸지 않는다.
2. **byte-pinned — 한 바이트도 바꾸지 않는다:** `src/alive/io.py`, `src/alive/__init__.py`,
   `src/alive/compose/__init__.py`, `uv.lock`, `.python-version`, 그리고 **`src/alive/compose/approximation_bias.py`**
   (`_PENDING_REPROOF` digest `af0dab18086bcdf5adc3d19815ac6fa4a7695efa9f6dd1f6d58138c83f6c31c2`,
   pod 의 Linux 재증명 전까지 — `tests/alive/compose/test_kernel_isolation_ci.py:625-632`).
   이 파일이 필요한 해결책은 **스크립트/호출 쪽으로 우회**한다.
3. **seal UNOPENED · RELEASE-BLOCKED 유지.** 어떤 guard 도 약화하지 않는다 —
   `outcome_store.py`, `phase2b_cmd.py`, `terminal.py`, `durable.py`, `seal_boundary.py`, `preflight.py`,
   `confirmation.py`, `pair_index.py`, `freeze.py`, `gates.py` 는 **추가만** 한다.
4. **`CLAUDE.md` 는 스크립트로만 편집**(에디터 직접 patch 금지), **≤ 200 줄**
   (`tests/test_claude_md_anchors.py:118` 이 `< 200` 을 강제; 현재 198).
5. **문서에서 `CLAUDE.md §N` 형식 참조 금지 → `#anchor` 만.**
   `tests/test_claude_md_anchors.py` 는 `git ls-files --cached --others` 로 훑으므로 **untracked 파일도 대상**이다.
6. **협력 도구·workflow 서술을 새로 쓰지 않는다.** 이 플랜을 포함해 새로 만드는 문서에는 현재형 협력 지시를 넣지 않는다.
   기존 문서의 provenance 서술은 GATE-1 승인 전까지 **한 글자도 건드리지 않는다**.
7. **서명된 결정문 문장은 재작성하지 않는다** — **날짜 붙은 정정 문단**만 추가한다.
8. **새 테스트마다 참/거짓 실측**을 step 으로 넣는다. kill 은 **이름 붙은 테스트의 `AssertionError`** 로만 인정한다
   (exit code·ImportError 는 kill 이 아니다).
9. **`_ISOLATION_CLOSURE`**(`tests/alive/compose/test_kernel_isolation_ci.py:575-607`)에 든 파일은
   `_PENDING_REPROOF` 항목이 아닌 한 바꿀 수 없다 — 여기에 `src/alive/io.py`, `src/alive/compose/roles.py`,
   `scripts/compose/run_network_isolated.py`, `scripts/compose/gears_decision_probe.py` 등이 포함된다.
   **실측:** 이 플랜이 손대는 `src/alive/compose/models.py`, `phase2b.py`, `durable.py`, `terminal.py`,
   `scripts/compose/{measure_pseudobulk_approximation_bias,finalize_approximation_bias_config}.py` 는 모두 closure **밖**이다.
<!-- R4-b: git/rg/shasum까지 uv로 실행하라는 모순을 없애고 Python 도구 실행에 locked 환경을 강제했다. -->
10. Python·pytest·Ruff 실행은 모두 **`uv run --locked`** 를 사용한다. `git`·`rg`·`wc`·`shasum` 은 직접 실행한다.
    커밋은 논리 단위별로 하고, 메시지 끝에 반드시 두 줄:
    ```
    Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
    Claude-Session: https://claude.ai/code/session_01Gh4k8KQJtMwgTV1YAZhYS2
    ```

---

## §0 판정 기록

15 개 항목 전부에 대해 두 독립 플랜(A안·B안)이 같은 disposition 에 도달했다. 잔여 쟁점 둘은 코디네이터 판정으로 닫혔다.

| id | 무엇 | 판정 | 채택된 안 | 한 줄 근거 | 출처 |
|---:|---|---|---|---|---|
| 1 | producer 가 `NOT_ADMISSIBLE` report 를 쓰고도 exit 0 | **FIX-NOW** (T3) | **A안** — opt-in `--require-admitted`, 기본 exit 0 유지 | 기본값을 뒤집으면 committed 테스트 2 개가 red 가 된다(`tests/alive/compose/test_approximation_bias_metric.py:1155-1157`, `tests/alive/compose/test_finalize_approximation_bias_config.py:462-464`) — 그 둘이 "측정은 성공했고 거부 사유는 디스크에" 라는 판정을 핀한다 | R2 양쪽 합의 |
| 2 | finalizer 가 Probe-A evidence 를 다시 열지 않는다 | **FIX-NOW** (T4) | **B안** — 세 경로 **필수** | optional 인자는 생략으로 우회되는 guard 다. 비용 실측: 호출부는 테스트 2 파일 10 곳뿐이고 Probe-A fixture 빌더는 이미 재사용 중(`tests/alive/compose/test_finalize_approximation_bias_config.py:450-461`), committed runbook 호출 기록 없음 | A안이 R2 에서 양보 |
| 3 | `ruff` S101 미적용 + production bare assert 2 건 | **FIX-NOW** (T2) | **A안 대상 + B안 문안·`-O` arm** | `--select S101 src` 가 정확히 `src/alive/compose/models.py:360,397` 2 건만 낸다(실측). 같은 클래스에 이미 `RuntimeError` 관례가 있다(`:434`) | 양쪽 합의 |
| 4 | 변이 harness 가 실패 frame 의 파일을 인증하지 않는다 | **FIX-NOW** (T1) | **A안** — "저장소 소유(비-`.venv`) frame 중 마지막 == nodeid 의 테스트 모듈" | 소박한 "마지막 frame" 규칙은 기존 kill 17 건 중 8 건을 깨뜨린다(실측: `pytest.fail`/`pytest.raises` 는 `_pytest/outcomes.py`·`_pytest/raises.py` 에서 끝난다). 새 술어는 17/17 통과 | A안 실측, B안 CONCEDE |
| 5 | `CLAUDE.md` 개정일·`§5 registry`·채팅 인용 | **FIX-NOW** (T5) | **제3안** — line-neutral 치환 + 속성 기반 검증 | 양쪽 초안 모두 자기모순이었다(A안: 2줄→1줄로 198→197 이면서 같은 범위의 byte equality 요구 — 실측; B안: 존재하지 않는 `<!-- Last revised: … -->` 문자열에 assert — `grep -c` = 0). item 14 를 여기에 흡수 | R3 양쪽 합의 |
| 6 | `<!-- /HISTORICAL -->` 종료 sentinel 규칙 부재 | **FIX-NOW** (T6) | **양쪽 동일 문안 + B안 spec 근거** | 규칙 파일 25 줄에 없고 계약은 테스트에만 산다(`tests/alive/compose/test_audit_contract_docs.py:98-104`); spec 부록 H(`…2026-06-22…:771-778`)가 sentinel 을 서술한다 | 양쪽 합의 |
| 7 | D4 §8 의 `λ=<flip>` 치환 계약에 emission 이 없다 | **FIX-NOW** (T7a → T7b) | **B안 중첩·durable 재검증 + A안 leaf/INVALID/no-raise 안전장치** | 오늘 durable 은 checksum 결속만 본다(`src/alive/compose/durable.py:854-860`) → 자기일관적 위조가 통과한다. 문장을 artifact 밖에 두면 아무것에도 결속되지 않고, 검증된 입력을 줄 read-only API 도 없다(`durable.py:670`·`:1379` 둘 다 publish) | 코디네이터 판정 1 |
| 8 | 소비 **후** sealed-source 변경에 durable witness 없음 | **DROP** | **B안** | `alive.io.atomic_write_once`(`src/alive/io.py:16-39`)는 `except` 절이 하나도 없어 진단 branch 의 "절대 raise 금지" 를 깬다. D3-a 가 stderr-only 를 이미 서명했다(`…release-decisions.md:129-150`) | R2/R3 양쪽 합의 |
| 9 | `outcome_store.py:252-277` 이 죽은 stub 이라는 관찰 | **DROP** | 양쪽 동일 | 오독이다 — `:252` 는 `class OutcomeStore(Protocol)` 안, `:539` 는 `class ComposeOutcomeStore`(`:334`) 안. 지우면 실패가 아니라 `@runtime_checkable` 요구 표면이 **조용히 줄어든다**(`tests/alive/compose/test_outcome_store.py:193`) | 양쪽 합의 |
| 10 | 정상 경로에서 재해시 2 회(~0.4 s) | **DROP** | 양쪽 동일 | 두 지점이 **서로 다른 시간 경계**를 본다(소비 경계 `outcome_store.py:702-717` vs 소비 후 진단 `driver/phase2b_cmd.py:661-683`). 하나를 지우면 사후 drift 의 유일한 신호를 잃는다 | 양쪽 합의 |
| 11 | readiness `Updated:` stamp | **DROP** | 양쪽 동일 | 정책이 이미 문서에 있다 — stamp 는 부모 커밋을 부르고 상태가 바뀔 때만 갱신한다(`docs/superpowers/COMPOSE-SEAL-READINESS.md:11-15`). 조건부 마무리 체크리스트로만 남긴다(검증 사다리 8) | 양쪽 합의 |
| 12 | 기존 문서의 협력 서술 소급 범위 | **DECISION-GATE (GATE-1)** | 양쪽 게이트 | 오너 규칙의 소급 범위는 트리가 답할 수 없다. 대상은 전부 병합 전 `main`(`85e9749`)에 선재하고, 그중 하나는 evidence 값이자 테스트가 verbatim 으로 핀한다 | 양쪽 합의 |
| 13 | `protect()` 의 중복 강제가 기록되지 않았다 | **FIX-NOW** (T8) | **A안(축소)** — 코드 변경 0, 주석만 | exit 30 을 결정하는 것은 두 site 중 어느 쪽도 아니고 `_seal_consumed(audit_path)`(`driver/phase2b_cmd.py:424-426`)다. 역방향 참조는 트리에 없다(`terminal.py:1341-1370` 에 `outcome_store` 언급 0) | 코디네이터 판정 2 |
| 14 | doc-contract 의 literal 줄번호 grep | **DROP (T5 에 흡수)** | 양쪽 동일 | live test 는 이미 `#data-eval` 앵커를 요구한다(`tests/alive/compose/test_audit_contract_docs.py:266-269`); 결정문은 줄번호가 dated snapshot 이고 anchor 가 정본이라고 스스로 적는다(`…release-decisions.md:70-72`) | 양쪽 합의 |
| 15 | `measure_approximation_bias_v3` vs schema v4 | **FIX-NOW** (T9) | **B안 방향 + A안 전수 목록** | 현행 표면 두 곳이 아직 v3 라고 말한다: live docstring `src/alive/compose/driver/bias_report_preseal.py:124` 와 현행 entrypoint 로 등록된 runbook `docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md:14`(`tests/test_documentation_hygiene.py:18`) | B안, A안이 R2 에서 양보 |

**집계: FIX-NOW 9 · DECISION-GATE 1 · POD-GATED 0 · DROP 5.**
POD-GATED 가 0 인 이유: 이 목록은 전부 macOS 로컬에서 재현·검증 가능하다. pod 로 미뤄진 것들(커널 재증명,
실 `.pyz` adapter parity, D3 runtime 증거, R1 representation 결정, D1-c real-bank λ*)은 별도 목록이며 이 플랜의 대상이 아니다.

**오너 확인 요청(플랜 서명 시, 게이트 아님).** T7a/T7b 는 "`sealed_axis ∈ {INVALID, FUTILITY_STOPPED}` 인 terminal 에는
사전등록 headline 문장을 싣지 않는다" 를 도입한다. 이는 D4 가 명시하지 않은 규정이므로 pair-dependence 결정문 §8 에
**날짜 붙은 정정 문단**으로 넣는다. 유효한 verdict 가 없는 terminal 에 대한 규정이므로 **어떤 claim 도 바뀌지 않는다.**

> **오너 확인 (2026-09-09): 승인.** INVALID·FUTILITY_STOPPED terminal 에는 사전등록 headline 문장을 싣지 않는다 — T7a 가 pair-dependence 결정문 §8 에 날짜 붙은 정정 문단으로 넣는다.

---

## 결정 게이트

### GATE-1 — 기존 문서의 협력 서술: 소급 범위와 editable roster (item 12)

**질문.** "협력 도구·workflow 서술은 git 에 올리지 않는다" 가 **병합 전부터 있던** 문서의 표현까지 소급하는가.

**실측된 대상**(전부 `85e9749` 에 선재; `git show 85e9749:<path>` 로 확인):

| 위치 | 성격 |
|---|---|
| `docs/activation-evidence/compose/kernel_isolation_ci_2dd23d627fc0e31a7d5005a3e81ff20b8dcd9472.json:3` `archived_by` | **immutable evidence 값**. `tests/alive/compose/test_kernel_isolation_ci.py:499-504` 가 verbatim 핀하고, 그 docstring(`:490-498`)이 "이 문자열이 v1 의 독립 리뷰와 v2 의 자기 리뷰를 구분하는 유일한 필드" 라고 적는다 |
| `docs/activation-evidence/compose/README.md:127` | 위 값을 설명하는 provenance 산문 |
| `docs/superpowers/journal/2026-09-07-compose-readiness-narrative-archive.md:182`, `:1589` | verbatim 아카이브(원본은 `85e9749:docs/superpowers/COMPOSE-SEAL-READINESS.md:210,1617`) |
| `docs/superpowers/audits/2026-07-11-compose-gu-exact-sha-independent-review.md:26` | 당시 리뷰 방법의 기록 |
| `docs/superpowers/runbooks/2026-08-12-compose-kernel-archive-independent-archiver.md:61` | 아카이브 생성 방법의 기록 |
| `docs/superpowers/plans/*.md` 헤더 **13 개** | 실행 지시(현재형) |

**선택지**

| | 선택 | 결과 |
|---|---|---|
| **a (권장)** | 기존 provenance/audit/runbook/plan 문구를 **전부 보존**하고, **새로 쓰는 문서에만** 현재형 협력 지시를 금지한다(이 플랜이 그 규칙을 이미 따른다) | 노력 0(문서 변경 0). evidence 불변식과 "과장 금지" 를 모두 지킨다. 잃는 것: 규칙의 소급 해석이 문서로 남지 않는다 → 이 플랜의 이 절이 그 기록이 된다 |
| b | 오너가 **exact editable roster** 를 준다 | 노력 M. roster 밖은 불변, 안쪽만 날짜 붙은 정정으로 고친다 |
| c | 전면 소급 | **비권장.** `archived_by` 를 고치면 v2 아카이브가 **없는 독립성을 주장**하게 되고 `#data-eval` 의 "immutable evidence 를 조용히 갱신하지 않는다" 와 정면 충돌한다. 아카이브 본문 수정은 "verbatim" 주장을 깎는다 |

**권장: a.** 규칙의 목적은 작업 배분 서술을 새로 남기지 않는 것이고, `archived_by` 는 작업 배분이 아니라
**리뷰 등급의 정직한 라벨**이다. **승인 전까지 item 12 관련 파일 변경은 0 이다**(T10 은 GATE-1 승인 후에만 시작).

> **오너 결정 (2026-09-09): a.** 기존 provenance/audit/runbook/plan 문구는 전부 보존한다. 이 절이 규칙의 소급 해석 기록이다. item 12 의 파일 변경은 0 으로 확정.

### GATE-2 — 실행 경로

**질문.** 이 wave 를 어디에 올리고, 이 플랜 파일을 커밋하는가.

| | 선택 | 결과 |
|---|---|---|
| **a (권장)** | 이 플랜 파일을 커밋 + 새 브랜치 `compose-pr15-followups` → PR → 독립 리뷰 → 병합 | main 이 항상 리뷰된 상태를 유지한다 |
| b | `main` 직접 커밋 | **비권장.** PR #15 에서 **두 번째** 리뷰가 Critical 을 찾았다는 실측이 있다 |
| c | 플랜 untracked 유지 + 오너가 고른 task 만 실행 | 유연하지만 판정 기록이 저장소 밖에 남는다 |

**권장: a.** 커밋한다면 `tests/test_documentation_hygiene.py:55` 의 링크 검사가 `git ls-files --cached --others` 로
**untracked 까지** 훑으므로 이 파일의 상대 링크가 전부 resolve 해야 한다(검증 사다리 7).

> **오너 결정 (2026-09-09): a.** 이 플랜 파일을 커밋하고 `compose-pr15-followups` 브랜치에서 구현 → PR → 독립 리뷰 → 병합.
**R4 단계에서 이 파일은 untracked 로 둔다 — 커밋 자체가 GATE-2 의 결과다.**

---

## Task 1 — 변이 harness 가 실패 frame 의 파일까지 인증한다 (item 4)

> **가장 먼저 실행한다.** T2 가 `models.py` 의 bare assert 를 없애면 이 task 의 red 증거를 더는 재현할 수 없다.

**Files**
- Modify: `scripts/compose_audit_mutation_harness.py` — `_CHILD_PROGRAM` recorder(`:121-155`), `CaseRun`(`:180-205`),
  `_call_phase`(`:462-474`), `run_plan`(`:476-532`), `classify`(`:594-613`), `_report`(`:660-675`)
- Test: `tests/alive/compose/test_audit_mutation_harness.py` (326 줄; rule-8 절이 `:210-278`)

**Interfaces**
- Consumes: `pytest` `CallInfo.excinfo.traceback`, `REPO`(`scripts/compose_audit_mutation_harness.py:103`),
  nodeid 의 `<file>::<test>` 분해, `ASSERTION_KINDS`(`:116`)
- Produces: `CaseRun.call_frame: str | None`(저장소 상대 POSIX 경로) + `classify` 의 새 거부 사유
  `HARNESS_FAILURE (frame outside the test module: <path>)`

**Steps**
- [ ] **1. red 증거 먼저 확보(T2 이전에만 가능).** `models.py:397` 의 `assert self.weights_ is not None` 을
      in-memory 로 뒤집는 변이를 `tests/alive/compose/test_models.py::test_l3_deterministic_init_and_training` 에 걸어
      현재 `classify` 가 **`KILLED`** 를 주고 마지막 저장소 프레임이 `src/alive/compose/models.py` 임을 실행해 기록한다.
      (이 측정은 보고서에만 남기고 committed test 로 만들지 않는다 — T2 뒤에는 재현되지 않기 때문이다.)
<!-- R4-b: 사용하지 않는 tmp 모듈+수동 CaseRun이라는 공허한 negative를 실제 traceback 선택까지 타는 합성 모듈 검사로 바꿨다. -->
- [ ] **2. 실패 테스트.** `test_audit_mutation_harness.py` 에 이름이 주장을 하는 두 테스트를 추가한다.
      **production frame 은 합성 모듈로 만든다**(T2 뒤에도 유효해야 하므로 `models.py` 에 의존하지 않는다):
      ```
      test_a_kill_requires_the_failing_frame_to_be_the_tests_own_module
      test_an_assertion_raised_in_a_synthetic_production_module_is_not_a_kill
      ```
      후자는 `tmp_path` 아래 `src/synthetic_production.py` 의 bare assert 를 실제로 호출해 잡은 traceback을
      `_repo_frame` 에 넣는다(`REPO` 는 `tmp_path` 로 monkeypatch). 선택된 frame으로 `CaseRun` 을 구성하고
      `classify` 를 호출해 **test module frame은 KILLED, synthetic production frame은 HARNESS_FAILURE**임을 함께 단언한다.
- [ ] **3. red 확인.** `_repo_frame`/새 필드가 없으므로 첫 실행은 `AttributeError` 또는 현행 `KILLED` 로 red 임을 기록한다.
- [ ] **4. 구현 — recorder 에 프레임 목록을 더한다.**
      ```python
      self.records.append({
          "nodeid": item.nodeid,
          "when": call.when,
          "type": call.excinfo.type.__name__,
          "repr": repr(call.excinfo.value)[:400],
          # 규칙 8 확장: kind 만으로는 production 의 bare assert 와 테스트 자신의 단언을
          # 구별할 수 없다. 프레임 출처까지 인증한다.
          "frames": [str(entry.path) for entry in call.excinfo.traceback],
      })
      ```
- [ ] **5. 구현 — 마지막 저장소 소유 프레임.**
      ```python
      def _repo_frame(frames: list[str]) -> str | None:
          """마지막 저장소 소유 프레임(상대경로). pytest 내부 프레임은 제외한다.

          `pytest.fail` 과 미충족 `pytest.raises` 는 traceback 의 마지막을
          `_pytest/outcomes.py` / `_pytest/raises.py` 로 남긴다 — 등록된 17 개 in-memory
          case 중 8 개가 그렇다(실측). '마지막 프레임 == 테스트 모듈' 규칙은 그 8 개를
          전부 깨뜨리므로 쓰지 않는다.
          """
          repo = str(REPO) + "/"
          owned = [
              f[len(repo):] for f in frames
              if f.startswith(repo) and not f[len(repo):].startswith(".venv/")
          ]
          return owned[-1] if owned else None
      ```
- [ ] **6. 구현 — `classify` 에 한 절 추가.**
      ```python
      if mutant.returncode == 1 and nodeid in mutant.failed:
          if mutant.call_kind not in ASSERTION_KINDS:
              return f"{HARNESS_FAILURE} (non-assertion: {mutant.call_kind})"
          test_module = nodeid.split("::")[0]
          if mutant.call_frame != test_module:
              return f"{HARNESS_FAILURE} (frame outside the test module: {mutant.call_frame})"
          return KILLED
      ```
      `_report`(`:660-675`)의 출력 줄에 `frame=` 을 더한다.
- [ ] **7. green 확인.** 두 새 테스트 pass.
- [ ] **8. 회귀 실측(이 task 의 핵심).**
      ```bash
      uv run --locked python scripts/compose_audit_mutation_harness.py
      ```
      → **18 / 18 KILLED**, 전부 assertion-kind **이고** frame 이 테스트 모듈. 출력을 보고서에 붙인다.
      `CASES`(17, `:259-411`) 외에 `SANDBOX_CASES`(1, `:412-`)가 있으므로 sandbox arm 이 새 술어를 통과하는지
      **별도로 확인**한다 — 스크립트 sandbox 는 nodeid 의 테스트 모듈이 아닌 파일에서 raise 할 수 있다.
      통과하지 못하면 sandbox case 에 한해 케이스별 기대 프레임 필드를 두는 fallback 을 추가한다.
- [ ] **9. Commit**
      ```
      test+fix(harness): kill 은 테스트 자신의 프레임에서 나온 단언만 인정한다

      classify 가 call-phase 예외의 kind 만 보고 프레임 출처를 보지 않아, production 의 bare
      assert 를 건드리는 변이도 KILLED 로 셀 수 있었다. recorder 가 traceback 전체를 남기고
      classify 가 "저장소 소유(비-.venv) 프레임 중 마지막 == nodeid 의 테스트 모듈" 을 추가로
      요구한다. 소박한 "마지막 프레임" 규칙은 등록된 17 case 중 8 개를 깨뜨린다(pytest.fail /
      pytest.raises 가 _pytest 내부에서 끝난다) — 실측해서 배제했다. 18/18 유지.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_01Gh4k8KQJtMwgTV1YAZhYS2
      ```

---

## Task 2 — `-O` 에서도 사는 검사로 승격하고 `S101` 을 `src` 에 켠다 (item 3)

**Files**
- Modify: `src/alive/compose/models.py:360`, `:397`
- Modify: `pyproject.toml:36-38`
- Test: `tests/alive/compose/test_models.py`

**Interfaces** — Consumes: 학습 전 `L3Model.weights_` 상태. Produces: `AssertionError` 대신 `RuntimeError`
(같은 클래스의 기존 관례 `models.py:434` `"L3Model.predict_eps called before fit"` 를 따른다).

**Steps**
- [ ] **1. 실패 테스트 3 개.** 두 assert 는 **각각 다른 도달 경로**를 가진다 — 하나로 묶지 않는다:
      ```
      test_the_l3_forward_refuses_an_uninitialised_weight_bank
          # models.py:360 — _forward_batch 는 미학습 인스턴스에서 직접 호출로 도달한다
      test_the_l3_fit_refuses_when_lazy_init_left_the_bank_unset
          # models.py:397 — _lazy_init(:342) 바로 다음 줄이라 monkeypatch 로 no-op 을 만들어야 도달한다
      test_both_invariants_still_raise_under_optimized_python
          # subprocess `python -O` 로 두 경로를 각각 확인한다
      ```
<!-- R4-b: -O가 assert를 지운 뒤 실제로는 len(None)의 TypeError로 붕괴하는 두 경로의 관찰값을 바로잡았다. -->
- [ ] **2. red 확인.** 지금은 정상 interpreter에서 `AssertionError` 이므로 `pytest.raises(RuntimeError)` 가 red 임을,
      `python -O` arm 에서는 두 assert가 사라진 뒤 후속 `len(None)`에서 **비계약 `TypeError`**가 나는 것을 각각 기록한다
      (`models.py:363`, `:402`). 구현 후 두 모드 모두 지정한 `RuntimeError`여야 한다.
- [ ] **3. 구현(코드).** 두 site 모두:
      ```python
      if self.weights_ is None:  # -O 에서도 살아 있는 검사 (bare assert 는 사라진다)
          raise RuntimeError("L3Model._forward_batch called before fit")   # :360
          # :397 은 "L3Model.fit: _lazy_init left weights_ unset"
      ```
- [ ] **4. 구현(lint).**
      ```toml
      [tool.ruff.lint]
      select = ["E", "F", "W", "I", "S101"]
      ignore = []

      [tool.ruff.lint.per-file-ignores]
      # 테스트와 스크립트의 `assert` 는 이 저장소의 검증 언어 자체다(kill 인증도 그 위에 선다).
      # S101 은 production source 에만 적용한다 — `-O` 실행에서 조용히 사라지는 검사를 막는 것이 목적.
      "tests/**" = ["S101"]
      "scripts/**" = ["S101"]
      ```
- [ ] **5. green 확인.**
      ```bash
      uv run --locked ruff check src tests scripts && uv run --locked ruff format --check src tests scripts
      uv run --locked pytest -q tests/alive/compose/test_models.py -p no:randomly
      ```
- [ ] **6. 참/거짓 실측.** `raise` 를 다시 `assert` 로 되돌리면 (a) 세 테스트가 각각 red, (b) `ruff check src` 가
      S101 **2 건**(`models.py:360,397`)을 낸다 — 둘 다 실행해 기록한다.
      *사전 실측:* `ruff check --select E,F,W,I,S101 --per-file-ignores 'tests/**:S101' --per-file-ignores 'scripts/**:S101' src tests scripts`
      → `Found 2 errors`, 정확히 그 두 줄.
- [ ] **7. Commit**
      ```
      fix(compose): L3 의 두 내부 불변식을 -O 에서도 남는 검사로 승격하고 S101 을 src 에 켠다

      models.py:360,397 의 bare assert 는 python -O 아래에서 사라져 아무 검사도 남지 않았다.
      같은 클래스의 기존 RuntimeError 관례(:434)를 따라 승격하고, ruff S101 을 production
      source 에만 적용해 재발을 lint 에서 막는다. 두 site 는 도달 경로가 달라 각각의 negative
      를 둔다(:360 직접 호출, :397 _lazy_init no-op).

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_01Gh4k8KQJtMwgTV1YAZhYS2
      ```

---

## Task 3 — producer 의 `--require-admitted` (item 1)

**Files**
- Modify: `scripts/compose/measure_pseudobulk_approximation_bias.py` — argparse(`:947-997`), `main()` 말미(`:1029-1038`)
- Test: `tests/alive/compose/test_approximation_bias_metric.py` (CLI 절은 `:1054` 이후)

**Interfaces** — Consumes: `report["admission_status"]`(`:889`), `ADMITTED`(`src/alive/compose/approximation_bias.py:44`).
Produces: exit `0`(기본, 불변) / exit `4`(플래그 + 비-admitted). **보고서 파일은 어느 경우에도 그대로 쓰인다.**

**Steps**
- [ ] **1. 실패 테스트 2 개.**
      ```
      test_require_admitted_makes_a_not_admissible_report_a_nonzero_exit   # exit 4, --out 존재, 내용 NOT_ADMISSIBLE
      test_without_the_flag_a_not_admissible_report_still_exits_zero       # 대조군(기본 경로)
      ```
- [ ] **2. red 확인.** 플래그가 없으므로 첫 테스트가 argparse `SystemExit(2)` 로 red 임을 실행해 기록한다.
- [ ] **3. 구현.**
      ```python
      ap.add_argument(
          "--require-admitted",
          action="store_true",
          help=(
              "exit non-zero when the report is NOT_ADMISSIBLE. The report is STILL "
              "written -- the refusal reason belongs on disk. Default off, because the "
              "measurement succeeding and the report being admissible are two different "
              "facts, and two committed tests pin the default."
          ),
      )
      ...
      if args.require_admitted and report["admission_status"] != ADMITTED:
          print(
              f"refusing: admission_status={report['admission_status']} (--require-admitted)",
              file=sys.stderr,
          )
          return 4
      return 0
      ```
      `sys.exit(main())`(`:1041-1042`)은 그대로.
      *exit code 근거:* driver 의 등록된 exit 계약(`tests/alive/compose/driver/test_exit_code_contract.py`, 0/10/20/30/1)은
      **driver CLI 전용**이고 이 producer 는 그 파일에 등장하지 않는다. `4` 는 그 다섯 값과도 argparse 의 `2` 와도 겹치지 않는다.
      새 예외 클래스를 만들지 않으므로 같은 파일의 기계적 예외 열거(`src/alive` 전수)도 영향받지 않는다.
- [ ] **4. green 확인 + 기존 계약 불변 실측.**
      ```bash
      uv run --locked pytest -q tests/alive/compose/test_approximation_bias_metric.py \
                                tests/alive/compose/test_finalize_approximation_bias_config.py -p no:randomly
      ```
      `test_a_log_normalized_probe_a_pass_does_not_admit_a_raw_count_report`(`:1140`, `exit_code == 0` at `:1157`)와
      `test_a_log_probe_chain_cannot_clear_the_collective_bias_blocker`(`test_finalize_…:442`, `:464`)가 green 이어야 한다.
- [ ] **5. 참/거짓 실측.** `return 4` → `return 0` 변이 → 새 테스트가 이름 붙은 `AssertionError` 로 red.
- [ ] **6. Commit**
      ```
      feat(compose): producer 의 --require-admitted — 거부 사유는 디스크에, 실패 신호는 exit code 로

      NOT_ADMISSIBLE 보고서에도 exit 0 이라 단순 자동화가 성공으로 오인할 수 있었다. 기본값은
      유지한다(committed 테스트 두 개가 "측정은 성공했고 거부 사유는 디스크에" 를 핀한다) —
      strict caller 만 플래그로 exit 4 를 받는다. 보고서 바이트는 플래그와 무관하게 동일하다.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_01Gh4k8KQJtMwgTV1YAZhYS2
      ```

---

## Task 4 — finalizer 를 Probe-A evidence bytes 에 결속한다 (item 2) · T1 이후

**Files**
- Modify: `scripts/compose/finalize_approximation_bias_config.py` — imports(`:60-65`),
  module Usage(`:40-45`), `finalize_bias_config`(`:172-288`), argparse(`:307-311`), `main`(`:290-`)
<!-- R4-b: T4의 실제 negative 수를 아래 보강된 다섯 arm과 맞췄다. -->
<!-- R4-b: required CLI paths가 깨뜨리는 실제 main(argv) 호출과 Usage 예제를 T4 범위에 추가했다. -->
- Test: `tests/alive/compose/test_finalize_approximation_bias_config.py` — 8 개 직접 호출부(`:177`, `:205`, `:251`, `:267` 등),
  CLI argv 호출부(`:353-371`) + 신규 5
- Test: `tests/alive/compose/test_phase2b.py:2476`, `:2528` — 2 개 호출부
- Modify: `scripts/compose_audit_mutation_harness.py` — **M19 등록** (T1 이 같은 파일을 먼저 고친다)

**Interfaces**
- Consumes(전부 기존 public API; byte-pinned `approximation_bias.py` 는 **읽기만**):
  `load_probe_a_evidence`(`:829`), `probe_a_from_evidence`(`:788`), `bridge_admits`(`:257`),
  `REPRESENTATION`(`:29`), `validate_approximation_bias_report`(`:868`), `sha256_file`
<!-- R4-b: _PROVENANCE_KEYS의 실제 정의 파일을 명시해 finalizer 안의 존재하지 않는 상수로 오해하지 않게 했다. -->
- Consumes(report provenance, 전부 `src/alive/compose/approximation_bias.py:80-99`의 `_PROVENANCE_KEYS` 필수 키):
  `probe_a_evidence_sha256`, `probe_a_registration_sha256`, `probe_a_verification_sha256`,
  `probe_a_output_representation`, `git_commit`
- Produces: **키워드 필수** 세 인자를 더한 시그니처. optional 로 두지 않고, "no-arguments still works" 테스트도 **두지 않는다** —
  그 테스트가 바로 취약 경로를 green 으로 고정한다.

**Steps**
<!-- R4-b: 필수 세 byte-source 각각의 변조 arm을 추가하고 구현 전 오류를 unexpected-keyword로 정확히 고쳤다. -->
- [ ] **1. 신규 negative 5 개와 기존 10 개 직접 호출부 및 CLI argv 호출부를 먼저 갱신한다.** 전부
      `metric_tests._write_probe_a_evidence`(`test_finalize_approximation_bias_config.py:455-457`)가 만든 admission,
      `probe_a_registration.json`, `verify.json` 세 경로를 명시한다. negatives는 (a) admission content SHA,
      (b) registration SHA, (c) verification SHA가 각각 report provenance와 다름, (d) evidence의
      `output_bridge.representation`이 report leaf와 다름, (e) finalizer가 가져온 `bridge_admits`를 false로
      monkeypatch한 defense-in-depth arm이다. 전부 **capture-and-assert 헬퍼**로 쓴다.
- [ ] **2. red 확인.** 구현 전에는 새 keyword를 받지 않으므로 다섯 negative와 갱신된 호출부가
      `TypeError: unexpected keyword argument`로 red임을 각각 기록한다.
- [ ] **3. 구현 뒤 각 negative가 의도한 typed refusal에 도달하는지 확인한다.** 단순 `TypeError`/경로 누락은 green으로 세지 않는다.
- [ ] **4. 구현.** `validate_approximation_bias_report(...)`(`:262-274`) **뒤**에:
      ```python
      provenance = report["provenance"]
      for path, key, field in (
          (probe_a_evidence_path, "probe_a_evidence_sha256", "Probe-A admission"),
          (probe_a_registration_path, "probe_a_registration_sha256", "Probe-A registration"),
          (probe_a_verification_path, "probe_a_verification_sha256", "Probe-A verification"),
      ):
          if sha256_file(path) != provenance[key]:
              raise ValueError(
                  f"finalize_bias_config: {field} bytes do not match the report's {key}"
              )
      # 같은 검증기를 다시 태운다 -- 새 신뢰 가정을 만들지 않기 위해서다.
      evidence = load_probe_a_evidence(
          probe_a_evidence_path,
          registration_path=probe_a_registration_path,
          verification_path=probe_a_verification_path,
          expected_git_commit=str(provenance["git_commit"]),
          expected_registration_sha256=str(provenance["probe_a_registration_sha256"]),
          expected_verification_sha256=str(provenance["probe_a_verification_sha256"]),
      )
      probe_a = probe_a_from_evidence(
          evidence,
          expected_git_commit=str(provenance["git_commit"]),
          expected_registration_sha256=str(provenance["probe_a_registration_sha256"]),
          expected_verification_sha256=str(provenance["probe_a_verification_sha256"]),
      )
      bridged = str(probe_a["output_bridge"]["representation"])
      if bridged != str(provenance["probe_a_output_representation"]):
          raise ValueError(
              "finalize_bias_config: the report's probe_a_output_representation "
              f"({provenance['probe_a_output_representation']!r}) is not what the Probe-A "
              f"evidence actually validated ({bridged!r})"
          )
      if not bridge_admits(method=REPRESENTATION, probe_representation=bridged):
          raise ValueError(
              "finalize_bias_config: the Probe-A bridge validated "
              f"{bridged!r}, which does not admit a {REPRESENTATION!r} report"
          )
      ```
      검증은 **config 복사·기록 전**에 둔다(`:276-285` 의 단일 leaf 변경은 그대로).
      CLI 에 `--probe-a-evidence` / `--probe-a-registration` / `--probe-a-verification` 을 `required=True` 로 더한다.
<!-- R4-b: 세 digest·representation·bridge의 각 guard가 독립 named assertion에 결속되도록 mutation step을 완전하게 했다. -->
- [ ] **5. green 확인 + 참/거짓 실측.** 세 digest 비교, representation 비교, `bridge_admits` 거부를 각각
      무력화하는 변이 → 대응 negative가 이름 붙은 `AssertionError`로 red임을 실행해 기록한다.
- [ ] **6. M19 등록.** `scripts/compose_audit_mutation_harness.py` 에 "bridge 비교 제거" → (b) 의 nodeid.
      이 스크립트는 `scripts/compose/` 아래라 importable dotted name 이 없으므로, 기존 `SandboxCase`
      (`:412-`)가 producer 스크립트에 쓰는 것과 **같은 방식**을 따른다. `uv run --locked python
      scripts/compose_audit_mutation_harness.py` → **19 / 19 KILLED** 출력을 붙인다.
- [ ] **7. Commit**
      ```
      fix(compose): finalizer 를 Probe-A evidence bytes 에 결속한다 (세 경로 필수)

      finalizer 는 report 의 자기 선언 probe_a_output_representation 만 검사하고 원 evidence 를
      다시 열지 않았다. 세 경로를 필수 인자로 만들고, 기존 load_probe_a_evidence /
      probe_a_from_evidence / bridge_admits 를 그대로 호출해 (1) 세 digest 대조 (2) evidence 가
      실제로 검증한 representation 과 report leaf 의 일치 (3) 그 representation 이 이 method 를
      ADMIT 하는지를 확인한다. optional 로 두면 생략으로 우회되므로 두지 않는다.
      byte-pinned approximation_bias.py 는 호출만 한다. M19 추가, 19/19.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_01Gh4k8KQJtMwgTV1YAZhYS2
      ```

---

## Task 5 — `CLAUDE.md` 정합 (item 5, item 14 흡수)

<!-- R4-b: T5의 세 governance 치환 자체를 red→green으로 고정하는 named contract test를 추가했다. -->
**Files**
- Modify(스크립트 경유): `CLAUDE.md:4`, `:25`, `:135-136`
- Test: `tests/test_claude_md_anchors.py:116-125` 옆에 세 치환의 속성을 검사하는 named test 추가

**Interfaces** — Consumes: 서명된 결정문의 근거 표기(`docs/superpowers/2026-09-07-compose-audit-release-decisions.md` D2 절).
Produces: 개정일 갱신 · 취약 참조 제거 · 채팅 인용 → 서명 근거. **줄 수 불변(198).**

**Steps**
<!-- R4-b: 경로·수명 불명의 임시 파일 생성을 없애고 사전 값을 실행 보고에 기록하도록 했다. -->
- [ ] **1. 실패 테스트.** `test_root_governance_uses_the_current_signed_attribution_and_stable_registry_anchor`를 추가한다.
      개정일 `2026-09-09`, literal `` `#registry` ``, 채팅 인용 부재, `수정안 G(2026-09-07 결정문` 존재를 각각 단언한다.
- [ ] **2. red 확인 + 사전 실측.** named test가 현행 세 old value 때문에 `AssertionError`인지 확인하고,
      `wc -l CLAUDE.md`(198) 와 `sed -n '132,136p' CLAUDE.md` 출력을 실행 보고에 기록한다.
- [ ] **3. 편집 — 스크립트로만, 개행 수 보존.**
      ```bash
      uv run --locked python - <<'PY'
      from pathlib import Path
      p = Path("CLAUDE.md"); s = p.read_text(encoding="utf-8")
      before = len(s.splitlines())

      R = [
          ("> **개정일:** 2026-07-19", "> **개정일:** 2026-09-09"),
          ("현재 protocol 상태는 §5 registry 가 authoritative 하다.",
           "현재 protocol 상태는 `#registry` 가 authoritative 하다."),
          # 3번째는 두 줄에 걸쳐 있다. 개행 수를 보존해야 줄 수가 유지된다.
          ('처분 — 오너 지시 "모두 권장사항으로\n진행"; 별도 spec 없이',
           '처분 — 수정안 G(2026-09-07 결정문\n서명표); 별도 spec 없이'),
      ]
      for old, new in R:
          assert s.count(old) == 1, old
          assert old.count("\n") == new.count("\n"), f"line-neutral 위반: {old!r}"
          s = s.replace(old, new, 1)

      # 검증은 byte equality 가 아니라 속성으로 한다.
      after = len(s.splitlines())
      assert after == before == 198, (before, after)
      assert after < 200
      region = "\n".join(s.splitlines()[132:136])              # 133-136
      assert "ID-only null" in region and "deferred 로 처분" in region
      assert "모두 권장사항으로" not in s
      assert "수정안 G(2026-09-07 결정문" in s
      p.write_text(s, encoding="utf-8")
      print("lines", before, "->", after)
      PY
      ```
      *사전 실측(in-memory):* `lines 198 -> 198` · `under_200 True` · 의무 문장 133-136 잔류 True ·
      채팅 인용 부재 True · 변경 구간 최대 폭 102자.
      **byte-equality 검사는 쓰지 않는다** — 고치려는 문장이 바로 그 범위 안(`:135-136`)에 있어 항상 거짓이 된다(양쪽 초안의 공통 결함).
- [ ] **4. item 14 흡수 검증.** 줄 수가 불변이므로 서명된 결정문의 snapshot
      `docs/superpowers/2026-09-07-compose-audit-release-decisions.md:70-72`(`CLAUDE.md:132-136 (#data-eval)`,
      "줄번호는 2026-09-07 기준 snapshot 이며 정본 참조는 anchor")는 **여전히 그 자리를 가리킨다**.
      어긋나면(줄 수가 움직였으면) 결정문에 `[2026-09-09 정정 — snapshot 줄번호]` **문단만** 추가한다(서명 문장 불변).
- [ ] **5. green 확인.**
      ```bash
      uv run --locked pytest -q tests/test_claude_md_anchors.py \
                                tests/alive/compose/test_audit_contract_docs.py -p no:randomly
      ```
<!-- R4-b: CLAUDE.md negative probe도 ARS와 복구 보장을 지키도록 구체화했다. -->
- [ ] **6. 참/거짓 실측.** assertion-heavy Python script의 `try/finally`에서만 `CLAUDE.md` 원 bytes를 보관한 채
      더미 두 줄을 추가해 정확히 200줄로 만들고, named test
      `test_root_claude_md_is_concise_and_protocol_independent`(`tests/test_claude_md_anchors.py:116-118`) 하나가
      red인지 실행한다. `finally`에서 원 bytes를 복원하고 SHA-256 일치를 assert한 뒤 green을 다시 확인한다.
- [ ] **7. Commit**
      ```
      docs(governance): CLAUDE.md 의 개정일·앵커 참조·D2-b 근거를 서명 기록으로 맞춘다

      개정일이 2026-07-19 로 낡았고, §5 registry 는 renumber 에 깨지는 참조였으며, D2-b 처분의
      근거가 서명문이 아니라 대화 인용이었다. 세 치환 모두 개행 수를 보존해 198 줄이 그대로다 —
      서명된 결정문이 CLAUDE.md:132-136 을 dated snapshot 으로 인용하고 있기 때문이다. 검증은
      byte equality 가 아니라 속성(줄 수·의무 문장 잔류·인용 부재·근거 존재)으로 한다.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_01Gh4k8KQJtMwgTV1YAZhYS2
      ```

---

## Task 6 — HISTORICAL 종료 sentinel 을 작성 규칙에 적는다 (item 6)

<!-- R4-b: 규칙 문구 자체를 고정하는 red/green test가 없던 공허한 T6에 contract test를 추가했다. -->
**Files**
- Modify: `.claude/rules/documentation.md` (현재 25 줄, 마지막 항목 뒤에 한 줄)
- Test: `tests/alive/compose/test_audit_contract_docs.py:74-104` 옆에 규칙 파일을 직접 읽는 named test 추가

**Interfaces** — Consumes: 실제 계약(`tests/alive/compose/test_audit_contract_docs.py:98-104`).
Produces: 작성 규칙 한 줄과 그 문구를 고정하는 contract test. 기존 `tests/test_claude_md_anchors.py:125` 는 파일 **존재**만 확인한다.

**Steps**
- [ ] **1. 실패 테스트.** `test_documentation_rule_requires_the_explicit_historical_closing_sentinel`을 추가해
      `.claude/rules/documentation.md`가 `[HISTORICAL …]`, literal `<!-- /HISTORICAL -->`, sentence heuristic 금지를
      모두 요구하게 한다. 현행 규칙에서 named `AssertionError`로 red임을 기록한다.
- [ ] **2. 한 줄 추가.**
      ```markdown
      - Isolate a superseded passage with a `[HISTORICAL …]` marker and close it with an explicit `<!-- /HISTORICAL -->` sentinel; block extent is the sentinel, never sentence heuristics.
      ```
      근거 위치: 계약은 `tests/alive/compose/test_audit_contract_docs.py:74-104`, spec 부록 H 의 서술은
      `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md:771-778`,
      실제 사용례는 같은 spec `:531-542`, `:594-630`.
- [ ] **3. 참/거짓 실측.** 새 규칙 문구에서 closing sentinel token을 제거한 temporary text를 검사하는 arm은
      named `AssertionError`, 원문 arm은 pass임을 각각 기록한다. signed spec bytes는 변형하지 않는다.
- [ ] **4. green 확인.** `uv run --locked pytest -q tests/alive/compose/test_audit_contract_docs.py -p no:randomly`
- [ ] **5. Commit**
      ```
      docs(rules): HISTORICAL 블록의 종료 sentinel 을 작성 규칙으로 적는다

      계약은 test_audit_contract_docs.py 의 범위 계산에만 살아 있었고 작성 규칙에는 없었다.
      sentinel 을 빼면 historical 격리 범위가 문장 추정으로 넓어진다.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_01Gh4k8KQJtMwgTV1YAZhYS2
      ```

---

## Task 7a — 분기·문장 renderer 를 leaf 모듈로 (item 7, 전반) · T7b 의 선행

**Files**
- Create: `src/alive/compose/headline.py` — `preregistered_headline_branch` **이동** + `render_preregistered_headline` 신설
- Modify: `src/alive/compose/phase2b.py:769-845` — 함수 본체를 제거하고 leaf 모듈에서 **re-export**
  (`test_band_sensitivity.py` 의 8 개 `from alive.compose.phase2b import preregistered_headline_branch` 를 깨지 않기 위해)
- Modify: `tests/alive/compose/test_audit_contract_docs.py:290`(`_PHASE2B_SOURCE`), `:361`
- Create: `tests/alive/compose/test_headline.py`

**Interfaces**
- Consumes: `band_passes: bool`, `flip: float | str`, `ladder_max: float`, `sealed_axis: str`
- Produces:
  ```python
  # INVALID/FUTILITY_STOPPED: claim text key 자체가 없는 최소 marker
  {"applicable": False, "reason": "INVALID" | "FUTILITY_STOPPED"}
  # 입력 의미 불일치: terminal 조립은 raise하지 않고 durable이 이 marker를 거부
  {"applicable": False, "reason": str, "band_branch": None,
   "band_sentence": None, "finite_flip_note": None,
   "learned_family_sentence": None, "inconsistent": True}
  # 그 밖의 axis
  {"applicable": True, "reason": None,
   "band_branch": "i" | "ii" | "iii", "band_sentence": str,
   "finite_flip_note": str | None,          # branch i 이고 flip 이 유한할 때만
   "learned_family_sentence": str | None,   # sealed_axis == "GI_LEARNABLE_WIN" 일 때만
   "inconsistent": bool}
  ```
<!-- R4-b: binding INVALID marker를 최소 2-key schema로 고정하고 Markdown 줄바꿈과 Python 문자열의 byte-equality 오해를 제거했다. -->
- 문장 상수: 서명된 §8 문장의 Markdown prefix와 줄바꿈을 공백 하나로 정규화한 **논리 문장 exact text**를
  코드 상수에 복사한다. 정본은 문서이고 상수는 그 복사본이며, doc-contract 테스트가 같은 정규화 뒤 equality를 강제한다.
  finite flip의 canonical 치환은 `repr(float(flip))`으로 고정하고 exact-text 테스트가 `1.25`와 `2.5`를 핀한다.

**Steps**
- [ ] **1. 순환 회피 근거 확인(사전 실측).** `src/alive/compose/phase2b.py:73` 이 이미
      `from alive.compose.durable import finalize_phase2b_durable_outputs` 다. durable 이 phase2b 의 renderer 를
      import 하면 **순환**이며, in-memory 로 그 import 를 넣어 실행한 결과
      `ImportError: cannot import name 'finalize_phase2b_durable_outputs' from 'alive.compose.durable'` 였다
      (무변경 control arm 은 정상 import). 그래서 renderer 는 **leaf 모듈**에 둔다.
- [ ] **2. 패키지 게이트 확인(사전 실측).** `src/alive/compose/__init__.py` 는 byte-pinned 이고 PEP-562
      `_LAZY_EXPORTS`(`:19`) 게이트지만, 그 map 에 없는 서브모듈도 전체 경로로 정상 import 된다
      (`alive.compose.verdict2` 로 확인). 따라서 **`__init__.py` 를 건드릴 필요가 없다.**
      또한 `phase2b.py`·`durable.py`·새 `headline.py` 는 모두 `_ISOLATION_CLOSURE`(`test_kernel_isolation_ci.py:575-607`) **밖**이다 — 이 step 에서 다시 확인한다.
- [ ] **3. 실패 테스트.** `tests/alive/compose/test_headline.py` 에 arm 별로:
      ```
      test_branch_i_sentinel_renders_the_registered_sentence            # flip == NEVER_FLIPS
      test_branch_i_finite_above_the_ladder_adds_the_extrapolation_note # 정정 (i): λ=<flip> 병기
      test_branch_ii_substitutes_the_canonical_flip_value               # 출력에 "<flip>" 이 남지 않는다
      test_branch_iii_renders_the_registered_band_failure_sentence
      test_the_learned_family_sentence_appears_only_for_gi_learnable_win  # on/off 두 arm
      test_an_invalid_axis_renders_no_preregistered_sentence            # applicable False
      test_a_futility_stopped_axis_renders_no_preregistered_sentence
      test_an_inconsistent_band_and_flip_is_recorded_not_raised         # inconsistent True, 예외 없음
      ```
      근거: (iv) 는 (i)~(iii) 에 **더해지는** 문장이고(`docs/superpowers/2026-08-29-compose-pair-dependence-decision.md:158-160`),
      정정 (i) 은 유한 flip 에서 `λ=<flip>` **병기**를 요구한다(`:176-178`).
      `SealedAxis` 는 5 값이다 — `GI_LEARNABLE_WIN`·`PARTIAL`·`NO_DISTINCT_WIN`·`FUTILITY_STOPPED`·`INVALID`
      (`src/alive/compose/verdict2.py:111-115`).
- [ ] **4. red 확인.** 모듈이 없으므로 `ImportError` 로 red 임을 실행해 기록한다.
- [ ] **5. 구현 — `src/alive/compose/headline.py`.**
      ```python
      def render_preregistered_headline(
          *, band_passes: bool, flip: float | str, ladder_max: float, sealed_axis: str
      ) -> dict[str, object]:
          """D4 §8 의 사전등록 문장을 고른다. terminal 조립 중 절대 raise 하지 않는다.

          유효한 verdict 가 없는 terminal(INVALID / FUTILITY_STOPPED)에는 사전등록 문장을
          싣지 않는다 -- COMPLETE 와 INVALID 는 같은 body 를 쓰고(phase2b.py:2240-2243),
          INVALID 스왑 시 clause 는 원값 그대로 실린다(:2176). 그대로 두면 "not trustworthy"
          로 선언된 run 에 headline claim 이 붙는다.
          """
          if sealed_axis in ("INVALID", "FUTILITY_STOPPED"):
              return {"applicable": False, "reason": sealed_axis}
          try:
              branch = preregistered_headline_branch(
                  band_passes=band_passes, flip=flip, ladder_max=ladder_max
              )
          except ValueError as exc:      # 불일치는 기록하고 durable 이 fail-closed 로 잡는다
              return {"applicable": False, "reason": str(exc), "band_branch": None,
                      "band_sentence": None, "finite_flip_note": None,
                      "learned_family_sentence": None, "inconsistent": True}
          ...
      ```
<!-- R4-b: 문장 drift 검사가 실제로 추가되도록 이동 검증 step에 normalized exact-text equality를 명시했다. -->
- [ ] **6. 이동에 따른 doc-contract 테스트 갱신(필수).** `tests/alive/compose/test_audit_contract_docs.py:361` 이
      `assert "def preregistered_headline_branch(" in source` 이고 `source` 는 `_PHASE2B_SOURCE`
      (`:290` = `src/alive/compose/phase2b.py`)다. **re-export 로는 이 단언을 만족시키지 못한다** — 이 테스트가
      새 leaf 모듈 소스를 보게 고친다. `:353-355` 의 세 토큰(`NEVER_FLIPS`·`FAILS_AT_REGISTERED_BAND`·
      `sensitivity_band_inflation`) 검사도 어느 소스를 보는지 함께 조정한다. 같은 test에 §8의 네 logical sentence를
      공백 정규화한 값과 `headline.py` 상수의 exact equality를 추가한다.
- [ ] **7. green 확인.**
      ```bash
      uv run --locked pytest -q tests/alive/compose/test_headline.py \
        tests/alive/compose/test_band_sensitivity.py \
        tests/alive/compose/test_audit_contract_docs.py -p no:randomly
      ```
- [ ] **8. 참/거짓 실측.** (a) 문장 상수의 한 글자를 바꾸면 doc-contract equality 테스트가 red,
      (b) `flip` 치환을 없애면 `"<flip>"` 잔존 테스트가 red, (c) INVALID 분기를 제거하면
      `test_an_invalid_axis_renders_no_preregistered_sentence` 가 red — 셋 다 실행해 기록한다.
- [ ] **9. Commit**
      ```
      feat(compose): 사전등록 headline 문장 renderer 를 leaf 모듈로 분리한다

      preregistered_headline_branch 는 분기만 정하고 문장을 내보내는 코드가 없어 λ=<flip> 치환이
      사람 손에 남아 있었다. renderer 를 새 leaf 모듈에 두는 이유는 phase2b 가 이미 durable 을
      import 하므로(phase2b.py:73) durable 이 renderer 를 가져오면 순환이기 때문이다 — 실측으로
      확인했다. 유효한 verdict 가 없는 terminal(INVALID / FUTILITY_STOPPED)에는 문장을 만들지
      않고, 불일치는 예외가 아니라 inconsistent 플래그로 기록한다.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_01Gh4k8KQJtMwgTV1YAZhYS2
      ```

---

## Task 7b — terminal 중첩 + durable 의미 재검증 + schema v2 (item 7, 후반) · T7a·T4 이후

**Files**
- Modify: `src/alive/compose/phase2b.py:753`(`BAND_SENSITIVITY_SCHEMA` v1→v2), `:847-874`(`_band_sensitivity_block`),
  `:2226-2238`(body 조립)
- Modify(추가만): `src/alive/compose/durable.py:854-860` — 의미 재검증을 **덧붙인다**
- Modify: `tests/alive/compose/_terminal_bodies.py:63` (schema 문자열)
- Modify: `tests/alive/compose/test_phase2b.py:1084` (schema 문자열), `:1043-1098`
- Modify: `tests/alive/compose/test_durable.py` (Amendment B checksum 테스트는 `:1279-1289`; 그 옆에 의미 tamper arm 추가)
- Modify(날짜 붙은 정정 문단만): `docs/superpowers/2026-08-29-compose-pair-dependence-decision.md` §8(`:141-190`),
  `docs/superpowers/specs/2026-07-05-compose-durable-ledger-design.md:107`
- Modify: `scripts/compose_audit_mutation_harness.py` — **M20 등록**

<!-- R4-b: producer가 renderer에 sealed axis와 additive clause를 넘기는 실제 함수 경계를 명시했다. -->
**Interfaces**
- Consumes: `registered_summary["verdict_clauses"]["additive_clears"]` 와 `["sealed_axis"]`
  (둘 다 `src/alive/compose/phase2b.py:1259-1262` 에서 방출), `band_sensitivity["flip_lambda"]["additive"]`,
  `by_lambda[*]["lambda"]` 의 최대값(= `ladder_max`; **config 를 hardcode 하지 않는다** — terminal 이 사다리를 이미 싣는다)
- Produces: `band_sensitivity.headline = {...}`(T7a 의 반환값) 아래 `compose_band_sensitivity_v2`.
  **terminal 최상위 roster 는 그대로다**(`src/alive/compose/terminal.py:444-461`) — 기존 rostered 필드 **안**에 중첩한다.
  Producer 경계는 `_band_sensitivity_block(sensitivity, *, sealed_axis, additive_clears)`로 바꾸고,
  body 조립 시 이미 생성된 `summary["sealed_axis"]`와 `summary["verdict_clauses"]["additive_clears"]`를 넘긴다
  (`src/alive/compose/phase2b.py:2191-2210`, `:2226`).

**Steps**
- [ ] **1. 실패 테스트 — durable 쪽 negative 를 먼저.** 오늘 durable 검증은 **checksum 결속뿐**이므로
      (`src/alive/compose/durable.py:854-860`, 유일한 테스트가 `test_durable.py:1279-1289`)
      **자기일관적인 잘못된 문장은 통과한다**. 그것을 red 로 만드는 테스트를 먼저 쓴다:
      ```
      test_a_headline_whose_branch_disagrees_with_the_flip_fails_closed
      test_a_headline_that_still_carries_the_flip_placeholder_fails_closed
      test_a_learned_family_sentence_on_a_non_learnable_axis_fails_closed
      test_a_headline_on_an_invalid_terminal_fails_closed
      test_an_inconsistent_headline_marker_fails_closed
      ```
      각 arm 은 블록을 고치고 **checksum 도 함께 다시 계산**해 넣는다(그래야 checksum 검사를 통과해 의미 검사에 도달한다).
<!-- R4-b: durable negative arm 수를 inconsistent marker를 포함한 다섯 개로 맞췄다. -->
- [ ] **2. red 확인.** 다섯 arm 이 지금은 **통과**함을(= 검사가 없음을) 실행해 기록한다 — 이것이 이 task 의 근거다.
- [ ] **3. 구현 — 블록 확장 + schema 승격.** `_band_sensitivity_block`(`:847`)이 T7a 의 renderer 를 호출해
      `"headline"` 키를 더하고, `BAND_SENSITIVITY_SCHEMA`(`:753`)를 `compose_band_sensitivity_v2` 로 올린다.
      `sha256_json(sensitivity_block)`(`:2237`)이 자동으로 새 내용을 묶는다.
<!-- R4-b: renderer가 만든 inconsistent marker가 self-consistent하게 durable을 통과하던 구멍을 fail-closed로 닫았다. -->
- [ ] **4. 구현 — durable 의미 재검증(추가만).** `durable.py` 의 Amendment B 절(`:854-860`) **뒤**에
      `from alive.compose.headline import render_preregistered_headline` 로 기대값을 재계산하고 **정확 일치**를 요구한다.
      이어 `headline.get("inconsistent") is True`면 `DurableLedgerError`로 거부한다. 즉 terminal 조립은 원 예외를
      내지 않고 진단 marker를 기록하지만 durable publish는 그 marker를 성공 artifact로 승인하지 않는다.
      T7a 의 leaf 모듈이므로 순환이 생기지 않는다(step 7a-1 의 실측).
- [ ] **5. green 확인 + 문서 정정 2 곳.**
      - `…pair-dependence-decision.md` §8 에 `[2026-09-09 정정 — 문장 emission 과 적용 범위]` 문단:
        emission 위치(terminal `band_sensitivity.headline`), schema v2, canonical float 표기, 그리고
        **"INVALID·FUTILITY_STOPPED terminal 에는 사전등록 문장을 싣지 않는다"**. 서명된 네 문장은 그대로 둔다.
      - `docs/superpowers/specs/2026-07-05-compose-durable-ledger-design.md:107` 이 이 블록을 **descriptive-only** 로
        등록하므로, 같은 절에 날짜 붙은 정정 한 문단으로 "블록이 사전등록 문장을 **담되** verdict 를 바꾸지 않는다"
        를 명시한다. (main spec `…2026-06-22…:717-718` 은 "두 필드로 기록한다" 이고 **필드 수는 변하지 않으므로** 정정이 필요 없다.)
- [ ] **6. 참/거짓 실측.** 다섯 durable negative 각각에 대해 구현 전(pass) / 구현 후(named `AssertionError` 또는
      `DurableLedgerError`) 출력을 나란히 기록한다.
- [ ] **7. M20 등록.** "durable 의미 재검증 제거" → step 1 의 첫 nodeid.
      `uv run --locked python scripts/compose_audit_mutation_harness.py` → **20 / 20 KILLED**.
- [ ] **8. Commit**
      ```
      feat(compose): 사전등록 headline 을 terminal 에 싣고 durable 이 의미를 재검증한다

      문장이 artifact 밖에 있으면 아무것에도 결속되지 않는다. band_sensitivity 블록 안에
      중첩해(최상위 roster 불변) 기존 band_sensitivity_checksum 이 묶게 하고, schema 를 v2 로
      올린다. durable 은 지금까지 checksum 결속만 봤기 때문에 자기일관적인 잘못된 문장이
      통과했다 -- 이제 verdict_clauses 와 sealed_axis 로 기대 문장을 재계산해 정확 일치를
      요구한다. 문서 정정 두 곳은 날짜 붙은 문단으로만 더한다. M20 추가, 20/20.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_01Gh4k8KQJtMwgTV1YAZhYS2
      ```

---

## Task 8 — 소비 경계의 중복 강제를 기록한다 (item 13)

<!-- R4-b: T8의 주석 변경 자체가 검증되도록 source-contract test를 추가하고 production 동작 변경 0으로 표현을 정확히 했다. -->
**Files**(production logic 변경 0; 주석/docstring + contract test만)
- Modify: `src/alive/compose/outcome_store.py:710-717`
- Modify: `src/alive/compose/terminal.py:1341-1370` (`_ProtectBoundary` docstring 에 역참조 한 줄)
- Modify: `tests/alive/compose/driver/test_sealed_source_integrity_e2e.py` (해당 arm 의 docstring 한 문장)
- Test: `tests/alive/compose/test_audit_contract_docs.py` — 세 역할과 역참조를 source에서 고정하는 named test

**Interfaces** — 없음(문서화). 어떤 동작도 바뀌지 않는다.

**Steps**
- [ ] **1. 실패 테스트 + red.** `test_the_three_consumption_failure_enforcement_roles_are_documented`를 먼저 추가한다.
      `outcome_store.py`에 `TYPED CONTEXT`와 `_ProtectBoundary`, `terminal.py`에 `DURABLE ABORT`와
      `ComposeSealingError`, e2e docstring에 `_seal_consumed`/`EXIT CODE`가 모두 있어야 한다고 단언하고,
      현행 source에서 named `AssertionError`로 red임을 기록한다.
- [ ] **2. 세 강제 지점의 역할을 주석으로 적는다.**
      ```python
      # 소비 경계의 실패는 세 지점이 각기 다른 역할로 처리한다 (변이 규칙 7):
      #   1) 이 site = TYPED CONTEXT. 실패를 ComposeSealingError 로 감싸 메시지를 소유한다.
      #   2) _ProtectBoundary.__exit__ (terminal.py:1386-1405) = DURABLE ABORT. 예외 타입과
      #      무관하게 ABORTED_AFTER_SEAL terminal 을 쓰고 원 예외를 재전파한다.
      #   3) phase2b_cmd._seal_consumed (driver/phase2b_cmd.py:424-426, :853) = EXIT CODE.
      #      예외 타입이 아니라 durable audit 의 존재만 보고 30 을 돌려준다.
      # 따라서 이 site 를 무력화하는 단일 변이는 exit code 30 을 그대로 남긴다(실측). 그런 변이가
      # SURVIVED 로 보이면 테스트가 공허한 것이 아니라 (2)(3)이 막은 것이다 -- 어느 line 이
      # raise 했는지 먼저 측정하고, kill 은 메시지 단언으로 받는다.
      ```
      `_ProtectBoundary` docstring 에는 역방향 한 줄(현재 `outcome_store`·`ComposeSealingError` 언급이 **0** 이다).
<!-- R4-b: T8의 behavioral observation과 documentation red/green을 분리해 둘 다 거짓 양상을 식별하게 했다. -->
- [ ] **3. 동작 참/거짓 실측.** 주석이 주장하는 바를 실행으로 확인한다 — store 의 `except Exception`(`:713`)을
      무력화한 변이에서 `test_an_io_error_in_the_materialization_recheck_still_aborts_after_seal` 의
      **exit-code 단언은 여전히 통과**하고 **메시지 단언이 red** 임을 기록한다.
- [ ] **4. 문서 참/거짓 실측.** 세 source 중 한 곳의 역할 token을 temporary string에서 제거하면 source-contract
      helper가 named `AssertionError`, 원문은 pass임을 기록한다.
<!-- R4-b: T8 green 명령에 새 source-contract test 파일을 포함했다. -->
- [ ] **5. green 확인.**
      ```bash
      uv run --locked pytest -q tests/alive/compose/driver/test_sealed_source_integrity_e2e.py \
                                tests/alive/compose/test_outcome_store.py \
                                tests/alive/compose/test_audit_contract_docs.py -p no:randomly
      ```
- [ ] **6. Commit**
      ```
      docs(compose): 소비 경계 무결성의 세 강제 지점을 기록한다

      exit 30 을 결정하는 것은 store 의 래핑도 protect() 도 아니고 _seal_consumed(audit_path) 다.
      기록이 없으면 단일 site 변이의 SURVIVED 를 "테스트가 공허하다" 로 오독하게 된다(변이 규칙 7).
      코드는 바뀌지 않는다.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_01Gh4k8KQJtMwgTV1YAZhYS2
      ```

---

## Task 9 — 현행 v4 naming 정합 (item 15)

**Files (전수 실측: `measure_approximation_bias_v3` 는 `artifacts/` 제외 30 회 / 5 파일)**
- Modify: `scripts/compose/measure_pseudobulk_approximation_bias.py` — 4 회(정의 `:630`, 호출 `:1015`, docstring `:619`·`:656`)
- Modify: `src/alive/compose/phase2b.py:922`, `:1018` — 2 회 (**양쪽 초안이 모두 빠뜨린 파일**)
- Modify: `tests/alive/compose/test_approximation_bias_metric.py` — 19 회
- Modify: `tests/alive/compose/test_phase2b.py` — 3 회
- Modify: `src/alive/compose/driver/bias_report_preseal.py:124` — live docstring 의 "full v3 integrity"
- Modify: `docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md:14` — "approximation-bias v3 report"

**보존 목록 (건드리지 않는다)**
- `scripts/compose/measure_pseudobulk_approximation_bias.py:932` — "a conforming **v3** pass admission" 은
  **Probe-A admission schema v3** 이고 지금 참이다.
- `src/alive/compose/approximation_bias.py` 의 Probe-A v3 계약 — 게다가 **byte-pinned**.
- `docs/superpowers/plans/2026-07-13-compose-approximation-bias-implementation.md:175`, `:197` — 그 문서 `:11-15` 의
  날짜 붙은 배너가 "아래의 모든 v3 언급은 historical 이며 as-written 으로 보존한다" 를 명시한다.
- `docs/superpowers/specs/2026-07-13-compose-approximation-bias-metric-design.md:107`("v3 reports are not reused
  for activation") 과 `:148`·`:348`(Probe A v3 admission) — 둘 다 다른 대상이고 참이다.

**Interfaces** — 반환 schema 는 그대로 `compose_approximation_bias_report_v4` 다. 심볼과 현행 산문만 바뀐다.

**Steps**
<!-- R4-b: rename이 산출물 bytes를 보존한다는 검사가 사후 자기비교가 되지 않도록 pre-rename SHA capture를 명시했다. -->
- [ ] **1. 실패 테스트 + 사전 산출물.** `test_approximation_bias_metric.py` 에 import-level 테스트를 추가한다 —
      `measure_approximation_bias_v4` 가 존재하고 `measure_approximation_bias_v3` 는 **없어야 한다**.
      코드 개명 전 `_full_report_fixture`로 만든 canonical v4 report bytes의 SHA-256을 실행 보고에 기록한다.
- [ ] **2. red 확인.** 지금은 반대이므로 red 임을 실행해 기록한다.
- [ ] **3. 구현.** 위 Files 목록만 개명한다. sweep 은 **심볼 정확일치**로 한정한다:
      ```bash
      rg -n '\bmeasure_approximation_bias_v3\b' src scripts tests docs
      ```
      "Probe-A v3" 계열 문자열은 **금지 목록**이므로 이 sweep 에 걸리지 않아야 한다(걸리면 패턴이 틀린 것이다).
- [ ] **4. green 확인 + 바이트 불변 실측.** 같은 fixture 로 만든 canonical v4 보고서의 SHA를 다시 계산해
      step 1에 기록한 SHA와 **동일**함을 확인한다
      (개명은 산출물을 바꾸지 않는다).
      ```bash
      uv run --locked pytest -q tests/alive/compose/test_approximation_bias_metric.py \
                                tests/alive/compose/test_phase2b.py -p no:randomly
      uv run --locked pytest -q tests/test_documentation_hygiene.py -p no:randomly
      ```
- [ ] **5. 잔여 분류.** step 3 의 `rg` 를 다시 돌려 남은 히트를 **전부** "보존 목록의 어느 항목인가" 로 분류해 기록한다.
- [ ] **6. Commit**
      ```
      refactor(compose): 현행 approximation-bias 심볼과 문서를 v4 로 맞춘다

      보고서 schema 는 v4 인데 현행 표면 두 곳이 아직 v3 라고 말했다 -- live docstring
      (driver/bias_report_preseal.py:124)과 현행 entrypoint 로 등록된 runbook. 심볼도 v3 다.
      현행 코드/테스트/문서만 v4 로 옮기고, Probe-A admission schema v3 와 배너가 붙은
      historical 문서는 보존 목록으로 명시해 건드리지 않는다.

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_01Gh4k8KQJtMwgTV1YAZhYS2
      ```

---

<!-- R4-b: exact roster 없는 조건부 수정을 실행 task로 가장하지 않고 Gate 결과 처리로 바꿨다. -->
## GATE-1 결과 처리 — 협력 서술 경계 (item 12; implementation task 아님)

GATE-1 이 **a** 로 승인되면: 파일 변경·테스트·커밋 없음. 이 플랜의 GATE-1 절이 그 판단의 기록이 되고,
Global Constraint 6("새로 쓰는 문서에 현재형 협력 지시를 넣지 않는다")만 유지한다.

GATE-1 이 **b** 로 승인되면(오너가 exact roster 제공):
- 먼저 이 플랜에 **exact path:line Files, Interfaces, named red/green test, true/false 측정, commit trailer**를 갖춘
  implementation addendum을 작성·리뷰한다. roster가 없는 현재 문안으로는 파일을 편집하지 않는다.
- addendum은 roster 밖 파일 SHA-256 before/after manifest를 실행 보고에 남기고, immutable evidence JSON과
  `tests/alive/compose/test_kernel_isolation_ci.py:499-504`를 제외한다. 그 문자열이 v1의 독립 리뷰와 v2의
  자기 리뷰를 구분하는 유일한 필드다(`:490-498`).

GATE-1 이 **c** 로 승인되면: evidence 등급 대체 문안과 digest/아카이브 정합화 범위까지 오너가 서명한 뒤,
위와 같은 implementation addendum을 먼저 만든다. 서명 전 변경은 0이다.

---

## 검증 사다리

각 task 끝에서 1→3, wave 끝에서 1→6, 전체 마무리에서 1→8.

1. **각 named red/green pair.** positive 와 negative 를 **따로** 실행해 출력 차이를 기록한다.
   새 kill 은 **이름 붙은 테스트 파일 프레임의 `AssertionError`** 일 때만 인정한다.
2. **Targeted** — 그 task 가 만든/고친 nodeid만: `uv run --locked pytest -q <nodeid> -p no:randomly -p no:cacheprovider`
3. **관련 suite**
   ```bash
   uv run --locked pytest -q tests/alive/compose/test_audit_mutation_harness.py tests/alive/compose/test_models.py -p no:randomly
   uv run --locked pytest -q tests/alive/compose/test_approximation_bias_metric.py tests/alive/compose/test_finalize_approximation_bias_config.py -p no:randomly
   uv run --locked pytest -q tests/test_claude_md_anchors.py tests/test_documentation_hygiene.py tests/alive/compose/test_audit_contract_docs.py -p no:randomly
   uv run --locked pytest -q tests/alive/compose/test_headline.py tests/alive/compose/test_band_sensitivity.py tests/alive/compose/test_phase2b.py tests/alive/compose/test_durable.py -p no:randomly
   uv run --locked pytest -q tests/alive/compose/driver tests/alive/compose/test_outcome_store.py -p no:randomly
   ```
4. **Static**
   ```bash
   uv run --locked ruff check src tests scripts && uv run --locked ruff format --check src tests scripts
   git diff --check
   ```
5. **변이 harness** — `uv run --locked python scripts/compose_audit_mutation_harness.py`
   → T1 후 **18/18**, T4 후 **19/19**, T7b 후 **20/20**. 전부 assertion-kind **이고** 프레임이 테스트 모듈.
   `SANDBOX_CASES` arm 도 개별 확인한다.
<!-- R4-b: committed-range 하나만 보아 uncommitted/staged pinned 변경을 놓치던 공허한 diff 검사를 3면 검사로 교체했다. -->
6. **불변식 재확인**(각 wave 끝; 명령과 출력을 그대로 보고서에)
   ```bash
   git diff --name-only 595697b..HEAD -- src/alive/io.py src/alive/__init__.py \
       src/alive/compose/__init__.py uv.lock .python-version \
       src/alive/compose/approximation_bias.py configs        # → 반드시 비어야 한다
   git diff --name-only -- src/alive/io.py src/alive/__init__.py src/alive/compose/__init__.py \
       uv.lock .python-version src/alive/compose/approximation_bias.py configs
   git diff --cached --name-only -- src/alive/io.py src/alive/__init__.py src/alive/compose/__init__.py \
       uv.lock .python-version src/alive/compose/approximation_bias.py configs
                                                               # → 세 출력 모두 비어야 한다
   shasum -a 256 src/alive/compose/approximation_bias.py
   # → af0dab18086bcdf5adc3d19815ac6fa4a7695efa9f6dd1f6d58138c83f6c31c2
   wc -l CLAUDE.md                                            # → 198 (< 200)
   uv run --locked python - <<'PY'
   from pathlib import Path
   import yaml
   from alive.provenance import sha256_json
   EXPECT = "a9dc9410d1b7fe1580e179b1fa5f9f3756688e059247a6d63322edf642b44767"
   raw = yaml.safe_load(Path("configs/compose_k562_v1_phase2.yaml").read_text(encoding="utf-8"))
   digest = sha256_json(raw)
   print("config_sha256 =", digest)
   assert digest == EXPECT, f"config digest moved: {digest} != {EXPECT}"
   PY
   rg -n 'CLAUDE\.md\s+§\d' docs src tests scripts     # → 0 hits
   rg -n '\bmeasure_approximation_bias_v3\b' src scripts tests   # → T9 후 0 hits
   ```
   *사전 실측:* 위 config 명령은 이 트리에서 `a9dc9410d1b7fe…44767` 을 출력하고 assert 를 통과한다.
<!-- R4-b: 계획의 실제 상대 Markdown 링크가 생겼으므로 untracked plan까지 도는 link 검사의 비공허성을 명시했다. -->
7. **문서 이식성** — `uv run --locked pytest -q tests/test_documentation_hygiene.py -p no:randomly`.
   이 테스트의 링크 검사(`:55`)는 `git ls-files --cached --others` 로 **untracked 파일까지** 훑으므로,
   **이 플랜 Spec 절의 상대 Markdown 링크가 전부 resolve 해야 한다**(GATE-2 와 무관하게 지금부터 유효).
8. **전체 suite + 마무리**
   ```bash
   uv run --locked pytest -q
   ```
   → 기준선 **3142 passed · 3 skipped · 0 failed**(트리 `595697b`) + 이 플랜이 추가한 테스트 수.
   증가분이 정확히 설명되지 않으면 멈춘다.
   **조건부 마무리:** 이 wave 가 `docs/superpowers/COMPOSE-SEAL-READINESS.md` 의 **상태 행을 바꿨을 때만**
   그 행을 고치고 같은 커밋에 index 를 stage 한다(pre-commit 훅이 stamp 를 갱신한다). 행을 바꾸지 않았으면
   **아무것도 하지 않는다** — 문서 `:11-15` 의 갱신 트리거가 그렇게 정한다.
9. **Release boundary.** 로컬 green 은 release 신호가 아니다. COMPOSE-K562-v1 은
   **ACTIVE / RELEASE-BLOCKED / seal UNOPENED** 로 유지되며, readiness 의 오너 게이트와 pod Linux 재증명을 별도로 기다린다.

---

## 실행 순서 (wave) 와 병렬성

```text
Wave 0 (선행 측정, 커밋 없음)
  └─ T1 step 1: models.py:397 의 production assert 가 오늘 KILLED 로 점수됨을 실측·기록
     (T2 가 그 assert 를 없애면 재현 불가)

Wave 1 (harness 체인 — 같은 CASES 를 만지므로 직렬)
  T1(harness frame, 18/18)  →  T4(finalizer, M19, 19/19)  →  T7b(headline durable, M20, 20/20)
                                                    ↑
  Wave 1' (병렬 — 서로 무관, 위 체인과도 무관)          │
  ├─ T2(ruff S101 + models)        ← T1 step 1 이후    │
  ├─ T3(producer --require-admitted)                   │
  ├─ T5(CLAUDE.md 정합)                                │
  ├─ T6(HISTORICAL 규칙)                               │
  ├─ T8(protect 중복 강제 문서화)                       │
  └─ T7a(leaf 모듈 + renderer) ────────────────────────┘  (T7b 의 선행)

Wave 2  T9(v3→v4)  — T3·T4 와 같은 파일을 만지므로 그 둘 뒤에 둔다
Wave 3  GATE-1 결과 기록 — a면 변경 없음; b/c면 exact roster를 담은 별도 implementation addendum부터
Wave 4  검증 사다리 8 (전체 suite) + 조건부 readiness 마무리
```

**병렬 가능:** T2 · T3 · T5 · T6 · T7a · T8 (파일 충돌 없음).
**직렬 필수:** T1 → T4 → T7b (`scripts/compose_audit_mutation_harness.py` 의 `CASES`),
T7a → T7b, (T3, T4) → T9.
**게이트가 막는 것:** item 12 implementation addendum (GATE-1). 플랜 파일의 커밋 자체는 GATE-2.

---

## 부록 — 이 플랜이 닫지 않는 것

- **pod-gated (별도 목록):** Linux 커널 격리 재증명과 `_PENDING_REPROOF` 핀 이동, 실 `.pyz` adapter parity,
  D3 의 runtime mount/actor 증거, R1 representation 결정(raw 증명 vs log 채택), D1-c 의 real-bank λ*.
- **여섯 개 config blocker:** 이 플랜은 `configs/` 를 건드리지 않는다.
- **재론하지 않는 것:** PR #15 원장이 DROP 으로 판정한 항목들. 새 반대 근거가 나오면 결정 게이트로만 다시 연다.

<!-- R4-b: binding rulings와 수정된 실행 가능성을 재검토한 공동 저자 서명을 추가했다. -->
## 서명 (R4-b, 공동 저자 B안)

SIGNED — 이견 없음
