# Codex ↔ Claude 일일 교차감사 협력체계 — 설계 제안

> **상태: PROPOSAL (owner 승인 전) · 개정 3판.** 이 문서는 아무 계약도 발효시키지 않는다.
> 작성 2026-08-16 · 대상: `docs/GPT audit/comprehensiveaudit.md`와 그 검수 루프
> **승인된 상위 계약:** canonical audit은 `docs/GPT audit/comprehensiveaudit.md` **하나뿐이며
> 매 감사시점 전면 교체**된다. 이 제안서는 그 계약에 종속되며 이를 바꾸지 않는다.
> 관련 authority: [`CLAUDE.md#sources`](../../CLAUDE.md#sources) ·
> [`#seal`](../../CLAUDE.md#seal) · [`#provenance`](../../CLAUDE.md#provenance) ·
> [`#agent`](../../CLAUDE.md#agent)

---

## 0. 요약

**이미 있는 것:** 로컬 Codex heartbeat가 매 감사시점 ALIVE 전체를 읽기 전용으로 감사하고
`docs/GPT audit/comprehensiveaudit.md`를 전면 교체한다. 2026-08-16 04:42 EDT 첫 실행 확인
(기준 HEAD `4cd2321`, F-01…F-12 발견).

**요청:** Claude가 매일 ET 10:00에 그 파일을 읽고 검수한다.

그대로만 하면 협력체계가 아니라 **일일 독후감**이 된다. 감사 내용이 틀려도 검출되지 않고,
Codex는 자기 지적이 어떻게 처리됐는지 모르며, 같은 지적이 반복되고, 침묵(감사 실패)과
정상(문제 없음)이 구분되지 않는다. 이 제안의 핵심은 셋이다.

1. **재현 없는 확인 금지.** finding은 *명령 + 실제 출력*으로만 CONFIRMED가 된다. 서술적 동의는
   상태를 바꾸지 못한다. **기각도 같은 근거를 요구한다** — 무근거 기각은 무근거 지적의 거울상이다.
2. **감사시점은 시각이 아니라 (시각, 기준 HEAD)다.** 기준 HEAD가 현재와 다르면 그 감사는 stale이고
   승인 근거로 쓰지 않는다. 감사 §7도 같은 요구를 한다.
3. **바깥에서 검증 가능한가를 매일 묻는다.** `origin/main` 워크트리로 2-pass 검사 —
   `RECORD_GAP` = 로컬에서는 참이지만 main만으로는 검증 불가능한 주장. 이 저장소가 실제로 그 상태다.

> **개정 이력.** 1판(클라우드 Codex 가정) → 2판(로컬 전용 + 코멘트 in-place) →
> **3판: 승인된 단일 canonical 전면 교체 계약에 맞춰 축소.** 계기는 첫 감사문의
> `[HIGH, 채택 차단] F-06`이었고 그 지적은 대부분 **옳았다**(검수 기록 §10). 날짜별 audit 파일,
> `~/ALIVE-collab`, 손으로 쓰는 원장, automation 교체, release-gate 승격을 모두 철회했다.
> 단 F-06의 "코멘트 append 금지"는 **과잉해석**이었고 owner 결정으로 뒤집혔다 —
> 코멘트는 canonical 파일 안에 두되 **Claude가 매일 자기 블록을 재구성**해 누적을 막는다(§2.2).
>
> **설계 결정은 모두 해소됐다.** 마지막 결정 D-B는 owner가 `audit-log`로 정했고 orphan 브랜치 +
> 워크트리로 **구현 완료**했다(오늘 감사판 verbatim 커밋 `323ef20`).
>
> ⚠️ **남은 owner 조치 1건 — C1.** 감사 heartbeat의 실제 권한이 `:danger-full-access` +
> `approvalPolicy: never` + 샌드박스 `disabled`다. 감사는 canonical 파일만 건드렸지만 그건
> **모델의 자제이지 강제된 경계가 아니다.** read-only + `docs/GPT audit/` 쓰기 예외로 좁혀야
> "읽기 전용 감사"가 사실이 된다([§3.1](#codex-perm-gap)).

---

## 1. 무엇을 고치려는가 — 순진한 설계의 실패 모드

| # | 실패 모드 | 결과 |
|---|---|---|
| F1 | 단방향 채널 | Codex가 처리 결과를 모른다 → 같은 지적 무한 반복, 수렴 없음 |
| F2 | 측정 없는 신뢰 | 감사문의 주장이 틀려도 통과. **이 저장소의 실증 이력**: 리뷰 4회가 모두 DO NOT MERGE를 말하는 동안 CI는 계속 green이었고, 결함은 코드가 아니라 *기록*에 있었다 |
| F3 | 약한 anchor | "감사시점"만으로는 부족하다. 저장소는 그 사이 움직인다. 09:00 감사문을 10:00에 다른 SHA에서 확인/반박하면 그 판정 자체가 무의미 |
| F4 | 중복 폭증 | 매일 "전면"감사는 같은 항목을 재생산한다. 영속 dedup 없이는 매일이 1라운드 |
| F5 | 거버넌스 위험 | seal UNOPENED 저장소에서 자율 에이전트가 매일 돈다. 구조적으로 seal·config·scientific run에 닿을 수 없어야 한다 |
| F6 | 침묵 = 성공 오인 | cron 실패 시 "이상 없음"과 구분되지 않는다 |
| F7 | 합의 편향 | 둘 다 LLM이다. 틀린 것에 사이좋게 동의할 수 있다 → 불일치를 1급 상태로 보존해야 한다 |
| F8 | owner 과부하 | 매일 수십 항목이 오면 아무도 안 읽는다 → 상한과 라우팅 필요 |

---

## 2. 아키텍처

### 2.1 역할 비대칭 (핵심 설계 결정)

두 에이전트에게 같은 일을 시키지 않는다. **보이는 것이 다르므로 맡는 것도 달라야 한다.**

| | Codex (ET 09:00, 로컬 `codex exec`) | Claude (ET 10:00, 로컬 `claude -p`) |
|---|---|---|
| 샌드박스 | `-s read-only` — 저장소를 바꿀 수 없다 | 쓰기는 collab/fixes 워크트리에 한정 |
| 역할 | **감사자/기소** — 주장을 제기 | **검증자/재현 + 수리** — 재현하거나 반박 |
| 시야 | pass 1 로컬 진실 · pass 2 `origin/main`만 (§2.13) | 로컬 진실 + 명령 실행 + 측정 |
| 금지 | 자기 finding을 CLOSED로 만들기 | 자기 수정을 CLOSED로 만들기 |

역할을 나누는 근거가 "보이는 게 다르다"에서 **"묻는 게 다르다"**로 바뀐다. 둘 다 같은 기계에서
같은 파일을 보지만, Codex는 주장하고 Claude는 재현한다. 그리고 바깥 시야는 §2.13의 2-pass가
인공적으로 공급한다.

여기서 새 finding class가 하나 나온다.

> **`RECORD_GAP`** — 로컬에서는 참이지만 `origin/main`만으로는 검증 불가능한 주장.
> 누가 "못 본" 것이 아니라, **바깥에서 안 보이는 것 자체가 결함**이라는 판정.

이 저장소가 실제로 이 상태에 있다: COMPOSE 작업 8커밋이 unmerged 브랜치에 있고, 리뷰 4라운드가
모두 기록의 거짓을 지적했다. `RECORD_GAP`은 그 상태를 매일 자동으로 계측한다.

### 2.2 산출물과 흐름 — 승인된 단일 canonical 계약에 맞춘다

> **2026-08-16 F-06 반영 (CONFIRMED).** 이전 판은 `~/ALIVE-collab/audits/YYYY-MM-DD-audit.md`에
> 날짜별 immutable 파일을 쌓자고 했다. 이는 owner가 Codex와 이미 맺은 계약
> — **단일 파일 `docs/GPT audit/comprehensiveaudit.md`를 매 실행마다 전면 교체** — 과 정면 충돌한다.
> owner 지시 원문: *"매 감사시점마다 새로운 감사기록파일을 작성하는게 아니라, 기존의 감사파일을
> 전면 업데이트 하는 방식이다 … 매번 전체 내용을 전면 교체하면서, 교체 시점도 포함해라."*
> **날짜별 audit 파일 제안은 철회한다.**

```
매 감사시점  Codex heartbeat (로컬, 읽기 전용)
             ──▶  docs/GPT audit/comprehensiveaudit.md      ← 유일한 canonical audit
                  전면 교체. 헤더에 교체 시점(ET) + 감사 기준 HEAD + 브랜치 + seal 상태.
                  findings는 F-01… 식 안정 id와 [HIGH|MEDIUM|LOW] 등급, 반증 조건을 갖는다.

ET 10:00     Claude
             ──▶  preflight (결정적 사실 수집)
             ──▶  각 finding 독립 검수 → 판정 + 근거(명령+실제 출력)
             ──▶  반영할 것은 수정 브랜치로, 기각할 것은 근거와 함께 기록
```

canonical audit은 **하나뿐이고 Codex 소유다.** Claude는 그것을 읽고 검수하되 대체 canonical을
만들지 않는다.

#### D-A 해소 — 충돌이 아니었다 (owner, 2026-08-16)

owner 확인: 두 지시는 서로 다른 것을 말한다.

| 지시 | 실제 의미 |
|---|---|
| owner → Codex: "전면 업데이트" | **감사 내용**을 어제 것 뒤에 이어붙여 파일을 비대하게 만들지 말라 |
| owner → Claude: "코멘트를 남겨라" | 검토 후 **의견**을 그 감사기록에 남겨라 |

**전자는 감사 내용의 누적을 금지한 것이지, Claude의 코멘트를 금지한 것이 아니다.**
감사 §7의 *"이 파일에 annotation을 append하지 않는다"*는 Codex의 **과잉해석**이며 owner 승인 계약이
아니다. 내 검수(§10)의 `DISPUTED` 판정이 owner 결정으로 풀렸다 — 설계한 대로 작동했다.

**결론: 코멘트는 canonical 파일 안에 둔다. Codex 프롬프트 수정은 필요 없다**(아래 이유).

#### 코멘트가 전면 교체를 살아남는 법 — Claude가 재구성한다

Codex는 매 감사시점 파일을 통째로 갈아엎으므로 어제의 코멘트 블록은 사라진다. 이를 **Codex가
보존하게 만들지 않는다** — 그러면 매일 모델이 정확히 지켜주기를 기대해야 하고, 프롬프트 수정도 필요하다.
대신 **Claude가 매일 자기 블록을 재구성한다.** Codex는 Claude의 존재를 몰라도 된다.

```
ET 09:00  Codex  파일 전면 교체 (감사 내용만). 어제 코멘트 블록은 이 시점에 사라진다.

ET 10:00  Claude 1. git에서 어제 판을 꺼낸다 → 어제 코멘트 블록 확보
                 2. 오늘 감사 내용을 검수 (명령 + 실제 출력)
                 3. 아직 열려 있는 항목만 이월. 해소된 것은 버린다 (이력은 git에 있다)
                 4. 마커 아래에 오늘 코멘트 블록을 쓰고 커밋
```

```bash
git show <audit-log>:"docs/GPT audit/comprehensiveaudit.md"   # 어제의 주석 포함 판
```

그 결과 파일은 항상 **[오늘의 전체 감사] + [지금 열려 있는 코멘트]** 다. 양쪽 절반 모두 현재 상태이며
어느 쪽도 누적되지 않는다 — owner가 Codex에게 요구한 성질을 코멘트 블록도 똑같이 지킨다.

```markdown
<!-- ===== CODEX AUDIT ENDS · CLAUDE REVIEW BEGINS ===== -->

## Claude 검토 — 2026-08-17 10:0x ET
audit_replaced_at: 08/17/2026 09:00:03 EDT     # 검토한 감사판
audit_head: 4cd2321   ·   review_head: 4cd2321  # 일치 → stale 아님

### F-01 → CONFIRMED · 수정 제안
cmd:      uv run pytest -q tests/alive/compose/test_bootstrap.py
observed: gene-sharing pair가 독립으로 취급됨 (재현)
branch:   fix/pair-bootstrap-dependency        (~/ALIVE-fixes)

### F-09 → OUT_OF_SCOPE
근거:     preflight CLI UX는 seal 경계 밖 · CLAUDE.md#agent 상 owner 우선순위 판단 사항

### 이월 (어제부터 열려 있음)
- F-03 TOCTOU — 2일째 미해소. 수정 브랜치 대기 중
```

#### 지금 이 구조가 성립하지 않는다 — 파일이 untracked다 {#untracked-gap}

**2026-08-16 실측:** `git status` → `?? "docs/GPT audit/comprehensiveaudit.md"`, 커밋 이력 **0건**.

전면 교체 + 이력 없음 = **오늘 감사는 내일 아침 복구 불가능하게 사라진다.** 위 재구성도 불가능하고,
"어제 무엇을 지적했는가"를 물을 방법 자체가 없다. 이는 내 설계와 무관하게 **현재 설정의 결함**이다.
전면 교체가 안전한 이유는 애초에 "파일은 현재 상태만, 이력은 git이 보존"이기 때문인데 그 절반이 비어 있다.

**필요한 조치: 매일 검토 후 Claude가 커밋한다.** 어디에 커밋할지는 owner 결정(D-B):

- **권장 — 전용 로컬 브랜치 `audit-log`** (never pushed, 워크트리로 접근). feature 브랜치를 오염시키지
  않고, 병합을 따라다니지 않으며, 로컬 전용 방침과 일치한다.
- 대안 — 현재 체크아웃 브랜치에 그대로 커밋. 단순하지만 감사기록이 feature 브랜치에 섞이고
  나중에 main으로 병합돼 들어간다.

#### "필요 없다"에도 근거가 필요하다

어느 선택지든 이 규칙은 유지된다. **기각도 판정이므로 근거가 있어야 한다.** 근거 없는 "필요 없음"은
F2(측정 없는 신뢰)의 거울상이다 — Codex의 무근거 지적을 막아놓고 Claude의 무근거 기각을 허용하면
아무것도 나아지지 않는다. `REFUTED`·`OUT_OF_SCOPE`·`DISPUTED`도 명령+출력 또는 거버넌스 anchor를
첨부한다. 반박 가능성이 없는 기각은 대화가 아니라 묵살이다.

#### 원장은 손으로 쓰지 않는다

canonical audit이 전면 교체되므로 "어제 무엇이 있었는가"는 **git이 보존한다** — 이것이 이 계약이
성립하는 이유다. 별도 hash-chained 원장을 손으로 쓰지 않고, 필요하면 `git log -p`로 canonical
파일의 이력을 스캔해 **파생 인덱스**를 재생성한다(같은 이슈의 반복 제기, 현재 열린 항목, 말라붙음).
쓰는 곳이 하나면 어긋날 수 없다.


### 2.3 감사 identity — "감사시점"의 올바른 형태

시각만으로는 부족하다. [`CLAUDE.md#provenance`](../../CLAUDE.md#provenance)의 run identity 개념을
감사에 그대로 적용한다.

```yaml
repo_state:
  git_sha: <40-hex>        # 감사한 정확한 커밋
  branch: main
  origin_main_sha: <sha>   # pass 2 가 본 "바깥 시야"의 고정점
  dirty: false             # 사용자 작업트리가 더러웠는가 (판정의 신뢰도에 영향)
```

Claude는 자기 review에 `review_sha`를 기록하고, 두 SHA가 다르면 finding별로 staleness를 판정한다:

```bash
git diff --name-only <audit_sha>..<review_sha> -- <finding.primary_path>
```

비어 있지 않으면 그 finding은 CONFIRMED/REFUTED가 아니라 **`STALE`**이다. 이것이 "감사시점을
이정표로 삼는다"의 기계적 구현이다 — 이정표는 시각이 아니라 **(시각, SHA, 가시성)** 3튜플이다.

### 2.4 finding 스키마 (Codex가 방출해야 하는 계약)

```yaml
- id: AUD-2026-08-17-03
  fingerprint: <hex8>        # sha256(area|normalized_claim|primary_path)[:8] — 날짜 넘어 동일 이슈를 잇는 키
  area: readiness-record | seal-governance | code-correctness | doc-consistency
      | provenance | test-instrument | dependency | scope-creep
  severity: P0 | P1 | P2 | P3
  claim: "<한 문장 — 무엇이 틀렸는가>"
  primary_path: docs/superpowers/COMPOSE-SEAL-READINESS.md:412
  evidence_kind: command | file-quote | cross-reference
  evidence: "<실행한 정확한 명령과 실제 출력, 또는 인용문>"
  falsifier: "<이 finding이 틀렸음을 보여줄 관찰 — 필수>"
  prior_issue: ISSUE-<fp8> | null
```

`falsifier`가 이 스키마의 핵심이다. 반증 조건을 스스로 적게 하면 (a) 근거 없는 지적이 작성
단계에서 걸러지고, (b) Claude의 검증이 서술 판단이 아니라 **기계적 절차**가 된다.

### 2.5 판정과 상태기계

Claude의 finding별 판정:

| 판정 | 조건 | 필수 첨부 |
|---|---|---|
| `CONFIRMED` | 독립 재현 성공 | 실행 명령 + **실제 출력 발췌** |
| `REFUTED` | falsifier 성립 | 실행 명령 + 실제 출력 |
| `STALE` | audit_sha≠review_sha 이고 관련 경로가 변경됨 | diff 경로 목록 |
| `UNREPRODUCIBLE` | 증거가 부족해 재현 불가 | REQUESTS의 `REPRO` 항목 |
| `DISPUTED` | 사실은 일치, 판단이 갈림 | 양측 논거 |
| `OUT_OF_SCOPE` | seal/config/scientific run 영역 | 해당 거버넌스 anchor |

상태 전이:

```
NEW ─(재현)→ CONFIRMED ─(수정 브랜치)→ FIX_PROPOSED ─(Codex 다음 감사가 확인)→ CLOSED
 │              └─(owner 판단 필요)→ ESCALATED
 ├─(falsifier 성립)→ REFUTED ─(Codex 새 증거)→ 새 id + prior_issue 링크
 ├─(SHA 불일치)→ STALE ─(다음 감사에서 재평가)
 └─(증거 부족)→ UNREPRODUCIBLE ─(REQUESTS: REPRO)
```

**불변식 2개** (F7 대응):

- **CLOSED는 발견자가 쓰지 못한다.** Claude가 고친 것은 Codex가 다음 감사에서 확인해야 CLOSED.
  Codex가 제기한 것은 Claude 재현 없이 CONFIRMED가 되지 못한다.
- **DISPUTED는 어느 쪽도 단독 종결하지 못한다.** 새 증거(명령+출력) 또는 owner 결정만이 푼다.

### 2.6 일일 verdict는 계산된 값이다

`alive.loop.verdict.compute`와 같은 형태의 순수 함수. 산문으로 "대체로 양호" 같은 말을 쓰지 않는다.

```
BLOCKED         := CONFIRMED P0 가 1건 이상  (seal/governance/거짓기록)
ACTION_REQUIRED := CONFIRMED P1 가 1건 이상
DEGRADED        := 감사 파일 없음(AUDIT_MISSING) 또는 preflight 실패 또는 원장 chain 검증 실패
CLEAN           := 감사 존재 + preflight green + CONFIRMED P0/P1 0건
```

`DEGRADED`가 F6(침묵=성공 오인)의 해법이다. 감사가 없으면 그날은 조용한 성공이 아니라 **명시적 열화**다.

### 2.7 결정적 preflight — LLM이 사실을 두고 다투지 않게

두 에이전트가 추론을 시작하기 전에 같은 지반을 밟는다.

```json
{ "git": {"sha": "...", "branch": "...", "clean": true, "unpushed_branches": [...]},
  "tests": {"cmd": "uv run pytest -q", "exit": 0, "summary": "1347 passed, 1 skipped"},
  "lint":  {"ruff_check": "pass", "ruff_format": "pass"},
  "governance": {"sealed_access_count": 0, "ledger_chain_ok": true},
  "docs": {"broken_links": [], "stale_status_banners": [...]} }
```

이후 두 에이전트의 불일치는 **사실**이 아니라 **판단**에 국한된다. 사실 다툼은 artifact가 끝낸다.

### 2.8 얕은 전면 + 회전 심층 (F4 대응)

매일 "전면"을 깊게 하면 비싸고 반복적이다. 대신:

- **매일 얕은 전면**: preflight + 고정 체크리스트(아래 2.9) — 저렴, 회귀 탐지용.
- **매일 하나의 심층 초점**: 큐에서 회전. 날짜에서 결정적으로 유도하므로 양쪽이 조율 없이 일치한다.
  `focus = QUEUE[ (date - 2026-01-01).days % len(QUEUE) ]`

```
QUEUE = [ seal-governance, readiness-record-vs-reality, test-instrument-validity,
          doc-code-consistency, provenance-write-once, dependency-and-env,
          scope-and-claim-boundary ]
```

### 2.9 고정 체크리스트 — "기록이 거짓일 수 있다"를 상시 항목으로

이 저장소의 가장 비싼 교훈은 *기능은 멀쩡했고 기록이 거짓이었다*는 것이다. 따라서 다음은 발현적
관찰에 맡기지 않고 매일 고정으로 묻는다.

1. readiness 인덱스가 주장하는 상태가 git 실측과 일치하는가.
2. "killed/verified/passing"이라고 적힌 항목에 **이름 붙은 실패 테스트**가 실제로 대응하는가
   (exit code는 근거가 아니다).
3. 문서에 적힌 수치를 지금 재측정하면 같은 값이 나오는가.
4. main에 없는 작업을 main의 상태처럼 서술한 곳이 있는가 (**`RECORD_GAP`**).
5. seal/leakage guard 파일이 우회·완화·mock 대체되지 않았는가.

### 2.10 라우팅과 상한 (F8 대응)

| 등급 | 대상 | 처리 |
|---|---|---|
| P0 | seal·leakage·거버넌스·거짓 기록 | 즉시 owner 에스컬레이션. **자동 수정 금지** |
| P1 | 정확성 결함 | 로컬 브랜치 + TDD 수정 제안 (push·merge 금지) |
| P2 | 문서/일관성 | 주간 배치 |
| P3 | 사소 | 원장 기록만 |

일일 digest는 **상위 7건 상한**. 나머지는 원장 링크로만.

### 2.11 역방향 채널 (F1·F7 대응)

검수 결과 끝에 `## REQUESTS` 항을 붙여 다음 감사의 과제를 등록한다. 위치는 D-A가 정한다
(선택지 B면 canonical 파일 안, A면 리뷰 파일 안).

```markdown
## REQUESTS — 다음 감사에서 다룰 것
- REPRO   F-07: 재현 불가. 네가 실행한 정확한 명령을 적어라.
- RETARGET: 브랜치 compose-fold-conditioning 의 mutation-testing 기록을 재감사하라.
- REFUTE:  오늘 내가 CONFIRMED로 판정한 3건(F-01, F-04, F-06)을 반박 시도하라.
```

`REFUTE`가 F7(합의 편향)의 구조적 해법이다. 감사가 저장소만 보는 게 아니라 **상대의 판정도 본다.**
Codex는 읽기 전용이므로 코드가 아니라 **다음 감사기록으로** 답한다.

선택지 A로 운영하는 동안 이 채널이 작동하려면 Codex heartbeat 프롬프트가 리뷰 파일을 읽어야 한다 —
이는 프롬프트 수정이므로 D-A와 함께 owner가 승인한다. **승인 전까지 역방향 채널은 작동하지 않고,
루프는 단방향이다.** 그 사실을 숨기지 않고 검수 결과에 매일 명시한다.

### 2.12 release gate 승격 — 보류 (F-06 반영)

> **철회/보류.** 이전 판은 Codex를 COMPOSE의 상시 외부 검증자로 지정하고 `attestations.jsonl`을
> readiness 승격 근거로 쓰자고 제안했다. 2026-08-16 감사 F-06이 이를 과도하다고 판정했고, 그 판정이 옳다:
> **mutable local LLM 문서를 강한 release attestation으로 승격하는 것은 현재 신뢰모델을 넘어선다.**
> GU sub-project의 PASS 승격 규칙이 요구하는 것은 exact-committed-SHA 독립 리뷰이지 일일 감사가 아니다.

일일 감사는 당분간 **dev 위생 도구**로만 쓴다. seal readiness의 승격 근거로 쓰지 않는다.
이 승격을 다시 논의하려면 (a) 감사 정확도의 축적된 실측(§2.14), (b) owner의 명시적 승인,
(c) [`CLAUDE.md#sources`](../../CLAUDE.md#sources)에 이 채널을 추가하는 거버넌스 변경이 모두 필요하다.

### 2.13 실행 환경 — Codex heartbeat는 이미 로컬이다

> **D1 해소 (owner, 2026-08-16):** 일일 감사는 **로컬에서 도는 Codex heartbeat 작업**이다.
> 클라우드가 아니다. 이전 판의 "Codex를 launchd + `codex exec`로 이전한다"는 **철회한다** —
> 이미 로컬이므로 이전할 것이 없고, 감사 §7도 automation 교체를 owner 승인 없이 하지 말라고 요구한다.

이 사실이 이전 판의 걱정 하나를 통째로 없앤다. Codex가 로컬에서 돌므로 **작업트리와 unpushed
브랜치를 이미 본다.** push 네임스페이스도, 가시성 선언도 필요 없다. 실제 감사문이 그 증거다 —
`compose-activation-rank-rule` 브랜치의 HEAD를 감사 기준으로 삼았고, untracked 파일까지 열거했다.

| | Codex heartbeat (로컬, 읽기 전용) | Claude (ET 10:00, 로컬) |
|---|---|---|
| 산출 | `docs/GPT audit/comprehensiveaudit.md` 전면 교체 | 검수 결과 (§2.2 선택지 A/B) + 수정 브랜치 |
| 권한 | 읽기 전용. 이 파일 외 어떤 경로도 생성·수정하지 않는다 | 읽기 + 수정 브랜치. push·merge 없음 |
| 역할 | 감사자 — 주장을 제기 | 검증자 — 재현하거나 반박, 그리고 수리 |
| 금지 | 자기 finding을 CLOSED로 만들기 | 자기 수정을 CLOSED로 만들기 |

#### 바깥 시야는 Claude가 본다

둘 다 로컬이므로 "바깥에서 검증 가능한가"를 아무도 묻지 않게 된다. 그 질문을 **Claude 검수 단계에
넣는다** — Codex 프롬프트를 바꾸지 않으므로 승인이 필요 없다.

```bash
git worktree add /Users/jam/ALIVE-origin origin/main   # 바깥이 볼 수 있는 전부
```

**`RECORD_GAP` = 로컬에서는 참이지만 `origin/main`만으로는 검증 불가능한 주장.**
이 저장소가 실제로 그 상태에 있다 — 감사 기준 HEAD `4cd2321`은 `origin/main`보다 4커밋 앞선
브랜치이고, `compose-*` 계열 다수가 미병합이다. 검수 결과가 "main 기준으로는 아직 아무것도 아니다"를
매일 계측한다.

#### Claude 쪽 봉투

```
허용: 읽기 전체 · uv run pytest / ruff · git read-only · ~/ALIVE-fixes 워크트리 쓰기
      · §2.2에서 정해진 검수 결과 경로 쓰기
금지: 모든 git push / gh · 모든 merge · docs/GPT audit/comprehensiveaudit.md 수정(선택지 A 하에서)
      · configs/** 수정 · src/alive/compose/{gates,freeze,outcome_store}.py 및
        driver/seal_boundary.py 수정 · CLAUDE.md 수정
      · scientific CLI(prepare/fit/develop/calibrate/evaluate-once) 실행 · seal 접근
```

**봉투는 비대칭이 맞다.** 역할이 다르기 때문이다 — Codex는 주장만 하고, Claude만 고친다.

#### 같은 기계를 공유할 때

1. **순서.** Codex heartbeat가 먼저, Claude 검수가 나중(ET 10:00). 겹치면 나중 잡은 `DEGRADED`로
   기록하고 종료한다.
2. **기준 HEAD 일치 확인.** 감사문의 "감사 기준 HEAD"가 현재 HEAD와 다르면 그 감사는 stale이다.
   감사 §7이 같은 요구를 한다. 2026-08-16 실측: 둘 다 `4cd2321` — **일치, stale 아님.**
3. **기계가 꺼져 있던 날.** 그날의 감사는 없다. 침묵과 구분해 `MISSED`로 기록한다(F6).

### 2.14 주간 메타리뷰 — 협력체계 자체를 측정

7일 롤업(`~/ALIVE-collab/weekly/YYYY-Www-meta-review.md`):

- Codex precision = CONFIRMED / (CONFIRMED + REFUTED)
- Claude 수정 품질 = Codex가 다음 감사에서 되돌린 수정 비율
- 미결 중앙시간, 반복 영역 top-3, DISPUTED 잔량

precision이 낮으면 감사 프롬프트를 조인다. 이 지표가 없으면 시스템이 작동하는지 알 방법이 없다.

---

## 3. Codex 쪽에 필요한 설정 (heartbeat)

Codex는 **읽기 전용 감사자**다. 아래는 그 역할이 도구 수준에서 성립하기 위한 설정이며,
Claude는 여기에 손댈 수 없다 — **owner가 Codex 데스크톱 앱에서 직접 설정한다.**

### 3.1 지금 상태 (2026-08-16 실측) — 읽기 전용이 아니다 {#codex-perm-gap}

감사 스레드 `019eeba1-bdf5-7f53`(cwd `/Users/jam/ALIVE`, model `gpt-5.6-sol`)의 실제 권한:

| 항목 | 현재 값 | 뜻 |
|---|---|---|
| heartbeat permission profile | `:danger-full-access` | 파일시스템 전체 쓰기 가능 |
| `approvalPolicy` | `never` | 무인 실행, 아무것도 묻지 않음 |
| thread `sandbox_policy` | `{"type":"disabled"}` | 샌드박스 없음 |
| network | 제한 없음 | 외부 접근 가능 |

**감사가 실제로 한 일과 할 수 있었던 일이 다르다.** 감사 §8은 canonical 파일 하나만 건드렸다고
밝혔고 그 진술은 사실로 보이지만, 그것은 **모델의 자제이지 강제된 경계가 아니다.**
[`CLAUDE.md#enforcement`](../../CLAUDE.md#enforcement)가 말하는 그대로다 — 규범을 적는 것과
guard가 집행하는 것은 다르다. seal이 UNOPENED인 저장소에서 매일 무인으로 도는 작업이
`configs/`·seal guard·`artifacts/`에 쓸 수 있는 상태로 남아 있을 이유가 없다.

같은 저장소의 다른 스레드(`019f7730`)가 **이 앱이 세밀한 정책을 지원한다는 증거**다:
`managed` 파일시스템에 root=read, `/Users/jam/ALIVE`=write, `/tmp`=write, `.git`=read,
`network: restricted`가 실제로 걸려 있다. 즉 아래 요구는 새 기능이 아니라 설정 변경이다.

### 3.2 요구 설정

| 항목 | 요구 값 | 이유 |
|---|---|---|
| 파일시스템 | root = **read** · `/Users/jam/ALIVE` = **read** | 전수 감사는 읽기만 하면 된다 |
| 쓰기 예외 ① | `/Users/jam/ALIVE/docs/GPT audit/` = **write** | canonical 감사기록을 쓸 유일한 경로 |
| 쓰기 예외 ② | `/tmp` (및 `TMPDIR`) = **write** | 감사가 격리 mutation 검증을 `/tmp` 사본에서 수행한다(감사문 §5) |
| network | **restricted** | 저장소 감사에 외부 접근이 필요 없다 |
| `approvalPolicy` | `never` 유지 가능 | 무인이어야 하므로. 단 **위 샌드박스가 전제**다 |

이 설정이면 owner가 말한 "읽기 전용 전수 감사"가 **부탁이 아니라 사실**이 된다. 감사가 실수로든
프롬프트 오염으로든 `configs/`·`src/`·seal guard를 건드릴 경로 자체가 사라진다.

> Claude는 `~/.codex/`의 앱 상태를 **편집하지 않는다.** 실행 중인 다른 앱의 사설 상태이며
> 잘못 쓰면 손상된다. 이 변경은 앱 UI에서 owner가 한다.

### 3.3 프롬프트 계약 — 이미 지켜지고 있는 것

첫 감사문이 아래를 모두 갖췄다. **바꿀 것이 없다.** 규격으로 고정만 한다.

- 헤더에 **전체 교체 시점(ET)** · **감사 기준 HEAD** · 브랜치 · 원격 상태 · **seal 상태**.
- finding마다 안정 id(`F-01`…), 등급(`HIGH`/`MEDIUM`/`LOW`), **근거**, **영향**,
  그리고 **필수 개선 / 반증 조건**. 반증 조건이 있어야 Claude의 검증이 판단이 아니라 절차가 된다.
- 파일은 이전 내용을 남기지 않고 **전면 교체**한다(누적 금지).
- 마지막에 **작업트리·비변경 보증** — 무엇을 만들고 무엇을 안 건드렸는지.

### 3.4 Codex가 하지 않아야 하는 것

- canonical 파일 **외 어떤 경로도** 생성·수정·삭제·stage·commit하지 않는다 (이미 준수 중).
- **마커 아래 Claude 코멘트 구역을 신경 쓰지 않아도 된다.** 전면 교체가 그것을 지워도 무방하다 —
  Claude가 git에서 복원해 매일 재구성한다(§2.2). **Codex 프롬프트 수정은 필요 없다.**
- seal을 열거나 sealed outcome에 접근하지 않는다 (이미 준수 중).
- 자기 finding을 CLOSED로 만들지 않는다.

### 3.5 선택 개선 (지금은 불필요)

`codex exec --output-schema`로 구조화 JSON을 강제하는 안은 **보류**한다. 실제 감사문이 이미
파싱 가능한 규격을 지키고 있고, heartbeat는 CLI가 아니라 데스크톱 앱 기능이라 그 플래그를 쓸 수
없다. 산문 파싱이 실제로 흔들리기 시작하면 그때 다시 본다.

---

## 4. Claude Code 쪽에 필요한 설정

Claude는 **검증자 겸 수리자**다. 신규 automation은 여기 하나뿐이다.

### 4.1 워크트리 3개

```bash
git worktree add --orphan -b audit-log /Users/jam/ALIVE-audit-log   # ✅ 생성 완료
git worktree add            /Users/jam/ALIVE-origin  origin/main     # 미생성
git worktree add -b collab-fixes /Users/jam/ALIVE-fixes              # 미생성
```

| 워크트리 | 용도 | 상태 |
|---|---|---|
| `/Users/jam/ALIVE-audit-log` | orphan 브랜치 `audit-log` — 감사판 이력. **never pushed** | ✅ `323ef20`, `e00d3e2` |
| `/Users/jam/ALIVE-origin` | `origin/main` 고정 — `RECORD_GAP` 2-pass 검사용 | 미생성 |
| `/Users/jam/ALIVE-fixes` | 수정 제안 브랜치 전용. **Claude만** | 미생성 |

`/Users/jam/ALIVE`(사용자 체크아웃)는 **읽기와 canonical 파일 코멘트 추가 외에 건드리지 않는다.**

### 4.2 launchd — ET 10:00, DST 무보수 흡수

머신은 KST다. ET 10:00은 EDT 기간 23:00 KST, EST 기간 00:00 KST(익일)로 **이동한다.**
plist에 두 시각을 등록하고 래퍼가 ET 시각으로 자기검증하면 연 2회 수동 조정이 사라진다.

`~/Library/LaunchAgents/com.alive.collab.audit-review.plist` (미래 산출물)

```xml
<key>StartCalendarInterval</key>
<array>
  <dict><key>Hour</key><integer>23</integer><key>Minute</key><integer>12</integer></dict>
  <dict><key>Hour</key><integer>0</integer> <key>Minute</key><integer>12</integer></dict>
</array>
```

분은 :00/:30을 피한다. 절전 중이었으면 launchd가 기상 시 누락분을 실행한다.

### 4.3 래퍼 스크립트

`/Users/jam/ALIVE-audit-log/bin/daily_review.sh` (미래 산출물) — 감사 이력과 함께 버전관리한다.

```bash
[[ "$(TZ=America/New_York date +%H)" == "10" ]] || exit 0   # 나머지 한 번은 무조건 no-op
```

이후 락 파일로 중복 실행을 막고, `claude -p`를 §4.5 봉투로 호출하며, 종료코드와 로그를 남긴다.

### 4.4 검토 절차 (매일)

1. canonical 파일의 **교체 시점**과 **감사 기준 HEAD**를 먼저 읽는다.
2. 기준 HEAD ≠ 현재 HEAD → 그 감사는 **stale**. 승인 근거로 쓰지 않고 다음 갱신을 요구한다.
   파일이 없거나 교체 시점이 24시간 이상 지났으면 `MISSED`/`DEGRADED`로 기록한다(F6).
3. **오늘 감사판을 verbatim으로 커밋한다** — `audit(codex): …`. 검토 코멘트를 섞지 않는다.
4. preflight 수집(pytest·ruff·git·seal 접근수) — 사실 다툼을 artifact가 끝낸다.
5. 직전 `review(claude)` 커밋에서 어제 코멘트 블록을 꺼낸다.
6. finding별 독립 검증: 근거가 현재 HEAD에서도 유효한가, 반증 조건이 실제 test/artifact로 성립하는가.
   **명령과 실제 출력을 남긴다.** 기각에도 같은 수준의 근거를 요구한다.
7. `/Users/jam/ALIVE-origin`으로 `RECORD_GAP` 검사(§2.13).
8. 반영: `/Users/jam/ALIVE-fixes`의 브랜치. 열린 항목만 이월해 마커 아래 코멘트 블록을 쓰고
   `review(claude): …`로 커밋한다.

### 4.5 능력 봉투 — `--settings` deny로 강제

```bash
claude -p --model fable --permission-mode acceptEdits \
       --settings /Users/jam/ALIVE-audit-log/review-settings.json \
       < /Users/jam/ALIVE-audit-log/prompts/review.md
```

```
허용: 읽기 전체 · uv run pytest / ruff · git read-only
      · ALIVE-audit-log / ALIVE-fixes 워크트리 쓰기 · canonical 파일의 마커 아래 구역
금지: 모든 git push / gh · 모든 merge · configs/** 수정
      · src/alive/compose/{gates,freeze,outcome_store}.py · driver/seal_boundary.py 수정
      · CLAUDE.md 수정 · canonical 파일의 마커 **위** 구역 수정
      · scientific CLI(prepare/fit/develop/calibrate/evaluate-once) 실행 · seal 접근
```

> `--settings`·`--permission-mode`·`--disallowedTools` 플래그 존재는 확인했다.
> **`permissions.deny` 항목의 정확한 패턴 문법은 구현 시 설정 스키마로 확인한다** —
> 현재 `~/.claude/settings.json`에는 `permissions` 키가 없어 실물 예시가 없다.

### 4.6 봉투가 비대칭인 이유

Codex는 주장만 하고(§3, read-only), Claude만 고친다(격리 워크트리). **역할이 다르므로 봉투도 다르다.**
이전 판의 "봉투를 두 에이전트에 대칭으로"는 Codex가 수정한다는 전제 위에 있었고 그 전제가 철회됐다.

### 4.7 비용

일 1회. 얕은 전면(preflight + 고정 체크리스트 §2.9) + 회전 심층 1건(§2.8) + finding 재현 명령.
전면 심층을 매일 돌리지 않는 것이 비용 통제의 본체다.

---

## 5. 설정 요약 — 누가 무엇을 하는가

| # | 항목 | 담당 | 상태 |
|---|---|---|---|
| C1 | heartbeat 샌드박스를 read-only + `docs/GPT audit/` 쓰기 예외로 축소 | **owner** (Codex 앱 UI) | owner 조치 알림. **2026-08-17 00:02 KST 재확인 시 `activePermissionProfile`만 `null`로 바뀌고 `sandboxPolicy dangerFullAccess` · `approvalPolicy never` · thread `sandbox_policy disabled`는 그대로** — 설정이 다른 곳에 반영됐을 수 있어 **결과 수준(다음 감사판의 비변경 보증 + 실제 작업트리 변화)으로 재확인**한다 |
| C2 | network `restricted` | **owner** | 위와 동일 |
| C3 | 감사문 규격(교체 시점·기준 HEAD·seal·반증 조건) | Codex | ✅ 이미 준수 |
| C4 | canonical 외 경로 비변경 | Codex | ✅ 준수(§8 보증). 단 강제가 아니라 자제 — C1 이 이를 강제로 바꾼다 |
| K1 | `audit-log` orphan 브랜치 + 워크트리 | Claude | ✅ 완료 (`323ef20`, `e00d3e2`) |
| K2 | `ALIVE-origin`(@`origin/main`) · `ALIVE-fixes`(`collab-fixes`) 워크트리 | Claude | ✅ 완료 |
| K3 | launchd plist + 래퍼 + `review-settings.json` + `verify_marker.py` + 프롬프트 | Claude | ✅ 완료 (`bc8eeb0`), LaunchAgent bootstrap 완료 |
| K4 | 첫 검토 | Claude | ✅ **HIGH 6건(F-01~F-06) 전부 재현** + F-10/F-11/F-12 확인 + RECORD_GAP-01 신규. F-07·F-08·F-09만 이월 |

**K1~K4 완료. 남은 것은 C1/C2의 실효 확인 하나다.**

무결성 가드 실측(3 케이스): 무변조 `exit 0` · 마커 위 1바이트 변조 `exit 1` · 마커 부재 `SKIP exit 0`.
ET 가드 실측: `ET 11 시 — 대상 시각 아님. no-op 종료.`

---

## 6. 브랜치·경로 배치

```
docs/GPT audit/comprehensiveaudit.md   ← 유일한 canonical audit
     [마커 위]  Codex 소유 — 매 감사시점 전면 교체
     [마커 아래] Claude 소유 — 검토 코멘트. 매일 재구성하며 열린 항목만 이월
브랜치 audit-log (orphan, never pushed) ← 이 파일의 일별 커밋 이력 ✅ 생성됨
     워크트리 /Users/jam/ALIVE-audit-log · audit(codex) / review(claude) 2단 커밋
/Users/jam/ALIVE-origin                ← worktree @ origin/main. RECORD_GAP 검사용 (미래)
/Users/jam/ALIVE-fixes                 ← worktree. Claude 수정 브랜치 전용 (미래)
~/Library/LaunchAgents/…claude-review.plist    ← ET 10:00 검수 잡 (미래)
```

**파일은 어느 쪽도 누적되지 않는다.** 감사 내용은 Codex가, 코멘트는 Claude가 매일 현재 상태로
갈아 쓴다. 이력은 전부 git이 보존한다 — owner가 Codex에게 요구한 성질을 두 절반 모두 지킨다.

`docs/GPT audit/`의 기존 2건(2026-07-19자)은 손대지 않는다 — 이미 커밋된 역사적 기록이다.
경로 이름의 공백은 승인된 계약의 일부이므로 **개명 제안을 철회한다**(이전 D4). 스크립트에서 인용부호를 쓴다.

**이전 판에서 철회된 것 전부**

| 철회 | 사유 |
|---|---|
| `~/ALIVE-collab` 워크트리 + 날짜별 audit 파일 | 단일 canonical 전면 교체 계약 위반 (F-06) |
| 손으로 쓰는 hash-chained 원장 | canonical이 전면 교체되므로 이력은 **git이 보존**한다 |
| `collab/{claude,codex}/*` push 네임스페이스 · CI 봉투 | 로컬 전용 결정으로 소멸 |
| Codex를 launchd + `codex exec`로 이전 | 이미 로컬 heartbeat다 (D1) + 감사 §7이 automation 교체 금지 |
| Codex 수정 브랜치 권한 | owner 결정: Codex는 읽기 전용 |
| `attestations.jsonl` → release gate 승격 | 신뢰모델 초과 (F-06), §2.12 보류 |
| `docs/GPT audit/` 개명 | 승인된 계약의 일부 |

남은 것은 **Claude의 ET 10:00 검수 잡 하나**와 그 결과를 어디에 쓸지(§2.2 A/B)뿐이다.
설계가 이전 판의 1/3 이하로 줄었고, 줄어든 이유는 전부 "이미 승인된 계약이 그 자리를 채우고 있어서"다.

---

## 7. 결정 기록

| # | 결정 | 상태 |
|---|---|---|
| D-B | 감사기록을 어느 브랜치에 커밋하는가 | **해소 (owner, 2026-08-16): `audit-log`.** orphan 브랜치 + 워크트리 `/Users/jam/ALIVE-audit-log`로 구현 완료. never pushed |
| D-A | 검토 코멘트를 어디에 쓰는가 | **해소:** canonical 파일 안. 두 지시는 충돌이 아니었다(owner, 2026-08-16). Codex 프롬프트 수정 불필요 |
| D1 | Codex 감사가 어디서 도는가 | **해소:** 로컬 heartbeat, 읽기 전용 |
| D2 | 각 잡의 권한 | **해소:** Codex 읽기 전용, 수정은 Claude만 |
| D3 | 파생 인덱스 | 불필요. `git log -p "docs/GPT audit/comprehensiveaudit.md"` 하나가 연속성·이력·diff를 전부 준다 |
| D6 | `--output-schema` 강제 | **해소:** 불필요. 실제 감사문이 이미 `F-01`… 안정 id + 등급 + 반증 조건 규격을 지킨다 |

> **결정 이력 (지우지 않는다):** ①push 금지 → ②`collab/*` push 허용 → ③로컬 전용이라 push 불필요 →
> ④Codex 읽기 전용·코멘트 응답 → ⑤단일 canonical 전면 교체 계약 준수 →
> ⑥**코멘트는 canonical 안에 두되 Claude가 매일 재구성(D-A 해소), 남은 것은 커밋 위치(D-B)뿐.**

---

## 8. 단계별 구현

| 단계 | 내용 | 자동화 |
|---|---|---|
| ~~P0~~ | ~~오늘 감사판을 커밋해 이력을 시작한다~~ → **완료 2026-08-16.** orphan 브랜치 `audit-log` + 워크트리 `/Users/jam/ALIVE-audit-log`; `323ef20` verbatim 감사판, `e00d3e2` 브랜치 README | 없음 |
| P1 | 검수 절차(§4.4)를 **수동으로 3일 시범** — 판정·근거·이월 형식을 실제 감사문으로 검증 | 없음 |
| P2 | launchd + 래퍼 + 봉투 + `ALIVE-origin`/`ALIVE-fixes` 워크트리 | ET 10:00 자동 |
| P3 | 주간 메타리뷰(§2.14) — 감사 정확도 실측 | — |

**P0 완료.** 다음 전면 교체(오늘 22:00 KST)가 와도 오늘 감사(F-01~F-12)는 `audit-log`에 남는다.
커밋은 **verbatim** — Codex가 쓴 그대로이며 검토 코멘트를 섞지 않았다. 검토는 별도
`review(claude)` 커밋으로 마커 아래에 덧붙인다. sha256 `6bb58c96…`으로 원본 동일성을 확인했다.

**P1을 수동으로 먼저 돌리는 이유**: 첫 감사문 하나로 이미 제 설계의 전제가 두 번 무너졌다
(날짜별 파일 가정, 그리고 append 금지 오해). 자동화를 먼저 걸었다면 틀린 잡이 매일 돌았을 것이다.

**Codex 프롬프트는 건드리지 않는다.** Claude가 자기 블록을 재구성하므로 Codex는 Claude의 존재를
몰라도 된다. 역방향 채널(§2.11)은 Codex가 파일 하단을 읽게 되는 순간 저절로 성립한다 —
감사가 파일 전체를 읽는다면 이미 읽고 있다.

---

## 9. 이 체계가 지키지 않는 것 (비-주장)

- 과학적 verdict가 아니다. 이 루프는 **seal을 열거나 읽거나 닫지 않는다**
  ([`CLAUDE.md#seal`](../../CLAUDE.md#seal)). 검수 통과는 과학적 성공을 뜻하지 않는다.
- **release readiness의 근거가 아니다**(§2.12 보류). GU의 PASS 승격이 요구하는 것은
  exact-committed-SHA 독립 리뷰이지 일일 감사가 아니다.
- 독립 감사기관이 아니다. 두 LLM의 교차검증이며, 상호 재현이 신뢰도를 *제한적으로만* 올린다.
  §2.14의 정확도 실측이 실제 신뢰 수준을 알려주는 유일한 근거다.
- 아무것도 push하지 않는다. merge와 `main` 기록 변경은 항상 owner 행위로 남는다.
- `~/ALIVE-fixes`의 브랜치는 *제안*이지 승인이 아니다.
- canonical audit을 대체하지 않는다. `docs/GPT audit/comprehensiveaudit.md`가 유일한 canonical이다.

---

## 10. 부록 — 2026-08-16 첫 검수 (F-06)

첫 canonical 감사문이 이 제안서를 `[HIGH, 채택 차단] F-06`으로 지적했다. 계약대로 독립 검수한다.

**판정: `CONFIRMED`.** Codex가 옳고 제안서가 틀렸다.

| 검증 | 명령 / 관찰 |
|---|---|
| 감사 기준 HEAD가 현재와 일치하는가 | `git rev-parse HEAD` → `4cd232145657354bafeca03b946c67463fbc693e`, 감사문 기재와 동일. **stale 아님** |
| 승인된 계약이 실제로 전면 교체인가 | owner 지시 원문 확인: *"기존의 감사파일을 전면 업데이트 하는 방식 … 파일 이름은 comprehensiveaudit"* — 참 |
| 제안서가 그와 충돌하는가 | 이전 판이 `~/ALIVE-collab/audits/YYYY-MM-DD-audit.md` 날짜별 immutable 파일을 제안 — 참 |
| release-gate 승격이 과도한가 | `CLAUDE.md#sources`에 이 채널이 없고 GU 승격 규칙은 exact-SHA 독립 리뷰를 요구 — 참 |

**반영:** 날짜별 audit 파일·`~/ALIVE-collab`·손으로 쓰는 원장·automation 교체·release-gate 승격을
모두 철회했다(§6 철회 표).

**부분 이견 — `DISPUTED` 1건 → owner 결정으로 해소.** F-06의 필수 개선 ②*"이 파일에 annotation을
append하지 않는다"*는 owner 승인 계약이 아니라 **Codex의 과잉해석**이었다. owner 확인(2026-08-16):
"전면 업데이트"는 *감사 내용*이 날마다 이어붙어 파일이 비대해지는 것을 막으라는 뜻이지, Claude의
코멘트를 금지한 것이 아니다. **따라서 F-06 ②는 REFUTED**이고, ①(계약 준수)과 ③(automation 교체 보류)은
CONFIRMED로 남는다.

이 한 건이 설계 규칙 하나를 실증했다 — *"DISPUTED는 어느 쪽도 단독 종결하지 못한다. 새 증거 또는
owner 결정만이 푼다."* 내가 Codex 말을 그대로 받아 코멘트를 포기했다면 owner 의도를 잃었을 것이고,
반대로 내 해석을 밀어붙였다면 승인된 계약을 위반했을 것이다. **올려서 물은 것이 옳았다.**

**신규 발견 (내 쪽) — canonical 파일이 untracked다.** `git log -- "docs/GPT audit/comprehensiveaudit.md"`
→ 0건. 전면 교체 + 이력 없음이면 오늘 감사는 내일 아침 복구 불가능하게 사라진다. 감사 §8이
"이 파일 외 아무것도 stage/commit하지 않았다"고 밝힌 것과 정합적이며, **감사 자신은 이 결함을
보고하지 않았다**(자기 산출물의 지속성은 감사 범위 밖이었다). D-B로 올린다.

**미검수:** F-01~F-05, F-07~F-12는 아직 검수하지 않았다. P1 시범에서 다룬다.
