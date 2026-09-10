# COMPOSE-K562-v1 — 오너 위임 판단 4건 (2026-09-10)

> **역할:** 2026-09-06 검토가 **오너 판단**으로 남기고 간 4건의 authoritative 결정 기록. 판정과 그
> 판정이 선 실측·비용·구현 위치를 한 곳에 둔다.
> **날짜:** 2026-09-10 · **기준 트리:** `main` `21bc56a`.
> **STATUS: SIGNED — by delegation (Claude, authorised by Jae Min Yoon) / 2026-09-10.**
> **위임 근거:** 오너 서면 지시 2026-09-10 — **"오너 판단 너에게 위임한다"**. 2026-09-05 의 위임
> ("오너 결정 목록에 대한 권한을 너에게 위임한다. 최고의 권장사항 도출 후 진행해라",
> [amendments record](2026-08-30-compose-spec-10-5-amendments.md))과 같은 형식의 서면 위임이며,
> 대상만 다르다 — 이번에는 2026-09-06 검토가 남긴 네 질문이다. 서명은 **선택**이지 구현이 아니다:
> 각 절의 구현은 [plan](plans/2026-09-10-owner-delegated-judgments.md) 의 Task 1~4 가 한다.
> **네 판정 중 어느 것도 상태를 움직이지 않는다** — `config_sha256`
> `a9dc9410d1b7fe1580e179b1fa5f9f3756688e059247a6d63322edf642b44767` 불변, seal **UNOPENED**,
> lifecycle **ACTIVE** / execution **RELEASE-BLOCKED** 유지. 게이트가 없는 이유는 §0 마지막 문단에 적는다.

각 절은 **질문 → 실측 → 판정 → 비용(틀렸을 때) → 구현** 순서다. 실측은 이 트리에서 실제로 실행한
명령과 그 출력의 요지이며, 인용이 아니라 측정이다 — 판정의 근거는 그 측정이지 검토문의 주장이 아니다
(governance: [CLAUDE.md](../../CLAUDE.md#agent) `#agent`).

## §0 — 네 판단 한 눈에

| id | 질문 | 판정 | 비용(틀렸을 때) | 구현 |
|---|---|---|---|---|
| `J1` | 위임 서명(B·C)과 서명 후 정정(A)을 오너가 자기 손으로 재서명해야 하는가 | **재서명 불요** — 09-10 위임이 곧 재확인 | 0 (문서) | Task 1 |
| `J2` | crash 뒤 lock 이 참조하지 않는 sidecar: fail-closed + 수동 정리 vs atomic directory publish | **현행 유지 + `reclaim-unbound` 하위명령** | S | Task 2 |
| `J3` | sealed roster 를 caller 입력이 아니라 split manifest 에서 유도할 것인가 | **승인·구현** — `verify_split_manifest` 로 검증한 manifest 에서 유도 | M | Task 3 |
| `J4` | 검토 루프의 로컬 전용 state ledger 에 slot ID·run_id 를 넣을 것인가 | **구현(로컬 전용)** — 5·6열 `slot_id`·`run_id` 추가 | S | Task 4 |

**게이트가 없다.** 네 판단 모두 오너가 위임했고, 어느 것도 config·seal·claim 을 움직이지 않는다.
`J2`·`J3` 는 guard 를 **추가**하거나 **좁히는** 쪽이고(약화 없음), `J4` 는 이 저장소 밖에서만 일어난다.

## J1 — 위임 서명과 서명 후 정정의 지위

**질문.** 수정안 B·C 의 위임 서명과, 수정안 A 의 서명 후 조항 정정을 오너가 **자기 손으로** 다시
서명해야 하는가. 2026-09-06 검토는 사실 관계에는 이견을 두지 않고 절차만 권고했다.

**실측.**

```text
$ diff <(git show 21bc56a:docs/superpowers/2026-08-30-compose-spec-10-5-amendments.md) \
       docs/superpowers/2026-08-30-compose-spec-10-5-amendments.md   # → 차이 없음
$ git show 21bc56a:docs/superpowers/2026-08-30-compose-spec-10-5-amendments.md | sed -n '9p;22,24p;46,49p'
```

- `:9` STATUS — A SIGNED (2026-09-03; 삽입 + 조항 정정 2026-09-05 under delegation) · B SIGNED
  (2026-09-05, by delegation) · C SIGNED (2026-09-05, by delegation).
- `:22-24` 서명 표 — A 는 **Jae Min Yoon / 2026-09-03** 의 자필 서명이고, B·C 만 위임 서명이다.
- `:46-49` — 2026-09-05 위임 기록이 그 위임 문구를 축자로 인용하고, "모든 서명은 그것이 선 주장을
  먼저 측정한 뒤에 이뤄졌다" 를 명시한다.

즉 다투는 대상은 **A 의 서명이 아니라 A 의 정정 + B·C 의 서명**이며, 그 셋의 사실 관계는 검토도
합의했다. 그리고 그 절차 질문 **자체**를 오너가 2026-09-10 에 다시 서면으로 위임했다.

**판정 — 재서명 불요.** 오너의 09-10 위임이 곧 09-05 위임 서명에 대한 **재확인**이다. 같은 손이
같은 형식으로 두 번 위임했고, 두 번째 위임은 첫 번째 위임 아래 이뤄진 서명들을 알고 있는 상태에서
내려졌다. 종결 방법은 **날짜 붙은 문단 하나** — amendments 문서에
`**Re-affirmation record — 2026-09-10.**` 를 [delegation record](2026-08-30-compose-spec-10-5-amendments.md)
문단 뒤에 더하고, 헤더 STATUS 줄 아래에 그리로 가는 한 줄 인용을 둔다. **서명된 문장과 서명 표 세 줄은
한 바이트도 다시 쓰지 않는다** — 재확인은 더하는 것이지 고쳐 쓰는 것이 아니고, 그 "추가만" 은
`test_the_delegated_judgments_record_names_all_four_and_their_basis` 가 base `21bc56a` 의 세 줄을
상수로 들고 실측한다.

**이 판정이 하지 않는 것.** 오너가 자기 손 서명을 원하면 **추가로** 넣으면 되고, 그때도 되돌릴 것은
없다. 이 판정은 세 수정안의 내용을 다시 열지 않고, 어느 residual(`seal.claim-materialization-replay`,
`seal.transient-inode-mutation-restoration`)도 닫지 않는다 — 그 둘은 여전히 열려 있다.

**비용(틀렸을 때).** 0 — 문서 문단 하나다. 오너가 다르게 판단하면 자필 서명을 덧붙이는 것으로
끝나며 어떤 코드·config·seal 상태도 관여하지 않는다.

**구현.** Task 1 (이 기록 + amendments 재확인 문단 + readiness 행 + 위 named test).

## J2 — crash 뒤 lock 이 참조하지 않는 sidecar

**질문.** promotion 도중 crash 가 나면 sidecar 만 남고 재실행이 거부된다. fail-closed 를 유지하고
수동 정리를 받아들일 것인가, 아니면 evidence 디렉터리 전체를 atomic directory publish 로 바꿀 것인가.

**실측.** `grep -n "def publish_promotion" -A 60 src/alive/compose/smoke_evidence.py` —
[smoke_evidence.py](../../src/alive/compose/smoke_evidence.py) `:753` 의 `publish_promotion` 은

- `:787-793` 모든 sidecar 이름을 **먼저** 검사해 하나라도 있으면 `FileExistsError` 로 거부하고,
- `:796-805` staging 사본에서 `validate_dependency_lock` 이 COMPLETE 를 낼 때만 진행하며,
- `:807-808` sidecar 를 `atomic_write_once` 로 쓰고 **`:809` 에서 lock 을 atomic rename 으로 마지막에** 쓴다.

lock 이 commit point 이므로 그 사이의 crash 는 **sidecar 만 남긴** 상태를 만든다. 그 상태에서
재실행은 `:787-793` 에 걸려 거부되고, 지금까지는 사람이 손으로 지워야 했다. 한편 evidence 디렉터리는
committed 파일들과 공존하므로 디렉터리 전체를 swap 하는 설계는 그 파일들까지 교체 대상으로 만든다 —
문제의 크기에 비해 과하고, write-once 불변식을 디렉터리 단위로 옮겨 놓는다.

**판정 — 현행 유지 + `reclaim-unbound`.** `publish_promotion` 의 거부는 **그대로** 두고, 별도 경로로
`reclaim-unbound` 하위명령을 더한다. 세 조건이 **모두** 참일 때만, **이 promotion 이 만들 이름의**
sidecar 만 지운다: (a) `LOCK_NAME` 이 있고 `run_gate.evidence_status != "COMPLETE"`, (b) lock 의 어느
필드도 그 파일을 참조하지 않는다, (c) 이름이 이번 promotion 의 파일 집합에 속한다. write-once 불변식은
유지되고(지우는 것은 lock 이 결속하지 않은 잔해뿐이다), run_dir·seal audit·terminal 에는 손대지 않는다.

**비용(틀렸을 때).** S — 하위명령 하나. 다만 조건이 틀리면 **지우지 말아야 할 파일을 지운다**. 그래서
세 조건을 각각 **negative 로** 핀하고(조건 하나만 거짓일 때 거부되는지를 각각 측정), 실패 주입으로
"sidecar 만 남은" 상태를 실제로 만들어 고정한다.

**구현.** Task 2 ([smoke_evidence.py](../../src/alive/compose/smoke_evidence.py) 에 함수 추가 +
CLI 하위명령; `publish_promotion` 불변).

## J3 — sealed roster 를 split manifest 에서 유도한다

**질문.** sealed roster 를 caller 가 건네는 `sealed_pair_ids` 로 계속 받을 것인가, 아니면 fit-role
artifact 가 가리키는 **split manifest** 에서 유도할 것인가(seal-guard 경로 착수).

**실측.**

- [smoke_evidence.py](../../src/alive/compose/smoke_evidence.py) `:189-289` `build_smoke_pair_roster` —
  training roster 는 artifact 의 행에서 **세우지만**(`:251-264`), `sealed_pair_ids` 는 `:194` 의
  **caller 인자**이고 그것으로 하는 일은 `:248` 의 정규화와 `:286` 의 `sealed_pair_overlap_count` 뿐이다.
  즉 sealed roster 자체는 아무것에도 결속되지 않는다.
- [phase2b.py](../../src/alive/compose/phase2b.py) `:710` — artifact block 의
  `pair_manifest_sha256` 은 scientific 경로에서 split manifest 의 `checksum` 이다.
- [carrier_loader.py](../../src/alive/compose/driver/carrier_loader.py) `:779`·`:810` — driver 는
  같은 manifest 를 `_preseal_json(spec, "pair_manifest")` 로 읽는다.
- [split.py](../../src/alive/compose/split.py) `:278` `verify_split_manifest` 는 checksum 재계산 ·
  algorithm/version · role 집합 · seed 재현을 자체적으로 검증하고, `:266-270` 의 `roles` 는
  calibration 하나와 **sealed role 둘**(`sealed_double_unseen`, `sealed_single_unseen`)을 담는다.
- 결속 코드는 **0** 이다: `grep -rn "verify_split_manifest" src/` 는 정의 파일(`split.py:274`·`:278`)을
  빼면 `phase2b.py:125`·`:1692` 와 `outcome_store.py:68`·`:388` 뿐이고, `smoke_evidence.py` 는 그 함수를
  import 조차 하지 않는다(`:22-44` import 블록). 2026-09-06 검토도 (b) 항에서 이를 인정했다.

**판정 — 승인·구현.** manifest 를 `verify_split_manifest` 로 검증하고, 그 checksum 이 artifact block 의
`pair_manifest_sha256` 과 **같을 때만** sealed roster = manifest 의 두 sealed role 로 유도한다. caller 의
`sealed_pair_ids` 는 **optional 교차검증**으로 강등한다 — 주어지면 유도값과 **정확히 같아야** 하고,
다르면 거부한다. dev-smoke 의 sentinel digest 경로는 애초에 release evidence 가 아니므로
**promotion 불가**임을 명시한다.

**비용(틀렸을 때).** M — inputs bundle 에 `pair_manifest` 경로가 추가되고, 테스트 fixture 가 실제
tiny manifest 를 만들어야 한다. 틀리면 유도값이 caller 값과 갈라지며 **거부**로 나타난다(조용한
통과가 아니다) — 이것이 caller 입력을 남겨 두는 이유다: 두 출처가 어긋나는 순간이 관측 가능해진다.

**구현.** Task 3.

## J4 — 검토 루프 ledger 의 slot ID·run_id

**질문.** 검토 루프의 **로컬 전용 state ledger**(이 저장소 밖에 있다)에 slot ID 와 run_id 를 넣을 것인가.

**실측.** ledger 는 4열 `(ET date, time, state, detail)` 이고, 그 소비자는 **첫째(ET date)·셋째(state)
열만 읽는다** — `awk -F'\t'` 로 `$1`·`$3` 만 본다. 둘째(time)와 넷째(detail)는 어느 소비자도 읽지
않는다. 그래서 뒤에 열을 덧붙이는 것은 소비자를 바꾸지 않는 **호환 변경**이다. 현재 ledger 는 한
항목이 어느 실행 슬롯에 속했는지, 어느 실행이 그것을 썼는지를 담지 않으므로, 같은 날 여러 번
기록된 항목을 사후에 구분할 수 없다.

**판정 — 구현(로컬 전용).** 기록 지점이 5열 `slot_id`(`<날짜>T<시>`)와 6열 `run_id`(실행마다 하나;
없으면 프로세스 id + epoch)를 덧붙인다. 소비자는 바꾸지 않는다. **이 저장소 밖에서만** 일어나며 git 에
올리지 않는다 — 이 판정이 이 저장소에 남기는 것은 이 문단이 전부다.

**비용(틀렸을 때).** S — 열 추가다. 틀려도 소비자가 읽지 못하게 되는 것이 아니라 **열이 비는** 것으로
나타난다.

**구현.** Task 4 (저장소 밖 워크트리에서만; push 금지).

## 이 기록이 하지 않는 것

- **config 를 움직이지 않는다.** `config_sha256` 은
  `a9dc9410d1b7fe1580e179b1fa5f9f3756688e059247a6d63322edf642b44767` 그대로다. 네 판정 중 어느 것도
  `configs/` 를 읽는 것 말고는 건드리지 않는다.
- **seal 은 UNOPENED 다.** sealed outcome 에 접근하지 않고, seal audit·run_dir·terminal 에 손대지
  않는다([CLAUDE.md](../../CLAUDE.md#seal-immutability) `#seal-immutability`).
- **RELEASE-BLOCKED 는 그대로다.** 이 기록은 release gate 를 하나도 닫지 않는다 — 현재 blocker 는
  [readiness](COMPOSE-SEAL-READINESS.md) 가 authoritative 하다.
- **claim 을 넓히지 않는다.** 어떤 estimand·comparator·margin·multiplicity·verdict threshold 도 건드리지
  않는다. `J3` 는 sealed roster 의 **출처**를 바꾸는 것이지 그 roster 의 내용을 바꾸는 것이 아니다.
- **residual 을 닫지 않는다.** `seal.claim-materialization-replay` 와
  `seal.transient-inode-mutation-restoration` 은 열린 채로 남는다.
- **서명된 문장을 다시 쓰지 않는다.** amendments 문서에는 날짜 붙은 문단만 더한다.
