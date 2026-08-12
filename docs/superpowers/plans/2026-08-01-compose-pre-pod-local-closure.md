# COMPOSE-K562-v1 — pre-pod local closure Plan (초안)

> **⚠ 2026-08-04 부분 SUPERSEDED.** L1은 완료됐고 L2는 **여기 적힌 것과 다른 설계로** 구현됐다.
> L2-T3의 "`DesignConditionError` 신설 → roster 편입 → exit 10" 안과, D2 항목의 처분 서술은 더 이상
> 유효하지 않다. 현재 계약은 spec의 *Registered conditioning ceiling* 문단이며, ceiling은 selection의
> **후보별 admissibility 심사**다(모든 후보 부적격일 때만 `SelectionError` → exit 10). 아래 §4의
> "조건수는 uniform rescale에 **정확히 불변**" 서술도 정정됐다 — 반올림 오차 범위에서 불변이다.
> §7 task #14의 "live `2a8b1bc3…`"도 stale이며 현재 digest는 `b158417a…`다. §1의 D2 행이 적은
> `identification.condition_ceiling: 1.0e8` 철자는 YAML 1.1이 **문자열**로 파싱하므로 committed
> config는 `1.0e+8`을 쓴다. 아래 DRAFT 상태 행과 "D1·D2가 정해지기 전 L2 전체는 착수하지
> 않는다"는 gate 문장, 그리고 L1/L2 checkbox는 **집행 당시 상태로 보존**한다(이 문서는 실행
> 기록이 아니라 계획이며, 실제 진행은 readiness index가 authoritative다).
> 진행 상태와 종결 근거는 `docs/superpowers/COMPOSE-SEAL-READINESS.md`가 authoritative다.

> **상태:** DRAFT — owner decision gate D1–D4 미결. 아래 work package는 **전부 로컬(MacBook + GitHub
> Actions)에서 완결 가능한 항목만** 담는다. real Norman data·pod·owner key가 필요한 항목은 §7에 명시적으로
> 제외한다.
> **전제 상태:** `main` = `origin/main` = `b963ee9`, worktree clean, Linux CI green,
> COMPOSE lifecycle **ACTIVE** · execution **RELEASE-BLOCKED** · seal **UNOPENED**.
> **권위:** claim은 spec, exact value는 config, 현재 release 상태는
> `docs/superpowers/COMPOSE-SEAL-READINESS.md`, 실행 계약은 runbook이 정한다. 충돌 시 이 plan이 아니라
> 그쪽이 옳다([sources](../../../CLAUDE.md#sources)).

**Goal:** readiness index에 열려 있는 항목 중 **pod·owner-key에 의존하지 않는 전부**를 dev-pod 출발 전에
닫는다. 목적은 두 가지다 — (1) pod에서 발생할 실패가 등록된 exit code로 진단 가능하도록 driver 계약을
완성하고, (2) config digest를 움직이는 변경을 **pod 이전에 한 번만** 모아 lineage 이동 횟수를 최소화한다.

**Non-goal:** seal을 열지 않고, real fit을 돌리지 않으며, config의 기존 null activation blocker를 채우지
않는다. §4.3 guard를 약화하지 않는다.

---

## 1. Owner decision gate (착수 전 필요)

| ID | 결정 | 권고 | 영향 |
|----|------|------|------|
| **D1** | leakage-class rejection(`OutcomeLeakageError`/`LeakageError`)의 exit code | **(a) exit 10 단일 버킷 + runbook의 exception-name 대응표.** 숫자 계약(0/10/20/30)을 그대로 두고, "retry 가능 vs lineage 오염" 구분은 이미 stderr 한 줄이 나르는 type name 기준 표로 표현한다. 대안 (b) 전용 코드 11 신설 | (a)는 계약 변경 최소, (b)는 pod 운영자의 기계적 분기 가능 |
| **D2** | condition ceiling 통계량과 값 | **`identification.condition_ceiling: 1.0e8`**, 대상은 `rank_diagnostics(Φ).condition_number`. 근거는 data-free numeric anchor `1/√ε_f64 ≈ 6.7e7`(float64 유효자릿수 절반 상실 지점)를 자릿수로 반올림 | config digest 이동(=새 run identity). 아래 §3 margin 표 참조 |
| **D3** | uniform-scale에서의 "무의미한 λ"(penalty immateriality) 기준 | **등록하지 말고 registered limitation으로 기록.** 관측된 band는 surrogate-specific이고 원칙적 threshold가 없다. invariant #14(negative results are results) 적용 | spec 비주장 문단 + readiness 항목만 추가, 코드 변경 없음 |
| **D4** | receipt schema에 interpreter patch/build 기록을 지금 할지 | **지금 한다.** 비용은 CI 1회, closure file을 건드리지 않으므로 re-archive 불필요 | 아래 §4 트랩 참조 |

D1·D2가 정해지기 전 L1-T3 이후와 L2 전체는 착수하지 않는다. D3·D4는 병렬 가능.

---

## 2. Global constraints (모든 task에 적용)

- **Opens no seal.** 어떤 task도 `ComposeOutcomeStore`를 만들거나 `evaluate_sealed_once`를 호출하거나
  sealed pair outcome을 읽지 않는다.
- **[enforcement](../../../CLAUDE.md#enforcement) guard 파일을 약화하지 않는다.** 이 plan은 `outcome_store.py`·`gates.py`·`freeze.py`·
  `preflight.py`·`seal_boundary.py`·`run_spec.py`·`phase2b_cmd.py`·`pair_index.py`·`durable.py`·
  `terminal.py`·`io.atomic_write_once`·`confirmation.py`의 **동작을 바꾸지 않는다.** L1은 그들이 raise하는
  타입을 driver에서 **잡아서 등록된 exit code로 변환**할 뿐이며, 실행을 계속시키지 않는다.
- **`_ISOLATION_CLOSURE` 18개 파일을 건드리지 않는다.** 하나라도 바뀌면 v2 kernel proof가 무효가 되어
  Linux CI 재실행 + 새 archive + pin 이동이 강제된다.
- **bare `uv sync` 금지.** `uv.lock`이 closure에 pin되어 있다. 의존성 작업이 필요하면 `--locked`/`--frozen`.
- config/data-card/evidence field 변경은 새 run identity다. documentation cleanup과 섞지 않는다.
- 커밋은 bisect-safe 단위로 분할하고 **각 커밋이 독립적으로 green**임을 확인한다(직전 wave와 동일 절차).

---

## 3. L1 — driver exit-code contract 완성 (최우선)

**문제.** readiness `:383`(2026-07-30 NEW BLOCKER) + `:404`(2026-07-31 widening). `driver/cli.py:140`의
`_KNOWN_PRESEAL_REJECTIONS`가 phase2a 경로의 8개 타입을 받지 않아 전부 **traceback + exit 1**로 빠진다.
spec/runbook은 `main`의 반환을 0/10/20/30으로 **전면적(totally)** 정의하므로 exit 1은 계약 밖이다. pod
운영자는 exit 1만 보고 "등록된 pre-seal 거부"와 "driver 버그"를 구분할 수 없고, 그중
`BaselineUnavailable`(GEARS/CPA worker non-zero exit)은 pod에서 가장 먼저 터질 후보다.

**핵심 설계 원칙 — bare `ValueError`를 roster에 넣지 않는다.** `src/alive/compose`에는 raise 문 2112개,
그중 **bare `ValueError`가 218개**다. `ValueError`를 admit하면 218개의 미분류 실패(상당수는 진짜 버그)가
"등록된 pre-seal 거부"로 보고된다 — 정확히 이 프로젝트가 금지하는 fail-open이다. 따라서 계약되어야 하는
raise site는 **typed class를 갖게 만들고**, roster에는 typed class만 넣는다.

**Import surface 사전 확인(완료).** `alive.compose.driver.cli` import 시점에 `baselines_combo`·`freeze`·
`gates`·`phase2a`·`seed_variability`·`config2`·`identify`가 **이미 전부 로드**된다(alive.compose 모듈 48개,
`torch` 미로드). 따라서 roster 확장은 **새 import surface를 만들지 않으며** cycle·closure·worker-stack
위험이 없다.

### Tasks

- [ ] **L1-T1 (design).** `specs/2026-07-07-compose-production-driver-design.md` §1.1 개정:
      exit-code 계약이 **전면적이 아님**을 명시하고 **exit 1을 "uncontracted driver bug"로 등록**한다
      (stderr에 traceback, stdout 비어 있음, blind retry 금지). 동시에 roster 편입 규칙을 등록한다 —
      "`src/alive`에 정의된 typed exception만 admit 가능, bare `ValueError`는 어떤 경우에도 admit 불가".
      분류 어휘 등록: `PRESEAL_REJECTION` / `POSTSEAL` / `BUG` / `UNREACHABLE_FROM_DRIVER`.
- [ ] **L1-T2.** `phase2a.py:678`의 도달 가능한 bare `ValueError`(`_validate_config_contract` config drift)를
      typed로 교체한다. `Phase2ConfigError`(`config2.py:365`, `ValueError` 서브클래스) 재사용 여부를 구현 중
      판단하고 근거를 남긴다. `phase2a.py:1416`의 도달 불가 site는 **삭제하거나** 도달 불가를 증명하는
      테스트를 남긴다(둘 중 하나, 침묵 금지).
- [ ] **L1-T3 (D1 이후).** roster 편입: `HashMismatchError`(`phase2a.py:91`),
      `BaselineUnavailable`(`baselines_combo.py:55`, `RuntimeError`), `FreezeError`(`freeze.py:84`),
      `OutcomeLeakageError`(`freeze.py:94`), `LeakageError`(`gates.py:18`, **`ValueError`조차 아님**),
      `Phase2ConfigError`, seed-variability 계열(CONTINUE 경로에서 실제 도달하는 것만 —
      `SeedVariabilityContractError`/`ReportError`/`PreflightError` 중 확인된 것). 각 항목에 stage·raise
      site·pre-seal인 이유를 주석으로 남긴다(기존 `AssemblerError`/`SelectionError` 주석 스타일).
- [ ] **L1-T4.** **분류 레지스트리 + fail-closed 테스트.** `src/alive` 전체의 exception class 정의(현재 약
      70개, 이름 중복 포함)를 열거해 각각이 명시적 분류표에 1줄 근거와 함께 존재하도록 강제한다. 새 class가
      생기면 테스트가 닫히며 실패하고, 메시지는 "삭제하지 말고 분류하라"고 지시한다. — *이 항목이 재발
      방지의 핵심이다. 지금까지 roster와 closure 열거는 **손으로 세서 두 번 다 빠졌다.***
- [ ] **L1-T5.** contract 테스트: (subcommand × exception type) parametrize, 실제 `main()`에
      monkeypatch 주입 후 **(exit code, stderr 정확히 1줄 `f"{stage}: {type}: {msg}"`, stdout 완전히 비어
      있음)** 을 검증한다. bug bucket도 포함 — 미분류 예외가 exit 1 + traceback + **빈 stdout**을 내는지.
- [ ] **L1-T6.** `select.py`의 OOF↔L1 하드코딩 바인딩에 assert 추가(readiness `:400-403`의 latent item).
      현재 도달 불가이나 roster가 configurable해지는 순간 singular comparator가 "비viable 후보"로 기록된다.
- [ ] **L1-T7.** runbook `2026-07-02-…-pod-sealed-run.md:124`의 계약 줄에 등록된 exit 1을 추가하고,
      **exception name → 운영 대응** 표를 넣는다(재시도 가능 vs lineage 오염 → 새 run identity 필요).
      D1이 (a)면 이 표가 severity 구분을 나르는 유일한 장소가 되므로 정확해야 한다.
- [ ] **L1-T8.** readiness의 2026-07-30 blocker와 2026-07-31 widening 항목을 닫는다(삭제 아님, 종결 기록).

### L1 리뷰가 반드시 확인할 것

1. 새 catch가 `phase2b`의 post-seal → exit 30 경로(`6761428`)를 **잠식하지 않는가**.
2. leakage abort를 잡아 "일상적 거부"처럼 보이게 하거나 실행을 계속시키지 **않는가**
   (`main`은 즉시 반환, 어떤 subcommand도 이어지지 않음).
3. roster 확장으로 stdout에 무엇이든 새는 경로가 생기지 **않는가**.

---

## 4. L2 — registered condition ceiling (D2 이후)

**문제.** 2026-07-29 representability guard 삭제로 **block-scale imbalance를 탐지하던 유일한(우연한)
장치가 사라졌고 대체물이 없다**(readiness `:472-485`). 조건수는 uniform rescale에 **정확히 불변**
(1× / 1e6× 모두 `10.4218`)이지만 block imbalance에서는 11.55 자릿수 움직인다.

**Margin 표 (권고값 `1.0e8` 기준)**

| 대상 | 측정 조건수 | 권고 ceiling 대비 |
|------|------------|------------------|
| real 보고서 3건 | 15.8 / 32.9 / **484** | **5.3 자릿수 아래** |
| numeric anchor `1/√ε_f64` | 6.7e7 | ceiling의 근거 |
| ESM block ×1e6 exhibit | **3.71e12** | **4.6 자릿수 위** |
| 이전에 측정된 pathological bank | 4.3e12 | 4.6 자릿수 위 |

양쪽 margin이 모두 4자릿수를 넘고, **pre-seal 검사이므로 최악의 경우 pod 사이클 1회를 잃을 뿐 seal은
절대 태우지 않는다.**

### Tasks

- [ ] **L2-T1 (design).** `specs/2026-06-22-compose-epistasis-operator-design.md`의 identification 절에
      등록: 통계량(Φ의 조건수), uniform-rescale 불변성, ceiling이 **덮는 것**(block imbalance)과
      **덮지 않는 것**(uniform-scale penalty immateriality → D3)을 분명히 구분한다.
- [ ] **L2-T2.** config key `identification.condition_ceiling` 추가 + `config2.py`에 schema/dataclass/
      validator(`_EXPECTED_…` + `is not` guard 패턴). D2가 보류되면 값 대신 기존
      `unestablished_activation_blocker` 관용구를 그대로 쓴다.
- [ ] **L2-T3.** pre-seal 경로에서 강제. `diagnostics2`가 이미 조건수를 계산하므로 그 지점에서 typed
      `DesignConditionError`(신설, `ValueError` 서브클래스)를 raise하고 **L1 roster에 편입**해 exit 10으로
      계약한다. `SingularDesignError`를 재사용하지 않는다 — 그것은 "추정 자체를 거부"의 의미이고 이건
      **scientific admissibility** 판정이다.
- [ ] **L2-T4.** 테스트(mutation-verified): 삭제된 `test_one_over_scaled_factor_block_is_rejected…`의 exhibit
      (그 파일 `_make`, seed 6, ESM block ×1e6, cond 3.71e12) → **거부**. 동일 bank unscaled(10.4218) → 통과.
      **uniform ×1e6 → 통과**(불변성 회귀 테스트). real 기록값 15.8/32.9/484 → 통과.
- [ ] **L2-T5.** config canonical digest 재계산·기록. 기존 config-bound evidence는 이미 stale이므로
      추가 비용 없음(§7의 task #14는 어차피 pod 이후).
- [ ] **L2-T6.** leakage suite + full compose + readiness 항목 종결(open item `:485`, `:563`).

---

## 5. L3 / L4 / L5 / L6 — 나머지 로컬 항목

> **[2026-08-12] 이 checkbox들도 위 banner의 규칙을 따른다 — 집행 당시 상태로 보존한다.**
> L4는 완료(merge `18e323f`), L5는 **local half만** 완료(지시서 `runbooks/2026-08-12-compose-kernel-archive-independent-archiver.md`;
> 실제 독립 당사자 섭외는 owner 몫이라 task #16은 열려 있다), L3는 spec 비주장 문단 + readiness 4b로
> 실질 반영됨. **종결 근거와 진행 상태는 `COMPOSE-SEAL-READINESS.md`가 authoritative다** — 여기서
> checkbox로 중복 기록하지 않는다.

- [ ] **L3 (D3).** penalty immateriality를 **등록하지 않고 registered limitation으로 기록**한다.
      readiness `:591-595`의 band(λ가 `max||z||~116`부터 실질 무효)는 uniform-scale 의존이라 **L2의
      조건수 ceiling으로 닫히지 않는다.** 이걸 "닫혔다"고 쓰지 않는 것이 이 task의 요점이다.
      산출물: spec 비주장 문단 1개 + readiness 항목 1개. 코드 변경 없음.
- [ ] **L4 (D4).** kernel-isolation receipt schema에 실제 interpreter 기록 추가(readiness `:373` open item).
      `.python-version`은 minor series일 뿐 patch release를 식별하지 못한다.
      `scripts/compose/build_kernel_isolation_ci_receipt.py`에 `platform.python_version()`·`sys.version`
      build 문자열·`sys.implementation`을 추가하고 schema version을 올린다.
      **제약: validator는 기존 v1/v2 archive 2건을 계속 통과시켜야 한다(back-compat).** 빌더는
      `_ISOLATION_CLOSURE`에 없으므로 re-archive는 강제되지 않는다. CI 1회로 새 receipt를 생성해 확인.
- [ ] **L5 (task #16).** seal을 뒷받침할 kernel archive의 **독립 archiver** 요구. runbook §2.5에 항목은 이미
      들어가 있으므로 로컬 잔여는 archiver 지시서 정리뿐이고, **실제 독립 당사자 섭외는 owner 몫**이다.
- [ ] **L6.** `head_sha == C` archive는 **unresolved owner decision**으로 기록된 상태다. "archive의
      `head_sha`가 `C`에 선행하되 isolation closure가 byte-identical" 경로를 택하면 **이미 테스트로 강제되고
      있으므로 로컬 작업은 0**이다. 결정 전까지 코드를 만들지 않는다.

---

## 6. 순서와 그 이유

```
Wave 1  L1 (config 미이동)            → 독립 adversarial 리뷰 → merge → Linux CI
Wave 2  L2 (config digest 이동, L1 roster 의존, D2 필요) → 리뷰 → merge → Linux CI
Wave 3  L4 (독립, Wave 1/2와 병렬 가능) → merge → CI가 새 receipt 생성
Wave 4  L3 · L5 · L6 문서 종결
------- 이후: pre-pod SHA 동결 → dev pod 출발
```

순서를 이렇게 잡는 이유:

1. **L1이 먼저인 이유:** pod 실패를 진단 가능하게 만드는 장치이므로 pod **이전에** 있어야 값이 있다.
   그리고 L2의 ceiling 위반은 등록된 pre-seal rejection이어야 하므로 L1의 roster 메커니즘에 의존한다.
2. **config digest 이동을 한 번으로 모으는 이유:** pod에서 4개 null blocker(`power_status`,
   gears/cpa `revision`·`environment_status`, `approximation_bias_report_sha256`)를 채울 때 어차피 한 번 더
   움직인다. 지금 L2로 한 번 움직이는 비용은 0이다(현 evidence는 이미 stale). 대신 **L2를 pod 이후로 미루면
   digest가 한 번 더 움직여 evidence 재생성을 두 번 하게 된다.**
3. **§2.5는 `C`를 마지막 commit으로 동결한다.** 따라서 이 plan의 모든 항목은 `C` 동결 **이전에** 끝나야 한다.
4. **closure 변경은 재archive를 강제한다.** L1·L2는 closure 파일을 건드리지 않는다(사전 확인 완료). L4도
   빌더만 건드린다. `uv.lock`을 움직이지 않는 것이 이 wave 전체의 운영 제약이다.

## 6.1 wave별 검증 프로토콜 ([verify](../../../CLAUDE.md#verify))

1. targeted: 변경된 모듈의 테스트
2. `uv run pytest -q tests/alive/compose` — 기준선 **1723 passed / 2 skipped**(macOS)
3. `uv run pytest -q` 전체 — 기준선 **2414 passed / 3 skipped**(macOS)
4. `uv run ruff check src tests` + `uv run ruff format --check src tests`
5. **L2는 leakage suite 필수**(data/eval 계약 변경), **L4는 tamper/resume 필수**(provenance 변경)
6. **매 wave `tests/alive/compose/test_kernel_isolation_ci.py`** — closure drift 사고 방지
7. 커밋별 독립 green 확인 후 `--no-ff` merge, merge tree가 tip과 byte-identical인지 확인
8. merge SHA에서 **Linux CI green**(seccomp 2건이 실제 실행됐는지 = skip 1건인지 확인)

리뷰: 프로젝트 규범대로 branch별 **독립 adversarial 리뷰**. 추가로 standing practice인 loop gate 실행
(spec 증분에 spec-review 프로파일, 구현 증분에 science-dev 프로파일) — `loop-engineering-local`은
**LOCAL ONLY, 절대 push/commit/publish 금지**.

---

## 7. 이 plan에 **없는** 것 (pod / owner 전용)

- §2.2 real `gears_worker`/`cpa_worker` + pinned env 재실행 (dep-lock 현재 `INCOMPLETE`)
- conforming Probe A 재실행 (현 probe 결과 QUARANTINED/NONCONFORMING)
- real Norman bias report 생성 → `approximation_bias_report_sha256` 단방향 finalize
- config의 4개 null activation blocker 채우기 → 새 run identity
- **task #14** — activation-evidence 2건 재생성(현재 `d8c65ac4…` 박제, live `2a8b1bc3…`, `config2.py`가
  정확히 거부 중). config 확정 **후**에만 가능
- owner Ed25519 offline 서명 · fingerprint 외부 대조 · v2 image lock
- §2.5 release gate: `C` 동결 → 독립 exact-SHA 리뷰 → external durable 게시 → owner 승인
- A100 sealed run (seal 1회 개봉)

**이 plan의 어떤 항목도, 전부 완료되어도, `RELEASE-BLOCKED`를 해제하지 않고 seal을 열 권한을 주지 않는다.**

---

## 8. Exit criteria

1. D1–D4 결정 기록됨.
2. L1–L4 merge 완료, 각 wave가 독립 리뷰 통과, `main`에서 full suite + ruff green, Linux CI green.
3. readiness의 exit-code blocker와 condition-ceiling open item이 **종결 또는 명시적 registered
   limitation**으로 기록됨(침묵 종결 금지).
4. config digest 최종값이 기록되고, 그 digest가 pod에서 채울 null blocker의 **직전 기준선**임이 명시됨.
5. `_ISOLATION_CLOSURE` 18개 파일 무변경 확인 — 또는 변경 시 새 Linux archive와 pin 이동 완료.
