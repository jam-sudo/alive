# 오너 위임 판단 4건 — Implementation Plan

> **For agentic workers:** task 단위로 실행한다. 각 task 는 **실패 테스트 → red 실측 → 구현 → green 실측 → 커밋** 순서를 지키고,
> 새 테스트마다 "참일 때와 거짓일 때 출력이 다른지" 를 실제로 실행해 보고서에 남긴다. kill 은 **이름 붙은 테스트의 own-frame
> `AssertionError`** 로만 인정한다(production frame 에서 난 실패·guard mock 은 kill 이 아니다). Step 은 checkbox 문법을 쓴다.

**작성:** 2026-09-10 · **기준 트리:** `main` `21bc56a` · **브랜치:** `compose-owner-judgments-2026-09-10`
**위임 근거:** 오너 서면 지시 2026-09-10 "오너 판단 너에게 위임한다" — 대상은 2026-09-06 검토가 남긴 오너 판단 4건
(§6.1 위임 서명의 지위 · §6.3 crash 뒤 unbound sidecar · sealed roster 를 split manifest 에서 유도 · review-state ledger 의 slot ID·run_id).

**Goal:** 네 판단을 실측 위에서 내리고, 그 결과를 저장소가 잃는 것 없이 코드·문서로 고정한다. `configs/` 는 건드리지 않고
(`config_sha256` `a9dc9410…` 불변), seal 은 열지 않으며, 어떤 guard 도 약화하지 않는다.

**Architecture:** (1) 판단 기록은 날짜 붙은 결정문 하나(`docs/superpowers/2026-09-10-compose-owner-delegated-judgments.md`)와
기존 amendments 문서의 재확인 문단으로 남긴다. (2) §6.3 은 write-once 를 유지한 채 CLI `reclaim-unbound` 하위명령으로
"손으로 정리" 만 없앤다. (3) sealed roster 는 caller 입력이 아니라 fit-role artifact 가 가리키는 **split manifest**
(`verify_split_manifest` 로 digest 대조)에서 유도한다. (4) slot ID·run_id 는 협력 루프의 로컬 전용 ledger 에 5·6열로 덧붙인다
— 이 저장소 밖(`audit-log` 워크트리) 이며 git 에 올리지 않는다.

**Tech Stack:** Python 3.12 · `uv run --locked` · pytest · Ruff. bash(협력 루프 latch 스크립트).

**Spec:** [split manifest](../../src/alive/compose/split.py) `build_split_manifest`/`verify_split_manifest` ·
[smoke evidence](../../src/alive/compose/smoke_evidence.py) `build_smoke_pair_roster`/`publish_promotion` ·
[amendments record](../2026-08-30-compose-spec-10-5-amendments.md) · [readiness](../COMPOSE-SEAL-READINESS.md) ·
governance [CLAUDE.md](../../../CLAUDE.md#seal-immutability) (`#seal-immutability`, `#provenance`, `#agent`).

---

## Global Constraints

1. **`configs/` 변경 금지** — `config_sha256` `a9dc9410d1b7fe1580e179b1fa5f9f3756688e059247a6d63322edf642b44767` 불변(사다리에서 assert).
2. **byte-pinned 무변경:** `src/alive/io.py`, `src/alive/__init__.py`, `src/alive/compose/__init__.py`, `uv.lock`, `.python-version`,
   `src/alive/compose/approximation_bias.py`(`af0dab18…`). `_ISOLATION_CLOSURE` 파일도 대상 아님 — 이 플랜이 만지는
   `smoke_evidence.py`·`compose_smoke_evidence.py`·`build_dev_smoke_payload.py`·`split.py`(읽기만) 는 closure 밖임을 T2 에서 실측.
3. **seal UNOPENED · RELEASE-BLOCKED 유지.** evidence 디렉터리(`docs/activation-evidence/compose/`)의 write-once 는 유지한다 — reclaim 은
   **lock 이 참조하지 않고 lock 이 INCOMPLETE 일 때의 sidecar 만** 지운다. run_dir·seal audit·terminal 에는 손대지 않는다.
4. **guard 파일은 추가만.** `publish_promotion` 의 FileExistsError 거부는 그대로다(reclaim 은 별도 경로).
5. **`CLAUDE.md` 무변경.** 문서에서 `CLAUDE.md §N` 참조 금지 → `#anchor`. 협력 도구·workflow 서술을 저장소 문서에 새로 쓰지 않는다
   (T4 는 저장소 밖 워크트리에서만 한다).
6. **서명된 결정문 문장은 재작성하지 않는다** — 날짜 붙은 문단만.
7. **새 테스트마다 참/거짓 실측** + own-frame kill. 새 negative 는 capture-and-assert(타입·메시지 단언).
8. Python·pytest·Ruff 는 `uv run --locked`. 커밋 trailer 두 줄:
   ```
   Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
   Claude-Session: https://claude.ai/code/session_01Gh4k8KQJtMwgTV1YAZhYS2
   ```
9. push·merge 는 코디네이터가 한다(브랜치 → PR → 독립 리뷰 → 병합 — 오너 승인 경로).

---

## §0 판단 (실측 → 판정)

| # | 질문 | 실측 | 판정 | 비용(틀렸을 때) |
|---|---|---|---|---|
| 1 | §6.1 — B·C 의 위임 서명과 A 의 서명 후 정정을 오너가 자기 손으로 재서명해야 하는가 | `2026-08-30-compose-spec-10-5-amendments.md:9,22-24,46-49`: A 는 오너 서명(09-03) + 위임 정정(09-05), B·C 는 위임 서명(09-05). 사실 관계 이견 없음(Codex M1 도 사실은 합의, 절차만 권고). 오너가 2026-09-10 에 이 판단 자체를 서면 위임 | **재서명 불요.** 오너의 09-10 위임이 곧 재확인이다 — amendments 문서에 날짜 붙은 "재확인 기록" 문단 추가, DISPUTED 종결. 오너가 자기 손 서명을 원하면 **추가**로 넣으면 되고 아무것도 되돌리지 않는다 | 0 (문서) |
| 2 | §6.3 — crash 뒤 unbound sidecar: fail-closed+수동 정리 vs atomic directory publish | `publish_promotion` 은 sidecar 를 write-once 로 먼저, lock 을 atomic rename 으로 **마지막**에 쓴다(`smoke_evidence.py:753-`); 그 사이 crash → sidecar 만 남고 재실행은 `FileExistsError` 로 거부 → 손으로 지워야 했다. evidence 디렉터리는 다른 committed 파일과 공존하므로 directory swap 은 과하다 | **현행 유지 + `reclaim-unbound`** 하위명령: `LOCK_NAME` 이 INCOMPLETE(또는 `evidence_status != COMPLETE`) 이고 lock 의 어느 필드도 참조하지 않는, **이 promotion 이 만들 이름의** sidecar 만 제거. 실패 주입 테스트로 고정. write-once 불변식 유지 | S — 하위명령 하나; 조건이 틀리면 지우지 말아야 할 파일을 지울 수 있으므로 세 조건을 각각 negative 로 핀 |
| 3 | sealed roster 를 split manifest 에서 유도할 것인가(seal-guard 경로 착수) | `build_smoke_pair_roster` 는 `sealed_pair_ids` 를 **caller 에게서** 받고 training roster 와 overlap 만 센다(`:189-289`); artifact block 의 `pair_manifest_sha256` 은 scientific 경로에서 split manifest 의 `checksum`(`phase2b.py:710`)이고 driver 는 `carrier_loader._preseal_json(spec, "pair_manifest")` 로 그 manifest 를 읽는다. 결속 코드 0(09/06 검토 (b) 인정) | **승인·구현.** manifest 를 `verify_split_manifest` 로 검증하고 그 checksum 이 artifact block 의 `pair_manifest_sha256` 과 같을 때만 sealed roster = manifest 의 두 sealed role. caller 의 `sealed_pair_ids` 는 **optional 교차검증**(주어지면 유도값과 정확히 같아야 함)으로 강등. dev-smoke 의 sentinel digest 경로는 promotion 불가임을 명시(원래 release evidence 가 아니다) | M — inputs bundle 에 `pair_manifest` 경로 추가; 테스트 fixture 가 실제 tiny manifest 를 만들어야 함 |
| 4 | review-state ledger 에 slot ID·run_id(M7) | ledger = `ALIVE-audit-log/logs/review-state.tsv`, 4열 `(ET date, time, state, detail)`; reader 는 `$1`·`$3` 만 본다(`bin/review_latch.sh`). 루프는 09/05 이후 Codex 판 부재로 DEGRADED_STALE_AUDIT 상태 | **구현(로컬 전용).** `latch_record` 가 5열 `slot_id`(`<ET date>T<ET hour>`) · 6열 `run_id`(launchd 기동별 uuid; 없으면 `$$-epoch`) 를 덧붙인다. reader 무변경(호환). `audit-log` 워크트리에 커밋, **push 금지**. Codex 침묵 자체는 이 플랜 밖(오너 통지) | S — 열 추가; 틀리면 reader 가 못 읽는 것이 아니라 열이 비는 것 |

**게이트 없음.** 네 판단 모두 오너가 위임했고, 어느 것도 config·seal·claim 을 움직이지 않는다.

---

## Task 1 — 판단 기록 (item 1 + 결정문)

**Files**
- Create: `docs/superpowers/2026-09-10-compose-owner-delegated-judgments.md`
- Modify(문단 추가만): `docs/superpowers/2026-08-30-compose-spec-10-5-amendments.md` — "Delegation record — 2026-09-05" 문단 뒤에
  `**Re-affirmation record — 2026-09-10.**` 문단; 헤더 `:9` 의 STATUS 줄은 그대로 두고 그 아래 한 줄 인용 추가
- Modify(행 추가만): `docs/superpowers/COMPOSE-SEAL-READINESS.md` "열린 결정" 표 — 4건이 위임 판정으로 닫혔음을 한 행으로(상태 행 변경이므로 pre-commit 훅이 stamp 를 갱신한다)
- Test: `tests/alive/compose/test_audit_contract_docs.py` 에 named test 추가(아래)

**Steps**
- [ ] 1. 실패 테스트 `test_the_delegated_judgments_record_names_all_four_and_their_basis`: 결정문이 존재하고 §0 의 네 질문 id 와 `위임 근거` 문구, 각 판정 토큰(`재서명 불요` · `reclaim-unbound` · `verify_split_manifest` · `slot_id`) 을 담으며, amendments 문서에 `Re-affirmation record — 2026-09-10` 가 있고 서명 표 세 줄(`:22-24`) 이 byte 불변임(base `21bc56a` 의 텍스트를 테스트 상수로)을 단언. red 확인.
- [ ] 2. 결정문 작성: §0 표를 옮기고 각 항목에 실측 명령·출력 요지, 판정, 비용, 구현 task 를 적는다. 협력 도구·workflow 서술 금지(루프 ledger 는 "로컬 전용 ledger" 로만).
- [ ] 3. amendments 재확인 문단 + readiness 행. green 확인: `uv run --locked pytest -q tests/alive/compose/test_audit_contract_docs.py tests/test_claude_md_anchors.py tests/test_documentation_hygiene.py -p no:randomly`
- [ ] 4. 참/거짓 실측: 재확인 문단을 임시로 지운 사본 → named AssertionError.
- [ ] 5. Commit `docs(compose): 오너 위임 판단 4건 — 실측·판정·비용을 결정문으로 고정하고 §6.1 을 재확인으로 종결한다`.

## Task 2 — `reclaim-unbound` (item 2)

**Files**
- Modify: `src/alive/compose/smoke_evidence.py` — 새 함수 `reclaim_unbound_sidecars(*, evidence_dir, sidecar_names) -> list[str]`(추가만; `publish_promotion` 불변)
- Modify: `scripts/compose_smoke_evidence.py` — 하위명령 `reclaim-unbound --evidence-dir --inputs`(같은 bundle 로 이번 promotion 의 sidecar 이름을 계산)
- Test: `tests/alive/compose/test_smoke_evidence.py`, `tests/test_compose_smoke_evidence_cli.py`

**Interfaces** — Consumes: `LOCK_NAME`, `validate_dependency_lock`(또는 lock JSON 의 `run_gate.evidence_status`), `Promotion.files` 의 이름 집합.
Produces: 제거한 파일명 목록; 조건 불충족 시 `ActivationEvidenceError`(메시지에 이유).

**규칙(세 조건 전부 참일 때만 제거):** (a) `evidence_dir/LOCK_NAME` 이 존재하고 `run_gate.evidence_status != "COMPLETE"`;
(b) 대상 파일명이 이번 promotion 이 만들 sidecar 이름 집합에 있음; (c) lock JSON 을 문자열 검색해 그 파일명이 어디에도 등장하지 않음.
COMPLETE lock 아래에서는 어떤 파일도 지우지 않는다(에러). 조건 (c) 위반 파일은 건너뛰지 않고 **전체를 거부**한다(부분 삭제 금지).

**Steps**
- [ ] 1. 실패 테스트(각각 own-frame): `test_reclaim_removes_only_sidecars_left_by_a_crashed_publish`(실패 주입: `atomic_write_once` 를 두 번째 호출에서 raise 하도록 monkeypatch 해 publish 를 중단 → 첫 sidecar 만 남음 → reclaim → 재-promote 성공), `test_reclaim_refuses_under_a_complete_lock`, `test_reclaim_refuses_a_sidecar_the_lock_references`, `test_reclaim_refuses_a_name_outside_this_promotion`, `test_reclaim_leaves_the_directory_byte_identical_when_it_refuses`(디렉터리 snapshot 비교). CLI: `test_reclaim_unbound_subcommand_exit_codes`(0 / 1 REFUSED).
  실패 주입은 **production guard 를 mock 하는 것이 아니라 I/O 를 중단시키는 것**이다 — 주입 지점을 `smoke_evidence.atomic_write_once` 이름으로 한정하고 테스트 docstring 에 이유를 적는다.
- [ ] 2. red 확인(함수/하위명령 부재).
- [ ] 3. 구현. 4. green. 5. 참/거짓: 조건 (a)(b)(c) 각각을 무력화한 변이 → 대응 negative red(own-frame).
- [ ] 6. Commit `feat(compose): smoke evidence 의 unbound sidecar 를 reclaim-unbound 로 되찾는다 — write-once 는 유지, 손으로 지우는 일만 없앤다`.

## Task 3 — sealed roster 를 split manifest 에서 유도 (item 3) · T2 뒤(같은 파일)

**Files**
- Modify: `src/alive/compose/smoke_evidence.py` — `build_smoke_pair_roster(..., pair_manifest: Mapping[str, Any], sealed_pair_ids: Sequence | None = None, ...)`
- Modify: `scripts/compose_smoke_evidence.py` — bundle 의 backend 항목에 `pair_manifest`(경로) 필수; `sealed_pair_ids` optional
- Modify: `tests/alive/compose/smoke_evidence_support.py` — tiny fixture 가 `build_pair_split`/`build_split_manifest` 로 **실제** manifest 를 만들고 그 checksum 을 artifact block 의 `pair_manifest_sha256` 으로 쓴다(`TINY_SEALED_PAIRS` 는 manifest 의 sealed role 에서 유도)
- Modify: `tests/alive/compose/test_smoke_evidence.py`, `tests/test_compose_smoke_evidence_cli.py`
- Modify(문서): `scripts/compose_smoke_evidence.py` 모듈 docstring 의 bundle 예시; `docs/superpowers/COMPOSE-SEAL-READINESS.md` 의 smoke evidence 관련 행이 있으면 한 절
- 건드리지 않음: `scripts/compose/build_dev_smoke_payload.py` 의 sentinel(dev 전용) — 대신 `test_dev_smoke_payload.py` 에 "dev sentinel artifact 는 promotion 에 쓸 수 없다" negative 하나

**Interfaces** — Consumes: `alive.compose.split.verify_split_manifest`, role 이름 상수 `SEALED_DOUBLE_UNSEEN_ROLE_NAME`·`SEALED_SINGLE_UNSEEN_ROLE_NAME`(실제 이름은 `split.py` 에서 확인), `FitRoleArtifactSpec.pair_manifest_sha256`.
Produces: roster `sealed_pair_ids` = manifest 의 두 sealed role 을 `combo_sep` 로 canonical 토큰화한 정렬 목록; record 에 `pair_manifest_sha256`(검증된 checksum) 추가.

**Steps**
- [ ] 1. 실패 테스트: `test_the_sealed_roster_is_derived_from_the_split_manifest`(caller 가 아무것도 안 줘도 roster 가 manifest 의 sealed role 과 같다), `test_a_manifest_whose_checksum_differs_from_the_artifact_is_refused`(digest 불일치 → typed 거부), `test_a_tampered_manifest_is_refused_by_verify_split_manifest`(역할 하나 바꾸고 checksum 은 그대로), `test_a_harness_sealed_roster_that_disagrees_with_the_manifest_is_refused`(optional 교차검증), `test_the_dev_sentinel_artifact_cannot_be_promoted`. CLI: bundle 에 `pair_manifest` 없으면 usage error(exit 2).
- [ ] 2. red. 3. 구현(fixture 부터 — manifest 를 실제로 만든다; `build_split_manifest` 가 seed/fraction 재현을 요구하므로 tiny universe 의 역할은 `build_pair_split` 이 정한다 — **fixture 상수를 그 결과에서 유도**하고 손으로 정한 역할과 다르면 상수 쪽을 고친다). 4. green: `uv run --locked pytest -q tests/alive/compose/test_smoke_evidence.py tests/test_compose_smoke_evidence_cli.py tests/alive/compose/test_dev_smoke_payload.py tests/alive/compose/test_split.py -p no:randomly`(파일명은 실재 확인).
- [ ] 5. 참/거짓: digest 비교 제거 → 첫 negative red; role 유도 제거(빈 roster) → 첫 positive red.
- [ ] 6. Commit `feat(compose): smoke evidence 의 sealed roster 를 caller 가 아니라 split manifest 에서 유도한다 — artifact 의 pair_manifest_sha256 과 digest 대조`.

## Task 4 — review-state ledger 에 slot ID·run_id (item 4; 저장소 밖, 로컬 전용)

**Files(워크트리 `/Users/jam/ALIVE-audit-log`, 브랜치 `audit-log`)**
- Modify: `bin/review_latch.sh` `latch_record` — 5열 `slot_id`, 6열 `run_id`; `bin/daily_review.sh` — `RUN_ID` 를 기동 시 한 번 생성(`uuidgen` 없으면 `$$-$(date +%s)`), `SLOT_ID="${ET_D}T${ET_H}"`
- Test: `bin/test_review_latch.sh`(있으면 확장, 없으면 신설) — 임시 state 파일에 기록 → 6열, `latch_attempts_today`/`latch_succeeded_today`/`latch_should_run` 결과가 열 추가 전후 동일(기존 4열 줄과 섞여도)

**Steps**
- [ ] 1. 현재 reader 가 `$1`·`$3` 만 쓰는지 grep 으로 재확인. 2. 테스트 스크립트(red: 5·6열 부재). 3. 구현. 4. green + 기존 4열 줄 호환 실측. 5. `audit-log` 브랜치에 커밋(**push 금지**). 6. 이 저장소에는 아무것도 쓰지 않는다 — 보고서에만 결과.

---

## 검증 사다리
1. task 별 red/green(own-frame). 2. targeted nodeid. 3. 관련 suite(위 명령들). 4. `uv run --locked ruff check src tests scripts && uv run --locked ruff format --check src tests scripts`; `git diff --check`.
5. 변이 harness `uv run --locked python scripts/compose_audit_mutation_harness.py` → 20/20 유지(이 플랜은 case 를 추가하지 않는다; T3 의 digest 비교가 seal-guard 성격이므로 코디네이터가 M21 추가 여부를 최종 리뷰에서 판단).
6. 불변식: pinned/config 3면 diff 비어야 함 · `shasum -a 256 src/alive/compose/approximation_bias.py` = `af0dab18…` · config digest assert · `rg -n 'CLAUDE\.md\s+§\d' docs src tests scripts` 0 · `wc -l CLAUDE.md` 198.
7. 문서: `tests/test_documentation_hygiene.py`, `tests/test_claude_md_anchors.py`.
8. 전체 suite `uv run --locked pytest -q` → 기준 3188 passed / 3 skipped + 새 테스트 수(정확히 설명).
9. Release boundary: 로컬 green 은 release 신호가 아니다 — ACTIVE / RELEASE-BLOCKED / seal UNOPENED 유지.

## 실행 순서
T1 ∥ T4(저장소 밖) → T2 → T3(같은 파일) → 사다리 → whole-branch 리뷰 → PR → 독립 리뷰 → 병합.

## 부록 — 닫지 않는 것
- Codex 감사판 5일 부재(루프 DEGRADED_STALE_AUDIT) — 오너 통지 사항, 이 플랜 밖.
- pod-gated 목록(커널 재증명·`.pyz` parity·D3 runtime 증거·R1 representation·D1-c λ*) 은 그대로.
