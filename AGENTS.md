# ALIVE — Codex 작업 계약

ALIVE는 `p(X_post | P_control, A, C)`로 표현하는 causal virtual-cell world model을 단계적으로 연구한다.
`P_control`은 control-cell population, `A`는 intervention, `C`는 context다.
이는 연구 목표이며 현재 구현의 causal·mechanistic 성질을 입증한 식이 아니다.
개별 protocol의 claim은 실제 split과 estimand가 검증하는 범위로 제한한다.

이 파일은 Codex 진입점이다. 과학적 계약은 [CLAUDE.md](CLAUDE.md)에 두고 여기서 재정의하지 않는다.
Threshold·seed·metric·roster·blocker·실험 명령은 해당 원문을 참조한다.

## 1. 작업 방식과 skill

- 시작할 때 `git status --short`로 기존 변경을 확인하고 사용자 수정·미추적 파일을 보존한다.
- [CLAUDE.md](CLAUDE.md)를 읽고 대상 protocol과 affected invariant를 식별한다. 같은 작업에서 이미 읽은
  변경 없는 문서는 반복 로딩하지 않는다. 아래 경로 규칙과 작업에 필요한 spec/plan/config, 구현·테스트를 확인한다.
- 대상 경로의 하위 지침도 확인한다. 같은 디렉터리에서는 `AGENTS.override.md`가 `AGENTS.md`에 우선한다.
  루트에서 시작했다고 하위 지침까지 자동으로 로딩되었다고 가정하지 않는다.
- Skill은 현재 세션에 제공된 목록과 trigger에 따라 선택한다. 선택한 `SKILL.md`는 전부 읽고,
  추가 자료는 그 skill이 요구하는 범위만 읽는다. 설치 경로나 도구·CLI 명령을 이 파일에 복제하지 않는다.
- 이 파일은 프로젝트 제약, skill은 작업별 절차를 담당한다. 실제 지시 우선순위와 도구 권한은 실행 환경을 따른다.
  Skill의 설치·업로드·배포·위임 절차를 요청 범위 확장이나 scientific run 승인으로 해석하지 않는다.
  Skill과 과학 계약이 충돌하면 해당 scientific action을 보류하고 충돌 위치와 필요한 결정을 보고한다.
- 일반 수정·로컬 검증은 요청 범위에서 진행하고 불필요한 승인 단계를 추가하지 않는다.
  질문·리뷰·진단 요청만으로 구현이나 외부 변경을 시작하지 않는다. 결론이나 권한을 바꾸는 불확실성만 질문한다.
- 한국어로 설명하되 identifier·protocol ID·metric·verdict는 원문을 유지한다.
  가정·관찰·검증된 결론을 구분하고 미실행 검사·승인을 완료했다고 쓰지 않는다.

## 2. 원문과 충돌 처리

도메인별 권위는 [CLAUDE.md#sources](CLAUDE.md#sources)를 따른다:
governance는 CLAUDE, claim/estimand는 spec, 실행은 plan/runbook, exact value는 config/data card,
현재 release 상태는 [readiness](docs/superpowers/COMPOSE-SEAL-READINESS.md), 실제 동작은 코드·테스트다.
코드나 green test가 spec 위반을 정당화하지 않는다.
장기 비전 자료는 현재 protocol의 실행 근거가 아니다. Superseded 연구보고서·계획은 역사 자료로 읽는다.

문서 충돌이 있으면 위치·affected protocol/invariant를 보고하고 해당 scientific run을 시작·계속하지 않는다.
Owner의 권위 문서 정합화가 필요하며 변경된 lineage에는 새 run identity를 사용한다.
독립적인 조사·문서 정정·synthetic 검증은 계속할 수 있다.

## 3. Scientific boundary

Protocol 상태 원문은 [registry](CLAUDE.md#registry)와 readiness다. **2026-09-11 확인 snapshot**:

- `TG-K562-v1`: COMPLETE; seal 1회 사용; `NO_DISTINCT_WIN`. 완료된 evaluation을 재실행하지 않는다.
- `COMPOSE-K562-v1`: Norman K562 CRISPRa pair-level GI; **ACTIVE / RELEASE-BLOCKED / UNOPENED**.
- `CT-RPE1-v1`: DEFERRED; 별도 활성화 계약·owner approval 전 perturbed outcome 접근 금지.

`ACTIVE`는 실행 허가가 아니다. COMPOSE real fit·sealed run에는 finalized config/evidence lineage,
유효한 current `ActivationRecord`, clean owner-approved **exact Git SHA**, passing release gate,
canonical protocol-global seal audit path가 필요하다.
[Current runbook](docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md)의
final human confirmation을 코드 수정 승인이나 local green으로 대체하지 않는다. Blocker를 추측값으로 채우지 않는다.

[모든 scientific invariants](CLAUDE.md#invariants)와 [data/model/eval 계약](CLAUDE.md#data-eval)을 적용한다.
특히 다음 경계를 유지한다.

- Outcome 접근 전에 protocol·baseline·claim-unit split·metric·power/detectable-effect·exclusion을 사전등록한다.
  Fit/selection은 허용된 role만 사용하며 평가 universe를 response strength로 선택하지 않는다.
- Claim unit, biological unit, technical replicate를 구분한다. Cell 수나 seed 수를 독립 biological N으로
  취급하지 않고 exact N·반복 구조·effect size·CI·seed variability·실패/제외를 보고한다.
- 가설을 반증할 가장 작은 적법한 실험을 우선한다. Leakage·confounding·collapse·metric gaming을 점검하고
  exploratory를 confirmatory로, bilinear 성과를 deep/causal/heterogeneity 증거로 승격하지 않는다.
- Encoder ablation과 non-claim은 [현재 모델 계약](CLAUDE.md#data-eval)의 protocol별 처분까지 따른다.
  COMPOSE의 유예된 encoder marginal-signal ablation을 일반 규칙으로 다시 의무화하거나 수행했다고 주장하지 않는다.
- Data source·modality·cell line·checksum·transformation provenance를 확인하고 sparse/on-disk/bounded access를 쓴다.
  Raw/processed data·checkpoint·credential은 commit하지 않는다. Transfer 전 size·destination·license·privacy를 확인한다.

## 4. Seal·실패·기록 보존

[Seal](CLAUDE.md#seal), [provenance](CLAUDE.md#provenance), [enforcement](CLAUDE.md#enforcement)가 원문이다.

- fit/develop/calibrate/PREPARE의 sealed access count는 **0**이다. Sealed source를 열거나 materialize하지 않고,
  그 stat을 selection에 사용하지 않는다. Authorized evaluation도 protocol-global 1회 계약을 따른다.
- Guard 거부 시 error·stage·run identity·audit를 보존하고 원인을 조사한다. Guard를 우회·약화·mock 대체하지 않는다.
  Guard 변경은 요청 범위에서 fail-closed 성질과 관련 negative test를 보존해야 한다.
- Run·audit·terminal·evidence를 덮어쓰거나 삭제해 재시도하지 않는다. Resume은 byte-identical upstream만 허용하며
  terminal/seal 이후 upstream을 재실행하지 않는다. 새 run ID는 protocol seal을 초기화하지 않는다.
- Futility-stopped run은 count 0으로 영구 종료한다. Futility를 scientific negative verdict로 바꾸지 않으며
  negative/invalid 결과도 삭제·대체하지 않는다.
- Signed decision·as-run command·hash·outcome은 prose cleanup으로 고치지 않는다. 정정은 날짜를 붙여 추가한다.
  Historical/superseded 자료는 원문과 current authority 연결을 보존한다.

## 5. 경로별 읽기

`.claude/rules/`나 Claude 전용 도구의 자동 적용을 가정하지 않는다. 아래 해당 규칙은 직접 읽고,
연결된 원문은 변경에 영향을 주는 계약을 확인한다. Scientific run 전에는 전체 관련
spec/plan/config/runtime contract audit가 필요하다. CLI help나 readiness 조회만으로 대체하지 않는다.

| 범위 | 규칙과 진입 문서 |
|---|---|
| COMPOSE 소스/테스트·script·baseline worker·config·문서 | [.claude/rules/compose.md](.claude/rules/compose.md), [design spec](docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md), [phase2 config](configs/compose_k562_v1_phase2.yaml), readiness/current runbook |
| CARTOGRAPHER 및 공유 data/base/gate/baselines/conformal/metrics/eval/experiment | [.claude/rules/cartographer.md](.claude/rules/cartographer.md), [design spec](docs/superpowers/specs/2026-06-20-cartographer-design.md); 공유 모듈은 실제 영향받는 protocol 규칙도 확인 |
| README·AGENTS·CLAUDE·virtual-cell 문서·docs | [.claude/rules/documentation.md](.claude/rules/documentation.md), 수정할 내용의 authoritative spec/plan/config |

## 6. 개발과 검증

[Repository](CLAUDE.md#repo)와 [compute](CLAUDE.md#compute)를 따른다.
재사용 로직은 `src/alive/`, entry point와 등록된 pod-only worker/probe는 `scripts/`, 검증은 `tests/`에 둔다.
Python은 `pyproject.toml`·`.python-version`, dependency는 `uv.lock`을 따른다.
실험값을 production source에 hardcode하지 않는다. 등록된 `config2.py`의 `_EXPECTED_*` 검증 미러는 예외다.
Public API에는 type hint와 NumPy-style docstring을 사용한다.

환경 설정은 `uv sync --locked`, Python 도구 실행은 `uv run --locked`를 사용한다.
Lock 불일치 시 원인을 확인하고 자동 갱신하지 않는다. 의존성 변경은 요청 범위에서만 한다.
Scientific 명령은 current runbook/CLI help로 확인한다.
Local Mac은 setup·unit/mini/synthetic·bounded inspection용이며 승인된 real-data preparation/full run은 pod에서 한다.
Device fallback과 cloud 비용·환경·input hash·Git SHA·wall time을 기록하고 ephemeral disk를 유일본으로 쓰지 않는다.

- **문서만 변경:** 링크·anchor·현재 상태·원문 정합성 확인 후
  `uv run --locked pytest -q tests/test_claude_md_anchors.py tests/test_documentation_hygiene.py`, `git diff --check`.
- **코드 변경:** targeted unit → applicable integration → Ruff.
  COMPOSE는 경로 규칙에 따라 targeted 후 `uv run --locked pytest -q tests/alive/compose`.
  공통 모듈·dependency·여러 protocol 영향 시 `uv run --locked pytest -q`.
  반복 편집 중에는 targeted 검사를 사용하고 완료 전 필요한 전체 회귀검사를 수행한다.
- **추가 검증:** data/eval은 leakage·role isolation, metric은 known-answer/constant/shuffled/random,
  artifact/provenance/guard는 tamper·resume·negative/fail-closed. 기능 수정에는 회귀 검증을 둔다.
- **정적 검사:** `uv run --locked ruff check src tests scripts`,
  `uv run --locked ruff format --check src tests scripts`, `git diff --check`.
- [CI](.github/workflows/test-suite.yml)의 Linux x86_64 kernel-isolation proof를 Mac 결과나 mock으로 대체하지 않는다.
  `repo_history` 검사는 실제 Git history가 필요하다.
  환경 때문에 실패·skip한 검사는 별도 보고하고 green을 위해 guard/test를 삭제하거나 임의 제외하지 않는다.
- 상태 전이 시 live banner와 readiness를 정합화하되 역사 기록은 유지한다. 문서 링크는 stable
  `CLAUDE.md#...` anchor를 사용하며 미래 artifact의 부재를 감추려 파일을 꾸며내지 않는다.
- 완료 보고는 변경·이유·실행한 검사와 결과·미실행 검사/남은 blocker를 담는다.
  Scientific 결과는 protocol/run identity·근거 artifact를 연결한다. Local 성공은 release/scientific 성공이 아니다.

<!-- 유지보수: 공통 진입 지침만 유지하고 scientific 규칙·skill 절차를 중복 정의하지 않는다.
Codex 발견/적용 방식: https://learn.chatgpt.com/docs/agent-configuration/agents-md
Skill 역할: https://learn.chatgpt.com/docs/customization/overview -->
