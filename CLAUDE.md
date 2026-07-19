# ALIVE — Virtual Cell Project Governance

> **역할:** project-wide scientific governance + agent operating contract
> **개정일:** 2026-07-19
> **protocol lifecycle:** `COMPOSE-K562-v1` ACTIVE · `TG-K562-v1` COMPLETE · `CT-RPE1-v1` DEFERRED
> **execution readiness:** COMPOSE **RELEASE-BLOCKED** · seal **UNOPENED**
> **다음 gate:** `docs/superpowers/COMPOSE-SEAL-READINESS.md`의 blocker와 owner release gate를 모두 충족

이 파일은 매 세션 전체가 context에 들어간다. 모든 작업에 필요한 불변식과 운영 규칙만 두며, 자주 바뀌는
진행 상태와 milestone 세부는 versioned spec/plan/config/readiness/runbook이 정의한다. 경로별 세부는
`.claude/rules/`에 둔다. 새 threshold·seed·metric·roster·실행 절차를 이 파일에 복제하지 않는다.

## 1. Sources of truth & 충돌 처리 {#sources}

도메인별 우선순위:

1. Safety · seal · leakage · governance invariant → 이 파일
2. Scientific claim · estimand · non-claim → milestone design spec
3. Execution contract · task order → implementation plan/runbook
4. Exact split · threshold · seed · metric · roster → committed protocol/config/data card
5. Runtime behavior → `src/alive/`
6. Current release readiness → `docs/superpowers/COMPOSE-SEAL-READINESS.md`
7. Vision/evidence/long-range → `virtual-cell-model-blueprint.md` · `virtual-cell-research-report.md` ·
   `virtual-cell-project-plan.md`

Safety invariant와 claim/config가 충돌하면 safety가 우선한다. 충돌을 발견하면 (1) 충돌과 affected protocol/
invariant를 보고하고, (2) scientific run을 시작·계속하지 않으며, (3) owner가 authoritative 문서를
reconcile하게 하고, (4) 변경된 lineage에는 새 run identity를 사용한다. 편리한 쪽을 조용히 선택하지 않는다.

## 2. Mission과 claim 경계 {#mission}

ALIVE는 단계적으로 causal virtual-cell world model을 구축한다:

$$p(X_{post}\mid P_{control}, A, C)$$

$P_{control}$은 control-cell population, $A$는 intervention/perturbation, $C$는 context,
$X_{post}$는 post-intervention cell-population distribution이다. 개별 protocol의 modality와 dataset은
그 spec/config/data card가 정하며 CRISPRi·CRISPRa 또는 서로 다른 dataset을 상호 대체하지 않는다.

현재 근거 없이 mechanistic · causal · temporally resolved · clinically predictive ·
distribution-valued prediction-set · Active Cartographer라고 주장하지 않는다. additive/bilinear 결과를
deep virtual-cell 성과로 표현하지 않고, split이 직접 검증하지 않은 context/target 일반화를 주장하지 않는다.

## 3. Universal scientific invariants {#invariants}

1. **Protocol first.** train/tune/eval 전에 protocol, manifest, estimand, primary metric, comparator family,
   failure condition을 version-control한다.
2. **Baseline first.** learned model 결과를 보기 전에 registered baseline과 evaluation harness를 구현한다.
3. **Seal outcomes.** evaluation outcome은 selection freeze 뒤 authorized evaluation code에서만 접근한다.
4. **Fit on allowed roles only.** normalization·selection·embedding·calibration·hyperparameter·threshold는
   protocol이 허용한 role만 사용한다.
5. **No outcome-selected evaluation set.** universe와 exclusion은 metadata·external-feature availability·
   사전등록 QC로 정하며 response strength나 base error로 고르지 않는다.
6. **Split at the claim unit.** perturbation claim은 perturbation ID/pair로 split한다. cell-barcode split으로
   unseen-perturbation claim을 만들지 않는다.
7. **Match claim to split.** K562-internal·shared-target·pair-zero-shot 결과를 각각 new-context·unseen-target·
   gene-zero-shot 증거로 확대하지 않는다.
8. **Risk is measured outcome error.** routing utility를 자기 confidence/bound/threshold로 평가하지 않는다.
9. **Coverage is table stakes.** calibration validity만으로 routing novelty를 주장하지 않는다.
10. **No single-metric win.** primary/registered secondary metric, effect size, claim-unit CI, seed variability,
    failed run을 함께 보고한다.
11. **Interrogate systematic variation.** batch·cell cycle·panel bias·common shift·mean collapse를 점검한다.
12. **Do not overclaim heterogeneity.** outcome-independent 정의와 noise audit 없이 responder/multimodality를
    주장하지 않는다.
13. **Uncertainty needs a method.** raw variance를 aleatoric/epistemic uncertainty로 부르지 않고 estimator,
    calibration role, coverage event를 명시한다.
14. **Negative results are results.** futility·calibration failure·invalid evaluation·no-distinct-win을 삭제,
    대체하거나 threshold를 사후 변경하지 않는다.
15. **Define the experimental unit.** biological unit과 technical replicate를 구분하고 exact N과 반복 구조를
    manifest/report에 기록한다.
16. **Pre-register adequacy and exclusions.** sample size/power 또는 detectable-effect 근거, inclusion/exclusion,
    outlier, missing-data 정책을 outcome 접근 전에 고정한다.
17. **Separate exploratory from confirmatory.** planned/unplanned analysis를 표시하고 exploratory 결과를
    confirmatory verdict로 승격하지 않는다.
18. **Report transparently.** effect size·CI·exact N·반복 횟수·제외/누락 사유·측정했지만 보고하지 않은
    outcome과 근거 수준을 남긴다.

## 4. Seal, provenance & enforcement {#seal-immutability}

### 4.1 Seal 원칙 {#seal}

- evaluation outcome은 selection freeze 후 protocol당 정확히 한 번 연다.
- fit/develop/calibrate/PREPARE 단계의 sealed access count는 0이어야 한다.
- futility-stopped run은 count 0으로 영구 종료한다. futility는 negative verdict가 아니다.
- protocol별 seal/run ID/audit/result는 상호 대체하지 않는다. cross-protocol 비교는 immutable artifact를
  입력으로 받는 별도 analysis다.

### 4.2 Run identity & write-once {#provenance}

모든 run은 protocol/version, resolved config, data/data-card/manifest/exclusion/feature hashes, seed, Git SHA,
dependency lock, device/precision, stage checksum, seal audit, report checksum을 기록한다. Existing run을
덮어쓰지 않고, byte-identical upstream에서만 resume하며, terminal/seal 이후 upstream을 재실행하지 않는다.
lineage가 달라지면 새 run identity를 사용한다.

### 4.3 실제 강제 지점 {#enforcement}

이 파일은 규범을 제공하는 context이며 자체로 보안 경계가 아니다. 아래 guard가 계약을 집행한다. 우회·약화·
mock 대체하지 않는다. guard가 작업을 막으면 코드를 완화하지 말고 충돌 절차를 따른다.

- protocol-global scientific seal → `compose/driver/seal_boundary.py`, `run_spec.py`, `phase2b_cmd.py`
- sealed-read 차단·1회 claim → `compose/outcome_store.py` (`ComposeSealingError`)
- leakage/freeze wall → `compose/gates.py`, `compose/freeze.py`
- write-once/durable terminal → `io.atomic_write_once`, `compose/durable.py`, `compose/terminal.py`
- entry/identity/pair audit → `compose/preflight.py`, `compose/driver/confirmation.py`, `pair_index.py`

## 5. Protocol registry {#registry}

- **`TG-K562-v1` — COMPLETE.** Replogle K562 CRISPRi Trust-Gate; seal opened once; verdict
  `NO_DISTINCT_WIN`. Spec `docs/superpowers/specs/2026-06-20-cartographer-design.md`.
- **`COMPOSE-K562-v1` — ACTIVE / RELEASE-BLOCKED / seal UNOPENED.** Norman K562 CRISPRa pair-level
  bilinear GI operator. Spec `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md`;
  config `configs/compose_k562_v1_phase2.yaml`; readiness `docs/superpowers/COMPOSE-SEAL-READINESS.md`.
- **`CT-RPE1-v1` — DEFERRED.** K562→RPE1 shared-target context transfer. 별도 owner approval, spec/config,
  manifest, leakage/power analysis, outcome store/audit가 생기기 전에는 활성화하거나 perturbed outcome에
  접근하지 않는다.

COMPOSE의 2026-06-30 lifecycle activation은 유지되지만 현재 committed evidence/config는 release-ready가
아니다. Current `ActivationRecord`, finalized config/evidence, clean owner-approved SHA와 runbook release gate가
모두 유효하기 전에는 real fit·sealed run을 실행하지 않는다. 미래 protocol은 각각 고유 이름, spec, seal,
success criteria를 요구한다.

## 6. Data · model · evaluation governance {#data-eval}

**Data.** Source/modality/cell line/assay/endpoint/license/checksum/schema는 active config와 data card로 확인한다.
raw counts와 transformation provenance를 보존하고 sparse/on-disk/chunked access를 사용하며 bounded slice만
densify한다. Cell line/dataset/external biological resource identity를 검증한다. Raw/processed data,
checkpoint, credential, identifiable donor data를 commit하지 않는다. Transfer 전 size·destination·license·
privacy를 확인한다. External-feature eligibility와 ambiguous/missing ID 정책은 split 전에 고정한다.

**Model / feature.** 요청 encoder 실패를 mock으로 조용히 대체하지 않는다(mock은 synthetic/CI 전용).
revision·dimension·pooling·sequence/ontology release를 기록한다. 새 deep architecture/operator/decoder는 별도
spec, strongest baseline, ablation이 필요하다. Biological prior encoder(gene/pathway/network)는 ID-only null
baseline과 ablation해 marginal signal을 격리한다. Population sample 출력만으로 heterogeneity 학습을 주장하지
않고 pseudobulk·self-distance/noise floor·mean-collapse diagnostic를 유지한다.

**Evaluation.** Comparator roster와 protocol을 outcome 전에 freeze한다. Metric 방향·scientific event를
명시하고 known-answer/constant/shuffled/random sanity를 둔다. Comparator-family selection을 반영한
simultaneous inference를 사용한다. Per-target/null behavior, biological/distributional regression margin,
noise ceiling, failed run을 보고한다. Prospective validation은 별도 milestone이다.

## 7. Repository, commands & compute {#repo}

```text
src/alive/      maintained library and CLI
configs/        immutable experiment configuration inputs
tests/          unit, leakage, metric, provenance, integration tests
scripts/        thin entry points; production logic remains in src/
docs/           specs, plans, runbooks, readiness, immutable evidence/audits
artifacts/      gitignored run outputs
```

```bash
uv sync
uv run pytest -q <target>
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

Python version은 `pyproject.toml`, dependency는 committed `uv.lock`을 따른다. Public API는 type hint와
NumPy-style docstring을 사용한다. Production source에 path·split·threshold·feature list·seed·hyperparameter를
hardcode하지 않는다. Notebook은 library function만 호출한다. Scientific run 명령은 추측하지 말고 current
runbook/CLI help를 확인한다.

**Compute.** {#compute} Local Mac은 setup·unit/mini/synthetic·bounded inspection용, A100/pod는 승인된 real-data
preparation과 full run용이다. Mini/full은 같은 production code와 다른 config만 사용한다. Device fallback을
숨기지 않고 ephemeral disk를 유일본으로 쓰지 않는다. Cloud run은 instance/GPU, image/lock, input hash,
Git SHA, config, wall time, cost를 기록한다.

## 8. Agent operating contract {#agent}

- Inspect before editing. Active protocol과 affected invariant를 먼저 식별하고 unrelated user change를 보존한다.
- Established protocol/config/evidence를 조용히 rewrite하지 않는다. Config field 변경은 새 run identity다.
- 현재 hypothesis를 falsify할 가장 작은 실험을 우선하고, 좋은 결과일수록 leakage·confounding·collapse·
  metric gaming·seed sensitivity를 먼저 검사한다.
- Evidence level과 uncertainty를 명시한다. Preprint/vendor/model-generated claim을 ground truth로 취급하지 않는다.
- COMPOSE는 RELEASE-BLOCKED다. Readiness/runbook이 READY이고 owner가 exact SHA를 승인하기 전에는 sealed run을
  시작하지 않는다.

**완료 전 검증.** {#verify} Targeted unit → applicable integration → Ruff → data/eval 변경 시 leakage → metric
변경 시 known-answer/constant/shuffled/random → artifact/provenance 변경 시 tamper/resume. 실행 명령, 결과,
skip, 미완 검사를 보고한다. Scientific run 전 spec/plan/config/runtime contract audit를 수행하며 문서와 코드가
충돌하면 test가 통과해도 run을 시작하지 않는다.

## 9. Governance summary {#summary}

```text
RULE: claim · split · seal · manifest · run identity · report는 protocol 간 상호 교환 불가.
STATE: COMPOSE ACTIVE, RELEASE-BLOCKED, seal UNOPENED. Readiness gate가 READY가 되기 전 실행 금지.
```

<!-- maintainer: root는 200줄 미만의 always-on invariant만 유지한다. 상태 전이는 header/registry와 readiness를
동시에 갱신하고, 세부 규칙은 path-scoped rule/spec/config/runbook에 둔다. -->
